"""Today's work as a person sees it: the jobs that are theirs, what is up for grabs, and what has
been done. The owner sees the whole team; a staff member sees their own and the shared pool.

Built from the kept jobs (store.py), today's routines and what CLIVE found live (found.py). A found
job somebody has claimed shows as theirs; an order somebody packed shows as packed, waiting to be
fulfilled; something finished stays finished until the person writes again.
"""

from __future__ import annotations

from typing import Any

from app.work import found as live
from app.work.store import WorkItem, today, work

OPEN_SHOWN = 60
DONE_SHOWN = 30


def _found_state(items: list[WorkItem], since: Any = None) -> dict[str, Any]:
    """What the kept jobs say about one found thing: who has it, who packed it, or that it was
    finished. Finished holds until the thing is newer than the finishing: a customer who writes
    again after their reply is waiting again."""
    claimed = next((i for i in items if i.status == "claimed"), None)
    if claimed is not None:
        packed = bool(claimed.evidence.get("packed"))
        return {"status": "claimed", "item_id": claimed.item_id, "claimed_by": claimed.claimed_by, "packed": packed,
                "packed_at": str(claimed.evidence.get("packed_at") or "") if packed else ""}
    finished = max((i for i in items if i.status == "done"), key=lambda i: i.done_at, default=None)
    if finished is not None:
        newer = live.when(since)
        done_at = live.when(finished.done_at)
        if newer is None or done_at is None or newer <= done_at:
            status = "packed" if finished.evidence.get("packed") and not finished.evidence.get("fulfilled") else "finished"
            return {"status": status, "item_id": finished.item_id, "done_by": finished.done_by}
    return {"status": "open"}


async def today_for(runtime: Any, *, who: str, owner: bool, day: str = "", fresh: bool = False) -> dict[str, Any]:
    day = day or today()
    work.materialise(day)
    kept = work.items()
    sources = await live.found(runtime, fresh=fresh)
    by_ref: dict[str, list[WorkItem]] = {}
    for item in kept:
        if item.ref:
            by_ref.setdefault(item.ref, []).append(item)

    found_rows: list[dict[str, Any]] = []
    for source, answer in sources.items():
        for row in answer.get("items") or []:
            state = _found_state(by_ref.get(row["ref"], []), row.get("since"))
            found_rows.append({**row, "source": source, **state})
    # A kept job about something found today is shown as that found row, with what CLIVE knows
    # about it (the lines to pack, the message); kept on its own only once it is no longer found.
    shown_live = {row["ref"] for row in found_rows}

    def visible(item: WorkItem) -> bool:
        return owner or not item.assignee or item.assignee == who or item.claimed_by == who

    active = [i for i in kept if i.status in ("open", "claimed") and (not i.due or i.due <= day) and visible(i)
              and not (i.source == "found" and (i.status == "open" or i.ref in shown_live))]
    mine = [i for i in active if i.claimed_by == who or (i.status == "open" and i.assignee == who)]
    pool = [i for i in active if i.status == "open" and not i.assignee]
    listed = {i.item_id for i in mine} | {i.item_id for i in pool}
    others = [i for i in active if owner and i.item_id not in listed]
    done = sorted((i for i in kept if i.status == "done" and i.done_at.startswith(day) and (owner or i.done_by == who)),
                  key=lambda i: i.done_at, reverse=True)
    open_found = [r for r in found_rows if r["status"] == "open"]
    mine_found = [r for r in found_rows if r["status"] == "claimed" and r.get("claimed_by") == who]
    others_found = [r for r in found_rows if (r["status"] == "claimed" and r.get("claimed_by") != who) or r["status"] == "packed"]
    return {
        "day": day,
        "mine": [i.summary() for i in mine][:OPEN_SHOWN],
        "mine_found": mine_found[:OPEN_SHOWN],
        "up_for_grabs": [i.summary() for i in pool][:OPEN_SHOWN],
        "found": open_found[:OPEN_SHOWN],
        "in_hand": others_found[:OPEN_SHOWN] if owner else [r for r in others_found if r["status"] == "packed"][:OPEN_SHOWN],
        "team": [i.summary() for i in others][:OPEN_SHOWN],
        "done": [i.summary() for i in done][:DONE_SHOWN],
        "sources": {name: {"available": bool(a.get("available")), "reason": a.get("reason") or "", "count": len(a.get("items") or [])}
                    for name, a in sources.items()},
    }


def found_row(sources: dict[str, dict[str, Any]], ref: str) -> dict[str, Any] | None:
    for answer in sources.values():
        for row in answer.get("items") or []:
            if row.get("ref") == ref:
                return row
    return None
