import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.core.session_events import SessionEventWriter, truncate_tool_result
from tests.conftest import cleanup_test_dir, make_test_dir


def _read_records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    index = 0
    records: list[dict] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        record, next_index = decoder.raw_decode(text, index)
        records.append(record)
        index = next_index
    return records


def test_truncate_tool_result_limits_lines_and_marks_metadata():
    content = "\n".join(f"line {index}" for index in range(250))

    truncated, metadata = truncate_tool_result(content, max_chars=100000)

    assert metadata == {
        "truncated": True,
        "original_line_count": 250,
        "original_char_count": len(content),
    }
    assert truncated.count("\n") < 205
    assert "[工具输出已截断" in truncated
    assert "原始 250 行" in truncated
    assert f"原始 {len(content)} 字符" in truncated
    assert "保留" in truncated
    assert "截断位置" in truncated
    assert "请不要假设后续内容已读取" in truncated


def test_truncate_tool_result_allows_higher_limit_for_document_reads():
    content = "x" * 35000

    default_truncated, default_metadata = truncate_tool_result(content, max_chars=30000)
    document_truncated, document_metadata = truncate_tool_result(
        content,
        max_chars=30000,
        tool_name="read",
    )

    assert default_metadata["truncated"] is True
    assert document_metadata == {}
    assert len(document_truncated) == len(content)
    assert "[工具输出已截断" in default_truncated

def test_truncate_tool_result_uses_smaller_limits_for_browser_tools_without_affecting_reads():
    content = "x" * 35000

    navigate_truncated, navigate_metadata = truncate_tool_result(
        content,
        max_chars=30000,
        tool_name="browser_navigate",
    )
    snapshot_truncated, snapshot_metadata = truncate_tool_result(
        content,
        max_chars=30000,
        tool_name="browser_snapshot",
    )
    read_result, read_metadata = truncate_tool_result(
        content,
        max_chars=30000,
        tool_name="read",
    )

    assert navigate_metadata["truncated"] is True
    assert snapshot_metadata["truncated"] is True
    assert len(navigate_truncated) <= 6000
    assert len(snapshot_truncated) <= 11000
    assert read_metadata == {}
    assert len(read_result) == len(content)


def test_session_event_writer_appends_multiline_json_blocks_with_seq():
    tmp_dir = make_test_dir("session-events-writer")
    try:
        writer = SessionEventWriter(tmp_dir / "events", "abc123")

        writer.write({"role": "user", "content": "hello"})
        writer.write({"role": "assistant", "content": "world"})

        path = tmp_dir / "events" / "abc123.jsonl"
        text = path.read_text(encoding="utf-8")
        records = _read_records(path)

        assert [record["seq"] for record in records] == [1, 2]
        assert all(record["session_id"] == "abc123" for record in records)
        assert records[0]["entry"] == {"role": "user", "content": "hello"}
        assert records[1]["entry"] == {"role": "assistant", "content": "world"}
        assert '{\n  "ts": ' in text
        assert "\n\n{\n  \"ts\": " in text
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_event_writer_continues_seq_from_legacy_single_line_records():
    tmp_dir = make_test_dir("session-events-legacy")
    try:
        path = tmp_dir / "events" / "abc123.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"ts":"2026-06-06T20:00:00","seq":1,"session_id":"abc123","entry":{"role":"user","content":"one"}}\n'
            '{"ts":"2026-06-06T20:00:01","seq":2,"session_id":"abc123","entry":{"role":"assistant","content":"two"}}\n',
            encoding="utf-8",
        )

        writer = SessionEventWriter(tmp_dir / "events", "abc123")
        writer.write({"role": "tool", "content": "three"})

        records = _read_records(path)
        assert [record["seq"] for record in records] == [1, 2, 3]
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_event_writer_appends_compaction_event_with_summary():
    tmp_dir = make_test_dir("session-events-compaction")
    try:
        writer = SessionEventWriter(tmp_dir / "events", "abc123")

        writer.write_event(
            "context_compacted",
            {
                "trigger": "manual",
                "summary": "## 当前状态\n- 已压缩。",
                "before_message_count": 12,
                "after_message_count": 3,
            },
        )

        records = _read_records(tmp_dir / "events" / "abc123.jsonl")
        assert records[0]["type"] == "context_compacted"
        assert records[0]["event"]["summary"] == "## 当前状态\n- 已压缩。"
        assert records[0]["event"]["trigger"] == "manual"
        assert "entry" not in records[0]
    finally:
        cleanup_test_dir(tmp_dir)


def test_session_event_writer_compaction_event_continues_after_history_entries():
    tmp_dir = make_test_dir("session-events-compaction-seq")
    try:
        writer = SessionEventWriter(tmp_dir / "events", "abc123")
        writer.write({"role": "user", "content": "hello"})
        writer.write({"role": "assistant", "content": "working"})

        writer.write_event(
            "context_compacted",
            {
                "trigger": "auto-threshold",
                "summary": '## 当前状态\n- "quoted" | json-ish {x}',
            },
        )

        records = _read_records(tmp_dir / "events" / "abc123.jsonl")
        assert [record["seq"] for record in records] == [1, 2, 3]
        assert records[2]["type"] == "context_compacted"
        assert records[2]["event"]["summary"] == '## 当前状态\n- "quoted" | json-ish {x}'
    finally:
        cleanup_test_dir(tmp_dir)
