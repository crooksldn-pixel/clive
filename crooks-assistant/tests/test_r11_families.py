"""Round 11, the families: what the round-10 deploy review found in the family reads, and the
round-9 family findings it could not rule on, held end to end.

Each test names the finding it closes or evidences. What they hold:

* **AC1-F-01** — `email_query` puts a member in "not contacted" only after their inbox was
  actually read. A member whose Gmail check failed or did not come back is neither contacted
  nor not contacted: they are held apart as the unchecked set, so "draft an apology to the rest"
  cannot reach someone who may well have written.
* **F-01** — the abandoned-checkout figures are the WINDOW's: the read follows Shopify's pages
  to the end of the window, within a bound, and past the bound (or when a later page fails) the
  figures are labelled as the checkouts read and the cards are marked incomplete.
* **F-02** — the Orders landing says "Nothing is waiting to go out" only of a complete read. An
  open-orders read that answered but is not complete (the order cache still filling) says none
  are held so far and more may exist, and the answer is partial.
* **R9-E-families1-E-01** — the Add on the variant picker, tapped through `POST /command`,
  stages only a row of the picker the half's screen holds for the order on screen: an item the
  conversation was shown elsewhere is refused, and nothing is calculated.
* **R9-E-families1-E-02** — an address the model writes into a composer, however canonical,
  reaches no draft and no send until the owner has put a finger on it: the model's own call of
  the write tool in the same turn is refused by the write tool, the tap is refused, and only
  after the owner types it does the tap prepare — that address and no other.
* **R9-J-docs1-J-01** — what the README now says is what the turn does: a sentence naming an
  order reaches the model as said, with no order read in front of it.

Everything runs through the real routes, the real gate and the real action engine where the
finding is about a route; the golden world (experience/fixtures) refuses every write.
"""

from __future__ import annotations

import pytest

from app.clients.shopify import ShopifyError
from app.families import abandoned
from app.session.models import Session
from app.tools import analytics_tools, registry, shopify_tools
from app.tools.dispatch import dispatch
from experience.fixtures import data
from experience.harness import harness
from tests.test_abandoned import HOODIE, AbandonedStore
from tests.test_analytics_tools import NOW, Clock, Store, london_now
from tests.test_turn_boundary import A as BOUNDARY_ORDER
from tests.test_turn_boundary import records, say, shop  # noqa: F401 — `shop` is the route fixture

# ================================================================ AC1-F-01: email_query


@pytest.fixture()
def orders_store():
    return Store()


@pytest.fixture()
def cache(orders_store):
    from app.analytics.cache import OrderCache

    held = OrderCache(lambda: orders_store, clock=Clock(NOW.timestamp()))
    analytics_tools.bind(held)
    yield held
    analytics_tools.bind(None)


@pytest.fixture()
def convo() -> Session:
    s = Session(session_id="r11fam")
    s.turn_id = "turn_r11"
    return s


BEN, FLO, GUS = "gid://shopify/Order/1002", "gid://shopify/Order/1007", "gid://shopify/Order/1009"


@pytest.fixture()
def half_read_inbox():
    """Ben's inbox is read and holds nothing from him. Flo's read raises (Gmail did not answer
    for her), and Gus's comes back unavailable. Neither of the last two is known not to have
    written."""
    asked: list[dict] = []

    async def threads_for(**kwargs):
        asked.append(kwargs)
        sender = kwargs.get("sender")
        if sender == "flo@example.com":
            raise RuntimeError("Gmail did not answer")
        if sender == "gus@example.com":
            return {"available": False, "reason": "Gmail is rate-limiting us", "threads": []}
        return {"available": True, "threads": []}

    async def replied(thread_id):
        return False

    analytics_tools.bind_email(threads_for, replied)
    threads_for.asked = asked
    yield threads_for
    analytics_tools.bind_email(None, None)


@pytest.mark.usefixtures("owner_asking")
async def test_a_member_whose_inbox_was_not_read_is_never_in_the_rest(cache, half_read_inbox, convo, monkeypatch):
    """AC1-F-01. Before round 11 all three delayed orders went into the "not contacted" set —
    the set "draft an apology to the rest" acts on — while the count beside it said one. Only
    Ben's inbox was read; Flo and Gus are the unchecked set, and the counts and the sets agree."""
    london_now(monkeypatch)
    calls: list = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"},
                                      "title": "Delayed orders"}, session=convo, timeout_s=5, calls=calls)
    set_id = calls[-1].result["set"]["set_id"]
    assert set(convo.sets[set_id].members) == {BEN, FLO, GUS}

    await dispatch("email_query", {"set_id": set_id, "days": 30}, session=convo, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert calls[-1].ok, calls[-1]
    assert {c["sender"] for c in half_read_inbox.asked} == {"ben@example.com", "flo@example.com", "gus@example.com"}, "all three were asked for"

    assert result["counts"] == {"contacted": 0, "not_contacted": 1, "replied": 0, "needs_reply": 0, "unchecked": 2}, result["counts"]
    quiet = convo.sets[result["set_not_contacted"]["set_id"]]
    assert set(quiet.members) == {BEN}, "only a member whose inbox was read and held nothing from them"
    assert result["set_not_contacted"]["count"] == result["counts"]["not_contacted"], "the set and its count agree"
    unchecked = convo.sets[result["set_unchecked"]["set_id"]]
    assert set(unchecked.members) == {FLO, GUS} and unchecked.parent == set_id
    assert "set_contacted" not in result, "nobody is known to have written"
    assert convo.focus["set"] == set_id, "the set the owner asked about stays the one in focus"

    rows = {r["customer_name"]: r for r in result["rows"]}
    assert rows["Ben Bold"]["checked"] is True and rows["Ben Bold"]["latest_direction"] == "none"
    for who in ("Flo Fry", "Gus Gee"):
        assert rows[who]["checked"] is False and rows[who]["emailed"] is False, rows[who]
        assert rows[who]["latest_direction"] == "unknown" and rows[who]["confidence"] == "unknown", rows[who]
    assert "2 customer(s) could not be checked in Gmail" in result["note"]
    assert "held apart as the unchecked set" in result["note"]


@pytest.mark.usefixtures("owner_asking")
async def test_the_card_counts_only_what_was_read(cache, half_read_inbox, convo, monkeypatch):
    """AC1-F-01, on the glass: the correlation card's "no contact" is one, and the table marks
    the two unread rows as unknown rather than "no"."""
    from app.presentation import present

    london_now(monkeypatch)
    calls: list = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"},
                                      "title": "Delayed orders"}, session=convo, timeout_s=5, calls=calls)
    set_id = calls[-1].result["set"]["set_id"]
    await dispatch("email_query", {"set_id": set_id, "days": 30}, session=convo, timeout_s=5, calls=calls)
    items = present(calls[-1:], session=convo)
    metrics = {m["key"]: m["value"] for m in items[0]["data"]["metrics"]}
    assert metrics["not_contacted"] == "1" and items[0]["data"]["complete"] is False
    emailed = {r["cells"][0]: r["cells"][2] for r in items[1]["data"]["rows"]}
    assert emailed == {"Ben Bold": "no", "Flo Fry": "?", "Gus Gee": "?"}, emailed


# ================================================================ F-01: abandoned checkouts


class PagedStore(AbandonedStore):
    """Shopify's pages, as Shopify serves them: `first` checkouts at a time, `after` the cursor
    the last page ended on, and `hasNextPage` while there are more."""

    def __init__(self, count: int, *, fail_after_pages: int | None = None) -> None:
        super().__init__()
        self.checkouts = [(f"#C{i:03d}", 1.0, False, "", [(HOODIE, 1)], "10.00") for i in range(count)]
        self.fail_after_pages = fail_after_pages

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksAbandonedCheckouts" not in query:
            return await super().graphql(query, variables)
        variables = dict(variables or {})
        if self.fail_after_pages is not None and len(self.asked) >= self.fail_after_pages:
            self.asked.append(variables)
            raise ShopifyError("Shopify is rate-limiting us.")
        whole = await super().graphql(query, variables)
        edges = whole["data"]["abandonedCheckouts"]["edges"]
        start, size = int(variables.get("after") or 0), int(variables["n"])
        page = edges[start:start + size]
        return {"data": {"abandonedCheckouts": {"edges": page, "pageInfo": {
            "hasNextPage": start + size < len(edges), "endCursor": str(start + len(page))}}}}


def _bind(store: AbandonedStore) -> AbandonedStore:
    shopify_tools.bind(store)
    return store


async def test_the_count_and_the_value_are_the_whole_windows_when_shopify_has_more_pages():
    """F-01. Sixty checkouts, pages of twenty-five. The count used to be the first page's
    twenty-five and the value £250, on a card marked complete."""
    store = _bind(PagedStore(60))
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    assert [a.get("after") for a in store.asked] == [None, "25", "50"], store.asked
    assert body["count"] == 60 and body["value"] == "600.00" and body["value_display"] == "£600.00"
    assert body["complete"] is True and body["more"] is False and body["pages"] == 3
    assert body["partial"] == "" and body["note"] == abandoned.WHAT_IT_IS
    figures, ranking = abandoned.cards(body)
    assert figures.data["complete"] is True and figures.freshness.complete is True
    assert {m["label"]: m["value"] for m in figures.data["metrics"]}["checkouts abandoned"] == "60"
    assert ranking.data["rows"][0]["primary"]["value"] == "60", "the ranking is over the whole window too"


async def test_past_the_page_bound_the_figures_are_the_checkouts_read_and_say_so():
    """F-01. More than the bound allows: the figures are of what was read, every card says
    "at least", and the cards are not complete — the model reads the same sentence."""
    store = _bind(PagedStore(abandoned.MAX_PAGES * abandoned.DEFAULT_LIMIT + 20))
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    read = abandoned.MAX_PAGES * abandoned.DEFAULT_LIMIT
    assert len(store.asked) == abandoned.MAX_PAGES, "bounded: never a page past the bound"
    assert body["count"] == read and body["complete"] is False and body["more"] is True
    assert "Partial" in body["partial"] and "at least" in body["partial"] and body["partial"] in body["note"]
    assert abandoned.WHAT_IT_IS in body["note"]

    figures, ranking = abandoned.cards(body)
    metrics = {m["label"]: m["value"] for m in figures.data["metrics"]}
    assert metrics == {"checkouts abandoned, of those read": f"at least {read}",
                       "not taken, of those read": f"at least £{read * 10:,.2f}",
                       "average of those read": "£10.00"}, metrics
    assert figures.data["complete"] is False and figures.data["truncated"] is True
    assert figures.freshness.complete is False and figures.freshness.caveat
    assert "Partial" in figures.data["note"] and abandoned.WHAT_IT_IS in figures.data["note"]
    assert ranking.data["complete"] is False and ranking.freshness.complete is False
    assert "of those read" in ranking.data["subtitle"]
    assert {"value": f"at least {read}", "label": "abandoned"} in ranking.data["totals"]


async def test_a_later_page_that_fails_leaves_what_was_read_said_as_partial():
    """F-01. The first page answered and the second did not: the answer is the first page,
    labelled as partial, never the first page passed off as the window."""
    _bind(PagedStore(60, fail_after_pages=1))
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    assert body["count"] == abandoned.DEFAULT_LIMIT and body["complete"] is False
    assert "stopped answering" in body["partial"]
    assert abandoned.cards(body)[0].data["complete"] is False


async def test_a_first_page_that_fails_is_the_answer_failing():
    _bind(PagedStore(60, fail_after_pages=0))
    with pytest.raises(ShopifyError):
        await abandoned.shopify_abandoned_checkouts(days=14)


@pytest.mark.usefixtures("owner_asking")
async def test_the_models_read_of_a_window_past_the_bound_draws_incomplete_cards(convo):
    """F-01 through the dispatcher and the presenter, as the model's call is drawn."""
    from app.presentation import present

    _bind(PagedStore(abandoned.MAX_PAGES * abandoned.DEFAULT_LIMIT + 1))
    calls: list = []
    text = await dispatch(abandoned.READ_TOOL, {"days": 14}, session=convo, timeout_s=10, calls=calls)
    assert calls and calls[-1].ok, text
    assert "Partial" in text, "the model is told the figures are the checkouts read"
    drawn = [i for i in present(calls, session=convo) if i["type"] in ("metric_group", "ranking")]
    assert [i["type"] for i in drawn] == ["metric_group", "ranking"]
    assert all(i["data"]["complete"] is False and i["freshness"]["complete"] is False for i in drawn), drawn


def test_the_query_pages_by_cursor():
    assert "$after: String" in abandoned.ABANDONED_QUERY and "after: $after" in abandoned.ABANDONED_QUERY
    assert "endCursor" in abandoned.ABANDONED_QUERY
    assert registry.get(abandoned.READ_TOOL).write is None


# ================================================================ the golden world, tapped


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _open_orders_read_as(monkeypatch, *, period: str, complete: bool) -> None:
    """The order read for this period answers with no rows, complete or not — which is what the
    order cache says for the first questions after a restart, while it is still filling."""
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        result = await real(name, args, timeout_s=timeout_s)
        if name == "commerce_query" and str((args or {}).get("period") or "") == period and isinstance(result, dict):
            result = {k: v for k, v in result.items() if k != "set"}
            result.update({"rows": [], "row_count": 0, "complete": complete})
            result["note"] = "" if complete else "The server is still reading recent orders."
        return result

    monkeypatch.setattr(registry, "invoke", invoke)


# ================================================================ F-02: the Orders landing


async def test_an_incomplete_empty_open_orders_read_is_not_nothing_waiting(stage, monkeypatch):
    """F-02. The open-orders read answered with no rows and `complete: False`. Before round 11
    this said "Nothing is waiting to go out." with the hedge appended after it."""
    _open_orders_read_as(monkeypatch, period="last_30_days", complete=False)
    tapped = await stage.touch("open.area", area="orders", session_id="r11inc1")
    assert _ok(tapped), tapped.raw
    assert "Nothing is waiting to go out" not in tapped.answer, tapped.answer
    assert "None of the orders read so far are waiting to go out" in tapped.answer, tapped.answer
    assert "more may exist" in tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True, "and the answer is marked partial"


async def test_a_complete_empty_open_orders_read_is_nothing_waiting(stage, monkeypatch):
    """F-02's control: the same empty list from a complete read is the definitive answer."""
    _open_orders_read_as(monkeypatch, period="last_30_days", complete=True)
    tapped = await stage.touch("open.area", area="orders", session_id="r11inc2")
    assert _ok(tapped), tapped.raw
    assert "Nothing is waiting to go out." in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is False


async def test_an_incomplete_empty_today_is_not_none_in_today(stage, monkeypatch):
    """F-02, the other half of the landing: "None in today yet" is only for a complete read."""
    _open_orders_read_as(monkeypatch, period="today", complete=False)
    tapped = await stage.touch("open.area", area="orders", session_id="r11inc3")
    assert _ok(tapped), tapped.raw
    assert "None in today yet" not in tapped.answer, tapped.answer
    assert "None of today's orders read so far" in tapped.answer, tapped.answer
    assert (tapped.raw.get("changed") or {}).get("partial") is True


# ================================================================ R9-E-families1-E-01: the picker

CAP = "gid://shopify/ProductVariant/9301"
ORDER = data.BY_NAME["#1938"]


async def test_the_add_on_the_picker_stages_only_a_row_of_the_picker_on_screen(stage):
    """R9-E-families1-E-01, through `POST /command`. The order read issued the hoodie on it to
    this conversation; the picker on screen is the cap picker for the same order. An Add
    posting the hoodie — issued, of the right kind, for the order on screen — is refused, and
    nothing is calculated. The cap, a row of that picker, is prepared for that order."""
    session = "r11pick"
    await stage.open_order("1938", session_id=session)
    held = stage.runtime.sessions.get(session)
    assert HOODIE in held.issued_ids, "the order read showed the conversation the hoodie"

    picked = await stage.touch("order_edit.find", session_id=session, order_id=ORDER.order_id, product="crooks cap")
    assert _ok(picked), picked.raw
    picker = picked.data("variant_picker")
    offered = [c.get("variant_id") for c in picker.get("candidates") or []]
    assert picker.get("order_id") == ORDER.order_id and CAP in offered and HOODIE not in offered, offered

    refused = await stage.touch("order_edit.stage", session_id=session, order_id=ORDER.order_id, variant_id=HOODIE, quantity=1)
    assert not _ok(refused) and _code(refused) == "not_on_picker", refused.raw
    assert not refused.surfaces and not held.proposals, "no card, nothing waiting"
    assert not getattr(stage.store, "calculations", []), "not even a calculation reached the shop"

    added = await stage.touch("order_edit.stage", session_id=session, order_id=ORDER.order_id, variant_id=CAP, quantity=1)
    assert _ok(added), added.raw
    (proposal,) = [p for p in held.proposals if p.status.value == "PENDING"]
    assert proposal.entity_ref == ORDER.order_id and proposal.execution.get("variant_id") == CAP, proposal.execution
    assert getattr(stage.store, "mutations_sent", -1) == 0, "prepared, not applied"


# ================================================================ R9-E-families1-E-02: the address

SAID = "4417lighthousepony@example.com"     # the model's clean transcription of a spoken address


def _then_send(calls) -> dict:
    """The model's own send, straight after opening the composer: the composer's id and the
    address it wrote down, as Claude would pass them."""
    opened = next(c.result for c in calls if c.name == "gmail_compose_open")
    return {"compose_id": opened["compose_id"], "to": SAID, "subject": "A shoot on Sunday", "body": "Are you free on Sunday?"}


async def test_an_address_the_model_wrote_down_reaches_no_email_until_the_owner_checks_it(stage):
    """R9-E-families1-E-02, through `POST /turn` and `POST /command`. The model opens a composer
    with the address in canonical form and, in the same turn, calls the send itself with the
    composer's issued id. The write tool refuses it; the card says the address is for the owner
    to check; Send tapped is refused. Once the owner has typed the address, Send prepares it —
    that address, from the Mac's copy — and nothing has been sent."""
    session = "r11addr"
    said = await stage.ask("email 4417 lighthouse pony at example dot com and ask if they're free on Sunday",
                           ("gmail_compose_open", {"to": SAID, "subject": "A shoot on Sunday", "body": "Are you free on Sunday?"}),
                           ("gmail_send_new", _then_send), session_id=session)
    held = stage.runtime.sessions.get(session)
    sent = [c for c in said.raw.get("tool_calls") or [] if c.get("name") == "gmail_send_new"]
    assert sent and sent[0]["ok"] is False and "has not checked that address" in str(sent[0].get("error")), said.raw.get("tool_calls")
    assert not held.proposals and not said.surface("confirmation"), "no card, nothing waiting"
    to = said.data("email_compose").get("to") or {}
    assert to.get("value") == SAID and to.get("status") == "uncertain", to
    compose_id = str(said.data("email_compose").get("compose_id") or "")

    tapped = await stage.touch("compose.stage", session_id=session, compose_id=compose_id, mode="send")
    assert not _ok(tapped) and _code(tapped) == "not_ready", tapped.raw
    assert not held.proposals

    typed = await stage.touch("compose.field", session_id=session, compose_id=compose_id, field="to", value=SAID)
    assert _ok(typed) and (typed.data("email_compose").get("to") or {}).get("status") == "ok", typed.raw
    ready = await stage.touch("compose.stage", session_id=session, compose_id=compose_id, mode="send")
    assert _ok(ready), ready.raw
    (proposal,) = held.proposals
    assert proposal.operation == "gmail_send_new" and proposal.status.value == "PENDING"
    assert proposal.execution["to"] == SAID and proposal.summary["off_shopify"] is True


# ================================================================ R9-J-docs1-J-01: the README


async def test_saying_an_order_number_reads_no_order_before_claude_is_asked(shop):  # noqa: F811 — the route fixture
    """R9-J-docs1-J-01. The README used to tell the owner to say an order number so "the Mac
    looks the order up before Claude is asked". It does not: the sentence reaches the model as
    it was said, and at the moment the model is asked the Mac has read no order — nothing
    naming 1938 has gone to Shopify, and no card of it is drawn unless the model reads it."""
    said = "what's happening with order 1938"
    seen: dict = {}

    async def the_model(session, calls, text):
        seen["queries"] = list(shop.store.queries)
        return "Which part of it do you want?"

    shop.model.steps.append(the_model)
    body = await say(shop, said, "r11j01")
    assert shop.model.prompts[-1].split("\n")[1] == said, "the model is handed exactly what was said"
    looked_up = [(q.split("(")[0].strip()[:60], v) for q, v in seen["queries"]
                 if "1938" in str(v) or v.get("id") == BOUNDARY_ORDER or "CrooksOrderByName" in q]
    assert looked_up == [], f"the Mac read an order before the model was asked: {looked_up}"
    assert not [r for r in records(body) if r[1] == BOUNDARY_ORDER], records(body)
