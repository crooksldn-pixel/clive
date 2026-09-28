"""Making a discount code (brief §12), driven the way the tablet drives it.

Two things this pack is for, and neither of them is the mechanics — those are unit tests
(tests/test_discounts.py). What a scenario can prove that a unit test cannot is what the
OWNER meets: that a code he might reasonably pick is checked against the shop before he is
asked to authorise anything, that the card in front of him says what the code will do in
words rather than in a payload, and that the whole path from an empty form to a waiting
card costs no language model at all.

"Set up a code" said out loud goes to Claude like every sentence, and nothing is prepared on
the way to it. `discount_sentence_defers` scripts what Claude then does — opens the form and
asks for the code — and holds the result to the same boundary a tap meets: a card waiting for
the owner's gesture, and nothing created.
"""

from __future__ import annotations

import re

from experience.fixtures import data
from experience.harness import Harness
from experience.scenarios import Result, a_model_turn, a_surface, check, deterministic, grounded

FREE = data.DISCOUNT_FREE_CODE          # AUTUMN20 — nothing in the golden world uses it
TAKEN = "SUMMER15"                      # the Summer sale, still running
TAKEN_TITLE = data.DISCOUNTS[TAKEN]["title"]


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _detail(c) -> str:
    return str(c.raw.get("detail") or "")


def _workspace(c) -> dict:
    return c.data("workspace")


def _fields(c) -> dict[str, dict]:
    return {str(f.get("name")): f for f in (_workspace(c).get("fields") or [])}


def _facts(c) -> dict[str, str]:
    return {str(f.get("label")): str(f.get("value")) for f in (_workspace(c).get("facts") or [])}


def _card_facts(c) -> dict[str, str]:
    return {str(f.get("label")): str(f.get("value")) for f in (c.data("confirmation").get("facts") or [])}


def _amount(value) -> float | None:
    found = re.search(r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)", str(value or ""))
    return float(found.group(1).replace(",", "")) if found else None


async def _open(h: Harness, session: str, scenario: str):
    """The form, from a fresh tablet, the way the tablet gets there.

    The dock landing first, and not for decoration: `POST /command` will only START a
    conversation for `open.area` (app/routes/command.py FRESH_START), because a tap about a
    record the tablet claims to have has nothing to be about when the conversation is gone.
    So a discount form is reached from somewhere, as it is in the shop — the dock, then the
    control — and a scenario that skipped the first tap would be testing a route the tablet
    cannot take.
    """
    await h.touch("open.area", scenario=scenario, session_id=session, area="orders")
    return await h.touch("discount.open", scenario=scenario, session_id=session)


async def discount_new_code(h: Harness) -> Result:
    """The whole path: an empty form, a code typed, the shop asked, the priced card, nothing
    created."""
    r = Result("discount_new_code", "Set up a code for 20% off")
    session = "disc1"
    h.configure()

    c = await _open(h, session, "discount_new_code")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "workspace", what="draws the form")
    r.checks.append(deterministic(c))
    r.checks.append(check("it is empty and says what it needs",
                          _fields(c).get("code", {}).get("value") == ""
                          and "needs a code" in str(_workspace(c).get("blocked") or ""),
                          f"code={_fields(c).get('code')} blocked={_workspace(c).get('blocked')!r}"))
    r.checks.append(check("and nothing can be prepared from it yet",
                          all(a.get("enabled") is False for a in (_workspace(c).get("actions") or []) if a.get("risk") == "red"),
                          f"actions={_workspace(c).get('actions')}"))
    workspace_id = str(_workspace(c).get("workspace_id") or "")
    r.checks.append(check("the form has an id of its own", workspace_id.startswith("dsc_"), f"id={workspace_id!r}"))

    # The code, typed. This is the read that matters: is it taken?
    d = await h.touch("discount.field", scenario="discount_new_code", session_id=session,
                      workspace_id=workspace_id, field="code", value=FREE.lower())
    r.captures.append(d)
    r.checks += a_surface(d, "workspace", what="redraws the form")
    r.checks.append(deterministic(d))
    r.checks.append(check("the Mac normalised what was typed", _fields(d).get("code", {}).get("value") == FREE,
                          f"code={_fields(d).get('code')}"))
    r.checks.append(check("and it read the shop for it", f"free — nothing in the shop uses {FREE}" in _facts(d).get("That code", ""),
                          f"facts={_facts(d)}"))
    r.checks.append(check("the answer says so in words", FREE in d.answer and "Nothing is created" in d.answer, d.answer[:160]))

    # What it takes off.
    e = await h.touch("discount.field", scenario="discount_new_code", session_id=session,
                      workspace_id=workspace_id, field="value", value="20")
    r.captures.append(e)
    r.checks.append(check("the value is accepted", _fields(e).get("value", {}).get("status") == "ok",
                          f"value={_fields(e).get('value')}"))
    r.checks.append(check("and the form is now ready", not str(_workspace(e).get("blocked") or ""),
                          f"blocked={_workspace(e).get('blocked')!r}"))
    if grounded(h):
        r.checks.append(check("the form says what the code would take off", _facts(e).get("Takes off") == "20%",
                              f"facts={_facts(e)}"))

    # The gesture that asks the Mac to prepare it: one id, and nothing else.
    f = await h.touch("discount.stage", scenario="discount_new_code", session_id=session, workspace_id=workspace_id)
    r.captures.append(f)
    r.checks.append(check("the Mac prepares it", f.status == 200 and _ok(f), f"status={f.status} code={_code(f)!r} detail={_detail(f)!r}"))
    r.checks += a_surface(f, "confirmation", what="draws the card that has to be authorised")
    card = f.data("confirmation")
    r.checks.append(check("it is this change, waiting, at the graver tier",
                          card.get("operation") == "discount_code_create" and card.get("status") == "pending"
                          and card.get("risk") == "red",
                          f"operation={card.get('operation')!r} status={card.get('status')!r} risk={card.get('risk')!r}"))
    r.checks.append(check("a spoken yes cannot apply it: the gesture is a hold",
                          (card.get("interaction") or {}).get("kind") == "hold_to_arm",
                          f"interaction={(card.get('interaction') or {}).get('kind')!r}"))
    r.checks.append(check("and it says it cannot be undone from here",
                          "cannot be undone" in str(card.get("detail") or "").lower() and card.get("reversible") is False,
                          f"detail={card.get('detail')!r} reversible={card.get('reversible')}"))
    facts = _card_facts(f)
    r.checks.append(check("the card names the code and what it does",
                          facts.get("Code") == FREE and _amount(facts.get("Takes off")) == 20.0,
                          f"code={facts.get('Code')!r} takes={facts.get('Takes off')!r}"))
    r.checks.append(check("it says what the code applies to and what it stacks with",
                          facts.get("Applies to") == "everything in the shop" and facts.get("Combines with") == "nothing else",
                          f"applies={facts.get('Applies to')!r} combines={facts.get('Combines with')!r}"))
    r.checks.append(check("and that the code was free when it was prepared",
                          FREE in facts.get("That code now", ""), f"collision={facts.get('That code now')!r}"))

    # Nothing has been created. The fixture refuses `discount_code_create` outright, so a
    # prepare that tried to create would have failed here rather than passing quietly.
    r.checks.append(check("no mutation was sent, of any kind",
                          getattr(h.store, "mutations_sent", -1) == 0 and not getattr(h.store, "calculations", []),
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    g = await h.touch("discount.field", scenario="discount_new_code", session_id=session,
                      workspace_id=workspace_id, field="code", value=FREE)
    r.captures.append(g)
    r.checks.append(check("and the shop still does not have that code",
                          f"free — nothing in the shop uses {FREE}" in _facts(g).get("That code", ""),
                          f"facts={_facts(g)}"))
    return r


async def discount_code_taken(h: Harness) -> Result:
    """A code the shop already uses. Named, on the card, before anything is prepared — which
    is the difference between an answer and a refusal from Shopify after the owner has held
    a card."""
    r = Result("discount_code_taken", "Set up a code that is already in use")
    session = "disc2"
    h.configure()
    c = await _open(h, session, "discount_code_taken")
    workspace_id = str(_workspace(c).get("workspace_id") or "")
    d = await h.touch("discount.field", scenario="discount_code_taken", session_id=session,
                      workspace_id=workspace_id, field="code", value=TAKEN)
    r.captures.append(d)
    r.checks += a_surface(d, "workspace", what="redraws the form")
    r.checks.append(deterministic(d))
    r.checks.append(check("the form says the code is taken, and by what",
                          TAKEN_TITLE in str(_workspace(d).get("blocked") or ""),
                          f"blocked={_workspace(d).get('blocked')!r}"))
    r.checks.append(check("the fact is marked as bad rather than merely present",
                          any(f.get("label") == "That code" and f.get("tone") == "bad"
                              for f in (_workspace(d).get("facts") or [])),
                          f"facts={_workspace(d).get('facts')}"))
    r.checks.append(check("the answer says so out loud", TAKEN in d.answer and "already in use" in d.answer, d.answer[:160]))
    r.checks.append(check("and the button that would prepare it is off",
                          all(a.get("enabled") is False for a in (_workspace(d).get("actions") or []) if a.get("risk") == "red"),
                          f"actions={_workspace(d).get('actions')}"))

    # And the Mac refuses the gesture too, so the greyed button is not the only thing
    # holding the line.
    e = await h.touch("discount.stage", scenario="discount_code_taken", session_id=session, workspace_id=workspace_id)
    r.captures.append(e)
    r.checks.append(check("the gesture is refused, not attempted",
                          e.status == 200 and not _ok(e) and _code(e) == "not_ready",
                          f"status={e.status} code={_code(e)!r}"))
    r.checks.append(check("and the refusal says why, in words",
                          TAKEN in _detail(e) and "already in use" in _detail(e), f"detail={_detail(e)!r}"))
    r.checks.append(check("no card was drawn and nothing is waiting",
                          e.surface("confirmation") is None
                          and not [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"],
                          f"surfaces={e.surface_types}"))
    r.checks.append(check("and nothing was sent to the shop", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


async def discount_sentence_defers(h: Harness) -> Result:
    """The spoken form: the model's, and the model's own attempt at the change is held to the
    same boundary as a tap (the 2026-09-28 deploy review, round 9, H-03).

    Scripted: the harness's model opens the form with the code and the percentage it heard and
    then asks for the code to be created, as Claude would. What is asserted is the Mac's side —
    the form is drawn from a read, the create is PREPARED as a card waiting for the owner's
    gesture, nothing reaches the shop, and the answer does not say a code exists. Before round
    10 this sent the sentence to a model that called nothing, so none of that could fail.
    """
    from app.observability import contract

    r = Result("discount_sentence_defers", "“Set up a code for 20% off”, spoken")
    session = "disc3"
    h.configure()

    def _made(calls):
        return {"workspace_id": next((str((c.result or {}).get("workspace_id") or "") for c in calls
                                      if c.name == "shopify_discount_open" and isinstance(c.result, dict)), "")}

    c = await h.ask(f"set up a discount code {FREE} for 20 per cent off",
                    ("shopify_discount_open", {"code": FREE, "percent": 20}),
                    ("shopify_discount_create", _made),
                    reply=f"{FREE} is ready on the card — hold it to create the code.",
                    scenario="discount_sentence_defers", session_id=session)
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    r.checks += a_surface(c, "confirmation", what="the model's create comes back as a card to authorise")
    card = c.data("confirmation")
    r.checks.append(check("it is waiting for the owner's gesture, and a spoken yes cannot apply it",
                          card.get("status") == "pending" and (card.get("interaction") or {}).get("kind") not in (None, "", "none"),
                          f"status={card.get('status')!r} interaction={(card.get('interaction') or {}).get('kind')!r}"))
    pending = [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"]
    r.checks.append(check("exactly the code that was said is prepared, and nothing is created",
                          len(pending) == 1 and pending[0].executed_at is None
                          and FREE in str(pending[0].summary) and getattr(h.store, "mutations_sent", -1) == 0,
                          f"pending={[(p.operation, p.status.value) for p in pending]} "
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    r.checks.append(check("and the answer does not say the code exists (the report's own FALSE_SUCCESS rule)",
                          not contract.reports_success(c.answer), f"answer={c.answer[:120]!r}"))
    return r


SCENARIOS = (
    ("discount_new_code", discount_new_code),
    ("discount_code_taken", discount_code_taken),
    ("discount_sentence_defers", discount_sentence_defers),
)
