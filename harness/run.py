#!/usr/bin/env python3
"""FlightRules test harness, tier 1: deterministic hook tests.

Runs every hook's tests/cases/*.json against its hook.py with synthetic
stdin, asserting on exit code, stdout JSON, and stderr. No LLM calls, no
network. Tier 2 (live headless Claude Code sessions) builds on the same
case files and runs pre-release.

Usage:
  python3 harness/run.py            # all hooks
  python3 harness/run.py <hook>...  # specific hook(s)

Case file schema:
{
  "name": "human-readable case name",
  "stdin": { ... hook stdin JSON; "{CWD}" in strings -> fixture dir ... },
  "stdin_raw": "literal stdin string (alternative to stdin, e.g. bad JSON)",
  "env": { "FR_SOMETHING": "1" },              // optional
  "fixture": { "files": { "rel/path": "content" } },  // optional temp dir
  "expect": {
    "exit": 0,                                  // required
    "stdout_json": { "dot.path": "expected" },  // optional, deep-get match
    "stdout_contains": "substr",                // optional
    "stdout_not_contains": ["substr", ...],     // optional, none may appear
    "stderr_contains": "substr",                // optional
    "stdout_empty": true,                       // optional
    "file_contains": { "rel/path": "substr" },  // optional, fixture dir post-run
    "file_absent": ["rel/path"]                 // optional, fixture dir post-run
  }
}
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
LOG = Path(__file__).resolve().parent / "last-run.log"


def deep_get(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def substitute(value, cwd):
    if isinstance(value, str):
        return value.replace("{CWD}", cwd)
    if isinstance(value, dict):
        return {k: substitute(v, cwd) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, cwd) for v in value]
    return value


def run_case(hook_dir, case_path):
    case = json.loads(case_path.read_text())
    failures = []
    with tempfile.TemporaryDirectory(prefix="fr-harness-") as tmp:
        for rel, content in case.get("fixture", {}).get("files", {}).items():
            p = Path(tmp) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        if "stdin_raw" in case:
            stdin_text = case["stdin_raw"]
        else:
            stdin_obj = substitute(case["stdin"], tmp)
            stdin_obj.setdefault("cwd", tmp)
            stdin_text = json.dumps(stdin_obj)
        env = dict(os.environ)
        env.update(case.get("env", {}))
        proc = subprocess.run(
            [sys.executable, str(hook_dir / "hook.py")],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp,
            timeout=30,
        )
        post_files = {}
        exp = case["expect"]
        for rel in list(exp.get("file_contains", {})) + list(exp.get("file_absent", [])):
            p = Path(tmp) / rel
            post_files[rel] = p.read_text() if p.exists() else None
    if proc.returncode != exp["exit"]:
        failures.append(
            f"exit: want {exp['exit']}, got {proc.returncode} "
            f"(stderr: {proc.stderr.strip()[:200]})"
        )
    if exp.get("stdout_empty") and proc.stdout.strip():
        failures.append(f"stdout not empty: {proc.stdout.strip()[:200]}")
    if "stdout_contains" in exp and exp["stdout_contains"] not in proc.stdout:
        failures.append(f"stdout missing {exp['stdout_contains']!r}: {proc.stdout.strip()[:200]}")
    for banned in exp.get("stdout_not_contains", []):
        if banned in proc.stdout:
            failures.append(f"stdout contains banned {banned!r}: {proc.stdout.strip()[:200]}")
    if "stderr_contains" in exp and exp["stderr_contains"] not in proc.stderr:
        failures.append(f"stderr missing {exp['stderr_contains']!r}: {proc.stderr.strip()[:200]}")
    if "stdout_json" in exp:
        try:
            out = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            out = None
            failures.append(f"stdout is not JSON: {proc.stdout.strip()[:200]}")
        if out is not None:
            for path, want in exp["stdout_json"].items():
                got = deep_get(out, path)
                if got != want:
                    failures.append(f"stdout json {path}: want {want!r}, got {got!r}")
    for rel, want in exp.get("file_contains", {}).items():
        content = post_files.get(rel)
        if content is None:
            failures.append(f"file {rel}: expected to exist")
        elif want not in content:
            failures.append(f"file {rel}: missing {want!r} (got: {content[:200]!r})")
    for rel in exp.get("file_absent", []):
        if post_files.get(rel) is not None:
            failures.append(f"file {rel}: expected to be absent")
    return case.get("name", case_path.stem), failures


def main():
    wanted = sys.argv[1:]
    hook_dirs = sorted(
        d for d in (PACK / "hooks").iterdir()
        if d.is_dir() and (d / "hook.py").exists()
    )
    if wanted:
        hook_dirs = [d for d in hook_dirs if d.name in wanted]
        missing = set(wanted) - {d.name for d in hook_dirs}
        if missing:
            print(f"unknown hooks: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    total = passed = 0
    lines = []
    for hook_dir in hook_dirs:
        cases = sorted(hook_dir.glob("tests/cases/*.json"))
        if not cases:
            lines.append(f"FAIL {hook_dir.name}: no test cases")
            total += 1
            continue
        for case_path in cases:
            total += 1
            try:
                name, failures = run_case(hook_dir, case_path)
            except Exception as e:  # harness must report, not crash
                name, failures = case_path.stem, [f"harness error: {e}"]
            if failures:
                lines.append(f"FAIL {hook_dir.name} :: {name}")
                lines.extend(f"     - {f}" for f in failures)
            else:
                passed += 1
                lines.append(f"ok   {hook_dir.name} :: {name}")
    summary = f"{passed}/{total} cases passed across {len(hook_dirs)} hooks"
    report = "\n".join(lines + ["", summary])
    print(report)
    if not wanted:  # only full runs write the log (parallel partial runs would race)
        LOG.write_text(report + "\n")
    return 0 if passed == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
