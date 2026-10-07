"""Printed means printed: the print view for everyone, PrintNode only when it is connected.

Without PrintNode, Print opens the label as a 4x6 PDF, as Shopify prints labels; opening it is
the print (nothing else can know). With PrintNode, Print sends the job and the order says
"Printing…" until PrintNode reports the printer finished; an error or expiry says why and lets
the label be printed again. Neither path can buy anything.
"""

from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from shipping import lifecycle
from shipping.app import create_app
from shipping.models import DocumentKind, PageSize, ShipmentDocument
from shipping.physical_printing import PhysicalPrinting
from shipping.settings import Settings

from . import test_printing
from .conftest import SHOP
from .test_label_selection import bundle
from .test_printing import bought, trap

shopify = test_printing.shopify
svc = test_printing.svc


def with_label(svc, s, body):
    s = svc.store.get(SHOP, s.id)
    artifact = svc.store.put_artifact(SHOP, s.id, "shipping_label", "application/pdf", body)
    s.label.documents = [
        ShipmentDocument(
            kind=DocumentKind.shipping_label,
            artifact_id=artifact,
            page_size=PageSize.label_4x6,
            pages=len(PdfReader(BytesIO(body)).pages),
        )
    ]
    svc.store.save(s)
    return s


@pytest.fixture
def two(svc, shopify):
    a = with_label(svc, bought(svc, shopify, 2145), bundle(("LABEL 2145",)))
    b = with_label(svc, bought(svc, shopify, 2146), bundle(("LABEL 2146",)))
    return a, b


@pytest.fixture
def printer():
    p = Mock()
    p.print_pdf.side_effect = range(9000, 9100)
    p.get_job_states.return_value = []
    p.describe.return_value = dict(
        reachable=True,
        printer_name="JD-168BT",
        printer_state="online",
        computer_name="CROOKS-PC",
        computer_state="connected",
    )
    p.health.return_value = dict(enabled=True, connected=True, name="JD-168BT", detail="Connected")
    return p


def print_of(physical, s) -> dict:
    out = physical.summary(SHOP, s.id)
    assert out is not None
    return out


def stage(svc, physical, s):
    return lifecycle.stage(svc.store.get(SHOP, s.id), physical.summary(SHOP, s.id))


# ------------------------------------------------------------------ the print view


def test_print_view_opens_the_label_and_counts_as_printed(svc, two, provider, monkeypatch):
    a, _ = two
    trap(provider, monkeypatch)
    view = PhysicalPrinting(svc.store, None, 0)
    assert stage(svc, view, a) == "bought"
    body, note = view.print_view(SHOP, a.id, "Staff (dev)")
    assert note == "" and "LABEL 2145" in PdfReader(BytesIO(body)).pages[0].extract_text()
    summary = print_of(view, a)
    assert summary["state"] == "printed" and summary["via"] == "print view"
    assert stage(svc, view, a) == "printed"
    assert svc.store.get(SHOP, a.id).timeline[-1].type == "label_print_view"
    view.print_view(SHOP, a.id, "Staff (dev)")  # again: a reprint, still nothing bought
    assert print_of(view, a)["reprint_count"] == 1
    assert svc.store.get(SHOP, a.id).timeline[-1].type == "label_print_view_again"


def test_easyship_bundle_opens_as_its_label_page_only(svc, shopify):
    s = bought(svc, shopify, 2147)
    s.label.provider, s.label.carrier = "Easyship", "Royal Mail"
    s.label.service_name = "Royal Mail - Domestic Tracked 48 - Small Parcel"
    svc.store.save(s)
    body = "CUSTOMS DECLARATION CN23May be opened officially"
    s = with_label(svc, s, bundle(("LABEL VU732053366GB", body)))
    out, _ = PhysicalPrinting(svc.store, None, 0).print_view(SHOP, s.id, "staff")
    assert len(PdfReader(BytesIO(out)).pages) == 1  # the CN23 stays in Open PDF


def test_an_unknown_bundle_opens_whole_and_says_so(svc, shopify):
    s = with_label(svc, bought(svc, shopify, 2148), bundle(("PAGE ONE", "PAGE TWO")))
    out, note = PhysicalPrinting(svc.store, None, 0).print_view(SHOP, s.id, "staff")
    assert len(PdfReader(BytesIO(out)).pages) == 2 and "print the label page" in note


def test_bulk_print_view_is_one_pdf_and_names_what_it_left_out(svc, two, shopify):
    a, b = two
    shopify.add(test_printing.fo(2149, [test_printing.tee_line()]))
    svc.sync(SHOP)
    unbought = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2149")
    view = PhysicalPrinting(svc.store, None, 0)
    out, done, skipped = view.print_view_many(SHOP, [b.id, a.id, unbought.id, a.id], "staff")
    pages = [p.extract_text() for p in PdfReader(BytesIO(out)).pages]
    assert done == [b.id, a.id] and "2146" in pages[0] and "2145" in pages[1]  # order kept
    assert skipped == [{"order": "CROOKS-2149", "reason": skipped[0]["reason"]}]
    assert "never buys" in skipped[0]["reason"]
    assert all(stage(svc, view, x) == "printed" for x in (a, b))


def test_admin_print_view_endpoints(svc, two):
    a, b = two
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        d = c.get(f"/admin/api/shipments/{a.id}").json()
        assert d["print_method"] == "print_view" and d["print_connection"]["method"] == "print_view"
        r = c.post(f"/admin/api/shipments/{a.id}/print-view")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert c.get(f"/admin/api/shipments/{a.id}").json()["stage"] == "printed"
        inbox = c.get("/admin/api/inbox?stage=bought").json()
        assert inbox["print_method"] == "print_view"
        assert [r["id"] for r in inbox["rows"] if r["can_first_print"]] == [b.id]
        many = c.post("/admin/api/print-view", json={"shipment_ids": [b.id, "shp_nope"]})
        assert many.status_code == 200 and many.headers["x-print-count"] == "1"
        assert "Left%20out" in many.headers["x-print-note"]  # latin-1 safe header


# ------------------------------------------------------------------ PrintNode


def test_printnode_printing_is_not_printed_until_the_printer_finishes(svc, two, printer):
    a, _ = two
    node = PhysicalPrinting(svc.store, printer, 75883753)
    job = node.print_label(SHOP, a.id, "staff", "press-1")
    assert print_of(node, a)["label"] == "Printing…" and stage(svc, node, a) == "bought"
    printer.get_job_states.return_value = [
        dict(state="sent_to_client", at="2026-10-07T15:25:26Z", message=""),
        dict(state="in_progress", at="2026-10-07T15:25:28Z", message=""),
    ]
    node.status(SHOP, job["id"])
    summary = print_of(node, a)
    assert summary["state"] == "printing"
    assert [x["words"] for x in summary["steps"]] == ["Sent to the printer's computer", "Printing"]
    printer.get_job_states.return_value.append(
        dict(state="done", at="2026-10-07T15:25:31Z", message="")
    )
    node.status(SHOP, job["id"])
    assert print_of(node, a)["state"] == "printed" and stage(svc, node, a) == "printed"
    done = svc.store.get(SHOP, a.id).timeline[-1]
    assert done.type == "label_print_done" and done.verified


@pytest.mark.parametrize("ending", ["error", "expired", "deleted", "disappeared"])
def test_a_job_that_did_not_print_says_why_and_can_print_again(svc, two, printer, ending):
    a, _ = two
    node = PhysicalPrinting(svc.store, printer, 75883753)
    job = node.print_label(SHOP, a.id, "staff", "press-1")
    printer.get_job_states.return_value = [
        dict(state=ending, at="2026-10-07T15:30:00Z", message="Printer offline")
    ]
    node.status(SHOP, job["id"])
    summary = print_of(node, a)
    assert summary["state"] == "failed" and summary["label"] == "Print failed"
    assert "Printer offline" in summary["error"] and summary["first_print_available"]
    assert stage(svc, node, a) == "bought"  # never in Printed
    assert node.print_label(SHOP, a.id, "staff", "press-1")["id"] == job["id"]  # retried reply
    again = node.print_label(SHOP, a.id, "staff", "press-2")  # a new press of Print
    assert again["id"] != job["id"] and printer.print_pdf.call_count == 2
    assert svc.store.get(SHOP, a.id).timeline[-2].type == "label_print_failed"


def test_a_job_never_confirmed_is_said_so_not_called_printed(svc, two, printer, monkeypatch):
    from datetime import timedelta

    from shipping import physical_printing

    a, _ = two
    node = PhysicalPrinting(svc.store, printer, 75883753)
    node.print_label(SHOP, a.id, "staff", "press-1")
    later = physical_printing.now() + timedelta(hours=7)
    monkeypatch.setattr(physical_printing, "now", lambda: later)
    summary = print_of(node, a)
    assert summary["state"] == "unconfirmed" and stage(svc, node, a) == "bought"
    assert not summary["first_print_available"]  # it may have printed: Reprint, on purpose


def test_the_connection_says_which_computer_and_printer(svc, printer):
    c = PhysicalPrinting(svc.store, printer, 75883753).connection()
    assert c["method"] == "printnode" and c["ready"]
    assert (c["printer_name"], c["printer_state"]) == ("JD-168BT", "online")
    assert (c["computer_name"], c["computer_state"]) == ("CROOKS-PC", "connected")
    off = PhysicalPrinting(svc.store, None, 0).connection()
    assert off["method"] == "print_view" and "PrintNode" in off["detail"]


def test_printnode_client_reads_the_job_trail_and_an_offline_computer():
    import httpx

    from shipping.print_provider import PrintNodeProvider

    def answer(req):
        if req.url.path == "/printjobs/7/states":
            return httpx.Response(
                200,
                json=[
                    [
                        dict(printJobId=7, state="new", createTimestamp="2026-10-07T15:25:25Z"),
                        dict(
                            printJobId=7,
                            state="error",
                            createTimestamp="2026-10-07T15:25:40Z",
                            message="Paper jam",
                        ),
                    ]
                ],
            )
        return httpx.Response(
            200,
            json=[
                dict(
                    id=75883753,
                    name="JD-168BT",
                    state="online",
                    computer=dict(id=1, name="CROOKS-PC", state="disconnected"),
                )
            ],
        )

    p = PrintNodeProvider("test", 75883753, transport=httpx.MockTransport(answer))
    trail = p.get_job_states(7)
    assert [x["state"] for x in trail] == ["new", "error"] and trail[-1]["message"] == "Paper jam"
    assert p.get_job_status(7) == "error"
    seen = p.describe()
    assert seen["computer_state"] == "disconnected" and seen["computer_name"] == "CROOKS-PC"
    assert not p.health()["connected"]  # the reason is shown, not just "unavailable"
