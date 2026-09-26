"""Append-only realtime runtime logs."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.session_events import truncate_text


MAX_LOG_TOOL_RESULT_CHARS = 128_000
MAX_LOG_TOOL_RESULT_LINES = 2_000
LOG_VERSION = 3
LOG_RETENTION_DAYS = 7
_BODY_FIELDS = {"content", "reasoning_content", "arguments", "system_prompt", "tools"}


def _encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


def iter_log_records(path: Path, *, strict: bool = False):
    """Read old and new JSONL without loading the complete log into memory."""
    with Path(path).open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Log record must be an object")
            except (ValueError, UnicodeDecodeError):
                if strict:
                    raise
                continue  # A killed worker can leave an unfinished final record.
            yield record


def read_realtime_log(path: Path, *, strict: bool = False):
    """Expand references and input edits for debugging; old logs remain readable."""
    values: dict[int, Any] = {}
    messages: list[dict[str, Any]] = []

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$log_ref"}:
                return copy.deepcopy(values[value["$log_ref"]])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    for record in iter_log_records(path, strict=strict):
        if record.get("log_version") != LOG_VERSION:
            yield record
            continue
        if record.get("type") == "log_value":
            values[record["value_id"]] = record["value"]
            continue
        result = expand({key: value for key, value in record.items() if key != "log_version"})
        if result.get("type") == "llm_input":
            event = result["event"]
            edit = event.pop("messages_delta")
            start, count = edit["start"], edit["delete"]
            if not 0 <= start <= start + count <= len(messages):
                raise ValueError("Invalid log input edit")
            messages[start:start + count] = edit["insert"]
            event["messages"] = copy.deepcopy(messages)
        yield result


def cleanup_expired_logs(logs_dir: Path, *, retention_days: int = LOG_RETENTION_DAYS,
                         now: datetime | None = None, protected_sessions: set[str] | None = None) -> list[Path]:
    """Delete debug logs by file mtime without opening or scanning their contents."""
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    root = Path(logs_dir).resolve()
    cutoff = (now or datetime.now()).timestamp() - retention_days * 24 * 60 * 60
    removed: list[Path] = []
    for path in root.iterdir():
        try:
            if not path.is_file() or path.name == ".gitkeep" or path.suffix not in {".json", ".jsonl", ".tmp"}:
                continue
            if path.stem in (protected_sessions or set()):
                continue
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError:
            pass  # Locked/interrupted cleanup is retried on the next sweep.
    return removed


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
        self._values: dict[str, int] = {}
        self._next_value_id = 1
        self._messages: list[dict[str, Any]] = []
        self._context: dict[str, Any] = {}
        self._has_header = False
        self._partial: list[str] = []
        self._partial_record: dict[str, Any] | None = None
        self._pending: list[dict[str, Any]] = []
        self._stamp: tuple[int, int] | None = None
        self._sync()

    def _sync(self) -> None:
        """A supervisor may append compaction diagnostics between worker runs."""
        if self._pending:
            return
        if self._stamp is not None and not self.path.exists():
            raise FileNotFoundError(f"Session log was removed: {self.path}")
        if self.path.exists():
            stat = self.path.stat()
            if self._stamp == (stat.st_size, stat.st_mtime_ns):
                return
            self._values.clear()
            self._next_value_id = 1
            self._messages = []
            self._context = {}
            self._has_header = False
            for record in iter_log_records(self.path):
                if record.get("log_version") == LOG_VERSION:
                    if record.get("type") == "log_value":
                        value_id = record["value_id"]
                        self._values[_digest(record["value"])] = value_id
                        self._next_value_id = max(self._next_value_id, value_id + 1)
                    elif record.get("type") == "llm_input":
                        edit = record["event"]["messages_delta"]
                        start = edit["start"]
                        self._messages[start:start + edit["delete"]] = edit["insert"]
                if record.get("type") in {"session_started", "context_changed"}:
                    self._has_header = True
                    self._context.update(record.get("event", {}))
            # Keep an incomplete crash tail separate from the next append.
            if self.path.stat().st_size:
                with self.path.open("rb+") as handle:
                    handle.seek(-1, 2)
                    if handle.read(1) != b"\n":
                        handle.seek(0, 2)
                        handle.write(b"\n")
            stat = self.path.stat()
            self._stamp = (stat.st_size, stat.st_mtime_ns)

    def write_session_header(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._sync()
            if not self._has_header:
                self.write_event("session_started", payload)
                self._has_header = True
            else:
                changed = {key: value for key, value in payload.items()
                           if key in {"system_prompt", "tools"}
                           and self._encode(value, key) != self._context.get(key)}
                if changed:
                    self.write_event("context_changed", changed)

    def write_entry(self, entry: dict[str, Any], *, request_id: str, raw_tool_result: bool = False, **metadata: Any) -> None:
        logged_entry = copy.deepcopy(entry)
        if raw_tool_result and logged_entry.get("role") == "tool":
            content, truncation = truncate_text(
                str(logged_entry.get("content") or ""),
                max_chars=MAX_LOG_TOOL_RESULT_CHARS,
                max_lines=MAX_LOG_TOOL_RESULT_LINES,
            )
            logged_entry["content"] = content
            metadata.update(truncation)
        self.write_record(
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
        self.write_record(payload)

    def _encode(self, value: Any, key: str = "") -> Any:
        if key in _BODY_FIELDS and value not in (None, "", []):
            digest = _digest(value)
            if digest not in self._values:
                value_id = self._next_value_id
                self._write({"type": "log_value", "value_id": value_id, "kind": key, "value": value})
                self._values[digest] = value_id
                self._next_value_id += 1
            return {"$log_ref": self._values[digest]}
        if isinstance(value, dict):
            return {name: self._encode(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [self._encode(item) for item in value]
        return value

    def flush_partial(self) -> None:
        """Failures retain partial output; successful streams live in Event only."""
        with self._lock:
            if self._partial_record is not None:
                record = self._partial_record
                record["type"] = "llm_partial_response"
                record["event"] = {"content": "".join(self._partial)}
                self._partial_record = None
                self._partial.clear()
                self.write_record(record)

    def commit_cycle(self) -> None:
        """Persist one completed/interrupted Agent Loop cycle with a single file write."""
        with self._lock:
            self.flush_partial()
            if not self._pending:
                return
            if self._stamp is not None and not self.path.exists():
                raise FileNotFoundError(f"Session log was removed: {self.path}")
            lines = "".join(_encoded(record) + "\n" for record in self._pending)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(lines)
                handle.flush()
            self._pending.clear()
            stat = self.path.stat()
            self._stamp = (stat.st_size, stat.st_mtime_ns)

    def write_record(self, payload: dict[str, Any]) -> None:
        """Append one semantic record, also used by the offline legacy converter."""
        with self._lock:
            self._sync()
            kind = payload.get("type")
            if kind == "assistant_delta":
                self._partial_record = dict(payload)
                self._partial.append(str(payload.get("event", {}).get("content") or ""))
                return
            if kind in {"llm_response", "llm_rejected_response"}:
                self._partial.clear()
                self._partial_record = None
            elif kind in {"llm_request_failed", "llm_request_interrupted", "run_failed", "run_finished", "llm_input"}:
                self.flush_partial()
            encoded = self._encode(payload)
            if kind == "llm_input":
                event = encoded["event"]
                messages = event.pop("messages")
                prefix = 0
                limit = min(len(self._messages), len(messages))
                while prefix < limit and self._messages[prefix] == messages[prefix]:
                    prefix += 1
                suffix = 0
                while suffix < limit - prefix and self._messages[-1 - suffix] == messages[-1 - suffix]:
                    suffix += 1
                end = len(messages) - suffix
                event["messages_delta"] = {
                    "start": prefix, "delete": len(self._messages) - prefix - suffix,
                    "insert": messages[prefix:end],
                }
                self._write(encoded)
                self._messages = messages
            else:
                self._write(encoded)
            if kind in {"session_started", "context_changed"}:
                self._context.update(encoded["event"])

    def _write(self, payload: dict[str, Any]) -> None:
        self._pending.append({"log_version": LOG_VERSION, **payload})

