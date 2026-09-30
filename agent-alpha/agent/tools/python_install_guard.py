"""Serialize additive installs into Alpha's shared Python."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from agent.tools.browser_harness_lock import BrowserFileLock
from agent.core.command_path_extractor import has_shell_control
from agent.tools.process_utils import subprocess_group_kwargs, terminate_process_tree


def shared_install_args(command: str, shared_python: Path, *, cwd: Path | None = None) -> tuple[list[str], str] | None:
    """Accept only a direct uv/pip install; other commands use the usual Bash route."""
    if has_shell_control(command):
        return None
    try:
        args = [token.strip('"\'') for token in shlex.split(command, posix=False)]
    except ValueError:
        return None
    if len(args) < 4:
        return None
    first = Path(args[0]).name.lower()
    def is_shared(value: str) -> bool:
        path = Path(value)
        if not path.is_absolute():
            path = (cwd or Path.cwd()) / path
        return path.resolve() == shared_python.resolve()
    if first in {"uv", "uv.exe"} and args[1:3] == ["pip", "install"]:
        for index, value in enumerate(args[:-1]):
            if value in {"--python", "-p"} and is_shared(args[index + 1]):
                return args, "uv"
        if any(value.startswith("--python=") and is_shared(value.split("=", 1)[1]) for value in args):
            return args, "uv"
    if is_shared(args[0]) and args[1:4] == ["-m", "pip", "install"]:
        return args, "pip"
    return None


def _check_arguments(args: list[str], manager: str) -> None:
    """Keep the shared environment route limited to additive installs."""
    options_with_value = {
        "-r", "--requirement", "-c", "--constraint", "--index-url",
        "--extra-index-url", "--find-links", "--trusted-host",
    }
    if manager == "uv":
        options_with_value.update({"--python", "-p"})
        start = 3
    else:
        start = 4
    options_without_value = {"--pre", "--no-config", "--no-python-downloads", "--no-index"}
    index = start
    found_requirement = False
    while index < len(args):
        value = args[index]
        option = value.split("=", 1)[0]
        if option in options_with_value:
            if "=" not in value:
                if index + 1 >= len(args) or args[index + 1].startswith("-"):
                    raise ValueError(f"缺少安装参数 {option} 的值。")
                index += 1
            if option in {"-r", "--requirement"}:
                found_requirement = True
        elif value in options_without_value:
            pass
        elif value.startswith("-"):
            raise ValueError(f"共用环境安装不支持参数 {option}；请使用独立环境或简化命令。")
        else:
            found_requirement = True
            if value.startswith((".", "/", "-e", "file:")) or " @ " in value:
                raise ValueError("共用环境安装暂不支持本地源码或可编辑依赖。")
        index += 1
    if not found_requirement:
        raise ValueError("没有指定需要安装的依赖。")


def _input_files(args: list[str], cwd: Path) -> dict[Path, bytes]:
    """Snapshot requirements including nested references, preserving original paths."""
    pending: list[Path] = []
    for index, token in enumerate(args[:-1]):
        if token in {"-r", "--requirement", "-c", "--constraint"}:
            pending.append((cwd / args[index + 1]).resolve())
    for token in args:
        if token.startswith(("--requirement=", "--constraint=")):
            pending.append((cwd / token.split("=", 1)[1]).resolve())
    snapshots: dict[Path, bytes] = {}
    while pending:
        path = pending.pop()
        if path in snapshots:
            continue
        data = path.read_bytes()
        snapshots[path] = hashlib.sha256(data).digest()
        for line in data.decode("utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"(?:-r|--requirement|-c|--constraint)(?:=|\s+)([^#\s]+)", line)
            if match:
                pending.append((path.parent / match.group(1)).resolve())
            elif line.startswith(("-", ".", "/", "file:")) or " @ " in line:
                raise ValueError("共用环境安装暂不支持清单中的安装选项或本地源码依赖，请使用独立环境。")
    return snapshots


def _result(*, success: bool, message: str, stdout: str = "", stderr: str = "", returncode: int | None = None) -> dict:
    return {"success": success, "error": None if success else message, "stdout": stdout,
            "stderr": stderr, "returncode": returncode}


def _run_stage(args: list[str], *, cwd: Path, env: dict[str, str], started: float,
               timeout: int, interrupt_event: threading.Event | None) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", **subprocess_group_kwargs())
    while True:
        if (interrupt_event is not None and interrupt_event.is_set()) or time.monotonic() - started >= timeout:
            terminate_process_tree(process)
            process.wait()
            raise TimeoutError("安装已取消或超时；请检查环境当前状态。")
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def install_shared(
    command: str, *, python: Path, root: Path, cwd: Path, env: dict[str, str],
    timeout: int, interrupt_event: threading.Event | None,
) -> dict:
    parsed = shared_install_args(command, python, cwd=cwd)
    if parsed is None:
        return _result(success=False, message="共用 Python 安装只支持单条明确的 uv pip install 或 python -m pip install。")
    args, manager = parsed
    try:
        _check_arguments(args, manager)
    except ValueError as exc:
        return _result(success=False, message=str(exc))
    started = time.monotonic()
    lock = BrowserFileLock(root / "state" / "skill-install.lock")
    try:
        while not lock.acquire(0):
            if interrupt_event is not None and interrupt_event.is_set():
                return _result(success=False, message="安装等待已取消。")
            if time.monotonic() - started >= min(timeout, 10):
                return _result(success=False, message="共用 Python 正在安装依赖，请稍后重试。")
            time.sleep(0.05)
    except OSError as exc:
        return _result(success=False, message=f"无法取得共用环境安装锁：{exc}")
    staging = None
    try:
        staging = Path(tempfile.mkdtemp(prefix="skill-install-", dir=root / "temp"))
        inputs = _input_files(args, cwd)
        list_args = ([args[0], "pip", "list", "--format=json", "--python", str(python)]
                     if manager == "uv" else [str(python), "-m", "pip", "list", "--format=json"])
        listed = _run_stage(list_args, cwd=cwd, env=env, started=started, timeout=timeout, interrupt_event=interrupt_event)
        if listed.returncode:
            return _result(success=False, message="无法读取共用环境现有依赖。", stderr=listed.stderr, returncode=listed.returncode)
        packages = json.loads(listed.stdout)
        constraints = staging / "constraints.txt"
        constraints.write_text("".join(f"{package['name']}=={package['version']}\n" for package in packages), encoding="utf-8")
        planned_args = [*args, "--constraint", str(constraints), "--dry-run"]
        if manager == "uv":
            planned_args.append("--no-config")
        else:
            report = staging / "plan.json"
            planned_args.extend(("--report", str(report)))
        planned = _run_stage(planned_args, cwd=cwd, env=env, started=started, timeout=timeout, interrupt_event=interrupt_event)
        if planned.returncode:
            return _result(success=False, message="依赖预演未通过；共用环境未修改。", stdout=planned.stdout, stderr=planned.stderr, returncode=planned.returncode)
        if manager == "uv":
            if re.search(r"\b(?:would\s+)?(?:uninstall|remove|replace|reinstall)\b", planned.stdout + planned.stderr, re.I):
                return _result(success=False, message="安装计划会改动现有依赖，请使用独立环境。")
        else:
            plan = json.loads(report.read_text(encoding="utf-8"))
            changes = plan.get("install") if isinstance(plan, dict) else None
            if not isinstance(changes, list):
                return _result(success=False, message="无法读取完整安装预演；共用环境未修改。")
            existing = {package["name"].lower().replace("_", "-") for package in packages}
            if any(change.get("metadata", {}).get("name", "").lower().replace("_", "-") in existing for change in changes):
                return _result(success=False, message="安装计划会重装现有依赖，请使用独立环境。")
        if any(not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != digest for path, digest in inputs.items()):
            return _result(success=False, message="依赖文件在预演后发生变化，请重新检查。")
        actual_args = [*args, "--constraint", str(constraints)]
        if manager == "uv":
            actual_args.append("--no-config")
        installed = _run_stage(actual_args, cwd=cwd, env=env, started=started, timeout=timeout, interrupt_event=interrupt_event)
        return _result(success=installed.returncode == 0, message="依赖安装失败。", stdout=installed.stdout, stderr=installed.stderr, returncode=installed.returncode)
    except (OSError, ValueError, KeyError, UnicodeError, TimeoutError) as exc:
        return _result(success=False, message=f"共用环境安装检查未完成：{exc}")
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        lock.release()
