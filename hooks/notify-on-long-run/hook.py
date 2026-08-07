#!/usr/bin/env python3
"""notify-on-long-run: surface Claude Code notifications on your desktop.

Notification event, any matcher. Claude Code emits Notification events when
it needs you (permission prompt, waiting for input after a long run). In a
buried terminal those are easy to miss; this hook turns them into a desktop
notification so you can walk away from long runs.

Dispatch order (first hit wins):
1. FR_NOTIFY_CMD - user template with {title} and {message} placeholders,
   substituted pre-quoted (shlex) and run via the shell
2. notify-send, if on PATH (Linux desktops)
3. osascript display notification (macOS)
4. nothing available: exit 0 silently

Title is "Claude Code"; message comes from the stdin "message" field,
falling back to "Claude Code needs your attention".

Config (env vars):
  FR_NOTIFY_OFF=1     disable entirely
  FR_NOTIFY_CMD=...   custom command template, e.g.
                      'ntfy publish claude {message}'

Fail-open contract: this hook never blocks and never errors loudly.
Malformed stdin exits 0 silently; a failing or hanging notify command gets a
one-line stderr note (debug log only) and still exits 0; internal errors
exit 1 (non-blocking). The session is never wrecked.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys

TITLE = "Claude Code"
FALLBACK_MESSAGE = "Claude Code needs your attention"
COMMAND_TIMEOUT = 5  # seconds; a hung notifier must not eat the hook budget


def applescript_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_command(message):
    """Return the shell command to run, or None if no notifier is available.

    Placeholder values are shell-quoted before insertion, so message content
    is always literal text to the shell, never syntax. {title} is replaced
    before {message} so a message containing '{title}' stays literal.
    """
    template = os.environ.get("FR_NOTIFY_CMD", "").strip()
    if template:
        return (template.replace("{title}", shlex.quote(TITLE))
                        .replace("{message}", shlex.quote(message)))
    if shutil.which("notify-send"):
        return f"notify-send {shlex.quote(TITLE)} {shlex.quote(message)}"
    if sys.platform == "darwin" and shutil.which("osascript"):
        script = (f'display notification "{applescript_escape(message)}" '
                  f'with title "{applescript_escape(TITLE)}"')
        return f"osascript -e {shlex.quote(script)}"
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed stdin: fail open, stay silent
    if os.environ.get("FR_NOTIFY_OFF") == "1":
        return 0
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        message = FALLBACK_MESSAGE
    command = build_command(message)
    if command is None:
        return 0  # no notifier on this box: silence, not noise
    try:
        proc = subprocess.run(
            command, shell=True, timeout=COMMAND_TIMEOUT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            print(f"notify-on-long-run: notify command exited "
                  f"{proc.returncode}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"notify-on-long-run: notify command timed out after "
              f"{COMMAND_TIMEOUT}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail open: never wreck the session
        print(f"notify-on-long-run internal error: {e}", file=sys.stderr)
        sys.exit(1)
