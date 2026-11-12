"""The one price table, and the functions that turn token counts into dollars.

Every dollar figure from this module is API-equivalent: exact token counts times public API
list prices. It is not a bill. No price in this file was fitted to the logs.
"""
import re

PRICES_URL = 'https://platform.claude.com/docs/en/about-claude/pricing'
PRICES_CHECKED = '2026-11-12'  # the page shows no "last updated" date, so this is the day we read it
LABEL = 'API-equivalent'

TOKEN_TYPES = ('input', 'cache_read', 'cache_write_5m', 'cache_write_1h', 'output')

# Dollars per million tokens: input, cache_write_5m, cache_write_1h, cache_read, output.
# The page lists display names only. Log ids are mapped to display names by naming convention
# (for example claude-fable-5-1 is "Claude Fable 5.1"). Ids with no row here have no public price.
# Checked on 2026-11-12 against cost-state costUSD, on the 71 entries whose transcript reconciles
# exactly: claude-sonnet-5-5 (28 entries), claude-opus-5-5 (33), claude-fable-5-1 (9 entries,
# 779 calls), claude-opus-4-8 (1 entry, 6 calls) all matched to rounding error. These rows have
# NOT been checked that way, because no exactly reconciling entry uses them: claude-fable-5-2,
# claude-fable-5, claude-haiku-5-5, claude-haiku-4-5. Rerun `python3 -m src.audit prices` to refresh.
_ROWS = {
    'claude-fable-5-2': ('Claude Fable 5.2', 8, 10, 16, 0.20, 40),
    'claude-fable-5-1': ('Claude Fable 5.1', 10, 12.50, 20, 0.25, 50),
    'claude-fable-5': ('Claude Fable 5', 10, 12.50, 20, 1, 50),
    'claude-opus-5-5': ('Claude Opus 5.5', 4, 5, 8, 0.20, 20),
    'claude-opus-4-8': ('Claude Opus 4.8', 5, 6.25, 10, 0.50, 25),
    'claude-sonnet-5-5': ('Claude Sonnet 5.5', 2, 2.50, 4, 0.10, 10),
    'claude-haiku-5-5': ('Claude Haiku 5.5, prompts up to 100,000 tokens', 0.10, 0.125, 0.20, 0.01, 0.50),
    'claude-haiku-4-5': ('Claude Haiku 4.5', 1, 1.25, 2, 0.10, 5),
}
PRICES = {
    model: {'name': row[0], 'input': row[1], 'cache_write_5m': row[2], 'cache_write_1h': row[3],
            'cache_read': row[4], 'output': row[5]}
    for model, row in _ROWS.items()
}

# Haiku 5.5 only: prompts over 100,000 tokens (input + cache read + cache write) cost more.
# The page gives these as a second table row. No other model has a prompt-size tier.
LONG_CONTEXT_THRESHOLD = 100_000
LONG_CONTEXT = {
    'claude-haiku-5-5': {'input': 0.50, 'cache_write_5m': 0.625, 'cache_write_1h': 1,
                         'cache_read': 0.05, 'output': 2.50},
}

# Fast mode: the page lists fast prices for these models. Each is 2x the standard input and
# output price, and the page says caching multipliers stack on top, so 2x on every category.
FAST_MODELS = ('claude-fable-5-2', 'claude-opus-5-5', 'claude-opus-4-8')
FAST_MULTIPLIER = 2.0
US_GEO_MULTIPLIER = 1.1  # inference_geo "us" on Claude 4.6 and later; "global" is standard
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches. Web fetch has no extra fee.
# The page has no priority-tier or service-tier price, so service_tier cannot change dollars.


def canonical_model(model):
    """Return the price-table id for a log model id, or None. Drops a trailing -YYYYMMDD date."""
    if not isinstance(model, str):
        return None
    if model in PRICES:
        return model
    dated = re.sub(r'-\d{8}$', '', model)
    return dated if dated in PRICES else None


def rates_for(model, prompt_tokens=None, long_context=True):
    """Return dollars per million tokens for a model, or None when there is no public price."""
    key = canonical_model(model)
    if key is None:
        return None
    tier = LONG_CONTEXT.get(key)
    if long_context and tier and prompt_tokens is not None and prompt_tokens > LONG_CONTEXT_THRESHOLD:
        return tier
    return PRICES[key]


def prompt_size(tokens):
    """Prompt tokens of a call: uncached input plus cache read plus cache writes."""
    return (tokens['input'] + tokens['cache_read'] + tokens['cache_write_5m']
            + tokens['cache_write_1h'])


def _regroup_writes(tokens, mode):
    """Return a copy of tokens with cache writes priced all at the 5m or all at the 1h rate."""
    moved = dict(tokens)
    if mode == 'all_5m':
        moved['cache_write_5m'] += moved['cache_write_1h']
        moved['cache_write_1h'] = 0
    elif mode == 'all_1h':
        moved['cache_write_1h'] += moved['cache_write_5m']
        moved['cache_write_5m'] = 0
    return moved


def price_tokens(model, tokens, *, cache_write='split', prompt_tokens=None, long_context=True,
                 fast=False, us_geo=False, web_searches=0):
    """Dollars for a token dict at public prices, or None for a model with no public price.

    Options exist so the validation can test one modifier at a time: cache_write is 'split',
    'all_5m', or 'all_1h'; long_context turns the Haiku 5.5 tier on; fast and us_geo apply the
    page's multipliers; web_searches adds the per-search fee.
    """
    rates = rates_for(model, prompt_tokens, long_context)
    if rates is None:
        return None
    grouped = _regroup_writes(tokens, cache_write)
    usd = sum(grouped[kind] * rates[kind] for kind in TOKEN_TYPES) / 1_000_000
    if fast and canonical_model(model) in FAST_MODELS:
        usd *= FAST_MULTIPLIER
    if us_geo:
        usd *= US_GEO_MULTIPLIER
    return usd + web_searches * WEB_SEARCH_USD


def price_call(call):
    """Dollars for one model call, using the modifiers the call itself recorded."""
    return price_tokens(
        call['model'], call['tokens'], prompt_tokens=prompt_size(call['tokens']),
        fast=call.get('speed') == 'fast', us_geo=call.get('inference_geo') == 'us',
        web_searches=call.get('web_search_requests', 0))


def price_aggregate(model, tokens, cache_write='split'):
    """Dollars for summed tokens at base prices. Prompt-size tiers cannot be applied to totals."""
    return price_tokens(model, tokens, cache_write=cache_write, long_context=False)


def price_by_type(model, tokens, cache_write='split'):
    """Dollars per token type at base prices, or None when there is no public price."""
    rates = rates_for(model, long_context=False)
    if rates is None:
        return None
    grouped = _regroup_writes(tokens, cache_write)
    return {kind: grouped[kind] * rates[kind] / 1_000_000 for kind in TOKEN_TYPES}


# ---------------------------------------------------------------- validation against costUSD

# Each variant is one change to the base computation (split cache writes, no modifiers).
VARIANTS = (
    ('base', 'split cache writes, list prices', {}),
    ('a1', 'a. all cache writes at the 5-minute rate', {'cache_write': 'all_5m'}),
    ('a2', 'a. all cache writes at the 1-hour rate', {'cache_write': 'all_1h'}),
    ('b', 'b. usage.speed (fast-mode multiplier)', {'speed': True}),
    ('c', 'c. long-context tier (Haiku 5.5 only)', {'long_context': True}),
    ('d', 'd. web search request fees', {'web': True}),
    ('e', 'e. service_tier / inference_geo', {'geo': True}),
    ('b-e', 'b to e together', {'speed': True, 'long_context': True, 'web': True, 'geo': True}),
)


def _entry_usd(item, options):
    """Sum per-call dollars for one cost-state entry under one variant. None if unpriced."""
    total = 0.0
    for call in item['calls']:
        usd = price_tokens(
            call['model'], call['tokens'], cache_write=options.get('cache_write', 'split'),
            prompt_tokens=prompt_size(call['tokens']), long_context=options.get('long_context', False),
            fast=bool(options.get('speed')) and call.get('speed') == 'fast',
            us_geo=bool(options.get('geo')) and call.get('inference_geo') == 'us')
        if usd is None:
            return None
        total += usd
    if options.get('web'):
        total += item['web_searches'] * WEB_SEARCH_USD
    return total


def _matches(computed, reported):
    """True when two dollar figures agree to within one part in a million (float rounding only)."""
    return abs(computed - reported) <= max(1e-9, 1e-6 * abs(reported))


def validate(items):
    """Compare per-call dollars summed per entry against cost-state costUSD.

    items: [{'session_id', 'model', 'cost_usd', 'web_searches', 'calls': [call, ...]}], each
    an entry whose transcript tokens equal the cost-state tokens exactly. Returns one result
    row per variant, plus per-model ratios costUSD / computed for the base variant (a
    diagnostic: a constant ratio would mean the client used a different table).
    """
    priced = [item for item in items if _entry_usd(item, {}) is not None]
    rows = []
    for name, description, options in VARIANTS:
        diffs, computed_sum, reported_sum, matched = [], 0.0, 0.0, 0
        for item in priced:
            computed = _entry_usd(item, options)
            diffs.append(abs(computed - item['cost_usd']))
            computed_sum += computed
            reported_sum += item['cost_usd']
            matched += _matches(computed, item['cost_usd'])
        rows.append({'variant': name, 'description': description, 'entries': len(priced),
                     'matched': matched, 'max_abs_diff_usd': max(diffs, default=0.0),
                     'computed_sum_usd': computed_sum, 'cost_usd_sum': reported_sum})
    return {'rows': rows, 'unpriced_entries': len(items) - len(priced),
            'ratios_by_model': _ratios_by_model(priced)}


def _ratios_by_model(items):
    """Per model: (count, min, median, max) of costUSD divided by base computed dollars."""
    ratios = {}
    for item in items:
        computed = _entry_usd(item, {})
        if computed > 0:
            ratios.setdefault(item['model'], []).append(item['cost_usd'] / computed)
    summary = {}
    for model, values in ratios.items():
        values.sort()
        summary[model] = (len(values), values[0], values[len(values) // 2], values[-1])
    return summary
