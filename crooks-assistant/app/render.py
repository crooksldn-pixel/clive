"""Which card is which, and what has actually changed about it.

`app/presentation.py` decides WHAT a card contains. This decides WHICH card it is — and that
turns out to be the missing half. The live session drew 24 `email_thread` cards across 14
turns and five identical `order` cards, because every path that produced a card produced a NEW
card: a turn re-presented what was already on the glass, a navigation redrew the record it had
just drawn, an enrichment re-rendered the order around it. Nothing anywhere could say "this is
the same card as that one", so nothing could say "and it has not changed".

Three ideas, and every one of them is a number the report can read:

* **Render identity.** A card's identity is its type and the record it is about — an order id,
  a thread id, a set id — never its position in a list. `render_id` is stable across turns,
  across lanes and across enrichments, which is what makes patching in place possible at all.
* **Patch semantics.** Between two renders of one identity exactly one of four things is true:
  it is NEW, its DATA changed, only its VISUAL STATE changed (folded, a pending region, which
  tab is open), or there is NO VISIBLE CHANGE. The fourth is the one the live session kept
  paying for, and the only correct response to it is to draw nothing.
* **A ledger that counts.** `RenderLedger` remembers the fingerprint of every identity it has
  staged, so a repeat is suppressed rather than drawn, and `counts` says how many were.

Nothing here reads a tool, mutates anything, or decides what a card may contain. It hashes the
payload the presentation layer already bounded and compares it with the last one.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# What identifies a record of each kind. The first key with a value wins, so an order card is
# the same card whether the read that produced it returned a gid or only a number.
#
# A kind that is absent from this table has no record of its own — an error, the assistant's
# own words — and is identified by its type alone, which is right: one error card per service
# per turn is what `present()` already builds.
KEY_OF: dict[str, tuple[str, ...]] = {
    "order": ("order_id", "order_number"),
    "order_list": ("set_id", "title", "query"),
    "customer": ("customer_id", "email"),
    "customer_list": ("title", "query"),
    "product": ("product_id", "query"),
    "inventory": ("query",),
    "sales_summary": ("title", "since"),
    "email_list": ("title", "query"),
    "email_thread": ("thread_id",),
    "email_draft": ("subject", "to"),
    "attention": ("for",),
    "confirmation": ("proposal_id",),
    "success": ("proposal_id",),
    "batch_action": ("batch_id",),
    "batch_result": ("batch_id",),
    "error": ("service", "kind"),
    "metric_group": ("title",),
    "ranking": ("title", "mode"),
    "table": ("title",),
    "comparison": ("title",),
    "variant_matrix": ("title",),
    "trend": ("title", "metric"),
    "working_set": ("set_id",),
    # The remote for one of the owner's screens (round 9): one card per screen.
    "screen_remote": ("screen_id",),
    # One of the owner's objectives (round 12): one card per objective, patched as it changes.
    "objective": ("objective_id",),
    "capability": ("build",),
    # A summary is identified by the TASK it answers, not by its title: "Orders today" asked
    # twice is one card, and the returning-customers summary is never the same card as the
    # attention summary however the titles are worded (app/summaries.py).
    "summary_list": ("task", "title"),
    "reply_state": ("thread_id",),
    "variant_picker": ("order_id",),
    "email_compose": ("compose_id",),
    "workspace": ("workspace_id",),
    # A composed surface is identified by the canonical entity it is about and by nothing
    # else (app/workspace.py). That is the point of it: the customer read three times is one
    # card with one identity, so the second read PATCHES the first rather than landing beside
    # it — which is what §6 asks for and what D-3's deck did not do.
    "customer_workspace": ("ref",),
    "order_workspace": ("ref",),
    # The workspace's own header: what this screen IS and what state each of its sections is
    # in (§15, §27 — app/progressive.py). One per turn, patched in place for the life of it,
    # which is what makes "patch the sections, never replace the workspace" possible at all.
    "workspace_plan": ("workspace_id",),
}

# A product or an inventory card is about a product, and the query that found it is not its
# identity: "hoodie" and "the convict hoodie" are the same card. Where the payload carries the
# products themselves, the first one's id is the identity.
NESTED_KEY_OF: dict[str, tuple[str, str]] = {
    "product": ("products", "product_id"),
    "inventory": ("products", "product_id"),
}

# Fields that describe how a card is DRAWN rather than what it says. A change confined to
# these is a visual-state update: the tablet adjusts an attribute and keeps the DOM, the
# scroll, the open tab and the focus exactly as they were.
#
# `pending` is here deliberately. A region going from "still reading" to "read" changes the
# card's data too — and then the data fingerprint says so. `pending` alone changing means the
# asking stopped, which is a mark on a tab, not a redraw.
VISUAL_KEYS = frozenset({"secondary", "pending", "loading", "shell", "tab", "placeholder"})

# The identity a shell card holds until the read it stands for lands. One per type, because a
# shell is a promise about a KIND of card ("orders are coming") and cannot know which record
# it will turn out to be about.
SHELL_SUFFIX = "~shell"

ADDED, DATA, VISUAL, NONE, REMOVED = "add", "data", "visual", "none", "remove"


def key_of(item: dict[str, Any]) -> str:
    """The record a `ui` item is about, as a short string. Empty when it is about none."""
    kind = str(item.get("type") or "")
    data = item.get("data")
    if not isinstance(data, dict):
        return ""
    nested = NESTED_KEY_OF.get(kind)
    if nested is not None:
        rows = data.get(nested[0])
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            found = str(rows[0].get(nested[1]) or "").strip()
            if found:
                return found[:120]
    for name in KEY_OF.get(kind, ()):
        value = data.get(name)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()[:120]
    return ""


def render_id(item: dict[str, Any]) -> str:
    """The stable identity of one card: `type:record`, or `type` when it is about no record.

    The same order, drawn by a spoken question, by a tapped row and by the enrichment that
    followed, is one identity and therefore one card.
    """
    kind = str(item.get("type") or "")
    if not kind:
        return ""
    if is_shell(item):
        return f"{kind}:{SHELL_SUFFIX}"
    key = key_of(item)
    return f"{kind}:{key}" if key else kind


def is_shell(item: dict[str, Any]) -> bool:
    data = item.get("data")
    return bool(isinstance(data, dict) and data.get("shell") is True)


def fingerprint(item: dict[str, Any], *, keys: frozenset[str] | None = None) -> str:
    """A hash of what the card SAYS, with the visual-state fields taken out.

    Bounded and canonical: the presentation layer has already capped every list and truncated
    every string, so this is cheap and stable — the same payload always hashes the same, and a
    payload that differs only in which tab is open does not.
    """
    data = item.get("data")
    if not isinstance(data, dict):
        return ""
    drop = VISUAL_KEYS if keys is None else keys
    body = {k: v for k, v in sorted(data.items()) if k not in drop}
    blob = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def visual_print(item: dict[str, Any]) -> str:
    data = item.get("data")
    if not isinstance(data, dict):
        return ""
    body = {k: data[k] for k in sorted(VISUAL_KEYS) if k in data}
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Patch:
    """One instruction to the glass: draw this card, change this card, or change nothing.

    `replaces` is the identity of the node this one takes the place of — how the shell card
    for "orders are coming" becomes the order list itself without the list being appended
    below it, and the only place in the protocol where one identity hands over to another.
    """

    render_id: str
    op: str
    type: str = ""
    item: dict[str, Any] | None = None
    replaces: str = ""
    seq: int = 0
    at_ms: float | None = None

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.render_id, "op": self.op, "type": self.type, "seq": self.seq}
        if self.item is not None and self.op in (ADDED, DATA, VISUAL):
            out["item"] = self.item
        if self.replaces:
            out["replaces"] = self.replaces
        if self.at_ms is not None:
            out["at_ms"] = round(float(self.at_ms), 1)
        return out


@dataclass(slots=True)
class RenderLedger:
    """What has been drawn, and what it looked like.

    One ledger per workspace. `stage` is the whole interface: hand it the cards a phase
    produced and it returns the patches the glass needs — which is sometimes none at all.
    """

    data_print: dict[str, str] = field(default_factory=dict)
    visual: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    shells: dict[str, str] = field(default_factory=dict)          # type -> the shell's identity
    counts: Counter = field(default_factory=Counter)
    seq: int = 0

    def known(self, identity: str) -> bool:
        return identity in self.data_print

    def has_real(self, kind: str) -> bool:
        """Is there already a card of this kind that is NOT a skeleton?

        The second read of one kind in a turn — an order found, then that order read in full —
        must not put a skeleton up underneath the card it is about to update. That was the
        live session's duplicate in miniature: the same record, twice on the glass.
        """
        shell = f"{kind}:{SHELL_SUFFIX}"
        return any(i != shell and (i == kind or i.startswith(f"{kind}:")) for i in self.order)

    def stage(self, items: list[dict[str, Any]], *, at_ms: float | None = None) -> list[Patch]:
        """The patches for one phase, in the order the cards arrived.

        A card whose fingerprint is unchanged produces NO patch and is counted as suppressed.
        That count is the measurement §25 asks for: the live session's five identical order
        renders would appear here as four.
        """
        patches: list[Patch] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
                continue
            kind = str(item.get("type") or "")
            if not kind:
                continue
            identity = render_id(item)
            if not identity:
                continue
            body, look = fingerprint(item), visual_print(item)
            replaces = ""
            if not self.known(identity) and not is_shell(item):
                # A shell of this kind is standing in for exactly this card: it hands over
                # its place rather than the real card being appended underneath it.
                shell = self.shells.pop(kind, "")
                if shell and shell != identity and self.known(shell):
                    replaces = shell
                    self._forget(shell)
            if is_shell(item):
                self.shells[kind] = identity
            self.seq += 1
            if not self.known(identity):
                self.data_print[identity] = body
                self.visual[identity] = look
                self.order.append(identity)
                self.counts["drawn"] += 1
                patches.append(Patch(identity, ADDED, kind, item, replaces, self.seq, at_ms))
                continue
            if self.data_print[identity] != body:
                self.data_print[identity] = body
                self.visual[identity] = look
                self.counts["data"] += 1
                patches.append(Patch(identity, DATA, kind, item, replaces, self.seq, at_ms))
                continue
            if self.visual[identity] != look:
                self.visual[identity] = look
                self.counts["visual"] += 1
                patches.append(Patch(identity, VISUAL, kind, item, replaces, self.seq, at_ms))
                continue
            # Byte for byte what is already on the glass. This is the render the live session
            # kept doing: it is counted, and it is not drawn.
            self.counts["suppressed"] += 1
            self.counts[f"suppressed:{kind}"] += 1
            self.seq -= 1
        return patches

    def drop_shells(self, *, at_ms: float | None = None) -> list[Patch]:
        """Shells whose read never landed. A skeleton must never be left standing: the live
        session's "Checking the inbox…" was read as calm 34 seconds after the asking stopped.
        """
        patches = []
        for kind, identity in sorted(self.shells.items()):
            if not self.known(identity):
                continue
            self._forget(identity)
            self.seq += 1
            patches.append(Patch(identity, REMOVED, kind, None, "", self.seq, at_ms))
        self.shells.clear()
        return patches

    def drop_shell(self, kind: str, *, at_ms: float | None = None) -> list[Patch]:
        """ONE kind's skeleton, taken down because its read failed (§27).

        `drop_shells` is the end of the turn; this is one read of it going wrong, and the
        difference matters: a failed inbox read must take down the inbox placeholder and
        leave every other section of the workspace exactly as it was.
        """
        identity = self.shells.pop(kind, "")
        if not identity or not self.known(identity):
            return []
        return self.drop(identity, kind, at_ms=at_ms)

    def drop(self, identity: str, kind: str = "", *, at_ms: float | None = None) -> list[Patch]:
        """One card, removed by identity. Nothing else on the glass is touched."""
        if not identity or not self.known(identity):
            return []
        self._forget(identity)
        self.seq += 1
        return [Patch(identity, REMOVED, kind or identity.split(":", 1)[0], None, "", self.seq, at_ms)]

    def _forget(self, identity: str) -> None:
        self.data_print.pop(identity, None)
        self.visual.pop(identity, None)
        if identity in self.order:
            self.order.remove(identity)

    def report(self) -> dict[str, int]:
        """The counts, as the timeline and the report want them: plain ints, no content."""
        return {k: int(v) for k, v in sorted(self.counts.items()) if v}
