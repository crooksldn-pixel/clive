"""Creating a discount code: RED, a hold, and the collision read before anybody holds a card.

The store here is a fake with a discount table of its own, so the read the family actually
depends on is exercised for real: `codeDiscountNodeByCode` answers a node for a code it has
and null for one it has not, and `discountCodeBasicCreate` is the only mutation the gesture
sends. Nothing reaches a network.

What these hold, beyond the mechanics:

* the collision is read when the workspace opens, again when the code changes, and again at
  the moment of preparing — and a code created between the card and the tap is STALE, which
  is the difference between "nothing was sent" and a refusal from Shopify after the hold;
* the percentage the mutation carries is Shopify's fraction and the one on the card is the
  owner's number, so a typed 15 can never leave as 15.0;
* the tablet posts a workspace id and a field name and never a value of the change;
* a field name the family did not declare, and an option it did not offer, are refused.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, discount_code_input_ok
from app.families import _workspace as ws
from app.families import discounts
from app.session.models import Session
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import FakeStore

# The admitted owner calling tools directly, as a request the door let through would — granted
# per test, to the tests that call a tool, and to no others (the 2026-09-28 deploy review, round
# 9, F-A2-FIXTURE). A refusal asserted under it is a refusal the OWNER meets, so it cannot pass
# for want of authority; a test about a declaration, the gate's table or a probe runs with none,
# which is production's default; and `test_with_no_authority_stamped_nothing_runs` holds what a
# tool call with none gets.
AS_THE_OWNER = pytest.mark.usefixtures("owner_asking")

WRITE = discounts.WRITE_TOOL
OPEN = discounts.OPEN_TOOL
CHECK = discounts.CHECK_TOOL

TAKEN = {
    "SUMMER15": {
        "id": "gid://shopify/DiscountCodeNode/8801", "title": "Summer sale", "status": "ACTIVE",
        "startsAt": "2026-08-01T00:00:00Z", "endsAt": None, "usageLimit": None, "asyncUsageCount": 46,
        "value": {"__typename": "DiscountPercentage", "percentage": 0.15},
    },
    "FRIENDS5": {
        "id": "gid://shopify/DiscountCodeNode/8802", "title": "Friends and family", "status": "EXPIRED",
        "startsAt": "2026-01-01T00:00:00Z", "endsAt": "2026-03-01T00:00:00Z", "usageLimit": 200,
        "asyncUsageCount": 188,
        "value": {"__typename": "DiscountAmount", "amount": {"amount": "5.00", "currencyCode": "GBP"}},
    },
}


class DiscountStore(FakeStore):
    """A shop with two discount codes in it, and one that will accept a third."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.codes: dict[str, dict] = copy.deepcopy(TAKEN)
        self.scopes = {"read_orders", "write_orders", "read_discounts", "write_discounts"}
        self.created: list[dict] = []
        self.refuse_create = False
        self.status_after = "ACTIVE"
        self.value_after: dict | None = None      # what the shop shows afterwards, if not what was sent

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksDiscountByCode" in query:
            self.reads += 1
            found = self.codes.get(str((variables or {}).get("code") or "").upper())
            if found is None:
                return {"data": {"codeDiscountNodeByCode": None}}
            return {"data": {"codeDiscountNodeByCode": {"id": found["id"], "codeDiscount": {
                "__typename": "DiscountCodeBasic", "title": found["title"], "status": found["status"],
                "startsAt": found["startsAt"], "endsAt": found["endsAt"],
                "usageLimit": found["usageLimit"], "asyncUsageCount": found["asyncUsageCount"],
                "customerGets": {"value": copy.deepcopy(found["value"])},
            }}}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate is None or reviewed.validate("basicCodeDiscount", variables["basicCodeDiscount"]), \
            "the reviewed shape, exactly"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name != "discount_code_create":
            raise AssertionError(f"unexpected mutation {name}")
        if self.fail_mutation or self.refuse_create:
            raise ShopifyError("Shopify refused it.")
        sent = variables["basicCodeDiscount"]
        got = sent["customerGets"]["value"]
        value = ({"__typename": "DiscountPercentage", "percentage": got["percentage"]} if "percentage" in got
                 else {"__typename": "DiscountAmount",
                       "amount": {"amount": got["discountAmount"]["amount"], "currencyCode": "GBP"}})
        self.codes[sent["code"]] = {
            "id": "gid://shopify/DiscountCodeNode/9999", "title": sent["title"], "status": self.status_after,
            "startsAt": sent["startsAt"], "endsAt": sent.get("endsAt"),
            "usageLimit": sent.get("usageLimit"), "asyncUsageCount": 0,
            "value": self.value_after or value,
        }
        self.created.append(copy.deepcopy(sent))
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"discountCodeBasicCreate": {
            "codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/9999", "codeDiscount": {
                "title": sent["title"], "status": self.status_after, "startsAt": sent["startsAt"],
                "endsAt": sent.get("endsAt"), "usageLimit": sent.get("usageLimit"),
                "appliesOncePerCustomer": sent.get("appliesOncePerCustomer"),
                "codes": {"edges": [{"node": {"code": sent["code"]}}]},
            }},
            "userErrors": [],
        }}}


@pytest.fixture()
def store():
    s = DiscountStore()
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
    s.epoch = 1
    return s


@pytest.fixture()
def branch(session):
    return session.branch()


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


def _ctx(session, branch, **args):
    from app.commands import Ctx

    return Ctx(runtime=None, session=session, branch=branch, args={k: str(v) for k, v in args.items()})


async def open_workspace(session, **args) -> dict:
    """The workspace as the model opens it, through the gate, so the read tool's own
    permissions are exercised rather than the function being called directly."""
    from app.tools.context import CURRENT_SESSION

    token = CURRENT_SESSION.set(session)
    try:
        await dispatch(OPEN, {"code": "AUTUMN20", **args}, session=session, timeout_s=5)
    finally:
        CURRENT_SESSION.reset(token)
    return ws.held(session.branch(), discounts.KIND) or {}


async def stage(session, workspace_id: str):
    text = await dispatch(WRITE, {"workspace_id": workspace_id}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold(engine, proposal):
    _, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_creating_a_code_is_red_irreversible_a_hold_and_one_reviewed_mutation():
    spec = registry.get(WRITE)
    assert spec.tier is Tier.RED and spec.write.complete
    assert spec.write.kind == "irreversible" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    assert spec.write.operation == "discount_code_create" and spec.write.mutation == "discount_code_create"
    assert spec.issued_id_args == ("workspace_id",)
    reviewed = REVIEWED_MUTATIONS["discount_code_create"]
    assert reviewed.scope == "write_discounts" and reviewed.idempotent is False
    assert reviewed.root == "discountCodeBasicCreate"
    assert set(reviewed.variables) == {"basicCodeDiscount"}
    # The two reads are reads, and the family owns all three so a missing write scope hides
    # only the write.
    for name in (OPEN, CHECK):
        read = registry.get(name)
        assert read.write is None and read.batch is None and read.tier is Tier.GREEN
    from app.capabilities import families

    family = families.get("discount_create")
    assert family is not None and family.operations == ("discount_code_create",)
    assert family.scopes == ("write_discounts",)
    assert set(family.tools) == {CHECK, OPEN, WRITE}


def test_the_gate_stages_it_only_with_a_workspace_id_this_conversation_holds():
    good = "dsc_0123456789"
    assert classify(WRITE, {"workspace_id": good}, issued_ids={good}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(WRITE, {"workspace_id": good}, issued_ids=set()).disposition is Disposition.DENY
    # Not a workspace id: a Shopify gid, a composer's id, an order id.
    for wrong in ("gid://shopify/Order/1930", "cmp_0123456789", "set_0123456789"):
        assert classify(WRITE, {"workspace_id": wrong}, issued_ids={wrong}).disposition is Disposition.DENY, wrong
    # Not one value of the change is an argument this tool takes.
    for extra in ({"code": "FREE"}, {"percent": 99}, {"input": {}}):
        assert classify(WRITE, {"workspace_id": good, **extra}, issued_ids={good}).disposition is Disposition.DENY, extra
    assert classify(CHECK, {"code": "SUMMER15"}, issued_ids=set()).disposition is Disposition.EXECUTE_NOW


def test_the_reviewed_shape_refuses_the_percentage_read_the_wrong_way_round():
    """`DiscountPercentageInput.percentage` is a fraction between 0 and 1: 0.15 is fifteen
    per cent. Sending 15 there is a fifteen-hundred-per-cent discount, and that reading has
    to be impossible rather than merely avoided by the code that builds the input."""
    base = {
        "title": "t", "code": "AUTUMN20", "startsAt": "2026-09-10T00:00:00Z",
        "customerSelection": {"all": True},
        "customerGets": {"value": {"percentage": 0.2}, "items": {"all": True}},
        "combinesWith": {"orderDiscounts": False, "productDiscounts": False, "shippingDiscounts": False},
    }
    assert discount_code_input_ok(base)
    for share in (20, 1.5, 0, -0.2):
        bad = copy.deepcopy(base)
        bad["customerGets"]["value"]["percentage"] = share
        assert not discount_code_input_ok(bad), share
    # And a code that combines with the shop's own discounts, or is aimed at a segment, is
    # not a shape this application sends at all.
    stacked = copy.deepcopy(base)
    stacked["combinesWith"]["orderDiscounts"] = True
    assert not discount_code_input_ok(stacked)
    segment = copy.deepcopy(base)
    segment["customerSelection"] = {"customerSegments": {"add": ["gid://shopify/Segment/1"]}}
    assert not discount_code_input_ok(segment)


# --------------------------------------------------------------------------- the workspace


@AS_THE_OWNER
async def test_the_workspace_reads_the_shop_for_the_code_and_stages_nothing(store, session):
    workspace = await open_workspace(session, percent=20)
    assert workspace["kind"] == "discount"
    assert ws.value(workspace, "code") == "AUTUMN20" and ws.value(workspace, "value") == "20"
    assert ws.chosen(workspace, "basis") == "percentage"
    assert ws.fact(workspace, "checked_code") == "AUTUMN20" and ws.fact(workspace, "taken_by") is None
    assert discounts._blocked(workspace) == ""
    assert store.mutations == [] and session.proposals == [], "nothing was sent and nothing is waiting"
    # The id is issued, which is the whole permission story for the change behind it.
    assert str(workspace["workspace_id"]) in session.issued_ids


@AS_THE_OWNER
async def test_a_code_the_shop_already_uses_is_named_on_the_card_and_blocks_the_button(store, session):
    workspace = await open_workspace(session, code="SUMMER15", percent=20)
    assert ws.fact(workspace, "taken_by") == "Summer sale"
    blocked = discounts._blocked(workspace)
    assert "SUMMER15 is already in use by 'Summer sale'" in blocked
    data = discounts.workspace_surface(workspace).data
    assert data["blocked"] == blocked
    prepare = next(a for a in data["actions"] if a["id"] == "prepare")
    assert prepare["enabled"] is False, "a form that lets you press it and then says no wastes the gesture"
    assert {"label": "That code", "value": "already 'Summer sale'", "tone": "bad"} in data["facts"]


@AS_THE_OWNER
async def test_both_shapes_of_shopifys_value_union_are_read_back_the_same_way(store, session):
    percentage = await dispatch(CHECK, {"code": "SUMMER15"}, session=session, timeout_s=5)
    assert '"takes_off": "15%"' in percentage and '"taken": true' in percentage
    money = await dispatch(CHECK, {"code": "FRIENDS5"}, session=session, timeout_s=5)
    assert '"takes_off": "£5.00"' in money and '"status": "EXPIRED"' in money
    free = await dispatch(CHECK, {"code": "AUTUMN20"}, session=session, timeout_s=5)
    assert '"taken": false' in free


@AS_THE_OWNER
async def test_a_field_the_family_did_not_declare_is_refused_and_a_value_is_validated(store, session, branch):
    from app import commands

    workspace = await open_workspace(session)
    ident = str(workspace["workspace_id"])
    for name in ("facts", "staged", "at", "workspace_id", "input"):
        outcome = commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field=name, value="x"))
        assert not outcome.ok and outcome.code == "unknown_field", name
    # A value the Mac cannot read is stored with the reason, not silently accepted.
    commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="value", value="loads"))
    assert ws.status(workspace, "value") == "invalid"
    assert "not a number" in workspace["hints"]["value"]
    assert "a percentage, or an amount" in discounts._blocked(workspace)
    # And a date that is not a date.
    commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="ends", value="next Tuesday"))
    assert ws.status(workspace, "ends") == "invalid"


@AS_THE_OWNER
async def test_an_option_the_family_did_not_offer_is_refused(store, session, branch):
    from app import commands

    workspace = await open_workspace(session)
    ident = str(workspace["workspace_id"])
    good = commands.run("discount.choose", _ctx(session, branch, workspace_id=ident, field="basis", option="amount"))
    assert good.ok and ws.chosen(workspace, "basis") == "amount"
    for field, option in (("basis", "free"), ("each", "twice"), ("payment", "pending")):
        outcome = commands.run("discount.choose", _ctx(session, branch, workspace_id=ident, field=field, option=option))
        assert not outcome.ok and outcome.code == "unknown_choice", (field, option)
    assert ws.chosen(workspace, "basis") == "amount", "a refused choice changes nothing"


@AS_THE_OWNER
async def test_typing_a_code_asks_the_shop_again_and_typing_anything_else_does_not(store, session, branch):
    from app import commands

    workspace = await open_workspace(session)
    ident = str(workspace["workspace_id"])
    moved = commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="code", value="summer15"))
    # The code changed, so what the card said about the collision is about the old one: the
    # command names the recipe and the ROUTE does the read (a command is synchronous).
    assert moved.ok and moved.changed["recipe"] == "discount_code"
    assert ws.value(workspace, "code") == "SUMMER15", "normalised on the Mac, not on the tablet"
    assert ws.fact(workspace, "checked_code") is None, "and nothing is claimed about it until it is read"
    typed = commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="value", value="25"))
    assert typed.ok and "recipe" not in typed.changed, "a percentage costs no Shopify read"
    assert typed.surfaces and typed.surfaces[0].data["fields"][1]["value"] == "25"


@AS_THE_OWNER
async def test_the_recipe_redraws_the_workspace_with_what_the_shop_said_and_uses_no_model(store, session, branch):
    from app.reads.scheduler import run_plan
    from app.recipes import RECIPES
    from app.recipes import Ctx as RecipeCtx

    workspace = await open_workspace(session, code="SUMMER15")
    workspace["facts"].pop("taken_by", None)
    workspace["facts"].pop("checked_code", None)
    recipe = RECIPES["discount_code"]
    ctx = RecipeCtx(runtime=None, session=session, branch=branch)
    plan = recipe.plan(ctx)
    assert plan is not None and [r.tool for r in plan.reads] == [CHECK]
    result = await run_plan(plan, session=session, timeout_s=5.0)
    answer = recipe.render(ctx, result)
    assert ws.fact(workspace, "taken_by") == "Summer sale"
    assert answer.surfaces and answer.surfaces[0].ui_type == "workspace"
    assert "already in use" in answer.answer and "Nothing is created" in answer.answer


# --------------------------------------------------------------------------- preparing


@AS_THE_OWNER
async def test_the_card_says_what_the_code_does_and_the_input_carries_shopifys_fraction(store, session):
    workspace = await open_workspace(session, percent=20, ends=(date.today() + timedelta(days=20)).isoformat(), uses=50)
    text, proposal = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("PROPOSED"), text
    assert proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    assert proposal.status is ActionStatus.PENDING and proposal.entity_kind == "discount"
    assert proposal.entity_label == "AUTUMN20"
    execution = dict(proposal.execution)
    assert set(execution) == {"workspace_id", "code", "value_words", "scheduled", "input"}
    sent = execution["input"]
    assert sent["customerGets"]["value"] == {"percentage": 0.2}, "the owner typed 20; Shopify gets 0.2"
    assert sent["code"] == "AUTUMN20" and sent["usageLimit"] == 50
    assert sent["customerSelection"] == {"all": True}
    assert sent["combinesWith"] == {"orderDiscounts": False, "productDiscounts": False, "shippingDiscounts": False}
    assert execution["value_words"] == "20%" and execution["scheduled"] is False
    assert proposal.before == {"exists": False, "code": "AUTUMN20", "value": "", "status": ""}
    assert proposal.expected_after == {"exists": True, "code": "AUTUMN20", "value": "20%", "status": "ACTIVE"}
    facts = {f["label"]: f["value"] for f in registry.get(WRITE).write.present(proposal)["facts"]}
    assert facts["Code"] == "AUTUMN20" and facts["Takes off"] == "20%"
    assert facts["Applies to"] == "everything in the shop" and facts["Combines with"] == "nothing else"
    assert facts["Uses"] == "50 in total"
    assert "free — nothing in the shop uses AUTUMN20" in facts["That code now"]
    assert "create the code AUTUMN20 for 20% off" in proposal.summary["read_back"]


@AS_THE_OWNER
async def test_an_amount_off_carries_the_money_shape_and_the_currency(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, amount=7.5)
    ident = str(workspace["workspace_id"])
    assert ws.chosen(workspace, "basis") == "amount" and ws.value(workspace, "value") == "7.5"
    commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="currency", value="gbp"))
    _text, proposal = await stage(session, ident)
    sent = dict(proposal.execution)["input"]
    assert sent["customerGets"]["value"] == {"discountAmount": {"amount": "7.50", "appliesOnEachItem": False}}
    assert dict(proposal.execution)["value_words"] == "£7.50"


@AS_THE_OWNER
async def test_a_window_becomes_the_shops_own_midnights_not_utcs(store, session):
    """A code that starts on the 12th starts at the shop's midnight. Resolved in UTC it would
    start an hour early in summer, which is a bug that passes all day and fails at eleven at
    night — so the instants are asserted, not the dates."""
    first = date(2026, 7, 1)
    last = date(2026, 7, 31)
    workspace = await open_workspace(session, percent=10, starts=first.isoformat(), ends=last.isoformat())
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    sent = dict(proposal.execution)["input"]
    # July: Europe/London is UTC+1, so the shop's midnight is 23:00Z the day before.
    assert sent["startsAt"] == "2026-06-30T23:00:00Z"
    assert sent["endsAt"] == "2026-07-31T22:59:59Z", "the last moment of the 31st, so the 31st counts"
    assert dict(proposal.execution)["scheduled"] is (first > datetime.now(discounts.SHOP_TZ).date())


@AS_THE_OWNER
async def test_a_workspace_that_is_not_ready_prepares_nothing(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, code="SUMMER15", percent=10)
    ident = str(workspace["workspace_id"])
    refused = commands.run("discount.stage", _ctx(session, branch, workspace_id=ident))
    assert not refused.ok and refused.code == "not_ready" and "already in use" in refused.detail
    assert "stage" not in refused.changed
    # And the write tool refuses it too, so the route is not the only thing holding the line.
    text, _ = await stage(session, ident)
    assert text.startswith("ERROR") and "already in use" in text
    assert store.mutations == [] and session.proposals == []


@AS_THE_OWNER
async def test_a_code_taken_between_the_open_and_the_prepare_is_refused_before_anything_is_sent(store, session):
    workspace = await open_workspace(session, percent=10)
    assert ws.fact(workspace, "taken_by") is None
    store.codes["AUTUMN20"] = copy.deepcopy(TAKEN["SUMMER15"])
    text, _ = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("ERROR") and "already in use by 'Summer sale'" in text
    assert store.mutations == [] and session.proposals == []
    assert ws.fact(workspace, "taken_by") == "Summer sale", "and the card now says so"


@AS_THE_OWNER
async def test_a_workspace_from_another_conversation_cannot_be_prepared(store, session):
    workspace = await open_workspace(session, percent=10)
    stranger = Session(session_id="c9")
    text = await dispatch(WRITE, {"workspace_id": str(workspace["workspace_id"])}, session=stranger, timeout_s=5)
    assert text.startswith(("NOT YET", "REFUSED")), text
    assert store.mutations == [] and stranger.proposals == []


# --------------------------------------------------------------------------- applying


@AS_THE_OWNER
async def test_a_hold_creates_the_code_once_and_proves_it_by_reading_it_back(store, engine, session):
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await hold(engine, proposal)
    assert result.code == "verified", result.detail
    assert result.spoken == "AUTUMN20 is live — 20% off."
    creates = [v for name, v in store.mutations if name == "discount_code_create"]
    assert len(creates) == 1 and creates[0]["basicCodeDiscount"]["code"] == "AUTUMN20"
    assert proposal.status is ActionStatus.VERIFIED and proposal.verified is True
    assert proposal.after == {"exists": True, "code": "AUTUMN20", "value": "20%", "status": "ACTIVE"}
    assert proposal.undo_id is None, "there is no undo that un-creates a code customers may have used"
    assert (proposal.entity or {}).get("discount_id") == "gid://shopify/DiscountCodeNode/9999"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed"
    assert len([1 for n, _ in store.mutations if n == "discount_code_create"]) == 1


@AS_THE_OWNER
async def test_a_tap_without_the_hold_sends_nothing(store, engine, session):
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.created == [] and proposal.status is ActionStatus.PENDING


@AS_THE_OWNER
async def test_a_code_created_in_admin_between_the_card_and_the_tap_is_stale(store, engine, session):
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.codes["AUTUMN20"] = copy.deepcopy(TAKEN["SUMMER15"])
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.created == [] and proposal.status is ActionStatus.STALE
    assert result.spoken == "Somebody created that code since this was prepared, so I haven't sent it."


@AS_THE_OWNER
async def test_a_refusal_from_shopify_leaves_the_shop_without_the_code(store, engine, session):
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.refuse_create = True
    result = await hold(engine, proposal)
    assert result.code in ("failed", "service_unavailable", "unverified", "refused")
    assert "AUTUMN20" not in store.codes and proposal.status is not ActionStatus.VERIFIED


@AS_THE_OWNER
async def test_a_lost_answer_is_settled_by_reading_the_code_back(store, engine, session):
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified", result.detail
    assert len([1 for n, _ in store.mutations if n == "discount_code_create"]) == 1


async def test_a_code_created_with_the_wrong_value_is_not_proven(store, engine, session):
    """The proof is not "a discount with that code exists" — that would pass on a code
    somebody else created in the same second, and the precondition says it did not exist.
    The value has to be the one on the card."""
    verify = registry.get(WRITE).write.verify
    before = {"exists": False, "code": "AUTUMN20", "value": "", "status": ""}
    execution = {"code": "AUTUMN20", "value_words": "20%", "scheduled": False}
    assert verify(before, {"exists": True, "code": "AUTUMN20", "value": "20%", "status": "ACTIVE"}, execution)[0] is True
    assert verify(before, {"exists": False, "code": "AUTUMN20", "value": "", "status": ""}, execution)[0] is False
    assert verify(before, {"exists": True, "code": "AUTUMN20", "value": "15%", "status": "ACTIVE"}, execution)[0] is False
    assert verify(before, {"exists": True, "code": "OTHER", "value": "20%", "status": "ACTIVE"}, execution)[0] is False
    # Created and not usable: applied, with a caveat, which is not the same as a failure.
    ok, note = verify(before, {"exists": True, "code": "AUTUMN20", "value": "20%", "status": "EXPIRED"}, execution)
    assert ok is True and "expired" in note
    ok, note = verify(before, {"exists": True, "code": "AUTUMN20", "value": "20%", "status": "SCHEDULED"}, execution)
    assert ok is True and "scheduled rather than live" in note


@AS_THE_OWNER
async def test_a_value_the_shop_shows_differently_is_not_proven(store, engine, session):
    """The same check, end to end: the fake store is told to record a different percentage
    from the one it was sent, and the engine must not call that verified."""
    store.value_after = {"__typename": "DiscountPercentage", "percentage": 0.05}
    workspace = await open_workspace(session, percent=20)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await hold(engine, proposal)
    assert result.code == "unverified" and proposal.verified is False
    assert result.spoken.startswith("I couldn't confirm the code was created")


@AS_THE_OWNER
async def test_the_ledger_keeps_the_numbers_and_not_the_words(store, engine, session):
    workspace = await open_workspace(session, percent=20, uses=5)
    await stage(session, str(workspace["workspace_id"]))
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED"
    assert line["facts"] == {"basis": "percentage", "value": "20.00", "currency": "GBP", "uses": 5}


# --------------------------------------------------------------------- the tablet's path


@AS_THE_OWNER
async def test_the_tablet_posts_one_id_and_never_a_value_of_the_change(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, percent=20)
    ident = str(workspace["workspace_id"])
    outcome = commands.run("discount.stage", _ctx(session, branch, workspace_id=ident, code="FREE", percent="99"))
    assert outcome.ok, outcome.detail
    staged = outcome.changed["stage"]
    assert staged["tool"] == WRITE and staged["args"] == {"workspace_id": ident}
    assert set(staged["args"]) == {"workspace_id"}, "the code, the value and the dates are the Mac's"


@AS_THE_OWNER
async def test_the_card_the_tablet_gets_carries_the_command_each_control_posts(store, session):
    workspace = await open_workspace(session, percent=20)
    item = discounts.workspace_surface(workspace).as_ui()
    assert item["type"] == "workspace" and item["surface"] == "workspace"
    data = item["data"]
    assert data["field_command"] == "discount.field"
    assert [f["name"] for f in data["fields"]] == list(discounts.FIELD_NAMES)
    assert [f["kind"] for f in data["fields"]][:3] == ["code", "money", "code"]
    ident = str(workspace["workspace_id"])
    assert {a["command"] for a in data["actions"]} == {"discount.stage", "discount.discard"}
    assert all(a["args"].startswith(f"workspace_id={ident}") for a in data["actions"])
    # Not one of the values of the change is in an argument on the card.
    for action in data["actions"]:
        for forbidden in ("code=", "percent=", "value=", "input="):
            assert forbidden not in action["args"], (action, forbidden)


@AS_THE_OWNER
async def test_discarding_leaves_nothing_behind(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, percent=20)
    ident = str(workspace["workspace_id"])
    gone = commands.run("discount.discard", _ctx(session, branch, workspace_id=ident))
    assert gone.ok and "Nothing was created" in gone.answer
    assert ws.held(branch, discounts.KIND) is None
    again = commands.run("discount.field", _ctx(session, branch, workspace_id=ident, field="code", value="X"))
    assert not again.ok and again.code == "no_workspace"


def test_a_workspace_opened_by_touch_is_empty_and_reads_nothing(store, session, branch):
    from app import commands

    outcome = commands.run("discount.open", _ctx(session, branch))
    assert outcome.ok and outcome.surfaces
    workspace = ws.held(branch, discounts.KIND)
    assert workspace is not None and ws.value(workspace, "code") == ""
    assert store.reads == 0, "a command is synchronous and reads nothing"
    assert "It needs a code" in discounts._blocked(workspace)
    assert str(workspace["workspace_id"]) in session.issued_ids


def test_every_command_of_this_family_is_touch_only():
    from app import commands

    for name in ("discount.open", "discount.field", "discount.choose", "discount.stage", "discount.discard"):
        spec = commands.get(name)
        assert spec is not None and spec.voice is False and spec.touch is True, name


# ------------------------------------------------------------------ the capability state


async def test_a_store_without_the_scope_names_it_and_hides_the_write_tool():
    class Runtime:
        def __init__(self, scopes):
            self.shopify = type("S", (), {"access_scopes": staticmethod(lambda: _scopes(scopes))})()
            self.family_states_table: dict = {}
            self.capability_states: dict = {}

        def withheld_by_family(self):
            from app.runtime import Runtime as Real

            return Real.withheld_by_family(self)

    async def _scopes(scopes):
        return set(scopes)

    ready = await discounts._probe(Runtime({"write_discounts", "read_discounts"}))
    assert ready["state"] == "READY"
    missing = Runtime({"write_orders"})
    probed = await discounts._probe(missing)
    assert probed["state"] == "MISSING_SCOPE" and probed["scope"] == "write_discounts"
    assert "write_discounts" in probed["detail"]
    # Granted the write and not the read: it could create a code and could not tell the owner
    # whether it was taken, which is not "ready".
    half = await discounts._probe(Runtime({"write_discounts"}))
    assert half["state"] == "MISSING_SCOPE" and half["scope"] == "read_discounts"
    assert "whether a" in half["detail"] and "taken" in half["detail"]
    # MISSING_SCOPE withholds the family's tools from the model.
    missing.family_states_table = {"discount_create": {"state": "MISSING_SCOPE"}}
    withheld = missing.withheld_by_family()
    assert WRITE in withheld


async def test_a_shopify_that_does_not_answer_is_not_a_missing_grant():
    class Broken:
        shopify = type("S", (), {"access_scopes": staticmethod(lambda: _boom())})()

    async def _boom():
        raise ShopifyError("not answering")

    probed = await discounts._probe(Broken())
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE" and "ShopifyError" in probed["detail"]


@AS_THE_OWNER
async def test_a_collision_read_that_fails_does_not_claim_the_code_is_free(store, session):
    """Best effort, and honest about it: the card says the code has not been checked, and
    `_blocked` does not report it as free — because Shopify would then refuse the creation
    after the owner had held the card."""
    workspace = await open_workspace(session, percent=20)
    assert ws.fact(workspace, "checked_code") == "AUTUMN20"
    workspace["facts"].pop("checked_code")
    notes = discounts.workspace_surface(workspace).data["notes"]
    assert any("has not been checked" in n for n in notes)


async def test_with_no_authority_stamped_nothing_runs(store, engine, session, monkeypatch):
    """F-A2-FIXTURE's regression, with NO `owner_asking`: the dispatch a call gets when it did
    not come through the owner's door. The form is opened as the owner first, so its id is one
    this conversation really holds; then his authority goes, and the same conversation's call
    to prepare it — or to open another — runs no handler, reads nothing from the shop and
    prepares nothing."""
    from app.tools import authority

    granted = authority.for_owner("owner@example.com")
    token = authority.TOOL_AUTHORITY.set(granted)
    try:
        workspace = await open_workspace(session, percent=20)
    finally:
        authority.TOOL_AUTHORITY.reset(token)
        granted.revoke()
    assert workspace.get("workspace_id"), "opened as the owner"
    ran: list[str] = []
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        ran.append(name)
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    reads = store.reads
    staged = await dispatch(WRITE, {"workspace_id": str(workspace["workspace_id"])}, session=session, timeout_s=5)
    opened = await dispatch(OPEN, {"code": "WINTER10", "percent": 10}, session=session, timeout_s=5)
    assert staged.startswith(("REFUSED", "NOT YET")) and opened.startswith(("REFUSED", "NOT YET")), (staged, opened)
    assert ran == [] and store.reads == reads and not store.mutations, ran
    assert not session.proposals
