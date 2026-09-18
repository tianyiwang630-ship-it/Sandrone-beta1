---
name: browser-harness
description: Control Alpha's isolated real browser through CDP for clicking, typing, navigation, logged-in sessions, JavaScript-rendered pages, downloads, and uploads. Use fetch instead for plain public HTTP content.
---

# Browser Harness

Use `browser_harness_exec` for interactive browser work. Browser Harness helpers are pre-imported. Pass Python directly in the tool's `code` field; never invoke `browser-harness` through Bash, Git Bash, a heredoc, or a temporary script.

**Manual-login hard stop:** if the tool returns `status="user_action_required"`, tell the user “请在 Alpha 浏览器完成登录后回复‘继续’。” and end the turn immediately. Do not retry, increase the timeout, use Bash to launch Chrome, or resume until the user replies “继续”; then call once with `mode="cdp"`.

Alpha starts a separate visible Chrome with its own persistent profile. `mode="manual"` opens it without automation for human sign-in; `mode="cdp"` restarts that same profile with a private CDP endpoint and runs browser code. Never discover, attach to, navigate, copy, or close the user's daily Chrome or Edge profile.

## Before acting

- Use `fetch` for a public page or API that does not require interaction, login, JavaScript rendering, or bot-sensitive browser behavior.
- For a browser task, begin by checking `current_tab()` and `list_tabs()`.
- The first navigation for a new task/site uses `new_tab(url)`, not `goto_url(url)`.
- Record the `targetId` returned for every tab you create. Reuse that tab with `switch_tab(target_id)` on later calls.
- Close only a tab whose `targetId` you created and recorded. Never close tabs by domain or close an unknown tab.

Example tool code:

```python
tabs = list_tabs()
print(tabs)
target = new_tab("https://example.com")
print(target)
wait_for_load()
print(page_info())
```

## Page workflow

1. Inspect the current state with `page_info()` and targeted DOM queries.
2. Prefer the accessibility tree for controls:

```python
nodes = cdp("Accessibility.getFullAXTree")["nodes"]
for node in nodes:
    role = (node.get("role") or {}).get("value")
    name = (node.get("name") or {}).get("value")
    if role in {"button", "link", "textbox"} and name:
        print(role, name, node.get("backendDOMNodeId"))
```

3. Get the box center from `DOM.getBoxModel`, click with `click_at_xy(x, y)`, and verify the result.
4. Use `js(...)` for focused DOM inspection or extraction when the accessibility tree is insufficient.
5. Call `wait_for_load()` after navigation. If the attached tab is stale or internal, use `ensure_real_tab()`.
6. Use `cdp("Domain.method", ...)` only when a normal helper does not cover the operation.

Do not print an unfiltered full accessibility tree or very large HTML document. Filter in Python so the tool result stays useful.

## Tabs and visibility

Browser Harness keeps one mutable current tab for all Web agents, so always re-check `current_tab()` and `list_tabs()` at the start of each tool call. Other agents may have used the shared browser between calls.

`new_tab()` and `switch_tab()` normally attach in the background. Use `activate_tab(target)` only when the user explicitly asks to see the tab or the page demonstrably stops working while hidden. If a background `scroll(...)` times out, activate the current tab once, retry once, then verify the scroll position.

## Login and human takeover

- Existing SSO may be used automatically only when the account choice is unambiguous.
- Stop for passwords, MFA, CAPTCHA, consent, payment, account choice, an unsafe-browser warning, or the same sign-in state twice. Do not retry or ask for secrets.
- If the user asks to take over, or login, MFA, CAPTCHA, an unsafe-browser warning, or the same sign-in state appears twice, call `browser_harness_exec` with `mode="manual"` and no `code`. Say: “请在 Alpha 浏览器完成登录后回复‘继续’。” End the turn.
- After “继续”, call the tool with `mode="cdp"` and code that re-checks the page. The Alpha profile keeps the login state while its window restarts.
- Never copy a daily-browser profile or ask for a password in chat.

## Downloads, uploads, dialogs, and frames

- Inspect download behavior and verify the resulting file under `$BH_TMP_DIR` or the task workspace.
- Upload only a file the user placed in scope. Use the page's file input/helper and verify the displayed filename before submitting.
- Handle JavaScript dialogs explicitly through CDP and verify whether the action was accepted or dismissed.
- Coordinate input works through same-origin, cross-origin iframe, and shadow-DOM compositor surfaces. Use DOM/frame inspection only to locate the correct coordinates.
- Screenshots can help with layout, canvas, or imagery, but the current text model cannot independently solve visual CAPTCHA challenges.

## Shared helpers

Task-specific reusable helpers belong in `$BH_AGENT_WORKSPACE/agent_helpers.py`. This file is shared across all Alpha Web agents. Keep helpers short, generic, and compatible with Browser Harness 0.1.13. If a helper has a syntax/runtime error, fix it from the traceback; do not silently replace it with the retired browser system.

Domain skills are disabled (`BH_DOMAIN_SKILLS=0`). Recordings, telemetry, update checks, and Browser Use Cloud auto-start are also disabled by Alpha.

## Failure handling

- A busy result means another Web agent owns the browser channel; retry after it finishes.
- A recoverable `user_action_required` result means the shared Alpha browser is waiting for manual login. Give the short instruction from the login section and wait for the user; do not retry in the same turn.
- On interruption or timeout, do not assume the browser or tab closed. Re-check state on the next call.
- If the user closes the Alpha browser or a tab, call again and inspect `current_tab()` / `list_tabs()`; recreate only the task tab you need.
- When the tool reports a missing or wrong CLI version, ask the user to run `setup-agent-alpha.ps1`. Do not install or update Browser Harness during a task.
- Never call cloud helpers such as `start_remote_daemon`, and never set `BU_NAME`, `BU_CDP_URL`, or other connection variables from tool code.
