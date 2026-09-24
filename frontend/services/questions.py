"""Answer spoken questions from Vosk transcripts; returns Answer or None, never raises."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Callable

from pages.base import Answer
from services import mining_data, scwiki, uex, wiki

log = logging.getLogger(__name__)

Combo = tuple[tuple[tuple[str | None, str], ...], tuple[str | None, str]]  # (mods, base); key = (side, name)

MAX_SPOKEN = 5

# Default Star Citizen binds (reference subset), spoken when a key is unused by user commands.
KEYBIND_REFERENCE: dict[str, list[str]] = {
    "w": ["Move forward / ship throttle up"],
    "a": ["Move or strafe left"],
    "s": ["Move backward / ship throttle down"],
    "d": ["Move or strafe right"],
    "q": ["Lean left on foot / roll left in ship"],
    "e": ["Lean right on foot / roll right in ship"],
    "r": ["Reload on foot", "Flight Ready in ship"],
    "t": ["Suit light on foot", "Select target nearest the crosshair in ship"],
    "u": ["Ship power toggle"],
    "f": ["Interact"],
    "g": ["Grenade on foot", "Cycle gimbal mode in ship"],
    "h": ["Hold to deploy decoy"],
    "j": ["Deploy noise countermeasure"],
    "c": ["Cruise control in ship"],
    "x": ["Prone on foot / space brake in ship"],
    "y": ["Hold to exit seat"],
    "b": ["Quantum / NAV mode; hold for quantum travel"],
    "n": ["Landing gear / landing mode"],
    "1": ["Sidearm"],
    "2": ["Primary weapon"],
    "3": ["Secondary weapon"],
    "4": ["Target closest ship targeting you"],
    "5": ["Target closest hostile ship"],
    "6": ["Target closest friendly ship"],
    "7": ["Target closest contact"],
    "space": ["Jump"],
    "left shift": ["Sprint on foot / boost in ship"],
    "left ctrl": ["Crouch on foot / hold for auto land in ship"],
    "f1": ["Open or close MobiGlas"],
    "f2": ["Open Starmap"],
    "f4": ["Cycle camera view"],
    "f11": ["Open Contacts"],
    "f12": ["Show or hide chat"],
    "num 8": ["Raise front shield level"],
    "num 2": ["Raise rear shield level"],
    "num 4": ["Raise left shield level"],
    "num 6": ["Raise right shield level"],
    "num 7": ["Raise top shield level"],
    "num 1": ["Raise bottom shield level"],
    "num 5": ["Reset shield levels"],
    "right alt+k": ["Unlock ship component ports"],
    "left alt+n": ["Request landing / takeoff"],
    "left alt+c": ["Toggle coupled / decoupled flight mode"],
    "left alt+right mouse": ["Precision targeting / ship target zoom"],
}


# ================================================================ normalisation


def _normalize(text: str) -> str:
    t = text.lower().replace("\u2019", "'")
    t = re.sub(r"\bwhat'?s\b", "what is", t)
    t = re.sub(r"\bwhere'?s\b", "where is", t)
    t = re.sub(r"\bwho'?s\b", "who is", t)
    t = re.sub(r"[?!.;:\"()]", " ", t)
    t = re.sub(r"(?<!\d),|,(?!\d)", " ", t)  # keep thousands separators
    return " ".join(t.split())


_ARTICLES = {"a", "an", "the", "some", "any", "me"}


def _clean_name(name: str, drop_suffix: tuple[str, ...] = ()) -> str:
    """Drop leading articles but keep a spelled letter 'a' ('the a d four b' -> 'a d four b')."""
    words = name.strip().split()
    while words and words[0] in _ARTICLES:
        nxt = words[1] if len(words) > 1 else ""
        if words[0] == "a" and (len(nxt) == 1 or scwiki.num_kind(nxt)):
            break
        words.pop(0)
    n = " ".join(words)
    for suffix in drop_suffix:
        n = re.sub(rf"\s+{suffix}$", "", n)
    return n.strip()


def _first_match(patterns: list[str], text: str) -> str | None:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


# ================================================================ keys

_MOD_WORDS = {"alt": "alt", "control": "ctrl", "ctrl": "ctrl", "shift": "shift"}
_LETTER_WORDS = {
    "ay": "a", "bee": "b", "be": "b", "see": "c", "sea": "c", "dee": "d", "ee": "e", "ef": "f", "eff": "f",
    "gee": "g", "aitch": "h", "eye": "i", "jay": "j", "kay": "k", "el": "l", "em": "m", "en": "n",
    "oh": "o", "pee": "p", "queue": "q", "cue": "q", "are": "r", "ar": "r", "es": "s", "tea": "t",
    "tee": "t", "you": "u", "vee": "v", "ex": "x", "why": "y", "zed": "z", "zee": "z",
}
_NAMED = {
    ("space", "bar"): "space", ("spacebar",): "space", ("space",): "space", ("tab",): "tab",
    ("enter",): "enter", ("return",): "enter", ("escape",): "escape", ("esc",): "escape",
    ("back", "space"): "backspace", ("backspace",): "backspace", ("delete",): "delete", ("del",): "delete",
    ("insert",): "insert", ("home",): "home", ("end",): "end", ("page", "up"): "page up",
    ("page", "down"): "page down", ("caps", "lock"): "capslock", ("print", "screen"): "print screen",
    ("back", "slash"): "backslash", ("backslash",): "backslash", ("minus",): "minus", ("dash",): "minus",
    ("equals",): "equals", ("comma",): "comma", ("period",): "period", ("slash",): "slash",
    ("tilde",): "grave", ("backtick",): "grave", ("up",): "up", ("down",): "down",
    ("left",): "left", ("right",): "right",
    ("double", "you"): "w", ("double", "u"): "w",
}
_KEY_ALIASES = {
    "spacebar": "space", "return": "enter", "esc": "escape", "del": "delete", "back": "backspace",
    "print_screen": "print screen", "printscreen": "print screen", "pageup": "page up",
    "pagedown": "page down", "control": "ctrl",
}
_KEY_FILLER = {"the", "key", "keys", "button", "plus", "and", "arrow", "press", "pressing", "hotkey", "my"}
# Key phrase of only these words = misheard letter (N -> "and"); inside combos "and" is filler.
_SOLO_LETTER = {"and": "n", "an": "n", "in": "n", "inn": "n", "hey": "a", "eh": "a", "pea": "p"}


def _number_at(toks: list[str], i: int) -> tuple[int, int] | None:
    """(value, tokens consumed) for a digit token or number-word run starting at toks[i]."""
    if i >= len(toks):
        return None
    if toks[i].isdigit():
        return int(toks[i]), 1
    runs = scwiki.number_runs(toks[i:])
    if runs and runs[0][0] == 0:
        return runs[0][2], runs[0][1]
    return None


def _parse_spoken_combo(phrase: str) -> Combo | None:
    raw = [t for t in re.split(r"[\s+]+", phrase.lower()) if t and t not in ("the", "key", "button")]
    if len(raw) == 1 and raw[0] in _SOLO_LETTER:
        return (), (None, _SOLO_LETTER[raw[0]])
    toks = [t for t in re.split(r"[\s+]+", phrase.lower()) if t and t not in _KEY_FILLER]
    if not toks:
        return None
    mods: list[tuple[str | None, str]] = []
    base: tuple[str | None, str] | None = None
    i = 0
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        found: tuple[str | None, str] | None = None
        step = 1
        if t in ("left", "right") and nxt in _MOD_WORDS:
            mods.append((t, _MOD_WORDS[nxt]))
            i += 2
            continue
        if t in _MOD_WORDS:
            mods.append((None, _MOD_WORDS[t]))
            i += 1
            continue
        if t in ("left", "right", "middle") and nxt in ("mouse", "click"):
            found, step = (None, f"{t} mouse"), 2
        elif (m := re.fullmatch(r"f(\d{1,2})", t)) and 1 <= int(m.group(1)) <= 24:
            found = (None, f"f{int(m.group(1))}")
        elif t == "f" and (num := _number_at(toks, i + 1)) and 1 <= num[0] <= 24:
            found, step = (None, f"f{num[0]}"), 1 + num[1]
        elif (m := re.fullmatch(r"(?:numpad|num|kp_?)(\d)", t)):
            found = (None, f"num {m.group(1)}")
        elif t in ("num", "numpad", "keypad") or (t == "number" and nxt == "pad"):
            j = i + (2 if t == "number" else 1)
            num = _number_at(toks, j)
            if not num or not 0 <= num[0] <= 9:
                return None
            found, step = (None, f"num {num[0]}"), (j - i) + num[1]
        elif (t, nxt) in _NAMED:
            found, step = (None, _NAMED[(t, nxt)]), 2
        elif (t,) in _NAMED:
            found = (None, _NAMED[(t,)])
        elif len(t) == 1 and (t.isalpha() or t.isdigit()):
            found = (None, t)
        elif t in _LETTER_WORDS:
            found = (None, _LETTER_WORDS[t])
        elif (num := _number_at(toks, i)) and 0 <= num[0] <= 9 and num[1] == 1:
            found = (None, str(num[0]))
        else:
            return None
        if base is not None:
            return None  # two base keys: not a key name
        base = found
        i += step
    if base is None:
        base = mods.pop()
    return tuple(mods), base


def _combo_str(combo: Combo) -> str:
    return "+".join(f"{s} {n}" if s else n for s, n in (*combo[0], combo[1]))


def parse_key(phrase: str) -> str | None:
    """Spoken key name -> canonical key string ('f one' -> 'f1', 'right alt k' -> 'right alt+k')."""
    combo = _parse_spoken_combo(phrase or "")
    return _combo_str(combo) if combo else None


def _parse_key_part(part: str) -> tuple[str | None, str]:
    p = " ".join(part.strip().lower().split())
    m = re.fullmatch(r"(?:(left|right)\s*)?(alt|ctrl|control|shift)", p)
    if m:
        return m.group(1), _MOD_WORDS[m.group(2)]
    m = re.fullmatch(r"(?:numpad|num|kp_?)\s*(\d)", p)
    if m:
        return None, f"num {m.group(1)}"
    return None, _KEY_ALIASES.get(p, p)


def _parse_keys_string(keys: str) -> list[tuple[str | None, str]]:
    return [_parse_key_part(p) for p in str(keys or "").split("+") if p.strip()]


def _command_combo(cmd: dict) -> Combo | None:
    action = cmd.get("action") or {}
    kind = action.get("type")
    if kind in ("tap", "press", "release", "hold"):
        parts = _parse_keys_string(action.get("keys", ""))
        return (tuple(parts[:-1]), parts[-1]) if parts else None
    if kind == "mouse" and action.get("button"):
        return tuple(_parse_keys_string(action.get("keys", ""))), (None, f"{action['button']} mouse")
    return None


def _key_ok(a: tuple[str | None, str], b: tuple[str | None, str]) -> bool:
    return a[1] == b[1] and (a[0] is None or b[0] is None or a[0] == b[0])


def _combo_matches(q: Combo, c: Combo) -> bool:
    if not _key_ok(q[1], c[1]) or len(q[0]) != len(c[0]):
        return False
    remaining = list(c[0])
    for m in q[0]:
        hit = next((r for r in remaining if _key_ok(m, r)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def _key_display(key: tuple[str | None, str]) -> str:
    side, name = key
    if len(name) == 1 or re.fullmatch(r"f\d+", name):
        label = name.upper()
    else:
        label = " ".join(w.capitalize() for w in name.split())
    return f"{side.capitalize()} {label}" if side else label


def _combo_display(combo: Combo) -> str:
    return " plus ".join(_key_display(k) for k in (*combo[0], combo[1]))


def _label(cmd: dict) -> str:
    label = str(cmd.get("label") or "").strip()
    if label:
        return label
    return " ".join(w.capitalize() for w in str(cmd.get("id", "command")).replace("_", " ").split())


def _command_key_display(cmd: dict) -> str:
    combo = _command_combo(cmd)
    if combo:
        return _combo_display(combo)
    action = cmd.get("action") or {}
    if action.get("type") == "scroll":
        return f"the mouse wheel, scrolling {action.get('direction', '')}".strip()
    return "a voice-only action with no key"


def _labels_speech(labels: list[str]) -> str:
    uniq = list(dict.fromkeys(labels))
    text = ", ".join(uniq[:MAX_SPOKEN])
    if len(uniq) > MAX_SPOKEN:
        text += f", and {len(uniq) - MAX_SPOKEN} more"
    return text


def _reference_items() -> list[tuple[Combo, list[str]]]:
    out = []
    for keys, descr in KEYBIND_REFERENCE.items():
        parts = _parse_keys_string(keys)
        out.append(((tuple(parts[:-1]), parts[-1]), descr))
    return out


def keybind_answer(key_phrase: str, commands: list[dict]) -> Answer | None:
    q = _parse_spoken_combo(key_phrase)
    if q is None:
        return None
    disp = _combo_display(q)
    # KEYBINDS payload is the canonical key ("alt+f4"); the page filter can't parse the display form.
    kb_payload = {"kind": "by_key", "key": _combo_str(q)}
    exact: list[str] = []
    related: dict[str, list[str]] = {}
    for cmd in commands:
        c = _command_combo(cmd)
        if c is None:
            continue
        if _combo_matches(q, c):
            exact.append(_label(cmd))
        elif _key_ok(q[1], c[1]) or any(_key_ok(q[1], m) for m in c[0]):
            related.setdefault(_combo_display(c), []).append(_label(cmd))
    details = [f"{k}: {', '.join(v)}" for k, v in related.items()]
    if exact:
        return Answer(f"{disp} is bound to {_labels_speech(exact)}.",
                      page="KEYBINDS", payload=kb_payload, details=details)
    if related:
        combos = list(related.items())[:3]
        spoken = "; ".join(f"{k} is bound to {_labels_speech(v)}" for k, v in combos)
        return Answer(f"Nothing in your commands uses {disp} by itself. {spoken}.",
                      page="KEYBINDS", payload=kb_payload, details=details)
    ref_exact = [d for c, descr in _reference_items() if _combo_matches(q, c) for d in descr]
    if ref_exact:
        return Answer(f"{disp} isn't used by your voice commands. In the default Star Citizen controls "
                      f"it is: {'; '.join(ref_exact)}.",
                      page="KEYBINDS", payload=kb_payload)
    ref_related = [(c, descr) for c, descr in _reference_items() if _key_ok(q[1], c[1])]
    if ref_related:
        c, descr = ref_related[0]
        return Answer(f"Nothing in your commands uses {disp}. In the default Star Citizen controls "
                      f"{_combo_display(c)} is: {'; '.join(descr)}.",
                      page="KEYBINDS", payload=kb_payload)
    return Answer(f"Nothing in your commands uses {disp}, and I have no default Star Citizen binding for it.",
                  page="KEYBINDS", payload=kb_payload)


def reverse_keybind_answer(name: str, commands: list[dict]) -> Answer | None:
    q = _clean_name(name, ("command", "action"))
    if not q:
        return None
    best_score, best_cmd = 0.0, None
    for cmd in commands:
        names = [_label(cmd).lower(), str(cmd.get("id", "")).replace("_", " ")] + \
                [str(p).lower() for p in cmd.get("phrases", [])]
        score = max((1.0 if n == q else difflib.SequenceMatcher(None, q, n).ratio()) for n in names if n) \
            if any(names) else 0.0
        if best_cmd is None or score > best_score:
            best_score, best_cmd = score, cmd
    if best_cmd is None or best_score < 0.75:
        return Answer(f"I couldn't find a command called {q}.")
    cmd = best_cmd
    return Answer(f"{_label(cmd)} is on {_command_key_display(cmd)}.",
                  page="KEYBINDS", payload={"kind": "by_command", "command_id": cmd.get("id", "")})


_KEY_PATTERNS = [
    r"^what is (.+?) bound to$",
    r"^what is (.+?) mapped to$",
    r"^what does (.+?) do$",
    r"^what is bound to (.+)$",
    r"^what is (?:the )?(?:key ?)?bind(?:ing)? (?:for|on) (.+)$",
    r"^what is (?:the )?keybind(?:ing)? (?:for|on) (.+)$",
]
_REVERSE_KEY_PATTERNS = [
    r"^(?:what|which) (?:key|button) (?:is|does|for|controls|toggles) (.+?)(?: use| on| bound to| mapped to)?$",
    r"^what is the (?:key|button) (?:for|to) (.+)$",
    r"^(?:what|which) (?:key|button) (?:is )?(?:used )?for (.+)$",
]


def _keybind_handler(text: str, commands: list[dict]) -> Answer | None:
    raw = _first_match(_KEY_PATTERNS, text)
    if raw:
        a = keybind_answer(raw, commands)
        if a is not None:
            return a
        if text.startswith(("what is the bind", "what is the keybind", "what is the key bind")):
            return reverse_keybind_answer(raw, commands)
        return None
    raw = _first_match(_REVERSE_KEY_PATTERNS, text)
    if raw:
        return reverse_keybind_answer(raw, commands)
    return None


# ================================================================ mining signatures

_SIG_KEYS = ("what resource", "which resource", "what ore", "which ore", "what mineral", "which mineral",
             "resource is", "ore is", "signature is", "signature for", "resource for", "what signature",
             "what is signature", "which rock", "what rock", "what is the signature")


def extract_signature(text: str) -> int | None:
    if not any(k in text for k in _SIG_KEYS):
        return None
    values = [int(x.replace(",", "")) for x in re.findall(r"\b\d[\d,]*\b", text)]
    values += scwiki.spoken_numbers(text)
    for v in reversed(values):
        if v >= 1000:
            return v
    return None


def _signature_handler(text: str, _commands: list[dict]) -> Answer | None:
    sig = extract_signature(text)
    if sig is None:
        return None
    result = mining_data.reverse_lookup(sig)
    details = [f"{m.label()} = {m.value:,} (off by {m.diff:,})" for m in result.candidates(5)]
    return Answer(result.speech(), page="MINING MODE", payload=result, details=details)


# ================================================================ wiki item lookups

_UNREACHABLE = "Sorry, I couldn't reach the Star Citizen Wiki to look up {}."

_WEAPON_PATTERNS = [
    r"^where (?:can|do|could) i (?:buy|get|find) (.+?) (?:ship |vehicle )?weapons?$",
    r"^list (?:the )?(?:ship )?weapon locations (?:for|of) (.+)$",
    r"^(?:list|show|find) (?:me )?(?:the )?locations (?:for|of) (.+?) (?:ship |vehicle )?weapons?$",
    r"^(?:what|which) locations (?:sell|have) (.+?) (?:ship |vehicle )?weapons?$",
    r"^where is (.+?) (?:ship |vehicle )?weapons? sold$",
]
_SHIP_PATTERNS = [
    r"^where (?:can|do|could) i rent (.+)$",
    r"^where (?:can|do|could) i (?:buy|get) (.+?) ship$",
    r"^how much (?:is|does|do|are) (.+?) ships? (?:cost|costs|to buy|to rent)?$",
    r"^what does (.+?) ship cost$",
    r"^(?:find|show me|show) (?:the )?ship (.+)$",
    r"^(?:what are |what is )?(?:the )?(?:rental|purchase|buy) (?:price|prices|locations?) (?:for|of) (.+)$",
]
_COMPONENT_PATTERNS = [
    r"^where (?:can|do|could) i (?:buy|get|find) (.+)$",
    r"^where is (.+?) sold$",
    r"^(?:list|show|find) (?:me )?(?:the )?locations (?:for|of) (.+)$",
    r"^(?:what|which) locations (?:sell|have) (.+)$",
    r"^where (?:do they|does anyone) sell (.+)$",
]
_MINING_PATTERNS = [  # (pattern, explicit)
    (r"^where (?:can|do|should|could) i mine (.+)$", True),
    (r"^where to mine (.+)$", True),
    (r"^where (?:is|are) (.+?) mined$", True),
    (r"^(?:list|show|find) (?:me )?(?:the )?mining locations (?:for|of) (.+)$", True),
    (r"^where (?:can|do|could) i find (.+?) (?:for mining|to mine)$", True),
    (r"^where (?:can|do|could) i find (.+)$", False),
    (r"^where (?:is|are) (.+?) found$", False),
    # Vosk mishears "mine" (e.g. "might"); accept variants only when a known mineral follows.
    (r"^where (?:can|do|should|could) i (?:might|mind|my|mean|man|mining|mined|mines) (.+)$", False),
]


def _ship_answer(name: str, client: scwiki.ScWikiClient) -> Answer:
    try:
        r = client.find_ship(name)
    except scwiki.NotFound:
        return Answer(f"I could not find a ship called {name}.")
    except scwiki.ScWikiError as e:
        return Answer(_UNREACHABLE.format(f"the {name}"), details=[str(e)])
    details = ([r.note] if r.note else []) + r.lines()[:12]
    return Answer(scwiki.ship_speech(r), page="SHIP FINDER", payload=r, details=details)


def _try_ship(name: str, client: scwiki.ScWikiClient) -> Answer | None:
    try:
        r = client.find_ship(name)
    except scwiki.ScWikiError:
        return None
    if r.offline or r.purchase or r.rental:
        details = ([r.note] if r.note else []) + r.lines()[:12]
        return Answer(scwiki.ship_speech(r), page="SHIP FINDER", payload=r, details=details)
    return None


def _item_answer(name: str, weapon: bool) -> Answer:
    client = scwiki.default_client()
    page = "SHIP WEAPONS" if weapon else "COMPONENTS"
    try:
        item = client.search_ship_weapon(name) if weapon else client.search_component(name)
    except scwiki.NotFound:
        if not weapon:
            ship = _try_ship(name, client)
            if ship:
                return ship
        what = f"the ship weapon {name}" if weapon else name
        return Answer(f"I could not find current Star Citizen Wiki locations for {what}.")
    except scwiki.ScWikiError as e:
        return Answer(_UNREACHABLE.format(name), details=[str(e)])
    if not weapon and item.is_vehicle:
        ship = _try_ship(item.name, client)
        if ship:
            return ship
    return Answer(scwiki.item_speech(item), page=page, payload=item, details=item.lines()[:10])


def _weapon_handler(text: str, _commands: list[dict]) -> Answer | None:
    raw = _first_match(_WEAPON_PATTERNS, text)
    name = _clean_name(raw or "", ("ship",))
    return _item_answer(name, weapon=True) if name else None


def _ship_handler(text: str, _commands: list[dict]) -> Answer | None:
    raw = _first_match(_SHIP_PATTERNS, text)
    name = _clean_name(raw or "", ("ship", "spaceship"))
    return _ship_answer(name, scwiki.default_client()) if name else None


def _component_handler(text: str, _commands: list[dict]) -> Answer | None:
    raw = _first_match(_COMPONENT_PATTERNS, text)
    name = _clean_name(raw or "", ("components", "component", "item"))
    return _item_answer(name, weapon=False) if name else None


def _mining_handler(text: str, _commands: list[dict]) -> Answer | None:
    for pattern, explicit in _MINING_PATTERNS:
        m = re.search(pattern, text)
        if not m:
            continue
        resource = re.sub(r"\b(?:ore|ores|resource|mineral|minerals)\b", "", _clean_name(m.group(1))).strip()
        ore = mining_data.normalize_ore(resource)
        if not resource or (not explicit and ore is None):
            return None
        display = mining_data.wiki_title(ore) if ore else resource.title()
        try:
            r = scwiki.default_client().lookup_mining_locations(ore or resource)
        except scwiki.NotFound:
            return Answer(f"I could not find mining locations for {display}.")
        except scwiki.ScWikiError as e:
            return Answer(_UNREACHABLE.format(f"{display} mining locations"), details=[str(e)])
        details = ([r.note] if r.note else []) + r.lines()[:15]
        return Answer(scwiki.mining_speech(r), page="MINING MODE", payload=r, details=details)
    return None


# ================================================================ commodities

_COMMODITY_PATTERNS = [
    r"^what is the (?:price|value|sell price|selling price|sale price) (?:of|for) (.+)$",
    r"^(?:what are |what is )?(?:the )?(?:prices?|values?) (?:of|for) (.+)$",
    r"^how much (?:is|does|do|are) (.+?) (?:sell|sells|selling|go|going|worth|trade|trading)(?: for)?$",
    r"^how much can i (?:get|sell) (?:for )?(.+?)(?: for)?$",
    r"^where (?:can|do|should|could) i sell (.+)$",
    r"^where to sell (.+)$",
    r"^what is (.+?) (?:selling|trading|going) for$",
    r"^(?:what|where) is the best (?:place|price) to sell (.+)$",
]


def _commodity_handler(text: str, _commands: list[dict]) -> Answer | None:
    raw = _first_match(_COMMODITY_PATTERNS, text)
    name = _clean_name(raw or "", ("right now", "at the moment", "per scu", "commodity", "commodities"))
    if not name:
        return None
    try:
        result = uex.get_client().lookup(name)
    except uex.UexError as e:
        return Answer(f"Sorry, I couldn't reach UEX to look up {name} prices.", details=[str(e)])
    if result is None:
        return Answer(f"UEX has no commodity called {name}.")
    details = [f"Sell to {l.location}: {l.price_sell:,.0f}" for l in result.sell_to(5)]
    details += [f"Buy from {l.location}: {l.price_buy:,.0f}" for l in result.buy_from(5)]
    return Answer(uex.price_speech(result), page="COMMODITIES", payload=result, details=details)


# ================================================================ wiki

_WIKI_PATTERNS = [
    r"^tell me about (.+)$",
    r"^who (?:is|are|was|were) (.+)$",
    r"^what (?:is|are) (?:an?) (.+)$",
    r"^(?:search|check|look up|lookup) (?:the )?wiki (?:for|about|on) (.+)$",
    r"^what does the wiki say about (.+)$",
    r"^(?:show|find) (?:me )?(?:the )?wiki (?:page |entry )?(?:for|about|on) (.+)$",
]


def _wiki_handler(text: str, _commands: list[dict]) -> Answer | None:
    topic = _clean_name(_first_match(_WIKI_PATTERNS, text) or "")
    if not topic:
        return None
    try:
        r = wiki.default_client().lookup(topic)
    except wiki.WikiError as e:
        return Answer(f"Sorry, I couldn't reach the Star Citizen wiki to look up {topic}.", details=[str(e)])
    if not r.title:
        return Answer(f"The Star Citizen wiki has nothing on {topic}.")
    speech = wiki.first_sentences(r.summary) or f"I found the {r.title} page on the wiki."
    return Answer(speech, page="WIKI", payload=r, details=[r.url] + [h.title for h in r.hits[1:5]])


# ================================================================ entry point

_HANDLERS: list[Callable[[str, list[dict]], Answer | None]] = [
    _signature_handler,
    _keybind_handler,
    _commodity_handler,
    _weapon_handler,
    _ship_handler,
    _mining_handler,
    _component_handler,
    _wiki_handler,
]


def answer(text: str, commands: list[dict]) -> Answer | None:
    """Answer a spoken question; None if not understood. Never raises."""
    try:
        if not isinstance(text, str):
            return None
        t = _normalize(text)
        if not t:
            return None
        cmds: list[Any] = commands.all() if hasattr(commands, "all") else list(commands or [])
        cmds = [c for c in cmds if isinstance(c, dict)]
        for handler in _HANDLERS:
            result = handler(t, cmds)
            if result is not None:
                return result
        return None
    except Exception as e:  # noqa: BLE001 - contract: never raise
        log.exception("question answering failed for %r", text)
        return Answer("Sorry, something went wrong while answering that question.",
                      details=[f"{type(e).__name__}: {e}"])
