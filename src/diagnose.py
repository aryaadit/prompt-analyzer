"""Rules-only diagnosis. No model call. Each finding states what happened and gives no advice.

A finding has an id, its numbers, and one plain sentence built from a fixed template with the
step's or session's own numbers. Every number in a sentence carries the word "exact" or "est.".
A later prompt (the lean prompt writer) reads these findings, so ids and numbers are stable.

The top cards merge steps that share a target ("Read inventory.py 3 times") and pull up the next distinct
step, so the cards show different causes. A cache rebuild's cost is not part of any step's ranking: the
pause caused it, not the step. It is reported as its own session finding.
"""
import os

from .fmt import count, minutes, money, percent

TOP_STEPS = 3
MAX_PAUSES_LISTED = 5
STARTING_CONTEXT_MIN_SHARE = 0.10
FIXED_OVERHEAD_MIN_SHARE = 0.50  # above this, the starting context is called fixed overhead in the headline
RESENT_MIN_SHARE = 0.30
REPEATED_READ_MIN = 3


def _step_numbers(step):
    """The pieces of a step's cost that the why-sentence chooses between."""
    sub = step['subagent']['usd'] if step['subagent'] else 0.0
    rebuild = step['rebuild']['rewritten_usd'] if step['rebuild'] else 0.0
    return {'subagent': sub, 'rebuild': rebuild, 'large_result': step['new_usd'] + step['carried_usd'],
            'thinking': step['thinking_usd'], 'writing': step['output_usd'] - step['thinking_usd']}


def _why_id(step):
    """Pick the biggest piece of a step's cost. Ties go in this order."""
    numbers = _step_numbers(step)
    order = ('subagent', 'rebuild', 'large_result', 'thinking', 'writing')
    return max(order, key=lambda key: (numbers[key], -order.index(key)))


def _why(step, why_id):
    """The fixed template for one reason, filled with the step's own numbers."""
    numbers = _step_numbers(step)
    if why_id == 'subagent':
        info = step['subagent']
        who = 'A subagent made' if info['agents'] == 1 else '%d subagents made' % info['agents']
        return {'id': why_id, 'numbers': dict(info), 'sentence': (
            '%s %s model calls (exact) and cost %s (exact).' % (who, count(info['calls']), money(info['usd'])))}
    if why_id == 'rebuild':
        info = step['rebuild']
        return {'id': why_id, 'numbers': dict(info), 'sentence': (
            'It came after a pause of %s, long enough for the saved copy of the conversation to expire, so '
            '%s tokens (exact) were written again, costing %s (est.).'
            % (minutes(info['pause_minutes']), count(info['tokens_written']), money(info['rewritten_usd'])))}
    if why_id == 'large_result':
        later = step['resent_calls']
        tail = ('It was sent again on %s later calls, which cost %s (est.) on top of %s (est.) the first time.'
                % (count(later), money(step['carried_usd']), money(step['new_usd']))) if later else (
            'It was sent once, costing %s (est.).' % money(step['new_usd']))
        return {'id': why_id, 'numbers': {'tokens': step['material_tokens'], 'later_calls': later,
                                          'new_usd': step['new_usd'], 'carried_usd': step['carried_usd']},
                'sentence': 'Its result was about %s tokens (est.). %s' % (count(step['material_tokens']), tail)}
    if why_id == 'thinking':
        return {'id': why_id, 'numbers': {'thinking_tokens': step['thinking_tokens'],
                                          'usd': step['thinking_usd']}, 'sentence': (
            'The model spent %s tokens thinking (exact), which cost %s (exact).'
            % (count(step['thinking_tokens']), money(step['thinking_usd'])))}
    written = step['tokens']['output'] - min(step['thinking_tokens'], step['tokens']['output'])
    return {'id': 'writing', 'numbers': {'output_tokens': written, 'usd': numbers['writing']},
            'sentence': 'The model wrote %s tokens (exact), which cost %s (exact).'
                        % (count(written), money(numbers['writing']))}


def _merge(group):
    """One pseudo-step that adds up several steps with the same target."""
    total = lambda field: sum(s[field] for s in group)
    subs = [s['subagent'] for s in group if s['subagent']]
    return {'new_usd': total('new_usd'), 'carried_usd': total('carried_usd'), 'thinking_usd': total('thinking_usd'),
            'output_usd': total('output_usd'), 'material_tokens': total('material_tokens'),
            'resent_calls': total('resent_calls'), 'times': len(group), 'rebuild': None,
            'tokens': {'output': sum(s['tokens']['output'] for s in group)},
            'thinking_tokens': total('thinking_tokens'),
            'subagent': {'usd': sum(s['usd'] for s in subs), 'calls': sum(s['calls'] for s in subs),
                         'agents': sum(s['agents'] for s in subs)} if subs else None}


def _group_description(group):
    """'Read inventory.py 3 times' for steps that read (or wrote) the same file."""
    if len(group) == 1:
        return group[0]['description']
    verb, path = group[0]['targets'][0]
    names = [os.path.basename(p) for _, p in group[0]['targets']]
    what = names[0] + (' and %d more' % (len(names) - 1) if len(names) > 1 else '')
    return '%s %s %d times' % ('Read' if verb == 'read' else 'Wrote or edited', what, len(group))


def _card(group):
    """One top card: a step, or several steps merged because they share a target."""
    step = group[0] if len(group) == 1 else _merge(group)
    why = _why(step, _why_id(step))
    sentence = why['sentence']
    if len(group) > 1:
        sentence = ('These %d results were about %s tokens (est.) in all. They were sent again on %s later calls '
                    'in total, which cost %s (est.) on top of %s (est.) the first time.' % (
                        len(group), count(step['material_tokens']), count(step['resent_calls']),
                        money(step['carried_usd']), money(step['new_usd']))) if why['id'] == 'large_result' else (
            'In all %d steps, %s%s' % (len(group), sentence[0].lower(), sentence[1:]))
    sub = step['subagent']['usd'] if step['subagent'] else 0.0
    return {'id': why['id'], 'numbers': why['numbers'], 'sentence': sentence,
            'number': group[0]['number'], 'steps': sorted(s['number'] for s in group), 'times': len(group),
            'total_usd': sum(s['total_usd'] for s in group), 'description': _group_description(group),
            'kind': group[0]['kind'], 'parts': {'output': step['output_usd'], 'new': step['new_usd'],
                                                  'carried': step['carried_usd'], 'subagent': sub}}


def top_steps(steps):
    """The three biggest causes among the steps, each with its why-sentence.

    Steps are ranked by total cost. Steps that touch the same files in the same way are merged into one
    card, and the next distinct step moves up, so the cards show three different causes.
    """
    groups = {}
    for step in sorted((s for s in steps if s['priced']), key=lambda s: -s['total_usd']):
        key = tuple(map(tuple, step['targets'])) or ('step', step['number'])
        if key in groups:
            groups[key].append(step)
        elif len(groups) < TOP_STEPS:
            groups[key] = [step]
    cards = [_card(sorted(group, key=lambda s: s['number'])) for group in groups.values()]
    return sorted(cards, key=lambda c: -c['total_usd'])


def _line_usd(kinds, key):
    """Dollars of one kind line."""
    return next(row['usd'] for row in kinds if row['key'] == key)


def _starting_context(estimate):
    """Finding: the share of the total that went to the starting context."""
    total = estimate['totals']['transcript_usd']
    usd = _line_usd(estimate['kinds'], 'start')
    if not total or usd / total < STARTING_CONTEXT_MIN_SHARE:
        return None
    first = next((i for i in estimate['items'] if i['kind'] == 'start'), None)
    tokens = first['tokens'] if first else 0
    return {'id': 'starting_context_share', 'numbers': {'share': usd / total, 'usd': usd, 'tokens': tokens},
            'sentence': ('The starting context (system prompt, tool definitions, project instructions) was about '
                         '%s tokens (est.) and made up %s of the total (est.), %s (est.). It is sent on every call.'
                         % (count(tokens), percent(usd / total), money(usd)))}


def _resent_share(estimate):
    """Finding: the share of dollars spent sending earlier material again."""
    share, usd = estimate['totals']['carried_share'], estimate['totals']['carried_usd']
    if share < RESENT_MIN_SHARE:
        return None
    return {'id': 'resent_share', 'numbers': {'share': share, 'usd': usd}, 'sentence': (
        '%s of the dollars (%s, est.) went to sending earlier material again, not to new material.'
        % (percent(share), money(usd)))}


def _repeated_file(estimate):
    """Finding: a file that was read many times."""
    reads = [(f['reads'] + f['bash_reads'], f) for f in estimate['files']]
    reads = [(n, f) for n, f in reads if n >= REPEATED_READ_MIN]
    if not reads:
        return None
    n, row = max(reads, key=lambda pair: (pair[0], pair[1]['new_usd'] + pair[1]['carried_usd']))
    usd = row['new_usd'] + row['carried_usd']
    return {'id': 'file_read_repeatedly', 'numbers': {'file': os.path.basename(row['path']), 'reads': n,
                                                      'read_tool': row['reads'], 'shell_reads': row['bash_reads'],
                                                      'usd': usd}, 'sentence': (
        '%s was read %d times (%d with the Read tool, %d inside shell commands). Its results cost %s (est.) '
        'in total.' % (os.path.basename(row['path']), n, row['reads'], row['bash_reads'], money(usd)))}


def _compaction(estimate):
    """Finding: the conversation was compacted."""
    boundaries = estimate['segments'][1:]
    if not boundaries:
        return None
    triggers = [b['trigger'] for b in boundaries]
    pre, post = sum(b['pre_tokens'] or 0 for b in boundaries), sum(b['post_tokens'] or 0 for b in boundaries)
    return {'id': 'compaction', 'numbers': {'count': len(boundaries), 'auto': triggers.count('auto'),
                                            'manual': triggers.count('manual'), 'tokens_before': pre,
                                            'tokens_after': post}, 'sentence': (
        'The conversation was compacted %d time%s (%d automatic, %d manual). Each time it was replaced by a '
        'summary: %s tokens (exact) before, %s tokens (exact) after, added up over all compactions.'
        % (len(boundaries), '' if len(boundaries) == 1 else 's', triggers.count('auto'),
           triggers.count('manual'), count(pre), count(post)))}


def _cache_rebuilds(estimate):
    """Finding: the saved copy of the conversation expired, and what writing it again cost extra."""
    events = sorted(estimate['rebuild_events'], key=lambda e: e['order'])
    if not events:
        return None
    extra, total = estimate['rebuild_extra_usd'], estimate['totals']['transcript_usd']
    pauses = [minutes(e['pause_minutes']) for e in events[:MAX_PAUSES_LISTED]]
    more = len(events) - MAX_PAUSES_LISTED
    inside = sum(1 for e in events if e['chain'] == 'subagent')
    return {'id': 'cache_rebuilds', 'numbers': {
        'count': len(events), 'pause_minutes': [e['pause_minutes'] for e in events], 'extra_usd': extra,
        'extra_share': extra / total if total else 0.0, 'in_subagents': inside,
        'full_cost_usd': estimate['rebuild_call_usd']}, 'sentence': (
        'The saved copy of the conversation expired %d time%s (after %s%s), so earlier material had to be written '
        'again. That cost %s (est.) more than re-sending it would have.%s' % (
            len(events), '' if len(events) == 1 else 's',
            'a pause of ' + pauses[0] if len(events) == 1 else 'pauses of ' + ', '.join(pauses),
            ' and %d more' % more if more > 0 else '', money(extra),
            ' %d of them happened inside subagents.' % inside if inside else ''))}


def _headline(estimate, cards, session_findings):
    """One plain sentence: the single largest cause, taken from the findings above.

    When the starting context is more than half of the total, the sentence says so plainly (fixed overhead) and
    gives the cost of the task itself: the total minus the starting context.
    """
    total = estimate['totals']['transcript_usd']
    if not total:
        return None
    options = []
    if cards:
        top = cards[0]
        what = top['description'] + (', %s in all' % money(top['total_usd']) if top['times'] > 1
                                      else ' (step %d), which cost %s' % (top['number'], money(top['total_usd'])))
        options.append((top['total_usd'], 'repeated_step' if top['times'] > 1 else 'top_step', what))
    by_id = {f['id']: f for f in session_findings}
    if 'starting_context_share' in by_id:
        found = by_id['starting_context_share']['numbers']
        options.append((found['usd'], 'starting_context', 'the starting context, which is sent on every call. '
                        'It cost %s' % money(found['usd'])))
    if 'cache_rebuilds' in by_id:
        found = by_id['cache_rebuilds']['numbers']
        options.append((found['extra_usd'], 'cache_rebuilds', 'the saved copy of the conversation expiring %d time%s, '
                        'which cost %s more than re-sending would have' % (
                            found['count'], '' if found['count'] == 1 else 's', money(found['extra_usd']))))
    overhead = by_id.get('starting_context_share')
    if overhead and overhead['numbers']['usd'] / total > FIXED_OVERHEAD_MIN_SHARE:
        start_usd = overhead['numbers']['usd']
        share = start_usd / total
        task_usd = max(total - start_usd, 0.0)
        return {'id': 'fixed_overhead', 'cause': "Claude Code's starting context (fixed overhead, sent before any work)",
                'numbers': {'usd': start_usd, 'share': share, 'task_usd': task_usd}, 'sentence': (
                    "Most of this cost was fixed overhead: Claude Code's starting context, sent before any work. "
                    "The task itself cost %s." % money(task_usd))}
    if not options:
        return None
    usd, cause, text = max(options, key=lambda option: option[0])
    return {'id': cause, 'cause': text, 'numbers': {'usd': usd, 'share': usd / total}, 'sentence': (
        'The largest single cause: %s, %s of the total (est.).' % (text, percent(usd / total)))}


def diagnose(estimate):
    """The top cards, up to five session findings, and the one-sentence headline."""
    cards = top_steps(estimate['steps'])
    session = [f for f in (_starting_context(estimate), _resent_share(estimate), _repeated_file(estimate),
                           _compaction(estimate), _cache_rebuilds(estimate)) if f]
    return {'top_steps': cards, 'session': session, 'headline': _headline(estimate, cards, session)}
