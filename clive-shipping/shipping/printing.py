"""Printing: what to print for a bought label, made only from what is already stored.

This module can't buy anything. It reads stored shipments and stored document files and records
that a print happened; it holds no provider and no purchase code (a test keeps it that way). A
print or reprint of an order without a label is refused, never turned into a purchase.

A print is described as jobs: plain data naming the printer role (the 4x6 label printer or the
A4 printer), the stored file and the copies. The embedded admin prints them in the browser
today; a PrintNode sender can take the same jobs later, for "CLIVE, reprint order 2145" or
"print all 9 ready international labels", without touching the purchase path.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from shipping.models import (
    DocumentKind,
    Event,
    PageSize,
    Shipment,
    ShipmentDocument,
    ShipmentStatus,
)
from shipping.store import Conflict, Store, now

log = logging.getLogger("shipping.printing")

# Statuses where a label exists and may be printed.
PRINTABLE = (
    ShipmentStatus.label_purchased,
    ShipmentStatus.fulfillment_failed,
    ShipmentStatus.fulfilled,
    ShipmentStatus.in_transit,
)
PRINT_EVENTS = ("label_printed", "label_reprinted", "label_print_view", "label_print_view_again")

TITLES = {
    DocumentKind.shipping_label: "Shipping label",
    DocumentKind.commercial_invoice: "Commercial invoice",
    DocumentKind.customs_declaration: "Customs declaration",
    DocumentKind.other_documents: "Other documents",
}


class PrinterRole(StrEnum):
    label = "label"  # the 4x6 thermal printer (JADENS)
    document = "document"  # an A4 desk printer


class PrintError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class PrintJob:
    shipment_id: str
    order_name: str
    artifact_id: str
    kind: str
    title: str
    printer: PrinterRole
    copies: int
    page_size: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def printed(s: Shipment) -> bool:
    return any(e.type in PRINT_EVENTS for e in s.timeline)


def order_number(ref: str) -> str:
    """ "2145", "#2145", "CROOKS-2145", "order 2145" -> "2145"."""
    found = re.findall(r"\d+", ref or "")
    return found[-1] if found else ""


def _printer(doc: ShipmentDocument) -> PrinterRole:
    return PrinterRole.label if doc.page_size == PageSize.label_4x6 else PrinterRole.document


class Printing:
    def __init__(self, store: Store, clock: Callable[[], datetime] = now) -> None:
        self.store = store
        self.clock = clock

    def _get(self, shop: str, sid: str) -> Shipment:
        s = self.store.get(shop, sid)
        if s is None:
            raise PrintError("Shipment not found.", 404)
        return s

    def jobs(self, s: Shipment) -> list[PrintJob]:
        """The stored documents to print for this shipment: the label once, and each
        customs document that must go with the parcel, as many copies as it needs."""
        if s.status not in PRINTABLE or s.label is None:
            raise PrintError(
                f"{s.order_name} has no bought label to print. Printing never buys one: buy the "
                "label first."
            )
        out = []
        for doc in s.label.documents:
            if not doc.artifact_id:
                continue  # e.g. customs filed electronically: nothing to print
            if doc.kind == DocumentKind.shipping_label:
                copies = 1
            elif doc.must_print:
                copies = max(doc.copies_required, 1)
            else:
                continue  # kept for the record only
            out.append(
                PrintJob(
                    shipment_id=s.id,
                    order_name=s.order_name,
                    artifact_id=doc.artifact_id,
                    kind=doc.kind.value,
                    title=TITLES.get(doc.kind, doc.kind.value),
                    printer=_printer(doc),
                    copies=copies,
                    page_size=doc.page_size.value,
                )
            )
        if not any(j.kind == DocumentKind.shipping_label.value for j in out):
            raise PrintError(
                f"The label file for {s.order_name} isn't stored yet. CLIVE is fetching it; try "
                "again in a minute.",
                503,
            )
        return out

    def print_shipment(self, shop: str, sid: str, actor: str) -> list[PrintJob]:
        """Print (the first time) or reprint (after that) one shipment's documents."""
        s = self._get(shop, sid)
        jobs = self.jobs(s)
        self._record(shop, sid, actor, "label_reprinted" if printed(s) else "label_printed", jobs)
        return jobs

    def find_order(self, shop: str, ref: str) -> Shipment:
        """The shipment for an order number, for "reprint order 2145"."""
        number = order_number(ref)
        found = [
            s
            for s in self.store.shipments(shop)
            if number and order_number(s.order_name) == number and s.label is not None
        ]
        if not found:
            raise PrintError(f"No bought label for order {ref}.", 404)
        return max(found, key=lambda s: s.updated_at)

    def ready(self, shop: str) -> list[Shipment]:
        """Bought labels nobody has printed yet, oldest first."""
        return sorted(
            (
                s
                for s in self.store.shipments(shop, [x.value for x in PRINTABLE])
                if s.label is not None and not printed(s)
            ),
            key=lambda s: (s.label.purchased_at if s.label else s.created_at, s.order_name),
        )

    def print_ready(self, shop: str, actor: str) -> tuple[list[PrintJob], list[dict[str, str]]]:
        """Every unprinted label, as one batch ("print all 9 ready labels"). Returns the jobs
        and the orders left out, with why (e.g. the label file isn't stored yet); those stay in
        the ready list."""
        out: list[PrintJob] = []
        skipped: list[dict[str, str]] = []
        for s in self.ready(shop):
            try:
                out.extend(self.print_shipment(shop, s.id, actor))
            except PrintError as exc:
                log.warning("print all: %s left out: %s", s.order_name, exc)
                skipped.append({"order": s.order_name, "reason": str(exc)})
        return out, skipped

    def document(self, shop: str, artifact_id: str) -> tuple[str, bytes]:
        """A stored document's bytes, for this shop only."""
        found = self.store.get_artifact(shop, artifact_id)
        if found is None:
            raise PrintError("Document not found.", 404)
        _, content_type, body = found
        return content_type, body

    def _record(self, shop: str, sid: str, actor: str, kind: str, jobs: list[PrintJob]) -> None:
        detail = {"documents": [f"{j.title} ×{j.copies}" for j in jobs]}
        for _ in range(3):
            s = self._get(shop, sid)
            s.timeline.append(Event(at=self.clock(), type=kind, actor=actor, detail=detail))
            try:
                self.store.save(s)
                return
            except Conflict:
                continue  # saved meanwhile (a sync, a reconcile): add ours to the fresh copy
        log.warning("print of %s not recorded: the shipment kept changing", sid)
        raise PrintError("This order is being updated; print again in a moment.")
