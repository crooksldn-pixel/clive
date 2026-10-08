"""The workspace that arrives in pieces.

`turn_c8eb4cffe077` — "look up today's orders and today's emails and see if anything
correlates" — took **7,975 ms to first cards**. Not to the answer: to the first pixel of
content. `shopify_list_orders`, then `gmail_search`, then `gmail_read_thread`, and only when
the last of them came back was anything drawn at all. Session-wide the Mac spent 17,302 ms
reading and the owner spent 13,388 ms waiting, and he said what it felt like: the system
"waits and then dumps a large chunk".

The read graph is not the problem. Running it in one wave is already what `app/reads/
scheduler.py` does. The problem is that the SCREEN waited for the graph, because `present()`
is called once, at the end, over the whole list of calls — so the first fact and the last fact
arrive together however fast the reads were.

This module is the other half: a workspace that exists from the first moment and fills in.

**Since 7 October 2026 (DEC-069) a turn's workspace is QUIET.** The owner, that day: "if you
ask a question, sometimes you'll get shown irrelevant screens that just happened during a
search process" — the customer's order count, somebody else's email, today's threads and
today's orders, when all he wanted was the reply to that customer. So `POST /turn` begins its workspace with
`quiet=True`: while CLIVE works the glass says what it is doing in words (the /state poll's
running tool, web/app.js `DETAIL_WORDS`), and nothing a read found is staged until `complete`,
which reconciles only what the answer is about (`app/focus.py`). The machinery below — shells,
the header, a read's cards as it lands — is unchanged and still what a non-quiet workspace
does; no caller begins one any more.

    identity         WHAT this workspace is, and the sections coming            ~0 ms
    first fact       the first read lands; its card takes the skeleton's place
    next section     the second read lands; its card is patched in beside it
    complete         the turn returns; what changed is patched, what did not is NOT redrawn

**§15 — identity, not a spinner.** Phase 4 put a skeleton up and called that progress. An
empty grey box is not progress: it does not say what workspace this is, so there is nothing
on it to read. A compound task now establishes its IDENTITY first — the workspace's name and
one line per section, each in a state —

    TODAY'S ACTIVITY
    Orders        loading…
    Inbox         waiting…

— and then each section is PATCHED IN PLACE as it lands: `Orders · 7`, then `Inbox · 4`. The
workspace is never replaced, never reordered, never duplicated. That card is `workspace_plan`
(`PLAN_TYPE`), the one card the Mac stages that `present()` never builds, and it goes up when
two conditions hold: there are at least two sections to name, and no fact has landed yet. A
one-section task already names itself on the titled skeleton of the single card it is about,
and a header that arrives after the cards it describes is a fifth wheel — so the earliest
honest moment is where this is done from: `app/reads/scheduler.py` names the sections of a
read plan before it runs the first read of it.

**§27 — five deliberate states**, for the workspace and for every section of it: LOADING,
PARTIAL, READY, EMPTY, ERROR. **EMPTY IS NOT ERROR**: a Gmail search that found no threads
keeps the workspace and says `Inbox — No messages found`, rather than replacing the workspace
with an empty email screen. An ERROR is confined to the section whose read failed; the
sections that landed keep what they found, and the workspace as a whole is PARTIAL, not dead.

Four numbers, and they are the point of the exercise (§15, §25). They are Phase 4's four,
RENAMED to say what they actually measure:

    time_to_visible_shell             when the screen said what workspace this is
                                      (Phase 4: `time_to_shell`, which counted an anonymous
                                      skeleton — §15 says that does not count, so this one
                                      is only set by a shell carrying IDENTITY)
    time_to_first_meaningful_fact     when the first real value was on it
                                      (Phase 4: `time_to_first_fact`, unchanged in meaning:
                                      a shell is not a fact, an error about the world is)
    time_to_first_actionable_surface  when it could be USED — a record or rows, not a state
                                      (Phase 4: `time_to_first_useful_workspace`)
    time_to_complete_workspace        when nothing more was coming (unchanged)

They live beside `facts_ms` / `workspace_ms` / `prose_wait_ms` in the turn's performance
record rather than replacing them: those three measure the MAC (when it held the data, when
it had built the cards, how long the prose took afterwards), and these four measure the GLASS.

What this module may not do, and structurally cannot:

* It never reads. `observe` is handed a result a read already returned.
* It never mutates a session, issues an id, or stages a change. The cards it stages are built
  by `present()` with no session at all, so nothing is remembered twice and no id is issued
  before the turn's own presentation issues it.
* It never invents a value. A skeleton carries a count and a word; every other field on every
  card comes from `app/presentation.py`, key by key, as it always has.
* A failure here is never a failed turn. Every public entry point is called inside a guard at
  its caller, and everything here is pure bookkeeping over payloads that already exist.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.render import ADDED, DATA, SHELL_SUFFIX, Patch, RenderLedger, render_id

log = logging.getLogger("crooks.progressive")

# ----------------------------------------------------------------------- §27, the five states
#
# One vocabulary for the workspace and for every section of it. WAITING is deliberately not
# one of them: it describes a read that has not started, which is a fact about the plan rather
# than a state of the workspace — a workspace all of whose sections are waiting is LOADING.
LOADING, PARTIAL, READY, EMPTY, ERROR = "loading", "partial", "ready", "empty", "error"
WAITING = "waiting"
STATES = (LOADING, PARTIAL, READY, EMPTY, ERROR)

# The card that carries the workspace's identity and its sections' states. It is the only card
# the Mac stages that `present()` never builds, which is why its name is here: the tablet's
# renderer (web/ui.js `renderWorkspacePlan`) and `app/render.py KEY_OF` are held against this
# by `tests/test_progressive_states.py`.
PLAN_TYPE = "workspace_plan"

# The four numbers §15 asks for, named once so the turn's performance record and its log
# cannot drift from them (app/routes/turn.py reads this tuple).
TIMINGS = (
    "time_to_visible_shell",
    "time_to_first_meaningful_fact",
    "time_to_first_actionable_surface",
    "time_to_complete_workspace",
)

# What each read is going to put on the screen, so a skeleton can stand there while it runs.
# Read alongside `presentation._from_result`, which is the code that decides for real: the
# test `test_every_shell_promises_a_card_the_renderer_can_draw` holds the two together, so a
# read that changes its card cannot leave a skeleton promising the old one.
SHELL_OF_TOOL: dict[str, str] = {
    "shopify_list_orders": "order_list",
    "shopify_find_order": "order",
    "shopify_order_detail": "order",
    "shopify_customer_history": "customer",
    "shopify_find_customer": "customer",
    "shopify_inventory": "inventory",
    "shopify_sales_summary": "sales_summary",
    "shopify_product_info": "product",
    "gmail_search": "email_list",
    "gmail_read_thread": "email_thread",
}

# Which SECTION of a workspace each card belongs to, and what that section is called on the
# workspace's own header. Two cards of one section are one section: an order list and an order
# are both Orders, a thread and a search are both the Inbox. `tests/test_progressive_states.py`
# holds this against SHELL_OF_TOOL, so a read whose card has no section cannot exist.
SECTION_OF_KIND: dict[str, tuple[str, str]] = {
    "order": ("orders", "Orders"),
    "order_list": ("orders", "Orders"),
    "customer": ("customer", "Customer"),
    "customer_list": ("customer", "Customers"),
    "product": ("products", "Products"),
    "inventory": ("stock", "Stock"),
    "sales_summary": ("sales", "Sales"),
    "email_list": ("inbox", "Inbox"),
    "email_thread": ("inbox", "Inbox"),
}

# The words on a skeleton. Never a value, never a count of anything that has not been read —
# the kind of thing that is coming, and that is all it is allowed to say.
SHELL_WORDS: dict[str, tuple[str, int]] = {
    "order": ("Order", 4),
    "order_list": ("Orders", 4),
    "customer": ("Customer", 3),
    "customer_list": ("Customers", 3),
    "product": ("Product", 3),
    "inventory": ("Stock", 4),
    "sales_summary": ("Sales", 3),
    "email_list": ("Email", 4),
    "email_thread": ("Email thread", 3),
}

# A card that is worth looking at: it is about a record, or it carries rows. An error, the
# assistant's own sentence, the context stack and the workspace's own header are none of
# those, which is why a turn that drew only those is the failure §8 is about rather than a
# workspace. The header is on this list deliberately: §15's whole point is that a shell,
# however well it names itself, is not a fact and is not something the owner can act on.
NOT_USEFUL = frozenset({"assistant", "error", "context_stack", PLAN_TYPE})
ROW_KEYS = ("orders", "threads", "messages", "customers", "products", "rows", "items", "metrics", "points", "cells")

# Bounds. The patch log is read by a tablet that polls every 400 ms and may miss a poll; it is
# not a transcript, and a turn that produced sixty patches has a bug upstream.
MAX_PATCHES = 60
MAX_LIVE = 24


def _useful(item: dict[str, Any]) -> bool:
    kind = str(item.get("type") or "")
    data = item.get("data")
    if kind in NOT_USEFUL or not isinstance(data, dict):
        return False
    if data.get("shell") is True:
        return False
    if any(isinstance(data.get(key), list) and data[key] for key in ROW_KEYS):
        return True
    from app.render import key_of

    return bool(key_of(item))


# What a skeleton says when the Mac cannot name what is coming. §15: a box that says this and
# nothing else is NOT a visible shell, and `_identity` refuses to count it as one.
GENERIC_TITLE = "Reading"


def shell_item(kind: str, *, title: str = "", rows: int = 0) -> dict[str, Any]:
    """One skeleton card, in the same `{type, data}` shape as every other card.

    `shell` is the whole of what makes it one. The tablet draws a bounded placeholder for any
    card whose data says so (web/ui.js `skeletonCard`), which is why this adds nothing to the
    vocabulary: there is no skeleton type to keep in step with anything.
    """
    words, count = SHELL_WORDS.get(kind, (GENERIC_TITLE, 3))
    return {
        "type": kind,
        "data": {"shell": True, "loading": True, "title": str(title or words)[:40], "placeholder": int(rows or count)},
    }


def _identity(item: dict[str, Any]) -> bool:
    """Does this patch put IDENTITY on the glass — does the screen now say what it is about?

    §15's rule, and the whole of the `time_to_shell` → `time_to_visible_shell` rename: the
    workspace's own header with a name on it, a skeleton that names its section ("Orders"),
    or a real card about a record. A bounded grey box saying "Reading…" is none of those and
    is not progress, however early it appeared.
    """
    data = item.get("data")
    if not isinstance(data, dict):
        return False
    kind = str(item.get("type") or "")
    if kind == PLAN_TYPE:
        return bool(str(data.get("title") or "").strip())
    if data.get("shell") is True:
        title = str(data.get("title") or "").strip()
        return bool(title) and title != GENERIC_TITLE
    return _useful(item)


@dataclass(slots=True)
class Section:
    """One part of a workspace, and what state it is in (§27).

    `value` is a count the Mac has READ — never an estimate, never a percentage. `note` is the
    one line an EMPTY or an ERROR section says instead: "No messages found", "Gmail did not
    answer". Which is the whole of EMPTY IS NOT ERROR: two states, two sentences, one card.
    """

    name: str
    label: str
    kind: str
    state: str = WAITING
    value: str = ""
    note: str = ""

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "label": self.label, "state": self.state}
        if self.value:
            out["value"] = self.value
        if self.note:
            out["note"] = self.note
        return out


@dataclass(slots=True)
class Workspace:
    """One turn's screen, as it fills in. Owned by the session that asked."""

    session_id: str
    turn_id: str = ""
    branch_id: str = ""
    clock: Callable[[], float] = time.perf_counter
    started: float = 0.0
    ledger: RenderLedger = field(default_factory=RenderLedger)
    patches: list[Patch] = field(default_factory=list)
    revision: int = 0
    # §15: what this workspace IS, and the sections it is made of, each in a state (§27).
    title: str = ""
    sections: OrderedDict[str, Section] = field(default_factory=OrderedDict)
    planned: bool = False
    # §15's four numbers, measured on the GLASS. The module docstring says what each one
    # means and what Phase 4 called it.
    visible_shell_ms: float | None = None
    fact_ms: float | None = None
    actionable_ms: float | None = None
    complete_ms: float | None = None
    finished: bool = False
    # [flow, 7 Oct — DEC-069] A turn's workspace is QUIET: while CLIVE works the owner sees
    # progress words only, and nothing a read found reaches the glass until the answer says
    # what it is about. The sections still keep their states (what is being read, what has
    # landed), but no shell, no header and no read's card is staged before `complete`.
    quiet: bool = False

    def __post_init__(self) -> None:
        if not self.started:
            self.started = self.clock()

    # ----------------------------------------------------------------- the sections (§15, §27)

    def section(self, kind: str) -> Section | None:
        """The section a card of this kind belongs to, made if this is the first of them."""
        found = SECTION_OF_KIND.get(str(kind or ""))
        if found is None:
            return None
        name, label = found
        held = self.sections.get(name)
        if held is None:
            held = Section(name=name, label=label, kind=str(kind))
            self.sections[name] = held
        return held

    @property
    def state(self) -> str:
        """§27, for the workspace as a whole, read from the states of its sections.

        EMPTY and ERROR are not the same thing, and neither of them is the end of the
        workspace: one empty section beside a full one is READY, and a workspace whose inbox
        read failed is PARTIAL — what landed is still there and still usable.
        """
        states = [s.state for s in self.sections.values()]
        if not states:
            return READY if self.finished else LOADING
        if all(s in (WAITING, LOADING) for s in states):
            return LOADING
        if all(s == EMPTY for s in states):
            return EMPTY
        if all(s == ERROR for s in states):
            return ERROR
        if any(s in (WAITING, LOADING, ERROR) for s in states):
            return PARTIAL
        return READY

    def _plan_item(self) -> dict[str, Any]:
        """The workspace's own header, as a card. Never a value the Mac has not read: a
        section says `loading…`, `waiting…`, what it found, or why it found nothing."""
        title = self.title or " · ".join(s.label for s in self.sections.values())
        return {
            "type": PLAN_TYPE,
            "data": {
                "workspace_id": self.turn_id or self.session_id or "workspace",
                "title": str(title or "Workspace")[:60],
                "state": self.state,
                "sections": [s.public() for s in self.sections.values()],
            },
        }

    def plan(self, title: str = "", kinds: tuple[str, ...] | list[str] = ()) -> list[Patch]:
        """Name this workspace and the sections coming, and put that on the glass NOW.

        §15: identity first. The header is ONE card for the life of the turn — patched in
        place as each section lands, never replaced, and the sections under it never reorder.
        """
        if title:
            self.title = str(title)[:60]
        for kind in list(kinds)[:6]:
            self.section(kind)
        if self.fact_ms is None:
            self.planned = True
        return self._plan_now(self.at_ms())

    def _plan_now(self, at_ms: float) -> list[Patch]:
        """The header, staged or patched.

        It goes up once there are two sections to name — a one-section task already names
        itself on the titled skeleton of the single card it is about, and a header over one
        card is a second placeholder for the same thing. After that, every change to a
        section is a patch to this one card; a restage that changes nothing produces no patch
        at all, because the ledger sees to that (§25).

        And it goes up BEFORE the facts or not at all. The header is identity: a header that
        arrives after the cards it describes is a fifth wheel, and appending one under a
        screen the owner is already reading is the late clutter D-8 is about. So a workspace
        that learns of its second section only when that section's card lands keeps the cards
        as its identity and draws no header.
        """
        if self.quiet or not self.sections or (not self.planned and (len(self.sections) < 2 or self.fact_ms is not None)):
            return []
        self.planned = True
        return self._record(self.ledger.stage([self._plan_item()], at_ms=at_ms))

    def _observe(self, items: list[dict[str, Any]]) -> None:
        """What the cards that just landed say about their sections (§27).

        A read that returned rows makes its section READY and says how many. A read that
        returned none makes it EMPTY, with the sentence the presentation layer already wrote
        for the card — "No messages found" is an answer about the shop — and EMPTY IS NOT
        ERROR: the workspace stays, every section stays, and nothing is replaced.
        """
        for item in items or []:
            if not isinstance(item, dict):
                continue
            data = item.get("data")
            if not isinstance(data, dict) or data.get("shell") is True:
                continue
            kind = str(item.get("type") or "")
            if kind == PLAN_TYPE:
                continue
            section = self.section(kind)
            if section is None:
                continue
            count = _count_of(kind, data)
            if data.get("empty") is True or count == 0:
                section.state, section.value = EMPTY, ""
                section.note = str(data.get("note") or "Nothing found")[:80]
            else:
                section.state = READY
                section.value = "" if count is None else str(count)
                section.note = ""

    def in_flight(self) -> list[str]:
        """The sections whose reads have not landed, in the order they were planned.

        The join with the workspace composition (`app/presentation.py present(pending=…)`,
        which draws a section whose read is still running as loading): WHEN a section is
        in flight is known here and nowhere else, and WHAT goes in it is composed there. A
        section that has already landed, found nothing, or failed is not in flight — it has
        an answer, and `pending` is not the word for an answer.
        """
        return [s.name for s in self.sections.values() if s.state in (WAITING, LOADING)]

    def _settle_sections(self, at_ms: float) -> list[Patch]:
        """The sections this turn never got to, at the end of it.

        A placeholder is never left saying "loading…": the live session's "Checking the
        inbox…" was still on the glass 34.8 seconds after the asking had stopped, read as calm
        while a customer waited. A read that STARTED and never came back is an ERROR on its
        own section; a section whose read never started was never part of this workspace.
        """
        for name, section in list(self.sections.items()):
            if section.state == WAITING:
                del self.sections[name]
            elif section.state == LOADING:
                section.state, section.value = ERROR, ""
                section.note = "That lookup did not come back"
        if self.sections or not self.planned:
            return []
        self.planned = False
        return self._record(self.ledger.drop(render_id(self._plan_item()), PLAN_TYPE, at_ms=at_ms))

    # ----------------------------------------------------------------- the phases

    def at_ms(self) -> float:
        return max(0.0, (self.clock() - self.started) * 1000.0)

    def shell(self, kinds: tuple[str, ...] | list[str], *, title: str = "") -> list[Patch]:
        """The workspace's identity, and a skeleton for each card the Mac knows is coming."""
        now = self.at_ms()
        if title:
            self.title = str(title)[:60]
        wanted = [kind for kind in list(kinds)[:4] if kind in SHELL_WORDS]
        for kind in wanted:
            self.section(kind)
        if self.quiet:
            return []
        patches = self._plan_now(now)
        return patches + self._record(self.ledger.stage([shell_item(kind) for kind in wanted], at_ms=now))

    def starting(self, tool: str) -> list[Patch]:
        """A read has begun. Its section says so, and where its card is known its skeleton
        goes up now.

        Not when a real card of that kind is already on the glass: an order found and then
        read in full is one card being filled in, and a skeleton under it would be exactly
        the duplicate this pass exists to remove.
        """
        kind = SHELL_OF_TOOL.get(str(tool or ""))
        if not kind:
            return []
        now = self.at_ms()
        section = self.section(kind)
        if section is not None and section.state == WAITING:
            section.state = LOADING
        if self.quiet:
            return []
        patches = self._plan_now(now)
        if self.ledger.has_real(kind):
            return patches
        return patches + self._record(self.ledger.stage([shell_item(kind)], at_ms=now))

    def landed(self, tool: str) -> None:
        """A read came back on a quiet workspace (DEC-069): its section is no longer being read.
        Nothing is staged and no count is claimed — the card it drew may not be the answer."""
        section = self.section(SHELL_OF_TOOL.get(str(tool or ""), ""))
        if section is not None and section.state in (WAITING, LOADING):
            section.state = READY

    def failed(self, tool: str, why: str = "") -> list[Patch]:
        """A read did not come back (§27). Its section says so — and only its section.

        An error in one part of a workspace never destroys another: the orders that landed
        keep saying what they found, their card is untouched, and the workspace is PARTIAL
        rather than an error screen. The failed read's own skeleton comes down, because
        nothing is coming to fill it.
        """
        kind = SHELL_OF_TOOL.get(str(tool or ""))
        if not kind:
            return []
        now = self.at_ms()
        section = self.section(kind)
        if section is not None and section.state not in (READY, EMPTY):
            section.state, section.value = ERROR, ""
            section.note = str(why or "That lookup failed")[:80]
        if self.quiet:
            return []
        patches = self._record(self.ledger.drop_shell(kind, at_ms=now))
        return patches + self._plan_now(now)

    def facts(self, items: list[dict[str, Any]]) -> list[Patch]:
        """A read has landed. Its section is patched in place; its cards take their
        skeletons' places, or are added."""
        now = self.at_ms()
        self._observe(list(items))
        if self.quiet:
            # A search in progress never takes the screen (DEC-069): the section knows it has
            # landed, and the card waits for the answer to say whether it is what it is about.
            return []
        patches = self._plan_now(now)
        patches += self._record(self.ledger.stage(list(items), at_ms=now))
        self._measure(patches, now)
        return patches

    def complete(self, items: list[dict[str, Any]]) -> list[Patch]:
        """The turn's own presentation, reconciled against what is already on the glass.

        This is the moment the old code redrew everything. What it does now is compare: the
        cards that are unchanged produce nothing at all, the ones that gained a rail or an
        enrichment are patched in place, and any skeleton whose read never landed is taken
        down rather than left saying "reading…".
        """
        now = self.at_ms()
        self._observe(list(items))
        patches = self._record(self.ledger.stage(list(items), at_ms=now))
        self._measure(patches, now)
        patches += self._record(self._drop_undrawn(items, now))
        patches += self._settle_sections(now)
        patches += self._plan_now(now)
        patches += self._record(self.ledger.drop_shells(at_ms=now))
        self.complete_ms = now
        self.finished = True
        return patches

    def _drop_undrawn(self, items: list[dict[str, Any]], at_ms: float) -> list[Patch]:
        """The cards a read staged that the turn's own answer does not contain.

        A read's cards go up the moment it lands, before anyone knows whether the answer will
        show them. A recipe that reads a list only to work from it draws its own card instead
        (`RecipeAnswer.drawn`), and the list's card was left standing beneath the answer: "any
        emails need my attention" put a revenue ranking of the 25 customers it had checked,
        and the month's totals, under the reply queue. The glass ends as the answer — the
        workspace's own header and its skeletons are settled by their own rules below.
        """
        keep = {render_id(item) for item in items if isinstance(item, dict)}
        out: list[Patch] = []
        for identity in list(self.ledger.order):
            if identity in keep or identity.endswith(f":{SHELL_SUFFIX}") or identity.split(":", 1)[0] == PLAN_TYPE:
                continue
            out += self.ledger.drop(identity, at_ms=at_ms)
        return out

    def _measure(self, patches: list[Patch], now: float) -> None:
        """§15's two middle numbers. A shell is not a fact, however well it names itself, and
        the workspace's own header is not something the owner can act on."""
        for patch in patches:
            if patch.op not in (ADDED, DATA) or patch.item is None or patch.type == PLAN_TYPE:
                continue
            data = patch.item.get("data")
            if isinstance(data, dict) and data.get("shell") is True:
                continue
            if self.fact_ms is None:
                self.fact_ms = now
            if self.actionable_ms is None and _useful(patch.item):
                self.actionable_ms = now

    # ----------------------------------------------------------------- what the glass reads

    def _record(self, patches: list[Patch]) -> list[Patch]:
        if not patches:
            return []
        # §15's first number, at the one place every patch passes through: the moment the
        # screen said what it was about. An anonymous skeleton does not count (`_identity`).
        if self.visible_shell_ms is None:
            for patch in patches:
                if patch.item is not None and _identity(patch.item):
                    self.visible_shell_ms = patch.at_ms if patch.at_ms is not None else self.at_ms()
                    break
        self.patches.extend(patches)
        if len(self.patches) > MAX_PATCHES:
            del self.patches[: len(self.patches) - MAX_PATCHES]
        self.revision = self.patches[-1].seq
        return patches

    def public(self, since: int = 0) -> dict[str, Any]:
        """The patches the tablet has not seen, and where the workspace now stands.

        `since` is the last `seq` it applied. A tablet that missed a poll catches up; one that
        has seen everything is told so and draws nothing, which is the same rule as §25's:
        no visible change means no work.
        """
        try:
            cursor = int(since)
        except (TypeError, ValueError):
            cursor = 0
        pending = [p.public() for p in self.patches if p.seq > cursor]
        return {
            "revision": self.revision,
            "turn_id": self.turn_id,
            "branch_id": self.branch_id,
            "complete": bool(self.finished),
            # What this workspace is and how far it has got (§15, §27). The cards say it too —
            # the header is one of them — and a poll that arrives between patches can read it
            # here without reassembling the sections itself.
            "title": self.title,
            "state": self.state,
            "patches": pending,
            # A tablet that fell far enough behind that the log no longer reaches its cursor
            # must redraw from the turn's payload rather than apply half a sequence.
            "gap": bool(pending and self.patches and pending[0]["seq"] > cursor + 1 and cursor > 0),
            "timings_ms": self.timings(),
            "renders": self.ledger.report(),
        }

    def timings(self) -> dict[str, float | None]:
        """§15's four, in the order the owner experiences them. Keys named in `TIMINGS`."""
        return {
            "time_to_visible_shell": _ms(self.visible_shell_ms),
            "time_to_first_meaningful_fact": _ms(self.fact_ms),
            "time_to_first_actionable_surface": _ms(self.actionable_ms),
            "time_to_complete_workspace": _ms(self.complete_ms),
        }


def _ms(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


# What a count means on each kind of card, and the only keys it may be read from. Kept per
# kind rather than "the first list on the card", because the first list on an ORDER is its
# line items and `Orders · 3` would then be a count of socks. A kind that is not here is about
# one record and gets no count at all — never a 1 invented to fill the space.
COUNT_OF_KIND: dict[str, tuple[str, ...]] = {
    "order_list": ("count", "orders"),
    "customer_list": ("count", "customers"),
    "email_list": ("count", "threads"),
    "email_thread": ("count", "messages"),
    "product": ("count", "products"),
    "inventory": ("count", "products"),
}


def _count_of(kind: str, data: dict[str, Any]) -> int | None:
    """How many things a card carries, as the card itself says — never a guess.

    `count` is what the presentation layer puts on a listing. Returns None for a card about
    one record, and 0 only when the read genuinely found nothing (which is EMPTY, not ERROR).
    """
    for key in COUNT_OF_KIND.get(str(kind or ""), ()):
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, list):
            return len(value)
    return None


# --------------------------------------------------------------------------- the live ones

# One workspace per half of one conversation, bounded, oldest evicted. Held here rather than
# on the Session because it is about a TURN: it is built when the turn starts and read by
# /state while that turn runs, and a session that is asleep should not be holding one.
_LIVE: OrderedDict[str, Workspace] = OrderedDict()


def _key(session_id: str, branch_id: str = "") -> str:
    return f"{str(session_id or '')}/{str(branch_id or '')}"


def begin(session_id: str, *, turn_id: str = "", branch_id: str = "",
          clock: Callable[[], float] | None = None, quiet: bool = False) -> Workspace:
    """A turn has started: a working shell, now, before anything has been read. What the
    shell holds is named by its sections as each read starts (`starting`); nothing guesses
    from the words what is coming.

    `quiet` (what `POST /turn` asks for since DEC-069): nothing reaches the glass until the
    turn's own answer is reconciled in `complete` — the owner sees progress words, then only
    what the answer is about."""
    workspace = Workspace(
        session_id=str(session_id or ""), turn_id=str(turn_id or ""), branch_id=str(branch_id or ""),
        clock=clock or time.perf_counter, quiet=bool(quiet),
    )
    _LIVE[_key(session_id, branch_id)] = workspace
    while len(_LIVE) > MAX_LIVE:
        _LIVE.popitem(last=False)
    workspace.shell(())
    return workspace


def current(session_id: str, branch_id: str = "") -> Workspace | None:
    """The workspace a poll should read: this half's, or the session's only one."""
    found = _LIVE.get(_key(session_id, branch_id))
    if found is not None:
        return found
    prefix = f"{str(session_id or '')}/"
    mine = [w for k, w in _LIVE.items() if k.startswith(prefix)]
    return mine[-1] if len(mine) == 1 else None


def forget(session_id: str, branch_id: str = "") -> None:
    _LIVE.pop(_key(session_id, branch_id), None)


def reset() -> None:
    """For tests, and for a Mac that has just been restarted."""
    _LIVE.clear()


# Whether the read running now is one the OWNER is waiting for. A speculative read
# (app/anticipation, `origin="predicted"`) must never put a card on the glass: it was nobody's
# question, and D-4 is what happens when anticipation is allowed to spend the foreground's
# room. Set false around a predicted plan by app/reads/scheduler.py; everything else — the
# model's tool calls, a recipe's reads, a tapped navigation — is the owner's.
FOREGROUND: ContextVar[bool] = ContextVar("crooks_progressive_foreground", default=True)


@contextmanager
def background() -> Any:
    """Run reads that nobody asked for. Their cards are not staged."""
    token = FOREGROUND.set(False)
    try:
        yield
    finally:
        FOREGROUND.reset(token)


# The workspace the read running on this task was issued into, set by `starting` and read when
# the same read lands or fails. A read belongs to the turn that asked for it: when a newer
# instruction to the same half has begun a workspace of its own while the read was out, what
# the read found is not put on the newer one's glass (the 2026-09-28 deploy review, round 9,
# D2-01: a turn the owner has moved on from publishes nothing). Per task, so reads running
# side by side each keep their own.
_ISSUED_INTO: ContextVar[Any] = ContextVar("crooks_progressive_issued_into", default=None)


def _workspace_for(session: Any, branch_id: str = "") -> Workspace | None:
    """The workspace of the half this work is for: the one named, else the running request's
    own half (`app/tools/context.py` acting_branch). It was the FOCUSED half, so a read made by
    the half put aside, while the focused half was answering something else, was staged on the
    focused half's glass (round 9, D2-03)."""
    if not FOREGROUND.get():
        return None
    session_id = str(getattr(session, "session_id", "") or "")
    if not session_id:
        return None
    if not branch_id:
        from app.tools.context import acting_branch

        branch_id = acting_branch(session)
    return current(session_id, branch_id)


def _landing_on(session: Any) -> Workspace | None:
    """The live workspace a read that has come back may put its cards on: the one it was
    issued into, while that is still the one on this half's glass."""
    workspace = _workspace_for(session)
    issued = _ISSUED_INTO.get()
    if issued is not None and issued is not workspace:
        return None
    return workspace


def starting(session: Any, tool: str) -> None:
    """A read has been issued. Never raises: a skeleton is not worth a failed turn."""
    try:
        workspace = _workspace_for(session)
        _ISSUED_INTO.set(workspace)
        if workspace is not None and not workspace.finished:
            workspace.starting(tool)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break a read
        log.debug("progressive shell for %s failed: %s", tool, type(exc).__name__)


def planning(session: Any, tools: list[str] | tuple[str, ...]) -> None:
    """A read plan is about to run: the workspace says what it will be made of (§15).

    This is the earliest honest moment for a compound task — the graph is known and not one
    read of it has gone out yet, so the sections can be named and shown WAITING rather than
    the owner watching an empty screen until the last of them lands. Never raises, and never
    invents: the sections are the cards the planned reads are going to draw.
    """
    try:
        workspace = _workspace_for(session)
        if workspace is None or workspace.finished:
            return
        kinds = [SHELL_OF_TOOL[tool] for tool in tools if tool in SHELL_OF_TOOL]
        seen: list[str] = []
        for kind in kinds:
            if kind not in seen:
                seen.append(kind)
        if len(seen) > 1:
            workspace.plan(kinds=seen)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break a read plan
        log.debug("progressive plan failed: %s", type(exc).__name__)


def in_flight(session: Any) -> list[str]:
    """Which sections of this half's workspace are still being read.

    For the workspace composition to draw a section as loading rather than as absent
    (`app/presentation.py present(pending=…)`): the states live here, the cards live there,
    and this is the whole of what has to cross between them. Never raises and never invents —
    an empty list means nothing is in flight, which is also what it says when there is no
    workspace at all.
    """
    try:
        workspace = _workspace_for(session)
        return [] if workspace is None else workspace.in_flight()
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break a presentation
        log.debug("progressive in-flight sections failed: %s", type(exc).__name__)
        return []


def failed(session: Any, tool: str, why: str = "") -> None:
    """A read did not come back. Its section says so, and nothing else changes (§27).

    Never raises, for the same reason `starting` does not: a workspace that could not record
    a failure is not a failed turn, and the spoken answer still says what happened.
    """
    try:
        workspace = _landing_on(session)
        if workspace is not None and not workspace.finished:
            workspace.failed(tool, why)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break the error path
        log.debug("progressive failure for %s failed: %s", tool, type(exc).__name__)


def observe(session: Any, name: str, result: Any) -> None:
    """A read has landed: its cards, staged now, patched in place on the glass.

    `present()` is called with NO session, deliberately. It shapes the payload and nothing
    else — nothing is remembered onto the context stack and no id is issued, because the
    turn's own presentation does both when the turn ends and doing them twice would put a
    record on the stack the owner never saw and issue an id nobody was shown.
    """
    try:
        workspace = _landing_on(session)
        if workspace is None or workspace.finished or not isinstance(result, dict):
            return
        if workspace.quiet:
            # Nothing of it goes on the glass before the answer (DEC-069), so it is not shaped:
            # its section only learns that the read came back.
            workspace.landed(str(name))
            return
        from app.presentation import present
        from app.providers.base import ToolCall

        items = present([ToolCall(name=str(name), args={}, ok=True, result=result)])
        if items:
            workspace.facts(items)
    except Exception as exc:  # noqa: BLE001 — a card that could not be staged early still arrives late
        log.debug("progressive facts for %s failed: %s", name, type(exc).__name__)


def complete(session: Any, items: list[dict[str, Any]], *, branch_id: str = "") -> dict[str, Any]:
    """The turn's final cards, reconciled. Returns the numbers for the performance record."""
    try:
        workspace = _workspace_for(session, branch_id)
        if workspace is None:
            return {}
        patches = workspace.complete(list(items or []))
        return {
            **workspace.timings(),
            "renders": workspace.ledger.report(),
            "revision": workspace.revision,
            "turn_id": workspace.turn_id,
            # The reconciliation itself, so the turn's own response can carry it: the tablet
            # stops polling the moment the turn answers, and these are the patches that would
            # otherwise never be collected.
            "patches": [p.public() for p in patches],
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("progressive reconciliation failed: %s", type(exc).__name__)
        return {}


def suppressed_of(patches: list[Patch]) -> int:
    return sum(1 for p in patches if p.op == DATA)


def identities(items: list[dict[str, Any]]) -> list[str]:
    """The render identities of a list of cards, in order. Used by the tablet's own tests and
    by the turn payload, so the glass and the Mac name the same cards the same way."""
    out: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            found = render_id(item)
            if found:
                out.append(found)
    return out
