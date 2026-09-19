from types import SimpleNamespace
import json

from agent.core.agent_loop import AgentLoop


def test_input_arriving_during_final_generation_continues_same_loop():
    pending, requests, saved = [], [], []

    def generate_with_tools(messages, tools):
        requests.append(messages)
        if len(requests) == 1:
            pending.append({"role": "user", "content": "new direction", "_message_id": "m2"})
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=f"answer {len(requests)}", tool_calls=[]),
        )])

    def take_inputs():
        entries = pending[:]
        pending.clear()
        return entries

    history = []
    loop = AgentLoop(
        llm=SimpleNamespace(generate_with_tools=generate_with_tools), tools=[], tool_loader=None,
        history=history, system_prompt="system", max_turns=5, input_provider=take_inputs,
        checkpoint=lambda messages: saved.append([dict(item) for item in messages]),
    )
    assert loop.run("original") == "answer 2"
    assert len(requests) == 2
    assert all(item.get("content") != "new direction" for item in requests[0])
    assert requests[1][-1]["content"] == "new direction"
    assert history[-2]["_message_id"] == "m2"
    assert saved[-1] == history


def test_shared_edit_conflict_returns_error_and_loop_can_retry(tmp_path):
    from agent.core.tool_loader import ToolLoader
    from agent.tools.edit_tool import EditTool

    path = tmp_path / "shared.txt"
    path.write_text("original", encoding="utf-8")
    editor = EditTool()
    loader = ToolLoader(project_root=tmp_path, workspace_root=tmp_path, enable_permissions=False)
    loader.tool_executors["edit"] = editor.execute
    turns = []

    def generate_with_tools(messages, tools):
        turns.append(messages)
        if len(turns) == 1:
            # Another agent changed the shared document after this agent read it.
            assert editor.execute(file_path=str(path), old_string="original", new_string="other agent")["success"]
        if len(turns) <= 2:
            arguments = {"file_path": str(path), "old_string": "original" if len(turns) == 1 else "other agent",
                         "new_string": "updated after re-read"}
            calls = [SimpleNamespace(id=f"edit{len(turns)}", type="function",
                                     function=SimpleNamespace(name="edit", arguments=json.dumps(arguments)))]
            content = None
        else:
            calls, content = [], "已处理冲突并完成修改"
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
            message=SimpleNamespace(content=content, tool_calls=calls))])

    history = []
    loop = AgentLoop(llm=SimpleNamespace(generate_with_tools=generate_with_tools),
                     tools=[editor.get_tool_definition()], tool_loader=loader, history=history,
                     system_prompt="system", max_turns=5)
    assert loop.run("修改共享文件") == "已处理冲突并完成修改"
    results = [json.loads(entry["content"]) for entry in history if entry["role"] == "tool"]
    assert [result["success"] for result in results] == [False, True]
    assert path.read_text(encoding="utf-8") == "updated after re-read"
