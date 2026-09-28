import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.server.routes.projects import _default_picker_dir, _host_user_profile, _temporary_host_profile_env
from agent.core.session_store import SessionRecord
from agent.server.models import RetrospectiveRequest
from agent.server.routes.sessions import (
    _display_history_for_record,
    _read_event_file,
    create_retrospective,
    get_session,
)


def test_read_event_file_accepts_pretty_jsonl(tmp_path):
    path = tmp_path / "sess_1.jsonl"
    events = [
        {"seq": 1, "type": "assistant", "event": {"message": "thinking"}},
        {"seq": 2, "type": "tool_result", "event": {"tool_name": "bash", "content": "ok"}},
    ]
    path.write_text("\n\n".join(json.dumps(event, ensure_ascii=False, indent=2) for event in events), encoding="utf-8")

    assert _read_event_file(path) == events


def test_delete_can_retry_a_session_archived_by_failed_cleanup(monkeypatch):
    from agent.server.routes.sessions import delete_session

    deleted = []
    record = SessionRecord(session_id="sess", metadata={"is_archived": True})
    manager = SimpleNamespace(store=SimpleNamespace(load=lambda session_id: record),
                              delete_session=lambda session_id: deleted.append(session_id) or True)
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", manager)
    assert delete_session("sess") == {"ok": True}
    assert deleted == ["sess"]


def test_display_history_uses_event_entries_when_snapshot_was_truncated(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    session_id = "sess_damaged"
    full_history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    event_objects = [
        {"seq": index, "entry": message}
        for index, message in enumerate(full_history, start=1)
    ]
    (events_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False, indent=2) for event in event_objects),
        encoding="utf-8",
    )
    record = SessionRecord(
        session_id=session_id,
        history=[{"role": "assistant", "content": "Compressed summary"}],
    )

    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", SimpleNamespace(events_dir=events_dir))

    assert _display_history_for_record(record) == full_history


def test_display_history_uses_event_entries_when_user_count_matches_but_messages_are_missing(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    session_id = "sess_partially_damaged"
    full_history = [
        {"role": "user", "content": "same user"},
        {"role": "assistant", "content": "answer"},
    ]
    (events_dir / f"{session_id}.jsonl").write_text(
        "\n".join(
            json.dumps({"seq": index, "entry": message}, ensure_ascii=False, indent=2)
            for index, message in enumerate(full_history, start=1)
        ),
        encoding="utf-8",
    )
    record = SessionRecord(
        session_id=session_id,
        history=[{"role": "user", "content": "same user"}],
    )

    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", SimpleNamespace(events_dir=events_dir))

    assert _display_history_for_record(record) == full_history


def test_display_history_keeps_partial_answer_when_stream_is_interrupted(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    session_id = "sess_interrupted_stream"
    events = [
        {"seq": 1, "request_id": "run1", "entry": {"role": "user", "content": "继续"}},
        {"seq": 2, "type": "llm_request_started", "event": {"request_id": "run1"}},
        {"seq": 3, "type": "assistant_delta", "event": {"content": "已经生成"}},
        {"seq": 4, "type": "assistant_delta", "event": {"content": "一半"}},
        {"seq": 5, "type": "llm_request_interrupted", "event": {"request_id": "run1"}},
    ]
    (events_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8",
    )
    record = SessionRecord(session_id=session_id, history=[events[0]["entry"]])
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", SimpleNamespace(events_dir=events_dir))

    assert _display_history_for_record(record) == [
        events[0]["entry"],
          {"role": "assistant", "content": "已经生成一半", "_partial": True},
    ]


def test_partial_answer_merges_into_complete_history_when_event_entries_are_missing(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    session_id = "sess_incomplete_events"
    events = [
        {"seq": 1, "request_id": "run1", "entry": {"role": "user", "content": "first"}},
        {"seq": 2, "request_id": "run2", "entry": {"role": "user", "content": "second"}},
        {"seq": 3, "type": "llm_request_started", "event": {"request_id": "run2"}},
        {"seq": 4, "type": "assistant_delta", "event": {"content": "partial answer"}},
        {"seq": 5, "type": "llm_request_interrupted", "event": {"request_id": "run2"}},
    ]
    (events_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8",
    )
    full_history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "missing old answer"},
        {"role": "tool", "content": "missing tool result"},
        {"role": "user", "content": "second"},
    ]
    record = SessionRecord(session_id=session_id, history=full_history)
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", SimpleNamespace(events_dir=events_dir))

    assert _display_history_for_record(record) == [
        *full_history,
        {"role": "assistant", "content": "partial answer", "_partial": True},
    ]


def test_session_detail_restores_unprocessed_user_steer_once(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    events = [
        {"seq": 1, "request_id": "run1", "entry": {"role": "user", "content": "已有消息", "_message_id": "old"}},
        {"seq": 2, "type": "llm_request_started", "event": {"request_id": "run1"}},
        {"seq": 3, "type": "assistant_delta", "event": {"content": "中断前的回答"}},
        {"seq": 4, "type": "llm_request_interrupted", "event": {"request_id": "run1"}},
    ]
    (events_dir / "sess_mailbox.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8",
    )
    record = SessionRecord(
        session_id="sess_mailbox",
        workspace=str(tmp_path),
        history=[{"role": "user", "content": "已有消息", "_message_id": "old"}],
        metadata={"project_id": "project", "title": "会话", "mailbox": [
            {"id": "old", "sender_id": None, "content": "已有消息", "delivery": "steer", "state": "delivered"},
            {"id": "pending", "sender_id": None, "content": "等待输入", "delivery": "steer", "state": "pending"},
            {"id": "child", "sender_id": "agent_1", "content": "子 Agent 消息", "delivery": "steer", "state": "pending"},
            {"id": "done", "sender_id": None, "content": "已处理", "delivery": "steer", "state": "delivered"},
        ]},
    )
    monkeypatch.setattr(
        "agent.server.routes.sessions.agent_manager",
        SimpleNamespace(events_dir=events_dir, get_session=lambda session_id: record),
    )

    detail = get_session(record.session_id)

    assert [(message.message_id, message.content, message.delivery_status) for message in detail.messages] == [
        ("old", "已有消息", "received"),
        (None, "中断前的回答", None),
        ("pending", "等待输入", "waiting"),
    ]
    assert detail.messages[1].partial


def test_session_detail_exposes_subagent_message_origin_and_reply_link(monkeypatch, tmp_path):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    record = SessionRecord(
        session_id="sess_subagent_display",
        workspace=str(tmp_path),
        history=[
            {"role": "user", "content": "检查项目"},
            {
                "role": "user",
                "content": "[异步子 agent 结果：内部上下文]\n检查完成。",
                "_message_id": "result-1",
                "_sender_id": "agent-a",
                "_source": "subagent_result",
                "_reply_to": ["mail-1"],
                "_result_agent_id": "agent-a",
                "_result_run_id": "run-a",
            },
        ],
    )
    manager = SimpleNamespace(events_dir=events_dir, get_session=lambda _session_id: record)
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", manager)

    detail = get_session(record.session_id)

    result = detail.messages[1]
    assert result.source == "subagent_result"
    assert result.source_agent_id == "agent-a"
    assert result.reply_to == ["mail-1"]
    assert result.result_agent_id == "agent-a"
    assert result.result_run_id == "run-a"


def test_folder_picker_default_dir_exists():
    assert _default_picker_dir().exists()


def test_host_user_profile_uses_public_parent_and_username(monkeypatch, tmp_path):
    users_dir = tmp_path / "Users"
    public = users_dir / "Public"
    profile = users_dir / "alice"
    public.mkdir(parents=True)
    profile.mkdir()

    monkeypatch.setattr("agent.server.routes.projects.os.name", "nt")

    result = _host_user_profile({"PUBLIC": str(public), "USERNAME": "alice", "SystemDrive": "Z:"})

    assert result == profile.resolve()


def test_temporary_host_profile_env_restores_runtime_home(monkeypatch, tmp_path):
    users_dir = tmp_path / "Users"
    public = users_dir / "Public"
    profile = users_dir / "alice"
    public.mkdir(parents=True)
    profile.mkdir()
    runtime_home = tmp_path / "agent-alpha" / "home"

    monkeypatch.setattr("agent.server.routes.projects.os.name", "nt")
    monkeypatch.setenv("PUBLIC", str(public))
    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.setenv("USERPROFILE", str(runtime_home))
    monkeypatch.setenv("HOME", str(runtime_home))

    with _temporary_host_profile_env():
        assert str(profile) == __import__("os").environ["USERPROFILE"]

    assert __import__("os").environ["USERPROFILE"] == str(runtime_home)
    assert __import__("os").environ["HOME"] == str(runtime_home)


def test_project_retrospective_filters_sources_and_includes_log_paths(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    events_dir = tmp_path / "events"
    logs_dir = tmp_path / "logs"
    workspace.mkdir()
    events_dir.mkdir()
    logs_dir.mkdir()
    source = SessionRecord(
        session_id="sess_source",
        workspace=str(workspace),
        metadata={"project_id": "proj_1", "title": "原会话", "is_archived": True},
    )
    (events_dir / "sess_source.jsonl").write_text("{}", encoding="utf-8")
    (logs_dir / "sess_source.jsonl").write_text("{}", encoding="utf-8")
    created = SessionRecord(
        session_id="sess_review",
        workspace=str(workspace),
        metadata={"project_id": "proj_1", "title": "项目复盘"},
    )
    captured = {}

    class FakeManager:
        def list_sessions(self, *, project_id, include_archived):
            captured["list"] = (project_id, include_archived)
            return [source]

        def get_active_run_for_session(self, session_id):
            return {"status": "running"} if session_id == source.session_id else None

        def create_session(self, **_kwargs):
            return created

        def start_chat(self, **kwargs):
            captured["start"] = kwargs
            return "req_review"

        def delete_session(self, _session_id):
            raise AssertionError("successful start must not delete review session")

    manager = FakeManager()
    manager.events_dir = events_dir
    manager.logs_dir = logs_dir
    manager.store = SimpleNamespace(load=lambda _session_id: None)
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", manager)
    monkeypatch.setattr(
        "agent.server.routes.sessions.state_store",
        SimpleNamespace(
            get_project=lambda _project_id: {"id": "proj_1", "name": "项目一", "workspace_path": str(workspace)},
            get_settings=lambda: {"permission_mode": "ask"},
        ),
    )

    result = create_retrospective(RetrospectiveRequest(project_id="proj_1", scope="project"))

    assert result.session.id == "sess_review"
    assert result.run.request_id == "req_review"
    assert captured["list"] == ("proj_1", True)
    prompt = captured["start"]["message"]
    assert "[系统复盘任务]" in prompt
    assert str(events_dir / "sess_source.jsonl") in prompt
    assert str(logs_dir / "sess_source.jsonl") in prompt
    assert "仍在运行" in prompt
    assert "session-log/sessions" not in prompt.replace("\\", "/")
    assert captured["start"]["runtime_metadata"] == {"retrospective_scope": "project"}


def test_session_retrospective_rejects_source_from_other_project(monkeypatch, tmp_path):
    source = SessionRecord(session_id="sess_other", metadata={"project_id": "proj_other"})
    manager = SimpleNamespace(store=SimpleNamespace(load=lambda _session_id: source))
    state = SimpleNamespace(
        get_project=lambda _project_id: {"id": "proj_1", "name": "项目一", "workspace_path": str(tmp_path)}
    )
    monkeypatch.setattr("agent.server.routes.sessions.agent_manager", manager)
    monkeypatch.setattr("agent.server.routes.sessions.state_store", state)

    with pytest.raises(HTTPException) as exc_info:
        create_retrospective(
            RetrospectiveRequest(project_id="proj_1", scope="session", source_session_id="sess_other")
        )

    assert exc_info.value.status_code == 404
