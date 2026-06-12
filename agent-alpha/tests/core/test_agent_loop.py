from pathlib import Path
import json
import sys
import threading
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from agent.core.agent_loop import AgentLoop
from agent.core.session_events import SessionEventWriter
from tests.conftest import cleanup_test_dir, make_test_dir


def _read_event_records(path: Path) -> list[dict]:
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


class FakeToolFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, tool_id, name, arguments):
        self.id = tool_id
        self.function = FakeToolFunction(name, arguments)


class FakeMessage:
    def __init__(self, content, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls or []
        if reasoning_content is not None:
            self.reasoning_content = reasoning_content


class FakeLLM:
    def __init__(self, provider="openai", first_message=None):
        self.profile = type("Profile", (), {"provider": provider})()
        self.messages_seen = []
        self._responses = [
            first_message
            or FakeMessage(
                content="",
                tool_calls=[FakeToolCall("call-1", "load_skill", '{"name": "pdf"}')],
            ),
            FakeMessage(content="done", tool_calls=[]),
        ]

    def generate_with_tools(self, messages, tools):
        self.messages_seen.append(messages)
        message = self._responses.pop(0)
        return type("Resp", (), {"choices": [type("Choice", (), {"message": message})()]})()


class FakeToolLoader:
    def __init__(self):
        self.calls = []

    def execute_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return '<skill name="pdf">\nUse OCR when needed.\n</skill>'


class SlowLLM:
    def __init__(self, delay=1.0):
        self.profile = type("Profile", (), {"provider": "openai"})()
        self.delay = delay

    def generate_with_tools(self, messages, tools):
        time.sleep(self.delay)
        message = FakeMessage(content="late answer", tool_calls=[])
        return type("Resp", (), {"choices": [type("Choice", (), {"message": message})()]})()


class EventSettingLLM:
    def __init__(self, interrupt_event):
        self.profile = type("Profile", (), {"provider": "openai"})()
        self.interrupt_event = interrupt_event

    def generate_with_tools(self, messages, tools):
        self.interrupt_event.set()
        message = FakeMessage(
            content="",
            tool_calls=[FakeToolCall("call-1", "bash", '{"command": "echo should-not-run"}')],
        )
        return type("Resp", (), {"choices": [type("Choice", (), {"message": message})()]})()


class InterruptingToolLoader:
    def __init__(self, interrupt_event):
        self.interrupt_event = interrupt_event
        self.calls = []

    def execute_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        self.interrupt_event.set()
        return {"success": False, "interrupted": True, "error": "Command interrupted by ESC"}


class CountingToolLoader:
    def __init__(self, interrupt_event=None):
        self.interrupt_event = interrupt_event
        self.calls = []

    def execute_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.interrupt_event is not None:
            self.interrupt_event.set()
        return {"ok": True, "tool": tool_name}


class LargeResultToolLoader:
    def __init__(self, line_count=250):
        self.line_count = line_count

    def execute_tool(self, tool_name, arguments):
        return "\n".join(f"line {index}" for index in range(self.line_count))


class BlockingToolLoader:
    def __init__(self, delay=1.0):
        self.delay = delay
        self.calls = []

    def execute_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        time.sleep(self.delay)
        return {"ok": True}


def test_agent_loop_runs_tool_then_returns_final_answer():
    history = []
    llm = FakeLLM()
    tool_loader = FakeToolLoader()
    loop = AgentLoop(
        llm=llm,
        tools=[{"type": "function", "function": {"name": "load_skill"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
    )

    result = loop.run("please help with pdf")

    assert result == "done"
    assert tool_loader.calls == [("load_skill", {"name": "pdf"})]
    assert history[0] == {"role": "user", "content": "please help with pdf"}
    assert history[-1] == {"role": "assistant", "content": "done"}


def test_agent_loop_appends_realtime_events_for_history_entries():
    tmp_dir = make_test_dir("agent-loop-events")
    try:
        history = []
        llm = FakeLLM()
        tool_loader = FakeToolLoader()
        writer = SessionEventWriter(tmp_dir / "events", "abc123")
        loop = AgentLoop(
            llm=llm,
            tools=[{"type": "function", "function": {"name": "load_skill"}}],
            tool_loader=tool_loader,
            history=history,
            system_prompt="system prompt",
            max_turns=3,
            event_writer=writer,
        )

        result = loop.run("please help with pdf")

        assert result == "done"
        records = _read_event_records(tmp_dir / "events" / "abc123.jsonl")
        assert [record["entry"]["role"] for record in records] == ["user", "assistant", "tool", "assistant"]
        assert [record["seq"] for record in records] == [1, 2, 3, 4]
        assert records[1]["entry"]["tool_calls"][0]["function"]["name"] == "load_skill"
    finally:
        cleanup_test_dir(tmp_dir)


def test_agent_loop_marks_truncated_tool_results_in_events():
    tmp_dir = make_test_dir("agent-loop-events-truncate")
    try:
        history = []
        llm = FakeLLM(first_message=FakeMessage(content="", tool_calls=[FakeToolCall("call-1", "bash", '{"command": "huge"}')]))
        writer = SessionEventWriter(tmp_dir / "events", "abc123")
        loop = AgentLoop(
            llm=llm,
            tools=[{"type": "function", "function": {"name": "bash"}}],
            tool_loader=LargeResultToolLoader(line_count=250),
            history=history,
            system_prompt="system prompt",
            max_turns=3,
            event_writer=writer,
            max_tool_result_chars=100000,
        )

        result = loop.run("run huge tool")

        assert result == "done"
        records = _read_event_records(tmp_dir / "events" / "abc123.jsonl")
        tool_record = next(record for record in records if record["entry"]["role"] == "tool")
        assert tool_record["truncated"] is True
        assert tool_record["original_line_count"] == 250
        assert "[工具输出已截断" in tool_record["entry"]["content"]
        assert "原始 250 行" in tool_record["entry"]["content"]
        assert "请不要假设后续内容已读取" in tool_record["entry"]["content"]
        assert history[2]["content"] == tool_record["entry"]["content"]
    finally:
        cleanup_test_dir(tmp_dir)


def test_deepseek_tool_call_reasoning_content_is_replayed():
    history = []
    llm = FakeLLM(
        provider="MyDeepSeekProvider",
        first_message=FakeMessage(
            content="",
            reasoning_content="I should load the PDF skill first.",
            tool_calls=[FakeToolCall("call-1", "load_skill", '{"name": "pdf"}')],
        ),
    )
    tool_loader = FakeToolLoader()
    loop = AgentLoop(
        llm=llm,
        tools=[{"type": "function", "function": {"name": "load_skill"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
    )

    loop.run("please help with pdf")

    tool_call_message = history[1]
    assert tool_call_message["reasoning_content"] == "I should load the PDF skill first."
    assert llm.messages_seen[1][2]["reasoning_content"] == "I should load the PDF skill first."


def test_non_deepseek_tool_call_does_not_store_reasoning_content():
    history = []
    llm = FakeLLM(
        provider="openai",
        first_message=FakeMessage(
            content="",
            reasoning_content="Do not keep this for non-DeepSeek providers.",
            tool_calls=[FakeToolCall("call-1", "load_skill", '{"name": "pdf"}')],
        ),
    )
    tool_loader = FakeToolLoader()
    loop = AgentLoop(
        llm=llm,
        tools=[{"type": "function", "function": {"name": "load_skill"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
    )

    loop.run("please help with pdf")

    assert "reasoning_content" not in history[1]
    assert "reasoning_content" not in llm.messages_seen[1][2]


def test_agent_loop_returns_promptly_when_llm_wait_is_interrupted():
    history = []
    interrupt_event = threading.Event()

    def start_interrupt_listener():
        timer = threading.Timer(0.05, interrupt_event.set)
        timer.daemon = True
        timer.start()
        return timer

    loop = AgentLoop(
        llm=SlowLLM(delay=1.0),
        tools=[],
        tool_loader=FakeToolLoader(),
        history=history,
        system_prompt="system prompt",
        max_turns=3,
        interrupt_event=interrupt_event,
        start_interrupt_listener=start_interrupt_listener,
    )

    started_at = time.monotonic()
    result = loop.run("please stop soon")

    assert result == "[用户中断] 已停止当前任务。"
    assert time.monotonic() - started_at < 0.5
    assert history == [{"role": "user", "content": "please stop soon"}]


def test_agent_loop_does_not_execute_tool_when_interrupted_before_tool_call():
    history = []
    interrupt_event = threading.Event()
    tool_loader = FakeToolLoader()
    loop = AgentLoop(
        llm=EventSettingLLM(interrupt_event),
        tools=[{"type": "function", "function": {"name": "bash"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
        interrupt_event=interrupt_event,
    )

    result = loop.run("run a tool")

    assert result == "[用户中断] 已停止当前任务。"
    assert tool_loader.calls == []
    assert history[-1]["content"] == "[用户中断] 此工具调用未执行"


def test_agent_loop_stops_after_tool_reports_interrupted():
    history = []
    interrupt_event = threading.Event()
    tool_loader = InterruptingToolLoader(interrupt_event)
    loop = AgentLoop(
        llm=FakeLLM(first_message=FakeMessage(content="", tool_calls=[FakeToolCall("call-1", "bash", '{"command": "sleep 60"}')])),
        tools=[{"type": "function", "function": {"name": "bash"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
        interrupt_event=interrupt_event,
    )

    result = loop.run("run a long command")

    assert result == "[用户中断] 已停止当前任务。"
    assert tool_loader.calls == [("bash", {"command": "sleep 60"})]
    assert '"interrupted": true' in history[-1]["content"]


def test_agent_loop_returns_promptly_when_tool_wait_is_interrupted():
    history = []
    interrupt_event = threading.Event()
    tool_loader = BlockingToolLoader(delay=1.0)

    def start_interrupt_listener():
        timer = threading.Timer(0.05, interrupt_event.set)
        timer.daemon = True
        timer.start()
        return timer

    loop = AgentLoop(
        llm=FakeLLM(first_message=FakeMessage(content="", tool_calls=[FakeToolCall("call-1", "mcp__search", '{"query": "agent"}')])),
        tools=[{"type": "function", "function": {"name": "mcp__search"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
        interrupt_event=interrupt_event,
        start_interrupt_listener=start_interrupt_listener,
    )

    started_at = time.monotonic()
    result = loop.run("run a blocking tool")

    assert result == "[用户中断] 已停止当前任务。"
    assert time.monotonic() - started_at < 0.5
    assert tool_loader.calls == [("mcp__search", {"query": "agent"})]
    assert history[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "[用户中断] 此工具调用未执行",
    }


def test_agent_loop_fills_missing_tool_results_before_llm_call():
    history = [
        {"role": "user", "content": "research"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "fetch", "arguments": '{"url": "https://a.example"}'},
                },
                {
                    "id": "call-2",
                    "type": "function",
                    "function": {"name": "fetch", "arguments": '{"url": "https://b.example"}'},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "first result"},
    ]
    llm = FakeLLM(first_message=FakeMessage(content="done", tool_calls=[]))
    loop = AgentLoop(
        llm=llm,
        tools=[],
        tool_loader=FakeToolLoader(),
        history=history,
        system_prompt="system prompt",
        max_turns=1,
    )

    result = loop.run("continue")

    assert result == "done"
    assert history[3] == {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": "[用户中断] 此工具调用未执行",
    }
    assert history[4] == {"role": "user", "content": "continue"}
    assert llm.messages_seen[0][4]["tool_call_id"] == "call-2"


def test_agent_loop_fills_remaining_tool_results_when_interrupted_mid_batch():
    history = []
    interrupt_event = threading.Event()
    tool_loader = CountingToolLoader(interrupt_event)
    loop = AgentLoop(
        llm=FakeLLM(
            first_message=FakeMessage(
                content="",
                tool_calls=[
                    FakeToolCall("call-1", "bash", '{"command": "one"}'),
                    FakeToolCall("call-2", "bash", '{"command": "two"}'),
                ],
            )
        ),
        tools=[{"type": "function", "function": {"name": "bash"}}],
        tool_loader=tool_loader,
        history=history,
        system_prompt="system prompt",
        max_turns=3,
        interrupt_event=interrupt_event,
    )

    result = loop.run("run tools")

    assert result == "[用户中断] 已停止当前任务。"
    assert tool_loader.calls == [("bash", {"command": "one"})]
    assert history[-1] == {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": "[用户中断] 此工具调用未执行",
    }


def test_agent_loop_drops_orphan_tool_results_before_llm_call():
    history = [
        {"role": "user", "content": "old question"},
        {"role": "tool", "tool_call_id": "orphan-call", "content": "orphan result"},
        {"role": "assistant", "content": "old answer"},
    ]
    llm = FakeLLM(first_message=FakeMessage(content="done", tool_calls=[]))
    loop = AgentLoop(
        llm=llm,
        tools=[],
        tool_loader=FakeToolLoader(),
        history=history,
        system_prompt="system prompt",
        max_turns=1,
    )

    result = loop.run("continue")

    assert result == "done"
    sent_roles = [message["role"] for message in llm.messages_seen[0]]
    assert sent_roles == ["system", "user", "assistant", "user"]
    assert all(message.get("tool_call_id") != "orphan-call" for message in llm.messages_seen[0])
