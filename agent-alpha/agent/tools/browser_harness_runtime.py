from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from agent.core.runtime_paths import build_runtime_env, ensure_runtime_directories
from agent.tools.browser_harness_browser import BrowserProcessDiscoveryError, DedicatedBrowser
from agent.tools.browser_harness_lock import BrowserFileLock


BROWSER_HARNESS_VERSION = "0.1.13"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 50_000
BROWSER_START_TIMEOUT_SECONDS = 20
SHUTDOWN_TIMEOUT_SECONDS = 25


class BrowserHarnessRuntime:
    """One process-local browser channel, scoped to the owning agent."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.state_dir, browser_temp = browser_scope_paths(self.project_root, os.environ)
        self.runtime_dir = self.state_dir / "runtime"
        self.profile_dir = self.state_dir / "browser-profile"
        self.workspace_dir = self.state_dir / "agent-workspace"
        self.temp_dir = browser_temp
        self._lock = threading.Lock()
        self._process_lock = BrowserFileLock(self.state_dir / "browser-use.lock")
        self._cli_path: Path | None = None
        self._used = False
        self._manual_waiting = False
        self._last_endpoint: str | None = None
        self.browser = DedicatedBrowser(self.profile_dir, self.temp_dir)
        ensure_runtime_directories(self.project_root)

    def execute(
        self,
        *,
        code: Any = None,
        mode: Any = None,
        timeout_seconds: Any = DEFAULT_TIMEOUT_SECONDS,
        interrupt_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if mode not in (None, "manual", "cdp"):
            return self._error("validation", "mode must be 'manual' or 'cdp'")
        if mode == "manual" and isinstance(code, str) and code.strip():
            return self._error("validation", "code must be omitted in manual mode")
        if mode != "manual" and (not isinstance(code, str) or not code.strip()):
            return self._error("validation", "code must be a non-empty string in cdp mode")
        timeout = self._validate_timeout(timeout_seconds)
        if timeout is None:
            return self._error(
                "validation",
                f"timeout_seconds must be an integer between 1 and {MAX_TIMEOUT_SECONDS}",
                invalid_timeout_seconds=timeout_seconds,
            )

        deadline = time.monotonic() + timeout
        lock_result = self._acquire_lock(timeout, interrupt_event)
        if lock_result is not None:
            return lock_result
        try:
            try:
                cli_result = self._verify_cli()
                if isinstance(cli_result, dict):
                    return cli_result
                if mode == "manual":
                    return self._prepare_manual(cli_result, deadline, interrupt_event)
                endpoint_result = self._ensure_browser(
                    cli_result,
                    interrupt_event,
                    explicit_takeover=mode == "cdp",
                    deadline=deadline,
                )
                if isinstance(endpoint_result, dict):
                    return endpoint_result
                self._used = True
                remaining = int(deadline - time.monotonic())
                if remaining < 1:
                    return self._error("timeout", "Browser task timed out before execution", timed_out=True)
                env = build_browser_harness_env(
                    self.project_root,
                    cdp_url=endpoint_result,
                    base_env=os.environ,
                )
                return self._run_cli(
                    [str(cli_result)],
                    input_text=code,
                    timeout_seconds=remaining,
                    interrupt_event=interrupt_event,
                    env=env,
                )
            except BrowserProcessDiscoveryError as exc:
                return self._error(
                    "browser",
                    f"Could not safely inspect Alpha's browser process: {exc}",
                    recoverable=True,
                )
            except Exception as exc:
                return self._error("runtime", f"Unexpected Browser Harness failure: {exc}")
        finally:
            if self._process_lock.handle is not None:
                try:
                    (self.state_dir / "last-browser-use").touch()
                except OSError:
                    pass
            self._process_lock.release()
            self._lock.release()

    def shutdown(self) -> dict[str, Any]:
        """Best-effort normal Web shutdown; never discovers or kills other browsers."""
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
        if not self._lock.acquire(timeout=min(5, SHUTDOWN_TIMEOUT_SECONDS)):
            return self._error("shutdown", "browser channel is still busy")
        try:
            acquired = self._process_lock.acquire(5)
        except OSError as exc:
            self._lock.release()
            return self._error("shutdown", f"Could not lock browser channel: {exc}")
        if not acquired:
            self._lock.release()
            return self._error("shutdown", "browser channel is still busy")
        try:
            try:
                endpoint = self._healthy_endpoint()
            except BrowserProcessDiscoveryError as exc:
                return self._error(
                    "shutdown",
                    f"Could not safely inspect Alpha's browser process: {exc}",
                    recoverable=True,
                )
            cli = self._cli_path if self._cli_path and self._cli_path.is_file() else self._find_cli()
            if cli is None:
                return self._error("shutdown", self._missing_cli_message())
            env = build_browser_harness_env(self.project_root, cdp_url=endpoint, base_env=os.environ)
            close_result: dict[str, Any] = {"success": True, "skipped": endpoint is None}
            if endpoint is not None:
                close_result = self._run_cli(
                    [str(cli)],
                    input_text='cdp("Browser.close")',
                    timeout_seconds=max(1, min(10, int(deadline - time.monotonic()))),
                    interrupt_event=None,
                    env=env,
                )
            reload_result = self._run_cli(
                [str(cli), "--reload"],
                input_text=None,
                timeout_seconds=max(1, min(10, int(deadline - time.monotonic()))),
                interrupt_event=None,
                env=env,
            )
            process_close: dict[str, Any] = {"success": True, "skipped": True}
            if endpoint is None:
                try:
                    current_mode = self.browser.current_mode()
                except BrowserProcessDiscoveryError as exc:
                    return self._error(
                        "shutdown",
                        f"Could not safely inspect Alpha's browser process: {exc}",
                        recoverable=True,
                    )
                if current_mode == "cdp":
                    process_close = self.browser.close(
                        timeout_seconds=min(10, max(0, deadline - time.monotonic()))
                    )
            self._used = False
            self._last_endpoint = None
            return {
                "success": bool(
                    close_result.get("success")
                    and reload_result.get("success")
                    and process_close.get("success")
                ),
                "browser_close": close_result,
                "daemon_reload": reload_result,
                "process_close": process_close,
            }
        finally:
            self._process_lock.release()
            self._lock.release()

    def _validate_timeout(self, value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 1 <= value <= MAX_TIMEOUT_SECONDS else None

    def _acquire_lock(
        self,
        timeout_seconds: int,
        interrupt_event: threading.Event | None,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if interrupt_event is not None and interrupt_event.is_set():
                return self._error("lock", "Browser Harness call interrupted while waiting", interrupted=True)
            if self._lock.acquire(timeout=min(0.05, max(0.0, deadline - time.monotonic()))):
                try:
                    if self._process_lock.acquire(max(0.0, deadline - time.monotonic())):
                        return None
                except OSError as exc:
                    self._lock.release()
                    return self._error("lock", f"Could not lock browser channel: {exc}")
                self._lock.release()
                break
        return self._error(
            "lock",
            "The shared browser is busy with another task. Retry after that task finishes.",
            timed_out=True,
            timeout_seconds=timeout_seconds,
        )

    def _verify_cli(self) -> Path | dict[str, Any]:
        cli = self._cli_path if self._cli_path and self._cli_path.is_file() else self._find_cli()
        if cli is None:
            return self._error("cli", self._missing_cli_message())
        try:
            completed = subprocess.run(
                [str(cli), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                env=build_browser_harness_env(self.project_root, base_env=os.environ),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return self._error("cli", f"Could not run Browser Harness: {exc}")
        version = completed.stdout.strip()
        if completed.returncode != 0 or version != BROWSER_HARNESS_VERSION:
            found = version or completed.stderr.strip() or "unknown"
            return self._error(
                "cli",
                f"Browser Harness {BROWSER_HARNESS_VERSION} is required, but found {found}. Run setup-agent-alpha.ps1.",
                expected_version=BROWSER_HARNESS_VERSION,
                found_version=found,
            )
        self._cli_path = cli
        return cli

    def _find_cli(self) -> Path | None:
        names = ["browser-harness.exe", "browser-harness"] if os.name == "nt" else ["browser-harness", "browser-harness.exe"]
        for name in names:
            candidate = self.project_root / "bin" / name
            if candidate.is_file():
                return candidate
        return None

    def _missing_cli_message(self) -> str:
        return (
            f"Browser Harness {BROWSER_HARNESS_VERSION} is not installed in agent-alpha/bin. "
            "Run setup-agent-alpha.ps1; Alpha will not download it during a browser task."
        )

    def _prepare_manual(
        self,
        cli: Path,
        deadline: float,
        interrupt_event: threading.Event | None,
    ) -> dict[str, Any]:
        mode = self.browser.current_mode()
        if mode == "conflict":
            return self._error("browser", "Multiple Alpha browser modes are running. Close the Alpha browser windows, then retry.")
        if mode == "manual" and (self._manual_waiting or not self.browser.native_remote_debugging_enabled()):
            if not self._manual_waiting:
                reload_result = self._reload_daemon(cli, deadline, interrupt_event)
                if not reload_result.get("success"):
                    return reload_result
            self._manual_waiting = True
            return self._manual_login_required()
        reload_result = self._reload_daemon(cli, deadline, interrupt_event)
        if not reload_result.get("success"):
            return reload_result
        if mode is not None:
            close_result = self.browser.close(timeout_seconds=min(10, max(0, deadline - time.monotonic())))
            if not close_result.get("success"):
                return close_result
        setting_result = self.browser.disable_native_remote_debugging()
        if not setting_result.get("success"):
            return setting_result
        try:
            (self.profile_dir / "DevToolsActivePort").unlink(missing_ok=True)
        except OSError as exc:
            return self._error("browser", f"Could not clear stopped browser endpoint: {exc}")
        executable = find_browser_executable(self.project_root, os.environ)
        if executable is None:
            return self._missing_browser_error()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.browser.launch(executable, "manual")
        except OSError as exc:
            return self._error("browser", f"Could not start Alpha's manual-login browser: {exc}")
        self._manual_waiting = True
        self._last_endpoint = None
        return self._manual_login_required()

    def _ensure_browser(
        self,
        cli: Path,
        interrupt_event: threading.Event | None,
        *,
        explicit_takeover: bool,
        deadline: float,
    ) -> str | dict[str, Any]:
        if self._manual_waiting and not explicit_takeover:
            return self._manual_login_required()
        mode = self.browser.current_mode()
        if mode == "conflict":
            return self._error("browser", "Multiple Alpha browser modes are running. Close the Alpha browser windows, then retry.")
        if mode == "manual" and not explicit_takeover:
            self._manual_waiting = True
            return self._manual_login_required()
        endpoint = self._healthy_endpoint()
        if mode == "cdp" and endpoint is not None:
            self._last_endpoint = endpoint
            self._manual_waiting = False
            return endpoint

        reload_result = self._reload_daemon(cli, deadline, interrupt_event)
        if not reload_result.get("success"):
            return reload_result
        if mode is not None:
            close_result = self.browser.close(timeout_seconds=min(10, max(0, deadline - time.monotonic())))
            if not close_result.get("success"):
                return close_result
        setting_result = self.browser.disable_native_remote_debugging()
        if not setting_result.get("success"):
            return setting_result
        try:
            (self.profile_dir / "DevToolsActivePort").unlink(missing_ok=True)
        except OSError as exc:
            return self._error("browser", f"Could not clear stopped browser endpoint: {exc}")
        executable = find_browser_executable(self.project_root, os.environ)
        if executable is None:
            return self._missing_browser_error()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            process = self.browser.launch(executable, "cdp")
        except OSError as exc:
            return self._error("browser", f"Could not start Alpha's isolated browser: {exc}")

        startup_deadline = min(deadline, time.monotonic() + BROWSER_START_TIMEOUT_SECONDS)
        while time.monotonic() < startup_deadline:
            if interrupt_event is not None and interrupt_event.is_set():
                return self._error("browser", "Browser startup interrupted", interrupted=True)
            endpoint = self._healthy_endpoint()
            if endpoint is not None:
                self._manual_waiting = False
                self._last_endpoint = endpoint
                return endpoint
            returncode = process.poll()
            if returncode is not None:
                if returncode == 0:
                    return self._error("browser", "Alpha's CDP browser command was handed off without creating a usable endpoint.")
                return self._error(
                    "browser",
                    "Alpha's dedicated browser exited before it was ready for manual login or remote-debugging authorization.",
                    returncode=returncode,
                )
            time.sleep(0.05)
        return self._error("browser", "Alpha's CDP browser did not expose a usable endpoint before startup timed out.", timed_out=True)

    @staticmethod
    def _manual_login_required() -> dict[str, Any]:
        return {
            "success": False,
            "stage": "browser",
            "status": "user_action_required",
            "action": "manual_login",
            "recoverable": True,
            "error": "Complete the sign-in in the Alpha browser, then reply '继续'.",
        }

    @staticmethod
    def _missing_browser_error() -> dict[str, Any]:
        return BrowserHarnessRuntime._error(
            "browser",
            "No bundled Chrome for Testing or compatible local Chrome/Edge executable was found. "
            "Expected bundled path: tools/chrome-for-testing/chrome-win64/chrome.exe.",
        )

    def _healthy_endpoint(self) -> str | None:
        try:
            lines = (self.profile_dir / "DevToolsActivePort").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            port = int(lines[0].strip())
            if not 1 <= port <= 65535:
                return None
        except (OSError, ValueError, IndexError):
            return None
        if not self.browser.port_belongs_to_profile(port):
            return None
        endpoint = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{endpoint}/json/version", timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (OSError, ValueError, TypeError):
            return None
        websocket_url = payload.get("webSocketDebuggerUrl") if isinstance(payload, dict) else None
        return endpoint if isinstance(websocket_url, str) and websocket_url else None

    def _reload_daemon(
        self,
        cli: Path,
        deadline: float,
        interrupt_event: threading.Event | None,
    ) -> dict[str, Any]:
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            return self._error("timeout", "Browser mode switch timed out", timed_out=True)
        result = self._run_cli(
            [str(cli), "--reload"],
            input_text=None,
            timeout_seconds=max(1, min(10, remaining)),
            interrupt_event=interrupt_event,
            env=build_browser_harness_env(self.project_root, base_env=os.environ),
        )
        if result.get("success"):
            self._last_endpoint = None
        return result

    def _run_cli(
        self,
        command: list[str],
        *,
        input_text: str | None,
        timeout_seconds: int,
        interrupt_event: threading.Event | None,
        env: Mapping[str, str],
    ) -> dict[str, Any]:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(env),
                cwd=str(self.project_root),
            )
        except OSError as exc:
            return self._error("cli", f"Could not start Browser Harness: {exc}")

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        readers = [
            threading.Thread(target=self._read_stream, args=(process.stdout, stdout_parts), daemon=True),
            threading.Thread(target=self._read_stream, args=(process.stderr, stderr_parts), daemon=True),
        ]
        for reader in readers:
            reader.start()

        if input_text is not None and process.stdin is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
                process.stdin = None
            except OSError:
                pass

        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if interrupt_event is not None and interrupt_event.is_set():
                self._stop_cli_process(process)
                self._join_readers(readers)
                return self._process_result(
                    process,
                    "".join(stdout_parts),
                    "".join(stderr_parts),
                    interrupted=True,
                )
            if time.monotonic() >= deadline:
                self._stop_cli_process(process)
                self._join_readers(readers)
                return self._process_result(
                    process,
                    "".join(stdout_parts),
                    "".join(stderr_parts),
                    timed_out=True,
                    timeout_seconds=timeout_seconds,
                )
            time.sleep(0.05)
        self._join_readers(readers)
        return self._process_result(process, "".join(stdout_parts), "".join(stderr_parts))

    @staticmethod
    def _read_stream(stream, output: list[str]) -> None:
        if stream is None:
            return
        try:
            while chunk := stream.read(8192):
                output.append(chunk)
        except (OSError, ValueError):
            return

    @staticmethod
    def _join_readers(readers: list[threading.Thread]) -> None:
        for reader in readers:
            reader.join(timeout=2)

    @staticmethod
    def _stop_cli_process(process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _process_result(
        self,
        process: subprocess.Popen[str],
        stdout: str,
        stderr: str,
        **extra: Any,
    ) -> dict[str, Any]:
        stdout, stdout_truncated = self._truncate(stdout or "")
        stderr, stderr_truncated = self._truncate(stderr or "")
        return {
            "success": process.returncode == 0 and not extra.get("interrupted") and not extra.get("timed_out"),
            "stdout": stdout,
            "stderr": stderr,
            "returncode": process.returncode,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            **extra,
        }

    @staticmethod
    def _truncate(value: str) -> tuple[str, bool]:
        if len(value) <= MAX_OUTPUT_CHARS:
            return value, False
        half = MAX_OUTPUT_CHARS // 2
        return f"{value[:half]}\n... output truncated ...\n{value[-half:]}", True

    @staticmethod
    def _error(stage: str, message: str, **extra: Any) -> dict[str, Any]:
        return {"success": False, "stage": stage, "error": message, **extra}


def browser_scope_paths(root: Path, env: Mapping[str, str]) -> tuple[Path, Path]:
    state = root / "state" / "browser-harness"
    temp = root / "temp" / "browser-harness"
    return state, temp


def build_browser_harness_env(
    project_root: str | Path,
    *,
    cdp_url: str | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    root = Path(project_root).resolve()
    env = build_runtime_env(root, base_env=base_env or os.environ)
    state, temp = browser_scope_paths(root, env)
    env.update(
        {
            "BH_HOME": str(state),
            "BH_CONFIG_DIR": str(state),
            "BH_RUNTIME_DIR": str(state / "runtime"),
            "BH_TMP_DIR": str(temp),
            "BH_AGENT_WORKSPACE": str(state / "agent-workspace"),
            "BH_UPDATE_CHECK": "0",
            "BH_TELEMETRY": "0",
            "BH_RECORD": "0",
            "BH_DOMAIN_SKILLS": "0",
            "BU_NAME": "alpha-shared",
            "BU_AUTOSPAWN": "",
            "BU_BROWSER_ID": "",
            "BU_CDP_WS": "",
            "BROWSER_USE_API_KEY": "",
        }
    )
    if cdp_url:
        env["BU_CDP_URL"] = cdp_url
    else:
        env["BU_CDP_URL"] = ""
    return env


def find_browser_executable(project_root: str | Path, env: Mapping[str, str]) -> Path | None:
    root = Path(project_root).resolve()
    app_root = Path(env.get("AGENT_ALPHA_APP_ROOT") or root).resolve()
    bundled = app_root / "tools" / "chrome-for-testing" / "chrome-win64" / "chrome.exe"
    if bundled.is_file():
        return bundled

    candidates: list[Path] = []
    local_app_data = env.get("AGENT_ALPHA_HOST_LOCALAPPDATA") or env.get("LOCALAPPDATA")
    program_files = env.get("AGENT_ALPHA_HOST_PROGRAMFILES") or env.get("PROGRAMFILES")
    program_files_x86 = env.get("AGENT_ALPHA_HOST_PROGRAMFILES_X86") or env.get("PROGRAMFILES(X86)")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for base in (program_files, program_files_x86):
        if not base:
            continue
        base_path = Path(base)
        candidates.extend(
            [
                base_path / "Google" / "Chrome" / "Application" / "chrome.exe",
                base_path / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
    if os.name != "nt":
        for command in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(command)
            if found:
                candidates.append(Path(found))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


_RUNTIMES: dict[Path, BrowserHarnessRuntime] = {}
_RUNTIMES_LOCK = threading.Lock()


def get_browser_harness_runtime(project_root: str | Path) -> BrowserHarnessRuntime:
    key = Path(project_root).resolve()
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = BrowserHarnessRuntime(key)
            _RUNTIMES[key] = runtime
        return runtime


def shutdown_browser_harness_runtime(project_root: str | Path) -> dict[str, Any]:
    key = Path(project_root).resolve()
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = BrowserHarnessRuntime(key)
            _RUNTIMES[key] = runtime
    return runtime.shutdown()
