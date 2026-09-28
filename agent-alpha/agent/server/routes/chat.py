from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent.server.deps import agent_manager, state_store
from agent.server.models import (
    ChatRequest,
    ChatStartResponse,
    ChatStatusResponse,
    CompactRequest,
    PermissionDecisionRequest,
    PermissionDecisionResponse,
)
from agent.server.routes.settings import normalize_settings
from agent.server.web_permissions import PermissionConflictError, PermissionNotFoundError

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatStartResponse)
def start_chat(body: ChatRequest):
    settings = normalize_settings(state_store.get_settings())
    try:
        result = agent_manager.submit_chat(
            mode=body.mode,
            session_id=body.session_id,
            message=body.message,
            expected_request_id=body.expected_request_id,
            client_message_id=body.client_message_id,
            permission_mode=str(settings.get("permission_mode") or "ask"),
            llm_settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(result, str):
        return ChatStartResponse(request_id=result, session_id=body.session_id)
    return ChatStartResponse(session_id=body.session_id, **result)


@router.post("/compact", response_model=ChatStartResponse)
def compact_chat_context(body: CompactRequest):
    settings = normalize_settings(state_store.get_settings())
    try:
        request_id = agent_manager.start_compact(
            session_id=body.session_id,
            permission_mode=str(settings.get("permission_mode") or "ask"),
            llm_settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ChatStartResponse(request_id=request_id, session_id=body.session_id)


@router.get("/status/{request_id}", response_model=ChatStatusResponse)
def get_chat_status(request_id: str):
    run = agent_manager.get_run(request_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Chat request not found")
    return ChatStatusResponse(**run)


@router.get("/session-status/{session_id}", response_model=ChatStatusResponse)
def get_session_chat_status(session_id: str):
    run = agent_manager.get_active_run_for_session(session_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No active chat request for session")
    return ChatStatusResponse(**run)


@router.post("/interrupt/{session_id}")
def interrupt_chat(session_id: str):
    interrupted = agent_manager.interrupt(session_id)
    return {"ok": interrupted}


@router.post(
    "/permissions/{permission_id}/decision",
    response_model=PermissionDecisionResponse,
)
def resolve_permission(permission_id: str, body: PermissionDecisionRequest):
    instruction = body.instruction.strip() if body.instruction else None
    if body.decision == "retry_with_context" and not instruction:
        raise HTTPException(status_code=422, detail="instruction is required for retry_with_context")
    try:
        agent_manager.resolve_permission(permission_id, body.decision, instruction)
    except PermissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PermissionDecisionResponse()
