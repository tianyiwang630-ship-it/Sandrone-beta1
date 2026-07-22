from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.server.agent_manager import AgentManager
from agent.server.routes import chat as chat_route
from agent.server.web_permissions import (
    PermissionConflictError,
    PermissionNotFoundError,
    WebPermissionBroker,
)


PROMPT = {
    "tool": "bash",
    "risk_level": "medium",
    "reason": "Workspace package installation requires approval.",
    "summary_label": "命令",
    "summary": "npm install docx",
}


def wait_for_pending(broker: WebPermissionBroker, request_id: str) -> dict:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        pending = broker.pending_for_request(request_id)
        if pending:
            return pending
        time.sleep(0.005)
    raise AssertionError("permission request did not become pending")


def run_request(broker: WebPermissionBroker, results: list, *, request_id: str = "req-1") -> threading.Thread:
    thread = threading.Thread(
        target=lambda: results.append(broker.request(request_id, "sess-1", PROMPT)),
        daemon=True,
    )
    thread.start()
    return thread


def test_web_permission_broker_allows_once_and_rejects_duplicate_decision():
    broker = WebPermissionBroker(timeout_seconds=1)
    results = []
    thread = run_request(broker, results)
    pending = wait_for_pending(broker, "req-1")

    broker.resolve(pending["permission_id"], "allow_once")
    thread.join(timeout=1)

    assert results == [True]
    assert broker.pending_for_request("req-1") is None
    with pytest.raises(PermissionConflictError):
        broker.resolve(pending["permission_id"], "deny")


def test_web_permission_broker_returns_retry_instruction():
    broker = WebPermissionBroker(timeout_seconds=1)
    results = []
    thread = run_request(broker, results)
    pending = wait_for_pending(broker, "req-1")

    broker.resolve(pending["permission_id"], "retry_with_context", "请改用全局安装")
    thread.join(timeout=1)

    assert results == [{"retry_with_context": "请改用全局安装"}]


def test_web_permission_broker_times_out_with_distinct_denial_reason():
    broker = WebPermissionBroker(timeout_seconds=0.02)

    result = broker.request("req-timeout", "sess-1", PROMPT)

    assert result == {"permission_denied_reason": "Permission request timed out"}
    assert broker.pending_for_request("req-timeout") is None


def test_web_permission_broker_cancels_session_and_rejects_unknown_request():
    broker = WebPermissionBroker(timeout_seconds=1)
    results = []
    thread = run_request(broker, results)
    wait_for_pending(broker, "req-1")

    broker.cancel_session("sess-1")
    thread.join(timeout=1)

    assert results == [{"permission_denied_reason": "Permission request cancelled"}]
    with pytest.raises(PermissionNotFoundError):
        broker.resolve("missing", "deny")


def test_agent_manager_status_exposes_pending_permission_and_resolves_it():
    broker = WebPermissionBroker(timeout_seconds=1)
    manager = AgentManager.__new__(AgentManager)
    manager._runs = {
        "req-1": {
            "request_id": "req-1",
            "session_id": "sess-1",
            "status": "running",
        }
    }
    manager._lock = threading.RLock()
    manager._web_permission_broker = broker
    results = []
    thread = run_request(broker, results)
    pending = wait_for_pending(broker, "req-1")

    status = manager.get_run("req-1")
    manager.resolve_permission(pending["permission_id"], "deny")
    thread.join(timeout=1)

    assert status["pending_permission"]["summary"] == "npm install docx"
    assert results == [False]


def test_permission_decision_endpoint_maps_conflicts_and_validates_retry(monkeypatch):
    class FakeManager:
        def __init__(self):
            self.calls = []

        def resolve_permission(self, permission_id, decision, instruction=None):
            self.calls.append((permission_id, decision, instruction))
            if permission_id == "stale":
                raise PermissionConflictError("Permission request is no longer pending")

    fake = FakeManager()
    monkeypatch.setattr(chat_route, "agent_manager", fake)
    app = FastAPI()
    app.include_router(chat_route.router)
    client = TestClient(app)

    allowed = client.post(
        "/api/chat/permissions/perm-1/decision",
        json={"decision": "allow_once"},
    )
    blank_retry = client.post(
        "/api/chat/permissions/perm-2/decision",
        json={"decision": "retry_with_context", "instruction": "   "},
    )
    stale = client.post(
        "/api/chat/permissions/stale/decision",
        json={"decision": "deny"},
    )

    assert allowed.status_code == 200
    assert allowed.json() == {"ok": True}
    assert fake.calls[0] == ("perm-1", "allow_once", None)
    assert blank_retry.status_code == 422
    assert stale.status_code == 409


def test_agent_manager_release_all_cancels_every_pending_permission():
    broker = WebPermissionBroker(timeout_seconds=1)
    manager = AgentManager.__new__(AgentManager)
    manager._agents = {"sess-1": object()}
    manager._lock = threading.RLock()
    manager._web_permission_broker = broker
    results = []
    thread = run_request(broker, results)
    wait_for_pending(broker, "req-1")

    manager.release_all()
    thread.join(timeout=1)

    assert results == [{"permission_denied_reason": "Permission request cancelled"}]
    assert manager._agents == {}


def test_fastapi_status_and_decision_complete_pending_permission_flow(monkeypatch):
    broker = WebPermissionBroker(timeout_seconds=1)
    manager = AgentManager.__new__(AgentManager)
    manager._runs = {
        "req-1": {
            "request_id": "req-1",
            "session_id": "sess-1",
            "status": "running",
            "operation": "chat",
            "started_after_seq": 0,
            "response": None,
            "error": None,
            "tool_calls_count": 0,
            "created_at": "2026-07-21T10:00:00",
            "updated_at": "2026-07-21T10:00:00",
        }
    }
    manager._lock = threading.RLock()
    manager._web_permission_broker = broker
    monkeypatch.setattr(chat_route, "agent_manager", manager)
    app = FastAPI()
    app.include_router(chat_route.router)
    client = TestClient(app)
    results = []
    thread = run_request(broker, results)
    wait_for_pending(broker, "req-1")

    status = client.get("/api/chat/status/req-1")
    permission_id = status.json()["pending_permission"]["permission_id"]
    decision = client.post(
        f"/api/chat/permissions/{permission_id}/decision",
        json={"decision": "allow_once"},
    )
    thread.join(timeout=1)

    assert status.status_code == 200
    assert status.json()["pending_permission"]["summary"] == "npm install docx"
    assert decision.status_code == 200
    assert results == [True]
