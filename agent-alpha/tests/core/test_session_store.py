from datetime import datetime
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from tests.conftest import cleanup_test_dir, make_test_dir
from agent.core.session_store import SessionKind, SessionRecord, SessionStore


def test_session_store_saves_and_loads_full_history_snapshot():
    tmp_dir = make_test_dir("session-store-save-load")
    try:
        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        record = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/agent-alpha/workspace",
            history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:00:00",
        )

        store.save(record)
        loaded = store.load("abc123")

        assert loaded is not None
        assert loaded.session_id == "abc123"
        assert loaded.kind == SessionKind.INTERACTIVE
        assert loaded.workspace == "D:/demo/agent-alpha/workspace"
        assert loaded.history[-1]["content"] == "world"
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_store_lists_recent_interactive_sessions_only():
    tmp_dir = make_test_dir("session-store-list")
    try:
        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        store.save(
            SessionRecord(
                session_id="interactive-1",
                kind=SessionKind.INTERACTIVE,
                workspace="D:/demo/workspace",
                history=[{"role": "user", "content": "hello"}],
                created_at="2026-04-08T10:00:00",
                updated_at="2026-04-08T10:00:00",
            )
        )
        store.save(
            SessionRecord(
                session_id="cron-1",
                kind=SessionKind.CRON,
                workspace="D:/demo/workspace",
                history=[{"role": "user", "content": "scheduled"}],
                created_at="2026-04-08T11:00:00",
                updated_at="2026-04-08T11:00:00",
            )
        )

        sessions = store.list_recent(kind=SessionKind.INTERACTIVE)

        assert [item.session_id for item in sessions] == ["interactive-1"]
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_store_updates_workspace_in_same_session_and_records_event():
    tmp_dir = make_test_dir("session-store-workspace-change")
    try:
        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        record = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/workspace",
            history=[{"role": "user", "content": "hello"}],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:00:00",
        )
        store.save(record)

        updated = store.update_workspace(
            "abc123",
            "D:/demo/extra",
            changed_at="2026-04-08T10:05:00",
        )

        assert updated.workspace == "D:/demo/extra"
        assert updated.events[-1]["type"] == "workspace_changed"
        assert updated.events[-1]["workspace"] == "D:/demo/extra"
        assert updated.updated_at == "2026-04-08T10:05:00"
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_store_appends_compaction_event_without_changing_history():
    tmp_dir = make_test_dir("session-store-compaction-event")
    try:
        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        original_history = [{"role": "user", "content": "hello"}]
        store.save(
            SessionRecord(
                session_id="abc123",
                kind=SessionKind.INTERACTIVE,
                workspace="D:/demo/workspace",
                history=original_history,
                created_at="2026-04-08T10:00:00",
                updated_at="2026-04-08T10:00:00",
            )
        )

        updated = store.append_event(
            "abc123",
            {
                "type": "context_compacted",
                "timestamp": "2026-04-08T10:05:00",
                "summary": "## 当前状态\n- 已压缩。",
            },
        )

        assert updated.history == original_history
        assert updated.events[-1]["type"] == "context_compacted"
        assert updated.events[-1]["summary"] == "## 当前状态\n- 已压缩。"
        assert updated.updated_at == "2026-04-08T10:05:00"
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_store_save_write_failure_keeps_existing_snapshot(monkeypatch):
    tmp_dir = make_test_dir("session-store-atomic-write-fails")
    try:
        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        original = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/workspace",
            history=[{"role": "user", "content": "old safe snapshot"}],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:00:00",
        )
        store.save(original)
        original_text = (sessions_dir / "abc123.json").read_text(encoding="utf-8")

        real_write_text = Path.write_text

        def fail_tmp_write(self, *args, **kwargs):
            if self.name == "abc123.json.tmp":
                raise OSError("tmp write failed")
            return real_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", fail_tmp_write)

        updated = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/workspace",
            history=[{"role": "user", "content": "new unsafe snapshot"}],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:05:00",
        )

        try:
            store.save(updated)
        except OSError as exc:
            assert str(exc) == "tmp write failed"
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("expected tmp write failure")

        assert (sessions_dir / "abc123.json").read_text(encoding="utf-8") == original_text
        assert not (sessions_dir / "abc123.json.tmp").exists()
        assert store.load("abc123").history == original.history
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_store_save_replace_failure_keeps_existing_snapshot(monkeypatch):
    tmp_dir = make_test_dir("session-store-atomic-replace-fails")
    try:
        import agent.core.session_store as session_store_module

        sessions_dir = tmp_dir / "session-log" / "sessions"
        store = SessionStore(sessions_dir)
        original = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/workspace",
            history=[{"role": "user", "content": "old safe snapshot"}],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:00:00",
        )
        store.save(original)
        original_text = (sessions_dir / "abc123.json").read_text(encoding="utf-8")

        def fail_replace(_src, _dst):
            raise OSError("replace failed")

        monkeypatch.setattr(session_store_module.os, "replace", fail_replace)
        updated = SessionRecord(
            session_id="abc123",
            kind=SessionKind.INTERACTIVE,
            workspace="D:/demo/workspace",
            history=[{"role": "user", "content": "new unsafe snapshot"}],
            created_at="2026-04-08T10:00:00",
            updated_at="2026-04-08T10:05:00",
        )

        try:
            store.save(updated)
        except OSError as exc:
            assert str(exc) == "replace failed"
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("expected replace failure")

        assert (sessions_dir / "abc123.json").read_text(encoding="utf-8") == original_text
        assert not (sessions_dir / "abc123.json.tmp").exists()
        assert store.load("abc123").history == original.history
    finally:
        cleanup_test_dir(tmp_dir)
