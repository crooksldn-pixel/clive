"""Run CLIVE Shipping locally for browser checks (Playwright), with no Shopify and no secrets.

    cd clive-shipping && python scripts/dev_server.py [PORT]            # default 8120
    python scripts/dev_server.py 8120 --empty                           # nothing waiting
    python scripts/dev_server.py 8120 --sandbox                         # real Parcel2Go SANDBOX

    http://127.0.0.1:8120/admin      the embedded admin (admin auth skipped)

The store is a fixture (FakeShopify). Seeded so every screen state exists: ready orders, a
first-time product with three details needed, an address without a postcode, a destination
no courier serves, a provider outage, a fulfilled paperless label, a paper-customs label, a
label whose Shopify update failed, and a purchase awaiting reconciliation.

With --sandbox, labels are bought from the Parcel2Go SANDBOX (fake money) using
SHIPPING_P2G_CLIENT_ID / SHIPPING_P2G_CLIENT_SECRET; it refuses any other Parcel2Go host.
Shopify stays the fixture: no real store is touched.

Dev-only controls (never part of the app): POST /dev/order/{n}/quantity?value=3,
POST /dev/provider/outage?on=1, POST /dev/shopify/refuse?times=1.

App Bridge and Polaris load from cdn.shopify.com; outside Shopify admin App Bridge has no host
to talk to, so expect "App Bridge Next: missing required configuration fields: shop".
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("SHIPPING_ENV_FILE", "")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from shipping import packages  # noqa: E402
from shipping.app import create_app  # noqa: E402
from shipping.fake_shopify import FakeShopify, fo, hoodie_line, tee_line  # noqa: E402
from shipping.models import Address, PageSize  # noqa: E402
from shipping.providers.base import ProviderUnavailable  # noqa: E402
from shipping.providers.fake import FakeProvider  # noqa: E402
from shipping.purchase import Purchases  # noqa: E402
from shipping.service import ShippingService  # noqa: E402
from shipping.settings import Settings  # noqa: E402
from shipping.store import Store  # noqa: E402

SHOP = "crooks-dev.myshopify.com"
TEE = "gid://shopify/Product/tee"

ORIGIN = Address(
    name="CROOKS LDN",
    company="CROOKS LDN",
    line1="Unit M",
    line2="Bourne End Business Park",
    city="Bourne End",
    postcode="SL8 5AS",
    country="GB",
    phone="07700900000",
    email="team@example.com",
)

ADDRESSES = {
    # Like CROOKS-2142: the customer gave Shopify no phone; the store's is booked instead.
    "GG": Address(
        name="Test Recipient",
        line1="1 Test Street",
        city="St Peter Port",
        postcode="GY1 1AA",
        country="GG",
        email="recipient@example.com",
    ),
    "DE": Address(
        name="Max Muster",
        line1="Torstrasse 12",
        city="Berlin",
        postcode="10115",
        country="DE",
        phone="+4915112345678",
        email="max@example.com",
    ),
    "US": Address(
        name="Sam Lee",
        line1="1 Broadway",
        city="New York",
        region="NY",
        postcode="10004",
        country="US",
        phone="+12125550100",
    ),
    "FR": Address(
        name="Camille Martin",
        line1="8 Rue de Rivoli",
        city="Paris",
        postcode="",
        country="FR",
        phone="+33612345678",
    ),
    "JP": Address(
        name="Yuki Tanaka",
        line1="1-1 Jingumae",
        city="Tokyo",
        region="Shibuya",
        postcode="150-0001",
        country="JP",
        phone="+819012345678",
    ),
    "ES": Address(
        name="Lucía García",
        line1="Calle Mayor 5",
        city="Madrid",
        postcode="28013",
        country="ES",
        phone="+34612345678",
    ),
    "IT": Address(
        name="Marco Rossi",
        line1="Via Roma 10",
        city="Milano",
        postcode="20121",
        country="IT",
        phone="+393471234567",
    ),
    "BY": Address(
        name="Ivan Petrov",
        line1="Prospekt Nezavisimosti 1",
        city="Minsk",
        postcode="220030",
        country="BY",
        phone="+375291234567",
    ),
    "CH": Address(
        name="Anna Meier",
        line1="Bahnhofstrasse 1",
        city="Zürich",
        postcode="8001",
        country="CH",
        phone="+41791234567",
    ),
    "NL": Address(
        name="Daan de Vries",
        line1="Damrak 1",
        city="Amsterdam",
        postcode="1012 LG",
        country="NL",
        phone="+31612345678",
    ),
}


def text_pdf(width: int, height: int, lines: list[str], pages: int = 1) -> bytes:
    """A small real PDF (Helvetica text), so the browser shows something like a label."""
    objs: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Count {pages} /Kids [{kids}] >>".encode())
    font = 3 + pages * 2
    for p in range(pages):
        y, ops = height - 40, ["BT /F1 14 Tf"]
        for i, line in enumerate(lines + ([f"Copy {p + 1} of {pages}"] if pages > 1 else [])):
            safe = line.replace("\\", "").replace("(", "").replace(")", "")
            size = 18 if i == 0 else 11
            ops.append(f"/F1 {size} Tf 1 0 0 1 24 {y} Tm ({safe}) Tj")
            y -= 26 if i == 0 else 16
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + p * 2} 0 R >>".encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


class DevProvider(FakeProvider):
    """The fake provider with an outage switch, a destination nobody serves, and label files
    a browser can show."""

    outage: bool = False
    no_service = frozenset({"BY"})

    def quotes(self, shipment):
        if self.outage:
            self.calls.append("quotes")
            raise ProviderUnavailable("Parcel2Go timed out")
        if shipment.destination.country in self.no_service:
            self.calls.append("quotes")
            return []
        return super().quotes(shipment)

    def documents(self, ref):
        docs = super().documents(ref)
        for d in docs.documents:
            if d.body is None:
                continue
            if d.page_size == PageSize.label_4x6:
                d.body = text_pdf(
                    283,
                    425,
                    [
                        "DPD CLASSIC (TEST)",
                        f"Ref {ref}",
                        f"Tracking {docs.tracking_number}",
                        "CROOKS LDN - Bourne End SL8 5AS",
                    ],
                )
            else:
                d.body = text_pdf(
                    595, 842, ["COMMERCIAL INVOICE (TEST)", f"Ref {ref}"], pages=max(d.pages, 1)
                )
        return docs


def order(shopify: FakeShopify, n: int, lines, country: str):
    snap = fo(n, lines)
    snap.destination = ADDRESSES[country]
    return shopify.add(snap)


def seed_settings(store: Store) -> None:
    cfg = store.config(SHOP)
    cfg.origin, cfg.origin_location_id = ORIGIN, "gid://shopify/Location/1"
    packages.add(
        cfg,
        name="Mailer bag",
        length_cm=38,
        width_cm=28,
        height_cm=8,
        empty_weight_g=40,
        actor="dev",
    )
    packages.add(
        cfg,
        name="Hoodie box",
        length_cm=40,
        width_cm=30,
        height_cm=12,
        empty_weight_g=180,
        actor="dev",
    )
    store.save_config(cfg)
    for fact, value in (
        ("hs_code", "6109100010"),
        ("origin_country", "PT"),
        ("customs_description", "Men's cotton T-shirt"),
        ("product_type", "T-Shirt"),
    ):
        store.put_fact(
            SHOP,
            "product",
            TEE,
            fact,
            value,
            source="merchant",
            actor="dev",
            label="Express Tee",
            shopify_written=True,
        )


def by_order(svc: ShippingService, n: int):
    return next(s for s in svc.store.shipments(SHOP) if s.order_name == f"CROOKS-{n}")


def buy(svc: ShippingService, n: int, key: str) -> None:
    s = by_order(svc, n)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "dev", key)


def seed_states(svc: ShippingService, shopify: FakeShopify, provider: DevProvider) -> None:
    order(shopify, 2145, [tee_line(qty=2)], "DE")
    order(shopify, 2146, [hoodie_line()], "US")
    order(shopify, 2147, [tee_line()], "FR")
    order(shopify, 2148, [tee_line()], "JP")
    order(shopify, 2149, [tee_line()], "US")
    order(shopify, 2150, [tee_line()], "ES")
    order(shopify, 2151, [tee_line()], "IT")
    order(shopify, 2152, [tee_line()], "BY")
    order(shopify, 2154, [tee_line(qty=1)], "NL")
    order(shopify, 2142, [tee_line(qty=1)], "GG")
    svc.sync(SHOP)
    buy(svc, 2148, "seed-2148")  # fulfilled, paperless
    s = by_order(svc, 2149)  # Evri: paper customs
    svc.choose_service(SHOP, s.id, "myhermes-international-parcelshop", "dev")
    provider.customs = "paper"
    buy(svc, 2149, "seed-2149")
    provider.customs = "electronic"
    shopify.refuse_fulfillment = 1  # Shopify refuses: label bought, update needs retry
    buy(svc, 2150, "seed-2150")
    provider.lose_pay_reply, provider.read_down = True, 10_000  # outcome unknown
    buy(svc, 2151, "seed-2151")
    provider.read_down = 0
    order(shopify, 2153, [tee_line()], "CH")
    svc.sync(SHOP)
    provider.outage = True  # its prices were asked for during an outage
    svc.prepare(SHOP, by_order(svc, 2153).id)
    provider.outage = False


def build(port: int, empty: bool = False, sandbox: bool = False) -> FastAPI:
    db = Path(tempfile.mkdtemp(prefix="shipping-dev-")) / "dev.sqlite3"
    settings = Settings(
        shop_domain=SHOP,
        shopify_backend="fake",
        provider="parcel2go" if sandbox else "fake",
        dev_skip_admin_auth=True,
        db_path=str(db),
        tick_interval_s=0,
        p2g_base_url=os.environ.get("SHIPPING_P2G_BASE_URL", "https://sandbox.parcel2go.com"),
        p2g_client_id=os.environ.get("SHIPPING_P2G_CLIENT_ID", ""),
        p2g_client_secret=os.environ.get("SHIPPING_P2G_CLIENT_SECRET", ""),
    )
    store = Store(settings.db_path)
    shopify = FakeShopify()
    provider: DevProvider | object
    if sandbox:
        if settings.p2g_environment != "sandbox":
            sys.exit("--sandbox only talks to the Parcel2Go sandbox.")
        from shipping.providers.parcel2go import Parcel2Go

        provider = Parcel2Go(
            settings.p2g_base_url,
            settings.p2g_client_id,
            settings.p2g_client_secret,
            config=store.config,
            cache=store,
        )
    else:
        provider = DevProvider()
    svc = ShippingService(store, shopify, provider, Purchases(store, provider))  # type: ignore[arg-type]
    if not empty:
        seed_settings(store)
        if sandbox:
            order(shopify, 2160, [tee_line(qty=2)], "DE")  # one fresh order for the E2E
            svc.sync(SHOP)
        else:
            assert isinstance(provider, DevProvider)
            seed_states(svc, shopify, provider)
    app = create_app(settings, svc)

    @app.post("/dev/order/{n}/quantity")
    def change_quantity(n: int, value: int) -> dict:
        shopify.fos[f"gid://shopify/FulfillmentOrder/{n}"].lines[0].quantity = value
        return {"ok": True}

    @app.post("/dev/provider/outage")
    def outage(on: int = 1) -> dict:
        if isinstance(provider, DevProvider):
            provider.outage = bool(on)
        return {"ok": True}

    @app.get("/dev/charges")
    def charges() -> dict:
        """How many times the (fake) provider took money, for double-click checks."""
        return {"charges": len(getattr(provider, "charges", []))}

    @app.post("/dev/shopify/refuse")
    def refuse(times: int = 1) -> dict:
        shopify.refuse_fulfillment = times
        return {"ok": True}

    return app


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8120
    app = build(port, empty="--empty" in sys.argv, sandbox="--sandbox" in sys.argv)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
