# Prompt 6: the design standard and the receipt redesign

Start a fresh Claude Code session after prompt 5 is committed. From the repo root, type:

    Read prompts/06-polish.md and carry out the prompt in the code block.

It adds the chart library and rebuilds the receipt page to the new design standard in
docs/DESIGN.md. Every page after this one follows the same standard.

```
Read AGENTS.md and docs/DESIGN.md first. DESIGN.md is the standard for every page from now
on. Then read docs/METHOD.md and src/receipt.py. Keep every number, test, and command
working. This is a redesign of how the page looks and reads, not of how it computes.

PART 1. The chart library.
- I approve one dependency: Apache ECharts. Get the latest stable release's
  dist/echarts.min.js from the official npm package or GitHub release. Ask me first if the
  download is blocked.
- Save it as vendor/echarts.min.js. Write vendor/README.md with the version, the source
  URL, the SHA-256, and the Apache 2.0 license text. Commit the file.
- Add src/page.py: shared page parts for every page. The CSS, the color palette (one color
  per kind of work, color-blind safe), number formats, the exact and est. badges, the
  glossary hover text, collapsible sections, the CSV download button, the print styles, and
  a function that inlines ECharts. The receipt uses it now. The experiment board will use it
  next.
- A test that checks the inlined library matches the SHA-256 in vendor/README.md, and that
  no page makes a network request (no http or https in any src, href, url(), or fetch,
  except plain text links in the fine print).

PART 2. Rebuild the receipt to DESIGN.md. Every number on the current page stays on the
new page. Detail moves down a layer. Nothing is dropped.

Layer 1, the answer, above the fold at 1280 by 800:
- Title line: project folder, date, length of the session, model.
- The headline sentence: the single largest cause, in plain words, with its dollars.
- Four tiles: total, model calls, share spent re-sending earlier material, and the
  extra dollars from cache rebuilds.
- One ECharts chart: where the money went, as one horizontal stacked bar with labels, plus
  the legend table with its total row and the "Matches the total at the top" check.

Layer 2, the explanation:
- "What made it expensive?": the top three cards, as they are now.
- "How did the conversation grow?": ECharts bar chart, one bar per call, re-sent and new
  stacked, compactions and cache rebuilds marked, a tooltip per call with exact tokens by
  type, and zoom for long sessions. Statement title, axis labels with units, and one
  sentence of text summary under it.
- "Where did the cost pile up over time?": ECharts line of the running total in dollars
  across calls, with the top three steps marked on the line.

Layer 3, the evidence, collapsed by default:
- Every step: the table, with search, sort, kind filter, row detail, top 50 then
  "show all", and a CSV download.
- Files: the table, with a CSV download.
- Other findings.
- How to read this page, and a glossary of every term the page uses.
- Fine print: method, prices and date checked, validation, the Claude Code total versus
  the transcript total.

Polish:
- Follow DESIGN.md for words, numbers, look, and behavior.
- Hover or tap explanations on re-sent, new, carried cost, cache rebuild, starting context,
  and API-equivalent where each first appears.
- Print and PDF: colors and charts survive, collapsed sections expand, nothing splits
  across pages. Charts use the SVG renderer.

PART 3. Check it like a reader.
- Build the demo and the receipt for 965acdc8. Open both in headless Chrome. Take
  screenshots at 1280 by 800 (layer 1 only), full page, and print to PDF.
- Look at the screenshots yourself. Fix anything that is cramped, misaligned, cut off,
  unreadable, or inconsistent with DESIGN.md, then take them again.
- Save the screenshots and the PDF under reports/ (not committed), and tell me the paths.
- Build every one of my sessions once in memory. Report the largest page size in MB and
  the slowest build.

When you finish:
- Run all tests. Rebuild docs/demo-receipt.html.
- Update README.md and docs/METHOD.md where they describe the page, and add one line to
  docs/AI-USAGE.md.
- Tell me what changed, the page size before and after, what you were unsure about, and
  open questions.
- Commit. Ask before pushing.
```

## What to bring back to the planning chat

- Claude Code's final report, pasted whole.
- The three screenshots or the PDF of the demo receipt.
