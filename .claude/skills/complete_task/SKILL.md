---
name: complete_task
description: Wrap up and close out a piece of work cleanly — verify it's actually done, run the test suite, commit with a sensible message, and report on completeness. Use this whenever the user signals a task is finished or wants to "wrap up", "close out", "finalize", "ship", or "complete" what they've been working on, or types /complete_task.
---

# Complete Task

A disciplined wrap-up routine. The point is to avoid the two classic failure modes of "done": declaring victory while something is still broken, and committing a mess with a vague message. Work through the four steps in order. Don't skip ahead — each step gates the next.

## Step 1 — Verify the task is actually complete

Before anything else, confirm with the user that the work is genuinely done. You can't reliably know this on your own: "done" depends on intent the user holds in their head (the acceptance criteria, the edge case they cared about, whether a follow-up was meant to be in scope).

Do this:
- Summarize what was accomplished in this task in 1–3 bullets, based on the conversation and the actual diff (`git status` + `git diff`).
- Call out anything you're unsure about — half-finished edges, TODOs left in the code, things explicitly deferred.
- Ask the user plainly: **"Does this look complete to you, or is something still missing?"**

Wait for their confirmation before proceeding. If they say something's missing, that's not a wrap-up anymore — help them finish it first, then come back to this step.

## Step 2 — Run the tests and make sure they pass

**First, decide whether tests are even relevant.** If the task only touched files that no test exercises — a skill, docs, README, comments, config that the suite doesn't load — running the suite proves nothing and just wastes time. In that case, skip it and say so plainly: "this only changed `<file>`, which no test covers — skipping the suite." Look at the actual diff to make this call; if any code under test changed (even indirectly), run the tests.

Otherwise, run the suite and read the output. A green run is the floor for committing.

For this project:
- Tests: `.venv/Scripts/python.exe -m pytest` (config in `pyproject.toml`, `testpaths = ["tests"]`). **Use the venv interpreter, not bare `python`** — the project requires Python ≥3.12 (it imports `StrEnum`), and the `python` on PATH here is 3.10, which fails at import time with a confusing `ModuleNotFoundError`/`StrEnum` error rather than a real test failure. The `.venv` has the right interpreter and the package installed.
- Lint: `.venv/Scripts/python.exe -m ruff check src tests` — worth running too, since it's part of the project's bar.

If you're in a different project, detect the runner the usual way (look for `pyproject.toml`, `package.json`, `Makefile`, `go.mod`, etc.) rather than assuming.

Report the result honestly:
- **All pass** → say so with the summary line (e.g. "142 passed") and move on.
- **Failures** → STOP. Do not commit. Show the failing output, diagnose whether the failure is from this task's changes or pre-existing, and help fix it. Only continue once tests are green (or the user explicitly accepts a known failure and tells you to proceed anyway).

If there are genuinely no tests covering this work, say that out loud — don't let an empty or trivial run masquerade as verification.

## Step 3 — Commit the work

Stage and commit the task's changes with a message that will make sense to someone reading `git log` in six months.

- Review `git status` and `git diff` so the commit captures the right files. Be deliberate about what you stage — don't blindly `git add -A` if there are unrelated stray files (e.g. scratch files, secrets, temp artifacts). Flag anything suspicious to the user rather than committing it.
- Write a message that explains **what changed and why**, not just a restatement of the filenames. Match the style of the existing history (`git log --oneline -10`) — tense, prefix conventions, length.
- Keep it to a concise subject line; add a body only if the change needs context that the subject can't carry.
- Follow the repo's commit conventions and any commit-message trailer rules from the environment/CLAUDE.md.

Commit only — do not push unless the user asks.

## Step 4 — Report on completeness

Close with a short, honest status report so the user knows exactly where things stand:

- **What was done** — the substance of the task, briefly.
- **Verification** — test/lint result (e.g. "all 142 tests pass, ruff clean").
- **Commit** — the hash and subject line of what you committed.
- **What's missing or deferred** — anything not covered: untested paths, follow-ups, known limitations, things the user said were out of scope. If nothing is missing, say so directly rather than padding.

The value of this last step is calibration: the user should finish reading it knowing whether they can move on or whether there's a loose thread to track.
