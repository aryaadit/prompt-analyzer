"""The estimated layer: which step caused which tokens, and what it cost to keep re-sending them.

The session total is exact and stays exact. Estimates only decide how that exact total is split
between steps, and the split must add back up to the total (asserted on every build).

Vocabulary used in the code, the JSON, and the page:
  step            one model call, the tool calls it made, and the results that came back
  chain           the main thread within one segment, or one subagent; steps in a chain share a conversation
  item            a block of material in the conversation: starting context, a typed prompt,
                  harness text, or one step's material (its output and its results)
  output cost     what the model's own writing and thinking cost on a step (exact)
  new cost        what an item cost the first time it was sent to the model (estimated)
  carried cost    what it cost to send that item again on every later call (estimated)
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime

from . import bash, diagnose, paths, prices, summarize

CHARS_PER_TOKEN = 2.6  # typed text: measured on real logs (2.1 to 2.6 on clean gaps; harness text inflates growth)
REBUILD_FACTOR = 2.0  # a call "rebuilt the cache" when it paid for more than this many times the new tokens...
REBUILD_MIN_EXTRA = 5000  # ...and at least this many tokens more than were new
SUM_BACK_TOLERANCE = 0.000001

KIND_LINES = (
    ('start', 'Starting context'), ('prompt', 'Your prompts'), ('thinking', 'Thinking'),
    ('answer', 'Answers'), ('read_file', 'Reading files'), ('search', 'Searching'),
    ('run_command', 'Running commands'), ('write_edit', 'Writing and editing files'),
    ('web', 'Web'), ('subagent', 'Subagents'), ('other_tool', 'Other tools'),
    ('harness', 'Harness text'),
)
KIND_LABELS = dict(KIND_LINES)
_BASH_TO_KIND = {bash.SEARCH: 'search', bash.READ: 'read_file', bash.RUN: 'run_command',
                 bash.WRITE: 'write_edit', bash.WEB: 'web', bash.OTHER: 'run_command'}
_TOOL_KINDS = {'Read': 'read_file', 'Edit': 'write_edit', 'MultiEdit': 'write_edit',
               'Write': 'write_edit', 'NotebookEdit': 'write_edit', 'Grep': 'search',
               'Glob': 'search', 'WebFetch': 'web', 'WebSearch': 'web', 'Agent': 'subagent',
               'Workflow': 'subagent'}
_WRITE_TOOLS = ('Edit', 'MultiEdit', 'Write', 'NotebookEdit')


class ReceiptError(Exception):
    """The receipt cannot be built (for example, the sum-back check failed)."""


# ---------------------------------------------------------------- small helpers

def parse_time(text):
    """Parse an ISO timestamp from a log, or return None."""
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


def minutes_between(earlier, later):
    """Minutes between two log timestamps, or None when either cannot be read."""
    start, end = parse_time(earlier), parse_time(later)
    return None if start is None or end is None else (end - start).total_seconds() / 60.0


def tool_kind(tool_call):
    """The kind of one tool call (one of KIND_LINES' keys). Bash is classified by its commands."""
    if tool_call['tool'] == 'Bash' and tool_call.get('bash'):
        return _BASH_TO_KIND[tool_call['bash']['kind']]
    return _TOOL_KINDS.get(tool_call['tool'], 'other_tool')


def _call_dollars(call):
    """Split one call's exact bill: re-sent (cache read), new (input and writes), output, thinking."""
    parts = prices.price_components(call)
    if parts is None:
        return {'priced': False, 'read': 0.0, 'write': 0.0, 'output': 0.0, 'thinking': 0.0}
    out_tokens = call['tokens']['output']
    thinking = min(call['thinking_tokens'], out_tokens)
    return {'priced': True, 'read': parts['cache_read'],
            'write': parts['input'] + parts['cache_write_5m'] + parts['cache_write_1h'],
            'output': parts['output'] + parts['fees'],
            'thinking': parts['output'] * thinking / out_tokens if out_tokens else 0.0}


def _new_item(kind, label, tokens, born, step=None):
    """An item: a block of material in the conversation, with estimated tokens and costs."""
    return {'kind': kind, 'label': label, 'tokens': float(tokens), 'born': born, 'step': step,
            'new_usd': 0.0, 'carried_usd': 0.0}


def _spread(items, amount, field):
    """Add a dollar amount to items in proportion to their tokens (all to the first if none)."""
    total = sum(item['tokens'] for item in items)
    for item in items:
        item[field] += amount * item['tokens'] / total if total > 0 else (amount if item is items[0] else 0.0)


# ---------------------------------------------------------------- chains

def _make_chains(session):
    """Group calls into chains: main thread per segment, and one chain per subagent."""
    groups = {}
    for call in session['calls']:
        key = ('main', call['segment']) if call['source'] == 'main' else ('sub', call['agent_id'])
        groups.setdefault(key, []).append(call)
    prompts = defaultdict(list)
    for prompt in session['prompts']:
        key = ('main', prompt['segment']) if prompt['source'] == 'main' else ('sub', prompt['agent_id'])
        prompts[key].append(prompt)
    chains = []
    for key, calls in groups.items():
        chains.append({'key': key, 'kind': 'main' if key[0] == 'main' else 'subagent',
                       'segment': key[1] if key[0] == 'main' else None,
                       'agent_id': key[1] if key[0] == 'sub' else None,
                       'workflow_id': calls[0].get('workflow_id'), 'calls': calls,
                       'prompts': prompts.get(key, [])})
    chains.sort(key=lambda c: c['calls'][0]['order'])
    return chains


def _first_items(chain, call, typed_before):
    """Items in a chain's first prompt: starting context plus the typed prompt, or one summary."""
    total = prices.prompt_size(call['tokens'])
    if chain['kind'] == 'main' and chain['segment']:
        return [_new_item('start', 'Summary of the earlier conversation', total, 0)]
    chars = sum(p['chars'] for p in typed_before)
    typed_tokens = min(chars / CHARS_PER_TOKEN, total)
    label = 'Starting context' if chain['kind'] == 'main' else 'Instructions and starting context'
    items = [_new_item('start', label, total - typed_tokens, 0)]
    for prompt in typed_before:
        share = typed_tokens * prompt['chars'] / chars if chars else 0.0
        items.append(_new_item('prompt', 'Your prompt', share, 0))
    return items


def _gap_items(prev, call, typed_gap, prev_index, born):
    """Items that are new at `call`: the previous step's material, typed prompts, harness text.

    Returns (items, skipped). skipped is True when the prompt grew by less than the previous output
    (context was trimmed, or thinking was dropped), so the results cannot be sized from growth.
    """
    new_tokens = prices.prompt_size(call['tokens']) - prices.prompt_size(prev['tokens'])
    out_prev = prev['tokens']['output']
    typed_chars = sum(p['chars'] for p in typed_gap)
    typed_raw = typed_chars / CHARS_PER_TOKEN
    growth = new_tokens - out_prev
    has_results = any(t['result_chars'] is not None for t in prev['tool_calls'])
    harness = 0.0
    if new_tokens <= 0:
        skipped, typed, material = True, typed_raw, float(out_prev) or 1.0
    elif growth < 0:
        skipped = True
        typed = min(typed_raw, new_tokens)
        material = new_tokens - typed
    else:
        skipped = False
        typed = min(typed_raw, growth)
        rest = growth - typed
        material, harness = (out_prev + rest, 0.0) if has_results else (float(out_prev), rest)
    items = [_new_item('step', 'Step material', material, born, prev_index)]
    for prompt in typed_gap:
        share = typed * prompt['chars'] / typed_chars if typed_chars else 0.0
        items.append(_new_item('prompt', 'Your prompt', share, born))
    if harness > 0:
        items.append(_new_item('harness', 'Harness text', harness, born))
    return items, skipped, new_tokens


def _new_step(index, call, dollars):
    """A step's exact facts. Estimated fields are filled in after the chain is allocated."""
    return {'index': index, 'order': call['order'], 'call_id': call['id'], 'timestamp': call['timestamp'],
            'model': call['model'], 'tokens': call['tokens'], 'thinking_tokens': call['thinking_tokens'],
            'priced': dollars['priced'], 'output_usd': dollars['output'], 'thinking_usd': dollars['thinking'],
            'tool_calls': call['tool_calls'], 'stop_reason': call['stop_reason'],
            'segment': call['segment'], 'material_tokens': 0.0, 'new_usd': 0.0, 'carried_usd': 0.0,
            'resent_calls': 0, 'rebuild': None, 'growth_skipped': False, 'subagent': None,
            'prompt_tokens': prices.prompt_size(call['tokens'])}


def _rebuild_info(prev, call, dollars, new_tokens, new_total):
    """Detect a cache rebuild and return (new_pool, carried_pool, info) for the call's input bill."""
    tokens = call['tokens']
    paid = tokens['input'] + tokens['cache_write_5m'] + tokens['cache_write_1h']
    new_positive = max(new_tokens, 0)
    rebuilt = (dollars['priced'] and paid > REBUILD_FACTOR * new_positive
               and paid - new_positive >= REBUILD_MIN_EXTRA)
    if not rebuilt:
        return dollars['write'], dollars['read'], None
    write_rate = dollars['write'] / paid
    new_charge = min(new_total * write_rate, dollars['write'])
    rewritten = dollars['write'] - new_charge
    excess = max(paid - new_positive, 0)
    extra = max(rewritten - excess * (prices.resend_rate(call) or 0.0), 0.0)  # write price minus re-sent price
    info = {'pause_minutes': minutes_between(prev['timestamp'], call['timestamp']),
            'miss_reason': call['cache_miss_reason'], 'tokens_written': paid,
            'rewritten_usd': rewritten, 'excess_tokens': excess, 'extra_usd': extra,
            'call_usd': dollars['read'] + dollars['write'] + dollars['output']}
    return new_charge, dollars['read'] + dollars['write'] - new_charge, info


def allocate_chain(chain, stats):
    """Split every call's input bill across the items in the conversation, one chain at a time.

    Running sums keep this linear: an item born at call b is charged tokens x (C_end - C_b), where
    C is the running total of (carried dollars at each call / tokens of the older items).
    """
    calls = chain['calls']
    typed = [p for p in chain['prompts'] if p['kind'] == 'typed']
    stamps = [p['timestamp'] for p in typed]
    steps, items, cumulative = [], [], [0.0] * len(calls)
    old_tokens = 0.0
    for n, call in enumerate(calls):
        dollars = _call_dollars(call)
        steps.append(_new_step(n, call, dollars))
        if n == 0:
            new_items = _first_items(chain, call, typed[:bisect_right(stamps, call['timestamp'])])
            _spread(new_items, dollars['read'] + dollars['write'], 'new_usd')
        else:
            prev = calls[n - 1]
            lo, hi = bisect_right(stamps, prev['timestamp']), bisect_right(stamps, call['timestamp'])
            new_items, skipped, new_tokens = _gap_items(prev, call, typed[lo:hi], n - 1, n)
            steps[n - 1]['growth_skipped'] = skipped
            stats['skipped_pairs'] += skipped
            new_total = sum(item['tokens'] for item in new_items)
            new_pool, carried_pool, rebuild = _rebuild_info(prev, call, dollars, new_tokens, new_total)
            steps[n]['rebuild'] = rebuild
            stats['rebuilds'] += rebuild is not None
            if rebuild:
                stats['events'].append(dict(rebuild, chain=chain['kind'], agent_id=chain['agent_id'],
                                            order=call['order']))
            _spread(new_items, new_pool, 'new_usd')
            if old_tokens > 0:
                cumulative[n] = cumulative[n - 1] + carried_pool / old_tokens
            else:
                cumulative[n] = cumulative[n - 1]
                items[0]['carried_usd'] += carried_pool
        items.extend(new_items)
        old_tokens += sum(item['tokens'] for item in new_items)
    _finish_chain(chain, steps, items, cumulative)
    return steps, items


def _finish_chain(chain, steps, items, cumulative):
    """Charge each item its carried cost and copy item numbers onto the steps that own them."""
    last = len(chain['calls']) - 1
    for item in items:
        item['carried_usd'] += item['tokens'] * (cumulative[last] - cumulative[item['born']])
        item['resent_calls'] = max(last - item['born'], 0)
        if item['kind'] == 'step':
            step = steps[item['step']]
            step.update(material_tokens=item['tokens'], new_usd=item['new_usd'],
                        carried_usd=item['carried_usd'], resent_calls=item['resent_calls'])


# ---------------------------------------------------------------- kinds and descriptions

def _tool_weights(step):
    """Weight of each tool call in a step: its result length, or equal weights if all are empty."""
    weights = [t['result_chars'] or 0 for t in step['tool_calls']]
    return weights if sum(weights) > 0 else [1] * len(weights)


def step_kind_split(step):
    """Split a step's own dollars across kinds. Thinking is its own line; a step with no tool call
    is an answer; a step that mixed kinds is split by result length (equal if all are empty)."""
    base = (step['output_usd'] - step['thinking_usd']) + step['new_usd'] + step['carried_usd']
    split = defaultdict(float)
    split['thinking'] += step['thinking_usd']
    if not step['tool_calls']:
        split['answer'] += base
        return dict(split)
    weights = _tool_weights(step)
    for tool_call, weight in zip(step['tool_calls'], weights):
        split[tool_kind(tool_call)] += base * weight / sum(weights)
    return dict(split)


def primary_kind(step):
    """The kind that holds the most of a step's non-thinking dollars (for the row's colour chip)."""
    split = {k: v for k, v in step_kind_split(step).items() if k != 'thinking'}
    return max(split, key=split.get) if split else 'thinking'


def _words(items):
    """Join words: 'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def _phrase(tool_call):
    """Plain words for one tool call. File names are base names only."""
    tool, target = tool_call['tool'], tool_call['target']
    name = paths.basename(target) if target and tool_call['target_kind'] == 'file_path' else None
    if tool == 'Bash':
        words = (tool_call.get('bash') or {}).get('words') or []
        return 'Ran ' + (_words(words[:3]) if words else 'a command')
    if tool == 'Read':
        return 'Read ' + (name or 'a file')
    if tool in ('Edit', 'MultiEdit'):
        return 'Edited ' + (name or 'a file')
    if tool == 'Write':
        return 'Wrote ' + (name or 'a file')
    if tool == 'NotebookEdit':
        return 'Edited notebook ' + (name or '')
    fixed = {'Grep': 'Searched files', 'Glob': 'Listed files', 'WebSearch': 'Searched the web',
             'Workflow': 'Ran a workflow', 'ToolSearch': 'Looked up tools',
             'TodoWrite': 'Updated the to-do list', 'AskUserQuestion': 'Asked you a question'}
    if tool in fixed:
        return fixed[tool]
    if tool == 'WebFetch':
        return 'Fetched ' + (target.split('/')[2] if target and target.count('/') >= 2 else 'a web page')
    if tool == 'Agent':
        return 'Launched subagent ' + target if target else 'Launched a subagent'
    if tool == 'Skill':
        return 'Used skill ' + target if target else 'Used a skill'
    return 'Used ' + tool


def describe_step(step):
    """One plain-words line for a step, such as 'Read parse.py' or 'Ran grep and sed'."""
    if not step['tool_calls']:
        return 'Answered'
    phrases = []
    for tool_call in step['tool_calls']:
        phrase = _phrase(tool_call)
        if phrase not in phrases:
            phrases.append(phrase)
    text = ', '.join(phrases[:3])
    return text + (' and %d more' % (len(phrases) - 3) if len(phrases) > 3 else '')


# ---------------------------------------------------------------- subagents

def _link_subagents(chains):
    """Roll each subagent's exact total into the step that launched it. Returns the unlinked ones."""
    subs = {c['agent_id']: c for c in chains if c['kind'] == 'subagent'}
    members = defaultdict(list)
    for agent_id, chain in subs.items():
        if chain['workflow_id']:
            members[chain['workflow_id']].append(agent_id)
    children, parent = defaultdict(list), {}
    for chain in chains:
        for step in chain['steps']:
            for tool_call in step['tool_calls']:
                ids = [tool_call['spawned_agent_id']] if tool_call.get('spawned_agent_id') in subs else []
                ids += members.get(tool_call.get('spawned_workflow_id'), [])
                for agent_id in ids:
                    if agent_id not in parent and agent_id != chain['agent_id']:
                        parent[agent_id] = (chain['key'], step['index'])
                        children[(chain['key'], step['index'])].append(agent_id)
    totals = {}
    for agent_id, chain in subs.items():
        totals[agent_id] = sum(c['usd'] for c in chain['calls'] if c['usd'] is not None)

    def rolled(agent_id, stack):
        """(dollars, calls, agents) of a subagent and everything it launched."""
        usd, calls, agents = totals[agent_id], len(subs[agent_id]['calls']), 1
        for step in subs[agent_id]['steps']:
            for child in children.get((subs[agent_id]['key'], step['index']), []):
                if child not in stack:
                    c_usd, c_calls, c_agents = rolled(child, stack | {child})
                    usd, calls, agents = usd + c_usd, calls + c_calls, agents + c_agents
        return usd, calls, agents

    accounted = set()
    for chain in chains:
        if chain['kind'] != 'main':
            continue
        for step in chain['steps']:
            kids = children.get((chain['key'], step['index']), [])
            if kids:
                usd = calls = agents = 0
                for kid in kids:
                    k_usd, k_calls, k_agents = rolled(kid, {kid})
                    usd, calls, agents = usd + k_usd, calls + k_calls, agents + k_agents
                    accounted |= _reachable(kid, subs, children)
                step['subagent'] = {'usd': usd, 'calls': calls, 'agents': agents}
    return _unlinked(subs, parent, accounted, rolled, children)


def _reachable(root, subs, children):
    """Every subagent reachable from `root` through launch links (including itself)."""
    seen, todo = set(), [root]
    while todo:
        agent_id = todo.pop()
        if agent_id in seen:
            continue
        seen.add(agent_id)
        for step in subs[agent_id]['steps']:
            todo.extend(children.get((subs[agent_id]['key'], step['index']), []))
    return seen


def _unlinked(subs, parent, accounted, rolled, children):
    """Subagent roots that no step launched, plus anything cut off by a link cycle."""
    roots = [a for a in subs if a not in parent]
    leftovers = []
    for agent_id in roots:
        accounted |= _reachable(agent_id, subs, children)
    for agent_id in subs:
        if agent_id not in accounted:
            leftovers.append(agent_id)
            accounted |= _reachable(agent_id, subs, children)
    rows = []
    for agent_id in roots + [a for a in leftovers if a not in roots]:
        usd, calls, agents = rolled(agent_id, {agent_id})
        rows.append({'agent_id': agent_id, 'workflow_id': subs[agent_id]['workflow_id'],
                     'usd': usd, 'calls': calls, 'agents': agents})
    return rows


# ---------------------------------------------------------------- files table

def _path_key(path, cwd):
    """One key per file: absolute, with relative paths resolved against the project folder."""
    return paths.path_key(path, cwd)


def _file_events(step, cwd):
    """Yield (path key, 'read' or 'write', share of the step's material) for each file touched."""
    weights = _tool_weights(step)
    total = sum(weights) or 1
    for tool_call, weight in zip(step['tool_calls'], weights):
        share = weight / total
        if tool_call['tool'] == 'Read':
            yield _path_key(tool_call['target'], cwd), 'read', share
        elif tool_call['tool'] in _WRITE_TOOLS:
            yield _path_key(tool_call['target'], cwd), 'write', share
        elif tool_call['tool'] == 'Bash' and tool_call.get('bash') and tool_call['bash']['paths']:
            paths = tool_call['bash']['paths']
            for path in paths:
                yield _path_key(path, cwd), 'bash_read', share / len(paths)


def files_table(steps, cwd):
    """Per file: reads (Read tool plus Bash reads), writes, tokens brought in, new and carried cost."""
    files = {}
    for step in steps:
        results_tokens = max(step['material_tokens'] - step['tokens']['output'], 0.0)
        for key, kind, share in _file_events(step, cwd):
            if key is None:
                continue
            row = files.setdefault(key, {'path': key, 'reads': 0, 'bash_reads': 0, 'writes': 0,
                                         'tokens_in': 0.0, 'new_usd': 0.0, 'carried_usd': 0.0})
            row['reads'] += kind == 'read'
            row['bash_reads'] += kind == 'bash_read'
            row['writes'] += kind == 'write'
            row['tokens_in'] += results_tokens * share
            row['new_usd'] += step['new_usd'] * share
            row['carried_usd'] += step['carried_usd'] * share
    rows = sorted(files.values(), key=lambda r: -(r['new_usd'] + r['carried_usd']))
    for row in rows:
        row['read_more_than_once'] = row['reads'] + row['bash_reads'] > 1
    return rows


# ---------------------------------------------------------------- the whole estimate

def _kind_rows(items, steps, subagent_usd):
    """Roll every dollar up into the twelve lines. The lines add up to the transcript total."""
    usd = defaultdict(float)
    item_kinds = {'start': 'start', 'prompt': 'prompt', 'harness': 'harness'}
    for item in items:
        if item['kind'] in item_kinds:
            usd[item_kinds[item['kind']]] += item['new_usd'] + item['carried_usd']
    for step in steps:
        for kind, amount in step_kind_split(step).items():
            usd[kind] += amount
    usd['subagent'] += subagent_usd
    total = sum(usd.values())
    return [{'key': key, 'label': label, 'usd': usd[key], 'share': usd[key] / total if total else 0.0,
             'exact': key == 'thinking'} for key, label in KIND_LINES]


def _check_sum_back(transcript_usd, main_items, main_steps, subagent_usd, kinds):
    """Assert the estimate adds back to the transcript total. Raise ReceiptError if it does not."""
    estimated = (sum(i['new_usd'] + i['carried_usd'] for i in main_items)
                 + sum(s['output_usd'] for s in main_steps) + subagent_usd)
    by_kind = sum(row['usd'] for row in kinds)
    result = {'transcript_usd': transcript_usd, 'estimated_layer_usd': estimated,
              'difference_usd': abs(estimated - transcript_usd), 'kind_lines_difference_usd':
              abs(by_kind - transcript_usd), 'tolerance_usd': SUM_BACK_TOLERANCE}
    if max(result['difference_usd'], result['kind_lines_difference_usd']) > SUM_BACK_TOLERANCE:
        raise ReceiptError('the receipt does not add back up to the transcript total '
                           '(difference $%.9f), so it was not built' % result['difference_usd'])
    return result


def _session_facts(session, calls):
    """Title facts: project folder, dates, duration, models, counts."""
    stamps = [c['timestamp'] for c in calls if c['timestamp']] + [
        p['timestamp'] for p in session['prompts'] if p['timestamp']]
    models = defaultdict(float)
    for call in calls:
        models[call['model']] += call['usd'] or 0.0
    first, last = (min(stamps), max(stamps)) if stamps else ('', '')
    seconds = (minutes_between(first, last) or 0.0) * 60
    return {'session_id': session['session_id'], 'cwd': session['cwd'],
            'project': paths.basename(session['cwd']) or session['session_id'][:8],
            'started': first, 'ended': last, 'duration_seconds': seconds,
            'models': sorted(models, key=lambda m: -models[m]), 'calls': len(calls),
            'tool_calls': sum(len(c['tool_calls']) for c in calls)}


def _chain_usd(chain):
    """A chain's exact transcript dollars (calls with no public price count as zero)."""
    return sum(c['usd'] or 0.0 for c in chain['calls'])


def _chain_summary(chain, steps, items):
    """A short record of one chain for the JSON."""
    return {'kind': chain['kind'], 'segment': chain['segment'], 'agent_id': chain['agent_id'],
            'workflow_id': chain['workflow_id'], 'calls': len(chain['calls']),
            'usd': _chain_usd(chain),
            'first_prompt_tokens': prices.prompt_size(chain['calls'][0]['tokens']),
            'items': len(items)}


def _recorded_total(session):
    """Claude Code's own session total next to ours (as a low-to-high range), if it exists."""
    recon = summarize.reconciliation(session)
    if recon is None:
        return None
    totals = recon['totals']
    return {'session_total_usd_low': totals['session_total_usd_low'],
            'session_total_usd_high': totals['session_total_usd_high'],
            'gap_usd_low': totals['gap_usd_low'], 'gap_usd_high': totals['gap_usd_high'],
            'gap_tokens': totals['gap_tokens'],
            'cost_usd_reported': totals['cost_usd_reported_cross_check'],
            'models_without_public_price': totals['models_without_public_price']}


def build_estimate(session):
    """Build the estimated layer for a parsed session. Raises ReceiptError if it cannot."""
    summarize.price_calls(session['calls'])
    if not session['calls']:
        raise ReceiptError('this log has no model calls')
    stats = defaultdict(int)
    stats['events'] = []
    chains = _make_chains(session)
    all_items = {}
    for chain in chains:
        chain['steps'], all_items[chain['key']] = allocate_chain(chain, stats)
    unlinked = _link_subagents(chains)
    main = [c for c in chains if c['kind'] == 'main']
    main_steps = sorted((s for c in main for s in c['steps']), key=lambda s: s['order'])
    main_items = [dict(i, chain=c['key'][1]) for c in main for i in all_items[c['key']]]
    transcript_usd = summarize.build_summary(session)['totals']['attributed_usd']
    subagent_usd = sum(_chain_usd(c) for c in chains if c['kind'] == 'subagent')
    kinds = _kind_rows(main_items, main_steps, subagent_usd)
    sum_back = _check_sum_back(transcript_usd, main_items, main_steps, subagent_usd, kinds)
    for number, step in enumerate(main_steps, start=1):
        step['number'] = number
        step['description'] = describe_step(step)
        step['kind'] = primary_kind(step)
        step['kind_split'] = step_kind_split(step)
        step['targets'] = sorted({('read' if kind != 'write' else 'write', key)
                                  for key, kind, _ in _file_events(step, session['cwd']) if key})
        step['total_usd'] = (step['output_usd'] + step['new_usd'] + step['carried_usd']
                             + (step['subagent']['usd'] if step['subagent'] else 0.0))
    facts = _session_facts(session, session['calls'])
    carried = sum(i['carried_usd'] for i in main_items)
    files = files_table(main_steps, session['cwd'])
    estimate = {
        'session': facts, 'vocabulary': 'step, chain, item, starting context, output cost, new cost, carried cost',
        'totals': {'transcript_usd': transcript_usd, 'carried_usd': carried,
                   'carried_share': carried / transcript_usd if transcript_usd else 0.0,
                   'new_usd': sum(i['new_usd'] for i in main_items),
                   'output_usd': sum(s['output_usd'] for s in main_steps), 'subagent_usd': subagent_usd,
                   'largest_prompt_tokens': max(prices.prompt_size(c['tokens']) for c in session['calls']),
                   'steps': len(main_steps), 'calls_without_public_price': sum(
                       1 for c in session['calls'] if c['usd'] is None)},
        'sum_back': sum_back, 'kinds': kinds, 'steps': main_steps, 'items': main_items,
        'chains': [_chain_summary(c, c['steps'], all_items[c['key']]) for c in chains],
        'unlinked_subagents': unlinked, 'files': files, 'segments': session['segments'],
        'recorded_total': _recorded_total(session),
        'models_not_validated': sorted({c['model'] for c in session['calls']
                                        if c['usd'] is not None and not prices.is_validated(c['model'])}),
        'models_without_public_price': sorted({c['model'] for c in session['calls'] if c['usd'] is None}),
        'skipped_pairs': stats['skipped_pairs'], 'rebuilds': stats['rebuilds'],
        'rebuild_events': stats['events'], 'rebuild_extra_usd': sum(e['extra_usd'] for e in stats['events']),
        'rebuild_call_usd': sum(e['call_usd'] for e in stats['events']),
        'bash': _bash_stats(session['calls']), 'calls': [_call_row(c) for c in session['calls']
                                                         if c['source'] == 'main'],
    }
    estimate['findings'] = diagnose.diagnose(estimate)
    return estimate


def _call_row(call):
    """The exact per-call numbers the growth chart needs."""
    tokens = call['tokens']
    return {'order': call['order'], 'segment': call['segment'], 'timestamp': call['timestamp'],
            'resent_tokens': tokens['cache_read'],
            'new_tokens': tokens['input'] + tokens['cache_write_5m'] + tokens['cache_write_1h'],
            'prompt_tokens': prices.prompt_size(tokens)}


def _bash_stats(calls):
    """How Bash calls were classified (for the fine print and the report)."""
    counts = defaultdict(int)
    for call in calls:
        for tool_call in call['tool_calls']:
            if tool_call['tool'] == 'Bash' and tool_call.get('bash'):
                counts[tool_call['bash']['kind']] += 1
    total = sum(counts.values())
    return {'calls': total, 'by_kind': dict(counts),
            'other_command_share': counts[bash.OTHER] / total if total else 0.0}
