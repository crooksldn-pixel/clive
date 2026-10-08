"""Who asks: one TOML file per persona in app/bench/personas/, read and checked here.

Why files: George adds people (docs/BENCH.md says how), and a persona is something he should be able
to read and change without touching code. What a file must say is checked when it is read, so a
persona with a missing goal or an access level CLIVE has no door for is refused by name rather than
run half-described.

What it promises:
- Only the two doors CLIVE has: "owner" (his) or "staff" (the team's). A staff persona must say what
  its people card says about them (`card_role`), because that is what their assistant is told.
- The kinds of question a persona is asked for are the five the generator knows; their weights are
  whole numbers above zero.
- A persona's fingerprint is the hash of its file, so a question set records which version of each
  persona it was generated from.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).resolve().parent / "personas"
ACCESS = ("owner", "staff")
KINDS = ("in_scope", "out_of_scope", "ambiguous", "multi_step", "adversarial")
ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
REQUIRED = ("id", "name", "access", "role", "knows_clive", "goals", "style", "language", "examples", "mix")


class PersonaError(ValueError):
    """A persona file that does not say enough to be asked for, or says something CLIVE has no door for."""


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    access: str
    role: str
    knows_clive: str
    goals: tuple[str, ...]
    style: str
    language: str
    examples: tuple[str, ...]
    mix: dict[str, int]
    card_role: str = ""
    sources: tuple[str, ...] = ()
    fingerprint: str = ""
    path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def login(self) -> str:
        """The Tailscale login a staff persona's requests carry in the fake world. Invented, and
        on example's domain, so it can never be anyone's."""
        return f"{self.id}@bench.example"

    def brief(self) -> dict[str, Any]:
        """What the generator and the judge are told about this person."""
        return {
            "id": self.id, "name": self.name, "door": self.access, "role": self.role,
            "knows_about_clive": self.knows_clive, "goals": list(self.goals), "style": self.style,
            "language": self.language, "examples_of_how_they_write": list(self.examples),
        }


def _text(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PersonaError(f"{path.name}: {key} must be some words")
    return " ".join(value.split())


def _lines(raw: dict[str, Any], key: str, path: Path) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        raise PersonaError(f"{path.name}: {key} must be a list of at least one line")
    return tuple(" ".join(v.split()) for v in value)


def _mix(raw: dict[str, Any], path: Path) -> dict[str, int]:
    mix = raw.get("mix")
    if not isinstance(mix, dict) or not mix:
        raise PersonaError(f"{path.name}: mix must give at least one kind of question a weight")
    out: dict[str, int] = {}
    for kind, weight in mix.items():
        if kind not in KINDS:
            raise PersonaError(f"{path.name}: {kind!r} is not a kind of question ({', '.join(KINDS)})")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
            raise PersonaError(f"{path.name}: the weight of {kind} must be a whole number above zero")
        out[kind] = weight
    return out


def read(path: Path) -> Persona:
    """One persona file, checked."""
    blob = path.read_bytes()
    try:
        raw = tomllib.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PersonaError(f"{path.name}: not readable TOML ({exc})") from None
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise PersonaError(f"{path.name}: says nothing about {', '.join(missing)}")
    persona_id = str(raw.get("id") or "")
    if not ID.fullmatch(persona_id) or persona_id != path.stem:
        raise PersonaError(f"{path.name}: id must be lower-case words joined by hyphens, and the file's own name")
    access = str(raw.get("access") or "")
    if access not in ACCESS:
        raise PersonaError(f"{path.name}: access must be one of {', '.join(ACCESS)}: the doors CLIVE has")
    card_role = " ".join(str(raw.get("card_role") or "").split())
    if access == "staff" and not card_role:
        raise PersonaError(f"{path.name}: a staff persona needs card_role, what their people card says they do")
    known = set(REQUIRED) | {"card_role", "sources"}
    return Persona(
        id=persona_id, name=_text(raw, "name", path), access=access, role=_text(raw, "role", path),
        knows_clive=_text(raw, "knows_clive", path), goals=_lines(raw, "goals", path),
        style=_text(raw, "style", path), language=_text(raw, "language", path),
        examples=_lines(raw, "examples", path), mix=_mix(raw, path), card_role=card_role,
        sources=tuple(str(s) for s in raw.get("sources") or ()),
        fingerprint=hashlib.sha256(blob).hexdigest()[:12], path=str(path),
        extra={k: v for k, v in raw.items() if k not in known},
    )


def load(folder: Path | None = None, *, only: list[str] | tuple[str, ...] = ()) -> list[Persona]:
    """Every persona in the folder, in file-name order; `only` names the ones wanted, and a name
    that is not there is an error rather than a smaller run."""
    folder = folder or FOLDER
    found = [read(path) for path in sorted(folder.glob("*.toml"))]
    if not only:
        return found
    by_id = {p.id: p for p in found}
    unknown = [name for name in only if name not in by_id]
    if unknown:
        raise PersonaError(f"no persona called {', '.join(unknown)} (there are: {', '.join(by_id)})")
    return [by_id[name] for name in only]


def split(total: int, mix: dict[str, int]) -> dict[str, int]:
    """`total` questions shared across the kinds by their weights, largest remainder first, so the
    counts always add up to `total` and a kind with any weight gets one once total allows."""
    weights = {k: w for k, w in mix.items() if w > 0}
    whole = sum(weights.values())
    if total <= 0 or not whole:
        return {k: 0 for k in weights}
    exact = {k: total * w / whole for k, w in weights.items()}
    counts = {k: int(v) for k, v in exact.items()}
    left = total - sum(counts.values())
    for kind in sorted(weights, key=lambda k: (-(exact[k] - counts[k]), -weights[k], k))[:left]:
        counts[kind] += 1
    return counts
