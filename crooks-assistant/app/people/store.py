"""People cards: who someone is to CROOKS, in the owner's words and as fields CLIVE can use.

One JSON file (people.json beside CLIVE's other records, 0600), written atomically. A card never
grants anything: whether a staff member's login opens the door is access.py's, approved by the
owner's passkey. The card only says who they are, what they do, how to reach them, and how the
owner likes them used.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KINDS = ("staff", "contact")
MAX_PEOPLE = 50
MAX_TEXT = 400
MAX_AREAS = 12
LOGIN = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,24}$")
EMAIL = LOGIN
HANDLE = re.compile(r"^@?[A-Za-z0-9._]{1,30}$")


class PeopleError(ValueError):
    """A card that cannot be kept as asked, with a reason fit to say back."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return base[:32] or "person"


@dataclass
class Person:
    person_id: str
    name: str
    kind: str = "contact"
    role: str = ""                 # the owner's words: what they do for CROOKS
    areas: list[str] = field(default_factory=list)   # packing, email, instagram, warehouse, design ...
    email: str = ""
    instagram: str = ""
    phone: str = ""
    uses: str = ""                 # how the owner likes them used: "posters and post designs, not product design"
    notes: str = ""
    login: str = ""                # staff: the Tailscale login they sign in with
    active: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public(self, *, for_staff: bool = False) -> dict[str, Any]:
        """What a card shows. A colleague sees who someone is and what they do, not their
        phone, the owner's notes or how he likes them used."""
        out = {"person_id": self.person_id, "name": self.name, "kind": self.kind, "role": self.role,
               "areas": list(self.areas), "active": self.active}
        if not for_staff:
            out.update(email=self.email, instagram=self.instagram, phone=self.phone, uses=self.uses,
                       notes=self.notes, login=self.login)
        return out


def _clip(value: Any, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _clean_areas(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [v for v in re.split(r"[,;/]| and ", values) if v.strip()]
    out: list[str] = []
    for value in values or []:
        word = _clip(value, 40).lower()
        if word and word not in out:
            out.append(word)
    return out[:MAX_AREAS]


class PeopleStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.RLock()

    def configure(self, path: Path | None) -> None:
        with self._lock:
            self._path = Path(path) if path else None

    # ------------------------------------------------------------------ file

    def _load(self) -> dict[str, Person]:
        if self._path is None:
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise PeopleError("the people record on this server cannot be read") from None
        out: dict[str, Person] = {}
        for item in (data.get("people") if isinstance(data, dict) else None) or []:
            if not isinstance(item, dict) or not item.get("person_id"):
                continue
            known = {k: v for k, v in item.items() if k in Person.__dataclass_fields__}
            try:
                person = Person(**known)
            except TypeError:
                continue
            out[person.person_id] = person
        return out

    def _save(self, people: dict[str, Person]) -> None:
        if self._path is None:
            raise PeopleError("people are not set up on this server")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=str(self._path.parent), prefix=".people.", suffix=".tmp")
        temporary_path = Path(temporary)
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "people": [p.to_dict() for p in people.values()]}, stream, indent=1)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(self._path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ reads

    def all(self, *, include_inactive: bool = False) -> list[Person]:
        with self._lock:
            people = list(self._load().values())
        return sorted([p for p in people if include_inactive or p.active], key=lambda p: (p.kind != "staff", p.name.lower()))

    def get(self, person_id: str) -> Person | None:
        with self._lock:
            return self._load().get(str(person_id or ""))

    def find(self, text: str) -> Person | None:
        """By id, name or first name, case aside: "mia", "Mia", "Mia Jones"."""
        wanted = str(text or "").strip().lower()
        if not wanted:
            return None
        people = self.all(include_inactive=True)
        for person in people:
            if wanted in (person.person_id, person.name.lower()):
                return person
        firsts = [p for p in people if p.name.lower().split()[:1] == [wanted]]
        return firsts[0] if len(firsts) == 1 else None

    def by_login(self, login: str) -> Person | None:
        wanted = str(login or "").strip().lower()
        if not wanted:
            return None
        return next((p for p in self.all() if p.kind == "staff" and p.login == wanted), None)

    # ------------------------------------------------------------------ the one write

    def note(self, fields: dict[str, Any]) -> tuple[Person, bool]:
        """Create or update a card from the fields CLIVE read in the owner's words. Returns the
        card and whether it is new. An empty field leaves what is there."""
        name = _clip(fields.get("name"), 80)
        with self._lock:
            people = self._load()
            target = None
            if fields.get("person_id"):
                target = people.get(str(fields["person_id"]))
            if target is None and name:
                target = next((p for p in people.values() if p.name.lower() == name.lower()), None)
            created = target is None
            if created:
                if not name:
                    raise PeopleError("say who it is: a name is needed")
                if len(people) >= MAX_PEOPLE:
                    raise PeopleError(f"there are already {MAX_PEOPLE} people; take one off first")
                base = slug(name)
                person_id, n = base, 2
                while person_id in people:
                    person_id, n = f"{base}-{n}", n + 1
                target = Person(person_id=person_id, name=name)
            if fields.get("kind"):
                kind = str(fields["kind"]).strip().lower()
                if kind not in KINDS:
                    raise PeopleError("a person is staff (uses CLIVE) or a contact (someone CLIVE can ask)")
                target.kind = kind
            if name and not created:
                target.name = name
            for key in ("role", "uses", "notes"):
                if fields.get(key):
                    setattr(target, key, _clip(fields[key]))
            if fields.get("areas"):
                target.areas = _clean_areas(fields["areas"])
            if fields.get("email"):
                email = str(fields["email"]).strip().lower()
                if not EMAIL.fullmatch(email):
                    raise PeopleError("that email address does not look right")
                target.email = email
            if fields.get("instagram"):
                handle = str(fields["instagram"]).strip()
                if not HANDLE.fullmatch(handle):
                    raise PeopleError("that Instagram handle does not look right")
                target.instagram = "@" + handle.lstrip("@")
            if fields.get("phone"):
                target.phone = _clip(fields["phone"], 32)
            if fields.get("login"):
                login = str(fields["login"]).strip().lower()
                if not LOGIN.fullmatch(login):
                    raise PeopleError("a login is the email address they sign in to Tailscale with")
                clash = next((p for p in people.values() if p.login == login and p.person_id != target.person_id), None)
                if clash is not None:
                    raise PeopleError(f"that login is already {clash.name}'s")
                target.login = login
            if "active" in fields and fields["active"] is not None:
                target.active = bool(fields["active"])
            if target.kind == "contact":
                target.login = ""
            target.updated_at = _now()
            people[target.person_id] = target
            self._save(people)
        return target, created


people = PeopleStore()
