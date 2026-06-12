"""
Helpers for keeping chat history valid around tool-call messages.
"""

from __future__ import annotations

from typing import Any, Callable


INTERRUPTED_TOOL_RESULT = "[用户中断] 此工具调用未执行"


def sanitize_tool_history(
    history: list[dict[str, Any]],
    *,
    interrupted_tool_result: str = INTERRUPTED_TOOL_RESULT,
) -> list[dict[str, Any]]:
    """Drop orphan tool results and fill missing tool results."""
    sanitized: list[dict[str, Any]] = []
    index = 0

    while index < len(history):
        message = history[index]

        if message.get("role") == "tool":
            index += 1
            continue

        sanitized.append(message)

        tool_calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if not tool_calls:
            index += 1
            continue

        expected_ids = [tool_call.get("id") for tool_call in tool_calls if tool_call.get("id")]
        seen_ids: set[str] = set()
        index += 1

        while index < len(history) and history[index].get("role") == "tool":
            tool_message = history[index]
            tool_call_id = tool_message.get("tool_call_id")
            if tool_call_id in expected_ids and tool_call_id not in seen_ids:
                sanitized.append(tool_message)
                seen_ids.add(tool_call_id)
            index += 1

        for tool_call_id in expected_ids:
            if tool_call_id not in seen_ids:
                sanitized.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": interrupted_tool_result,
                    }
                )

    return sanitized


def collect_recent_complete_groups(
    history: list[dict[str, Any]],
    *,
    max_groups: int | None = None,
    max_tokens: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
    count_message_tokens: Callable[[dict[str, Any]], int] | None = None,
    interrupted_tool_result: str = INTERRUPTED_TOOL_RESULT,
) -> list[dict[str, Any]]:
    """Collect recent history without splitting assistant tool-call groups."""
    sanitized = sanitize_tool_history(
        history,
        interrupted_tool_result=interrupted_tool_result,
    )
    groups = _group_history(sanitized)
    selected: list[list[dict[str, Any]]] = []
    running_tokens = 0

    for group in reversed(groups):
        if max_groups is not None and len(selected) >= max_groups:
            break

        group_tokens = _count_group_tokens(group, count_tokens, count_message_tokens)
        if max_tokens is not None and running_tokens + group_tokens > max_tokens:
            if selected:
                break
            if group_tokens > max_tokens:
                break

        selected.append(group)
        running_tokens += group_tokens

    selected.reverse()
    return [message for group in selected for message in group]


def _group_history(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(history):
        message = history[index]
        group = [message]
        index += 1

        tool_calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if tool_calls:
            expected_ids = {tool_call.get("id") for tool_call in tool_calls if tool_call.get("id")}
            while index < len(history) and history[index].get("role") == "tool":
                if history[index].get("tool_call_id") not in expected_ids:
                    break
                group.append(history[index])
                index += 1

        groups.append(group)
    return groups


def _count_group_tokens(
    group: list[dict[str, Any]],
    count_tokens: Callable[[str], int] | None,
    count_message_tokens: Callable[[dict[str, Any]], int] | None,
) -> int:
    if count_message_tokens is not None:
        return sum(count_message_tokens(message) for message in group)
    if count_tokens is None:
        return len(group)
    return sum(count_tokens(str(message.get("content", ""))) for message in group)
