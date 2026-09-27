# ruff: noqa
# A VERBATIM COPY of crooks-assistant/app/objectives/gaps.py at 3e77f215 — the gap reader production
# runs before this deploy, and so the code a rollback returns to. Used only by
# tests/test_capability_gaps.py to prove that code still reads, writes and reports the record the
# new code cleans (the 2026-09-27 deploy review, round 6, F-07). Never edited; never imported by the app.
"""What CLIVE cannot do yet, counted, and what became of each gap.

Two signals name a gap, and both are CLIVE's own:

- a missing_capability blocker on an objective: CLIVE saying, in words the owner reads, what it
  lacks to get the objective done. Keyed by the capability the model names with it
  (`capability`), or, for a blocker written before that existed, by the blocker's own words;
- a call to a tool that does not exist: the model reaching for something CLIVE lacks. Keyed by
  the tool's name.

A third is counted apart, because it is not a gap: a false unsupported claim, CLIVE declining
something it can compose (app/observability/claims.py). That is CLIVE misjudging itself, and a
build would be the wrong fix for it.

Each gap carries what became of it, so the owner can judge whether CLIVE picks the right fixes:
whether a build was proposed for it (a request prepared for an objective the gap blocks),
filed (the owner's tap), built (the loop reports it complete), merged (its candidate is on the
trunk), live (its candidate is in the commit this CLIVE is running), and how often the gap came
back once its fix was live. The gaps that recur most should be the ones CLIVE proposes to
build, and a live fix should stop its gap recurring.

One JSON file beside the objectives, written atomically, 0600 in a 0700 folder like the
objectives themselves (the 2026-09-26 deploy review, F-07). What it keeps is the least that
answers the question: a label per gap, passed through the timeline's own redaction (contact
details and the customer names this process has been shown are gone before it is written), the
objective ids, the build ids and times. A gap nobody has hit for KEEP_DAYS and nothing was built
for is forgotten. Nothing here is sent anywhere, and nothing here ever raises into a turn: a
record that cannot be written is logged and dropped.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("crooks.objectives.gaps")

VERSION = 1
MAX_GAPS = 200
KEEP_DAYS = 180
MAX_LABEL = 200
MAX_KEY = 60
MAX_LINKS = 20
TOP = 5
# Words that say nothing about which capability is missing, dropped when a key is made from a
# blocker's own words ("No web or research tool to look up…" -> "web research tool look up…").
_FILLER = frozenset({
    "no", "not", "there", "is", "isn't", "are", "a", "an", "the", "to", "of", "for", "and", "or", "on",
    "in", "with", "can", "cannot", "can't", "clive", "has", "have", "any", "way", "yet", "it", "its",
    "this", "that", "so", "be", "from", "right", "now", "which", "would",
})
_TOOL = re.compile(r"[^a-z0-9_.-]+")
# A tool whose name asks to authorise, approve or run something is the model reaching for the
# owner's own gesture, which is withheld by design: never a gap, and never something to build.
_SELF_AUTHORITY = re.compile(r"approv|confirm|authori[sz]|execut|commit|proposal|override|bypass|unlock|permission|sudo|admin|gate", re.I)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(at: object) -> str:
    """One form for every time kept here, UTC to the second, so they compare as text: a
    blocker's own time may carry microseconds or another offset."""
    try:
        when = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return _now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds")


def key_for(capability: str = "", text: str = "") -> str:
    """The key a gap is counted under: the capability the model named, or the first
    meaningful words of what it wrote. Lowercase words, at most 60 characters."""
    source = capability if str(capability or "").strip() else text
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", str(source or "").lower())
    if not str(capability or "").strip():
        words = [w for w in words if w not in _FILLER][:6]
    key = " ".join(words)
    return key[:MAX_KEY].rstrip() or "unnamed"


def tool_key(name: str) -> str:
    return "tool: " + (_TOOL.sub("", str(name or "").lower())[:MAX_KEY - 6] or "unnamed")


class GapLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    # ---- reading and writing --------------------------------------------------------
    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            log.warning("gap record unreadable at %s; starting a fresh one in memory", self.path)
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", VERSION)
        for name in ("gaps", "builds", "misjudged"):
            if not isinstance(data.get(name), dict):
                data[name] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            if folder.stat().st_mode & 0o077:
                folder.chmod(0o700)
        except OSError:
            pass
        _forget_stale(data)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, self.path)

    def _change(self, fn) -> None:
        """One read-modify-write. A failure is logged, never raised: the turn that noticed the
        gap is the owner's, and a bookkeeping error must not cost him his answer."""
        try:
            with self._lock:
                data = self.load()
                fn(data)
                self._save(data)
        except Exception:  # noqa: BLE001 - see above
            log.warning("gap record not updated", exc_info=True)

    # ---- the signals ------------------------------------------------------------------
    def note_blocker(self, objective_id: str, text: str, capability: str = "", *, at: str | None = None) -> None:
        name = " ".join(str(capability or "").split())[:MAX_KEY]
        self._change(lambda data: _hit(data, key_for(capability, text), "blocker", text, objective_id, at or _now(), name))

    def note_missing_tool(self, name: str, *, at: str | None = None) -> None:
        if _SELF_AUTHORITY.search(str(name or "")):
            log.info("tool %r reaches for the owner's authority; not a capability gap", name)
            return
        key = tool_key(name)
        label = f"Tried to use {key[6:]}, which CLIVE does not have"
        self._change(lambda data: _hit(data, key, "tool", label, "", at or _now(), f"A tool called {key[6:]}"))

    def note_misjudged(self, capabilities: list[str], *, at: str | None = None) -> None:
        """CLIVE declined something it could have composed (a false unsupported claim)."""
        when = at or _now()

        def fn(data):
            for cap in capabilities or ["unnamed"]:
                row = data["misjudged"].setdefault(str(cap)[:MAX_KEY], {"count": 0, "first_seen": when})
                row["count"] = int(row.get("count", 0)) + 1
                row["last_seen"] = when
        self._change(fn)

    def seed(self, objectives) -> None:
        """The missing_capability blockers recorded before this record existed, counted once,
        at the time each was written. Only when the record has never been seeded."""
        def fn(data):
            if data.get("seeded"):
                return
            data["seeded"] = _now()
            for obj in objectives:
                for blocker in getattr(obj, "blockers", []) or []:
                    if blocker.get("kind") == "missing_capability":
                        _hit(data, key_for(blocker.get("capability", ""), blocker.get("text", "")), "blocker",
                             blocker.get("text", ""), obj.id, str(blocker.get("at") or _now()),
                             str(blocker.get("capability") or ""))
        self._change(fn)

    # ---- what became of a gap -----------------------------------------------------------
    def proposed(self, request_id: str, objective_id: str, keys: list[str]) -> None:
        """A build was prepared for an objective these gaps block."""
        when = _now()

        def fn(data):
            build = data["builds"].setdefault(request_id, {"objective_id": objective_id, "gaps": [], "proposed_at": when})
            build["gaps"] = sorted(set(build.get("gaps", [])) | set(keys))
            for key in keys:
                gap = data["gaps"].get(key)
                if gap is not None and request_id not in gap["requests"]:
                    gap["requests"] = (gap["requests"] + [request_id])[-MAX_LINKS:]
        self._change(fn)

    def filed(self, request_id: str) -> None:
        def fn(data):
            build = data["builds"].get(request_id)
            if build is not None and not build.get("filed_at"):
                build["filed_at"] = _now()
        self._change(fn)

    def progressed(self, rows: dict[str, dict]) -> None:
        """The loop's own words for each build this record follows."""
        def fn(data):
            for request_id, build in data["builds"].items():
                row = rows.get(request_id)
                if not row:
                    continue
                build["progress"] = row.get("progress")
                if row.get("progress") == "done" and not build.get("built_at"):
                    build["built_at"] = _now()
                if row.get("candidate_sha"):
                    build["candidate_sha"] = row["candidate_sha"]
        self._change(fn)

    def merged(self, request_id: str) -> None:
        def fn(data):
            build = data["builds"].get(request_id)
            if build is not None and not build.get("merged_at"):
                build["merged_at"] = _now()
        self._change(fn)

    def live(self, request_id: str) -> None:
        def fn(data):
            build = data["builds"].get(request_id)
            if build is not None and not build.get("live_at"):
                build["live_at"] = _now()
                build.setdefault("merged_at", build["live_at"])
        self._change(fn)

    def unmerged_builds(self) -> list[tuple[str, str]]:
        """Built, not yet seen on the trunk: (request id, candidate SHA)."""
        builds = self.load()["builds"]
        return [(rid, b["candidate_sha"]) for rid, b in builds.items()
                if b.get("candidate_sha") and not b.get("merged_at")]

    def unlive_builds(self) -> list[tuple[str, str]]:
        """Built, not yet in the commit this CLIVE runs: (request id, candidate SHA)."""
        builds = self.load()["builds"]
        return [(rid, b["candidate_sha"]) for rid, b in builds.items()
                if b.get("candidate_sha") and not b.get("live_at")]

    # ---- the report ---------------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        """Every gap with what became of it, the most frequent first, and the few numbers that
        say whether CLIVE is picking the right fixes."""
        data = self.load()
        builds = data["builds"]
        rows = []
        for key, gap in data["gaps"].items():
            linked = [dict(builds[r], request_id=r) for r in gap.get("requests", []) if r in builds]
            live_at = min((b["live_at"] for b in linked if b.get("live_at")), default=None)
            after = [t for t in gap.get("seen", []) if live_at and t > live_at]
            rows.append({
                "key": key,
                # What to call it: the capability as CLIVE named it, or what it wrote.
                "title": gap.get("name") or gap.get("label", key),
                "label": gap.get("label", key),
                "hits": int(gap.get("hits", 0)),
                "sources": gap.get("sources", {}),
                "objectives": gap.get("objectives", []),
                "first_seen": gap.get("first_seen"),
                "last_seen": gap.get("last_seen"),
                "stage": _stage(linked),
                "builds": [{k: b.get(k) for k in ("request_id", "progress", "proposed_at", "filed_at", "built_at",
                                                  "merged_at", "live_at")} for b in linked],
                "hits_after_fix": len(after) if live_at else None,
            })
        rows.sort(key=lambda r: r["last_seen"] or "", reverse=True)
        rows.sort(key=lambda r: r["hits"], reverse=True)   # stable: equal counts stay newest first
        top = rows[:TOP]
        fixed = [r for r in rows if r["stage"] == "live"]
        summary = {
            "gaps": len(rows),
            "hits": sum(r["hits"] for r in rows),
            "proposed": sum(1 for r in rows if r["stage"] != "open"),
            "filed": sum(1 for r in rows if r["stage"] in ("filed", "building", "built", "merged", "live")),
            "merged": sum(1 for r in rows if r["stage"] in ("merged", "live")),
            "live": len(fixed),
            "top_proposed": sum(1 for r in top if r["stage"] != "open"),
            "top": len(top),
            "fixes_held": sum(1 for r in fixed if not r["hits_after_fix"]),
            "fixes_recurred": sum(1 for r in fixed if r["hits_after_fix"]),
            "misjudged": sum(int(v.get("count", 0)) for v in data["misjudged"].values()),
        }
        return {"summary": summary, "gaps": rows,
                "misjudged": [{"capability": k, **v} for k, v in sorted(data["misjudged"].items(), key=lambda kv: -int(kv[1].get("count", 0)))]}


def _hit(data: dict[str, Any], key: str, source: str, text: str, objective_id: str, at: str, name: str = "") -> None:
    at = _iso(at)
    gaps = data["gaps"]
    gap = gaps.get(key)
    if gap is None:
        if len(gaps) >= MAX_GAPS:
            # The least recently seen gap makes room: an old one-off is worth less than a new one.
            oldest = min(gaps, key=lambda k: gaps[k].get("last_seen") or "")
            del gaps[oldest]
        gap = gaps[key] = {"label": _minimal(text or key), "hits": 0, "sources": {},
                           "objectives": [], "requests": [], "seen": [], "first_seen": at}
    if name and not gap.get("name"):
        gap["name"] = name[:1].upper() + name[1:]
    gap["hits"] = int(gap.get("hits", 0)) + 1
    gap["sources"][source] = int(gap["sources"].get(source, 0)) + 1
    gap["first_seen"] = min(gap.get("first_seen") or at, at)
    gap["last_seen"] = max(gap.get("last_seen") or at, at)
    gap["seen"] = sorted(gap.get("seen", []) + [at])[-50:]
    if objective_id and objective_id not in gap["objectives"]:
        gap["objectives"] = (gap["objectives"] + [objective_id])[-MAX_LINKS:]


def _minimal(text: str) -> str:
    """A label as little as it can be: one line, bounded, with contact details and known
    customer names taken out by the same rule every event on the timeline passes."""
    from app.observability.timeline import scrub_text

    return " ".join(scrub_text(str(text or "")).split())[:MAX_LABEL]


def _forget_stale(data: dict[str, Any], now: datetime | None = None) -> None:
    """Gaps nobody has hit for KEEP_DAYS, with no build ever proposed for them, are forgotten."""
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    for key in [k for k, g in data["gaps"].items() if (g.get("last_seen") or "") < cutoff and not g.get("requests")]:
        del data["gaps"][key]


def _stage(builds: list[dict]) -> str:
    """How far the furthest build for a gap got."""
    order = ("open", "proposed", "filed", "building", "built", "merged", "live")
    best = "open"
    for b in builds:
        if b.get("live_at"):
            stage = "live"
        elif b.get("merged_at"):
            stage = "merged"
        elif b.get("built_at"):
            stage = "built"
        elif b.get("filed_at") and b.get("progress") not in (None, "queued"):
            stage = "building"
        elif b.get("filed_at"):
            stage = "filed"
        else:
            stage = "proposed"
        if order.index(stage) > order.index(best):
            best = stage
    return best


_LEDGER: GapLedger | None = None


def install(path: Path) -> GapLedger:
    global _LEDGER
    _LEDGER = GapLedger(path)
    return _LEDGER


def ledger() -> GapLedger | None:
    """The record, once the runtime has installed it; before that (a bare test, a script)
    nothing is recorded."""
    return _LEDGER
