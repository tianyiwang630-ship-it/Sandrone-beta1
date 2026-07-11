from agent.core.session_events import SessionEventWriter, read_session_events


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
