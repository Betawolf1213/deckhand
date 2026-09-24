"""Keyless Star Citizen Wiki lookups (items, mining, ships); failures raise ScWikiError."""
from __future__ import annotations

import difflib
import html as html_lib
import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests

from services import mining_data

WIKI_BASE = "https://starcitizen.tools"
WIKI_API = f"{WIKI_BASE}/api.php"
SHIP_API_BASE = "https://api.star-citizen.wiki/api"
USER_AGENT = "Deckhand/0.1 (offline Star Citizen voice commands)"
TIMEOUT_S = 10.0
MAX_SPOKEN = 5


class ScWikiError(RuntimeError):
    """Network, HTTP or response-format failure talking to a Star Citizen Wiki API."""


class NotFound(ScWikiError):
    """The API answered but has no matching entry."""


class FormatError(ScWikiError):
    """The API answered with data in a shape we do not understand."""


# ------------------------------------------------------------------ spoken names

_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split())}
_TEENS = {w: i + 10 for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}
_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


def _num_kind(word: str) -> str | None:
    if word in _UNITS:
        return "unit"
    if word in _TEENS:
        return "teen"
    if word in _TENS:
        return "tens"
    if word == "hundred":
        return "hundred"
    if word == "thousand":
        return "thousand"
    return None


def _word_value(word: str) -> int:
    return _UNITS.get(word, _TEENS.get(word, _TENS.get(word, 0)))


def _parse_run(words: list[str]) -> int:
    """Value of a number-word run; uncombinable groups concatenate ("forty two seventy" -> 4270)."""
    groups: list[int] = []
    total = cur = 0
    last: str | None = None
    for w in words:
        kind = _num_kind(w)
        ok = {
            "unit": last in (None, "tens", "hundred", "thousand"),
            "teen": last in (None, "hundred", "thousand"),
            "tens": last in (None, "hundred", "thousand"),
            "hundred": last in ("unit", "teen", "tens") and cur < 100,
            "thousand": last not in (None, "thousand"),
        }[kind]
        if not ok:
            groups.append(total + cur)
            total = cur = 0
            last = None
            if kind in ("hundred", "thousand"):  # dangling scale word: treat as 1 x scale
                cur = 1
                last = "unit"
        if kind in ("unit", "teen", "tens"):
            cur += _word_value(w)
        elif kind == "hundred":
            cur *= 100
        elif kind == "thousand":
            total += cur * 1000
            cur = 0
        last = kind
    groups.append(total + cur)
    if len(groups) == 1:
        return groups[0]
    return int("".join(str(g) for g in groups))


def _number_runs(tokens: list[str]) -> list[tuple[int, int, int]]:
    """[(start, end_exclusive, value)] for runs of number words in lowercase tokens."""
    runs: list[tuple[int, int, int]] = []
    i = 0
    while i < len(tokens):
        if _num_kind(tokens[i]) is None:
            i += 1
            continue
        j = i
        words: list[str] = []
        while j < len(tokens):
            t = tokens[j]
            if _num_kind(t) is not None:
                words.append(t)
                j += 1
            elif (t == "and" and words and _num_kind(words[-1]) in ("hundred", "thousand")
                  and j + 1 < len(tokens) and _num_kind(tokens[j + 1]) is not None):
                j += 1
            else:
                break
        runs.append((i, j, _parse_run(words)))
        i = j
    return runs


def spoken_numbers(text: str) -> list[int]:
    """Numbers spoken as words, in order: 'four thousand two hundred seventy' -> [4270]."""
    tokens = re.findall(r"[a-z]+", (text or "").lower())
    return [v for _, _, v in _number_runs(tokens)]


def normalize_spoken_name(text: str, roman: bool = True) -> str:
    """Spoken item name -> wiki search text ('a d four b' -> 'AD4B'; roman=True: 'five' -> 'V')."""
    raw = (text or "").split()
    low = [t.lower() for t in raw]
    tokens: list[tuple[str, str, int | None]] = []  # (kind, text, small_value)
    runs = {s: (e, v) for s, e, v in _number_runs(low)}
    i = 0
    while i < len(raw):
        if i in runs:
            end, value = runs[i]
            small = value if (end - i == 1 and 1 <= value <= 20) else None
            tokens.append(("num", str(value), small))
            i = end
            continue
        kind = "letter" if re.fullmatch(r"[A-Za-z]", raw[i]) else "word"
        tokens.append((kind, raw[i], None))
        i += 1

    out: list[str] = []
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and tokens[j][0] in ("letter", "num"):
            j += 1
        run = tokens[i:j]
        if len(run) >= 2 and any(k == "letter" for k, _, _ in run):
            out.append("".join(t.upper() for _, t, _ in run))
            i = j
            continue
        kind, word, small = tokens[i]
        if kind == "num" and roman and small is not None:
            out.append(_ROMAN[small])
        else:
            out.append(word)
        i += 1
    return " ".join(out)


# ------------------------------------------------------------------ html helpers

_STYLE_RE = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.S | re.I)


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", _STYLE_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _tables(page_html: str) -> list[tuple[str, list[list[str]]]]:
    """[(caption, rows-of-cleaned-cells)] for every <table> in the page."""
    out = []
    body = _STYLE_RE.sub(" ", page_html)
    for table in re.findall(r"<table[^>]*>(.*?)</table>", body, flags=re.S | re.I):
        cap = re.search(r"<caption[^>]*>(.*?)</caption>", table, flags=re.S | re.I)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S | re.I):
            cells = [_clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
            if cells:
                rows.append(cells)
        out.append((_clean(cap.group(1)) if cap else "", rows))
    return out


def page_url(title: str) -> str:
    return f"{WIKI_BASE}/{urllib.parse.quote(title.replace(' ', '_'))}"


# ------------------------------------------------------------------ data types


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


@dataclass(frozen=True)
class ShopListing:
    system: str
    location: str
    price: str  # as shown on the wiki, e.g. "84,000"

    @property
    def price_value(self) -> int | None:
        return _to_int(self.price)


@dataclass
class ItemResult:
    name: str
    url: str
    kind: str  # "component" | "ship weapon"
    locations: list[ShopListing]
    specs: list[tuple[str, str]]

    @property
    def is_vehicle(self) -> bool:
        return is_vehicle_specs(self.specs)

    def lines(self) -> list[str]:
        if not self.locations:
            return ["No current Wiki shop locations are listed."]
        return [f"{l.location} — {l.price} aUEC ({l.system})" for l in self.locations]


@dataclass(frozen=True)
class MiningLocation:
    system: str
    body: str
    type: str
    spawn: str    # "17.9%"
    quality: str  # "245–1000"

    @property
    def spawn_value(self) -> float:
        try:
            return float(re.sub(r"[^\d.]", "", self.spawn) or 0)
        except ValueError:
            return 0.0

    def line(self) -> str:
        return f"{self.system}: {self.body} ({self.type}) — {self.spawn} spawn • quality {self.quality}"


@dataclass
class MiningResult:
    resource: str
    url: str
    locations: list[MiningLocation] = field(default_factory=list)
    offline: bool = False
    fallback: list[str] = field(default_factory=list)
    note: str = ""

    def lines(self) -> list[str]:
        return list(self.fallback) if self.offline else [l.line() for l in self.locations]


@dataclass(frozen=True)
class VehiclePrice:
    kind: str  # "buy" | "rent"
    terminal: str
    location: str
    system: str
    price: int

    def line(self) -> str:
        where = " • ".join(p for p in (self.terminal, self.location, self.system) if p)
        return f"{where} • {self.price:,} aUEC"


@dataclass
class ShipResult:
    name: str
    manufacturer: str
    purchase: list[VehiclePrice]
    rental: list[VehiclePrice]
    offline: bool = False
    note: str = ""
    source: str = SHIP_API_BASE

    def lines(self) -> list[str]:
        out = ["BUY"] + ([f"  {p.line()}" for p in self.purchase] or ["  No purchase locations listed."])
        out += ["RENT"] + ([f"  {p.line()}" for p in self.rental] or ["  No rental locations listed."])
        return out


# ------------------------------------------------------------------ parsers


def parse_shop_table(page_html: str, column: str = "buy") -> list[ShopListing]:
    """Rows of the wiki's 'System | Location | Buy' (or '... | Rent') table."""
    column = column.lower()
    for _cap, rows in _tables(page_html):
        if not rows:
            continue
        header = [c.lower() for c in rows[0]]
        if not {"system", "location", column} <= set(header):
            continue
        si, li, pi = header.index("system"), header.index("location"), header.index(column)
        need = max(si, li, pi)
        return [ShopListing(r[si], r[li], r[pi]) for r in rows[1:] if len(r) > need and r[li]]
    return []


_SPEC_RE = re.compile(
    r'<dt[^>]*class="[^"]*t-infobox-item-label[^"]*"[^>]*>(.*?)</dt>\s*'
    r'<dd[^>]*class="[^"]*t-infobox-item-(?:value|content)[^"]*"[^>]*>(.*?)</dd>',
    re.S | re.I,
)


def parse_specs(page_html: str, limit: int = 40) -> list[tuple[str, str]]:
    specs = []
    for label, value in _SPEC_RE.findall(_STYLE_RE.sub(" ", page_html)):
        label, value = _clean(label), _clean(value)
        if label and value:
            specs.append((label, value))
    return specs[:limit]


_VEHICLE_TYPES = {"spacecraft", "ground vehicle", "gravlev", "vehicle"}


def is_vehicle_specs(specs: list[tuple[str, str]]) -> bool:
    labels = {k.lower(): v.lower() for k, v in specs}
    return "career" in labels or labels.get("type", "") in _VEHICLE_TYPES


def parse_mining_tables(page_html: str) -> list[MiningLocation]:
    """Every 'Body | Type | Spawn % | Quality' table, captioned '<System> System'."""
    out: list[MiningLocation] = []
    for caption, rows in _tables(page_html):
        if not rows or not caption or rows[0][0].lower() != "body":
            continue
        system = re.sub(r"\s+System\s*$", "", caption).strip()
        for r in rows[1:]:
            if len(r) < 4 or not r[0]:
                continue
            loc = MiningLocation(system, r[0], r[1].split("_")[0], r[2], r[3])
            if loc not in out:
                out.append(loc)
    return out


# ------------------------------------------------------------------ ranking

_WEAPON_WORDS = ("cannon", "gatling", "repeater", "scattergun", "gun", "missile", "torpedo",
                 "weapon", "laser", "rocket", "launcher", "driver")
_MANUFACTURER_WORDS = {"aegis", "anvil", "aopoa", "argo", "banu", "crusader", "cnou", "consolidated",
                       "outland", "drake", "esperia", "gatac", "greycat", "kruger", "misc", "mirai",
                       "origin", "rsi", "roberts", "space", "industries", "tumbril", "vanduul"}


def rank_titles(query: str, titles: list[str], ship_weapon: bool = False) -> list[str]:
    q = query.lower().strip()

    def key(title: str):
        t = title.lower()
        return (
            ship_weapon and not any(w in t for w in _WEAPON_WORDS),
            "/" in t,
            t != q,
            q not in t,
            t.find(q) if q in t else len(t),
            -difflib.SequenceMatcher(None, q, t).ratio(),
            len(t),
        )

    return sorted(dict.fromkeys(titles), key=key)


def _vehicle_score(query: str, vehicle: dict) -> tuple:
    q = query.lower().strip()
    name = str(vehicle.get("name") or "").lower()
    bare = " ".join(w for w in name.split() if w not in _MANUFACTURER_WORDS)
    ratio = max(difflib.SequenceMatcher(None, q, name).ratio(),
                difflib.SequenceMatcher(None, q, bare).ratio())
    prices = vehicle.get("uex_prices") if isinstance(vehicle.get("uex_prices"), dict) else {}
    count = len(prices.get("purchase") or []) + len(prices.get("rental") or [])
    return (0 if q in (name, bare) else 1, -round(ratio, 3), -count, len(name))


# ------------------------------------------------------------------ ship helpers

CUTLASS_BLACK_SNAPSHOT = ShipResult(
    name="Cutlass Black",
    manufacturer="Drake Interplanetary",
    purchase=[VehiclePrice("buy", "New Deal - Teasa Spaceport - Lorville", "Lorville", "Stanton", 2010960)],
    rental=[
        VehiclePrice("rent", "Vantage Rentals - Lorville", "Lorville", "Stanton", 50274),
        VehiclePrice("rent", "Traveler Rentals (Baijini / Tressler) and other Vantage locations", "", "Stanton", 52920),
    ],
    offline=True,
    note="Offline snapshot (4.10) — live ship data was unavailable.",
    source="offline snapshot",
)


def _snapshot_for(*names: str) -> ShipResult | None:
    for n in names:
        if re.sub(r"\s+", " ", (n or "").lower()).strip() in ("cutlass black", "drake cutlass black"):
            return ShipResult(**{**CUTLASS_BLACK_SNAPSHOT.__dict__,
                                 "purchase": list(CUTLASS_BLACK_SNAPSHOT.purchase),
                                 "rental": list(CUTLASS_BLACK_SNAPSHOT.rental)})
    return None


def parse_vehicle_prices(vehicle: dict) -> tuple[list[VehiclePrice], list[VehiclePrice]]:
    prices = vehicle.get("uex_prices")
    if not isinstance(prices, dict) or not isinstance(prices.get("purchase", []), list) \
            or not isinstance(prices.get("rental", []), list):
        raise FormatError("The ship API response no longer contains 'uex_prices'.")

    def conv(rows: list, kind: str, key: str) -> list[VehiclePrice]:
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(key)
            if not isinstance(value, (int, float)) or value <= 0:
                continue
            loc = row.get("starmap_location") if isinstance(row.get("starmap_location"), dict) else {}
            out.append(VehiclePrice(kind, str(row.get("terminal_name") or "").strip(),
                                    str(loc.get("name") or "").strip(),
                                    str(loc.get("star_system_name") or "").strip(), int(value)))
        return sorted(out, key=lambda p: p.price)

    return conv(prices.get("purchase") or [], "buy", "price_buy"), conv(prices.get("rental") or [], "rent", "price_rent")


# ------------------------------------------------------------------ speech


def _join(items: list[str]) -> str:
    return ", ".join(items)


def item_speech(result: ItemResult) -> str:
    if not result.locations:
        return f"I found {result.name}, but the Star Citizen Wiki has no current buy locations listed."
    spoken = [f"{l.location}, {l.system}, for {l.price} a UEC" for l in result.locations[:MAX_SPOKEN]]
    return f"{result.name} is listed at {_join(spoken)}."


def mining_speech(result: MiningResult) -> str:
    if result.offline:
        return (f"Live lookup failed. Known {result.resource} mining hotspots include "
                f"{_join(result.fallback[:MAX_SPOKEN])}.")
    if not result.locations:
        return f"I could not find mining locations for {result.resource}."
    best = sorted(result.locations, key=lambda l: -l.spawn_value)[:MAX_SPOKEN]
    spoken = [f"{l.body} in {l.system}, {l.spawn_value:g} percent" for l in best]
    return (f"I found {len(result.locations)} listed locations for {result.resource}. "
            f"The best spawn chances are {_join(spoken)}.")


def ship_speech(result: ShipResult) -> str:
    parts = []
    if result.offline:
        parts.append("Live ship data is unavailable, using the offline snapshot.")
    parts.append(f"{result.name}.")
    if result.purchase:
        parts.append("Buy at " + _join(f"{p.terminal} for {p.price:,} a UEC" for p in result.purchase[:3]) + ".")
    else:
        parts.append("No purchase locations are listed.")
    if result.rental:
        parts.append("Rent at " + _join(f"{p.terminal} for {p.price:,} a UEC" for p in result.rental[:2]) + ".")
    else:
        parts.append("No rental locations are listed.")
    return " ".join(parts)


# ------------------------------------------------------------------ client


class ScWikiClient:
    def __init__(self, session: requests.Session | Any | None = None, timeout_s: float = TIMEOUT_S) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._timeout = timeout_s
        self._lock = threading.Lock()
        self._suggest_cache: dict[tuple[str, str], list[str]] = {}
        self._vehicle_cache: dict[str, list[dict]] = {}

    # ---- transport

    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        try:
            r = self._session.get(url, params=params, timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise ScWikiError(f"Could not reach {urllib.parse.urlsplit(url).netloc}: {e}") from e
        except ValueError as e:
            raise FormatError(f"{urllib.parse.urlsplit(url).netloc} returned invalid JSON") from e

    def _wiki(self, **params: Any) -> Any:
        params.setdefault("format", "json")
        return self._get_json(WIKI_API, params)

    # ---- starcitizen.tools

    def search_titles(self, query: str, limit: int = 20) -> list[str]:
        query = query.strip()
        if not query:
            return []
        data = self._wiki(action="opensearch", search=query, limit=limit, namespace=0)
        if not isinstance(data, list):
            raise FormatError("Unexpected opensearch response from starcitizen.tools")
        titles = [str(t) for t in (data[1] if len(data) > 1 else [])]
        if titles:
            return titles
        # OpenSearch is prefix-based; full-text search catches partial series names.
        data = self._wiki(action="query", list="search", srsearch=query, srlimit=limit, srinfo="suggestion")
        q = data.get("query", {}) if isinstance(data, dict) else {}
        titles = [str(h.get("title", "")) for h in q.get("search", []) if h.get("title")]
        suggestion = (q.get("searchinfo") or {}).get("suggestion")
        if not titles and suggestion and suggestion.lower() != query.lower():
            data = self._wiki(action="opensearch", search=suggestion, limit=limit, namespace=0)
            titles = [str(t) for t in (data[1] if isinstance(data, list) and len(data) > 1 else [])]
        return titles

    def fetch_html(self, title: str) -> str:
        data = self._wiki(action="parse", page=title, prop="text", formatversion=2, redirects=1)
        if not isinstance(data, dict):
            raise FormatError("Unexpected parse response from starcitizen.tools")
        if "error" in data:
            info = (data["error"] or {}).get("info", "page not found")
            raise NotFound(f'Star Citizen Wiki has no page "{title}" ({info}).')
        text = (data.get("parse") or {}).get("text")
        if isinstance(text, dict):  # formatversion=1 shape
            text = text.get("*")
        if not isinstance(text, str):
            raise FormatError(f'No page content returned for "{title}".')
        return text

    def _suggest(self, query: str, ship_weapon: bool, limit: int) -> list[str]:
        normalized = normalize_spoken_name(query)
        key = ("weapon" if ship_weapon else "component", normalized.lower())
        with self._lock:
            if key in self._suggest_cache:
                return self._suggest_cache[key][:limit]
        ranked = rank_titles(normalized, self.search_titles(normalized), ship_weapon)
        with self._lock:
            self._suggest_cache[key] = ranked
        return ranked[:limit]

    def suggest_components(self, query: str, limit: int = 10) -> list[str]:
        return self._suggest(query, False, limit)

    def suggest_ship_weapons(self, query: str, limit: int = 10) -> list[str]:
        return self._suggest(query, True, limit)

    def _search_item(self, query: str, kind: str, ship_weapon: bool) -> ItemResult:
        ranked = self._suggest(query, ship_weapon, 20)
        if not ranked:
            raise NotFound(f'Star Citizen Wiki found no {kind} matching "{query}".')
        name = ranked[0]
        page_html = self.fetch_html(name)
        return ItemResult(name, page_url(name), kind, parse_shop_table(page_html), parse_specs(page_html))

    def search_component(self, query: str) -> ItemResult:
        return self._search_item(query, "component", False)

    def search_ship_weapon(self, query: str) -> ItemResult:
        return self._search_item(query, "ship weapon", True)

    # ---- mining

    def fetch_mining_locations(self, resource: str) -> MiningResult:
        ore = mining_data.normalize_ore(resource)
        title = mining_data.wiki_title(ore) if ore else resource.strip().title()
        if not title:
            raise NotFound("No mining resource given.")
        locations = parse_mining_tables(self.fetch_html(title))
        if not locations:
            raise NotFound(f"The Star Citizen Wiki lists no mining locations for {title}.")
        return MiningResult(title, page_url(title), locations)

    def lookup_mining_locations(self, resource: str) -> MiningResult:
        """Live lookup; on failure fall back to the saved hotspot list when one exists."""
        try:
            return self.fetch_mining_locations(resource)
        except ScWikiError as e:
            ore = mining_data.normalize_ore(resource)
            fallback = mining_data.fallback_locations(ore) if ore else []
            if not fallback:
                raise
            title = mining_data.wiki_title(ore)
            return MiningResult(title, page_url(title), [], offline=True, fallback=fallback,
                                note=f"Live lookup failed ({e}). Showing the saved hotspot list.")

    # ---- ships (api.star-citizen.wiki)

    def _vehicles(self, query: str) -> list[dict]:
        key = query.lower().strip()
        with self._lock:
            if key in self._vehicle_cache:
                return self._vehicle_cache[key]
        data = self._get_json(f"{SHIP_API_BASE}/vehicles", {"filter[name]": query, "page[size]": 20})
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise FormatError("Unexpected /vehicles response from api.star-citizen.wiki")
        rows = [v for v in data["data"] if isinstance(v, dict) and v.get("name")]
        with self._lock:
            self._vehicle_cache[key] = rows
        return rows

    def _vehicle_candidates(self, query: str) -> tuple[str, list[dict]]:
        q = normalize_spoken_name(query, roman=False).strip()
        words = q.split()
        variants = [q, " ".join(w for w in words if w.lower() not in _MANUFACTURER_WORDS)]
        if len(words) > 1:
            variants.append(max(words, key=len))
        for v in dict.fromkeys(x for x in variants if x):
            rows = self._vehicles(v)
            if rows:
                return q, sorted(rows, key=lambda r: _vehicle_score(q, r))
        return q, []

    def suggest_ships(self, query: str, limit: int = 10) -> list[str]:
        _q, rows = self._vehicle_candidates(query)
        return list(dict.fromkeys(str(r["name"]) for r in rows))[:limit]

    def find_ship(self, query: str) -> ShipResult:
        try:
            q, rows = self._vehicle_candidates(query)
        except FormatError:
            snap = _snapshot_for(query)
            if snap:
                return snap
            raise
        except ScWikiError as e:
            snap = _snapshot_for(query)
            if snap:
                snap.note = f"Offline snapshot (4.10) — live lookup failed: {e}"
                return snap
            raise
        if not rows:
            raise NotFound(f'No vehicle found for "{query}".')
        vehicle = rows[0]
        name = str(vehicle.get("name") or query)
        manufacturer = vehicle.get("manufacturer")
        if isinstance(manufacturer, dict):
            manufacturer = manufacturer.get("name", "")
        try:
            purchase, rental = parse_vehicle_prices(vehicle)
        except FormatError:
            snap = _snapshot_for(name, query)
            if snap:
                snap.note = "Offline snapshot (4.10) — the live price format was not recognised."
                return snap
            raise
        if not purchase and not rental:
            snap = _snapshot_for(name)
            if snap:
                snap.note = "Offline snapshot (4.10) — the live data listed no prices."
                return snap
        return ShipResult(name, str(manufacturer or ""), purchase, rental)


# ------------------------------------------------------------------ module-level API

_default: ScWikiClient | None = None
_default_lock = threading.Lock()


def default_client() -> ScWikiClient:
    global _default
    with _default_lock:
        if _default is None:
            _default = ScWikiClient()
        return _default


def suggest_components(query: str, limit: int = 10) -> list[str]:
    return default_client().suggest_components(query, limit)


def suggest_ship_weapons(query: str, limit: int = 10) -> list[str]:
    return default_client().suggest_ship_weapons(query, limit)


def suggest_ships(query: str, limit: int = 10) -> list[str]:
    return default_client().suggest_ships(query, limit)


def search_component(query: str) -> ItemResult:
    return default_client().search_component(query)


def search_ship_weapon(query: str) -> ItemResult:
    return default_client().search_ship_weapon(query)


def lookup_mining_locations(resource: str) -> MiningResult:
    return default_client().lookup_mining_locations(resource)


def find_ship(query: str) -> ShipResult:
    return default_client().find_ship(query)
