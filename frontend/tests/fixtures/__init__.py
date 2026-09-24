"""Recorded API responses + a fake requests.Session for offline lookup tests.

Every *.json file here is a real response recorded once from the live API
(bulky fields trimmed; see each test for which endpoint it stands in for).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import requests

FIXTURES = Path(__file__).resolve().parent


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status

    def json(self) -> Any:
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """route(url, params) -> fixture file name | dict/list payload | Exception | None (=404)."""

    def __init__(self, route: Callable[[str, dict], Any]) -> None:
        self.route = route
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, timeout: float | None = None, **_kw: Any) -> FakeResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        target = self.route(url, params)
        if isinstance(target, Exception):
            raise target
        if target is None:
            return FakeResponse({}, 404)
        if isinstance(target, str):
            return FakeResponse(load(target))
        return FakeResponse(target)


def offline_session() -> FakeSession:
    return FakeSession(lambda url, params: requests.ConnectionError("offline (test)"))


def uex_route(url: str, params: dict) -> Any:
    """UEX 2.0: /commodities and /commodities_prices (only Iron, id 44, is recorded)."""
    if url.endswith("/commodities"):
        return "uex_commodities.json"
    if url.endswith("/commodities_prices"):
        if int(params.get("id_commodity", 0)) == 44:
            return "uex_prices_iron.json"
        return {"status": "ok", "data": []}
    return None


def wiki_route(url: str, params: dict) -> Any:
    """starcitizen.tools search/extract calls used by services.wiki (Carrack recorded)."""
    if params.get("action") == "opensearch":
        return "wiki_opensearch_carrack.json"
    if params.get("list") == "search":
        if "carrack" in str(params.get("srsearch", "")).lower():
            return "wiki_search_carrack.json"
        return {"query": {"search": []}}
    if params.get("prop") == "extracts":
        if params.get("titles") == "Carrack":
            return "wiki_extract_carrack.json"
        return {"query": {"pages": {"-1": {"missing": ""}}}}
    return None


def scwiki_route(url: str, params: dict) -> Any:
    """Routes for starcitizen.tools api.php and api.star-citizen.wiki used by the fixtures."""
    if "api.star-citizen.wiki" in url:
        name = str(params.get("filter[name]", "")).lower()
        if "cutlass black" in name:
            return "scapi_vehicles_cutlass_black.json"
        if "prospector" in name:
            return "scapi_vehicles_prospector.json"
        return {"data": []}
    action = params.get("action")
    if action == "opensearch":
        q = str(params.get("search", "")).lower()
        for key, fx in (("atlas", "atlas"), ("deadbolt v", "deadbolt_v"),
                        ("cutlass black", "cutlass_black"), ("iron", "iron")):
            if q == key:
                return f"scwiki_opensearch_{fx}.json"
        return "scwiki_opensearch_empty.json"
    if action == "query" and params.get("list") == "search":
        return {"batchcomplete": "", "query": {"searchinfo": {"totalhits": 0}, "search": []}}
    if action == "parse":
        page = str(params.get("page", ""))
        fx = {"Atlas": "atlas", "Deadbolt V Cannon": "deadbolt_v_cannon",
              "Iron": "iron", "Cutlass Black": "cutlass_black"}.get(page)
        if fx:
            return f"scwiki_parse_{fx}.json"
        return {"error": {"code": "missingtitle", "info": "The page you specified doesn't exist."}}
    return None
