from pathlib import Path

import pytest

from agent.core.sandbox_guard import SandboxGuard


@pytest.fixture
def guarded_paths(tmp_path: Path) -> tuple[SandboxGuard, Path, Path]:
    project_root = tmp_path / "agent-alpha"
    workspace_root = tmp_path / "workspace"
    (project_root / "agent" / "core").mkdir(parents=True)
    (project_root / "temp").mkdir()
    (project_root / "cache").mkdir()
    (project_root / "home" / ".agents" / "skills").mkdir(parents=True)
    (project_root / ".venv").mkdir()
    workspace_root.mkdir()
    return SandboxGuard(project_root=project_root, workspace_root=workspace_root), project_root, workspace_root


def test_agent_source_is_readable_but_file_tool_writes_are_denied(guarded_paths):
    guard, project_root, _workspace_root = guarded_paths
    source = project_root / "agent" / "core" / "runtime.py"
    source.write_text("original", encoding="utf-8")

    assert guard.check_tool_call("read", {"file_path": str(source)}).decision == "allow"
    for tool_name in ("write", "edit", "append"):
        assert guard.check_tool_call(tool_name, {"file_path": str(source)}).decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        'echo changed > "{target}"',
        'echo changed | tee "{target}"',
        'sed -i s/original/changed/ "{target}"',
        'rm "{target}"',
        'cp "{workspace_file}" "{target}"',
        'Set-Content -LiteralPath "{target}" -Value changed',
        'powershell -Command "value | Out-File -FilePath \'{target}\'"',
    ],
)
def test_bash_explicit_writes_to_agent_source_are_denied(guarded_paths, command: str):
    guard, project_root, workspace_root = guarded_paths
    target = project_root / "agent" / "core" / "runtime.py"
    workspace_file = workspace_root / "source.txt"
    target.write_text("original", encoding="utf-8")
    workspace_file.write_text("source", encoding="utf-8")

    result = guard.check_tool_call(
        "bash",
        {"command": command.format(target=target, workspace_file=workspace_file)},
    )

    assert result.decision == "deny"


def test_bash_relative_write_paths_use_effective_workspace_cwd(guarded_paths):
    guard, project_root, workspace_root = guarded_paths
    (workspace_root / "agent" / "core").mkdir(parents=True)

    workspace_result = guard.check_tool_call(
        "bash",
        {"command": "echo ok > agent/core/output.txt"},
    )
    protected_result = guard.check_tool_call(
        "bash",
        {"command": "echo blocked > agent/core/output.txt", "working_dir": str(project_root)},
    )

    assert workspace_result.decision == "allow"
    assert protected_result.decision == "deny"


def test_python_command_redirect_cannot_bypass_agent_source_protection(guarded_paths):
    guard, project_root, _workspace_root = guarded_paths
    target = project_root / "agent" / "generated.txt"
    python = project_root / ".venv" / "Scripts" / "python.exe"

    result = guard.check_tool_call(
        "bash",
        {"command": f'"{python}" -c "print(1)" > "{target}"'},
    )

    assert result.decision == "deny"


def test_agent_source_remains_read_only_if_selected_as_workspace(tmp_path: Path):
    project_root = tmp_path / "relocated-alpha"
    workspace_root = project_root / "agent" / "nested-workspace"
    workspace_root.mkdir(parents=True)
    guard = SandboxGuard(project_root=project_root, workspace_root=workspace_root)

    result = guard.check_tool_call(
        "bash",
        {"command": "echo blocked > output.txt"},
    )

    assert result.decision == "deny"


def test_agent_source_parent_traversal_is_denied(guarded_paths):
    guard, project_root, workspace_root = guarded_paths
    nested = workspace_root / "nested"
    nested.mkdir()
    relative_target = Path("..") / ".." / project_root.name / "agent" / "core" / "runtime.py"

    result = guard.check_tool_call(
        "bash",
        {"command": f'echo blocked > "{relative_target}"', "working_dir": str(nested)},
    )

    assert result.decision == "deny"


def test_simple_cd_prefix_uses_same_effective_cwd_as_bash_tool(guarded_paths):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": f'cd "{project_root}" && echo blocked > agent/generated.txt'},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize("directory_command", ["CD", "pushd", "PUSHD"])
def test_windows_directory_prefixes_cannot_desync_sandbox_cwd(guarded_paths, directory_command: str):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": f'{directory_command} "{project_root}" && echo blocked > agent/generated.txt'},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize("command", ["git checkout -- .", "git restore .", "git apply change.patch"])
def test_git_bulk_changes_cannot_touch_agent_source(guarded_paths, command: str):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": command, "working_dir": str(project_root)},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        'git -C "{project_root}" checkout -- .',
        'git -C "{project_root}" restore .',
        'git -C "{project_root}" apply change.patch',
        'git --work-tree="{project_root}" checkout -- .',
    ],
)
def test_git_directory_overrides_cannot_bypass_agent_source_protection(
    guarded_paths, command: str
):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": command.format(project_root=project_root)},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        'git -C "{project_root}" checkout -- agent/core/runtime.py',
        'git -C "{project_root}" restore agent/core/runtime.py',
        'git --work-tree="{project_root}" checkout -- agent/core/runtime.py',
        'git --work-tree="{project_root}" restore agent/core/runtime.py',
    ],
)
def test_git_directory_overrides_use_effective_cwd_for_single_file_changes(
    guarded_paths, command: str
):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": command.format(project_root=project_root)},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize("subcommand", ["checkout --", "restore"])
def test_git_c_and_work_tree_combination_uses_work_tree_for_protection(
    guarded_paths, subcommand: str
):
    guard, project_root, workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {
            "command": (
                f'git -C "{workspace_root}" --work-tree="{project_root}" '
                f"{subcommand} agent/core/runtime.py"
            )
        },
    )

    assert result.decision == "deny"


@pytest.mark.parametrize("subcommand", ["reset --hard", "clean -fd"])
def test_git_c_cannot_bypass_existing_dangerous_command_policy(
    guarded_paths, subcommand: str
):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": f'git -C "{project_root}" {subcommand}'},
    )

    assert result.decision == "deny"


@pytest.mark.parametrize(
    "relative",
    ["temp/output.txt", "cache/item.bin", "home/.agents/skills/demo/SKILL.md", ".venv/tool.txt"],
)
def test_allowed_agent_runtime_directories_remain_writable(guarded_paths, relative: str):
    guard, project_root, _workspace_root = guarded_paths

    result = guard.check_tool_call(
        "bash",
        {"command": f'echo ok > "{relative}"', "working_dir": str(project_root)},
    )

    assert result.decision == "allow"
