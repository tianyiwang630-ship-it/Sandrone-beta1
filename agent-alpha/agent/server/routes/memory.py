from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from agent.server.deps import agent_manager, state_store


router = APIRouter(prefix="/api/memory", tags=["memory"])


def call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    documents_auto_update: bool | None = None
    skills_auto_update: bool | None = None
    auto_prompt: str | None = None
    manual_prompt: str | None = None


class EditStart(BaseModel):
    target: str


class DocumentSave(BaseModel):
    edit_id: str
    revision: str
    content: str


class Restoration(BaseModel):
    edit_id: str
    revision: str
    version_id: str


class TaskStart(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    targets: list[str] | None = None


@router.get("/config")
def config():
    return agent_manager.memory.config()


@router.patch("/config")
def update_config(body: ConfigPatch):
    return call(agent_manager.memory.update_config, body.model_dump(exclude_unset=True))


@router.get("/documents/{target}")
def document(target: str):
    return call(agent_manager.memory.document, target)


@router.post("/edits")
def begin_edit(body: EditStart):
    return call(agent_manager.memory.begin_edit, body.target)


@router.delete("/edits/{edit_id}")
def cancel_edit(edit_id: str):
    agent_manager.memory.cancel_edit(edit_id)
    return {"ok": True}


@router.put("/documents/{target}")
def save_document(target: str, body: DocumentSave):
    return call(agent_manager.memory.save_document, target, body.content,
                edit_id=body.edit_id, revision=body.revision)


@router.get("/documents/{target}/versions")
def versions(target: str):
    return call(agent_manager.memory.versions, target)


@router.get("/documents/{target}/versions/{version_id}")
def version(target: str, version_id: str):
    return call(agent_manager.memory.version, target, version_id)


@router.post("/documents/{target}/restorations")
def restore(target: str, body: Restoration):
    return call(agent_manager.memory.restore, target, body.version_id,
                edit_id=body.edit_id, revision=body.revision)


@router.post("/tasks")
def start_task(body: TaskStart):
    return call(agent_manager.memory.start_task, manual=True,
                start=body.start.isoformat() if body.start else None,
                end=body.end.isoformat() if body.end else None,
                targets=body.targets,
                llm_settings=state_store.get_settings())


@router.get("/tasks/current")
def current_task():
    task = agent_manager.memory.current_task()
    return agent_manager.memory._public_task(task) if task else None


@router.get("/tasks/{task_id}")
def task(task_id: str):
    return call(agent_manager.memory.task, task_id)
