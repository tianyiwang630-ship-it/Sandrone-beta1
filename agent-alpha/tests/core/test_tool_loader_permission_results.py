from __future__ import annotations

from types import SimpleNamespace

from agent.core.tool_loader import ToolLoader


def test_permission_timeout_does_not_execute_tool():
    executed = []
    loader = ToolLoader.__new__(ToolLoader)
    loader.sandbox_guard = SimpleNamespace(
        check_tool_call=lambda _name, _args: SimpleNamespace(
            decision="ask",
            reason="Approval required",
            guidance=None,
        )
    )
    loader.enable_permissions = True
    loader.permission_manager = SimpleNamespace(
        mode="ask",
        ask_user=lambda _name, _args, _reason: {
            "permission_denied_reason": "Permission request timed out"
        },
    )
    loader.tool_executors = {"bash": lambda **_kwargs: executed.append(True)}

    result = loader.execute_tool("bash", {"command": "npm install docx"})

    assert result["error"] == "Permission request timed out"
    assert executed == []
