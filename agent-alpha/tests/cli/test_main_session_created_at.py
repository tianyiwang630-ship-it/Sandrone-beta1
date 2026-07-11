from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from agent.cli import main as cli_main
from agent.core.session_store import SessionKind, SessionRecord


class FakeAgent:
    def __init__(self):
        self.history: list[dict] = []
        self.tool_loader = SimpleNamespace(permission_manager=None)
        self.workspace_root = Path(".")

    def close(self) -> None:
        return None

    def reset(self) -> None:
        self.history = []


def test_run_single_agent_cli_uses_initial_started_at_for_new_session(monkeypatch, tmp_path):
    captures: dict[str, object] = {}
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "logs"
    workspace_root = tmp_path / "workspace"
    events_dir = tmp_path / "events"
    for path in (sessions_dir, logs_dir, workspace_root, events_dir):
        path.mkdir()

    monkeypatch.setattr(cli_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli_main, "apply_runtime_env", lambda _project_root: None)
    monkeypatch.setattr(cli_main, "_generate_session_id", lambda: "sess_new")
    monkeypatch.setattr(cli_main, "create_cli_session", lambda _project_root: (sessions_dir, logs_dir, workspace_root))
    monkeypatch.setattr(cli_main, "build_log_path", lambda *_args, **_kwargs: logs_dir / "session.json")
    monkeypatch.setattr(cli_main, "save_session_log", lambda **_kwargs: None)

    class FakeSessionStore:
        def __init__(self, _sessions_dir: Path):
            self.sessions_dir = _sessions_dir

    monkeypatch.setattr(cli_main, "SessionStore", FakeSessionStore)

    def fake_create_runtime(workspace, logs, events, session_created_at=None, history=None, permission_mode=None):
        captures["session_created_at"] = session_created_at
        return FakeAgent()

    monkeypatch.setattr(cli_main, "_create_runtime", fake_create_runtime)

    def fake_save_session_snapshot(**kwargs):
        captures["snapshot_created_at"] = kwargs["created_at"].isoformat()

    monkeypatch.setattr(cli_main, "_save_session_snapshot", fake_save_session_snapshot)

    answers = iter(["quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    cli_main.run_single_agent_cli()

    assert captures["session_created_at"] == captures["snapshot_created_at"]


def test_run_single_agent_cli_uses_original_created_at_when_resuming(monkeypatch, tmp_path):
    captures: list[str | None] = []
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "logs"
    workspace_root = tmp_path / "workspace"
    events_dir = tmp_path / "events"
    for path in (sessions_dir, logs_dir, workspace_root, events_dir):
        path.mkdir()

    resumed_record = SessionRecord(
        session_id="sess_resumed",
        kind=SessionKind.INTERACTIVE,
        workspace=str(workspace_root),
        history=[{"role": "user", "content": "earlier"}],
        metadata={"project_root": str(tmp_path)},
        created_at="2026-06-28T08:30:00",
    )

    monkeypatch.setattr(cli_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli_main, "apply_runtime_env", lambda _project_root: None)
    monkeypatch.setattr(cli_main, "_generate_session_id", lambda: "sess_new")
    monkeypatch.setattr(cli_main, "create_cli_session", lambda _project_root: (sessions_dir, logs_dir, workspace_root))
    monkeypatch.setattr(cli_main, "build_log_path", lambda *_args, **_kwargs: logs_dir / "session.json")
    monkeypatch.setattr(cli_main, "save_session_log", lambda **_kwargs: None)
    monkeypatch.setattr(cli_main, "_restore_session_interactive", lambda _store: resumed_record)

    class FakeSessionStore:
        def __init__(self, _sessions_dir: Path):
            self.sessions_dir = _sessions_dir

    monkeypatch.setattr(cli_main, "SessionStore", FakeSessionStore)
    monkeypatch.setattr(cli_main, "_save_session_snapshot", lambda **_kwargs: None)

    def fake_create_runtime(workspace, logs, events, session_created_at=None, history=None, permission_mode=None):
        captures.append(session_created_at)
        return FakeAgent()

    monkeypatch.setattr(cli_main, "_create_runtime", fake_create_runtime)

    answers = iter(["/resume", "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    cli_main.run_single_agent_cli()

    assert len(captures) >= 2
    assert captures[1] == resumed_record.created_at
