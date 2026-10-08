"""CLIVE's own Gmail drafts: which drafts CLIVE made, and taking away the ones it left unsent.

Ruling 28 of DEC-071 (George, 8 October): "Let CLIVE delete the unused Gmail drafts it leaves
behind?" — "Y". CLIVE removes drafts it made and that were never sent; never a draft George or
anyone else wrote.

Provenance is CLIVE's own record, written the moment Gmail answers CLIVE's own create call
(app/tools/gmail_writes.py `_settle_draft`): the draft id and message id Gmail handed back, the
thread, the Message-ID CLIVE minted for it, a fingerprint of the words as Gmail then held them
(read back from Gmail), whether it is a reply or a new email, when, and who held the card that made
it. No address, subject or words are kept. A draft that is not in this record is never touched here.

A recorded draft is CLIVE's to delete only while every one of these still holds, read from Gmail
just before the delete: it is still a draft (never sent); its Gmail message id is the one Gmail gave
CLIVE (Gmail gives a draft edited in Gmail a new one); its Message-ID header is CLIVE's own; and its
words are the words CLIVE wrote. A draft that fails one is someone's words now: it is marked kept
and never looked at again.

When:
  - a send replaced it. A reply sent in the same thread, on the card George (or a member of the
    team) held: the card says so before the hold (`waiting_for`), and the deletion happens inside
    that change once the send is proven (`replaced`, called from gmail_writes `_settle_send`). A new
    email to someone does not replace a draft to them: it may be about something else entirely,
    so a new-email draft goes only by age.
  - it went unused for UNUSED_DAYS. Nobody sent, edited or replaced it in two weeks — long enough
    for a campaign saved as drafts to be sent over a slow week, short enough that Drafts does not
    fill with CLIVE's leftovers. CLIVE looks every SWEEP_EVERY_S, while changes are switched on, and
    deletes those itself (`sweep`). It changes nothing anyone else wrote and nothing that leaves the
    building, which is why it needs no card.
Each deletion is proven by reading back (Gmail no longer holds the draft) and recorded here with
when and why; one that cannot be proven stays waiting and is tried again on the next look.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.tools.gmail_drafts")

FILENAME = "gmail-drafts.json"
UNUSED_DAYS = 14
SWEEP_EVERY_S = 6 * 3600.0
FIRST_SWEEP_S = 600.0          # after a start, the first look waits for the service to settle
MAX_PER_SWEEP = 25             # drafts deleted in one look, at most; the rest wait for the next
CALL_TIMEOUT_S = 15.0          # one Gmail call, at most
KEEP_SETTLED_S = 90 * 86400.0  # a settled row is dropped from the record after this long
MAX_ROWS = 2000

WAITING, SENT, DELETED, KEPT, GONE = "waiting", "sent", "deleted", "kept", "gone"

_path: Path | None = None
_lock = threading.RLock()
_client = None                 # the Gmail client, bound with gmail_writes
_task: asyncio.Task | None = None


def configure(path: Path | None) -> None:
    global _path
    with _lock:
        _path = Path(path) if path else None


def bind(client) -> None:
    global _client
    _client = client


def fingerprint(text: str) -> str:
    """The words, or an address, reduced to a fingerprint: enough to say "the same", nothing to read."""
    return hashlib.sha256(str(text or "").replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------------------- the record


def _load() -> dict[str, Any]:
    if _path is None:
        return {"version": 1, "drafts": {}}
    try:
        data = json.loads(_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "drafts": {}}
    except (OSError, ValueError):
        log.warning("CLIVE's record of its drafts could not be read; nothing is tidied until it can")
        raise
    drafts = data.get("drafts") if isinstance(data, dict) else None
    return {"version": 1, "drafts": drafts if isinstance(drafts, dict) else {}, "swept_at": data.get("swept_at") if isinstance(data, dict) else None}


def _save(data: dict[str, Any]) -> None:
    if _path is None:
        return
    _path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(_path.parent), prefix=".gmail-drafts.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _prune(drafts: dict[str, Any], now: float) -> None:
    for draft_id, row in list(drafts.items()):
        if row.get("state") != WAITING and now - float(row.get("settled_at") or now) > KEEP_SETTLED_S:
            del drafts[draft_id]
    while len(drafts) > MAX_ROWS:
        oldest = min(drafts, key=lambda k: (drafts[k].get("state") == WAITING, float(drafts[k].get("made_at") or 0)))
        del drafts[oldest]


def rows() -> list[dict[str, Any]]:
    with _lock:
        try:
            return [dict(row, draft_id=k) for k, row in _load()["drafts"].items()]
        except (OSError, ValueError):
            return []


def row(draft_id: str) -> dict[str, Any] | None:
    with _lock:
        try:
            found = _load()["drafts"].get(str(draft_id or ""))
        except (OSError, ValueError):
            return None
    return dict(found, draft_id=str(draft_id)) if isinstance(found, dict) else None


def _settle(draft_id: str, state: str, why: str = "", **extra: Any) -> None:
    with _lock:
        try:
            data = _load()
        except (OSError, ValueError):
            return
        found = data["drafts"].get(str(draft_id))
        if not isinstance(found, dict):
            return
        found.update({"state": state, "why": str(why)[:80], "settled_at": time.time(), **extra})
        _save(data)


def who_now() -> str:
    """Who held the card being committed: "owner", a member of the team's id, or "" for nobody."""
    from app.tools import authority

    held = authority.current()
    if held is None:
        return ""
    if held.kind == authority.OWNER:
        return "owner"
    return str(held.who or "") if held.kind == authority.STAFF else ""


async def _call(fn, *args, **kwargs):
    return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=CALL_TIMEOUT_S)


async def note_made(execution: dict[str, Any], created: dict[str, Any]) -> None:
    """Gmail has answered CLIVE's create: write the draft down as CLIVE's. The words' fingerprint is
    taken from Gmail's own copy of the draft, so it is compared with Gmail's copy later; when that
    read fails the fingerprint is empty and the draft is never taken away (its words cannot be
    shown to be CLIVE's). Never raises: the draft is made whatever the record says."""
    draft_id = str(created.get("draft_id") or "")
    if not draft_id or _client is None:
        return
    words = ""
    try:
        from app.tools.gmail_writes import _draft_text

        body, headers = await _draft_text(draft_id)
        if str(headers.get("message-id") or "").strip() == str(execution.get("token") or ""):
            words = fingerprint(body)
    except Exception as exc:  # noqa: BLE001 — a record without a fingerprint is one never tidied
        log.info("a draft CLIVE made could not be read back for its record (%s)", type(exc).__name__)
    entry = {
        "message_id": str(created.get("message_id") or ""), "thread_id": str(created.get("thread_id") or execution.get("thread_id") or ""),
        "token": str(execution.get("token") or ""), "words": words, "kind": "reply" if execution.get("thread_id") else "new", "by": who_now(), "made_at": time.time(), "state": WAITING,
    }
    try:
        with _lock:
            data = _load()
            data["drafts"][draft_id] = entry
            _prune(data["drafts"], time.time())
            _save(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("a draft CLIVE made could not be written down (%s); it will not be tidied", type(exc).__name__)


def note_gone(token: str, state: str = DELETED, why: str = "") -> None:
    """A recorded draft that has left Drafts through a change CLIVE made (its own undo deleting it,
    or a send of it): settled in the record, by its Message-ID."""
    for found in rows():
        if found.get("state") == WAITING and found.get("token") == str(token or ""):
            _settle(found["draft_id"], state, why)


def waiting_for(thread_id: str, *, besides: str = "") -> list[dict[str, Any]]:
    """CLIVE's reply drafts still waiting in this thread: the ones a reply sent there replaces.
    `besides` is a draft that is itself being sent, never counted."""
    if not thread_id:
        return []
    out = [found for found in rows()
           if found.get("state") == WAITING and found["draft_id"] != besides and found.get("kind") == "reply"
           and found.get("thread_id") == thread_id]
    return sorted(out, key=lambda r: float(r.get("made_at") or 0))


def words_of(draft_id: str = "", token: str = "") -> str:
    """Who a draft's words are, by CLIVE's record: "owner", a member of the team's id, "clive" for a
    draft CLIVE made with nobody's hold behind it — or "" when CLIVE did not make it (it was written
    in Gmail)."""
    for found in rows():
        if (draft_id and found["draft_id"] == draft_id) or (token and found.get("token") == token):
            return str(found.get("by") or "clive")
    return ""


# ------------------------------------------------------------------------ is it still CLIVE's


async def _still_ours(found: dict[str, Any]) -> tuple[str, str]:
    """(state, why) for a recorded draft, read from Gmail now: WAITING when it is still CLIVE's
    untouched, unsent draft; KEPT when someone has changed it; SENT or GONE when it has left Drafts."""
    from app.clients.gmail import GmailRefused
    from app.tools.gmail_writes import _draft_text

    try:
        draft = await _call(_client.get_draft, found["draft_id"])
    except GmailRefused:
        token = str(found.get("token") or "").strip("<>")
        sent = await _call(_client.find_messages, f"rfc822msgid:{token} in:sent") if token else []
        return (SENT, "sent") if sent else (GONE, "no longer in Drafts")
    message = (draft or {}).get("message") or {}
    if str(message.get("id") or "") != str(found.get("message_id") or ""):
        return KEPT, "edited since CLIVE made it"
    body, headers = await _draft_text(found["draft_id"])
    if str(headers.get("message-id") or "").strip() != str(found.get("token") or ""):
        return KEPT, "not CLIVE's Message-ID"
    if not found.get("words") or fingerprint(body) != found["words"]:
        return KEPT, "its words are not CLIVE's as written"
    return WAITING, ""


async def _take_away(found: dict[str, Any], why: str) -> str:
    """Delete one of CLIVE's drafts and prove it gone. Returns the state it settled in, or WAITING
    when it could not be done or proven (it is tried again later)."""
    from app import readonly
    from app.clients.gmail import GmailRefused

    if readonly.active():
        return WAITING
    try:
        state, said = await _still_ours(found)
    except Exception as exc:  # noqa: BLE001 — not read, not touched
        log.info("a draft of CLIVE's could not be checked (%s); left for the next look", type(exc).__name__)
        return WAITING
    if state != WAITING:
        _settle(found["draft_id"], state, said)
        return state
    try:
        await _call(_client.delete_draft, found["draft_id"])
    except Exception as exc:  # noqa: BLE001 — the read-back below decides
        log.info("deleting a draft of CLIVE's answered %s", type(exc).__name__)
    try:
        await _call(_client.get_draft, found["draft_id"])
    except GmailRefused:
        _settle(found["draft_id"], DELETED, why)
        _timeline("draft_tidied", why=why)
        return DELETED
    except Exception as exc:  # noqa: BLE001 — unproven: still waiting
        log.info("a deleted draft could not be read back (%s)", type(exc).__name__)
        return WAITING
    log.warning("a draft of CLIVE's is still in Gmail after its delete; tried again later")
    return WAITING


def _timeline(event: str, **fields: Any) -> None:
    try:
        from app.observability import timeline

        timeline.emit(event, **fields)
    except Exception:  # noqa: BLE001 — the record is a courtesy here; the store already has it
        pass


# ------------------------------------------------------------------------------- when


def replaces_line(drafts: list[dict[str, Any]]) -> str:
    """The card's words for the drafts a send will take away, from the record (nobody's words)."""
    if not drafts:
        return ""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    made = datetime.fromtimestamp(float(drafts[0].get("made_at") or time.time()), ZoneInfo("Europe/London"))
    when = f"{made.day} {made.strftime('%b')}"
    if len(drafts) == 1:
        return f"CLIVE's unsent draft here from {when} is deleted once this goes"
    return f"CLIVE's {len(drafts)} unsent drafts here (from {when}) are deleted once this goes"


async def replaceable(thread_id: str, *, besides: str = "") -> list[dict[str, Any]]:
    """The drafts a reply sent in this thread would take away, as Gmail holds them now: CLIVE's own
    reply drafts here that are still untouched and unsent. Read when the card is made, so the card
    says only what is true; any that has changed is settled in the record and left alone. Empty
    when Gmail cannot be asked — then the card says nothing and nothing is taken away."""
    if _client is None:
        return []
    out = []
    for found in waiting_for(thread_id, besides=besides):
        try:
            state, why = await _still_ours(found)
        except Exception as exc:  # noqa: BLE001 — not read: not named on the card, not touched
            log.info("a draft of CLIVE's could not be checked for the card (%s)", type(exc).__name__)
            continue
        if state == WAITING:
            out.append(found)
        else:
            _settle(found["draft_id"], state, why)
    return out


async def replaced(draft_ids: list[str]) -> str:
    """A reply the card said would replace these drafts has been proven sent: take them away, each
    checked again first. The note for after the send's success line — said only when one was not
    taken away (it changed meanwhile, or the delete could not be proven)."""
    if _client is None or not draft_ids:
        return ""
    left = kept = 0
    for draft_id in draft_ids:
        found = row(draft_id)
        if found is None or found.get("state") != WAITING:
            continue
        state = await _take_away(found, "a send replaced it")
        if state == WAITING:
            left += 1
        elif state == KEPT:
            kept += 1
    notes = []
    if kept:
        notes.append("CLIVE's earlier draft was changed meanwhile, so it was kept." if kept == 1 else f"{kept} of CLIVE's earlier drafts were changed meanwhile, so they were kept.")
    if left:
        notes.append("CLIVE's earlier draft could not be deleted just now; it is still in Drafts and CLIVE tries again later."
                     if left == 1 else f"{left} of CLIVE's earlier drafts could not be deleted just now; they are still in Drafts and CLIVE tries again later.")
    return " ".join(notes)


async def sweep(now: float | None = None) -> dict[str, int]:
    """One look: CLIVE's drafts unused for UNUSED_DAYS, each checked and taken away, at most
    MAX_PER_SWEEP. Counts of what became of them."""
    now = time.time() if now is None else now
    counts = {DELETED: 0, KEPT: 0, SENT: 0, GONE: 0, WAITING: 0}
    if _client is None:
        return counts
    old = [r for r in rows() if r.get("state") == WAITING and now - float(r.get("made_at") or now) >= UNUSED_DAYS * 86400]
    for found in sorted(old, key=lambda r: float(r.get("made_at") or 0))[:MAX_PER_SWEEP]:
        state = await _take_away(found, f"unused for {UNUSED_DAYS} days")
        counts[state] = counts.get(state, 0) + 1
    with _lock, contextlib.suppress(OSError, ValueError):
        data = _load()
        data["swept_at"] = now
        _prune(data["drafts"], now)
        _save(data)
    if old:
        log.info("CLIVE's drafts: %s", ", ".join(f"{k} {v}" for k, v in counts.items() if v))
    return counts


# --------------------------------------------------------------------------- the clock


def start(writes_enabled) -> None:
    """Look every SWEEP_EVERY_S while the process runs (app/main.py's lifespan starts it), and only
    while changes are switched on (`writes_enabled()` read at each look)."""
    global _task
    loop = asyncio.get_running_loop()
    if _task is not None and not _task.done() and _task.get_loop() is loop:
        return
    _task = loop.create_task(_loop(writes_enabled), name="gmail-drafts")


async def _loop(writes_enabled) -> None:
    await asyncio.sleep(FIRST_SWEEP_S)
    while True:
        try:
            if writes_enabled():
                await sweep()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a look that fails is tried again next time
            log.warning("tidying CLIVE's drafts did not complete (%s)", type(exc).__name__)
        await asyncio.sleep(SWEEP_EVERY_S)


async def stop() -> None:
    """Stop looking. Never raises: it runs as the service shuts down."""
    global _task
    task, _task = _task, None
    if task is None or task.done():
        return
    try:
        if task.get_loop() is not asyncio.get_running_loop():
            return              # a clock of an event loop that has gone; nothing of it is running
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    except Exception as exc:  # noqa: BLE001 — shutting down
        log.debug("the drafts clock did not stop cleanly (%s)", type(exc).__name__)


# ------------------------------------------------------------------ whose words (ruling 34)
#
# George, 8 October (DEC-071, ruling 34): a member of the team may send a draft he left, on their own
# hold. So a draft says whose words it is — his, written in Gmail (a draft CLIVE did not make is the
# mailbox's own, which is his); his or a team member's, drafted with CLIVE (by this record) — and the
# card says who sends it. Words are said from where the asker stands: "Yours" to whoever wrote them.


def first_name(person_id: str) -> str:
    try:
        from app.people.store import people

        person = people.get(person_id)
    except Exception:  # noqa: BLE001 — the team's record unreadable just now: their id says who
        person = None
    name = str(getattr(person, "name", "") or "").strip()
    return (name.split() or [person_id])[0]


def whose(by: str, asker: str) -> str:
    """Whose words a draft is, said to `asker` ("owner", or a team member's id): `by` is what
    `words_of` read from the record ("" for a draft written in Gmail)."""
    mine = (by in ("", "owner", "clive") and asker == "owner") or (by == asker and asker)
    if by == "":
        return "Yours, written in Gmail" if mine else "George's, written in Gmail"
    if by in ("owner", "clive"):
        return "Yours, drafted with CLIVE" if mine else "George's, drafted with CLIVE"
    return "Yours, drafted with CLIVE" if mine else f"{first_name(by)}'s, drafted with CLIVE"


def whose_draft(draft: dict[str, Any], *, required: bool = False) -> dict[str, str]:
    """Whose words a draft waiting in Gmail is, and whose hold would send it, for its card: from this
    record ("" — written in Gmail — when CLIVE did not make it) and the authority asking now. A member
    of the team is refused a draft another member drafted with CLIVE: George's drafts, and their own,
    are the ones they may send (ruling 34)."""
    asker = who_now()
    if required and not asker:
        raise ToolError("Nobody is signed in to send it, so nothing was prepared.")
    by = words_of(draft_id=str(draft.get("draft_id") or ""), token=str(draft.get("token") or ""))
    if asker not in ("owner", "") and by not in ("", "owner", "clive", asker):
        raise ToolError(f"That draft is {first_name(by)}'s words, drafted with CLIVE: they or George send it. Nothing was prepared.")
    return {"by": by, "asker": asker, "words_line": whose(by, asker), "sender_line": sender_line(asker)}


def sender_line(asker: str) -> str:
    """Who sends it, said on the card: the one whose hold will send it."""
    if asker == "owner":
        return "You, on your hold"
    return f"{first_name(asker)}, on their own hold" if asker else "Nobody: no one is signed in"


MAX_LISTED = 10


@tool(
    name="gmail_unsent",
    description="The drafts waiting unsent in Gmail (≤10): to whom, the subject, whose words. gmail_send_draft sends one as written.",
    input_schema={"type": "object", "properties": {}},
    tier=Tier.AMBER,
    timeout_s=15.0,
)
async def gmail_unsent() -> dict[str, Any]:
    """Read only: the drafts as Gmail holds them now, each with its thread (issued, so it can be
    sent), its recipient, its subject, the start of its words and whose words they are."""
    from email.utils import parseaddr

    from app.tools.gmail_writes import _draft_text

    if _client is None:
        raise ToolError("Gmail is not configured on this backend.")
    asker = who_now()
    listed = await _call(_client.list_drafts, "in:draft")
    out = []
    for d in listed[:MAX_LISTED]:
        try:
            body, headers = await _draft_text(d["draft_id"])
        except Exception as exc:  # noqa: BLE001 — one unreadable draft is said as that, not guessed at
            log.info("a draft could not be read for the list (%s)", type(exc).__name__)
            out.append({"thread_id": d.get("thread_id") or "", "unreadable": True})
            continue
        name, address = parseaddr(headers.get("to", ""))
        token = str(headers.get("message-id") or "").strip()
        out.append({
            "thread_id": d.get("thread_id") or "",
            "to": f"{name} <{address}>" if name else address,
            "subject": " ".join(str(headers.get("subject") or "").split())[:120],
            "reply": bool(headers.get("in-reply-to")),
            "words": whose(words_of(draft_id=d["draft_id"], token=token), asker),
            "start": " ".join(body.split())[:160],
            **({"more_than_one_recipient": True} if headers.get("cc") or headers.get("bcc") or "," in str(headers.get("to") or "") else {}),
        })
    result: dict[str, Any] = {"count": len(out), "drafts": out}
    if len(listed) >= MAX_LISTED:
        result["note"] = f"Gmail may hold more than these {MAX_LISTED}; only these were read."
    if not out:
        result["note"] = "No drafts are waiting in Gmail."
    return result
