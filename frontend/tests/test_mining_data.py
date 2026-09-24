"""Mining signature table, reverse signature lookup and spoken text (no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import mining_data as md  # noqa: E402


class TableTests(unittest.TestCase):
    def test_display_order_covers_every_ore_once(self):
        self.assertEqual(len(md.MINING_DISPLAY_ORDER), 26)
        self.assertEqual(len(set(md.MINING_DISPLAY_ORDER)), 26)
        for ore in md.MINING_DISPLAY_ORDER:
            self.assertIn(ore, md.MINING_PRIMARY)

    def test_signature_values_are_one_to_ten_multiples(self):
        vals = md.signature_values("iron")
        self.assertEqual(vals[0], 4270)
        self.assertEqual(vals[1], 8540)
        self.assertEqual(vals[-1], 42700)
        self.assertEqual(len(vals), 10)

    def test_table_lines_have_header_rule_and_one_row_per_ore(self):
        lines = md.table_lines()
        self.assertTrue(lines[0].startswith("ORE"))
        self.assertIn("10x", lines[0])
        self.assertEqual(len(lines), 2 + 26)
        self.assertTrue(lines[2].startswith("Ice"))
        self.assertIn("43,000", lines[2])


class NormalizeOreTests(unittest.TestCase):
    def test_us_spelling_alias(self):
        self.assertEqual(md.normalize_ore("aluminum"), "aluminium")

    def test_strips_filler_words_and_case(self):
        self.assertEqual(md.normalize_ore("Iron ore"), "iron")

    def test_fuzzy_misheard_name(self):
        self.assertEqual(md.normalize_ore("quanta nium"), "quantainium")
        self.assertEqual(md.normalize_ore("laranight"), "laranite")

    def test_unknown_returns_none(self):
        self.assertIsNone(md.normalize_ore("banana bread"))
        self.assertIsNone(md.normalize_ore(""))


class ReverseLookupTests(unittest.TestCase):
    def test_exact_single_match(self):
        r = md.reverse_lookup(4270)
        self.assertEqual([(m.ore, m.multiple) for m in r.exact], [("iron", 1)])
        self.assertEqual(r.speech(), "4,270 is Iron, at 1 X signature.")

    def test_exact_multiple_matches(self):
        r = md.reverse_lookup(19200)
        self.assertEqual([(m.ore, m.multiple) for m in r.exact],
                         [("aslarite", 5), ("savrililum", 6)])
        self.assertEqual(r.speech(),
                         "19,200 has multiple matches: Aslarite at 5 X, Savrililum at 6 X.")

    def test_near_match_within_tolerance(self):
        r = md.reverse_lookup(4280)
        self.assertEqual(r.exact, [])
        self.assertEqual((r.nearest.ore, r.nearest.multiple, r.nearest.value, r.nearest.diff),
                         ("aluminium", 1, 4285, 5))
        self.assertEqual(r.speech(), "There is no exact match for 4,280. The closest is "
                                     "Aluminium at 1 X, with a signature of 4,285.")

    def test_far_from_any_match(self):
        r = md.reverse_lookup(1000)
        self.assertEqual(r.nearest.value, 3170)
        self.assertTrue(r.speech().startswith("There is no mining signature match for 1,000. "
                                              "The nearest is Quantainium at 1 X"))

    def test_candidates_lists_close_values_sorted_by_distance(self):
        r = md.reverse_lookup(12808)  # 12,800 is Savrililum x4, 12,810 Iron x3
        top = r.candidates(3)
        self.assertEqual(len(top), 3)
        self.assertEqual((top[0].ore, top[0].multiple), ("iron", 3))  # 12,810
        self.assertLessEqual(top[0].diff, top[1].diff)


class SpeechTests(unittest.TestCase):
    def test_signature_speech(self):
        s = md.signature_speech("iron")
        self.assertTrue(s.startswith("Iron mining signatures are: 1 X, 4,270, 2 X, 8,540"))
        self.assertTrue(s.endswith("10 X, 42,700."))

    def test_fallback_locations_for_iron(self):
        locs = md.fallback_locations("iron")
        self.assertEqual(len(locs), 18)
        self.assertEqual(locs[0], "Pyro V-c (Adir)")
        self.assertEqual(md.fallback_locations("gold"), [])


if __name__ == "__main__":
    unittest.main()
