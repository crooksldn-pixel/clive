"""The composer, and the draft turned into a send (brief §7, §8).

Four scenarios. Each is one of the two bench failures, or something that had to be true for
the fix not to be a new hole:

    compose_open            the exact sentence the bench refused draws an editable email
    compose_dictated        an address a microphone heard is marked, then corrected by finger
    compose_stage           the gesture prepares a change; nothing is executed
    compose_send_instead    the draft becomes a send in one gesture, and its card is withdrawn

The sentence is the model's, like every sentence (since 28 September 2026): the harness's
model opens the composer with `gmail_compose_open`, as Claude does, and what is asserted is
the card the Mac drew from that call and what the owner's taps do to it.

Nothing here reaches Gmail: `experience/fixtures/gmail.py` raises on every write method, so a
scenario that accidentally sent something would fail loudly rather than pass quietly.
"""

from __future__ import annotations

from typing import Any

from experience.fixtures import data
from experience.harness import Harness
from experience.scenarios import Result, a_model_turn, a_surface, check, grounded


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _detail(c) -> str:
    return str(c.raw.get("detail") or "")


def _compose(c) -> dict[str, Any]:
    return c.data("email_compose")


def _field(c, name: str) -> dict[str, Any]:
    got = _compose(c).get(name)
    return got if isinstance(got, dict) else {}


def _opens(to: str, *, subject: str = data.COMPOSE_SUBJECT, body: str = data.COMPOSE_BODY) -> tuple[str, dict[str, Any]]:
    """The composer, opened by the model for the bench sentence: the address as the owner gave
    it, words of its own, and what it is about in his."""
    return ("gmail_compose_open", {"to": to, "subject": subject, "body": body,
                                   "about": "asking if they're free for a shoot next Sunday"})


async def _draft_waiting(h: Harness, session_id: str, r: Result) -> Any:
    """Open the composer with the bench sentence, type the words in, and tap Save draft.

    Every step goes through the same HTTP surface the tablet uses, so the draft this leaves on
    the branch was prepared exactly as production prepares one: the write tool's own handler,
    on the action engine, from the Mac's own copy of the email.
    """
    opened = await h.ask(data.COMPOSE_SENTENCE, _opens(data.COMPOSE_TO, subject="A shoot", body="Are you free?"),
                         session_id=session_id)
    r.captures.append(opened)
    compose_id = str(_compose(opened).get("compose_id") or "")
    r.checks.append(check("the composer opened", bool(compose_id), f"surfaces={opened.surface_types}"))
    if not compose_id:
        return None
    for name, value in (("subject", data.COMPOSE_SUBJECT), ("body", data.COMPOSE_BODY)):
        typed = await h.touch("compose.field", session_id=session_id, compose_id=compose_id,
                              field=name, value=value)
        r.captures.append(typed)
        r.checks.append(check(f"the typed {name} reaches the Mac's own copy",
                              _ok(typed) and _field(typed, name).get("value") == value,
                              f"{name}={_field(typed, name)} code={_code(typed)!r} detail={_detail(typed)!r}"))
    staged = await h.touch("compose.stage", session_id=session_id, compose_id=compose_id, mode="draft")
    r.captures.append(staged)
    r.checks.append(check("Save draft prepares a draft", staged.status == 200 and _ok(staged),
                          f"status={staged.status} code={_code(staged)!r} detail={_detail(staged)!r}"))
    session = h.runtime.sessions.get_or_create(session_id)
    drafts = [p for p in session.proposals if p.operation == "gmail_draft_new"]
    r.checks.append(check("one draft is waiting on this half, and only one",
                          len(drafts) == 1 and drafts[0].status.value == "PENDING",
                          f"proposals={[(p.operation, p.status.value) for p in session.proposals]}"))
    return drafts[0] if drafts else None


async def compose_open(h: Harness) -> Result:
    r = Result("compose_open", "The sentence the bench refused")
    c = await h.ask(data.COMPOSE_SENTENCE, _opens(data.COMPOSE_TO), scenario="compose_open", session_id="cmp1")
    r.captures.append(c)
    r.checks += a_surface(c, "email_compose", what="draws an editable email")
    r.checks.append(a_model_turn(c))
    card = _compose(c)
    to = _field(c, "to")
    r.checks.append(check("addressed to the address in the sentence, and it reads as sound",
                          to.get("value") == data.COMPOSE_TO and to.get("status") == "ok",
                          f"to={to}"))
    r.checks.append(check("a new email, not a reply",
                          card.get("kind") == "new" and not card.get("thread_id"),
                          f"kind={card.get('kind')!r} thread={card.get('thread_id')!r}"))
    about = str(card.get("about") or "").lower()
    r.checks.append(check("says what it is about, in the owner's own words",
                          "shoot" in about and "sunday" in about, f"about={card.get('about')!r}"))
    if grounded(h):
        when = card.get("resolved_when") or {}
        r.checks.append(check("resolves “next Sunday” to the next Sunday, in the shop's zone",
                              isinstance(when, dict) and when.get("date") == data.next_sunday(),
                              f"resolved_when={when} expected={data.next_sunday()}"))
    r.checks.append(check("the words the model wrote are on the card, as fields he can edit",
                          _field(c, "subject").get("value") == data.COMPOSE_SUBJECT
                          and _field(c, "body").get("value") == data.COMPOSE_BODY,
                          f"subject={_field(c, 'subject')} body={_field(c, 'body')}"))
    r.checks.append(check("nothing was prepared and nothing was sent",
                          not [x for x in c.surface_types if x in ("confirmation", "success", "email_draft")]
                          and not h.runtime.sessions.get_or_create("cmp1").proposals,
                          f"surfaces={c.surface_types}"))
    ids = [str(a.get("id") or "") for a in (card.get("actions") or []) if isinstance(a, dict)]
    r.checks.append(check("offers Save draft, Send and Discard, and Send is the red one",
                          ids == ["save_draft", "send", "discard"]
                          and any(a.get("id") == "send" and a.get("risk") == "red" for a in card["actions"]),
                          f"actions={card.get('actions')}"))
    # The Mac keeps the composer, because that copy is what a gesture builds execution from.
    branch = h.branch("cmp1")
    r.checks.append(check("the composer is held on the branch, not on the tablet",
                          isinstance(getattr(branch, "compose", None), dict)
                          and branch.compose.get("to") == data.COMPOSE_TO,
                          f"branch.compose={getattr(branch, 'compose', None)}"))
    return r


async def compose_dictated(h: Harness) -> Result:
    r = Result("compose_dictated", "An address heard rather than typed, then corrected")
    c = await h.ask(data.COMPOSE_DICTATED, _opens("1232 candlestick horse at gmail dot com"),
                    scenario="compose_dictated", session_id="cmp2")
    r.captures.append(c)
    r.checks += a_surface(c, "email_compose", what="draws the email anyway")
    r.checks.append(a_model_turn(c))
    to = _field(c, "to")
    r.checks.append(check("a dictated address is marked uncertain, whatever it normalised to",
                          to.get("status") == "uncertain" and bool(to.get("hint")),
                          f"to={to}"))
    before = _compose(c)
    compose_id = str(before.get("compose_id") or "")
    r.checks.append(check("the card names the composer the Mac holds", bool(compose_id), f"compose_id={compose_id!r}"))

    # An uncertain address cannot be staged. That refusal is the whole reason for the status.
    refused = await h.touch("compose.stage", scenario="compose_dictated", session_id="cmp2",
                            compose_id=compose_id, mode="draft")
    r.captures.append(refused)
    r.checks.append(check("and it refuses to prepare anything until it has been checked",
                          refused.status == 200 and not _ok(refused) and _code(refused) == "not_ready",
                          f"code={_code(refused)!r} detail={_detail(refused)!r}"))

    fixed = await h.touch("compose.field", scenario="compose_dictated", session_id="cmp2",
                          compose_id=compose_id, field="to", value=data.COMPOSE_TO)
    r.captures.append(fixed)
    r.checks.append(check("the typed correction is accepted", fixed.status == 200 and _ok(fixed),
                          f"status={fixed.status} code={_code(fixed)!r} detail={_detail(fixed)!r}"))
    r.checks += a_surface(fixed, "email_compose", what="answers with the same card")
    after_to = _field(fixed, "to")
    r.checks.append(check("a typed address reads as sound",
                          after_to.get("value") == data.COMPOSE_TO and after_to.get("status") == "ok",
                          f"to={after_to}"))
    after = _compose(fixed)
    keys = ("about", "original", "resolved_when")
    r.checks.append(check("and correcting one field changes nothing else about the email",
                          after.get("compose_id") == compose_id
                          and all(after.get(k) == before.get(k) for k in keys),
                          f"before={ {k: before.get(k) for k in keys} } after={ {k: after.get(k) for k in keys} }"))
    sneaky = await h.touch("compose.field", session_id="cmp2", compose_id=compose_id,
                           field="converts", value="prop_deadbeef")
    r.captures.append(sneaky)
    r.checks.append(check("a key of the Mac's own context is not a field the tablet may set",
                          not _ok(sneaky) and _code(sneaky) == "unknown_field",
                          f"code={_code(sneaky)!r} detail={_detail(sneaky)!r}"))
    return r


async def compose_stage(h: Harness) -> Result:
    r = Result("compose_stage", "Save draft, tapped")
    draft = await _draft_waiting(h, "cmp3", r)
    if draft is None:
        return r
    staged = r.captures[-1]
    r.checks += a_surface(staged, "confirmation", what="answers with a card still waiting for a gesture")
    confirmation = staged.data("confirmation")
    r.checks.append(check("it is a draft, and it is only waiting",
                          str(confirmation.get("operation") or "") == "gmail_draft_new"
                          and str(confirmation.get("status") or "pending") in ("pending", "proposed"),
                          f"confirmation={ {k: confirmation.get(k) for k in ('operation', 'status', 'title')} }"))
    facts = {str(f.get("label")): str(f.get("value")) for f in (confirmation.get("facts") or []) if isinstance(f, dict)}
    r.checks.append(check("the card says the address, and that it is nobody the shop knows",
                          data.COMPOSE_TO in facts.get("To", "")
                          and "not a Shopify customer" in facts.get("Recipient", ""),
                          f"facts={facts}"))
    r.checks.append(check("the change was built from the Mac's copy of the email, not from the tap",
                          draft.execution.get("to") == data.COMPOSE_TO
                          and draft.execution.get("subject") == data.COMPOSE_SUBJECT
                          and data.COMPOSE_BODY in str(draft.execution.get("body") or ""),
                          f"execution={ {k: draft.execution.get(k) for k in ('to', 'subject')} }"))
    r.checks.append(check("a draft is the lighter gesture; it is not held like a send",
                          draft.risk == "AMBER" and draft.interaction == "tap_commit",
                          f"risk={draft.risk} gesture={draft.interaction}"))
    r.checks.append(check("nothing was executed: the fixture inbox was never asked to save anything",
                          draft.executed_at is None and draft.status.value == "PENDING",
                          f"status={draft.status.value} executed_at={draft.executed_at}"))
    return r


async def compose_send_instead(h: Harness) -> Result:
    r = Result("compose_send_instead", "“Send it instead”, as one gesture")
    draft = await _draft_waiting(h, "cmp4", r)
    if draft is None:
        return r
    body_sent = str(draft.execution.get("body") or "")
    session = h.runtime.sessions.get_or_create("cmp4")

    converted = await h.touch("draft.send_instead", scenario="compose_send_instead", session_id="cmp4")
    r.captures.append(converted)
    r.checks.append(check("the tap prepares the send", converted.status == 200 and _ok(converted),
                          f"status={converted.status} code={_code(converted)!r} detail={_detail(converted)!r}"))
    r.checks += a_surface(converted, "confirmation", what="answers with the send, waiting for its gesture")
    sends = [p for p in session.proposals if p.operation.startswith("gmail_send_")]
    r.checks.append(check("one send is staged, carrying exactly the draft's own words",
                          len(sends) == 1 and str(sends[0].execution.get("body") or "") == body_sent,
                          f"sends={[(p.operation, p.status.value) for p in sends]}"))
    r.checks.append(check("to the draft's own recipient, which the Mac had already decided",
                          bool(sends) and sends[0].execution.get("to") == draft.execution.get("to"),
                          f"send_to={sends[0].execution.get('to') if sends else None} draft_to={draft.execution.get('to')}"))
    r.checks.append(check("held to the graver gesture, because a send cannot be unsent",
                          bool(sends) and sends[0].risk == "RED" and sends[0].interaction == "hold_to_arm",
                          f"risk={sends[0].risk if sends else None} gesture={sends[0].interaction if sends else None}"))
    r.checks.append(check("and the draft is withdrawn, so one email is not two cards",
                          draft.status.value == "REVOKED", f"draft={draft.status.value}"))
    r.checks.append(check("nothing was executed by any of it",
                          all(p.executed_at is None for p in session.proposals),
                          f"executed={[p.operation for p in session.proposals if p.executed_at is not None]}"))
    # And again, because one email going twice is the failure a send has no undo for.
    again = await h.touch("draft.send_instead", scenario="compose_send_instead", session_id="cmp4")
    r.captures.append(again)
    r.checks.append(check("asking twice is refused in words, not answered with a second send",
                          not _ok(again) and _code(again) == "already_ready"
                          and len([p for p in session.proposals if p.operation.startswith("gmail_send_")]) == 1,
                          f"code={_code(again)!r} sends={[(p.operation, p.status.value) for p in session.proposals if p.operation.startswith('gmail_send_')]}"))
    return r


SCENARIOS = (
    ("compose_open", compose_open),
    ("compose_dictated", compose_dictated),
    ("compose_stage", compose_stage),
    ("compose_send_instead", compose_send_instead),
)
