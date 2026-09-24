"""Smoke tests: each lookup page builds with FakeContext and fixtures and shows a real Answer."""
from __future__ import annotations

import os
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_ctx import FakeContext  # noqa: E402
from fixtures import FakeSession, offline_session, scwiki_route, uex_route, wiki_route  # noqa: E402
from pages import PAGE_ORDER  # noqa: E402
from services import questions, scwiki, uex, wiki  # noqa: E402

LOOKUP_PAGES = ["COMPONENTS", "SHIP WEAPONS", "COMMODITIES", "MINING MODE", "SHIP FINDER", "WIKI"]


def page_class(key: str):
    import importlib
    return importlib.import_module(f"pages.{PAGE_ORDER[key]}").PAGE_CLASS


def text_of(widget: tk.Text) -> str:
    return widget.get("1.0", "end-1c")


class PageTestBase(unittest.TestCase):
    scwiki_session = None
    uex_session = None

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as e:  # pragma: no cover - headless CI
            raise unittest.SkipTest(f"Tk unavailable: {e}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        env = mock.patch.dict(os.environ, {"UEX_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        sc = scwiki.ScWikiClient(session=self.scwiki_session or FakeSession(scwiki_route))
        ux = uex.Uex(session=self.uex_session or FakeSession(uex_route), require_key=False)
        wk = wiki.Wiki(session=FakeSession(wiki_route))
        for target, name, value in ((scwiki, "default_client", sc), (uex, "get_client", ux),
                                    (wiki, "default_client", wk)):
            p = mock.patch.object(target, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.ctx = FakeContext(self.root)

    def build(self, key: str):
        page = page_class(key)(self.root, self.ctx)
        self.addCleanup(page.destroy)
        return page

    def answer(self, text: str):
        a = questions.answer(text, [])
        self.assertIsNotNone(a, text)
        return a


class BuildTests(PageTestBase):
    def test_every_lookup_page_builds_with_title(self):
        for key in LOOKUP_PAGES:
            with self.subTest(page=key):
                page = self.build(key)
                self.assertEqual(page.title, key)
                page.on_show()


class ComponentsPageTests(PageTestBase):
    def test_answer_payload_is_displayed(self):
        a = self.answer("where can i buy an atlas component")
        self.assertEqual(a.page, "COMPONENTS")
        page = self.build(a.page)
        page.show_payload(a.payload)
        out = text_of(page.results)
        self.assertIn("ATLAS", out)
        self.assertIn("Platinum Bay - HUR-L5", out)
        self.assertIn("84,000", out)
        self.assertIn("Roberts Space Industries", out)
        self.assertEqual(page.search_var.get(), "Atlas")

    def test_typing_shows_suggestions_and_selecting_searches(self):
        page = self.build("COMPONENTS")
        page.search_var.set("atlas")
        page._on_typed()
        page._suggest_now()  # flush the 300 ms debounce
        items = page.suggestions.get(0, "end")
        self.assertEqual(items[0], "Atlas")
        page.suggestions.selection_set(0)
        page._on_suggestion_selected()
        self.assertIn("Platinum Bay - HUR-L5", text_of(page.results))

    def test_speak_button_speaks_result(self):
        page = self.build("COMPONENTS")
        page.show_payload("atlas")  # a plain string runs a search
        page.speak_result()
        self.assertEqual(self.ctx.spoken, ["Atlas is listed at Platinum Bay - HUR-L5, Stanton, for 84,000 a UEC."])


class ComponentsOfflineTests(PageTestBase):
    scwiki_session = offline_session()

    def test_error_is_shown(self):
        page = self.build("COMPONENTS")
        page.search_var.set("atlas")
        page.search()
        self.assertIn("Could not reach", page.status_var.get())


class ShipWeaponsPageTests(PageTestBase):
    def test_answer_payload_is_displayed(self):
        a = self.answer("where can i buy a deadbolt five ship weapon")
        page = self.build(a.page)
        page.show_payload(a.payload)
        out = text_of(page.results)
        self.assertIn("DEADBOLT V CANNON", out)
        self.assertIn("CenterMass - New Babbage", out)
        self.assertIn("Ballistic Cannon", out)


class CommoditiesPageTests(PageTestBase):
    def test_answer_payload_and_key_notice(self):
        a = self.answer("what is the price of iron")
        page = self.build(a.page)
        self.assertIn("UEX_API_KEY", page.notice_var.get())
        page.show_payload(a.payload)
        out = text_of(page.results)
        self.assertIn("IRON", out)
        self.assertIn("Admin - Endgame", out)
        self.assertIn("3,900", out)
        self.assertIn("Levski", out)

    def test_suggestions(self):
        page = self.build("COMMODITIES")
        page.search_var.set("lara")
        page._on_typed()
        page._suggest_now()
        self.assertEqual(page.suggestions.get(0, 1), ("Laranite", "Laranite (Raw)"))

    def test_unknown_commodity_message(self):
        page = self.build("COMMODITIES")
        page.search_var.set("zzqxv")
        page.search()
        self.assertIn("no commodity", page.status_var.get().lower())


class ShipFinderPageTests(PageTestBase):
    def test_answer_payload_is_displayed(self):
        a = self.answer("where can i rent a cutlass black")
        page = self.build(a.page)
        page.show_payload(a.payload)
        out = text_of(page.results)
        self.assertIn("CUTLASS BLACK", out)
        self.assertIn("New Deal - Teasa Spaceport - Lorville", out)
        self.assertIn("2,010,960 aUEC", out)
        self.assertIn("RENT", out)
        self.assertNotIn("OFFLINE SNAPSHOT", out)


class ShipFinderOfflineTests(PageTestBase):
    scwiki_session = offline_session()

    def test_snapshot_is_flagged(self):
        page = self.build("SHIP FINDER")
        page.search_var.set("Cutlass Black")
        page.search()
        self.assertIn("OFFLINE SNAPSHOT", text_of(page.results))
        self.assertIn("offline snapshot", page.status_var.get().lower())


class MiningPageTests(PageTestBase):
    def test_table_and_speak(self):
        page = self.build("MINING MODE")
        self.assertIn("Quantainium", text_of(page.table))
        page.ore_var.set("iron")
        page.speak_signatures()
        self.assertTrue(self.ctx.spoken[-1].startswith("Iron mining signatures are: 1 X, 4,270"))

    def test_reverse_signature_entry(self):
        page = self.build("MINING MODE")
        page.signature_var.set("4,280")
        page.reverse_lookup()
        out = page.reverse_var.get()
        self.assertIn("closest is Aluminium at 1 X", out)
        self.assertIn("Iron at 1 X", text_of(page.reverse_table))
        page.signature_var.set("not a number")
        page.reverse_lookup()
        self.assertIn("Enter a scanner signature", page.reverse_var.get())

    def test_signature_answer_payload(self):
        a = self.answer("what resource is nineteen thousand two hundred")
        page = self.build(a.page)
        page.show_payload(a.payload)
        self.assertEqual(page.signature_var.get(), "19,200")
        self.assertIn("Aslarite at 5 X", page.reverse_var.get())

    def test_location_answer_payload(self):
        a = self.answer("where can i mine iron")
        page = self.build(a.page)
        page.show_payload(a.payload)
        out = text_of(page.locations)
        self.assertIn("Stanton: ARC L3", out)
        self.assertIn("Pyro: Adir", out)
        self.assertIn("92", page.location_status.get())

    def test_location_button(self):
        page = self.build("MINING MODE")
        page.location_var.set("iron")
        page.find_locations()
        self.assertIn("Nyx: Glaciem Ring", text_of(page.locations))
        page.speak_locations()
        self.assertTrue(self.ctx.spoken[-1].startswith("I found 92 listed locations for Iron."))


class MiningOfflineTests(PageTestBase):
    scwiki_session = offline_session()

    def test_fallback_flagged(self):
        page = self.build("MINING MODE")
        page.location_var.set("iron")
        page.find_locations()
        self.assertIn("Pyro V-c (Adir)", text_of(page.locations))
        self.assertIn("saved", page.location_status.get().lower())


class WikiPageTests(PageTestBase):
    def test_answer_payload_is_displayed(self):
        a = self.answer("tell me about the carrack")
        page = self.build(a.page)
        page.show_payload(a.payload)
        out = text_of(page.results)
        self.assertIn("Carrack Expedition", out)
        self.assertIn("multi-crew explorer", out)

    def test_suggestions(self):
        page = self.build("WIKI")
        page.search_var.set("carrack")
        page._on_typed()
        page._suggest_now()
        self.assertEqual(page.suggestions.get(0), "Carrack")


if __name__ == "__main__":
    unittest.main()
