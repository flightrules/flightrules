# lint-on-stop

Runs the project's linter when Claude tries to finish responding, and
blocks the stop with the lint output when it fails. Sessions stop ending
with a red linter that nobody ran; Claude sees the errors and fixes them
before handing back.

**Event:** Stop

**Command resolution** (first match wins):

1. `FR_LINT_CMD` if set (run via shell in the session cwd)
2. `package.json` with a `scripts.lint` entry, and the `npm` binary on
   PATH -> `npm run -s lint`
3. `pyproject.toml` containing `[tool.ruff`, or a `ruff.toml`, and the
   `ruff` binary on PATH -> `ruff check .`
4. nothing found -> allow silently, run nothing

Exit 0 from the lint command allows the stop silently. Any other exit
blocks it with `lint failed:` plus the last 2000 chars of lint output.

**Loop guard:** a per-session counter (keyed by `session_id`, stored in
`FR_STATE_DIR`) counts blocked stops. After 2 blocks in one session the
hook allows the stop with a visible warning instead of blocking again, so
a lint failure Claude cannot fix never traps the session in a block loop.
A passing lint run resets the counter.

**Config:**

| Env var | Effect |
|---------|--------|
| `FR_LINT_OFF=1` | disable entirely |
| `FR_LINT_CMD=cmd` | lint command (shell), overrides autodetection |
| `FR_LINT_TIMEOUT=120` | seconds before the lint run is abandoned (allow with warning) |
| `FR_STATE_DIR=dir` | loop-guard counter location (default: system temp dir) |

**Honest limitations:** the lint command runs via `shell=True` in the
session cwd with no sandboxing - your lint script is executed as-is, so
treat lint config as code. Autodetection is deliberately narrow (npm
`scripts.lint`, ruff); monorepos and other linters need `FR_LINT_CMD`.
Both autodetected commands require their binary on PATH, which is checked
rather than assumed: under `shell=True` a missing binary is exit 127, not
an exception, and reporting `npm: not found` to the model as a lint
failure would block the stop over nothing. Worth knowing if you use nvm,
since it loads in interactive shells and a hook subprocess is not one -
set `FR_LINT_CMD` to an absolute path if you want lint to run there.
The lint run adds its full duration to every stop - keep it fast or cap
it with `FR_LINT_TIMEOUT` (a timeout allows the stop with a warning, it
does not block). Only the command's exit code is consulted; a linter that
reports problems but exits 0 will not block. Loop-guard state files are
small, live in the temp dir, and are left to the OS temp cleaner; a
resumed session keeps its counter until a lint run passes.

**Fail-open contract:** malformed stdin exits 0 silently; no detectable
lint command exits 0 silently; a lint timeout or unwritable state dir
allows the stop with a warning; internal errors exit 1 (non-blocking). A
broken hook never wrecks your session.

**Install:** copy `hook.py` to
`.claude/hooks/flightrules/lint-on-stop.py` and merge `hook.json` into
`.claude/settings.json`.
