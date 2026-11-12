# Prompt Analyzer

An itemized receipt for an AI agent session, plus a leaner rerun that compares cost and quality.

Group project for B8609 Generative AI for Business (Columbia Business School, Fall 2026).
Track: Build It for Yourself. Team: Adit Arya, Anna Liedtke, Reid Yankowski.
Presentation: Wednesday, December 9, 2026.

**Running the experiment (Anna, Reid)? Read [`docs/START-HERE.md`](docs/START-HERE.md).** One page, plain words.

**New here? Read [`docs/GAME-PLAN.md`](docs/GAME-PLAN.md) first.** It is the project plan: goal,
schedule, roles, and what is built.

## What it does

1. **Receipt.** Reads a Claude Code session log and lists every file, search, and tool call with its token cost.
2. **Diagnosis.** Names the three most expensive steps and explains why in plain words.
3. **Rematch.** Reruns the task with a leaner prompt in a clean copy of the folder, then compares cost and quality.

## Status

Week 1. Built and tested: the exact layer (parser, price table, plain-text summary) and the receipt
page with its diagnosis, redesigned to the standard in [`docs/DESIGN.md`](docs/DESIGN.md) (three layers, Apache ECharts charts, one colour per meaning). Open [`docs/demo-receipt.html`](docs/demo-receipt.html) to see one (made-up data, safe for slides).
[`docs/METHOD.md`](docs/METHOD.md) explains every number on it. Also built: the teammate kit (`src/kit.py`): a setup check, a run starter and finisher,
eight plain-English skills under `.claude/skills/`, and one practice task, so Anna and Reid can run the experiment by typing sentences in the
Claude Code panel. Runs happen outside the repo, in `prompt-analyzer-scratch` in the home folder; their results (numbers, receipts, and what the agent made) are copied into `results/`, which is committed and shared with `share`. Next: the experiment board, the lean prompt writer.

## Run it

From the repo root. Python 3 only, nothing to install.

```
python3 -m src.receipt --session latest        # the receipt page for your latest session here (opens in the browser)
python3 -m src.receipt --demo                  # the demo receipt from made-up data (docs/demo-receipt.html)
python3 -m src.summarize --session latest      # plain-text summary of the same session
python3 -m src.audit all                       # gap and price check across all your sessions
python3 -m src.audit receipts                  # build every receipt in memory (no files) and report how it went
python3 -m unittest                            # run the tests
```

The teammate kit (teammates type sentences instead; see `docs/START-HERE.md`). Use `python` or `py` if `python3` is not the name on your machine:

```
python3 -m src.kit check                                # is this laptop ready? one line per item
python3 -m src.kit start <task> <original|lean> [--run N] [--who NAME]   # fresh run folder, prompt on the clipboard, new VS Code window
python3 -m src.kit finish [<run folder name>]           # receipt, what the agent made, one row in results/<who>.csv (with model and effort), a flag if the run needs a second look
python3 -m src.kit receipt [latest | <run folder name>] [--export]  # open a run's receipt; --export makes a standalone copy to share outside the repo
python3 -m src.kit prompt [latest | <run folder name>]  # put a run's prompt back on the clipboard and print it
python3 -m src.kit runs                                 # table of runs so far, merged from every results/<who>.csv
python3 -m src.kit share                                # commit results/ only, pull --rebase, push; stops if anything else changed
python3 -m src.kit update                               # git pull --ff-only, and stops if you changed anything
```

Settings live in `local-settings.json` in the repo root (gitignored): `scratch_folder` (default `~/prompt-analyzer-scratch`) and `who`.

`results/` is committed: `<who>.csv`, `receipts/<run>.receipt.html`, `outputs/<run>/` (files the run created or changed, nothing over 5 MB), and `run-details/<run>.json`. A run is named `<task>-<version>-<n>-<who>`, for example `sample-lean-1-anna`. A receipt there links `../../vendor/echarts.min.js` (about 50 KB); `receipt --export` makes a self-contained copy. Made-up task inputs only, never session logs.

`--session` takes a path, a session id, `latest`, or a folder (the latest session that ran in it). Add `--no-open`
to skip the browser, `--out <path>` to choose the file, and `--json` to also write the numbers. Files go to `reports/`,
which is never committed. A live session usually has no session total yet (Claude Code writes it later), so the
receipt shows the transcript total only and says so.

## Layout

| Path | What lives there |
|---|---|
| `AGENTS.md` | Rules every coding agent follows in this repo |
| `CLAUDE.md` | Points Claude Code at `AGENTS.md` |
| `docs/GAME-PLAN.md` | The project plan: goal, schedule, roles. Read first |
| `docs/PLAN.md` | Timeline, experiment design, risks, open questions |
| `docs/SCHEMA.md` | How Claude Code session logs are structured |
| `vendor/` | Apache ECharts 6.1.0, the one approved dependency, with its version, source, SHA-256, and license. Inlined into pages; receipts in `results/receipts/` link it |
| `docs/METHOD.md` | How each number on the receipt is produced: exact, estimated, and known weaknesses |
| `docs/demo-receipt.html` | A receipt built from made-up data. Open it in a browser. Safe to share |
| `docs/AI-USAGE.md` | Running note of how we used AI (course policy) |
| `prompts/` | The prompts we give the coding agent, in order |
| `src/` | Parser, price table, the estimated layer, the receipt page and its shared parts `page.py`, summary, audit, the teammate kit `kit.py` (rematch runner later) |
| `tests/` | Unit tests, with synthetic fixtures under `tests/fixtures/` |
| `skill/` | The packaged skill (later) |
| `experiments/tasks/<task>/` | One task: `task.md`, `start/` (made-up starting files), `prompt-original.md`, `prompt-lean.md`. `sample` is a practice task |
| `.claude/` | Project skills (one per plain-English action) and `settings.json`, which allows only the kit commands and the four git commands that `share` uses |
| `results/` | Committed. Experiment runs on made-up inputs: `<who>.csv`, `receipts/`, `outputs/<run>/`, `run-details/`. Never session logs |
| `docs/START-HERE.md` | One page for Anna and Reid: setup, every run, what to type |
| `samples/`, `runs/`, `reports/` | Local only. Never committed |

## Privacy

Session logs contain prompts and file contents. Everything stays on the laptop. See `AGENTS.md`.
