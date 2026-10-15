"""Bulk printing sends each person's documents as one set, one person at a time.

Live, 15 Oct 2026: six labels sent as six PrintNode jobs within half a second reached the JADENS
85 ms apart; it fed through and printed them garbled. A set is the label (and its customs form)
then the packing slip, in one job, and the next set goes only once PrintNode says the previous
one finished and its pages have had time to come out.
"""

from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

from shipping.models import DocumentKind, PageSize, ShipmentDocument
from shipping.operations import Operations, Pacer
from shipping.physical_printing import PhysicalPrinting
from shipping.printing import PrintError

from . import test_printing as printing
from .conftest import SHOP
from .test_label_selection import bundle
from .test_operations import purchased

svc = printing.svc
shopify = printing.shopify

DONE = [dict(state="done", at="2026-10-15T10:18:21Z", message="")]
QUEUED = [dict(state="queued", at="2026-10-15T10:18:18Z", message="")]


def texts(body: bytes) -> list[str]:
    return [(p.extract_text() or "").strip() for p in PdfReader(BytesIO(body)).pages]


class Timeline:
    """A fake clock and sleep that record what happened in which order."""

    def __init__(self):
        self.t = 0.0
        self.log: list[str] = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.log.append(f"sleep {s:g}")
        self.t += s


@pytest.fixture
def line():
    return Timeline()


@pytest.fixture
def sender(line):
    p = Mock()
    jobs = iter(range(1000, 2000))
    p.sent = []

    def send(body, title, key):
        jid = next(jobs)
        p.sent.append((jid, body))
        line.log.append(f"send {jid}")
        return jid

    p.print_pdf.side_effect = send
    p.get_job_states.return_value = DONE
    return p


def slip_for(shop, sid):
    s = svc_ref[0].store.get(shop, sid)
    return bundle((f"SLIP {s.order_name}",))


svc_ref: list = []


@pytest.fixture
def ops(svc, sender, line):
    svc_ref[:] = [svc]
    pacer = Pacer(page_s=4, wait_s=30, poll_s=1, sleep=line.sleep, clock=line.clock)
    return Operations(
        svc, PhysicalPrinting(svc.store, sender, 75883753), slips=slip_for, pacer=pacer
    )


def run(ops, rows, kind="print", key="print-sets"):
    b = ops.preview(SHOP, kind, [s.id for s in rows], "staff", key)
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    return ops.get(SHOP, b["id"])


def test_each_person_is_one_job_label_then_slip(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 2)
    b = run(ops, rows)
    assert [c["state"] for c in b["children"]] == ["printed", "printed"]
    assert len(sender.sent) == 2  # one job per person, never one per document
    for (_, body), s in zip(sender.sent, rows, strict=True):
        assert texts(body) == [f"LABEL {s.order_name}", f"SLIP {s.order_name}"]
    assert b["children"][0]["documents"] == ["Shipping label", "Packing slip"]


def test_international_set_is_label_customs_then_slip(svc, shopify, ops, sender):
    a, b_ = purchased(svc, shopify, 2)
    # Easyship: the CN23 is page 2 of the label file.
    doc = a.label.document(DocumentKind.shipping_label)
    doc.artifact_id = svc.store.put_artifact(
        SHOP, a.id, "shipping_label", "application/pdf", bundle(("LABEL A", "CN23 A"))
    )
    svc.store.save(a)
    # Shopify Shipping: the customs form is its own 4x6 file.
    form = svc.store.put_artifact(
        SHOP, b_.id, "customs_declaration", "application/pdf", bundle(("CN23 B",))
    )
    b_.label.documents.append(
        ShipmentDocument(
            kind=DocumentKind.customs_declaration,
            artifact_id=form,
            page_size=PageSize.label_4x6,
            pages=1,
            copies_required=1,
            must_print=True,
            attach_to_parcel=True,
        )
    )
    svc.store.save(b_)
    out = run(ops, [a, b_])
    assert texts(sender.sent[0][1]) == ["LABEL A", "CN23 A", f"SLIP {a.order_name}"]
    assert texts(sender.sent[1][1]) == [f"LABEL {b_.order_name}", "CN23 B", f"SLIP {b_.order_name}"]
    assert out["children"][1]["documents"] == ["Shipping label", "Customs form", "Packing slip"]


def test_the_next_person_waits_for_the_last_to_come_out(svc, shopify, ops, sender, line):
    rows = purchased(svc, shopify, 3)
    sender.get_job_states.side_effect = [QUEUED, QUEUED, DONE, DONE, DONE]
    run(ops, rows)
    # Job 1000 is polled until done, then its two pages (label + slip) get 4 s each to come
    # out; only then is the next person's set sent.
    assert line.log == [
        "send 1000",
        "sleep 1",
        "sleep 1",
        "sleep 8",
        "send 1001",
        "sleep 8",
        "send 1002",
        "sleep 8",
    ]


def test_a_printer_that_never_finishes_holds_everyone_after(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 3)
    sender.get_job_states.return_value = QUEUED
    b = run(ops, rows)
    assert len(sender.sent) == 1  # nothing piles up behind a stuck job
    first, *rest = b["children"]
    assert first["state"] == "sent"
    assert all(c["state"] == "held" for c in rest)
    assert all("nothing was sent" in c["message"] for c in rest)
    # A held order was never sent, so it may be printed for the first time again.
    for c in rest:
        summary = ops.physical.summary(SHOP, c["shipment_id"])
        assert summary is not None
        assert summary["state"] == "not_printed" and summary["first_print_available"]


def test_a_failed_print_stops_the_rest(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 2)
    sender.get_job_states.return_value = [dict(state="error", at="x", message="Paper out")]
    b = run(ops, rows)
    assert len(sender.sent) == 1
    assert b["children"][0]["state"] == "failed"
    assert b["children"][1]["state"] == "held"


def test_no_slip_means_nothing_prints_for_that_person(svc, shopify, sender, line):
    rows = purchased(svc, shopify, 2)
    svc_ref[:] = [svc]

    def slips(shop, sid):
        if sid == rows[0].id:
            raise PrintError("Shopify didn't answer just now, so the slip can't be made.")
        return slip_for(shop, sid)

    pacer = Pacer(page_s=4, wait_s=30, poll_s=1, sleep=line.sleep, clock=line.clock)
    ops = Operations(svc, PhysicalPrinting(svc.store, sender, 75883753), slips=slips, pacer=pacer)
    b = run(ops, rows)
    assert b["children"][0]["state"] == "failed"
    assert "slip" in b["children"][0]["message"]
    assert len(sender.sent) == 1 and texts(sender.sent[0][1])[0] == f"LABEL {rows[1].order_name}"
    summary = ops.physical.summary(SHOP, rows[0].id)
    assert summary is not None and summary["first_print_available"]


def test_bulk_reprint_sends_each_set_again_without_buying(svc, shopify, ops, sender, provider):
    rows = purchased(svc, shopify, 2)
    charges = len(provider.charges)
    run(ops, rows, key="first")
    again = run(ops, rows, kind="reprint", key="again")
    assert [c["state"] for c in again["children"]] == ["printed", "printed"]
    assert len(sender.sent) == 4
    assert texts(sender.sent[2][1]) == [f"LABEL {rows[0].order_name}", f"SLIP {rows[0].order_name}"]
    assert len(provider.charges) == charges  # nothing bought
    summary = ops.physical.summary(SHOP, rows[0].id)
    assert summary is not None and summary["reprint_count"] == 1


def test_bulk_print_still_refuses_a_second_first_copy(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 1)
    run(ops, rows, key="first")
    b = ops.preview(SHOP, "print", [rows[0].id], "staff", "first-again")
    assert b["children"][0]["state"] == "excluded"


def test_print_view_puts_each_slip_after_its_label(svc, shopify, sender):
    rows = purchased(svc, shopify, 2)
    svc_ref[:] = [svc]
    physical = PhysicalPrinting(svc.store, None, 75883753)
    body, done, skipped = physical.print_view_many(
        SHOP, [s.id for s in rows], "staff", slips=slip_for
    )
    assert texts(body) == [
        f"LABEL {rows[0].order_name}",
        f"SLIP {rows[0].order_name}",
        f"LABEL {rows[1].order_name}",
        f"SLIP {rows[1].order_name}",
    ]
