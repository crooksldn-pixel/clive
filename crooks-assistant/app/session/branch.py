"""Branch state: where the conversation is, per branch of it.

The tablet's orb can divide in two (app/routes/branches.py). Each half is a branch: its own
current entity, working set, workflow and cursor, navigation stack, selected tab and scroll
position, its own recent reads and its own pending changes. What they share is only what is
safe to share — the read caches (app/memory), the source clients, the issued-id ledger — and
never a mutable position, a proposal or an approval.

The point of holding this is speed. "Next" is a cursor increment and one read of a member
the Mac already knows the id of; it is not a question for the model. Nothing here is a
permission: the gate reads `Session.issued_ids`, which is not branch state.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

# Two branches at most. The orb divides once; it does not become a window manager.
MAX_BRANCHES = 2
# The five words a half's state can be, and the only five. ACTIVE means the owner can talk to
# it and nothing is running; the other four are what it is doing. There is no percentage here
# and there never will be: nothing on the Mac can compute one honestly, and a bar that guesses
# is a lie drawn to two decimal places.
BRANCH_STATES = ("ACTIVE", "WORKING", "WAITING", "READY", "FAILED")
# What a half is showing, in one word, from the cards it presented. The tablet draws this as
# that half's header. The Phase 3 live test recorded the owner tapping between two halves six
# times in nine seconds looking for the difference, then saying "it just shows two of the same
# thing" — because nothing on either screen said which half it was.
AREA_OF_CARD = {
    "order": "ORDER", "order_list": "ORDERS", "attention": "ORDERS",
    "customer": "CUSTOMER", "customer_list": "CUSTOMERS",
    "email_list": "INBOX", "email_queue": "INBOX", "work_queue": "INBOX",
    "email_thread": "EMAIL", "email_draft": "DRAFT", "email_compose": "DRAFT", "reply_state": "EMAIL",
    "sales_summary": "SALES", "metric_group": "SALES", "trend": "SALES", "comparison": "SALES",
    "ranking": "PRODUCTS", "product": "PRODUCT", "variant_matrix": "PRODUCT", "variant_picker": "PRODUCT",
    "inventory": "STOCK", "working_set": "LIST", "capability": "SYSTEM", "workspace": "BUILDING",
    "batch_action": "BATCH", "batch_result": "BATCH",
}
# And the same from the record the half is on, which is the better evidence when the two
# disagree: the entity is where the branch IS, the cards are what it last drew.
AREA_OF_KIND = {
    "order": "ORDER", "customer": "CUSTOMER", "email_thread": "EMAIL",
    "product": "PRODUCT", "variant": "PRODUCT", "draft": "DRAFT", "set": "LIST",
}


def area_of(ui: list[dict[str, Any]] | None) -> str:
    """The one-word area a screenful of cards is about. The first card that names one wins."""
    for item in ui or []:
        if isinstance(item, dict):
            area = AREA_OF_CARD.get(str(item.get("type") or ""))
            if area:
                return area
    return ""
# Entities, results and actions kept per branch. A tablet screen shows a handful; the rest is
# memory that would go stale before it was read.
MAX_RECENT = 8
MAX_NAV = 12

# What kind of workspace a stop on the trail is. Two of them are not records:
#
#   LIST_KIND     the listing a working set came from — "today's orders", the reply queue.
#                 It has a set_id rather than an entity id, and it cannot be replayed from
#                 the entity cache, because a listing is not a record: there is no
#                 `list_id` in app/memory to read. So its cards travel with the stop.
#   LANDING_KIND  one of the dock's places (Sales, Products) that opens no set at all.
#
# Before these existed, only records were stops, so the Orders list the owner started from
# was never on the trail and no number of Backs could reach it.
LIST_KIND = "list"
LANDING_KIND = "landing"
WORKSPACE_KINDS = (LIST_KIND, LANDING_KIND)
# Cards kept with a workspace stop, so Back to a list redraws the list. Bounded twice: the
# tablet shows a handful, and this is presentation that has already been sent once.
MAX_STOP_UI = 4
# Where a branch goes when the owner asks for the assistant and the branch has never been
# anywhere. The dock's first place; `Branch.landing` names the one it was actually in.
DEFAULT_AREA = "orders"


def new_branch_id() -> str:
    return f"br_{os.urandom(5).hex()}"


@dataclass(slots=True)
class Workflow:
    """A thing being worked through, member by member: a working set and a position in it.

    `operation` is what is being done at each stop ("review", "reply", "check") and is
    presentation only — a workflow never applies anything. Advancing the cursor is what
    "Next" means, and it is arithmetic, not reasoning.
    """

    workflow_id: str
    set_id: str
    kind: str
    # What a person calls this set. The tablet's set chip — the thing on screen that says what
    # "these" currently means — used to read it off a `working_set` CARD, so the chip only
    # changed when a card happened to be drawn. It now comes from here, with the rest of the
    # branch, which is the only copy that is always right.
    label: str = ""
    operation: str = "review"
    cursor: int = 0
    total: int = 0
    started_at: float = field(default_factory=time.time)
    # Members already visited, by ref, so "back" and "next" agree about where they have been.
    visited: list[str] = field(default_factory=list)

    @property
    def position(self) -> int:
        """The cursor as a person counts: one-based, never past the end, and zero before the
        first "Next" has landed on anything (the cursor starts at -1, waiting)."""
        if not self.total or self.cursor < 0:
            return 0
        return min(self.cursor + 1, self.total)

    def at_end(self) -> bool:
        return self.total > 0 and self.cursor >= self.total - 1

    def at_start(self) -> bool:
        return self.cursor <= 0

    def public(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id, "set_id": self.set_id, "kind": self.kind,
            "label": self.label,
            "operation": self.operation, "position": self.position, "total": self.total,
            "at_end": self.at_end(), "at_start": self.at_start(),
        }


@dataclass(slots=True)
class NavEntry:
    """One stop on the branch's back stack: a WORKSPACE, not a render.

    The distinction is the whole of defect D-10. A stop used to be an entity, a tab and a
    scroll depth, so Back put the record back and lost everything else the screen was made
    of — which set "these" meant, where the cursor stood in it, which rows were open, and
    which record this one had been reached from. The owner came back to a screen that looked
    like the one he had left and did not behave like it, four times in twenty-two seconds.

    So a stop holds everything it takes to put the screen back:

        kind/ref/label   the record, or the set a listing found, or a dock area
        tab, scroll      which part of it, and how far down
        set_id …total    the working set and the cursor's place in it AT THIS STOP
        expanded         the rows opened in place
        from_*           the record this workspace was reached FROM — "Customer on #1957"
        ui               the cards, for a stop that no cache can rebuild (a listing)

    The filters are not here and do not need to be: a working set is immutable and carries
    the query that made it (app/analytics/sets.py provenance), so restoring `set_id` restores
    exactly the narrowing the owner was looking at.
    """

    entry_id: str
    kind: str
    ref: str
    label: str
    tab: str = ""
    scroll: int = 0
    set_id: str = ""
    # The cursor, as this stop had it. A member of a set is not the same workspace as the same
    # record opened cold: the position is part of what the owner can see.
    cursor: int = -1
    total: int = 0
    set_kind: str = ""
    set_label: str = ""
    operation: str = "review"
    workflow_id: str = ""
    # Which of the dock's places this workspace belongs to, so Home knows where home is and
    # the dock can light the right icon when Back arrives.
    area: str = ""
    expanded: list[str] = field(default_factory=list)
    # The record open at this stop. The same thing as kind/ref/label for a record stop; for a
    # list stop it is whatever was open when the list was drawn, which is usually nothing.
    entity: dict[str, str] | None = None
    # Where this stop was reached from, and nothing about why: the relation is the pair.
    from_kind: str = ""
    from_ref: str = ""
    from_label: str = ""
    # Cards as presented, for a workspace stop only (see WORKSPACE_KINDS). A record stop keeps
    # none: `commands.replay` rebuilds it from the shared entity cache, which is cheaper and
    # cannot go stale in a way this would hide.
    ui: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    at: float = field(default_factory=time.time)

    @property
    def is_workspace(self) -> bool:
        return self.kind in WORKSPACE_KINDS

    @property
    def position(self) -> int:
        """The cursor as a person counts it, one-based; nought before the first member."""
        if not self.total or self.cursor < 0:
            return 0
        return min(self.cursor + 1, self.total)

    def public(self) -> dict[str, Any]:
        return {"entry_id": self.entry_id, "kind": self.kind, "ref": self.ref, "label": self.label,
                "tab": self.tab, "scroll": self.scroll, "set_id": self.set_id,
                "cursor": self.cursor, "position": self.position, "total": self.total,
                "set_kind": self.set_kind, "set_label": self.set_label, "area": self.area,
                "expanded": list(self.expanded),
                "from": ({"kind": self.from_kind, "ref": self.from_ref, "label": self.from_label}
                         if self.from_ref else None)}


@dataclass(slots=True)
class Branch:
    """One half of the conversation. Created on demand; the first is made with the session."""

    branch_id: str
    session_id: str = ""
    parent_id: str = ""
    # ACTIVE (the owner is talking to it), BACKGROUND (it is working while he is elsewhere),
    # MERGED or CANCELLED (it is over). A background branch never commits a change: see
    # app/actions/engine.py, which refuses a commit whose branch is not the focused one.
    status: str = "ACTIVE"
    label: str = ""
    created_at: float = field(default_factory=time.time)
    # This half's own count of instructions. A turn records it when it starts and a tool
    # call compares (app/providers/max_agent_sdk.py): a later instruction to THIS half means
    # the turn is answering a replaced question and its calls act for nobody — while an
    # instruction to the other half, which also moves the session's epoch, means nothing
    # here. Without it the two halves could not think at once: the right half's question
    # refused every tool call the left half was still making.
    instruction_seq: int = 0
    # A /cancel aimed at this half. Read where the session-wide flag is read; set only by
    # a cancel that names the half, so a cancel on the left never silences the right.
    abandoned: bool = False
    # Turns actually running on this half, counted up when one begins and down when it ends.
    # `state()` reads it, and it is the whole of why WORKING is a fact rather than a leftover:
    # a task dictionary saying WORKING is only a note somebody wrote, and a half whose turn
    # died would have gone on saying "working" for as long as the conversation lasted.
    in_flight: int = 0
    # What this half received when the orb divided, kept so a refusal can say what it has to
    # work with instead of leaving the owner with a dead control (see `holds`).
    inherited: dict[str, Any] | None = None
    # The one-word area this half last drew (AREA_OF_CARD). Presentation, and the header the
    # tablet puts on this half so two halves are never indistinguishable.
    area: str = ""

    # Where the branch is.
    entity: dict[str, str] | None = None          # {"kind","ref","label"}
    set_id: str = ""                               # the working set "these" means here
    workflow: Workflow | None = None
    nav: list[NavEntry] = field(default_factory=list)
    nav_index: int = -1
    # Which tab the screen is on NOW, and which tab each RECORD was left on.
    #
    # D-2, and the difference between the two lines is the whole of it. `tab` alone was the
    # branch's tab, and the tablet handed it to every card that had tabs: the owner tapped
    # Email once, on one customer, early in the live session, and from that moment every
    # customer card on this half opened on Email — including seven cards drawn for seven
    # customers he had never opened. He asked for a customer's orders and history and got an
    # empty inbox, with his orders one tab away on the same card.
    #
    # So `tabs` keeps it per record, keyed by RENDER IDENTITY (`kind:ref` — the same name the
    # patch protocol and web/ui.js address a card by), and `tab` stays as what it always
    # honestly was: where this half's screen is, for the stop on the trail and for the
    # spoken "show me the shipping". Bounded, newest kept.
    tab: str = ""
    tabs: dict[str, str] = field(default_factory=dict)
    scroll: int = 0
    # Which of the dock's places this half is in, and therefore where "back to the assistant"
    # goes. Branch state like every other position: the right half working in the inbox goes
    # home to the inbox while the left half goes home to orders. Empty until the half has
    # actually been somewhere; `home_area` supplies the default.
    landing: str = ""
    # Rows opened in place on the current surface, by ref. Branch state rather than something
    # only the DOM knows, so a Back that returns here returns to the same shape of screen, and
    # a half put aside keeps its own.
    expanded: list[str] = field(default_factory=list)
    # What the next thing said applies to, when the owner tapped a control that expects words.
    # Tapping Rewrite on a draft binds the draft here and starts listening, so "make it shorter
    # and more apologetic" lands on that draft without the owner naming it again. Held on the
    # BRANCH, never on the session: a continuation armed on one half of the orb must not catch
    # a sentence spoken to the other. It expires, because a binding the owner has forgotten
    # about is a sentence applied to the wrong thing.
    voice_context: dict[str, Any] | None = None
    # An email being composed on this half (app/families/compose.py): who it is to, what it
    # is about, the words so far, and the status of each field. Held here and NOWHERE else,
    # because it is the Mac's copy of a change that has not been prepared yet: the tablet
    # posts a compose id and a typed value, and the execution arguments are built from THIS
    # dictionary when the owner's gesture asks for them. A composer is one half's, like every
    # other position — an email started on the left is not what "send it" means on the right.
    compose: dict[str, Any] | None = None
    # A structured workspace being filled on this half (app/families/_workspace.py): the
    # discount code being written, the order being built, the credit being decided. The same
    # thing the composer is and for the same reason — the Mac's copy of a change nobody has
    # proposed yet — and one at a time per half, because the execution arguments are built
    # from THIS dictionary when a gesture asks for them and the owner is looking at one card.
    workspace: dict[str, Any] | None = None

    # What it has seen, most recent first.
    recent_entities: list[dict[str, str]] = field(default_factory=list)
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    recent_actions: list[dict[str, Any]] = field(default_factory=list)

    # Work running for this branch that the owner is not waiting on. Semantic states only:
    # QUEUED, WORKING, WAITING, READY, FAILED — never a percentage nobody can compute,
    # because nothing here can compute one honestly.
    task: dict[str, Any] | None = None

    # What this half last put on the screen: the cards as presented (bounded), the sentence,
    # and the question they answered. Held so that tapping a half SHOWS that half — the Phase
    # 2 live test found that tapping the other half changed who was listening and nothing
    # visible — and so that a reload, or a half put aside that has since finished, can be drawn
    # from the Mac's copy rather than from a browser cache. Presentation data only: it has
    # already been sent to the tablet once, and it stages nothing.
    last_ui: list[dict[str, Any]] = field(default_factory=list)
    last_answer: str = ""
    last_question: str = ""
    last_at: float = 0.0

    def shown(self, ui: list[dict[str, Any]], answer: str, question: str, *, clock=time.time) -> None:
        """The screen this half now has. Cards only (never the context stack, which the
        tablet keeps for itself), at most six, and never an error card standing in for a
        record the branch still holds."""
        kept = [u for u in (ui or []) if isinstance(u, dict) and u.get("type") not in ("context_stack",)]
        if kept or not self.last_ui:
            self.last_ui = kept[:6]
            self.area = area_of(kept) or self.area
        self.last_answer = str(answer or "")[:400]
        self.last_question = str(question or "")[:200]
        self.last_at = clock()
        # A stop that no cache can rebuild keeps its own cards, so Back to the Orders list
        # redraws the Orders list rather than announcing a move over an empty screen. A record
        # stop keeps none: `commands.replay` rebuilds it from the shared entity cache.
        entry = self.here
        if entry is not None and entry.is_workspace and kept:
            entry.ui = kept[:MAX_STOP_UI]
            entry.answer = self.last_answer

    # ------------------------------------------------------------------ work

    def working(self, what: str, *, clock=time.time) -> None:
        """This branch has taken on a piece of work. `what` is a short phrase in the owner's
        words — never a tool name, never the model's reasoning."""
        self.task = {"state": "WORKING", "what": str(what)[:80], "since": clock()}

    def waiting(self, what: str = "", *, clock=time.time) -> None:
        """Working, but on something outside the Mac: a source that has not answered yet."""
        self.task = {"state": "WAITING", "what": str(what or (self.task or {}).get("what") or "")[:80], "since": clock()}

    def ready(self, what: str = "", *, clock=time.time) -> None:
        """There is an answer here whenever the owner wants it. This is what makes the
        background half pulse; it never takes his attention (app/routes/branches.py)."""
        self.task = {"state": "READY", "what": str(what or (self.task or {}).get("what") or "")[:80], "since": clock()}

    def failed(self, why: str, *, clock=time.time) -> None:
        self.task = {"state": "FAILED", "what": str(why)[:80], "since": clock()}

    def idle(self) -> None:
        self.task = None

    def begin_turn(self, what: str, *, clock=time.time) -> None:
        """A turn has started on this half. The counter is what makes WORKING true rather
        than merely written down; `working()` on its own says nothing about whether anything
        is still running."""
        self.in_flight += 1
        self.working(what, clock=clock)

    def end_turn(self) -> None:
        """It has stopped, however it stopped — answered, refused, timed out, abandoned."""
        self.in_flight = max(0, self.in_flight - 1)

    def state(self) -> str:
        """This half, in one of five words (BRANCH_STATES).

        READY and FAILED are outcomes and stand on their own. WORKING and WAITING are claims
        about right now, so they are only said while a turn is actually in flight here: a task
        left saying WORKING by a turn that died reads ACTIVE, which is what it is.
        """
        named = str((self.task or {}).get("state") or "")
        if named in ("READY", "FAILED"):
            return named
        if self.in_flight <= 0:
            return "ACTIVE"
        return "WAITING" if named in ("WAITING", "QUEUED") else "WORKING"

    #: The words the GLASS says for a token that is a STATE rather than a place. ORDERS,
    #: INBOX, SALES and PRODUCTS are the shop's own words and pass through untouched; EMPTY
    #: and WORKSPACE are database states, and the Phase 5 visual pass caught both of them on
    #: screen — a chip reading "EMPTY To go out", and the band above the cards reading
    #: "EMPTY Orders" over a focused empty half. The translation lives HERE, next to the
    #: tokens, because `headline`'s promise is that both ends say the same thing: the tablet
    #: keeps a copy only as the fallback for a Mac older than its own build.
    SAID_ALOUD: ClassVar[dict[str, str]] = {"EMPTY": "Nothing yet", "WORKSPACE": "This half"}

    def headline(self) -> dict[str, str]:
        """What this half IS, in a line the tablet draws on it: "ORDER · #1957", "INBOX · READY".

        Never two indistinguishable halves — this is the difference the owner could not find.
        It is built here, on the Mac, from branch state, so both ends say the same thing and
        the tablet invents none of it.

        Four keys, and the difference between them matters. `area`, `detail` and `state` are
        the MACHINE's: tokens, asserted verbatim across the branch protocol and its tests,
        and unchanged by this pass. `words` and `title` are the GLASS's — the same fact in
        language, so that nothing has to translate a token downstream and get it half right.
        """
        entity = self.entity or {}
        area = AREA_OF_KIND.get(str(entity.get("kind") or ""), "") or self.area
        state = self.state()
        detail = str(entity.get("label") or "").strip()
        if not detail and self.workflow is not None:
            detail = str(self.workflow.label or "").strip()
        if not area:
            area = "WORKSPACE" if (self.last_ui or self.last_answer) else "EMPTY"
        if not detail:
            detail = "nothing yet" if area == "EMPTY" and state == "ACTIVE" else state
        detail = detail[:40]
        # And the same line in language. A state token becomes the sentence a person would
        # say, and it does NOT then also carry a detail: "Nothing yet · nothing yet" is the
        # repetition §26 forbids, and "Nothing yet · Orders" — which is what the band drew —
        # says at once that the half holds nothing and that it is about its parent's set.
        said = self.SAID_ALOUD.get(area)
        words = said if said else (f"{area} · {detail}" if detail else area)
        return {"area": area, "detail": detail, "state": state, "words": words,
                "title": f"{area} · {detail}"}

    def holds(self) -> dict[str, Any]:
        """What this half has to work with, said plainly.

        The forked half in the Phase 3 live session was refused `landing_unavailable` and then
        `not_held`, and neither refusal told the owner what the half DID have or what to do
        next. A refusal he cannot act on is a dead control, so every refusal that can reach a
        divided orb carries this.
        """
        return {
            "entity": dict(self.entity) if self.entity else None,
            "set_id": self.set_id or "",
            "recent": [dict(e) for e in self.recent_entities[:4]],
            "from": self.parent_id or "",
            "state": self.state(),
        }

    # ------------------------------------------------------------- navigation

    @property
    def here(self) -> NavEntry | None:
        """The stop the branch is standing on, if it is standing on one."""
        return self.nav[self.nav_index] if 0 <= self.nav_index < len(self.nav) else None

    @property
    def home_area(self) -> str:
        """Where "back to the assistant" goes on this half. Never a record."""
        return self.landing or DEFAULT_AREA

    def visit(self, kind: str, ref: str, label: str, *, tab: str = "", set_id: str = "",
              area: str = "") -> NavEntry:
        """Go to a RECORD. Truncates any forward history, as a browser does.

        Asking about the record you are already on is not going anywhere, so it does not push a
        stop. Reads land here again and again, so three questions about one order used to
        leave three identical entries on the trail — and Back then
        landed on the same record, on the same tab, and said the same sentence, which is a
        button that visibly does nothing. The owner has no way to tell that from a Back that
        failed.

        Two things happen here that did not before, and both are what Back needs to be worth
        pressing. The stop being LEFT is stamped with the screen as it actually stands — how
        far down, which rows are open, where the cursor is — because those change after a stop
        is pushed and a snapshot taken at push time is a snapshot of the wrong moment. And the
        stop being MADE records the record it was reached from, so a customer opened from
        CROOKS-1957 comes back as the customer on CROOKS-1957.
        """
        current = self.here
        self._stamp()
        if current is not None and current.kind == kind and current.ref == str(ref) and current.tab == tab:
            current.set_id = set_id or self.set_id
            self._bind_cursor(current)
            self.entity = {"kind": kind, "ref": str(ref), "label": str(label)[:80]}
            current.entity = dict(self.entity)
            self.scroll = 0
            current.scroll = 0
            self.remember_entity(kind, ref, label)
            return current
        entry = NavEntry(entry_id=f"nav_{os.urandom(4).hex()}", kind=kind, ref=str(ref),
                         label=str(label)[:80], tab=tab, set_id=set_id or self.set_id,
                         area=area or (current.area if current is not None else ""),
                         entity={"kind": kind, "ref": str(ref), "label": str(label)[:80]})
        if current is not None:
            entry.from_kind, entry.from_ref, entry.from_label = current.kind, current.ref, current.label
        self._bind_cursor(entry)
        self._push(entry)
        self.entity = dict(entry.entity or {})
        self.tab = tab
        if tab:
            # A stop that arrives ON a tab ("show me the shipping on 1912", a Back) belongs to
            # the record it arrived at — never to whatever the branch draws next (D-2).
            self.remember_tab(self.tab_key(kind, str(ref)), tab)
        self.scroll = 0
        self.expanded = []
        self.remember_entity(kind, ref, label)
        return entry

    def enter(self, *, area: str, kind: str = LANDING_KIND, ref: str = "", label: str = "",
              set_id: str = "", set_kind: str = "", set_label: str = "", total: int = 0,
              operation: str = "review", workflow_id: str = "") -> NavEntry:
        """Arrive at a PLACE: a listing, or one of the dock's landings.

        A place is a stop on the trail like a record is, and this is the only way one gets
        there. Before it existed the Orders list the owner started from was not on the trail
        at all — `_open_workflow` set a cursor and nothing else — so no number of Backs could
        return to it, and Home had nowhere to go but the oldest record the branch held.

        Arriving somewhere the branch already is updates that stop rather than pushing
        another: eight Homes in twenty-two seconds must not leave eight stops behind, and a
        re-listing of the same area is the same place with fresher rows. The area, not the set
        id, is the identity — a new read makes a new set every time.
        """
        area = str(area or "")[:24]
        current = self.here
        self._stamp()
        if current is not None and current.is_workspace and current.area == area:
            entry = current
            # A landing arriving where a listing already stands does not erase the listing:
            # the Inbox landing draws the reply queue, and the queue is what the cursor walks.
            if kind != LANDING_KIND or not entry.set_id:
                entry.kind = kind or entry.kind
                entry.ref = str(ref or entry.ref)
                entry.label = str(label or entry.label)[:80]
            # Fresher rows: the cards this stop was showing are no longer what it shows, and
            # `shown()` will stamp the new ones.
            entry.ui = []
        else:
            entry = NavEntry(entry_id=f"nav_{os.urandom(4).hex()}", kind=kind, ref=str(ref),
                             label=str(label)[:80], area=area,
                             entity=dict(self.entity) if self.entity else None)
            if current is not None:
                entry.from_kind, entry.from_ref, entry.from_label = current.kind, current.ref, current.label
            self._push(entry)
        if set_id:
            entry.set_id, entry.set_kind, entry.set_label = str(set_id), str(set_kind), str(set_label)[:80]
            entry.total, entry.cursor, entry.operation = int(total), -1, str(operation)
            entry.workflow_id = str(workflow_id)
        entry.tab, entry.scroll = "", 0
        entry.expanded = []
        self.tab, self.scroll, self.expanded = "", 0, []
        self.landing = area or self.landing
        return entry

    def _push(self, entry: NavEntry) -> None:
        if self.nav_index >= 0:
            del self.nav[self.nav_index + 1 :]
        self.nav.append(entry)
        del self.nav[:-MAX_NAV]
        self.nav_index = len(self.nav) - 1

    def _stamp(self) -> None:
        """Write the screen as it now stands onto the stop being left.

        `mark()` keeps the tab and the scroll up to date as they change; the cursor and the
        opened rows move without anything telling the stack, and they are half of what makes
        one workspace different from another.
        """
        entry = self.here
        if entry is None:
            return
        entry.scroll = self.scroll
        entry.tab = self.tab
        entry.expanded = list(self.expanded)
        # The cursor is stamped on a LISTING as the walk moves it, so returning to the list
        # returns to where the walk had got to. It is NOT stamped on a record: a member's stop
        # is the place that member holds in the set, fixed when it was opened. Stamping it
        # here would have written the cursor's new value onto the stop it had just left —
        # `move_cursor` moves the cursor before the visit that records the arrival — and every
        # stop on the trail would have carried the same position.
        if entry.is_workspace and self.workflow is not None and self.workflow.set_id == entry.set_id:
            entry.cursor, entry.total = self.workflow.cursor, self.workflow.total

    def _bind_cursor(self, entry: NavEntry) -> None:
        """The set and the place in it, as the stop being MADE has them."""
        if self.workflow is None:
            return
        entry.set_id = entry.set_id or self.workflow.set_id
        if entry.set_id != self.workflow.set_id:
            return
        entry.cursor, entry.total = self.workflow.cursor, self.workflow.total
        entry.set_kind, entry.set_label = self.workflow.kind, self.workflow.label
        entry.operation, entry.workflow_id = self.workflow.operation, self.workflow.workflow_id

    def back(self) -> NavEntry | None:
        if self.nav_index <= 0:
            return None
        self._stamp()
        self.nav_index -= 1
        return self._land()

    def forward(self) -> NavEntry | None:
        if self.nav_index < 0 or self.nav_index >= len(self.nav) - 1:
            return None
        self._stamp()
        self.nav_index += 1
        return self._land()

    def _land(self) -> NavEntry:
        """Put the branch back the way this stop had it. Everything the screen is made of.

        What this restores beyond the record is the point: the working set "these" means, the
        cursor's place in it, the part of the record that was showing, how far down it was
        scrolled, and the rows that were open. A Back that restored only the record put the
        owner on a screen that looked right and behaved like a different one.
        """
        entry = self.nav[self.nav_index]
        self.entity = dict(entry.entity) if entry.entity else (
            {"kind": entry.kind, "ref": entry.ref, "label": entry.label} if not entry.is_workspace else None
        )
        self.tab = entry.tab
        self.scroll = entry.scroll
        self.expanded = list(entry.expanded)
        self.set_id = entry.set_id or self.set_id
        if entry.area:
            self.landing = entry.area
        self._restore_cursor(entry)
        return entry

    def _restore_cursor(self, entry: NavEntry) -> None:
        """The cursor as this stop had it, rebuilding the workflow when the branch has since
        walked a different set. A stop that names no set leaves the branch's set alone: the
        screen it describes was drawn before "these" meant anything."""
        if not entry.set_id:
            return
        if self.workflow is not None and self.workflow.set_id == entry.set_id:
            self.workflow.cursor = entry.cursor
            if entry.total:
                self.workflow.total = entry.total
            return
        self.workflow = Workflow(
            workflow_id=entry.workflow_id or f"wf_{os.urandom(4).hex()}", set_id=entry.set_id,
            kind=entry.set_kind or "orders", label=entry.set_label, operation=entry.operation,
            cursor=entry.cursor, total=entry.total,
        )

    def where(self) -> dict[str, Any]:
        """Where this half is, as the tablet needs it: the stop it stands on, plus what the
        branch holds when it does not stand on one yet.

        Named `where` rather than `workspace` because `workspace` is already this half's
        half-written discount or order (above) — a different thing entirely."""
        entry = self.here
        if entry is not None:
            return {**entry.public(), "entity": dict(self.entity) if self.entity else None}
        return {"entry_id": "", "kind": "", "ref": "", "label": "", "tab": self.tab or "",
                "scroll": self.scroll, "set_id": self.set_id, "cursor": -1, "position": 0,
                "total": 0, "set_kind": "", "set_label": "", "area": self.landing,
                "expanded": list(self.expanded), "from": None,
                "entity": dict(self.entity) if self.entity else None}

    # How many records' tabs one half remembers. A tab is two words about a record the owner
    # has looked at; the oldest goes when the room runs out.
    MAX_TABS = 24

    def tab_key(self, kind: str, ref: str) -> str:
        """A record's name in the tab map: the render identity the glass draws it by."""
        kind, ref = str(kind or "").strip(), str(ref or "").strip()
        if not kind:
            return ""
        return f"{kind}:{ref}" if ref else kind

    def tab_for(self, kind: str, ref: str = "") -> str:
        """The tab THIS record was left on, or nothing. Never another record's tab (D-2).

        Takes a kind and a reference, or a whole render identity as the first argument —
        whichever the caller has, since the tablet works in identities and the Mac's own
        navigation works in kind-and-ref.
        """
        key = self.tab_key(kind, ref) if ref else str(kind or "").strip()
        return str(self.tabs.get(key) or "")

    def remember_tab(self, key: str, tab: str) -> None:
        """One record, one tab, most recent first."""
        key, tab = str(key or "").strip()[:160], str(tab or "").strip()[:40]
        if not key or not tab:
            return
        self.tabs.pop(key, None)
        self.tabs[key] = tab
        while len(self.tabs) > self.MAX_TABS:
            self.tabs.pop(next(iter(self.tabs)))

    def mark(self, *, tab: str | None = None, scroll: int | None = None,
             expanded: list[str] | None = None, of: str = "") -> None:
        """The screen moved. Kept on the current stack entry so going back restores it.

        `of` is the RECORD a tab belongs to, as a render identity ("customer:cus_1"). The
        tablet sends it with the tap; when nothing says, the tab belongs to the record this
        half is standing on — which is what the spoken "show me the shipping" means, and what
        `surface.tab` passes through. It is never applied to a record nobody named.
        """
        if tab is not None:
            self.tab = str(tab)[:40]
            entity = self.entity or {}
            self.remember_tab(str(of or "") or self.tab_key(str(entity.get("kind") or ""), str(entity.get("ref") or "")), self.tab)
        if scroll is not None:
            self.scroll = max(0, int(scroll))
        if expanded is not None:
            self.expanded = [str(x)[:200] for x in expanded][-12:]
        entry = self.here
        if entry is not None:
            if tab is not None:
                entry.tab = self.tab
            if scroll is not None:
                entry.scroll = self.scroll
            if expanded is not None:
                entry.expanded = list(self.expanded)

    # ---------------------------------------------------------------- memory

    # How long a tapped control waits for the words that go with it. Long enough to think of
    # the sentence, short enough that a tap made and abandoned does not catch the next question.
    VOICE_CONTEXT_TTL_S = 120.0

    def bind_voice(self, family: str, *, kind: str = "", ref: str = "", label: str = "",
                   prompt: str = "", phrase: str = "", clock=time.time) -> dict[str, Any]:
        """Arm this branch for a spoken continuation of a tapped control.

        `prompt` is what the screen should say it is waiting for — "Add a note". It is stored
        rather than looked up again so that `public()` can hand it to the tablet on every
        reply, including one that follows a reload, without importing the command table.
        """
        self.voice_context = {
            "family": family, "kind": kind, "ref": ref, "label": label, "prompt": prompt, "phrase": phrase,
            "branch_id": self.branch_id, "at": clock(),
            "expires_at": clock() + self.VOICE_CONTEXT_TTL_S,
        }
        return dict(self.voice_context)

    def voice_target(self, *, clock=time.time) -> dict[str, Any] | None:
        """What the next sentence applies to, or nothing.

        Checks the branch it was armed on as well as the clock: a context that somehow reached
        another half is not this half's, and is ignored rather than obeyed.
        """
        held = self.voice_context
        if not held:
            return None
        if held.get("branch_id") != self.branch_id or clock() >= float(held.get("expires_at") or 0):
            self.voice_context = None
            return None
        return dict(held)

    def release_voice(self) -> None:
        """One sentence, one binding. Cleared as soon as it has been used or abandoned."""
        self.voice_context = None

    def remember_entity(self, kind: str, ref: str, label: str) -> None:
        if not (kind and ref):
            return
        ref = str(ref)
        self.recent_entities = [e for e in self.recent_entities if not (e["kind"] == kind and e["ref"] == ref)]
        self.recent_entities.insert(0, {"kind": kind, "ref": ref, "label": str(label or "")[:80]})
        del self.recent_entities[MAX_RECENT:]

    def remember_result(self, tool: str, *, summary: str, ref: str = "", ms: float = 0.0, cached: bool = False) -> None:
        """A compact note of a read, not the read. What goes to the model later is this line;
        the whole result stays on the Mac (app/memory)."""
        self.recent_results.insert(0, {"tool": tool, "summary": str(summary)[:200], "ref": str(ref)[:80], "ms": round(ms, 1), "cached": bool(cached), "at": time.time()})
        del self.recent_results[MAX_RECENT:]

    def remember_action(self, proposal_id: str, operation: str, status: str, *, spoken: str = "") -> None:
        self.recent_actions = [a for a in self.recent_actions if a["proposal_id"] != proposal_id]
        self.recent_actions.insert(0, {"proposal_id": proposal_id, "operation": operation, "status": status, "spoken": str(spoken)[:200], "at": time.time()})
        del self.recent_actions[MAX_RECENT:]

    # ----------------------------------------------------------------- shape

    def public(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id, "parent_id": self.parent_id or None, "status": self.status,
            # `status` is where the half lives (ACTIVE, BACKGROUND, MERGED, CANCELLED);
            # `state` is what it is doing, in one of five words, and it is what the chip says.
            "state": self.state(),
            # The line drawn ON this half, so tapping between two halves can never again show
            # the owner two screens he cannot tell apart.
            "headline": self.headline(),
            "label": self.label, "entity": self.entity, "set_id": self.set_id or None,
            "workflow": self.workflow.public() if self.workflow else None,
            "tab": self.tab or None, "scroll": self.scroll, "expanded": list(self.expanded),
            # Which tab each RECORD was left on, by render identity, so the tablet can put a
            # card back on ITS tab after a reload or a switch of halves — and can put a card
            # for a record he has never opened on the tab the task implies instead (D-2).
            "tabs": dict(self.tabs) or None,
            # What the tablet should show as the target of the next thing said, when a tapped
            # control is waiting for words.
            # The prompt and the deadline travel with it: the tablet draws a band naming what
            # it is listening for, and the band was previously drawn from the tap alone — so a
            # binding made by voice, or one surviving a reload, left the screen silent about it.
            "listening_for": ({"family": self.voice_context["family"], "label": self.voice_context.get("label", ""),
                               "prompt": self.voice_context.get("prompt", ""), "phrase": self.voice_context.get("phrase", ""),
                               "expires_at": self.voice_context.get("expires_at")}
                              if self.voice_target() else None),
            # The composer, in five fields: enough for the tablet to know one is open and
            # what it is to, never the body (that is on the card the Mac drew, and a branch
            # summary goes out with every reply).
            "compose": ({"compose_id": str(self.compose.get("compose_id") or ""),
                         "kind": str(self.compose.get("kind") or ""),
                         "to": str(self.compose.get("to") or "")[:254],
                         "subject": str(self.compose.get("subject") or "")[:120],
                         "thread_id": str(self.compose.get("thread_id") or "")}
                        if isinstance(self.compose, dict) and self.compose.get("compose_id") else None),
            # What this half is BUILDING, in two fields: which workspace and what kind of
            # thing it makes. Deliberately not its values — `has_workspace` below is about
            # whether there is a screen to redraw, and this is about whether a discount, an
            # order or a credit is half-written on this half; the values are on the card the
            # Mac drew, and a branch summary goes out with every reply.
            "building": ({"workspace_id": str(self.workspace.get("workspace_id") or ""),
                          "kind": str(self.workspace.get("kind") or "")}
                         if isinstance(self.workspace, dict) and self.workspace.get("workspace_id") else None),
            # Whether there is anywhere to go, and where. `can_back` is the trail's own answer
            # and the only one the Back chip may be drawn from: while the tablet decided for
            # itself — a local render cache, or "the list cursor is not at the start" — Back
            # meant two different things depending on which of them happened to be true.
            "can_back": self.nav_index > 0, "can_forward": 0 <= self.nav_index < len(self.nav) - 1,
            "depth": max(0, self.nav_index), "recent": list(self.recent_entities[:4]),
            # Which of the dock's places this half is in, and the one Home goes back to. The
            # dock lights the first; the Assistant chip is the second, and neither is a guess
            # the tablet has to make from the card types on screen.
            "area": (self.here.area if self.here is not None else self.landing) or None,
            "landing": self.home_area,
            "task": dict(self.task) if self.task else None,
            # Whether there is a screen to show for this half, and what it answered. The cards
            # themselves come through `branch.show`, on request, not with every reply.
            "has_workspace": bool(self.last_ui or self.last_answer),
            "last_question": self.last_question, "last_at": self.last_at or None,
        }


def fork_from(parent: Branch, *, label: str = "") -> Branch:
    """The orb divides. One function, so what a half inherits is one contract with one test.

    The child inherits what its parent HOLDS — the record it is on, the working set, the names
    it has already resolved, the trail of what it has looked at — and NOTHING of what its
    parent is SHOWING. That division is the whole of D-3. Cloning the parent's screen is what
    produced two identical halves; withholding what the parent held is what made `open.area`
    and `open.entity` refuse the clone with reasons its owner could not act on. So: context
    yes, presentation no, and the child says plainly that it holds nothing yet.

    Nothing that could be APPLIED crosses: no proposal, no composer, no half-written workspace,
    no armed voice binding, no task. A change belongs to the half it was asked for in.
    """
    child = Branch(
        branch_id=new_branch_id(), session_id=parent.session_id, parent_id=parent.branch_id,
        label=str(label or "").strip()[:40] or "second",
        entity=dict(parent.entity) if parent.entity else None,
        set_id=parent.set_id, tab=parent.tab,
        # A tab the owner chose on a record is context, like the record itself: it crosses,
        # and from here the two halves move apart.
        tabs=dict(parent.tabs),
        # Where the new half's "back to the assistant" goes. The half starts where the old one
        # is, and the PLACE it is in is part of what it holds; without this a half forked out
        # of the inbox went home to orders. A value, not the stack: its own one-stop trail is
        # built at the end of this function and the two halves never share one.
        landing=parent.landing,
    )
    if parent.workflow is not None:
        # The same set at the same place; advancing one cursor does not move the other.
        from dataclasses import replace

        child.workflow = replace(parent.workflow, workflow_id=f"{parent.workflow.workflow_id}b",
                                 visited=list(parent.workflow.visited))
    # What its parent had already seen. References, not permissions — the gate still reads
    # `Session.issued_ids` — and exactly what the clone never received in the live session.
    child.recent_entities = [dict(e) for e in parent.recent_entities[:MAX_RECENT]]
    child.inherited = {
        "from": parent.branch_id,
        "entity": dict(parent.entity) if parent.entity else None,
        "set_id": parent.set_id or "",
        "area": parent.headline()["area"],
    }
    if parent.entity:
        # Its own one-stop trail, so Back and Home have a floor of their own rather than
        # walking a stack that belongs to the other half.
        child.visit(parent.entity["kind"], parent.entity["ref"], parent.entity["label"], tab=parent.tab)
    return child

