"""Editable command set: user commands.json over shipped defaults; canonical side-sensitive keys."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

CUSTOM_CATEGORY = "Custom Phrases"
FORMAT_VERSION = 2

# Canonical key names from backend/src/input/vk_map.zig (tests assert they stay a subset).
MODIFIER_KEYS = (
    "ctrl", "alt", "shift",
    "left ctrl", "right ctrl", "left alt", "right alt", "left shift", "right shift",
)
_NAMED_KEYS = (
    "backspace", "tab", "clear", "enter", "pause", "capslock", "escape", "space",
    "pageup", "pagedown", "end", "home", "left", "up", "right", "down",
    "print_screen", "insert", "delete", "lwin", "rwin",
    "semicolon", "plus", "comma", "minus", "period", "slash", "backtick",
    "lbracket", "backslash", "rbracket", "apostrophe",
    "kp_multiply", "kp_add", "kp_subtract", "kp_divide", "kp_decimal",
)
KEY_NAMES: frozenset[str] = frozenset(
    MODIFIER_KEYS
    + _NAMED_KEYS
    + tuple("abcdefghijklmnopqrstuvwxyz")
    + tuple("0123456789")
    + tuple(f"f{n}" for n in range(1, 25))
    + tuple(f"numpad{n}" for n in range(10))
)

_ALIASES = {
    "control": "ctrl", "left control": "left ctrl", "right control": "right ctrl",
    "lctrl": "left ctrl", "rctrl": "right ctrl", "lalt": "left alt", "ralt": "right alt",
    "lshift": "left shift", "rshift": "right shift", "menu": "alt",
    "return": "enter", "esc": "escape", "back": "backspace", "del": "delete",
    "spacebar": "space", "space bar": "space",
    "page up": "pageup", "page down": "pagedown", "pgup": "pageup", "pgdn": "pagedown",
    "printscreen": "print_screen", "print screen": "print_screen", "prtsc": "print_screen",
    "caps lock": "capslock", "win": "lwin", "windows": "lwin",
    "left windows": "lwin", "right windows": "rwin",
    ";": "semicolon", "=": "plus", ",": "comma", "-": "minus", ".": "period",
    "/": "slash", "`": "backtick", "grave": "backtick", "[": "lbracket",
    "\\": "backslash", "]": "rbracket", "'": "apostrophe", "quote": "apostrophe",
    "num multiply": "kp_multiply", "num plus": "kp_add", "num minus": "kp_subtract",
    "num divide": "kp_divide", "num decimal": "kp_decimal",
    "arrow left": "left", "arrow right": "right", "arrow up": "up", "arrow down": "down",
    # mouse / wheel display names (see key_display)
    "mouse left": "left mouse", "mouse right": "right mouse", "mouse middle": "middle mouse",
    "lmb": "left mouse", "rmb": "right mouse", "mmb": "middle mouse",
    "left click": "left mouse", "right click": "right mouse",
    "wheel up": "scroll up", "wheel down": "scroll down",
    "mouse wheel up": "scroll up", "mouse wheel down": "scroll down",
}
_MOD_ORDER = {m: i for i, m in enumerate(
    ("ctrl", "left ctrl", "right ctrl", "alt", "left alt", "right alt", "shift", "left shift", "right shift")
)}
_NUMPAD_RE = re.compile(r"^(?:num|numpad|kp)[ _]?([0-9])$")

MOUSE_BUTTONS = ("left", "right", "middle", "x1", "x2")
MOUSE_KINDS = ("click", "double", "down", "up")
SYSTEM_OPS = ("stop_listening", "stop_speaking", "say_random")
ACTION_TYPES = ("tap", "hold", "press", "release", "mouse", "scroll", "system")
_KNOWN_TOKENS = KEY_NAMES | {f"{b} mouse" for b in MOUSE_BUTTONS} | {"scroll up", "scroll down"}


def _canon_token(tok: str) -> str:
    tok = " ".join(tok.split())
    tok = _ALIASES.get(tok, tok)
    m = _NUMPAD_RE.match(tok)
    return f"numpad{m.group(1)}" if m else tok


def _split_spaced(part: str) -> list[str]:
    """'alt f4' -> ['alt', 'f4']; 'left alt n' -> ['left alt', 'n'] (only when unambiguous)."""
    words = part.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        # greedily take the longest run of words that forms a known token
        for j in range(len(words), i, -1):
            cand = _canon_token(" ".join(words[i:j]))
            if cand in _KNOWN_TOKENS:
                out.append(cand)
                i = j
                break
        else:
            return [part]
    return out


def normalize_keys(keys: str) -> str:
    """Canonical keybind string (see module docstring). '' for empty input."""
    tokens: list[str] = []
    for raw in str(keys or "").lower().split("+"):
        part = " ".join(raw.split())
        if not part:
            continue
        tok = _canon_token(part)
        if tok not in _KNOWN_TOKENS and " " in part:
            tokens.extend(_split_spaced(part))
        else:
            tokens.append(tok)
    mods, base = [], []
    for t in tokens:
        (mods if t in _MOD_ORDER else base).append(t)
    mods = sorted(dict.fromkeys(mods), key=_MOD_ORDER.__getitem__)
    return "+".join(mods + list(dict.fromkeys(base)))


def key_display(action: dict) -> str:
    """Human/matchable keybind of any action: 'left alt+n', 'left alt+right mouse', 'scroll up'."""
    t = action.get("type")
    if t in ("tap", "hold", "press", "release"):
        return str(action.get("keys", ""))
    if t == "mouse":
        mouse = f"{action.get('button', 'left')} mouse"
        return f"{action['keys']}+{mouse}" if action.get("keys") else mouse
    if t == "scroll":
        return f"scroll {action.get('direction', 'down')}"
    return ""


def describe_action(action: dict) -> str:
    """Short text for previews, e.g. 'tap left alt+n', 'hold b for 0.8 s'."""
    t = action.get("type")
    if t == "hold":
        return f"hold {action.get('keys')} for {action.get('duration_ms', 0) / 1000:g} s"
    if t in ("tap", "press", "release"):
        return f"{t} {action.get('keys')}"
    if t == "mouse":
        kind = action.get("kind", "click")
        return f"{kind} {key_display(action)}"
    if t == "scroll":
        return f"scroll {action.get('direction')} x{action.get('amount', 1)}"
    if t == "system":
        return f"system: {action.get('op')}"
    return str(t)


def normalize_phrase(phrase: str) -> str:
    return " ".join(str(phrase or "").lower().split())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _validated_keys(keys: Any, *, required: bool = True) -> str:
    if not isinstance(keys, str) or not keys.strip():
        if required:
            raise ValueError("Enter a keybind.")
        return ""
    canon = normalize_keys(keys)
    parts = canon.split("+") if canon else []
    for p in parts:
        if p not in KEY_NAMES:
            raise ValueError(f"Unknown key '{p}' in keybind '{keys.strip()}'.")
    base = [p for p in parts if p not in MODIFIER_KEYS]
    if len(base) > 1:
        raise ValueError(f"Keybind '{keys.strip()}' has more than one main key ({', '.join(base)}).")
    if not parts:
        raise ValueError("Enter a keybind.")
    return canon


def validate_action(action: Any) -> dict:
    """Return a canonical copy of `action` or raise ValueError (docs/COMMANDS.md)."""
    if not isinstance(action, dict):
        raise ValueError("Action must be an object.")
    t = action.get("type")
    if t in ("tap", "press", "release"):
        return {"type": t, "keys": _validated_keys(action.get("keys"))}
    if t == "hold":
        d = action.get("duration_ms")
        if isinstance(d, float) and d.is_integer():
            d = int(d)
        if not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= 60000:
            raise ValueError("Hold duration must be between 0.001 and 60 seconds.")
        return {"type": "hold", "keys": _validated_keys(action.get("keys")), "duration_ms": d}
    if t == "mouse":
        if action.get("button") not in MOUSE_BUTTONS:
            raise ValueError(f"Mouse button must be one of {', '.join(MOUSE_BUTTONS)}.")
        if action.get("kind", "click") not in MOUSE_KINDS:
            raise ValueError(f"Mouse action must be one of {', '.join(MOUSE_KINDS)}.")
        out = {"type": "mouse", "button": action["button"], "kind": action.get("kind", "click")}
        keys = _validated_keys(action.get("keys"), required=False)
        if keys:
            out["keys"] = keys
        return out
    if t == "scroll":
        if action.get("direction") not in ("up", "down"):
            raise ValueError("Scroll direction must be up or down.")
        amount = action.get("amount", 1)
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= 100:
            raise ValueError("Scroll amount must be between 1 and 100.")
        return {"type": "scroll", "direction": action["direction"], "amount": amount}
    if t == "system":
        op = action.get("op")
        if op not in SYSTEM_OPS:
            raise ValueError(f"System action must be one of {', '.join(SYSTEM_OPS)}.")
        out: dict = {"type": "system", "op": op}
        if "responses" in action or op == "say_random":
            resp = [str(r).strip() for r in action.get("responses") or [] if str(r).strip()]
            if op == "say_random" and not resp:
                raise ValueError("Add at least one response to say.")
            out["responses"] = resp
        return out
    raise ValueError(f"Unknown action type '{t}'.")


_FIELD_ORDER = ("id", "label", "category", "phrases", "disabled_phrases", "custom", "action", "tts_ack")


def dump_commands(commands: Iterable[dict]) -> str:
    """v2 file text, one command per line (diff-friendly, same style as the default file)."""
    lines = []
    for c in commands:
        ordered = {k: c[k] for k in _FIELD_ORDER if k in c}
        ordered.update({k: v for k, v in c.items() if k not in ordered})
        lines.append("    " + json.dumps(ordered, ensure_ascii=False))
    body = ",\n".join(lines)
    return '{\n  "version": %d,\n  "commands": [\n%s\n  ]\n}\n' % (FORMAT_VERSION, body)


class CommandStore:
    """Implements pages.base.CommandStoreLike plus the editing API used by the edit pages."""

    normalize_keys = staticmethod(normalize_keys)

    def __init__(self, default_path: Path | str, user_path: Path | str) -> None:
        self.default_path = Path(default_path)
        self.user_path = Path(user_path)
        self._defaults: dict[str, dict] = {}
        self._commands: list[dict] = []
        self._listeners: list[Callable[[], None]] = []
        self.load_error: str | None = None

    # ------------------------------------------------------------ loading

    @staticmethod
    def _read(path: Path) -> list[dict]:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        cmds = data.get("commands") if isinstance(data, dict) else None
        if not isinstance(cmds, list):
            raise ValueError(f"{path.name}: missing 'commands' list")
        return [c for c in cmds if isinstance(c, dict) and isinstance(c.get("id"), str)]

    @staticmethod
    def _normalized(c: dict, default: dict | None) -> dict:
        out = copy.deepcopy(c)
        base = default or {}
        custom = bool(out.get("custom", False))
        out["label"] = str(out.get("label") or base.get("label") or out["id"].replace("_", " ").title())
        out["category"] = str(out.get("category") or base.get("category")
                              or (CUSTOM_CATEGORY if custom else "Other"))
        out["phrases"] = [p for p in dict.fromkeys(normalize_phrase(p) for p in out.get("phrases", [])) if p]
        out["disabled_phrases"] = [
            p for p in dict.fromkeys(normalize_phrase(p) for p in out.get("disabled_phrases", []))
            if p and p not in out["phrases"]
        ]
        out["custom"] = custom
        out.setdefault("action", copy.deepcopy(base.get("action", {})))
        return {k: out[k] for k in _FIELD_ORDER if k in out} | {k: v for k, v in out.items() if k not in _FIELD_ORDER}

    def load(self) -> None:
        defaults = [self._normalized(c, None) for c in self._read(self.default_path)]
        self._defaults = {c["id"]: c for c in defaults}
        self.load_error = None
        user: list[dict] | None = None
        if self.user_path.exists():
            try:
                user = self._read(self.user_path)
            except (OSError, ValueError) as e:
                self.load_error = f"Could not read {self.user_path.name} ({e}); using the default commands."
        if user is None:
            self._commands = copy.deepcopy(defaults)
            return
        merged: list[dict] = []
        seen: set[str] = set()
        for c in user:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            merged.append(self._normalized(c, self._defaults.get(c["id"])))
        # add defaults missing from the user file right after their default predecessor
        prev: str | None = None
        for d in defaults:
            if d["id"] not in seen:
                pos = 0
                if prev is not None:
                    pos = next(i for i, c in enumerate(merged) if c["id"] == prev) + 1
                merged.insert(pos, copy.deepcopy(d))
                seen.add(d["id"])
            prev = d["id"]
        self._commands = merged

    # ------------------------------------------------------------ CommandStoreLike

    def all(self) -> list[dict]:
        return copy.deepcopy(self._commands)

    def get(self, command_id: str) -> dict | None:
        c = self._find(command_id)
        return copy.deepcopy(c) if c else None

    def categories(self) -> list[str]:
        seen: list[str] = []
        has_custom = False
        for c in self._commands:
            if c.get("custom"):
                has_custom = True
            elif c["category"] not in seen:
                seen.append(c["category"])
        if has_custom:
            seen.append(CUSTOM_CATEGORY)
        return seen

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------ saving

    def save(self) -> None:
        text = dump_commands(self._commands)
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".commands.", suffix=".tmp", dir=str(self.user_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, self.user_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        for fn in list(self._listeners):
            fn()

    @contextmanager
    def transaction(self) -> Iterator["CommandStore"]:
        """Group several edits (+ save): if anything raises, in-memory state is rolled back."""
        backup = copy.deepcopy(self._commands)
        try:
            yield self
        except BaseException:
            self._commands = backup
            raise

    # ------------------------------------------------------------ helpers

    def _find(self, command_id: str) -> dict | None:
        return next((c for c in self._commands if c["id"] == command_id), None)

    def _require(self, command_id: str) -> dict:
        c = self._find(command_id)
        if c is None:
            raise ValueError(f"Unknown command '{command_id}'.")
        return c

    def phrase_owner(self, phrase: str, exclude_id: str | None = None) -> dict | None:
        """The command (enabled or disabled list) that already uses `phrase`."""
        n = normalize_phrase(phrase)
        for c in self._commands:
            if c["id"] != exclude_id and (n in c["phrases"] or n in c["disabled_phrases"]):
                return c
        return None

    def _clean_phrases(self, command_id: str | None, enabled: Iterable[str],
                       disabled: Iterable[str]) -> tuple[list[str], list[str]]:
        en = [p for p in dict.fromkeys(normalize_phrase(p) for p in enabled) if p]
        dis = [p for p in dict.fromkeys(normalize_phrase(p) for p in disabled) if p and p not in en]
        for p in en + dis:
            owner = self.phrase_owner(p, exclude_id=command_id)
            if owner is not None:
                raise ValueError(f"The phrase '{p}' is already used by '{owner['label']}'.")
        return en, dis

    # ------------------------------------------------------------ editing

    def set_phrases(self, command_id: str, enabled: list[str], disabled: list[str]) -> None:
        c = self._require(command_id)
        en, dis = self._clean_phrases(command_id, enabled, disabled)
        if c["custom"] and not (en or dis):
            raise ValueError(f"'{c['label']}' must keep at least one phrase.")
        c["phrases"], c["disabled_phrases"] = en, dis

    def add_phrase(self, command_id: str, phrase: str, enabled: bool = True) -> None:
        c = self._require(command_id)
        n = normalize_phrase(phrase)
        if not n:
            raise ValueError("Enter a phrase.")
        if n in c["phrases"] or n in c["disabled_phrases"]:
            raise ValueError(f"'{c['label']}' already has the phrase '{n}'.")
        if enabled:
            self.set_phrases(command_id, c["phrases"] + [n], c["disabled_phrases"])
        else:
            self.set_phrases(command_id, c["phrases"], c["disabled_phrases"] + [n])

    def remove_phrase(self, command_id: str, phrase: str) -> None:
        c = self._require(command_id)
        n = normalize_phrase(phrase)
        self.set_phrases(command_id, [p for p in c["phrases"] if p != n],
                         [p for p in c["disabled_phrases"] if p != n])

    def set_action(self, command_id: str, action: dict) -> None:
        c = self._require(command_id)
        c["action"] = validate_action(action)

    def create_custom(self, label: str, category: str, phrases: list[str], action: dict,
                      disabled_phrases: list[str] | None = None) -> str:
        label = str(label or "").strip()
        if not label:
            raise ValueError("Enter an action name.")
        en, dis = self._clean_phrases(None, phrases, disabled_phrases or [])
        if not en:
            raise ValueError("Add and check at least one phrase.")
        act = validate_action(action)
        base = slugify(label) or "custom"
        cid, n = base, 2
        while self._find(cid) is not None or cid in self._defaults:
            cid, n = f"{base}_{n}", n + 1
        self._commands.append({
            "id": cid, "label": label, "category": str(category or "").strip() or CUSTOM_CATEGORY,
            "phrases": en, "disabled_phrases": dis, "custom": True, "action": act,
        })
        return cid

    def update_custom(self, command_id: str, label: str | None = None, category: str | None = None) -> None:
        c = self._require(command_id)
        if not c["custom"]:
            raise ValueError(f"'{c['label']}' is a built-in command; only custom commands can be renamed.")
        if label is not None:
            if not label.strip():
                raise ValueError("Enter an action name.")
            c["label"] = label.strip()
        if category is not None:
            c["category"] = category.strip() or CUSTOM_CATEGORY

    def delete_custom(self, command_id: str) -> None:
        c = self._require(command_id)
        if not c["custom"]:
            raise ValueError(f"'{c['label']}' is a built-in command and cannot be deleted.")
        self._commands.remove(c)

    def default_of(self, command_id: str) -> dict | None:
        d = self._defaults.get(command_id)
        return copy.deepcopy(d) if d else None

    def reset_command(self, command_id: str) -> None:
        c = self._require(command_id)
        d = self._defaults.get(command_id)
        if c["custom"] or d is None:
            raise ValueError(f"'{c['label']}' is a custom command; there is no default to restore.")
        self._clean_phrases(command_id, d["phrases"], d["disabled_phrases"])
        idx = self._commands.index(c)
        self._commands[idx] = copy.deepcopy(d)

    def is_modified(self, command_id: str) -> bool:
        c = self._find(command_id)
        d = self._defaults.get(command_id)
        if c is None or d is None or c["custom"]:
            return False
        return c != d

    # ------------------------------------------------------------ searching

    def search_all(self, query: str) -> list[dict]:
        q = " ".join(str(query or "").lower().split())
        out = []
        for c in self._commands:
            hay = " | ".join([c["id"], c["label"], c["category"], key_display(c["action"]),
                              *c["phrases"], *c["disabled_phrases"]]).lower()
            if not q or q in hay:
                out.append(copy.deepcopy(c))
        return out

    def commands_for_key(self, keys: str) -> list[dict]:
        """Commands bound to exactly `keys` (normalised, side-sensitive)."""
        k = normalize_keys(keys)
        if not k:
            return []
        return [copy.deepcopy(c) for c in self._commands if normalize_keys(key_display(c["action"])) == k]

    def filter_by_keybind(self, keys: str) -> list[dict]:
        """Exact keybind filter; a lone bare modifier also matches its left-side variant."""
        k = normalize_keys(keys)
        if k in ("ctrl", "alt", "shift"):
            wanted = {k, f"left {k}"}
            return [copy.deepcopy(c) for c in self._commands
                    if normalize_keys(key_display(c["action"])) in wanted]
        return self.commands_for_key(k)
