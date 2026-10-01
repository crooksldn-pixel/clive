"""Follow-ups from the round-12 deploy review: a new order by voice, the halves of a conversation,
a draft he asks CLIVE to forget, and the order tests made able to fail.

Each test here fails on the code it was written against (b577bc97) and passes on the fix:

* S2Ba/F-03 — "the next size up" read only the first hundred of a product's variants and took
  the starting variant's options from that page, so a size past it was said not to exist;
* S2Ba/F-04 — an order and a variant were taken together without the variant being checked
  against the order's lines, and the lines were read only to the first twenty;
* S2Bb-03 — the only live half could be merged, and a merged or cancelled half put back to
  BACKGROUND and focused live again;
* S2b-04 — forgetting a draft already saved in Gmail answered "Nothing was saved";
* T1-03, T7-02, T2/F-03, T2/F-01 and R9-I-tests2-I-02 — tests that could not fail as they
  should: each is run here against the fault it exists to catch, and has to catch it.

The shops, customers, addresses and orders are the invented ones of the tests they come from.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.actions.models import ActionStatus
from app.families import _sizes as sizes
from app.families import order_create as oc
from tests import test_branches, test_compose, test_r11_turn
from tests import test_r12_orders as r12
from tests import test_r12_surfaces as surfaces
from tests import test_turn_boundary as boundary
from tests.test_r12_orders import card, order_node, rows, say, vid

# The fixtures this file borrows, bound under their own names so pytest finds them here: the
# round-12 order shop, the round-11 desk, the halves' routes, and the composer's half.
shop = r12.shop
desk = test_r11_turn.desk
client = test_branches.client
branch = test_compose.branch
session = test_compose.session


# ============================================================ S2Ba/F-03: past the first page

# A hoodie in forty shades and three sizes: 120 variants, shade by shade, so the first hundred end
# at Shade 33 in S. Shade 33's M is the first variant of the second page, and Shade 39 is on it.
SHADES = [f"Shade {n:02d}" for n in range(40)]
SIZES = ["S", "M", "L"]
LONG = [{"id": f"gid://shopify/ProductVariant/{70000 + i}", "title": f"{shade} / {size}",
         "options": [("Colour", shade), ("Size", size)]}
        for i, (shade, size) in enumerate(itertools.product(SHADES, SIZES))]


def long_variant(index: int) -> str:
    return LONG[index]["id"]


def _node(variant: dict[str, Any]) -> dict[str, Any]:
    return {"id": variant["id"], "title": variant["title"], "sku": f"CRK-LONG-{variant['id'][-5:]}", "price": "60.00",
            "availableForSale": True, "inventoryQuantity": 3,
            "selectedOptions": [{"name": n, "value": v} for n, v in variant["options"]]}


class LongProduct:
    """Shopify answering for a product with more variants than one page: the variant asked for,
    from its own lookup, and its product's variants a page at a time, with whether there are more
    and the cursor to read them from. A query that names no page size gets the hundred the old
    one asked for."""

    def __init__(self) -> None:
        self.reads: list[dict[str, Any]] = []

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        self.reads.append(variables)
        assert "CrooksVariantSiblings" in query, query
        variant = next((v for v in LONG if v["id"] == variables.get("id")), None)
        if variant is None:
            return {"data": {"productVariant": None}}
        start, size = int(variables.get("after") or 0), int(variables.get("n") or 100)
        page = LONG[start:start + size]
        return {"data": {"productVariant": {**_node(variant), "product": {
            "id": "gid://shopify/Product/9700", "title": "Convict Hoodie", "status": "ACTIVE",
            "options": [{"name": "Colour", "values": SHADES}, {"name": "Size", "values": SIZES}],
            "variants": {"pageInfo": {"hasNextPage": start + size < len(LONG), "endCursor": str(start + size)},
                         "edges": [{"node": _node(v)} for v in page]},
        }}}}


@pytest.fixture()
def long_shop(monkeypatch) -> LongProduct:
    store = LongProduct()
    monkeypatch.setattr(oc, "_c", lambda: store)
    return store


async def test_f03_the_next_size_up_is_found_when_it_is_past_the_first_page(long_shop):
    """Shade 33 in S is the hundredth variant; its M is the hundred-and-first. It was "There is
    no Shade 33 Convict Hoodie in M"; it is the M, read from the second page."""
    stepped, why = await oc._step_size(long_variant(99), 1)
    assert why == "" and stepped is not None, why
    assert (stepped["variant_id"], stepped["variant"]) == (long_variant(100), "Shade 33 / M")
    assert (stepped["size_from"], stepped["size_to"]) == ("S", "M")
    assert [r.get("after") for r in long_shop.reads] == [None, "100"], "the second page was read from the cursor"


async def test_f03_a_starting_variant_past_the_first_page_steps_from_its_own_options(long_shop):
    """Shade 39 in M is on the second page. It was "I could not find that variant": where it
    starts was looked for among the first hundred. Its options are now its own lookup's."""
    stepped, why = await oc._step_size(long_variant(118), 1)
    assert why == "" and stepped is not None, why
    assert (stepped["variant_id"], stepped["variant"], stepped["size_to"]) == (long_variant(119), "Shade 39 / L", "L")


async def test_f03_a_read_cut_short_by_its_bound_is_refused_as_incomplete(long_shop, monkeypatch):
    """There is always a bound. A product whose variants run past it is refused as a read that
    was incomplete — never "there is no such size", which the variants not read could disprove."""
    monkeypatch.setattr(oc, "MAX_VARIANT_PAGES", 1)
    stepped, why = await oc._step_size(long_variant(99), 1)
    assert stepped is None
    assert why == "I read only the first 100 of Convict Hoodie's variants, so the read was incomplete and I cannot say which is the next size.", why
    assert "There is no" not in why and "could not find" not in why


def test_f03_the_start_is_the_variant_s_own_and_not_a_copy_from_the_sibling_list():
    """`_sizes.step` takes the starting variant as its own lookup gave it, and steps from that
    even when no page read so far carries it."""
    product = {"title": "Convict Hoodie", "options": [{"name": "Size", "values": ["S", "M", "L"]}],
               "variants": [{"id": "v-l", "title": "L", "selectedOptions": [{"name": "Size", "value": "L"}]}],
               "start": {"id": "v-m", "title": "M", "selectedOptions": [{"name": "Size", "value": "M"}]}}
    found = sizes.step(product, "v-m", 1)
    assert found["ok"] is True and found["variant"]["id"] == "v-l" and (found["from"], found["to"]) == ("M", "L"), found


# ============================================================ S2Ba/F-04: the item against its order


def _found(calls, n: int) -> dict[str, Any]:
    """The order the n-th search of this turn found, as Claude reads it off the result."""
    return [c for c in calls if c.name == "shopify_find_order" and c.ok][n].result["orders"][0]


def _opened(body: dict) -> dict[str, Any]:
    (opened,) = [t for t in body["tool_calls"] if t["name"] == "shopify_order_open"]
    return opened


async def test_f04_a_variant_on_none_of_the_order_s_lines_is_refused_naming_the_order(shop):
    """Theo's order (CROOKS-2101) and the waist-28 jeans from Ravi's order: "a new order from
    2101 in the next size up of this" used to step the jeans onto an order for Theo. It is
    refused, naming the order, and no order is opened; the hoodie that IS on 2101 still steps."""
    body = await say(shop, "the hoodie that went to SL6 2AB, a new order the next size up of the jeans to B3 3AS",
                     ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}),
                     ("shopify_find_order", {"item": "jeans", "address": "B3 3AS"}),
                     ("shopify_order_open", lambda calls: {
                         "order_id": _found(calls, 0)["order_id"],
                         "variant_id": _found(calls, 1)["matched_items"][0]["variant_id"], "size_step": 1}))
    opened = _opened(body)
    assert opened["ok"] is False, opened
    assert opened["error"] == ("That item is not on any line of order CROOKS-2101, so nothing was opened from it. "
                               "Say which item on CROOKS-2101 he means."), opened["error"]
    assert not [i for i in body["ui"] if i["type"] == "workspace"]
    assert getattr(shop.runtime.sessions.get("g1").branch(), "workspace", None) is None, "nothing was opened"
    assert shop.store.mutations == []

    again = await say(shop, "the hoodie, then",
                      ("shopify_order_open", {"order_id": "gid://shopify/Order/2101", "variant_id": vid(9112), "size_step": 1}))
    assert _opened(again)["ok"] is True
    assert rows(card(again)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")]


def _long_order(store) -> list[dict[str, Any]]:
    """Order 2101 with seventy lines of stickers before its hoodie, answered a page at a time as
    Shopify pages an order's lines. Returns the reads of it, as they were asked for."""
    real = store.graphql
    asked: list[dict[str, Any]] = []

    async def graphql(query, variables=None):
        if "CrooksOrderForNewOrder" not in query:
            return await real(query, variables)
        variables = dict(variables or {})
        asked.append(variables)
        node = order_node(2101)
        stickers = [{"node": {"title": f"Sticker {n}", "variantTitle": None, "quantity": 1, "variant": None}} for n in range(70)]
        edges = stickers + node["lineItems"]["edges"]
        # The old query asked for the first twenty and named no page size.
        start, size = int(variables.get("after") or 0), int(variables.get("n") or 20)
        node["lineItems"] = {"pageInfo": {"hasNextPage": start + size < len(edges), "endCursor": str(start + size)},
                             "edges": edges[start:start + size]}
        return {"data": {"order": node}}

    store.graphql = graphql
    return asked


async def test_f04_an_order_whose_lines_run_past_the_first_page_is_paged_before_it_is_stepped_from(shop):
    """The hoodie is the seventy-first line of 2101. It is found by paging the order's lines,
    and stepped; nothing is stepped from the first page alone."""
    asked = _long_order(shop.store)
    body = await say(shop, r12.THE_SENTENCE, *r12.the_sentence("black hoodie", "SL6 2AB"))
    assert _opened(body)["ok"] is True, _opened(body)
    assert rows(card(body)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")]
    assert [a.get("after") for a in asked] == [None, "50"], asked


async def test_f04_an_order_whose_lines_run_past_the_bound_is_refused_as_incomplete(shop, monkeypatch):
    """Past the bound, the item cannot be checked against the order, and nothing is opened."""
    monkeypatch.setattr(oc, "MAX_SOURCE_LINE_PAGES", 1)
    _long_order(shop.store)
    body = await say(shop, r12.THE_SENTENCE, *r12.the_sentence("black hoodie", "SL6 2AB"))
    opened = _opened(body)
    assert opened["ok"] is False
    assert opened["error"] == ("Order CROOKS-2101 has more lines than I read, so the read was incomplete and I cannot "
                               "check that item is on it. Nothing was opened."), opened["error"]
    assert not [i for i in body["ui"] if i["type"] == "workspace"]
    assert shop.store.mutations == []


# ============================================================ S2Bb-03: halves that stay live


async def _post(client, route: str, branch_id: str):
    return await client.post(f"/branches/{branch_id}/{route}", data={"session_id": "br"})


async def test_s2bb03_the_only_live_half_is_not_merged(client):
    """Merging the only half left none live, and the conversation's focus on a MERGED half."""
    session_ = client.runtime.sessions.get("br")
    only = session_.branch()
    refused = await _post(client, "merge", only.branch_id)
    assert refused.status_code == 409 and refused.json()["code"] == "last_branch", refused.text
    assert only.status == "ACTIVE" and session_.focused_branch == only.branch_id


@pytest.mark.parametrize("ended_by", ["merge", "cancel"])
async def test_s2bb03_a_merged_or_cancelled_half_never_comes_back_to_life(client, ended_by):
    """/background turned a merged or cancelled half back to BACKGROUND, and /focus then made it
    ACTIVE. Now /merge and /background refuse it as /focus does, its status stays what it was,
    and no sequence of the three makes it live again or moves the focus off the live half."""
    session_ = client.runtime.sessions.get("br")
    keeper = session_.branch()
    other = (await client.post("/branches/fork", data={"session_id": "br"})).json()["branch_id"]
    ended = await _post(client, ended_by, other)
    assert ended.status_code == 200, ended.text
    status = session_.branches[other].status
    assert status == {"merge": "MERGED", "cancel": "CANCELLED"}[ended_by]
    for route in ("merge", "background", "focus"):
        refused = await _post(client, route, other)
        assert refused.status_code == 409 and refused.json()["code"] == "branch_closed", (route, refused.text)
        assert session_.branches[other].status == status, route
    for sequence in itertools.product(("background", "focus", "merge"), repeat=3):
        for route in sequence:
            await _post(client, route, other)
        assert session_.branches[other].status == status, sequence
        assert session_.focused_branch == keeper.branch_id and keeper.status == "ACTIVE", sequence
    listed = (await client.get("/branches", params={"session_id": "br"})).json()
    assert [b["branch_id"] for b in listed["branches"]] == [keeper.branch_id]


# ============================================================ S2b-04: a draft saved in Gmail


class Untouchable:
    """A Gmail client that records anything asked of it. Forgetting a draft asks nothing."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __getattr__(self, name: str):
        self.asked.append(name)
        raise AssertionError(f"Gmail was asked for {name}")


def test_s2b04_forgetting_a_draft_saved_in_gmail_says_so_and_withdraws_nothing(branch, session, monkeypatch):
    """A draft already saved in Gmail (VERIFIED) is still there: the answer says it is saved in
    Gmail and was not deleted, nothing is withdrawn and Gmail is not asked. A draft still waiting
    for a tap is withdrawn, as before, and nothing was saved."""
    from app import commands
    from app.tools import gmail_tools, gmail_writes

    gmail = Untouchable()
    monkeypatch.setattr(gmail_writes, "_client", gmail)
    monkeypatch.setattr(gmail_tools, "_client", gmail)
    saved = test_compose._draft(session, branch, status=ActionStatus.VERIFIED)
    runtime = test_compose._Runtime()
    out = commands.run("draft.discard", test_compose._ctx(runtime, session, branch))
    assert out.ok, out
    assert out.answer == ("That draft is saved in Gmail and was not deleted: it is still in your Drafts there. "
                          "Delete it in Gmail if you do not want it."), out.answer
    assert "Nothing was saved" not in out.answer
    assert runtime.actions.revoked == [] and saved.status is ActionStatus.VERIFIED
    assert gmail.asked == []

    waiting = test_compose._draft(session, branch)
    out = commands.run("draft.discard", test_compose._ctx(runtime, session, branch))
    assert out.ok and out.answer == "Forgotten. Nothing was saved."
    assert runtime.actions.revoked == [waiting.proposal_id]
    assert gmail.asked == []


# ============================================================ T1-03: a date that is a date


def test_t103_order_2102_is_placed_on_a_day_that_exists():
    """Thirty days before 29 September was written "2026-09--1". It is 30 August, and every
    fixture order's dates are dates."""
    node = order_node(2102)
    assert node["createdAt"] == node["processedAt"] == "2026-08-30T10:00:00Z"
    assert datetime.fromisoformat(node["createdAt"]).date().isoformat() == "2026-08-30"
    for number, *_ in r12.ORDERS:
        placed = order_node(number)["createdAt"]
        assert datetime.fromisoformat(placed).year == 2026, (number, placed)


# ============================================================ T7-02: completions counted


def test_t702_the_browser_test_counts_completions_and_a_second_makes_nothing():
    """The browser test's draftOrderComplete answered #1999 to every call and counted none. It
    counts each call by draft, and a second call for one draft completes nothing."""
    from tests.test_r12_orders_browser import Completions

    draft_id = "gid://shopify/DraftOrder/5001"
    store = SimpleNamespace(drafts_by_id={draft_id: {"id": draft_id, "status": "OPEN", "order": None}})
    completions = Completions()
    first = completions(store, {"id": draft_id})["data"]["draftOrderComplete"]
    assert first["userErrors"] == [] and first["draftOrder"]["order"]["name"] == "#1999"
    assert completions.calls == [draft_id]
    second = completions(store, {"id": draft_id})["data"]["draftOrderComplete"]
    assert second["draftOrder"] is None and second["userErrors"], second
    assert completions.calls == [draft_id, draft_id]


# ============================================================ T2/F-03 and T2/F-01: the surfaces tests


async def test_t2f03_the_refused_note_test_fails_when_the_refusal_is_not_shown(desk, monkeypatch):
    """The refused-note test checked only that the order stayed on screen, which is as true when
    the owner is never told the note was refused. With the refusal kept off the screen, it fails."""
    from app import presentation

    monkeypatch.setattr(presentation, "_recovered", lambda call, later: True)
    with pytest.raises(AssertionError, match="the owner is shown the refusal once"):
        await surfaces.test_a_change_that_could_not_be_prepared_keeps_the_record_and_says_why(desk)


async def test_t2f01_the_claim_test_puts_back_the_very_timeline_it_displaced(desk, tmp_path):
    from app.observability import timeline

    before = timeline.current()
    installed = timeline.install(timeline.NullTimeline())
    try:
        await surfaces.test_the_claim_is_written_to_the_timeline_beside_the_decline_claims(desk, tmp_path)
        assert timeline.current() is installed, "a timeline other than the one displaced was left installed"
    finally:
        timeline.install(before)


# ============================================================ R9-I-tests2-I-02: "Here it is."


def _answers(model, words: str) -> None:
    """The model answering `words` whatever it read — a model whose answer names nothing."""
    turn = model.turn

    async def answered(session_id: str, text: str):
        result = await turn(session_id, text)
        result.text = words
        return result

    model.turn = answered


async def test_r9_the_named_order_test_fails_on_an_answer_that_names_no_order(desk):
    _answers(desk.model, "Here it is.")
    with pytest.raises(AssertionError, match="names the order asked for"):
        await boundary.test_a_number_that_is_not_the_open_order_is_drawn_from_what_was_read_for_it(desk, "1938", "1940")


async def test_r9_the_named_person_test_fails_on_an_answer_that_names_nobody(desk):
    _answers(desk.model, "Here it is.")
    with pytest.raises(AssertionError, match="the person asked for is named"):
        await test_r11_turn.test_a_named_person_with_another_customer_s_order_open_is_answered_from_that_person(desk)
