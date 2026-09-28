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


def _strict_iso(at: object) -> str | None:
    """A time kept here, in the one form, or None when it is not a time at all: a value that is
    not a time is dropped, never replaced by now (round 7, F-07-VALUES). Total over whatever a
    stored record holds (round 8, F-07-VALUES): a valid time that cannot be put in UTC — year 1
    with a positive offset is before year 1 there, and year 9999 with a negative one after 9999 —
    raises OverflowError on the way, and is dropped like any other value that is not a time."""
    if not isinstance(at, str) or not at or len(at) > 40:
        return None
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC).isoformat(timespec="seconds")
    except (ValueError, OverflowError, TypeError):
        return None


def _iso(at: object) -> str:
    """One form for every time kept here, UTC to the second, so they compare as text: a
    blocker's own time may carry microseconds or another offset. A time that is not one, or
    cannot be put in UTC (round 8, F-07-VALUES), is the time it was noticed, never a raise."""
    return _strict_iso(str(at)) or _now()


def key_for(capability: str = "", text: str = "") -> str:
    """The key a gap is counted under: the capability the model named, or the first
    meaningful words of what it wrote. Lowercase words, at most 60 characters."""
    source = capability if str(capability or "").strip() else text
    # Redacted before anything is taken from it: a key is written down too (F-07).
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", _scrubbed(source).lower())
    if not str(capability or "").strip():
        words = [w for w in words if w not in _FILLER][:6]
    key = " ".join(words)
    return key[:MAX_KEY].rstrip() or "unnamed"


def tool_key(name: str) -> str:
    return "tool: " + (_TOOL.sub("", _scrubbed(name).lower())[:MAX_KEY - 6] or "unnamed")


def _scrubbed(text: object) -> str:
    """Credentials, contact details and known customer names out, by the timeline's own rule."""
    from app.observability.timeline import scrub_text

    return scrub_text(str(text or ""))


def _misjudged_key(cap: object) -> str:
    """Only the capabilities the claims map names are kept as keys; anything else is "other"."""
    from app.observability.claims import CAPABILITIES

    return str(cap) if str(cap) in {c.key for c in CAPABILITIES} else "other"


class WrittenNotConfirmed(Exception):
    """The record on disk WAS replaced, but its folder could not be flushed afterwards (round 8,
    F-07-DURABILITY): the new contents are what the file now holds, and whether a power cut would
    keep them is not confirmed. Never an OSError, so nothing that reads "OSError" as "nothing was
    written" can take it for one. `kept` is the original's copy, when a clean made one first."""

    def __init__(self, cause: BaseException, kept: Path | None = None) -> None:
        super().__init__(f"written, but its folder could not be flushed ({type(cause).__name__}: {cause})")
        self.kept = kept


class GapLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._repaired = False

    # ---- reading and writing --------------------------------------------------------
    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError, RecursionError):
            # RecursionError: JSON nested deeper than the parser will go is as unreadable as JSON
            # cut off mid-write, and must not raise out of report() (round 8, F-07-VALUES).
            log.warning("gap record unreadable at %s; starting a fresh one in memory", self.path)
            data = {}
        data = _shaped(data)
        _sanitise(data)
        return data

    def repair(self) -> Path | None:
        """Bring the file on disk up to today's rule, keeping the original first (the 2026-09-27
        deploy review, F-07). load() cleans only in memory; without this the live file stayed
        as it was until some unrelated change happened to save it, and that save was one way:
        merged keys and dropped history could not be had back by rolling the code back.

        When cleaning would change what is on disk, the file's exact bytes are copied first to
        `<name>.<UTC time>.before-clean` beside it (0600 in the same 0700 folder, never
        overwritten, so it holds what the file already held and nothing more), and only then is
        the clean record saved. A file that cannot be parsed is copied the same way before
        anything is written over it. Returns the copy's path, or None when nothing needed
        doing. Raises if the copy cannot be made, so nothing is saved without one. The copy and
        then the folder are flushed to disk before the clean record is written, and the clean
        record and the folder after it, so a power cut leaves one or the other, never neither.
        When only that last flush fails, the clean record has replaced the original and cannot be
        called untouched: WrittenNotConfirmed is raised, carrying the copy (round 8,
        F-07-DURABILITY). Any other failure is raised before the original is replaced.

        The cleaned file is one the code before this change (3e77f215) still reads, writes and
        reports: tests/test_capability_gaps.py runs that code, vendored verbatim, against it.

        To restore the original (after rolling the code back, or to undo the clean), with the
        service stopped:
            systemctl stop crooks-assistant
            cd <objectives dir>            # /var/lib/crooks-assistant/objectives in production
            cp -p gaps.json gaps.json.$(date -u +%Y%m%dT%H%M%SZ).after-clean   # keep the clean one
            install -m 0600 gaps.json.<time>.before-clean gaps.json
            systemctl start crooks-assistant
        Starting the new code again cleans it again, keeping a fresh copy first; the old code
        reads it as it was. docs/DEPLOY_LINUX.md carries the same steps."""
        with self._lock:
            return self._repair_locked()

    def _repair_locked(self) -> Path | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            self._repaired = True
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
            # A copy to clean, leaving what was read as it was read. Nesting deeper than the
            # parser or the encoder will go is unreadable too, never a raise (round 8, F-07-VALUES).
            shaped = _shaped(json.loads(json.dumps(parsed))) if isinstance(parsed, dict) else None
        except (UnicodeDecodeError, ValueError, RecursionError):
            shaped = None
        if shaped is None:
            # Unreadable: kept aside before a change would start a fresh record over it.
            copy = self._existing_original(raw, "unreadable") or self._keep_original(raw, "unreadable")
            self._repaired = True
            return copy
        clean = json.loads(json.dumps(shaped))
        _sanitise(clean)
        if clean == shaped:
            self._repaired = True
            return None
        # A clean that failed after its copy was made (a failed save, a crash) is tried again
        # with the copy it already has, verified byte for byte, not with another (round 7).
        copy = self._existing_original(raw, "before-clean") or self._keep_original(raw, "before-clean")
        try:
            # Cleaned, not aged (round 9, A3a-LIVE-CLEAN): every gap the original holds is in the
            # clean record, merged where keys clean alike; forgetting the stale is for a later
            # change, as it always was, never for start-up.
            self._save(clean, forget=False)
        except WrittenNotConfirmed as exc:
            # The clean record is in place (round 8, F-07-DURABILITY): not tried again over
            # itself, and said as what it is, with the copy that was flushed before it.
            self._repaired = True
            exc.kept = copy
            raise
        self._repaired = True
        log.warning("gap record cleaned to today's rule; the original is kept at %s", copy.name)
        return copy

    def _existing_original(self, raw: bytes, why: str) -> Path | None:
        """A copy already kept of exactly these bytes, made durable again, or None."""
        import hashlib

        want = hashlib.sha256(raw).hexdigest()
        for copy in sorted(self.path.parent.glob(f"{self.path.name}.*.{why}")):
            try:
                if copy.is_symlink() or copy.stat().st_mode & 0o077:
                    continue
                if hashlib.sha256(copy.read_bytes()).hexdigest() != want:
                    continue
                fd = os.open(copy, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                continue
            _fsync_dir(copy.parent)
            return copy
        return None

    def _keep_original(self, raw: bytes, why: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        copy = self.path.with_name(f"{self.path.name}.{stamp}.{why}")
        n = 1
        while copy.exists():
            n += 1
            copy = self.path.with_name(f"{self.path.name}.{stamp}-{n}.{why}")
        fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        # The copy's name is in the folder, on disk, before anything is written over the original.
        _fsync_dir(copy.parent)
        return copy

    def _save(self, data: dict[str, Any], *, forget: bool = True) -> None:
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            if folder.stat().st_mode & 0o077:
                folder.chmod(0o700)
        except OSError:
            pass
        if forget:
            _forget_stale(data)
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(data, indent=2, ensure_ascii=False))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            # Nothing replaced: the record is as it was, and no half-written file is left beside it.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # From here the live file holds the new record, so no failure below may be reported as
        # "not updated" or "left as it was" (round 8, F-07-DURABILITY): it is its own outcome.
        # Not tried again: a second fsync after a failed one can report success for data the
        # first lost.
        try:
            _fsync_dir(folder)
        except Exception as exc:  # noqa: BLE001 - whatever it was, the replace has happened
            raise WrittenNotConfirmed(exc) from exc

    def _change(self, fn, *, forget: bool = True) -> None:
        """One read-modify-write. A failure is logged, never raised: the turn that noticed the
        gap is the owner's, and a bookkeeping error must not cost him his answer. What is logged
        says what is on disk (round 8, F-07-DURABILITY): "not updated" only when the record was
        not replaced; a replace whose folder could not be flushed is said as that.

        A change that changes nothing writes nothing (round 9, A3a-LIVE-CLEAN): start-up's seed of
        a record already seeded used to save it all the same, and that save forgot stale gaps with
        no copy kept. With `forget` False (the seed) no gap is forgotten by this save either, so
        start-up writes only what the clean has kept a copy of the original for."""
        try:
            with self._lock:
                if not self._repaired:
                    # Nothing is saved over a record that has not been kept aside first.
                    try:
                        self._repair_locked()
                    except WrittenNotConfirmed as exc:
                        # The original was kept, flushed, before the clean replaced it; the change
                        # goes on, and its own save flushes the folder again.
                        log.error("gap record cleaned before this change and written, but not confirmed on disk "
                                  "(%s); the original is kept at %s", exc, getattr(exc.kept, "name", "?"))
                data = self.load()
                before = json.dumps(data, sort_keys=True)
                fn(data)
                if json.dumps(data, sort_keys=True) == before:
                    return
                self._save(data, forget=forget)
        except WrittenNotConfirmed as exc:
            log.error("gap record updated, but not confirmed on disk: %s", exc)
        except Exception:  # noqa: BLE001 - see above
            log.warning("gap record not updated", exc_info=True)

    # ---- the signals ------------------------------------------------------------------
    def note_blocker(self, objective_id: str, text: str, capability: str = "", *, at: str | None = None) -> None:
        name = _minimal(capability)[:MAX_KEY]
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
                row = data["misjudged"].setdefault(_misjudged_key(cap), {"count": 0, "first_seen": when})
                row["count"] = min(_MAX_COUNT, int(row.get("count", 0)) + 1)
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
                             _minimal(blocker.get("capability") or "")[:MAX_KEY])
        # Start-up: a record already seeded is not written at all, and seeding one forgets nothing.
        self._change(fn, forget=False)

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
                    _keep_requests(gap, [*gap["requests"], request_id], data["builds"])
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
            dropped = gap.get("dropped") or {}
            uncertain = set(gap.get("uncertain") or ())
            stage = _stage(linked)
            # A count that some forgotten history could add to is said to be a floor, not the
            # figure (round 7, F-07-LINKS): seen times kept are the newest, so it is exact
            # unless one of those forgotten came after the fix. And not exact either when history
            # was let go unread, or a link was let go that could have been an earlier fix (round
            # 8, F-07-LINKS: `uncertain`, set where it happened).
            exact = not (live_at and dropped.get("seen") and (gap.get("seen_dropped_last") or "") > live_at) \
                and not uncertain
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
                "stage": stage,
                # Live is as far as a gap goes, so a live stage is exact whatever was let go; below
                # it, a link let go could be further along than any kept (round 8, F-07-LINKS).
                "stage_exact": stage == "live" or "links" not in uncertain,
                "builds": [{k: b.get(k) for k in ("request_id", "progress", "proposed_at", "filed_at", "built_at",
                                                  "merged_at", "live_at")} for b in linked],
                "hits_after_fix": len(after) if live_at else None,
                # With no fix live among the links kept, None; but False, not None, when a link let
                # go could itself have been a live fix.
                "hits_after_fix_exact": bool(exact) if live_at else (False if "links" in uncertain else None),
                # Links and history the record could not keep, counted rather than lost silently.
                "not_kept": {k: int(v) for k, v in dropped.items() if v},
                # What was let go without being looked at: "links", "history" (round 8, F-07-LINKS).
                "uncertain": sorted(uncertain),
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
            # Held only when nought is the figure, not a floor (round 8, F-07-LINKS): a fix whose
            # count after it is not exact and reads nought is in neither, so held and recurred
            # fall short of live by exactly the fixes the record cannot vouch for.
            "fixes_held": sum(1 for r in fixed if not r["hits_after_fix"] and r["hits_after_fix_exact"]),
            "fixes_recurred": sum(1 for r in fixed if r["hits_after_fix"]),
            "misjudged": sum(int(v.get("count", 0)) for v in data["misjudged"].values()),
        }
        return {"summary": summary, "gaps": rows,
                # Named fields only, the cleaned key last: nothing a stored row carries can stand in for it.
                "misjudged": [{**{f: v.get(f) for f in _MISJUDGED_FIELDS}, "capability": k}
                              for k, v in sorted(data["misjudged"].items(), key=lambda kv: -int(kv[1].get("count", 0)))]}


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
    gap["hits"] = min(_MAX_COUNT, int(gap.get("hits", 0)) + 1)
    gap["sources"][source] = min(_MAX_COUNT, int(gap["sources"].get(source, 0)) + 1)
    gap["first_seen"] = min(gap.get("first_seen") or at, at)
    gap["last_seen"] = max(gap.get("last_seen") or at, at)
    _keep_seen(gap, [*gap.get("seen", []), at])
    if objective_id and objective_id not in gap["objectives"]:
        _keep_objectives(gap, [*gap["objectives"], objective_id])


def _clean_key(key: str) -> str:
    return tool_key(key[6:]) if str(key).startswith("tool: ") else key_for(key)


def _shaped(data: Any) -> dict[str, Any]:
    """A record with its version and its three sections, whatever was read."""
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", VERSION)
    for name in ("gaps", "builds", "misjudged"):
        if not isinstance(data.get(name), dict):
            data[name] = {}
    return data


def _sanitise(data: dict[str, Any]) -> None:
    """Every key, name, label and value the record holds, cleaned or rebuilt by today's rule,
    whatever wrote it: a record written before keys were redacted is cleaned in memory the first
    time it is read, and on disk at startup by GapLedger.repair, which keeps the original first
    (the 2026-09-26 and 2026-09-27 deploy reviews, F-07). Only fields the record writes survive
    (round 6), and each of their values is checked for what it must be (round 7): times are
    times, counts are counts, ids are ids; anything else is dropped. Links between gaps and
    builds are kept only when both sides name each other. Idempotent."""
    for name in [k for k in data if k not in _TOP_FIELDS]:
        del data[name]
    data["version"] = VERSION
    seeded = _strict_iso(data.get("seeded"))
    if seeded is None:
        data.pop("seeded", None)
    else:
        data["seeded"] = seeded
    renamed: dict[str, str] = {}
    gaps: dict[str, dict] = {}
    for key, raw in data["gaps"].items():
        if not isinstance(raw, dict):
            continue
        gap = _only_known_gap(raw)
        new = _clean_key(str(key))
        renamed[str(key)] = new
        # A label that cleans to nothing is the key, on the first read as on every later one.
        gap["label"] = _minimal(gap.get("label") or "") or _minimal(new)
        if gap.get("name"):
            gap["name"] = _minimal(gap["name"])[:MAX_KEY]
        if new in gaps:
            _merge(gaps[new], gap)
        else:
            gaps[new] = gap
    data["gaps"] = gaps
    builds: dict[str, dict] = {}
    # Builds whose own list of gaps was longer than is read (round 8, F-07-LINKS): a gap naming
    # one of them that the part read does not name may be a real link, let go unseen.
    cut_short: set[str] = set()
    for request_id, raw in data["builds"].items():
        if not isinstance(raw, dict) or not _REQUEST_ID.fullmatch(str(request_id)):
            continue
        build, truncated = _only_known_build(raw)
        for k in build["gaps"]:
            if k not in renamed:
                renamed[k] = _clean_key(k)   # remembered: a key many builds name is cleaned once
        build["gaps"] = sorted({renamed[k] for k in build["gaps"]})
        builds[str(request_id)] = build
        if truncated:
            cut_short.add(str(request_id))
    data["builds"] = builds
    misjudged: dict[str, dict] = {}
    for cap, raw in data["misjudged"].items():
        if not isinstance(raw, dict):
            continue
        row = _only_known_misjudged(raw)
        key = _misjudged_key(cap)
        if key in misjudged:
            into = misjudged[key]
            into["count"] = min(_MAX_COUNT, into["count"] + row["count"])
            into["first_seen"] = min(filter(None, [into.get("first_seen"), row.get("first_seen")]), default=None)
            into["last_seen"] = max(filter(None, [into.get("last_seen"), row.get("last_seen")]), default=None)
        else:
            misjudged[key] = row
    data["misjudged"] = misjudged
    # Both sides of every link (round 7, F-07-LINKS): a gap's request counts only when that build
    # names the gap, and a build's gap only when that gap names the build, so no gap reports the
    # stage of a build that was never for it. A link dropped here is counted on the gap.
    names = {request_id: set(build["gaps"]) for request_id, build in builds.items()}
    for key, gap in gaps.items():
        kept: list[str] = []
        for r in gap["requests"]:
            if r in names and key in names[r]:
                kept.append(r)
            elif r in cut_short:
                # Not named in the part of the build's list that was read: whether it is named
                # in the rest is not known, so this gap's stage and recurrence are not either.
                _mark_uncertain(gap, "links")
        _count_dropped(gap, "requests", len(gap["requests"]) - len(kept))
        _keep_requests(gap, kept, builds)
    for request_id, build in builds.items():
        build["gaps"] = [key for key in build["gaps"] if key in gaps and request_id in gaps[key]["requests"]]


def _fsync_dir(folder: Path) -> None:
    """A rename or a new file is durable only once its folder is. A failure is raised, never
    passed over (round 7, F-07-DURABILITY): after the copy, it stops the clean before the live
    file is touched; after a save, it is the save's failure."""
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# Every field the record writes, and nothing else survives a read (the 2026-09-27 deploy review,
# round 6, F-07): a row carrying a field of its own, "capability" in a misjudged row for one,
# could otherwise override the cleaned key where the report spreads the row.
_TOP_FIELDS = frozenset({"version", "gaps", "builds", "misjudged", "seeded"})
_GAP_FIELDS = ("label", "name", "hits", "sources", "objectives", "requests", "seen", "first_seen", "last_seen",
               "dropped", "seen_dropped_last", "uncertain")
_BUILD_FIELDS = ("objective_id", "gaps", "proposed_at", "filed_at", "built_at", "merged_at", "live_at",
                 "progress", "candidate_sha")
_MISJUDGED_FIELDS = ("count", "first_seen", "last_seen")
_SOURCES = frozenset({"blocker", "tool"})
_DROPPED = ("requests", "objectives", "seen")
# What a gap can have let go without looking at it (round 8, F-07-LINKS): "links", builds it can no
# longer follow that could be (or become) a further stage or an earlier fix than any it kept;
# "history", times of hits whose value was never read.
_UNCERTAIN = frozenset({"links", "history"})
# A count written as text: ASCII digits only. str.isdigit() also says yes to '²' and every other
# script's digits, which int() then refuses (round 8, F-07-VALUES).
_NUMERAL = re.compile(r"[0-9]{1,8}")
_OBJECTIVE_ID = re.compile(r"^obj_[a-z0-9]{4,40}$")
_REQUEST_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){1,7}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_WORDS = re.compile(r"^[a-z ]{1,40}$")
_KEEP_SEEN = 50
_MAX_COUNT = 10_000_000
_MAX_READ = 1000      # entries read from any one list of a stored record, hostile or not


def _stamp(value: object) -> str | None:
    return _strict_iso(value)


def _count(value: object) -> int:
    """A count: a whole number, nought or more, bounded; anything else is nought. Total over any
    JSON value (round 8, F-07-VALUES): an int that is not a bool, held to the bound, or text of
    one to eight ASCII digits. Nothing here can raise, so neither can the repair or the report."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, min(value, _MAX_COUNT))
    if isinstance(value, str) and _NUMERAL.fullmatch(value):
        return min(int(value, 10), _MAX_COUNT)
    return 0


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _mark_uncertain(gap: dict, what: str) -> None:
    gap["uncertain"] = sorted({*(gap.get("uncertain") or ()), what})


def _count_dropped(gap: dict, what: str, n: int) -> None:
    if n > 0:
        dropped = gap.setdefault("dropped", {})
        dropped[what] = min(_MAX_COUNT, int(dropped.get(what, 0)) + n)


def _keep_seen(gap: dict, seen: list[str]) -> None:
    """The newest _KEEP_SEEN times; how many older ones went, and the latest of them, are kept so
    the report can say when its count after a fix is a floor rather than the figure."""
    ordered = sorted(seen)
    gone = ordered[:-_KEEP_SEEN] if len(ordered) > _KEEP_SEEN else []
    gap["seen"] = ordered[-_KEEP_SEEN:]
    if gone:
        _count_dropped(gap, "seen", len(gone))
        gap["seen_dropped_last"] = max(filter(None, [gap.get("seen_dropped_last"), gone[-1]]))


def _keep_objectives(gap: dict, objectives: list[str]) -> None:
    ordered = list(dict.fromkeys(objectives))
    _count_dropped(gap, "objectives", max(0, len(ordered) - MAX_LINKS))
    gap["objectives"] = ordered[-MAX_LINKS:]


_STAGE_RANK = {"proposed": 0, "filed": 1, "building": 2, "built": 3, "merged": 4, "live": 5}


def _keep_requests(gap: dict, requests: list[str], builds: dict[str, dict]) -> None:
    """At most MAX_LINKS builds per gap, and never at the cost of the report's stage or its count
    after the fix: the build that went live first is always kept (round 8, F-07-LINKS: "the last
    twenty live" could let it go, and the count after the fix then started at a later one), then
    the furthest along, then the newest; how many went is counted on the gap.

    With a live build kept, nothing let go can change the stage (live is as far as it goes) or
    the fix's time (a build let go goes live later, if ever, than the one kept). With none live,
    one let go could go live later and the gap would not see it: that is marked "links"
    uncertain, and the report says its stage and its count after a fix are not exact."""
    ordered = list(dict.fromkeys(requests))
    if len(ordered) > MAX_LINKS:
        position = {r: i for i, r in enumerate(ordered)}
        live = [r for r in ordered if (builds.get(r) or {}).get("live_at")]
        first = min(live, key=lambda r: (builds[r]["live_at"], position[r])) if live else None

        def rank(r: str) -> tuple:
            stage = _STAGE_RANK[_stage([builds[r]])] if r in builds else -1
            return (r == first, stage, position[r])

        keep = set(sorted(ordered, key=rank)[-MAX_LINKS:])
        _count_dropped(gap, "requests", len(ordered) - MAX_LINKS)
        if first is None:
            _mark_uncertain(gap, "links")
        ordered = [r for r in ordered if r in keep]
    gap["requests"] = ordered


def _only_known_gap(raw: dict) -> dict:
    """A stored gap with only its known fields, each checked for what it must be. Each list is
    read to _MAX_READ entries at most, against a hostile record; what that leaves unread is
    counted in `dropped`, and marked in `uncertain` where it could change the report (round 8,
    F-07-LINKS): requests unread could be the build that fixed it, history unread could be hits
    after that fix. Nothing is let go without trace."""
    gap: dict[str, Any] = {field: raw[field] for field in _GAP_FIELDS if field in raw}
    for field in ("label", "name"):
        if field in gap and not isinstance(gap[field], str):
            del gap[field]   # text, or nothing: a list or an object is not a label (round 8)
    gap["hits"] = _count(gap.get("hits"))
    sources = gap.get("sources") if isinstance(gap.get("sources"), dict) else {}
    gap["sources"] = {k: _count(v) for k, v in sources.items() if k in _SOURCES and _count(v)}
    dropped = gap.get("dropped") if isinstance(gap.get("dropped"), dict) else {}
    gap["dropped"] = {k: _count(v) for k, v in dropped.items() if k in _DROPPED and _count(v)}
    uncertain = _as_list(gap.get("uncertain"))
    gap["uncertain"] = sorted({u for u in uncertain if isinstance(u, str) and u in _UNCERTAIN})
    for field in ("first_seen", "last_seen", "seen_dropped_last"):
        stamped = _stamp(gap.get(field))
        if stamped is None:
            gap.pop(field, None)
        else:
            gap[field] = stamped
    objectives = _as_list(gap.get("objectives"))
    if len(objectives) > _MAX_READ:
        _count_dropped(gap, "objectives", len(objectives) - _MAX_READ)
        objectives = objectives[-_MAX_READ:]
    gap["objectives"] = [o for o in objectives if isinstance(o, str) and _OBJECTIVE_ID.fullmatch(o)]
    requests = _as_list(gap.get("requests"))
    if len(requests) > _MAX_READ:
        _count_dropped(gap, "requests", len(requests) - _MAX_READ)
        _mark_uncertain(gap, "links")
        requests = requests[:_MAX_READ]
    # Which MAX_LINKS are kept is settled once the builds are known (_sanitise, _keep_requests),
    # so the stage the report shows is not lost here.
    gap["requests"] = list(dict.fromkeys(r for r in requests if isinstance(r, str) and _REQUEST_ID.fullmatch(r)))
    seen = _as_list(gap.get("seen"))
    if len(seen) > _MAX_READ:
        _count_dropped(gap, "seen", len(seen) - _MAX_READ)
        _mark_uncertain(gap, "history")
        seen = seen[-_MAX_READ:]
    gap["seen"] = sorted(filter(None, (_stamp(t) for t in seen)))
    _keep_objectives(gap, gap["objectives"])
    _keep_seen(gap, gap["seen"])
    if "last_seen" not in gap and gap["seen"]:
        # A last hit that was not a time is the newest hit kept (round 8, F-07-VALUES): dropped
        # and not replaced, the gap read as never hit and was forgotten at the next save.
        gap["last_seen"] = gap["seen"][-1]
    if not gap["dropped"]:
        gap.pop("dropped")
    if not gap["uncertain"]:
        gap.pop("uncertain")
    return gap


def _only_known_build(raw: dict) -> tuple[dict, bool]:
    """A stored build with only its known fields, each checked; and whether its list of gaps was
    longer than is read. That list was cut at MAX_GAPS before its keys were cleaned (round 8,
    F-07-LINKS), which let go links to gaps whose legacy keys came later in it; it is read to
    _MAX_READ now, and a build cut there is said to be, so the gaps it may name are marked."""
    build: dict[str, Any] = {field: raw[field] for field in _BUILD_FIELDS if field in raw}
    if not (isinstance(build.get("objective_id"), str) and _OBJECTIVE_ID.fullmatch(build["objective_id"])):
        build.pop("objective_id", None)
    if not (isinstance(build.get("candidate_sha"), str) and _SHA40.fullmatch(build["candidate_sha"])):
        build.pop("candidate_sha", None)
    if not (isinstance(build.get("progress"), str) and _WORDS.fullmatch(build["progress"])):
        build.pop("progress", None)
    gaps = _as_list(build.get("gaps"))
    truncated = len(gaps) > _MAX_READ
    build["gaps"] = [k for k in gaps[:_MAX_READ] if isinstance(k, str) and k]
    for field in ("proposed_at", "filed_at", "built_at", "merged_at", "live_at"):
        if field in build:
            stamped = _stamp(build[field])
            if stamped is None:
                del build[field]
            else:
                build[field] = stamped
    return build, truncated


def _only_known_misjudged(raw: dict) -> dict:
    return {"count": _count(raw.get("count")), "first_seen": _stamp(raw.get("first_seen")),
            "last_seen": _stamp(raw.get("last_seen"))}


def _merge(into: dict, other: dict) -> None:
    """Two gaps that turn out to be one, once cleaned. Counts add up; links and history join, and
    whatever the bounds cannot keep is counted, never lost without trace (round 7, F-07-LINKS).
    Which builds are kept is settled when the record's builds are known (_sanitise)."""
    into["hits"] = min(_MAX_COUNT, into["hits"] + other["hits"])
    sources = dict(into.get("sources") or {})
    for source, count in (other.get("sources") or {}).items():
        sources[source] = min(_MAX_COUNT, int(sources.get(source, 0)) + int(count))
    into["sources"] = sources
    for what, n in (other.get("dropped") or {}).items():
        _count_dropped(into, what, n)
    for what in other.get("uncertain") or ():
        _mark_uncertain(into, what)
    if other.get("seen_dropped_last"):
        into["seen_dropped_last"] = max(filter(None, [into.get("seen_dropped_last"), other["seen_dropped_last"]]))
    _keep_objectives(into, [*into["objectives"], *other["objectives"]])
    into["requests"] = list(dict.fromkeys([*into["requests"], *other["requests"]]))
    _keep_seen(into, [*into["seen"], *other["seen"]])
    into["first_seen"] = min(filter(None, [into.get("first_seen"), other.get("first_seen")]), default=None)
    into["last_seen"] = max(filter(None, [into.get("last_seen"), other.get("last_seen")]), default=None)
    if into["first_seen"] is None:
        into.pop("first_seen")
    if into["last_seen"] is None:
        into.pop("last_seen")
    if not into.get("name") and other.get("name"):
        into["name"] = other["name"]


def _minimal(text: str) -> str:
    """A label as little as it can be: one line, bounded, with contact details and known
    customer names taken out by the same rule every event on the timeline passes."""
    from app.observability.timeline import scrub_text

    # A lone surrogate ("\ud800" in the JSON) is text Python reads and UTF-8 cannot write: kept, it
    # made every save of the record fail, the repair's included (round 8, F-07-VALUES).
    text = str(text or "").encode("utf-8", "ignore").decode("utf-8")
    return " ".join(scrub_text(text).split())[:MAX_LABEL]


def _forget_stale(data: dict[str, Any], now: datetime | None = None) -> None:
    """Gaps nobody has hit for KEEP_DAYS, with no build ever proposed for them, are forgotten. A
    gap whose last hit is not known is not known to be stale, and is kept (round 8, F-07-VALUES):
    a stored time that was not one used to make its whole gap go at the next save."""
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    for key in [k for k, g in data["gaps"].items()
                if g.get("last_seen") and g["last_seen"] < cutoff and not g.get("requests")]:
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
    """The process's record. Brought up to today's rule on disk now, with the original kept
    aside first (GapLedger.repair); a repair that cannot keep the original leaves the file
    untouched and says so, and the first change tries again before it saves. A clean that
    replaced the file but could not flush its folder afterwards says exactly that, and names
    the copy of the original, flushed before it (round 8, F-07-DURABILITY)."""
    global _LEDGER
    _LEDGER = GapLedger(path)
    try:
        _LEDGER.repair()
    except WrittenNotConfirmed as exc:
        log.error("gap record cleaned at startup: the clean record has replaced the original, but is not "
                  "confirmed on disk (%s). The original is kept, flushed, at %s", exc, getattr(exc.kept, "name", "?"))
    except Exception:  # noqa: BLE001 - never stops the process; raised before the replace, nothing written
        log.warning("gap record not cleaned at startup; left exactly as it was", exc_info=True)
    return _LEDGER


def ledger() -> GapLedger | None:
    """The record, once the runtime has installed it; before that (a bare test, a script)
    nothing is recorded."""
    return _LEDGER
