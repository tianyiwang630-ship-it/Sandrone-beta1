"""Compact stopped sessions' debug logs, verifying retained records before replacement."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.core.realtime_log import RealtimeLogWriter, cleanup_expired_logs, read_realtime_log


def _fingerprint(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compact_log(source: Path, output_dir: Path, *, replace: bool = False) -> dict:
    source = Path(source).resolve()
    destination = Path(output_dir).resolve() / source.name
    if source == destination or destination.exists():
        raise ValueError("Choose an output directory without an existing copy of this log")
    before = source.stat()
    writer = RealtimeLogWriter(destination.parent, source.stem)
    expected = hashlib.sha256()
    expected_count = 0
    original_partials = []
    for record in read_realtime_log(source, strict=True):
        kind = record.get("type")
        if kind == "llm_partial_response":
            original_partials.append(_fingerprint(record))
        elif kind != "assistant_delta":
            expected.update(_fingerprint(record) + b"\n")
            expected_count += 1
        writer.write_record(record)
    writer.commit_cycle()

    actual = hashlib.sha256()
    actual_count = 0
    partials = []
    for record in read_realtime_log(destination, strict=True):
        if record.get("type") == "llm_partial_response":
            partials.append(_fingerprint(record))
            continue
        actual.update(_fingerprint(record) + b"\n")
        actual_count += 1
    if actual_count != expected_count or actual.digest() != expected.digest():
        raise ValueError("Compacted log differs from the original non-stream records")
    remaining = iter(partials)
    if any(not any(item == old for item in remaining) for old in original_partials):
        raise ValueError("An existing partial response was lost")
    current = source.stat()
    if (before.st_size, before.st_mtime_ns) != (current.st_size, current.st_mtime_ns):
        raise RuntimeError("Source log changed during compaction; stop the session before retrying")
    after_bytes = destination.stat().st_size
    if replace:
        if after_bytes >= before.st_size:
            raise ValueError("Compaction did not reduce this file; the source was not replaced")
        os.replace(destination, source)
    return {
        "source": str(source), "output": str(source if replace else destination),
        "before_bytes": before.st_size, "after_bytes": after_bytes,
        "reduction_percent": round(100 * (1 - after_bytes / max(1, before.st_size)), 2),
        "verified_records": actual_count, "partial_responses": len(partials), "replaced": replace,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="*")
    parser.add_argument("--logs-dir", type=Path, help="Process every .jsonl debug log in this directory")
    parser.add_argument("--prune-days", type=int, help="Delete expired debug logs before migration")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--replace", action="store_true", help="Replace verified originals; stop the application first")
    parser.add_argument("--read", action="store_true", help="Read expanded records instead of compacting")
    parser.add_argument("--request-id")
    parser.add_argument("--event-type")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    logs = list(args.logs)
    if args.logs_dir:
        logs.extend(sorted(args.logs_dir.resolve().glob("*.jsonl")))
    if args.prune_days is not None:
        if not args.logs_dir:
            parser.error("--prune-days requires --logs-dir")
        removed = cleanup_expired_logs(args.logs_dir, retention_days=args.prune_days)
        print(json.dumps({"pruned": [str(path) for path in removed], "retention_days": args.prune_days},
                         ensure_ascii=False), flush=True)
        logs = [path for path in logs if path.exists()]
    if not logs:
        parser.error("provide log paths or --logs-dir")
    if args.read:
        if args.replace or args.limit <= 0:
            parser.error("--read requires a positive --limit and cannot use --replace")
        count = 0
        for path in logs:
            for record in read_realtime_log(path, strict=True):
                if args.request_id and record.get("request_id") != args.request_id:
                    continue
                if args.event_type and record.get("type") != args.event_type:
                    continue
                print(json.dumps(record, ensure_ascii=False))
                count += 1
                if count >= args.limit:
                    return
        return
    directory = args.output_dir or (
        Path(__file__).resolve().parents[1] / "temp" / "log-compaction" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    failures = 0
    for path in logs:
        try:
            report = compact_log(path, directory, replace=args.replace)
        except Exception as exc:
            failures += 1
            report = {"source": str(path), "error_type": type(exc).__name__, "error": str(exc)}
        print(json.dumps(report, ensure_ascii=False), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
