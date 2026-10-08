"""From a research file to proposals George can answer: the one way in, whichever door it came by.

Why this exists: George gives research on the Builds screen (POST /objectives/research/upload) or by
putting it in the server folder (<research dir>/inbox/, swept when the Research section is read or
by scripts/research.py). Both doors end here, and each file goes the same way, one at a time:

  1. received: kept as given, its record queued (app/research/store.py);
  2. quarantine: the digester's intake takes it in by name (kind "research",
     app/digest/intakes/research.py), as the Markdown it holds, read-only and pinned;
  3. digested: recognised, scanned and read into sections (app/digest/pipeline.py). A block-severity
     finding stops it here, before any model sees it, and the record says which rule and where;
  4. reviewed: the sections, exactly as the scanner read them, are weighed against CLIVE's design by
     the model on the Max plan (app/research/review.py, app/research/model.py);
  5. done: the proposals are written into the record, frozen, for the Builds screen.

What it promises:
- Every failure is a state with George's words (failed, stopped), never a silent empty result.
- One document is read at a time in this process, and a lock file keeps a second process
  (scripts/research.py) from reading the same store at once.
- The same file given twice is read once: the second record says it repeats the first.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.research.store import ResearchStore, now

log = logging.getLogger("crooks.research")

_running: asyncio.Task | None = None


# ------------------------------------------------------------------ the two doors


def receive(store: ResearchStore, name: str, data: bytes, *, via: str) -> dict[str, Any]:
    """A file George gave: refused at once when it is not a kind CLIVE reads, queued otherwise."""
    from app.research.convert import ACCEPTED, MAX_FILE_BYTES, kind_of

    if not kind_of(name):
        raise ValueError(f"CLIVE reads {ACCEPTED}; “{Path(str(name)).name[:80]}” isn't one of those.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"That file is over {MAX_FILE_BYTES >> 20} MB.")
    if not data.strip():
        raise ValueError("That file is empty.")
    return store.new_document(name, data, via=via)


def sweep(store: ResearchStore) -> list[dict[str, Any]]:
    """Take in every file put in the server folder, and move each out of the way once taken."""
    taken = store.folder("inbox/taken")
    records = []
    for path in sorted(store.inbox.iterdir()):
        if not path.is_file() or path.is_symlink() or path.name.startswith("."):
            continue
        try:
            data = path.read_bytes()
            record = receive(store, path.name, data, via="folder")
        except (OSError, ValueError) as exc:
            record = store.refused_document(path.name, str(exc), via="folder")
        records.append(record)
        with contextlib.suppress(OSError):
            shutil.move(str(path), str(taken / f"{record['id']}-{path.name}"))
    return records


# ------------------------------------------------------------------ reading, one at a time


def kick(store: ResearchStore) -> bool:
    """Start reading what is queued, in the background, unless a read is already running."""
    global _running
    if _running is not None and not _running.done():
        return False
    if not any(r.get("state") in ("queued", "reading") for r in store.documents()):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _running = loop.create_task(run_pending(store))
    return True


async def run_pending(store: ResearchStore, *, model=None, the_map=None) -> list[dict[str, Any]]:
    """Read every queued document, oldest first. Returns the records as they ended."""
    done = []
    while True:
        queued = [r for r in store.documents() if r.get("state") in ("queued", "reading")]
        if not queued:
            return done
        record = sorted(queued, key=lambda r: str(r.get("received_at") or ""))[0]
        ended = await read_one(store, record, model=model, the_map=the_map)
        done.append(ended)
        if ended.get("state") == "queued":
            return done          # another process holds the store: the next kick reads it


async def read_one(store: ResearchStore, record: dict[str, Any], *, model=None, the_map=None) -> dict[str, Any]:
    """One document, from its file as given to its proposals. Never raises: the record says how it ended."""
    from app.research import model as model_module
    from app.research.review import ReviewError, review

    record = dict(record, state="reading", why="")
    store.save(record)
    try:
        with _store_lock(store):
            prepared = await asyncio.to_thread(_digest, store, record)
            if prepared.get("state"):
                record.update(prepared)
            else:
                the_map = the_map or await asyncio.to_thread(_map)
                earlier = _earlier(store, record["id"])
                found = await review(artifact_id=record["artifact_id"], name=record["name"], text=prepared["text"],
                                     the_map=the_map, model=model or model_module.current(), earlier=earlier)
                record.update(state="done", proposals=[p.to_dict() for p in found.proposals], dropped=found.dropped,
                              notes=[*record.get("notes", []), *found.notes], model=found.model,
                              map_digest=found.map_digest)
    except ReviewError as exc:
        record.update(state="failed", why=f"It was taken in safely, but couldn't be weighed: {exc}")
    except BlockingIOError:
        record.update(state="queued", why="Another reader is busy with the research store; it will be read next.")
        store.save(record)
        return record
    except Exception as exc:  # noqa: BLE001 - every failure is said on the screen
        log.exception("research document %s could not be read", record.get("id"))
        record.update(state="failed", why=f"Reading it stopped: {type(exc).__name__}.")
    record["finished_at"] = now()
    store.save(record)
    if record["state"] in ("done", "stopped") or record.get("repeat_of"):
        store.forget_received(record)
    return record


def _digest(store: ResearchStore, record: dict[str, Any]) -> dict[str, Any]:
    """Quarantine and digest the file. {"state": ...} when it ends here; {"text": ...} to review."""
    from app.digest.intake import IntakeError, intake
    from app.digest.pipeline import digest
    from app.digest.store import ArtifactConflict, DigestStore

    path = store.received_file(record)
    if not path.is_file():
        return {"state": "failed", "why": "The file as given is no longer on the server, so it can't be read."}
    try:
        taken = intake(str(path), store.quarantine, kind="research")
    except IntakeError as exc:
        return {"state": "failed", "why": str(exc)}
    record["artifact_id"] = taken.artifact_id
    record["file_digest"] = taken.source.pinned_ref
    record["notes"] = list(taken.notes)
    # The same bytes given again, under any name, are read once: the earlier record answers for them.
    earlier = next((r for r in store.documents() if r.get("id") != record["id"] and not r.get("repeat_of")
                    and r.get("file_digest") == taken.source.pinned_ref and r.get("state") in ("done", "stopped")), None)
    if earlier is not None:
        said = "its proposals are there" if earlier.get("state") == "done" else "the safety scan stopped it then"
        return {"state": earlier["state"], "repeat_of": earlier["id"],
                "why": f"The same file as “{earlier.get('name')}”, already read: {said}."}
    try:
        result = digest(taken.path, taken.source, DigestStore(store.digests), notes=taken.notes)
    except ArtifactConflict as exc:
        return {"state": "failed", "why": str(exc)}
    if result.blocked:
        return {"state": "stopped", "why": _blocked_words(result)}
    text = document_text(result.artifact.units)
    if not text.strip():
        return {"state": "failed", "why": "The safety scan passed, but no readable sections were left to weigh."}
    return {"text": text}


def document_text(units) -> str:
    """The research as the scanner read it: each section's heading path and body, in order."""
    sections = [u for u in units if u.kind == "knowledge" and u.body.strip()]
    sections.sort(key=lambda u: (u.location.path, u.location.line_start or 0))
    return "\n\n".join(f"## {u.title}\n\n{u.body.strip()}" for u in sections)


def _blocked_words(result) -> str:
    worst = [f for f in result.findings if f.category == "safety" and f.severity in ("critical", "high")]
    if not worst:
        return "CLIVE's safety scan stopped it before anything read it."
    first = worst[0]
    where = f" (line {first.location.line_start})" if first.location.line_start else ""
    rest = f" and {len(worst) - 1} more" if len(worst) > 1 else ""
    return f"CLIVE's safety scan stopped it before anything read it{where}: {first.explanation[:240]}{rest}"


def _earlier(store: ResearchStore, doc_id: str):
    from app.research.review import Proposal

    out = []
    for record in sorted(store.documents(), key=lambda r: str(r.get("received_at") or "")):
        if record.get("id") == doc_id:
            continue
        for item in record.get("proposals") or []:
            with contextlib.suppress(TypeError, ValueError):
                out.append(Proposal.from_dict(item))
    return out


def _map():
    from app.research.rules import read_map

    return read_map()


@contextlib.contextmanager
def _store_lock(store: ResearchStore):
    """Held while a document is read: a second process reading the same store waits its turn."""
    path = store.root / ".reading.lock"
    store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
