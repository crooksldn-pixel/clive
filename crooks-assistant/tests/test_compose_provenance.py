"""An address the model writes into a composer is the owner's to check, however cleanly it reads.

The 2026-09-28 deploy review, round 9, E-02. Every sentence is a model turn now, so "email
4417 lighthouse pony at example dot com" reaches `gmail_compose_open` as whatever the model
wrote down — and the model writes it down canonically: "4417lighthousepony@example.com". The
composer ran that through `check_address`, which answers for characters a finger typed, found
nothing dictated about it and marked it `ok`. `_ready_to_stage` refused only `uncertain`, so a
mis-heard address the model had tidied could reach Send without the owner ever touching it.
And the model did not need the composer's Send at all: `gmail_send_new` took any address beside
an issued `compose_id`.

The repair, held here end to end through the real gate and the real action engine:

* an address the model supplies is `uncertain` whatever its shape (`compose.check_said_address`);
* neither the tap on Save draft or Send (`_ready_to_stage`) nor the write tools themselves
  (`gmail_writes._recipient` asking `compose.owner_checked`) will prepare it until the owner has
  typed it — and then only that address, from a composer still open;
* an address from a record the conversation read — a held thread's sender — is `ok` from the
  start, because the mailbox served it.
"""

from __future__ import annotations

import pytest

from app import commands
from app.actions.models import ActionStatus
from app.commands import Ctx
from app.families import compose as family
from app.memory import ENTITY
from app.memory import current as memory
from app.session.models import Session
from app.tools.dispatch import dispatch
from tests import test_gmail_writes as mailbox

ADDRESS = "4417lighthousepony@example.com"      # as the model writes a dictated address down
THREAD = mailbox.THREAD

# The fake inbox and the engine the Gmail write tests use, bound under these names so pytest
# finds them here (the same way tests/test_compose.py borrows the route fixtures).
box = mailbox.box
engine = mailbox.engine


@pytest.fixture()
def session() -> Session:
    s = Session(session_id="prov1")
    s.issue(THREAD)
    s.epoch = 1
    s.branch()          # the focused half, which the composer tools act on
    return s


def _ctx(session, **args):
    return Ctx(runtime=None, session=session, branch=session.branch(), args={k: str(v) for k, v in args.items()})


async def _model_opens(session, to: str = ADDRESS, **extra) -> str:
    """The model's own call, as Claude makes it after hearing the sentence."""
    text = await dispatch("gmail_compose_open", {"to": to, "subject": "A shoot on Sunday",
                                                 "body": "Are you free on Sunday?", **extra},
                          session=session, timeout_s=5)
    assert not text.startswith(("ERROR", "REFUSED")), text
    return str(session.branch().compose["compose_id"])


async def _stage(session, tool: str, **args):
    before = len(session.proposals)
    text = await dispatch(tool, args, session=session, timeout_s=5)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


@pytest.mark.usefixtures("owner_asking")
async def test_an_address_the_model_wrote_down_cleanly_is_for_the_owner_to_check(session):
    """The finding's own case: a dictated address that the model supplies in canonical form.
    Before the repair it was `ok` and Send staged; now it is marked, and the tap is refused."""
    compose_id = await _model_opens(session)
    held = session.branch().compose
    assert held["to"] == ADDRESS
    assert held["to_status"] == "uncertain", "a clean transcription and a clean mistake look the same"
    assert held["to_hint"] == family.FROM_WORDS_HINT
    for mode in ("draft", "send"):
        refused = commands.run("compose.stage", _ctx(session, compose_id=compose_id, mode=mode))
        assert not refused.ok and refused.code == "not_ready", refused
        assert "stage" not in refused.changed
        assert "Tap it, check it" in refused.detail


@pytest.mark.usefixtures("owner_asking")
async def test_the_model_cannot_stage_that_address_behind_the_composers_back(box, engine, session):
    """The other door: the model calling the write tool itself with the issued composer id
    beside the address. The gate passes the id; the write tool's own check refuses the
    address, and nothing is prepared."""
    compose_id = await _model_opens(session)
    for tool in ("gmail_send_new", "gmail_draft_new"):
        text, proposal = await _stage(session, tool, compose_id=compose_id, to=ADDRESS,
                                      subject="A shoot on Sunday", body="Are you free on Sunday?")
        assert proposal is None, f"{tool} prepared an unchecked address: {text}"
        assert "has not checked that address" in text, text
    assert not box.sent and not box.drafts


@pytest.mark.usefixtures("owner_asking")
async def test_once_the_owner_has_typed_it_that_address_and_only_that_one_is_prepared(box, engine, session):
    compose_id = await _model_opens(session)
    typed = commands.run("compose.field", _ctx(session, compose_id=compose_id, field="to", value=ADDRESS))
    assert typed.ok and typed.changed["status"] == "ok", typed

    # The tap now prepares, and the change is built from the Mac's copy.
    tapped = commands.run("compose.stage", _ctx(session, compose_id=compose_id, mode="send"))
    assert tapped.ok and tapped.changed["stage"]["args"]["to"] == ADDRESS, tapped

    # A different address beside the same composer id is not the one he checked.
    text, proposal = await _stage(session, "gmail_send_new", compose_id=compose_id, to="someone.else@example.com",
                                  subject="A shoot on Sunday", body="Are you free on Sunday?")
    assert proposal is None and "not the address on the email" in text, text

    text, proposal = await _stage(session, "gmail_send_new", compose_id=compose_id, to=ADDRESS,
                                  subject="A shoot on Sunday", body="Are you free on Sunday?")
    assert proposal is not None and proposal.status is ActionStatus.PENDING, text
    assert proposal.execution["to"] == ADDRESS
    assert not box.sent, "prepared, not sent: the hold is still to come"


@pytest.mark.usefixtures("owner_asking")
async def test_a_draft_of_a_checked_address_still_turns_into_a_send(box, engine, session):
    """"Send it instead" builds its send from the draft, with the draft's composer id and
    address — which the owner checked — so the conversion is not caught by the new rule."""
    compose_id = await _model_opens(session)
    commands.run("compose.field", _ctx(session, compose_id=compose_id, field="to", value=ADDRESS))
    _, draft = await _stage(session, "gmail_draft_new", compose_id=compose_id, to=ADDRESS,
                            subject="A shoot on Sunday", body="Are you free on Sunday?")
    assert draft is not None, "the checked address drafts"
    converted = commands.run("draft.send_instead", _ctx(session))
    assert converted.ok, converted
    wanted = converted.changed["stage"]
    text, send = await _stage(session, wanted["tool"], **wanted["args"])
    assert send is not None and send.execution["to"] == ADDRESS, text


@pytest.mark.usefixtures("owner_asking")
async def test_a_composer_that_has_closed_carries_no_address(box, engine, session):
    compose_id = await _model_opens(session)
    commands.run("compose.field", _ctx(session, compose_id=compose_id, field="to", value=ADDRESS))
    commands.run("compose.discard", _ctx(session, compose_id=compose_id))
    text, proposal = await _stage(session, "gmail_send_new", compose_id=compose_id, to=ADDRESS,
                                  subject="A shoot on Sunday", body="Are you free on Sunday?")
    assert proposal is None and "no longer open" in text, text


@pytest.mark.usefixtures("owner_asking")
async def test_a_reply_takes_its_recipient_from_the_thread_the_mac_holds(session):
    """A reply opened by the model shows the thread's own sender — read off a record Gmail
    served, so it needs no check — and not whatever the model put in `to`."""
    memory().put(ENTITY, f"email_thread:{THREAD}", {"thread_id": THREAD, "messages": [
        {"from": "Daniel Stub", "from_email": mailbox.CUSTOMER, "subject": "Order 1930", "outbound": False},
    ]}, source="gmail")
    try:
        await _model_opens(session, to="somebody.else@example.com", thread_id=THREAD)
        held = session.branch().compose
        assert held["kind"] == "reply"
        assert held["to"] == mailbox.CUSTOMER and held["to_status"] == "ok", held
    finally:
        memory().drop(ENTITY, f"email_thread:{THREAD}")


@pytest.mark.usefixtures("owner_asking")
async def test_a_reply_to_a_thread_the_mac_does_not_hold_says_who_decides(session):
    await _model_opens(session, to="daniel@example.com", thread_id=THREAD)
    held = session.branch().compose
    assert held["kind"] == "reply" and held["to_status"] == "uncertain"
    assert "whoever wrote last" in held["to_hint"]
    # The reply's recipient is the thread's, re-read by the write tool, so the field the owner
    # cannot type into does not hold the reply up.
    assert family._ready_to_stage({**held, "body": "Thanks"}) == ""


def test_a_typed_address_is_still_sound_the_moment_it_is_typed():
    """What did not change: characters a finger typed that read as an address are `ok`, and a
    dictation shape is `uncertain` either way."""
    assert family.check_address(ADDRESS)[1] == "ok"
    assert family.check_said_address(ADDRESS)[1] == "uncertain"
    assert family.check_said_address("4417 lighthouse pony at example dot com")[1] == "uncertain"
    assert family.check_said_address("a model")[1] == "invalid"
