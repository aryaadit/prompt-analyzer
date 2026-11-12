"""The teammate kit: setup check, run starter, run finisher, receipts, and the run list.

    python3 -m src.kit check
    python3 -m src.kit start <task> <original|lean> [--run N] [--who NAME]
    python3 -m src.kit finish [<run folder name>]
    python3 -m src.kit receipt [latest | <run folder name>]
    python3 -m src.kit prompt [latest | <run folder name>]
    python3 -m src.kit runs
    python3 -m src.kit update

Everything printed is plain words. A problem says what happened and what to do next, in a
sentence or two, never a stack trace. Runs live outside the repo (default: prompt-analyzer-runs
in the home folder) because Claude Code reads instruction files from parent folders, and a run
inside this repo would carry this project's rules and change its cost. Works on Mac and Windows:
paths are pathlib, and nothing assumes the Python command is called python3.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import estimate, fmt, parse, paths, receipt, summarize

REPO = Path(__file__).resolve().parent.parent
SETTINGS_NAME = 'local-settings.json'  # gitignored; holds runs_folder and who
DEFAULT_RUNS_NAME = 'prompt-analyzer-runs'
MIN_PYTHON = (3, 9)
VERSIONS = ('original', 'lean')
DETAILS_DIR = 'run-details'
LONG_AGO = datetime(1970, 1, 1, tzinfo=timezone.utc)
RESULTS_NAME = 'results.csv'
JUNK_FILES = ('.DS_Store', '.gitkeep', 'Thumbs.db')
_SLUG = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_RUN_NAME = re.compile(r'^(?P<task>[a-z0-9][a-z0-9-]*)-(?P<version>original|lean)-(?P<run>\d+)$')
GO_BACK = 'Go back to the prompt-analyzer window to do this, so the run stays clean.'
CSV_COLUMNS = (
    'practice', 'task', 'version', 'run', 'who', 'model', 'effort', 'date', 'minutes', 'model_calls', 'tool_calls', 'tool_errors',
    'input_tokens', 'cache_read_tokens', 'cache_write_5m_tokens', 'cache_write_1h_tokens', 'output_tokens',
    'total_usd_api_equivalent', 'cache_rebuilds', 'compacted', 'check_this', 'check_reasons', 'session_id')


class KitError(Exception):
    """A problem to tell the teammate about in plain words. The message is what gets printed."""


# ---------------------------------------------------------------- where things live

class Env:
    """The folders the kit works in. Tests pass fake ones; the real kit uses the real ones."""

    def __init__(self, home=None, repo=None, settings_path=None):
        self.home = Path(home) if home else Path.home()
        self.repo = Path(repo) if repo else REPO
        self.settings_path = Path(settings_path) if settings_path else self.repo / SETTINGS_NAME
        self.projects_root = self.home / '.claude' / 'projects'
        self.tasks_root = self.repo / 'experiments' / 'tasks'


def load_settings(env):
    """The local settings as a dict. Missing file means no settings; a broken file is reported."""
    try:
        data = json.loads(env.settings_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise KitError('The settings file %s is damaged. Delete it and try again; the kit will make a new one. '
                       'If you are unsure, tell Adit.' % env.settings_path.name)
    return data if isinstance(data, dict) else {}


def save_settings(env, settings):
    """Write the local settings file."""
    env.settings_path.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')


def runs_folder(env):
    """The folder that holds every run: from the settings file, else prompt-analyzer-runs in the home folder."""
    chosen = load_settings(env).get('runs_folder')
    folder = Path(chosen).expanduser() if chosen else env.home / DEFAULT_RUNS_NAME
    if not folder.is_absolute():
        raise KitError('The runs folder in %s must be a full path, such as one starting with / or C:\\. Tell Adit.'
                       % env.settings_path.name)
    return folder


def now_text():
    """The current local time as text, to the millisecond."""
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def _atomic_write(path, text):
    """Write a small text file in one step so a crash cannot leave half a file."""
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(str(temp), str(path))


# ---------------------------------------------------------------- things that touch the machine
# Tests replace these four, so no test opens a window, a browser, or the real clipboard.

def copy_to_clipboard(text):
    """Put text on the clipboard (pbcopy on Mac, clip on Windows). True if it worked."""
    if sys.platform == 'darwin':
        command, data = ['pbcopy'], text.encode('utf-8')
    elif sys.platform.startswith('win'):
        command, data = ['clip'], (text.encode('ascii') if text.isascii() else text.encode('utf-16'))
    else:
        return False
    try:
        subprocess.run(command, input=data, check=True, timeout=10,
                       env=dict(os.environ, LC_ALL='en_US.UTF-8'))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def open_in_vscode(folder):
    """Open a folder in a new VS Code window. True if it worked."""
    attempts = []
    code = shutil.which('code')
    if code:
        attempts.append([code, '-n', str(folder)])
    if sys.platform == 'darwin':
        attempts.append(['open', '-a', 'Visual Studio Code', str(folder)])
    for command in attempts:
        try:
            subprocess.run(command, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def open_in_browser(path):
    """Open a local file in the default browser. True if it worked."""
    try:
        return bool(webbrowser.open(Path(path).resolve().as_uri()))
    except Exception:  # a browser that cannot start must never stop a run from being recorded
        return False


def git(env, *args, timeout=90):
    """Run git in the repo. Returns (exit code, output), or None when git is not installed."""
    try:
        done = subprocess.run(['git', '-C', str(env.repo)] + list(args), capture_output=True, text=True,
                              timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return 124, ''
    return done.returncode, done.stdout.strip()


def python_command_name():
    """The command name that runs this same Python on this machine (python3, python, or py), or None."""
    order = ('py', 'python', 'python3') if sys.platform.startswith('win') else ('python3', 'python', 'py')
    ours = os.path.realpath(sys.executable)
    for name in order:
        found = shutil.which(name)
        if not found:
            continue
        try:
            done = subprocess.run([found, '-c', 'import sys; print(sys.executable)'], capture_output=True,
                                  text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and os.path.realpath(done.stdout.strip()) == ours:
            return name
    return None


# ---------------------------------------------------------------- tasks and runs on disk

def list_tasks(env):
    """Names of the tasks that have a start folder and both prompts, sorted."""
    if not env.tasks_root.is_dir():
        return []
    return sorted(p.name for p in env.tasks_root.iterdir()
                  if p.is_dir() and (p / 'start').is_dir() and (p / 'prompt-original.md').is_file()
                  and (p / 'prompt-lean.md').is_file())


def task_folder(env, task):
    """The folder of a task, or a plain error that lists the tasks there are."""
    if _SLUG.match(task or '') and task in list_tasks(env):
        return env.tasks_root / task
    names = list_tasks(env)
    raise KitError('I do not know a task called "%s". The tasks are: %s.' % (task, ', '.join(names) or 'none yet'))


def is_practice(task_dir):
    """A task is practice when the first line of its task.md says PRACTICE."""
    try:
        first = (task_dir / 'task.md').read_text(encoding='utf-8').splitlines()[0]
    except (OSError, IndexError):
        return False
    return 'PRACTICE' in first


def task_answers(task_dir):
    """The fixed answers section of task.md as plain lines, or an empty list."""
    try:
        lines = (task_dir / 'task.md').read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out, inside = [], False
    for line in lines:
        if line.startswith('#'):
            inside = 'answer' in line.lower()
            continue
        if inside and line.strip():
            out.append(line.rstrip())
    return out


def run_name(task, version, number):
    """The folder name of one run."""
    return '%s-%s-%d' % (task, version, number)


def read_all_details(runs):
    """Every run's details record, oldest start first. Damaged files are skipped."""
    found = []
    for path in sorted((runs / DETAILS_DIR).glob('*.json')) if (runs / DETAILS_DIR).is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get('name'):
            found.append(data)
    found.sort(key=lambda d: estimate.parse_time(d.get('started')) or LONG_AGO)
    return found


def write_details(runs, details):
    """Save one run's details record (outside the run folder)."""
    folder = runs / DETAILS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    _atomic_write(folder / (details['name'] + '.json'), json.dumps(details, indent=2) + '\n')


def next_run_number(runs, task, version):
    """The next free run number for a task and version (folders and details files both count)."""
    used = set()
    names = [p.name for p in runs.iterdir()] if runs.is_dir() else []
    names += [d['name'] for d in read_all_details(runs)]
    for name in names:
        match = _RUN_NAME.match(name)
        if match and match.group('task') == task and match.group('version') == version:
            used.add(int(match.group('run')))
    return max(used, default=0) + 1


def find_run(runs, name):
    """The details record for a run folder name, or a plain error."""
    for details in read_all_details(runs):
        if details['name'] == name:
            return details
    raise KitError('I do not know a run called "%s". Say "show the runs" to see the ones there are.' % name)


# ---------------------------------------------------------------- start

def start_run(env, task, version, run=None, who=None):
    """Make the run folder and its details record. Returns (details, prompt text, task folder)."""
    if version not in VERSIONS:
        raise KitError('The version must be "original" or "lean", not "%s".' % version)
    task_dir = task_folder(env, task)
    settings = load_settings(env)
    who = (who or settings.get('who') or '').strip()
    if not who:
        raise KitError('I need your first name for the record. Add --who and your first name, for example: --who Anna.')
    runs = runs_folder(env)
    number = run if run is not None else next_run_number(runs, task, version)
    if number < 1:
        raise KitError('The run number must be 1 or higher.')
    name = run_name(task, version, number)
    if (runs / name).exists() or (runs / DETAILS_DIR / (name + '.json')).exists():
        raise KitError('The run folder %s already exists, so I did not touch it. Never reuse a run folder: it still '
                       'holds the earlier run. Start again without --run to use the next free number, which is %d.'
                       % (name, next_run_number(runs, task, version)))
    prompt = (task_dir / ('prompt-%s.md' % version)).read_text(encoding='utf-8').rstrip('\r\n')
    _copy_start_files(task_dir / 'start', runs / name)
    details = {'name': name, 'task': task, 'version': version, 'run': number, 'who': who,
               'started': now_text(), 'finished': None, 'practice': is_practice(task_dir),
               'folder': str(runs / name), 'prompt': prompt}
    write_details(runs, details)
    if settings.get('who') != who:
        save_settings(env, dict(settings, who=who))
    return details, prompt, task_dir


def _copy_start_files(source, target):
    """Copy the task's start files into a new folder, and nothing else. Cleans up if the copy fails."""
    if not any(p.is_file() and p.name not in JUNK_FILES for p in source.rglob('*')):
        raise KitError('The start folder of this task is empty, so there is nothing to run. Tell Adit.')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(source), str(target), ignore=shutil.ignore_patterns(*JUNK_FILES))
    except OSError:
        shutil.rmtree(str(target), ignore_errors=True)  # a half-made folder we just created
        raise KitError('I could not copy the start files into %s. Check that the disk has room and that the '
                       'folder is not open in another program, then try again.' % target.parent)


def next_steps(details, task_dir, clipboard_ok, vscode_ok, prompt):
    """The plain-words text printed after a run starts."""
    lines = []
    if details['practice']:
        lines += ['PRACTICE TASK: this run is not part of the experiment.', '']
    lines.append('Run folder: %s' % details['folder'])
    if vscode_ok:
        lines.append('It is opening in a new VS Code window.')
    else:
        lines.append('I could not open VS Code for you. In VS Code choose File, then Open Folder, and pick the '
                     'run folder above.')
    if clipboard_ok:
        lines.append('The prompt is on your clipboard.')
    else:
        lines += ['I could not reach the clipboard. Copy the prompt between the two lines:',
                  '----- START OF PROMPT (copy everything below this line) -----', prompt,
                  '----- END OF PROMPT (copy everything above this line) -----']
    lines += ['', 'Next steps:',
              '1. In the new VS Code window, open Claude Code and start a NEW session (a fresh chat).',
              '2. Type /model. Pick Sonnet 5.5, set Effort to High, leave Ultracode off. Same every run.',
              '3. Paste the prompt (Cmd+V on a Mac, Ctrl+V on Windows) and press Enter.',
              '4. Do not add anything to it.',
              '5. If a permission prompt appears, click Yes.',
              '6. Do not step away until it finishes. A pause lets the saved copy of the conversation expire, '
              'which makes it rebuild and changes the cost.']
    answers = task_answers(task_dir)
    if answers:
        lines += ['7. If it asks a question, answer from this list (it is the same for every run):'] + [
            '   ' + line for line in answers]
    else:
        lines.append('7. If it asks a question, answer from task.md (experiments/tasks/%s/task.md).' % details['task'])
    lines += ['8. When it finishes, come back to the prompt-analyzer window and say: finish my run']
    return '\n'.join(lines)


def command_start(env, args, out):
    """kit start: make the run, copy the prompt, open VS Code, print the next steps."""
    details, prompt, task_dir = start_run(env, args.task, args.version, args.run, args.who)
    clipboard_ok = copy_to_clipboard(prompt)
    vscode_ok = open_in_vscode(details['folder'])
    print(next_steps(details, task_dir, clipboard_ok, vscode_ok, prompt), file=out)
    return 0


# ---------------------------------------------------------------- finish

def find_session(env, folder):
    """The one Claude Code session that ran in a run folder. Zero or many is a plain error: no guessing."""
    found = parse.sessions_for_cwd(str(folder), str(env.projects_root))
    name = paths.basename(str(folder))
    if not found:
        raise KitError('I cannot find a Claude Code session for %s. Check that you pasted the prompt and pressed Enter '
                       'in the VS Code window that opened that folder. If you did, say "check my setup".' % name)
    if len(found) > 1:
        raise KitError('I found %d Claude Code sessions for %s, and a run must be exactly one. I will not guess which '
                       'one to use. Do not delete anything: tell Adit.' % (len(found), name))
    return found[0]


def tool_error_count(session):
    """How many tool calls returned an error. Recorded in the results, but not a reason to flag the run."""
    return sum(1 for c in session['calls'] for t in c['tool_calls'] if t['is_error'])


def model_names(est):
    """The models a run used, as one text (most dollars first)."""
    return '; '.join(est['session']['models'])


def effort_names(session):
    """The effort levels the main thread ran at, as one text (most calls first), as the log records them
    (api-request output_config.effort). Empty when the log does not say."""
    counts = Counter(c['effort'] for c in session['calls'] if c['source'] == 'main' and c.get('effort'))
    return '; '.join(name for name, _ in counts.most_common())


def reference_run(runs, details):
    """The details of the first finished run of the same task, or None when this run is the first one."""
    same_task = [d for d in read_all_details(runs) if d['task'] == details['task'] and d['name'] != details['name']
                 and d.get('model')]
    if not same_task:
        return None
    first = same_task[0]
    mine = estimate.parse_time(details['started']) or LONG_AGO
    return first if (estimate.parse_time(first['started']) or LONG_AGO) < mine else None


def setting_flags(session, est, first):
    """Plain reasons when the model or effort differs from the first run of the same task."""
    reasons = []
    if not first:
        return reasons
    if first.get('model') and set(first['model'].split('; ')) != set(est['session']['models']):
        reasons.append('this run used a different model (%s) from the first run of this task (%s), so the cost is '
                       'not comparable' % (model_names(est), first['model']))
    mine = effort_names(session)
    if first.get('effort') and mine and set(first['effort'].split('; ')) != set(mine.split('; ')):
        reasons.append('this run used a different effort (%s) from the first run of this task (%s), so the cost is '
                       'not comparable' % (mine, first['effort']))
    elif first.get('effort') and not mine:
        reasons.append('the log does not say which effort this run used, so I cannot confirm it matches the first '
                       'run of this task (%s)' % first['effort'])
    return reasons


def session_flags(session, est, first=None):
    """The plain reasons a run needs a second look. Empty means nothing to check."""
    reasons = []
    if est['rebuilds']:
        reasons.append('the saved copy of the conversation was rebuilt %d time%s (usually after a pause), which '
                       'changes the cost' % (est['rebuilds'], '' if est['rebuilds'] == 1 else 's'))
    if session['compaction']['compacted']:
        reasons.append('the conversation was compacted (summarized to make room)')
    if session['warnings'].get('skipped_synthetic_or_error'):
        reasons.append('the log holds an API error or an interruption')
    main = [c for c in session['calls'] if c['source'] == 'main']
    if not main or main[-1]['stop_reason'] not in ('end_turn', 'stop_sequence'):
        reasons.append('the session did not finish (it did not end with a final answer)')
    if est['models_without_public_price']:
        reasons.append('some calls use a model with no public price, so the total is incomplete')
    return reasons + setting_flags(session, est, first)


def build_result(details, session, est, reasons):
    """The exact numbers of a finished run, as one CSV row (a dict)."""
    tokens = summarize.build_summary(session)['totals']['tokens']
    facts = est['session']
    started = estimate.parse_time(details['started'])
    return {
        'practice': 'yes' if details.get('practice') else 'no', 'task': details['task'],
        'version': details['version'], 'run': details['run'], 'who': details['who'],
        'model': model_names(est), 'effort': effort_names(session), 'date': started.date().isoformat() if started else '',
        'minutes': round(facts['duration_seconds'] / 60, 1), 'model_calls': facts['calls'],
        'tool_calls': facts['tool_calls'], 'tool_errors': tool_error_count(session), 'input_tokens': tokens['input'], 'cache_read_tokens': tokens['cache_read'],
        'cache_write_5m_tokens': tokens['cache_write_5m'], 'cache_write_1h_tokens': tokens['cache_write_1h'],
        'output_tokens': tokens['output'], 'total_usd_api_equivalent': '%.6f' % est['totals']['transcript_usd'],
        'cache_rebuilds': est['rebuilds'], 'compacted': 'yes' if session['compaction']['compacted'] else 'no',
        'check_this': 'yes' if reasons else 'no', 'check_reasons': '; '.join(reasons),
        'session_id': facts['session_id']}


def upsert_result(runs, row):
    """Add the row to results.csv, replacing an earlier row for the same task, version, and run."""
    path = runs / RESULTS_NAME
    rows = []
    if path.is_file():
        with open(str(path), newline='', encoding='utf-8') as handle:
            rows = [r for r in csv.DictReader(handle)
                    if (r.get('task'), r.get('version'), r.get('run')) != (row['task'], row['version'], str(row['run']))]
    rows.append({key: row[key] for key in CSV_COLUMNS})
    temp = path.with_name(path.name + '.tmp')
    with open(str(temp), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(str(temp), str(path))


def _build_receipt(env, details):
    """Find the run's session, build its receipt page, and write it next to the run. Returns the pieces."""
    runs = runs_folder(env)
    folder = runs / details['name']
    if not folder.is_dir():
        raise KitError('The run folder %s is missing, so I cannot find its session. Tell Adit; do not start it again.'
                       % details['name'])
    session_path = find_session(env, folder)
    try:
        session = parse.parse_session(session_path)
        est = estimate.build_estimate(session)
    except estimate.ReceiptError as error:
        raise KitError('I could not build the receipt: %s. Tell Adit.' % error)
    page = runs / (details['name'] + '.receipt.html')
    page.write_text(receipt.render(est), encoding='utf-8')
    return session, est, page


def _most_expensive(est):
    """Plain text for the most expensive step, or a line saying there is none."""
    priced = [s for s in est['steps'] if s['priced']]
    if not priced:
        return 'none (no step has a public price)'
    best = max(priced, key=lambda s: s['total_usd'])
    return 'step %d, %s, %s (estimated)' % (best['number'], best['description'], fmt.money(best['total_usd']))


def _largest_cause(est):
    """Plain text for the largest cause: the same one the receipt's headline sentence names (the starting
    context counts), not only the most expensive step."""
    found = est['findings']['headline']
    if not found:
        return 'none stands out'
    return '%s, %s of the total (estimated)' % (found['cause'], fmt.percent(found['numbers']['share']))


def pick_unfinished(runs):
    """The most recently started run that is not finished, or a plain error."""
    open_runs = [d for d in read_all_details(runs) if not d.get('finished')]
    if not open_runs:
        raise KitError('There is no unfinished run. Say "show the runs" to see them, or "start a run" to begin one.')
    return open_runs[-1]


def command_finish(env, args, out):
    """kit finish: build the receipt, record the row, flag anything odd, print four lines."""
    runs = runs_folder(env)
    details = find_run(runs, args.run_name) if args.run_name else pick_unfinished(runs)
    session, est, page = _build_receipt(env, details)
    reasons = session_flags(session, est, reference_run(runs, details))
    row = build_result(details, session, est, reasons)
    upsert_result(runs, row)
    details.update({'finished': now_text(), 'model': model_names(est), 'effort': effort_names(session),
                    'session_id': est['session']['session_id'],
                    'total_usd': est['totals']['transcript_usd'], 'check_this': bool(reasons),
                    'check_reasons': reasons})
    write_details(runs, details)
    if not args.no_open and not open_in_browser(page):
        print('I could not open the receipt in a browser. Open this file yourself.', file=out)
    if reasons:
        print('Check this run: %s.' % '; and '.join(reasons), file=out)
    print('Total: %s API-equivalent (exact tokens at public API prices)' % fmt.money(est['totals']['transcript_usd']), file=out)
    print('Largest cause: %s' % _largest_cause(est), file=out)
    print('Most expensive step: %s' % _most_expensive(est), file=out)
    print('Receipt: %s' % page, file=out)
    return 0


# ---------------------------------------------------------------- receipt, runs, update

def command_receipt(env, args, out):
    """kit receipt: open the receipt for a run, building it if needed."""
    runs = runs_folder(env)
    if args.run_name in (None, 'latest'):
        done = [d for d in read_all_details(runs) if d.get('finished')]
        if not done:
            raise KitError('There is no finished run yet. When a run is done, say "finish my run".')
        details = max(done, key=lambda d: estimate.parse_time(d['finished']) or LONG_AGO)
    else:
        details = find_run(runs, args.run_name)
    page = runs / (details['name'] + '.receipt.html')
    if not page.is_file():
        _, _, page = _build_receipt(env, details)
    if not args.no_open and not open_in_browser(page):
        print('I could not open the receipt in a browser. Open this file yourself.', file=out)
    print('Receipt: %s' % page, file=out)
    return 0


def prompt_for_run(env, details):
    """(prompt text, note) for a run. The text was saved at start; an older run falls back to the task's
    prompt file, with a note. It never comes from a session log."""
    if details.get('prompt'):
        return details['prompt'], None
    try:
        fallback = (task_folder(env, details['task']) / ('prompt-%s.md' % details['version'])).read_text(
            encoding='utf-8').rstrip('\r\n')
    except (KitError, OSError):
        raise KitError('I did not save the prompt of %s when it started, and the task file is missing, so I cannot '
                       'show it. Tell Adit.' % details['name'])
    return fallback, ('This run began before prompts were saved, so this is the prompt file of the task as it is now. '
                      'If someone edited it since, it may differ from what this run used.')


def command_prompt(env, args, out):
    """kit prompt: put a run's prompt back on the clipboard and print it. Default: the run started last."""
    runs = runs_folder(env)
    if args.run_name in (None, 'latest'):
        everything = read_all_details(runs)
        if not everything:
            raise KitError('No runs yet. To begin one, say "start a run".')
        details = everything[-1]
    else:
        details = find_run(runs, args.run_name)
    prompt, note = prompt_for_run(env, details)
    clipboard_ok = copy_to_clipboard(prompt)
    print('Prompt for %s (%s, %s version):' % (details['name'], details['task'], details['version']), file=out)
    print('----- START OF PROMPT -----', file=out)
    print(prompt, file=out)
    print('----- END OF PROMPT -----', file=out)
    if note:
        print(note, file=out)
    print('It is on your clipboard.' if clipboard_ok else
          'I could not reach the clipboard. Copy the prompt from between the two lines above.', file=out)
    return 0


def _table(rows):
    """Plain-text table: a list of rows, the first row being the header."""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    return '\n'.join('  '.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows)


def command_runs(env, args, out):
    """kit runs: list the runs so far."""
    details = read_all_details(runs_folder(env))
    if not details:
        print('No runs yet. To begin one, say "start a run".', file=out)
        return 0
    rows = [('Task', 'Version', 'Run', 'Who', 'Dollars (API-equivalent)', 'Flag')]
    notes = []
    for d in details:
        done = bool(d.get('finished'))
        flag = ('check this' if d.get('check_this') else 'ok') if done else 'not finished'
        flag += ' (practice)' if d.get('practice') else ''
        rows.append((d['task'], d['version'], d['run'], d['who'],
                     fmt.money(d['total_usd']) if done and d.get('total_usd') is not None else '-', flag))
        if d.get('check_this'):
            notes.append('%s: %s.' % (d['name'], '; '.join(d.get('check_reasons') or [])))
    print(_table(rows), file=out)
    for note in notes:
        print(note, file=out)
    return 0


def command_update(env, args, out):
    """kit update: pull the latest version of the tool. Stops if there are local changes. Never forces."""
    changed = git(env, 'status', '--porcelain', '--untracked-files=no')
    if changed is None:
        raise KitError('Git is not installed, or VS Code cannot find it, so I cannot update. Say "check my setup".')
    if changed[0] != 0:
        raise KitError('This folder is not a copy cloned from GitHub, so I cannot update it. Tell Adit.')
    if changed[1]:
        count = len(changed[1].splitlines())
        raise KitError('You have %d changed file%s in this folder, so I stopped and changed nothing. Tell Adit '
                       'before you update.' % (count, '' if count == 1 else 's'))
    pulled = git(env, 'pull', '--ff-only')
    if pulled[0] != 0:
        raise KitError('The update did not work and nothing was changed. Check your internet connection and that VS '
                       'Code is signed in to GitHub, then try again. If it keeps failing, tell Adit.')
    print('Already up to date.' if 'up to date' in pulled[1].lower() else 'Updated to the latest version.', file=out)
    return 0


# ---------------------------------------------------------------- check

def check_python():
    """(ok, text) for the Python version and the command name that works."""
    version = '%d.%d' % sys.version_info[:2]
    if sys.version_info[:2] < MIN_PYTHON:
        return False, 'Python %s is too old. Install Python %d.%d or newer from python.org, then say "check my setup" again.' % (
            version, MIN_PYTHON[0], MIN_PYTHON[1])
    name = python_command_name()
    if name is None:
        return True, 'Python %s works. I could not tell which command name runs it on this machine (python3, python, or py).' % version
    return True, 'Python %s works. The command name on this machine is: %s' % (version, name)


def check_sessions(env):
    """(ok, text) for whether Claude Code session logs exist."""
    found = len(parse.list_sessions(str(env.projects_root)))
    if not found:
        return False, ('No Claude Code sessions found. The tool reads Claude Code only. If you use ChatGPT or Codex '
                       'for this class, tell Adit.')
    return True, 'Found %d Claude Code session%s on this machine.' % (found, '' if found == 1 else 's')


def check_git(env):
    """(ok, text) for whether this copy of the tool is up to date with GitHub."""
    inside = git(env, 'rev-parse', '--is-inside-work-tree')
    if inside is None:
        return False, ('Git is not installed, or VS Code cannot find it. Install Git from git-scm.com, restart '
                       'VS Code, then say "check my setup" again.')
    if inside[0] != 0:
        return False, 'This folder is not a copy cloned from GitHub, so I cannot check for updates. Tell Adit.'
    if git(env, 'fetch', '--quiet')[0] != 0:
        return False, ('I could not reach GitHub. Check your internet connection and that VS Code is signed in to '
                       'GitHub, then say "check my setup" again.')
    behind = git(env, 'rev-list', '--count', 'HEAD..@{upstream}')
    if behind[0] != 0 or not behind[1].isdigit():
        return False, 'This copy is not linked to a branch on GitHub, so I cannot tell if it is current. Tell Adit.'
    if int(behind[1]) > 0:
        return False, 'Your copy is %s update%s behind GitHub. Say "update the tool" to get them.' % (
            behind[1], '' if behind[1] == '1' else 's')
    return True, 'The tool is up to date with GitHub.'


def check_runs_folder(env):
    """(ok, text) for whether the runs folder exists or can be made."""
    runs = runs_folder(env)
    try:
        runs.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, ('I cannot make the runs folder %s. Tell Adit; the runs folder can be moved in %s.'
                       % (runs, SETTINGS_NAME))
    if not os.access(str(runs), os.W_OK):
        return False, 'I cannot write to the runs folder %s. Tell Adit.' % runs
    return True, 'The runs folder is ready: %s' % runs


INSTRUCTION_FILES = ('CLAUDE.md', 'CLAUDE.local.md', 'AGENTS.md', os.path.join('.claude', 'CLAUDE.md'))


def check_parents(env):
    """(ok, text) for whether an instruction file sits above the runs folder (it would change every run)."""
    runs = runs_folder(env)
    for folder in [runs] + list(runs.parents):
        for name in INSTRUCTION_FILES:
            found = folder / name
            if found.is_file():
                return False, ('The file %s sits above the runs folder. Claude Code reads it in every run, which adds '
                               'text to the prompt and changes the cost. Tell Adit; the runs folder needs to move, or '
                               'the file does.' % found)
    return True, 'No CLAUDE.md or AGENTS.md sits above the runs folder.'


def check_demo():
    """(ok, text) for whether the receipt builds on the made-up demo session."""
    import tempfile
    try:
        from tests.make_demo_session import write_demo_session
        with tempfile.TemporaryDirectory() as folder:
            receipt.render(receipt.build(write_demo_session(folder)))
    except ImportError:
        return False, 'Part of the tool is missing from this folder. Say "update the tool", then "check my setup".'
    except Exception:  # any failure here means the tool is broken on this machine
        return False, 'The receipt did not build on the demo. Tell Adit.'
    return True, 'The receipt builds on the demo.'


def command_check(env, args, out):
    """kit check: one line per item, then Ready or Not ready."""
    results = [check_python(), check_sessions(env), check_git(env), check_runs_folder(env), check_parents(env),
               check_demo()]
    for ok, text in results:
        print(('OK: ' if ok else 'FIX: ') + text, file=out)
    ready = all(ok for ok, _ in results)
    print('Ready to run' if ready else 'Not ready: fix the items above', file=out)
    return 0 if ready else 1


# ---------------------------------------------------------------- command line

class PlainParser(argparse.ArgumentParser):
    """An argument parser whose errors are one plain sentence, not a usage dump."""

    def error(self, message):
        raise KitError('I did not understand that (%s). Try saying what you want in a sentence, for example '
                       '"check my setup" or "start a run".' % message)


def make_parser():
    """The command line: check, start, finish, receipt, prompt, runs, update."""
    parser = PlainParser(prog='python3 -m src.kit', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True, parser_class=PlainParser)
    commands.add_parser('check', help='check that everything is ready')
    start = commands.add_parser('start', help='start a run')
    start.add_argument('task')
    start.add_argument('version')
    start.add_argument('--run', type=int)
    start.add_argument('--who')
    finish = commands.add_parser('finish', help='finish a run')
    finish.add_argument('run_name', nargs='?')
    finish.add_argument('--no-open', action='store_true')
    show = commands.add_parser('receipt', help='open a receipt')
    show.add_argument('run_name', nargs='?')
    show.add_argument('--no-open', action='store_true')
    again = commands.add_parser('prompt', help='show a run\'s prompt again')
    again.add_argument('run_name', nargs='?')
    commands.add_parser('runs', help='list the runs')
    commands.add_parser('update', help='get the latest version of the tool')
    return parser


COMMANDS = {'check': command_check, 'start': command_start, 'finish': command_finish,
            'receipt': command_receipt, 'prompt': command_prompt, 'runs': command_runs, 'update': command_update}


def inside_runs_folder(env, cwd):
    """True when the command was run from inside the runs folder (a run window, not this one)."""
    runs = runs_folder(env).resolve()
    here = Path(cwd).resolve()
    return here == runs or runs in here.parents


def main(argv=None, out=None, env=None, cwd=None):
    """Run one kit command. Returns the exit code. Never prints a stack trace."""
    out = out or sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(errors='replace')  # an odd character in a Windows user name must not stop the kit
    env = env or Env()
    try:
        args = make_parser().parse_args(argv)
        if args.command != 'check' and inside_runs_folder(env, cwd or Path.cwd()):
            raise KitError(GO_BACK)
        return COMMANDS[args.command](env, args, out)
    except KitError as error:
        print(str(error), file=out)
        return 2
    except Exception as error:  # the teammate never sees a stack trace
        print('Something unexpected went wrong (%s). Say "check my setup". If it keeps happening, take a screenshot '
              'and text Adit.' % type(error).__name__, file=out)
        return 2


if __name__ == '__main__':
    sys.exit(main())
