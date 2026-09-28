"""POST /command — a tap: a button that names what it does.

Only taps come here. Words never do: a sentence, typed or spoken, is a model turn on /turn,
and nothing matches its words to a command. A tap is different in kind — it names its action
explicitly, so there is nothing to understand and no model on the path.

The tablet posts which command it was and which record it was on. It does not post what the
command should do, and it cannot: the body is a name from a fixed registry plus a reference,
and the Mac decides the rest. That is the same rule the write boundary keeps — the tablet
carries identity, never arguments — applied to the read side, where it costs nothing and
removes a class of bug that starts with the client and the server disagreeing about what a
button means.

The response is the shape `/turn` returns: an answer, a `ui` list, the branch state. So the
tablet renders a tap and a spoken instruction with the same code, and so does everything
downstream of it — the timeline, the report, the experience harness.

Nothing here can change the shop or the inbox. Almost every command in the registry is a read
or a move. One kind is not — a command may PROPOSE a change (`_stage_change`), which is what
the brief means by "the model or a touch command proposes": the Mac reads the entity afresh,
builds and stores the exact execution arguments, and answers with a card that is still
waiting. Applying it is `/actions/{id}/commit` with a proposal id and nothing else, and that
is where the gesture, the freshness reread and the verification live. So this route can put a
change in front of the owner; it cannot make one.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app import commands
from app.observability import timeline
from app.presentation import compact, present
from app.reads import budget
from app.routes.actions import session_matches, writes_context

router = APIRouter(tags=["command"])
log = logging.getLogger("crooks.command")

MAX_REF_CHARS = 200


def _refuse(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.get("/commands", response_model=None)
async def listing() -> dict:
    """What the page may post, and which end of the system may reach each one.

    Derived from the registry, so the page cannot offer a control the server does not implement
    and the feature matrix cannot claim a command that does not exist.
    """
    return {"commands": commands.public()}


@router.post("/command", response_model=None)
async def command(
    request: Request,
    session_id: str = Form(default=""),
    command: str = Form(default=""),      # noqa: A002 — the field name the tablet posts
    branch_id: str = Form(default=""),
    kind: str = Form(default=""),
    ref: str = Form(default=""),
    label: str = Form(default=""),
    tab: str = Form(default=""),
    surface: str = Form(default=""),
    family: str = Form(default=""),
) -> JSONResponse | dict:
    runtime = request.app.state.runtime
    session_id = (session_id or "").strip()
    if not session_id:
        return _refuse(400, "wrong_session", "The session is missing.")
    name = (command or "").strip()
    try:
        session = runtime.sessions.get(session_id)
    except KeyError:
        # A tap on a fresh tablet — the dock from the idle screen — is as legitimate a first
        # request as a sentence is, and /turn creates the conversation for a sentence. A
        # command about a record the tablet claims to have, though, has nothing to be about
        # when the conversation is gone: those still say so.
        if name not in FRESH_START:
            return _refuse(409, "no_session", "That conversation has gone; ask again.")
        session = runtime.sessions.get_or_create(session_id)
    if not session_matches(session, request):
        # A conversation is its first caller's, on this route as on every other.
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")

    spec = commands.get(name)
    if spec is None:
        return _refuse(400, "unknown_command", f"There is no command called {name!r}.")
    if not spec.touch:
        return _refuse(400, "not_tappable", f"{name!r} is not something the screen can post.")

    branch = session.branch(branch_id) if branch_id else session.branch()
    # A tap is addressed to a half too, and anything it causes downstream — a read that opens
    # a working set, a proposal — must be filed against that half rather than the focused one.
    session.acting_branch = branch.branch_id
    started = time.perf_counter()
    outcome = commands.run(name, commands.Ctx(runtime, session, branch, await _arguments(request, {
        "kind": (kind or "").strip()[:40],
        "ref": (ref or "").strip()[:MAX_REF_CHARS],
        "label": (label or "").strip()[:120],
        "tab": (tab or "").strip()[:40],
        "surface": (surface or "").strip()[:40],
        "family": (family or "").strip()[:40],
    })))
    recipe_id = outcome.changed.get("recipe") if outcome.ok and isinstance(outcome.changed, dict) else None
    if recipe_id:
        # A command that names a place rather than a record — a dock landing — or a read a
        # form needs (who is that customer, is that code taken). Commands are synchronous and
        # read nothing themselves; the recipe reads, through the read scheduler and the
        # registered read tools, and no model: a button is not a sentence.
        outcome = await _run_recipe(runtime, session, branch, str(recipe_id), outcome)
    wanted = outcome.changed.get("stage") if outcome.ok and isinstance(outcome.changed, dict) else None
    if isinstance(wanted, dict):
        # A command that PROPOSES a change — the touch half of "the model or a touch command
        # proposes": Add on the variant picker (app/families/order_edit.py), Save draft or Send
        # on the composer (app/families/compose.py). Same reason as the recipe above: a command
        # is synchronous, and preparing a change is a fresh read of the entity. What the tablet
        # named is a registered write tool and the arguments THE MAC built from its own
        # context; the gesture is still to come.
        outcome = await _stage_change(request, runtime, session, branch, wanted, outcome)
    elapsed = (time.perf_counter() - started) * 1000

    timeline.emit(
        "command", session_id=session.session_id, branch_id=branch.branch_id, command=name,
        ok=outcome.ok, code=outcome.code or None, ms=round(elapsed, 1),
        # The reference, never the record: a timeline is a record of what happened, not of
        # whose address was on the screen.
        entity=(outcome.changed.get("entity") or {}).get("kind") if isinstance(outcome.changed.get("entity"), dict) else None,
        replayed=bool(outcome.changed.get("replayed")),
    )
    if not outcome.ok:
        # A refusal is not an error: the owner tapped something that no longer applies. It
        # comes back 200 with the reason so the tablet can say so without a failure state.
        return {
            "ok": False, "code": outcome.code, "detail": outcome.detail, "answer": outcome.answer,
            # What the owner can do instead, when the refusal knows: an `offer` of commands the
            # tablet can post unchanged, and what this half holds. A refusal with nothing to
            # tap is a dead control, which is what a forked half was twice in the live session.
            "changed": outcome.changed,
            "ui": [], "command": name, "branch": branch.public(), "session_id": session.session_id,
            "ms": round(elapsed, 1), "lane": "TOUCH",
        }

    calls = list(outcome.calls)
    needs = outcome.changed.get("needs_read") if isinstance(outcome.changed, dict) else None
    if isinstance(needs, dict) and not calls:
        # The cursor landed on a record the Mac does not hold. Memory makes Back and Next
        # instant when it can; when it cannot, the record is read here rather than the tap
        # doing nothing. A button that moves a cursor and draws nothing is the worst of both.
        calls = await _read_member(runtime, session, needs)
        outcome.changed["read"] = bool(calls)
    ui = present(calls, session=session, writes=await _writes(request))
    if outcome.surfaces:
        ui = [s.as_ui() if hasattr(s, "as_ui") else s for s in outcome.surfaces] + ui
    # The same compaction a spoken turn gets: a tap on Inbox draws the queue and the recent
    # threads, and two email lists do not fit an eight-inch screen (brief section 22).
    ui = compact(ui)
    if any(item.get("type") != "context_stack" for item in ui):
        # What this half now shows, kept on the Mac: a tap that drew cards is as much this
        # half's workspace as a sentence that did, and `branch.show` redraws it after a
        # switch or a reload (app/session/branch.py).
        branch.shown(ui, outcome.answer, "")
    # A tap that opened a record is the other place the anticipation layer learns from and
    # reads ahead of (§18) — the spoken half arrives at /context/order. Background work only,
    # never awaited for its own sake, and never able to fail the tap.
    await _anticipate(session, branch, name, outcome, calls)
    return {
        "ok": True,
        "command": name,
        "answer": outcome.answer,
        "ui": ui,
        "changed": outcome.changed,
        "branch": branch.public(),
        "session_id": session.session_id,
        "ms": round(elapsed, 1),
        # `ms` above is how long the COMMAND took to resolve, measured before the read a
        # cursor move can cause and before the card is built — which is the number the
        # timeline wants. `served_ms` is the whole request, which is what the owner waited
        # and what a benchmark should print. They are the same for a replay and differ by
        # a Shopify round trip when memory had dropped the record.
        "served_ms": round((time.perf_counter() - started) * 1000, 1),
        # Named so the timeline and the report can tell a tap from a sentence without guessing.
        "lane": "TOUCH",
        "model_calls": 0,
    }


# Which tap means which learnable event (app/anticipation/models.py: EVENTS). A command not
# named here is not something the layer learns from; opening a record is, and so is a move.
ANTICIPATED: dict[str, str] = {
    "open.entity": "order_opened",
    "workflow.next": "next_record",
    "workflow.previous": "previous_record",
    "surface.tab": "tab_opened",
    "order.open_shipping": "tracking_checked",
    "order.open_items": "tab_opened",
}


async def _anticipate(session, branch, command_name: str, outcome, calls) -> None:
    """Tell the anticipation layer what the owner just tapped.

    Only for a tap that landed on an ORDER, because that is the only shape the rules read so
    far. Everything here is wrapped: a speculative layer must not be able to turn a tap that
    worked into a failure, and it must not add a Shopify round trip of its own — the order it
    describes is the one this tap already read.
    """
    event = ANTICIPATED.get(str(command_name or ""))
    if event is None:
        return
    entity = outcome.changed.get("entity") if isinstance(outcome.changed, dict) else None
    if not isinstance(entity, dict) or entity.get("kind") != "order" or not entity.get("ref"):
        return
    try:
        from app.anticipation import engine as anticipation
        from app.anticipation import signals

        order = next(
            (c.result for c in calls or []
             if isinstance(getattr(c, "result", None), dict) and c.result.get("order_id") == entity["ref"]),
            None,
        )
        signal = signals.for_order(str(entity["ref"]), order, session=session, branch=branch, event=event)
        await anticipation.observe(signal, session=session)
    except Exception as exc:  # noqa: BLE001 — never at the cost of the tap
        log.debug("anticipation on a tap failed: %s", type(exc).__name__)


# Commands a tablet may post before the conversation exists on the Mac.
FRESH_START = frozenset({"open.area"})

# Bounds on what a tap may carry. A command's arguments are identities and small values —
# an id, a field name, an address typed into a precision field, a quantity — never an
# execution argument (those the Mac builds); the bound keeps a runaway client from posting
# a document.
MAX_ARGS = 24
MAX_ARG_CHARS = 8000
RESERVED = frozenset({"session_id", "command", "branch_id"})


async def _arguments(request: Request, named: dict[str, str]) -> dict[str, str]:
    """Every field the tablet posted, the named ones already bounded, the rest bounded here.
    A family's command takes its own arguments (`area`, `compose_id`, `quantity` …) without
    this route having to know each one; the command decides what they mean."""
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 — not a form body: only the named fields
        return dict(named)
    args = dict(named)
    for key, value in list(form.multi_items())[:MAX_ARGS + len(RESERVED) + len(named)]:
        if key in RESERVED or key in args or not isinstance(value, str):
            continue
        if len(args) >= MAX_ARGS + len(named):
            break
        args[str(key)[:40]] = value[:MAX_ARG_CHARS]
    return args


async def _run_recipe(runtime, session, branch, recipe_id: str, outcome):
    """A recipe, run for a tap (app/recipes.py): the read-only assertion, the read scheduler
    and no model. What the tapped control narrowed the read to travels in `slots`."""
    from app import commands as command_mod
    from app import recipes
    from app.memory import current as memory

    recipe = recipes.RECIPES.get(recipe_id)
    if recipe is None:
        return command_mod.Outcome.refused("unknown_recipe", f"There is no recipe called {recipe_id!r}.")
    # A tap is its own interaction, and it is the owner NAVIGATING. Two things follow, and
    # D-4 was two things and this is both of them: the NAVIGATION lane keyed on THIS tap is a
    # fresh scope for the bounds (without which a press after a read-heavy turn was refused
    # outright) and for the reuse (without which the second press of the Assistant chip was
    # handed "the same query already ran this turn" and drew a landing with nothing on it).
    # Together they are the whole of the `landing_unavailable` on the tablet at 00:25:48. No
    # bound changed; only the scope they belong to.
    lane_key = timeline.new_id("tap")
    ledger = budget.ledger_for(session)
    refused_before = ledger.spend(budget.NAVIGATION, lane_key).refusals
    # A tap can be about something as well as somewhere. A landing is not — Orders is Orders —
    # but a picker is about a product, and the words that narrow it come from the control that
    # was tapped. Neither can carry an execution argument: a recipe cannot write
    # (app/recipes.py assert_read_only).
    slots = {str(k)[:40]: v for k, v in (outcome.changed.get("slots") or {}).items()}
    area = str(outcome.changed.get("area") or "")
    branch.begin_turn("opening " + (area or recipe.ui))
    try:
        with budget.using(budget.NAVIGATION, lane_key, scope=budget.scope_of(session)):
            answer = await recipes.run(recipe, recipes.Ctx(runtime=runtime, session=session, branch=branch, slots=slots,
                                                            text=str(outcome.changed.get("said") or ""), memory=memory()))
    finally:
        branch.end_turn()
        branch.idle()
    if answer.deferred:
        # Two different things, said differently. A tap that ran out of reading is not a
        # landing that does not exist — saying so is how the owner was told the screen was not
        # there when the truth was the budget. Either way the refusal is ACTIONABLE: the same
        # tap offered back, what this half holds, and where else it can go. One unactionable
        # sentence is what reached him on a forked half.
        offer = {"area": area, "retry": {"command": "open.area", "area": area} if area else None,
                 "offer": command_mod.offer_for(branch), "holds": branch.holds()}
        if ledger.spend(budget.NAVIGATION, lane_key).refusals > refused_before:
            return command_mod.Outcome.refused(
                "read_budget_spent",
                "That screen needed more reading than one tap is allowed. Tap it again in a moment.",
                changed=offer,
            )
        return command_mod.Outcome.refused(
            "landing_unavailable",
            f"{(area or 'That').capitalize()} could not be read just now ({answer.defer}). Tap it again, or ask for it out loud.",
            changed=offer,
        )
    calls = list(answer.calls if answer.drawn is None else answer.drawn)
    changed = {**outcome.changed, "recipe_id": recipe_id, "partial": bool(answer.partial),
               "reads": list((answer.trace or {}).get("reads") or []), "ms": (answer.trace or {}).get("ms")}
    return command_mod.Outcome(answer=answer.answer, calls=calls, surfaces=list(answer.surfaces), changed=changed)


async def _read_member(runtime, session, needs: dict) -> list:
    """Read one record, through the read scheduler and the registered read tools.

    Not a shortcut around the gate: `run_plan` refuses a plan naming anything but a read, and
    the tools are the registered ones. A tap can therefore cause a read and can never cause
    anything else.
    """
    from app.commands import MEMBER_READ
    from app.reads.scheduler import Read, ReadPlan, run_plan

    tool, argument, _kind = MEMBER_READ.get(str(needs.get("set_kind") or ""), ("", "", ""))
    ref = str(needs.get("ref") or "")
    if not tool or not ref:
        return []
    # The cursor landed somewhere the Mac does not hold: this is the owner's NAVIGATION being
    # hydrated, which is lane 2 and has its own budget. It was sharing the turn's.
    plan = ReadPlan([Read("member", tool, {argument: ref},
                          source="gmail" if tool.startswith("gmail_") else "shopify")],
                    label="command:member", lane=budget.NAVIGATION, key=timeline.new_id("tap"),
                    scope=budget.scope_of(session))
    try:
        result = await run_plan(plan, session=session, timeout_s=6.0,
                                turn_id=getattr(session, "turn_id", ""))
    except Exception as exc:  # noqa: BLE001 — a tap that cannot read says so; it never fails the app
        log.info("a command could not read %s: %s", tool, exc)
        return []
    _remember(needs, ref, result)
    return list(result.calls)


def _remember(needs: dict, ref: str, result) -> None:
    """Put what the tap just read where a replay will look for it.

    `run_plan` reads and does not keep. Without this a record reached by tapping Next was gone
    a second later: Back onto it missed `replay()` and read Shopify again, and `open.entity`
    refused a record the owner had been looking at moments before with "I no longer have that
    one to hand".
    """
    from app.commands import MEMBER_READ
    from app.memory import ENTITY
    from app.memory import current as memory

    _, _, kind = MEMBER_READ.get(str(needs.get("set_kind") or ""), ("", "", ""))
    body = result.values.get("member") if hasattr(result, "values") else None
    if not kind or not isinstance(body, dict):
        return
    try:
        memory().put(ENTITY, f"{kind}:{ref}", body, source="gmail" if kind == "email_thread" else "shopify",
                     query="command:member", provenance={"command": "member", "ref": ref})
    except Exception as exc:  # noqa: BLE001 — a cold cache is a slower Back, not a fault
        log.debug("could not keep what a tap read: %s", exc)


async def _writes(request: Request) -> dict:
    """What the action rail on a replayed card may offer THIS caller.

    `writes_context` is the same function /turn uses, and using it is the whole point: a card
    redrawn by a tap must offer exactly what the same card offered when it was read, no more.

    This used to build its own dict — `{"enabled": ..., "capabilities": await
    runtime.capabilities()}` — which was wrong twice. Every consumer in app/presentation.py
    reads `writes["allowed"]`, which was absent, so the rail fell back to None. And
    `runtime.capabilities()` is the MAC's table, not this caller's: `writes_context` runs
    `caller_check` first and returns no capabilities at all when the caller may not apply
    changes — no allow-list, a request from the Mac itself with CROOKS_WRITES_LOCAL_OWNER
    false, or an identity Tailscale cannot verify. /command ran none of that, so a tapped card
    carried live chips that /turn deliberately suppresses on the same order, with no code or
    reason on it to say why a tap would fail.
    """
    try:
        return await writes_context(request)
    except Exception as exc:  # noqa: BLE001 — a rail is not worth failing a navigation for
        log.info("could not read the capability table for a command: %s", exc)
        return {}


async def _stage_change(request: Request, runtime, session, branch, staging: dict, outcome):
    """A touch command that proposes a change: PREPARE it, and nothing more.

    This is the same path `POST /actions/row` takes, for the same reason — the tablet named
    an action and a record, and the Mac decides everything else. It resolves the registered
    write tool, checks that a gesture from THIS caller could work at all, and hands the
    arguments to `dispatch`, which is where the gate checks that every id was issued to this
    conversation and the action engine stores the execution the tool prepared from a fresh
    read. The card that comes back is still waiting: nothing here can commit, and the only
    route to a mutation remains `POST /actions/{id}/commit` with a proposal id.

    The refusals are the write boundary's own, in the words the commit route uses, so a tap
    that could not be applied says why here rather than after the owner has held the card.
    """
    from app.routes.actions import _write_status_soon, caller_check
    from app.tools import registry
    from app.tools.dispatch import dispatch

    tool = str(staging.get("tool") or "")
    args = staging.get("args")
    try:
        spec = registry.get(tool)
    except KeyError:
        spec = None
    if spec is None or spec.write is None or not spec.write.complete or not isinstance(args, dict):
        # Fail closed. A command naming a tool this build does not carry, or one with no
        # reviewed write definition, prepares nothing.
        log.warning("a command asked to stage %r, which is not a reviewed write tool", tool)
        return commands.Outcome.refused("unknown_change", "That is not a change this build can prepare.")
    caller, code, detail, spoken_key = caller_check(request)
    if code:
        log.warning(
            "staging refused: %s — %s (login=%s proxied=%s)", code, detail,
            request.headers.get("tailscale-user-login", "") or "-", bool(request.headers.get("x-forwarded-for")),
        )
        return commands.Outcome.refused(spoken_key or code, detail)
    status = await _write_status_soon(runtime, spec.write.operation)
    if not status.ready:
        return commands.Outcome.refused(status.code, status.detail)

    calls: list = []
    await dispatch(tool, dict(args), session=session, timeout_s=runtime.settings.tool_timeout_s, calls=calls)
    proposal_id = next((c.proposal_id for c in calls if getattr(c, "proposal_id", None)), "")
    if not proposal_id:
        why = next((str(c.error) for c in calls if not c.ok and c.error), "That change could not be prepared.")
        timeline.emit("command_stage", session_id=session.session_id, branch_id=getattr(branch, "branch_id", None),
                      tool=tool, ok=False, detail=why[:200])
        return commands.Outcome.refused("not_prepared", why[:200])
    runtime.actions.deliver(proposal_id)
    proposal = runtime.actions.find(proposal_id)
    # The card this one replaces — a draft turned into a send. Withdrawn only now that the
    # replacement exists: doing it first leaves the owner with nothing to tap when the send
    # could not be prepared.
    withdrawn = runtime.actions.revoke_ids([str(x) for x in (staging.get("revoke") or [])], "replaced by " + tool)
    timeline.emit("command_stage", session_id=session.session_id, turn_id=getattr(session, "turn_id", "") or None,
                  branch_id=getattr(branch, "branch_id", None), tool=tool, ok=True, proposal_id=proposal_id,
                  risk=(proposal.risk if proposal is not None else None),
                  interaction=(proposal.interaction if proposal is not None else None),
                  revoked=withdrawn or None)
    return commands.Outcome(
        answer=_staged_words(proposal), calls=calls,
        # `stage` is cleared: it was the instruction to this function, and a tablet that read
        # it back off the payload would be reading the Mac's own working note.
        changed={**outcome.changed, "stage": None, "staged": True, "proposal_id": proposal_id,
                 "operation": spec.write.operation, "revoked": withdrawn,
                 "what": str(staging.get("what") or "")[:80]},
    )


def _staged_words(proposal) -> str:
    """What the tablet says about a change it has just prepared: the tool's own read-back and
    the gesture that would apply it. Both are fixed text from the Mac — the read-back was
    built by the write tool from what it read, and the gesture's words come from the
    interaction grammar. No model is on this path."""
    if proposal is None:
        return "That is prepared and waiting on the card."
    from app.actions.grammar import words_for

    what = str(proposal.summary.get("read_back") or "").strip()
    verb = words_for(proposal.interaction)["verb"]
    lead = f"Ready to {what}" if what else "That is prepared"
    return f"{lead}. Nothing has changed yet; {verb}."
