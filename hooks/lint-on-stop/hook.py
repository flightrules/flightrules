#!/usr/bin/env python3
"""lint-on-stop: run the project's linter before Claude is allowed to stop.

Stop hook. Resolves a lint command (FR_LINT_CMD if set; else "npm run -s
lint" when package.json has a scripts.lint entry; else "ruff check ." when
ruff config exists and the ruff binary is on PATH), runs it in the session
cwd, and blocks the stop with the lint output when it fails - so sessions
do not end with a red linter. No lint command found means silent allow.

Loop guard: a per-session counter in FR_STATE_DIR (default: system temp
dir). After 2 blocked stops in one session the hook allows the stop with a
visible warning instead of blocking again - a lint failure Claude cannot
fix must never trap the session in a block loop. A passing run resets the
counter.

Config (env vars):
  FR_LINT_OFF=1        disable entirely
  FR_LINT_CMD=...      lint command (run via shell), overrides autodetect
  FR_LINT_TIMEOUT=120  seconds before the lint run is abandoned (allow)
  FR_STATE_DIR=...     directory for the loop-guard counter

Fail-open contract: malformed stdin exits 0 silently; a lint timeout or
unwritable state dir allows the stop with a warning; internal errors exit
1 (non-blocking) with a one-line stderr note. The session is never
wrecked.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

MAX_BLOCKS = 2
TAIL_CHARS = 2000


def state_path(session_id):
    state_dir = os.environ.get("FR_STATE_DIR") or tempfile.gettempdir()
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "") or "unknown"
    return os.path.join(state_dir, f"fr-lint-on-stop-{safe}.count")


def read_blocks(path):
    try:
        with open(path) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def detect_command(cwd):
    cmd = os.environ.get("FR_LINT_CMD", "").strip()
    if cmd:
        return cmd
    pkg = os.path.join(cwd, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg) as f:
                scripts = (json.load(f) or {}).get("scripts") or {}
            if "lint" in scripts:
                return "npm run -s lint"
        except (OSError, ValueError, AttributeError):
            pass  # unreadable package.json: keep detecting, do not crash
    ruff_configured = os.path.isfile(os.path.join(cwd, "ruff.toml"))
    if not ruff_configured:
        pyproject = os.path.join(cwd, "pyproject.toml")
        try:
            if os.path.isfile(pyproject):
                with open(pyproject) as f:
                    ruff_configured = "[tool.ruff" in f.read()
        except OSError:
            pass
    if ruff_configured and shutil.which("ruff"):
        return "ruff check ."
    return None


def allow_with_warning(message):
    print(json.dumps({"systemMessage": message}))
    return 0


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed stdin: fail open, stay silent
    if not isinstance(data, dict):
        return 0
    if os.environ.get("FR_LINT_OFF") == "1":
        return 0
    cwd = data.get("cwd") or os.getcwd()
    if not os.path.isdir(cwd):
        return 0
    command = detect_command(cwd)
    if not command:
        return 0
    try:
        timeout = float(os.environ.get("FR_LINT_TIMEOUT", "") or 120)
    except ValueError:
        timeout = 120.0
    if timeout <= 0:
        timeout = 120.0
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return allow_with_warning(
            f"lint-on-stop: '{command}' did not finish within {int(timeout)}s; "
            "allowing stop. Run it manually or raise FR_LINT_TIMEOUT."
        )
    spath = state_path(data.get("session_id"))
    if proc.returncode == 0:
        try:
            os.remove(spath)  # passing lint resets the loop guard
        except OSError:
            pass
        return 0
    blocks = read_blocks(spath)
    if blocks >= MAX_BLOCKS:
        return allow_with_warning(
            f"lint-on-stop: lint still failing after {MAX_BLOCKS} blocked "
            f"stops this session; allowing stop so the session does not "
            f"loop. Run '{command}' manually."
        )
    try:
        with open(spath, "w") as f:
            f.write(str(blocks + 1))
    except OSError:
        return allow_with_warning(
            f"lint-on-stop: cannot write loop-guard state in "
            f"'{os.path.dirname(spath)}'; allowing stop instead of risking "
            f"an endless block loop. Lint is failing - run '{command}' "
            "manually."
        )
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = output[-TAIL_CHARS:]
    print(json.dumps({
        "decision": "block",
        "reason": f"lint failed:\n{tail}\nFix these before finishing.",
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail open: never wreck the session
        print(f"lint-on-stop internal error: {e}", file=sys.stderr)
        sys.exit(1)
