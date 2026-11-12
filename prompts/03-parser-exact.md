# Prompt 3: parser and the exact layer

Start a fresh Claude Code session for this one. Paste the block below from the repo root.

It builds the part of the receipt that is exact: tokens and dollars per model call, read
straight from the log. No estimates and no HTML yet. Those are prompt 4.

```
Read AGENTS.md, docs/PLAN.md, and docs/SCHEMA.md first.

Goal: build the exact layer of the receipt. No estimates and no HTML yet.

Before you write any code, answer two questions from my real logs. Numbers only.
  a. Of the 76 unreconciled (session, model) entries in SCHEMA.md section 5, how many are
     models with no assistant record in the transcript? What share of total cost-state
     dollars do the 76 entries represent?
  b. In the 10 sessions with more than one cost-state record, is the last record cumulative?
If the answers change the design below, stop and tell me before coding.

Then build this in src/, Python standard library only.

1. parse.py
   - Stream one top-level session file line by line, plus every file under its
     <sessionId>/subagents/ folder, workflows included.
   - Produce one record per model call, keyed by message.id, with usage counted once.
     Follow every trap in SCHEMA.md section 11.
   - For each call keep: order, timestamp, model, the token counts (uncached input, cache
     read, 5-minute cache write, 1-hour cache write, output), thinking tokens, stop reason,
     cache miss reason if present, whether it came from the main session or a subagent (and
     which agentId), and the tool calls it made (tool name, tool_use id).
   - Join each tool call to its result by tool_use_id. Keep the result's size in characters
     and its is_error flag. Never keep the result content.
   - For each tool call keep a target: file_path for Read, Edit, and Write. url for WebFetch.
     query for WebSearch. Skill name for Skill. Subagent type for Agent. For Bash keep only
     the first word of the command for now.
   - Split the session into segments at compact_boundary records.

2. prices.py
   - One price table: per model, dollars per million tokens for uncached input, cache read,
     5-minute cache write, 1-hour cache write, and output. Look the prices up on Anthropic's
     public pricing page. Record the URL and the date checked in the file. Ask me before
     assuming a price for any model id you cannot find there.
   - Validate the table. For sessions where the transcript reconciles exactly with
     cost-state, our computed dollars should match cost-state costUSD. Report the match rate
     and the largest difference.

3. summarize.py, with this command line:
     python3 -m src.summarize --session <path, id, or "latest"> [--json <path>]
   - "latest" means the most recent top-level session for the current working directory.
   - Print a plain-text summary: number of calls, tokens by type, API-equivalent dollars,
     split by model and by main session versus subagents. Then the top 10 calls by cost,
     and tool call counts by tool.
   - Print a reconciliation block: transcript total versus the last cost-state total, per
     model, and the gap. Label the gap "calls not in the transcript".
   - With --json, write the full normalized structure. Default location is reports/. The
     JSON must contain no prompt text, no file contents, and no tool output.

4. tests/
   - Hand-written synthetic .jsonl fixtures with invented content, never copied from real
     logs. Cover: a multi-block response (usage counted once), parallel tool calls, a
     subagent file, a <synthetic> record, missing optional fields, a lowercase tool name,
     and a compact_boundary. Use unittest.
   - Put fixtures under tests/fixtures/ and add a .gitignore exception so *.jsonl is allowed
     only there.

Do not build yet: per-tool token estimates, Bash command classification, the HTML receipt,
or anything for Codex or Copilot.

When you finish:
- Run the tests.
- Run the summary on this repo's own latest session and show me the output, with file paths
  shortened to their base names.
- Update the open questions in docs/PLAN.md to match what SCHEMA.md settled.
- Commit, and ask before pushing.
```

## What prompt 4 will add (not yet written)

- Estimated tokens per tool result, using the growth method from SCHEMA.md section 10.
- Carried cost: how many later calls re-read each result, and what that cost.
- A rule that recognizes searches and file reads hidden inside Bash commands.
- The one-page HTML receipt, with every number labeled exact or estimated.
