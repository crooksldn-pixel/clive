from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ["PREORDERS_ENV_FILE"] = ""  # never read a real .env in tests (read at import)

from preorders.app import build_service  # noqa: E402
from preorders.comms import RecordingMailer  # noqa: E402
from preorders.fake import FakeShopify  # noqa: E402
from preorders.settings import Settings  # noqa: E402

SHOP = "crooks-test.myshopify.com"


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> None:
        self.at += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def shopify() -> FakeShopify:
    return FakeShopify()


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        shop_domain=SHOP,
        shopify_client_id="client-id",
        shopify_client_secret="test-secret",
        shopify_backend="graphql",
        selling_plans="shopify",
        db_path=str(tmp_path / "preorders.sqlite3"),
        tick_interval_s=0,
        reconcile_every_min=0,
        clive_read_keys="read-key",
    )


@pytest.fixture
def svc(settings, shopify, mailer, clock):
    s = build_service(settings, shopify=shopify, mailer=mailer)
    s.clock = clock
    return s


@pytest.fixture
def jogger(svc, shopify):
    """Black Jogger: XS 7 in stock, S 0 (30 coming), M 0 (50 coming), L 0 (nothing coming),
    XL 3 in stock. Returns (product id, {size: variant id})."""
    pid = shopify.add_product("Black Jogger", {"XS": 7, "S": 0, "M": 0, "L": 0, "XL": 3})
    svc.refresh_catalog()
    sizes = {s: shopify.variant(pid, s).variant_id for s in ("XS", "S", "M", "L", "XL")}
    return pid, sizes


def open_preorder(
    svc,
    pid,
    sizes,
    *,
    s=30,
    m=50,
    alloc_s=None,
    alloc_m=None,
    discount=0,
    dispatch="2026-11-07",
    arrival="2026-11-04",
):
    batch = svc.create_batch(
        reference="Jogger Batch 2",
        expected_arrival_at=arrival,
        expected_dispatch_at=dispatch,
        lines=[
            {
                "variant_id": sizes["S"],
                "expected_quantity": s,
                "preorder_allocation": s if alloc_s is None else alloc_s,
            },
            {
                "variant_id": sizes["M"],
                "expected_quantity": m,
                "preorder_allocation": m if alloc_m is None else alloc_m,
            },
        ],
        actor="Sam",
    )
    offer = svc.configure_offer(
        product_id=pid,
        batch_id=batch["id"],
        discount_type="PERCENTAGE" if discount else "NONE",
        discount_value=discount,
        actor="Sam",
    )
    svc.activate_offer(offer["id"], "Sam")
    return svc.batch(batch["id"]), svc.offer_view(offer["id"])


def line_of(svc, batch, size_variant):
    return next(x for x in batch["lines"] if x["variant_id"] == size_variant)
