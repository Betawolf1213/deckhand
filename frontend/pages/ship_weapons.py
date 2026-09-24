"""SHIP WEAPONS page — Star Citizen Wiki vehicle-weapon lookup (spoken numerals work)."""
from __future__ import annotations

from pages.components import ComponentsPage
from services import scwiki


class ShipWeaponsPage(ComponentsPage):
    title = "SHIP WEAPONS"
    heading = "SHIP WEAPONS"
    description = ("Search the Star Citizen Wiki for ship-weapon locations, prices and statistics. "
                   "Spoken numerals work: \"where can I buy a Deadbolt five ship weapon\" finds Deadbolt V Cannon.")
    hint = "Type a vehicle weapon name, for example AD4B, Greatsword or Deadbolt V."
    kind_label = "STAR CITIZEN WIKI SHIP WEAPON DATA"
    specs_heading = "WEAPON STATISTICS"

    def suggest(self, query: str) -> list[str]:
        return scwiki.suggest_ship_weapons(query)

    def lookup(self, query: str) -> scwiki.ItemResult:
        return scwiki.search_ship_weapon(query)


PAGE_CLASS = ShipWeaponsPage
