from __future__ import annotations

import json
import locale
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent.tools.process_utils import subprocess_group_kwargs, terminate_process_tree


COMPACT_BROWSER_SNAPSHOT_CHARS = 8000
COMPACT_BROWSER_SNAPSHOT_ITEMS = 80


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
        self.locks_dir = self.root / "locks"
        self.registry_path = self.root / "profiles.json"
        self.active_sessions: dict[str, BrowserSession] = {}
        self.owner_pid = os.getpid()
        self.owner_id = f"{self.owner_pid}-{uuid.uuid4().hex[:8]}"
        self.current_session_id: str | None = None
        self.current_headless_session_id: str | None = None
        self.current_headed_session_id: str | None = None
        self.current_cdp_session_id: str | None = None
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
            self.locks_dir,
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
        self._cleanup_dead_owner_sessions()
        self._refresh_interactive_lock()
        for lock_file in self.profiles_dir.glob("*/.headed.lock"):
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass

    def _session_metadata_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _session_socket_dir(self, session_id: str) -> Path:
        return self.sockets_dir / session_id

    def _session_runtime_dir(self, session_id: str) -> Path:
        return self.runtime_dir / session_id

    def _write_session_metadata(self, session: BrowserSession, status: str) -> None:
        payload = {
            "session_id": session.session_id,
            "mode": session.mode,
            "profile": session.profile,
            "cdp_url": session.cdp_url,
            "profile_dir": str(session.profile_dir) if session.profile_dir else None,
            "runtime_dir": str(session.runtime_dir) if session.runtime_dir else None,
            "owner_id": self.owner_id,
            "owner_pid": self.owner_pid,
            "project_root": str(self.project_root),
            "status": status,
            "updated_at": _utc_now(),
        }
        path = self._session_metadata_path(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _is_owner_process_alive(self, pid: int | str | None) -> bool:
        try:
            value = int(pid)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        if value <= 0:
            return False
        if value == os.getpid():
            return True
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {value}", "/FO", "CSV", "/NH"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                return True
            return str(value) in (result.stdout or "")
        try:
            os.kill(value, 0)
            return True
        except OSError:
            return False

    def _cleanup_dead_owner_sessions(self) -> None:
        if not self.sessions_dir.exists():
            return
        for session_file in self.sessions_dir.glob("*.json"):
            data = self._read_json_file(session_file)
            if not data:
                continue
            session_id = str(data.get("session_id") or session_file.stem)
            owner_pid = data.get("owner_pid")
            if owner_pid is None or self._is_owner_process_alive(owner_pid):
                continue
            for path in [self._session_runtime_dir(session_id), self._session_socket_dir(session_id)]:
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
            try:
                session_file.unlink()
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

    def _interactive_lock_file(self) -> Path:
        return self.locks_dir / "interactive.lock"

    def _profile_copy_lock_file(self) -> Path:
        return self.locks_dir / "profile-copy-default.lock"

    def _headless_base_dir(self, profile: str) -> Path:
        return self.profiles_dir / profile / "headless-base"

    def _headless_base_next_dir(self, profile: str) -> Path:
        return self.profiles_dir / profile / "headless-base.next"

    def _headed_state_dir(self, profile: str) -> Path:
        return self.profiles_dir / profile / "headed-state"

    def _headed_state_file(self, profile: str = "default") -> Path:
        return self._headed_state_dir(profile) / f"{self.owner_id}.json"

    def _read_interactive_lock(self) -> dict[str, Any] | None:
        return self._read_json_file(self._interactive_lock_file())

    def _write_interactive_lock(self, payload: dict[str, Any]) -> None:
        path = self._interactive_lock_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload.setdefault("owner_id", self.owner_id)
        payload.setdefault("owner_pid", self.owner_pid)
        payload.setdefault("project_root", str(self.project_root))
        payload.setdefault("created_at", _utc_now())
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _try_create_interactive_lock(self, payload: dict[str, Any]) -> bool:
        path = self._interactive_lock_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload.setdefault("owner_id", self.owner_id)
        payload.setdefault("owner_pid", self.owner_pid)
        payload.setdefault("project_root", str(self.project_root))
        payload.setdefault("created_at", _utc_now())
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return True
        except FileExistsError:
            return False

    def _remove_interactive_lock(self) -> None:
        try:
            self._interactive_lock_file().unlink()
        except FileNotFoundError:
            pass

    @contextmanager
    def _profile_copy_lock(self, timeout: float = 60.0) -> Iterator[None]:
        path = self._profile_copy_lock_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "owner_id": self.owner_id,
                "owner_pid": self.owner_pid,
                "project_root": str(self.project_root),
                "created_at": _utc_now(),
            },
            ensure_ascii=False,
        )
        started = time.monotonic()
        acquired = False
        while time.monotonic() - started <= timeout:
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(payload)
                acquired = True
                break
            except FileExistsError:
                data = self._read_json_file(path)
                if data and not self._is_owner_process_alive(data.get("owner_pid")):
                    try:
                        path.unlink()
                        continue
                    except FileNotFoundError:
                        continue
                time.sleep(0.05)
        if not acquired:
            raise TimeoutError("profile-copy-default.lock is busy")
        try:
            yield
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _headed_browser_is_alive(self, lock: dict[str, Any]) -> bool:
        browser_pid = lock.get("browser_pid")
        if browser_pid is not None and self._is_owner_process_alive(browser_pid):
            return True
        profile_dir = str(lock.get("profile_dir") or "")
        if not profile_dir:
            return False
        return self._alpha_browser_process_using_path(profile_dir)

    def _alpha_browser_process_using_path(self, path: str) -> bool:
        marker = self._normalized_path_text(path)
        if os.name == "nt":
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
                return False
            output = (proc.stdout or "").strip()
            if not output:
                return False
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                return False
            items = data if isinstance(data, list) else [data]
            return any(marker in self._normalized_path_text(str(item.get("CommandLine") or "")) for item in items if isinstance(item, dict))
        try:
            proc = subprocess.run(
                ["ps", "-eo", "args="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return False
        return marker in self._normalized_path_text(proc.stdout or "")

    def _refresh_interactive_lock(self, *, cleanup_headless_base: bool = True) -> dict[str, Any] | None:
        lock = self._read_interactive_lock()
        if not lock:
            return None
        kind = lock.get("kind")
        owner_alive = self._is_owner_process_alive(lock.get("owner_pid"))
        if kind == "headed":
            browser_alive = self._headed_browser_is_alive(lock)
            if browser_alive or (lock.get("status") == "starting" and owner_alive):
                return lock
            if cleanup_headless_base:
                try:
                    with self._profile_copy_lock(timeout=2):
                        profile = str(lock.get("profile") or "default")
                        shutil.rmtree(self._headless_base_dir(profile), ignore_errors=True)
                        shutil.rmtree(self._headless_base_next_dir(profile), ignore_errors=True)
                except TimeoutError:
                    return lock
            self._remove_interactive_lock()
            return None
        if kind == "cdp":
            if owner_alive:
                return lock
            self._remove_interactive_lock()
            return None
        self._remove_interactive_lock()
        return None

    def _interactive_lock_guidance(self, lock: dict[str, Any] | None) -> dict[str, Any]:
        owner = "none"
        if lock:
            owner = "current_alpha" if lock.get("owner_id") == self.owner_id else "other_alpha"
        guidance: dict[str, Any] = {
            "interactive_owner": owner,
            "interactive_lock_scope": "global_across_alpha_instances",
            "sessions_scope": "current_alpha_only",
            "headless_allowed_by_interactive_lock": True,
            "recommended_next_tool": None,
            "do_not_call": [],
        }
        if owner == "other_alpha":
            guidance["recommended_next_tool"] = "browser_navigate"
            guidance["do_not_call"] = [
                "browser_disconnect_cdp",
                "browser_close",
                "browser_connect_cdp",
            ]
            guidance["note"] = (
                "interactive_lock is owned by another alpha instance; do not disconnect, close, "
                "or reconnect that interactive browser. Use browser_navigate for headless work."
            )
        return guidance

    def _interactive_busy_error(self, requested: str, lock: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": False,
            "error": f"Cannot start {requested}; browser interactive mode is already occupied by {lock.get('kind')}.",
            "interactive_lock": lock,
            **self._interactive_lock_guidance(lock),
        }

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

    def _has_minimal_chrome_profile(self, path: Path) -> bool:
        return (path / "Local State").exists() and (path / "Default" / "Preferences").exists()

    def _replace_dir(self, source: Path, target: Path) -> None:
        old = target.with_name(f"{target.name}.old-{uuid.uuid4().hex[:8]}")
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        try:
            source.rename(target)
        except Exception:
            if old.exists() and not target.exists():
                old.rename(target)
            raise
        finally:
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)

    def _build_headless_base(self, profile: str) -> None:
        source = self._profile_dir(profile)
        target = self._headless_base_dir(profile)
        staging = self._headless_base_next_dir(profile)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        if not self._has_minimal_chrome_profile(staging):
            shutil.rmtree(staging, ignore_errors=True)
            raise ValueError("default profile is missing Local State or Default/Preferences")
        self._replace_dir(staging, target)

    def _headless_copy_source(self, profile: str) -> tuple[Path | None, dict[str, Any] | None]:
        lock = self._refresh_interactive_lock(cleanup_headless_base=False)
        if lock and lock.get("kind") == "headed":
            if not self._headed_browser_is_alive(lock) and lock.get("status") != "starting":
                lock = self._refresh_interactive_lock(cleanup_headless_base=False)
            if lock and lock.get("kind") == "headed":
                base = self._headless_base_dir(profile)
                if not base.exists():
                    return None, {
                        "success": False,
                        "error": "headed browser is active, but headless-base is missing; refusing to copy live default profile.",
                        "profile": profile,
                        "headless_base": str(base),
                    }
                return base, None
        return self._profile_dir(profile), None

    def _prepare_runtime_profile(self, session: BrowserSession) -> dict[str, Any] | None:
        if not session.profile:
            return None
        runtime = self.runtime_dir / session.session_id
        target = runtime / "user-data"
        session.runtime_dir = runtime
        self._write_session_metadata(session, "starting")
        try:
            with self._profile_copy_lock():
                source, source_error = self._headless_copy_source(session.profile)
                if source_error:
                    return source_error
                assert source is not None
                self._unlock_profile(session.profile)
                self._copy_runtime_profile_once(source, runtime, target)
        except OSError as first_error:
            self._cleanup_alpha_browser_processes()
            self._unlock_profile(session.profile)
            if runtime.exists():
                shutil.rmtree(runtime, ignore_errors=True)
            try:
                with self._profile_copy_lock():
                    source, source_error = self._headless_copy_source(session.profile)
                    if source_error:
                        return source_error
                    assert source is not None
                    self._copy_runtime_profile_once(source, runtime, target)
            except OSError as second_error:
                self._write_session_metadata(session, "failed")
                return {
                    "success": False,
                    "error": (
                        "default profile is still locked by an alpha browser process; "
                        "close alpha browser windows and retry."
                    ),
                    "first_error": str(first_error),
                    "second_error": str(second_error),
                    "profile": session.profile,
                    "profile_dir": str(self._profile_dir(session.profile)),
                    "runtime_dir": str(runtime),
                }
        except TimeoutError as exc:
            self._write_session_metadata(session, "failed")
            return {"success": False, "error": str(exc), "profile": session.profile}
        session.profile_dir = target
        session.runtime_dir = runtime
        self._write_session_metadata(session, "starting")
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

    def _extract_snapshot_data(self, result: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
        data = result.get("data")
        if isinstance(data, dict):
            snapshot = data.get("snapshot")
            refs = data.get("refs")
            origin = data.get("origin") or data.get("url")
            if isinstance(snapshot, str):
                return snapshot, refs if isinstance(refs, dict) else {}, str(origin) if origin else None
        snapshot = result.get("snapshot")
        if isinstance(snapshot, str):
            return snapshot, {}, None
        raw = result.get("raw")
        if isinstance(raw, str):
            return raw, {}, None
        if isinstance(data, str):
            return data, {}, None
        return "", {}, None

    def _is_actionable_snapshot_line(self, line: str) -> bool:
        stripped = line.strip()
        if "[ref=" not in stripped:
            return False
        actionable_prefixes = (
            "- heading ",
            "- link ",
            "- button ",
            "- textbox ",
            "- input ",
            "- textarea ",
            "- select ",
            "- combobox ",
            "- searchbox ",
            "- checkbox ",
            "- radio ",
            "- menuitem ",
            "- option ",
            "- tab ",
        )
        return stripped.startswith(actionable_prefixes)

    def _compact_snapshot_text(self, snapshot: str) -> tuple[str, bool]:
        lines = snapshot.replace("\r\n", "\n").splitlines()
        kept: list[str] = []
        truncated = False
        for line in lines:
            if not self._is_actionable_snapshot_line(line):
                continue
            candidate = "\n".join([*kept, line]) if kept else line
            if len(candidate) > COMPACT_BROWSER_SNAPSHOT_CHARS:
                truncated = True
                break
            kept.append(line)
            if len(kept) >= COMPACT_BROWSER_SNAPSHOT_ITEMS:
                truncated = True
                break

        if not kept:
            fallback = [line for line in lines if "[ref=" in line][:COMPACT_BROWSER_SNAPSHOT_ITEMS]
            kept = fallback
            truncated = len(fallback) < len([line for line in lines if "[ref=" in line])

        compact = "\n".join(kept)
        if len(compact) > COMPACT_BROWSER_SNAPSHOT_CHARS:
            compact = compact[:COMPACT_BROWSER_SNAPSHOT_CHARS]
            truncated = True
        if len(compact) < len(snapshot):
            truncated = True
        return compact, truncated

    def _refs_for_snapshot_text(self, refs: dict[str, Any], snapshot: str) -> dict[str, Any]:
        if not refs:
            return {}
        ref_ids = set(re.findall(r"\[ref=([^\]\s]+)\]", snapshot))
        return {key: value for key, value in refs.items() if key in ref_ids}

    def _compact_snapshot_result(self, result: dict[str, Any], session: BrowserSession) -> dict[str, Any]:
        snapshot, refs, origin = self._extract_snapshot_data(result)
        compact, truncated = self._compact_snapshot_text(snapshot)
        compact_refs = self._refs_for_snapshot_text(refs, compact)
        return {
            "success": bool(result.get("success", True)),
            "session_id": session.session_id,
            "mode": session.mode,
            "origin": origin,
            "snapshot": compact,
            "refs": compact_refs,
            "truncated": truncated,
            "original_chars": len(snapshot),
            "returned_chars": len(compact),
            "original_ref_count": len(refs),
            "returned_ref_count": len(compact_refs),
            "browser_executable": self.browser_executable_info(),
            "note": (
                "Returned compact actionable browser snapshot. "
                "Use save_full=true to write the full snapshot to temp/browser_snapshots."
            ),
        }

    def _save_full_snapshot_result(self, result: dict[str, Any], session: BrowserSession) -> dict[str, Any]:
        snapshot, refs, origin = self._extract_snapshot_data(result)
        if not snapshot:
            snapshot = json.dumps(result, ensure_ascii=False, indent=2)
        snapshot_dir = self.project_root / "temp" / "browser_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = snapshot_dir / f"{session.session_id}-{stamp}.md"
        path.write_text(
            "\n".join(
                [
                    "# Browser Snapshot",
                    "",
                    f"- session_id: {session.session_id}",
                    f"- mode: {session.mode}",
                    f"- origin: {origin or ''}",
                    f"- original_chars: {len(snapshot)}",
                    f"- refs: {len(refs)}",
                    "",
                    "```text",
                    snapshot,
                    "```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        note = "Full browser snapshot saved to temp file and not returned to model history."
        return {
            "success": bool(result.get("success", True)),
            "session_id": session.session_id,
            "mode": session.mode,
            "origin": origin,
            "snapshot_file": self._relative_path(path),
            "original_chars": len(snapshot),
            "returned_chars": len(note),
            "original_ref_count": len(refs),
            "browser_executable": self.browser_executable_info(),
            "note": note,
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
        if mode == "local-headless":
            self.current_headless_session_id = session_id
            self.current_session_id = session_id
        elif mode == "local-headed-login":
            self.current_headed_session_id = session_id
        elif mode == "external-cdp":
            self.current_cdp_session_id = session_id
        return session

    def _get_session(self, session_id: str | None = None) -> BrowserSession | None:
        if session_id:
            return self.active_sessions.get(session_id)
        if self.current_headless_session_id:
            return self.active_sessions.get(self.current_headless_session_id)
        return None

    def _load_profile_state(self, session: BrowserSession) -> dict[str, Any] | None:
        if not session.profile or session.cdp_url:
            return None
        state_file = self._profile_state_file(session.profile)
        if not state_file.exists():
            return None
        return self._run_cli(session, ["state", "load", str(state_file)], timeout=30)

    def _load_headed_state(self, session: BrowserSession) -> dict[str, Any] | None:
        if not session.profile or session.cdp_url:
            return None
        state_file = self._headed_state_file(session.profile)
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
                    self.current_session_id = None
                if self.current_headless_session_id == session.session_id:
                    self.current_headless_session_id = None
                return copy_error
            self._load_headed_state(session)
        result = self._run_cli(session, ["open", url], timeout=60)
        self._touch_profile(profile)
        self._write_session_metadata(session, "running" if result.get("success", True) else "failed")
        persistent_profile_dir = self._profile_dir(profile)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "success": bool(result.get("success", result.get("data") is not None)),
            "session_id": session.session_id,
            "profile": profile,
            "profile_dir": str(persistent_profile_dir),
            "runtime_profile_dir": str(session.profile_dir) if session.profile_dir else None,
            "mode": session.mode,
            "url": data.get("url") or data.get("origin") or url,
            "title": data.get("title"),
            "browser_executable": self.browser_executable_info(),
            "open": result,
            "next_step": "Call browser_snapshot for actionable page state; use save_full=true only when full evidence is needed.",
        }

    def start_headed_login(self, profile: str = "default", url: str = "about:blank") -> dict[str, Any]:
        self.ensure_profile(profile)
        profile_dir = self._profile_dir(profile)
        existing = self._refresh_interactive_lock()
        if existing:
            if existing.get("kind") == "headed" and existing.get("owner_id") == self.owner_id:
                session = self.active_sessions.get(str(existing.get("session_id") or ""))
                return {
                    "success": True,
                    "reused": True,
                    "session_id": existing.get("session_id"),
                    "profile": profile,
                    "profile_dir": str(profile_dir),
                    "mode": "local-headed-login",
                    "interactive_lock": existing,
                }
            return self._interactive_busy_error("headed browser", existing)
        session = self._new_session("local-headed-login", profile, profile_dir=profile_dir)
        self._write_session_metadata(session, "starting")
        lock_payload = {
            "kind": "headed",
            "status": "starting",
            "owner_id": self.owner_id,
            "owner_pid": self.owner_pid,
            "session_id": session.session_id,
            "profile": profile,
            "profile_dir": str(profile_dir),
        }
        if not self._try_create_interactive_lock(lock_payload):
            existing = self._refresh_interactive_lock()
            self.active_sessions.pop(session.session_id, None)
            self.current_headed_session_id = None
            if existing:
                return self._interactive_busy_error("headed browser", existing)
            return {"success": False, "error": "interactive lock is busy; retry starting headed browser."}
        try:
            with self._profile_copy_lock():
                self._build_headless_base(profile)
        except Exception as exc:
            self._remove_interactive_lock()
            self.active_sessions.pop(session.session_id, None)
            self.current_headed_session_id = None
            self._write_session_metadata(session, "failed")
            return {"success": False, "error": f"failed to create headless-base before headed launch: {exc}"}
        result = self._run_cli(session, ["open", url], timeout=60, headed=True)
        if not result.get("success", result.get("data") is not None):
            self._remove_interactive_lock()
            self._write_session_metadata(session, "failed")
            return {
                "success": False,
                "session_id": session.session_id,
                "profile": profile,
                "profile_dir": str(profile_dir),
                "mode": session.mode,
                "result": result,
                "error": "headed browser launch failed",
            }
        lock_payload["status"] = "running"
        lock_payload["browser_pid"] = result.get("browser_pid")
        self._write_interactive_lock(lock_payload)
        self._write_session_metadata(session, "running")
        self._touch_profile(profile)
        return {
            "success": bool(result.get("success", result.get("data") is not None)),
            "session_id": session.session_id,
            "profile": profile,
            "profile_dir": str(profile_dir),
            "mode": session.mode,
            "browser_executable": self.browser_executable_info(),
            "result": result,
            "next_step": "After manual login, call profile_save_headed to save state for this alpha, or profile_close_headed only if the user explicitly asks to close the visible browser.",
        }

    def connect_cdp(self, cdp_url: str) -> dict[str, Any]:
        value = (cdp_url or "").strip()
        if not value:
            return {"success": False, "error": "cdp_url is required"}
        existing = self._refresh_interactive_lock()
        if existing:
            return self._interactive_busy_error("CDP", existing)
        session = self._new_session("external-cdp", None, cdp_url=value)
        if not self._try_create_interactive_lock(
            {
                "kind": "cdp",
                "status": "running",
                "owner_id": self.owner_id,
                "owner_pid": self.owner_pid,
                "session_id": session.session_id,
                "cdp_url": value,
            }
        ):
            existing = self._refresh_interactive_lock()
            self.active_sessions.pop(session.session_id, None)
            self.current_cdp_session_id = None
            if existing:
                return self._interactive_busy_error("CDP", existing)
            return {"success": False, "error": "interactive lock is busy; retry connecting CDP."}
        self._write_session_metadata(session, "running")
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

    def snapshot_current(self, *, save_full: bool = False, session_id: str | None = None) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session is None:
            return {"success": False, "error": "No active browser session. Call browser_navigate or browser_connect_cdp first."}
        args = ["snapshot"] if save_full else ["snapshot", "-i"]
        result = self._run_cli(session, args, timeout=60)
        if not result.get("success", True):
            result.setdefault("session_id", session.session_id)
            result.setdefault("mode", session.mode)
            return result
        if save_full:
            return self._save_full_snapshot_result(result, session)
        return self._compact_snapshot_result(result, session)

    def close(self, session_id: str | None = None, save_profile: bool | None = None) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session is None:
            return {"success": False, "error": "No active browser session to close."}
        if session.mode == "local-headed-login":
            return {
                "success": False,
                "error": "browser_close refuses to close a visible headed browser. Use profile_close_headed with explicit user confirmation.",
                "session_id": session.session_id,
                "mode": session.mode,
            }
        if session.mode == "external-cdp":
            return {
                "success": False,
                "error": "browser_close refuses to close an external CDP browser. Use browser_disconnect_cdp to disconnect control only.",
                "session_id": session.session_id,
                "mode": session.mode,
            }

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
        self.active_sessions.pop(session.session_id, None)
        if self.current_session_id == session.session_id:
            self.current_session_id = None
        if self.current_headless_session_id == session.session_id:
            self.current_headless_session_id = None
        try:
            self._session_metadata_path(session.session_id).unlink()
        except FileNotFoundError:
            pass
        return {
            "success": bool(closed.get("success", True)),
            "session_id": session.session_id,
            "profile": session.profile,
            "mode": session.mode,
            "saved": saved,
            "closed": closed,
            "temporary_profile_removed": temporary_profile_removed,
        }

    def profile_save_headed(self, profile: str = "default") -> dict[str, Any]:
        lock = self._refresh_interactive_lock()
        if not lock or lock.get("kind") != "headed" or lock.get("owner_id") != self.owner_id:
            return {"success": False, "error": "No current headed browser owned by this alpha to save."}
        session = self.active_sessions.get(str(lock.get("session_id") or "")) or self.active_sessions.get(
            self.current_headed_session_id or ""
        )
        if not session or session.mode != "local-headed-login":
            return {"success": False, "error": "No active headed browser session to save."}
        state_file = self._headed_state_file(profile)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_cli(session, ["state", "save", str(state_file)], timeout=30)
        return {
            "success": bool(result.get("success", True)),
            "session_id": session.session_id,
            "profile": profile,
            "state_file": str(state_file),
            "result": result,
        }

    def profile_close_headed(
        self,
        profile: str = "default",
        *,
        user_confirmed_close_visible_browser: bool = False,
        wait_timeout: float = 30.0,
    ) -> dict[str, Any]:
        if not user_confirmed_close_visible_browser:
            return {
                "success": False,
                "error": "Refusing to close visible headed browser without user_confirmed_close_visible_browser=true.",
            }
        lock = self._refresh_interactive_lock()
        if not lock or lock.get("kind") != "headed" or lock.get("owner_id") != self.owner_id:
            return {"success": False, "error": "No current headed browser owned by this alpha to close."}
        session = self.active_sessions.get(str(lock.get("session_id") or "")) or self.active_sessions.get(
            self.current_headed_session_id or ""
        )
        if not session or session.mode != "local-headed-login":
            return {"success": False, "error": "No active headed browser session to close."}
        closed = self._run_cli(session, ["close"], timeout=30)
        started = time.monotonic()
        while time.monotonic() - started <= wait_timeout:
            if not self._headed_browser_is_alive(lock):
                break
            time.sleep(0.1)
        else:
            return {
                "success": False,
                "error": "headed browser is still running; interactive lock was not released.",
                "session_id": session.session_id,
                "closed": closed,
            }
        with self._profile_copy_lock(timeout=5):
            shutil.rmtree(self._headless_base_dir(profile), ignore_errors=True)
            shutil.rmtree(self._headless_base_next_dir(profile), ignore_errors=True)
        try:
            self._headed_state_file(profile).unlink()
        except FileNotFoundError:
            pass
        self._remove_interactive_lock()
        self.active_sessions.pop(session.session_id, None)
        self.current_headed_session_id = None
        try:
            self._session_metadata_path(session.session_id).unlink()
        except FileNotFoundError:
            pass
        return {
            "success": bool(closed.get("success", True)),
            "session_id": session.session_id,
            "profile": profile,
            "closed": closed,
            "interactive_lock_released": True,
        }

    def disconnect_cdp(self, session_id: str | None = None) -> dict[str, Any]:
        self._refresh_interactive_lock()
        value = session_id or self.current_cdp_session_id
        session = self.active_sessions.get(value or "")
        if not session or session.mode != "external-cdp":
            lock = self._read_interactive_lock()
            if lock and lock.get("kind") == "cdp" and lock.get("owner_id") == self.owner_id:
                self._remove_interactive_lock()
                return {"success": True, "session_id": lock.get("session_id"), "disconnected": True}
            result = {"success": False, "error": "No active external CDP session to disconnect."}
            if lock and lock.get("kind") == "cdp":
                result["error"] = (
                    "No active external CDP session owned by this alpha to disconnect. "
                    "The global CDP lock belongs to another alpha instance."
                )
                result["interactive_lock"] = lock
                result.update(self._interactive_lock_guidance(lock))
            return result
        self.active_sessions.pop(session.session_id, None)
        self.current_cdp_session_id = None
        lock = self._read_interactive_lock()
        if lock and lock.get("kind") == "cdp" and lock.get("session_id") == session.session_id:
            self._remove_interactive_lock()
        try:
            self._session_metadata_path(session.session_id).unlink()
        except FileNotFoundError:
            pass
        return {"success": True, "session_id": session.session_id, "disconnected": True}

    def status(self) -> dict[str, Any]:
        self._refresh_interactive_lock()
        lock = self._read_interactive_lock()
        return {
            "success": True,
            "current_session_id": self.current_session_id,
            "current_headless_session_id": self.current_headless_session_id,
            "current_headed_session_id": self.current_headed_session_id,
            "current_cdp_session_id": self.current_cdp_session_id,
            "interactive_lock": lock,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "mode": item.mode,
                    "profile": item.profile,
                    "cdp_url": item.cdp_url,
                }
                for item in self.active_sessions.values()
            ],
            **self._interactive_lock_guidance(lock),
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
