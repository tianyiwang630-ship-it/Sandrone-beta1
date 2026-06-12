"""
Bash Tool - 像 Claude Code 一样执行 bash 命令
"""

import subprocess
import platform
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

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
        timeout: int = 300,
        project_root: str | Path | None = None,
        interrupt_event: threading.Event | None = None,
    ):
        """
        初始化 Bash Tool

        Args:
            timeout: 命令超时时间（秒，默认 300 秒 = 5 分钟）
        """
        self.timeout = timeout
        self.project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
        self.interrupt_event = interrupt_event
        ensure_runtime_directories(self.project_root)
        self._detect_shell()

    def set_interrupt_event(self, interrupt_event: threading.Event | None) -> None:
        self.interrupt_event = interrupt_event

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
                    "执行 bash/shell 命令并返回结果。命令默认在当前 project_root 执行；"
                    "通常不要在 command 里写 cd ... && ...，需要切换目录时请使用 working_dir。"
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
                                "可选。本次命令的执行目录；相对路径按 project_root 解析，"
                                "绝对路径必须位于 project_root 内。不传则默认使用 project_root。"
                            )
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

        prepared = self._prepare_command(command, working_dir)
        if prepared.get("error"):
            return prepared

        command = prepared["command"]
        cwd = prepared["cwd"]

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

                if time.monotonic() - started_at > self.timeout:
                    terminate_process_tree(proc)
                    self._wait_after_stop(proc)
                    self._join_output_readers(reader_threads)
                    stdout, stderr = self._truncate_output("".join(stdout_parts), "".join(stderr_parts))
                    return {
                        "success": False,
                        "error": f"命令超时（>{self.timeout}秒）",
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": proc.returncode,
                        "command": command,
                        "working_dir": str(cwd),
                    }

                time.sleep(0.05)

            self._join_output_readers(reader_threads)
            stdout, stderr = self._truncate_output("".join(stdout_parts), "".join(stderr_parts))

            return {
                "success": proc.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": proc.returncode,
                "command": command,
                "working_dir": str(cwd),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "working_dir": str(cwd),
            }

    def _prepare_command(self, command: str, working_dir: str | Path | None) -> Dict[str, Any]:
        try:
            command, cd_working_dir = self._split_simple_cd_prefix(command)
        except ValueError as exc:
            return self._working_dir_error(str(exc), command)

        if cd_working_dir is not None:
            if working_dir:
                return self._working_dir_error(
                    "command 中已包含 cd 前缀，请不要同时传 working_dir；请只使用 working_dir 指定目录。",
                    command,
                )
            working_dir = cd_working_dir

        try:
            cwd = self._resolve_working_dir(working_dir)
        except ValueError as exc:
            return self._working_dir_error(str(exc), command)

        misplaced_path_error = self._detect_project_root_prefixed_runtime_path(command, cwd)
        if misplaced_path_error:
            return self._working_dir_error(misplaced_path_error, command)

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
        if working_dir in (None, ""):
            return self.project_root

        path = self._path_from_user_input(working_dir).expanduser()
        if not path.is_absolute():
            path = self.project_root / path

        resolved = path.resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("working_dir 必须位于 project_root 内部。") from exc

        if not resolved.is_dir():
            raise ValueError("working_dir 必须是已存在的目录。")

        return resolved

    def _path_from_user_input(self, path: str | Path) -> Path:
        text = str(path)
        if os.name == "nt" and len(text) > 3 and text[0] == "/" and text[2] == "/" and text[1].isalpha():
            return Path(f"{text[1].upper()}:{text[2:]}")
        return Path(text)

    def _split_simple_cd_prefix(self, command: str) -> tuple[str, str | None]:
        stripped = command.strip()
        if not stripped.startswith("cd "):
            return command, None

        parts = stripped.split("&&")
        if len(parts) != 2:
            raise ValueError("检测到复杂 cd 用法，请把目录放到 working_dir 参数里。")

        cd_part, rest = parts[0].strip(), parts[1].strip()
        if not rest:
            raise ValueError("cd 后缺少要执行的命令，请把目录放到 working_dir 参数里。")

        cd_tokens = cd_part.split(maxsplit=1)
        if len(cd_tokens) != 2:
            raise ValueError("cd 后缺少目录，请把目录放到 working_dir 参数里。")

        target = cd_tokens[1].strip()
        if any(token in target for token in ("$", "`", "|", ";", "&")):
            raise ValueError("检测到复杂 cd 目录表达式，请把目录放到 working_dir 参数里。")

        if (target.startswith('"') and target.endswith('"')) or (target.startswith("'") and target.endswith("'")):
            target = target[1:-1]

        if not target:
            raise ValueError("cd 后缺少目录，请把目录放到 working_dir 参数里。")

        return rest, target

    def _working_dir_error(self, message: str, command: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": message,
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "command": command,
        }

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
