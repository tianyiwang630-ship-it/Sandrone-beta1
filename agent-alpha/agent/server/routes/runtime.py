from __future__ import annotations

import asyncio

from fastapi import APIRouter

from agent.core.agent_runtime import PROJECT_ROOT
from agent.tools.browser_harness_runtime import shutdown_browser_harness_runtime


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.delete("/browser")
async def shutdown_browser() -> dict:
    """Close Alpha's browser channel without stopping the shared Web backend."""
    return await asyncio.to_thread(shutdown_browser_harness_runtime, PROJECT_ROOT)
