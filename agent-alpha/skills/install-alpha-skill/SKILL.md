---
name: install-alpha-skill
description: Install third-party skills into agent-alpha. Use when the user asks to install, inspect, configure, or enable a skill from a local folder, GitHub repository, GitHub subpath, README, or another agent's skill package, while adapting paths and dependency commands to agent-alpha's sandbox and runtime layout.
---

# Install Alpha Skill

Use this workflow when installing a skill for agent-alpha.

## Runtime Map

Install skill bodies preferably into:

```text
agent-alpha/home/.agents/skills/<skill-name>
```

When writing bash commands, remember that bash already runs with cwd set to `AGENT_ALPHA_ROOT`, the `agent-alpha` directory itself. In bash command arguments, use project-root-relative paths without the `agent-alpha/` prefix:

```text
home/.agents/skills/<skill-name>
temp/skill-install/<source-name>
skills/<skill-name>
```

Do not write bash commands like `agent-alpha/home/...`, `agent-alpha/temp/...`, or `agent-alpha/skills/...`; they create a wrong nested `agent-alpha/agent-alpha/...` path.

`load_skill` also reads the compatibility directory:

```text
agent-alpha/skills/<skill-name>
```

If the same skill name exists in both locations, `agent-alpha/skills/<skill-name>` wins.

Do not install skill bodies into Claude, Codex, OpenClaw, or user-level directories:

```text
~/.claude/skills
~/.codex/skills
~/.openclaw/skills
~/.agent-alpha/skills
C:\Users\<user>\...
```

agent-alpha redirects normal runtime directories into the project:

```text
AGENT_ALPHA_ROOT=agent-alpha
HOME=agent-alpha/home
USERPROFILE=agent-alpha/home
XDG_CONFIG_HOME=agent-alpha/config
XDG_CACHE_HOME=agent-alpha/cache
XDG_DATA_HOME=agent-alpha/data
XDG_STATE_HOME=agent-alpha/state
APPDATA=agent-alpha/config/appdata
LOCALAPPDATA=agent-alpha/data/localappdata
TMP=agent-alpha/temp
TEMP=agent-alpha/temp
PIP_CACHE_DIR=agent-alpha/cache/pip
UV_CACHE_DIR=agent-alpha/cache/uv
UV_TOOL_DIR=agent-alpha/tools/uv
PYTHONUSERBASE=agent-alpha/home/.local
PYTHONPYCACHEPREFIX=agent-alpha/cache/python
HF_HOME=agent-alpha/cache/huggingface
TRANSFORMERS_CACHE=agent-alpha/cache/huggingface/transformers
PLAYWRIGHT_BROWSERS_PATH=agent-alpha/cache/playwright
DOTNET_CLI_HOME=agent-alpha/home
CARGO_HOME=agent-alpha/cache/cargo
RUSTUP_HOME=agent-alpha/cache/rustup
```

`agent-alpha/.venv/Scripts` or `agent-alpha/.venv/bin` and `agent-alpha/bin` are at the front of PATH. Python CLI tools installed into the alpha venv should be called directly, for example `twitter user-posts @elonmusk -n 2`.

Persistent service variables are stored in:

```text
agent-alpha/config/runtime_env.local.json
```

Use this file for tokens, cookies, API keys, auth headers, proxies, and other service configuration. Do not use it to override path policy variables such as HOME, USERPROFILE, PATH, TEMP, APPDATA, AGENT_ALPHA_ROOT, or XDG_*.

Writable without special confirmation:

```text
current workspace
agent-alpha/home
agent-alpha/skills
agent-alpha/temp
agent-alpha/cache
agent-alpha/tools
agent-alpha/config
agent-alpha/data
agent-alpha/state
agent-alpha/bin
```

Read-only unless the user explicitly asks to change agent-alpha itself:

```text
agent-alpha/agent/core
agent loop files
sandbox and permission-system files
```

Do not create, edit, delete, move, or overwrite ordinary files outside agent-alpha and the current workspace. npm and Go global installs are the only host-global dependency exceptions.

## Installation Workflow

1. Identify the source:
   - local directory
   - GitHub repository URL
   - GitHub repository subpath
2. If the source is GitHub, clone or download it into `temp/skill-install/<source-name>` from bash. Conceptually, this is `agent-alpha/temp/skill-install/<source-name>`.
3. Read installation documents before copying:
   - `README.md`
   - `INSTALL.md`
   - local docs explicitly linked by the README in the same repository
4. Find `SKILL.md` candidates:
   - if root has `SKILL.md`, install root as one skill
   - if the repository has exactly one `SKILL.md`, install that skill
   - if the repository has multiple `SKILL.md` files, install them as multiple flat skills
5. Choose the skill name:
   - prefer `SKILL.md` frontmatter `name`
   - otherwise use the skill directory name
   - for packs, prefix with the pack name if needed to avoid conflicts, such as `superpowers-brainstorming`
6. Copy the skill body into `home/.agents/skills/<skill-name>` from bash. Conceptually, this is `agent-alpha/home/.agents/skills/<skill-name>`.
7. Translate third-party target paths to alpha paths. Example: if a README says `~/.claude/skills/agent-reach`, use `home/.agents/skills/agent-reach` in bash commands.

## Dependency Rules

Read README install commands, but adapt them to alpha's runtime.

Python dependencies and Python CLI tools must install into `agent-alpha/.venv`.

Prefer:

```text
.venv/Scripts/python.exe -m pip install <packages>
.venv/bin/python -m pip install <packages>
uv pip install --python .venv/Scripts/python.exe <packages>
uv pip install --python .venv/bin/python <packages>
```

Allowed only when it resolves to `agent-alpha/.venv`:

```text
pip install <packages>
python -m pip install <packages>
uv pip install <packages>
```

Avoid for Python CLI tools unless the user explicitly asks for an isolated tool environment:

```text
pipx install <packages>
uv tool install <packages>
```

Forbidden:

```text
pip install --user <packages>
system Python pip
conda pip
installing into user site-packages
installing into another project's virtualenv
```

If a README asks to install a Python CLI with `pipx install ...` or `uv tool install ...`, translate it to an alpha venv install first. For example, use `.venv/Scripts/python.exe -m pip install ...` on Windows or `.venv/bin/python -m pip install ...` on Linux/macOS.

npm and Go global installs keep host-global meaning:

```text
npm install -g ...
pnpm add -g ...
yarn global add ...
go install ...
```

Do not force npm global tools into `agent-alpha/tools`. Do not set `NPM_CONFIG_PREFIX`, `GOPATH`, `GOBIN`, `GOMODCACHE`, or `GOCACHE` for this purpose.

If the README asks to edit shell profiles, system environment variables, or files under `C:\Users\<user>`, do not edit those directly. Use alpha's local runtime env profile or current alpha configuration mechanism if available. If none exists, report the required env vars as follow-up work.

Do not blindly run `install.ps1`, `install.sh`, `setup.sh`, or similar installer scripts. Read them first when possible. If they only invoke allowed dependency commands, run or reproduce those commands. If they write ordinary files outside agent-alpha or the current workspace, do not run them as-is.

## Verification

1. Use `load_skill <skill-name>`.
2. Confirm the loaded skill content matches the installed skill.
3. If the README provides a smoke test, run it without asking the user.
4. If the smoke test requires credentials, accounts, paid services, or external side effects, run only the local non-destructive parts and report what remains.

After installation, report:

```text
source
installed skill name(s)
target path(s)
dependency commands run
load_skill result
smoke test result, if any
anything skipped because it would violate alpha's path rules
```
