"""Tests for the page's number formats, print rules, headline, chart, and total row."""
import io
import contextlib
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
        self.assertEqual([mixed(v) for v in (0.0063, 0.1155, 0.01, 0)], ['$0.0063', '$0.1155', '$0.0100', '$0.0000'])
        cents = fmt.money_column([0.02, 0.1155, 3.0])
        self.assertEqual([cents(v) for v in (0.02, 0.1155, 3.0)], ['$0.02', '$0.12', '$3.00'])
        self.assertEqual(len({len(mixed(v).split('.')[1]) for v in (0.0063, 0.1155, 0.01, 0)}), 1)

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
        start = text.index('<h2>%s</h2>' % title)
        return text[start:text.index('</section>', start)]


class NumberFormatOnThePageTest(PageCase):
    def test_tiles_legend_and_cards_use_two_decimals_only(self):
        for name, (est, text) in self.pages.items():
            tiles = text[text.index('class="tiles"'):text.index('</section>', text.index('class="tiles"'))]
            for part in (tiles, self.section(text, 'Where the money went'), self.section(text, 'The three most expensive steps')):
                for amount in DOLLARS.findall(part):
                    self.assertEqual(len(amount.split('.')[1]), 2, (name, amount))

    def test_amounts_under_a_cent_read_less_than_one_cent(self):
        est, text = self.pages['demo']
        legend = self.section(text, 'Where the money went')
        self.assertIn('&lt;$0.01', legend)  # escaped, so it is valid HTML
        self.assertIn('&lt;0.1%', legend)  # "Your prompts" are under 0.1 percent of the demo
        self.assertNotIn('<$', text)
        self.assertNotIn('><0.1%', text)
        self.assertNotRegex(legend, r'\$0\.00\d')

    def test_every_row_of_a_table_column_has_the_same_decimals(self):
        for name, (est, text) in self.pages.items():
            steps = text[text.index('<tbody id="stepbody"'):text.index('</tbody>')]
            totals = re.findall(r'<td class="r">(\$[\d,]+\.\d+|no public price)</td></tr>', steps)
            self.assertEqual(len({len(t.split('.')[1]) for t in totals if t.startswith('$')}), 1, name)
        est, text = self.pages['demo']
        steps = text[text.index('<tbody id="stepbody"'):text.index('</tbody>')]
        decimals = [len(d) for d in re.findall(r'<td class="r">\$[\d,]+\.(\d+)</td></tr>', steps)]
        self.assertEqual(len(decimals), 36)
        self.assertEqual(set(decimals), {4})  # the demo's steps are mostly under a dime, so the column uses four
        files = text[text.index('id="filetable"'):text.index('</tbody>', text.index('id="filetable"'))]
        decimals = {len(d) for d in re.findall(r'<td class="r">\$[\d,]+\.(\d+)</td>', files)}
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
        self.assertEqual(text.count('<svg class="mk"'), 4)  # the growth chart's legend markers are drawn too

    def test_the_legend_and_its_total_row_stay_together(self):
        text = self.pages['demo'][1]
        keep = text[text.index('<div class="keep"><svg class="kindbar"'):]
        keep = keep[:keep.index('</div></section>')]
        self.assertIn('class="totalrow"', keep)
        self.assertIn('Each line is rounded', keep)
        self.assertIn('.keepsec{break-inside:avoid', receipt.CSS)


class HeadlineTest(PageCase):
    def test_one_headline_sentence_sits_under_the_tiles(self):
        est, text = self.pages['demo']
        found = est['findings']['headline']
        self.assertEqual(found['id'], 'repeated_step')
        self.assertEqual(found['sentence'], 'The largest single cause: Read inventory.py 3 times, $0.32 in all, 37% of the total (est.).')
        self.assertLess(text.index('class="tiles"'), text.index('class="headline"'))
        self.assertLess(text.index('class="headline"'), text.index('Where the money went'))
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

    def test_every_fixture_page_builds_with_or_without_a_headline(self):
        for name in ('s1', 's2', 's3'):
            self.assertIn('Where the money went', self.pages[name][1])


class GrowthChartTest(PageCase):
    def test_taller_with_readable_axes_and_drawn_markers(self):
        est, text = self.pages['demo']
        chart = text[text.index('<svg class="growth"'):text.index('</svg>', text.index('<svg class="growth"'))]
        self.assertGreaterEqual(int(re.search(r'viewBox="0 0 1000 (\d+)"', chart).group(1)), 360)
        labels = re.findall(r'<text[^>]*font-size="(\d+)"[^>]*>([^<]*)</text>', chart)
        self.assertTrue(all(int(size) >= 13 for size, _ in labels))
        words = [w for _, w in labels]
        for expected in ('0', '25k', '50k', '75k', '100k', '1', '36', 'Model call, in order', 'Tokens in the prompt'):
            self.assertIn(expected, words)
        self.assertIn('Cache rebuilt after 25 minutes', chart)
        self.assertEqual(chart.count('<g><title>Call '), 36)

    def test_ticks_are_round_and_labels_are_few(self):
        self.assertEqual(receipt._nice_ceiling(98140), 100000)
        self.assertEqual(receipt._nice_ceiling(21000), 25000)
        self.assertEqual(receipt._nice_ceiling(147573), 200000)
        self.assertLessEqual(len(receipt._x_ticks(6578)), 9)
        self.assertEqual(receipt._x_ticks(36)[0], 1)
        self.assertIn(36, receipt._x_ticks(36))
        self.assertEqual(receipt._x_ticks(1), [1])


class TotalRowTest(PageCase):
    ROW = re.compile(r'<tr class="totalrow"><td></td><td>([^<]*)</td><td class="r">([^<]*)</td><td class="r">([^<]*)</td>'
                     r'<td class="check">(.*?)</td></tr>')

    def test_the_total_row_equals_the_headline_total_on_every_fixture_and_the_demo(self):
        for name, (est, text) in self.pages.items():
            label, total, share, check = self.ROW.search(text).groups()
            self.assertEqual(label, 'Total of the lines above')
            self.assertEqual(share, '100%')
            self.assertIn('Matches the total at the top', check)
            self.assertNotIn('Does not match', text)
            headline = re.search(r'Total at public API prices: <b>([^<]*)</b>', text).group(1)
            self.assertEqual(total, headline, name)
            self.assertEqual(total, receipt.money(est['totals']['transcript_usd']))  # the page's HTML-safe form
            self.assertLessEqual(abs(sum(r['usd'] for r in est['kinds']) - est['totals']['transcript_usd']), 1e-6)

    def test_the_total_is_the_sum_of_the_unrounded_lines(self):
        est, text = self.pages['demo']
        lines = [r['usd'] for r in est['kinds']]
        self.assertEqual(self.ROW.search(text).group(2), receipt.money(sum(lines)))
        rounded = sum(round(v, 2) for v in lines)
        self.assertNotEqual(round(rounded, 2), round(sum(lines), 2) + 1)  # rounding each line is not how the total is made

    def test_the_row_sits_in_the_legend_table_under_a_rule(self):
        est, text = self.pages['demo']
        table = text[text.index('<table class="legend kindlegend">'):text.index('</table>', text.index('<table class="legend kindlegend">'))]
        self.assertTrue(table.rstrip().endswith('</tr>'))
        self.assertEqual(table.count('class="totalrow"'), 1)
        self.assertLess(table.index('Harness text'), table.index('class="totalrow"'))
        self.assertIn('tr.totalrow td{border-top:2px solid', receipt.CSS)
        self.assertIn('Each line is rounded, so the lines may not add up to the last cent. The total is the exact sum.', text)
        self.assertIn('.small{color:#6b7078', receipt.CSS)

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
        self.assertIn('.nomatch{color:#b3261e', receipt.CSS)

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
