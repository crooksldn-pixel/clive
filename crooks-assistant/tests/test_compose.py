"""The composer: an email to any address, and a draft corrected into a send.

The two things these hold, because everything else in the family follows from them:

* An arbitrary recipient does not weaken the write boundary. `to` is admitted only with the
  `compose_id` of a composer this conversation was handed; the gate refuses it without one; a
  reply's recipient is still read from the thread; a dictated address cannot be staged at all
  until a finger has corrected it; and the arguments that reach Gmail are built on the Mac
  from the Mac's own copy of the email, never from what the tablet posted.
* Said out loud, every one of these is a model turn: the model opens the composer with
  `gmail_compose_open` and fills it with `gmail_compose_fill` (the word-matching lane that
  used to open it was removed on 28 September 2026).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.actions.models import ActionStatus
from app.families import compose as family
from app.session.branch import Branch
from app.session.models import Session
from app.tools import registry
from app.tools.gate import Disposition, Tier, classify

WEB = Path(__file__).resolve().parents[1] / "web"
ADDRESS = "4417lighthousepony@example.com"
BENCH = (
    "Write an email to a model asking if they're free for a shoot next Sunday. "
    f"Their email is {ADDRESS}. Don't send it yet."
)
DICTATED = (
    "Write an email to a model asking if they're free for a shoot next Sunday. "
    "Their email is 4417 lighthouse pony at example dot com. Don't send it yet."
)


@pytest.fixture
def branch() -> Branch:
    return Branch(branch_id="br_compose", session_id="s1")


@pytest.fixture
def session() -> Session:
    return Session(session_id="s1")


# --------------------------------------------------------------------------- the address


@pytest.mark.parametrize(("said", "value", "status"), [
    (ADDRESS, ADDRESS, "ok"),
    ("  Sam@CrooksLDN.com ", "sam@crooksldn.com", "ok"),
    ("their email is 4417 lighthouse pony at example dot com", ADDRESS, "uncertain"),
    ("sam at crooksldn dot co dot uk", "sam@crooksldn.co.uk", "uncertain"),
    ("send it to sam at crooksldn dot com", "sam@crooksldn.com", "uncertain"),
    ("4417lighthousepony at example", "4417lighthousepony@example", "invalid"),
    ("just a name", "just a name", "invalid"),
    ("", "", "invalid"),
])
def test_an_address_is_read_and_its_soundness_is_said(said, value, status):
    got_value, got_status, hint = family.check_address(said)
    assert (got_value, got_status) == (value, status)
    assert bool(hint) == (status != "ok"), "anything but ok has to say why"


def test_a_dictated_address_is_never_treated_as_typed():
    """The whole reason `uncertain` exists: "light house" and "lighthouse" are both valid
    addresses and only the owner knows which was meant."""
    clean, status, _ = family.check_address("light house pony at example dot com")
    assert status == "uncertain" and family.EMAIL_ADDRESS.match(clean), clean
    assert family.check_address(clean)[1] == "ok", "typed, the same characters are sound"


def test_an_address_that_is_not_one_cannot_reach_the_write_tool():
    from app.tools.gmail_writes import EMAIL_ADDRESS

    for bad in ("sam@", "@gmail.com", "sam@gmail", "sam gmail.com", "a@b.c d@e.f", "sam@-b.com", "sam@b..com"):
        assert not EMAIL_ADDRESS.match(bad), bad
    for good in (ADDRESS, "sam.o'neill@crooksldn.co.uk", "a+b@c-d.io"):
        assert EMAIL_ADDRESS.match(good), good


# --------------------------------------------------------------------------- the date


@pytest.mark.parametrize(("said", "on", "expected"), [
    ("free for a shoot next Sunday", date(2026, 9, 10), "2026-09-13"),   # a Thursday
    ("free on Sunday", date(2026, 9, 10), "2026-09-13"),
    ("next Sunday", date(2026, 9, 13), "2026-09-20"),                    # said ON a Sunday
    ("tomorrow", date(2026, 9, 10), "2026-09-11"),
    ("today", date(2026, 9, 10), "2026-09-10"),
    ("next week", date(2026, 9, 10), "2026-09-17"),
    ("on Friday", date(2026, 9, 10), "2026-09-11"),
    ("this weekend", date(2026, 9, 10), "2026-09-12"),                   # the coming Saturday
])
def test_a_relative_date_becomes_one_date_in_the_shops_own_zone(said, on, expected):
    now = datetime(on.year, on.month, on.day, 14, 30, tzinfo=ZoneInfo("Europe/London"))
    assert family.resolve_when(said, now=now)["date"] == expected


def test_a_sentence_with_no_date_in_it_invents_none():
    assert family.resolve_when("write to sam about the fabric") == {}


def test_the_date_is_the_shops_day_not_utcs():
    """Half past eleven at night in London in July is already tomorrow in UTC. A date
    resolved in UTC is then a day out — a bug that passes all day and fails at night."""
    late = datetime(2026, 7, 2, 23, 30, tzinfo=ZoneInfo("Europe/London"))   # a Thursday
    assert family.resolve_when("tomorrow", now=late)["date"] == "2026-07-03"


# --------------------------------------------------------------------------- the composer


def test_the_composer_summary_on_the_branch_is_bounded(branch, session):
    secret = "PLEASE-DO-NOT-CARRY-THE-BODY"
    family.open_compose(branch, kind="new", to=ADDRESS, subject="s", body=secret, about=secret)
    summary = branch.public()["compose"]
    assert set(summary) == {"compose_id", "kind", "to", "subject", "thread_id"}
    assert summary["to"] == ADDRESS
    # A branch summary goes out with every reply. The words of an unsent email do not.
    assert secret not in str(summary)
    branch.compose = None
    assert branch.public()["compose"] is None


def test_a_composer_goes_stale_rather_than_being_sent_tomorrow(branch):
    compose_id = family.open_compose(branch, to=ADDRESS, subject="s", body="b")
    assert family.held(branch, compose_id) is not None
    assert family.held(branch, "cmp_someone_elses") is None, "another half's id must not match"
    branch.compose["at"] -= family.COMPOSE_TTL_S + 1
    assert family.held(branch, compose_id) is None and branch.compose is None


# --------------------------------------------------------------------------- typing into it


def _ctx(runtime, session, branch, **args):
    from app.commands import Ctx

    return Ctx(runtime, session, branch, args)


def test_a_typed_value_is_validated_into_the_macs_copy_and_nowhere_else(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, to="", subject="", body="")
    out = commands.run("compose.field", _ctx(None, session, branch, compose_id=compose_id,
                                             field="to", value="4417 lighthouse pony at example dot com"))
    assert out.ok and out.changed["status"] == "uncertain"
    assert branch.compose["to"] == ADDRESS
    assert out.surfaces[0].as_ui()["data"]["to"]["status"] == "uncertain"
    out = commands.run("compose.field", _ctx(None, session, branch, compose_id=compose_id,
                                             field="to", value=ADDRESS))
    assert out.ok and out.changed["status"] == "ok" and branch.compose["to_status"] == "ok"


def test_the_tablet_cannot_name_a_key_of_the_macs_own_context(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, to=ADDRESS, subject="s", body="b")
    for field in ("converts", "at", "thread_id", "to_status", "compose_id", ""):
        out = commands.run("compose.field", _ctx(None, session, branch, compose_id=compose_id,
                                                 field=field, value="x"))
        assert not out.ok and out.code == "unknown_field", field
    assert branch.compose["thread_id"] == "" and branch.compose["converts"] == ""


def test_a_typed_value_is_bounded(branch, session):
    from app import commands
    from app.tools.gmail_writes import MAX_BODY_CHARS, MAX_SUBJECT_CHARS

    compose_id = family.open_compose(branch, to=ADDRESS, subject="s", body="b")
    commands.run("compose.field", _ctx(None, session, branch, compose_id=compose_id,
                                       field="subject", value="x" * (MAX_SUBJECT_CHARS + 500)))
    commands.run("compose.field", _ctx(None, session, branch, compose_id=compose_id,
                                       field="body", value="y" * (MAX_BODY_CHARS + 5000)))
    assert len(branch.compose["subject"]) == MAX_SUBJECT_CHARS
    assert len(branch.compose["body"]) == MAX_BODY_CHARS


def test_typing_into_a_composer_that_is_not_there_is_refused(branch, session):
    from app import commands

    out = commands.run("compose.field", _ctx(None, session, branch, compose_id="cmp_nothing",
                                             field="to", value=ADDRESS))
    assert not out.ok and out.code == "no_composer"


# --------------------------------------------------------------------------- the gesture


def test_the_gesture_names_the_tool_and_the_macs_own_arguments(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, to=ADDRESS, subject="Free on Sunday?", body="Hello.")
    out = commands.run("compose.stage", _ctx(None, session, branch, compose_id=compose_id, mode="draft"))
    assert out.ok
    staged = out.changed["stage"]
    assert staged["tool"] == "gmail_draft_new"
    assert staged["args"] == {"compose_id": compose_id, "to": ADDRESS, "to_name": "",
                              "subject": "Free on Sunday?", "body": "Hello."}
    assert not out.calls, "the command itself must not prepare anything"
    send = commands.run("compose.stage", _ctx(None, session, branch, compose_id=compose_id, mode="send"))
    assert send.changed["stage"]["tool"] == "gmail_send_new"


def test_a_reply_never_carries_its_own_recipient(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, kind="reply", to="mia@example.com",
                                     subject="Re: 1938", body="On its way.", thread_id="aa70d3f83dbef06e")
    out = commands.run("compose.stage", _ctx(None, session, branch, compose_id=compose_id, mode="send"))
    staged = out.changed["stage"]
    assert staged["tool"] == "gmail_send_reply"
    assert staged["args"] == {"thread_id": "aa70d3f83dbef06e", "body": "On its way."}
    assert "to" not in staged["args"], "a reply's recipient is read from the thread, always"


@pytest.mark.parametrize(("to", "to_status", "subject", "body", "code"), [
    (ADDRESS, "uncertain", "s", "b", "not_ready"),
    ("", "invalid", "s", "b", "not_ready"),
    (ADDRESS, "ok", "", "b", "not_ready"),
    (ADDRESS, "ok", "s", "", "not_ready"),
])
def test_a_half_written_email_cannot_be_prepared(branch, session, to, to_status, subject, body, code):
    from app import commands

    compose_id = family.open_compose(branch, to=to, subject=subject, body=body)
    branch.compose["to_status"] = to_status
    out = commands.run("compose.stage", _ctx(None, session, branch, compose_id=compose_id, mode="draft"))
    assert not out.ok and out.code == code, out
    assert "stage" not in out.changed


def test_an_unknown_mode_is_refused_rather_than_guessed(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, to=ADDRESS, subject="s", body="b")
    out = commands.run("compose.stage", _ctx(None, session, branch, compose_id=compose_id, mode="post"))
    assert not out.ok and out.code == "unknown_mode"


def test_discarding_leaves_nothing_behind(branch, session):
    from app import commands

    compose_id = family.open_compose(branch, to=ADDRESS, subject="s", body="b")
    out = commands.run("compose.discard", _ctx(None, session, branch, compose_id=compose_id))
    assert out.ok and branch.compose is None
    assert not commands.run("compose.discard", _ctx(None, session, branch, compose_id=compose_id)).ok


# --------------------------------------------------------------------------- the gate


def test_an_arbitrary_address_needs_a_composer_the_gate_has_seen():
    """The permission story for the recipient, in four lines. An address is not a
    well-formed id, so it could never carry this check itself; the compose id can."""
    args = {"to": ADDRESS, "subject": "s", "body": "b"}
    assert classify("gmail_draft_new", args).disposition is Disposition.DENY
    assert "compose_id" in classify("gmail_draft_new", args).reason
    with_id = {**args, "compose_id": "cmp_abcdef0123"}
    assert classify("gmail_draft_new", with_id).disposition is Disposition.DENY, "an id nobody was issued"
    assert classify("gmail_draft_new", with_id, issued_ids={"cmp_abcdef0123"}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("gmail_send_new", with_id, issued_ids={"cmp_abcdef0123"}).disposition is Disposition.STAGE_FOR_OWNER


def test_a_reply_still_refuses_a_recipient_argument():
    for name in ("gmail_draft_reply", "gmail_send_reply"):
        spec = registry.get(name)
        assert "to" not in spec.input_schema["properties"], name
        assert classify(name, {"thread_id": "aa70d3f83dbef06e", "body": "x", "to": ADDRESS},
                        issued_ids={"aa70d3f83dbef06e"}).disposition is Disposition.DENY


def test_no_email_tool_takes_a_copy_header():
    for name in ("gmail_draft_new", "gmail_send_new", "gmail_draft_reply", "gmail_send_reply"):
        properties = registry.get(name).input_schema["properties"]
        assert "cc" not in properties and "bcc" not in properties, name


def test_the_composers_own_tools_are_reads_and_are_declared_so():
    for name in ("gmail_compose_open", "gmail_compose_fill"):
        spec = registry.get(name)
        assert spec.tier is Tier.GREEN and spec.write is None and spec.batch is None, name
        assert "stages nothing" in spec.description.lower() or "nothing is saved or sent" in spec.description.lower(), name
    # And a read of theirs cannot be reached with an id this conversation was never given.
    assert classify("gmail_compose_fill", {"compose_id": "cmp_x0123456", "subject": "s", "body": "b"}).disposition is Disposition.DENY


# --------------------------------------------------------------------------- draft → send


class _Actions:
    """Just enough of the engine for `draft.discard`: what it withdrew, by id."""

    def __init__(self) -> None:
        self.revoked: list[str] = []

    def revoke_ids(self, ids, reason):
        self.revoked += list(ids)
        return len(ids)


class _Runtime:
    def __init__(self) -> None:
        self.actions = _Actions()


def _draft(session, branch, *, operation="gmail_draft_new", entity_ref="cmp_abcdef0123",
           status=ActionStatus.PENDING, thread_id="", to=ADDRESS, body="Hello.", age=0.0):
    from types import MappingProxyType

    from app.actions.models import ActionProposal

    proposal = ActionProposal(
        proposal_id=f"prop_{len(session.proposals):04d}", session_id=session.session_id, epoch=1,
        tool_name=operation, operation=operation, risk="AMBER", model_args=MappingProxyType({}),
        execution=MappingProxyType({"thread_id": thread_id, "to": to, "to_name": "",
                                    "subject": "Free on Sunday?", "body": body}),
        entity_kind="email", entity_ref=entity_ref, entity_label="new email",
        interaction="tap_commit", reversible=True, before={}, expected_after={}, summary={},
        fingerprint="f", created_at=family._now() - age, expires_at=family._now() + 60,
        status=status, branch_id=branch.branch_id,
    )
    session.proposals.append(proposal)
    return proposal


def test_send_instead_stages_the_draft_that_was_prepared(branch, session):
    from app import commands

    draft = _draft(session, branch)
    out = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch))
    assert out.ok
    staged = out.changed["stage"]
    assert staged["tool"] == "gmail_send_new"
    assert staged["args"]["body"] == draft.execution["body"], "the same words, exactly"
    assert staged["args"]["to"] == ADDRESS and staged["args"]["compose_id"] == "cmp_abcdef0123"
    assert staged["revoke"] == [draft.proposal_id], "the draft's own card goes with it"


def test_send_instead_finds_the_identity_the_mac_recorded(branch, session):
    from app import commands

    _draft(session, branch, entity_ref="gid://shopify/Order/1938")
    args = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch)).changed["stage"]["args"]
    assert args["order_id"] == "gid://shopify/Order/1938" and "to" not in args
    session.proposals.clear()
    _draft(session, branch, entity_ref="gid://shopify/Customer/7001")
    args = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch)).changed["stage"]["args"]
    assert args["customer_id"] == "gid://shopify/Customer/7001" and "to" not in args


def test_a_reply_draft_becomes_a_reply_send(branch, session):
    from app import commands

    _draft(session, branch, operation="gmail_draft_reply", entity_ref="aa70d3f83dbef06e",
           thread_id="aa70d3f83dbef06e")
    staged = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch)).changed["stage"]
    assert staged["tool"] == "gmail_send_reply"
    assert staged["args"] == {"thread_id": "aa70d3f83dbef06e", "body": "Hello."}


def test_a_draft_withdrawn_by_the_very_sentence_converting_it_is_still_findable(branch, session):
    """`POST /turn` advances the epoch and withdraws this half's pending cards BEFORE the fast
    lane runs, so the draft the owner is looking at is REVOKED by the words "send it
    instead". If this stops holding, the bench sentence stops working and nothing else fails."""
    from app import commands

    _draft(session, branch, status=ActionStatus.REVOKED)
    assert commands.run("draft.send_instead", _ctx(_Runtime(), session, branch)).ok


def test_a_draft_from_ten_minutes_ago_is_not_what_it_means(branch, session):
    from app import commands

    _draft(session, branch, age=family.CONVERT_WINDOW_S + 5)
    out = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch))
    assert not out.ok and out.code == "no_draft"


def test_another_halfs_draft_is_not_this_halfs_to_send(branch, session):
    from app import commands

    other = Branch(branch_id="br_other", session_id="s1")
    _draft(session, other)
    out = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch))
    assert not out.ok and out.code == "no_draft"


def test_asking_twice_is_refused_rather_than_sending_twice(branch, session):
    from app import commands

    _draft(session, branch)
    _draft(session, branch, operation="gmail_send_new", status=ActionStatus.PENDING)
    out = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch))
    assert not out.ok and out.code == "already_ready"


def test_with_no_draft_it_says_so_in_words(branch, session):
    from app import commands

    out = commands.run("draft.send_instead", _ctx(_Runtime(), session, branch))
    assert not out.ok and out.code == "no_draft" and "say what the email should say" in out.detail.lower()


def test_forgetting_the_draft_withdraws_its_card(branch, session):
    from app import commands

    draft = _draft(session, branch)
    runtime = _Runtime()
    out = commands.run("draft.discard", _ctx(runtime, session, branch))
    assert out.ok and runtime.actions.revoked == [draft.proposal_id]


# --------------------------------------------------------------------------- the card


def test_the_card_says_the_address_is_nobody_the_shop_knows():
    from app.tools.gmail_writes import _prepared_email, _present_email

    prepared = _prepared_email(
        execution={"thread_id": "", "token": "<t@x>", "raw": "", "to": ADDRESS, "to_name": "",
                   "subject": "Free on Sunday?", "body": "Hello.", "state": "draft"},
        before={}, expected_after={}, entity_ref="cmp_abcdef0123", ctx=None,
        customer={"name": "", "email": ADDRESS, "label": "", "off_shopify": True},
        sending=False, title="Save a draft", sender="orders@crooksldn.example", kind="draft_new",
    )
    facts = {f["label"]: f["value"] for f in _present_email(_AsProposal(prepared))["facts"]}
    assert facts["To"] == ADDRESS
    assert "not a Shopify customer" in facts["Recipient"]
    assert "Order" not in facts, "there is no order and the card must not imply one"
    assert prepared.entity_label == "new email"
    # The ledger must not claim the address was checked against anything.
    assert prepared.summary["ledger"]["to_checked"] is False


def test_an_orders_own_card_is_unchanged_by_all_of_this():
    from app.tools.gmail_writes import _prepared_email, _present_email

    prepared = _prepared_email(
        execution={"thread_id": "", "token": "<t@x>", "raw": "", "to": "mia@example.com",
                   "to_name": "Mia Jones", "subject": "Your order", "body": "Hello.", "state": "draft"},
        before={}, expected_after={}, entity_ref="gid://shopify/Order/1938", ctx=None,
        customer={"name": "Mia Jones", "email": "mia@example.com", "label": "#1938"},
        sending=False, title="Save a draft", sender="orders@crooksldn.example", kind="draft_new",
    )
    facts = {f["label"]: f["value"] for f in _present_email(_AsProposal(prepared))["facts"]}
    assert facts["Order"] == "#1938 · the customer on the order"
    assert "Recipient" not in facts
    assert prepared.summary["ledger"]["to_checked"] is True


class _AsProposal:
    """A prepared change in the shape `present()` reads it: the summary and no undo."""

    def __init__(self, prepared) -> None:
        self.summary = prepared.summary
        self.undo_of = None


def test_the_composers_card_is_in_both_vocabularies():
    from app.presentation import UI_TYPES
    from app.surfaces import SURFACE_TYPES

    assert "email_compose" in UI_TYPES and "email_compose" in SURFACE_TYPES
    assert "email_compose: renderEmailCompose" in (WEB / "ui.js").read_text(encoding="utf-8")


def test_the_field_is_at_least_44px_and_says_its_status_in_more_than_colour():
    """The Phase 2 audit's measured floor, and the glass pass's rule that a state is never
    carried by hue alone. Both are in the stylesheet, so both are asserted there."""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.field-input\{[^}]*min-height:44px", css), "the field lost its tap target"
    for status in ("ok", "uncertain", "invalid"):
        assert f".field.is-{status} .field-input{{" in css, status
    assert ".field.is-uncertain .field-hint{" in css and ".field.is-invalid .field-hint{" in css


def test_the_page_never_posts_the_email_with_a_gesture():
    """The composer's buttons carry an action id and a mode. If the body of the email ever
    appears in `data-args`, the write boundary has been crossed in the renderer."""
    source = (WEB / "ui.js").read_text(encoding="utf-8")
    block = source[source.index("function renderEmailCompose"):]
    block = block[: block.index("\n  const RENDERERS")]
    assert "compose_id=${id}&mode=${mode}" in block
    for forbidden in ("body.value", "subject.value", "&body=", "&subject=", "&to="):
        assert forbidden not in block.replace("value: body.value", "").replace("value: subject.value", ""), forbidden


def test_the_typed_value_reaches_the_mac_through_a_command_and_not_a_write_route():
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    block = app_js[app_js.index("compose · begin"): app_js.index("compose · end")]
    # One precision-field component now serves every family that has fields (the composer,
    # and the discount/order/credit workspaces of app/families/_workspace.py), so WHICH
    # command a keystroke posts is read off the card the Mac drew, with the composer's own
    # as the default for a card built before the seam existed. What has not changed, and is
    # what this test is for, is that a keystroke posts a semantic COMMAND carrying an id, a
    # field name and the characters — and never touches a write route.
    assert "control.dataset.post || 'compose.field'" in block
    assert "semanticCommand(post, { compose_id: composeId, field: name, value })" in block
    assert "COMPOSE_DEBOUNCE_MS = 400" in block
    # A field must never reach a write route, and typing must never begin a recording.
    for forbidden in ("/actions/", "startRecording", "sendAudio", "fetch("):
        assert forbidden not in block, forbidden
    assert "window.__crooksCommandDelegate" in block, "the shared delegate must be guarded"
    # A thumb on the dock while a field has focus sends what was typed and puts the keyboard
    # away, before the turn redraws the deck.
    assert "el.talk.addEventListener('pointerdown'" in block
    assert "composeFieldChanged(active)" in block and "active.blur()" in block


def test_the_hold_surface_is_not_over_the_composer():
    """The block above says typing cannot start a recording BECAUSE of the DOM, not because of
    a check. That claim has to be true of the DOM: #talk is a sibling of the deck, and in
    context mode — the only mode with cards in it — it is the band along the bottom."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    deck, talk, cards = html.index('id="deck"'), html.index('id="talk"'), html.index('id="cards"')
    assert deck < cards < talk, "the hold surface must come after the deck, as its sibling"
    assert 'id="talk"' not in html[deck:html.index('id="timings"')], "#talk must not be inside the deck"
    css = (WEB / "style.css").read_text(encoding="utf-8")
    band = css[css.index('body[data-mode="context"] .talk{'):]
    band = band[: band.index("}")]
    assert "bottom:0" in band and "height:var(--dock)" in band, band


# --------------------------------------------------------------------------- the model's way in


@pytest.mark.asyncio
@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_model_opens_a_composer_and_the_card_is_drawn_from_it(branch, session):
    """The path when the fast lane defers and Claude takes the turn: two GREEN reads that
    change nothing but the Mac's own copy, and a card built by the family that owns it."""
    from app.presentation import present
    from app.providers.base import ToolCall
    from app.tools.dispatch import dispatch

    session.branches[branch.branch_id] = branch
    session.focused_branch = branch.branch_id
    calls: list[ToolCall] = []
    text = await dispatch("gmail_compose_open",
                          {"to": "4417 lighthouse pony at example dot com", "subject": "Free on Sunday?",
                           "body": "Are you free next Sunday?", "about": "a shoot next Sunday"},
                          session=session, timeout_s=5, calls=calls)
    assert "staged" in text and "false" in text.lower()
    assert branch.compose is not None and branch.compose["to"] == ADDRESS
    compose_id = branch.compose["compose_id"]
    assert compose_id in session.issued_ids

    ui = present(calls, session=session)
    card = [item for item in ui if item["type"] == "email_compose"]
    assert len(card) == 1, [i["type"] for i in ui]
    assert card[0]["data"]["to"] == {"value": ADDRESS, "status": "uncertain", "editable": True,
                                     "hint": "heard, not typed — check it before this goes anywhere"}

    # And the words, into the same copy. The recipient is not an argument of this tool.
    calls.clear()
    await dispatch("gmail_compose_fill",
                   {"compose_id": compose_id, "subject": "Shoot on Sunday?", "body": "Are you free?"},
                   session=session, timeout_s=5, calls=calls)
    assert branch.compose["subject"] == "Shoot on Sunday?" and branch.compose["subject_status"] == "ok"
    assert branch.compose["to"] == ADDRESS, "filling the words must not touch the recipient"
    assert present(calls, session=session)[0]["data"]["subject"]["value"] == "Shoot on Sunday?"


@pytest.mark.asyncio
@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_model_cannot_open_a_composer_to_something_that_is_not_an_address(branch, session):
    from app.tools.dispatch import dispatch

    session.branches[branch.branch_id] = branch
    session.focused_branch = branch.branch_id
    text = await dispatch("gmail_compose_open", {"to": "a model", "subject": "s", "body": "b"},
                          session=session, timeout_s=5)
    assert text.startswith("ERROR") and "not an address" in text
    assert branch.compose is None, "a refused composer must not be left half-open"


@pytest.mark.asyncio
@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_filling_a_composer_that_is_not_open_is_refused(branch, session):
    from app.tools.dispatch import dispatch

    session.branches[branch.branch_id] = branch
    session.focused_branch = branch.branch_id
    session.issue("cmp_abcdef0123")
    text = await dispatch("gmail_compose_fill", {"compose_id": "cmp_abcdef0123", "subject": "s", "body": "b"},
                          session=session, timeout_s=5)
    assert text.startswith("ERROR") and "closed" in text


# --------------------------------------------------------------------------- rewriting


# --------------------------------------------------------------------------- the route


# The route-level fixtures, reused rather than rebuilt: the same app, the same lifespan and
# the same write boundary the commit route is held to. Bound by attribute, as
# tests/test_council_fixes.py binds the batch suite's, so pytest finds them under these names.
from tests import test_actions_routes as routes  # noqa: E402

PROXIED = routes.PROXIED
configure = routes.configure
client = routes.client


async def _open_and_fill(client, session_id="cmp") -> str:
    """A composer on the Mac, addressed and written, with nothing prepared."""
    session = client.runtime.sessions.get_or_create(session_id)
    branch = session.branch()
    session.acting_branch = branch.branch_id
    compose_id = family.open_compose(branch, to=ADDRESS, subject="Free on Sunday?", body="Are you free?")
    session.issue(compose_id)
    return compose_id


async def test_a_gesture_on_the_composer_is_held_to_the_write_boundary(client):
    """The refusal that /command did not make before this family existed. Staging is not a
    read: a Mac that would refuse the commit must refuse this too, or the tablet fills with
    cards it will never be allowed to apply."""
    configure(client, writes=False)
    compose_id = await _open_and_fill(client)
    reply = await client.post("/command", data={"session_id": "cmp", "command": "compose.stage",
                                                "compose_id": compose_id, "mode": "draft"},
                              headers=PROXIED)
    body = reply.json()
    assert body["ok"] is False and body["code"] == "writes_disabled", body
    assert "CROOKS_WRITES_ENABLED" in body["detail"], "the refusal has to say which of the three it was"
    assert not client.runtime.sessions.get_or_create("cmp").proposals

    # A login off the allow-list never reaches the route at all: the app refuses it in front.
    # Asserted here so that the two boundaries are known to be in the right order.
    configure(client, writes=True, logins="somebody.else@example.com")
    refused = await client.post("/command", data={"session_id": "cmp", "command": "compose.stage",
                                                  "compose_id": compose_id, "mode": "draft"},
                                headers=PROXIED)
    assert refused.status_code == 403, refused.json()
    assert not client.runtime.sessions.get_or_create("cmp").proposals


async def test_typing_into_the_composer_is_a_read_and_needs_no_write_permission(client):
    """The other side of the same rule: a keystroke changes nothing outside the Mac, so it
    works with changes switched off — the owner can correct an address on a read-only Mac and
    be told at the gesture, not at the keyboard."""
    configure(client, writes=False)
    compose_id = await _open_and_fill(client)
    body = (await client.post("/command", data={"session_id": "cmp", "command": "compose.field",
                                                "compose_id": compose_id, "field": "subject",
                                                "value": "Shoot on Sunday?"},
                              headers=PROXIED)).json()
    assert body["ok"] is True, body
    assert body["ui"][0]["type"] == "email_compose"
    assert body["ui"][0]["data"]["subject"]["value"] == "Shoot on Sunday?"
    assert body["model_calls"] == 0 and body["lane"] == "TOUCH"


async def test_the_gesture_stages_through_the_engine_and_applies_nothing(client):
    from app.clients.gmail import SCOPE_COMPOSE, SCOPE_MODIFY, ScopeReport
    from app.tools import gmail_writes

    configure(client, writes=True)
    compose_id = await _open_and_fill(client)
    sent: list = []

    class Box:
        """An inbox that grants the scope and refuses the work: the preflight has to pass and
        the mutation must never be reached, because a tap on Send only PREPARES."""

        def scopes(self, *, fresh: bool = False):
            return ScopeReport(frozenset({SCOPE_MODIFY, SCOPE_COMPOSE}), "google", 1e12)

        def address(self) -> str:
            return "orders@crooksldn.example"

        def create_draft(self, raw, thread_id):
            sent.append(("create_draft", thread_id))
            raise AssertionError("a tap that only PREPARES must never reach Gmail")

        def send_message(self, raw, thread_id):
            sent.append(("send", thread_id))
            raise AssertionError("a tap that only PREPARES must never reach Gmail")

        def list_drafts(self, query):
            return []

        def find_messages(self, query):
            return []

    box = Box()
    # The preflight reads the scopes off `runtime.gmail`; the write tool uses its own client.
    client.runtime.gmail = box
    gmail_writes.bind(box, policy=lambda: client.runtime.settings)
    try:
        body = (await client.post("/command", data={"session_id": "cmp", "command": "compose.stage",
                                                    "compose_id": compose_id, "mode": "send"},
                                  headers=PROXIED)).json()
    finally:
        gmail_writes.bind(None)
    assert body["ok"] is True, body
    assert body["changed"]["staged"] is True and body["changed"]["proposal_id"]
    card = [i for i in body["ui"] if i["type"] == "confirmation"]
    assert card and card[0]["data"]["operation"] == "gmail_send_new", body["ui"]
    proposals = client.runtime.sessions.get_or_create("cmp").proposals
    assert len(proposals) == 1 and proposals[0].status.value == "PENDING"
    assert proposals[0].execution["to"] == ADDRESS
    assert not sent, "nothing was sent and nothing was drafted"
