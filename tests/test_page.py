"""Tests for src/page.py and the standard in docs/DESIGN.md: the vendored chart library, no network requests, one colour
per meaning, hover explanations, collapsible sections, CSV buttons, and print. Every session here is an invented fixture."""
import csv
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import page, receipt
from tests.helpers import RECEIPT_MARKERS, SESSION_1, SESSION_2, SESSION_3
from tests.make_demo_session import MARKERS, write_demo_session

HEX = re.compile(r'#[0-9a-fA-F]{6}\b')


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
    def main_part(text):
        """The page's own markup: everything before the library, the CSV blocks, and the data."""
        return text[:text.index('<div id="tip"')]

    @staticmethod
    def data(text):
        raw = re.search(r'<script type="application/json" id="page-data">(.*?)</script>', text, re.S).group(1)
        return json.loads(raw)


class ChartLibraryTest(PageCase):
    def test_the_vendored_file_matches_the_sha256_in_its_readme(self):
        raw = page.ECHARTS_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), page.vendored_sha256())
        readme = page.VENDOR_README.read_text(encoding='utf-8')
        for needed in ('6.1.0', 'https://registry.npmjs.org/echarts/-/echarts-6.1.0.tgz', 'Apache License', 'Version 2.0, January 2004'):
            self.assertIn(needed, readme)

    def test_the_library_inlined_in_every_page_is_the_vendored_file_byte_for_byte(self):
        library = page.ECHARTS_FILE.read_text(encoding='utf-8')
        for name, (est, text) in self.pages.items():
            self.assertIn('<script>%s</script>' % library, text, name)
            inlined = re.search(r'<script>(.*?)</script><script type="application/json"', text, re.S).group(1)
            self.assertEqual(hashlib.sha256(inlined.encode('utf-8')).hexdigest(), page.vendored_sha256(), name)

    def test_a_library_that_does_not_match_its_checksum_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / 'echarts.min.js'
            fake.write_text('alert(1)', encoding='utf-8')
            with mock.patch.object(page, 'ECHARTS_FILE', fake):
                with self.assertRaises(page.PageError):
                    page.inline_echarts()

    def test_charts_use_the_svg_renderer_with_no_animation(self):
        self.assertIn("renderer:'svg'", page.SHARED_JS)
        self.assertIn('option.animation=false', page.SHARED_JS)
        self.assertNotIn("renderer:'canvas'", page.SHARED_JS)


class NoNetworkTest(PageCase):
    BAD_ATTR = re.compile(r'(?:src|href|action|poster|srcset|data)\s*=\s*["\']?\s*(?:https?:)?//', re.I)

    def test_no_page_makes_a_network_request(self):
        for name, (est, text) in self.pages.items():
            own = text.replace(page.ECHARTS_FILE.read_text(encoding='utf-8'), '')
            self.assertNotRegex(own, self.BAD_ATTR, name)
            self.assertNotRegex(own, r'url\(\s*["\']?(?:https?:)?//', name)
            self.assertNotRegex(own, r'@import', name)
            for api in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', 'EventSource', 'importScripts'):
                self.assertNotIn(api, own, (name, api))
            for tag, attr in re.findall(r'<(\w+)[^>]*?\s(src|href)=', own):
                self.fail('%s: <%s %s=> points somewhere' % (name, tag, attr))  # nothing links out; no script, link, or image src

    def test_the_only_urls_in_the_page_are_plain_text_in_the_fine_print(self):
        for name, (est, text) in self.pages.items():
            own = text.replace(page.ECHARTS_FILE.read_text(encoding='utf-8'), '')
            urls = set(re.findall(r'https?://[^\s"\'<>),]+', own))
            # the price source, and a fetched address that a fixture step shows as text in its detail; neither is a link (see above)
            self.assertLessEqual(urls, {'https://platform.claude.com/docs/en/about-claude/pricing', 'https://example.com/page'}, name)

    def test_the_library_itself_contains_no_request_apis_and_only_xml_namespace_urls(self):
        library = page.ECHARTS_FILE.read_text(encoding='utf-8')
        for api in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', 'EventSource', 'importScripts'):
            self.assertNotIn(api, library, api)
        self.assertEqual(set(re.findall(r'https?://[^"\')\s]+', library)),
                         {'http://www.w3.org/2000/svg', 'http://www.w3.org/2000/xmlns/', 'http://www.w3.org/XML/1998/namespace',
                          'http://www.w3.org/1999/xlink',  # four XML namespace names, not requests
                          'http://www.apache.org/licenses/LICENSE-2.0', 'https://github.com/ecomfe/zrender/blob/master/LICENSE'})  # license links in comments
        self.assertNotIn('</script', library.lower())

    def test_csv_downloads_are_built_in_the_page_from_a_blob(self):
        self.assertIn('new Blob', page.SHARED_JS)
        self.assertIn('createObjectURL', page.SHARED_JS)


class LinkedLibraryTest(PageCase):
    """A receipt kept in results/receipts/ loads the library from ../../vendor/ instead of carrying it inside."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.linked = {name: receipt.render(est, library='linked') for name, (est, _) in cls.pages.items()}

    def test_a_linked_page_points_at_the_vendored_file_and_does_not_contain_it(self):
        library = page.ECHARTS_FILE.read_text(encoding='utf-8')
        for name, text in self.linked.items():
            self.assertIn('<script src="../../vendor/echarts.min.js"></script>', text, name)
            self.assertNotIn(library[:2000], text, name)
            self.assertLess(len(text), len(self.pages[name][1]) - len(library) + len(page.LINKED_BLOCK), name)

    def test_the_path_really_reaches_the_vendored_file_from_results_receipts(self):
        here = page.REPO_ROOT / 'results' / 'receipts'
        self.assertEqual((here / page.LINKED_ECHARTS_PATH).resolve(), page.ECHARTS_FILE.resolve())

    def test_the_only_thing_a_linked_page_points_at_is_that_one_local_file(self):
        for name, text in self.linked.items():
            found = re.findall(r'<(\w+)[^>]*?\s(src|href)="([^"]*)"', text)
            self.assertEqual(found, [('script', 'src', '../../vendor/echarts.min.js')], name)
            self.assertNotRegex(text, NoNetworkTest.BAD_ATTR, name)
            self.assertNotRegex(text, r'@import|url\(\s*["\']?(?:https?:)?//', name)

    def test_a_linked_page_says_so_in_words_when_the_library_is_not_there(self):
        for text in self.linked.values():
            self.assertIn('window.echarts||', text)
            self.assertIn(page.NO_CHARTS_NOTE, text)
        self.assertIn('export option', page.NO_CHARTS_NOTE)

    def test_standalone_gives_back_exactly_the_inline_page(self):
        for name, text in self.linked.items():
            self.assertEqual(page.standalone(text), self.pages[name][1], name)

    def test_a_page_that_is_already_standalone_is_unchanged(self):
        text = self.pages['s3'][1]
        self.assertEqual(page.standalone(text), text)

    def test_the_default_page_is_still_inline_so_the_demo_receipt_does_not_change(self):
        for name, (est, text) in self.pages.items():
            self.assertEqual(receipt.render(est, library='inline'), text, name)
            self.assertNotIn('src="', text.replace(page.ECHARTS_FILE.read_text(encoding='utf-8'), ''), name)

    def test_an_unknown_library_mode_is_refused(self):
        with self.assertRaises(page.PageError):
            page.Page('cdn')

    def test_a_linked_page_is_only_built_against_the_pinned_library(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / 'echarts.min.js'
            fake.write_text('alert(1)', encoding='utf-8')
            with mock.patch.object(page, 'ECHARTS_FILE', fake):
                with self.assertRaises(page.PageError):
                    receipt.render(self.pages['s3'][0], library='linked')
                with self.assertRaises(page.PageError):
                    page.standalone(self.linked['s3'])


class OneColourPerMeaningTest(PageCase):
    def test_no_two_meanings_share_a_colour(self):
        values = page.palette_values()
        self.assertEqual(len(set(v.lower() for v in values.values())), len(values), values)
        self.assertEqual(page.COST_COLORS['subagent'], page.KIND_COLORS['subagent'])  # one meaning, one colour

    def test_every_colour_on_every_page_is_in_the_palette(self):
        allowed = {v.lower() for v in page.palette_values().values()} | {v.lower() for v in page.UI.values()}
        allowed |= {'#ffffff', '#00000040', '#000000'}
        for name, (est, text) in self.pages.items():
            library = page.ECHARTS_FILE.read_text(encoding='utf-8')
            own = text.replace(library, '')
            found = {c.lower() for c in HEX.findall(own)}
            self.assertLessEqual(found, allowed, (name, found - allowed))

    def test_the_cost_colours_are_the_same_in_the_cards_the_steps_and_the_growth_chart(self):
        est, text = self.pages['demo']
        growth = self.data(text)['charts']['chart-growth']
        self.assertEqual(growth['series'][0]['itemStyle']['color'], page.COST_COLORS['resent'])
        self.assertEqual(growth['series'][1]['itemStyle']['color'], page.COST_COLORS['new'])
        bar = receipt._bar({'output': 1, 'new': 1, 'carried': 1, 'subagent': 1}, 4)
        for key in ('output', 'new', 'resent', 'subagent'):
            self.assertIn('fill="%s"' % page.COST_COLORS[key], bar)
        legend = receipt._cost_legend(page.Page())
        for key in ('output', 'new', 'resent', 'subagent'):
            self.assertIn('fill="%s"' % page.COST_COLORS[key], legend)
        self.assertNotEqual(page.COST_COLORS['new'], page.COST_COLORS['resent'])  # blue is re-sent, never new

    def test_the_kind_colours_match_between_the_bar_the_legend_and_the_step_rows(self):
        est, text = self.pages['demo']
        kinds = self.data(text)['charts']['chart-kinds']
        for series, row in zip(kinds['series'], [r for r in est['kinds'] if r['usd'] > 0]):
            self.assertEqual(series['itemStyle']['color'], page.KIND_COLORS[row['key']])
            self.assertIn('fill="%s"' % page.KIND_COLORS[row['key']], text)

    def test_text_on_every_colour_has_enough_contrast(self):
        def lum(c):
            parts = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            lin = [p / 12.92 if p <= 0.04045 else ((p + 0.055) / 1.055) ** 2.4 for p in parts]
            return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        for meaning, colour in page.palette_values().items():
            if meaning.startswith('mark:'):
                continue  # a marker shape carries no text
            ink = page.contrast_ink(colour)
            hi, lo = max(lum(colour), lum(ink)), min(lum(colour), lum(ink))
            self.assertGreaterEqual((hi + 0.05) / (lo + 0.05), 4.5, (meaning, colour))

    def test_page_text_colours_have_enough_contrast_on_the_background(self):
        def lum(c):
            parts = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            lin = [p / 12.92 if p <= 0.04045 else ((p + 0.055) / 1.055) ** 2.4 for p in parts]
            return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        for name in ('ink', 'muted', 'ok', 'bad', 'flag'):
            for background in ('bg', 'card'):
                hi, lo = max(lum(page.UI[name]), lum(page.UI[background])), min(lum(page.UI[name]), lum(page.UI[background]))
                self.assertGreaterEqual((hi + 0.05) / (lo + 0.05), 4.5, (name, background))


class HoverExplanationTest(PageCase):
    REQUIRED = ('re-sent', 'new', 'carried cost', 'cache rebuild', 'starting context', 'API-equivalent')

    def test_each_required_term_explains_itself_where_it_first_appears_and_only_there(self):
        for name in ('demo', 's3'):
            est, text = self.pages[name]
            body = self.main_part(text)
            for key in ('api', 'resent', 'new', 'carried', 'rebuild', 'start'):
                words, explanation = page.TERMS[key]
                tip = 'data-tip="%s"' % page.esc(explanation)
                if key == 'start' and name == 'demo':
                    continue  # the demo's headline does not mention the starting context
                self.assertEqual(body.count(tip), 1, (name, key))
                shown = body[body.index(tip):body.index('</span>', body.index(tip))]
                self.assertIn(page.esc(words).lower(), shown.lower(), (name, key))

    def test_the_first_word_of_each_kind_of_number_explains_exact_and_estimated(self):
        body = self.main_part(self.pages['demo'][1])
        self.assertEqual(body.count('data-tip="%s"' % page.esc(page.TERMS['exact'][1])), 1)
        self.assertEqual(body.count('data-tip="%s"' % page.esc(page.TERMS['est'][1])), 1)

    def test_the_glossary_lists_every_term_the_page_explains(self):
        body = self.main_part(self.pages['demo'][1])
        glossary = body[body.index('<dl class="glossary">'):body.index('</dl>')]
        for words, explanation in page.TERMS.values():
            self.assertIn('<dt>%s</dt>' % page.esc(words), glossary)
            self.assertIn(page.esc(explanation), glossary)

    def test_terms_can_be_reached_by_keyboard_and_a_tooltip_is_drawn_by_script(self):
        body = self.main_part(self.pages['demo'][1])
        self.assertIn('class="term" tabindex="0" role="button"', body)
        self.assertIn("addEventListener('focus'", page.SHARED_JS)
        self.assertIn("addEventListener('click'", page.SHARED_JS)  # tap

    def test_a_term_is_plain_after_its_first_use(self):
        pg = page.Page()
        self.assertIn('data-tip', pg.term('resent'))
        self.assertEqual(pg.term('resent'), 're-sent')
        self.assertEqual(pg.annotate('The starting context was big. The starting context again.', ['start']).count('data-tip'), 1)


class LayersAndSectionsTest(PageCase):
    def test_every_section_heading_is_a_question_followed_by_an_answer_sentence(self):
        for name, (est, text) in self.pages.items():
            headings = re.findall(r'<h2[^>]*>(?:<button[^>]*>(?:<span[^>]*></span>)?)?([^<]+)', self.main_part(text))
            self.assertGreaterEqual(len(headings), 8, name)
            for heading in headings:
                self.assertTrue(heading.endswith('?'), (name, heading))
            self.assertGreaterEqual(self.main_part(text).count('<p class="answer">'), 8, name)

    def test_the_evidence_sections_start_collapsed_and_open_for_print(self):
        text = self.pages['demo'][1]
        collapsed = re.findall(r'<section class="sec collapsed" id="(\w+)"', text)
        self.assertEqual(collapsed, ['steps', 'files', 'findings', 'howto', 'fineprint'])
        self.assertEqual(text.count('aria-expanded="false" aria-controls='), 5)
        printed = page.CSS[page.CSS.index('@media print'):]
        self.assertIn('.sec.collapsed .secbody{display:block!important}', printed)
        self.assertIn('.sec.collapsed .secbody{display:none}', page.CSS)
        self.assertIn('.sec.collapsed .secbody,tr.detail{display:block!important}', page.NOSCRIPT_CSS)  # no script: everything shows

    def test_the_answer_layer_comes_before_the_explanation_and_the_evidence(self):
        text = self.pages['demo'][1]
        order = [text.index(x) for x in ('class="headline"', 'class="tiles"', 'id="where"', 'id="expensive"', 'id="growth"',
                                         'id="piling"', 'id="steps"', 'id="fineprint"')]
        self.assertEqual(order, sorted(order))

    def test_at_most_four_tiles_and_a_fifth_only_for_the_task_itself(self):
        for name, (est, text) in self.pages.items():
            tiles = text.count('<div class="tile">')
            self.assertEqual(tiles, 5 if receipt.task_cost(est) is not None else 4, name)

    def test_two_font_weights_at_most(self):
        weights = set(re.findall(r'font-weight:(\d+)', page.CSS)) | set(re.findall(r'font:[^;]*?(\d00)\s', page.CSS))
        self.assertLessEqual(weights, {'400', '700'})


class EveryChartTest(PageCase):
    def test_every_chart_has_a_statement_title_axis_labels_a_tooltip_and_a_text_summary(self):
        for name, (est, text) in self.pages.items():
            charts = self.data(text)['charts']
            self.assertGreaterEqual(len(charts), 3, name)
            for chart_id, option in charts.items():
                self.assertTrue(option['title']['text'].strip(), (name, chart_id))
                self.assertGreater(len(option['title']['text'].split()), 3, (name, chart_id))  # a statement, not a label
                self.assertTrue(option['xAxis'].get('name'), (name, chart_id))
                self.assertIn('tooltip', option)
                box = re.search(r'id="%s".*?</div><p class="chartsum">(.*?)</p></div>' % chart_id, text, re.S)
                self.assertTrue(box and len(box.group(1)) > 20, (name, chart_id))  # the page still reads if the chart fails
                self.assertIn('exact' if 'growth' in chart_id or 'running' in chart_id else 'est.', box.group(1))

    def test_no_pie_no_3d_and_one_value_axis_only(self):
        for name, (est, text) in self.pages.items():
            for chart_id, option in self.data(text)['charts'].items():
                for series in option['series']:
                    self.assertNotIn(series['type'], ('pie', 'bar3D', 'line3D', 'surface'), (name, chart_id))
                self.assertNotIsInstance(option['yAxis'], list)  # no dual axes

    def test_the_stacked_bar_adds_up_to_the_total_and_labels_the_big_segments(self):
        est, text = self.pages['demo']
        option = self.data(text)['charts']['chart-kinds']
        self.assertAlmostEqual(sum(s['data'][0]['value'] for s in option['series']), est['totals']['transcript_usd'], places=6)
        self.assertEqual(option['xAxis']['max'], est['totals']['transcript_usd'])
        big = [s for s in option['series'] if s['label']['show']]
        self.assertGreaterEqual(len(big), 3)

    def test_chart_data_cannot_end_a_script_block(self):
        self.assertEqual(page.json_for_html({'a': '</script><b>&'}), '{"a":"\\u003c/script\\u003e\\u003cb\\u003e\\u0026"}')
        self.assertNotIn('\u2028', page.json_for_html('\u2028'))
        for name, (est, text) in self.pages.items():
            raw = re.search(r'<script type="application/json" id="page-data">(.*?)</script>', text, re.S).group(1)
            self.assertNotIn('<', raw)

    def test_long_sessions_get_zoom_on_both_call_by_call_charts(self):
        est = receipt.build(SESSION_3)
        calls = est['calls']
        many = [dict(calls[i % len(calls)], order=i) for i in range(60)]
        big = dict(est, calls=many)
        self.assertEqual([z['type'] for z in receipt.growth_option(big)['dataZoom']], ['inside', 'slider'])
        self.assertEqual(receipt.growth_option(est)['dataZoom'], [])


class CsvTest(PageCase):
    def blocks(self, text):
        return {m.group(1): json.loads(m.group(2)) for m in re.finditer(
            r'<script type="application/json" id="csv-(\w+)">(.*?)</script>', text, re.S)}

    def test_every_data_table_has_a_download_button_and_its_csv_is_in_the_page(self):
        est, text = self.pages['demo']
        blocks = self.blocks(text)
        self.assertEqual(sorted(blocks), ['files', 'kinds', 'prices', 'steps'])
        for key in blocks:
            self.assertIn('data-csv="csv-%s"' % key, text)
        self.assertEqual(text.count('class="csvbtn"'), 4)

    def test_the_steps_csv_has_a_row_per_step_with_unrounded_dollars(self):
        est, text = self.pages['demo']
        rows = list(csv.reader(io.StringIO(self.blocks(text)['steps'])))
        self.assertEqual(rows[0][:4], ['step', 'kind', 'what_happened', 'output_usd_exact'])
        self.assertEqual(len(rows) - 1, 36)
        self.assertAlmostEqual(float(rows[1][3]), est['steps'][0]['output_usd'], places=6)
        self.assertAlmostEqual(sum(float(r[7]) for r in rows[1:]), sum(s['total_usd'] for s in est['steps']), places=4)

    def test_the_kinds_csv_total_matches_the_headline_total(self):
        est, text = self.pages['demo']
        rows = list(csv.reader(io.StringIO(self.blocks(text)['kinds'])))
        self.assertEqual(len(rows) - 1, 12)
        self.assertAlmostEqual(sum(float(r[1]) for r in rows[1:]), est['totals']['transcript_usd'], places=5)

    def test_no_private_text_reaches_any_csv(self):
        for name, (est, text) in self.pages.items():
            joined = ''.join(self.blocks(text).values())
            for marker in RECEIPT_MARKERS + MARKERS:
                self.assertNotIn(marker, joined, (name, marker))

    def test_the_download_button_is_hidden_when_printing(self):
        self.assertIn('.csvbtn', page.CSS[page.CSS.index('@media print'):])


class FilesTableTest(PageCase):
    def test_the_path_shows_only_when_it_differs_from_the_file_name(self):
        est = receipt.build(SESSION_3)
        cwd = est['session']['cwd']
        est['files'] = [dict(est['files'][0], path=cwd + '/root.txt'),
                        dict(est['files'][0], path=cwd + '/pantry/deep.py')]
        text = receipt.render(est)
        table = text[text.index('id="filetable"'):text.index('</table>', text.index('id="filetable"'))]
        self.assertIn('<b>root.txt</b>', table)
        self.assertNotIn('<span class="sub">root.txt', table)  # same as the name: not repeated
        self.assertIn('<span class="sub">pantry/deep.py</span>', table)


class PrintAndSizeTest(PageCase):
    def test_print_keeps_colour_expands_sections_and_avoids_splitting(self):
        printed = page.CSS[page.CSS.index('@media print'):]
        self.assertIn('print-color-adjust:exact', printed)
        for selector in ('.card', '.tile', 'tr', '.chartbox'):
            self.assertIn(selector, printed[printed.index('break-inside:avoid') - 200:printed.index('break-inside:avoid')])
        self.assertIn('beforeprint', page.SHARED_JS)  # charts are resized to the paper width, and stay SVG
        self.assertIn('.controls,.csvbtn,#tip{display:none!important}', printed)

    def test_no_page_holds_prompt_text_file_contents_or_tool_output(self):
        for name, (est, text) in self.pages.items():
            own = text.replace(page.ECHARTS_FILE.read_text(encoding='utf-8'), '')
            for marker in RECEIPT_MARKERS + MARKERS:
                self.assertNotIn(marker, own, (name, marker))


if __name__ == '__main__':
    unittest.main()
