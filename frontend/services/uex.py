"""UEX v2 commodity prices; UEX_API_KEY from .env is optional for GUI lookups and never logged."""
from __future__ import annotations

import difflib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

BASE_URL = "https://api.uexcorp.space/2.0"
USER_AGENT = "Deckhand/0.1"

PLACEHOLDER = "REPLACE_WITH_YOUR_UEX_V2_API_KEY"


class UexError(RuntimeError):
    """Network, HTTP or response-format failure talking to UEX."""


class UexKeyMissing(UexError):
    """Raised by the strict constructor if UEX_API_KEY is unset or still the placeholder."""


def _key() -> str:
    key = os.getenv("UEX_API_KEY", "").strip()
    return "" if key == PLACEHOLDER else key


def strict_key() -> str:
    # key is externally-provided; deployer sets UEX_API_KEY in .env — see README
    key = _key()
    if not key:
        raise UexKeyMissing(
            "UEX_API_KEY is not set.\n\n"
            "The UEX v2.0 API requires a key. Copy `.env.example` to `.env` in "
            "the project root and paste the key you were given.\n\n"
            "  copy .env.example .env\n"
            "  notepad .env\n\n"
            "See README.md for details."
        )
    return key




def key_status() -> str | None:
    """None when a key is configured, else a one-line notice for the GUI."""
    if _key():
        return None
    return ("UEX_API_KEY is not set in .env — using anonymous public UEX access "
            "(may be rate-limited). Add your key to .env for reliable lookups.")


@dataclass
class Listing:
    location: str       # e.g. "Area18 - Terminal"
    price_buy: float | None
    price_sell: float | None
    scu_buy: int | None
    scu_sell: int | None
    system: str = ""    # star system, e.g. "Stanton"
    planet: str = ""


@dataclass
class Commodity:
    id: int
    name: str
    code: str


@dataclass
class CommodityResult:
    """Full commodity lookup, used as the COMMODITIES page payload."""
    commodity: Commodity
    listings: list[Listing]
    note: str = ""
    matches: list[str] = field(default_factory=list)

    def sell_to(self, n: int | None = None) -> list[Listing]:
        """Terminals that buy from you, best price first."""
        rows = sorted((l for l in self.listings if l.price_sell), key=lambda l: -(l.price_sell or 0))
        return rows[:n] if n else rows

    def buy_from(self, n: int | None = None) -> list[Listing]:
        """Terminals that sell to you, cheapest first."""
        rows = sorted((l for l in self.listings if l.price_buy), key=lambda l: l.price_buy or 0)
        return rows[:n] if n else rows


class Uex:
    def __init__(self, session: requests.Session | None = None, timeout_s: float = 15.0,
                 require_key: bool = True) -> None:
        key = strict_key() if require_key else _key()  # strict: fail loudly at construct time
        self.anonymous = not key
        self._session = session or requests.Session()
        self._session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
        if key:
            self._session.headers["Authorization"] = f"Bearer {key}"
        self._timeout = timeout_s
        self._commodity_cache: list[Commodity] | None = None
        self._commodity_cache_ts: float = 0.0

    # ---- Commodities ----

    def list_commodities(self) -> list[Commodity]:
        # Refresh once an hour; commodity master list is stable per patch.
        if self._commodity_cache and time.time() - self._commodity_cache_ts < 3600:
            return self._commodity_cache
        data = self._get("/commodities")
        out: list[Commodity] = []
        for row in data.get("data", []) or []:
            out.append(Commodity(
                id=int(row.get("id", 0)),
                name=str(row.get("name", "")),
                code=str(row.get("code", "")),
            ))
        self._commodity_cache = out
        self._commodity_cache_ts = time.time()
        return out

    def suggest(self, query: str, limit: int = 10) -> list[str]:
        """Commodity names for a partial/misheard query: prefix, then substring, then fuzzy."""
        q = query.strip().lower()
        if not q:
            return []
        names = [c.name for c in self.list_commodities()]
        prefix = [n for n in names if n.lower().startswith(q)]
        contains = [n for n in names if q in n.lower() and n not in prefix]
        fuzzy = difflib.get_close_matches(q, [n.lower() for n in names], n=limit, cutoff=0.6)
        fuzzy_names = [next(x for x in names if x.lower() == f) for f in fuzzy]
        ranked = sorted(prefix, key=len) + sorted(contains, key=len) + fuzzy_names
        return list(dict.fromkeys(ranked))[:limit]

    def find_commodity(self, query: str) -> Commodity | None:
        """Case-insensitive exact match, then substring, then fuzzy (misheard speech)."""
        q = query.strip().lower()
        if not q:
            return None
        commodities = self.list_commodities()
        for c in commodities:
            if c.name.lower() == q or c.code.lower() == q:
                return c
        for c in sorted(commodities, key=lambda c: len(c.name)):
            if q in c.name.lower():
                return c
        lowered = {c.name.lower(): c for c in commodities}
        hit = difflib.get_close_matches(q, list(lowered), n=1, cutoff=0.72)
        if not hit:
            squashed = {re.sub(r"[^a-z]", "", k): v for k, v in lowered.items()}
            hit2 = difflib.get_close_matches(re.sub(r"[^a-z]", "", q), list(squashed), n=1, cutoff=0.8)
            return squashed[hit2[0]] if hit2 else None
        return lowered[hit[0]]

    def prices_for(self, commodity_id: int) -> list[Listing]:
        data = self._get("/commodities_prices", params={"id_commodity": commodity_id})
        rows: list[Listing] = []
        for row in data.get("data", []) or []:
            rows.append(Listing(
                location=str(row.get("terminal_name") or row.get("terminal") or ""),
                price_buy=_num(row.get("price_buy")),
                price_sell=_num(row.get("price_sell")),
                scu_buy=_int(row.get("scu_buy")),
                scu_sell=_int(row.get("scu_sell")),
                system=str(row.get("star_system_name") or ""),
                planet=str(row.get("planet_name") or ""),
            ))
        return rows

    def search(self, query: str) -> tuple[Commodity, list[Listing]] | None:
        c = self.find_commodity(query)
        if c is None:
            return None
        return c, self.prices_for(c.id)

    def lookup(self, query: str) -> CommodityResult | None:
        """search() packaged for pages/questions, with the key notice attached."""
        found = self.search(query)
        if found is None:
            return None
        commodity, listings = found
        note = key_status() if self.anonymous else ""
        return CommodityResult(commodity, listings, note or "", self.suggest(query))

    # ---- Internal ----

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = BASE_URL + path
        try:
            r = self._session.get(url, params=params, timeout=self._timeout)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            # str(e) never contains request headers, so the key cannot leak here.
            raise UexError(f"Could not reach UEX ({path}): {e}") from e
        except ValueError as e:
            raise UexError(f"UEX returned invalid JSON for {path}") from e
        if not isinstance(data, dict):
            raise UexError(f"Unexpected UEX response for {path}")
        if data.get("status") not in (None, "ok"):
            raise UexError(f"UEX error for {path}: {data.get('status')}")
        return data


def price_speech(result: CommodityResult) -> str:
    name = result.commodity.name
    sell = result.sell_to(3)
    buy = result.buy_from(2)
    parts = []
    if sell:
        parts.append(f"{name} sells best at "
                     + ", ".join(f"{l.location} for {l.price_sell:,.0f}" for l in sell) + " a UEC per SCU.")
    if buy:
        parts.append("Cheapest to buy at " + ", ".join(f"{l.location} for {l.price_buy:,.0f}" for l in buy) + ".")
    if not parts:
        return f"UEX has no current prices listed for {name}."
    return " ".join(parts)


_client: Uex | None = None
_client_lock = threading.Lock()


def get_client() -> Uex:
    """Shared lookup client (anonymous if no key). Rebuilt if the key changes."""
    global _client
    with _client_lock:
        if _client is None or _client.anonymous != (not _key()):
            _client = Uex(require_key=False)
        return _client


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
