#!/usr/bin/env python3
"""destructive-bash-guard: stop catastrophic Bash commands before they run.

PreToolUse on Bash. Denies (via structured JSON, not exit 2) commands that
match named high-risk patterns:
- rm-recursive-force   rm with -r and -f targeting /, ~/$HOME, a path that
                       escapes or equals the session cwd, or a '/*' sweep
                       (relative paths inside the project stay allowed)
- git-force-push       git push --force / -f to main or master, any remote
- git-clean-root       git clean -f -d -x at the repo root, no pathspec
- dd-device-write      dd of=/dev/<device> (null/zero/stdout/stderr exempt)
- mkfs                 mkfs or mkfs.* (formats a filesystem)
- system-power         shutdown / reboot / halt / poweroff (incl. systemctl)
- recursive-perms      chmod/chown -R on / or ~
- fork-bomb            the :(){ ...|...& };: fork bomb
- disk-redirect        shell redirection onto a raw block device

Threat model: accidents, not adversaries. This catches the classic one-line
disasters an agent can produce under pressure; a determined obfuscated
command can evade token analysis. That is documented, not hidden.

Config (env vars):
  FR_DESTRUCTIVE_GUARD_OFF=1   disable entirely
  FR_DESTRUCTIVE_ALLOW=a:b     allow named patterns (colon-separated)

Fail-open contract: malformed stdin exits 0 silently; internal errors exit 1
(non-blocking) with a one-line stderr note. The session is never wrecked.
"""
import json
import os
import re
import shlex
import sys

PUNCT = set(";|&()<>")
POWER_VERBS = {"shutdown", "reboot", "halt", "poweroff"}
POWER_ARGS = {"reboot", "poweroff", "halt"}
SAFE_DEVICES = {"/dev/null", "/dev/zero", "/dev/stdout", "/dev/stderr", "/dev/tty"}
DEVICE_RE = re.compile(r"^/dev/(sd|hd|vd|xvd|nvme|mmcblk|disk)")
FORK_BOMB_RE = re.compile(r":\s*\(\s*\)\s*\{")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "nohup", "time", "exec"}
GIT_ARG_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_ARG_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def normalize(command):
    """Return (analyzed, masked): unquoted newlines become ';', analysis stops
    at an unquoted heredoc (its body is data, not commands), and `masked` has
    quoted spans blanked out for raw-regex checks."""
    analyzed, masked = [], []
    quote = None
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if quote:
            if quote == '"' and c == "\\" and i + 1 < n:
                analyzed.append(command[i:i + 2])
                masked.append("  ")
                i += 2
                continue
            if c == quote:
                quote = None
                masked.append(c)
            else:
                masked.append(" ")
            analyzed.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            analyzed.append(command[i:i + 2])
            masked.append(command[i:i + 2])
            i += 2
            continue
        if c in ("'", '"'):
            quote = c
            analyzed.append(c)
            masked.append(c)
            i += 1
            continue
        if c == "<" and command[i:i + 2] == "<<" and command[i:i + 3] != "<<<":
            break
        if c == "\n":
            analyzed.append(";")
            masked.append(";")
            i += 1
            continue
        analyzed.append(c)
        masked.append(c)
        i += 1
    return "".join(analyzed), "".join(masked)


def tokenize(text):
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:  # unbalanced quotes: degrade to a crude token scan
        return re.findall(r"[;|&()<>]+|[^\s;|&()<>]+", text)


def split_segments(tokens):
    segments, current = [], []
    for tok in tokens:
        if tok and set(tok) <= PUNCT:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def strip_wrappers(segment):
    i = 0
    while i < len(segment):
        tok = segment[i]
        if ASSIGN_RE.match(tok):
            i += 1
            continue
        if tok in WRAPPERS:
            i += 1
            while i < len(segment) and segment[i].startswith("-"):
                consumes = segment[i] in ("-u", "-g") and tok in ("sudo", "doas")
                i += 2 if consumes else 1
            continue
        if tok == "timeout":
            i += 1
            while i < len(segment) and (segment[i].startswith("-") or re.match(r"^\d", segment[i])):
                i += 1
            continue
        break
    return segment[i:]


def get_home():
    home = os.path.expanduser("~")
    return home if home and home != "~" else None


def expand(target, home):
    t = target
    if home:
        if t == "~" or t.startswith("~/"):
            t = home + t[1:]
        t = t.replace("${HOME}", home).replace("$HOME", home)
    return t


def within(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def rm_target_danger(target, cwd, home):
    """Return a human-readable danger description for one rm target, or None."""
    if target.endswith("/*"):
        return f"'{target}' sweeps everything under '{target[:-2] or '/'}'"
    if not home and target in ("~", "$HOME", "${HOME}"):
        return f"'{target}' is the home directory"
    norm = os.path.normpath(expand(target, home))
    ncwd = os.path.normpath(cwd)
    if norm in ("/", "//"):
        return f"'{target}' is the filesystem root"
    if home and norm == os.path.normpath(home):
        return f"'{target}' is the home directory"
    if os.path.isabs(norm):
        if norm == ncwd:
            return f"'{target}' is the session working directory itself"
        if not within(norm, ncwd):
            return f"'{target}' is an absolute path outside the session working directory"
        return None
    resolved = os.path.normpath(os.path.join(ncwd, norm))
    if resolved == ncwd:
        return f"'{target}' resolves to the session working directory itself"
    if not within(resolved, ncwd):
        return f"'{target}' escapes the session working directory via '..'"
    return None


def check_rm(args, cwd, home):
    recursive = force = end_flags = False
    targets = []
    for tok in args:
        if not end_flags and tok == "--":
            end_flags = True
        elif not end_flags and tok.startswith("--"):
            recursive = recursive or tok == "--recursive"
            force = force or tok == "--force"
        elif not end_flags and tok.startswith("-") and len(tok) > 1:
            recursive = recursive or bool(set("rR") & set(tok[1:]))
            force = force or "f" in tok[1:]
        else:
            targets.append(tok)
    if not (recursive and force):
        return None
    for target in targets:
        danger = rm_target_danger(target, cwd, home)
        if danger:
            return ("rm-recursive-force", f"recursive force delete: {danger}.")
    return None


def check_git(args, cwd):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_ARG_FLAGS else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]

    if sub == "push":
        force = False
        positional = []
        skip_next = False
        for tok in rest:
            if skip_next:
                skip_next = False
            elif tok in PUSH_ARG_FLAGS:
                skip_next = True
            elif tok == "--force" or (
                tok.startswith("-") and not tok.startswith("--") and "f" in tok[1:]
            ):
                force = True
            elif not tok.startswith("-"):
                positional.append(tok)
        if force:
            for refspec in positional[1:]:  # positional[0] is the remote
                dest = refspec.lstrip("+").rsplit(":", 1)[-1]
                if dest in ("main", "master"):
                    return (
                        "git-force-push",
                        f"force push to '{dest}' rewrites history on a protected branch.",
                    )
        return None

    if sub == "clean":
        flags = set()
        pathspecs = []
        for tok in rest:
            if tok == "--force":
                flags.add("f")
            elif tok == "--dry-run":
                flags.add("n")
            elif tok.startswith("-") and not tok.startswith("--"):
                flags |= set(tok[1:])
            elif not tok.startswith("-"):
                pathspecs.append(tok)
        at_repo_root = os.path.exists(os.path.join(cwd, ".git"))
        if {"f", "d", "x"} <= flags and "n" not in flags and at_repo_root and not pathspecs:
            return (
                "git-clean-root",
                "git clean -f -d -x at the repo root deletes every untracked and "
                "ignored file (.env, node_modules, IDE state, ...).",
            )
    return None


def check_dd(args):
    for tok in args:
        if tok.startswith("of="):
            dest = tok[3:]
            if dest.startswith("/dev/") and os.path.normpath(dest) not in SAFE_DEVICES:
                return ("dd-device-write", f"dd writes raw bytes to device '{dest}'.")
    return None


def check_perms(verb, args, home):
    recursive = any(
        tok == "--recursive"
        or (tok.startswith("-") and not tok.startswith("--") and "R" in tok[1:])
        for tok in args
    )
    if not recursive:
        return None
    for tok in args:
        if tok.startswith("-"):
            continue
        norm = os.path.normpath(expand(tok, home))
        if (
            norm in ("/", "//")
            or (home and norm == os.path.normpath(home))
            or tok in ("~", "$HOME", "${HOME}")
        ):
            where = "the filesystem root" if norm in ("/", "//") else "the home directory"
            return (
                "recursive-perms",
                f"'{verb} -R' on '{tok}' rewrites ownership/permissions across {where}.",
            )
    return None


def check_segment(segment, cwd, home):
    segment = strip_wrappers(segment)
    if not segment:
        return None
    verb = segment[0].strip("`").lstrip("\\").rsplit("/", 1)[-1]
    args = segment[1:]
    if verb == "rm":
        return check_rm(args, cwd, home)
    if verb == "git":
        return check_git(args, cwd)
    if verb == "dd":
        return check_dd(args)
    if verb == "mkfs" or verb.startswith("mkfs."):
        return ("mkfs", f"'{verb}' formats a filesystem, destroying its contents.")
    if verb in POWER_VERBS:
        return ("system-power", f"'{verb}' powers down or restarts the host.")
    if verb == "systemctl" and POWER_ARGS & set(args):
        return ("system-power", "'systemctl' powers down or restarts the host.")
    if verb in ("chmod", "chown"):
        return check_perms(verb, args, home)
    return None


def find_violation(command, cwd, allowed):
    analyzed, masked = normalize(command)
    if "fork-bomb" not in allowed and FORK_BOMB_RE.search(masked):
        return ("fork-bomb", "':(){ ...' defines a fork bomb that exhausts the host.")
    tokens = tokenize(analyzed)
    if "disk-redirect" not in allowed:
        for i in range(len(tokens) - 1):
            if ">" in tokens[i] and set(tokens[i]) <= PUNCT and DEVICE_RE.match(tokens[i + 1]):
                return (
                    "disk-redirect",
                    f"redirects output onto raw block device '{tokens[i + 1]}'.",
                )
    home = get_home()
    for segment in split_segments(tokens):
        violation = check_segment(segment, cwd, home)
        if violation and violation[0] not in allowed:
            return violation
    return None


def deny_response(name, detail):
    reason = (
        f"destructive-bash-guard [{name}]: {detail} If this is genuinely "
        "intended, ask the user to run it themselves, or to waive this one "
        f"rule for the session (FR_DESTRUCTIVE_ALLOW={name})."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed stdin: fail open, stay silent
    if os.environ.get("FR_DESTRUCTIVE_GUARD_OFF") == "1":
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        return 0
    cwd = data.get("cwd") or os.getcwd()
    allowed = {p for p in os.environ.get("FR_DESTRUCTIVE_ALLOW", "").split(":") if p}
    violation = find_violation(command, cwd, allowed)
    if violation:
        deny_response(*violation)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail open: never wreck the session
        print(f"destructive-bash-guard internal error: {e}", file=sys.stderr)
        sys.exit(1)
