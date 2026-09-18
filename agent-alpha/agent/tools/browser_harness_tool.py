from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.base_tool import BaseTool
from agent.tools.browser_harness_runtime import get_browser_harness_runtime


class BrowserHarnessTool(BaseTool):
    """Execute trusted Browser Harness Python through its official CLI."""

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
        self.runtime = get_browser_harness_runtime(self.project_root)
        self.interrupt_event = None

    @property
    def name(self) -> str:
        return "browser_harness_exec"

    def set_interrupt_event(self, interrupt_event) -> None:
        self.interrupt_event = interrupt_event

    def get_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Execute Python code with Browser Harness helpers pre-imported in Alpha's shared, "
                    "isolated browser, or prepare that browser for manual login. Load the browser-harness "
                    "skill before first use. The code is sent "
                    "through UTF-8 stdin; do not use shell heredocs or invoke browser-harness through bash."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Required in cdp mode and omitted in manual mode. Python using Browser Harness helpers such as new_tab, page_info, cdp, and js.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["manual", "cdp"],
                            "description": "manual opens the isolated browser for human sign-in; cdp enables automation. Omit to keep normal CDP behavior unless manual login is already pending.",
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Execution and lock-wait timeout. Defaults to 60 seconds; maximum 300 seconds.",
                            "minimum": 1,
                            "maximum": 300,
                        },
                    },
                },
            },
        }

    def execute(self, **kwargs) -> dict[str, Any]:
        return self.runtime.execute(
            code=kwargs.get("code"),
            mode=kwargs.get("mode"),
            timeout_seconds=kwargs.get("timeout_seconds", 60),
            interrupt_event=self.interrupt_event,
        )
