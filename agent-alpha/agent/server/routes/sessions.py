from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from agent.core.session_store import SessionRecord
from agent.server.deps import agent_manager, state_store
from agent.server.models import (
    MessageItem,
    ChatStartResponse,
    RetrospectiveRequest,
    RetrospectiveStartResponse,
    SessionCreate,
    SessionDetail,
    SessionInfo,
    SessionListResponse,
    SessionPatch,
)
from agent.server.routes.settings import normalize_settings

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _read_event_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    index = 0
    events: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        event, next_index = decoder.raw_decode(text, index)
        if isinstance(event, dict):
            events.append(event)
        index = next_index
    return events


def _message_history_from_events(path: Path) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for event in _read_event_file(path):
        entry = event.get("entry")
        if not isinstance(entry, dict):
            continue
        if entry.get("role") not in {"user", "assistant", "tool"}:
            continue
        messages.append(dict(entry))
    return messages


def _count_user_messages(history: list[dict[str, Any]]) -> int:
    return sum(1 for item in history if item.get("role") == "user")


def _display_history_for_record(record: SessionRecord) -> list[dict[str, Any]]:
    history = [dict(message) for message in record.history]
    event_path = agent_manager.events_dir / f"{record.session_id}.jsonl"
    event_history = _message_history_from_events(event_path)
    event_user_count = _count_user_messages(event_history)
    history_user_count = _count_user_messages(history)
    if event_user_count > history_user_count:
        return event_history
    if event_history and event_user_count >= history_user_count and len(event_history) > len(history):
        return event_history
    return history


def to_session_info(record: SessionRecord) -> SessionInfo:
    metadata = record.metadata or {}
    title = str(metadata.get("title") or record.title or "新对话")
    return SessionInfo(
        id=record.session_id,
        project_id=metadata.get("project_id"),
        title=title,
        workspace_path=record.workspace,
        created_at=record.created_at,
        updated_at=record.updated_at,
        message_count=len(record.history),
        is_pinned=bool(metadata.get("is_pinned")),
        is_archived=bool(metadata.get("is_archived")),
    )


@router.get("", response_model=SessionListResponse)
def list_sessions(project_id: str | None = None):
    sessions = [to_session_info(record) for record in agent_manager.list_sessions(project_id=project_id)]
    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.post("", response_model=SessionInfo)
def create_session(body: SessionCreate):
    project = state_store.get_project(body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    record = agent_manager.create_session(
        project_id=body.project_id,
        workspace=Path(project["workspace_path"]),
        title=body.title,
    )
    return to_session_info(record)


@router.post("/retrospective", response_model=RetrospectiveStartResponse)
def create_retrospective(body: RetrospectiveRequest):
    project = state_store.get_project(body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.scope == "session":
        if not body.source_session_id:
            raise HTTPException(status_code=422, detail="source_session_id is required for session retrospective")
        source = agent_manager.store.load(body.source_session_id)
        if source is None or source.metadata.get("project_id") != body.project_id:
            raise HTTPException(status_code=404, detail="Source session not found in project")
        source_records = [source]
    else:
        source_records = agent_manager.list_sessions(project_id=body.project_id, include_archived=True)

    source_records = list(source_records)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    scope_id = body.source_session_id if body.scope == "session" else body.project_id
    scope_label = "会话" if body.scope == "session" else "项目"
    review_key = f"{timestamp}-{body.scope}-{scope_id}"
    review_root = Path(project["workspace_path"]) / "复盘"
    process_dir = review_root / ".过程" / review_key
    human_report = review_root / f"{review_key}-工作复盘.md"
    ai_report = review_root / f"{review_key}-AI交接报告.md"

    source_lines: list[str] = []
    active_sessions: list[str] = []
    for source in source_records:
        title = str(source.metadata.get("title") or source.title or source.session_id)
        event_path = agent_manager.events_dir / f"{source.session_id}.jsonl"
        log_path = agent_manager.logs_dir / f"{source.session_id}.jsonl"
        source_lines.append(f"- 会话 {source.session_id}：{title}")
        source_lines.append(f"  - event：{event_path if event_path.exists() else '不存在'}")
        source_lines.append(f"  - log：{log_path if log_path.exists() else '不存在'}")
        if agent_manager.get_active_run_for_session(source.session_id) is not None:
            active_sessions.append(source.session_id)

    active_notice = (
        "以下来源会话仍在运行，本次复盘以读取时已经落盘的内容为准：" + "、".join(active_sessions)
        if active_sessions
        else "所有来源会话当前均未运行。"
    )
    prompt = "\n".join(
        [
            "[系统复盘任务]",
            "",
            f"这是一次{scope_label}复盘。请显式加载 retrospective Skill，并严格按照 Skill 执行。",
            "复盘过程中必须显式加载 planwithfile Skill，使用文件保存计划、发现和进度。",
            active_notice,
            "",
            "来源资料（event 是主要材料，只有信息不足时才读取对应 log）：",
            *(source_lines or ["- 当前范围没有可读取的历史会话。"]),
            "",
            f"过程文件目录：{process_dir}",
            f"给人看的工作复盘：{human_report}",
            f"给 AI 看的交接报告：{ai_report}",
            "",
            "项目复盘时，跳过第一条用户消息包含 [系统复盘任务] 的历史复盘会话，也不要读取复盘目录中的旧报告作为来源。",
        ]
    )

    title_source = project["name"] if body.scope == "project" else str(source_records[0].metadata.get("title") or scope_id)
    record = agent_manager.create_session(
        project_id=body.project_id,
        workspace=Path(project["workspace_path"]),
        title=f"{scope_label}复盘 · {title_source}",
    )
    settings = normalize_settings(state_store.get_settings())
    try:
        request_id = agent_manager.start_chat(
            session_id=record.session_id,
            message=prompt,
            permission_mode=str(settings.get("permission_mode") or "ask"),
            llm_settings=settings,
            runtime_metadata={"retrospective_scope": body.scope},
        )
    except Exception:
        agent_manager.delete_session(record.session_id)
        raise

    return RetrospectiveStartResponse(
        session=to_session_info(record),
        run=ChatStartResponse(request_id=request_id, session_id=record.session_id),
    )


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str):
    record = agent_manager.get_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    info = to_session_info(record)
    messages = _display_history_for_record(record)
    info.message_count = len(messages)
    return SessionDetail(
        **info.model_dump(),
        messages=[MessageItem(**message) for message in messages],
    )


@router.get("/{session_id}/events")
def get_session_events(session_id: str):
    record = agent_manager.get_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    path = agent_manager.events_dir / f"{session_id}.jsonl"
    return {"events": _read_event_file(path)}


@router.patch("/{session_id}", response_model=SessionInfo)
def update_session(session_id: str, body: SessionPatch):
    record = agent_manager.update_session(session_id, body.model_dump(exclude_none=True))
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return to_session_info(record)


@router.delete("/{session_id}")
def delete_session(session_id: str):
    record = agent_manager.get_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_manager.delete_session(session_id)
    return {"ok": True}
