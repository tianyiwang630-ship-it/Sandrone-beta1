"""Append-only realtime runtime logs."""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.session_events import truncate_text


MAX_LOG_TOOL_RESULT_CHARS = 128_000
MAX_LOG_TOOL_RESULT_LINES = 2_000


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RealtimeLogWriter:
    """Write one compact JSON record per line so crashes preserve prior records."""

    def __init__(self, logs_dir: Path, session_id: str):
        self.logs_dir = Path(logs_dir).resolve()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.path = self.logs_dir / f"{session_id}.jsonl"
        self._lock = threading.RLock()

    def write_session_header(self, payload: dict[str, Any]) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            return
        self.write_event("session_started", payload)

    def write_entry(self, entry: dict[str, Any], *, request_id: str, raw_tool_result: bool = False) -> None:
        logged_entry = copy.deepcopy(entry)
        metadata: dict[str, Any] = {}
        if raw_tool_result and logged_entry.get("role") == "tool":
            content, metadata = truncate_text(
                str(logged_entry.get("content") or ""),
                max_chars=MAX_LOG_TOOL_RESULT_CHARS,
                max_lines=MAX_LOG_TOOL_RESULT_LINES,
            )
            logged_entry["content"] = content
        self._append(
            {
                "ts": _now_iso(),
                "session_id": self.session_id,
                "request_id": request_id,
                "entry": logged_entry,
                **metadata,
            }
        )

    def write_event(self, event_type: str, event: dict[str, Any], *, request_id: str | None = None) -> None:
        payload = {
            "ts": _now_iso(),
            "session_id": self.session_id,
            "type": event_type,
            "event": copy.deepcopy(event),
        }
        if request_id:
            payload["request_id"] = request_id
        self._append(payload)

    def _append(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()

