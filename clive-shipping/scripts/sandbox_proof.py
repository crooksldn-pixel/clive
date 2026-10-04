"""Stage 3 proof against the real Parcel2Go SANDBOX (test money only).

    SHIPPING_P2G_BASE_URL=https://sandbox.parcel2go.com SHIPPING_P2G_CLIENT_ID=... \
    SHIPPING_P2G_CLIENT_SECRET=... python scripts/sandbox_proof.py OUT_DIR

Each numbered step prints evidence and stops the run if it doesn't hold. Every request reaches
Parcel2Go for real; faults are injected only in the replies (an httpx response hook), which is
exactly what a lost reply is. Request counts per endpoint prove what was and wasn't called.
Refuses to run against anything but the sandbox. Saves every document to OUT_DIR.
"""

from __future__ import annotations

import collections
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shipping.documents import print_plan  # noqa: E402
from shipping.models import (  # noqa: E402
    Address,
    CustomsLine,
    CustomsMode,
    DocumentKind,
    PackagePlan,
    PageSize,
    Shipment,
    ShipmentStatus,
    ShopConfig,
)
from shipping.money import Money  # noqa: E402
from shipping.providers.base import ProviderRefused  # noqa: E402
from shipping.providers.parcel2go import Parcel2Go, balance  # noqa: E402
from shipping.purchase import ActionError, Purchases, Stale  # noqa: E402
from shipping.store import Store  # noqa: E402

SHOP = "crooks-sandbox.myshopify.com"
ORIGIN = Address(
    name="CROOKS LDN",
    company="CROOKS LDN",
    line1="Unit M",
    line2="Bourne End Business Park",
    city="Bourne End",
    postcode="SL8 5AS",
    country="GB",
    phone="07700900000",
    email="team@crooksldn.com",
)
BERLIN = Address(
    name="Max Muster",
    line1="Torstrasse 12",
    city="Berlin",
    postcode="10115",
    country="DE",
    phone="+4915112345678",
    email="max@example.com",
)
NEW_YORK = Address(
    name="Sam Lee",
    line1="1 Broadway",
    city="New York",
    region="NY",
    postcode="10004",
    country="US",
    phone="+12125550100",
    email="sam@example.com",
)
TENERIFE = Address(
    name="Ana Diaz",
    line1="Calle del Castillo 5",
    city="Santa Cruz de Tenerife",
    postcode="38001",
    country="ES",
    phone="+34600000000",
)


class Wire:
    """Counts requests per endpoint and can lose the next reply to one of them."""

    def __init__(self) -> None:
        self.calls: collections.Counter[str] = collections.Counter()
        self.lose_reply_to: str | None = None

    @staticmethod
    def endpoint(request: httpx.Request) -> str:
        path = request.url.path
        for marker in ("paywithprepay", "parcelnumbers"):
            if marker in path:
                return marker
        if path.startswith("/api/labels/"):
            return "labels:" + request.url.params.get("detailLevel", "")
        return f"{request.method} {path.replace('/api', '')}"

    def on_request(self, request: httpx.Request) -> None:
        self.calls[self.endpoint(request)] += 1

    def on_response(self, response: httpx.Response) -> None:
        if self.lose_reply_to and self.endpoint(response.request) == self.lose_reply_to:
            self.lose_reply_to = None
            response.read()  # Parcel2Go has fully processed it; only the reply goes missing
            raise httpx.ReadTimeout("reply lost (injected)", request=response.request)


def shipment(sid: str, destination: Address) -> Shipment:
    at = datetime.now(UTC)
    return Shipment(
        id=sid,
        shop=SHOP,
        order_id=f"gid://shopify/Order/{sid}",
        order_name=f"PROOF-{sid}",
        fulfillment_order_id=f"gid://shopify/FulfillmentOrder/{sid}",
        destination=destination,
        status=ShipmentStatus.ready,
        lines=[
            CustomsLine(
                fulfillment_order_line_item_id=f"gid://shopify/FulfillmentOrderLineItem/{sid}",
                title="Express Tee",
                customs_description="Men's cotton T-shirt",
                quantity=2,
                unit_value=Money(minor=3700),
                unit_weight_g=220,
                hs_code="610910",
                origin_country="PT",
            )
        ],
        package=PackagePlan(
            name="Sandbox mailer",
            length_mm=380,
            width_mm=280,
            height_mm=80,
            empty_weight_g=40,
            items_weight_g=440,
        ),
        created_at=at,
        updated_at=at,
    )


def check(ok: bool, what: str) -> None:
    print(("   ✓ " if ok else "   ✗ ") + what)
    if not ok:
        sys.exit(f"FAILED: {what}")


def main(out_dir: str) -> None:
    base = os.environ["SHIPPING_P2G_BASE_URL"]
    if "sandbox" not in base:
        sys.exit("sandbox_proof only talks to the Parcel2Go sandbox.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wire = Wire()
    http = httpx.Client(
        timeout=httpx.Timeout(60, connect=10),
        event_hooks={"request": [wire.on_request], "response": [wire.on_response]},
    )
    store = Store(str(Path(tempfile.mkdtemp()) / "proof.sqlite3"))
    cfg = ShopConfig(shop=SHOP, origin=ORIGIN)
    store.save_config(cfg)
    p2g = Parcel2Go(
        base,
        os.environ["SHIPPING_P2G_CLIENT_ID"],
        os.environ["SHIPPING_P2G_CLIENT_SECRET"],
        config=store.config,
        http=http,
        cache=store,
    )
    purchases = Purchases(store, p2g)
    evidence: dict = {"orders": []}
    start = balance(p2g)
    print(f"Sandbox PrePay at start: {start}")

    def pick(s: Shipment, slug_prefix: str):
        q = next((q for q in p2g.quotes(s) if q.service_code.startswith(slug_prefix)), None)
        check(q is not None, f"{slug_prefix} offered to {s.destination.country}")
        return q

    # 1, 2: quotes
    print("\n1. Quote Germany")
    de = shipment("de1", BERLIN)
    de_quotes = p2g.quotes(de)
    for q in sorted(de_quotes, key=lambda q: q.amount.minor)[:5]:
        print(f"     {q.title:<45} {q.amount}  ~{q.est_days_max}d")
    check(len(de_quotes) > 0, f"{len(de_quotes)} door-delivery quotes to DE")
    print("2. Quote USA")
    us = shipment("us1", NEW_YORK)
    us_quotes = p2g.quotes(us)
    for q in sorted(us_quotes, key=lambda q: q.amount.minor)[:5]:
        print(f"     {q.title:<45} {q.amount}  ~{q.est_days_max}d")
    check(len(us_quotes) > 0, f"{len(us_quotes)} door-delivery quotes to US")
    place = p2g.place("DE", "10115")
    check(
        (place.iso2, place.iso3, place.name) == ("DE", "DEU", "Germany"),
        f"country kept as ISO inside, Parcel2Go's name outside: {place.model_dump()}",
    )

    # 3: an unpaid order on its own (never paid; costs nothing)
    print("3. Create an unpaid provider order")
    de.quote = pick(de, "dpd-classic")
    unpaid = p2g.create_order(de, de.quote, "proof-unpaid")
    seen = p2g.read_order(unpaid.ref)
    check(
        not seen.paid,
        f"order {unpaid.ref.split(':')[1]} exists, unpaid, £{unpaid.amount_minor / 100:.2f}",
    )
    evidence["unpaid_order"] = unpaid.ref.split(":")[1]

    # 4: exact price, as approved
    print("4. Preview the exact approved price")
    store.save(de)
    pv = purchases.preview(SHOP, de.id)
    check(pv["money"]["shipping_minor"] > 0, f"exact price {pv['will'][0]}")

    # 13 first half and 12: buy with the payment reply lost
    print("5/6/12. Pay once, with the payment reply lost; reconcile by PaidDate")
    before = balance(p2g)
    wire.lose_reply_to = "paywithprepay"
    result = purchases.buy(SHOP, de.id, pv["basis"], "proof", "proof-de-1")
    op = store.op_by_key(SHOP, "proof-de-1")
    after = balance(p2g)
    check(wire.calls["paywithprepay"] == 1, "pay was called exactly once")
    check(result["charged"] and result["status"] == "label_purchased", "outcome: paid (read back)")
    check(
        before is not None
        and after is not None
        and before.minor - after.minor == pv["money"]["shipping_minor"],
        f"PrePay fell by exactly one price: {before} -> {after}",
    )
    evidence["orders"].append(
        {"case": "DE DPD, reply lost", "order": op.provider_ref.split(":")[1]}
    )

    print("13. Double click")
    replay = purchases.buy(SHOP, de.id, pv["basis"], "proof", "proof-de-1")
    check(replay["replayed"] and replay["operation"] == result["operation"], "same key replays")
    try:
        purchases.buy(SHOP, de.id, pv["basis"], "proof", "proof-de-2")
        check(False, "a new key was refused")
    except ActionError as exc:
        check(True, f"a second click with a new key is refused: {exc}")
    check(wire.calls["paywithprepay"] == 1 and balance(p2g) == after, "still one charge")

    # 7, 8, 9, 11: documents for a paperless service
    print("7/8/9/11. Documents: genuine 4x6, paperless customs, identifiers")
    s = store.get(SHOP, de.id)
    label = s.label.document(DocumentKind.shipping_label)
    check(label.page_size == PageSize.label_4x6 and label.pages == 1, "label is one 4x6 page")
    check(s.label.customs == CustomsMode.electronic, "DPD: customs filed electronically")
    plan = print_plan(s.label)
    check(
        plan.ready and plan.extra_documents == 0,
        f"{plan.summary}: {[ln.text for ln in plan.lines]}",
    )
    check(
        bool(s.label.tracking_number),
        f"tracking {s.label.tracking_number}, ids {s.label.provider_ids}",
    )
    for doc in s.label.documents:
        if doc.artifact_id:
            (out / f"de-dpd-{doc.kind.value}.pdf").write_bytes(
                store.get_artifact(SHOP, doc.artifact_id)[2]
            )

    # 15: reprint
    print("15. Reprint never reaches Parcel2Go")
    calls = sum(wire.calls.values())
    money = balance(p2g)
    calls_with_balance = sum(wire.calls.values())
    for _ in range(3):
        purchases.reprint(SHOP, de.id, DocumentKind.shipping_label)
    check(sum(wire.calls.values()) == calls_with_balance, "3 reprints, 0 requests to Parcel2Go")
    check(balance(p2g) == money, f"balance unchanged ({money}); requests before {calls}")

    # 10: paper customs, 3 copies (Evri, DE) and 4 copies (UPS, US)
    for sid, dest, slug, copies in (
        ("de2", BERLIN, "myhermes-international", 3),
        ("us2", NEW_YORK, "ups-access-point", 4),
    ):
        print(f"10. Paper customs: {slug} to {dest.country}")
        ps = shipment(sid, dest)
        ps.quote = pick(ps, slug)
        store.save(ps)
        b = purchases.preview(SHOP, sid)["basis"]
        before = balance(p2g)
        res = purchases.buy(SHOP, sid, b, "proof", f"proof-{sid}")
        ps = store.get(SHOP, sid)
        inv = ps.label.document(DocumentKind.commercial_invoice)
        check(res["charged"] and ps.label.customs == CustomsMode.paper, "customs on paper")
        check(
            inv is not None
            and inv.must_print
            and inv.copies_required == copies
            and inv.page_size == PageSize.a4,
            f"commercial invoice: print {inv.copies_required if inv else '?'} copies (A4), attach",
        )
        check(
            before.minor - balance(p2g).minor == ps.label.amount.minor,  # type: ignore[union-attr]
            "charged exactly once",
        )
        plan = print_plan(ps.label)
        print(f"     {plan.summary}: {[ln.text for ln in plan.lines]}")
        for doc in ps.label.documents:
            if doc.artifact_id:
                (out / f"{sid}-{doc.kind.value}.pdf").write_bytes(
                    store.get_artifact(SHOP, doc.artifact_id)[2]
                )
        evidence["orders"].append(
            {"case": f"{dest.country} {slug}", "order": ps.label.provider_ids.get("order")}
        )

    # 14: stale fingerprint
    print("14. Stale fingerprint")
    st = shipment("us3", NEW_YORK)
    st.quote = pick(st, "landmark")
    store.save(st)
    b = purchases.preview(SHOP, "us3")["basis"]
    st = store.get(SHOP, "us3")
    st.destination = st.destination.model_copy(update={"postcode": "10005"})
    store.save(st)
    orders_before = wire.calls["POST /orders"]
    try:
        purchases.buy(SHOP, "us3", b, "proof", "proof-us3")
        check(False, "stale buy refused")
    except Stale as exc:
        check(True, f"refused: {exc}")
    check(wire.calls["POST /orders"] == orders_before, "nothing was sent to Parcel2Go")

    # 16: a real provider 4xx, as an actionable state
    print("16. A real Parcel2Go refusal (Canaries without the recipient's DNI)")
    ca = shipment("es1", TENERIFE)
    try:
        ca.quote = next(iter(sorted(p2g.quotes(ca), key=lambda q: q.amount.minor)))
        store.save(ca)
        purchases.preview(SHOP, "es1")
        check(False, "refused")
    except ActionError as exc:
        check(exc.status == 422, f"422, staff see: {exc}")
    except ProviderRefused as exc:
        check(True, f"refused at quote: {exc}")

    end = balance(p2g)
    print(f"\nSandbox PrePay: {start} -> {end}")
    print("Requests per endpoint:", dict(sorted(wire.calls.items())))
    evidence.update(
        start=str(start), end=str(end), calls=dict(wire.calls), at=datetime.now(UTC).isoformat()
    )
    (out / "evidence.json").write_text(json.dumps(evidence, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sandbox-proof")
