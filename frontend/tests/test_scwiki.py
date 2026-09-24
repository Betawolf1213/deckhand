"""services.scwiki against recorded starcitizen.tools / api.star-citizen.wiki responses."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import FakeSession, load, offline_session, scwiki_route  # noqa: E402
from services import scwiki  # noqa: E402


def parse_html(name: str) -> str:
    return load(name)["parse"]["text"]


def client(route=scwiki_route) -> scwiki.ScWikiClient:
    return scwiki.ScWikiClient(session=FakeSession(route))


class SpokenNameTests(unittest.TestCase):
    def test_spoken_roman_numeral(self):
        self.assertEqual(scwiki.normalize_spoken_name("deadbolt five"), "deadbolt V")

    def test_spelled_code_with_number_words(self):
        self.assertEqual(scwiki.normalize_spoken_name("a d four b"), "AD4B")
        self.assertEqual(scwiki.normalize_spoken_name("f r seventy six"), "FR76")

    def test_compound_number_is_digits_not_roman(self):
        self.assertEqual(scwiki.normalize_spoken_name("m seven a cannon"), "M7A cannon")
        self.assertEqual(scwiki.normalize_spoken_name("seventy six"), "76")

    def test_digits_mode_for_ship_names(self):
        self.assertEqual(scwiki.normalize_spoken_name("c two hercules", roman=False), "C2 hercules")
        self.assertEqual(scwiki.normalize_spoken_name("three hundred i", roman=False), "300I")

    def test_plain_text_untouched(self):
        self.assertEqual(scwiki.normalize_spoken_name("Atlas"), "Atlas")
        self.assertEqual(scwiki.normalize_spoken_name("FR-76"), "FR-76")


class NumberWordTests(unittest.TestCase):
    def test_scale_words(self):
        self.assertEqual(scwiki.spoken_numbers("four thousand two hundred seventy"), [4270])
        self.assertEqual(scwiki.spoken_numbers("twelve thousand eight hundred and ten"), [12810])

    def test_hundreds_shortcut(self):
        self.assertEqual(scwiki.spoken_numbers("forty two hundred seventy"), [4270])

    def test_pairs_and_digit_by_digit_are_concatenated(self):
        self.assertEqual(scwiki.spoken_numbers("forty two seventy"), [4270])
        self.assertEqual(scwiki.spoken_numbers("four two seven zero"), [4270])

    def test_separate_runs(self):
        self.assertEqual(scwiki.spoken_numbers("f one and then seven"), [1, 7])


class RankingTests(unittest.TestCase):
    def test_ship_weapon_ranking_prefers_exact_weapon(self):
        titles = load("scwiki_opensearch_deadbolt_v.json")[1]
        ranked = scwiki.rank_titles("deadbolt V", titles, ship_weapon=True)
        self.assertEqual(ranked[0], "Deadbolt V Cannon")

    def test_component_ranking_exact_title_first_and_subpages_last(self):
        titles = load("scwiki_opensearch_atlas.json")[1]
        ranked = scwiki.rank_titles("atlas", titles)
        self.assertEqual(ranked[0], "Atlas")
        slash = [i for i, t in enumerate(ranked) if "/" in t]
        plain = [i for i, t in enumerate(ranked) if "/" not in t]
        self.assertTrue(slash and min(slash) > max(plain))


class HtmlParsingTests(unittest.TestCase):
    def test_component_buy_table(self):
        rows = scwiki.parse_shop_table(parse_html("scwiki_parse_atlas.json"))
        self.assertEqual(rows, [scwiki.ShopListing("Stanton", "Platinum Bay - HUR-L5", "84,000")])
        self.assertEqual(rows[0].price_value, 84000)

    def test_rent_table(self):
        rows = scwiki.parse_shop_table(parse_html("scwiki_parse_cutlass_black.json"), column="rent")
        self.assertEqual(len(rows), 28)
        self.assertEqual(rows[0], scwiki.ShopListing("Stanton", "Traveler Tressler", "52,920"))

    def test_specs_strip_inline_styles(self):
        specs = dict(scwiki.parse_specs(parse_html("scwiki_parse_iron.json")))
        self.assertEqual(specs["Refinable"], "Yes")
        self.assertEqual(specs["Signature"], "4,700")
        atlas = dict(scwiki.parse_specs(parse_html("scwiki_parse_atlas.json")))
        self.assertEqual(atlas["Manufacturer"], "Roberts Space Industries")
        self.assertEqual(atlas["Classification"], "Ship.QuantumDrive")

    def test_vehicle_page_detection(self):
        self.assertTrue(scwiki.is_vehicle_specs(scwiki.parse_specs(parse_html("scwiki_parse_cutlass_black.json"))))
        self.assertFalse(scwiki.is_vehicle_specs(scwiki.parse_specs(parse_html("scwiki_parse_atlas.json"))))

    def test_mining_tables_read_every_system(self):
        locs = scwiki.parse_mining_tables(parse_html("scwiki_parse_iron.json"))
        self.assertEqual(len(locs), 65 + 26 + 1)
        self.assertEqual(locs[0], scwiki.MiningLocation("Stanton", "ARC L3", "Asteroid", "17.9%", "245–1000"))
        self.assertEqual({l.system for l in locs}, {"Stanton", "Pyro", "Nyx"})
        akiro = next(l for l in locs if l.body == "Akiro Cluster")
        self.assertEqual(akiro.type, "Asteroid")  # "Asteroid_ValidQT" cleaned
        self.assertAlmostEqual(akiro.spawn_value, 14.8)


class ItemLookupTests(unittest.TestCase):
    def test_component_lookup(self):
        r = client().search_component("atlas")
        self.assertEqual(r.name, "Atlas")
        self.assertEqual(r.kind, "component")
        self.assertEqual(r.url, "https://starcitizen.tools/Atlas")
        self.assertEqual(len(r.locations), 1)
        self.assertEqual(scwiki.item_speech(r),
                         "Atlas is listed at Platinum Bay - HUR-L5, Stanton, for 84,000 a UEC.")

    def test_ship_weapon_lookup_with_spoken_numeral(self):
        r = client().search_ship_weapon("deadbolt five")
        self.assertEqual(r.name, "Deadbolt V Cannon")
        self.assertEqual([l.location for l in r.locations],
                         ["CenterMass - New Babbage", "Ship Weapons - Crusader Showroom - Orison"])
        self.assertIn(("Type", "Ballistic Cannon"), r.specs)
        self.assertTrue(scwiki.item_speech(r).startswith(
            "Deadbolt V Cannon is listed at CenterMass - New Babbage, Stanton, for 288,325 a UEC, "))

    def test_speech_caps_at_five_locations(self):
        many = scwiki.ItemResult("X", "u", "component",
                                 [scwiki.ShopListing("Stanton", f"Shop {i}", "1") for i in range(9)], [])
        self.assertEqual(scwiki.item_speech(many).count("a UEC"), 5)

    def test_no_locations_speech(self):
        r = scwiki.ItemResult("Thing", "u", "component", [], [])
        self.assertEqual(scwiki.item_speech(r),
                         "I found Thing, but the Star Citizen Wiki has no current buy locations listed.")

    def test_not_found(self):
        with self.assertRaises(scwiki.NotFound):
            client().search_component("zzqxv nonsense")

    def test_network_error_is_wrapped(self):
        c = scwiki.ScWikiClient(session=offline_session())
        with self.assertRaises(scwiki.ScWikiError):
            c.search_component("atlas")

    def test_suggestions_are_cached(self):
        session = FakeSession(scwiki_route)
        c = scwiki.ScWikiClient(session=session)
        first = c.suggest_components("atlas")
        n = len(session.calls)
        self.assertEqual(c.suggest_components("atlas"), first)
        self.assertEqual(len(session.calls), n)
        self.assertEqual(first[0], "Atlas")


class MiningLookupTests(unittest.TestCase):
    def test_live_locations(self):
        r = client().fetch_mining_locations("iron")
        self.assertFalse(r.offline)
        self.assertEqual(r.resource, "Iron")
        self.assertEqual(len(r.locations), 92)
        speech = scwiki.mining_speech(r)
        self.assertTrue(speech.startswith("I found 92 listed locations for Iron. The best spawn chances are "
                                          "Adir in Pyro, 43.5 percent"))
        self.assertEqual(speech.count("percent"), 5)

    def test_fallback_when_offline(self):
        c = scwiki.ScWikiClient(session=offline_session())
        r = c.lookup_mining_locations("iron")
        self.assertTrue(r.offline)
        self.assertEqual(r.lines()[0], "Pyro V-c (Adir)")
        self.assertEqual(scwiki.mining_speech(r),
                         "Live lookup failed. Known Iron mining hotspots include Pyro V-c (Adir), "
                         "Pyro V-b (Vatra), Pyro III (Bloom), Magda, Lyria.")

    def test_offline_without_fallback_raises(self):
        c = scwiki.ScWikiClient(session=offline_session())
        with self.assertRaises(scwiki.ScWikiError):
            c.lookup_mining_locations("gold")

    def test_missing_page_is_not_found(self):
        with self.assertRaises(scwiki.NotFound):
            client().fetch_mining_locations("unobtainium")


class ShipLookupTests(unittest.TestCase):
    def test_cutlass_black_live_prices(self):
        r = client().find_ship("cutlass black")
        self.assertFalse(r.offline)
        self.assertEqual(r.name, "Cutlass Black")
        self.assertEqual(r.manufacturer, "Drake Interplanetary")
        self.assertEqual([(p.terminal, p.price) for p in r.purchase],
                         [("New Deal - Teasa Spaceport - Lorville", 2010960)])
        self.assertEqual(len(r.rental), 28)
        self.assertEqual(r.rental[0].price, 50274)
        self.assertEqual([p.price for p in r.rental], sorted(p.price for p in r.rental))
        self.assertEqual(r.rental[0].system, "Stanton")

    def test_name_without_manufacturer_matches(self):
        r = client().find_ship("prospector")
        self.assertEqual(r.name, "MISC Prospector")
        self.assertEqual(r.purchase[0].price, 2783020)

    def test_speech(self):
        r = client().find_ship("cutlass black")
        self.assertEqual(scwiki.ship_speech(r),
                         "Cutlass Black. Buy at New Deal - Teasa Spaceport - Lorville for 2,010,960 a UEC. "
                         "Rent at Traveler Rentals - Cargo Center - Everus Harbor for 50,274 a UEC, "
                         "Vantage Rentals - Lorville for 50,274 a UEC.")

    def test_cutlass_snapshot_when_offline(self):
        r = scwiki.ScWikiClient(session=offline_session()).find_ship("cutlass black")
        self.assertTrue(r.offline)
        self.assertEqual(r.purchase[0].price, 2010960)
        self.assertTrue(r.rental)
        self.assertIn("offline snapshot", scwiki.ship_speech(r))

    def test_cutlass_snapshot_when_live_format_changes(self):
        drifted = load("scapi_vehicles_cutlass_black.json")
        for v in drifted["data"]:
            v.pop("uex_prices")
        r = client(lambda url, params: drifted).find_ship("cutlass black")
        self.assertTrue(r.offline)
        self.assertEqual(r.name, "Cutlass Black")

    def test_other_ship_offline_raises(self):
        with self.assertRaises(scwiki.ScWikiError):
            scwiki.ScWikiClient(session=offline_session()).find_ship("avenger titan")

    def test_unknown_ship_not_found(self):
        with self.assertRaises(scwiki.NotFound):
            client().find_ship("zzqxv")

    def test_ship_suggestions_are_unique(self):
        names = client().suggest_ships("cutlass black")
        self.assertEqual(names, ["Cutlass Black", "Cutlass Black PYAM Exec"])


if __name__ == "__main__":
    unittest.main()
