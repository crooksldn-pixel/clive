"""What the merchant sees, in their words. No provider ids, hashes or raw customs data in lists.

Every screen is built from these: the inbox rows, the shipment detail and Setup. The status
phrases are fixed here so the inbox, the detail and any future surface (CLIVE, email) say
the same thing:

    Ready · 1 detail needed (Missing HS code) · Address needs attention · No available service
    Provider unavailable · Purchase requires reconciliation · Label purchased — updating Shopify
    Label purchased — Shopify update needs retry · Fulfilled
"""

from __future__ import annotations

import re
from typing import Any

from shipping import contacts, readiness, tracking
from shipping.models import Address, CustomsMode, DocumentKind, Quote, Shipment
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.payment import payment
from shipping.printing import PRINTABLE, TITLES, printed
from shipping.rates import Option, Recommendation

QUESTION_PHRASES = {
    "origin": "Missing country of origin",
    "customs": "Missing HS code",
    "weight": "Missing weight",
    "package": "Package needed",
    "address": "Address needs attention",
    "no_rates": "No available service",
    "provider_unavailable": "Provider unavailable",
    "on_hold": "On hold in Shopify",
    "payment": "Payment not taken",
}
# Not something the merchant fills in: these name the problem instead of counting details.
# The first one present names the badge, so payment (the most basic) comes first.
NOT_DETAILS = ("payment", "no_rates", "provider_unavailable", "address", "on_hold")
PROBLEM_TONES = {
    "payment": "critical",
    "no_rates": "critical",
    "provider_unavailable": "caution",
    "address": "warning",
    "on_hold": "warning",
}


def phrase(q) -> str:
    """The short reason for one question: "Payment pending", "Missing HS code"."""
    if q.kind == "payment":
        return payment(q.subject).label
    return QUESTION_PHRASES.get(q.kind, "Needs a detail")


STALE = "Order changed — refresh required"

GROUP_READY, GROUP_ATTENTION, GROUP_BOUGHT, GROUP_DONE = "ready", "attention", "bought", "done"


def numeric_id(gid: str | None) -> str | None:
    found = re.search(r"/(\d+)$", gid or "")
    return found.group(1) if found else None


def status_of(s: Shipment) -> dict[str, Any]:
    """{label, tone, group, reasons}: one badge and the phrases behind it."""
    reasons = []
    for q in s.questions:
        said = phrase(q)
        if said not in reasons:
            reasons.append(said)
    if s.status == S.needs_attention:
        problem = min(
            (q for q in s.questions if q.kind in NOT_DETAILS),
            key=lambda q: NOT_DETAILS.index(q.kind),
            default=None,
        )
        if problem is not None:
            tone = PROBLEM_TONES[problem.kind]
            return _badge(phrase(problem), tone, GROUP_ATTENTION, reasons)
        n = len([q for q in s.questions if q.kind not in NOT_DETAILS]) or 1
        return _badge(
            f"{n} detail{'s' if n != 1 else ''} needed", "warning", GROUP_ATTENTION, reasons
        )
    fixed = {
        S.discovered: ("Checking", "info", GROUP_ATTENTION),
        S.ready: ("Ready", "success", GROUP_READY),
        S.purchasing: ("Buying label", "info", GROUP_ATTENTION),
        S.reconciliation_required: (
            "Purchase requires reconciliation",
            "critical",
            GROUP_ATTENTION,
        ),
        S.label_purchased: ("Label purchased — updating Shopify", "info", GROUP_BOUGHT),
        S.fulfillment_failed: (
            "Label purchased — Shopify update needs retry",
            "critical",
            GROUP_ATTENTION,
        ),
        S.fulfilled: ("Fulfilled", "success", GROUP_BOUGHT),
        S.in_transit: ("In transit", "success", GROUP_DONE),
        S.delivered: ("Delivered", "success", GROUP_DONE),
        S.cancelled: ("Cancelled in Shopify", "neutral", GROUP_DONE),
        S.void_requested: ("Cancelling label", "info", GROUP_ATTENTION),
        S.voided: ("Label cancelled", "neutral", GROUP_DONE),
        S.void_rejected: ("Label cancellation refused", "critical", GROUP_ATTENTION),
    }
    label, tone, group = fixed.get(
        s.status, (s.status.value.replace("_", " ").capitalize(), "neutral", GROUP_DONE)
    )
    return _badge(label, tone, group, reasons)


def _badge(label: str, tone: str, group: str, reasons: list[str]) -> dict[str, Any]:
    return {"label": label, "tone": tone, "group": group, "reasons": reasons}


def hs_text(code: str | None) -> str | None:
    """ "611020" -> "6110.20"; "6109100010" -> "6109.10.0010"."""
    if not code:
        return code
    return ".".join(x for x in (code[:4], code[4:6], code[6:]) if x)


def place(d) -> str:
    """ "New York, NY 10004" """
    tail = " ".join(x for x in (d.region, d.postcode) if x)
    return ", ".join(x for x in (d.city, tail) if x)


def kg(grams: int) -> str:
    return f"{grams / 1000:.2f} kg"


def package_text(s: Shipment) -> str:
    p = s.package
    if p is None:
        return "Package needed"
    return f"{p.name} · {kg(p.total_weight_g)}" if p.items_weight_g else p.name


def shipping_text(s: Shipment) -> str:
    if s.label is not None:
        return f"{s.label.carrier} · {s.label.amount}"
    if s.quote is not None:
        return f"{s.quote.carrier} · {s.quote.amount}"
    return "—"


def row(s: Shipment) -> dict[str, Any]:
    st = status_of(s)
    return {
        "id": s.id,
        "order": s.order_name,
        "destination": {"country": s.destination.country, "city": s.destination.city},
        "package": package_text(s),
        "shipping": shipping_text(s),
        "status": st,
        "printed": printed(s),
        "can_print": s.label is not None and s.status in PRINTABLE,
        "updated_at": s.updated_at.isoformat(),
    }


def matches(s: Shipment, q: str) -> bool:
    q = q.strip().casefold()
    if not q:
        return True
    digits = re.sub(r"\D", "", q)
    d = s.destination
    hay = " ".join((s.order_name, d.name, d.city, d.country)).casefold()
    return q in hay or bool(digits and digits == re.sub(r"\D", "", s.order_name))


# --------------------------------------------------------------------------- detail


def option_view(o: Option, chosen: Quote | None) -> dict[str, Any]:
    q = o.quote
    days = (
        f"{q.est_days_min}–{q.est_days_max} days"
        if q.est_days_min and q.est_days_max and q.est_days_min != q.est_days_max
        else (f"Up to {q.est_days_max} days" if q.est_days_max else "Delivery time not given")
    )
    return {
        "code": q.service_code,
        "title": q.title,
        "carrier": q.carrier,
        "price": str(q.amount),
        "price_minor": q.amount.minor,
        "days": days,
        "paperwork": o.paperwork.summary,
        "paperless": o.paperwork.mode == CustomsMode.electronic,
        "paperwork_source": o.paperwork.source,
        "roles": list(o.roles),
        "reason": o.reason,
        "chosen": chosen is not None and chosen.service_code == q.service_code,
        "provider": q.provider,
        "tracked": q.tracked,
        "handover": {
            "dropoff": "Drop-off",
            "collection": "Collection",
            "either": "Drop-off or collection",
        }.get(q.handover, ""),
    }


def shipping_view(s: Shipment, rec: Recommendation) -> dict[str, Any]:
    def one(o: Option | None) -> dict[str, Any] | None:
        return option_view(o, s.quote) if o else None

    chosen = next((o for o in rec.options if s.quote and o.quote is s.quote), None) or next(
        (o for o in rec.options if s.quote and o.quote.service_code == s.quote.service_code),
        None,
    )
    return {
        "chosen": one(chosen),
        "recommended": one(rec.recommended),
        "cheapest": one(rec.cheapest),
        "fastest": one(rec.fastest),
        "options": [option_view(o, s.quote) for o in rec.options],
        "overridden": bool(s.service_choice),
        "provider_failures": [f.model_dump(mode="json") for f in s.provider_failures],
        "note": (
            " ".join(f.safe_message for f in s.provider_failures)
            + (
                f" {' and '.join(sorted({o.quote.provider for o in rec.options}))} "
                "rates are shown instead."
                if rec.options
                else ""
            )
        )
        if s.provider_failures
        else None,
    }


def customs_view(s: Shipment, rec: Recommendation) -> dict[str, Any]:
    value = Money(
        minor=sum(ln.unit_value.minor * ln.quantity for ln in s.lines), currency=s.currency
    )
    items = sum(ln.quantity for ln in s.lines)
    out: dict[str, Any] = {
        "summary": f"{items} item{'s' if items != 1 else ''} · {value}",
        "complete": all(ln.hs_code and ln.origin_country for ln in s.lines),
        "duties": s.duties.summary if s.duties else None,
        "incoterm": s.duties.incoterm if s.duties else None,
    }
    label = s.label
    if label is None:
        chosen = next(
            (o for o in rec.options if s.quote and o.quote.service_code == s.quote.service_code),
            None,
        )
        out["expected"] = chosen.paperwork.summary if chosen else None
        out["state"] = "before_purchase"
        return out
    if label.customs == CustomsMode.electronic:
        out["state"] = "electronic"
        out["text"] = "Electronic ✓"
        out["confirming"] = not label.customs_confirmed
    elif label.customs == CustomsMode.paper:
        out["state"] = "paper"
        docs = [
            d for d in label.documents if d.kind != DocumentKind.shipping_label and d.must_print
        ]
        parts = [
            f"{TITLES.get(d.kind, d.kind.value)} — {d.copies_required} "
            f"cop{'y' if d.copies_required == 1 else 'ies'} — {d.page_size.value}"
            for d in docs
        ]
        out["text"] = "Customs paperwork required — " + ("; ".join(parts) or "see documents")
    elif label.customs == CustomsMode.not_required:
        out["state"] = "not_required"
        out["text"] = "No customs on this route"
    else:
        out["state"] = "unknown"
        out["text"] = "Checking customs paperwork with the carrier"
    return out


def steps(s: Shipment) -> list[dict[str, Any]]:
    """After purchase: label purchased → Shopify fulfilment created → tracking on the order
    (verified by reading Shopify back)."""
    fulfilled = s.status in (S.fulfilled, S.in_transit, S.delivered)
    verified = next((e for e in s.timeline if e.type == "fulfilled" and e.verified), None)
    return [
        {"key": "label", "label": "Label purchased", "done": s.label is not None},
        {
            "key": "created",
            "label": "Shopify fulfilment created",
            "done": bool(s.fulfillment_id) or fulfilled,
        },
        {
            "key": "verified",
            "label": "Tracking on the order (checked in Shopify)",
            "done": fulfilled and verified is not None,
        },
    ]


def actions(s: Shipment) -> list[str]:
    by_status = {
        S.needs_attention: ["answer", "package", "refresh"],
        S.ready: ["package", "service", "preview", "buy", "refresh"],
        S.label_purchased: ["print"],
        S.fulfillment_failed: ["retry_shopify", "print"],
        S.fulfilled: ["print"],
        S.in_transit: ["print"],
        S.discovered: ["refresh"],
        S.reconciliation_required: [],
        S.purchasing: [],
    }
    out = list(by_status.get(s.status, []))
    if "print" in out and printed(s):
        out[out.index("print")] = "reprint"
    return out


TIMELINE = {
    "discovered": "Found in Shopify",
    "needs_attention": "Waiting for a detail",
    "ready": "Ready to ship",
    "answered": "Detail saved",
    "package_added": "Package added",
    "package_chosen": "Package changed",
    "service_chosen": "Service changed",
    "service_choice_dropped": "Chosen service no longer offered",
    "order_changed": "Order changed in Shopify",
    "price_updated": "Price updated",
    "purchase_authorised": "Buy label clicked",
    "label_purchased": "Label purchased",
    "fulfillment_created": "Shopify fulfilment created",
    "fulfilled": "Tracking on the order (checked)",
    "fulfillment_failed": "Shopify update failed",
    "fulfillment_retry_failed": "Shopify update failed again",
    "label_printed": "Label sent to the printer (PrintNode)",
    "label_reprinted": "Extra copy sent to the printer (PrintNode)",
    "label_print_done": "Printer finished printing the label",
    "label_print_failed": "Label didn't print",
    "label_print_view": "Label opened to print",
    "label_print_view_again": "Label opened to print again",
    "alert": "Alert",
    "order_closed": "Order closed in Shopify",
    "on_hold": "On hold in Shopify",
    "payment_blocking": "Payment doesn't allow a label",
    "payment_cleared": "Payment taken: ready to price",
    "carrier_pre_transit": "Waiting for the carrier",
    "carrier_in_transit": "In transit (carrier)",
    "carrier_out_for_delivery": "Out for delivery",
    "carrier_delivery_attempted": "Delivery attempted",
    "carrier_ready_for_pickup": "Ready for pickup",
    "carrier_delivered": "Delivered (carrier)",
    "carrier_exception": "Carrier reports a problem",
    "carrier_cancelled": "Fulfilment cancelled in Shopify",
    "carrier_unknown": "No carrier update yet",
    "provider_unavailable": "Prices unavailable",
    "no_rates": "No courier offered a price",
    "payment_outcome_unknown": "Checking whether the label was paid",
    "payment_not_taken": "Not charged: the label wasn't bought",
    "purchase_failed": "Label not bought (nothing charged)",
    "reprinted": "Document printed again",
    "void_requested": "Label cancellation sent",
    "voided": "Label cancelled",
    "void_rejected": "Cancellation refused",
    "tracking_received": "Tracking number received",
}


def payment_view(s: Shipment) -> dict[str, Any]:
    state = payment(s.payment_status)
    bought = s.label is not None
    note = (
        "label purchase blocked"
        if not state.allows_purchase and not bought
        else "changed after the label was bought"
        if not state.allows_purchase
        else ""
    )
    return {"label": state.label, "tone": state.tone, "note": note, "reason": state.reason}


def fulfilment_view(s: Shipment) -> dict[str, Any]:
    if s.label is None:
        return {"label": "No label yet", "tone": "neutral"}
    st = status_of(s)
    return {"label": st["label"], "tone": st["tone"]}


def carrier_view(s: Shipment) -> dict[str, Any] | None:
    """Shopify's carrier tracking for a bought label (shipping.tracking); None before."""
    if s.label is None:
        return None
    t = s.tracking
    if t is None:
        return {"stage": "unknown", "label": tracking.LABELS["unknown"], "tone": "neutral",
                "note": "Checked once Shopify has the fulfilment.", "checked_at": None}  # fmt: skip
    tone = {"delivered": "success", "exception": "warning", "cancelled": "critical"}.get(
        t.stage, "info" if t.stage in tracking.MOVING else "neutral"
    )
    return {
        "stage": t.stage,
        "label": tracking.LABELS.get(t.stage, t.stage),
        "tone": tone,
        "display_status": t.display_status,
        "in_transit_at": t.in_transit_at,
        "delivered_at": t.delivered_at,
        "estimated_delivery_at": t.estimated_delivery_at,
        "checked_at": t.checked_at.isoformat() if t.checked_at else None,
        "note": t.note,
    }


def detail(
    s: Shipment,
    rec: Recommendation,
    presets: list[dict[str, Any]],
    may_buy: bool = True,
    may_cancel: bool = False,
    origin: Address | None = None,
) -> dict[str, Any]:
    d = s.destination
    gaps = readiness.address_gaps(d)
    p = s.package
    label = s.label
    out: dict[str, Any] = {
        **row(s),
        "order_admin_id": numeric_id(s.order_id),
        "address": {
            "lines": [x for x in (d.name, d.company, d.line1, d.line2, place(d)) if x],
            "country": d.country,
            "ok": not gaps,
            "gaps": gaps,
            # Booking data only, e.g. "Carrier contact: store phone used because ..."
            "contact_note": contacts.note(contacts.recipient(d, origin)[1]) or None,
        },
        # Who the label is (or would be) bought from, for messages about it.
        "provider": (label.provider if label and label.provider else None)
        or (s.quote.provider if s.quote else None),
        "products": [
            {
                "title": ln.title,
                "variant": ln.variant_title,
                "sku": ln.sku,
                "quantity": ln.quantity,
                "unit_value": str(ln.unit_value),
                "weight": f"{ln.unit_weight_g} g" if ln.unit_weight_g else None,
                "hs_code": hs_text(ln.hs_code),
                "hs_code_value": ln.hs_code,
                "origin": ln.origin_country,
                "description": ln.customs_description,
                "subject": ln.product_id or ln.title,
            }
            for ln in s.lines
        ],
        "questions": [
            {
                **q.model_dump(),
                "phrase": QUESTION_PHRASES.get(q.kind, "Needs a detail"),
                "tone": PROBLEM_TONES.get(q.kind, "warning"),
                "is_detail": q.kind not in NOT_DETAILS,
            }
            for q in s.questions
        ],
        "package": None
        if p is None
        else {
            "preset_id": p.preset_id,
            "name": p.name,
            "size": f"{p.length_mm / 10:g} × {p.width_mm / 10:g} × {p.height_mm / 10:g} cm",
            "weight": kg(p.total_weight_g) if p.items_weight_g else None,
            "source": {
                "merchant": "You chose this",
                "learned": "Used last time for these items",
                "default": "Your default package",
            }.get(p.source, ""),
        },
        "presets": presets,
        "shipping": shipping_view(s, rec),
        "customs": customs_view(s, rec),
        "label": None,
        "steps": steps(s) if label is not None else [],
        "alerts": list(s.alerts),
        "error": s.last_error,
        "actions": [a for a in actions(s) if may_buy or a != "buy"]
        + (["cancel_label"] if may_cancel else []),
        "buy_authorised": may_buy,
        "timeline": [
            {
                "at": e.at.isoformat(),
                "what": TIMELINE.get(e.type, e.type.replace("_", " ").capitalize()),
                "who": e.actor,
                "verified": e.verified,
            }
            for e in reversed(s.timeline[-30:])
        ],
    }
    if label is not None:
        out["label"] = {
            "provider": label.provider,
            "carrier": label.carrier,
            "service": label.service_name[len(label.carrier) :].strip()
            if label.service_name.lower().startswith(label.carrier.lower())
            else label.service_name,
            "price": str(label.amount),
            "tracking": label.tracking_number,
            "tracking_url": label.tracking_url,
            "documents": [
                {
                    "kind": doc.kind.value,
                    "title": TITLES.get(doc.kind, doc.kind.value),
                    "artifact_id": doc.artifact_id,
                    "page_size": doc.page_size.value,
                    "copies": doc.copies_required,
                    "must_print": doc.must_print or doc.kind == DocumentKind.shipping_label,
                    "note": doc.note,
                }
                for doc in label.documents
                if doc.artifact_id
            ],
            "printed": printed(s),
            # Safe to show staff (no access hashes): for a support call to the provider.
            "reference": " / ".join(label.provider_ids.values()) or None,
        }
    return out
