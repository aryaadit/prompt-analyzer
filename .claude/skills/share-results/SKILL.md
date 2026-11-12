---
name: share-results
description: Sends your finished runs to the group: commits the results folder and nothing else, gets the latest from GitHub, and pushes. Stops if anything outside the results folder is changed. Use after a run is finished.
when_to_use: The user says things like "share my results", "send my results", "share my run", "push my results", or "upload my results".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Share my results

Run `python3 -m src.kit share`. The kit does the whole job itself: it adds the `results/` folder only, saves it
as a commit named "Results: <first name>, <runs>", gets the latest from GitHub, and sends it. You do not run
git yourself.

Show everything it prints, in order, without changing the wording. If it stopped because files outside the
results folder are changed, say in plain words that nothing was sent and nothing was changed, and that the user
should text Adit before sharing. If it says "Nothing new to share", suggest "finish my run" first. After a
successful share, tell the user the run is done.


## Rules for every command

- **Only from the prompt-analyzer window.** If there is no `src/kit.py` in the current folder, or the
  folder name looks like a run (for example `sample-lean-1`), say exactly: "Go back to the
  prompt-analyzer window to do this, so the run stays clean." Then stop.
- **Python command name.** Run `python3 -m src.kit ...`. If the machine says the command is not found or
  not recognized (or opens the Microsoft Store), run the same thing with `python` and then with `py`.
  Use whichever worked for the rest of the chat.
- **Relay the output in plain words.** Copy every number, dollar amount, and file path exactly as the kit
  printed it. Never paraphrase a number.
- **Never edit code and never delete.** The only commit and push allowed is the one `python3 -m src.kit share`
  makes. Never run git yourself, never stash, reset, or force anything. If something fails, say what failed in
  one or two sentences and suggest "check my setup". Do not try to fix the code.
