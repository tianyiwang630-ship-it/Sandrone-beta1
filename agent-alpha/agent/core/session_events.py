"""
Realtime session event logging helpers.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


MAX_EVENT_TOOL_RESULT_LINES = 200
MAX_EVENT_TOOL_ARGUMENT_CHARS = 2_000
MAX_EVENT_TOOL_ARGUMENT_LINES = 20
MAX_EVENT_TOOL_RESULT_CHARS = 4_000
MAX_EVENT_TOOL_RESULT_LINES = 60
DOCUMENT_READ_TOOL_RESULT_CHARS = 50000
BROWSER_TOOL_RESULT_CHARS = {
    "browser_navigate": 5000,
    "browser_snapshot": 10000,
}
DOCUMENT_READ_TOOL_NAMES = {
    "read",
    "read_file",
    "filesystem_read",
    "load_skill",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def truncate_text(
    content: str,
    *,
    max_chars: int,
    max_lines: int,
) -> tuple[str, dict[str, Any]]:
    normalized = str(content).replace("\r\n", "\n")
    original_char_count = len(normalized)
    original_line_count = normalized.count("\n") + 1 if normalized else 0

    truncated = False
    truncated_text = normalized

    if original_line_count > max_lines:
        truncated_text = "\n".join(normalized.split("\n")[:max_lines])
        truncated = True

    if len(truncated_text) > max_chars:
        truncated_text = truncated_text[:max_chars]
        truncated = True

    if truncated:
        content_line_limit = max(0, max_lines - 1)
        if content_line_limit == 0:
            truncated_text = ""
        else:
            truncated_text = "\n".join(truncated_text.split("\n")[:content_line_limit])
        notice = (
            f"[工具输出已截断：原始 {original_line_count} 行，原始 {original_char_count} 字符；"
            "请根据截断元数据确认保留范围，不要假设后续内容已读取。]"
        )
        separator = "\n" if truncated_text else ""
        available = max(0, max_chars - len(separator) - len(notice))
        truncated_text = truncated_text[:available]
        separator = "\n" if truncated_text else ""
        truncated_text = f"{truncated_text}{separator}{notice}"[:max_chars]

    metadata: dict[str, Any] = {}
    if truncated:
        metadata = {
            "truncated": True,
            "original_line_count": original_line_count,
            "original_char_count": original_char_count,
            "retained_line_count": truncated_text.count("\n") + 1 if truncated_text else 0,
            "retained_char_count": len(truncated_text),
        }
    return truncated_text, metadata


def truncate_tool_result(
    content: str,
    *,
    max_chars: int,
    max_lines: int = MAX_EVENT_TOOL_RESULT_LINES,
    tool_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    return truncate_text(
        content,
        max_chars=_effective_max_chars(max_chars, tool_name),
        max_lines=max_lines,
    )


def _effective_max_chars(max_chars: int, tool_name: str | None) -> int:
    if not tool_name:
        return max_chars

    normalized_name = tool_name.lower()
    if normalized_name in BROWSER_TOOL_RESULT_CHARS:
        return min(max_chars, BROWSER_TOOL_RESULT_CHARS[normalized_name])
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
        max_seq = 0

        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break

            try:
                record, next_index = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                # A crash can leave the final append incomplete. Earlier records
                # are still valid and should remain available for recovery.
                break
            if isinstance(record, dict):
                max_seq = max(max_seq, int(record.get("seq") or 0))
            index = next_index

        return max_seq + 1

    def write(self, entry: dict[str, Any], **metadata: Any) -> None:
        event_entry, truncation = _slim_event_entry(entry)
        payload = {
            "ts": _now_iso(),
            "seq": self._next_seq,
            "session_id": self.session_id,
            "entry": event_entry,
        }
        payload.update({key: value for key, value in metadata.items() if value is not None})
        if truncation:
            payload["entry_truncation"] = truncation

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n\n")

        self._next_seq += 1

    def compact_completed_request(self, request_id: str) -> int:
        records = read_session_events(self.events_dir, self.session_id)
        retained = [record for record in records if not _is_cleanup_event(record, request_id)]
        removed = len(records) - len(retained)
        if removed:
            _write_event_records_atomic(self.path, retained)
        self._next_seq = max((int(record.get("seq") or 0) for record in retained), default=0) + 1
        return removed

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


def read_session_events(events_dir: Path, session_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
    """Read concatenated JSON event records without assuming one JSON object per line."""
    path = Path(events_dir).resolve() / f"{session_id}.jsonl"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    index = 0
    records: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            record, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            # Keep every complete record even if the process stopped halfway
            # through the final append.
            break
        if isinstance(record, dict) and int(record.get("seq") or 0) > after_seq:
            records.append(record)
    return records


def migrate_event_file(path: Path, *, cleanup_completed: bool) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    records = read_session_events(path.parent, path.stem)
    migrated: list[dict[str, Any]] = []
    changed = False
    for record in records:
        if cleanup_completed and _event_type(record) in {
            "assistant_delta",
            "llm_request_started",
            "llm_request_succeeded",
        }:
            changed = True
            continue
        next_record = copy.deepcopy(record)
        entry = next_record.get("entry")
        if isinstance(entry, dict):
            slimmed, truncation = _slim_event_entry(entry)
            if slimmed != entry:
                changed = True
            next_record["entry"] = slimmed
            if truncation:
                next_record["entry_truncation"] = truncation
        migrated.append(next_record)
    if changed:
        _write_event_records_atomic(path, migrated)
    return changed


def _slim_event_entry(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    slimmed = copy.deepcopy(entry)
    truncation: dict[str, Any] = {}
    if slimmed.get("role") == "tool":
        content, metadata = truncate_text(
            str(slimmed.get("content") or ""),
            max_chars=MAX_EVENT_TOOL_RESULT_CHARS,
            max_lines=MAX_EVENT_TOOL_RESULT_LINES,
        )
        slimmed["content"] = content
        if metadata:
            truncation["tool_result"] = metadata

    tool_calls = slimmed.get("tool_calls")
    if slimmed.get("role") == "assistant" and isinstance(tool_calls, list):
        for index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            arguments = str(function.get("arguments") or "")
            preview, metadata = truncate_text(
                arguments,
                max_chars=MAX_EVENT_TOOL_ARGUMENT_CHARS,
                max_lines=MAX_EVENT_TOOL_ARGUMENT_LINES,
            )
            if not metadata:
                continue
            function["arguments"] = json.dumps(
                {
                    "_event_truncated": True,
                    "preview": preview,
                    "original_char_count": metadata["original_char_count"],
                    "original_line_count": metadata["original_line_count"],
                },
                ensure_ascii=False,
            )
            truncation[f"tool_call_{index}_arguments"] = metadata
    return slimmed, truncation


def _event_type(record: dict[str, Any]) -> str:
    event = record.get("event")
    return str(record.get("type") or (event.get("type") if isinstance(event, dict) else "") or "")


def _event_request_id(record: dict[str, Any]) -> str:
    event = record.get("event")
    return str(record.get("request_id") or (event.get("request_id") if isinstance(event, dict) else "") or "")


def _is_cleanup_event(record: dict[str, Any], request_id: str) -> bool:
    return _event_request_id(record) == request_id and _event_type(record) in {
        "assistant_delta",
        "llm_request_started",
        "llm_request_succeeded",
    }


def _write_event_records_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    payload = "".join(json.dumps(record, ensure_ascii=False, indent=2) + "\n\n" for record in records)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
