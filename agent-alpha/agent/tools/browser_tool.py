from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict

from agent.tools.base_tool import BaseTool
from agent.tools.browser_manager import get_browser_manager


class _BrowserTool(BaseTool):
    def __init__(self, project_root: Path | None = None):
        self.project_root = Path(project_root) if project_root else None

    @property
    def manager(self):
        return get_browser_manager(self.project_root)

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.manager.set_interrupt_event(interrupt_event)


class BrowserNavigateTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_navigate"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Open a URL in a local headless agent-browser session. "
                    "Uses a temporary copy of the selected agent-alpha browser profile and returns a page snapshot."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open."},
                        "profile": {
                            "type": "string",
                            "description": "Persistent agent-alpha browser profile to copy for this headless run. Defaults to 'default'.",
                            "default": "default",
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Optional existing browser session id. Omit to create a new headless session.",
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.start_headless(
            url=kwargs.get("url", ""),
            profile=kwargs.get("profile", "default"),
            session_id=kwargs.get("session_id"),
        )


class BrowserSnapshotTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_snapshot"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Get the current browser page snapshot with element refs for follow-up clicks and typing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "full": {"type": "boolean", "description": "Return full snapshot instead of interactive compact snapshot.", "default": False},
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        args = ["snapshot"] if kwargs.get("full", False) else ["snapshot", "-i"]
        return self.manager.run_current(args, session_id=kwargs.get("session_id"))


class BrowserClickTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_click"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Click an element ref from browser_snapshot, for example '@e3'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element ref, for example '@e3'."},
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": ["ref"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        ref = kwargs.get("ref", "")
        if ref and not ref.startswith("@"):
            ref = f"@{ref}"
        return self.manager.run_current(["click", ref], session_id=kwargs.get("session_id"))


class BrowserTypeTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_type"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Fill text into an element ref from browser_snapshot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "Element ref, for example '@e2'."},
                        "text": {"type": "string", "description": "Text to fill."},
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": ["ref", "text"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        ref = kwargs.get("ref", "")
        if ref and not ref.startswith("@"):
            ref = f"@{ref}"
        return self.manager.run_current(["fill", ref, kwargs.get("text", "")], session_id=kwargs.get("session_id"))


class BrowserScrollTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_scroll"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Scroll the current page up, down, left, or right.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "Scroll direction."},
                        "pixels": {"type": "integer", "description": "Pixels to scroll. Defaults to 500.", "default": 500},
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": ["direction"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        pixels = int(kwargs.get("pixels", 500) or 500)
        return self.manager.run_current(
            ["scroll", kwargs.get("direction", "down"), str(pixels)],
            session_id=kwargs.get("session_id"),
        )


class BrowserPressTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_press"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Press a keyboard key such as Enter, Tab, Escape, or Control+a.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Key to press."},
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": ["key"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.run_current(["press", kwargs.get("key", "")], session_id=kwargs.get("session_id"))


class BrowserCloseTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_close"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Close the active browser session. Headed profile directories persist automatically; headless temporary profiles are cleaned up."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                        "save_profile": {
                            "type": "boolean",
                            "description": "Compatibility flag. Headed profile directories persist automatically.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.close(session_id=kwargs.get("session_id"), save_profile=kwargs.get("save_profile"))


class ProfileListTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "profile_list"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "List persistent agent-alpha browser profiles.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def execute(self, **kwargs) -> Any:
        return {"success": True, "profiles": self.manager.list_profiles()}


class ProfileCreateTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "profile_create"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Create a persistent agent-alpha browser profile backed by a Chrome user-data directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Profile name, for example 'default', 'work', or 'job-search'."},
                        "description": {"type": "string", "description": "Optional human-readable note."},
                    },
                    "required": ["name"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        try:
            profile = self.manager.ensure_profile(kwargs.get("name", ""), kwargs.get("description", ""))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "profile": profile}


class ProfileLoginHeadedTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "profile_login_headed"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Open a headed agent-browser session for manual login. "
                    "The selected profile's Chrome user-data directory persists login state automatically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string", "description": "Profile to update. Defaults to 'default'.", "default": "default"},
                        "url": {"type": "string", "description": "Login URL to open. Defaults to about:blank.", "default": "about:blank"},
                    },
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.start_headed_login(
            profile=kwargs.get("profile", "default"),
            url=kwargs.get("url", "about:blank"),
        )


class BrowserConnectCdpTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_connect_cdp"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Connect browser tools to a user-managed Chrome/Edge instance via CDP port or WebSocket URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cdp_url": {"type": "string", "description": "CDP port, HTTP URL, or WebSocket URL, for example '9222'."}
                    },
                    "required": ["cdp_url"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.connect_cdp(kwargs.get("cdp_url", ""))


class BrowserDisconnectCdpTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_disconnect_cdp"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Forget the active external CDP browser session without closing the user's browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"session_id": {"type": "string", "description": "Optional CDP session id."}},
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        session_id = kwargs.get("session_id") or self.manager.current_session_id
        session = self.manager.active_sessions.get(session_id or "")
        if not session or session.mode != "external-cdp":
            return {"success": False, "error": "No active external CDP session to disconnect."}
        self.manager.active_sessions.pop(session.session_id, None)
        if self.manager.current_session_id == session.session_id:
            self.manager.current_session_id = next(iter(self.manager.active_sessions), None)
        return {"success": True, "session_id": session.session_id, "disconnected": True}


class BrowserCdpStatusTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_cdp_status"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Show active browser sessions, including external CDP sessions.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.status()
