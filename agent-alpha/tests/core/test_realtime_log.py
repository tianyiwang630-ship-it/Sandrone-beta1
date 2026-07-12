import json

from agent.core.realtime_log import RealtimeLogWriter


def test_realtime_log_is_valid_jsonl_and_limits_raw_tool_results(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_session_header({"system_prompt": "secret Authorization token"})
    writer.write_entry(
        {"role": "tool", "tool_call_id": "call", "content": "x" * 200_000},
        request_id="req",
        raw_tool_result=True,
    )

    records = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["event"]["system_prompt"] == "secret Authorization token"
    assert records[1]["truncated"] is True
    assert records[1]["original_char_count"] == 200_000
    assert records[1]["retained_char_count"] <= 128_000


def test_realtime_log_header_is_written_once(tmp_path):
    first = RealtimeLogWriter(tmp_path, "sess")
    first.write_session_header({"value": 1})
    second = RealtimeLogWriter(tmp_path, "sess")
    second.write_session_header({"value": 2})

    records = [json.loads(line) for line in first.path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["event"]["value"] == 1

