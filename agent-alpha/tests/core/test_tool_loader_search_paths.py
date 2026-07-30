import os
from pathlib import Path

import pytest

from agent.core.tool_loader import ToolLoader
from agent.tools.glob_tool import GlobTool
from agent.tools.grep_tool import GrepTool


@pytest.mark.parametrize("tool_name", ["glob", "grep"])
@pytest.mark.parametrize("raw_path", [None, "", "   "])
def test_search_tool_empty_path_defaults_to_workspace(
    tmp_path: Path,
    tool_name: str,
    raw_path: str | None,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "工作区 有空格"
    project_root.mkdir()
    workspace_root.mkdir()
    loader = ToolLoader(
        project_root=project_root,
        workspace_root=workspace_root,
        enable_permissions=False,
    )
    checked: dict[str, object] = {}
    executed: dict[str, object] = {}
    real_check = loader.sandbox_guard.check_tool_call

    def record_check(name, arguments):
        checked.update(arguments)
        return real_check(name, arguments)

    loader.sandbox_guard.check_tool_call = record_check
    loader.tool_executors[tool_name] = lambda **arguments: executed.update(arguments) or "ok"
    arguments = {"pattern": "*.md"}
    if raw_path is not None:
        arguments["path"] = raw_path
    original = dict(arguments)

    assert loader.execute_tool(tool_name, arguments) == "ok"
    assert Path(str(checked["path"])) == workspace_root.resolve()
    assert checked == executed
    assert arguments == original


@pytest.mark.parametrize("tool_name", ["glob", "grep"])
@pytest.mark.parametrize("relative_path", ["shared", "~"])
def test_search_tool_relative_path_uses_workspace_even_when_alpha_has_same_name(
    tmp_path: Path,
    tool_name: str,
    relative_path: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    (project_root / relative_path).mkdir(parents=True)
    (workspace_root / relative_path).mkdir(parents=True)
    loader = ToolLoader(
        project_root=project_root,
        workspace_root=workspace_root,
        enable_permissions=False,
    )
    executed: dict[str, object] = {}
    loader.tool_executors[tool_name] = lambda **arguments: executed.update(arguments) or "ok"

    assert loader.execute_tool(tool_name, {"pattern": "*", "path": relative_path}) == "ok"
    assert Path(str(executed["path"])) == (workspace_root / relative_path).resolve()


@pytest.mark.parametrize("tool_name", ["glob", "grep"])
def test_search_tool_preserves_absolute_alpha_and_outside_read_paths(
    tmp_path: Path,
    tool_name: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    outside_root = tmp_path / "outside"
    project_root.mkdir()
    workspace_root.mkdir()
    outside_root.mkdir()
    loader = ToolLoader(
        project_root=project_root,
        workspace_root=workspace_root,
        enable_permissions=False,
    )
    seen: list[Path] = []
    loader.tool_executors[tool_name] = (
        lambda **arguments: seen.append(Path(str(arguments["path"]))) or "ok"
    )

    assert loader.execute_tool(tool_name, {"pattern": "*", "path": str(project_root)}) == "ok"
    assert loader.execute_tool(tool_name, {"pattern": "*", "path": str(outside_root)}) == "ok"
    assert seen == [project_root.resolve(), outside_root.resolve()]


@pytest.mark.skipif(os.name != "nt", reason="Windows/MSYS path syntax")
@pytest.mark.parametrize("with_colon", [False, True])
def test_search_tool_preserves_msys_absolute_path(tmp_path: Path, with_colon: bool):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    outside_root = tmp_path / "outside"
    project_root.mkdir()
    workspace_root.mkdir()
    outside_root.mkdir()
    loader = ToolLoader(
        project_root=project_root,
        workspace_root=workspace_root,
        enable_permissions=False,
    )
    executed: dict[str, object] = {}
    loader.tool_executors["glob"] = lambda **arguments: executed.update(arguments) or "ok"
    drive = outside_root.drive[0]
    suffix = outside_root.as_posix()[2:]
    raw_path = f"/{drive}:{suffix}" if with_colon else f"/{drive}{suffix}"

    assert loader.execute_tool("glob", {"pattern": "*", "path": raw_path}) == "ok"
    assert Path(str(executed["path"])) == outside_root.resolve()


@pytest.mark.parametrize("tool", [GlobTool(), GrepTool()])
def test_search_tool_schema_explains_workspace_and_absolute_alpha_paths(tool):
    function = tool.get_tool_definition()["function"]
    path_description = function["parameters"]["properties"]["path"]["description"]

    assert "不传或相对路径" in path_description
    assert "workspace" in path_description
    assert "AGENT_ALPHA_ROOT" in path_description
