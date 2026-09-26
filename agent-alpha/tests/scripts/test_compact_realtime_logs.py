import json

import pytest

from agent.core.realtime_log import RealtimeLogWriter, read_realtime_log
from scripts.compact_realtime_logs import compact_log


def test_legacy_compaction_reconstructs_inputs_and_keeps_failure_evidence(tmp_path):
    source = tmp_path / "sess.jsonl"
    messages = [{"role": "system", "content": "长期规则" * 4000}]
    records = []
    for i in range(30):
        messages = [*messages, {"role": "user", "content": f"消息{i}"}]
        records.extend([
            {"type": "llm_input", "event": {"messages": messages}, "request_id": str(i)},
            {"type": "assistant_delta", "event": {"content": "回答"}, "request_id": str(i)},
            {"type": "llm_response", "event": {"content": "回答"}, "request_id": str(i)},
        ])
    records.extend([
        {"type": "assistant_delta", "event": {"content": "最后半句"}, "request_id": "bad"},
        {"type": "run_failed", "event": {"error_message": "连接中断"}, "request_id": "bad"},
    ])
    source.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8")
    report = compact_log(source, tmp_path / "result", replace=True)
    actual = list(read_realtime_log(source, strict=True))
    assert report["reduction_percent"] > 95
    assert [item for item in actual if item.get("type") != "llm_partial_response"] == [
        item for item in records if item.get("type") != "assistant_delta"
    ]
    assert actual[-2]["event"]["content"] == "最后半句"
    assert not (tmp_path / "result" / source.name).exists()
    # Reopening the migrated log must continue from the retained input sequence.
    writer = RealtimeLogWriter(tmp_path, "sess")
    writer.write_event("llm_input", {"messages": messages})
    writer.commit_cycle()
    assert list(read_realtime_log(source))[-1]["event"]["messages"] == messages


def test_malformed_source_is_never_replaced(tmp_path):
    source = tmp_path / "sess.jsonl"
    content = b'{"type":"run_started","event":{}}\n{"broken":'
    source.write_bytes(content)
    with pytest.raises(ValueError):
        compact_log(source, tmp_path / "result", replace=True)
    assert source.read_bytes() == content


def test_source_changed_during_compaction_is_never_replaced(tmp_path, monkeypatch):
    source = tmp_path / "sess.jsonl"
    source.write_text('{"type":"run_started","event":{}}\n', encoding="utf-8")
    flush = RealtimeLogWriter.flush_partial

    def change_source(writer):
        flush(writer)
        with source.open("a", encoding="utf-8") as handle:
            handle.write('{"type":"late_write","event":{}}\n')

    monkeypatch.setattr(RealtimeLogWriter, "flush_partial", change_source)
    with pytest.raises(RuntimeError, match="changed"):
        compact_log(source, tmp_path / "result", replace=True)
    assert "late_write" in source.read_text(encoding="utf-8")
