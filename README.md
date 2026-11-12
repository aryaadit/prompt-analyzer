# Prompt Analyzer

An itemized receipt for an AI agent session, plus a leaner rerun that compares cost and quality.

Group project for B8609 Generative AI for Business (Columbia Business School, Fall 2026).
Track: Build It for Yourself. Team: Adit Arya, Anna Liedtke, Reid Yankowski.
Presentation: Wednesday, December 9, 2026.

## What it does

1. **Receipt.** Reads a Claude Code session log and lists every file, search, and tool call with its token cost.
2. **Diagnosis.** Names the three most expensive steps and explains why in plain words.
3. **Rematch.** Reruns the task with a leaner prompt in a clean copy of the folder, then compares cost and quality.

## Status

Week 1. Nothing is built yet. Start with `prompts/01-git-setup.md`, then `prompts/02-inspect-logs.md`.

## Layout

| Path | What lives there |
|---|---|
| `AGENTS.md` | Rules every coding agent follows in this repo |
| `CLAUDE.md` | Points Claude Code at `AGENTS.md` |
| `docs/PLAN.md` | Timeline, experiment design, risks, roles |
| `docs/AI-USAGE.md` | Running note of how we used AI (course policy) |
| `prompts/` | The prompts we give the coding agent, in order |
| `src/` | Parser, receipt builder, rematch runner |
| `skill/` | The packaged skill (later) |
| `experiments/` | Task definitions and results tables |
| `samples/`, `runs/`, `reports/` | Local only. Never committed |

## Privacy

Session logs contain prompts and file contents. Everything stays on the laptop. See `AGENTS.md`.
