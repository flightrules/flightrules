# FlightRules free tier

[![tests](https://github.com/flightrules/flightrules/actions/workflows/tests.yml/badge.svg)](https://github.com/flightrules/flightrules/actions/workflows/tests.yml)

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

## What a block looks like

Hooks speak Claude Code's JSON protocol on stdin and stdout, so you can run
one by hand without installing anything:

```console
$ echo '{"tool_name":"Bash","tool_input":{"command":"cat .env | grep KEY"}}' \
    | python3 hooks/secret-leak-guard/hook.py | python3 -m json.tool
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "secret-leak-guard: Bash touches '.env' which matches secret pattern '.env'. Reading secrets into context copies them into transcripts and logs. Carry on without this file, or ask the user to supply what you need from it, or to waive '.env' for this session (FR_SECRET_ALLOW)."
    }
}
```

The reason string is what Claude actually receives, which is why it is
written to be acted on rather than just logged: it says what to do instead,
and the waiver it names is scoped to one pattern (see
[Honest limitations](#honest-limitations) for why that detail matters).

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

75 cases across the five hooks, plus the installer's own suite. Each case is
a JSON file in `hooks/<name>/tests/cases/` naming the input, the expected
exit code, and the expected output. They run in seconds, with no network and
no API key:

```bash
python3 harness/run.py            # 75/75 cases across 5 hooks
python3 harness/test_install.py   # the installer itself
```

The badge above is that same pair of commands, run by GitHub on a clean
machine against Python 3.9, 3.11, and 3.13 on Linux and macOS, on every
push and once a week. `harness/last-run.log` is the full case-by-case output
of the run that shipped this exact tree, so you can diff yours against it.

The same hooks also pass a live tier-2 suite (real headless Claude Code
sessions against fixture repos, asserting side effects a model cannot fake)
before every release of the [full pack](https://flightrules.dev).

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
controls; treat these hooks as the seatbelt, not the airbag.

One design rule worth stealing even if you never install this: a denial
reason is fed straight back to the model, so it must never name the
guard's own kill switch. An agent that gets told "denied - or set
`FR_SECRET_GUARD_OFF=1`" has just been handed the off switch at the one
moment it is most motivated to use it. These hooks name only the narrow,
per-rule waiver, and ask the agent to get it from you.

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
