"""Staff links: a member of the team joins CLIVE from their own phone with a link and a code, and that
phone stays signed in (ruling 35 of DEC-071, built as DEC-075; docs/STAFF_LINKS.md).

Two records, in staff-links.json beside access.json and the owner's passkeys (the root-only
directory, 0600), because a line here lets someone in, as a passkey does:

  invites  one per link the owner made with his passkey: for exactly one person on the team, single
           use, open for INVITE_TTL_S, locked after MAX_CODE_TRIES wrong codes. Kept as hashes only:
           the link's token (SHA-256: 32 random bytes need no stretching) and the six-digit code he
           tells them (HMAC with a salt of its own).
  phones   one per phone that joined: whose, when, when last used, and the hashes of its sign-in
           (the cookie's secret): the current one, the ones just handed out and not yet seen back
           (pending), and every one it was ever given and has moved past (given: a replaced current
           one, and pendings dropped when another was seen back), each kept with when it was
           superseded. A superseded one works for GRACE_S more, for requests already on their way;
           used after that it means a copy exists, so the phone is signed out, for whoever holds it,
           and George sees why on People. `given` keeps the last KEEP_GIVEN; once it has had to
           forget any (`forgot`), every sign-in the phone does not know counts as a copy too, so no
           number of renewals by a copy outlives the tell.

What it promises: nothing here is ever logged or put where the server would see it in a URL; the
link, the code and the cookie cannot be rebuilt from the file; every refusal of a join looks the same
except "wrong code", which only the holder of a real link can reach; a phone is someone only while
their card is still active staff, and a phone or link refused because the card says they are off the
team is ended there and then, so putting the card back brings neither back. What a phone may do is
not decided here: the door gives it the team's own authority (app/people/team_door.py,
app/tools/authority.py for_staff).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.people.store import PeopleError, people

FILE_NAME = "staff-links.json"
COOKIE = "__Host-clive_team"

INVITE_TTL_S = 12 * 3600          # "expires (hours)": a link made in the morning works that day
MAX_CODE_TRIES = 5                # wrong codes before the link is locked for good
ROTATE_S = 3600                   # a phone in use is handed a new sign-in every hour
GRACE_S = 120                     # the sign-in it replaced, for requests already on their way
IDLE_S = 14 * 86400               # unused this long: signed out
MAX_AGE_S = 90 * 86400            # and every phone needs a new link after this, used or not
SEEN_EVERY_S = 300                # how often "last used" is written down
KEEP_PENDING = 3
# Superseded sign-ins remembered per phone: about six weeks of eight-hour days at one renewal an hour
# (Today's own read, every 30 seconds while it is on screen, is what renews it). Past that the
# phone stops telling a guess from an old copy and takes both as a copy (see `forgot` above): only the
# owner's screen ever shows a phone's id, so a stranger cannot aim a guess at one.
KEEP_GIVEN = 256
GIVEN_HEX = 32                    # of each superseded hash, kept: 128 bits, enough to know it again
COPIED = "a copy of this phone's sign-in was used"
KEEP_ENDED_S = 30 * 86400         # ended links and phones stay on the owner's screen this long

# Joins that fail, counted in memory (a restart clears them; the per-link count is on disk). They
# hold back only joins without an open link (redeem).
ADDRESS_FAILS, ADDRESS_WINDOW_S = 10, 15 * 60
ALL_FAILS, ALL_WINDOW_S = 200, 15 * 60

TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
CODE = re.compile(r"^[0-9]{6}$")
PHONE_ID = re.compile(r"^p[0-9a-f]{16}$")
COOKIE_VALUE = re.compile(r"^(p[0-9a-f]{16})\.([A-Za-z0-9_-]{43})$")

log = logging.getLogger("crooks.team")
_LOCK = threading.RLock()
_CONFIG: dict[str, Any] = {"state_dir": None}
_CACHE: dict[str, Any] = {"signature": None, "data": None}
_FAILS: dict[str, deque] = {}
_ALL_FAILS: deque = deque()


class LinkError(ValueError):
    """The owner's step could not be taken, with a reason fit to say back."""


class JoinRefused(Exception):
    """A join refused: `code` is one of not_valid, wrong_code, locked, too_many."""

    def __init__(self, code: str, detail: str, tries_left: int | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.tries_left = code, detail, tries_left


@dataclass(frozen=True)
class Joined:
    person_id: str
    name: str
    cookie: str           # the Set-Cookie header's value


@dataclass(frozen=True)
class Seen:
    """What the door learns from a phone's cookie: who, or why not."""
    person_id: str = ""
    phone_id: str = ""
    set_cookie: str = ""  # a new sign-in to hand the phone with this answer, when one is due
    refused: str = ""     # empty when the phone is someone


NOT_VALID = "That link doesn't work any more: it was used, cancelled or has run out. Ask George for a new one."
LOCKED = "Too many wrong codes, so this link is locked. Ask George for a new one."
TOO_MANY = "Too many tries just now. Wait a quarter of an hour, then try again."


def configure(*, state_dir: Path | None) -> None:
    with _LOCK:
        _CONFIG["state_dir"] = Path(state_dir) if state_dir else None
        _CACHE.update(signature=None, data=None)
        _FAILS.clear()
        _ALL_FAILS.clear()


def identity(person_id: str) -> str:
    """Who a phone's requests are, wherever CLIVE records who: never an owner login (those have an
    "@"), never "local", and never the same as the person's own Tailscale login."""
    return f"team:{person_id}"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _code_digest(salt: str, code: str) -> str:
    return hmac.new(bytes.fromhex(salt), code.encode("ascii"), hashlib.sha256).hexdigest()


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


def _iso(stamp: float | int | None) -> str:
    return datetime.fromtimestamp(float(stamp), UTC).isoformat(timespec="seconds") if stamp else ""


# ------------------------------------------------------------------ the file

def _path() -> Path | None:
    folder = _CONFIG["state_dir"]
    return Path(folder) / FILE_NAME if folder else None


def _empty() -> dict[str, Any]:
    return {"version": 1, "invites": {}, "phones": {}}


def _load() -> dict[str, Any]:
    path = _path()
    if path is None:
        return _empty()
    try:
        info = path.stat()
    except OSError:
        _CACHE.update(signature=None, data=None)
        return _empty()
    signature = (info.st_ino, info.st_size, info.st_mtime_ns)
    if _CACHE["signature"] == signature and _CACHE["data"] is not None:
        return _CACHE["data"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()                 # unreadable lets nobody in
    data = _empty()
    if isinstance(raw, dict):
        for key in ("invites", "phones"):
            if isinstance(raw.get(key), dict):
                data[key] = {str(k): v for k, v in raw[key].items() if isinstance(v, dict)}
    _CACHE.update(signature=signature, data=data)
    return data


def _save(data: dict[str, Any]) -> None:
    path = _path()
    if path is None:
        raise LinkError("staff links are not set up on this server")
    _prune(data, time.time())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".staff-links.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    _CACHE.update(signature=None, data=None)


def _prune(data: dict[str, Any], now: float) -> None:
    for key, invite in list(data["invites"].items()):
        ended = float(invite.get("ended_at") or invite.get("expires_at") or 0)
        if now - ended > KEEP_ENDED_S:
            del data["invites"][key]
    for phone_id, phone in list(data["phones"].items()):
        if phone.get("state") != "active" and now - float(phone.get("ended_at") or 0) > KEEP_ENDED_S:
            del data["phones"][phone_id]


def _copy() -> dict[str, Any]:
    data = _load()
    return {"version": 1, "invites": {k: dict(v) for k, v in data["invites"].items()},
            "phones": {k: dict(v) for k, v in data["phones"].items()}}


# ------------------------------------------------------------------ who may hold a link

def _on_the_team(person_id: str):
    """The card, if it is still active staff; None otherwise. An unreadable people record is None."""
    return _standing(person_id)[0]


def _standing(person_id: str):
    """(card, off_for_good). The card if it is still active staff. Otherwise None, and whether the
    people record says they are off the team (taken off, made a contact, or not on it at all), which
    ends their phones and links for good, rather than that it could not be read just now, which only
    refuses this once."""
    try:
        person = people.get(person_id)
    except PeopleError:
        return None, False
    if person is None or person.kind != "staff" or not person.active:
        return None, True
    return person, False


# ------------------------------------------------------------------ the owner's steps

def make(person_id: str, *, by: str, passkey: str = "", now: float | None = None) -> tuple[str, str, float]:
    """A new link for this member of the team: (token, code, expires_at). Only the route that has just
    checked the owner's passkey for exactly this person calls it (app/routes/staff_links.py). Any link
    still open for them is cancelled: there is only ever one, the one he has just been shown."""
    now = time.time() if now is None else now
    person = _on_the_team(person_id)
    if person is None:
        raise LinkError("only someone on the team, and still on it, can be given a staff link")
    token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    salt = secrets.token_hex(16)
    with _LOCK:
        data = _copy()
        _end_invites(data, person.person_id, "cancelled", now)
        data["invites"][_digest(token)] = {
            "person_id": person.person_id, "salt": salt, "code": _code_digest(salt, code), "made_at": now,
            "expires_at": now + INVITE_TTL_S, "made_by": str(by or ""), "passkey": str(passkey or "")[:200],
            "tries": 0, "state": "open"}
        _save(data)
    return token, code, now + INVITE_TTL_S


def cancel(person_id: str, *, now: float | None = None) -> bool:
    """The link waiting for this person stops working. Whether there was one."""
    now = time.time() if now is None else now
    with _LOCK:
        data = _copy()
        ended = _end_invites(data, str(person_id), "cancelled", now)
        if ended:
            _save(data)
    return bool(ended)


def sign_out(phone_id: str, *, by: str, why: str = "signed out by George", now: float | None = None) -> bool:
    """That phone is signed out at its next request. Whether it was signed in."""
    now = time.time() if now is None else now
    if not PHONE_ID.fullmatch(str(phone_id or "")):
        return False
    with _LOCK:
        data = _copy()
        phone = data["phones"].get(phone_id)
        if phone is None or phone.get("state") != "active":
            return False
        _end_phone(phone, "signed_out", by, why, now)
        _save(data)
    return True


def sign_out_person(person_id: str, *, by: str, why: str, now: float | None = None) -> int:
    """Every phone of theirs signed out and their waiting link cancelled (Take access away). How many
    phones were signed in."""
    now = time.time() if now is None else now
    with _LOCK:
        data = _copy()
        count = 0
        for phone in data["phones"].values():
            if phone.get("person_id") == person_id and phone.get("state") == "active":
                _end_phone(phone, "signed_out", by, why, now)
                count += 1
        ended = _end_invites(data, str(person_id), "cancelled", now)
        if count or ended:
            _save(data)
    return count


def _end_invites(data: dict[str, Any], person_id: str, state: str, now: float) -> int:
    ended = 0
    for invite in data["invites"].values():
        if invite.get("person_id") == person_id and invite.get("state") == "open":
            invite.update(state=state, ended_at=now)
            ended += 1
    return ended


def _end_phone(phone: dict[str, Any], state: str, by: str, why: str, now: float, *, copied: bool = False) -> None:
    phone.update(state=state, ended_at=now, ended_by=str(by or ""), why=str(why or "")[:120],
                 current="", pending=[], given=[], forgot=False, copied=bool(copied))


def _supersede(phone: dict[str, Any], hashes: list[str], now: float) -> None:
    """These sign-ins of the phone's are over as of now: remembered, so a later use is known for a copy."""
    given = [g for g in phone.get("given") or [] if isinstance(g, dict)]
    given += [{"hash": h[:GIVEN_HEX], "at": now} for h in hashes if h]
    if len(given) > KEEP_GIVEN:
        phone["forgot"] = True
        given = given[-KEEP_GIVEN:]
    phone["given"] = given


def _superseded_at(phone: dict[str, Any], digest: str) -> float | None:
    """When this sign-in stopped being the phone's own, if the phone was ever given it."""
    tag = digest[:GIVEN_HEX]
    found = [float(g.get("at") or 0) for g in phone.get("given") or []
             if isinstance(g, dict) and _same(tag, str(g.get("hash") or ""))]
    return max(found) if found else None


# ------------------------------------------------------------------ joining

def _throttled(address: str, now: float) -> bool:
    for queue, window in ((_FAILS.get(address), ADDRESS_WINDOW_S), (_ALL_FAILS, ALL_WINDOW_S)):
        while queue and now - queue[0] > window:
            queue.popleft()
    if len(_FAILS) > 5000:
        for key in [k for k, q in _FAILS.items() if not q]:
            del _FAILS[key]
    return len(_FAILS.get(address) or ()) >= ADDRESS_FAILS or len(_ALL_FAILS) >= ALL_FAILS


def _failed(address: str, now: float) -> None:
    _FAILS.setdefault(address, deque()).append(now)
    _ALL_FAILS.append(now)


def redeem(token: str, code: str, *, address: str, kind: str = "phone", now: float | None = None) -> Joined:
    """The link and the code, from the join page: this phone is signed in as the link's person, and any
    other phone of theirs is signed out (a new phone joining means the old one is gone). Raises
    JoinRefused, the same way for every link that is not open (unknown, used, cancelled, run out,
    or its person no longer on the team).

    The per-address and overall limits hold back only joins that carry no open link: a link that is
    open has its own lock (MAX_CODE_TRIES wrong codes), so made-up joins, however many and from
    wherever, never keep a real one out."""
    now = time.time() if now is None else now
    address = str(address or "unknown")[:64]
    token = str(token or "")
    code = re.sub(r"[\s-]", "", str(code or ""))[:12]
    with _LOCK:
        data = _copy()
        key = _digest(token) if TOKEN.fullmatch(token) else ""
        invite = data["invites"].get(key) if key else None
        if invite is not None and invite.get("state") == "open" and now >= float(invite.get("expires_at") or 0):
            invite.update(state="expired", ended_at=now)
            _save(data)
        person, off = _standing(str(invite.get("person_id") or "")) if invite else (None, False)
        if invite is not None and invite.get("state") == "open" and off:
            invite.update(state="cancelled", ended_at=now)      # off the team: this link is over for good
            _save(data)
        if invite is None or invite.get("state") != "open" or person is None:
            if _throttled(address, now):
                raise JoinRefused("too_many", TOO_MANY)
            _failed(address, now)
            raise JoinRefused("not_valid", NOT_VALID)
        if not (CODE.fullmatch(code) and _same(_code_digest(str(invite["salt"]), code), str(invite.get("code") or ""))):
            invite["tries"] = int(invite.get("tries") or 0) + 1
            left = MAX_CODE_TRIES - invite["tries"]
            if left <= 0:
                invite.update(state="locked", ended_at=now)
            _save(data)
            _failed(address, now)
            if left <= 0:
                raise JoinRefused("locked", LOCKED, 0)
            raise JoinRefused("wrong_code", f"That code isn't right. {left} {'try' if left == 1 else 'tries'} left.", left)
        invite.update(state="used", ended_at=now)
        for phone in data["phones"].values():
            if phone.get("person_id") == person.person_id and phone.get("state") == "active":
                _end_phone(phone, "signed_out", "", "another phone joined with a new link", now)
        phone_id = "p" + secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)
        data["phones"][phone_id] = {
            "person_id": person.person_id, "state": "active", "kind": str(kind or "phone")[:40], "joined_at": now,
            "last_seen": now, "rotated_at": now, "current": _digest(secret), "pending": [], "given": [],
            "forgot": False}
        _save(data)
    return Joined(person.person_id, person.name, cookie_header(f"{phone_id}.{secret}"))


# ------------------------------------------------------------------ a phone at the door

def cookie_header(value: str) -> str:
    return f"{COOKIE}={value}; Path=/; Max-Age={IDLE_S}; HttpOnly; Secure; SameSite=Strict"


def clear_cookie_header() -> str:
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"


def check(value: str, *, renew: bool = True, now: float | None = None) -> Seen:
    """Who the phone presenting this cookie is. Every request through the team door asks this. A new
    sign-in is handed out once an hour of use (set_cookie), and only when `renew`: the door renews
    only with Today's own quick read, never with an answer that can take minutes (a turn), whose new
    cookie could land after a newer one and put the phone back on a sign-in it had moved past. Every
    one the phone moves past keeps working for GRACE_S, and any use of one after that means a copy
    exists: the phone is signed out, for the copy and the real phone alike, and George sees why on
    People."""
    now = time.time() if now is None else now
    match = COOKIE_VALUE.fullmatch(str(value or ""))
    if not match:
        return Seen(refused="no_phone")
    phone_id, secret = match.group(1), match.group(2)
    digest = _digest(secret)
    with _LOCK:
        held = _load()["phones"].get(phone_id)
        if held is None or held.get("state") != "active":
            return Seen(refused="signed_out")
        data = _copy()
        phone = data["phones"][phone_id]
        person, off = _standing(str(phone.get("person_id") or ""))
        if person is None:
            if off:                     # off the team: putting the card back does not bring this phone back
                _end_phone(phone, "signed_out", "", "taken off the team", now)
                _save(data)
            return Seen(refused="signed_out")
        if now - float(phone.get("last_seen") or 0) > IDLE_S or now - float(phone.get("joined_at") or 0) > MAX_AGE_S:
            _end_phone(phone, "expired", "", "not used for a fortnight, or older than 90 days", now)
            _save(data)
            return Seen(refused="signed_out")
        verdict, fresh = _presented(phone, digest, now, renew=renew)
        if verdict == "copy":
            _end_phone(phone, "signed_out", "", COPIED, now, copied=True)
            _save(data)
            log.warning("team door: %s; that phone is signed out", COPIED)
            return Seen(refused="signed_out")
        if verdict == "unknown":
            return Seen(refused="signed_out")
        changed = verdict in ("promoted", "renewed")
        handed = cookie_header(f"{phone_id}.{fresh}") if fresh else ""
        if now - float(phone.get("last_seen") or 0) >= SEEN_EVERY_S:
            phone["last_seen"] = now
            changed = True
        if changed:
            _save(data)
        return Seen(person_id=str(phone["person_id"]), phone_id=phone_id, set_cookie=handed)


def _presented(phone: dict[str, Any], digest: str, now: float, *, renew: bool = True) -> tuple[str, str]:
    """(verdict, fresh secret to hand out or "") for the sign-in this phone's cookie carried, changing
    the phone's record in place. The verdict is one of:
      promoted  a sign-in just handed out, seen back: now the phone's own, and everything before it over
      renewed   its own, an hour of use is up and this answer may renew: a new one goes out with it
      current   its own
      grace     one it moved past less than GRACE_S ago: a request already on its way
      copy      one it moved past longer ago than that (or, once it has forgotten some, one it does
                not know): a copy exists
      unknown   never this phone's: refused, and nothing changes (a guess at someone else's phone)"""
    pending = [p for p in phone.get("pending") or [] if isinstance(p, dict)]
    promoted = next((p for p in pending if _same(digest, str(p.get("hash") or ""))), None)
    if promoted is not None:
        dropped = [str(p.get("hash") or "") for p in pending if p is not promoted]
        _supersede(phone, [str(phone.get("current") or ""), *dropped], now)
        phone.update(current=promoted["hash"], pending=[], rotated_at=now)
        return "promoted", ""
    if _same(digest, str(phone.get("current") or "")):
        latest = max((float(p.get("at") or 0) for p in pending), default=0.0)
        if not renew or now - float(phone.get("rotated_at") or 0) < ROTATE_S or now - latest < GRACE_S:
            return "current", ""
        fresh = secrets.token_urlsafe(32)
        kept = [*pending, {"hash": _digest(fresh), "at": now}]
        _supersede(phone, [str(p.get("hash") or "") for p in kept[:-KEEP_PENDING]], now)
        phone["pending"] = kept[-KEEP_PENDING:]
        return "renewed", fresh
    superseded = _superseded_at(phone, digest)
    if superseded is None:
        return ("copy" if phone.get("forgot") else "unknown"), ""
    return ("grace" if now - superseded <= GRACE_S else "copy"), ""


# ------------------------------------------------------------------ what George sees

def summary(now: float | None = None) -> dict[str, dict[str, Any]]:
    """Per person: their phones (kind, joined, last used, signed in or why not), their link (open until
    when, tries left, or how it ended), and `copied`: the phone of theirs signed out because a copy of
    its sign-in was used (kind, when), until a phone of theirs joins again. Never a hash, a token or a
    code."""
    now = time.time() if now is None else now
    out: dict[str, dict[str, Any]] = {}
    with _LOCK:
        data = _load()
        for phone_id, phone in sorted(data["phones"].items(), key=lambda kv: -float(kv[1].get("joined_at") or 0)):
            entry = out.setdefault(str(phone.get("person_id") or ""), {"phones": [], "link": None, "copied": None})
            entry["phones"].append({
                "phone_id": phone_id, "kind": str(phone.get("kind") or "phone"), "state": str(phone.get("state") or ""),
                "joined_at": _iso(phone.get("joined_at")), "last_seen": _iso(phone.get("last_seen")),
                "ended_at": _iso(phone.get("ended_at")), "why": str(phone.get("why") or "")})
        for person_id, phones in _by_person(data["phones"]).items():
            out[person_id]["copied"] = _copied(phones)
        for invite in sorted(data["invites"].values(), key=lambda i: float(i.get("made_at") or 0)):
            entry = out.setdefault(str(invite.get("person_id") or ""), {"phones": [], "link": None, "copied": None})
            state = str(invite.get("state") or "")
            if state == "open" and now >= float(invite.get("expires_at") or 0):
                state = "expired"
            entry["link"] = {"state": state, "made_at": _iso(invite.get("made_at")),
                             "expires_at": _iso(invite.get("expires_at")),
                             "tries_left": max(0, MAX_CODE_TRIES - int(invite.get("tries") or 0))}
    return out


def _by_person(phones: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for phone in phones.values():
        out.setdefault(str(phone.get("person_id") or ""), []).append(phone)
    return out


def _copied(phones: list[dict[str, Any]]) -> dict[str, str] | None:
    """The person's phone signed out for a copy, while no phone of theirs has joined since."""
    copied = [p for p in phones if p.get("copied")]
    if not copied:
        return None
    last = max(copied, key=lambda p: float(p.get("ended_at") or 0))
    ended = float(last.get("ended_at") or 0)
    if any(float(p.get("joined_at") or 0) > ended for p in phones):
        return None
    return {"kind": str(last.get("kind") or "phone"), "at": _iso(ended)}


def phones_signed_in(person_id: str) -> int:
    with _LOCK:
        return sum(1 for p in _load()["phones"].values()
                   if p.get("person_id") == person_id and p.get("state") == "active")
