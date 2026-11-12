---
name: start-run
description: Starts one experiment run: makes a fresh run folder, puts the prompt on the clipboard, opens the folder in a new VS Code window, and prints the next steps. Use when the user wants to start a run of a task.
when_to_use: The user says things like "start a run", "start run: sample, lean", "begin the next run", or "run the lean version of <task>".
allowed-tools: Bash(python3 -m src.kit *) Bash(python -m src.kit *) Bash(py -m src.kit *)
---

# Start a run

1. **Task.** Take the task name from what the user said. If they did not name one, list the tasks by looking
   for `experiments/tasks/*/task.md` (use the file search tool, not the shell) and ask which one, offering
   the names as a short list. Use only a name that is in that list.
2. **Version.** It must be `original` or `lean`. If the user did not say, ask, with those two choices.
3. **First name.** Look in `local-settings.json` (a file in this folder) for a `who` entry. If it is there,
   use it and do not ask. If not, ask once for the user's first name. Use letters only; if the answer holds
   anything else, ask again. The kit remembers the name, so nobody is asked twice.
4. Run `python3 -m src.kit start <task> <version> --who <first name>`. Add `--run <number>` only if the user
   asked for a specific number.
5. Show everything it prints, in order, including the numbered next steps, without changing the wording or the
   numbers. Tell the user to follow the steps in the new VS Code window, not in this one.

If the task is `sample`, say once that it is a practice task and not part of the experiment.
If the kit says a run folder already exists, relay that and do not try another number yourself.


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
