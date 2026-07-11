from pathlib import Path

from agent.core.command_path_extractor import classify_package_install_scope


def test_bare_pip_installs_are_denied(tmp_path: Path):
    project_root = tmp_path / "agent-alpha"

    assert classify_package_install_scope("pip install pymupdf", project_root=project_root) == "deny"
    assert classify_package_install_scope("pip2 install pymupdf", project_root=project_root) == "deny"
    assert classify_package_install_scope("pip3 install pymupdf", project_root=project_root) == "deny"
    assert classify_package_install_scope("pip3.11 install pymupdf", project_root=project_root) == "deny"
    assert classify_package_install_scope("pip3.12 install pymupdf", project_root=project_root) == "deny"


def test_pip_named_tools_are_not_misclassified_as_bare_pip(tmp_path: Path):
    project_root = tmp_path / "agent-alpha"

    assert classify_package_install_scope("pipx install some-cli", project_root=project_root) == "ask"
    assert classify_package_install_scope("pipenv install requests", project_root=project_root) == "ask"
    assert classify_package_install_scope("pip-compile requirements.in", project_root=project_root) == "ask"


def test_alpha_python_module_pip_install_is_allowed(tmp_path: Path):
    project_root = tmp_path / "agent-alpha"

    assert classify_package_install_scope("python -m pip install pymupdf", project_root=project_root) == "allowed_alpha_venv"
    assert (
        classify_package_install_scope(
            ".venv/Scripts/python.exe -m pip install pymupdf",
            project_root=project_root,
        )
        == "allowed_alpha_venv"
    )


def test_external_python_module_pip_install_is_denied(tmp_path: Path):
    project_root = tmp_path / "agent-alpha"
    external_python = tmp_path / "other-python" / "python.exe"

    assert (
        classify_package_install_scope(
            f'"{external_python}" -m pip install pymupdf',
            project_root=project_root,
        )
        == "deny"
    )


def test_uv_pip_install_requires_alpha_venv_python(tmp_path: Path):
    project_root = tmp_path / "agent-alpha"
    external_python = tmp_path / "other-python" / "python.exe"

    assert classify_package_install_scope("uv pip install pymupdf", project_root=project_root) == "deny"
    assert (
        classify_package_install_scope(
            "uv pip install --python .venv/Scripts/python.exe pymupdf",
            project_root=project_root,
        )
        == "allowed_alpha_venv"
    )
    assert (
        classify_package_install_scope(
            f'uv pip install --python "{external_python}" pymupdf',
            project_root=project_root,
        )
        == "deny"
    )
