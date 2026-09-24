"""WIKI page — starcitizen.tools search with live title suggestions and a lead summary."""
from __future__ import annotations

from pages.components import LookupPage
from services import wiki


class WikiPage(LookupPage):
    title = "WIKI"
    heading = "WIKI"
    description = "Search the Star Citizen wiki (starcitizen.tools). Voice: \"tell me about the Carrack\"."
    hint = "Type a topic, for example Carrack, Hurston or Quantum drive."
    button_text = "SEARCH WIKI"
    result_types = (wiki.WikiResult,)

    def suggest(self, query: str) -> list[str]:
        return wiki.default_client().suggest(query)

    def lookup(self, query: str) -> wiki.WikiResult:
        return wiki.default_client().lookup(query)

    def query_for(self, result: wiki.WikiResult) -> str:
        return result.title or result.query

    def render(self, result: wiki.WikiResult) -> list[str]:
        if not result.hits:
            return [f"No wiki results for \"{result.query}\"."]
        lines = []
        if result.title:
            summary = result.summary or "(no summary available)"
            lines += [result.title.upper(), result.url, "", summary, "", "OTHER RESULTS"]
        for h in result.hits:
            if h.title == result.title:
                continue
            lines.append(f"— {h.title}")
            if h.snippet:
                lines.append(f"  {h.snippet}")
        return lines

    def speech(self, result: wiki.WikiResult) -> str:
        return wiki.first_sentences(result.summary) if result.summary else ""

    def status_for(self, result: wiki.WikiResult) -> str:
        if result.hits:
            return f"{len(result.hits)} result(s) for \"{result.query}\"."
        return f"No results for \"{result.query}\"."


PAGE_CLASS = WikiPage
