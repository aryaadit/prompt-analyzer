"""Shared paths and strings for the tests. All fixture content is invented."""
import os

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
PROJECT_DIR = os.path.join(FIXTURE_ROOT, '-work-demo')  # "-work-demo" is how "/work/demo" is encoded
SESSION_1 = os.path.join(PROJECT_DIR, 'sess-0001.jsonl')
SESSION_2 = os.path.join(PROJECT_DIR, 'sess-0002.jsonl')
RECEIPT_ROOT = os.path.join(FIXTURE_ROOT, 'receipt')  # one level deeper, so the audit tests do not see it
SESSION_3 = os.path.join(RECEIPT_ROOT, '-work-demo', 'sess-0003.jsonl')
ALL_FIXTURES = (SESSION_1, SESSION_2, SESSION_3)

# Text that exists only in the fixtures' prompts, tool inputs, and tool results.
# None of it may ever reach a parsed structure, the printed summary, or the JSON.
PRIVATE_STRINGS = (
    'invented prompt text', 'invented thought', 'invented reply text', 'SECRETRESULTONE', 'abcde',
    'SECRETPATTERN', 'SECRETSUBAGENTPROMPT', 'OLDSECRET', 'NEWSECRET', 'FETCHEDBODY', 'SEARCHHITS',
    'skill loaded', 'AGENTDONE', 'SUBRES1', 'invented final answer', 'invented boundary text',
)

# Markers planted in the receipt fixture and in the made-up demo session. They must never reach the page or the JSON.
RECEIPT_MARKERS = (
    'SECRET-TYPED-PROMPT', 'SECRET-HEREDOC-BODY', 'SECRET-INLINE-SCRIPT', 'SECRET-QUOTED-ARG', 'SECRET-TOOL-OUTPUT',
    'SECRET-FILE-CONTENT', 'SECRET-SKILL-ARGS', 'SECRET-ANSWER-TEXT', 'invented line of text',
)
