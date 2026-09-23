"""Identification, verified facts, reasonable inference, and what is not known.

The three lists are kept apart on purpose. A fact is a field the source system returned,
cited by the evidence it came from. An inference is a conclusion drawn from facts and the
policy, and says so. An unknown is a question the evidence cannot answer, named rather than
papered over, and the draft is forbidden from filling it. The reference time is the bundle's
own `gathered_at`, so the same bundle always yields the same investigation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.support.evidence import EvidenceBundle

UK_COUNTRIES = ("united kingdom", "uk", "gb", "great britain", "england", "scotland", "wales", "northern ireland")
# The published policy windows (kb/shipping-policy.md, "When it lands"); the quoted line is
# the evidence, these numbers are how the lateness inference reads it.
UK_WINDOW_WORKING_DAYS = 2
INTERNATIONAL_WINDOW_DAYS = 14
DISPATCH_GRACE_WORKING_DAYS = 1
# Shopify's fulfilment display statuses, read as the carrier's word on the parcel: a label
# that exists without a scan, a delivery scan, and the failures.
LABEL_ONLY_STATUSES = ("CONFIRMED", "LABEL_PRINTED", "LABEL_PURCHASED", "SUBMITTED")
DELIVERED_STATUSES = ("DELIVERED",)
OPEN_RETURN_STATUSES = ("IN_PROGRESS", "REQUESTED")
_TAGS = re.compile(r"<[^>]+>")
_RETURN_NAME = re.compile(r"created return (\S+?)\.?$", re.I)


@dataclass(frozen=True)
class Finding:
    text: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "evidence": list(self.evidence)}


@dataclass
class Investigation:
    enquiry_kind: str
    identification: dict[str, Any]
    facts: list[Finding] = field(default_factory=list)
    inferences: list[Finding] = field(default_factory=list)
    unknowns: list[Finding] = field(default_factory=list)
    owner_decisions: list[str] = field(default_factory=list)
    what_happened: str = ""


# ------------------------------------------------------------------------ dates


def parse_when(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def day_words(value: Any) -> str:
    when = parse_when(value)
    return when.strftime("%-d %b %Y") if when else str(value or "an unknown date")


def working_days_between(start: datetime, end: datetime) -> int:
    """Whole weekdays after `start` up to and including `end`'s date. Saturday counts as a
    dispatch day at CROOKS but not as a delivery day, so this is the delivery reading."""
    if end <= start:
        return 0
    days = 0
    cursor = start.date()
    while cursor < end.date():
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
        if cursor.weekday() < 5:
            days += 1
    return days


def _digits(number: Any) -> str:
    return str(number or "").rsplit("-", 1)[-1].lstrip("#").strip()


def fulfilment_status(f: dict[str, Any]) -> str:
    return str(f.get("display_status") or f.get("status") or "").upper()


def label_only(fulfillments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in fulfillments if fulfilment_status(f) in LABEL_ONLY_STATUSES]


def delivered(fulfillments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in fulfillments if fulfilment_status(f) in DELIVERED_STATUSES]


def delivered_at(order: dict[str, Any]) -> Any:
    """When Shopify recorded the carrier's delivery scan, from the order's events."""
    for e in order.get("events") or []:
        message = str((e or {}).get("message") or "").lower()
        if "delivered" in message and "email" not in message:
            return e.get("at")
    return None


def return_name(order: dict[str, Any]) -> str:
    for e in order.get("events") or []:
        found = _RETURN_NAME.search(str((e or {}).get("message") or ""))
        if found:
            return found.group(1)
    return ""


def open_return(order: dict[str, Any]) -> bool:
    return str(order.get("return_status") or "").upper() in OPEN_RETURN_STATUSES


def _nonzero(amount: Any) -> bool:
    found = re.search(r"\d+(?:\.\d+)?", str(amount or ""))
    return bool(found) and float(found.group(0)) > 0


def is_uk(order: dict[str, Any]) -> bool | None:
    return _is_uk(order)


def _is_uk(order: dict[str, Any]) -> bool | None:
    where = str(order.get("ships_to") or "").strip().lower()
    if not where:
        return None
    country = where.split(",")[-1].strip()
    return country in UK_COUNTRIES


# --------------------------------------------------------------- identification


def identify(bundle: EvidenceBundle) -> dict[str, Any]:
    enquiry = bundle.parsed_enquiry
    search = bundle.order_search or {}
    order = bundle.order
    if order:
        digits = _digits(order.get("order_number"))
        customer_email = str(order.get("customer_email") or "").strip().lower()
        named = digits in enquiry.order_numbers
        reasons: list[str] = []
        if named:
            reasons.append(f"the customer named order {digits}")
        if enquiry.sender_email and customer_email and enquiry.sender_email == customer_email:
            reasons.append("written from the email address on the order")
            confidence = "confident"
        elif enquiry.sender_email and customer_email:
            reasons.append("the sender's address is not the one on the order")
            confidence = "possible"
        elif not enquiry.sender_email:
            reasons.append("no sender address to check against the order")
            confidence = "possible"
        else:
            reasons.append("the order has no customer email to check against")
            confidence = "possible"
        if not named:
            reasons.append("the enquiry does not name the order; it is the only recent order found for the address")
            if confidence == "confident":
                confidence = "possible"
        return {
            "status": "identified",
            "confidence": confidence,
            "order_number": order.get("order_number"),
            "order_id": order.get("order_id"),
            "customer_name": order.get("customer_name"),
            "reasons": reasons,
            "evidence": [bundle.search_ref, bundle.order_ref],
        }
    orders = [o for o in search.get("orders") or [] if isinstance(o, dict)]
    if not bundle.order_search and not enquiry.order_numbers and not enquiry.sender_email and not enquiry.emails_mentioned:
        return {"status": "no_identifier", "confidence": "none",
                "reasons": ["the enquiry gives no order number and no email address to search by"], "candidates": [], "evidence": ["enquiry"]}
    if bundle.order_search is None:
        return {"status": "unavailable", "confidence": "none",
                "reasons": ["the store could not be searched"] + list(bundle.problems), "candidates": [], "evidence": []}
    if len(orders) > 1 or search.get("ambiguous"):
        candidates = [{"order_number": o.get("order_number"), "placed_at": o.get("placed_at"), "fulfillment": o.get("fulfillment"),
                       "same_sender": bool(enquiry.sender_email) and str(o.get("customer_email") or "").lower() == enquiry.sender_email}
                      for o in orders]
        reasons = [f"{len(orders)} orders matched {search.get('query')!r} and the enquiry does not single one out"]
        if search.get("ambiguous"):
            reasons.append("more than one customer matched that name")
        return {"status": "ambiguous", "confidence": "none", "reasons": reasons, "candidates": candidates, "evidence": [bundle.search_ref]}
    reasons = [f"no order matched {search.get('query')!r}"]
    if search.get("note"):
        reasons.append(str(search.get("note"))[:200])
    return {"status": "not_found", "confidence": "none", "reasons": reasons, "candidates": [], "evidence": [bundle.search_ref]}


# ------------------------------------------------------------------------ facts


def _order_facts(bundle: EvidenceBundle) -> list[Finding]:
    order = bundle.order or {}
    ref = bundle.order_ref
    out: list[Finding] = []
    number = order.get("order_number")
    out.append(Finding(f"Order {number} was placed on {day_words(order.get('placed_at'))}.", (ref,)))
    out.append(Finding(f"Payment status: {order.get('payment') or 'unknown'}; fulfilment status: {order.get('fulfillment') or 'unknown'}.", (ref,)))
    items = [i for i in order.get("items") or [] if isinstance(i, dict)]
    if items:
        listed = "; ".join(f"{i.get('quantity') or 1} x {i.get('title') or 'item'}" + (f" ({i.get('variant')})" if i.get("variant") else "") for i in items)
        out.append(Finding(f"Items: {listed}.", (ref,)))
    if order.get("shipping_method") or order.get("ships_to"):
        out.append(Finding(f"Shipping: {order.get('shipping_method') or 'method not recorded'}, to {order.get('ships_to') or 'an unrecorded destination'}.", (ref,)))
    fulfillments = [f for f in order.get("fulfillments") or [] if isinstance(f, dict)]
    for f in fulfillments:
        if f.get("number"):
            out.append(Finding(f"Fulfilment recorded on {day_words(f.get('shipped_at'))}: {f.get('carrier') or 'carrier not recorded'}, tracking {f.get('number')}"
                               + (f" ({f.get('url')})" if f.get("url") else "") + f"; status {fulfilment_status(f) or 'unknown'}.", (ref,)))
        else:
            out.append(Finding(f"Fulfilment recorded on {day_words(f.get('shipped_at'))}; no tracking number on it"
                               + (f" (carrier {f.get('carrier')})" if f.get("carrier") else "") + f"; status {fulfilment_status(f) or 'unknown'}.", (ref,)))
    if not fulfillments:
        out.append(Finding("No fulfilment recorded: the order has not been dispatched.", (ref,)))
    if order.get("cancelled_at"):
        out.append(Finding(f"Cancelled on {day_words(order.get('cancelled_at'))}" + (f" (reason: {order.get('cancel_reason')})" if order.get("cancel_reason") else "") + ".", (ref,)))
    for r in order.get("refunds") or []:
        if isinstance(r, dict):
            out.append(Finding(f"Refund of {r.get('amount') or 'an unrecorded amount'} on {day_words(r.get('created_at'))}.", (ref,)))
    money = order.get("money") if isinstance(order.get("money"), dict) else {}
    if money.get("total"):
        out.append(Finding(f"Order total {money.get('total')}" + (f"; refunded {money['refunded']}" if _nonzero(money.get("refunded")) else "") + ".", (ref,)))
    if order.get("note"):
        note = " / ".join(part.strip() for part in str(order.get("note")).splitlines() if part.strip())
        out.append(Finding(f"Internal order note (not for the customer): {note}", (ref,)))
    if order.get("tags"):
        out.append(Finding(f"Order tags: {', '.join(order.get('tags'))}.", (ref,)))
    if order.get("return_status") and str(order.get("return_status")).upper() != "NO_RETURN":
        out.append(Finding(f"Return status on the order: {order.get('return_status')}.", (ref,)))
    for e in order.get("events") or []:
        if isinstance(e, dict) and e.get("message") and "payout" not in str(e.get("message")).lower():
            out.append(Finding(f"Shopify event, {day_words(e.get('at'))}: {_TAGS.sub('', str(e.get('message'))).strip()}", (ref,)))
    history = order.get("history") if isinstance(order.get("history"), dict) else None
    if history and history.get("orders") is not None:
        out.append(Finding(f"The customer has {history.get('orders')} order(s) with CROOKS in total.", (f"{ref}#history",)))
    return out


def _thread_facts(bundle: EvidenceBundle) -> list[Finding]:
    out: list[Finding] = []
    order = bundle.order or {}
    tracking_numbers = {str(f.get("number")) for f in order.get("fulfillments") or [] if isinstance(f, dict) and f.get("number")}
    for t in bundle.threads:
        ref = bundle.thread_ref(t)
        messages = t.get("messages") or []
        inbound = [m for m in messages if not m.get("outbound")]
        outbound = [m for m in messages if m.get("outbound")]
        latest = messages[-1] if messages else None
        who = "from the customer's address" if t.get("match") in ("both", "sender") else "matched by the order number, not from the customer's address"
        line = (f"Email thread {t.get('subject')!r} ({who}): {t.get('message_count', len(messages))} message(s), "
                f"{len(inbound)} inbound and {len(outbound)} from us")
        if latest:
            line += f"; the latest is {'ours' if latest.get('outbound') else 'theirs'} on {day_words(latest.get('date')) if parse_when(latest.get('date')) else latest.get('date')}"
        out.append(Finding(line + ".", (ref,)))
        for m in outbound:
            said = {n for n in tracking_numbers if n and n in str(m.get("body") or "")}
            if said:
                out.append(Finding(f"Our earlier reply in that thread gave the tracking number {', '.join(sorted(said))}.", (ref,)))
    return out


# --------------------------------------------------------------------- inference


def _inferences(bundle: EvidenceBundle, identification: dict[str, Any]) -> tuple[list[Finding], list[str]]:
    enquiry = bundle.parsed_enquiry
    order = bundle.order or {}
    now = parse_when(bundle.gathered_at) or datetime.now(UTC)
    ref = bundle.order_ref
    out: list[Finding] = []
    decisions: list[str] = []
    if identification.get("status") != "identified":
        return out, decisions
    kind = enquiry.kind
    number = order.get("order_number")
    fulfillments = [f for f in order.get("fulfillments") or [] if isinstance(f, dict)]
    uk = _is_uk(order)
    placed = parse_when(order.get("placed_at"))
    policy_refs = tuple(bundle.policy_ref(n) for n in ("delivery_windows",) if n in bundle.policy)
    dispatch_refs = tuple(bundle.policy_ref(n) for n in ("dispatch",) if n in bundle.policy)

    if order.get("cancelled_at"):
        out.append(Finding("The order was cancelled, so nothing is on its way; the enquiry should be answered from the cancellation and any refund.", (ref,)))
    elif fulfillments:
        arrived = delivered(fulfillments)
        labelled = label_only(fulfillments)
        if arrived:
            when = delivered_at(order)
            out.append(Finding("The carrier has reported the parcel delivered" + (f" on {day_words(when)}" if when else "") + "; the fulfilment status is DELIVERED.", (ref,)))
            if kind == "delivery":
                decisions.append(f"Order {number}: the carrier says delivered and the customer says not; check the proof of delivery, a neighbour or a safe place, then a replacement or refund is the owner's call.")
        elif labelled:
            f = labelled[-1]
            out.append(Finding(f"The fulfilment status is {fulfilment_status(f)}: a shipping label exists (created {day_words(f.get('shipped_at'))}) but no carrier scan has reached Shopify, "
                               f"so the parcel may not have been collected by {f.get('carrier') or 'the carrier'} yet.", (ref,)))
            decisions.append(f"Order {number}: confirm with the courier whether the parcel was collected on or after {day_words(f.get('shipped_at'))}; if it was not, get it collected or re-dispatch it, and tell the customer which.")
        shipped = [parse_when(f.get("shipped_at")) for f in fulfillments]
        shipped = [s for s in shipped if s]
        if shipped and not arrived:
            verb = "Label created" if labelled else "Dispatched"
            latest_dispatch = max(shipped)
            elapsed_working = working_days_between(latest_dispatch, now)
            elapsed_calendar = (now - latest_dispatch).days
            if uk is True:
                late_by = elapsed_working - UK_WINDOW_WORKING_DAYS
                verdict = (f"by the published UK window (one to two working days once dispatched) the parcel is running late by about {late_by} working day(s)"
                           if late_by > 0 else "the parcel is still within the published UK window (one to two working days once dispatched)")
                out.append(Finding(f"{verb} {elapsed_working} working day(s) ago: {verdict}.", (ref,) + policy_refs))
                if late_by > 0:
                    decisions.append(f"Order {number} is late by policy: chase the courier, or offer a replacement or refund?")
            elif uk is False:
                late_by = elapsed_calendar - INTERNATIONAL_WINDOW_DAYS
                verdict = (f"by the published international window (seven to fourteen days) the parcel is running late by about {late_by} day(s)"
                           if late_by > 0 else "the parcel is still within the published international window (seven to fourteen days)")
                out.append(Finding(f"{verb} {elapsed_calendar} day(s) ago for an international address: {verdict}.", (ref,) + policy_refs))
                if late_by > 0:
                    decisions.append(f"Order {number} is late by policy: chase the courier, or offer a replacement or refund?")
            else:
                out.append(Finding(f"{verb} {elapsed_calendar} day(s) ago; the destination is not recorded, so which delivery window applies is not certain.", (ref,)))
        if not any(f.get("number") for f in fulfillments):
            out.append(Finding("The fulfilment carries no tracking number, so the customer cannot have been sent one; the parcel's whereabouts can only be checked with the courier by hand.", (ref,)))
    elif placed is not None:
        waiting = working_days_between(placed, now)
        if waiting > DISPATCH_GRACE_WORKING_DAYS:
            out.append(Finding(f"Not dispatched {waiting} working day(s) after the order was placed; the published rule is same-day dispatch before 6pm, Monday to Saturday, so something has held it.", (ref,) + dispatch_refs))
            decisions.append(f"Order {number} is not dispatched {waiting} working day(s) on: what is holding it, and what should the customer be told?")
        else:
            out.append(Finding("Not dispatched yet, but within the normal dispatch time.", (ref,) + dispatch_refs))

    if kind == "delivery" and not fulfillments and not order.get("cancelled_at"):
        out.append(Finding("The customer is asking where an order is that has not left yet.", (ref, "enquiry")))
    if kind in ("wrong_item", "missing_item", "damaged"):
        out.append(Finding("What the customer received cannot be seen from here; the order shows what should have been sent.", (ref, "enquiry")))
        decisions.append(f"Order {number}: replacement, exchange or refund once the photo arrives (the policy puts damage in transit on us; discretion is the owner's).")
    if kind == "cancel":
        decisions.append(f"Cancel order {number}?" + (" It has not been dispatched." if not fulfillments else " It has already been dispatched, so a cancellation would be a return instead."))
    if kind == "change_address":
        decisions.append(f"Change the delivery address on order {number}?" + (" It has not been dispatched." if not fulfillments else " It has already been dispatched."))
    if open_return(order):
        name = return_name(order)
        out.append(Finding("A return is already open on this order" + (f" ({name})" if name else "") + f" (return status {order.get('return_status')}), "
                           "so the customer's request has reached us through the returns process and is waiting on our side.", (ref,)))
        decisions.append(f"Order {number}: approve or decline the open return{f' {name}' if name else ''} and send the return instructions.")
    elif kind == "return_exchange":
        decisions.append(f"Return or exchange on order {number}: within policy? (fourteen days from delivery, unworn with tags).")
    if fulfillments and placed is not None and not order.get("cancelled_at"):
        firsts = [parse_when(f.get("shipped_at")) for f in fulfillments]
        firsts = [s for s in firsts if s]
        if firsts:
            delay = working_days_between(placed, min(firsts))
            if delay > DISPATCH_GRACE_WORKING_DAYS:
                out.append(Finding(f"The first fulfilment was recorded {delay} working day(s) after the order was placed; the published rule is same-day dispatch before 6pm, Monday to Saturday.", (ref,) + dispatch_refs))
    if not bundle.threads and bundle.sources.get("gmail") == "live":
        out.append(Finding("No earlier email from this customer about this order was found in the last sixty days, so this is the first message we hold on it.", ("gmail:search",)))
    reply_refs = tuple(bundle.policy_ref(n) for n in ("reply_time",) if n in bundle.policy)
    for t in bundle.threads:
        if t.get("match") not in ("both", "sender"):
            continue
        messages = [m for m in t.get("messages") or [] if isinstance(m, dict)]
        unanswered = 0
        for m in reversed(messages):
            if m.get("outbound"):
                break
            unanswered += 1
        if not unanswered:
            continue
        latest = parse_when(messages[-1].get("date"))
        waited = working_days_between(latest, now) if latest else 0
        if unanswered >= 2 or waited > 2:
            out.append(Finding(f"The customer has written {unanswered} time(s) in thread {t.get('subject')!r} without a reply from us; the latest was {waited} working day(s) ago, "
                               "and the published promise is a reply within one to two working days.", (bundle.thread_ref(t),) + reply_refs))
        else:
            out.append(Finding(f"The customer is waiting on us in thread {t.get('subject')!r}: the latest message is theirs.", (bundle.thread_ref(t),)))
    return out, decisions


# ---------------------------------------------------------------------- unknowns


def _unknowns(bundle: EvidenceBundle, identification: dict[str, Any]) -> list[Finding]:
    enquiry = bundle.parsed_enquiry
    order = bundle.order or {}
    out: list[Finding] = []
    status = identification.get("status")
    if status != "identified":
        out.append(Finding("Which order this is about: not established from the evidence.", tuple(identification.get("evidence") or ())))
        return out
    if identification.get("confidence") != "confident":
        out.append(Finding("Whether the person writing is the customer on the order: " + "; ".join(identification.get("reasons") or []) + ".", (bundle.order_ref,)))
    fulfillments = [f for f in order.get("fulfillments") or [] if isinstance(f, dict)]
    if fulfillments and not order.get("cancelled_at"):
        if delivered(fulfillments):
            out.append(Finding("Whether the parcel is actually with the customer: the carrier reports it delivered, and nothing here can see beyond that scan.", (bundle.order_ref,)))
        else:
            out.append(Finding("Where the parcel is now and whether it has been delivered: no carrier tracking is integrated, so only the tracking reference and the fulfilment status are known, not the scan history.", (bundle.order_ref,)))
        if not any(f.get("number") for f in fulfillments):
            out.append(Finding("The carrier and tracking reference: none recorded on the fulfilment.", (bundle.order_ref,)))
    sent = [e for e in order.get("events") or [] if isinstance(e, dict) and "email" in str(e.get("message") or "").lower()]
    if sent:
        out.append(Finding(f"Whether the customer received the email(s) Shopify records as sent ({', '.join(day_words(e.get('at')) for e in sent)}): sending is recorded, receipt is not visible.", (bundle.order_ref,)))
    else:
        out.append(Finding("Whether the customer received the confirmation or tracking email: not visible from the store or the inbox.", (bundle.order_ref,)))
    if enquiry.kind in ("wrong_item", "missing_item", "damaged"):
        out.append(Finding("What actually arrived: no photo or description on file yet.", ("enquiry",)))
    if bundle.sources.get("gmail", "").startswith("unavailable") or bundle.sources.get("gmail") == "not configured":
        out.append(Finding(f"Any earlier conversation with the customer: the inbox was {bundle.sources.get('gmail')}.", ()))
    for problem in bundle.problems:
        out.append(Finding(f"Could not read: {problem}", ()))
    return out


# ------------------------------------------------------------------ narrative


def _narrative(bundle: EvidenceBundle, identification: dict[str, Any], facts: list[Finding], inferences: list[Finding]) -> str:
    enquiry = bundle.parsed_enquiry
    ask = enquiry.asks[0] if enquiry.asks else enquiry.text[:160]
    status = identification.get("status")
    if status == "identified":
        who = f"order {identification.get('order_number')}"
        conf = identification.get("confidence")
        opening = f"The customer asks ({enquiry.kind.replace('_', ' ')}): {ask!r}. This is {who}, identified ({conf}: {'; '.join(identification.get('reasons') or [])})."
    elif status == "ambiguous":
        opening = f"The customer asks ({enquiry.kind.replace('_', ' ')}): {ask!r}. The order is not singled out: {'; '.join(identification.get('reasons') or [])}."
    elif status == "not_found":
        opening = f"The customer asks ({enquiry.kind.replace('_', ' ')}): {ask!r}. No order was found: {'; '.join(identification.get('reasons') or [])}."
    else:
        opening = f"The customer asks ({enquiry.kind.replace('_', ' ')}): {ask!r}. The order could not be identified: {'; '.join(identification.get('reasons') or [])}."
    journey = " ".join(f.text for f in facts if f.text.startswith(("Order ", "Fulfilment", "No fulfilment", "Cancelled", "Refund", "Return status", "Email thread", "Our earlier")))
    reading = " ".join(f.text for f in inferences)
    return " ".join(part for part in (opening, journey, reading) if part).strip()


# ------------------------------------------------------------------------ entry


def investigate(bundle: EvidenceBundle) -> Investigation:
    identification = identify(bundle)
    facts: list[Finding] = []
    if identification.get("status") == "identified":
        facts.extend(_order_facts(bundle))
        facts.extend(_thread_facts(bundle))
    for name in ("delivery_windows", "dispatch", "lost_or_damaged", "returns", "photo", "reply_time"):
        line = bundle.policy.get(name)
        if line:
            facts.append(Finding(f"Policy ({line.get('file')}, {line.get('heading')}): {line.get('text')}", (bundle.policy_ref(name),)))
    inferences, decisions = _inferences(bundle, identification)
    unknowns = _unknowns(bundle, identification)
    investigation = Investigation(
        enquiry_kind=bundle.parsed_enquiry.kind,
        identification=identification,
        facts=facts,
        inferences=inferences,
        unknowns=unknowns,
        owner_decisions=decisions,
    )
    investigation.what_happened = _narrative(bundle, identification, facts, inferences)
    return investigation


_TOKEN = re.compile(r"[A-Z]{2}\d{9}[A-Z]{2}|\d{4,}")


def numbers_in(text: str) -> set[str]:
    """Order-shaped and tracking-shaped tokens in a text: what a draft may only take from evidence."""
    return set(_TOKEN.findall(text or ""))
