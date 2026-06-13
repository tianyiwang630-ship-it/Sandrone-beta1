"""
上下文管理器 - 负责 token 计数和历史压缩
"""

import json
from dataclasses import dataclass
from typing import List, Dict, Any

import tiktoken

from agent.core.config import (
    MAX_CONTEXT_TOKENS,
    KEEP_RECENT_TURNS,
    COMPRESSION_THRESHOLD,
    COMPRESSION_INPUT_RATIO,
    TIKTOKEN_ENCODING,
    LLM_SUMMARY_MAX_TOKENS
)
from agent.core.message_history import collect_recent_complete_groups, sanitize_tool_history
from agent.core.session_events import truncate_tool_result


@dataclass(slots=True)
class ContextCompressionResult:
    trigger: str
    history: List[Dict]
    summary: str
    before_message_count: int
    after_message_count: int
    before_tokens: int
    after_tokens: int
    success: bool
    fallback: bool
    error: str | None = None

    @property
    def event_type(self) -> str:
        return "context_compacted" if self.success else "context_compaction_failed"

    def to_event(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "trigger": self.trigger,
            "summary": self.summary,
            "before_message_count": self.before_message_count,
            "after_message_count": self.after_message_count,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "success": self.success,
            "fallback": self.fallback,
            "error": self.error,
        }


class ContextManager:
    """上下文管理器 - 负责 token 计数和历史压缩"""

    def __init__(self, llm, tools: List[Dict], system_prompt: str,
                 max_context_tokens: int = MAX_CONTEXT_TOKENS,
                 keep_recent_turns: int = KEEP_RECENT_TURNS):
        """
        初始化上下文管理器

        Args:
            llm: LLMClient 实例（用于生成压缩摘要）
            tools: 工具定义列表
            system_prompt: 系统提示词
            max_context_tokens: 总上下文 token 限制
            keep_recent_turns: 压缩时保留最近 N 轮消息
        """
        self.llm = llm
        self.encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)

        self.max_context_tokens = max_context_tokens
        self.keep_recent_turns = keep_recent_turns
        self.compression_threshold = COMPRESSION_THRESHOLD

        # 计算固定成本
        self.system_tokens = self.count_tokens(system_prompt)
        self.tools_tokens = self._count_tools_tokens(tools)
        self.available_for_history = (
            self.max_context_tokens - self.system_tokens - self.tools_tokens
        )

        print(f"📊 上下文配置:")
        print(f"   - 总限制: {self.max_context_tokens:,} tokens")
        print(f"   - System: {self.system_tokens:,} tokens")
        print(f"   - Tools: {self.tools_tokens:,} tokens")
        print(f"   - History 可用: {self.available_for_history:,} tokens")

    # ============================================
    # 公开方法
    # ============================================

    def count_tokens(self, text: str) -> int:
        """
        计算文本的 token 数

        Args:
            text: 文本内容

        Returns:
            token 数量
        """
        if not text:
            return 0
        return len(self.encoding.encode(text))

    def count_history_tokens(self, history: List[Dict]) -> int:
        """
        计算 history 的 token 数

        Args:
            history: 对话历史

        Returns:
            history 的 token 数量
        """
        total = 0
        for msg in history:
            if msg.get("role") in ["user", "assistant", "tool"]:
                content = msg.get("content", "")
                if content:
                    total += self.count_tokens(content)

                # 如果 assistant 有 tool_calls，也计算
                if msg.get("tool_calls"):
                    tool_calls_json = json.dumps(msg["tool_calls"])
                    total += self.count_tokens(tool_calls_json)

        return total

    def should_compress(self, history: List[Dict]) -> bool:
        """
        检查是否需要压缩

        Args:
            history: 对话历史

        Returns:
            是否需要压缩
        """
        if len(history) <= self.keep_recent_turns:
            return False

        history_tokens = self.count_history_tokens(history)
        threshold = int(self.available_for_history * self.compression_threshold)
        should = history_tokens > threshold

        if should:
            print(f"\n⚠️  上下文即将超限: {history_tokens:,} / {threshold:,} tokens (阈值 {self.compression_threshold*100:.0f}%)")

        return should

    def compress_history(self, history: List[Dict]) -> List[Dict]:
        """
        压缩 history，返回新的 history 列表

        Args:
            history: 原始对话历史

        Returns:
            压缩后的新 history 列表
        """
        return self.compress_history_with_result(
            history,
            trigger="auto-threshold",
            allow_fallback=True,
        ).history

    def compress_history_with_result(
        self,
        history: List[Dict],
        *,
        trigger: str,
        allow_fallback: bool,
    ) -> ContextCompressionResult:
        """压缩 history，并返回可记录到日志的压缩结果。"""
        print("\n🗜️  开始压缩对话历史...")
        before_message_count = len(history)
        before_tokens = self.count_history_tokens(history)

        # 1. 分离旧对话和最近对话，保留完整 tool-call 消息组
        valid_history = sanitize_tool_history(history)
        recent_history = collect_recent_complete_groups(
            valid_history,
            max_groups=self.keep_recent_turns,
            count_message_tokens=self._count_history_message_tokens,
        )
        old_history = valid_history[: len(valid_history) - len(recent_history)]

        if not old_history:
            print("⚠️  没有需要压缩的历史")
            return ContextCompressionResult(
                trigger=trigger,
                history=history,
                summary="",
                before_message_count=before_message_count,
                after_message_count=len(history),
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                success=False,
                fallback=False,
                error="没有需要压缩的历史",
            )

        old_tokens = sum(
            self.count_tokens(msg.get("content", ""))
            for msg in old_history
            if msg.get("content")
        )

        print(f"   - 压缩前: {len(old_history)} 条消息, {old_tokens:,} tokens")

        # 2. 调用 LLM 生成压缩摘要文本
        try:
            summary_md = self._generate_summary(old_history)
            summary_tokens = self.count_tokens(summary_md)

            # 3. 重组 history
            new_history = [
                {
                    "role": "user",
                    "content": summary_md
                }
            ] + recent_history

            compression_ratio = (1 - summary_tokens / old_tokens) * 100 if old_tokens > 0 else 0

            print(f"   - 压缩后: 1 条摘要, {summary_tokens:,} tokens")
            print(f"   - 压缩率: {compression_ratio:.1f}%")
            print(f"✅ 压缩完成，保留最近 {self.keep_recent_turns} 组\n")

            return ContextCompressionResult(
                trigger=trigger,
                history=new_history,
                summary=summary_md,
                before_message_count=before_message_count,
                after_message_count=len(new_history),
                before_tokens=before_tokens,
                after_tokens=self.count_history_tokens(new_history),
                success=True,
                fallback=False,
                error=None,
            )

        except Exception as e:
            if not allow_fallback:
                print(f"❌ 压缩失败: {e}，历史未改变")
                return ContextCompressionResult(
                    trigger=trigger,
                    history=history,
                    summary="",
                    before_message_count=before_message_count,
                    after_message_count=len(history),
                    before_tokens=before_tokens,
                    after_tokens=before_tokens,
                    success=False,
                    fallback=False,
                    error=str(e),
                )

            print(f"❌ 压缩失败: {e}，压缩失败，已退回最近短上下文")
            fallback_target = int(self.available_for_history * self.compression_threshold * 0.3)
            fallback_history = collect_recent_complete_groups(
                history,
                max_tokens=fallback_target,
                count_message_tokens=self._count_history_message_tokens,
            )
            return ContextCompressionResult(
                trigger=trigger,
                history=fallback_history,
                summary="",
                before_message_count=before_message_count,
                after_message_count=len(fallback_history),
                before_tokens=before_tokens,
                after_tokens=self.count_history_tokens(fallback_history),
                success=False,
                fallback=True,
                error=str(e),
            )

    # ============================================
    # 私有方法
    # ============================================

    def _count_tools_tokens(self, tools: List[Dict]) -> int:
        """
        计算 tools 的 token 数

        Args:
            tools: 工具定义列表

        Returns:
            tools 的 token 数量
        """
        tools_json = json.dumps(tools)
        return self.count_tokens(tools_json)

    def _generate_summary(self, old_history: List[Dict]) -> str:
        """
        调用 LLM 生成压缩摘要

        Args:
            old_history: 需要压缩的历史消息

        Returns:
            压缩后的文本摘要
        """
        # 构建摘要提示词
        summary_prompt = """# 任务：将对话历史压缩为可继续工作的文本摘要

直接输出 Markdown 文本，不要输出 JSON，不要使用代码块。

请按以下结构组织：

## 任务时间线
- 只记录推进任务的关键步骤，保持因果链完整。

## 关键工具调用
- 只保留 write/edit/bash(非查询)/创建修改删除等会影响后续工作的工具调用。
- 忽略 ls/pwd/cat/read/git status 等普通查询。

## 重要文件
- 记录完整路径、创建/修改/删除状态。
- 省略临时文件，除非它对继续任务很关键。

## 当前状态
- 说明刚完成什么、被打断在做什么、下一步做什么、是否等待用户。

## 错误记忆
- 只记录有价值的错误、触发场景、纠正方式和教训。

## 关键用户意图
- 保留需求变更、新增要求、特定偏好等转折点。

---

## 压缩原则
1. 去重合并：相同操作合并为一条
2. 保持因果：删除无因果的中间步骤
3. 具体化：必须有具体文件名/路径/值
4. 面向恢复：确保能继续对话

请基于以下对话历史生成摘要，只输出摘要正文：

"""

        # 添加历史记录（转成纯文本 transcript，避免把 OpenAI tool role 结构传给摘要节点）
        history_text = self._history_to_transcript(old_history)
        max_summary_input = int(self.max_context_tokens * COMPRESSION_INPUT_RATIO)
        if self.count_tokens(history_text) > max_summary_input:
            kept = collect_recent_complete_groups(
                old_history,
                max_tokens=max_summary_input,
                count_message_tokens=self._count_transcript_message_tokens,
            )
            history_text = self._history_to_transcript(kept)
            print(f"   - 压缩输入已截断: 保留 {len(kept)}/{len(old_history)} 条消息")

        full_prompt = summary_prompt + "\n" + history_text

        # 调用 LLM
        print("   - 正在生成摘要...")
        response = self.llm.generate(full_prompt, max_tokens=LLM_SUMMARY_MAX_TOKENS)

        # 空响应检查
        if not response or not response.strip():
            raise ValueError("LLM 返回空响应，无法生成摘要")

        return response.strip()

    def _history_to_transcript(self, history: List[Dict]) -> str:
        lines = ["## 对话转写"]
        for index, message in enumerate(history, 1):
            lines.extend(self._message_to_transcript_lines(index, message))
        return "\n".join(lines)

    def _message_to_transcript_lines(self, index: int, message: Dict) -> list[str]:
        role = message.get("role", "unknown")
        content = str(message.get("content", "") or "")
        if role == "assistant" and message.get("tool_calls"):
            lines = [f"[{index}] assistant: {content}".rstrip()]
            for tool_call in message["tool_calls"]:
                function = tool_call.get("function", {})
                name = function.get("name", "unknown")
                arguments = function.get("arguments", "")
                arguments, _ = truncate_tool_result(arguments, max_chars=1000, max_lines=20)
                lines.append(
                    f"[{index}] assistant tool_call {name} id={tool_call.get('id', '')} arguments={arguments}"
                )
            return lines

        if role == "tool":
            content, _ = truncate_tool_result(content, max_chars=2000, max_lines=60)
            return [f"[{index}] tool result for {message.get('tool_call_id', '')}: {content}"]

        content, _ = truncate_tool_result(content, max_chars=3000, max_lines=80)
        return [f"[{index}] {role}: {content}"]

    def _count_history_message_tokens(self, message: Dict) -> int:
        total = self.count_tokens(str(message.get("content", "") or ""))
        if message.get("tool_calls"):
            total += self.count_tokens(json.dumps(message["tool_calls"], ensure_ascii=False))
        return total

    def _count_transcript_message_tokens(self, message: Dict) -> int:
        return self.count_tokens("\n".join(self._message_to_transcript_lines(0, message)))

