"""What a tool call with no owner behind it gets, for the modules that grant the owner to every
test in them (F-A2-FIXTURE: the 2026-09-28 deploy review, round 9, I-tests1, I-tests2 I-04,
I-tests3, I-tests4 I-04 and I-tests5 I-04; round 10, parts T2 and T5).

`tests/conftest.py::owner_asking` is not autouse: a test holds the owner's authority only when
it asks for the fixture by name, and production's default — every request the door did not
admit, every task no request started — is no authority at all. Twelve PROTECTED modules still
ask for it module-wide (`pytestmark = pytest.mark.usefixtures("owner_asking")`): test_actions,
test_actions_routes, test_address, test_batch, test_cancel, test_engine_hooks, test_fulfil,
test_gmail_writes, test_inventory, test_order_edit, test_refund and test_tracking. None of their
tests is about absent authority — every tool call in them is the owner's, and every refusal
they assert is one the OWNER meets, which a refusal for want of authority could not stand in
for. (One unprotected module keeps a module-wide grant too, tests/test_action_state.py: every
test in it begins by staging or applying the owner's own change and uses the proposal that
came of it, so a call refused for want of authority fails each of them at once.) So
instead of editing protected files, what those modules cannot say is said here, with no
`owner_asking` anywhere in this file:

- every write and bulk change those modules stage, made as a call the gate would prepare for
  the owner, is refused to no authority before the gate — no handler, no read, no card, no id
  handed out — in a context never stamped and under an owner authority that has been revoked,
  which is what `owner_asking` leaves behind it;
- every registered tool, whatever it is asked, is refused the same way;
- for two of them the whole pair is run on the real handlers: refused with no authority, and
  the identical call prepared for the owner, so the refusal was for want of authority only;
- the two refusal tests in those modules that would pass on a call with no authority (a
  tracking number that is not one; a quantity out of bounds) are refused to the owner for
  what was asked, never for who asked.

Every test here asserts the fresh-context refusal the round-9 repairs ask for. Scenarios that
the harness drives are held to the same rule in tests/test_experience.py.
"""

from __future__ import annotations

import asyncio
import contextvars

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.session.models import Session
from app.tools import authority, registry, shopify_tools, shopify_writes
from app.tools import dispatch as dispatch_module
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, classify
from tests.test_actions_routes import client  # noqa: F401 — the application, as the suite runs it

# What the dispatcher answers a call made with no authority (app/tools/dispatch.py). The gate's
# own refusals carry a refusal id — "REFUSED (ref_…):" — and this does not.
NO_AUTHORITY = "REFUSED: this was not asked for by the owner"
OWNER = "owner@example.com"

ORDER = "gid://shopify/Order/1930"
THREAD = "18f3a9c2b1d4e5f6"
SET = "set_abcdef123456"
VARIANT = "gid://shopify/ProductVariant/44"
HOODIE = "gid://shopify/ProductVariant/9102"

# Each write or bulk change the module-wide-granted modules stage, as a call the gate prepares
# for the owner (checked below, so none of these is refused for its arguments): the module
# that stages it as the owner end to end is named beside it.
STAGED_BY_THE_GRANTED_MODULES = {
    "shopify_order_note_append": ({"order_id": ORDER, "note": "Customer asked for an exchange"}, "test_actions, test_actions_routes"),
    "shopify_order_cancel": ({"order_id": ORDER}, "test_cancel"),
    "shopify_refund_create": ({"order_id": ORDER, "amount": "20"}, "test_refund"),
    "shopify_order_shipping_address_set": ({"order_id": ORDER, "address1": "4 Example Row", "city": "London",
                                            "postcode": "EC1A 1AA", "country_code": "GB"}, "test_address"),
    "shopify_order_fulfil": ({"order_id": ORDER}, "test_fulfil"),
    "shopify_fulfillment_tracking_set": ({"order_id": ORDER, "tracking_number": "AB123456785GB"}, "test_tracking"),
    "shopify_inventory_adjust": ({"variant_id": VARIANT, "delta": 2}, "test_inventory"),
    "shopify_order_add_item": ({"order_id": ORDER, "variant_id": HOODIE, "quantity": 1}, "test_order_edit"),
    "gmail_draft_reply": ({"thread_id": THREAD, "body": "Hi Daniel", "order_id": ORDER}, "test_gmail_writes"),
    "gmail_send_reply": ({"thread_id": THREAD, "body": "Hi Daniel", "order_id": ORDER}, "test_gmail_writes"),
    "gmail_thread_archive": ({"thread_id": THREAD}, "test_gmail_writes"),
    "gmail_draft_new": ({"to": "daniel@example.com", "subject": "Your order", "body": "Hi", "order_id": ORDER}, "test_gmail_writes"),
    "gmail_send_new": ({"to": "daniel@example.com", "subject": "Your order", "body": "Hi", "order_id": ORDER}, "test_gmail_writes"),
    "batch_order_tags_add": ({"set_id": SET, "tags": ["hold"]}, "test_batch"),
    "batch_order_tags_remove": ({"set_id": SET, "tags": ["hold"]}, "test_batch"),
    "batch_email_archive": ({"set_id": SET}, "test_batch"),
    "batch_email_drafts": ({"set_id": SET, "subject": "Your order", "body": "Hi"}, "test_batch"),
    "batch_email_send": ({"set_id": SET, "subject": "Your order", "body": "Hi"}, "test_batch"),
    # [inbox] DEC-071, 8 Oct: junk (ruling 27), singly and on one card for a set; a draft sent as Gmail holds it (ruling 34).
    "gmail_thread_junk": ({"thread_id": THREAD}, "test_inbox_junk"),
    "batch_email_junk": ({"set_id": SET}, "test_inbox_junk"),
    "gmail_send_draft": ({"thread_id": THREAD}, "test_staff_send_draft"),
}
ISSUED = frozenset({ORDER, THREAD, SET, VARIANT, HOODIE})


def _load_every_tool() -> None:
    from experience import tool_matrix

    tool_matrix.load()


@pytest.fixture()
def nothing_reached(monkeypatch):
    """Every way from the dispatcher to a handler, recording anything that gets there."""
    reached: list[str] = []

    def record(step):
        async def reached_it(name, *args, **kwargs):
            reached.append(f"{step}:{name}")
            raise AssertionError(f"{name} reached {step} with no owner authority")
        return reached_it

    monkeypatch.setattr(dispatch_module, "_read_once", record("_read_once"))
    monkeypatch.setattr(dispatch_module, "_stage", record("_stage"))
    monkeypatch.setattr(registry, "invoke", record("invoke"))
    return reached


def _session() -> Session:
    s = Session(session_id="no-authority")
    for ref in ISSUED:
        s.issue(ref)
    s.epoch = 1
    return s


async def _in_a_fresh_context(tool: str, args: dict, session: Session, calls: list) -> str:
    """The call as a task no admitted request started makes it: in a brand-new context, where
    the authority has never been set — even though the code that starts it is the owner's."""
    async def call() -> str:
        assert authority.TOOL_AUTHORITY.get() is None and authority.current() is None
        return await dispatch(tool, dict(args), session=session, timeout_s=5, calls=calls)

    with authority.acting_as(authority.for_owner(OWNER)):
        task = asyncio.get_running_loop().create_task(call(), context=contextvars.Context())
    return await task


def test_the_owner_is_asked_for_by_name_and_this_file_never_asks():
    """The fixture itself, as pytest holds it: `owner_asking` is not autouse; and this test,
    which does not ask for it, holds no authority once every autouse fixture has run — so none
    of them grants it (the one that asks for it by name does so for six named tests of the
    protected tests/test_gate.py and nothing else)."""
    from tests import conftest

    marker = getattr(conftest.owner_asking, "_fixture_function_marker", None)
    assert marker is not None and marker.autouse is False, "owner_asking must be asked for by name"
    assert authority.current() is None and authority.TOOL_AUTHORITY.get() is None


def test_the_calls_here_are_ones_the_gate_would_prepare_for_the_owner():
    """So that the refusals below are for want of authority and for nothing else: each call,
    asked by the owner in a conversation that was shown its ids, is one the gate prepares for
    him — none is refused for its arguments. And every write or bulk tool of the modules that
    grant the owner module-wide is here."""
    _load_every_tool()
    for tool, (args, _where) in STAGED_BY_THE_GRANTED_MODULES.items():
        spec = registry.get(tool)
        assert spec.write is not None or spec.batch is not None, f"{tool} is not a change"
        decision = classify(tool, args, issued_ids=set(ISSUED))
        assert decision.disposition is Disposition.STAGE_FOR_OWNER, (tool, decision.reason)
    granted_writes = {"shopify_order_note_append", "shopify_order_cancel", "shopify_refund_create",
                      "shopify_order_shipping_address_set", "shopify_order_fulfil", "shopify_fulfillment_tracking_set",
                      "shopify_inventory_adjust", "shopify_order_add_item"}
    granted_writes |= {s.name for s in registry.all_specs() if s.name.startswith("gmail_") and s.write is not None}
    granted_writes |= {s.name for s in registry.all_specs() if s.batch is not None}
    assert granted_writes <= set(STAGED_BY_THE_GRANTED_MODULES), granted_writes - set(STAGED_BY_THE_GRANTED_MODULES)


@pytest.mark.parametrize("tool", sorted(STAGED_BY_THE_GRANTED_MODULES))
async def test_a_change_the_owner_would_be_offered_is_refused_to_no_authority_before_anything(tool, nothing_reached):
    _load_every_tool()
    args, _where = STAGED_BY_THE_GRANTED_MODULES[tool]
    session = _session()
    issued = set(session.issued_ids)
    calls: list = []
    text = await _in_a_fresh_context(tool, args, session, calls)
    assert text.startswith(NO_AUTHORITY), text
    # And under the owner's authority once it has been revoked — the state `owner_asking`, and a
    # request whose answer has been sent, leave behind them.
    revoked = authority.for_owner(OWNER)
    revoked.revoke()
    with authority.acting_as(revoked):
        again = await dispatch(tool, dict(args), session=session, timeout_s=5, calls=calls)
    assert again.startswith(NO_AUTHORITY), again
    assert [(c.name, c.ok, c.error) for c in calls] == [(tool, False, "no owner authority")] * 2
    assert nothing_reached == [] and session.proposals == [] and set(session.issued_ids) == issued
    assert not getattr(session, "batches", None), "no bulk change was prepared"


async def test_every_registered_tool_is_refused_to_no_authority_whatever_it_is_asked(nothing_reached):
    _load_every_tool()
    names = [spec.name for spec in registry.all_specs()]
    assert len(names) > 40
    session = _session()
    calls: list = []
    for name in names:
        text = await _in_a_fresh_context(name, {}, session, calls)
        assert text.startswith(NO_AUTHORITY), (name, text)
    assert [c.error for c in calls] == ["no owner authority"] * len(names)
    assert nothing_reached == [] and session.proposals == []


# ------------------------------------------------------------- the pair, on the real handlers


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


async def test_a_note_is_refused_with_no_authority_and_prepared_for_the_owner(engine):
    """test_actions' own call and store: nobody behind it, then the owner."""
    from tests.test_actions import ORDER as NOTE_ORDER
    from tests.test_actions import FakeStore

    store = FakeStore(note="Gift wrap please")
    shopify_tools.bind(store)
    session = Session(session_id="pair")
    session.issue(NOTE_ORDER)
    session.epoch = 1
    args = {"order_id": NOTE_ORDER, "note": "Customer asked for an exchange"}
    refused = await _in_a_fresh_context("shopify_order_note_append", args, session, [])
    assert refused.startswith(NO_AUTHORITY) and store.reads == 0 and session.proposals == [], refused
    with authority.acting_as(authority.for_owner(OWNER)):
        prepared = await dispatch("shopify_order_note_append", args, session=session, timeout_s=5)
    assert prepared.startswith("PROPOSED") and len(session.proposals) == 1 and store.mutations == [], prepared


async def test_a_tracking_number_is_refused_with_no_authority_and_prepared_for_the_owner(engine):
    """test_tracking's own call and store: nobody behind it, then the owner."""
    from tests import test_tracking as tracking

    store = tracking.TrackingStore()
    shopify_tools.bind(store)
    shopify_writes.bind_policy(lambda: tracking.Policy())
    session = Session(session_id="pair-tracking")
    session.issue(tracking.ORDER)
    session.epoch = 1
    args = {"order_id": tracking.ORDER, "tracking_number": tracking.TRACKING}
    refused = await _in_a_fresh_context(tracking.TOOL, args, session, [])
    assert refused.startswith(NO_AUTHORITY) and store.reads == 0 and session.proposals == [], refused
    with authority.acting_as(authority.for_owner(OWNER)):
        prepared = await dispatch(tracking.TOOL, args, session=session, timeout_s=5)
    assert prepared.startswith("PROPOSED") and len(session.proposals) == 1 and store.mutations == [], prepared


# ------------------------------------ the two granted refusals that no authority could satisfy


def _refused_for_what_was_asked(text: str) -> bool:
    """A refusal the tool or the gate gave for the call itself: an error, or the gate's own
    refusal with its id — and not the answer to a call with no authority. (No wider than the
    protected tests it stands beside, which accept "ERROR" or "REFUSED".)"""
    return text.startswith(("ERROR", "REFUSED (")) and not text.startswith(NO_AUTHORITY)


@pytest.mark.parametrize("bad", ["", "AB1", "x" * 35, "AB123456785GB;DROP", "<b>x</b>"])
async def test_a_tracking_number_that_is_not_one_is_refused_to_the_owner_for_what_it_is(bad, engine):
    """tests/test_tracking.py::test_a_number_that_is_not_a_number_is_refused_before_anything_is_read
    accepts any "ERROR" or "REFUSED", which a call with no authority would also satisfy. Its
    module grants the owner, so it is his refusal; this says so explicitly."""
    from tests import test_tracking as tracking

    store = tracking.TrackingStore()
    shopify_tools.bind(store)
    shopify_writes.bind_policy(lambda: tracking.Policy())
    session = Session(session_id="bad-tracking")
    session.issue(tracking.ORDER)
    session.epoch = 1
    with authority.acting_as(authority.for_owner(OWNER)):
        text = await dispatch(tracking.TOOL, {"order_id": tracking.ORDER, "tracking_number": bad}, session=session, timeout_s=5)
    assert _refused_for_what_was_asked(text), text
    assert store.reads == 0 and session.proposals == []


async def test_a_quantity_out_of_bounds_is_refused_to_the_owner_for_what_it_is(engine):
    """tests/test_order_edit.py::test_a_quantity_outside_the_bound_is_refused_before_anything_is_read,
    likewise: the owner's refusal, for the quantity."""
    from tests import test_order_edit as edit

    store = edit.EditStore()
    shopify_tools.bind(store)
    shopify_writes.bind_policy(lambda: edit.Policy())
    session = Session(session_id="bad-quantity")
    for ref in (edit.ORDER, edit.HOODIE):
        session.issue(ref)
    session.epoch = 1
    with authority.acting_as(authority.for_owner(OWNER)):
        for bad in (0, -1, 999):
            text = await dispatch(edit.TOOL, {"order_id": edit.ORDER, "variant_id": edit.HOODIE, "quantity": bad},
                                  session=session, timeout_s=5)
            assert _refused_for_what_was_asked(text), (bad, text)
    assert store.mutations == [] and session.proposals == []


# ------------------------------------------------------- the one default the suite does grant


async def test_the_suites_own_server_lets_itself_ask_and_never_apply_a_change(client):  # noqa: F811
    """The default every test that runs the application meets, set in tests/conftest.py
    (`_TEST_ENV`) and said there: the offline server is the owner's, asked from the server
    itself — CROOKS_ALLOWED_LOGINS names his login and CROOKS_LOCAL_OWNER is on — so a request
    made on the server that the door admits holds the owner's authority for its length, as it
    would on his Mac with that switch on. What no test is given by default is a change: writes
    are off (CROOKS_WRITES_ENABLED); with them on, a request made on the server still may not
    apply one (CROOKS_WRITES_LOCAL_OWNER); and the owner's login claimed through Tailscale is
    refused at the door, because Tailscale's confirmation is on (CROOKS_TAILSCALE_VERIFY)."""
    from app import identity
    from tests.test_actions_routes import PROXIED, commit, staged

    settings = client.runtime.settings
    assert (settings.writes_enabled, settings.writes_local_owner, settings.tailscale_verify, settings.local_owner) == \
        (False, False, True, True)
    assert client.runtime.allowed_logins == (OWNER,)
    # Tailscale is not on this machine: asked who opened a connection, the answer is "not it"
    # (the kernel is not read; tests/conftest.py puts the seam back).
    identity.bind_peer_check(lambda _client, _server: (False, "no tailscaled on the test machine"))

    asked = await client.post("/turn", json={"text": "hello", "session_id": "default"})
    assert asked.status_code == 200, asked.text
    with authority.acting_as(authority.for_owner(OWNER)):
        proposal = await staged(client, session_id="default")
    refused = await commit(client, proposal.proposal_id, session_id="default", headers={})
    assert refused.status_code == 403 and refused.json()["code"] == "writes_disabled", refused.text

    client.runtime.settings = settings.model_copy(update={"writes_enabled": True})
    refused = await commit(client, proposal.proposal_id, session_id="default", headers={})
    assert refused.status_code == 403 and refused.json()["code"] == "not_authorised_local", refused.text
    claimed = await commit(client, proposal.proposal_id, session_id="default", headers=PROXIED)
    assert claimed.status_code == 403, claimed.text
    assert client.store.mutations == [] and proposal.status.value == "PENDING"
