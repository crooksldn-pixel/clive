"""Label files print whole, customs form included, and the stored original is never changed."""

import base64
import hashlib
import json
from io import BytesIO
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from shipping.app import create_app
from shipping.label_selection import CN23_NOTE, easyship_cn23, parcel_label_pdf
from shipping.models import CustomsMode, DocumentKind, PageSize, ShipmentDocument
from shipping.physical_printing import validate_label
from shipping.print_provider import OPTIONS, PrintNodeProvider
from shipping.printing import PrintError
from shipping.providers.easyship import Easyship
from shipping.providers.parcel2go import Parcel2Go
from shipping.settings import Settings

from . import test_physical_printing as physical
from .conftest import SHOP
from .test_printing import trap

svc = physical.svc
shopify = physical.shopify
purchased = physical.purchased


def bundle(
    texts=("ROYAL MAIL SHIPPING LABEL - VU721241607GB", "CUSTOMS DECLARATION CN23"),
    size=(101 * mm, 152 * mm),
):
    stream = BytesIO()
    c = Canvas(stream, pagesize=size, invariant=1)
    for text in texts:
        c.rect(5 * mm, 5 * mm, size[0] - 10 * mm, size[1] - 10 * mm)
        c.setFont("Helvetica", 9)
        c.drawString(7 * mm, 140 * mm, text)
        c.showPage()
    c.save()
    return stream.getvalue()


def select(body, **changes):
    args: dict[str, Any] = dict(kind=DocumentKind.shipping_label, page_size=PageSize.label_4x6)
    return parcel_label_pdf(body, **(args | changes))


def test_print_reprint_original_download_storage_and_no_postage(
    svc, purchased, provider, monkeypatch
):
    s, _ = purchased
    original = bundle()
    invoice = bundle(("COMMERCIAL INVOICE",), (210 * mm, 297 * mm))
    artifact = svc.store.put_artifact(SHOP, s.id, "shipping_label", "application/pdf", original)
    invoice_id = svc.store.put_artifact(
        SHOP, s.id, "commercial_invoice", "application/pdf", invoice
    )
    s.label.provider = "Easyship"
    s.label.carrier = "Royal Mail"
    s.label.service_name = "Royal Mail Domestic Tracked 48 - Small Parcel"
    s.label.documents = [
        ShipmentDocument(
            kind=DocumentKind.shipping_label,
            artifact_id=artifact,
            page_size=PageSize.label_4x6,
            pages=2,
        ),
        ShipmentDocument(
            kind=DocumentKind.commercial_invoice,
            artifact_id=invoice_id,
            page_size=PageSize.a4,
            pages=1,
        ),
    ]
    svc.store.save(s)
    before = svc.store.get(SHOP, s.id)
    ops_before = [tuple(row) for row in svc.store._db.execute("SELECT * FROM provider_ops")]
    digest = hashlib.sha256(original).hexdigest()
    charges = list(provider.charges)
    trap(provider, monkeypatch)
    forbidden = Mock(side_effect=AssertionError("Print must not call postage providers"))
    monkeypatch.setattr(Easyship, "_call", forbidden)
    monkeypatch.setattr(Parcel2Go, "_call", forbidden)
    requests = []

    def transport(req):
        requests.append(req)
        if req.method == "GET":
            return httpx.Response(200, json=[physical.printer()])
        return httpx.Response(201, json=9000 + len(requests))

    node = PrintNodeProvider("test-only", 75883753, transport=httpx.MockTransport(transport))
    monkeypatch.setattr("shipping.admin.PrintNodeProvider", lambda *args: node)
    cfg = Settings.model_validate(
        dict(
            shop_domain=SHOP,
            provider="fake",
            dev_skip_admin_auth=True,
            tick_interval_s=0,
            PRINTNODE_ENABLED=True,
            PRINTNODE_API_KEY="test-only",
        )
    )
    with TestClient(create_app(cfg, svc)) as client:
        original_path = f"/admin/api/documents/{artifact}"
        assert client.get(original_path).content == original
        assert client.get(f"/admin/api/documents/{invoice_id}").content == invoice
        path = f"/admin/api/shipments/{s.id}/print-label"
        first = client.post(path, json={"idempotency_key": "first-print"})
        assert first.status_code == 200
        retry = client.post(path, json={"idempotency_key": "browser-retry"})
        assert retry.json()["print_intent"]["id"] == first.json()["print_intent"]["id"]
        reprint = client.post(
            path.replace("print-label", "reprint-label"),
            json={"idempotency_key": "intentional-reprint"},
        )
        assert (
            reprint.status_code == 200
            and reprint.json()["print_intent"]["id"] != first.json()["print_intent"]["id"]
        )
        assert client.get(original_path).content == original
        assert client.get(f"/admin/api/documents/{invoice_id}").content == invoice
    posts = [req for req in requests if req.method == "POST"]
    assert len(posts) == 2
    assert posts[0].headers["X-Idempotency-Key"] != posts[1].headers["X-Idempotency-Key"]
    sent = []
    for req in posts:
        payload = json.loads(req.content)
        assert payload["printerId"] == 75883753
        assert payload["contentType"] == "pdf_base64"
        # Both pages: the shipping label and the CN23 customs form go on the parcel.
        assert payload["options"] == OPTIONS | {"pages": "1-2"} and payload["qty"] == 1
        body = base64.b64decode(payload["content"])
        sent.append(body)
        validate_label(body)
        assert body == original  # the provider's file, unchanged
        pages = PdfReader(BytesIO(body)).pages
        assert "SHIPPING LABEL" in pages[0].extract_text()
        assert "CN23" in pages[1].extract_text()
    assert sent[0] == sent[1]
    stored = svc.store.get_artifact(SHOP, artifact)[2]
    assert stored == original and len(PdfReader(BytesIO(stored)).pages) == 2
    assert hashlib.sha256(stored).hexdigest() == digest
    db_digest = svc.store._db.execute(
        "SELECT sha256 FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()[0]
    assert db_digest == digest
    after = svc.store.get(SHOP, s.id)
    assert after.label == before.label
    assert [tuple(row) for row in svc.store._db.execute("SELECT * FROM provider_ops")] == ops_before
    assert after.status == before.status
    assert provider.charges == charges
    forbidden.assert_not_called()


def test_parcel2go_dedicated_label_unchanged():
    body = bundle(("PARCEL2GO SHIPPING LABEL",))
    assert select(body) == body
    validate_label(body)


@pytest.mark.parametrize(
    "changes", [dict(kind=DocumentKind.commercial_invoice), dict(page_size=PageSize.a4)]
)
def test_non_label_metadata_refused(changes):
    with pytest.raises(PrintError):
        select(bundle(), **changes)


@pytest.mark.parametrize(
    "texts",
    [
        ("LABEL", "UNIDENTIFIED SECOND PAGE"),
        ("LABEL", "CN23", "OTHER PAGE"),
        ("LABEL", "CUSTOMS DECLARATION CN22May be opened"),
    ],
)
def test_every_4x6_page_the_carrier_put_in_the_label_file_prints(texts):
    body = bundle(texts)
    assert select(body) == body  # never a page dropped: it may be the customs form


def test_a_mixed_sheet_and_label_file_is_never_sent_to_the_label_printer():
    stream = BytesIO()
    writer = PdfWriter()
    for part in (bundle(("LABEL",)), bundle(("INVOICE",), (210 * mm, 297 * mm))):
        writer.add_page(PdfReader(BytesIO(part)).pages[0])
    writer.write(stream)
    with pytest.raises(PrintError):
        select(stream.getvalue())


@pytest.mark.parametrize(
    "body",
    [
        bundle(size=(210 * mm, 297 * mm)),
        bundle(tuple(f"PAGE {n}" for n in range(5))),  # not a label file
        b"not a PDF",
    ],
)
def test_files_that_are_not_label_files_refused(body):
    with pytest.raises(PrintError):
        select(body)


@pytest.mark.parametrize("include_invoice", [False, True])
def test_easyship_cn23_metadata_and_separate_invoice(monkeypatch, include_invoice, cfg):
    original = bundle()
    invoice = bundle(("COMMERCIAL INVOICE",), (210 * mm, 297 * mm))
    docs: list[dict[str, Any]] = [
        dict(category="label", base64_encoded_strings=[base64.b64encode(original).decode()])
    ]
    if include_invoice:
        docs.append(
            dict(
                category="commercial_invoice",
                required=True,
                base64_encoded_strings=[base64.b64encode(invoice).decode()],
            )
        )
    monkeypatch.setattr(
        Easyship,
        "_shipment",
        lambda *args: dict(
            label_state="generated", label_paid_at="2026-10-05", shipping_documents=docs
        ),
    )
    result = Easyship("test-only", lambda shop: cfg).documents("es:stored-paid-reference")
    label = result.documents[0]
    assert label.body == original and label.pages == 2 and label.note == CN23_NOTE
    assert label.kind == DocumentKind.shipping_label and label.page_size == PageSize.label_4x6
    assert result.customs == CustomsMode.paper
    if include_invoice:
        assert result.documents[1].kind == DocumentKind.commercial_invoice
        assert result.documents[1].body == invoice and result.documents[1].page_size == PageSize.a4


@pytest.mark.parametrize("fault", ["encrypted", "rotated", "cropped", "landscape"])
def test_unsafe_combined_pdf_refused(fault):
    reader = PdfReader(BytesIO(bundle()))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    if fault == "encrypted":
        writer.encrypt("test-only")
    elif fault == "rotated":
        writer.pages[0].rotate(90)
    elif fault == "cropped":
        writer.pages[0].cropbox.upper_right = (90 * mm, 152 * mm)
    else:
        writer.pages[0].mediabox.upper_right = (152 * mm, 101 * mm)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(PrintError):
        select(stream.getvalue())


# The live Easyship Royal Mail bundles (CROOKS-2120/2124/2134/2142/2144, 2026-10-05): pypdf reads
# the CN23 heading run into the next words, "...DECLARATION CN23May be opened officially".
LIVE_CN23 = "CUSTOMS DECLARATION CN23May be opened officially"


def test_the_live_easyship_label_and_cn23_both_print():
    body = bundle(("ROYAL MAIL SHIPPING LABEL - VU721241607GB", LIVE_CN23))
    assert easyship_cn23(body)
    printed = select(body)
    pages = PdfReader(BytesIO(printed)).pages
    assert printed == body and len(pages) == 2
    assert "VU721241607GB" in (pages[0].extract_text() or "")
    assert "CN23" in (pages[1].extract_text() or "")  # the customs form goes on the parcel too
    validate_label(printed)


@pytest.mark.parametrize(
    "texts",
    [
        ("LABEL", "CUSTOMS DECLARATION CN230 FORM"),  # another form number is not a CN23
        ("LABEL", "CUSTOMS DECLARATION CN22May be opened"),
    ],
)
def test_only_a_real_cn23_is_named_as_one(texts):
    assert not easyship_cn23(bundle(texts))
