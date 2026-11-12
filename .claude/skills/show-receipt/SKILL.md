---
name: show-receipt
description: Opens the receipt page for an experiment run in the browser. Use when the user wants to see the receipt of the last finished run or of a named run.
when_to_use: The user says things like "show me the receipt", "show the receipt for the last run", "open the receipt", or "show the receipt for sample-lean-1".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Show the receipt

Run `python3 -m src.kit receipt latest`. If the user named a run folder (for example `sample-lean-1`), run
`python3 -m src.kit receipt <that name>` instead. "Last run" and "latest" mean the latest finished run.

Show what it prints, in order, without changing the wording. It opens the receipt in the browser; if it says
it could not, give the user the file path it printed.


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
