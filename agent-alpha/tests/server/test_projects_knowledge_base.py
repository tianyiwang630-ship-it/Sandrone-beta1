from __future__ import annotations

from pathlib import Path

from agent.server.models import ProjectInfo
from agent.server.models import ProjectCreate, ProjectPatch
from agent.server.routes import projects
from agent.server.routes.projects import _is_knowledge_base, _to_project_info


def _project(workspace: Path) -> dict[str, object]:
    return {
        "id": "project-1",
        "name": "知识库",
        "workspace_path": str(workspace),
        "workspace_kind": "external",
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T00:00:00+00:00",
    }


def test_project_info_defaults_to_non_knowledge_base_for_old_state(tmp_path: Path):
    info = ProjectInfo(**_project(tmp_path))
    assert info.is_knowledge_base is False


def test_missing_marker_and_empty_alpha_directory_are_not_knowledge_base(tmp_path: Path):
    assert _is_knowledge_base(tmp_path) is False
    (tmp_path / ".alpha").mkdir()
    assert _is_knowledge_base(tmp_path) is False


def test_marker_file_is_enough_even_when_json_is_invalid(tmp_path: Path):
    marker = tmp_path / ".alpha" / "knowledge-base.json"
    marker.parent.mkdir()
    marker.write_text("not json", encoding="utf-8")
    assert _is_knowledge_base(tmp_path) is True


def test_chinese_spaces_and_long_workspace_path_are_supported(tmp_path: Path):
    workspace = tmp_path / ("中文 空格" * 10)
    marker = workspace / ".alpha" / "knowledge-base.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    assert _is_knowledge_base(workspace) is True


def test_missing_workspace_and_workspace_file_fail_closed(tmp_path: Path):
    assert _is_knowledge_base(tmp_path / "missing") is False
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("x", encoding="utf-8")
    assert _is_knowledge_base(workspace_file) is False


def test_marker_resolving_outside_workspace_fails_closed(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    marker = workspace / ".alpha" / "knowledge-base.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside" / "knowledge-base.json"
    original_resolve = Path.resolve

    def fake_resolve(path: Path, strict: bool = False):
        if path == marker:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    assert _is_knowledge_base(workspace) is False


def test_project_response_computes_identity_without_mutating_stored_record(tmp_path: Path):
    marker = tmp_path / ".alpha" / "knowledge-base.json"
    marker.parent.mkdir()
    marker.write_text("broken is accepted", encoding="utf-8")
    stored = _project(tmp_path)

    info = _to_project_info(stored)

    assert info.is_knowledge_base is True
    assert "is_knowledge_base" not in stored


def test_list_detail_create_and_update_all_compute_knowledge_base_identity(tmp_path: Path, monkeypatch):
    marker = tmp_path / ".alpha" / "knowledge-base.json"
    marker.parent.mkdir()
    marker.write_text("{}", encoding="utf-8")
    stored = _project(tmp_path)

    monkeypatch.setattr(projects.state_store, "list_projects", lambda: [stored])
    monkeypatch.setattr(projects.state_store, "get_project", lambda project_id: stored if project_id == "project-1" else None)
    monkeypatch.setattr(projects.state_store, "create_project", lambda **kwargs: stored)
    monkeypatch.setattr(projects.state_store, "update_project", lambda project_id, body: stored)

    responses = [
        projects.list_projects()[0],
        projects.get_project("project-1"),
        projects.create_project(ProjectCreate(name="知识库", workspace_path=str(tmp_path))),
        projects.update_project("project-1", ProjectPatch(name="新名称")),
    ]

    assert all(response.is_knowledge_base for response in responses)
    assert "is_knowledge_base" not in stored


def test_patch_schema_does_not_allow_writing_derived_identity():
    patch = ProjectPatch.model_validate({"name": "新名称", "is_knowledge_base": True})
    assert "is_knowledge_base" not in patch.model_dump()


def test_unreadable_or_unresolvable_workspace_fails_closed(tmp_path: Path, monkeypatch):
    original_resolve = Path.resolve

    def fail_for_workspace(path: Path, strict: bool = False):
        if path == tmp_path:
            raise OSError("access denied")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_for_workspace)
    assert _is_knowledge_base(tmp_path) is False
