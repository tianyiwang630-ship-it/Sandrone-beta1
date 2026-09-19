import asyncio
from concurrent.futures import TimeoutError
import threading

import pytest

from agent.tools.mcp_manager import MCPManager


def test_timeout_cancels_background_coroutine_not_only_outer_wait():
    manager = MCPManager.__new__(MCPManager)
    manager.interrupt_event = None
    manager._loop = asyncio.new_event_loop()
    thread = threading.Thread(target=manager._loop.run_forever, daemon=True)
    thread.start()
    cancelled = threading.Event()

    async def operation():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    try:
        with pytest.raises(TimeoutError):
            manager._run_coro(operation(), timeout=0.05)
        assert cancelled.wait(1)
    finally:
        manager._loop.call_soon_threadsafe(manager._loop.stop)
        thread.join(timeout=1)
        manager._loop.close()
