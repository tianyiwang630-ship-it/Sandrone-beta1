from types import SimpleNamespace

from agent.core.collaboration_tools import install_collaboration_tools
from agent.core.tool_loader import ToolLoader


def test_child_keeps_editing_tools_and_fixed_identity_without_creation_tool(tmp_path):
    loader = ToolLoader(project_root=tmp_path, workspace_root=tmp_path, enable_permissions=True)
    loader._load_builtin_tools()
    permission_manager = loader.permission_manager
    runtime = SimpleNamespace(tools=loader.tools, tool_loader=loader,
                              system_prompt="项目规则", context_manager=SimpleNamespace())
    note = str(tmp_path / "temp" / "subagent-notes-root.md")
    calls = []
    install_collaboration_tools(runtime, {"agent_id": "child", "root_id": "root", "parent_id": "root",
                                         "notes_path": note}, lambda *args: calls.append(args))
    names = {tool["function"]["name"] for tool in runtime.tools}
    assert {"read", "write", "edit", "bash", "agent_message", "agent_wait", "agent_list"} <= names
    assert not any(name.startswith("subagent_") for name in names)
    assert "agent_create" not in names
    assert loader.permission_manager is permission_manager
    assert "项目规则" in runtime.system_prompt
    assert note in runtime.system_prompt
    assert runtime.context_manager.system_prompt == runtime.system_prompt
    loader.tool_executors["agent_message"](target_id="sibling", message="问题")
    assert calls == [("message", {"target_id": "sibling", "message": "问题"})]
    assert not (tmp_path / "temp" / "subagent-notes-root.md").exists()
