# Plan

Last updated: November 12, 2026.

## The rule

The receipt is table stakes. Free tools already draw it (claude-devtools, Claude Session
Visualizer, Token Dashboard). The rematch is the project. Give the receipt one week and
spend the rest on the part nobody has.

## Parts

| Part | What it does | Done means |
|---|---|---|
| 1. Receipt | Reads a Claude Code session log and lists every file, search, and tool call with its token cost | Works on any teammate's session with one command |
| 2. Diagnosis | Names the three most expensive steps and says why in plain words | A non-engineer understands it without help |
| 3. Rematch | Reruns the task with a leaner prompt in a clean copy of the folder, then compares cost and quality | Five tasks tested, with a results table |

Packaging: a skill with scripts, and the receipt as one local HTML page. An in-chat app
screen is a stretch goal. Only start it if the evidence is in by December 2.

## Timeline

| Dates | Goal | Checkpoint |
|---|---|---|
| Nov 12 to 18 | Receipt works on one real session | Session 4 (Nov 18): confirm the logs hold what we need |
| Nov 19 to 25 | Rematch runner works. Lock the five test tasks | One full original-versus-lean comparison, end to end |
| Nov 26 to Dec 2 | Run the experiments. Package the skill | Session 5 (Dec 2): collect blind votes from classmates |
| Dec 3 to 9 | Freeze features Dec 4. Video by Dec 6. Deck by Dec 7 | Present Dec 9 |

## Experiment (this is the critical assessment)

- **Tasks:** five. Start with the two in-class builds (Job Hunt in a Folder, the personal
  site), since every classmate ran them. Add three of our own.
- **Runs:** three per version. The same prompt costs a different amount each time.
- **Cost:** exact token totals from the logs, plus dollars at public API prices.
- **Quality:** blind vote. Classmates pick output A or B without knowing which is which.
- **Honesty:** if the lean prompt loses on quality, we report it. That is a finding.

## Known traps

- **Per-step costs are estimates.** We expect the log to record exact tokens per model call,
  not per file. `prompts/02-inspect-logs.md` checks this. Mark each number exact or estimated.
- **Dollar figures are notional.** On a subscription there is no per-prompt bill. Label them
  API-equivalent.
- **Reruns change files.** Every rematch needs a fresh copy of the folder.
- **Logs are private.** They hold prompts and file contents. Keep them local. Redact for the demo.
- **No compute or energy numbers.** They are not observable, so any figure would be a guess.

## Deliverable (from the Session 2 slides)

- 1 to 3 slides: problem statement
- One demo video we record ourselves, 2 to 3 minutes
- 1 to 3 slides: critical assessment. What problem it solves, how we know it works, what
  broke, what we would change

## Roles (proposed, not agreed)

| Person | Owns |
|---|---|
| Adit | Parser, rematch runner, repo |
| Reid | Cost method, plus the comparison against existing tools such as LangSmith |
| Anna | The experiment (tasks, blind votes), the deck, and the video script |

## Settled (from docs/SCHEMA.md and the exact layer, Nov 12)

- **Granularity:** the log records tokens per model call only, nothing finer. Per-tool and
  per-file costs will be estimates and must be labeled so.
- **Usage counting:** count once per `message.id`. Subagent and workflow files hold their own
  usage and must be read too.
- **Session totals:** `cost-state` is cumulative, so the last record is the session total.
- **Price check:** summed per call with the 5-minute and 1-hour cache-write split, our price
  table reproduces `costUSD` on 71 of 71 exactly reconciling (session, model) entries, to
  rounding error. Speed, service tier, long-context tier, and web search fees changed nothing.
  The 5m/1h split is what matters. `cost-state`'s own split fields are incomplete, so only its
  combined cache-write count is reliable.
- **The gap:** session totals exceed the transcript. It is not mostly helper models (those are
  41 of 148 entries and about $1). On one yardstick it is 8.0 to 8.3 percent of all session-total
  dollars: 9.7 to 10.2 percent in sessions with a compaction, 0.5 to 0.6 percent in sessions
  without. The range comes from pricing every cache write at the 5-minute or the 1-hour rate.

## Open questions

- Which agent do Anna and Reid use in class: Claude Code, Codex, or Copilot? Codex and Copilot
  log formats are unknown, so this decides whether the parser needs a second format.
- What is in the gap? It tracks compaction, but the cause is unconfirmed. A compaction
  summary call that writes no `assistant` record is the leading guess.
- Does top-level `usage` include `fallback_message` iterations? Only 4 cases. (SCHEMA open
  question 3.)
- Can `api-request` tail hashes be resolved to give exact per-message sizes? (SCHEMA open
  question 4.) This would replace the growth-method estimates for tool results.
- The price page shows display names, not API ids, and no "last updated" date. We map log ids
  to names by convention (`claude-fable-5-1` is "Claude Fable 5.1"). Recheck the page before
  the experiments on Nov 26.
- Presentation length. The Session 2 slides say 5 minutes in a 7-minute slot. The syllabus
  says 7 minutes plus Q&A. Confirm with the professors.
- We switched project type to Build It for Yourself after Session 2. Mention it to the professors.
