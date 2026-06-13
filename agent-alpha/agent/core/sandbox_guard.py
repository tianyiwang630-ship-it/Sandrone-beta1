from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from agent.core.command_path_extractor import (
    classify_alpha_venv_command_scope,
    classify_bash_command,
    classify_package_install_scope,
    classify_python_launcher_scope,
    explain_alpha_venv_command_guidance,
    explain_parseable_mutation_forms,
    extract_bash_paths,
    extract_general_write_paths,
    extract_script_path,
    is_external_executable_invocation,
)
from agent.core.path_policy import decide_path_access
from agent.core.sandbox_types import AccessAction, SandboxCheckResult


class SandboxGuard:
    FILE_TOOL_ACTIONS: dict[str, AccessAction] = {
        "read": "read",
        "write": "write",
        "append": "write",
        "edit": "write",
    }

    def __init__(self, *, project_root: Path, workspace_root: Path):
        self.project_root = Path(project_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()

    def check_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> SandboxCheckResult:
        if tool_name == "bash":
            return self._check_bash_command(arguments.get("command", ""), arguments.get("working_dir"))

        if tool_name not in self.FILE_TOOL_ACTIONS:
            return SandboxCheckResult(
                decision="allow",
                action="unknown",
                zone="unknown",
                reason="Sandbox not applied to this tool in phase 1",
            )

        action = self.FILE_TOOL_ACTIONS[tool_name]
        target_path = self._extract_path(arguments)
        decision, zone = decide_path_access(
            target_path,
            action=action,
            workspace_root=self.workspace_root,
            project_root=self.project_root,
        )

        if target_path is None:
            reason = "Could not determine the target path for this operation"
        elif zone == "workspace":
            reason = "Target path is inside an allowed workspace"
        elif zone == "project":
            if decision == "allow":
                reason = "Read access is allowed inside the agent-alpha project"
            else:
                reason = "Write access to protected agent-alpha runtime code requires user approval"
        elif zone == "outside":
            reason = "Target path is outside both the agent workspace and the agent-alpha project"
        else:
            reason = "Target path could not be classified safely"

        guidance = None
        if decision == "deny" and action in {"write", "delete"}:
            guidance = (
                "Use a path inside the current workspace or inside agent-alpha. "
                "For skills, write under agent-alpha/skills/<skill-name>. "
                "For temporary files, use agent-alpha/temp."
            )

        return SandboxCheckResult(
            decision=decision,
            action=action,
            zone=zone,
            reason=reason,
            guidance=guidance,
        )

    def _check_bash_command(self, command: str, working_dir: str | None = None) -> SandboxCheckResult:
        category = classify_bash_command(command)

        if category == "dangerous":
            return SandboxCheckResult(
                decision="deny",
                action="unknown",
                zone="unknown",
                reason="Dangerous system-level bash commands are not allowed",
                guidance="Disallowed examples include sudo, format, mkfs, diskpart, shutdown, reboot, and destructive permission changes.",
            )

        python_scope = classify_python_launcher_scope(command, project_root=self.project_root)
        if python_scope == "deny":
            return SandboxCheckResult(
                decision="deny",
                action="read",
                zone="outside",
                reason="Python commands must use agent-alpha's virtual environment",
                guidance=(
                    f"{explain_alpha_venv_command_guidance(self.project_root)} "
                    "Do not override PATH, use the Windows py launcher, conda run, uv --python with external interpreters, or external Python paths."
                ),
            )

        if category == "package_install":
            scope = classify_package_install_scope(command, project_root=self.project_root)
            if scope in {"allowed_host_global", "allowed_alpha_venv"}:
                return SandboxCheckResult(
                    decision="allow",
                    action="write",
                    zone="project",
                    reason="This dependency install matches an allowed alpha dependency boundary",
                )
            if scope == "deny":
                return SandboxCheckResult(
                    decision="deny",
                    action="write",
                    zone="outside",
                    reason="This dependency install would target an external Python environment or unsupported host path",
                    guidance="Use agent-alpha/.venv for Python installs. npm/go global installs are allowed host exceptions.",
                )
            return SandboxCheckResult(
                decision="ask",
                action="write",
                zone="project",
                reason="Package installation or removal commands require user approval",
                guidance="Package installation commands such as pip install or npm install are allowed only after one-time approval.",
            )

        if category == "project_command":
            return SandboxCheckResult(
                decision="allow",
                action="read",
                zone="project",
                reason="Project command execution is allowed for common development workflows",
            )

        alpha_venv_scope = classify_alpha_venv_command_scope(command, project_root=self.project_root)
        if alpha_venv_scope == "allowed_alpha_venv":
            return SandboxCheckResult(
                decision="allow",
                action="write",
                zone="project",
                reason="Command runs through agent-alpha's virtual environment",
            )
        if alpha_venv_scope == "deny":
            return SandboxCheckResult(
                decision="deny",
                action="write",
                zone="outside",
                reason="Python module commands must run through agent-alpha's virtual environment",
                guidance=explain_alpha_venv_command_guidance(self.project_root),
            )

        lowered_command = command.strip().lower()
        if lowered_command in {"git checkout -- .", "git restore ."}:
            return SandboxCheckResult(
                decision="ask",
                action="write",
                zone="project",
                reason="Bulk git restore commands require user approval",
                guidance="Single-file restore commands like git checkout -- file or git restore file can be parsed and sandboxed more precisely.",
            )

        if lowered_command.startswith("git apply "):
            return SandboxCheckResult(
                decision="allow",
                action="write",
                zone="project",
                reason="git apply is allowed for project patch workflows",
            )

        if category == "script_run":
            script_path = extract_script_path(command)
            decision, zone = decide_path_access(
                script_path,
                action="read",
                workspace_root=self.workspace_root,
                project_root=self.project_root,
            )
            if zone in {"workspace", "project"}:
                return SandboxCheckResult(
                    decision="allow",
                    action="read",
                    zone=zone,
                    reason="Script execution is allowed when the script file is inside a workspace or the agent-alpha project",
                )
            return SandboxCheckResult(
                decision="deny",
                action="read",
                zone=zone,
                reason="Script execution is allowed only for scripts inside an agent workspace or the agent-alpha project",
            )

        if category in {"read_only", "path_mutation"}:
            extracted = extract_bash_paths(command, category)
            if extracted is None:
                action: AccessAction = "write" if category == "path_mutation" else "read"
                return SandboxCheckResult(
                    decision="deny",
                    action=action,
                    zone="unknown",
                    reason="This bash command could not be parsed safely",
                    guidance=(
                        f"{explain_parseable_mutation_forms()} {self._write_path_guidance([], working_dir=working_dir)}"
                        if category == "path_mutation"
                        else "Use simple read-only commands with explicit paths when accessing files."
                    ),
                )

            action, paths = extracted
            if not paths:
                return SandboxCheckResult(
                    decision="allow",
                    action=action,
                    zone="unknown",
                    reason="Read-only bash command does not target a file path",
                )

            decisions = [
                decide_path_access(
                    path,
                    action=action,
                    workspace_root=self.workspace_root,
                    project_root=self.project_root,
                )
                for path in paths
            ]

            if any(decision == "deny" for decision, _zone in decisions):
                return SandboxCheckResult(
                    decision="deny",
                    action=action,
                    zone=next(zone for decision, zone in decisions if decision == "deny"),
                    reason="The bash command targets a path outside the allowed workspace or project boundaries",
                    guidance=(
                        f"{explain_parseable_mutation_forms()} {self._write_path_guidance(paths, working_dir=working_dir)}"
                        if category == "path_mutation"
                        else None
                    ),
                )

            if any(decision == "ask" for decision, _zone in decisions):
                return SandboxCheckResult(
                    decision="ask",
                    action=action,
                    zone=next(zone for decision, zone in decisions if decision == "ask"),
                    reason="The bash command modifies files inside the agent-alpha project but outside the current workspace",
                    guidance=explain_parseable_mutation_forms() if category == "path_mutation" else None,
                )

            return SandboxCheckResult(
                decision="allow",
                action=action,
                zone=decisions[0][1],
                reason="The bash command targets only allowed paths",
            )

        general_write_paths = extract_general_write_paths(command)
        if general_write_paths:
            decisions = [
                decide_path_access(
                    path,
                    action="write",
                    workspace_root=self.workspace_root,
                    project_root=self.project_root,
                )
                for path in general_write_paths
            ]
            if any(decision == "deny" for decision, _zone in decisions):
                return SandboxCheckResult(
                    decision="deny",
                    action="write",
                    zone=next(zone for decision, zone in decisions if decision == "deny"),
                    reason="The bash command appears to write to a path outside the allowed workspace or project boundaries",
                    guidance=self._write_path_guidance(general_write_paths, working_dir=working_dir),
                )
            if any(decision == "ask" for decision, _zone in decisions):
                return SandboxCheckResult(
                    decision="ask",
                    action="write",
                    zone=next(zone for decision, zone in decisions if decision == "ask"),
                    reason="The bash command appears to modify protected agent-alpha runtime files",
                    guidance="Use workspace files or agent-alpha runtime directories unless the user explicitly asks to modify core runtime code.",
                )
            return SandboxCheckResult(
                decision="allow",
                action="write",
                zone=decisions[0][1],
                reason="The bash command writes only to allowed workspace or agent-alpha paths",
            )

        if is_external_executable_invocation(
            command,
            project_root=self.project_root,
            workspace_root=self.workspace_root,
        ):
            return SandboxCheckResult(
                decision="allow",
                action="read",
                zone="outside",
                reason="External installed CLI/exe execution is allowed when it does not explicitly write outside agent-alpha or the current workspace",
            )

        return SandboxCheckResult(
            decision="allow",
            action="unknown",
            zone="unknown",
            reason="General shell command is allowed because it does not match dangerous commands or explicit external file writes",
        )

    def _write_path_guidance(self, paths: list[Path], *, working_dir: str | None = None) -> str:
        cwd = self._resolve_working_dir_for_guidance(working_dir)
        allowed_roots = [self.workspace_root, self.project_root / "temp"]
        if cwd == self.project_root:
            recommended = "temp/..."
        else:
            try:
                cwd.relative_to(self.workspace_root)
                recommended = "a path relative to the current workspace, or an explicit path under agent-alpha/temp"
            except ValueError:
                recommended = "temp/... or workspace/..."

        path_bits = []
        for path in paths:
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            path_bits.append(f"{path} -> {resolved}")
        detected = "; ".join(path_bits) if path_bits else "none safely parsed"
        roots = ", ".join(str(root) for root in allowed_roots)
        return (
            f"Detected write paths: {detected}. Current cwd: {cwd}. "
            f"allowed write roots: {roots}. Recommended target: {recommended}. "
            "Because bash starts inside agent-alpha, use temp/... instead of agent-alpha/temp/... for temporary files."
        )

    def _resolve_working_dir_for_guidance(self, working_dir: str | None) -> Path:
        if not working_dir:
            return self.project_root
        try:
            path = Path(working_dir)
            if not path.is_absolute():
                path = self.project_root / path
            resolved = path.resolve()
            resolved.relative_to(self.project_root)
            return resolved
        except Exception:
            return self.project_root

    def _extract_path(self, arguments: Dict[str, Any]) -> Path | None:
        raw_path = arguments.get("file_path")
        if not raw_path:
            return None
        try:
            return Path(raw_path).resolve()
        except Exception:
            return None
