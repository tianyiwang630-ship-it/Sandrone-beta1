"""Real process tests: no model, network, or browser is started."""
import os
import subprocess
import sys
import multiprocessing
import time
import ctypes
from ctypes import wintypes

import pytest

from agent.core.windows_job import WindowsJob


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows lifecycle contract")


def gated_process(code):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline(); " + code],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


@pytest.mark.parametrize("new_process_group", [False, True])
def test_terminate_covers_descendants_and_preserves_other_job(new_process_group, tmp_path):
    flags = subprocess.CREATE_NO_WINDOW | (subprocess.CREATE_NEW_PROCESS_GROUP if new_process_group else 0)
    ready_path = tmp_path / "grandchild-ready.txt"
    child_code = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags={flags}); "
        f"Path({str(ready_path)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    with WindowsJob() as target, WindowsJob() as sibling:
        worker = gated_process(
            "import subprocess,time; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}],creationflags={flags}); "
            "print(p.pid,flush=True); time.sleep(60)"
        )
        other = gated_process("import time; print('ready',flush=True); time.sleep(60)")
        try:
            target.assign(int(worker._handle))
            sibling.assign(int(other._handle))
            for process in (worker, other):
                process.stdin.write("start\n")
                process.stdin.flush()
            assert worker.stdout.readline().strip().isdigit()
            deadline = time.monotonic() + 5
            while not ready_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready_path.exists(), "grandchild was not started"
            assert ready_path.read_text().isdigit()
            assert other.stdout.readline().strip() == "ready"
            # A venv Python launcher can add another process; every descendant
            # must belong to the Job, not just an assumed fixed process count.
            assert target.active_processes >= 3
            target.terminate()
            assert target.active_processes == 0
            worker.wait(timeout=3)
            assert other.poll() is None
            sibling.terminate()
        finally:
            target.terminate()
            sibling.terminate()
            for process in (worker, other):
                process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()


def test_close_last_handle_kills_worker():
    worker = gated_process("import time; print('ready',flush=True); time.sleep(60)")
    job = WindowsJob()
    try:
        job.assign(int(worker._handle))
        worker.stdin.write("start\n")
        worker.stdin.flush()
        assert worker.stdout.readline().strip() == "ready"
        job.close()
        # Kill-on-close can report exit code zero; exit before the 60s sleep
        # finishes is the contract, not the numeric process exit status.
        worker.wait(timeout=3)
        job.close()
    finally:
        job.close()
        worker.wait(timeout=3)
        worker.stdin.close()
        worker.stdout.close()


def sleeping_owner():
    time.sleep(60)


def owned_host(owner_pid, connection):
    application_job = WindowsJob()
    application_job.transfer_to_owner(owner_pid)
    with WindowsJob() as backend_job:
        child = gated_process("import time; print('ready',flush=True); time.sleep(60)")
        backend_job.assign(int(child._handle))
        child.stdin.write("start\n")
        child.stdin.flush()
        child.stdout.readline()
        connection.send(child.pid)
        time.sleep(60)


@pytest.mark.parametrize("kill_owner", [True, False])
def test_desktop_or_host_crash_cleans_backend_without_exit_callbacks(kill_owner):
    context = multiprocessing.get_context("spawn")
    parent, child_pipe = context.Pipe()
    owner = context.Process(target=sleeping_owner)
    owner.start()
    host = context.Process(target=owned_host, args=(owner.pid, child_pipe))
    host.start()
    child_pipe.close()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = None
    try:
        assert parent.poll(10), "host failed to establish ownership"
        pid = parent.recv()
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        assert handle
        (owner if kill_owner else host).terminate()
        host.join(timeout=3)
        assert not host.is_alive()
        assert kernel.WaitForSingleObject(handle, 3000) == 0
    finally:
        if handle:
            kernel.CloseHandle(handle)
        for process in (owner, host):
            if process.is_alive():
                process.terminate()
            process.join(timeout=3)
            process.close()
        parent.close()
