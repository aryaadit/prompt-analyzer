"""Tests for src/summarize.py: the structure, the text, the JSON, and the command line."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from src import parse, summarize
from tests.helpers import FIXTURE_ROOT, PRIVATE_STRINGS, SESSION_1, SESSION_2


def build(path=SESSION_1):
    """Parse and summarize a fixture session."""
    return summarize.build_summary(parse.parse_session(path))


def text_of(summary):
    """Render the plain-text report to a string."""
    buffer = io.StringIO()
    summarize.render_text(summary, buffer)
    return buffer.getvalue()


class SummaryStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = build()

    def test_totals_and_unpriced_share(self):
        totals = self.summary['totals']
        self.assertEqual(totals['calls'], 7)
        self.assertEqual(totals['calls_without_public_price'], 1)
        self.assertAlmostEqual(totals['share_calls_without_public_price'], 1 / 7)
        self.assertEqual(totals['models_without_public_price'], ['claude-unknown-9'])
        self.assertEqual(totals['tokens']['output'], 300 + 80 + 50 + 5 + 40 + 25 + 10)

    def test_unpriced_calls_have_no_dollars_but_keep_tokens(self):
        unpriced = [c for c in self.summary['calls'] if c['model'] == 'claude-unknown-9'][0]
        self.assertIsNone(unpriced['usd'])
        self.assertEqual(unpriced['tokens']['output'], 5)
        self.assertEqual(self.summary['by_model']['claude-unknown-9']['unpriced_calls'], 1)

    def test_attributed_dollars_sum_the_priced_calls(self):
        expected = sum(c['usd'] for c in self.summary['calls'] if c['usd'] is not None)
        self.assertAlmostEqual(self.summary['totals']['attributed_usd'], expected)
        self.assertGreater(expected, 0)

    def test_main_versus_subagent_split(self):
        self.assertEqual(self.summary['by_source']['main session']['calls'], 4)
        self.assertEqual(self.summary['by_source']['subagents']['calls'], 3)

    def test_tool_counts(self):
        counts = self.summary['tool_counts']
        self.assertEqual(counts['Bash'], {'calls': 1, 'results': 1, 'errors': 1, 'result_chars': 5})
        self.assertEqual(counts['Read']['calls'], 2)  # one main, one subagent
        self.assertEqual(counts['Edit']['results'], 0)

    def test_top_calls_are_sorted_by_cost(self):
        by_order = {c['order']: c for c in self.summary['calls']}
        costs = [by_order[o]['usd'] for o in self.summary['top_calls_by_cost']]
        self.assertEqual(costs, sorted(costs, reverse=True))
        self.assertEqual(len(costs), 6)  # the unpriced call is left out

    def test_reconciliation_block(self):
        recon = self.summary['reconciliation']
        self.assertEqual(recon['totals']['label'], 'in session totals, not attributed to a transcript call')
        self.assertEqual(recon['totals']['models_without_public_price'], ['claude-unknown-9'])
        rows = {r['model']: r for r in recon['models']}
        self.assertEqual(rows['claude-opus-5-5']['gap_tokens']['output'], 20)
        self.assertLessEqual(rows['claude-opus-5-5']['gap_usd_low'], rows['claude-opus-5-5']['gap_usd_high'])
        self.assertEqual(rows['claude-sonnet-5-5']['exact_scope'], 'main')
        self.assertAlmostEqual(rows['claude-sonnet-5-5']['gap_usd_low'], 0.0, places=9)
        self.assertAlmostEqual(recon['totals']['gap_usd_low'],
                               sum(r['gap_usd_low'] for r in rows.values() if r['gap_usd_low'] is not None))

    def test_session_without_cost_state_has_no_reconciliation(self):
        summary = build(SESSION_2)
        self.assertIsNone(summary['reconciliation'])
        self.assertIn('no cost-state record', text_of(summary))

    def test_segments(self):
        self.assertEqual([s['calls'] for s in self.summary['segments']], [4, 3])


class SummaryTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = text_of(build())

    def test_labels_and_sections_are_present(self):
        for needle in ('exact', 'API-equivalent', 'no public price', 'TOP 10 CALLS BY COST',
                       'TOOL CALLS BY TOOL', 'RECONCILIATION', 'not attributed to a transcript call',
                       'Session total', 'Attributed total', 'checked 2026-11-12'):
            self.assertIn(needle, self.text)

    def test_unpriced_share_is_listed(self):
        self.assertIn('1 of 7 calls (14.3%)', self.text)

    def test_paths_are_shortened_to_base_names(self):
        self.assertIn('Read:alpha.txt', self.text)
        self.assertNotIn('/work/demo', self.text)

    def test_no_private_text_in_the_report(self):
        for text in PRIVATE_STRINGS:
            self.assertNotIn(text, self.text)


class JsonAndCliTest(unittest.TestCase):
    def test_json_has_no_prompt_text_file_contents_or_tool_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = summarize.write_json(build(), os.path.join(folder, 'out.json'))
            with open(path) as handle:
                raw = handle.read()
        data = json.loads(raw)
        self.assertEqual(data['totals']['calls'], 7)
        for text in PRIVATE_STRINGS:
            self.assertNotIn(text, raw)
        call = data['calls'][0]
        self.assertIn('tokens', call)
        self.assertNotIn('content', call)

    def test_write_json_into_a_directory_uses_the_default_name(self):
        with tempfile.TemporaryDirectory() as folder:
            path = summarize.write_json(build(), folder)
            self.assertEqual(os.path.basename(path), 'sess-0001.summary.json')

    def test_default_json_location_is_reports(self):
        path = summarize.default_json_path('abc')
        self.assertEqual(os.path.basename(os.path.dirname(path)), 'reports')

    def test_command_line_by_path_and_by_id(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, 'summary.json')
            for session in (SESSION_1, 'sess-0001'):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = summarize.main(['--session', session, '--root', FIXTURE_ROOT, '--json', target])
                self.assertEqual(code, 0)
                self.assertIn('JSON written to summary.json', out.getvalue())
                self.assertTrue(os.path.exists(target))

    def test_command_line_unknown_session_fails_cleanly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = summarize.main(['--session', 'nope', '--root', FIXTURE_ROOT])
        self.assertEqual(code, 2)
        self.assertIn('session not found', err.getvalue())


if __name__ == '__main__':
    unittest.main()
