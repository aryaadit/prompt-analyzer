"""Tests for src/kit.py and the Windows-path handling. No test opens a window, a browser, or the clipboard,
runs a command, or spends model usage. Every session here is an invented fixture."""
import csv
import html
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import kit, parse, paths, receipt
from tests.helpers import SESSION_3
from tests.make_demo_session import write_demo_session

REPO_SAMPLE = Path(kit.REPO) / 'experiments' / 'tasks' / 'sample'
WINDOWS_CWD = 'C:\\Users\\Anna\\prompt-analyzer-runs\\sample-lean-1'
WINDOWS_FOLDER = 'C--Users-Anna-prompt-analyzer-runs-sample-lean-1'


class KitCase(unittest.TestCase):
    """A fake home and a fake repo in a temp folder, with every outside action replaced by a mock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.home, self.repo = base / 'home', base / 'repo'
        self.home.mkdir()
        shutil.copytree(str(REPO_SAMPLE), str(self.repo / 'experiments' / 'tasks' / 'sample'))
        self.env = kit.Env(home=self.home, repo=self.repo)
        self.runs = self.home / kit.DEFAULT_RUNS_NAME
        patches = {
            'clipboard': mock.patch.object(kit, 'copy_to_clipboard', return_value=True),
            'vscode': mock.patch.object(kit, 'open_in_vscode', return_value=True),
            'browser': mock.patch.object(kit, 'open_in_browser', return_value=True),
            'python': mock.patch.object(kit, 'python_command_name', return_value='python3'),
            'git': mock.patch.object(kit, 'git', return_value=(0, '0')),
            'webbrowser': mock.patch('webbrowser.open', return_value=True),
            'run': mock.patch('subprocess.run', side_effect=AssertionError('tests must not run commands')),
        }
        self.mocks = {name: patch.start() for name, patch in patches.items()}
        for patch in patches.values():
            self.addCleanup(patch.stop)

    def say(self, *argv):
        """Run one kit command. Returns (exit code, printed text)."""
        out = io.StringIO()
        code = kit.main(list(argv), out=out, env=self.env, cwd=self.repo)
        return code, out.getvalue()

    def put_session(self, cwd, source, name=None):
        """Place a session file (and any subagent folder next to it) where Claude Code would have saved it."""
        folder = self.home / '.claude' / 'projects' / parse.encode_cwd(str(cwd))
        folder.mkdir(parents=True, exist_ok=True)
        source = Path(source)
        shutil.copy(str(source), str(folder / (name or source.name)))
        sub = source.parent / source.stem
        if sub.is_dir():
            shutil.copytree(str(sub), str(folder / source.stem), dirs_exist_ok=True)
        return folder / (name or source.name)

    def start(self, version='lean', who='Anna'):
        """Start a run through the real command and return its folder."""
        code, text = self.say('start', 'sample', version, '--who', who)
        self.assertEqual(code, 0, text)
        return sorted(self.runs.glob('sample-%s-*' % version))[-1]

    def results(self):
        with open(str(self.runs / kit.RESULTS_NAME), newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def edited_copy(self, name, change):
        """A copy of the clean fixture session, changed by a function on its list of lines."""
        lines = Path(SESSION_3).read_text(encoding='utf-8').splitlines()
        target = Path(self.tmp.name) / 'edits' / name
        target.parent.mkdir(exist_ok=True)
        target.write_text('\n'.join(change(lines)) + '\n', encoding='utf-8')
        return target


# ---------------------------------------------------------------- check

class CheckTest(KitCase):
    def make_session(self):
        self.put_session('/work/demo', SESSION_3)

    def test_with_sessions_everything_is_ok_and_no_file_names_are_printed(self):
        self.make_session()
        code, text = self.say('check')
        self.assertEqual(code, 0, text)
        self.assertIn('Found 1 Claude Code session on this machine.', text)
        self.assertTrue(text.rstrip().endswith('Ready to run'))
        self.assertNotIn('sess-0003', text)
        self.assertTrue(all(line.startswith(('OK: ', 'FIX: ')) or line == 'Ready to run' for line in text.splitlines()))
        self.assertTrue(self.runs.is_dir())  # the runs folder was made

    def test_with_no_sessions_it_says_so_in_the_exact_words(self):
        code, text = self.say('check')
        self.assertEqual(code, 1)
        self.assertIn('FIX: No Claude Code sessions found. The tool reads Claude Code only. If you use ChatGPT or Codex '
                      'for this class, tell Adit.', text)
        self.assertTrue(text.rstrip().endswith('Not ready: fix the items above'))

    def test_a_claude_md_above_the_runs_folder_is_named(self):
        self.make_session()
        (self.home / 'CLAUDE.md').write_text('invented', encoding='utf-8')
        code, text = self.say('check')
        self.assertEqual(code, 1)
        self.assertIn(str(self.home / 'CLAUDE.md'), text)
        self.assertIn('changes the cost', text)
        self.assertIn('Not ready', text)

    def test_an_agents_md_in_a_higher_parent_is_found_too(self):
        self.make_session()
        (self.home.parent / 'AGENTS.md').write_text('invented', encoding='utf-8')
        code, text = self.say('check')
        self.assertEqual(code, 1)
        self.assertIn(str(self.home.parent / 'AGENTS.md'), text)

    def test_a_custom_runs_folder_is_used_and_checked(self):
        self.make_session()
        elsewhere = self.home / 'elsewhere' / 'my-runs'
        self.env.settings_path.write_text(json.dumps({'runs_folder': str(elsewhere)}), encoding='utf-8')
        code, text = self.say('check')
        self.assertEqual(code, 0, text)
        self.assertTrue(elsewhere.is_dir())
        self.assertIn(str(elsewhere), text)

    def test_behind_github_says_how_to_update(self):
        self.make_session()
        self.mocks['git'].side_effect = lambda env, *args, **kw: (0, '3') if args[0] == 'rev-list' else (0, '')
        code, text = self.say('check')
        self.assertEqual(code, 1)
        self.assertIn('Your copy is 3 updates behind GitHub. Say "update the tool"', text)

    def test_no_git_and_no_internet_give_plain_fixes(self):
        self.make_session()
        self.mocks['git'].return_value = None
        _, text = self.say('check')
        self.assertIn('Git is not installed', text)
        self.mocks['git'].return_value = (1, '')
        self.mocks['git'].side_effect = lambda env, *args, **kw: (0, 'true') if args[0] == 'rev-parse' else (1, '')
        _, text = self.say('check')
        self.assertIn('could not reach GitHub', text)

    def test_an_old_python_is_a_fix(self):
        self.make_session()
        with mock.patch.object(kit.sys, 'version_info', (3, 6, 0, 'final', 0)):
            code, text = self.say('check')
        self.assertEqual(code, 1)
        self.assertIn('Python 3.6 is too old', text)


# ---------------------------------------------------------------- start

class StartTest(KitCase):
    def test_run_numbers_count_up_per_task_and_version(self):
        self.assertEqual(self.start('lean').name, 'sample-lean-1')
        self.assertEqual(self.start('lean').name, 'sample-lean-2')
        self.assertEqual(self.start('original').name, 'sample-original-1')

    def test_a_folder_that_exists_is_never_reused(self):
        folder = self.start('lean')
        (folder / 'agent-output.txt').write_text('earlier run', encoding='utf-8')
        code, text = self.say('start', 'sample', 'lean', '--run', '1', '--who', 'Anna')
        self.assertEqual(code, 2)
        self.assertIn('sample-lean-1 already exists', text)
        self.assertIn('Never reuse a run folder', text)
        self.assertIn('next free number, which is 2', text)
        self.assertEqual((folder / 'agent-output.txt').read_text(encoding='utf-8'), 'earlier run')

    def test_a_deleted_folder_with_a_details_file_is_not_reused_either(self):
        folder = self.start('lean')
        shutil.rmtree(str(folder))
        code, text = self.say('start', 'sample', 'lean', '--run', '1', '--who', 'Anna')
        self.assertEqual(code, 2)
        self.assertIn('already exists', text)

    def test_the_run_folder_holds_only_the_start_files(self):
        folder = self.start('lean')
        start_files = sorted(p.name for p in (REPO_SAMPLE / 'start').iterdir())
        self.assertEqual(sorted(p.name for p in folder.rglob('*')), start_files)
        for name in start_files:
            self.assertEqual((folder / name).read_bytes(), (REPO_SAMPLE / 'start' / name).read_bytes())

    def test_the_details_file_is_written_outside_the_run_folder(self):
        folder = self.start('lean', who='Reid')
        details = json.loads((self.runs / kit.DETAILS_DIR / 'sample-lean-1.json').read_text(encoding='utf-8'))
        self.assertEqual((details['task'], details['version'], details['run'], details['who']),
                         ('sample', 'lean', 1, 'Reid'))
        self.assertTrue(details['started'])
        self.assertIsNone(details['finished'])
        self.assertTrue(details['practice'])
        self.assertNotIn(kit.DETAILS_DIR, [p.name for p in folder.iterdir()])

    def test_the_prompt_goes_to_the_clipboard_and_vscode_opens_on_the_run_folder(self):
        folder = self.start('lean')
        expected = (REPO_SAMPLE / 'prompt-lean.md').read_text(encoding='utf-8').rstrip('\r\n')
        self.mocks['clipboard'].assert_called_once_with(expected)
        self.mocks['vscode'].assert_called_once_with(str(folder))

    def test_next_steps_are_in_plain_words(self):
        _, text = self.say('start', 'sample', 'original', '--who', 'Anna')
        for phrase in ('PRACTICE TASK', 'NEW session', 'Do not add anything', 'Do not step away until it finishes',
                       'changes the cost', 'answer from this list', 'summary.md in this folder', 'finish my run',
                       '2. Type /model. Pick Sonnet 5.5, set Effort to High, leave Ultracode off. Same every run.',
                       '5. If a permission prompt appears, click Yes.'):
            self.assertIn(phrase, text)
        self.assertNotIn('same model as in your other runs', text)
        self.assertNotIn('Traceback', text)

    def test_without_a_clipboard_the_prompt_is_printed_between_two_lines(self):
        self.mocks['clipboard'].return_value = False
        _, text = self.say('start', 'sample', 'lean', '--who', 'Anna')
        self.assertIn('START OF PROMPT', text)
        self.assertIn('END OF PROMPT', text)
        prompt = (REPO_SAMPLE / 'prompt-lean.md').read_text(encoding='utf-8').strip()
        self.assertLess(text.index('START OF PROMPT'), text.index(prompt))
        self.assertLess(text.index(prompt), text.index('END OF PROMPT'))

    def test_without_vscode_the_folder_path_and_open_folder_are_printed(self):
        self.mocks['vscode'].return_value = False
        _, text = self.say('start', 'sample', 'lean', '--who', 'Anna')
        self.assertIn('File, then Open Folder', text)
        self.assertIn(str(self.runs / 'sample-lean-1'), text)

    def test_the_first_name_is_remembered_and_is_needed_once(self):
        code, text = self.say('start', 'sample', 'lean')
        self.assertEqual(code, 2)
        self.assertIn('--who', text)
        self.say('start', 'sample', 'lean', '--who', 'Anna')
        self.assertEqual(json.loads(self.env.settings_path.read_text(encoding='utf-8'))['who'], 'Anna')
        code, _ = self.say('start', 'sample', 'lean')
        self.assertEqual(code, 0)
        details = json.loads((self.runs / kit.DETAILS_DIR / 'sample-lean-2.json').read_text(encoding='utf-8'))
        self.assertEqual(details['who'], 'Anna')

    def test_an_unknown_task_or_version_is_a_plain_message(self):
        code, text = self.say('start', 'nope', 'lean', '--who', 'Anna')
        self.assertEqual(code, 2)
        self.assertIn('The tasks are: sample.', text)
        code, text = self.say('start', '../sample', 'lean', '--who', 'Anna')
        self.assertEqual(code, 2)
        code, text = self.say('start', 'sample', 'short', '--who', 'Anna')
        self.assertIn('"original" or "lean"', text)
        self.assertFalse(self.runs.exists())

    def test_a_bad_command_line_is_one_plain_sentence(self):
        code, text = self.say('start', 'sample')
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', text)
        self.assertNotIn('usage:', text)

    def test_commands_run_from_inside_a_run_folder_are_refused(self):
        folder = self.start('lean')
        out = io.StringIO()
        code = kit.main(['runs'], out=out, env=self.env, cwd=folder)
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue().strip(), kit.GO_BACK)


# ---------------------------------------------------------------- finish

class FinishTest(KitCase):
    def finish_clean_run(self, who='Anna'):
        folder = self.start('lean', who)
        self.put_session(folder, SESSION_3)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        return folder, text

    def test_it_finds_the_session_builds_the_receipt_and_prints_four_lines(self):
        folder, text = self.finish_clean_run()
        lines = text.splitlines()
        self.assertEqual(len(lines), 4, text)
        self.assertTrue(lines[0].startswith('Total: $'))
        self.assertIn('API-equivalent', lines[0])
        self.assertTrue(lines[1].startswith('Largest cause: '))
        self.assertTrue(lines[2].startswith('Most expensive step: step '))
        self.assertIn('(estimated)', lines[2])
        page = self.runs / 'sample-lean-1.receipt.html'
        self.assertEqual(lines[3], 'Receipt: %s' % page)
        self.assertTrue(page.is_file())
        self.assertNotIn(page.name, [p.name for p in folder.iterdir()])  # the receipt sits next to the run
        self.mocks['browser'].assert_called_once_with(page)

    def test_the_largest_cause_line_uses_the_same_rule_as_the_receipt_headline(self):
        """In this fixture the starting context (53 percent) is the largest cause, and it is not a step."""
        _, text = self.finish_clean_run()
        est = receipt.build(SESSION_3)
        found = est['findings']['headline']
        self.assertEqual(found['id'], 'fixed_overhead')
        line = next(l for l in text.splitlines() if l.startswith('Largest cause: '))
        self.assertIn("Claude Code's starting context (fixed overhead, sent before any work)", line)
        self.assertIn('53% of the total (estimated)', line)
        self.assertIn(found['cause'], line)
        page = (self.runs / 'sample-lean-1.receipt.html').read_text(encoding='utf-8')
        shown = re.search(r'<p class="headline">(.*?)</p>', page, re.S).group(1)
        plain = html.unescape(re.sub(r'<[^>]+>', '', shown)).strip()
        self.assertEqual(plain.removesuffix(' est.'), found['sentence'])  # the page says the same thing (plus its est. badge)
        self.assertNotIn('starting context', next(l for l in text.splitlines() if l.startswith('Most expensive step')))

    def test_with_no_headline_cause_the_line_says_so_in_words(self):
        est = {'findings': {'headline': None}}
        self.assertEqual(kit._largest_cause(est), 'none stands out')

    def test_it_writes_one_csv_row_with_exact_numbers(self):
        self.finish_clean_run()
        rows = self.results()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(tuple(row), kit.CSV_COLUMNS)
        self.assertEqual((row['task'], row['version'], row['run'], row['who'], row['practice']),
                         ('sample', 'lean', '1', 'Anna', 'yes'))
        est = receipt.build(SESSION_3)
        self.assertEqual(row['model_calls'], str(est['session']['calls']))
        self.assertEqual(row['tool_calls'], str(est['session']['tool_calls']))
        self.assertAlmostEqual(float(row['total_usd_api_equivalent']), est['totals']['transcript_usd'], places=6)
        self.assertEqual(row['session_id'], 'sess-0003')
        self.assertEqual(row['model'], 'claude-sonnet-5-5')
        self.assertEqual((row['check_this'], row['cache_rebuilds'], row['compacted']), ('no', '0', 'no'))
        for column in ('input_tokens', 'cache_read_tokens', 'cache_write_5m_tokens', 'output_tokens', 'minutes'):
            self.assertGreaterEqual(float(row[column]), 0)

    def test_a_clean_run_is_not_flagged(self):
        _, text = self.finish_clean_run()
        self.assertNotIn('Check this run', text)

    def test_a_cache_rebuild_sets_the_flag(self):
        folder = self.start('lean')
        demo = write_demo_session(str(Path(self.tmp.name) / 'demo'))
        self.put_session(folder, demo)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        self.assertTrue(text.startswith('Check this run: the saved copy of the conversation was rebuilt'), text)
        row = self.results()[0]
        self.assertEqual(row['check_this'], 'yes')
        self.assertGreaterEqual(int(row['cache_rebuilds']), 1)
        self.assertIn('rebuilt', row['check_reasons'])

    def test_a_compaction_an_api_error_and_an_unfinished_session_each_set_the_flag(self):
        boundary = json.dumps({'type': 'system', 'subtype': 'compact_boundary', 'timestamp': '2026-02-01T11:04:00.000Z',
                               'compactMetadata': {'trigger': 'auto', 'preTokens': 100, 'postTokens': 10}})
        api_error = json.dumps({'type': 'assistant', 'isApiErrorMessage': True, 'timestamp': '2026-02-01T11:04:00.000Z',
                                'message': {'id': 'msg_err', 'model': '<synthetic>', 'usage': {}}})
        cases = {
            'compacted': (self.edited_copy('compacted.jsonl', lambda lines: lines + [boundary]), 'compacted'),
            'api-error': (self.edited_copy('api.jsonl', lambda lines: lines[:-1] + [api_error] + lines[-1:]), 'API error'),
            'unfinished': (self.edited_copy('unfinished.jsonl', lambda lines: lines[:-1]), 'did not finish'),
        }
        for name, (path, reason) in cases.items():
            with self.subTest(name):
                shutil.rmtree(str(self.runs), ignore_errors=True)
                folder = self.start('lean')
                self.put_session(folder, path, name='sess-%s.jsonl' % name)
                code, text = self.say('finish')
                self.assertEqual(code, 0, text)
                self.assertIn('Check this run', text)
                self.assertIn(reason, self.results()[0]['check_reasons'])
                shutil.rmtree(str(self.home / '.claude'), ignore_errors=True)

    def test_tool_errors_are_counted_but_do_not_flag_the_run(self):
        folder = self.start('lean')
        path = self.edited_copy('tool-error.jsonl', lambda lines: [l.replace('"is_error": false', '"is_error": true')
                                                                    for l in lines])
        self.put_session(folder, path)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        self.assertNotIn('Check this run', text)
        row = self.results()[0]
        self.assertEqual(row['check_this'], 'no')
        self.assertGreaterEqual(int(row['tool_errors']), 1)

    def finish_with_model(self, version, model):
        """Start and finish a run whose session used the given model."""
        folder = self.start(version)
        path = self.edited_copy('%s-%s.jsonl' % (version, model), lambda lines: [
            l.replace('claude-sonnet-5-5', model) for l in lines])
        self.put_session(folder, path)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        return text

    def test_a_run_on_a_different_model_from_the_first_run_is_flagged_in_plain_words(self):
        first = self.finish_with_model('original', 'claude-sonnet-5-5')
        self.assertNotIn('different model', first)
        same = self.finish_with_model('lean', 'claude-sonnet-5-5')
        self.assertNotIn('different model', same)
        other = self.finish_with_model('lean', 'claude-opus-5-5')
        self.assertIn('Check this run: this run used a different model (claude-opus-5-5) from the first run of this '
                      'task (claude-sonnet-5-5)', other)
        rows = self.results()
        self.assertEqual([r['check_this'] for r in rows], ['no', 'no', 'yes'])
        self.assertEqual(rows[2]['model'], 'claude-opus-5-5')

    def test_refinishing_the_first_run_is_not_compared_with_a_later_one(self):
        self.finish_with_model('original', 'claude-sonnet-5-5')
        self.finish_with_model('lean', 'claude-opus-5-5')
        code, text = self.say('finish', 'sample-original-1')
        self.assertEqual(code, 0, text)
        self.assertNotIn('different model', text)

    def finish_with_effort(self, version, effort, name=None):
        """Start and finish a run whose log records the given effort in its api-request params (None: no record)."""
        folder = self.start(version)

        def add_requests(lines):
            out, seen = [], set()
            for line in lines:
                record = json.loads(line)
                if record['type'] == 'assistant' and effort:
                    ref = 'req-' + record['message']['id']
                    record['requestRef'] = ref
                    if ref not in seen:
                        seen.add(ref)
                        out.append(json.dumps({'type': 'api-request', 'id': ref, 'params': {
                            'model': 'claude-sonnet-5-5', 'output_config': {'effort': effort}}}))
                    line = json.dumps(record)
                out.append(line)
            return out
        path = self.edited_copy('%s-%s.jsonl' % (version, name or effort), add_requests)
        self.put_session(folder, path)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        return text

    def test_the_effort_of_each_run_is_recorded_in_the_results(self):
        self.finish_with_effort('original', 'high')
        self.finish_with_effort('lean', 'high')
        self.assertEqual(kit.CSV_COLUMNS[kit.CSV_COLUMNS.index('model') + 1], 'effort')
        self.assertEqual([r['effort'] for r in self.results()], ['high', 'high'])
        self.assertEqual([r['check_this'] for r in self.results()], ['no', 'no'])
        details = json.loads(next((self.runs / kit.DETAILS_DIR).glob('sample-lean-1.json')).read_text())
        self.assertEqual(details['effort'], 'high')

    def test_a_run_at_a_different_effort_from_the_first_run_is_flagged_in_plain_words(self):
        first = self.finish_with_effort('original', 'high')
        self.assertNotIn('different effort', first)
        other = self.finish_with_effort('lean', 'medium')
        self.assertIn('Check this run: this run used a different effort (medium) from the first run of this task '
                      '(high), so the cost is not comparable', other)
        self.assertNotIn('different model', other)
        rows = self.results()
        self.assertEqual([(r['effort'], r['check_this']) for r in rows], [('high', 'no'), ('medium', 'yes')])
        self.assertIn('different effort', rows[1]['check_reasons'])

    def test_a_different_model_and_a_different_effort_are_both_named(self):
        self.finish_with_effort('original', 'high')
        folder = self.start('lean')
        path = self.edited_copy('lean-both.jsonl', lambda lines: [
            l.replace('claude-sonnet-5-5', 'claude-opus-5-5') for l in lines])
        self.put_session(folder, path)
        code, text = self.say('finish')
        self.assertEqual(code, 0, text)
        self.assertIn('different model (claude-opus-5-5)', text)
        self.assertIn('does not say which effort this run used', text)

    def test_a_run_whose_log_has_no_effort_is_flagged_only_when_the_first_run_had_one(self):
        self.finish_with_effort('original', None)
        later = self.finish_with_effort('lean', 'high')
        self.assertNotIn('effort', later.split('Total:')[0])  # the first run recorded none, so nothing to compare
        self.assertEqual([r['effort'] for r in self.results()], ['', 'high'])

    def test_a_missing_effort_in_a_later_run_is_said_plainly(self):
        self.finish_with_effort('original', 'high')
        later = self.finish_with_effort('lean', None)
        self.assertIn('the log does not say which effort this run used, so I cannot confirm it matches the first '
                      'run of this task (high)', later)

    def test_refinishing_the_first_run_is_not_compared_on_effort_with_a_later_one(self):
        self.finish_with_effort('original', 'high')
        self.finish_with_effort('lean', 'medium')
        code, text = self.say('finish', 'sample-original-1')
        self.assertEqual(code, 0, text)
        self.assertNotIn('different effort', text)

    def test_an_older_results_file_without_an_effort_column_is_upgraded_not_broken(self):
        old = [c for c in kit.CSV_COLUMNS if c != 'effort']
        self.runs.mkdir(parents=True, exist_ok=True)
        with open(str(self.runs / kit.RESULTS_NAME), 'w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=old)
            writer.writeheader()
            writer.writerow({c: 'x' for c in old} | {'task': 'other', 'version': 'lean', 'run': '1'})
        self.finish_with_effort('original', 'high')
        rows = self.results()
        self.assertEqual([(r['task'], r['effort']) for r in rows], [('other', ''), ('sample', 'high')])

    def test_zero_sessions_stops_with_a_plain_message(self):
        self.start('lean')
        code, text = self.say('finish')
        self.assertEqual(code, 2)
        self.assertIn('cannot find a Claude Code session for sample-lean-1', text)
        self.assertFalse((self.runs / kit.RESULTS_NAME).exists())

    def test_two_sessions_stops_and_does_not_guess(self):
        folder = self.start('lean')
        self.put_session(folder, SESSION_3, name='first.jsonl')
        self.put_session(folder, SESSION_3, name='second.jsonl')
        code, text = self.say('finish')
        self.assertEqual(code, 2)
        self.assertIn('found 2 Claude Code sessions', text)
        self.assertIn('will not guess', text)
        self.assertFalse((self.runs / kit.RESULTS_NAME).exists())
        self.assertFalse((self.runs / 'sample-lean-1.receipt.html').exists())

    def test_the_default_is_the_most_recent_unfinished_run(self):
        first, second = self.start('lean'), self.start('lean')
        self.put_session(first, SESSION_3)
        self.put_session(second, SESSION_3)
        self.say('finish')
        self.assertEqual([r['run'] for r in self.results()], ['2'])
        self.say('finish')
        self.assertEqual(sorted(r['run'] for r in self.results()), ['1', '2'])
        code, text = self.say('finish')
        self.assertEqual(code, 2)
        self.assertIn('no unfinished run', text)

    def test_finishing_a_named_run_again_replaces_its_row(self):
        folder = self.start('lean')
        self.put_session(folder, SESSION_3)
        self.say('finish')
        self.say('finish', 'sample-lean-1')
        self.assertEqual(len(self.results()), 1)

    def test_an_unknown_run_name_is_a_plain_message(self):
        code, text = self.say('finish', 'sample-lean-9')
        self.assertEqual(code, 2)
        self.assertIn('do not know a run called "sample-lean-9"', text)


class PromptAgainTest(KitCase):
    def expected(self, version='lean'):
        return (REPO_SAMPLE / ('prompt-%s.md' % version)).read_text(encoding='utf-8').rstrip('\r\n')

    def test_the_prompt_is_saved_in_the_details_file_when_the_run_starts(self):
        self.start('lean')
        details = json.loads((self.runs / kit.DETAILS_DIR / 'sample-lean-1.json').read_text(encoding='utf-8'))
        self.assertEqual(details['prompt'], self.expected('lean'))

    def test_the_prompt_is_not_in_the_run_folder_or_the_results_file(self):
        folder = self.start('lean')
        self.put_session(folder, SESSION_3)
        self.say('finish')
        self.assertNotIn('prompt', ' '.join(p.name for p in folder.iterdir()).lower())
        text = (self.runs / kit.RESULTS_NAME).read_text(encoding='utf-8')
        self.assertNotIn(self.expected('lean'), text)

    def test_it_copies_the_latest_runs_prompt_and_prints_it_between_two_lines(self):
        self.start('original')
        self.start('lean')
        self.mocks['clipboard'].reset_mock()
        code, text = self.say('prompt')
        self.assertEqual(code, 0, text)
        self.mocks['clipboard'].assert_called_once_with(self.expected('lean'))
        self.assertIn('Prompt for sample-lean-1', text)
        self.assertLess(text.index('START OF PROMPT'), text.index(self.expected('lean')))
        self.assertLess(text.index(self.expected('lean')), text.index('END OF PROMPT'))
        self.assertIn('It is on your clipboard.', text)

    def test_a_named_run_gives_that_runs_prompt(self):
        self.start('original')
        self.start('lean')
        self.mocks['clipboard'].reset_mock()
        code, text = self.say('prompt', 'sample-original-1')
        self.assertEqual(code, 0, text)
        self.mocks['clipboard'].assert_called_once_with(self.expected('original'))
        self.assertIn('sample, original version', text)

    def test_the_saved_prompt_wins_over_a_task_file_edited_later(self):
        self.start('lean')
        task_file = self.repo / 'experiments' / 'tasks' / 'sample' / 'prompt-lean.md'
        task_file.write_text('A different prompt, written later.\n', encoding='utf-8')
        self.mocks['clipboard'].reset_mock()
        _, text = self.say('prompt')
        self.mocks['clipboard'].assert_called_once_with(self.expected_from(REPO_SAMPLE / 'prompt-lean.md'))
        self.assertNotIn('written later', text)

    def expected_from(self, path):
        return path.read_text(encoding='utf-8').rstrip('\r\n')

    def test_without_a_clipboard_it_still_prints_and_says_how_to_copy(self):
        self.start('lean')
        self.mocks['clipboard'].return_value = False
        code, text = self.say('prompt')
        self.assertEqual(code, 0)
        self.assertIn(self.expected('lean'), text)
        self.assertIn('I could not reach the clipboard. Copy the prompt from between the two lines above.', text)

    def test_a_run_from_before_prompts_were_saved_uses_the_task_file_and_says_so(self):
        self.start('lean')
        path = self.runs / kit.DETAILS_DIR / 'sample-lean-1.json'
        details = json.loads(path.read_text(encoding='utf-8'))
        del details['prompt']
        path.write_text(json.dumps(details), encoding='utf-8')
        self.mocks['clipboard'].reset_mock()
        code, text = self.say('prompt')
        self.assertEqual(code, 0, text)
        self.mocks['clipboard'].assert_called_once_with(self.expected('lean'))
        self.assertIn('began before prompts were saved', text)

    def test_with_no_saved_prompt_and_no_task_file_it_is_a_plain_message(self):
        self.start('lean')
        path = self.runs / kit.DETAILS_DIR / 'sample-lean-1.json'
        details = json.loads(path.read_text(encoding='utf-8'))
        del details['prompt']
        path.write_text(json.dumps(details), encoding='utf-8')
        shutil.rmtree(str(self.repo / 'experiments' / 'tasks' / 'sample'))
        code, text = self.say('prompt')
        self.assertEqual(code, 2)
        self.assertIn('cannot show it', text)
        self.assertNotIn('Traceback', text)

    def test_no_runs_and_unknown_runs_are_plain_messages(self):
        code, text = self.say('prompt')
        self.assertEqual(code, 2)
        self.assertIn('No runs yet', text)
        self.start('lean')
        code, text = self.say('prompt', 'sample-lean-9')
        self.assertEqual(code, 2)
        self.assertIn('I do not know a run called "sample-lean-9"', text)

    def test_it_is_refused_from_inside_a_run_folder_like_every_other_command(self):
        folder = self.start('lean')
        out = io.StringIO()
        self.assertEqual(kit.main(['prompt'], out=out, env=self.env, cwd=folder), 2)
        self.assertEqual(out.getvalue().strip(), kit.GO_BACK)

    def test_the_prompt_never_comes_from_a_session_log(self):
        """Finishing a run (which reads the session) must not change what the command shows."""
        folder = self.start('lean')
        self.put_session(folder, SESSION_3)
        self.say('finish')
        self.mocks['clipboard'].reset_mock()
        self.say('prompt')
        self.mocks['clipboard'].assert_called_once_with(self.expected('lean'))


class ReceiptAndRunsTest(KitCase):
    def test_latest_means_the_latest_finished_run_not_the_latest_session(self):
        first, second = self.start('lean'), self.start('original')
        self.put_session(first, SESSION_3)
        self.say('finish', 'sample-lean-1')
        self.put_session(second, SESSION_3)  # a newer session exists, but that run is not finished
        self.mocks['browser'].reset_mock()
        code, text = self.say('receipt', 'latest')
        self.assertEqual(code, 0, text)
        self.assertEqual(text.strip(), 'Receipt: %s' % (self.runs / 'sample-lean-1.receipt.html'))
        self.mocks['browser'].assert_called_once_with(self.runs / 'sample-lean-1.receipt.html')

    def test_a_receipt_is_built_when_it_is_missing(self):
        folder = self.start('lean')
        self.put_session(folder, SESSION_3)
        code, text = self.say('receipt', 'sample-lean-1')
        self.assertEqual(code, 0, text)
        self.assertTrue((self.runs / 'sample-lean-1.receipt.html').is_file())

    def test_receipt_with_nothing_finished_is_a_plain_message(self):
        code, text = self.say('receipt')
        self.assertEqual(code, 2)
        self.assertIn('no finished run yet', text)

    def test_the_runs_table(self):
        code, text = self.say('runs')
        self.assertIn('No runs yet', text)
        first, second = self.start('lean'), self.start('original', who='Reid')
        self.put_session(first, SESSION_3)
        self.say('finish', 'sample-lean-1')
        code, text = self.say('runs')
        lines = text.splitlines()
        self.assertEqual(lines[0].split(), ['Task', 'Version', 'Run', 'Who', 'Dollars', '(API-equivalent)', 'Flag'])
        self.assertIn('sample', lines[1])
        self.assertIn('Anna', lines[1])
        self.assertIn('$', lines[1])
        self.assertIn('ok (practice)', lines[1])
        self.assertIn('Reid', lines[2])
        self.assertIn('not finished', lines[2])


class UpdateTest(KitCase):
    def test_local_changes_stop_the_update_and_nothing_is_pulled(self):
        calls = []
        self.mocks['git'].side_effect = lambda env, *args, **kw: calls.append(args) or (0, ' M src/kit.py')
        code, text = self.say('update')
        self.assertEqual(code, 2)
        self.assertIn('1 changed file', text)
        self.assertIn('changed nothing', text)
        self.assertNotIn(('pull', '--ff-only'), calls)

    def test_a_clean_copy_is_updated_with_a_plain_fast_forward(self):
        calls = []
        self.mocks['git'].side_effect = lambda env, *args, **kw: calls.append(args) or (
            0, 'Already up to date.' if args[0] == 'pull' else '')
        code, text = self.say('update')
        self.assertEqual(code, 0)
        self.assertIn('Already up to date.', text)
        self.assertIn(('pull', '--ff-only'), calls)
        self.assertTrue(all(c[0] in ('status', 'pull') for c in calls))


# ---------------------------------------------------------------- Windows paths

class WindowsPathTest(KitCase):
    def test_encoding_matches_how_claude_code_names_folders(self):
        self.assertEqual(parse.encode_cwd(WINDOWS_CWD), WINDOWS_FOLDER)
        self.assertEqual(parse.encode_cwd('/Users/ann/my work'), '-Users-ann-my-work')

    def test_a_windows_working_directory_finds_its_session_folder(self):
        self.put_session(WINDOWS_CWD, SESSION_3)
        root = str(self.home / '.claude' / 'projects')
        self.assertEqual(len(parse.sessions_for_cwd(WINDOWS_CWD, root)), 1)
        self.assertEqual(parse.latest_session(WINDOWS_CWD, root), str(self.home / '.claude' / 'projects' / WINDOWS_FOLDER / 'sess-0003.jsonl'))

    def test_a_lower_case_drive_letter_still_matches(self):
        self.put_session(WINDOWS_CWD, SESSION_3)
        root = str(self.home / '.claude' / 'projects')
        self.assertEqual(len(parse.sessions_for_cwd('c:' + WINDOWS_CWD[2:], root)), 1)
        self.assertEqual(len(parse.sessions_for_cwd(WINDOWS_CWD.replace('Anna', 'ANNA'), root)), 1)

    def test_a_mac_path_is_still_case_sensitive(self):
        self.put_session('/Users/ann/Runs/x', SESSION_3)
        root = str(self.home / '.claude' / 'projects')
        self.assertEqual(len(parse.sessions_for_cwd('/Users/ann/Runs/x', root)), 1)
        self.assertEqual(parse.sessions_for_cwd('/Users/ann/runs/x', root), [])

    def test_a_long_path_matches_by_its_first_200_characters(self):
        cwd = 'C:\\' + '\\'.join(['folder%d' % n for n in range(40)])
        name = parse.encode_cwd(cwd)
        self.assertGreater(len(name), parse.MAX_FOLDER_NAME)
        folder = self.home / '.claude' / 'projects' / (name[:parse.MAX_FOLDER_NAME] + '-ab12cd')
        folder.mkdir(parents=True)
        shutil.copy(SESSION_3, str(folder / 'sess-0003.jsonl'))
        self.assertEqual(len(parse.sessions_for_cwd(cwd, str(self.home / '.claude' / 'projects'))), 1)

    def test_finish_finds_a_session_by_a_windows_style_folder(self):
        self.put_session(WINDOWS_CWD, SESSION_3)
        found = kit.find_session(self.env, WINDOWS_CWD)
        self.assertTrue(found.endswith('sess-0003.jsonl'))
        self.assertTrue(found.split(WINDOWS_FOLDER)[0].endswith('projects' + os.sep))

    def test_zero_and_two_windows_style_candidates_are_refused(self):
        with self.assertRaises(kit.KitError) as zero:
            kit.find_session(self.env, WINDOWS_CWD)
        self.assertIn('sample-lean-1', str(zero.exception))
        self.put_session(WINDOWS_CWD, SESSION_3, name='a.jsonl')
        self.put_session(WINDOWS_CWD, SESSION_3, name='b.jsonl')
        with self.assertRaises(kit.KitError) as two:
            kit.find_session(self.env, WINDOWS_CWD)
        self.assertIn('found 2', str(two.exception))

    def test_a_session_recorded_on_windows_builds_a_receipt_with_clean_names(self):
        text = Path(SESSION_3).read_text(encoding='utf-8')
        escaped = WINDOWS_CWD.replace('\\', '\\\\')
        text = text.replace('"cwd": "/work/demo"', '"cwd": "%s"' % escaped)
        text = text.replace('/work/demo/<b>x</b>.py', (escaped + '\\\\src\\\\app.py'))
        path = self.put_session(WINDOWS_CWD, SESSION_3)
        path.write_text(text, encoding='utf-8')
        est = receipt.build(str(path))
        self.assertEqual(est['session']['project'], 'sample-lean-1')
        self.assertEqual(est['session']['cwd'], WINDOWS_CWD)
        self.assertEqual([row['path'] for row in est['files'] if 'app.py' in row['path']], [WINDOWS_CWD + '\\src\\app.py'])
        self.assertEqual(receipt.display_path(WINDOWS_CWD + '\\src\\app.py', WINDOWS_CWD), 'src\\app.py')
        self.assertEqual(receipt.display_path('c:\\users\\anna\\prompt-analyzer-runs\\sample-lean-1\\a.txt', WINDOWS_CWD), 'a.txt')
        self.assertIn('app.py', receipt.render(est))

    def test_path_helpers(self):
        self.assertEqual(paths.basename(WINDOWS_CWD + '\\'), 'sample-lean-1')
        self.assertEqual(paths.basename('/demo/pantry-planner/'), 'pantry-planner')
        self.assertEqual(paths.path_key('src\\a.py', WINDOWS_CWD), WINDOWS_CWD + '\\src\\a.py')
        self.assertEqual(paths.path_key('/demo/x/../y.py', '/demo'), '/demo/y.py')
        self.assertIsNone(paths.relative_under('D:\\other\\a.txt', WINDOWS_CWD))
        self.assertEqual(paths.relative_under('/work/demo/a/b.py', '/work/demo'), 'a/b.py')


if __name__ == '__main__':
    unittest.main()
