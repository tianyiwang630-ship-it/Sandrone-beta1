from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALPHA = ROOT / "agent-alpha"
TWITTER = ALPHA / ".venv" / "Scripts" / "twitter.exe"


def run_case(name: str, args: list[str], env: dict[str, str] | None = None, timeout: int = 40) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=str(ALPHA),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "name": name,
            "returncode": proc.returncode,
            "seconds": round(time.monotonic() - started, 2),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "timeout": timeout,
            "seconds": round(time.monotonic() - started, 2),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }


def masked_env(env: dict[str, str]) -> dict[str, str]:
    keys = [
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "PATH",
        "TWITTER_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "TWITTER_AUTH_TOKEN",
        "TWITTER_CT0",
        "TWITTER_BROWSER",
    ]
    result = {}
    for key in keys:
        value = env.get(key)
        if value is None:
            result[key] = None
        elif key in {"TWITTER_AUTH_TOKEN", "TWITTER_CT0"}:
            result[key] = f"SET len={len(value)}"
        elif key == "PATH":
            result[key] = value.split(os.pathsep)[:8]
        else:
            result[key] = value
    return result


def force_utf8(env: dict[str, str]) -> dict[str, str]:
    result = dict(env)
    result["PYTHONUTF8"] = "1"
    result["PYTHONIOENCODING"] = "utf-8"
    return result


def build_alpha_env() -> dict[str, str]:
    sys.path.insert(0, str(ALPHA))
    from agent.core.runtime_paths import build_runtime_env

    return build_runtime_env(ALPHA, base_env=os.environ)


def main() -> int:
    alpha_env = force_utf8(build_alpha_env())
    host_env = force_utf8(dict(os.environ))
    host_with_alpha_twitter_env = dict(host_env)
    for key in ["TWITTER_AUTH_TOKEN", "TWITTER_CT0", "TWITTER_PROXY", "TWITTER_BROWSER"]:
        if alpha_env.get(key):
            host_with_alpha_twitter_env[key] = alpha_env[key]

    report = {
        "twitter_exists": TWITTER.exists(),
        "twitter_path": str(TWITTER),
        "host_env": masked_env(host_env),
        "host_with_alpha_twitter_env": masked_env(host_with_alpha_twitter_env),
        "alpha_env": masked_env(alpha_env),
        "cases": [],
    }

    if not TWITTER.exists():
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["cases"].append(run_case("host_help", [str(TWITTER), "--help"], env=host_env, timeout=15))
    report["cases"].append(run_case("alpha_help", [str(TWITTER), "--help"], env=alpha_env, timeout=15))
    report["cases"].append(run_case("host_status", [str(TWITTER), "status"], env=host_env, timeout=40))
    report["cases"].append(
        run_case(
            "host_with_alpha_twitter_status",
            [str(TWITTER), "status"],
            env=host_with_alpha_twitter_env,
            timeout=40,
        )
    )
    report["cases"].append(run_case("alpha_status", [str(TWITTER), "status"], env=alpha_env, timeout=40))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
