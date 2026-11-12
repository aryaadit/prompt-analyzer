# Design standard for every page this project makes

Applies to the receipt, the experiment board, and any page added later. If a page breaks a
rule here, fix the page, or change this file first and say why.

## The goal

A classmate who has never seen the tool understands the page in 30 seconds, and can find any
number in two clicks. Nothing is removed to make a page simpler. Detail is layered, not cut.

## Layers

Every page has three layers, in this order.

| Layer | What it holds | Shown |
|---|---|---|
| 1. The answer | One headline sentence, at most four tiles, one main chart | Always, above the fold at 1280 by 800 |
| 2. The explanation | The few things that explain the answer (for the receipt: the top three causes, where the money went) | Always, below the answer |
| 3. The evidence | Every row, every file, the method, the price table | Collapsed sections, tables with search, sort, and filter |

- Each section starts with a heading that is a plain question ("Where did the money go?")
  and one sentence that answers it before any chart.
- Every data table can be downloaded as CSV with one button, so it opens in Google Sheets.
- Every chart has a short text summary under it, so the page still reads if the chart fails.

## Words

- Plain words first. Field names from the log appear only in layer 3.
- Every number carries "exact" or "est." as a small badge. Never color alone.
- Dollars always say API-equivalent once per page, near the top.
- Every term the page coins (re-sent, carried cost, cache rebuild, starting context) has a
  hover or tap explanation where it first appears, and a glossary in layer 3.

## Numbers

- One format per column, right-aligned, tabular figures.
- Dollars: two decimals in tiles, legends, and cards. "<$0.01" below one cent. Four
  decimals only in layer 3 tables.
- Tokens: thousands separators. "14.0k" style in charts, full numbers in tables.
- Shares: whole percent in charts, one decimal in tables. "<0.1%" below 0.1 percent.
- Totals add up on the page. Any breakdown ends with a total row that checks against the
  headline total.

## Look

- One color per kind of work, the same on every page and every chart. Color-blind safe.
  The palette lives in one place in the code (`src/page.py`), and one color means one thing on the whole
  page: blue is re-sent, red-orange is new, indigo is output, ochre is subagent work. A test checks that no
  two meanings share a color and that no color outside the palette appears on a page.
- A true zero is "$0.00". Anything above zero and under a cent is "<$0.01". The same everywhere.
- A tile label never wraps in the middle of a phrase at 1,280 px wide.
- Light background, generous white space, an 8 px spacing grid, at most two font weights.
- System font stack. No web fonts.
- Large type on totals and tiles, so a screenshot works on a slide.
- Cards for layer 2, plain tables for layer 3. No decoration that carries no data.

## Charts

- Library: Apache ECharts, one pinned version, inlined into the page (a receipt in results/receipts/ links it from vendor/). See below.
- SVG renderer, so charts stay sharp in print and PDF.
- Every chart has a title that is a statement ("Prompt size grew 5x over the session"),
  axis labels with units, and a tooltip with the exact numbers and badges.
- No pie charts for more than four parts. No 3D. No dual axes.
- Long series get zoom (dataZoom) and stay fast at 10,000 points.

## Behavior

- One HTML file that works offline by double-click in Chrome, Safari, and Edge. It is self-contained, except a
  receipt saved in results/receipts/, which loads vendor/echarts.min.js from the repo (see below). No network
  requests at all.
- Print and PDF keep colors, keep charts, and never split a card or table row across pages.
  Collapsed sections expand for print.
- Works at 1,000 rows: show the top 50, with "show all".
- HTML-escape every string from a log. No prompt text, file contents, or tool output.
- Usable with a keyboard. Text contrast at least 4.5 to 1.

## The chart library

- Apache ECharts, Apache License 2.0, free.
- One pinned file at vendor/echarts.min.js, with its version, source URL, SHA-256, and the
  license text in vendor/README.md.
- The page builder reads that file and inlines it into each page. Pages never load it from
  the network.
- Exception: a receipt saved in results/receipts/ is built in "linked" mode. It loads
  ../../vendor/echarts.min.js from disk (the same checked file), so a committed receipt is about 50 KB
  instead of 1.1 MB. If the file is not there, each chart says so in words and the numbers still show.
  `python3 -m src.kit receipt <run> --export` writes a self-contained copy (library inlined) to the
  scratch folder, for sharing outside the repo. docs/demo-receipt.html and reports/ stay inlined.
- Approved by Adit on November 12, 2026. No other front-end dependency without approval.
