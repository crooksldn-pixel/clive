"""The customer-facing draft, built only from verified facts and the published policy.

Every number, date and tracking reference in the body comes from the evidence bundle; an
unknown is answered by asking, never by guessing. A draft may state a verified fact, state
uncertainty, say what still needs doing, ask the customer for what is needed, or make a
policy-backed statement. It never says that an internal action has begun or been done
unless the bundle proves it: nothing here checks with a courier, chases, confirms or
passes anything on, and the draft must not claim otherwise. The draft is text for the owner
to read, edit and send by hand: nothing here sends, saves to the mailbox, or changes anything.
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
    fulfilment_status,
    is_uk,
    label_only,
    moving,
    open_return,
    pending_approval,
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
    first = name.split(" ")[0] if name else ""
    return first[:1].upper() + first[1:]


def _window_line(order: dict[str, Any], bundle: EvidenceBundle) -> str:
    """The delivery window for this destination, in the customer's terms; the published
    line itself when the destination is not known."""
    uk = is_uk(order)
    if uk is True:
        return "Once it is on its way, UK delivery is usually one to two working days."
    if uk is False:
        return "Once it is on its way, international delivery usually takes seven to fourteen days."
    return _sentence(_policy(bundle, "delivery_windows"))


def _returns_line(bundle: EvidenceBundle) -> str:
    """The returns rule in the customer's terms when it is the line we know; verbatim otherwise."""
    line = _policy(bundle, "returns")
    if "Fourteen days from delivery" in line and "UK size swap is free" in line:
        return ("As a reminder, returns and exchanges are within fourteen days of delivery for unworn items with the tags on; "
                "return postage is yours to cover, and a UK size swap is free with the new size sent out at our cost.")
    return _sentence(line)


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
    slow = any("without a reply from us" in i.text for i in investigation.inferences)
    if slow:
        lines.append("Sorry for the slow reply.")
    if cancelled:
        refunds = [r for r in order.get("refunds") or [] if isinstance(r, dict)]
        lines.append(_sentence(f"That order was cancelled on {day_words(order.get('cancelled_at'))}"
                               + (f" and {refunds[0].get('amount')} was refunded on {day_words(refunds[0].get('created_at'))}" if refunds and refunds[0].get("amount") else "")))
        lines.append("If that is not what you expected, reply here so it can be looked into.")
    elif kind in ("delivery", "other") or (kind in ("cancel", "change_address") and fulfillments):
        if tracked and delivered(tracked):
            f = delivered(tracked)[-1]
            when = delivered_at(order)
            lines.append(_sentence("Our records show it was delivered" + (f" on {day_words(when)}" if when else "") + (f" by {f.get('carrier')}" if f.get("carrier") else "")
                                   + f", tracking number {f.get('number')}" + (f" ({f.get('url')})" if f.get("url") else "")))
            if kind == "delivery":
                lines.append("If it is not with you, could you check with neighbours or for a safe-place card and let us know? If it has not turned up, it needs taking up with the courier, and that can be done once we hear back from you.")
        elif tracked:
            f = tracked[-1]
            late = any("running late" in i.text for i in investigation.inferences)
            if label_only([f]):
                if not slow:
                    lines.append("Sorry for the wait.")
                lines.append(_sentence(f"A shipping label was created for it on {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")
                                       + f", tracking number {f.get('number')}" + (f" - you can follow it at {f.get('url')}" if f.get("url") else "")))
                lines.append(f"Our system currently shows the shipment as {fulfilment_status(f)} rather than picked up or in transit, so we cannot confirm from our records that "
                             f"{f.get('carrier') or 'the courier'} has collected it yet. We need to check that with the courier before we can give you a definite update.")
            else:
                if late and not slow:
                    lines.append("Sorry for the wait.")
                opening = "It was dispatched on" if moving([f]) else "Our records show it as fulfilled on"
                lines.append(_sentence(f"{opening} {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")
                                       + f", tracking number {f.get('number')}" + (f" - you can follow it at {f.get('url')}" if f.get("url") else "")))
            if delivery_line:
                lines.append(_window_line(order, bundle))
                based.append(bundle.policy_ref("delivery_windows"))
            if late:
                lines.append("It is taking longer than it should, and it needs chasing with the courier before we can give you a definite update.")
            if lost_line:
                lines.append("If it does not turn up, reply here: that is on us to sort, and the options are chasing the courier, a replacement or a refund.")
                based.append(bundle.policy_ref("lost_or_damaged"))
        elif fulfillments:
            f = fulfillments[-1]
            lines.append(_sentence(f"It was dispatched on {day_words(f.get('shipped_at'))}" + (f" with {f.get('carrier')}" if f.get("carrier") else "")))
            lines.append("We do not have a tracking reference on file for it, so we need to check with the courier before we can say where it is.")
        else:
            lines.append(_sentence(f"It has not left us yet; it was placed on {day_words(order.get('placed_at'))}"))
            if dispatch_line:
                lines.append(_sentence(dispatch_line))
                based.append(bundle.policy_ref("dispatch"))
            held = any("held" in i.text for i in investigation.inferences)
            if held:
                lines.append("It should have gone out by now, and we need to find out what has held it before we can give you a date.")
            lines.append("Tracking is emailed the moment it ships.")
            if "tracking_emailed" in bundle.policy:
                based.append(bundle.policy_ref("tracking_emailed"))
        if kind == "cancel" and fulfillments:
            lines.append("Because it has already been dispatched we cannot cancel it now; once it arrives you have fourteen days to return it for a refund.")
            if returns_line:
                based.append(bundle.policy_ref("returns"))
        if kind == "change_address" and fulfillments:
            lines.append("Because it has already been dispatched we cannot change the address on it now. If it comes back to us undelivered, let us know the new address and sending it on can be looked at then.")
    elif kind == "cancel":
        lines.append(_sentence(f"It has not been dispatched yet (placed on {day_words(order.get('placed_at'))}), so it can still be cancelled"))
        lines.append("Cancelling it is a step we need to take on our side; once it has been cancelled you will get a confirmation, with the refund to follow.")
    elif kind == "change_address":
        lines.append(_sentence(f"It has not been dispatched yet (placed on {day_words(order.get('placed_at'))}), so the address can still be changed"))
        lines.append("Could you reply with the full new address, including the postcode? It needs changing on our side before it ships, so the sooner we have it the better.")
    elif kind == "damaged":
        lines.append("Sorry about that. Damage in transit is on us to sort.")
        lines.append("Could you reply with a photo of the damage (and the label, if there is one)? With that, the options are a replacement or a refund, whichever you would prefer.")
        if lost_line:
            based.append(bundle.policy_ref("lost_or_damaged"))
    elif kind == "wrong_item":
        items = [i for i in order.get("items") or [] if isinstance(i, dict)]
        if items:
            listed = "; ".join(f"{i.get('quantity') or 1} x {i.get('title') or 'item'}" + (f" ({i.get('variant')})" if i.get("variant") else "") for i in items)
            lines.append(_sentence(f"Sorry about that. Your order was for {listed}"))
        else:
            lines.append("Sorry about that.")
        lines.append("Could you reply with a photo of what arrived and its label? That is what we need to see what went wrong and to put it right.")
    elif kind == "missing_item":
        items = [i for i in order.get("items") or [] if isinstance(i, dict)]
        if items:
            listed = "; ".join(f"{i.get('quantity') or 1} x {i.get('title') or 'item'}" + (f" ({i.get('variant')})" if i.get("variant") else "") for i in items)
            lines.append(_sentence(f"Sorry about that. Your order should have had {listed}"))
        else:
            lines.append("Sorry about that.")
        lines.append("Could you tell us which item is missing? The packing needs checking on our side before it can be put right.")
    elif kind == "return_exchange":
        if open_return(order):
            name = return_name(order)
            pending_ref = pending_approval(bundle)
            state = " and is currently pending approval" if pending_ref else f" (status {order.get('return_status')})"
            lines.append("Your return request is already open on our side" + (f" ({name})" if name else "") + state + ", so you do not need to submit another request.")
            lines.append("Once it has been reviewed, we can confirm the outcome and the return instructions.")
            if pending_ref:
                based.append(pending_ref)
            if returns_line:
                lines.append(_returns_line(bundle))
                based.append(bundle.policy_ref("returns"))
        else:
            if returns_line:
                lines.append(_returns_line(bundle))
                based.append(bundle.policy_ref("returns"))
            else:
                lines.append("Returns and exchanges are within fourteen days of delivery for unworn items with the tags on.")
            lines.append("Reply with what you would like to swap it for, or that you would like a refund, and the return details can follow from there.")
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
