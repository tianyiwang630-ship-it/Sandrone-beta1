import json
import threading

import pytest

from agent.core.session_store import SessionRecord, SessionStore


def test_save_retries_temporary_windows_access_denial(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    record = SessionRecord(session_id="session", metadata={"value": "kept"})
    real_replace = __import__("os").replace
    attempts = []

    def flaky_replace(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError(5, "Access is denied")
        real_replace(source, target)

    monkeypatch.setattr("agent.core.session_store.os.replace", flaky_replace)
    store.save(record)

    assert len(attempts) == 3
    assert store.load("session").metadata["value"] == "kept"
    assert not list(store.sessions_dir.glob("*.tmp"))


def test_concurrent_saves_use_independent_temp_files_and_keep_valid_json(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    real_replace = __import__("os").replace
    temp_paths = []
    barrier = threading.Barrier(2)

    def observed_replace(source, target):
        temp_paths.append(source)
        real_replace(source, target)

    monkeypatch.setattr("agent.core.session_store.os.replace", observed_replace)

    def save(value):
        barrier.wait()
        store.save(SessionRecord(session_id="shared", metadata={"value": value}))

    threads = [threading.Thread(target=save, args=(value,)) for value in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(temp_paths) == 2
    assert len(set(temp_paths)) == 2
    payload = json.loads((store.sessions_dir / "shared.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["value"] in {"a", "b"}
    assert not list(store.sessions_dir.glob("*.tmp"))


def test_persistent_access_denial_keeps_previous_snapshot(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    store.save(SessionRecord(session_id="session", metadata={"value": "old"}))

    def denied_replace(_source, _target):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr("agent.core.session_store.os.replace", denied_replace)
    with pytest.raises(PermissionError):
        store.save(SessionRecord(session_id="session", metadata={"value": "new"}))

    assert store.load("session").metadata["value"] == "old"
    assert not list(store.sessions_dir.glob("*.tmp"))
