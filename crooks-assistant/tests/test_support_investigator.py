"""The Customer Support Investigator, V1: one enquiry, investigated read-only, with the
evidence exposed and a reply drafted for the owner to approve.

Everything here runs against synthetic fixtures (tests/fixtures/support): invented people at
.invalid addresses, in the shapes the real read tools return. The real acceptance case is a
captured bundle replayed through the same code, and is not in the repository.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app import readonly
from app.context.order import summary
from app.support import EvidenceBundle, investigate_bundle, parse_enquiry
from app.support.enquiry import classify
from app.support.evidence import gather
from app.support.investigate import numbers_in
from app.support.redact import redact_bundle
from app.tools.registry import ToolError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "support"
KB = ROOT / "kb"
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)  # a Friday


def orders() -> dict:
    return {k: v for k, v in json.loads((FIXTURES / "orders.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}


def threads() -> dict:
    return {k: v for k, v in json.loads((FIXTURES / "threads.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}


class Readers:
    """Fake readers in the shapes the live ones return: the order search, the hydrated order,
    the inbox correlation and one thread. Every call is recorded, so a test can prove only
    reads were made."""

    def __init__(self, keys=(), *, inbox=(), gmail: str = "live", fail_search: bool = False) -> None:
        book = orders()
        self.orders = [book[k] for k in keys]
        box = threads()
        self.threads = [box[k] for k in inbox]
        self.gmail = gmail
        self.fail_search = fail_search
        self.calls: list[tuple] = []

    async def find_order(self, query: str) -> dict:
        self.calls.append(("find_order", query))
        if self.fail_search:
            raise RuntimeError("store down")
        q = query.strip()
        if q.isdigit():
            found = [o for o in self.orders if o["order_number"].endswith(f"-{q}")]
        elif "@" in q:
            found = [o for o in self.orders if o["customer_email"] == q.lower()]
        else:
            found = []
        found.sort(key=lambda o: o["placed_at"], reverse=True)
        result = {"query": query, "orders": [summary(o) for o in found]}
        if not found:
            result["note"] = f"No order found for {query!r}. Note that without the read_all_orders scope only the last 60 days of orders are visible."
        return result

    async def order_detail(self, order_id: str) -> dict:
        self.calls.append(("order_detail", order_id))
        order = next(o for o in self.orders if o["order_id"] == order_id)
        return {**order, "history": {"orders": order["customer"]["orders"]}, "pending": []}

    async def threads_for(self, *, sender: str = "", terms=(), **_) -> dict:
        self.calls.append(("threads_for", sender, tuple(terms)))
        if self.gmail == "unavailable":
            return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
        out = []
        for t in self.threads:
            s = t["summary"]
            if (sender and s["from_email"] == sender) or any(term and term in f"{s['subject']} {s['snippet']}" for term in terms):
                out.append(s)
        return {"available": True, "threads": out}

    async def read_thread(self, thread_id: str) -> dict:
        self.calls.append(("read_thread", thread_id))
        for t in self.threads:
            if t["thread"]["thread_id"] == thread_id:
                return t["thread"]
        raise ToolError(f"Could not read thread {thread_id}")

    def kwargs(self) -> dict:
        return {"find_order": self.find_order, "order_detail": self.order_detail, "threads_for": self.threads_for,
                "read_thread": self.read_thread, "kb_dir": KB, "now": lambda: NOW}

    @property
    def verbs(self) -> set[str]:
        return {c[0] for c in self.calls}


async def run(text: str, readers: Readers, *, subject: str = "", sender: str = ""):
    enquiry = parse_enquiry(text, subject=subject, sender_email=sender)
    bundle = await gather(enquiry, **readers.kwargs())
    return bundle, investigate_bundle(bundle)


def evidence_numbers(bundle: EvidenceBundle) -> set[str]:
    return numbers_in(json.dumps(bundle.to_dict()))


# ------------------------------------------------------------------------ the enquiry


@pytest.mark.parametrize("text, kind", [
    ("Where is my order?", "delivery"),
    ("I want to cancel my order please", "cancel"),
    ("Can I change the address on it?", "change_address"),
    ("It arrived damaged, the seam is ripped", "damaged"),
    ("You sent me the wrong size", "wrong_item"),
    ("One item is missing from the parcel", "missing_item"),
    ("I'd like to return it, it's too big", "return_exchange"),
    ("Do you do gift wrapping?", "other"),
])
def test_the_kind_of_enquiry_is_read_from_the_customers_words(text, kind):
    assert classify(text) == kind


def test_identifiers_come_from_the_subject_and_the_text_and_the_sender_is_not_a_mention():
    enquiry = parse_enquiry("Hi, it's about order 2101. My partner pat@fixture.invalid ordered it. Where is it?",
                            subject="Order 2101", sender_email="Sam@Fixture.invalid")
    assert set(enquiry.order_numbers) == {"2101"}
    assert enquiry.emails_mentioned == ("pat@fixture.invalid",)
    assert enquiry.sender_email == "sam@fixture.invalid"
    assert enquiry.asks[0] == "Where is it?", "questions come first"
    assert enquiry.kind == "delivery"


def test_a_phone_number_group_and_a_year_are_not_order_numbers():
    enquiry = parse_enquiry("Order CROOKS-1924 please. Call me on +44 7789 545133. Sent 19 Sep 2026.", sender_email="c@fixture.invalid")
    assert enquiry.order_numbers == ("1924",)
    assert parse_enquiry("Where is 2103?").order_numbers == ("2103",), "an uncued number still counts"
    assert parse_enquiry("Two orders: 2090 and order 2101").order_numbers == ("2101", "2090"), "the cued one comes first"


def test_the_asks_come_from_the_customers_own_words_and_what_they_quoted_of_themselves():
    text = ("Hi again. Please can you confirm.\n\nSam\n\n+44 7700 900123\n\n"
            "On Sat, 19 Sep 2026 at 08:41, Sam Fixture <sam@fixture.invalid>\nwrote:\n\n> Hi\n>\n> I'd like to return this item - too big.\n>\n"
            "> Can you confirm the process?\n>\n> ---------- Forwarded message ---------\n> From: CROOKS <shop@fixture.invalid>\n> Subject: Order CROOKS-2090 confirmed\n> Total 54.00 GBP\n")
    enquiry = parse_enquiry(text, subject="Re: Order CROOKS-2090 confirmed", sender_email="sam@fixture.invalid")
    assert enquiry.asks[0] == "Can you confirm the process?"
    assert "Please can you confirm." in enquiry.asks
    assert not any("Forwarded" in a or "GBP" in a or "7700" in a for a in enquiry.asks)
    assert enquiry.kind == "return_exchange" and enquiry.order_numbers == ("2090",)
    quoted_ours = "Thanks!\n\nOn Mon, 14 Sep 2026 at 10:00, CROOKS <shop@fixture.invalid> wrote:\n> Could you send a photo of the label?\n"
    assert not any("photo" in a for a in parse_enquiry(quoted_ours, sender_email="sam@fixture.invalid").asks), "what they quoted of ours is not their ask"


def test_soft_line_breaks_are_joined_and_greetings_are_not_asks():
    enquiry = parse_enquiry("Good evening,\n\nI was wondering if you could let me\nknow when it ships.\n\nThank you,\nSam")
    assert enquiry.asks == ("I was wondering if you could let me know when it ships.",)


# --------------------------------------------------------------------- identification


async def test_a_named_order_from_its_own_address_is_identified_with_confidence():
    r = Readers(["late_uk", "older_same_customer"], inbox=["late_uk_chase", "unrelated"])
    bundle, result = await run("Where is my order 2101? It hasn't arrived.", r, sender="sam@fixture.invalid")
    ident = result["identification"]
    assert ident["status"] == "identified" and ident["confidence"] == "confident"
    assert ident["order_number"] == "CROOKS-2101"
    assert "written from the email address on the order" in ident["reasons"]
    assert r.calls[:2] == [("find_order", "2101"), ("order_detail", "gid://shopify/Order/2101")]
    assert r.verbs <= {"find_order", "order_detail", "threads_for", "read_thread"}, "reads, and nothing else"


async def test_a_named_order_from_another_address_is_only_possible_and_says_so():
    r = Readers(["late_uk"])
    _, result = await run("Where is order 2101?", r, sender="someone@else.invalid")
    ident = result["identification"]
    assert ident["status"] == "identified" and ident["confidence"] == "possible"
    assert "the sender's address is not the one on the order" in ident["reasons"]
    assert any(u["text"].startswith("Whether the person writing is the customer") for u in result["unknowns"])


async def test_the_only_recent_order_for_the_address_is_identified_as_possible():
    r = Readers(["unfulfilled_held"])
    _, result = await run("Where is my order?", r, sender="alex@fixture.invalid")
    ident = result["identification"]
    assert ident["status"] == "identified" and ident["confidence"] == "possible"
    assert ident["order_number"] == "CROOKS-2102"
    assert r.calls[0] == ("find_order", "alex@fixture.invalid")


async def test_two_orders_for_the_address_and_no_number_is_ambiguous_and_the_draft_asks():
    r = Readers(["late_uk", "older_same_customer"], inbox=["late_uk_chase"])
    bundle, result = await run("Where is my order? Still waiting.", r, sender="sam@fixture.invalid")
    ident = result["identification"]
    assert ident["status"] == "ambiguous" and ident["confidence"] == "none"
    assert [c["order_number"] for c in ident["candidates"]] == ["CROOKS-2101", "CROOKS-2090"]
    assert all(c["same_sender"] for c in ident["candidates"])
    assert "order_detail" not in r.verbs, "no order is read until one is chosen"
    body = result["reply_draft"]["body"]
    assert "CROOKS-2101, CROOKS-2090" in body and "Which one is this about?" in body
    assert bundle.threads and bundle.threads[0]["match"] == "sender", "the sender's own thread is still gathered"


async def test_an_unknown_number_is_not_found_and_the_draft_invents_nothing():
    r = Readers(["late_uk"])
    _, result = await run("Where is order 9999?", r)
    assert result["identification"]["status"] == "not_found"
    body = result["reply_draft"]["body"]
    assert "order number from your confirmation email and the email address you ordered with" in body
    assert numbers_in(body) == set()


async def test_no_identifier_at_all_is_said_so_and_nothing_is_searched():
    r = Readers(["late_uk"])
    bundle, result = await run("Where is my order?", r)
    assert result["identification"]["status"] == "no_identifier"
    assert r.calls == []
    assert any("no identifier" in p for p in bundle.problems)


async def test_a_store_that_does_not_answer_is_a_named_problem_not_a_crash():
    r = Readers(["late_uk"], fail_search=True)
    bundle, result = await run("Where is order 2101?", r, sender="sam@fixture.invalid")
    assert result["identification"]["status"] == "unavailable"
    assert any(p.startswith("order search '2101' failed: RuntimeError") for p in bundle.problems)
    assert bundle.sources["shopify"].startswith("unavailable")
    assert result["approval"]["required"] is True


# ------------------------------------------------- facts, inference, unknowns


async def test_facts_inference_and_unknowns_are_kept_apart_for_a_late_uk_parcel():
    r = Readers(["late_uk", "older_same_customer"], inbox=["late_uk_chase", "unrelated"])
    bundle, result = await run("Order 2101 still hasn't arrived, any update?", r, sender="sam@fixture.invalid")
    facts = [f["text"] for f in result["facts"]]
    inferences = [f["text"] for f in result["inferences"]]
    unknowns = [f["text"] for f in result["unknowns"]]
    assert "Fulfilment recorded on 11 Sep 2026: Royal Mail, tracking RM123456789GB (https://track.example.invalid/RM123456789GB); status IN_TRANSIT." in facts
    assert "Our earlier reply in that thread gave the tracking number RM123456789GB." in facts
    assert any("running late by about 3 working day(s)" in i for i in inferences)
    assert any("The customer is waiting on us" in i for i in inferences)
    assert any("no carrier tracking is integrated" in u for u in unknowns)
    assert any("late by policy" in d for d in result["owner_decisions"])
    refs = {e["ref"] for e in result["evidence"]}
    for finding in result["facts"] + result["inferences"]:
        assert finding["evidence"], f"a statement without evidence: {finding['text']}"
        assert set(finding["evidence"]) <= refs, finding
    assert "gmail:thread:18f2a9c0b1d2e301" in refs and "gmail:thread:18f2a9c0b1d2e399" not in refs, "the unrelated thread is not evidence"


async def test_a_system_email_about_the_order_is_evidence_but_not_the_customer_waiting():
    r = Readers(["late_uk"], inbox=["system_notice"])
    bundle, result = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    assert bundle.threads and bundle.threads[0]["match"] == "order_number"
    assert any("matched by the order number, not from the customer's address" in f["text"] for f in result["facts"])
    assert not any("waiting on us" in i["text"] or "without a reply" in i["text"] for i in result["inferences"])


async def test_two_unanswered_messages_are_named_and_the_draft_apologises():
    r = Readers(["late_uk"], inbox=["two_chases"])
    _, result = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    assert any(i["text"].startswith("The customer has written 2 time(s) in thread 'Order 2101' without a reply from us") for i in result["inferences"])
    body = result["reply_draft"]["body"]
    assert "Sorry for the slow reply." in body and body.count("Sorry") == 1


async def test_an_order_not_dispatched_after_the_grace_period_is_flagged_and_the_note_stays_internal():
    r = Readers(["unfulfilled_held"])
    _, result = await run("Any update on my order 2102?", r, sender="alex@fixture.invalid")
    assert any("something has held it" in i["text"] for i in result["inferences"])
    assert any("has no fulfilment recorded 5 working day(s) on" in d for d in result["owner_decisions"])
    assert any(f["text"].startswith("Internal order note (not for the customer): Customer phoned") for f in result["facts"])
    body = result["reply_draft"]["body"]
    assert "neighbour" not in body and "phoned" not in body
    assert "Our records show no fulfilment for it yet" in body and "It should have gone out by now" in body
    assert "dispatched" not in body.lower()


async def test_a_cancelled_order_is_answered_from_the_cancellation_and_the_refund():
    r = Readers(["cancelled"])
    _, result = await run("Where is my order 2103?", r, sender="jo@fixture.invalid")
    assert any(i["text"].startswith("The order was cancelled") for i in result["inferences"])
    body = result["reply_draft"]["body"]
    assert "cancelled on 13 Sep 2026" in body and "£45.00 was refunded on 13 Sep 2026" in body
    assert "dispatched" not in body


async def test_an_international_parcel_is_judged_by_the_international_window():
    r = Readers(["international"])
    _, result = await run("Where is my order 2104?", r, sender="kim@fixture.invalid")
    assert any("international window" in i["text"] and "late by about 3 day(s)" in i["text"] for i in result["inferences"])
    assert "CP123456789DE" in result["reply_draft"]["body"]


async def test_a_fulfilment_without_tracking_is_an_unknown_not_a_guess():
    r = Readers(["untracked"])
    bundle, result = await run("Where is my order 2105?", r, sender="ash@fixture.invalid")
    assert any("no tracking number on it" in f["text"] for f in result["facts"])
    assert any(u["text"].startswith("The carrier and tracking reference: none recorded") for u in result["unknowns"])
    body = result["reply_draft"]["body"]
    assert "We do not have a tracking reference on file for it, so we need to check with the courier before we can say where it is." in body
    assert "Our records show it as fulfilled on 15 Sep 2026" in body
    assert "dispatched" not in body.lower(), "FULFILLED without tracking records no movement (S-01R)"
    assert numbers_in(body) <= evidence_numbers(bundle)


async def test_an_untracked_fulfilment_whose_status_records_movement_is_still_dispatched():
    r = Readers(["untracked_moving"])
    _, result = await run("Where is my order 2109?", r, sender="ash@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "It was dispatched on 15 Sep 2026 with Royal Mail" in body, "IN_TRANSIT is movement Shopify recorded"
    assert "We do not have a tracking reference on file for it, so we need to check with the courier before we can say where it is." in body


async def test_a_label_without_a_carrier_scan_is_not_called_dispatched():
    r = Readers(["label_only_us"])
    bundle, result = await run("My tracking only shows label created. Has my order 2107 actually shipped?", r, sender="jay@fixture.invalid")
    assert any("not established from our records" in i["text"] and "CONFIRMED" in i["text"] for i in result["inferences"])
    assert any("Label created 2 day(s) ago for an international address" in i["text"] for i in result["inferences"])
    assert any("confirm with the courier whether the parcel was collected" in d for d in result["owner_decisions"])
    assert any(f["text"].startswith("Shopify event, 15 Sep 2026: Shipping app sent a shipping confirmation email") for f in result["facts"])
    assert any("sending is recorded, receipt is not visible" in u["text"] for u in result["unknowns"])
    assert any("The first fulfilment was recorded 2 working day(s) after the order was placed" in i["text"] for i in result["inferences"])
    body = result["reply_draft"]["body"]
    assert body.startswith("Hi Jay,"), "a lower-case store name is still a name"
    assert "A shipping label was created for it on 15 Sep 2026 with FedEx, tracking number 877200000110" in body
    assert "international delivery usually takes seven to fourteen days" in body
    assert "Our system currently shows the shipment as CONFIRMED rather than picked up or in transit" in body
    assert "we cannot confirm from our records that FedEx has collected it yet" in body
    assert "We need to check that with the courier before we can give you a definite update." in body
    assert "It was dispatched" not in body and "checking with them" not in body
    assert numbers_in(body) <= evidence_numbers(bundle)


async def test_a_delivered_parcel_is_answered_from_the_delivery_scan():
    r = Readers(["delivered_return_open"])
    _, result = await run("Where is my order 2108? Nothing has arrived.", r, sender="chris@fixture.invalid")
    assert any(i["text"].startswith("The carrier has reported the parcel delivered on 10 Sep 2026") for i in result["inferences"])
    assert not any("running late" in i["text"] for i in result["inferences"])
    assert any("check the proof of delivery" in d for d in result["owner_decisions"])
    assert any(u["text"].startswith("Whether the parcel is actually with the customer") for u in result["unknowns"])
    body = result["reply_draft"]["body"]
    assert "Our records show it was delivered on 10 Sep 2026 by Royal Mail, tracking number VU000000001GB" in body
    assert "check with neighbours" in body


async def test_an_open_return_is_recognised_and_not_restarted():
    r = Readers(["delivered_return_open"])
    _, result = await run("I'd like to return order 2108, it's too big. Can you confirm the process?", r, sender="chris@fixture.invalid")
    assert any(i["text"].startswith("A return is already open on this order (CROOKS-2108-R1)") for i in result["inferences"])
    assert "Order CROOKS-2108: approve or decline the open return CROOKS-2108-R1 and send the return instructions." in result["owner_decisions"]
    assert "Return status on the order: IN_PROGRESS." in [f["text"] for f in result["facts"]]
    assert "Shopify event, 12 Sep 2026: Returns app created return CROOKS-2108-R1." in [f["text"] for f in result["facts"]]
    body = result["reply_draft"]["body"]
    assert "Your return request is already open on our side (CROOKS-2108-R1) (status IN_PROGRESS), so you do not need to submit another request." in body
    assert "Once it has been reviewed, we can confirm the outcome and the return instructions." in body
    assert "pending approval" not in body, "nothing read said so"
    assert "within fourteen days of delivery" in body and "swap it for" not in body and "confirming it now" not in body


@pytest.mark.parametrize("keys, text, sender", [
    (["label_only_us"], "Has my order 2107 shipped? Tracking says label created", "jay@fixture.invalid"),
    (["delivered_return_open"], "Where is my order 2108?", "chris@fixture.invalid"),
    (["delivered_return_open"], "I want to return 2108", "chris@fixture.invalid"),
    (["late_uk", "older_same_customer"], "Where is my order 2101?", "sam@fixture.invalid"),
    (["late_uk", "older_same_customer"], "Where is my order?", "sam@fixture.invalid"),
    (["unfulfilled_held"], "Please cancel order 2102", "alex@fixture.invalid"),
    (["cancelled"], "Where is 2103?", "jo@fixture.invalid"),
    (["international"], "You sent the wrong size on 2104", "kim@fixture.invalid"),
    (["untracked"], "Order 2105 arrived damaged", "ash@fixture.invalid"),
    (["late_uk"], "Where is order 9999?", ""),
    (["late_uk"], "Where is my order 2101?", "stranger@else.invalid"),
])
async def test_the_draft_never_carries_a_number_the_evidence_does_not(keys, text, sender):
    r = Readers(keys, inbox=["late_uk_chase"])
    bundle, result = await run(text, r, sender=sender)
    draft = result["reply_draft"]
    assert numbers_in(draft["body"]) <= evidence_numbers(bundle), draft["body"]
    assert draft["requires_owner_approval"] is True
    assert draft["external_effects"].startswith("none")
    assert r.verbs <= {"find_order", "order_detail", "threads_for", "read_thread"}


# ---------------------------------------------------------------------- the drafts


async def test_a_cancellation_after_dispatch_is_answered_as_a_return_and_not_performed():
    r = Readers(["late_uk"])
    _, result = await run("Please cancel order 2101", r, sender="sam@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "we cannot cancel it now" in body and "fourteen days to return it" in body
    assert "Cancel order CROOKS-2101? The recorded status is IN_TRANSIT: it has already been dispatched, so a cancellation would be a return instead." in result["owner_decisions"]
    assert r.verbs <= {"find_order", "order_detail", "threads_for"}


async def test_a_cancellation_before_dispatch_is_a_decision_for_the_owner_not_an_action():
    r = Readers(["unfulfilled_held"])
    _, result = await run("Please cancel my order 2102", r, sender="alex@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "so it can still be cancelled" in body
    assert "Cancel order CROOKS-2102? Our records show no fulfilment." in result["owner_decisions"]
    assert "Our records show no fulfilment for it yet (placed on 12 Sep 2026), so it can still be cancelled." in body
    assert result["approval"]["external_effects_so_far"] == "none"


async def test_an_address_change_before_dispatch_asks_for_the_new_address():
    r = Readers(["unfulfilled_held"])
    _, result = await run("Can I change the address on order 2102?", r, sender="alex@fixture.invalid")
    assert "reply with the full new address, including the postcode" in result["reply_draft"]["body"]


async def test_damage_asks_for_a_photo_and_puts_the_remedy_to_the_owner():
    r = Readers(["late_uk"])
    _, result = await run("Order 2101 arrived damaged, the jeans are ripped", r, sender="sam@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "Damage in transit is on us to sort" in body and "photo of the damage" in body
    assert any("replacement, exchange or refund once the photo arrives" in d for d in result["owner_decisions"])
    assert any(u["text"].startswith("What actually arrived") for u in result["unknowns"])


async def test_a_wrong_or_missing_item_is_answered_from_what_was_ordered():
    r = Readers(["international"])
    _, wrong = await run("You sent me the wrong size on order 2104", r, sender="kim@fixture.invalid")
    assert "Your order was for 2 x Yard Jeans (Blue Wash / L)" in wrong["reply_draft"]["body"]
    _, missing = await run("Order 2104: only received one pair, one is missing", r, sender="kim@fixture.invalid")
    assert "should have had 2 x Yard Jeans (Blue Wash / L)" in missing["reply_draft"]["body"]


async def test_a_return_quotes_the_published_policy_line():
    r = Readers(["older_same_customer"])
    _, result = await run("I'd like to return order 2090, it's too big", r, sender="sam@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "returns and exchanges are within fourteen days of delivery for unworn items with the tags on" in body
    assert "kb:returns" in result["reply_draft"]["based_on"]


UNDERWAY = re.compile(r"\bwe (are|have|were|'re|'ve) (checking|chasing|finding|confirming|passing|passed|arranging|looking|sorting|updating|working)\b|\bwe (will|'ll|shall)\b|\bwe're \w+ing\b", re.I)


@pytest.mark.parametrize("keys, inbox, text, sender", [
    (["label_only_us"], [], "Tracking only shows label created. Has my order 2107 shipped?", "jay@fixture.invalid"),
    (["delivered_return_open"], ["return_pending"], "I'd like to return order 2108, too big. Can you confirm the process?", "chris@fixture.invalid"),
    (["delivered_return_open"], [], "Where is my order 2108? Nothing has arrived.", "chris@fixture.invalid"),
    (["late_uk", "older_same_customer"], ["late_uk_chase"], "Where is my order 2101?", "sam@fixture.invalid"),
    (["late_uk"], ["two_chases"], "Where is my order 2101?", "sam@fixture.invalid"),
    (["unfulfilled_held"], [], "Any update on my order 2102?", "alex@fixture.invalid"),
    (["label_only_us"], [], "Please cancel my order 2107", "jay@fixture.invalid"),
    (["label_only_us"], [], "Can I change the address on order 2107?", "jay@fixture.invalid"),
    (["untracked"], [], "Please cancel order 2105", "ash@fixture.invalid"),
    (["delivered_return_open"], [], "Please cancel order 2108", "chris@fixture.invalid"),
    (["unfulfilled_held"], [], "Please cancel my order 2102", "alex@fixture.invalid"),
    (["unfulfilled_held"], [], "Can I change the address on order 2102?", "alex@fixture.invalid"),
    (["late_uk"], [], "Please cancel order 2101", "sam@fixture.invalid"),
    (["late_uk"], [], "I moved house, can you change the address on order 2101?", "sam@fixture.invalid"),
    (["cancelled"], [], "Where is my order 2103?", "jo@fixture.invalid"),
    (["international"], [], "You sent me the wrong size on order 2104", "kim@fixture.invalid"),
    (["international"], [], "Order 2104: one item is missing", "kim@fixture.invalid"),
    (["untracked"], [], "Where is my order 2105?", "ash@fixture.invalid"),
    (["untracked_moving"], [], "Where is my order 2109?", "ash@fixture.invalid"),
    (["late_uk"], [], "Order 2101 arrived damaged", "sam@fixture.invalid"),
    (["older_same_customer"], [], "I'd like to return order 2090, too big", "sam@fixture.invalid"),
    (["late_uk"], [], "Where is order 9999?", ""),
    (["late_uk", "older_same_customer"], [], "Where is my order?", "sam@fixture.invalid"),
])
async def test_no_draft_claims_an_internal_action_is_underway_or_promised(keys, inbox, text, sender):
    """S-01: a draft states facts, uncertainty, what still needs doing, asks and policy; it never
    says we are checking, chasing, confirming or have passed anything on, and never promises
    an internal action, because nothing here does any of that."""
    r = Readers(keys, inbox=inbox)
    _, result = await run(text, r, sender=sender)
    body = result["reply_draft"]["body"]
    assert not UNDERWAY.search(body), body
    for phrase in ("we are checking", "we are chasing", "we are finding out", "we have passed", "we are confirming", "will confirm", "will update you", "will come back to you"):
        assert phrase not in body.lower(), (phrase, body)


async def test_an_open_return_that_the_returns_system_says_is_pending_approval_is_said_so_with_its_evidence():
    r = Readers(["delivered_return_open"], inbox=["return_pending"])
    bundle, result = await run("I'd like to return order 2108, too big. Can you confirm the process?", r, sender="chris@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "Your return request is already open on our side (CROOKS-2108-R1) and is currently pending approval, so you do not need to submit another request." in body
    assert "Once it has been reviewed, we can confirm the outcome and the return instructions." in body
    assert "gmail:thread:18f2a9c0b1d2e330" in result["reply_draft"]["based_on"], "the pending-approval statement cites the message that says so"
    assert "confirming it now" not in body


async def test_unresolved_cancel_held_and_untracked_cases_say_what_needs_doing_not_what_is_being_done():
    cancel = (await run("Please cancel my order 2102", Readers(["unfulfilled_held"]), sender="alex@fixture.invalid"))[1]["reply_draft"]["body"]
    assert "Cancelling it is a step we need to take on our side" in cancel and "passed it to the team" not in cancel
    held = (await run("Any update on my order 2102?", Readers(["unfulfilled_held"]), sender="alex@fixture.invalid"))[1]["reply_draft"]["body"]
    assert "we need to find out what has held it before we can give you a date" in held and "finding out" not in held
    untracked = (await run("Where is my order 2105?", Readers(["untracked"]), sender="ash@fixture.invalid"))[1]["reply_draft"]["body"]
    assert "we need to check with the courier before we can say where it is" in untracked and "checking with the courier" not in untracked
    assert "dispatched" not in untracked.lower() and "Our records show it as fulfilled on" in untracked
    late = (await run("Where is my order 2101?", Readers(["late_uk"]), sender="sam@fixture.invalid"))[1]["reply_draft"]["body"]
    assert "It was dispatched on 11 Sep 2026 with Royal Mail" in late, "IN_TRANSIT is movement Shopify recorded"
    assert "it needs chasing with the courier" in late and "we are chasing" not in late
    assert "that is on us to sort, and the options are chasing the courier, a replacement or a refund" in late


async def test_a_cancellation_against_a_label_only_fulfilment_is_uncertainty_not_a_refusal():
    """S-01C: a fulfilment record is not dispatch. CONFIRMED with a label and no movement is said
    as what the records show and what still needs establishing, never as already dispatched
    or as making cancellation impossible."""
    r = Readers(["label_only_us"])
    _, result = await run("Please cancel my order 2107", r, sender="jay@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "already been dispatched" not in body and "dispatched" not in body.lower()
    assert "cannot cancel" not in body and "can no longer be cancelled" not in body
    assert "Our records show a fulfilment for it created on 15 Sep 2026 (status CONFIRMED), but not whether the parcel has actually left us, so we cannot say yet whether it can still be cancelled." in body
    assert "That needs checking on our side before we can give you an answer." in body
    assert "international delivery usually takes" not in body and "If it does not turn up" not in body, "delivery-window lines belong to a delivery enquiry"
    decision = next(d for d in result["owner_decisions"] if d.startswith("Cancel order CROOKS-2107?"))
    assert "without recorded movement" in decision and "not established" in decision and "already been dispatched" not in decision


async def test_an_address_change_against_a_label_only_fulfilment_is_uncertainty_not_a_refusal():
    r = Readers(["label_only_us"])
    _, result = await run("Can I change the address on order 2107?", r, sender="jay@fixture.invalid")
    body = result["reply_draft"]["body"]
    assert "already been dispatched" not in body and "dispatched" not in body.lower()
    assert "cannot change the address" not in body and "can no longer be changed" not in body
    assert "so we cannot say yet whether the address can still be changed." in body
    assert "If you reply with the full new address, including the postcode, we can see what is possible once that is checked." in body
    decision = next(d for d in result["owner_decisions"] if d.startswith("Change the delivery address on order CROOKS-2107?"))
    assert "without recorded movement" in decision and "not established" in decision


async def test_cancel_and_address_change_against_a_moving_fulfilment_still_say_dispatched():
    r = Readers(["late_uk"])
    _, cancel = await run("Please cancel order 2101", r, sender="sam@fixture.invalid")
    assert "Because it has already been dispatched we cannot cancel it now; once it arrives you have fourteen days to return it for a refund." in cancel["reply_draft"]["body"]
    _, change = await run("I moved house, can you change the address on order 2101?", r, sender="sam@fixture.invalid")
    assert "Because it has already been dispatched we cannot change the address on it now." in change["reply_draft"]["body"]
    assert any(d.startswith("Change the delivery address on order CROOKS-2101? The recorded status is IN_TRANSIT") for d in change["owner_decisions"])


async def test_cancel_against_a_fulfilled_untracked_or_delivered_order_reads_the_record_not_the_fulfilment():
    _, fulfilled = await run("Please cancel order 2105", Readers(["untracked"]), sender="ash@fixture.invalid")
    body = fulfilled["reply_draft"]["body"]
    assert "dispatched" not in body.lower() and "(status FULFILLED)" in body and "we cannot say yet whether it can still be cancelled" in body
    _, delivered_case = await run("Please cancel order 2108", Readers(["delivered_return_open"]), sender="chris@fixture.invalid")
    body = delivered_case["reply_draft"]["body"]
    assert "Our records show it delivered on 10 Sep 2026, so it can no longer be cancelled; you have fourteen days from delivery to return it for a refund." in body
    assert "dispatched" not in body.lower()
    assert "Cancel order CROOKS-2108? The carrier reports it delivered, so this is a return question rather than a cancellation." in delivered_case["owner_decisions"]


# ----------------------------------------------------------- the report and the bundle


async def test_the_report_exposes_the_evidence_and_the_approval_requirement():
    r = Readers(["late_uk"], inbox=["late_uk_chase"])
    _, result = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    md = result["markdown"]
    for heading in ("## The enquiry", "## Identification", "## What happened", "## Verified facts", "## Reasonable inference",
                    "## Unknown", "## Evidence gathered", "## Decisions for the owner", "## Reply draft (requires the owner's approval; nothing has been sent)"):
        assert heading in md, heading
    assert "`shopify:order:gid://shopify/Order/2101`" in md and "`kb:delivery_windows`" in md and "`gmail:thread:18f2a9c0b1d2e301`" in md
    assert result["approval"] == {"required": True, "state": "awaiting_owner", "external_effects_so_far": "none",
                                  "what_approval_would_permit": "sending the reply, by the owner, outside this tool"}
    assert result["what_happened"].startswith("The customer asks (delivery)")


async def test_a_bundle_survives_a_round_trip_and_replays_identically():
    r = Readers(["late_uk", "older_same_customer"], inbox=["late_uk_chase"])
    bundle, result = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    replayed = EvidenceBundle.from_dict(json.loads(json.dumps(bundle.to_dict())))
    assert investigate_bundle(replayed) == result
    with pytest.raises(ValueError):
        EvidenceBundle.from_dict({"schema": "something.else"})


async def test_the_redacted_copy_keeps_the_conclusion_and_loses_the_person():
    r = Readers(["late_uk", "older_same_customer"], inbox=["late_uk_chase"])
    bundle, result = await run("Hi, it's Sam Fixture here. Where is my order 2101 (tracking RM123456789GB)? Call me on 07700 900123.", r,
                               subject="Sam Fixture - order 2101", sender="sam@fixture.invalid")
    redacted = redact_bundle(bundle)
    dumped = json.dumps(redacted.to_dict(), ensure_ascii=False)
    for secret in ("sam@fixture.invalid", "shop@fixture.invalid", "Sam", "Fixture", "Leeds", "1 Fixture Street", "LS1 1AA", "07700 900123",
                   "RM123456789GB", "track.example.invalid", "Still nothing"):
        assert secret not in dumped, secret
    assert "…89GB" in dumped, "the tracking reference is masked, not lost"
    again = investigate_bundle(redacted)
    assert again["identification"]["status"] == "identified" and again["identification"]["confidence"] == "confident"
    assert again["identification"]["reasons"] == result["identification"]["reasons"]
    assert [i["text"] for i in again["inferences"]] == [i["text"] for i in result["inferences"]]
    assert "customer1@redacted.invalid" not in again["reply_draft"]["body"] and "Hi Redacted," in again["reply_draft"]["body"]


# -------------------------------------------------------------- the live adapters


async def test_the_live_readers_are_the_read_tools_and_a_fake_store_sees_only_reads(monkeypatch):
    """The live readers reach shopify_find_order and the hydrated order through the bound
    store, and the inbox correlation through the unbound Gmail tools: reads, and nothing else."""
    from app.support import live
    from app.tools import gmail_tools, shopify_tools
    from tests.test_context import ORDER_NODE, Store

    monkeypatch.setattr(shopify_tools, "_client", None)
    monkeypatch.setattr(shopify_tools, "_hydrator", None)
    monkeypatch.setattr(gmail_tools, "_client", None)
    store = Store()
    shopify_tools.bind(store)
    readers = live.readers(kb_dir=KB)
    enquiry = parse_enquiry("Where is my order 1938?", sender_email="daniel@example.com")
    bundle = await gather(enquiry, **{**readers, "now": lambda: NOW})
    result = investigate_bundle(bundle)
    assert result["identification"]["status"] == "identified" and result["identification"]["confidence"] == "confident"
    assert bundle.order["order_number"] == ORDER_NODE["name"]
    assert bundle.sources["shopify"] == "live" and bundle.sources["gmail"].startswith("unavailable")
    names = {q.split("(")[0].split()[-1] for q, _ in store.queries}
    assert names <= {"CrooksOrderByName", "CrooksOrderContext", "CrooksCustomerOrders"}, names
    assert not any("mutation" in q.lower() for q, _ in store.queries)
    assert store.mutations_sent == 0 if hasattr(store, "mutations_sent") else True
    assert readonly.active() is False, "the library never touches the latch; the CLI engages it"


def test_nothing_in_the_support_package_imports_a_write_tool():
    files = list((ROOT / "app" / "support").glob("*.py")) + [ROOT / "app" / "routes" / "support.py", ROOT / "scripts" / "support_investigate.py"]
    for path in files:
        source = path.read_text(encoding="utf-8")
        for forbidden in ("shopify_writes", "gmail_writes", ".mutate(", "send_message", "create_draft", "orderCancel", "refundCreate", "fulfillmentCreate"):
            assert forbidden not in source, f"{path.name} mentions {forbidden}"


# ------------------------------------------------------------------ the route and CLI


async def test_the_route_replays_a_bundle_and_refuses_an_empty_message(monkeypatch):
    from app.main import app
    from app.routes import support as support_route

    r = Readers(["late_uk"], inbox=["late_uk_chase"])
    bundle, expected = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        replayed = await c.post("/support/investigate", json={"bundle": bundle.to_dict()})
        assert replayed.status_code == 200, replayed.text
        body = replayed.json()
        assert body["mode"] == "replay" and body["read_only"] is True
        assert body["identification"] == expected["identification"]
        assert body["approval"]["required"] is True and "bundle" not in body

        empty = await c.post("/support/investigate", json={"text": "   "})
        assert empty.status_code == 400 and empty.json()["code"] == "empty"
        bad = await c.post("/support/investigate", json={"bundle": {"schema": "nope"}})
        assert bad.status_code == 400 and bad.json()["code"] == "bad_bundle"

        monkeypatch.setattr(support_route, "live_readers", lambda: r.kwargs())
        live = await c.post("/support/investigate", json={"text": "Where is my order 2101?", "sender_email": "sam@fixture.invalid", "include_bundle": True})
        assert live.status_code == 200, live.text
        assert live.json()["mode"] == "live" and live.json()["bundle"]["schema"] == "clive.support_evidence_bundle.v1"
        assert live.json()["identification"]["order_number"] == "CROOKS-2101"


async def test_the_cli_replays_a_saved_bundle_and_writes_a_redacted_capture(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import support_investigate as cli

    r = Readers(["late_uk"], inbox=["late_uk_chase"])
    bundle, _ = await run("Where is my order 2101?", r, sender="sam@fixture.invalid")
    saved = tmp_path / "case.json"
    saved.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
    out = tmp_path / "report.md"
    redacted = tmp_path / "case.redacted.json"
    code = await cli.run(cli.build_parser().parse_args(["--bundle", str(saved), "--out", str(out), "--redacted-capture", str(redacted)]))
    assert code == 0
    report = out.read_text(encoding="utf-8")
    assert "## Reply draft (requires the owner's approval; nothing has been sent)" in report and "RM123456789GB" in report
    assert "sam@fixture.invalid" not in redacted.read_text(encoding="utf-8")
    assert readonly.active() is False, "a replay reads nothing and engages nothing"
