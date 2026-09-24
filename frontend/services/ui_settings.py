"""config/ui_settings.json load/save (save merges, keeping unknown keys) plus small helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_HOTKEY = "ctrl+shift+f12"

MODIFIERS = ("ctrl", "alt", "shift", "win")
_ALIASES = {"control": "ctrl", "ctl": "ctrl", "menu": "alt", "windows": "win", "super": "win"}


def load(path: Path | str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path | str, data: dict[str, Any]) -> None:
    """Atomic write; keys present on disk but absent from `data` are preserved."""
    path = Path(path)
    merged = load(path)
    merged.update(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    tmp.replace(path)


def hotkey_of(settings: dict[str, Any]) -> str:
    value = settings.get("hotkey", DEFAULT_HOTKEY)
    return value if isinstance(value, str) else DEFAULT_HOTKEY


def normalize_chord(text: str) -> str:
    """'Shift + Ctrl + F12' -> 'ctrl+shift+f12'; '' = disabled; raises ValueError if malformed."""
    text = (text or "").strip().lower()
    if not text:
        return ""
    parts = [p.strip() for p in text.split("+")]
    if any(not p for p in parts):
        raise ValueError("empty key in chord")
    parts = [_ALIASES.get(p, p) for p in parts]
    mods = [p for p in parts if p in MODIFIERS]
    keys = [p for p in parts if p not in MODIFIERS]
    if len(set(mods)) != len(mods):
        raise ValueError("modifier repeated")
    if len(keys) != 1:
        raise ValueError("a chord needs exactly one non-modifier key (e.g. ctrl+shift+f12)")
    ordered = [m for m in MODIFIERS if m in mods]
    return "+".join(ordered + keys)


def device_choices(devices: Any) -> list[tuple[str, str]]:
    """[(id, label)] for the microphone picker; Windows default first."""
    out = [("", "Windows default")]
    for d in devices or []:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            continue
        name = str(d.get("name") or d["id"])
        out.append((d["id"], f"{name} (default)" if d.get("is_default") else name))
    return out
