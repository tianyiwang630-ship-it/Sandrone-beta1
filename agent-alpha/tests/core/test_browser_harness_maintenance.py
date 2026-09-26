import subprocess
import sys
import threading

from agent.tools import browser_harness_maintenance as maintenance
from agent.tools.browser_harness_lock import BrowserFileLock


def test_browser_lock_releases_after_owner_exits(tmp_path):
    path = tmp_path / "browser-use.lock"
    first, second = BrowserFileLock(path), BrowserFileLock(path)
    assert first.acquire(0)
    assert not second.acquire(0)
    first.release()
    assert second.acquire(0)
    second.release()


def test_browser_lock_releases_after_process_crash(tmp_path):
    path = tmp_path / "browser-use.lock"
    script = (
        "import os,sys; from pathlib import Path; "
        "from agent.tools.browser_harness_lock import BrowserFileLock; "
        "lock=BrowserFileLock(Path(sys.argv[1])); assert lock.acquire(0); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", script, str(path)], check=True, timeout=10)
    lock = BrowserFileLock(path)
    assert lock.acquire(0)
    lock.release()


def test_new_browser_request_waits_for_cleanup_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 1)
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    cache = cleaner.profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "page").write_bytes(b"large")
    cleaning = threading.Event()
    release = threading.Event()
    original_remove = cleaner._remove_files

    def paused_remove(root, deadline):
        cleaning.set()
        assert release.wait(2)
        original_remove(root, deadline)

    monkeypatch.setattr(cleaner, "_remove_files", paused_remove)
    worker = threading.Thread(target=cleaner.sweep)
    worker.start()
    assert cleaning.wait(2)
    request_lock = BrowserFileLock(cleaner.state / "browser-use.lock")
    try:
        assert not request_lock.acquire(0)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert request_lock.acquire(0)
    request_lock.release()


def test_cleanup_timeout_reports_failure_without_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 1)
    monkeypatch.setattr(maintenance, "SWEEP_BUDGET_SECONDS", -1)
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    cache = cleaner.profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "page").write_bytes(b"large")
    cleaner.sweep()
    assert (cache / "page").exists()
    assert maintenance.read_browser_maintenance_notice(tmp_path)["kind"] == "failed"


def test_idle_cleanup_keeps_profile_and_removes_only_cache_first(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 50)
    monkeypatch.setattr(maintenance, "TARGET", 20)
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    cache = cleaner.profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "page").write_bytes(b"x" * 60)
    preferences = cleaner.profile / "Default" / "Preferences"
    preferences.write_text("account", encoding="utf-8")
    cleaner.sweep()
    assert preferences.read_text(encoding="utf-8") == "account"
    assert not cache.exists()
    assert maintenance.read_browser_maintenance_notice(tmp_path) == {}


def test_open_browser_is_never_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 1)
    monkeypatch.setattr(maintenance.DedicatedBrowser, "main_processes", lambda self: [object()])
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    cache = cleaner.profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "page").write_bytes(b"large")
    cleaner.sweep()
    assert (cache / "page").exists()
    assert (cleaner.state / "last-browser-use").exists()
    monkeypatch.setattr(maintenance.DedicatedBrowser, "main_processes", lambda self: [])
    cleaner.sweep()
    assert (cache / "page").exists()


def test_failed_cleanup_reports_and_defers_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 1)
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    cache = cleaner.profile / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "page").write_bytes(b"large")
    monkeypatch.setattr(cleaner, "_remove_files", lambda *_: (_ for _ in ()).throw(PermissionError("locked")))
    cleaner.sweep()
    assert (cache / "page").exists()
    assert cleaner.next_retry > 0
    assert maintenance.read_browser_maintenance_notice(tmp_path)["kind"] == "failed"


def test_reset_is_last_resort_and_reports_new_login(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "LIMIT", 10)
    monkeypatch.setattr(maintenance, "TARGET", 5)
    cleaner = maintenance.BrowserMaintenance(tmp_path)
    profile = cleaner.profile / "Default"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_bytes(b"x" * 20)
    cleaner.sweep()
    assert not cleaner.profile.exists()
    assert maintenance.read_browser_maintenance_notice(tmp_path)["kind"] == "reset"
