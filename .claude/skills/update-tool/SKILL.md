---
name: update-tool
description: Gets the latest version of the tool from GitHub with a safe update that never forces anything. Stops and explains if the user has changes of their own. Use when the user wants the newest version.
when_to_use: The user says things like "update the tool", "get the latest version", "pull the latest", or the setup check said the copy is behind.
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Update the tool

Run `python3 -m src.kit update`. It checks for changes of the user's own, stops if there are any, and
otherwise runs a plain `git pull --ff-only`.

Show what it prints. If it stopped because of local changes, say in plain words that nothing was changed and
that the user should text Adit before updating. Do not stash, reset, discard, or force anything yourself. After
a successful update, suggest "check my setup".


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
