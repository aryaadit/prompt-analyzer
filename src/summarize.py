"""Summarize one session: calls, tokens, API-equivalent dollars, tools, and reconciliation.

    python3 -m src.summarize --session <path, id, or "latest"> [--json [path]]

Tokens are exact (read from the log). Dollars are API-equivalent: exact tokens times public
list prices from src/prices.py. cost-state costUSD is shown only as a cross-check.
The summary and the JSON hold no prompt text, no file contents, and no tool output.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

from . import parse, prices, reconcile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_PRICE = 'no public price'
CACHE_WRITE_MODES = (('low', 'all_5m'), ('high', 'all_1h'))


# ---------------------------------------------------------------- building the structure

def price_calls(calls):
    """Attach per-call dollars (None when the model has no public price) and prompt size."""
    for call in calls:
        call['prompt_tokens'] = prices.prompt_size(call['tokens'])
        call['usd'] = prices.price_call(call)


def _sum_tokens(calls):
    """Sum the token dicts of calls, plus thinking tokens."""
    total = reconcile.empty_tokens()
    for call in calls:
        reconcile.add_tokens(total, call['tokens'])
    total['thinking'] = sum(call['thinking_tokens'] for call in calls)
    return total


def _usd(calls):
    """Sum priced dollars of calls. Returns (dollars, number of calls with no public price)."""
    priced = [c['usd'] for c in calls if c['usd'] is not None]
    return sum(priced), len(calls) - len(priced)


def _group(calls, key):
    """Group calls and return {name: {calls, tokens, usd, unpriced_calls}} for a key function."""
    groups = {}
    for call in calls:
        groups.setdefault(key(call), []).append(call)
    result = {}
    for name, members in sorted(groups.items()):
        usd, unpriced = _usd(members)
        result[name] = {'calls': len(members), 'tokens': _sum_tokens(members), 'usd': usd,
                        'unpriced_calls': unpriced}
    return result


def tool_counts(calls):
    """Count tool calls by canonical tool name, with errors and result characters."""
    counts = {}
    for call in calls:
        for tool_call in call['tool_calls']:
            row = counts.setdefault(tool_call['tool'], {'calls': 0, 'results': 0, 'errors': 0,
                                                        'result_chars': 0})
            row['calls'] += 1
            if tool_call['result_chars'] is not None:
                row['results'] += 1
                row['result_chars'] += tool_call['result_chars']
            row['errors'] += bool(tool_call['is_error'])
    return dict(sorted(counts.items(), key=lambda item: -item[1]['calls']))


def segment_rows(session):
    """Per compaction segment: its calls, dollars, and the boundary that opened it."""
    rows = []
    for segment in session['segments']:
        members = [c for c in session['calls'] if c['segment'] == segment['index']]
        usd, unpriced = _usd(members)
        rows.append(dict(segment, calls=len(members), usd=usd, unpriced_calls=unpriced))
    return rows


def _entry_row(session, entry):
    """One reconciliation row: tokens, per-call dollars, and the gap range for one model."""
    calls = [c for c in session['calls'] if c['model'] == entry['model']]
    attributed, unpriced = _usd(calls)
    row = {'model': entry['model'], 'in_session_totals': entry['in_cost_state'],
           'transcript_calls': entry['transcript_calls'],
           'transcript_tokens': entry['transcript_tokens'],
           'session_total_tokens': entry['cost_state_tokens'], 'gap_tokens': entry['gap_tokens'],
           'exact_scope': entry['exact_scope'],
           'attributed_usd_per_call': None if unpriced else attributed,
           'cost_usd_reported_cross_check': entry['cost_state_usd_reported']}
    for name, mode in CACHE_WRITE_MODES:
        priced = reconcile.price_entry(entry, mode)
        row['session_total_usd_' + name] = priced['session_total_usd'] if priced else None
        row['gap_usd_' + name] = priced['gap_usd'] if priced else None
    return row


def reconciliation(session):
    """Transcript versus the last cost-state, per model, with totals over priced models."""
    if session['cost_state']['last'] is None:
        return None
    rows = [_entry_row(session, e) for e in reconcile.session_entries(session)]
    priced = [r for r in rows if r['gap_usd_low'] is not None]
    totals = {'label': reconcile.SESSION_TOTAL_LABEL,
              'models_without_public_price': [r['model'] for r in rows if r['gap_usd_low'] is None]}
    for name, _ in CACHE_WRITE_MODES:
        totals['session_total_usd_' + name] = sum(r['session_total_usd_' + name] for r in priced)
        totals['gap_usd_' + name] = sum(r['gap_usd_' + name] for r in priced)
    totals['gap_tokens'] = reconcile.empty_tokens()
    for row in rows:
        reconcile.add_tokens(totals['gap_tokens'], row['gap_tokens'])
    totals['cost_usd_reported_cross_check'] = sum(r['cost_usd_reported_cross_check'] for r in rows)
    return {'models': rows, 'totals': totals}


def build_summary(session):
    """Build the full normalized structure that both the text report and the JSON use."""
    calls = session['calls']
    price_calls(calls)
    usd, unpriced = _usd(calls)
    ranked = sorted((c for c in calls if c['usd'] is not None), key=lambda c: -c['usd'])
    return {
        'session': {'session_id': session['session_id'], 'file': session['file_name'],
                    'files': session['files'], 'warnings': session['warnings'],
                    'compaction': session['compaction']},
        'pricing': {'url': prices.PRICES_URL, 'checked': prices.PRICES_CHECKED,
                    'label': prices.LABEL, 'tokens': 'exact (read from the log)',
                    'dollars': 'API-equivalent: exact tokens times public list prices'},
        'totals': {'calls': len(calls), 'tokens': _sum_tokens(calls), 'attributed_usd': usd,
                   'calls_without_public_price': unpriced,
                   'share_calls_without_public_price': unpriced / len(calls) if calls else 0.0,
                   'models_without_public_price': sorted(
                       {c['model'] for c in calls if c['usd'] is None})},
        'by_model': _group(calls, lambda c: c['model']),
        'by_source': _group(calls, lambda c: 'main session' if c['source'] == 'main' else 'subagents'),
        'top_calls_by_cost': [c['order'] for c in ranked[:10]],
        'tool_counts': tool_counts(calls),
        'segments': segment_rows(session),
        'cost_state': {'records': session['cost_state']['records'],
                       'last_total_cost_usd_reported': (session['cost_state']['last'] or {}).get(
                           'total_cost_usd')},
        'reconciliation': reconciliation(session),
        'calls': calls,
    }


# ---------------------------------------------------------------- text rendering

def money(value):
    """Format dollars, or the no-public-price label."""
    if value is None:
        return NO_PRICE
    return '$%s' % format(value, ',.4f' if 0 < abs(value) < 0.01 else ',.2f')


def short_target(tool_call):
    """A short, safe label for a tool call: file paths shrink to their base name."""
    tool, target, kind = tool_call['tool'], tool_call['target'], tool_call['target_kind']
    if target is None or kind in ('query', None):
        return tool
    if kind == 'file_path':
        target = os.path.basename(target)
    elif kind == 'url':
        target = urlsplit(target).netloc or '?'
    return '%s:%s' % (tool, target[:40])


def _token_line(tokens):
    """Tokens by type on one line."""
    return ('input %s | cache read %s | cache write 5m %s | cache write 1h %s | output %s'
            % tuple(format(tokens[k], ',') for k in prices.TOKEN_TYPES))


def _scope_label(row):
    """Say how one model's transcript relates to its session totals."""
    if row['exact_scope']:
        return 'reconciles exactly (%s)' % row['exact_scope'].replace('+', ' + ')
    if not row['in_session_totals']:
        return 'not in session totals'
    return 'no transcript calls' if not row['transcript_calls'] else 'session totals exceed transcript'


def _gap_token_line(tokens):
    """Gap tokens by type. Cache writes are combined: only their sum is reliable in cost-state."""
    write = tokens['cache_write_5m'] + tokens['cache_write_1h']
    return ('input %s | cache read %s | cache write %s | output %s'
            % (format(tokens['input'], ','), format(tokens['cache_read'], ','),
               format(write, ','), format(tokens['output'], ',')))


def _print_overview(summary, out):
    """Print the header, legend, token totals, and dollar splits."""
    session, totals = summary['session'], summary['totals']
    files = session['files']
    print('SESSION %s  (%s)' % (session['session_id'], session['file']), file=out)
    print('files: 1 main, %d subagent, %d workflow-agent | calls: %d | compaction boundaries: %d'
          % (files['subagent'], files['workflow'], totals['calls'],
             session['compaction']['main_boundaries']), file=out)
    print('Tokens are exact (read from the log). Dollars are %s: exact tokens x public list prices\n'
          '(%s, checked %s). cost-state costUSD is a cross-check only.'
          % (prices.LABEL, prices.PRICES_URL, prices.PRICES_CHECKED), file=out)
    print('\nTOKENS (transcript, exact)', file=out)
    print('  ' + _token_line(totals['tokens']), file=out)
    print('  thinking tokens (part of output): %s' % format(totals['tokens']['thinking'], ','), file=out)
    print('\nATTRIBUTED DOLLARS (transcript, %s, per call with the 5m/1h split): %s'
          % (prices.LABEL, money(totals['attributed_usd'])), file=out)
    for title, groups in (('by model', summary['by_model']), ('main session vs subagents', summary['by_source'])):
        print('  ' + title, file=out)
        for name, g in groups.items():
            note = '  (%d calls: %s)' % (g['unpriced_calls'], NO_PRICE) if g['unpriced_calls'] else ''
            print('    %-28s %6d calls  %14s%s' % (name, g['calls'], money(g['usd']), note), file=out)
    if totals['calls_without_public_price']:
        print('  %s: %d of %d calls (%.1f%%), models %s. Tokens are shown; dollars left out.'
              % (NO_PRICE, totals['calls_without_public_price'], totals['calls'],
                 100 * totals['share_calls_without_public_price'],
                 ', '.join(totals['models_without_public_price'])), file=out)


def _print_top_calls(summary, out):
    """Print the ten most expensive calls."""
    by_order = {c['order']: c for c in summary['calls']}
    print('\nTOP 10 CALLS BY COST (%s)' % prices.LABEL, file=out)
    for rank, order in enumerate(summary['top_calls_by_cost'], start=1):
        call = by_order[order]
        who = 'main' if call['source'] == 'main' else 'sub:' + str(call['agent_id'])[:8]
        tools = ', '.join(short_target(t) for t in call['tool_calls'][:3]) or '-'
        print('  %2d. #%-5d %-20s %-14s %10s  prompt %9s  out %7s  %-9s %s'
              % (rank, order, call['model'], who, money(call['usd']), format(call['prompt_tokens'], ','),
                 format(call['tokens']['output'], ','), call['stop_reason'] or '-', tools), file=out)


def _print_tools(summary, out):
    """Print tool call counts and compaction segments."""
    print('\nTOOL CALLS BY TOOL', file=out)
    print('  %-24s %7s %8s %7s %14s' % ('tool', 'calls', 'results', 'errors', 'result chars'), file=out)
    for tool, row in summary['tool_counts'].items():
        print('  %-24s %7d %8d %7d %14s' % (tool, row['calls'], row['results'], row['errors'],
                                           format(row['result_chars'], ',')), file=out)
    if len(summary['segments']) > 1:
        print('\nSEGMENTS (split at compact_boundary)', file=out)
        for seg in summary['segments']:
            opened = 'start' if seg['index'] == 0 else '%s, %s tokens before, %s after' % (
                seg['trigger'], seg['pre_tokens'], seg['post_tokens'])
            print('  %d: %d calls, %s  (%s)' % (seg['index'], seg['calls'], money(seg['usd']), opened), file=out)


def _print_reconciliation(summary, out):
    """Print the two-number headline, the gap, and the per-model reconciliation."""
    recon = summary['reconciliation']
    print('\nRECONCILIATION: session totals (last cost-state) vs transcript', file=out)
    if recon is None:
        print('  This log has no cost-state record, so there are no session totals to compare.', file=out)
        return
    totals = recon['totals']
    attributed = summary['totals']['attributed_usd']
    print('  Session total (cost-state tokens x our prices) : %s to %s' % (
        money(totals['session_total_usd_low']), money(totals['session_total_usd_high'])), file=out)
    print('  Attributed total (transcript, per call)        : %s' % money(attributed), file=out)
    print('  Gap, "%s":' % totals['label'], file=out)
    print('    tokens  ' + _gap_token_line(totals['gap_tokens']), file=out)
    print('    dollars %s (every cache write at the 5m rate) to %s (at the 1h rate)'
          % (money(totals['gap_usd_low']), money(totals['gap_usd_high'])), file=out)
    print('    The range exists because cost-state records only its combined cache-write count '
          'reliably; the 5m/1h split is incomplete.', file=out)
    print('  cross-check, costUSD reported by the client: %s' % money(totals['cost_usd_reported_cross_check']), file=out)
    print('\n  per model', file=out)
    for row in recon['models']:
        scope = _scope_label(row)
        print('    %s | transcript %d calls | %s' % (row['model'], row['transcript_calls'], scope), file=out)
        print('      gap tokens: ' + _gap_token_line(row['gap_tokens']), file=out)
        print('      session total %s to %s | attributed %s | gap %s to %s'
              % (money(row['session_total_usd_low']), money(row['session_total_usd_high']),
                 money(row['attributed_usd_per_call']), money(row['gap_usd_low']),
                 money(row['gap_usd_high'])), file=out)


def render_text(summary, out=sys.stdout):
    """Print the plain-text summary."""
    _print_overview(summary, out)
    _print_top_calls(summary, out)
    _print_tools(summary, out)
    _print_reconciliation(summary, out)


# ---------------------------------------------------------------- command line

def default_json_path(session_id):
    """Where --json writes by default: reports/ at the repo root (kept out of git)."""
    return os.path.join(REPO_ROOT, 'reports', session_id + '.summary.json')


def write_json(summary, path):
    """Write the normalized structure. A directory path gets the default file name inside it."""
    if os.path.isdir(path) or path.endswith(os.sep):
        path = os.path.join(path, summary['session']['session_id'] + '.summary.json')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2)
    return path


def main(argv=None):
    """Parse the session, print the summary, and optionally write the JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--session', required=True, help='path, session id, or "latest"')
    parser.add_argument('--json', nargs='?', const='', default=None, metavar='PATH',
                        help='also write the full normalized structure (default: reports/)')
    parser.add_argument('--root', default=parse.PROJECTS_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        path = parse.resolve_session(args.session, os.getcwd(), args.root)
    except FileNotFoundError as error:
        print('error: %s' % error, file=sys.stderr)
        return 2
    summary = build_summary(parse.parse_session(path))
    render_text(summary)
    if args.json is not None:
        written = write_json(summary, args.json or default_json_path(summary['session']['session_id']))
        print('\nJSON written to %s' % os.path.basename(written))
    return 0


if __name__ == '__main__':
    sys.exit(main())
