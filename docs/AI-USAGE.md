# How we used AI

Course policy: when we use GenAI tools on an assignment, we must describe how we used them.
Add one line per work session.

| Date | Who | Tool | What it did |
|---|---|---|---|
| 2026-11-10 | Adit | Claude | Brainstormed project ideas, compared tracks, drafted the group vote message |
| 2026-11-12 | Adit | Claude | Wrote the project plan and scaffolded this repo (README, AGENTS.md, prompts) |
| 2026-11-12 | Adit | Claude Code | Checked git and gh, initialized the repo, verified no sample, run, or report files were staged, and made the first commit |
| 2026-11-12 | Adit | Claude Code | Inspected the structure of local Claude Code session logs with throwaway scripts (keys, types, counts only) and wrote docs/SCHEMA.md; no log content was copied |
| 2026-11-12 | Adit | Claude Code | Built the exact layer: parser, price table, summary command, and synthetic-fixture tests (src/, tests/). Measured the transcript-versus-session-total gap and validated prices against cost-state on local logs (numbers only); looked up public prices through a web-fetch subagent; no log content was copied or sent anywhere |
| 2026-11-12 | Adit | Claude Code | Pushed the exact-layer commit after approval; committed the planning-chat files (GAME-PLAN, prompt 3); updated SCHEMA open questions 1 and 2 with the measured answers; checked which models the 71 validated price entries cover; added a "Run it" section to the README and a start-here pointer to AGENTS.md |
| 2026-11-12 | Adit | Claude Code | Pushed the second commit after approval; added a validated flag per model in the price table, an audit report of which flags to change, and a summary note for models not yet checked against a session total |
| 2026-11-12 | Adit | Claude Code | Built the estimated layer, the diagnosis rules, the receipt page, and a demo receipt from made-up data (src/estimate.py, diagnose.py, bash.py, receipt.py, tests); checked the method on local logs (numbers only) and looked at the pages in a headless browser; wrote docs/METHOD.md; no log content was copied or sent anywhere |
| 2026-11-12 | Adit | Claude Code | Pushed the prompt 4 commit after approval; applied the demo-page review: number formats, print and PDF styles (checked by exporting to PDF in a headless browser), merged top cards, a cache-rebuild finding with extra dollars, a headline sentence, a taller growth chart, and a total row with a match check; added tests and updated docs/METHOD.md; numbers only from local logs, no log content copied |
| 2026-11-12 | Adit | Claude Code | Built the teammate kit: src/kit.py (setup check, run starter and finisher, receipt, run list, update), Windows-safe session lookup, six project skills and a permissions file under .claude/, a practice task, docs/START-HERE.md, and tests; looked up the current Claude Code skill and permission syntax through a docs subagent; no log content was copied or sent anywhere |
