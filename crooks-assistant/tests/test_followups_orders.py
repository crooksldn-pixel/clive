"""Follow-ups from the round-12 deploy review (round 13): a new order by voice, the halves of a
conversation, and a draft the owner asks CLIVE to forget.

Each test here names the finding it answers, and each failed on the code it was written against:

* S2Ba/F-03 — "the next size up" read only the first 100 of a product's variants and dropped
  the starting variant's own options, so a size on a later page "did not exist".
* S2Ba/F-04 — with an order and a variant both given, the variant was never checked against the
  order's lines (read only to the first 20), so a variant of an unrelated product was stepped.
* S2Bb-03 — /merge took the only live half, and /background brought a merged or cancelled half
  back to life. Its three tests went with those routes when Split was deleted on the owner's
  ruling of 8 October (DEC-071, ruling 37).
* S2b-04 — "forget the draft" on a draft already saved in Gmail said "Nothing was saved."
* X1-03 — the order_by_voice scenario called its draft check exact and looked only at the lines,
  the postcode and the total.
* T1-03 — order 2102's date in tests/test_r12_orders.py was "2026-09--1".

The shops here are fakes and every name, address and order in them is invented.
"""

from __future__ import annotations

import copy
from datetime import datetime
from types import MappingProxyType
from typing import Any

import pytest

from app.families import _sizes as sizes
from app.families import order_create
from tests import test_r12_orders
from tests.test_r12_orders import THE_SENTENCE, card, order_node, rows, say, the_sentence, vid

shop = test_r12_orders.shop

# =========================================================== S2Ba/F-03: past the first page


def _variant(number: int, colour: str, size: str) -> dict[str, Any]:
    return {"id": f"gid://shopify/ProductVariant/{number}", "title": f"{colour} / {size}", "sku": f"YRD-{number}",
            "price": "55.00", "availableForSale": True, "inventoryQuantity": 3,
            "selectedOptions": [{"name": "Colour", "value": colour}, {"name": "Size", "value": size}]}


# Seven variants, two to a page: the next size of anything past the first two is on a later page.
YARD_HOODIE = [
    _variant(701, "Black", "XS"), _variant(702, "Black", "S"),
    _variant(703, "Black", "M"), _variant(704, "Black", "L"),
    _variant(705, "Black", "XL"), _variant(706, "Bone", "S"),
    _variant(707, "Bone", "M"),
]


class PagedProduct:
    """A product whose variants come back a page at a time, as Shopify returns a connection: a
    cursor is where the next page starts. `endless` says there is always more; `silent` leaves
    pageInfo out altogether."""

    def __init__(self, *, page: int = 2, endless: bool = False, silent: bool = False) -> None:
        self.page, self.endless, self.silent = page, endless, silent
        self.asked: list[Any] = []

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        assert "CrooksVariantSiblings" in query, query
        variables = dict(variables or {})
        self.asked.append(variables.get("after"))
        start = int(variables.get("after") or 0)
        own = next(v for v in YARD_HOODIE if v["id"] == variables["id"])
        more = self.endless or start + self.page < len(YARD_HOODIE)
        connection: dict[str, Any] = {"edges": [{"node": v} for v in YARD_HOODIE[start:start + self.page]]}
        if not self.silent:
            connection["pageInfo"] = {"hasNextPage": more, "endCursor": str(start + self.page) if more else None}
        return {"data": {"productVariant": {
            "id": own["id"], "title": own["title"], "selectedOptions": own["selectedOptions"],
            "product": {"id": "gid://shopify/Product/700", "title": "Yard Hoodie", "status": "ACTIVE",
                        "options": [{"name": "Colour", "values": ["Black", "Bone"]},
                                    {"name": "Size", "values": ["XS", "S", "M", "L", "XL"]}],
                        "variants": connection},
        }}}


def _bind(monkeypatch, product: PagedProduct) -> PagedProduct:
    monkeypatch.setattr(order_create, "_c", lambda: product)
    return product


async def test_f03_the_next_size_on_a_later_page_is_found_and_every_page_is_read(monkeypatch):
    """Black S is on the first page and Black M on the second. Reading one page said "There is no
    Black Yard Hoodie in M"; every page is read now, each from the cursor the last one gave."""
    product = _bind(monkeypatch, PagedProduct())
    stepped, why = await order_create._step_size(vid(702), 1)
    assert why == "" and stepped is not None, why
    assert (stepped["variant_id"], stepped["size_from"], stepped["size_to"]) == (vid(703), "S", "M")
    assert product.asked == [None, "2", "4", "6"], product.asked


async def test_f03_a_starting_variant_past_the_first_page_steps_from_its_own_options(monkeypatch):
    """Black L is on the second page and Black XL on the third. The start was looked for in the
    first page only, so it was "not on" its own product."""
    _bind(monkeypatch, PagedProduct())
    stepped, why = await order_create._step_size(vid(704), 1)
    assert why == "" and stepped is not None, why
    assert (stepped["variant_id"], stepped["size_from"], stepped["size_to"]) == (vid(705), "L", "XL")


async def test_f03_a_read_cut_short_by_its_bound_says_so_and_never_that_the_size_does_not_exist(monkeypatch):
    monkeypatch.setattr(order_create, "MAX_VARIANT_PAGES", 2, raising=False)
    product = _bind(monkeypatch, PagedProduct(endless=True))
    stepped, why = await order_create._step_size(vid(702), 1)
    assert stepped is None
    assert "could not read all of Yard Hoodie's variants" in why and "Nothing was added" in why, why
    assert "There is no" not in why and "not one of" not in why and "largest" not in why, why
    assert len(product.asked) == 2, "read to the bound and no further"


async def test_f03_a_page_that_does_not_say_whether_there_is_more_is_an_incomplete_read(monkeypatch):
    _bind(monkeypatch, PagedProduct(silent=True))
    stepped, why = await order_create._step_size(vid(702), 1)
    assert stepped is None and "could not read all of Yard Hoodie's variants" in why, why
    assert "There is no" not in why, why


def test_f03_the_step_starts_from_the_variant_s_own_lookup_wherever_it_is_listed():
    """The starting variant as its own lookup returned it is where the step starts, whether or
    not the variants listed include it."""
    product = {"title": "Yard Hoodie", "options": [{"name": "Colour", "values": ["Black"]},
                                                   {"name": "Size", "values": ["S", "M", "L"]}],
               "variants": [_variant(703, "Black", "M")],
               "start": {"id": vid(702), "title": "Black / S",
                         "selectedOptions": [{"name": "Colour", "value": "Black"}, {"name": "Size", "value": "S"}]}}
    found = sizes.step(product, vid(702), 1)
    assert found["ok"] is True, found
    assert (found["variant"]["id"], found["from"], found["to"]) == (vid(703), "S", "M")


# ======================================================= S2Ba/F-04: the item against its order

THEOS_ORDER = "gid://shopify/Order/2101"


def _opened(body: dict) -> dict:
    (opened,) = [t for t in body["tool_calls"] if t["name"] == "shopify_order_open"]
    return opened


async def test_f04_a_variant_on_none_of_the_order_s_lines_is_refused_naming_the_order(shop):
    """Theo's order (CROOKS-2101) has a black hoodie and a cap on it. Ravi's jeans, looked up in
    the same breath, are not on it: stepping them used to put Indigo / 30 jeans on an order for
    Theo. Refused now, saying which order, and nothing is opened."""
    body = await say(shop, "a new order for Theo in the next size up of the jeans",
                     ("shopify_find_order", {"item": "black hoodie", "address": "SL6 2AB"}),
                     ("shopify_find_order", {"item": "jeans", "address": "B3 3AS"}),
                     ("shopify_order_open", {"order_id": THEOS_ORDER, "variant_id": vid(9228), "size_step": 1}))
    opened = _opened(body)
    assert opened["ok"] is False, opened
    assert "That item is not on order CROOKS-2101" in str(opened.get("error")), opened
    assert not [i for i in body["ui"] if i["type"] == "workspace"], [i["type"] for i in body["ui"]]
    assert shop.runtime.sessions.get("g1").branch().workspace is None, "nothing was added to a workspace"
    assert shop.store.mutations == []

    # A variant that IS on one of its lines still steps as it did.
    again = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    assert rows(card(again)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")]


def _paged_lines(shop, *, endless: bool = False, hoodie_first: bool = False) -> list[Any]:
    """Theo's order read for a new order with its lines a page at a time: the cap on the first
    page and the hoodie on the second — or, `endless`, the cap on every page and always more.
    `hoodie_first` puts the hoodie on the first page and the cap on every page after it, the
    last of them saying there is no more unless `endless`."""
    real = shop.store.graphql
    asked: list[Any] = []

    async def graphql(query, variables=None):
        if "CrooksOrderForNewOrder" in query and (variables or {}).get("id") == THEOS_ORDER:
            after = (variables or {}).get("after")
            asked.append(after)
            node = order_node(2101)
            cap, hoodie = sorted(node["lineItems"]["edges"], key=lambda e: e["node"]["variant"]["id"] != vid(9301))
            if hoodie_first:
                more = endless or not after
                node["lineItems"] = {"edges": [cap if after else hoodie],
                                     "pageInfo": {"hasNextPage": more, "endCursor": f"p{len(asked)}" if more else None}}
            elif endless:
                node["lineItems"] = {"edges": [cap], "pageInfo": {"hasNextPage": True, "endCursor": f"p{len(asked)}"}}
            elif not after:
                node["lineItems"] = {"edges": [cap], "pageInfo": {"hasNextPage": True, "endCursor": "p1"}}
            else:
                assert after == "p1", after
                node["lineItems"] = {"edges": [hoodie], "pageInfo": {"hasNextPage": False, "endCursor": None}}
            return {"data": {"order": node}}
        return await real(query, variables)

    shop.store.graphql = graphql
    return asked


async def test_f04_an_order_whose_lines_run_past_the_first_page_is_paged_to_find_the_line(shop):
    asked = _paged_lines(shop)
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    assert _opened(body)["ok"] is True, _opened(body)
    assert "p1" in asked, f"the second page of the order's lines was never read: {asked}"
    assert rows(card(body)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")]


async def test_f04_an_order_whose_lines_could_not_all_be_read_is_refused_as_incomplete(shop, monkeypatch):
    monkeypatch.setattr(order_create, "MAX_SOURCE_LINE_PAGES", 2, raising=False)
    asked = _paged_lines(shop, endless=True)
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    opened = _opened(body)
    assert opened["ok"] is False, opened
    assert "could not read all of order CROOKS-2101's lines" in str(opened.get("error")), opened
    assert len([a for a in asked if a]) == 1, f"read to the bound and no further: {asked}"
    assert not [i for i in body["ui"] if i["type"] == "workspace"]
    assert shop.runtime.sessions.get("g1").branch().workspace is None


async def test_f04_a_line_found_on_the_first_page_is_still_read_to_the_order_s_last_line(shop):
    """The hoodie is on the first page and the cap on the second. Finding the hoodie is not the
    end of the read: the order's lines are read to their last page before anything is stepped."""
    asked = _paged_lines(shop, hoodie_first=True)
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    assert _opened(body)["ok"] is True, _opened(body)
    assert asked.count("p1") == 1, f"the order's second page of lines was not read: {asked}"
    assert rows(card(body)) == [("Convict Hoodie", "Black / L", "× 1", "£60.00")]


async def test_f04_a_line_found_on_the_first_page_of_an_order_not_read_to_its_end_is_refused(shop, monkeypatch):
    """The hoodie is on the first page, but the order's lines run past the bound: the step would
    rest on a partial read, so it is refused as incomplete and nothing is opened."""
    monkeypatch.setattr(order_create, "MAX_SOURCE_LINE_PAGES", 2, raising=False)
    asked = _paged_lines(shop, hoodie_first=True, endless=True)
    body = await say(shop, THE_SENTENCE, *the_sentence("black hoodie", "SL6 2AB"))
    opened = _opened(body)
    assert opened["ok"] is False, opened
    assert "could not read all of order CROOKS-2101's lines" in str(opened.get("error")), opened
    assert len([a for a in asked if a]) == 1, f"read to the bound and no further: {asked}"
    assert not [i for i in body["ui"] if i["type"] == "workspace"]
    assert shop.runtime.sessions.get("g1").branch().workspace is None
    assert shop.store.mutations == []


# ======================================================= S2b-04: a saved draft, told truly


class _Actions:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    def revoke_ids(self, ids, reason):
        self.revoked += list(ids)
        return len(ids)


class _NoGmail:
    """Any use of Gmail at all fails the test: forgetting a draft is not a Gmail call."""

    def __getattr__(self, name):
        raise AssertionError(f"Gmail was called ({name})")


class _Runtime:
    def __init__(self) -> None:
        self.actions = _Actions()
        self.gmail = _NoGmail()


def _draft(session, branch, status):
    from app.actions.models import ActionProposal
    from app.families import compose

    proposal = ActionProposal(
        proposal_id=f"prop_{len(session.proposals):04d}", session_id=session.session_id, epoch=1,
        tool_name="gmail_draft_new", operation="gmail_draft_new", risk="AMBER", model_args=MappingProxyType({}),
        execution=MappingProxyType({"thread_id": "", "to": "kit.ormond@example.com", "to_name": "",
                                    "subject": "Sunday", "body": "Free on Sunday?"}),
        entity_kind="email", entity_ref="cmp_abcdef0123", entity_label="new email",
        interaction="tap_commit", reversible=True, before={}, expected_after={}, summary={},
        fingerprint="f", created_at=compose._now(), expires_at=compose._now() + 60,
        status=status, branch_id=branch.branch_id,
    )
    session.proposals.append(proposal)
    return proposal


def test_s2b04_forgetting_a_draft_saved_in_gmail_says_so_and_withdraws_nothing():
    from app import commands
    from app.actions.models import ActionStatus
    from app.session.branch import Branch
    from app.session.models import Session

    session, branch = Session(session_id="s1"), Branch(branch_id="br_d", session_id="s1")
    saved = _draft(session, branch, ActionStatus.VERIFIED)
    runtime = _Runtime()
    out = commands.run("draft.discard", commands.Ctx(runtime, session, branch, {}))
    assert out.ok, out
    assert "saved in Gmail" in out.answer and "not deleted" in out.answer, out.answer
    assert "Nothing was saved" not in out.answer, out.answer
    assert runtime.actions.revoked == [], "nothing is withdrawn"
    assert saved.status is ActionStatus.VERIFIED

    # A draft still waiting for its tap is withdrawn exactly as before.
    session, branch = Session(session_id="s2"), Branch(branch_id="br_p", session_id="s2")
    waiting = _draft(session, branch, ActionStatus.PENDING)
    runtime = _Runtime()
    out = commands.run("draft.discard", commands.Ctx(runtime, session, branch, {}))
    assert out.ok and out.answer == "Forgotten. Nothing was saved."
    assert runtime.actions.revoked == [waiting.proposal_id]


# ==================================================== X1-03: the scenario's draft check, exact


def _tamper(kind: str, as_sent: list[dict] | None = None):
    """What the app sent, recorded wrong in one part: the scenario has to notice."""
    as_sent = as_sent if as_sent is not None else []
    from experience.fixtures import shopify as golden

    real = golden._draft_order_create

    def made(store, variables):
        answer = real(store, variables)
        sent = store.drafts[-1]
        if kind == "customer":
            sent["customerId"] = "gid://shopify/Customer/7999"
        elif kind == "email":
            sent["email"] = "someone.else@example.org"
        elif kind == "address":
            sent["shippingAddress"] = {**sent["shippingAddress"], "address1": "1 Other Street"}
        elif kind == "second line dropped":
            # What the app sent, kept so the test can see it carried the whole address and it
            # is only the record of it that loses a line.
            as_sent.append(dict(sent["shippingAddress"]))
            sent["shippingAddress"] = {k: v for k, v in sent["shippingAddress"].items() if k != "address2"}
        elif kind == "postage":
            sent["shippingLine"] = {"title": "Postage", "price": "9.00"}
        elif kind == "two drafts":
            store.drafts.append(copy.deepcopy(sent))
        return answer
    return made


@pytest.mark.parametrize(("kind", "caught_by"), [
    ("customer", "it is for the customer the order was found for, confirmed to her own address"),
    ("email", "it is for the customer the order was found for, confirmed to her own address"),
    ("address", "and goes to the whole of the address on the order it came from"),
    ("second line dropped", "and goes to the whole of the address on the order it came from"),
    ("postage", "with the postage he said"),
    ("two drafts", "exactly one draft was made in the shop"),
])
async def test_x103_order_by_voice_fails_on_a_draft_that_is_not_exactly_the_card(monkeypatch, kind, caught_by):
    from experience.fixtures import data
    from experience.fixtures import shopify as golden
    from experience.harness import harness
    from experience.scenarios import BY_NAME

    if kind == "second line dropped":
        # The order it came from with a second address line and a company, invented here, so a
        # draft that drops one is a draft that is not going to the whole of that address.
        parcel = data.BY_NAME["#1938"].address
        monkeypatch.setitem(parcel, "address2", "Flat 3")
        monkeypatch.setitem(parcel, "company", "Bridge Street Studio")
    as_sent: list[dict] = []
    monkeypatch.setitem(golden._DRAFTS, "draft_order_create", _tamper(kind, as_sent))
    async with harness(admitted=True) as h:
        result = await BY_NAME["order_by_voice"](h)
    assert result.status != "PASS", f"order_by_voice passed with the draft's {kind} wrong"
    assert caught_by in [c.what for c in result.failures], [c.what for c in result.failures]
    if kind == "second line dropped":
        (address,) = as_sent
        assert (address.get("address2"), address.get("company")) == ("Flat 3", "Bridge Street Studio"), address


# ========================================================= T1-03: dates made by arithmetic


def test_t103_every_order_date_in_the_round_12_shop_is_a_real_timestamp():
    assert order_node(2102)["createdAt"] == "2026-08-30T10:00:00Z"
    for number, *_ in test_r12_orders.ORDERS:
        placed = order_node(number)["createdAt"]
        assert datetime.fromisoformat(placed.replace("Z", "+00:00")).tzinfo is not None, placed
