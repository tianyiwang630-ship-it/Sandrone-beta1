from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pytest

from agent.core.tool_loader import ToolLoader
from agent.tools import browser_harness_runtime as runtime_module
from agent.tools.browser_harness_browser import BrowserProcessDiscoveryError
from agent.tools.browser_harness_runtime import (
    BROWSER_HARNESS_VERSION,
    BrowserHarnessRuntime,
    build_browser_harness_env,
    find_browser_executable,
    get_browser_harness_runtime,
    shutdown_browser_harness_runtime,
)
from agent.tools.browser_harness_tool import BrowserHarnessTool
from agent.tools.browser_tool import BrowserNavigateTool


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class InputRecorder:
    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, value: str):
        self.value += value

    def close(self):
        self.closed = True


class FakeCliProcess:
    def __init__(self, *, running: bool = False, stdout: str = "ok", stderr: str = ""):
        self.stdin = InputRecorder()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = None if running else 0
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def make_runtime(tmp_path: Path) -> BrowserHarnessRuntime:
    return BrowserHarnessRuntime(tmp_path / "alpha")


def test_bundled_chrome_for_testing_has_priority(tmp_path: Path):
    root = tmp_path / "alpha"
    bundled = root / "tools" / "chrome-for-testing" / "chrome-win64" / "chrome.exe"
    fallback = tmp_path / "program-files" / "Google" / "Chrome" / "Application" / "chrome.exe"
    bundled.parent.mkdir(parents=True)
    fallback.parent.mkdir(parents=True)
    bundled.touch()
    fallback.touch()

    found = find_browser_executable(root, {"AGENT_ALPHA_HOST_PROGRAMFILES": str(tmp_path / "program-files")})

    assert found == bundled


def test_bundled_chrome_can_live_in_packaged_app_root(tmp_path: Path):
    data_root = tmp_path / "data"
    app_root = tmp_path / "resources" / "agent-alpha"
    bundled = app_root / "tools" / "chrome-for-testing" / "chrome-win64" / "chrome.exe"
    bundled.parent.mkdir(parents=True)
    bundled.touch()

    assert find_browser_executable(
        data_root,
        {"AGENT_ALPHA_APP_ROOT": str(app_root)},
    ) == bundled


def test_local_chrome_then_edge_are_development_fallbacks(tmp_path: Path):
    root = tmp_path / "alpha"
    program_files = tmp_path / "program-files"
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    edge = program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    chrome.parent.mkdir(parents=True)
    edge.parent.mkdir(parents=True)
    edge.touch()
    env = {"AGENT_ALPHA_HOST_PROGRAMFILES": str(program_files)}

    assert find_browser_executable(root, env) == edge

    chrome.touch()
    assert find_browser_executable(root, env) == chrome


def test_missing_browser_does_not_trigger_download(tmp_path: Path):
    assert find_browser_executable(tmp_path / "alpha", {}) is None


def test_cli_lookup_keeps_using_project_executable_when_browser_python_is_set(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = runtime.project_root / "bin" / "browser-harness.exe"
    browser_python = runtime.project_root / "tools" / "uv" / "browser-harness" / "Scripts" / "python.exe"
    cli.parent.mkdir(parents=True, exist_ok=True)
    browser_python.parent.mkdir(parents=True, exist_ok=True)
    cli.touch()
    browser_python.touch()
    monkeypatch.setenv("AGENT_ALPHA_BROWSER_PYTHON", str(browser_python))

    assert runtime._find_cli() == cli


def test_execute_passes_browser_harness_executable_as_one_command(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = runtime.project_root / "bin" / "browser-harness.exe"
    calls = []
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime, "_ensure_browser", lambda *_args, **_kwargs: "http://127.0.0.1:43210")
    monkeypatch.setattr(
        runtime,
        "_run_cli",
        lambda command, **_kwargs: calls.append(command) or {"success": True},
    )

    assert runtime.execute(code="print(1)", timeout_seconds=5)["success"] is True
    assert calls == [[str(cli)]]


def test_runtime_env_is_local_private_and_offline(tmp_path: Path):
    root = tmp_path / "alpha"
    env = build_browser_harness_env(
        root,
        cdp_url="http://127.0.0.1:43210",
        base_env={"PATH": "host-path", "BU_CDP_WS": "ws://do-not-use", "BROWSER_USE_API_KEY": "secret"},
    )

    assert env["BH_HOME"] == str(root.resolve() / "state" / "browser-harness")
    assert env["BH_RUNTIME_DIR"] == str(root.resolve() / "state" / "browser-harness" / "runtime")
    assert env["BH_TMP_DIR"] == str(root.resolve() / "temp" / "browser-harness")
    assert env["BH_AGENT_WORKSPACE"] == str(root.resolve() / "state" / "browser-harness" / "agent-workspace")
    assert env["BU_CDP_URL"] == "http://127.0.0.1:43210"
    assert env["BU_CDP_WS"] == ""
    assert env["BU_BROWSER_ID"] == ""
    assert env["BU_NAME"] == "alpha-shared"
    assert env["BU_AUTOSPAWN"] == ""
    assert env["BROWSER_USE_API_KEY"] == ""
    assert env["BH_UPDATE_CHECK"] == "0"
    assert env["BH_TELEMETRY"] == "0"
    assert env["BH_RECORD"] == "0"
    assert env["BH_DOMAIN_SKILLS"] == "0"


def test_healthy_devtools_active_port_reconnects_without_launch(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    port_file = runtime.profile_dir / "DevToolsActivePort"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text("43210\n/devtools/browser/id\n", encoding="utf-8")
    opened: list[str] = []

    def fake_urlopen(url, timeout):
        opened.append(url)
        return FakeResponse({"webSocketDebuggerUrl": "ws://127.0.0.1:43210/devtools/browser/id"})

    monkeypatch.setattr(runtime_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime.browser, "port_belongs_to_profile", lambda _port: True)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: "cdp")
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})
    cli = tmp_path / "browser-harness.exe"

    assert runtime._ensure_browser(cli, None, explicit_takeover=False, deadline=time.monotonic() + 5) == "http://127.0.0.1:43210"
    assert opened == ["http://127.0.0.1:43210/json/version"]


def test_stale_port_launches_dedicated_profile_with_random_debugging_port(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    stale = runtime.profile_dir / "DevToolsActivePort"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("11111\n", encoding="utf-8")
    executable = tmp_path / "chrome.exe"
    executable.touch()
    health = iter([None, "http://127.0.0.1:45678"])
    calls: list[tuple[Path, str]] = []

    class BrowserProcess:
        def poll(self):
            return None

    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: next(health))
    monkeypatch.setattr(runtime_module, "find_browser_executable", lambda *_args: executable)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: None)
    monkeypatch.setattr(runtime.browser, "disable_native_remote_debugging", lambda: {"success": True})
    monkeypatch.setattr(runtime.browser, "launch", lambda path, mode: calls.append((path, mode)) or BrowserProcess())
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})
    cli = tmp_path / "browser-harness.exe"

    assert runtime._ensure_browser(cli, None, explicit_takeover=False, deadline=time.monotonic() + 5) == "http://127.0.0.1:45678"
    assert not stale.exists()
    assert calls == [(executable, "cdp")]


def test_invalid_devtools_port_is_not_treated_as_browser(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    port_file = runtime.profile_dir / "DevToolsActivePort"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text("not-a-port", encoding="utf-8")

    assert runtime._healthy_endpoint() is None


def test_native_404_does_not_delete_devtools_active_port(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    port_file = runtime.profile_dir / "DevToolsActivePort"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text("43210\n/devtools/browser/native-id\n", encoding="utf-8")
    monkeypatch.setattr(runtime.browser, "port_belongs_to_profile", lambda _port: True)

    def missing_http_endpoint(*_args, **_kwargs):
        raise runtime_module.urllib.error.HTTPError("url", 404, "missing", {}, None)

    monkeypatch.setattr(runtime_module.urllib.request, "urlopen", missing_http_endpoint)

    assert runtime._healthy_endpoint() is None
    assert port_file.read_text(encoding="utf-8").startswith("43210\n")


def test_browser_start_failure_is_reported_without_process_scan_or_kill(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    executable = tmp_path / "chrome.exe"
    executable.touch()

    class ExitedBrowser:
        def poll(self):
            return 7

    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: None)
    monkeypatch.setattr(runtime_module, "find_browser_executable", lambda *_args: executable)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: None)
    monkeypatch.setattr(runtime.browser, "disable_native_remote_debugging", lambda: {"success": True})
    monkeypatch.setattr(runtime.browser, "launch", lambda *_args: ExitedBrowser())
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})

    result = runtime._ensure_browser(tmp_path / "browser-harness.exe", None, explicit_takeover=False, deadline=time.monotonic() + 5)

    assert result["success"] is False
    assert result["stage"] == "browser"
    assert "exited before it was ready" in result["error"]
    assert result["returncode"] == 7


def test_omitted_mode_does_not_take_over_manual_browser(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: "manual")

    result = runtime._ensure_browser(tmp_path / "browser-harness.exe", None, explicit_takeover=False, deadline=time.monotonic() + 5)

    assert result["success"] is False
    assert result["status"] == "user_action_required"
    assert result["action"] == "manual_login"
    assert result["recoverable"] is True
    assert "Alpha browser" in result["error"]


def test_process_local_manual_wait_blocks_retry_even_when_process_scan_would_fail(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    runtime._manual_waiting = True
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: pytest.fail("manual wait must be checked first"))

    result = runtime._ensure_browser(
        tmp_path / "browser-harness.exe",
        None,
        explicit_takeover=False,
        deadline=time.monotonic() + 5,
    )

    assert result["status"] == "user_action_required"
    assert result["action"] == "manual_login"


def test_process_discovery_failure_stops_before_browser_mutation(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    port_file = runtime.profile_dir / "DevToolsActivePort"
    runtime.profile_dir.mkdir(parents=True, exist_ok=True)
    port_file.write_text("43210\n/devtools/browser/test\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(
        runtime.browser,
        "current_mode",
        lambda: (_ for _ in ()).throw(BrowserProcessDiscoveryError("query failed")),
    )
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: pytest.fail("must not reload daemon"))
    monkeypatch.setattr(
        runtime.browser,
        "disable_native_remote_debugging",
        lambda: pytest.fail("must not modify browser profile"),
    )

    result = runtime.execute(code="print(list_tabs())")

    assert result["stage"] == "browser"
    assert result["recoverable"] is True
    assert port_file.is_file()


def test_cdp_command_handoff_without_endpoint_is_reported_as_failure(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    executable = tmp_path / "chrome.exe"
    executable.touch()

    class HandedOffBrowserCommand:
        def poll(self):
            return 0

    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: None)
    monkeypatch.setattr(runtime_module, "find_browser_executable", lambda *_args: executable)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: None)
    monkeypatch.setattr(runtime.browser, "disable_native_remote_debugging", lambda: {"success": True})
    monkeypatch.setattr(runtime.browser, "launch", lambda *_args: HandedOffBrowserCommand())
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})

    result = runtime._ensure_browser(tmp_path / "browser-harness.exe", None, explicit_takeover=True, deadline=time.monotonic() + 5)

    assert result["success"] is False
    assert "without creating a usable endpoint" in result["error"]


def test_cli_receives_utf8_multiline_code_on_stdin(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    process = FakeCliProcess(stdout="完成")
    stdin = process.stdin
    calls: list[dict] = []

    def fake_popen(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return process

    monkeypatch.setattr(runtime_module.subprocess, "Popen", fake_popen)
    result = runtime._run_cli(
        ["browser-harness"],
        input_text='print("中文")\nprint(page_info())',
        timeout_seconds=2,
        interrupt_event=None,
        env={"PATH": "test"},
    )

    assert result["success"] is True
    assert result["stdout"] == "完成"
    assert stdin.value == 'print("中文")\nprint(page_info())'
    assert stdin.closed is True
    assert calls[0]["encoding"] == "utf-8"
    assert calls[0]["text"] is True


def test_manual_mode_rejects_code_before_touching_browser(tmp_path: Path):
    runtime = make_runtime(tmp_path)

    result = runtime.execute(mode="manual", code="print(page_info())")

    assert result["success"] is False
    assert result["stage"] == "validation"


def test_cdp_mode_requires_code(tmp_path: Path):
    runtime = make_runtime(tmp_path)

    result = runtime.execute(mode="cdp")

    assert result["success"] is False
    assert result["stage"] == "validation"


def test_manual_mode_stops_daemon_and_launches_plain_browser(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    executable = tmp_path / "chrome.exe"
    executable.touch()
    launched = []
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: None)
    monkeypatch.setattr(runtime.browser, "disable_native_remote_debugging", lambda: {"success": True})
    monkeypatch.setattr(runtime.browser, "launch", lambda path, mode: launched.append((path, mode)))
    monkeypatch.setattr(runtime_module, "find_browser_executable", lambda *_args: executable)

    result = runtime.execute(mode="manual")

    assert result["status"] == "user_action_required"
    assert result["action"] == "manual_login"
    assert launched == [(executable, "manual")]


def test_manual_mode_reuses_plain_browser_after_backend_restart(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    reloaded = []
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: "manual")
    monkeypatch.setattr(runtime.browser, "native_remote_debugging_enabled", lambda: False)
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: reloaded.append(True) or {"success": True})
    monkeypatch.setattr(runtime.browser, "close", lambda **_kwargs: pytest.fail("must preserve manual window"))
    monkeypatch.setattr(runtime.browser, "launch", lambda *_args: pytest.fail("must not relaunch"))

    result = runtime.execute(mode="manual")

    assert result["action"] == "manual_login"
    assert reloaded == [True]


def test_explicit_cdp_takes_over_manual_browser_but_omitted_mode_waits(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    modes = iter(["manual", "manual"])
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime.browser, "current_mode", lambda: next(modes))
    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: pytest.fail("omitted mode must not inspect CDP"))

    waiting = runtime.execute(code="print(page_info())")

    assert waiting["action"] == "manual_login"

    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: "http://127.0.0.1:43210")
    monkeypatch.setattr(runtime, "_reload_daemon", lambda *_args: {"success": True})
    monkeypatch.setattr(runtime.browser, "close", lambda **_kwargs: {"success": True})
    monkeypatch.setattr(runtime.browser, "disable_native_remote_debugging", lambda: {"success": True})
    monkeypatch.setattr(runtime.browser, "launch", lambda *_args: FakeCliProcess())
    monkeypatch.setattr(runtime_module, "find_browser_executable", lambda *_args: tmp_path / "chrome.exe")
    monkeypatch.setattr(runtime, "_run_cli", lambda *_args, **_kwargs: {"success": True, "stdout": "ready"})

    result = runtime.execute(mode="cdp", code="print(page_info())")

    assert result["success"] is True


def test_interrupt_stops_only_current_cli_process(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    process = FakeCliProcess(running=True)
    interrupt = threading.Event()
    interrupt.set()
    monkeypatch.setattr(runtime_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = runtime._run_cli(
        ["browser-harness"],
        input_text="wait(100)",
        timeout_seconds=2,
        interrupt_event=interrupt,
        env={},
    )

    assert result["success"] is False
    assert result["interrupted"] is True
    assert process.terminated is True


def test_timeout_stops_current_cli_and_reports_limit(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    process = FakeCliProcess(running=True)
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(runtime_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: next(clock))

    result = runtime._run_cli(
        ["browser-harness"],
        input_text="wait(100)",
        timeout_seconds=1,
        interrupt_event=None,
        env={},
    )

    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 1
    assert process.terminated is True


def test_long_output_is_truncated_from_middle(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    process = FakeCliProcess(stdout="a" * 60_000)
    monkeypatch.setattr(runtime_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = runtime._run_cli(
        ["browser-harness"], input_text="print('x')", timeout_seconds=2, interrupt_event=None, env={}
    )

    assert result["success"] is True
    assert result["stdout_truncated"] is True
    assert "output truncated" in result["stdout"]
    assert len(result["stdout"]) < 51_000


def test_all_web_agents_share_one_serial_browser_channel(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    active = 0
    max_active = 0
    guard = threading.Lock()

    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime, "_ensure_browser", lambda *_args, **_kwargs: "http://127.0.0.1:43210")

    def fake_run(*_args, **_kwargs):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with guard:
            active -= 1
        return {"success": True}

    monkeypatch.setattr(runtime, "_run_cli", fake_run)
    results: list[dict] = []
    threads = [
        threading.Thread(target=lambda: results.append(runtime.execute(code="print(1)", timeout_seconds=2)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1
    assert len(results) == 2
    assert all(result["success"] for result in results)


def test_tool_instances_share_runtime_for_same_alpha_root(tmp_path: Path):
    root = tmp_path / "alpha"

    first = BrowserHarnessTool(project_root=root)
    second = BrowserHarnessTool(project_root=root)

    assert first.runtime is second.runtime
    assert first.runtime is get_browser_harness_runtime(root)


def test_lock_wait_timeout_is_recoverable(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    runtime._lock.acquire()
    clock = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: next(clock))
    try:
        result = runtime.execute(code="print(1)", timeout_seconds=1)
    finally:
        runtime._lock.release()

    assert result["success"] is False
    assert result["stage"] == "lock"
    assert result["timed_out"] is True
    assert "Retry" in result["error"]


def test_exception_releases_shared_lock(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    monkeypatch.setattr(runtime, "_verify_cli", lambda: cli)
    monkeypatch.setattr(runtime, "_ensure_browser", lambda *_args, **_kwargs: "http://127.0.0.1:43210")
    monkeypatch.setattr(runtime, "_run_cli", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = runtime.execute(code="print(1)", timeout_seconds=1)

    assert result["success"] is False
    assert result["stage"] == "runtime"
    assert runtime._lock.acquire(blocking=False) is True
    runtime._lock.release()


def test_shutdown_closes_alpha_browser_then_reloads_daemon(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    runtime._used = True
    cli = tmp_path / "browser-harness.exe"
    cli.touch()
    runtime._cli_path = cli
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: "http://127.0.0.1:43210")

    def fake_run(command, *, input_text, **_kwargs):
        calls.append((command, input_text))
        return {"success": True}

    monkeypatch.setattr(runtime, "_run_cli", fake_run)

    result = runtime.shutdown()

    assert result["success"] is True
    assert calls == [([str(cli)], 'cdp("Browser.close")'), ([str(cli), "--reload"], None)]


def test_shutdown_checks_healthy_endpoint_even_before_successful_tool_use(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    cli.touch()
    runtime._cli_path = cli
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: "http://127.0.0.1:43210")
    monkeypatch.setattr(
        runtime,
        "_run_cli",
        lambda command, *, input_text, **_kwargs: calls.append((command, input_text)) or {"success": True},
    )

    result = runtime.shutdown()

    assert result["success"] is True
    assert calls == [([str(cli)], 'cdp("Browser.close")'), ([str(cli), "--reload"], None)]


def test_shutdown_without_debug_endpoint_only_reloads_daemon(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = tmp_path / "browser-harness.exe"
    cli.touch()
    runtime._cli_path = cli
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(runtime, "_healthy_endpoint", lambda: None)
    monkeypatch.setattr(
        runtime,
        "_run_cli",
        lambda command, *, input_text, **_kwargs: calls.append((command, input_text)) or {"success": True},
    )

    result = runtime.shutdown()

    assert result["success"] is True
    assert result["browser_close"]["skipped"] is True
    assert calls == [([str(cli), "--reload"], None)]


def test_shutdown_entrypoint_creates_runtime_to_clean_previous_process_state(tmp_path: Path, monkeypatch):
    root = (tmp_path / "alpha").resolve()
    runtime_module._RUNTIMES.pop(root, None)
    seen = []
    monkeypatch.setattr(
        BrowserHarnessRuntime,
        "shutdown",
        lambda self: seen.append(self.project_root) or {"success": True},
    )

    result = shutdown_browser_harness_runtime(root)

    assert result["success"] is True
    assert seen == [root]
    assert runtime_module._RUNTIMES[root].project_root == root


def test_tool_loader_registers_only_browser_harness_by_default(tmp_path: Path, monkeypatch):
    loader = ToolLoader(project_root=tmp_path, enable_permissions=False)
    monkeypatch.setattr(loader, "_load_mcp_tools", lambda: None)
    monkeypatch.setattr(loader, "_load_skills", lambda: None)

    tools = loader.load_all()
    names = {tool["function"]["name"] for tool in tools}

    assert "browser_harness_exec" in names
    assert not names.intersection(
        {
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_press",
            "browser_close",
            "profile_list",
            "profile_create",
            "profile_login_headed",
            "profile_save_headed",
            "profile_close_headed",
            "profile_force_close_headed",
            "browser_connect_cdp",
            "browser_disconnect_cdp",
            "browser_cdp_status",
        }
    )
    assert BrowserNavigateTool().name == "browser_navigate"


def test_cli_version_mismatch_is_actionable(tmp_path: Path, monkeypatch):
    runtime = make_runtime(tmp_path)
    cli = runtime.project_root / "bin" / "browser-harness.exe"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.touch()

    class Completed:
        returncode = 0
        stdout = "9.9.9\n"
        stderr = ""

    monkeypatch.setattr(runtime_module.subprocess, "run", lambda *_args, **_kwargs: Completed())

    result = runtime._verify_cli()

    assert result["success"] is False
    assert result["expected_version"] == BROWSER_HARNESS_VERSION
    assert result["found_version"] == "9.9.9"
    assert "setup-agent-alpha.ps1" in result["error"]


def test_builtin_skill_uses_tool_not_heredoc():
    skill = Path(__file__).resolve().parents[2] / "skills" / "browser-harness" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")

    assert "browser_harness_exec" in text
    assert "<<'PY'" not in text
    assert "Git Bash" in text
    assert 'mode="manual"' in text
    assert "user_action_required" in text
    assert "the same sign-in state twice" in text
