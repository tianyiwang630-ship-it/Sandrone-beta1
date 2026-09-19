"""
Agent loop extraction for multi-turn tool execution.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAIError

from agent.core.config import LLM_MAX_TOKENS
from agent.core.message_history import collect_recent_complete_groups, sanitize_tool_history
from agent.core.message_pipeline import UNKNOWN_TOOL_RESULT, prepare_runtime_history, validate_assistant_message
from agent.core.session_events import SessionEventWriter, truncate_tool_result
from agent.core.realtime_log import RealtimeLogWriter
from agent.errors import LLMInterrupted, LLMInvalidResponse


class AgentLoop:
    """Run the agent message loop while reusing the caller's history list."""

    INTERRUPTED_TOOL_RESULT = "[用户中断] 此工具调用未执行"
    INTERRUPTED_RESPONSE = "[用户中断] 已停止当前任务。"
    RECOVERABLE_RESPONSE = "当前模型请求未能完成，已保护本轮消息和工具现场。网络或配置恢复后可直接继续。"
    TOOL_WAIT_INTERRUPTED = object()
    SLOW_CONNECTION_RECOVERY_SECONDS = 120.0
    SLOW_CONNECTION_ERROR_TYPES = {"APIConnectionError", "APITimeoutError"}
    SLOW_CONNECTION_RECOVERY_PROMPT = (
        "[系统恢复提示] 上一次模型请求在长时间等待后连接失败。"
        "请把接下来的回答或文件修改拆成小批次完成："
        "每次只输出/调用工具处理一小段内容，完成后再继续下一批，避免单次生成过长。"
    )
    INVALID_RESPONSE_RECOVERY_PROMPT = (
        "[临时恢复提示] 上一次模型返回的 assistant 消息结构无效。"
        "请重新生成本轮回复：必须返回非空正文，或返回字段完整且参数为有效 JSON 对象的 tool_calls。"
    )

    def __init__(
        self,
        *,
        llm,
        tools: List[Dict[str, Any]],
        tool_loader,
        history: List[Dict[str, Any]],
        system_prompt: str,
        max_turns: int,
        max_tool_result_chars: int = 12000,
        event_writer: SessionEventWriter | None = None,
        log_writer: RealtimeLogWriter | None = None,
        interrupt_event: Optional[threading.Event] = None,
        start_interrupt_listener: Optional[Callable[[], Any]] = None,
        request_id: str = "runtime",
        input_provider: Callable[[], list[dict[str, Any]]] | None = None,
        checkpoint: Callable[[list[dict[str, Any]]], None] | None = None,
    ):
        self.llm = llm
        self.tools = tools
        self.tool_loader = tool_loader
        self.history = history
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.max_tool_result_chars = max_tool_result_chars
        self.event_writer = event_writer
        self.log_writer = log_writer
        self._interrupted = interrupt_event or threading.Event()
        self._start_interrupt_listener = start_interrupt_listener
        self.request_id = request_id
        self.input_provider = input_provider
        self.checkpoint = checkpoint
        self._llm_recovery_prompt_injected = False
        self.was_interrupted = False
        self.was_recoverable = False
        self.recovery_stage: str | None = None
        self.recovery_error: str | None = None

    def run(self, user_input: str, *, input_entry: dict[str, Any] | None = None) -> str:
        """Execute the multi-turn loop for one user input."""
        self.was_interrupted = False
        self.was_recoverable = False
        self.recovery_stage = None
        self.recovery_error = None
        self._fill_missing_tool_results()
        self._append_history_entry(input_entry or {"role": "user", "content": user_input})

        if self._start_interrupt_listener:
            self._start_interrupt_listener()

        try:
            for _ in range(self.max_turns):
                if self._interrupted.is_set():
                    break

                self._receive_inputs()
                messages = self._build_messages()
                try:
                    choice = self._call_llm_with_recovery(messages)
                except (OpenAIError, LLMInvalidResponse) as exc:
                    self.was_recoverable = True
                    self.recovery_stage = "exhausted"
                    self.recovery_error = str(exc) or type(exc).__name__
                    self._write_event(
                        "run_recoverable",
                        {
                            "recovery_stage": self.recovery_stage,
                            "error_type": type(exc).__name__,
                            "error_message": self.recovery_error,
                        },
                    )
                    return self.RECOVERABLE_RESPONSE
                if choice is None:
                    break
                message = choice.message

                if getattr(message, "tool_calls", None):
                    self._handle_tool_calls(
                        message,
                        output_truncated=getattr(choice, "finish_reason", None) == "length",
                    )
                    if self._interrupted.is_set():
                        break
                    continue

                self._append_history_entry({"role": "assistant", "content": message.content})
                if self._receive_inputs():
                    continue
                return message.content

            if self._interrupted.is_set():
                self.was_interrupted = True
                return self.INTERRUPTED_RESPONSE
            return "抱歉，任务太复杂，已达到最大处理轮次。"
        finally:
            self._interrupted.set()

    def _call_llm(self, messages: List[Dict[str, Any]]) -> Any:
        if self.log_writer is not None:
            self.log_writer.write_event(
                "llm_input",
                {"messages": messages, "tool_count": len(self.tools)},
                request_id=self.request_id,
            )
        previous_callback = getattr(self.llm, "event_callback", None)
        self._llm_recovery_prompt_injected = False
        try:
            setattr(self.llm, "event_callback", self._handle_llm_diagnostic_event)
            response = self.llm.generate_with_tools(messages=messages, tools=self.tools)
        finally:
            setattr(self.llm, "event_callback", previous_callback)
        choice = response.choices[0]
        message = choice.message

        validation = validate_assistant_message(
            message,
            tools=self.tools,
            request_id=self.request_id,
            finish_reason=getattr(choice, "finish_reason", None),
        )
        if not validation.valid:
            self._write_event(
                "assistant_message_rejected",
                {
                    "error": validation.error,
                    "repairs": validation.repairs,
                    "finish_reason": getattr(choice, "finish_reason", None),
                },
            )
            raise LLMInvalidResponse(
                validation.error or "assistant response is invalid",
                finish_reason=getattr(choice, "finish_reason", None),
            )
        if validation.repairs:
            self._write_event(
                "assistant_message_repaired",
                {"repairs": validation.repairs},
            )
        normalized = validation.message or {}
        message = SimpleNamespace(
            content=normalized.get("content"),
            reasoning_content=normalized.get("reasoning_content"),
            tool_calls=[
                SimpleNamespace(
                    id=call["id"],
                    type=call["type"],
                    function=SimpleNamespace(**call["function"]),
                )
                for call in normalized.get("tool_calls", [])
            ],
        )
        choice = SimpleNamespace(message=message, finish_reason=getattr(choice, "finish_reason", None))

        if self.log_writer is not None:
            self.log_writer.write_event(
                "llm_response",
                {
                    "content": message.content,
                    "reasoning_content": message.reasoning_content,
                    "tool_calls": normalized.get("tool_calls", []),
                    "finish_reason": getattr(choice, "finish_reason", None),
                },
                request_id=self.request_id,
            )

        if hasattr(message, "tool_calls") and message.tool_calls:
            debug_mode = os.environ.get("DEBUG_AGENT", "0") == "1"
            if debug_mode:
                debug_file = Path("workspace/temp/last_llm_response.json")
                debug_file.parent.mkdir(parents=True, exist_ok=True)
                debug_data = {
                    "content": message.content,
                    "tool_calls": [
                        {
                            "name": tc.function.name,
                            "arguments_raw": tc.function.arguments,
                        }
                        for tc in message.tool_calls
                    ],
                }
                debug_file.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")

        return choice

    def _call_llm_with_recovery(self, messages: List[Dict[str, Any]]) -> Any:
        attempts = [
            ("normal", messages),
            ("corrected", self._with_recovery_instruction(messages)),
            ("degraded", self._build_degraded_messages()),
        ]
        last_error: Exception | None = None
        for stage, attempt_messages in attempts:
            if stage != "normal":
                refresh = getattr(self.llm, "refresh_client", None)
                if refresh is not None:
                    refresh()
                self._write_event("agent_recovery_started", {"recovery_stage": stage})
            try:
                return self._call_llm_interruptible(attempt_messages)
            except (OpenAIError, LLMInvalidResponse) as exc:
                last_error = exc
                self._write_event(
                    "agent_recovery_attempt_failed",
                    {
                        "recovery_stage": stage,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc) or type(exc).__name__,
                    },
                )
                if type(exc).__name__ in {"AuthenticationError", "PermissionDeniedError"}:
                    break
        if last_error is None:
            raise LLMInvalidResponse("LLM recovery exited without a response")
        raise last_error

    def _with_recovery_instruction(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not messages:
            return [{"role": "system", "content": self.INVALID_RESPONSE_RECOVERY_PROMPT}]
        return [messages[0], {"role": "system", "content": self.INVALID_RESPONSE_RECOVERY_PROMPT}, *messages[1:]]

    def _build_degraded_messages(self) -> List[Dict[str, Any]]:
        recent = collect_recent_complete_groups(self.history, max_groups=6)
        prepared = prepare_runtime_history(
            recent,
            request_id=self.request_id,
            provider=str(getattr(getattr(self.llm, "profile", None), "provider", "")),
        )
        return self._with_recovery_instruction(
            [{"role": "system", "content": self.system_prompt}, *prepared.provider_messages]
        )

    def _handle_llm_diagnostic_event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(event.get("type") or "")
        payload = {"request_id": self.request_id, **{key: value for key, value in event.items() if key != "type"}}
        if self.event_writer is not None and event_type:
            self.event_writer.write_event(event_type, payload)
        if self.log_writer is not None and event_type:
            self.log_writer.write_event(event_type, payload, request_id=self.request_id)

        if not self._should_inject_slow_connection_recovery(event):
            return None

        self._llm_recovery_prompt_injected = True
        self._append_history_entry(
            {"role": "user", "content": self.SLOW_CONNECTION_RECOVERY_PROMPT},
            llm_recovery_prompt=True,
        )
        return {
            "retry_messages": self._build_messages(),
            "slow_connection_recovery_injected": True,
        }

    def _should_inject_slow_connection_recovery(self, event: dict[str, Any]) -> bool:
        if self._llm_recovery_prompt_injected:
            return False
        if event.get("type") != "llm_request_failed":
            return False
        if event.get("attempt") != 1:
            return False
        if event.get("error_type") not in self.SLOW_CONNECTION_ERROR_TYPES:
            return False
        try:
            elapsed_seconds = float(event.get("elapsed_seconds") or 0)
        except (TypeError, ValueError):
            elapsed_seconds = 0.0
        if elapsed_seconds < self.SLOW_CONNECTION_RECOVERY_SECONDS:
            return False
        if int(event.get("max_attempts") or 0) <= int(event.get("attempt") or 0):
            return False
        return True

    def _record_output_truncation(self, tool_call) -> None:
        if self.event_writer is None:
            return
        profile = getattr(self.llm, "profile", None)
        self.event_writer.write_event(
            "llm_output_truncated",
            {
                "profile": getattr(profile, "name", "unknown"),
                "max_tokens": self._output_token_limit(),
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.function.name,
            },
        )

    def _output_token_limit(self) -> int:
        configured = getattr(getattr(self.llm, "profile", None), "max_tokens", None)
        return configured if configured is not None else LLM_MAX_TOKENS

    def _call_llm_interruptible(self, messages: List[Dict[str, Any]]) -> Any:
        result: List[Any] = [None]
        error: List[Optional[Exception]] = [None]

        def call():
            try:
                result[0] = self._call_llm(messages)
            except LLMInterrupted as exc:
                error[0] = exc
            except Exception as exc:  # pragma: no cover - passthrough branch
                error[0] = exc

        thread = threading.Thread(target=call, daemon=True)
        thread.start()

        while thread.is_alive():
            thread.join(timeout=0.1)
            if self._interrupted.is_set():
                cancel = getattr(self.llm, "cancel_current_request", None)
                if cancel is not None:
                    cancel()
                return None

        if error[0]:
            if isinstance(error[0], LLMInterrupted):
                self._interrupted.set()
                return None
            raise error[0]
        return result[0]

    def _handle_tool_calls(self, message, *, output_truncated: bool = False) -> None:
        assistant_message = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ],
        }
        reasoning_content = getattr(message, "reasoning_content", None)
        if self._is_deepseek_provider() and reasoning_content is not None:
            assistant_message["reasoning_content"] = reasoning_content

        self._append_history_entry(assistant_message)

        for index, tool_call in enumerate(message.tool_calls):
            if self._interrupted.is_set():
                self._append_history_entry(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self.INTERRUPTED_TOOL_RESULT,
                    }
                )
                continue

            self._write_event(
                "tool_execution_started",
                {"tool_call_id": tool_call.id, "tool_name": tool_call.function.name},
            )
            result = self._execute_single_tool_interruptible(
                tool_call,
                output_truncated=output_truncated,
            )
            if result is self.TOOL_WAIT_INTERRUPTED:
                self._append_history_entry(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": UNKNOWN_TOOL_RESULT,
                    }
                )
                self._write_event(
                    "tool_execution_uncertain",
                    {"tool_call_id": tool_call.id, "tool_name": tool_call.function.name},
                )
                self._append_interrupted_tool_results(message.tool_calls[index + 1 :])
                break

            if isinstance(result, dict) and "retry_with_context" in result:
                extra_instruction = result["retry_with_context"]
                if self.history and self.history[-1]["role"] == "assistant":
                    self.history.pop()
                self._append_history_entry({"role": "user", "content": f"[补充说明] {extra_instruction}"})
                break

            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
            result_str = re.sub(r"\x1b\[[0-9;]*m", "", result_str)
            if self.log_writer is not None:
                self.log_writer.write_entry(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    },
                    request_id=self.request_id,
                    raw_tool_result=True,
                )
            result_str, event_metadata = truncate_tool_result(
                result_str,
                max_chars=self.max_tool_result_chars,
                tool_name=tool_call.function.name,
            )

            self._append_history_entry(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                },
                **event_metadata,
                write_log=False,
            )
            self._write_event(
                "tool_execution_completed",
                {
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.function.name,
                    "success": not (isinstance(result, dict) and result.get("success") is False),
                },
            )
            if self._interrupted.is_set():
                self._append_interrupted_tool_results(message.tool_calls[index + 1 :])
                break

    def _execute_single_tool(self, tool_call, *, output_truncated: bool = False) -> Any:
        tool_name = tool_call.function.name
        raw_arguments = tool_call.function.arguments

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            if output_truncated:
                self._record_output_truncation(tool_call)
            return {
                "success": False,
                "error": "tool call 参数不是有效 JSON 对象，未执行该工具。",
                "tool": tool_name,
                "truncated": output_truncated,
                "guidance": "请重新生成字段完整的工具调用；不要猜测或省略必填参数。",
            }

        if not isinstance(arguments, dict):
            return {
                "success": False,
                "error": "tool call 参数必须是 JSON 对象，未执行该工具。",
                "tool": tool_name,
            }

        return self.tool_loader.execute_tool(tool_name, arguments)

    def _execute_single_tool_interruptible(self, tool_call, *, output_truncated: bool = False) -> Any:
        result: List[Any] = [None]
        error: List[Optional[Exception]] = [None]

        def call():
            try:
                result[0] = self._execute_single_tool(
                    tool_call,
                    output_truncated=output_truncated,
                )
            except Exception as exc:  # pragma: no cover - passthrough branch
                error[0] = exc

        thread = threading.Thread(target=call, daemon=True)
        thread.start()

        while thread.is_alive():
            thread.join(timeout=0.1)
            if self._interrupted.is_set():
                return self.TOOL_WAIT_INTERRUPTED

        if error[0]:
            error_message = str(error[0]) or type(error[0]).__name__
            return {
                "success": False,
                "error": error_message,
                "error_type": type(error[0]).__name__,
                "tool": tool_call.function.name,
            }
        return result[0]

    def _is_deepseek_provider(self) -> bool:
        profile = getattr(self.llm, "profile", None)
        provider = getattr(profile, "provider", "")
        return "deepseek" in str(provider).lower()

    def _build_messages(self) -> List[Dict[str, Any]]:
        prepared = prepare_runtime_history(
            self.history,
            request_id=self.request_id,
            provider=str(getattr(getattr(self.llm, "profile", None), "provider", "")),
        )
        if prepared.changed:
            self.history[:] = prepared.history
            self._write_event("runtime_history_repaired", {"repairs": prepared.repairs})
        return [{"role": "system", "content": self.system_prompt}, *prepared.provider_messages]

    def _write_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_writer is not None:
            self.event_writer.write_event(event_type, {"request_id": self.request_id, **payload})
        if self.log_writer is not None:
            self.log_writer.write_event(event_type, payload, request_id=self.request_id)

    def _append_history_entry(self, entry: dict[str, Any], *, write_log: bool = True, **event_metadata: Any) -> None:
        self.history.append(entry)
        if write_log and self.log_writer is not None:
            self.log_writer.write_entry(entry, request_id=self.request_id)
        if self.event_writer is not None:
            event_metadata.setdefault("request_id", self.request_id)
            self.event_writer.write(entry, **event_metadata)
        if self.checkpoint is not None:
            self.checkpoint(self.history)

    def _receive_inputs(self) -> bool:
        """Admit steering only between complete model/tool exchanges."""
        entries = self.input_provider() if self.input_provider else []
        for entry in entries:
            self._append_history_entry(entry)
        return bool(entries)

    def _insert_history_entry(self, index: int, entry: dict[str, Any], **event_metadata: Any) -> None:
        self.history.insert(index, entry)
        if self.log_writer is not None:
            self.log_writer.write_entry(entry, request_id=self.request_id)
        if self.event_writer is not None:
            event_metadata.setdefault("request_id", self.request_id)
            self.event_writer.write(entry, **event_metadata)

    def _fill_missing_tool_results(self) -> None:
        """Keep OpenAI tool-call history valid after interrupted sessions."""
        index = 0
        while index < len(self.history):
            message = self.history[index]
            tool_calls = message.get("tool_calls") if message.get("role") == "assistant" else None
            if not tool_calls:
                index += 1
                continue

            expected_ids = [tool_call.get("id") for tool_call in tool_calls if tool_call.get("id")]
            seen_ids = set()
            insert_at = index + 1
            while insert_at < len(self.history) and self.history[insert_at].get("role") == "tool":
                tool_call_id = self.history[insert_at].get("tool_call_id")
                if tool_call_id in expected_ids:
                    seen_ids.add(tool_call_id)
                insert_at += 1

            missing_ids = [tool_call_id for tool_call_id in expected_ids if tool_call_id not in seen_ids]
            for offset, tool_call_id in enumerate(missing_ids):
                self._insert_history_entry(
                    insert_at + offset,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": self.INTERRUPTED_TOOL_RESULT,
                    },
                )
            index = insert_at + len(missing_ids)

    def _append_interrupted_tool_results(self, tool_calls) -> None:
        for tool_call in tool_calls:
            self._append_history_entry(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": self.INTERRUPTED_TOOL_RESULT,
                }
            )

    def _drop_orphan_tool_results(self) -> None:
        sanitized = sanitize_tool_history(
            self.history,
            interrupted_tool_result=self.INTERRUPTED_TOOL_RESULT,
        )
        if sanitized != self.history:
            self.history[:] = sanitized
