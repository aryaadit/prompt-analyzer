"""Tests for src/parse.py, run against the synthetic fixtures."""
import json
import os
import shutil
import tempfile
import unittest

from src import parse
from tests.helpers import FIXTURE_ROOT, PRIVATE_STRINGS, SESSION_1, SESSION_2


class ParseSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = parse.parse_session(SESSION_1)
        cls.calls = {c['id']: c for c in cls.session['calls']}

    def test_one_call_per_message_id(self):
        self.assertEqual(sorted(self.calls), ['msg_A', 'msg_B', 'msg_C', 'msg_D', 'msg_W1',
                                              'msg_X1', 'msg_X2'])
        self.assertEqual(len(self.session['calls']), 7)

    def test_multi_block_response_counts_usage_once(self):
        call = self.calls['msg_A']  # four records: thinking, text, two tool_use blocks
        self.assertEqual(call['tokens'], {'input': 10, 'cache_read': 1000, 'cache_write_5m': 150,
                                          'cache_write_1h': 50, 'output': 300})
        self.assertEqual(call['thinking_tokens'], 120)
        self.assertEqual(call['stop_reason'], 'tool_use')
        self.assertEqual(call['cache_miss_reason'], 'messages_changed')
        self.assertTrue(call['cache_write_split_known'])
        self.assertNotIn('usage_mismatch', self.session['warnings'])

    def test_parallel_tool_calls_join_to_results_by_id(self):
        read, bash = self.calls['msg_A']['tool_calls']
        self.assertEqual((read['tool'], read['target'], read['target_kind']),
                         ('Read', '/work/demo/alpha.txt', 'file_path'))
        self.assertEqual((read['result_chars'], read['is_error']), (15, False))
        self.assertEqual((bash['result_chars'], bash['result_nontext_blocks'], bash['is_error']),
                         (5, 1, True))

    def test_lowercase_tool_name_is_canonical_and_bash_keeps_first_word_only(self):
        bash = self.calls['msg_A']['tool_calls'][1]
        self.assertEqual((bash['tool'], bash['target'], bash['target_kind']),
                         ('Bash', 'grep', 'command_word'))

    def test_targets_for_each_tool(self):
        web, search, skill, edit = [(t['tool'], t['target']) for t in self.calls['msg_D']['tool_calls']]
        self.assertEqual(web, ('WebFetch', 'https://example.com/page'))
        self.assertEqual(search, ('WebSearch', 'invented query words'))
        self.assertEqual(skill, ('Skill', 'demo-skill'))
        self.assertEqual(edit, ('Edit', '/work/demo/beta.py'))
        agent = self.calls['msg_B']['tool_calls'][0]
        self.assertEqual((agent['tool'], agent['target']), ('Agent', 'explorer'))
        self.assertEqual(agent['spawned_agent_id'], 'ag1')

    def test_call_with_no_result_keeps_none(self):
        edit = self.calls['msg_D']['tool_calls'][3]
        self.assertIsNone(edit['result_chars'])
        self.assertIsNone(edit['is_error'])

    def test_missing_optional_fields_default_safely(self):
        opus = self.calls['msg_C']  # no cache_creation split, no details, no speed
        self.assertEqual(opus['tokens']['cache_write_5m'], 400)
        self.assertEqual(opus['tokens']['cache_write_1h'], 0)
        self.assertFalse(opus['cache_write_split_known'])
        self.assertEqual(opus['thinking_tokens'], 0)
        self.assertIsNone(opus['speed'])
        self.assertIsNone(opus['cache_miss_reason'])
        self.assertEqual(opus['web_search_requests'], 0)

    def test_synthetic_and_api_error_records_are_skipped(self):
        self.assertEqual(self.session['warnings']['skipped_synthetic_or_error'], 2)
        self.assertNotIn('msg_S', self.calls)
        self.assertNotIn('msg_E', self.calls)

    def test_subagent_and_workflow_files_are_read(self):
        self.assertEqual(self.session['files'], {'main': 1, 'subagent': 1, 'workflow': 1})
        self.assertEqual((self.calls['msg_X1']['source'], self.calls['msg_X1']['agent_id']),
                         ('subagent', 'ag1'))
        self.assertEqual(self.calls['msg_W1']['agent_id'], 'ag2')
        self.assertEqual(self.calls['msg_X1']['tool_calls'][0]['result_chars'], 7)

    def test_journal_file_is_not_treated_as_an_agent(self):
        agent_ids = [agent_id for agent_id, _, _ in parse.find_agent_files(SESSION_1)]
        self.assertEqual(agent_ids, ['ag1', 'ag2'])

    def test_compact_boundary_splits_segments(self):
        self.assertEqual(len(self.session['segments']), 2)
        boundary = self.session['segments'][1]
        self.assertEqual((boundary['trigger'], boundary['pre_tokens'], boundary['post_tokens']),
                         ('auto', 5000, 800))
        self.assertEqual(self.calls['msg_B']['segment'], 0)
        self.assertEqual(self.calls['msg_C']['segment'], 1)
        self.assertEqual(self.calls['msg_X1']['segment'], 0)  # subagent call before the boundary
        self.assertEqual(self.calls['msg_X2']['segment'], 1)  # subagent call after it
        self.assertTrue(self.session['compaction']['compacted'])

    def test_calls_are_ordered_by_timestamp(self):
        stamps = [c['timestamp'] for c in self.session['calls']]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual([c['order'] for c in self.session['calls']], list(range(7)))

    def test_cost_state_last_record_is_kept(self):
        self.assertEqual(self.session['cost_state']['records'], 2)
        last = self.session['cost_state']['last']
        self.assertAlmostEqual(last['total_cost_usd'], 0.0082)
        self.assertEqual(last['models']['claude-sonnet-5-5']['output'], 380)

    def test_no_private_text_in_the_parsed_structure(self):
        dumped = json.dumps(self.session)
        for text in PRIVATE_STRINGS:
            self.assertNotIn(text, dumped)

    def test_session_without_cost_state(self):
        session = parse.parse_session(SESSION_2)
        self.assertIsNone(session['cost_state']['last'])
        self.assertEqual(len(session['calls']), 1)
        self.assertFalse(session['compaction']['compacted'])


class HelperTest(unittest.TestCase):
    def test_bash_first_word(self):
        self.assertEqual(parse.bash_first_word('FOO=1 /usr/bin/grep -n x'), 'grep')
        self.assertEqual(parse.bash_first_word('cd /x && ls'), 'cd')
        self.assertEqual(parse.bash_first_word('$(evil)'), '?')
        self.assertIsNone(parse.bash_first_word('   '))
        self.assertIsNone(parse.bash_first_word(None))

    def test_canonical_tool_ignores_case(self):
        self.assertEqual(parse.canonical_tool('bash'), 'Bash')
        self.assertEqual(parse.canonical_tool('WEBFETCH'), 'WebFetch')
        self.assertEqual(parse.canonical_tool('mcp__demo__thing'), 'mcp__demo__thing')
        self.assertEqual(parse.canonical_tool(None), '?')

    def test_usage_tokens_handles_missing_and_inconsistent_fields(self):
        tokens, known = parse.usage_tokens({})
        self.assertEqual(sum(tokens.values()), 0)
        self.assertFalse(known)
        tokens, known = parse.usage_tokens({'cache_creation_input_tokens': 100, 'cache_creation': {
            'ephemeral_5m_input_tokens': 10, 'ephemeral_1h_input_tokens': 20}})
        self.assertEqual((tokens['cache_write_5m'], tokens['cache_write_1h']), (80, 20))
        self.assertFalse(known)
        tokens, _ = parse.usage_tokens({'input_tokens': True, 'output_tokens': 'x'})
        self.assertEqual((tokens['input'], tokens['output']), (0, 0))

    def test_bad_json_lines_are_counted_not_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'bad.jsonl')
            with open(path, 'w') as handle:
                handle.write('{"type":"assistant", broken\n{"type":"mode"}\n')
            session = parse.parse_session(path)
        self.assertEqual(session['warnings'], {'bad_lines': 1})
        self.assertEqual(session['calls'], [])


class FindingSessionsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        shutil.copytree(FIXTURE_ROOT, self.root, dirs_exist_ok=True)
        os.utime(os.path.join(self.root, '-work-demo', 'sess-0001.jsonl'), (1, 1))  # make 0002 newest

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_encode_cwd(self):
        self.assertEqual(parse.encode_cwd('/work/demo'), '-work-demo')
        self.assertEqual(parse.encode_cwd('/a b/c.d'), '-a-b-c-d')

    def test_latest_is_most_recent_for_the_working_directory(self):
        self.assertTrue(parse.latest_session('/work/demo', self.root).endswith('sess-0002.jsonl'))
        with self.assertRaises(FileNotFoundError):
            parse.latest_session('/nowhere', self.root)

    def test_resolve_path_id_prefix_and_latest(self):
        found = parse.resolve_session('sess-0001', '/work/demo', self.root)
        self.assertTrue(found.endswith('sess-0001.jsonl'))
        self.assertEqual(parse.resolve_session(found, '/work/demo', self.root), found)
        self.assertTrue(parse.resolve_session('latest', '/work/demo', self.root).endswith('sess-0002.jsonl'))
        with self.assertRaises(FileNotFoundError):
            parse.resolve_session('sess-', '/work/demo', self.root)  # ambiguous
        with self.assertRaises(FileNotFoundError):
            parse.resolve_session('zzz', '/work/demo', self.root)


if __name__ == '__main__':
    unittest.main()


class EffortTest(unittest.TestCase):
    """The effort of each call comes from the api-request params; nothing else of the request is kept."""

    def parse_lines(self, records):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, 'abc.jsonl')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(json.dumps(r) for r in records) + '\n')
        return {c['id']: c for c in parse.parse_session(path)['calls']}

    @staticmethod
    def reply(message_id, **extra):
        usage = {'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        record = {'type': 'assistant', 'timestamp': '2026-01-01T00:00:00Z',
                  'message': {'id': message_id, 'model': 'claude-sonnet-5-5', 'usage': usage, 'content': []}}
        record.update(extra)
        return record

    @staticmethod
    def request(request_id, effort='high', **params):
        params = dict(params, model='claude-sonnet-5-5', output_config={'effort': effort})
        return {'type': 'api-request', 'id': request_id, 'params': params}

    def test_effort_is_read_from_the_request_the_call_answers(self):
        calls = self.parse_lines([self.request('r1', 'high'), self.reply('m1', requestRef='r1'),
                                  self.request('r2', 'medium'), self.reply('m2', requestRef='r2')])
        self.assertEqual((calls['m1']['effort'], calls['m2']['effort']), ('high', 'medium'))

    def test_a_request_logged_after_its_reply_still_matches(self):
        calls = self.parse_lines([self.reply('m1', requestRef='r1'), self.request('r1', 'xhigh')])
        self.assertEqual(calls['m1']['effort'], 'xhigh')

    def test_the_assistant_records_own_effort_is_the_fallback(self):
        calls = self.parse_lines([self.reply('m1', effort='high'), self.reply('m2')])
        self.assertEqual((calls['m1']['effort'], calls['m2']['effort']), ('high', None))

    def test_odd_effort_values_are_ignored_and_nothing_else_of_the_request_is_kept(self):
        calls = self.parse_lines([self.request('r1', 'a long sentence, not a level', betas=['x']),
                                  self.reply('m1', requestRef='r1')])
        self.assertIsNone(calls['m1']['effort'])
        self.assertFalse([k for k in calls['m1'] if k.startswith('_') or k in ('params', 'betas')])
