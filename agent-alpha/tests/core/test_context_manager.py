from agent.core.context_manager import ContextManager


class FailingLLM:
    def generate(self, _prompt, max_tokens=None):
        raise RuntimeError("summary network down")


class CountingLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, _prompt, max_tokens=None):
        self.calls += 1
        return "## 任务时间线\n- work\n\n## 当前状态\n- done\n\n## 关键用户意图\n- continue"


def test_auto_compaction_fallback_slims_recent_complete_tool_group():
    manager = ContextManager(
        llm=FailingLLM(),
        tools=[],
        system_prompt="system",
        max_context_tokens=1200,
        keep_recent_turns=1,
    )
    long_arguments = "ARG\n" * 2000
    long_tool_result = "RESULT\n" * 3000
    history = [
        {"role": "user", "content": "old context"},
        {
            "role": "assistant",
            "content": "preparing write",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "write", "arguments": long_arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": long_tool_result},
    ]

    result = manager.compress_history_with_result(
        history,
        trigger="auto-threshold",
        allow_fallback=True,
    )

    assert result.success is False
    assert result.fallback is True
    assert result.error == "summary network down"
    assert result.history[0]["role"] == "assistant"
    assert result.history[0]["tool_calls"][0]["id"] == "call_1"
    assert result.history[1]["role"] == "tool"
    assert result.history[1]["tool_call_id"] == "call_1"
    assert len(result.history[0]["tool_calls"][0]["function"]["arguments"]) <= 1000
    assert len(result.history[1]["content"]) <= 2000
    assert history[1]["tool_calls"][0]["function"]["arguments"] == long_arguments
    assert history[2]["content"] == long_tool_result


def test_manual_compaction_failure_does_not_fallback_or_change_history():
    manager = ContextManager(
        llm=FailingLLM(),
        tools=[],
        system_prompt="system",
        max_context_tokens=1200,
        keep_recent_turns=1,
    )
    history = [
        {"role": "user", "content": "old context"},
        {"role": "assistant", "content": "recent answer"},
    ]

    result = manager.compress_history_with_result(
        history,
        trigger="manual",
        allow_fallback=False,
    )

    assert result.success is False
    assert result.fallback is False
    assert result.history is history


def test_repeated_manual_compaction_skips_without_calling_llm_again():
    llm = CountingLLM()
    manager = ContextManager(
        llm=llm,
        tools=[],
        system_prompt="system",
        max_context_tokens=1200,
        keep_recent_turns=1,
    )
    history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
    ]

    first = manager.compress_history_with_result(history, trigger="manual", allow_fallback=False)
    second = manager.compress_history_with_result(first.history, trigger="manual", allow_fallback=False)

    assert first.outcome == "compacted"
    assert second.outcome == "skipped"
    assert second.history == first.history
    assert llm.calls == 1


def test_compaction_merges_existing_summary_only_when_new_old_history_exists():
    llm = CountingLLM()
    manager = ContextManager(
        llm=llm,
        tools=[],
        system_prompt="system",
        max_context_tokens=1200,
        keep_recent_turns=1,
    )
    history = [
        {
            "role": "user",
            "content": "## 任务时间线\n- old\n\n## 当前状态\n- old\n\n## 关键用户意图\n- old",
            "_runtime_kind": "compaction_summary",
        },
        {"role": "user", "content": "new old question"},
        {"role": "assistant", "content": "new old answer"},
        {"role": "user", "content": "recent"},
    ]

    result = manager.compress_history_with_result(history, trigger="manual", allow_fallback=False)

    assert result.outcome == "compacted"
    assert result.history[0]["_runtime_kind"] == "compaction_summary"
    assert llm.calls == 1
