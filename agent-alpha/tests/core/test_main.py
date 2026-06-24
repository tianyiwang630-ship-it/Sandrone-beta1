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
        events_path = project_root / "session-log" / "events" / "abc123.jsonl"
        events_path.parent.mkdir(parents=True)
        events_path.write_text(
            json.dumps(
                {
                    "ts": "2026-03-22T15:30:01",
                    "seq": 1,
                    "session_id": "abc123",
                    "type": "llm_request_failed",
                    "event": {
                        "attempt": 1,
                        "max_attempts": 2,
                        "elapsed_seconds": 130.0,
                        "error_type": "APIConnectionError",
                        "error_message": "Connection error.",
                        "model": "test-model",
                        "profile": "test",
                        "provider": "openai",
                        "base_url": "https://example.test/v1",
                        "max_tokens": 32000,
                        "has_tools": True,
                        "tool_count": 3,
                        "message_count": 10,
                        "estimated_input_chars": 1234,
                        "client_refreshed": False,
                        "slow_connection_recovery_injected": False,
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        profile = SimpleNamespace(
            name="test",
            provider="openai",
            model="test-model",
            base_url="https://example.test/v1",
        )
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "hello world"}],
            llm=SimpleNamespace(profile=profile, model_name="test-model"),
            get_session_log_data=lambda: {
                "history": [{"role": "user", "content": "hello world"}],
                "events": [{"type": "context_compacted"}],
            },
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
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        assert log_data["schema_version"] == 2
        assert log_data["session_kind"] == "interactive_cli"
        assert log_data["entrypoint"] == "cli"
        assert log_data["project_root"] == str(project_root)
        assert log_data["events_path"] == str(events_path)
        assert log_data["llm"] == {
            "profile": "test",
            "provider": "openai",
            "model": "test-model",
            "base_url": "https://example.test/v1",
        }
        assert log_data["history_stats"]["user_turns"] == 1
        assert log_data["runtime_event_stats"]["runtime_event_type_counts"] == {"context_compacted": 1}
        assert log_data["recent_llm_diagnostics"][0]["type"] == "llm_request_failed"
        assert "api_key" not in json.dumps(log_data, ensure_ascii=False).lower()
        assert (sessions_dir / "index.md").exists()
    finally:
        cleanup_test_dir(tmp_dir)


def test_save_session_log_survives_corrupt_events_file():
    tmp_dir = make_test_dir("main-session-log-corrupt-events")
    try:
        from agent.cli.main import save_session_log

        project_root = tmp_dir / "agent-alpha"
        sessions_dir, logs_dir, workspace_root = create_cli_session(project_root)
        log_path = build_log_path(logs_dir, "abc123", datetime(2026, 3, 22, 15, 30, 0))
        events_path = project_root / "session-log" / "events" / "abc123.jsonl"
        events_path.parent.mkdir(parents=True)
        events_path.write_text('{"seq": 1, "type": "llm_request_started"\n', encoding="utf-8")
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "keep this even if events is broken"}],
            llm=None,
            get_session_log_data=lambda: {
                "history": [{"role": "user", "content": "keep this even if events is broken"}],
                "events": [{"type": "runtime_error", "message": "boom"}],
            },
        )

        save_session_log(
            agent=agent,
            session_id="abc123",
            started_at=datetime(2026, 3, 22, 15, 30, 0),
            sessions_dir=sessions_dir,
            workspace=workspace_root,
            log_path=log_path,
        )

        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        assert log_data["history"][-1]["content"] == "keep this even if events is broken"
        assert log_data["event_read_error"]["error_type"] == "JSONDecodeError"
        assert log_data["runtime_event_stats"]["runtime_event_type_counts"] == {"runtime_error": 1}
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


def test_record_runtime_error_writes_event_without_overwriting_resumable_session():
    tmp_dir = make_test_dir("main-runtime-error-event")
    try:
        from agent.cli.main import _record_runtime_error

        sessions_dir = tmp_dir / "agent-alpha" / "session-log" / "sessions"
        events_dir = tmp_dir / "agent-alpha" / "session-log" / "events"
        workspace_root = tmp_dir / "agent-alpha" / "workspace"
        store = SessionStore(sessions_dir)
        clean_history = [{"role": "user", "content": "clean resumable history"}]
        store.save(
            SessionRecord(
                session_id="abc123",
                kind=SessionKind.INTERACTIVE,
                workspace=str(workspace_root),
                history=clean_history,
                created_at="2026-06-14T10:00:00",
                updated_at="2026-06-14T10:00:00",
            )
        )

        _record_runtime_error(
            events_dir=events_dir,
            session_id="abc123",
            exc=RuntimeError("Content Exists Risk"),
        )

        records = _read_event_records(events_dir / "abc123.jsonl")
        assert records[0]["type"] == "runtime_error"
        assert records[0]["event"]["error_type"] == "RuntimeError"
        assert records[0]["event"]["message"] == "Content Exists Risk"
        assert "traceback" not in records[0]["event"]
        assert store.load("abc123").history == clean_history
    finally:
        cleanup_test_dir(tmp_dir)


def test_recoverable_snapshot_preserves_user_input_after_runtime_failure():
    tmp_dir = make_test_dir("main-recoverable-snapshot-user-input")
    try:
        from agent.cli.main import _save_recoverable_session_snapshot

        sessions_dir = tmp_dir / "agent-alpha" / "session-log" / "sessions"
        workspace_root = tmp_dir / "agent-alpha" / "workspace"
        store = SessionStore(sessions_dir)
        user_input = "最新的2024的那篇文章，意识的涌现过程能不能再具体一些\n也是用ljg的办法"
        agent = SimpleNamespace(
            history=[
                {"role": "user", "content": "previous turn"},
                {"role": "assistant", "content": "previous answer"},
                {"role": "user", "content": user_input},
            ],
            runtime_events=[],
        )

        saved = _save_recoverable_session_snapshot(
            store=store,
            session_id="abc123",
            agent=agent,
            workspace=workspace_root,
            created_at=datetime(2026, 6, 23, 10, 0, 0),
            metadata={"project_root": str(tmp_dir / "agent-alpha")},
        )

        record = store.load("abc123")
        assert saved is True
        assert record is not None
        assert record.history[-1] == {"role": "user", "content": user_input}
        assert [message["role"] for message in record.history] == ["user", "assistant", "user"]
    finally:
        cleanup_test_dir(tmp_dir)


def test_recoverable_snapshot_failure_is_reported_but_not_raised(capsys):
    tmp_dir = make_test_dir("main-recoverable-snapshot-save-fails")
    try:
        from agent.cli.main import _save_recoverable_session_snapshot

        class FailingStore:
            def load(self, _session_id):
                return None

            def save(self, _record):
                raise OSError("disk full")

        workspace_root = tmp_dir / "agent-alpha" / "workspace"
        agent = SimpleNamespace(
            history=[{"role": "user", "content": "must not be lost silently"}],
            runtime_events=[],
        )

        saved = _save_recoverable_session_snapshot(
            store=FailingStore(),
            session_id="abc123",
            agent=agent,
            workspace=workspace_root,
            created_at=datetime(2026, 6, 23, 10, 0, 0),
            metadata={"project_root": str(tmp_dir / "agent-alpha")},
        )

        assert saved is False
        assert "Failed to save recoverable session snapshot: disk full" in capsys.readouterr().out
    finally:
        cleanup_test_dir(tmp_dir)


def test_cli_runtime_error_saves_latest_user_input_before_resume_snapshot(capsys, monkeypatch):
    tmp_dir = make_test_dir("main-cli-runtime-error-saves-user-input")
    try:
        import agent.cli.main as cli_main

        project_root = tmp_dir / "agent-alpha"
        sessions_dir = project_root / "session-log" / "sessions"
        logs_dir = project_root / "session-log" / "logs"
        workspace_root = project_root / "workspace"
        sessions_dir.mkdir(parents=True)
        logs_dir.mkdir(parents=True)
        workspace_root.mkdir(parents=True)
        latest_input = "最新的2024的那篇文章，意识的涌现过程能不能再具体一些"

        class CrashingAgent:
            def __init__(self):
                self.history = []
                self.runtime_events = []
                self.workspace_root = workspace_root

            def handle(self, request):
                self.history.append({"role": "user", "content": request.content})
                raise RuntimeError("llm connection dropped")

            def get_session_log_data(self):
                return {"history": list(self.history), "events": list(self.runtime_events)}

            def close(self):
                pass

        monkeypatch.setattr(cli_main, "PROJECT_ROOT", project_root)
        monkeypatch.setattr(cli_main, "_generate_session_id", lambda: "abc123")
        monkeypatch.setattr(
            cli_main,
            "create_cli_session",
            lambda _project_root: (sessions_dir, logs_dir, workspace_root),
        )
        monkeypatch.setattr(cli_main, "_create_runtime", lambda *_args, **_kwargs: CrashingAgent())
        inputs = iter([latest_input, "q"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        cli_main.run_single_agent_cli()

        record = SessionStore(sessions_dir).load("abc123")
        records = _read_event_records(project_root / "session-log" / "events" / "abc123.jsonl")
        assert record is not None
        assert record.history[-1] == {"role": "user", "content": latest_input}
        assert records[-1]["type"] == "runtime_error"
        assert records[-1]["event"]["message"] == "llm connection dropped"
        log_files = list(logs_dir.glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert log_data["history"][-1] == {"role": "user", "content": latest_input}
        assert log_data["runtime_event_stats"]["runtime_event_type_counts"] == {"runtime_error": 1}
        assert log_data["events"][-1]["type"] == "runtime_error"
        assert log_data["events"][-1]["message"] == "llm connection dropped"
        assert "RuntimeError: llm connection dropped" in log_data["events"][-1]["traceback"]
        assert "Error: llm connection dropped" in capsys.readouterr().out
    finally:
        cleanup_test_dir(tmp_dir)
