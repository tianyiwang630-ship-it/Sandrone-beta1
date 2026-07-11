from pathlib import Path

from agent.core.sandbox_guard import SandboxGuard


def make_guard(project_root: Path, workspace_root: Path) -> SandboxGuard:
    project_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return SandboxGuard(project_root=project_root, workspace_root=workspace_root)


def test_sandbox_denies_bare_pip_install_with_guidance(tmp_path: Path):
    guard = make_guard(tmp_path / "agent-alpha", tmp_path / "workspace")

    result = guard.check_tool_call("bash", {"command": "pip install pymupdf"})

    assert result.decision == "deny"
    assert result.zone == "outside"
    assert "Do not use bare pip or pip3" in result.guidance
    assert "python -m pip install" in result.guidance


def test_sandbox_allows_alpha_bound_python_pip_install(tmp_path: Path):
    guard = make_guard(tmp_path / "agent-alpha", tmp_path / "workspace")

    result = guard.check_tool_call("bash", {"command": "python -m pip install pymupdf"})

    assert result.decision == "allow"
    assert result.zone == "project"


def test_sandbox_allows_uv_pip_install_with_alpha_python(tmp_path: Path):
    guard = make_guard(tmp_path / "agent-alpha", tmp_path / "workspace")

    result = guard.check_tool_call(
        "bash",
        {"command": "uv pip install --python .venv/Scripts/python.exe pymupdf"},
    )

    assert result.decision == "allow"
    assert result.zone == "project"
