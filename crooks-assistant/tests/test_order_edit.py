"""Adding an item to an order: RED, a hold, priced by Shopify before the owner authorises it.

The store here is a fake with a catalogue and an order edit of its own, so the three-mutation
shape is exercised for real: `orderEditBegin` and `orderEditAddVariant` build and price a
scratch order at PREPARE time and leave the order alone, and `orderEditCommit` is the only
mutation the gesture sends. Nothing reaches a network.

What these hold, beyond the mechanics:

* the two calculation mutations run before the card and change nothing on the order;
* the card's numbers are Shopify's arithmetic, not the tool's;
* a cancelled or archived order, and a variant that is not for sale, are refused before
  anything is opened;
* the tablet's own path posts three ids and an integer and never an execution argument.
"""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError
from app.families import order_edit
from app.session.models import Session
from app.tools import registry, shopify_tools, shopify_writes
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_order_add_item"
SEARCH = "shopify_variant_search"
HOODIE = "gid://shopify/ProductVariant/9102"      # Convict Hoodie, Black / M, £60.00
BONE = "gid://shopify/ProductVariant/9104"        # Convict Hoodie, Bone / M, £60.00
CAP = "gid://shopify/ProductVariant/9301"         # Crooks Cap, Black / One size, £18.00
CALCULATED = "gid://shopify/CalculatedOrder/1930"

# The catalogue the fake store answers with: one product, three variants, one of them sold out.
CATALOGUE = [
    {
        "id": "gid://shopify/Product/9001", "title": "Convict Hoodie", "status": "ACTIVE",
        "variants": [
            {"id": HOODIE, "title": "Black / M", "sku": "CRK-HOOD-BLK-M", "price": "60.00", "inventoryQuantity": 4,
             "options": [("Colour", "Black"), ("Size", "M")]},
            {"id": BONE, "title": "Bone / M", "sku": "CRK-HOOD-BON-M", "price": "60.00", "inventoryQuantity": 0,
             "options": [("Colour", "Bone"), ("Size", "M")]},
        ],
    },
    {
        "id": "gid://shopify/Product/9003", "title": "Crooks Cap", "status": "ACTIVE",
        "variants": [
            {"id": CAP, "title": "Black / One size", "sku": "CRK-CAP-BLK", "price": "18.00", "inventoryQuantity": 31,
             "options": [("Colour", "Black"), ("Size", "One size")]},
        ],
    },
]
VARIANTS = {v["id"]: (p, v) for p in CATALOGUE for v in p["variants"]}


class EditStore(FakeStore):
    """An order with one line of £60, paid, and a catalogue to add from.

    The money follows the fixture's own rule: the order's total is its lines plus £5 postage,
    and what the customer owes after an edit is the new total less what has been paid.
    """

    SHIPPING = 5.0

    def __init__(self) -> None:
        super().__init__(note="")
        self.lines: list[tuple[str, int]] = [(HOODIE, 1)]
        self.cancelled_at: str | None = None
        self.closed_at: str | None = None
        self.paid = 65.0                      # £60 of goods and £5 of postage
        self.edits: list[tuple[str, dict]] = []      # the calculation mutations, in order
        self.added: list[tuple[str, int]] = []       # what has been put on the scratch order
        self.committed = False
        self.refuse_commit = False
        self.commit_other_order = False
        self.fail_add = False

    # ---- reads

    def _total(self, lines: list[tuple[str, int]]) -> float:
        return round(sum(float(VARIANTS[v][1]["price"]) * q for v, q in lines) + self.SHIPPING, 2)

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "cancelledAt": self.cancelled_at, "closedAt": self.closed_at,
            "currentTotalPriceSet": {"shopMoney": {"amount": f"{self._total(self.lines):.2f}", "currencyCode": "GBP"}},
            "totalOutstandingSet": {"shopMoney": {"amount": f"{max(0.0, self._total(self.lines) - self.paid):.2f}", "currencyCode": "GBP"}},
            "lineItems": {"edges": [
                {"node": {"id": f"gid://shopify/LineItem/{i}", "quantity": q, "currentQuantity": q, "variant": {"id": v}}}
                for i, (v, q) in enumerate(self.lines)
            ]},
        })
        return node

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        if "CrooksVariantForOrderEdit" in query:
            self.reads += 1
            found = VARIANTS.get(str(variables.get("id") or ""))
            if found is None:
                return {"data": {"productVariant": None}}
            product, variant = found
            return {"data": {"productVariant": {
                "id": variant["id"], "title": variant["title"], "sku": variant["sku"], "price": variant["price"],
                "availableForSale": variant["inventoryQuantity"] > 0, "inventoryQuantity": variant["inventoryQuantity"],
                "selectedOptions": [{"name": n, "value": val} for n, val in variant["options"]],
                "product": {"id": product["id"], "title": product["title"], "status": product["status"]},
            }}}
        if "CrooksVariantSearch" in query:
            self.reads += 1
            term = str(variables.get("q") or "").strip().lower()
            return {"data": {"products": {"pageInfo": {"hasNextPage": False}, "edges": [
                {"node": {
                    "id": p["id"], "title": p["title"], "status": p["status"],
                    "variants": {"edges": [{"node": {
                        "id": v["id"], "title": v["title"], "sku": v["sku"], "price": v["price"],
                        "availableForSale": v["inventoryQuantity"] > 0, "inventoryQuantity": v["inventoryQuantity"],
                        "selectedOptions": [{"name": n, "value": val} for n, val in v["options"]],
                    }} for v in p["variants"]]},
                }}
                for p in CATALOGUE if not term or term == "*" or term in p["title"].lower()
            ]}}}
        return await super().graphql(query, variables)

    # ---- the three mutations

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name in ("order_edit_begin", "order_edit_add_variant"):
            self.edits.append((name, copy.deepcopy(variables)))
        if name == "order_edit_begin":
            assert variables["id"] == ORDER
            self.added = []
            return {"data": {"orderEditBegin": {"calculatedOrder": {"id": CALCULATED, "committed": False}, "userErrors": []}}}
        if name == "order_edit_add_variant":
            if self.fail_add:
                raise ShopifyError("Shopify would not price that.")
            assert variables["id"] == CALCULATED and variables["allowDuplicates"] is False
            _, variant = VARIANTS[str(variables["variantId"])]
            self.added.append((variant["id"], int(variables["quantity"])))
            folded: dict[str, int] = {}
            for vid, quantity in self.lines + self.added:
                folded[vid] = folded.get(vid, 0) + quantity
            total = self._total(list(folded.items()))
            return {"data": {"orderEditAddVariant": {
                "calculatedLineItem": {
                    "id": "gid://shopify/CalculatedLineItem/new", "title": VARIANTS[variant["id"]][0]["title"],
                    "variantTitle": variant["title"], "quantity": int(variables["quantity"]),
                    "originalUnitPriceSet": {"shopMoney": {"amount": variant["price"], "currencyCode": "GBP"}},
                },
                "calculatedOrder": {
                    "id": CALCULATED,
                    "subtotalPriceSet": {"shopMoney": {"amount": f"{total - self.SHIPPING:.2f}", "currencyCode": "GBP"}},
                    "totalPriceSet": {"shopMoney": {"amount": f"{total:.2f}", "currencyCode": "GBP"}},
                    "totalOutstandingSet": {"shopMoney": {"amount": f"{max(0.0, total - self.paid):.2f}", "currencyCode": "GBP"}},
                    "lineItems": {"edges": [{"node": {"id": f"gid://shopify/CalculatedLineItem/{i}", "quantity": q, "variant": {"id": v}}}
                                            for i, (v, q) in enumerate(folded.items())]},
                },
                "userErrors": [],
            }}}
        if name == "order_edit_commit":
            if self.fail_mutation or self.refuse_commit:
                raise ShopifyError("Shopify refused it.")
            # The scratch order is applied: the addition folds into the line that has that
            # variant, because allowDuplicates was false.
            folded: dict[str, int] = {}
            for vid, quantity in self.lines + self.added:
                folded[vid] = folded.get(vid, 0) + quantity
            self.lines = list(folded.items())
            self.committed = True
            if self.lose_answer:
                raise ShopifyError("timed out")
            named = "gid://shopify/Order/999" if self.commit_other_order else ORDER
            return {"data": {"orderEditCommit": {"order": {"id": named, "name": "#1930"}, "userErrors": []}}}
        raise AssertionError(f"unexpected mutation {name}")


class Policy:
    carrier = "Royal Mail"
    fulfil_notify = False


@pytest.fixture()
def store():
    s = EditStore()
    shopify_tools.bind(s)
    shopify_writes.bind_policy(lambda: Policy())
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(ORDER)
    s.issue(HOODIE)
    s.issue(BONE)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    text = await dispatch(TOOL, {"order_id": ORDER, "variant_id": HOODIE, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold(engine, proposal):
    _, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_adding_a_line_is_red_irreversible_a_hold_and_one_reviewed_mutation():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete
    assert spec.write.kind == "irreversible" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    assert spec.write.operation == "order_edit_add_line" and spec.write.mutation == "order_edit_commit"
    assert spec.issued_id_args == ("order_id", "variant_id")
    for name, idempotent, root in (
        ("order_edit_begin", True, "orderEditBegin"),
        ("order_edit_add_variant", False, "orderEditAddVariant"),
        ("order_edit_commit", False, "orderEditCommit"),
    ):
        reviewed = REVIEWED_MUTATIONS[name]
        assert reviewed.scope == "write_order_edits" and reviewed.idempotent is idempotent and reviewed.root == root
    assert set(REVIEWED_MUTATIONS["order_edit_add_variant"].variables) == {"id", "variantId", "quantity", "allowDuplicates"}
    assert set(REVIEWED_MUTATIONS["order_edit_commit"].variables) == {"id", "notifyCustomer", "staffNote"}


def test_the_gate_stages_it_only_with_both_ids_issued_and_a_sane_quantity():
    ok = {"order_id": ORDER, "variant_id": HOODIE}
    assert classify(TOOL, ok, issued_ids={ORDER, HOODIE}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, ok, issued_ids={ORDER}).disposition is Disposition.DENY, "the variant must be one that was looked up"
    assert classify(TOOL, ok, issued_ids={HOODIE}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {**ok, "quantity": 0}, issued_ids={ORDER, HOODIE}).disposition is Disposition.DENY
    assert classify(TOOL, {**ok, "quantity": 99}, issued_ids={ORDER, HOODIE}).disposition is Disposition.DENY
    assert classify(TOOL, {**ok, "price": "1.00"}, issued_ids={ORDER, HOODIE}).disposition is Disposition.DENY, "the price is not an argument"
    # A customer id is an issued id and is not an order id.
    assert classify(TOOL, {"order_id": "gid://shopify/Customer/7", "variant_id": HOODIE},
                    issued_ids={"gid://shopify/Customer/7", HOODIE}).disposition is Disposition.DENY


def test_the_steppers_ceiling_and_the_tools_bound_are_the_same_number():
    """The picker's stepper stops at the number the write tool would refuse. Two ceilings in
    two files drift, and the shape of that drift is a button that posts a quantity the Mac
    then rejects — so they are asserted to agree rather than kept in step by hand."""
    from app.presentation import MAX_PICKER_QUANTITY
    from app.tools.shopify_writes import MAX_ADD_QUANTITY

    assert MAX_PICKER_QUANTITY == MAX_ADD_QUANTITY
    assert registry.get(TOOL).input_schema["properties"]["quantity"]["maximum"] == MAX_ADD_QUANTITY


def test_the_read_that_finds_the_variant_is_a_read_and_the_family_declares_both():
    search = registry.get(SEARCH)
    assert search.write is None and search.batch is None and search.tier is Tier.GREEN
    assert classify(SEARCH, {"product": "hoodie"}, issued_ids=set()).disposition is Disposition.EXECUTE_NOW
    from app.capabilities import families

    family = families.get("order_edit")
    assert family is not None and family.operations == ("order_edit_add_line",) and family.scopes == ("write_order_edits",)
    assert set(family.tools) == {SEARCH, TOOL}, "the family owns both, so a missing scope hides only the write"


# --------------------------------------------------------------------------- preparing


async def test_the_two_calculation_mutations_run_and_the_order_is_untouched(store, engine, session):
    text, proposal = await stage(session)
    assert text.startswith("PROPOSED"), text
    assert [name for name, _ in store.edits] == ["order_edit_begin", "order_edit_add_variant"]
    assert store.edits[1][1] == {"id": CALCULATED, "variantId": HOODIE, "quantity": 1, "allowDuplicates": False}
    # Nothing has been committed, and the order still reads exactly as it did.
    assert store.committed is False and store.lines == [(HOODIE, 1)]
    assert not any(name == "order_edit_commit" for name, _ in store.mutations)
    assert proposal.risk == "RED" and proposal.interaction == "hold_to_arm" and proposal.status is ActionStatus.PENDING


async def test_the_card_carries_shopifys_own_arithmetic(store, engine, session):
    _, proposal = await stage(session)
    execution = dict(proposal.execution)
    assert set(execution) == {
        "calculated_order_id", "order_id", "variant_id", "quantity", "line_item_title",
        "unit_price", "subtotal_delta", "new_total", "amount_outstanding",
    }
    # One more £60 hoodie on a £65 order: £125 in total, and the customer owes the £60.
    assert execution["calculated_order_id"] == CALCULATED and execution["quantity"] == 1
    assert execution["unit_price"] == "60.00" and execution["subtotal_delta"] == "60.00"
    assert execution["new_total"] == "125.00" and execution["amount_outstanding"] == "60.00"
    assert proposal.before == {"lines": 1, "total": "65.00", "variant_qty": 1, "cancelled": False, "closed": False}
    # `allowDuplicates` is false, so the addition folds into the line the order already has:
    # the count does not move, and the expectation says so rather than claiming one more.
    assert proposal.expected_after["lines"] == 1 and proposal.expected_after["variant_qty"] == 2
    assert proposal.expected_after["total"] == "125.00"
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Adding"] == "1 x Convict Hoodie (Black / M)"
    assert facts["Unit price"] == "£60.00" and facts["Adds"] == "£60.00 to the order"
    assert facts["New total"] == "£125.00" and facts["Customer owes"] == "£60.00 after this"
    assert facts["Customer emailed"] == "no — tell them yourself"
    assert facts["Customer"] == "Daniel Sear"
    assert "£60.00 more, taking the order to £125.00" in proposal.summary["read_back"]


async def test_a_quantity_of_two_is_priced_as_two(store, engine, session):
    _, proposal = await stage(session, quantity=2)
    execution = dict(proposal.execution)
    assert execution["quantity"] == 2 and execution["subtotal_delta"] == "120.00" and execution["new_total"] == "185.00"
    assert proposal.expected_after["variant_qty"] == 3


async def test_a_cancelled_or_archived_order_is_refused_before_an_edit_is_opened(store, engine, session):
    store.cancelled_at = "2026-09-08T12:00:00Z"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "is cancelled" in text and "nothing can be added" in text
    store.cancelled_at, store.closed_at = None, "2026-09-08T12:00:00Z"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "is archived" in text
    assert store.mutations == [] and session.proposals == [], "nothing was opened and nothing is waiting"


async def test_a_variant_that_is_not_for_sale_is_refused(store, engine, session):
    text, _ = await stage(session, variant_id=BONE)
    assert text.startswith("ERROR") and "not for sale" in text
    assert store.mutations == [] and session.proposals == []


async def test_a_quantity_outside_the_bound_is_refused_before_anything_is_read(store, engine, session):
    for bad in (0, -1, 999):
        text = await dispatch(TOOL, {"order_id": ORDER, "variant_id": HOODIE, "quantity": bad}, session=session, timeout_s=5)
        assert text.startswith(("ERROR", "REFUSED")), text
    assert store.mutations == [] and session.proposals == []


async def test_less_stock_than_asked_for_is_a_caveat_on_the_card_not_a_refusal(store, engine, session):
    _, proposal = await stage(session, quantity=5)
    facts = {f["label"]: f for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Stock"]["value"] == "4 in stock, 5 being added" and facts["Stock"]["tone"] == "warn"


# --------------------------------------------------------------------------- applying


async def test_a_hold_commits_the_edit_once_and_proves_it_by_re_reading_the_order(store, engine, session):
    _, proposal = await stage(session)
    result = await hold(engine, proposal)
    assert result.code == "verified", result.detail
    assert result.spoken == "Added to order 1930. The total is now £125.00."
    commits = [v for name, v in store.mutations if name == "order_edit_commit"]
    assert len(commits) == 1
    assert commits[0]["id"] == CALCULATED and commits[0]["notifyCustomer"] is False
    assert commits[0]["staffNote"] == "Added 1 x Convict Hoodie (CROOKS assistant)"
    assert store.lines == [(HOODIE, 2)] and proposal.status is ActionStatus.VERIFIED
    assert proposal.after == {"lines": 1, "total": "125.00", "variant_qty": 2, "cancelled": False, "closed": False}
    assert proposal.undo_id is None, "there is no undo that puts a paid order back"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len([1 for n, _ in store.mutations if n == "order_edit_commit"]) == 1


async def test_a_tap_without_the_hold_sends_nothing(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.committed is False and proposal.status is ActionStatus.PENDING


async def test_a_line_added_in_admin_meanwhile_makes_it_stale(store, engine, session):
    _, proposal = await stage(session)
    store.lines = [(HOODIE, 1), (CAP, 1)]
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.committed is False and proposal.status is ActionStatus.STALE
    assert result.spoken == "The order changed since this was prepared. Nothing was added."


async def test_an_order_cancelled_between_the_card_and_the_tap_makes_it_stale(store, engine, session):
    _, proposal = await stage(session)
    store.cancelled_at = "2026-09-09T09:00:00Z"
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.committed is False


async def test_a_refusal_from_shopify_leaves_the_order_as_it_was(store, engine, session):
    _, proposal = await stage(session)
    store.refuse_commit = True
    result = await hold(engine, proposal)
    assert result.code in ("failed", "service_unavailable", "unverified", "refused")
    assert store.lines == [(HOODIE, 1)] and proposal.status is not ActionStatus.VERIFIED


async def test_a_lost_answer_is_settled_by_re_reading_the_order(store, engine, session):
    _, proposal = await stage(session)
    store.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified" and store.lines == [(HOODIE, 2)]
    assert len([1 for n, _ in store.mutations if n == "order_edit_commit"]) == 1


async def test_the_verification_is_the_quantity_that_moved_not_the_quantity_that_is_there(store, engine, session):
    """The order already had one of this variant. A proof of "a line with at least the
    quantity asked for" would pass on an order to which nothing was added; this one does not."""
    verify = registry.get(TOOL).write.verify
    before = {"lines": 1, "total": "65.00", "variant_qty": 1, "cancelled": False, "closed": False}
    execution = {"quantity": 1, "new_total": "125.00"}
    assert verify(before, {"variant_qty": 2, "total": "125.00"}, execution)[0] is True
    assert verify(before, {"variant_qty": 1, "total": "65.00"}, execution)[0] is False, "unchanged is not applied"
    ok, note = verify(before, {"variant_qty": 2, "total": "131.00"}, execution)
    assert ok is True and "not the figure on the card" in note, "applied, and the total is not what was priced"


async def test_the_ledger_keeps_the_numbers_and_not_the_customer(store, engine, session):
    _, proposal = await stage(session)
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"quantity": 1, "adds": "60.00", "currency": "GBP"}
    assert "Daniel" not in str(line)


# --------------------------------------------------------------------------- finding it


async def test_the_search_is_confident_only_when_one_variant_matches_every_word(store, engine, session):
    from app.tools.shopify_tools import shopify_variant_search

    one = await shopify_variant_search(product="convict hoodie", colour="black", size="medium")
    assert one["confident"] is True and [c["variant_id"] for c in one["candidates"]] == [HOODIE]
    assert one["candidates"][0]["options"] == ["Black", "M"] and one["candidates"][0]["price_display"] == "£60.00"
    several = await shopify_variant_search(product="hoodie")
    assert several["confident"] is False and len(several["candidates"]) == 2
    none = await shopify_variant_search(product="convict hoodie", colour="purple")
    assert none["candidates"] == [] and none["confident"] is False and "No variant matches" in none["note"]
    browse = await shopify_variant_search()
    assert len(browse["candidates"]) == 3 and browse["confident"] is False, "browsing is never confident"
    assert browse["candidates"][1]["for_sale"] is False, "the sold-out variant is shown, and shown as such"


async def test_the_search_result_issues_the_variant_ids_it_returned(store, engine, session):
    fresh = Session(session_id="c2")
    await dispatch(SEARCH, {"product": "hoodie"}, session=fresh, timeout_s=5)
    assert HOODIE in fresh.issued_ids and BONE in fresh.issued_ids
    assert CAP not in fresh.issued_ids, "only what was actually returned"


# --------------------------------------------------------------------- the tablet's path


def _ctx(session, branch, **args):
    from app.commands import Ctx

    return Ctx(runtime=None, session=session, branch=branch, args={k: str(v) for k, v in args.items()})


@pytest.fixture()
def branch(session):
    b = session.branch()
    b.visit("order", ORDER, "#1930")
    return b


def test_the_tablet_posts_ids_and_an_integer_and_never_an_execution_argument(session, branch):
    from app import commands

    outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=ORDER, variant_id=HOODIE, quantity=2))
    assert outcome.ok, outcome.detail
    staged = outcome.changed["stage"]
    assert staged["tool"] == TOOL
    assert staged["args"] == {"order_id": ORDER, "variant_id": HOODIE, "quantity": 2}
    # Everything the mutation is sent with — the calculated order, the price, the total, what
    # the customer owes — is absent, because the Mac has not read it yet.
    assert set(staged["args"]) == {"order_id", "variant_id", "quantity"}
    assert isinstance(staged["args"]["quantity"], int)
    # And a price posted alongside is ignored: only the three are read out of the form.
    with_extra = commands.run("order_edit.stage", _ctx(session, branch, order_id=ORDER, variant_id=HOODIE, quantity=1, new_total="1.00", unit_price="0.01"))
    assert with_extra.changed["stage"]["args"] == {"order_id": ORDER, "variant_id": HOODIE, "quantity": 1}


def test_the_staging_command_refuses_an_id_this_conversation_was_never_given(session, branch):
    from app import commands

    other = commands.run("order_edit.stage", _ctx(session, branch, order_id=ORDER, variant_id="gid://shopify/ProductVariant/1"))
    assert not other.ok and other.code == "unknown_variant"
    stranger = Session(session_id="c3")
    stranger.branch().visit("order", ORDER, "#1930")
    refused = commands.run("order_edit.stage", _ctx(stranger, stranger.branch(), order_id=ORDER, variant_id=HOODIE))
    assert not refused.ok and refused.code == "not_held"


def test_the_quantity_is_refused_rather_than_clamped(session, branch):
    from app import commands

    for bad in ("0", "21", "two", "1.5", "-1"):
        outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=ORDER, variant_id=HOODIE, quantity=bad))
        assert not outcome.ok and outcome.code == "bad_quantity", f"{bad!r} was accepted"
    # An absent or empty field is the ordinary case of asking for one, not a typo: the
    # stepper starts at one and a form that omits it means the same thing.
    for absent in ({}, {"quantity": ""}):
        outcome = commands.run("order_edit.stage", _ctx(session, branch, order_id=ORDER, variant_id=HOODIE, **absent))
        assert outcome.ok and outcome.changed["stage"]["args"]["quantity"] == 1


def test_the_picker_command_names_the_recipe_and_only_the_open_order(session, branch):
    from app import commands

    outcome = commands.run("order_edit.find", _ctx(session, branch, product="convict hoodie", colour="black", size="medium"))
    assert outcome.ok and outcome.changed["recipe"] == "order_add_item"
    assert outcome.changed["slots"] == {"product": "convict hoodie", "colour": "black", "size": "medium"}
    assert "stage" not in outcome.changed, "finding stages nothing"
    wrong = commands.run("order_edit.find", _ctx(session, branch, order_id="gid://shopify/Order/1"))
    assert not wrong.ok and wrong.code == "wrong_order"
    empty = Session(session_id="c4")
    nothing = commands.run("order_edit.find", _ctx(empty, empty.branch(), product="hoodie"))
    assert not nothing.ok and nothing.code == "no_entity", "no order open, nothing to add to"


def test_both_commands_are_touch_only_because_no_sentence_can_reach_them():
    from app import commands
    from app.fastpath.intent import family as intent_family
    from app.fastpath.intent import resolve, score, signals_for

    for name in ("order_edit.find", "order_edit.stage"):
        spec = commands.get(name)
        assert spec is not None and spec.voice is False and spec.touch is True

    # The reachability this family is honest about: `intent.resolve` returns no family at all
    # for a sentence carrying a mutation signal, and "add" is one. So the family matches the
    # signals of the request when it is scored — and it is never scored.
    added = intent_family("order_add_item")
    assert added is not None, "the family is registered"
    branch = type("B", (), {"entity": {"kind": "order", "ref": ORDER}, "set_id": "", "workflow": None, "resolutions": {}})()
    sentence = "add a black medium convict hoodie to this order"
    sig = signals_for(sentence, branch=branch)
    assert sig.mutation is True and score(added, sig) > 0
    assert resolve(sentence, branch=branch).family == "", "and can still never win"
    assert resolve(sentence, branch=branch).reason == "asks for a change"
    # With no order open the family is ruled out, which is the brief's other rule.
    bare = type("B", (), {"entity": None, "set_id": "", "workflow": None, "resolutions": {}})()
    assert score(added, signals_for("add a hoodie to this order", branch=bare)) == 0.0


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

    granted = Runtime({"write_order_edits"})
    assert (await order_edit._probe(granted))["state"] == "READY"
    missing = Runtime({"write_orders"})
    probed = await order_edit._probe(missing)
    assert probed["state"] == "MISSING_SCOPE" and probed["scope"] == "write_order_edits"
    assert "write_order_edits" in probed["detail"]

    # MISSING_SCOPE withholds the family's WRITE tool from the model and keeps its read.
    missing.family_states_table = {"order_edit": {"state": "MISSING_SCOPE"}}
    withheld = missing.withheld_by_family()
    assert TOOL in withheld and SEARCH not in withheld


async def test_a_shopify_that_does_not_answer_is_not_a_missing_grant():
    class Broken:
        shopify = type("S", (), {"access_scopes": staticmethod(lambda: _boom())})()

    async def _boom():
        raise ShopifyError("not answering")

    probed = await order_edit._probe(Broken())
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE" and "ShopifyError" in probed["detail"]
