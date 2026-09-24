"""TTS voice discovery (SAPI5 + OneCore registry tokens) and persisted voice-feedback settings."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

HKLM = "HKEY_LOCAL_MACHINE"
CATEGORIES: tuple[tuple[str, str], ...] = (
    (r"SOFTWARE\Microsoft\Speech\Voices\Tokens", "Desktop"),
    (r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens", "OneCore"),
)

DEFAULT_VOLUME = 150
MAX_VOLUME = 300
ADD_VOICES_URI = "ms-settings:speech"
TEST_PHRASE = "Deckhand voice check. Landing gear deployed."

Reader = Callable[[str], Iterable[tuple[str, str]]]


@dataclass(frozen=True)
class Voice:
    token_id: str  # "" = Windows default voice
    label: str


def _winreg_reader(category_path: str) -> list[tuple[str, str]]:
    """Return [(token_key_name, display_name)] for HKLM\\<category_path>."""
    import winreg

    sub = category_path.split("\\", 1)[1]  # strip "HKEY_LOCAL_MACHINE\"
    out: list[tuple[str, str]] = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as root:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, name) as k:
                    display, _ = winreg.QueryValueEx(k, "")
            except OSError:
                display = ""
            out.append((name, str(display or "")))
    return out


def list_voices(read: Reader | None = None) -> list[Voice]:
    """Installed voices, Windows default first. Missing categories are skipped."""
    read = read or _winreg_reader
    voices = [Voice("", "Windows default voice")]
    for sub, source in CATEGORIES:
        path = f"{HKLM}\\{sub}"
        try:
            entries = list(read(path))
        except OSError:
            continue
        for key, display in sorted(entries, key=lambda e: (e[1] or e[0]).lower()):
            voices.append(Voice(f"{path}\\{key}", f"{display or key}  [{source}]"))
    return voices


def _clamp(v: object, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


@dataclass
class TtsSettings:
    enabled: bool = True
    voice_id: str = ""
    volume: int = DEFAULT_VOLUME
    rate: int = 0

    @classmethod
    def load(cls, path: Path) -> "TtsSettings":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = data.get("tts", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(raw)

    def to_dict(self) -> dict:
        """The value stored under the 'tts' key of ui_settings.json."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "TtsSettings":
        if not isinstance(raw, dict):
            return cls()
        voice = raw.get("voice_id", "")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            voice_id=voice if isinstance(voice, str) else "",
            volume=_clamp(raw.get("volume", DEFAULT_VOLUME), 0, MAX_VOLUME, DEFAULT_VOLUME),
            rate=_clamp(raw.get("rate", 0), -10, 10, 0),
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data["tts"] = asdict(self)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)

    def ipc_messages(self) -> list[dict]:
        return [
            {"type": "set_tts_enabled", "enabled": self.enabled},
            {"type": "set_tts_voice", "id": self.voice_id},
            {"type": "set_tts_volume", "volume": self.volume},
            {"type": "set_tts_rate", "rate": self.rate},
        ]
