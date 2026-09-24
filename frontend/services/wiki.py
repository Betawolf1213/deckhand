"""MediaWiki API client for starcitizen.tools (no HTML scraping); failures raise WikiError."""
from __future__ import annotations

import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests

BASE_URL = "https://starcitizen.tools/api.php"
PAGE_BASE = "https://starcitizen.tools"
TIMEOUT_S = 20.0
USER_AGENT = "Deckhand/0.1 (offline Star Citizen voice commands)"


class WikiError(RuntimeError):
    """Network, HTTP or response-format failure talking to starcitizen.tools."""


@dataclass
class SearchHit:
    title: str
    snippet: str
    pageid: int


@dataclass
class WikiResult:
    """Search hits + lead summary of the best hit (WIKI page payload)."""
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    title: str = ""
    summary: str = ""

    @property
    def url(self) -> str:
        return page_url(self.title) if self.title else ""


def page_url(title: str) -> str:
    return f"{PAGE_BASE}/{urllib.parse.quote(title.replace(' ', '_'))}"


class Wiki:
    def __init__(self, session: requests.Session | None = None, timeout_s: float = TIMEOUT_S) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._timeout = timeout_s
        self._suggest_cache: dict[str, list[str]] = {}

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        data = self._get({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
        })
        hits: list[SearchHit] = []
        for row in data.get("query", {}).get("search", []):
            hits.append(SearchHit(
                title=row.get("title", ""),
                snippet=_strip_tags(row.get("snippet", "")),
                pageid=int(row.get("pageid", 0)),
            ))
        return hits

    def suggest(self, query: str, limit: int = 10) -> list[str]:
        """Title completions (opensearch), cached per query."""
        q = query.strip()
        if not q:
            return []
        key = q.lower()
        if key not in self._suggest_cache:
            data = self._get({"action": "opensearch", "search": q, "limit": limit,
                              "namespace": 0, "format": "json"})
            titles = data[1] if isinstance(data, list) and len(data) > 1 else []
            self._suggest_cache[key] = [str(t) for t in titles]
        return self._suggest_cache[key][:limit]

    def page_summary(self, title: str) -> str | None:
        """Plain-text lead paragraphs — ~500 chars typical."""
        data = self._get({
            "action": "query",
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "titles": title,
            "format": "json",
        })
        pages = data.get("query", {}).get("pages", {})
        for _, page in pages.items():
            extract = page.get("extract")
            if extract:
                return extract
        return None

    def lookup(self, query: str, limit: int = 5) -> WikiResult:
        """Search, then fetch the lead summary of the best hit (exact title preferred)."""
        hits = self.search(query, limit=limit)
        result = WikiResult(query=query, hits=hits)
        if not hits:
            return result
        q = query.strip().lower()
        best = next((h for h in hits if h.title.lower() == q), hits[0])
        result.title = best.title
        result.summary = self.page_summary(best.title) or ""
        return result

    def page_infobox(self, title: str) -> dict[str, str]:
        """Best-effort extraction of key: value pairs from the infobox."""
        data = self._get({
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
        })
        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        return _parse_infobox(wikitext)

    def _get(self, params: dict[str, Any]) -> Any:
        try:
            r = self._session.get(BASE_URL, params=params, timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise WikiError(f"Could not reach starcitizen.tools: {e}") from e
        except ValueError as e:
            raise WikiError("starcitizen.tools returned invalid JSON") from e


def first_sentences(text: str, n: int = 2, max_chars: int = 320) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    out = " ".join(s.strip() for s in sentences[:n] if s.strip())
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


_default: Wiki | None = None
_default_lock = threading.Lock()


def default_client() -> Wiki:
    global _default
    with _default_lock:
        if _default is None:
            _default = Wiki()
        return _default


def _strip_tags(html: str) -> str:
    import html as html_lib
    return html_lib.unescape(re.sub(r"<[^>]+>", "", html))


def _parse_infobox(wikitext: str) -> dict[str, str]:
    """Naive but adequate: scan template pipes for `key = value` lines."""
    out: dict[str, str] = {}
    # First {{Infobox ...}} block; non-greedy, adequate because wiki infoboxes are usually flat.
    m = re.search(r"\{\{Infobox[^{}]*\}\}", wikitext, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return out
    body = m.group(0)
    for line in body.split("|"):
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().rstrip("}").strip()
        if k and v and not k.lower().startswith("infobox"):
            out[k] = v
    return out
