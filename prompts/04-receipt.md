# Prompt 4: per-step estimates and the receipt page

Start a fresh Claude Code session for this one. From the repo root, type:

    Read prompts/04-receipt.md and carry out the prompt in the code block.

It builds two things on top of the exact layer from prompt 3:

- The estimated layer: which step caused which tokens, and what it cost to keep re-sending
  them on later calls.
- The receipt page: one HTML file that opens in the browser. This is the first thing Anna
  and Reid will see, so plain words matter as much as the numbers.

It also builds a demo receipt from made-up data. That one is safe to share and to put on a
slide.

```
Read AGENTS.md, docs/GAME-PLAN.md, and docs/SCHEMA.md sections 5 and 8 to 11 first. Then
read src/parse.py, src/prices.py, and src/summarize.py. Build on them. Keep every existing
command and test working.

Goal: turn the exact layer into a receipt that a person who does not code can read in a
browser. Two teammates who do not code will use this page from Saturday on, with nobody to
ask. Plain words matter as much as the numbers.

The rule that shapes everything: the session total is exact and stays exact. Estimates only
decide how that exact total is split between steps. The split must add back up to the exact
total, and a test must prove it.

Vocabulary. Use these words in the code, the JSON, and the page.
- Step: one model call, the tool calls it made, and the results that came back.
- Chain: the main thread within one segment, or one subagent. Steps in a chain share one
  conversation.
- Item: a block of material in the conversation. The starting context, a typed prompt,
  harness text, or one step's material (its output and its results).
- Starting context: everything in a chain's first prompt except what the user typed. System
  prompt, tool definitions, project instructions, skill and connector listings.
- Output cost: what the model's own writing and thinking cost on a step. Exact.
- New cost: what an item cost the first time it was sent to the model. Estimated.
- Carried cost: what it cost to send that item again on every later call. Estimated.

PART 0. Check three things on my real logs before coding. Numbers only.
a. New-token check. For consecutive calls in a chain, compare the tokens the later call
   paid for at uncached or cache-write rates with the tokens that were new since the
   earlier call (the growth from SCHEMA section 10, plus the earlier call's output). Report
   the median ratio and the share of pairs within 20 percent.
b. Cache rebuilds. How many calls wrote far more than was new (more than twice as much, and
   at least 5,000 tokens more)? What share of total dollars are those calls? How many of
   them carry a cache_miss_reason? How long was the pause before them, at the median?
c. Can you get the character length of each prompt the user typed, separate from tool
   results and from text the harness injected, without keeping the text?
If fewer than about 70 percent of pairs in (a) are within 20 percent, stop, tell me, and
propose a simpler split. Otherwise report the numbers and keep going without waiting for me.

PART 1. src/estimate.py, the estimated layer.

1. Size of each item, in estimated tokens.
   - A step's results: the growth between that call and the next call in the chain, as in
     SCHEMA section 10. When a step made several tool calls, split the growth between them
     by result length in characters. Skip pairs with negative growth and count them.
   - A typed prompt between two calls: estimate it from its character length, and take it
     out of that gap's growth.
   - Growth with no tool result and no typed prompt behind it is "harness text".
   - Starting context: the first prompt's size minus the estimated first typed prompt.
   - After a compact_boundary, the new segment's first prompt is one item named "Summary of
     the earlier conversation". Nothing from before the boundary is carried past it.

2. Splitting each call's input bill. The dollars are exact. The split is estimated.
   - Re-sent pool: the call's cache-read dollars. Split them across the items that were
     already in the conversation at the previous call, in proportion to tokens. That is
     carried cost.
   - New pool: the call's uncached-input and cache-write dollars. They go to the items that
     are new since the previous call (the previous step's material, a typed prompt, harness
     text), in proportion to tokens. That is new cost.
   - Cache rebuild: when a call wrote far more than was new (the test from PART 0 b),
     charge the new items at that call's write rate, split the rest across the older items
     in proportion to tokens as carried cost, and flag the step "cache rebuilt". Keep the
     cache_miss_reason when the log has one, and the minutes since the previous call.
   - First call of a chain: its whole input bill goes to the starting context and the first
     typed prompt, in proportion to tokens.
   - A step's own output dollars are exact and stay with that step. Show thinking
     separately. Its token count is exact.
   - Use running sums. A session with thousands of calls should build in a few seconds.

3. Subagents and workflows. Treat each subagent as its own chain. In the main receipt, roll
   a subagent's exact total into the Agent or Workflow step that launched it, shown as
   "subagent work". If the log does not link a subagent to a step, list it under "Subagents
   not linked to a step".

4. The sum-back rule. New cost and carried cost over all items, plus output cost over all
   steps, plus subagent work, must equal the transcript total from src/summarize.py to
   within $0.000001. Assert it on every build. If it fails, the receipt does not render and
   the error says so.

5. Kinds. Every tool call gets one kind: read file, search, run command, write or edit
   file, web, subagent, other tool. A step with no tool call is an answer. Roll costs up
   into these lines: Starting context, Your prompts, Thinking, Answers, Reading files,
   Searching, Running commands, Writing and editing files, Web, Subagents, Other tools,
   Harness text. When a step mixes kinds, split its costs by result length. Keep the rule
   simple and write it down.

6. Bash commands. Searches and file reads mostly hide inside Bash (SCHEMA section 7).
   - Split a command at &&, ||, ;, and |. Take the command word of each part with the
     existing bash_first_word rule.
   - Keep one table in the code that maps command words to kinds. For example: grep, rg,
     find, and ls are search. cat, head, tail, sed, and wc are read file. python, node,
     npm, pytest, and make are run command. curl and wget are web. Words such as cd and
     export decide nothing.
   - Pick one simple rule for a command whose parts disagree, and write it down.
   - For read-type parts, also keep the arguments that look like file paths, so the files
     table can count them. Keep nothing from a heredoc body, an inline script, or a quoted
     string. When unsure, keep nothing.
   - Report what share of my real Bash calls end up as "other command". Aim under 10 percent.

7. Files table. Per file: times read (Read tool plus Bash reads), times written or edited,
   estimated tokens brought in, estimated new and carried cost. Flag files read more than
   once.

8. Diagnosis. Rules only. No model call.
   - The three most expensive steps by total cost. Each gets one plain sentence that says
     why, built from fixed templates with the step's own numbers. Cover at least: a large
     result that was carried through N later calls, a cache rebuild after a pause of N
     minutes, a long piece of writing, heavy thinking, and a subagent that made N calls.
   - Up to four session findings, when they apply: the starting context's share of the
     total, the share of dollars that went to re-sending earlier material, a file read N
     times, and a compaction.
   - Each finding has an id, its numbers, and its sentence. State what happened. Give no
     advice. Advice comes in a later prompt, which will read these findings.

PART 2. src/receipt.py and the page.

Command line:
  python3 -m src.receipt --session <path, id, "latest", or a folder> [--out <path>]
                         [--json [path]] [--no-open]
  python3 -m src.receipt --demo
- Writes reports/<session-id>.receipt.html and opens it in the default browser with the
  webbrowser module. --no-open skips the browser.
- Prints three plain lines: where the file is, the total, and the most expensive step.
- A folder argument means the latest session whose working directory was that folder.
  Experiment runs will live in their own folders outside this repo.
- --json writes the estimated layer to reports/<session-id>.receipt.json.

The page, top to bottom:
1. Title: project folder base name, date, how long the session ran, model. One sentence:
   how many model calls and tool calls, and the total at public API prices. Say once, near
   the top, that dollars are API-equivalent and that a subscription bills differently.
2. Four tiles: total dollars, model calls, largest prompt in tokens, and the share of
   dollars spent re-sending earlier material.
3. "Where the money went": one stacked horizontal bar by kind, with a legend that gives
   dollars and percent.
4. "The three most expensive steps": three cards. Step number, what it did in plain words,
   its cost split, and the why sentence.
5. "How the conversation grew": one bar per model call, in order. Height is prompt size,
   split into re-sent and new. Mark compactions and cache rebuilds. These numbers are exact.
6. "Every step": one row per step, in order. What happened in plain words ("Read
   parse.py", "Ran grep and sed", "Wrote receipt.py", "Answered"), a bar split into output,
   new, and carried cost, and the total. Sort by order or by cost. Filter by kind. Click a
   row for detail: exact tokens by type, estimated new tokens, how many later calls re-sent
   them, and any flags.
7. "Files": the files table.
8. "Other findings": the session findings.
9. Fine print, collapsed by default: how to read the page, what is exact and what is
   estimated, the price rows used and the date checked, any model without a validated
   price, and the session total recorded by Claude Code next to the transcript total when
   it exists. If that gap is above 2 percent, say so under the headline total as well.

Page rules:
- One self-contained HTML file. Inline CSS, inline SVG, and a little inline JavaScript for
  sort, filter, and expand. No external fonts, scripts, or images. It must work offline by
  double-click in Chrome, Safari, and Edge.
- The headline total is the transcript total, because that is what the steps add up to.
- Every number carries a word: "exact" or "est.". Never color alone.
- Plain words on the page. "Re-sent" for cache reads. "New" for cache writes and uncached
  input. Raw field names appear only in the expanded detail and the fine print.
- One color per kind, the same in the bar, the cards, and the rows. Safe for color-blind
  readers. Light background. Large type on the totals, so a screenshot works on a slide.
- Stay usable at 1,000 steps. Show the 50 most expensive rows first, with a "show all".
- HTML-escape every string that came from a log. Show file base names in rows and the path
  relative to the project folder in the detail. Replace the home folder with ~.
- No prompt text, no file contents, no tool output. Same rule as the JSON.

PART 3. A demo receipt from made-up data.
- Add a generator (for example tests/make_demo_session.py) that writes a synthetic session
  to a temporary folder. Fixed seed. Invented file names and invented content. About 40
  model calls: a large file read early, the same file read three times, searches, a test
  run, edits, a long write, one subagent, and one cache rebuild after a pause.
- python3 -m src.receipt --demo builds docs/demo-receipt.html from it and opens it. Commit
  that file. It is the page teammates open first, and the one that is safe for slides.

PART 4. Tests, with unittest.
- Sum-back on every fixture and on the demo session.
- No negative token estimate and no negative cost.
- Privacy: put marker strings in the fixtures' prompt text, tool output, file contents,
  heredoc bodies, and inline scripts. Assert that no marker appears in the HTML or the JSON.
- The Bash table: pipes, &&, env prefixes, heredocs, inline scripts, a lowercase tool name.
- The receipt builds for: one call and no tools, parallel tool calls, a subagent, a
  compacted session, and a live session with no cost-state record.
- The HTML parses with html.parser and has no src or href that points off the page.

Do not build yet: plain-English commands or skills, the setup check, the run starter, the
experiment board, the lean prompt writer, redaction, or anything for Codex. Those are
prompts 5 to 7.

If an edge case in my real logs is eating time, handle the common case, say what is not
handled in the fine print and in your report, and move on. The page matters more than the
last 2 percent of the split.

When you finish:
- Run all tests.
- Build the receipt for this repo's latest finished session, and the demo.
- Build across all my sessions once, in memory, without writing files. Report how many
  built, the largest sum-back difference, the share of Bash calls left as "other command",
  and the build time for my largest session.
- Write docs/METHOD.md: one page, plain words. How each number on the receipt is produced,
  what is exact, what is estimated, and the known weaknesses. The team will present from it.
- Update README.md (Status, Run it, Layout), the prompt 4 lines in docs/GAME-PLAN.md, and
  add one line to docs/AI-USAGE.md.
- Tell me: the PART 0 numbers, the total and the split by kind for the latest session, the
  three most expensive steps with their why sentences (file base names only), what you
  skipped, and open questions.
- Commit. Ask before pushing.
```

## What to bring back to the planning chat

- Claude Code's final report, pasted whole.
- A screenshot of the receipt page. The demo receipt is fine, since it has no real data.

## What comes next

- Prompt 5, the teammate kit: a setup check, plain-English commands, and a run starter.
- Prompt 6, the experiment board and the task sheets.
- Prompt 7, the lean prompt writer, which reads the findings from this prompt.
