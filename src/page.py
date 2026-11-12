"""Shared parts for every page this project makes (the receipt now, the experiment board next).

The standard is docs/DESIGN.md. This module holds what every page shares: the colours (one colour per meaning,
set once, here), number formats, the exact and est. badges, hover explanations, collapsible sections, CSV buttons,
the print styles, and the functions that bring in Apache ECharts from vendor/.

A page is one HTML file that makes no network request. By default the chart library is read from vendor/ and
placed inside the page, so the file is self-contained (docs/demo-receipt.html, reports/). A receipt kept in
results/receipts/ is built in "linked" mode instead: it loads ../../vendor/echarts.min.js, which is the same
file read from disk, so a committed receipt is small. standalone() turns a linked page back into a self-contained
one for sharing outside the repo. Every string that came from a log must go through esc() before it reaches the page.
"""
import csv
import hashlib
import html
import io
import json
import re
from pathlib import Path

from . import fmt

REPO_ROOT = Path(__file__).resolve().parent.parent
ECHARTS_FILE = REPO_ROOT / 'vendor' / 'echarts.min.js'
VENDOR_README = REPO_ROOT / 'vendor' / 'README.md'
FONT_STACK = 'system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'

# ---------------------------------------------------------------- colours: one colour per meaning
# The 13 hues and 2 greys below were picked together so that every pair stays at least 15 apart (CIE Lab distance)
# for normal vision and for protan, deutan, and tritan colour blindness. Colour is never the only cue: every
# colour sits next to its name, and the exact and est. badges are words.

KIND_COLORS = {  # the twelve lines of "where the money went": one colour per kind of work
    'start': '#92C5DE', 'prompt': '#AA4499', 'thinking': '#882255', 'answer': '#FB9A99',
    'read_file': '#B2DF8A', 'search': '#CCBB44', 'run_command': '#000000', 'write_edit': '#8C510A',
    'web': '#543005', 'subagent': '#BF812D', 'other_tool': '#888888', 'harness': '#CCCCCC',
}
COST_COLORS = {  # how a call's input and output are paid for. Subagent is the same colour as the kind of work.
    'output': '#332288', 'new': '#E0705C', 'resent': '#33BBEE', 'subagent': KIND_COLORS['subagent'],
}
MARK_COLORS = {'rebuild': '#EE3377'}  # the marker for a cache rebuild (a triangle, never colour alone)
UI = {  # page chrome: text, lines, backgrounds, and state colours. None of these is a category.
    'bg': '#fbfaf7', 'ink': '#1c1f24', 'muted': '#565c66', 'line': '#dcd8cf', 'card': '#ffffff',
    'track': '#ECEAE4', 'ok': '#1d5c2e', 'bad': '#b3261e', 'warn_bg': '#fff4d6', 'warn_line': '#e0c36a',
    'focus': '#1a5fb4', 'flag': '#8a2208', 'chrome': '#bdb8ad', 'hover': '#f3f1ea', 'detail': '#f7f5ef',
}
INK = UI['ink']


def palette_values():
    """Every colour the pages may use, by meaning. The tests check that no two meanings share a value."""
    meanings = {'kind:' + k: v for k, v in KIND_COLORS.items()}
    meanings.update({'cost:' + k: v for k, v in COST_COLORS.items() if k != 'subagent'})
    meanings.update({'mark:' + k: v for k, v in MARK_COLORS.items()})
    return meanings


def contrast_ink(color):
    """Black-ish or white text, whichever reads better on this colour."""
    def lum(hex_color):
        parts = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a, b):
        hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
        return (hi + 0.05) / (lo + 0.05)
    return '#ffffff' if ratio(color, '#ffffff') >= ratio(color, INK) else INK


# ---------------------------------------------------------------- escaping and number formats

def esc(value):
    """HTML-escape any string that came from a log."""
    return html.escape(str(value), quote=True)


def money(value):
    """Dollars for the page (two decimals, "<$0.01" under a cent, "$0.00" only for a true zero), safe in HTML."""
    return esc(fmt.money(value))


def percent(share):
    """A share for the page ("<0.1%" under a tenth of a percent), safe to put in HTML."""
    return esc(fmt.percent(share))


def money_column(values):
    """A formatter that gives every row of one table column the same look, safe in HTML."""
    inner = fmt.money_column(values)
    return lambda value: esc(inner(value))


def tag(kind):
    """The word that goes with every number: exact, or est."""
    return '<span class="tag %s">%s</span>' % (kind, 'exact' if kind == 'exact' else 'est.')


def swatch(color, cls='sw', size=14):
    """A colour square drawn as inline SVG, so it survives printing and PDF export."""
    return ('<svg class="%s" width="%d" height="%d" viewBox="0 0 %d %d" aria-hidden="true">'
            '<rect x="0.5" y="0.5" width="%d" height="%d" rx="3" fill="%s" stroke="#00000040"/></svg>'
            % (cls, size, size, size, size, size - 1, size - 1, color))


def chip(color):
    """The small kind-colour square in front of a row."""
    return swatch(color, 'chip', 12)


# ---------------------------------------------------------------- words with a hover explanation

TERMS = {  # key: (the words on the page, the plain explanation)
    'api': ('API-equivalent', 'Tokens multiplied by the public prices that companies pay when they use the model through '
                              'the API. On a flat monthly plan nobody is billed this amount. It is a yardstick, not a bill.'),
    'resent': ('re-sent', 'Material the model already saw on an earlier call, sent again. Every call sends the whole '
                          'conversation so far. The provider charges a lower price for it, but it is paid for on every call.'),
    'new': ('new', 'Material sent for the first time on a call: what you typed, what a tool just returned, the model\'s '
                   'last reply. It is charged at the higher price for fresh input.'),
    'carried': ('carried cost', 'What it costs to re-send something on every later call. A big file read early is carried '
                                'through the rest of the session, so it is paid for many times.'),
    'rebuild': ('cache rebuild', 'The provider keeps a saved copy of the conversation for a few minutes. After a pause the '
                                 'copy expires, and the next call has to write the whole conversation again at a higher price.'),
    'start': ('starting context', 'Everything Claude Code sends before you type anything: its own instructions, the tool '
                                  'definitions, and any project instruction files. It is sent on every call.'),
    'exact': ('exact', 'Read straight from the session log, with no guessing.'),
    'est': ('est.', 'Estimated: worked out by a fixed rule from the exact numbers. The log does not record it directly.'),
    'step': ('step', 'One call to the model, the tool calls it made, and what came back.'),
    'call': ('model call', 'One request to the model. A single prompt from you can trigger dozens.'),
    'token': ('token', 'The unit models read and write, about three quarters of an English word. Usage is counted in tokens.'),
    'compaction': ('compaction', 'When a long conversation is summarized to free up room. The earlier material is replaced by '
                                 'the summary, so it stops being re-sent.'),
    'thinking': ('thinking', 'The model\'s own reasoning before it answers. It is billed as output.'),
    'subagent': ('subagent', 'A helper agent that Claude Code starts for a side task. It has its own conversation, and its '
                             'exact cost is added to the step that started it.'),
}


class Page:
    """One page being built. It owns the glossary, the chart specs, and the CSV blocks, so the shell can emit them once."""

    def __init__(self, library='inline'):
        if library not in ('inline', 'linked'):
            raise PageError('A page loads the chart library either "inline" or "linked", not "%s".' % library)
        self.library = library
        self.used_terms = set()
        self.charts = {}
        self.csv = {}
        self.data = {}

    def term(self, key, text=None):
        """The words for a term. The first time on the page they carry a hover or tap explanation; later they are plain."""
        words, explanation = TERMS[key]
        shown = esc(text if text is not None else words)
        if key in self.used_terms:
            return shown
        self.used_terms.add(key)
        return '<span class="term" tabindex="0" role="button" data-tip="%s">%s</span>' % (esc(explanation), shown)

    def tag(self, kind):
        """The exact or est. word. The first one on the page also explains itself on hover or tap."""
        key = 'exact' if kind == 'exact' else 'est'
        if key in self.used_terms:
            return tag(kind)
        self.used_terms.add(key)
        return ('<span class="tag %s term" tabindex="0" role="button" data-tip="%s">%s</span>'
                % (key, esc(TERMS[key][1]), 'exact' if key == 'exact' else 'est.'))

    def annotate(self, escaped_text, keys):
        """Give the first plain occurrence of each term's words in already-escaped text a hover explanation."""
        spans = []
        for key in keys:
            words = esc(TERMS[key][0])
            at = escaped_text.find(words)
            if key not in self.used_terms and at >= 0 and all(not (a < at + len(words) and at < b) for a, b, _ in spans):
                spans.append((at, at + len(words), key))
        out, last = [], 0
        for a, b, key in sorted(spans):
            out.append(escaped_text[last:a])
            out.append(self.term(key))
            last = b
        out.append(escaped_text[last:])
        return ''.join(out)

    def glossary(self):
        """The glossary of every term the page uses, for the evidence layer."""
        rows = ''.join('<dt>%s</dt><dd>%s</dd>' % (esc(words), esc(explanation)) for words, explanation in TERMS.values())
        return '<dl class="glossary">%s</dl>' % rows

    def chart(self, chart_id, option, height, summary, label):
        """A chart box: a statement title lives inside the option; the text summary under it always shows."""
        self.charts[chart_id] = option
        return ('<div class="chartbox keep"><div class="chart" id="%s" style="height:%dpx" role="img" aria-label="%s"></div>'
                '<p class="chartsum">%s</p></div>' % (esc(chart_id), height, esc(label), summary))

    def csv_button(self, csv_id, filename, header, rows, label='Download CSV'):
        """A button that downloads a table as CSV. The CSV text sits in the page and is built on click, with no network."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator='\r\n')
        writer.writerow(header)
        writer.writerows(rows)
        self.csv[csv_id] = buffer.getvalue()
        return '<button type="button" class="csvbtn" data-csv="csv-%s" data-name="%s">%s</button>' % (
            esc(csv_id), esc(filename), esc(label))

    def csv_blocks(self):
        """The CSV texts as inert script blocks (JSON strings, so nothing in them can end the block)."""
        return ''.join('<script type="application/json" id="csv-%s">%s</script>' % (esc(k), json_for_html(v))
                       for k, v in self.csv.items())

    def shell(self, title, body, page_js=''):
        """The whole document: head, styles, body, then the library, the data, and the scripts."""
        data = dict(self.data, charts=self.charts)
        return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"><title>%s</title>'
                '<style>%s</style><noscript><style>%s</style></noscript></head><body><main>%s</main>'
                '<div id="tip" role="tooltip" hidden></div>%s<script type="application/json" id="page-data">%s</script>'
                '<script>%s</script></body></html>\n' % (
                    esc(title), CSS, NOSCRIPT_CSS, body, (inline_echarts() if self.library == 'inline' else linked_echarts()) + self.csv_blocks(),
                    json_for_html(data),
                    SHARED_JS + page_js))


# ---------------------------------------------------------------- sections

def section(sec_id, question, answer, body, cls='layer'):
    """A section: a plain question as the heading, one sentence that answers it, then the content."""
    return ('<section class="%s" id="%s" aria-labelledby="%s-h"><h2 id="%s-h">%s</h2><p class="answer">%s</p>%s</section>'
            % (cls, esc(sec_id), esc(sec_id), esc(sec_id), esc(question), answer, body))


def collapsible(sec_id, question, answer, body):
    """A layer 3 section: heading and answer sentence always show, the content is collapsed until opened."""
    return ('<section class="sec collapsed" id="%s"><h2><button type="button" class="sechead" aria-expanded="false" '
            'aria-controls="%s-body"><span class="chev" aria-hidden="true"></span>%s</button></h2><p class="answer">%s</p>'
            '<div class="secbody" id="%s-body">%s</div></section>' % (
                esc(sec_id), esc(sec_id), esc(question), answer, esc(sec_id), body))


# ---------------------------------------------------------------- the chart library

def vendored_sha256():
    """The SHA-256 that vendor/README.md records for echarts.min.js."""
    found = re.search(r'SHA-256 of echarts\.min\.js \| `([0-9a-f]{64})`', VENDOR_README.read_text(encoding='utf-8'))
    if not found:
        raise PageError('vendor/README.md does not record a SHA-256 for echarts.min.js')
    return found.group(1)


class PageError(Exception):
    """A page cannot be built (for example, the chart library does not match its recorded checksum)."""


def _checked_library():
    """The text of vendor/echarts.min.js, after checking it against the checksum in vendor/README.md."""
    raw = ECHARTS_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != vendored_sha256():
        raise PageError('vendor/echarts.min.js does not match the SHA-256 in vendor/README.md')
    return raw.decode('utf-8')


def inline_echarts():
    """The chart library as one inline script block. It is checked against the checksum in vendor/README.md."""
    text = _checked_library()
    if '</script' in text.lower():
        raise PageError('vendor/echarts.min.js contains a script end tag, so it cannot be inlined as it is')
    return '<script>%s</script>' % text


# A receipt in results/receipts/ sits two folders below the repo root, so the library is at ../../vendor/.
LINKED_ECHARTS_PATH = '../../vendor/echarts.min.js'
NO_CHARTS_NOTE = ('The charts did not load. This page reads them from the vendor folder of the project, so open it from '
                  'inside the project, or make a standalone copy with the export option.')
LINKED_BLOCK = ('<script src="%s"></script><script>window.echarts||Array.prototype.forEach.call('
                'document.querySelectorAll(".chart"),function(e){e.textContent="%s";});</script>'
                % (LINKED_ECHARTS_PATH, NO_CHARTS_NOTE))


def linked_echarts():
    """The script tags of a linked page. The vendored file is checked now, so a page is only built against the pinned
    library. If the file is missing when the page is opened, each chart says so in words."""
    _checked_library()
    return LINKED_BLOCK


def standalone(page_text):
    """A linked page as a self-contained one: the link is replaced by the checked library. A page that is already
    self-contained comes back unchanged."""
    return page_text.replace(LINKED_BLOCK, inline_echarts(), 1)


def json_for_html(value):
    """JSON that is safe inside a script block: no raw angle brackets, ampersands, or line separators."""
    text = json.dumps(value, separators=(',', ':'))
    return (text.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


# ---------------------------------------------------------------- styles

CSS = """
:root{%s}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 %s;font-weight:400}
main{max-width:1232px;margin:0 auto;padding:16px 24px 80px}
b,strong,th,h1,h2,h3,.num,.headline{font-weight:700}
h1{font-size:1.875rem;line-height:1.2;margin:0}h2{font-size:1.375rem;line-height:1.3;margin:40px 0 4px}#where>h2{margin-top:20px}h3{font-size:1.0625rem;margin:24px 0 4px}
.meta{color:var(--muted);margin:4px 0 0}.note{color:var(--muted);margin:4px 0 0;font-size:.9375rem}
.answer{margin:0 0 8px;font-size:1.0625rem}.sub{color:var(--muted);margin:2px 0 12px;font-size:.9375rem}
.warn{background:var(--warn_bg);border:1px solid var(--warn_line);border-radius:8px;padding:8px 16px;margin:8px 0}
.small{color:var(--muted);font-size:.8125rem;margin:8px 0 0}
.tag{font-size:.6875rem;letter-spacing:.05em;text-transform:uppercase;padding:0 8px;border-radius:99px;border:1px solid currentColor;
white-space:nowrap;vertical-align:middle;color:var(--ink);font-weight:400}.tag.est{border-style:dashed}
.term{border-bottom:1px dotted currentColor;cursor:help}.term:focus{outline:2px solid var(--focus);outline-offset:2px}
#tip{position:fixed;z-index:20;max-width:320px;background:var(--ink);color:#fff;padding:8px 16px;border-radius:8px;font-size:.875rem;
line-height:1.4;pointer-events:none;box-shadow:0 4px 16px #0003}#tip[hidden]{display:none}
.headline{font-size:1.5rem;line-height:1.3;margin:12px 0 0;padding:8px 24px;border-left:8px solid var(--ink);background:var(--card)}
.tiles{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));gap:16px;margin-top:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px 16px}
.num{font-size:2.25rem;line-height:1.15;white-space:nowrap}.lbl{color:var(--muted);font-size:.8125rem;margin-top:2px}
.lbl .t{white-space:nowrap}.lbl .tag{margin-left:8px;display:inline-block}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:4px 16px 4px}
.chart{width:100%%}.chart svg{max-width:100%%}
.chartsum{margin:0;padding:0 8px 8px;color:var(--muted);font-size:.875rem}
table{border-collapse:collapse;width:100%%}
.legend{margin-top:8px}.legend td,.legend th{padding:2px 8px;text-align:left;font-size:.875rem}
.legendcols{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:0 40px;align-items:start}
.kindlegend{margin-top:0}.kindlegend td:first-child{width:28px}.kindlegend td:nth-child(3){width:88px}.kindlegend td:nth-child(4){width:64px}.kindlegend td:nth-child(5){width:72px}
.totaltable{margin-top:8px;border-top:2px solid var(--ink)}.totaltable td{padding-top:8px;font-weight:700}.totaltable td:nth-child(2){width:88px}.totaltable td:nth-child(3){width:64px}
.match{color:var(--ok);font-weight:700}.nomatch{color:var(--bad);font-weight:700}
.r{text-align:right!important;font-variant-numeric:tabular-nums}
.sw,.chip,.mk{display:inline-block;vertical-align:-2px;margin-right:8px}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}
.cardhead{display:flex;align-items:center;gap:8px;min-height:24px}.cardcost{font-size:1.75rem;font-weight:700}
.what{font-size:1.0625rem;margin:8px 0}.split{font-size:.875rem;color:var(--muted);margin-top:8px}.why{margin:8px 0 0}
.costbar{width:100%%;height:12px;display:block;min-width:64px;border-radius:6px}
.legendline{margin-top:16px;font-size:.875rem;color:var(--muted)}.key{margin-right:16px;white-space:nowrap}
.controls{display:flex;flex-wrap:wrap;gap:16px;align-items:center;margin-bottom:8px}
select,button,input[type=search]{font:inherit;font-size:.9375rem;padding:4px 12px;border:1px solid var(--chrome);border-radius:8px;background:var(--card);color:var(--ink)}
button{cursor:pointer}button:focus,select:focus,input:focus{outline:2px solid var(--focus);outline-offset:1px}
input[type=search]{min-width:200px}
#steps th,.files th{text-align:left;font-size:.875rem;color:var(--muted);border-bottom:2px solid var(--line);padding:8px}
#steps td,.files td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
tr.step{cursor:pointer}tr.step:hover{background:var(--hover)}tr.step:focus{outline:2px solid var(--focus)}
.flag{display:inline-block;font-size:.75rem;border:1px solid var(--flag);color:var(--flag);border-radius:8px;padding:0 8px;margin-left:8px;white-space:nowrap}
.detailbox{background:var(--detail);border:1px solid var(--line);border-radius:8px;padding:8px 16px;font-size:.875rem}
.detailbox ul{margin:4px 0;padding-left:24px}.findings li{margin:8px 0}
.sec{margin-top:32px}.sec>h2{margin:0 0 4px}
.sechead{font:inherit;font-size:1.375rem;font-weight:700;background:none;border:0;padding:0;color:var(--ink);text-align:left;
display:inline-flex;align-items:center;gap:8px}.sechead:focus{outline:2px solid var(--focus);outline-offset:4px}
.chev::before{content:"\\25BE"}.sec.collapsed .chev::before{content:"\\25B8"}
.sec.collapsed .secbody{display:none}.secbody{margin-top:8px}
.csvbtn{margin:0 0 0 8px;padding:0 12px}.glossary dt{font-weight:700;margin-top:8px}.glossary dd{margin:0 0 0 0;color:var(--muted)}
@media(max-width:900px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.cards{grid-template-columns:1fr}.num{font-size:1.75rem}
.lbl .t{white-space:normal}.headline{font-size:1.25rem}}
@page{size:A4;margin:12mm}
@media print{
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{background:#fff;font-size:11px}main{max-width:none;padding:0}
.controls,.csvbtn,#tip{display:none!important}
.sec.collapsed .secbody{display:block!important}.chev{display:none}
.term{border-bottom:0}
.card,.tile,tr,.keep,.detailbox,.warn,.headline,svg,.legendline,.chartbox{break-inside:avoid;page-break-inside:avoid}
h2,h3,.sub,.answer{break-after:avoid;page-break-after:avoid}.sec{break-inside:auto}.layer{break-inside:avoid;page-break-inside:avoid}
.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.tiles{grid-template-columns:repeat(var(--n,4),minmax(0,1fr))}.lbl .t{white-space:nowrap}
thead{display:table-header-group}tr.step:hover{background:none}
.tiles{margin-top:8px}.num{font-size:1.5rem}.card{padding:8px 16px}.cardcost{font-size:1.375rem}.what{font-size:.9375rem}
.headline{font-size:1.125rem}h2{margin-top:24px}
}
""" % (';'.join('--%s:%s' % (k, v) for k, v in UI.items()), FONT_STACK)

NOSCRIPT_CSS = '.sec.collapsed .secbody,tr.detail{display:block!important}tr.detail{display:table-row!important}.controls,.csvbtn{display:none}'


# ---------------------------------------------------------------- scripts shared by every page

SHARED_JS = r"""
(function(){
'use strict';
function $(s,r){return (r||document).querySelector(s);}
function $$(s,r){return [].slice.call((r||document).querySelectorAll(s));}
var tip=document.getElementById('tip');
function placeTip(el){
 tip.textContent=el.getAttribute('data-tip');tip.hidden=false;
 var r=el.getBoundingClientRect(),w=tip.offsetWidth,h=tip.offsetHeight;
 var x=Math.max(8,Math.min(r.left,window.innerWidth-w-8)),y=r.bottom+8;
 if(y+h>window.innerHeight-8)y=Math.max(8,r.top-h-8);
 tip.style.left=x+'px';tip.style.top=y+'px';
}
function hideTip(){tip.hidden=true;}
$$('.term').forEach(function(el){
 el.addEventListener('mouseenter',function(){placeTip(el);});
 el.addEventListener('mouseleave',hideTip);
 el.addEventListener('focus',function(){placeTip(el);});
 el.addEventListener('blur',hideTip);
 el.addEventListener('click',function(e){e.stopPropagation();if(tip.hidden||tip._for!==el){placeTip(el);tip._for=el;}else{hideTip();tip._for=null;}});
 el.addEventListener('keydown',function(e){if(e.key==='Escape')hideTip();});
});
document.addEventListener('click',function(){hideTip();});
$$('.sechead').forEach(function(b){
 b.addEventListener('click',function(){
  var s=b.closest('.sec'),closed=s.classList.toggle('collapsed');
  b.setAttribute('aria-expanded',String(!closed));
  if(!closed)resizeCharts();
 });
});
$$('[data-csv]').forEach(function(b){
 b.addEventListener('click',function(){
  var text=JSON.parse(document.getElementById(b.getAttribute('data-csv')).textContent);
  var blob=new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=b.getAttribute('data-name');
  document.body.appendChild(a);a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},0);
 });
});
/* charts: the page data holds one option per chart; strings that start with fn: are replaced by a function */
var DATA=JSON.parse(document.getElementById('page-data').textContent);
var FN={};
window.PAGE={data:DATA,fn:FN};
function revive(o){
 if(Array.isArray(o))return o.map(revive);
 if(o&&typeof o==='object'){var r={};for(var k in o)r[k]=revive(o[k]);return r;}
 if(typeof o==='string'&&o.indexOf('fn:')===0){var f=FN[o.slice(3)];return typeof f==='function'?f:undefined;}
 return o;
}
FN.int=function(n){return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');};
FN.short=function(n){return n>=1e6?(n/1e6).toFixed(1).replace(/\.0$/,'')+'M':n>=1e3?(n/1e3).toFixed(1).replace(/\.0$/,'')+'k':String(Math.round(n));};
FN.money=function(v){return v===0?'$0.00':v<0.01?'<$0.01':'$'+v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',');};
FN.tok=function(v){return FN.short(v);};
FN.usd2=function(v){return '$'+v.toFixed(2);};
FN.usd3=function(v){return '$'+v.toFixed(3);};
FN.usd4=function(v){return '$'+v.toFixed(4);};
FN.tip=function(p){var q=Array.isArray(p)?p[0]:p;return q&&q.data&&q.data.tip?q.data.tip:'';};
var charts=[];
function resizeCharts(){charts.forEach(function(c){c.resize();});}
window.PAGE.start=function(){
 if(!window.echarts)return;
 $$('.chart').forEach(function(el){
  var spec=DATA.charts[el.id];if(!spec)return;
  var option=revive(spec);option.animation=false;
  var c=echarts.init(el,null,{renderer:'svg'});c.setOption(option);charts.push(c);
 });
};
var resizeTimer=null;
window.addEventListener('resize',function(){clearTimeout(resizeTimer);resizeTimer=setTimeout(resizeCharts,100);});
/* printing: charts are SVG, so they print sharp; they are resized to the paper width first */
function printSize(){charts.forEach(function(c){c.resize({width:680});});}
window.addEventListener('beforeprint',printSize);
window.addEventListener('afterprint',resizeCharts);
if(window.matchMedia){var mq=window.matchMedia('print');var onPrint=function(e){if(e.matches)printSize();else resizeCharts();};
 if(mq.addEventListener)mq.addEventListener('change',onPrint);else if(mq.addListener)mq.addListener(onPrint);}
})();
"""
