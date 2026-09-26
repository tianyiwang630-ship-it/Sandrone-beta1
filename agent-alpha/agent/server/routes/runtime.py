from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from agent.core.agent_runtime import PROJECT_ROOT
from agent.tools.browser_harness_runtime import shutdown_browser_harness_runtime
from agent.tools.browser_harness_maintenance import read_browser_maintenance_notice
from agent.server.deps import agent_manager


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.post("/browser/maintenance/start")
def start_browser_maintenance(request: Request) -> dict:
    maintenance = getattr(request.app.state, "browser_maintenance", None)
    if maintenance is not None:
        maintenance.start()
    return {"ok": True}


@router.get("/browser/maintenance")
def browser_maintenance() -> dict:
    return read_browser_maintenance_notice(PROJECT_ROOT)


@router.delete("/executions")
async def shutdown_executions() -> dict:
    """Stop admission and all owned execution groups before desktop exit."""
    await asyncio.to_thread(agent_manager.release_all)
    return {"success": True}


@router.delete("/browser")
async def shutdown_browser() -> dict:
    """Close Alpha's browser channel without stopping the shared Web backend."""
    return await asyncio.to_thread(shutdown_browser_harness_runtime, PROJECT_ROOT)
