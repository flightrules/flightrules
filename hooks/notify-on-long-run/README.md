# notify-on-long-run

Turns Claude Code's in-terminal notifications into desktop ones. Long runs
end with a permission prompt or a question in a terminal you stopped
watching twenty minutes ago; this hook pings your desktop instead, so you
can walk away without babysitting the session.

**Event:** Notification (any matcher)

**Behavior:** picks the first notifier that exists and fires it once per
Notification event:

1. `FR_NOTIFY_CMD` if set - your command template, with `{title}` and
   `{message}` placeholders, run via the shell
2. `notify-send` if on PATH (Linux desktops)
3. `osascript` display notification (macOS)
4. none of the above: exits 0 silently

Title is always `Claude Code`; the message is the stdin `message` field,
falling back to `Claude Code needs your attention` when absent or empty.

**Config:**

| Env var | Effect |
|---------|--------|
| `FR_NOTIFY_OFF=1` | disable entirely |
| `FR_NOTIFY_CMD='...'` | custom notifier template, e.g. `ntfy publish claude {message}` or `powershell.exe -c "..."` on WSL |

Placeholders are substituted already shell-quoted, so write
`notify-send {title} {message}`, not `notify-send "{title}" "{message}"`;
message content can never become shell syntax.

**Honest limitations:** despite the name, there is no duration threshold -
Notification events carry no timing info, so the hook fires on every one
(in practice: permission prompts and idle-input waits, which is exactly
when long runs need you). It does not dedupe or rate-limit; a burst of
events is a burst of toasts. Over SSH or on headless boxes `notify-send`
may exist but have no session bus to talk to; the failure lands as a
one-line note in the debug log, not on your screen. On WSL there is
usually no `notify-send`, so set `FR_NOTIFY_CMD` (e.g. via
`powershell.exe` or `wsl-notify-send`). Your notifier's own stdout/stderr
is discarded.

**Fail-open contract:** malformed stdin exits 0 silently; a failing or
hanging notify command (5s cap) gets a one-line stderr note and still
exits 0; internal errors exit 1 (non-blocking). A broken notifier never
wrecks your session.

**Install:** copy `hook.py` to
`.claude/hooks/flightrules/notify-on-long-run.py` and merge `hook.json`
into `.claude/settings.json`.
