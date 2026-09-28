"""The query engine, against the failures a real tablet session produced (brief §15).

The session that prompted this asked two things:

    "Can you see if any of our orders are undelivered or unfulfilled?"
    "Find a real international order that has been waiting too long and hasn't been fulfilled"

and both cost 15-16 s of Claude, three times over, to

    Query not understood: sort by : not one of the metrics or groups asked for

repeated verbatim while the planner invented another shape. Every test here is one of those
shapes, or one of the things that had no answer at all: "undelivered" (nothing here knows),
"international" (nothing compared a destination with the shop's own country), and the words
of ageing — "oldest", "waiting longest" — that the layer had never been taught.

The rule these follow: a refusal must be either a Query or a refusal that NAMES the fix. A
test that accepted "not understood" with nothing after it would be a test of the bug.
"""

from __future__ import annotations

import json

import pytest

from app.analytics import engine
from app.analytics.cache import OrderCache, shape_order
from app.analytics.query import (
    ALIASES,
    LISTING_SORT_KEYS,
    QueryError,
    parse,
    shop_country_from,
)
from app.session.models import Session
from app.tools import analytics_tools
from app.tools.dispatch import dispatch
from tests.test_analytics import HOODIE, JEANS, JOGGERS, LONDON, NOW, node
from tests.test_analytics_tools import Store, london_now

# A month of orders with something going abroad in it, something waiting a long time, and
# something already paid for and shipped: enough for every filter below to be able to fail.
NODES = [
    # Home, shipped yesterday with a tracking number: the only fulfilled one, and the cheapest.
    node(2001, days_ago=1, items=[(*JOGGERS, "Black", "L", 1, 45.0)], fulfillment="FULFILLED"),
    # Home, unfulfilled, three days old, and the most valuable — so "highest value" and
    # "oldest" cannot accidentally agree.
    node(2002, days_ago=3, items=[(*JEANS, "Blue", "M", 1, 90.0), (*JOGGERS, "Black", "M", 1, 45.0)],
         customer=("gid://shopify/Customer/2", "Ben Bold", 1, 135.0)),
    # Ireland, unfulfilled, twenty days old: the international order waiting too long.
    node(2003, days_ago=20, items=[(*HOODIE, "Grey", "M", 1, 70.0)], customer=("gid://shopify/Customer/3", "Cy Cole", 1, 70.0), country="IE"),
    # Home, unfulfilled, twelve days old, and never paid.
    node(2004, days_ago=12, items=[(*JOGGERS, "Pink", "S", 2, 45.0)], customer=("gid://shopify/Customer/4", "Di Dane", 1, 90.0), financial="PENDING"),
]


@pytest.fixture()
def rows():
    return [shape_order(n, read_at=NOW.timestamp()) for n in NODES]


@pytest.fixture()
def bound(monkeypatch):
    """The read tools against the orders above, with the clock the fixtures were built at."""
    store = Store(NODES)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    analytics_tools.bind(cache)
    london_now(monkeypatch)
    try:
        yield store
    finally:
        analytics_tools.bind(None)


def run(spec: dict, rows: list[dict], **kwargs) -> dict:
    query = parse(spec, now=NOW, **{k: v for k, v in kwargs.items() if k == "shop_country"})
    return engine.aggregate(query, rows, now=NOW.timestamp(), tz=LONDON)


def numbers(result: dict) -> list[str]:
    return [str(r.get("order_number") or "") for r in result["rows"]]


# --------------------------------------------------------------------------- sort shapes

SORTS = [
    # (what a planner sent, what it means)
    ({"metric": "age_days", "direction": "desc"}, ("age_days", "desc")),
    ({"key": "created_at", "order": "asc"}, ("created_at", "asc")),
    ({"field": "total", "dir": "DESC"}, ("total", "desc")),
    ({"by": "oldest"}, ("created_at", "asc")),
    ({"metric": "placed_at", "direction": "desc"}, ("created_at", "desc")),
    ("oldest", ("created_at", "asc")),
    ("newest", ("created_at", "desc")),
    ("created_at desc", ("created_at", "desc")),
    ("total desc", ("total", "desc")),
    ("waiting longest", ("created_at", "asc")),
    ("age", ("created_at", "asc")),
    ("value", ("total", "desc")),
    ("highest_value", ("total", "desc")),
    ("lowest value", ("total", "asc")),
    ("-total", ("total", "desc")),
    ("+created_at", ("created_at", "asc")),
    ("total:asc", ("total", "asc")),
    (["oldest"], ("created_at", "asc")),
    ([{"metric": "total", "direction": "asc"}], ("total", "asc")),
]


@pytest.mark.parametrize(("sent", "meant"), SORTS)
def test_every_sort_shape_a_planner_sends_parses(sent, meant):
    query = parse({"entity": "orders", "period": "last_90_days", "sort": sent}, now=NOW)
    assert query.sort[0] == meant, f"{sent!r} became {query.sort[0]}"


def test_the_words_of_ageing_and_the_key_age_days_order_the_same_list(rows):
    oldest_first = numbers(run({"entity": "orders", "period": "last_90_days", "sort": "oldest"}, rows))
    by_age = numbers(run({"entity": "orders", "period": "last_90_days", "sort": [{"metric": "age_days", "direction": "desc"}]}, rows))
    assert oldest_first == by_age == ["CROOKS-2003", "CROOKS-2004", "CROOKS-2002", "CROOKS-2001"]
    assert numbers(run({"entity": "orders", "period": "last_90_days", "sort": "newest"}, rows)) == list(reversed(oldest_first))
    assert numbers(run({"entity": "orders", "period": "last_90_days", "sort": "highest value"}, rows))[0] == "CROOKS-2002", "135 is the biggest order here"


@pytest.mark.parametrize("sent", [
    {"metric": "", "direction": "desc"},        # the empty key that produced "sort by :"
    {"direction": "desc"},
    "",
    {"metric": None},
])
def test_an_empty_sort_key_names_the_keys_instead_of_saying_nothing(sent):
    with pytest.raises(QueryError) as caught:
        parse({"entity": "orders", "period": "last_90_days", "sort": sent}, now=NOW)
    message = str(caught.value)
    assert "sort by :" not in message, "the tablet saw this three times: a refusal naming nothing"
    assert all(key in message for key in LISTING_SORT_KEYS), message
    assert caught.value.schema_help["accepted_sort_keys"], "the refusal must carry the schema"


def test_an_unknown_sort_key_is_named_as_unknown_and_a_known_one_is_not():
    with pytest.raises(QueryError) as caught:
        parse({"entity": "orders", "period": "last_90_days", "sort": "how_cross_the_customer_is"}, now=NOW)
    assert caught.value.unknown == ["sort:how_cross_the_customer_is"], "a dimension worth counting"
    assert "created_at" in str(caught.value)
    with pytest.raises(QueryError) as asked:
        parse({"entity": "order_line_items", "metrics": ["units"], "sort": [{"metric": "revenue"}]}, now=NOW)
    assert asked.value.unknown == [], "revenue exists; it was just not asked for — not a gap in the language"
    assert "units" in str(asked.value)


# ------------------------------------------------------------------- the live failure again

# What the planner actually tried, in order, for each sentence. Reconstructed from the shapes
# that appear in the transcript: a sort with no key, a sort naming a filter, a filter named
# after a delivery it cannot see.
UNDELIVERED_ATTEMPTS = [
    {"entity": "orders", "filters": {"delivery_status": "undelivered"}, "sort": [{"metric": "", "direction": "desc"}]},
    {"entity": "orders", "filters": {"fulfillment": "unfulfilled"}, "sort": [{"metric": "fulfillment", "direction": "desc"}]},
    {"entity": "orders", "filters": {"fulfillment": "unfulfilled"}, "sort": "oldest"},
]
INTERNATIONAL_ATTEMPTS = [
    {"entity": "orders", "filters": {"international": True, "fulfillment": "unfulfilled"}, "sort": [{"metric": "waiting_time", "direction": "desc"}]},
    {"entity": "orders", "filters": {"overseas": True, "unfulfilled": True}, "sort": {"by": "waiting longest"}},
    {"entity": "orders", "filters": {"international": True, "fulfillment": "unfulfilled", "older_than_days": 10}, "sort": "age_days desc"},
]


@pytest.mark.parametrize("spec", UNDELIVERED_ATTEMPTS + INTERNATIONAL_ATTEMPTS)
def test_each_attempt_either_parses_or_says_what_would_work(spec):
    """The invariant that stops the loop: never a refusal a planner cannot act on."""
    try:
        query = parse(spec, now=NOW, shop_country="GB")
        assert query.entity == "orders" and query.sort, spec
        return
    except QueryError as exc:
        help_ = exc.schema_help
        assert help_.get("accepted_sort_keys"), f"no sort keys offered: {exc}"
        assert help_.get("filters") and "fulfillment" in help_["filters"], f"no filters offered: {exc}"
        example = help_.get("example") or {}
        assert parse(example, now=NOW).entity, "the example the refusal offers must itself parse"


def test_the_third_attempt_of_each_sentence_is_the_answer(rows):
    """The shapes that DO parse answer the question that was asked, in the right order."""
    unfulfilled = run(UNDELIVERED_ATTEMPTS[-1], rows)
    assert numbers(unfulfilled) == ["CROOKS-2003", "CROOKS-2004", "CROOKS-2002"], "every unfulfilled one, oldest first"
    abroad = run(INTERNATIONAL_ATTEMPTS[-1], rows, shop_country="GB")
    assert numbers(abroad) == ["CROOKS-2003"], "the Irish one, waiting twenty days"


# --------------------------------------------------------------- delivery does not exist here


@pytest.mark.parametrize("spec", [
    {"entity": "orders", "filters": {"delivered": True}},
    {"entity": "orders", "filters": {"undelivered": True}},
    {"entity": "orders", "filters": {"delivery_status": "pending"}},
    {"entity": "orders", "filters": {"fulfillment": "delivered"}},
    {"entity": "orders", "sort": "undelivered"},
    {"entity": "orders", "sort": {"metric": "delivered", "direction": "desc"}},
    {"entity": "deliveries"},
    {"entity": "order_line_items", "group_by": ["delivery"]},
])
def test_delivered_and_undelivered_fail_locally_and_offer_what_exists(spec):
    with pytest.raises(QueryError) as caught:
        parse(spec, now=NOW)
    message = str(caught.value)
    assert "tracking" in message and "has_tracking" in message, message
    assert "fulfilled" in message, "the refusal offers the fact that IS known"
    assert caught.value.unknown, "the report counts what was asked for and does not exist"


def test_undelivered_is_never_quietly_read_as_unfulfilled():
    """The failure mode worse than the refusal: answering a delivery question with fulfilment
    and saying nothing about the difference."""
    for spec in ({"entity": "orders", "filters": {"undelivered": True}},
                 {"entity": "orders", "filters": {"fulfillment": "undelivered"}}):
        with pytest.raises(QueryError):
            parse(spec, now=NOW)


# --------------------------------------------------------------------------- the new filters


def test_international_and_domestic_are_decided_against_the_shops_own_country(rows):
    abroad = run({"entity": "orders", "period": "last_90_days", "filters": {"international": True}}, rows, shop_country="GB")
    assert numbers(abroad) == ["CROOKS-2003"]
    home = run({"entity": "orders", "period": "last_90_days", "filters": {"domestic": True}}, rows, shop_country="GB")
    assert set(numbers(home)) == {"CROOKS-2001", "CROOKS-2002", "CROOKS-2004"}
    # Move the shop and the same rows answer the other way round: this is a comparison, not a
    # list of countries somebody typed out.
    moved = run({"entity": "orders", "period": "last_90_days", "filters": {"international": True}}, rows, shop_country="IE")
    assert set(numbers(moved)) == {"CROOKS-2001", "CROOKS-2002", "CROOKS-2004"}
    assert numbers(run({"entity": "orders", "period": "last_90_days", "filters": {"overseas": True}}, rows, shop_country="GB")) == ["CROOKS-2003"]


def test_an_order_with_no_shipping_country_is_neither_international_nor_domestic():
    nowhere = shape_order(node(2099, days_ago=2, items=[(*JOGGERS, "Black", "L", 1, 45.0)], country=""), read_at=NOW.timestamp())
    rows = [nowhere]
    assert run({"entity": "orders", "period": "last_90_days", "filters": {"international": True}}, rows, shop_country="GB")["rows"] == []
    assert run({"entity": "orders", "period": "last_90_days", "filters": {"international": False}}, rows, shop_country="GB")["rows"] == []
    assert run({"entity": "orders", "period": "last_90_days"}, rows)["totals"]["orders"] == 1, "it is still an order"


def test_the_shop_country_comes_from_the_shop_with_the_setting_as_the_override():
    assert shop_country_from({"billingAddress": {"countryCodeV2": "IE"}}) == "IE", "the shop's own answer"
    assert shop_country_from(None) == "GB", "nothing said: where CROOKS is"
    assert shop_country_from({"billingAddress": {"countryCodeV2": "IE"}}, "US") == "US", "the setting overrides"
    assert shop_country_from({"countryCode": "de"}, "GB") == "DE", "the default setting does not override the shop"


@pytest.mark.parametrize(("filters", "expected"), [
    ({"unfulfilled": True}, {"CROOKS-2002", "CROOKS-2003", "CROOKS-2004"}),
    ({"fulfilled": True}, {"CROOKS-2001"}),
    ({"unpaid": True}, {"CROOKS-2004"}),
    ({"paid": True}, {"CROOKS-2001", "CROOKS-2002", "CROOKS-2003"}),
    ({"waiting_days": 15}, {"CROOKS-2003"}),
    ({"days_waiting": 10, "unfulfilled": True}, {"CROOKS-2003", "CROOKS-2004"}),
    ({"at_least_days": 30}, set()),
    ({"has_tracking": True}, {"CROOKS-2001"}),
    ({"country": "IE"}, {"CROOKS-2003"}),
    ({"region": "IE"}, {"CROOKS-2003"}),
    ({"town": "london"}, {"CROOKS-2001", "CROOKS-2002", "CROOKS-2003", "CROOKS-2004"}),
    ({"min_value": 89}, {"CROOKS-2002", "CROOKS-2004"}),
    ({"max_amount": 50}, {"CROOKS-2001"}),
    ({"variant": "grey"}, {"CROOKS-2003"}),
    ({"customer": "gid://shopify/Customer/3"}, {"CROOKS-2003"}),
])
def test_the_filters_and_their_aliases_narrow_the_rows(filters, expected, rows):
    got = set(numbers(run({"entity": "orders", "period": "last_90_days", "filters": filters}, rows, shop_country="GB")))
    assert got == expected, f"{filters} -> {sorted(got)}"


def test_every_example_the_refusals_offer_parses_for_its_own_entity():
    """The refusal hands the planner a spec to copy. One that did not parse would send it
    round the loop this whole pass exists to end."""
    from app.analytics.query import ENTITIES, schema_help

    for entity in ENTITIES:
        example = schema_help(entity)["example"]
        parsed = parse(example, now=NOW)
        assert parsed.entity == example["entity"], f"{entity}: the example became {parsed.entity}"


def test_every_alias_in_the_table_resolves_to_a_filter_that_exists():
    from app.analytics.query import FILTERS

    for alias, name in ALIASES.items():
        assert name in FILTERS, f"{alias} points at {name}, which is not a filter"
        assert alias not in FILTERS, f"{alias} is both a filter and an alias"


def test_a_date_window_in_the_filters_becomes_the_period():
    window = parse({"entity": "orders", "filters": {"date_from": "2026-09-01", "date_to": "2026-09-03"}}, now=NOW)
    assert window.period.start.date().isoformat() == "2026-09-01" and window.filters == {"cancelled": "false"}
    one_day = parse({"entity": "orders", "filters": {"on": "2026-09-02"}}, now=NOW)
    assert one_day.period.start.date().isoformat() == "2026-09-02" and one_day.period.end.date().isoformat() == "2026-09-03"
    with pytest.raises(QueryError) as caught:
        parse({"entity": "orders", "period": "today", "filters": {"since": "2026-09-01"}}, now=NOW)
    assert "keep one" in str(caught.value)


# ------------------------------------------------------------------ what the model is handed


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_tools_refusal_carries_the_schema_and_stays_short_enough_to_read(bound, monkeypatch):
    from app.observability import timeline

    events: list[dict] = []
    monkeypatch.setattr(timeline, "emit", lambda kind, **fields: events.append({"kind": kind, **fields}))
    session = Session(session_id="q1")
    session.turn_id = "turn_query"
    calls: list = []
    text = await dispatch("commerce_query", {"entity": "orders", "sort": [{"metric": "", "direction": "desc"}]},
                          session=session, timeout_s=5, calls=calls)
    assert text.startswith("ERROR: Query not understood:") and calls[-1].ok is False
    assert "sort by :" not in text
    assert "created_at, total, age_days" in text, "the accepted keys, named"
    assert "Retry ONCE with this shape:" in text
    assert len(text) < 500, f"the whole error is {len(text)} chars; a planner skims a longer one"
    # The dispatcher adds its own sentence after the tool's message; the shape is what is
    # between the two.
    offered = text.split("Retry ONCE with this shape: ", 1)[1]
    shape = json.loads(offered.split(" Say that", 1)[0])
    assert parse(shape, now=NOW).entity == "orders", "the shape offered is a shape that works"
    rejected = [e for e in events if e["kind"] == "query_rejected"]
    assert rejected and rejected[-1]["tool"] == "commerce_query"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_rejected_names_reach_the_timeline(bound, monkeypatch):
    from app.observability import timeline

    events: list[dict] = []
    monkeypatch.setattr(timeline, "emit", lambda kind, **fields: events.append({"kind": kind, **fields}))
    session = Session(session_id="q2")
    session.turn_id = "turn_query"
    await dispatch("commerce_query", {"entity": "orders", "filters": {"undelivered": True}}, session=session, timeout_s=5, calls=[])
    rejected = [e for e in events if e["kind"] == "query_rejected"]
    assert rejected and rejected[-1]["unknown"] == ["filter:undelivered"], rejected


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_international_listing_runs_through_the_tool_oldest_first(bound):
    session = Session(session_id="q3")
    session.turn_id = "turn_query"
    calls: list = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days",
                                      "filters": {"fulfillment": "unfulfilled", "international": True},
                                      "sort": "oldest", "title": "Abroad"},
                   session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert [r["order_number"] for r in result["rows"]] == ["CROOKS-2003"]
    assert result["set"]["set_id"] and result["set"]["count"] == 1, "a set to work through"
    assert "abroad" in result["set"]["label"].lower(), result["set"]["label"]


def test_the_catalogue_and_the_manifest_publish_the_new_vocabulary():
    from app.capabilities.manifest import build

    catalogue = analytics_tools.catalogue()
    assert catalogue["filters"]["international"]["type"] == "bool"
    assert "domestic" in catalogue["filters"]["international"]["aliases"]
    assert catalogue["filter_aliases"]["waiting_days"] == "older_than_days"
    assert "oldest" in catalogue["sort_keys"]["orders"]
    assert "tracking" in catalogue["not_available"]["delivery_status"]
    dims = build(build_id="t")["query_dimensions"]
    assert {"international", "city", "variant"} <= set(dims["filters"])
    assert {"waiting_days", "days_waiting", "domestic"} <= set(dims["filter_aliases"])
    assert {"oldest", "waiting_longest", "age_days"} <= set(dims["sort_keys"])


def test_the_mac_says_out_loud_that_delivery_is_not_connected():
    """The systemic half of the local refusal: the model is told once, at the start of the
    turn, rather than discovering it a refused query at a time."""
    from app.capabilities import families as capability_families
    from app.families import load_all

    load_all()
    family = capability_families.get("delivery_tracking")
    assert family is not None and family.state == "DISCONNECTED"
    lines = capability_families.words({family.key: {"label": family.label, "state": family.state, "detail": family.detail}})
    # State first, then who — and the "do not attempt" is once at the head of the block
    # (app/routes/turn.py FAMILY_LINE_PREFIX), not on each line.
    assert any("DISCONNECTED" in line and "Delivery status" in line for line in lines), lines
    assert any("no carrier is connected" in line for line in lines), lines


# ------------------------------------------------------------------ what the words ask for

def test_a_change_is_still_a_change_and_a_state_is_not():
    """"fulfilled" moved from the strong mutation words to the soft ones so that "hasn't been
    fulfilled" could be read as a description. The imperatives must still be instructions.
    The rule lives in the report's request contract now that nothing routes by words."""
    from app.observability.contract import mutating

    assert mutating(("fulfil", "1938")) and mutating(("mark", "1938", "fulfilled"))
    assert mutating(("cancel", "it")) and mutating(("what", "should", "i", "cancel"))
    assert not mutating(("has", "1938", "been", "fulfilled"))
    assert not mutating(("find", "an", "order", "that", "has", "not", "been", "fulfilled"))
