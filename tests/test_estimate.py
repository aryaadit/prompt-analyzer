"""Tests for src/estimate.py and src/diagnose.py: the split must add back to the exact total."""
import json
import os
import tempfile
import unittest

from src import estimate, parse, prices, summarize
from tests.helpers import ALL_FIXTURES, PRIVATE_STRINGS, RECEIPT_MARKERS, SESSION_1, SESSION_2, SESSION_3
from tests.make_demo_session import MARKERS, write_demo_session


def build(path):
    """Parse a session file and build its estimate."""
    return estimate.build_estimate(parse.parse_session(path))


class DemoCase(unittest.TestCase):
    """Builds the made-up demo session once per test class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = write_demo_session(cls.tmp.name)
        cls.session = parse.parse_session(cls.path)
        cls.est = estimate.build_estimate(cls.session)
        cls.steps = {s['number']: s for s in cls.est['steps']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class SumBackTest(DemoCase):
    def sessions(self):
        return [self.est] + [build(path) for path in ALL_FIXTURES]

    def test_sum_back_on_every_fixture_and_the_demo(self):
        for est in self.sessions():
            back = est['sum_back']
            self.assertLessEqual(back['difference_usd'], 1e-6)
            self.assertLessEqual(back['kind_lines_difference_usd'], 1e-6)
            self.assertAlmostEqual(back['estimated_layer_usd'], back['transcript_usd'], places=9)

    def test_it_matches_the_summary_total(self):
        for path in (SESSION_1, SESSION_3):
            session = parse.parse_session(path)
            self.assertAlmostEqual(estimate.build_estimate(session)['totals']['transcript_usd'],
                                   summarize.build_summary(session)['totals']['attributed_usd'], places=12)

    def test_kind_lines_add_up_to_the_total(self):
        for est in self.sessions():
            self.assertAlmostEqual(sum(r['usd'] for r in est['kinds']), est['totals']['transcript_usd'], places=9)
            self.assertAlmostEqual(sum(r['share'] for r in est['kinds']), 1.0, places=9)
            self.assertEqual([r['label'] for r in est['kinds']][:3], ['Starting context', 'Your prompts', 'Thinking'])

    def test_a_broken_sum_raises_and_the_error_says_so(self):
        with self.assertRaises(estimate.ReceiptError) as caught:
            estimate._check_sum_back(1.0, [{'new_usd': 0.4, 'carried_usd': 0.4}], [{'output_usd': 0.1}], 0.0,
                                     [{'usd': 0.9}])
        self.assertIn('does not add back up', str(caught.exception))
        ok = estimate._check_sum_back(1.0, [{'new_usd': 0.4, 'carried_usd': 0.4}], [{'output_usd': 0.1}], 0.1,
                                      [{'usd': 1.0}])
        self.assertLessEqual(ok['difference_usd'], 1e-6)

    def test_a_session_with_no_model_calls_cannot_be_built(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'empty.jsonl')
            with open(path, 'w') as handle:
                handle.write('{"type":"user","timestamp":"2026-01-01T00:00:00.000Z","message":{"role":"user","content":"x"}}\n')
            with self.assertRaises(estimate.ReceiptError):
                build(path)


class NoNegativesTest(DemoCase):
    def test_no_negative_tokens_or_costs(self):
        for est in [self.est] + [build(p) for p in ALL_FIXTURES]:
            for item in est['items']:
                self.assertGreaterEqual(item['tokens'], 0)
                self.assertGreaterEqual(item['new_usd'], -1e-12)
                self.assertGreaterEqual(item['carried_usd'], -1e-12)
            for step in est['steps']:
                self.assertGreaterEqual(step['material_tokens'], 0)
                self.assertGreaterEqual(step['total_usd'], 0)
            for row in est['kinds']:
                self.assertGreaterEqual(row['usd'], -1e-12)
            for row in est['files']:
                self.assertGreaterEqual(row['tokens_in'], 0)


class AllocationTest(DemoCase):
    def test_first_call_bill_goes_to_the_starting_context_and_the_first_prompt(self):
        first = [i for i in self.est['items'] if i['born'] == 0 and i['chain'] == 0]
        self.assertEqual({i['kind'] for i in first}, {'start', 'prompt'})
        self.assertAlmostEqual(sum(i['tokens'] for i in first), self.session['calls'][0]['tokens']['cache_read']
                               + self.session['calls'][0]['tokens']['cache_write_5m'] + 3, places=6)
        self.assertAlmostEqual(sum(i['new_usd'] for i in first), prices.price_call(self.session['calls'][0])
                               - self.steps[1]['output_usd'], places=9)

    def test_output_cost_is_exact_and_thinking_is_separate(self):
        step = self.steps[27]  # the heavy-thinking step
        self.assertEqual(step['thinking_tokens'], 6000)
        self.assertAlmostEqual(step['thinking_usd'], 6000 * 10 / 1e6, places=12)
        self.assertAlmostEqual(step['output_usd'], 6600 * 10 / 1e6, places=12)
        self.assertAlmostEqual(self.est['kinds'][2]['usd'], sum(s['thinking_usd'] for s in self.est['steps']), places=12)
        self.assertTrue(self.est['kinds'][2]['exact'])

    def test_a_big_result_is_carried_through_the_later_calls(self):
        read = self.steps[2]  # the first read of the large file
        self.assertGreater(read['material_tokens'], 12000)
        self.assertEqual(read['resent_calls'], 36 - 2 - 1)  # sent on call 3, re-sent on calls 4 to 36
        self.assertGreater(read['carried_usd'], read['new_usd'])
        self.assertGreater(read['total_usd'], self.steps[3]['total_usd'] * 5)

    def test_the_cache_rebuild_is_flagged_with_its_pause_and_reason(self):
        rebuilt = [s for s in self.est['steps'] if s['rebuild']]
        self.assertEqual([s['number'] for s in rebuilt], [19])
        info = rebuilt[0]['rebuild']
        self.assertAlmostEqual(info['pause_minutes'], 25, delta=2)
        self.assertEqual(info['miss_reason'], 'previous_message_not_found')
        self.assertGreater(info['tokens_written'], 70000)
        self.assertEqual(self.est['rebuilds'], 1)

    def test_rebuild_dollars_go_to_older_items_as_carried_cost(self):
        step = self.steps[19]
        call = [c for c in self.session['calls'] if c['id'] == 'msg_main_018'][0]  # the 19th main-thread call
        self.assertGreater(step['rebuild']['rewritten_usd'], 0.2 * prices.price_call(call))
        self.assertLess(step['rebuild']['rewritten_usd'], prices.price_call(call))

    def test_no_pair_is_skipped_in_a_clean_session(self):
        self.assertEqual(self.est['skipped_pairs'], 0)

    def test_subagent_total_is_rolled_into_the_step_that_launched_it(self):
        step = self.steps[22]
        self.assertEqual(step['subagent']['calls'], 5)
        sub_total = sum(c['usd'] for c in self.session['calls'] if c['source'] == 'subagent')
        self.assertAlmostEqual(step['subagent']['usd'], sub_total, places=12)
        self.assertAlmostEqual(step['total_usd'], step['output_usd'] + step['new_usd'] + step['carried_usd'] + sub_total, places=12)
        self.assertEqual(self.est['unlinked_subagents'], [])
        self.assertEqual(sorted({s['number'] for s in self.est['steps'] if s['subagent']}), [22])
        self.assertAlmostEqual(self.est['kinds'][9]['usd'] - sub_total, step['kind_split'].get('subagent', 0), places=9)

    def test_kinds_for_the_demo_steps(self):
        kinds = {n: s['kind'] for n, s in self.steps.items()}
        self.assertEqual((kinds[1], kinds[2], kinds[3], kinds[6], kinds[8], kinds[12], kinds[19], kinds[22]),
                         ('search', 'read_file', 'search', 'run_command', 'write_edit', 'answer', 'write_edit', 'subagent'))
        self.assertEqual(kinds[31], 'read_file')  # cat file | head: a read hidden in Bash
        self.assertEqual(kinds[32], 'write_edit')  # cat > file <<EOF
        self.assertEqual(self.steps[4]['description'], 'Read recipes.py')
        self.assertEqual(self.steps[3]['description'], 'Ran grep and head')
        self.assertEqual(self.steps[12]['description'], 'Answered')

    def test_a_mixed_step_splits_by_result_length(self):
        step = {'output_usd': 0.0, 'thinking_usd': 0.0, 'new_usd': 1.0, 'carried_usd': 0.0, 'tool_calls': [
            {'tool': 'Read', 'result_chars': 300, 'bash': None}, {'tool': 'Grep', 'result_chars': 100, 'bash': None}]}
        split = estimate.step_kind_split(step)
        self.assertAlmostEqual(split['read_file'], 0.75)
        self.assertAlmostEqual(split['search'], 0.25)
        step['tool_calls'][0]['result_chars'] = step['tool_calls'][1]['result_chars'] = None
        self.assertAlmostEqual(estimate.step_kind_split(step)['read_file'], 0.5)


class FilesTableTest(DemoCase):
    def test_reads_writes_and_shell_reads_are_counted(self):
        files = {os.path.basename(f['path']): f for f in self.est['files']}
        inventory = files['inventory.py']
        self.assertEqual((inventory['reads'], inventory['writes'], inventory['read_more_than_once']), (3, 2, True))
        self.assertEqual((files['report.py']['bash_reads'], files['report.py']['writes']), (1, 5))
        self.assertEqual((files['recipes.py']['reads'], files['recipes.py']['bash_reads']), (1, 1))
        self.assertFalse(files['NOTES.md']['read_more_than_once'])
        self.assertEqual(self.est['files'][0]['path'], os.path.join('/demo/pantry-planner', 'pantry/inventory.py'))
        self.assertGreater(inventory['tokens_in'], 30000)


class DiagnosisTest(DemoCase):
    def test_three_steps_each_with_a_template_sentence(self):
        top = self.est['findings']['top_steps']
        self.assertEqual(len(top), 3)
        self.assertEqual([t['total_usd'] for t in top], sorted((t['total_usd'] for t in top), reverse=True))
        for item in top:
            self.assertIn(item['id'], ('subagent', 'rebuild', 'large_result', 'thinking', 'writing'))
            self.assertRegex(item['sentence'], r'exact|est\.')
        self.assertEqual({t['id'] for t in top}, {'large_result'})
        self.assertIn('later calls', top[0]['sentence'])

    def test_each_template_can_be_produced(self):
        base = {'new_usd': 0.0, 'carried_usd': 0.0, 'thinking_usd': 0.0, 'output_usd': 0.0, 'subagent': None, 'rebuild': None,
                'material_tokens': 0, 'resent_calls': 0, 'tokens': {'output': 1000}, 'thinking_tokens': 0}
        cases = {
            'subagent': dict(base, subagent={'usd': 1.0, 'calls': 12, 'agents': 1}),
            'rebuild': dict(base, rebuild={'rewritten_usd': 1.0, 'pause_minutes': 18.0, 'tokens_written': 90000, 'miss_reason': None}),
            'large_result': dict(base, new_usd=0.2, carried_usd=0.8, material_tokens=30000, resent_calls=40),
            'thinking': dict(base, thinking_usd=1.0, output_usd=1.0, thinking_tokens=900, tokens={'output': 1000}),
            'writing': dict(base, output_usd=1.0, tokens={'output': 5000}),
        }
        from src import diagnose
        for expected, step in cases.items():
            why = diagnose._why(step, diagnose._why_id(step))
            self.assertEqual(why['id'], expected)
        self.assertIn('12 model calls', diagnose._why(cases['subagent'], 'subagent')['sentence'])
        self.assertIn('18 minutes', diagnose._why(cases['rebuild'], 'rebuild')['sentence'])
        self.assertIn('40 later calls', diagnose._why(cases['large_result'], 'large_result')['sentence'])

    def test_session_findings_state_facts_and_give_no_advice(self):
        found = {f['id']: f for f in self.est['findings']['session']}
        self.assertEqual(set(found), {'starting_context_share', 'resent_share', 'file_read_repeatedly'})
        self.assertIn('inventory.py was read 3 times', found['file_read_repeatedly']['sentence'])
        for finding in found.values():
            self.assertTrue(finding['numbers'])
            self.assertNotRegex(finding['sentence'].lower(), r'\b(should|try|consider|avoid|recommend)\b')

    def test_a_compaction_finding_appears_after_a_compact_boundary(self):
        found = {f['id']: f for f in build(SESSION_1)['findings']['session']}
        self.assertEqual(found['compaction']['numbers']['count'], 1)


class SpecialSessionsTest(unittest.TestCase):
    def test_one_call_and_no_tools_live_session_without_cost_state(self):
        est = build(SESSION_2)
        self.assertEqual(len(est['steps']), 1)
        self.assertEqual(est['steps'][0]['description'], 'Answered')
        self.assertIsNone(est['recorded_total'])
        self.assertLessEqual(est['sum_back']['difference_usd'], 1e-6)

    def test_parallel_tool_calls_share_one_step(self):
        est = build(SESSION_1)
        first = est['steps'][0]
        self.assertEqual(len(first['tool_calls']), 2)
        self.assertEqual(first['description'], 'Read alpha.txt, Ran grep')
        self.assertAlmostEqual(sum(first['kind_split'].values()), first['output_usd'] + first['new_usd'] + first['carried_usd'], places=12)

    def test_a_compacted_session_starts_the_new_segment_from_a_summary(self):
        est = build(SESSION_1)
        summary = [i for i in est['items'] if i['label'] == 'Summary of the earlier conversation']
        self.assertEqual(len(summary), 1)
        self.assertEqual((summary[0]['kind'], summary[0]['chain']), ('start', 1))
        # nothing before the boundary is carried past it: every item of chain 1 was born in chain 1
        self.assertTrue(all(i['born'] >= 0 for i in est['items'] if i['chain'] == 1))

    def test_subagents_that_no_step_launched_are_listed(self):
        est = build(SESSION_1)
        self.assertEqual([(u['agent_id'], u['workflow_id']) for u in est['unlinked_subagents']], [('ag2', 'wf_test1')])
        linked = [s for s in est['steps'] if s['subagent']]
        self.assertEqual([(s['number'], s['subagent']['calls']) for s in linked], [(2, 2)])  # ag1 made two calls

    def test_calls_with_no_public_price_keep_tokens_and_drop_dollars(self):
        est = build(SESSION_1)
        step = [s for s in est['steps'] if not s['priced']][0]
        self.assertEqual(step['total_usd'], 0.0)
        self.assertEqual(step['tokens']['output'], 5)
        self.assertEqual(est['models_without_public_price'], ['claude-unknown-9'])
        self.assertEqual(est['totals']['calls_without_public_price'], 1)

    def test_price_components_add_up_to_price_call(self):
        for path in ALL_FIXTURES:
            for call in parse.parse_session(path)['calls']:
                parts = prices.price_components(call)
                if parts is None:
                    self.assertIsNone(prices.price_call(call))
                else:
                    self.assertAlmostEqual(sum(parts.values()), prices.price_call(call), places=15)

    def test_typed_prompt_is_sized_from_its_length_and_taken_out_of_the_growth(self):
        est = build(SESSION_3)
        prompts = [i for i in est['items'] if i['kind'] == 'prompt']
        second = [i for i in prompts if i['born'] > 0][0]
        self.assertAlmostEqual(second['tokens'], 300 / estimate.CHARS_PER_TOKEN, places=6)
        material = [s for s in est['steps']][1]  # the step whose results arrived with that prompt
        self.assertGreater(material['material_tokens'], 1000)

    def test_the_estimate_holds_no_prompt_text_file_contents_or_tool_output(self):
        dumped = json.dumps([build(p) for p in ALL_FIXTURES], default=str)
        for text in PRIVATE_STRINGS + RECEIPT_MARKERS:
            self.assertNotIn(text, dumped)
        with tempfile.TemporaryDirectory() as folder:
            demo_path = write_demo_session(folder)
            raw = open(demo_path).read()
            demo = json.dumps(build(demo_path), default=str)
        for text in MARKERS:
            self.assertIn(text, raw)  # the markers really are in the made-up log...
            self.assertNotIn(text, demo)  # ...and none of them reaches the estimate


if __name__ == '__main__':
    unittest.main()
