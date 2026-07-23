from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException
from tkinter import Tk, filedialog

from agent.core.agent_runtime import PROJECT_ROOT
from agent.server.deps import agent_manager, state_store
from agent.server.models import FolderPickResponse, ProjectCreate, ProjectInfo, ProjectPatch, SessionListResponse
from agent.server.routes.sessions import to_session_info

router = APIRouter(prefix="/api/projects", tags=["projects"])

KNOWLEDGE_BASE_MARKER = Path(".alpha") / "knowledge-base.json"


def _is_knowledge_base(workspace_path: str | Path) -> bool:
    try:
        workspace = Path(workspace_path).resolve(strict=True)
        if not workspace.is_dir():
            return False
        marker = (workspace / KNOWLEDGE_BASE_MARKER).resolve(strict=False)
        marker.relative_to(workspace)
        return marker.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def _to_project_info(project: dict[str, object]) -> ProjectInfo:
    payload = dict(project)
    payload["is_knowledge_base"] = _is_knowledge_base(str(project.get("workspace_path", "")))
    return ProjectInfo(**payload)


def _default_picker_dir() -> Path:
    default_dir = PROJECT_ROOT.parent
    if default_dir.exists():
        return default_dir
    return Path.cwd()


def _host_user_profile(env: dict[str, str] | os._Environ[str] = os.environ) -> Path | None:
    if os.name != "nt":
        return None
    username = env.get("USERNAME")
    candidates: list[Path] = []
    public_dir = env.get("PUBLIC")
    if public_dir and username:
        candidates.append(Path(public_dir).parent / username)
    system_drive = env.get("SystemDrive") or env.get("SYSTEMDRIVE") or "C:"
    if username:
        candidates.append(Path(system_drive) / "Users" / username)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


@contextmanager
def _temporary_host_profile_env():
    profile = _host_user_profile()
    if profile is None:
        yield
        return

    keys = ("USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH")
    old_values = {key: os.environ.get(key) for key in keys}
    drive = profile.drive
    os.environ["USERPROFILE"] = str(profile)
    os.environ["HOME"] = str(profile)
    if drive:
        os.environ["HOMEDRIVE"] = drive
        os.environ["HOMEPATH"] = str(profile)[len(drive) :] or "\\"

    try:
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _pick_folder() -> str | None:
    with _temporary_host_profile_env():
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(title="选择项目文件夹", initialdir=str(_default_picker_dir()))
        finally:
            root.destroy()
    return str(Path(selected).resolve()) if selected else None


@router.get("", response_model=list[ProjectInfo])
def list_projects():
    return [_to_project_info(project) for project in state_store.list_projects()]


@router.post("", response_model=ProjectInfo)
def create_project(body: ProjectCreate):
    project = state_store.create_project(
        name=body.name,
        workspace_path=body.workspace_path,
        description=body.description,
    )
    return _to_project_info(project)


@router.get("/pick-folder", response_model=FolderPickResponse)
def pick_folder():
    return FolderPickResponse(path=_pick_folder())


@router.get("/{project_id}", response_model=ProjectInfo)
def get_project(project_id: str):
    project = state_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_project_info(project)


@router.patch("/{project_id}", response_model=ProjectInfo)
def update_project(project_id: str, body: ProjectPatch):
    project = state_store.update_project(project_id, body.model_dump(exclude_none=True))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_project_info(project)


@router.delete("/{project_id}")
def delete_project(project_id: str):
    project = state_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    agent_manager.delete_project_sessions(project_id)
    state_store.delete_project(project_id)
    return {"ok": True}


@router.get("/{project_id}/sessions", response_model=SessionListResponse)
def list_project_sessions(project_id: str):
    project = state_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    sessions = [to_session_info(record) for record in agent_manager.list_sessions(project_id=project_id)]
    return SessionListResponse(sessions=sessions, total=len(sessions))
