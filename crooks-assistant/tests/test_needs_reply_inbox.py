""""Any emails need my attention", as the owner saw it answered after the trunk deployed.

He asked about his inbox and was answered about 25 recent customers: "10 of 25 customers
checked are waiting on a reply", a queue whose times read "11d ag›o" in no order at all, and
under it a revenue ranking of those 25 with the month's totals — 272 orders, £16,681.45 —
printed as "THIS LIST 25 customers £16,681.45 VALUE". Each part of that is held here:

  1. the question is answered from the inbox, and the answer says what it covered;
  2. only the answer is drawn — the list a read works from never reaches the glass;
  3. a list's stated value is the sum of its own rows, or it is labelled for what it is;
  4. the queue runs longest-waiting first, in the answer, on the card and under Next;
  5. a row's time has room beside its chevron, and a row is not a card inside the card.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

from app import progressive
from app.analytics.cache import OrderCache
from app.analytics.present import working_set_items
from app.families import landings as library
from app.presentation import present
from app.reads.scheduler import Read, ReadPlan, ReadResult, run_plan
from app.recipes import Ctx
from app.session.branch import Branch
from app.session.models import Session
from app.tools import analytics_tools, gmail_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, classify
from tests.test_analytics_tools import NOW, Clock, Store, london_now

WEB = Path(__file__).resolve().parent.parent / "web"
OURS = "orders@crooksldn.example"
DAY_MS = 86_400_000


def ago(days: float, *, now: float | None = None) -> int:
    """Gmail's own stamp for a message this many days before now, in epoch milliseconds."""
    return int(((NOW.timestamp() if now is None else now) - days * 86_400) * 1000)


def summary(thread_id: str, sender: str, subject: str, *, name: str = "", snippet: str = "", authenticated: bool = True) -> dict:
    return {"thread_id": thread_id, "from": name or sender.split("@")[0].title(), "from_email": sender, "subject": subject,
            "date": "", "snippet": snippet, "likely_bulk": False, "authenticated": authenticated}


def state(thread_id: str, *, inbound: list[int], outbound: list[int] | None = None) -> dict:
    """What `gmail_tools.reply_state` answers for a thread with these messages."""
    latest_in, latest_out = max(inbound, default=None), max(outbound or [], default=None)
    unanswered = [t for t in inbound if latest_out is None or t > latest_out]
    return {"thread_id": thread_id, "latest_inbound_at": latest_in, "latest_outbound_at": latest_out,
            "waiting_since": min(unanswered) if unanswered else None}


BEN_OLD, BEN_NEW, FLO, DANA, SHOPIFY, OURS_T, CY = (f"18f00000000000{n:02d}" for n in range(1, 8))


@pytest.fixture()
def cache(monkeypatch):
    london_now(monkeypatch)
    analytics_tools.bind(OrderCache(lambda: Store(), clock=Clock(NOW.timestamp())))
    yield
    analytics_tools.bind(None)


@pytest.fixture()
def inbox(cache):
    """The inbox as Gmail lists it, newest first: two customers, a stranger, a machine, us."""
    listed = [
        summary(BEN_NEW, "ben@example.com", "Also — sizing?"),
        summary(FLO, "flo@example.com", "Order 1007"),
        summary(CY, "cy@example.com", "Hello"),
        summary(BEN_OLD, "ben@example.com", "Where is order 1002?", snippet="still waiting on CROOKS-1002"),
        summary(DANA, "buyer@boutique.example", "Stockist enquiry", name="Dana Shop"),
        summary(SHOPIFY, "no-reply@shopify.example", "Abandoned checkout: order 1009"),
        summary(OURS_T, OURS, "Your order 1003"),
    ]
    states = {
        BEN_OLD: state(BEN_OLD, inbound=[ago(5)]),             # Ben asked five days ago…
        BEN_NEW: state(BEN_NEW, inbound=[ago(1)]),             # …and again yesterday. Five days' wait.
        FLO: state(FLO, inbound=[ago(9)], outbound=[ago(8)]),  # answered
        DANA: state(DANA, inbound=[ago(12)]),                  # not a customer, and still waiting
        SHOPIFY: state(SHOPIFY, inbound=[ago(0.5)]),
        OURS_T: state(OURS_T, inbound=[], outbound=[ago(2)]),
        # Cy's thread cannot be read: unknown, and said so.
    }
    asked: list[dict] = []
    read: list[str] = []

    async def inbox_for(**kwargs):
        asked.append(kwargs)
        return {"available": True, "threads": [dict(t) for t in listed], "full": False}

    async def reply_state(thread_id: str):
        read.append(thread_id)
        return states.get(thread_id)

    analytics_tools.bind_email(None, None, reply_state, own_address=OURS, inbox_for=inbox_for)
    yield {"asked": asked, "read": read, "listed": listed}
    analytics_tools.bind_email(None, None)


# ---------------------------------------------------------------- 1. the inbox is the question


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_inbox_itself_is_read_and_everyone_who_wrote_is_judged(inbox):
    session = Session(session_id="nr-inbox")
    session.turn_id = "turn_nr"
    calls: list = []
    text = await dispatch("email_query", {"days": 30}, session=session, timeout_s=5, calls=calls)
    body = calls[-1].result
    assert text.startswith("AMBER"), "customer data, read back before acting on it"
    assert inbox["asked"] == [{"days": 30}], "one listing of the inbox — not a customer set first"
    assert body["scope"] == "inbox" and body["window_complete"] is True
    rows = {r["customer_email"]: r for r in body["rows"]}
    assert set(rows) == {"ben@example.com", "flo@example.com", "cy@example.com", "buyer@boutique.example"}, (
        "the automated sender and our own mail are not people waiting on us")
    ben, dana = rows["ben@example.com"], rows["buyer@boutique.example"]
    # Matched to the shop where the order cache knows the address, and not where it does not.
    assert ben["known_customer"] and ben["customer_name"] == "Ben Bold" and ben["customer_id"] == "gid://shopify/Customer/2"
    assert ben["orders"] == ["CROOKS-1002"] and ben["related_orders"] == ["1002"] and ben["confidence"] == "confident"
    assert dana["known_customer"] is False and dana["customer_id"] == "" and dana["customer_name"] == "Dana Shop" and dana["confidence"] == "none"
    # One person, two threads, never merged: waiting since the FIRST unanswered message, and
    # the thread to open is the one they last wrote in.
    assert ben["needs_reply"] and ben["threads"] == 2 and ben["waiting_since"] == ago(5) and ben["last_thread_id"] == BEN_NEW
    assert rows["flo@example.com"]["needs_reply"] is False and rows["flo@example.com"]["replied"] is True
    assert rows["cy@example.com"]["checked"] is False and rows["cy@example.com"]["needs_reply"] is False
    assert body["counts"]["needs_reply"] == 2 and body["counts"]["unchecked"] == 1 and "1 thread(s) could not be checked" in body["note"]
    assert [r["customer_email"] for r in body["rows"]][:2] == ["buyer@boutique.example", "ben@example.com"], "longest wait first"
    assert set(inbox["read"]) == {BEN_OLD, BEN_NEW, FLO, DANA, CY}, "every thread from a person asked who spoke last"


async def test_the_inbox_read_is_a_read_and_needs_no_set():
    # No set is issued, and none is needed: the inbox is not a record the conversation was shown.
    assert classify("email_query", {"days": 30}).disposition is Disposition.EXECUTE_NOW
    # A set, when one is named, is still held to having been issued.
    assert classify("email_query", {"set_id": "set_abcdef123456"}).disposition is Disposition.DENY


async def test_a_slow_thread_is_counted_unchecked_and_the_answer_still_lands(inbox, monkeypatch):
    slow = analytics_tools._reply_state

    async def reply_state(thread_id: str):
        if thread_id == DANA:
            await asyncio.sleep(5)
        return await slow(thread_id)

    monkeypatch.setattr(analytics_tools, "_reply_state", reply_state)
    monkeypatch.setattr(analytics_tools, "INBOX_DEADLINE_S", 0.3)
    started = time.perf_counter()
    body = await analytics_tools.email_query(days=30)
    assert time.perf_counter() - started < 2.0, "the inbox read must land inside the fast lane"
    assert body["counts"]["unchecked"] == 2 and body["threads_checked"] == 3


async def test_a_listing_that_came_back_full_says_what_it_covered(inbox, monkeypatch):
    async def full(**kwargs):
        return {"available": True, "threads": [dict(t) for t in inbox["listed"]], "full": True}

    monkeypatch.setattr(analytics_tools, "_inbox_for", full)
    body = await analytics_tools.email_query(days=30)
    assert body["window_complete"] is False and body["source"].endswith("the newest 5")
    answer = library._needs_reply_render(_ctx(Session(session_id="nr-full")), ReadResult(values={"mail": body}))
    assert "in the inbox's newest 5 threads" in answer.answer and "last 30 days:" not in answer.answer, answer.answer
    assert "The newest 5 threads were checked; the last 30 days hold more." in answer.surfaces[0].data["note"]


async def test_the_listing_is_the_inbox_query_bounded_and_without_bulk(monkeypatch):
    seen: list[tuple[str, int]] = []

    def message(mid: str, thread: str, sender: str, **headers: str) -> dict:
        names = {"From": sender, "Subject": "hi", **headers}
        return {"id": mid, "threadId": thread, "snippet": "", "payload": {"headers": [{"name": k, "value": v} for k, v in names.items()]}}

    async def listing(client, query, limit):
        seen.append((query, limit))
        return [message("m1", "t1", "Ann <ann@example.com>"), message("m2", "t1", "Ann <ann@example.com>"),
                message("m3", "t2", "News <news@brand.example>", **{"List-Unsubscribe": "<mailto:x>"})]

    monkeypatch.setattr(gmail_tools, "_client", object())
    monkeypatch.setattr(gmail_tools, "_list_metadata", listing)
    found = await gmail_tools.inbox_threads(days=30, limit=3)
    assert seen == [(f"newer_than:30d {gmail_tools.BASE_QUERY}", 3)]
    assert [t["thread_id"] for t in found["threads"]] == ["t1"] and found["full"] is True


async def test_reply_state_says_since_when_they_have_been_waiting(monkeypatch):
    class Client:
        def thread_state(self, thread_id):
            return [{"labels": ["INBOX"], "at_ms": 1_000}, {"labels": ["SENT"], "at_ms": 2_000},
                    {"labels": ["INBOX"], "at_ms": 3_000}, {"labels": ["INBOX"], "at_ms": 4_000}, {"labels": ["DRAFT"], "at_ms": 5_000}]

    monkeypatch.setattr(gmail_tools, "_client", Client())
    got = await gmail_tools.reply_state("t1")
    assert got["waiting_since"] == 3_000 and got["latest_inbound_at"] == 4_000 and got["latest_direction"] == "inbound"


def test_the_fold_waits_from_the_first_message_nobody_answered():
    fold = analytics_tools._fold_reply_states
    # Asked on day 1, chased on day 3, never answered: waiting since day 1.
    assert fold([{"latest_inbound_at": 3_000, "latest_outbound_at": None, "waiting_since": 1_000}])["waiting_since"] == 1_000
    # A reply in another thread on day 2 answered day 1; what is still unanswered starts later.
    folded = fold([{"latest_inbound_at": 3_000, "latest_outbound_at": None, "waiting_since": 1_000},
                   {"latest_inbound_at": None, "latest_outbound_at": 2_000}])
    assert folded["needs_reply"] and folded["waiting_since"] == 3_000
    assert fold([{"latest_inbound_at": 1_000, "latest_outbound_at": 2_000, "waiting_since": None}])["waiting_since"] is None


def test_the_recipe_reads_the_inbox_and_nothing_else():
    """The queue is the Inbox landing's (the tapped dock icon); the sentence that used to reach
    a recipe of its own is the model's since 28 September 2026."""
    from app.recipes import RECIPES

    plan = library._inbox_plan(_ctx(Session(session_id="nr-plan")))
    queue = next(read for read in plan.reads if read.name == "mail")
    assert queue.tool == "email_query" and "set_id" not in queue.args and queue.args["days"] == 30
    assert queue.draws is False, "a working input: the recipe draws its own card"
    assert RECIPES["landing_inbox"].read_primitives == ("email_query", "gmail_search"), "no customer list read first"


# ------------------------------------------------------- 2 and 4. the answer, and its order


def _ctx(session: Session) -> Ctx:
    return Ctx(runtime=None, session=session, branch=Branch(branch_id="b", session_id=session.session_id),
               text="any emails need my attention")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_answer_is_the_queue_longest_waiting_first_and_nothing_else(inbox):
    session = Session(session_id="nr-answer")
    session.turn_id = "turn_answer"
    calls: list = []
    await dispatch("email_query", {"days": 30}, session=session, timeout_s=5, calls=calls)
    ctx = _ctx(session)
    answer = library._needs_reply_render(ctx, ReadResult(values={"mail": calls[-1].result}, calls=calls))
    assert answer.answer == "2 people are waiting on a reply in the inbox's last 30 days: Dana Shop and Ben Bold. 1 thread could not be checked."
    assert answer.drawn == [], "the read's own cards — the list it worked from — are not the answer"
    (surface,) = answer.surfaces
    rows = surface.data["threads"]
    assert [r["from"] for r in rows] == ["Dana Shop", "Ben Bold"]
    assert [r["thread_id"] for r in rows] == [DANA, BEN_NEW]
    assert rows[1]["snippet"] == "#1002 · 2 threads" and rows[0]["snippet"] == "" and rows[0]["known_customer"] is False
    # Next walks the THREADS, in the card's order, and every row can be opened.
    assert ctx.branch.workflow is not None and ctx.branch.workflow.kind == "emails"
    assert session.sets[ctx.branch.workflow.set_id].members == (DANA, BEN_NEW)
    assert {DANA, BEN_NEW} <= session.issued_ids


def test_the_rows_are_ordered_by_how_long_each_person_has_waited():
    now = time.time()
    waits = [11, 13, 13, 5, 9, 13, 7, 2]
    rows = [{"customer_name": f"Person {i}", "last_thread_id": f"{i:016x}", "needs_reply": True, "last_subject": "?",
             "latest_inbound_at": ago(0.1, now=now), "waiting_since": ago(days, now=now)} for i, days in enumerate(waits)]
    body = {"scope": "inbox", "days": 30, "window_complete": True, "threads_listed": 8, "threads_checked": 8, "rows": rows, "counts": {"unchecked": 0}}
    answer = library._needs_reply_render(_ctx(Session(session_id="nr-order")), ReadResult(values={"mail": body}))
    shown = [int(r["date"].rstrip("d ago")) for r in answer.surfaces[0].data["threads"]]
    assert shown == sorted(waits, reverse=True), shown
    assert answer.answer.startswith("8 people are waiting on a reply in the inbox's last 30 days: Person 1, Person 2, Person 5 and 5 others.")


def test_a_customer_set_is_still_named_as_what_it_was():
    """The set path is the model's (email_query over a listing it made). Said as that set, and
    never as the inbox."""
    row = {"customer_name": "Mia Jones", "last_thread_id": "aa70d3f83dbef06e", "needs_reply": True, "latest_inbound_at": 1_000}
    body = {"rows": [row], "counts": {"contacted": 1, "not_contacted": 24, "unchecked": 0}}
    answer = library._needs_reply_render(_ctx(Session(session_id="nr-set")), ReadResult(values={"mail": body}))
    assert answer.answer == "1 of the 25 customers checked is waiting on a reply: Mia Jones."


# ------------------------------------------------------------------ 2. the glass is the answer


def test_a_card_the_answer_does_not_contain_is_taken_off_the_glass():
    workspace = progressive.Workspace("s-glass", clock=Clock(0.0))
    workspace.shell(("email_list",))
    ranking = {"type": "ranking", "data": {"title": "Recent customers", "rows": [{"label": "Ann"}]}}
    strip = {"type": "working_set", "data": {"set_id": "set_abcdef123456", "count": 25}}
    workspace.facts([ranking, strip])
    queue = {"type": "email_list", "data": {"title": "Waiting on a reply", "threads": [{"thread_id": "t1"}]}}
    patches = workspace.complete([queue])
    assert [(p.op, p.render_id) for p in patches if p.op == "remove"] == [("remove", "ranking:Recent customers"), ("remove", "working_set:set_abcdef123456")]
    assert workspace.ledger.order == ["email_list:Waiting on a reply"]


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_read_that_does_not_draw_never_reaches_the_glass(cache):
    session = Session(session_id="s-quiet")
    session.turn_id = "turn_quiet"
    workspace = progressive.begin("s-quiet", turn_id="turn_quiet")
    try:
        await run_plan(ReadPlan([
            Read("customers", "commerce_query", {"entity": "customers", "period": "last_30_days", "limit": 2}, draws=False),
            Read("orders", "commerce_query", {"entity": "orders", "period": "last_30_days", "title": "Orders"}),
        ]), session=session, timeout_s=5.0)
        kinds = {identity.split(":", 1)[0] for identity in workspace.ledger.order}
        assert "ranking" not in kinds, workspace.ledger.order
        assert "order_list" in kinds, "a read that draws still draws"
    finally:
        progressive.forget("s-quiet")


# ---------------------------------------------------------- 3. a list's value is its own rows


def _money(value: float) -> str:
    return f"£{value:,.2f}"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_list_states_the_sum_of_its_own_rows_or_says_whose_totals_it_shows(cache):
    session = Session(session_id="s-totals")
    session.turn_id = "turn_totals"
    for limit in (2, 25):
        calls: list = []
        await dispatch("commerce_query", {"entity": "customers", "period": "last_30_days", "limit": limit, "title": "Recent customers"},
                       session=session, timeout_s=5, calls=calls)
        result = calls[-1].result
        rows = result["rows"]
        own = round(sum(r["revenue"] for r in rows), 2)
        # The set's value is what its members came to, whatever the period's total was.
        assert result["set"]["count"] == len(rows)
        assert result["set"]["totals"]["revenue"] == own and result["set"]["totals"]["customers"] == len(rows)
        strip = next(i for i in working_set_items(result) if i["type"] == "working_set")
        stated = [line["value"] for line in strip["data"]["lines"] if line["label"] == "value"]
        assert stated in ([], [_money(own)]), f"THIS LIST … VALUE must be the list's own: {stated} vs {_money(own)}"
        # The ranking's totals are the period's: labelled so whenever the rows are not all of it.
        ranking = next(i for i in present(calls) if i["type"] == "ranking")
        if result["truncated"]:
            assert result["totals"]["revenue"] > own
            assert ranking["data"]["totals_label"] == "Whole period (last 30 days), not just this list"
        else:
            assert result["totals"]["revenue"] == own and ranking["data"]["totals_label"] == ""


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_an_order_listing_of_a_number_is_worth_those_orders(cache):
    session = Session(session_id="s-orders")
    session.turn_id = "turn_orders"
    calls: list = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_30_days", "limit": 2, "title": "Two newest"},
                   session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    own = round(sum(float(r["total"]) for r in result["rows"]), 2)
    assert result["set"]["count"] == 2 and result["set"]["totals"]["revenue"] == own and result["totals"]["revenue"] > own


# ------------------------------------------------------------------------- 5. the row itself


def test_the_row_keeps_room_for_its_chevron_and_is_not_a_card():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    tight = re.search(r"\.rows\.tight \.row\{([^}]*)\}", css)
    assert tight is not None
    assert not re.search(r"(?<![-\w])padding:", tight.group(1)), (
        "the shorthand zeroes the right padding `.row.tappable` keeps for its chevron: '11d ag›o'")
    assert re.search(r"\.row\.tappable\{[^}]*padding-right:26px", css)
    assert re.search(r"\.rows > \.row\.tappable\{border-radius:0\}", css), (
        "a list row's divider is a border-top; a radius bends it into a card inside the card")


# --------------------------------------------------- the storefront's contact form (follow-up)
#
# CROOKSLDN's customers write through the shop's contact form, and Shopify delivers that From
# its own mailer with the customer in Reply-To and in the body — the shape
# tests/test_gmail_writes.py already replies to. The scan dropped every one of them as bulk,
# and then as automated, so the most likely enquiry of all could never be somebody waiting.

MAILER = "CROOKSLDN (Shopify) <mailer@shopify.com>"
FORM_INTRO = "You received a new message from your online store&#39;s contact form."
JO_FORM, ANN_FORM, FLO_FORM, BEN_ORDER, REPORT = (f"c1000000000000{n:02d}" for n in range(1, 6))


def gmail_message(mid: str, thread: str, *, sender: str, subject: str, snippet: str = "", reply_to: str = "", to: str = "",
                  at: int = 0, labels: tuple[str, ...] = ("INBOX",), **extra: str) -> dict:
    """A message as `messages.get(format="metadata")` returns it."""
    headers = {"From": sender, "Subject": subject, **({"Reply-To": reply_to} if reply_to else {}), **({"To": to} if to else {}), **extra}
    return {"id": mid, "threadId": thread, "labelIds": list(labels), "internalDate": str(at), "snippet": snippet,
            "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]}}


INBOX_LISTING = [
    # Jo is not a customer yet and asked through the form. Nobody has answered.
    gmail_message("m1", JO_FORM, sender=MAILER, reply_to="Jo Bloggs <jo@example.com>", at=ago(6),
                  subject="New customer message on September 3, 2026 at 10:14 am",
                  snippet=f"{FORM_INTRO} Country Code: GB Name: Jo Bloggs Email: jo@example.com Phone Number: Body: Do the joggers run small?"),
    # Ann asked through the form and we answered in the thread (Gmail's reply goes to Reply-To).
    gmail_message("m2", ANN_FORM, sender=MAILER, reply_to="Ann Able <ann@example.com>", at=ago(4),
                  subject="New customer message on September 5, 2026 at 9:02 am",
                  snippet=f"{FORM_INTRO} Country Code: GB Name: Ann Able Email: ann@example.com Body: Is 1001 on its way?"),
    # Flo's form came without Reply-To: the body names her. We answered with a new email.
    gmail_message("m3", FLO_FORM, sender=MAILER, at=ago(5), subject="New customer message on September 4, 2026 at 4:40 pm",
                  snippet=f"{FORM_INTRO} Country Code: IE Name: Flo Fry Email: flo@example.com Body: Can I change the size on 1007?"),
    # The same mailer's order notification — Reply-To the buyer — is not the buyer writing.
    gmail_message("m4", BEN_ORDER, sender="Shopify <mailer@shopify.com>", reply_to="Ben Bold <ben@example.com>", at=ago(7),
                  subject="[CROOKSLDN] Order #1002 placed by Ben Bold", snippet="Order summary Convict Joggers × 1 Yard Jeans × 1"),
    gmail_message("m5", REPORT, sender="Shopify <no-reply@shopify.com>", at=ago(1), subject="Your weekly store report",
                  snippet="Here is how CROOKSLDN did this week", **{"List-Unsubscribe": "<mailto:unsubscribe@shopify.com>"}),
]
SENT_LISTING = [
    gmail_message("s1", "d000000000000001", sender=OURS, to="Flo Fry <flo@example.com>", at=ago(2), labels=("SENT",), subject="Your order 1007"),
    gmail_message("s2", ANN_FORM, sender=OURS, to="Ann Able <ann@example.com>", at=ago(3), labels=("SENT",), subject="Re: New customer message"),
    # Written to Jo BEFORE she asked: it cannot have answered her.
    gmail_message("s3", "d000000000000003", sender=OURS, to="jo@example.com", at=ago(10), labels=("SENT",), subject="Welcome"),
    # Not ours — a message that merely names her — never counts as us writing.
    gmail_message("s4", "d000000000000004", sender="Someone <x@else.example>", to="jo@example.com", at=ago(1), subject="fwd"),
]


@pytest.fixture()
def storefront(cache, monkeypatch):
    queries: list[tuple[str, int, list[str] | None]] = []

    async def listing(client, query, limit, headers=None):
        queries.append((query, limit, headers))
        return [dict(m) for m in (SENT_LISTING if query.startswith("in:sent") else INBOX_LISTING)]

    states = {
        JO_FORM: state(JO_FORM, inbound=[ago(6)]),
        ANN_FORM: state(ANN_FORM, inbound=[ago(4)], outbound=[ago(3)]),   # the reply in the thread
        FLO_FORM: state(FLO_FORM, inbound=[ago(5)]),                      # nothing in HER thread
    }

    async def reply_state(thread_id: str):
        return states.get(thread_id)

    monkeypatch.setattr(gmail_tools, "_client", object())
    monkeypatch.setattr(gmail_tools, "_list_metadata", listing)
    analytics_tools.bind_email(None, None, reply_state, own_address=OURS, inbox_for=gmail_tools.inbox_threads, sent_for=gmail_tools.sent_to)
    yield queries
    analytics_tools.bind_email(None, None)


def test_a_contact_form_is_the_customer_who_filled_it_in_and_nothing_else_is():
    form = {"from": MAILER, "subject": "New customer message on September 3, 2026", "reply-to": "Jo Bloggs <jo@example.com>"}
    assert gmail_tools.contact_form(form, FORM_INTRO) == ("Jo Bloggs", "jo@example.com")
    # No Reply-To, or one that is Shopify's own: the body's Email field.
    body = f"{FORM_INTRO} Country Code: GB Name: Flo Fry Email: flo@example.com Phone Number: Body: hi"
    assert gmail_tools.contact_form({**form, "reply-to": ""}, body) == ("Flo Fry", "flo@example.com")
    assert gmail_tools.contact_form({**form, "reply-to": "mailer@shopify.com"}, body) == ("Flo Fry", "flo@example.com")
    assert gmail_tools.contact_form({**form, "reply-to": ""}, FORM_INTRO) is None, "nobody named: nobody to answer"
    # The same mailer's order notification, and the same subject from anyone else, are not it.
    order = {"from": "Shopify <mailer@shopify.com>", "subject": "[CROOKSLDN] Order #1002 placed by Ben Bold", "reply-to": "ben@example.com"}
    assert gmail_tools.contact_form(order, "Order summary") is None
    assert gmail_tools.contact_form({**form, "from": "Jo <jo@example.com>"}, FORM_INTRO) is None


async def test_the_inbox_listing_keeps_the_contact_form_and_drops_the_mailers_other_mail(storefront):
    found = await gmail_tools.inbox_threads(days=30)
    by_thread = {t["thread_id"]: t for t in found["threads"]}
    assert set(by_thread) == {JO_FORM, ANN_FORM, FLO_FORM}, "the order notification and the store report stay out"
    jo = by_thread[JO_FORM]
    assert (jo["from"], jo["from_email"], jo["via"], jo["relay"]) == ("Jo Bloggs", "jo@example.com", "contact_form", "mailer@shopify.com")
    assert jo["authenticated"] is False and jo["likely_bulk"] is False, "a typed address is a claim; Shopify's signature vouches for Shopify"
    assert by_thread[FLO_FORM]["from_email"] == "flo@example.com"


async def test_a_contact_form_nobody_answered_is_waiting(storefront):
    body = await analytics_tools.email_query(days=30)
    rows = {r["customer_email"]: r for r in body["rows"]}
    assert set(rows) == {"jo@example.com", "ann@example.com", "flo@example.com"}, "Ben's order notification is not Ben writing"
    jo = rows["jo@example.com"]
    assert jo["needs_reply"] is True and jo["via"] == "contact_form" and jo["waiting_since"] == ago(6)
    assert jo["known_customer"] is False, "not a customer yet, and still somebody waiting on us"
    answer = library._needs_reply_render(_ctx(Session(session_id="nr-form")), ReadResult(values={"mail": body}))
    assert answer.answer == "1 person is waiting on a reply in the inbox's last 30 days: Jo Bloggs."
    (row,) = answer.surfaces[0].data["threads"]
    assert row["thread_id"] == JO_FORM and row["snippet"] == "contact form"
    # One listing of Sent, for everyone the inbox named, metadata only.
    sent_queries = [q for q in storefront if q[0].startswith("in:sent")]
    assert sent_queries == [("in:sent newer_than:30d (to:ann@example.com OR to:flo@example.com OR to:jo@example.com)", gmail_tools.SENT_LIMIT, ["To", "Cc"])]


async def test_a_contact_form_answered_in_its_thread_is_not_waiting(storefront, monkeypatch):
    # Without the Sent listing at all: the reply in the thread answers her on its own.
    monkeypatch.setattr(analytics_tools, "_sent_for", None)
    rows = {r["customer_email"]: r for r in (await analytics_tools.email_query(days=30))["rows"]}
    ann = rows["ann@example.com"]
    assert ann["needs_reply"] is False and ann["replied"] is True and ann["known_customer"] and ann["customer_name"] == "Ann Able"
    assert rows["flo@example.com"]["needs_reply"] is True, "and without it, a new email to Flo cannot be seen"


async def test_a_contact_form_answered_with_a_new_email_is_not_waiting(storefront):
    rows = {r["customer_email"]: r for r in (await analytics_tools.email_query(days=30))["rows"]}
    flo = rows["flo@example.com"]
    assert flo["needs_reply"] is False and flo["replied"] is True and flo["latest_outbound_at"] == ago(2) and flo["waiting_since"] is None
    assert rows["jo@example.com"]["needs_reply"] is True, "an email to her from before she asked answers nothing"


async def test_what_we_sent_is_read_from_sent_mail_only(monkeypatch):
    async def listing(client, query, limit, headers=None):
        return [dict(m) for m in SENT_LISTING]

    monkeypatch.setattr(gmail_tools, "_client", object())
    monkeypatch.setattr(gmail_tools, "_list_metadata", listing)
    got = await gmail_tools.sent_to(["Jo@Example.com", "flo@example.com", "not an address"], days=30)
    assert got["latest"] == {"flo@example.com": ago(2), "jo@example.com": ago(10)}, "s4 names Jo but is not ours"


# ------------------------------------------------ the 2026-09-26 deploy review of these fixes


def _waiting_body(n: int, **extra) -> dict:
    now = time.time()
    rows = [{"customer_name": f"Person {i}", "last_thread_id": f"{i:016x}", "needs_reply": True, "last_subject": "?",
             "latest_inbound_at": ago(0.1, now=now), "waiting_since": ago(1 + i, now=now)} for i in range(n)]
    return {"scope": "inbox", "days": 30, "window_complete": True, "threads_listed": n, "threads_checked": n,
            "rows": rows, "counts": {"unchecked": 0}, **extra}


def test_only_the_threads_the_card_draws_are_issued_and_walkable():
    """F-04: a conversation reaches only a record it was shown. With more people waiting than the
    card draws, the threads past the card are neither issued nor on the walk."""
    session = Session(session_id="nr-shown")
    body = _waiting_body(library.WAITING_SHOWN + 4)
    ctx = _ctx(session)
    answer = library._needs_reply_render(ctx, ReadResult(values={"mail": body}))
    drawn = [r["thread_id"] for r in answer.surfaces[0].data["threads"]]
    assert len(drawn) == library.WAITING_SHOWN
    hidden = {r["last_thread_id"] for r in body["rows"]} - set(drawn)
    assert len(hidden) == 4 and not hidden & session.issued_ids
    assert set(drawn) <= session.issued_ids
    if ctx.branch.workflow is not None:
        assert set(session.sets[ctx.branch.workflow.set_id].members) <= set(drawn)
    assert f"The {library.WAITING_SHOWN} longest waits are shown." in answer.surfaces[0].data["note"]


@pytest.mark.parametrize(("sent", "said"), [
    ("none", "Replies sent as new emails could not be checked"),
    ("partial", "Only the newest sent emails were checked for replies"),
])
def test_a_reply_check_that_was_not_complete_is_said_in_the_answer_and_on_the_card(sent, said):
    """F-02: when what we sent as new emails was not read, or only its newest part was, someone
    shown as waiting may already have been answered, and the owner is told so."""
    answer = library._needs_reply_render(_ctx(Session(session_id=f"nr-sent-{sent}")),
                                         ReadResult(values={"mail": _waiting_body(2, sent_checked=sent)}))
    assert said in answer.answer and "may already have been answered" in answer.answer
    assert said in answer.surfaces[0].data["note"]
    complete = library._needs_reply_render(_ctx(Session(session_id="nr-sent-all")),
                                           ReadResult(values={"mail": _waiting_body(2, sent_checked="all")}))
    assert "may already have been answered" not in complete.answer


def test_asking_again_still_says_the_reply_check_was_not_complete():
    """F-02's repeat branch (the deploy review of 9c37973f): "Still Person 0 and Person 1." dropped
    the caveat with the scope sentence, so the answer the owner acts on no longer said the list
    may name people already answered. The caveat is said again; the answer is partial either way."""
    session = Session(session_id="nr-sent-again")
    first = library._needs_reply_render(_ctx(session), ReadResult(values={"mail": _waiting_body(2, sent_checked="partial")}))
    again = library._needs_reply_render(_ctx(session), ReadResult(values={"mail": _waiting_body(2, sent_checked="partial")}))
    assert again.trace["repeat"] is True and again.answer.startswith("Still ")
    assert "may already have been answered" in again.answer
    assert first.partial and again.partial
    complete = library._needs_reply_render(_ctx(Session(session_id="nr-sent-all-again")),
                                           ReadResult(values={"mail": _waiting_body(2, sent_checked="all")}))
    assert not complete.partial


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_scan_says_how_far_the_sent_check_reached(inbox, monkeypatch):
    for listing, expected in (({"available": True, "latest": {}, "full": True}, "partial"),
                              ({"available": False, "latest": {}}, "none"),
                              ({"available": True, "latest": {}, "full": False}, "all")):
        async def sent_for(addresses, *, days, _listing=listing):
            return _listing
        monkeypatch.setattr(analytics_tools, "_sent_for", sent_for)
        session = Session(session_id=f"nr-scan-{expected}")
        session.turn_id = "turn_scan"
        calls: list = []
        await dispatch("email_query", {"days": 30}, session=session, timeout_s=5, calls=calls)
        assert calls[-1].result["sent_checked"] == expected


def test_a_ranking_with_more_rows_than_it_draws_labels_its_totals_as_not_the_lists():
    """F-03: the engine's scope says whether its totals are its rows'; the presenter draws at most
    MAX_ROWS of them, so totals over more rows than drawn are labelled, and the card says it is cut."""
    from app.analytics import present as analytic

    rows = [{"key": f"c{i}", "label": f"Customer {i}", "revenue": 10.0, "orders": 1} for i in range(analytic.MAX_ROWS + 5)]
    result = {"entity": "customers", "metrics": ["revenue", "orders"], "rows": rows, "truncated": False,
              "totals_scope": "rows", "totals": {"revenue": 300.0, "orders": 30},
              "period": {"label": "last 30 days"}, "currency": "GBP"}
    card = analytic._ranking(result, "GBP")
    assert card["totals_label"] == "Whole period (last 30 days), not just this list"
    assert card["truncated"] is True
    fits = {**result, "rows": rows[:analytic.MAX_ROWS], "totals": {"revenue": 250.0, "orders": 25}}
    card = analytic._ranking(fits, "GBP")
    assert card["totals_label"] == "" and card["truncated"] is False
