"""Build the receipt: one self-contained HTML page for a session.

    python3 -m src.receipt --session <path, id, "latest", or a folder> [--out <path>]
                           [--json [path]] [--no-open]
    python3 -m src.receipt --demo [--no-open]

The page has inline CSS, inline SVG, and a little inline JavaScript (sort, filter, expand). It loads
nothing from the network and works offline by double-click. Every string that came from a log is
HTML-escaped. The page holds no prompt text, no file contents, and no tool output.
"""
import argparse
import html
import json
import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from . import estimate, fmt, parse, paths, prices
from .fmt import count, minutes, short_tokens
from .summarize import REPO_ROOT

# One colour per kind, the same in the bar, the cards, and the rows (Paul Tol's "muted" set, which
# stays distinguishable for the common kinds of colour blindness). Colour is never the only cue.
KIND_COLORS = {
    'start': '#88CCEE', 'prompt': '#332288', 'thinking': '#AA4499', 'answer': '#CC6677',
    'read_file': '#117733', 'search': '#DDCC77', 'run_command': '#882255', 'write_edit': '#44AA99',
    'web': '#999933', 'subagent': '#E69F00', 'other_tool': '#888888', 'harness': '#CCCCCC',
}
COST_COLORS = {'output': '#1B2A49', 'new': '#0077BB', 'carried': '#99DDFF', 'subagent': '#EE7733'}
TOP_ROWS = 50
TOP_FILES = 25

E = html.escape


def esc(value):
    """HTML-escape any string that came from a log."""
    return E(str(value), quote=True)


def money(value):
    """Dollars for the page (two decimals, "<$0.01" under a cent), safe to put in HTML."""
    return esc(fmt.money(value))


def percent(share):
    """A share for the page ("<0.1%" under a tenth of a percent), safe to put in HTML."""
    return esc(fmt.percent(share))


def money_column(values):
    """A formatter that gives every row of one table column the same number of decimals."""
    inner = fmt.money_column(values)
    return lambda value: esc(inner(value))


def tag(kind):
    """The word that goes with every number: exact, or est."""
    return '<span class="tag %s">%s</span>' % (kind, 'exact' if kind == 'exact' else 'est.')


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
    if seconds < 60:
        return 'under a minute'
    hours, mins = divmod(int(seconds // 60), 60)
    return '%d h %d min' % (hours, mins) if hours else '%d min' % mins


# ---------------------------------------------------------------- page pieces

def _top(est):
    """Title, one sentence, the API-equivalent note, and the gap note when it is above 2 percent."""
    facts, totals = est['session'], est['totals']
    recorded = est['recorded_total']
    lines = ['<h1>%s</h1>' % esc(facts['project']),
             '<p class="sub">%s &middot; ran %s &middot; %s</p>' % (
                 esc(when(facts['started'])), esc(duration(facts['duration_seconds'])),
                 esc(', '.join(facts['models'])))]
    lines.append('<p class="lede">%s model calls and %s tool calls. Total at public API prices: <b>%s</b> %s.</p>' % (
        count(facts['calls']), count(facts['tool_calls']), money(totals['transcript_usd']), tag('exact')))
    lines.append('<p class="note">Dollars on this page are <b>API-equivalent</b>: tokens times public API prices. '
                 'On a subscription nobody is billed this amount.</p>')
    if est['models_without_public_price']:
        lines.append('<p class="warn">%s of %s calls use a model with no public price (%s). Their tokens are shown; '
                     'their dollars are left out.</p>' % (
                         count(totals['calls_without_public_price']), count(facts['calls']),
                         esc(', '.join(est['models_without_public_price']))))
    gap = _gap_share(recorded)
    if gap is not None and gap > 0.02:
        lines.append('<p class="warn">Claude Code recorded a session total about %s higher than this transcript total. '
                     'The difference is calls the transcript does not hold; this receipt shows only the transcript. '
                     'Details are in the fine print.</p>' % percent(gap))
    return '<header>%s</header>' % ''.join(lines)


def _gap_share(recorded):
    """The gap as a share of the recorded total, using the low end of the range (so it is never overstated)."""
    if not recorded or not recorded['session_total_usd_low']:
        return None
    return recorded['gap_usd_low'] / recorded['session_total_usd_low']


def _tiles(est):
    """Four big numbers."""
    totals = est['totals']
    tiles = [(money(totals['transcript_usd']), 'Total, API-equivalent', 'exact'),
             (count(est['session']['calls']), 'Model calls', 'exact'),
             (count(totals['largest_prompt_tokens']), 'Largest prompt, in tokens', 'exact'),
             (percent(totals['carried_share']), 'Of the dollars went to re-sending earlier material', 'est.')]
    cells = ''.join('<div class="tile"><div class="num">%s</div><div class="lbl">%s %s</div></div>' % (
        value, esc(label), tag('exact' if word == 'exact' else 'est')) for value, label, word in tiles)
    return '<section class="tiles">%s</section>' % cells


def swatch(color, cls='sw', size=14):
    """A colour square drawn as inline SVG, so it survives printing and PDF export."""
    return ('<svg class="%s" width="%d" height="%d" viewBox="0 0 %d %d" aria-hidden="true">'
            '<rect x="0.5" y="0.5" width="%d" height="%d" rx="3" fill="%s" stroke="#00000040"/></svg>'
            % (cls, size, size, size, size, size - 1, size - 1, color))


def chip(color):
    """The small kind-colour square in front of a row."""
    return swatch(color, 'chip', 12)


def _headline(est):
    """One sentence under the tiles: the single largest cause, taken from the findings."""
    found = est['findings']['headline']
    return '<p class="headline">%s</p>' % esc(found['sentence']) if found else ''


def _total_row(est):
    """The total of the lines above, with a check against the headline total at the top of the page."""
    lines_sum = sum(row['usd'] for row in est['kinds'])
    headline = est['totals']['transcript_usd']
    if abs(lines_sum - headline) <= estimate.SUM_BACK_TOLERANCE:
        check = '<span class="match">Matches the total at the top</span>'
    else:
        check = ('<span class="nomatch">Does not match: the lines add up to $%.6f, but the total at the top is $%.6f</span>'
                 % (lines_sum, headline))
    return ('<tr class="totalrow"><td></td><td>Total of the lines above</td><td class="r">%s</td><td class="r">100%%</td>'
            '<td class="check">%s</td></tr>' % (money(lines_sum), check))


def _where(est):
    """The stacked bar by kind, with a legend that gives dollars and percent, and a total row."""
    rows = [r for r in est['kinds'] if r['usd'] > 0]
    x, rects = 0.0, []
    for row in rows:
        width = row['share'] * 1000
        rects.append('<rect x="%.2f" y="0" width="%.2f" height="46" fill="%s"><title>%s: %s, %s</title></rect>' % (
            x, max(width, 0.0), KIND_COLORS[row['key']], esc(row['label']), money(row['usd']), percent(row['share'])))
        x += width
    legend = ''.join(
        '<tr><td>%s</td><td>%s</td><td class="r">%s</td><td class="r">%s</td><td>%s</td></tr>' % (
            swatch(KIND_COLORS[r['key']]), esc(r['label']), money(r['usd']), percent(r['share']),
            tag('exact' if r['exact'] else 'est')) for r in rows)
    return ('<section class="keepsec"><h2>Where the money went</h2><p class="sub">Every dollar of the transcript total, by what it was spent on.</p>'
            '<div class="keep"><svg class="kindbar" viewBox="0 0 1000 46" role="img" aria-label="Dollars by kind">%s</svg>'
            '<table class="legend kindlegend">%s%s</table>'
            '<p class="small">Each line is rounded, so the lines may not add up to the last cent. The total is the exact sum.</p>'
            '</div></section>' % (''.join(rects), legend, _total_row(est)))


def _bar(parts, scale):
    """A bar split into output, new, carried, and subagent work, drawn as SVG. Width is relative to `scale`."""
    total = sum(parts.values())
    fill = max(total / scale * 1000, 4.0) if scale else 4.0
    rects, x = [], 0.0
    for key in ('output', 'new', 'carried', 'subagent'):
        width = parts[key] / total * fill if total > 0 else 0.0
        if width > 0:
            rects.append('<rect x="%.2f" y="0" width="%.2f" height="12" fill="%s"/>' % (x, width, COST_COLORS[key]))
            x += width
    return ('<svg class="costbar" viewBox="0 0 1000 12" preserveAspectRatio="none" role="img" aria-label="Cost split">'
            '<rect width="1000" height="12" fill="#ECEAE4"/>%s</svg>' % ''.join(rects))


def _parts(step):
    """A step's own dollars as the four parts of a cost bar."""
    return {'output': step['output_usd'], 'new': step['new_usd'], 'carried': step['carried_usd'],
            'subagent': step['subagent']['usd'] if step['subagent'] else 0.0}


def _split_text(parts):
    """The same split in words, each with its exact/est. word."""
    bits = ['Output %s %s' % (money(parts['output']), tag('exact')),
            'New %s %s' % (money(parts['new']), tag('est')),
            'Carried %s %s' % (money(parts['carried']), tag('est'))]
    if parts['subagent']:
        bits.append('Subagent work %s %s' % (money(parts['subagent']), tag('exact')))
    return ' &middot; '.join(bits)


def _step_numbers(numbers):
    """'Step 2' or 'Steps 2, 7 and 14'."""
    names = [str(n) for n in numbers]
    return 'Step ' + names[0] if len(names) == 1 else 'Steps ' + ', '.join(names[:-1]) + ' and ' + names[-1]


def _cards(est):
    """The three biggest causes. Steps that share a target are merged into one card."""
    cards = []
    for top in est['findings']['top_steps']:
        total = '<span class="cardcost">%s</span>%s' % (money(top['total_usd']), ' <span class="sub">in total</span>' if top['times'] > 1 else '')
        cards.append(
            '<div class="card"><div class="cardhead">%s<b>%s</b></div><div class="cardmoney">%s</div><div class="what">%s</div>%s'
            '<div class="split">%s</div><p class="why">%s</p></div>' % (
                chip(KIND_COLORS[top['kind']]), _step_numbers(top['steps']), total, esc(top['description']),
                _bar(top['parts'], top['total_usd']), _split_text(top['parts']), esc(top['sentence'])))
    body = ''.join(cards) or '<p class="sub">No step has a public price, so none can be ranked.</p>'
    return ('<section><h2>The three most expensive steps</h2><p class="sub">A step\'s cost is its own output plus what '
            'its results cost to send, now and on every later call. Steps that touched the same file are merged into one card.</p>'
            '<div class="cards">%s</div><div class="legendline">%s</div></section>' % (body, _cost_legend()))


def _cost_legend():
    """What the colours of a cost bar mean."""
    labels = (('output', 'Output (the model\'s writing and thinking)'), ('new', 'New (first time sent)'),
              ('carried', 'Carried (re-sent on later calls)'), ('subagent', 'Subagent work'))
    return ' '.join('<span class="key">%s%s</span>' % (swatch(COST_COLORS[k]), esc(v)) for k, v in labels)


def _nice_ceiling(value):
    """A round number at or above value (1, 2, 2.5, 5 or 10 times a power of ten)."""
    magnitude = 10 ** (len(str(int(max(value, 1)))) - 1)
    for factor in (1, 2, 2.5, 5, 10):
        if factor * magnitude >= value:
            return factor * magnitude
    return 10 * magnitude


def _x_ticks(n):
    """Which call numbers get a label on the x axis: about eight, at round numbers, plus the last."""
    step = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000) if n / s <= 8)
    ticks = [1] + [k for k in range(step, n + 1, step) if k > 1]
    return ticks if n - ticks[-1] >= step / 2 or n in ticks else ticks[:-1] + [n]


GROWTH = {'left': 78, 'right': 990, 'top': 34, 'bottom': 310, 'width': 1000, 'height': 392}


def _growth_axes(peak, n):
    """Gridlines, y labels, x ticks, and axis titles for the growth chart."""
    g, top = GROWTH, _nice_ceiling(peak)
    span = g['bottom'] - g['top']
    out = ['<text x="%d" y="18" font-size="15" fill="#333" font-weight="600">Tokens in the prompt</text>' % g['left']]
    for i in range(5):
        y = g['bottom'] - span * i / 4
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>' % (
            g['left'], y, g['right'], y, '#999' if i == 0 else '#E3E0D8'))
        out.append('<text x="%d" y="%.1f" font-size="14" fill="#444" text-anchor="end">%s</text>' % (
            g['left'] - 8, y + 5, short_tokens(top * i / 4)))
    slot = (g['right'] - g['left']) / n
    for k in _x_ticks(n):
        x = g['left'] + slot * (k - 0.5)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#999"/>' % (x, g['bottom'], x, g['bottom'] + 5))
        out.append('<text x="%.1f" y="%d" font-size="14" fill="#444" text-anchor="middle">%d</text>' % (x, g['bottom'] + 24, k))
    out.append('<text x="%d" y="%d" font-size="15" fill="#333" font-weight="600" text-anchor="middle">Model call, in order</text>' % (
        (g['left'] + g['right']) // 2, g['bottom'] + 52))
    return ''.join(out), top


def _marker(kind):
    """A drawn legend marker (inline SVG, so it prints)."""
    shapes = {'resent': '<rect x="1" y="1" width="14" height="14" rx="2" fill="#0077BB"/>',
              'new': '<rect x="1" y="1" width="14" height="14" rx="2" fill="#EE7733"/>',
              'rebuild': '<polygon points="8,15 1,2 15,2" fill="#CC3311"/>',
              'compacted': '<line x1="8" y1="0" x2="8" y2="16" stroke="#222" stroke-width="2" stroke-dasharray="4 3"/>'}
    return '<svg class="mk" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">%s</svg>' % shapes[kind]


def _growth(est):
    """One bar per main-thread call: prompt size split into re-sent and new. Exact numbers."""
    calls = est['calls']
    if not calls:
        return ''
    g = GROWTH
    rebuilds = {s['order']: s['rebuild'] for s in est['steps'] if s['rebuild']}
    axes, top = _growth_axes(max(c['prompt_tokens'] for c in calls) or 1, len(calls))
    span, slot = g['bottom'] - g['top'], (g['right'] - g['left']) / len(calls)
    bars, marks, last_segment = [], [], calls[0]['segment']
    for i, call in enumerate(calls):
        x, bw = g['left'] + i * slot + slot * 0.07, max(slot * 0.86, 0.6)
        h_resent, h_new = span * call['resent_tokens'] / top, span * call['new_tokens'] / top
        tip = 'Call %d: %s tokens in the prompt (%s re-sent, %s new)' % (
            i + 1, count(call['prompt_tokens']), count(call['resent_tokens']), count(call['new_tokens']))
        bars.append('<g><title>%s</title><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#0077BB"/>'
                    '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#EE7733"/></g>' % (
                        tip, x, g['bottom'] - h_resent, bw, h_resent, x, g['bottom'] - h_resent - h_new, bw, h_new))
        if call['segment'] != last_segment:
            edge = g['left'] + i * slot
            marks.append('<line x1="%.2f" y1="%d" x2="%.2f" y2="%d" stroke="#222" stroke-width="1.5" stroke-dasharray="5 4"/>'
                         '<text x="%.2f" y="%d" font-size="13" fill="#222">compacted</text>' % (
                             edge, g['top'] - 8, edge, g['bottom'], edge + 4, g['top'] + 6))
            last_segment = call['segment']
        if call['order'] in rebuilds:
            cx, peak_y = x + bw / 2, g['bottom'] - h_resent - h_new
            marks.append('<polygon points="%.2f,%.2f %.2f,%.2f %.2f,%.2f" fill="#CC3311"><title>Cache rebuilt after %s</title>'
                         '</polygon>' % (cx, peak_y - 3, cx - 7, peak_y - 17, cx + 7, peak_y - 17,
                                          esc(minutes(rebuilds[call['order']]['pause_minutes']))))
    return ('<section class="keepsec"><h2>How the conversation grew</h2><p class="sub">One bar per model call in the main thread, in order. '
            'Height is the size of the prompt that call sent. These numbers are %s.</p>'
            '<div class="keep"><svg class="growth" viewBox="0 0 %d %d" role="img" aria-label="Prompt size by call">%s%s%s</svg>'
            '<div class="legendline"><span class="key">%sRe-sent (served from the saved copy)</span> '
            '<span class="key">%sNew (written for the first time)</span> '
            '<span class="key">%sCache rebuilt (the saved copy had expired)</span> '
            '<span class="key">%sCompacted</span></div></div></section>' % (
                tag('exact'), g['width'], g['height'], axes, ''.join(bars), ''.join(marks),
                _marker('resent'), _marker('new'), _marker('rebuild'), _marker('compacted')))


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
                     % (minutes(info['pause_minutes']), reason, money(info['extra_usd'])))
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
    return ('<td colspan="5"><div class="detailbox"><p><b>Exact tokens</b> %s<br>%s</p><p><b>Estimated</b> %s<br>%s</p>%s'
            '%s<p><b>Tool calls</b></p>%s</div></td>' % (
                tag('exact'), exact, tag('est'), est, sub,
                ('<ul class="flags">%s</ul>' % flags) if flags else '', _tool_lines(step, cwd)))


def _steps(est):
    """The table of every step, with sort, filter, expand, and a top-50 default."""
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
        rows.append(
            '<tr class="step" tabindex="0" aria-expanded="false" data-order="%d" data-cost="%.9f" data-rank="%d" data-kind="%s">'
            '<td class="r">%d</td><td>%s%s %s</td>'
            '<td>%s</td><td class="r">%s</td></tr>' % (
                step['number'], step['total_usd'], rank[step['number']], step['kind'], step['number'],
                chip(KIND_COLORS[step['kind']]), esc(step['description']),
                flag_html, _bar(_parts(step), scale), total)
            + '<tr class="detail" hidden>%s</tr>' % _detail(step, cwd))
    kinds = ''.join('<option value="%s">%s</option>' % (k, esc(l)) for k, l in estimate.KIND_LINES
                    if k in {s['kind'] for s in steps})
    return ('<section><h2>Every step</h2><p class="sub">One row per model call in the main thread. Click a row for detail. '
            'Costs here are each step\'s own: its output, plus what its results cost to send. %s</p>'
            '<div class="controls"><label>Sort <select id="sort"><option value="order">in order</option>'
            '<option value="cost">by cost</option></select></label> <label>Show <select id="kind"><option value="all">all kinds</option>%s</select></label> '
            '<button id="showall" type="button">Show all %d steps</button> <span id="shown" class="sub"></span></div>'
            '<table id="steps"><thead><tr><th class="r">#</th><th>What happened</th><th>Output / new / carried</th>'
            '<th class="r">Total</th></tr></thead><tbody id="stepbody" data-limit="%d">%s</tbody></table>'
            '<div class="legendline">%s</div></section>' % (
                '%s %s' % (tag('exact'), tag('est')), kinds, len(steps), TOP_ROWS, ''.join(rows), _cost_legend()))


def _files(est):
    """The files table."""
    cwd, files = est['session']['cwd'], est['files']
    if not files:
        return '<section><h2>Files</h2><p class="sub">No file reads or edits were found.</p></section>'
    column = money_column([r[k] for r in files for k in ('new_usd', 'carried_usd')])
    rows = []
    for i, row in enumerate(files):
        repeat = '<span class="flag">read %d times</span>' % (row['reads'] + row['bash_reads']) if row['read_more_than_once'] else ''
        hidden = ' class="extra" hidden' if i >= TOP_FILES else ''
        rows.append('<tr%s><td><b>%s</b> %s<br><span class="sub">%s</span></td><td class="r">%d</td><td class="r">%d</td>'
                    '<td class="r">%d</td><td class="r">%s</td><td class="r">%s</td><td class="r">%s</td></tr>' % (
                        hidden, esc(os.path.basename(row['path'])), repeat, esc(display_path(row['path'], cwd)),
                        row['reads'], row['bash_reads'], row['writes'], count(row['tokens_in']),
                        column(row['new_usd']), column(row['carried_usd'])))
    more = ('<button id="morefiles" type="button">Show all %d files</button>' % len(files)) if len(files) > TOP_FILES else ''
    return ('<section><h2>Files</h2><p class="sub">Files the agent read or changed, most expensive first. Tokens and costs are %s. '
            '"Shell reads" are files read inside Bash commands (cat, head, sed and so on).</p>'
            '<table class="files" id="filetable"><thead><tr><th>File</th><th class="r">Read tool</th><th class="r">Shell reads</th>'
            '<th class="r">Written or edited</th><th class="r">Tokens brought in</th><th class="r">New cost</th>'
            '<th class="r">Carried cost</th></tr></thead><tbody>%s</tbody></table>%s</section>' % (tag('est'), ''.join(rows), more))


def _findings(est):
    """The session findings. They state what happened and give no advice."""
    found = est['findings']['session']
    body = ''.join('<li>%s</li>' % esc(f['sentence']) for f in found) or '<li>Nothing stood out in this session.</li>'
    return '<section><h2>Other findings</h2><ul class="findings">%s</ul></section>' % body


def rate(value):
    """A price per million tokens with at least two decimals: $2.00, $0.125."""
    return ('$%.2f' % value) if round(value, 2) == value else ('$%.3f' % value)


def _price_rows(est):
    """The price rows used, one per model in the session."""
    seen = []
    for step in est['steps']:
        key = prices.canonical_model(step['model'])
        if key and key not in seen:
            seen.append(key)
    rows = ''.join('<tr><td>%s</td><td class="r">%s</td><td class="r">%s</td><td class="r">%s</td><td class="r">%s</td>'
                   '<td class="r">%s</td><td>%s</td></tr>' % (
                       esc(prices.PRICES[k]['name']), rate(prices.PRICES[k]['input']), rate(prices.PRICES[k]['cache_write_5m']),
                       rate(prices.PRICES[k]['cache_write_1h']), rate(prices.PRICES[k]['cache_read']), rate(prices.PRICES[k]['output']),
                       'checked' if prices.PRICES[k]['validated'] else 'not yet checked against a session total')
                   for k in seen)
    return ('<table class="legend"><tr><th>Model</th><th class="r">Input</th><th class="r">Write 5 min</th><th class="r">Write 1 h</th>'
            '<th class="r">Re-sent</th><th class="r">Output</th><th>Against session totals</th></tr>%s</table>' % rows)


def _fine_print(est):
    """Collapsed by default: how to read the page, what is exact, prices, and known limits."""
    recorded, totals = est['recorded_total'], est['totals']
    if recorded and not any(recorded['gap_tokens'].values()):
        recorded_html = ('<p><b>Session total recorded by Claude Code.</b> It matches the transcript exactly: every token it '
                         'counted is in the transcript (%s). Claude Code\'s own dollar figure for the session is %s (it uses its own '
                         'price table).</p>' % (money(totals['transcript_usd']), money(recorded['cost_usd_reported'])))
    elif recorded:
        gap = _gap_share(recorded)
        recorded_html = (
            '<p><b>Session total recorded by Claude Code.</b> Its own record of this session\'s tokens, priced with the same table, '
            'comes to %s to %s (the range depends on whether cache writes were 5 minute or 1 hour; the log records only the '
            'combined count reliably). The transcript total is %s. The gap is %s to %s, or about %s of the recorded total. '
            'It is made of calls that produce no record in the transcript. Claude Code\'s own dollar figure for the session is '
            '%s (it uses its own price table).</p>' % (
                money(recorded['session_total_usd_low']), money(recorded['session_total_usd_high']),
                money(totals['transcript_usd']), money(recorded['gap_usd_low']), money(recorded['gap_usd_high']),
                percent(gap or 0), money(recorded['cost_usd_reported'])))
    else:
        recorded_html = ('<p><b>Session total recorded by Claude Code.</b> This log has none yet. A session that is still running '
                         'usually has not written one, so there is nothing to compare the transcript total with.</p>')
    unvalidated = ''
    if est['models_not_validated']:
        unvalidated = '<p><b>Prices not yet checked against a session total:</b> %s. %s</p>' % (
            esc(', '.join(est['models_not_validated'])), esc(prices.NOT_VALIDATED_NOTE.capitalize() + '.'))
    bash = est['bash']
    return ('<section><details><summary><h2 style="display:inline">Fine print</h2></summary>'
            '<h3>How to read this page</h3><p>The agent works in <b>steps</b>: one call to the model, the tool calls it made, and what '
            'came back. Every call sends the whole conversation so far. Material the model has just seen is <b>new</b>; material sent '
            'again on a later call is <b>re-sent</b> (<b>carried</b> cost). A step\'s cost is its own output plus what its results '
            'cost to send, now and on every later call.</p>'
            '<h3>What is exact and what is estimated</h3><ul>'
            '<li><b>Exact</b>: tokens of every model call, the total, thinking tokens, and each step\'s output cost.</li>'
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
            '<li>Only the main thread is drawn in "How the conversation grew".</li></ul></details></section>' % (
                estimate.CHARS_PER_TOKEN, est['sum_back']['difference_usd'], esc(prices.PRICES_URL), esc(prices.PRICES_CHECKED),
                _price_rows(est), recorded_html, unvalidated, count(est['skipped_pairs']), count(est['rebuilds']),
                count(estimate.REBUILD_MIN_EXTRA), percent(bash['other_command_share']), count(bash['calls']),
                count(len(est['unlinked_subagents']))))


# ---------------------------------------------------------------- the page

CSS = """
:root{--bg:#fbfaf7;--ink:#1c1f24;--muted:#5b616b;--line:#dcd8cf;--card:#fff}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:2.2rem;margin:0}h2{font-size:1.4rem;margin:44px 0 4px}h3{font-size:1.05rem;margin:22px 0 4px}
.sub{color:var(--muted);margin:2px 0 12px;font-size:.95rem}.lede{font-size:1.2rem;margin:10px 0 4px}
.note{color:var(--muted);margin:0 0 6px}.warn{background:#fff4d6;border:1px solid #e0c36a;border-radius:8px;padding:8px 12px;margin:8px 0}
.small{color:#6b7078;font-size:.82rem;margin:6px 0 0}
.tag{font-size:.64rem;letter-spacing:.05em;text-transform:uppercase;padding:0 6px;border-radius:99px;border:1px solid currentColor;
white-space:nowrap;vertical-align:middle;color:#3a3f47}.tag.est{border-style:dashed}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.num{font-size:2.5rem;font-weight:700;line-height:1.1}.lbl{color:var(--muted);font-size:.9rem;margin-top:4px}
.headline{font-size:1.25rem;font-weight:600;margin:16px 0 0;padding:10px 14px;border-left:5px solid #1b2a49;background:#fff}
.kindbar,.growth{width:100%;height:auto;display:block;background:var(--card);border:1px solid var(--line);border-radius:10px}
.kindbar{border-radius:8px}.legend{border-collapse:collapse;margin-top:10px;width:100%}.legend td,.legend th{padding:3px 8px;text-align:left;font-size:.93rem}
.kindlegend td:first-child{width:26px}.kindlegend td:nth-child(2){width:36%}.kindlegend td:nth-child(5){width:34%}
.kindlegend tr.totalrow td{border-top:2px solid #1c1f24;padding-top:7px;font-weight:700}
.match{color:#1d5c2e;font-weight:600}.nomatch{color:#b3261e;font-weight:700}
.r{text-align:right!important;font-variant-numeric:tabular-nums}
.sw,.chip,.mk{display:inline-block;vertical-align:-2px;margin-right:6px}.mk{vertical-align:-3px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.cardhead{display:flex;align-items:center;gap:6px;min-height:24px}.cardmoney{margin-top:2px}.cardcost{font-size:1.7rem;font-weight:700}
.what{font-size:1.05rem;margin:6px 0 8px}.split{font-size:.85rem;color:var(--muted);margin-top:8px}.why{margin:10px 0 0}
.costbar{width:100%;height:12px;display:block;min-width:60px;border-radius:6px}
.legendline{margin-top:10px;font-size:.88rem;color:var(--muted)}.key{margin-right:14px;white-space:nowrap}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:8px}
select,button{font:inherit;padding:4px 10px;border:1px solid #bdb8ad;border-radius:8px;background:#fff;cursor:pointer}
table{border-collapse:collapse;width:100%}#steps th,.files th{text-align:left;font-size:.85rem;color:var(--muted);border-bottom:2px solid var(--line);padding:6px 8px}
#steps td,.files td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
tr.step{cursor:pointer}tr.step:hover{background:#f3f1ea}tr.step:focus{outline:2px solid #0077BB}
.flag{display:inline-block;font-size:.72rem;border:1px solid #CC3311;color:#8a2208;border-radius:6px;padding:0 6px;margin-left:6px;white-space:nowrap}
.detailbox{background:#f7f5ef;border:1px solid var(--line);border-radius:10px;padding:10px 14px;font-size:.9rem}
.detailbox ul{margin:4px 0;padding-left:20px}.findings li{margin:6px 0}
details>summary{cursor:pointer;list-style:none}details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"\\25B8 ";font-size:1.2rem}details[open]>summary::before{content:"\\25BE "}
@media(max-width:800px){.tiles{grid-template-columns:repeat(2,1fr)}.cards{grid-template-columns:1fr}.num{font-size:2rem}}
@page{margin:14mm}
@media print{
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{background:#fff;font-size:12px}main{max-width:none;padding:0}
.controls,#morefiles,#showall{display:none!important}
.card,.tile,tr,.keep,.detailbox,.warn,.headline,svg,.legendline{break-inside:avoid;page-break-inside:avoid}
h2,h3,.sub{break-after:avoid;page-break-after:avoid}.keepsec{break-inside:avoid;page-break-inside:avoid}
thead{display:table-header-group}tr.step:hover{background:none}
.tiles{margin-top:10px;grid-template-columns:repeat(4,1fr)}.num{font-size:1.6rem}.cards{grid-template-columns:repeat(3,1fr)}
.card{padding:10px 12px}.cardcost{font-size:1.4rem}.what{font-size:.95rem}
}
"""

JS = """
(function(){
var body=document.getElementById('stepbody');
if(body){
 var rows=[].slice.call(body.querySelectorAll('tr.step')),limit=parseInt(body.getAttribute('data-limit'),10),showAll=rows.length<=limit;
 rows.forEach(function(r){r._d=r.nextElementSibling;});
 var sortSel=document.getElementById('sort'),kindSel=document.getElementById('kind'),btn=document.getElementById('showall'),shown=document.getElementById('shown');
 function num(r,k){return parseFloat(r.getAttribute(k));}
 function apply(){
  var byCost=sortSel.value==='cost';
  rows.sort(function(a,b){return byCost?(num(b,'data-cost')-num(a,'data-cost'))||(num(a,'data-order')-num(b,'data-order')):num(a,'data-order')-num(b,'data-order');});
  var n=0;
  rows.forEach(function(r){
   body.appendChild(r);body.appendChild(r._d);
   var ok=(kindSel.value==='all'||r.getAttribute('data-kind')===kindSel.value)&&(showAll||parseInt(r.getAttribute('data-rank'),10)<=limit);
   r.hidden=!ok;if(!ok){r._d.hidden=true;r.setAttribute('aria-expanded','false');}else{n++;}
  });
  shown.textContent=showAll?('Showing '+n+' of '+rows.length+' steps'):('Showing the '+limit+' most expensive of '+rows.length+' steps');
  btn.hidden=showAll;
 }
 function toggle(r){r._d.hidden=!r._d.hidden;r.setAttribute('aria-expanded',String(!r._d.hidden));}
 rows.forEach(function(r){r.addEventListener('click',function(){toggle(r);});r.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(r);}});});
 sortSel.addEventListener('change',apply);kindSel.addEventListener('change',apply);
 btn.addEventListener('click',function(){showAll=true;apply();});apply();
}
var more=document.getElementById('morefiles');
if(more){more.addEventListener('click',function(){[].slice.call(document.querySelectorAll('#filetable tr.extra')).forEach(function(r){r.hidden=false;});more.hidden=true;});}
})();
"""


def render(est):
    """The whole page as one string."""
    title = 'Receipt: %s, %s' % (est['session']['project'], when(est['session']['started']))
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>%s</title>'
            '<style>%s</style><noscript><style>tr.detail{display:table-row!important}</style></noscript></head><body><main>%s%s%s%s%s%s%s%s%s%s'
            '</main><script>%s</script></body></html>\n' % (
                esc(title), CSS, _top(est), _tiles(est), _headline(est), _where(est), _cards(est), _growth(est), _steps(est),
                _files(est), _findings(est), _fine_print(est), JS))


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
    except (FileNotFoundError, estimate.ReceiptError) as error:
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
