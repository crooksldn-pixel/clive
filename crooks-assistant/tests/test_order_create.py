"""Making an order from nothing: RED, money, a drag, and a draft that is priced first.

The store here is a fake with two customers called Jones, a catalogue, and draft orders of
its own, so the two-mutation shape is exercised for real: `draftOrderCreate` makes and prices
the draft at PREPARE time, and `draftOrderComplete` is the only mutation the gesture sends.

What these hold, beyond the mechanics:

* two customers of the same name are named and neither is guessed at, and the same rule
  applies to an item that matches four variants;
* every number on the card is Shopify's arithmetic on the draft, not ours;
* preparing twice reuses the draft already made rather than leaving two in Admin;
* the tablet posts a workspace id, a field name and characters — never a price, never a
  variant id it invented, never the payment state as an argument of the mutation.
"""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, draft_order_input_ok
from app.families import _workspace as ws
from app.families import order_create as oc
from app.session.models import Session
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

OPEN = oc.OPEN_TOOL
WRITE = oc.WRITE_TOOL

MIA = "gid://shopify/Customer/7001"
MIA_TWIN = "gid://shopify/Customer/7009"
POPPY = "gid://shopify/Customer/7010"
HOODIE = "gid://shopify/ProductVariant/9102"
BONE = "gid://shopify/ProductVariant/9104"
CAP = "gid://shopify/ProductVariant/9301"

PEOPLE = {
    MIA: {"name": "Mia Jones", "email": "mia.jones@example.com", "orders": 3},
    MIA_TWIN: {"name": "Mia Jones", "email": "m.jones@example.net", "orders": 1},
    POPPY: {"name": "Poppy De-Witt", "email": "poppy@example.com", "orders": 0},
}
CATALOGUE = [
    {"id": "gid://shopify/Product/9001", "title": "Convict Hoodie", "status": "ACTIVE", "variants": [
        {"id": HOODIE, "title": "Black / M", "sku": "CRK-HOOD-BLK-M", "price": "60.00", "stock": 4,
         "options": [("Colour", "Black"), ("Size", "M")]},
        {"id": BONE, "title": "Bone / M", "sku": "CRK-HOOD-BON-M", "price": "60.00", "stock": 2,
         "options": [("Colour", "Bone"), ("Size", "M")]},
    ]},
    {"id": "gid://shopify/Product/9003", "title": "Crooks Cap", "status": "ACTIVE", "variants": [
        {"id": CAP, "title": "Black / One size", "sku": "CRK-CAP-BLK", "price": "18.00", "stock": 31,
         "options": [("Colour", "Black"), ("Size", "One size")]},
    ]},
]
VARIANTS = {v["id"]: (p, v) for p in CATALOGUE for v in p["variants"]}


class OrderStore(FakeStore):
    """A shop that can look people up, price a draft, and complete one."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.scopes = {"read_orders", "write_orders", "read_draft_orders", "write_draft_orders", "read_customers", "read_products"}
        self.people = dict(PEOPLE)
        self.withdrawn: set[str] = set()      # variants no longer for sale
        self.drafts: dict[str, dict] = {}
        self.draft_number = 4000
        self.refuse_complete = False
        self.complete_without_order = False

    # ---- reads

    def _rows(self, term: str) -> list[dict]:
        term = term.strip().strip('"').lower()
        if term.startswith("email:"):
            wanted = term[6:].strip().strip('"')
            return [{"id": i, **p} for i, p in self.people.items() if p["email"].lower() == wanted]
        return [{"id": i, **p} for i, p in self.people.items() if not term or term in p["name"].lower()]

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        if "CrooksCustomerCandidates" in query or "FindCustomers" in query:
            self.reads += 1
            rows = self._rows(str(variables.get("q") or ""))[: int(variables.get("n") or 5)]
            return {"data": {"customers": {"edges": [{"node": {
                "id": r["id"], "displayName": r["name"], "numberOfOrders": str(r["orders"]),
                "defaultEmailAddress": {"emailAddress": r["email"]},
                "amountSpent": {"amount": "0.00", "currencyCode": "GBP"},
            }} for r in rows]}}}
        if "CrooksCustomerForOrder" in query:
            self.reads += 1
            person = self.people.get(str(variables.get("id") or ""))
            if person is None:
                return {"data": {"customer": None}}
            return {"data": {"customer": {
                "id": str(variables["id"]), "displayName": person["name"],
                "numberOfOrders": str(person["orders"]),
                "defaultEmailAddress": {"emailAddress": person["email"]},
                "defaultAddress": ({"address1": "12 Kiln Road", "address2": "", "city": "Windsor",
                                    "provinceCode": "", "zip": "SL4 1AA", "country": "United Kingdom",
                                    "countryCodeV2": "GB"} if person.get("orders") else None),
            }}}
        if "CrooksVariantSearch" in query:
            self.reads += 1
            term = str(variables.get("q") or "").strip().lower()
            return {"data": {"products": {"pageInfo": {"hasNextPage": False}, "edges": [
                {"node": {
                    "id": p["id"], "title": p["title"], "status": p["status"],
                    "variants": {"edges": [{"node": {
                        "id": v["id"], "title": v["title"], "sku": v["sku"], "price": v["price"],
                        "availableForSale": v["id"] not in self.withdrawn,
                        "inventoryQuantity": v["stock"],
                        "selectedOptions": [{"name": n, "value": val} for n, val in v["options"]],
                    }} for v in p["variants"]]},
                }}
                for p in CATALOGUE if not term or term == "*" or term in p["title"].lower()
                or any(term in v["title"].lower() or term == v["sku"].lower() for v in p["variants"])
            ]}}}
        if "CrooksVariantForOrderEdit" in query:
            self.reads += 1
            found = VARIANTS.get(str(variables.get("id") or ""))
            if found is None:
                return {"data": {"productVariant": None}}
            product, variant = found
            return {"data": {"productVariant": {
                "id": variant["id"], "title": variant["title"], "sku": variant["sku"], "price": variant["price"],
                "availableForSale": variant["id"] not in self.withdrawn,
                "inventoryQuantity": variant["stock"],
                "selectedOptions": [{"name": n, "value": val} for n, val in variant["options"]],
                "product": {"id": product["id"], "title": product["title"], "status": product["status"]},
            }}}
        if "CrooksDraftOrder" in query:
            self.reads += 1
            draft = self.drafts.get(str(variables.get("id") or ""))
            return {"data": {"draftOrder": copy.deepcopy(draft) if draft else None}}
        return await super().graphql(query, variables)

    # ---- the two mutations

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        for key, value in variables.items():
            if isinstance(value, dict) and reviewed.validate is not None:
                assert reviewed.validate(key, value), f"{name}.{key} is not the reviewed shape"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name == "draft_order_create":
            body = dict(variables["input"])
            lines = [(str(x["variantId"]), int(x["quantity"])) for x in body["lineItems"]]
            goods = round(sum(float(VARIANTS[v][1]["price"]) * q for v, q in lines), 2)
            postage = round(float((body.get("shippingLine") or {}).get("price") or 0.0), 2)
            off = body.get("appliedDiscount") or {}
            cut = round(goods * float(off.get("value") or 0) / 100.0, 2) if off.get("valueType") == "PERCENTAGE" else 0.0
            total = round(goods - cut + postage, 2)
            self.draft_number += 1
            draft_id = f"gid://shopify/DraftOrder/{self.draft_number}"
            node = {
                "id": draft_id, "name": f"#D{self.draft_number}", "status": "OPEN",
                "totalPriceSet": {"shopMoney": {"amount": f"{total:.2f}", "currencyCode": "GBP"}},
                "subtotalPriceSet": {"shopMoney": {"amount": f"{goods - cut:.2f}", "currencyCode": "GBP"}},
                "totalShippingPriceSet": {"shopMoney": {"amount": f"{postage:.2f}", "currencyCode": "GBP"}},
                "totalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
                "customer": {"id": body["customerId"], "displayName": self.people[body["customerId"]]["name"]},
                "email": body.get("email") or "",
                "order": None,
                "lineItems": {"edges": [{"node": {
                    "id": f"gid://shopify/DraftOrderLineItem/{i}", "title": VARIANTS[v][0]["title"],
                    "variantTitle": VARIANTS[v][1]["title"], "quantity": q,
                    "originalUnitPriceSet": {"shopMoney": {"amount": VARIANTS[v][1]["price"], "currencyCode": "GBP"}},
                }} for i, (v, q) in enumerate(lines)]},
            }
            self.drafts[draft_id] = node
            return {"data": {"draftOrderCreate": {"draftOrder": copy.deepcopy(node), "userErrors": []}}}
        if name == "draft_order_complete":
            if self.fail_mutation or self.refuse_complete:
                raise ShopifyError("Shopify refused it.")
            draft = self.drafts[str(variables["id"])]
            draft["status"] = "COMPLETED"
            if not self.complete_without_order:
                draft["order"] = {"id": "gid://shopify/Order/2001", "name": "#2001"}
            if self.lose_answer:
                raise ShopifyError("timed out")
            return {"data": {"draftOrderComplete": {"draftOrder": copy.deepcopy(draft), "userErrors": []}}}
        raise AssertionError(f"unexpected mutation {name}")


@pytest.fixture()
def store():
    s = OrderStore()
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
    from app.tools.context import CURRENT_SESSION

    token = CURRENT_SESSION.set(session)
    try:
        await dispatch(OPEN, {"customer": "Poppy", **args}, session=session, timeout_s=5)
    finally:
        CURRENT_SESSION.reset(token)
    return ws.held(session.branch(), oc.KIND) or {}


def add_line(workspace: dict, variant_id: str = HOODIE, quantity: int = 1) -> None:
    """A line, as the recipe puts it there. Used by the tests about PREPARING, which are not
    about the catalogue read; the recipe's own behaviour has its own tests below."""
    _product, variant = VARIANTS[variant_id]
    workspace["facts"].setdefault("lines", []).append({
        "variant_id": variant_id, "title": _product["title"], "variant": variant["title"],
        "sku": variant["sku"], "price": variant["price"], "quantity": quantity,
    })
    workspace["facts"].pop("draft", None)


async def stage(session, workspace_id: str):
    text = await dispatch(WRITE, {"workspace_id": workspace_id}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def drag(engine, proposal):
    _, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_making_an_order_is_red_money_a_drag_and_two_reviewed_mutations():
    spec = registry.get(WRITE)
    assert spec.tier is Tier.RED and spec.write.complete
    assert spec.write.kind == "money" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_drag_target", "the gravest gesture this build has"
    assert spec.write.operation == "draft_order_complete" and spec.write.mutation == "draft_order_complete"
    assert spec.issued_id_args == ("workspace_id",)
    for name, root in (("draft_order_create", "draftOrderCreate"), ("draft_order_complete", "draftOrderComplete")):
        reviewed = REVIEWED_MUTATIONS[name]
        assert reviewed.scope == "write_draft_orders" and reviewed.idempotent is False and reviewed.root == root
    assert set(REVIEWED_MUTATIONS["draft_order_complete"].variables) == {"id", "paymentPending"}
    from app.capabilities import families

    family = families.get("order_create")
    assert family is not None and family.operations == ("draft_order_complete",)
    assert family.scopes == ("write_draft_orders",) and set(family.tools) == {OPEN, WRITE}


def test_the_gate_stages_it_only_with_a_workspace_id_and_takes_nothing_else():
    good = "ord_0123456789"
    assert classify(WRITE, {"workspace_id": good}, issued_ids={good}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(WRITE, {"workspace_id": good}, issued_ids=set()).disposition is Disposition.DENY
    assert classify(WRITE, {"workspace_id": "dsc_0123456789"}, issued_ids={"dsc_0123456789"}).disposition is Disposition.STAGE_FOR_OWNER, \
        "the shape check cannot tell a discount workspace from an order one; the family's own `held` does"
    for wrong in ("gid://shopify/Customer/7001", "cmp_0123456789"):
        assert classify(WRITE, {"workspace_id": wrong}, issued_ids={wrong}).disposition is Disposition.DENY, wrong
    for extra in ({"customer_id": MIA}, {"paymentPending": True}, {"total": "1.00"}):
        assert classify(WRITE, {"workspace_id": good, **extra}, issued_ids={good}).disposition is Disposition.DENY, extra


def test_the_reviewed_shape_refuses_a_price_of_ours_and_an_empty_order():
    good = {"lineItems": [{"variantId": HOODIE, "quantity": 2}], "customerId": MIA}
    assert draft_order_input_ok(good)
    assert not draft_order_input_ok({**good, "lineItems": []}), "an order with nothing on it"
    assert not draft_order_input_ok({"lineItems": good["lineItems"]}), "an order for nobody"
    priced = {**good, "lineItems": [{"variantId": HOODIE, "quantity": 1, "originalUnitPrice": "0.01"}]}
    assert not draft_order_input_ok(priced), "a price of ours is not a shape this application sends"
    assert not draft_order_input_ok({**good, "appliedDiscount": {"title": "x", "value": 150, "valueType": "PERCENTAGE"}})
    assert draft_order_input_ok({**good, "appliedDiscount": {"title": "x", "value": 10, "valueType": "PERCENTAGE"}})


# --------------------------------------------------------------------------- ambiguity


async def test_one_customer_of_that_name_is_resolved_and_nothing_is_staged(store, session):
    workspace = await open_workspace(session, customer="Poppy")
    assert oc._chosen_customer(workspace)["customer_id"] == POPPY
    assert ws.value(workspace, "email") == "poppy@example.com", "the confirmation address, from the shop"
    assert "It has nothing on it" in oc._blocked(workspace)
    assert store.mutations == [] and session.proposals == []
    assert str(workspace["workspace_id"]) in session.issued_ids


async def test_two_customers_of_the_same_name_are_named_and_neither_is_guessed(store, session):
    workspace = await open_workspace(session, customer="Jones")
    assert oc._chosen_customer(workspace) is None
    candidates = ws.fact(workspace, "candidates")
    assert len(candidates) == 2 and {c["customer_id"] for c in candidates} == {MIA, MIA_TWIN}
    blocked = oc._blocked(workspace)
    assert "2 customers match that name" in blocked and "I will not guess" in blocked
    assert "mia.jones@example.com" in blocked and "m.jones@example.net" in blocked
    data = oc.workspace_surface(workspace).data
    assert data["blocked"] == blocked
    assert len([f for f in data["facts"] if f["label"] == "Could be"]) == 2
    assert all(a["enabled"] is False for a in data["actions"] if a["risk"] == "red")
    # And the spoken line reads the choice back rather than making it.
    said = oc._spoken(workspace)
    assert "2 customers match" in said and "will not guess" in said


async def test_a_name_nobody_has_says_so_rather_than_offering_the_nearest(store, session):
    workspace = await open_workspace(session, customer="Nobody At All")
    assert ws.fact(workspace, "candidates") == []
    assert "Nobody in the shop is called" in oc._blocked(workspace)
    assert "make the customer in Admin first" in oc._blocked(workspace)


async def test_an_ambiguous_customer_cannot_be_prepared_by_the_model_either(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Jones")
    ident = str(workspace["workspace_id"])
    refused = commands.run("order.stage", _ctx(session, branch, workspace_id=ident))
    assert not refused.ok and refused.code == "not_ready" and "will not guess" in refused.detail
    text, _ = await stage(session, ident)
    assert text.startswith("ERROR") and "will not guess" in text
    assert store.mutations == [] and session.proposals == []


async def test_choosing_one_of_them_is_only_ever_one_the_mac_found(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Jones")
    ident = str(workspace["workspace_id"])
    good = commands.run("order.customer", _ctx(session, branch, workspace_id=ident, customer_id=MIA))
    assert good.ok and good.changed["recipe"] == "order_customer"
    assert ws.fact(workspace, "chose_customer") == MIA
    stranger = commands.run("order.customer", _ctx(session, branch, workspace_id=ident, customer_id="gid://shopify/Customer/9"))
    assert not stranger.ok and stranger.code == "unknown_customer"


async def test_the_recipe_chooses_the_one_that_was_picked_and_uses_no_model(store, session, branch):
    from app.reads.scheduler import run_plan
    from app.recipes import RECIPES
    from app.recipes import Ctx as RecipeCtx

    workspace = await open_workspace(session, customer="Jones")
    workspace["facts"]["chose_customer"] = MIA_TWIN
    recipe = RECIPES["order_customer"]
    ctx = RecipeCtx(runtime=None, session=session, branch=branch)
    plan = recipe.plan(ctx)
    assert plan is not None and [r.tool for r in plan.reads] == ["shopify_find_customer"]
    result = await run_plan(plan, session=session, timeout_s=5.0)
    answer = recipe.render(ctx, result)
    assert oc._chosen_customer(workspace)["customer_id"] == MIA_TWIN
    assert ws.value(workspace, "email") == "m.jones@example.net"
    assert answer.surfaces and answer.surfaces[0].ui_type == "workspace"
    assert answer.trace == {"candidates": 2, "chosen": True}


# --------------------------------------------------------------------------- the items


async def test_an_item_that_matches_several_variants_is_not_added(store, session, branch):
    from app.reads.scheduler import run_plan
    from app.recipes import RECIPES
    from app.recipes import Ctx as RecipeCtx

    workspace = await open_workspace(session, customer="Poppy", item="hoodie")
    recipe = RECIPES["order_line"]
    ctx = RecipeCtx(runtime=None, session=session, branch=branch, slots={"product": "hoodie"})
    result = await run_plan(recipe.plan(ctx), session=session, timeout_s=5.0)
    recipe.render(ctx, result)
    assert oc._lines(workspace) == [], "four hoodies match; choosing one for him is the same mistake as choosing a Jones"
    note = ws.fact(workspace, "item_note")
    assert "2 match 'hoodie'" in note and "Be more specific" in note
    assert "It has nothing on it" in oc._blocked(workspace)


async def test_an_item_that_matches_one_variant_is_added_at_the_catalogues_price(store, session, branch):
    from app.reads.scheduler import run_plan
    from app.recipes import RECIPES
    from app.recipes import Ctx as RecipeCtx

    workspace = await open_workspace(session, customer="Poppy", item="cap", quantity=2)
    recipe = RECIPES["order_line"]
    ctx = RecipeCtx(runtime=None, session=session, branch=branch, slots={"product": "cap"})
    result = await run_plan(recipe.plan(ctx), session=session, timeout_s=5.0)
    answer = recipe.render(ctx, result)
    lines = oc._lines(workspace)
    assert len(lines) == 1 and lines[0]["variant_id"] == CAP and lines[0]["quantity"] == 2
    assert lines[0]["price"] == "18.00", "the catalogue's price, read; never one the model said"
    assert oc._goods(workspace) == 36.0
    assert ws.value(workspace, "item") == "" and ws.value(workspace, "quantity") == "1", "the field is cleared for the next one"
    assert oc._blocked(workspace) == ""
    assert "2 x Crooks Cap" in answer.answer

    # The same variant again folds into the line rather than making a second one.
    ws.type_into(workspace, oc.FIELDS, "item", "cap")
    result = await run_plan(recipe.plan(ctx), session=session, timeout_s=5.0)
    recipe.render(ctx, result)
    assert len(oc._lines(workspace)) == 1 and oc._lines(workspace)[0]["quantity"] == 3


async def test_a_line_can_be_taken_off_again(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, CAP, 1)
    ident = str(workspace["workspace_id"])
    gone = commands.run("order.removeitem", _ctx(session, branch, workspace_id=ident, variant_id=CAP))
    assert gone.ok and oc._lines(workspace) == []
    again = commands.run("order.removeitem", _ctx(session, branch, workspace_id=ident, variant_id=CAP))
    assert not again.ok and again.code == "no_line"


# --------------------------------------------------------------------------- preparing


async def test_the_draft_is_made_and_priced_and_no_order_exists(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    add_line(workspace, CAP, 2)
    ws.type_into(workspace, oc.FIELDS, "postage", "5")
    text, proposal = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("PROPOSED"), text
    sent = [name for name, _ in store.mutations]
    assert sent == ["draft_order_create"], "the completion is the gesture's, not the prepare's"
    body = store.mutations[0][1]["input"]
    assert body["customerId"] == POPPY
    assert body["lineItems"] == [{"variantId": HOODIE, "quantity": 1}, {"variantId": CAP, "quantity": 2}]
    assert body["tags"] == [oc.DRAFT_TAG] and body["shippingLine"] == {"title": "Postage", "price": "5.00"}
    assert "originalUnitPrice" not in str(body), "not one price of ours goes in"
    # The card's numbers are the DRAFT's — 60 + 36 + 5 — read back off Shopify's answer.
    assert proposal.risk == "RED" and proposal.interaction == "hold_drag_target"
    assert proposal.status is ActionStatus.PENDING and proposal.entity_kind == "draft_order"
    assert dict(proposal.execution)["total"] == "101.00"
    assert proposal.before == {"status": "OPEN", "order": "", "total": "101.00"}
    assert proposal.expected_after["status"] == "COMPLETED"
    facts = {f["label"]: f["value"] for f in registry.get(WRITE).write.present(proposal)["facts"]}
    assert facts["Customer"] == "Poppy De-Witt · poppy@example.com" and facts["Total"] == "£101.00"
    assert facts["Goods"] == "£96.00 + £5.00 postage"
    # Eight facts is what app/presentation.py carries, and a ninth is silently dropped — so
    # the card must fit in eight rather than trust the renderer to choose which to keep.
    assert len(registry.get(WRITE).write.present(proposal)["facts"]) <= 8
    assert facts["Items"] == "1 x Convict Hoodie (Black / M), 2 x Crooks Cap (Black / One size)"
    assert facts["Payment"] == "not paid — it will owe the whole total"
    assert facts["Priced as"].startswith("draft #D") and "in Admin now" in facts["Priced as"]
    assert facts["Going to"] == "no address on file", "Poppy has never ordered; the card says so"


async def test_a_discount_is_shopifys_arithmetic_and_the_payment_state_is_the_owners(store, engine, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Mia Jones")
    # Two Joneses: pick one, then build.
    oc.choose_row(workspace, next(c for c in ws.fact(workspace, "candidates") if c["customer_id"] == MIA))
    add_line(workspace, HOODIE, 1)
    ident = str(workspace["workspace_id"])
    commands.run("order.field", _ctx(session, branch, workspace_id=ident, field="discount", value="25"))
    commands.run("order.choose", _ctx(session, branch, workspace_id=ident, field="payment", option="paid"))
    _text, proposal = await stage(session, ident)
    body = store.mutations[0][1]["input"]
    assert body["appliedDiscount"] == {"title": "Discount", "value": 25.0, "valueType": "PERCENTAGE"}
    # £60 less 25% is £45, and Shopify is the one that worked that out.
    assert dict(proposal.execution)["total"] == "45.00"
    assert dict(proposal.execution)["payment_pending"] is False
    facts = {f["label"]: f["value"] for f in registry.get(WRITE).write.present(proposal)["facts"]}
    assert facts["Discount"] == "25% off" and facts["Payment"] == "marked as already paid"
    assert facts["Going to"] == "12 Kiln Road, Windsor, SL4 1AA", "Mia has ordered; her address is read at prepare"


async def test_preparing_twice_reuses_the_draft_rather_than_leaving_two_in_admin(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    ident = str(workspace["workspace_id"])
    _text, first = await stage(session, ident)
    session.epoch += 1                      # the owner moved on and asked again
    _text, second = await stage(session, ident)
    creates = [v for name, v in store.mutations if name == "draft_order_create"]
    assert len(creates) == 1, "the same lines, the same draft"
    assert dict(second.execution)["draft_id"] == dict(first.execution)["draft_id"]
    # A line changed makes the stored draft stale, and a second draft is right.
    add_line(workspace, CAP, 1)
    session.epoch += 1
    _text, third = await stage(session, ident)
    assert len([1 for n, _ in store.mutations if n == "draft_order_create"]) == 2
    assert dict(third.execution)["draft_id"] != dict(first.execution)["draft_id"]


async def test_an_item_withdrawn_since_it_was_added_is_refused_before_the_draft(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    store.withdrawn.add(HOODIE)
    text, _ = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("ERROR") and "not for sale any more" in text
    assert store.mutations == [] and session.proposals == []


async def test_a_customer_gone_between_the_card_and_the_prepare_refuses_it(store, engine, session):
    """Deleted, merged, or erased on request between the workspace opening and the prepare.
    The order must not be made for an id the shop no longer has."""
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    del store.people[POPPY]
    text, _ = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("ERROR") and "not in the shop any more" in text
    assert "Poppy De-Witt" in text
    assert store.mutations == [] and session.proposals == []


async def test_a_name_that_now_means_several_other_people_refuses_the_prepare(store, engine, session):
    """The guard on the prepare-time re-read: the typed name matches several people and the
    one on the card is not among them, so the workspace's resolution is no longer a
    resolution. Constructed here — a customer renamed and two others taking the name is not
    a thing that happens often — because insurance whose failure mode is an order for the
    wrong person is worth a test that can fail."""
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    ws.type_into(workspace, oc.FIELDS, "customer", "Jones")
    text, _ = await stage(session, str(workspace["workspace_id"]))
    assert text.startswith("ERROR") and "2 customers now match that name" in text
    assert oc._chosen_customer(workspace) is None, "and the card no longer claims to know who"
    assert store.mutations == [] and session.proposals == []


# --------------------------------------------------------------------------- applying


async def test_a_drag_completes_the_draft_once_and_proves_it_by_re_reading_it(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await drag(engine, proposal)
    assert result.code == "verified", result.detail
    assert result.spoken == "Order D4001 is created, £60.00."
    completes = [v for name, v in store.mutations if name == "draft_order_complete"]
    assert len(completes) == 1 and completes[0]["paymentPending"] is True
    assert proposal.status is ActionStatus.VERIFIED and proposal.undo_id is None
    assert proposal.after["order"] == "gid://shopify/Order/2001"
    assert (proposal.entity or {}).get("order_number") == "#2001"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed"
    assert len([1 for n, _ in store.mutations if n == "draft_order_complete"]) == 1


async def test_a_tap_without_the_gesture_sends_nothing(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed"
    assert not any(n == "draft_order_complete" for n, _ in store.mutations)


async def test_a_draft_changed_in_admin_between_the_card_and_the_gesture_is_stale(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.drafts[dict(proposal.execution)["draft_id"]]["status"] = "INVOICE_SENT"
    result = await drag(engine, proposal)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert result.spoken == "The draft changed since this was prepared, so I haven't completed it."
    assert not any(n == "draft_order_complete" for n, _ in store.mutations)


async def test_a_draft_already_completed_is_stale_rather_than_completed_twice(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    draft = store.drafts[dict(proposal.execution)["draft_id"]]
    draft["status"], draft["order"] = "COMPLETED", {"id": "gid://shopify/Order/1", "name": "#1"}
    result = await drag(engine, proposal)
    assert result.code == "stale"
    assert not any(n == "draft_order_complete" for n, _ in store.mutations)


async def test_a_completion_that_leaves_no_order_is_not_proven(store, engine, session):
    store.complete_without_order = True
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    result = await drag(engine, proposal)
    assert result.code == "unverified" and proposal.verified is False


async def test_a_lost_answer_is_settled_by_re_reading_the_draft(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    _text, proposal = await stage(session, str(workspace["workspace_id"]))
    store.lose_answer = True
    result = await drag(engine, proposal)
    assert result.code == "verified", result.detail
    assert len([1 for n, _ in store.mutations if n == "draft_order_complete"]) == 1


def test_the_verification_is_the_order_and_not_merely_a_completed_draft():
    verify = registry.get(WRITE).write.verify
    before = {"status": "OPEN", "order": "", "total": "101.00"}
    execution = {"total": "101.00"}
    assert verify(before, {"status": "COMPLETED", "order": "gid://shopify/Order/1", "total": "101.00"}, execution)[0] is True
    assert verify(before, {"status": "COMPLETED", "order": "", "total": "101.00"}, execution)[0] is False
    assert verify(before, {"status": "INVOICE_SENT", "order": "", "total": "101.00"}, execution)[0] is False
    ok, note = verify(before, {"status": "COMPLETED", "order": "gid://shopify/Order/1", "total": "88.00"}, execution)
    assert ok is True and "not the figure on the card" in note


async def test_the_ledger_keeps_the_numbers_and_not_the_customer(store, engine, session):
    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    await stage(session, str(workspace["workspace_id"]))
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED"
    assert line["facts"] == {"lines": 1, "total": "60.00", "currency": "GBP", "pending": True}
    assert "Poppy" not in str(line)


# --------------------------------------------------------------------- the tablet's path


async def test_the_tablet_posts_one_id_and_never_a_value_of_the_change(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    ident = str(workspace["workspace_id"])
    outcome = commands.run("order.stage", _ctx(session, branch, workspace_id=ident, customer_id=MIA, total="1.00"))
    assert outcome.ok, outcome.detail
    staged = outcome.changed["stage"]
    assert staged["tool"] == WRITE and staged["args"] == {"workspace_id": ident}


async def test_a_field_the_family_did_not_declare_is_refused(store, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Poppy")
    ident = str(workspace["workspace_id"])
    for name in ("facts", "lines", "draft", "at", "customerId"):
        outcome = commands.run("order.field", _ctx(session, branch, workspace_id=ident, field=name, value="x"))
        assert not outcome.ok and outcome.code == "unknown_field", name
    for field, option in (("payment", "later"), ("address", "somewhere"), ("basis", "percentage")):
        outcome = commands.run("order.choose", _ctx(session, branch, workspace_id=ident, field=field, option=option))
        assert not outcome.ok and outcome.code == "unknown_choice", (field, option)


async def test_changing_anything_the_draft_was_built_from_makes_the_stored_draft_stale(store, engine, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    ident = str(workspace["workspace_id"])
    await stage(session, ident)
    assert (ws.fact(workspace, "draft") or {}).get("id")
    commands.run("order.field", _ctx(session, branch, workspace_id=ident, field="postage", value="5"))
    assert ws.fact(workspace, "draft") is None, "the draft priced without postage is not this order any more"


async def test_discarding_says_the_draft_is_still_in_admin(store, engine, session, branch):
    from app import commands

    workspace = await open_workspace(session, customer="Poppy")
    add_line(workspace, HOODIE, 1)
    ident = str(workspace["workspace_id"])
    await stage(session, ident)
    gone = commands.run("order.discard", _ctx(session, branch, workspace_id=ident))
    assert gone.ok and "No order was created" in gone.answer
    assert "is still in Admin" in gone.answer and "delete it there" in gone.answer
    assert ws.held(branch, oc.KIND) is None


def test_a_workspace_opened_by_touch_is_empty_and_reads_nothing(store, session, branch):
    from app import commands

    outcome = commands.run("order.open", _ctx(session, branch))
    assert outcome.ok and outcome.surfaces
    workspace = ws.held(branch, oc.KIND)
    assert workspace is not None and ws.value(workspace, "customer") == ""
    assert store.reads == 0, "a command is synchronous and reads nothing"
    assert "It needs a customer" in oc._blocked(workspace)


def test_every_command_of_this_family_is_touch_only():
    from app import commands

    for name in ("order.open", "order.field", "order.choose", "order.customer",
                 "order.additem", "order.removeitem", "order.stage", "order.discard"):
        spec = commands.get(name)
        assert spec is not None and spec.voice is False and spec.touch is True, name


# --------------------------------------------------------------------------- the fast lane


def test_what_a_tap_may_do_here_is_read():
    """The form's two recipes name read tools only: a recipe naming a write tool is a crash."""
    from app.recipes import RECIPES, assert_read_only

    assert_read_only(RECIPES)
    assert RECIPES["order_customer"].read_primitives == ("shopify_find_customer",)
    assert RECIPES["order_line"].read_primitives == (oc.SEARCH_TOOL,)


# ------------------------------------------------------------------ the capability state


async def test_the_probe_names_each_missing_grant_and_hides_the_write_tool():
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

    ready = await oc._probe(Runtime({"write_draft_orders", "read_draft_orders"}))
    assert ready["state"] == "READY"
    missing = Runtime({"read_draft_orders"})
    probed = await oc._probe(missing)
    assert probed["state"] == "MISSING_SCOPE" and probed["scope"] == "write_draft_orders"
    half = await oc._probe(Runtime({"write_draft_orders"}))
    assert half["state"] == "MISSING_SCOPE" and half["scope"] == "read_draft_orders"
    assert "created and not proven" in half["detail"]
    missing.family_states_table = {"order_create": {"state": "MISSING_SCOPE"}}
    assert WRITE in missing.withheld_by_family()


async def test_a_shopify_that_does_not_answer_is_not_a_missing_grant():
    class Broken:
        shopify = type("S", (), {"access_scopes": staticmethod(lambda: _boom())})()

    async def _boom():
        raise ShopifyError("not answering")

    probed = await oc._probe(Broken())
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE" and "ShopifyError" in probed["detail"]
