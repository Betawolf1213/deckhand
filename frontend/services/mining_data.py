"""Mining radar signatures (single rock, SC 4.x) and offline reverse signature lookup."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

MAX_MULTIPLE = 10
NEAR_TOLERANCE = 50  # a scan read "a little off" still counts as the closest match

MINING_PRIMARY: dict[str, int] = {
    "ice": 4300,
    "aluminium": 4285,
    "iron": 4270,
    "silicon": 4255,
    "copper": 4240,
    "corundum": 4225,
    "quartz": 4210,
    "tin": 4195,
    "hephaestanite": 4180,
    "torite": 3900,
    "agricium": 3885,
    "tungsten": 3870,
    "titanium": 3855,
    "aslarite": 3840,
    "laranite": 3825,
    "bexalite": 3600,
    "gold": 3585,
    "borase": 3570,
    "taranite": 3555,
    "beryl": 3540,
    "lindinium": 3400,
    "riccite": 3385,
    "ouratite": 3370,
    "savrililum": 3200,
    "stileron": 3185,
    "quantainium": 3170,
}

MINING_DISPLAY_ORDER: list[str] = list(MINING_PRIMARY)  # table order == dict order

ORE_ALIASES: dict[str, str] = {
    "aluminum": "aluminium",
    "quantanium": "quantainium",
    "quantum": "quantainium",
    "hephaestenite": "hephaestanite",
}

# Wiki page title for each ore where it differs from ore.title().
WIKI_TITLES: dict[str, str] = {"aluminium": "Aluminum"}

# Offline hotspot snapshot, used only when the live Wiki lookup fails.
MINING_LOCATION_FALLBACK: dict[str, list[str]] = {
    "iron": [
        "Pyro V-c (Adir)", "Pyro V-b (Vatra)", "Pyro III (Bloom)", "Magda", "Lyria",
        "Calliope", "Pyro I", "Pyro II (Monox)", "microTech", "Pyro V-e (Fuego)",
        "Pyro V-f (Vuur)", "Pyro V-d (Fairo)", "Pyro IV", "Wala", "Glaciem Ring",
        "Yela Asteroid Belt", "Akiro Cluster", "Aaron Halo",
    ],
}

_FILLER = re.compile(r"\b(?:ore|ores|resource|resources|mineral|minerals|raw|some|the|a|an)\b")


def signature_values(ore: str) -> list[int]:
    base = MINING_PRIMARY[ore]
    return [base * i for i in range(1, MAX_MULTIPLE + 1)]


def table_lines() -> list[str]:
    header = f"{'ORE':<16}" + "".join(f"{str(i) + 'x':>8}" for i in range(1, MAX_MULTIPLE + 1))
    lines = [header, "-" * len(header)]
    for ore in MINING_DISPLAY_ORDER:
        lines.append(f"{ore.title():<16}" + "".join(f"{v:>8,}" for v in signature_values(ore)))
    return lines


def normalize_ore(name: str) -> str | None:
    """Map a typed or misheard mineral name to a MINING_PRIMARY key (or None)."""
    text = _FILLER.sub(" ", (name or "").lower())
    text = re.sub(r"[^a-z ]+", " ", text)
    words = text.split()
    if not words:
        return None
    for candidate in (" ".join(words), "".join(words)):
        if candidate in MINING_PRIMARY:
            return candidate
        if candidate in ORE_ALIASES:
            return ORE_ALIASES[candidate]
    vocab = list(MINING_PRIMARY) + list(ORE_ALIASES)
    joined = "".join(words)
    hit = difflib.get_close_matches(joined, vocab, n=1, cutoff=0.75)
    if hit:
        return ORE_ALIASES.get(hit[0], hit[0])
    return None


def wiki_title(ore: str) -> str:
    return WIKI_TITLES.get(ore, ore.title())


def fallback_locations(ore: str) -> list[str]:
    return list(MINING_LOCATION_FALLBACK.get(ore, []))


def signature_speech(ore: str) -> str:
    spoken = ", ".join(f"{i} X, {v:,}" for i, v in enumerate(signature_values(ore), start=1))
    return f"{ore.title()} mining signatures are: {spoken}."


@dataclass(frozen=True)
class SignatureMatch:
    ore: str
    multiple: int   # rock count
    value: int      # signature of that many rocks
    diff: int       # |value - scanned signature|

    def label(self) -> str:
        return f"{self.ore.title()} at {self.multiple} X"


@dataclass
class ReverseResult:
    signature: int
    exact: list[SignatureMatch] = field(default_factory=list)
    nearest: SignatureMatch | None = None
    _all: list[SignatureMatch] = field(default_factory=list, repr=False)

    def candidates(self, n: int = 5) -> list[SignatureMatch]:
        return self._all[:n]

    def speech(self) -> str:
        sig = f"{self.signature:,}"
        if len(self.exact) == 1:
            m = self.exact[0]
            return f"{sig} is {m.ore.title()}, at {m.multiple} X signature."
        if self.exact:
            return f"{sig} has multiple matches: " + ", ".join(m.label() for m in self.exact) + "."
        n = self.nearest
        if n is None:
            return f"I could not find a mining resource for {sig}."
        if n.diff <= NEAR_TOLERANCE:
            return (f"There is no exact match for {sig}. The closest is {n.label()}, "
                    f"with a signature of {n.value:,}.")
        return (f"There is no mining signature match for {sig}. The nearest is {n.label()}, "
                f"with {n.value:,}.")


def reverse_lookup(signature: int) -> ReverseResult:
    every: list[SignatureMatch] = []
    for ore in MINING_DISPLAY_ORDER:
        for multiple, value in enumerate(signature_values(ore), start=1):
            every.append(SignatureMatch(ore, multiple, value, abs(value - signature)))
    ranked = sorted(every, key=lambda m: m.diff)  # stable: display order breaks ties
    exact = [m for m in every if m.diff == 0]
    return ReverseResult(signature, exact, ranked[0] if ranked else None, ranked)
