"""Compare transcript token totals with the session totals in the last cost-state record."""
from .prices import TOKEN_TYPES, price_aggregate, price_by_type

SESSION_TOTAL_LABEL = 'in session totals, not attributed to a transcript call'
# The four counts cost-state has always carried, used to decide whether an entry reconciles.
_EXACT_FIELDS = ('input', 'output', 'cache_read', 'cache_write')


def empty_tokens():
    """Return a zeroed token dict."""
    return {kind: 0 for kind in TOKEN_TYPES}


def add_tokens(total, tokens):
    """Add one token dict into another, in place."""
    for kind in TOKEN_TYPES:
        total[kind] += tokens[kind]


def transcript_by_model(calls):
    """Sum call tokens per model, split into main-session and subagent parts."""
    result = {}
    for call in calls:
        entry = result.setdefault(call['model'], {
            'all': empty_tokens(), 'main': empty_tokens(), 'calls': 0, 'main_calls': 0})
        for key in ('all', 'main' if call['source'] == 'main' else None):
            if key:
                add_tokens(entry[key], call['tokens'])
        entry['calls'] += 1
        entry['main_calls'] += call['source'] == 'main'
    return result


def _matches_exactly(cost_tokens, tokens):
    """True when the four cost-state counts equal the transcript counts."""
    combined = dict(tokens, cache_write=tokens['cache_write_5m'] + tokens['cache_write_1h'])
    cost = dict(cost_tokens, cache_write=cost_tokens['cache_write_5m'] + cost_tokens['cache_write_1h'])
    return all(cost[field] == combined[field] for field in _EXACT_FIELDS)


def _cost_tokens(state_entry):
    """The five token counts of one cost-state model entry."""
    return {kind: state_entry[kind] for kind in TOKEN_TYPES}


def session_entries(session):
    """One entry per model in the last cost-state: totals, transcript, gap, and exactness."""
    last = session['cost_state']['last']
    if last is None:
        return []
    transcript = transcript_by_model(session['calls'])
    entries = []
    for model in sorted(set(last['models']) | set(transcript)):
        state = last['models'].get(model)
        mine = transcript.get(model)
        cost_tokens = _cost_tokens(state) if state else empty_tokens()
        all_tokens = mine['all'] if mine else empty_tokens()
        main_tokens = mine['main'] if mine else empty_tokens()
        scope = None
        if state and mine and _matches_exactly(cost_tokens, main_tokens):
            scope = 'main'
        elif state and mine and _matches_exactly(cost_tokens, all_tokens):
            scope = 'main+subagents'
        entries.append({
            'session_id': session['session_id'], 'model': model,
            'compacted': session['compaction']['compacted'],
            'in_cost_state': state is not None, 'has_transcript_calls': mine is not None,
            'cost_state_tokens': cost_tokens, 'transcript_tokens': all_tokens,
            'gap_tokens': {kind: cost_tokens[kind] - all_tokens[kind] for kind in TOKEN_TYPES},
            'transcript_calls': mine['calls'] if mine else 0,
            'cost_state_thinking': state['thinking'] if state else 0,
            'cost_state_web_searches': state['web_search'] if state else 0,
            'cost_state_usd_reported': state['cost_usd'] if state else 0.0,
            'exact_scope': scope,
        })
    return entries


def price_entry(entry, cache_write='split'):
    """Price an entry's session total, transcript, and gap with the same table.

    Returns None when the model has no public price. Both sides use aggregate base prices, so
    the gap is on one yardstick (prompt-size tiers cannot be applied to summed tokens).
    cache_write 'all_5m' or 'all_1h' prices every cache write at one rate on both sides. That
    is needed because cost-state's own 5m/1h split is incomplete; only its combined count is reliable.
    """
    total = price_aggregate(entry['model'], entry['cost_state_tokens'], cache_write)
    if total is None:
        return None
    attributed = price_aggregate(entry['model'], entry['transcript_tokens'], cache_write)
    gap_by_type = price_by_type(entry['model'], entry['gap_tokens'], cache_write)
    return {'session_total_usd': total, 'attributed_usd': attributed,
            'gap_usd': total - attributed, 'gap_by_type_usd': gap_by_type}
