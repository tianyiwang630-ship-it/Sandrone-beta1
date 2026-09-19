from agent.tools.browser_harness_runtime import BrowserHarnessRuntime, build_browser_harness_env


def test_browser_resources_are_scoped_to_agent_without_changing_project_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_ALPHA_BROWSER_SCOPE", "agent_first")
    first = BrowserHarnessRuntime(tmp_path)
    first_env = build_browser_harness_env(tmp_path)
    monkeypatch.setenv("AGENT_ALPHA_BROWSER_SCOPE", "agent_second")
    second = BrowserHarnessRuntime(tmp_path)
    second_env = build_browser_harness_env(tmp_path)
    assert first.profile_dir != second.profile_dir
    assert first_env["BH_RUNTIME_DIR"] != second_env["BH_RUNTIME_DIR"]
    assert first_env["BU_NAME"] != second_env["BU_NAME"]
    assert first.project_root == second.project_root == tmp_path
    assert first_env["BH_HOME"] == str(first.state_dir)
