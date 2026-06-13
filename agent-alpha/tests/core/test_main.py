from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from tests.conftest import cleanup_test_dir, make_test_dir
from agent.cli.main import append_session_index, build_log_path, create_cli_session
from agent.core.context_manager import ContextCompressionResult
from agent.core.session_store import SessionKind, SessionRecord, SessionStore


def _read_event_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    index = 0
    records: list[dict] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        record, next_index = decoder.raw_decode(text, index)
        records.append(record)
        index = next_index
    return records


def test_create_cli_session_returns_session_storage_and_default_workspace():
    tmp_dir = make_test_dir("main-cli-session")
    try:
        project_root = tmp_dir / "agent-alpha"

        sessions_dir, logs_dir, workspace_root = create_cli_session(project_root)

        assert sessions_dir == (project_root / "session-log" / "sessions").resolve()
        assert logs_dir == (project_root / "session-log" / "logs").resolve()
        assert workspace_root == (project_root / "workspace").resolve()
        assert sessions_dir.exists()
        assert logs_dir.exists()
        assert workspace_root.exists()
    finally:
        cleanup_test_dir(tmp_dir)


def test_build_log_path_uses_logs_dir_and_session_id():
    started_at = datetime(2026, 3, 22, 15, 30, 0)
    log_path = build_log_path(Path("D:/demo/workspace/logs"), "abc123", started_at)
    assert str(log_path).endswith("2026-03-22_15-30-00_session_abc123.json")


def test_append_session_index_records_workspace_and_log_file():
    tmp_dir = make_test_dir("main-session-index")
    try:
        project_root = tmp_dir / "agent-alpha"
        sessions_dir, logs_dir, workspace_root = create_cli_session(project_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        (workspace_root / "draft.txt").write_text("draft", encoding="utf-8")
        log_path = logs_dir / "2026-03-22_15-30-00_session_abc123.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{}", encoding="utf-8")

        append_session_index(
            sessions_dir=sessions_dir,
            session_id="abc123",
            started_at=datetime(2026, 3, 22, 15, 30, 0),
            history=[{"role": "user", "content": "hello world"}],
            workspace=workspace_root,
            log_path=log_path,
        )

        index_text = (sessions_dir / "index.md").read_text(encoding="utf-8")
        assert "abc123" in index_text
        assert "workspace" in index_text
        assert "session-log/logs/2026-03-22_15-30-00_session_abc123.json" in index_text
        assert "hello world" in index_text
    finally:
        cleanup_test_dir(tmp_dir)


def test_save_session_log_writes_to_session_log_folder():
    tmp_dir = make_test_dir("main-save-session-log")
    try:
        from agent.cli.main import save_session_log

        project_root = tmp_dir / "agent-alpha"
        sessions_dir, logs_dir, workspace_root = create_cli_session(project_root)
        log_path = build_log_path(logs_dir, "abc123", datetime(2026, 3, 22, 15, 30, 0))
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "hello world"}],
            get_session_log_data=lambda: {"history": [{"role": "user", "content": "hello world"}]},
        )

        save_session_log(
            agent=agent,
            session_id="abc123",
            started_at=datetime(2026, 3, 22, 15, 30, 0),
            sessions_dir=sessions_dir,
            workspace=workspace_root,
            log_path=log_path,
        )

        assert log_path.exists()
        assert (sessions_dir / "index.md").exists()
    finally:
        cleanup_test_dir(tmp_dir)


def test_compact_command_records_summary_in_sessions_and_events(capsys):
    tmp_dir = make_test_dir("main-compact-command-success")
    try:
        from agent.cli.main import _handle_compact_command

        project_root = tmp_dir / "agent-alpha"
        sessions_dir, _logs_dir, workspace_root = create_cli_session(project_root)
        events_dir = project_root / "session-log" / "events"
        store = SessionStore(sessions_dir)
        store.save(
            SessionRecord(
                session_id="abc123",
                kind=SessionKind.INTERACTIVE,
                workspace=str(workspace_root),
                history=[{"role": "user", "content": "old"}],
                created_at="2026-04-08T10:00:00",
                updated_at="2026-04-08T10:00:00",
            )
        )
        result = ContextCompressionResult(
            trigger="manual",
            history=[{"role": "user", "content": "## 当前状态\n- 手动摘要。"}],
            summary="## 当前状态\n- 手动摘要。",
            before_message_count=4,
            after_message_count=1,
            before_tokens=100,
            after_tokens=20,
            success=True,
            fallback=False,
            error=None,
        )
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "old"}],
            compact_history=lambda **_: result,
        )

        _handle_compact_command(
            agent=agent,
            session_id="abc123",
            store=store,
            events_dir=events_dir,
        )

        assert agent.history == result.history
        session = store.load("abc123")
        assert session.events[-1]["type"] == "context_compacted"
        assert session.events[-1]["summary"] == "## 当前状态\n- 手动摘要。"
        records = _read_event_records(events_dir / "abc123.jsonl")
        assert records[0]["type"] == "context_compacted"
        assert records[0]["event"]["summary"] == "## 当前状态\n- 手动摘要。"
        assert "手动摘要" in capsys.readouterr().out
    finally:
        cleanup_test_dir(tmp_dir)


def test_compact_command_failure_keeps_history_and_records_failure(capsys):
    tmp_dir = make_test_dir("main-compact-command-failure")
    try:
        from agent.cli.main import _handle_compact_command

        project_root = tmp_dir / "agent-alpha"
        sessions_dir, _logs_dir, workspace_root = create_cli_session(project_root)
        events_dir = project_root / "session-log" / "events"
        store = SessionStore(sessions_dir)
        original_history = [{"role": "user", "content": "old"}]
        store.save(
            SessionRecord(
                session_id="abc123",
                kind=SessionKind.INTERACTIVE,
                workspace=str(workspace_root),
                history=original_history,
                created_at="2026-04-08T10:00:00",
                updated_at="2026-04-08T10:00:00",
            )
        )
        result = ContextCompressionResult(
            trigger="manual",
            history=list(original_history),
            summary="",
            before_message_count=1,
            after_message_count=1,
            before_tokens=10,
            after_tokens=10,
            success=False,
            fallback=False,
            error="summary failed",
        )
        agent = SimpleNamespace(
            history=list(original_history),
            compact_history=lambda **_: result,
        )

        _handle_compact_command(
            agent=agent,
            session_id="abc123",
            store=store,
            events_dir=events_dir,
        )

        assert agent.history == original_history
        assert store.load("abc123").history == original_history
        assert store.load("abc123").events[-1]["type"] == "context_compaction_failed"
        records = _read_event_records(events_dir / "abc123.jsonl")
        assert records[0]["type"] == "context_compaction_failed"
        assert records[0]["event"]["error"] == "summary failed"
        out = capsys.readouterr().out
        assert "压缩失败，历史未改变" in out
        assert "summary failed" in out
    finally:
        cleanup_test_dir(tmp_dir)


def test_compact_command_empty_history_does_not_write_success_event(capsys):
    tmp_dir = make_test_dir("main-compact-command-empty")
    try:
        from agent.cli.main import _handle_compact_command

        project_root = tmp_dir / "agent-alpha"
        sessions_dir, _logs_dir, _workspace_root = create_cli_session(project_root)
        events_dir = project_root / "session-log" / "events"
        store = SessionStore(sessions_dir)
        agent = SimpleNamespace(history=[])

        _handle_compact_command(
            agent=agent,
            session_id="abc123",
            store=store,
            events_dir=events_dir,
        )

        assert not (events_dir / "abc123.jsonl").exists()
        assert "当前没有可压缩的对话历史" in capsys.readouterr().out
    finally:
        cleanup_test_dir(tmp_dir)


def test_save_session_snapshot_merges_runtime_events_for_auto_compaction():
    tmp_dir = make_test_dir("main-save-session-runtime-events")
    try:
        from agent.cli.main import _save_session_snapshot

        sessions_dir = tmp_dir / "agent-alpha" / "session-log" / "sessions"
        workspace_root = tmp_dir / "agent-alpha" / "workspace"
        workspace_root.mkdir(parents=True)
        store = SessionStore(sessions_dir)
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "## 当前状态\n- 自动摘要。"}],
            runtime_events=[
                {
                    "type": "context_compacted",
                    "timestamp": "2026-04-08T10:05:00",
                    "summary": "## 当前状态\n- 自动摘要。",
                }
            ],
        )

        _save_session_snapshot(
            store=store,
            session_id="abc123",
            agent=agent,
            workspace=workspace_root,
            created_at=datetime(2026, 4, 8, 10, 0, 0),
            metadata={"project_root": str(tmp_dir / "agent-alpha")},
        )

        record = store.load("abc123")
        assert record.events == agent.runtime_events
        assert record.history == agent.history
    finally:
        cleanup_test_dir(tmp_dir)
