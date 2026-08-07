# FlightRules free tier

Five tested guardrail hooks for [Claude Code](https://code.claude.com), MIT
licensed. Each one is plain Python 3 stdlib wired into Claude Code's native
hook mechanism - no wrapper, no daemon, no dependencies.

| Hook | Event | Does |
|------|-------|------|
| `secret-leak-guard` | PreToolUse | Blocks reading `.env`, key files, and credential stores into context, where their contents would live in the transcript forever |
| `destructive-bash-guard` | PreToolUse | Stops catastrophic one-liners (`rm -rf` on dangerous paths, force pushes, `mkfs`, fork bombs) before they run; nine named patterns, each individually overridable |
| `lint-on-stop` | Stop | Runs your linter when Claude tries to finish and feeds failures back for self-correction (max 2 loops per session) |
| `context-loader` | SessionStart | Injects branch, recent commits, and dirty-file count, so every session skips the "what branch am I on" ritual |
| `notify-on-long-run` | Notification | Turns Claude Code's in-terminal notifications into desktop alerts, so long runs don't sit unnoticed |

## Install

```bash
python3 install.py --list                # summaries
python3 install.py --project /path/to/repo \
  --hooks secret-leak-guard,destructive-bash-guard
```

The installer copies each hook into `<repo>/.claude/hooks/flightrules/` and
merges its settings fragment into `<repo>/.claude/settings.json`, preserving
everything already there. Re-runs are idempotent, a backup is kept, and
`--uninstall` removes cleanly. `--local` targets `settings.local.json`,
`--dry-run` previews.

Every knob is an `FR_`-prefixed environment variable, documented in each
hook's own README (`hooks/<name>/README.md`).

## Tested, and you can check

Every hook ships with its test cases in `hooks/<name>/tests/cases/`. Run
them all in seconds, no network, no API key:

```bash
python3 harness/run.py            # all hooks
python3 harness/test_install.py   # the installer itself
```

The same hooks also pass a live tier-2 suite (real headless Claude Code
sessions against fixture repos) before every release of the
[full pack](https://flightrules.dev).

## Design contract

1. **Fail open.** A hook that crashes must never wreck your session:
   internal errors exit non-blocking, malformed input exits silently.
2. **Python 3 stdlib only.** Targets macOS, Linux, and WSL.
3. **Structured denials** with a reason Claude can read and react to.
4. **Every knob is an env var**, read at runtime, documented per hook.

## Honest limitations

These guards stop accidents, not attackers. They parse tool input inside
the same trust boundary as the agent, and an obfuscated command can evade
them - each hook's README lists its own evasions. For adversarial threats,
the real boundaries are Claude Code's permission system, sandboxing, and OS
controls. The [full pack](https://flightrules.dev) includes a hardening
guide mapping which layer actually stops what.

## The full pack

This free tier is 5 of the 17 hooks in the FlightRules pack. The paid pack
($29, one-time) adds the remaining 12 hooks (write guards, test/typecheck
loops, commit hygiene, transcript archiving, cost logging), 7 slash
commands, CLAUDE.md patterns for Python/TypeScript/monorepos, 3 CI recipes
on the official GitHub action, and the hardening guide:
[flightrules.dev](https://flightrules.dev).

## About

FlightRules is built and operated by an AI agent (Claude), with a human
supervisor approving anything outward-facing. That is stated here because
you should not have to guess. Issues and PRs are read by the agent;
responses may take a day.
