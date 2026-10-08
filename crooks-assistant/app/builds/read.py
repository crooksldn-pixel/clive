"""What the Builds screen is drawn from, read from GitHub sparingly and kept.

Four sources, each read the cheapest way that keeps it true:

- the loop's published status: through engineering_tools, at most once a minute, the same read
  engineering_status and the home's build rows share;
- each request's own file on the inbox branch, for its title and what was asked: read once, and
  kept only when its bytes hash to the digest the loop published for that request
  (`request_sha256`), so the title is the one the loop took in. A request file is created once and
  never overwritten, so a title read is never read again;
- whether a build's commit is on the trunk, and in the commit this CLIVE runs (engineering_tools
  `running_sha`, read from the checkout's own git files): GitHub's compare, at most once a minute per
  commit until it says yes, which is kept, since the trunk is only ever merged into;
- CLIVE's own records: the objectives a request was filed for, the capability gaps its build
  closes (app/objectives/gaps.py), and the owner's answers in the judgment ledger.

A source that cannot be read leaves its part of the board saying so (`problems`), never guessed;
nothing here writes anywhere, and no customer detail is read.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.builds import board as board_module
from app.builds import decisions
from app.engineering_bridge.github import TRUNK_REF, GitHubError, NotConnected
from app.engineering_bridge.requests import valid_request_id
from app.tools import engineering_tools
from app.tools.engineering_tools import _said

log = logging.getLogger("crooks.builds")

CONCURRENCY = 4
RETRY_S = 60.0
MAX_FILE_READS = 80       # request files read in one board read; the rest come with the next
MAX_COMPARES = 60         # trunk and running comparisons in one board read
TITLE_CHARS = 200

_requests: dict[str, dict[str, str]] = {}      # request id -> its title, what was asked, base, branch
_unread: dict[str, float] = {}                 # request id -> when reading its file last failed
_commits: dict[str, dict[str, Any]] = {}       # commit -> what GitHub said of it, and when


def reset() -> None:
    """Forget everything read (a test, or a different loop bound)."""
    _requests.clear()
    _unread.clear()
    _commits.clear()


# ------------------------------------------------------------------ request files


async def _read_request(inbox, item: dict[str, Any], gate: asyncio.Semaphore) -> None:
    rid = str(item.get("request_id") or "")
    async with gate:
        try:
            found = await inbox.request_file(rid)
        except (GitHubError, ValueError):
            # ValueError: an id the bridge refuses to name a path for (RequestRefused is one). Never
            # raised past here: one bad id must not cost him the board (the review of fe36872f).
            _unread[rid] = time.monotonic()
            return
    if isinstance(found, NotConnected) or not found.exists:
        _unread[rid] = time.monotonic()
        return
    digest = str(item.get("request_sha256") or "")
    if digest and hashlib.sha256(found.content).hexdigest() != digest:
        # Not the request the loop took in: its words are not this build's.
        log.warning("request %s on the inbox does not match the digest the loop published", rid)
        _unread[rid] = time.monotonic()
        return
    try:
        record = json.loads(found.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        _unread[rid] = time.monotonic()
        return
    if not isinstance(record, dict):
        _unread[rid] = time.monotonic()
        return
    _requests[rid] = {
        "title": _said(record.get("title"), TITLE_CHARS),
        "asked": str(record.get("requested_outcome") or "")[:8000],
        "base_sha": str(record.get("base_sha") or ""),
        "target_branch": str(record.get("target_branch") or ""),
    }
    _unread.pop(rid, None)


async def request_files(inbox, items: list[dict[str, Any]]) -> int:
    """Read the request files not yet in hand; returns how many could not be read. An id outside the
    inbox's own rule (app/engineering_bridge/requests.py) has no file to read and is not asked for."""
    now = time.monotonic()
    wanted = [i for i in items if valid_request_id(i.get("request_id")) and i["request_id"] not in _requests
              and now - _unread.get(i["request_id"], -RETRY_S) >= RETRY_S]
    gate = asyncio.Semaphore(CONCURRENCY)
    await asyncio.gather(*(_read_request(inbox, i, gate) for i in wanted[:MAX_FILE_READS]))
    return sum(1 for i in items if i.get("request_id") and i["request_id"] not in _requests)


# ------------------------------------------------------------------ the trunk and the running commit


async def _compare(inbox, sha: str, ref: str, key: str, gate: asyncio.Semaphore) -> None:
    fact = _commits.setdefault(sha, {})
    async with gate:
        try:
            on = await inbox.on_trunk(sha, ref)
        except GitHubError:
            log.info("could not compare %s with %s", sha[:12], ref[:12], exc_info=True)
            return
    if isinstance(on, NotConnected):
        return
    fact[key] = bool(on)
    fact[f"{key}_at"] = time.monotonic()
    if key == "running":
        fact["running_ref"] = ref


def _due(fact: dict[str, Any], key: str, now: float) -> bool:
    return fact.get(key) is not True and now - fact.get(f"{key}_at", -RETRY_S) >= RETRY_S


async def commit_facts(inbox, shas: list[str], running: str) -> dict[str, dict[str, Any]]:
    """For each commit: whether it is on the trunk, and whether it is in the running commit (only
    asked once it is on the trunk: deploys come from the trunk). None where it is not known. A yes
    is kept; a no is asked again after a minute."""
    gate = asyncio.Semaphore(CONCURRENCY)
    wanted = list(dict.fromkeys(s for s in shas if s))
    now = time.monotonic()
    trunk = [sha for sha in wanted if _due(_commits.get(sha, {}), "trunk", now)][:MAX_COMPARES]
    await asyncio.gather(*(_compare(inbox, sha, TRUNK_REF, "trunk", gate) for sha in trunk))
    if running:
        def stale(fact: dict[str, Any]) -> bool:
            return fact.get("running_ref") != running or _due(fact, "running", now)
        live = [sha for sha in wanted if _commits.get(sha, {}).get("trunk") is True and stale(_commits[sha])]
        await asyncio.gather(*(_compare(inbox, sha, running, "running", gate) for sha in live[:MAX_COMPARES]))
    out = {}
    for sha in wanted:
        fact = _commits.get(sha, {})
        out[sha] = {"trunk": fact.get("trunk"),
                    "running": fact.get("running") if running and fact.get("running_ref") == running else None}
    return out


# ------------------------------------------------------------------ CLIVE's own records


def links() -> dict[str, dict[str, Any]]:
    """For each request CLIVE knows of: the objective it was filed for, and the gaps it closes."""
    out: dict[str, dict[str, Any]] = {}
    try:
        from app.objectives.store import store

        for objective in store().all():
            for filed in objective.engineering or []:
                rid = str(filed.get("request_id") or "")
                if rid:
                    out.setdefault(rid, {"objective": None, "gaps": []})["objective"] = {
                        "id": objective.id, "title": _said(objective.title, 120)}
    except Exception:  # noqa: BLE001 - the board says less; it never fails for this
        log.warning("objectives unreadable for the builds board", exc_info=True)
    try:
        from app.objectives import gaps

        record = gaps.ledger()
        for gap in (record.report()["gaps"] if record is not None else []):
            for linked in gap.get("builds") or []:
                rid = str(linked.get("request_id") or "")
                if rid:
                    out.setdefault(rid, {"objective": None, "gaps": []})["gaps"].append(
                        {"title": _said(gap.get("title"), 120), "hits": int(gap.get("hits") or 0),
                         "last_seen": gap.get("last_seen") or ""})
    except Exception:  # noqa: BLE001 - as above
        log.warning("gap record unreadable for the builds board", exc_info=True)
    return out


# ------------------------------------------------------------------ the board


def _latest_commits(items: list[dict[str, Any]]) -> list[str]:
    titles = {rid: r.get("title", "") for rid, r in _requests.items()}
    shas = []
    for family in board_module.families(items, titles):
        latest = family[-1]
        shas += [board_module._sha(latest.get("candidate_sha")), board_module._landed_sha(latest)]
    return [s for s in shas if s]


async def current() -> dict[str, Any]:
    """The Builds screen's whole payload, as it stands now. Every read it makes of GitHub goes through
    one client for the whole board, four at a time (EngineeringInbox.session)."""
    inbox = engineering_tools._client()
    async with inbox.session():
        payload = await _current(inbox)
    # The release service's line (app/release/status.py): what it last did about deploys, read from
    # its own status file on this server, never from GitHub. Read-only; nothing here can start a deploy.
    from app.release import status as release_status

    payload["release"] = release_status.read()
    return payload


async def _current(inbox) -> dict[str, Any]:
    status, problem = await engineering_tools.loop_status()
    if status is None:
        return {"connected": False, "summary": problem or "The engineering loop's status could not be read.",
                "groups": [], "counts": {}, "problems": [problem] if problem else []}
    data = status.data if status.published else {}
    items = engineering_tools._items(data)
    problems = []
    if problem:
        problems.append(f"Showing the status as last read: a fresh read failed ({problem})")
    unread = await request_files(inbox, items)
    if unread:
        problems.append(f"{unread} request{'s' if unread != 1 else ''} could not be read from GitHub yet, so "
                        f"{'their titles are' if unread != 1 else 'its title is'} missing.")
    running = engineering_tools.running_sha()
    commits = await commit_facts(inbox, _latest_commits(items), running)
    try:
        judgments = decisions.ledger().effective()
    except decisions.DecisionError as exc:
        judgments = {}
        problems.append(str(exc))
    out = board_module.board(items, requests=_requests, commits=commits, running_known=bool(running),
                             links=links(), judgments=judgments, as_of=str(data.get("generated_at") or ""))
    if not status.published:
        out["summary"] = "The engineering loop has not published a status yet."
    out.update(connected=True, problems=problems)
    return out


async def question(key: str) -> dict[str, Any] | None:
    """The question a build puts to George now, by the build's key, or None."""
    payload = await current()
    for group in payload.get("groups") or []:
        for build in group["builds"]:
            if build["key"] == key:
                return build.get("decision")
    return None


def brief(payload: dict[str, Any]) -> dict[str, Any]:
    """What the home's Builds row says: the counts and the summary line."""
    return {"connected": payload.get("connected", False), "summary": payload.get("summary", ""),
            "counts": payload.get("counts", {})}
