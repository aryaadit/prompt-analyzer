"""Audit across every local session: size the gap and validate the price table.

    python3 -m src.audit gap      # gap between session totals and the transcript, in dollars
    python3 -m src.audit prices   # per-call dollars versus cost-state costUSD
    python3 -m src.audit all

Prints counts, token numbers, and dollars only. Reads logs, never writes to them.
"""
import argparse
import sys

from . import parse, prices, reconcile


def load_all(root):
    """Parse every session once. Return (entries, validation items, per-session facts)."""
    entries, items, sessions = [], [], []
    for path in parse.list_sessions(root):
        session = parse.parse_session(path)
        has_state = session['cost_state']['last'] is not None
        sessions.append({'compacted': session['compaction']['compacted'], 'has_cost_state': has_state,
                         'calls': len(session['calls'])})
        if not has_state:
            continue
        for entry in reconcile.session_entries(session):
            entries.append(entry)
            if entry['exact_scope']:
                items.append(_validation_item(session, entry))
    return entries, items, sessions


def _validation_item(session, entry):
    """Collect the calls an exactly reconciling entry covers, for per-call pricing."""
    only_main = entry['exact_scope'] == 'main'
    calls = [c for c in session['calls']
             if c['model'] == entry['model'] and (c['source'] == 'main' or not only_main)]
    return {'session_id': entry['session_id'], 'model': entry['model'],
            'cost_usd': entry['cost_state_usd_reported'],
            'web_searches': entry['cost_state_web_searches'], 'calls': calls}


def _group_stats(entries, cache_write='split'):
    """Total dollars and gap of a group of entries on the price-table yardstick."""
    stats = {'entries': len(entries), 'total': 0.0, 'attributed': 0.0, 'gap': 0.0, 'gap_pos': 0.0,
             'gap_neg': 0.0, 'reported': 0.0, 'unpriced': 0, 'neg_entries': 0,
             'gap_by_type': dict.fromkeys(prices.TOKEN_TYPES, 0.0),
             'gap_tokens': reconcile.empty_tokens()}
    for entry in entries:
        stats['reported'] += entry['cost_state_usd_reported']
        priced = reconcile.price_entry(entry, cache_write)
        if priced is None:
            stats['unpriced'] += 1
            continue
        stats['total'] += priced['session_total_usd']
        stats['attributed'] += priced['attributed_usd']
        stats['gap'] += priced['gap_usd']
        stats['gap_pos'] += max(priced['gap_usd'], 0.0)
        stats['gap_neg'] += min(priced['gap_usd'], 0.0)
        stats['neg_entries'] += priced['gap_usd'] < 0
        for kind in prices.TOKEN_TYPES:
            stats['gap_by_type'][kind] += priced['gap_by_type_usd'][kind]
            stats['gap_tokens'][kind] += entry['gap_tokens'][kind]
    return stats


def _pct(part, whole):
    """Percent with one decimal, safe for a zero denominator."""
    return '%.1f%%' % (100 * part / whole) if whole else 'n/a'


def _group_line(title, stats):
    """One table row: session total, attributed, net gap, and its parts."""
    return ('  %-26s %5d  $%9.2f  $%9.2f  $%8.2f %7s   +$%8.2f / -$%7.2f (%d entries below zero)'
            % (title, stats['entries'], stats['total'], stats['attributed'], stats['gap'],
               _pct(stats['gap'], stats['total']), stats['gap_pos'], abs(stats['gap_neg']),
               stats['neg_entries']))


def print_gap(entries, sessions):
    """Print the gap as a share of session-total dollars, with and without compaction."""
    with_state = [s for s in sessions if s['has_cost_state']]
    print('GAP: session totals (last cost-state) minus transcript, priced with our table')
    print('prices: %s, checked %s. Dollars are %s.' % (prices.PRICES_URL, prices.PRICES_CHECKED, prices.LABEL))
    print('sessions %d; with cost-state %d (compacted %d, not compacted %d); without cost-state %d'
          % (len(sessions), len(with_state), sum(s['compacted'] for s in with_state),
             sum(not s['compacted'] for s in with_state), len(sessions) - len(with_state)))
    groups = (('all sessions', entries),
              ('WITH compaction', [e for e in entries if e['compacted']]),
              ('WITHOUT compaction', [e for e in entries if not e['compacted']]))
    modes = (('all_5m', 'every cache write at the 5-minute rate (low)'),
             ('all_1h', 'every cache write at the 1-hour rate (high)'),
             ('split', "cost-state's own 5m/1h fields as recorded (incomplete; shown for reference)"))
    for mode, description in modes:
        print('\n[%s] %s' % (mode, description))
        print('  %-26s %5s  %10s  %10s  %9s %7s   %s' % ('group', 'n', 'session $', 'attributed $',
                                                       'gap $', 'share', 'gap above zero / below zero'))
        for title, group in groups:
            print(_group_line(title, _group_stats(group, mode)))
    s = _group_stats(entries, 'all_5m')
    tokens = s['gap_tokens']
    print('\ngap tokens, all sessions (exact): input %d  cache_read %d  cache_write %d  output %d' % (
        tokens['input'], tokens['cache_read'], tokens['cache_write_5m'] + tokens['cache_write_1h'],
        tokens['output']))
    print('cross-check, cost-state costUSD sum (client-computed): all $%.2f, with compaction $%.2f, without $%.2f'
          % (s['reported'], _group_stats(groups[1][1])['reported'], _group_stats(groups[2][1])['reported']))
    split = [('models with transcript calls', [e for e in entries if e['has_transcript_calls']]),
             ('models with no transcript call', [e for e in entries if not e['has_transcript_calls']])]
    print('\nwhere the gap sits (all sessions, 5m rate / 1h rate)')
    for title, group in split:
        low, high = _group_stats(group, 'all_5m'), _group_stats(group, 'all_1h')
        print('  %-32s %4d entries, gap $%.2f to $%.2f' % (title, low['entries'], low['gap'], high['gap']))


def print_validation(items):
    """Print how well per-call dollars match costUSD on entries that reconcile exactly."""
    result = prices.validate(items)
    print('\nPRICE VALIDATION: per-call dollars summed per entry, entries that reconcile exactly')
    print('entries %d (%d skipped: no public price)' % (len(items) - result['unpriced_entries'],
                                                      result['unpriced_entries']))
    print('%-6s %-48s %8s %12s %14s %14s' % ('', 'variant', 'matched', 'max diff $', 'computed $', 'costUSD $'))
    for row in result['rows']:
        print('%-6s %-48s %4d/%-3d %12.4f %14.2f %14.2f'
              % (row['variant'], row['description'], row['matched'], row['entries'],
                 row['max_abs_diff_usd'], row['computed_sum_usd'], row['cost_usd_sum']))
    print('\ncostUSD / computed (base), per model: count, min, median, max')
    for model, (count, low, mid, high) in sorted(result['ratios_by_model'].items()):
        print('  %-28s %3d  %.4f  %.4f  %.4f' % (model, count, low, mid, high))
    print('\ncalls in exact entries by usage.speed / service_tier / inference_geo:')
    counts = {}
    for item in items:
        for call in item['calls']:
            key = (call['speed'], call['service_tier'], call['inference_geo'])
            counts[key] = counts.get(key, 0) + 1
    for key, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print('  %s: %d' % (key, count))
    print('exact entries with web searches in cost-state: %d' % sum(1 for i in items if i['web_searches']))


def main(argv=None):
    """Run the requested audit over every session under the projects folder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('what', choices=('gap', 'prices', 'all'))
    parser.add_argument('--root', default=parse.PROJECTS_ROOT)
    args = parser.parse_args(argv)
    entries, items, sessions = load_all(args.root)
    if args.what in ('gap', 'all'):
        print_gap(entries, sessions)
    if args.what in ('prices', 'all'):
        print_validation(items)
    return 0


if __name__ == '__main__':
    sys.exit(main())
