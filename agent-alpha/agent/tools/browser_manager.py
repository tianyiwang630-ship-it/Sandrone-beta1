from __future__ import annotations

import json
import locale
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.tools.process_utils import subprocess_group_kwargs, terminate_process_tree


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_process_text(path: Path) -> str:
    data = path.read_bytes()
    if not data:
        return ""
    encodings = ["utf-8", locale.getpreferredencoding(False), "gbk"]
    for encoding in dict.fromkeys(item for item in encodings if item):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


@dataclass(slots=True)
class BrowserSession:
    session_id: str
    mode: str
    profile: str | None
    cdp_url: str | None = None
    profile_dir: Path | None = None
    runtime_dir: Path | None = None


class BrowserManager:
    """Small state manager and agent-browser CLI wrapper."""

    def __init__(self, project_root: Path | None = None, interrupt_event: threading.Event | None = None):
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.interrupt_event = interrupt_event
        self.root = self.project_root / "state" / "browser"
        self.profiles_dir = self.root / "profiles"
        self.sessions_dir = self.root / "sessions"
        self.sockets_dir = self.root / "sockets"
        self.downloads_dir = self.root / "downloads"
        self.runtime_dir = self.root / "runtime"
        self.registry_path = self.root / "profiles.json"
        self.active_sessions: dict[str, BrowserSession] = {}
        self.current_session_id: str | None = None
        self._ensure_dirs()
        self._cleanup_stale_browser_state()
        self.ensure_profile("default")

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.interrupt_event = interrupt_event

    def _ensure_dirs(self) -> None:
        for path in [
            self.root,
            self.profiles_dir,
            self.sessions_dir,
            self.sockets_dir,
            self.downloads_dir,
            self.runtime_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def _remove_children(self, path: Path) -> None:
        if not path.exists():
            return
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass

    def _cleanup_stale_browser_state(self) -> None:
        for path in [self.runtime_dir, self.sessions_dir, self.sockets_dir]:
            self._remove_children(path)
            path.mkdir(parents=True, exist_ok=True)
        if not self.profiles_dir.exists():
            return
        for lock_file in self.profiles_dir.glob("*/.headed.lock"):
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass

    def _read_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"profiles": {}}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return {"profiles": {}}
        if not isinstance(data, dict):
            return {"profiles": {}}
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            data["profiles"] = {}
        return data

    def _write_registry(self, data: dict[str, Any]) -> None:
        self.registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _validate_profile_name(self, name: str) -> str:
        value = (name or "").strip()
        if not value:
            raise ValueError("profile name cannot be empty")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if any(ch not in allowed for ch in value):
            raise ValueError("profile name may contain only letters, numbers, '_' and '-'")
        return value

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.project_root).as_posix()

    def ensure_profile(self, name: str, description: str = "") -> dict[str, Any]:
        profile_name = self._validate_profile_name(name)
        data = self._read_registry()
        profiles = data["profiles"]
        if profile_name in profiles:
            profile_dir = self.profiles_dir / profile_name
            user_data_dir = profile_dir / "user-data"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            item = profiles[profile_name]
            changed = False
            if "profile_dir" not in item:
                item["profile_dir"] = self._relative_path(user_data_dir)
                changed = True
            if "state_file" not in item:
                item["state_file"] = self._relative_path(profile_dir / "state.json")
                changed = True
            if changed:
                self._write_registry(data)
            return profiles[profile_name]

        profile_dir = self.profiles_dir / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = profile_dir / "user-data"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        state_file = profile_dir / "state.json"
        profiles[profile_name] = {
            "name": profile_name,
            "kind": "persistent",
            "description": description,
            "profile_dir": self._relative_path(user_data_dir),
            "state_file": self._relative_path(state_file),
            "created_at": _utc_now(),
            "last_used_at": None,
        }
        self._write_registry(data)
        return profiles[profile_name]

    def list_profiles(self) -> list[dict[str, Any]]:
        data = self._read_registry()
        return list(data["profiles"].values())

    def _profile_state_file(self, profile: str) -> Path:
        item = self.ensure_profile(profile)
        return self.project_root / item["state_file"]

    def _profile_dir(self, profile: str) -> Path:
        item = self.ensure_profile(profile)
        return self.project_root / item["profile_dir"]

    def _profile_lock_file(self, profile: str) -> Path:
        return self.profiles_dir / profile / ".headed.lock"

    def _lock_profile_for_headed(self, profile: str, session_id: str) -> dict[str, Any] | None:
        lock_file = self._profile_lock_file(profile)
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"session_id": session_id, "created_at": _utc_now()}, ensure_ascii=False)
        try:
            with lock_file.open("x", encoding="utf-8") as handle:
                handle.write(payload)
        except FileExistsError:
            return {
                "success": False,
                "error": f"profile '{profile}' is locked by a headed browser session; close it before starting another browser run.",
                "lock_file": str(lock_file),
            }
        return None

    def _unlock_profile(self, profile: str | None) -> None:
        if not profile:
            return
        lock_file = self._profile_lock_file(profile)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            return

    def _copy_runtime_profile_once(self, source: Path, runtime: Path, target: Path) -> None:
        if runtime.exists():
            shutil.rmtree(runtime)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)

    def _prepare_runtime_profile(self, session: BrowserSession) -> dict[str, Any] | None:
        if not session.profile:
            return None
        source = self._profile_dir(session.profile)
        runtime = self.runtime_dir / session.session_id
        target = runtime / "user-data"
        self._unlock_profile(session.profile)
        try:
            self._copy_runtime_profile_once(source, runtime, target)
        except OSError as first_error:
            self._cleanup_alpha_browser_processes()
            self._unlock_profile(session.profile)
            if runtime.exists():
                shutil.rmtree(runtime, ignore_errors=True)
            try:
                self._copy_runtime_profile_once(source, runtime, target)
            except OSError as second_error:
                return {
                    "success": False,
                    "error": (
                        "default profile is still locked by an alpha browser process; "
                        "close alpha browser windows and retry."
                    ),
                    "first_error": str(first_error),
                    "second_error": str(second_error),
                    "profile": session.profile,
                    "profile_dir": str(source),
                    "runtime_dir": str(runtime),
                }
        session.profile_dir = target
        session.runtime_dir = runtime
        return None

    def _normalized_path_text(self, value: Path | str) -> str:
        return str(value).replace("\\", "/").lower()

    def _is_alpha_browser_command(self, command_line: str | None) -> bool:
        if not command_line:
            return False
        normalized_command = self._normalized_path_text(command_line)
        marker = self._normalized_path_text(self.root.resolve())
        start = normalized_command.find(marker)
        if start < 0:
            return False
        end = start + len(marker)
        if end >= len(normalized_command):
            return True
        return normalized_command[end] in {"/", '"', "'", " ", "\t", "\r", "\n"}

    def _cleanup_alpha_browser_processes(self) -> int:
        if os.name == "nt":
            return self._cleanup_alpha_browser_processes_windows()
        return self._cleanup_alpha_browser_processes_posix()

    def _cleanup_alpha_browser_processes_windows(self) -> int:
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('chrome.exe','chromium.exe','msedge.exe','agent-browser-win32-x64.exe') } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return 0
        output = (proc.stdout or "").strip()
        if not output:
            return 0
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return 0
        items = data if isinstance(data, list) else [data]
        stopped = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            command_line = str(item.get("CommandLine") or "")
            if not self._is_alpha_browser_command(command_line):
                continue
            try:
                pid = int(item["ProcessId"])
            except (KeyError, TypeError, ValueError):
                continue
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode == 0:
                stopped += 1
        return stopped

    def _cleanup_alpha_browser_processes_posix(self) -> int:
        try:
            proc = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return 0
        stopped = 0
        for line in (proc.stdout or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            pid_text, _, command_line = stripped.partition(" ")
            if not self._is_alpha_browser_command(command_line):
                continue
            try:
                os.kill(int(pid_text), signal.SIGTERM)
            except (OSError, ValueError):
                continue
            stopped += 1
        return stopped

    def _touch_profile(self, profile: str) -> None:
        data = self._read_registry()
        item = data["profiles"].get(profile)
        if item:
            item["last_used_at"] = _utc_now()
            self._write_registry(data)

    def _command_prefix(self) -> list[str]:
        found = shutil.which("agent-browser")
        if found:
            native = self._native_agent_browser_exe(found)
            return [str(native or found)]
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        return [npx, "-y", "agent-browser@latest"]

    def _native_agent_browser_exe(self, command_path: str) -> Path | None:
        path = Path(command_path)
        if os.name != "nt" or path.suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            return None
        candidates = [
            path.parent / "node_modules" / "agent-browser" / "bin" / "agent-browser-win32-x64.exe",
            path.parent.parent / "agent-browser" / "bin" / "agent-browser-win32-x64.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _runtime_env_value(self, key: str) -> str:
        profile_path = self.project_root / "config" / "runtime_env.local.json"
        if not profile_path.exists():
            return ""
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        value = data.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _configured_browser_executable_path(self) -> str:
        return (os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH") or "").strip() or self._runtime_env_value(
            "AGENT_BROWSER_EXECUTABLE_PATH"
        )

    def browser_executable_info(self) -> dict[str, Any]:
        configured = self._configured_browser_executable_path()
        if not configured:
            return {"mode": "agent_browser_default", "fallback": False}
        executable = Path(configured)
        if executable.is_file():
            return {
                "mode": "configured",
                "path": str(executable),
                "exists": True,
                "fallback": False,
            }
        return {
            "mode": "agent_browser_default",
            "configured_path": configured,
            "exists": False,
            "fallback": True,
            "warning": "Configured Chrome path was not found; fell back to agent-browser default browser.",
        }

    def _browser_env(self) -> dict[str, str]:
        env = dict(os.environ)
        info = self.browser_executable_info()
        if info.get("mode") == "configured" and info.get("path"):
            env["AGENT_BROWSER_EXECUTABLE_PATH"] = str(info["path"])
        else:
            env.pop("AGENT_BROWSER_EXECUTABLE_PATH", None)
        return env

    def _session_args(self, session: BrowserSession, *, headed: bool = False) -> list[str]:
        args: list[str] = []
        if session.cdp_url:
            args.extend(["--cdp", session.cdp_url])
        else:
            args.extend(["--session", session.session_id])
            if session.profile_dir:
                args.extend(["--profile", str(session.profile_dir)])
        if headed:
            args.append("--headed")
        args.append("--json")
        return args

    def _run_cli(
        self,
        session: BrowserSession,
        command_args: list[str],
        *,
        timeout: int = 60,
        headed: bool = False,
    ) -> dict[str, Any]:
        socket_dir = self.sockets_dir / session.session_id
        socket_dir.mkdir(parents=True, exist_ok=True)
        download_dir = self.downloads_dir / session.session_id
        download_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = socket_dir / "_stdout.txt"
        stderr_path = socket_dir / "_stderr.txt"
        cmd = self._command_prefix() + self._session_args(session, headed=headed) + command_args
        env = self._browser_env()
        env["AGENT_BROWSER_SOCKET_DIR"] = str(socket_dir)
        env["AGENT_BROWSER_DOWNLOAD_PATH"] = str(download_dir)

        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            popen_kwargs: dict[str, Any] = subprocess_group_kwargs()
            if os.name == "nt":
                popen_kwargs["creationflags"] = 0x08000000
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=env,
                **popen_kwargs,
            )
            started_at = time.monotonic()
            while proc.poll() is None:
                if self.interrupt_event is not None and self.interrupt_event.is_set():
                    terminate_process_tree(proc)
                    self._wait_after_stop(proc)
                    return {
                        "success": False,
                        "interrupted": True,
                        "error": "agent-browser command interrupted by ESC",
                    }
                if time.monotonic() - started_at > timeout:
                    terminate_process_tree(proc)
                    self._wait_after_stop(proc)
                    return {"success": False, "error": f"agent-browser command timed out after {timeout}s"}
                time.sleep(0.05)

        stdout_text = _read_process_text(stdout_path).strip()
        stderr_text = _read_process_text(stderr_path).strip()
        if not stdout_text:
            if proc.returncode == 0:
                return {"success": True, "data": {}}
            return {"success": False, "error": stderr_text or f"agent-browser exited with {proc.returncode}"}

        try:
            result = json.loads(stdout_text.splitlines()[-1])
            if isinstance(result, dict):
                result.setdefault("browser_executable", self.browser_executable_info())
            return result
        except json.JSONDecodeError:
            return {
                "success": proc.returncode == 0,
                "raw": stdout_text,
                "stderr": stderr_text,
                "browser_executable": self.browser_executable_info(),
            }

    def _new_session(
        self,
        mode: str,
        profile: str | None,
        cdp_url: str | None = None,
        profile_dir: Path | None = None,
    ) -> BrowserSession:
        base = profile or "cdp"
        session_id = f"aa_{mode.replace('-', '_')}_{base}_{uuid.uuid4().hex[:8]}"
        session = BrowserSession(
            session_id=session_id,
            mode=mode,
            profile=profile,
            cdp_url=cdp_url,
            profile_dir=profile_dir,
        )
        self.active_sessions[session_id] = session
        self.current_session_id = session_id
        return session

    def _get_session(self, session_id: str | None = None) -> BrowserSession | None:
        if session_id:
            return self.active_sessions.get(session_id)
        if self.current_session_id:
            return self.active_sessions.get(self.current_session_id)
        return None

    def _load_profile_state(self, session: BrowserSession) -> dict[str, Any] | None:
        if not session.profile or session.cdp_url:
            return None
        state_file = self._profile_state_file(session.profile)
        if not state_file.exists():
            return None
        return self._run_cli(session, ["state", "load", str(state_file)], timeout=30)

    def start_headless(self, url: str, profile: str = "default", session_id: str | None = None) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session is None:
            self.ensure_profile(profile)
            session = self._new_session("local-headless", profile)
            copy_error = self._prepare_runtime_profile(session)
            if copy_error:
                self.active_sessions.pop(session.session_id, None)
                if self.current_session_id == session.session_id:
                    self.current_session_id = next(iter(self.active_sessions), None)
                return copy_error
        result = self._run_cli(session, ["open", url], timeout=60)
        snapshot = self._run_cli(session, ["snapshot", "-i"], timeout=60)
        self._touch_profile(profile)
        persistent_profile_dir = self._profile_dir(profile)
        return {
            "success": bool(result.get("success", result.get("data") is not None)),
            "session_id": session.session_id,
            "profile": profile,
            "profile_dir": str(persistent_profile_dir),
            "runtime_profile_dir": str(session.profile_dir) if session.profile_dir else None,
            "mode": session.mode,
            "browser_executable": self.browser_executable_info(),
            "open": result,
            "snapshot": snapshot,
        }

    def start_headed_login(self, profile: str = "default", url: str = "about:blank") -> dict[str, Any]:
        self.ensure_profile(profile)
        profile_dir = self._profile_dir(profile)
        session = self._new_session("local-headed-login", profile, profile_dir=profile_dir)
        lock_error = self._lock_profile_for_headed(profile, session.session_id)
        if lock_error:
            self.active_sessions.pop(session.session_id, None)
            if self.current_session_id == session.session_id:
                self.current_session_id = next(iter(self.active_sessions), None)
            return lock_error
        result = self._run_cli(session, ["open", url], timeout=60, headed=True)
        self._touch_profile(profile)
        return {
            "success": bool(result.get("success", result.get("data") is not None)),
            "session_id": session.session_id,
            "profile": profile,
            "profile_dir": str(profile_dir),
            "mode": session.mode,
            "browser_executable": self.browser_executable_info(),
            "result": result,
            "next_step": "After manual login, call browser_close. The Chrome profile directory persists automatically.",
        }

    def connect_cdp(self, cdp_url: str) -> dict[str, Any]:
        value = (cdp_url or "").strip()
        if not value:
            return {"success": False, "error": "cdp_url is required"}
        session = self._new_session("external-cdp", None, cdp_url=value)
        status = self._run_cli(session, ["get", "url"], timeout=30)
        return {
            "success": True,
            "session_id": session.session_id,
            "mode": session.mode,
            "cdp_url": value,
            "status": status,
        }

    def run_current(self, command_args: list[str], session_id: str | None = None, timeout: int = 60) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session is None:
            return {"success": False, "error": "No active browser session. Call browser_navigate or browser_connect_cdp first."}
        result = self._run_cli(session, command_args, timeout=timeout)
        result.setdefault("session_id", session.session_id)
        result.setdefault("mode", session.mode)
        return result

    def close(self, session_id: str | None = None, save_profile: bool | None = None) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session is None:
            return {"success": False, "error": "No active browser session to close."}

        should_save = bool(save_profile)
        if save_profile is None and session.mode == "local-headed-login":
            should_save = True

        saved = None
        if should_save and session.profile and not session.cdp_url:
            saved = {
                "success": True,
                "method": "profile_dir",
                "path": str(session.profile_dir or self._profile_dir(session.profile)),
            }

        closed = self._run_cli(session, ["close"], timeout=30)
        temporary_profile_removed = None
        if session.runtime_dir:
            temporary_profile_removed = False
            if session.runtime_dir.exists():
                shutil.rmtree(session.runtime_dir)
                temporary_profile_removed = True
        if session.mode == "local-headed-login":
            self._unlock_profile(session.profile)
        self.active_sessions.pop(session.session_id, None)
        if self.current_session_id == session.session_id:
            self.current_session_id = next(iter(self.active_sessions), None)
        return {
            "success": bool(closed.get("success", True)),
            "session_id": session.session_id,
            "profile": session.profile,
            "mode": session.mode,
            "saved": saved,
            "closed": closed,
            "temporary_profile_removed": temporary_profile_removed,
        }

    def status(self) -> dict[str, Any]:
        return {
            "success": True,
            "current_session_id": self.current_session_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "mode": item.mode,
                    "profile": item.profile,
                    "cdp_url": item.cdp_url,
                }
                for item in self.active_sessions.values()
            ],
        }

    def _wait_after_stop(self, proc: subprocess.Popen[Any]) -> None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


_MANAGERS: dict[Path, BrowserManager] = {}


def get_browser_manager(project_root: Path | None = None) -> BrowserManager:
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    manager = _MANAGERS.get(root)
    if manager is None:
        manager = BrowserManager(root)
        _MANAGERS[root] = manager
    return manager
