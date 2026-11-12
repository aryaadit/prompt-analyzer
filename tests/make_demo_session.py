"""Write a made-up Claude Code session log, for the demo receipt and for tests.

Everything here is invented: a pretend "pantry planner" project, invented file names, invented text.
The random seed is fixed, so the output is the same every time. The session has about 40 model
calls: a large file read early, the same file read three times, searches, test runs, edits, a long
write, heavy thinking, one subagent, and one cache rebuild after a 25-minute pause.

Marker strings (they all start with DEMO-) are planted in the prompts, tool outputs, file
contents, heredoc bodies, and an inline script. Tests assert that none of them reaches the receipt.
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

from src import prices

SESSION_ID = 'demo-0001'
CWD = '/demo/pantry-planner'
MODEL = 'claude-sonnet-5-5'
MARKERS = ('DEMO-PROMPT-MARKER', 'DEMO-OUTPUT-MARKER', 'DEMO-FILE-MARKER', 'DEMO-HEREDOC-MARKER',
           'DEMO-INLINE-MARKER', 'DEMO-EDIT-MARKER', 'DEMO-THOUGHT-MARKER', 'DEMO-ANSWER-MARKER')
START_CONTEXT_TOKENS = 21_000
CACHED_START_TOKENS = 18_000
CHARS_PER_TOKEN = 2.6

INVENTORY, RECIPES, TESTS = 'pantry/inventory.py', 'pantry/recipes.py', 'tests/test_inventory.py'
REPORT, README, NOTES = 'pantry/report.py', 'README.md', 'docs/NOTES.md'


def _text(chars, marker):
    """Invented text of exactly `chars` characters that starts with a marker."""
    text, line = marker + ' ', 0
    while len(text) < chars:
        text += 'line %d of invented pantry output\n' % line
        line += 1
    return text[:chars]


def _tool(name, tool_input, result_chars=0, marker='DEMO-OUTPUT-MARKER', error=False):
    """A tool call the invented model makes, and the size of the result that comes back."""
    return {'name': name, 'input': tool_input, 'chars': result_chars, 'marker': marker, 'error': error}


def _read(path, chars):
    return _tool('Read', {'file_path': '%s/%s' % (CWD, path)}, chars, 'DEMO-FILE-MARKER')


def _edit(path):
    return _tool('Edit', {'file_path': '%s/%s' % (CWD, path), 'old_string': 'DEMO-EDIT-MARKER old',
                          'new_string': 'DEMO-EDIT-MARKER new'}, 140)


def _bash(command, chars):
    return _tool('Bash', {'command': command, 'description': 'invented'}, chars)


PYTEST = 'cd %s && python3 -m pytest -q 2>&1 | tail -20' % CWD

# One row per main-thread model call. pause = minutes since the previous call (default under a minute).
# typed = a prompt the invented user typed right before the call. think = thinking tokens.
STEPS = [
    {'typed': 'DEMO-PROMPT-MARKER Please make items in the pantry planner warn me a few days before they expire, and add a report.',
     'tools': [_tool('Grep', {'pattern': 'def add_item', 'path': CWD}, 900)], 'out': 160, 'think': 90},
    {'tools': [_read(INVENTORY, 36000)], 'out': 90, 'think': 60},
    {'tools': [_bash('grep -rn "expiry" pantry tests | head -20', 1800)], 'out': 110, 'think': 120},
    {'tools': [_read(RECIPES, 9000)], 'out': 80},
    {'tools': [_read(TESTS, 6000)], 'out': 80},
    {'tools': [_bash(PYTEST, 2500)], 'out': 120, 'think': 200},
    {'tools': [_read(INVENTORY, 36000)], 'out': 90},
    {'tools': [_edit(INVENTORY)], 'out': 420, 'think': 300},
    {'tools': [_bash(PYTEST, 600)], 'out': 70},
    {'tools': [_bash('ls pantry && wc -l pantry/*.py', 500)], 'out': 90},
    {'tools': [_read(README, 3000)], 'out': 80},
    {'tools': [], 'out': 380, 'think': 150, 'answer': 'DEMO-ANSWER-MARKER The warning is in place.'},
    {'typed': 'DEMO-PROMPT-MARKER Good. Now make the recipes module use the same expiry rule.',
     'tools': [_tool('Grep', {'pattern': 'expiry_days', 'path': CWD}, 700)], 'out': 100},
    {'tools': [_read(INVENTORY, 36000)], 'out': 80, 'think': 80},
    {'tools': [_edit(RECIPES)], 'out': 360, 'think': 250},
    {'tools': [_edit(INVENTORY)], 'out': 300},
    {'tools': [_bash("sed -n '1,60p' pantry/recipes.py", 2400)], 'out': 90},
    {'tools': [_bash(PYTEST, 600)], 'out': 70},
    {'pause': 25, 'tools': [_tool('Write', {'file_path': '%s/%s' % (CWD, REPORT), 'content': 'DEMO-FILE-MARKER report'}, 120)],
     'out': 5400, 'think': 1800},
    {'tools': [_bash('python3 - <<\'PY\'\nprint("DEMO-INLINE-MARKER")\nPY', 300)], 'out': 90},
    {'tools': [_edit(REPORT)], 'out': 260},
    {'tools': [_tool('Agent', {'description': 'invented', 'prompt': 'DEMO-PROMPT-MARKER look around',
                              'subagent_type': 'explorer'}, 1500)], 'out': 150, 'subagent': True},
    {'tools': [_read(NOTES, 4500)], 'out': 80},
    {'tools': [_bash('git status && git diff | head -50', 3200)], 'out': 90},
    {'tools': [_bash(PYTEST, 600)], 'out': 70},
    {'tools': [_edit(README)], 'out': 300},
    {'tools': [_edit(REPORT)], 'out': 6600, 'think': 6000},
    {'tools': [_bash('rg -n "TODO" pantry', 800)], 'out': 80},
    {'tools': [_edit(REPORT)], 'out': 240},
    {'tools': [_bash(PYTEST, 600)], 'out': 70},
    {'typed': 'DEMO-PROMPT-MARKER Show me the top of the report.',
     'tools': [_bash('cat pantry/report.py | head -40', 2200)], 'out': 90},
    {'tools': [_bash('cat > pantry/notes.txt <<\'EOF\'\nDEMO-HEREDOC-MARKER\nEOF', 60)], 'out': 160},
    {'tools': [_edit(REPORT)], 'out': 220},
    {'tools': [_bash(PYTEST, 600)], 'out': 70},
    {'tools': [_bash('git add -A && git commit -q -m "expiry warnings and report"', 200)], 'out': 80},
    {'tools': [], 'out': 420, 'think': 100, 'answer': 'DEMO-ANSWER-MARKER Done: warnings and a report.'},
]
# The subagent: a few reads and an answer, in its own conversation.
SUBAGENT_STEPS = [
    {'tools': [_tool('Glob', {'pattern': '**/*.py'}, 600)], 'out': 70},
    {'tools': [_read(INVENTORY, 36000)], 'out': 90},
    {'tools': [_read(RECIPES, 9000)], 'out': 80},
    {'tools': [_bash('grep -n "def " pantry/report.py', 900)], 'out': 80},
    {'tools': [], 'out': 600, 'answer': 'DEMO-ANSWER-MARKER Summary of the layout.'},
]


class _Writer:
    """Builds one chain's log lines while tracking the conversation size."""

    def __init__(self, rng, agent_id=None):
        self.rng, self.agent_id = rng, agent_id
        self.lines, self.clock = [], datetime(2026, 3, 10, 14, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.size = 0
        self.totals = {'input': 0, 'cache_read': 0, 'cache_write_5m': 0, 'cache_write_1h': 0, 'output': 0, 'thinking': 0}

    def _stamp(self, seconds):
        self.clock += timedelta(seconds=seconds)
        return self.clock.strftime('%Y-%m-%dT%H:%M:%S.000Z')

    def _record(self, kind, stamp, **fields):
        self.seq += 1
        record = {'type': kind, 'uuid': '%s-%s-%d' % (SESSION_ID, self.agent_id or 'main', self.seq),
                  'sessionId': SESSION_ID, 'isSidechain': self.agent_id is not None, 'cwd': CWD, 'timestamp': stamp}
        if self.agent_id:
            record['agentId'] = self.agent_id
        record.update(fields)
        self.lines.append(json.dumps(record))

    def user_prompt(self, text, seconds=5):
        self._record('user', self._stamp(seconds), message={'role': 'user', 'content': text})
        return len(text) / CHARS_PER_TOKEN

    def call(self, index, step, new_tokens, rebuild, start, seconds):
        """One model call: its assistant records (one per block), then one result record per tool.

        The prompt is the previous prompt plus the new material. The cache read is the previous prompt,
        except on the first call and after a pause, when the cache is empty and everything is written.
        """
        stamp = self._stamp(seconds)
        out, think = step['out'], step.get('think', 0)
        new_tokens = int(round(new_tokens))
        if start:
            self.size = (START_CONTEXT_TOKENS if not self.agent_id else 6000) + new_tokens
            read = CACHED_START_TOKENS if not self.agent_id else 0
            write = self.size - read - 3
        elif rebuild:
            self.size += new_tokens
            read, write = 0, self.size - 3
        else:
            read, write = self.size, new_tokens - 3
            self.size += new_tokens
        usage = {'input_tokens': 3, 'cache_read_input_tokens': read, 'cache_creation_input_tokens': write,
                 'cache_creation': {'ephemeral_5m_input_tokens': write, 'ephemeral_1h_input_tokens': 0},
                 'output_tokens': out, 'output_tokens_details': {'thinking_tokens': think},
                 'server_tool_use': {'web_search_requests': 0, 'web_fetch_requests': 0},
                 'service_tier': 'standard', 'speed': 'standard', 'inference_geo': 'global'}
        for key, value in (('input', 3), ('cache_read', read), ('cache_write_5m', write), ('output', out), ('thinking', think)):
            self.totals[key] += value
        message_id = 'msg_%s_%03d' % (self.agent_id or 'main', index)
        blocks = []
        if think:
            blocks.append({'type': 'thinking', 'thinking': 'DEMO-THOUGHT-MARKER invented thought'})
        if step.get('answer'):
            blocks.append({'type': 'text', 'text': step['answer']})
        tool_ids = []
        for number, tool in enumerate(step['tools']):
            tool_id = 'toolu_%s_%03d_%d' % (self.agent_id or 'main', index, number)
            tool_ids.append(tool_id)
            blocks.append({'type': 'tool_use', 'id': tool_id, 'name': tool['name'], 'input': tool['input']})
        for number, block in enumerate(blocks):
            message = {'id': message_id, 'model': MODEL, 'role': 'assistant', 'content': [block], 'usage': usage,
                       'stop_reason': ('tool_use' if step['tools'] else 'end_turn') if number == len(blocks) - 1 else None}
            if rebuild and number == 0:
                message['diagnostics'] = {'cache_miss_reason': {'type': 'previous_message_not_found'}}
            self._record('assistant', stamp, message=message)
        return sum(self._result(tool, tool_id, 3) for tool, tool_id in zip(step['tools'], tool_ids))

    def _result(self, tool, tool_id, seconds):
        """The tool_result record for one tool call; returns its size in tokens."""
        content = _text(tool['chars'], tool['marker']) if tool['chars'] else 'ok'
        result = {'agentId': 'dm1', 'status': 'completed'} if tool['name'] == 'Agent' else {'type': 'text'}
        self._record('user', self._stamp(seconds), sourceToolAssistantUUID='x', toolUseResult=result,
                     message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': tool_id,
                                                           'is_error': tool['error'], 'content': content}]})
        return len(content) / CHARS_PER_TOKEN + 30


def _write_chain(writer, steps, first_prompt):
    """Play a list of steps through a writer. Each call's new material is the last call's output,
    its tool results, any typed prompt, and a little harness text."""
    carry = writer.user_prompt(first_prompt)
    for index, step in enumerate(steps):
        if index and step.get('typed'):
            carry += writer.user_prompt(step['typed'])
        rebuild = bool(step.get('pause'))
        seconds = step['pause'] * 60 if rebuild else writer.rng.randint(20, 90)
        harness = writer.rng.randint(0, 40) if index else 0
        results = writer.call(index, step, carry + harness, rebuild, index == 0, seconds)
        carry = step['out'] + results
    return writer


def write_demo_session(folder):
    """Write the invented session into `folder` and return the path of its main log file."""
    rng = random.Random(2026)
    project = os.path.join(folder, '-demo-pantry-planner')
    main = _Writer(rng)
    _write_chain(main, STEPS, STEPS[0]['typed'])
    sub = _Writer(random.Random(11), agent_id='dm1')
    sub.clock = main.clock - timedelta(minutes=30)
    _write_chain(sub, SUBAGENT_STEPS, 'DEMO-PROMPT-MARKER look around')
    main.lines.append(json.dumps({'type': 'cost-state', 'sessionId': SESSION_ID, **_cost_state(main, sub)}))
    os.makedirs(os.path.join(project, SESSION_ID, 'subagents'), exist_ok=True)
    path = os.path.join(project, SESSION_ID + '.jsonl')
    with open(path, 'w') as handle:
        handle.write('\n'.join(main.lines) + '\n')
    with open(os.path.join(project, SESSION_ID, 'subagents', 'agent-dm1.jsonl'), 'w') as handle:
        handle.write('\n'.join(sub.lines) + '\n')
    return path


def _cost_state(main, sub):
    """A cost-state record equal to the transcript, priced with the same table."""
    totals = {key: main.totals[key] + sub.totals[key] for key in main.totals}
    tokens = {k: totals[k] for k in prices.TOKEN_TYPES}
    cost = prices.price_aggregate(MODEL, tokens)
    usage = {'inputTokens': totals['input'], 'outputTokens': totals['output'],
             'cacheReadInputTokens': totals['cache_read'], 'cacheCreationInputTokens': totals['cache_write_5m'],
             'cacheCreationEphemeral5mInputTokens': totals['cache_write_5m'],
             'cacheCreationEphemeral1hInputTokens': 0, 'thinkingTokens': totals['thinking'],
             'webSearchRequests': 0, 'costUSD': cost}
    return {'totalCostUSD': cost, 'modelUsage': {MODEL: usage}}
