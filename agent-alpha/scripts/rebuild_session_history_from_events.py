from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


MESSAGE_ROLES = {"user", "assistant", "tool"}


def read_event_objects(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        event, next_index = decoder.raw_decode(text, index)
        if isinstance(event, dict):
            events.append(event)
        index = next_index
    return events


def history_from_events(path: Path) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for event in read_event_objects(path):
        entry = event.get("entry")
        if not isinstance(entry, dict):
            continue
        if entry.get("role") not in MESSAGE_ROLES:
            continue
        history.append(dict(entry))
    return history


def rebuild_session(project_root: Path, session_id: str) -> None:
    session_path = project_root / "session-log" / "sessions" / f"{session_id}.json"
    events_path = project_root / "session-log" / "events" / f"{session_id}.jsonl"
    if not session_path.exists():
        raise FileNotFoundError(f"Session snapshot not found: {session_path}")
    if not events_path.exists():
        raise FileNotFoundError(f"Session events not found: {events_path}")

    record = json.loads(session_path.read_text(encoding="utf-8"))
    rebuilt_history = history_from_events(events_path)
    if not rebuilt_history:
        raise ValueError(f"No message entries found in {events_path}")

    old_history = list(record.get("history", []))
    old_runtime_history = list(record.get("runtime_history") or old_history)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_dir = project_root / "temp" / "session-history-repair"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{session_id}.{timestamp}.json"
    backup_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    record["history"] = rebuilt_history
    record["runtime_history"] = old_runtime_history
    record["updated_at"] = datetime.now().isoformat(timespec="seconds")

    tmp_path = session_path.with_name(f"{session_path.name}.tmp")
    tmp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, session_path)

    print(f"Rebuilt session: {session_id}")
    print(f"History messages: {len(old_history)} -> {len(rebuilt_history)}")
    print(f"Runtime history messages: {len(old_runtime_history)}")
    print(f"Backup: {backup_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild SessionRecord.history from session-log/events entries.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="agent-alpha project root",
    )
    args = parser.parse_args()
    rebuild_session(args.project_root.resolve(), args.session_id)


if __name__ == "__main__":
    main()
