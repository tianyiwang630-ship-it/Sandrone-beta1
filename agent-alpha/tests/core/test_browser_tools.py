from pathlib import Path
import json
import shutil
import sys
import threading


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.core.role_config import RoleConfig
from agent.core.tool_loader import ToolLoader
import agent.tools.browser_manager as browser_manager_module
from agent.tools.browser_manager import BrowserManager
from agent.tools.browser_tool import BrowserNavigateTool, BrowserSnapshotTool


class FakeBrowserProc:
    def __init__(self):
        self.pid = 23456
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -1
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_browser_manager_creates_default_profile(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)

    profiles = manager.list_profiles()
    assert [item["name"] for item in profiles] == ["default"]
    assert (project_root / "state" / "browser" / "profiles.json").exists()
    assert (project_root / "state" / "browser" / "profiles" / "default").exists()
    assert (project_root / "state" / "browser" / "profiles" / "default" / "user-data").exists()
    assert profiles[0]["profile_dir"] == "state/browser/profiles/default/user-data"


def test_browser_manager_initialization_keeps_unowned_runtime_state_and_profiles(tmp_path):
    project_root = tmp_path / "project"
    browser_root = project_root / "state" / "browser"
    runtime_file = browser_root / "runtime" / "old-session" / "marker.txt"
    session_file = browser_root / "sessions" / "old.json"
    socket_file = browser_root / "sockets" / "old" / "_stdout.txt"
    download_file = browser_root / "downloads" / "old" / "paper.pdf"
    profile_file = browser_root / "profiles" / "default" / "user-data" / "Preferences"
    for path in [runtime_file, session_file, socket_file, download_file, profile_file]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep-or-clean", encoding="utf-8")

    BrowserManager(project_root)

    assert runtime_file.exists()
    assert session_file.exists()
    assert socket_file.exists()
    assert download_file.exists()
    assert profile_file.exists()


def test_headless_navigation_uses_temporary_profile_copy(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    manager.ensure_profile("work")
    profile_dir = project_root / "state" / "browser" / "profiles" / "work" / "user-data"
    marker = profile_dir / "marker.txt"
    marker.write_text("login-state", encoding="utf-8")

    calls = []

    def fake_run(session, command_args, timeout=60, headed=False):
        calls.append((session.session_id, list(command_args), headed))
        if command_args[:1] == ["snapshot"]:
            raise AssertionError("browser_navigate must not collect a page snapshot")
        return {"success": True, "data": {"command": command_args}}

    manager._run_cli = fake_run
    result = manager.start_headless("https://example.com", profile="work")

    assert result["success"] is True
    assert result["profile"] == "work"
    assert result["profile_dir"] == str(profile_dir)
    assert result["runtime_profile_dir"] != str(profile_dir)
    assert (Path(result["runtime_profile_dir"]) / "marker.txt").read_text(encoding="utf-8") == "login-state"
    assert calls[0][1] == ["open", "https://example.com"]
    assert len(calls) == 1
    assert calls[0][2] is False
    assert "snapshot" not in result
    assert "browser_snapshot" in result["next_step"]

    closed = manager.close(result["session_id"])

    assert closed["temporary_profile_removed"] is True
    assert not Path(result["runtime_profile_dir"]).parent.exists()


def test_browser_manager_initialization_cleans_dead_owner_runtime_but_not_live_owner(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    browser_root = project_root / "state" / "browser"
    dead_runtime = browser_root / "runtime" / "dead-session" / "user-data" / "marker.txt"
    live_runtime = browser_root / "runtime" / "live-session" / "user-data" / "marker.txt"
    dead_socket = browser_root / "sockets" / "dead-session" / "_stdout.txt"
    live_socket = browser_root / "sockets" / "live-session" / "_stdout.txt"
    for path in [dead_runtime, live_runtime, dead_socket, live_socket]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("state", encoding="utf-8")
    sessions_dir = browser_root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "dead-session.json").write_text(
        json.dumps({"session_id": "dead-session", "owner_pid": 111, "owner_id": "111-dead", "mode": "local-headless"}),
        encoding="utf-8",
    )
    (sessions_dir / "live-session.json").write_text(
        json.dumps({"session_id": "live-session", "owner_pid": 222, "owner_id": "222-live", "mode": "local-headless"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(BrowserManager, "_is_owner_process_alive", lambda self, pid: pid == 222)

    BrowserManager(project_root)

    assert not (browser_root / "runtime" / "dead-session").exists()
    assert not (browser_root / "sockets" / "dead-session").exists()
    assert not (sessions_dir / "dead-session.json").exists()
    assert live_runtime.exists()
    assert live_socket.exists()
    assert (sessions_dir / "live-session.json").exists()


def test_browser_manager_initialization_does_not_delete_damaged_session_metadata(tmp_path):
    project_root = tmp_path / "project"
    browser_root = project_root / "state" / "browser"
    runtime_file = browser_root / "runtime" / "mystery" / "user-data" / "marker.txt"
    session_file = browser_root / "sessions" / "mystery.json"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text("state", encoding="utf-8")
    session_file.write_text("{not-json", encoding="utf-8")

    BrowserManager(project_root)

    assert runtime_file.exists()
    assert session_file.exists()


def test_browser_snapshot_compacts_noisy_snapshot_but_keeps_action_refs_and_unicode(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    manager._new_session("local-headless", "default")
    refs = {
        **{f"e{i}": {"role": "link", "name": f"Job {i} 护士 😊"} for i in range(120)},
        "search": {"role": "textbox", "name": "Search input"},
        "submit": {"role": "button", "name": "Submit"},
        "noise": {"role": "generic", "name": "footer spam"},
    }
    useful_lines = [
        '- heading "Main results" [level=1, ref=e999]',
        '- textbox "Search input" [ref=search]',
        '- button "Submit" [ref=submit]',
    ]
    useful_lines.extend(f'- link "Job {i} 护士 😊" [ref=e{i}]' for i in range(120))
    noisy_lines = [
        '- generic "' + ("footer spam copyright newsletter " * 30) + f'{i}" [ref=noise]'
        for i in range(80)
    ]
    long_unexpected_line = '- generic "' + ("unexpected single line " * 700) + '"'
    snapshot = "\n".join(noisy_lines[:40] + useful_lines + noisy_lines[40:] + [long_unexpected_line])

    def fake_run(session, command_args, timeout=60, headed=False):
        assert command_args == ["snapshot", "-i"]
        return {
            "success": True,
            "data": {
                "origin": "https://example.com/jobs",
                "snapshot": snapshot,
                "refs": refs,
            },
        }

    manager._run_cli = fake_run

    result = manager.snapshot_current(save_full=False)

    assert result["success"] is True
    assert result["origin"] == "https://example.com/jobs"
    assert result["truncated"] is True
    assert result["original_chars"] == len(snapshot)
    assert result["returned_chars"] <= 8000
    assert len(result["snapshot"]) <= 8000
    assert 'textbox "Search input" [ref=search]' in result["snapshot"]
    assert 'button "Submit" [ref=submit]' in result["snapshot"]
    assert 'link "Job 0 护士 😊" [ref=e0]' in result["snapshot"]
    assert "footer spam copyright newsletter" not in result["snapshot"]
    assert "unexpected single line" not in result["snapshot"]
    assert result["refs"]["search"]["role"] == "textbox"
    assert result["refs"]["submit"]["role"] == "button"
    assert "noise" not in result["refs"]


def test_browser_snapshot_save_full_writes_complete_utf8_file_without_returning_body(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    session = manager._new_session("local-headless", "default")
    full_snapshot = ("FULL SNAPSHOT 中文 😊\n" * 2000) + "tail marker"

    def fake_run(run_session, command_args, timeout=60, headed=False):
        assert run_session.session_id == session.session_id
        assert command_args == ["snapshot"]
        return {
            "success": True,
            "data": {
                "origin": "https://example.com/full",
                "snapshot": full_snapshot,
                "refs": {"e1": {"role": "link", "name": "keep"}},
            },
        }

    manager._run_cli = fake_run

    result = manager.snapshot_current(save_full=True)

    snapshot_file = project_root / result["snapshot_file"]
    saved_text = snapshot_file.read_text(encoding="utf-8")
    result_json = json.dumps(result, ensure_ascii=False)
    assert result["success"] is True
    assert result["original_chars"] == len(full_snapshot)
    assert result["returned_chars"] < 1200
    assert snapshot_file.exists()
    assert "temp/browser_snapshots/" in result["snapshot_file"]
    assert "FULL SNAPSHOT 中文 😊" in saved_text
    assert "tail marker" in saved_text
    assert "FULL SNAPSHOT 中文 😊" not in result_json


def test_browser_snapshot_tool_prefers_save_full_name_but_accepts_full_alias(tmp_path):
    tool = BrowserSnapshotTool(project_root=tmp_path / "project")
    calls = []

    def fake_snapshot_current(*, save_full, session_id=None):
        calls.append((save_full, session_id))
        return {"success": True}

    tool.manager.snapshot_current = fake_snapshot_current

    definition = tool.get_tool_definition()
    assert "save_full" in definition["function"]["parameters"]["properties"]
    assert tool.execute(save_full=True, session_id="abc") == {"success": True}
    assert tool.execute(full=True, session_id="def") == {"success": True}
    assert calls == [(True, "abc"), (True, "def")]


def test_headless_navigation_ignores_legacy_stale_headed_lock_before_copy(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    manager.ensure_profile("work")
    lock_file = project_root / "state" / "browser" / "profiles" / "work" / ".headed.lock"
    lock_file.write_text("stale", encoding="utf-8")

    manager._run_cli = lambda session, command_args, timeout=60, headed=False: {"success": True}
    result = manager.start_headless("https://example.com", profile="work")

    assert result["success"] is True
    assert not lock_file.exists()
    assert result["runtime_profile_dir"]


def test_headless_uses_headless_base_when_valid_headed_lock_exists(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    default_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    headless_base = project_root / "state" / "browser" / "profiles" / "default" / "headless-base"
    (default_dir / "Default").mkdir(parents=True, exist_ok=True)
    (headless_base / "Default").mkdir(parents=True, exist_ok=True)
    (default_dir / "Default" / "source.txt").write_text("live-default", encoding="utf-8")
    (headless_base / "Default" / "source.txt").write_text("stable-base", encoding="utf-8")
    manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-owner",
            "owner_pid": 999,
            "session_id": "headed-session",
            "profile": "default",
            "profile_dir": str(default_dir),
            "browser_pid": 888,
        }
    )
    manager._headed_browser_is_alive = lambda lock: True
    manager._run_cli = lambda session, command_args, timeout=60, headed=False: {"success": True}

    result = manager.start_headless("https://example.com")

    copied = Path(result["runtime_profile_dir"]) / "Default" / "source.txt"
    assert result["success"] is True
    assert copied.read_text(encoding="utf-8") == "stable-base"


def test_headless_refuses_to_copy_live_default_when_headed_base_missing(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    default_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": "other-owner",
            "owner_pid": 999,
            "session_id": "headed-session",
            "profile": "default",
            "profile_dir": str(default_dir),
            "browser_pid": 888,
        }
    )
    manager._headed_browser_is_alive = lambda lock: True

    result = manager.start_headless("https://example.com")

    assert result["success"] is False
    assert "headless-base" in result["error"]
    assert "default" in result["error"]


def test_headless_after_user_closed_headed_releases_lock_and_copies_latest_default(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    default_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    headless_base = project_root / "state" / "browser" / "profiles" / "default" / "headless-base"
    (default_dir / "Default").mkdir(parents=True, exist_ok=True)
    (headless_base / "Default").mkdir(parents=True, exist_ok=True)
    (default_dir / "Default" / "source.txt").write_text("latest-default", encoding="utf-8")
    (headless_base / "Default" / "source.txt").write_text("old-base", encoding="utf-8")
    manager._write_interactive_lock(
        {
            "kind": "headed",
            "status": "running",
            "owner_id": manager.owner_id,
            "owner_pid": manager.owner_pid,
            "session_id": "headed-session",
            "profile": "default",
            "profile_dir": str(default_dir),
            "browser_pid": 888,
        }
    )
    manager._headed_browser_is_alive = lambda lock: False
    manager._run_cli = lambda session, command_args, timeout=60, headed=False: {"success": True}

    result = manager.start_headless("https://example.com")

    copied = Path(result["runtime_profile_dir"]) / "Default" / "source.txt"
    assert result["success"] is True
    assert copied.read_text(encoding="utf-8") == "latest-default"
    assert manager._read_interactive_lock() is None


def test_headless_copy_failure_cleans_alpha_browser_processes_and_retries(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    manager.ensure_profile("work")
    attempts = []
    cleaned = []
    real_copytree = shutil.copytree

    def flaky_copytree(source, target, dirs_exist_ok=False):
        attempts.append((Path(source), Path(target)))
        if len(attempts) == 1:
            raise PermissionError("profile is locked")
        return real_copytree(source, target, dirs_exist_ok=dirs_exist_ok)

    monkeypatch.setattr(browser_manager_module.shutil, "copytree", flaky_copytree)
    monkeypatch.setattr(manager, "_cleanup_alpha_browser_processes", lambda: cleaned.append("called"))
    manager._run_cli = lambda session, command_args, timeout=60, headed=False: {"success": True}

    result = manager.start_headless("https://example.com", profile="work")

    assert result["success"] is True
    assert cleaned == ["called"]
    assert len(attempts) == 2
    assert result["runtime_profile_dir"]


def test_headless_copy_failure_reports_error_after_single_retry(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    manager.ensure_profile("work")
    cleaned = []

    def failing_copytree(source, target, dirs_exist_ok=False):
        raise PermissionError("profile is locked")

    monkeypatch.setattr(browser_manager_module.shutil, "copytree", failing_copytree)
    monkeypatch.setattr(manager, "_cleanup_alpha_browser_processes", lambda: cleaned.append("called"))

    result = manager.start_headless("https://example.com", profile="work")

    assert result["success"] is False
    assert cleaned == ["called"]
    assert "default profile is still locked" in result["error"]
    assert "close alpha browser windows" in result["error"]


def test_alpha_browser_process_matcher_only_accepts_project_browser_state(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    alpha_cmd = f'chrome.exe --user-data-dir="{project_root}\\state\\browser\\profiles\\default\\user-data"'
    user_cmd = r'chrome.exe --user-data-dir="C:\Users\20157\AppData\Local\Google\Chrome\User Data"'
    sibling_cmd = f'chrome.exe --user-data-dir="{project_root}\\state\\browser-cache\\profile"'

    assert manager._is_alpha_browser_command(alpha_cmd) is True
    assert manager._is_alpha_browser_command(user_cmd) is False
    assert manager._is_alpha_browser_command(sibling_cmd) is False
    assert manager._is_alpha_browser_command("chrome.exe") is False


def test_windows_alpha_browser_cleanup_taskkills_only_matching_state_browser_processes(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    alpha_cmd = f'chrome.exe --user-data-dir="{project_root}\\state\\browser\\profiles\\default\\user-data"'
    user_cmd = r'chrome.exe --user-data-dir="C:\Users\20157\AppData\Local\Google\Chrome\User Data"'
    sibling_cmd = f'chrome.exe --user-data-dir="{project_root}\\state\\browser-cache\\profile"'
    calls = []

    class Result:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == "powershell.exe":
            return Result(
                json.dumps(
                    [
                        {"ProcessId": 101, "CommandLine": alpha_cmd},
                        {"ProcessId": 202, "CommandLine": user_cmd},
                        {"ProcessId": 303, "CommandLine": sibling_cmd},
                    ]
                )
            )
        return Result(returncode=0)

    monkeypatch.setattr(browser_manager_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(browser_manager_module.subprocess, "run", fake_run)

    stopped = manager._cleanup_alpha_browser_processes()

    assert stopped == 1
    assert ["taskkill", "/PID", "101", "/T", "/F"] in calls
    assert ["taskkill", "/PID", "202", "/T", "/F"] not in calls
    assert ["taskkill", "/PID", "303", "/T", "/F"] not in calls


def test_headed_login_uses_persistent_profile_creates_interactive_lock_and_headless_base(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    profile_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    (profile_dir / "Local State").write_text("{}", encoding="utf-8")
    (profile_dir / "Default").mkdir(parents=True, exist_ok=True)
    (profile_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")

    calls = []

    def fake_run(session, command_args, timeout=60, headed=False):
        calls.append((session.session_id, list(command_args), headed))
        return {"success": True}

    manager._run_cli = fake_run
    login = manager.start_headed_login(profile="default", url="https://example.com/login")
    lock = manager._read_interactive_lock()

    assert login["success"] is True
    assert login["profile_dir"] == str(profile_dir)
    assert calls[0][1] == ["open", "https://example.com/login"]
    assert calls[0][2] is True
    assert lock["kind"] == "headed"
    assert lock["status"] == "running"
    assert lock["session_id"] == login["session_id"]
    assert (project_root / "state" / "browser" / "profiles" / "default" / "headless-base" / "Default" / "Preferences").exists()
    assert ["state", "save", str(project_root / "state" / "browser" / "profiles" / "job" / "state.json")] not in [
        call[1] for call in calls
    ]


def test_browser_close_rejects_headed_and_cdp_even_when_session_id_is_explicit(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    headed = manager._new_session("local-headed-login", "default")
    cdp = manager._new_session("external-cdp", None, cdp_url="http://127.0.0.1:9222")
    calls = []
    manager._run_cli = lambda session, command_args, timeout=60, headed=False: calls.append((session.session_id, command_args)) or {"success": True}

    headed_result = manager.close(headed.session_id)
    cdp_result = manager.close(cdp.session_id)

    assert headed_result["success"] is False
    assert cdp_result["success"] is False
    assert "profile_close_headed" in headed_result["error"]
    assert "browser_disconnect_cdp" in cdp_result["error"]
    assert calls == []


def test_profile_close_headed_requires_confirmation_and_waits_before_unlock(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    profile_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    (profile_dir / "Local State").write_text("{}", encoding="utf-8")
    (profile_dir / "Default").mkdir(parents=True, exist_ok=True)
    (profile_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    manager._run_cli = lambda session, command_args, timeout=60, headed=False: {"success": True}
    login = manager.start_headed_login(url="https://example.com/login")
    assert manager.profile_close_headed(user_confirmed_close_visible_browser=False)["success"] is False

    alive = [True, False]
    monkeypatch.setattr(manager, "_headed_browser_is_alive", lambda lock: alive.pop(0) if alive else False)
    result = manager.profile_close_headed(user_confirmed_close_visible_browser=True, wait_timeout=1)

    assert result["success"] is True
    assert manager._read_interactive_lock() is None
    assert not (project_root / "state" / "browser" / "profiles" / "default" / "headless-base").exists()
    assert result["session_id"] == login["session_id"]


def test_profile_save_headed_exports_state_for_same_owner_headless(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    profile_dir = project_root / "state" / "browser" / "profiles" / "default" / "user-data"
    (profile_dir / "Local State").write_text("{}", encoding="utf-8")
    (profile_dir / "Default").mkdir(parents=True, exist_ok=True)
    (profile_dir / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    calls = []

    def fake_run(session, command_args, timeout=60, headed=False):
        calls.append((session.mode, list(command_args), headed))
        if command_args[:2] == ["state", "save"]:
            Path(command_args[2]).parent.mkdir(parents=True, exist_ok=True)
            Path(command_args[2]).write_text("{}", encoding="utf-8")
        return {"success": True}

    manager._run_cli = fake_run
    manager.start_headed_login(url="https://example.com/login")
    monkeypatch.setattr(manager, "_headed_browser_is_alive", lambda lock: True)
    saved = manager.profile_save_headed()
    result = manager.start_headless("https://example.com")

    assert saved["success"] is True
    assert ["state", "save", str(manager._headed_state_file("default"))] in [call[1] for call in calls]
    assert ["state", "load", str(manager._headed_state_file("default"))] in [call[1] for call in calls]
    assert result["success"] is True


def test_cdp_uses_interactive_lock_but_never_touches_profile_copy_paths(tmp_path):
    project_root = tmp_path / "project"
    manager = BrowserManager(project_root)
    calls = []

    def forbidden_copy(*args, **kwargs):
        raise AssertionError("CDP must not copy or write alpha browser profiles")

    browser_manager_module.shutil.copytree, old_copytree = forbidden_copy, browser_manager_module.shutil.copytree
    try:
        manager._run_cli = lambda session, command_args, timeout=60, headed=False: calls.append((session.mode, command_args)) or {"success": True}
        result = manager.connect_cdp("9222")
        lock = manager._read_interactive_lock()
        disconnected = manager.disconnect_cdp()
    finally:
        browser_manager_module.shutil.copytree = old_copytree

    assert result["success"] is True
    assert lock["kind"] == "cdp"
    assert disconnected["success"] is True
    assert manager._read_interactive_lock() is None
    assert calls == [("external-cdp", ["get", "url"])]


def test_profile5_sync_script_uses_lock_and_staging_instead_of_destructive_default_delete():
    script = (PROJECT_ROOT / "sync-chrome-profile5-to-alpha.ps1").read_text(encoding="utf-8")

    assert "profile-copy-default.lock" in script
    assert "user-data.importing" in script
    assert "Default\\Preferences" in script
    assert 'GetEnvironmentVariable("USERPROFILE", "User")' in script
    assert "Remove-Item -LiteralPath $TargetUserData -Recurse -Force" not in script


def test_browser_reports_configured_chrome_path(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    chrome_path = tmp_path / "Chrome" / "chrome.exe"
    chrome_path.parent.mkdir(parents=True)
    chrome_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_BROWSER_EXECUTABLE_PATH", str(chrome_path))
    manager = BrowserManager(project_root)

    info = manager.browser_executable_info()

    assert info == {
        "mode": "configured",
        "path": str(chrome_path),
        "exists": True,
        "fallback": False,
    }


def test_browser_reports_fallback_when_configured_chrome_path_is_missing(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    missing_path = tmp_path / "missing" / "chrome.exe"
    monkeypatch.setenv("AGENT_BROWSER_EXECUTABLE_PATH", str(missing_path))
    manager = BrowserManager(project_root)

    info = manager.browser_executable_info()

    assert info["mode"] == "agent_browser_default"
    assert info["configured_path"] == str(missing_path)
    assert info["exists"] is False
    assert info["fallback"] is True
    assert "warning" in info


def test_browser_reads_chrome_path_from_runtime_env_file(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    chrome_path = tmp_path / "Chrome" / "chrome.exe"
    chrome_path.parent.mkdir(parents=True)
    chrome_path.write_text("", encoding="utf-8")
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "runtime_env.local.json").write_text(
        f'{{"AGENT_BROWSER_EXECUTABLE_PATH": "{chrome_path.as_posix()}"}}',
        encoding="utf-8-sig",
    )
    monkeypatch.delenv("AGENT_BROWSER_EXECUTABLE_PATH", raising=False)
    manager = BrowserManager(project_root)

    info = manager.browser_executable_info()
    env = manager._browser_env()

    assert info["mode"] == "configured"
    assert info["path"] == str(chrome_path)
    assert env["AGENT_BROWSER_EXECUTABLE_PATH"] == str(chrome_path)


def test_browser_command_prefix_uses_native_windows_exe_when_npm_cmd_is_found(monkeypatch, tmp_path):
    npm_dir = tmp_path / "npm"
    shim = npm_dir / "agent-browser.cmd"
    native = npm_dir / "node_modules" / "agent-browser" / "bin" / "agent-browser-win32-x64.exe"
    native.parent.mkdir(parents=True)
    shim.write_text("@ECHO off\n", encoding="utf-8")
    native.write_text("", encoding="utf-8")
    manager = BrowserManager(tmp_path / "project")

    monkeypatch.setattr(browser_manager_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(browser_manager_module.shutil, "which", lambda name: str(shim) if name == "agent-browser" else None)

    assert manager._command_prefix() == [str(native)]


def test_run_cli_tolerates_gbk_stderr(monkeypatch, tmp_path):
    manager = BrowserManager(tmp_path / "project")
    manager._command_prefix = lambda: ["agent-browser"]
    session = manager._new_session("local-headless", "default")

    class DoneProc:
        def __init__(self):
            self.pid = 34567
            self.returncode = 0

        def poll(self):
            return self.returncode

    def fake_popen(cmd, stdin, stdout, stderr, env, **kwargs):
        stdout.write(json.dumps({"success": True, "data": {"url": "https://example.com"}}))
        stdout.flush()
        stderr.flush()
        Path(stderr.name).write_bytes("'order' \xb2\xbb\xca\xc7\xc4\xda\xb2\xbf\xbb\xf2\xcd\xe2\xb2\xbf\xc3\xfc\xc1\xee".encode("latin1"))
        return DoneProc()

    monkeypatch.setattr("agent.tools.browser_manager.subprocess.Popen", fake_popen)

    result = manager._run_cli(session, ["open", "https://example.com/?q=test&order=rank"])

    assert result["success"] is True
    assert result["data"]["url"] == "https://example.com"


def test_tool_loader_browser_groups_are_role_scoped(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)

    loader = ToolLoader(project_root=project_root, enable_permissions=False)
    loader._load_mcp_tools = lambda: None
    loader._load_skills = lambda: None
    loader.load_all()

    resolved = loader.resolve_tools(RoleConfig(name="worker", enabled_tool_groups=["browser_headless"]))
    tool_names = {tool["function"]["name"] for tool in resolved}

    assert "browser_navigate" in tool_names
    assert "browser_click" in tool_names
    assert "profile_login_headed" not in tool_names
    assert "browser_connect_cdp" not in tool_names


def test_browser_manager_interrupts_agent_browser_process(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    event = threading.Event()
    event.set()
    manager = BrowserManager(project_root, interrupt_event=event)
    manager._command_prefix = lambda: ["agent-browser"]
    session = manager._new_session("local-headed-login", "default")
    fake_proc = FakeBrowserProc()
    killed = []

    monkeypatch.setattr("agent.tools.browser_manager.subprocess.Popen", lambda *args, **kwargs: fake_proc)

    def fake_terminate(proc):
        killed.append(proc.pid)
        proc.returncode = -1

    monkeypatch.setattr("agent.tools.browser_manager.terminate_process_tree", fake_terminate)

    result = manager._run_cli(session, ["open", "https://example.com"], headed=True, timeout=30)

    assert result["success"] is False
    assert result["interrupted"] is True
    assert killed == [23456]


def test_browser_tool_receives_interrupt_event(tmp_path):
    event = threading.Event()
    tool = BrowserNavigateTool(project_root=tmp_path / "project")

    tool.set_interrupt_event(event)

    assert tool.manager.interrupt_event is event


def test_tool_loader_propagates_interrupt_event_to_builtin_tools(tmp_path):
    event = threading.Event()
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    loader = ToolLoader(project_root=project_root, enable_permissions=False)
    loader._load_mcp_tools = lambda: None
    loader._load_skills = lambda: None

    loader.set_interrupt_event(event)
    loader.load_all()

    assert loader.tool_instances["bash"].interrupt_event is event
    assert loader.tool_instances["browser_navigate"].manager.interrupt_event is event
