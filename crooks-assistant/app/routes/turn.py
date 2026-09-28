"""POST /turn — the whole product, in one endpoint.

Accepts text (development, and the typed interface that keeps allowance testing cheap) or audio
(the tablet). Both converge on the same agent path, which is what made M11 nearly trivial.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import uuid
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import progressive
from app.actions import engine as action_engine
from app.actions.grammar import AFFIRMATION_BLOCKED, affirmation_for, words_for
from app.actions.grammar import FIXED_LINES as GRAMMAR_FIXED_LINES
from app.logging.turnlog import redact
from app.observability import timeline
from app.presentation import compact, present
from app.providers.base import ToolCall
from app.routes.actions import session_matches, writes_context
from app.speech.decode import DecodeError, decode
from app.speech.speakable import to_speakable
from app.tools.context import CURRENT_BRANCH

log = logging.getLogger("crooks.turn")

router = APIRouter()

MAX_UPLOAD_BYTES = 10_000_000
MAX_TEXT_CHARS = 2_000


def _tool_state(tool_names: list[str]) -> str:
    """The UI state is driven by the tool actually running, never guessed from the question."""
    for name in reversed(tool_names):
        if name.startswith("shopify_"):
            return "CHECKING SHOPIFY"
        if name.startswith("gmail_"):
            return "CHECKING EMAIL"
    return "THINKING"


@router.post("/turn")
async def turn(
    request: Request,
    text: str | None = Form(default=None),
    session_id: str = Form(default=""),
    audio: UploadFile | None = File(default=None),
) -> dict:
    runtime = request.app.state.runtime
    started = time.perf_counter()
    timings: dict[str, float] = {}
    expected_turns: int | None = None
    # "I will ask /speak for this answer." Lets the backend start the voice a round trip early.
    speak = False
    # Which half of a divided orb asked. Empty is the focused one, which is the usual case.
    branch_id = ""

    # JSON bodies are what curl and scripts/chat.py send; multipart is what the tablet sends.
    if text is None and audio is None:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        text = body.get("text")
        session_id = body.get("session_id") or session_id
        # A count, whatever shape the client sent it in; "0" must not read as "one turn".
        try:
            expected_turns = int(body.get("turns") or 0) or None
        except (TypeError, ValueError):
            expected_turns = None
        speak = _truthy(body.get("speak"))
        branch_id = str(body.get("branch_id") or "")[:32]
    else:
        form = await request.form()
        form_turns = form.get("turns")
        expected_turns = int(form_turns) if form_turns not in (None, "") else None
        speak = _truthy(form.get("speak"))
        branch_id = str(form.get("branch_id") or "")[:32]

    # The tablet says how many turns it thinks this conversation has had. If the backend has
    # no such session but the tablet believes one exists, the backend restarted (or the
    # session idled out) and the honest answer is "I've lost the thread", not a fresh start
    # that silently forgets what "that order" meant.
    lost_thread = False
    if session_id and expected_turns and not runtime.sessions.exists(session_id):
        lost_thread = True
    session_id = session_id or uuid.uuid4().hex[:12]
    if lost_thread:
        runtime.sessions.drop(session_id)
        await runtime.provider.reset_session(session_id)
    # The session exists from the first moment of the turn: the tablet must not see the last
    # question while this one is heard, and a hold that abandons this question may land at
    # any point from here on — during transcription as much as during Claude's thinking.
    live = runtime.sessions.get_or_create(session_id)
    if not session_matches(live, request):
        # A conversation is its first caller's. Another login on the tailnet that learns the
        # id gets nothing of it: not the thread, not the cards, not the tap.
        log.warning("turn refused: session belongs to another login")
        return JSONResponse(status_code=403, content={"code": "wrong_session", "detail": "That conversation belongs to another login."})
    # Which half of the orb is being spoken to, from the first moment: everything this turn
    # does is filed against that half, the early refusals included.
    branch = live.branch(branch_id)
    # And which half this REQUEST acts for, held on the request's own task rather than only on
    # the session. The session's `acting_branch` is one field for both halves: a turn to the
    # other half that starts while this one is thinking overwrites it, and anything this turn
    # stages afterwards on its own task — rather than inside the provider's per-call dispatch,
    # which sets the same context itself — would be filed against the wrong half (the
    # 2026-09-28 deploy review, round 9, D2-03). The session field is still written, for the
    # readers that have only a session and no turn; `app/tools/context.py::acting_branch`
    # reads this first.
    token = CURRENT_BRANCH.set(branch.branch_id)
    try:
        return await _turn(
            request, runtime, live, branch, text=text, audio=audio, session_id=session_id, speak=speak,
            lost_thread=lost_thread, started=started, timings=timings,
        )
    finally:
        CURRENT_BRANCH.reset(token)


async def _turn(request: Request, runtime, live, branch, *, text: str | None, audio: UploadFile | None, session_id: str,
                speak: bool, lost_thread: bool, started: float, timings: dict[str, float]) -> dict:
    """The turn itself, once the conversation and the half it is addressed to are known."""
    transcript_info: dict | None = None
    live.heard = ""
    live.abandoned = False
    # This turn's place in the conversation. A hold that abandons the question, or a later
    # question, moves the session past it; the answer then goes unspoken.
    epoch = live.epoch
    # The turn's id: every tool call, proposal and tablet event it causes is written against
    # it on the test-session timeline (a no-op while no session is on). Kept here as well as on
    # the session, because the session's copy is the NEXT turn's as soon as one starts.
    live.turn_id = turn_id = timeline.new_id("turn")
    # The names this conversation has already been shown, handed to the timeline's redaction
    # BEFORE this turn writes anything: the focus, the words heard and the answer are all
    # written below, and a name is not a shape the timeline can find by itself (D1-01).
    timeline.note_names(live.pii_seen)
    if timeline.current().active is not None:
        timeline.emit(
            "turn_started", session_id=session_id, turn_id=turn_id, input="audio" if audio is not None else "text",
            turns_before=live.turns, epoch=epoch, lost_thread=lost_thread, focus=(live.context[0] if live.context else None),
            # What was WAITING when this turn began: changes the owner has not decided about.
            # An undo offer is not one of those and is recorded separately — the report read
            # `waiting` and called two undo offers two outstanding changes.
            waiting=[p for p in action_engine.waiting_ids(live) if not live.proposal(p).batch_id] + [b.batch_id for b in live.batches.values() if b.status.value == "PENDING"],
            undoable=action_engine.undoable_ids(live) or None,
        )

    # What the recogniser heard is written to the timeline once the turn knows the names its
    # own reads returned, not at the moment it was heard: "what did <a customer> order" names a
    # person no read has returned yet, and an event is redacted as it is written, never after
    # (the 2026-09-28 deploy review, round 9, D1-01). It keeps the time it was heard, so the
    # timeline still reads in the order things happened.
    heard_event: dict[str, Any] = {}

    def written_heard() -> None:
        if heard_event and timeline.current().active is not None:
            timeline.note_names(live.pii_seen)
            timeline.emit("stt", **heard_event)
        heard_event.clear()

    if audio is not None:
        blob = await audio.read()
        if len(blob) > MAX_UPLOAD_BYTES:
            return await _answer(
                runtime, session_id, "That recording was too long for me to handle.",
                request=request, error_kind="audio_too_large", timings=timings, started=started, speak=speak, epoch=epoch,
                branch=branch, turn_id=turn_id,
            )
        # The Mac says what it is doing while it does it: the tablet reads this rather than
        # guessing from a timer how long the recogniser takes.
        live.set_state("TRANSCRIBING")
        result = await runtime.transcriber.from_blob(blob, filename_hint=audio.filename or "")
        transcript_info = result.as_dict()
        timings.update(result.timings_ms)
        if timeline.current().active is not None:
            stats = transcript_info.get("stats") or {}
            heard_event.update(
                session_id=session_id, turn_id=turn_id, ok=result.ok, engine=result.engine or None, fallback=result.fallback,
                engine_detail=result.engine_detail or None, reason=result.reason or None, raw_text=result.raw_text or None, text=result.text or None,
                audio_s=stats.get("duration_s"), audio_bytes=len(blob), timings=transcript_info.get("timings_ms"),
                ts=_timeline_now(),
            )
        if not result.ok:
            written_heard()
            live.set_state("READY")
            return await _answer(
                runtime, session_id, result.reason, request=request, error_kind="speech",
                timings=timings, started=started, transcript=transcript_info, speak=speak, epoch=epoch,
                branch=branch, turn_id=turn_id,
            )
        # What the recogniser heard, word for word. Nothing rewrites it towards the catalogue
        # first: the owner said "Clive" and a term list turned it into "Plaid".
        text = result.text

    if not text or not text.strip():
        written_heard()
        live.set_state("READY")
        return await _answer(
            runtime, session_id, "I did not catch that.", request=request, error_kind="empty",
            timings=timings, started=started, transcript=transcript_info, speak=speak, epoch=epoch,
            branch=branch, turn_id=turn_id,
        )
    text = text.strip()[:MAX_TEXT_CHARS]

    # A new instruction, now that there is one. Whatever the assistant proposed under the last
    # one is withdrawn: a proposal is bound to the conversation position it was made in, and
    # this is a new one. A fumbled hold or a recording that said nothing is not an instruction
    # and withdraws nothing; the card the owner was about to tap survives it.
    # A bare "yes" while a card is waiting is not a new instruction and applies nothing; it
    # is answered here, in a fixed sentence, without the model and without withdrawing the
    # card — the owner is told again what applies it. Anything else said is an instruction.
    # This is the one check on the words kept in front of the model, and it is kept because
    # it is part of the write boundary, not a shortcut: it fires only with a card waiting
    # and only on a whole sentence of four words or fewer from a fixed list of bare yeses, it
    # looks nothing up, and sending that yes to the model instead would withdraw the very card
    # he is agreeing to (every new instruction withdraws pending cards, below). "Yes, and
    # cancel the order" is not a bare yes and goes to the model, and so does "yes, #1938":
    # a number, or any word beyond the fixed list, is something he said (`is_affirmation`).
    # A question asked over here is not a new instruction to a card waiting over there.
    # Everything downstream that is handed only the session — the action engine when it
    # stages, working sets when they are created — asks which half is speaking; the request's
    # own context answers first (see `turn` above), and the session's field is kept for the rest.
    live.acting_branch = branch.branch_id
    waiting = _waiting_proposal(runtime, live, branch.branch_id)
    if waiting is not None and is_affirmation(text):
        written_heard()
        live.heard = text
        live.set_state("READY")
        # The card is re-presented as it stands: its clock started when it was delivered and
        # a spoken yes does not wind it back. The tablet keeps the card it already shows.
        calls = [ToolCall(name=waiting.tool_name, args={}, ok=True, result={}, proposal_id=waiting.proposal_id)]
        return await _answer(
            runtime, session_id, _affirmation_answer(live, waiting), request=request, timings=timings, started=started,
            transcript=transcript_info, question=text, speak=speak, calls=calls, epoch=epoch, revoked=[],
            branch=branch, turn_id=turn_id,
        )

    # A control was tapped that expects words, and these are the words. The sentence is about
    # the record that was bound when it was tapped, so the owner does not have to name it
    # again — "make it shorter and more apologetic" rather than "rewrite Millie's draft to be
    # shorter and more apologetic". The binding belongs to THIS half of the orb and expires;
    # a sentence spoken to the other half never picks it up (app/session/branch.py).
    # What the owner SAID, kept apart from what the model is told. The continuation note below
    # is an instruction to the model — "[this applies to order #1938]" — and while it was
    # spliced into `text` itself, everything downstream read the annotated string as the
    # transcript: `live.heard`, which /state returns and the tablet prints under the orb, and
    # `question`, which the payload carries and the turn log records. The owner tapped Note,
    # said "make it shorter", and saw his own words come back with a machine instruction
    # stapled to them.
    spoken = text
    continuation = branch.voice_target()
    if continuation:
        branch.release_voice()      # one sentence, one binding, taken or abandoned
        # Said beside the words, never instead of them: whether "how many orders today" is a
        # note for #1938 or a question in its own right is the model's to judge, not a word
        # list's.
        text = _with_continuation(text, continuation)

    revoked = runtime.actions.revoke_pending(live, "new instruction", branch_id=branch.branch_id) + runtime.batches.revoke_pending(live, "new instruction")
    epoch = runtime.actions.advance_epoch(live, "new instruction", branch_id=branch.branch_id)
    runtime.batches.advance_epoch(live)
    # This half's own position, beside the session's. The epoch moves for either half's
    # instruction — a proposal is bound to the conversation's position — but a turn that is
    # still thinking on the OTHER half has not been replaced by this one, and must neither
    # have its tool calls refused nor its answer treated as abandoned. The sequence is what
    # tells the two apart (app/session/branch.py, app/providers/max_agent_sdk.py).
    branch.instruction_seq += 1
    branch.abandoned = False
    # A new instruction to THIS half replaces whatever it was doing, so nothing earlier is
    # still in flight here. Said out loud because `in_flight` is what makes the chip's WORKING
    # true, and a turn that died on its way out would otherwise leave that word standing.
    branch.in_flight = 0
    seq = branch.instruction_seq

    # Every sentence is a model turn. Nothing matches the words first — no phrase, no order
    # number, no intent — and nothing is looked up in front of the model. The owner's
    # decision of 28 September 2026: a lane that matched words in front of Claude meant that
    # mentioning an order number or a word could get a canned lookup instead of what he asked.
    # What was heard goes on the session now, so the tablet can show it while Claude thinks
    # rather than only once the answer lands — a mis-heard question is visible at once.
    live.heard = spoken.strip()
    # What this half is doing, while it does it. A half he has put aside says this on its own
    # chip rather than taking his attention (brief section 17). `begin_turn` rather than
    # `working`: the branch counts turns actually in flight, so WORKING on a chip is a fact
    # and not a note left behind by a turn that died.
    branch.begin_turn("working it out")
    # The workspace starts NOW, not when the reads are done (§7, D-5): its sections go up as
    # each read starts (app/tools/dispatch.py) and are collected by the tablet's /state poll.
    progressive.begin(session_id, turn_id=turn_id, branch_id=branch.branch_id)

    await _ensure_provider_started(runtime)

    # What the Mac already knows about applying a change from this request, before the model
    # is asked: a change proposed while changes are off must never be announced as something
    # to tap. Asked once per turn (the scope answer is cached), and reused for the card.
    prompt_text = f"{_now_line(runtime)}\n{text.strip()}"
    writes = await writes_context(request) if request is not None else None
    live.writes_blocked = "" if writes is None or writes["allowed"] else _blocked_words(writes)
    from app.analytics import sets as working_sets

    set_line = working_sets.prompt_line(live, branch=branch)
    if set_line:
        prompt_text = f"{prompt_text}\n\n{set_line}"
    # A defect the owner says out loud is taken down before the model is asked, against the screen
    # he was complaining about, and the model is told what the Mac did with it (the 2026-09-28
    # deploy review, round 9, E-03: app/observability/feedback.py held_at_turn). It is WRITTEN
    # once this turn's reads have named whoever they found, as the words heard are, because a
    # defect report can name a customer only those reads go on to find (round 9, D1-01). It
    # never fails a turn.
    from app.observability import feedback

    told, write_feedback = feedback.held_at_turn(text, branch=branch, session_id=session_id, turn_id=turn_id)
    if told:
        prompt_text = f"{prompt_text}\n\n{told}"
    for extra in _context_lines(live, text, runtime=runtime):
        prompt_text = f"{prompt_text}\n\n{extra}"
    where = _branch_line(branch)
    if where:
        prompt_text = f"{prompt_text}\n\n{where}"

    # What the model is about to be given, in numbers (brief section 11). Counts only: no
    # part of the prompt is written anywhere, here or on the timeline. Kept apart from
    # `timings`, which is milliseconds and is published as such.
    measures = {"model_input_chars": len(prompt_text), "tool_schema_bytes": _tool_schema_bytes(runtime)}
    t0 = time.perf_counter()
    try:
        result = await _provider_turn(runtime, session_id, prompt_text, branch)
    finally:
        # Written even when the model fails — that is when a defect report matters most — and
        # only after the names this turn's reads returned are known to the timeline.
        timeline.note_names(live.pii_seen)
        write_feedback()
    timings["agent"] = (time.perf_counter() - t0) * 1000
    for step, ms in getattr(result, "steps", None) or []:
        timings[f"step:{step}"] = ms
    # The names this turn's reads just returned, before the answer that may say them is
    # written — and before the words heard, which may have named the same person.
    timeline.note_names(live.pii_seen)
    written_heard()
    if timeline.current().active is not None:
        timeline.emit(
            "model", session_id=session_id, turn_id=turn_id, ms=round(timings["agent"], 1), steps=list(getattr(result, "steps", None) or []),
            error_kind=result.error_kind, stopped_early=result.stopped_early, answer=result.text or None,
            tool_calls=[{"tool": c.name, "ok": c.ok, "tool_call_id": getattr(c, "tool_call_id", "") or None, "proposal_id": c.proposal_id} for c in result.tool_calls or []],
        )
    answer = result.text or "I could not work out an answer to that."
    if len(answer) > runtime.settings.max_answer_chars:
        # A forty-second spoken monologue is a bad product; truncate at a sentence boundary.
        cut = answer[: runtime.settings.max_answer_chars]
        answer = cut[: cut.rfind(".") + 1] or cut
    if lost_thread and result.error_kind is None:
        # The backend restarted (or the conversation idled out) since the tablet last spoke.
        # It heard the question, so it answers it — from the start, and says so — rather than
        # asking the owner to repeat himself. Only "that order" questions lose anything, and
        # for those Claude asks which one.
        answer = f"{LOST_THREAD_PREFIX}{answer}"

    return await _answer(
        runtime,
        session_id,
        answer,
        request=request,
        error_kind=result.error_kind,
        timings=timings,
        started=started,
        transcript=transcript_info,
        question=spoken.strip(),
        tool_calls=[
            {
                "name": c.name, "ok": c.ok, "error": c.error, "ms": c.duration_ms,
                # Arguments are what make a wrong answer diagnosable in chat.py — redacted,
                # because the model may have put an email address in them. A proposed write's
                # content stays out of the log altogether; the ledger keeps its length.
                "args": _loggable_args(c),
                "proposal_id": c.proposal_id,
                "tool_call_id": getattr(c, "tool_call_id", "") or None,
            }
            for c in list(result.tool_calls)
        ],
        calls=result.tool_calls,
        speak=speak,
        lost_thread=lost_thread,
        epoch=epoch,
        seq=seq,
        revoked=revoked,
        writes=writes,
        branch=branch,
        measures=measures,
        turn_id=turn_id,
    )


def _timeline_now() -> float:
    """The timeline's own clock, for an event written later than the moment it records."""
    clock = getattr(timeline.current(), "clock", None)
    try:
        return float(clock()) if callable(clock) else time.time()
    except Exception:  # noqa: BLE001 — a clock is not worth a turn
        return time.time()


LOST_THREAD_PREFIX = "I lost our earlier thread, so from the start: "


def _written(text: str, names: set[str]) -> str:
    """What the timeline keeps of something spoken. The spoken answer is the owner's and may
    carry a customer's name, an email address or a street; the file it would land in is read
    later, by a person, and may be handed to somebody else. The turn log has always redacted
    by shape and by the exact names this turn's tools returned — this is that, applied to the
    other place an answer is written."""
    from app.logging.turnlog import redact_text

    return redact_text(str(text or ""), names) if text else ""


# The opening of the standing capability line. Named, not quoted twice: a test that needs to
# separate "what the Mac cannot do" from "what this conversation knows" filters on this.
# The instruction is here, ONCE, rather than repeated on every line of the block. It was on
# each line, and with seven unavailable families that was 287 characters a turn of the same
# sentence.
FAMILY_LINE_PREFIX = "[What CLIVE cannot do right now. Do not attempt these; say why if asked:\n"


def _performance(timings: dict, *, branch, calls, session, measures: dict, ui: list | None = None, glass: dict | None = None) -> dict:
    """The turn's own measurements. No content, no arguments, no personal data: counts,
    milliseconds and names of tools.

    Every turn is a model turn, so the fields the removed fast lane wrote — `recipe_id` and
    `fast_path_hit` — are no longer produced; a reader of older records finds them there and
    of newer ones finds them absent. `lane` stays, always NORMAL, because readers of the
    record group turns by it and a tap is TOUCH on /command."""
    from app.memory import current as memory
    from app.memory.coalesce import current as coalescer
    from app.memory.prefetch import current as prefetcher
    from app.reads import budget as read_budget
    from app.reads.dedupe import current as dedupe

    sources: dict[str, float] = {}
    for call in calls or []:
        source = "shopify" if call.name.startswith(("shopify_", "commerce_", "inventory_")) else ("gmail" if call.name.startswith(("gmail_", "email_")) else "mac")
        sources[source] = round(sources.get(source, 0.0) + float(getattr(call, "duration_ms", 0.0) or 0.0), 1)
    model_ms = timings.get("agent")
    model_phases = sum(1 for key in timings if key.startswith("step:model"))
    facts_ms, workspace_ms, waited_ms = _workspace_timing(timings, calls=calls, measures=measures)
    return {
        "lane": "NORMAL",
        "branch_id": getattr(branch, "branch_id", None),
        "parent_branch_id": (getattr(branch, "parent_id", "") or None),
        "backgrounded": getattr(branch, "status", "") == "BACKGROUND",
        "cancelled": bool(getattr(session, "abandoned", False) or getattr(branch, "abandoned", False)),
        "partial": False,
        "tool_calls": len(calls or []),
        "source_ms": sources,
        "stt_ms": round(float(timings.get("transcribe") or timings.get("stt") or 0.0), 1) or None,
        "model_ms": round(float(model_ms), 1) if model_ms is not None else None,
        "model_calls": 1,
        "model_phases": model_phases or None,
        "model_input_chars": measures.get("model_input_chars"),
        "tool_schema_bytes": measures.get("tool_schema_bytes"),
        "prefetch_ms": round(float(timings["prefetch"]), 1) if "prefetch" in timings else None,
        # Section 25's three numbers, kept apart on purpose.
        #
        # `facts_ms` is when the Mac HELD the authoritative data the cards are drawn from —
        # the last read to land. A progressive workspace could be on screen at that moment.
        # `workspace_ms` is when the cards existed (present() returned).
        # `prose_wait_ms` is the rest: what the owner waited AFTER the facts were in hand,
        # which on the live bench was most of a twenty-five-second turn and is the number to
        # attack. Do not wait ten seconds to polish a sentence about data already read.
        "facts_ms": facts_ms,
        "workspace_ms": workspace_ms,
        "prose_wait_ms": waited_ms,
        # And §15's four, which are the same turn seen from the GLASS. The three above say
        # when the MAC held the data and had built the cards; these say when the owner had a
        # screen that said what it was, a fact on it, something he could act on, and
        # everything. A turn where `time_to_first_actionable_surface` is most of
        # `time_to_complete_workspace` is D-5 happening again, and the report can see it
        # without being told. Named in app/progressive.py, so a rename cannot leave this
        # behind: Phase 4's `time_to_shell` counted a shell with nothing on it, which §15
        # says is not progress, and the four names now say what each one measures.
        **{name: (glass or {}).get(name) for name in progressive.TIMINGS},
        # Section 25: what was drawn, what was patched, and the identical renders that were
        # NOT drawn. `suppressed` is D-13's five identical order cards, as a number.
        "renders": (glass or {}).get("renders") or None,
        # Regions the cards left still loading. The tablet collects them from /context/order,
        # whose own duration is on the timeline as `context_request` — so final enrichment is
        # measured where it happens rather than guessed at here.
        "enrichment_pending": sorted({
            str(region) for item in (ui or [])
            if isinstance(item, dict) and isinstance(item.get("data"), dict)
            for region in (item["data"].get("pending") or []) if isinstance(region, str)
        }) or None,
        "turn_total_ms": round(float(timings.get("total") or 0.0), 1),
        "cache": memory().counts(),
        "coalesced": coalescer().counts(),
        "prefetch": prefetcher().counts(),
        # What asking once instead of twice actually saved, in the three units the brief asks
        # for: requests avoided, milliseconds saved and provider calls saved. Measured from
        # the duration the avoided read took, not estimated (app/reads/dedupe.py).
        "deduped": dedupe().stats(),
        # And what each lane spent, so a refusal can be read back to the lane that caused it
        # rather than to "the turn" (app/reads/budget.py).
        "read_budgets": read_budget.report(session),
    }


def _workspace_timing(timings: dict, *, calls, measures: dict) -> tuple[float | None, float | None, float | None]:
    """(when the facts were in hand, when the cards existed, what was waited after the facts).

    The model path records a step per tool call at the moment it returned, offset from the
    start of the turn (`step:tool:<name>`); the last of those is when the workspace COULD
    have been drawn. A turn that read nothing has no facts time and is not counted as slow
    prose.
    """
    steps = [float(v) for k, v in timings.items() if k.startswith("step:tool:") and isinstance(v, (int, float))]
    facts = max(steps) if steps else None
    if facts is None and calls:
        # No per-step offsets (a provider that does not measure): the reads themselves are
        # the floor, run in parallel where they could be.
        durations = [float(getattr(c, "duration_ms", 0.0) or 0.0) for c in calls]
        facts = max(durations) if any(durations) else None
    workspace = timings.get("workspace")
    total = timings.get("total")
    waited = None
    if facts is not None and isinstance(total, (int, float)):
        waited = round(max(0.0, float(total) - facts), 1)
    return (
        round(facts, 1) if facts is not None else None,
        round(float(workspace), 1) if isinstance(workspace, (int, float)) else None,
        waited,
    )


def _call_summary(call) -> str:
    """A read, in a clause the next turn can be told without re-reading it."""
    body = call.result if isinstance(getattr(call, "result", None), dict) else {}
    for key in ("order_number", "name", "subject", "label", "set_label"):
        if body.get(key):
            return f"{call.name}: {body[key]}"
    for key in ("rows", "orders", "customers", "threads"):
        if isinstance(body.get(key), list):
            return f"{call.name}: {len(body[key])} rows"
    return call.name


def _call_ref(call) -> str:
    body = call.result if isinstance(getattr(call, "result", None), dict) else {}
    for key in ("order_id", "customer_id", "thread_id", "set_id"):
        if body.get(key):
            return str(body[key])
    return ""


_SCHEMA_BYTES: dict[tuple, int] = {}


def _tool_schema_bytes(runtime) -> int:
    """The size of the tool block the model is offered, in bytes. Measured once per writes
    setting: the registry does not change while the process runs."""
    import json

    writes = bool(getattr(runtime.settings, "writes_enabled", False))
    # A family the store cannot use is not offered either (runtime.withheld_by_family), and
    # that set moves with the store's state — so it is part of the key, not a surprise.
    by_family = getattr(runtime, "withheld_by_family", None)
    family = frozenset(by_family() if callable(by_family) else ())
    key = (writes, family)
    if key not in _SCHEMA_BYTES:
        from app.providers.max_agent_sdk import withheld_tools
        from app.tools import registry

        specs = registry.all_specs()
        withheld = withheld_tools(specs, writes_enabled=writes) | set(family)
        _SCHEMA_BYTES[key] = sum(
            len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema}))
            for s in specs if s.name not in withheld
        )
    return _SCHEMA_BYTES[key]


def _with_continuation(text: str, continuation: dict) -> str:
    """The sentence, with the control he tapped before saying it named plainly beside it.

    A bracketed note the model reads, never a rewrite of the words: the owner's sentence stays
    exactly as he said it, and whether it is the words that control was waiting for or a new
    request of its own is the model's to judge. It used to be decided by a word list in front
    of the model, which is the kind of guess the owner asked to be rid of. The reference is
    the record's id and its label — never its contents.
    """
    family = str(continuation.get("family") or "")
    kind = str(continuation.get("kind") or "record").replace("_", " ")
    label = str(continuation.get("label") or "").strip()
    ref = str(continuation.get("ref") or "")
    named = f" ({label})" if label else ""
    return (
        f"{text}\n[Just before saying this he tapped {family} on the {kind} he is looking at{named}"
        f"{f', id {ref}' if ref else ''}. If these words are for that, apply them to that record and to "
        "nothing else; if they ask for something else, do that instead.]"
    )


#: Said once, after where the screen is: the record on screen is the default for "it" and
#: "this", never for a record he names. The fast lane refused, in code, to answer "where is
#: 1940" or "what's Millie's address" from the order that happened to be open; the model
#: reads what it decides to read, so the rule is put to it in words, every turn a record is
#: open (the 2026-09-28 deploy review, round 9, D2-05). Nothing on the Mac reads the open
#: record for a sentence any more, and the screen is drawn only from what the model read.
NAMED_OUTRANKS_SHOWN = "A number or a name he says is the record he means, whatever is on screen"


def _branch_line(branch) -> str:
    """Where the conversation is, in one line, so the model does not spend a tool call
    rediscovering it. Position only — never a permission, and never a whole read."""
    if branch is None:
        return ""
    bits: list[str] = []
    entity = getattr(branch, "entity", None)
    if entity:
        bits.append(f"looking at the {entity['kind']} {entity['label']}")
    workflow = getattr(branch, "workflow", None)
    if workflow is not None and workflow.total:
        bits.append(f"working through {workflow.total} {workflow.kind}, at {workflow.position}")
    recent = getattr(branch, "recent_results", None) or []
    if recent:
        bits.append("just read: " + "; ".join(str(r.get("summary") or "")[:60] for r in recent[:2]))
    if not bits:
        return ""
    rule = f" {NAMED_OUTRANKS_SHOWN}." if entity else ""
    return f"[Where we are: {'; '.join(bits)}.{rule}]"

# What a spoken yes gets while a card is waiting: the waiting card's own gesture, in a fixed
# sentence — synthesised once and kept, and never a promise: the gesture is the only thing
# that applies anything. The sentences live with the grammar (app/actions/grammar.py).
AFFIRMATION_ANSWER = words_for("tap_commit")["affirmation"]
AFFIRMATION_BLOCKED_ANSWER = AFFIRMATION_BLOCKED
FIXED_LINES = GRAMMAR_FIXED_LINES

def _context_lines(session, text: str, runtime=None) -> list[str]:
    """What the Mac knows that the model would otherwise guess at, one line each: the last
    gesture's counted outcome (once), the last query's shape (for a follow-up), and which
    composable capability the question's words name (so it is reached for, not declined)."""
    from app.observability import claims

    lines: list[str] = []
    outcome = str(getattr(session, "last_outcome", "") or "").strip()
    if outcome:
        lines.append(f'[The last change, as CLIVE proved it: "{outcome[:200]}". If asked whether it worked, say this; do not propose it again.]')
        session.last_outcome = ""
    session.hinted = False
    last = getattr(session, "last_query", None)
    if isinstance(last, dict) and last:
        lines.append(f"[Last read-layer query: {_short_query(last)}. A follow-up (\"just this week\", \"by size\", \"only joggers\") is this query with that one thing changed.]")
    # A change the Mac knowingly cannot make: said plainly, with what it can do instead.
    # Without this the September session's "add two items to David Randall's order" was
    # answered as though it had been done (app/observability/contract.py).
    from app.observability import contract as contract_mod

    limitation = contract_mod.limitation_line(text)
    if limitation:
        lines.append(limitation)
    # Drafting and sending are different requests, and the words tell them apart. Said here
    # rather than left to be inferred, because the wrong one is either an email nobody meant
    # to send or a draft nobody asked for.
    wants = _draft_or_send(text)
    if wants:
        lines.append(wants)
    matched = claims.match_capabilities(text)
    if matched:
        known = claims.registered()
        usable = [c for c in matched if all(t in known for t in c.tools)]
        if usable:
            lines.append("[This asks for " + "; ".join(f"{c.what} ({', '.join(c.tools)})" for c in usable[:3]) + " — CLIVE composes it; call the tool rather than saying it cannot be done.]")
            session.hinted = True
    lines.extend(_family_lines(runtime))
    return lines


def _family_lines(runtime) -> list[str]:
    """The capability families the model CANNOT use, with the reason, so it stops trying them
    and says why.

    Only those: the families it can use are the tools it is offered, and
    `runtime.withheld_by_family` has already taken the others away, so listing fifteen READY
    families on every prompt would be five hundred characters a turn spent saying nothing
    (brief section 25). Read from the table the last capability check left on the runtime;
    nothing is probed on the turn.
    """
    from app.capabilities import families as families_mod

    table = getattr(runtime, "family_states_table", None) if runtime is not None else None
    if not table:
        table = {f.key: {"label": f.label, "state": f.state, "detail": f.detail, "scope": (f.scopes[0] if f.scopes else "")}
                 for f in families_mod.all_families()}
    lines = families_mod.words(table) if table else []
    if not lines:
        return []
    return [FAMILY_LINE_PREFIX + "\n".join(lines) + "]"]


# "Draft", "prepare", "write me" ask for something to read first. "Send", "email them",
# "let them know" ask for something to go. Both still need the owner's gesture; what differs
# is which change is staged, and staging the wrong one is not a small mistake.
_WANTS_DRAFT = re.compile(r"\b(?:draft|drafts?|prepare|prepared|write me|write out|put together|compose|mock up|rough out|have a go at)\b", re.I)
# "Reply to" is deliberately absent: it names what the email is, not whether it goes. A bare
# "reply to Millie" is left unhinted and the model decides, which is honest — the owner's
# gesture is what sends either way.
_WANTS_SEND = re.compile(r"\b(?:send|sends|email them|email him|email her|email the|let (?:them|him|her) know|tell (?:them|him|her)|get back to|chase|fire (?:it|them) off|(?:want|wants|wanted|get|have) (?:it|them) sent)\b", re.I)
# A draft or a send the owner says NOT to do: "no, don't save a draft, send it", "don't send it,
# just draft it". Read within the clause, so the correction is what steers the model (the
# 2026-09-28 deploy review, round 9, H-04: the words alone steered "don't save a draft" to one).
_NOT_DRAFT = re.compile(r"\b(?:don'?t|do not|not|no|never)\b[^.,;!?]{0,24}?\bdrafts?\b", re.I)
_NOT_SEND = re.compile(r"\b(?:don'?t|do not|not|never)\b[^.,;!?]{0,12}?\bsend\b", re.I)


def _draft_or_send(text: str) -> str:
    draft = bool(_WANTS_DRAFT.search(_NOT_DRAFT.sub(" ", text)))
    send = bool(_WANTS_SEND.search(_NOT_SEND.sub(" ", text)))
    if draft and not send:
        return "[This asks for a DRAFT: stage gmail_draft_reply or gmail_draft_new, not a send. Nothing is sent.]"
    if send and not draft:
        return "[This asks for the email to GO: stage gmail_send_reply or gmail_send_new. It still waits for the owner's gesture; a spoken yes never sends it.]"
    if send and draft:
        return "[This says both draft and send. Stage the DRAFT and say that sending it is a second gesture.]"
    return ""


def _short_query(query: dict) -> str:
    import json

    keep = {k: query[k] for k in ("tool", "entity", "period", "filters", "group_by", "metrics", "sort", "limit", "compare") if k in query and query[k] not in (None, [], {}, False)}
    return json.dumps(keep, ensure_ascii=False, default=str)[:300]


def _blocked_words(writes: dict) -> str:
    """Why a tap would be refused, in a clause the model can put in a sentence."""
    return str(writes.get("detail") or "changes cannot be applied from there.").rstrip(".") + "."


def _affirmation_answer(session, waiting=None) -> str:
    """What a spoken yes gets: the waiting card's own gesture, in its fixed sentence."""
    kind = getattr(waiting, "interaction", "tap_commit") if waiting is not None else "tap_commit"
    return affirmation_for(kind, blocked=bool(session.writes_blocked))


# A bare affirmation: a few words that mean "apply it", nothing else. "Yes, and cancel the
# order" is not one; neither is "fine" or "correct", which may answer a question the model
# asked, and must reach it.
_AFFIRMATIONS = frozenset({
    "yes", "yeah", "yep", "yup", "ok", "okay", "go", "go ahead", "go on", "do it", "do that",
    "confirm", "confirmed", "yes please", "please do", "apply it", "add it", "go ahead please",
    "yes do it", "yes go ahead", "ok go ahead", "okay go ahead",
})


# What may sit between the words of a bare yes and change nothing: spaces and the punctuation
# a recogniser or a keyboard puts round them. Nothing else. A digit, a "#", a "£" or an "@" is
# something he SAID, and a sentence carrying one is not a bare yes.
_HARMLESS = re.compile(r"[\s.,!?;:'\"‘’“”…–—-]+")
_WORD = re.compile(r"[a-z]+")


def is_affirmation(text: str) -> bool:
    """Whether the whole sentence is one of the fixed bare yeses, and nothing more.

    Every character is accounted for: the words must be the fixed list's and everything between
    them harmless punctuation. It used to delete whatever was not a letter first and then look
    the rest up, so "yes, #1938" and "yes 1938" were read as a bare "yes" — the model was never
    asked, the waiting card was not withdrawn, and the order number he named was dropped at the
    write boundary without a word (the 2026-09-28 deploy review, round 9, D2-02). A sentence
    with anything more in it is an instruction and goes to the model, which sees the card."""
    lowered = str(text or "").lower().replace("’", "'")
    words: list[str] = []
    for chunk in _HARMLESS.split(lowered):
        if not chunk:
            continue
        if not _WORD.fullmatch(chunk):
            return False
        words.append(chunk)
    if not words or len(words) > 4:
        return False
    return " ".join(words) in _AFFIRMATIONS


def _waiting_proposal(runtime, session, branch_id: str = ""):
    """The one proposal a spoken yes could refer to: pending, unexpired, this epoch, staged
    in THIS half of the orb, and a change the owner asked for — never the undo the Mac
    offered after a success, or "okay" said to "Note added" would be answered as if a card
    were waiting to be tapped; and never the other half's, which he is not looking at."""
    now = time.time()
    for proposal in reversed(session.proposals):
        if (
            proposal.status.value == "PENDING" and proposal.epoch == session.epoch
            and not proposal.expired(now) and proposal.undo_of is None and not proposal.batch_id
            and (not branch_id or str(getattr(proposal, "branch_id", "") or "") in ("", branch_id))
        ):
            return proposal
    # A batch's members are not cards of their own; the batch is the card.
    return runtime.batches.waiting(session)


def _now_line(runtime) -> str:
    """The clock, in the shop's own time zone, at the top of every question. "Yesterday" and
    "this morning" then mean what the owner means, whatever day the model believes it is."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(runtime.settings.shop_timezone)
    except Exception:  # noqa: BLE001
        tz = None
    now = datetime.now(tz)
    # Day without a leading zero, spelled out here rather than with a strftime flag that
    # differs between the Mac's libc and Linux's.
    return f"[Now: {now.strftime('%A')} {now.day} {now.strftime('%B %Y, %H:%M')} {runtime.settings.shop_timezone}]"


#: The cards that are one record, with the kind the branch calls it by and where the card
#: keeps its id and its name.
_RECORD_CARDS: dict[str, tuple[str, str, str]] = {
    "order": ("order", "order_id", "order_number"),
    "customer": ("customer", "customer_id", "name"),
    "email_thread": ("email_thread", "thread_id", "subject"),
}
#: The composed surfaces that are one record (app/workspace.py `compose`). `present()` puts
#: one of these in place of the record's own card when the task wanted more than one thing
#: about it, so it names its record itself: `kind` and `ref`, and a title to call it by.
_WORKSPACE_CARDS = frozenset({"order_workspace", "customer_workspace"})


def _card_record(item: Any) -> tuple[str, str, str] | None:
    """(kind, ref, label) of the one record a card is, or None for a card that is not one."""
    if not isinstance(item, dict):
        return None
    card = str(item.get("type") or "")
    data = item.get("data")
    if not isinstance(data, dict) or data.get("empty"):
        return None
    if card in _RECORD_CARDS:
        kind, id_key, label_key = _RECORD_CARDS[card]
        ref, label = str(data.get(id_key) or ""), str(data.get(label_key) or "")
    elif card in _WORKSPACE_CARDS:
        kind, ref = str(data.get("kind") or ""), str(data.get("ref") or "")
        # "Order #1938" is the order's title; the branch calls it "#1938", as the card does.
        title = str(data.get("title") or "")
        label = title[len("Order "):] if kind == "order" and title.startswith("Order ") else title
    else:
        return None
    return (kind, ref, label) if kind and ref else None


def _record_key(kind: str, ref: str) -> str:
    """One record, however its id arrived: a gid on one card and the same gid on a workspace
    are one order, and so are the order's number said two ways (app/entities.py)."""
    from app import entities

    return entities.key(kind, ref) or f"{kind}:{ref}"


def _records_shown(ui: list) -> dict[str, tuple[str, str, str]]:
    """Every distinct record the cards put on the screen, by canonical key, first card first."""
    out: dict[str, tuple[str, str, str]] = {}
    for item in ui or []:
        record = _card_record(item)
        if record is not None:
            out.setdefault(_record_key(record[0], record[1]), record)
    return out


# ------------------------------------------------ the order he named, and a change to another one
#
# Every sentence is the model's (the owner's decision of 28 September 2026), and nothing here
# answers one or reads anything for it. What is here runs AFTER the model, on what it did: when
# the owner plainly named an order and the model staged a change to a different one, the change
# is withdrawn before it is shown; when it read a different order and none he named, the answer
# says so in one short sentence and the half's cursor does not follow that order. The fast lane
# used to refuse these in front of the model; the write boundary is where a wrong record costs
# something, so that is where the Mac checks (the 2026-09-28 deploy review, round 9, D2-05,
# I-tests2 I-01, I-tests5 I-03).

#: An order number said as one: "#1940", "order 1940", "order number 1940", "order no. 1940",
#: "CROOKS-1940". Any other number counts only when it is an order this conversation already
#: holds (`_orders_known`) — "1940" once #1940 has been read, "orders 1938 and 1940" once both
#: have: "refund 150", "orders over 100" and "since 2025" are not orders, and nothing in their
#: shape says so, so a number the conversation has never seen as an order is left to the model
#: and to the card, which names its own order.
_ORDER_SAID = re.compile(r"(?:#\s?|\border\s+(?:number\s+|no\.?\s*|#\s?)?|\b[a-z]{2,12}-)(\d{3,7})\b", re.I)
_NUMBER = re.compile(r"(?<![\d£$€.,#-])(\d{3,7})(?!\d|[.,]\d)")
_TRAILING_NUMBER = re.compile(r"(\d{3,7})\s*$")


def _order_number(label: Any) -> str:
    """"1940" from "#1940" or "CROOKS-1940"; empty when the label carries no number."""
    match = _TRAILING_NUMBER.search(str(label or ""))
    return match.group(1) if match else ""


def _orders_read(calls, *, lists: bool = False) -> set[str]:
    """The numbers of the orders this turn read as orders: a record read on its own, and what
    an order search found. With `lists`, every order row any read returned as well."""
    out: set[str] = set()
    for call in calls or []:
        result = getattr(call, "result", None)
        if not getattr(call, "ok", False) or not isinstance(result, dict):
            continue
        if result.get("order_id") and result.get("order_number"):
            out.add(_order_number(result["order_number"]))
        rows = result.get("orders")
        if isinstance(rows, list) and (lists or getattr(call, "name", "") == "shopify_find_order"):
            for row in rows:
                if isinstance(row, dict) and row.get("order_number"):
                    out.add(_order_number(row["order_number"]))
    out.discard("")
    return out


def _orders_known(session, branch, calls) -> set[str]:
    """Every order number this conversation holds: on its context stack, under the half's
    cursor, on a change it staged, and in what this turn read."""
    known = _orders_read(calls, lists=True)
    for entry in getattr(session, "context", None) or []:
        if isinstance(entry, dict) and entry.get("kind") == "order":
            known.add(_order_number(entry.get("label")))
    entity = getattr(branch, "entity", None) or {}
    if entity.get("kind") == "order":
        known.add(_order_number(entity.get("label")))
    for proposal in getattr(session, "proposals", None) or []:
        if getattr(proposal, "entity_kind", "") == "order":
            known.add(_order_number(getattr(proposal, "entity_label", "")))
    known.discard("")
    return known


def _orders_named(text: str, known: set[str]) -> frozenset[str]:
    """The order numbers the owner's own words name — said as an order, or a number that is an
    order this conversation holds. Only his words: never the note a tapped control put beside
    them, which names the record the tap bound and not what he said next."""
    words = str(text or "")
    said = set(_ORDER_SAID.findall(words))
    said.update(n for n in _NUMBER.findall(words) if n in known)
    return frozenset(said)


def _spoken_orders(numbers) -> str:
    return " and ".join(f"#{n}" for n in sorted(numbers))


def _off_target(proposed: list[str], session, named: frozenset[str]) -> list[str]:
    """The changes this turn staged on an order the owner did not name, when he named one.

    A change to an order is the owner's only when it is to the order he said. "Add a note to
    1940" after Add a note was tapped on #1938, or "yes, #1940" over a refund waiting on #1938,
    must not come back as a card for #1938, however the model read the words. A change whose
    order cannot be told from its card is not his either. A bulk change is over a set and a
    change to anything but an order names its own record; neither is judged here."""
    off: list[str] = []
    for proposal_id in proposed:
        if str(proposal_id).startswith("batch_"):
            continue
        proposal = session.proposal(proposal_id)
        if proposal is None or getattr(proposal, "entity_kind", "") != "order":
            continue
        number = _order_number(getattr(proposal, "entity_label", ""))
        if not number or number not in named:
            off.append(proposal_id)
    return off


def _off_target_words(session, off: list[str], named: frozenset[str]) -> str:
    """What the owner is told instead of the model's sentence about a change that was withdrawn."""
    targets = {_order_number(getattr(session.proposal(p), "entity_label", "")) for p in off}
    targets.discard("")
    were = _spoken_orders(targets) if targets else "another order"
    return (f"You said {_spoken_orders(named)}, but the change I'd prepared was for {were}, so I've "
            "withdrawn it. Say which order you want it on.")


def _stand_on_what_was_shown(branch, ui: list, named: frozenset[str] = frozenset()) -> None:
    """The record the model put on the screen is the record the owner is now on — when there
    is exactly one.

    Everything the tablet does next under a finger — Add a note, Reply, Back, the next tab —
    acts on the branch's cursor, never on what a card happens to show. Only the word-matching
    lane used to move that cursor for a sentence, so once every sentence became a model turn,
    "show me order 1938" drew the order and left the cursor where it was: Add a note on that
    card was refused as "no order open". This follows the cards, not the words.

    One record shown — as its own card or as the workspace composed over it — is where he now
    is. Anything else moves nothing: several orders are a list, and an order beside a
    customer is two records, of which the Mac cannot say which he means. It used to take the
    first record card and count only its own kind, so an order and a customer moved the
    cursor to whichever came first, and a workspace, which is what `present()` draws in
    place of the card when the task asked for more than one thing, moved nothing at all and
    left the cursor on the record before (the 2026-09-28 deploy review, round 9, D2-04,
    D1-02). Staying put is safe for the write boundary: the one control that binds the cursor
    to a change — a listening chip such as Add a note — is only offered on the card that IS
    the cursor (`_bind_listening_to_cursor`), and every other change names its own record (a
    row's id, an open chip's arguments, or the words said).

    Nor does it follow an order the owner did not name when he named one (`named`): "what's
    the status of #1940" answered with #1938's card leaves the cursor where it was, so a tapped
    Add a note cannot bind an order he never asked about (D2-05).
    """
    records = _records_shown(ui)
    if len(records) != 1:
        return
    ((kind, ref, label),) = records.values()
    if named and kind == "order" and _order_number(label) not in named:
        return
    entity = getattr(branch, "entity", None) or {}
    if entity.get("kind") == kind and _record_key(kind, str(entity.get("ref") or "")) == _record_key(kind, ref):
        return
    branch.visit(kind, ref, label)


def _bind_listening_to_cursor(ui: list, entity: dict | None) -> None:
    """Keep a listening control only on the card whose record is the half's cursor.

    A rail chip in "ask" mode that names a spoken control (`family`, e.g. order.add_note) binds
    the next sentence to the record the tablet holds as this half's entity — the cursor — and
    not to the card the chip is drawn on (web/app.js `primeAction`). On a screen with two
    records, or with one the cursor did not move to, that chip would bind a record other than
    the one under the owner's thumb, and the note he dictates would be staged against it. So
    on every other card the chip loses its `family`: a tap still primes its words, which name
    that card's own record ("Add a note to #1940"), and the model reads the record from the
    words. Nothing is removed and nothing can bind the wrong record.
    """
    here = entity or {}
    cursor = _record_key(str(here.get("kind") or ""), str(here.get("ref") or "")) if here.get("ref") else ""
    for item in ui or []:
        record = _card_record(item)
        if record is None or (cursor and _record_key(record[0], record[1]) == cursor):
            continue
        for action in (item["data"].get("actions") or []):
            if isinstance(action, dict) and action.get("family") and str(action.get("mode") or "ask") == "ask":
                action["family"] = ""


#: Where each record a replay rebuilds keeps its id (app/commands.py REPLAY_TOOL).
_ID_OF_KIND = {"order": "order_id", "customer": "customer_id", "email_thread": "thread_id"}


def _keep_what_was_read(calls) -> None:
    """The records the model read, kept where a tap finds them (app/commands.py `replay`).

    Back, a tapped link and a replayed card rebuild a record from the entity tier rather than
    asking the shop again. Only the word-matching lane's recipes used to put records there, so
    once every sentence became a model turn, Back onto the order he had just asked for read
    Shopify a second time. These are the same reads a replay rebuilds from, kept as they came
    back; who may see them is still decided at replay, against the conversation's issued ids.
    """
    from app.commands import REPLAY_TOOL
    from app.memory import ENTITY
    from app.memory import current as memory

    kind_of = {tool: kind for kind, tool in REPLAY_TOOL.items()}
    for call in calls or []:
        kind = kind_of.get(getattr(call, "name", ""))
        result = getattr(call, "result", None)
        if kind is None or not getattr(call, "ok", False) or not isinstance(result, dict) or result.get("reused"):
            continue
        key = _ID_OF_KIND[kind]
        ref = str(result.get(key) or (getattr(call, "args", None) or {}).get(key) or "")
        if not ref:
            continue
        try:
            memory().put(ENTITY, f"{kind}:{ref}", result, source="gmail" if kind == "email_thread" else "shopify",
                         query=f"model:{call.name}", provenance={"tool": call.name, "ref": ref})
        except Exception as exc:  # noqa: BLE001 — a cold cache is a slower Back, not a failed turn
            log.debug("could not keep what the model read: %s", exc)


def _ui_entities(ui: list) -> list[dict]:
    """Which records the cards showed, by kind and id — never their contents."""
    out: list[dict] = []
    for item in ui or []:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            continue
        kind = str(item.get("type") or "")
        named = item.get("entity") if isinstance(item.get("entity"), dict) else None
        ref = (named or {}).get("ref") or data.get("order_id") or data.get("customer_id") or data.get("thread_id") or data.get("proposal_id") or ""
        if not ref and kind in ("product", "inventory") and isinstance(data.get("products"), list) and data["products"] and isinstance(data["products"][0], dict):
            ref = data["products"][0].get("product_id") or ""
        if ref:
            out.append({"type": kind, "ref": str(ref)[:80]})
    return out


def _loggable_args(call) -> dict:
    """What the turn log keeps of a tool call's arguments. A write tool's content — the note
    the owner dictated — is logged by length only, whether or not it became a proposal: a
    refused or unpreparable note is still the owner's words about a customer."""
    args = call.args or {}
    if call.proposal_id or _is_write_tool(call.name):
        return {k: (str(v)[:80] if k.endswith("_id") else f"<{len(str(v))} chars>") for k, v in args.items()}
    return redact({k: str(v)[:80] for k, v in args.items()})


def _is_write_tool(name: str) -> bool:
    from app.tools import registry

    try:
        spec = registry.get(name)
        return spec.write is not None or spec.batch is not None
    except KeyError:
        return False


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _ensure_provider_started(runtime) -> None:
    """If the provider failed at boot (token not yet stored, say), retry now rather than
    answering "still starting up" until someone restarts the process."""
    provider = runtime.provider
    if getattr(provider, "_started", True):
        return
    try:
        await provider.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("provider start retry failed: %s", exc)


def _moved_on(session, branch, *, epoch: int | None, seq: int | None) -> bool:
    """Whether the owner has replaced the question this answer is for.

    Judged per half when the turn knows its half: a /cancel aimed at it, or a later
    instruction to it. The session's epoch moves for the OTHER half's instruction too, so
    with two halves thinking at once the epoch alone would call every slower answer
    abandoned — unspoken, its proposals withdrawn — because the owner asked the other half
    something meanwhile. A turn with no half (a test double, an early error) keeps the
    session-wide rule.
    """
    if bool(getattr(session, "abandoned", False)):
        return True
    if branch is not None and seq is not None:
        return bool(getattr(branch, "abandoned", False)) or int(getattr(branch, "instruction_seq", 0) or 0) != int(seq)
    return epoch is not None and session.epoch != epoch


async def _provider_turn(runtime, session_id: str, prompt_text: str, branch):
    """The model turn, on this half's own conversation when the provider keeps one per half.
    A provider without the method — a test double — gets the plain turn."""
    on_branch = getattr(runtime.provider, "turn_on_branch", None)
    branch_id = str(getattr(branch, "branch_id", "") or "")
    if on_branch is not None and branch_id:
        return await on_branch(session_id, prompt_text, branch_id=branch_id)
    return await runtime.provider.turn(session_id, prompt_text)


class _SceneSwitch(BaseSettings):
    """CLIVE_SCENES: whether a turn also carries a validated scene (Generative UI V1,
    docs/product-memory/GENERATIVE_UI_V1.md). Read as config/settings.py reads every setting —
    the environment, then the same .env file — once, and off unless it is set."""

    model_config = SettingsConfigDict(env_prefix="CLIVE_", env_file_encoding="utf-8", extra="ignore")

    scenes: bool = False


@lru_cache(maxsize=1)
def scenes_enabled() -> bool:
    from config.settings import _env_file

    return _SceneSwitch(_env_file=_env_file()).scenes


def _writing_id(timeline) -> str | None:
    session = timeline.active
    return session.test_session_id if session is not None else None


def _turn_scene(question: str, answer: str, calls: list | None, session_id: str) -> dict | None:
    """The turn's scene and its decision trace when CLIVE_SCENES is on, and nothing when it is
    off. Beside the cards, never instead of them, and never at the cost of the turn: a failure
    anywhere in it is logged by its kind alone — its message can carry the answer's words or a
    customer's — and the turn goes out without a scene."""
    try:
        if not scenes_enabled():
            return None
        from app.scenes.planner import scene_for_turn

        return scene_for_turn(question, answer, calls or [], session_id=session_id)
    except Exception as exc:  # noqa: BLE001 — a scene is never worth a turn
        log.warning("scene not built: %s", type(exc).__name__)
        return None


async def _answer(
    runtime,
    session_id: str,
    answer: str,
    *,
    request: Request | None = None,
    error_kind: str | None = None,
    timings: dict,
    started: float,
    transcript: dict | None = None,
    question: str = "",
    tool_calls: list | None = None,
    lost_thread: bool = False,
    calls: list | None = None,
    speak: bool = False,
    epoch: int | None = None,
    revoked: list[str] | None = None,
    writes: dict | None = None,
    branch: Any = None,
    measures: dict | None = None,
    seq: int | None = None,
    turn_id: str = "",
) -> dict:
    tool_calls = tool_calls or []
    turns = 0
    names: set[str] = set()
    session = None
    try:
        session = runtime.sessions.get(session_id)
        turns = session.turns
        names = set(session.pii_seen)
    except KeyError:
        pass
    # D-15. The one call that feeds the timeline's redaction seam. Redacting at each call site
    # is what left three real customer email addresses in the 11 September file: `tts.text`,
    # `model.answer` and `prediction.key` are written by other code, and nothing told them.
    # `app/observability/timeline.py::scrub` takes contact details out by SHAPE on every event
    # whether or not this runs; a NAME is not a shape, and this is the place that knows them.
    timeline.note_names(names)
    # Abandoned: the owner cancelled, or asked something else while this was being answered.
    # The session's position has moved past this turn's; nobody is waiting for its voice.
    abandoned = bool(session is not None and _moved_on(session, branch, epoch=epoch, seq=seq))
    proposed = [c.proposal_id for c in (calls or []) if getattr(c, "proposal_id", None)]
    if abandoned and proposed:
        # Claude was still running when the owner moved on, and staged a change into the
        # conversation's new position. Nobody asked for it there: withdrawn, unsent.
        runtime.actions.revoke_ids(proposed, "the owner moved on")
        runtime.batches.revoke_ids(proposed, "the owner moved on")
        proposed = []
    # The order the owner named, held against what the model did with it — on a model turn
    # (`seq`), which is the only place a change is staged from words. A change to another order
    # is withdrawn before it is delivered and drawn nowhere; a read of another order and none
    # he named is said to be that, in one sentence, and does not move the cursor (see
    # `_off_target`, `_stand_on_what_was_shown`).
    named: frozenset[str] = frozenset()
    withheld: set[str] = set()
    if seq is not None and session is not None and not abandoned:
        named = _orders_named(question, _orders_known(session, branch, calls))
    if named:
        off = _off_target(proposed, session, named)
        if off:
            log.warning("withdrew %d change(s) staged on an order the owner did not name", len(off))
            answer = (LOST_THREAD_PREFIX if lost_thread and answer.startswith(LOST_THREAD_PREFIX) else "") + _off_target_words(session, off, named)
            runtime.actions.revoke_ids(off, "not the order the owner named")
            withheld = set(off)
            proposed = [p for p in proposed if p not in withheld]
        else:
            read = _orders_read(calls)
            if read and not (read & named):
                answer = f"{answer.rstrip()} That's {_spoken_orders(read)}, not {_spoken_orders(named)}."
    # A change was proposed this turn. Say, now and in the same breath, whether a tap on THIS
    # tablet could apply it — a card that cannot be applied must never look as if it can.
    if proposed and writes is None and request is not None:
        writes = await writes_context(request)
    if proposed and writes is not None and not writes["allowed"] and writes["spoken"]:
        answer = f"{answer.rstrip()} {writes['spoken']}"
    # `writes` on the wire is about a proposal: it tells the tablet whether a tap on the card
    # this turn produced could apply it, and on a turn that proposed nothing there is nothing
    # for it to describe. But the same table is also where the order card's rail comes from —
    # which changes make sense for THIS order and which the store has granted — and a read
    # turn is exactly when the rail matters. Nulling the one variable did both, so every
    # order looked up came back with an empty `actions` list and nothing to do with it. The
    # rail keeps the table; the payload keeps its old contract.
    rail = writes
    if not proposed:
        writes = None
    # The card leaves for the tablet now; its wait for the tap starts now.
    for proposal_id in proposed:
        if proposal_id.startswith("batch_"):
            runtime.batches.deliver(proposal_id)
        else:
            runtime.actions.deliver(proposal_id)
    if speak and answer and not abandoned:
        # Start the voice now: by the time the tablet has this JSON and asks /speak, the MP3
        # is already generating. The same request it would make anyway, just earlier. An
        # error line is a fixed sentence: synthesised once, kept, free and instant after that.
        # A question the owner abandoned (/cancel) gets no voice: nobody will ask for it.
        runtime.voice.prefetch(
            to_speakable(answer, max_chars=runtime.voice.max_chars), pin=bool(error_kind) or answer in FIXED_LINES
        )
    # Replaced, as opposed to merely cancelled: a newer instruction to this half is running
    # now, and everything that says what this half is doing belongs to it — the session's
    # state, the chip's WORKING, the count of turns in flight (which that instruction reset
    # when it began). A turn the owner only cancelled, with nothing after it, still ends here.
    cancelled = bool(session is not None and (getattr(session, "abandoned", False) or getattr(branch, "abandoned", False)))
    replaced = abandoned and not cancelled
    # The turn is over: whatever it was doing (hearing, checking Shopify, thinking), the
    # session says so now, so a /state poll that outlives the turn cannot report otherwise.
    if session is not None and not replaced and session.state not in ("READY", "ERROR"):
        session.set_state("ERROR" if error_kind else "READY")
    timings["total"] = (time.perf_counter() - started) * 1000
    if branch is None and session is not None:
        branch = session.branch()
    # The turn's own id, not the session's: the session's is the NEXT turn's as soon as one
    # has started, and an answer that finished late must not be filed under its replacement.
    turn_id = turn_id or (getattr(session, "turn_id", "") if session is not None else "")
    if abandoned:
        # Nobody is waiting for this answer, and the half has moved on to another question
        # (the 2026-09-28 deploy review, round 9, D2-01). It publishes nothing: no cards, so the
        # context stack and the entity graph are not handed an old record as though it were
        # new; no `shown`, so tapping the half does not redraw it; no cursor, so "cancel it"
        # and a tapped Add a note act on what the newer answer showed and not on the order
        # this one read; and no reconciliation, because the live workspace on this half is
        # the newer turn's. What it read is still kept where a replay finds it — reads are
        # facts, and Back onto that order later need not ask the shop again.
        ui: list[dict[str, Any]] = []
        scene = None
        timings["workspace"] = (time.perf_counter() - started) * 1000
        if branch is not None and not replaced:
            if seq is not None:
                branch.end_turn()
            branch.idle()
        _keep_what_was_read(calls)
        glass: dict[str, Any] = {}
    else:
        # What the screen shows beside the answer: cards chosen from the tool results, never
        # from the prose. See app/presentation.py for the vocabulary and the bounds.
        ui = present([c for c in (calls or []) if getattr(c, "proposal_id", None) not in withheld] if withheld else calls,
                     session=session, error_kind=error_kind, writes=rail)
        # The same turn as a validated scene, when CLIVE_SCENES is on: planned from these
        # reads, carried as its own field and changing nothing else. Off, nothing here runs.
        scene = _turn_scene(question or str((transcript or {}).get("text") or ""), answer, calls, session_id)
        # One cursor, one headline per kind, the rest folded (brief section 22).
        ui = compact(ui)
        # When the Mac had cards to show, as a fact and not an inference (brief section 25
        # asks for time-to-first-useful-workspace measured APART from the whole turn). Taken
        # here, after present(), because this is the moment the workspace exists.
        timings["workspace"] = (time.perf_counter() - started) * 1000
        if branch is not None:
            # The answer is here. A half the owner is looking at simply goes quiet; one he has
            # put aside — or simply tapped away from while it was working — says "ready" on
            # its chip and pulses once, and does not take his attention. The live test found a
            # half that finished a ten-second turn with zero change on the tablet and an answer
            # that could never be read: it was not BACKGROUND, only not looked at, so it went
            # idle.
            elsewhere = bool(session is not None and getattr(session, "focused_branch", "") and session.focused_branch != branch.branch_id)
            # The turn is over however it ended. Counted down first, so nothing below can leave
            # a half saying it is working when it is not — and only by a turn that counted
            # itself in: a refusal before the model (nothing heard, a spoken yes) never began,
            # and must not end the turn another request has in flight on this half.
            if seq is not None:
                branch.end_turn()
            if error_kind:
                branch.failed("that did not work")
            elif branch.status == "BACKGROUND" or elsewhere:
                branch.ready("there is an answer")
            else:
                branch.idle()
            if not error_kind:
                _stand_on_what_was_shown(branch, ui, named)
            # A control on a card that listens for words binds the half's cursor, not the card
            # it sits on (web/app.js `primeAction` posts the branch's entity). So only the card
            # that IS the cursor keeps one; every other card's chip primes its words and binds
            # nothing, and those words name its own record (D2-04, D1-02).
            _bind_listening_to_cursor(ui, getattr(branch, "entity", None))
            # What this half now shows, kept on the Mac so tapping it later draws it (branch.show).
            branch.shown(ui, answer, question)
        for call in calls or []:
            if branch is not None and getattr(call, "ok", False):
                branch.remember_result(call.name, summary=_call_summary(call), ref=_call_ref(call), ms=float(getattr(call, "duration_ms", 0.0) or 0.0))
        _keep_what_was_read(calls)
        # The turn's own cards, reconciled against what the progressive workspace already put
        # on the glass (§7, §25). A card that is unchanged is NOT redrawn — the whole point —
        # and one that gained its rail or an enrichment is patched in place. The numbers come
        # back for the performance record; the patches themselves the tablet has already
        # collected from /state.
        glass = progressive.complete(session, ui, branch_id=getattr(branch, "branch_id", "") or "")
    # How this turn actually went, in numbers. Every field is measured; none of it is content.
    # This is what the report's speed section and the bench read (brief section 32).
    performance = _performance(timings, branch=branch, calls=calls, session=session, measures=measures or {}, ui=ui, glass=glass)
    # An answer that declines, held against what the Mac composes: a refusal of a best
    # seller, a breakdown, a comparison or a bulk change the tools could have made is a
    # FALSE UNSUPPORTED claim, and the report counts it. Words only; no reasoning text. The
    # gap record counts it too, apart from the gaps: CLIVE misjudging what it can do.
    from app.objectives import gaps as gap_record
    from app.observability import claims

    record = gap_record.ledger()
    signal = None
    if timeline.current().active is not None or record is not None:
        signal = claims.claim(question or (transcript or {}).get("text") or "", answer, tool_calls, claims.registered(), hinted=bool(getattr(session, "hinted", False)))
        if record is not None and signal is not None and signal.get("false_unsupported"):
            record.note_misjudged(list(signal.get("capabilities") or []))
    if timeline.current().active is not None:
        if signal is not None:
            timeline.emit("unsupported_claim", session_id=session_id, turn_id=turn_id or None, **signal)
        timeline.emit(
            "turn_performance", session_id=session_id, turn_id=turn_id or None, **performance,
        )
        timeline.emit(
            "turn_finished", session_id=session_id, turn_id=turn_id or None, ms=round(timings["total"], 1),
            timings={k: round(v, 1) for k, v in timings.items()}, question=_written(question or (transcript or {}).get("text") or "", names) or None,
            # Redacted by the same rule the turn log uses, and for the same reason: the
            # answer may carry a street address the owner asked to be read out. He may hear
            # it; the timeline and the report built from it get "[address]".
            answer=_written(answer, names), error_kind=error_kind, lost_thread=lost_thread, abandoned=abandoned,
            ui=[item["type"] for item in ui], ui_entities=_ui_entities(ui), proposed=proposed or None, revoked=list(revoked or []) or None,
            # What the owner was actually shown, as a fact separate from which components drew
            # it: the surfaces this turn produced, whether anything was shown at all, and what
            # it offered to do next. A turn that answered in words and drew nothing is the
            # failure this pass exists for, and `surfaces: []` is what it looks like here.
            surfaces=[item.get("surface") or item["type"] for item in ui if item["type"] != "context_stack"] or None,
            showed_nothing=not any(item["type"] != "context_stack" for item in ui),
            actions=sorted({
                str(a.get("operation") or a.get("id") or "")
                for item in ui if isinstance(item.get("data"), dict)
                for a in (item["data"].get("actions") or []) if isinstance(a, dict)
            }) or None,
            writes_code=(None if writes is None or writes.get("allowed") else writes.get("code")),
            speak_requested=speak, tts_prefetched=bool(speak and answer and not abandoned),
            tool_calls=[{"tool": c.get("name"), "ok": c.get("ok"), "ms": c.get("ms"), "tool_call_id": c.get("tool_call_id") or None, "proposal_id": c.get("proposal_id")} for c in tool_calls] or None,
        )
    payload = {
        "session_id": session_id,
        "turn_id": turn_id,
        # Whatever is being written down — a test session or a production recording — so the page
        # keeps its telemetry on through the turn. `active_id` names the test session alone, and a
        # recording answered null here, which switched the page's telemetry off after every turn
        # until the next /health poll turned it back on.
        "test_session_id": _writing_id(timeline.current()),
        "turns": turns,
        "answer": answer,
        "question": question or (transcript or {}).get("text", ""),
        "error_kind": error_kind,
        "lost_thread": lost_thread,
        "state": "ERROR" if error_kind else "READY",
        "last_state": _tool_state([c["name"] for c in tool_calls]),
        # The page files this answer was made for. A tablet running an older page learns it
        # here, at the end of the turn, rather than at the next health poll.
        "build": runtime.build,
        "writes": writes,
        # Cards this instruction withdrew. The tablet settles exactly these, no others.
        "revoked": list(revoked or []),
        "tool_calls": tool_calls,
        "transcript": transcript,
        "timings_ms": {k: round(v, 1) for k, v in timings.items()},
        "ui": ui,
        # Which lane answered — always the model's on this route; a tap is TOUCH on /command —
        # and where the conversation now is. The tablet renders its navigation from this
        # rather than from what it can see on screen.
        "lane": "NORMAL",
        "branch": branch.public() if branch is not None else None,
        # Both halves, when there are two, so the tablet draws what the Mac holds rather
        # than what it remembers doing.
        "branches": (
            {"focused": session.focused_branch,
             "branches": [b.public() for b in session.branches.values() if b.status in ("ACTIVE", "BACKGROUND")]}
            if session is not None and session.branches else None
        ),
        "partial": False,
        "performance": performance,
        # What the glass still needs to agree with this payload (§7). The tablet has been
        # collecting patches from /state while the turn ran and stops the moment this arrives,
        # so the last reconciliation rides here: the cards it already drew are NOT in it, and
        # that is the point — an unchanged card is not redrawn at the end of a turn.
        "workspace": {
            "turn_id": glass.get("turn_id") or turn_id,
            "revision": glass.get("revision"),
            "complete": True,
            "patches": glass.get("patches") or [],
            "renders": glass.get("renders"),
            "timings_ms": {k: glass.get(k) for k in progressive.TIMINGS},
        } if glass else None,
    }
    # The cards repeat what the tools returned, which the log already has in redacted form;
    # the log keeps only which kinds were shown. The workspace's patches carry the same cards
    # again — a customer's name, an address, an email body — so the log keeps their SHAPE and
    # not their contents, for exactly the reason the line above exists.
    runtime.turnlog.write({
        **payload,
        "ui": [item["type"] for item in ui],
        "workspace": {
            "revision": (payload.get("workspace") or {}).get("revision"),
            "patches": [f"{p.get('op')}:{p.get('id')}" for p in ((payload.get("workspace") or {}).get("patches") or [])],
            "renders": (payload.get("workspace") or {}).get("renders"),
            "timings_ms": (payload.get("workspace") or {}).get("timings_ms"),
        } if payload.get("workspace") else None,
    }, names=names)
    # After the log is written: a scene can bind a customer's name to a row, and the log keeps
    # which cards were shown, not what they said.
    if scene is not None:
        payload["scene"] = scene
    return payload


@router.get("/state/{session_id}")
async def state(request: Request, session_id: str, since: int = 0, branch_id: str = "") -> dict:
    """What the assistant is doing right now. The page polls this during a turn so the
    screen says CHECKING SHOPIFY because shopify_list_orders is actually running, not because
    the question had the word "orders" in it."""
    runtime = request.app.state.runtime
    try:
        session = runtime.sessions.peek(session_id)
    except KeyError:
        return {"session_id": session_id, "known": False, "state": "READY", "detail": ""}
    if not session_matches(session, request):
        return JSONResponse(status_code=403, content={"code": "wrong_session", "detail": "That conversation belongs to another login."})
    # The workspace as it stands, from the cursor the tablet last applied. This is the channel
    # progressive hydration travels on: the tablet already polls this route every 400 ms to
    # say CHECKING SHOPIFY, so the cards a landed read produced ride back on a request it was
    # making anyway — no stream, no second socket, and nothing to keep alive.
    workspace = progressive.current(session_id, str(branch_id or getattr(session, "focused_branch", "") or ""))
    return {
        "session_id": session_id,
        "known": True,
        "state": session.state,
        "detail": session.state_detail,
        "turns": session.turns,
        "epoch": session.epoch,
        "heard": session.heard,
        "workspace": workspace.public(since) if workspace is not None else None,
    }


@router.post("/cancel")
async def cancel(request: Request, session_id: str = Form(default=""), branch_id: str = Form(default="")) -> dict:
    """The owner has moved on: he is holding the orb again while the last question is still
    being thought about. Interrupt Claude, and stop synthesising any answer nobody will hear.
    Nothing applied is undone; whatever the abandoned turn had proposed is withdrawn, unsent.

    With a `branch_id`, one half of a divided orb: that half's turn is interrupted and its
    waiting cards withdrawn, and the other half — which may be thinking about something else
    entirely — is not touched. Without one, the whole session, as before."""
    runtime = request.app.state.runtime
    interrupted = False
    revoked: list[str] = []
    branch_id = str(branch_id or "")[:32]
    if session_id:
        # Marked whether or not the turn has reached Claude yet — a hold during transcription
        # counts — and even before the session's first turn has created it. Anything the
        # abandoned turn proposed is withdrawn with it.
        live = runtime.sessions.get_or_create(session_id)
        if not session_matches(live, request):
            return JSONResponse(status_code=403, content={"code": "wrong_session", "detail": "That conversation belongs to another login."})
        half = live.branches.get(branch_id) if branch_id else None
        if half is not None:
            half.abandoned = True
            revoked = runtime.actions.revoke_pending(live, "turn abandoned", undos=True, branch_id=half.branch_id) + runtime.batches.revoke_pending(live, "turn abandoned", undos=True)
            runtime.actions.advance_epoch(live, "turn abandoned", branch_id=half.branch_id)
            interrupted = await _interrupt(runtime, session_id, half.branch_id)
        else:
            live.abandoned = True
            # Named, so the tablet settles exactly the cards this withdrew rather than guessing.
            revoked = runtime.actions.revoke_pending(live, "turn abandoned", undos=True) + runtime.batches.revoke_pending(live, "turn abandoned", undos=True)
            runtime.actions.advance_epoch(live, "turn abandoned")
            interrupted = await _interrupt(runtime, session_id, "")
    stopped = runtime.voice.cancel_prefetches()
    return {"cancelled": True, "interrupted": interrupted, "prefetches_stopped": stopped, "revoked": revoked}


async def _interrupt(runtime, session_id: str, branch_id: str) -> bool:
    """The provider's interrupt, by half when it can tell halves apart. A test double whose
    interrupt takes only the session gets only the session."""
    import inspect

    interrupt = runtime.provider.interrupt
    try:
        takes_branch = "branch_id" in inspect.signature(interrupt).parameters
    except (TypeError, ValueError):
        takes_branch = False
    if branch_id and takes_branch:
        return bool(await interrupt(session_id, branch_id=branch_id))
    return bool(await interrupt(session_id))


@router.post("/audio-test")
async def audio_test(request: Request, audio: UploadFile = File(...)) -> dict:
    """M2's endpoint. Kept afterwards because "is the microphone alright today" stays useful."""
    runtime = request.app.state.runtime
    blob = await audio.read()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = (audio.filename or "").rsplit(".", 1)
    # Kept on disk only when captures are asked for, like every other recording.
    save_to = (
        runtime.settings.bench_audio_dir / f"{stamp}.{suffix[-1] if len(suffix) > 1 else 'webm'}"
        if runtime.settings.save_captures else None
    )
    try:
        decoded = await asyncio.to_thread(decode, blob, save_to=save_to)
    except DecodeError as exc:
        return {"ok": False, "error": str(exc), "bytes_in": len(blob),
                "mime_type": audio.content_type}
    return {
        "ok": True,
        "mime_type": audio.content_type,
        "saved_to": str(decoded.saved_to) if decoded.saved_to else None,
        # The decoded WAV, so the page can play back exactly what the backend heard (M2).
        "wav_base64": base64.b64encode(decoded.as_wav()).decode("ascii"),
        **decoded.stats.as_dict(),
    }


@router.post("/reset")
async def reset(request: Request, session_id: str = Form(default="")) -> dict:
    runtime = request.app.state.runtime
    if session_id:
        try:
            existing = runtime.sessions.peek(session_id)
        except KeyError:
            existing = None
        if existing is not None and not session_matches(existing, request):
            return JSONResponse(status_code=403, content={"code": "wrong_session", "detail": "That conversation belongs to another login."})
        runtime.actions.forget_session(session_id)
        runtime.sessions.drop(session_id)
        await runtime.provider.reset_session(session_id)
    return {"reset": True}
