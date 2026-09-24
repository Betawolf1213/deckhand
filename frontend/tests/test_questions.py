"""services.questions.answer() + the UEX / wiki service extensions it relies on (offline)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import FakeSession, offline_session, scwiki_route, uex_route, wiki_route  # noqa: E402
from pages.base import Answer  # noqa: E402
from services import mining_data, questions, scwiki, uex, wiki  # noqa: E402

COMMANDS = [
    {"id": "landing_gear", "label": "Landing Gear", "phrases": ["landing gear", "gear"],
     "action": {"type": "tap", "keys": "n"}},
    {"id": "mobiglas", "label": "MobiGlas", "phrases": ["open mobi"], "action": {"type": "tap", "keys": "f1"}},
    {"id": "unlock_ports", "label": "Unlock Ports", "phrases": ["unlock ports"],
     "action": {"type": "tap", "keys": "right alt+k"}},
    {"id": "shield_front", "label": "Shields Front", "phrases": ["shields front"],
     "action": {"type": "tap", "keys": "numpad8"}},
    {"id": "chat", "label": "Chat", "phrases": ["chat"], "action": {"type": "tap", "keys": "f12"}},
    {"id": "ship_zoom", "phrases": ["zoom"],
     "action": {"type": "mouse", "button": "right", "kind": "click", "keys": "left alt"}},
    {"id": "boost", "label": "Boost", "phrases": ["boost"],
     "action": {"type": "hold", "keys": "left shift", "duration_ms": 250}},
    {"id": "scroll_up", "phrases": ["scroll up"], "action": {"type": "scroll", "direction": "up", "amount": 3}},
]


class LiveServicesPatched(unittest.TestCase):
    """Route every service through recorded fixtures (or an offline session)."""

    scwiki_session = None
    uex_session = None
    wiki_session = None

    def setUp(self):
        sc = scwiki.ScWikiClient(session=self.scwiki_session or FakeSession(scwiki_route))
        with mock.patch.dict(os.environ, {"UEX_API_KEY": ""}):
            ux = uex.Uex(session=self.uex_session or FakeSession(uex_route), require_key=False)
        wk = wiki.Wiki(session=self.wiki_session or FakeSession(wiki_route))
        for target, value in ((scwiki, sc), (uex, ux), (wiki, wk)):
            name = {"scwiki": "default_client", "uex": "get_client", "wiki": "default_client"}[target.__name__.split(".")[-1]]
            p = mock.patch.object(target, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def ask(self, text: str) -> Answer | None:
        return questions.answer(text, COMMANDS)


# ---------------------------------------------------------------- key parsing


class ParseKeyTests(unittest.TestCase):
    def test_function_keys(self):
        self.assertEqual(questions.parse_key("f one"), "f1")
        self.assertEqual(questions.parse_key("f twelve"), "f12")
        self.assertEqual(questions.parse_key("f12"), "f12")

    def test_modifiers(self):
        self.assertEqual(questions.parse_key("right alt k"), "right alt+k")
        self.assertEqual(questions.parse_key("alt f four"), "alt+f4")
        self.assertEqual(questions.parse_key("left control plus c"), "left ctrl+c")

    def test_numpad(self):
        self.assertEqual(questions.parse_key("num seven"), "num 7")
        self.assertEqual(questions.parse_key("numpad eight"), "num 8")
        self.assertEqual(questions.parse_key("number pad two"), "num 2")

    def test_spoken_letters_and_named_keys(self):
        self.assertEqual(questions.parse_key("kay"), "k")
        self.assertEqual(questions.parse_key("the n key"), "n")
        self.assertEqual(questions.parse_key("space bar"), "space")
        self.assertEqual(questions.parse_key("left shift"), "left shift")
        self.assertEqual(questions.parse_key("seven"), "7")

    def test_mouse(self):
        self.assertEqual(questions.parse_key("left alt right mouse"), "left alt+right mouse")

    def test_misheard_single_letters(self):
        # Real Vosk free-form output for a spoken "what is N bound to" was "what is and bound to".
        self.assertEqual(questions.parse_key("and"), "n")
        self.assertEqual(questions.parse_key("an"), "n")
        self.assertEqual(questions.parse_key("in"), "n")
        self.assertEqual(questions.parse_key("hey"), "a")
        self.assertEqual(questions.parse_key("double you"), "w")
        # "and" stays filler inside a combo
        self.assertEqual(questions.parse_key("alt and k"), "alt+k")

    def test_misheard_letter_question(self):
        a = questions.answer("what is and bound to", COMMANDS)
        self.assertIsNotNone(a)
        self.assertTrue(a.speech.startswith("N is bound to"), a.speech)

    def test_not_a_key(self):
        self.assertIsNone(questions.parse_key("landing gear"))
        self.assertIsNone(questions.parse_key(""))


# ---------------------------------------------------------------- keybinds


class KeybindQuestionTests(unittest.TestCase):
    def ask(self, text):
        return questions.answer(text, COMMANDS)

    def test_what_is_letter_bound_to(self):
        a = self.ask("what is n bound to")
        self.assertEqual(a.speech, "N is bound to Landing Gear.")
        # Keybind answers now open the KEYBINDS page filtered to that key.
        self.assertEqual(a.page, "KEYBINDS")
        self.assertEqual(a.payload, {"kind": "by_key", "key": "n"})

    def test_what_does_function_key_do(self):
        self.assertEqual(self.ask("what does f one do").speech, "F1 is bound to MobiGlas.")

    def test_modifier_combo(self):
        self.assertEqual(self.ask("what is right alt k bound to").speech,
                         "Right Alt plus K is bound to Unlock Ports.")

    def test_sideless_modifier_matches_either_side(self):
        self.assertEqual(self.ask("what is alt k bound to").speech, "Alt plus K is bound to Unlock Ports.")
        self.assertEqual(self.ask("what is shift bound to").speech, "Shift is bound to Boost.")

    def test_whats_the_bind_for(self):
        self.assertEqual(self.ask("what's the bind for f12").speech, "F12 is bound to Chat.")
        self.assertEqual(self.ask("what is the bind for f twelve").speech, "F12 is bound to Chat.")

    def test_numpad_matches_command_spelling(self):
        self.assertEqual(self.ask("what is num eight bound to").speech, "Num 8 is bound to Shields Front.")

    def test_mouse_binding_uses_id_when_label_missing(self):
        self.assertEqual(self.ask("what is left alt right mouse bound to").speech,
                         "Left Alt plus Right Mouse is bound to Ship Zoom.")

    def test_base_key_only_used_in_combo(self):
        self.assertEqual(self.ask("what is k bound to").speech,
                         "Nothing in your commands uses K by itself. Right Alt plus K is bound to Unlock Ports.")

    def test_falls_back_to_default_game_reference(self):
        self.assertEqual(self.ask("what is f two bound to").speech,
                         "F2 isn't used by your voice commands. In the default Star Citizen controls it is: Open Starmap.")

    def test_unknown_key(self):
        self.assertEqual(self.ask("what is f nine bound to").speech,
                         "Nothing in your commands uses F9, and I have no default Star Citizen binding for it.")

    def test_reverse_lookup_by_command_name(self):
        self.assertEqual(self.ask("what key is landing gear").speech, "Landing Gear is on N.")
        self.assertEqual(self.ask("what is the bind for unlock ports").speech, "Unlock Ports is on Right Alt plus K.")

    def test_not_a_keybind_question(self):
        self.assertIsNone(self.ask("landing gear"))
        self.assertIsNone(self.ask(""))


# ---------------------------------------------------------------- signatures


class SignatureQuestionTests(unittest.TestCase):
    def ask(self, text):
        return questions.answer(text, COMMANDS)

    def test_spoken_number(self):
        a = self.ask("what resource is four thousand two hundred seventy")
        self.assertEqual(a.speech, "4,270 is Iron, at 1 X signature.")
        self.assertEqual(a.page, "MINING MODE")
        self.assertIsInstance(a.payload, mining_data.ReverseResult)
        self.assertEqual(a.payload.signature, 4270)

    def test_digits_with_comma(self):
        self.assertEqual(self.ask("what ore is 12,810").speech, "12,810 is Iron, at 3 X signature.")

    def test_multiple_matches_and_pair_form(self):
        self.assertTrue(self.ask("what is signature nineteen thousand two hundred").speech
                        .startswith("19,200 has multiple matches"))
        self.assertEqual(self.ask("which mineral is forty two seventy").speech, "4,270 is Iron, at 1 X signature.")

    def test_small_numbers_are_not_signatures(self):
        self.assertIsNone(self.ask("what resource is five"))


# ---------------------------------------------------------------- wiki lookups


class MiningQuestionTests(LiveServicesPatched):
    def test_where_can_i_mine(self):
        a = self.ask("where can i mine iron")
        self.assertEqual(a.page, "MINING MODE")
        self.assertIsInstance(a.payload, scwiki.MiningResult)
        self.assertTrue(a.speech.startswith("I found 92 listed locations for Iron."))
        self.assertTrue(a.details)

    def test_where_can_i_find_a_mineral(self):
        a = self.ask("where can i find iron ore")
        self.assertEqual(a.page, "MINING MODE")

    def test_misheard_mine_still_mining(self):
        # Real Vosk free-form output for a spoken "where can I mine iron".
        for text in ("where can i might iron", "where can i mind iron", "where can i my iron",
                     "where can i mean iron", "where can i mining iron"):
            with self.subTest(text=text):
                self.assertEqual(self.ask(text).page, "MINING MODE")

    def test_misheard_mine_needs_a_known_mineral(self):
        # "might" + a non-mineral must not become a mining lookup.
        a = self.ask("where can i might atlas")
        self.assertNotEqual(getattr(a, "page", None), "MINING MODE")


class MiningOfflineTests(LiveServicesPatched):
    scwiki_session = offline_session()

    def test_iron_fallback(self):
        a = self.ask("where can i mine iron")
        self.assertTrue(a.speech.startswith("Live lookup failed. Known Iron mining hotspots include Pyro V-c (Adir)"))
        self.assertTrue(a.payload.offline)

    def test_no_fallback_apologises(self):
        a = self.ask("where is quantainium mined")
        self.assertEqual(a.speech, "Sorry, I couldn't reach the Star Citizen Wiki to look up Quantainium mining locations.")


class ComponentQuestionTests(LiveServicesPatched):
    def test_component(self):
        a = self.ask("where can i buy an atlas component")
        self.assertEqual(a.speech, "Atlas is listed at Platinum Bay - HUR-L5, Stanton, for 84,000 a UEC.")
        self.assertEqual(a.page, "COMPONENTS")
        self.assertEqual(a.payload.name, "Atlas")

    def test_where_can_i_find_non_mineral_is_a_component(self):
        self.assertEqual(self.ask("where can i find an atlas").page, "COMPONENTS")

    def test_ship_weapon_with_spoken_numeral(self):
        a = self.ask("where can i buy a deadbolt five ship weapon")
        self.assertEqual(a.page, "SHIP WEAPONS")
        self.assertEqual(a.payload.name, "Deadbolt V Cannon")
        self.assertTrue(a.speech.startswith("Deadbolt V Cannon is listed at CenterMass - New Babbage"))
        self.assertEqual(self.ask("list locations for the deadbolt five ship weapon").page, "SHIP WEAPONS")

    def test_article_stripping_keeps_spelled_letter_a(self):
        self.assertEqual(questions._clean_name("the a d four b"), "a d four b")
        self.assertEqual(questions._clean_name("a d four b"), "a d four b")
        self.assertEqual(questions._clean_name("an atlas"), "atlas")
        self.assertEqual(questions._clean_name("the atlas"), "atlas")

    def test_vehicle_page_routes_to_ship_finder(self):
        a = self.ask("where can i buy a cutlass black")
        self.assertEqual(a.page, "SHIP FINDER")
        self.assertIsInstance(a.payload, scwiki.ShipResult)
        self.assertTrue(a.speech.startswith("Cutlass Black. Buy at New Deal"))

    def test_not_found(self):
        a = self.ask("where can i buy a zzqxv")
        self.assertEqual(a.speech, "I could not find current Star Citizen Wiki locations for zzqxv.")
        self.assertIsNone(a.page)


class ComponentOfflineTests(LiveServicesPatched):
    scwiki_session = offline_session()

    def test_offline_apology(self):
        a = self.ask("where can i buy an atlas")
        self.assertEqual(a.speech, "Sorry, I couldn't reach the Star Citizen Wiki to look up atlas.")


class ShipQuestionTests(LiveServicesPatched):
    def test_rent(self):
        a = self.ask("where can i rent a cutlass black")
        self.assertEqual(a.page, "SHIP FINDER")
        self.assertEqual(a.payload.name, "Cutlass Black")

    def test_how_much_is_a_ship(self):
        a = self.ask("how much does a prospector ship cost")
        self.assertEqual(a.payload.name, "MISC Prospector")


class ShipOfflineTests(LiveServicesPatched):
    scwiki_session = offline_session()

    def test_cutlass_snapshot(self):
        a = self.ask("where can i rent a cutlass black")
        self.assertTrue(a.payload.offline)
        self.assertIn("offline snapshot", a.speech)


# ---------------------------------------------------------------- commodities


class CommodityQuestionTests(LiveServicesPatched):
    def test_price_of(self):
        a = self.ask("what is the price of iron")
        self.assertEqual(a.page, "COMMODITIES")
        self.assertEqual(a.payload.commodity.name, "Iron")
        self.assertEqual(a.speech,
                         "Iron sells best at Admin - Endgame for 3,900, Admin - Terra Gateway (Stanton) for 3,700, "
                         "Admin - Gaslight for 3,700 a UEC per SCU. Cheapest to buy at Levski for 2,349, "
                         "Admin - Checkmate for 2,480.")

    def test_where_can_i_sell(self):
        self.assertEqual(self.ask("where can i sell iron").page, "COMMODITIES")


class CommodityOfflineTests(LiveServicesPatched):
    uex_session = offline_session()

    def test_offline(self):
        a = self.ask("what is the price of iron")
        self.assertEqual(a.speech, "Sorry, I couldn't reach UEX to look up iron prices.")


class WikiQuestionTests(LiveServicesPatched):
    def test_tell_me_about(self):
        a = self.ask("tell me about the carrack")
        self.assertEqual(a.page, "WIKI")
        self.assertEqual(a.payload.title, "Carrack")
        self.assertTrue(a.speech.startswith("The Anvil Carrack is a multi-crew explorer"))
        self.assertLessEqual(a.speech.count(". "), 2)

    def test_open_ended_what_is_the_is_not_answered(self):
        self.assertIsNone(self.ask("what is the meaning of life"))


class NeverRaisesTests(unittest.TestCase):
    def test_unexpected_exception_becomes_apology(self):
        with mock.patch.object(scwiki, "default_client", side_effect=RuntimeError("boom")), \
                self.assertLogs("services.questions", level="ERROR"):
            a = questions.answer("where can i buy an atlas", COMMANDS)
        self.assertIsInstance(a, Answer)
        self.assertIn("Sorry", a.speech)

    def test_garbage_input(self):
        self.assertIsNone(questions.answer(None, None))  # type: ignore[arg-type]


# ---------------------------------------------------------------- service extensions


class UexServiceTests(unittest.TestCase):
    def client(self, session=None):
        with mock.patch.dict(os.environ, {"UEX_API_KEY": ""}):
            return uex.Uex(session=session or FakeSession(uex_route), require_key=False)

    def test_strict_constructor_still_requires_key(self):
        with mock.patch.dict(os.environ, {"UEX_API_KEY": ""}):
            with self.assertRaises(uex.UexKeyMissing):
                uex.Uex(session=FakeSession(uex_route))

    def test_anonymous_mode_sends_no_auth_header(self):
        c = self.client()
        self.assertTrue(c.anonymous)
        self.assertNotIn("Authorization", c._session.headers)
        self.assertIn("UEX_API_KEY", uex.key_status())

    def test_search_contract_unchanged(self):
        commodity, listings = self.client().search("iron")
        self.assertEqual((commodity.id, commodity.name, commodity.code), (44, "Iron", "IRON"))
        self.assertEqual(len(listings), 44)
        self.assertTrue(all(isinstance(l, uex.Listing) for l in listings))
        self.assertEqual(listings[0].system, "Stanton")

    def test_suggestions_rank_prefix_first(self):
        self.assertEqual(self.client().suggest("iro")[:2], ["Iron", "Iron (Ore)"])
        self.assertEqual(self.client().suggest("lara")[:2], ["Laranite", "Laranite (Raw)"])

    def test_fuzzy_misheard_name(self):
        self.assertEqual(self.client().find_commodity("medical supply").name, "Medical Supplies")
        self.assertEqual(self.client().find_commodity("laranight").name, "Laranite")

    def test_network_error_is_uex_error(self):
        with self.assertRaises(uex.UexError):
            self.client(offline_session()).list_commodities()


class WikiServiceTests(unittest.TestCase):
    def test_lookup_returns_hits_and_summary(self):
        r = wiki.Wiki(session=FakeSession(wiki_route)).lookup("carrack")
        self.assertEqual(r.title, "Carrack")
        self.assertEqual(r.hits[0].title, "Carrack")
        self.assertTrue(r.summary.startswith("The Anvil Carrack"))
        self.assertEqual(r.url, "https://starcitizen.tools/Carrack")

    def test_suggest(self):
        self.assertEqual(wiki.Wiki(session=FakeSession(wiki_route)).suggest("carrack")[:2],
                         ["Carrack", "Carrack Expedition"])

    def test_network_error_is_wiki_error(self):
        with self.assertRaises(wiki.WikiError):
            wiki.Wiki(session=offline_session()).lookup("carrack")


if __name__ == "__main__":
    unittest.main()
