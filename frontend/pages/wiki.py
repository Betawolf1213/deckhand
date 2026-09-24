"""WIKI page — starcitizen.tools search with live title suggestions and a lead summary."""
from __future__ import annotations

from pages.components import LookupPage
from services import wiki


class WikiPage(LookupPage):
    title = "WIKI"
    heading = "WIKI"
    description = ("Search the Star Citizen wiki (starcitizen.tools). Voice: \"tell me about the Carrack\".")
    hint = "Type a topic, for example Carrack, Hurston or Quantum drive."
    button_text = "SEARCH WIKI"
    result_types = (wiki.WikiResult,)

    def suggest(self, query: str) -> list[str]:
        return wiki.default_client().suggest(query)

    def lookup(self, query: str) -> wiki.WikiResult:
        return wiki.default_client().lookup(query)

    def query_for(self, r: wiki.WikiResult) -> str:
        return r.title or r.query

    def render(self, r: wiki.WikiResult) -> list[str]:
        if not r.hits:
            return [f"No wiki results for \"{r.query}\"."]
        lines = []
        if r.title:
            lines += [r.title.upper(), r.url, "", r.summary or "(no summary available)", "", "OTHER RESULTS"]
        for h in r.hits:
            if h.title == r.title:
                continue
            lines.append(f"— {h.title}")
            if h.snippet:
                lines.append(f"  {h.snippet}")
        return lines

    def speech(self, r: wiki.WikiResult) -> str:
        return wiki.first_sentences(r.summary) if r.summary else ""

    def status_for(self, r: wiki.WikiResult) -> str:
        return f"{len(r.hits)} result(s) for \"{r.query}\"." if r.hits else f"No results for \"{r.query}\"."


PAGE_CLASS = WikiPage
