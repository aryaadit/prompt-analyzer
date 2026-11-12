# How the receipt works

One page, in plain words. Every number on the receipt page is produced as described here.
Code: `src/parse.py` (read the log), `src/prices.py` (dollars), `src/estimate.py` (the split),
`src/diagnose.py` (the sentences), `src/receipt.py` (the page), `src/page.py` (parts every page shares: colours,
formats, badges, hover text, collapsible sections, CSV, print styles, the chart library).

## The one rule

**The session total is exact and stays exact.** The log records tokens for every call to the model. We
multiply them by public API prices. That is the total on the page. Estimates only decide how that exact
total is **split between steps**. The split always adds back up to the total, and the program checks this
on every build. If it does not add up (more than one millionth of a dollar off), no page is built.

Dollars are **API-equivalent**: tokens times public prices. On a subscription nobody is billed this amount.

## How the page is laid out

The page follows docs/DESIGN.md, in three layers. Nothing was dropped when the page was redesigned: detail moved down a layer.

1. **The answer**, above the fold at 1280 by 800: the title line, the headline sentence (the single largest cause), four tiles
   (total, model calls, share re-sent, extra dollars from cache rebuilds), and one chart of where the money went with its legend
   table, its total row, and the check against the total at the top. A fifth tile, "Cost of the task itself" (the total minus the
   starting context), appears only when the starting context is more than half of the total. Then the headline says: "Most of this
   cost was fixed overhead: Claude Code's starting context, sent before any work. The task itself cost $X."
   The same rule gives the "Largest cause" line that `kit finish` prints.
2. **The explanation**: the top three cards, a bar chart of how the prompt grew (one bar per call, with a tooltip of exact tokens
   by type), and a line of the running total in dollars with the top steps marked on it.
3. **The evidence**, in sections that open and close: every step (search, sort, filter, top 50 then show all), the files, other
   findings, how to read the page with a glossary, and the fine print. Every table has a CSV button. Print and PDF expand them.

One colour per meaning, set once in `src/page.py`: 13 hues and 2 greys, picked so every pair stays at least 15 apart (CIE Lab) under
normal vision and protan, deutan, and tritan simulation. Blue is re-sent, red-orange is new, indigo is output, ochre is subagent
work, and the twelve kinds of work keep their own colours. Colour is never the only cue. A true zero is "$0.00" and nothing else is:
anything under a cent reads "<$0.01" (or "<$0.0001" in the four-decimal tables). The chart library is Apache ECharts, inlined (or, in a receipt kept in results/receipts/, linked) from
`vendor/echarts.min.js` and checked against the SHA-256 in `vendor/README.md` on every build. A page makes no network request.

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
   to the older items as carried cost. The step is flagged with the pause and the reason the log gives. The pause caused the
   rebuild, not the step, so rebuild dollars are never part of a step's cost or of the top-three ranking. They are reported
   as one finding instead: how many rebuilds, the pause before each, and the **extra** dollars. Extra is the write price minus
   the re-sent price, on the tokens that had to be written again (est.).
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
- Cache rebuilds: 256 calls (0.6% of consecutive pairs). Their **full cost is 16.8% of all dollars** ($1,023 of $6,073). That is
  the whole cost of those calls, not the part that was avoidable. The **extra** over a normal re-send is $961, 15.8% of all dollars
  (est.): re-writing a saved prompt costs the write price, where re-sending it would have cost the much lower re-sent price.
  The extra is not all avoidable either: a pause that outlasts the saved copy forces a rebuild. An earlier count gave 246 calls and
  16.4%; it skipped the calls where the model changed mid-session, which this count includes. The median pause before a rebuild was
  18 minutes. Run `python3 -m src.audit receipts` to recompute all of this on your own logs.
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
