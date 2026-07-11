import json
from types import SimpleNamespace

from agent.server.routes.projects import _default_picker_dir, _host_user_profile, _temporary_host_profile_env
from agent.core.session_store import SessionRecord
from agent.server.routes.sessions import _display_history_for_record, _read_event_file


def test_read_event_file_accepts_pretty_jsonl(tmp_path):
    path = tmp_path / "sess_1.jsonl"
    events = [
        {"seq": 1, "type": "assistant", "event": {"message": "thinking"}},
        {"seq": 2, "type": "tool_result", "event": {"tool_name": "bash", "content": "ok"}},
    ]
    path.write_text("\n\n".join(json.dumps(event, ensure_ascii=False, indent=2) for event in events), encoding="utf-8")

    assert _read_event_file(path) == events


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
