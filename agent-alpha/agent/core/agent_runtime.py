"""
Primary agent runtime entrypoint.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

try:
    import msvcrt

    HAS_MSVCRT = True
except ImportError:  # pragma: no cover - platform specific
    HAS_MSVCRT = False

from agent.api.llm import LLMClient
from agent.core.agent_loop import AgentLoop
from agent.core.config import KEEP_RECENT_TURNS, MAX_CONTEXT_TOKENS, MAX_TOOL_RESULT_CHARS
from agent.core.context_manager import ContextManager
from agent.core.message_pipeline import prepare_runtime_history
from agent.core.realtime_log import RealtimeLogWriter
from agent.core.prompt_docs_loader import load_workspace_prompt_documents
from agent.core.role_config import RoleConfig
from agent.core.runtime_paths import apply_runtime_env
from agent.core.runtime_layout import APP_ROOT, PROJECT_ROOT
from agent.core.session_events import SessionEventWriter
from agent.core.runtime_types import RuntimeRequest, RuntimeResponse
from agent.core.skill_loader import SkillLoader
from agent.core.system_prompt_builder import build_system_prompt
from agent.core.tool_loader import ToolLoader


class AgentRuntime:
    """Reusable runtime for a single agent instance."""

    def __init__(
        self,
        max_turns: int = 10000,
        workspace_root: str | None = None,
        logs_dir: str | None = None,
        events_dir: str | None = None,
        session_created_at: str | None = None,
        task_id: str | None = None,
        llm_profile_name: str | None = None,
        llm_settings: dict[str, Any] | None = None,
        role_config: RoleConfig | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else PROJECT_ROOT.resolve()
        self.runtime_logs_dir = Path(logs_dir).resolve() if logs_dir else None
        self.runtime_events_dir = Path(events_dir).resolve() if events_dir else None
        self.session_created_at = session_created_at
        self.task_id = task_id
        self.llm_profile_name = llm_profile_name
        self.llm_settings = dict(llm_settings or {})
        self.role_config = role_config or RoleConfig()
        self.input_provider = None
        self.checkpoint = None

        apply_runtime_env(PROJECT_ROOT)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        self.llm = LLMClient.from_settings(self.llm_settings, llm_profile_name)
        self.skills_dir = APP_ROOT / "skills"
        self.agent_home_skills_dir = PROJECT_ROOT / "home" / ".agents" / "skills"
        self.skill_loader = SkillLoader(
            self.skills_dir,
            extra_skills_dirs=[self.agent_home_skills_dir],
        )
        self.tool_loader = ToolLoader(
            project_root=PROJECT_ROOT,
            app_root=APP_ROOT,
            skill_loader=self.skill_loader,
            workspace_root=self.workspace_root,
        )
        self.max_turns = max_turns
        self.history: List[Dict[str, Any]] = []
        self.runtime_events: List[Dict[str, Any]] = []
        self._interrupted = threading.Event()
        self.llm.set_interrupt_event(self._interrupted)
        self.tool_loader.set_interrupt_event(self._interrupted)

        print("Loading Agent Runtime...")
        self.tool_loader.load_all()
        self.tools = self.tool_loader.resolve_tools(self.role_config)
        self.tool_loader.configure_runtime(self.workspace_root)

        self.prompt_documents = load_workspace_prompt_documents(self.workspace_root)
        self.system_prompt = self._build_system_prompt()

        self.context_manager = ContextManager(
            llm=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            max_context_tokens=MAX_CONTEXT_TOKENS,
            keep_recent_turns=KEEP_RECENT_TURNS,
        )

    def _build_system_prompt(self) -> str:
        return build_system_prompt(
            workspace_root=self.workspace_root,
            logs_dir=self.runtime_logs_dir,
            events_dir=self.runtime_events_dir,
            skills_dir=self.skills_dir,
            agent_home_skills_dir=self.agent_home_skills_dir,
            mcp_servers_dir=APP_ROOT / "mcp-servers",
            mcp_registry_path=APP_ROOT / "mcp-servers" / "registry.json",
            data_root=PROJECT_ROOT,
            session_created_at=self.session_created_at,
            task_id=self.task_id,
            skill_summaries=self.skill_loader.get_summaries(),
            prompt_documents=self.prompt_documents,
        )

    def handle(self, request: str | RuntimeRequest) -> RuntimeResponse:
        runtime_request = request if isinstance(request, RuntimeRequest) else RuntimeRequest(content=request)

        event_writer = self._create_event_writer(runtime_request.session_id)
        log_writer = self._create_log_writer(runtime_request.session_id)
        self.clear_interrupt()
        request_id = str(runtime_request.metadata.get("request_id") or runtime_request.session_id or "runtime")
        try:
            if log_writer is not None:
                log_writer.write_session_header(
                    {
                        "source": runtime_request.source,
                        "workspace": str(self.workspace_root),
                        "session_created_at": self.session_created_at,
                        "system_prompt": self.system_prompt,
                        "tools": self.tools,
                        "model": getattr(self.llm, "model_name", None),
                    }
                )
                log_writer.write_event(
                    "run_started",
                    {"source": runtime_request.source, "metadata": runtime_request.metadata},
                    request_id=request_id,
                )
            prepared = prepare_runtime_history(
                self.history,
                request_id=request_id,
                provider=str(getattr(getattr(self.llm, "profile", None), "provider", "")),
            )
            if prepared.changed:
                self.history = prepared.history
                repair_event = {
                    "type": "runtime_history_repaired",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "request_id": request_id,
                    "repairs": prepared.repairs,
                }
                self.runtime_events.append(repair_event)
                if event_writer is not None:
                    event_writer.write_event("runtime_history_repaired", repair_event)
                if log_writer is not None:
                    log_writer.write_event("runtime_history_repaired", repair_event, request_id=request_id)
            if self.context_manager.should_compress(self.history):
                result = self.compact_history(trigger="auto-threshold", allow_fallback=True)
                if log_writer is None:
                    self._record_compression_event(result, event_writer=event_writer, request_id=request_id)
                else:
                    self._record_compression_event(
                        result,
                        event_writer=event_writer,
                        log_writer=log_writer,
                        request_id=request_id,
                    )
                self._print_compression_result(result)

            loop = AgentLoop(
                llm=self.llm,
                tools=self.tools,
                tool_loader=self.tool_loader,
                history=self.history,
                system_prompt=self.system_prompt,
                max_turns=self.max_turns,
                max_tool_result_chars=MAX_TOOL_RESULT_CHARS,
                event_writer=event_writer,
                log_writer=log_writer,
                interrupt_event=self._interrupted,
                start_interrupt_listener=self._start_esc_listener,
                request_id=request_id,
                input_provider=getattr(self, "input_provider", None),
                checkpoint=getattr(self, "checkpoint", None),
            )
            initial_entry = runtime_request.metadata.get("input_entry")
            result = (loop.run(runtime_request.content, input_entry=initial_entry)
                      if initial_entry else loop.run(runtime_request.content))
            if log_writer is not None:
                log_writer.write_event(
                    "run_finished",
                    {
                        "interrupted": loop.was_interrupted,
                        "recoverable": bool(getattr(loop, "was_recoverable", False)),
                    },
                    request_id=request_id,
                )
            return RuntimeResponse(
                content=result,
                session_id=runtime_request.session_id,
                metadata={
                    "source": runtime_request.source,
                    "interrupted": loop.was_interrupted,
                    "recoverable": bool(getattr(loop, "was_recoverable", False)),
                    "recovery_stage": getattr(loop, "recovery_stage", None),
                    "recovery_error": getattr(loop, "recovery_error", None),
                    **runtime_request.metadata,
                },
            )
        except Exception as exc:
            if log_writer is not None:
                log_writer.write_event(
                    "run_failed",
                    {"error_type": type(exc).__name__, "error_message": str(exc)},
                    request_id=request_id,
                )
            raise

    def interrupt(self) -> None:
        self._interrupted.set()
        cancel = getattr(self.llm, "cancel_current_request", None)
        if cancel is not None:
            cancel()

    def clear_interrupt(self) -> None:
        # Old tools retain their cancelled signal; never clear a previous run.
        self._interrupted = threading.Event()
        self.llm.set_interrupt_event(self._interrupted)
        self.tool_loader.set_interrupt_event(self._interrupted)

    def is_interrupted(self) -> bool:
        return self._interrupted.is_set()

    def _start_esc_listener(self):
        if not HAS_MSVCRT:
            return None

        interrupted = self._interrupted
        last_esc = [0.0]

        def listener():
            while not interrupted.is_set():
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key == b"\x1b":
                        now = time.time()
                        if now - last_esc[0] < 1.0:
                            interrupted.set()
                            print("\n\nInterrupted by ESC.")
                            return
                        last_esc[0] = now
                time.sleep(0.05)

        thread = threading.Thread(target=listener, daemon=True)
        thread.start()
        return thread

    def get_context_json(self) -> str:
        context = self.get_session_log_data()
        return json.dumps(context, ensure_ascii=False, indent=2)

    def get_session_log_data(self) -> Dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "available_tools": len(self.tools),
            "workspace": str(self.workspace_root),
            "history": self.history,
            "role": self.role_config.name,
            "events": self.runtime_events,
        }

    def save_context(self, filepath: str):
        Path(filepath).write_text(self.get_context_json(), encoding="utf-8")
        print(f"Saved context to: {filepath}")

    def reset(self):
        self.history = []
        print("Session history cleared.")

    def compact_history(self, *, trigger: str, allow_fallback: bool):
        result = self.context_manager.compress_history_with_result(
            self.history,
            trigger=trigger,
            allow_fallback=allow_fallback,
        )
        if result.success or result.fallback:
            self.history = result.history
        return result

    def _create_event_writer(self, session_id: str | None) -> SessionEventWriter | None:
        if self.runtime_events_dir is None or not session_id:
            return None
        return SessionEventWriter(self.runtime_events_dir, session_id)

    def _create_log_writer(self, session_id: str | None) -> RealtimeLogWriter | None:
        logs_dir = getattr(self, "runtime_logs_dir", None)
        if logs_dir is None or not session_id:
            return None
        return RealtimeLogWriter(logs_dir, session_id)

    def _record_compression_event(
        self,
        result,
        *,
        event_writer: SessionEventWriter | None = None,
        log_writer: RealtimeLogWriter | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        event = result.to_event()
        event["timestamp"] = datetime.now().isoformat(timespec="seconds")
        if request_id:
            event["request_id"] = request_id
        self.runtime_events.append(event)
        if event_writer is not None:
            event_writer.write_event(event["type"], event)
        if log_writer is not None:
            log_writer.write_event(event["type"], event, request_id=request_id)
        return event

    def _print_compression_result(self, result) -> None:
        if result.success:
            print(
                "\n上下文已压缩："
                f"{result.trigger}，消息 {result.before_message_count} -> {result.after_message_count}，"
                f"tokens {result.before_tokens} -> {result.after_tokens}"
            )
            if result.summary:
                print("\n压缩摘要：")
                print(result.summary)
            print()
            return

        if result.fallback:
            print(
                "\n上下文压缩失败，已 fallback 到最近短上下文："
                f"{result.trigger}，消息 {result.before_message_count} -> {result.after_message_count}，"
                f"tokens {result.before_tokens} -> {result.after_tokens}，错误：{result.error}\n"
            )
            return

        print(f"\n上下文压缩失败：{result.error}\n")

    def close(self) -> None:
        mcp_mgr = self.tool_loader.tool_executors.get("_mcp_manager")
        if mcp_mgr:
            try:
                mcp_mgr.close_all()
            except Exception:
                pass
