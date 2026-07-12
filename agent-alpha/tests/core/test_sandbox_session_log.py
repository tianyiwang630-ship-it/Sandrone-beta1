from pathlib import Path

from agent.core.sandbox_guard import SandboxGuard


def make_guard(tmp_path: Path) -> tuple[SandboxGuard, Path]:
    project_root = tmp_path / "agent-alpha"
    workspace_root = tmp_path / "workspace"
    (project_root / "session-log" / "sessions").mkdir(parents=True)
    (project_root / "session-log" / "events").mkdir(parents=True)
    (project_root / "session-log" / "logs").mkdir(parents=True)
    workspace_root.mkdir()
    return SandboxGuard(project_root=project_root, workspace_root=workspace_root), project_root


def test_session_log_is_read_only_for_agent_file_tools(tmp_path):
    guard, root = make_guard(tmp_path)
    session_path = root / "session-log" / "sessions" / "sess.json"

    assert guard.check_tool_call("read", {"file_path": str(session_path)}).decision == "allow"
    assert guard.check_tool_call("write", {"file_path": str(session_path), "content": "bad"}).decision == "deny"


def test_logs_are_readable_without_runtime_authorization(tmp_path):
    guard, root = make_guard(tmp_path)
    log_file = root / "session-log" / "logs" / "allowed.jsonl"
    other = root / "session-log" / "logs" / "other.jsonl"

    assert guard.check_tool_call("read", {"file_path": str(log_file)}).decision == "allow"
    assert guard.check_tool_call("read", {"file_path": str(other)}).decision == "allow"
    assert guard.check_tool_call("read", {"file_path": str(root / "session-log" / "logs")}).decision == "allow"
    assert guard.check_tool_call("write", {"file_path": str(log_file), "content": "bad"}).decision == "deny"


def test_bash_can_read_logs_but_cannot_write_session_log(tmp_path):
    guard, root = make_guard(tmp_path)
    event_path = root / "session-log" / "events" / "sess.jsonl"
    log_path = root / "session-log" / "logs" / "sess.jsonl"

    assert guard.check_tool_call("bash", {"command": f'echo bad > "{event_path}"'}).decision == "deny"
    assert guard.check_tool_call("bash", {"command": f'cat "{log_path}"'}).decision == "allow"


def test_recursive_search_can_include_logs_because_session_log_is_read_only(tmp_path):
    guard, root = make_guard(tmp_path)
    source_root = root / "agent"
    source_root.mkdir()

    assert guard.check_tool_call("glob", {"pattern": "**/*", "path": str(root)}).decision == "allow"
    assert guard.check_tool_call("grep", {"pattern": "token", "path": str(source_root)}).decision == "allow"
    assert guard.check_tool_call("bash", {"command": "rg token"}).decision == "allow"
    assert guard.check_tool_call("bash", {"command": f'rg token "{source_root}"'}).decision == "allow"
