import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.core.tool_loader import ToolLoader
from agent.tools import browser_manager as browser_manager_module
from agent.tools.browser_manager import BrowserManager, BrowserSession
from agent.tools.browser_tool import ProfileForceCloseHeadedTool


class FakeCompletedProcess:
    def __init__(self, cmd, *, stdout, env, calls):
        self.pid = 4321
        self.returncode = 0
        calls.append({"cmd": list(cmd), "env": dict(env)})
        payload = {
            "success": True,
            "browser_pid": self.pid,
            "data": {
                "url": "about:blank",
                "title": "ok",
                "snapshot": "- button \"OK\" [ref=ok]\n- link \"Docs\" [ref=docs]",
                "refs": {"ok": {"kind": "button"}, "docs": {"kind": "link"}},
            },
        }
        stdout.write(json.dumps(payload) + "\n")
        stdout.flush()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class FakeHangingProcess:
    def __init__(self, cmd, *, stdout, env, calls):
        self.pid = 9876
        self.returncode = None
        calls.append({"cmd": list(cmd), "env": dict(env)})

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def browser_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(BrowserManager, "_cleanup_stale_browser_state", lambda self: None)
    monkeypatch.setattr(BrowserManager, "_command_prefix", lambda self: ["agent-browser"])
    monkeypatch.setattr(BrowserManager, "_build_headless_base", lambda self, profile: None)
    monkeypatch.setattr(BrowserManager, "_profile_has_headless_browser", lambda self, profile_dir: False)

    def fake_prepare_runtime_profile(self, session):
        runtime = self._session_runtime_dir(session.session_id)
        profile_dir = runtime / "user-data"
        profile_dir.mkdir(parents=True, exist_ok=True)
        session.runtime_dir = runtime
        session.profile_dir = profile_dir
        self._write_session_metadata(session, "starting")
        return None

    monkeypatch.setattr(BrowserManager, "_prepare_runtime_profile", fake_prepare_runtime_profile)
    return BrowserManager(tmp_path)


@pytest.fixture
def completed_agent_browser(monkeypatch):
    calls = []

    def fake_popen(cmd, stdin=None, stdout=None, stderr=None, env=None, **kwargs):
        return FakeCompletedProcess(cmd, stdout=stdout, env=env, calls=calls)

    monkeypatch.setattr(browser_manager_module.subprocess, "Popen", fake_popen)
    return calls


def assert_headed_call(call):
    assert call["env"]["AGENT_BROWSER_HEADED"] == "true"
    assert "--headed" in call["cmd"]


def assert_headless_call(call):
    assert call["env"]["AGENT_BROWSER_HEADED"] == "false"
    assert "--headed" not in call["cmd"]


def test_start_headed_login_sets_headed_env(browser_manager, completed_agent_browser):
    result = browser_manager.start_headed_login(profile="default", url="https://example.com")

    assert result["success"] is True
    assert_headed_call(completed_agent_browser[0])


def test_headed_session_keeps_headed_across_multi_turn_operations(browser_manager, completed_agent_browser):
    started = browser_manager.start_headed_login(profile="default", url="https://example.com")
    session_id = started["session_id"]
    completed_agent_browser.clear()

    browser_manager.snapshot_current(session_id=session_id)
    browser_manager.run_current(["open", "https://example.com/search"], session_id=session_id)
    browser_manager.snapshot_current(session_id=session_id)
    browser_manager.run_current(["click", "ok"], session_id=session_id)
    browser_manager.snapshot_current(session_id=session_id)

    assert len(completed_agent_browser) == 5
    for call in completed_agent_browser:
        assert_headed_call(call)


def test_headed_and_headless_sessions_do_not_leak_modes(browser_manager, completed_agent_browser):
    headless = browser_manager.start_headless("https://example.com", profile="default")
    headed = browser_manager.start_headed_login(profile="default", url="https://example.com/login")
    completed_agent_browser.clear()

    browser_manager.run_current(["get", "url"], session_id=headless["session_id"])
    browser_manager.run_current(["get", "url"], session_id=headed["session_id"])

    assert_headless_call(completed_agent_browser[0])
    assert_headed_call(completed_agent_browser[1])


def test_second_alpha_can_start_headless_without_inheriting_headed_lock(monkeypatch, tmp_path, completed_agent_browser):
    monkeypatch.setattr(BrowserManager, "_cleanup_stale_browser_state", lambda self: None)
    monkeypatch.setattr(BrowserManager, "_command_prefix", lambda self: ["agent-browser"])
    monkeypatch.setattr(BrowserManager, "_build_headless_base", lambda self, profile: None)
    monkeypatch.setattr(BrowserManager, "_profile_has_headless_browser", lambda self, profile_dir: False)

    def fake_prepare_runtime_profile(self, session):
        runtime = self._session_runtime_dir(session.session_id)
        profile_dir = runtime / "user-data"
        profile_dir.mkdir(parents=True, exist_ok=True)
        session.runtime_dir = runtime
        session.profile_dir = profile_dir
        return None

    monkeypatch.setattr(BrowserManager, "_prepare_runtime_profile", fake_prepare_runtime_profile)
    first_alpha = BrowserManager(tmp_path)
    second_alpha = BrowserManager(tmp_path)

    assert first_alpha.start_headed_login(profile="default", url="https://example.com")["success"] is True
    completed_agent_browser.clear()

    result = second_alpha.start_headless("https://example.com/headless", profile="default")

    assert result["success"] is True
    assert_headless_call(completed_agent_browser[0])


def test_cdp_session_does_not_force_headed_or_profile_lifecycle(browser_manager, completed_agent_browser):
    cdp = browser_manager.connect_cdp("http://127.0.0.1:9222")
    cdp_session_id = cdp["session_id"]

    assert cdp["success"] is True
    assert_headless_call(completed_agent_browser[0])
    assert "--cdp" in completed_agent_browser[0]["cmd"]
    assert "--profile" not in completed_agent_browser[0]["cmd"]

    browser_manager.run_current(["get", "url"], session_id=cdp_session_id)
    assert_headless_call(completed_agent_browser[1])

    assert browser_manager.disconnect_cdp(cdp_session_id)["success"] is True
    completed_agent_browser.clear()

    headless = browser_manager.start_headless("https://example.com", profile="default")
    headed = browser_manager.start_headed_login(profile="default", url="https://example.com/login")

    assert_headless_call(completed_agent_browser[0])
    assert_headed_call(completed_agent_browser[1])
    assert headless["mode"] == "local-headless"
    assert headed["mode"] == "local-headed-login"


def test_interrupt_only_stops_current_command_without_mutating_session_or_lock(monkeypatch, browser_manager):
    calls = []

    def fake_popen(cmd, stdin=None, stdout=None, stderr=None, env=None, **kwargs):
        return FakeHangingProcess(cmd, stdout=stdout, env=env, calls=calls)

    def fake_terminate(proc):
        proc.returncode = -15

    monkeypatch.setattr(browser_manager_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(browser_manager_module, "terminate_process_tree", fake_terminate)
    browser_manager.interrupt_event = threading.Event()
    browser_manager.interrupt_event.set()
    session = browser_manager._new_session(
        "local-headed-login",
        "default",
        profile_dir=browser_manager._profile_dir("default"),
    )
    browser_manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-alpha",
            "owner_pid": 123456,
            "session_id": "other-session",
            "profile": "default",
            "profile_dir": str(browser_manager._profile_dir("default")),
        }
    )

    result = browser_manager._run_cli(session, ["snapshot"], timeout=30)

    assert result["interrupted"] is True
    assert browser_manager.active_sessions[session.session_id].mode == "local-headed-login"
    assert browser_manager._read_interactive_lock()["owner_id"] == "other-alpha"
    assert_headed_call(calls[0])


def test_headed_launch_fails_and_releases_lock_when_real_process_is_headless(
    monkeypatch,
    browser_manager,
    completed_agent_browser,
):
    monkeypatch.setattr(BrowserManager, "_profile_has_headless_browser", lambda self, profile_dir: True)

    result = browser_manager.start_headed_login(profile="default", url="https://example.com")

    assert result["success"] is False
    assert "headless Chrome process" in result["error"]
    assert browser_manager._read_interactive_lock() is None
    assert result["session_id"] not in browser_manager.active_sessions
    assert_headed_call(completed_agent_browser[0])


def test_plain_navigate_creates_headless_session_with_headless_env(browser_manager, completed_agent_browser):
    result = browser_manager.start_headless("https://example.com", profile="default")

    assert result["success"] is True
    assert result["mode"] == "local-headless"
    assert_headless_call(completed_agent_browser[0])


def test_cdp_ignores_explicit_headed_flag(browser_manager, completed_agent_browser):
    session = BrowserSession(
        session_id="cdp1",
        mode="external-cdp",
        profile=None,
        cdp_url="http://127.0.0.1:9222",
    )
    browser_manager.active_sessions[session.session_id] = session

    result = browser_manager._run_cli(session, ["get", "url"], headed=True)

    assert result["success"] is True
    assert_headless_call(completed_agent_browser[0])


def test_force_close_headed_requires_user_confirmation(monkeypatch, browser_manager):
    called = {"terminate": False}
    browser_manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-alpha",
            "owner_pid": os.getpid(),
            "session_id": "old-session",
            "profile": "default",
            "profile_dir": str(browser_manager._profile_dir("default")),
        }
    )
    monkeypatch.setattr(BrowserManager, "_terminate_alpha_browser_processes_using_path", lambda self, path: called.update(terminate=True))

    result = browser_manager.profile_force_close_headed(user_confirmed_close_visible_browser=False)

    assert result["success"] is False
    assert called["terminate"] is False
    assert browser_manager._read_interactive_lock()["session_id"] == "old-session"


def test_force_close_headed_closes_other_alpha_lock_without_local_session(monkeypatch, browser_manager):
    paths = []
    (browser_manager._headless_base_dir("default") / "Default").mkdir(parents=True)
    (browser_manager._headless_base_next_dir("default") / "Default").mkdir(parents=True)
    browser_manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-alpha",
            "owner_pid": 999999,
            "session_id": "old-session",
            "profile": "default",
            "profile_dir": str(browser_manager._profile_dir("default")),
        }
    )
    monkeypatch.setattr(BrowserManager, "_headed_browser_is_alive", lambda self, lock: True)
    monkeypatch.setattr(BrowserManager, "_alpha_browser_process_using_path", lambda self, path: False)

    def fake_terminate(self, path):
        paths.append(Path(path))
        return 2

    monkeypatch.setattr(BrowserManager, "_terminate_alpha_browser_processes_using_path", fake_terminate)

    result = browser_manager.profile_force_close_headed(user_confirmed_close_visible_browser=True)

    assert result["success"] is True
    assert result["closed"] is True
    assert result["stopped_processes"] == 2
    assert result["profile"] == "default"
    assert paths == [browser_manager._profile_dir("default")]
    assert browser_manager._read_interactive_lock() is None
    assert not browser_manager._headless_base_dir("default").exists()
    assert not browser_manager._headless_base_next_dir("default").exists()


def test_force_close_headed_refuses_cdp_lock(monkeypatch, browser_manager):
    called = {"terminate": False}
    browser_manager._write_interactive_lock(
        {
            "kind": "cdp",
            "status": "running",
            "owner_id": "other-alpha",
            "owner_pid": os.getpid(),
            "session_id": "cdp-session",
            "cdp_url": "http://127.0.0.1:9222",
        }
    )
    monkeypatch.setattr(BrowserManager, "_terminate_alpha_browser_processes_using_path", lambda self, path: called.update(terminate=True))

    result = browser_manager.profile_force_close_headed(user_confirmed_close_visible_browser=True)

    assert result["success"] is False
    assert "not a headed browser" in result["error"]
    assert called["terminate"] is False
    assert browser_manager._read_interactive_lock()["kind"] == "cdp"


def test_force_close_headed_refuses_running_startup(monkeypatch, browser_manager):
    called = {"terminate": False}
    browser_manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "starting",
            "owner_id": "other-alpha",
            "owner_pid": os.getpid(),
            "session_id": "starting-session",
            "profile": "default",
            "profile_dir": str(browser_manager._profile_dir("default")),
        }
    )
    monkeypatch.setattr(BrowserManager, "_alpha_browser_process_using_path", lambda self, path: False)
    monkeypatch.setattr(BrowserManager, "_terminate_alpha_browser_processes_using_path", lambda self, path: called.update(terminate=True))

    result = browser_manager.profile_force_close_headed(user_confirmed_close_visible_browser=True)

    assert result["success"] is False
    assert "still starting" in result["error"]
    assert called["terminate"] is False
    assert browser_manager._read_interactive_lock()["session_id"] == "starting-session"


def test_force_close_headed_keeps_lock_when_process_survives(monkeypatch, browser_manager):
    browser_manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-alpha",
            "owner_pid": 999999,
            "session_id": "stuck-session",
            "profile": "default",
            "profile_dir": str(browser_manager._profile_dir("default")),
        }
    )
    monkeypatch.setattr(BrowserManager, "_headed_browser_is_alive", lambda self, lock: True)
    monkeypatch.setattr(BrowserManager, "_terminate_alpha_browser_processes_using_path", lambda self, path: 0)
    monkeypatch.setattr(BrowserManager, "_alpha_browser_process_using_path", lambda self, path: True)

    result = browser_manager.profile_force_close_headed(
        user_confirmed_close_visible_browser=True,
        wait_timeout=0.01,
    )

    assert result["success"] is False
    assert "still running" in result["error"]
    assert browser_manager._read_interactive_lock()["session_id"] == "stuck-session"


def test_force_close_headed_kills_only_processes_for_locked_profile(monkeypatch, browser_manager):
    killed_pids = []
    target = browser_manager._profile_dir("default")
    other_profile = browser_manager.profiles_dir / "other" / "user-data"
    normal_chrome = "C:\\Users\\20157\\AppData\\Local\\Google\\Chrome\\User Data"
    process_rows = [
        {"ProcessId": 101, "CommandLine": f'chrome.exe --user-data-dir="{target}"'},
        {"ProcessId": 102, "CommandLine": f'chrome.exe --type=renderer --user-data-dir="{target}"'},
        {"ProcessId": 201, "CommandLine": f'chrome.exe --user-data-dir="{other_profile}"'},
        {"ProcessId": 301, "CommandLine": f'chrome.exe --user-data-dir="{normal_chrome}"'},
    ]

    def fake_run(cmd, **kwargs):
        if cmd[0] == "powershell.exe":
            return SimpleNamespace(stdout=json.dumps(process_rows), returncode=0)
        if cmd[0] == "taskkill":
            killed_pids.append(int(cmd[2]))
            return SimpleNamespace(stdout="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(browser_manager_module.subprocess, "run", fake_run)

    stopped = browser_manager._terminate_alpha_browser_processes_using_path(target)

    assert stopped == 2
    assert killed_pids == [101, 102]


def test_force_close_headed_no_lock_is_noop(browser_manager):
    result = browser_manager.profile_force_close_headed(user_confirmed_close_visible_browser=True)

    assert result["success"] is True
    assert result["closed"] is False
    assert result["interactive_lock_released"] is False


def test_force_close_headed_tool_is_preserved_but_not_registered():
    assert "profile_force_close_headed" not in ToolLoader.TOOL_GROUPS
    assert ("agent.tools.browser_tool", "ProfileForceCloseHeadedTool", {}) not in ToolLoader.BUILTIN_TOOLS
    assert ProfileForceCloseHeadedTool().name == "profile_force_close_headed"


def test_force_close_headed_tool_schema_has_no_profile_parameter():
    definition = ProfileForceCloseHeadedTool().get_tool_definition()
    properties = definition["function"]["parameters"]["properties"]

    assert set(properties) == {"user_confirmed_close_visible_browser"}
    assert definition["function"]["parameters"]["required"] == ["user_confirmed_close_visible_browser"]
