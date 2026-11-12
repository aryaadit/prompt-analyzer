# Start here (Anna and Reid)

This page is for running the experiment on your own laptop, with nobody to ask. You never type a
command and you never open a terminal. You type plain sentences in the Claude Code chat panel in
VS Code, and the tool does the rest.

## One time: get set up (about 20 minutes)

1. Send Adit your GitHub username. Accept the invitation email GitHub sends you. The project is
   private, so nothing works until you have done this.
2. Install VS Code from code.visualstudio.com.
3. Install Git from git-scm.com. On a Mac, if a window offers to install "developer tools", say yes
   instead. Restart VS Code afterwards.
4. Install Python from python.org (version 3.9 or newer). On Windows, tick the box "Add python.exe to PATH"
   on the first screen of the installer.
5. In VS Code, click the Extensions icon on the left, search for "Claude Code", click Install, then sign in
   with your Claude account.
6. Get the project. In VS Code press Ctrl+Shift+P (Cmd+Shift+P on a Mac), type "Git: Clone", press Enter,
   paste https://github.com/aryaadit/prompt-analyzer, press Enter, pick your Documents folder, and sign in to
   GitHub when it asks. When it offers to open the folder, click Open. If it asks whether you trust the
   authors, click Yes.
7. Open the Claude Code panel in that VS Code window, start a new chat, and type this exact sentence:

       check my setup

8. Read the answer. Every line starts with OK or FIX. A line that starts with FIX says what to do. When
   the last line says "Ready to run", you are done. This is the only window that has the tool, so keep it
   open. We call it the prompt-analyzer window.

## Every run

Do these in order. Do not skip any.

1. In the prompt-analyzer window, in the Claude Code chat panel, type: "start a run". It asks which task and which
   version (original or lean), and your first name the very first time. You can also type the
   whole thing at once, for example this exact sentence:

       start run: sample, lean

2. A new VS Code window opens on a fresh, empty copy of the task. It lives in a scratch folder
   (prompt-analyzer-scratch, in your home folder), outside the project. The prompt is already on your clipboard.
   The prompt-analyzer window prints the next steps. They are the same as the steps below.
3. In the new window, open Claude Code and start a NEW session (a fresh chat, not an old one).
4. Type /model. Pick Sonnet 5.5, set Effort to High, leave Ultracode off. Same every run.
5. Paste the prompt (Ctrl+V on Windows, Cmd+V on a Mac) and press Enter.
6. Add nothing. Do not type anything else.
7. If a permission prompt appears, click Yes.
8. Do not step away until it finishes. If you pause, the saved copy of the conversation expires and has
   to be rebuilt. That changes the cost, and the run gets flagged.
9. If it asks you a question, answer from the list the tool printed (it is also in the task's task.md). Every run
   of a task gets the same answers.
10. When it finishes, go back to the prompt-analyzer window and type this exact sentence:

       finish my run

11. It prints the total, the largest cause, the most expensive step, and where the receipt is. The receipt opens
   in your browser. It then says where everything went: the receipt, what the agent made, and your row in
   your results file, all inside the project's results folder. If it says "Check this run", the run was
   flagged (for example, it used a different model or effort from the first run of the task). Do not start it
   again. Tell Anna. If it says it skipped a file for being over 5 MB, tell Anna too.
12. Open your results file, results/<your first name in lower case>.csv, in the project. Copy the new last row
    into the shared results sheet.
13. Last step: in the prompt-analyzer window, type this exact sentence:

       share my results

    It sends your results folder to the group (and nothing else). If it says files outside the results folder
    are changed, nothing was sent: text Adit.

Runs are named task, version, number, and your first name, for example sample-lean-1-anna. Everything the blind
vote needs is now in results/outputs/ (what the agent made), results/receipts/, and
results/run-details/, all inside the project. The scratch folder is only a work area. Once you have shared,
you can clear it; the tool never deletes it for you.

## What to type

Type these in the Claude Code chat panel of the prompt-analyzer window. Your own words work too.

| Sentence | What it does |
|---|---|
| check my setup | Checks that your laptop is ready, one line per item |
| start a run | Makes a fresh run folder, copies the prompt, opens the folder in a new window |
| start run: sample, lean | The same, with the task and version given |
| finish my run | Finds the session, builds the receipt, copies what the agent made, saves the numbers in results/ |
| show me the receipt | Opens the receipt of the last finished run. It shows its charts when opened from inside the project |
| export my receipt | Makes a standalone copy of the receipt to send to someone or open anywhere |
| show me the prompt again | Puts the prompt of your latest run back on the clipboard and prints it |
| show the runs | Lists every run so far, from everyone's results files: task, version, run, who, dollars, flag |
| share my results | Sends your results folder to the group. It sends nothing else, and stops if anything else is changed |
| update the tool | Gets the newest version of the tool. It stops if you changed anything yourself |

All dollar amounts are API-equivalent: tokens times public API prices. Nobody is billed that amount.

## If something goes wrong

1. **The setup check shows a FIX line.** Do what the line says. If it says you are behind, type "update the tool".
   If it says Git or Python is missing, install it (steps 3 and 4 above), restart VS Code, and type "check my
   setup" again.
2. **The new window did not open, or the prompt is not on your clipboard.** The chat panel prints the folder
   path and, if needed, the whole prompt between two lines. In VS Code choose File, then Open Folder, and pick
   the folder. Copy the prompt from between the two lines.
3. **"share my results" says files outside the results folder are changed.** Nothing was sent and nothing was
   changed. Text Adit; do not try to fix it yourself.
4. **"finish my run" cannot find the session.** Make sure you pasted the prompt in the NEW window and pressed
   Enter. Do not start the run again. Type "check my setup", and if that is fine, text Adit.

If none of those fix it: text Adit with a screenshot.

## The rules

- The same person runs both versions of a task.
- Never reuse a run folder. Each run gets its own, and the tool will not let you reuse one.
- Never put real data in results/. It is shared with the group on GitHub: made-up inputs only.
- Never add to the prompt. Paste it exactly as it is.
- Never change the model or effort between runs: Sonnet 5.5, Effort High, Ultracode off, every time.
- Do not step away during a run. Start it when you have the time to see it through.
- Made-up inputs only. No real CVs, no personal files.
- Type the setup and tool sentences in the prompt-analyzer window only. In a run window, type nothing except
  /model (step 4), the pasted prompt, and the answers to the agent's questions. Anything else changes the run and its cost.
