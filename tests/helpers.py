"""Shared paths and strings for the tests. All fixture content is invented."""
import os

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
PROJECT_DIR = os.path.join(FIXTURE_ROOT, '-work-demo')  # "-work-demo" is how "/work/demo" is encoded
SESSION_1 = os.path.join(PROJECT_DIR, 'sess-0001.jsonl')
SESSION_2 = os.path.join(PROJECT_DIR, 'sess-0002.jsonl')

# Text that exists only in the fixtures' prompts, tool inputs, and tool results.
# None of it may ever reach a parsed structure, the printed summary, or the JSON.
PRIVATE_STRINGS = (
    'invented prompt text', 'invented thought', 'invented reply text', 'SECRETRESULTONE', 'abcde',
    'SECRETPATTERN', 'SECRETSUBAGENTPROMPT', 'OLDSECRET', 'NEWSECRET', 'FETCHEDBODY', 'SEARCHHITS',
    'skill loaded', 'AGENTDONE', 'SUBRES1', 'invented final answer', 'invented boundary text',
)
