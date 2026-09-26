"""IMPROVEMENT CANDIDATES from a test session: the report's evidence, written as proposals a
person can pick up. Nothing here changes code, and nothing here runs anything: it reads the
timeline, applies the same rules the report applies, and writes a file that says, for each
candidate, what the evidence is (by turn id), where it probably lives, what change is
proposed, which tests would prove it and what it must not touch. See docs/ENGINEERING_LOOP.md."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.observability import claims
from app.observability.report import (
    Reconstruction,
    Turn,
    _cell,
    _opportunities,
    intelligence,
    registered_tools,
)
from app.observability.timeline import read_events

# What the OWNER said was wrong outranks everything derived. The other weights are a severity
# times a count, so this is deliberately above any of them: a defect a person narrated while it
# was happening is better evidence than any rule in this file, and it goes at the top of the
# page whatever the counts say.
OWNER_FIRST = 1_000

# The invariant every candidate is held to, named once.
INVARIANTS = (
    "reads never mutate; a change is a reviewed mutation on the action engine with a fresh read, a precondition, one execution and a proving re-read",
    "the model proposes and never authorises; the gesture on the tablet is the only authorisation",
    "the Mac owns working-set membership and batch membership; the tablet names ids and nothing else",
    "no customer detail in the ledger, the timeline or a proposal beyond what the owner said aloud",
)


def candidates(rec: Reconstruction, *, registered: list[str] | None = None,
               capability_states: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The candidates, most evidence first. Each cites turn ids; none is applied.

    `capability_states` is the live capability table when the caller has a runtime. It decides
    whether a change asked for out loud is a family to build or a scope to grant — which is the
    difference between an engineering task and a two-minute job in the Dev Dashboard.
    """
    registered = registered if registered is not None else registered_tools()
    turns = rec.turns
    intel = intelligence(rec, registered, capability_states=capability_states)
    out: list[dict[str, Any]] = []

    def add(kind: str, title: str, evidence: list[str], component: str, change: str, tests: str, risk: str, weight: int) -> None:
        out.append({"kind": kind, "title": title, "evidence": evidence, "component": component, "change": change, "tests": tests, "risk": risk, "weight": weight})

    for row in intel["false_unsupported"]:
        add("FALSE_UNSUPPORTED", f"The assistant declined something the Mac composes: {row['what']}", [row["turn_id"]],
            "the system prompt's guidance and commerce_capabilities (app/kb/loader.py, app/tools/analytics_tools.py)",
            f"Make the composition explicit for questions like “{_cell(row['question'], 80)}”: an example in commerce_capabilities, or a line in the prompt naming {', '.join(row['tools'])}.",
            "a scripted turn asking this in the mocked session; the answer must call the tools named and never decline.",
            "prompt words only; no new tool, no wider bound.", 4)
    for row in intel["composable_failed"]:
        add("COMPOSABLE_FAILED", f"A composable request failed on its way: {row['what']}", [row["turn_id"]],
            "the read layer (app/analytics) or the tool named in the failure",
            f"Reproduce the failing call ({row['detail']}) against the fake store and fix what refused or timed out.",
            "a test with the same arguments that must return rows or a bounded refusal the model can act on.",
            "keep the query bounds; a bound that was hit is a reason to narrow, not to widen.", 3)
    for name, n, ids in intel["dimensions"]:
        add("QUERY_DIMENSION", f"A query dimension the language does not have: {name}", ids,
            "the query language (app/analytics/query.py, engine.py)",
            f"Decide whether `{name}` is a filter, a group or a metric; add it with a bound and a cost, or teach the prompt the nearest existing one.",
            "a parse test and an aggregate test for the new dimension; the catalogue test.",
            "a new dimension is read-only and bounded like the rest.", 3 * n)
    for name, n, ids in intel["new_actions"]:
        add("NEW_ACTION", f"A change asked for that is not built: {name}", ids,
            "the action engine (app/actions) and a new reviewed mutation (app/clients/shopify.py, app/tools/*_writes.py)",
            f"Build `{name}` as a write tool: a fresh read, a fingerprint, one reviewed mutation, a proving re-read, a card, a ledger line; or have the assistant name the nearest existing change.",
            "the write walkthrough (stage, commit once, stale, unverified, undo) for the new tool.",
            "a new write ships behind the same switches and gestures; never GREEN.", 3 * n)
    for key, n, ids, state, scope, what in intel["spoken_capabilities"]:
        # Asked for OUT LOUD, which is different from asked for by a tool: a change the
        # assistant declines in words reaches no tool at all, and the September report's
        # "Potential new actions: none" is what that difference looked like. The capability
        # table decides which candidate this is.
        if state == "NO_FAMILY":
            add("NEW_CAPABILITY_FAMILY", f"A change asked for out loud that nothing claims: {what}", ids,
                "a new capability family (app/families/<name>.py) and its state in app/capabilities/families.py",
                f"Decide whether `{key}` becomes a family — its tools, its commands, its recipes, its intent family, its "
                "capability state, all in one file — or whether the assistant should say plainly what it can do instead.",
                "the family's own scenario pack, and a capability-state test that the family reports what it really is.",
                "a new write ships behind the same switches and gestures; a family that is not READY offers no write tool at all.", 3 * n)
        else:
            add("CAPABILITY_STATE", f"A change asked for out loud that this Mac has and cannot run: {what} ({state})", ids,
                "the store's own grants, and the family's capability state (app/capabilities/families.py)",
                f"The capability exists. Grant {scope or 'the scope the family names'} on the Dev Dashboard and approve it in the "
                "store admin (or connect the provider), rather than building it a second time.",
                "the family's probe test: with the scope missing the state is MISSING_SCOPE and names the scope; with it granted, READY.",
                "nothing is built here; a grant is the owner's to make.", 4 * n)
    for shape, n, ids, why in intel["new_read_families"]:
        if n >= 2:
            add("NEW_READ_FAMILY", f"A read the router places in no family, asked {n} times: {shape}", ids,
                "the intent families and the fast lane (app/families/, app/fastpath/recipes.py)",
                f"A family and a read-only recipe would answer this without the model ({why}). Name the signals it needs; a family "
                "brings its own signal through `intent.signal` rather than editing the shared table.",
                "the family's scenario, asserting the lane is FAST and the model was not called.",
                "a recipe names read tools only; the read scheduler refuses a plan with a write in it.", 2 * n)
    for branch, what, detail in intel["branch_failures"]:
        add("BRANCH_UX", f"The split orb cost the owner something: {what}", [branch],
            "the branches (app/routes/branches.py) and the tablet's two halves (web/app.js)",
            f"Read what was recorded ({detail}). A focus that redraws nothing, or a half put aside and never returned to, is a "
            "control the glass does not have yet.",
            "a browser check that switching halves changes the visible cards, and that a finished aside is retrievable.",
            "a background half still cannot commit; nothing here touches the mutation boundary.", 3)
    for turn_id, what, detail in intel["precision_input"]:
        add("PRECISION_INPUT", f"A value had to be exact and a voice could not make it so: {what}", [turn_id],
            "the precision-input path (the composer's fields, app/routes/command.py)",
            f"Give the field a keyboard on the card rather than another attempt at saying it ({detail}).",
            "a command test that the posted field reaches the Mac bounded, and a renderer test for the field itself.",
            "a posted field is a value the Mac validates; the tablet still sends names and references only.", 2)
    for turn_id, what, said in intel["corrections"]:
        add("CORRECTION", f"The same request said again: {what}", [turn_id],
            "speech (app/speech), the normaliser, and the answer's own wording",
            f"Read the pair: the owner repeated himself because the first answer missed the question, or because the transcript did "
            f"({said[:80]}).",
            "a bench case for the transcript, or a scenario for the answer, whichever the pair shows.",
            "no new tool.", 2)
    for shape, n, ids in intel["cross_source_workflows"]:
        if n >= 2:
            add("CROSS_SOURCE_RECIPE", f"A cross-source read repeated {n} times: {shape}", ids,
                "the read layer and the fast lane's recipes (app/families/, app/reads/)",
                "One recipe would do this in one pass, with the ids issued once, instead of the model discovering the same sequence "
                "each time.",
                "the recipe's scenario, asserting one pass and both sets of ids issued.",
                "reads compose; a recipe names read tools only.", 2 * n)
    for op, n, ids, supported in intel["bulk"]:
        if not supported:
            add("NEW_BULK_ACTION", f"A change asked for in bulk with no batch yet: {op}", ids,
                "the batch engine (app/actions/batch.py) and app/tools/batch_tools.py",
                f"Register a batch tool over the single `{op}` write when the single change has proved itself: same BatchSpec shape, its own gesture by size, counts on the card.",
                "the batch tests (eligibility, exactly once, partial failure, expiry, wrong session) for the new tool.",
                "refunds, cancels, fulfilments and stock changes are money or irreversible: a hold and a drag at any size.", 3 * n)
    for shape, n, ids in intel["follow_ups"]:
        if n >= 3:
            add("FOLLOW_UP_SHORTCUT", f"A follow-up shape repeated {n} times: {shape}", ids,
                "the prompt's follow-up guidance (app/kb/loader.py) and the working sets (app/analytics/sets.py)",
                f"Check each of these turns re-ran the previous query with one thing changed and nothing else; if any re-ran from scratch, the prompt's follow-up line needs the '{shape}' case spelled out.",
                "a two-turn test: the first query, then the follow-up, asserting the second call keeps the first's shape.",
                "no new tool.", n)
    for tools, n, ids in intel["workflows"]:
        if n >= 3:
            add("WORKFLOW", f"A multi-tool workflow repeated {n} times: {' → '.join(tools)}", ids,
                "the read layer (app/tools/analytics_tools.py)",
                "Consider whether one call could answer it (a view, a default, a derived set made at once) without a new tool; if the calls are all reads, the plan already bounds them.",
                "a test that the single call returns what the sequence returned.",
                "no new mutation; reads compose.", n)
    for kind, n, ids in intel["ui_types"]:
        add("UI_COMPONENT", f"A card type the tablet could not draw: {kind}", ids,
            "the renderer (web/ui.js) and the vocabulary (app/presentation.py)",
            f"Either add `{kind}` to the vocabulary on both sides with a bounded data shape, or stop the presentation layer emitting it.",
            "the vocabulary test in tests/web/ui.test.js and the presentation test.",
            "no model-generated markup; a new type is a new renderer with its own bounds.", 2 * n)
    for row in _recipe_candidates(turns):
        add(*row)
    # What the OWNER said was wrong, first, and heaviest. A tester narrating defects as they
    # happen is the most valuable thing in an hour, and in September all of it was discarded:
    # he was told twice there was no tool for it and the report did not mention any of it.
    experience = getattr(rec, "experience", None)
    for event in (experience.feedback if experience is not None else []):
        words = " ".join(str(event.get("text") or "").split())
        add("OWNER_REPORTED", f"The owner reported this himself: “{_cell(words, 90)}”",
            [str(event.get("turn_id") or "—")],
            f"on screen at the time: {', '.join(str(x) for x in (event.get('screen') or [])) or 'no card'}"
            f"; half {event.get('branch_id') or '—'}",
            "Read what he said and fix the thing he named. He should not have to say it twice, "
            "and a session that records feedback and does not act on it is worse than one that "
            "cannot record it.",
            "the regression test for whatever he named; a fixture timeline of this turn if the "
            "defect is in the analyser or the surface.",
            "none: this is a bug report, not a change to the bounds.", OWNER_FIRST)
    for row in (experience.ignored_feedback if experience is not None else []):
        words = " ".join(str(row.get("text") or "").split())
        add("OWNER_REPORTED", f"The owner reported this and NOTHING recorded it: “{_cell(words, 90)}”",
            [str(row.get("turn_id") or "—")],
            "owner feedback (app/observability/feedback.py, app/families/owner_feedback.py)",
            "Two things: fix what he named, and find out why the sentence reached no "
            "`owner_feedback` event — either the session was not in test mode or the router did "
            "not take it.",
            "say the same sentence during an active test session and assert both the event and "
            "the report's OWNER-REPORTED DEFECTS section.",
            "none: recording what somebody said is not a change to the shop.", OWNER_FIRST + 1)
    for o in _opportunities(rec, turns, registered, capability_states):
        # The report's own ranked list, carried over as summaries beside the specific rows above.
        add("REPORT", o["problem"], list(o["examples"]), o["component"], o["task"],
            "the tests the component already has, extended with this session's example.", "as the component's invariants say.", int(o["weight"]))
    out.sort(key=lambda c: (-c["weight"], c["title"]))
    seen: set[str] = set()
    unique = []
    for c in out:
        if c["title"] in seen:
            continue
        seen.add(c["title"])
        unique.append(c)
    return unique[:24]


# What a turn cost when the model answered it, above which it is worth asking whether the
# Mac could have. The September session's median model time was 12 seconds.
SLOW_MODEL_MS = 8_000
# How many times a question must repeat before "write the procedure down" is worth proposing.
REPEATED = 3


def _recipe_candidates(turns: list[Turn]) -> list[tuple]:
    """Proposals about the fast lane itself (brief section 29).

    Three things the timeline can now say that it could not before: which questions the model
    answered slowly and repeatedly (a recipe waiting to be written), which recipes deferred
    and why (a recipe that is not earning its place), and which recipes ran over their own
    target. All proposals; nothing here writes a recipe.
    """
    out: list[tuple] = []
    slow: Counter = Counter()
    slow_ids: dict[str, list[str]] = {}
    defers: Counter = Counter()
    defer_ids: dict[str, list[str]] = {}
    over: dict[str, list[str]] = {}

    for turn in turns:
        lane = (turn.lane or {}).get("lane") if turn.lane else None
        fast = turn.fast or {}
        if fast.get("defer"):
            key = f"{fast.get('recipe_id')}: {fast['defer']}"
            defers[key] += 1
            defer_ids.setdefault(key, []).append(turn.turn_id)
        target, took = fast.get("target_ms"), fast.get("ms")
        if fast.get("hit") and isinstance(target, (int, float)) and isinstance(took, (int, float)) and took > target:
            over.setdefault(str(fast.get("recipe_id")), []).append(turn.turn_id)
        if lane == "NORMAL" and turn.model and isinstance(turn.model.get("ms"), (int, float)) and turn.model["ms"] >= SLOW_MODEL_MS:
            shape = _shape_of(turn)
            if shape:
                slow[shape] += 1
                slow_ids.setdefault(shape, []).append(turn.turn_id)

    for shape, n in slow.most_common(6):
        if n < REPEATED:
            continue
        out.append((
            "FAST_PATH_RECIPE", f"A question asked {n} times that the model answered slowly: {shape}",
            slow_ids[shape][:3], "the fast lane (app/fastpath/intent.py, library.py)",
            f"Write the procedure down: an intent family for “{shape}”, the reads it needs, and the sentence that answers it. "
            "It must decline rather than guess when an entity does not resolve.",
            "a routing test (this phrasing and two near neighbours), a plan test, and a deferral test for the case it cannot serve.",
            "read-only and navigation-only; a recipe can never stage, arm or commit a change.", 4 * n,
        ))
    for key, n in defers.most_common(4):
        if n < 2:
            continue
        out.append((
            "RECIPE_DEFERRED", f"A recipe took the lane and then could not answer, {n} times: {key}",
            defer_ids[key][:3], "the fast lane (app/fastpath)",
            "Either resolve what it could not (an entity, a period, a dimension) or stop routing that shape to it: a recipe that defers is a model call plus its own cost.",
            "a test that this request either answers or never reaches the recipe.",
            "deferring is safe and answering wrongly is not; tighten the route rather than loosening the recipe.", 3 * n,
        ))
    for recipe_id, ids in sorted(over.items(), key=lambda kv: -len(kv[1]))[:4]:
        out.append((
            "RECIPE_SLOW", f"A recipe answered but missed its own target, {len(ids)} time(s): {recipe_id}",
            ids[:3], "the recipe and its reads (app/fastpath/library.py, app/reads/scheduler.py)",
            "Look at the read plan on those turns: a wave that could be one, a read that could be cached, or a target that was never realistic.",
            "make bench-lanes, which fails when a recipe is over target.",
            "no bound may be widened to make a target: narrow the work instead.", 2 * len(ids),
        ))
    return out


def _shape_of(turn: Turn) -> str:
    """A question reduced to its SHAPE, so two askings of the same thing count as two.

    Built from a CLOSED vocabulary — the words the router itself knows (app/fastpath/intent.py)
    — rather than by dropping a list of stop words. A name, a street, an order number or
    anything else the owner said about a customer is not in that vocabulary and therefore
    cannot reach a proposals file, whatever it was. This file is written to disk and read by
    a person; a deny-list would only be as good as its last omission.
    """
    import re

    words = re.findall(r"[a-z]{3,}", (turn.question or "").lower())
    kept = [w for w in words if w in _VOCABULARY]
    return " ".join(dict.fromkeys(kept))[:80]


def _vocabulary() -> frozenset[str]:
    from app.fastpath import intent as router

    words: set[str] = set()
    for name in dir(router):
        value = getattr(router, name)
        if isinstance(value, frozenset) and value and all(isinstance(v, str) for v in value):
            words |= {str(v) for v in value}
    # The shapes of a question, which the router reads off structure rather than words.
    words |= {"how", "many", "much", "long", "should", "would", "could", "left", "each", "all", "every", "any", "some", "still"}
    return frozenset(w for w in words if len(w) >= 3)


_VOCABULARY = _vocabulary()


def render(rec: Reconstruction, cands: list[dict[str, Any]]) -> str:
    session = rec.session
    lines = [
        f"# IMPROVEMENT CANDIDATES — {session.get('test_session_id') or 'unknown'}",
        "",
        "Proposals, not changes. Written from the timeline by the report's own rules; every one cites the turns it comes from. "
        "Nothing here has been applied, and nothing here can apply itself: a person picks a candidate, an engineering agent works it on a development branch, tests and a review follow, and the owner approves what runs (docs/ENGINEERING_LOOP.md).",
        "",
        f"Session: **{session.get('name') or '—'}** · {len(rec.turns)} turns · {len(cands)} candidate(s).",
        "",
        "Invariants every candidate is held to:",
        "",
    ]
    lines.extend(f"- {inv}" for inv in INVARIANTS)
    lines.append("")
    if not cands:
        lines.append("_Nothing in this session's evidence calls for a change._")
    for i, c in enumerate(cands, 1):
        lines.append(f"## IC-{i} · {c['kind']} · {c['title']}")
        lines.append("")
        lines.append(f"- **Evidence:** {', '.join(c['evidence']) or 'session-wide'}")
        lines.append(f"- **Component:** {c['component']}")
        lines.append(f"- **Proposed change:** {c['change']}")
        lines.append(f"- **Tests to write first:** {c['tests']}")
        lines.append(f"- **Risk / must not touch:** {c['risk']}")
        lines.append("- **Status:** PROPOSED — not applied")
        lines.append("")
    return "\n".join(lines) + "\n"


def build(path: Path, *, registered: list[str] | None = None,
          capability_states: dict[str, Any] | None = None) -> tuple[Reconstruction, list[dict[str, Any]], str]:
    from app.observability.report import reconstruct

    events = read_events(Path(path))
    rec = reconstruct(events, capability_states=capability_states)
    if not rec.session.get("test_session_id"):
        rec.session["test_session_id"] = Path(path).stem
    cands = candidates(rec, registered=registered, capability_states=capability_states)
    return rec, cands, render(rec, cands)


def write_proposals(path: Path, out_dir: Path, *, registered: list[str] | None = None,
                    capability_states: dict[str, Any] | None = None) -> Path:
    rec, _cands, markdown = build(Path(path), registered=registered, capability_states=capability_states)
    from app.observability.session import write_private_text

    target = Path(out_dir) / f"{rec.session.get('test_session_id') or Path(path).stem}-proposals.md"
    return write_private_text(target, markdown)


def evidence_counter(turns: list[Turn]) -> Counter:
    """How often each class appears, for a summary line."""
    return Counter(c for t in turns for c in t.classes)


__all__ = ["INVARIANTS", "build", "candidates", "claims", "render", "write_proposals"]
