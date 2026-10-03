"""What a customer may return and what they are offered for it. Pure functions of the order,
the selection, the date and the settings: the portal, the submission and CLIVE's previews all
call the same code, and the server never trusts a number the browser sends back."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from returns.models import (
    FIT,
    REASON_LABELS,
    SELLER_FAULT,
    Order,
    OrderLine,
    Postage,
    Reason,
    Resolution,
    ReturnLine,
    Selection,
    Variant,
    gbp,
)
from returns.settings import Settings


class PolicyError(ValueError):
    """The request breaks a rule. The message is safe to show the customer."""


class LineCheck(BaseModel):
    fulfillment_line_item_id: str
    returnable_qty: int
    allowed_reasons: list[Reason]
    code: str  # ok | fault_only | window_closed | not_delivered | none_left
    message: str = ""
    window_ends: date | None = None
    fault_window_ends: date | None = None


class PostageOption(BaseModel):
    choice: Postage
    label: str
    fee_pence: int
    total_pence: int


class Option(BaseModel):
    resolution: Resolution
    headline: str
    detail: str
    items_pence: int
    bonus_pence: int = 0
    shipping_refund_pence: int = 0
    postage: list[PostageOption]
    # Exchange only: fulfillment line item id -> the variants it may become.
    exchange_choices: dict[str, list[Variant]] = Field(default_factory=dict)


class Quote(BaseModel):
    lines: list[ReturnLine]
    items_pence: int
    seller_fault: bool
    options: list[Option]


# ------------------------------------------------------------------------------- the window


def delivered_on(order: Order, settings: Settings) -> date | None:
    tz = ZoneInfo(settings.timezone)
    if order.delivered_at:
        return order.delivered_at.astimezone(tz).date()
    if order.fulfilled_at:
        return (
            (order.fulfilled_at + timedelta(days=settings.transit_fallback_days))
            .astimezone(tz)
            .date()
        )
    return None


def check_line(order: Order, line: OrderLine, today: date, settings: Settings) -> LineCheck:
    base = {
        "fulfillment_line_item_id": line.fulfillment_line_item_id,
        "returnable_qty": line.returnable_qty,
    }
    if line.returnable_qty < 1:
        return LineCheck(**base, allowed_reasons=[], code="none_left", message="Already returned.")
    delivered = delivered_on(order, settings)
    if delivered is None:
        return LineCheck(
            **base,
            allowed_reasons=[],
            code="not_delivered",
            message="You can start a return once your order has been delivered.",
        )
    window_ends = delivered + timedelta(days=settings.window_days)
    fault_ends = delivered + timedelta(days=settings.fault_window_days)
    dates = {"window_ends": window_ends, "fault_window_ends": fault_ends}
    excluded = bool(settings.excluded_tags() & {t.casefold() for t in line.tags})
    fault_only = sorted(SELLER_FAULT)
    if today > fault_ends:
        return LineCheck(
            **base,
            **dates,
            allowed_reasons=[],
            code="window_closed",
            message="The return window for this item has closed. "
            "If it is faulty, contact us and we will sort it out.",
        )
    if today > window_ends:
        return LineCheck(
            **base,
            **dates,
            allowed_reasons=fault_only,
            code="fault_only",
            message=f"The {settings.window_days}-day return window has closed, "
            "but you can still return it if it is faulty or wrong.",
        )
    if excluded:
        return LineCheck(
            **base,
            **dates,
            allowed_reasons=fault_only,
            code="fault_only",
            message="This item can only be returned if it is faulty or wrong.",
        )
    return LineCheck(**base, **dates, allowed_reasons=list(Reason), code="ok")


# ------------------------------------------------------------------------------- the offers


def credit_bonus(items_pence: int, settings: Settings) -> int:
    if items_pence <= 0:
        return 0  # nothing was paid, so there is nothing to top up
    bonus = 0
    for floor, amount in settings.bonus_bands():
        if items_pence >= floor:
            bonus = amount
    return bonus


def size_rank(line: OrderLine, variant_id: str) -> int | None:
    """Where a variant sits in the product's sizes, smallest first. Uses the size option when
    the product has one, otherwise the order the variants are listed in."""
    found = next((v for v in line.siblings if v.id == variant_id), None)
    if found is None:
        return None
    if line.size_option and line.sizes:
        value = found.options.get(line.size_option)
        return line.sizes.index(value) if value in line.sizes else None
    return line.siblings.index(found)


def exchange_variants(line: OrderLine, reason: Reason) -> list[Variant]:
    """What an item may be swapped for: the same product, in stock, at the same price, so an
    exchange never has a difference to pay or refund.

    Too small offers only bigger sizes and too big only smaller ones, in the same colour (or
    other options), nearest size first. A faulty item may also be swapped like-for-like.
    """
    out = []
    for v in line.siblings:
        if not v.available:
            continue
        if line.variant_price_pence is not None and v.price_pence != line.variant_price_pence:
            continue
        if v.id == line.variant_id and reason not in SELLER_FAULT:
            continue
        out.append(v)
    if reason not in FIT or line.variant_id is None:
        return out
    mine = size_rank(line, line.variant_id)
    if mine is None:
        return out
    keep = {k: val for k, val in line.options.items() if k != line.size_option}
    ranked = []
    for v in out:
        rank = size_rank(line, v.id)
        if rank is None:
            continue
        if line.size_option and any(v.options.get(k) != val for k, val in keep.items()):
            continue
        if (reason == Reason.too_small and rank > mine) or (
            reason == Reason.too_big and rank < mine
        ):
            ranked.append((abs(rank - mine), v))
    return [v for _, v in sorted(ranked, key=lambda pair: pair[0])]


def exchange_direction(line: OrderLine, to_variant_id: str) -> str:
    if to_variant_id == line.variant_id:
        return "same"
    mine = size_rank(line, line.variant_id) if line.variant_id else None
    theirs = size_rank(line, to_variant_id)
    if mine is None or theirs is None or mine == theirs:
        return "other"
    return "size_up" if theirs > mine else "size_down"


def build_lines(
    order: Order, selections: list[Selection], today: date, settings: Settings
) -> list[ReturnLine]:
    if not selections:
        raise PolicyError("Choose at least one item to return.")
    by_id = {line.fulfillment_line_item_id: line for line in order.lines}
    seen: set[str] = set()
    out = []
    for sel in selections:
        line = by_id.get(sel.fulfillment_line_item_id)
        if line is None or sel.fulfillment_line_item_id in seen:
            raise PolicyError("That item is not on this order.")
        seen.add(sel.fulfillment_line_item_id)
        check = check_line(order, line, today, settings)
        if sel.reason not in check.allowed_reasons:
            raise PolicyError(check.message or "That item cannot be returned for that reason.")
        if sel.quantity > line.returnable_qty:
            raise PolicyError(f"Only {line.returnable_qty} of {line.title} can be returned.")
        out.append(
            ReturnLine(
                fulfillment_line_item_id=line.fulfillment_line_item_id,
                line_item_id=line.line_item_id,
                title=line.title,
                variant_title=line.variant_title,
                sku=line.sku,
                variant_id=line.variant_id,
                quantity=sel.quantity,
                reason=sel.reason,
                note=sel.note.strip(),
                unit_paid_pence=line.unit_paid_pence,
            )
        )
    return out


def is_full_return(order: Order, lines: list[ReturnLine]) -> bool:
    chosen = {line.fulfillment_line_item_id: line.quantity for line in lines}
    return all(
        chosen.get(line.fulfillment_line_item_id, 0) == line.returnable_qty == line.ordered_qty
        for line in order.lines
    )


def quote(order: Order, selections: list[Selection], today: date, settings: Settings) -> Quote:
    lines = build_lines(order, selections, today, settings)
    items = sum(line.unit_paid_pence * line.quantity for line in lines)
    fault = any(line.reason in SELLER_FAULT for line in lines)
    by_id = {line.fulfillment_line_item_id: line for line in order.lines}
    options: list[Option] = []

    def free(total: int) -> list[PostageOption]:
        return [
            PostageOption(
                choice=Postage.free_label,
                label="Free Royal Mail return label",
                fee_pence=0,
                total_pence=total,
            ),
            PostageOption(
                choice=Postage.self_ship,
                label="I'll send it back myself",
                fee_pence=0,
                total_pence=total,
            ),
        ]

    # 1. Exchange, offered when every item has something in stock to become.
    choices = {
        line.fulfillment_line_item_id: exchange_variants(
            by_id[line.fulfillment_line_item_id], line.reason
        )
        for line in lines
    }
    if all(choices.values()):
        fit = any(line.reason in FIT for line in lines)
        options.append(
            Option(
                resolution=Resolution.exchange,
                headline="Swap your size" if fit else "Exchange it",
                detail="Free exchange with free return postage. Your new item ships as soon as "
                "your return arrives back with us.",
                items_pence=items,
                postage=free(0),
                exchange_choices=choices,
            )
        )

    # 2. Store credit with a bonus, and free postage: value kept, so the label is on us.
    # Not offered on items that were free (gifted, 100% off): there is no value to keep.
    if order.customer_id and items > 0:
        bonus = credit_bonus(items, settings)
        options.append(
            Option(
                resolution=Resolution.store_credit,
                headline=f"Get {gbp(items + bonus)} store credit",
                detail=f"{gbp(items)} back plus a {gbp(bonus)} bonus to spend at CROOKS, with free "
                "return postage. Added to your account when your return arrives.",
                items_pence=items,
                bonus_pence=bonus,
                postage=free(items + bonus),
            )
        )

    # 3. Refund to the original payment method: always available inside the law.
    shipping = 0
    if settings.refund_outbound_shipping_on_full_return and is_full_return(order, lines):
        shipping = order.shipping_pence
    total = items + shipping
    if fault:
        postage = free(total)
        detail = "Full refund to your original payment method, with free return postage."
    else:
        postage = [
            PostageOption(
                choice=Postage.self_ship,
                label="I'll send it back myself",
                fee_pence=0,
                total_pence=total,
            )
        ]
        fee = settings.return_label_cost_pence
        if fee is not None and fee <= total:
            postage.insert(
                0,
                PostageOption(
                    choice=Postage.paid_label,
                    label=f"Royal Mail return label, {gbp(fee)} taken off your refund",
                    fee_pence=fee,
                    total_pence=total - fee,
                ),
            )
        detail = (
            "Refund to your original payment method once your return arrives. "
            "Choose store credit or an exchange instead and return postage is free."
        )
    options.append(
        Option(
            resolution=Resolution.refund,
            headline=f"Refund {gbp(total)}",
            detail=detail,
            items_pence=items,
            shipping_refund_pence=shipping,
            postage=postage,
        )
    )
    return Quote(lines=lines, items_pence=items, seller_fault=fault, options=options)


def reason_list() -> list[dict[str, str]]:
    return [{"id": r.value, "label": REASON_LABELS[r]} for r in Reason]


def today_in(settings: Settings, now: datetime) -> date:
    return now.astimezone(ZoneInfo(settings.timezone)).date()
