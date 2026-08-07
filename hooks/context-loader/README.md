# context-loader

Orients the agent the moment a session starts. Every session otherwise
opens with the same ritual: `git status`, `git log`, "what branch am I
on?". This hook injects that state as context up front, so the first
model turn starts informed instead of spending tool calls rediscovering
the obvious.

**Event:** SessionStart (all sources: startup, resume, clear, compact)

**Emits** (as `additionalContext`, only when `{cwd}/.git` exists):
- current branch, parsed directly from `.git/HEAD` - works even with no
  `git` binary on PATH, and handles worktree/submodule `.git` pointer
  files and detached HEAD (`detached HEAD at <short-hash>`)
- last 5 commits from `git log --oneline -5`
- dirty file count from `git status --porcelain`

If the cwd is not a repo, the hook emits nothing at all. If `git` is
absent, fails, or is slow, those lines are silently omitted rather than
delaying the session: each git call gets a 2s timeout inside a 5s total
budget, and no network is ever touched (both commands are local-only).

**Config:**

| Env var | Effect |
|---------|--------|
| `FR_CONTEXT_OFF=1` | disable entirely |

**Honest limitations:** the hook looks only at `{cwd}/.git` and does not
search parent directories, so a session started in a subdirectory of a
repo gets no context (cheap and predictable beats clever). The dirty
count is a signal, not an audit: it counts `--porcelain` lines, so a
rename counts once and each untracked file counts individually, and it
respects your git config (e.g. `status.showUntrackedFiles=no` lowers
it). On very large repos `git status` can exceed its 2s timeout, in
which case the count is dropped for that session. The snapshot is taken
at session start and is not refreshed afterwards.

**Fail-open contract:** malformed stdin exits 0 silently; internal
errors exit 1 (non-blocking). A broken loader never wrecks your
session, and a slow repo degrades to fewer lines, never to a stall.

**Install:** copy `hook.py` to
`.claude/hooks/flightrules/context-loader.py` and merge `hook.json`
into `.claude/settings.json`.
