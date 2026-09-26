from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.server import app as app_module
from agent.server.routes import runtime as runtime_route


def test_fastapi_lifespan_shuts_down_browser_harness(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_module,
        "shutdown_browser_harness_runtime",
        lambda project_root: calls.append(project_root) or {"success": True},
    )

    async def run_lifespan():
        async with app_module.lifespan(app_module.app):
            assert calls == []

    asyncio.run(run_lifespan())

    assert calls == [app_module.PROJECT_ROOT]


def test_runtime_browser_delete_reuses_shared_shutdown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        runtime_route,
        "shutdown_browser_harness_runtime",
        lambda project_root: calls.append(project_root) or {"success": True, "browser_close": {"success": True}},
    )

    test_app = FastAPI()
    test_app.include_router(runtime_route.router)
    with TestClient(test_app) as client:
        response = client.delete("/api/runtime/browser")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == [runtime_route.PROJECT_ROOT]


def test_browser_maintenance_starts_after_ui_requests_it(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(app_module.agent_manager, "release_all", lambda: None)
    monkeypatch.setattr(app_module, "shutdown_browser_harness_runtime", lambda _root: {"success": True})
    test_app = FastAPI(lifespan=app_module.lifespan)
    test_app.include_router(runtime_route.router)
    with TestClient(test_app) as client:
        maintenance = test_app.state.browser_maintenance
        assert maintenance._thread is None
        assert client.post("/api/runtime/browser/maintenance/start").json() == {"ok": True}
        first_thread = maintenance._thread
        assert first_thread is not None
        assert client.post("/api/runtime/browser/maintenance/start").status_code == 200
        assert maintenance._thread is first_thread
