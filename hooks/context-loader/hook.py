#!/usr/bin/env python3
"""context-loader: orient the agent at session start with cheap git context.

SessionStart. Emits additionalContext (structured JSON) containing:
- current branch, parsed straight from {cwd}/.git/HEAD (no git needed)
- last 5 commits via `git log --oneline -5` (omitted if git absent/fails)
- count of dirty files via `git status --porcelain` (omitted likewise)

This saves the ritual first round-trips of every session (git status,
git log) and means the agent never starts blind on branch state. If the
session cwd has no .git, the hook says nothing at all.

Speed is a feature: HEAD is a single small file read; each git call gets
a 2s timeout inside a 5s total budget; no network is ever touched. A
slow repo degrades to fewer lines, never to a stalled session start.

Config (env vars):
  FR_CONTEXT_OFF=1          disable entirely

Fail-open contract: malformed stdin exits 0 silently; internal errors
exit 1 (non-blocking) with a one-line stderr note. The session is never
wrecked.
"""
import json
import os
import re
import subprocess
import sys
import time

TOTAL_BUDGET = 5.0  # hard wall-clock budget for the whole hook (seconds)
GIT_TIMEOUT = 2.0  # per git subprocess (seconds)
MAX_LOG_LINES = 5
MAX_LINE_CHARS = 200


def branch_from_head(git_entry):
    """Resolve the branch by reading HEAD directly; None if unreadable.

    git_entry is {cwd}/.git: either a directory, or a pointer file
    ("gitdir: <path>") as used by linked worktrees and submodules.
    """
    try:
        git_dir = git_entry
        if os.path.isfile(git_entry):
            with open(git_entry, encoding="utf-8", errors="replace") as f:
                first = f.readline(4096).strip()
            if not first.startswith("gitdir:"):
                return None
            target = first[len("gitdir:"):].strip()
            if not os.path.isabs(target):
                target = os.path.join(os.path.dirname(git_entry), target)
            git_dir = os.path.normpath(target)
        with open(os.path.join(git_dir, "HEAD"), encoding="utf-8",
                  errors="replace") as f:
            line = f.readline(4096).strip()
    except OSError:
        return None
    if line.startswith("ref: "):
        ref = line[len("ref: "):].strip()
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/"):]
        return ref  # unusual but honest: show the full ref
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", line):
        return f"detached HEAD at {line[:12]}"
    return None


def run_git(args, cwd, deadline):
    """Run one git command under the budget; None on any failure."""
    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        return None
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")  # never hang on a prompt
    env["GIT_OPTIONAL_LOCKS"] = "0"  # status must not take index locks
    # Only report on {cwd}/.git itself: stop git from discovering some
    # unrelated parent repo when cwd's .git turns out to be broken.
    parent = os.path.dirname(os.path.abspath(cwd))
    ceiling = env.get("GIT_CEILING_DIRECTORIES")
    env["GIT_CEILING_DIRECTORIES"] = f"{ceiling}:{parent}" if ceiling else parent
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "--no-pager", *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=min(GIT_TIMEOUT, remaining),
        )
    except (OSError, subprocess.SubprocessError):
        return None  # git absent, timed out, or otherwise unusable
    if proc.returncode != 0:
        return None
    return proc.stdout


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed stdin: fail open, stay silent
    if not isinstance(data, dict):
        return 0
    if os.environ.get("FR_CONTEXT_OFF") == "1":
        return 0
    cwd = data.get("cwd") or os.getcwd()
    git_entry = os.path.join(cwd, ".git")
    if not os.path.exists(git_entry):
        return 0  # not a repo: nothing to say
    deadline = time.monotonic() + TOTAL_BUDGET

    parts = []
    branch = branch_from_head(git_entry)
    if branch:
        parts.append(f"- branch: {branch}")
    log = run_git(["log", "--oneline", "--no-color", f"-{MAX_LOG_LINES}"],
                  cwd, deadline)
    if log:
        commits = [l[:MAX_LINE_CHARS] for l in log.splitlines() if l.strip()]
        if commits:
            parts.append("- recent commits (newest first):")
            parts.extend(f"    {c}" for c in commits[:MAX_LOG_LINES])
    status = run_git(["status", "--porcelain"], cwd, deadline)
    if status is not None:
        dirty = sum(1 for l in status.splitlines() if l.strip())
        parts.append(f"- dirty files: {dirty}")
    if not parts:
        return 0

    context = "Git repo state at session start:\n" + "\n".join(parts)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail open: never wreck the session
        print(f"context-loader internal error: {e}", file=sys.stderr)
        sys.exit(1)
