"""The capability delta: what this build can do that the last one could not.

"I updated your capabilities earlier. What more can you do now?" took seventy-five seconds
and zero tool calls in the September test session, and the answer was wrong. It is a
comparison of two manifests, both of which the Mac holds, and needs no read at all.

The previous manifest is kept beside the current one in the log directory. Recording is
idempotent: a restart with the same code does not invent a new build, because the
fingerprint has not moved.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import time
from pathlib import Path
from typing import Any

FILE_NAME = "capabilities.json"
# Builds kept. Enough to answer "what changed this week"; not a changelog.
MAX_HISTORY = 12


def _path(log_dir: Path | str) -> Path:
    return Path(log_dir) / FILE_NAME


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# Every scratch file this process writes gets a number of its own, so two writes from the
# same process cannot collide either.
_SCRATCH = itertools.count()


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A scratch name belonging to THIS writer. It used to be one shared `capabilities.tmp`,
    # and the rename is atomic but the source was not unique: two starts against the same log
    # directory — `make up` overlapping the launchd agent through a restart, or two test
    # workers — and whichever renamed first took the other's scratch file out from under it.
    # The second os.replace then raised FileNotFoundError out of record_build, out of
    # runtime.build, and out of the lifespan: the backend did not come up at all.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{next(_SCRATCH)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (json.dumps(data, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.replace(tmp, path)
    except OSError:
        # Never leave scratch behind for the next start to wonder about.
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def record_build(manifest: dict[str, Any], log_dir: Path | str, *, clock=time.time) -> dict[str, Any]:
    """Note this build's manifest, keeping the last different one as `previous`.

    Returns the stored record: {current, previous, history}. Called once at startup.
    """
    path = _path(log_dir)
    stored = _read(path)
    current = stored.get("current") if isinstance(stored.get("current"), dict) else None
    record: dict[str, Any] = {"current": {**manifest, "seen_at": clock()}, "previous": stored.get("previous"), "history": stored.get("history") or []}
    if current is not None and current.get("fingerprint") == manifest.get("fingerprint"):
        # Same capabilities: the build id may have moved, the answer has not.
        record["current"]["seen_at"] = current.get("seen_at", clock())
        record["previous"] = stored.get("previous")
    elif current is not None:
        record["previous"] = current
        history = list(record["history"])
        history.append({"build": current.get("build"), "fingerprint": current.get("fingerprint"), "seen_at": current.get("seen_at"), "counts": current.get("counts")})
        record["history"] = history[-MAX_HISTORY:]
    _write(path, record)
    return record


def _index(manifest: dict[str, Any] | None, section: str, key: str = "name") -> dict[str, dict]:
    if not isinstance(manifest, dict):
        return {}
    return {str(e.get(key)): e for e in manifest.get(section) or [] if isinstance(e, dict) and e.get(key)}


def delta(record: dict[str, Any]) -> dict[str, Any]:
    """What moved between `previous` and `current`. Empty lists when nothing did."""
    current = record.get("current") if isinstance(record.get("current"), dict) else {}
    previous = record.get("previous") if isinstance(record.get("previous"), dict) else None
    out: dict[str, Any] = {
        "previous_build": (previous or {}).get("build") or None,
        "current_build": current.get("build") or None,
        "previous_fingerprint": (previous or {}).get("fingerprint") or None,
        "current_fingerprint": current.get("fingerprint") or None,
        "first_build": previous is None,
        "added": [], "removed": [], "changed": [],
    }
    if previous is None:
        return out
    for section in ("reads", "writes", "batches"):
        now, before = _index(current, section), _index(previous, section)
        for name in sorted(set(now) - set(before)):
            out["added"].append({"section": section, "name": name, "what": now[name].get("what", ""), "operation": now[name].get("operation")})
        for name in sorted(set(before) - set(now)):
            out["removed"].append({"section": section, "name": name, "what": before[name].get("what", "")})
        for name in sorted(set(now) & set(before)):
            was, is_now = before[name], now[name]
            moved = [k for k in ("tier", "risk", "gesture", "set_kinds", "max_members", "entity_kind") if was.get(k) != is_now.get(k)]
            if moved:
                out["changed"].append({"section": section, "name": name, "fields": moved})
    now_dims = current.get("query_dimensions") or {}
    was_dims = previous.get("query_dimensions") or {}
    for key in sorted(set(now_dims) | set(was_dims)):
        a, b = was_dims.get(key), now_dims.get(key)
        if isinstance(a, list) and isinstance(b, list):
            gained, lost = sorted(set(b) - set(a)), sorted(set(a) - set(b))
            if gained:
                out["added"].append({"section": "query_dimensions", "name": key, "what": ", ".join(str(g) for g in gained[:8])})
            if lost:
                out["removed"].append({"section": "query_dimensions", "name": key, "what": ", ".join(str(x) for x in lost[:8])})
        elif a != b and a is not None:
            out["changed"].append({"section": "query_dimensions", "name": key, "fields": ["value"]})
    gained_ui = sorted(set(current.get("ui_components") or []) - set(previous.get("ui_components") or []))
    if gained_ui:
        out["added"].append({"section": "ui_components", "name": "cards", "what": ", ".join(gained_ui[:8])})
    return out


# What a section is called when spoken. "batch_order_tags_add" is not an answer.
_SECTION_WORDS = {"reads": "new things I can look up", "writes": "new changes I can stage for you",
                  "batches": "new bulk changes", "query_dimensions": "new ways to slice a question",
                  "ui_components": "new cards"}


# What a spoken answer may be. The scenario oracle asks for under 400 characters and it is
# right to: this is READ ALOUD, and 435 characters of it — which is what an eighteen-family
# manifest produced — is half a minute of the assistant reciting a list at somebody who asked
# a one-line question. The CARD carries the whole list; the sentence carries the shape of it.
SPOKEN_CHARS = 360
SPOKEN_PER_SECTION = 3


def spoken_delta(record: dict[str, Any], *, limit: int = SPOKEN_PER_SECTION) -> str:
    """The delta in one breath, in the owner's words.

    "In one breath" is a bound, not a figure of speech. At most `limit` things per section are
    named and the rest are counted, and if the sentence still runs long the sections are
    summarised instead — because a build that adds forty things is exactly the build whose
    delta must not be recited.
    """
    d = delta(record)
    if d["first_build"]:
        counts = (record.get("current") or {}).get("counts") or {}
        return (f"This is the first build I have a record of, so I have nothing to compare against. "
                f"Right now: {counts.get('reads', 0)} things I can look up, {counts.get('writes', 0)} changes I can stage "
                f"and {counts.get('batches', 0)} bulk changes.")
    if not (d["added"] or d["removed"] or d["changed"]):
        return "Nothing has changed since the last build — same tools, same questions, same cards."
    parts: list[str] = []
    for section in ("reads", "writes", "batches", "query_dimensions", "ui_components"):
        gained = [a for a in d["added"] if a["section"] == section]
        if not gained:
            continue
        words = ", ".join(_readable(a) for a in gained[:limit])
        if len(gained) > limit:
            rest = len(gained) - limit
            words = f"{words} and {rest} more"
        parts.append(f"{_SECTION_WORDS[section]}: {words}")
    lost = d["removed"]
    if lost:
        parts.append("gone: " + ", ".join(_readable(r) for r in lost[:4]))
    changed = d["changed"]
    if changed and not parts:
        parts.append(", ".join(f"{_readable(c)} works differently" for c in changed[:4]))
    said = "Since the last build — " + "; ".join(parts) + "."
    if len(said) <= SPOKEN_CHARS:
        return said
    # Still too long to say: count the sections rather than naming anything in them. The card
    # beside it has every entry, which is where a list belongs.
    counted = []
    for section in ("reads", "writes", "batches", "query_dimensions", "ui_components"):
        gained = [a for a in d["added"] if a["section"] == section]
        if gained:
            counted.append(f"{len(gained)} {_SECTION_WORDS[section]}")
    if lost:
        counted.append(f"{len(lost)} gone")
    return "Since the last build — " + ", ".join(counted) + ". They are on the card."


def _readable(entry: dict[str, Any]) -> str:
    what = str(entry.get("what") or "").strip()
    if entry.get("section") == "query_dimensions":
        return f"{entry.get('name')} ({what})" if what else str(entry.get("name"))
    return what or str(entry.get("operation") or entry.get("name") or "").replace("_", " ")
