"""Owned Windows process groups; closing the owner kills all descendants.

Assign workers before releasing their startup gate. Handles are deliberately
non-inheritable, so a worker cannot keep its own lifetime guard alive.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import time


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in (
        "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime",
    )] + [(name, wintypes.DWORD) for name in (
        "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses",
    )]


class WindowsJob:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows Job Objects require Windows")
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "GetCurrentProcess": ([], wintypes.HANDLE),
            "DuplicateHandle": ([wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self._api, name)
            function.argtypes, function.restype = args, result
        self._handle = self._api.CreateJobObjectW(None, None)
        self._check(self._handle)
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway.
        try:
            self._check(self._api.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits),
            ))
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def assign(self, process_handle: int) -> None:
        self._check(self._api.AssignProcessToJobObject(self._handle, process_handle))

    def transfer_to_owner(self, owner_pid: int) -> None:
        """Put this host in the Job and give its sole handle to the desktop.

        Windows closes that handle even when the desktop is forcibly killed.
        The host's separate child Job guards backend death when the host itself
        is killed first. Neither guarantee depends on a Python exit callback.
        """
        owner = self._check(self._api.OpenProcess(0x0040, False, owner_pid))  # PROCESS_DUP_HANDLE
        try:
            self.assign(self._api.GetCurrentProcess())
            remote = wintypes.HANDLE()
            self._check(self._api.DuplicateHandle(
                self._api.GetCurrentProcess(), self._handle, owner, ctypes.byref(remote),
                0, False, 0x00000002,  # DUPLICATE_SAME_ACCESS, non-inheritable
            ))
            self.close()  # Desktop now owns the only remaining handle.
        finally:
            self._api.CloseHandle(owner)

    @property
    def active_processes(self) -> int:
        accounting = _Accounting()
        self._check(self._api.QueryInformationJobObject(
            self._handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None,
        ))
        return accounting.ActiveProcesses

    def terminate(self, timeout: float = 2.0) -> None:
        self._check(self._api.TerminateJobObject(self._handle, 1))
        deadline = time.monotonic() + timeout
        while self.active_processes:
            if time.monotonic() >= deadline:
                raise TimeoutError("Windows has not confirmed all execution processes exited")
            time.sleep(0.01)

    def close(self) -> None:
        if self._handle:
            self._check(self._api.CloseHandle(self._handle))
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
