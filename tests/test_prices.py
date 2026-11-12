"""Tests for src/prices.py and src/reconcile.py."""
import unittest

from src import audit, parse, prices, reconcile
from tests.helpers import FIXTURE_ROOT, SESSION_1


def tokens(**kwargs):
    """A token dict with zeros for anything not given."""
    base = dict.fromkeys(prices.TOKEN_TYPES, 0)
    base.update(kwargs)
    return base


class PriceTableTest(unittest.TestCase):
    def test_every_token_type_at_list_price(self):
        million = 1_000_000
        for kind, expected in (('input', 2.0), ('cache_read', 0.10), ('cache_write_5m', 2.50),
                               ('cache_write_1h', 4.0), ('output', 10.0)):
            self.assertAlmostEqual(prices.price_tokens('claude-sonnet-5-5', tokens(**{kind: million})),
                                   expected)

    def test_dated_model_id_maps_to_its_row(self):
        self.assertEqual(prices.canonical_model('claude-haiku-4-5-20251001'), 'claude-haiku-4-5')
        self.assertAlmostEqual(prices.price_tokens('claude-haiku-4-5-20251001', tokens(input=1_000_000)), 1.0)

    def test_unknown_model_has_no_public_price(self):
        self.assertIsNone(prices.price_tokens('claude-unknown-9', tokens(input=5)))
        self.assertIsNone(prices.canonical_model(None))

    def test_haiku_long_context_tier(self):
        small = prices.price_tokens('claude-haiku-5-5', tokens(input=1_000_000), prompt_tokens=100_000)
        large = prices.price_tokens('claude-haiku-5-5', tokens(input=1_000_000), prompt_tokens=100_001)
        self.assertAlmostEqual(small, 0.10)
        self.assertAlmostEqual(large, 0.50)
        flat = prices.price_tokens('claude-haiku-5-5', tokens(input=1_000_000), prompt_tokens=500_000,
                                   long_context=False)
        self.assertAlmostEqual(flat, 0.10)
        other = prices.price_tokens('claude-sonnet-5-5', tokens(input=1_000_000), prompt_tokens=900_000)
        self.assertAlmostEqual(other, 2.0)  # no tier for other models

    def test_modifiers(self):
        base = tokens(input=1_000_000, output=1_000_000)
        self.assertAlmostEqual(prices.price_tokens('claude-opus-5-5', base), 24.0)
        self.assertAlmostEqual(prices.price_tokens('claude-opus-5-5', base, fast=True), 48.0)
        self.assertAlmostEqual(prices.price_tokens('claude-sonnet-5-5', base, fast=True), 12.0)  # no fast row
        self.assertAlmostEqual(prices.price_tokens('claude-opus-5-5', base, us_geo=True), 26.4)
        self.assertAlmostEqual(prices.price_tokens('claude-opus-5-5', base, web_searches=3), 24.03)

    def test_cache_write_regrouping(self):
        mixed = tokens(cache_write_5m=1_000_000, cache_write_1h=1_000_000)
        self.assertAlmostEqual(prices.price_tokens('claude-sonnet-5-5', mixed), 6.5)
        self.assertAlmostEqual(prices.price_tokens('claude-sonnet-5-5', mixed, cache_write='all_5m'), 5.0)
        self.assertAlmostEqual(prices.price_tokens('claude-sonnet-5-5', mixed, cache_write='all_1h'), 8.0)
        self.assertEqual(mixed['cache_write_1h'], 1_000_000)  # input is not modified

    def test_price_call_uses_the_calls_own_modifiers(self):
        call = {'model': 'claude-opus-5-5', 'tokens': tokens(output=1_000_000), 'speed': 'fast',
                'inference_geo': 'us', 'web_search_requests': 0}
        self.assertAlmostEqual(prices.price_call(call), 20.0 * 2.0 * 1.1)

    def test_table_records_its_source_and_date(self):
        self.assertTrue(prices.PRICES_URL.startswith('https://'))
        self.assertRegex(prices.PRICES_CHECKED, r'^\d{4}-\d{2}-\d{2}$')


class ReconcileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = parse.parse_session(SESSION_1)
        cls.entries = {e['model']: e for e in reconcile.session_entries(cls.session)}

    def test_exact_scopes(self):
        self.assertEqual(self.entries['claude-sonnet-5-5']['exact_scope'], 'main')
        self.assertEqual(self.entries['claude-haiku-5-5']['exact_scope'], 'main+subagents')
        self.assertIsNone(self.entries['claude-opus-5-5']['exact_scope'])

    def test_gap_tokens_for_a_model_with_a_gap(self):
        gap = self.entries['claude-opus-5-5']['gap_tokens']
        self.assertEqual(gap, tokens(input=2, cache_read=100, output=20))

    def test_model_with_no_transcript_call(self):
        entry = self.entries['claude-haiku-4-5-20251001']
        self.assertFalse(entry['has_transcript_calls'])
        self.assertEqual(entry['gap_tokens']['input'], 100)

    def test_model_missing_from_session_totals(self):
        entry = self.entries['claude-unknown-9']
        self.assertFalse(entry['in_cost_state'])
        self.assertIsNone(reconcile.price_entry(entry))  # no public price

    def test_gap_dollars_use_the_same_prices_on_both_sides(self):
        priced = reconcile.price_entry(self.entries['claude-opus-5-5'], 'all_5m')
        self.assertAlmostEqual(priced['gap_usd'], (2 * 4 + 100 * 0.20 + 20 * 20) / 1e6)
        self.assertAlmostEqual(priced['session_total_usd'] - priced['attributed_usd'], priced['gap_usd'])
        self.assertAlmostEqual(sum(priced['gap_by_type_usd'].values()), priced['gap_usd'])

    def test_low_and_high_gap_differ_only_in_cache_write_rate(self):
        entry = dict(self.entries['claude-opus-5-5'])
        entry['gap_tokens'] = tokens(cache_write_5m=1_000_000)
        entry['cost_state_tokens'] = tokens(cache_write_5m=1_000_000)
        entry['transcript_tokens'] = tokens()
        low = reconcile.price_entry(entry, 'all_5m')['gap_usd']
        high = reconcile.price_entry(entry, 'all_1h')['gap_usd']
        self.assertAlmostEqual((low, high), (5.0, 8.0))


class ValidationTest(unittest.TestCase):
    def test_per_call_dollars_match_cost_state_on_exact_entries(self):
        _, items, _ = audit.load_all(FIXTURE_ROOT)
        self.assertEqual(sorted(i['model'] for i in items), ['claude-haiku-5-5', 'claude-sonnet-5-5'])
        result = prices.validate(items)
        base = result['rows'][0]
        self.assertEqual((base['variant'], base['matched'], base['entries']), ('base', 2, 2))
        self.assertLess(base['max_abs_diff_usd'], 1e-9)
        by_name = {row['variant']: row for row in result['rows']}
        self.assertLess(by_name['a1']['matched'], 2)  # the 1h write in the Sonnet entry needs the split
        self.assertEqual(by_name['b-e']['matched'], 2)

    def test_audit_counts_sessions_without_cost_state(self):
        _, _, sessions = audit.load_all(FIXTURE_ROOT)
        self.assertEqual(sorted(s['has_cost_state'] for s in sessions), [False, True])


if __name__ == '__main__':
    unittest.main()
