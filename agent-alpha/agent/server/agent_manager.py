from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.agent_runtime import AgentRuntime, PROJECT_ROOT
from agent.core.message_pipeline import prepare_runtime_history
from agent.core.runtime_types import RuntimeRequest
from agent.core.realtime_log import RealtimeLogWriter
from agent.core.session_events import SessionEventWriter, migrate_event_file, read_session_events
from agent.core.session_paths import create_cli_session_paths
from agent.core.session_store import SessionKind, SessionRecord, SessionStore
from agent.server.stores.app_state import now_iso, new_id


class AgentManager:
    def __init__(self):
        self.sessions_dir, self.logs_dir = create_cli_session_paths(project_root=PROJECT_ROOT)
        self.events_dir = PROJECT_ROOT / "session-log" / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.store = SessionStore(self.sessions_dir)
        self._agents: dict[str, AgentRuntime] = {}
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self.cleanup_legacy_sessions()
        self.migrate_historical_events()

    def create_session(self, *, project_id: str, workspace: Path, title: str | None = None) -> SessionRecord:
        session_id = new_id("sess")
        timestamp = now_iso()
        record = SessionRecord(
            session_id=session_id,
            kind=SessionKind.INTERACTIVE,
            workspace=str(workspace),
            metadata={
                "project_id": project_id,
                "title": title or "新对话",
                "is_pinned": False,
                "is_archived": False,
            },
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.store.save(record)

    def list_sessions(self, *, project_id: str | None = None, include_archived: bool = False) -> list[SessionRecord]:
        records = self.store.list_recent(kind=SessionKind.INTERACTIVE, limit=None)
        result: list[SessionRecord] = []
        for record in records:
            if project_id and record.metadata.get("project_id") != project_id:
                continue
            if not include_archived and record.metadata.get("is_archived"):
                continue
            result.append(record)
        result.sort(key=lambda item: item.updated_at or "", reverse=True)
        result.sort(key=lambda item: 0 if item.metadata.get("is_pinned") else 1)
        return result

    def get_session(self, session_id: str) -> SessionRecord | None:
        record = self.store.load(session_id)
        if record and record.kind == SessionKind.INTERACTIVE and not record.metadata.get("is_archived"):
            return record
        return None

    def update_session(self, session_id: str, updates: dict[str, Any]) -> SessionRecord | None:
        record = self.get_session(session_id)
        if record is None:
            return None
        metadata = dict(record.metadata)
        for key in ("title", "is_pinned", "is_archived"):
            if key in updates and updates[key] is not None:
                metadata[key] = updates[key]
        record.metadata = metadata
        record.updated_at = now_iso()
        return self.store.save(record)

    def archive_project_sessions(self, project_id: str) -> None:
        for record in self.list_sessions(project_id=project_id, include_archived=True):
            self.update_session(record.session_id, {"is_archived": True})
            self.release(record.session_id)

    def delete_session(self, session_id: str) -> bool:
        removed = self.store.delete(session_id)
        event_path = self.events_dir / f"{session_id}.jsonl"
        if event_path.exists():
            event_path.unlink()
            removed = True
        for log_path in self.logs_dir.glob(f"*_session_{session_id}.json"):
            log_path.unlink()
            removed = True
        realtime_log_path = self.logs_dir / f"{session_id}.jsonl"
        if realtime_log_path.exists():
            realtime_log_path.unlink()
            removed = True
        self.release(session_id)
        return removed

    def delete_project_sessions(self, project_id: str) -> None:
        for record in self.list_sessions(project_id=project_id, include_archived=True):
            self.delete_session(record.session_id)

    def start_chat(
        self,
        *,
        session_id: str,
        message: str,
        permission_mode: str = "ask",
        llm_settings: dict[str, Any] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> str:
        record = self.get_session(session_id)
        if record is None:
            raise ValueError(f"Session not found: {session_id}")
        if self._has_active_run(session_id):
            raise RuntimeError("Session already has an active run")
        request_id = uuid.uuid4().hex
        timestamp = now_iso()
        started_after_seq = self._latest_event_seq(session_id)
        self._save_incoming_user_message(
            record,
            message,
            timestamp,
            request_id=request_id,
            started_after_seq=started_after_seq,
        )
        with self._lock:
            self._runs[request_id] = {
                "request_id": request_id,
                "session_id": session_id,
                "status": "running",
                "operation": "chat",
                "started_after_seq": started_after_seq,
                "response": None,
                "error": None,
                "tool_calls_count": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        self._executor.submit(
            self._run_chat,
            request_id,
            record,
            message,
            permission_mode,
            dict(llm_settings or {}),
            dict(runtime_metadata or {}),
        )
        return request_id

    def start_compact(
        self,
        *,
        session_id: str,
        permission_mode: str = "ask",
        llm_settings: dict[str, Any] | None = None,
    ) -> str:
        record = self.get_session(session_id)
        if record is None:
            raise ValueError(f"Session not found: {session_id}")
        if self._has_active_run(session_id):
            raise RuntimeError("Session already has an active run")
        request_id = uuid.uuid4().hex
        timestamp = now_iso()
        with self._lock:
            self._runs[request_id] = {
                "request_id": request_id,
                "session_id": session_id,
                "status": "running",
                "operation": "compact",
                "started_after_seq": self._latest_event_seq(session_id),
                "response": None,
                "error": None,
                "tool_calls_count": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        self._executor.submit(self._run_compact, request_id, record, permission_mode, dict(llm_settings or {}))
        return request_id

    def get_run(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(request_id)
            return dict(run) if run else None

    def get_active_run_for_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            runs = [
                dict(run)
                for run in self._runs.values()
                if run.get("session_id") == session_id and run.get("status") == "running"
            ]
        if not runs:
            return None
        runs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return runs[0]

    def _has_active_run(self, session_id: str) -> bool:
        with self._lock:
            return any(
                run.get("session_id") == session_id and run.get("status") == "running"
                for run in self._runs.values()
            )

    def interrupt(self, session_id: str) -> bool:
        with self._lock:
            agent = self._agents.get(session_id)
        if agent is None:
            return False
        agent.interrupt()
        return True

    def release(self, session_id: str) -> None:
        with self._lock:
            self._agents.pop(session_id, None)

    def release_all(self) -> None:
        with self._lock:
            self._agents.clear()

    def cleanup_legacy_sessions(self) -> int:
        removed = 0
        for record in self.store.list_recent(kind=SessionKind.INTERACTIVE, limit=None):
            if record.metadata.get("project_id"):
                continue
            removed += 1
            self.store.delete(record.session_id)
            event_path = self.events_dir / f"{record.session_id}.jsonl"
            if event_path.exists():
                event_path.unlink()
            for log_path in self.logs_dir.glob(f"*_session_{record.session_id}.json"):
                log_path.unlink()
            realtime_log_path = self.logs_dir / f"{record.session_id}.jsonl"
            if realtime_log_path.exists():
                realtime_log_path.unlink()
        return removed

    def migrate_historical_events(self) -> int:
        migrated = 0
        for record in self.store.list_recent(kind=SessionKind.INTERACTIVE, limit=None):
            checkpoint_status = str((record.runtime_checkpoint or {}).get("status") or "")
            if checkpoint_status in {"running", "failed", "recoverable"}:
                continue
            event_path = self.events_dir / f"{record.session_id}.jsonl"
            try:
                if migrate_event_file(event_path, cleanup_completed=True):
                    migrated += 1
            except Exception:
                continue
        return migrated

    def _get_agent(self, record: SessionRecord, permission_mode: str, llm_settings: dict[str, Any]) -> AgentRuntime:
        with self._lock:
            agent = self._agents.get(record.session_id)
            if agent is not None and not self._should_rebuild_agent(agent, record, permission_mode, llm_settings):
                return agent
            if agent is not None:
                self._agents.pop(record.session_id, None)
        agent = AgentRuntime(
            workspace_root=record.workspace,
            logs_dir=str(self.logs_dir),
            events_dir=str(self.events_dir),
            session_created_at=record.created_at,
            llm_settings=llm_settings,
        )
        agent.llm.stream_responses = True
        agent.history = self._runtime_history_for_record(record)
        if agent.tool_loader.permission_manager is not None:
            agent.tool_loader.permission_manager.set_mode(permission_mode)
        setattr(agent, "_web_permission_mode", permission_mode)
        with self._lock:
            self._agents[record.session_id] = agent
        return agent

    def _run_chat(
        self,
        request_id: str,
        record: SessionRecord,
        message: str,
        permission_mode: str,
        llm_settings: dict[str, Any],
        runtime_metadata: dict[str, Any] | None = None,
    ) -> None:
        agent: AgentRuntime | None = None
        runtime_event_start = 0
        try:
            agent = self._get_agent(record, permission_mode, llm_settings)
            runtime_event_start = len(getattr(agent, "runtime_events", []))
            response = agent.handle(
                RuntimeRequest(
                    content=message,
                    session_id=record.session_id,
                    source="web",
                    metadata={
                        "project_id": record.metadata.get("project_id"),
                        "request_id": request_id,
                        **dict(runtime_metadata or {}),
                    },
                )
            )
            latest = self.store.load(record.session_id) or record
            runtime_events = list(getattr(agent, "runtime_events", []))[runtime_event_start:]
            metadata = dict(latest.metadata or record.metadata)
            if metadata.get("title") in {None, "", "新对话", "鏂板璇?"}:
                metadata["title"] = message.strip().replace("\n", " ")[:80] or "新对话"
            saved = SessionRecord(
                session_id=record.session_id,
                kind=SessionKind.INTERACTIVE,
                workspace=latest.workspace or record.workspace,
                history=self._merge_display_history(latest.history, agent.history, message),
                runtime_history=[dict(item) for item in agent.history],
                runtime_checkpoint=(
                    {
                        "request_id": request_id,
                        "operation": "chat",
                        "status": "recoverable",
                        "phase": response.metadata.get("recovery_stage") or "exhausted",
                        "pending_user_message": message,
                        "started_after_seq": self._latest_event_seq(record.session_id),
                        "last_error": response.metadata.get("recovery_error"),
                        "updated_at": now_iso(),
                    }
                    if response.metadata.get("recoverable")
                    else {}
                ),
                metadata=metadata,
                events=list(latest.events) + runtime_events,
                created_at=latest.created_at or record.created_at,
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )
            self.store.save(saved)
            if not response.metadata.get("interrupted") and not response.metadata.get("recoverable"):
                try:
                    SessionEventWriter(self.events_dir, record.session_id).compact_completed_request(request_id)
                except Exception:
                    pass
            self._set_run(
                request_id,
                status=(
                    "interrupted"
                    if response.metadata.get("interrupted")
                    else "recoverable"
                    if response.metadata.get("recoverable")
                    else "success"
                ),
                response=response.content,
                tool_calls_count=self._count_tool_calls(agent.history),
                recovery_stage=response.metadata.get("recovery_stage"),
                can_resume=bool(response.metadata.get("recoverable")),
                error=response.metadata.get("recovery_error"),
            )
        except Exception as exc:
            tool_calls_count = self._count_tool_calls(agent.history) if agent is not None else 0
            self._save_failed_run_snapshot(
                request_id=request_id,
                record=record,
                agent=agent,
                error=exc,
                message=message,
                tool_calls_count=tool_calls_count,
                runtime_event_start=runtime_event_start,
            )
            self._set_run(request_id, status="failed", error=str(exc), tool_calls_count=tool_calls_count)

    def _run_compact(
        self,
        request_id: str,
        record: SessionRecord,
        permission_mode: str,
        llm_settings: dict[str, Any],
    ) -> None:
        agent: AgentRuntime | None = None
        runtime_event_start = 0
        event_writer = SessionEventWriter(self.events_dir, record.session_id)
        logs_dir = getattr(self, "logs_dir", None)
        log_writer = RealtimeLogWriter(logs_dir, record.session_id) if logs_dir is not None else None
        try:
            agent = self._get_agent(record, permission_mode, llm_settings)
            runtime_event_start = len(getattr(agent, "runtime_events", []))
            agent.clear_interrupt()
            started_event = {
                "type": "context_compaction_started",
                "timestamp": now_iso(),
                "request_id": request_id,
                "trigger": "manual-web",
            }
            agent.runtime_events.append(started_event)
            event_writer.write_event("context_compaction_started", started_event)
            if log_writer is not None:
                log_writer.write_event("context_compaction_started", started_event, request_id=request_id)

            result = agent.compact_history(trigger="manual-web", allow_fallback=False)

            if agent.is_interrupted():
                interrupted_event = {
                    "type": "context_compaction_interrupted",
                    "timestamp": now_iso(),
                    "request_id": request_id,
                    "trigger": "manual-web",
                    "error": result.error,
                }
                agent.runtime_events.append(interrupted_event)
                event_writer.write_event("context_compaction_interrupted", interrupted_event)
                if log_writer is not None:
                    log_writer.write_event("context_compaction_interrupted", interrupted_event, request_id=request_id)
                self._save_compact_run_snapshot(
                    record=record,
                    agent=agent,
                    runtime_event_start=runtime_event_start,
                    update_runtime_history=False,
                )
                self._set_run(
                    request_id,
                    status="interrupted",
                    response="上下文压缩已中断",
                    tool_calls_count=self._count_tool_calls(agent.history),
                )
                return

            self._record_compaction_event(
                agent,
                result,
                request_id=request_id,
                event_writer=event_writer,
                log_writer=log_writer,
            )
            if getattr(result, "skipped", False):
                self._save_compact_run_snapshot(
                    record=record,
                    agent=agent,
                    runtime_event_start=runtime_event_start,
                    update_runtime_history=True,
                )
                self._set_run(
                    request_id,
                    status="success",
                    response="当前上下文已经足够紧凑，无需再次压缩",
                    tool_calls_count=self._count_tool_calls(agent.history),
                )
                return
            if result.success:
                self._save_compact_run_snapshot(
                    record=record,
                    agent=agent,
                    runtime_event_start=runtime_event_start,
                    update_runtime_history=True,
                )
                self._set_run(
                    request_id,
                    status="success",
                    response="上下文已压缩",
                    tool_calls_count=self._count_tool_calls(agent.history),
                )
                return

            self._save_compact_run_snapshot(
                record=record,
                agent=agent,
                runtime_event_start=runtime_event_start,
                update_runtime_history=False,
            )
            self._set_run(
                request_id,
                status="failed",
                error=result.error or "Context compaction failed",
                tool_calls_count=self._count_tool_calls(agent.history),
            )
        except Exception as exc:
            if agent is not None:
                failed_event = {
                    "type": "context_compaction_failed",
                    "timestamp": now_iso(),
                    "request_id": request_id,
                    "trigger": "manual-web",
                    "success": False,
                    "fallback": False,
                    "error": str(exc),
                }
                agent.runtime_events.append(failed_event)
                try:
                    event_writer.write_event("context_compaction_failed", failed_event)
                    if log_writer is not None:
                        log_writer.write_event("context_compaction_failed", failed_event, request_id=request_id)
                except Exception:
                    pass
                self._save_compact_run_snapshot(
                    record=record,
                    agent=agent,
                    runtime_event_start=runtime_event_start,
                    update_runtime_history=False,
                )
            self._set_run(request_id, status="failed", error=str(exc), tool_calls_count=0)

    def _save_incoming_user_message(
        self,
        record: SessionRecord,
        message: str,
        timestamp: str,
        *,
        request_id: str,
        started_after_seq: int,
    ) -> SessionRecord:
        latest = self.store.load(record.session_id) or record
        history = [dict(item) for item in latest.history]
        history.append({"role": "user", "content": message})
        runtime_history = self._runtime_history_for_record(latest)
        runtime_history.append({"role": "user", "content": message})
        metadata = dict(latest.metadata or record.metadata)
        if metadata.get("title") in {None, "", "新对话", "鏂板璇?"}:
            metadata["title"] = message.strip().replace("\n", " ")[:80] or "新对话"
        saved = SessionRecord(
            session_id=record.session_id,
            kind=latest.kind,
            workspace=latest.workspace or record.workspace,
            history=history,
            runtime_history=runtime_history,
            runtime_checkpoint={
                "request_id": request_id,
                "operation": "chat",
                "status": "running",
                "phase": "queued",
                "pending_user_message": message,
                "started_after_seq": started_after_seq,
                "updated_at": timestamp,
            },
            metadata=metadata,
            events=list(latest.events),
            created_at=latest.created_at or record.created_at,
            updated_at=timestamp,
        )
        return self.store.save(saved)

    def _save_failed_run_snapshot(
        self,
        *,
        request_id: str,
        record: SessionRecord,
        agent: AgentRuntime | None,
        error: Exception,
        message: str,
        tool_calls_count: int,
        runtime_event_start: int = 0,
    ) -> None:
        timestamp = now_iso()
        error_message = str(error) or type(error).__name__
        event = {
            "type": "run_failed",
            "timestamp": timestamp,
            "request_id": request_id,
            "error_type": type(error).__name__,
            "error_message": error_message,
            "tool_calls_count": tool_calls_count,
            "history_message_count": len(agent.history) if agent is not None else 0,
        }

        try:
            SessionEventWriter(self.events_dir, record.session_id).write_event("run_failed", event)
        except Exception:
            pass

        latest = self.store.load(record.session_id) or record
        if agent is not None and agent.history:
            prepared = prepare_runtime_history(
                agent.history,
                request_id=request_id,
                provider=str(
                    getattr(getattr(getattr(agent, "llm", None), "profile", None), "provider", "")
                ),
            )
            runtime_history = prepared.history
        else:
            runtime_history = self._runtime_history_for_record(latest)
        history = (
            self._merge_display_history(latest.history, agent.history, message)
            if agent is not None and agent.history
            else [dict(item) for item in latest.history]
        )
        metadata = dict(latest.metadata or record.metadata)
        if metadata.get("title") in {None, "", "新对话", "鏂板璇?"}:
            metadata["title"] = message.strip().replace("\n", " ")[:80] or "新对话"

        runtime_events = (
            list(getattr(agent, "runtime_events", []))[runtime_event_start:]
            if agent is not None
            else []
        )
        saved = SessionRecord(
            session_id=record.session_id,
            kind=SessionKind.INTERACTIVE,
            workspace=latest.workspace or record.workspace,
            history=history,
            runtime_history=runtime_history,
            runtime_checkpoint={
                "request_id": request_id,
                "operation": "chat",
                "status": "failed",
                "phase": "failed",
                "pending_user_message": message,
                "last_error": error_message,
                "updated_at": timestamp,
            },
            metadata=metadata,
            events=list(latest.events) + runtime_events + [event],
            created_at=latest.created_at or record.created_at,
            updated_at=timestamp,
        )
        self.store.save(saved)

    def _save_compact_run_snapshot(
        self,
        *,
        record: SessionRecord,
        agent: AgentRuntime,
        runtime_event_start: int,
        update_runtime_history: bool,
    ) -> None:
        latest = self.store.load(record.session_id) or record
        saved = SessionRecord(
            session_id=record.session_id,
            kind=SessionKind.INTERACTIVE,
            workspace=latest.workspace or record.workspace,
            history=[dict(item) for item in latest.history],
            runtime_history=(
                [dict(item) for item in agent.history]
                if update_runtime_history
                else self._runtime_history_for_record(latest)
            ),
            runtime_checkpoint=dict(latest.runtime_checkpoint),
            metadata=dict(latest.metadata or record.metadata),
            events=list(latest.events) + list(getattr(agent, "runtime_events", []))[runtime_event_start:],
            created_at=latest.created_at or record.created_at,
            updated_at=now_iso(),
        )
        self.store.save(saved)

    def _record_compaction_event(
        self,
        agent: AgentRuntime,
        result: Any,
        *,
        request_id: str,
        event_writer: SessionEventWriter,
        log_writer: RealtimeLogWriter | None = None,
    ) -> dict[str, Any]:
        event = result.to_event()
        event["timestamp"] = now_iso()
        event["request_id"] = request_id
        agent.runtime_events.append(event)
        event_writer.write_event(event["type"], event)
        if log_writer is not None:
            log_writer.write_event(event["type"], event, request_id=request_id)
        return event

    def _latest_event_seq(self, session_id: str) -> int:
        events_dir = getattr(self, "events_dir", None)
        if events_dir is None:
            return 0
        writer = SessionEventWriter(events_dir, session_id)
        return max(0, writer._next_seq - 1)

    def _runtime_history_for_record(self, record: SessionRecord) -> list[dict[str, Any]]:
        source = record.runtime_history if record.runtime_history else record.history
        history = [dict(message) for message in source]
        checkpoint = dict(record.runtime_checkpoint or {})
        if checkpoint.get("status") == "running":
            request_id = str(checkpoint.get("request_id") or "")
            pending_user = checkpoint.get("pending_user_message")
            skipped_pending = False
            for event in read_session_events(
                self.events_dir,
                record.session_id,
                after_seq=int(checkpoint.get("started_after_seq") or 0),
            ):
                if request_id and str(event.get("request_id") or "") != request_id:
                    continue
                entry = event.get("entry")
                if not isinstance(entry, dict):
                    continue
                if (
                    not skipped_pending
                    and entry.get("role") == "user"
                    and entry.get("content") == pending_user
                ):
                    skipped_pending = True
                    continue
                history.append(dict(entry))
        return prepare_runtime_history(history, request_id=f"load_{record.session_id}").history

    @staticmethod
    def _last_user_index(history: list[dict[str, Any]], message: str) -> int | None:
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            if item.get("role") == "user" and item.get("content") == message:
                return index
        return None

    @classmethod
    def _merge_display_history(
        cls,
        base_history: list[dict[str, Any]],
        runtime_history: list[dict[str, Any]],
        message: str,
    ) -> list[dict[str, Any]]:
        history = [dict(item) for item in base_history]
        runtime = [dict(item) for item in runtime_history]
        runtime_user_index = cls._last_user_index(runtime, message)
        if runtime_user_index is None:
            return history

        base_has_user = cls._last_user_index(history, message) is not None
        delta_start = runtime_user_index + 1 if base_has_user else runtime_user_index
        history.extend(dict(item) for item in runtime[delta_start:])
        return history

    def _set_run(self, request_id: str, **updates: Any) -> None:
        with self._lock:
            run = self._runs.get(request_id)
            if not run:
                return
            run.update(updates)
            run["updated_at"] = now_iso()

    @staticmethod
    def _count_tool_calls(history: list[dict[str, Any]]) -> int:
        count = 0
        for message in history:
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                count += len(tool_calls)
        return count

    @staticmethod
    def _should_rebuild_agent(
        agent: AgentRuntime,
        record: SessionRecord,
        permission_mode: str,
        llm_settings: dict[str, Any],
    ) -> bool:
        if Path(agent.workspace_root).resolve() != Path(record.workspace).resolve():
            return True
        if dict(getattr(agent, "llm_settings", {})) != dict(llm_settings):
            return True
        return getattr(agent, "_web_permission_mode", None) != permission_mode
