"""Parse Claude Code session logs into one record per model call.

Read only. Streams each file line by line. Keeps structure, counts, token numbers, and tool
targets. Never keeps prompt text, file contents, or tool output (see docs/SCHEMA.md).
"""
import glob
import json
import os
import re
from collections import Counter

from .bash import analyze_command, first_word

PROJECTS_ROOT = os.path.expanduser('~/.claude/projects')
SYNTHETIC_MODEL = '<synthetic>'
RECORD_TYPES = ('assistant', 'user', 'system', 'cost-state', 'attachment')
_TYPE_RE = re.compile(r'"type"\s*:\s*"(assistant|user|system|cost-state|attachment)"')
_SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')

_KNOWN_TOOLS = (
    'Bash', 'Read', 'Edit', 'MultiEdit', 'Write', 'NotebookEdit', 'Grep', 'Glob', 'WebFetch',
    'WebSearch', 'Agent', 'Workflow', 'Skill', 'ToolSearch', 'Monitor', 'TaskStop',
    'AskUserQuestion', 'StructuredOutput', 'ReadNotifications', 'SendMessage', 'Artifact',
    'ListAgents', 'SendUserFile', 'TodoWrite',
)
CANONICAL_TOOLS = {name.lower(): name for name in _KNOWN_TOOLS}
CANONICAL_TOOLS['task'] = 'Agent'  # older name of the Agent tool

# tool -> (input key holding the target, what kind of target it is)
TARGET_KEYS = {
    'Read': ('file_path', 'file_path'), 'Edit': ('file_path', 'file_path'),
    'MultiEdit': ('file_path', 'file_path'), 'Write': ('file_path', 'file_path'),
    'NotebookEdit': ('notebook_path', 'file_path'), 'WebFetch': ('url', 'url'),
    'WebSearch': ('query', 'query'), 'Skill': ('skill', 'skill'),
    'Agent': ('subagent_type', 'subagent_type'),
}
_MAX_TARGET_CHARS = 300


# ---------------------------------------------------------------- small helpers

def _int(value):
    """Return value as an int when it is a real number, else 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def canonical_tool(name):
    """Map a tool name to its canonical spelling, ignoring case. Unknown names pass through."""
    if not isinstance(name, str) or not name:
        return '?'
    return CANONICAL_TOOLS.get(name.lower(), name)


def bash_first_word(command):
    """Return only the first word of a shell command, skipping VAR=value prefixes."""
    return first_word(command)


def tool_target(tool, tool_input):
    """Return (target, kind) for a tool call. Bash keeps only its first word."""
    if not isinstance(tool_input, dict):
        return None, None
    if tool == 'Bash':
        word = bash_first_word(tool_input.get('command'))
        return word, ('command_word' if word else None)
    key, kind = TARGET_KEYS.get(tool, (None, None))
    value = tool_input.get(key) if key else None
    if isinstance(value, str) and value:
        return value[:_MAX_TARGET_CHARS], kind
    return None, None


def usage_tokens(usage):
    """Return (tokens, split_known) from a message.usage dict. Missing fields count as 0."""
    usage = usage if isinstance(usage, dict) else {}
    total_write = _int(usage.get('cache_creation_input_tokens'))
    split = usage.get('cache_creation')
    split_known = isinstance(split, dict)
    write_5m = _int(split.get('ephemeral_5m_input_tokens')) if split_known else 0
    write_1h = _int(split.get('ephemeral_1h_input_tokens')) if split_known else 0
    if write_5m + write_1h < total_write:  # no split, or a split that does not add up
        write_5m += total_write - write_5m - write_1h
        split_known = False
    tokens = {
        'input': _int(usage.get('input_tokens')),
        'cache_read': _int(usage.get('cache_read_input_tokens')),
        'cache_write_5m': write_5m,
        'cache_write_1h': write_1h,
        'output': _int(usage.get('output_tokens')),
    }
    return tokens, split_known


def _result_size(content):
    """Return (characters of text, number of non-text blocks) for a tool_result content."""
    if isinstance(content, str):
        return len(content), 0
    chars = other = 0
    if isinstance(content, list):
        for block in content:
            text = block.get('text') if isinstance(block, dict) else None
            if isinstance(text, str):
                chars += len(text)
            else:
                other += 1
    return chars, other


# ---------------------------------------------------------------- one file

def iter_records(path, counters):
    """Yield (line_no, record) for the record types we use. Attachments only if they are queued prompts."""
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line_no, line in enumerate(handle):
            match = _TYPE_RE.search(line)
            if not match or (match.group(1) == 'attachment' and 'queued_command' not in line):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                counters['bad_lines'] += 1
                continue
            if isinstance(record, dict) and record.get('type') in RECORD_TYPES:
                yield line_no, record


def _new_call(record, message, source, agent_id, segment, line_no):
    """Build the call record for the first assistant record of a response."""
    tokens, split_known = usage_tokens(message.get('usage'))
    usage = message.get('usage') or {}
    details = usage.get('output_tokens_details')
    server_tools = usage.get('server_tool_use')
    server_tools = server_tools if isinstance(server_tools, dict) else {}
    return {
        'id': message['id'],
        'timestamp': record.get('timestamp') if isinstance(record.get('timestamp'), str) else '',
        'model': message['model'],
        'source': source,
        'agent_id': agent_id,
        'segment': segment,
        'tokens': tokens,
        'cache_write_split_known': split_known,
        'thinking_tokens': _int(details.get('thinking_tokens')) if isinstance(details, dict) else 0,
        'speed': usage.get('speed'),
        'service_tier': usage.get('service_tier'),
        'inference_geo': usage.get('inference_geo'),
        'web_search_requests': _int(server_tools.get('web_search_requests')),
        'web_fetch_requests': _int(server_tools.get('web_fetch_requests')),
        'stop_reason': None,
        'cache_miss_reason': None,
        'tool_calls': [],
        '_line_no': line_no,
    }


def _merge_assistant(call, record, message, counters):
    """Fold a later record of the same response into its call (usage is counted once)."""
    tokens, _ = usage_tokens(message.get('usage'))
    if tokens != call['tokens']:
        counters['usage_mismatch'] += 1
    if message.get('stop_reason'):
        call['stop_reason'] = message['stop_reason']
    diagnostics = message.get('diagnostics')
    miss = diagnostics.get('cache_miss_reason') if isinstance(diagnostics, dict) else None
    if isinstance(miss, dict) and isinstance(miss.get('type'), str) and not call['cache_miss_reason']:
        call['cache_miss_reason'] = miss['type']
    known = {t['tool_use_id'] for t in call['tool_calls']}
    content = message.get('content')
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get('type') != 'tool_use':
            continue
        tool_use_id = block.get('id')
        if not isinstance(tool_use_id, str) or tool_use_id in known:
            continue
        tool = canonical_tool(block.get('name'))
        tool_input = block.get('input')
        target, kind = tool_target(tool, tool_input)
        bash = None
        if tool == 'Bash':  # the command itself is never kept, only its classification
            bash = analyze_command(tool_input.get('command') if isinstance(tool_input, dict) else None)
        call['tool_calls'].append({
            'tool_use_id': tool_use_id, 'tool': tool, 'target': target, 'target_kind': kind,
            'result_chars': None, 'result_nontext_blocks': None, 'is_error': None,
            'spawned_agent_id': None, 'spawned_workflow_id': None, 'bash': bash,
        })
        known.add(tool_use_id)


def _add_assistant(state, record, line_no):
    """Handle one assistant record: skip synthetic and error records, else add or merge."""
    message = record.get('message')
    if not isinstance(message, dict):
        return
    model, message_id = message.get('model'), message.get('id')
    if record.get('isApiErrorMessage') or model == SYNTHETIC_MODEL:
        state['counters']['skipped_synthetic_or_error'] += 1
        return
    if not (isinstance(model, str) and isinstance(message_id, str)
            and isinstance(message.get('usage'), dict)):
        state['counters']['skipped_no_usage'] += 1
        return
    call = state['calls'].get(message_id)
    if call is None:
        call = _new_call(record, message, state['source'], state['agent_id'],
                         len(state['boundaries']), line_no)
        state['calls'][message_id] = call
    _merge_assistant(call, record, message, state['counters'])


def _safe_id(value):
    """Return value if it looks like a plain id (letters, digits, - and _), else None."""
    return value if isinstance(value, str) and _SAFE_ID.match(value) else None


def _workflow_id(result):
    """The workflow folder name a Workflow tool result points to (from transcriptDir or runId)."""
    if not isinstance(result, dict):
        return None
    folder = result.get('transcriptDir')
    if isinstance(folder, str) and folder:
        return _safe_id(os.path.basename(folder.rstrip('/\\')))
    return _safe_id(result.get('runId'))


def _add_user(state, record):
    """Handle one user record: store tool-result sizes, or note a typed prompt's length."""
    message = record.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    result = record.get('toolUseResult')
    agent_id = _safe_id(result.get('agentId')) if isinstance(result, dict) else None
    workflow_id = _workflow_id(result)
    found_result = False
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get('type') != 'tool_result':
            continue
        found_result = True
        tool_use_id = block.get('tool_use_id')
        if not isinstance(tool_use_id, str):
            continue
        chars, other = _result_size(block.get('content'))
        state['results'][tool_use_id] = {
            'chars': chars, 'nontext_blocks': other, 'is_error': bool(block.get('is_error')),
            'agent_id': agent_id, 'workflow_id': workflow_id,
        }
    if not found_result:
        _add_prompt(state, record, content)


def _prompt_kind(record):
    """'summary' for a compaction summary, None for harness-injected text, else 'typed'."""
    if record.get('isCompactSummary'):
        return 'summary'
    origin = record.get('origin')
    origin_kind = origin.get('kind') if isinstance(origin, dict) else None
    if record.get('isMeta') or (isinstance(origin_kind, str) and origin_kind != 'human'):
        return None
    return 'typed'


def _add_prompt(state, record, content, kind=None):
    """Note the length (never the text) of a typed prompt or a compaction summary."""
    kind = kind or _prompt_kind(record)
    if kind is None:
        return
    chars, images = _result_size(content)
    stamp = record.get('timestamp')
    state['prompts'].append({
        'timestamp': stamp if isinstance(stamp, str) else '', 'chars': chars, 'images': images,
        'kind': kind, 'source': state['source'], 'agent_id': state['agent_id'],
        'segment': len(state['boundaries']) if state['source'] == 'main' else None,
    })


def _add_attachment(state, record):
    """A prompt typed while the agent was busy arrives as a queued_command attachment."""
    attachment = record.get('attachment')
    if not isinstance(attachment, dict) or attachment.get('type') != 'queued_command':
        return
    if attachment.get('commandMode') == 'prompt':
        stamped = dict(record, timestamp=attachment.get('timestamp') or record.get('timestamp'))
        _add_prompt(state, stamped, attachment.get('prompt'), kind='typed')


def _add_boundary(state, record):
    """Handle a system record: note compact_boundary records (counts and token numbers only)."""
    if record.get('subtype') != 'compact_boundary':
        return
    meta = record.get('compactMetadata')
    meta = meta if isinstance(meta, dict) else {}
    trigger = meta.get('trigger')
    state['boundaries'].append({
        'timestamp': record.get('timestamp') if isinstance(record.get('timestamp'), str) else '',
        'trigger': trigger if isinstance(trigger, str) else None,
        'pre_tokens': _int(meta.get('preTokens')),
        'post_tokens': _int(meta.get('postTokens')),
    })


def parse_cost_state(record):
    """Normalize one cost-state record to numbers only: per-model tokens and costUSD."""
    models = {}
    usage = record.get('modelUsage')
    for model, entry in (usage.items() if isinstance(usage, dict) else []):
        entry = entry if isinstance(entry, dict) else {}
        write_5m = _int(entry.get('cacheCreationEphemeral5mInputTokens'))
        write_1h = _int(entry.get('cacheCreationEphemeral1hInputTokens'))
        total_write = _int(entry.get('cacheCreationInputTokens'))
        split_known = write_5m + write_1h >= total_write
        if not split_known:
            write_5m += total_write - write_5m - write_1h
        cost = entry.get('costUSD')
        models[model] = {
            'input': _int(entry.get('inputTokens')), 'output': _int(entry.get('outputTokens')),
            'cache_read': _int(entry.get('cacheReadInputTokens')),
            'cache_write_5m': write_5m, 'cache_write_1h': write_1h,
            'cache_write_split_known': split_known,
            'thinking': _int(entry.get('thinkingTokens')),
            'web_search': _int(entry.get('webSearchRequests')),
            'cost_usd': float(cost) if isinstance(cost, (int, float)) else 0.0,
        }
    total = record.get('totalCostUSD')
    return {'total_cost_usd': float(total) if isinstance(total, (int, float)) else 0.0,
            'models': models}


def parse_file(path, source, agent_id=None, workflow_id=None):
    """Stream one log file. Return its calls, results, prompts, boundaries, and cost-states."""
    state = {'source': source, 'agent_id': agent_id, 'calls': {}, 'results': {}, 'prompts': [],
             'boundaries': [], 'cost_states': [], 'counters': Counter(), 'cwd': None}
    for line_no, record in iter_records(path, state['counters']):
        kind = record['type']
        if state['cwd'] is None and isinstance(record.get('cwd'), str):
            state['cwd'] = record['cwd']
        if kind == 'assistant':
            _add_assistant(state, record, line_no)
        elif kind == 'user':
            _add_user(state, record)
        elif kind == 'system':
            _add_boundary(state, record)
        elif kind == 'attachment':
            _add_attachment(state, record)
        elif kind == 'cost-state' and source == 'main':
            state['cost_states'].append(parse_cost_state(record))
    for call in state['calls'].values():
        call['workflow_id'] = workflow_id
    return state


# ---------------------------------------------------------------- one session

def find_agent_files(session_path):
    """Return [(agent_id, path, is_workflow)] for every subagent file of a session."""
    session_dir = os.path.splitext(session_path)[0]
    pattern = os.path.join(glob.escape(session_dir), 'subagents', '**', 'agent-*.jsonl')
    found = []
    for path in sorted(glob.glob(pattern, recursive=True)):
        agent_id = os.path.basename(path)[len('agent-'):-len('.jsonl')]
        found.append((agent_id, path, os.sep + 'workflows' + os.sep in path))
    return found


def _attach_results(calls, results):
    """Join each tool call to its result by tool_use_id; keep size and error flag only."""
    for call in calls:
        for tool_call in call['tool_calls']:
            result = results.get(tool_call['tool_use_id'])
            if result is None:
                continue
            tool_call['result_chars'] = result['chars']
            tool_call['result_nontext_blocks'] = result['nontext_blocks']
            tool_call['is_error'] = result['is_error']
            if tool_call['tool'] == 'Agent':
                tool_call['spawned_agent_id'] = result['agent_id']
            elif tool_call['tool'] == 'Workflow':
                tool_call['spawned_workflow_id'] = result['workflow_id']


def _assign_segments(calls, boundaries):
    """Subagent calls join the main session's segment that was open at their timestamp."""
    stamps = [b['timestamp'] for b in boundaries]
    for call in calls:
        if call['source'] == 'subagent' and call['timestamp']:
            call['segment'] = sum(1 for stamp in stamps if stamp and stamp <= call['timestamp'])


def _order_calls(calls):
    """Sort calls by timestamp (main before subagent, then file order) and number them."""
    calls.sort(key=lambda c: (c['timestamp'], c['source'] != 'main', c['_line_no']))
    for index, call in enumerate(calls):
        call['order'] = index
        del call['_line_no']


def parse_session(path):
    """Parse a top-level session file and its subagent files into one normalized dict."""
    main = parse_file(path, 'main')
    agent_files = find_agent_files(path)
    parts = [main] + [parse_file(p, 'subagent', agent_id, os.path.basename(os.path.dirname(p)) if is_wf else None)
                      for agent_id, p, is_wf in agent_files]
    calls, results, counters, sub_boundaries = {}, {}, Counter(), 0
    for part in parts:
        results.update(part['results'])
        counters.update(part['counters'])
        sub_boundaries += len(part['boundaries']) if part is not main else 0
        for message_id, call in part['calls'].items():
            if message_id in calls:
                counters['duplicate_calls_skipped'] += 1
            else:
                calls[message_id] = call
    call_list = list(calls.values())
    prompts = sorted((pr for part in parts for pr in part['prompts']), key=lambda pr: pr['timestamp'])
    _assign_segments(call_list, main['boundaries'])
    _attach_results(call_list, results)
    _order_calls(call_list)
    cost_states = main['cost_states']
    return {
        'session_id': os.path.basename(path)[:-len('.jsonl')],
        'file_name': os.path.basename(path),
        'files': {'main': 1, 'subagent': sum(1 for _, _, wf in agent_files if not wf),
                  'workflow': sum(1 for _, _, wf in agent_files if wf)},
        'cwd': main['cwd'],
        'calls': call_list,
        'prompts': prompts,
        'segments': _segments(main['boundaries']),
        'compaction': {'main_boundaries': len(main['boundaries']),
                       'subagent_boundaries': sub_boundaries,
                       'compacted': bool(main['boundaries']) or bool(sub_boundaries)},
        'cost_state': {'records': len(cost_states),
                       'last': cost_states[-1] if cost_states else None},
        'warnings': dict(counters),
    }


def _segments(boundaries):
    """Describe the segments a session splits into at compact_boundary records."""
    segments = [{'index': 0, 'starts_at': None, 'trigger': None, 'pre_tokens': None,
                 'post_tokens': None}]
    for index, boundary in enumerate(boundaries, start=1):
        segments.append({'index': index, 'starts_at': boundary['timestamp'],
                         'trigger': boundary['trigger'], 'pre_tokens': boundary['pre_tokens'],
                         'post_tokens': boundary['post_tokens']})
    return segments


# ---------------------------------------------------------------- finding sessions

def encode_cwd(cwd):
    """Encode a working directory the way Claude Code names its project folders."""
    return re.sub(r'[^A-Za-z0-9]', '-', cwd)


def list_sessions(root=PROJECTS_ROOT):
    """Return every top-level session file under root, oldest first."""
    paths = glob.glob(os.path.join(glob.escape(root), '*', '*.jsonl'))
    return sorted(paths, key=os.path.getmtime)


def latest_session(cwd, root=PROJECTS_ROOT):
    """Return the most recently modified top-level session file for a working directory."""
    folder = os.path.join(root, encode_cwd(cwd))
    paths = glob.glob(os.path.join(glob.escape(folder), '*.jsonl'))
    if not paths:
        raise FileNotFoundError('no sessions found for this working directory')
    return max(paths, key=os.path.getmtime)


def resolve_session(arg, cwd, root=PROJECTS_ROOT):
    """Turn a path, a session id (or unique prefix), or 'latest' into a session file path."""
    if arg == 'latest':
        return latest_session(cwd, root)
    if os.path.isfile(arg):
        return arg
    matches = [p for p in list_sessions(root)
               if os.path.basename(p)[:-len('.jsonl')].startswith(arg)]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError('session not found' if not matches else 'session id is ambiguous')
