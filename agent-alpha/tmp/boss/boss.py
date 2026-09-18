"""Direct CDP driver for BOSS直聘 work (bypasses agent-browser, so the
framework-level 'interrupted by ESC' cannot kill our commands).

Usage:
  python boss.py list                      # list page targets
  python boss.py newtab <url>              # open a new tab
  python boss.py nav <url> [target_substr] # navigate a page
  python boss.py js "<expr>" [substr]      # evaluate JS in a page
  python boss.py shot <path.png> [substr]  # screenshot
"""
import asyncio
import base64
import json
import sys
import time
import urllib.request

import websockets

PORT = 9222
BASE = f"http://127.0.0.1:{PORT}"


def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.load(r)


def _put(path):
    req = urllib.request.Request(BASE + path, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def targets():
    return _get("/json/list")


def _pages():
    return [t for t in targets() if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def pick_page(prefer=None):
    pages = _pages()
    if not pages:
        raise SystemExit("no page target")
    if prefer:
        for p in pages:
            if prefer in (p.get("url") or "") or prefer in (p.get("title") or ""):
                return p
    # prefer a zhipin page, else the newest
    for p in pages:
        if "zhipin.com" in (p.get("url") or ""):
            return p
    return pages[-1]


def _send_sync(ws_url, method, params, timeout=45):
    async def _run():
        async with websockets.connect(ws_url, max_size=100 * 1024 * 1024,
                                      ping_interval=None) as ws:
            await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if msg.get("id") == 1:
                    return msg
    return asyncio.run(_run())


def js(expr, prefer=None, timeout=45):
    p = pick_page(prefer)
    r = _send_sync(p["webSocketDebuggerUrl"], "Runtime.evaluate", {
        "expression": expr, "returnByValue": True,
        "awaitPromise": True, "userGesture": True,
    }, timeout)
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return {"__error__": res["exceptionDetails"].get("text"),
                "detail": str(res["exceptionDetails"])[:600]}
    return res.get("result", {}).get("value")


def nav(url, prefer=None, timeout=60):
    p = pick_page(prefer)
    _send_sync(p["webSocketDebuggerUrl"], "Page.navigate", {"url": url}, timeout)
    return url


def wait_ready(prefer=None, quiet=2.5, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        state = js("document.readyState", prefer)
        if state == "complete":
            break
        time.sleep(0.3)
    time.sleep(quiet)
    return js("document.readyState", prefer)


def new_tab(url="about:blank"):
    t = _put("/json/new?" + urllib.parse.quote(url, safe=":/?=&%"))
    return t


def shot(path, prefer=None):
    p = pick_page(prefer)
    r = _send_sync(p["webSocketDebuggerUrl"], "Page.captureScreenshot", {"format": "png"}, 60)
    data = r.get("result", {}).get("data")
    if not data:
        return {"error": str(r)[:400]}
    with open(path, "wb") as f:
        f.write(base64.b64decode(data))
    return path


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for t in _pages():
            print((t.get("title") or "")[:60], "|", (t.get("url") or "")[:130])
    elif cmd == "newtab":
        print(json.dumps(new_tab(sys.argv[2]), ensure_ascii=False)[:600])
    elif cmd == "nav":
        url = sys.argv[2]
        prefer = sys.argv[3] if len(sys.argv) > 3 else None
        nav(url, prefer)
        print(wait_ready(prefer))
    elif cmd == "js":
        prefer = sys.argv[3] if len(sys.argv) > 3 else None
        out = js(sys.argv[2], prefer)
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
    elif cmd == "shot":
        prefer = sys.argv[3] if len(sys.argv) > 3 else None
        print(shot(sys.argv[2], prefer))
    else:
        raise SystemExit(f"unknown cmd {cmd}")


if __name__ == "__main__":
    main()
