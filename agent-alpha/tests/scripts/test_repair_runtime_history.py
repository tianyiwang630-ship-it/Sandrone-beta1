from agent.core.session_store import SessionRecord, SessionStore
from scripts.repair_runtime_history import repair_runtime_history


def test_repair_runtime_history_changes_only_runtime_and_creates_root_temp_backup(tmp_path):
    project_root = tmp_path / "agent-alpha"
    store = SessionStore(project_root / "session-log" / "sessions")
    full_history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": None},
    ]
    store.save(
        SessionRecord(
            session_id="sess_bad",
            history=full_history,
            runtime_history=full_history,
        )
    )

    report = repair_runtime_history(project_root, "sess_bad", apply=True)
    repaired = store.load("sess_bad")

    assert report["applied"] is True
    assert repaired.history == full_history
    assert repaired.runtime_history == [{"role": "user", "content": "hello"}]
    assert repaired.runtime_checkpoint["status"] == "recoverable"
    assert (tmp_path / "temp" / "session-runtime-repair").is_dir()
