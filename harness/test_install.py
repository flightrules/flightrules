#!/usr/bin/env python3
"""Deterministic tests for install.py: install, merge, idempotency, uninstall.

Runs the real installer against throwaway project dirs. No LLM, no network.

Usage: python3 harness/test_install.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
INSTALL = PACK / "install.py"
FAILURES = []


def run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(INSTALL), *args],
        capture_output=True, text=True, cwd=cwd, timeout=60,
    )


def check(name, condition, detail=""):
    if condition:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}  {detail}")
        FAILURES.append(name)


def our_commands(settings):
    out = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for h in group.get("hooks", []):
                if "/flightrules/" in h.get("command", ""):
                    out.append(h["command"])
    return out


def main():
    hooks = sorted(
        d.name for d in (PACK / "hooks").iterdir()
        if (d / "hook.py").is_file() and (d / "hook.json").is_file()
    )

    listing = run(["--list"])
    check("list exits 0 and names every hook",
          listing.returncode == 0
          and all(h in listing.stdout for h in hooks),
          listing.stdout[:200])

    with tempfile.TemporaryDirectory(prefix="fr-install-") as tmp:
        project = Path(tmp)
        settings_path = project / ".claude" / "settings.json"

        # Pre-existing user config must survive everything below.
        settings_path.parent.mkdir(parents=True)
        user_settings = {
            "permissions": {"deny": ["Read(./secrets/**)"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "echo user-hook"}]}]},
        }
        settings_path.write_text(json.dumps(user_settings))

        proc = run(["--project", str(project)])
        settings = json.loads(settings_path.read_text())
        installed = list((project / ".claude" / "hooks" / "flightrules").glob("*.py"))
        check("install all: exits 0", proc.returncode == 0, proc.stderr[:200])
        check("install all: one .py per hook", len(installed) == len(hooks))
        check("install all: installed hooks are executable",
              all(os.access(f, os.X_OK) for f in installed))
        check("install all: one settings entry per hook",
              len(our_commands(settings)) == len(hooks))
        check("install all: user permissions preserved",
              settings.get("permissions") == user_settings["permissions"])
        check("install all: user hook entry preserved",
              any(h.get("command") == "echo user-hook"
                  for g in settings["hooks"]["PreToolUse"]
                  for h in g.get("hooks", [])))
        check("install all: backup written",
              (settings_path.with_name("settings.json.bak")).exists())

        rerun = run(["--project", str(project)])
        settings = json.loads(settings_path.read_text())
        check("re-run: idempotent, still one entry per hook",
              rerun.returncode == 0
              and len(our_commands(settings)) == len(hooks))

        dry = run(["--project", str(project), "--uninstall", "--dry-run"])
        settings_after_dry = json.loads(settings_path.read_text())
        check("dry-run uninstall: reports but changes nothing",
              dry.returncode == 0 and settings_after_dry == settings
              and len(list((project / ".claude" / "hooks" / "flightrules")
                           .glob("*.py"))) == len(hooks))

        proc = run(["--project", str(project), "--uninstall"])
        settings = json.loads(settings_path.read_text())
        check("uninstall: exits 0", proc.returncode == 0, proc.stderr[:200])
        check("uninstall: no flightrules entries left",
              not our_commands(settings))
        check("uninstall: flightrules dir removed",
              not (project / ".claude" / "hooks" / "flightrules").exists())
        check("uninstall: user hook entry still present",
              any(h.get("command") == "echo user-hook"
                  for g in settings.get("hooks", {}).get("PreToolUse", [])
                  for h in g.get("hooks", [])))

    with tempfile.TemporaryDirectory(prefix="fr-install-") as tmp:
        project = Path(tmp)
        proc = run(["--project", str(project), "--hooks", "secret-leak-guard",
                    "--local"])
        local_path = project / ".claude" / "settings.local.json"
        settings = json.loads(local_path.read_text())
        files = list((project / ".claude" / "hooks" / "flightrules").glob("*.py"))
        check("selective --local install: exits 0", proc.returncode == 0,
              proc.stderr[:200])
        check("selective: exactly one hook installed",
              [f.name for f in files] == ["secret-leak-guard.py"])
        check("selective: exactly one settings entry",
              len(our_commands(settings)) == 1)
        check("selective: plain settings.json untouched",
              not (project / ".claude" / "settings.json").exists())

        bad = run(["--project", str(project), "--hooks", "no-such-hook"])
        check("unknown hook name: exits nonzero and names it",
              bad.returncode != 0 and "no-such-hook" in bad.stderr)

    with tempfile.TemporaryDirectory(prefix="fr-install-") as tmp:
        project = Path(tmp)
        settings_path = project / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{not json")
        proc = run(["--project", str(project)])
        check("corrupt settings.json: refuses, exits nonzero, file untouched",
              proc.returncode != 0
              and settings_path.read_text() == "{not json"
              and not (project / ".claude" / "hooks").exists())

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        return 1
    print("all installer tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
