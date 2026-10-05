"""Durable print intents consume purchased artifacts only; no purchase dependencies."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from shipping.label_selection import select_shipping_label_pdf
from shipping.models import DocumentKind, Event, PageSize
from shipping.print_provider import PrintProvider, PrintProviderError
from shipping.printing import PRINTABLE, PrintError
from shipping.store import Store, new_id, now


def validate_label(body: bytes) -> None:
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted or len(reader.pages) != 1:
            raise ValueError()
        p = reader.pages[0]
        w, h = float(p.mediabox.width) * 25.4 / 72, float(p.mediabox.height) * 25.4 / 72
        if not (98 <= w <= 104 and 148 <= h <= 155) or p.rotation % 360:
            raise ValueError()
        # Cropped / oversized pages must never be scaled into an apparently valid label.
        if list(p.cropbox) != list(p.mediabox):
            raise ValueError()
    except Exception:
        raise PrintError(
            "Use a dedicated single-page portrait 4x6 shipping-label PDF; "
            "combined documents and A4 paperwork cannot go to JD-168BT."
        ) from None


def test_pdf() -> bytes:
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=(288, 432))
    c.rect(9, 9, 270, 414)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(144, 340, "CROOKS SHIPPING")
    c.drawCentredString(144, 305, "PRINTER TEST")
    c.setFont("Helvetica", 12)
    c.drawCentredString(144, 250, "4 x 6 / 203 dpi / one copy")
    c.drawCentredString(144, 220, "No postage purchased")
    c.showPage()
    c.save()
    return stream.getvalue()


class PhysicalPrinting:
    def __init__(self, store: Store, provider: PrintProvider | None, printer_id: int):
        self.store, self.provider, self.printer_id = store, provider, printer_id

    def health(self):
        if self.provider is None:
            return dict(
                enabled=False,
                connected=False,
                name="JD-168BT",
                printer_id=self.printer_id,
                state="disabled",
                detail="Direct printing is not configured on the server",
            )
        return self.provider.health()

    def print_label(
        self, shop: str, sid: str, actor: str, key: str, reprint: bool = False
    ) -> dict[str, Any]:
        s = self.store.get(shop, sid)
        if s is None:
            raise PrintError("Shipment not found.", 404)
        if s.status not in PRINTABLE or s.label is None:
            raise PrintError("No purchased label exists. Printing never buys postage.")
        doc = s.label.document(DocumentKind.shipping_label)
        if not doc or not doc.artifact_id or doc.page_size != PageSize.label_4x6:
            raise PrintError("No stored dedicated 4x6 shipping label is available.")
        artifact = self.store.get_artifact(shop, doc.artifact_id)
        if not artifact or artifact[0] != "shipping_label" or artifact[1] != "application/pdf":
            raise PrintError("The stored shipping-label PDF is unavailable.")
        body = select_shipping_label_pdf(
            artifact[2],
            provider=s.label.provider,
            carrier=s.label.carrier,
            service=s.label.service_name,
            kind=doc.kind,
            page_size=doc.page_size,
        )
        validate_label(body)
        # A second first-print click (even with a different request key) never reprints.
        identity = f"reprint:{key}" if reprint else "first"
        intent_key = hashlib.sha256(f"{sid}:{doc.artifact_id}:{identity}".encode()).hexdigest()
        result = self._send(
            shop,
            intent_key,
            sid,
            s.order_name,
            doc.artifact_id,
            "shipping_label",
            body,
            actor,
            reprint,
        )
        return result

    def test_print(self, shop: str, actor: str, key: str):
        return self._send(
            shop,
            "test:" + key,
            None,
            "Printer test",
            None,
            "printer_test",
            test_pdf(),
            actor,
            False,
        )

    def _send(self, shop, key, sid, order, artifact_id, kind, body, actor, reprint):
        if self.provider is None:
            raise PrintError("Direct printing is disabled. Open PDF is still available.", 503)
        # Cross-process SQLite transaction owns the single submission. No automatic POST
        # retry: a crash or lost response remains uncertain, even past PrintNode's 24h window.
        with self.store.atomic():
            old = self.store.print_intent_by_key(shop, key)
            if old:
                return old
            record = dict(
                id=new_id("prt"),
                shipment_id=sid,
                order_reference=order,
                document_id=artifact_id,
                document_kind=kind,
                document_sha256=hashlib.sha256(body).hexdigest(),
                provider="printnode",
                printer_id=self.printer_id,
                printer_name="JD-168BT",
                provider_job_id=None,
                idempotency_key=new_id("print"),
                copies=1,
                requested_at=now().isoformat(),
                requested_by=actor,
                state="requested",
                provider_state=None,
                error=None,
                last_checked_at=None,
            )
            self.store.add_print_intent(shop, key, record)
        try:
            self.provider.get_printer()
            record["state"] = "submitting"
            self.store.save_print_intent(shop, record)
            jid = self.provider.print_pdf(
                body, f"CROOKS Shipping {order}", record["idempotency_key"]
            )
            record.update(provider_job_id=jid, state="accepted")
        except PrintProviderError as exc:
            record.update(state="unknown" if exc.uncertain else "failed", error=str(exc))
        except Exception:
            record.update(state="unknown", error="Print outcome is uncertain; no automatic retry.")
        self.store.save_print_intent(shop, record)
        if record["state"] == "accepted" and sid:
            # Timeline evidence means submitted, never proof of paper emerging.
            with self.store.atomic():
                current = self.store.get(shop, sid)
                current.timeline.append(
                    Event(
                        at=now(),
                        actor=actor,
                        type="label_reprinted" if reprint else "label_printed",
                        detail={
                            "print_intent": record["id"],
                            "provider_job_id": jid,
                            "evidence": "Sent to printer; physical output unconfirmed",
                        },
                    )
                )
                self.store.save(current)
        return record

    def status(self, shop: str, intent_id: str):
        record = self.store.print_intent(shop, intent_id)
        if record is None:
            raise PrintError("Print intent not found.", 404)
        if record["provider_job_id"] and self.provider:
            try:
                state = self.provider.get_job_status(record["provider_job_id"])
                record.update(provider_state=state, last_checked_at=now().isoformat())
                if state in ("error", "expired"):
                    record.update(
                        state="failed" if state == "error" else "expired",
                        error=f"PrintNode reported {state}; physical output unconfirmed.",
                    )
                self.store.save_print_intent(shop, record)
            except PrintProviderError:
                pass  # Last recorded submission evidence remains valid.
        return record
