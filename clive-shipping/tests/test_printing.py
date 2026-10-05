"""Print and reprint read stored documents only. They can never quote, buy or pay (Stage 4)."""

import ast
from pathlib import Path

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.printing import PrinterRole, PrintError, Printing, order_number
from shipping.purchase import Purchases
from shipping.service import ShippingService

from .conftest import SHOP
from .test_stage2 import answer_all_first_time, only

PRINTING = Path(__file__).resolve().parent.parent / "shipping" / "printing.py"


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


@pytest.fixture
def printing(store, clock):
    return Printing(store, clock=clock)


def bought(svc, shopify, n=2145):
    shopify.add(fo(n, [tee_line()]))
    svc.sync(SHOP)
    s = next(x for x in svc.store.shipments(SHOP) if x.order_name == f"CROOKS-{n}")
    s = answer_all_first_time(svc, s)
    b = svc.preview(SHOP, s.id)["basis"]
    return svc.buy(SHOP, s.id, b, "george", f"k{n}")["shipment"]


def trap(provider, monkeypatch):
    """From here on, any provider call fails the test."""
    for name in ("quotes", "verify", "create_order", "pay", "read_order", "documents"):

        def boom(*args, _name=name, **kwargs):
            raise AssertionError(f"printing reached the provider: {_name}")

        monkeypatch.setattr(provider, name, boom)


def test_the_printing_module_has_no_way_to_buy():
    tree = ast.parse(PRINTING.read_text())
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    assert imported <= {
        "__future__",
        "re",
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "typing",
        "shipping.models",
        "shipping.store",
    }, imported


def test_print_then_reprint_use_the_stored_label_only(
    svc, shopify, provider, printing, monkeypatch
):
    s = bought(svc, shopify)
    charges, ops = len(provider.charges), len(svc.store.ops_for(SHOP, s.id))
    trap(provider, monkeypatch)
    first = printing.print_shipment(SHOP, s.id, "george")
    again = printing.print_shipment(SHOP, s.id, "george")
    assert [j.artifact_id for j in first] == [j.artifact_id for j in again]
    label = first[0]
    assert label.printer == PrinterRole.label and label.copies == 1 and label.page_size == "4x6"
    content_type, body = printing.document(SHOP, label.artifact_id)
    assert content_type == "application/pdf" and body.startswith(b"%PDF")
    kinds = [e.type for e in svc.store.get(SHOP, s.id).timeline]
    assert kinds.count("label_printed") == 1 and kinds.count("label_reprinted") == 1
    assert len(provider.charges) == charges and len(svc.store.ops_for(SHOP, s.id)) == ops


def test_paper_customs_print_the_invoice_copies_on_the_a4_printer(svc, shopify, provider, printing):
    provider.customs = "paper"
    s = bought(svc, shopify)
    jobs = printing.print_shipment(SHOP, s.id, "george")
    invoice = next(j for j in jobs if j.kind == "commercial_invoice")
    assert invoice.printer == PrinterRole.document and invoice.copies == 3


def test_printing_an_order_without_a_label_never_buys_one(
    svc, shopify, provider, printing, monkeypatch
):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))  # ready, priced, not bought
    trap(provider, monkeypatch)
    with pytest.raises(PrintError, match="never buys"):
        printing.print_shipment(SHOP, s.id, "george")
    with pytest.raises(PrintError):
        printing.find_order(SHOP, "2145")
    assert svc.store.ops_for(SHOP, s.id) == [] and provider.charges == []


def test_reprint_order_2145_finds_it_by_number(svc, shopify, printing):
    s = bought(svc, shopify)
    for ref in ("2145", "#2145", "CROOKS-2145", "reprint order 2145"):
        assert printing.find_order(SHOP, ref).id == s.id
    assert order_number("CROOKS-2145") == "2145"


def test_print_all_ready_labels_prints_each_unprinted_label_once(
    svc, shopify, provider, printing, monkeypatch
):
    ids = [bought(svc, shopify, n).id for n in (2145, 2146, 2147)]
    printing.print_shipment(SHOP, ids[0], "george")  # already printed by hand
    trap(provider, monkeypatch)
    assert [s.id for s in printing.ready(SHOP)] == ids[1:]
    jobs = printing.print_ready(SHOP, "george")
    assert sorted({j.shipment_id for j in jobs}) == sorted(ids[1:])
    assert printing.ready(SHOP) == [] and printing.print_ready(SHOP, "george") == []


def test_a_document_from_another_shop_is_not_served(svc, shopify, printing):
    s = bought(svc, shopify)
    artifact = s.label.documents[0].artifact_id
    with pytest.raises(PrintError):
        printing.document("other-shop.myshopify.com", artifact)
