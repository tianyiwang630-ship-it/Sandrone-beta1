import json

from agent.core.session_events import SessionEventWriter, migrate_event_file, read_session_events


def test_event_writer_keeps_write_event_and_reader_filters_by_sequence(tmp_path):
    writer = SessionEventWriter(tmp_path, "sess")
    writer.write({"role": "user", "content": "hello"}, request_id="req")
    writer.write_event("tool_execution_started", {"tool_call_id": "call_1"})

    records = read_session_events(tmp_path, "sess", after_seq=1)

    assert len(records) == 1
    assert records[0]["seq"] == 2
    assert records[0]["type"] == "tool_execution_started"


def test_event_reader_and_reopened_writer_tolerate_truncated_final_record(tmp_path):
    writer = SessionEventWriter(tmp_path, "sess")
    writer.write({"role": "user", "content": "hello"}, request_id="req")
    with writer.path.open("a", encoding="utf-8") as handle:
        handle.write('{"seq": 2, "entry": ')

    records = read_session_events(tmp_path, "sess")
    reopened = SessionEventWriter(tmp_path, "sess")

    assert len(records) == 1
    assert records[0]["seq"] == 1
    assert reopened._next_seq == 2


def test_event_writer_truncates_copy_without_changing_session_entry(tmp_path):
    arguments = json.dumps({"text": "a" * 4000})
    entry = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": arguments}}
        ],
    }
    writer = SessionEventWriter(tmp_path, "sess")

    writer.write(entry, request_id="req")

    assert entry["tool_calls"][0]["function"]["arguments"] == arguments
    stored = read_session_events(tmp_path, "sess")[0]
    stored_arguments = stored["entry"]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(stored_arguments)["_event_truncated"] is True
    assert stored["entry_truncation"]["tool_call_0_arguments"]["original_char_count"] == len(arguments)


def test_event_tool_result_stops_at_character_or_line_limit(tmp_path):
    writer = SessionEventWriter(tmp_path, "sess")
    writer.write({"role": "tool", "tool_call_id": "chars", "content": "x" * 9000})
    writer.write({"role": "tool", "tool_call_id": "lines", "content": "\n".join(["x"] * 200)})

    records = read_session_events(tmp_path, "sess")

    assert records[0]["entry_truncation"]["tool_result"]["original_char_count"] == 9000
    assert records[1]["entry_truncation"]["tool_result"]["original_line_count"] == 200
    assert records[0]["entry_truncation"]["tool_result"]["retained_char_count"] <= 4000
    assert records[1]["entry_truncation"]["tool_result"]["retained_line_count"] <= 60


def test_compact_completed_request_removes_only_matching_low_value_events_and_preserves_seq(tmp_path):
    writer = SessionEventWriter(tmp_path, "sess")
    writer.write_event("assistant_delta", {"request_id": "req_1", "content": "a"})
    writer.write_event("llm_request_started", {"request_id": "req_1"})
    writer.write_event("assistant_delta", {"request_id": "req_2", "content": "b"})
    writer.write({"role": "assistant", "content": "done"}, request_id="req_1")

    assert writer.compact_completed_request("req_1") == 2

    reopened = SessionEventWriter(tmp_path, "sess")
    reopened.write_event("tool_execution_started", {"request_id": "req_3"})
    records = read_session_events(tmp_path, "sess")
    assert [record["seq"] for record in records] == [3, 4, 5]


def test_historical_migration_is_idempotent(tmp_path):
    writer = SessionEventWriter(tmp_path, "sess")
    writer.write_event("assistant_delta", {"content": "old"})
    writer.write({"role": "tool", "tool_call_id": "call", "content": "x" * 9000})

    assert migrate_event_file(writer.path, cleanup_completed=True) is True
    first = writer.path.read_text(encoding="utf-8")
    assert migrate_event_file(writer.path, cleanup_completed=True) is False
    assert writer.path.read_text(encoding="utf-8") == first
