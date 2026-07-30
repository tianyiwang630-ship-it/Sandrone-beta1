import os
from pathlib import Path

import pytest

from agent.tools.bash_tool import BashTool


def make_bash_tool(project_root: Path, workspace_root: Path, shell: str) -> BashTool:
    tool = BashTool.__new__(BashTool)
    tool.timeout = 30
    tool.max_timeout = 300
    tool.project_root = project_root.resolve()
    tool.workspace_root = workspace_root.resolve()
    tool.interrupt_event = None
    tool.shell = shell
    return tool


@pytest.mark.parametrize(
    "command",
    [
        "echo hi >nul",
        "echo hi >>nul",
        "echo hi 1>nul",
        "echo hi 2>nul",
        "echo hi 2> nul",
        "echo hi 2>NUL",
        'echo hi 2>>"nul"',
        "echo hi 2>'NuL'",
    ],
)
def test_posix_shell_rejects_cmd_null_redirection_before_starting_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("subprocess must not start")

    monkeypatch.setattr("agent.tools.bash_tool.subprocess.Popen", fail_if_started)

    result = tool.execute(command=command)

    assert result["success"] is False
    assert result["error"] == "POSIX shell 不支持 CMD 的 nul 空设备重定向；命令未执行。"
    assert result["guidance"] == "请使用 /dev/null，例如：2>/dev/null。"
    assert "nul" not in {entry.name.casefold() for entry in os.scandir(workspace_root)}


@pytest.mark.parametrize(
    ("shell", "command"),
    [
        ("bash", "echo hi 2>/dev/null"),
        ("bash", 'echo "2>nul"'),
        ("cmd", "echo hi 2>nul"),
    ],
)
def test_valid_or_non_posix_null_text_is_not_rejected(
    tmp_path: Path,
    shell: str,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, shell)

    assert tool._validate_null_redirection(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "echo '>' nul",
        'echo ">" nul',
        r"echo \> nul",
        "echo hi # >nul",
    ],
)
def test_quoted_escaped_or_commented_redirect_text_is_not_rejected(
    tmp_path: Path,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    assert tool._validate_null_redirection(command) is None


def test_comment_only_skips_current_line_before_real_redirect(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    result = tool._validate_null_redirection(
        "echo before # harmless >nul\n"
        "echo actual >nul"
    )

    assert result is not None


@pytest.mark.parametrize(
    "command",
    [
        "[[ foo > nul ]] && echo yes",
        "echo $((value > nul))",
        "(( value > nul )) && echo yes",
        "cat <<'EOF'\n>nul\nEOF",
    ],
)
def test_non_redirection_bash_contexts_are_not_rejected(
    tmp_path: Path,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    assert tool._validate_null_redirection(command) is None


def test_real_redirect_after_heredoc_is_still_rejected(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    result = tool._validate_null_redirection(
        "cat <<'EOF'\n"
        ">nul\n"
        "EOF\n"
        "echo actual 2>nul"
    )

    assert result is not None


@pytest.mark.parametrize(
    "command",
    [
        '[[ "$(echo hi >nul)" == "" ]]',
        "echo $(( $(echo 1 >nul; echo 1) ))",
        "cat <<EOF\n$(echo hi >nul)\nEOF",
    ],
)
def test_redirect_inside_executed_command_substitution_is_rejected(
    tmp_path: Path,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    assert tool._validate_null_redirection(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        'echo "$(echo "foo" >nul)"',
        'echo "$(printf "%s" hi 2>nul)"',
        'echo "`echo hi >nul`"',
        "cat <<EOF\n`echo hi >nul`\nEOF",
    ],
)
def test_nested_or_legacy_command_substitution_redirect_is_rejected(
    tmp_path: Path,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    assert tool._validate_null_redirection(command) is not None


def test_multiple_quoted_heredoc_bodies_are_not_rejected(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    command = "cat <<'A' <<'B'\nbody A\nA\n>nul\nB"

    assert tool._validate_null_redirection(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "echo foo[[bar >nul",
        "printf %s abc[[def 2>nul",
    ],
)
def test_brackets_inside_word_do_not_hide_real_redirect(
    tmp_path: Path,
    command: str,
):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    assert tool._validate_null_redirection(command) is not None


def test_bash_schema_explains_shell_specific_null_device(tmp_path: Path):
    project_root = tmp_path / "alpha"
    workspace_root = tmp_path / "workspace"
    project_root.mkdir()
    workspace_root.mkdir()
    tool = make_bash_tool(project_root, workspace_root, "bash")

    description = tool.get_tool_definition()["function"]["description"]

    assert "POSIX shell" in description
    assert "/dev/null" in description
    assert "CMD" in description
