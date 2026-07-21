from pathlib import Path

import pytest

from agent.core.runtime_paths import build_runtime_env
from agent.core.tool_loader import ToolLoader
from agent.tools.bash_tool import BashTool


def make_bash_tool(project_root: Path, workspace_root: Path) -> BashTool:
    tool = BashTool.__new__(BashTool)
    tool.timeout = 30
    tool.max_timeout = 300
    tool.project_root = project_root.resolve()
    tool.workspace_root = workspace_root.resolve()
    return tool


def test_working_dir_defaults_to_workspace_root(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir(None) == workspace_root.resolve()


def test_working_dir_allows_project_root_absolute_child(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = project_root / "frontend"
    target.mkdir(parents=True)
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir(target) == target.resolve()


def test_working_dir_allows_external_workspace_absolute_path(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = workspace_root / "src"
    project_root.mkdir()
    target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir(target) == target.resolve()


def test_working_dir_relative_path_uses_workspace(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    target = workspace_root / "src"
    project_root.mkdir()
    target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("src") == target.resolve()


def test_working_dir_relative_path_prefers_workspace_when_both_exist(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_target = project_root / "shared"
    workspace_target = workspace_root / "shared"
    project_target.mkdir(parents=True)
    workspace_target.mkdir(parents=True)
    tool = make_bash_tool(project_root, workspace_root)

    assert tool._resolve_working_dir("shared") == workspace_target.resolve()


def test_working_dir_relative_path_does_not_fall_back_to_project(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_target = project_root / "src"
    project_target.mkdir(parents=True)
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="已存在的目录"):
        tool._resolve_working_dir("src")


def test_bash_schema_explains_workspace_relative_and_absolute_harness_rules(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    definition = tool.get_tool_definition()
    function = definition["function"]
    working_dir_description = function["parameters"]["properties"]["working_dir"]["description"]

    assert "不传则使用当前 workspace" in function["description"]
    assert "相对路径仅按当前 workspace 解析" in working_dir_description
    assert "访问 AGENT_ALPHA_ROOT 必须传绝对路径" in working_dir_description


def test_working_dir_rejects_workspace_sibling(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    sibling = tmp_path / "external-workspace-sibling"
    project_root.mkdir()
    workspace_root.mkdir()
    sibling.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="AGENT_ALPHA_ROOT 或当前 workspace"):
        tool._resolve_working_dir(sibling)


def test_working_dir_rejects_parent_escape_from_workspace(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    outside = tmp_path / "outside"
    project_root.mkdir()
    workspace_root.mkdir()
    outside.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    with pytest.raises(ValueError, match="AGENT_ALPHA_ROOT 或当前 workspace"):
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


def test_workspace_cwd_does_not_change_harness_runtime_env(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "external-workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root)

    env = build_runtime_env(project_root, base_env={})

    assert tool._resolve_working_dir(None) == workspace_root.resolve()
    assert Path(env["HOME"]) == (project_root / "home").resolve()
    assert Path(env["TEMP"]) == (project_root / "temp").resolve()
    assert Path(env["PIP_CACHE_DIR"]) == (project_root / "cache" / "pip").resolve()
    assert Path(env["VIRTUAL_ENV"]) == (project_root / ".venv").resolve()


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
