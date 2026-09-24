"""GUI pages in nav order; a module that fails to import is skipped and logged, not fatal."""

PAGE_ORDER: dict[str, str] = {
    # key            module name (frontend/pages/<module>.py)
    "VOICE": "voice",
    "HOW TO": "how_to",
    "CUSTOMIZE": "customize",
    "PHRASES": "phrases",
    "KEYBINDS": "keybinds",
    "CUSTOM WORDS": "custom_words",
    "COMPONENTS": "components",
    "SHIP WEAPONS": "ship_weapons",
    "COMMODITIES": "commodities",
    "MINING MODE": "mining",
    "SHIP FINDER": "ship_finder",
    "WIKI": "wiki",
    "GUIDES": "guides",
    "ANNOUNCEMENTS": "announcements",
    "CREDIT": "credit",
}
