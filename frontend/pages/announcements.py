"""ANNOUNCEMENTS page: link to the official RSI Spectrum announcements forum."""
from __future__ import annotations

from app_paths import ANNOUNCEMENTS_URL
from pages.guides import LinkPage


class AnnouncementsPage(LinkPage):
    title = "ANNOUNCEMENTS"
    heading = "OFFICIAL ANNOUNCEMENTS"
    description = ("Patch notes, server status and news straight from Cloud Imperium on the official "
                   "RSI Spectrum Announcements forum. Opens in your web browser.")
    button_text = "OPEN RSI ANNOUNCEMENTS"
    url = ANNOUNCEMENTS_URL


PAGE_CLASS = AnnouncementsPage
