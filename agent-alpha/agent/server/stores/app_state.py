from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.agent_runtime import PROJECT_ROOT


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class AppStateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or PROJECT_ROOT / "state" / "web" / "app_state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        state = self._default_state()
        state.update(data if isinstance(data, dict) else {})
        state["projects"] = list(state.get("projects") or [])
        state["settings"] = {**self._default_settings(), **dict(state.get("settings") or {})}
        state["users"] = list(state.get("users") or self._default_users())
        return state

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)
        return state

    def list_projects(self) -> list[dict[str, Any]]:
        projects = [p for p in self.load()["projects"] if not p.get("is_archived")]
        projects.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        projects.sort(key=lambda item: 0 if item.get("is_pinned") else 1)
        return projects

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        for project in self.load()["projects"]:
            if project.get("id") == project_id and not project.get("is_archived"):
                return project
        return None

    def create_project(
        self,
        *,
        name: str | None,
        workspace_path: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        project_id = new_id("proj")
        workspace_kind = "external" if workspace_path else "managed"
        workspace = (
            Path(workspace_path).expanduser().resolve()
            if workspace_path
            else PROJECT_ROOT / "workspace" / "projects" / project_id
        )
        workspace.mkdir(parents=True, exist_ok=True)
        timestamp = now_iso()
        project_name = str(name or "").strip() or workspace.name or project_id
        project = {
            "id": project_id,
            "name": project_name,
            "workspace_path": str(workspace),
            "workspace_kind": workspace_kind,
            "description": description,
            "created_at": timestamp,
            "updated_at": timestamp,
            "is_pinned": False,
            "is_archived": False,
        }
        state["projects"].append(project)
        self.save(state)
        return project

    def update_project(self, project_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        state = self.load()
        for project in state["projects"]:
            if project.get("id") != project_id or project.get("is_archived"):
                continue
            for key in ("name", "description", "is_pinned"):
                if key in updates:
                    project[key] = updates[key]
            project["updated_at"] = now_iso()
            self.save(state)
            return project
        return None

    def archive_project(self, project_id: str) -> bool:
        state = self.load()
        for project in state["projects"]:
            if project.get("id") != project_id:
                continue
            project["is_archived"] = True
            project["updated_at"] = now_iso()
            self.save(state)
            return True
        return False

    def delete_project(self, project_id: str) -> bool:
        state = self.load()
        original_count = len(state["projects"])
        state["projects"] = [project for project in state["projects"] if project.get("id") != project_id]
        if len(state["projects"]) == original_count:
            return False
        self.save(state)
        return True

    def get_settings(self) -> dict[str, Any]:
        return dict(self.load()["settings"])

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        settings = state["settings"]
        provider = str(updates.get("llm_provider") or settings.get("llm_provider") or "openai")
        api_keys = dict(settings.get("llm_api_keys") or {})
        if updates.get("llm_api_key"):
            api_keys[provider] = str(updates["llm_api_key"])
        settings.update(
            {
                key: value
                for key, value in updates.items()
                if value is not None and key not in {"llm_api_key", "llm_api_keys"}
            }
        )
        settings["llm_api_keys"] = api_keys
        selected_provider = str(settings.get("llm_provider") or provider)
        settings["llm_api_key"] = api_keys.get(
            selected_provider,
            str(settings.get("llm_api_key") or "") if not api_keys else "",
        )
        self.save(state)
        return dict(settings)

    def list_users(self) -> list[dict[str, Any]]:
        return list(self.load()["users"])

    def update_current_user(self, updates: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        user = state["users"][0]
        if updates.get("name"):
            user["name"] = str(updates["name"]).strip()
        self.save(state)
        return dict(user)

    @staticmethod
    def _default_settings() -> dict[str, Any]:
        return {
            "llm_provider": "openai",
            "llm_base_url": "",
            "llm_api_key": "",
            "llm_api_keys": {},
            "llm_model_name": "",
            "permission_mode": "ask",
            "theme": "light",
        }

    @staticmethod
    def _default_users() -> list[dict[str, Any]]:
        return [{"id": "local_admin", "name": "Local Admin", "role": "admin"}]

    @classmethod
    def _default_state(cls) -> dict[str, Any]:
        return {"projects": [], "settings": cls._default_settings(), "users": cls._default_users()}
