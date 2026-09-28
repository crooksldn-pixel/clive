"""The capability manifest as something to look at rather than something to listen to.

"What can you do now?" is the question a new owner asks first and the one an experienced owner
asks after an update. It was answered in a paragraph: the manifest was summarised into a
sentence, spoken, and nothing was drawn. A spoken list of thirty capabilities is not a list —
by the fourth item the first is gone.

So the same manifest is grouped by the part of the shop it touches, each entry carrying what it
is and whether it could be done right now, and the whole thing goes on screen while the spoken
answer stays one sentence. The words and the card come from the same manifest, so they cannot
disagree.

Nothing here decides what is possible. `manifest.build()` reads the tool registry and is the
only authority; this arranges what it returns.
"""

from __future__ import annotations

from typing import Any

from app.surfaces import Freshness, Surface

# What the manifest calls each area, and what to call it on screen. The manifest tags every
# tool by prefix (app/capabilities/manifest.py:_FAMILY) and those tags are its words, not
# these — so anything it invents that is not listed here still gets a group, under its own
# name. A capability that quietly vanished from this surface because nobody updated a table
# would be the worst kind of wrong: the screen would say the assistant cannot do something it
# can.
LABELS: dict[str, str] = {
    "the shop": "The shop",
    "the inbox": "The inbox",
    "the read layer": "Sales and stock",
    "bulk changes": "Bulk changes",
    "the assistant": "The assistant",
}
ORDER = tuple(LABELS)

MAX_PER_GROUP = 10
MAX_EXAMPLES = 6

# Things worth saying, shown as chips. A short fixed list of everyday questions; tapping one
# asks it, and it is a model turn like anything said.
EXAMPLES: tuple[str, ...] = (
    "Show me today's orders",
    "Show me order 1938",
    "Which customers need replying to?",
    "How much have we sold today?",
    "What is running out?",
    "Which orders are late?",
)


MAX_WHAT_CHARS = 140


def _clipped(words: str, limit: int = MAX_WHAT_CHARS) -> str:
    """A sentence cut at a word, with an ellipsis to say it was cut.

    Cutting at the character produced "any other order still to s", which reads as a typo
    rather than as a truncation — and ran straight into the label beside it.
    """
    words = " ".join(str(words or "").split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _kind_of(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "name": str(entry.get("name") or ""),
        "what": _clipped(entry.get("what")),
        "kind": kind,
        "area": str(entry.get("area") or "system"),
        "operation": str(entry.get("operation") or ""),
        "risk": str(entry.get("risk") or ""),
        "reversible": bool(entry.get("reversible", True)),
    }


def _grouped(manifest: dict[str, Any], states: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    states = states or {}
    entries: list[dict[str, Any]] = []
    entries += [_kind_of(e, "read") for e in manifest.get("reads") or []]
    entries += [_kind_of(e, "change") for e in manifest.get("writes") or []]
    entries += [_kind_of(e, "bulk") for e in manifest.get("batches") or []]

    for entry in entries:
        state = states.get(entry["operation"]) if entry["operation"] else None
        if isinstance(state, dict):
            entry["state"] = str(state.get("state") or "")
            entry["detail"] = _clipped(state.get("detail"))
        elif entry["kind"] == "read":
            # A read needs no permission beyond the credential the health page already checks.
            entry["state"] = "ready"
        else:
            entry["state"] = "unknown"

    groups: list[dict[str, Any]] = []
    for area in sorted({e["area"] for e in entries}, key=lambda a: (ORDER.index(a) if a in ORDER else len(ORDER), a)):
        mine = [e for e in entries if e["area"] == area]
        mine.sort(key=lambda e: ({"read": 0, "change": 1, "bulk": 2}[e["kind"]], e["name"]))
        groups.append({
            "area": area,
            "label": LABELS.get(area, area[:1].upper() + area[1:]),
            "count": len(mine),
            "truncated": len(mine) > MAX_PER_GROUP,
            "items": _representative(mine),
        })
    return groups


def _representative(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most MAX_PER_GROUP rows, drawn from every kind rather than the first kind.

    The list is sorted reads, then changes, then bulk, and taking `[:MAX_PER_GROUP]` off the
    front of that meant the reads ate the whole group: "the shop" has nine reads and nine
    changes, so the card showed nine reads and ONE change — and dropped cancel, refund, note,
    address, fulfilment, inventory and both tag operations — while its own subtitle said
    "17 readings · 14 changes" and the group carried "More than shown."

    So the budget is shared out a kind at a time, in the same order, until it runs out: every
    kind that exists in a group is represented before any kind gets a second helping. The rows
    stay in their sorted order, so the card does not reshuffle between builds.
    """
    if len(entries) <= MAX_PER_GROUP:
        return entries
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_kind.setdefault(entry["kind"], []).append(entry)
    kept: list[dict[str, Any]] = []
    while len(kept) < MAX_PER_GROUP and any(by_kind.values()):
        for kind in ("read", "change", "bulk"):
            queue = by_kind.get(kind)
            if not queue or len(kept) >= MAX_PER_GROUP:
                continue
            kept.append(queue.pop(0))
    order = {id(e): i for i, e in enumerate(entries)}
    return sorted(kept, key=lambda e: order[id(e)])


def build_surface(
    manifest: dict[str, Any],
    *,
    spoken: str = "",
    states: dict[str, dict[str, Any]] | None = None,
    changed: dict[str, Any] | None = None,
) -> Surface:
    """The capability surface for one build.

    `states` is the per-operation table `/health` already computes (ready / blocked / disabled
    / unknown). It is optional: without it a change reads as "unknown" rather than as ready,
    because claiming a change is available when nobody has checked the scope is the one wrong
    answer here.
    """
    groups = _grouped(manifest, states)
    counts = dict(manifest.get("counts") or {})
    writes_on = bool(manifest.get("writes_enabled"))
    data: dict[str, Any] = {
        "build": str(manifest.get("build") or "")[:40],
        "fingerprint": str(manifest.get("fingerprint") or "")[:16],
        "writes_enabled": writes_on,
        "counts": {
            "reads": int(counts.get("reads") or 0),
            "changes": int(counts.get("writes") or 0),
            "bulk": int(counts.get("batches") or 0),
        },
        "groups": groups,
        "examples": list(EXAMPLES[:MAX_EXAMPLES]),
        "note": ("" if writes_on else "Changes are switched off on the server, so everything here is read-only."),
    }
    if changed:
        # The delta answer: the same surface, with what moved since the last build called out.
        data["changed"] = {
            "since": str(changed.get("since") or "")[:40],
            "added": [str(x)[:120] for x in (changed.get("added") or [])[:12]],
            "gone": [str(x)[:120] for x in (changed.get("gone") or [])[:12]],
        }
    return Surface(
        surface_type="capability",
        ui_type="capability",
        data=data,
        title="What this can do",
        subtitle=(f"{data['counts']['reads']} readings · {data['counts']['changes']} changes"
                  if writes_on else f"{data['counts']['reads']} readings · changes off"),
        freshness=Freshness(source="mac", complete=True),
        spoken_summary=spoken,
    )
