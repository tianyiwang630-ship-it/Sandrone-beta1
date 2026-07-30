"""
Bash Tool - 像 Claude Code 一样执行 bash 命令
"""

import subprocess
import platform
import os
import re
import shlex
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

from agent.core.command_path_extractor import classify_python_launcher_scope, command_uses_python_launcher
from agent.core.path_policy import resolve_bash_command_context, resolve_working_directory
from agent.core.runtime_paths import build_runtime_env, ensure_runtime_directories
from agent.tools.base_tool import BaseTool
from agent.tools.process_utils import subprocess_group_kwargs, terminate_process_tree


class BashTool(BaseTool):
    """Bash 命令执行工具"""

    @property
    def name(self) -> str:
        return "bash"

    def __init__(
        self,
        timeout: int = 30,
        max_timeout: int = 300,
        project_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
        interrupt_event: threading.Event | None = None,
    ):
        """
        初始化 Bash Tool

        Args:
            timeout: default command timeout in seconds.
            max_timeout: maximum per-call timeout in seconds.
        """
        self.timeout = timeout
        self.max_timeout = max_timeout
        self.project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else self.project_root
        self.interrupt_event = interrupt_event
        ensure_runtime_directories(self.project_root)
        self._detect_shell()

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.interrupt_event = interrupt_event

    def set_workspace_root(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def _detect_shell(self):
        """检测可用的 shell"""
        system = platform.system()

        if system == "Windows":
            # Windows 上的优先级：Git Bash（多种路径） > WSL > cmd

            # Git Bash 的常见安装路径
            git_bash_paths = [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                "bash",  # 如果在 PATH 中
            ]

            # 尝试 Git Bash
            for bash_path in git_bash_paths:
                try:
                    result = subprocess.run(
                        [bash_path, "-c", "echo test"],
                        capture_output=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        self.shell = bash_path
                        shell_name = "Git Bash" if "Program Files" in bash_path else "bash"
                        print(f"✅ 检测到 shell: {shell_name}")
                        return
                except:
                    continue

            # 尝试 WSL
            try:
                result = subprocess.run(
                    ["wsl", "bash", "-c", "echo test"],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    self.shell = "wsl"
                    print(f"✅ 检测到 shell: WSL")
                    return
            except:
                pass

            # 默认 cmd
            self.shell = "cmd"
            print(f"⚠️  未找到 bash/WSL，使用默认 shell: cmd")

        else:
            # Linux/Mac 使用 bash
            self.shell = "bash"
            print(f"✅ 使用 shell: bash")

    def get_tool_definition(self) -> Dict[str, Any]:
        """
        返回 OpenAI function calling 格式的工具定义

        Returns:
            工具定义
        """
        return {
            "type": "function",
            "function": {
                "name": "bash",
                "description": (
                    "执行 bash/shell 命令并返回结果。working_dir 不传则使用当前 workspace；"
                    "通常不要在 command 里写 cd ... && ...，需要切换目录时请使用 working_dir。"
                    "POSIX shell 丢弃输出必须使用 /dev/null，不要使用 CMD 的 nul。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的命令（例如：ls -la, cat file.txt, python script.py）"
                        },
                        "working_dir": {
                            "type": "string",
                            "description": (
                                "可选。本次命令的执行目录；相对路径仅按当前 workspace 解析。"
                                "访问 AGENT_ALPHA_ROOT 必须传绝对路径。绝对路径必须位于 "
                                "AGENT_ALPHA_ROOT 或当前 workspace 内；目录必须已存在。"
                            )
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": (
                                f"Optional per-command timeout in seconds. Defaults to {self.timeout} seconds; "
                                "use a larger value for builds, tests, installs, or long file processing. "
                                f"Maximum is {self.max_timeout} seconds."
                            ),
                            "minimum": 1,
                            "maximum": self.max_timeout,
                        }
                    },
                    "required": ["command"]
                }
            }
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行命令

        Args (via kwargs):
            command: 要执行的命令

        Returns:
            执行结果
        """
        command = kwargs.get('command', '')
        working_dir = kwargs.get('working_dir')
        timeout_result = self._resolve_timeout_seconds(kwargs.get("timeout_seconds"))
        if isinstance(timeout_result, dict):
            timeout_result["command"] = command
            return timeout_result
        timeout_seconds = timeout_result

        prepared = self._prepare_command(command, working_dir)
        if prepared.get("error"):
            return prepared

        command = prepared["command"]
        cwd = prepared["cwd"]
        null_redirection_error = self._validate_null_redirection(command)
        if null_redirection_error is not None:
            null_redirection_error["command"] = command
            null_redirection_error["working_dir"] = str(cwd)
            return null_redirection_error

        try:
            # 根据 shell 类型调整命令格式
            if self.shell == "cmd":
                cmd_args = ["cmd", "/c", command]
            elif self.shell == "wsl":
                cmd_args = ["wsl", "bash", "-c", command]
            elif self.shell.endswith(".exe") or "\\" in self.shell:
                # Git Bash 完整路径
                cmd_args = [self.shell, "-c", command]
            else:
                # 普通 bash
                cmd_args = ["bash", "-c", command]

            # 执行命令，轮询 interrupt_event，确保 ESC 能停止外部进程。
            proc = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',  # 明确使用UTF-8编码，避免Windows GBK编码问题
                errors='replace',  # 遇到无法解码的字符用�替换，而不是抛出异常
                cwd=str(cwd),
                env=build_runtime_env(self.project_root, base_env=os.environ),
                **subprocess_group_kwargs(),
            )
            stdout_parts, stderr_parts, reader_threads = self._start_output_readers(proc)

            started_at = time.monotonic()
            while proc.poll() is None:
                if self.interrupt_event is not None and self.interrupt_event.is_set():
                    terminate_process_tree(proc)
                    self._wait_after_stop(proc)
                    self._join_output_readers(reader_threads)
                    stdout, stderr = self._truncate_output("".join(stdout_parts), "".join(stderr_parts))
                    return {
                        "success": False,
                        "interrupted": True,
                        "error": "Command interrupted by ESC",
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": proc.returncode,
                        "command": command,
                        "working_dir": str(cwd),
                    }

                if time.monotonic() - started_at > timeout_seconds:
                    terminate_process_tree(proc)
                    self._wait_after_stop(proc)
                    self._join_output_readers(reader_threads)
                    stdout, stderr = self._truncate_output("".join(stdout_parts), "".join(stderr_parts))
                    return {
                        "success": False,
                        "timed_out": True,
                        "timeout_seconds": timeout_seconds,
                        "error": f"Command timed out after {timeout_seconds}s.",
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": proc.returncode,
                        "command": command,
                        "working_dir": str(cwd),
                        "guidance": self._timeout_guidance(timeout_seconds),
                    }

                time.sleep(0.05)

            self._join_output_readers(reader_threads)
            stdout, stderr = self._truncate_output("".join(stdout_parts), "".join(stderr_parts))

            result = {
                "success": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": proc.returncode,
                "command": command,
                "working_dir": str(cwd),
            }
            guidance = self._python_alias_guidance(stdout, stderr)
            if guidance:
                result["guidance"] = guidance
            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "working_dir": str(cwd),
            }

    def _validate_null_redirection(self, command: str) -> Dict[str, Any] | None:
        if self.shell == "cmd":
            return None
        if not self._has_posix_null_redirection(command):
            return None
        return {
            "success": False,
            "error": "POSIX shell 不支持 CMD 的 nul 空设备重定向；命令未执行。",
            "guidance": "请使用 /dev/null，例如：2>/dev/null。",
            "stdout": "",
            "stderr": "",
            "returncode": None,
        }

    @classmethod
    def _has_posix_null_redirection(cls, command: str) -> bool:
        index = 0
        while index < len(command):
            char = command[index]
            if char == "\\":
                index += 2
                continue
            if char == "'":
                index = cls._skip_quoted_text(command, index)
                continue
            if char == '"':
                index, quote_redirect = cls._scan_double_quoted_text(command, index)
                if quote_redirect:
                    return True
                continue
            if char == "#" and cls._starts_shell_comment(command, index):
                newline = command.find("\n", index)
                if newline == -1:
                    break
                index = newline + 1
                continue
            if cls._starts_conditional_expression(command, index):
                block_end = cls._skip_until_token(command, index + 2, "]]")
                if cls._has_command_substitution_null_redirection(
                    command[index + 2:block_end - 2]
                ):
                    return True
                index = block_end
                continue
            if command.startswith("$((", index):
                block_end = cls._skip_arithmetic(command, index + 3)
                if cls._has_command_substitution_null_redirection(
                    command[index + 3:block_end - 2]
                ):
                    return True
                index = block_end
                continue
            if command.startswith("((", index):
                block_end = cls._skip_arithmetic(command, index + 2)
                if cls._has_command_substitution_null_redirection(
                    command[index + 2:block_end - 2]
                ):
                    return True
                index = block_end
                continue
            if command.startswith("<<", index) and not command.startswith("<<<", index):
                index, same_line_redirect = cls._skip_heredoc(command, index + 2)
                if same_line_redirect:
                    return True
                continue
            if char != ">":
                index += 1
                continue

            index += 2 if index + 1 < len(command) and command[index + 1] == ">" else 1
            while index < len(command) and command[index].isspace():
                index += 1
            target, index = cls._read_shell_word(command, index)
            if target.casefold() == "nul":
                return True
        return False

    @staticmethod
    def _skip_quoted_text(command: str, index: int) -> int:
        quote = command[index]
        index += 1
        while index < len(command):
            if quote == '"' and command[index] == "\\" and index + 1 < len(command):
                index += 2
                continue
            if command[index] == quote:
                return index + 1
            index += 1
        return index

    @classmethod
    def _scan_double_quoted_text(cls, command: str, index: int) -> tuple[int, bool]:
        index += 1
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command.startswith("$(", index) and not command.startswith("$((", index):
                block_end = cls._skip_parenthesized_command(command, index + 2)
                if cls._has_posix_null_redirection(command[index + 2:block_end - 1]):
                    return block_end, True
                index = block_end
                continue
            if command[index] == "`":
                block_end = cls._skip_backtick(command, index)
                if cls._has_posix_null_redirection(command[index + 1:block_end - 1]):
                    return block_end, True
                index = block_end
                continue
            if command[index] == '"':
                return index + 1, False
            index += 1
        return index, False

    @staticmethod
    def _starts_shell_comment(command: str, index: int) -> bool:
        return index == 0 or command[index - 1].isspace() or command[index - 1] in ";|&()"

    @staticmethod
    def _starts_conditional_expression(command: str, index: int) -> bool:
        if not command.startswith("[[", index):
            return False
        has_left_boundary = (
            index == 0
            or command[index - 1].isspace()
            or command[index - 1] in ";|&()"
        )
        after = index + 2
        has_right_boundary = after == len(command) or command[after].isspace()
        return has_left_boundary and has_right_boundary

    @classmethod
    def _skip_until_token(cls, command: str, index: int, token: str) -> int:
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command[index] in {"'", '"'}:
                index = cls._skip_quoted_text(command, index)
                continue
            if command.startswith(token, index):
                return index + len(token)
            index += 1
        return index

    @classmethod
    def _skip_arithmetic(cls, command: str, index: int) -> int:
        depth = 1
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command[index] in {"'", '"'}:
                index = cls._skip_quoted_text(command, index)
                continue
            if command.startswith("((", index):
                depth += 1
                index += 2
                continue
            if command.startswith("))", index):
                depth -= 1
                index += 2
                if depth == 0:
                    return index
                continue
            index += 1
        return index

    @classmethod
    def _skip_heredoc(cls, command: str, index: int) -> tuple[int, bool]:
        delimiter, delimiter_end, strip_tabs, delimiter_is_quoted = (
            cls._read_heredoc_spec(command, index)
        )
        if not delimiter:
            return delimiter_end, False

        line_end = command.find("\n", delimiter_end)
        if line_end == -1:
            return len(command), cls._has_posix_null_redirection(command[delimiter_end:])
        same_line_redirect = cls._has_posix_null_redirection(
            command[delimiter_end:line_end]
        )

        specs = [(delimiter, strip_tabs, delimiter_is_quoted)]
        scan_index = delimiter_end
        while scan_index < line_end:
            if command[scan_index] == "\\":
                scan_index += 2
                continue
            if command[scan_index] in {"'", '"'}:
                scan_index = cls._skip_quoted_text(command, scan_index)
                continue
            if command.startswith("<<", scan_index) and not command.startswith(
                "<<<", scan_index
            ):
                next_spec = cls._read_heredoc_spec(command, scan_index + 2)
                next_delimiter, scan_index, next_strip_tabs, next_is_quoted = next_spec
                if next_delimiter:
                    specs.append((next_delimiter, next_strip_tabs, next_is_quoted))
                continue
            scan_index += 1

        line_start = line_end + 1
        for delimiter, strip_tabs, delimiter_is_quoted in specs:
            body_start = line_start
            while line_start <= len(command):
                line_end = command.find("\n", line_start)
                if line_end == -1:
                    line_end = len(command)
                line = command[line_start:line_end].rstrip("\r")
                if strip_tabs:
                    line = line.lstrip("\t")
                if line == delimiter:
                    body = command[body_start:line_start]
                    if (
                        not delimiter_is_quoted
                        and cls._has_command_substitution_null_redirection(body)
                    ):
                        return line_end, True
                    line_start = line_end + 1 if line_end < len(command) else line_end
                    break
                if line_end == len(command):
                    return len(command), same_line_redirect
                line_start = line_end + 1
        return line_start, same_line_redirect

    @classmethod
    def _read_heredoc_spec(
        cls,
        command: str,
        index: int,
    ) -> tuple[str, int, bool, bool]:
        strip_tabs = index < len(command) and command[index] == "-"
        if strip_tabs:
            index += 1
        while index < len(command) and command[index] in " \t":
            index += 1
        delimiter_start = index
        delimiter, delimiter_end = cls._read_shell_word(command, index)
        delimiter_is_quoted = any(
            char in {"'", '"', "\\"}
            for char in command[delimiter_start:delimiter_end]
        )
        return delimiter, delimiter_end, strip_tabs, delimiter_is_quoted

    @classmethod
    def _has_command_substitution_null_redirection(cls, command: str) -> bool:
        index = 0
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command[index] == "'":
                index = cls._skip_quoted_text(command, index)
                continue
            if command[index] == "`":
                block_end = cls._skip_backtick(command, index)
                if cls._has_posix_null_redirection(command[index + 1:block_end - 1]):
                    return True
                index = block_end
                continue
            if command.startswith("$((", index):
                index += 3
                continue
            if not command.startswith("$(", index):
                index += 1
                continue

            block_end = cls._skip_parenthesized_command(command, index + 2)
            content_end = block_end - 1 if block_end <= len(command) else len(command)
            if cls._has_posix_null_redirection(command[index + 2:content_end]):
                return True
            index = block_end
        return False

    @staticmethod
    def _skip_backtick(command: str, index: int) -> int:
        index += 1
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command[index] == "`":
                return index + 1
            index += 1
        return index

    @classmethod
    def _skip_parenthesized_command(cls, command: str, index: int) -> int:
        depth = 1
        while index < len(command):
            if command[index] == "\\":
                index += 2
                continue
            if command[index] in {"'", '"'}:
                index = cls._skip_quoted_text(command, index)
                continue
            if command[index] == "(":
                depth += 1
            elif command[index] == ")":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        return index

    @staticmethod
    def _read_shell_word(command: str, index: int) -> tuple[str, int]:
        chars: list[str] = []
        quote: str | None = None
        while index < len(command):
            char = command[index]
            if quote is not None:
                if char == quote:
                    quote = None
                    index += 1
                    continue
                if quote == '"' and char == "\\" and index + 1 < len(command):
                    chars.append(command[index + 1])
                    index += 2
                    continue
                chars.append(char)
                index += 1
                continue
            if char.isspace() or char in "<>|&;()":
                break
            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if char == "\\" and index + 1 < len(command):
                chars.append(command[index + 1])
                index += 2
                continue
            chars.append(char)
            index += 1
        return "".join(chars), index

    def _resolve_timeout_seconds(self, value: Any) -> int | Dict[str, Any]:
        if value is None:
            return self.timeout
        if isinstance(value, bool) or not isinstance(value, int):
            return self._timeout_argument_error(value)
        if value < 1 or value > self.max_timeout:
            return self._timeout_argument_error(value)
        return value

    def _timeout_argument_error(self, value: Any) -> Dict[str, Any]:
        return {
            "success": False,
            "error": f"timeout_seconds must be an integer between 1 and {self.max_timeout}.",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "command": "",
            "guidance": (
                f"Use timeout_seconds only when a command is expected to run longer than the "
                f"{self.timeout}s default. The maximum allowed value is {self.max_timeout}s."
            ),
            "invalid_timeout_seconds": value,
        }

    def _timeout_guidance(self, timeout_seconds: int) -> str:
        return (
            f"The command timed out after {timeout_seconds}s. For quick checks, try a simpler command, "
            "avoid shell pipelines, and prefer agent-alpha .venv Python for environment checks. "
            f"For expected long tasks such as builds, tests, installs, or large file processing, retry with "
            f"a larger timeout_seconds value up to {self.max_timeout}s."
        )

    def _prepare_command(self, command: str, working_dir: str | Path | None) -> Dict[str, Any]:
        try:
            command, cwd = resolve_bash_command_context(
                project_root=self.project_root,
                workspace_root=self.workspace_root,
                command=command,
                working_dir=working_dir,
            )
        except ValueError as exc:
            return self._working_dir_error(str(exc), command)

        misplaced_path_error = self._detect_project_root_prefixed_runtime_path(command, cwd)
        if misplaced_path_error:
            return self._working_dir_error(misplaced_path_error, command)

        python_error = self._validate_alpha_python(command)
        if python_error:
            return self._working_dir_error(python_error, command)

        return {
            "success": True,
            "command": command,
            "cwd": cwd,
        }

    def _detect_project_root_prefixed_runtime_path(self, command: str, cwd: Path) -> str | None:
        try:
            cwd.resolve().relative_to(self.project_root)
        except ValueError:
            return None

        protected_runtime_dirs = (
            "home",
            "temp",
            "skills",
            "cache",
            "config",
            "state",
            "workspace",
        )
        project_name = re.escape(self.project_root.name)
        dirs = "|".join(re.escape(item) for item in protected_runtime_dirs)
        pattern = re.compile(
            rf"(?<![\w.:\-/\\])(?:\./)?{project_name}[\\/](?:{dirs})(?:[\\/]|$)",
            re.IGNORECASE,
        )
        match = pattern.search(command)
        if not match:
            return None

        bad_path = match.group(0).replace("\\", "/").rstrip("/")
        relative_path = bad_path.split("/", 1)[1] if "/" in bad_path else bad_path
        return (
            "当前 bash 已经在 AGENT_ALPHA_ROOT 内部，不要写 "
            f"`{bad_path}/...`。请改用 `{relative_path}/...`；"
            "例如使用 `temp/...`、`home/.agents/skills/...` 或 `skills/...`。"
        )

    def _resolve_working_dir(self, working_dir: str | Path | None) -> Path:
        return resolve_working_directory(
            project_root=self.project_root,
            workspace_root=self.workspace_root,
            working_dir=working_dir,
        )

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _working_dir_error(self, message: str, command: str) -> Dict[str, Any]:
        result = {
            "success": False,
            "error": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "command": command,
        }
        if "agent-alpha .venv Python" in message:
            result["guidance"] = self._alpha_python_guidance()
        return result

    def _validate_alpha_python(self, command: str) -> str | None:
        if not command_uses_python_launcher(command):
            return None

        scope = classify_python_launcher_scope(command, project_root=self.project_root)
        if scope == "deny":
            return "Python commands must use agent-alpha .venv Python."

        launcher = self._resolve_alpha_python_launcher(command)
        if launcher is None or not launcher.exists():
            return "Missing agent-alpha .venv Python; Python commands will not fall back to host Python."
        return None

    def _resolve_alpha_python_launcher(self, command: str) -> Path | None:
        try:
            tokens = shlex.split(command, posix=False)
        except ValueError:
            return None
        tokens = [self._strip_quotes(token) for token in tokens if token and token not in {"2>&1", "1>&2"}]
        if not tokens:
            return None

        executable = tokens[0]
        if "/" in executable or "\\" in executable or executable.lower().endswith((".exe", ".cmd", ".bat")):
            path = Path(executable)
            if not path.is_absolute():
                path = self.project_root / path
            return path.resolve()

        launcher = executable.lower()
        scripts_dir = self.project_root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        if os.name == "nt":
            candidates = [scripts_dir / launcher, scripts_dir / f"{launcher}.exe"]
            if launcher == "python":
                candidates.insert(0, scripts_dir / "python.exe")
            if launcher == "python3":
                candidates.insert(0, scripts_dir / "python3.exe")
        else:
            candidates = [scripts_dir / launcher]

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return candidates[0].resolve() if candidates else None

    def _strip_quotes(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value

    def _alpha_python_guidance(self) -> str:
        windows_python = self.project_root / ".venv" / "Scripts" / "python.exe"
        posix_python = self.project_root / ".venv" / "bin" / "python"
        return (
            "Use agent-alpha .venv Python only. "
            f"Windows: {windows_python}; macOS/Linux: {posix_python}. "
            "Do not use py, conda run, external Python paths, or command-local PATH overrides."
        )

    def _start_output_readers(
        self,
        proc: subprocess.Popen[str],
    ) -> tuple[List[str], List[str], List[threading.Thread]]:
        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        threads: List[threading.Thread] = []

        if proc.stdout is not None:
            thread = threading.Thread(target=self._read_stream, args=(proc.stdout, stdout_parts), daemon=True)
            thread.start()
            threads.append(thread)

        if proc.stderr is not None:
            thread = threading.Thread(target=self._read_stream, args=(proc.stderr, stderr_parts), daemon=True)
            thread.start()
            threads.append(thread)

        return stdout_parts, stderr_parts, threads

    def _read_stream(self, stream, output_parts: List[str]) -> None:
        try:
            while True:
                chunk = stream.read(1)
                if not chunk:
                    break
                output_parts.append(chunk)
        except Exception:
            return

    def _join_output_readers(self, threads: List[threading.Thread]) -> None:
        for thread in threads:
            thread.join(timeout=2)

    def _wait_after_stop(self, proc: subprocess.Popen[str]) -> None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _truncate_output(self, stdout: str, stderr: str) -> tuple[str, str]:
        # Claude Code 使用 50,000 字符，我们对齐这个限制。
        max_output_length = 50000

        if stdout and len(stdout) > max_output_length:
            stdout = stdout[:max_output_length] + f"\n... (输出过长，已截断，总长度: {len(stdout)} 字符)"

        if stderr and len(stderr) > max_output_length:
            stderr = stderr[:max_output_length] + f"\n... (错误输出过长，已截断)"

        return stdout, stderr

    def _python_alias_guidance(self, stdout: str, stderr: str) -> str | None:
        combined = f"{stdout}\n{stderr}"
        if "Python was not found" in combined and "Microsoft Store" in combined:
            return self._alpha_python_guidance()
        return None


# ============================================
# 使用示例
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("Bash Tool 测试")
    print("=" * 60)

    # 初始化
    bash = BashTool()

    # 测试命令
    test_commands = [
        "echo 'Hello from Bash!'",
        "ls -la",
        "pwd",
        "python --version"
    ]

    for cmd in test_commands:
        print(f"\n📝 命令: {cmd}")
        result = bash.execute(command=cmd)

        if result.get("success"):
            print(f"✅ 成功")
            print(f"输出:\n{result['stdout']}")
        else:
            print(f"❌ 失败")
            if "error" in result:
                print(f"错误: {result['error']}")
            if result.get("stderr"):
                print(f"stderr:\n{result['stderr']}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
