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
    transcript_info: dict | None = None
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
    live.heard = ""
    live.abandoned = False
    # This turn's place in the conversation. A hold that abandons the question, or a later
    # question, moves the session past it; the answer then goes unspoken.
    epoch = live.epoch
    # The turn's id: every tool call, proposal and tablet event it causes is written against
    # it on the test-session timeline (a no-op while no session is on).
    live.turn_id = timeline.new_id("turn")
    if timeline.current().active is not None:
        timeline.emit(
            "turn_started", session_id=session_id, turn_id=live.turn_id, input="audio" if audio is not None else "text",
            turns_before=live.turns, epoch=epoch, lost_thread=lost_thread, focus=(live.context[0] if live.context else None),
            # What was WAITING when this turn began: changes the owner has not decided about.
            # An undo offer is not one of those and is recorded separately — the report read
            # `waiting` and called two undo offers two outstanding changes.
            waiting=[p for p in action_engine.waiting_ids(live) if not live.proposal(p).batch_id] + [b.batch_id for b in live.batches.values() if b.status.value == "PENDING"],
            undoable=action_engine.undoable_ids(live) or None,
        )

    if audio is not None:
        blob = await audio.read()
        if len(blob) > MAX_UPLOAD_BYTES:
            return await _answer(
                runtime, session_id, "That recording was too long for me to handle.",
                request=request, error_kind="audio_too_large", timings=timings, started=started, speak=speak, epoch=epoch,
            )
        # The Mac says what it is doing while it does it: the tablet reads this rather than
        # guessing from a timer how long the recogniser takes.
        live.set_state("TRANSCRIBING")
        result = await runtime.transcriber.from_blob(blob, filename_hint=audio.filename or "")
        transcript_info = result.as_dict()
        timings.update(result.timings_ms)
        if timeline.current().active is not None:
            stats = transcript_info.get("stats") or {}
            timeline.emit(
                "stt", session_id=session_id, turn_id=live.turn_id, ok=result.ok, engine=result.engine or None, fallback=result.fallback,
                engine_detail=result.engine_detail or None, reason=result.reason or None, raw_text=result.raw_text or None, text=result.text or None,
                audio_s=stats.get("duration_s"), audio_bytes=len(blob), timings=transcript_info.get("timings_ms"),
                matches=transcript_info.get("matches"), order_numbers=transcript_info.get("order_numbers"),
            )
        if not result.ok:
            live.set_state("READY")
            return await _answer(
                runtime, session_id, result.reason, request=request, error_kind="speech",
                timings=timings, started=started, transcript=transcript_info, speak=speak, epoch=epoch,
            )
        text = result.text
        # The normaliser refused to guess between near-identical names; tell the model, so it
        # can search the partial name and ask — rather than silently losing the information.
        if result.normalised and result.normalised.ambiguities:
            notes = "; ".join(
                f"'{a.heard}' could be {' or '.join(a.candidates)}" for a in result.normalised.ambiguities
            )
            text = f"{text}\n[The speech recogniser was unsure: {notes}. Ask if it matters.]"

    if not text or not text.strip():
        live.set_state("READY")
        return await _answer(
            runtime, session_id, "I did not catch that.", request=request, error_kind="empty",
            timings=timings, started=started, transcript=transcript_info, speak=speak, epoch=epoch,
        )
    text = text.strip()[:MAX_TEXT_CHARS]

    # A new instruction, now that there is one. Whatever the assistant proposed under the last
    # one is withdrawn: a proposal is bound to the conversation position it was made in, and
    # this is a new one. A fumbled hold or a recording that said nothing is not an instruction
    # and withdraws nothing; the card the owner was about to tap survives it.
    # A bare "yes" while a card is waiting is not a new instruction and applies nothing; it
    # is answered here, in a fixed sentence, without the model and without withdrawing the
    # card — the owner is told again what applies it. Anything else said is an instruction.
    # Which half of the orb is being spoken to, before anything is withdrawn: a question
    # asked over here is not a new instruction to a card waiting over there.
    # A recipe's half of a compound answer, when there is one: its cards and its reads are
    # carried into the model turn below rather than ending it (brief section 16).
    fast_partial = None
    branch = live.branch(branch_id)
    # Everything downstream that is handed only the session — the action engine when it
    # stages, working sets when they are created — asks the session which half is speaking.
    live.acting_branch = branch.branch_id
    waiting = _waiting_proposal(runtime, live, branch.branch_id)
    if waiting is not None and is_affirmation(text):
        live.heard = text
        live.set_state("READY")
        # The card is re-presented as it stands: its clock started when it was delivered and
        # a spoken yes does not wind it back. The tablet keeps the card it already shows.
        calls = [ToolCall(name=waiting.tool_name, args={}, ok=True, result={}, proposal_id=waiting.proposal_id)]
        return await _answer(
            runtime, session_id, _affirmation_answer(live, waiting), request=request, timings=timings, started=started,
            transcript=transcript_info, question=text, speak=speak, calls=calls, epoch=epoch, revoked=[],
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
        if not _is_a_command(text, branch):
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

    # The hourly catalogue refresh is a Shopify round trip; it runs beside this turn, not
    # in front of it. This question is answered with the catalogue as it stands.
    runtime.refresh_catalogue_soon()

    # ---------------------------------------------------------------- the fast lane
    # Most of what is said to a tablet on a workbench is not a new problem. If the Mac knows
    # the procedure for this one — an order, a customer, a period, "next", "what can you do"
    # — it runs it and answers, with no model on the critical path. A recipe that is not sure
    # defers, and the turn carries on to Claude exactly as it did before.
    live.heard = spoken.strip()
    lane, lane_why, intent, recipe = _route(text, branch)
    if timeline.current().active is not None:
        timeline.emit(
            "lane", session_id=session_id, turn_id=live.turn_id, lane=lane, why=lane_why,
            branch_id=branch.branch_id, recipe_id=(recipe.recipe_id if recipe else None), **intent.public(),
        )
    # What this half is doing, in the owner's words, while it does it. A half he has put
    # aside says this on its own chip rather than taking his attention (brief section 17).
    # `begin_turn` rather than `working`: the branch counts turns actually in flight, so
    # WORKING on a chip is a fact and not a note left behind by a turn that died.
    branch.begin_turn(_working_words(lane, intent))
    # The workspace starts NOW, not when the reads are done (§7, D-5). A family the router
    # recognised already knows what kind of card is coming, so its skeleton goes up before the
    # first read is issued; the rest arrive as each read lands (app/tools/dispatch.py) and are
    # collected by the tablet's /state poll. `turn_c8eb4cffe077` waited 7,975 ms for its first
    # card and the owner said the system "waits and then dumps a large chunk".
    progressive.begin(
        session_id, turn_id=live.turn_id, branch_id=branch.branch_id,
        family=str(getattr(intent, "family", "") or ""),
    )
    if lane == "FAST" and recipe is not None:
        # The rail is worked out beside the read, not after it. A fast turn used to answer with
        # `writes` still None — that variable is set further down, on the path the fast lane
        # returns before reaching — so present() built the card with no actions on it and an
        # order looked up quickly offered nothing to do with the order.
        #
        # Beside, though, and not in front. This was an `asyncio.gather` of the two, with a
        # comment claiming the preflight is cached and so costs nothing — which was wrong on
        # both halves. Before that change a read turn never called `writes_context` at all
        # (`_answer` asks for it only when something was proposed), and the scope caches behind
        # it last ten minutes, so every expiry, every restart and every cold tablet paid
        # `WRITE_STATUS_TIMEOUT_S` on the fastest turn in the system: measured, "what can you
        # do now?" went from 24 ms to 1508 ms with a slow scope check. So the preflight starts
        # here and is only waited for by an answer that has a card to hang a rail on. A recipe
        # that draws from its own state — capability, navigation, the end of a list — reads
        # nothing and offers nothing, and now pays nothing.
        preflight = (
            asyncio.create_task(writes_context(request)) if request is not None else None
        )
        fast = await _fast(runtime, live, branch, intent, recipe, text)
        fast_writes = None
        if preflight is not None:
            if fast is not None and fast.calls:
                fast_writes = await preflight
            else:
                preflight.cancel()
        if fast is not None and fast.partial and fast.continuation:
            # The recipe drew the workspace and says the rest is Claude's (brief section 16).
            # The turn does NOT end here: the cards are kept, the continuation is put to the
            # model, and one answer comes back with both halves. The alternative — returning
            # the recipe's sentence and arming the branch — made the owner ask twice, which is
            # what the bench's thirty-five-second compound turn already cost him once.
            fast_partial = fast
            timings["fast_partial"] = (time.perf_counter() - started) * 1000
            lane, lane_why = "NORMAL", f"the fast path drew {recipe.recipe_id} and handed the words to Claude"
        elif fast is not None:
            return await _answer(
                runtime, session_id, fast.answer, request=request, timings=timings, started=started,
                transcript=transcript_info, question=spoken.strip(), speak=speak,
                # What is worth looking at, which is not always everything that was read. The
                # reads themselves still reach the log and the timeline, on the line below.
                calls=fast.calls if fast.drawn is None else fast.drawn,
                epoch=epoch, seq=seq, revoked=revoked, tool_calls=_fast_tool_calls(fast.calls),
                lane=lane, recipe_id=recipe.recipe_id, branch=branch, partial=fast.partial,
                surfaces=fast.surfaces, writes=fast_writes,
                # When the facts were in hand on this lane: the recipe's own measurement of
                # its reads (section 25's time-to-first-useful-workspace). There is no model
                # step to read it from, and the whole point of the lane is that the two
                # numbers are nearly the same.
                measures={"recipe_reads_ms": (fast.trace or {}).get("critical_path_ms") or (fast.trace or {}).get("ms")},
            )
        elif fast is None:
            lane, lane_why = "NORMAL", "the fast path deferred"

    await _ensure_provider_started(runtime)

    # What was heard, on the session now, so the tablet can show it while Claude thinks
    # rather than only once the answer lands — a mis-heard question is visible at once.
    live.heard = spoken.strip()

    # What the Mac already knows about applying a change from this request, before the model
    # is asked: a change proposed while changes are off must never be announced as something
    # to tap. Asked once per turn (the scope answer is cached), and reused for the card.
    # An order number in the question is looked up before the model is asked: the Mac
    # already knows it is an order number, the lookup is the model's first step anyway, and
    # having the record — and its id issued — saves a model round trip and the stumble of a
    # note proposed for an order that has not been looked up yet. It runs beside the scope
    # preflight, which does not depend on it.
    prefetched: list[ToolCall] = []
    prompt_text = f"{_now_line(runtime)}\n{text.strip()}"
    writes, lookup = await asyncio.gather(
        writes_context(request) if request is not None else _none(),
        _prefetch_order(runtime, live, text, prefetched, timings),
    )
    live.writes_blocked = "" if writes is None or writes["allowed"] else _blocked_words(writes)
    if lookup:
        prompt_text = f"{prompt_text}\n\n{lookup}"
    from app.analytics import sets as working_sets

    set_line = working_sets.prompt_line(live, branch=branch)
    if set_line:
        prompt_text = f"{prompt_text}\n\n{set_line}"
    for extra in _context_lines(live, text, runtime=runtime):
        prompt_text = f"{prompt_text}\n\n{extra}"
    if fast_partial is not None and fast_partial.continuation:
        # Last, so it is the freshest thing in front of the model, and marked as the Mac's own
        # reading rather than something the owner said.
        prompt_text = f"{prompt_text}\n\n{fast_partial.continuation}"
    where = _branch_line(branch)
    if where:
        prompt_text = f"{prompt_text}\n\n{where}"
    if timeline.current().active is not None:
        timeline.emit(
            "prefetch", session_id=session_id, turn_id=live.turn_id, order_numbers=spoken_order_numbers(text), hit=bool(lookup),
            ms=(round(timings["prefetch"], 1) if "prefetch" in timings else None), hydrating=live.hydrating is not None, writes_code=(None if writes is None or writes["allowed"] else writes.get("code")),
        )

    # What the model is about to be given, in numbers (brief section 11). Counts only: no
    # part of the prompt is written anywhere, here or on the timeline. Kept apart from
    # `timings`, which is milliseconds and is published as such.
    measures = {"model_input_chars": len(prompt_text), "tool_schema_bytes": _tool_schema_bytes(runtime)}
    if fast_partial is not None:
        # The facts were in hand when the RECIPE finished reading, not when the model's
        # sentence landed — which is exactly the gap section 25 asks to be measured.
        measures["recipe_reads_ms"] = (fast_partial.trace or {}).get("critical_path_ms") or (fast_partial.trace or {}).get("ms")
    t0 = time.perf_counter()
    result = await _provider_turn(runtime, session_id, prompt_text, branch)
    timings["agent"] = (time.perf_counter() - t0) * 1000
    for step, ms in getattr(result, "steps", None) or []:
        timings[f"step:{step}"] = ms
    if timeline.current().active is not None:
        timeline.emit(
            "model", session_id=session_id, turn_id=live.turn_id, ms=round(timings["agent"], 1), steps=list(getattr(result, "steps", None) or []),
            error_kind=result.error_kind, stopped_early=result.stopped_early, answer=result.text or None,
            tool_calls=[{"tool": c.name, "ok": c.ok, "tool_call_id": getattr(c, "tool_call_id", "") or None, "proposal_id": c.proposal_id} for c in result.tool_calls or []],
        )
    if prefetched:
        result.tool_calls = _hydrated(live, prefetched + list(result.tool_calls or []))

    answer = result.text or "I could not work out an answer to that."
    if fast_partial is not None and fast_partial.answer:
        # The recipe's sentence LEADS, and the model's follows it. Section 16 splits this turn
        # deliberately: the mechanics are the Mac's and the synthesis is Claude's, so the facts
        # the owner hears first — who wrote, when, whether we replied — are the ones that were
        # read, not the ones that were generated. It is also what is left if the model fails:
        # the fallback sentence lands after a true one instead of instead of it.
        answer = f"{fast_partial.answer.rstrip()} {answer}"
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
            for c in list(result.tool_calls) + (list(fast_partial.calls) if fast_partial is not None else [])
        ] + [],
        # The recipe's cards, in front of whatever the model's own reads drew. A compound
        # answer is one screen: the workspace the Mac built and the sentence Claude wrote
        # about it, not two turns' worth of cards (brief section 16).
        calls=(
            list(fast_partial.calls if fast_partial.drawn is None else fast_partial.drawn) + list(result.tool_calls or [])
            if fast_partial is not None else result.tool_calls
        ),
        surfaces=(list(fast_partial.surfaces) if fast_partial is not None else None),
        # A compound turn is still a recipe turn: it ran, it did the reads, and the report and
        # the timeline should be able to say which one, next to the model call it handed on to.
        # Nameless, the only NORMAL turns with `recipe_reads_ms` on them would be unattributable.
        recipe_id=(recipe.recipe_id if fast_partial is not None and recipe is not None else ""),
        speak=speak,
        lost_thread=lost_thread,
        epoch=epoch,
        seq=seq,
        revoked=revoked,
        writes=writes,
        branch=branch,
        measures=measures,
    )


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


def _performance(timings: dict, *, lane: str, recipe_id: str, branch, calls, partial: bool, session, measures: dict, ui: list | None = None, glass: dict | None = None) -> dict:
    """The turn's own measurements. No content, no arguments, no personal data: counts,
    milliseconds and names of tools."""
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
        "lane": lane,
        "recipe_id": recipe_id or None,
        "fast_path_hit": lane == "FAST",
        "branch_id": getattr(branch, "branch_id", None),
        "parent_branch_id": (getattr(branch, "parent_id", "") or None),
        "backgrounded": getattr(branch, "status", "") == "BACKGROUND",
        "cancelled": bool(getattr(session, "abandoned", False) or getattr(branch, "abandoned", False)),
        "partial": bool(partial),
        "tool_calls": len(calls or []),
        "source_ms": sources,
        "stt_ms": round(float(timings.get("transcribe") or timings.get("stt") or 0.0), 1) or None,
        "model_ms": round(float(model_ms), 1) if model_ms is not None else None,
        "model_calls": 0 if lane == "FAST" else 1,
        "model_phases": model_phases or None,
        "model_input_chars": measures.get("model_input_chars"),
        "tool_schema_bytes": measures.get("tool_schema_bytes"),
        "prefetch_ms": round(float(timings["prefetch"]), 1) if "prefetch" in timings else None,
        # Section 25's three numbers, kept apart on purpose.
        #
        # `facts_ms` is when the Mac HELD the authoritative data the cards are drawn from —
        # the last read to land. A progressive workspace could be on screen at that moment,
        # and on the FAST lane it effectively is.
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
    have been drawn. The fast lane has no model, so its reads are its critical path, which
    the recipe measures and passes here. A turn that read nothing — a capability answer, a
    navigation move — has no facts time and is not counted as slow prose.

    A recipe's reads come FIRST where there are both. On a compound turn (§16) the cards are
    the recipe's and the model is there to write about them, so the last model step is not
    when the facts arrived — it is a draft being composed from facts already held, and
    reading it as "facts_ms" would report a twenty-second turn as twenty seconds of reading
    and nothing waited. Which is the opposite of the number §25 asks for.
    """
    recipe_ms = measures.get("recipe_reads_ms")
    facts = float(recipe_ms) if isinstance(recipe_ms, (int, float)) else None
    if facts is None:
        steps = [float(v) for k, v in timings.items() if k.startswith("step:tool:") and isinstance(v, (int, float))]
        facts = max(steps) if steps else None
    if facts is None and calls:
        # No per-step offsets (a fast lane that did not report, a provider that does not
        # measure): the reads themselves are the floor, run in parallel where they could be.
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


def _route(text: str, branch):
    """(lane, why, intent, recipe) for this request. Structure only: no source is touched."""
    from app.fastpath import choose_lane, recipe_for, resolve

    intent = resolve(text, branch=branch)
    recipe = recipe_for(intent.family) if intent.family else None
    lane, why = choose_lane(intent, recipe=recipe, text=text)
    return lane, why, intent, recipe


# The other thing a request asked for, said in a clause. Explicit requested work outranks
# contextual status (§14, D-14) — but the status half was ASKED, and the live session's answer
# to "are you okay now?" was the capability delta INSTEAD of the emails. Answering the work
# and saying nothing about the health would be the same mistake with the halves swapped.
#
# Fixed sentences, and true by construction: the Mac is answering, so it is running. Nothing
# here claims anything the turn has not already proved.
_SECONDARY_WORDS = {
    "capability_delta": "I'm back up and running.",
    "capability_summary": "I'm back up and running.",
    # And the family that answers the health question itself (app/families/interaction.py).
    # "Are you okay now?" used to reach `capability_delta` only because it carries the word
    # "now" — the delta answers "what MORE can you do", which is not what was asked. With a
    # family of its own for the status question, this is the clause that acknowledges it.
    "assistant_status": "I'm running fine.",
}


async def _fast(runtime, session, branch, intent, recipe, text: str):
    """Run a recipe. Returns its answer, or None when it deferred and Claude should answer."""
    from app.fastpath import run as run_recipe
    from app.fastpath.models import Ctx
    from app.memory import current as memory

    session.turns += 1
    session.set_state("THINKING", recipe.recipe_id)
    answer = await run_recipe(recipe, Ctx(runtime=runtime, session=session, branch=branch, intent=intent, text=text, memory=memory()))
    session.set_state("READY")
    if answer.deferred:
        # The turn is about to be answered properly; it was never a second turn.
        session.turns -= 1
        return None
    aside = _SECONDARY_WORDS.get(str(getattr(intent, "secondary", "") or ""))
    if aside and answer.answer:
        answer.answer = f"{aside} {answer.answer.lstrip()}"
    return answer


# What a lane is doing, said once, in words. Deliberately vague about the work and exact
# about the source: the owner does not need to know which tool, and must never be told what
# the model is thinking.
_WORKING = {
    "order_lookup": "reading the order", "order_status_lookup": "reading the order",
    "order_address_lookup": "reading the order", "customer_purchase_lookup": "reading the customer",
    "best_sellers_period": "adding up the sales", "sales_breakdown_period": "adding up the sales",
    "delayed_orders": "listing what is late", "stock_cover_analysis": "checking stock",
    "needs_reply": "checking the inbox", "inbox_state": "checking the inbox",
    "working_set_next": "reading the next one", "working_set_previous": "reading the last one",
}


def _working_words(lane: str, intent) -> str:
    if lane == "DEEP":
        return "working through it"
    return _WORKING.get(getattr(intent, "family", ""), "working it out")


# Families that are instructions to the assistant rather than words about a record. A
# continuation must not swallow one: tapping Note and then saying "go back" abandons the note,
# it does not write "go back" into it. Deciding this from the family rather than from a list of
# phrases means it holds for however those things are said.
# Sentences that are instructions to the assistant, whatever control was tapped a moment ago.
# Two kinds. These are the ones that command it directly: "go back", "next", "what can you do".
_NEVER_A_CONTINUATION = frozenset({
    "navigation_back", "navigation_home", "working_set_next", "working_set_previous",
    "capability_summary", "capability_delta", "order_reopen",
    # And every other way of saying "move the screen": the dock's four landings, a tab on the
    # record, and the switch to the other half of the orb. Tap Note on #1938, say "open the
    # inbox", and the inbox is what should open.
    "landing_orders", "landing_inbox", "landing_sales", "landing_products",
    "order_tab_show", "branch_switch",
    # And §4's two ways of saying it in words the router had no family for at all
    # (app/families/ui_intent.py). "Take me to the inbox" said over a tapped Add a note is
    # the inbox, not note text — the same rule the dock's four landings are here for.
    "ui_area_workspace",
    # And the two that are about the machine rather than about the shop (§15, §16). "What does
    # the split button do" is a question to the assistant, like "what can you do"; "log that
    # your split function is broken" is an instruction to write something down. Tap Add a note
    # on #1938 and say either of them, and a note containing it is the last thing wanted.
    "ui_semantics", "owner_feedback",
    # And "what is on this screen" (D-11), which is the same kind of question as "what does
    # the split button do" — about the machine, not about the record. Tap Add a note on #1938,
    # ask what is on the screen, and a note containing the question is the last thing wanted.
    "screen_state",
    # And §24's three (app/families/interaction.py). "Stop" said over a tapped Add a note is
    # an interruption — it abandons the note, it does not become its text — and a hello or a
    # "are you working?" is a word to the assistant, not dictation for the control.
    "interaction_stop", "greeting", "assistant_status",
})
# And these are the ones that NAME THEIR OWN SUBJECT, which the glue would then overrule. Tap
# Add a note on #1938, then ask "how many orders today", and the model was handed
#
#     how many orders today
#     [This continues order.add_note on the order the owner is looking at (#1938) … Apply it
#      to that record and to nothing else.]
#
# — a sales question turned into an instruction about one order's note, and the turn dropped
# off the fast lane on the way. "Show me order 1782" was glued to #1938 the same way.
#
# Dictated note and rewrite text is not in either set, because it does not resolve to a
# confident family: "he wants it by Friday" names no order, no period and no list, so it is
# still taken as the words the tapped control was waiting for. That is the whole distinction —
# a sentence the router can already act on is not dictation.
_CARRIES_ITS_OWN_SUBJECT = frozenset({
    "order_lookup", "order_list_period", "order_status_lookup", "order_address_lookup",
    "customer_history_lookup", "customer_purchase_lookup", "sales_breakdown_period",
    "best_sellers_period", "stock_cover_analysis", "delayed_orders", "inbox_state",
    "needs_reply",
    # Phase 3's families, on the same rule. The email pair says which record it is asking
    # about ("this order") and then reads the thread; the latest order and the two list
    # questions name the set they want; adding an item to an order is an instruction in its
    # own right, and a tapped Note must not swallow it as note text.
    "order_latest", "order_email_draft", "order_email_waiting",
    "unfulfilled_orders", "international_orders", "order_add_item",
    # And the composer's three. "Write an email to <address> …" names the address it is going
    # to; "make it shorter" and "send it instead" name the composer or the draft in front of
    # the owner. None of them is dictation for a control tapped a moment ago — the composer's
    # own fields are typed into, and its rewrite arrives as words with a composer open, which
    # is a different mechanism from a bound control.
    "email_compose_any", "compose_rewrite", "draft_send_instead",
    # And the commerce families' four (app/families/discounts.py, order_create.py,
    # abandoned.py), on the same rule. "How many abandoned checkouts" is a question about the
    # shop and names the window it wants; "create an order for Poppy De-Witt" names the
    # person it is for; the two discount families name the code. None of them is dictation
    # for a control tapped a moment ago — tap Add a note on #1938, ask what has been
    # abandoned, and it is the abandonment that should be answered.
    "abandoned_checkouts", "discount_code", "order_new", "order_new_line",
    # §4's workspace family (app/families/ui_intent.py). "Expand David's customer page" names
    # the person it is about; tap Add a note on #1938 and say it, and the customer's page is
    # what should open, not a note containing the sentence.
    "customer_workspace",
    # And the summary families (app/families/summaries.py), on the same rule. "Any returning
    # customers today", "which orders need attention" and "what came in yesterday" each name
    # the period and the question they are about. Tap Add a note on #1938 and ask any of
    # them, and it is the summary that should be answered — not a note containing the words.
    "returning_customers", "returning_customers_before", "orders_attention",
    "order_list_summary",
})


def _is_a_command(text: str, branch: Any) -> bool:
    """Whether this sentence is an instruction in its own right.

    Resolved from the words the owner actually said, before any continuation note is added —
    the note is for the model, and routing must not see it.
    """
    from app.fastpath import resolve

    try:
        family = resolve(text, branch=branch).family
    except Exception:  # noqa: BLE001 — a router that cannot decide is not a reason to fail a turn
        return False
    return family in _NEVER_A_CONTINUATION or family in _CARRIES_ITS_OWN_SUBJECT


def _with_continuation(text: str, continuation: dict) -> str:
    """The sentence, with what it applies to said plainly beside it.

    A bracketed note rather than a new mechanism: the recogniser's ambiguity note already uses
    this shape, the model already reads it, and it survives being logged. The reference is the
    record's id and its label — never its contents.
    """
    family = str(continuation.get("family") or "")
    kind = str(continuation.get("kind") or "record").replace("_", " ")
    label = str(continuation.get("label") or "").strip()
    ref = str(continuation.get("ref") or "")
    named = f" ({label})" if label else ""
    return (
        f"{text}\n[This continues {family} on the {kind} the owner is looking at{named}"
        f"{f', id {ref}' if ref else ''}. Apply it to that record and to nothing else.]"
    )


def _fast_tool_calls(calls) -> list[dict]:
    """The fast lane's reads, in the shape the turn log and the tablet already read."""
    return [
        {"name": c.name, "ok": c.ok, "error": c.error, "ms": c.duration_ms, "args": _loggable_args(c),
         "proposal_id": c.proposal_id, "tool_call_id": getattr(c, "tool_call_id", "") or None}
        for c in calls or []
    ]


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
    return f"[Where we are: {'; '.join(bits)}.]" if bits else ""

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
_WANTS_SEND = re.compile(r"\b(?:send|sends|email them|email him|email her|email the|let (?:them|him|her) know|tell (?:them|him|her)|get back to|chase|fire (?:it|them) off)\b", re.I)


def _draft_or_send(text: str) -> str:
    draft, send = bool(_WANTS_DRAFT.search(text)), bool(_WANTS_SEND.search(text))
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


def is_affirmation(text: str) -> bool:
    words = re.sub(r"[^a-z' ]+", " ", text.lower()).split()
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


# The lookup ahead of the model gets less time than a tool call the model makes: past this,
# the model does its own looking up and nothing was lost but the head start.
PREFETCH_TIMEOUT_S = 2.5

# An order number the owner SAID: the cue, then the number, and nothing between them but
# "number", "no." or "#". Four digits, because that is what CROOKS issues; not a year unless
# written as a number ("order number 2025", "#2025"); and never "orders over 500 pounds",
# "orders from 2025" or "orders in the last 100 days", which name no order.
_SPOKEN_ORDER = re.compile(
    r"\b(?:order|invoice)\b\s*(?P<explicit>(?:number|no\.?|#)\s*#?\s*)?(?P<digits>\d{4})\b"
    # Not a figure with a unit after it, and not the head of something the recogniser left
    # half-converted ("1930-eight"): a number that runs into a word is not an order number.
    r"(?!\s*(?:pounds?|quid|days?|items?|units?|percent|%|per\b))"
    r"(?![\u2010-\u2015-]?[A-Za-z])",
    re.I,
)


def spoken_order_numbers(text: str) -> list[str]:
    """The order numbers the owner named, if any. CROOKS issues four digits; "order 2025" is
    read as the year unless it was said as a number ("order number 2025", "order #2025")."""
    found: list[str] = []
    for match in _SPOKEN_ORDER.finditer(text):
        digits = match.group("digits")
        looks_like_a_year = 2000 <= int(digits) <= 2099
        if looks_like_a_year and not match.group("explicit"):
            continue
        if digits not in found:
            found.append(digits)
    return found


async def _prefetch_order(runtime, session, text: str, calls: list, timings: dict) -> str:
    """Look one spoken order number up through the same gate the model uses. Returns the
    text to hand the model, or nothing when there was no single order number, or the lookup
    failed (the model then does it itself, as before)."""
    from app.tools.dispatch import dispatch

    numbers = spoken_order_numbers(text)
    if len(numbers) != 1:
        return ""
    number = numbers[0]
    session.set_state("CHECKING SHOPIFY", "shopify_find_order")
    t0 = time.perf_counter()
    try:
        rendered = await dispatch(
            "shopify_find_order", {"query": number}, session=session,
            timeout_s=min(PREFETCH_TIMEOUT_S, runtime.settings.tool_timeout_s), calls=calls,
        )
    finally:
        timings["prefetch"] = (time.perf_counter() - t0) * 1000
    if not calls or not calls[-1].ok:
        calls.clear()
        return ""
    # One order: its full picture is read now, beside the model rather than in front of it.
    # If the model asks for the detail it is answered at once; if it does not, the card still
    # shows the whole order when the read has landed by the time the answer does.
    found = calls[-1].result.get("orders") if isinstance(calls[-1].result, dict) else None
    hydrating = ""
    if isinstance(found, list) and len(found) == 1 and isinstance(found[0], dict) and found[0].get("order_id"):
        session.hydrating = _hydrate_soon(str(found[0]["order_id"]))
        hydrating = (
            " The full order (items, money, address, tracking, the customer's history and their "
            "recent email) is being read beside you: call shopify_order_detail if the answer needs "
            "any of it — it answers at once."
        )
    return (
        f"[CLIVE already ran shopify_find_order(query=\"{number}\") for this question. Its result:\n"
        f"{rendered}\nUse it as if you had called the tool; do not call shopify_find_order for "
        f"{number} again.{hydrating}]"
    )


def _hydrate_soon(order_id: str) -> asyncio.Task | None:
    """Start the order's full read in the background. Never awaited by the turn itself.

    Lane 4 — "an active branch's requested background job". The owner asked for this order,
    so it outranks a guess; he is not waiting on this read, so it yields to his next question
    (app/reads/budget.py). A task copies the context at creation, which is why entering the
    lane here is enough for everything the read reaches.
    """
    from app.reads import budget
    from app.tools.shopify_tools import hydrator

    async def read() -> Any:
        with budget.using(budget.BACKGROUND, f"hydrate:{order_id}", yielding=False):
            return await hydrator().order(order_id)

    try:
        return asyncio.get_running_loop().create_task(read())
    except Exception as exc:  # noqa: BLE001 — Shopify not bound; the model looks it up itself
        log.debug("no background hydration: %s", exc)
        return None


def _hydrated(session, calls: list) -> list:
    """The order the Mac read beside the model, as a tool call the card is built from — when
    it landed in time and the model did not read it itself. The ids in it are issued as any
    tool result's are. Nothing is waited for: a read still in flight is collected by the
    tablet from /context/order once the card is up."""
    task = getattr(session, "hydrating", None)
    if task is None:
        return calls
    session.hydrating = None
    if not task.done() or task.cancelled() or task.exception() is not None:
        if task.done() and task.exception() is not None:
            log.debug("background hydration failed: %s", task.exception())
        return calls
    result = task.result()
    if not isinstance(result, dict) or any(c.name == "shopify_order_detail" and c.ok for c in calls):
        return calls
    from app.tools.dispatch import harvest_ids

    harvest_ids(result, session)
    return list(calls) + [ToolCall(name="shopify_order_detail", args={"order_id": result.get("order_id", "")}, ok=True, result=result)]


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


async def _none():
    return None


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
    lane: str = "NORMAL",
    recipe_id: str = "",
    branch: Any = None,
    partial: bool = False,
    measures: dict | None = None,
    surfaces: list | None = None,
    seq: int | None = None,
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
    # The turn is over: whatever it was doing (hearing, checking Shopify, thinking), the
    # session says so now, so a /state poll that outlives the turn cannot report otherwise.
    if session is not None and session.state not in ("READY", "ERROR"):
        session.set_state("ERROR" if error_kind else "READY")
    timings["total"] = (time.perf_counter() - started) * 1000
    # What the screen shows beside the answer: cards chosen from the tool results, never from
    # the prose. See app/presentation.py for the vocabulary and the bounds.
    ui = present(calls, session=session, error_kind=error_kind, writes=rail)
    # The same turn as a validated scene, when CLIVE_SCENES is on: planned from these reads,
    # carried as its own field and changing nothing else. Off, nothing here runs.
    scene = _turn_scene(question or str((transcript or {}).get("text") or ""), answer, calls, session_id)
    # A card a recipe built for itself, for an answer no tool produced. It goes in front of
    # the context stack and behind nothing: it IS the answer to the question that was asked.
    if surfaces:
        ui = [s.as_ui() if hasattr(s, "as_ui") else s for s in surfaces] + ui
    # One cursor, one headline per kind, the rest folded (brief section 22). Here rather than
    # inside present(): a recipe's own cards are in front of the tool cards by now, and it is
    # the two together that have to fit an eight-inch screen.
    ui = compact(ui)
    # When the Mac had cards to show, as a fact and not an inference (brief section 25 asks
    # for time-to-first-useful-workspace measured APART from the whole turn). Taken here,
    # after present(), because this is the moment the workspace exists.
    timings["workspace"] = (time.perf_counter() - started) * 1000
    turn_id = getattr(session, "turn_id", "") if session is not None else ""
    if branch is None and session is not None:
        branch = session.branch()
    if branch is not None:
        # The answer is here. A half the owner is looking at simply goes quiet; one he has
        # put aside — or simply tapped away from while it was working — says "ready" on its
        # chip and pulses once, and does not take his attention. The live test found a half
        # that finished a ten-second turn with zero change on the tablet and an answer that
        # could never be read: it was not BACKGROUND, only not looked at, so it went idle.
        elsewhere = bool(session is not None and getattr(session, "focused_branch", "") and session.focused_branch != branch.branch_id)
        # The turn is over however it ended. Counted down first, so nothing below can leave a
        # half saying it is working when it is not.
        branch.end_turn()
        if error_kind:
            branch.failed("that did not work")
        elif branch.status == "BACKGROUND" or elsewhere:
            branch.ready("there is an answer")
        else:
            branch.idle()
        # What this half now shows, kept on the Mac so tapping it later draws it (branch.show).
        branch.shown(ui, answer, question)
    for call in calls or []:
        if branch is not None and getattr(call, "ok", False):
            branch.remember_result(call.name, summary=_call_summary(call), ref=_call_ref(call), ms=float(getattr(call, "duration_ms", 0.0) or 0.0))
    # The turn's own cards, reconciled against what the progressive workspace already put on
    # the glass (§7, §25). A card that is unchanged is NOT redrawn — the whole point — and one
    # that gained its rail or an enrichment is patched in place. The numbers come back for the
    # performance record; the patches themselves the tablet has already collected from /state.
    glass = progressive.complete(session, ui, branch_id=getattr(branch, "branch_id", "") or "")
    # How this turn actually went, in numbers. Every field is measured; none of it is content.
    # This is what the report's speed section and the bench read (brief section 32).
    performance = _performance(timings, lane=lane, recipe_id=recipe_id, branch=branch, calls=calls, partial=partial, session=session, measures=measures or {}, ui=ui, glass=glass)
    if timeline.current().active is not None:
        # An answer that declines, held against what the Mac composes: a refusal of a best
        # seller, a breakdown, a comparison or a bulk change the tools could have made is a
        # FALSE UNSUPPORTED claim, and the report counts it. Words only; no reasoning text.
        from app.observability import claims

        signal = claims.claim(question or (transcript or {}).get("text") or "", answer, tool_calls, claims.registered(), hinted=bool(getattr(session, "hinted", False)))
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
        "test_session_id": timeline.current().active_id,
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
        # Which lane answered, and where the conversation now is. The tablet renders its
        # navigation from this rather than from what it can see on screen.
        "lane": lane,
        "recipe_id": recipe_id or None,
        "branch": branch.public() if branch is not None else None,
        # Both halves, when there are two, so the tablet draws what the Mac holds rather
        # than what it remembers doing.
        "branches": (
            {"focused": session.focused_branch,
             "branches": [b.public() for b in session.branches.values() if b.status in ("ACTIVE", "BACKGROUND")]}
            if session is not None and session.branches else None
        ),
        "partial": bool(partial),
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
