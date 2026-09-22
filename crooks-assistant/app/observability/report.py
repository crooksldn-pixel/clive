"""The report: an hour with the tablet, read back from the timeline.

`reconstruct` turns the JSONL into turns, tool calls and proposals joined by their ids;
`render` writes the fourteen sections as Markdown. Everything in it is counted or matched —
nothing is scored by a model. The rules that classify a failure are the ones written here,
and the report names them, so a reader can disagree with a line and see why it was drawn.

Two things it does not do, learned from the report of the September live hour, which was
useful and wrong in five places:

It does not read the owner's words with rules of its own. Whether a change was asked for is
the ROUTER's answer, taken off the turn's `lane` event, because the router is what decided the
lane and a second reading that disagrees with it is a second bug
(`app/observability/semantics.py`). And what to DO about a change asked for is the capability
table's answer (`app/capabilities/families.py`): no family is a family to build, a family that
is not READY is a scope to grant, and a READY one declined anyway is the assistant being wrong
about itself. Reporting all three as one class is how a capability that has since been built
gets reported as still open.

It does not read a relationship off what a tool returned. Backend data existing is not a
visible relationship existing, so a relation is read off the card's own `relations` — the
tappable link targets inside it, which `web/telemetry.js` reports — and section 9 asks the
two questions separately."""

from __future__ import annotations

import difflib
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.observability import claims, visible
from app.observability.pad import APPLIANCE_KINDS
from app.observability.timeline import read_events

# The classes this file tests on the speech, tool and contract paths, named once so the
# vocabulary below can be assembled without repeating any of them.
_SPOKEN_CLASSES = (
    "GESTURE_COLLISION", "STT_ERROR", "TIMEOUT", "PERMISSION_ERROR", "MISSING_CAPABILITY",
    "FALSE_UNSUPPORTED", "TOOL_ERROR", "VERIFICATION_ERROR", "FALSE_SUCCESS",
    "UNFULFILLED_ACTION", "ACTION_MISMATCH", "UI_INTENT_UNFULFILLED", "UI_RELATION_MISSING",
    "DATA_FIELD_UNAVAILABLE", "INTENT_DIVERGENCE", "PARTIAL_COVERAGE", "TOOL_SELECTION_ERROR",
    "UI_RENDER_ERROR", "UI_NAVIGATION_PROBLEM", "CONTEXT_INCOMPLETE", "INTENT_ERROR",
    "UNKNOWN", "OWNER_FEEDBACK",
)
# The classes a failed or partial turn is filed under, in the order they are tested.
CLASSES = (
    # GESTURE_COLLISION is tested BEFORE STT_ERROR and displaces it: a second finger on the
    # orb ends the recording, and the recogniser being handed no speech is the consequence,
    # not the fault. Six turns of the live session were filed as the recogniser's.
    "GESTURE_COLLISION", "STT_ERROR", "TIMEOUT", "PERMISSION_ERROR", "MISSING_CAPABILITY", "FALSE_UNSUPPORTED", "TOOL_ERROR", "VERIFICATION_ERROR",
    # What the request was FOR, held against what the turn did (app/observability/contract.py).
    "FALSE_SUCCESS", "UNFULFILLED_ACTION", "ACTION_MISMATCH", "UI_INTENT_UNFULFILLED", "UI_RELATION_MISSING",
    "DATA_FIELD_UNAVAILABLE", "INTENT_DIVERGENCE", "PARTIAL_COVERAGE",
    "TOOL_SELECTION_ERROR", "UI_RENDER_ERROR", "UI_NAVIGATION_PROBLEM", "CONTEXT_INCOMPLETE", "INTENT_ERROR", "UNKNOWN",
    # §20. Not a defect: the one thing that worked all evening. Held in the vocabulary because
    # it must be able to WIN over a generic mutation match — three of the eight owner-feedback
    # records of the 11 September session were filed UNFULFILLED_ACTION at severity 5/5, and
    # the report's third-highest priority was the feature that was working.
    "OWNER_FEEDBACK",
    # What the OWNER could see (app/observability/visible.py). Tested last and reported first:
    # these are the classes that make a turn the backend called successful a failure. Deduped
    # against the names above: GESTURE_COLLISION is tested on the speech path AND filed by the
    # touch classifier, and a vocabulary that held it twice would print it twice.
    *(name for name in visible.CLASSES if name not in _SPOKEN_CLASSES),
)
# Classes that are not defects. They describe what the system did RIGHT, so they never make a
# turn partial or failed, and they never take the `visible` column.
NON_DEFECT = frozenset({"OWNER_FEEDBACK"})
SEVERITY = {
    "FALSE_SUCCESS": 6, "ACTION_MISMATCH": 6,
    "VERIFICATION_ERROR": 5, "UNFULFILLED_ACTION": 5,
    "TOOL_ERROR": 4, "TIMEOUT": 4, "PERMISSION_ERROR": 4, "UI_RENDER_ERROR": 4, "FALSE_UNSUPPORTED": 4,
    "GESTURE_COLLISION": 4, "UI_RELATION_MISSING": 4,
    "UI_INTENT_UNFULFILLED": 3, "DATA_FIELD_UNAVAILABLE": 3, "INTENT_DIVERGENCE": 3, "PARTIAL_COVERAGE": 2,
    "STT_ERROR": 3, "MISSING_CAPABILITY": 3, "UNKNOWN": 3,
    "TOOL_SELECTION_ERROR": 2, "CONTEXT_INCOMPLETE": 2, "INTENT_ERROR": 2, "UI_NAVIGATION_PROBLEM": 2,
    "OWNER_FEEDBACK": 0,
    **visible.SEVERITY,
}
COMPONENT = {
    "GESTURE_COLLISION": "the tablet's touch handling (web/app.js): a second finger ended the recording before the recogniser saw any speech",
    "UI_RELATION_MISSING": "the surface (app/presentation.py, web/ui.js): the relation was in the data and not on the card",
    "STT_ERROR": "speech (Scribe / whisper.cpp, app/speech)", "TIMEOUT": "the turn's budget (provider or tool timeouts)",
    "PERMISSION_ERROR": "the write boundary (CROOKS_WRITES_ENABLED, allow-list, scopes, Tailscale identity)",
    "MISSING_CAPABILITY": "the tool registry (app/tools)", "TOOL_ERROR": "the Shopify / Gmail clients (app/clients, app/tools)",
    "FALSE_UNSUPPORTED": "the model's use of the read layer and the batch tools (system prompt, commerce_capabilities)",
    "FALSE_SUCCESS": "the action engine and the prompt: a change reported as made that was never staged (app/actions, system prompt)",
    "UNFULFILLED_ACTION": "the write tools: a change asked for that nothing staged and nothing refused (app/tools)",
    "ACTION_MISMATCH": "the model's tool choice: a different change staged from the one asked for (system prompt, tool descriptions)",
    "UI_INTENT_UNFULFILLED": "the controlled UI (app/presentation.py, web/ui.js): the screen could carry what was asked for",
    "DATA_FIELD_UNAVAILABLE": "the read models (app/context, app/tools): a field said to be missing that a tool returns",
    "INTENT_DIVERGENCE": "the prompt: the answer addressed something the request did not ask about",
    "PARTIAL_COVERAGE": "the read that reported a subset without the answer saying so",
    "VERIFICATION_ERROR": "the action engine's proof (app/actions/engine.py)", "TOOL_SELECTION_ERROR": "the model's tool use (system prompt, tool descriptions)",
    "UI_RENDER_ERROR": "the tablet renderer (web/ui.js, app/presentation.py)", "UI_NAVIGATION_PROBLEM": "the tablet's screens (web/app.js)",
    "CONTEXT_INCOMPLETE": "context hydration (app/context/order.py, /context route)", "INTENT_ERROR": "the model's reading of the request (system prompt, normaliser)",
    "UNKNOWN": "unclassified — read the turn's events",
    "OWNER_FEEDBACK": "owner feedback (app/observability/feedback.py, app/families/owner_feedback.py): working, and the most valuable evidence in the session",
    **visible.COMPONENT,
}
PERMISSION_CODES = frozenset({
    "writes_disabled", "allow_list_missing", "scope_missing", "gmail_scope_missing", "not_authorised", "not_authorised_local", "identity_unverified", "wrong_session",
})
# What a turn is about, from its tools first and its words second. Higher entries win.
CLUSTERS = (
    ("actions", (), ()),
    ("analytics", ("commerce_", "inventory_query", "email_query"), ("best seller", "sold most", "by size", "by colour", "compare", "average order", "days of cover", "run out", "older than", "who have emailed")),
    ("email", ("gmail_",), ("email", "inbox", "reply", "draft")),
    ("sales", ("shopify_sales_summary",), ("sales", "revenue", "takings", "how much did we")),
    ("inventory", ("shopify_inventory",), ("stock", "inventory", "how many left")),
    ("products", ("shopify_product_info",), ("inseam", "made of", "fabric", "measurements")),
    ("customers", ("shopify_find_customer", "shopify_customer_history"), ("customer", "bought before", "spent")),
    ("orders", ("shopify_find_order", "shopify_order_detail", "shopify_list_orders"), ("order", "shipped", "tracking", "delivery")),
)
# The rail's chips, by the change each puts into the owner's mouth.
RAIL_BY_OPERATION = {
    "order_note_append": "note", "order_cancel": "cancel", "refund_create": "refund", "order_shipping_address_set": "address",
    "fulfillment_create": "fulfil", "gmail_draft_new": "email",
}
# Words the assistant uses when it declines: a deterministic signal, not a judgement. Held
# with the map of what the Mac composes (app/observability/claims.py).
CANNOT_RE = claims.CANNOT_RE
CLARIFY_RE = re.compile(r"\b(which (?:one|order|customer|product)|do you mean|could you (?:say|tell me)|can you (?:say|tell me)|which do you)\b", re.I)
OFFER_GESTURE_RE = re.compile(r"\b(tap|hold|swipe|drag)\b.{0,40}\b(card|to apply|to send)\b|\bthe card\b", re.I)
# The change a request names, for "the assistant said it cannot, but a tool exists".
CAPABILITY_WORDS = {
    "refund": "shopify_refund_create", "cancel": "shopify_order_cancel", "address": "shopify_order_shipping_address_set",
    "note": "shopify_order_note_append", "tag": "shopify_order_tags_add", "ship": "shopify_order_fulfil", "fulfil": "shopify_order_fulfil",
    "tracking": "shopify_fulfillment_tracking_set", "stock": "shopify_inventory_adjust", "email": "gmail_draft_new", "reply": "gmail_draft_reply",
    "archive": "gmail_thread_archive",
}
# ------------------------------------------------------------------------- the ranking
#
# §21. The 11 September report ranked its improvement candidates by `severity × occurrences`
# and printed the top twelve. The winner was "A value had to be exact and a voice could not
# make it so" at 2 × 62 = 124 — a severity-2 guess multiplied by sixty-two rows of the same
# swallowed tap. A raw count is not urgency: the sixty-third occurrence of one defect does not
# make it worse than a defect that tells the owner a false thing about his own business.
#
# So the weight is `severity × min(sites, RANK_CAP) × confidence`, where
#   * `sites` is the number of DISTINCT TURNS a class occurred in — not the number of events,
#     because one burst of twenty-six taps is one defect;
#   * `RANK_CAP` bounds how far frequency can carry a finding, so severity decides between a
#     P0 seen four times and a P3 seen forty;
#   * `confidence` is 1.0 when the evidence names the component outright and 0.6 when the class
#     was inferred, so an inference can never outrank a certainty of the same severity.
# Every row carries the three numbers it was ranked on, so a reader can disagree with the order
# and see exactly what produced it.
RANK_CAP = 8
INFERRED_CONFIDENCE = 0.6
# Classes whose evidence is a reading of shape rather than a record of the thing itself. Named
# here rather than guessed: each is a class this file infers from counts and timings.
INFERRED_CLASSES = frozenset({
    "CONTROL_TAP_MISROUTED_TO_VOICE", "REAL_SHORT_VOICE_RECORDING", "INTENT_DIVERGENCE",
    "PARTIAL_COVERAGE", "UNKNOWN", "SUMMARY_ANSWERED_WITH_PROFILES",
})


def rank(severity: float, sites: int, *, inferred: bool = False) -> float:
    """What engineering should do first, as one number and three inputs."""
    confidence = INFERRED_CONFIDENCE if inferred else 1.0
    return round(float(severity) * min(int(sites), RANK_CAP) * confidence, 2)


# How many findings of ONE class the evidence table prints. §21: a report in which one class
# can take sixty-two rows is a report that buries the other nine, whatever the counts say.
EVIDENCE_PER_CLASS = 4
ABANDON_S = 3.0        # a screen left this soon after it was rendered was not what was wanted
SLOW_MS = {"stt": 3000.0, "claude": 8000.0, "total": 12000.0, "tts_first_byte": 2000.0, "context": 4000.0,
           # Section 25's two numbers, kept apart: waiting for a sentence about facts already
           # read is a different fault from the reads themselves being slow, and a report that
           # cannot tell them apart sends the engineer to the wrong file.
           "prose_wait": 6000.0, "facts": 4000.0}
# How long before a failed recording a touch on the orb still explains it. A second finger
# lands, the recorder stops, `turn_started` follows: the gesture is on the timeline BEFORE the
# turn it ruined, and often under the previous turn's id, so this is matched by clock and not
# by correlation id.
GESTURE_WINDOW_S = 6.0
# Card types that are an email surface. An email surface drawn with no order on it, in a turn
# whose own data held one, is the P0 the live session's report called "correlation missing:
# never" — the correlation existed and the screen did not carry it.
EMAIL_CARDS = frozenset({"email", "email_list", "email_thread", "thread", "email_draft", "email_queue"})
# What a card says about the relations it drew: `relations` on a render's card is the set of
# `data-kind` values of the tappable link targets inside it (web/telemetry.js). An email card
# whose relations do not include "order" did not show the order, whatever the tools returned.
RELATION_ORDER = "order"
# How alike two consecutive requests must be to count as the same one said again.
REPHRASE_RATIO = 0.62


# ----------------------------------------------------------------------- the model


@dataclass
class ToolRecord:
    tool_call_id: str
    tool: str
    turn_id: str
    requested_at: float = 0.0
    finished_at: float = 0.0
    args: dict[str, Any] = field(default_factory=dict)
    tier: str = ""
    disposition: str = ""
    outcome: str = ""            # ok | staged | refused | not_yet | error | exception | unprepared | (empty: never finished)
    ok: bool | None = None
    error: str = ""
    ms: float | None = None
    result: dict[str, Any] | None = None
    proposal_id: str = ""
    missing_capability: str = ""

    @property
    def service(self) -> str:
        if self.tool.startswith("shopify_"):
            return "shopify"
        if self.tool.startswith("gmail_"):
            return "gmail"
        return "other"


@dataclass
class ProposalRecord:
    proposal_id: str
    turn_id: str = ""
    session_id: str = ""
    operation: str = ""
    tool: str = ""
    risk: str = ""
    interaction: str = ""
    reversible: bool | None = None
    entity_kind: str = ""
    entity_label: str = ""
    undo_of: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)   # the ledger's, in order
    refusals: list[dict[str, Any]] = field(default_factory=list)  # arm/commit refused before the engine
    commits: list[dict[str, Any]] = field(default_factory=list)   # action_commit (the route's outcome)
    tablet: list[dict[str, Any]] = field(default_factory=list)    # gestures, arms, commits, renders naming it

    def _first(self, event: str) -> dict[str, Any] | None:
        return next((e for e in self.events if e.get("event") == event), None)

    @property
    def staged_at(self) -> float | None:
        e = self._first("PROPOSED")
        return e.get("ts") if e else None

    @property
    def delivered(self) -> bool:
        return self._first("DELIVERED") is not None

    @property
    def armed(self) -> bool:
        return self._first("ARMED") is not None

    @property
    def committed(self) -> bool:
        return self._first("EXECUTING") is not None

    @property
    def final(self) -> dict[str, Any] | None:
        terminal = [e for e in self.events if e.get("status") in ("VERIFIED", "UNVERIFIED", "FAILED", "STALE", "EXPIRED", "REVOKED")]
        return terminal[-1] if terminal else None

    @property
    def status(self) -> str:
        final = self.final
        if final is not None:
            return str(final.get("status") or "")
        if self.committed:
            return "EXECUTING"
        return "PENDING"

    @property
    def code(self) -> str:
        final = self.final
        return str(final.get("code") or "") if final else ""

    @property
    def verified(self) -> bool | None:
        final = self.final
        return final.get("verified") if final else None

    @property
    def reason(self) -> str:
        final = self.final
        return str(final.get("reason") or final.get("detail") or "") if final else ""

    @property
    def latency_ms(self) -> float | None:
        if self.commits:
            ms = self.commits[-1].get("ms")
            if isinstance(ms, (int, float)):
                return float(ms)
        e = self._first("EXECUTED")
        return float(e["ms"]) if e and isinstance(e.get("ms"), (int, float)) else None


@dataclass
class Turn:
    turn_id: str
    session_id: str = ""
    seq: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    input: str = ""
    focus: dict[str, Any] | None = None
    waiting: list[str] = field(default_factory=list)
    stt: dict[str, Any] | None = None
    prefetch: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    # Which lane answered (app/fastpath): FAST is the Mac's own procedure with no model on
    # the critical path, NORMAL is Claude, DEEP is work that outlives one answer.
    lane: dict[str, Any] | None = None
    fast: dict[str, Any] | None = None
    read_plans: list[dict[str, Any]] = field(default_factory=list)
    performance: dict[str, Any] | None = None
    finished: dict[str, Any] | None = None
    tools: list[ToolRecord] = field(default_factory=list)
    proposals: list[ProposalRecord] = field(default_factory=list)
    hydrations: list[dict[str, Any]] = field(default_factory=list)
    context_requests: list[dict[str, Any]] = field(default_factory=list)
    tts: list[dict[str, Any]] = field(default_factory=list)
    tablet: list[dict[str, Any]] = field(default_factory=list)
    # The read layer's own bookkeeping: working sets made, cross-source reads, rejected
    # queries, and the turn-time claim signal (app/observability/claims.py).
    sets: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    batches: list[dict[str, Any]] = field(default_factory=list)
    submitted: dict[str, Any] | None = None   # the tablet's turn_submitted, paired by order
    # The Mac's own controls: a semantic command the tablet posted (`command`), a change a
    # command prepared (`command_stage`), a row action, and the branch moves. Twenty-seven of
    # these went unread in the live session, so a report that was about a tablet said nothing
    # about what was tapped on it.
    commands: list[dict[str, Any]] = field(default_factory=list)
    branch_events: list[dict[str, Any]] = field(default_factory=list)
    # What the request was for (app/observability/contract.py), set by the classifier.
    contract: str = "READ_INTENT"
    classes: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    outcome: str = "successful"
    cluster: str = "other"
    # The request as the ROUTER read it (app/observability/semantics.py). Set by the
    # classifier; `None` on a turn with nothing said.
    verdict: Any = None
    # The two outcomes (§17, app/observability/visible.py). `outcome` above is the report's
    # old single verdict and stays what it was; these are what the SERVER did and what the
    # OWNER could see, and `experience` is the verdict the two produce together. A turn is not
    # successful because the backend verified.
    backend: str = ""
    visible: str = ""
    experience: str = ""
    predictions: list[dict[str, Any]] = field(default_factory=list)
    anticipations: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)

    # ---- what was said
    @property
    def raw_text(self) -> str:
        if self.stt and self.stt.get("raw_text"):
            return str(self.stt["raw_text"])
        return self.question

    @property
    def question(self) -> str:
        if self.finished and self.finished.get("question"):
            return str(self.finished["question"])
        if self.stt and self.stt.get("text"):
            return str(self.stt["text"])
        return ""

    @property
    def answer(self) -> str:
        if self.finished and self.finished.get("answer"):
            return str(self.finished["answer"])
        if self.model and self.model.get("answer"):
            return str(self.model["answer"])
        return ""

    @property
    def error_kind(self) -> str:
        return str((self.finished or {}).get("error_kind") or (self.model or {}).get("error_kind") or "")

    @property
    def ui(self) -> list[str]:
        return [str(x) for x in ((self.finished or {}).get("ui") or [])]

    @property
    def ui_entities(self) -> list[dict[str, Any]]:
        return [x for x in ((self.finished or {}).get("ui_entities") or []) if isinstance(x, dict)]

    def tablet_events(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.tablet if e.get("kind") == f"tablet_{kind}"]

    @property
    def render(self) -> dict[str, Any] | None:
        renders = self.tablet_events("render")
        return renders[0] if renders else None

    # ---- where the time went
    def latency(self, part: str) -> float | None:
        timings = (self.finished or {}).get("timings") or {}
        if part == "audio":
            return float(self.stt["audio_s"]) * 1000 if self.stt and isinstance(self.stt.get("audio_s"), (int, float)) else None
        if part == "stt":
            t = (self.stt or {}).get("timings") or {}
            for key in ("transcribe", "stt", "scribe", "whisper"):
                if isinstance(t.get(key), (int, float)):
                    return float(t[key])
            return float(timings["transcribe"]) if isinstance(timings.get("transcribe"), (int, float)) else None
        if part == "claude":
            return float(self.model["ms"]) if self.model and isinstance(self.model.get("ms"), (int, float)) else None
        if part in ("shopify", "gmail"):
            values = [t.ms for t in self.tools if t.service == part and isinstance(t.ms, (int, float))]
            return float(sum(values)) if values else None
        if part == "context":
            values = [h.get("ms") for h in self.hydrations if isinstance(h.get("ms"), (int, float))]
            return float(max(values)) if values else None
        if part == "tts_first_byte":
            values = [t.get("ms_first_byte") for t in self.tts if isinstance(t.get("ms_first_byte"), (int, float))]
            if values:
                return float(values[0])
            speaks = [e.get("ms") for e in self.tablet_events("speak") if isinstance(e.get("ms"), (int, float))]
            return float(speaks[0]) if speaks else None
        if part == "total":
            return float(self.finished["ms"]) if self.finished and isinstance(self.finished.get("ms"), (int, float)) else None
        if part == "round_trip":
            responses = [e.get("ms") for e in self.tablet_events("turn_response") if isinstance(e.get("ms"), (int, float))]
            return float(responses[0]) if responses else None
        if part in ("facts", "workspace", "prose_wait"):
            # From the turn's own `turn_performance`, not derived here: `facts_ms` is when the
            # Mac HELD the data, `workspace_ms` when the cards existed, `prose_wait_ms` what
            # was waited after the facts were in hand (app/routes/turn.py::_performance). With
            # the three on the timeline, "the model was slow" and "the reads were slow" are two
            # rows in the report rather than one guess.
            value = (self.performance or {}).get(f"{part}_ms" if part != "prose_wait" else "prose_wait_ms")
            return float(value) if isinstance(value, (int, float)) else None
        return None


@dataclass
class Reconstruction:
    session: dict[str, Any]
    events: list[dict[str, Any]]
    turns: list[Turn]
    proposals: dict[str, ProposalRecord]
    orphans: list[dict[str, Any]]           # tablet and Mac events outside any turn
    unknown_kinds: Counter = field(default_factory=Counter)
    # The appliance layer's own events (§18): `pad_*`, from the native shell around the page.
    # They belong to no turn BY CONSTRUCTION — an app being backgrounded is not part of a
    # question — so they are filed here rather than counted as kinds the report cannot read.
    # Section 17 reads them; every other section is unchanged by their presence.
    appliance: list[dict[str, Any]] = field(default_factory=list)
    # Commands, row actions and branch moves that belong to no turn — a tap is not a turn, and
    # most of them happen between two. Kept so section 14 can count them.
    controls: list[dict[str, Any]] = field(default_factory=list)
    # The moments a second finger landed while the orb was recording, from the tablet's own
    # `hold` events and the branch forks they caused. Used to tell a gesture collision from a
    # failure of the recogniser.
    collisions: list[dict[str, Any]] = field(default_factory=list)
    # What the owner could SEE (app/observability/visible.py): the findings, the two outcomes
    # per turn, and what he said about the product while he was testing it.
    experience: Any = None

    def turn(self, turn_id: str) -> Turn | None:
        return next((t for t in self.turns if t.turn_id == turn_id), None)


# ------------------------------------------------------------------ reconstruction


def reconstruct(events: list[dict[str, Any]], *, capability_states: dict[str, dict[str, Any]] | None = None) -> Reconstruction:
    """Turns, tool calls and proposals from the timeline, joined by their ids. Deterministic:
    the same file gives the same structure.

    `capability_states` is `app.capabilities.families.states(runtime)` when the caller has a
    runtime. It decides one thing: whether a change the owner asked for out loud is a family
    that does not exist, a scope that has not been granted, or a capability that is READY and
    was declined anyway. Without it the families' declared states are used.
    """
    events = sorted(events, key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0)))
    session: dict[str, Any] = {"test_session_id": "", "name": "", "started_at": None, "stopped_at": None, "duration_s": None}
    turns: dict[str, Turn] = {}
    order: list[str] = []
    proposals: dict[str, ProposalRecord] = {}
    tools: dict[str, ToolRecord] = {}
    orphans: list[dict[str, Any]] = []
    appliance: list[dict[str, Any]] = []
    unknown: Counter = Counter()
    controls: list[dict[str, Any]] = []
    pending_submits: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def turn_for(event: dict[str, Any]) -> Turn | None:
        turn_id = str(event.get("turn_id") or "")
        if not turn_id:
            return None
        if turn_id not in turns:
            turns[turn_id] = Turn(turn_id=turn_id, session_id=str(event.get("session_id") or ""), seq=int(event.get("seq") or 0), started_at=float(event.get("ts") or 0.0))
            order.append(turn_id)
        return turns[turn_id]

    def proposal_for(event: dict[str, Any]) -> ProposalRecord:
        pid = str(event.get("proposal_id") or "")
        if pid not in proposals:
            proposals[pid] = ProposalRecord(proposal_id=pid)
        p = proposals[pid]
        for key in ("turn_id", "session_id", "operation", "tool", "risk", "interaction", "entity_kind", "entity_label", "undo_of"):
            if event.get(key) and not getattr(p, key):
                setattr(p, key, event[key])
        if event.get("reversible") is not None and p.reversible is None:
            p.reversible = bool(event["reversible"])
        return p

    for event in events:
        kind = str(event.get("kind") or "")
        session["test_session_id"] = session["test_session_id"] or str(event.get("test_session_id") or "")
        if kind == "session_started":
            session["name"] = str(event.get("name") or "")
            session["started_at"] = event.get("started_at") or event.get("ts")
        elif kind == "session_stopped":
            session["stopped_at"] = event.get("ts")
            session["duration_s"] = event.get("duration_s")
        elif kind == "turn_started":
            turn = turn_for(event)
            if turn is not None:
                turn.session_id = str(event.get("session_id") or turn.session_id)
                turn.input = str(event.get("input") or "")
                turn.focus = event.get("focus") if isinstance(event.get("focus"), dict) else None
                turn.waiting = [str(x) for x in event.get("waiting") or []]
                turn.started_at = float(event.get("ts") or 0.0)
                turn.seq = int(event.get("seq") or 0)
                queued = pending_submits.get(turn.session_id) or []
                if queued:
                    turn.submitted = queued.pop(0)
        elif kind == "stt":
            turn = turn_for(event)
            if turn is not None:
                turn.stt = event
        elif kind == "lane":
            turn = turn_for(event)
            if turn is not None:
                turn.lane = event
        elif kind == "fast_path":
            turn = turn_for(event)
            if turn is not None:
                turn.fast = event
        elif kind == "read_plan":
            turn = turn_for(event)
            if turn is not None:
                turn.read_plans.append(event)
        elif kind == "turn_performance":
            turn = turn_for(event)
            if turn is not None:
                turn.performance = event
        elif kind == "prefetch":
            turn = turn_for(event)
            if turn is not None:
                turn.prefetch = event
        elif kind == "model":
            turn = turn_for(event)
            if turn is not None:
                turn.model = event
        elif kind == "turn_finished":
            turn = turn_for(event)
            if turn is not None:
                turn.finished = event
                turn.finished_at = float(event.get("ts") or 0.0)
        elif kind == "tool_requested":
            tc = str(event.get("tool_call_id") or "")
            record = ToolRecord(tool_call_id=tc, tool=str(event.get("tool") or ""), turn_id=str(event.get("turn_id") or ""), requested_at=float(event.get("ts") or 0.0),
                                args=event.get("args") if isinstance(event.get("args"), dict) else {}, tier=str(event.get("tier") or ""), disposition=str(event.get("disposition") or ""))
            tools[tc] = record
            turn = turn_for(event)
            if turn is not None:
                turn.tools.append(record)
            else:
                orphans.append(event)
        elif kind == "tool_finished":
            tc = str(event.get("tool_call_id") or "")
            record = tools.get(tc)
            if record is None:
                record = ToolRecord(tool_call_id=tc, tool=str(event.get("tool") or ""), turn_id=str(event.get("turn_id") or ""))
                tools[tc] = record
                turn = turn_for(event)
                if turn is not None:
                    turn.tools.append(record)
            record.finished_at = float(event.get("ts") or 0.0)
            record.outcome = str(event.get("outcome") or "")
            record.ok = event.get("ok")
            record.error = str(event.get("error") or "")
            record.ms = float(event["ms"]) if isinstance(event.get("ms"), (int, float)) else None
            record.result = event.get("result") if isinstance(event.get("result"), dict) else None
            record.proposal_id = str(event.get("proposal_id") or "")
            record.missing_capability = str(event.get("missing_capability") or "")
        elif kind.startswith("action_") and event.get("proposal_id"):
            p = proposal_for(event)
            if kind in ("action_arm_refused", "action_commit_refused"):
                p.refusals.append(event)
            elif kind == "action_commit":
                p.commits.append(event)
            else:
                p.events.append(event)
            turn = turn_for(event)
            if turn is not None and p not in turn.proposals:
                turn.proposals.append(p)
        elif kind in ("working_set", "cross_source"):
            turn = turn_for(event) or _turn_in_flight(turns, order, event)
            if turn is not None:
                turn.sets.append(event)
            else:
                orphans.append(event)
        elif kind == "query_rejected":
            turn = turn_for(event) or _turn_in_flight(turns, order, event)
            if turn is not None:
                turn.rejected.append(event)
            else:
                orphans.append(event)
        elif kind in ("command", "command_stage", "row_action"):
            # `_turn_during`, not `_turn_in_flight`: a hydration that lands after the answer
            # belongs to the turn it was for, and a tap thirty seconds later belongs to nothing.
            # Most taps belong to no turn — a tap is not a turn — and saying so is the point.
            turn = turn_for(event) or _turn_during(turns, order, event)
            if turn is not None:
                turn.commands.append(event)
            controls.append(event)
        elif kind.startswith("branch_"):
            turn = turn_for(event) or _turn_during(turns, order, event)
            if turn is not None:
                turn.branch_events.append(event)
            controls.append(event)
        elif kind in ("prediction", "anticipation"):
            # What the Mac guessed the owner would want next, and what it started reading
            # before he asked. Read here so an hour that anticipated 9 times and was starved 3
            # times can be reported as one sentence rather than as "event kinds this report
            # does not read".
            turn = turn_for(event) or _turn_during(turns, order, event)
            if turn is not None:
                (turn.predictions if kind == "prediction" else turn.anticipations).append(event)
            controls.append(event)
        elif kind == "owner_feedback":
            # What the owner said about the product while he was testing it (§16). Filed
            # against its turn so the report can print it beside what was on screen.
            turn = turn_for(event) or _turn_during(turns, order, event)
            if turn is not None:
                turn.feedback.append(event)
            else:
                orphans.append(event)
        elif kind == "unsupported_claim":
            turn = turn_for(event)
            if turn is not None:
                turn.claims.append(event)
            else:
                orphans.append(event)
        elif kind.startswith("batch_") and event.get("batch_id"):
            turn = turn_for(event) or _turn_in_flight(turns, order, event)
            if turn is not None:
                turn.batches.append(event)
            else:
                orphans.append(event)
        elif kind == "context_hydration":
            turn = _turn_in_flight(turns, order, event)
            if turn is not None:
                turn.hydrations.append(event)
            else:
                orphans.append(event)
        elif kind == "context_request":
            turn = turn_for(event) or _turn_in_flight(turns, order, event)
            if turn is not None:
                turn.context_requests.append(event)
            else:
                orphans.append(event)
        elif kind == "tts":
            turn = turn_for(event)
            if turn is not None:
                turn.tts.append(event)
            else:
                orphans.append(event)
        elif kind.startswith("tablet_"):
            if kind == "tablet_turn_submitted":
                pending_submits[str(event.get("session_id") or "")].append(event)
                continue
            turn = turn_for(event)
            if turn is not None:
                turn.tablet.append(event)
                pid = str(event.get("proposal_id") or "")
                if pid:
                    proposal_for({"proposal_id": pid}).tablet.append(event)
                if kind == "tablet_render":
                    # A render names the proposals whose cards it drew, inside the cards.
                    for c in event.get("cards") or []:
                        if isinstance(c, dict) and c.get("proposal_id"):
                            proposal_for({"proposal_id": str(c["proposal_id"])}).tablet.append(event)
            else:
                orphans.append(event)
        elif kind.startswith("pad_"):
            # The appliance: `app/observability/pad.py`. Matched by PREFIX rather than against
            # the known set, so a timeline written by a newer backend — one that has learned a
            # `pad_` kind this one has not — is still read, and the unrecognised kind shows up
            # in section 17's counts instead of as "event kinds this report does not read".
            appliance.append(event)
        else:
            unknown[kind] += 1
            orphans.append(event)

    # A proposal's events name its turn; a turn it was not filed under yet gets it now.
    for p in proposals.values():
        if p.turn_id and p.turn_id in turns and p not in turns[p.turn_id].proposals:
            turns[p.turn_id].proposals.append(p)
    result = [turns[t] for t in order]
    collisions = _collisions(events)
    # The tap bursts the voice layer swallowed, read once for the whole timeline: a long hold
    # that produced nothing inside one of these was competing with a finger (D-13).
    taps = _tap_bursts(events)
    for turn in result:
        turn.tools.sort(key=lambda t: t.requested_at or t.finished_at)
        _classify(turn, collisions=collisions, taps=taps, capability_states=capability_states)
        turn.cluster = _cluster(turn)
    _mark_repeats(result)
    rec = Reconstruction(session=session, events=events, turns=result, proposals=proposals, orphans=orphans,
                         unknown_kinds=unknown, controls=controls, collisions=collisions, appliance=appliance)
    # The second reading: what the owner could SEE. It runs over the whole reconstruction
    # because most of what it reads spans turns — six reconciles across six turns, a burst of
    # Home in twenty seconds, a half focused and never redrawn — and it puts its classes on
    # the turns themselves, so every section that reads `turn.classes` reads these too.
    rec.experience = visible.apply(rec)
    return rec


def _turn_during(turns: dict[str, Turn], order: list[str], event: dict[str, Any]) -> Turn | None:
    """The turn that was actually RUNNING at that moment, or None.

    Stricter than `_turn_in_flight`, which reaches thirty seconds past a turn's end because a
    context hydration that lands after the answer is still that answer's. A tap is not: one made
    while the Mac was thinking belongs to that turn, and one made afterwards belongs to the
    owner working the screen between two questions.
    """
    ts = float(event.get("ts") or 0.0)
    for turn_id in reversed(order):
        turn = turns[turn_id]
        end = turn.finished_at or (turn.started_at + 30.0)
        if turn.started_at <= ts <= end:
            return turn
    return None


def _turn_in_flight(turns: dict[str, Turn], order: list[str], event: dict[str, Any]) -> Turn | None:
    """The turn a Mac-side event without a turn id belongs to: the one in flight at that
    moment, else the last one finished within a few seconds (a hydration that landed after
    the answer left)."""
    ts = float(event.get("ts") or 0.0)
    for turn_id in reversed(order):
        turn = turns[turn_id]
        if turn.started_at <= ts and (not turn.finished_at or ts <= turn.finished_at + 30.0):
            return turn
    return None


# -------------------------------------------------------------------- classification


def _contract_classes(turn: Turn) -> tuple[list[str], list[str], list[str]]:
    """The request contract, held against what the turn actually did.

    This is the section of the report that would have caught the September turn which asked
    for two items to be added to an order, called nothing, staged nothing, and answered as
    though it had. Words and counts only.
    """
    from app.observability import contract as contract_mod
    from app.observability import semantics

    classes: list[str] = []
    signals: list[str] = []
    # Signals that belong to the TURN rather than to a class: the reading of the request, and
    # any disagreement with the router. Kept apart because `classes` and `signals` are paired
    # index for index by the caller, and a note with no class would shift every pair after it.
    notes: list[str] = []
    question, answer = turn.question, turn.answer
    ui_asked = "UI_INTENT" in ()  # placeholder kept out of the way; the regex does the work
    # Whether a change was asked for is the ROUTER's answer, taken off the turn's own `lane`
    # event, and not a second reading of the words by this file. The contract module still
    # decides between the other five shapes — UI, navigation, workflow, meta, read — because
    # those are about what the sentence points AT and the router says nothing about them.
    verdict = turn.verdict if turn.verdict is not None else semantics.read_request(question, lane=turn.lane)
    turn.verdict = verdict
    kind = contract_mod.contract_of(question, ui_asked=ui_asked)
    # §5. "Can you expand his customer page?", "bring up a UI for the customer's page",
    # "show me his orders" — a request for a visible workspace. `contract_of` reads the nouns
    # of the screen (button, tab, column, card) and misses every one of these, so the report
    # filed the three attempts of 20:14:02–20:14:22 as read requests and never asked whether
    # anything appeared. The verb is what makes it a UI request, and the verb is here.
    if kind in (contract_mod.READ_INTENT, contract_mod.META_CAPABILITY_INTENT) and _asked_to_see(question):
        kind = contract_mod.UI_INTENT
        notes.append("read as a request for a workspace: " + _asked_to_see(question))
    if kind == contract_mod.WRITE_INTENT and not verdict.mutation:
        # §27D. A noun or a state is not a requested mutation: "what is the refund status",
        # "which customers need replying to", "find an order that has not been fulfilled".
        # Downgraded, and the disagreement is on the record rather than silent.
        kind = contract_mod.READ_INTENT
        notes.append(verdict.disagreement or "read as a question, not an instruction")
    elif kind != contract_mod.WRITE_INTENT and verdict.mutation and verdict.mutation_source == "router" and kind == contract_mod.READ_INTENT:
        # The router saw a change and the contract module's own regexes did not. The router
        # is the one that decided the lane, so it is the one that decides the contract.
        kind = contract_mod.WRITE_INTENT
        notes.append("the router read this as a change" + (f" ({verdict.reason})" if verdict.reason else ""))
    turn.contract = kind
    staged = [p for p in turn.proposals if p.proposal_id]
    settled = [p for p in staged if p.status in ("VERIFIED", "EXECUTED")]

    # §20. OWNER_FEEDBACK precedes generic mutation matching, and takes the turn out of the
    # write contract entirely. "Make a note of what you just failed to do", "log that I cannot
    # click the merge button", "tag that" are mutation WORDS with no mutation behind them: the
    # thing being changed is the test session's own record, `owner_feedback` already answered,
    # and the change the words name was never asked of the shop. The 11 September report filed
    # three of them UNFULFILLED_ACTION at severity 5/5 against "the write tools" and sent
    # engineering looking for a write tool that is not missing.
    recorded_feedback = _recorded_feedback(turn)
    if recorded_feedback:
        classes.append("OWNER_FEEDBACK")
        signals.append(recorded_feedback)
        return classes, signals, notes

    if kind == contract_mod.WRITE_INTENT:
        if contract_mod.reports_success(answer) and not settled:
            classes.append("FALSE_SUCCESS")
            signals.append("the answer says the change was made; " + (f"{len(staged)} card(s) were staged and none is verified" if staged else "nothing was staged and no tool ran"))
        elif not staged and not contract_mod.declines(answer) and not contract_mod.waiting_for_a_gesture(answer):
            classes.append("UNFULFILLED_ACTION")
            signals.append("a change was asked for; nothing was staged and nothing was refused in words")
        limitation = contract_mod.limitation_for(question)
        if limitation is not None and contract_mod.reports_success(answer):
            notes.append(f"the request runs into a known limitation ({limitation['name']}) and was answered as done")
    # §5. "Show me", "open", "pull up", "bring up", "expand", "view" — a request for a visible
    # workspace has not succeeded until one appears, whether or not the answer declined.
    # `turn_0cce1678e014` / `turn_ddb733d15472` / `turn_9d59579ab03e` are the same request three
    # times in twenty seconds: a 1,014 px capability card, then nothing, then nothing, the
    # third prefixed "No," and asking outright to "bring up a UI". None was filed, because the
    # old rule needed the answer to decline in words first.
    if kind == contract_mod.UI_INTENT and not _workspace_appeared(turn) and not _is_feedback(question):
        classes.append("UI_INTENT_UNFULFILLED")
        signals.append(
            "asked for something on the screen and no visible workspace appeared: "
            + (f"the answer declined ({_cell(answer, 60)})" if contract_mod.declines(answer)
               else "the answer spoke instead")
            + (f"; the cards drawn were {', '.join(turn.ui)}" if turn.ui else "; no card at all"))
    relation = _relation_gap(turn)
    if relation:
        classes.append("UI_RELATION_MISSING")
        signals.append(relation)
    field = _missing_field(turn)
    if field:
        classes.append("DATA_FIELD_UNAVAILABLE")
        signals.append(field)
    partial = _partial_coverage(turn)
    if partial:
        classes.append("PARTIAL_COVERAGE")
        signals.append(partial)
    divergence = _divergence(turn)
    if divergence:
        classes.append("INTENT_DIVERGENCE")
        signals.append(divergence)
    return classes, signals, notes


# Fields an answer may say it has no access to, and the tool that returns them. Each pair is
# a claim the report can check rather than take on trust.
_FIELDS: tuple[tuple[Any, str, str], ...] = (
    (re.compile(r"\b(?:street|full|actual|whole)? ?address(?:es)? line|only the town|only the (?:city|postcode)|don'?t (?:return|have) the (?:actual |full )?(?:street )?address", re.I), "the street address", "shopify_order_address"),
    (re.compile(r"\bcan'?t (?:read|search) (?:the )?(?:body|bodies|full text) of", re.I), "the text of an email", "gmail_find_in_email"),
)


def _missing_field(turn: Turn) -> str:
    """An answer that says a field is unavailable, when a registered tool returns it."""
    from app.observability.claims import registered

    if not turn.answer or not CANNOT_RE.search(turn.answer):
        return ""
    known = registered()
    for pattern, what, tool in _FIELDS:
        if pattern.search(turn.answer) and tool in known:
            return f"said it has no {what}; {tool} returns it"
    return ""


def _partial_coverage(turn: Turn) -> str:
    """A read that covered part of what was asked, where the answer does not say so."""
    for record in turn.tools:
        shape = record.result if isinstance(record.result, dict) else {}
        checked, found = shape.get("threads_checked"), shape.get("threads_found")
        if isinstance(checked, int) and isinstance(found, int) and 0 <= checked < found:
            if not re.search(r"\b(?:checked|read|of the|could not (?:open|check))\b", turn.answer or "", re.I):
                return f"{record.tool} read {checked} of {found}; the answer does not say so"
    return ""


_DECLINED_MECHANISM = re.compile(r"\b(?:no way to|can'?t|cannot) ([a-z ]{4,40}?)(?:\.|,|$)", re.I)


def _divergence(turn: Turn) -> str:
    """The answer declined a mechanism the request never named. "There is no way to merge
    Gmail threads", to a request that asked for a reply on a separate thread."""
    if not turn.answer or not turn.question:
        return ""
    match = _DECLINED_MECHANISM.search(turn.answer)
    if not match:
        return ""
    phrase = match.group(1).strip().lower()
    words = [w for w in re.findall(r"[a-z]{4,}", phrase) if w not in ("that", "this", "them", "from", "here", "with", "your", "into")]
    if not words:
        return ""
    asked = (turn.question or "").lower()
    if any(w in asked for w in words):
        return ""
    return f"declined {phrase!r}, which the request did not ask for"


def _collisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The moments a second finger landed on the orb, or a gesture forked the conversation.

    §27A. Six turns of the live session were filed under STT_ERROR. What happened was that two
    fingers went down on the orb, the recorder stopped, and the recogniser was handed silence —
    a multitouch, not a mis-hearing, and a fix in `web/app.js` rather than in the keyterms. The
    tablet reports the touch itself (`hold` with `phase: "multitouch"`, and the finger count),
    and a split posts `navigate {nav: "split"}` and forks a branch on the Mac. Any of those
    within `GESTURE_WINDOW_S` of a recording that produced nothing is what produced nothing.
    """
    out: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or 0.0)
        if kind == "tablet_hold" and str(event.get("phase") or "") == "multitouch":
            fingers = event.get("fingers") if isinstance(event.get("fingers"), int) else event.get("count")
            out.append({"ts": ts, "what": "multitouch", "detail": f"{fingers or 2} fingers on the {event.get('target') or 'orb'}"})
        elif kind == "tablet_navigate" and str(event.get("nav") or "") in ("split", "merge"):
            out.append({"ts": ts, "what": str(event["nav"]), "detail": f"{event['nav']} by {event.get('name') or 'gesture'}"})
        elif kind == "branch_forked":
            out.append({"ts": ts, "what": "fork", "detail": f"branch {event.get('branch_id') or '?'} forked"})
    return out


def _gesture_collision(turn: Turn, collisions: list[dict[str, Any]],
                       taps: list[dict[str, Any]] | None = None) -> str:
    """The gesture that explains this turn's empty recording, if one does.

    §22 and D-13. At 23:08:28 the owner held for **4,526 ms** — a real, deliberate, properly
    held question — and the transcript came back empty. Two more real holds in the same window
    (1,237 ms and 1,186 ms) went the same way, and the 11 September report attributed all of it
    to speech quality and made STT its number two improvement candidate.

    Those long holds sit INSIDE the twenty-six-tap burst: his other finger was hitting the
    screen throughout, each tap starting and ending a competing recording on the same element.
    That is gesture arbitration destroying real speech, not a recogniser failing to hear it —
    and until touch ownership is fixed every speech measurement in the session is contaminated.
    So a tap burst overlapping the hold counts as a gesture here, exactly as a second finger
    does, and the recogniser is not sent the bill for it.
    """
    start = turn.started_at or 0.0
    end = turn.finished_at or start
    near = [c for c in (collisions or [])
            if start - GESTURE_WINDOW_S <= c["ts"] <= max(end, start) + 0.5]
    for burst in taps or []:
        if burst["from"] - GESTURE_WINDOW_S <= max(end, start) and burst["to"] + GESTURE_WINDOW_S >= start:
            near.append({"ts": burst["from"], "what": "tap burst", "detail": burst["detail"]})
    if not near:
        return ""
    return "; ".join(sorted({str(c["detail"]) for c in near}))


def _tap_bursts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The bursts of control taps the voice layer swallowed, as windows.

    Read from `app/observability/touch.py`, which is the one place that decides what a touch
    was. Each burst is a window on the session clock, so a hold that overlaps one can be said
    to have been competing with a finger rather than mis-heard.
    """
    from app.observability import touch

    out: list[dict[str, Any]] = []
    for found in touch.classify(events):
        if found.name != "CONTROL_TAP_MISROUTED_TO_VOICE" or found.taps < touch.BURST_MIN:
            continue
        out.append({"from": found.at, "to": found.at + touch.BURST_S,
                    "detail": f"{found.taps} control taps on the {found.target or 'orb'} in the "
                              f"same window, each starting and ending a competing recording"})
    return out


def _empty_speech(turn: Turn) -> bool:
    """Whether the recogniser was handed something it could make no words out of. The three
    shapes the route writes: `ok: false` from the recogniser, an `empty` transcript, and audio
    the route refused for its size."""
    stt = turn.stt or {}
    return bool(stt and stt.get("ok") is False) or turn.error_kind in ("speech", "empty", "audio_too_large")


def _relation_gap(turn: Turn) -> str:
    """An email surface drawn without the order it is about, in a turn whose own data held one.

    §27B. The live session's report said "Email correlation missing: never", which was true of
    the BACKEND and false of the screen: the thread card showed the words and hid the order.
    Backend data existing is not a visible relationship existing, so this is read off the
    render — the card's own `relations`, which are the `data-kind` values of the tappable links
    inside it — and never off what a tool returned.
    """
    cards = [c for r in turn.tablet_events("render") for c in (r.get("cards") or []) if isinstance(c, dict)]
    email_cards = [c for c in cards if str(c.get("type") or "") in EMAIL_CARDS]
    if not email_cards:
        return ""
    if any(RELATION_ORDER in [str(x) for x in (c.get("relations") or [])] for c in email_cards):
        return ""
    # An order card drawn beside the email one carries the relation by being there.
    if any(str(c.get("type") or "") == "order" for c in cards):
        return ""
    held = _orders_in_hand(turn)
    if not held:
        return ""
    kinds = ", ".join(sorted({str(c.get("type")) for c in email_cards}))
    return f"the {kinds} surface drew no order, and the turn held {len(held)}: " + ", ".join(sorted(held)[:3])


def _orders_in_hand(turn: Turn) -> set[str]:
    """The orders this turn's own data named: what the tools returned, what the screen was
    already on, and what the context hydration was about. Ids only."""
    held: set[str] = set()
    for record in turn.tools:
        shape = record.result if isinstance(record.result, dict) else {}
        orders = shape.get("orders")
        if isinstance(orders, dict):
            held.update(str(x) for x in (orders.get("ids") or []))
        if shape.get("order_id"):
            held.add(str(shape["order_id"]))
        linked = shape.get("linked_order")
        if isinstance(linked, dict) and linked.get("order_id"):
            held.add(str(linked["order_id"]))
    for entity in turn.ui_entities:
        if str(entity.get("type") or "") == "order" and entity.get("ref"):
            held.add(str(entity["ref"]))
    focus = turn.focus or {}
    if str(focus.get("type") or focus.get("kind") or "") == "order" and focus.get("ref"):
        held.add(str(focus["ref"]))
    for hydration in turn.hydrations:
        if hydration.get("order_id"):
            held.add(str(hydration["order_id"]))
    return held


def _classify(turn: Turn, *, collisions: list[dict[str, Any]] | None = None,
              taps: list[dict[str, Any]] | None = None,
              capability_states: dict[str, dict[str, Any]] | None = None) -> None:
    from app.observability import semantics

    classes: list[str] = []
    signals: list[str] = []
    notes: list[str] = []
    # The request as the router read it, and the change it named, before anything else: what
    # this Mac can do about that change decides whether an answer of "I cannot" is a capability
    # missing or a capability declined.
    turn.verdict = semantics.read_request(turn.question, lane=turn.lane)
    spoken = _spoken_capability(turn, capability_states)
    stt = turn.stt or {}
    error_kind = turn.error_kind
    tools = turn.tools
    ok_tools = [t for t in tools if t.outcome in ("ok", "staged")]
    failed_tools = [t for t in tools if t.outcome in ("error", "exception", "unprepared")]
    refused = [t for t in tools if t.outcome == "refused"]
    not_yet = [t for t in tools if t.outcome == "not_yet"]
    missing = [t for t in tools if t.missing_capability]
    tablet_failed = turn.tablet_events("turn_failed")

    if _empty_speech(turn):
        gesture = _gesture_collision(turn, collisions or [], taps or [])
        if gesture:
            classes.append("GESTURE_COLLISION")
            signals.append(f"the recording was ended by a gesture, not mis-heard: {gesture}")
        else:
            classes.append("STT_ERROR")
            signals.append(f"speech: {stt.get('reason') or error_kind}")
    if error_kind == "timeout" or any(e.get("aborted") for e in tablet_failed) or any(re.search(r"time[d ]?out|timeout", t.error, re.I) for t in failed_tools):
        classes.append("TIMEOUT")
        signals.append("a timeout: " + (error_kind or next((t.tool for t in failed_tools if re.search(r"time[d ]?out|timeout", t.error, re.I)), "the tablet gave up")))
    permission_refusals = [r for p in turn.proposals for r in p.refusals if str(r.get("code") or "") in PERMISSION_CODES]
    if permission_refusals or ((turn.finished or {}).get("writes_code") in PERMISSION_CODES and turn.proposals):
        classes.append("PERMISSION_ERROR")
        signals.append("a tap refused by the write boundary: " + ", ".join(sorted({str(r.get('code')) for r in permission_refusals}) or [str((turn.finished or {}).get("writes_code"))]))
    false_claim = _false_claim(turn)
    if false_claim:
        classes.append("FALSE_UNSUPPORTED")
        signals.append("declined, though the Mac composes this: " + ", ".join(false_claim["capabilities"]) + " via " + ", ".join(false_claim["composable_via"]))
    elif missing or (not ok_tools and CANNOT_RE.search(turn.answer)):
        # Nothing succeeded and the answer said it cannot. WHICH kind of "cannot" it was is the
        # capability table's answer, not this file's: a family that does not exist is missing, a
        # family whose scope is not granted is a grant, and a READY family declined anyway is
        # the assistant being wrong about itself. Filing all three as MISSING_CAPABILITY is how
        # a change that has since been BUILT gets reported as still open.
        if spoken is None or missing or spoken["state"] == semantics.NO_FAMILY:
            classes.append("MISSING_CAPABILITY")
            signals.append(spoken["signal"] if spoken is not None and not missing
                           else "asked for: " + (", ".join(sorted({t.missing_capability for t in missing})) or "something the assistant said it cannot do"))
        elif spoken["state"] == "READY":
            classes.append("FALSE_UNSUPPORTED")
            signals.append(spoken["signal"])
        else:
            classes.append("PERMISSION_ERROR")
            signals.append(spoken["signal"])
    if failed_tools:
        classes.append("TOOL_ERROR")
        signals.append("; ".join(f"{t.tool}: {t.error[:80]}" for t in failed_tools[:3]))
    unverified = [p for p in turn.proposals if p.status == "UNVERIFIED" or (p.committed and p.status == "FAILED" and p.code == "unverified")]
    if unverified:
        classes.append("VERIFICATION_ERROR")
        signals.append("not proven: " + ", ".join(p.proposal_id for p in unverified))
    duplicates = _duplicate_calls(tools)
    rules = [t for t in refused if not t.missing_capability]
    if len(not_yet) >= 2 or rules or duplicates:
        classes.append("TOOL_SELECTION_ERROR")
        if len(not_yet) >= 2:
            signals.append(f"{len(not_yet)} calls with an id the conversation had not been shown")
        if rules:
            signals.append("refused by a rule: " + ", ".join(f"{t.tool} ({t.error[:60]})" for t in rules[:2]))
        if duplicates:
            signals.append("the same call twice: " + ", ".join(duplicates))
    render = turn.render or {}
    exceptions = turn.tablet_events("exception")
    if exceptions or render.get("skipped") or render.get("errors") or turn.tablet_events("image_failed"):
        classes.append("UI_RENDER_ERROR")
        if exceptions:
            signals.append("tablet exception: " + str(exceptions[0].get("message") or "")[:100])
        if render.get("skipped"):
            signals.append("cards the tablet could not draw: " + ", ".join(str(x) for x in render["skipped"]))
        if render.get("errors"):
            signals.append("error cards: " + ", ".join(str(x) for x in render["errors"]))
        if turn.tablet_events("image_failed"):
            signals.append(f"{len(turn.tablet_events('image_failed'))} image(s) failed to load")
    if _abandoned(turn) or _dead_touches(turn):
        classes.append("UI_NAVIGATION_PROBLEM")
        if _abandoned(turn):
            signals.append(f"the screen was left within {ABANDON_S:.0f} s of rendering")
        signals.extend(_dead_touches(turn))
    if _context_incomplete(turn):
        classes.append("CONTEXT_INCOMPLETE")
        signals.append(_context_incomplete(turn))
    if CLARIFY_RE.search(turn.answer) and not ok_tools and (stt.get("order_numbers") or turn.focus):
        classes.append("INTENT_ERROR")
        signals.append("asked which, though the request named one (" + (", ".join(str(n) for n in stt.get("order_numbers") or []) or "the entity in focus") + ")")
    contract_classes, contract_signals, contract_notes = _contract_classes(turn)
    for name, signal in zip(contract_classes, contract_signals, strict=True):
        if name not in classes:
            classes.append(name)
            signals.append(signal)
    notes.extend(contract_notes)
    # §27C. A change the owner ASKED FOR out loud that nothing on this Mac claims. The tool
    # registry can only report a capability the model reached for; a request the model declined
    # in words, or answered as though it had done, reaches no tool at all — which is why "create
    # an order", "a discount code" and "store credit" were reported as "Potential new actions:
    # none". The capability table (app/capabilities/families.py) is what decides: no family is a
    # capability that does not exist; a family that is not READY is a grant or a provider, and
    # its state names which. That difference is what keeps a fix from being reported as still
    # open, and an open one as fixed.
    if spoken is not None and spoken["state"] == semantics.NO_FAMILY:
        if "MISSING_CAPABILITY" not in classes:
            classes.append("MISSING_CAPABILITY")
            signals.append(spoken["signal"])
        elif spoken["signal"] not in signals:
            notes.append(spoken["signal"])
    elif spoken is not None and spoken["state"] not in ("READY", semantics.NO_FAMILY):
        if "PERMISSION_ERROR" not in classes:
            classes.append("PERMISSION_ERROR")
            signals.append(spoken["signal"])
        else:
            notes.append(spoken["signal"])
    if (error_kind or tablet_failed) and not classes:
        classes.append("UNKNOWN")
        signals.append(f"error_kind={error_kind or 'tablet turn_failed'}")
    turn.classes = classes
    turn.signals = signals + notes
    cards = [u for u in turn.ui if u not in ("error", "context_stack", "assistant")]
    # A class that describes what went RIGHT is not a reason to call a turn partial. §20:
    # successful owner feedback is a success, and the old rule made it a failure twice over —
    # once as UNFULFILLED_ACTION, and once because any class at all took the turn out of
    # "successful".
    defects = [c for c in classes if c not in NON_DEFECT]
    if not defects:
        turn.outcome = "successful"
    elif ok_tools or any(p.status == "VERIFIED" for p in turn.proposals) or (cards and not error_kind):
        turn.outcome = "partial"
    else:
        turn.outcome = "failed"
    if defects in (["MISSING_CAPABILITY"], ["FALSE_UNSUPPORTED"]) and not ok_tools:
        turn.outcome = "failed"


def _is_feedback(question: str) -> bool:
    """Whether this sentence is the owner telling the product about itself.

    Used as a guard, not a class: "why is there bullshit on the screen right now?" names the
    screen, so `contract_of` reads it as a UI request — and it is not a request for a
    workspace, it is a complaint about the one he has. Filing it UI_INTENT_UNFULFILLED would be
    a second, wrong diagnosis of a turn that already has the right one
    (OWNER_FEEDBACK_IGNORED), which is the habit this whole workstream exists to break.
    """
    from app.observability import feedback as feedback_mod

    return feedback_mod.recognise(question) is not None


def _recorded_feedback(turn: Turn) -> str:
    """Whether this turn is the owner telling the product about itself, and it was written down.

    Two things must both be true: the sentence reads as local development feedback
    (`app/observability/feedback.py`, which is the same rule the router uses), and an
    `owner_feedback` event exists for the turn. Feedback that nothing recorded is
    OWNER_FEEDBACK_IGNORED and belongs to `app/observability/visible.py`; this is the other
    half, and it is a success.
    """
    from app.observability import feedback as feedback_mod

    if not turn.feedback:
        return ""
    recognition = feedback_mod.recognise(turn.question or turn.raw_text)
    if recognition is None:
        return ""
    shapes = ", ".join(dict.fromkeys(str(e.get("shape") or recognition.kind) for e in turn.feedback))
    return (f"the owner reported a defect ({shapes}) and it was recorded against this test "
            f"session with the screen he was on — the words name a change and none was asked "
            f"of the shop")


# The words that ask for a workspace. §5: expand, bring up and show require something visible.
# Anchored on an OBJECT, so "see if he's in Gmail anywhere" and "show me" on its own are not
# this: a request for a workspace names the thing it wants on the screen.
_ASKED_TO_SEE_RE = re.compile(
    r"\b(show me|open|pull up|bring up|expand|display|put up|let me see|"
    r"give me a (?:view|screen|page|ui)|i want to (?:see|be seeing))\b"
    r"(?=[^.?!]{0,60}\b(?:page|screen|ui|u\.i\.|card|profile|workspace|orders?|history|"
    r"inbox|email|customer|order|thread|list|details?|everything|it|him|her|them|that|this)\b)",
    re.I)


def _asked_to_see(question: str) -> str:
    """The words in this request that ask for something to be on the screen, or "" ."""
    found = _ASKED_TO_SEE_RE.search(question or "")
    return found.group(1).lower() if found else ""
# Cards that are not a workspace for anything the owner asked about: the assistant's own
# chrome, an error, the context stack, and the capability list — which is what "can you expand
# his customer page" produced, 1,014 px of what the system can do.
_NOT_A_WORKSPACE = frozenset({"error", "context_stack", "assistant", "capability", "half_empty",
                              "folded", "attention"})


def _workspace_appeared(turn: Turn) -> bool:
    """Whether anything the owner asked to SEE actually appeared.

    Read off what the turn drew, never off what a tool returned. A capability card is not a
    customer page; an error is not a workspace; the context stack is furniture.
    """
    drawn = {str(x) for x in turn.ui}
    for render in turn.tablet_events("render"):
        drawn |= {str(c.get("type") or "") for c in (render.get("cards") or []) if isinstance(c, dict)}
    return bool(drawn - _NOT_A_WORKSPACE - {""})


def _spoken_capability(turn: Turn, states: dict[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The change this turn's words asked for, and what this Mac can do about it.

    None when no change was asked for, or when the change's family is READY — a READY family
    that failed for some other reason is that other reason's business, and reporting it here
    would be reporting a built capability as missing.
    """
    from app.observability import semantics

    verdict = turn.verdict
    if verdict is None or not verdict.mutation or verdict.change is None:
        return None
    change = verdict.change
    state = semantics.capability_state(change, states)
    if state["state"] == "READY":
        # A family that stages ONE change being READY says nothing about the same change asked
        # for over a set. "Refund all of them" is not a refund the Mac can compose, and reading
        # the single family's READY as an answer to it would report an honest decline as the
        # assistant being wrong about itself. The bulk question has its own table and its own
        # rule (app/observability/claims.py, and section 13's bulk rows).
        wholesale = claims.bulk_request(turn.question)
        if wholesale is not None and not wholesale.get("supported"):
            return None
        return {"change": change.key, "what": change.what, "state": "READY", "scope": state["scope"], "family": state["family"],
                "signal": f"asked out loud to {change.what}; {state['label']} is READY on this Mac"}
    if state["state"] == semantics.NO_FAMILY:
        stated = f"; stated as a limitation ({change.limitation})" if change.limitation else ""
        return {"change": change.key, "what": change.what, "state": state["state"], "scope": "", "family": "",
                "signal": f"asked out loud to {change.what}; no capability family claims it{stated}"}
    scope = f" ({state['scope']})" if state["scope"] else ""
    return {"change": change.key, "what": change.what, "state": state["state"], "scope": state["scope"], "family": state["family"],
            "signal": f"asked out loud to {change.what}; {state['label']} is {state['state']}{scope}"}


def _false_claim(turn: Turn) -> dict[str, Any] | None:
    """The turn's claim signal, from the timeline when the Mac wrote one, else from the same
    rule applied now to the words (an older timeline, a session without the signal)."""
    for c in turn.claims:
        if c.get("false_unsupported"):
            return {"capabilities": [str(x) for x in c.get("capabilities") or []], "composable_via": [str(x) for x in c.get("composable_via") or []]}
    if turn.claims:
        return None
    signal = claims.claim(turn.question, turn.answer, [{"tool": t.tool, "ok": t.outcome in ("ok", "staged")} for t in turn.tools], _registered_for_claims())
    return signal if signal and signal.get("false_unsupported") else None


_REGISTERED_CACHE: list[str] | None = None


def _registered_for_claims() -> frozenset[str]:
    """The tools the claim rule judges against when a turn carries no signal of its own (an
    older timeline): this process's registry, read once."""
    global _REGISTERED_CACHE
    if _REGISTERED_CACHE is None:
        _REGISTERED_CACHE = registered_tools()
    return frozenset(_REGISTERED_CACHE)


def _duplicate_calls(tools: list[ToolRecord]) -> list[str]:
    seen: Counter = Counter((t.tool, tuple(sorted((k, str(v)) for k, v in t.args.items()))) for t in tools if t.outcome in ("ok", "staged", "error", "exception"))
    return [name for (name, _args), n in seen.items() if n > 1]


def _abandoned(turn: Turn) -> bool:
    render = turn.render
    if not render or not isinstance(render.get("t"), (int, float)):
        return False
    for nav in turn.tablet_events("navigate"):
        if nav.get("nav") in ("back", "home") and isinstance(nav.get("t"), (int, float)) and 0 <= (nav["t"] - render["t"]) / 1000 <= ABANDON_S:
            return True
    return False


def _dead_touches(turn: Turn) -> list[str]:
    out = []
    for tap in turn.tablet_events("rail_tap"):
        if tap.get("state") == "disabled":
            out.append(f"a tap on the disabled '{tap.get('action')}' chip")
    for nav in turn.tablet_events("navigate"):
        if nav.get("nav") == "dead_chip":
            out.append("a tap on a context chip the tablet no longer held")
    for g in turn.tablet_events("gesture"):
        if g.get("gesture") == "down" and g.get("state") in ("unavailable", "expired", "revoked", "stale"):
            out.append(f"a touch on a card already {g.get('state')}")
    for c in turn.tablet_events("action_commit"):
        if c.get("outcome") in ("unknown", "blocked_busy"):
            out.append(f"a tap the tablet could not settle ({c.get('outcome')})")
    return out


def _context_incomplete(turn: Turn) -> str:
    failed = turn.tablet_events("context_failed")
    if failed:
        return f"the tablet could not collect the rest of the order ({len(failed)} failed request(s))"
    if any(int(r.get("status") or 0) >= 500 for r in turn.context_requests):
        return "the order's history could not be read (/context answered 503)"
    unavailable = sorted({str(u) for h in turn.hydrations for u in (h.get("unavailable") or [])})
    if unavailable:
        return "unavailable for the order: " + ", ".join(unavailable)
    return ""


def _cluster(turn: Turn) -> str:
    names = {t.tool for t in turn.tools}
    words = f"{turn.question} {turn.answer}".lower()
    if turn.proposals or any(t.outcome == "staged" for t in turn.tools):
        return "actions"
    for name, prefixes, _keywords in CLUSTERS[1:]:
        if any(any(n.startswith(p) for p in prefixes) for n in names):
            return name
    for name, _prefixes, keywords in CLUSTERS[1:]:
        if any(k in words for k in keywords):
            return name
    return "other"


def _mark_repeats(turns: list[Turn]) -> None:
    """A signal, not a class: the answer repeats most of the previous answer in the session."""
    last: dict[str, str] = {}
    for turn in turns:
        previous = last.get(turn.session_id, "")
        if previous and turn.answer and _overlap(previous, turn.answer) >= 0.6:
            turn.signals.append("repeats the previous answer")
        if turn.answer:
            last[turn.session_id] = turn.answer


def _overlap(a: str, b: str) -> float:
    sa = {s.strip().lower() for s in re.split(r"[.!?]\s+", a) if len(s.strip()) > 12}
    sb = {s.strip().lower() for s in re.split(r"[.!?]\s+", b) if len(s.strip()) > 12}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


# ------------------------------------------------------------------------ rendering


def _fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} ms"


def _stats(values: list[float]) -> tuple[str, str, str]:
    if not values:
        return "—", "—", "—"
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))]
    return _fmt_ms(statistics.fmean(values)), _fmt_ms(statistics.median(values)), _fmt_ms(p95)


def _clock(ts: float | None) -> str:
    if not ts:
        return "—"
    import time

    return time.strftime("%H:%M:%S", time.localtime(float(ts)))


def _cell(text: Any, limit: int = 90) -> str:
    s = " ".join(str(text if text is not None else "").split())
    s = s.replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["_none_", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    out.append("")
    return out


def _closest_capability(name: str, registered: list[str]) -> str:
    for word, tool in CAPABILITY_WORDS.items():
        if word in name and tool in registered:
            return f"{tool} (by the word '{word}')"
    close = difflib.get_close_matches(name, registered, n=1, cutoff=0.5)
    return close[0] if close else "none close by name"


def registered_tools() -> list[str]:
    try:
        from app.tools import (  # noqa: F401
            analytics_tools,
            batch_tools,
            gmail_tools,
            gmail_writes,
            shopify_tools,
            shopify_writes,
        )
        from app.tools.registry import all_specs

        return sorted(s.name for s in all_specs() if not s.name.startswith("mock_"))
    except Exception:  # noqa: BLE001 — the report still reads without the registry
        return []


def _no_family() -> str:
    from app.observability import semantics

    return semantics.NO_FAMILY


def _uncovered_families(reached: list[str]) -> list[str]:
    """Of the intent families this session actually reached, the ones no golden scenario
    exercises. Read from `experience/matrix.py`, which derives it from the registries rather
    than from a list kept by hand — so a family added in this pass is on it the same day.
    Empty when the matrix cannot be built (a report written without the repository beside it)."""
    try:
        from experience import matrix

        gaps = set(matrix.uncovered())
    except Exception:  # noqa: BLE001 — the report still reads without the scenario list
        return []
    return sorted(name for name in reached if name in gaps)


def _branch_failures(rec: Reconstruction) -> list[tuple[str, str, str]]:
    """Where the two halves of the orb cost the owner something.

    A focus that changed who was listening and nothing on screen; a half put aside whose
    answer never appeared; a branch command the Mac refused. Each row cites what it read.
    """
    out: list[tuple[str, str, str]] = []
    renders = sorted(
        [(float(e.get("ts") or 0.0), e) for t in rec.turns for e in t.tablet_events("render")]
        + [(float(e.get("ts") or 0.0), e) for e in rec.orphans if e.get("kind") == "tablet_render"],
        key=lambda pair: pair[0],
    )
    for event in rec.controls:
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or 0.0)
        branch = str(event.get("branch_id") or "")
        if kind == "branch_focused":
            after = [e for at, e in renders if ts <= at <= ts + 5.0]
            if not after:
                out.append((branch or "—", "focus changed with nothing redrawn",
                            "who was listening moved and no card was drawn within five seconds"))
        elif kind == "branch_backgrounded":
            ready = [e for e in rec.events if str(e.get("kind") or "") in ("tablet_branch", "branch_focused")
                     and float(e.get("ts") or 0.0) > ts and str(e.get("branch_id") or e.get("id") or "") == branch]
            if not ready:
                out.append((branch or "—", "a half put aside was never returned to",
                            "backgrounded, and nothing afterwards names it again"))
        elif kind == "command" and event.get("ok") is False:
            out.append((branch or "—", f"the command {event.get('command')} was refused",
                        str(event.get("code") or "no code")))
    for event in rec.controls:
        if str(event.get("kind") or "") == "branch_cancelled" and event.get("revoked"):
            out.append((str(event.get("branch_id") or "—"), "a half was cancelled with cards waiting",
                        f"{event['revoked']} proposal(s) withdrawn"))
    return out


def _corrections(turns: list[Turn]) -> list[tuple[str, str, str]]:
    """The same thing said again. A pair of consecutive turns whose requests are mostly the
    same words is the owner correcting himself or the Mac; six of them in an hour is a shape,
    not an accident."""
    out: list[tuple[str, str, str]] = []
    previous: dict[str, Turn] = {}
    for turn in turns:
        before = previous.get(turn.session_id)
        previous[turn.session_id] = turn
        said = (turn.question or turn.raw_text or "").strip().lower()
        if before is None or not said:
            continue
        was = (before.question or before.raw_text or "").strip().lower()
        if not was or was == said:
            ratio = 1.0 if was == said and was else 0.0
        else:
            ratio = difflib.SequenceMatcher(None, was, said).ratio()
        if ratio >= REPHRASE_RATIO:
            out.append((turn.turn_id, f"said again after {before.turn_id} ({ratio:.0%} the same words)",
                        turn.question or turn.raw_text))
    return out


def _precision_input(turns: list[Turn]) -> list[tuple[str, str, str]]:
    """Where a value had to be got exactly right and a voice could not do it.

    §21. This table had **62 rows** in the 11 September report, dominated the document and made
    the precision-input path the number one improvement candidate. **61 of the 62 were
    `recording_too_short` events** — ordinary taps on controls, 39–140 ms, swallowed by the
    voice layer because the branch bar sits inside the orb's stacking context. Not one of them
    was about a value needing to be exact. The one real row was a transcript the normaliser had
    to correct.

    So a short recording is no longer evidence of anything here. What a touch was is
    `app/observability/touch.py`'s answer, in four classes; this table holds only POSITIVE
    evidence of exact entry — a value typed, a keyboard opened, a transcript corrected, a
    dimension the query language does not have.
    """
    from app.observability import touch

    out: list[tuple[str, str, str]] = []
    for turn in turns:
        for what, detail in touch.precision_evidence(turn):
            out.append((turn.turn_id, what, detail))
    return out


def _cross_source_workflows(turns: list[Turn]) -> list[tuple[str, int, list[str]]]:
    """Reads that crossed Shopify and Gmail in one turn, by the sequence of tools. Counted so
    a shape the owner keeps asking for can become one recipe instead of four calls."""
    shapes: Counter = Counter()
    where: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for turn in turns:
        names = tuple(x.tool for x in turn.tools if x.outcome in ("ok", "staged"))
        services = {x.service for x in turn.tools if x.outcome in ("ok", "staged")}
        crossed = any(e.get("kind") == "cross_source" for e in turn.sets)
        if crossed or ({"shopify", "gmail"} <= services and len(names) >= 2):
            shapes[names] += 1
            where[names].append(turn.turn_id)
    return [(" → ".join(names) or "(a cross-source read)", n, where[names][:5]) for names, n in shapes.most_common(10)]


def intelligence(rec: Reconstruction, registered: list[str], *, capability_states: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Section 13's evidence, by rule, each row citing its turn: false unsupported claims,
    composable requests that failed, the multi-tool workflows and follow-up shapes the
    session repeated, and the query dimensions, actions, bulk actions and card types asked
    for that do not exist yet."""
    turns = rec.turns
    known = frozenset(registered)
    false_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    for t in turns:
        signal = _false_claim(t)
        if signal:
            caps = [c for c in claims.CAPABILITIES if c.key in signal["capabilities"]]
            hinted = any(c.get("hinted") for c in t.claims)
            false_rows.append({"turn_id": t.turn_id, "question": t.question or t.raw_text, "answer": t.answer, "what": "; ".join(c.what for c in caps) or ", ".join(signal["capabilities"]), "tools": signal["composable_via"], "attempted": (", ".join(x.tool for x in t.tools) or "nothing") + (" (the prompt named the capability)" if hinted else "")})
        matched = [c for c in claims.match_capabilities(t.question) if all(x in known for x in c.tools)]
        if matched:
            wanted = {x for c in matched for x in c.tools}
            tried = [x for x in t.tools if x.tool in wanted]
            broken = [x for x in tried if x.outcome not in ("ok", "staged")]
            if tried and broken and not any(x.outcome in ("ok", "staged") for x in tried):
                failed_rows.append({"turn_id": t.turn_id, "question": t.question, "what": "; ".join(c.what for c in matched), "detail": "; ".join(f"{x.tool}: {x.outcome} {x.error[:80]}".strip() for x in broken[:3])})
    workflows: Counter = Counter()
    workflow_turns: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for t in turns:
        names = tuple(x.tool for x in t.tools if x.outcome in ("ok", "staged"))
        if len(names) >= 2:
            workflows[names] += 1
            workflow_turns[names].append(t.turn_id)
    dimensions: Counter = Counter()
    dimension_turns: dict[str, list[str]] = defaultdict(list)
    for t in turns:
        for r in t.rejected:
            for name in r.get("unknown") or []:
                dimensions[str(name)] += 1
                dimension_turns[str(name)].append(t.turn_id)
    actions: Counter = Counter()
    action_turns: dict[str, list[str]] = defaultdict(list)
    for t in turns:
        for x in t.tools:
            if x.missing_capability:
                actions[x.missing_capability] += 1
                action_turns[x.missing_capability].append(t.turn_id)
    bulk: dict[str, dict[str, Any]] = {}
    for t in turns:
        req = claims.bulk_request(t.question)
        if req is None:
            continue
        served = any(x.tool.startswith("batch_") and x.outcome == "staged" for x in t.tools) or any(b.get("event") == "PROPOSED" for b in t.batches)
        entry = bulk.setdefault(req["operation"], {"n": 0, "turns": [], "supported": bool(req["supported"]), "served": 0})
        entry["n"] += 1
        entry["turns"].append(t.turn_id)
        entry["served"] += 1 if served else 0
    follow_ups: Counter = Counter()
    follow_up_turns: dict[str, list[str]] = defaultdict(list)
    previous: dict[str, Turn] = {}
    for t in turns:
        shape = claims.follow_up_shape(t.question)
        if shape and previous.get(t.session_id) is not None:
            follow_ups[shape] += 1
            follow_up_turns[shape].append(t.turn_id)
        previous[t.session_id] = t
    ui_types: Counter = Counter()
    ui_turns: dict[str, list[str]] = defaultdict(list)
    for t in turns:
        for r in t.tablet_events("render"):
            for kind in r.get("skipped") or []:
                ui_types[str(kind)] += 1
                ui_turns[str(kind)].append(t.turn_id)
        entity_results = [x for x in t.tools if x.outcome == "ok" and x.result and any(k in x.result for k in ("rows", "orders", "customers", "threads", "products"))]
        if entity_results and not [u for u in t.ui if u not in ("assistant", "error", "context_stack")]:
            ui_types["(records without a card)"] += 1
            ui_turns["(records without a card)"].append(t.turn_id)
    sets_made = [e for t in turns for e in t.sets if e.get("kind") == "working_set"]
    cross = [e for t in turns for e in t.sets if e.get("kind") == "cross_source"]
    batches = {str(e.get("batch_id")): e for t in turns for e in t.batches if e.get("event") == "DONE"}
    # §27C and the detections §27 asks for, each from the turn's own record.
    spoken: dict[str, dict[str, Any]] = {}
    for t in turns:
        found = _spoken_capability(t, capability_states)
        if found is None:
            continue
        if found["state"] == "READY":
            continue      # a capability that is here and works is neither a build nor a grant
        entry = spoken.setdefault(found["change"], {"what": found["what"], "state": found["state"], "scope": found["scope"],
                                                    "family": found["family"], "n": 0, "turns": []})
        entry["n"] += 1
        entry["turns"].append(t.turn_id)
    new_actions: list[tuple[str, int, list[str], str]] = []
    for key, entry in sorted(spoken.items(), key=lambda kv: -kv[1]["n"]):
        if entry["state"] != _no_family():
            continue
        # A change nothing claims AND no intent family takes: a family to add, not a scope
        # to grant. `verdict.unplaced` is the router's own answer to "is there a family".
        unplaced = [t.turn_id for t in turns if t.verdict is not None and t.verdict.change is not None
                    and t.verdict.change.key == key and t.verdict.unplaced]
        new_actions.append((key, entry["n"], entry["turns"][:5], f"{entry['what']}; no intent family took {len(unplaced)} of {entry['n']} request(s)"))
    read_gaps: dict[str, dict[str, Any]] = {}
    for t in turns:
        v = t.verdict
        if v is None or v.mutation or not v.unplaced or not (t.question or "").strip():
            continue
        shape = f"{t.cluster}: " + " ".join((t.question or "").lower().split()[:4])
        why = v.disagreement or v.reason or "no family matched"
        entry = read_gaps.setdefault(shape, {"n": 0, "turns": [], "reason": why})
        entry["n"] += 1
        entry["turns"].append(t.turn_id)
    relations = [(t.turn_id, sig) for t in turns for sig in t.signals if "surface drew no order" in sig]
    branch_rows = _branch_failures(rec)
    corrections = _corrections(turns)
    precision = _precision_input(turns)
    cross_rows = _cross_source_workflows(turns)
    reached = sorted({str((t.lane or {}).get("family") or "") for t in turns if (t.lane or {}).get("family")})
    uncovered = _uncovered_families(reached)
    return {
        "false_unsupported": false_rows,
        "composable_failed": failed_rows,
        "workflows": [(names, n, workflow_turns[names][:5]) for names, n in workflows.most_common(10)],
        "dimensions": [(name, n, dimension_turns[name][:5]) for name, n in dimensions.most_common(10)],
        "new_actions": [(name, n, action_turns[name][:5]) for name, n in actions.most_common(10)],
        "spoken_capabilities": [(key, e["n"], e["turns"][:5], e["state"], e["scope"], e["what"]) for key, e in sorted(spoken.items(), key=lambda kv: -kv[1]["n"])],
        "new_action_families": new_actions,
        "new_read_families": [(shape, e["n"], e["turns"][:5], e["reason"]) for shape, e in sorted(read_gaps.items(), key=lambda kv: -kv[1]["n"])],
        "relation_gaps": relations,
        "branch_failures": branch_rows,
        "corrections": corrections,
        "precision_input": precision,
        "cross_source_workflows": cross_rows,
        "families_reached": reached,
        "families_uncovered": uncovered,
        "bulk": [(op, e["n"], e["turns"][:5], e["supported"] and e["served"] > 0) for op, e in sorted(bulk.items(), key=lambda kv: -kv[1]["n"])],
        "follow_ups": [(shape, n, follow_up_turns[shape][:6]) for shape, n in follow_ups.most_common()],
        "ui_types": [(kind, n, ui_turns[kind][:5]) for kind, n in ui_types.most_common(10)],
        "sets": {"made": len(sets_made), "derived": sum(1 for e in sets_made if e.get("parent")), "by_step": dict(Counter(str(e.get("step")) for e in sets_made)), "cross_source": len(cross)},
        "batches": {"done": len(batches), "counts": {k: sum(int((e.get("counts") or {}).get(k) or 0) for e in batches.values()) for k in ("requested", "eligible", "excluded", "verified", "failed", "stale", "unverified", "not_attempted")}},
    }


def render(rec: Reconstruction, *, tools_registered: list[str] | None = None,
           capability_states: dict[str, dict[str, Any]] | None = None) -> str:
    """The Markdown. `capability_states` is `app.capabilities.families.states(runtime)` when
    the caller has a runtime: with it, a change asked for is held against the store's own
    scopes rather than against the family's declared state, so the report can say MISSING_SCOPE
    and name the scope. Without one the declared state is used and the report says so."""
    registered = tools_registered if tools_registered is not None else registered_tools()
    turns = rec.turns
    session = rec.session
    lines: list[str] = []
    add = lines.append

    add(f"# CROOKS OS test session — {session.get('test_session_id') or 'unknown'}")
    add("")
    add(f"Name: **{session.get('name') or '—'}**. Written from the timeline alone; every number below is a count or a measurement, and the rules that file a turn under a failure class are the ones named in section 5.")
    add("")

    # 1 ------------------------------------------------------------------------------
    add("## 1. Session summary")
    add("")
    duration = session.get("duration_s")
    if duration is None and turns:
        duration = (turns[-1].finished_at or turns[-1].started_at) - turns[0].started_at
    counts = Counter(t.outcome for t in turns)
    add(f"- Started {_clock(session.get('started_at'))}, stopped {_clock(session.get('stopped_at'))}; duration {(_fmt_s(duration))}.")
    add(f"- Interactions: **{len(turns)}** turns across {len({t.session_id for t in turns})} conversation(s); {sum(len(t.tools) for t in turns)} tool calls; {len(rec.proposals)} proposals.")
    add(f"- Successful **{counts.get('successful', 0)}** · partial **{counts.get('partial', 0)}** · failed **{counts.get('failed', 0)}** — "
        "by what the BACKEND did, which is the number the September report gave and the one that was wrong.")
    experience = rec.experience
    if experience is not None:
        lived = Counter(t.experience for t in turns)
        add(f"- **As the owner lived it: successful {lived.get('SUCCESSFUL', 0)} · partial {lived.get('PARTIAL', 0)} · "
            f"failed {lived.get('FAILED', 0)}.** A turn is not successful because the change verified; "
            "section 16 gives both outcomes per turn.")
        if experience.ignored_feedback:
            add(f"- **{len(experience.ignored_feedback)} defect(s) the owner reported out loud that nothing recorded** "
                "— section 15.")
        elif experience.feedback:
            add(f"- {len(experience.feedback)} defect(s) the owner reported out loud, recorded — section 15.")
    add(f"- By input: {dict(Counter(t.input or 'unknown' for t in turns))}. Events: {len(rec.events)} ({sum(1 for e in rec.events if e.get('source') == 'tablet')} from the tablet).")
    if rec.unknown_kinds:
        add(f"- Event kinds this report does not read: {dict(rec.unknown_kinds)}.")
    add("")
    add("Outcome rule: a turn with no failure class is successful; one with a class but an answered request (a tool that returned, a card, a verified change) is partial; otherwise failed. A request for something the assistant does not have is failed, and listed in section 6.")
    add("")

    # 2 ------------------------------------------------------------------------------
    add("## 2. Performance")
    add("")
    rows = []
    parts = [("audio", "Audio length"), ("stt", "Speech to text"), ("claude", "Claude"), ("shopify", "Shopify (per turn, summed)"), ("gmail", "Gmail (per turn, summed)"), ("context", "Context hydration"),
             # The three that separate a slow model from slow reads (app/routes/turn.py).
             ("facts", "Facts in hand"), ("workspace", "Cards existed"), ("prose_wait", "Waited after the facts"),
             ("tts_first_byte", "TTS to first byte"), ("total", "Total turn (Mac)"), ("round_trip", "Total turn (tablet round trip)")]
    for key, label in parts:
        values = [v for v in (t.latency(key) for t in turns) if v is not None]
        avg, med, p95 = _stats(values)
        rows.append([label, len(values), avg, med, p95])
    lines.extend(_table(["Stage", "Samples", "Average", "Median", "P95"], rows))
    facts = [v for v in (t.latency("facts") for t in turns) if v is not None]
    waited = [v for v in (t.latency("prose_wait") for t in turns) if v is not None]
    if facts or waited:
        add("**Reads against prose.** `Facts in hand` is when the Mac held the data the cards are drawn from; "
            "`Waited after the facts` is what the owner waited for a sentence about data already read. "
            f"Summed across the session: {sum(facts):,.0f} ms reading, {sum(waited):,.0f} ms waiting — "
            + ("the waiting dominates, and the fix is in the prompt and the lane, not in the reads."
               if sum(waited) > sum(facts) else "the reads dominate, and the fix is in the read layer, not in the prompt.")
            )
        add("")
    slowest = sorted((t for t in turns if t.latency("total") is not None), key=lambda t: -(t.latency("total") or 0))[:10]
    add("The ten slowest turns:")
    add("")
    lines.extend(_table(["Turn", "Total", "STT", "Claude", "Shopify", "Gmail", "TTS first byte", "Request"], [
        [t.turn_id, _fmt_ms(t.latency("total")), _fmt_ms(t.latency("stt")), _fmt_ms(t.latency("claude")), _fmt_ms(t.latency("shopify")), _fmt_ms(t.latency("gmail")), _fmt_ms(t.latency("tts_first_byte")), t.question] for t in slowest
    ]))

    # 3 ------------------------------------------------------------------------------
    add("## 3. Requests")
    add("")
    by_cluster: dict[str, list[Turn]] = defaultdict(list)
    for t in turns:
        by_cluster[t.cluster].append(t)
    for name in [c[0] for c in CLUSTERS] + ["other"]:
        group = by_cluster.get(name) or []
        if not group:
            continue
        add(f"### {name} — {len(group)}")
        add("")
        lines.extend(_table(["Turn", "Outcome", "Request", "Tools"], [[t.turn_id, t.outcome, t.question or t.raw_text, ", ".join(f"{x.tool}:{x.outcome or '?'}" for x in t.tools) or "—"] for t in group]))

    # 4 ------------------------------------------------------------------------------
    add("## 4. Tool usage")
    add("")
    per_tool: dict[str, list[ToolRecord]] = defaultdict(list)
    for t in turns:
        for x in t.tools:
            per_tool[x.tool].append(x)
    rows = []
    for name in sorted(per_tool):
        calls = per_tool[name]
        ok = sum(1 for c in calls if c.outcome in ("ok", "staged"))
        ms = [c.ms for c in calls if isinstance(c.ms, (int, float))]
        failures = [f"{c.turn_id}: {c.outcome} {c.error[:50]}".strip() for c in calls if c.outcome not in ("ok", "staged")]
        rows.append([name, len(calls), f"{100 * ok / len(calls):.0f}%", _fmt_ms(statistics.fmean(ms)) if ms else "—", "; ".join(failures) or "—"])
    lines.extend(_table(["Tool", "Calls", "Success", "Avg latency", "Failures"], rows))

    # 5 ------------------------------------------------------------------------------
    add("## 5. Failures")
    add("")
    add("Classes, in the order tested: " + ", ".join(CLASSES) + ". A turn may carry more than one. "
        "GESTURE_COLLISION: the recording produced nothing and a second finger, a split or a fork is on the timeline within "
        f"{GESTURE_WINDOW_S:.0f} s of it — the touch handling ended the recording, and the recogniser never had any speech to lose. "
        "UI_RELATION_MISSING: an email surface was drawn with no order on it in a turn whose own data held one; the relation existed and the screen did not carry it. "
        "STT_ERROR: the recogniser returned no usable text, with no gesture to explain it. TIMEOUT: the turn, a tool or the tablet gave up. PERMISSION_ERROR: a tap refused by the write boundary. MISSING_CAPABILITY: a tool asked for that is not registered, or an answer that says it cannot with no tool having succeeded. TOOL_ERROR: a tool raised or returned an error. VERIFICATION_ERROR: a change sent but not proven. TOOL_SELECTION_ERROR: repeated calls with unissued ids, a rule refusal, or the same call twice. UI_RENDER_ERROR: a tablet exception, a card it could not draw, a failed image. UI_NAVIGATION_PROBLEM: the screen left within three seconds, or a touch on something dead. CONTEXT_INCOMPLETE: part of the order never arrived. INTENT_ERROR: a clarifying question though the request named its entity. UNKNOWN: an error nothing above explains.")
    add("")
    add("The last fifteen are what the OWNER could see rather than what the server did "
        "(`app/observability/visible.py`), and they are why this report's numbers differ from the "
        "September one's. " + " ".join(f"{name}: {visible.TASKS[name].split('.')[0]}." for name in visible.CLASSES))
    add("")
    # Every turn the owner did not get what he wanted — which is not the same set as the turns
    # the backend failed, and that difference is the whole of §17.
    failed = [t for t in turns if t.outcome != "successful" or t.experience != "SUCCESSFUL"]
    rows = []
    for t in failed:
        rows.append([t.turn_id, t.raw_text, t.question if t.question != t.raw_text else "(same)", t.answer, ", ".join(f"{x.tool}:{x.outcome or '?'}" for x in t.tools) or "—", "; ".join(t.signals), ", ".join(c.get("type", "") for c in ((t.render or {}).get("cards") or [])) or ", ".join(t.ui) or "—", ", ".join(t.classes), f"{t.backend} / {t.visible} / {t.experience}"])
    lines.extend(_table(["Turn", "Owner said", "Normalised", "Assistant answered", "Tools attempted", "Technical reason", "UI displayed", "Class", "backend / visible / experience"], rows))
    add("By class: " + (", ".join(f"{k} × {v}" for k, v in Counter(c for t in failed for c in t.classes).most_common()) or "none") + ".")
    add("")

    # 6 ------------------------------------------------------------------------------
    add("## 6. Unsupported requests")
    add("")
    asked: dict[str, list[Turn]] = defaultdict(list)
    cannot: list[Turn] = []
    for t in turns:
        names = {x.missing_capability for x in t.tools if x.missing_capability}
        for name in names:
            asked[name].append(t)
        if not names and "MISSING_CAPABILITY" in t.classes:
            cannot.append(t)
    if asked:
        rows = [[name, f"requested {len(group)} time(s)", ", ".join(x.turn_id for x in group[:4]), _closest_capability(name, registered)] for name, group in sorted(asked.items(), key=lambda kv: -len(kv[1]))]
        lines.extend(_table(["Capability asked for", "Frequency", "Turns", "Closest existing capability"], rows))
        for name, group in sorted(asked.items(), key=lambda kv: -len(kv[1])):
            for t in group[:3]:
                add(f"- `{name}` — {t.turn_id}: owner said “{_cell(t.raw_text, 120)}”; assistant answered “{_cell(t.answer, 160)}”.")
        add("")
    if cannot:
        add("Answers that declined without naming a tool:")
        add("")
        lines.extend(_table(["Turn", "Owner said", "Assistant answered", "Closest existing capability"], [[t.turn_id, t.raw_text, t.answer, _closest_capability(t.question.lower(), registered)] for t in cannot]))
    if not asked and not cannot:
        add("_none_")
        add("")

    # 7 ------------------------------------------------------------------------------
    add("## 7. UI usage")
    add("")
    renders = [e for t in turns for e in t.tablet_events("render")] + [e for e in rec.orphans if e.get("kind") == "tablet_render"]
    screens = Counter(str(r.get("screen") or "") for r in renders)
    card_types = Counter(str(c.get("type") or "") for r in renders for c in (r.get("cards") or []) if isinstance(c, dict))
    sections = Counter(s for r in renders for c in (r.get("cards") or []) if isinstance(c, dict) for s in (c.get("sections") or []))
    tabs_rendered = Counter(s for r in renders for c in (r.get("cards") or []) if isinstance(c, dict) for s in (c.get("tabs") or []))
    tab_taps = Counter(str(e.get("label") or "") for t in turns for e in t.tablet_events("tab"))
    exposed: Counter = Counter()
    disabled: Counter = Counter()
    for r in renders:
        for c in r.get("cards") or []:
            for a in (c.get("actions") or []) if isinstance(c, dict) else []:
                if isinstance(a, dict):
                    (exposed if a.get("enabled") else disabled)[str(a.get("id") or "")] += 1
    used: Counter = Counter()
    for t in turns:
        for e in t.tablet_events("rail_tap"):
            used[str(e.get("action") or "")] += 1
        for e in t.tablet_events("action_primed"):
            used[str(e.get("action") or "")] += 1
    nav = Counter(str(e.get("nav") or "") for t in turns for e in t.tablet_events("navigate"))
    nav.update(str(e.get("nav") or "") for e in rec.orphans if e.get("kind") == "tablet_navigate")
    add(f"- Screens rendered: {dict(screens) or '—'}; cards: {dict(card_types) or '—'}.")
    add(f"- Sections shown on cards: {dict(sections) or '—'}; tab controls: {dict(tabs_rendered) or 'none rendered'}; tabs tapped: {dict(tab_taps) or 'none'}.")
    add(f"- Rail actions exposed (enabled): {dict(exposed) or '—'}; shown disabled: {dict(disabled) or '—'}; actually used: {dict(used) or 'none'}.")
    unused = sorted(set(exposed) - set(used))
    if unused:
        add(f"- **Exposed but never used:** {', '.join(unused)}.")
    staged_ops = Counter(p.operation for p in rec.proposals.values() if not p.undo_of)
    not_shown = [op for op in staged_ops if RAIL_BY_OPERATION.get(op) and RAIL_BY_OPERATION[op] not in exposed]
    if not_shown:
        add(f"- **Asked for by voice but never offered on the rail:** {', '.join(f'{op} ×{staged_ops[op]}' for op in not_shown)}.")
    add(f"- Navigation: {dict(nav) or 'none recorded'}.")
    abandoned = [t.turn_id for t in turns if _abandoned(t)]
    if abandoned:
        add(f"- **Screens left within {ABANDON_S:.0f} s:** {', '.join(abandoned)}.")
    images = [e for t in turns for e in t.tablet_events("image_failed")] + [e for e in rec.orphans if e.get("kind") == "tablet_image_failed"]
    if images:
        add(f"- **Failed image loads:** {len(images)} — {dict(Counter(str(e.get('src') or '') for e in images))}.")
    clipped = [(t.turn_id, c.get("type"), c.get("clipped_x")) for t in turns for r in t.tablet_events("render") for c in (r.get("cards") or []) if isinstance(c, dict) and c.get("clipped_x")]
    if clipped:
        add(f"- **Clipping / horizontal overflow:** {clipped}.")
    long_scroll = [(t.turn_id, (r.get("document") or {}).get("cards_height"), (r.get("document") or {}).get("cards_visible")) for t in turns for r in t.tablet_events("render") if (r.get("overflow") or {}).get("long_scroll")]
    if long_scroll:
        add(f"- **Long scroll surfaces** (cards taller than the view; turn, height, visible): {long_scroll}.")
    scrolls = [e for t in turns for e in t.tablet_events("scroll")]
    if scrolls:
        add(f"- Scrolling: {len(scrolls)} scroll report(s); deepest {max(int(e.get('depth') or 0) for e in scrolls)} px.")
    viewports = {f"{(r.get('viewport') or {}).get('w')}×{(r.get('viewport') or {}).get('h')}@{(r.get('viewport') or {}).get('dpr')}" for r in renders}
    if viewports:
        add(f"- Viewports seen: {', '.join(sorted(viewports))}.")
    exceptions = [e for t in turns for e in t.tablet_events("exception")] + [e for e in rec.orphans if e.get("kind") == "tablet_exception"]
    if exceptions:
        add(f"- **Frontend exceptions:** {len(exceptions)} — " + "; ".join(_cell(e.get("message"), 100) for e in exceptions[:5]) + ".")
    connectivity = [e for t in turns for e in t.tablet_events("connectivity")] + [e for e in rec.orphans if e.get("kind") == "tablet_connectivity"]
    if connectivity:
        add(f"- Connectivity: {dict(Counter(str(e.get('state')) for e in connectivity))}.")
    add("")

    # 8 ------------------------------------------------------------------------------
    add("## 8. Action engine")
    add("")
    rows = []
    for p in sorted(rec.proposals.values(), key=lambda p: p.staged_at or 0):
        rows.append([
            p.proposal_id, p.turn_id or "—", p.operation + (" (undo)" if p.undo_of else ""), p.risk, p.interaction, "yes" if p.staged_at else "no",
            "yes" if p.committed else "no", {True: "yes", False: "no", None: "—"}[p.verified], p.status + (f" / {p.code}" if p.code else ""), _fmt_ms(p.latency_ms), p.reason or (p.refusals[-1].get("code") if p.refusals else "") or "—",
        ])
    lines.extend(_table(["Proposal", "Turn", "Operation", "Risk", "Gesture", "Staged", "Committed", "Verified", "Outcome", "Latency", "Failure reason"], rows))
    discrepancies = []
    for p in rec.proposals.values():
        attempted = [e for e in p.tablet if e.get("kind") == "tablet_action_commit"]
        shown_unavailable = [e for e in p.tablet if e.get("kind") == "tablet_render" and any(isinstance(c, dict) and c.get("proposal_id") == p.proposal_id and (c.get("surface") or {}).get("state") == "unavailable" for c in e.get("cards") or [])]
        if p.refusals and attempted:
            discrepancies.append(f"{p.proposal_id}: the tablet tried ({len(attempted)}×) and the Mac refused ({', '.join(str(r.get('code')) for r in p.refusals)})")
        if attempted and not p.committed and not p.refusals:
            discrepancies.append(f"{p.proposal_id}: the tablet reported a commit the Mac never claimed")
        if p.committed and not attempted and p.tablet:
            discrepancies.append(f"{p.proposal_id}: committed on the Mac with no tablet commit event")
        if shown_unavailable:
            discrepancies.append(f"{p.proposal_id}: shown as unavailable on the tablet")
        if p.status == "EXPIRED" and p.armed:
            discrepancies.append(f"{p.proposal_id}: armed by a hold, then expired")
    revoked = [p for p in rec.proposals.values() if p.status == "REVOKED"]
    if revoked:
        add("Withdrawn: " + "; ".join(f"{p.proposal_id} ({p.reason or 'no reason recorded'})" for p in revoked) + ".")
        add("")
    add("Displayed / available / attempted discrepancies: " + ("; ".join(discrepancies) if discrepancies else "none") + ".")
    add("")

    # 9 ------------------------------------------------------------------------------
    add("## 9. Context quality")
    add("")
    already = []
    for t in turns:
        if t.prefetch and t.prefetch.get("hit") and any(x.tool == "shopify_order_detail" and x.outcome == "ok" for x in t.tools) and t.prefetch.get("hydrating"):
            already.append(t.turn_id)
        for x in t.tools:
            if x.tool == "shopify_find_order" and t.prefetch and t.prefetch.get("hit") and x.requested_at > float(t.prefetch.get("ts") or 0):
                already.append(f"{t.turn_id} (find_order after the Mac had run it)")
    history_missing = [t.turn_id for t in turns if any("history" in (h.get("unavailable") or []) for h in t.hydrations)]
    email_missing = [t.turn_id for t in turns if any("email" in (h.get("unavailable") or []) for h in t.hydrations)]
    incomplete = [t.turn_id for t in turns if any(h.get("pending") for h in t.hydrations if h.get("hydration") == "order") and not t.tablet_events("context_landed")]
    duplicates = [(t.turn_id, _duplicate_calls(t.tools)) for t in turns if _duplicate_calls(t.tools)]
    add(f"- Claude asked for what the Mac had already read: {', '.join(already) or 'never'}.")
    add(f"- Customer history missing from an order's context: {', '.join(history_missing) or 'never'}.")
    add(f"- Email correlation missing FROM THE DATA (the hydration could not read it): {', '.join(email_missing) or 'never'}.")
    # The other half of the same question, and the one the live session's report got wrong:
    # the data had the correlation and the screen did not show it.
    relation_gaps = [t.turn_id for t in turns if "UI_RELATION_MISSING" in t.classes]
    add(f"- Email correlation missing FROM THE SURFACE (the card drew no order though the turn held one): {', '.join(relation_gaps) or 'never'}.")
    add("  Read from the card's own `relations` — the tappable link targets inside it — and never from what a tool returned: backend data existing is not a visible relationship existing.")
    add(f"- Order context still incomplete when the answer left, and not collected later: {', '.join(incomplete) or 'never'}.")
    add(f"- Duplicate tool calls: {duplicates or 'none'}.")
    hydrations = [h for t in turns for h in t.hydrations]
    if hydrations:
        reused = sum(1 for h in hydrations if h.get("reused_core"))
        add(f"- Hydrations: {len(hydrations)} ({reused} reused a recent read); by kind {dict(Counter(str(h.get('hydration')) for h in hydrations))}.")
    add("")

    # 10 -----------------------------------------------------------------------------
    add("## 10. Response quality")
    add("")
    add("Deterministic signals only: word matching against the registered tools and the previous answer, never a judgement of tone or correctness.")
    add("")
    rows = []
    for t in turns:
        answer = t.answer
        if not answer:
            continue
        if CANNOT_RE.search(answer):
            named = [tool for word, tool in CAPABILITY_WORDS.items() if word in t.question.lower() and tool in registered]
            if named:
                rows.append([t.turn_id, "says it cannot, though a registered tool can", ", ".join(sorted(set(named)))])
        if OFFER_GESTURE_RE.search(answer) and not t.proposals:
            rows.append([t.turn_id, "offers a card or a gesture, but no change was staged", _cell(answer, 100)])
        if "repeats the previous answer" in t.signals:
            rows.append([t.turn_id, "repeats most of the previous answer", _cell(answer, 100)])
        entity_results = [x for x in t.tools if x.outcome == "ok" and x.result and any(k in x.result for k in ("order_id", "customer_id", "thread_id", "orders", "customers", "threads", "products"))]
        if entity_results and not [u for u in t.ui if u not in ("assistant", "error", "context_stack")]:
            rows.append([t.turn_id, "a tool returned records but no structured card was shown", ", ".join(x.tool for x in entity_results)])
    lines.extend(_table(["Turn", "Signal", "Detail"], rows))

    # 11 -----------------------------------------------------------------------------
    add("## 11. Anticipation")
    add("")
    attention_turns = [t for t in turns if "attention" in t.ui or ((t.render or {}).get("attention"))]
    opens = [e for t in turns for e in t.tablet_events("navigate") if e.get("nav") == "attention_open"] + [e for e in rec.orphans if e.get("kind") == "tablet_navigate" and e.get("nav") == "attention_open"]
    add(f"- Attention surfaces shown: {len(attention_turns)} turn(s) ({', '.join(t.turn_id for t in attention_turns) or '—'}); items on the last: {((attention_turns[-1].render or {}).get('attention') if attention_turns else 0) or 0}.")
    add(f"- Opened by the owner: {len(opens)} time(s).")
    if opens:
        later = []
        for e in opens:
            t0 = float(e.get("t") or 0) / 1000
            after = [p for p in rec.proposals.values() if p.staged_at and p.staged_at >= t0 and p.staged_at - t0 <= 600 and not p.undo_of]
            later.append(f"{len(after)} change(s) proposed within ten minutes" if after else "no change followed within ten minutes")
        add("- Relevance to later actions: " + "; ".join(later) + ".")
    add("")

    # 12 -----------------------------------------------------------------------------
    add("## 12. Top improvement opportunities")
    add("")
    add("Ranked by what engineering should do FIRST: severity decides the order, and frequency "
        f"decides within a severity — `severity × min(distinct turns, {RANK_CAP}) × confidence`, "
        f"with an inferred class discounted to {INFERRED_CONFIDENCE}. The three numbers are printed "
        "beside each row so the order can be disagreed with. The 11 September report ranked on "
        "occurrences alone, which put a severity-2 guess multiplied by 62 swallowed control taps "
        "above every P0 in the session.")
    add("")
    opportunities = _opportunities(rec, turns, registered, capability_states)
    if not opportunities:
        add("_Nothing in this session's evidence calls for a change._")
    for i, o in enumerate(opportunities, 1):
        add(f"{i}. **{o['problem']}** — {o['frequency']}; severity {o['severity']}/5; "
            f"rank {o['weight']} ({o.get('basis') or 'severity × sites'}); "
            f"e.g. {', '.join(o['examples']) or '—'}. Likely component: {o['component']}. "
            f"Task: {o['task']}")
    add("")

    # 13 -----------------------------------------------------------------------------
    add("## 13. Intelligence")
    add("")
    add("What the session asked of the read layer, the working sets and the batch tools, and what it asked for that does not exist yet. Every row names its turns; the rules are word matches (app/observability/claims.py) and counts, never a judgement.")
    add("")
    intel = intelligence(rec, registered, capability_states=capability_states)
    add("### False unsupported claims")
    add("")
    add("The assistant said it could not, and the tools registered on this Mac compose exactly that.")
    add("")
    lines.extend(_table(["Turn", "Owner said", "Assistant answered", "Composable as", "Via", "Attempted"], [[r["turn_id"], r["question"], r["answer"], r["what"], ", ".join(r["tools"]), r["attempted"]] for r in intel["false_unsupported"]]))
    hinted = sum(1 for r in intel["false_unsupported"] if "the prompt named" in r["attempted"])
    if intel["false_unsupported"]:
        add(f"{len(intel['false_unsupported']) - hinted} declined unaided; {hinted} declined after the Mac named the capability on the prompt (a prompted decline is the model's, not the prompt's).")
        add("")
    add("### Composable but failed requests")
    add("")
    lines.extend(_table(["Turn", "Owner said", "Composable as", "What failed"], [[r["turn_id"], r["question"], r["what"], r["detail"]] for r in intel["composable_failed"]]))
    add("### Common multi-tool workflows")
    add("")
    lines.extend(_table(["Workflow", "Times", "Turns"], [[" → ".join(names), n, ", ".join(ids)] for names, n, ids in intel["workflows"]]))
    add("### Potential new query dimensions")
    add("")
    add("Asked of the query language and refused as unknown.")
    add("")
    lines.extend(_table(["Dimension", "Times", "Turns"], [[name, n, ", ".join(ids)] for name, n, ids in intel["dimensions"]]))
    add("### Potential new actions")
    add("")
    add("Two tables. The first is what a TOOL asked for and did not find — a capability the model reached for. "
        "The second is what the OWNER asked for out loud, which reaches no tool at all when the assistant declines it in words, "
        "and is why an hour that asked three times for changes this Mac cannot make reported \"none\" here.")
    add("")
    lines.extend(_table(["Capability a tool asked for", "Times", "Turns"], [[name, n, ", ".join(ids)] for name, n, ids in intel["new_actions"]]))
    add("Asked for in words, held against the capability table (`app/capabilities/families.py`). "
        + ("The store's own scopes were read for this report." if capability_states else "No runtime was available, so each family's DECLARED state is shown; a family with a probe is settled against the store, not here.")
        )
    add("")
    lines.extend(_table(["Change asked for", "Times", "Turns", "Capability state", "Scope named"], [
        [what, n, ", ".join(ids), state, scope or "—"] for _key, n, ids, state, scope, what in intel["spoken_capabilities"]
    ]))
    add("### Possible new action families")
    add("")
    add("A change nothing on this Mac claims AND no intent family takes: a family to add (`app/families/`), not a scope to grant.")
    add("")
    lines.extend(_table(["Change", "Times", "Turns", "What the router did with it"], [[name, n, ", ".join(ids), why] for name, n, ids, why in intel["new_action_families"]]))
    add("### Possible new read families")
    add("")
    add("A question the router placed in no family, so the model took it. Grouped by what was asked; the reason is the router's own.")
    add("")
    lines.extend(_table(["Request shape", "Times", "Turns", "Why no family"], [[shape, n, ", ".join(ids), why] for shape, n, ids, why in intel["new_read_families"]]))
    add("### UI component gaps")
    add("")
    lines.extend(_table(["Gap", "Turn"], [["an email surface drew no order though the turn held one", tid] for tid, _sig in intel["relation_gaps"]]))
    add("### Branch (split orb) UX failures")
    add("")
    lines.extend(_table(["Branch", "What happened", "What was read"], [[b, what, detail] for b, what, detail in intel["branch_failures"]]))
    add("### Precision input needed")
    add("")
    lines.extend(_table(["Turn", "What needed to be exact", "Detail"], [[tid, what, detail] for tid, what, detail in intel["precision_input"]]))
    add("### Repeated corrections")
    add("")
    lines.extend(_table(["Turn", "Pattern", "Request"], [[tid, what, said] for tid, what, said in intel["corrections"]]))
    add("### Repeated cross-source workflows")
    add("")
    lines.extend(_table(["Workflow", "Times", "Turns"], [[shape, n, ", ".join(ids)] for shape, n, ids in intel["cross_source_workflows"]]))
    if intel["families_reached"]:
        add(f"Intent families this session reached: {', '.join(intel['families_reached'])}. "
            + (f"**Reached and covered by no golden scenario:** {', '.join(intel['families_uncovered'])}." if intel["families_uncovered"] else "Every one of them is covered by a golden scenario.")
            )
        add("")
    add("### Bulk workflows requested")
    add("")
    lines.extend(_table(["Change, in bulk", "Times", "Turns", "A batch exists and was staged"], [[op, n, ", ".join(ids), "yes" if served else "no"] for op, n, ids, served in intel["bulk"]]))
    add("### Repeated follow-up patterns")
    add("")
    lines.extend(_table(["Shape", "Times", "Turns"], [[shape, n, ", ".join(ids)] for shape, n, ids in intel["follow_ups"]]))
    add("### Potential UI components")
    add("")
    lines.extend(_table(["Card type", "Times", "Turns"], [[kind, n, ", ".join(ids)] for kind, n, ids in intel["ui_types"]]))
    sets_info = intel["sets"]
    add(f"Working sets: {sets_info['made']} made ({sets_info['derived']} derived), by step {sets_info['by_step'] or '—'}; cross-source reads: {sets_info['cross_source']}. Batches run: {intel['batches']['done']}; members counted {intel['batches']['counts']}.")
    add("")
    # 14 -----------------------------------------------------------------------------
    add("## 14. Touch, commands and branches")
    add("")
    add("What was TAPPED, from the Mac's own `command` events and the branch moves beside them. "
        "The live session wrote twenty-seven of these and the report read none of them, so an hour spent on a tablet said nothing about the tablet's own controls.")
    add("")
    commands = [e for e in rec.controls if str(e.get("kind") or "") == "command"]
    by_command: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in commands:
        by_command[str(event.get("command") or "?")].append(event)
    rows = []
    for name in sorted(by_command):
        group = by_command[name]
        refused = [e for e in group if e.get("ok") is False]
        ms = [float(e["ms"]) for e in group if isinstance(e.get("ms"), (int, float))]
        rows.append([name, len(group), len(group) - len(refused), _fmt_ms(statistics.fmean(ms)) if ms else "—",
                     ", ".join(sorted({str(e.get("code") or "?") for e in refused})) or "—"])
    lines.extend(_table(["Command", "Posted", "Accepted", "Avg latency", "Refusal codes"], rows))
    staged = [e for e in rec.controls if str(e.get("kind") or "") == "command_stage"]
    rows_actions = [e for e in rec.controls if str(e.get("kind") or "") == "row_action"]
    branch_moves = Counter(str(e.get("kind") or "") for e in rec.controls if str(e.get("kind") or "").startswith("branch_"))
    add(f"- Changes prepared by a tap (`command_stage`): {len(staged)} ({sum(1 for e in staged if e.get('ok') is False)} refused). Row actions: {len(rows_actions)}.")
    add("")
    add("### What each finger actually did")
    add("")
    add("§21. Four classes where the 11 September report had one bucket. It counted 62 "
        "`recording_too_short` events as \"a value had to be exact and a voice could not make it "
        "so\" and made the precision-input path its first improvement candidate and speech its "
        "second. A short touch is one of four different things, and which one it was decides "
        "which file the defect is in — `web/style.css`, `web/app.js`, `app/speech`, or the "
        "composer. The rule and its false-positive risk are in `app/observability/touch.py`.")
    add("")
    from app.observability import touch as touch_mod

    touches = touch_mod.classify(rec.events)
    lines.extend(_table(["What the touch was", "Findings", "Touches", "How it is known", "Severity"], [
        [name, sum(1 for t in touches if t.name == name), touch_mod.taps_in(touches, name),
         ", ".join(f"{how} × {n}" for how, n in Counter(
             t.basis for t in touches if t.name == name).most_common()) or "—",
         SEVERITY[name]]
        for name in touch_mod.CLASSES if any(t.name == name for t in touches)
    ] or [["nothing swallowed a touch in this session", 0, 0, "—", "—"]]))
    holds = touch_mod.holds(rec.events)
    lengths = sorted(h.ms for h in holds if h.ms is not None)
    if lengths:
        add(f"- {len(holds)} hold(s) on the glass, "
            f"{sum(1 for x in lengths if x < touch_mod.TAP_MS)} of them under "
            f"{touch_mod.TAP_MS:.0f} ms; median {statistics.median(lengths):,.0f} ms. "
            f"Targets the tablet recorded: "
            + (", ".join(f"{name or 'none'} × {n}" for name, n in
                         Counter(h.target for h in holds).most_common()) or "none")
            + ". A file in which only the voice target is ever named is a file in which nothing "
              "else ever received a touch.")
    add("")
    by_collision = Counter(str(c["what"]) for c in rec.collisions)
    add(f"- Branch moves: {dict(branch_moves) or 'none'}. Gestures that could end a recording: {dict(by_collision) or 'none'}"
        + (f" — {'; '.join(sorted({str(c['detail']) for c in rec.collisions}))}." if rec.collisions else "."))
    tapped = sum(1 for t in turns if t.commands)
    add(f"- Turns with a tap of their own: {tapped} of {len(turns)}. Commands outside any turn: {len([e for e in commands if not any(e in t.commands for t in turns)])}.")
    add("")
    predictions = [e for t in turns for e in t.predictions] + [e for e in rec.controls if str(e.get("kind") or "") == "prediction"]
    anticipations = [e for t in turns for e in t.anticipations] + [e for e in rec.controls if str(e.get("kind") or "") == "anticipation"]
    if predictions or anticipations:
        levels = Counter(str(e.get("level") or e.get("tier") or "") for e in predictions)
        states = Counter(str(e.get("state") or e.get("event") or "") for e in anticipations)
        add(f"- What the Mac guessed would be wanted next: {len(set(id(e) for e in predictions))} prediction(s) "
            f"by level {dict(levels) or '—'}; {len(set(id(e) for e in anticipations))} anticipation record(s) "
            f"by state {dict(states) or '—'}.")
        starved = [t.turn_id for t in turns if "FOREGROUND_STARVED" in t.classes]
        if starved:
            add(f"  **Anticipation was added to make the product feel faster and it refused work instead:** "
                f"the owner's own read was starved in {', '.join(starved)} (section 16).")
        add("")

    # 15 -----------------------------------------------------------------------------
    add("## 15. OWNER-REPORTED DEFECTS")
    add("")
    add("What the owner said about the product, in his own words, while he was using it. "
        "Verbatim, because a defect paraphrased is a defect argued about; and first in this half of "
        "the report, because a tester narrating what is broken is the most valuable thing in an hour. "
        "He should not have to say any of it twice.")
    add("")
    lines.extend(_owner_defects(rec))

    # 16 -----------------------------------------------------------------------------
    add("## 16. Two outcomes per turn")
    add("")
    add("`backend` is what the server did. `visible` is what the owner could see. `experience` is the "
        "verdict the two produce together, and their DISAGREEMENT is the defect: a send that Gmail "
        "confirmed while the card still said “Applying…” is a failed turn, whatever the action engine "
        "proved. The September report had only the first column, and that is how an hour the owner "
        "spent reporting four defects was scored eleven successful of fourteen.")
    add("")
    lines.extend(_two_outcomes(rec))

    # 17 ------------------------------------------------------------------------------
    # Only when there is one. Every session recorded before the appliance existed, and every
    # session driven from a browser rather than from the pad, has no appliance events at all —
    # and a section that said "none" at the bottom of each of those would be noise in every
    # report ever written. So the report of a browser session is unchanged, to the byte.
    if rec.appliance:
        add("## 17. The appliance")
        add("")
        lines.extend(_appliance(rec))

    add("---")
    appliance_note = f" · {len(rec.appliance)} appliance event(s)" if rec.appliance else ""
    add(f"Timeline: `logs/test-sessions/{session.get('test_session_id')}.jsonl` · {len(rec.events)} events · {len(rec.orphans)} outside any turn · {len(rec.controls)} command / branch event(s){appliance_note}.")
    return "\n".join(lines) + "\n"


def _appliance(rec: Reconstruction) -> list[str]:
    """Section 17: the native shell around the page, from its own `pad_*` events (§18).

    Every line is a count or the difference of two timestamps. It exists because an appliance's
    failure modes are invisible to every other section of this report: the app was never brought
    to the foreground, the WebView never loaded, the renderer was killed and Android rebuilt the
    page underneath the owner, the pad could not reach this Mac for four minutes. A session in
    which the owner says "I got no answer" reads identically in sections 1 to 16 whether the Mac
    was slow or the tablet was asleep in a drawer, and that is the ambiguity this removes.
    """
    out: list[str] = []
    events = rec.appliance
    counts = Counter(str(e.get("kind") or "") for e in events)
    beats = [e for e in events if e.get("kind") == "pad_heartbeat"]
    identity = next((e for e in reversed(beats) if e.get("device_model") or e.get("app_version")), None)
    if identity is not None:
        out.append(f"- Pad: **{identity.get('device_model') or '?'}** · app **{identity.get('app_version') or '?'}** · OS {identity.get('os_version') or '?'}.")
    out.append(f"- Appliance events: {len(events)} — {dict(counts)}.")
    folded = sum(int(e["repeats"]) for e in events if isinstance(e.get("repeats"), (int, float)) and not isinstance(e.get("repeats"), bool))
    if folded:
        out.append(f"- {folded} identical repeat(s) were folded away before anything was written (`app/observability/pad.py`); "
                   "each surviving event carries `repeats` — the number of reports of the state it replaced.")
    returned = [e for e in beats if str(e.get("state") or "") == "returned"]
    if returned:
        gaps = ", ".join(_fmt_s(float(e.get("gap_s") or 0.0)) for e in returned)
        out.append(f"- **The pad went quiet and came back {len(returned)} time(s)**: {gaps}. Each gap is a stretch in which "
                   "nothing on this Mac could have known whether the tablet was alive.")
    unreachable = [e for e in events if e.get("kind") == "pad_backend_unreachable"]
    if unreachable:
        out.append(f"- The pad could not reach this Mac **{len(unreachable)}** time(s): {dict(Counter(str(e.get('code') or '?') for e in unreachable))}. "
                   "From the pad's side, not from ours — this is the half of the connection /health cannot see.")
    errors = [e for e in events if e.get("kind") == "pad_webview_error"]
    if errors:
        out.append(f"- The WebView failed to load **{len(errors)}** time(s): {dict(Counter(str(e.get('code') or '?') for e in errors))}. "
                   "The app was running and CROOKS was not on the screen.")
    crashes = [e for e in events if e.get("kind") == "pad_renderer_crash"]
    if crashes:
        out.append(f"- **The renderer died {len(crashes)} time(s)** — {dict(Counter(str(e.get('reason') or '?') for e in crashes))}. "
                   "Whatever was on screen went with it, and anything done next was done on a page that had just been rebuilt.")
    mic = [e for e in events if e.get("kind") == "pad_mic_permission"]
    if mic:
        out.append(f"- Microphone permission: {dict(Counter(str(e.get('state') or '?') for e in mic))}. Denied means the orb could not have heard anything.")
    admin = [e for e in events if e.get("kind") == "pad_admin_entered"]
    if admin:
        out.append(f"- Admin was entered {len(admin)} time(s), left {counts.get('pad_admin_exited', 0)} time(s).")
    unread = sorted(k for k in counts if k not in APPLIANCE_KINDS)
    if unread:
        out.append(f"- Appliance kinds this report does not read line by line: {unread}. They are in the counts above, "
                   "and they are there because the timeline was written by a backend that knows a kind this one does not.")
    out.append("")
    return out


def _owner_defects(rec: Reconstruction) -> list[str]:
    """Section 15: the owner's own words, and what was on screen when he said them.

    Two tables, because the difference matters. The first is what the session RECORDED — an
    `owner_feedback` event, which is what §16 of the brief added. The second is what he said
    that nothing recorded, which is what the live hour did twice: he asked for a defect to be
    logged, was told there was no tool for it, and the report that came out did not mention it.
    """
    experience = rec.experience
    if experience is None:
        return ["_none_", ""]
    out: list[str] = []
    if experience.feedback:
        out.append(f"**{len(experience.feedback)} recorded during the session.**")
        out.append("")
        for event in experience.feedback:
            when = _clock(event.get("ts"))
            where = ", ".join(str(x) for x in (event.get("screen") or [])) or "no card"
            refs = ", ".join(f"{e.get('kind')} {e.get('ref')}" for e in (event.get("entities") or [])
                             if isinstance(e, dict)) or "nothing open"
            nearby = ", ".join(f"{row.get('kind')} {row.get('id') or ''}".strip()
                               for row in (event.get("nearby") or [])[:4]) or "nothing"
            out.append(f"- **{when}** · {event.get('shape') or 'feedback'} · half {event.get('branch_id') or '—'} "
                       f"· on screen: {where} · holding: {refs}")
            out.append(f"  > {' '.join(str(event.get('text') or '').split())}")
            out.append(f"  Nearby: {nearby}. Turn `{event.get('turn_id') or '—'}`.")
        out.append("")
    if experience.ignored_feedback:
        out.append(f"**{len(experience.ignored_feedback)} the owner reported and NOTHING recorded.** "
                   "Read back from what he said, because no `owner_feedback` event exists for these turns: "
                   "either the session was not in test mode, or the sentence never reached the family that "
                   "takes it. Each one is still a defect he reported, and it is printed here so the hour is "
                   "not lost.")
        out.append("")
        for row in experience.ignored_feedback:
            out.append(f"- **{_clock(row.get('at'))}** · {row.get('shape')} · turn `{row.get('turn_id')}` "
                       f"· on screen: {', '.join(row.get('screen') or []) or 'no card'}")
            out.append(f"  > {' '.join(str(row.get('text') or '').split())}")
            out.append(f"  The assistant answered: “{_cell(row.get('answer'), 160)}”")
        out.append("")
    if not experience.feedback and not experience.ignored_feedback:
        out.append("_The owner said nothing about the product itself during this session._")
        out.append("")
    return out


def _two_outcomes(rec: Reconstruction) -> list[str]:
    """Section 16: the line §17 asks for, one per turn, and what was read to draw it."""
    experience = rec.experience
    if experience is None:
        return ["_none_", ""]
    out: list[str] = ["```"]
    for row in experience.rows:
        out.append(f"{row.turn_id}  {row.line()}")
    out.append("```")
    out.append("")
    disagree = [r for r in experience.rows if r.backend in ("VERIFIED", "READ_OK", "ANSWERED")
                and r.experience == "FAILED"]
    if disagree:
        out.append(f"**{len(disagree)} turn(s) where the server did its part and the owner still could not.** "
                   "Every one of those was counted as a success by the September rule.")
        out.append("")
    counts = experience.counts
    if counts:
        out.append("What the owner could see, by class. Each row is a count over ids, and the rule that drew it "
                   "is named in `app/observability/visible.py`.")
        out.append("")
        out.extend(_table(["What the owner saw", "Times", "Severity", "Turns", "Likely component"], [
            [name, n, SEVERITY[name],
             ", ".join(dict.fromkeys(f.turn_id for f in experience.of(name)))[:120],
             COMPONENT[name]]
            for name, n in sorted(counts.items(), key=lambda kv: (-SEVERITY[kv[0]], -kv[1], kv[0]))
        ]))
        out.append(f"The evidence, finding by finding, up to {EVIDENCE_PER_CLASS} per class — the "
                   "counts above are complete and this is what was read. §21: the 11 September "
                   "report gave one class sixty-two rows of its own and buried the other nine, "
                   "so no class may take more of this table than any other.")
        out.append("")
        shown: Counter = Counter()
        rows: list[list[Any]] = []
        for f in experience.findings:
            shown[f.name] += 1
            if shown[f.name] <= EVIDENCE_PER_CLASS:
                rows.append([f.name, f.turn_id, f.subject or "—",
                             f.signal + ("" if getattr(f, "basis", "direct") == "direct"
                                         else f" [{f.basis}]")])
        out.extend(_table(["What the owner saw", "Turn", "About", "What was read"], rows))
        held_back = {name: n - EVIDENCE_PER_CLASS for name, n in shown.items()
                     if n > EVIDENCE_PER_CLASS}
        if held_back:
            out.append("Not printed above, and counted in the table before it: "
                       + ", ".join(f"{n} more {name}" for name, n in sorted(held_back.items()))
                       + ".")
            out.append("")
    else:
        out.append("_Nothing the owner could see went wrong in this session._")
        out.append("")
    if experience.errors:
        out.append(f"**Rules that could not read this timeline: {', '.join(experience.errors)}.** "
                   "A detection that silently stops detecting is how an hour comes to be scored wrongly, "
                   "so it is reported rather than swallowed.")
        out.append("")
    return out


def _fmt_s(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = float(seconds)
    return f"{int(seconds // 60)} min {int(seconds % 60)} s" if seconds >= 60 else f"{seconds:.0f} s"


def _opportunities(rec: Reconstruction, turns: list[Turn], registered: list[str],
                   capability_states: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    by_class: dict[str, list[Turn]] = defaultdict(list)
    for t in turns:
        for c in t.classes:
            by_class[c].append(t)
    tasks = {
        "FALSE_UNSUPPORTED": "the assistant declined a question the read layer or a batch tool composes: add the example to commerce_capabilities or the prompt's guidance so the composition is reached for.",
        "STT_ERROR": "replay the failing recordings through `make bench`; check the keyterms and the VAD padding for the words that were lost.",
        "TIMEOUT": "raise or split the budget that expired, and make the slow step visible on the tablet while it runs.",
        "PERMISSION_ERROR": "grant the scope or login the refusal names (the card and /health say which) before the next session.",
        "MISSING_CAPABILITY": "decide whether to build the capability (see section 6) or to have the assistant say plainly what the nearest existing one is.",
        "TOOL_ERROR": "read the client error on the failing tool and add the retry or the clearer refusal it needs.",
        "VERIFICATION_ERROR": "look at the re-read the proof made and the state Shopify/Gmail holds; the change may need a longer settle or a different fingerprint.",
        "TOOL_SELECTION_ERROR": "tighten the tool description or the system prompt for the call the model kept making wrongly.",
        "UI_RENDER_ERROR": "reproduce the card in the renderer tests with the same data shape; fix the exception or the skipped item.",
        "UI_NAVIGATION_PROBLEM": "watch the screen the owner left at once; the card or the chip did not offer what they wanted.",
        "CONTEXT_INCOMPLETE": "extend the hydration budget for the part that never arrived, or make the tablet's collection retry longer.",
        "INTENT_ERROR": "hand the model the entity in focus more plainly (the prefetch line, the context stack) for follow-up questions.",
        "UNKNOWN": "read the turn's events; the error kind has no rule here yet.",
        "GESTURE_COLLISION": "the tablet's touch handling ended the recording. Cover it with a two-finger gesture in the tablet gate and assert ZERO turns posted; nothing here is speech's to fix.",
        "UI_RELATION_MISSING": "the relation was in the turn's data and not on the card. Carry it on the surface (a linked-order strip the tablet can tap), not in the prose.",
        "FALSE_SUCCESS": "the worst class there is: a change reported as made that nothing staged. Read the turn, then either build the named mutation or add the limitation to app/observability/contract.py so the assistant says what it cannot do.",
        "UNFULFILLED_ACTION": "a change was asked for and nothing happened, in either direction. Decide whether the write tool is missing or the request was misread, and make the answer say which.",
        "ACTION_MISMATCH": "a different change was staged from the one asked for; tighten the tool description or the entity resolution for that phrasing.",
        "UI_INTENT_UNFULFILLED": "the owner asked for something on the screen and none appeared. Add it to the card vocabulary (app/presentation.py, web/ui.js); a spoken answer to \"bring up a UI\" is not a partial success.",
        "OWNER_FEEDBACK": "nothing to do: the owner reported a defect and it was recorded. Read section 15 — his own words are the most valuable evidence in the session.",
        "DATA_FIELD_UNAVAILABLE": "the answer said a field is not available and a registered tool returns it: name the tool in the prompt, or in the tool's own description.",
        "INTENT_DIVERGENCE": "the answer addressed a mechanism the request never named. Read the pair; the misunderstanding is usually one word.",
        "PARTIAL_COVERAGE": "a read covered part of what was asked and the answer did not say so. Make the coverage line part of the answer, not the result.",
        # What the owner could SEE, and what to do about each (app/observability/visible.py).
        **visible.TASKS,
    }
    experience = rec.experience
    sure: set[str] = set()
    if experience is not None:
        sure = {f.name for f in experience.findings if getattr(f, "basis", "direct") != "inferred"}
    for cls, group in by_class.items():
        if cls in NON_DEFECT:
            continue          # a class that records what worked is not an improvement candidate
        # A class is only discounted while every one of its findings was inferred. One burst
        # the owner himself confirmed out loud settles the class for the whole session.
        inferred = cls in INFERRED_CLASSES and cls not in sure
        out.append({
            "problem": cls, "frequency": f"{len(group)} of {len(turns)} turns", "severity": SEVERITY[cls],
            "examples": [t.turn_id for t in group[:3]], "component": COMPONENT[cls], "task": tasks[cls],
            "weight": rank(SEVERITY[cls], len(group), inferred=inferred),
            "basis": f"severity {SEVERITY[cls]} × {min(len(group), RANK_CAP)} turn(s)"
                     + (f" × {INFERRED_CONFIDENCE} (inferred)" if inferred else ""),
        })
    for key, bound in SLOW_MS.items():
        slow = [t for t in turns if (t.latency(key) or 0) > bound]
        if slow:
            out.append({"problem": f"Slow {key.replace('_', ' ')} (over {bound:,.0f} ms)", "frequency": f"{len(slow)} of {len(turns)} turns", "severity": 2,
                        "examples": [t.turn_id for t in sorted(slow, key=lambda t: -(t.latency(key) or 0))[:3]], "component": {"stt": "speech", "claude": "the model / prompt size", "total": "the whole turn", "tts_first_byte": "ElevenLabs / prefetch", "context": "context hydration",
                                      "prose_wait": "the prompt and the lane: this is time spent after the facts were in hand",
                                      "facts": "the read layer: the data itself was slow to arrive"}[key],
                        "task": "look at the slowest examples' step timings and cut the step that dominates.", "weight": rank(2, len({t.turn_id for t in slow})), "basis": f"severity 2 × {min(len(slow), RANK_CAP)} turn(s)"})
    images = [e for t in turns for e in t.tablet_events("image_failed")]
    if images:
        out.append({"problem": "Images failed to load", "frequency": f"{len(images)} failure(s)", "severity": 2, "examples": sorted({t.turn_id for t in turns if t.tablet_events('image_failed')})[:3],
                    "component": "the media proxy (app/media.py) and the thumbnail paths", "task": "fetch the failing paths on the Mac and see what the proxy answers.", "weight": rank(2, len({t.turn_id for t in turns if t.tablet_events("image_failed")})), "basis": "severity 2 × the turns that failed an image"})
    exposed: Counter = Counter()
    used: Counter = Counter()
    for t in turns:
        for r in t.tablet_events("render"):
            for c in r.get("cards") or []:
                for a in (c.get("actions") or []) if isinstance(c, dict) else []:
                    if isinstance(a, dict) and a.get("enabled"):
                        exposed[str(a.get("id"))] += 1
        for e in t.tablet_events("rail_tap") + t.tablet_events("action_primed"):
            used[str(e.get("action") or "")] += 1
    unused = sorted(set(exposed) - set(used))
    if unused and len(turns) >= 5:
        out.append({"problem": "Rail actions exposed but never used", "frequency": f"{len(unused)} chip(s) ({', '.join(unused)}) across {len(turns)} turns", "severity": 1, "examples": [],
                    "component": "the rail (app/actions/available.py, web/ui.js)", "task": "ask whether these chips earn their place, or whether their wording did not read as the thing the owner wanted.", "weight": rank(1, len(unused)), "basis": f"severity 1 × {min(len(unused), RANK_CAP)} chip(s)"})
    for name, n in Counter(x.missing_capability for t in turns for x in t.tools if x.missing_capability).items():
        out.append({"problem": f"Requested capability not built: {name}", "frequency": f"requested {n} time(s)", "severity": 3, "examples": [t.turn_id for t in turns if any(x.missing_capability == name for x in t.tools)][:3],
                    "component": "the tool registry (app/tools)", "task": f"build `{name}` on the action engine, or teach the assistant the nearest existing capability ({_closest_capability(name, registered)}).", "weight": rank(3, n), "basis": f"severity 3 × {min(n, RANK_CAP)} request(s)"})
    intel = intelligence(rec, registered, capability_states=capability_states)
    for key, n, ids, state, scope, what in intel["spoken_capabilities"]:
        if state == _no_family():
            out.append({"problem": f"Asked for out loud and not built: {what}", "frequency": f"{n} time(s)", "severity": 3, "examples": ids[:3],
                        "component": "the capability families (app/capabilities/families.py, app/families/)",
                        "task": f"decide whether `{key}` becomes a family, or whether the assistant should say plainly what it can do instead.", "weight": rank(3, n), "basis": f"severity 3 × {min(n, RANK_CAP)} request(s)"})
        else:
            out.append({"problem": f"Asked for out loud and {state}: {what}", "frequency": f"{n} time(s)", "severity": 4, "examples": ids[:3],
                        "component": "the write boundary and the store's scopes",
                        "task": f"the capability exists; grant {scope or 'the scope it names'} (or connect the provider) rather than building it again.", "weight": rank(4, n), "basis": f"severity 4 × {min(n, RANK_CAP)} request(s)"})
    for shape, n, ids, why in intel["new_read_families"]:
        if n >= 2:
            out.append({"problem": f"A read the router places in no family, asked {n} times: {shape}", "frequency": f"{n} time(s)", "severity": 2, "examples": ids[:3],
                        "component": "the intent families and the fast lane (app/families/, app/fastpath)",
                        "task": f"a family and a recipe would answer this without the model ({why}).", "weight": rank(2, n), "basis": f"severity 2 × {min(n, RANK_CAP)} request(s)"})
    if intel["branch_failures"]:
        out.append({"problem": "The split orb cost the owner something", "frequency": f"{len(intel['branch_failures'])} occurrence(s)", "severity": 3,
                    "examples": sorted({b for b, _w, _d in intel["branch_failures"]})[:3], "component": "the branches (app/routes/branches.py, web/app.js)",
                    "task": "read the rows in section 13: a focus that redraws nothing, or a half put aside and never returned to, is a control the glass does not have.", "weight": rank(3, len(intel["branch_failures"])), "basis": f"severity 3 × {min(len(intel['branch_failures']), RANK_CAP)} occurrence(s)"})
    if len(intel["corrections"]) >= 2:
        out.append({"problem": "The same request said again", "frequency": f"{len(intel['corrections'])} pair(s) of turns", "severity": 2,
                    "examples": [tid for tid, _w, _s in intel["corrections"]][:3], "component": "speech, the normaliser and the answer's own wording",
                    "task": "read each pair: the first question is whether the first ANSWER was wrong rather than unheard — see WRONG_ENTITY_ANSWERED, which is what one of these pairs turned out to be.", "weight": rank(2, len(intel["corrections"])), "basis": f"severity 2 × {min(len(intel['corrections']), RANK_CAP)} pair(s)"})
    # §21. This row was the 11 September report's number one candidate at 2 × 62 = 124, and
    # 61 of the 62 were control taps the voice layer swallowed. It is now ranked on the TURNS
    # that hold real evidence of exact entry, so a tap burst can never buy it a priority again.
    precision_turns = {tid for tid, _w, _d in intel["precision_input"]}
    if len(precision_turns) >= 2:
        out.append({"problem": "A value had to be exact and a voice could not make it so", "frequency": f"{len(intel['precision_input'])} occurrence(s) across {len(precision_turns)} turn(s)", "severity": 2,
                    "examples": sorted(precision_turns)[:3], "component": "the precision-input path (the composer's fields, app/routes/command.py)",
                    "task": "give the field a keyboard on the card rather than another attempt at saying it.",
                    "weight": rank(2, len(precision_turns)), "basis": f"severity 2 × {min(len(precision_turns), RANK_CAP)} turn(s) of real exact-entry evidence"})
    for shape, n, ids in intel["cross_source_workflows"]:
        if n >= 2:
            out.append({"problem": f"A cross-source read repeated: {shape}", "frequency": f"{n} time(s)", "severity": 2, "examples": ids[:3],
                        "component": "the read layer and the fast lane's recipes", "task": "one recipe would do this in one pass with the ids issued once.", "weight": rank(2, n), "basis": f"severity 2 × {min(n, RANK_CAP)} time(s)"})
    for name, n, ids in intel["dimensions"]:
        out.append({"problem": f"Query dimension asked for and unknown: {name}", "frequency": f"{n} time(s)", "severity": 3, "examples": ids[:3],
                    "component": "the query language (app/analytics/query.py)", "task": f"decide whether `{name}` is a filter, a group or a metric, and add it with a bound; or teach the prompt the nearest existing one.", "weight": rank(3, n), "basis": f"severity 3 × {min(n, RANK_CAP)} time(s)"})
    for op, n, ids, served in intel["bulk"]:
        if not served:
            out.append({"problem": f"Bulk change asked for with no batch: {op}", "frequency": f"{n} time(s)", "severity": 3, "examples": ids[:3],
                        "component": "the batch engine (app/actions/batch.py, app/tools/batch_tools.py)", "task": f"register a batch over the single `{op}` write once that change has proved itself; money and irreversible changes take a hold and a drag at any size.", "weight": rank(3, n), "basis": f"severity 3 × {min(n, RANK_CAP)} time(s)"})
    for shape, n, ids in intel["follow_ups"]:
        if n >= 3:
            out.append({"problem": f"Follow-up shape repeated: {shape}", "frequency": f"{n} time(s)", "severity": 1, "examples": ids[:3],
                        "component": "the prompt's follow-up guidance (app/kb/loader.py)", "task": "check each follow-up re-ran the previous query with one thing changed; spell the case out in the prompt if any started over.", "weight": rank(1, n), "basis": f"severity 1 × {min(n, RANK_CAP)} time(s)"})
    # SEVERITY decides what engineering does first; frequency decides the order within a
    # severity. The 11 September report sorted on frequency alone and put a severity-2 guess,
    # multiplied by sixty-two swallowed taps, above every P0 in the session.
    out.sort(key=lambda o: (-o["severity"], -o["weight"], o["problem"]))
    return out[:12]


# ---------------------------------------------------------------------- entry points


def build_report(path: Path, *, tools_registered: list[str] | None = None,
                 capability_states: dict[str, dict[str, Any]] | None = None) -> tuple[Reconstruction, str]:
    events = read_events(Path(path))
    rec = reconstruct(events, capability_states=capability_states)
    if not rec.session.get("test_session_id"):
        rec.session["test_session_id"] = Path(path).stem
    return rec, render(rec, tools_registered=tools_registered, capability_states=capability_states)


def write_report(path: Path, out_dir: Path, *, tools_registered: list[str] | None = None,
                 capability_states: dict[str, dict[str, Any]] | None = None) -> Path:
    rec, markdown = build_report(Path(path), tools_registered=tools_registered, capability_states=capability_states)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{rec.session.get('test_session_id') or Path(path).stem}.md"
    target.write_text(markdown, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target
