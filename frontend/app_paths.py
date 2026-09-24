"""Shared frontend paths/constants; keeps the upstream config dir so old settings carry over."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Upstream settings dir kept for existing users; commands live in config/commands.json.
LEGACY_CONFIG_DIR = Path(os.path.expanduser("~")) / ".star_citizen_voice_keybinds"
LEGACY_SETTINGS_FILE = LEGACY_CONFIG_DIR / "settings.json"

# Cache for scunpacked JSON (per-patch data, safe to cache aggressively).
CACHE_DIR = Path(os.path.expanduser("~")) / ".deckhand" / "cache"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
COMMANDS_JSON = CONFIG_DIR / "commands.json"
COMMANDS_DEFAULT = CONFIG_DIR / "commands.default.json"
UI_SETTINGS = CONFIG_DIR / "ui_settings.json"  # GUI-owned (TTS, theme, hotkey, microphone, window)

PIPE_NAME = r"\\.\pipe\deckhand"

APP_NAME = "Deckhand"
APP_VERSION = "2.0.0"

# Links used by the GUIDES / ANNOUNCEMENTS / CREDIT pages.
GUIDES_URL = "https://starcitizen.tools/Category:Guides"
ANNOUNCEMENTS_URL = "https://robertsspaceindustries.com/spectrum/community/SC/forum/1"
UPSTREAM_URL = "https://github.com/Kabutopzzz/Kabutopz-Voice-Protocol"

# GUI diagnostics (pythonw has no console, so tracebacks go here).
FRONTEND_LOG = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "deckhand-frontend.log"


def ensure_dirs() -> None:
    LEGACY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv(path: Path | str | None = None) -> None:
    """Minimal .env loader — no python-dotenv dep required."""
    if path is None:
        path = PROJECT_ROOT / ".env"
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
