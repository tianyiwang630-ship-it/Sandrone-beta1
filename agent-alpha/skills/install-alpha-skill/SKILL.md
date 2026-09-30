---
name: install-alpha-skill
description: Install third-party skills into agent-alpha from local folders, repositories, or installation instructions, adapting paths and dependencies to the current Alpha runtime.
---

# Install Alpha Skill

Read the **Runtime environment guide** at the absolute path in the system prompt before choosing installation paths or commands. It gives this instance's program resources, writable data root, third-party skill directory, shared Python, CLI directory, bin, state and temp paths. Bash defaults to the current workspace; set `working_dir` or use explicit absolute paths when installing. Do not assume this is a Codex, Claude Code, or fixed `agent-alpha/.venv` layout.

Read the source README and installer scripts before using their commands. Stage downloads under the guide's temp directory, then install the entire skill folder in its third-party skill directory. Preserve attached files and directory structure. Built-in skills have priority over third-party skills of the same name.

You may edit a third-party skill's Markdown only where paths or invocation commands must change for Alpha. Preserve its behavior, requirements, name, description and other content. This does not authorize edits to attached scripts or Alpha application code. Installing a skill never modifies the backend tool registry; a skill that requires a new backend tool needs separate application work.

For Python dependencies, reuse installed packages when possible. Check the shared Python's current packages and the proposed install. Add compatible requirements to that environment without replacing or removing its existing packages. If they conflict, use an existing suitable isolated tool, or create a skill environment under the guide's `tools/venvs/<skill-name>` and call its Python explicitly; do not create one for every skill. Never use bare pip, host Python, Conda, or another project's environment. Follow actual terminal and sandbox errors instead of changing the application's rules during installation. Preserve the existing Browser Harness installation and do not add packages to an existing uv tool environment. npm and other dependencies follow the guide's actual paths.

If you create an isolated Python environment, tell the user why, its actual path, and how its Python will be called. Tell them even if later dependency installation fails, accurately stating what completed. Do not require manual activation.

Confirm that files were copied and required dependency commands completed. Report the installed skill's name and path, its dependency environment, and any incomplete step. Then say:

> 新建对话，发送：请检查「技能名称」是否安装成功。

Do not require a real browser, account, external service smoke test, or immediate skill reload in the current conversation.
