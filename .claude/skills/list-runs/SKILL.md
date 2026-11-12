---
name: list-runs
description: Lists the experiment runs done so far in a short table: task, version, run number, who ran it, dollars, and whether the run needs a second look. Use when the user asks what has been run.
when_to_use: The user says things like "what runs have we done", "show the runs", "list the runs", or "how many runs are done".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# List the runs

Run `python3 -m src.kit runs`.

Show the table it prints exactly as it is, and any lines under it that explain a "check this" flag. Dollar
figures are API-equivalent: tokens times public API prices, not a bill. Say that once.


## Rules for every command

- **Only from the prompt-analyzer window.** If there is no `src/kit.py` in the current folder, or the
  folder name looks like a run (for example `sample-lean-1`), say exactly: "Go back to the
  prompt-analyzer window to do this, so the run stays clean." Then stop.
- **Python command name.** Run `python3 -m src.kit ...`. If the machine says the command is not found or
  not recognized (or opens the Microsoft Store), run the same thing with `python` and then with `py`.
  Use whichever worked for the rest of the chat.
- **Relay the output in plain words.** Copy every number, dollar amount, and file path exactly as the kit
  printed it. Never paraphrase a number.
- **Never edit code, never commit, never push, never delete.** If something fails, say what failed in
  one or two sentences and suggest "check my setup". Do not try to fix the code.
