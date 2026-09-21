from pathlib import Path

from agent.core.runtime_layout import RuntimeLayout, runtime_python


def test_development_layout_keeps_app_and_data_together(tmp_path: Path):
    layout = RuntimeLayout.from_env({"AGENT_ALPHA_APP_ROOT": str(tmp_path)})

    assert layout.app_root == tmp_path.resolve()
    assert layout.data_root == tmp_path.resolve()
    assert layout.packaged is False
    assert runtime_python(tmp_path).name == "python.exe"


def test_packaged_layout_separates_resources_and_user_data(tmp_path: Path):
    app_root = tmp_path / "installed" / "resources" / "agent-alpha"
    data_root = tmp_path / "local-app-data" / "AgentAlpha"
    backend_python = app_root / "runtime" / "backend-python" / "python.exe"
    browser_python = app_root / "runtime" / "browser-python" / "python.exe"
    layout = RuntimeLayout.from_env(
        {
            "AGENT_ALPHA_APP_ROOT": str(app_root),
            "AGENT_ALPHA_ROOT": str(data_root),
            "AGENT_ALPHA_PYTHON": str(backend_python),
            "AGENT_ALPHA_BROWSER_PYTHON": str(browser_python),
            "AGENT_ALPHA_NODE_EXECUTABLE": str(tmp_path / "Agent Alpha.exe"),
        }
    )

    assert layout.app_root == app_root.resolve()
    assert layout.data_root == data_root.resolve()
    assert layout.python_executable == backend_python.resolve()
    assert layout.browser_python_executable == browser_python.resolve()
    assert layout.packaged is True
