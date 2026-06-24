"""
Single-agent CLI runner.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
import shlex

from agent.core.agent_runtime import AgentRuntime
from agent.core.runtime_paths import apply_runtime_env
from agent.core.session_events import SessionEventWriter
from agent.core.session_store import SessionKind, SessionRecord, SessionStore
from agent.core.runtime_types import RuntimeRequest
from agent.core.session_paths import create_cli_session_paths, get_default_workspace_root


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _generate_session_id() -> str:
    import uuid

    return uuid.uuid4().hex[:6]


def create_cli_session(project_root: Path) -> tuple[Path, Path, Path]:
    sessions_dir, logs_dir = create_cli_session_paths(project_root=project_root)
    workspace_root = get_default_workspace_root(project_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return sessions_dir, logs_dir, workspace_root


def build_log_path(logs_dir: Path, session_id: str, started_at: datetime) -> Path:
    filename = f"{started_at.strftime('%Y-%m-%d_%H-%M-%S')}_session_{session_id}.json"
    return logs_dir / filename


def _read_event_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
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


def _history_stats(history: list[dict]) -> dict:
    role_counts = Counter(str(message.get("role") or "unknown") for message in history)
    return {
        "total_messages": len(history),
        "role_counts": dict(role_counts),
        "user_turns": role_counts.get("user", 0),
        "assistant_turns": role_counts.get("assistant", 0),
        "tool_results": role_counts.get("tool", 0),
        "assistant_tool_call_messages": sum(1 for message in history if message.get("tool_calls")),
    }


def _runtime_event_stats(runtime_events: list[dict], event_records: list[dict]) -> dict:
    runtime_counts = Counter(str(event.get("type") or "unknown") for event in runtime_events)
    realtime_counts = Counter(str(record.get("type") or "history_entry") for record in event_records)
    return {
        "runtime_event_count": len(runtime_events),
        "runtime_event_type_counts": dict(runtime_counts),
        "realtime_event_count": len(event_records),
        "realtime_event_type_counts": dict(realtime_counts),
    }


def _recent_llm_diagnostics(event_records: list[dict], *, limit: int = 20) -> list[dict]:
    diagnostics: list[dict] = []
    for record in event_records:
        event_type = str(record.get("type") or "")
        if not event_type.startswith("llm_"):
            continue
        event = dict(record.get("event") or {})
        event["type"] = event_type
        event["seq"] = record.get("seq")
        event["ts"] = record.get("ts")
        diagnostics.append(event)
    return diagnostics[-limit:]


def _llm_log_info(agent: AgentRuntime) -> dict:
    llm = getattr(agent, "llm", None)
    profile = getattr(llm, "profile", None)
    return {
        "profile": getattr(profile, "name", None),
        "provider": getattr(profile, "provider", None),
        "model": getattr(llm, "model_name", None) or getattr(profile, "model", None),
        "base_url": getattr(profile, "base_url", None),
    }


def append_session_index(
    *,
    sessions_dir: Path,
    session_id: str,
    started_at: datetime,
    history,
    workspace: Path,
    log_path: Path,
):
    index_file = sessions_dir / "index.md"
    index_file.parent.mkdir(parents=True, exist_ok=True)

    user_turns = len([message for message in history if message["role"] == "user"])
    first_msg = next((m["content"][:100] for m in history if m["role"] == "user"), "")
    first_msg = first_msg.replace("\n", " ").replace("|", "/")

    if not index_file.exists():
        header = "# Session Index\n\n"
        header += "| Session ID | Started | User Turns | Workspace | Log File | First User Message |\n"
        header += "|---|---|---:|---|---|---|\n"
        index_file.write_text(header, encoding="utf-8")

    time_str = started_at.strftime("%m-%d %H:%M")
    project_root = sessions_dir.parent.parent

    def _display_path(path: Path) -> str:
        try:
            return str(path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    workspace_str = _display_path(workspace)
    log_str = _display_path(log_path)
    line = f"| {session_id} | {time_str} | {user_turns} | {workspace_str} | {log_str} | {first_msg} |\n"
    with open(index_file, "a", encoding="utf-8") as handle:
        handle.write(line)


def save_session_log(
    *,
    agent: AgentRuntime,
    session_id: str,
    started_at: datetime,
    sessions_dir: Path,
    workspace: Path,
    log_path: Path,
):
    if not agent.history:
        print("No session history to save.")
        return

    ended_at = datetime.now()
    project_root = sessions_dir.parent.parent
    events_path = log_path.parent.parent / "events" / f"{session_id}.jsonl"
    event_read_error = None
    try:
        event_records = _read_event_records(events_path)
    except Exception as exc:
        event_records = []
        event_read_error = {
            "path": str(events_path),
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    runtime_data = agent.get_session_log_data()
    history = list(runtime_data.get("history") or agent.history)
    runtime_events = list(runtime_data.get("events") or [])
    log_data = {
        "schema_version": 2,
        "session_id": session_id,
        "session_kind": "interactive_cli",
        "entrypoint": "cli",
        "project_root": str(project_root),
        "events_path": str(events_path),
        "start_time": started_at.isoformat(),
        "end_time": ended_at.isoformat(),
        "duration_seconds": (ended_at - started_at).total_seconds(),
        "total_turns": len([msg for msg in history if msg.get("role") == "user"]),
        "llm": _llm_log_info(agent),
        "history_stats": _history_stats(history),
        "runtime_event_stats": _runtime_event_stats(runtime_events, event_records),
        "recent_llm_diagnostics": _recent_llm_diagnostics(event_records),
    }
    if event_read_error is not None:
        log_data["event_read_error"] = event_read_error
    log_data.update(runtime_data)

    tmp_path = log_path.with_name(f"{log_path.name}.tmp")
    try:
        payload = json.dumps(log_data, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, log_path)
        print(f"Saved session log: {log_path}")
        append_session_index(
            sessions_dir=sessions_dir,
            session_id=session_id,
            started_at=started_at,
            history=agent.history,
            workspace=workspace,
            log_path=log_path,
        )
    except Exception as exc:  # pragma: no cover - logging fallback
        try:
            tmp_path.unlink()
        except Exception:
            pass
        print(f"Failed to save session log: {exc}")


def _create_runtime(
    workspace: Path,
    logs_dir: Path,
    events_dir: Path,
    history: list[dict] | None = None,
    permission_mode: str | None = None,
) -> AgentRuntime:
    agent = AgentRuntime(
        workspace_root=str(workspace),
        logs_dir=str(logs_dir),
        events_dir=str(events_dir),
    )
    agent.history = [dict(message) for message in (history or [])]
    if permission_mode and agent.tool_loader.permission_manager is not None:
        agent.tool_loader.permission_manager.set_mode(permission_mode)
    return agent


def _save_session_snapshot(
    *,
    store: SessionStore,
    session_id: str,
    agent: AgentRuntime,
    workspace: Path,
    created_at: datetime,
    metadata: dict | None = None,
) -> SessionRecord:
    existing = store.load(session_id)
    events = _merge_session_events(
        list(existing.events) if existing is not None else [],
        list(getattr(agent, "runtime_events", [])),
    )
    record = SessionRecord(
        session_id=session_id,
        kind=SessionKind.INTERACTIVE,
        workspace=str(workspace),
        history=[dict(message) for message in agent.history],
        metadata=metadata or {},
        events=events,
        created_at=created_at.isoformat(),
        updated_at=datetime.now().isoformat(),
    )
    return store.save(record)


def _save_recoverable_session_snapshot(
    *,
    store: SessionStore,
    session_id: str,
    agent: AgentRuntime,
    workspace: Path,
    created_at: datetime,
    metadata: dict | None = None,
) -> bool:
    if not getattr(agent, "history", None):
        return False

    try:
        _save_session_snapshot(
            store=store,
            session_id=session_id,
            agent=agent,
            workspace=workspace,
            created_at=created_at,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover - defensive recovery path
        print(f"Failed to save recoverable session snapshot: {exc}")
        return False
    return True


def _merge_session_events(existing: list[dict], runtime_events: list[dict]) -> list[dict]:
    merged = [dict(event) for event in existing]
    seen = {json.dumps(event, ensure_ascii=False, sort_keys=True) for event in merged}
    for event in runtime_events:
        key = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        merged.append(dict(event))
        seen.add(key)
    return merged


def _record_runtime_error(*, events_dir: Path, session_id: str, exc: Exception) -> dict:
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    writer = SessionEventWriter(events_dir, session_id)
    writer.write_event("runtime_error", event)
    return {"type": "runtime_error", **event}


def _append_session_event_and_history(
    *,
    store: SessionStore,
    session_id: str,
    agent,
    event: dict,
) -> None:
    record = store.load(session_id)
    if record is None:
        return
    payload = dict(event)
    payload["timestamp"] = str(payload.get("timestamp") or datetime.now().isoformat(timespec="seconds"))
    record.history = [dict(message) for message in agent.history]
    record.events.append(payload)
    record.updated_at = payload["timestamp"]
    store.save(record)


def _print_compaction_result(result) -> None:
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

    print(f"\n压缩失败，历史未改变：{result.error}\n")


def _handle_compact_command(
    *,
    agent,
    session_id: str,
    store: SessionStore,
    events_dir: Path,
) -> None:
    if not agent.history:
        print("\n当前没有可压缩的对话历史。\n")
        return

    result = agent.compact_history(trigger="manual", allow_fallback=False)
    if result.success:
        agent.history = result.history

    event = result.to_event()
    event["timestamp"] = datetime.now().isoformat(timespec="seconds")

    if hasattr(agent, "runtime_events"):
        agent.runtime_events.append(event)

    writer = SessionEventWriter(events_dir, session_id)
    writer.write_event(event["type"], event)
    _append_session_event_and_history(
        store=store,
        session_id=session_id,
        agent=agent,
        event=event,
    )
    _print_compaction_result(result)


def _format_session_option(index: int, record: SessionRecord) -> str:
    updated = record.updated_at.replace("T", " ")[:16]
    workspace = record.workspace or "(no workspace)"
    title = record.title or "(empty session)"
    return f"  [{index}] {record.session_id} | {updated} | {workspace} | {title}"


def _restore_session_interactive(store: SessionStore) -> SessionRecord | None:
    sessions = store.list_recent(kind=SessionKind.INTERACTIVE)
    if not sessions:
        print("\nNo interactive sessions available to resume.\n")
        return None

    print("\nRecent sessions:")
    for index, record in enumerate(sessions, start=1):
        print(_format_session_option(index, record))
    print("  [0] cancel\n")

    choice = input("Select session: ").strip()
    if choice in {"", "0"}:
        print("Resume cancelled.\n")
        return None

    try:
        selected = int(choice)
    except ValueError:
        print("Invalid selection.\n")
        return None

    if not 1 <= selected <= len(sessions):
        print("Invalid selection.\n")
        return None

    return store.load(sessions[selected - 1].session_id)


def _print_current_workspace(workspace: Path) -> None:
    print("\nCurrent workspace:")
    print(f"  {workspace}")
    print()


def _parse_workspace_arg(raw: str) -> Path:
    parts = shlex.split(raw, posix=False)
    if len(parts) != 1:
        raise ValueError("Please provide exactly one workspace path.")
    return Path(parts[0]).expanduser().resolve()


def _handle_workspace_command(
    *,
    command: str,
    agent: AgentRuntime,
    logs_dir: Path,
    events_dir: Path,
    current_session_id: str,
    store: SessionStore,
) -> tuple[AgentRuntime, Path]:
    if command in {"/workspace", "/workspace show"}:
        _print_current_workspace(agent.workspace_root)
        return agent, agent.workspace_root

    if command.startswith("/workspace set "):
        new_workspace = _parse_workspace_arg(command[len("/workspace set "):])
        permission_mode = (
            agent.tool_loader.permission_manager.mode
            if agent.tool_loader.permission_manager is not None
            else None
        )
        next_agent = _create_runtime(new_workspace, logs_dir, events_dir, agent.history, permission_mode)
        store.update_workspace(
            current_session_id,
            str(new_workspace),
            changed_at=datetime.now().isoformat(),
        )
        print("Updated workspace.\n")
        _print_current_workspace(new_workspace)
        return next_agent, new_workspace

    print(
        "\nWorkspace commands:\n"
        "  /workspace\n"
        "  /workspace show\n"
        "  /workspace set <path>\n"
    )
    return agent, agent.workspace_root


def run_single_agent_cli():
    print("=" * 70)
    print("Agent CLI")
    print("=" * 70)

    project_root = PROJECT_ROOT.resolve()
    apply_runtime_env(project_root)
    session_id = _generate_session_id()
    started_at = datetime.now()
    sessions_dir, logs_dir, workspace_root = create_cli_session(project_root)
    events_dir = (project_root / "session-log" / "events").resolve()
    events_dir.mkdir(parents=True, exist_ok=True)
    log_path = build_log_path(logs_dir, session_id, started_at)
    session_store = SessionStore(sessions_dir)
    current_workspace = workspace_root
    agent = _create_runtime(current_workspace, logs_dir, events_dir)
    _save_session_snapshot(
        store=session_store,
        session_id=session_id,
        agent=agent,
        workspace=current_workspace,
        created_at=started_at,
        metadata={"project_root": str(project_root)},
    )

    print("\nCommands:")
    print("  - quit / exit: save the session log and leave")
    print("  - reset: clear current history")
    print("  - /resume: restore an earlier interactive session")
    print("  - /workspace: show current workspace")
    print("  - /workspace set <path>: replace workspace")
    print("  - /compact: manually compress current conversation context")
    print("  - context: print current prompt + history JSON")
    print("  - save: write current context JSON into this session temp directory")
    print("  - save-log: persist the session log now")
    print("  - /admin: change permission mode")
    print("  - press ESC twice: interrupt the current model/tool turn\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue

            if user_input.lower() in ["quit", "exit", "q"]:
                save_session_log(
                    agent=agent,
                    session_id=session_id,
                    started_at=started_at,
                    sessions_dir=sessions_dir,
                    workspace=current_workspace,
                    log_path=log_path,
                )
                break

            if user_input.lower() == "reset":
                agent.reset()
                _save_session_snapshot(
                    store=session_store,
                    session_id=session_id,
                    agent=agent,
                    workspace=current_workspace,
                    created_at=started_at,
                    metadata={"project_root": str(project_root)},
                )
                continue

            if user_input.lower() == "/resume":
                if agent.history:
                    _save_session_snapshot(
                        store=session_store,
                        session_id=session_id,
                        agent=agent,
                        workspace=current_workspace,
                        created_at=started_at,
                        metadata={"project_root": str(project_root)},
                    )

                record = _restore_session_interactive(session_store)
                if record is None:
                    continue

                session_id = record.session_id
                started_at = datetime.fromisoformat(record.created_at)
                current_workspace = Path(record.workspace).expanduser().resolve() if record.workspace else workspace_root
                permission_mode = (
                    agent.tool_loader.permission_manager.mode
                    if agent.tool_loader.permission_manager is not None
                    else None
                )
                agent.close()
                agent = _create_runtime(current_workspace, logs_dir, events_dir, record.history, permission_mode)
                log_path = build_log_path(logs_dir, session_id, datetime.now())
                print(f"Resumed session {session_id}.\n")
                _print_current_workspace(current_workspace)
                continue

            if user_input.lower().startswith("/workspace"):
                try:
                    next_agent, next_workspace = _handle_workspace_command(
                        command=user_input,
                        agent=agent,
                        logs_dir=logs_dir,
                        events_dir=events_dir,
                        current_session_id=session_id,
                        store=session_store,
                    )
                except ValueError as exc:
                    print(f"\nError: {exc}\n")
                    continue

                if next_agent is not agent:
                    agent.close()
                    agent = next_agent
                    current_workspace = next_workspace
                    _save_session_snapshot(
                        store=session_store,
                        session_id=session_id,
                        agent=agent,
                        workspace=current_workspace,
                        created_at=started_at,
                        metadata={"project_root": str(project_root)},
                    )
                continue

            if user_input.lower() == "/compact":
                _handle_compact_command(
                    agent=agent,
                    session_id=session_id,
                    store=session_store,
                    events_dir=events_dir,
                )
                continue

            if user_input.lower() == "context":
                print("\n" + "=" * 70)
                print(agent.get_context_json())
                print("=" * 70 + "\n")
                continue

            if user_input.lower() == "save":
                save_path = agent.workspace_root / "agent_context.json"
                agent.save_context(str(save_path))
                continue

            if user_input.lower() == "save-log":
                save_session_log(
                    agent=agent,
                    session_id=session_id,
                    started_at=started_at,
                    sessions_dir=sessions_dir,
                    workspace=current_workspace,
                    log_path=log_path,
                )
                continue

            if user_input.lower() == "/admin":
                _handle_admin(agent)
                continue

            response = agent.handle(RuntimeRequest(content=user_input, session_id=session_id))
            print(f"\nAgent: {response.content}\n")
            _save_session_snapshot(
                store=session_store,
                session_id=session_id,
                agent=agent,
                workspace=current_workspace,
                created_at=started_at,
                metadata={"project_root": str(project_root)},
            )
        except KeyboardInterrupt:
            print("\n\nInterrupted by Ctrl+C.")
            save_session_log(
                agent=agent,
                session_id=session_id,
                started_at=started_at,
                sessions_dir=sessions_dir,
                workspace=current_workspace,
                log_path=log_path,
            )
            agent.close()
            break
        except Exception as exc:
            print(f"\nError: {exc}")
            import traceback

            traceback_text = traceback.format_exc()
            print(traceback_text, end="")
            _save_recoverable_session_snapshot(
                store=session_store,
                session_id=session_id,
                agent=agent,
                workspace=current_workspace,
                created_at=started_at,
                metadata={"project_root": str(project_root)},
            )
            runtime_error_event = _record_runtime_error(events_dir=events_dir, session_id=session_id, exc=exc)
            runtime_error_event["traceback"] = traceback_text
            if hasattr(agent, "runtime_events"):
                agent.runtime_events.append(runtime_error_event)
            save_session_log(
                agent=agent,
                session_id=session_id,
                started_at=started_at,
                sessions_dir=sessions_dir,
                workspace=current_workspace,
                log_path=log_path,
            )
            print()


def _handle_admin(agent: AgentRuntime):
    permission_manager = agent.tool_loader.permission_manager
    if permission_manager is None:
        print("\nPermissions are disabled.\n")
        return

    print("\n" + "=" * 70)
    print("Permission Mode")
    print("=" * 70)
    print(f"\nCurrent mode: {permission_manager.mode}")
    print("\nOptions:")
    print("  [1] ask - ask before risky actions")
    print("  [2] auto - auto-approve allowed actions")
    print("  [0] cancel")
    print("=" * 70)

    choice = input("Select (1/2/0): ").strip()
    if choice == "1":
        permission_manager.set_mode("ask")
    elif choice == "2":
        permission_manager.set_mode("auto")
    elif choice == "0":
        print("No changes made.")
    else:
        print("Invalid choice.")
    print()


if __name__ == "__main__":
    run_single_agent_cli()
