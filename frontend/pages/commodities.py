"""COMMODITIES page — UEX commodity prices with live name suggestions."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pages.components import LookupPage
from services import uex


class CommodityNotFound(LookupError):
    pass


class CommoditiesPage(LookupPage):
    title = "COMMODITIES"
    heading = "COMMODITIES"
    description = ("Search UEX for current per-SCU prices at every terminal that sells or buys a commodity. "
                   "Voice: \"what is the price of laranite\", \"where can I sell iron\".")
    hint = "Enter a commodity name, for example Iron, Laranite or Medical Supplies."
    button_text = "SEARCH UEX"
    result_types = (uex.CommodityResult,)

    def build_notice(self) -> None:
        self.notice_var = tk.StringVar(value=uex.key_status() or "")
        self.notice = ttk.Label(self, textvariable=self.notice_var, style="Muted.TLabel",
                                wraplength=900, justify="left")
        warn = self.ctx.theme.colors.get("warn")
        if warn:
            self.notice.configure(foreground=warn)
        self.notice.pack(anchor="w", pady=(0, 6))

    def on_show(self) -> None:
        self.notice_var.set(uex.key_status() or "")

    def suggest(self, query: str) -> list[str]:
        return uex.get_client().suggest(query)

    def lookup(self, query: str) -> uex.CommodityResult:
        result = uex.get_client().lookup(query)
        if result is None:
            raise CommodityNotFound(f'UEX has no commodity matching "{query}".')
        return result

    def query_for(self, result: uex.CommodityResult) -> str:
        return result.commodity.name

    def render(self, result: uex.CommodityResult) -> list[str]:
        c = result.commodity
        buy, sell = result.buy_from(), result.sell_to()
        lines = [f"{c.name.upper()} ({c.code}) — LIVE UEX DATA (prices are aUEC per SCU)"]
        if result.note:
            lines.append(result.note)
        lines += ["", f"BUY FROM — {len(buy)} terminal(s) selling {c.name}, cheapest first"]
        lines += [f"  {l.location:<44} {l.price_buy:>10,.0f}   {l.system:<8} "
                  f"{'' if l.scu_buy is None else f'{l.scu_buy:,} SCU'}" for l in buy] or ["  none listed"]
        lines += ["", f"SELL TO — {len(sell)} terminal(s) buying {c.name}, best price first"]
        lines += [f"  {l.location:<44} {l.price_sell:>10,.0f}   {l.system:<8} "
                  f"{'' if l.scu_sell is None else f'{l.scu_sell:,} SCU demand'}" for l in sell] or ["  none listed"]
        others = [m for m in result.matches if m != c.name]
        if others:
            lines += ["", "Other UEX matches: " + ", ".join(others[:8])]
        lines += ["", "UEX data is community-maintained; verify prices in game before trading."]
        return lines

    def speech(self, result: uex.CommodityResult) -> str:
        return uex.price_speech(result)

    def status_for(self, result: uex.CommodityResult) -> str:
        return (f"Loaded {len(result.buy_from())} buy and {len(result.sell_to())} sell terminal(s) "
                f"for {result.commodity.name} from UEX.")


PAGE_CLASS = CommoditiesPage
