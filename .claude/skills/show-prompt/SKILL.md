---
name: show-prompt
description: Puts the prompt of an experiment run back on the clipboard and prints it, so it can be pasted again. Use when the user lost the prompt, pasted something else over it, or wants to see it once more.
when_to_use: The user says things like "show me the prompt again", "put the prompt back on my clipboard", "I lost the prompt", "copy the prompt again", or "what was the prompt for sample-lean-1-anna".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Show the prompt again

Run `python3 -m src.kit prompt`. It uses the run that was started last. If the user named a run folder (for example
`sample-lean-1-anna`), run `python3 -m src.kit prompt <that name>` instead.

Show everything it prints, in order, without changing the wording: the prompt between the two lines, then whether it
is on the clipboard. If it says it could not reach the clipboard, tell the user to copy the prompt from between the
two lines. If it says the run began before prompts were saved, relay that note too.

The prompt comes from the task's prompt file, saved when the run started. It never comes from a session log.

Remind the user to paste it in the run window and add nothing to it.


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
