from __future__ import annotations

from agent.core.permission_manager import PermissionManager


def test_permission_manager_delegates_web_prompt_without_using_terminal_input():
    captured = []
    manager = PermissionManager()
    manager.set_approval_handler(lambda prompt: captured.append(prompt) or True)

    result = manager.ask_user(
        "bash",
        {"command": "npm install docx", "content": "must-not-leak"},
        "Installing a workspace dependency requires approval.",
    )

    assert result is True
    assert captured == [
        {
            "tool": "bash",
            "risk_level": "medium",
            "reason": "Installing a workspace dependency requires approval.",
            "summary_label": "命令",
            "summary": "npm install docx",
        }
    ]


def test_permission_manager_can_return_to_cli_prompt_after_web_run():
    manager = PermissionManager()
    manager.set_approval_handler(lambda _prompt: True)

    manager.set_approval_handler(None)

    assert manager.approval_handler is None
