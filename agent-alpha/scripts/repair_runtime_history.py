from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.core.message_pipeline import prepare_runtime_history  # noqa: E402
from agent.core.session_events import SessionEventWriter  # noqa: E402
from agent.core.session_store import SessionStore  # noqa: E402


def repair_runtime_history(project_root: Path, session_id: str, *, apply: bool) -> dict:
    session_root = project_root / "session-log"
    store = SessionStore(session_root / "sessions")
    record = store.load(session_id)
    if record is None:
        raise FileNotFoundError(f"Session snapshot not found: {session_id}")

    original_history_count = len(record.history)
    original_runtime = [dict(message) for message in (record.runtime_history or record.history)]
    result = prepare_runtime_history(original_runtime, request_id=f"repair_{session_id}")
    report = {
        "session_id": session_id,
        "history_count": original_history_count,
        "runtime_before": len(original_runtime),
        "runtime_after": len(result.history),
        "repairs": result.repairs,
        "changed": result.history != original_runtime,
        "applied": False,
    }
    if not apply or not report["changed"]:
        return report

    session_path = session_root / "sessions" / f"{session_id}.json"
    timestamp = datetime.now().isoformat(timespec="seconds")
    backup_dir = project_root.parent / "temp" / "session-runtime-repair"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{session_id}.{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    shutil.copy2(session_path, backup_path)

    last_user = next(
        (message.get("content") for message in reversed(result.history) if message.get("role") == "user"),
        None,
    )
    event = {
        "type": "runtime_history_repaired",
        "timestamp": timestamp,
        "request_id": f"repair_{session_id}",
        "repairs": result.repairs,
        "before_message_count": len(original_runtime),
        "after_message_count": len(result.history),
        "history_unchanged": len(record.history) == original_history_count,
    }
    record.runtime_history = result.history
    record.runtime_checkpoint = {
        "request_id": f"repair_{session_id}",
        "operation": "chat",
        "status": "recoverable",
        "phase": "runtime_history_repaired",
        "pending_user_message": last_user,
        "updated_at": timestamp,
    }
    record.events.append(event)
    record.updated_at = timestamp
    SessionEventWriter(session_root / "events", session_id).write_event(event["type"], event)
    store.save(record)

    report["applied"] = True
    report["backup"] = str(backup_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair invalid runtime history without changing display history.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--apply", action="store_true", help="Apply the repair; otherwise only print a dry-run report.")
    args = parser.parse_args()
    report = repair_runtime_history(args.project_root.resolve(), args.session_id, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
