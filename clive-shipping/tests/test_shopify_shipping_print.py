"""Shopify Shipping labels print like every other label: the stored file, whole, through the
print view or PrintNode, singly or in bulk. A file that isn't a 4x6 label is said to be what it
is and never scaled; a label whose file couldn't be fetched says where to print it."""

from __future__ import annotations

from io import BytesIO
from typing import cast
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

from shipping.fake_shopify import label_pdf
from shipping.models import DocumentKind, PageSize
from shipping.operations import Operations
from shipping.physical_printing import PhysicalPrinting
from shipping.printing import PrintError, Printing

from .conftest import SHOP
from .test_shopify_shipping import World, label_of


@pytest.fixture
def w(store, clock) -> World:
    return World(store, clock)


@pytest.fixture
def sender():
    p = Mock()
    p.print_pdf.side_effect = range(100, 120)
    return p


def bought(w: World, n: int = 3001):
    s = w.ready(n=n)
    assert w.buy(s, key=f"k{n}")["charged"]
    return w.get(s.id)


def test_a_4x6_shopify_label_prints_whole_through_the_print_view_and_printnode(w, sender):
    s, other = bought(w, 3001), bought(w, 3002)
    printer = PhysicalPrinting(w.store, sender, 75883753)
    body, note = printer.print_view(SHOP, other.id, "george")
    assert body == w.ss.label_file and note == ""  # the stored file as Shopify made it
    intent = printer.print_label(SHOP, s.id, "george", "print-1")
    assert intent["state"] == "accepted" and sender.print_pdf.call_count == 1
    assert sender.print_pdf.call_args.args[0] == w.ss.label_file
    jobs = Printing(w.store).jobs(w.get(s.id))
    assert [(j.kind, j.printer.value) for j in jobs] == [("shipping_label", "label")]
    assert len(w.ss.purchases) == 2  # one per order: printing never bought anything


def test_bulk_print_view_puts_several_labels_in_one_pdf(w):
    a, b = bought(w, 3001), bought(w, 3002)
    out, done, skipped = PhysicalPrinting(w.store, None, 1).print_view_many(
        SHOP, [a.id, b.id], "george"
    )
    assert done == [a.id, b.id] and skipped == []
    assert len(PdfReader(BytesIO(out)).pages) == 2


@pytest.mark.parametrize(
    ("size", "words"),
    [((612, 792), "US Letter"), ((595, 842), "A4"), ((432, 288), "4×6 (landscape)")],
)
def test_a_label_that_isnt_4x6_says_what_it_is_and_is_never_scaled(w, sender, size, words):
    w.ss.label_file = label_pdf(*size)
    s = bought(w)
    doc = label_of(s).document(DocumentKind.shipping_label)
    assert doc is not None and doc.page_size != PageSize.label_4x6
    assert f"file is {words}, not 4×6" in doc.note and "isn't scaled" in doc.note
    printer = PhysicalPrinting(w.store, sender, 75883753)
    with pytest.raises(PrintError, match="not 4×6"):
        printer.print_label(SHOP, s.id, "george", "print-1")
    sender.print_pdf.assert_not_called()
    body, note = printer.print_view(SHOP, s.id, "george")
    assert body == w.ss.label_file and note == doc.note  # whole and unchanged, with why


def test_a_label_bought_after_a_lost_reply_says_where_to_print_it(w, sender):
    s = w.ready()
    w.ss.lose_reply = True
    w.buy(s)
    s = w.get(s.id)
    assert label_of(s).file_note
    printer = PhysicalPrinting(w.store, sender, 75883753)
    for attempt in (
        lambda: printer.print_view(SHOP, s.id, "george"),
        lambda: printer.print_label(SHOP, s.id, "george", "print-1"),
        lambda: Printing(w.store).jobs(s),
    ):
        with pytest.raises(PrintError, match="Print it from the order in Shopify admin"):
            attempt()
    sender.print_pdf.assert_not_called()


def test_a_zpl_label_is_kept_and_said_to_be_unprintable_here(w):
    w.ss.file_format, w.ss.label_file = "ZPL", b"^XA^FO50,50^FDTEST^FS^XZ"
    s = bought(w)
    doc = label_of(s).document(DocumentKind.shipping_label)
    assert doc is not None and doc.artifact_id and "as ZPL, not PDF" in doc.note
    with pytest.raises(PrintError, match="as ZPL"):
        PhysicalPrinting(w.store, None, 1).print_view(SHOP, s.id, "george")


def test_bulk_buy_then_bulk_print_through_printnode(w, sender):
    a, b = w.ready(n=3001), w.ready(n=3002)
    ops = Operations(w.svc, PhysicalPrinting(w.store, sender, 75883753))
    review = ops.preview(SHOP, "buy", [a.id, b.id], "george", "bulk-buy-1")
    children = cast(list[dict], review["children"])
    assert [c["state"] for c in children] == ["review", "review"]
    assert all(c["price_known"] is False and c["provider"] == "Shopify Shipping"
               for c in children)  # fmt: skip
    ops.confirm(SHOP, review["id"], "george")
    ops.run(SHOP, review["id"])
    done = ops.get(SHOP, review["id"])
    assert [c["state"] for c in done["children"]] == ["purchased", "purchased"]
    assert len(w.ss.purchases) == 2 and w.ss.labels_bought == 2

    review = ops.preview(SHOP, "print", [a.id, b.id], "george", "bulk-print-1")
    ops.confirm(SHOP, review["id"], "george")
    ops.run(SHOP, review["id"])
    assert [c["state"] for c in ops.get(SHOP, review["id"])["children"]] == ["sent", "sent"]
    assert sender.print_pdf.call_count == 2
    assert all(call.args[0] == w.ss.label_file for call in sender.print_pdf.call_args_list)
    assert len(w.ss.purchases) == 2
