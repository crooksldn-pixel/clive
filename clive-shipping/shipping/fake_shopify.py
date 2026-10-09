"""A stand-in Shopify: fulfillment orders, InventoryItem customs facts, fulfillments. Records
every write so tests can say exactly what Shopify would have been told."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

from shipping.models import Address
from shipping.money import Money
from shipping.shopify import (
    FoLine,
    FoSnapshot,
    FulfillmentTracking,
    ItemFacts,
    ShopifyError,
    ShopifyRefused,
)

BOURNE_END = Address(
    name="Bourne End",
    line1="Unit M",
    line2="Bourne End Business Park",
    city="Bourne End",
    postcode="SL8 5AS",
    country="GB",
    phone="07700900000",
)


def tee_line(n: int = 1, qty: int = 2, size: str = "M", price: int = 3700) -> FoLine:
    return FoLine(
        id=f"gid://shopify/FulfillmentOrderLineItem/{n}",
        quantity=qty,
        title="Express Tee",
        variant_title=f"Black / {size}",
        sku=f"TEE-BLK-{size}",
        variant_id=f"gid://shopify/ProductVariant/tee-{size}",
        product_id="gid://shopify/Product/tee",
        product_type="T-Shirt",
        inventory_item_id=f"gid://shopify/InventoryItem/tee-{size}",
        unit_value=Money(minor=price),
        weight_g=220,
    )


def hoodie_line(n: int = 2, qty: int = 1) -> FoLine:
    return FoLine(
        id=f"gid://shopify/FulfillmentOrderLineItem/{n}",
        quantity=qty,
        title="Heavyweight Hoodie",
        variant_title="Grey / L",
        sku="HOOD-GRY-L",
        variant_id="gid://shopify/ProductVariant/hood-L",
        product_id="gid://shopify/Product/hood",
        product_type="Hoodie",
        inventory_item_id="gid://shopify/InventoryItem/hood-L",
        unit_value=Money(minor=6500),
        weight_g=None,
    )


def fo(
    n: int,
    lines: list[FoLine],
    country: str = "DE",
    name: str | None = None,
    shipping_line: str | None = "Tracked 48",
) -> FoSnapshot:
    dest = Address(
        name="Max Muster",
        line1="Torstrasse 12",
        city="Berlin",
        postcode="10115",
        country=country,
        phone="+4915112345678",
        email="max@example.com",
    )
    if country == "US":
        dest = Address(
            name="Sam Lee",
            line1="1 Broadway",
            city="New York",
            region="NY",
            postcode="10004",
            country="US",
            phone="+12125550100",
        )
    if country == "GB":
        dest = Address(
            name="Jo Bloggs", line1="1 Brick Lane", city="London", postcode="E1 6AN", country="GB"
        )
    return FoSnapshot(
        id=f"gid://shopify/FulfillmentOrder/{n}",
        status="OPEN",
        order_id=f"gid://shopify/Order/{n}",
        order_name=name or f"CROOKS-{n}",
        order_cancelled=False,
        currency="GBP",
        destination=dest,
        origin=BOURNE_END,
        origin_location_id="gid://shopify/Location/1",
        lines=lines,
        financial_status="PAID",
        shipping_line=shipping_line,
    )


@dataclass
class FakeShopify:
    fos: dict[str, FoSnapshot] = field(default_factory=dict)
    items: dict[str, ItemFacts] = field(default_factory=dict)
    products: dict[str, list[str]] = field(default_factory=dict)
    fulfillments: list[dict] = field(default_factory=list)
    writes: list[tuple] = field(default_factory=list)
    refuse_item_update: bool = False
    refuse_fulfillment: int = 0  # refuse this many times (userErrors)
    fulfillment_reply_lost: bool = False  # creates it, then raises (reply lost)
    fo_reads_fail: int = 0  # fulfillment_order() raises this many times
    tracking_reads: list[str] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(5000))

    def add(self, snap: FoSnapshot) -> FoSnapshot:
        self.fos[snap.id] = snap
        for ln in snap.lines:
            self.items.setdefault(ln.inventory_item_id, ItemFacts(None, None, ln.weight_g))
            ids = self.products.setdefault(ln.product_id, [])
            if ln.inventory_item_id not in ids:
                ids.append(ln.inventory_item_id)
        return snap

    def open_fulfillment_orders(self) -> list[FoSnapshot]:
        return [copy.deepcopy(f) for f in self.fos.values() if f.open]

    def carrier(self, number: str, display: str, **when: str | None) -> None:
        """The carrier moved a parcel: as Shopify would show it on the fulfilment."""
        f = next(f for f in self.fulfillments if f["number"] == number)
        f["display"] = display
        f.update(when)

    def _tracking(self, f: dict) -> FulfillmentTracking:
        order = next((x for x in self.fos.values() if x.order_id == f.get("order_id")), None)
        return FulfillmentTracking(
            id=f["id"],
            status=f.get("status", "SUCCESS"),
            display_status=f.get("display"),
            in_transit_at=f.get("in_transit_at"),
            delivered_at=f.get("delivered_at"),
            estimated_delivery_at=f.get("estimated_delivery_at"),
            updated_at=f.get("updated_at"),
            numbers=[f["number"]],
            financial_status=order.financial_status if order else None,
            order_created_at=order.order_created_at if order else None,
            customer_name=order.customer_name if order else None,
            events=list(f.get("events", [])),
        )

    staff_name: str | None = None  # what the token exchange would say; None: refused
    timezone: str | None = "Europe/London"

    def shop_timezone(self) -> str | None:
        return self.timezone

    def staff_member(self, id_token: str) -> str | None:
        return self.staff_name

    def scan(self, number: str, status: str, message: str, at: str, country: str = "GB") -> None:
        """The carrier scanned a parcel: a FulfillmentEvent on its fulfilment, as Shopify keeps
        it (status, time, the carrier's words, where)."""
        f = next(f for f in self.fulfillments if f["number"] == number)
        f.setdefault("events", []).append(
            dict(status=status, at=at, message=message, city=None, province=None, country=country)
        )

    def fulfillment_tracking(self, fulfillment_id: str) -> FulfillmentTracking | None:
        self.tracking_reads.append(fulfillment_id)
        found = next((f for f in self.fulfillments if f["id"] == fulfillment_id), None)
        return self._tracking(found) if found else None

    def order_fulfillments(self, order_id: str) -> list[FulfillmentTracking]:
        self.tracking_reads.append(order_id)
        return [self._tracking(f) for f in self.fulfillments if f.get("order_id") == order_id]

    def fulfillment_order(self, fo_id: str) -> FoSnapshot | None:
        if self.fo_reads_fail:
            self.fo_reads_fail -= 1
            raise ShopifyError("Shopify could not be reached")
        found = self.fos.get(fo_id)
        return copy.deepcopy(found) if found else None

    def item_facts(self, inventory_item_ids: list[str]) -> dict[str, ItemFacts]:
        return {i: copy.deepcopy(self.items[i]) for i in inventory_item_ids if i in self.items}

    def product_items(self, product_id: str) -> list[str]:
        return list(self.products.get(product_id, []))

    def update_item(self, inventory_item_id, *, hs_code=None, origin_country=None, weight_g=None):
        if self.refuse_item_update:
            raise ShopifyRefused("Access denied for inventoryItemUpdate")
        self.writes.append(
            ("inventoryItemUpdate", inventory_item_id, hs_code, origin_country, weight_g)
        )
        item = self.items.setdefault(inventory_item_id, ItemFacts(None, None, None))
        item.hs_code = hs_code or item.hs_code
        item.origin_country = origin_country or item.origin_country
        item.weight_g = weight_g or item.weight_g

    def create_fulfillment(self, fo_id, lines, company, number, url, notify) -> str:
        if self.refuse_fulfillment:
            self.refuse_fulfillment -= 1
            raise ShopifyRefused("Fulfillment order is on hold")
        fid = f"gid://shopify/Fulfillment/{next(self._ids)}"
        self.fulfillments.append(
            {
                "id": fid,
                "fo": fo_id,
                "lines": lines,
                "company": company,
                "number": number,
                "url": url,
                "notify": notify,
            }
        )
        snap = self.fos[fo_id]
        self.fulfillments[-1].update(order_id=snap.order_id, status="SUCCESS", display="CONFIRMED")
        snap.tracking_numbers.append(number)
        snap.status = "CLOSED"
        if self.fulfillment_reply_lost:
            self.fulfillment_reply_lost = False
            raise ShopifyError("connection reset after sending")
        return fid


# --------------------------------------------------------------------------- Shopify Shipping


def label_pdf(width_pt: float = 288, height_pt: float = 432, text: str = "ROYAL MAIL") -> bytes:
    """A one-page PDF of the given size: 288 x 432 pt is exactly 4 x 6 in."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    out = BytesIO()
    c = canvas.Canvas(out, pagesize=(width_pt, height_pt))
    c.drawString(20, height_pt - 40, f"{text} (TEST LABEL, NO POSTAGE)")
    c.showPage()
    c.save()
    return out.getvalue()


@dataclass
class FakeShopifyShipping:
    """Shopify Shipping's label purchase as the Admin API behaves (2026-10): asynchronous, no
    idempotency (each mutation buys again), a result to poll, and documents behind links. It
    can misbehave like the real thing: lose the reply after buying, stay pending, fail the
    purchase, refuse with userErrors, or never be reached. Every label it sells is counted."""

    shopify: FakeShopify
    purchases: list[dict] = field(default_factory=list)  # every mutation that arrived
    labels_bought: int = 0  # labels Shopify would bill for
    not_sent: int = 0  # raise ShopifyNotSent this many times (never reached Shopify)
    user_errors: list[dict] | None = None  # the next mutation answers with these
    lose_reply: bool = False  # buy, then the answer is lost (no result id)
    no_result_id: bool = False  # buy, then answer without a result id (and no userErrors)
    tracking_late: int = 0  # reads of a bought label that show no tracking number yet
    pending_polls: int = 0  # polls answered PENDING_PURCHASE before the end
    outcome: str = "PURCHASED"  # or "PURCHASE_FAILED"
    fail_errors: list[dict] = field(
        default_factory=lambda: [{"code": "CARRIER_NOT_AVAILABLE", "message": "Not available"}]
    )
    creates_fulfillment: bool = True  # Shopify marks the order fulfilled with the tracking
    reads_fail: int = 0  # label_purchase() raises this many times
    downloads_fail: int = 0
    label_file: bytes = field(default_factory=label_pdf)
    customs_file: bytes | None = None
    file_format: str = "PDF"
    downloads: list[str] = field(default_factory=list)
    _results: dict[str, dict] = field(default_factory=dict)
    _n: itertools.count = field(default_factory=lambda: itertools.count(9001))

    def purchase_label(self, purchase: dict) -> dict:
        from shipping.shopify import ShopifyNotSent

        if self.not_sent:
            self.not_sent -= 1
            raise ShopifyNotSent("Shopify could not be reached: connection refused")
        self.purchases.append(copy.deepcopy(purchase))
        if self.user_errors is not None:
            errors, self.user_errors = self.user_errors, None
            return {"shippingLabelPurchaseResult": None, "userErrors": errors}
        snap = self.shopify.fos.get(purchase["fulfillmentOrderId"])
        if snap is None or not snap.open:
            return {
                "shippingLabelPurchaseResult": None,
                "userErrors": [{"code": "FULFILLMENT_ORDER_INVALID", "message": "Not eligible"}],
            }
        n = next(self._n)
        rid = f"gid://shopify/ShippingLabelPurchaseResult/{n}"
        self._results[rid] = {
            "n": n,
            "fo": snap.id,
            "status": "PENDING_PURCHASE",
            "polls_left": self.pending_polls,
            "errors": [],
            "labels": [],
        }
        if self.pending_polls == 0 or self.lose_reply:
            self._finish(rid)
        if self.lose_reply:
            self.lose_reply = False
            raise ShopifyError("connection reset after sending")
        if self.no_result_id:
            self.no_result_id = False
            return {"shippingLabelPurchaseResult": None, "userErrors": []}
        return {
            "shippingLabelPurchaseResult": {"id": rid, "status": "PENDING_PURCHASE", "done": False},
            "userErrors": [],
        }

    def _finish(self, rid: str) -> None:
        r = self._results[rid]
        if self.outcome != "PURCHASED":
            r.update(status="PURCHASE_FAILED", errors=list(self.fail_errors))
            return
        self.labels_bought += 1
        number = f"RM{r['n']}GB"
        docs = [{"documentType": "LABEL", "format": self.file_format,
                 "url": f"https://shipping.shopify.test/labels/{r['n']}.pdf"}]  # fmt: skip
        if self.customs_file is not None:
            docs.append({"documentType": "CUSTOMS_FORM", "format": "PDF",
                         "url": f"https://shipping.shopify.test/customs/{r['n']}.pdf"})  # fmt: skip
        r.update(
            status="PURCHASED",
            labels=[
                {
                    "id": f"gid://shopify/ShippingLabel/{r['n']}",
                    "trackingInfo": {
                        "number": number,
                        "company": "Royal Mail",
                        "url": f"https://www.royalmail.com/track-your-item#/tracking-results/{number}",
                    },
                    "shippingDocuments": docs,
                }
            ],
        )
        if self.creates_fulfillment:
            snap = self.shopify.fos[r["fo"]]
            self.shopify.fulfillments.append(
                {
                    "id": f"gid://shopify/Fulfillment/{r['n']}",
                    "fo": snap.id,
                    "lines": [(ln.id, ln.quantity) for ln in snap.lines],
                    "company": "Royal Mail",
                    "number": number,
                    "url": None,
                    "notify": True,
                    "order_id": snap.order_id,
                    "status": "SUCCESS",
                    "display": "LABEL_PURCHASED",
                    "by": "shopify_shipping",
                }
            )
            snap.tracking_numbers.append(number)
            snap.status = "CLOSED"

    def label_purchase(self, result_id: str) -> dict | None:
        if self.reads_fail:
            self.reads_fail -= 1
            raise ShopifyError("Shopify could not be reached")
        r = self._results.get(result_id)
        if r is None:
            return None
        if r["status"] == "PENDING_PURCHASE":
            if r["polls_left"] > 0:
                r["polls_left"] -= 1
            else:
                self._finish(result_id)
        labels = copy.deepcopy(r["labels"]) if r["status"] == "PURCHASED" else []
        if labels and self.tracking_late:
            self.tracking_late -= 1
            labels[0]["trackingInfo"] = None
        return {
            "id": result_id,
            "status": r["status"],
            "done": r["status"] != "PENDING_PURCHASE",
            "errors": r["errors"],
            "shippingLabels": labels,
        }

    def download(self, url: str) -> tuple[str, bytes]:
        if self.downloads_fail:
            self.downloads_fail -= 1
            raise ShopifyError("The label file couldn't be fetched (503).")
        self.downloads.append(url)
        if "/customs/" in url and self.customs_file is not None:
            return "application/pdf", self.customs_file
        return "application/pdf", self.label_file
