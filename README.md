# Prompt Analyzer

An itemized receipt for an AI agent session, plus a leaner rerun that compares cost and quality.

Group project for B8609 Generative AI for Business (Columbia Business School, Fall 2026).
Track: Build It for Yourself. Team: Adit Arya, Anna Liedtke, Reid Yankowski.
Presentation: Wednesday, December 9, 2026.

**New here? Read [`docs/GAME-PLAN.md`](docs/GAME-PLAN.md) first.** It is the project plan: goal,
schedule, roles, and what is built.

## What it does

1. **Receipt.** Reads a Claude Code session log and lists every file, search, and tool call with its token cost.
2. **Diagnosis.** Names the three most expensive steps and explains why in plain words.
3. **Rematch.** Reruns the task with a leaner prompt in a clean copy of the folder, then compares cost and quality.

## Status

Week 1. Built and tested: the exact layer (parser, price table, plain-text summary) and the receipt
page with its diagnosis. Open [`docs/demo-receipt.html`](docs/demo-receipt.html) to see one (made-up data, safe for slides).
[`docs/METHOD.md`](docs/METHOD.md) explains every number on it. Next: the teammate kit, the experiment board, the lean prompt writer.

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
| `docs/METHOD.md` | How each number on the receipt is produced: exact, estimated, and known weaknesses |
| `docs/demo-receipt.html` | A receipt built from made-up data. Open it in a browser. Safe to share |
| `docs/AI-USAGE.md` | Running note of how we used AI (course policy) |
| `prompts/` | The prompts we give the coding agent, in order |
| `src/` | Parser, price table, the estimated layer, the receipt page, summary, audit (rematch runner later) |
| `tests/` | Unit tests, with synthetic fixtures under `tests/fixtures/` |
| `skill/` | The packaged skill (later) |
| `experiments/` | Task definitions and results tables |
| `samples/`, `runs/`, `reports/` | Local only. Never committed |

## Privacy

Session logs contain prompts and file contents. Everything stays on the laptop. See `AGENTS.md`.
