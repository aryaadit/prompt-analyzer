"""The teammate kit: setup check, run starter, run finisher, receipts, the run list, and sharing.

    python3 -m src.kit check
    python3 -m src.kit start <task> <original|lean> [--run N] [--who NAME]
    python3 -m src.kit finish [<run folder name>]
    python3 -m src.kit receipt [latest | <run folder name>] [--export]
    python3 -m src.kit prompt [latest | <run folder name>]
    python3 -m src.kit runs
    python3 -m src.kit share
    python3 -m src.kit update

Everything printed is plain words. A problem says what happened and what to do next, in a
sentence or two, never a stack trace.

Where things live. A run happens in a scratch folder OUTSIDE the repo (default:
prompt-analyzer-scratch in the home folder), because Claude Code reads instruction files from
parent folders, and a run inside this repo would carry this project's rules and change its cost.
Everything else lives in results/ in the repo, which is committed: results/<who>.csv (one file
per person), results/receipts/, results/outputs/<run>/ (what the agent made), and
results/run-details/<run>.json. results/ holds made-up task inputs only, never session logs.
A run is named <task>-<version>-<n>-<who>, for example sample-lean-1-anna (who in lower case), so two people can
never take the same name. A receipt in results/receipts/ loads the chart library from ../../vendor/; the receipt
command with --export makes a self-contained copy for sharing outside the repo.
Works on Mac and Windows: paths are pathlib, and nothing assumes the Python command is called python3.
"""
import argparse
import csv
import filecmp
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

from . import estimate, fmt, page as pagelib, parse, paths, receipt, summarize

REPO = Path(__file__).resolve().parent.parent
SETTINGS_NAME = 'local-settings.json'  # gitignored; holds scratch_folder and who
DEFAULT_SCRATCH_NAME = 'prompt-analyzer-scratch'
EXPORTS_DIR = 'exports'  # inside the scratch folder: standalone copies of receipts, never committed
RESULTS_DIR = 'results'  # inside the repo, committed
RECEIPTS_DIR, OUTPUTS_DIR = 'receipts', 'outputs'
MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # a file the agent made that is bigger than this is not copied
SKIP_OUTPUT_DIRS = ('.git', '.claude', 'node_modules', '__pycache__')  # tooling, not something the agent made
MIN_PYTHON = (3, 9)
VERSIONS = ('original', 'lean')
DETAILS_DIR = 'run-details'
LONG_AGO = datetime(1970, 1, 1, tzinfo=timezone.utc)
JUNK_FILES = ('.DS_Store', '.gitkeep', 'Thumbs.db')
_SLUG = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_WHO = re.compile(r'^[A-Za-z]+$')
_RUN_NAME = re.compile(r'^(?P<task>[a-z0-9][a-z0-9-]*)-(?P<version>original|lean)-(?P<run>\d+)-(?P<who>[a-z]+)$')
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
        self.results = self.repo / RESULTS_DIR


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


def scratch_folder(env):
    """The working folder where runs happen, outside the repo: from the settings file, else
    prompt-analyzer-scratch in the home folder."""
    settings = load_settings(env)
    chosen = settings.get('scratch_folder') or settings.get('runs_folder')  # runs_folder: the old setting name
    folder = Path(chosen).expanduser() if chosen else env.home / DEFAULT_SCRATCH_NAME
    if not folder.is_absolute():
        raise KitError('The scratch folder in %s must be a full path, such as one starting with / or C:\\. Tell Adit.'
                       % env.settings_path.name)
    return folder


def results_csv(env, who):
    """The results file of one person: results/<first name in lower case>.csv (lower case so that Adit and adit
    cannot become two files on a Mac or Windows machine)."""
    return env.results / (who.lower() + '.csv')


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


def run_name(task, version, number, who):
    """The folder name of one run: task, version, number, and the person (lower case)."""
    return '%s-%s-%d-%s' % (task, version, number, who.lower())


def _read_details_in(base):
    """The details records saved under base/run-details, in no particular order. Damaged files are skipped."""
    folder = base / DETAILS_DIR
    found = []
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and _RUN_NAME.match(str(data.get('name'))):  # the name becomes a file name
            found.append(data)
    return found


def read_all_details(env):
    """Every run's details record, oldest start first: runs in progress (scratch folder) and finished runs of
    everyone (results/run-details). When a run is in both places, the finished record in results/ wins."""
    found = {d['name']: d for d in _read_details_in(scratch_folder(env))}
    found.update({d['name']: d for d in _read_details_in(env.results)})
    return sorted(found.values(), key=lambda d: estimate.parse_time(d.get('started')) or LONG_AGO)


def my_details(env):
    """read_all_details, but only the runs of the person using this laptop (when their name is known)."""
    who = (load_settings(env).get('who') or '').strip().lower()
    return [d for d in read_all_details(env) if not who or str(d.get('who', '')).lower() == who]


def write_details(base, details):
    """Save one run's details record under base/run-details."""
    folder = base / DETAILS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    _atomic_write(folder / (details['name'] + '.json'), json.dumps(details, indent=2) + '\n')


def public_details(details):
    """The details record that goes into results/: without the path of the scratch folder on this laptop."""
    return {key: value for key, value in details.items() if key != 'folder'}


def read_all_rows(env):
    """Every row of every person's results file in results/, oldest date first. Damaged files are skipped."""
    rows = []
    for path in sorted(env.results.glob('*.csv')) if env.results.is_dir() else []:
        try:
            with open(str(path), newline='', encoding='utf-8') as handle:
                rows += [r for r in csv.DictReader(handle) if r.get('task') and r.get('version')]
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: (r.get('date') or '', r['task'], r['version'], int(r['run']) if str(r.get('run')).isdigit() else 0))
    return rows


def used_names(env):
    """Every run name already taken: a folder or details file in the scratch folder, or a run in results/."""
    scratch = scratch_folder(env)
    names = {p.name for p in scratch.iterdir()} if scratch.is_dir() else set()
    names |= {d['name'] for d in read_all_details(env)}
    names |= {'%s-%s-%s-%s' % (r['task'], r['version'], r['run'], r.get('who', '').lower()) for r in read_all_rows(env)}
    return names


def next_run_number(env, task, version, who):
    """The next free run number for a task, version, and person (folders, details files, and results all count)."""
    used = set()
    for name in used_names(env):
        match = _RUN_NAME.match(name)
        if match and (match.group('task'), match.group('version'), match.group('who')) == (task, version, who.lower()):
            used.add(int(match.group('run')))
    return max(used, default=0) + 1


def find_run(env, name):
    """The details record for a run folder name, or a plain error."""
    for details in read_all_details(env):
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
    if not _WHO.match(who):
        raise KitError('Your first name must be letters only, with no spaces, for example: --who Anna.')
    scratch = scratch_folder(env)
    number = run if run is not None else next_run_number(env, task, version, who)
    if number < 1:
        raise KitError('The run number must be 1 or higher.')
    name = run_name(task, version, number, who)
    if name in used_names(env):
        raise KitError('The run %s already exists, so I did not touch it. Never reuse a run folder: it still '
                       'holds the earlier run. Start again without --run to use the next free number, which is %d.'
                       % (name, next_run_number(env, task, version, who)))
    prompt = (task_dir / ('prompt-%s.md' % version)).read_text(encoding='utf-8').rstrip('\r\n')
    _copy_start_files(task_dir / 'start', scratch / name)
    details = {'name': name, 'task': task, 'version': version, 'run': number, 'who': who,
               'started': now_text(), 'finished': None, 'practice': is_practice(task_dir),
               'folder': str(scratch / name), 'prompt': prompt}
    write_details(scratch, details)
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
    lines += ['8. When it finishes, come back to the prompt-analyzer window and say: finish my run',
              '9. Then say: share my results']
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


def reference_run(env, details):
    """The details of the first finished run of the same task, or None when this run is the first one."""
    same_task = [d for d in read_all_details(env) if d['task'] == details['task'] and d['name'] != details['name']
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


def upsert_result(env, row):
    """Add the row to the person's results file (results/<who>.csv), replacing an earlier row for the same task,
    version, and run."""
    path = results_csv(env, row['who'])
    path.parent.mkdir(parents=True, exist_ok=True)
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


def receipt_path(env, name):
    """Where a run's receipt page is kept: results/receipts/<run>.receipt.html."""
    return env.results / RECEIPTS_DIR / (name + '.receipt.html')


def _build_receipt(env, details):
    """Find the run's session, build its receipt page, and write it into results/receipts. Returns the pieces."""
    folder = scratch_folder(env) / details['name']
    if not folder.is_dir():
        raise KitError('The run folder %s is missing from the scratch folder, so I cannot find its session. Tell Adit; '
                       'do not start it again.' % details['name'])
    session_path = find_session(env, folder)
    try:
        session = parse.parse_session(session_path)
        est = estimate.build_estimate(session)
    except estimate.ReceiptError as error:
        raise KitError('I could not build the receipt: %s. Tell Adit.' % error)
    page = receipt_path(env, details['name'])
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(receipt.render(est, library='linked'), encoding='utf-8')  # the library is read from vendor/
    return session, est, page


def find_outputs(start_dir, run_dir):
    """What the agent made in a run folder. Returns (paths to copy, notes about files left out). A path is
    relative to the run folder. Files that are unchanged from the task's start files are not outputs. Tooling
    folders, junk files, links, and files over 5 MB are left out (the big ones are named in the notes)."""
    copy, notes = [], []
    for here, folders, files in os.walk(str(run_dir)):  # os.walk does not follow links to folders
        folders[:] = sorted(f for f in folders if f not in SKIP_OUTPUT_DIRS and not os.path.islink(os.path.join(here, f)))
        for name in sorted(files):
            path = Path(here) / name
            relative = path.relative_to(run_dir)
            if name in JUNK_FILES or path.is_symlink():
                continue
            original = start_dir / relative
            if original.is_file() and filecmp.cmp(str(original), str(path), shallow=False):
                continue
            size = path.stat().st_size
            if size > MAX_OUTPUT_BYTES:
                notes.append('Skipped %s: it is %.1f MB, over the 5 MB limit.' % (relative.as_posix(), size / 1048576))
                continue
            copy.append(relative)
    return copy, notes


def copy_outputs(env, details, run_dir, task_dir=None):
    """Copy what the run made into results/outputs/<run>/. Returns (number of files copied, notes)."""
    try:
        task_dir = task_dir or task_folder(env, details['task'])
        start_dir = task_dir / 'start'
    except KitError:
        start_dir = Path(os.devnull)  # the task is gone, so every file counts as made by the run
    copy, notes = find_outputs(start_dir, run_dir)
    target = env.results / OUTPUTS_DIR / details['name']
    done = 0
    for relative in copy:
        try:
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(run_dir / relative), str(target / relative))
            done += 1
        except OSError:
            notes.append('Could not copy %s.' % relative.as_posix())
    return done, notes


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


def pick_unfinished(env):
    """The most recently started run of this laptop that is not finished, or a plain error."""
    done = {d['name'] for d in _read_details_in(env.results)}
    open_runs = [d for d in _read_details_in(scratch_folder(env)) if not d.get('finished') and d['name'] not in done]
    open_runs.sort(key=lambda d: estimate.parse_time(d.get('started')) or LONG_AGO)
    if not open_runs:
        raise KitError('There is no unfinished run. Say "show the runs" to see them, or "start a run" to begin one.')
    return open_runs[-1]


def command_finish(env, args, out):
    """kit finish: build the receipt, copy what the run made, record the row, flag anything odd, print the result."""
    scratch = scratch_folder(env)
    details = find_run(env, args.run_name) if args.run_name else pick_unfinished(env)
    session, est, page = _build_receipt(env, details)
    reasons = session_flags(session, est, reference_run(env, details))
    row = build_result(details, session, est, reasons)
    copied, notes = copy_outputs(env, details, scratch / details['name'])
    upsert_result(env, row)
    details.update({'finished': now_text(), 'model': model_names(est), 'effort': effort_names(session),
                    'session_id': est['session']['session_id'],
                    'total_usd': est['totals']['transcript_usd'], 'check_this': bool(reasons),
                    'check_reasons': reasons})
    write_details(env.results, public_details(details))
    write_details(scratch, details)
    if not args.no_open and not open_in_browser(page):
        print('I could not open the receipt in a browser. Open this file yourself.', file=out)
    if reasons:
        print('Check this run: %s.' % '; and '.join(reasons), file=out)
    print('Total: %s API-equivalent (exact tokens at public API prices)' % fmt.money(est['totals']['transcript_usd']), file=out)
    print('Largest cause: %s' % _largest_cause(est), file=out)
    print('Most expensive step: %s' % _most_expensive(est), file=out)
    print('Receipt: %s' % page, file=out)
    print(('Outputs: %d file%s copied to %s' % (copied, '' if copied == 1 else 's', env.results / OUTPUTS_DIR / details['name']))
          if copied else 'Outputs: the run made no new files, so nothing was copied.', file=out)
    for note in notes:
        print(note, file=out)
    print('Results: row saved in %s' % results_csv(env, details['who']), file=out)
    print('Everything from this run is now in %s, so the scratch folder %s can be cleared. I deleted nothing.'
          % (env.results, scratch), file=out)
    print('Last step: say "share my results" to send this to the group.', file=out)
    return 0


# ---------------------------------------------------------------- receipt, runs, update

def export_receipt(env, name, page):
    """Write a standalone copy of a receipt (the chart library inside it) to exports/ in the scratch folder, which is
    outside the repo, and return its path."""
    target = scratch_folder(env) / EXPORTS_DIR / (name + '.receipt.html')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(pagelib.standalone(page.read_text(encoding='utf-8')), encoding='utf-8')
    except pagelib.PageError as error:
        raise KitError('I could not make a standalone copy: %s. Tell Adit.' % error)
    return target


def command_receipt(env, args, out):
    """kit receipt: open the receipt for a run, building it if needed."""
    if args.run_name in (None, 'latest'):
        done = [d for d in my_details(env) if d.get('finished')]
        if not done:
            raise KitError('There is no finished run yet. When a run is done, say "finish my run".')
        details = max(done, key=lambda d: estimate.parse_time(d['finished']) or LONG_AGO)
    else:
        details = find_run(env, args.run_name)
    page = receipt_path(env, details['name'])
    if not page.is_file():
        _, _, page = _build_receipt(env, details)
    if args.export:
        page = export_receipt(env, details['name'], page)
    if not args.no_open and not open_in_browser(page):
        print('I could not open the receipt in a browser. Open this file yourself.', file=out)
    if args.export:
        print('Standalone receipt: %s' % page, file=out)
        print('This copy has the charts inside it, so it works anywhere, even when sent by email. It is outside the '
              'project and is not committed.', file=out)
    else:
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
    if args.run_name in (None, 'latest'):
        everything = my_details(env)
        if not everything:
            raise KitError('No runs yet. To begin one, say "start a run".')
        details = everything[-1]
    else:
        details = find_run(env, args.run_name)
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


def _dollars(text):
    """A dollar figure from a results cell, or a dash when the cell is empty or damaged."""
    try:
        return fmt.money(float(text))
    except (TypeError, ValueError):
        return '-'


def command_runs(env, args, out):
    """kit runs: list the runs so far. Finished runs of everyone come from every results/<who>.csv; runs
    started on this laptop and not finished come from the scratch folder."""
    rows = read_all_rows(env)
    finished = {'%s-%s-%s-%s' % (r['task'], r['version'], r['run'], r.get('who', '').lower()) for r in rows}
    waiting = [d for d in _read_details_in(scratch_folder(env)) if not d.get('finished') and d['name'] not in finished]
    waiting.sort(key=lambda d: estimate.parse_time(d.get('started')) or LONG_AGO)
    if not rows and not waiting:
        print('No runs yet. To begin one, say "start a run".', file=out)
        return 0
    table = [('Task', 'Version', 'Run', 'Who', 'Dollars (API-equivalent)', 'Flag')]
    notes = []
    for r in rows:
        flag = 'check this' if r.get('check_this') == 'yes' else 'ok'
        table.append((r['task'], r['version'], r['run'], r.get('who', ''), _dollars(r.get('total_usd_api_equivalent')),
                      flag + (' (practice)' if r.get('practice') == 'yes' else '')))
        if r.get('check_this') == 'yes':
            notes.append('%s-%s-%s-%s: %s.' % (r['task'], r['version'], r['run'], r.get('who', '').lower(),
                                               r.get('check_reasons', '')))
    for d in waiting:
        table.append((d['task'], d['version'], d['run'], d['who'], '-',
                      'not finished' + (' (practice)' if d.get('practice') else '')))
    print(_table(table), file=out)
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


# ---------------------------------------------------------------- share

def _git_lines(env, *args):
    """The lines git printed for a command, or None when git is missing or the command failed."""
    done = git(env, '-c', 'core.quotepath=off', *args)
    return done[1].splitlines() if done is not None and done[0] == 0 else None


def changed_outside_results(env):
    """Paths with changes outside results/ (tracked, staged, or new and not ignored). None when git cannot say."""
    tracked = _git_lines(env, 'diff', '--name-only', 'HEAD')
    new = _git_lines(env, 'ls-files', '--others', '--exclude-standard')
    if tracked is None or new is None:
        return None
    return sorted({path for path in tracked + new if path and not path.startswith(RESULTS_DIR + '/')})


def command_share(env, args, out):
    """kit share: commit results/ and nothing else, pull with rebase, push. Stops if anything else changed."""
    who = (load_settings(env).get('who') or '').strip()
    if not who:
        raise KitError('I do not know your first name yet. Start a run once so I can save it, or tell Adit.')
    if git(env, 'rev-parse', '--is-inside-work-tree') is None:
        raise KitError('Git is not installed, or VS Code cannot find it, so I cannot share. Say "check my setup".')
    outside = changed_outside_results(env)
    if outside is None:
        raise KitError('This folder is not a copy cloned from GitHub, or git could not read it, so I cannot share. '
                       'Tell Adit.')
    if outside:
        shown = ', '.join(outside[:3]) + (' and %d more' % (len(outside) - 3) if len(outside) > 3 else '')
        raise KitError('You have %d changed file%s outside the results folder (%s). Sharing sends results only, so I '
                       'stopped and changed nothing. Tell Adit before you share.'
                       % (len(outside), '' if len(outside) == 1 else 's', shown))
    ahead = git(env, 'rev-list', '--count', '@{upstream}..HEAD')
    if ahead[0] != 0 or not ahead[1].isdigit():
        raise KitError('This copy is not linked to a branch on GitHub, so I cannot share. Tell Adit.')
    staged = []
    if env.results.is_dir():
        if git(env, 'add', RESULTS_DIR + '/')[0] != 0:
            raise KitError('Git could not add the results folder, so I stopped. Tell Adit.')
        staged = _git_lines(env, 'diff', '--cached', '--name-only') or []
    if not staged and ahead[1] == '0':
        print('Nothing new to share. Finish a run first, then say "share my results".', file=out)
        return 0
    message = None
    if staged:
        names = sorted({m.group(1) for m in (re.match(r'^results/run-details/(.+)\.json$', p) for p in staged) if m})
        message = 'Results: %s, %s' % (who, ', '.join(names) or 'results')
        if git(env, 'commit', '-m', message)[0] != 0:
            raise KitError('Git could not save your results as a commit. If it needs your name and email, tell Adit. '
                           'Nothing was sent.')
    if git(env, 'pull', '--rebase')[0] != 0:
        git(env, 'rebase', '--abort')  # leave no half-finished rebase behind
        raise KitError('Getting the latest from GitHub did not work, so I stopped before sending anything. Your '
                       'results are saved on this laptop and nothing was lost. Check your internet connection, then '
                       'say "share my results" again. If it keeps failing, tell Adit.')
    if git(env, 'push')[0] != 0:
        raise KitError('Sending to GitHub did not work. Your results are saved on this laptop and nothing was lost. '
                       'Check your internet connection and that VS Code is signed in to GitHub, then say "share my '
                       'results" again. If it keeps failing, tell Adit.')
    print('Shared with the group: %s' % message if message else 'Shared your earlier saved results with the group.',
          file=out)
    if staged:
        print('%d file%s from results/ sent to GitHub.' % (len(staged), '' if len(staged) == 1 else 's'), file=out)
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


def check_scratch_folder(env):
    """(ok, text) for whether the scratch folder exists or can be made."""
    scratch = scratch_folder(env)
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, ('I cannot make the scratch folder %s. Tell Adit; the scratch folder can be moved in %s.'
                       % (scratch, SETTINGS_NAME))
    if not os.access(str(scratch), os.W_OK):
        return False, 'I cannot write to the scratch folder %s. Tell Adit.' % scratch
    return True, 'The scratch folder is ready: %s' % scratch


INSTRUCTION_FILES = ('CLAUDE.md', 'CLAUDE.local.md', 'AGENTS.md', os.path.join('.claude', 'CLAUDE.md'))


def check_parents(env):
    """(ok, text) for whether an instruction file sits above the scratch folder (it would change every run)."""
    scratch = scratch_folder(env)
    for folder in [scratch] + list(scratch.parents):
        for name in INSTRUCTION_FILES:
            found = folder / name
            if found.is_file():
                return False, ('The file %s sits above the scratch folder. Claude Code reads it in every run, which adds '
                               'text to the prompt and changes the cost. Tell Adit; the scratch folder needs to move, or '
                               'the file does.' % found)
    return True, 'No CLAUDE.md or AGENTS.md sits above the scratch folder.'


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
    results = [check_python(), check_sessions(env), check_git(env), check_scratch_folder(env), check_parents(env),
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
    """The command line: check, start, finish, receipt, prompt, runs, share, update."""
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
    show.add_argument('--export', action='store_true', help='make a standalone copy to share outside the project')
    again = commands.add_parser('prompt', help='show a run\'s prompt again')
    again.add_argument('run_name', nargs='?')
    commands.add_parser('runs', help='list the runs')
    commands.add_parser('share', help='send your results to the group')
    commands.add_parser('update', help='get the latest version of the tool')
    return parser


COMMANDS = {'check': command_check, 'start': command_start, 'finish': command_finish,
            'receipt': command_receipt, 'prompt': command_prompt, 'runs': command_runs, 'share': command_share,
            'update': command_update}


def inside_scratch_folder(env, cwd):
    """True when the command was run from inside the scratch folder (a run window, not this one)."""
    scratch = scratch_folder(env).resolve()
    here = Path(cwd).resolve()
    return here == scratch or scratch in here.parents


def main(argv=None, out=None, env=None, cwd=None):
    """Run one kit command. Returns the exit code. Never prints a stack trace."""
    out = out or sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(errors='replace')  # an odd character in a Windows user name must not stop the kit
    env = env or Env()
    try:
        args = make_parser().parse_args(argv)
        if args.command != 'check' and inside_scratch_folder(env, cwd or Path.cwd()):
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
