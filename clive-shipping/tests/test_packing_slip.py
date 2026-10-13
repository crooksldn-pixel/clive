"""The packing slip: what's in the parcel, sizes and prices, the order total; for an exchange,
what was swapped for what and why. Every page prints on the 4x6 label roll as made."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from shipping import packing_slip
from shipping.app import create_app
from shipping.label_selection import label_page
from shipping.physical_printing import PhysicalPrinting, validate_label
from shipping.settings import Settings
from shipping.shopify import ShopifyError

from . import test_print_truth as truth
from .conftest import SHOP

shopify, svc, two, printer = truth.shopify, truth.svc, truth.two, truth.printer


def money(amount):
    return {"shopMoney": {"amount": amount, "currencyCode": "GBP"}}


def fo_line(n, title, size, sku, qty, price, product="P1"):
    return {
        "id": f"gid://shopify/FulfillmentOrderLineItem/{n}",
        "totalQuantity": qty,
        "remainingQuantity": qty,
        "productTitle": title,
        "variantTitle": size,
        "sku": sku,
        "variant": {"product": {"id": f"gid://shopify/Product/{product}"}},
        "lineItem": {
            "id": f"gid://shopify/LineItem/{n}",
            "quantity": qty,
            "discountedUnitPriceAfterAllDiscountsSet": money(price),
        },
    }


def order(lines, returns=()):
    return {
        "id": "gid://shopify/FulfillmentOrder/9",
        "lineItems": {"nodes": lines},
        "order": {
            "name": "#2150",
            "createdAt": "2026-10-12T10:00:00Z",
            "currencyCode": "GBP",
            "customer": {"displayName": "Sam Taylor"},
            "shippingAddress": {"name": "Sam Taylor", "city": "London", "zip": "E1 6AN"},
            "currentSubtotalPriceSet": money("100.00"),
            "currentShippingPriceSet": money("4.95"),
            "currentTotalDiscountsSet": money("10.00"),
            "currentTotalPriceSet": money("94.95"),
            "returns": {"nodes": list(returns)},
        },
    }


def pages(pdf):
    reader = PdfReader(BytesIO(pdf))
    return reader, " ".join(p.extract_text() for p in reader.pages)


def test_a_slip_lists_items_sizes_prices_and_the_order_total():
    slip = packing_slip.parse(
        order(
            [
                fo_line(1, "Blue Jeans", "32", "JEANS-32", 1, "60.00"),
                fo_line(2, "Crest Tee", "M", "TEE-M", 2, "20.00"),
                fo_line(3, "Gift card", "Default Title", "", 0, "0.00"),  # nothing to send
            ]
        )
    )
    assert [(x.title, x.size, x.quantity, str(x.total)) for x in slip.lines] == [
        ("Blue Jeans", "32", 1, "£60.00"),
        ("Crest Tee", "M", 2, "£40.00"),
    ]
    assert slip.exchange is None
    pdf = packing_slip.render(slip)
    validate_label(pdf)  # the label printer accepts it as it is
    reader, text = pages(pdf)
    assert all(label_page(p) for p in reader.pages)
    for words in (
        "CROOKS",
        "#2150",
        "Sam Taylor",
        "Blue Jeans",
        "Size 32",
        "Size M",
        "£40.00",
        "2 × £20.00",
        "Order total",
        "£94.95",
        "-£10.00",
    ):
        assert words in text, words


def returned(n, title, size, product, reason):
    return {
        "quantity": 1,
        "returnReasonDefinition": {"name": reason, "handle": reason.lower()},
        "fulfillmentLineItem": {
            "lineItem": {
                "id": f"gid://shopify/LineItem/{n}",
                "title": title,
                "variantTitle": size,
                "sku": "",
                "product": {"id": f"gid://shopify/Product/{product}"},
            }
        },
    }


def exchanged(n, title, size, product):
    return {
        "quantity": 1,
        "lineItems": [
            {
                "id": f"gid://shopify/LineItem/{n}",
                "title": title,
                "variantTitle": size,
                "sku": "",
                "product": {"id": f"gid://shopify/Product/{product}"},
            }
        ],
    }


def test_an_exchange_slip_says_what_was_swapped_for_what_and_why():
    ret = {
        "name": "#2150-R1",
        "status": "CLOSED",
        "returnLineItems": {
            "nodes": [
                returned(1, "Blue Jeans", "XS", "JEANS", "Size too small"),
                returned(2, "Joggers", "XS", "JOG", "Changed my mind"),
            ]
        },
        "exchangeLineItems": {
            "nodes": [
                exchanged(11, "Blue Jeans", "S", "JEANS"),
                exchanged(12, "Blue Jeans", "M", "JEANS"),
            ]
        },
    }
    other = {
        "name": "#2150-R0",
        "returnLineItems": {"nodes": []},
        "exchangeLineItems": {"nodes": []},
    }
    slip = packing_slip.parse(
        order(
            [
                fo_line(11, "Blue Jeans", "S", "J-S", 1, "60.00", "JEANS"),
                fo_line(12, "Blue Jeans", "M", "J-M", 1, "60.00", "JEANS"),
            ],
            returns=[other, ret],
        )
    )
    ex = slip.exchange
    assert ex is not None and ex.return_name == "#2150-R1"
    assert [(s.words, s.kind, s.reason) for s in ex.swaps] == [
        ("Blue Jeans XS > S", "Size swap", "Size too small"),
        ("Joggers XS > Blue Jeans M", "Credit swap", "Changed my mind"),
    ]
    pdf = packing_slip.render(slip)
    validate_label(pdf)
    _, text = pages(pdf)
    for words in (
        "EXCHANGE ORDER",
        "Return #2150-R1",
        "Blue Jeans XS > S",
        "Size swap",
        "Size too small",
        "Joggers XS > Blue Jeans M",
        "Credit swap",
    ):
        assert words in text, words
    assert "Order total" not in text  # an exchange isn't a sale


def test_a_long_order_runs_onto_more_4x6_pages():
    lines = [
        fo_line(i, f"Item number {i} with a long product name", "XL", f"SKU-{i}", 1, "5.00")
        for i in range(1, 30)
    ]
    pdf = packing_slip.render(packing_slip.parse(order(lines)))
    reader, text = pages(pdf)
    assert len(reader.pages) > 1 and all(label_page(p) for p in reader.pages)
    assert "Item number 29" in text and "PAGE 2" in text


# ------------------------------------------------------------------ through Shipping


@pytest.fixture
def admin(svc):
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        yield c


def test_staff_open_the_slip_and_see_an_exchange(admin, svc, shopify, two):
    a, b = two
    r = admin.post(f"/admin/api/shipments/{a.id}/packing-slip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    validate_label(r.content)
    assert "Order total" in pages(r.content)[1]
    assert admin.get(f"/admin/api/shipments/{a.id}/exchange").json() == {"exchange": None}
    # Opening a slip is not printing the label.
    assert admin.get(f"/admin/api/shipments/{a.id}").json()["stage"] != "printed"

    fo = shopify.fos[b.fulfillment_order_id]
    line = fo.lines[0]
    shopify.order_returns[fo.order_id] = [
        {
            "name": f"{fo.order_name}-R1",
            "returnLineItems": {"nodes": [returned(900, line.title, "XS", "X", "Size too small")]},
            "exchangeLineItems": {
                "nodes": [
                    {
                        "quantity": 1,
                        "lineItems": [
                            {
                                "id": line.id.replace("FulfillmentOrderLineItem", "LineItem"),
                                "title": line.title,
                                "variantTitle": line.variant_title,
                                "product": {"id": line.product_id},
                            }
                        ],
                    }
                ]
            },
        }
    ]
    ex = admin.get(f"/admin/api/shipments/{b.id}/exchange").json()["exchange"]
    assert ex["return_name"] == f"{fo.order_name}-R1"
    assert ex["swaps"][0]["kind"] == "Credit swap"  # the returned item was another product
    text = pages(admin.post(f"/admin/api/shipments/{b.id}/packing-slip").content)[1]
    assert "EXCHANGE ORDER" in text and "Size too small" in text


def test_no_slip_is_made_up_when_shopify_doesnt_answer(admin, svc, shopify, two, monkeypatch):
    a, _ = two

    def down(fo_id):
        raise ShopifyError("Shopify could not be reached")

    monkeypatch.setattr(shopify, "slip_source", down)
    r = admin.post(f"/admin/api/shipments/{a.id}/packing-slip")
    assert r.status_code == 503 and "Try again" in r.json()["detail"]["message"]
    assert admin.post("/admin/api/shipments/shp_nope/packing-slip").status_code == 404


def test_a_slip_goes_to_the_label_printer_once_per_press(svc, two, printer):
    a, _ = two
    node = PhysicalPrinting(svc.store, printer, 75883753)
    source = svc.shopify.slip_source(a.fulfillment_order_id)
    assert source is not None
    body = packing_slip.render(packing_slip.parse(source))
    first = node.print_slip(SHOP, a.id, "Sam", "slip-press-1", body)
    again = node.print_slip(SHOP, a.id, "Sam", "slip-press-1", body)  # lost reply, retried
    assert again["id"] == first["id"] and printer.print_pdf.call_count == 1
    node.print_slip(SHOP, a.id, "Sam", "slip-press-2", body)  # another copy, on purpose
    assert printer.print_pdf.call_count == 2
    s = svc.store.get(SHOP, a.id)
    assert [e.type for e in s.timeline].count("packing_slip_printed") == 2
    label = node.summary(SHOP, a.id)
    assert label is not None and label["state"] == "not_printed"  # the label isn't printed


def test_an_order_number_opens_the_shipment_still_to_send(admin, svc, two):
    a, _ = two
    number = a.order_name.split("-")[-1]
    out = admin.get(f"/admin/api/orders/{number}/shipment")
    assert out.status_code == 200 and out.json()["shipment_id"] == a.id
    missing = admin.get("/admin/api/orders/999999/shipment")
    assert missing.status_code == 404 and "processed" in missing.json()["detail"]["message"]
