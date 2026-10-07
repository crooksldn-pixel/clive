"""Parcel2Go labels, end to end against a stand-in Parcel2Go that answers with the shapes the
sandbox returned on 2026-10-03."""

import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from returns.app import create_app
from returns.models import Postage, Reason, Resolution, Selection, Status
from returns.parcel2go import Parcel2Go
from returns.service import ReturnsService
from returns.store import Store

from .conftest import RecordingNotifier

TEE = "gid://shopify/FulfillmentLineItem/1"


class Stopped(BaseException):
    """The process stopped mid-request (a deploy, a crash): nothing after this line runs."""


def quote(slug, courier, collection, price, printer=True, extras=(), code="", size=None):
    size = size or {"MaxLength": 1.2, "MaxWidth": None, "MaxHeight": None}
    return {
        "AvailableExtras": [{"Type": t, "Price": 0.0, "Vat": 0.0, "Total": 0.0} for t in extras],
        "Service": {
            "DropOffProviderCode": code,
            "CourierName": courier.title(),
            "CourierSlug": courier,
            "Slug": slug,
            "Name": slug.replace("-", " ").title(),
            "CollectionType": collection,
            "DeliveryType": "Door",
            "IsPrinterRequired": printer,
            "MaxWeight": 15.0,
            **size,
        },
        "TotalPrice": price,
        "TotalPriceExVat": round(price / 1.2, 2),
    }


class FakeParcel2Go:
    def __init__(self):
        self.orders: list[dict] = []
        self.paid: list[str] = []
        self.fail_documents = False
        self.balance = 50.0
        # Like the real API: paying an already-paid order charges again.
        self.lose_pay_response = False
        self.refuse_pay = False
        # Live Parcel2Go can take a while to release a paid label: GET /orders answers with
        # no links and no in-store code this many times.
        self.unreleased_reads = 0
        self.order_reads = 0
        self.label_answers_html = False
        # Every paywithprepay that reached Parcel2Go, answered or not.
        self.pay_calls = 0
        # The reply is lost and the payment is still going through: the order reads unpaid
        # until land() (or forever, if it never lands).
        self.pay_lands_late = False
        self.landing: list[str] = []
        # Parcel2Go takes the money, then this process stops before hearing back.
        self.stop_after_paying = False

    def land(self) -> None:
        self.paid += self.landing
        self.landing = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/auth/connect/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        assert request.headers.get("authorization") == "Bearer tok" or path.startswith("/label/")
        if path == "/api/quotes":
            return httpx.Response(
                200,
                json={
                    "Quotes": [
                        quote("hermes-uk-economy", "hermes", "Collection", 3.11),
                        quote("inpost", "inpost", "Shop", 3.59, code="INPOST"),
                        quote(
                            "myhermes-parcelshop",
                            "myhermes",
                            "Shop",
                            2.39,
                            extras=("PrintInStore", "Sms"),
                            code="MYHRMS",
                        ),
                        quote(
                            "myhermes-parcelshop-small",
                            "myhermes",
                            "Shop",
                            2.19,
                            extras=("PrintInStore",),
                            code="MYHRMS",
                            size={"MaxLength": 0.30, "MaxWidth": 0.20, "MaxHeight": 0.05},
                        ),
                        quote("dpd", "dpd", "Shop", 6.83, code="DPD"),
                    ]
                },
            )
        if path.startswith("/api/dropshops/"):
            shop = {
                "Name": "Tesco Express",
                "Address1": "116 Commercial Street",
                "Postcode": "E1 6NF",
            }
            return httpx.Response(
                200,
                json={
                    "Results": [
                        {**shop, "Distance": 306, "ConcatenatedTimes": ": "},
                        {**shop, "Distance": 306, "ConcatenatedTimes": ": "},
                        {
                            "Name": "Best One",
                            "Address1": "20 Brick Lane",
                            "Postcode": "E1 6RF",
                            "Distance": 504,
                            "ConcatenatedTimes": "Mon-Sat: 09:00 - 20:00<br/>Sun: 10:00 - 20:00",
                        },
                    ]
                },
            )
        if path == "/api/orders" and method == "POST":
            self.orders.append(json.loads(request.content))
            n = 26632 + len(self.orders)
            return httpx.Response(
                200,
                json={
                    "OrderId": str(n),
                    "TotalPrice": 2.39,
                    "Hash": "h+/=",
                    "OrderlineIdMap": [{"OrderLineId": str(45692 + len(self.orders))}],
                },
            )
        if path.endswith("/paywithprepay"):
            self.pay_calls += 1
            if self.pay_lands_late:
                self.landing.append(path.split("/")[3])
                raise httpx.ReadTimeout("no answer yet", request=request)
            if self.stop_after_paying:
                self.paid.append(path.split("/")[3])
                raise Stopped()
            if self.refuse_pay:
                return httpx.Response(
                    400, json={"Errors": [{"Name": "Balance", "Description": "Not enough"}]}
                )
            self.paid.append(path.split("/")[3])
            if self.unreleased_reads:  # paid, but no label links yet
                return httpx.Response(200, json={"Links": []})
            if self.lose_pay_response:  # charged, but the reply never arrives
                raise httpx.ReadTimeout("connection lost", request=request)
            return httpx.Response(
                200,
                json={"Links": [{"Name": "labels-a4", "Link": "https://p2g.test/label/order?x=1"}]},
            )
        if path == "/api/orders" and method == "GET":
            oid = request.url.params.get("orderId")
            self.order_reads += 1
            if self.unreleased_reads:
                self.unreleased_reads -= 1
                return httpx.Response(
                    200,
                    json={
                        "PaidDate": "2026-10-04T10:00:00" if oid in self.paid else None,
                        "TotalPrice": 2.39,
                        "Items": [{"Parcels": [{"Links": {}}]}],
                        "Links": {},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "PaidDate": "2026-10-04T10:00:00" if oid in self.paid else None,
                    "TotalPrice": 2.39,
                    "Items": [
                        {
                            "Parcels": [
                                {
                                    "PrintInStoreBarcode": "EVRI-QR-123",
                                    "PrintInStoreBarcodeFormat": "QRCode",
                                    "Links": {},
                                }
                            ]
                        }
                    ],
                    "Links": {"labels-a4": "https://p2g.test/label/order?x=1"},
                },
            )
        if path.startswith("/label/"):
            if self.fail_documents:
                return httpx.Response(503)
            if self.label_answers_html:
                return httpx.Response(200, content=b"<html>Sign in</html>")
            return httpx.Response(200, content=b"%PDF-1.4 evri label")
        if path.startswith("/api/labels/"):
            return httpx.Response(404, json={})
        if path.endswith("/parcelnumbers"):
            return httpx.Response(200, json={"TrackingNumbers": [{"TrackingNumber": "H01ABC"}]})
        if path == "/api/prepay":
            return httpx.Response(200, json=self.balance)
        return httpx.Response(404, json={"Message": f"no route {method} {path}"})


@pytest.fixture
def p2g_server():
    return FakeParcel2Go()


@pytest.fixture
def p2g(settings, p2g_server):
    settings.p2g_client_id, settings.p2g_client_secret = "id:CrooksReturns", "secret"
    settings.p2g_base_url = "https://p2g.test"
    settings.returns_address_line1 = "Unit M (Oairo UK Offices)"
    settings.returns_address_line2 = "Bourne End Business Park"
    settings.returns_address_city = "Bourne End, Buckinghamshire"
    settings.returns_address_postcode = "SL8 5AS"
    settings.p2g_webhook_secret = "hook-secret"
    return Parcel2Go(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(p2g_server)),
        sleep=lambda seconds: None,
    )


@pytest.fixture
def psvc(settings, shop, p2g, clock):
    return ReturnsService(
        settings, Store(settings.db_path), shop, p2g, RecordingNotifier(settings), clock=clock
    )


def request(svc, courier="evri", resolution=Resolution.store_credit):
    order = svc.shopify.get_order("gid://shopify/Order/1939")
    sel = [Selection(fulfillment_line_item_id=TEE, quantity=1, reason=Reason.changed_mind)]
    return svc.submit(order, sel, resolution, Postage.free_label, {}, courier)


def test_options_are_printer_free_first_and_fit_the_parcel(p2g):
    options = p2g.options("E1 6AN")
    assert [o.courier for o in options] == ["evri", "inpost"]
    evri, inpost = options
    # The small Evri service is cheaper but our 35x25x8cm parcel doesn't fit it.
    assert evri.service == "myhermes-parcelshop" and evri.courier_name == "Evri"
    assert evri.print_in_store and not evri.printer and evri.price_pence == 239
    assert inpost.printer  # no in-store printing offered: the customer prints
    names = [(s.name, s.distance_m, s.hours) for s in evri.shops]
    assert names == [
        ("Tesco Express", 306, ""),
        ("Best One", 504, "Mon-Sat: 09:00 - 20:00; Sun: 10:00 - 20:00"),
    ]


def test_customer_picks_a_drop_off_and_approval_books_it(psvc, p2g_server):
    choices = psvc.drop_off_options(psvc.shopify.get_order("gid://shopify/Order/1939"))
    assert [c["courier"] for c in choices] == ["evri", "inpost"]
    ret = request(psvc)
    assert ret.postage.service == "evri" and ret.postage.shops[0]["name"] == "Tesco Express"

    plan = psvc.preview(ret.id, "approve", {"postage_mode": "label_now"})["will"]
    assert any("Book Evri (Evri Parcelshop) for £2.39" in w and "£50.00" in w for w in plan)
    assert not p2g_server.orders  # a preview buys nothing

    out = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")
    ret = out["return_doc"]
    assert ret.status == Status.awaiting_shipment and not ret.last_error
    sent = p2g_server.orders[0]["Items"][0]
    assert sent["Service"] == "myhermes-parcelshop"
    assert sent["Upsells"] == [{"Type": "PrintInStore"}]
    # From the customer, to us.
    assert sent["CollectionAddress"]["Postcode"] == "E1 6AN"
    assert sent["CollectionAddress"]["Property"] == "1"
    assert sent["CollectionAddress"]["Street"] == "Brick Lane"
    delivery = sent["Parcels"][0]["DeliveryAddress"]
    assert (delivery["Postcode"], delivery["Town"], delivery["County"]) == (
        "SL8 5AS",
        "Bourne End",
        "Buckinghamshire",
    )
    assert ret.postage.label_price_pence == 239 and ret.postage.tracking == "H01ABC"
    assert ret.postage.carrier == "Evri" and ret.postage.drop_off_text == "EVRI-QR-123"
    kind, png = psvc.store.get_file(ret.postage.qr_file_id)
    assert kind == "image/png" and png.startswith(b"\x89PNG")
    bought = next(e for e in ret.timeline if e.type == "label_bought")
    assert bought.detail["cost"] == "£2.39" and bought.detail["ref"] == "26633"

    seen = psvc.public(ret)["drop_off"]
    assert seen["courier"] == "Evri" and seen["code"] == "EVRI-QR-123"
    assert seen["qr_url"].startswith("https://returns.example.com/files/")
    assert seen["shops"][0]["name"] == "Tesco Express"


def test_a_paid_label_is_never_bought_twice(psvc, p2g_server):
    ret = request(psvc)
    p2g_server.fail_documents = True
    ret = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")[
        "return_doc"
    ]
    # The GET /orders code still gives a QR, so make that fail too for this case.
    assert ret.status in (Status.awaiting_shipment, Status.awaiting_label)
    assert len(p2g_server.orders) == 1 and p2g_server.paid == ["26633"]


def test_label_retry_fetches_the_paid_one(psvc, p2g, p2g_server, monkeypatch):
    ret = request(psvc)
    monkeypatch.setattr(p2g, "_fetch", lambda url, kind: None)
    monkeypatch.setattr("returns.parcel2go.qr_png", lambda code, fmt=None: None)
    ret = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")[
        "return_doc"
    ]
    assert ret.status == Status.awaiting_label and "hasn't released" in ret.last_error
    assert ret.postage.label_ref.startswith("p2g:26633:")
    monkeypatch.undo()
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert ret.status == Status.awaiting_shipment and ret.postage.qr_file_id
    assert len(p2g_server.orders) == 1 and p2g_server.paid == ["26633"]


def test_unknown_courier_choice_is_refused(psvc):
    with pytest.raises(Exception, match="drop-off option"):
        request(psvc, courier="dpd")


def test_portal_offers_drop_offs_and_takes_the_choice(psvc):
    c = TestClient(create_app(psvc.s, psvc))
    found = c.post("/proxy/api/lookup", json={"order": "#1939", "proof": "E1 6AN"}).json()
    offer = c.post("/proxy/api/dropoff", json={"session": found["session"]}).json()
    assert offer["postcode"] == "E1 6AN"
    assert [o["courier"] for o in offer["options"]] == ["evri", "inpost"]
    assert "price_pence" not in offer["options"][0]  # our cost isn't the customer's business
    made = c.post(
        "/proxy/api/submit",
        json={
            "session": found["session"],
            "items": [{"fulfillment_line_item_id": TEE, "quantity": 1, "reason": "too_small"}],
            "resolution": "store_credit",
            "postage": "free_label",
            "courier": "inpost",
        },
    ).json()["return"]
    assert psvc.store.get(made["id"]).postage.service == "inpost"


def signed(body, secret="hook-secret"):
    stamp = body["Timestamp"].replace("T", " ")[:19]
    msg = f"{body['Id']}:{stamp}:{body['Type']}"
    return {
        **body,
        "Signature": hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest(),
    }


def test_courier_tracking_moves_the_return(psvc):
    ret = request(psvc)
    ret = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")[
        "return_doc"
    ]
    line = ret.postage.label_ref.split(":")[2]
    c = TestClient(create_app(psvc.s, psvc))

    def hook(stage, hook_id, secret="hook-secret"):
        body = {
            "Id": hook_id,
            "Timestamp": "2026-10-04T10:15:00.123+00:00",
            "Type": "Tracking",
            "Payload": {"OrderLineId": int(line), "TrackingStage": stage, "StatusDescription": "x"},
        }
        return c.post("/webhooks/parcel2go", json=signed(body, secret))

    assert hook("DroppedOff", "a", secret="wrong").status_code == 401
    assert hook("DroppedOff", "a").json()["return"] == ret.id
    assert psvc.store.get(ret.id).status == Status.in_transit
    assert hook("DroppedOff", "a").json()["return"] is None  # replayed: ignored
    hook("Delivered", "b")
    after = psvc.staff(psvc.store.get(ret.id))
    assert after["attention"] == ["delivered_unchecked"]
    assert [e["type"] for e in after["timeline"]][-2:] == ["in_transit", "delivered_to_us"]


def test_a_free_item_is_declared_at_its_shop_price(psvc, shop, p2g_server):
    # Couriers refuse a parcel worth £0 (Parcel2Go: "Please enter a value for your parcel").
    shop.orders["gid://shopify/Order/1939"].lines[0].unit_paid_pence = 0
    order = psvc.shopify.get_order("gid://shopify/Order/1939")
    sel = [Selection(fulfillment_line_item_id=TEE, quantity=1, reason=Reason.faulty)]
    ret = psvc.submit(order, sel, Resolution.refund, Postage.free_label, {}, "evri")
    psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")
    assert p2g_server.orders[0]["Items"][0]["Parcels"][0]["EstimatedValue"] == 25.0


def test_a_lost_payment_reply_never_buys_a_second_label(psvc, p2g_server):
    # The dangerous case: Parcel2Go takes the money, the reply is lost.
    ret = request(psvc)
    p2g_server.lose_pay_response = True
    ret = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")[
        "return_doc"
    ]
    assert ret.status == Status.awaiting_label and "payment not confirmed" in ret.last_error
    assert ret.postage.label_ref.startswith("p2g:26633:")
    p2g_server.lose_pay_response = False
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    # Parcel2Go said it was paid, so it was not paid again and no new order was made.
    assert ret.status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def test_a_refused_payment_is_paid_once_after_topping_up(psvc, p2g_server):
    ret = request(psvc)
    p2g_server.refuse_pay = True
    ret = psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", "k1")[
        "return_doc"
    ]
    assert ret.status == Status.awaiting_label and "Not enough" in ret.last_error
    p2g_server.refuse_pay = False
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert ret.status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def approve(psvc, ret, key="k1"):
    return psvc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "staff", key)[
        "return_doc"
    ]


def test_a_payment_still_going_through_is_never_paid_again(psvc, p2g, p2g_server, clock):
    # The reply to the payment is lost and Parcel2Go hasn't marked the order paid yet. A retry
    # straight away must wait, not pay again: paying a paid order charges twice.
    p2g.clock = clock
    ret = request(psvc)
    p2g_server.pay_lands_late = True
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label and "payment not confirmed" in ret.last_error
    p2g_server.pay_lands_late = False
    clock.now += timedelta(seconds=30)
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert p2g_server.pay_calls == 1  # not paid a second time
    assert ret.status == Status.awaiting_label and "may still be going through" in ret.last_error
    p2g_server.land()  # Parcel2Go finishes taking the first payment
    ret = psvc.execute(ret.id, "label", {}, "staff", "k3")["return_doc"]
    assert ret.status == Status.awaiting_shipment and not ret.postage.pay_sent_at
    assert p2g_server.pay_calls == 1 and p2g_server.paid == ["26633"]
    assert len(p2g_server.orders) == 1


def test_a_payment_that_never_arrived_is_paid_once_two_minutes_on(psvc, p2g, p2g_server, clock):
    p2g.clock = clock
    ret = request(psvc)
    p2g_server.pay_lands_late = True
    ret = approve(psvc, ret)
    p2g_server.pay_lands_late, p2g_server.landing = False, []  # it never reached Parcel2Go
    clock.now += timedelta(minutes=3)
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert ret.status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def test_a_stop_after_paying_never_makes_or_pays_a_second_order(
    psvc, p2g, p2g_server, settings, shop, clock
):
    # Parcel2Go took the money, then the service stopped (a deploy restarts it) before the
    # answer was saved. The order was written down before paying, so the next try settles it.
    ret = request(psvc)
    p2g_server.stop_after_paying = True
    with pytest.raises(Stopped):
        approve(psvc, ret)
    p2g_server.stop_after_paying = False
    restarted = ReturnsService(
        settings, Store(settings.db_path), shop, p2g, RecordingNotifier(settings), clock=clock
    )
    kept = restarted.store.get(ret.id)
    assert kept.postage.label_ref and kept.postage.label_ref.startswith("p2g:26633:")
    assert "never pays twice" in kept.last_error  # what staff see if it stays like this
    ret = approve(restarted, kept, key="k2")
    assert ret.status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1
    assert len(shop.called("returnCreate")) == 1


def test_a_refused_payment_clears_the_wait(psvc, p2g, p2g_server, clock):
    # A 4xx is Parcel2Go saying no: nothing is in flight, so topping up and trying again is
    # not made to wait.
    p2g.clock = clock
    ret = request(psvc)
    p2g_server.refuse_pay = True
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label and ret.postage.pay_sent_at is None
    p2g_server.refuse_pay = False
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert ret.status == Status.awaiting_shipment and p2g_server.paid == ["26633"]


def test_a_label_released_a_few_seconds_late_still_reaches_the_customer(psvc, p2g_server):
    ret = request(psvc)
    p2g_server.unreleased_reads = 2  # the first two asks after paying find no label
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_shipment and not ret.last_error
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def test_a_paid_label_parcel2go_is_slow_to_release_is_collected_by_the_timer(
    psvc, shop, p2g_server
):
    ret = request(psvc)
    p2g_server.unreleased_reads = 1000  # not released while staff wait
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label
    # Staff are told the truth: it is bought and will be sent, not that it failed.
    assert "is paid for" in ret.last_error and "automatically" in ret.last_error
    assert "label_paid_not_collected" in [e.type for e in ret.timeline]
    assert not any(c[0] == "reverseDeliveryCreateWithShipping" for c in shop.calls)

    p2g_server.unreleased_reads = 0  # Parcel2Go releases it
    assert psvc.tick() == []  # nothing overdue
    ret = psvc.store.get(ret.id)
    assert ret.status == Status.awaiting_shipment and not ret.last_error
    assert ret.postage.qr_file_id and ret.postage.tracking == "H01ABC"
    sent = [c for c in shop.calls if c[0] == "reverseDeliveryCreateWithShipping"]
    assert len(sent) == 1 and sent[0][1]["notify"] and sent[0][1]["label"]
    # Collected, never paid again, no second order.
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1
    psvc.tick()
    assert len([c for c in shop.calls if c[0] == "reverseDeliveryCreateWithShipping"]) == 1


def test_a_label_shopify_refused_is_handed_over_again_by_the_timer(psvc, shop, p2g_server):
    ret = request(psvc)
    shop.fail.add("attach_shipping")
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label and ret.postage.label_file_id
    shop.fail.discard("attach_shipping")
    psvc.tick()
    ret = psvc.store.get(ret.id)
    assert ret.status == Status.awaiting_shipment and ret.shopify.reverse_delivery_id
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def test_the_timer_never_pays(psvc, p2g_server):
    ret = request(psvc)
    p2g_server.refuse_pay = True
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label
    p2g_server.refuse_pay = False  # topped up, but only staff decide to pay
    psvc.tick()
    ret = psvc.store.get(ret.id)
    assert ret.status == Status.awaiting_label and "isn't paid" in ret.last_error
    assert p2g_server.paid == []


def test_an_unexpected_answer_after_paying_keeps_the_order(psvc, p2g, p2g_server, monkeypatch):
    ret = request(psvc)

    def broken(*a, **kw):
        raise KeyError("Links")

    monkeypatch.setattr(p2g, "_documents", broken)
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label and ret.postage.label_ref.startswith("p2g:26633:")
    monkeypatch.undo()
    ret = psvc.execute(ret.id, "label", {}, "staff", "k2")["return_doc"]
    assert ret.status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"] and len(p2g_server.orders) == 1


def test_a_web_page_is_never_sent_as_the_label(p2g, p2g_server):
    p2g_server.label_answers_html = True
    assert p2g._fetch("https://p2g.test/label/order?x=1", "pdf") is None
    p2g_server.label_answers_html = False
    assert p2g._fetch("https://p2g.test/label/order?x=1", "pdf").startswith(b"%PDF")


def test_ctl_collect_sends_stuck_labels_now(psvc, p2g_server, monkeypatch, capsys):
    from returns import ctl

    ret = request(psvc)
    p2g_server.unreleased_reads = 1000
    approve(psvc, ret)
    monkeypatch.setattr(ctl, "get_settings", lambda: psvc.s)
    monkeypatch.setattr(ctl, "build_service", lambda settings: psvc)
    assert ctl.main(["collect"]) == 0
    assert "Waiting" in capsys.readouterr().out
    p2g_server.unreleased_reads = 0
    assert ctl.main(["collect"]) == 0
    assert f"Sent    {ret.id}" in capsys.readouterr().out
    assert psvc.store.get(ret.id).status == Status.awaiting_shipment
    assert p2g_server.paid == ["26633"]


def no_email(psvc, shop, ret):
    order = shop.orders["gid://shopify/Order/1939"]
    order.email = order.customer_email = None
    ret.customer_email = None
    psvc.store.save(ret)
    return ret


def test_a_customer_with_no_email_gets_ours_on_the_label(psvc, shop, p2g_server):
    # CROOKS-2082: "Collection Address: Please enter the email address".
    psvc.s.returns_contact_email = "returns@crooksldn.com"
    ret = no_email(psvc, shop, request(psvc))
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_shipment
    sent = p2g_server.orders[0]["Items"][0]["CollectionAddress"]
    assert sent["Email"] == "returns@crooksldn.com"


def test_no_email_anywhere_is_said_plainly_before_anything_is_ordered(psvc, shop, p2g_server):
    psvc.s.returns_contact_email = ""
    ret = no_email(psvc, shop, request(psvc))
    ret = approve(psvc, ret)
    assert ret.status == Status.awaiting_label and "RETURNS_RETURNS_CONTACT_EMAIL" in ret.last_error
    assert p2g_server.orders == [] and p2g_server.paid == []


def test_the_order_email_is_used_when_the_return_has_none(psvc, shop, p2g_server):
    ret = request(psvc)
    ret.customer_email = None
    psvc.store.save(ret)
    approve(psvc, ret)
    assert p2g_server.orders[0]["Items"][0]["CollectionAddress"]["Email"] == "customer@example.com"
