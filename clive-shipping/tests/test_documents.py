"""Label documents: page sizes, the paperless/paper decision, the print plan, reprint."""

import pytest

from shipping.documents import (
    CustomsEvidence,
    customs_mode,
    page_size,
    pdf_pages,
    print_plan,
)
from shipping.models import CustomsMode, DocumentKind, PageSize
from shipping.models import ShipmentStatus as S
from shipping.purchase import ActionError

from .conftest import SHOP, make_shipment
from .pdfs import A4, LABEL_4X6, pdf


def test_page_sizes_are_read_from_the_pdf():
    assert page_size(pdf(LABEL_4X6)) == PageSize.label_4x6
    assert page_size(pdf(A4, A4, A4)) == PageSize.a4
    # Parcel2Go's ready-made "labels-4x6" link: A4 advice and invoice pages around one label.
    assert page_size(pdf(A4, A4, LABEL_4X6, A4)) == PageSize.mixed
    assert pdf_pages(pdf(A4, A4, A4)) == 3
    assert pdf_pages(b"<html>Sign in</html>") == 0


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        # DPD, Landmark, OCS: no additional documents, and "all" holds only label + invoice.
        (CustomsEvidence(True, 0, 1, 1, 2), (CustomsMode.electronic, 0)),
        # Evri International: 3 invoice copies; UPS Access Point: 4.
        (CustomsEvidence(True, 3, 1, 1, 5), (CustomsMode.paper, 3)),
        (CustomsEvidence(True, 4, 1, 1, 6), (CustomsMode.paper, 4)),
        # A 404 that "all" contradicts (documents not generated yet?) is not paperless.
        (CustomsEvidence(True, 0, 1, 1, 5), (CustomsMode.unknown, 0)),
        # The views disagree on how many pages to print.
        (CustomsEvidence(True, 3, 1, 1, 6), (CustomsMode.unknown, 0)),
        # A request failed: unknown, never electronic.
        (CustomsEvidence(True, None, 1, 1, 2), (CustomsMode.unknown, 0)),
        (CustomsEvidence(True, 0, 1, 1, None), (CustomsMode.unknown, 0)),
        # No customs on the route at all.
        (CustomsEvidence(False, 0, None, 1, 1), (CustomsMode.not_required, 0)),
    ],
)
def test_paperless_needs_two_views_to_agree(evidence, expected):
    assert customs_mode(evidence) == expected


def bought(purchases, store, provider, customs="electronic"):
    provider.customs = customs
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    return out, store.get(SHOP, s.id)


def test_paperless_reads_as_one_thing_to_print(purchases, store, provider):
    _, s = bought(purchases, store, provider)
    plan = print_plan(s.label)
    assert plan.ready and plan.summary == "Ready to print" and plan.extra_documents == 0
    assert [ln.text for ln in plan.lines] == [
        "Shipping label — 4×6 thermal",
        "Customs — filed electronically, nothing to print",
    ]
    assert plan.lines[0].printer == "thermal"
    invoice = s.label.document(DocumentKind.commercial_invoice)
    assert invoice.electronic and not invoice.must_print  # kept for the record


def test_paper_customs_reads_as_one_extra_document(purchases, store, provider):
    _, s = bought(purchases, store, provider, customs="paper")
    plan = print_plan(s.label)
    assert plan.ready and plan.summary == "1 extra document required"
    assert [ln.text for ln in plan.lines] == [
        "Shipping label — 4×6 thermal",
        "Commercial invoice — print 3 copies (A4)",
    ]
    invoice = s.label.document(DocumentKind.commercial_invoice)
    assert invoice.must_print and invoice.attach_to_parcel and invoice.copies_required == 3


def test_unknown_customs_is_never_shown_as_ready(purchases, store, provider):
    out, s = bought(purchases, store, provider, customs="unknown")
    assert out["charged"] and s.status == S.label_purchased
    plan = print_plan(s.label)
    assert not plan.ready and "still being checked" in plan.lines[-1].text
    op = store.op_by_key(SHOP, "k1")
    assert op.state.value == "paid"  # stays open: reconcile keeps checking
    provider.customs = "paper"  # the provider's documents arrive
    purchases.reconcile(op)
    s = store.get(SHOP, s.id)
    assert print_plan(s.label).ready and s.label.customs == CustomsMode.paper
    assert len(provider.charges) == 1


@pytest.mark.parametrize("kind", list(DocumentKind))
def test_reprinting_any_document_never_reaches_the_provider(purchases, store, provider, kind):
    _, s = bought(purchases, store, provider, customs="paper")
    calls, charges = list(provider.calls), list(provider.charges)
    stored = s.label.document(kind)
    if stored and stored.artifact_id:
        _, body = purchases.reprint(SHOP, s.id, kind)
        _, again = purchases.reprint(SHOP, s.id, kind)
        assert body == again and body.startswith(b"%PDF")
    else:
        with pytest.raises(ActionError):
            purchases.reprint(SHOP, s.id, kind)
    assert provider.calls == calls and provider.charges == charges
