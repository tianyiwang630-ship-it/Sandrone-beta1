from agent.core.context_manager import ContextManager


SUMMARY_JSON = """{
  "task_timeline": [],
  "skill_deltas": [],
  "important_files": [],
  "current_state": {},
  "error_memory": [],
  "critical_user_intents": []
}"""


class RecordingSummaryLLM:
    def __init__(self, response=SUMMARY_JSON, error=None):
        self.response = response
        self.error = error
        self.prompts = []

    def generate(self, prompt, max_tokens):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.response


def _assistant_with_tool_calls(*tool_ids):
    return {
        "role": "assistant",
        "content": "calling tools",
        "tool_calls": [
            {
                "id": tool_id,
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command": "echo hi"}'},
            }
            for tool_id in tool_ids
        ],
    }


def _tool(tool_id, content="tool result"):
    return {"role": "tool", "tool_call_id": tool_id, "content": content}


def _assert_no_orphan_tools(history):
    open_ids = set()
    for message in history:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            open_ids.update(tool_call["id"] for tool_call in message["tool_calls"])
            continue
        if message.get("role") == "tool":
            assert message.get("tool_call_id") in open_ids
            open_ids.discard(message.get("tool_call_id"))


def test_compress_history_keeps_parent_assistant_when_recent_boundary_starts_with_tool():
    llm = RecordingSummaryLLM()
    manager = ContextManager(llm=llm, tools=[], system_prompt="", keep_recent_turns=10)
    history = [
        {"role": "user", "content": f"old {index}"}
        for index in range(34)
    ] + [
        _assistant_with_tool_calls("call-parent"),
        _tool("call-parent"),
        {"role": "assistant", "content": "after parent"},
        _assistant_with_tool_calls("call-1"),
        _tool("call-1"),
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next question"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "one more"},
        {"role": "assistant", "content": "final"},
        {"role": "user", "content": "tail"},
    ]

    compressed = manager.compress_history(history)

    assert compressed[0]["role"] == "user"
    parent_index = next(
        index
        for index, message in enumerate(compressed)
        if message.get("role") == "assistant"
        and message.get("tool_calls")
        and message["tool_calls"][0]["id"] == "call-parent"
    )
    assert compressed[parent_index + 1]["tool_call_id"] == "call-parent"
    _assert_no_orphan_tools(compressed[1:])


def test_compress_history_keeps_multi_tool_call_group_complete():
    llm = RecordingSummaryLLM()
    manager = ContextManager(llm=llm, tools=[], system_prompt="", keep_recent_turns=2)
    history = [
        {"role": "user", "content": f"old {index}"}
        for index in range(8)
    ] + [
        _assistant_with_tool_calls("call-1", "call-2", "call-3"),
        _tool("call-1"),
        _tool("call-2"),
        _tool("call-3"),
        {"role": "assistant", "content": "all tools done"},
    ]

    compressed = manager.compress_history(history)

    recent = compressed[1:]
    assert recent[0]["role"] == "assistant"
    assert [tool_call["id"] for tool_call in recent[0]["tool_calls"]] == ["call-1", "call-2", "call-3"]
    assert [message["tool_call_id"] for message in recent[1:4]] == ["call-1", "call-2", "call-3"]
    _assert_no_orphan_tools(recent)


def test_compression_summary_uses_plain_text_transcript_not_raw_messages_json():
    llm = RecordingSummaryLLM()
    manager = ContextManager(llm=llm, tools=[], system_prompt="", keep_recent_turns=1)
    history = [
        {"role": "user", "content": "research"},
        _assistant_with_tool_calls("call-1"),
        _tool("call-1", "x" * 5000),
        {"role": "assistant", "content": "done"},
    ]

    manager.compress_history(history)

    prompt = llm.prompts[0]
    assert "对话转写" in prompt
    assert "assistant tool_call bash" in prompt
    assert '"role": "tool"' not in prompt
    assert '"tool_calls"' not in prompt


def test_compression_accepts_plain_text_summary_with_json_like_fragments():
    summary_text = '摘要：中文、"引号"、{坏掉的 JSON 片段，依然只是文本。'
    llm = RecordingSummaryLLM(response=summary_text)
    manager = ContextManager(llm=llm, tools=[], system_prompt="", keep_recent_turns=1)
    history = [
        {"role": "user", "content": "old research"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "latest question"},
        {"role": "assistant", "content": "latest answer"},
    ]

    compressed = manager.compress_history(history)

    assert compressed[0] == {"role": "user", "content": summary_text}
    assert compressed[1:] == history[-1:]


def test_compression_failure_falls_back_to_short_valid_recent_history(capsys):
    llm = RecordingSummaryLLM(error=RuntimeError("summary failed"))
    manager = ContextManager(
        llm=llm,
        tools=[],
        system_prompt="",
        max_context_tokens=1000,
        keep_recent_turns=5,
    )
    history = []
    for index in range(20):
        history.extend(
            [
                {"role": "user", "content": f"u{index}"},
                _assistant_with_tool_calls(f"call-{index}"),
                _tool(f"call-{index}", "result"),
                {"role": "assistant", "content": f"a{index}"},
            ]
        )

    fallback = manager.compress_history(history)

    out = capsys.readouterr().out
    target = int(manager.available_for_history * manager.compression_threshold * 0.3)
    assert "压缩失败，已退回最近短上下文" in out
    assert manager.count_history_tokens(fallback) <= target
    _assert_no_orphan_tools(fallback)
