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

    def render(self, result: scwiki.ShipResult) -> list[str]:
        lines = [result.name.upper()]
        if result.manufacturer:
            lines.append(f"Manufacturer: {result.manufacturer}")
        if result.offline:
            lines += ["", "*** OFFLINE SNAPSHOT — not live data ***", result.note]
        lines.append("")
        lines.append(f"BUY — {len(result.purchase)} location(s), cheapest first")
        lines += [f"  • {p.line()}" for p in result.purchase] or ["  No purchase locations found."]
        lines.append("")
        lines.append(f"RENT — {len(result.rental)} location(s), cheapest first")
        lines += [f"  • {p.line()}" for p in result.rental] or ["  No rental locations found."]
        lines += ["", f"Source: {result.source}",
                  "Community data can change with patches and player-submitted shop updates."]
        return lines

    def speech(self, result: scwiki.ShipResult) -> str:
        return scwiki.ship_speech(result)

    def status_for(self, result: scwiki.ShipResult) -> str:
        if result.offline:
            return f"Showing the offline snapshot for {result.name}. {result.note}"
        return f"Loaded {len(result.purchase)} purchase and {len(result.rental)} rental location(s) for {result.name}."


PAGE_CLASS = ShipFinderPage
