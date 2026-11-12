"""Tests for the page's number formats, print rules, headline, chart, and total row."""
import contextlib
import html
import io
import json
import re
import tempfile
import unittest

from src import audit, diagnose, estimate, fmt, receipt
from tests.helpers import SESSION_1, SESSION_2, SESSION_3
from tests.make_demo_session import write_demo_session

DOLLARS = re.compile(r'\$[\d,]+\.\d+')


class FormatTest(unittest.TestCase):
    def test_money_has_two_decimals_and_under_a_cent_is_marked(self):
        self.assertEqual([fmt.money(v) for v in (0, 0.004, 0.0099, 0.01, 0.1155, 0.12, 1234.5)],
                         ['$0.00', '<$0.01', '<$0.01', '$0.01', '$0.12', '$0.12', '$1,234.50'])
        self.assertEqual(fmt.money(None), 'no public price')

    def test_a_share_under_a_tenth_of_a_percent_is_marked(self):
        self.assertEqual([fmt.percent(s) for s in (0, 0.0004, 0.00099, 0.001, 0.045, 0.37, 1.0)],
                         ['0%', '<0.1%', '<0.1%', '0.1%', '4.5%', '37%', '100%'])

    def test_a_column_uses_one_number_of_decimals(self):
        mixed = fmt.money_column([0.0063, 0.1155, 0.01, 0])
        self.assertEqual([mixed(v) for v in (0.0063, 0.1155, 0.01)], ['$0.0063', '$0.1155', '$0.0100'])
        self.assertEqual(len({len(mixed(v).split('.')[1]) for v in (0.0063, 0.1155, 0.01)}), 1)
        cents = fmt.money_column([0.02, 0.1155, 3.0])
        self.assertEqual([cents(v) for v in (0.02, 0.1155, 3.0)], ['$0.02', '$0.12', '$3.00'])

    def test_zero_is_written_only_for_a_true_zero_everywhere(self):
        small = fmt.money_column([0.0000237, 0.0009, 0.12, 0])
        self.assertEqual(small(0), '$0.00')
        self.assertEqual(small(0.0000237), '<$0.0001')  # a real amount is never shown as zero
        self.assertEqual(small(0.0009), '$0.0009')
        two = fmt.money_column([0.5, 0])
        self.assertEqual((two(0), two(0.5)), ('$0.00', '$0.50'))
        self.assertEqual((fmt.money(0), fmt.money(0.0000237), fmt.money(0.004)), ('$0.00', '<$0.01', '<$0.01'))
        for value in (0.0000001, 0.0001, 0.004, 0.0099):
            for formatted in (fmt.money(value), small(value)):
                self.assertNotIn(formatted, ('$0.00', '$0.0000'), value)

    def test_axis_labels(self):
        self.assertEqual([fmt.short_tokens(v) for v in (950, 25000, 100000, 1200000)], ['950', '25k', '100k', '1.2M'])


class PageCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pages = {}
        for name, path in (('demo', write_demo_session(cls.tmp.name)), ('s1', SESSION_1), ('s2', SESSION_2), ('s3', SESSION_3)):
            est = receipt.build(path)
            cls.pages[name] = (est, receipt.render(est))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def section(text, title):
        start = text.index('>%s</h2>' % title)
        return text[start:text.index('</section>', start)]

    @staticmethod
    def main_part(text):
        """The page's own markup: everything before the library and the data blocks."""
        return text[:text.index('<div id="tip"')]


class NumberFormatOnThePageTest(PageCase):
    def test_tiles_legend_and_cards_use_two_decimals_only(self):
        for name, (est, text) in self.pages.items():
            tiles = text[text.index('class="tiles"'):text.index('</section>', text.index('class="tiles"'))]
            for part in (tiles, self.section(text, 'Where did the money go?'), self.section(text, 'What made it expensive?')):
                for amount in DOLLARS.findall(part):
                    self.assertEqual(len(amount.split('.')[1]), 2, (name, amount))

    def test_amounts_under_a_cent_read_less_than_one_cent(self):
        est, text = self.pages['demo']
        legend = self.section(text, 'Where did the money go?')
        self.assertIn('&lt;$0.01', legend)  # escaped, so it is valid HTML
        self.assertIn('&lt;0.1%', legend)  # "Your prompts" are under 0.1 percent of the demo
        self.assertNotIn('<$', self.main_part(text))
        self.assertNotIn('><0.1%', self.main_part(text))
        self.assertNotRegex(legend, r'\$0\.00\d')

    def test_every_row_of_a_table_column_has_the_same_decimals(self):
        for name, (est, text) in self.pages.items():
            steps = text[text.index('<tbody id="stepbody"'):text.index('</tbody>')]
            totals = re.findall(r'<td class="r">(\$[\d,]+\.\d+|no public price)</td></tr>', steps)
            self.assertLessEqual(len({len(t.split('.')[1]) for t in totals if t.startswith('$') and t != '$0.00'}), 1, name)
        est, text = self.pages['demo']
        steps = text[text.index('<tbody id="stepbody"'):text.index('</tbody>')]
        decimals = [len(d) for d in re.findall(r'<td class="r">\$[\d,]+\.(\d+)</td></tr>', steps)]
        self.assertEqual(len(decimals), 36)
        self.assertEqual(set(decimals), {4})  # the demo's steps are mostly under a dime, so the column uses four
        files = text[text.index('id="filetable"'):text.index('</tbody>', text.index('id="filetable"'))]
        cells = re.findall(r'<td class="r">(\$[\d,]+\.\d+|<\$0\.0001)</td>', files)
        decimals = {len(c.split('.')[1]) for c in cells if c.startswith('$') and c != '$0.00'}  # a true zero is always $0.00
        self.assertEqual(len(decimals), 1)

    def test_numbers_in_a_money_column_are_right_aligned(self):
        text = self.pages['demo'][1]
        self.assertIn('.r{text-align:right!important;font-variant-numeric:tabular-nums}', text)
        self.assertRegex(text, r'<th class="r">Total</th>')

    def test_sentences_use_the_same_money_format(self):
        est = self.pages['demo'][0]
        for card in est['findings']['top_steps']:
            for amount in DOLLARS.findall(card['sentence']):
                self.assertEqual(len(amount.split('.')[1]), 2)


class PrintTest(PageCase):
    def test_print_styles_keep_colour_and_avoid_splitting(self):
        css = receipt.CSS
        self.assertIn('print-color-adjust:exact', css)
        self.assertIn('-webkit-print-color-adjust:exact', css)
        printed = css[css.index('@media print'):]
        rule = re.search(r'([^{}]*)\{break-inside:avoid;page-break-inside:avoid\}', printed).group(1)
        for selector in ('.card', '.tile', 'tr', '.keep', '.detailbox'):
            self.assertIn(selector, [s.strip() for s in rule.split(',')])  # no card, tile, table row, or kept block splits across pages
        self.assertIn('thead{display:table-header-group}', printed)  # table headings repeat on each page

    def test_colour_squares_and_row_bars_are_svg_not_backgrounds(self):
        for name, (est, text) in self.pages.items():
            self.assertNotIn('style="background', text, name)
            self.assertNotIn('class="fill"', text, name)
        text = self.pages['demo'][1]
        self.assertGreaterEqual(text.count('<svg class="sw"'), 14)
        self.assertGreaterEqual(text.count('<svg class="chip"'), 36)
        self.assertGreaterEqual(text.count('<svg class="costbar"'), 36 + 3)
        self.assertEqual(text.count('<svg class="mk"'), 0)  # the growth chart is ECharts now; its legend is drawn by the chart

    def test_the_legend_and_its_total_row_stay_together(self):
        text = self.pages['demo'][1]
        keep = text[text.index('<div class="keep" id="kindtable">'):]
        keep = keep[:keep.index('</section>')]
        self.assertIn('class="totalrow"', keep)
        self.assertIn('Each line is rounded', keep)
        self.assertIn('Matches the total at the top', keep)


class HeadlineTest(PageCase):
    @staticmethod
    def headline_text(text):
        """The headline sentence as plain text (tags removed, entities decoded)."""
        found = re.search(r'<p class="headline">(.*?)</p>', text, re.S).group(1)
        return html.unescape(re.sub(r'<[^>]+>', '', found)).strip()

    def test_one_headline_sentence_sits_above_the_tiles(self):
        est, text = self.pages['demo']
        found = est['findings']['headline']
        self.assertEqual(found['id'], 'repeated_step')
        self.assertEqual(found['sentence'], 'The largest single cause: Read inventory.py 3 times, $0.32 in all, 37% of the total (est.).')
        self.assertEqual(self.headline_text(text), found['sentence'])
        self.assertLess(text.index('<h1>'), text.index('class="headline"'))
        self.assertLess(text.index('class="headline"'), text.index('class="tiles"'))
        self.assertLess(text.index('class="tiles"'), text.index('Where did the money go?'))
        self.assertEqual(text.count('class="headline"'), 1)

    def test_the_headline_picks_the_largest_cause_among_the_findings(self):
        est = {'totals': {'transcript_usd': 10.0}}
        cards = [{'times': 1, 'number': 4, 'description': 'Ran make', 'total_usd': 1.0}]
        start = {'id': 'starting_context_share', 'numbers': {'usd': 3.0}}
        rebuild = {'id': 'cache_rebuilds', 'numbers': {'usd': 0, 'extra_usd': 2.0, 'count': 2}}
        self.assertEqual(diagnose._headline(est, cards, [start, rebuild])['id'], 'starting_context')
        self.assertEqual(diagnose._headline(est, cards, [rebuild])['id'], 'cache_rebuilds')
        self.assertEqual(diagnose._headline(est, cards, [])['id'], 'top_step')
        self.assertIsNone(diagnose._headline({'totals': {'transcript_usd': 0}}, cards, []))

    def test_when_the_starting_context_is_over_half_the_headline_says_it_is_fixed_overhead(self):
        est = {'totals': {'transcript_usd': 10.0}}
        cards = [{'times': 1, 'number': 4, 'description': 'Ran make', 'total_usd': 1.0}]
        half = {'id': 'starting_context_share', 'numbers': {'usd': 5.0}}
        over = {'id': 'starting_context_share', 'numbers': {'usd': 6.5}}
        self.assertNotEqual(diagnose._headline(est, cards, [half])['id'], 'fixed_overhead')  # exactly half is not over half
        found = diagnose._headline(est, cards, [over])
        self.assertEqual(found['id'], 'fixed_overhead')
        self.assertEqual(found['sentence'], "Most of this cost was fixed overhead: Claude Code's starting context, sent before any "
                                            "work. The task itself cost $3.50.")
        self.assertAlmostEqual(found['numbers']['task_usd'], 3.5)

    def test_a_fifth_tile_shows_the_cost_of_the_task_itself_only_in_that_case(self):
        est, text = self.pages['s3']  # the starting context is 53 percent of this fixture
        found = est['findings']['headline']
        self.assertEqual(found['id'], 'fixed_overhead')
        self.assertTrue(self.headline_text(text).startswith("Most of this cost was fixed overhead: Claude Code's starting context"))
        self.assertIn('Cost of the task itself', text)
        self.assertIn('class="tiles" style="--n:5"', text)
        start = [r for r in est['kinds'] if r['key'] == 'start'][0]['usd']
        self.assertAlmostEqual(found['numbers']['task_usd'], est['totals']['transcript_usd'] - start)
        self.assertEqual(receipt.task_cost(est), found['numbers']['task_usd'])
        demo = self.pages['demo']
        self.assertNotIn('Cost of the task itself', demo[1])
        self.assertIn('class="tiles" style="--n:4"', demo[1])
        self.assertIsNone(receipt.task_cost(demo[0]))

    def test_every_tile_label_stays_on_one_line(self):
        for name, (est, text) in self.pages.items():
            tiles = text[text.index('class="tiles"'):text.index('</section>', text.index('class="tiles"'))]
            labels = re.findall(r'<span class="t">(.*?)</span>(?=<span class="tag|<span class="tag)', tiles)
            self.assertGreaterEqual(len(re.findall(r'class="lbl"', tiles)), 4, name)
        self.assertIn('.lbl .t{white-space:nowrap}', receipt.CSS)

    def test_every_fixture_page_builds_with_or_without_a_headline(self):
        for name in ('s1', 's2', 's3'):
            self.assertIn('Where did the money go?', self.pages[name][1])


class GrowthChartTest(PageCase):
    @staticmethod
    def data(text):
        raw = re.search(r'<script type="application/json" id="page-data">(.*?)</script>', text, re.S).group(1)
        return json.loads(raw)

    def test_the_growth_chart_has_a_statement_title_axis_labels_one_bar_per_call_and_markers(self):
        est, text = self.pages['demo']
        option = self.data(text)['charts']['chart-growth']
        self.assertEqual(option['title']['text'], 'Prompt size grew 5x over the session')
        self.assertEqual(option['xAxis']['name'], 'Model call, in order')
        self.assertEqual(option['yAxis']['name'], 'Tokens in the prompt')
        names = [s['name'] for s in option['series']]
        self.assertEqual(names, ['Re-sent', 'New', 'Cache rebuilt'])
        self.assertEqual(len(option['series'][0]['data']), 36)
        self.assertEqual(len(option['series'][2]['data']), 1)  # one rebuild in the demo
        self.assertEqual(option['dataZoom'], [])  # a short session needs no zoom
        self.assertEqual([c['prompt_tokens'] for c in est['calls']],
                         [a + b for a, b in zip(option['series'][0]['data'], option['series'][1]['data'])])

    def test_the_tooltip_data_holds_exact_tokens_by_type_for_every_call(self):
        est, text = self.pages['demo']
        growth = self.data(text)['growth']
        self.assertEqual(len(growth['calls']), 36)
        first = est['calls'][0]['tokens']
        self.assertEqual(growth['calls'][0][:5], [first['input'], first['cache_read'], first['cache_write_5m'],
                                                  first['cache_write_1h'], first['output']])
        self.assertEqual(len(growth['rebuilds']), 1)
        self.assertAlmostEqual(list(growth['rebuilds'].values())[0][0], 25, delta=1)
        self.assertEqual(list(growth['rebuilds'].values())[0][1], 'previous_message_not_found')
        self.assertIn('Cache rebuilt after 25 minutes (previous_message_not_found)', text)  # and the reason in the step detail

    def test_the_chart_has_a_text_summary_with_its_numbers_so_the_page_reads_without_it(self):
        est, text = self.pages['demo']
        summary = re.search(r'id="chart-growth".*?<p class="chartsum">(.*?)</p>', text, re.S).group(1)
        self.assertIn('21,044 tokens on the first call and 98,140 on the last', summary)
        self.assertIn('the largest was 98,140 tokens', summary)
        self.assertIn('The saved copy expired 1 time', summary)

    def test_a_long_session_gets_zoom_and_a_compaction_marker_when_the_log_has_one(self):
        self.assertEqual(receipt._zoom(40), ([], 0))
        controls, room = receipt._zoom(41)
        self.assertEqual([c['type'] for c in controls], ['inside', 'slider'])
        self.assertGreater(room, 0)
        est = self.pages['s1'][0]  # an invented session with a compaction
        option = receipt.growth_option(est)
        if len(est['segments']) > 1:
            self.assertIn('Compacted', [s['name'] for s in option['series']])

    def test_statements_say_what_happened(self):
        calls = lambda *sizes: [{'prompt_tokens': s} for s in sizes]
        self.assertEqual(receipt._growth_statement(calls(1000, 5000)), 'Prompt size grew 5x over the session')
        self.assertEqual(receipt._growth_statement(calls(1000, 1300)), 'Prompt size grew 30% over the session')
        self.assertEqual(receipt._growth_statement(calls(1000, 1010)), 'Prompt size stayed about the same over the session')
        self.assertIn('one call', receipt._growth_statement(calls(1234)))
        self.assertEqual(receipt._running_statement([0.1, 0.2, 0.6, 1.0]), 'Half of the cost was spent by call 3 of 4')


class RunningTotalChartTest(PageCase):
    def test_the_line_ends_at_the_total_and_marks_the_top_steps(self):
        est, text = self.pages['demo']
        option = GrowthChartTest.data(text)['charts']['chart-running']
        line = option['series'][0]
        self.assertEqual(len(line['data']), 36)
        self.assertAlmostEqual(line['data'][-1], est['totals']['transcript_usd'], places=6)
        self.assertEqual(line['data'], sorted(line['data']))  # a running total never goes down
        ranks = sorted(p['value'] for p in line['markPoint']['data'])
        expected = sorted(rank for rank, card in enumerate(est['findings']['top_steps'], 1) for _ in card['steps'])
        self.assertEqual(ranks, expected)
        self.assertEqual(option['yAxis']['name'], 'Dollars so far, API-equivalent')
        self.assertTrue(option['title']['text'].startswith('Half of the cost was spent by call'))


class TotalRowTest(PageCase):
    ROW = re.compile(r'<tr class="totalrow"><td>([^<]*)</td><td class="r">([^<]*)</td><td class="r">([^<]*)</td>'
                     r'<td class="check">(.*?)</td></tr>')

    def test_the_total_row_equals_the_headline_total_on_every_fixture_and_the_demo(self):
        for name, (est, text) in self.pages.items():
            label, total, share, check = self.ROW.search(text).groups()
            self.assertEqual(label, 'Total of the lines above')
            self.assertEqual(share, '100%')
            self.assertIn('Matches the total at the top', check)
            self.assertNotIn('Does not match', text)
            headline = re.search(r'<div class="num">([^<]*)</div>', text).group(1)  # the first tile is the total
            self.assertEqual(total, headline, name)
            self.assertEqual(total, receipt.money(est['totals']['transcript_usd']))  # the page's HTML-safe form
            self.assertLessEqual(abs(sum(r['usd'] for r in est['kinds']) - est['totals']['transcript_usd']), 1e-6)

    def test_the_total_is_the_sum_of_the_unrounded_lines(self):
        est, text = self.pages['demo']
        lines = [r['usd'] for r in est['kinds']]
        self.assertEqual(self.ROW.search(text).group(2), receipt.money(sum(lines)))
        rounded = sum(round(v, 2) for v in lines)
        self.assertNotEqual(round(rounded, 2), round(sum(lines), 2) + 1)  # rounding each line is not how the total is made

    def test_the_row_sits_under_the_legend_lines_with_a_rule_above_it(self):
        est, text = self.pages['demo']
        table = text[text.index('<table class="legend totaltable">'):text.index('</table>', text.index('<table class="legend totaltable">'))]
        self.assertEqual(table.count('class="totalrow"'), 1)
        self.assertLess(text.index('Harness text'), text.index('class="totalrow"'))
        self.assertIn('.totaltable{margin-top:8px;border-top:2px solid', receipt.CSS)
        self.assertIn('Each line is rounded, so the lines may not add up to the last cent. The total is the exact sum.', text)
        self.assertIn('.small{color:var(--muted)', receipt.CSS)

    def test_a_mismatch_is_shown_in_red_with_both_numbers(self):
        est = receipt.build(SESSION_1)
        est['kinds'][0]['usd'] += 0.01
        text = receipt.render(est)
        check = self.ROW.search(text).group(4)
        total = est['totals']['transcript_usd']
        self.assertIn('Does not match', check)
        self.assertIn('class="nomatch"', check)
        self.assertIn('$%.6f' % (total + 0.01), check)
        self.assertIn('$%.6f' % total, check)
        self.assertNotIn('Matches the total at the top', text)
        self.assertIn('.nomatch{color:var(--bad)', receipt.CSS)
        self.assertIn('--bad:#b3261e', receipt.CSS)

    def test_a_tiny_difference_within_the_tolerance_still_matches(self):
        est = receipt.build(SESSION_1)
        est['kinds'][0]['usd'] += 5e-7
        self.assertIn('Matches the total at the top', receipt.render(est))


class RebuildFindingTest(PageCase):
    def test_extra_dollars_are_write_price_minus_resent_price(self):
        prev = {'timestamp': '2026-01-01T10:00:00.000Z'}
        call = {'timestamp': '2026-01-01T10:40:00.000Z', 'model': 'claude-sonnet-5-5', 'cache_miss_reason': 'unavailable',
                'thinking_tokens': 0, 'speed': 'standard', 'inference_geo': 'global', 'web_search_requests': 0,
                'tokens': {'input': 3, 'cache_read': 0, 'cache_write_5m': 100497, 'cache_write_1h': 0, 'output': 100}}
        dollars = estimate._call_dollars(call)
        new_pool, carried_pool, info = estimate._rebuild_info(prev, call, dollars, 500, 500.0)
        self.assertEqual(info['excess_tokens'], 100000)
        self.assertAlmostEqual(info['extra_usd'], 100000 * (2.5 - 0.10) / 1e6, places=4)  # Sonnet 5.5: $2.50 write, $0.10 re-sent
        self.assertAlmostEqual(new_pool + carried_pool, dollars['read'] + dollars['write'], places=12)
        self.assertAlmostEqual(info['pause_minutes'], 40.0)
        self.assertEqual(info['miss_reason'], 'unavailable')

    def test_the_demo_has_one_finding_with_the_count_the_pause_and_the_extra_dollars(self):
        est, text = self.pages['demo']
        found = {f['id']: f for f in est['findings']['session']}['cache_rebuilds']
        self.assertEqual(found['numbers']['count'], 1)
        self.assertAlmostEqual(found['numbers']['pause_minutes'][0], 25, delta=1)
        event = est['rebuild_events'][0]
        self.assertAlmostEqual(found['numbers']['extra_usd'], event['excess_tokens'] * (2.5 - 0.10) / 1e6, delta=0.001)
        self.assertEqual(found['numbers']['extra_usd'], est['rebuild_extra_usd'])
        self.assertEqual(found['sentence'], 'The saved copy of the conversation expired 1 time (after a pause of 25 minutes), so earlier '
                                            'material had to be written again. That cost $0.18 (est.) more than re-sending it would have.')
        self.assertIn(receipt.esc(found['sentence']), text)
        self.assertGreater(est['rebuild_call_usd'], est['rebuild_extra_usd'])  # the full cost is more than the avoidable part

    def test_the_rebuild_is_not_part_of_the_step_ranking(self):
        est = self.pages['demo'][0]
        step = [s for s in est['steps'] if s['rebuild']][0]
        self.assertAlmostEqual(step['total_usd'], step['output_usd'] + step['new_usd'] + step['carried_usd'], places=12)
        self.assertGreater(step['rebuild']['extra_usd'], 0.1)  # it is large, yet none of it is in the step's total
        card = [c for c in est['findings']['top_steps'] if step['number'] in c['steps']][0]
        by_number = {s['number']: s for s in est['steps']}
        self.assertAlmostEqual(card['total_usd'], sum(by_number[n]['total_usd'] for n in card['steps']), places=12)
        self.assertNotEqual(card['id'], 'rebuild')

    def test_no_finding_when_nothing_was_rebuilt_and_many_pauses_are_listed_briefly(self):
        self.assertNotIn('cache_rebuilds', {f['id'] for f in self.pages['s1'][0]['findings']['session']})
        events = [{'order': i, 'pause_minutes': 10.0 + i, 'chain': 'main' if i else 'subagent', 'extra_usd': 0.5, 'call_usd': 1.0}
                  for i in range(8)]
        finding = diagnose._cache_rebuilds({'rebuild_events': events, 'rebuild_extra_usd': 4.0, 'rebuild_call_usd': 8.0,
                                            'totals': {'transcript_usd': 40.0}})
        self.assertIn('8 times', finding['sentence'])
        self.assertIn('and 3 more', finding['sentence'])
        self.assertIn('1 of them happened inside subagents', finding['sentence'])
        self.assertAlmostEqual(finding['numbers']['extra_share'], 0.1)

    def test_the_audit_reports_the_rebuild_extra_dollars(self):
        with tempfile.TemporaryDirectory() as root:
            write_demo_session(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                audit.print_receipts(root)
        text = out.getvalue()
        self.assertIn('cache rebuilds: 1 calls', text)
        self.assertIn('full cost of those calls', text)
        self.assertIn('extra over a normal re-send (est.)', text)
        self.assertRegex(text, r'extra over a normal re-send \(est\.\): \$0\.18 ')


if __name__ == '__main__':
    unittest.main()
