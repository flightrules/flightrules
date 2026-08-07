#!/usr/bin/env python3
"""FlightRules installer: wire pack hooks into a project's Claude Code config.

Copies each selected hook's hook.py into
  <project>/.claude/hooks/flightrules/<name>.py
and merges its hook.json fragment into <project>/.claude/settings.json
(or settings.local.json with --local). Everything else already in the
settings file is preserved; re-running is idempotent - existing FlightRules
entries are replaced, never duplicated. The previous settings file is kept
as settings.json.bak unless --no-backup.

Usage:
  python3 install.py [--project PATH] [--hooks a,b,c] [--local] [--dry-run]
  python3 install.py --list
  python3 install.py --uninstall [--project PATH] [--hooks a,b,c] [--local]

Requires python3, nothing else. Never edits anything outside
<project>/.claude/.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent
HOOKS_DIR = PACK / "hooks"
INSTALL_SUBDIR = Path(".claude") / "hooks" / "flightrules"
MARKER = "/flightrules/"  # identifies our command entries inside settings


def available_hooks():
    return sorted(
        d.name for d in HOOKS_DIR.iterdir()
        if d.is_dir() and (d / "hook.py").is_file() and (d / "hook.json").is_file()
    )


def hook_summary(name):
    """First prose line of the hook's README, as a one-line description."""
    readme = HOOKS_DIR / name / "README.md"
    try:
        for line in readme.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except OSError:
        pass
    return ""


def load_settings(path):
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"error: cannot parse {path}: {e}\n"
                 "Fix or move it first; refusing to overwrite a file "
                 "I cannot read.")
    if not isinstance(settings, dict):
        sys.exit(f"error: {path} is not a JSON object; refusing to touch it.")
    return settings


def is_ours(entry, names):
    command = entry.get("command", "") if isinstance(entry, dict) else ""
    return any(f"{MARKER}{n}.py" in command for n in names)


def strip_entries(settings, names):
    """Remove our command entries for the given hook names. Returns count."""
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            kept = [h for h in group["hooks"] if not is_ours(h, names)]
            removed += len(group["hooks"]) - len(kept)
            group["hooks"] = kept
        hooks[event] = [
            g for g in groups
            if not isinstance(g, dict) or g.get("hooks") or "hooks" not in g
        ]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return removed


def merge_fragment(settings, fragment):
    """Append the fragment's matcher groups into settings['hooks']."""
    for event, groups in (fragment.get("hooks") or {}).items():
        settings.setdefault("hooks", {}).setdefault(event, []).extend(groups)


def write_settings(path, settings, backup):
    if path.exists() and backup:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def resolve_names(arg):
    every = available_hooks()
    if not arg:
        return every
    names = [n.strip() for n in arg.split(",") if n.strip()]
    unknown = sorted(set(names) - set(every))
    if unknown:
        sys.exit(f"error: unknown hooks: {', '.join(unknown)}\n"
                 f"available: {', '.join(every)}")
    return names


def cmd_list():
    for name in available_hooks():
        print(f"{name:24} {hook_summary(name)}")


def cmd_install(project, names, settings_path, dry_run, backup):
    target_dir = project / INSTALL_SUBDIR
    settings = load_settings(settings_path)
    strip_entries(settings, names)
    for name in names:
        fragment = json.loads((HOOKS_DIR / name / "hook.json").read_text(encoding="utf-8"))
        merge_fragment(settings, fragment)
    if dry_run:
        print(f"would copy {len(names)} hook(s) into {target_dir}")
        print(f"would update {settings_path} with entries for: {', '.join(names)}")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        dest = target_dir / f"{name}.py"
        shutil.copy2(HOOKS_DIR / name / "hook.py", dest)
        # Zip extraction (Python zipfile, macOS Archive Utility) drops the
        # exec bit, so guarantee it here instead of trusting the source.
        dest.chmod(dest.stat().st_mode | 0o755)
        print(f"installed {dest.relative_to(project)}")
    write_settings(settings_path, settings, backup)
    print(f"updated {settings_path.relative_to(project)} "
          f"({len(names)} hook(s) wired)")
    print("Restart your Claude Code session (or /hooks reload) to activate.")


def cmd_uninstall(project, names, settings_path, dry_run, backup):
    target_dir = project / INSTALL_SUBDIR
    settings = load_settings(settings_path)
    removed = strip_entries(settings, names)
    files = [target_dir / f"{n}.py" for n in names if (target_dir / f"{n}.py").exists()]
    if dry_run:
        print(f"would remove {removed} settings entr(ies) and "
              f"{len(files)} file(s) from {target_dir}")
        return
    for f in files:
        f.unlink()
        print(f"removed {f.relative_to(project)}")
    if target_dir.exists() and not any(target_dir.iterdir()):
        target_dir.rmdir()
    if settings or settings_path.exists():
        write_settings(settings_path, settings, backup)
    print(f"updated {settings_path.relative_to(project)} "
          f"({removed} entr(ies) removed)")


def main():
    parser = argparse.ArgumentParser(
        description="Install FlightRules hooks into a project's Claude Code config.")
    parser.add_argument("--project", default=".",
                        help="project root (default: current directory)")
    parser.add_argument("--hooks", default="",
                        help="comma-separated hook names (default: all)")
    parser.add_argument("--local", action="store_true",
                        help="write to settings.local.json instead of settings.json")
    parser.add_argument("--list", action="store_true",
                        help="list available hooks and exit")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove FlightRules hooks instead of installing")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without writing")
    parser.add_argument("--no-backup", action="store_true",
                        help="do not keep a .bak of the previous settings file")
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return
    project = Path(args.project).resolve()
    if not project.is_dir():
        sys.exit(f"error: project directory not found: {project}")
    names = resolve_names(args.hooks)
    settings_name = "settings.local.json" if args.local else "settings.json"
    settings_path = project / ".claude" / settings_name
    if args.uninstall:
        cmd_uninstall(project, names, settings_path, args.dry_run,
                      backup=not args.no_backup)
    else:
        cmd_install(project, names, settings_path, args.dry_run,
                    backup=not args.no_backup)


if __name__ == "__main__":
    main()
