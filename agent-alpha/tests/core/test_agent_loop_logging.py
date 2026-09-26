import json
from types import SimpleNamespace

import pytest

from agent.core.agent_loop import AgentLoop
from agent.core.realtime_log import RealtimeLogWriter, read_realtime_log
from agent.errors import LLMInvalidResponse


def test_tool_log_matches_actual_history_and_next_model_input(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    captured = []
    definition = {"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}

    def generate_with_tools(messages, tools):
        captured.append(messages)
        calls = [SimpleNamespace(id="call", type="function", function=SimpleNamespace(name="read", arguments="{}"))]
        message = SimpleNamespace(content=None if len(captured) == 1 else "完成",
                                  tool_calls=calls if len(captured) == 1 else [])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)])

    history = []
    loop = AgentLoop(llm=SimpleNamespace(generate_with_tools=generate_with_tools), tools=[definition],
                     tool_loader=SimpleNamespace(execute_tool=lambda *args: "原始输出" * 100_000),
                     history=history, system_prompt="规则", max_turns=3, log_writer=writer,
                     max_tool_result_chars=100)
    assert loop.run("读取") == "完成"
    writer.commit_cycle()
    records = list(read_realtime_log(writer.path, strict=True))
    logged_tool = next(item for item in records if item.get("entry", {}).get("role") == "tool")
    actual_tool = next(item for item in history if item["role"] == "tool")
    assert logged_tool["entry"] == actual_tool
    assert logged_tool["truncated"] is True
    assert [item["event"]["messages"] for item in records if item.get("type") == "llm_input"] == captured
    bodies = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]
    assert sum(item.get("value") == actual_tool["content"] for item in bodies) == 1


def test_rejected_response_remains_in_debug_log_but_not_history(tmp_path):
    writer = RealtimeLogWriter(tmp_path, "sess")
    message = SimpleNamespace(content="被截断的回答", reasoning_content="相关思考", tool_calls=[])
    llm = SimpleNamespace(generate_with_tools=lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="length")]))
    history = []
    loop = AgentLoop(llm=llm, tools=[], tool_loader=None, history=history,
                     system_prompt="规则", max_turns=1, log_writer=writer)
    with pytest.raises(LLMInvalidResponse):
        loop._call_llm([{"role": "user", "content": "请求"}])
    writer.commit_cycle()
    record = next(item for item in read_realtime_log(writer.path) if item.get("type") == "llm_rejected_response")
    assert record["event"]["content"] == "被截断的回答"
    assert history == []
