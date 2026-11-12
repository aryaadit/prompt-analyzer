---
name: setup-check
description: Checks that this laptop is ready to run the experiment: Python, Claude Code sessions, the latest version of the tool, the scratch folder, and the demo receipt. Use when the user wants to know if their setup works.
when_to_use: The user says things like "check my setup", "am I ready", "is everything working", "is the tool set up", or something went wrong and they do not know why.
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Check my setup

Run `python3 -m src.kit check`.

Show every line it prints, in order, without changing the wording. Each line starts with OK or FIX. The last
line says "Ready to run" or "Not ready: fix the items above". If any line starts with FIX, say which fix to do
first, using the words on that line. If the fix says to tell Adit, tell the user to text Adit with a screenshot.


## Rules for every command

- **Only from the prompt-analyzer window.** If there is no `src/kit.py` in the current folder, or the
  folder name looks like a run (for example `sample-lean-1-anna`), say exactly: "Go back to the
  prompt-analyzer window to do this, so the run stays clean." Then stop.
- **Python command name.** Run `python3 -m src.kit ...`. If the machine says the command is not found or
  not recognized (or opens the Microsoft Store), run the same thing with `python` and then with `py`.
  Use whichever worked for the rest of the chat.
- **Relay the output in plain words.** Copy every number, dollar amount, and file path exactly as the kit
  printed it. Never paraphrase a number.
- **Never edit code, never commit, never push, never delete.** If something fails, say what failed in
  one or two sentences and suggest "check my setup". Do not try to fix the code.
