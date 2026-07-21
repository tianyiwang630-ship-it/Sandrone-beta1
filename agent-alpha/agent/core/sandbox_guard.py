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
    extract_git_command_context,
    extract_script_path,
    is_external_executable_invocation,
)
from agent.core.path_policy import decide_path_access, resolve_bash_command_context
from agent.core.sandbox_types import AccessAction, SandboxCheckResult


class SandboxGuard:
    FILE_TOOL_ACTIONS: dict[str, AccessAction] = {
        "read": "read",
        "glob": "read",
        "grep": "read",
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
        target_path = self._extract_path(arguments, tool_name)
        decision, zone = self._decide_path_access(
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
                reason = "The target is protected agent-alpha runtime data"
        elif zone == "outside":
            reason = "Target path is outside both the agent workspace and the agent-alpha project"
        else:
            reason = "Target path could not be classified safely"

        guidance = None
        if decision == "deny" and action in {"write", "delete"}:
            guidance = (
                f"Write project files under {self.workspace_root}. "
                f"Write third-party skills under {self.project_root / 'home' / '.agents' / 'skills'}. "
                f"Write temporary files under {self.project_root / 'temp'}. "
                f"{self.project_root / 'agent'} is read-only."
            )

        return SandboxCheckResult(
            decision=decision,
            action=action,
            zone=zone,
            reason=reason,
            guidance=guidance,
        )

    def _check_bash_command(self, command: str, working_dir: str | None = None) -> SandboxCheckResult:
        try:
            command, cwd = resolve_bash_command_context(
                project_root=self.project_root,
                workspace_root=self.workspace_root,
                command=command,
                working_dir=working_dir,
            )
        except ValueError as exc:
            return SandboxCheckResult(
                decision="deny",
                action="unknown",
                zone="unknown",
                reason=str(exc),
                guidance="Use an existing directory inside the current workspace, or an absolute directory inside AGENT_ALPHA_ROOT.",
            )

        category = classify_bash_command(command)

        if category == "dangerous":
            return SandboxCheckResult(
                decision="deny",
                action="unknown",
                zone="unknown",
                reason="Dangerous system-level bash commands are not allowed",
                guidance="Disallowed examples include sudo, format, mkfs, diskpart, shutdown, reboot, and destructive permission changes.",
            )

        general_write_paths = extract_general_write_paths(command, base_dir=cwd)
        if general_write_paths:
            decisions = [
                self._decide_path_access(
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
                    reason="The bash command appears to write to a path outside the allowed workspace or into read-only agent source",
                    guidance=self._write_path_guidance(general_write_paths, cwd=cwd),
                )
            if any(decision == "ask" for decision, _zone in decisions):
                return SandboxCheckResult(
                    decision="ask",
                    action="write",
                    zone=next(zone for decision, zone in decisions if decision == "ask"),
                    reason="The bash command appears to modify protected agent-alpha runtime files",
                    guidance="Use workspace files or writable agent-alpha runtime directories.",
                )

        git_context = extract_git_command_context(command, base_dir=cwd)
        if git_context is not None:
            git_command, git_cwd, unsafe_override = git_context
            git_category = classify_bash_command(git_command)
            if git_category == "dangerous":
                return SandboxCheckResult(
                    decision="deny",
                    action="write",
                    zone="project" if self._paths_overlap(git_cwd, self.project_root) else "workspace",
                    reason="Dangerous git cleanup or hard reset commands are not allowed",
                    guidance="Use explicit, non-destructive Git operations on individual workspace files.",
                )
            lowered_git_command = git_command.strip().lower()
            is_bulk_restore = lowered_git_command in {"git checkout -- .", "git restore ."}
            is_patch_apply = lowered_git_command.startswith("git apply ")
            if is_bulk_restore or is_patch_apply:
                cwd_decision, cwd_zone = self._decide_path_access(
                    git_cwd,
                    action="write",
                    workspace_root=self.workspace_root,
                    project_root=self.project_root,
                )
                could_touch_agent = (
                    self._paths_overlap(git_cwd, self.project_root / "agent")
                    if is_bulk_restore
                    else self._paths_overlap(git_cwd, self.project_root)
                )
                if unsafe_override or cwd_decision == "deny" or could_touch_agent:
                    return SandboxCheckResult(
                        decision="deny",
                        action="write",
                        zone="project" if could_touch_agent else cwd_zone,
                        reason="Git directory overrides or bulk changes could modify read-only agent source",
                        guidance=f"Apply project changes inside {self.workspace_root}; {self.project_root / 'agent'} is read-only.",
                    )
                if is_bulk_restore:
                    return SandboxCheckResult(
                        decision="ask",
                        action="write",
                        zone=cwd_zone,
                        reason="Bulk git restore commands require user approval",
                        guidance="Restore explicit files when possible so paths can be sandboxed precisely.",
                    )
                return SandboxCheckResult(
                    decision="allow",
                    action="write",
                    zone=cwd_zone,
                    reason="git apply is allowed for workspace patch workflows",
                )
            if unsafe_override and git_category == "path_mutation":
                return SandboxCheckResult(
                    decision="deny",
                    action="write",
                    zone="unknown",
                    reason="Git directory overrides could not be mapped safely for this write command",
                    guidance=f"Use explicit workspace paths; {self.project_root / 'agent'} is read-only.",
                )
            command = git_command
            cwd = git_cwd
            category = git_category

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
                    guidance=(
                        f"{explain_alpha_venv_command_guidance(self.project_root)} "
                        "npm/go global installs are allowed host exceptions."
                    ),
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

        if category == "script_run":
            script_path = extract_script_path(command, base_dir=cwd)
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
            extracted = extract_bash_paths(command, category, base_dir=cwd)
            if extracted is None:
                action: AccessAction = "write" if category == "path_mutation" else "read"
                return SandboxCheckResult(
                    decision="deny",
                    action=action,
                    zone="unknown",
                    reason="This bash command could not be parsed safely",
                    guidance=(
                        f"{explain_parseable_mutation_forms()} {self._write_path_guidance([], cwd=cwd)}"
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
                self._decide_path_access(
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
                        f"{explain_parseable_mutation_forms()} {self._write_path_guidance(paths, cwd=cwd)}"
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

        if is_external_executable_invocation(
            command,
            project_root=self.project_root,
            workspace_root=self.workspace_root,
            base_dir=cwd,
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

    def _decide_path_access(
        self,
        path: Path | None,
        *,
        action: AccessAction,
        workspace_root: Path,
        project_root: Path,
    ) -> tuple[str, str]:
        if path is not None:
            resolved = Path(path).resolve()
            logs_root = (self.project_root / "session-log" / "logs").resolve()
            try:
                resolved.relative_to(logs_root)
            except ValueError:
                pass
            else:
                if action != "read":
                    return "deny", "project"
                return "allow", "project"
        return decide_path_access(
            path,
            action=action,
            workspace_root=workspace_root,
            project_root=project_root,
        )

    @staticmethod
    def _paths_overlap(first: Path, second: Path) -> bool:
        first = first.resolve()
        second = second.resolve()
        try:
            first.relative_to(second)
            return True
        except ValueError:
            pass
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False

    def _write_path_guidance(self, paths: list[Path], *, cwd: Path) -> str:
        allowed_roots = [self.workspace_root, self.project_root / "temp"]
        recommended = (
            f"a path relative to {self.workspace_root}, or an absolute path under "
            f"{self.project_root / 'temp'}"
        )

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
            f"{self.project_root / 'agent'} is read-only."
        )

    def _extract_path(self, arguments: Dict[str, Any], tool_name: str = "") -> Path | None:
        raw_path = arguments.get("path") if tool_name in {"glob", "grep"} else arguments.get("file_path")
        if not raw_path:
            return None
        try:
            return Path(raw_path).resolve()
        except Exception:
            return None
