"""Build the receipt: one self-contained HTML page for a session.

    python3 -m src.receipt --session <path, id, "latest", or a folder> [--out <path>]
                           [--json [path]] [--no-open]
    python3 -m src.receipt --demo [--no-open]

The page follows docs/DESIGN.md and is built from src/page.py. Three layers: the answer (headline, tiles, where the
money went), the explanation (the costliest steps, how the conversation grew, how the cost piled up), and the
evidence (every step, every file, the findings, how to read the page, the fine print), collapsed until opened.

It loads nothing from the network and works offline by double-click. Apache ECharts is inlined from vendor/, or, for
a receipt kept in results/receipts/, linked as ../../vendor/echarts.min.js (see page.py).
Every string that came from a log is HTML-escaped. The page holds no prompt text, no file contents, and no tool output.
"""
import argparse
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from . import estimate, fmt, page, parse, paths, prices
from .fmt import count, minutes
from .page import (COST_COLORS, INK, KIND_COLORS, MARK_COLORS, CSS, Page, chip, collapsible, contrast_ink, esc, money,
                   money_column, percent, section, swatch, tag)
from .summarize import REPO_ROOT

TOP_ROWS = 50
TOP_FILES = 25
ZOOM_FROM = 40  # sessions with more calls than this get zoom on the two call-by-call charts
SHORT_KIND = {'start': 'Starting context', 'prompt': 'Prompts', 'thinking': 'Thinking', 'answer': 'Answers',
              'read_file': 'Reading', 'search': 'Searching', 'run_command': 'Commands', 'write_edit': 'Writing',
              'web': 'Web', 'subagent': 'Subagents', 'other_tool': 'Other tools', 'harness': 'Harness'}


def num(value, kind):
    """A number followed by its word."""
    return '%s %s' % (value, tag(kind))


def display_path(path, cwd):
    """A path relative to the project folder, with the home folder shown as ~. Mac and Windows paths."""
    home = os.path.expanduser('~')
    inside = paths.relative_under(path, cwd)
    if inside is not None:
        return inside
    under_home = paths.relative_under(path, home)
    if under_home is not None:
        return '~' + paths.flavor(home).sep + under_home
    return '~' if path == home else path


def clean_url(url):
    """A URL without its query or fragment (those can carry tokens)."""
    parts = urlsplit(url)
    return '%s://%s%s' % (parts.scheme, parts.netloc, parts.path) if parts.scheme else url


def when(stamp):
    """A log timestamp as 'Nov 12, 2026' in the local time zone."""
    parsed = estimate.parse_time(stamp)
    return parsed.astimezone().strftime('%b %d, %Y').replace(' 0', ' ') if parsed else 'unknown date'


def duration(seconds):
    """How long the session ran, in plain words."""
    if seconds < 1:
        return 'under a second'
    if seconds < 60:
        return '%d s' % round(seconds)
    hours, mins = divmod(int(seconds // 60), 60)
    return '%d h %d min' % (hours, mins) if hours else '%d min' % mins


def rate(value):
    """A price per million tokens with at least two decimals: $2.00, $0.125."""
    return ('$%.2f' % value) if round(value, 2) == value else ('$%.3f' % value)


# ---------------------------------------------------------------- layer 1: the answer

def _gap_share(recorded):
    """The gap as a share of the recorded total, using the low end of the range (so it is never overstated)."""
    if not recorded or not recorded['session_total_usd_low']:
        return None
    return recorded['gap_usd_low'] / recorded['session_total_usd_low']


def _top(est, pg):
    """Title line, the API-equivalent note, and the warnings that apply."""
    facts, totals = est['session'], est['totals']
    lines = ['<h1>%s</h1>' % esc(facts['project']),
             '<p class="meta">%s &middot; ran %s &middot; %s &middot; %s model calls and %s tool calls</p>' % (
                 esc(when(facts['started'])), esc(duration(facts['duration_seconds'])), esc(', '.join(facts['models'])),
                 count(facts['calls']), count(facts['tool_calls'])),
             '<p class="note">Every dollar on this page is %s: tokens times public API prices. On a subscription nobody is '
             'billed this amount.</p>' % pg.term('api')]
    if est['models_without_public_price']:
        lines.append('<p class="warn">%s of %s calls use a model with no public price (%s). Their tokens are shown; '
                     'their dollars are left out.</p>' % (
                         count(totals['calls_without_public_price']), count(facts['calls']),
                         esc(', '.join(est['models_without_public_price']))))
    gap = _gap_share(est['recorded_total'])
    if gap is not None and gap > 0.02:
        lines.append('<p class="warn">Claude Code recorded a session total about %s higher than this transcript total. '
                     'The difference is calls the transcript does not hold; this receipt shows only the transcript. '
                     'Details are in the fine print.</p>' % percent(gap))
    return '<header>%s</header>' % ''.join(lines)


def _headline(est, pg):
    """The single largest cause in plain words, with its dollars. It is an estimate, so it says so."""
    found = est['findings']['headline']
    if not found:
        return ''
    text = pg.annotate(esc(found['sentence']), ['start'])
    return '<p class="headline">%s%s</p>' % (text, '' if '(est.)' in found['sentence'] else ' ' + pg.tag('est'))


def _tile(value, label_html, kind, pg):
    """One big number with a label that never wraps mid-phrase, and its exact or est. word beside it."""
    return '<div class="tile"><div class="num">%s</div><div class="lbl"><span class="t">%s</span>%s</div></div>' % (
        value, label_html, pg.tag(kind))


def task_cost(est):
    """The cost of the task itself, the total minus the starting context, when the starting context is over half."""
    found = est['findings']['headline']
    return found['numbers']['task_usd'] if found and found['id'] == 'fixed_overhead' else None


def _tiles(est, pg):
    """Four tiles, and a fifth (the task itself) only when most of the cost was the starting context."""
    totals = est['totals']
    tiles = [_tile(money(totals['transcript_usd']), 'Total, API-equivalent', 'exact', pg),
             _tile(count(est['session']['calls']), pg.term('call', 'Model calls'), 'exact', pg),
             _tile(percent(totals['carried_share']), pg.term('resent', 'Re-sent') + ' share of cost', 'est', pg),
             _tile(money(est['rebuild_extra_usd']), pg.term('rebuild', 'Cache rebuild') + ' extra', 'est', pg)]
    task = task_cost(est)
    if task is not None:
        tiles.append(_tile(money(task), 'Cost of the task itself', 'est', pg))
    return '<section class="tiles" style="--n:%d">%s</section>' % (len(tiles), ''.join(tiles))


def _total_row(est):
    """The total of the lines above, with a check against the headline total at the top of the page."""
    lines_sum = sum(row['usd'] for row in est['kinds'])
    headline = est['totals']['transcript_usd']
    if abs(lines_sum - headline) <= estimate.SUM_BACK_TOLERANCE:
        check = '<span class="match">Matches the total at the top</span>'
    else:
        check = ('<span class="nomatch">Does not match: the lines add up to $%.6f, but the total at the top is $%.6f</span>'
                 % (lines_sum, headline))
    return ('<table class="legend totaltable"><tr class="totalrow"><td>Total of the lines above</td><td class="r">%s</td>'
            '<td class="r">100%%</td><td class="check">%s</td></tr></table>' % (money(lines_sum), check))


def kinds_option(est):
    """The ECharts option for where the money went: one horizontal stacked bar, labelled, in dollars."""
    rows = [r for r in est['kinds'] if r['usd'] > 0]
    total = est['totals']['transcript_usd']
    lead = sorted(rows, key=lambda r: -r['usd'])[:3]
    title = ('%s made up %s of the total' % (lead[0]['label'], fmt.percent(lead[0]['share'])) if len(lead) < 3 else
             'Three lines made up %s of the total' % fmt.percent(sum(r['share'] for r in lead)))
    series = []
    for row in rows:
        label = ''
        if row['share'] >= 0.12:
            label = '%s\n%s' % (SHORT_KIND[row['key']], fmt.percent(row['share']))
        elif row['share'] >= 0.04:
            label = fmt.percent(row['share'])
        tip = '<b>%s</b><br>%s &middot; %s of the total <span class="tag %s">%s</span>' % (
            esc(row['label']), money(row['usd']), percent(row['share']), 'exact' if row['exact'] else 'est',
            'exact' if row['exact'] else 'est.')
        color = KIND_COLORS[row['key']]
        series.append({'type': 'bar', 'name': row['label'], 'stack': 'total', 'barWidth': 44,
                       'data': [{'value': row['usd'], 'tip': tip}],
                       'itemStyle': {'color': color, 'borderColor': '#ffffff', 'borderWidth': 1},
                       'label': {'show': bool(label), 'position': 'inside', 'formatter': label,
                                 'color': contrast_ink(color), 'fontSize': 13, 'lineHeight': 16},
                       'emphasis': {'focus': 'series'}})
    decimals = 2 if total >= 0.1 else 3 if total >= 0.01 else 4
    return {'title': {'text': title, 'left': 0, 'top': 4, 'textStyle': {'fontSize': 16, 'fontWeight': 700, 'color': INK}},
            'tooltip': {'trigger': 'item', 'confine': True, 'formatter': 'fn:tip'},
            'grid': {'left': 8, 'right': 24, 'top': 44, 'bottom': 48},
            'xAxis': {'type': 'value', 'min': 0, 'max': total, 'name': 'Dollars, API-equivalent', 'nameLocation': 'middle',
                      'nameGap': 30, 'nameTextStyle': {'color': INK, 'fontSize': 13},
                      'axisLabel': {'formatter': 'fn:usd%d' % decimals, 'color': INK, 'fontSize': 13, 'showMaxLabel': False},
                      'splitLine': {'lineStyle': {'color': page.UI['line']}}},
            'yAxis': {'type': 'category', 'data': ['Total'], 'show': False},
            'series': series, 'textStyle': {'fontFamily': page.FONT_STACK}}


def _where(est, pg):
    """Layer 1 chart: one stacked bar, then the legend table (with its total row and check) and its CSV button."""
    rows = [r for r in est['kinds'] if r['usd'] > 0]
    total = est['totals']['transcript_usd']
    if not rows or not total:
        return section('where', 'Where did the money go?',
                       'Nothing here has a public price, so there are no dollars to split.', '')
    ranked = sorted(rows, key=lambda r: -r['usd'])
    top = ranked[0]
    answer = 'Most went to %s: %s of the %s total (%s). %s' % (
        esc(top['label'].lower()), money(top['usd']), money(total), percent(top['share']),
        pg.tag('exact') if top['exact'] else pg.tag('est'))
    bits = ['%s %s (%s)' % (r['label'], fmt.money(r['usd']), fmt.percent(r['share'])) for r in ranked[:3]]
    rest = total - sum(r['usd'] for r in ranked[:3])
    summary = 'The largest lines, in order: %s%s.' % (', '.join(bits), (', and the rest together %s' % fmt.money(rest))
                                                       if len(ranked) > 3 else '')
    cells = ['<tr><td>%s</td><td>%s</td><td class="r">%s</td><td class="r">%s</td><td>%s</td></tr>' % (
        swatch(KIND_COLORS[r['key']]), esc(r['label']), money(r['usd']), percent(r['share']),
        pg.tag('exact' if r['exact'] else 'est')) for r in rows]
    cut = (len(cells) + 1) // 2
    halves = [cells] if len(cells) <= 6 else [cells[:cut], cells[cut:]]
    legend = ''.join('<table class="legend kindlegend">%s</table>' % ''.join(half) for half in halves)
    chart = pg.chart('chart-kinds', kinds_option(est), 148, esc(summary) + ' ' + pg.tag('est'), 'Dollars by kind of work')
    csv_rows = [(r['label'], '%.6f' % r['usd'], '%.4f' % r['share'], 'exact' if r['exact'] else 'est') for r in est['kinds']]
    button = pg.csv_button('kinds', 'where-the-money-went.csv', ('line', 'usd_api_equivalent', 'share_of_total', 'basis'),
                           csv_rows)
    table = ('<div class="keep" id="kindtable"><div class="legendcols">%s</div>%s'
             '<p class="small">Each line is rounded, so the lines may not add up to the last cent. The total is the exact sum.'
             ' %s</p></div>' % (legend, _total_row(est), button))
    return section('where', 'Where did the money go?', answer, chart + table)


# ---------------------------------------------------------------- layer 2: the explanation

def _bar(parts, scale):
    """A bar split into output, new, carried (re-sent), and subagent work, drawn as SVG. Width is relative to `scale`."""
    total = sum(parts.values())
    fill = max(total / scale * 1000, 4.0) if scale else 4.0
    colors = {'output': COST_COLORS['output'], 'new': COST_COLORS['new'], 'carried': COST_COLORS['resent'],
              'subagent': COST_COLORS['subagent']}
    rects, x = [], 0.0
    for key in ('output', 'new', 'carried', 'subagent'):
        width = parts[key] / total * fill if total > 0 else 0.0
        if width > 0:
            rects.append('<rect x="%.2f" y="0" width="%.2f" height="12" fill="%s"/>' % (x, width, colors[key]))
            x += width
    return ('<svg class="costbar" viewBox="0 0 1000 12" preserveAspectRatio="none" role="img" aria-label="Cost split">'
            '<rect width="1000" height="12" fill="%s"/>%s</svg>' % (page.UI['track'], ''.join(rects)))


def _parts(step):
    """A step's own dollars as the four parts of a cost bar."""
    return {'output': step['output_usd'], 'new': step['new_usd'], 'carried': step['carried_usd'],
            'subagent': step['subagent']['usd'] if step['subagent'] else 0.0}


def _split_text(parts, pg):
    """The same split in words, each with its exact/est. word."""
    bits = ['Output %s %s' % (money(parts['output']), pg.tag('exact')),
            'New %s %s' % (money(parts['new']), pg.tag('est')),
            'Carried %s %s' % (money(parts['carried']), pg.tag('est'))]
    if parts['subagent']:
        bits.append('Subagent work %s %s' % (money(parts['subagent']), pg.tag('exact')))
    return ' &middot; '.join(bits)


def _step_numbers(numbers):
    """'Step 2' or 'Steps 2, 7 and 14'."""
    names = [str(n) for n in numbers]
    return 'Step ' + names[0] if len(names) == 1 else 'Steps ' + ', '.join(names[:-1]) + ' and ' + names[-1]


def _cost_legend(pg):
    """What the colours of a cost bar mean. The first time on the page, the terms explain themselves."""
    labels = (('output', esc('Output (the model\'s writing and thinking)')),
              ('new', pg.term('new', 'New') + ' (first time sent)'),
              ('resent', pg.term('carried', 'Carried cost') + ' (' + pg.term('resent', 're-sent') + ' on later calls)'),
              ('subagent', 'Subagent work'))
    return ' '.join('<span class="key">%s%s</span>' % (swatch(COST_COLORS[k]), v) for k, v in labels)


def _cards(est, pg):
    """The three biggest causes. Steps that share a target are merged into one card."""
    tops = est['findings']['top_steps']
    if not tops:
        return section('expensive', 'What made it expensive?', 'No step has a public price, so none can be ranked.', '')
    total = est['totals']['transcript_usd']
    added = sum(t['total_usd'] for t in tops)
    answer = ('The costliest %s added up to %s, %s of the total. A step\'s cost is its own output plus what its results cost '
              'to send, now and on every later call. %s' % ('step' if len(tops) == 1 else 'causes', money(added),
                                                            percent(added / total if total else 0), pg.tag('est')))
    cards = []
    for top in tops:
        total_html = '<span class="cardcost">%s</span>%s' % (
            money(top['total_usd']), ' <span class="sub">in total</span>' if top['times'] > 1 else '')
        cards.append(
            '<div class="card"><div class="cardhead">%s<b>%s</b></div><div>%s</div><div class="what">%s</div>%s'
            '<div class="split">%s</div><p class="why">%s</p></div>' % (
                chip(KIND_COLORS[top['kind']]), _step_numbers(top['steps']), total_html, esc(top['description']),
                _bar(top['parts'], top['total_usd']), _split_text(top['parts'], pg), esc(top['sentence'])))
    return section('expensive', 'What made it expensive?', answer,
                   '<div class="cards">%s</div><div class="legendline">%s</div>' % (''.join(cards), _cost_legend(pg)))


def call_costs(est):
    """The exact dollars of each main-thread call, with the subagent work that the call's step launched added in."""
    launched = {s['order']: s['subagent']['usd'] for s in est['steps'] if s['subagent']}
    return [(c['usd'] or 0.0) + launched.get(c['order'], 0.0) for c in est['calls']]


def _zoom(n):
    """Zoom controls for a long series: scroll or drag, plus a slider. Returns (controls, extra room at the bottom)."""
    if n <= ZOOM_FROM:
        return [], 0
    return [{'type': 'inside', 'filterMode': 'none'},
            {'type': 'slider', 'height': 20, 'bottom': 8, 'filterMode': 'none', 'borderColor': page.UI['line']}], 36


def _growth_statement(calls):
    """A statement title for the growth chart, with its own numbers."""
    first, peak = calls[0]['prompt_tokens'], max(c['prompt_tokens'] for c in calls)
    if len(calls) == 1:
        return 'The session made one call, with a prompt of %s tokens' % count(first)
    ratio = peak / first if first else 1.0
    if ratio >= 1.95:
        return 'Prompt size grew %dx over the session' % round(ratio)
    if ratio >= 1.1:
        return 'Prompt size grew %d%% over the session' % round((ratio - 1) * 100)
    return 'Prompt size stayed about the same over the session'


def growth_option(est):
    """The ECharts option for how the conversation grew: one stacked bar per call, markers for rebuilds and compactions."""
    calls, n = est['calls'], len(est['calls'])
    rebuilds = {s['order']: s['rebuild'] for s in est['steps'] if s['rebuild']}
    labels = [str(i + 1) for i in range(n)]
    zoom, extra_bottom = _zoom(n)
    common = {'type': 'bar', 'stack': 'prompt', 'large': n > 400, 'largeThreshold': 400}
    series = [dict(common, name='Re-sent', data=[c['resent_tokens'] for c in calls], itemStyle={'color': COST_COLORS['resent']}),
              dict(common, name='New', data=[c['new_tokens'] for c in calls], itemStyle={'color': COST_COLORS['new']})]
    legend = ['Re-sent', 'New']
    marks = [i for i, c in enumerate(calls) if c['order'] in rebuilds]
    if marks:
        series.append({'type': 'scatter', 'name': 'Cache rebuilt', 'symbol': 'triangle', 'symbolSize': 14,
                       'symbolOffset': [0, -12],
                       'itemStyle': {'color': MARK_COLORS['rebuild'], 'borderColor': '#ffffff', 'borderWidth': 1},
                       'data': [[i, calls[i]['prompt_tokens']] for i in marks], 'z': 5})
        legend.append('Cache rebuilt')
    cuts = [i for i in range(1, n) if calls[i]['segment'] != calls[i - 1]['segment']]
    if cuts:
        series.append({'type': 'line', 'name': 'Compacted', 'data': [], 'symbol': 'none',
                       'lineStyle': {'type': 'dashed', 'color': INK, 'width': 2}, 'itemStyle': {'color': INK},
                       'markLine': {'silent': True, 'symbol': 'none',
                                    'label': {'formatter': 'Compacted', 'position': 'insideEndTop', 'color': INK, 'fontSize': 13},
                                    'lineStyle': {'type': 'dashed', 'color': INK, 'width': 1.5},
                                    'data': [{'xAxis': i - 0.5} for i in cuts]}})
        legend.append('Compacted')
    return {'title': {'text': _growth_statement(calls), 'left': 0, 'top': 4,
                      'textStyle': {'fontSize': 16, 'fontWeight': 700, 'color': INK}},
            'legend': {'data': legend, 'left': 0, 'top': 32, 'itemWidth': 16, 'itemHeight': 12, 'itemGap': 24,
                       'textStyle': {'color': INK, 'fontSize': 13}},
            'tooltip': {'trigger': 'axis', 'axisPointer': {'type': 'shadow'}, 'confine': True, 'formatter': 'fn:growth_tip'},
            'grid': {'left': 8, 'right': 24, 'top': 100, 'bottom': 56 + extra_bottom, 'containLabel': True},
            'xAxis': {'type': 'category', 'data': labels, 'name': 'Model call, in order', 'nameLocation': 'middle',
                      'nameGap': 32, 'nameTextStyle': {'color': INK, 'fontSize': 13},
                      'axisLabel': {'color': INK, 'fontSize': 13}, 'axisTick': {'alignWithLabel': True}},
            'yAxis': {'type': 'value', 'name': 'Tokens in the prompt',
                      'nameTextStyle': {'color': INK, 'fontSize': 13, 'align': 'left'},
                      'axisLabel': {'formatter': 'fn:tok', 'color': INK, 'fontSize': 13},
                      'splitLine': {'lineStyle': {'color': page.UI['line']}}},
            'dataZoom': zoom, 'series': series, 'textStyle': {'fontFamily': page.FONT_STACK}}


def growth_data(est):
    """What the growth tooltips need, as plain numbers: tokens by type, the call's dollars, rebuild pauses, compactions."""
    calls = est['calls']
    rebuilds = {s['order']: s['rebuild'] for s in est['steps'] if s['rebuild']}
    rows = [[c['tokens']['input'], c['tokens']['cache_read'], c['tokens']['cache_write_5m'], c['tokens']['cache_write_1h'],
             c['tokens']['output'], c['prompt_tokens'], c['usd']] for c in calls]
    rebuilt = {str(i): [round(rebuilds[c['order']]['pause_minutes'] or 0, 1), rebuilds[c['order']]['miss_reason']]
               for i, c in enumerate(calls) if c['order'] in rebuilds}
    cuts = [i for i in range(1, len(calls)) if calls[i]['segment'] != calls[i - 1]['segment']]
    return {'calls': rows, 'rebuilds': rebuilt, 'compacted': cuts}


def _growth(est, pg):
    """Layer 2: how the conversation grew. Exact numbers, with a text summary under the chart."""
    calls = est['calls']
    if not calls:
        return ''
    first, last, peak = calls[0]['prompt_tokens'], calls[-1]['prompt_tokens'], est['totals']['largest_prompt_tokens']
    resent_share = sum(c['resent_tokens'] for c in calls) / max(sum(c['prompt_tokens'] for c in calls), 1)
    cuts = len(est['segments']) - 1
    notes = []
    if est['rebuilds']:
        notes.append('The saved copy expired %s time%s' % (count(est['rebuilds']), '' if est['rebuilds'] == 1 else 's'))
    if cuts:
        notes.append('the conversation was compacted %s time%s' % (count(cuts), '' if cuts == 1 else 's'))
    summary = ('The prompt was %s tokens on the first call and %s on the last; the largest was %s tokens. %s of all prompt '
               'tokens sent were re-sent material.%s' % (
                   count(first), count(last), count(peak), fmt.percent(resent_share),
                   (' ' + '; '.join(notes) + '.') if notes else ''))
    summary = esc(summary) + ' ' + pg.tag('exact')
    answer = ('Every call sends the whole conversation again, so the prompt only gets bigger: most of each bar is %s material, '
              'and a little is %s.' % (pg.term('resent', 're-sent'), pg.term('new', 'new')))
    pg.data['growth'] = growth_data(est)
    chart = pg.chart('chart-growth', growth_option(est), 440 if len(calls) <= ZOOM_FROM else 476, summary,
                     'Prompt size by model call')
    return section('growth', 'How did the conversation grow?', answer, chart)


def _running_statement(cum):
    """A statement title for the running-total chart: how far along the session half of the money was spent."""
    n = len(cum)
    if n == 1 or not cum[-1]:
        return 'All of the cost came from one call' if n == 1 else 'The calls had no public price'
    half = next(i for i, v in enumerate(cum) if v >= cum[-1] / 2)
    return 'Half of the cost was spent by call %d of %d' % (half + 1, n)


def running_option(est, cum, marks):
    """The ECharts option for the running total of dollars across calls, with the top steps marked on the line."""
    n = len(cum)
    zoom, extra_bottom = _zoom(n)
    points = [{'coord': [index, cum[index]], 'value': rank, 'symbolSize': 26,
               'itemStyle': {'color': color, 'borderColor': '#ffffff', 'borderWidth': 2},
               'label': {'show': True, 'formatter': str(rank), 'color': contrast_ink(color), 'fontSize': 13}}
              for index, rank, color in marks]
    decimals = 2 if cum[-1] >= 0.1 else 3 if cum[-1] >= 0.01 else 4
    return {'title': {'text': _running_statement(cum), 'left': 0, 'top': 4,
                      'textStyle': {'fontSize': 16, 'fontWeight': 700, 'color': INK}},
            'tooltip': {'trigger': 'axis', 'confine': True, 'formatter': 'fn:running_tip'},
            'grid': {'left': 8, 'right': 24, 'top': 72, 'bottom': 56 + extra_bottom, 'containLabel': True},
            'xAxis': {'type': 'category', 'data': [str(i + 1) for i in range(n)], 'name': 'Model call, in order',
                      'nameLocation': 'middle', 'nameGap': 32, 'boundaryGap': False,
                      'nameTextStyle': {'color': INK, 'fontSize': 13}, 'axisLabel': {'color': INK, 'fontSize': 13}},
            'yAxis': {'type': 'value', 'name': 'Dollars so far, API-equivalent',
                      'nameTextStyle': {'color': INK, 'fontSize': 13, 'align': 'left'},
                      'axisLabel': {'formatter': 'fn:usd%d' % decimals, 'color': INK, 'fontSize': 13},
                      'splitLine': {'lineStyle': {'color': page.UI['line']}}},
            'dataZoom': zoom, 'textStyle': {'fontFamily': page.FONT_STACK},
            'series': [{'type': 'line', 'name': 'Dollars so far', 'data': cum, 'symbol': 'none', 'step': 'end',
                        'lineStyle': {'color': INK, 'width': 3}, 'itemStyle': {'color': INK}, 'sampling': 'lttb',
                        'markPoint': {'data': points, 'silent': True}}]}


def _top_marks(est):
    """Where the top three steps sit on the running-total line: (call index, rank, kind colour), plus tooltip words."""
    position = {c['order']: i for i, c in enumerate(est['calls'])}
    by_number = {s['number']: s for s in est['steps']}
    marks, notes = [], {}
    for rank, card in enumerate(est['findings']['top_steps'], start=1):
        for number in card['steps']:
            index = position.get(by_number[number]['order'])
            if index is None:
                continue
            marks.append((index, rank, KIND_COLORS[card['kind']]))
            notes[str(index)] = [rank, number, card['description'], card['total_usd']]
    return marks, notes


def _running(est, pg):
    """Layer 2: the running total across calls, with the costliest steps marked on the line."""
    calls = est['calls']
    if not calls:
        return ''
    steps = call_costs(est)
    cum, running = [], 0.0
    for value in steps:
        running += value
        cum.append(round(running, 9))
    marks, notes = _top_marks(est)
    total = est['totals']['transcript_usd']
    pg.data['running'] = {'calls': [round(v, 9) for v in steps], 'top': notes}
    answer = ('The line climbs each time a call is paid for. The numbered markers are the costliest steps from the cards above, '
              'in the same order.')
    summary = 'The running total reaches %s by the last call.' % fmt.money(cum[-1])
    gap = total - cum[-1]
    if gap > estimate.SUM_BACK_TOLERANCE:
        summary += (' The other %s of the %s total is subagent work that no step launched, so it is not on this line.'
                    % (fmt.money(gap), fmt.money(total)))
    chart = pg.chart('chart-running', running_option(est, cum, marks), 384 if len(calls) <= ZOOM_FROM else 420,
                     esc(summary) + ' ' + pg.tag('exact'), 'Running total of dollars by model call')
    return section('piling', 'Where did the cost pile up over time?', answer, chart)


# ---------------------------------------------------------------- layer 3: the evidence

def _tool_lines(step, cwd):
    """The tool calls of a step for the detail view: tool, what it touched, result size, error."""
    lines = []
    for tool_call in step['tool_calls']:
        target, kind = tool_call['target'], tool_call['target_kind']
        shown = ''
        if kind == 'file_path' and target:
            shown = display_path(target, cwd)
        elif kind == 'url' and target:
            shown = clean_url(target)
        elif kind in ('skill', 'subagent_type') and target:
            shown = target
        elif tool_call['tool'] == 'Bash' and tool_call.get('bash'):
            shown = ' '.join(tool_call['bash']['words'])
        size = '' if tool_call['result_chars'] is None else ', result %s characters (exact)' % count(tool_call['result_chars'])
        error = ' &middot; <b>error</b>' if tool_call['is_error'] else ''
        lines.append('<li>%s %s%s%s</li>' % (esc(tool_call['tool']), esc(shown), size, error))
    return '<ul>%s</ul>' % ''.join(lines) if lines else '<p class="sub">No tool calls: the model answered.</p>'


def _flags(step):
    """Short flag texts for a step."""
    flags = []
    if step['rebuild']:
        info = step['rebuild']
        reason = ' (%s)' % info['miss_reason'] if info['miss_reason'] else ''
        flags.append('Cache rebuilt after %s%s: writing the conversation again cost %s (est.) more than re-sending it would have'
                     % (minutes(info['pause_minutes']), reason, fmt.money(info['extra_usd'])))
    if step['growth_skipped']:
        flags.append('Result size could not be read from growth')
    if not step['priced']:
        flags.append('No public price')
    if step['subagent']:
        flags.append('Subagent work')
    return flags


def _detail(step, cwd):
    """The expanded detail for one step: exact tokens, estimated tokens, flags, tool calls."""
    t = step['tokens']
    exact = ('Uncached input (input_tokens): %s &middot; Re-sent (cache_read_input_tokens): %s &middot; '
             'New written, 5 min (cache_creation, ephemeral_5m): %s &middot; New written, 1 h (ephemeral_1h): %s '
             '&middot; Output (output_tokens): %s, of which thinking %s' % (
                 count(t['input']), count(t['cache_read']), count(t['cache_write_5m']), count(t['cache_write_1h']),
                 count(t['output']), count(step['thinking_tokens'])))
    later = step['resent_calls']
    est = ('About %s tokens of this step\'s material (its output and its results) were first sent on the next call. '
           'They were sent again on %s later calls.' % (count(step['material_tokens']), count(later)))
    flags = ''.join('<li>%s</li>' % esc(f) for f in _flags(step))
    sub = ''
    if step['subagent']:
        sub = '<p><b>Subagent work:</b> %s subagent(s) made %s model calls, %s %s.</p>' % (
            count(step['subagent']['agents']), count(step['subagent']['calls']), money(step['subagent']['usd']), tag('exact'))
    return ('<td colspan="4"><div class="detailbox"><p><b>Exact tokens</b> %s<br>%s</p><p><b>Estimated</b> %s<br>%s</p>%s'
            '%s<p><b>Tool calls</b></p>%s</div></td>' % (
                tag('exact'), exact, tag('est'), est, sub,
                ('<ul class="flags">%s</ul>' % flags) if flags else '', _tool_lines(step, cwd)))


def _steps_csv(est):
    """Every step as CSV rows, with the exact or est. basis in each column name."""
    header = ('step', 'kind', 'what_happened', 'output_usd_exact', 'new_usd_est', 'carried_usd_est', 'subagent_usd_exact',
              'total_usd_est', 'tool_calls', 'flags')
    rows = [(s['number'], estimate.KIND_LABELS[s['kind']], s['description'], '%.6f' % s['output_usd'], '%.6f' % s['new_usd'],
             '%.6f' % s['carried_usd'], '%.6f' % (s['subagent']['usd'] if s['subagent'] else 0.0),
             '%.6f' % s['total_usd'] if s['priced'] else 'no public price', len(s['tool_calls']),
             '; '.join(f.split(':')[0] for f in _flags(s))) for s in est['steps']]
    return header, rows


def _steps(est, pg):
    """Layer 3: the table of every step, with search, sort, kind filter, row detail, top 50 then show all, and CSV."""
    steps, cwd = est['steps'], est['session']['cwd']
    ranked = sorted(steps, key=lambda s: -s['total_usd'])
    rank = {s['number']: i + 1 for i, s in enumerate(ranked)}
    scale = ranked[0]['total_usd'] if ranked else 0.0
    column = money_column([s['total_usd'] for s in steps if s['priced']])
    rows = []
    for step in steps:
        flag_html = ''.join('<span class="flag">%s</span>' % esc(f.split(' after')[0] if f.startswith('Cache') else f)
                            for f in _flags(step))
        total = column(step['total_usd']) if step['priced'] else 'no public price'
        text = ' '.join([step['description'], estimate.KIND_LABELS[step['kind']]]).lower()
        rows.append(
            '<tr class="step" tabindex="0" aria-expanded="false" data-order="%d" data-cost="%.9f" data-rank="%d" data-kind="%s" '
            'data-text="%s"><td class="r">%d</td><td>%s%s %s</td><td>%s</td><td class="r">%s</td></tr>' % (
                step['number'], step['total_usd'], rank[step['number']], step['kind'], esc(text), step['number'],
                chip(KIND_COLORS[step['kind']]), esc(step['description']), flag_html, _bar(_parts(step), scale), total)
            + '<tr class="detail" hidden>%s</tr>' % _detail(step, cwd))
    kinds = ''.join('<option value="%s">%s</option>' % (k, esc(l)) for k, l in estimate.KIND_LINES
                    if k in {s['kind'] for s in steps})
    header, csv_rows = _steps_csv(est)
    controls = ('<div class="controls"><label>Search <input type="search" id="search" placeholder="file or command"></label> '
                '<label>Sort <select id="sort"><option value="order">in order</option><option value="cost">by cost</option></select></label> '
                '<label>Show <select id="kind"><option value="all">all kinds</option>%s</select></label> '
                '<button id="showall" type="button">Show all %s steps</button> <span id="shown" class="sub"></span> %s</div>' % (
                    kinds, count(len(steps)), pg.csv_button('steps', 'every-step.csv', header, csv_rows)))
    table = ('<table id="steps"><thead><tr><th class="r">#</th><th>What happened</th><th>Output / new / carried</th>'
             '<th class="r">Total</th></tr></thead><tbody id="stepbody" data-limit="%d">%s</tbody></table>'
             '<div class="legendline">%s</div>' % (TOP_ROWS, ''.join(rows), _cost_legend(pg)))
    answer = ('One row per model call in the main thread. Click a row for detail. Costs are each step\'s own: its output, plus '
              'what its results cost to send. %s %s' % (pg.tag('exact'), pg.tag('est')))
    return collapsible('steps', 'What happened at every step?', answer, controls + table)


def _files(est, pg):
    """Layer 3: the files table. The path shows only when it differs from the file name."""
    cwd, files = est['session']['cwd'], est['files']
    if not files:
        return collapsible('files', 'Which files did it touch?', 'No file reads or edits were found.', '')
    column = money_column([r[k] for r in files for k in ('new_usd', 'carried_usd')])
    rows, csv_rows = [], []
    for i, row in enumerate(files):
        name, shown = os.path.basename(row['path']), display_path(row['path'], cwd)
        repeat = '<span class="flag">read %d times</span>' % (row['reads'] + row['bash_reads']) if row['read_more_than_once'] else ''
        where = '' if shown == name else '<br><span class="sub">%s</span>' % esc(shown)
        hidden = ' class="extra" hidden' if i >= TOP_FILES else ''
        rows.append('<tr%s><td><b>%s</b> %s%s</td><td class="r">%d</td><td class="r">%d</td><td class="r">%d</td>'
                    '<td class="r">%s</td><td class="r">%s</td><td class="r">%s</td></tr>' % (
                        hidden, esc(name), repeat, where, row['reads'], row['bash_reads'], row['writes'],
                        count(row['tokens_in']), column(row['new_usd']), column(row['carried_usd'])))
        csv_rows.append((name, shown, row['reads'], row['bash_reads'], row['writes'], round(row['tokens_in']),
                         '%.6f' % row['new_usd'], '%.6f' % row['carried_usd']))
    more = ('<button id="morefiles" type="button">Show all %s files</button>' % count(len(files))) if len(files) > TOP_FILES else ''
    button = pg.csv_button('files', 'files.csv', ('file', 'path', 'read_tool', 'shell_reads', 'written_or_edited',
                                                  'tokens_brought_in_est', 'new_usd_est', 'carried_usd_est'), csv_rows)
    answer = ('Files the agent read or changed, most expensive first. Tokens and costs are %s. "Shell reads" are files read '
              'inside Bash commands (cat, head, sed and so on).' % pg.tag('est'))
    table = ('<table class="files" id="filetable"><thead><tr><th>File</th><th class="r">Read tool</th><th class="r">Shell reads</th>'
             '<th class="r">Written or edited</th><th class="r">Tokens brought in</th><th class="r">New cost</th>'
             '<th class="r">Carried cost</th></tr></thead><tbody>%s</tbody></table>%s' % (''.join(rows), more))
    return collapsible('files', 'Which files did it touch?', answer, button + table)


def _findings(est):
    """Layer 3: the session findings. They state what happened and give no advice."""
    found = est['findings']['session']
    body = ''.join('<li>%s</li>' % esc(f['sentence']) for f in found) or '<li>Nothing stood out in this session.</li>'
    return collapsible('findings', 'What else stood out?',
                       'Other things the rules noticed. They say what happened, not what to do.',
                       '<ul class="findings">%s</ul>' % body)


def _price_keys(est):
    """The price-table keys used, one per model in the session."""
    seen = []
    for step in est['steps']:
        key = prices.canonical_model(step['model'])
        if key and key not in seen:
            seen.append(key)
    return seen


def _price_table(est, pg):
    """The prices used, per million tokens, with the date they were checked, and a CSV button."""
    seen = _price_keys(est)
    rows = ''.join('<tr><td>%s</td><td class="r">%s</td><td class="r">%s</td><td class="r">%s</td><td class="r">%s</td>'
                   '<td class="r">%s</td><td>%s</td></tr>' % (
                       esc(prices.PRICES[k]['name']), rate(prices.PRICES[k]['input']), rate(prices.PRICES[k]['cache_write_5m']),
                       rate(prices.PRICES[k]['cache_write_1h']), rate(prices.PRICES[k]['cache_read']), rate(prices.PRICES[k]['output']),
                       'checked' if prices.PRICES[k]['validated'] else 'not yet checked against a session total')
                   for k in seen)
    csv_rows = [(prices.PRICES[k]['name'], prices.PRICES[k]['input'], prices.PRICES[k]['cache_write_5m'],
                 prices.PRICES[k]['cache_write_1h'], prices.PRICES[k]['cache_read'], prices.PRICES[k]['output'],
                 'checked' if prices.PRICES[k]['validated'] else 'not yet checked', prices.PRICES_CHECKED) for k in seen]
    button = pg.csv_button('prices', 'prices.csv', ('model', 'input_per_million_usd', 'write_5m_per_million_usd',
                                                    'write_1h_per_million_usd', 'resent_per_million_usd',
                                                    'output_per_million_usd', 'against_session_totals', 'date_checked'), csv_rows)
    return button + ('<table class="legend"><tr><th>Model</th><th class="r">Input</th><th class="r">Write 5 min</th>'
                     '<th class="r">Write 1 h</th><th class="r">Re-sent</th><th class="r">Output</th>'
                     '<th>Against session totals</th></tr>%s</table>' % rows)


def _how_to_read(pg):
    """Layer 3: how to read the page, and a glossary of every term it uses."""
    body = ('<p>The agent works in <b>steps</b>: one call to the model, the tool calls it made, and what came back. Every call '
            'sends the whole conversation so far. Material the model has just seen is <b>new</b>; material sent again on a later '
            'call is <b>re-sent</b> (<b>carried</b> cost). A step\'s cost is its own output plus what its results cost to send, '
            'now and on every later call.</p>'
            '<p>The page has three layers: the answer at the top, the explanation under it, and the evidence in the sections that '
            'open and close. Every number carries a small word: <b>exact</b> means it was read from the log, <b>est.</b> means '
            'a fixed rule worked it out from the exact numbers. Colour is never the only cue; each colour sits next to its name.</p>'
            '<h3>Glossary</h3>%s' % pg.glossary())
    return collapsible('howto', 'How do I read this page?', 'In plain words, with every term the page uses explained.', body)


def _gap_html(est):
    """The paragraph about Claude Code's own session total next to the transcript total."""
    recorded, totals = est['recorded_total'], est['totals']
    if recorded and not any(recorded['gap_tokens'].values()):
        return ('<p><b>Session total recorded by Claude Code.</b> It matches the transcript exactly: every token it '
                'counted is in the transcript (%s). Claude Code\'s own dollar figure for the session is %s (it uses its own '
                'price table).</p>' % (money(totals['transcript_usd']), money(recorded['cost_usd_reported'])))
    if recorded:
        gap = _gap_share(recorded)
        return ('<p><b>Session total recorded by Claude Code.</b> Its own record of this session\'s tokens, priced with the same table, '
                'comes to %s to %s (the range depends on whether cache writes were 5 minute or 1 hour; the log records only the '
                'combined count reliably). The transcript total is %s. The gap is %s to %s, or about %s of the recorded total. '
                'It is made of calls that produce no record in the transcript. Claude Code\'s own dollar figure for the session is '
                '%s (it uses its own price table).</p>' % (
                    money(recorded['session_total_usd_low']), money(recorded['session_total_usd_high']),
                    money(totals['transcript_usd']), money(recorded['gap_usd_low']), money(recorded['gap_usd_high']),
                    percent(gap or 0), money(recorded['cost_usd_reported'])))
    return ('<p><b>Session total recorded by Claude Code.</b> This log has none yet. A session that is still running '
            'usually has not written one, so there is nothing to compare the transcript total with.</p>')


def _fine_print(est, pg):
    """Layer 3: what is exact and what is estimated, prices and their date, validation, and the known limits."""
    unvalidated = ''
    if est['models_not_validated']:
        unvalidated = '<p><b>Prices not yet checked against a session total:</b> %s. %s</p>' % (
            esc(', '.join(est['models_not_validated'])), esc(prices.NOT_VALIDATED_NOTE.capitalize() + '.'))
    bash = est['bash']
    body = ('<h3>What is exact and what is estimated</h3><ul>'
            '<li><b>Exact</b>: tokens of every model call, the total, the largest prompt (%s tokens), thinking tokens, and each '
            'step\'s output cost.</li>'
            '<li><b>Est.</b>: how the input bill is split between items. The log records tokens per call, not per file or per tool. '
            'Result sizes come from how much the prompt grew after each step; typed prompts are sized at %.1f characters per token.</li>'
            '<li>The split always adds back up to the exact transcript total (checked on every build: difference $%.9f).</li></ul>'
            '<h3>Prices</h3><p>Dollars are API-equivalent. Source: %s, checked %s.</p>%s%s%s'
            '<h3>Known limits</h3><ul>'
            '<li>%s step(s) had growth smaller than the previous output (context trimmed or thinking dropped), so their results '
            'could not be sized from growth.</li>'
            '<li>%s call(s) were flagged "cache rebuilt": they paid for more than twice the new tokens, and at least %s more.</li>'
            '<li>Searches and file reads hidden inside Bash commands are found by a word table, so those lines are estimates. '
            '%s of %s Bash calls could not be classified.</li>'
            '<li>Work done by subagents is added to the step that launched it, as one exact amount. It is not broken down here, '
            'and files read by subagents are not in the Files table.</li>'
            '<li>Subagents that no step launched: %s.</li>'
            '<li>Only the main thread is drawn in the two call-by-call charts.</li></ul>' % (
                count(est['totals']['largest_prompt_tokens']), estimate.CHARS_PER_TOKEN, est['sum_back']['difference_usd'],
                esc(prices.PRICES_URL), esc(prices.PRICES_CHECKED), _price_table(est, pg), _gap_html(est), unvalidated,
                count(est['skipped_pairs']), count(est['rebuilds']), count(estimate.REBUILD_MIN_EXTRA),
                percent(bash['other_command_share']), count(bash['calls']), count(len(est['unlinked_subagents']))))
    return collapsible('fineprint', 'What is in the fine print?', 'The method, the prices and the date they were checked, '
                       'how the totals were validated, and what the numbers cannot tell you.', body)


# ---------------------------------------------------------------- the page

PAGE_JS = r"""
(function(){
'use strict';
var P=window.PAGE,D=P.data,F=P.fn;
function $(s,r){return (r||document).querySelector(s);}
function $$(s,r){return [].slice.call((r||document).querySelectorAll(s));}
var BADGE_E='<span class="tag exact">exact</span>',BADGE_S='<span class="tag est">est.</span>';
F.growth_tip=function(ps){
 var i=ps[0].dataIndex,g=D.growth,c=g.calls[i],h='<b>Call '+(i+1)+' of '+g.calls.length+'</b><br>';
 h+='Prompt: '+F.int(c[5])+' tokens '+BADGE_E+'<br>';
 h+='Re-sent (from the saved copy): '+F.int(c[1])+'<br>';
 h+='New, not saved: '+F.int(c[0])+'<br>New, saved for 5 minutes: '+F.int(c[2])+'<br>New, saved for 1 hour: '+F.int(c[3])+'<br>';
 h+='Output: '+F.int(c[4])+' tokens<br>';
 h+='Cost of this call: '+(c[6]===null?'no public price':F.money(c[6]))+' '+BADGE_E;
 if(g.rebuilds[i]){h+='<br><b>Cache rebuilt</b> after a pause of '+g.rebuilds[i][0]+' minutes'+(g.rebuilds[i][1]?' ('+g.rebuilds[i][1]+')':'');}
 if(g.compacted.indexOf(i)>=0)h+='<br><b>Starts after a compaction</b>';
 return h;
};
F.running_tip=function(ps){
 var i=ps[0].dataIndex,r=D.running,t=r.top[String(i)];
 var h='<b>Call '+(i+1)+' of '+r.calls.length+'</b><br>This call: '+F.money(r.calls[i])+' '+BADGE_E+'<br>Running total: '+F.money(ps[0].data)+' '+BADGE_E;
 if(t)h+='<br><b>#'+t[0]+' costliest</b>: step '+t[1]+', '+t[2]+', '+F.money(t[3])+' '+BADGE_S;
 return h;
};
P.start();
/* the table of every step: search, sort, kind filter, top 50 then show all, row detail */
var body=document.getElementById('stepbody');
if(body){
 var rows=$$('tr.step',body),limit=parseInt(body.getAttribute('data-limit'),10),showAll=rows.length<=limit;
 rows.forEach(function(r){r._d=r.nextElementSibling;});
 var sortSel=$('#sort'),kindSel=$('#kind'),search=$('#search'),btn=$('#showall'),shown=$('#shown');
 var number=function(r,k){return parseFloat(r.getAttribute(k));};
 var apply=function(){
  var byCost=sortSel.value==='cost',q=search.value.trim().toLowerCase(),narrowed=q!==''||kindSel.value!=='all';
  rows.sort(function(a,b){return byCost?(number(b,'data-cost')-number(a,'data-cost'))||(number(a,'data-order')-number(b,'data-order')):number(a,'data-order')-number(b,'data-order');});
  var n=0;
  rows.forEach(function(r){
   body.appendChild(r);body.appendChild(r._d);
   var ok=(kindSel.value==='all'||r.getAttribute('data-kind')===kindSel.value)&&(q===''||r.getAttribute('data-text').indexOf(q)>=0)&&(showAll||narrowed||parseInt(r.getAttribute('data-rank'),10)<=limit);
   r.hidden=!ok;if(!ok){r._d.hidden=true;r.setAttribute('aria-expanded','false');}else{n++;}
  });
  shown.textContent=(showAll||narrowed)?('Showing '+F.int(n)+' of '+F.int(rows.length)+' steps'):('Showing the '+limit+' most expensive of '+F.int(rows.length)+' steps');
  btn.hidden=showAll;
 };
 var toggle=function(r){r._d.hidden=!r._d.hidden;r.setAttribute('aria-expanded',String(!r._d.hidden));};
 rows.forEach(function(r){r.addEventListener('click',function(){toggle(r);});r.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(r);}});});
 sortSel.addEventListener('change',apply);kindSel.addEventListener('change',apply);search.addEventListener('input',apply);
 btn.addEventListener('click',function(){showAll=true;apply();});apply();
}
var more=document.getElementById('morefiles');
if(more){more.addEventListener('click',function(){$$('#filetable tr.extra').forEach(function(r){r.hidden=false;});more.hidden=true;});}
})();
"""


def render(est, library='inline'):
    """The whole page as one string. library is "inline" (self-contained) or "linked" (for results/receipts/)."""
    pg = Page(library)
    title = 'Receipt: %s, %s' % (est['session']['project'], when(est['session']['started']))
    body = ''.join([_top(est, pg), _headline(est, pg), _tiles(est, pg), _where(est, pg), _cards(est, pg), _growth(est, pg),
                    _running(est, pg), _steps(est, pg), _files(est, pg), _findings(est), _how_to_read(pg), _fine_print(est, pg)])
    return pg.shell(title, body, PAGE_JS)


# ---------------------------------------------------------------- command line

def resolve_target(arg, cwd=None, root=parse.PROJECTS_ROOT):
    """A path, id, 'latest', or a folder (meaning the latest session that ran in it) to a session file."""
    cwd = cwd or os.getcwd()
    if os.path.isdir(arg):
        return parse.latest_session(os.path.abspath(arg), root)
    return parse.resolve_session(arg, cwd, root)


def _target_path(value, default_name, session_id):
    """Where an output file goes: reports/ by default; a directory gets the default file name."""
    if not value:
        return os.path.join(REPO_ROOT, 'reports', session_id + default_name)
    if os.path.isdir(value) or value.endswith(os.sep):
        return os.path.join(value, session_id + default_name)
    return value


def _write(path, text):
    """Write a text file, creating the folder."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)


def build(session_path):
    """Parse a session and build its estimated layer."""
    return estimate.build_estimate(parse.parse_session(session_path))


def _report(est, path, out):
    """The three plain lines: where the file is, the total, and the most expensive step (a single step)."""
    priced = [s for s in est['steps'] if s['priced']]
    best = max(priced, key=lambda s: s['total_usd']) if priced else None
    print('Receipt: %s' % path, file=out)
    print('Total: %s (API-equivalent, exact tokens at public API prices)' % fmt.money(est['totals']['transcript_usd']), file=out)
    print('Most expensive step: %s' % ('#%d, %s, %s' % (best['number'], best['description'], fmt.money(best['total_usd']))
                                       if best else 'none (no step has a public price)'), file=out)


def main(argv=None, out=None):
    """Build the receipt, write it, print three lines, and open it unless told not to."""
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--session', help='path, session id, "latest", or a folder')
    parser.add_argument('--demo', action='store_true', help='build docs/demo-receipt.html from made-up data')
    parser.add_argument('--out', help='where to write the HTML (default: reports/<session-id>.receipt.html)')
    parser.add_argument('--json', nargs='?', const='', default=None, metavar='PATH',
                        help='also write the estimated layer (default: reports/<session-id>.receipt.json)')
    parser.add_argument('--no-open', action='store_true', help='do not open the page in the browser')
    parser.add_argument('--root', default=parse.PROJECTS_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.demo and not args.session:
        parser.error('give --session or --demo')
    try:
        if args.demo:
            from tests.make_demo_session import write_demo_session
            with tempfile.TemporaryDirectory() as folder:
                session_path = write_demo_session(folder)
                est = build(session_path)
            html_path = args.out or os.path.join(REPO_ROOT, 'docs', 'demo-receipt.html')
        else:
            session_path = resolve_target(args.session, root=args.root)
            est = build(session_path)
            html_path = _target_path(args.out, '.receipt.html', est['session']['session_id'])
        _write(html_path, render(est))
    except (FileNotFoundError, estimate.ReceiptError, page.PageError) as error:
        print('error: %s' % error, file=sys.stderr)
        return 2
    if args.json is not None:
        _write(_target_path(args.json, '.receipt.json', est['session']['session_id']), json.dumps(est, indent=2))
    _report(est, html_path, out)
    if not args.no_open:
        webbrowser.open(Path(html_path).resolve().as_uri())
    return 0


if __name__ == '__main__':
    sys.exit(main())
