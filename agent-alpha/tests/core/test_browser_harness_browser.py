from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent.tools.browser_harness_browser import BrowserProcess, BrowserProcessDiscoveryError, DedicatedBrowser


def make_browser(tmp_path: Path) -> DedicatedBrowser:
    return DedicatedBrowser(tmp_path / "Alpha 资料" / "profile", tmp_path / "temp")


def test_process_matching_requires_exact_user_data_dir(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    exact = str(browser.profile_dir)
    similar = f"{exact}-other"
    monkeypatch.setattr(browser, "_split_command_line", lambda value: value.split("|"))
    items = [
        {"Name": "chrome.exe", "ProcessId": 10, "CreationDate": "a", "CommandLine": f"chrome.exe|--user-data-dir={exact}"},
        {"Name": "chrome.exe", "ProcessId": 11, "CreationDate": "b", "CommandLine": f"chrome.exe|--user-data-dir={similar}"},
        {"Name": "chrome.exe", "ProcessId": 12, "CreationDate": "c", "CommandLine": f"chrome.exe|--user-data-dir={exact}|--type=renderer"},
    ]

    owned = browser._owned_processes(items)

    assert [process.pid for process in owned] == [10, 12]
    assert [process.pid for process in owned if not browser._is_child(process.arguments)] == [10]


def test_mode_comes_from_main_process_arguments(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    manual = BrowserProcess(1, "a", "", ("chrome.exe", f"--user-data-dir={browser.profile_dir}"))
    cdp = BrowserProcess(2, "b", "", ("chrome.exe", f"--user-data-dir={browser.profile_dir}", "--remote-debugging-port=0"))
    monkeypatch.setattr(browser, "main_processes", lambda: [manual])
    assert browser.current_mode() == "manual"
    monkeypatch.setattr(browser, "main_processes", lambda: [cdp])
    assert browser.current_mode() == "cdp"
    monkeypatch.setattr(browser, "main_processes", lambda: [manual, cdp])
    assert browser.current_mode() == "conflict"


def test_windows_process_query_forces_utf8_for_chinese_profile(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    exact = str(browser.profile_dir)
    payload = json.dumps(
        {"Name": "chrome.exe", "ProcessId": 10, "CreationDate": "a", "CommandLine": f'chrome.exe "--user-data-dir={exact}"'},
        ensure_ascii=False,
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

    monkeypatch.setattr("agent.tools.browser_harness_browser.os.name", "nt")
    monkeypatch.setattr("agent.tools.browser_harness_browser.subprocess.run", fake_run)

    processes = browser._processes()

    assert [process.pid for process in processes] == [10]
    assert "[Console]::OutputEncoding" in calls[0][0][-1]
    assert calls[0][1]["encoding"] == "utf-8"


def test_windows_process_query_failure_is_not_treated_as_no_browser(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 5, stdout="", stderr="access denied")

    monkeypatch.setattr("agent.tools.browser_harness_browser.os.name", "nt")
    monkeypatch.setattr("agent.tools.browser_harness_browser.subprocess.run", fake_run)

    with pytest.raises(BrowserProcessDiscoveryError, match="exit code 5"):
        browser.current_mode()


def test_native_toggle_is_disabled_after_browser_exit_and_other_state_is_preserved(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    browser.profile_dir.mkdir(parents=True)
    local_state = browser.profile_dir / "Local State"
    local_state.write_text(
        json.dumps({"devtools": {"remote_debugging": {"user-enabled": True}, "other": 7}, "profile": {"last_used": "Default"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser, "main_processes", lambda: [])

    result = browser.disable_native_remote_debugging()

    saved = json.loads(local_state.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["changed"] is True
    assert saved["devtools"]["remote_debugging"]["user-enabled"] is False
    assert saved["devtools"]["other"] == 7
    assert saved["profile"]["last_used"] == "Default"
    assert Path(result["backup"]).is_file()


def test_native_toggle_is_not_changed_while_browser_is_running(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    browser.profile_dir.mkdir(parents=True)
    local_state = browser.profile_dir / "Local State"
    original = json.dumps({"devtools": {"remote_debugging": {"user-enabled": True}}})
    local_state.write_text(original, encoding="utf-8")
    process = BrowserProcess(1, "a", "", ("chrome.exe", f"--user-data-dir={browser.profile_dir}"))
    monkeypatch.setattr(browser, "main_processes", lambda: [process])

    result = browser.disable_native_remote_debugging()

    assert result["success"] is False
    assert local_state.read_text(encoding="utf-8") == original


def test_close_rechecks_process_creation_time_before_posting_window_close(tmp_path: Path, monkeypatch):
    browser = make_browser(tmp_path)
    original = BrowserProcess(7, "old", "", ("chrome.exe", f"--user-data-dir={browser.profile_dir}"))
    replacement = BrowserProcess(7, "new", "", original.arguments)
    calls = iter([[original], [replacement]])
    monkeypatch.setattr(browser, "main_processes", lambda: next(calls))
    posted: list[int] = []
    monkeypatch.setattr(browser, "_post_close", lambda pid: posted.append(pid) or True)

    result = browser.close()

    assert result["status"] == "close_required"
    assert posted == []
