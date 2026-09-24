"""scunpacked static-JSON ship/item client, cached on disk; check BASE_URL if lookups 404."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

import app_paths

BASE_URL = "https://scunpacked.com"
CACHE_TTL_S = 7 * 24 * 3600  # 7 days — refresh weekly, covers most patches
TIMEOUT_S = 15.0


class Scunpacked:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "Deckhand/0.1"})
        app_paths.ensure_dirs()
        self._cache_dir: Path = app_paths.CACHE_DIR / "scunpacked"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def ship(self, name: str) -> dict[str, Any] | None:
        return self._fetch_json(f"/ships/{_slug(name)}.json")

    def item(self, name: str) -> dict[str, Any] | None:
        return self._fetch_json(f"/items/{_slug(name)}.json")

    def _fetch_json(self, path: str) -> dict[str, Any] | None:
        cache_path = self._cache_dir / path.strip("/").replace("/", "__")
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime < CACHE_TTL_S:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cache_path.unlink(missing_ok=True)

        url = BASE_URL + path
        try:
            r = self._session.get(url, timeout=TIMEOUT_S)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, json.JSONDecodeError):
            # Fall back to a stale cache if the network is down.
            if cache_path.exists():
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            return None

        cache_path.write_text(json.dumps(data), encoding="utf-8")
        return data


def _slug(name: str) -> str:
    return name.strip().lower().replace(" ", "-").replace("_", "-")
