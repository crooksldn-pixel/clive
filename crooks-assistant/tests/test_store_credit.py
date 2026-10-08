"""Store credit: RED, money, a drag — and an honest answer when the store has not got it.

The brief's instruction was to implement it only if the 2025-07 API and the store's
configuration genuinely permit it, and to say what is unavailable if not. Both branches are
tested here, and they are told apart by a READ rather than by a guess: the fake store can be
a shop WITH store credit or a shop that answers `storeCreditAccounts: null`, which is what
Shopify does for a store that has not got the feature.

What these hold, beyond the mechanics:

* MISSING_SCOPE names the grant, NOT_SUPPORTED_BY_STORE says the code is here and the store's
  configuration is not, and a shop that will not answer is neither of those;
* the balance is read before the card, held to as the precondition, and the proof is the old
  balance plus what was credited in the currency it was credited in;
* a customer with an account per currency has the right one credited.
"""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, store_credit_input_ok
from app.families import _workspace as ws
from app.families import store_credit as sc
from app.session.models import Session
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import FakeStore

# The admitted owner calling tools directly, as a request the door let through would — granted
# per test, to the tests that call a tool, and to no others (the 2026-09-28 deploy review, round
# 9, I-tests4 I-04). A test about a declaration, a predicate or a probe runs with no authority,
# which is production's default; and `test_with_no_authority_stamped_nothing_runs` holds what a
# tool call with none gets.
AS_THE_OWNER = pytest.mark.usefixtures("owner_asking")

OPEN = sc.OPEN_TOOL
WRITE = sc.WRITE_TOOL
MIA = "gid://shopify/Customer/7001"
DAVID = "gid://shopify/Customer/7002"

PEOPLE = {
    MIA: {"name": "Mia Jones", "email": "mia.jones@example.com"},
    DAVID: {"name": "David Replica", "email": "david.replica@example.com"},
}


class CreditStore(FakeStore):
    """A shop that either has store credit or does not."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.scopes = {
            "read_orders", "write_orders", "read_customers",
            "read_store_credit_accounts", "write_store_credit_account_transactions",
        }
        # customer id -> [{currency, balance}]. None for a shop without the feature at all.
        self.accounts: dict[str, list[dict]] | None = {MIA: [{"currency": "GBP", "balance": 15.0}], DAVID: []}
        self.refuse_credit = False
        self.credit_lands = True          # False: Shopify answers and the balance does not move

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksStoreCredit" in query:
            self.reads += 1
            wanted = str((variables or {}).get("id") or "")
            person = PEOPLE.get(wanted)
            if person is None:
                return {"data": {"customer": None}}
            node = {
                "id": wanted, "displayName": person["name"],
                "defaultEmailAddress": {"emailAddress": person["email"]},
                "storeCreditAccounts": None,
            }
            if self.accounts is not None:
                node["storeCreditAccounts"] = {"edges": [
                    {"node": {"id": f"gid://shopify/StoreCreditAccount/{i}",
                              "balance": {"amount": f"{a['balance']:.2f}", "currencyCode": a["currency"]}}}
                    for i, a in enumerate(self.accounts.get(wanted) or [])
                ]}
            return {"data": {"customer": node}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate("creditInput", variables["creditInput"]), "the reviewed shape, exactly"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name != "store_credit_credit":
            raise AssertionError(f"unexpected mutation {name}")
        if self.fail_mutation or self.refuse_credit:
            raise ShopifyError("Shopify refused it.")
        who = str(variables["id"])
        money = variables["creditInput"]["creditAmount"]
        currency = str(money["currencyCode"])
        amount = round(float(money["amount"]), 2)
        rows = (self.accounts or {}).setdefault(who, [])
        if self.credit_lands:
            found = next((a for a in rows if a["currency"] == currency), None)
            if found is None:
                rows.append({"currency": currency, "balance": amount})
            else:
                found["balance"] = round(found["balance"] + amount, 2)
        after = next((a["balance"] for a in rows if a["currency"] == currency), 0.0)
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"storeCreditAccountCredit": {"storeCreditAccountTransaction": {
            "amount": {"amount": f"{amount:.2f}", "currencyCode": currency},
            "balanceAfterTransaction": {"amount": f"{after:.2f}", "currencyCode": currency},
            "account": {"id": "gid://shopify/StoreCreditAccount/0",
                        "balance": {"amount": f"{after:.2f}", "currencyCode": currency}},
        }, "userErrors": []}}}


@pytest.fixture()
def store():
    s = CreditStore()
    shopify_tools.bind(s)
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(MIA)
    s.issue(DAVID)
    s.epoch = 1
    return s


@pytest.fixture()
def branch(session):
    b = session.branch()
    b.visit("customer", MIA, "Mia Jones")
    return b


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


def _ctx(session, branch, **args):
    from app.commands import Ctx

    return Ctx(runtime=None, session=session, branch=branch, args={k: str(v) for k, v in args.items()})


async def open_workspace(session, **args) -> dict:
    from app.tools.context import CURRENT_SESSION

    token = CURRENT_SESSION.set(session)
    try:
        text = await dispatch(OPEN, {"customer_id": MIA, **args}, session=session, timeout_s=5)
    finally:
        CURRENT_SESSION.reset(token)
    return ws.held(session.branch(), sc.KIND) or {"_text": text}


async def stage(session, workspace_id: str):
    text = await dispatch(WRITE, {"workspace_id": workspace_id}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def drag(engine, proposal):
    _, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_crediting_an_account_is_red_money_a_drag_and_one_reviewed_mutation():
    spec = registry.get(WRITE)
    assert spec.tier is Tier.RED and spec.write.complete
    assert spec.write.kind == "money" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_drag_target"
    assert spec.write.operation == "store_credit_credit" and spec.write.mutation == "store_credit_credit"
    assert spec.issued_id_args == ("workspace_id",)
    reviewed = REVIEWED_MUTATIONS["store_credit_credit"]
    assert reviewed.scope == "write_store_credit_account_transactions"
    assert reviewed.idempotent is False and reviewed.root == "storeCreditAccountCredit"
    assert set(reviewed.variables) == {"id", "creditInput"}
    from app.capabilities import families

    family = families.get("store_credit")
    assert family is not None and family.operations == ("store_credit_credit",)
    assert family.scopes == ("write_store_credit_account_transactions",)
    assert set(family.tools) == {OPEN, WRITE}
    # The scope the OWNER reads is a word, not a URL (tests/test_families.py holds that for
    # every family; this is the one that could most plausibly have been a URL).
    assert "://" not in family.scopes[0]


def test_the_gate_stages_it_only_with_a_workspace_id_and_takes_nothing_else():
    good = "crd_0123456789"
    assert classify(WRITE, {"workspace_id": good}, issued_ids={good}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(WRITE, {"workspace_id": good}, issued_ids=set()).disposition is Disposition.DENY
    for extra in ({"amount": 20}, {"currency": "GBP"}, {"customer_id": MIA}):
        assert classify(WRITE, {"workspace_id": good, **extra}, issued_ids={good}).disposition is Disposition.DENY, extra
    # The read needs an issued customer, so a guessed id never reaches a Shopify read.
    assert classify(OPEN, {"customer_id": MIA}, issued_ids={MIA}).disposition is Disposition.EXECUTE_NOW
    assert classify(OPEN, {"customer_id": MIA}, issued_ids=set()).disposition is Disposition.DENY
    assert classify(OPEN, {"customer_id": "gid://shopify/Order/1"}, issued_ids={"gid://shopify/Order/1"}).disposition is Disposition.DENY


def test_the_reviewed_shape_is_one_amount_in_one_named_currency():
    assert store_credit_input_ok({"creditAmount": {"amount": "20.00", "currencyCode": "GBP"}})
    assert store_credit_input_ok({"creditAmount": {"amount": "20.00", "currencyCode": "GBP"},
                                  "expiresAt": "2027-01-01T00:00:00Z"})
    for bad in (
        {"creditAmount": {"amount": "0", "currencyCode": "GBP"}},
        {"creditAmount": {"amount": "-5.00", "currencyCode": "GBP"}},
        {"creditAmount": {"amount": "20.00", "currencyCode": "pounds"}},
        {"creditAmount": {"amount": "20.00"}},
        {"creditAmount": {"amount": "99999.00", "currencyCode": "GBP"}},
        {"expiresAt": "2027-01-01T00:00:00Z"},
        {"creditAmount": {"amount": "20.00", "currencyCode": "GBP"}, "expiresAt": "next year"},
    ):
        assert not store_credit_input_ok(bad), bad


# --------------------------------------------------------------------------- the workspace


@AS_THE_OWNER
async def test_the_balance_is_read_and_nothing_is_credited(store, session):
    workspace = await open_workspace(session, amount=20, reason="the late parcel")
    assert sc._customer(workspace)["name"] == "Mia Jones"
    assert sc._balance(workspace) == 15.0
    assert ws.value(workspace, "amount") == "20.00" and ws.value(workspace, "currency") == "GBP"
    assert sc._blocked(workspace) == ""
    assert store.mutations == [] and session.proposals == []
    assert str(workspace["workspace_id"]) in session.issued_ids
    facts = {f["label"]: f["value"] for f in sc.workspace_surface(workspace).data["facts"]}
    assert facts["Has now"] == "£15.00" and facts["Adding"] == "£20.00"
    assert facts["Would have"] == "£35.00", "the consequence, displayed"
    assert facts["Why"] == "the late parcel"


@AS_THE_OWNER
async def test_a_customer_with_no_account_yet_reads_as_nothing_not_as_unknown(store, session):
    from app.tools.context import CURRENT_SESSION

    token = CURRENT_SESSION.set(session)
    try:
        await dispatch(OPEN, {"customer_id": DAVID, "amount": 5}, session=session, timeout_s=5)
    finally:
        CURRENT_SESSION.reset(token)
    workspace = ws.held(session.branch(), sc.KIND)
    assert sc._balance(workspace) == 0.0
    assert sc._blocked(workspace) == "", "a first credit is a credit like any other"
    facts = {f["label"]: f["value"] for f in sc.workspace_surface(workspace).data["facts"]}
    assert facts["Has now"] == "£0.00"


@AS_THE_OWNER
async def test_a_store_without_store_credit_says_what_is_unavailable_and_that_the_code_exists(store, session):
    store.accounts = None
    text = await dispatch(OPEN, {"customer_id": MIA}, session=session, timeout_s=5)
    assert text.startswith("ERROR"), text
    assert "does not have store credit" in text
    assert "The code for it is here and reviewed" in text
    assert "Shopify enables store credit per store" in text
    assert ws.held(session.branch(), sc.KIND) is None, "no form for a feature the store has not got"


@AS_THE_OWNER
async def test_an_amount_the_mac_cannot_use_is_refused_with_the_reason(store, session, branch):
    from app import commands

    workspace = await open_workspace(session)
    ident = str(workspace["workspace_id"])
    for value, hint in (("", "How much credit?"), ("loads", "not an amount"), ("0", "more than nothing"),
                        ("99999", "At most")):
        commands.run("credit.field", _ctx(session, branch, workspace_id=ident, field="amount", value=value))
        assert ws.status(workspace, "amount") == "invalid", value
        assert hint in workspace["hints"]["amount"], (value, workspace["hints"]["amount"])
    assert "It needs an amount to credit" in sc._blocked(workspace)
    commands.run("credit.field", _ctx(session, branch, workspace_id=ident, field="currency", value="pounds"))
    assert ws.status(workspace, "currency") == "invalid"


@AS_THE_OWNER
async def test_a_field_the_family_did_not_declare_is_refused(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, amount=20)
    ident = str(workspace["workspace_id"])
    for name in ("facts", "customer", "accounts", "at", "input"):
        outcome = commands.run("credit.field", _ctx(session, branch, workspace_id=ident, field=name, value="x"))
        assert not outcome.ok and outcome.code == "unknown_field", name


# --------------------------------------------------------------------------- preparing


@AS_THE_OWNER
async def test_the_card_shows_the_consequence_and_the_input_carries_one_amount(store, engine, session):
    workspace = await open_workspace(session, amount=20, reason="the late parcel")
    text, proposal = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("PROPOSED"), text
    assert proposal.risk == "RED" and proposal.interaction == "hold_drag_target"
    assert proposal.status is ActionStatus.PENDING and proposal.entity_kind == "customer"
    assert proposal.entity_ref == MIA
    # Never the name. `entity_label` reaches the ledger, which carries identities, counts and
    # controlled words; `gmail_send_new` labels its entity "customer" for the same reason.
    assert proposal.entity_label == "customer" and "Mia" not in proposal.entity_label
    execution = dict(proposal.execution)
    assert set(execution) == {"workspace_id", "customer_id", "currency", "amount", "input"}
    assert execution["input"] == {"creditAmount": {"amount": "20.00", "currencyCode": "GBP"}}
    assert proposal.before == {"balance": "15.00", "currency": "GBP", "accounts": 1}
    assert proposal.expected_after == {"balance": "35.00", "currency": "GBP", "accounts": 1}
    facts = {f["label"]: f["value"] for f in registry.get(WRITE).write.present(proposal)["facts"]}
    assert facts["Customer"] == "Mia Jones" and facts["Has now"] == "£15.00"
    assert facts["Credit"] == "£20.00" and facts["Will have"] == "£35.00"
    assert facts["Spendable"] == "immediately, on anything in the shop"
    assert facts["Why"] == "the late parcel"
    assert "credit Mia Jones with £20.00 of store credit" in proposal.summary["read_back"]
    assert "cannot be taken back" in registry.get(WRITE).write.present(proposal)["detail"]


@AS_THE_OWNER
async def test_the_balance_is_read_again_at_the_moment_of_preparing(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    # Spent in the shop between the form and the prepare: the card must say the new balance,
    # and the precondition must hold the change to it.
    store.accounts[MIA] = [{"currency": "GBP", "balance": 4.0}]
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    assert proposal.before == {"balance": "4.00", "currency": "GBP", "accounts": 1}
    assert proposal.expected_after["balance"] == "24.00"
    assert sc._balance(workspace) == 4.0, "and the form is corrected too"


@AS_THE_OWNER
async def test_a_second_account_in_another_currency_credits_the_right_one(store, engine, session, branch):
    from app import commands

    store.accounts[MIA] = [{"currency": "GBP", "balance": 15.0}, {"currency": "EUR", "balance": 40.0}]
    workspace = await open_workspace(session, amount=20)
    ident = str(workspace["workspace_id"])
    commands.run("credit.field", _ctx(session, branch, workspace_id=ident, field="currency", value="eur"))
    assert sc._balance(workspace) == 40.0, "the balance in the currency being credited"
    _text, proposal = await stage(session, ident)
    assert proposal.before == {"balance": "40.00", "currency": "EUR", "accounts": 2}
    assert dict(proposal.execution)["input"]["creditAmount"]["currencyCode"] == "EUR"
    facts = {f["label"]: f["value"] for f in registry.get(WRITE).write.present(proposal)["facts"]}
    assert facts["Credit"] == "€20.00" and facts["Accounts"].startswith("2 accounts")


@AS_THE_OWNER
async def test_a_store_that_loses_the_feature_between_the_form_and_the_prepare_refuses(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    store.accounts = None
    text, _ = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("ERROR") and "does not have store credit" in text
    assert store.mutations == [] and session.proposals == []


@AS_THE_OWNER
async def test_a_workspace_that_is_not_ready_prepares_nothing(store, engine, session, branch):
    from app import commands

    workspace = await open_workspace(session)
    ident = str(workspace["workspace_id"])
    refused = commands.run("credit.stage", _ctx(session, branch, workspace_id=ident))
    assert not refused.ok and refused.code == "not_ready" and "amount to credit" in refused.detail
    text, _ = await stage(session, ident)
    assert text.startswith("ERROR") and "amount to credit" in text
    assert store.mutations == [] and session.proposals == []


@AS_THE_OWNER
async def test_the_staging_command_refuses_a_customer_this_conversation_never_looked_up(store, session):
    from app import commands

    workspace = await open_workspace(session, amount=20)
    stranger = Session(session_id="c9")
    stranger.issue(str(workspace["workspace_id"]))
    b = stranger.branch()
    b.visit("customer", MIA, "Mia Jones")
    b.workspace = dict(workspace)
    outcome = commands.run("credit.stage", _ctx(stranger, b, workspace_id=str(workspace["workspace_id"])))
    assert not outcome.ok and outcome.code == "not_held"


# --------------------------------------------------------------------------- applying


@AS_THE_OWNER
async def test_a_drag_credits_the_account_once_and_proves_it_by_reading_the_balance(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await drag(engine, proposal)
    assert result.code == "verified", result.detail
    assert result.spoken == "Their store credit is £35.00 now."
    credits = [v for name, v in store.mutations if name == "store_credit_credit"]
    assert len(credits) == 1 and credits[0]["id"] == MIA
    assert credits[0]["creditInput"] == {"creditAmount": {"amount": "20.00", "currencyCode": "GBP"}}
    assert proposal.status is ActionStatus.VERIFIED and proposal.undo_id is None
    assert proposal.after == {"balance": "35.00", "currency": "GBP", "accounts": 1}
    assert (proposal.entity or {}).get("balance") == "£35.00"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed"
    assert len([1 for n, _ in store.mutations if n == "store_credit_credit"]) == 1


@AS_THE_OWNER
async def test_a_first_credit_creates_the_account_and_is_still_proven(store, engine, session):
    """The account COUNT moves on a first credit — Shopify makes the account for the currency
    — which is why the proof is a predicate on the balance and not an equality on the whole
    fingerprint, and why the precondition does not include the count."""
    from app.tools.context import CURRENT_SESSION

    token = CURRENT_SESSION.set(session)
    try:
        await dispatch(OPEN, {"customer_id": DAVID, "amount": 10}, session=session, timeout_s=5)
    finally:
        CURRENT_SESSION.reset(token)
    workspace = ws.held(session.branch(), sc.KIND)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    assert proposal.before == {"balance": "0.00", "currency": "GBP", "accounts": 0}
    result = await drag(engine, proposal)
    assert result.code == "verified", result.detail
    assert proposal.after == {"balance": "10.00", "currency": "GBP", "accounts": 1}


@AS_THE_OWNER
async def test_a_tap_without_the_gesture_sends_nothing(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.mutations == []
    assert store.accounts[MIA][0]["balance"] == 15.0


@AS_THE_OWNER
async def test_a_balance_that_moved_between_the_card_and_the_gesture_is_stale(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.accounts[MIA] = [{"currency": "GBP", "balance": 12.5}]
    result = await drag(engine, proposal)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert result.spoken == "Their balance moved since this was prepared, so I haven't credited anything."
    assert store.mutations == [], "nothing was sent"


@AS_THE_OWNER
async def test_a_refusal_from_shopify_leaves_the_balance_alone(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.refuse_credit = True
    result = await drag(engine, proposal)
    assert result.code in ("failed", "service_unavailable", "unverified", "refused")
    assert store.accounts[MIA][0]["balance"] == 15.0
    assert proposal.status is not ActionStatus.VERIFIED


@AS_THE_OWNER
async def test_a_lost_answer_is_settled_by_reading_the_balance(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.lose_answer = True
    result = await drag(engine, proposal)
    assert result.code == "verified", result.detail
    assert len([1 for n, _ in store.mutations if n == "store_credit_credit"]) == 1


@AS_THE_OWNER
async def test_a_credit_shopify_accepted_that_did_not_move_the_balance_is_not_proven(store, engine, session):
    store.credit_lands = False
    workspace = await open_workspace(session, amount=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await drag(engine, proposal)
    assert result.code == "unverified" and proposal.verified is False
    assert result.spoken.startswith("I couldn't confirm the credit")


def test_the_verification_is_the_balance_plus_what_was_sent():
    """Exactly the old balance plus what was sent, to the penny, in the currency it was sent in
    — and nothing else is proof. Closes the 2026-09-28 deploy review, round 9, I-tests4 I-01:
    this test used to accept £15 → £40 as proof of a £20 credit."""
    verify = registry.get(WRITE).write.verify
    before = {"balance": "15.00", "currency": "GBP", "accounts": 1}
    execution = {"amount": "20.00", "currency": "GBP"}
    assert verify(before, {"balance": "35.00", "currency": "GBP", "accounts": 1}, execution) == (True, "")
    # A first credit in a currency opens the account for it: the count moves, and that is fine.
    assert verify({"balance": "0.00", "currency": "GBP", "accounts": 0}, {"balance": "20.00", "currency": "GBP", "accounts": 1}, execution)[0] is True
    assert verify(before, {"balance": "15.00", "currency": "GBP", "accounts": 1}, execution)[0] is False
    assert verify(before, {"balance": "35.00", "currency": "EUR", "accounts": 1}, execution)[0] is False
    # And a balance that went DOWN is not this change landing.
    assert verify(before, {"balance": "5.00", "currency": "GBP", "accounts": 1}, execution)[0] is False


def test_a_balance_that_moved_by_anything_but_what_was_sent_is_not_proof():
    """£15, £20 sent, £40 read back: £5 nobody can account for. Not verified — the engine then
    says "I couldn't confirm the credit. Check the customer's account", which is the truth.
    Closes the 2026-09-28 deploy review, round 9, I-tests4 I-01."""
    verify = registry.get(WRITE).write.verify
    before = {"balance": "15.00", "currency": "GBP", "accounts": 1}
    execution = {"amount": "20.00", "currency": "GBP"}
    ok, note = verify(before, {"balance": "40.00", "currency": "GBP", "accounts": 1}, execution)
    assert ok is False, "a £25 rise is not proof of a £20 credit"
    assert "£40.00" in note and "£35.00" in note and "not proven" in note
    # One penny either way is still not the credit that was sent.
    for off in ("34.99", "35.01"):
        assert verify(before, {"balance": off, "currency": "GBP", "accounts": 1}, execution)[0] is False, off
    # Pennies add as money, not as floats: 15.10 + 20.20 is 35.30 exactly.
    assert verify({"balance": "15.10", "currency": "GBP"}, {"balance": "35.30", "currency": "GBP"},
                  {"amount": "20.20", "currency": "GBP"})[0] is True
    # The currency sent in is the currency proven in, whatever the two reads agree on.
    assert verify({"balance": "15.00", "currency": "EUR"}, {"balance": "35.00", "currency": "EUR"}, execution)[0] is False
    # And a figure that is not money is never proof.
    for bad in ("", None, "abc", "NaN"):
        assert verify(before, {"balance": bad, "currency": "GBP"}, execution)[0] is False, bad


@AS_THE_OWNER
async def test_a_credit_that_landed_with_something_else_is_unverified_end_to_end(store, engine, session):
    """The whole path, not the predicate alone: the store answers the credit and reads back a
    balance £5 higher than the card said. The engine settles it UNVERIFIED and says so in
    plain words (I-tests4 I-01)."""
    workspace = await open_workspace(session, amount=20)
    _, proposal = await stage(session, str(workspace["workspace_id"]))
    assert proposal is not None and proposal.status is ActionStatus.PENDING
    assert proposal.before["balance"] == "15.00"
    credit = store.mutate

    async def credit_and_five_more(name, variables):
        answer = await credit(name, variables)
        # Somebody else's £5 lands on the same account between the credit and the re-read.
        store.accounts[MIA][0]["balance"] = round(store.accounts[MIA][0]["balance"] + 5, 2)
        return answer

    store.mutate = credit_and_five_more
    result = await drag(engine, proposal)
    assert store.accounts[MIA][0]["balance"] == 40.0, "the credit did land, with five more beside it"
    assert result.code == "unverified" and proposal.verified is False, result.code
    assert proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken.startswith("I couldn't confirm the credit")


@AS_THE_OWNER
async def test_the_ledger_keeps_the_numbers_and_not_the_customer(store, engine, session):
    workspace = await open_workspace(session, amount=20)
    await stage(session, str(workspace["workspace_id"]))
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED"
    assert line["facts"] == {"amount": "20.00", "currency": "GBP", "was": "15.00"}
    assert "Mia" not in str(line)


# --------------------------------------------------------------------- the tablet's path


@AS_THE_OWNER
async def test_the_tablet_posts_one_id_and_never_an_amount(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, amount=20)
    ident = str(workspace["workspace_id"])
    outcome = commands.run("credit.stage", _ctx(session, branch, workspace_id=ident, amount="9999", currency="EUR"))
    assert outcome.ok, outcome.detail
    staged = outcome.changed["stage"]
    assert staged["tool"] == WRITE and staged["args"] == {"workspace_id": ident}


@AS_THE_OWNER
async def test_the_card_carries_the_command_each_control_posts(store, session):
    workspace = await open_workspace(session, amount=20)
    item = sc.workspace_surface(workspace).as_ui()
    assert item["type"] == "workspace"
    data = item["data"]
    assert data["field_command"] == "credit.field"
    assert [f["name"] for f in data["fields"]] == list(sc.FIELD_NAMES)
    assert [f["kind"] for f in data["fields"]] == ["money", "code", "text"]
    assert {a["command"] for a in data["actions"]} == {"credit.stage", "credit.discard"}
    for action in data["actions"]:
        assert action["args"] == f"workspace_id={workspace['workspace_id']}"


@AS_THE_OWNER
async def test_discarding_leaves_nothing_behind(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, amount=20)
    ident = str(workspace["workspace_id"])
    gone = commands.run("credit.discard", _ctx(session, branch, workspace_id=ident))
    assert gone.ok and "Nothing was credited" in gone.answer
    assert ws.held(branch, sc.KIND) is None


def test_every_command_of_this_family_is_touch_only_and_there_is_no_open_command():
    from app import commands

    for name in ("credit.field", "credit.stage", "credit.discard"):
        spec = commands.get(name)
        assert spec is not None and spec.voice is False and spec.touch is True, name
    # Opening it needs a READ of the balance, and a command reads nothing: the way in is the
    # model calling the read tool for a customer this conversation has looked up.
    assert commands.get("credit.open") is None


# ------------------------------------------------------------------ the capability state


class Runtime:
    def __init__(self, scopes, *, sample: str = "", store=None):
        self.shopify = store or type("S", (), {"access_scopes": staticmethod(lambda: _scopes(scopes))})()
        self.store_credit_sample = sample
        self.family_states_table: dict = {}
        self.capability_states: dict = {}

    def withheld_by_family(self):
        from app.runtime import Runtime as Real

        return Real.withheld_by_family(self)


async def _scopes(scopes):
    return set(scopes)


async def test_a_missing_grant_names_the_grant_and_says_the_code_is_here():
    probed = await sc._probe(Runtime({"read_orders"}))
    assert probed["state"] == "MISSING_SCOPE"
    assert probed["scope"] == "write_store_credit_account_transactions"
    assert "the code is here" in probed["detail"]
    half = await sc._probe(Runtime({"write_store_credit_account_transactions"}))
    assert half["state"] == "MISSING_SCOPE" and half["scope"] == "read_store_credit_accounts"
    assert "not be proven" in half["detail"] or "not proven" in half["detail"]


async def test_the_grants_without_a_customer_to_ask_about_is_ready_and_says_it_is_unproven():
    probed = await sc._probe(Runtime({"write_store_credit_account_transactions", "read_store_credit_accounts"}))
    assert probed["state"] == "READY" and "proven on first use" in probed["detail"]


async def test_a_store_that_answers_without_the_field_is_not_supported_by_store(store):
    store.accounts = None
    runtime = Runtime(store.scopes, sample=MIA, store=store)
    probed = await sc._probe(runtime)
    assert probed["state"] == "NOT_SUPPORTED_BY_STORE"
    assert probed["detail"] == sc.NOT_ON_THIS_STORE
    assert "The code for it is here and reviewed" in probed["detail"]
    # And the family's tools are then withheld from the model, so it does not spend a turn
    # trying a feature the store has not got.
    runtime.family_states_table = {"store_credit": {"state": "NOT_SUPPORTED_BY_STORE"}}
    withheld = runtime.withheld_by_family()
    assert WRITE in withheld and OPEN in withheld


async def test_a_store_that_does_have_it_is_ready(store):
    probed = await sc._probe(Runtime(store.scopes, sample=MIA, store=store))
    assert probed["state"] == "READY" and "can be credited" in probed["detail"]


async def test_a_shopify_that_does_not_answer_is_neither_missing_nor_unsupported():
    class Broken:
        @staticmethod
        async def access_scopes():
            raise ShopifyError("not answering")

    probed = await sc._probe(Runtime(set(), store=Broken()))
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE" and "ShopifyError" in probed["detail"]

    class Half:
        @staticmethod
        async def access_scopes():
            return {"write_store_credit_account_transactions", "read_store_credit_accounts"}

        @staticmethod
        async def graphql(_query, _variables=None):
            raise ShopifyError("not answering")

    probed = await sc._probe(Runtime(set(), sample=MIA, store=Half()))
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE"
    assert "store credit check did not answer" in probed["detail"]


async def test_the_probe_gets_a_real_customer_from_the_cache_rather_than_guessing_ready():
    """Whether a store HAS store credit is a per-store Shopify setting, not a scope — so the
    two grants can both be present and the feature still be off.

    Without a customer to ask about, `_probe` returned READY with "proven on first use". READY
    means `runtime.withheld_by_family()` OFFERS the write tool to the model, so the first time
    the owner asked for a credit Claude would attempt it and the shop would refuse. That is
    the fifteen seconds of attempting-refused-operations section 29 exists to remove, and
    "proven on first use" is the owner paying for the proof.

    `Runtime.store_credit_sample` takes one customer id off the orders the Mac has already
    warmed, so the probe is conclusive and nothing was read for its own sake. Empty stays a
    fine answer — no cache, or no order with a customer on it — and then the old
    READY-unproven wording is honest again.
    """
    from app.runtime import Runtime

    class Cache:
        def __init__(self, rows):
            self._rows = rows

        def rows(self):
            return self._rows

    runtime = Runtime.__new__(Runtime)
    runtime.order_cache = None
    assert runtime.store_credit_sample == "", "no cache is not a customer"

    runtime.order_cache = Cache([])
    assert runtime.store_credit_sample == "", "an empty cache is not a customer"

    runtime.order_cache = Cache([{"customer": None}, {"not a dict": 1}])
    assert runtime.store_credit_sample == "", "an order with no customer on it is not a customer"

    runtime.order_cache = Cache([
        {"customer": None},
        {"customer": {"customer_id": "gid://shopify/Customer/7001", "name": "Mia Jones"}},
        {"customer": {"customer_id": "gid://shopify/Customer/7002"}},
    ])
    assert runtime.store_credit_sample == "gid://shopify/Customer/7001"

    class Broken:
        def rows(self):
            raise RuntimeError("the cache is mid-sync")

    runtime.order_cache = Broken()
    assert runtime.store_credit_sample == "", "a cache that raises must not fail a health check"


async def test_with_no_authority_stamped_nothing_runs(store, engine, session, monkeypatch):
    """The dispatch regression with NO authority (I-tests4 I-04): no `owner_asking`, as for a
    call that did not come through the owner's door. The form is not opened, the credit is not
    prepared, no handler runs and the shop is not read."""
    ran: list[str] = []
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        ran.append(name)
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    reads = store.reads
    opened = await dispatch(OPEN, {"customer_id": MIA, "amount": 20}, session=session, timeout_s=5)
    staged = await dispatch(WRITE, {"workspace_id": "wsc_0123456789"}, session=session, timeout_s=5)
    assert opened.startswith(("REFUSED", "NOT YET")) and staged.startswith(("REFUSED", "NOT YET")), (opened, staged)
    assert ran == [] and store.reads == reads and not store.mutations
    assert not session.proposals and ws.held(session.branch(), sc.KIND) is None
