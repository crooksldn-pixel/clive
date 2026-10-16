"""A stand-in Shopify and Click & Drop for local work and the tests. Same interface as the real
clients; it records every call so a test can say exactly what would have been sent."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

from returns.labels import Label, LabelError
from returns.models import Order, OrderLine, OrderMoney, Return, Transaction, Variant
from returns.shopify import ShopifyRefused, ShopifyUncertain, return_input

_ids = itertools.count(1000)


def gid(kind: str) -> str:
    return f"gid://shopify/{kind}/{next(_ids)}"


def _sizes(product: str, sizes: list[str], price: int, out_of_stock: set[str] = frozenset()):
    return [
        Variant(
            id=f"gid://shopify/ProductVariant/{product}-{s}",
            title=s,
            sku=f"{product.upper()}-{s}",
            price_pence=price,
            available=s not in out_of_stock,
            options={"Size": s},
        )
        for s in sizes
    ]


def sample_orders(now: datetime | None = None) -> list[Order]:
    now = now or datetime.now(UTC)
    tee = _sizes("tee", ["S", "M", "L", "XL"], 2500, out_of_stock={"XL"})
    jeans = _sizes("jeans", ["30", "32", "34"], 6000)
    recent = Order(
        id="gid://shopify/Order/1939",
        name="#1939",
        created_at=now - timedelta(days=8),
        email="customer@example.com",
        phone="+447700900123",
        customer_id="gid://shopify/Customer/77",
        customer_name="Sam Taylor",
        customer_email="customer@example.com",
        shipping_zip="E1 6AN",
        billing_zip="E1 6AN",
        shipping_pence=395,
        shipping_address={
            "firstName": "Sam",
            "lastName": "Taylor",
            "address1": "1 Brick Lane",
            "city": "London",
            "zip": "E1 6AN",
            "countryCodeV2": "GB",
        },
        fulfilled_at=now - timedelta(days=7),
        delivered_at=now - timedelta(days=5),
        lines=[
            OrderLine(
                fulfillment_line_item_id="gid://shopify/FulfillmentLineItem/1",
                line_item_id="gid://shopify/LineItem/1",
                title="Docket Tee",
                variant_title="M",
                sku="TEE-M",
                variant_id=tee[1].id,
                variant_price_pence=2500,
                product_id="gid://shopify/Product/tee",
                ordered_qty=1,
                returnable_qty=1,
                unit_paid_pence=2500,
                siblings=tee,
                options={"Size": "M"},
                size_option="Size",
                sizes=["S", "M", "L", "XL"],
                size_chart=[
                    {"size": "S", "chest": "105.4cm", "length": "69.8cm", "shoulder": "52.1cm"},
                    {"size": "M", "chest": "110.5cm", "length": "72.4cm", "shoulder": "54.6cm"},
                    {"size": "L", "chest": "115.6cm", "length": "74.9cm", "shoulder": "57.1cm"},
                    {"size": "XL", "chest": "119.4cm", "length": "76.2cm", "shoulder": "59.7cm"},
                ],
            ),
            OrderLine(
                fulfillment_line_item_id="gid://shopify/FulfillmentLineItem/2",
                line_item_id="gid://shopify/LineItem/2",
                title="Yard Jeans",
                variant_title="32",
                sku="JEANS-32",
                variant_id=jeans[1].id,
                variant_price_pence=6000,
                product_id="gid://shopify/Product/jeans",
                ordered_qty=1,
                returnable_qty=1,
                unit_paid_pence=6000,
                siblings=jeans,
                options={"Size": "32"},
                size_option="Size",
                sizes=["30", "32", "34"],
                size_chart=[
                    {"size": "30", "waist": "76.2cm", "inseam": "78.7cm", "leg opening": "45.7cm"},
                    {"size": "32", "waist": "81.3cm", "inseam": "80.0cm", "leg opening": "48.3cm"},
                    {"size": "34", "waist": "86.4cm", "inseam": "81.3cm", "leg opening": "50.8cm"},
                ],
            ),
        ],
    )
    old = recent.model_copy(
        deep=True,
        update={
            "id": "gid://shopify/Order/1800",
            "name": "#1800",
            "fulfilled_at": now - timedelta(days=22),
            "delivered_at": now - timedelta(days=20),
        },
    )
    guest = recent.model_copy(
        deep=True,
        update={
            "id": "gid://shopify/Order/1950",
            "name": "#1950",
            "customer_id": None,
            "delivered_at": None,
            "fulfilled_at": now - timedelta(days=2),
        },
    )
    return [recent, old, guest]


class FakeShopify:
    def __init__(self, orders: list[Order] | None = None) -> None:
        self.orders = {o.id: o for o in (orders or sample_orders())}
        self.calls: list[tuple[str, Any]] = []
        self.returns: dict[str, dict[str, Any]] = {}
        self.fail: set[str] = set()
        # Done at Shopify, but the answer never arrives (a dropped connection, a 502).
        self.lose_reply: set[str] = set()
        self.holds: list[str] = []

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise ShopifyRefused(f"{name} refused (test)")

    def _maybe_lose(self, name: str) -> None:
        if name in self.lose_reply:
            self.lose_reply.discard(name)
            raise ShopifyUncertain(f"{name}: no answer (test)")

    def find_orders(self, digits: str) -> list[Order]:
        return [o for o in self.orders.values() if o.name.lstrip("#") == digits]

    def get_order(self, order_id: str) -> Order | None:
        found = self.orders.get(order_id)
        return found.model_copy(deep=True) if found else None

    def order_money(self, order_id: str) -> OrderMoney:
        o = self.orders[order_id]
        total = sum(ln.unit_paid_pence * ln.ordered_qty for ln in o.lines) + o.shipping_pence
        return OrderMoney(
            transactions=[
                Transaction(
                    id="gid://shopify/OrderTransaction/9",
                    kind="SALE",
                    status="SUCCESS",
                    amount_pence=total,
                )
            ],
            shipping_pence=o.shipping_pence,
        )

    def reason_ids(self) -> dict[str, str]:
        return {
            "too_small": "gid://shopify/ReturnReasonDefinition/1",
            "too_big": "gid://shopify/ReturnReasonDefinition/2",
        }

    def create_return(self, ret: Return, reason_ids: dict[str, str]) -> dict[str, Any]:
        self._maybe_fail("create_return")
        payload = return_input(ret, reason_ids)
        self.calls.append(("returnCreate", payload))
        rid = gid("Return")
        rfo = gid("ReverseFulfillmentOrder")
        created = {
            "return_id": rid,
            "return_name": f"{ret.order_name}-R1",
            "reverse_fulfillment_order_ids": [rfo],
            "return_line_item_ids": {
                ln.fulfillment_line_item_id: gid("ReturnLineItem") for ln in ret.lines
            },
            "rfo_line_item_ids": {
                ln.fulfillment_line_item_id: gid("ReverseFulfillmentOrderLineItem")
                for ln in ret.lines
            },
            "exchange_line_item_ids": [
                gid("ExchangeLineItem")
                for ln in ret.lines
                if ln.exchange_variant_id
                for _ in range(ln.quantity)
            ],
        }
        self.returns[rid] = {
            "id": rid,
            "status": "OPEN",
            "order_id": ret.order_id,
            "created": created,
            "createdAt": "2099-01-01T00:00:00Z",
            "reverseFulfillmentOrders": {
                "nodes": [{"id": rfo, "reverseDeliveries": {"nodes": []}}]
            },
            "refunds": {"nodes": []},
            "exchangeLineItems": {
                "nodes": [
                    {"id": e, "lineItems": [{"id": f"line-{e}"}]}
                    for e in created["exchange_line_item_ids"]
                ]
            },
        }
        for ln in ret.lines:
            for o_line in self.orders[ret.order_id].lines:
                if o_line.fulfillment_line_item_id == ln.fulfillment_line_item_id:
                    o_line.returnable_qty -= ln.quantity
        self._maybe_lose("create_return")
        return created

    def attach_shipping(self, rfo_id, tracking, tracking_url, label_url, notify) -> str:
        self._maybe_fail("attach_shipping")
        self.calls.append(
            (
                "reverseDeliveryCreateWithShipping",
                {"rfo": rfo_id, "tracking": tracking, "label": label_url, "notify": notify},
            )
        )
        delivery = gid("ReverseDelivery")
        for node in self.returns.values():
            for rfo in node.get("reverseFulfillmentOrders", {}).get("nodes", []):
                if rfo["id"] == rfo_id:
                    rfo["reverseDeliveries"]["nodes"].append({"id": delivery})
        self._maybe_lose("attach_shipping")
        return delivery

    def process_return(self, payload: dict[str, Any], key: str) -> str:
        self._maybe_fail("process_return")
        self.calls.append(("returnProcess", {"input": payload, "key": key}))
        node = self.returns[payload["returnId"]]
        node["status"] = "CLOSED"
        if payload.get("financialTransfer"):
            node["refunds"]["nodes"].append({"id": gid("Refund")})
        return "CLOSED"

    def credit(self, customer_id: str, pence: int, currency: str, key: str) -> str:
        self._maybe_fail("credit")
        self.calls.append(
            ("storeCreditAccountCredit", {"id": customer_id, "pence": pence, "key": key})
        )
        return gid("StoreCreditAccountCreditTransaction")

    def read_return(self, return_id: str) -> dict[str, Any]:
        return self.returns[return_id]

    def order_returns(self, order_id: str) -> list[dict[str, Any]]:
        self.calls.append(("orderReturns", {"id": order_id}))
        return [
            {**n["created"], "status": n["status"], "created_at": n["createdAt"]}
            for n in self.returns.values()
            if n.get("order_id") == order_id
        ]

    def app_scopes(self) -> list[str]:
        from returns.shopify import REQUIRED_SCOPES

        return list(REQUIRED_SCOPES)

    def exchange_holds(self, order_id: str, line_item_ids: list[str]) -> list[str]:
        return list(self.holds)

    def cancel_return(self, return_id: str) -> str:
        self.calls.append(("returnCancel", {"id": return_id}))
        self.returns[return_id]["status"] = "CANCELED"
        return "CANCELED"

    def staff_member(self, id_token: str) -> str | None:
        return "Sam Staff"

    def called(self, name: str) -> list[Any]:
        return [args for n, args in self.calls if n == name]


class FakeLabels:
    """Test labels. With drop_off, it offers drop-off networks with their nearest shops and
    gives a QR code, as Parcel2Go does. lose_next: the next purchase happens but its answer is
    lost (the retry settles it)."""

    name = "Test labels"

    def __init__(self, ok: bool = True, drop_off: bool = False) -> None:
        self.ok = ok
        self.drop_off = drop_off
        self.lose_next = False
        self.made: list[str] = []
        if drop_off:
            self.options = self._options

    def _options(
        self, postcode: str, value_pence: int = 2500, with_shops: bool = True
    ) -> list[Any]:
        from returns.parcel2go import DropOption, DropShop

        def shops(kind: str) -> list[DropShop]:
            return [
                DropShop(
                    name=f"{kind} {n}",
                    address=f"{n} High Street, London",
                    postcode=postcode,
                    distance_m=250 * n,
                    hours="Mon–Sat 8am–9pm",
                )
                for n in (1, 2, 3)
            ]

        return [
            DropOption(
                courier="evri",
                courier_name="Evri",
                service="evri-parcelshop-dropoff",
                service_name="Evri ParcelShop drop-off",
                price_pence=299,
                price_ex_vat_pence=249,
                printer=False,
                locker=False,
                drop_off_code=None,
                print_in_store=True,
                shops=shops("Evri ParcelShop") if with_shops else [],
            ),
            DropOption(
                courier="inpost",
                courier_name="InPost",
                service="inpost-locker",
                service_name="InPost Locker",
                price_pence=275,
                price_ex_vat_pence=229,
                printer=False,
                locker=True,
                drop_off_code=None,
                print_in_store=False,
                shops=shops("InPost Locker") if with_shops else [],
            ),
        ]

    def _label(self, ret: Return, ref: str) -> Label:
        if not self.drop_off:
            return Label(tracking=f"RT{int(ref):09d}GB", pdf=b"%PDF-1.4 fake label", ref=ref)
        from returns.parcel2go import qr_png

        code = f"CRK{int(ref):06d}"
        return Label(
            tracking=f"RT{int(ref):09d}GB",
            pdf=b"%PDF-1.4 fake label",
            ref=ref,
            carrier="Evri" if ret.postage.service != "inpost" else "InPost",
            qr_png=qr_png(code),
            drop_off_code=code,
            service=ret.postage.service,
            service_name=ret.postage.service_name,
            price_pence=299,
        )

    def available(self) -> tuple[bool, str]:
        return (True, "") if self.ok else (False, "Click & Drop is not connected (test).")

    def create(self, ret: Return, address: dict[str, Any], record=None) -> Label:
        if not self.ok:
            raise LabelError(self.available()[1])
        if ret.postage.label_ref:
            # Like Parcel2Go: an order from an earlier try is settled, never bought again.
            return self._label(ret, ret.postage.label_ref)
        self.made.append(ret.id)
        if self.lose_next:
            self.lose_next = False
            raise LabelError("No answer from the label service (test).", ref=str(len(self.made)))
        return self._label(ret, str(len(self.made)))
