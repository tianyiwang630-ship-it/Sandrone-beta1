"""Canonical pre/post-message validation for the agent loop."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from agent.core.message_history import INTERRUPTED_TOOL_RESULT, sanitize_tool_history


SUMMARY_KIND = "compaction_summary"
UNKNOWN_TOOL_RESULT = "[系统恢复] 工具执行结果未知，请先检查目标状态，勿直接重复执行"
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_VALID_ROLES = {"system", "user", "assistant", "tool"}


@dataclass(slots=True)
class HistoryPreparationResult:
    history: list[dict[str, Any]]
    provider_messages: list[dict[str, Any]]
    repairs: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


@dataclass(slots=True)
class AssistantValidationResult:
    message: dict[str, Any] | None
    repairs: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.message is not None and self.error is None


def prepare_runtime_history(
    history: Iterable[dict[str, Any]],
    *,
    request_id: str = "runtime",
    provider: str = "",
    uncertain_tool_call_ids: set[str] | None = None,
) -> HistoryPreparationResult:
    """Repair persisted runtime history and project it to provider-safe messages."""
    repairs: list[str] = []
    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    id_queues: dict[str, list[str]] = {}
    uncertain = uncertain_tool_call_ids or set()

    for message_index, raw in enumerate(history):
        if not isinstance(raw, dict):
            repairs.append("drop_non_object_message")
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in _VALID_ROLES:
            repairs.append("drop_unknown_role")
            continue

        if role == "tool":
            old_id = str(raw.get("tool_call_id") or "")
            queue = id_queues.get(old_id)
            tool_call_id = queue.pop(0) if queue else old_id
            content = _normalize_content(raw.get("content"))
            if not tool_call_id or content is None:
                repairs.append("drop_invalid_tool_result")
                continue
            item = {"role": "tool", "tool_call_id": tool_call_id, "content": content}
            normalized.append(item)
            if tool_call_id != old_id:
                repairs.append("repair_tool_result_id")
            continue

        content = _normalize_content(raw.get("content"))
        item: dict[str, Any] = {"role": role, "content": content}
        for key in ("_message_id", "_sender_id", "_source"):
            if key in raw:
                item[key] = raw[key]
        runtime_kind = raw.get("_runtime_kind")
        if runtime_kind:
            item["_runtime_kind"] = str(runtime_kind)

        if role == "assistant":
            tool_calls = raw.get("tool_calls")
            repaired_calls: list[dict[str, Any]] = []
            if isinstance(tool_calls, list):
                for call_index, tool_call in enumerate(tool_calls):
                    repaired = _repair_tool_call(
                        tool_call,
                        request_id=request_id,
                        message_index=message_index,
                        call_index=call_index,
                        used_ids=used_ids,
                        id_queues=id_queues,
                        repairs=repairs,
                        require_parseable_arguments=False,
                    )
                    if repaired is not None:
                        repaired_calls.append(repaired)
            if repaired_calls:
                item["tool_calls"] = repaired_calls
                reasoning = _normalize_content(raw.get("reasoning_content"))
                if reasoning is not None:
                    item["reasoning_content"] = reasoning
            elif content is None:
                repairs.append("drop_empty_assistant")
                continue
        elif content is None:
            repairs.append("drop_empty_message")
            continue

        normalized.append(item)

    sanitized = sanitize_tool_history(normalized, interrupted_tool_result=INTERRUPTED_TOOL_RESULT)
    if sanitized != normalized:
        repairs.append("repair_tool_history")
    for message in sanitized:
        if message.get("role") != "tool":
            continue
        tool_call_id = str(message.get("tool_call_id") or "")
        if tool_call_id in uncertain and message.get("content") == INTERRUPTED_TOOL_RESULT:
            message["content"] = UNKNOWN_TOOL_RESULT

    return HistoryPreparationResult(
        history=[dict(message) for message in sanitized],
        provider_messages=project_provider_messages(sanitized, provider=provider),
        repairs=_dedupe(repairs),
    )


def validate_assistant_message(
    raw_message: Any,
    *,
    tools: list[dict[str, Any]],
    request_id: str,
    finish_reason: str | None = None,
) -> AssistantValidationResult:
    """Normalize one provider assistant response without guessing intent."""
    repairs: list[str] = []
    content = _normalize_content(_get(raw_message, "content"))
    raw_tool_calls = _get(raw_message, "tool_calls") or []
    if not isinstance(raw_tool_calls, (list, tuple)):
        return AssistantValidationResult(None, error="tool_calls must be a list")

    used_ids: set[str] = set()
    id_queues: dict[str, list[str]] = {}
    tool_calls: list[dict[str, Any]] = []
    for call_index, tool_call in enumerate(raw_tool_calls):
        repaired = _repair_tool_call(
            tool_call,
            request_id=request_id,
            message_index=0,
            call_index=call_index,
            used_ids=used_ids,
            id_queues=id_queues,
            repairs=repairs,
            require_parseable_arguments=True,
        )
        if repaired is None:
            return AssistantValidationResult(None, repairs=_dedupe(repairs), error="invalid tool call")
        schema_error = _validate_tool_schema(repaired, tools)
        if schema_error:
            return AssistantValidationResult(None, repairs=_dedupe(repairs), error=schema_error)
        tool_calls.append(repaired)

    if finish_reason == "length" and tool_calls:
        return AssistantValidationResult(None, repairs=_dedupe(repairs), error="tool call output was truncated")
    if content is None and not tool_calls:
        return AssistantValidationResult(None, repairs=_dedupe(repairs), error="assistant response is empty")

    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    reasoning = _normalize_content(_get(raw_message, "reasoning_content"))
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return AssistantValidationResult(message, repairs=_dedupe(repairs))


def project_provider_messages(history: Iterable[dict[str, Any]], *, provider: str = "") -> list[dict[str, Any]]:
    """Strip internal fields before sending messages to a provider."""
    include_reasoning = "deepseek" in provider.lower()
    projected: list[dict[str, Any]] = []
    for message in history:
        role = message.get("role")
        if role in {"system", "user"}:
            projected.append({"role": role, "content": message.get("content")})
        elif role == "assistant":
            item = {"role": "assistant", "content": message.get("content")}
            if message.get("tool_calls"):
                item["tool_calls"] = message["tool_calls"]
            if include_reasoning and message.get("reasoning_content") is not None:
                item["reasoning_content"] = message["reasoning_content"]
            projected.append(item)
        elif role == "tool":
            projected.append(
                {
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id"),
                    "content": message.get("content"),
                }
            )
    return projected


def _repair_tool_call(
    raw: Any,
    *,
    request_id: str,
    message_index: int,
    call_index: int,
    used_ids: set[str],
    id_queues: dict[str, list[str]],
    repairs: list[str],
    require_parseable_arguments: bool,
) -> dict[str, Any] | None:
    function = _get(raw, "function")
    if function is None:
        return None
    name = str(_get(function, "name") or "").strip()
    if not name:
        return None

    arguments, repaired_arguments = _normalize_arguments(_get(function, "arguments"))
    if arguments is None and require_parseable_arguments:
        return None
    if arguments is None:
        value = _get(function, "arguments")
        arguments = value if isinstance(value, str) else "{}"
    if repaired_arguments:
        repairs.append("repair_tool_arguments")

    old_id = str(_get(raw, "id") or "").strip()
    tool_call_id = old_id
    if not tool_call_id or tool_call_id in used_ids:
        prefix = re.sub(r"[^A-Za-z0-9_-]", "", request_id)[:12] or "runtime"
        tool_call_id = f"call_repaired_{prefix}_{message_index}_{call_index}"
        repairs.append("repair_tool_call_id")
    used_ids.add(tool_call_id)
    id_queues.setdefault(old_id, []).append(tool_call_id)

    call_type = str(_get(raw, "type") or "").strip()
    if not call_type:
        call_type = "function"
        repairs.append("repair_tool_call_type")
    if call_type != "function":
        return None
    return {
        "id": tool_call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _normalize_arguments(value: Any) -> tuple[str | None, bool]:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False), True
    if not isinstance(value, str):
        return None, False
    text = value.strip()
    match = _JSON_FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None, bool(match)
    if not isinstance(parsed, dict):
        return None, bool(match)
    normalized = json.dumps(parsed, ensure_ascii=False)
    return normalized, bool(match) or normalized != value


def _validate_tool_schema(tool_call: dict[str, Any], tools: list[dict[str, Any]]) -> str | None:
    function = tool_call["function"]
    tool = next(
        (
            item
            for item in tools
            if isinstance(item, dict)
            and isinstance(item.get("function"), dict)
            and item["function"].get("name") == function["name"]
        ),
        None,
    )
    if tool is None:
        return None
    arguments = json.loads(function["arguments"])
    schema = tool["function"].get("parameters") or {}
    required = schema.get("required") or []
    missing = [name for name in required if name not in arguments]
    if missing:
        return f"tool {function['name']} is missing required arguments: {', '.join(missing)}"
    properties = schema.get("properties") or {}
    for name, value in arguments.items():
        expected = properties.get(name, {}).get("type")
        if expected and not _matches_json_type(value, expected):
            return f"tool {function['name']} argument {name} must be {expected}"
    return None


def _matches_json_type(value: Any, expected: str) -> bool:
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
        "null": lambda item: item is None,
    }
    return checks.get(expected, lambda _item: True)(value)


def _normalize_content(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (bool, int, float)):
        return str(value)
    return None


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
