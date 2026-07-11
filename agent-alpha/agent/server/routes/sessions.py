from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from agent.core.session_store import SessionRecord
from agent.server.deps import agent_manager, state_store
from agent.server.models import (
    MessageItem,
    SessionCreate,
    SessionDetail,
    SessionInfo,
    SessionListResponse,
    SessionPatch,
)

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
