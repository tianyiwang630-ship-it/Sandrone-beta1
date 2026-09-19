from datetime import datetime
from types import SimpleNamespace

import pytest

from agent.cli import main as cli_main
from agent.cli.managed import ManagedCLI
from agent.core.session_store import SessionRecord
from agent.server import agent_manager as manager_module


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(manager_module, "PROJECT_ROOT", tmp_path)
    manager = manager_module.AgentManager()
    manager._executor = SimpleNamespace(submit=lambda *args: None, shutdown=lambda: None)
    yield manager
    manager.release_all()


def test_cli_new_session_passes_its_persisted_creation_time_to_worker(manager, tmp_path):
    cli = ManagedCLI(manager, tmp_path)
    record = manager.store.load(cli.session_id)
    worker = manager._get_agent(record, "ask", {})
    assert worker.config["session_created_at"] == record.created_at
    assert datetime.fromisoformat(record.created_at)
    assert worker._process is None


def test_cli_resume_preserves_original_creation_time_and_does_not_execute(manager, monkeypatch, tmp_path):
    record = SessionRecord(
        session_id="old_cli", workspace=str(tmp_path),
        history=[{"role": "user", "content": "earlier"}],
        metadata={"project_root": str(tmp_path)}, created_at="2026-06-28T08:30:00",
    )
    manager.store.save(record)
    cli = ManagedCLI(manager, tmp_path)
    monkeypatch.setattr(cli_main, "_restore_session_interactive", lambda store: store.load(record.session_id))
    assert cli.command("/resume")
    assert cli.session_id == record.session_id
    assert not manager._runs
    worker = manager._get_agent(manager.store.load(cli.session_id), "ask", {})
    assert worker.config["session_created_at"] == record.created_at
    assert worker.history == record.history


def test_cli_queue_steer_and_stop_use_shared_supervisor(manager, tmp_path):
    cli = ManagedCLI(manager, tmp_path)
    cli.command("first")
    active = manager.get_active_run_for_session(cli.session_id)
    child = manager.collaboration.create(cli.session_id, "child", "work")
    cli.command("later")
    cli.command("/steer new direction")
    inputs = manager.collaboration.take_inputs(cli.session_id, active["request_id"])
    assert [entry["content"] for entry in inputs] == ["new direction"]
    cli.command("/stop")
    assert manager.get_run(active["request_id"])["status"] == "stopping"
    assert manager.get_run(child["request_id"])["status"] == "running"
    assert cli.command("quit") is False


def test_manager_keeps_existing_cli_sessions(manager, tmp_path):
    record = SessionRecord(session_id="legacy_cli", workspace=str(tmp_path),
                           metadata={"project_root": str(tmp_path)})
    manager.store.save(record)
    manager.cleanup_legacy_sessions()
    assert manager.store.load(record.session_id) is not None


def test_context_export_preserves_persisted_prompt_after_worker_release(manager, tmp_path, capsys):
    import json

    cli = ManagedCLI(manager, tmp_path)
    record = manager.store.load(cli.session_id)
    record.runtime_history = [{"role": "user", "content": "compressed history"}]
    record.metadata["runtime_context"] = {"system_prompt": "project rules and agent identity",
                                          "available_tools": 12, "role": "default"}
    manager.store.save(record)
    cli.command("context")
    data = json.loads(capsys.readouterr().out)
    assert data["system_prompt"] == "project rules and agent identity"
    assert data["available_tools"] == 12
    assert data["history"] == record.runtime_history
    cli.command("save")
    saved = json.loads((tmp_path / "agent_context.json").read_text(encoding="utf-8"))
    assert saved == data
