"""Abandoned checkouts: the read, the ranking, and the sentence that says what the data is.

The store here is a fake with a handful of checkouts, one of which was completed in the end,
so the filter that keeps a recovered checkout out of the count is a filter over something.

What these hold, beyond the mechanics:

* the count, the value and the ranking are arithmetic over what was read, and the ranking is
  by how many CHECKOUTS an item appears in rather than by units or by value;
* a checkout that was paid for in the end is not an abandonment;
* every card and every spoken line says which of the three abandonment questions this is —
  and a store that cannot serve the query gets the limitation, never "I don't have a tool".
"""

from __future__ import annotations

import pytest

from app.clients.shopify import ShopifyError
from app.families import abandoned
from app.session.models import Session
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import FakeStore

TOOL = abandoned.READ_TOOL
HOODIE = "gid://shopify/ProductVariant/9102"
BONE = "gid://shopify/ProductVariant/9104"
CAP = "gid://shopify/ProductVariant/9301"

TITLES = {HOODIE: ("Convict Hoodie", "Black / M"), BONE: ("Convict Hoodie", "Bone / M"), CAP: ("Crooks Cap", "Black / One size")}

# Six abandoned and one recovered. The Black / M hoodie is in three of them, one of them
# twice, so counting checkouts and counting units give different answers — and the cap is in
# three as well with fewer units, which is what makes the tie-break a real one.
CHECKOUTS = [
    ("#C1", 0.4, False, "Mia Jones", [(HOODIE, 1), (CAP, 1)], "65.00"),
    ("#C2", 1.5, False, "", [(HOODIE, 2)], "125.00"),
    ("#C3", 3.2, False, "Priya Raman", [(BONE, 1)], "65.00"),
    ("#C4", 6.8, False, "Millie Fenwick", [(HOODIE, 1), (BONE, 1)], "125.00"),
    ("#C5", 11.0, False, "", [(CAP, 1)], "23.00"),
    ("#C6", 2.0, True, "David Randall", [(HOODIE, 1)], "65.00"),
    ("#C7", 40.0, False, "", [(CAP, 1)], "23.00"),
]


class AbandonedStore(FakeStore):
    def __init__(self) -> None:
        super().__init__(note="")
        self.checkouts = list(CHECKOUTS)
        self.answer_nothing = False        # the shop's plan does not serve the query
        self.window_days = 999.0           # what the fake honours as the window
        self.has_next = False
        self.asked: list[dict] = []

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksAbandonedCheckouts" in query:
            self.reads += 1
            self.asked.append(dict(variables or {}))
            if self.answer_nothing:
                return {"data": {"abandonedCheckouts": None}}
            edges = []
            for name, days, completed, who, lines, total in self.checkouts:
                if days > self.window_days:
                    continue
                edges.append({"node": {
                    "id": f"gid://shopify/AbandonedCheckout/{name.lstrip('#C')}",
                    "name": name,
                    "createdAt": "2026-09-09T10:00:00Z",
                    "completedAt": "2026-09-09T12:00:00Z" if completed else None,
                    "totalPriceSet": {"shopMoney": {"amount": total, "currencyCode": "GBP"}},
                    "customer": ({"id": "gid://shopify/Customer/1", "displayName": who} if who else None),
                    "lineItems": {"edges": [
                        {"node": {"title": TITLES[v][0], "variantTitle": TITLES[v][1], "quantity": q,
                                  "variant": {"id": v},
                                  "product": {"id": "gid://shopify/Product/9001", "title": TITLES[v][0]}}}
                        for v, q in lines
                    ]},
                }})
            return {"data": {"abandonedCheckouts": {"edges": edges, "pageInfo": {"hasNextPage": self.has_next}}}}
        return await super().graphql(query, variables)


@pytest.fixture()
def store():
    s = AbandonedStore()
    shopify_tools.bind(s)
    return s


@pytest.fixture()
def session():
    return Session(session_id="c1")


# --------------------------------------------------------------------------- declaration


def test_it_is_a_read_that_names_people_and_can_never_be_staged():
    spec = registry.get(TOOL)
    assert spec.write is None and spec.batch is None
    assert spec.tier is Tier.AMBER, "a checkout carries who began it"
    decision = classify(TOOL, {"days": 7}, issued_ids=set())
    assert decision.disposition is Disposition.EXECUTE_NOW and decision.tier is Tier.AMBER
    # Bounds, held by the gate before the tool sees them.
    assert classify(TOOL, {"days": 0}).disposition is Disposition.DENY
    assert classify(TOOL, {"days": 999}).disposition is Disposition.DENY
    assert classify(TOOL, {"limit": 500}).disposition is Disposition.DENY
    from app.capabilities import families

    family = families.get("abandoned_checkouts")
    assert family is not None and family.tools == (TOOL,) and family.operations == ()
    assert "not in Shopify's Admin API" in family.what


def test_the_description_and_the_family_both_say_what_the_data_is_not():
    """The one thing this family exists to keep saying. Held in one constant so the card, the
    spoken line and what the model reads cannot drift into three different claims."""
    assert "not baskets" in registry.get(TOOL).description.lower()
    assert "unfulfilled" in registry.get(TOOL).description.lower()
    assert "not baskets left on the site" in abandoned.WHAT_IT_IS
    assert "not orders waiting to go out" in abandoned.WHAT_IT_IS


# --------------------------------------------------------------------------- the read


async def test_the_count_the_value_and_the_average_are_arithmetic_over_what_was_read(store, session):
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    assert body["count"] == 6, "five in the fortnight plus the one older than it, which the fake still returns"
    # The fake returns everything; the WINDOW is Shopify's own filter, and the application
    # sends it — which is what the next test checks. What this one checks is the arithmetic.
    assert body["value"] == "426.00" and body["value_display"] == "£426.00"
    assert body["average_display"] == "£71.00"
    assert body["what_it_is"] == "checkout abandonment"
    assert "no cart resource" in body["not_included"]


async def test_a_checkout_that_was_paid_for_in_the_end_is_not_an_abandonment(store, session):
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    assert "#C6" not in [r["name"] for r in body["recent"]]
    store.checkouts = [c for c in CHECKOUTS if c[0] == "#C6"]
    empty = await abandoned.shopify_abandoned_checkouts(days=14)
    assert empty["count"] == 0 and empty["items"] == []
    assert "No checkouts were begun and left unpaid" in abandoned.spoken(empty)


async def test_the_window_is_the_shops_own_day_and_is_sent_to_shopify(store, session):
    await abandoned.shopify_abandoned_checkouts(days=7)
    asked = store.asked[-1]
    assert asked["n"] == abandoned.DEFAULT_LIMIT
    assert asked["q"].startswith("created_at:>='") and asked["q"].endswith("'")
    # Midnight in the shop's zone, which is 23:00Z the day before in summer and 00:00Z in
    # winter — never "now minus seven days", which would cut the seventh day in half.
    stamp = asked["q"].split("'")[1]
    assert stamp.endswith("Z") and stamp[11:] in ("23:00:00Z", "00:00:00Z"), stamp
    # The window is honoured by the shop, not by us: a checkout outside it never arrives.
    store.window_days = 7.0
    body = await abandoned.shopify_abandoned_checkouts(days=7)
    assert body["count"] == 4 and body["days"] == 7, "the four inside seven days; the recovered one is not one"


async def test_the_ranking_counts_checkouts_and_carries_the_units_beside_them(store, session):
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    rows = {r["item"] + "|" + r["variant"]: r for r in body["items"]}
    hoodie = rows["Convict Hoodie|Black / M"]
    cap = rows["Crooks Cap|Black / One size"]
    # Three checkouts each, four units against three: two hoodies in #C2.
    assert hoodie["checkouts"] == 3 and hoodie["units"] == 4
    assert cap["checkouts"] == 3 and cap["units"] == 3
    # The order is by checkouts, then units, then the name — never by value, which would put
    # one expensive checkout above a pattern. The hoodie leads on the tie-break.
    assert [(r["item"], r["variant"]) for r in body["items"]][0] == ("Convict Hoodie", "Black / M")
    assert [r["checkouts"] for r in body["items"]] == sorted((r["checkouts"] for r in body["items"]), reverse=True)
    assert body["items"][1] is cap or body["items"][1]["item"] == "Crooks Cap"


def test_two_of_the_same_item_in_one_checkout_is_one_checkout_not_two():
    """The check the ranking exists for: counting units would make a single bulk order look
    like a pattern, and counting checkouts must therefore not double-count a line."""
    ranked = abandoned.rank([
        {"total": 120.0, "lines": [
            {"title": "Convict Hoodie", "variant": "Black / M", "quantity": 2, "variant_id": HOODIE, "product_id": "p"},
        ]},
    ])
    assert len(ranked) == 1
    assert ranked[0]["checkouts"] == 1 and ranked[0]["units"] == 2
    # And an item with no variant id at all still ranks, by its words.
    named = abandoned.rank([
        {"total": 10.0, "lines": [{"title": "Sample", "variant": "", "quantity": 1, "variant_id": "", "product_id": ""}]},
        {"total": 10.0, "lines": [{"title": "Sample", "variant": "", "quantity": 1, "variant_id": "", "product_id": ""}]},
    ])
    assert len(named) == 1 and named[0]["checkouts"] == 2


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_shop_that_cannot_serve_the_query_gets_the_limitation_not_a_shrug(store, session):
    store.answer_nothing = True
    text = await dispatch(TOOL, {"days": 7}, session=session, timeout_s=5)
    assert text.startswith("ERROR"), text
    assert "read_orders" in text and "plan" in text
    assert "don't have a tool" not in text.lower() and "do not have a tool" not in text.lower()


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_shopify_that_is_not_answering_is_reported_as_that(store, session):
    class Broken(AbandonedStore):
        async def graphql(self, query, variables=None):
            raise ShopifyError("Shopify is rate-limiting us.")

    shopify_tools.bind(Broken())
    text = await dispatch(TOOL, {"days": 7}, session=session, timeout_s=5)
    assert text.startswith("ERROR") and "rate-limiting" in text


# --------------------------------------------------------------------------- the cards


async def test_the_cards_carry_the_numbers_and_say_what_the_data_is(store, session):
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    figures, ranking = abandoned.cards(body)
    assert figures.ui_type == "metric_group" and figures.surface_type == "analytics"
    metrics = {m["label"]: m["value"] for m in figures.data["metrics"]}
    assert metrics["checkouts abandoned"] == "6" and metrics["not taken"] == "£426.00"
    assert metrics["average each"] == "£71.00"
    assert abandoned.WHAT_IT_IS in figures.data["note"]
    assert abandoned.WHAT_IT_IS in figures.data["subtitle"]

    assert ranking.ui_type == "ranking"
    first = ranking.data["rows"][0]
    assert first["rank"] == 1 and first["kind"] == "variant" and first["ref"] == HOODIE
    assert first["primary"] == {"value": "3", "label": "checkouts"}
    assert first["secondary"] == {"value": "4", "label": "units"}
    assert first["pct"] == 100.0, "the leader fills the bar"
    assert "not by value" in ranking.data["note"]
    assert {"value": "£426.00", "label": "not taken"} in ranking.data["totals"]


async def test_no_abandonment_draws_the_figures_and_no_empty_ranking(store, session):
    store.checkouts = []
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    drawn = abandoned.cards(body)
    assert [c.ui_type for c in drawn] == ["metric_group"], "a ranking of nothing is not a card"
    assert drawn[0].data["metrics"][0]["value"] == "0"


async def test_the_spoken_line_names_the_number_the_value_and_the_item(store, session):
    body = await abandoned.shopify_abandoned_checkouts(days=7)
    said = abandoned.spoken(body)
    assert said.startswith("6 checkouts begun and not paid for in the last week, worth £426.00.")
    assert "Convict Hoodie (Black / M), in 3 of them" in said
    assert said.endswith(abandoned.WHAT_IT_IS)


def test_the_window_words_are_the_owners_words():
    assert abandoned._window_words(1) == "in the last day"
    assert abandoned._window_words(7) == "in the last week"
    assert abandoned._window_words(30) == "in the last 30 days"


# --------------------------------------------------------------------------- the fast lane


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_sentence_reaches_this_family_and_the_recipe_draws_both_cards(store, session):
    from app.fastpath import RECIPES
    from app.fastpath.intent import Intent, resolve, signals_for
    from app.fastpath.models import Ctx as RecipeCtx
    from app.reads.scheduler import run_plan

    branch = session.branch()
    for sentence in ("what's been abandoned this week", "how many abandoned checkouts", "abandoned baskets"):
        assert resolve(sentence, branch=branch).family == "abandoned_checkouts", sentence
    # A change is not this family, and neither is a question about the inbox.
    assert resolve("cancel the abandoned checkout", branch=branch).family != "abandoned_checkouts"
    assert resolve("who needs replying to", branch=branch).family != "abandoned_checkouts"

    recipe = RECIPES["abandoned_checkouts"]
    ctx = RecipeCtx(runtime=None, session=session, branch=branch,
                    intent=Intent(family="abandoned_checkouts", confidence=1.0,
                                  signals=signals_for("abandoned this week", branch=branch), slots={"days": 7}),
                    text="abandoned this week", memory=None)
    plan = recipe.plan(ctx)
    assert plan is not None and [r.tool for r in plan.reads] == [TOOL]
    assert plan.reads[0].args["days"] == 7
    result = await run_plan(plan, session=session, timeout_s=5.0)
    answer = recipe.render(ctx, result)
    assert [s.ui_type for s in answer.surfaces] == ["metric_group", "ranking"]
    assert "not paid for" in answer.answer and answer.trace["count"] == 6


async def test_a_shop_that_will_not_answer_defers_rather_than_drawing_an_empty_card(store, session):
    from app.fastpath import RECIPES
    from app.fastpath.intent import Intent, signals_for
    from app.fastpath.models import Ctx as RecipeCtx
    from app.reads.scheduler import ReadResult

    recipe = RECIPES["abandoned_checkouts"]
    branch = session.branch()
    ctx = RecipeCtx(runtime=None, session=session, branch=branch,
                    intent=Intent(family="abandoned_checkouts", confidence=1.0, signals=signals_for("", branch=branch)),
                    text="", memory=None)
    answer = recipe.render(ctx, ReadResult())
    assert answer.deferred and "did not answer" in answer.defer


async def test_the_probe_is_honest_about_the_one_scope_and_about_carts():
    class Runtime:
        def __init__(self, scopes):
            self.shopify = type("S", (), {"access_scopes": staticmethod(lambda: _scopes(scopes))})()

    async def _scopes(scopes):
        return set(scopes)

    ready = await abandoned._probe(Runtime({"read_orders"}))
    assert ready["state"] == "READY" and "carts are not in the API" in ready["detail"]
    missing = await abandoned._probe(Runtime({"read_products"}))
    assert missing["state"] == "MISSING_SCOPE" and missing["scope"] == "read_orders"

    class Broken:
        shopify = type("S", (), {"access_scopes": staticmethod(lambda: _boom())})()

    async def _boom():
        raise ShopifyError("not answering")

    probed = await abandoned._probe(Broken())
    assert probed["state"] == "TEMPORARILY_UNAVAILABLE" and "ShopifyError" in probed["detail"]
