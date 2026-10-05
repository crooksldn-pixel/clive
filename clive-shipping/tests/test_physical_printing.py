"""Physical output consumes purchased artifacts, with durable independent intent IDs."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from shipping.app import create_app
from shipping.models import DocumentKind, PageSize, ShipmentDocument
from shipping.physical_printing import PhysicalPrinting
from shipping.physical_printing import test_pdf as make_test_pdf
from shipping.print_provider import OPTIONS, PrintNodeProvider, PrintProviderError
from shipping.printing import PrintError
from shipping.settings import Settings
from shipping.store import Store

from . import test_printing
from .conftest import SHOP
from .test_printing import bought, trap

shopify = test_printing.shopify
svc = test_printing.svc


def pdf(*sizes):
    stream = BytesIO()
    w = PdfWriter()
    for width, height in sizes:
        w.add_blank_page(width=width, height=height)
    w.write(stream)
    return stream.getvalue()


@pytest.fixture
def purchased(svc, shopify):
    s = bought(svc, shopify)
    body = pdf((288, 432))
    artifact = svc.store.put_artifact(SHOP, s.id, "shipping_label", "application/pdf", body)
    s.label.documents = [
        ShipmentDocument(
            kind=DocumentKind.shipping_label,
            artifact_id=artifact,
            page_size=PageSize.label_4x6,
            pages=1,
        )
    ]
    svc.store.save(s)
    return s, body


@pytest.fixture
def sender():
    p = Mock()
    p.print_pdf.side_effect = range(100, 120)
    p.get_job_status.return_value = "done"
    return p


def test_print_retries_and_explicit_reprint_never_buy(
    svc, provider, purchased, sender, monkeypatch
):
    s, body = purchased
    charges = list(provider.charges)
    trap(provider, monkeypatch)
    output = PhysicalPrinting(svc.store, sender, 75883753)
    a = output.print_label(SHOP, s.id, "staff", "request-1")
    b = output.print_label(SHOP, s.id, "staff", "request-2")
    assert a["id"] == b["id"] and sender.print_pdf.call_count == 1
    c = output.print_label(SHOP, s.id, "staff", "reprint-1", reprint=True)
    d = output.print_label(SHOP, s.id, "staff", "reprint-1", reprint=True)
    assert c["id"] == d["id"] != a["id"] and sender.print_pdf.call_count == 2
    assert c["idempotency_key"] != a["idempotency_key"]
    assert all(call.args[0] == body for call in sender.print_pdf.call_args_list)
    assert provider.charges == charges
    assert output.status(SHOP, a["id"])["provider_state"] == "done"
    assert output.status(SHOP, a["id"])["state"] == "accepted"  # no physical success claim
    with pytest.raises(PrintError):
        output.status("other-shop", a["id"])


@pytest.mark.parametrize(
    "size", [((595, 842),), ((288, 432), (595, 842)), ((288, 432), (288, 432)), ((432, 288),)]
)
def test_rejects_a4_combined_multipage_and_landscape(svc, purchased, sender, size):
    s, _ = purchased
    d = s.label.documents[0]
    d.artifact_id = svc.store.put_artifact(
        SHOP, s.id, "shipping_label", "application/pdf", pdf(*size)
    )
    svc.store.save(s)
    with pytest.raises(PrintError, match="single-page"):
        PhysicalPrinting(svc.store, sender, 75883753).print_label(SHOP, s.id, "staff", "request-1")
    sender.print_pdf.assert_not_called()


def test_customs_metadata_never_reaches_printer(svc, purchased, sender):
    s, _ = purchased
    s.label.documents[0].kind = DocumentKind.customs_declaration
    svc.store.save(s)
    with pytest.raises(PrintError):
        PhysicalPrinting(svc.store, sender, 75883753).print_label(SHOP, s.id, "staff", "request-1")
    sender.print_pdf.assert_not_called()


def test_missing_purchase_refused(svc, shopify, provider, sender, monkeypatch):
    from shipping.fake_shopify import fo, tee_line

    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = svc.store.shipments(SHOP)[0]
    trap(provider, monkeypatch)
    with pytest.raises(PrintError, match="never buys"):
        PhysicalPrinting(svc.store, sender, 75883753).print_label(SHOP, s.id, "staff", "request-1")
    sender.print_pdf.assert_not_called()


@pytest.mark.parametrize("uncertain", [False, True])
def test_failure_keeps_purchase_and_never_resubmits(svc, purchased, sender, uncertain):
    s, _ = purchased
    before = svc.store.get(SHOP, s.id).model_dump_json()
    sender.print_pdf.side_effect = PrintProviderError("PrintNode unavailable", uncertain=uncertain)
    output = PhysicalPrinting(svc.store, sender, 75883753)
    a = output.print_label(SHOP, s.id, "staff", "request-1")
    assert a["state"] == ("unknown" if uncertain else "failed")
    assert output.print_label(SHOP, s.id, "staff", "request-1") == a
    assert sender.print_pdf.call_count == 1
    assert svc.store.get(SHOP, s.id).model_dump_json() == before


def test_offline_records_failure_without_post(svc, purchased, sender):
    s, _ = purchased
    sender.get_printer.side_effect = PrintProviderError("offline")
    result = PhysicalPrinting(svc.store, sender, 75883753).print_label(
        SHOP, s.id, "staff", "request-1"
    )
    assert result["state"] == "failed"
    sender.print_pdf.assert_not_called()


def test_cross_process_style_sqlite_intent_ownership(svc, purchased, sender):
    s, _ = purchased
    db = svc.store._db.execute("PRAGMA database_list").fetchone()[2]
    other = Store(db)
    a = PhysicalPrinting(svc.store, sender, 75883753)
    b = PhysicalPrinting(other, sender, 75883753)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda output: output.print_label(SHOP, s.id, "staff", "request-1"), [a, b])
        )
    assert results[0]["id"] == results[1]["id"]
    assert sender.print_pdf.call_count == 1


def printer(state="online", name="JD-168BT"):
    return dict(
        id=75883753,
        name=name,
        state=state,
        computer=dict(id=787558, state="connected"),
        capabilities=dict(
            papers={OPTIONS["paper"]: [1016, 1524]}, dpis=["203x203"], bins=["Roll Paper Feeder"]
        ),
    )


def test_actual_http_payload_is_stored_pdf_and_proven_options():
    calls = []
    body = pdf((288, 432))

    def handle(req):
        calls.append(req)
        if req.method == "GET":
            return httpx.Response(200, json=[printer()])
        return httpx.Response(201, json=4321)

    p = PrintNodeProvider("test-only-key", 75883753, transport=httpx.MockTransport(handle))
    p.get_printer()
    assert p.print_pdf(body, "label", "unique-intent") == 4321
    payload = json.loads(calls[-1].content)
    assert base64.b64decode(payload["content"]) == body
    assert payload["contentType"] == "pdf_base64" and payload["qty"] == 1
    assert payload["options"] == OPTIONS
    assert calls[-1].headers["X-Idempotency-Key"] == "unique-intent"
    assert all(req.url.host == "api.printnode.com" for req in calls)


@pytest.mark.parametrize("status", [401, 409, 500])
def test_errors_never_leak_key_or_response(status, caplog):
    key = "SECRET-TEST-SENTINEL"
    p = PrintNodeProvider(
        key, 75883753, transport=httpx.MockTransport(lambda req: httpx.Response(status, text=key))
    )
    with pytest.raises(PrintProviderError) as e:
        p.print_pdf(b"pdf", "label", "intent")
    assert key not in str(e.value) and key not in caplog.text
    cfg = Settings(PRINTNODE_API_KEY=key)
    assert key not in repr(cfg) and key not in cfg.model_dump_json()


@pytest.mark.parametrize("row", [printer("offline"), printer(name="wrong-printer")])
def test_invalid_printer_refused(row):
    p = PrintNodeProvider(
        "test", 75883753, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[row]))
    )
    with pytest.raises(PrintProviderError):
        p.get_printer()


def test_admin_api_authenticated_print_reprint_setup_and_test(svc, purchased, sender, monkeypatch):
    monkeypatch.setattr("shipping.admin.PrintNodeProvider", lambda *args: sender)
    sender.health.return_value = dict(
        enabled=True,
        connected=True,
        name="JD-168BT",
        printer_id=75883753,
        state="online",
        detail="Connected",
    )
    cfg = Settings(
        shop_domain=SHOP,
        provider="fake",
        dev_skip_admin_auth=True,
        tick_interval_s=0,
        PRINTNODE_ENABLED=True,
        PRINTNODE_API_KEY="test-key",
    )
    with TestClient(create_app(cfg, svc)) as client:
        s, _ = purchased
        path = f"/admin/api/shipments/{s.id}/print-label"
        body = {"idempotency_key": "same-request"}
        assert client.post(path, json=body).json()["message"] == "Sent to JD-168BT"
        assert client.post(path, json=body).status_code == 200
        assert sender.print_pdf.call_count == 1
        assert (
            client.post(path.replace("print-label", "reprint-label"), json=body).status_code == 200
        )
        assert sender.print_pdf.call_count == 2
        assert "test-key" not in client.get("/admin/api/setup").text
        response = client.post("/admin/api/print/test", json=body)
        assert response.status_code == 200
        assert client.post("/admin/api/print/test", json=body).status_code == 200
        assert sender.print_pdf.call_count == 3
        test_body = sender.print_pdf.call_args.args[0]
        from pypdf import PdfReader

        text = PdfReader(BytesIO(test_body)).pages[0].extract_text()
        assert "CROOKS SHIPPING" in text and "PRINTER TEST" in text
    cfg.dev_skip_admin_auth = False
    with TestClient(create_app(cfg, svc)) as client:
        assert client.post(path, json=body).status_code == 401


def test_test_pdf_is_single_portrait_label():
    from shipping.physical_printing import validate_label

    validate_label(make_test_pdf())


def test_postage_transports_cannot_be_reached(svc, purchased, sender, monkeypatch):
    from shipping.providers.easyship import Easyship
    from shipping.providers.parcel2go import Parcel2Go

    def forbidden(*args, **kwargs):
        raise AssertionError("Physical printing reached a postage transport")

    monkeypatch.setattr(Easyship, "_call", forbidden)
    monkeypatch.setattr(Parcel2Go, "_call", forbidden)
    s, _ = purchased
    output = PhysicalPrinting(svc.store, sender, 75883753)
    output.print_label(SHOP, s.id, "staff", "first-request")
    output.print_label(SHOP, s.id, "staff", "reprint-request", reprint=True)
    output.test_print(SHOP, "staff", "test-request")
    assert sender.print_pdf.call_count == 3


def test_intent_survives_reopening_database(svc, purchased, sender):
    s, _ = purchased
    output = PhysicalPrinting(svc.store, sender, 75883753)
    a = output.print_label(SHOP, s.id, "staff", "first-request")
    path = svc.store._db.execute("PRAGMA database_list").fetchone()[2]
    reopened = PhysicalPrinting(Store(path), sender, 75883753)
    assert reopened.print_label(SHOP, s.id, "staff", "new-browser-key")["id"] == a["id"]
    assert sender.print_pdf.call_count == 1


def test_status_error_records_failure_without_touching_label(svc, purchased, sender):
    s, _ = purchased
    output = PhysicalPrinting(svc.store, sender, 75883753)
    a = output.print_label(SHOP, s.id, "staff", "first-request")
    before = svc.store.get(SHOP, s.id).model_dump_json()
    sender.get_job_status.return_value = "error"
    result = output.status(SHOP, a["id"])
    assert result["state"] == "failed" and result["last_checked_at"]
    assert result["error"] == "PrintNode reported error; physical output unconfirmed."
    assert svc.store.get(SHOP, s.id).model_dump_json() == before
    assert sender.print_pdf.call_count == 1


def test_http_timeout_is_uncertain_with_one_attempt():
    attempts = []

    def timeout(req):
        attempts.append(req)
        raise httpx.ReadTimeout("secret must not escape", request=req)

    p = PrintNodeProvider("secret", 75883753, transport=httpx.MockTransport(timeout))
    with pytest.raises(PrintProviderError) as exc:
        p.print_pdf(b"pdf", "label", "stable-key")
    assert exc.value.uncertain and len(attempts) == 1
    assert "secret" not in str(exc.value)


def test_status_nested_api_shape_and_timestamp_ties():
    rows = [
        [
            dict(printJobId=123, state="in_progress", createTimestamp="same"),
            dict(printJobId=123, state="done", createTimestamp="same"),
        ]
    ]
    p = PrintNodeProvider(
        "test", 75883753, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=rows))
    )
    assert p.get_job_status(123) == "done"


def test_print_modules_have_no_postage_dependencies():
    import ast
    from pathlib import Path

    for module in ("physical_printing", "print_provider"):
        tree = ast.parse((Path(__file__).parents[1] / "shipping" / f"{module}.py").read_text())
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
        assert not any(
            i.startswith(("shipping.purchase", "shipping.service", "shipping.providers"))
            for i in imports
        )
