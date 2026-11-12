# Agent rules for this repo

**Start here:** read `docs/GAME-PLAN.md` first. It is the project plan (goal, schedule, roles,
what is built and what is next). Then read the rest of this file.

## What this project is

Prompt Analyzer reads the session logs that coding agents write to disk and turns them into
(1) an itemized cost receipt, (2) a plain-language diagnosis, and (3) a rematch that reruns
the task with a leaner prompt and compares cost and quality. Read `docs/PLAN.md` before
starting any task.

## Never

- Never copy prompt text, file contents, or tool output from a session log into this repo,
  a commit message, or a doc. Structure, field names, counts, and token numbers only.
- Never commit anything under `samples/`, `runs/`, or `reports/`.
- Never send log content to a network service.
- Never modify or delete anything under `~/.claude` or any other agent's log folder. Read only.

## Ask me first

- Before any `git push` or any change on GitHub.
- Before installing a dependency.
- Before deleting or overwriting a file you did not create in this session.
- Before running a rematch or anything else that spends model usage.

## Style

- Python 3, standard library only, unless I approve a dependency.
- Every page follows `docs/DESIGN.md`. Read it before building or changing any page.
- Pages are one self-contained HTML file. No build step and no network requests. The only
  approved script is Apache ECharts from `vendor/`, inlined into the page.
- Label every cost number as **exact** (read from the log) or **estimated**.
- Label every dollar figure as **API-equivalent**. Keep prices in one table with the date checked.
- Small functions, plain names, a short docstring on each. Tests for the parser.

## When you finish a task

- Tell me what you changed, what you skipped, and any open questions.
- Add one line to `docs/AI-USAGE.md` describing what the agent did in this session.
