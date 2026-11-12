"""Rules-only diagnosis. No model call. Each finding states what happened and gives no advice.

A finding has an id, its numbers, and one plain sentence built from a fixed template with the
step's or session's own numbers. Every number in a sentence carries the word "exact" or "est.".
A later prompt (the lean prompt writer) reads these findings, so ids and numbers are stable.
"""
import os

from .fmt import count, minutes, money, percent

TOP_STEPS = 3
STARTING_CONTEXT_MIN_SHARE = 0.10
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


def top_steps(steps):
    """The three most expensive steps by total cost, each with its why-sentence."""
    ranked = sorted((s for s in steps if s['priced']), key=lambda s: -s['total_usd'])[:TOP_STEPS]
    return [dict(_why(step, _why_id(step)), number=step['number'], total_usd=step['total_usd'],
                 description=step['description']) for step in ranked]


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


def diagnose(estimate):
    """The three most expensive steps, and up to four session findings."""
    session = [f for f in (_starting_context(estimate), _resent_share(estimate), _repeated_file(estimate),
                           _compaction(estimate)) if f]
    return {'top_steps': top_steps(estimate['steps']), 'session': session}
