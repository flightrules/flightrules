#!/usr/bin/env python3
"""secret-leak-guard: stop secret material from being read into context.

PreToolUse on Read|Grep|Bash. Denies (via structured JSON, not exit 2):
- Read/Grep targeting secret files (.env, keys, credential stores)
- Bash commands that combine a read-capable verb (cat, grep, source, ...)
  with a secret-file token

Threat model: accidents, not adversaries. This prevents the common failure
mode of an agent casually cat-ing .env into its context (and therefore into
transcripts and logs). A determined obfuscated command can evade the token
heuristic; that is documented, not hidden.

Config (env vars):
  FR_SECRET_GUARD_OFF=1     disable entirely
  FR_SECRET_EXTRA=a:b       extra deny globs (colon-separated, basename)
  FR_SECRET_ALLOW=a:b       extra allow globs (colon-separated, basename)

Fail-open contract: malformed stdin exits 0 silently; internal errors exit 1
(non-blocking) with a one-line stderr note. The session is never wrecked.
"""
import fnmatch
import json
import os
import re
import sys

DENY = [
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "id_ecdsa*",
    "*.p12", "*.pfx", "credentials.json", ".netrc", "_netrc", ".npmrc",
    ".pypirc", ".git-credentials", "*.keystore", "*.jks", "*.tfvars",
    "secrets.yml", "secrets.yaml", "secrets.json",
]
PATH_FRAGMENTS = [".aws/credentials", ".ssh/", ".docker/config.json", ".kube/config"]
ALLOW = [".env.example", ".env.sample", ".env.template", "*.pub"]
READ_VERBS = {
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg",
    "awk", "sed", "cut", "sort", "uniq", "source", ".", "xxd", "od",
    "strings", "base64", "openssl", "scp", "rsync", "curl", "wget", "dd",
    "python", "python3", "node", "ruby", "perl", "php",
}


def match_secret(path, deny, allow):
    base = os.path.basename(path.rstrip("/"))
    if not base:
        return None
    if any(fnmatch.fnmatch(base, g) for g in allow):
        return None
    for g in deny:
        if fnmatch.fnmatch(base, g):
            return g
    norm = path.replace("\\", "/")
    for frag in PATH_FRAGMENTS:
        if frag in norm:
            return frag
    return None


def deny_response(path, pattern, tool):
    reason = (
        f"secret-leak-guard: {tool} touches '{path}' which matches secret "
        f"pattern '{pattern}'. Reading secrets into context copies them into "
        "transcripts and logs. Carry on without this file, or ask the user "
        f"to supply what you need from it, or to waive '{pattern}' for this "
        "session (FR_SECRET_ALLOW)."
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
    if os.environ.get("FR_SECRET_GUARD_OFF") == "1":
        return 0
    deny = DENY + [g for g in os.environ.get("FR_SECRET_EXTRA", "").split(":") if g]
    allow = ALLOW + [g for g in os.environ.get("FR_SECRET_ALLOW", "").split(":") if g]
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    if tool in ("Read", "Grep"):
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        pattern = match_secret(path, deny, allow) if path else None
        if pattern:
            deny_response(path, pattern, tool)
            return 0
    elif tool == "Bash":
        command = tool_input.get("command") or ""
        tokens = [t for t in re.split(r"""[\s;|&<>()"'`]+""", command) if t]
        has_read_verb = any(t.rsplit("/", 1)[-1] in READ_VERBS for t in tokens)
        if has_read_verb:
            for tok in tokens:
                pattern = match_secret(tok, deny, allow)
                if pattern:
                    deny_response(tok, pattern, "Bash")
                    return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail open: never wreck the session
        print(f"secret-leak-guard internal error: {e}", file=sys.stderr)
        sys.exit(1)
