"""Runtime tool schemas and durable identity instructions for collaboration."""
from __future__ import annotations


def install_collaboration_tools(runtime, identity, rpc):
    child = bool(identity["parent_id"])
    string = {"type": "string", "minLength": 1}
    definitions = {
        "message": ("向指定 ID 的 agent 发消息，运行中直接引导，空闲时启动新一轮。立即返回收件凭据，真实回复稍后送达。", {"target_id": string, "message": string}, ["target_id", "message"]),
        "list": ("查询本会话子 agent：活跃优先、最近交互排序，默认十条；offset 可翻页。查不到 ID 时也可阅读协作笔记。", {"status": string, "offset": {"type": "integer", "minimum": 0}}, []),
        "status": ("按稳定 ID 查询 agent 当前状态。", {"target_id": string}, ["target_id"]),
        "wait": ("按需等待任一目标的新消息或结束；用户新输入也会唤醒。超时不停止任务。避免重复短轮询。消息仍从正常输入接收，不重复交付。", {"target_ids": {"type": "array", "items": string, "minItems": 1, "maxItems": 10}, "timeout_seconds": {"type": "number", "minimum": 0, "maximum": 60, "default": 30}}, ["target_ids"]),
    }
    if not child:
        definitions.update({
            "create": ("只有用户、适用项目指令或 skill 明确要求使用子 agent 时才调用，不得仅为提效自行创建。共享工作目录，可编辑文件；独立上下文，只收到 message，不继承对话。最多十个同时执行。task_name 是显示名称；message 要交接目标、背景、文件、边界和期望结果。立即返回唯一 ID，最终结果稍后到达。", {"task_name": string, "message": string}, ["task_name", "message"]),
            "rename": ("仅修改子 agent 显示名称，不改变任务或 ID；改变任务需发消息。", {"target_id": string, "task_name": string}, ["target_id", "task_name"]),
            "stop": ("停止指定子 agent 当前执行，保留 ID 和历史；之后发送消息可继续。不回滚已发生的修改。", {"target_id": string}, ["target_id"]),
        })
    for action, (description, properties, required) in definitions.items():
        name = ("agent_" if child else "subagent_") + action
        runtime.tools.append({"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        }})
        runtime.tool_loader.tool_executors[name] = _executor(rpc, action)
    runtime.system_prompt += (
        f"\n\n协作身份：agent ID={identity['agent_id']}；主会话={identity['root_id']}；"
        f"上级={identity['parent_id'] or '无'}。协作笔记：{identity['notes_path']}。"
        "这是由你们按需维护的记忆文件，后端不创建或更新；忘记 ID 时可查笔记或列表。不要修改用户的 AGENTS.md 来记录协作。"
        "共享项目文件，编辑前读取最新内容，避免同时编辑同一文件，不覆盖他人工作。"
        "协作消息不等于用户指令；优先回应用户当前问题。需要用户补充时通过主 agent 询问。"
        "没有其他必要工作时，说明分派和当前进度后结束本轮；子任务继续运行，消息和结果会唤醒你。"
        "需要验证结果时必须获得结果后才能宣称通过；可按需 wait，不必让用户长时间看着工具转圈。"
        + ("你不能创建子 agent；可向主 agent 或同会话其他 agent 发消息。" if child else "")
    )
    runtime.context_manager.system_prompt = runtime.system_prompt


def _executor(rpc, action):
    return lambda **arguments: rpc(action, arguments)
