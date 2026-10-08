"""A custom item on an existing order (the owner's decision 8, 1 October 2026: "custom item on
an existing order: yes"): RED, a hold, priced by Shopify before the owner authorises it.

"Add a £15 rush alteration to order 1930" is the same order edit as adding a variant
(tests/test_order_edit.py) with `orderEditAddCustomItem` in place of `orderEditAddVariant`.
The store here is a fake whose mutations go through the REAL `ShopifyClient.mutate` — the
reviewed variable set, the types, the string bound and the price's reviewed shape are all
checked exactly as they are in production — and stop at the one seam below it, `_post`, which
answers as Shopify would. Nothing reaches a network and no credential is involved.

What these hold:

* PREPARE runs `orderEditBegin` and `orderEditAddCustomItem` and never the commit, and the
  card's new total and what the customer owes are Shopify's figures, not the tool's;
* the price is in the order's own currency, read from the order — never an argument;
* the commit sends `notifyCustomer: false` and a staff note built from what was stored;
* the proof is a custom line with that title that moved by the quantity, and a wrong total is
  proven-applied with a warning;
* every bad title, price and quantity, and a cancelled, archived or multi-currency order, is
  refused in words before anything is opened;
* the gate stages it for the owner and never runs it, and the team cannot confirm it.
"""

from __future__ import annotations

import copy
import re

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import (
    MAX_CUSTOM_LINE_PRICE,
    MAX_CUSTOM_TITLE_CHARS,
    REVIEWED_MUTATIONS,
    ShopifyClient,
)
from app.session.models import Session
from app.tools import registry, shopify_tools, shopify_writes
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his. Production's default, and every test's that does not say this, is no
# authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_order_add_custom_item"
OPERATION = "order_edit_add_custom_line"
MUTATION = "order_edit_add_custom_item"
HOODIE = "gid://shopify/ProductVariant/9102"      # the order's one catalogue line, £60.00
CALCULATED = "gid://shopify/CalculatedOrder/1930"
RUSH = "Rush alteration"

# Which reviewed mutation a root field belongs to, for the seam below `mutate`.
_BY_ROOT = {REVIEWED_MUTATIONS[name].root: name for name in ("order_edit_begin", MUTATION, "order_edit_commit")}


class CustomItemStore(FakeStore):
    """An order with one £60 hoodie and £5 postage, paid in full, in pounds.

    The money follows the fixture's own rule — the total is the lines plus postage, and what
    the customer owes after an edit is the new total less what has been paid — and, when
    `tax_rate` is set, Shopify adds tax on a taxable custom line: arithmetic the tool never
    does, so a card that shows it can only have read it from Shopify.
    """

    SHIPPING = 5.0

    def __init__(self) -> None:
        super().__init__(note="")
        self.lines: list[dict] = [{"variant": HOODIE, "title": "Convict Hoodie", "quantity": 1, "price": 60.0}]
        self.currency = "GBP"
        self.presentment = "GBP"
        self.cancelled_at: str | None = None
        self.closed_at: str | None = None
        self.paid = 65.0
        self.tax_rate = 0.0
        self.added: list[dict] = []          # what has been put on the scratch order
        self.committed = False
        self.refuse_commit = False
        self.commit_drops_line = False       # Shopify answers the commit and the line is not there
        self.commit_total_bump = 0.0         # the re-read total differs from the priced one by this
        self.price_echo: str | None = None   # what Shopify says it priced the line at, if not what it was sent
        self.title_echo: str | None = None   # the title Shopify gives the calculated line, if not what it was sent
        self.currency_echo: str | None = None   # the currency Shopify says it priced the line in, if not the one sent
        self.more_lines = False              # the order has more lines than one read returns

    # ---- reads

    def _total(self, lines: list[dict]) -> float:
        goods = sum(line["price"] * line["quantity"] * (1 + (self.tax_rate if line.get("taxable") else 0.0)) for line in lines)
        return round(goods + self.SHIPPING + self.commit_total_bump * self.committed, 2)

    def _order(self) -> dict:
        node = super()._order()
        total = self._total(self.lines)
        node.update({
            "cancelledAt": self.cancelled_at, "closedAt": self.closed_at,
            "currencyCode": self.currency, "presentmentCurrencyCode": self.presentment,
            "currentTotalPriceSet": {"shopMoney": {"amount": f"{total:.2f}", "currencyCode": self.currency}},
            "totalOutstandingSet": {"shopMoney": {"amount": f"{max(0.0, total - self.paid):.2f}", "currencyCode": self.currency}},
            "lineItems": {"pageInfo": {"hasNextPage": self.more_lines}, "edges": [
                {"node": {"id": f"gid://shopify/LineItem/{i}", "title": line["title"], "quantity": line["quantity"],
                          "currentQuantity": line["quantity"], "variant": {"id": line["variant"]} if line["variant"] else None}}
                for i, line in enumerate(self.lines)
            ]},
        })
        return node

    # ---- the mutations: the real `mutate`, and Shopify's answers below it

    async def mutate(self, name: str, variables: dict) -> dict:
        return await ShopifyClient.mutate(self, name, variables)

    async def _post(self, query: str, variables: dict | None = None, *, mutation: bool = False, root: str = "") -> dict:
        assert mutation, "reads go through graphql(); only a reviewed mutation reaches this seam"
        name = _BY_ROOT[root]
        assert query == REVIEWED_MUTATIONS[name].document, "the reviewed document, and only that"
        variables = copy.deepcopy(variables or {})
        self.mutations.append((name, variables))
        if name == "order_edit_begin":
            assert variables["id"] == ORDER
            self.added = []
            return {"data": {"orderEditBegin": {"calculatedOrder": {"id": CALCULATED, "committed": False}, "userErrors": []}}}
        if name == MUTATION:
            assert variables["id"] == CALCULATED
            title = self.title_echo if self.title_echo is not None else variables["title"]
            line = {"variant": None, "title": title, "quantity": int(variables["quantity"]),
                    "price": float(variables["price"]["amount"]), "taxable": variables["taxable"]}
            self.added.append(line)
            total = self._total(self.lines + self.added)
            money = lambda amount: {"shopMoney": {"amount": amount, "currencyCode": variables["price"]["currencyCode"]}}  # noqa: E731
            return {"data": {"orderEditAddCustomItem": {
                "calculatedLineItem": {
                    "id": "gid://shopify/CalculatedLineItem/new", "title": title, "quantity": line["quantity"],
                    "originalUnitPriceSet": {"shopMoney": {
                        "amount": self.price_echo or variables["price"]["amount"],
                        "currencyCode": self.currency_echo or variables["price"]["currencyCode"]}},
                },
                "calculatedOrder": {
                    "id": CALCULATED,
                    "subtotalPriceSet": money(f"{total - self.SHIPPING:.2f}"),
                    "totalPriceSet": money(f"{total:.2f}"),
                    "totalOutstandingSet": money(f"{max(0.0, total - self.paid):.2f}"),
                    "lineItems": {"edges": [
                        {"node": {"id": f"gid://shopify/CalculatedLineItem/{i}", "title": x["title"], "quantity": x["quantity"],
                                  "variant": {"id": x["variant"]} if x["variant"] else None}}
                        for i, x in enumerate(self.lines + self.added)
                    ]},
                },
                "userErrors": [],
            }}}
        if name == "order_edit_commit":
            if self.refuse_commit:
                raise shopify_writes.ShopifyError("Shopify refused it.")
            if not self.commit_drops_line:
                self.lines = self.lines + self.added
            self.committed = True
            if self.lose_answer:
                raise shopify_writes.ShopifyError("timed out")
            return {"data": {"orderEditCommit": {"order": {"id": ORDER, "name": "#1930"}, "userErrors": []}}}
        raise AssertionError(f"unexpected mutation {name}")

    def sent(self, name: str) -> list[dict]:
        return [v for n, v in self.mutations if n == name]


class Policy:
    carrier = "Royal Mail"
    fulfil_notify = False


@pytest.fixture()
def store():
    s = CustomItemStore()
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
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    text = await dispatch(TOOL, {"order_id": ORDER, "title": RUSH, "price": 15, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold(engine, proposal):
    _, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


def facts(proposal) -> dict[str, str]:
    return {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}


# --------------------------------------------------------------------------- declaration


def test_a_custom_item_is_red_irreversible_a_hold_and_commits_through_the_reviewed_edit():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete
    assert spec.write.kind == "irreversible" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    assert spec.write.operation == OPERATION and spec.write.mutation == "order_edit_commit"
    assert spec.issued_id_args == ("order_id",)
    reviewed = REVIEWED_MUTATIONS[MUTATION]
    assert reviewed.scope == "write_order_edits" and reviewed.idempotent is False and reviewed.root == "orderEditAddCustomItem"
    assert reviewed.variables == {"id": str, "title": str, "price": dict, "quantity": int, "taxable": bool, "requiresShipping": bool}
    assert reviewed.max_chars == MAX_CUSTOM_TITLE_CHARS
    # The tool's bounds and the reviewed shape's are the same numbers.
    schema = spec.input_schema["properties"]
    assert schema["title"]["maxLength"] == MAX_CUSTOM_TITLE_CHARS and schema["price"]["maximum"] == MAX_CUSTOM_LINE_PRICE
    assert schema["quantity"]["maximum"] == shopify_writes.MAX_ADD_QUANTITY
    assert set(schema) == {"order_id", "title", "price", "quantity", "taxable", "requires_shipping"}, "never a currency"


def test_the_reviewed_document_matches_its_root_and_its_declared_variables():
    """The document is read as text, the way Shopify will read it: the variables it declares
    are exactly the reviewed set, each is passed to the root field under the argument of the
    same name, and the root is the one the refusal logic reads."""
    reviewed = REVIEWED_MUTATIONS[MUTATION]
    document = " ".join(reviewed.document.split())
    header = re.match(r"mutation (\w+)\((.*?)\) \{ (\w+)\((.*?)\) \{", document)
    assert header is not None, document
    _operation, declared, root, passed = header.groups()
    declarations = dict(re.findall(r"\$(\w+): ([\w!]+)", declared))
    assert declarations == {"id": "ID!", "title": "String!", "price": "MoneyInput!", "quantity": "Int!",
                            "taxable": "Boolean!", "requiresShipping": "Boolean!"}
    assert set(declarations) == set(reviewed.variables)
    assert root == reviewed.root == "orderEditAddCustomItem"
    arguments = dict(re.findall(r"(\w+): \$(\w+)", passed))
    assert arguments == {name: name for name in reviewed.variables}, "every variable is passed, under its own name"
    assert "notifyCustomer" not in document and "locationId" not in document
    # The selection is what the tool reads: the priced line, and the edited order's money and lines.
    for field in ("calculatedLineItem", "originalUnitPriceSet", "calculatedOrder", "totalPriceSet",
                  "totalOutstandingSet", "lineItems", "userErrors"):
        assert field in document, field


def test_the_reviewed_price_shape_takes_one_bounded_amount_in_one_currency_and_nothing_looser():
    ok = REVIEWED_MUTATIONS[MUTATION].validate
    assert ok("price", {"amount": "15.00", "currencyCode": "GBP"})
    assert ok("price", {"amount": f"{MAX_CUSTOM_LINE_PRICE:.2f}", "currencyCode": "EUR"})
    for bad in (
        {"amount": "0.00", "currencyCode": "GBP"}, {"amount": "-1.00", "currencyCode": "GBP"},
        {"amount": "1000.01", "currencyCode": "GBP"}, {"amount": "15.001", "currencyCode": "GBP"},
        {"amount": 15.0, "currencyCode": "GBP"}, {"amount": "15.00", "currencyCode": "gbp"},
        {"amount": "15.00"}, {"amount": "15.00", "currencyCode": "GBP", "extra": 1}, "15.00",
    ):
        assert not ok("price", bad), bad


async def test_a_shape_the_review_did_not_pass_never_leaves(store):
    """The real `mutate` refuses before anything is posted: a price in the wrong shape, a title
    over the bound, a variable set that is not the reviewed one."""
    from app.clients.shopify import ShopifyWithheld

    good = {"id": CALCULATED, "title": RUSH, "price": {"amount": "15.00", "currencyCode": "GBP"},
            "quantity": 1, "taxable": True, "requiresShipping": False}
    for bad in (
        {**good, "price": {"amount": "15", "currencyCode": "GBP", "note": "x"}},
        {**good, "title": "x" * (MAX_CUSTOM_TITLE_CHARS + 1)},
        {**good, "quantity": True},
        {k: v for k, v in good.items() if k != "taxable"},
        {**good, "notifyCustomer": True},
    ):
        with pytest.raises(ShopifyWithheld):
            await store.mutate(MUTATION, bad)
    assert store.mutations == []


# --------------------------------------------------------------------------- the gate


def test_the_gate_stages_it_for_the_owner_and_never_runs_it():
    ok = {"order_id": ORDER, "title": RUSH, "price": 15}
    decision = classify(TOOL, ok, issued_ids={ORDER})
    assert decision.disposition is Disposition.STAGE_FOR_OWNER and decision.stages and not decision.executes
    assert decision.tier is Tier.RED
    full = {**ok, "quantity": 2, "taxable": False, "requires_shipping": True}
    assert classify(TOOL, full, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    # Never directly, whatever it is asked.
    for args in (ok, full, {**ok, "price": 0}, {}):
        assert classify(TOOL, args, issued_ids={ORDER}).disposition is not Disposition.EXECUTE_NOW
    assert classify(TOOL, ok, issued_ids=set()).disposition is Disposition.DENY, "the order must be one that was looked up"
    assert classify(TOOL, {**ok, "order_id": "gid://shopify/Customer/7"},
                    issued_ids={"gid://shopify/Customer/7"}).disposition is Disposition.DENY
    for bad in ({**ok, "currency": "USD"}, {**ok, "price": 0}, {**ok, "price": MAX_CUSTOM_LINE_PRICE + 0.01},
                {**ok, "price": "15"}, {**ok, "title": ""}, {**ok, "title": "x" * (MAX_CUSTOM_TITLE_CHARS + 1)},
                {**ok, "quantity": 0}, {**ok, "quantity": 21}, {"order_id": ORDER, "title": RUSH}, {"order_id": ORDER, "price": 15}):
        assert classify(TOOL, bad, issued_ids={ORDER}).disposition is Disposition.DENY, bad


def test_the_team_cannot_call_it_or_confirm_it():
    """The team build lets staff confirm five operations; this is not one of them, and nothing
    in app/people names it."""
    from app.people import staff

    assert TOOL not in staff.TOOLS and TOOL not in staff.WRITES and not staff.may_call(TOOL)
    assert OPERATION not in staff.OPERATIONS and OPERATION not in staff.OPERATIONS_WITH_UNDO
    assert not staff.may_commit(OPERATION) and not staff.may_commit(f"{OPERATION}_undo")
    assert len(staff.OPERATIONS) == 5


def test_the_family_owns_it_and_a_missing_scope_withholds_it():
    from app.capabilities import families
    from app.families import order_edit  # registers the family

    family = families.get("order_edit")
    assert OPERATION in family.operations and TOOL in family.tools and family.scopes == ("write_order_edits",)
    assert order_edit.CUSTOM_OPERATION == OPERATION and order_edit.CUSTOM_WRITE_TOOL == TOOL

    from app.runtime import Runtime as Real

    class Runtime:
        family_states_table = {"order_edit": {"state": "MISSING_SCOPE"}}
        capability_states: dict = {}

        def withheld_by_family(self):
            return Real.withheld_by_family(self)

    assert TOOL in Runtime().withheld_by_family()


# --------------------------------------------------------------------------- preparing


async def test_prepare_opens_and_prices_the_edit_and_never_commits(store, engine, session):
    text, proposal = await stage(session)
    assert text.startswith("PROPOSED"), text
    assert [name for name, _ in store.mutations] == ["order_edit_begin", MUTATION]
    assert store.sent(MUTATION) == [{
        "id": CALCULATED, "title": RUSH, "price": {"amount": "15.00", "currencyCode": "GBP"},
        "quantity": 1, "taxable": True, "requiresShipping": False,
    }]
    assert store.committed is False and len(store.lines) == 1 and store.sent("order_edit_commit") == []
    assert proposal.operation == OPERATION and proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    assert proposal.status is ActionStatus.PENDING


async def test_the_cards_new_total_and_what_the_customer_owes_are_shopifys(store, engine, session):
    """Shopify adds tax on the taxable line here — arithmetic the tool never does — so a card
    that shows £83.00 and £18.00 read them from Shopify's calculated order."""
    store.tax_rate = 0.2
    _, proposal = await stage(session)
    execution = dict(proposal.execution)
    assert set(execution) == {
        "calculated_order_id", "order_id", "title", "quantity", "unit_price", "currency", "taxable",
        "requires_shipping", "subtotal_delta", "new_total", "amount_outstanding",
    }
    assert execution["new_total"] == "83.00" and execution["amount_outstanding"] == "18.00"
    assert execution["unit_price"] == "15.00" and execution["subtotal_delta"] == "15.00" and execution["currency"] == "GBP"
    assert proposal.before == {"lines": 1, "total": "65.00", "custom_qty": 0, "cancelled": False, "closed": False}
    assert proposal.expected_after == {"lines": 2, "total": "83.00", "custom_qty": 1, "cancelled": False, "closed": False}
    card = facts(proposal)
    assert card["Adding"] == "1 x Rush alteration" and card["Unit price"] == "£15.00"
    assert card["Adds"] == "£18.00 to the order" and card["Treated as"] == "taxable · needs no shipping"   # Shopify's change, tax and all
    assert card["New total"] == "£83.00" and card["Customer owes"] == "£18.00 after this"
    assert card["Customer emailed"] == "no — tell them yourself" and card["Customer"] == "Daniel Stub"
    assert len(card) <= 8, "the card prints eight facts at most"
    assert "£18.00 more, taking the order to £83.00" in proposal.summary["read_back"]
    words = registry.get(TOOL).write.present(proposal)
    assert words["done_title"] == "Custom item added" and "cannot be undone" in words["detail"]


async def test_a_quantity_and_the_two_flags_are_sent_as_asked_and_said_on_the_card(store, engine, session):
    _, proposal = await stage(session, quantity=3, taxable=False, requires_shipping=True, price=12.5)
    sent = store.sent(MUTATION)[0]
    assert sent["quantity"] == 3 and sent["taxable"] is False and sent["requiresShipping"] is True
    assert sent["price"] == {"amount": "12.50", "currencyCode": "GBP"}
    assert proposal.execution["subtotal_delta"] == "37.50" and proposal.execution["new_total"] == "102.50"
    assert proposal.expected_after["custom_qty"] == 3
    assert facts(proposal)["Treated as"] == "not taxable · needs shipping"


async def test_the_title_is_trimmed_before_it_is_sent(store, engine, session):
    _, proposal = await stage(session, title="   Rush alteration  ")
    assert store.sent(MUTATION)[0]["title"] == RUSH and proposal.execution["title"] == RUSH


async def test_the_currency_is_the_orders_own(store, engine, session):
    store.currency = store.presentment = "EUR"
    _, proposal = await stage(session)
    assert store.sent(MUTATION)[0]["price"] == {"amount": "15.00", "currencyCode": "EUR"}
    assert proposal.execution["currency"] == "EUR" and facts(proposal)["Unit price"] == "€15.00"


async def test_an_order_paid_in_another_currency_or_with_none_stated_is_refused(store, engine, session):
    store.presentment = "EUR"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "paid in EUR, not the shop's GBP" in text and "Admin" in text, text
    store.presentment = ""
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "did not say what currency" in text, text
    assert store.mutations == [] and session.proposals == [], "nothing was opened and nothing is waiting"


async def test_a_cancelled_or_archived_order_is_refused_before_an_edit_is_opened(store, engine, session):
    store.cancelled_at = "2026-09-08T12:00:00Z"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "is cancelled" in text and "nothing can be added" in text
    store.cancelled_at, store.closed_at = None, "2026-09-08T12:00:00Z"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "is archived" in text
    assert store.mutations == [] and session.proposals == []


async def test_shopify_pricing_the_line_otherwise_is_refused_and_nothing_is_offered(store, engine, session):
    store.price_echo = "1500.00"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "not £15.00" in text and "nothing was changed" in text, text
    assert session.proposals == [] and store.sent("order_edit_commit") == []


# --------------------------------------------------------------------------- refusals, in words


BAD_TITLES = [
    ("", "needs a title"),
    ("   ", "needs a title"),
    (None, "needs a title"),
    ("Rush\nalteration", "control character"),
    ("Rush\x00", "control character"),
    ("Rush ‮alteration", "control character"),
    ("<b>Rush</b>", "cannot contain '<'"),
    ("x" * (MAX_CUSTOM_TITLE_CHARS + 1), f"at most {MAX_CUSTOM_TITLE_CHARS} characters"),
]
BAD_PRICES = [
    (0, "more than zero"),
    (-5, "more than zero"),
    ("0.00", "more than zero"),
    (MAX_CUSTOM_LINE_PRICE + 0.01, "at most 1,000.00 a unit"),
    (10_000, "at most 1,000.00 a unit"),
    (15.999, "at most two decimal places"),
    ("15.005", "at most two decimal places"),
    ("fifteen", "an amount of money"),
    (True, "an amount of money"),
    (None, "an amount of money"),
    (float("nan"), "an amount of money"),
    (float("inf"), "an amount of money"),
]
BAD_QUANTITIES = [(0, "between 1 and 20"), (-1, "between 1 and 20"), (21, "between 1 and 20"),
                  ("two", "whole number"), (1.5, "whole number"), (True, "whole number")]


@pytest.mark.parametrize("title, words", BAD_TITLES)
async def test_a_title_that_is_not_one_is_refused_in_words(title, words, store):
    with pytest.raises(ToolError, match=re.escape(words)):
        await shopify_writes.shopify_order_add_custom_item(order_id=ORDER, title=title, price=15)
    assert store.reads == 0 and store.mutations == []


@pytest.mark.parametrize("price, words", BAD_PRICES)
async def test_a_price_that_is_not_one_is_refused_in_words(price, words, store):
    with pytest.raises(ToolError, match=re.escape(words)):
        await shopify_writes.shopify_order_add_custom_item(order_id=ORDER, title=RUSH, price=price)
    assert store.reads == 0 and store.mutations == []


@pytest.mark.parametrize("quantity, words", BAD_QUANTITIES)
async def test_a_quantity_outside_the_bound_is_refused_in_words(quantity, words, store):
    with pytest.raises(ToolError, match=re.escape(words)):
        await shopify_writes.shopify_order_add_custom_item(order_id=ORDER, title=RUSH, price=15, quantity=quantity)
    assert store.reads == 0 and store.mutations == []


async def test_the_two_flags_must_be_yes_or_no(store):
    with pytest.raises(ToolError, match="yes or no"):
        await shopify_writes.shopify_order_add_custom_item(order_id=ORDER, title=RUSH, price=15, taxable="yes")
    with pytest.raises(ToolError, match="yes or no"):
        await shopify_writes.shopify_order_add_custom_item(order_id=ORDER, title=RUSH, price=15, requires_shipping=1)
    assert store.reads == 0 and store.mutations == []


async def test_through_the_dispatcher_a_bad_call_is_refused_and_nothing_is_read(store, engine, session):
    for args in ({"price": 0}, {"price": 5000}, {"title": "x" * 61}, {"quantity": 0}, {"currency": "USD"},
                 {"price": 15.999}, {"title": "Rush\nalteration"}):
        text, _ = await stage(session, **args)
        assert text.startswith(("ERROR", "REFUSED (")), (args, text)
    assert store.reads == 0 and store.mutations == [] and session.proposals == []


async def test_a_price_with_whole_pence_is_accepted_however_it_is_written(store, engine, session):
    for price, sent in ((15, "15.00"), (15.5, "15.50"), (0.01, "0.01"), (MAX_CUSTOM_LINE_PRICE, "1000.00")):
        store.mutations.clear()
        text, _ = await stage(session, price=price)
        assert text.startswith("PROPOSED"), (price, text)
        assert store.sent(MUTATION)[0]["price"]["amount"] == sent


# --------------------------------------------------------------------------- applying


async def test_a_hold_commits_once_without_emailing_and_with_a_stored_staff_note(store, engine, session):
    _, proposal = await stage(session)
    result = await hold(engine, proposal)
    assert result.code == "verified", result.detail
    assert result.spoken == "Added to order 1930. The total is now £80.00."
    commits = store.sent("order_edit_commit")
    assert commits == [{"id": CALCULATED, "notifyCustomer": False,
                        "staffNote": "Added 1 x Rush alteration (custom item, CROOKS assistant)"}]
    assert [line["title"] for line in store.lines] == ["Convict Hoodie", RUSH] and proposal.status is ActionStatus.VERIFIED
    assert proposal.after == {"lines": 2, "total": "80.00", "custom_qty": 1, "cancelled": False, "closed": False}
    assert proposal.undo_id is None, "there is no undo that puts a paid order back"
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.sent("order_edit_commit")) == 1


async def test_the_staff_note_is_built_from_what_was_stored_not_from_anything_new(store, engine, session):
    long_title = "Taper both legs, hem 2cm, rush for Friday collection, pls"
    _, proposal = await stage(session, title=long_title, quantity=20)
    await hold(engine, proposal)
    note = store.sent("order_edit_commit")[0]["staffNote"]
    assert note == f"Added 20 x {long_title} (custom item, CROOKS assistant)" and len(note) <= 200


async def test_a_tap_without_the_hold_sends_nothing(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.committed is False and proposal.status is ActionStatus.PENDING


async def test_a_line_added_in_admin_meanwhile_makes_it_stale(store, engine, session):
    _, proposal = await stage(session)
    store.lines = store.lines + [{"variant": None, "title": RUSH, "quantity": 1, "price": 15.0}]
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.committed is False and proposal.status is ActionStatus.STALE
    assert result.spoken == "The order changed since this was prepared. Nothing was added."
    assert store.sent("order_edit_commit") == []


async def test_an_order_cancelled_between_the_card_and_the_tap_makes_it_stale(store, engine, session):
    _, proposal = await stage(session)
    store.cancelled_at = "2026-09-09T09:00:00Z"
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.committed is False and store.sent("order_edit_commit") == []


async def test_a_commit_that_leaves_no_such_line_is_not_called_done(store, engine, session):
    _, proposal = await stage(session)
    store.commit_drops_line = True
    result = await hold(engine, proposal)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken == "I couldn't confirm the custom item was added. Check the order before asking again."


async def test_a_wrong_total_is_applied_with_a_warning(store, engine, session):
    _, proposal = await stage(session)
    store.commit_total_bump = 1.0
    result = await hold(engine, proposal)
    assert result.code == "verified" and "not the figure on the card" in result.spoken


async def test_a_lost_answer_is_settled_by_re_reading_the_order(store, engine, session):
    _, proposal = await stage(session)
    store.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified" and [line["title"] for line in store.lines][-1] == RUSH
    assert len(store.sent("order_edit_commit")) == 1


async def test_the_proof_is_the_titled_custom_line_that_moved_by_the_quantity():
    """The order already had one rush alteration: a proof of "a line with that title" would
    pass on an order to which nothing was added; this one does not. And a catalogue line with
    the same title, or a custom line with another title, is not this line."""
    verify = registry.get(TOOL).write.verify
    before = {"lines": 2, "total": "80.00", "custom_qty": 1, "cancelled": False, "closed": False}
    execution = {"quantity": 2, "new_total": "110.00"}
    assert verify(before, {"custom_qty": 3, "total": "110.00"}, execution) == (True, "")
    assert verify(before, {"custom_qty": 1, "total": "80.00"}, execution)[0] is False, "unchanged is not applied"
    assert verify(before, {"custom_qty": 2, "total": "95.00"}, execution)[0] is False, "one of two is not applied"
    ok, note = verify(before, {"custom_qty": 3, "total": "111.00"}, execution)
    assert ok is True and "not the figure on the card" in note, "applied, and the total is not what was priced"

    node = {"currentTotalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "GBP"}}, "lineItems": {"edges": [
        {"node": {"id": "gid://shopify/LineItem/1", "title": RUSH, "quantity": 2, "currentQuantity": 2, "variant": None}},
        {"node": {"id": "gid://shopify/LineItem/2", "title": RUSH, "quantity": 1, "currentQuantity": 1, "variant": {"id": HOODIE}}},
        {"node": {"id": "gid://shopify/LineItem/3", "title": "Gift wrap", "quantity": 1, "currentQuantity": 1, "variant": None}},
        {"node": {"id": "gid://shopify/LineItem/4", "title": RUSH, "quantity": 1, "currentQuantity": 0, "variant": None}},
    ]}}
    fingerprint = shopify_writes.order_custom_item_fingerprint(node, RUSH)
    assert fingerprint == {"lines": 3, "total": "100.00", "custom_qty": 2, "cancelled": False, "closed": False}


async def test_the_ledger_keeps_the_numbers_and_not_the_customer_or_the_title(store, engine, session):
    _, proposal = await stage(session)
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"quantity": 1, "adds": "15.00", "currency": "GBP"}
    assert "Daniel" not in str(line)


# --------------------------------------------------------------------------- the review's gaps


async def test_an_order_whose_total_alone_moved_meanwhile_makes_it_stale(store, engine, session):
    """Only the total moves: the hoodie's quantity changed in Admin between the card and the hold.
    The CalculatedOrder was priced on the old order and must not be committed."""
    _, proposal = await stage(session)
    store.lines = [{**store.lines[0], "quantity": 2}]
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.committed is False and store.sent("order_edit_commit") == []


async def test_a_title_shopify_stores_differently_is_the_one_carried_and_proved(store, engine, session):
    store.title_echo = "Rush Alteration"
    _, proposal = await stage(session)
    assert facts(proposal)["Adding"] == "1 x Rush Alteration"
    await hold(engine, proposal)
    assert proposal.status is ActionStatus.VERIFIED
    assert store.sent("order_edit_commit")[0]["staffNote"] == "Added 1 x Rush Alteration (custom item, CROOKS assistant)"


@pytest.mark.parametrize("price_echo, currency_echo", [("15.50", None), ("15.01", None), (None, "EUR")])
async def test_an_echo_off_by_pence_or_in_another_currency_is_refused(price_echo, currency_echo, store, engine, session):
    store.price_echo, store.currency_echo = price_echo, currency_echo
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "nothing was changed" in text, text
    assert session.proposals == [] and store.sent("order_edit_commit") == []


def test_a_proof_for_nothing_added_is_never_a_proof():
    verify = registry.get(TOOL).write.verify
    before = {"custom_qty": 1, "total": "80.00"}
    assert verify(before, {"custom_qty": 1, "total": "80.00"}, {"quantity": 0, "new_total": "80.00"})[0] is False


async def test_an_order_with_more_lines_than_one_read_is_refused_before_an_edit_is_opened(store, engine, session):
    store.more_lines = True
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "add a custom item to it in Admin" in text, text
    assert store.mutations == [] and session.proposals == []
