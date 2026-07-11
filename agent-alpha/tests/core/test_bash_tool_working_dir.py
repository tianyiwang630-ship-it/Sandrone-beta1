from pathlib import Path

import pytest

from agent.core.tool_loader import ToolLoader
from agent.tools.bash_tool import BashTool


def make_bash_tool(project_root: Path, workspace_root: Path) -> BashTool:
    tool = BashTool.__new__(BashTool)
    tool.project_root = project_root.resolve()
    tool.workspace_root = workspace_root.resolve()
    return tool


def test_working_dir_allows_project_root_child(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = project_root / "frontend"
    target.mkdir(parents=True)
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("frontend") == target.resolve()


def test_working_dir_allows_external_workspace_absolute_path(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = workspace_root / "src"
    project_root.mkdir()
    target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir(target) == target.resolve()


def test_working_dir_relative_path_falls_back_to_workspace(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = workspace_root / "src"
    project_root.mkdir()
    target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("src") == target.resolve()


def test_working_dir_relative_path_prefers_project_when_both_exist(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_target = project_root / "shared"
    workspace_target = workspace_root / "shared"
    project_target.mkdir(parents=True)
    workspace_target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("shared") == project_target.resolve()


def test_working_dir_relative_path_uses_workspace_when_project_match_is_file(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_root.mkdir()
    workspace_target = workspace_root / "src"
    workspace_target.mkdir(parents=True)
    (project_root / "src").write_text("not a directory", encoding="utf-8")
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("src") == workspace_target.resolve()


def test_working_dir_rejects_workspace_sibling(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    sibling = tmp_path / "external-workspace-sibling"
    project_root.mkdir()
    workspace_root.mkdir()
    sibling.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="project_root 或当前 workspace"):
        tool._resolve_working_dir(sibling)


def test_working_dir_rejects_parent_escape_from_workspace(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    outside = tmp_path / "outside"
    project_root.mkdir()
    workspace_root.mkdir()
    outside.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="project_root 或当前 workspace"):
        tool._resolve_working_dir(workspace_root / ".." / "outside")


def test_working_dir_rejects_missing_relative_directory(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="已存在的目录"):
        tool._resolve_working_dir("missing")


def test_set_workspace_root_updates_allowed_boundary(tmp_path: Path):
    project_root = tmp_path / "alpha"
    old_workspace = tmp_path / "old-workspace"
    new_workspace = tmp_path / "new-workspace"
    target = new_workspace / "src"
    project_root.mkdir()
    old_workspace.mkdir()
    target.mkdir(parents=True)
    tool = make_bash_tool(project_root, old_workspace)

    tool.set_workspace_root(new_workspace)

    assert tool._resolve_working_dir(target) == target.resolve()


def test_tool_loader_configure_runtime_updates_bash_and_sandbox(tmp_path: Path):
    project_root = tmp_path / "alpha"
    old_workspace = tmp_path / "old-workspace"
    new_workspace = tmp_path / "new-workspace"
    project_root.mkdir()
    old_workspace.mkdir()
    new_workspace.mkdir()
    bash_tool = make_bash_tool(project_root, old_workspace)
    loader = ToolLoader(project_root=project_root, enable_permissions=False, workspace_root=old_workspace)
    loader.tool_instances = {"bash": bash_tool}

    loader.configure_runtime(new_workspace)

    assert bash_tool.workspace_root == new_workspace.resolve()
    assert loader.sandbox_guard.workspace_root == new_workspace.resolve()
