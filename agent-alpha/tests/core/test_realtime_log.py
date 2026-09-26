import json

import copy
from datetime import datetime
from pathlib import Path

import pytest

from agent.core.realtime_log import RealtimeLogWriter, cleanup_expired_logs, read_realtime_log


def test_realtime_log_is_valid_jsonl_and_limits_raw_tool_results(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_session_header({"system_prompt": "secret Authorization token"})
    writer.write_entry(
        {"role": "tool", "tool_call_id": "call", "content": "x" * 200_000},
        request_id="req",
        raw_tool_result=True,
    )
    writer.commit_cycle()

    records = list(read_realtime_log(writer.path, strict=True))
    assert records[0]["event"]["system_prompt"] == "secret Authorization token"
    assert records[1]["truncated"] is True
    assert records[1]["original_char_count"] == 200_000
    assert records[1]["retained_char_count"] <= 128_000


def test_realtime_log_header_is_written_once(tmp_path):
    first = RealtimeLogWriter(tmp_path, "sess")
    first.write_session_header({"value": 1})
    first.commit_cycle()
    second = RealtimeLogWriter(tmp_path, "sess")
    second.write_session_header({"value": 2})
    second.commit_cycle()

    records = list(read_realtime_log(first.path, strict=True))
    assert len(records) == 1
    assert records[0]["event"]["value"] == 1


def test_input_edits_replay_after_restart_repair_compaction_and_duplicate_messages(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    messages = [{"role": "system", "content": "规则一"}, {"role": "user", "content": "继续"}]
    expected = []

    def record():
        expected.append(copy.deepcopy(messages))
        writer.write_event("llm_input", {"messages": messages, "tool_count": 0})
        writer.commit_cycle()

    record()
    messages.append({"role": "user", "content": "继续"})
    record()
    writer = RealtimeLogWriter(tmp_path, "sess")
    record()  # Restart with no changes must not store a complete history again.
    messages[0]["content"] = "规则二"
    messages.insert(1, {"role": "system", "content": "临时恢复指令"})
    record()
    messages[2]["content"] = "更正后的输入"
    record()
    messages[:] = [messages[0], {"role": "assistant", "content": "压缩摘要"}, messages[-1]]
    record()
    messages.clear()
    record()
    actual = [item["event"]["messages"] for item in read_realtime_log(writer.path)]
    assert actual == expected
    raw = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    assert sum(item.get("value") == "继续" for item in raw) == 1
    inputs = [item for item in raw if item.get("type") == "llm_input"]
    assert inputs[2]["event"]["messages_delta"] == {"start": 3, "delete": 0, "insert": []}


def test_prompt_and_tools_changes_saved_once_and_stale_writers_sync(tmp_path):
    one = RealtimeLogWriter(tmp_path, "sess")
    header = {"system_prompt": "第一版", "tools": [{"name": "read"}]}
    one.write_session_header(header)
    one.commit_cycle()
    two = RealtimeLogWriter(tmp_path, "sess")
    two.write_session_header({**header, "system_prompt": "第二版"})
    two.commit_cycle()
    one.write_session_header({"system_prompt": "第二版", "tools": [{"name": "write"}]})
    one.commit_cycle()
    one.write_session_header({"system_prompt": "第二版", "tools": [{"name": "write"}]})
    one.commit_cycle()
    records = list(read_realtime_log(one.path, strict=True))
    assert [item["type"] for item in records] == ["session_started", "context_changed", "context_changed"]
    assert records[1]["event"] == {"system_prompt": "第二版"}
    assert records[2]["event"] == {"tools": [{"name": "write"}]}


def test_successful_stream_not_duplicated_and_failed_partial_is_preserved(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_event("assistant_delta", {"content": "完整"}, request_id="ok")
    writer.write_event("assistant_delta", {"content": "回答"}, request_id="ok")
    writer.write_event("llm_response", {"content": "完整回答"}, request_id="ok")
    writer.write_entry({"role": "assistant", "content": "完整回答"}, request_id="ok")
    writer.write_event("assistant_delta", {"content": "未完成"}, request_id="bad")
    writer.write_event("llm_request_failed", {"error_message": "断线"}, request_id="bad")
    writer.commit_cycle()
    records = list(read_realtime_log(writer.path, strict=True))
    assert [item.get("type") for item in records] == ["llm_response", None, "llm_partial_response", "llm_request_failed"]
    assert records[2]["event"]["content"] == "未完成"
    raw = writer.path.read_text(encoding="utf-8")
    assert raw.count("完整回答") == 1


def test_crash_tail_can_resume_and_removed_log_cannot_be_recreated(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_entry({"role": "user", "content": "之前"}, request_id="old")
    writer.commit_cycle()
    with writer.path.open("ab") as handle:
        handle.write(b'{"unfinished":')
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_entry({"role": "user", "content": "之后"}, request_id="new")
    writer.commit_cycle()
    assert [item["entry"]["content"] for item in read_realtime_log(writer.path)] == ["之前", "之后"]
    writer.path.unlink()
    with pytest.raises(FileNotFoundError):
        writer.write_entry({"role": "assistant", "content": "迟到"}, request_id="new")
    assert not writer.path.exists()


def test_log_growth_is_incremental_and_tool_arguments_are_not_copied(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    arguments = json.dumps({"html": "<p>正文</p>" * 1000}, ensure_ascii=False)
    messages = [{"role": "system", "content": "规则" * 5000}, {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call", "function": {"name": "write", "arguments": arguments}}],
    }]
    for i in range(100):
        messages.append({"role": "user", "content": f"第{i}轮"})
        writer.write_event("llm_input", {"messages": messages})
        writer.commit_cycle()
    assert writer.path.stat().st_size < 100_000
    assert list(read_realtime_log(writer.path))[-1]["event"]["messages"] == messages


def test_one_cycle_batches_many_records_into_one_disk_append(tmp_path, monkeypatch):
    writer = RealtimeLogWriter(tmp_path, "sess")
    appends = []
    original_open = Path.open

    def tracked_open(path, mode="r", *args, **kwargs):
        if path == writer.path and mode == "a":
            appends.append(mode)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    writer.write_event("run_started", {})
    writer.write_event("llm_input", {"messages": [{"role": "user", "content": "你好"}]})
    writer.write_event("llm_response", {"content": "收到"})
    writer.write_entry({"role": "assistant", "content": "收到"}, request_id="req")
    assert not writer.path.exists()
    writer.commit_cycle()
    assert appends == ["a"]
    assert len(list(read_realtime_log(writer.path, strict=True))) == 4


def test_retention_removes_only_logs_older_than_7_days(tmp_path):
    old = tmp_path / "old.jsonl"
    copied_old = tmp_path / "copied-old.jsonl"
    recent = tmp_path / "recent.jsonl"
    archive = tmp_path / "old-archive.json"
    unrelated = tmp_path / "notes.txt"
    old.write_text('{"ts":"2026-07-01T12:00:00","type":"run_finished","event":{}}\n', encoding="utf-8")
    copied_old.write_text('{"ts":"2026-07-02T12:00:00","type":"run_finished","event":{}}\n', encoding="utf-8")
    recent.write_text('{"ts":"2026-09-15T12:00:01","type":"run_finished","event":{}}\n', encoding="utf-8")
    archive.write_text(json.dumps({"end_time": "2026-07-03T12:00:00"}), encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")
    old_time = datetime(2026, 7, 4).timestamp()
    recent_time = datetime(2026, 9, 15, 12, 0, 1).timestamp()
    __import__("os").utime(old, (old_time, old_time))
    __import__("os").utime(copied_old, (old_time, old_time))
    __import__("os").utime(recent, (recent_time, recent_time))
    __import__("os").utime(archive, (old_time, old_time))
    removed = cleanup_expired_logs(tmp_path, now=datetime(2026, 9, 22, 12, 0, 0))
    assert {path.name for path in removed} == {"old.jsonl", "copied-old.jsonl", "old-archive.json"}
    assert not copied_old.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_retention_boundary_and_invalid_days(tmp_path):
    boundary = tmp_path / "boundary.jsonl"
    boundary.write_text('{"ts":"2026-09-15T12:00:00","event":{}}\n', encoding="utf-8")
    boundary_time = datetime(2026, 9, 15, 12, 0, 0).timestamp()
    __import__("os").utime(boundary, (boundary_time, boundary_time))
    assert cleanup_expired_logs(tmp_path, now=datetime(2026, 9, 22, 12, 0, 0)) == []
    with pytest.raises(ValueError):
        cleanup_expired_logs(tmp_path, retention_days=0)


def test_retention_skips_locked_file_and_retries_next_sweep(tmp_path, monkeypatch):
    locked = tmp_path / "locked.jsonl"
    other = tmp_path / "other.jsonl"
    for path in (locked, other):
        path.write_text('{"ts":"2026-07-01T00:00:00","event":{}}\n', encoding="utf-8")
        old_time = datetime(2026, 7, 1).timestamp()
        __import__("os").utime(path, (old_time, old_time))
    unlink = Path.unlink

    def fail_locked(path, *args, **kwargs):
        if path == locked:
            raise PermissionError("in use")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_locked)
    removed = cleanup_expired_logs(tmp_path, now=datetime(2026, 9, 22))
    assert removed == [other]
    assert locked.exists() and not other.exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    assert cleanup_expired_logs(tmp_path, now=datetime(2026, 9, 22)) == [locked]

