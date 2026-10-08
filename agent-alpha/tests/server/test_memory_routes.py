import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.core.memory.service import MemoryService
from agent.core.memory.store import now


def test_memory_routes_use_maintenance_permission_and_expose_retry_results(tmp_path, monkeypatch):
    """Load the router with isolated dependencies, never the user's running data."""
    service = MemoryService(tmp_path)
    deps = ModuleType("agent.server.deps")
    deps.agent_manager = SimpleNamespace(memory=service)
    deps.state_store = SimpleNamespace(get_settings=lambda: {})
    monkeypatch.setitem(sys.modules, "agent.server.deps", deps)
    path = Path(__file__).resolve().parents[2] / "agent/server/routes/memory.py"
    spec = importlib.util.spec_from_file_location("memory_routes_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        assert client.patch("/api/memory/config", json={"enabled": False}).status_code == 200
        assert client.get("/api/memory/documents/user").status_code == 200
        task = {"id": "mem_" + "c" * 32, "created_at": now(), "manual": True, "status": "failed",
                "failed_stage": "organizing", "retryable": False, "retry_after": now(),
                "allowed_at_start": ["user", "memory"], "operations": {}, "proposals": [], "turns": [],
                "results": {}, "prompt": "saved", "organizer_history": [], "reviewer_history": [], "error": "test"}
        service.store.save_task(task)
        assert client.post(f"/api/memory/tasks/{task['id']}/actions", json={"action": "invalid"}).status_code == 422
        response = client.post(f"/api/memory/tasks/{task['id']}/actions", json={"action": "retry"})
        assert response.status_code == 200
        service._thread.join(3)
        result = client.get("/api/memory/tasks/current").json()
        assert result["status"] == "no_change" and result["operation_count"] == 0
        assert result["allowed_at_start"] == ["user", "memory"] and result["results"] == []
        assert client.post(f"/api/memory/tasks/{task['id']}/actions", json={"action": "retry"}).status_code == 422
