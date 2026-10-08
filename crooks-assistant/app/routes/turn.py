"""POST /turn — the whole product, in one endpoint.

Accepts text (development, and the typed interface that keeps allowance testing cheap) or audio
(the tablet). Both converge on the same agent path, which is what made M11 nearly trivial.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import focus, progressive, screen
from app.actions import engine as action_engine
from app.actions.grammar import AFFIRMATION_BLOCKED, affirmation_for, words_for
from app.actions.grammar import FIXED_LINES as GRAMMAR_FIXED_LINES
from app.logging.turnlog import redact
from app.observability import interactions, timeline
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
# What a team member is told when their turn cannot be taken (app/people): in words, as every refusal here.
TEAM_TYPES = "The team types to CLIVE: type your question instead of speaking it."
NO_STAFF_ASSISTANT = "CLIVE cannot answer the team on this server just now."


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

    if _staff_request():
        # The voice is the owner's ElevenLabs allowance, and /speak refuses the team: a team
        # member's turn never starts it, whatever the page asked for. Nor does it hear them — the
        # team types to CLIVE — so an upload is refused before anything listens to it.
        speak = False
        if audio is not None:
            log.warning("turn refused: a team member sent audio")
            return JSONResponse(status_code=403, content={"code": "team_types", "detail": TEAM_TYPES})
        # Their own assistant or none: never the owner's, which holds his conversations.
        from app.runtime import NoStaffAssistant

        try:
            _provider(runtime)
        except NoStaffAssistant:
            log.warning("turn refused: no assistant can be made for a team member")
            return JSONResponse(status_code=403, content={"code": "no_staff_assistant", "detail": NO_STAFF_ASSISTANT})

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
        await _provider(runtime).reset_session(session_id)
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
    # The workspace starts NOW, and QUIET (DEC-069, 7 Oct): a search in progress never takes the
    # screen. While the reads run the tablet's /state poll carries what CLIVE is doing, in
    # words; the cards come with the answer, and only what the answer is about (app/focus.py).
    progressive.begin(session_id, turn_id=turn_id, branch_id=branch.branch_id, quiet=True)

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
    for extra in _context_lines(live, text, runtime=runtime, branch=branch):
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
        # The control he tapped before saying this, spent on this sentence: what the model staged
        # under it is held to the record it bound (`_off_target`), not only told about it.
        binding=continuation,
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
    # A new order being built on this half: "add a print to it" is a change to THAT card, and
    # the model is told it is there rather than left to open another (round 12).
    from app.families.order_create import where_line

    building = where_line(branch)
    if building:
        bits.append(building)
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

def _context_lines(session, text: str, runtime=None, branch=None) -> list[str]:
    """What the Mac knows that the model would otherwise guess at, one line each: the last
    gesture's counted outcome (once), the last query's shape (for a follow-up), and which
    composable capability the question's words name (so it is reached for, not declined)."""
    from app.observability import claims

    lines: list[str] = []
    # Told to the half it happened in, once: the two halves are two conversations with the model.
    half = str(getattr(branch, "branch_id", "") or "")
    kept = getattr(session, "last_withdrawn", None)
    withdrawn = str(kept.pop(half, "") if isinstance(kept, dict) else "").strip()
    if withdrawn:
        lines.append(f'[CLIVE withdrew the change you prepared last time before the owner saw it, and told him: "{withdrawn[:240]}" '
                     "Nothing is on a card. If what he says now answers that, prepare the change again where he says.]")
    outcome = str(getattr(session, "last_outcome", "") or "").strip()
    if outcome:
        lines.append(f'[The last change, as CLIVE proved it: "{outcome[:200]}". If asked whether it worked, say this; do not propose it again.]')
        session.last_outcome = ""
    session.hinted = False
    last = getattr(session, "last_query", None)
    if isinstance(last, dict) and last:
        lines.append(f"[Last read-layer query: {_short_query(last)}. A follow-up (\"just this week\", \"by size\", \"only joggers\") is this query with that one thing changed.]")
    # A change the Mac knowingly cannot make: said plainly, with what it can do instead.
    # Without this the September session's "add two items to David Replica's order" was
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


def _order_places(text: str, known: set[str] | frozenset[str]) -> dict[int, str]:
    """Every place his words name an order number, by where it starts: said as an order ("#1940",
    "order 1940", "CROOKS-1940"), or a number that is an order this conversation holds. One place
    however many of the patterns find it there."""
    words = str(text or "")
    places: dict[int, str] = {}
    for found in _ORDER_SAID.finditer(words):
        places[found.start(1)] = found.group(1)
    for found in _NUMBER.finditer(words):
        if found.group(1) in known:
            places.setdefault(found.start(1), found.group(1))
    return places


def _order_mentions(text: str, known: set[str] | frozenset[str]) -> Counter:
    """How many times his words name each order number, counted by PLACE in the sentence."""
    return Counter(_order_places(text, known).values())


def _orders_named(text: str, known: set[str] | frozenset[str]) -> frozenset[str]:
    """The order numbers the owner's own words name — said as an order, or a number that is an
    order this conversation holds. Only his words: never the note a tapped control put beside
    them, which names the record the tap bound and not what he said next."""
    return frozenset(_order_mentions(text, known))


def _spoken_orders(numbers) -> str:
    return " and ".join(f"#{n}" for n in sorted(numbers))


def _numbers_said(text: str, session, proposed: list[str]) -> frozenset[str]:
    """Every number he said that could be an order's — said as one, or a bare number of three
    to seven digits that is not money — less the places inside what this turn's changes write.

    Wider than `_orders_named`, deliberately, and for a narrower purpose. That set decides
    where a change GOES, so it counts only what he plainly said as an order. This one decides
    only whether the screen he is looking at may stay under the answer (app/screen.py): "where
    is 1940" with #1938 up is about something that is not on the screen, whether or not this
    conversation has met #1940, and #1938's card must not stand under it. Staying off the
    screen when unsure costs a redraw; staying on it wrongly shows the owner one order's card
    under another's answer.

    Counted by place: "add a note to order 1940: 1940 goes with the gift box" says 1940 once more
    than the note carries it, so the sentence is about #1940 and a screen showing #1938 does not
    stay under it. Only whether a screen stays; where a change goes is `_off_target`'s, which
    lets the model's words excuse nothing."""
    words = str(text or "")
    places: dict[int, str] = {}
    for pattern in (_ORDER_SAID, _NUMBER):
        for found in pattern.finditer(words):
            places.setdefault(found.start(1), found.group(1))
    said = Counter(places.values())
    written: Counter = Counter()
    for proposal_id in proposed or []:
        proposal = session.proposal(proposal_id) if session is not None and not str(proposal_id).startswith("batch_") else None
        if proposal is not None:
            written.update(_written_counts(proposal))
            written.update(str(v) for v in (getattr(proposal, "model_args", None) or {}).values()
                           if isinstance(v, (int, float)) and not isinstance(v, bool))
    return frozenset(number for number, times in said.items() if times > written.get(number, 0))


#: A key whose value names a record rather than saying anything: an order's id, a gid.
_ID_KEY = re.compile(r"(?:^|_)(?:id|ids|ref|refs|gid)$", re.I)
_ANY_NUMBER = re.compile(r"(?<!\d)(\d{3,7})(?!\d)")


def _written_counts(proposal) -> Counter:
    """How many times each number stands in what a change WRITES — a note's words, a refund's
    reason, a tag, a message — as against the record it is written on. "Exchange for order 1912,
    she wants a medium" dictated as a note on #1938 carries 1912 once as its content; so does the
    tag "drop-007" carry 007.

    Read from the model's arguments, never from an id or a gid, and never from what will be sent:
    the sending copy can also hold what is already on the record — a note appended is sent with
    the old note above it — and the old note is not something he said."""
    counts: Counter = Counter()

    def walk(value: Any, key: str, depth: int) -> None:
        if depth > 5:
            return
        if isinstance(value, str):
            if not _ID_KEY.search(key) and not value.startswith("gid://"):
                counts.update(_ANY_NUMBER.findall(value))
        elif isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, str(k), depth + 1)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v, key, depth + 1)

    source = getattr(proposal, "model_args", None)
    if isinstance(source, Mapping):
        walk(source, "", 0)
    return counts


# ------------------------------------------------ the person he named, and a change to another one
#
# A change on a person — store credit — is his only when it is for the person he named, as a change
# to an order is his only when it is for the order he named. The names are the ones this
# conversation's reads returned; the words are his, after the model, never in front of it.

_NAME_WORD = re.compile(r"[^\W\d_]+(?:['-][^\W\d_]+)*")
_POSSESSIVE = re.compile(r"'s\b")


def _plain(text: str) -> str:
    """Words as they are compared for a name: one case, one kind of apostrophe, no possessive
    "'s" ("Mia's credit" names Mia), single spaces."""
    folded = str(text or "").replace("’", "'").replace("‘", "'").casefold()
    return " ".join(_POSSESSIVE.sub("", folded).split())


def _name_words(name: str) -> tuple[str, ...]:
    """A person's name as the words it is said in: letters, with an apostrophe or a hyphen inside a
    word kept (O'Brien, Mary-Jane). Nothing shorter than two letters."""
    return tuple(word for word in _NAME_WORD.findall(_plain(name)) if len(word) >= 2)


def _looks_like_a_name(text: str) -> bool:
    """Whether a personal string a read returned is a person's name rather than an address, a
    street, a postcode or a subject line: one to four words of letters and nothing else."""
    value = str(text or "")
    if "@" in value or any(ch.isdigit() for ch in value):
        return False
    words = _name_words(value)
    return 1 <= len(words) <= 4 and " ".join(words) == _plain(value).replace(".", "").strip()


def _says(words: str, text: str) -> bool:
    return re.search(rf"(?<![\w'-]){re.escape(words)}(?![\w'-])", text) is not None


def _people_held(session, calls) -> dict[str, str]:
    """Every customer this conversation holds by name, by id: those on its context stack, those
    this turn's reads returned, and those its changes were prepared for.

    `name` is a person's only in a customer's record: in an order's it is the order's own name
    ("CROOKS-1938"), which is why an order record is read by its `customer_name`."""
    held: dict[str, str] = {}
    for entry in getattr(session, "context", None) or []:
        if isinstance(entry, dict) and entry.get("kind") == "customer" and entry.get("ref") and entry.get("label"):
            held.setdefault(str(entry["ref"]), str(entry["label"]))

    def walk(value: Any, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(value, Mapping):
            ref = value.get("customer_id")
            orderish = "order_id" in value or "order_number" in value
            name = value.get("customer_name") or (None if orderish else value.get("name"))
            if isinstance(ref, str) and ref and isinstance(name, str) and name.strip():
                held.setdefault(ref, name.strip())
            for key, item in value.items():
                if not str(key).startswith("_"):
                    walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    for call in calls or []:
        if getattr(call, "ok", False) and isinstance(getattr(call, "result", None), dict):
            walk(call.result, 0)
    for proposal in getattr(session, "proposals", None) or []:
        if getattr(proposal, "entity_kind", "") == "customer":
            name = str((getattr(proposal, "summary", None) or {}).get("customer") or "").strip()
            if proposal.entity_ref and name:
                held.setdefault(str(proposal.entity_ref), name)
    return held


def _people_said(text: str, held: dict[str, str], others: Iterable[str] = ()) -> tuple[dict[str, str], set[str]]:
    """(the customers his words name, each with the words he named them by; those of them named
    only by a name that another person this conversation has been shown also has).

    A whole name is looked for first and settles it: "Mia Kowalski" is one person when there are
    two Mias. Then the single words of each name, in what is left of the sentence. `others` are
    the personal strings this conversation's reads returned (Session.pii_seen); the ones that are
    names count as people he could mean, so a Mia seen only in a list of search results still
    makes "Mia" two people. A name that is part of another — "Mia" beside "Mia Kowalski" — is the
    same person and counts once."""
    said = _plain(text)
    people = {ref: words for ref, name in held.items() if (words := _name_words(name))}
    everyone: list[frozenset[str]] = [frozenset(words) for words in people.values()]
    for other in others:
        words = frozenset(_name_words(other)) if _looks_like_a_name(other) else frozenset()
        if words and not any(words <= known or known <= words for known in everyone):
            everyone.append(words)

    named: dict[str, str] = {}
    shared: set[str] = set()
    rest = said
    for ref, words in people.items():
        whole = " ".join(words)
        if len(words) >= 2 and _says(whole, said):
            named[ref] = whole
            if sum(1 for person in everyone if person == frozenset(words)) > 1:
                shared.add(ref)
            rest = re.sub(rf"(?<![\w'-]){re.escape(whole)}(?![\w'-])", " ", rest)
    for ref, words in people.items():
        if ref in named:
            continue
        hits = [word for word in words if _says(word, rest)]
        if hits:
            named[ref] = hits[0]
            if any(sum(1 for person in everyone if word in person) > 1 for word in hits):
                shared.add(ref)
    return named, shared


def _as_he_said(words: str, text: str) -> str:
    """The words he named someone by, in his own capitals when they can be found in his sentence."""
    found = re.search(rf"(?<![\w'-]){re.escape(words)}", str(text or "").replace("’", "'"), re.I)
    return found.group(0) if found else words.title()


# ------------------------------------------------ a change held to what he named and what he tapped

#: The records a tapped control's words may change, by the kind of record it bound: a note or an
#: address on an order; a reply, a rewrite or an archive in an email thread; a change to a
#: customer. A change of one of these kinds made under that control goes on the bound record.
_BOUND_KINDS: dict[str, frozenset[str]] = {
    "order": frozenset({"order"}),
    "email_thread": frozenset({"email", "thread"}),
    "customer": frozenset({"customer"}),
}

#: Why a change was withdrawn: the reason it is revoked with, which the ledger keeps.
NOT_THE_ORDER_NAMED = "not the order the owner named"
NOT_THE_RECORD_TAPPED = "not the record the owner tapped"
NOT_THE_PERSON_NAMED = "not the person the owner named"
MORE_THAN_ONE_NAMED = "more than one person named"
A_NAME_TWO_SHARE = "a name two people share"


def _same_record(kind: str, one: Any, other: Any) -> bool:
    return bool(one) and bool(other) and _record_key(kind, str(one)) == _record_key(kind, str(other))


def _off_target(proposed: list[str], session, *, question: str, known: set[str] | frozenset[str],
                binding: Mapping[str, Any] | None = None, cursor: Mapping[str, Any] | None = None,
                calls: list | None = None) -> list[tuple[str, str, frozenset[str]]]:
    """The changes this turn staged somewhere the owner did not ask for them, as (proposal id,
    why, the orders he named for it). Run after the model, on what it staged; nothing here reads
    anything or answers a sentence.

    An order. When his words name an order, the change is on an order they name: "add a note to
    1940" after Add a note was tapped on #1938, or "yes, #1940" over a refund waiting on #1938,
    must not come back as a card for #1938, however the model read the words. Nothing the change
    itself writes excuses a number he said, and neither does a tap. Which of his numbers is where
    the change goes and which is what it says is a matter of how the sentence is built, which is
    the model's to read and is exactly what this checks; every attempt to excuse a number by the
    change's own words — counting them, then matching them word for word, then only after a tap
    — let a model that copied "order 1940" into a note on #1938 through (the round-12 deploy
    review, S2a-01, R9-I-tests2-I-01, R9-I-tests5-I-03, and round 13's three independent
    checks). So "add a note: exchange for order 1912", with #1938 on screen or Add a note tapped
    on it, is withdrawn and he is asked which order it is for; "on this one", or "1938", puts it
    there. Failing a named order, a tapped control's words go on the order it bound. A change
    whose order cannot be told from its card is not his when he named one.

    An email. After a tapped Reply or Rewrite, what is written is in the thread he tapped: his
    words cannot name a thread, and an order they name is not a way to another customer's inbox.

    A person. A change on a customer goes to a customer he named, when he named one this
    conversation holds; when the name he said is two people's, to neither, unless the control
    he tapped was on one of them. After a tapped control on a customer, with no one named, it
    goes to that customer.

    A bulk change is over a set, and is not judged here."""
    bound_kind = str((binding or {}).get("kind") or "")
    bound_ref = str((binding or {}).get("ref") or "")
    changes = [(p, session.proposal(p)) for p in proposed if not str(p).startswith("batch_")]
    changes = [(p, proposal) for p, proposal in changes if proposal is not None]
    if not changes:
        return []
    named_raw = _orders_named(question, known)
    people: dict[str, str] | None = None
    shared: set[str] = set()
    email_people: dict[str, str] | None = None
    email_named: dict[str, str] | None = None
    off: list[tuple[str, str, frozenset[str]]] = []
    for proposal_id, proposal in changes:
        kind = str(getattr(proposal, "entity_kind", "") or "")
        ref = str(getattr(proposal, "entity_ref", "") or "")
        bound_here = kind in _BOUND_KINDS.get(bound_kind, ()) and _same_record(bound_kind, ref, bound_ref)
        if kind == "order":
            number = _order_number(getattr(proposal, "entity_label", ""))
            if named_raw:
                # He named an order: the change is on one he named — after a tap too, when the
                # order he named is not the one he tapped: which one it is for is his to say.
                if not number or number not in named_raw:
                    off.append((proposal_id, NOT_THE_ORDER_NAMED, named_raw))
            elif bound_kind and bound_ref and not bound_here:
                # Named nothing, and tapped a control on another record — an order's, or an
                # email's Reply: the change is not what the tap was for.
                off.append((proposal_id, NOT_THE_RECORD_TAPPED, frozenset()))
        elif kind in _BOUND_KINDS["email_thread"]:
            number = _order_number(getattr(proposal, "entity_label", ""))
            if bound_kind == "email_thread" and bound_ref and not bound_here:
                # After a tapped Reply or Rewrite, what is written is in the thread he tapped. An
                # order his words name — which may be one he is telling this customer about —
                # does not send it to that order's customer instead (round 13's third check:
                # "David's order 1939 went to you by mistake", dictated to Priya, became an email
                # to David).
                off.append((proposal_id, NOT_THE_RECORD_TAPPED, frozenset()))
            elif ref.startswith("gid://shopify/Order/") and named_raw and (not number or number not in named_raw):
                # A new email is written to an order's customer: the order is held to the orders
                # he named, as any change on an order is (round 13's fourth check).
                off.append((proposal_id, NOT_THE_ORDER_NAMED, named_raw))
            elif str(getattr(proposal, "tool_name", "") or "") in _NEW_EMAIL_TOOLS:
                # And to a person he named, when he named one this conversation has been shown:
                # "email Priya: David's order 1939 went to you by mistake", written to #1939's
                # customer, names #1939 and goes to David (round 13's fourth check). Anyone its
                # reads have shown counts, not only the customers it holds by id: a recipient is
                # a name on an order, and so is the person he means.
                if email_people is None:
                    email_named = _names_seen(session, calls)
                    email_people, _shared = _people_said(question, email_named, getattr(session, "pii_seen", None) or ())
                if email_people and not _to_one_named(proposal, email_people, email_named or {}):
                    off.append((proposal_id, NOT_THE_PERSON_NAMED, frozenset()))
                elif len({_name_words((email_named or {}).get(r, "")) for r in email_people}) > 1:
                    # He named two people, and it goes to one: which one it is to, and which one
                    # it is about, is how the sentence is built — his to say, not a rule's.
                    off.append((proposal_id, MORE_THAN_ONE_NAMED, frozenset()))
        elif kind == "customer":
            if people is None:
                people, shared = _people_said(question, _people_held(session, calls),
                                              getattr(session, "pii_seen", None) or ())
            named_here = [r for r in people if _same_record("customer", ref, r)]
            if people:
                if not named_here:
                    off.append((proposal_id, NOT_THE_PERSON_NAMED, frozenset()))
                elif any(r in shared for r in named_here) and not bound_here:
                    off.append((proposal_id, A_NAME_TWO_SHARE, frozenset()))
            elif bound_kind == "customer" and bound_ref and not bound_here:
                off.append((proposal_id, NOT_THE_RECORD_TAPPED, frozenset()))
    return off


_NEW_EMAIL_TOOLS = frozenset({"gmail_draft_new", "gmail_send_new"})


def _names_seen(session, calls) -> dict[str, str]:
    """Every customer this conversation knows by name: those it holds by id (`_people_held`), and
    the customer of every order it was issued, as the entity cache holds that order — so a
    customer read two turns ago, on an order, is a person he can name now."""
    named = dict(_people_held(session, calls))
    try:
        from app.memory import ENTITY
        from app.memory import current as memory

        for ref in sorted(str(i) for i in (getattr(session, "issued_ids", None) or ()) if str(i).startswith("gid://shopify/Order/")):
            entry = memory().get(ENTITY, f"order:{ref}", allow_stale=True)
            value = getattr(entry, "value", None) if entry is not None else None
            if not isinstance(value, Mapping):
                continue
            customer = value.get("customer") if isinstance(value.get("customer"), Mapping) else {}
            who = str(customer.get("customer_id") or value.get("customer_id") or f"order-customer:{ref}")
            name = str(value.get("customer_name") or customer.get("name") or "").strip()
            if name:
                named.setdefault(who, name)
    except Exception:  # noqa: BLE001 — no memory bound (a unit test, a cold start) is fewer names
        pass
    return named


def _to_one_named(proposal, people: Mapping[str, Any], held: Mapping[str, str]) -> bool:
    """Whether a new email goes to one of the people he named: the customer it was written to by
    id, or the recipient whose name on the order is that person's whole name."""
    ref = str(getattr(proposal, "entity_ref", "") or "")
    if any(_same_record("customer", ref, r) for r in people):
        return True
    execution = getattr(proposal, "execution", None) if isinstance(getattr(proposal, "execution", None), Mapping) else {}
    to = _name_words(str(execution.get("to_name") or ""))
    return bool(to) and any(_name_words(held.get(r, "")) == to for r in people)


def _off_target_words(session, off: list[tuple[str, str, frozenset[str]]], *, question: str = "",
                      binding: Mapping[str, Any] | None = None, calls: list | None = None) -> str:
    """What the owner is told instead of the model's sentence about a change that was withdrawn,
    in one sentence, for the first reason it was withdrawn: the order he said, the control he
    tapped, the person he named, or a name two people share."""
    why = off[0][1]
    mine = [(session.proposal(p), where) for p, reason, where in off if reason == why]
    if why == NOT_THE_ORDER_NAMED:
        targets = {_order_number(getattr(proposal, "entity_label", "")) for proposal, _where in mine}
        targets.discard("")
        named = frozenset().union(*(where for _proposal, where in mine))
        were = _spoken_orders(targets) if targets else "another order"
        bound_kind, bound_ref = str((binding or {}).get("kind") or ""), str((binding or {}).get("ref") or "")
        if bound_kind == "order" and bound_ref and any(
                _same_record("order", getattr(proposal, "entity_ref", ""), bound_ref) for proposal, _where in mine):
            # On the order he tapped, and his words named another: he is asked, not corrected.
            tapped = str((binding or {}).get("prompt") or "that control").strip()
            return (f"You'd tapped {tapped} on {were} and said {_spoken_orders(named)}, so I haven't put it "
                    f"on {were}. Say which order it's for.")
        return (f"You said {_spoken_orders(named)}, but the change I'd prepared was for {were}, so I've "
                "withdrawn it. Say which order you want it on.")
    if why == NOT_THE_RECORD_TAPPED:
        tapped = str((binding or {}).get("prompt") or "that control").strip()
        kind = str((binding or {}).get("kind") or "")
        label = str((binding or {}).get("label") or "").strip()
        if kind == "order" or all(getattr(proposal, "entity_kind", "") == "order" for proposal, _where in mine):
            targets = {_order_number(getattr(proposal, "entity_label", "")) for proposal, _where in mine}
            targets.discard("")
            were = _spoken_orders(targets) if targets else "another order"
            on = f" on {label}" if label else ""
            return (f"You'd tapped {tapped}{on}, but the change I'd prepared was for {were}, so I've withdrawn it. "
                    "Say which order you want it on.")
        if kind == "customer":
            on = f" on {label}" if label else ""
            return (f"You'd tapped {tapped}{on}, but the change I'd prepared was for someone else, so I've "
                    "withdrawn it. Say who it's for.")
        return (f"You'd tapped {tapped}, but what I'd prepared was for a different email, so I've withdrawn it. "
                "Say who it's for.")
    if why == MORE_THAN_ONE_NAMED:
        to = sorted({str((getattr(proposal, "summary", None) or {}).get("spoken_to") or "") for proposal, _where in mine} - {""})
        named = _names_seen(session, calls)
        said_people, _shared = _people_said(question, named, getattr(session, "pii_seen", None) or ())
        said = " and ".join(dict.fromkeys(_as_he_said(words, question) for words in said_people.values()))
        return (f"You named {said or 'more than one person'}, and the email I'd prepared was to "
                f"{' and '.join(to) or 'one of them'}, so I haven't put it on a card. Say who it's to.")
    held = _people_held(session, calls)
    people, shared = _people_said(question, held, getattr(session, "pii_seen", None) or ())
    if why == A_NAME_TWO_SHARE:
        said = " and ".join(dict.fromkeys(_as_he_said(people[r], question) for r in people if r in shared))
        return (f"{said or 'That name'} could be more than one of your customers, so I've withdrawn the change "
                "rather than guess. Say which one you mean.")
    said = " and ".join(dict.fromkeys(_as_he_said(words, question) for words in people.values()))
    for_whom = sorted({str((getattr(proposal, "summary", None) or {}).get("customer") or held.get(str(proposal.entity_ref), "")
                           or (getattr(proposal, "summary", None) or {}).get("spoken_to") or "")
                       for proposal, _where in mine} - {""})
    were = " and ".join(for_whom) if for_whom else "someone else"
    return f"You said {said}, but the change I'd prepared was for {were}, so I've withdrawn it. Say who it's for."


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
    the cursor (app/screen.py `listening_on_cursor`), and every other change names its own record (a
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


# ------------------------------------------------ a list he asked for, walked as the Orders icon's is
#
# The checker's defect 1 (night of 7-8 Oct): since every sentence became the model's (28 Sep), a
# list drawn for a sentence opened no walk — Next answered "There is no list open to move through"
# — while the same list opened from the Orders icon could be walked. The answer's own list now
# opens the walk the landing opens (app/families/landings.py `_open_workflow`), decided from the
# cards the answer drew and never from the words (MAP rule 7).

#: [flow] The cards that are a list of orders a walk can go through.
_ORDER_LISTS = frozenset({"order_list", "summary_list"})


def _walk_what_was_listed(runtime, session, branch, ui: list) -> None:
    """When the answer's own screen holds one list of orders and no single record, Next and
    Previous walk that list, as they walk the Orders icon's.

    The set it walks is the one the read made when it made one (a summary's `set_id`), or one
    made here from the rows the card drew — their ids were issued to this conversation by the
    read that returned them, so the walk can open each. A list beside a record, two lists, or a
    list of something other than orders opens nothing new. Never raises: a walk is a
    convenience, never the answer."""
    own = [item for item in ui or [] if isinstance(item, dict) and not item.get("kept")]
    lists = [item for item in own if item.get("type") in _ORDER_LISTS and isinstance(item.get("data"), dict)
             and not item["data"].get("empty")]
    if len(lists) != 1 or _records_shown(own) or session is None or branch is None:
        return
    try:
        set_id = _set_of_the_list(session, lists[0])
        if not set_id:
            return
        from app.commands import Ctx
        from app.families.landings import _open_workflow

        _open_workflow(Ctx(runtime, session, branch), {}, kind="orders", operation="review", set_id=set_id)
    except Exception as exc:  # noqa: BLE001 — a cursor is a convenience, never the answer
        log.debug("could not open a walk on the answer's list: %s: %s", type(exc).__name__, exc)


def _set_of_the_list(session, item: dict) -> str:
    """The working set of orders a list card shows: its own, or one made from its rows."""
    from app.analytics import sets as working_sets
    from app.summaries import order_words

    data = item["data"]
    if data.get("set_id"):
        held = working_sets.get(session, str(data["set_id"]))
        return held.set_id if held is not None and held.kind == "orders" else ""
    rows = [o for o in data.get("orders") or [] if isinstance(o, dict) and o.get("order_id")]
    if item.get("type") != "order_list" or not rows:
        return ""
    made = working_sets.create(
        session, kind="orders", members=[str(o["order_id"]) for o in rows], label=str(data.get("title") or "Orders"),
        provenance={"tool": "answer", "step": "shown"},
        labels={str(o["order_id"]): order_words(o.get("order_number")) for o in rows if order_words(o.get("order_number"))},
    )
    return made.set_id


# ------------------------------------------------ "it's on your screen" held to the screen
#
# George, 29 September: "it can say stuff like confirmed order xyz on screen but there is
# nothing." What the model SAID is held against what this turn DREW, after the model, as
# `_off_target` holds a staged change against the order he named. The words that make a claim
# are the model's (app/observability/claims.py `ON_SCREEN_RE`), never the owner's sentence.


async def _hold_to_the_screen(answer: str, ui: list, *, session, branch, calls, said: frozenset[str],
                              rail: dict | None) -> tuple[str, list, dict | None]:
    """(answer, ui, what was done) for an answer that says something is on his screen.

    What the claim is about is read from the sentences that MAKE it, never from the rest of the
    answer: "Order #1938 is on your screen. #1940 shipped yesterday." is a claim about #1938,
    and with #1938 up it is true and nothing changes (the round-12 independent check, C1: it
    used to take #1940 from the second sentence and swap the cards, or, for an order never
    shown, cut the true claim).

    True already when the screen shows something — this turn's cards or the ones kept up —
    and every order the claim names as an order is on it. Otherwise the Mac makes it true
    when it can tell, unambiguously, which one record the answer is about: the one order it
    names that the screen does not show; else the one order the owner named that it does not
    show; else, when he named none, the record this half is on. That record is drawn from what
    the conversation already holds, through the gate's own issued-id rule. When none of that
    settles it — two orders named, one the conversation was never shown, nothing to stand on —
    the claim is taken out of the answer and he is told plainly how to get it shown.

    A turn that used one of his named TV screens is not judged: "it's on the screen" there is
    about that screen, which `screen_show` keeps honest itself.
    """
    from app.observability import claims

    claiming = claims.claiming_sentences(answer) if session is not None and branch is not None else []
    if not claiming:
        return answer, ui, None
    if any(str(getattr(c, "name", "") or "").startswith("screen_") for c in calls or []):
        return answer, ui, None
    showing = [item for item in ui if item.get("type") not in screen.BOOKKEEPING and item.get("type") != "error"]
    named_in_claim = frozenset(n for sentence in claiming for n in _ORDER_SAID.findall(sentence))
    on_it = screen.numbers_on(showing)
    missing = named_in_claim - on_it
    if showing and not missing:
        return answer, ui, None
    if any(item.get("type") in focus.TASK for item in showing):
        # [flow, DEC-069] A change waiting for him IS the screen (app/focus.py rule 1). A claim
        # naming a record beside it is taken out, never answered by drawing that record in the
        # change card's place: the card he has to hold is not swapped for one he did not ask for.
        kept = claims.without_the_claim(answer).removesuffix(claims.NOT_ON_SCREEN).strip()
        return (kept or READY_ON_SCREEN), ui, claims.screen_claim(corrected=True, named=sorted(missing | (said - on_it)))
    # What this turn drew of its own — a record it read, not one kept up from the screen before.
    # A claim about another record never replaces it: "show me order 1940", #1940 read, and "Order
    # #1938 is on your screen" drew #1938 in #1940's place and put the cursor on it (the round-12
    # deploy review, S2T-01). The screen is what the turn read; the sentence that says otherwise
    # is taken out, and when nothing else was said, what IS on the screen is said instead.
    own = [item for item in showing if screen.is_subject(item) and not item.get("kept")]
    if own:
        kept = claims.without_the_claim(answer).removesuffix(claims.NOT_ON_SCREEN).strip()
        return (kept or _what_is_up(own)), ui, claims.screen_claim(corrected=True, named=sorted(missing | (said - on_it)))
    target = None
    if len(missing) == 1:
        target = _order_held(session, branch, next(iter(missing)))
    elif not missing and len(said - on_it) == 1:
        target = _order_held(session, branch, next(iter(said - on_it)))
    elif not missing and not (said - on_it) and not showing:
        entity = getattr(branch, "entity", None) or {}
        if entity.get("kind") in _ID_OF_KIND and entity.get("ref"):
            target = (str(entity["kind"]), str(entity["ref"]), str(entity.get("label") or ""))
    drawn = await _draw_held(session, target, rail) if target is not None else []
    if drawn:
        bookkeeping = [item for item in ui if item.get("type") in screen.BOOKKEEPING]
        return answer, drawn + bookkeeping, claims.screen_claim(drew=target[2] or target[0], named=sorted(missing))
    return claims.without_the_claim(answer), ui, claims.screen_claim(corrected=True, named=sorted(missing | (said - on_it)))


#: [flow, DEC-069] What an answer that was only a claim says instead, when the screen is the
#: change waiting for him: true, because the change card is on it.
READY_ON_SCREEN = "It's ready on your screen."


def _what_is_up(own: list) -> str:
    """One true sentence about what this turn put on the screen, for an answer whose only
    sentence was a claim about something else: the order or the customer, when it drew one."""
    records = _records_shown(own)
    if len(records) == 1:
        ((kind, _ref, label),) = records.values()
        if kind == "order" and _order_number(label):
            return f"#{_order_number(label)} is on your screen."
        if kind == "customer" and label.strip():
            return f"{label.strip()} is on your screen."
    return "What I read is on your screen."


def _order_held(session, branch, number: str) -> tuple[str, str, str] | None:
    """(kind, ref, label) of the order this conversation holds by this number — from what the
    half drew, the context stack, or a change it staged — or None."""
    for entry in getattr(branch, "shown_before", None) or []:
        card = entry.get("card") if isinstance(entry, dict) else None
        record = screen.record_of(card) if isinstance(card, dict) else None
        if record is not None and record[0] == "order" and number in screen.numbers_on([card]):
            data = card.get("data") or {}
            return "order", str(data.get("order_id") or data.get("ref") or ""), f"#{number}"
    for entry in getattr(session, "context", None) or []:
        if isinstance(entry, dict) and entry.get("kind") == "order" and _order_number(entry.get("label")) == number and entry.get("ref"):
            return "order", str(entry["ref"]), f"#{number}"
    for proposal in reversed(getattr(session, "proposals", None) or []):
        if getattr(proposal, "entity_kind", "") == "order" and _order_number(getattr(proposal, "entity_label", "")) == number:
            return "order", str(proposal.entity_ref), f"#{number}"
    return None


async def _draw_held(session, target: tuple[str, str, str], rail: dict | None) -> list:
    """The record's cards, from the copy the Mac holds or, failing that, one gated read — and
    nothing when the conversation was never shown it. The rail is this caller's, as it was."""
    from app.commands import REPLAY_TOOL, Ctx, may_open
    from app.memory import ENTITY
    from app.memory import current as memory

    kind, ref, _label = target
    tool_name = REPLAY_TOOL.get(kind, "")
    if not tool_name or not ref or not may_open(Ctx(runtime=None, session=session, branch=None), kind, ref):
        return []
    held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    body = held.value if held is not None and isinstance(getattr(held, "value", None), dict) else None
    if body is None:
        from app.reads.scheduler import Read, ReadPlan, run_plan

        try:
            result = await run_plan(ReadPlan([Read("claimed", tool_name, {_ID_OF_KIND[kind]: ref},
                                                   source="gmail" if kind == "email_thread" else "shopify")],
                                             label="on_screen_claim"),
                                    session=session, timeout_s=6.0, turn_id=getattr(session, "turn_id", ""))
            body = result.values.get("claimed")
        except Exception as exc:  # noqa: BLE001 — a record that cannot be read is a claim corrected
            log.info("the claimed record could not be read: %s", type(exc).__name__)
            body = None
    if not isinstance(body, dict):
        return []
    drawn = compact(present([ToolCall(name=tool_name, args={}, ok=True, result=body)], session=session, writes=rail))
    return [item for item in drawn if item.get("type") != "context_stack"]


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
    provider = _provider(runtime)
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


def _provider(runtime):
    """The assistant this request talks to: a team member's own when the door made it a staff
    request (app/people), the owner's otherwise. A runtime without the choice (a test double) has
    only the one."""
    from app.tools import authority as tool_authority

    choose = getattr(runtime, "provider_for", None)
    return choose(tool_authority.current()) if callable(choose) else runtime.provider


async def _provider_turn(runtime, session_id: str, prompt_text: str, branch):
    """The model turn, on this half's own conversation when the provider keeps one per half.
    A provider without the method — a test double — gets the plain turn."""
    provider = _provider(runtime)
    # Counted as running in its assistant from here, before anything awaits, so an assistant
    # retired meanwhile (a card changed) is not stopped under it by somebody else's turn.
    running = getattr(runtime, "running", None)
    async with running(provider) if callable(running) else contextlib.nullcontext():
        ensure = getattr(runtime, "ensure_started", None)
        if callable(ensure):
            await ensure(provider)
        on_branch = getattr(provider, "turn_on_branch", None)
        branch_id = str(getattr(branch, "branch_id", "") or "")
        if on_branch is not None and branch_id:
            return await on_branch(session_id, prompt_text, branch_id=branch_id)
        return await provider.turn(session_id, prompt_text)


def _staff_request() -> bool:
    """Whether the door made this a team member's request (app/tools/authority.py STAFF)."""
    from app.tools import authority as tool_authority

    held = tool_authority.current()
    return held is not None and held.kind == tool_authority.STAFF


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
    # [recording] Never to a team member's page: the door refuses its telemetry, so turning it on
    # there would only fill the log with refusals (the interaction record is always on).
    if _staff_request():
        return None
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
    binding: Mapping[str, Any] | None = None,
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
    # Where this half stood when the answer began, for an answer that never counted itself in on
    # the half (a spoken yes, an early refusal): a newer instruction to the half, or a cancel aimed
    # at it, moves such an answer on as surely as it moves on a model turn, which has its `seq`.
    entry = ((int(getattr(branch, "instruction_seq", 0) or 0), bool(getattr(branch, "abandoned", False)))
             if branch is not None else None)

    def moved_on_since() -> bool:
        """Whether this answer is no longer the half's current one, asked again after an await.

        A newer sentence to the same half, or a cancel aimed at it, can land in any await this
        answer makes — the claim repair can wait up to six seconds on the shop — and an answer
        that publishes after that puts its cursor and its screen over the newer one's (the
        round-12 deploy review, R9-D2-D2-01). A sentence to the OTHER half is not a newer
        question to this one."""
        if session is None:
            return False
        if seq is not None:
            return _moved_on(session, branch, epoch=epoch, seq=seq)
        if bool(getattr(session, "abandoned", False)):
            return True
        if entry is None:
            return False
        return (int(getattr(branch, "instruction_seq", 0) or 0) != entry[0]
                or (bool(getattr(branch, "abandoned", False)) and not entry[1]))

    def withdraw(ids: list[str]) -> None:
        """Changes staged into a conversation that has moved past this answer. Nobody asked for
        them there: withdrawn, unsent."""
        if ids:
            runtime.actions.revoke_ids(ids, "the owner moved on")
            runtime.batches.revoke_ids(ids, "the owner moved on")

    # Abandoned: the owner cancelled, or asked something else while this was being answered.
    # The session's position has moved past this turn's; nobody is waiting for its voice.
    abandoned = bool(session is not None and _moved_on(session, branch, epoch=epoch, seq=seq))
    proposed = [c.proposal_id for c in (calls or []) if getattr(c, "proposal_id", None)]
    if abandoned and proposed:
        # Claude was still running when the owner moved on, and staged a change into the
        # conversation's new position.
        withdraw(proposed)
        proposed = []
    # What the owner named and what he tapped, held against what the model did with them — on a
    # model turn (`seq`), which is the only place a change is staged from words. A change to
    # another order, another record than the one his tapped control bound, or another person than
    # the one he named is withdrawn before it is delivered and drawn nowhere; a read of another
    # order and none he named is said to be that, in one sentence, and does not move the cursor
    # (see `_off_target`, `_stand_on_what_was_shown`).
    named: frozenset[str] = frozenset()
    withheld: set[str] = set()
    withdrawn_words = ""
    if seq is not None and session is not None and not abandoned:
        known = _orders_known(session, branch, calls)
        named = _orders_named(question, known)
        off = _off_target(proposed, session, question=question, known=known, binding=binding,
                          cursor=getattr(branch, "entity", None), calls=calls)
        if off:
            log.warning("withdrew %d change(s) staged somewhere the owner did not ask for them", len(off))
            answer = (LOST_THREAD_PREFIX if lost_thread and answer.startswith(LOST_THREAD_PREFIX) else "") + _off_target_words(
                session, off, question=question, binding=binding, calls=calls)
            for reason in dict.fromkeys(why for _p, why, _where in off):
                runtime.actions.revoke_ids([p for p, why, _where in off if why == reason], reason)
            withdrawn_words = answer
            withheld = {p for p, _why, _where in off}
            proposed = [p for p in proposed if p not in withheld]
        elif named:
            read = _orders_read(calls)
            if read and not (read & named):
                answer = f"{answer.rstrip()} That's {_spoken_orders(read)}, not {_spoken_orders(named)}."
    # A change was proposed this turn. Say, now and in the same breath, whether a tap on THIS
    # tablet could apply it — a card that cannot be applied must never look as if it can.
    if proposed and writes is None and request is not None:
        writes = await writes_context(request)
        if not abandoned and moved_on_since():
            # Moved on while the scope was asked: nothing of this answer is delivered.
            abandoned = True
            withdraw(proposed)
            proposed = []
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
    # What the Mac did about an answer that said something was on the screen when this turn
    # had put nothing there (`_hold_to_the_screen`); written beside the decline claims below.
    on_screen_claim: dict[str, Any] | None = None
    ui: list[dict[str, Any]] = []
    scene = None
    # [recording] Which rule of app/screen.py decided the screen, for the interaction record.
    carry_why: list[str] = []
    # [flow, DEC-069] Which rule chose the answer's cards out of everything the turn read
    # (app/focus.py), for the interaction record.
    focus_why: dict[str, Any] = {}
    # The records the model read, kept where a tap finds them, BEFORE the cards are drawn: a
    # card offers a write only over a record the Mac is already holding (app/workspace.py
    # `_still_held`), so drawn first, the first answer about a customer had no "Email <name>",
    # and asking a second time did. Kept whether or not this answer is still wanted: reads are
    # facts, and Back onto that order later need not ask the shop again.
    _keep_what_was_read(calls)
    if not abandoned:
        # What the screen shows beside the answer: cards chosen from the tool results, never
        # from the prose. See app/presentation.py for the vocabulary and the bounds. Only what
        # the answer is about (DEC-069): a change wins, a record read in full wins over the
        # searches that found it, and an error is never set aside.
        ui = present([c for c in (calls or []) if getattr(c, "proposal_id", None) not in withheld] if withheld else calls,
                     session=session, error_kind=error_kind, writes=rail, focus=True, focus_why=focus_why)
        # The same turn as a validated scene, when CLIVE_SCENES is on: planned from these
        # reads, carried as its own field and changing nothing else. Off, nothing here runs.
        scene = _turn_scene(question or str((transcript or {}).get("text") or ""), answer, calls, session_id)
        # One cursor, one headline per kind, the rest folded (brief section 22).
        ui = compact(ui)
        # The screen this half is showing stays up unless this answer brings a new subject:
        # an answer whose only card is the change — the note waiting for his tap, a refusal —
        # or that answers in words is drawn beside the record he was working on, never
        # instead of it (app/screen.py, round 12).
        said_numbers = _numbers_said(question, session, proposed) if seq is not None else frozenset()
        if branch is not None:
            ui = screen.carry(ui, branch=branch, session=session, calls=calls, named=said_numbers, why=carry_why)
        # Never "it's on your screen" when nothing is: an answer that says so over a screen
        # this turn left empty is made true — the one record it is about is drawn — or, when
        # that cannot be told, corrected before a word of it is spoken (round 12).
        if seq is not None and not error_kind:
            answer, ui, on_screen_claim = await _hold_to_the_screen(
                answer, ui, session=session, branch=branch, calls=calls, said=said_numbers, rail=rail)
            if moved_on_since():
                # A newer sentence to this half, or a cancel aimed at it, landed while the claim
                # was being held to the screen. From here this answer is the abandoned one: no
                # cursor, no screen, nothing of it staged for the glass, and its changes withdrawn.
                abandoned = True
                withdraw(proposed)
                proposed, writes = [], None
                cancelled = bool(getattr(session, "abandoned", False) or getattr(branch, "abandoned", False))
                replaced = not cancelled
                ui, scene, on_screen_claim = [], None, None
    if withdrawn_words and not abandoned and session is not None:
        # What he was told about a withdrawn change, for this half's model at its next question —
        # only when he was told it: an abandoned answer told him nothing.
        if not isinstance(getattr(session, "last_withdrawn", None), dict):
            session.last_withdrawn = {}
        session.last_withdrawn[str(getattr(branch, "branch_id", "") or "")] = withdrawn_words
    if abandoned:
        # Nobody is waiting for this answer, and the half has moved on to another question
        # (the 2026-09-28 deploy review, round 9, D2-01). It publishes nothing: no cards, so the
        # context stack and the entity graph are not handed an old record as though it were
        # new; no `shown`, so tapping the half does not redraw it; no cursor, so "cancel it"
        # and a tapped Add a note act on what the newer answer showed and not on the order
        # this one read; and no reconciliation, because the live workspace on this half is
        # the newer turn's. What it read is still kept where a replay finds it (above, before
        # any card was drawn) — reads are facts, and Back onto that order later need not ask the
        # shop again.
        # The newer turn's answer says what happens to the screen; this one leaves it alone.
        screen_state = screen.SCREEN_KEPT
        timings["workspace"] = (time.perf_counter() - started) * 1000
        if branch is not None and not replaced:
            if seq is not None:
                branch.end_turn()
            branch.idle()
        glass: dict[str, Any] = {}
    else:
        if speak and answer:
            # Start the voice now: by the time the tablet has this JSON and asks /speak, the MP3
            # is already generating. The same request it would make anyway, just earlier. An
            # error line is a fixed sentence: synthesised once, kept, free and instant after that.
            # A question the owner abandoned (/cancel) gets no voice: nobody will ask for it —
            # which is why this is here, on the path of an answer somebody is waiting for, and
            # after the check above, so that what is prefetched is what will be said.
            runtime.voice.prefetch(
                to_speakable(answer, max_chars=runtime.voice.max_chars), pin=bool(error_kind) or answer in FIXED_LINES
            )
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
                # [flow] A list he asked for is walked with Next and Previous, as the Orders
                # icon's list is (the checker's defect 1).
                _walk_what_was_listed(runtime, session, branch, ui)
            # A control on a card that listens for words binds the half's cursor, not the card
            # it sits on (web/app.js `primeAction` posts the branch's entity). So only the card
            # that IS the cursor keeps one; every other card's chip primes its words and binds
            # nothing, and those words name its own record (D2-04, D1-02).
            ui = screen.listening_on_cursor(ui, getattr(branch, "entity", None))
        # Whether the half's screen stands, is replaced or goes — said to the tablet on every
        # answer, so the glass obeys rather than guesses, and held the same way on the Mac
        # (round 12, the second pass: words about #1940 must not leave #1938 standing on one
        # side of the two and not the other).
        screen_state = screen.state_of(ui)
        if branch is not None:
            # What this half now shows, kept on the Mac so tapping it later draws it (branch.show).
            if screen_state == screen.SCREEN_CLEARED:
                branch.cleared(answer, question)
            else:
                branch.shown(ui, answer, question)
        for call in calls or []:
            if branch is not None and getattr(call, "ok", False):
                branch.remember_result(call.name, summary=_call_summary(call), ref=_call_ref(call), ms=float(getattr(call, "duration_ms", 0.0) or 0.0))
        # The turn's own cards, reconciled against what the progressive workspace already put
        # on the glass (§7, §25). A card that is unchanged is NOT redrawn — the whole point —
        # and one that gained its rail or an enrichment is patched in place. The numbers come
        # back for the performance record; the patches themselves the tablet has already
        # collected from /state.
        # A card carried from the screen already up is not this turn's to stage: it is on the
        # glass, and restaging it would draw it again (app/screen.py).
        glass = progressive.complete(session, [item for item in ui if not item.get("kept")],
                                     branch_id=getattr(branch, "branch_id", "") or "")
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
        if on_screen_claim is not None:
            timeline.emit("unsupported_claim", session_id=session_id, turn_id=turn_id or None, **on_screen_claim)
        timeline.emit(
            "turn_performance", session_id=session_id, turn_id=turn_id or None, **performance,
        )
        # What THIS turn drew. A card kept up from the screen before it (app/screen.py) is on the
        # glass but was not drawn by this answer, and the report reads these fields as what the
        # turn produced; how many were kept is its own field.
        drew = [item for item in ui if not item.get("kept")]
        timeline.emit(
            "turn_finished", session_id=session_id, turn_id=turn_id or None, ms=round(timings["total"], 1),
            timings={k: round(v, 1) for k, v in timings.items()}, question=_written(question or (transcript or {}).get("text") or "", names) or None,
            # Redacted by the same rule the turn log uses, and for the same reason: the
            # answer may carry a street address the owner asked to be read out. He may hear
            # it; the timeline and the report built from it get "[address]".
            answer=_written(answer, names), error_kind=error_kind, lost_thread=lost_thread, abandoned=abandoned,
            ui=[item["type"] for item in drew], ui_entities=_ui_entities(drew), proposed=proposed or None, revoked=list(revoked or []) or None,
            # What the owner was actually shown, as a fact separate from which components drew
            # it: the surfaces this turn produced, whether anything was shown at all, and what
            # it offered to do next. A turn that answered in words and drew nothing is the
            # failure this pass exists for, and `surfaces: []` is what it looks like here.
            surfaces=[item.get("surface") or item["type"] for item in drew if item["type"] != "context_stack"] or None,
            showed_nothing=not any(item["type"] != "context_stack" for item in drew),
            # The screen already up, kept under this answer rather than drawn by it: a turn that
            # drew nothing new and left the record he was working on in front of him is not the
            # same as one that left him nothing.
            kept=(len(ui) - len(drew)) or None,
            actions=sorted({
                str(a.get("operation") or a.get("id") or "")
                for item in drew if isinstance(item.get("data"), dict)
                for a in (item["data"].get("actions") or []) if isinstance(a, dict)
            }) or None,
            writes_code=(None if writes is None or writes.get("allowed") else writes.get("code")),
            speak_requested=speak, tts_prefetched=bool(speak and answer and not abandoned),
            tool_calls=[{"tool": c.get("name"), "ok": c.get("ok"), "ms": c.get("ms"), "tool_call_id": c.get("tool_call_id") or None, "proposal_id": c.get("proposal_id")} for c in tool_calls] or None,
        )
    # [recording] What this turn asked, heard, drew and why, for "look at our interaction"
    # (app/observability/interactions.py). Off, one check; it never fails a turn.
    interactions.after_turn(
        session_id=session_id, turn_id=turn_id, question=question, transcript=transcript, answer=answer, ui=ui,
        calls=calls, screen_state=screen_state, carry=carry_why, error_kind=error_kind, abandoned=abandoned,
        timings=timings, branch=branch, claim=on_screen_claim, withheld=len(withheld), binding=binding, scene=scene,
        session=session, focus=focus_why or None,
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
        # What this answer does to the half's screen: "kept", "new" or "cleared" (app/screen.py
        # `state_of`). The tablet obeys it (web/app.js `renderTurn`).
        "screen": screen_state,
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

    interrupt = _provider(runtime).interrupt
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
        await _provider(runtime).reset_session(session_id)
    return {"reset": True}
