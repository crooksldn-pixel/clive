"""Looking a customer's order up the way the owner says it, misheard names and all.

George, 2 October 2026: "There shouldn't be this friction for me trying to search up an order.
Clive should understand the relevance. Clive should realise when I say look up this customer xyz
the words it records may not be the exact customer name, e.g. Alysa could be Alicia or Alcya or
Alisya. Where it can find an order that matches the rest of the context it should do so and not
hinge on that one point of evidence."

Every test here is a sentence through the real `POST /turn`, with Claude scripted to make the one
call it would make (tests/test_r12_orders.py `Scripted`, held to the tool's own schema), against
the customers' fixture shop (tests/customers_world.py). The assertions are about what he would
SEE and what the model is told — and that nothing is claimed the facts do not support.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.customers import match, names, when
from tests.customers_world import ALICIA, PROXIED, THEO, cards, result, say, world_fixture

world = pytest.fixture(world_fixture)

# George's own four (2 October): "Alysa could be Alicia or Alcya or Alisya." Heard as one, the shop
# holds Alicia Grant.
GEORGES_FOUR = ("Alysa", "Alicia", "Alcya", "Alisya")
SPELLINGS = ("Alysa", "Alcya", "Alisya")


# --------------------------------------------------------------------------- the rules alone


@pytest.mark.parametrize("heard", SPELLINGS)
def test_each_of_his_spellings_sounds_like_alicia_and_not_like_somebody_else(heard):
    alicia = names.name_likeness(heard, "Alicia Grant")
    assert alicia["score"] >= names.FITS and not alicia["exact"]
    for other in ("Theo Marsh", "Mia Jones", "Poppy De-Witt", "Sam Cole"):
        assert names.name_likeness(heard, other)["score"] < names.DIFFERS, other


@pytest.mark.parametrize("heard", GEORGES_FOUR)
@pytest.mark.parametrize("written", GEORGES_FOUR)
def test_any_of_his_four_spellings_fits_any_other(heard, written):
    assert names.name_likeness(heard, written)["score"] >= names.FITS


@pytest.mark.parametrize(("heard", "written"), [
    ("Alicia", "Ellis Moore"), ("Alicia", "Elise Hart"), ("Alicia", "Alice Ward"), ("Ellis", "Alicia Grant"),
    ("Elise", "Alicia Grant"), ("Alice", "Alicia Grant"), ("Tom", "Tim Bell"), ("Tim", "Tom Bell"),
    ("Dan", "Don Reid"), ("Jake", "Jack Hall"), ("Jack", "Jake Hall"), ("Elissa", "Alicia Grant"),
])
def test_names_that_differ_only_in_their_vowels_are_never_a_full_match(heard, written):
    """The reviewer's pairs: the same consonants, other vowels, another name. At most "not sure"."""
    likeness = names.name_likeness(heard, written)
    assert likeness["score"] < names.FITS, likeness
    assert names.heard_words(heard, likeness) != f"name heard as '{heard}'"


def test_a_name_is_exact_a_nickname_or_neither():
    assert names.name_likeness("zoe adams", "Zoë Adams")["exact"] is True
    assert names.name_likeness("Dewitt", "Poppy De-Witt")["score"] == 1.0
    assert names.name_likeness("Kate Smith", "Katherine Smith")["how"] == "nickname"
    assert names.name_likeness("Ann", "Anne Rowe")["score"] >= names.FITS
    assert names.name_likeness("Theo", "Alicia Grant")["score"] < names.DIFFERS


def test_the_days_he_says_are_windows_in_the_shops_own_week():
    friday = date(2026, 10, 2)
    last_week = when.parse("last week", friday)
    assert (last_week.start, last_week.end) == (date(2026, 9, 21), date(2026, 9, 27))
    assert last_week.fit(date(2026, 9, 25)) == 1.0 and last_week.fit(date(2026, 9, 30)) == 0.5 and last_week.fit(date(2026, 9, 1)) == 0.0
    assert when.parse("Tuesday", friday).start == date(2026, 9, 29)
    assert when.parse("on Tuesday morning", friday).start == date(2026, 9, 29)
    assert when.parse("the 28th", friday).start == date(2026, 9, 28)
    assert when.parse("28/9", friday).start == date(2026, 9, 28)
    assert when.parse("3 days ago", friday).start == date(2026, 9, 29)
    assert when.parse("whenever it was", friday) is None


def test_an_amount_is_one_number_or_nothing():
    assert match.amount_of("£45") == 45.0 and match.amount_of("about 60 quid") == 60.0 and match.amount_of("45.50") == 45.5
    assert match.amount_of("between 40 and 50") is None and match.amount_of("a lot") is None


# --------------------------------------------------------------------------- one clear answer


async def test_a_real_customers_name_on_somebody_elses_order_is_a_question_not_an_answer(world):
    """The reviewer's case: "Alicia" is a real customer, and the only black cap is Ellis Moore's.
    The cap is offered — as a question, with Ellis's name on it — never as the answer."""
    body = await say(world, "Alicia who ordered the black cap",
                     ("shopify_find_order", {"name": "Alicia", "item": "black cap"}))
    told = result(world, "shopify_find_order")
    assert told["orders"] == [] and told["verdict"] == "check"
    assert [r["customer_name"] for r in told["likely"]] == ["Ellis Moore"]
    assert told["question"].startswith("Is it Ellis Moore's") and "a real customer's (Alicia)" in told["instruction"]
    (shown,) = cards(body, "order_match")
    assert shown["title"] != "Best match" and shown["question"] == told["question"]


@pytest.mark.parametrize("heard", SPELLINGS)
async def test_his_four_spellings_find_alicias_grey_hoodie_from_last_week(world, heard):
    body = await say(world, f"look up {heard} who ordered the grey hoodie last week",
                     ("shopify_find_order", {"name": heard, "item": "grey hoodie", "when": "last week"}))
    told = result(world, "shopify_find_order")
    # Nothing has ALL of it as said — and the order that fits the rest is found anyway.
    assert told["orders"] == [] and told["verdict"] == "one"
    (best,) = told["likely"]
    assert best["order_number"] == "CROOKS-2201" and best["customer_id"] == ALICIA
    assert best["why"].startswith("Alicia Grant — Loopback Hoodie (Grey / M), ordered ")
    assert best["why"].endswith(f"name heard as '{heard}'")
    assert "do not ask which" in told["instruction"]
    # On the glass: the match with its line, never an order card claiming he named it.
    (shown,) = cards(body, "order_match")
    assert shown["title"] == "Best match" and shown["rows"][0]["why"] == best["why"]
    assert shown["rows"][0]["fits"][0] == f"name heard as '{heard}'"
    assert not cards(body, "order")
    # And it is one tap away: the order's id is the conversation's to open.
    assert "gid://shopify/Order/2201" in world.runtime.sessions.get("c1").issued_ids


async def test_the_name_is_wrong_and_the_item_and_the_day_still_pick_the_order(world):
    body = await say(world, "find Rachel's indigo jeans from two days ago",
                     ("shopify_find_order", {"name": "Rachel", "item": "indigo jeans", "when": "2 days ago"}))
    told = result(world, "shopify_find_order")
    assert told["verdict"] == "one" and told["likely"][0]["customer_id"] == THEO
    assert "the name on it is Theo Marsh, not 'Rachel'" in told["likely"][0]["why"]
    assert "confirm before doing anything" in told["instruction"]
    assert "the name is not 'Rachel'" in told["likely"][0]["misses"]
    assert cards(body, "order_match")[0]["rows"][0]["order_number"] == "#2203"


async def test_an_amount_and_a_day_with_a_misheard_name(world):
    told_body = await say(world, "Thea's order, ninety quid, two days ago",
                          ("shopify_find_order", {"name": "Thea", "amount": "90", "when": "2 days ago"}))
    told = result(world, "shopify_find_order")
    assert told["verdict"] == "one" and told["likely"][0]["order_number"] == "CROOKS-2203"
    assert "£90.00" in told["likely"][0]["why"]
    assert cards(told_body, "order_match")


async def test_an_amount_is_held_to_what_was_paid_not_what_is_left_after_a_refund(world):
    """Alicia paid £70 for #2201 and £45 went back: "the £70 one" is that order."""
    await say(world, "Alicia Grant's seventy pound order", ("shopify_find_order", {"name": "Alicia Grant", "amount": "£70"}))
    told = result(world, "shopify_find_order")
    assert [o["order_number"] for o in told["orders"]] == ["CROOKS-2201"]


def test_an_order_the_cache_holds_with_a_refund_has_no_paid_amount_to_hold():
    """The read layer keeps what is left after refunds, not what was paid; such an order's amount
    is unknown to the scoring rather than wrong."""
    row = {"order_id": "gid://shopify/Order/1", "order_number": "#1", "created_at": "2026-09-30T10:00:00Z",
           "total": 25.0, "refunded": 45.0, "currency": "GBP", "items": []}
    assert match.from_cache_row(row).paid is None
    assert match.from_cache_row({**row, "refunded": 0.0}).paid == 25.0


async def test_part_of_an_email_and_a_day_find_the_order(world):
    await say(world, "the alicia.g one from last week", ("shopify_find_order", {"email": "alicia.g", "when": "last week"}))
    told = result(world, "shopify_find_order")
    assert told["verdict"] == "one" and told["likely"][0]["order_number"] == "CROOKS-2201"
    assert "email has 'alicia.g'" in told["likely"][0]["why"]


async def test_the_read_layers_own_orders_are_candidates_too(world):
    """Orders the Mac already holds (app/analytics/cache.py) are scored without asking again."""
    await world.runtime.order_cache.warm(90)
    from app.tools import shopify_tools

    candidates = shopify_tools._cached_candidates({"when": "last week"})
    assert {c.number for c in candidates} >= {"CROOKS-2201", "CROOKS-2204"}
    assert all(c.address.get("city") for c in candidates)


# --------------------------------------------------------------------------- a short question


async def test_two_that_fit_about_as_well_are_shown_with_one_question(world):
    body = await say(world, "Alysa who ordered a hoodie last week",
                     ("shopify_find_order", {"name": "Alysa", "item": "hoodie", "when": "last week"}))
    told = result(world, "shopify_find_order")
    assert told["verdict"] == "several"
    assert [r["order_number"] for r in told["likely"]] == ["CROOKS-2201", "CROOKS-2202"]
    assert told["question"].startswith("Which one: Alicia Grant's Loopback Hoodie on ")
    assert ", or Alison Grey's Loopback Hoodie on " in told["question"]
    (shown,) = cards(body, "order_match")
    assert shown["title"] == "Which one?" and shown["question"] == told["question"] and len(shown["rows"]) == 2


async def test_a_name_on_its_own_is_a_question_and_never_an_order(world):
    body = await say(world, "look up Alysa", ("shopify_find_order", {"name": "Alysa"}))
    told = result(world, "shopify_find_order")
    assert told["orders"] == [] and "likely" not in told
    assert [s["name"] for s in told["suggested"]] == ["Alicia Grant", "Alison Grey"]
    assert told["question"] == "Nobody is called Alysa. Did you mean Alicia Grant or Alison Grey?"
    (shown,) = cards(body, "customer_list")
    assert shown["title"] == "Did you mean?" and [c["name"] for c in shown["customers"]] == ["Alicia Grant", "Alison Grey"]
    assert shown["customers"][0]["why"] == "sounds like 'Alysa'"
    assert not cards(body, "order") and not cards(body, "order_match")


async def test_a_customer_search_that_finds_nobody_offers_the_names_that_sound_like_it(world):
    body = await say(world, "find the customer Alisya", ("shopify_find_customer", {"query": "Alisya"}))
    told = result(world, "shopify_find_customer")
    assert told["count"] == 0 and told["suggested"][0]["name"] == "Alicia Grant"
    assert cards(body, "customer_list")[0]["title"] == "Did you mean?"


# --------------------------------------------------------------------------- nothing claimed


async def test_one_fact_for_and_one_against_shows_nothing(world):
    """The jeans went to SL4; he said SL6. The item alone is no more an answer than the name."""
    body = await say(world, "the indigo jeans to SL6 4AB", ("shopify_find_order", {"item": "indigo jeans", "address": "SL6 4AB"}))
    told = result(world, "shopify_find_order")
    assert told["orders"] == [] and "likely" not in told
    (empty,) = cards(body, "order_list")
    assert empty["empty"] is True and "none has SL6 4AB in the delivery address" in empty["note"]


async def test_when_everything_fits_the_strict_answer_is_the_answer(world):
    body = await say(world, "Alicia's grey hoodie", ("shopify_find_order", {"name": "Alicia", "item": "grey hoodie"}))
    told = result(world, "shopify_find_order")
    assert [o["order_number"] for o in told["orders"]] == ["CROOKS-2201"] and "likely" not in told
    assert [o["order_number"] for o in cards(body, "order")] == ["#2201"]


async def test_a_day_he_says_narrows_the_strict_search_at_shopify(world):
    await say(world, "Alicia's grey hoodie last week", ("shopify_find_order", {"name": "Alicia", "item": "grey hoodie", "when": "last week"}))
    searched = [v["q"] for q, v in world.store.queries if "CrooksOrderEvidence" in q]
    assert "created_at:>=" in searched[0] and "created_at:<" in searched[0]
    assert [o["order_number"] for o in result(world, "shopify_find_order")["orders"]] == ["CROOKS-2201"]


async def test_a_day_only_near_what_he_said_is_never_called_a_match_for_it(world):
    """Theo's jeans were ordered two days ago. "Yesterday" is near that, not it: the order is
    offered as near yesterday, never listed as matching "yesterday"."""
    await say(world, "Theo Marsh's jeans from yesterday",
              ("shopify_find_order", {"name": "Theo Marsh", "item": "jeans", "when": "yesterday"}))
    told = result(world, "shopify_find_order")
    assert told["orders"] == []
    (near,) = told["likely"]
    assert near["order_number"] == "CROOKS-2203" and any(f.endswith("near yesterday") for f in near["fits"])


async def test_a_day_he_says_that_is_not_a_day_is_said_back(world):
    body = await say(world, "Alysa's grey hoodie, whenever", ("shopify_find_order", {"name": "Alysa", "item": "grey hoodie", "when": "whenever it was"}))
    assert result(world, "shopify_find_order")["unread"] == ["when ('whenever it was')"]
    assert "I could not read when ('whenever it was')" in cards(body, "order_match")[0]["note"]


# --------------------------------------------------------------------------- one tap


async def test_a_tap_on_the_match_opens_the_order_without_asking_again(world):
    await say(world, "look up Alcya who ordered the grey hoodie last week",
              ("shopify_find_order", {"name": "Alcya", "item": "grey hoodie", "when": "last week"}))
    opened = await world.post("/command", data={"session_id": "c1", "command": "open.entity", "kind": "order",
                                                "ref": "gid://shopify/Order/2201", "label": "#2201"}, headers=PROXIED)
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["ok"] is True, body
    assert [i["data"]["order_number"] for i in body["ui"] if i["type"] == "order"] == ["#2201"]
    assert len(world.model.prompts) == 1 and "look up Alcya" in world.model.prompts[0], "the tap reached no model"


async def test_words_that_are_not_a_day_are_not_held_against_the_order(world):
    """"Alicia's grey hoodie, whenever it was": the day is unknown, not wrong — the order is found."""
    await say(world, "Alicia's grey hoodie, whenever it was",
              ("shopify_find_order", {"name": "Alicia", "item": "grey hoodie", "when": "whenever it was"}))
    told = result(world, "shopify_find_order")
    assert [o["order_number"] for o in told["orders"]] == ["CROOKS-2201"]


async def test_words_that_could_not_be_read_are_said_even_when_the_order_is_found(world):
    """Not dropped quietly: the day and the amount he gave that could not be read are said back
    beside the order that was found without them."""
    await say(world, "Alicia's grey hoodie, whenever it was, a fair bit",
              ("shopify_find_order", {"name": "Alicia", "item": "grey hoodie", "when": "whenever it was", "amount": "a fair bit"}))
    told = result(world, "shopify_find_order")
    assert [o["order_number"] for o in told["orders"]] == ["CROOKS-2201"]
    assert told["unread"] == ["when ('whenever it was')", "amount ('a fair bit')"]
    assert told["unread_note"] == ("I could not read when ('whenever it was') or amount ('a fair bit'), "
                                   "so they were not used to find the order.")
    assert "unread_note" in told["instruction"]


async def test_a_tap_on_a_name_that_sounds_like_it_opens_their_story(world):
    await say(world, "look up Alysa", ("shopify_find_order", {"name": "Alysa"}))
    opened = await world.post("/command", data={"session_id": "c1", "command": "open.entity", "kind": "customer",
                                                "ref": ALICIA}, headers=PROXIED)
    body = opened.json()
    assert body["ok"] is True, body
    (customer,) = [i["data"] for i in body["ui"] if i["type"] == "customer"]
    assert customer["name"] == "Alicia Grant" and customer["timeline"]["rows"][0]["what"] == "Refunded £45.00 on #2201"
