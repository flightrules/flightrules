# destructive-bash-guard

Stops catastrophic Bash one-liners before they run. An agent under pressure
will occasionally reach for `rm -rf` on the wrong path or force-push over
main; this hook turns those moments into a structured denial with a named
reason instead of a lost weekend.

**Event:** PreToolUse on `Bash`

**Blocks (each pattern has a name, usable in `FR_DESTRUCTIVE_ALLOW`):**

| Pattern name | Trigger |
|--------------|---------|
| `rm-recursive-force` | `rm` with both `-r`/`-R` and `-f` (combined or separate, long forms too) targeting `/`, `~`/`$HOME`, a path that escapes or equals the session cwd, an absolute path outside the cwd, or any path ending `/*` |
| `git-force-push` | `git push --force` or `-f` with a refspec landing on `main` or `master` (any remote, `HEAD:main` and `+main` forms included) |
| `git-clean-root` | `git clean` with `-f`, `-d`, and `-x` run at the repo root with no pathspec (wipes `.env`, `node_modules`, IDE state) |
| `dd-device-write` | `dd of=/dev/<device>` (`/dev/null`, `/dev/zero`, `/dev/stdout`, `/dev/stderr`, `/dev/tty` exempt) |
| `mkfs` | `mkfs` or any `mkfs.*` variant |
| `system-power` | `shutdown`, `reboot`, `halt`, `poweroff`, or `systemctl reboot/poweroff/halt` |
| `recursive-perms` | `chmod`/`chown` with `-R` on `/` or `~`/`$HOME` |
| `fork-bomb` | the `:(){ ...\|...& };:` fork bomb |
| `disk-redirect` | shell redirection (`>`, `>>`) onto `/dev/sd*`, `/dev/hd*`, `/dev/vd*`, `/dev/xvd*`, `/dev/nvme*`, `/dev/mmcblk*`, `/dev/disk*` |

**Allows (deliberately):** relative `rm -rf` inside the project
(`rm -rf node_modules` is daily business), absolute `rm -rf` on paths inside
the session cwd, `rm -r` without `-f`, force-push to feature branches,
`--force-with-lease`, `git clean -fdx` in a subdirectory or with an explicit
pathspec, `git clean -fdxn` (dry run), and commands that merely *mention* a
dangerous string in quotes or a heredoc (`echo "rm -rf /"` passes).

The parser is token-based, not substring-based: commands are split on shell
separators (`;`, `&&`, `||`, `|`, newlines, subshells), quoting is
respected, wrapper prefixes (`sudo`, `env`, `nohup`, `timeout 30`, ...) are
stripped, and combined flags (`-rf`, `-fr`, `-r -f`) are decomposed. `echo
halted` does not match `halt`.

**Config:**

| Env var | Effect |
|---------|--------|
| `FR_DESTRUCTIVE_GUARD_OFF=1` | disable entirely |
| `FR_DESTRUCTIVE_ALLOW=name:name` | allow the named patterns above (colon-separated) |

**Honest limitations:** this defends against accidents, not adversaries.
Obfuscation (`rm -rf $(echo Lw== | base64 -d)`), variables (`X=/; rm -rf
$X`), commands hidden inside scripts or `xargs` pipelines, and `git push
--force` with no refspec (current branch unknown) all evade it. Path checks
use lexical normalization, not symlink resolution, so a symlink inside the
project pointing outside it is not caught. Text after an unquoted heredoc
marker is not analyzed. For adversarial contexts, use OS-level permissions
and Claude Code's permission system as the real boundary; this hook is the
seatbelt, not the airbag.

**Fail-open contract:** malformed stdin exits 0 silently; internal errors
exit 1 (non-blocking). A broken guard never wrecks your session.

**Install:** copy `hook.py` to
`.claude/hooks/flightrules/destructive-bash-guard.py` and merge `hook.json`
into `.claude/settings.json`.
