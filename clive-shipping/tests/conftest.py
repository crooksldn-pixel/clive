from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shipping.models import Address, CustomsLine, PackagePlan, Shipment, ShipmentStatus
from shipping.money import Money
from shipping.providers.fake import FakeProvider
from shipping.purchase import Purchases
from shipping.store import Store

SHOP = "crooks-test.myshopify.com"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(str(tmp_path / "s.sqlite3"))


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def purchases(store, provider, clock) -> Purchases:
    return Purchases(store, provider, clock=clock)


def make_shipment(
    store: Store,
    provider: FakeProvider,
    *,
    shop: str = SHOP,
    sid: str = "shp_1",
    fo: str = "gid://shopify/FulfillmentOrder/1",
    status: ShipmentStatus = ShipmentStatus.ready,
) -> Shipment:
    s = Shipment(
        id=sid,
        shop=shop,
        order_id="gid://shopify/Order/2145",
        order_name="CROOKS-2145",
        fulfillment_order_id=fo,
        destination=Address(
            name="Max Muster",
            line1="Torstrasse 12",
            city="Berlin",
            postcode="10115",
            country="DE",
            phone="+4915112345678",
        ),
        status=status,
        lines=[
            CustomsLine(
                fulfillment_order_line_item_id="gid://shopify/FulfillmentOrderLineItem/1",
                variant_id="gid://shopify/ProductVariant/11",
                title="Express Tee",
                customs_description="Men's cotton T-shirt",
                quantity=2,
                unit_value=Money(minor=3700),
                unit_weight_g=220,
                hs_code="610910",
                origin_country="PT",
            ),
        ],
        package=PackagePlan(
            name="Standard CROOKS parcel",
            length_mm=380,
            width_mm=280,
            height_mm=80,
            empty_weight_g=40,
            items_weight_g=440,
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    s.quote = provider.quotes(s)[0]
    store.save(s)
    return s
