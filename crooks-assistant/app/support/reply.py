"""The customer-facing draft, built only from verified facts and the published policy.

Every number, date and tracking reference in the body comes from the evidence bundle; an
unknown is answered by asking, never by guessing. The draft is text for the owner to read,
edit and send by hand: nothing here sends, saves to the mailbox, or changes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.support.evidence import EvidenceBundle
from app.support.investigate import (
    Investigation,
    day_words,
    delivered,
    delivered_at,
    label_only,
    open_return,
    return_name,
)

MAX_LISTED_ORDERS = 5


@dataclass(frozen=True)
class ReplyDraft:
    subject: str
    body: str
    requires_owner_approval: bool
    based_on: tuple[str, ...]
    not_said: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "requires_owner_approval": self.requires_owner_approval,
            "based_on": list(self.based_on),
            "not_said": list(self.not_said),
            "external_effects": "none: this draft has not been sent, saved or shown to the customer",
        }


def _first_name(order: dict[str, Any]) -> str:
    name = str(order.get("customer_name") or "").strip()
    return name.split(" ")[0] if name else ""


def _policy(bundle: EvidenceBundle, name: str) -> str:
    line = bundle.policy.get(name) or {}
    return str(line.get("text") or "").strip()


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else text + "."


def draft_reply(investigation: Investigation, bundle: EvidenceBundle, *, signature: str = "CROOKS") -> ReplyDraft:
    enquiry = bundle.parsed_enquiry
    order = bundle.order or {}
    ident = investigation.identification
    kind = investigation.enquiry_kind
    based: list[str] = ["enquiry"]
    lines: list[str] = []
    name = _first_name(order) if ident.get("status") == "identified" else ""
    lines.append(f"Hi {name}," if name else "Hi,")
    lines.append("")
    number = order.get("order_number")
    fulfillments = [f for f in order.get("fulfillments") or [] if isinstance(f, dict)]
    tracked = [f for f in fulfillments if f.get("number")]
    cancelled = bool(order.get("cancelled_at"))
    delivery_line = _policy(bundle, "delivery_windows")
    dispatch_line = _policy(bundle, "dispatch")
    lost_line = _policy(bundle, "lost_or_damaged")
    returns_line = _policy(bundle, "returns")
    photo_line = _policy(bundle, "photo")

    if ident.get("status") != "identified":
        lines.append("Thanks for getting in touch.")
        if ident.get("status") == "ambiguous" and enquiry.sender_email:
            mine = [c for c in ident.get("candidates") or [] if c.get("same_sender")][:MAX_LISTED_ORDERS]
            if mine:
                listed = ", ".join(str(c.get("order_number")) for c in mine)
                lines.append(f"We can see more than one order under your email address ({listed}). Which one is this about?")
                based.append(bundle.search_ref)
        lines.append("So we can find the right order straight away, could you reply with the order number from your confirmation email"
                     + (" and the email address you ordered with" if not enquiry.sender_email else "") + "?")
        if kind in ("damaged", "wrong_item", "missing_item"):
            lines.append("A photo of what arrived (and the label, if there is one) would help us sort it fastest.")
        if photo_line:
            based.append(bundle.policy_ref("photo"))
        lines.append("")
        lines.append(signature)
        return ReplyDraft(subject=_subject(enquiry, number), body="\n".join(lines), requires_owner_approval=True,
                          based_on=tuple(dict.fromkeys(based)), not_said=tuple(u.text for u in investigation.unknowns))

    based.append(bundle.order_ref)
    lines.append(f"Thanks for getting in touch about order {number}.")
    if cancelled:
        refunds = [r for r in order.get("refunds") or [] if isinstance(r, dict)]
        lines.append(_sentence(f"That order was cancelled on {day_words(order.get('cancelled_at'))}"
                               + (f" and {refunds[0].get('amount')} was refunded on {day_words(refunds[0].get('created_at'))}" if refunds and refunds[0].get("amount") else "")))
        lines.append("If that is not what you expected, tell us and we will look into it.")
    elif kind in ("delivery", "other") or (kind in ("cancel", "change_address") and fulfillments):
        if tracked and delivered(tracked):
            f = delivered(tracked)[-1]
            when = delivered_at(order)
            lines.append(_sentence("Our records show it was delivered" + (f" on {day_words(when)}" if when else "") + (f" by {f.get('carrier')}" if f.get("carrier") else "")
                                   + f", tracking number {f.get('number')}" + (f" ({f.get('url')})" if f.get("url") else "")))
            if kind == "delivery":
                lines.append("If it is not with you, could you check with neighbours or for a safe-place card and let us know? We will then take it up with the courier straight away.")
        elif tracked:
            f = tracked[-1]
            if label_only([f]):
                lines.append(_sentence(f"A shipping label was created for it on {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")
                                       + f", tracking number {f.get('number')}" + (f" - you can follow it at {f.get('url')}" if f.get("url") else "")))
                lines.append("The carrier has not yet reported a collection scan on our side, so we are checking with them that it has been picked up and will confirm as soon as it is moving.")
            else:
                lines.append(_sentence(f"It was dispatched on {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")
                                       + f", tracking number {f.get('number')}" + (f" - you can follow it at {f.get('url')}" if f.get("url") else "")))
            if delivery_line:
                lines.append(_sentence(delivery_line))
                based.append(bundle.policy_ref("delivery_windows"))
            late = any("running late" in i.text for i in investigation.inferences)
            if late:
                lines.append("It is taking longer than it should, so we are chasing the courier from our side as well.")
            if lost_line:
                lines.append("If it does not turn up, reply here and we will sort it: we chase the courier, or send a replacement or a refund.")
                based.append(bundle.policy_ref("lost_or_damaged"))
        elif fulfillments:
            f = fulfillments[-1]
            lines.append(_sentence(f"It was dispatched on {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")))
            lines.append("We do not have a tracking reference on file for it, so we are checking with the courier and will come back to you.")
        else:
            lines.append(_sentence(f"It has not left us yet; it was placed on {day_words(order.get('placed_at'))}"))
            if dispatch_line:
                lines.append(_sentence(dispatch_line))
                based.append(bundle.policy_ref("dispatch"))
            held = any("held" in i.text for i in investigation.inferences)
            if held:
                lines.append("It should have gone out by now, so we are finding out what has held it and will update you.")
            lines.append("Tracking is emailed the moment it ships.")
            if "tracking_emailed" in bundle.policy:
                based.append(bundle.policy_ref("tracking_emailed"))
        if kind == "cancel" and fulfillments:
            lines.append("Because it has already been dispatched we cannot cancel it now; once it arrives you have fourteen days to return it for a refund.")
            if returns_line:
                based.append(bundle.policy_ref("returns"))
        if kind == "change_address" and fulfillments:
            lines.append("Because it has already been dispatched we cannot change the address on it now; if it comes back to us we will send it on to the new one.")
    elif kind == "cancel":
        lines.append(_sentence(f"It has not been dispatched yet (placed on {day_words(order.get('placed_at'))}), so it can still be cancelled"))
        lines.append("We have passed it to the team; you will get a confirmation once it is cancelled and the refund is on its way.")
    elif kind == "change_address":
        lines.append(_sentence(f"It has not been dispatched yet (placed on {day_words(order.get('placed_at'))}), so the address can still be changed"))
        lines.append("Could you reply with the full new address, including the postcode, and we will update it before it ships?")
    elif kind == "damaged":
        lines.append("Sorry about that. Damage in transit is on us to sort.")
        lines.append("Could you reply with a photo of the damage (and the label, if there is one)? Then we will arrange a replacement or a refund, whichever you would prefer.")
        if lost_line:
            based.append(bundle.policy_ref("lost_or_damaged"))
    elif kind == "wrong_item":
        items = [i for i in order.get("items") or [] if isinstance(i, dict)]
        if items:
            listed = "; ".join(f"{i.get('quantity') or 1} x {i.get('title') or 'item'}" + (f" ({i.get('variant')})" if i.get("variant") else "") for i in items)
            lines.append(_sentence(f"Sorry about that. Your order was for {listed}"))
        else:
            lines.append("Sorry about that.")
        lines.append("Could you reply with a photo of what arrived and its label? Then we will get the right one to you and sort the return.")
    elif kind == "missing_item":
        items = [i for i in order.get("items") or [] if isinstance(i, dict)]
        if items:
            listed = "; ".join(f"{i.get('quantity') or 1} x {i.get('title') or 'item'}" + (f" ({i.get('variant')})" if i.get("variant") else "") for i in items)
            lines.append(_sentence(f"Sorry about that. Your order should have had {listed}"))
        else:
            lines.append("Sorry about that.")
        lines.append("Could you tell us which item is missing? We will check the packing and put it right.")
    elif kind == "return_exchange":
        if open_return(order):
            name = return_name(order)
            lines.append("Your return request is already open on our side" + (f" ({name})" if name else "") + ", so there is nothing more you need to do to start it.")
            lines.append("We are confirming it now and will send you the return instructions as soon as that is done.")
            if returns_line:
                lines.append(_sentence(returns_line))
                based.append(bundle.policy_ref("returns"))
        else:
            if returns_line:
                lines.append(_sentence(returns_line))
                based.append(bundle.policy_ref("returns"))
            else:
                lines.append("Returns and exchanges are within fourteen days of delivery for unworn items with the tags on.")
            lines.append("Reply with what you would like to swap it for, or that you would like a refund, and we will send the return details.")
    if photo_line and kind in ("damaged", "wrong_item", "missing_item"):
        based.append(bundle.policy_ref("photo"))
    lines.append("")
    lines.append(signature)
    return ReplyDraft(subject=_subject(enquiry, number), body="\n".join(lines), requires_owner_approval=True,
                      based_on=tuple(dict.fromkeys(based)), not_said=tuple(u.text for u in investigation.unknowns))


def _subject(enquiry, number: Any) -> str:
    if enquiry.subject:
        return enquiry.subject if enquiry.subject.lower().startswith("re:") else f"Re: {enquiry.subject}"
    return f"Re: your CROOKS order {number}" if number else "Re: your CROOKS order"
