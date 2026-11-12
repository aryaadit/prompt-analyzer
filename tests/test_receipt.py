"""Tests for src/receipt.py: the page, its privacy and escaping, and the command line."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from html.parser import HTMLParser
from unittest import mock

from src import estimate, parse, receipt
from tests.helpers import FIXTURE_ROOT, PRIVATE_STRINGS, RECEIPT_MARKERS, SESSION_1, SESSION_2, SESSION_3
from tests.make_demo_session import MARKERS, write_demo_session


class Page(HTMLParser):
    """Collects what the HTML parser sees: tags, attributes, and whether it parsed at all."""

    def __init__(self):
        super().__init__()
        self.tags, self.attrs, self.starts = [], [], 0

    def handle_starttag(self, tag, attrs):
        self.starts += 1
        self.tags.append(tag)
        self.attrs.extend((tag, name, value) for name, value in attrs)


def page_of(html_text):
    parser = Page()
    parser.feed(html_text)
    parser.close()
    return parser


class RenderCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.demo_path = write_demo_session(cls.tmp.name)
        cls.pages = {}
        for name, path in (('demo', cls.demo_path), ('s1', SESSION_1), ('s2', SESSION_2), ('s3', SESSION_3)):
            est = receipt.build(path)
            cls.pages[name] = (est, receipt.render(est))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class PageStructureTest(RenderCase):
    def test_the_html_parses_and_has_every_section_in_order(self):
        for name, (est, text) in self.pages.items():
            parsed = page_of(text)
            self.assertGreater(parsed.starts, 50, name)
            self.assertTrue(text.startswith('<!DOCTYPE html>'))
            positions = [text.index(h) for h in ('<h1>', 'class="tiles"', 'Where the money went', 'The three most expensive steps',
                                                 'How the conversation grew', 'Every step', '<h2>Files</h2>', 'Other findings', 'Fine print')]
            self.assertEqual(positions, sorted(positions), name)

    def test_nothing_points_off_the_page(self):
        for name, (est, text) in self.pages.items():
            parsed = page_of(text)
            self.assertNotIn('link', parsed.tags)
            for tag, attr, value in parsed.attrs:
                self.assertNotEqual(attr, 'src', (name, tag, value))
                if attr == 'href':
                    self.assertTrue(value.startswith('#'), (name, value))
            self.assertNotIn('<script src', text)
            self.assertNotIn('@import', text)
            self.assertNotIn('url(http', text)

    def test_one_script_block_and_it_is_inline(self):
        for name, (est, text) in self.pages.items():
            self.assertEqual(text.count('<script'), 1, name)  # only our own block; injected names are escaped
            self.assertEqual(text.count('</script>'), 1, name)

    def test_every_number_group_carries_an_exact_or_est_word(self):
        text = self.pages['demo'][1]
        self.assertGreater(text.count('>exact<'), 5)
        self.assertGreater(text.count('>est.<'), 5)
        self.assertIn('API-equivalent', text)
        self.assertIn('subscription', text)

    def test_plain_words_in_the_body_and_raw_field_names_only_in_detail_and_fine_print(self):
        text = self.pages['demo'][1]
        body = text[:text.index('<tr class="detail"')]
        for raw in ('cache_read_input_tokens', 'cache_creation', 'input_tokens', 'ephemeral'):
            self.assertNotIn(raw, body)
            self.assertIn(raw, text)  # present in the expanded detail
        self.assertIn('Re-sent', text)

    def test_the_top_cards_are_ordered_and_steps_that_share_a_file_are_merged(self):
        est, text = self.pages['demo']
        self.assertEqual(text.count('class="card"'), 3)
        self.assertLess(text.index('Steps 2, 7 and 14'), text.index('Steps 19, 21, 27, 29 and 33'))
        self.assertLess(text.index('Steps 19, 21, 27, 29 and 33'), text.index('Step 22'))
        self.assertIn('Read inventory.py 3 times', text)
        self.assertIn('in total', text)

    def test_step_rows_and_details(self):
        est, text = self.pages['demo']
        self.assertEqual(text.count('<tr class="step"'), 36)
        self.assertEqual(text.count('<tr class="detail" hidden>'), 36)
        self.assertIn('data-limit="50"', text)
        self.assertIn('Cache rebuilt', text)
        self.assertIn('result 36,000 characters (exact)', text)

    def test_growth_chart_marks_the_rebuild(self):
        est, text = self.pages['demo']
        self.assertEqual(text.count('<title>Cache rebuilt after 25 minutes</title>'), 1)  # one marker on the chart
        self.assertIn('Cache rebuilt after 25 minutes (previous_message_not_found)', text)  # and the reason in the step detail
        self.assertEqual(text.count('<g><title>Call '), 36)

    def test_gap_notes(self):
        self.assertIn('higher than this transcript total', self.pages['s1'][1])  # the fixture has a large gap
        self.assertNotIn('higher than this transcript total', self.pages['demo'][1])
        self.assertIn('matches the transcript exactly', self.pages['demo'][1])
        self.assertIn('This log has none yet', self.pages['s2'][1])  # a live session

    def test_models_without_a_public_price_are_called_out(self):
        text = self.pages['s1'][1]
        self.assertIn('no public price', text)
        self.assertIn('claude-unknown-9', text)
        self.assertIn('not yet checked against a session total', text)  # claude-haiku-5-5 is not validated

    def test_a_tag_is_text_not_just_colour(self):
        self.assertIn('text-transform:uppercase', receipt.CSS)
        self.assertIn('border-style:dashed', receipt.CSS)  # est. looks different from exact without colour


class PrivacyAndEscapingTest(RenderCase):
    def test_no_prompt_text_file_contents_or_tool_output_in_any_page_or_json(self):
        forbidden = PRIVATE_STRINGS + RECEIPT_MARKERS + MARKERS
        for name, (est, text) in self.pages.items():
            dumped = json.dumps(est, default=str)
            for marker in forbidden:
                self.assertNotIn(marker, text, (name, marker))
                self.assertNotIn(marker, dumped, (name, marker))

    def test_the_demo_log_really_contains_the_markers(self):
        raw = open(self.demo_path).read()
        for marker in MARKERS:
            self.assertIn(marker, raw)

    def test_log_strings_are_html_escaped(self):
        text = self.pages['s3'][1]
        self.assertNotIn('<script>alert(1)</script>', text)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', text)
        self.assertNotIn('<b>x</b>', text)
        self.assertIn('x&lt;/b&gt;.py', text)

    def test_escape_helper(self):
        self.assertEqual(receipt.esc('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#x27;&lt;/a&gt;')

    def test_paths_are_relative_to_the_project_and_home_is_shown_as_tilde(self):
        self.assertEqual(receipt.display_path('/demo/pantry-planner/pantry/a.py', '/demo/pantry-planner'), 'pantry/a.py')
        home = os.path.expanduser('~')
        self.assertEqual(receipt.display_path(home + '/notes/a.md', '/elsewhere'), '~/notes/a.md')
        self.assertEqual(receipt.display_path('/etc/hosts', '/demo'), '/etc/hosts')
        self.assertEqual(receipt.clean_url('https://example.com/a/b?token=SECRET#frag'), 'https://example.com/a/b')
        text = self.pages['demo'][1]
        self.assertIn('pantry/inventory.py', text)  # relative path in the detail and files table
        self.assertNotIn('/demo/pantry-planner/pantry/inventory.py', text)


class CommandLineTest(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = receipt.main(argv + ['--no-open'], out=out)
        return code, out.getvalue()

    def test_writes_the_page_and_the_json_and_prints_three_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            html_path, json_path = os.path.join(folder, 'r.html'), os.path.join(folder, 'r.json')
            code, printed = self.run_cli(['--session', SESSION_1, '--out', html_path, '--json', json_path])
            self.assertEqual(code, 0)
            lines = printed.strip().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[0].startswith('Receipt: ') and lines[0].endswith('r.html'))
            self.assertTrue(lines[1].startswith('Total: ') and 'API-equivalent' in lines[1])
            self.assertTrue(lines[2].startswith('Most expensive step: #1'))
            self.assertTrue(os.path.getsize(html_path) > 5000)
            data = json.load(open(json_path))
            self.assertEqual(data['session']['session_id'], 'sess-0001')
            self.assertLessEqual(data['sum_back']['difference_usd'], 1e-6)

    def test_session_by_id_and_by_folder(self):
        with tempfile.TemporaryDirectory() as root:
            shutil.copytree(FIXTURE_ROOT, root, dirs_exist_ok=True)
            work = os.path.join(root, 'myproject')
            os.makedirs(work)
            project = os.path.join(root, parse.encode_cwd(os.path.abspath(work)))
            os.makedirs(project)
            shutil.copy(SESSION_2, project)
            self.assertTrue(receipt.resolve_target(work, root=root).endswith('sess-0002.jsonl'))
            self.assertTrue(receipt.resolve_target('sess-0001', root=root).endswith('sess-0001.jsonl'))
            out = os.path.join(root, 'out.html')
            code, _ = self.run_cli(['--session', work, '--root', root, '--out', out])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out))

    def test_default_output_location_is_reports(self):
        path = receipt._target_path('', '.receipt.html', 'abc')
        self.assertEqual(os.path.basename(os.path.dirname(path)), 'reports')
        self.assertTrue(path.endswith('abc.receipt.html'))
        self.assertEqual(os.path.basename(receipt._target_path('/tmp/x/', '.receipt.json', 'abc')), 'abc.receipt.json')

    def test_demo_builds_to_the_path_given(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, 'demo.html')
            code, printed = self.run_cli(['--demo', '--out', out])
            self.assertEqual(code, 0)
            self.assertIn('Receipt: ' + out, printed)
            self.assertIn('Most expensive step: #2, Read inventory.py', printed)

    def test_the_committed_demo_receipt_is_current(self):
        committed = os.path.join(os.path.dirname(FIXTURE_ROOT), '..', 'docs', 'demo-receipt.html')
        if not os.path.exists(committed):
            self.skipTest('docs/demo-receipt.html has not been built yet')
        with tempfile.TemporaryDirectory() as folder:
            est = receipt.build(write_demo_session(folder))
        self.assertEqual(open(committed).read(), receipt.render(est))

    def test_an_error_is_reported_not_raised(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(receipt.main(['--session', 'nothing-here', '--no-open']), 2)
        self.assertIn('error:', err.getvalue())
        with mock.patch.object(estimate, 'build_estimate', side_effect=estimate.ReceiptError('did not add back up')):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(receipt.main(['--session', SESSION_1, '--no-open']), 2)
            self.assertIn('did not add back up', err.getvalue())

    def test_a_browser_is_opened_unless_told_not_to(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, 'r.html')
            with mock.patch.object(receipt.webbrowser, 'open') as opened:
                with contextlib.redirect_stdout(io.StringIO()):
                    receipt.main(['--session', SESSION_2, '--out', out])
                opened.assert_called_once()
                self.assertTrue(opened.call_args[0][0].startswith('file://'))
            with mock.patch.object(receipt.webbrowser, 'open') as opened:
                with contextlib.redirect_stdout(io.StringIO()):
                    receipt.main(['--session', SESSION_2, '--out', out, '--no-open'])
                opened.assert_not_called()


class ThousandStepsTest(unittest.TestCase):
    def test_a_long_session_builds_fast_and_the_page_limits_what_it_shows(self):
        lines, size = [], 20000
        for i in range(1200):
            stamp = '2026-03-01T%02d:%02d:%02d.000Z' % (i // 3600, (i // 60) % 60, i % 60)
            new, out = 400 + i % 7, 60
            usage = {'input_tokens': 3, 'cache_read_input_tokens': size, 'cache_creation_input_tokens': new - 3,
                     'cache_creation': {'ephemeral_5m_input_tokens': new - 3, 'ephemeral_1h_input_tokens': 0},
                     'output_tokens': out}
            size += new
            tool = {'type': 'tool_use', 'id': 't%d' % i, 'name': 'Read', 'input': {'file_path': '/p/f%d.py' % (i % 40)}}
            lines.append(json.dumps({'type': 'assistant', 'timestamp': stamp, 'sessionId': 'big', 'cwd': '/p', 'message': {
                'id': 'm%d' % i, 'model': 'claude-sonnet-5-5', 'stop_reason': 'tool_use', 'content': [tool], 'usage': usage}}))
            lines.append(json.dumps({'type': 'user', 'timestamp': stamp, 'sessionId': 'big', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 't%d' % i, 'content': 'x' * 900}]}}))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'big.jsonl')
            open(path, 'w').write('\n'.join(lines) + '\n')
            started = time.time()
            est = receipt.build(path)
            text = receipt.render(est)
            self.assertLess(time.time() - started, 10)
        self.assertLessEqual(est['sum_back']['difference_usd'], 1e-6)
        self.assertEqual(text.count('<tr class="step"'), 1200)
        self.assertIn('data-limit="50"', text)
        self.assertIn('Show all 1200 steps', text)
        self.assertLess(len(text), 6_000_000)


if __name__ == '__main__':
    unittest.main()
