"""
Agent loop extraction for multi-turn tool execution.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.core.config import LLM_MAX_TOKENS
from agent.core.message_history import sanitize_tool_history
from agent.core.session_events import SessionEventWriter, truncate_tool_result


class AgentLoop:
    """Run the agent message loop while reusing the caller's history list."""

    INTERRUPTED_TOOL_RESULT = "[用户中断] 此工具调用未执行"
    TOOL_WAIT_INTERRUPTED = object()

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
        interrupt_event: Optional[threading.Event] = None,
        start_interrupt_listener: Optional[Callable[[], Any]] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.tool_loader = tool_loader
        self.history = history
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.max_tool_result_chars = max_tool_result_chars
        self.event_writer = event_writer
        self._interrupted = interrupt_event or threading.Event()
        self._start_interrupt_listener = start_interrupt_listener

    def run(self, user_input: str) -> str:
        """Execute the multi-turn loop for one user input."""
        self._fill_missing_tool_results()
        self._append_history_entry({"role": "user", "content": user_input})

        self._interrupted.clear()
        if self._start_interrupt_listener:
            self._start_interrupt_listener()

        try:
            for _ in range(self.max_turns):
                if self._interrupted.is_set():
                    break

                messages = self._build_messages()
                choice = self._call_llm_interruptible(messages)
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
                return message.content

            if self._interrupted.is_set():
                return "[用户中断] 已停止当前任务。"
            return "抱歉，任务太复杂，已达到最大处理轮次。"
        finally:
            self._interrupted.set()

    def _call_llm(self, messages: List[Dict[str, Any]]) -> Any:
        response = self.llm.generate_with_tools(messages=messages, tools=self.tools)
        choice = response.choices[0]
        message = choice.message

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
            except Exception as exc:  # pragma: no cover - passthrough branch
                error[0] = exc

        thread = threading.Thread(target=call, daemon=True)
        thread.start()

        while thread.is_alive():
            thread.join(timeout=0.1)
            if self._interrupted.is_set():
                return None

        if error[0]:
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

            result = self._execute_single_tool_interruptible(
                tool_call,
                output_truncated=output_truncated,
            )
            if result is self.TOOL_WAIT_INTERRUPTED:
                self._append_history_entry(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self.INTERRUPTED_TOOL_RESULT,
                    }
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
            try:
                arguments = json.loads(raw_arguments.replace("'", '"'))
            except Exception:
                if output_truncated:
                    self._record_output_truncation(tool_call)
                    return {
                        "success": False,
                        "error": "模型输出达到 Token 上限，tool call 参数被截断，未执行该工具。",
                        "tool": tool_name,
                        "truncated": True,
                        "guidance": "请缩短参数内容或拆成多个完整调用；大文件请使用 write 和 append 分批写入。",
                    }
                arguments = {}

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
            raise error[0]
        return result[0]

    def _is_deepseek_provider(self) -> bool:
        profile = getattr(self.llm, "profile", None)
        provider = getattr(profile, "provider", "")
        return "deepseek" in str(provider).lower()

    def _build_messages(self) -> List[Dict[str, Any]]:
        self._fill_missing_tool_results()
        self._drop_orphan_tool_results()
        return [{"role": "system", "content": self.system_prompt}, *self.history]

    def _append_history_entry(self, entry: dict[str, Any], **event_metadata: Any) -> None:
        self.history.append(entry)
        if self.event_writer is not None:
            self.event_writer.write(entry, **event_metadata)

    def _insert_history_entry(self, index: int, entry: dict[str, Any], **event_metadata: Any) -> None:
        self.history.insert(index, entry)
        if self.event_writer is not None:
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
