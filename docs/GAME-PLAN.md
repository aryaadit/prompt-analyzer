<!-- Mirror of the Google Doc "Prompt Analyzer: project plan" as of 2026-11-12.
     The Google Doc wins for schedule and roles. This repository wins for technical detail.
     If you change one, change the other. -->

# Prompt Analyzer: project plan

B8609 Generative AI for Business, Section 001, Group 1. Adit Arya, Anna Liedtke, Reid Yankowski. Draft for discussion, November 12, 2026.

## Summary

We can finish by December 9 if one thing happens this week: Anna and Reid get the cost summary tool running on their own laptops before Adit leaves on November 14. The tool is built and tested. With it in hand, the experiment that makes up our critical assessment can be run by hand, so the project does not wait on Adit.

The main risk is the 17 days when Adit is away (November 14 to 30). This plan moves the work that needs no coding to the front and makes the automated rerun optional.

## Background

Most of us use AI coding agents on a flat monthly plan. The plan hides what each prompt costs. One prompt can make the agent read dozens of files, run searches, and call the model many times, and none of that is visible when the answer comes back.

The course keeps returning to this. Session 1 covered tokens and the fact that AI tools charge by the token. Session 5 covers cost and model choice. Anyone who pays per token, which includes every company building on these models, has to care about it.

Free tools already turn coding-agent logs into charts, for example claude-devtools and Token Dashboard. The ones we found stop at showing what happened. They do not rerun the task with a leaner prompt and check that the result held up. That is the part we are adding. Reid will compare us properly against LangSmith and the others.

## Goal

By December 9 we want a tool any classmate can run after a Claude Code session, and evidence on whether leaner prompts save money without hurting the result.

- A working tool. One command produces the receipt for a session.
- A result. Five tasks, original prompt against lean prompt, with cost and blind-vote quality for each.
- A five-minute presentation with a demo video and an honest account of what broke.

Out of scope: ordinary Claude or ChatGPT chats (a tool like ours cannot see inside them), energy or compute figures (they are not observable), and anything that sends logs off the laptop.

## What we are building

A tool for the AI coding agents we use in class, starting with Claude Code. It has three parts.

| Part | What it does | Status |
|---|---|---|
| Receipt | Reads the log of an agent session and lists what the agent read, searched, and ran, with the token cost of each step | In progress |
| Diagnosis | Names the most expensive steps and explains why in plain words | Not started |
| Rematch | Runs the same task again with a leaner prompt and compares cost and answer quality | Not started |

Project type on the class sheet: Build It for Yourself.

## How the tool works

Claude Code saves a log of every session on the laptop, under the folder ~/.claude/projects. Each log lists every call to the model with exact token counts, and every tool the agent used, such as reading a file or running a command. Our tool reads that log. It needs no internet connection.

### What is exact and what is estimated

- Exact: tokens for each model call, split into new input, cached input, and output. Session totals are exact too.
- Estimated: the cost of a single file read, search, or command. The log does not record this, so we estimate it from how much the prompt grew after that step.
- API-equivalent: every dollar figure. We multiply tokens by public API prices. On a subscription nobody is billed this amount.

### Carried cost

Everything the agent reads stays in the conversation and is sent again on every later call. A large file read early in a session is paid for many times. The receipt will show this. We expect it to be where a leaner prompt saves the most, and the experiment will test that.

### The pieces

- Parser: turns a session log into a clean list of model calls and tool calls.
- Price table: public prices per model, with the date they were checked.
- Summary: plain-text totals for a session. Built and tested.
- Receipt: a one-page view with every step and its cost.
- Diagnosis: the three most expensive steps and why they cost so much.
- Rematch: a rerun with a leaner prompt, and a comparison.

## Where things stand on November 12

- The idea is chosen and entered on the class sheet.
- A private code repository exists at [github.com/aryaadit/prompt-analyzer](https://github.com/aryaadit/prompt-analyzer). Anna and Reid need to send Adit their GitHub usernames to get access.
- We mapped how Claude Code records a session. Token counts are exact for each model call. They are not recorded per file or per tool, so per-step costs will be estimates, and the receipt will label them that way.
- The code is built and tested: a parser, a price table, a plain-text cost summary, and the receipt page (one HTML file, with the diagnosis). Run `python3 -m src.receipt --session latest`, or open docs/demo-receipt.html, which uses made-up data and is safe for slides.
- Claude Code's own session totals are sometimes higher than the sum of the calls in the log. We measured the gap. It is about half a percent of dollars in ordinary sessions and about 10 percent in long sessions that were compacted.

## What the logs taught us

We inspected 83 real sessions before writing code. The full write-up is docs/SCHEMA.md in the repository.

- Token usage is recorded once per model call, and it is exact.
- One model response is split across several log records that repeat the same usage. Counting every record would overcount, so the parser counts once per response.
- Every tool call links cleanly to its result. This held for all 18,250 results checked.
- Most searches happen inside shell commands, not through a search tool. Spotting them needs a rule that reads the command, so those lines are estimates.
- Work done by helper agents is stored in separate files and has to be added in.
- The log records why a cached prompt was missed. That helps the diagnosis explain an expensive step.
- For about half of the session totals, Claude Code's own total is higher than the sum of the logged calls. Priced out, the gap is about 0.5 percent of dollars in sessions without compaction and about 10 percent in sessions with it. Our experiment tasks are short, so they should fall in the first group.

## What the final presentation needs

- One to three slides on the problem.
- One demo video that we record ourselves, two to three minutes long.
- One to three slides of critical assessment: what problem the tool solves, how we know it works, what broke, and what we would change.

All three of us get the same grade, and not everyone has to present.

## Presentation outline

A first draft, for five minutes in total.

1. The problem, one slide. A flat plan hides what a prompt costs. Show one real receipt.
2. What we built, one slide. Receipt, diagnosis, rematch.
3. Demo video, two to three minutes. Run a class task, open the receipt, read the diagnosis, run the leaner prompt, compare the two.
4. Results, one slide. The five-task table with tokens saved and the blind-vote outcome.
5. What broke and what we would change, one slide. Estimated versus exact numbers, the totals gap, and any task where the lean prompt lost.

## How we prove it works

This experiment is the critical assessment. It is also the part that existing tools do not have.

- Five tasks. Start with the two in-class builds, Job Hunt in a Folder and the personal site, because every classmate has run them. Add three of our own.
- Two versions of each task: the original prompt and a leaner prompt.
- Three runs of each version, because the same prompt costs a different amount each time. That is 30 runs in total.
- Cost comes from the tool: exact token totals, and dollars at public API prices.
- Quality comes from a blind vote. Classmates see output A and output B without knowing which is which, and pick the better one.
- If the lean prompt loses on quality, we report that. It is a finding.

The runs can be done by hand: copy the task folder, paste the prompt into the agent, then run the summary tool on that session. The automated rerun is a convenience, not a requirement.

## One experiment run, step by step

1. Make a fresh copy of the task folder. Never reuse a folder from an earlier run.
2. Open the copy in VS Code and start a new Claude Code session.
3. Paste the prompt for that task and version. Add nothing to it.
4. Let it finish. If it asks a question, give the answer written in the task sheet, so every run gets the same answers.
5. Run the summary tool on that session and save the output.
6. Record the numbers in the results sheet.
7. Keep what the agent produced. The blind vote needs it.

Use made-up inputs, not real CVs or personal files, so the outputs can be shared for the vote.

The results sheet needs these columns: task, version (original or lean), run number, who ran it, model, tokens by type, API-equivalent dollars, number of model calls, number of tool calls, and where the output is saved.

## How we build

Nobody writes code by hand. A coding agent builds the tool from written prompts, and a person reviews each step.

- The prompts live in the prompts folder of the repository, numbered in order.
- Run each prompt in a fresh Claude Code session, from the repository folder.
- The agent follows the rules in AGENTS.md: nothing from a log goes into the repository, ask before any push, ask before installing anything.
- When the agent stops with a question, answer it or bring it to the group. Do not let it guess.
- After each session the agent adds a line to docs/AI-USAGE.md. The course requires us to describe how we used AI.

## Getting set up

1. Send Adit your GitHub username and accept the invitation to the repository.
2. Clone the repository and open the folder in VS Code.
3. Check that Python 3 and Claude Code are installed. Nothing else is needed.
4. Read README.md, then docs/PLAN.md.
5. Run the summary tool on one of your own sessions and tell the group whether it worked. The command is: python3 -m src.summarize --session latest

## Starting your own Claude on this project

If you use your own Claude with the repository open, paste this as the first message so it has the context:

```
Read AGENTS.md, README.md, docs/PLAN.md, and docs/SCHEMA.md. This is a group project for a Columbia Business School course. We are building a tool that reads Claude Code session logs and shows what a prompt cost, then tests whether a leaner prompt gives the same result for less. Follow the rules in AGENTS.md. Do not read or copy anything from session logs unless I ask. Start by telling me what is built, what is next, and any open questions.
```

The repository is the source of truth for technical detail. This document is the source of truth for schedule and roles.

## Build roadmap

Each step is one prompt and one agent session.

- Prompt 1, repository setup: done.
- Prompt 2, map the log format: done. The output is docs/SCHEMA.md.
- Prompt 3, parser, price table, and plain-text summary: done on November 12.
- Prompt 4, per-step estimates, the receipt page, and a demo receipt: done on November 12. See prompts/04-receipt.md and docs/METHOD.md. Open docs/demo-receipt.html to see the page.
- Prompt 5, the teammate kit: a setup check, plain-English commands, and a run starter. Before November 14.
- Prompt 6, the experiment board and the task sheets. Before November 14.
- Prompt 7, the lean prompt writer, which reads the receipt's findings. Before November 14.
- Prompt 8, clean-up for the demo: redaction and the README. After December 1.
- The automated rematch runner is dropped unless time allows. Runs are done by hand with the run starter.

## Timeline and owners

| Dates | Goal | Who |
|---|---|---|
| Nov 12 to 13 | The cost summary tool works on one session and is pushed to the repository. All three have repository access. This plan is agreed. | Adit, with Anna |
| Nov 14 to 21 | Pick the five tasks and write the original prompts. Draft the question for the blind vote. Install the tool and run it on our own sessions. | Anna (tasks and vote). Reid (install and test, after Nov 13) |
| Nov 22 to 30 | Do the 30 runs by hand and record the results in a shared sheet. Build the itemized receipt page and the diagnosis. | Anna and Reid (runs). Builder to be decided |
| Dec 1 to 2 | Package the tool as a skill. Collect blind votes at Session 5 on December 2. | All |
| Dec 3 to 9 | Freeze features on Dec 4. Record the video by Dec 6. Finish the deck by Dec 7. Rehearse. Present on Dec 9. | All. Anna leads the deck and video |

Adit is away from November 14 to 30. Reid joins after Friday, November 13. Thanksgiving is November 26.

## Proposed roles

| Person | Owns |
|---|---|
| Adit | The code: parser, cost summary, receipt page. Sets up the repository and writes the instructions for the coding agent before leaving. |
| Anna | The experiment: tasks, prompts, and the blind vote. The deck and the demo video script. |
| Reid | The cost method and the price table check. The comparison with existing tools such as LangSmith and claude-devtools. Testing the tool on a second laptop. |

These are proposals. Change them in the meeting.

## Decisions for the meeting

- How available is Adit while he is away? Can he run build sessions remotely, or does someone else drive the coding agent?
- Who builds the receipt page and the diagnosis while Adit is away? The repository has step-by-step prompts for the coding agent, so nobody has to write code by hand, but someone has to run them and review the output.
- Which coding agent do Anna and Reid use in class: Claude Code, Codex, or Copilot? The tool reads Claude Code logs today. A second log format is extra work.
- Which three tasks join the two in-class builds?
- How do we collect blind votes, and how many do we need? Suggested minimum: ten voters.
- Do we show our own real usage numbers in the presentation?

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| The receipt page is not ready by November 30 | Use the plain-text summary for the experiment. Build the page after Adit returns. |
| The tool does not run on Anna's or Reid's laptop | Run the experiment on one laptop and note the limit in the assessment. |
| Long sessions that get compacted show a totals gap of about 10 percent | Keep experiment tasks short. Compare whole-session totals, which are complete, and show the gap as its own line. |
| Lean prompts do not save much, or lose on quality | Report it. The assignment asks for an honest assessment. |
| Usage limits slow down the 30 runs | Keep the tasks small. Spread the runs across three accounts and several days. |

## Questions for the professors

- Presentation length. The Session 2 slides say 5 minutes inside a 7-minute slot. The syllabus says 7 minutes plus Q&A.
- We changed our project type to Build It for Yourself after Session 2. Confirm that this is fine.

## Privacy rule

Session logs contain our prompts and file contents. They stay on each person's laptop. Nothing from a log goes into the repository, this folder, or the deck, apart from numbers.

## Glossary

- Token: the unit models read and write, roughly three quarters of an English word. Usage is counted in tokens.
- Model call: one request to the model. A single prompt from you can trigger dozens.
- Session log: the file Claude Code saves for one session.
- Cached input: part of the prompt the provider has seen recently and charges less for.
- Carried cost: what it costs to resend earlier material on later calls.
- Compaction: when a long session is summarized to free up room. Our totals gap is more common in sessions where this happened.
- API-equivalent dollars: tokens multiplied by public API prices. A yardstick, not a bill.
- Skill: a folder of instructions and scripts that teaches an agent one task.
- AGENTS.md: the rules file a coding agent reads before working in a repository.

## Links

- [Code repository](https://github.com/aryaadit/prompt-analyzer) (private)
- [Class project sheet](https://docs.google.com/spreadsheets/d/1NFzF28GcuNPm6lGouEiqd8wU1YM1fHlfMhd4T8kN6Qs/edit)
- Project brief: "Gen AI Group Project - Brief (compiled).pdf" in this folder
