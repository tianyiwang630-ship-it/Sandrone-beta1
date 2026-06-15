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
                    "Uses a temporary copy of the selected agent-alpha browser profile and returns a navigation summary. "
                    "Use this as the headless fallback when headed or CDP interactive mode is occupied by another alpha."
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
                        "save_full": {
                            "type": "boolean",
                            "description": "Save full snapshot to temp/browser_snapshots and return only file metadata. Defaults to false.",
                            "default": False,
                        },
                        "full": {
                            "type": "boolean",
                            "description": "Compatibility alias for save_full. Prefer save_full for new calls.",
                            "default": False,
                        },
                        "session_id": {"type": "string", "description": "Optional browser session id."},
                    },
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        save_full = bool(kwargs.get("save_full", kwargs.get("full", False)))
        return self.manager.snapshot_current(save_full=save_full, session_id=kwargs.get("session_id"))


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
                    "Close a local headless browser session and clean its temporary profile. "
                    "This tool refuses to close headed login windows or external CDP browsers."
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
                    "The selected profile's Chrome user-data directory persists login state automatically. "
                    "Do not close it with browser_close. If another alpha owns headed or CDP interactive mode, "
                    "do not clear that lock; use browser_navigate for headless work."
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


class ProfileSaveHeadedTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "profile_save_headed"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Save the current headed login state for this same alpha instance without closing the visible browser."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string", "description": "Profile to save. Defaults to 'default'.", "default": "default"}
                    },
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.profile_save_headed(profile=kwargs.get("profile", "default"))


class ProfileCloseHeadedTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "profile_close_headed"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Close the visible headed login browser only when the user explicitly asked to close it. "
                    "Never call this just to unlock a profile."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string", "description": "Profile to close. Defaults to 'default'.", "default": "default"},
                        "user_confirmed_close_visible_browser": {
                            "type": "boolean",
                            "description": "Must be true only when the user explicitly asked to close the visible headed browser.",
                        },
                    },
                    "required": ["user_confirmed_close_visible_browser"],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.profile_close_headed(
            profile=kwargs.get("profile", "default"),
            user_confirmed_close_visible_browser=bool(kwargs.get("user_confirmed_close_visible_browser", False)),
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
                "description": (
                    "Connect browser tools to a user-managed Chrome/Edge instance via CDP port or WebSocket URL. "
                    "Only one alpha can own CDP at a time; if another alpha owns the global interactive lock, do not reconnect."
                ),
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
                "description": (
                    "Forget this alpha's active external CDP browser session without closing the user's browser. "
                    "This must not release CDP sessions owned by another alpha."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"session_id": {"type": "string", "description": "Optional CDP session id."}},
                    "required": [],
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.disconnect_cdp(kwargs.get("session_id"))


class BrowserCdpStatusTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_cdp_status"

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Show this alpha's current browser sessions plus the global interactive lock. "
                    "The global interactive lock may belong to another alpha while this current alpha has no local sessions."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.manager.status()
