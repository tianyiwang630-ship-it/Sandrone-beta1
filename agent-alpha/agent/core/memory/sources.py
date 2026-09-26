"""Select completed human turns and expose bounded, source-labelled log pages."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent.core.realtime_log import iter_log_records
from agent.core.session_store import SessionKind, SessionStore


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def memory_records(path: Path):
    """Expand only useful records; never reconstruct repeated model input history."""
    values = {}

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$log_ref"}:
                return values[value["$log_ref"]]
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    for record in iter_log_records(path):
        if record.get("type") == "log_value":
            values[record["value_id"]] = record["value"]
        elif record.get("type") != "llm_input":
            yield expand(record)


def available_turns(data_root: Path, *, start: str | None = None,
                    end: str | None = None) -> list[dict]:
    root = Path(data_root).resolve()
    sessions = SessionStore(root / "session-log" / "sessions")
    start_at = parse_time(start) if start else None
    end_at = parse_time(end) if end else None
    turns = []
    for session in sessions.list_recent(limit=None):
        if session.kind != SessionKind.INTERACTIVE:
            continue
        path = root / "session-log" / "logs" / f"{session.session_id}.jsonl"
        if not path.is_file():
            continue
        pending = {}
        try:
            for record in memory_records(path):
                request_id = record.get("request_id")
                entry = record.get("entry")
                if request_id and isinstance(entry, dict) and entry.get("role") == "user":
                    if entry.get("source_agent_id") or entry.get("_sender_id"):
                        continue
                    pending.setdefault(request_id, {"id": f"{session.session_id}:{request_id}",
                                                    "session_id": session.session_id, "request_id": request_id,
                                                    "started_at": record.get("ts"),
                                                    "content": str(entry.get("content") or "")[:240]})
                if record.get("type") == "run_finished" and request_id in pending:
                    event = record.get("event") or {}
                    if not event.get("interrupted") and not event.get("recoverable"):
                        turn = pending.pop(request_id)
                        try:
                            timestamp = parse_time(turn["started_at"])
                        except (TypeError, ValueError):
                            continue
                        if (start_at is None or timestamp >= start_at) and (end_at is None or timestamp < end_at):
                            turns.append(turn)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(turns, key=lambda item: (item["started_at"], item["id"]))


def read_turn(data_root: Path, turn: dict, *, offset: int = 0, limit: int = 12000) -> dict:
    if offset < 0 or not 1 <= limit <= 20000:
        raise ValueError("Invalid log page")
    path = Path(data_root).resolve() / "session-log" / "logs" / f"{turn['session_id']}.jsonl"
    if not path.is_file():
        return {"content": "", "missing": True, "next_offset": None}
    parts = []
    position = 0
    try:
        for record in memory_records(path):
            if record.get("request_id") != turn["request_id"]:
                continue
            entry = record.get("entry")
            if isinstance(entry, dict) and entry.get("role") in {"user", "assistant", "tool"}:
                line = f"[{record.get('ts')}] {entry['role']}: {entry.get('content') or ''}\n"
            elif record.get("type") in {"run_finished", "run_failed", "llm_request_failed"}:
                line = f"[{record.get('ts')}] {record['type']}: {record.get('event') or {}}\n"
            else:
                continue
            end = position + len(line)
            if end > offset and position < offset + limit:
                parts.append(line[max(0, offset - position):max(0, min(len(line), offset + limit - position))])
            position = end
    except (OSError, ValueError, KeyError):
        return {"content": "", "missing": True, "next_offset": None}
    page = "".join(parts)
    next_offset = offset + len(page) if offset + len(page) < position else None
    return {"content": page, "missing": False, "next_offset": next_offset,
            "source": turn["id"], "total_length": position}
