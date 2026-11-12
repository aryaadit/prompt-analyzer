# How the receipt works

One page, in plain words. Every number on the receipt page is produced as described here.
Code: `src/parse.py` (read the log), `src/prices.py` (dollars), `src/estimate.py` (the split),
`src/diagnose.py` (the sentences), `src/receipt.py` (the page).

## The one rule

**The session total is exact and stays exact.** The log records tokens for every call to the model. We
multiply them by public API prices. That is the total on the page. Estimates only decide how that exact
total is **split between steps**. The split always adds back up to the total, and the program checks this
on every build. If it does not add up (more than one millionth of a dollar off), no page is built.

Dollars are **API-equivalent**: tokens times public prices. On a subscription nobody is billed this amount.

## What is exact

- Tokens of every model call, split into uncached input, cache read, cache write (5 minute and 1 hour),
  and output. Thinking tokens are part of output and are recorded separately.
- The total, each call's cost, and each step's **output cost** (what the model's own writing and thinking
  cost). Thinking cost is exact too.
- The size of every tool result in characters, and the call counts.
- How big the prompt was on every call (the bars in "How the conversation grew").

## What is estimated, and how

The log does not record tokens per file or per tool, so these are estimates. The page says "est." next to them.

1. **How big each item was.** Each call sends the whole conversation again. The prompt of call *n+1* minus the
   prompt of call *n* is what was added in between: the model's last output, the tool results, anything you typed, and
   small harness text. Take out the exact output, and what is left is the size of the results. When a step ran
   several tools, the growth is split by result length. A typed prompt is sized from its length in characters
   (2.6 characters per token, measured on real logs) and taken out of the growth. Growth that no result or typed prompt
   explains is "harness text".
2. **Who pays for each call's input.** A call's input bill has two parts. *Re-sent* (cache read) is the old material,
   split across everything already in the conversation in proportion to size: that is **carried cost**.
   *New* (uncached input and cache writes) goes to what was added since the last call: that is **new cost**. The first call
   of a conversation charges everything to the starting context and your first prompt.
3. **Cache rebuilds.** If a call paid for more than twice the new tokens, and at least 5,000 more, the saved copy of the
   conversation had expired (usually after a pause). Only the new material is charged at the write price; the rest is charged
   to the older items as carried cost. The step is flagged with the pause and the reason the log gives.
4. **A step's cost** is its output cost plus the new and carried cost of what its results added. A big result read early is paid
   for again on every later call, so it becomes expensive. That is the "carried cost" the page keeps pointing at.
5. **Subagents** are separate conversations. Their exact total is added to the step that launched it ("subagent work"). The page
   does not break a subagent down. Subagents that no step launched are listed in the fine print.
6. **Compaction.** After a compaction the new segment starts from a summary. Nothing before it is carried past it.
7. **The twelve lines** in "Where the money went" roll the costs up by kind of work. A step that did several kinds of work is split
   by result length. Searches and file reads hidden inside shell commands are found by one table of command words
   (`src/bash.py`): the first command that decides wins, `cd` and `export` decide nothing, a redirect into a file is a write.
8. **The diagnosis** is rules and fixed sentences. No model is called. It states what happened and gives no advice.

## Checks we ran on real logs (numbers only)

- New material versus what the next call paid for at uncached or write prices: median ratio 1.001, and 99.2% of 42,768
  consecutive pairs within 20%. That is why growth is a good yardstick.
- Cache rebuilds: 246 calls (0.6% of pairs) but 16.4% of all dollars. The median pause before them was 18 minutes.
- Shell commands: 0.6% of 39,888 could not be classified.
- All 84 sessions on one laptop: 82 build (the other 2 hold no model calls); largest sum-back difference $3.4e-13.

## Known weaknesses

- Per-file and per-step costs are estimates. They are good at the level of "this file cost about $0.30", not to the cent.
- Result size comes from growth. It includes wrapper text, so it is an upper bound. If thinking is dropped from a later prompt,
  growth can be smaller than the previous output; those pairs are counted and flagged (15 of 42,770 on our logs).
- Claude Code's own session total is sometimes higher than the transcript (about 0.5% in ordinary sessions, about 10% in
  compacted ones). The page shows the transcript total and says when the gap is above 2%.
- Cost-state records only the combined cache-write count reliably, so the gap is shown as a range.
- Subagent internals, and files read by subagents, are not itemized. Codex and Copilot logs are not read.
- Prices come from the public page, checked on one date. Some model rows are not yet checked against a session total.

## Words

**Step**: one model call, its tool calls, and their results. **Chain**: the main thread within one segment, or one subagent.
**Item**: a block of material in the conversation. **Starting context**: everything in the first prompt except what you typed.
**Output cost**, **new cost**, **carried cost**: as above.
