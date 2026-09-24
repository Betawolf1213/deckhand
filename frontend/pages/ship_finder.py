"""SHIP FINDER page — ship purchase and rental locations/prices (api.star-citizen.wiki)."""
from __future__ import annotations

from pages.components import LookupPage
from services import scwiki


class ShipFinderPage(LookupPage):
    title = "SHIP FINDER"
    heading = "SHIP FINDER"
    description = ("Search a ship to see in-game purchase and rental locations and prices from the Star Citizen "
                   "Wiki community API. Voice: \"where can I rent a Cutlass Black\".")
    hint = "Type a ship name, for example Cutlass Black, Prospector or Avenger Titan."
    default_query = "Cutlass Black"
    min_suggest_chars = 3  # vehicle records are large; do not query on every letter
    result_types = (scwiki.ShipResult,)

    def suggest(self, query: str) -> list[str]:
        return scwiki.suggest_ships(query)

    def lookup(self, query: str) -> scwiki.ShipResult:
        return scwiki.find_ship(query)

    def render(self, r: scwiki.ShipResult) -> list[str]:
        lines = [r.name.upper()]
        if r.manufacturer:
            lines.append(f"Manufacturer: {r.manufacturer}")
        if r.offline:
            lines += ["", "*** OFFLINE SNAPSHOT — not live data ***", r.note]
        lines.append("")
        lines.append(f"BUY — {len(r.purchase)} location(s), cheapest first")
        lines += [f"  • {p.line()}" for p in r.purchase] or ["  No purchase locations found."]
        lines.append("")
        lines.append(f"RENT — {len(r.rental)} location(s), cheapest first")
        lines += [f"  • {p.line()}" for p in r.rental] or ["  No rental locations found."]
        lines += ["", f"Source: {r.source}",
                  "Community data can change with patches and player-submitted shop updates."]
        return lines

    def speech(self, r: scwiki.ShipResult) -> str:
        return scwiki.ship_speech(r)

    def status_for(self, r: scwiki.ShipResult) -> str:
        if r.offline:
            return f"Showing the offline snapshot for {r.name}. {r.note}"
        return f"Loaded {len(r.purchase)} purchase and {len(r.rental)} rental location(s) for {r.name}."


PAGE_CLASS = ShipFinderPage
