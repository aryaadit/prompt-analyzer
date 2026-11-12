---
name: finish-run
description: Finishes an experiment run: finds its Claude Code session, builds the receipt, records the result in the results file, flags anything odd, and prints the total, the largest cause, the most expensive step, and where the receipt is. Use when the user says a run is done.
when_to_use: The user says things like "finish my run", "I am done with the run", "the run finished", or "record my run".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Finish my run

1. Run `python3 -m src.kit finish`. If the user named a particular run folder (for example `sample-lean-1`),
   run `python3 -m src.kit finish <that name>` instead.
2. Show everything it prints, in order, without changing the wording or the numbers. That includes the lines about
   outputs (and any file it skipped for being over 5 MB), where the results went, and the last step: "share my
   results". Do not share for the user unless they say so.
3. If the first line starts with "Check this run", say plainly that this run is flagged, repeat the reasons
   from that line, and tell the user to mention it to Anna or Adit. Do not start the run again yourself.
4. If the kit says it found no session, or more than one, relay that and stop. Do not pick one.


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
