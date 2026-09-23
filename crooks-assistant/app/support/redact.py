"""A redacted copy of an evidence bundle, for engineering evidence.

The real acceptance case is a real customer. What the engineering record needs from it is the
shape of the investigation, not the person: whether the order was identified and on what
grounds, which statements were facts, which inference, which unknown, and that the draft
invented nothing. So this keeps the structure and the non-personal order data (dates, statuses,
items, policy) and replaces the person: names, email addresses, the address, phone numbers,
message bodies and the internal note. Tracking references are masked to their last four
characters. Email addresses are replaced consistently, so an identification that rested on
"written from the address on the order" still holds in the redacted copy.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.support.evidence import EvidenceBundle

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w-])(?:\+?\d[\d\s().-]{8,}\d)(?![\w-])")
_URL = re.compile(r"https?://\S+")
_TRACKING_KEYS = ("number",)
PSEUDONYM = "Redacted Customer"


class _Names:
    """One replacement per distinct real value, kept stable across the bundle."""

    def __init__(self) -> None:
        self.emails: dict[str, str] = {}
        self.names: list[str] = []
        self.tracking: list[str] = []

    def email(self, value: Any) -> str:
        real = str(value or "").strip().lower()
        if not real:
            return ""
        if real not in self.emails:
            self.emails[real] = f"customer{len(self.emails) + 1}@redacted.invalid"
        return self.emails[real]

    def learn_name(self, value: Any) -> None:
        for part in str(value or "").replace(",", " ").split():
            part = part.strip()
            if len(part) >= 2 and part.lower() not in ("mr", "mrs", "ms", "dr") and part not in self.names:
                self.names.append(part)

    def scrub(self, text: Any) -> str:
        out = str(text or "")
        out = _EMAIL.sub(lambda m: self.email(m.group(0)), out)
        out = _URL.sub("[url]", out)
        out = _PHONE.sub("[phone]", out)
        for name in sorted(self.names, key=len, reverse=True):
            out = re.sub(rf"(?i)(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", "[name]", out)
        for number in self.tracking:
            out = out.replace(number, mask_tracking(number) or "")
        return out


def mask_tracking(number: Any) -> str | None:
    text = str(number or "").strip()
    if not text:
        return None
    return "…" + text[-4:] if len(text) > 4 else "…" + text


def redact_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    names = _Names()
    data = copy.deepcopy(bundle.to_dict())
    order = data.get("order") or {}
    search = data.get("order_search") or {}

    # Learn the person first, from every field that names them, so the scrubber can find
    # the name wherever it was typed.
    for source in (order, *(o for o in (search.get("orders") or []) if isinstance(o, dict))):
        names.learn_name(source.get("customer_name"))
        customer = source.get("customer") if isinstance(source.get("customer"), dict) else {}
        names.learn_name(customer.get("name"))
        address = source.get("shipping_address") if isinstance(source.get("shipping_address"), dict) else {}
        names.learn_name(address.get("name"))
    for thread in data.get("threads") or []:
        for message in thread.get("messages") or []:
            names.learn_name(message.get("from"))
    names.tracking = [str(f.get("number")) for f in order.get("fulfillments") or [] if isinstance(f, dict) and f.get("number")]

    enquiry = data.get("enquiry") or {}
    enquiry["sender_email"] = names.email(enquiry.get("sender_email"))
    enquiry["emails_mentioned"] = [names.email(e) for e in enquiry.get("emails_mentioned") or []]
    enquiry["text"] = names.scrub(enquiry.get("text"))
    enquiry["subject"] = names.scrub(enquiry.get("subject"))
    enquiry["asks"] = [names.scrub(a) for a in enquiry.get("asks") or []]
    data["enquiry"] = enquiry

    if search:
        search["query"] = names.scrub(search.get("query"))
        search["orders"] = [_redact_summary(o, names) for o in search.get("orders") or [] if isinstance(o, dict)]
        search.pop("customers_matched", None)
        for key in ("note", "instruction"):
            if search.get(key):
                search[key] = names.scrub(search[key])
        data["order_search"] = search

    if order:
        data["order"] = _redact_order(order, names)

    data["threads"] = [_redact_thread(t, names, order) for t in data.get("threads") or []]
    data["problems"] = [names.scrub(p) for p in data.get("problems") or []]
    data["sources"] = {k: names.scrub(v) for k, v in (data.get("sources") or {}).items()}
    return EvidenceBundle.from_dict(data)


def _redact_summary(order: dict[str, Any], names: _Names) -> dict[str, Any]:
    out = dict(order)
    if out.get("customer_name"):
        out["customer_name"] = PSEUDONYM
    out["customer_email"] = names.email(out.get("customer_email")) or None
    return out


def _redact_order(order: dict[str, Any], names: _Names) -> dict[str, Any]:
    out = dict(order)
    if out.get("customer_name"):
        out["customer_name"] = PSEUDONYM
    out["customer_email"] = names.email(out.get("customer_email")) or None
    customer = out.get("customer") if isinstance(out.get("customer"), dict) else None
    if customer:
        out["customer"] = {**customer, "name": PSEUDONYM if customer.get("name") else None, "email": names.email(customer.get("email")) or None}
    address = out.get("shipping_address") if isinstance(out.get("shipping_address"), dict) else None
    if address:
        out["shipping_address"] = {"country": address.get("country"), "redacted": True}
    if out.get("ships_to"):
        out["ships_to"] = "[city], " + str(out["ships_to"]).split(",")[-1].strip() if "," in str(out["ships_to"]) else "[place]"
    if out.get("note"):
        out["note"] = f"[internal note redacted, {len(str(out['note']))} characters]"
    out["fulfillments"] = [
        {**f, "number": mask_tracking(f.get("number")), "url": None} for f in out.get("fulfillments") or [] if isinstance(f, dict)
    ]
    out["events"] = [{**e, "message": names.scrub(e.get("message"))} for e in out.get("events") or [] if isinstance(e, dict)]
    for key in ("refunds",):
        out[key] = [{**r, "note": names.scrub(r.get("note")) if r.get("note") else r.get("note")} for r in out.get(key) or [] if isinstance(r, dict)]
    history = out.get("history") if isinstance(out.get("history"), dict) else None
    if history:
        out["history"] = {k: v for k, v in history.items() if k in ("orders", "spent", "since", "open_orders", "customer_id")}
    email = out.get("email") if isinstance(out.get("email"), dict) else None
    if email:
        out["email"] = {"redacted": True, "threads": len(email.get("threads") or [])}
    return out


def _redact_thread(thread: dict[str, Any], names: _Names, order: dict[str, Any]) -> dict[str, Any]:
    tracking = [str(f.get("number")) for f in order.get("fulfillments") or [] if isinstance(f, dict) and f.get("number")]
    out = dict(thread)
    out["subject"] = names.scrub(out.get("subject"))
    out["from_email"] = names.email(out.get("from_email"))
    messages = []
    for m in out.get("messages") or []:
        body = str(m.get("body") or "")
        mentioned = [mask_tracking(n) for n in tracking if n in body]
        messages.append({
            **{k: v for k, v in m.items() if k != "from"},
            "from_email": names.email(m.get("from_email")),
            "body": f"[redacted, {len(body)} characters]" + (f"; mentions tracking {', '.join(mentioned)}" if mentioned else ""),
        })
    out["messages"] = messages
    return out
