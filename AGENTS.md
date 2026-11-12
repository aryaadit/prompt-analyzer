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
- Never commit anything under `samples/`, `runs/`, or `reports/`. They stay local.
- Never send log content to a network service.
- Never modify or delete anything under `~/.claude` or any other agent's log folder. Read only.

## results/ is committed

`results/` holds the experiment runs: `<who>.csv` (one file per person), `receipts/`, `outputs/<run>/`
(what the agent made), and `run-details/`. A run is named `<task>-<version>-<n>-<who>`, for example
`sample-lean-1-anna`. It holds runs on made-up inputs only, numbers and outputs,
never session logs and never anything from a real project. The kit fills it (`finish`) and sends it
(`share`). The run working folder, `prompt-analyzer-scratch` in the home folder, stays OUTSIDE the repo,
because Claude Code loads instruction files from parent folders and a run inside the repo would load
these rules and inflate its cost.

## Ask me first

- Before any `git push` or any change on GitHub. Coding agents always ask before a push. The only thing that
  pushes without asking is the kit's `share` command ("share my results"), and it pushes `results/` only.
- Before installing a dependency.
- Before deleting or overwriting a file you did not create in this session.
- Before running a rematch or anything else that spends model usage.

## Style

- Python 3, standard library only, unless I approve a dependency.
- Every page follows `docs/DESIGN.md`. Read it before building or changing any page.
- Pages are one HTML file. No build step and no network requests. The only approved script is Apache
  ECharts from `vendor/`. It is inlined into the page, except in receipts saved to `results/receipts/`,
  which load `../../vendor/echarts.min.js` so that a committed receipt stays small. `python3 -m src.kit
  receipt <run> --export` makes a self-contained copy for sharing outside the repo. `docs/demo-receipt.html`
  stays inlined.
- Rebuild `docs/demo-receipt.html` only when the page design changes, not on every commit.
- Label every cost number as **exact** (read from the log) or **estimated**.
- Label every dollar figure as **API-equivalent**. Keep prices in one table with the date checked.
- Small functions, plain names, a short docstring on each. Tests for the parser.

## When you finish a task

- Tell me what you changed, what you skipped, and any open questions.
- Add one line to `docs/AI-USAGE.md` describing what the agent did in this session.
