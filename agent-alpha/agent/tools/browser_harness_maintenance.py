"""Best-effort, bounded maintenance of Alpha's private browser data."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from agent.tools.browser_harness_browser import DedicatedBrowser
from agent.tools.browser_harness_lock import BrowserFileLock


LIMIT = 500 * 1024 * 1024
TARGET = 300 * 1024 * 1024
IDLE_SECONDS = 5 * 60
RETRY_SECONDS = 5 * 60 * 60
SWEEP_SECONDS = 60
SWEEP_BUDGET_SECONDS = 10


class BrowserMaintenance:
    def __init__(self, project_root: Path) -> None:
        self.state = project_root / "state" / "browser-harness"
        self.temp = project_root / "temp" / "browser-harness"
        self.profile = self.state / "browser-profile"
        self.lock = BrowserFileLock(self.state / "browser-use.lock")
        self.status_file = self.state / "maintenance-status.json"
        self.next_retry = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def start(self) -> None:
        if "PYTEST_CURRENT_TEST" in os.environ:
            return
        with self._start_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._loop, daemon=True, name="browser-maintenance")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        # FastAPI starts serving while this thread handles the first inspection.
        while not self._stop.wait(1 if not self.next_retry else SWEEP_SECONDS):
            try:
                self.sweep()
            except Exception as exc:
                try:
                    self._failure(str(exc))
                except OSError:
                    self.next_retry = time.time() + RETRY_SECONDS
            if not self.next_retry:
                self.next_retry = time.time() + SWEEP_SECONDS

    def sweep(self) -> None:
        now = time.time()
        if now < self.next_retry:
            return
        last_use = self.state / "last-browser-use"
        if not self.lock.acquire(0):
            return
        try:
            browser = DedicatedBrowser(self.profile, self.temp)
            if browser.main_processes():
                last_use.touch()
                return
            legacy = self.state / "agents"
            if legacy.is_dir():
                for scope in legacy.iterdir():
                    if scope.is_dir() and DedicatedBrowser(scope / "browser-profile", self.temp).main_processes():
                        last_use.touch()
                        return
            if last_use.exists() and now - last_use.stat().st_mtime < IDLE_SECONDS:
                return
            deadline = time.monotonic() + SWEEP_BUDGET_SECONDS
            total = self._size(self.state, deadline) + self._size(self.temp, deadline)
            if total <= LIMIT:
                return
            candidates = [
                self.temp,
                self.profile / "Default" / "Cache",
                self.profile / "Default" / "Code Cache",
                self.profile / "Default" / "GPUCache",
                self.profile / "Default" / "Service Worker" / "CacheStorage",
                self.profile / "Default" / "Service Worker" / "ScriptCache",
                self.profile / "Default" / "Service Worker",
                self.profile / "Default" / "Storage",
                self.profile / "Default" / "IndexedDB",
                self.profile / "Default" / "Local Storage",
                self.profile / "Default" / "History",
                self.profile / "GrShaderCache",
                self.profile / "ShaderCache",
                self.profile / "component_crx_cache",
                self.profile / "extensions_crx_cache",
                self.profile / "optimization_guide_model_store",
            ]
            if legacy.is_dir():
                candidates.extend(scope for scope in legacy.iterdir() if scope.is_dir())
            for candidate in candidates:
                size = self._size(candidate, deadline)
                self._remove_files(candidate, deadline)
                total -= size
                if total <= TARGET:
                    break
            if total > LIMIT:
                # Last resort: a full reset is safer than guessing Chrome's account files.
                self._remove_files(self.profile, deadline)
                self._notice("reset", "浏览器资料已因空间超限重置，下次使用需要重新登录。")
            self.next_retry = time.time() + SWEEP_SECONDS
        except (OSError, TimeoutError, ValueError) as exc:
            if not self._stop.is_set():
                self._failure(str(exc))
        finally:
            self.lock.release()

    def _size(self, root: Path, deadline: float) -> int:
        if not root.exists():
            return 0
        total = 0
        for base, _, files in os.walk(root):
            if self._stop.is_set():
                raise InterruptedError("browser maintenance stopping")
            if time.monotonic() > deadline:
                raise TimeoutError("browser maintenance time limit")
            for filename in files:
                if self._stop.is_set():
                    raise InterruptedError("browser maintenance stopping")
                try:
                    total += (Path(base) / filename).stat().st_size
                except FileNotFoundError:
                    continue
        return total

    def _remove_files(self, root: Path, deadline: float) -> None:
        if not root.exists():
            return
        for base, dirs, files in os.walk(root, topdown=False):
            if self._stop.is_set():
                raise InterruptedError("browser maintenance stopping")
            if time.monotonic() > deadline:
                raise TimeoutError("browser maintenance time limit")
            for filename in files:
                if self._stop.is_set():
                    raise InterruptedError("browser maintenance stopping")
                (Path(base) / filename).unlink()
            for directory in dirs:
                (Path(base) / directory).rmdir()
        root.rmdir()

    def _failure(self, _detail: str) -> None:
        self.next_retry = time.time() + RETRY_SECONDS
        self._notice("failed", "浏览器空间清理失败，5小时后或下次启动会重试。")

    def _notice(self, kind: str, message: str) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_name(f"maintenance-status.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps({"kind": kind, "message": message, "id": time.time_ns()}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.status_file)


def read_browser_maintenance_notice(project_root: Path) -> dict:
    path = project_root / "state" / "browser-harness" / "maintenance-status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
