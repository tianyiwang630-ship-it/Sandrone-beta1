from __future__ import annotations

from agent.server.agent_manager import AgentManager
from agent.server.stores.app_state import AppStateStore


state_store = AppStateStore()
agent_manager = AgentManager()

