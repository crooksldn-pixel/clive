"""Durable print intents consume purchased artifacts only; no purchase dependencies."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from shipping.label_selection import MAX_PARCEL_PAGES, label_page, parcel_label_pdf
from shipping.models import DocumentKind, Event, PageSize
from shipping.print_provider import PrintProvider, PrintProviderError
from shipping.printing import PRINTABLE, PrintError
from shipping.store import Store, new_id, now


def validate_label(body: bytes) -> None:
    """Only portrait 4x6 pages, as made (never scaled, cropped or turned), go to the label
    printer: the shipping label and any customs form that goes on the parcel with it."""
    try:
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PARCEL_PAGES:
            raise ValueError()
        if not all(label_page(p) for p in reader.pages):
            raise ValueError()
    except Exception:
        raise PrintError(
            "Use a portrait 4x6 label PDF (the label and its customs form); "
            "A4 paperwork cannot go to JD-168BT."
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


# PrintNode job states (GET /printjobs/{id}/states). Only "done" means the printer's computer
# finished the job; until then it is printing, and these end it without a print.
PRINTNODE_DONE = "done"
PRINTNODE_FAILED = ("error", "expired", "deleted", "disappeared")
PRINTNODE_WORDS = {
    "new": "Sent to PrintNode",
    "sent_to_client": "Sent to the printer's computer",
    "queued": "Queued on the printer's computer",
    "in_progress": "Printing",
    "done": "Printer finished the job",
    "error": "The printer's computer reported an error",
    "expired": "Expired: the printer's computer never collected it",
    "deleted": "Deleted before it printed",
    "disappeared": "Lost by the printer's computer",
}
UNCONFIRMED_AFTER = timedelta(hours=6)  # still not "done": say so, never call it printed
PRINT_VIEW = "print_view"


def _iso(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def intent_state(p: dict[str, Any]) -> str:
    """One print attempt, in words a person acts on: printed, printing, failed, unknown,
    unconfirmed."""
    if p.get("provider") == PRINT_VIEW:
        return "printed"
    if p["state"] in ("failed", "expired") or p.get("provider_state") in PRINTNODE_FAILED:
        return "failed"
    if p["state"] == "unknown":
        return "unknown"
    if p["state"] in ("requested", "submitting"):
        started = _iso(p.get("requested_at"))
        stale = started is not None and now() - started > timedelta(minutes=5)
        return "unknown" if stale else "sending"  # interrupted: never safe to resend by itself
    if p.get("provider_state") == PRINTNODE_DONE:
        return "printed"
    sent = _iso(p.get("sent_at") or p.get("requested_at"))
    if sent is not None and now() - sent > UNCONFIRMED_AFTER:
        return "unconfirmed"
    return "printing"


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

    def _label_input(self, shop: str, sid: str):
        s = self.store.get(shop, sid)
        if s is None:
            raise PrintError("Shipment not found.", 404)
        if s.status not in PRINTABLE or s.label is None:
            raise PrintError("No purchased label exists. Printing never buys postage.")
        if s.label.file_note:  # bought, but its file can't be fetched here (it says where)
            raise PrintError(s.label.file_note)
        doc = s.label.document(DocumentKind.shipping_label)
        if doc and doc.artifact_id and doc.page_size != PageSize.label_4x6 and doc.note:
            # The provider's file isn't a 4x6 label (e.g. Shopify's set to Letter): say so; it
            # is never scaled to fit the label printer.
            raise PrintError(doc.note)
        if not doc or not doc.artifact_id or doc.page_size != PageSize.label_4x6:
            raise PrintError("No stored dedicated 4x6 shipping label is available.")
        artifact = self.store.get_artifact(shop, doc.artifact_id)
        if not artifact or artifact[0] != "shipping_label" or artifact[1] != "application/pdf":
            raise PrintError("The stored shipping-label PDF is unavailable.")
        body = parcel_label_pdf(artifact[2], kind=doc.kind, page_size=doc.page_size)
        validate_label(body)
        return s, doc, body

    def validate_for_print(self, shop: str, sid: str) -> None:
        self._label_input(shop, sid)

    def print_label(
        self, shop: str, sid: str, actor: str, key: str, reprint: bool = False
    ) -> dict[str, Any]:
        s, doc, body = self._label_input(shop, sid)
        mine = [
            p
            for p in self.store.print_intents_for(shop, sid)
            if p["document_id"] == doc.artifact_id
        ]
        # The same request again (a lost reply, a retry) is answered from its record, never sent.
        again = next(
            (p for p in mine if p.get("client_key") == key and bool(p.get("reprint")) == reprint),
            None,
        )
        if again is not None:
            return again
        # A second first-print click (even with a different request key) never prints twice.
        # Only a print that definitely didn't happen (PrintNode error / expired) frees the next
        # first print, and every click after that one failure agrees on the same identity.
        failed = sum(1 for p in mine if not p.get("reprint") and intent_state(p) == "failed")
        identity = f"reprint:{key}" if reprint else ("first" if not failed else f"first:{failed}")
        intent_key = hashlib.sha256(f"{sid}:{doc.artifact_id}:{identity}".encode()).hexdigest()
        same = self.store.print_intent_by_key(shop, intent_key)  # this very first print: replays
        if not reprint and any(
            p["id"] != (same or {}).get("id") and intent_state(p) != "failed" for p in mine
        ):
            # A reprint printed (or is printing) after the first one failed: "print" from a stale
            # tab or CLIVE is not another copy. Reprint is the deliberate way.
            raise PrintError("This label has already been sent to the printer. Use Reprint.", 409)
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
            client_key=key,
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

    def _send(
        self, shop, key, sid, order, artifact_id, kind, body, actor, reprint, client_key=None
    ):
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
                reprint=reprint,
                client_key=client_key,
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
            record.update(provider_job_id=jid, state="accepted", sent_at=now().isoformat())
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
        if record.get("provider_job_id") and self.provider:
            before = intent_state(record)
            try:
                states = self.provider.get_job_states(record["provider_job_id"])
            except PrintProviderError:
                return record  # Last recorded submission evidence remains valid.
            state = (states[-1]["state"] if states else "") or "accepted"
            record.update(
                provider_state=state, provider_states=states, last_checked_at=now().isoformat()
            )
            if state in PRINTNODE_FAILED:
                why = states[-1].get("message") or PRINTNODE_WORDS.get(state, state)
                record.update(
                    state="failed" if state != "expired" else "expired",
                    error=f"PrintNode: {why}. Nothing was printed; print it again.",
                )
            self.store.save_print_intent(shop, record)
            after = intent_state(record)
            if after != before and after in ("printed", "failed") and record.get("shipment_id"):
                self._note(
                    shop,
                    record["shipment_id"],
                    "label_print_done" if after == "printed" else "label_print_failed",
                    {
                        "print_intent": record["id"],
                        "provider_job_id": record["provider_job_id"],
                        "printer": record.get("printer_name"),
                        "why": record.get("error") if after == "failed" else None,
                    },
                    verified=True,
                )
        return record

    def _note(self, shop, sid, kind, detail, verified=False, actor="PrintNode"):
        with self.store.atomic():
            current = self.store.get(shop, sid)
            if current is None:
                return
            current.timeline.append(
                Event(at=now(), actor=actor, type=kind, detail=detail, verified=verified)
            )
            self.store.save(current)

    # ------------------------------------------------------------------ the print view

    def print_view(self, shop: str, sid: str, actor: str) -> tuple[bytes, str]:
        """The label as a 4x6 PDF to print from the browser, as Shopify's own labels print.
        Recorded as printed when opened: nothing more can be known without PrintNode."""
        body, note = self._view_body(shop, sid)
        self._record_view(shop, sid, actor)
        return body, note

    def print_view_many(
        self, shop: str, sids: list[str], actor: str
    ) -> tuple[bytes, list[str], list[dict[str, str]]]:
        """Several labels as one PDF, in the order given, for one print. Orders that can't print
        are left out and named."""
        writer = PdfWriter()
        done: list[str] = []
        skipped: list[dict[str, str]] = []
        for sid in dict.fromkeys(sids):
            try:
                body, _ = self._view_body(shop, sid)
                for page in PdfReader(BytesIO(body)).pages:
                    writer.add_page(page)
                done.append(sid)
            except PrintError as exc:
                s = self.store.get(shop, sid)
                skipped.append({"order": s.order_name if s else sid, "reason": str(exc)})
        if not done:
            raise PrintError("None of these labels can be printed.", 409)
        for sid in done:
            self._record_view(shop, sid, actor)
        out = BytesIO()
        writer.write(out)
        return out.getvalue(), done, skipped

    def _view_body(self, shop: str, sid: str) -> tuple[bytes, str]:
        s = self.store.get(shop, sid)
        if s is None:
            raise PrintError("Shipment not found.", 404)
        if s.status not in PRINTABLE or s.label is None:
            raise PrintError("No purchased label exists. Printing never buys postage.")
        if s.label.file_note:
            raise PrintError(s.label.file_note)
        doc = s.label.document(DocumentKind.shipping_label)
        artifact = (
            self.store.get_artifact(shop, doc.artifact_id) if doc and doc.artifact_id else None
        )
        if doc and artifact and artifact[1] != "application/pdf" and doc.note:
            raise PrintError(doc.note)  # e.g. Shopify gave the label as ZPL
        if not doc or not artifact or artifact[1] != "application/pdf":
            raise PrintError("The label file isn't stored yet; try again in a minute.", 503)
        try:
            body = self._label_input(shop, sid)[2]
            pages = len(PdfReader(BytesIO(body)).pages)
            return body, "" if pages == 1 else (
                f"{pages} labels: the shipping label and its customs form. Print both; both go "
                "on the parcel."
            )
        except PrintError:
            # Not all 4x6 label pages (e.g. A4 paperwork in it, or Shopify's label set to
            # Letter): the whole original, unscaled, so nothing on it is lost.
            return artifact[2], doc.note or (
                "The label file isn't all 4×6 pages, so it is shown whole: print every page "
                "that goes on the parcel."
            )

    def _record_view(self, shop: str, sid: str, actor: str) -> None:
        s = self.store.get(shop, sid)
        assert s is not None and s.label is not None
        doc = s.label.document(DocumentKind.shipping_label)
        assert doc is not None
        again = any(
            intent_state(p) == "printed"
            for p in self.store.print_intents_for(shop, sid)
            if p["document_id"] == doc.artifact_id
        )
        at, rid = now().isoformat(), new_id("prt")
        record = dict(
            id=rid,
            shipment_id=sid,
            order_reference=s.order_name,
            document_id=doc.artifact_id,
            document_kind="shipping_label",
            provider=PRINT_VIEW,
            printer_name="this device",
            provider_job_id=None,
            reprint=again,
            requested_at=at,
            sent_at=at,
            requested_by=actor,
            state="opened",
            provider_state=None,
            error=None,
        )
        with self.store.atomic():
            self.store.add_print_intent(shop, "view:" + rid, record)
        self._note(
            shop,
            sid,
            "label_print_view_again" if again else "label_print_view",
            {"print_intent": rid},
            actor=actor,
        )

    # ------------------------------------------------------------------ the connection

    def connection(self) -> dict[str, Any]:
        """How labels print here, and what PrintNode says right now."""
        if self.provider is None:
            return dict(
                method=PRINT_VIEW,
                title="Print view",
                detail="Print opens the label as a 4x6 PDF; print it from your browser to your "
                "label printer. Connect PrintNode to send labels straight to the printer.",
            )
        cached = getattr(self, "_seen", None)
        if cached and now() - cached[0] < timedelta(seconds=30):
            return cached[1]  # order pages don't each wait on PrintNode
        seen = self.provider.describe()
        health = self.health()
        out = dict(
            method="printnode",
            title="PrintNode",
            ready=bool(health.get("connected")),
            detail=health.get("detail"),
            printer_name=seen.get("printer_name") or health.get("name"),
            printer_state=seen.get("printer_state"),
            computer_name=seen.get("computer_name"),
            computer_state=seen.get("computer_state"),
            checked_at=now().isoformat(),
        )
        self._seen = (now(), out)
        return out

    def summary(self, shop: str, sid: str) -> dict[str, Any] | None:
        s = self.store.get(shop, sid)
        if s is None or s.label is None:
            return None
        doc = s.label.document(DocumentKind.shipping_label)
        intents = [
            p
            for p in self.store.print_intents_for(shop, sid)
            if doc and p["document_id"] == doc.artifact_id
        ]
        legacy_reprints = {
            e.detail.get("print_intent") for e in s.timeline if e.type == "label_reprinted"
        }
        for p in intents:
            p["reprint"] = p.get("reprint", p["id"] in legacy_reprints)
            p["outcome"] = intent_state(p)
        printed = [p for p in intents if p["outcome"] == "printed"]
        last = intents[-1] if intents else None
        # Printed once is printed: a later reprint that failed doesn't undo the first.
        state = "printed" if printed else (last["outcome"] if last else "not_printed")
        sent = [p for p in intents if p.get("provider_job_id") or p.get("provider") == PRINT_VIEW]
        shown = printed[-1] if printed else last
        via = None
        if shown:
            via = (
                "print view"
                if shown.get("provider") == PRINT_VIEW
                else f"PrintNode → {shown.get('printer_name') or 'printer'}"
            )
        return dict(
            state=state,
            label={
                "not_printed": "Not printed",
                "sending": "Sending to printer",
                "printing": "Printing…",
                "printed": "Printed",
                "failed": "Print failed",
                "unknown": "Print uncertain",
                "unconfirmed": "Not confirmed by printer",
            }[state],
            tone={
                "not_printed": "warning",
                "sending": "info",
                "printing": "info",
                "printed": "success",
                "failed": "critical",
                "unknown": "critical",
                "unconfirmed": "warning",
            }[state],
            via=via,
            printed_at=(printed[0].get("sent_at") or printed[0]["requested_at"])
            if printed
            else None,
            error=last.get("error") if last and last["outcome"] in ("failed", "unknown") else None,
            last_attempt=last["requested_at"] if last else None,
            last_sent=(sent[-1].get("sent_at") or sent[-1]["requested_at"]) if sent else None,
            reprint_count=sum(bool(p["reprint"]) for p in sent),
            intent_id=last["id"] if last else None,
            job_id=last.get("provider_job_id") if last else None,
            # A label may go to the printer "for the first time" until one attempt might have
            # printed: none yet, or every one definitely failed.
            first_print_available=all(p["outcome"] == "failed" for p in intents),
            steps=[
                dict(
                    state=x.get("state"),
                    at=x.get("at"),
                    words=PRINTNODE_WORDS.get(x.get("state") or "", x.get("state")),
                    message=x.get("message") or "",
                )
                for x in (last.get("provider_states") or [])
            ]
            if last
            else [],
            history=[
                dict(
                    at=p["requested_at"],
                    state=p["outcome"],
                    via="print view" if p.get("provider") == PRINT_VIEW else "PrintNode",
                    reprint=p["reprint"],
                    job_id=p.get("provider_job_id"),
                    error=p.get("error"),
                )
                for p in intents
            ],
        )
