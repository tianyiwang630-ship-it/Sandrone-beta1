from __future__ import annotations

import ctypes
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


_BROWSER_NAMES = {"chrome", "chrome.exe", "chromium", "chromium.exe", "msedge", "msedge.exe"}


class BrowserProcessDiscoveryError(RuntimeError):
    """Raised when Alpha cannot safely determine ownership of browser processes."""


@dataclass(frozen=True)
class BrowserProcess:
    pid: int
    created: str
    command_line: str
    arguments: tuple[str, ...]

    @property
    def mode(self) -> str:
        return "cdp" if any(arg.startswith("--remote-debugging-port") for arg in self.arguments) else "manual"


class DedicatedBrowser:
    """Own the Chrome process whose exact user-data-dir is Alpha's private profile."""

    def __init__(self, profile_dir: Path, temp_dir: Path) -> None:
        self.profile_dir = profile_dir.resolve()
        self.temp_dir = temp_dir.resolve()

    def main_processes(self) -> list[BrowserProcess]:
        return [process for process in self._processes() if not self._is_child(process.arguments)]

    def current_mode(self) -> str | None:
        processes = self.main_processes()
        if not processes:
            return None
        modes = {process.mode for process in processes}
        return modes.pop() if len(modes) == 1 else "conflict"

    def port_belongs_to_profile(self, port: int) -> bool:
        if os.name != "nt":
            return bool(self._processes())
        owner = self._port_owner(port)
        return owner is not None and any(process.pid == owner for process in self._processes())

    def launch(self, executable: Path, mode: str) -> subprocess.Popen[Any]:
        command = [
            str(executable),
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if mode == "cdp":
            command.append("--remote-debugging-port=0")
        command.append("about:blank")
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def close(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
        targets = self.main_processes()
        if not targets:
            return {"success": True, "closed": False}
        if len(targets) != 1:
            return self._close_required("More than one Alpha browser main process was found.")
        target = targets[0]
        if not self._same_process_still_owned(target):
            return self._close_required("Alpha browser ownership changed before it could be closed.")
        if not self._post_close(target.pid):
            return self._close_required("Close the Alpha browser window, then retry.")
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            if not self._same_process_still_owned(target):
                return {"success": True, "closed": True}
            time.sleep(0.1)
        return self._close_required("The Alpha browser did not close. Close its dialog or window, then retry.")

    def disable_native_remote_debugging(self) -> dict[str, Any]:
        if self.main_processes():
            return {"success": False, "stage": "browser", "error": "Alpha browser must be closed before updating its settings."}
        local_state = self.profile_dir / "Local State"
        if not local_state.exists():
            return {"success": True, "changed": False}
        try:
            original = local_state.read_text(encoding="utf-8", errors="strict")
            payload = json.loads(original)
            if not isinstance(payload, dict):
                raise ValueError("root is not an object")
            devtools = payload.get("devtools")
            if not isinstance(devtools, dict):
                return {"success": True, "changed": False}
            remote = devtools.get("remote_debugging")
            if not isinstance(remote, dict) or remote.get("user-enabled") is not True:
                return {"success": True, "changed": False}
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            backup = self.temp_dir / "Local State.before-remote-debugging-disable.json"
            shutil.copy2(local_state, backup)
            remote["user-enabled"] = False
            handle, temporary_name = tempfile.mkstemp(prefix="Local State.", suffix=".tmp", dir=str(self.profile_dir))
            os.close(handle)
            temporary = Path(temporary_name)
            try:
                temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(temporary, local_state)
            finally:
                temporary.unlink(missing_ok=True)
            return {"success": True, "changed": True, "backup": str(backup)}
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return {"success": False, "stage": "browser", "error": f"Could not safely update Chrome Local State: {exc}"}

    def native_remote_debugging_enabled(self) -> bool:
        try:
            payload = json.loads((self.profile_dir / "Local State").read_text(encoding="utf-8", errors="strict"))
            return ((payload.get("devtools") or {}).get("remote_debugging") or {}).get("user-enabled") is True
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def _same_process_still_owned(self, expected: BrowserProcess) -> bool:
        return any(
            process.pid == expected.pid and process.created == expected.created
            for process in self.main_processes()
        )

    def _processes(self) -> list[BrowserProcess]:
        if os.name != "nt":
            return self._posix_processes()
        script = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$ErrorActionPreference='Stop'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('chrome.exe','chromium.exe','msedge.exe') } | "
            "Select-Object Name,ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                detail = (completed.stderr or "").strip()
                raise BrowserProcessDiscoveryError(
                    f"Windows process query failed with exit code {completed.returncode}"
                    + (f": {detail}" if detail else ".")
                )
            raw = json.loads((completed.stdout or "").strip() or "[]")
        except BrowserProcessDiscoveryError:
            raise
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise BrowserProcessDiscoveryError(f"Could not inspect Windows browser processes: {exc}") from exc
        items = raw if isinstance(raw, list) else [raw]
        return self._owned_processes(items)

    def _owned_processes(self, items: list[Any]) -> list[BrowserProcess]:
        result: list[BrowserProcess] = []
        for item in items:
            if not isinstance(item, Mapping) or str(item.get("Name") or "").lower() not in _BROWSER_NAMES:
                continue
            command_line = str(item.get("CommandLine") or "")
            arguments = tuple(self._split_command_line(command_line))
            if self._profile_argument(arguments) != self._normalized_path(self.profile_dir):
                continue
            try:
                pid = int(item.get("ProcessId"))
            except (TypeError, ValueError):
                continue
            result.append(BrowserProcess(pid, str(item.get("CreationDate") or ""), command_line, arguments))
        return result

    def _posix_processes(self) -> list[BrowserProcess]:
        try:
            completed = subprocess.run(
                ["ps", "-eo", "pid=,lstart=,args="], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return []
        items: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            parts = line.strip().split(None, 6)
            if len(parts) != 7:
                continue
            items.append({"Name": Path(parts[6].split()[0]).name, "ProcessId": parts[0], "CreationDate": " ".join(parts[1:6]), "CommandLine": parts[6]})
        return self._owned_processes(items)

    @staticmethod
    def _split_command_line(command_line: str) -> list[str]:
        if os.name != "nt":
            try:
                return shlex.split(command_line)
            except ValueError:
                return []
        argc = ctypes.c_int()
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        argv = shell32.CommandLineToArgvW(command_line, ctypes.byref(argc))
        if not argv:
            return []
        try:
            return [argv[index] for index in range(argc.value)]
        finally:
            kernel32.LocalFree(argv)

    def _profile_argument(self, arguments: tuple[str, ...]) -> str | None:
        for index, argument in enumerate(arguments):
            if argument.startswith("--user-data-dir="):
                return self._normalized_path(argument.split("=", 1)[1])
            if argument == "--user-data-dir" and index + 1 < len(arguments):
                return self._normalized_path(arguments[index + 1])
        return None

    @staticmethod
    def _is_child(arguments: tuple[str, ...]) -> bool:
        return any(argument == "--type" or argument.startswith("--type=") for argument in arguments)

    @staticmethod
    def _normalized_path(path: str | Path) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))

    @staticmethod
    def _post_close(pid: int) -> bool:
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        found = False
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def close_window(hwnd, _lparam):
            nonlocal found
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value == pid:
                found = True
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return True

        callback = callback_type(close_window)
        user32.EnumWindows(callback, 0)
        return found

    @staticmethod
    def _port_owner(port: int) -> int | None:
        script = (
            f"$c=Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess; if($c){$c}"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return int((completed.stdout or "").strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    @staticmethod
    def _close_required(message: str) -> dict[str, Any]:
        return {"success": False, "stage": "browser", "status": "close_required", "recoverable": True, "error": message}
