from pathlib import Path
import json
from types import SimpleNamespace

from agent.core.runtime_types import RuntimeResponse
from agent.core.session_store import SessionKind, SessionRecord, SessionStore
from agent.core.session_events import SessionEventWriter
from agent.server import agent_manager as agent_manager_module
from agent.server.agent_manager import AgentManager


def read_event_objects(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    events = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        event, index = decoder.raw_decode(text, index)
        events.append(event)
    return events


def test_cleanup_legacy_sessions_removes_non_project_snapshots(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "logs"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    logs_dir.mkdir()
    events_dir.mkdir()

    store = SessionStore(sessions_dir)
    legacy = SessionRecord(session_id="legacy1", kind=SessionKind.INTERACTIVE, workspace="workspace", metadata={})
    scoped = SessionRecord(
        session_id="scoped1",
        kind=SessionKind.INTERACTIVE,
        workspace="workspace",
        metadata={"project_id": "proj_1"},
    )
    store.save(legacy)
    store.save(scoped)
    (events_dir / "legacy1.jsonl").write_text("{}", encoding="utf-8")
    (logs_dir / "2026_session_legacy1.json").write_text("{}", encoding="utf-8")

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager.logs_dir = logs_dir

    removed = AgentManager.cleanup_legacy_sessions(manager)

    assert removed == 1
    assert store.load("legacy1") is None
    assert store.load("scoped1") is not None
    assert not (events_dir / "legacy1.jsonl").exists()


def test_delete_session_removes_snapshot_events_and_logs(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "logs"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    logs_dir.mkdir()
    events_dir.mkdir()

    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess1",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj1"},
    )
    store.save(record)
    (events_dir / "sess1.jsonl").write_text("{}", encoding="utf-8")
    (logs_dir / "2026_session_sess1.json").write_text("{}", encoding="utf-8")
    (logs_dir / "sess1.jsonl").write_text("{}", encoding="utf-8")

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager.logs_dir = logs_dir
    manager._agents = {"sess1": object()}
    manager._lock = __import__("threading").RLock()
    manager._runs = {}
    manager.interrupt = lambda session_id: True
    manager.release = lambda session_id: manager._agents.pop(session_id, None)

    assert AgentManager.delete_session(manager, "sess1") is True

    assert store.load("sess1") is None
    assert not (events_dir / "sess1.jsonl").exists()
    assert not (logs_dir / "2026_session_sess1.json").exists()
    assert not (logs_dir / "sess1.jsonl").exists()
    assert "sess1" not in manager._agents


def test_list_sessions_keeps_pinned_sessions_first(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = SessionStore(sessions_dir)

    regular = SessionRecord(
        session_id="sess_regular",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj1", "is_pinned": False},
        updated_at="2026-06-25T21:00:00",
    )
    pinned = SessionRecord(
        session_id="sess_pinned",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj1", "is_pinned": True},
        updated_at="2026-06-25T20:00:00",
    )
    other_project = SessionRecord(
        session_id="sess_other",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj2", "is_pinned": True},
        updated_at="2026-06-25T22:00:00",
    )
    store.save(regular)
    store.save(pinned)
    store.save(other_project)

    manager = AgentManager.__new__(AgentManager)
    manager.store = store

    records = AgentManager.list_sessions(manager, project_id="proj1")

    assert [record.session_id for record in records] == ["sess_pinned", "sess_regular"]


def test_get_agent_passes_session_created_at_to_runtime(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeAgentRuntime:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.llm = SimpleNamespace(stream_responses=False)
            self.history = []
            self.tool_loader = SimpleNamespace(permission_manager=None)
            self.workspace_root = kwargs["workspace_root"]

    monkeypatch.setattr(agent_manager_module, "AgentRuntime", FakeAgentRuntime)

    manager = AgentManager.__new__(AgentManager)
    manager.logs_dir = tmp_path / "logs"
    manager.events_dir = tmp_path / "events"
    manager._agents = {}
    manager._lock = __import__("threading").RLock()

    record = SessionRecord(
        session_id="sess_created",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[{"role": "user", "content": "hi"}],
        metadata={"project_id": "proj1"},
        created_at="2026-06-30T09:15:00",
    )

    manager.store = SessionStore(tmp_path / "sessions")
    manager.store.save(record)
    agent = AgentManager._get_agent(manager, record, "ask", {"model": "x"})

    assert captured["session_created_at"] == "2026-06-30T09:15:00"
    assert captured["workspace_root"] == str(tmp_path / "workspace")
    assert agent.llm.stream_responses is True
    assert agent.history == [{"role": "user", "content": "hi"}]


def test_get_agent_prefers_runtime_history_for_model_context(monkeypatch, tmp_path):
    class FakeAgentRuntime:
        def __init__(self, **kwargs):
            self.llm = SimpleNamespace(stream_responses=False)
            self.history = []
            self.tool_loader = SimpleNamespace(permission_manager=None)
            self.workspace_root = kwargs["workspace_root"]

    monkeypatch.setattr(agent_manager_module, "AgentRuntime", FakeAgentRuntime)

    manager = AgentManager.__new__(AgentManager)
    manager.logs_dir = tmp_path / "logs"
    manager.events_dir = tmp_path / "events"
    manager._agents = {}
    manager._lock = __import__("threading").RLock()

    record = SessionRecord(
        session_id="sess_runtime",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "full display"},
        ],
        runtime_history=[{"role": "assistant", "content": "compressed context"}],
        metadata={"project_id": "proj1"},
    )

    manager.store = SessionStore(tmp_path / "sessions")
    manager.store.save(record)
    agent = AgentManager._get_agent(manager, record, "ask", {})

    assert agent.history == [{"role": "assistant", "content": "compressed context"}]


def test_get_agent_reuses_runtime_across_web_turns(monkeypatch, tmp_path):
    created_agents = []

    class FakePermissionManager:
        def __init__(self):
            self.mode = None

        def set_mode(self, mode):
            self.mode = mode

    class FakeAgentRuntime:
        def __init__(self, **kwargs):
            self.llm = SimpleNamespace(stream_responses=False)
            self.history = []
            self.tool_loader = SimpleNamespace(permission_manager=FakePermissionManager())
            self.workspace_root = kwargs["workspace_root"]
            self.llm_settings = kwargs["llm_settings"]
            created_agents.append(self)

    monkeypatch.setattr(agent_manager_module, "AgentRuntime", FakeAgentRuntime)

    manager = AgentManager.__new__(AgentManager)
    manager.logs_dir = tmp_path / "logs"
    manager.events_dir = tmp_path / "events"
    manager._agents = {}
    manager._lock = __import__("threading").RLock()
    record = SessionRecord(
        session_id="sess_browser_state",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj1"},
    )

    manager.store = SessionStore(tmp_path / "sessions")
    manager.store.save(record)
    first = AgentManager._get_agent(manager, record, "ask", {"model": "x"})
    setattr(first, "browser_session_mode", "local-headed-login")
    second = AgentManager._get_agent(manager, record, "ask", {"model": "x"})

    assert second is first
    assert second.browser_session_mode == "local-headed-login"
    assert len(created_agents) == 1


def test_interrupt_calls_runtime_interrupt():
    class FakeAgent:
        def __init__(self):
            self.interrupted = False

        def interrupt(self):
            self.interrupted = True

    agent = FakeAgent()
    manager = AgentManager.__new__(AgentManager)
    manager._agents = {"sess1": agent}
    manager._lock = __import__("threading").RLock()

    assert AgentManager.interrupt(manager, "sess1") is True
    assert agent.interrupted is True


def test_start_chat_persists_user_message_before_background_run(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_pending",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[],
        metadata={"project_id": "proj1", "title": ""},
        created_at="2026-07-03T09:00:00",
    )
    store.save(record)

    class FakeExecutor:
        def __init__(self):
            self.submitted = None

        def submit(self, fn, *args):
            self.submitted = (fn, args)

    executor = FakeExecutor()
    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager._runs = {}
    manager._lock = __import__("threading").RLock()
    manager._executor = executor

    request_id = AgentManager.start_chat(manager, session_id="sess_pending", message="hello", permission_mode="ask")

    saved = store.load("sess_pending")
    assert saved is not None
    assert saved.history == [{"role": "user", "content": "hello"}]
    assert saved.runtime_history == [{"role": "user", "content": "hello"}]
    assert saved.metadata["title"] == "hello"
    assert manager.get_run(request_id)["status"] == "running"
    assert executor.submitted is not None
    assert executor.submitted[1][1].history == []


def test_start_compact_creates_compact_run_without_adding_user_message(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_compact_start",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[{"role": "user", "content": "hello"}],
        runtime_history=[{"role": "user", "content": "hello"}],
        metadata={"project_id": "proj1", "title": "hello"},
        created_at="2026-07-09T09:00:00",
    )
    store.save(record)

    class FakeExecutor:
        def __init__(self):
            self.submitted = None

        def submit(self, fn, *args):
            self.submitted = (fn, args)

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {}
    manager._lock = __import__("threading").RLock()
    manager._executor = FakeExecutor()

    request_id = AgentManager.start_compact(manager, session_id="sess_compact_start", permission_mode="ask")

    run = manager.get_run(request_id)
    assert run["operation"] == "compact"
    assert run["status"] == "running"
    assert run["started_after_seq"] == 0
    saved = store.load("sess_compact_start")
    assert saved.history == [{"role": "user", "content": "hello"}]
    assert saved.runtime_history == [{"role": "user", "content": "hello"}]
    assert manager._executor.submitted is not None


def test_run_compact_success_updates_runtime_history_only(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_compact_success",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
        ],
        runtime_history=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
        ],
        metadata={"project_id": "proj1", "title": "old"},
        created_at="2026-07-09T09:00:00",
    )
    store.save(record)

    class Result:
        success = True
        fallback = False
        error = None

        def to_event(self):
            return {"type": "context_compacted", "success": True, "fallback": False}

    class FakeAgent:
        def __init__(self):
            self.history = [dict(item) for item in record.runtime_history]
            self.runtime_events = []
            self.interrupted = False

        def clear_interrupt(self):
            self.interrupted = False

        def is_interrupted(self):
            return self.interrupted

        def compact_history(self, *, trigger, allow_fallback):
            assert trigger == "manual-web"
            assert allow_fallback is False
            self.history = [{"role": "user", "content": "Summary of old work."}]
            return Result()

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {
        "req_compact": {
            "request_id": "req_compact",
            "session_id": "sess_compact_success",
            "status": "running",
            "operation": "compact",
            "started_after_seq": 0,
            "created_at": "2026-07-09T09:01:00",
            "updated_at": "2026-07-09T09:01:00",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_compact(manager, "req_compact", record, "ask", {})

    saved = store.load("sess_compact_success")
    assert saved.history == record.history
    assert saved.runtime_history == [{"role": "user", "content": "Summary of old work."}]
    assert manager.get_run("req_compact")["status"] == "success"
    events = read_event_objects(events_dir / "sess_compact_success.jsonl")
    assert [event["type"] for event in events] == ["context_compaction_started", "context_compacted"]


def test_run_compact_failure_preserves_runtime_history(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_compact_failed",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[{"role": "user", "content": "full"}],
        runtime_history=[{"role": "user", "content": "runtime"}],
        metadata={"project_id": "proj1", "title": "full"},
        created_at="2026-07-09T09:00:00",
    )
    store.save(record)

    class Result:
        success = False
        fallback = False
        error = "timeout"

        def to_event(self):
            return {"type": "context_compaction_failed", "success": False, "fallback": False, "error": self.error}

    class FakeAgent:
        def __init__(self):
            self.history = [{"role": "user", "content": "too long"}]
            self.runtime_events = []

        def clear_interrupt(self):
            pass

        def is_interrupted(self):
            return False

        def compact_history(self, **_kwargs):
            return Result()

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {"req_failed": {"request_id": "req_failed", "session_id": record.session_id, "status": "running"}}
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_compact(manager, "req_failed", record, "ask", {})

    saved = store.load(record.session_id)
    assert saved.history == record.history
    assert saved.runtime_history == record.runtime_history
    run = manager.get_run("req_failed")
    assert run["status"] == "failed"
    assert run["error"] == "timeout"


def test_run_compact_interrupt_preserves_runtime_history_and_marks_interrupted(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_compact_interrupted",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[{"role": "user", "content": "full"}],
        runtime_history=[{"role": "user", "content": "runtime"}],
        metadata={"project_id": "proj1", "title": "full"},
        created_at="2026-07-09T09:00:00",
    )
    store.save(record)

    class Result:
        success = False
        fallback = False
        error = "LLM request interrupted"

    class FakeAgent:
        def __init__(self):
            self.history = [{"role": "user", "content": "runtime"}]
            self.runtime_events = []
            self.interrupted = False

        def clear_interrupt(self):
            self.interrupted = False

        def is_interrupted(self):
            return self.interrupted

        def compact_history(self, **_kwargs):
            self.interrupted = True
            return Result()

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {"req_interrupt": {"request_id": "req_interrupt", "session_id": record.session_id, "status": "running"}}
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_compact(manager, "req_interrupt", record, "ask", {})

    saved = store.load(record.session_id)
    assert saved.history == record.history
    assert saved.runtime_history == record.runtime_history
    assert manager.get_run("req_interrupt")["status"] == "interrupted"
    events = read_event_objects(events_dir / "sess_compact_interrupted.jsonl")
    assert [event["type"] for event in events] == ["context_compaction_started", "context_compaction_interrupted"]


def test_get_active_run_for_session_returns_latest_running_only():
    manager = AgentManager.__new__(AgentManager)
    manager._lock = __import__("threading").RLock()
    manager._runs = {
        "done": {
            "request_id": "done",
            "session_id": "sess1",
            "status": "success",
            "created_at": "2026-07-03T09:00:00",
        },
        "old": {
            "request_id": "old",
            "session_id": "sess1",
            "status": "running",
            "created_at": "2026-07-03T09:01:00",
        },
        "new": {
            "request_id": "new",
            "session_id": "sess1",
            "status": "running",
            "created_at": "2026-07-03T09:02:00",
        },
    }

    run = AgentManager.get_active_run_for_session(manager, "sess1")

    assert run is not None
    assert run["request_id"] == "new"
    assert AgentManager.get_active_run_for_session(manager, "missing") is None


def test_run_chat_marks_interrupted_response(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_interrupted",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[],
        metadata={"project_id": "proj1", "title": "New chat"},
        created_at="2026-06-30T09:15:00",
    )

    class FakeAgent:
        def __init__(self):
            self.history = [{"role": "user", "content": "stop me"}]
            self.runtime_events = []

        def handle(self, _request):
            return RuntimeResponse(
                content="INTERRUPTED",
                session_id="sess_interrupted",
                metadata={"interrupted": True},
            )

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager._runs = {
        "req1": {
            "request_id": "req1",
            "session_id": "sess_interrupted",
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-06-30T09:15:00",
            "updated_at": "2026-06-30T09:15:00",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(manager, "req1", record, "stop me", "ask", {})

    run = manager.get_run("req1")
    assert run is not None
    assert run["status"] == "interrupted"
    assert run["response"] == "INTERRUPTED"
    saved = store.load("sess_interrupted")
    assert saved is not None
    assert saved.history == [{"role": "user", "content": "stop me"}]
    assert saved.runtime_history == [{"role": "user", "content": "stop me"}]


def test_run_chat_preserves_full_display_history_when_runtime_history_is_compacted(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    store = SessionStore(sessions_dir)
    full_history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
    ]
    compact_runtime_history = [
        {"role": "assistant", "content": "Summary of earlier conversation."},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]
    record = SessionRecord(
        session_id="sess_compacted",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ],
        runtime_history=[{"role": "assistant", "content": "Summary of earlier conversation."}],
        metadata={"project_id": "proj1", "title": "old question"},
        created_at="2026-07-05T09:15:00",
    )
    store.save(
        SessionRecord(
            session_id=record.session_id,
            kind=record.kind,
            workspace=record.workspace,
            history=full_history,
            runtime_history=[
                {"role": "assistant", "content": "Summary of earlier conversation."},
                {"role": "user", "content": "new question"},
            ],
            metadata=dict(record.metadata),
            created_at=record.created_at,
            updated_at="2026-07-05T09:16:00",
        )
    )

    class FakeAgent:
        def __init__(self):
            self.history = [dict(item) for item in compact_runtime_history]
            self.runtime_events = []

        def handle(self, _request):
            return RuntimeResponse(content="new answer", session_id="sess_compacted", metadata={})

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager._runs = {
        "req_compacted": {
            "request_id": "req_compacted",
            "session_id": "sess_compacted",
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-05T09:16:00",
            "updated_at": "2026-07-05T09:16:00",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(manager, "req_compacted", record, "new question", "ask", {})

    saved = store.load("sess_compacted")
    assert saved is not None
    assert saved.history == full_history + [{"role": "assistant", "content": "new answer"}]
    assert saved.runtime_history == compact_runtime_history


def test_run_chat_failure_persists_partial_history_and_run_failed_event(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_failed",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[],
        metadata={"project_id": "proj1", "title": "New chat"},
        created_at="2026-07-05T09:00:00",
    )
    store.save(
        SessionRecord(
            session_id=record.session_id,
            kind=record.kind,
            workspace=record.workspace,
            history=[{"role": "user", "content": "make files"}],
            metadata={"project_id": "proj1", "title": "make files"},
            created_at=record.created_at,
            updated_at="2026-07-05T09:00:01",
        )
    )

    class APITimeoutError(Exception):
        pass

    partial_history = [
        {"role": "user", "content": "make files"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "write", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true}'},
    ]

    class FakeAgent:
        def __init__(self):
            self.history = [dict(item) for item in partial_history]
            self.runtime_events = [
                {
                    "type": "llm_request_exhausted",
                    "error_type": "APITimeoutError",
                    "error_message": "Request timed out.",
                }
            ]

        def handle(self, _request):
            raise APITimeoutError("Request timed out.")

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {
        "req_failed": {
            "request_id": "req_failed",
            "session_id": "sess_failed",
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-05T09:00:02",
            "updated_at": "2026-07-05T09:00:02",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(manager, "req_failed", record, "make files", "ask", {})

    run = manager.get_run("req_failed")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "Request timed out."
    assert run["tool_calls_count"] == 1

    saved = store.load("sess_failed")
    assert saved is not None
    assert saved.history == partial_history
    assert saved.runtime_history == partial_history
    assert not any(
        item.get("role") == "assistant" and "模型连接失败" in str(item.get("content") or "")
        for item in saved.history
    )
    assert saved.events[-1]["type"] == "run_failed"
    assert saved.events[-1]["request_id"] == "req_failed"
    assert saved.events[-1]["error_type"] == "APITimeoutError"
    assert saved.events[-1]["tool_calls_count"] == 1

    event_objects = read_event_objects(events_dir / "sess_failed.jsonl")
    assert event_objects[-1]["type"] == "run_failed"
    assert event_objects[-1]["event"]["error_message"] == "Request timed out."


def test_run_chat_failure_does_not_replace_display_history_with_compacted_runtime(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    full_history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
    ]
    runtime_history = [
        {"role": "assistant", "content": "Summary of earlier conversation."},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true}'},
    ]
    record = SessionRecord(
        session_id="sess_failed_compacted",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ],
        runtime_history=[{"role": "assistant", "content": "Summary of earlier conversation."}],
        metadata={"project_id": "proj1", "title": "old question"},
        created_at="2026-07-05T11:00:00",
    )
    store.save(
        SessionRecord(
            session_id=record.session_id,
            kind=record.kind,
            workspace=record.workspace,
            history=full_history,
            runtime_history=[
                {"role": "assistant", "content": "Summary of earlier conversation."},
                {"role": "user", "content": "new question"},
            ],
            metadata=dict(record.metadata),
            created_at=record.created_at,
        )
    )

    class ModelDisconnected(Exception):
        pass

    class FakeAgent:
        def __init__(self):
            self.history = [dict(item) for item in runtime_history]
            self.runtime_events = []

        def handle(self, _request):
            raise ModelDisconnected("connection closed")

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {
        "req_failed_compacted": {
            "request_id": "req_failed_compacted",
            "session_id": "sess_failed_compacted",
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-05T11:01:00",
            "updated_at": "2026-07-05T11:01:00",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(manager, "req_failed_compacted", record, "new question", "ask", {})

    saved = store.load("sess_failed_compacted")
    assert saved is not None
    assert saved.history == full_history + runtime_history[2:]
    assert saved.runtime_history == runtime_history


def test_runtime_history_replays_checkpoint_entries_without_duplicating_pending_user(tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    record = SessionRecord(
        session_id="sess_replay",
        runtime_history=[{"role": "user", "content": "hello"}],
        runtime_checkpoint={
            "request_id": "req_replay",
            "status": "running",
            "started_after_seq": 0,
            "pending_user_message": "hello",
        },
    )
    writer = SessionEventWriter(events_dir, record.session_id)
    writer.write({"role": "user", "content": "hello"}, request_id="req_replay")
    writer.write({"role": "assistant", "content": "recovered"}, request_id="req_replay")

    manager = AgentManager.__new__(AgentManager)
    manager.events_dir = events_dir

    history = AgentManager._runtime_history_for_record(manager, record)

    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "recovered"},
    ]


def test_migrate_historical_events_skips_recovery_sessions(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    stable = SessionRecord(session_id="stable", metadata={"project_id": "proj"})
    recovering = SessionRecord(
        session_id="recovering",
        metadata={"project_id": "proj"},
        runtime_checkpoint={"status": "recoverable"},
    )
    store.save(stable)
    store.save(recovering)
    for record in (stable, recovering):
        writer = SessionEventWriter(events_dir, record.session_id)
        writer.write_event("assistant_delta", {"content": "stream"})

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir

    assert AgentManager.migrate_historical_events(manager) == 1
    assert read_event_objects(events_dir / "stable.jsonl") == []
    assert read_event_objects(events_dir / "recovering.jsonl")[0]["type"] == "assistant_delta"


def test_run_chat_success_removes_completed_stream_events(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_cleanup",
        workspace=str(tmp_path / "workspace"),
        metadata={"project_id": "proj", "title": "cleanup"},
    )
    store.save(record)
    writer = SessionEventWriter(events_dir, record.session_id)
    writer.write_event("assistant_delta", {"request_id": "req_cleanup", "content": "partial"})
    writer.write_event("llm_request_started", {"request_id": "req_cleanup"})
    writer.write({"role": "assistant", "content": "done"}, request_id="req_cleanup")

    class FakeAgent:
        history = [{"role": "user", "content": "work"}, {"role": "assistant", "content": "done"}]
        runtime_events = []

        def handle(self, request):
            return RuntimeResponse(content="done", session_id=request.session_id, metadata={})

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {"req_cleanup": {"request_id": "req_cleanup", "session_id": record.session_id}}
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(manager, "req_cleanup", record, "work", "ask", {}, {})

    events = read_event_objects(events_dir / "sess_cleanup.jsonl")
    assert [event.get("entry", {}).get("content") for event in events] == ["done"]


def test_run_chat_recovery_exhaustion_is_saved_as_resumable_checkpoint(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_recoverable",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[],
        runtime_history=[],
        metadata={"project_id": "proj1", "title": "新对话"},
    )
    store.save(
        SessionRecord(
            session_id=record.session_id,
            kind=record.kind,
            workspace=record.workspace,
            history=[{"role": "user", "content": "continue the work"}],
            runtime_history=[{"role": "user", "content": "continue the work"}],
            metadata=dict(record.metadata),
            created_at=record.created_at,
        )
    )

    class FakeAgent:
        def __init__(self):
            self.history = [{"role": "user", "content": "continue the work"}]
            self.runtime_events = []

        def handle(self, request):
            return RuntimeResponse(
                content="本轮未能完成，但现场已保留。",
                session_id=request.session_id,
                metadata={
                    "recoverable": True,
                    "recovery_stage": "exhausted",
                    "recovery_error": "invalid assistant response",
                },
            )

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {
        "req_recoverable": {
            "request_id": "req_recoverable",
            "session_id": record.session_id,
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-11T00:00:00",
            "updated_at": "2026-07-11T00:00:00",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: FakeAgent()

    AgentManager._run_chat(
        manager,
        "req_recoverable",
        record,
        "continue the work",
        "ask",
        {},
    )

    run = manager.get_run("req_recoverable")
    saved = store.load(record.session_id)
    assert run is not None
    assert run["status"] == "recoverable"
    assert run["can_resume"] is True
    assert run["recovery_stage"] == "exhausted"
    assert saved is not None
    assert saved.history == [{"role": "user", "content": "continue the work"}]
    assert saved.runtime_history == [{"role": "user", "content": "continue the work"}]
    assert saved.runtime_checkpoint["status"] == "recoverable"
    assert saved.runtime_checkpoint["pending_user_message"] == "continue the work"


def test_run_chat_failure_before_agent_keeps_pre_saved_user_message(tmp_path):
    sessions_dir = tmp_path / "sessions"
    events_dir = tmp_path / "events"
    sessions_dir.mkdir()
    events_dir.mkdir()
    store = SessionStore(sessions_dir)
    record = SessionRecord(
        session_id="sess_agent_fail",
        kind=SessionKind.INTERACTIVE,
        workspace=str(tmp_path / "workspace"),
        history=[],
        metadata={"project_id": "proj1", "title": "New chat"},
        created_at="2026-07-05T10:00:00",
    )
    store.save(
        SessionRecord(
            session_id=record.session_id,
            kind=record.kind,
            workspace=record.workspace,
            history=[{"role": "user", "content": "hello"}],
            metadata={"project_id": "proj1", "title": "hello"},
            created_at=record.created_at,
            updated_at="2026-07-05T10:00:01",
        )
    )

    manager = AgentManager.__new__(AgentManager)
    manager.store = store
    manager.events_dir = events_dir
    manager._runs = {
        "req_before_agent": {
            "request_id": "req_before_agent",
            "session_id": "sess_agent_fail",
            "status": "running",
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-05T10:00:02",
            "updated_at": "2026-07-05T10:00:02",
        }
    }
    manager._lock = __import__("threading").RLock()
    manager._get_agent = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("profile missing"))

    AgentManager._run_chat(manager, "req_before_agent", record, "hello", "ask", {})

    run = manager.get_run("req_before_agent")
    assert run is not None
    assert run["status"] == "failed"
    assert run["tool_calls_count"] == 0
    saved = store.load("sess_agent_fail")
    assert saved is not None
    assert saved.history == [{"role": "user", "content": "hello"}]
    assert saved.runtime_history == [{"role": "user", "content": "hello"}]
    assert saved.events[-1]["type"] == "run_failed"
    assert saved.events[-1]["error_message"] == "profile missing"

    event_objects = read_event_objects(events_dir / "sess_agent_fail.jsonl")
    assert event_objects[-1]["type"] == "run_failed"
    assert event_objects[-1]["event"]["history_message_count"] == 0
