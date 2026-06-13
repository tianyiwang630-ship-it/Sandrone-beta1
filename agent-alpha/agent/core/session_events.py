"""
Realtime session event logging helpers.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any


MAX_EVENT_TOOL_RESULT_LINES = 200
DOCUMENT_READ_TOOL_RESULT_CHARS = 50000
DOCUMENT_READ_TOOL_NAMES = {
    "read",
    "read_file",
    "filesystem_read",
    "load_skill",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def truncate_tool_result(
    content: str,
    *,
    max_chars: int,
    max_lines: int = MAX_EVENT_TOOL_RESULT_LINES,
    tool_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized = str(content).replace("\r\n", "\n")
    original_char_count = len(normalized)
    original_line_count = normalized.count("\n") + 1 if normalized else 0
    effective_max_chars = _effective_max_chars(max_chars, tool_name)

    truncated = False
    truncated_text = normalized

    if original_line_count > max_lines:
        truncated_text = "\n".join(normalized.split("\n")[:max_lines])
        truncated = True

    if len(truncated_text) > effective_max_chars:
        truncated_text = truncated_text[:effective_max_chars]
        truncated = True

    if truncated:
        retained_char_count = len(truncated_text)
        retained_line_count = truncated_text.count("\n") + 1 if truncated_text else 0
        truncated_text += (
            "\n\n"
            f"[工具输出已截断：原始 {original_line_count} 行，原始 {original_char_count} 字符；"
            f"保留 {retained_line_count} 行，{retained_char_count} 字符；"
            f"截断位置：第 {retained_char_count} 字符附近。"
            "请不要假设后续内容已读取。]"
        )

    metadata: dict[str, Any] = {}
    if truncated:
        metadata = {
            "truncated": True,
            "original_line_count": original_line_count,
            "original_char_count": original_char_count,
        }
    return truncated_text, metadata


def _effective_max_chars(max_chars: int, tool_name: str | None) -> int:
    if not tool_name:
        return max_chars

    normalized_name = tool_name.lower()
    if (
        normalized_name in DOCUMENT_READ_TOOL_NAMES
        or normalized_name.endswith("_read")
        or normalized_name.endswith(".read")
    ):
        return max(max_chars, DOCUMENT_READ_TOOL_RESULT_CHARS)
    return max_chars


class SessionEventWriter:
    """Append realtime history entries for one CLI session."""

    def __init__(self, events_dir: Path, session_id: str):
        self.events_dir = Path(events_dir).resolve()
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.path = self.events_dir / f"{session_id}.jsonl"
        self._next_seq = self._load_next_seq()

    def _load_next_seq(self) -> int:
        if not self.path.exists():
            return 1

        text = self.path.read_text(encoding="utf-8")
        decoder = json.JSONDecoder()
        index = 0
        seq = 1

        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break

            _, next_index = decoder.raw_decode(text, index)
            seq += 1
            index = next_index

        return seq

    def write(self, entry: dict[str, Any], **metadata: Any) -> None:
        payload = {
            "ts": _now_iso(),
            "seq": self._next_seq,
            "session_id": self.session_id,
            "entry": copy.deepcopy(entry),
        }
        payload.update({key: value for key, value in metadata.items() if value is not None})

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n\n")

        self._next_seq += 1

    def write_event(self, event_type: str, event: dict[str, Any], **metadata: Any) -> None:
        payload = {
            "ts": _now_iso(),
            "seq": self._next_seq,
            "session_id": self.session_id,
            "type": event_type,
            "event": copy.deepcopy(event),
        }
        payload.update({key: value for key, value in metadata.items() if value is not None})

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n\n")

        self._next_seq += 1
