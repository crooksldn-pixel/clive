"""A stand-in Shopify: fulfillment orders, InventoryItem customs facts, fulfillments. Records
every write so tests can say exactly what Shopify would have been told."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

from shipping.models import Address
from shipping.money import Money
from shipping.shopify import FoLine, FoSnapshot, ItemFacts, ShopifyError, ShopifyRefused

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


def fo(n: int, lines: list[FoLine], country: str = "DE", name: str | None = None) -> FoSnapshot:
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
        snap.tracking_numbers.append(number)
        snap.status = "CLOSED"
        if self.fulfillment_reply_lost:
            self.fulfillment_reply_lost = False
            raise ShopifyError("connection reset after sending")
        return fid
