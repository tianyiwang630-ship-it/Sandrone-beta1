from types import SimpleNamespace

from agent.core.message_pipeline import prepare_runtime_history, validate_assistant_message


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["file_path", "content"],
            },
        },
    }
]


def test_pre_message_drops_empty_assistant_but_keeps_full_tool_group():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": None},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "write", "arguments": '{"file_path":"a","content":"b"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]

    result = prepare_runtime_history(history, request_id="req")

    assert [item["role"] for item in result.history] == ["user", "assistant", "tool"]
    assert "drop_empty_assistant" in result.repairs
    assert result.history[1]["tool_calls"][0]["id"] == "call_1"


def test_pre_message_repairs_missing_id_type_and_object_arguments():
    history = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "write", "arguments": {"file_path": "a", "content": "b"}}}],
        }
    ]

    result = prepare_runtime_history(history, request_id="req-1")

    call = result.history[0]["tool_calls"][0]
    assert call["id"] == "call_repaired_req-1_0_0"
    assert call["type"] == "function"
    assert call["function"]["arguments"] == '{"file_path": "a", "content": "b"}'
    assert result.history[1]["role"] == "tool"


def test_post_message_repairs_fenced_and_python_dict_arguments():
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=None,
                type=None,
                function=SimpleNamespace(
                    name="write",
                    arguments="```json\n{'file_path': 'a', 'content': 'b'}\n```",
                ),
            )
        ],
    )

    result = validate_assistant_message(message, tools=TOOLS, request_id="req")

    assert result.valid is True
    call = result.message["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"].startswith("call_repaired_req")
    assert call["function"]["arguments"] == '{"file_path": "a", "content": "b"}'


def test_post_message_rejects_empty_response_and_missing_required_arguments():
    empty = validate_assistant_message(
        SimpleNamespace(content=None, tool_calls=[]),
        tools=TOOLS,
        request_id="req",
    )
    missing = validate_assistant_message(
        SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(name="write", arguments='{"file_path":"a"}'),
                )
            ],
        ),
        tools=TOOLS,
        request_id="req",
    )

    assert empty.valid is False
    assert empty.error == "assistant response is empty"
    assert missing.valid is False
    assert "missing required arguments" in missing.error


def test_post_message_rejects_truncated_tool_call_without_executing_it():
    result = validate_assistant_message(
        SimpleNamespace(
            content=None,
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(name="write", arguments='{"file_path":"a","content":"b"}'),
                )
            ],
        ),
        tools=TOOLS,
        request_id="req",
        finish_reason="length",
    )

    assert result.valid is False
    assert result.error == "assistant output was truncated"


def test_post_message_rejects_truncated_plain_text_response():
    result = validate_assistant_message(
        SimpleNamespace(content="unfinished", tool_calls=[]),
        tools=TOOLS,
        request_id="req",
        finish_reason="length",
    )

    assert result.valid is False
    assert result.error == "assistant output was truncated"


def test_post_message_reports_truncation_before_malformed_tool_arguments():
    result = validate_assistant_message(
        SimpleNamespace(
            content="starting",
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    type="function",
                    function=SimpleNamespace(name="write", arguments='{"file_path":"a"'),
                )
            ],
        ),
        tools=TOOLS,
        request_id="req",
        finish_reason="length",
    )

    assert result.valid is False
    assert result.error == "assistant output was truncated"
