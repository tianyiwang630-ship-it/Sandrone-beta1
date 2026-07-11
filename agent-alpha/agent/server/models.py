from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    workspace_path: str | None = None
    description: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_pinned: bool | None = None


class ProjectInfo(BaseModel):
    id: str
    name: str
    workspace_path: str
    workspace_kind: Literal["managed", "external"]
    description: str | None = None
    created_at: str
    updated_at: str
    is_pinned: bool = False
    is_archived: bool = False


class SessionCreate(BaseModel):
    project_id: str
    title: str | None = None


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    is_pinned: bool | None = None
    is_archived: bool | None = None


class SessionInfo(BaseModel):
    id: str
    project_id: str | None
    title: str
    workspace_path: str
    created_at: str
    updated_at: str
    message_count: int
    is_pinned: bool = False
    is_archived: bool = False


class MessageItem(BaseModel):
    role: str
    content: Any = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class SessionDetail(SessionInfo):
    messages: list[MessageItem]


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo]
    total: int


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class CompactRequest(BaseModel):
    session_id: str


class ChatStartResponse(BaseModel):
    request_id: str
    session_id: str


ChatRunStatus = Literal["running", "success", "failed", "interrupted", "recoverable"]
ChatRunOperation = Literal["chat", "compact"]


class ChatStatusResponse(BaseModel):
    request_id: str
    session_id: str
    status: ChatRunStatus
    operation: ChatRunOperation = "chat"
    started_after_seq: int = 0
    response: str | None = None
    error: str | None = None
    tool_calls_count: int = 0
    recovery_stage: str | None = None
    can_resume: bool = False
    created_at: str
    updated_at: str


class SettingsPatch(BaseModel):
    llm_provider: Literal["openai", "deepseek", "minimax", "zhipu", "kimi", "siliconflow", "custom"] | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model_name: str | None = None
    permission_mode: Literal["ask", "auto"] | None = None
    theme: Literal["light", "dark", "system"] | None = None


class SettingsInfo(BaseModel):
    llm_provider: str = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_api_keys: dict[str, str] = Field(default_factory=dict)
    llm_model_name: str = ""
    has_api_key: bool = False
    permission_mode: str = "ask"
    theme: str = "light"


class FolderPickResponse(BaseModel):
    path: str | None


class UserInfo(BaseModel):
    id: str
    name: str
    role: Literal["admin", "operator", "viewer"]


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)


class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    is_dir: bool


class FileListResponse(BaseModel):
    root: str
    path: str
    items: list[FileInfo]


class FileContentResponse(BaseModel):
    path: str
    name: str
    size: int
    language: str
    content: str | None
    previewable: bool
    message: str | None = None


class FileConflictCheckRequest(BaseModel):
    project_id: str
    target_path: str = ""
    relative_paths: list[str]


class UploadConflictItem(BaseModel):
    path: str
    name: str
    is_dir: bool


class FileConflictCheckResponse(BaseModel):
    has_conflicts: bool
    conflicts: list[UploadConflictItem]


class CreateFolderRequest(BaseModel):
    project_id: str
    target_path: str = ""
    name: str = Field(min_length=1, max_length=120)


class OpenInFolderRequest(BaseModel):
    project_id: str
    path: str


class CapabilityItem(BaseModel):
    name: str
    kind: Literal["skill", "mcp"]
    path: str
    summary: str | None = None


class CapabilityResponse(BaseModel):
    items: list[CapabilityItem]
