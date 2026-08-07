# secret-leak-guard

Stops secret material from being read into context. Once an agent cats your
`.env`, those values live in the transcript, the context window, and any
logs downstream. This hook makes that a structured denial instead.

**Event:** PreToolUse on `Read|Grep|Bash`

**Blocks:**
- `Read`/`Grep` of `.env`, `.env.*`, private keys (`*.pem`, `*.key`,
  `id_rsa*`, ...), credential stores (`.netrc`, `.npmrc`, `.pypirc`,
  `.git-credentials`, `.aws/credentials`, `.kube/config`, ...),
  `*.tfvars`, `secrets.*`
- `Bash` commands that combine a read-capable verb (`cat`, `grep`,
  `source`, `base64`, `curl`, ...) with a secret-file token. `cp
  .env.example .env` passes (no read verb); `cat .env` does not.

**Allows:** `.env.example`, `.env.sample`, `.env.template`, `*.pub`.

**Config:**

| Env var | Effect |
|---------|--------|
| `FR_SECRET_GUARD_OFF=1` | disable entirely |
| `FR_SECRET_EXTRA=glob:glob` | extra deny globs (basename) |
| `FR_SECRET_ALLOW=glob:glob` | extra allow globs (basename) |

**Honest limitations:** this defends against accidents, not adversaries. An
obfuscated command (`cat $(echo LmVudg== | base64 -d)`) evades the token
heuristic. The guard also cannot see inside scripts that Bash executes. For
adversarial contexts, use OS-level permissions and Claude Code's permission
system as the real boundary; this hook is the seatbelt, not the airbag.

**Fail-open contract:** malformed stdin exits 0 silently; internal errors
exit 1 (non-blocking). A broken guard never wrecks your session.

**Install:** copy `hook.py` to
`.claude/hooks/flightrules/secret-leak-guard.py` and merge `hook.json` into
`.claude/settings.json`.
