"""The packing slip: what is in the parcel, by size and price, with the order total; for an
exchange, what was swapped for what and why. Read live from Shopify when printed (the order as
it is now) and drawn on the 4x6 label roll, so it prints on the same printer as the labels.

Pure: `parse` turns Shopify's answer into a `Slip`; `render` draws it. The routes fetch and print.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from shipping.money import Money, money

PAGE = (288.0, 432.0)  # 4 x 6 inches, portrait: the label roll
MARGIN = 14.0
INK = (0, 0, 0)
GREY = (0, 0, 0)  # thermal printers dither grey into dots: everything solid black


@dataclass
class SlipLine:
    title: str
    size: str
    sku: str
    quantity: int
    unit: Money

    @property
    def total(self) -> Money:
        return Money(minor=self.unit.minor * self.quantity, currency=self.unit.currency)


@dataclass
class Swap:
    """One exchanged item: what came back, what goes out, and why."""

    from_title: str
    from_size: str
    to_title: str
    to_size: str
    quantity: int
    kind: str  # "Size swap" (same product) or "Credit swap" (a different item)
    reason: str | None

    @property
    def words(self) -> str:
        """'Blue Jeans XS > S' for a size swap; 'Joggers XS > Blue Jeans S' otherwise."""
        if self.kind == "Size swap":
            return f"{self.to_title} {self.from_size} > {self.to_size}".strip()
        return f"{self.from_title} {self.from_size} > {self.to_title} {self.to_size}".strip()


@dataclass
class Exchange:
    return_name: str
    swaps: list[Swap]


@dataclass
class Slip:
    order_name: str
    created_at: datetime | None
    ship_to: list[str]
    lines: list[SlipLine]
    subtotal: Money | None = None
    discounts: Money | None = None
    shipping: Money | None = None
    total: Money | None = None
    exchange: Exchange | None = None
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ parse


def _money(node: dict[str, Any] | None, currency: str) -> Money | None:
    shop = (node or {}).get("shopMoney") or {}
    if shop.get("amount") in (None, ""):
        return None
    return money(shop["amount"], shop.get("currencyCode") or currency)


def _when(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _size(variant_title: str | None) -> str:
    title = (variant_title or "").strip()
    return "" if title == "Default Title" else title


def parse(node: dict[str, Any]) -> Slip:
    """A fulfillment order (with its order and the order's returns) as read by Q_SLIP."""
    order = node.get("order") or {}
    currency = order.get("currencyCode") or "GBP"
    lines, line_ids = [], set()
    for n in (node.get("lineItems") or {}).get("nodes") or []:
        qty = int(n.get("totalQuantity") or 0)
        item = n.get("lineItem") or {}
        if item.get("id"):
            line_ids.add(item["id"])
        if qty <= 0:
            continue
        unit = _money(item.get("discountedUnitPriceAfterAllDiscountsSet"), currency)
        lines.append(
            SlipLine(
                title=n.get("productTitle") or "Item",
                size=_size(n.get("variantTitle")),
                sku=n.get("sku") or "",
                quantity=qty,
                unit=unit or Money(minor=0, currency=currency),
            )
        )
    address = order.get("shippingAddress") or {}
    ship_to = [
        x
        for x in (
            address.get("name") or (order.get("customer") or {}).get("displayName"),
            " ".join(p for p in (address.get("city"), address.get("zip")) if p),
        )
        if x
    ]
    discounts = _money(order.get("currentTotalDiscountsSet"), currency)
    return Slip(
        order_name=order.get("name") or "",
        created_at=_when(order.get("createdAt")),
        ship_to=ship_to,
        lines=lines,
        subtotal=_money(order.get("currentSubtotalPriceSet"), currency),
        discounts=discounts if discounts and discounts.minor else None,
        shipping=_money(order.get("currentShippingPriceSet"), currency),
        total=_money(order.get("currentTotalPriceSet"), currency),
        exchange=exchange_for(order, line_ids),
    )


def exchange_for(order: dict[str, Any], line_ids: set[str]) -> Exchange | None:
    """The return whose exchange items are what this parcel carries, as swaps: an exchange item
    is paired with a returned item of the same product (a size swap), otherwise with the next
    returned item (a swap for something else, paid with the returned item's credit)."""
    for ret in (order.get("returns") or {}).get("nodes") or []:
        out = []
        for ex in (ret.get("exchangeLineItems") or {}).get("nodes") or []:
            for li in ex.get("lineItems") or []:
                out.append((li, int(ex.get("quantity") or 1)))
        if not any(li.get("id") in line_ids for li, _ in out):
            continue
        back = []
        for r in (ret.get("returnLineItems") or {}).get("nodes") or []:
            item = ((r.get("fulfillmentLineItem") or {}).get("lineItem")) or {}
            reason = (r.get("returnReasonDefinition") or {}).get("name")
            back.append({"item": item, "reason": reason, "used": False})
        swaps = []
        for li, qty in out:
            pid = (li.get("product") or {}).get("id")
            match = next(
                (
                    b
                    for b in back
                    if not b["used"] and (b["item"].get("product") or {}).get("id") == pid
                ),
                None,
            )
            kind = "Size swap" if match else "Credit swap"
            match = match or next((b for b in back if not b["used"]), None)
            if match:
                match["used"] = True
            gone = (match or {}).get("item") or {}
            swaps.append(
                Swap(
                    from_title=gone.get("title") or "",
                    from_size=_size(gone.get("variantTitle")),
                    to_title=li.get("title") or "",
                    to_size=_size(li.get("variantTitle")),
                    quantity=qty,
                    kind=kind,
                    reason=(match or {}).get("reason"),
                )
            )
        return Exchange(return_name=ret.get("name") or "", swaps=swaps)
    return None


# ------------------------------------------------------------------ render


class _Pages:
    """A cursor down 4x6 pages; a new page when the next block won't fit."""

    def __init__(self, slip: Slip) -> None:
        self.buf = BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=PAGE)
        self.c.setTitle(f"Packing slip {slip.order_name}")
        self.slip = slip
        self.y = 0.0
        self.page = 0
        self.start()

    def start(self) -> None:
        self.page += 1
        c, w, h = self.c, PAGE[0], PAGE[1]
        self.y = h - MARGIN
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(MARGIN, self.y - 18, "CROOKS")
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(w - MARGIN, self.y - 10, self.slip.order_name)
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(*GREY)
        sub = "PACKING SLIP" if self.page == 1 else f"PACKING SLIP · PAGE {self.page}"
        if self.slip.created_at and self.page == 1:
            sub += f" · {self.slip.created_at.strftime('%-d %b %Y')}"
        c.drawRightString(w - MARGIN, self.y - 21, sub)
        self.y -= 30
        self.rule(1.2)

    def rule(self, width: float = 0.5) -> None:
        self.c.setLineWidth(width)
        self.c.setStrokeColorRGB(*INK)
        self.c.line(MARGIN, self.y, PAGE[0] - MARGIN, self.y)
        self.y -= 8

    def need(self, height: float) -> None:
        if self.y - height < MARGIN + 18:
            self.c.showPage()
            self.start()

    def text(self, words: str, size: float = 9, bold: bool = False, grey: bool = False) -> None:
        font = "Helvetica-Bold" if bold else "Helvetica"
        for part in simpleSplit(words, font, size, PAGE[0] - 2 * MARGIN) or [""]:
            self.need(size + 3)
            self.c.setFont(font, size)
            self.c.setFillColorRGB(*(GREY if grey else INK))
            self.c.drawString(MARGIN, self.y - size, part)
            self.y -= size + 3

    def finish(self) -> bytes:
        self.c.setFont("Helvetica", 7)
        self.c.setFillColorRGB(*GREY)
        self.c.drawCentredString(
            PAGE[0] / 2, MARGIN, "Thank you for shopping with CROOKS · crooksldn.com"
        )
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def render(slip: Slip) -> bytes:
    p = _Pages(slip)
    c, right = p.c, PAGE[0] - MARGIN
    if slip.ship_to:
        p.text("SHIP TO", 7, grey=True)
        p.text(slip.ship_to[0], 10, bold=True)
        for extra in slip.ship_to[1:]:
            p.text(extra, 8.5)
        p.y -= 2
        p.rule()

    p.need(14)
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(*GREY)
    c.drawString(MARGIN, p.y - 7, "ITEM")
    c.drawRightString(right - 62, p.y - 7, "QTY")
    c.drawRightString(right, p.y - 7, "PRICE")
    p.y -= 12
    for line in slip.lines:
        title = simpleSplit(line.title, "Helvetica-Bold", 9.5, 170) or [line.title]
        p.need(12 * len(title) + 12)
        top = p.y
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 9.5)
        for i, part in enumerate(title):
            c.drawString(MARGIN, top - 9.5 - i * 11.5, part)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawRightString(right - 62, top - 9.5, f"{line.quantity}")
        c.drawRightString(right, top - 9.5, str(line.total))
        y = top - 9.5 - len(title) * 11.5
        detail = " · ".join(x for x in (f"Size {line.size}" if line.size else "", line.sku) if x)
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*GREY)
        if detail:
            c.drawString(MARGIN, y, detail)
        if line.quantity > 1:
            c.drawRightString(right, y, f"{line.quantity} × {line.unit}")
        p.y = y - 8
    p.rule()

    if slip.exchange is None:
        rows = [
            ("Subtotal", str(slip.subtotal) if slip.subtotal else None),
            ("Discounts", f"-{slip.discounts}" if slip.discounts else None),
            ("Shipping", str(slip.shipping) if slip.shipping else None),
        ]
        for label, value in rows:
            if value is None:
                continue
            p.need(12)
            c.setFont("Helvetica", 8.5)
            c.setFillColorRGB(*INK)
            c.drawString(MARGIN, p.y - 8.5, label)
            c.drawRightString(right, p.y - 8.5, value)
            p.y -= 12
        if slip.total is not None:
            p.need(18)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(MARGIN, p.y - 12, "Order total")
            c.drawRightString(right, p.y - 12, str(slip.total))
            p.y -= 18
    else:
        ex = slip.exchange
        rows = []
        for s in ex.swaps:
            rows.append((f"{s.quantity} × {s.words}" if s.quantity > 1 else s.words, 9.5, True))
            rows.append((" · ".join(x for x in (s.kind, s.reason) if x), 8, False))
        height = 30 + sum(
            len(
                simpleSplit(t, "Helvetica-Bold" if b else "Helvetica", z, PAGE[0] - 2 * MARGIN - 16)
            )
            * (z + 3)
            for t, z, b in rows
        )
        p.need(height + 6)
        top = p.y - 2
        c.setLineWidth(2)
        c.rect(MARGIN, top - height, PAGE[0] - 2 * MARGIN, height)
        c.setFillColorRGB(*INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGIN + 8, top - 15, "EXCHANGE ORDER")
        c.setFont("Helvetica", 7.5)
        if ex.return_name:
            c.drawRightString(right - 8, top - 14, f"Return {ex.return_name}")
        y = top - 24
        for words, size, bold in rows:
            font = "Helvetica-Bold" if bold else "Helvetica"
            for part in simpleSplit(words, font, size, PAGE[0] - 2 * MARGIN - 16):
                c.setFont(font, size)
                c.drawString(MARGIN + 8, y - size, part)
                y -= size + 3
        p.y = top - height - 8
    return p.finish()
