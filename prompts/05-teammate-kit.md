# Prompt 5: the teammate kit

Start a fresh Claude Code session for this one, after the prompt 4 follow-up is committed.
From the repo root, type:

    Read prompts/05-teammate-kit.md and carry out the prompt in the code block.

It makes the tool usable by someone who does not code. Anna and Reid will type plain
sentences in the Claude Code chat panel. They never type a command and never open a terminal.

```
Read AGENTS.md, docs/GAME-PLAN.md, docs/METHOD.md, and README.md first. Then read
src/parse.py and src/receipt.py. Build on them. Keep every existing command and test working.

Who this is for: two teammates who learned what VS Code and GitHub are this month. From
November 14 to 30 they run the experiment alone, with nobody to ask. They type plain
sentences in the Claude Code chat panel. Everything they see must be plain words. Any error
must say what happened and what to do next, in one or two sentences, with no stack trace.

We do not know yet whether they use a Mac or Windows. Everything must work on both. Use
pathlib everywhere. Do not assume "python3" exists on Windows ("python" or "py" may be the
name). Check how src/parse.py finds a session folder for a working directory, and make it
correct for Windows paths too. Test the Windows case with fixtures.

PART 1. The experiment's file layout.

Tasks live in the repo, under experiments/tasks/<task-slug>/:
- task.md: the task name, one line on what it tests, and the fixed answers to give if the
  agent asks a question during a run.
- start/: the starting files for the task. Made-up content only.
- prompt-original.md and prompt-lean.md: the two prompts, exactly as they will be pasted.

Add one task now, experiments/tasks/sample/, so the kit can be tested end to end. It must be
tiny and cheap: a start/ folder with two short invented text files, and prompts that ask for
a one-paragraph summary of them. Mark it clearly as a practice task, not part of the
experiment. The real tasks get written with Anna tomorrow.

Runs live OUTSIDE the repo. Claude Code loads instruction files from parent folders, so a
run inside this repo would carry this project's rules and inflate its cost. Default runs
folder: a folder named prompt-analyzer-runs in the user's home folder. Make it configurable
in one local settings file that is gitignored.

One run is one folder: <runs folder>/<task>-<version>-<run number>/, a fresh copy of the
task's start/ folder and nothing else. No notes file, no instructions, nothing the agent
could read that the task does not need. Keep run details (task, version, run number, who
ran it, start time) in a separate file in the runs folder, not inside the run folder.

PART 2. src/kit.py, with these commands. Each prints plain words only.

1. python3 -m src.kit check
   The setup check. One line per item, each with OK or a plain fix:
   - Python is new enough. Say which command name works on this machine.
   - Claude Code session logs exist on this machine. If none, say: "No Claude Code
     sessions found. The tool reads Claude Code only. If you use ChatGPT or Codex for
     this class, tell Adit." Count the sessions found. Print no file names.
   - The repo is up to date with GitHub (git fetch, then compare). If behind, say how
     to update in plain words.
   - The runs folder exists or can be created.
   - No CLAUDE.md or AGENTS.md sits in any parent of the runs folder. If one does, name
     the file and say why it matters.
   - The receipt builds on the demo.
   End with one line: "Ready to run" or "Not ready: fix the items above".

2. python3 -m src.kit start <task> <original|lean> [--run N] [--who NAME]
   The run starter.
   - Run number defaults to the next free number for that task and version.
   - Refuse to reuse a folder that exists. Say what to do instead.
   - Copy start/ into the new run folder. Record the run details file.
   - Put the prompt on the clipboard (pbcopy on Mac, clip on Windows; if neither works,
     print the prompt between two clear lines instead).
   - Open the run folder in a new VS Code window ("code" when it is on the path; on a Mac,
     open -a "Visual Studio Code" as a fallback). If neither works, print the folder path
     and say: File, then Open Folder.
   - Print the next steps in plain words: in the new window, open Claude Code, start a new
     session, paste, press Enter, do not add anything, do not step away until it finishes
     (a pause makes the cache rebuild and changes the cost), and if it asks a question,
     answer from task.md. When it finishes, come back to the prompt-analyzer window and
     say "finish my run".

3. python3 -m src.kit finish [<run folder name>]
   - Default: the most recently started run that is not finished.
   - Find the Claude Code session for that run folder. If there is none, or more than one,
     say so plainly and stop. Do not guess.
   - Build its receipt into the runs folder, next to the run, and open it.
   - Append one row to a results file in the runs folder (CSV): task, version, run number,
     who, model, date, minutes, model calls, tool calls, tokens by type, total dollars
     (API-equivalent), cache rebuilds, whether it compacted, and the session id. Exact
     numbers only.
   - Flag the run as "check this" if it had a cache rebuild, a compaction, an error, or
     a session that did not finish. Say so in plain words.
   - Print three lines: the total, the most expensive step, and where the receipt is.

4. python3 -m src.kit receipt [latest | <run folder name>]
   Opens the receipt for a run, building it if needed. "latest" means the latest finished
   run, not the latest session in this repo.

5. python3 -m src.kit runs
   Lists the runs so far in a short table: task, version, run, who, dollars, flag.

PART 3. Plain-English commands as project skills.

Add project skills under .claude/skills/ so a teammate can type a sentence and Claude Code
runs the right command. Read the current Claude Code docs for the exact skill file format
and how project skills are found before you write them. One skill per action:
- setup-check: "check my setup", "am I ready".
- start-run: "start a run", "start run: sample, lean". If the task or version is missing,
  ask with a short list of the tasks in experiments/tasks/. Ask for the teammate's first
  name once and remember it in the local settings file.
- finish-run: "finish my run", "I'm done with the run".
- show-receipt: "show me the receipt", "show the receipt for the last run".
- list-runs: "what runs have we done", "show the runs".
- update-tool: "update the tool", "get the latest version". Runs git pull. If there are
  local changes, stop and explain in plain words. Never force anything.

Each skill:
- Picks the right Python command name for the machine (python3, python, or py).
- Runs the kit command and relays its output in plain words. Never paraphrase a number.
- Never edits code, never commits, never pushes, never deletes. If something fails, say
  what failed and suggest "check my setup". Do not try to fix the code.
- Runs from the prompt-analyzer window only. If it is run from a run folder, say: "Go back
  to the prompt-analyzer window to do this, so the run stays clean."

Add a project .claude/settings.json that allows the kit commands without a permission
prompt, so teammates are not asked to approve every step. Allow only "python -m src.kit"
style commands under each Python command name, and git pull and git fetch. Nothing else.
Check the current docs for the exact permission syntax.

PART 4. docs/START-HERE.md.

One page for Anna and Reid. Plain words, numbered steps, no code blocks except the exact
sentences to type in the chat panel.
- One time: install what is needed (VS Code, Python, Claude Code extension), get the repo
  (GitHub Desktop or VS Code's Clone Repository, whichever needs fewer steps; pick one),
  open it, type "check my setup".
- Each run: the steps from the run starter, in order.
- What to type, as a short table: sentence, what it does.
- If something goes wrong: three common problems and their fixes, then "text Adit with a
  screenshot".
- The rules: same person runs both versions of a task, never reuse a run folder, never
  add to the prompt, do not step away during a run, made-up inputs only.
Link it at the top of README.md, above the game plan link.

PART 5. Tests, with unittest.
- check on a fake home folder: with sessions, with no sessions, with a CLAUDE.md in a
  parent of the runs folder.
- start: next run number, refusal to reuse a folder, the run folder holds only the start
  files, the run details file is written outside it.
- finish with fake session fixtures: finds the session by working directory on Mac-style
  and Windows-style paths, refuses with zero or two candidates, writes the CSV row, sets
  the flag on a rebuild.
- No test opens a browser, a VS Code window, or touches the real clipboard. Mock them.
- No test spends model usage.

When you finish:
- Run all tests.
- Run check on this machine and show me the output.
- Do one practice run end to end, except the part that spends usage: start the sample task
  with --who Adit and show me the next-steps text. Stop there. I will paste the prompt and
  run it myself, then say "finish my run".
- Update README.md (Status, Run it, Layout), the prompt 5 line in docs/GAME-PLAN.md, and add
  one line to docs/AI-USAGE.md.
- Tell me what you built, what you skipped, anything that only works on a Mac, and open
  questions.
- Commit. Ask before pushing.
```

## What to bring back to the planning chat

- Claude Code's final report, pasted whole.
- The output of the setup check.
- After your practice run: the three lines that "finish my run" printed.
