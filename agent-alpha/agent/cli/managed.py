"""Terminal entry channel for the same supervisor used by the desktop/Web UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

from agent.core.session_paths import get_default_workspace_root
from agent.server.agent_manager import AgentManager


class ManagedCLI:
    def __init__(self, manager, workspace):
        self.manager = manager
        self.session_id = manager.create_session(project_id="cli", workspace=workspace).session_id
        self.permission_mode = "ask"
        self.closed = threading.Event()
        self._shown_runs = set()
        self._shown_permissions = set()

    def report_updates(self):
        with self.manager._lock:
            runs = [dict(run) for run in self.manager._runs.values()]
        for run in runs:
            record = self.manager.store.load(run["session_id"])
            if record is None or self.manager.collaboration.root(record) != self.session_id:
                continue
            permission = self.manager.get_run(run["request_id"]).get("pending_permission")
            if permission and permission["permission_id"] not in self._shown_permissions:
                self._shown_permissions.add(permission["permission_id"])
                print(f"\n权限请求 {permission['permission_id']}（{record.metadata.get('title', record.session_id)}）：\n"
                      f"{permission['summary']}\n/allow <ID> 允许一次；/deny <ID> 拒绝；/retry <ID> 补充说明", flush=True)
            if (run["session_id"] == self.session_id and run["status"] not in {"running", "stopping"}
                    and run["request_id"] not in self._shown_runs):
                self._shown_runs.add(run["request_id"])
                print(f"\nAgent [{run['status']}]: {run.get('response') or run.get('error') or '本轮已结束'}\n", flush=True)

    def monitor(self):
        while not self.closed.wait(0.2):
            self.report_updates()

    def command(self, text):
        from agent.cli.main import _parse_workspace_arg, _restore_session_interactive

        text = text.strip()
        if not text:
            return True
        if text.lower() in {"quit", "exit", "q"}:
            return False
        if text == "/stop":
            self.manager.interrupt(self.session_id)
            return True
        if text.startswith(("/allow ", "/deny ", "/retry ")):
            command, permission_id, *remainder = text.split(maxsplit=2)
            decision = {"/allow": "allow_once", "/deny": "deny", "/retry": "retry_with_context"}[command]
            instruction = remainder[0] if remainder else None
            if decision == "retry_with_context" and not instruction:
                raise ValueError("请填写补充说明")
            self.manager.resolve_permission(permission_id, decision, instruction)
            return True
        if text == "/admin":
            mode = input("权限模式 ask / auto：").strip()
            if mode not in {"ask", "auto"}:
                raise ValueError("权限模式必须为 ask 或 auto")
            self.permission_mode = mode
            return True
        if text == "/resume":
            record = _restore_session_interactive(self.manager.store)
            if record is not None:
                self.session_id = record.session_id
                print(f"已恢复会话 {self.session_id}；未自动启动旧任务。")
            return True
        if text.startswith("/workspace"):
            if text.startswith("/workspace set "):
                workspace = _parse_workspace_arg(text[len("/workspace set "):])
                if not workspace.is_dir():
                    raise ValueError("工作目录不存在")
                with self.manager._lock:
                    if self.manager._has_active_run(self.session_id):
                        raise RuntimeError("请先停止当前执行，再切换工作目录")
                    self.manager.store.update_workspace(self.session_id, str(workspace))
            print(self.manager.store.load(self.session_id).workspace)
            return True
        if text == "reset":
            with self.manager._lock:
                if self.manager._has_active_run(self.session_id):
                    raise RuntimeError("请先停止当前执行，再清空历史")
                record = self.manager.store.load(self.session_id)
                record.history, record.runtime_history, record.runtime_checkpoint = [], [], {}
                for item in record.metadata.get("mailbox", []):
                    if item["state"] in {"pending", "reserved"}:
                        item["state"] = "interrupted"
                self.manager.store.save(record)
                self.manager.release(self.session_id)
            return True
        if text == "/compact":
            self.manager.start_compact(session_id=self.session_id, permission_mode=self.permission_mode)
            return True
        if text in {"context", "save", "save-log"}:
            record = self.manager.store.load(self.session_id)
            context = {**record.metadata.get("runtime_context", {}),
                       "session_id": record.session_id, "workspace": record.workspace,
                       "history": record.runtime_history or record.history, "events": record.events}
            payload = json.dumps(context, ensure_ascii=False, indent=2)
            if text == "context":
                print(payload)
            else:
                path = (Path(record.workspace) / "agent_context.json" if text == "save"
                        else self.manager.logs_dir / f"{self.session_id}-snapshot.json")
                path.write_text(payload, encoding="utf-8")
                print(f"已保存：{path}")
            return True
        mode = "steer" if text.startswith("/steer ") else "queue"
        message = text[len("/steer "):] if mode == "steer" else text
        self.manager.submit_chat(session_id=self.session_id, message=message, mode=mode,
                                 permission_mode=self.permission_mode, runtime_metadata={"entrypoint": "cli"})
        return True

    def read_command(self):
        if os.name != "nt" or not sys.stdin.isatty():
            return input("You: ")
        import msvcrt
        print("You: ", end="", flush=True)
        buffer = []
        last_escape = 0
        while True:
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue
            char = msvcrt.getwch()
            if char in {"\x00", "\xe0"}:
                msvcrt.getwch()
            elif char == "\x03":
                raise KeyboardInterrupt
            elif char == "\x1b":
                now = time.monotonic()
                if now - last_escape < 1:
                    self.manager.interrupt(self.session_id)
                    print("\n正在停止主 agent；子任务不受影响。", flush=True)
                last_escape = now
            elif char in {"\r", "\n"}:
                print()
                return "".join(buffer)
            elif char == "\b":
                if buffer:
                    buffer.pop()
                    print("\b \b", end="", flush=True)
            else:
                buffer.append(char)
                print(char, end="", flush=True)


def run_managed_cli():
    from agent.cli.main import PROJECT_ROOT
    workspace = get_default_workspace_root(PROJECT_ROOT)
    workspace.mkdir(parents=True, exist_ok=True)
    manager = AgentManager()
    cli = ManagedCLI(manager, workspace)
    monitor = threading.Thread(target=cli.monitor, daemon=True)
    monitor.start()
    print("普通消息排队；/steer 内容：直接引导；/stop 或连按两次 ESC：停止主 agent。\n"
          "/resume /workspace /workspace set <path> /compact /admin reset context save save-log\n"
          "quit / exit：退出并停止全部受管理执行。")
    try:
        while True:
            try:
                if not cli.command(cli.read_command()):
                    break
            except KeyboardInterrupt:
                manager.interrupt(cli.session_id)
                print("\n正在停止主 agent；输入 quit 退出应用。")
            except EOFError:
                break
            except Exception as exc:
                print(f"\nError: {exc}")
    finally:
        cli.closed.set()
        manager.release_all()
        manager._executor.shutdown()
        monitor.join(timeout=1)
