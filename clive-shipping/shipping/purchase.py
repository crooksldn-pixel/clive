"""Buying a label: preview, authorise, execute, reconcile. The money boundary.

Rules this module guarantees (each one has a test):

1. Nothing is bought without a preview's basis: if the order, address, package, service or
   price changed since the preview, the buy is refused as STALE and nothing is sent.
2. The ledger row is written before any provider call, and every step is saved before the
   call that might spend money. A crash at any point leaves a row that says what may have
   happened.
3. At most one buy is open per shipment (a unique index, not just a lock).
4. The pay call is made at most once per provider order, ever. Paying twice charges twice
   (Parcel2Go sandbox, 2026-10-04).
5. When a payment's outcome is unknown, the order is read back from the provider. Paid means
   carry on. "Unpaid" is believed only after two reads at least `confirm_unpaid_after` apart,
   and then that order is abandoned for good: never paid. A fresh buy needs a fresh preview.
6. The same idempotency key replays the stored outcome; it never starts a second purchase.
7. We never pay more than the person authorised: a provider order priced above the
   authorised amount is left unpaid.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from shipping.basis import basis
from shipping.models import (
    CustomsMode,
    DocumentKind,
    Label,
    OpState,
    ProviderOp,
    Quote,
    Shipment,
    ShipmentDocument,
)
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.providers.base import (
    ProviderError,
    ProviderRefused,
    ProviderUnavailable,
    ProviderUncertain,
    ShippingProvider,
)
from shipping.states import move
from shipping.store import Conflict, OpenOperationExists, Store, new_id, now

log = logging.getLogger("shipping.purchase")


class ActionError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class Stale(ActionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 409, "stale")


NOT_READY = {
    S.needs_attention: "This order needs a detail before a label can be bought.",
    S.purchasing: "A label for this order is being bought right now.",
    S.reconciliation_required: (
        "We're checking whether the label was bought. Don't buy again: CLIVE is confirming "
        "with the provider so you're not charged twice."
    ),
}


class Purchases:
    def __init__(
        self,
        store: Store,
        provider: ShippingProvider,
        clock: Callable[[], datetime] = now,
        confirm_unpaid_after: timedelta = timedelta(minutes=2),
        # Must exceed the longest provider call (httpx: 10 s connect + 30 s read), so a
        # sweep never mistakes a request still in flight for an interrupted one.
        interrupted_after: timedelta = timedelta(minutes=5),
        escalate_after: timedelta = timedelta(hours=1),
        confirm_paperless_after: timedelta = timedelta(minutes=2),
    ) -> None:
        self.store = store
        self.provider = provider
        self.clock = clock
        self.confirm_unpaid_after = confirm_unpaid_after
        self.interrupted_after = interrupted_after
        self.escalate_after = escalate_after
        self.confirm_paperless_after = confirm_paperless_after

    # ------------------------------------------------------------------ helpers

    def _get(self, shop: str, shipment_id: str) -> Shipment:
        s = self.store.get(shop, shipment_id)
        if s is None:
            raise ActionError("Shipment not found.", 404)
        return s

    def _who(self, op: ProviderOp | None = None, quote: Quote | None = None) -> str:
        """The provider this order or price belongs to, for messages and the label."""
        q = quote or (op.quote if op is not None else None)
        return q.provider if q is not None and q.provider else self.provider.name

    def _basis(self, s: Shipment) -> str:
        """The fingerprint, including the shop's sender details the provider is sent."""
        return basis(s, self.store.config(s.shop))

    def _require_ready(self, s: Shipment) -> None:
        if s.status != S.ready:
            raise ActionError(
                NOT_READY.get(s.status, f"A label can't be bought while this is {s.status.value}.")
            )
        if s.quote is None or s.package is None:
            raise ActionError("Choose a package and a service first.")

    def _exact_price(self, s: Shipment) -> int:
        who = self._who(quote=s.quote)
        try:
            return self.provider.verify(s, s.quote)
        except ProviderRefused as exc:
            raise ActionError(
                f"{who} won't take this parcel as it stands: {exc}. Nothing was bought.",
                422,
                "provider_refused",
            ) from exc
        except ProviderError as exc:
            raise ActionError(
                f"Couldn't get the exact price from {who} ({exc}). Nothing was bought; try "
                "again in a minute.",
                503,
                "provider_unavailable",
            ) from exc

    def _event(self, s: Shipment, kind: str, actor: str, detail: dict | None = None, **kw) -> None:
        from shipping.models import Event

        s.timeline.append(Event(at=self.clock(), type=kind, actor=actor, detail=detail or {}, **kw))

    # ------------------------------------------------------------------ preview

    def preview(self, shop: str, shipment_id: str) -> dict[str, Any]:
        s = self._get(shop, shipment_id)
        self._require_ready(s)
        exact = self._exact_price(s)
        if exact != s.quote.amount.minor:
            was = s.quote.amount
            s.quote = s.quote.model_copy(
                update={"amount": Money(minor=exact, currency=was.currency)}
            )
            # The list of services shows the same price as the preview.
            s.rates = [s.quote if r.service_code == s.quote.service_code else r for r in s.rates]
            self._event(s, "price_updated", "system", {"was": str(was), "now": str(s.quote.amount)})
            try:
                self.store.save(s)
            except Conflict as exc:
                raise ActionError(
                    "This order changed while the price was being checked. Look at it again.",
                    409,
                    "stale",
                ) from exc
        q, p = s.quote, s.package
        value = sum((ln.unit_value.minor * ln.quantity for ln in s.lines), 0)
        return {
            "will": [
                f"Buy {q.title} for {q.amount} from {self._who(quote=q)}",
                f"Parcel {p.length_mm // 10}×{p.width_mm // 10}×{p.height_mm // 10} cm, "
                f"{p.total_weight_g / 1000:.2f} kg",
                f"Customs: {sum(ln.quantity for ln in s.lines)} items, value "
                f"{Money(minor=value, currency=s.currency)}",
                f"Store the label and customs documents for {s.order_name}",
            ],
            "money": {"shipping_minor": q.amount.minor, "currency": q.amount.currency},
            "service": {
                "carrier": q.carrier,
                "name": q.service_name,
                "days": [q.est_days_min, q.est_days_max],
            },
            "basis": self._basis(s),
        }

    # ------------------------------------------------------------------ execute

    def buy(
        self, shop: str, shipment_id: str, basis_token: str, actor: str, key: str
    ) -> dict[str, Any]:
        if not key:
            raise ActionError("An idempotency key is required.", 422)
        with self.store.lock:
            done = self.store.op_by_key(shop, key)
            if done is not None:
                if done.shipment_id != shipment_id:
                    raise ActionError("That idempotency key belongs to another shipment.", 422)
                return self._result(done, replayed=True)
            s = self._get(shop, shipment_id)
            if self.store.open_op(shop, shipment_id) is not None:
                raise ActionError(
                    NOT_READY.get(s.status, "A purchase for this order is already in progress.")
                )
            self._require_ready(s)
            if basis_token != self._basis(s):
                raise Stale(
                    "This order changed since you saw the price. Nothing was bought; check it "
                    "again before buying."
                )
        exact = self._exact_price(s)
        if exact != s.quote.amount.minor:
            raise Stale(
                f"The price changed from {s.quote.amount} to "
                f"{Money(minor=exact, currency=s.quote.amount.currency)}. Nothing was bought."
            )
        with self.store.atomic():  # the operation and "purchasing" are written together
            s = self._get(shop, shipment_id)
            self._require_ready(s)
            if basis_token != self._basis(s):
                raise Stale("This order changed a moment ago. Nothing was bought.")
            at = self.clock()
            op = ProviderOp(
                id=new_id("op"),
                shop=shop,
                shipment_id=shipment_id,
                idempotency_key=key,
                basis=basis_token,
                actor=actor,
                amount=s.quote.amount,
                quote=s.quote,
                state=OpState.authorised,
                created_at=at,
                updated_at=at,
            )
            try:
                self.store.add_op(op)
            except OpenOperationExists as exc:
                raise ActionError("A purchase for this order is already in progress.") from exc
            s.last_error = None
            move(
                s,
                S.purchasing,
                at=at,
                actor=actor,
                event="purchase_authorised",
                detail={
                    "operation": op.id,
                    "amount": str(op.amount),
                    "service": s.quote.title,
                },
            )
            self.store.save(s)
        self._advance(op)
        return self._result(self.store.op_by_key(shop, key) or op)

    # ------------------------------------------------------------------ the protocol

    def _save_op(self, op: ProviderOp) -> None:
        op.updated_at = self.clock()
        self.store.save_op(op)  # compare-and-set: Conflict if someone else moved it on

    def _alert(self, s: Shipment, text: str) -> None:
        """Tell staff once (not on every sweep) about something only a person can settle."""
        if text not in s.alerts:
            s.alerts.append(text)
            self._event(s, "alert", "system", {"text": text})

    def _fail(self, op: ProviderOp, why: str, *, state: OpState = OpState.failed) -> None:
        # One transaction: the operation closes and the shipment is freed together, or
        # neither (a crash in between would otherwise strand the shipment with no open op).
        with self.store.atomic():
            op.state, op.last_error = state, why
            self._save_op(op)
            s = self._get(op.shop, op.shipment_id)
            s.last_error = why
            move(
                s,
                S.ready,
                at=self.clock(),
                actor="system",
                event="purchase_failed",
                detail={"operation": op.id, "why": why, "charged": False},
            )
            self.store.save(s)

    def _advance(self, op: ProviderOp) -> None:
        try:
            self._steps(op)
        except Conflict:
            # Someone else (a timer sweep) moved this operation on while we were waiting on the
            # provider. Their decision stands; in particular we never go on to pay.
            log.warning("operation %s changed under the buy; leaving it to the ledger", op.id)

    def _steps(self, op: ProviderOp) -> None:
        while True:
            s = self._get(op.shop, op.shipment_id)
            if op.state == OpState.authorised:
                quote = op.quote or s.quote
                if quote is None or self._basis(s) != op.basis:
                    self._fail(
                        op,
                        "This order changed after the label was authorised, so nothing was "
                        "ordered or paid. Check it and buy again.",
                    )
                    return
                try:
                    order = self.provider.create_order(s, quote, op.id)
                except ProviderUncertain as exc:
                    # An unpaid order may exist; we don't know its ref, so it can never be paid.
                    self._fail(
                        op,
                        f"{self._who(op)} didn't confirm the order ({exc}). "
                        "Nothing was paid; you can try again.",
                    )
                    return
                except ProviderRefused as exc:
                    self._fail(op, f"{self._who(op)} refused the order: {exc}. Nothing was paid.")
                    return
                except ProviderUnavailable as exc:
                    self._fail(
                        op,
                        f"{self._who(op)} couldn't be reached ({exc}). Nothing was paid; "
                        "try again shortly.",
                    )
                    return
                except Exception as exc:  # a fault building the order or reading the reply
                    # An order may exist, but without its reference it can never be paid.
                    log.exception("create_order for %s", op.id)
                    self._fail(
                        op,
                        f"CLIVE hit an internal error placing the order ({type(exc).__name__}). "
                        "Nothing was paid. If it happens again, it needs fixing before retrying.",
                    )
                    return
                op.provider_ref = order.ref
                op.state = OpState.order_created
                self._save_op(op)
                if order.amount_minor <= 0:
                    self._fail(
                        op,
                        f"{self._who(op)} didn't give the order a usable price, so it was "
                        "not paid. Check the price again.",
                    )
                    return
                if order.amount_minor > op.amount.minor:
                    self._fail(
                        op,
                        f"{self._who(op)} priced the order at "
                        f"{Money(minor=order.amount_minor, currency=order.currency)}, more than "
                        f"the {op.amount} you agreed. It was not paid; check the price again.",
                    )
                    return
            elif op.state == OpState.order_created:
                ref = op.provider_ref
                if not ref:  # can't happen by construction; never pay an unknown order
                    self._fail(op, "The provider order has no reference. Nothing was paid.")
                    return
                # Saved (compare-and-set) before the call: if a sweep moved this operation on
                # meanwhile, this raises Conflict and nothing is paid. From here a crash reads
                # as "may have been charged".
                op.state, op.pay_sent_at = OpState.pay_sent, self.clock()
                self._save_op(op)
                try:
                    self.provider.pay(ref)
                except (ProviderRefused, ProviderUnavailable) as exc:
                    self._fail(
                        op,
                        f"{self._who(op)} didn't take the payment: {exc}. You weren't charged.",
                    )
                    return
                except ProviderUncertain as exc:
                    self._uncertain(op, str(exc))
                    self.reconcile(op)
                    return
                except Exception as exc:  # the request went out; the answer is unusable
                    log.exception("pay for %s", op.id)
                    self._uncertain(op, f"unreadable payment reply ({type(exc).__name__})")
                    self.reconcile(op)
                    return
                op.state = OpState.paid
                self._save_op(op)
                self._label_bought(op, "Paid; confirmed by the provider's reply.")
            elif op.state == OpState.paid:
                self._fetch_documents(op)
                return
            else:
                return

    def _uncertain(self, op: ProviderOp, why: str) -> None:
        with self.store.atomic():
            op.state, op.last_error = OpState.pay_unknown, why
            self._save_op(op)
            s = self._get(op.shop, op.shipment_id)
            s.last_error = NOT_READY[S.reconciliation_required]
            if s.status in (S.purchasing, S.label_purchased):
                if s.status == S.label_purchased:
                    s.label = None  # recorded on a reply the provider now contradicts
                move(
                    s,
                    S.reconciliation_required,
                    at=self.clock(),
                    actor="system",
                    event="payment_outcome_unknown",
                    detail={"operation": op.id, "why": why},
                )
            self.store.save(s)

    def _label_bought(self, op: ProviderOp, how: str) -> None:
        with self.store.lock:
            s = self._get(op.shop, op.shipment_id)
            if s.label is not None:
                return  # already recorded (e.g. by an earlier sweep)
            if s.status not in (S.purchasing, S.reconciliation_required):
                # Paid, but the shipment isn't where a purchase leaves it. Don't guess a
                # transition; make it impossible to miss.
                log.error("operation %s paid but shipment %s is %s", op.id, s.id, s.status)
                self._alert(
                    s,
                    f"Paid for: {self._who(op)} took {op.amount} for this order (CLIVE "
                    f"reference {op.id}), but the order was '{s.status.value}' at the time, so "
                    "the label wasn't recorded automatically. Check it before buying again.",
                )
                self.store.save(s)
                return
            # What was authorised and paid for, not whatever quote the shipment holds now.
            bought = op.quote or s.quote
            s.label = Label(
                provider=self._who(op),
                provider_ref=op.provider_ref or "",
                carrier=bought.carrier if bought else self._who(op),
                service_name=bought.service_name if bought else "",
                service_code=bought.service_code if bought else "",
                amount=op.amount,
                purchased_at=self.clock(),
            )
            s.last_error = None
            move(
                s,
                S.label_purchased,
                at=self.clock(),
                actor=op.actor,
                event="label_purchased",
                detail={"operation": op.id, "amount": str(op.amount), "how": how},
                verified=True,
            )
            self.store.save(s)

    def _overdue(self, op: ProviderOp) -> bool:
        since = op.pay_sent_at or op.created_at
        return self.clock() - since >= self.escalate_after

    def _fetch_documents(self, op: ProviderOp) -> None:
        try:
            if not op.provider_ref:
                raise ProviderUnavailable("no provider reference to fetch from")
            docs = self.provider.documents(op.provider_ref)
        except ProviderRefused as exc:
            if exc.code == "unpaid":
                # A 2xx payment reply that the provider now contradicts: not ours to guess.
                # Back to the read-back rule; never paid again from here.
                log.error("operation %s: provider says not paid after a paid reply", op.id)
                self._uncertain(op, f"{self._who(op)} says the order isn't paid")
                return
            self._documents_later(op, exc)
            return
        except Exception as exc:  # documents never move money: always just "try again later"
            if not isinstance(exc, ProviderError):
                log.exception("documents for %s", op.id)
            self._documents_later(op, exc)
            return
        with self.store.atomic():
            s = self._get(op.shop, op.shipment_id)
            if s.label is None:  # not recorded as bought: nothing to attach documents to
                log.error("documents for %s but shipment %s has no label", op.id, s.id)
                return
            stored = {d.kind: d for d in s.label.documents if d.artifact_id or d.electronic}
            was = s.label.customs
            for doc in docs.documents:
                kept = stored.get(doc.kind)
                if kept and not (doc.must_print and not kept.must_print):
                    continue  # fetched on an earlier try: keep the first copy
                # (a printable document replaces a record-only one: paperwork that appeared)
                artifact = None
                if doc.body:
                    artifact = self.store.put_artifact(
                        op.shop, s.id, doc.kind.value, doc.media_type, doc.body
                    )
                stored[doc.kind] = ShipmentDocument(
                    kind=doc.kind,
                    artifact_id=artifact,
                    media_type=doc.media_type,
                    page_size=doc.page_size,
                    pages=doc.pages,
                    copies_required=doc.copies_required,
                    must_print=doc.must_print,
                    attach_to_parcel=doc.attach_to_parcel,
                    electronic=doc.electronic,
                    note=doc.note,
                )
            customs = docs.customs if docs.customs != CustomsMode.unknown else was
            now = self.clock()
            seen_at, confirmed = s.label.customs_seen_at, s.label.customs_confirmed
            if customs == CustomsMode.electronic:
                if was != CustomsMode.electronic or seen_at is None:
                    seen_at, confirmed = now, False  # shown now; confirmed on a later look
                elif now - seen_at >= self.confirm_paperless_after:
                    confirmed = True
            elif customs != CustomsMode.unknown:
                confirmed = True  # paper (documents in hand) or no customs: positive evidence
                if was == CustomsMode.electronic and customs == CustomsMode.paper:
                    invoice = stored.get(DocumentKind.commercial_invoice)
                    copies = invoice.copies_required if invoice else 0
                    self._alert(
                        s,
                        "Customs paperwork appeared after the label was ready: print "
                        f"{copies or 'the'} cop{'ies' if copies != 1 else 'y'} of the commercial "
                        "invoice (A4) and attach them to the parcel in an envelope marked "
                        '"Customs Documents".',
                    )
            s.label = s.label.model_copy(
                update={
                    "documents": list(stored.values()),
                    "customs": customs,
                    "customs_seen_at": seen_at,
                    "customs_confirmed": confirmed,
                    "tracking_number": docs.tracking_number or s.label.tracking_number,
                    "tracking_url": docs.tracking_url or s.label.tracking_url,
                    "provider_ids": {**s.label.provider_ids, **docs.provider_ids},
                }
            )
            if s.label.complete:
                if s.status == S.label_purchased:
                    s.last_error = None
                if not any(e.type == "documents_stored" for e in s.timeline):
                    self._event(
                        s,
                        "documents_stored",
                        "system",
                        {
                            "documents": [d.kind.value for d in s.label.documents],
                            "customs": customs.value,
                            "tracking": s.label.tracking_number,
                        },
                        verified=True,
                    )
                if confirmed:
                    op.state = OpState.done  # else: open for one more look, never a payment
            else:
                if s.status == S.label_purchased:
                    s.last_error = (
                        "The label is bought. Its customs paperwork isn't confirmed yet; "
                        "CLIVE keeps checking. Don't buy again."
                    )
                if self._overdue(op):
                    self._alert(
                        s,
                        "The customs paperwork for this label still isn't confirmed after an "
                        f"hour. Check the order (CLIVE reference {op.id}) in "
                        f"{self._who(op)} and print any customs documents it shows.",
                    )
            self.store.save(s)
            self._save_op(op)

    def _documents_later(self, op: ProviderOp, exc: Exception) -> None:
        log.warning("documents for %s not available yet: %s", op.id, exc)
        with self.store.lock:
            s = self._get(op.shop, op.shipment_id)
            if s.status == S.label_purchased:
                s.last_error = (
                    "The label is bought but its documents haven't arrived yet. They'll be "
                    "fetched again shortly; don't buy again."
                )
            if self._overdue(op):
                self._alert(
                    s,
                    f"The label's documents still haven't arrived from {self._who(op)} "
                    f"after an hour (CLIVE reference {op.id}). The label is paid for: download "
                    "it from the provider rather than buying again.",
                )
            self.store.save(s)

    # ------------------------------------------------------------------ reconcile

    def reconcile(self, op: ProviderOp) -> None:
        """Settle an open operation from the provider's own records. Safe to call any time,
        from any thread: it works on the latest saved copy and never pays."""
        fresh = self.store.op(op.shop, op.id)
        if fresh is None:
            return
        try:
            self._reconcile(fresh)
        except Conflict:
            log.info("operation %s moved on during reconcile; next sweep looks again", op.id)

    def _reconcile(self, op: ProviderOp) -> None:
        at = self.clock()
        if op.state == OpState.pay_sent:
            if at - (op.pay_sent_at or op.updated_at) < self.interrupted_after:
                return  # the payment may still be on the wire: its own thread settles it
            self._uncertain(op, "Interrupted after the payment was sent.")
        if op.state == OpState.pay_unknown:
            if not op.provider_ref:
                log.error("operation %s is unknown but has no provider reference", op.id)
                return  # stays unknown and visible; never paid again
            try:
                seen = self.provider.read_order(op.provider_ref)
            except Exception as exc:
                self._read_failed(op, exc)
                return  # still unknown; the next sweep tries again
            if seen.paid:
                op.state = OpState.paid
                self._save_op(op)
                self._label_bought(op, "Payment confirmed by reading the order back.")
                self._fetch_documents(op)
                return
            op.unpaid_reads.append(at)
            self._save_op(op)
            first = op.unpaid_reads[0]
            if len(op.unpaid_reads) >= 2 and at - first >= self.confirm_unpaid_after:
                with self.store.atomic():
                    op.state = OpState.abandoned
                    op.last_error = "Confirmed unpaid twice; this provider order is never paid."
                    self._save_op(op)
                    s = self._get(op.shop, op.shipment_id)
                    s.last_error = (
                        "You weren't charged: the provider confirms the payment "
                        "didn't go through. Buy again when you're ready."
                    )
                    move(
                        s,
                        S.ready,
                        at=at,
                        actor="system",
                        event="payment_not_taken",
                        detail={"operation": op.id, "charged": False},
                        verified=True,
                    )
                    self.store.save(s)
        elif op.state == OpState.paid:
            # Recorded first if a crash came between the payment and the label.
            self._label_bought(op, "Paid; recorded on reconcile.")
            self._fetch_documents(op)
        elif op.state in (OpState.authorised, OpState.order_created):
            # Nothing has been paid. Only once its own thread has clearly gone (well past the
            # longest provider call) is the decision given back.
            if at - op.updated_at >= self.interrupted_after:
                self._fail(
                    op,
                    "The purchase was interrupted before payment. You weren't "
                    "charged; buy again when you're ready.",
                    state=OpState.abandoned,
                )

    def _read_failed(self, op: ProviderOp, exc: Exception) -> None:
        if isinstance(exc, ProviderError):
            log.warning("read-back for %s failed: %s", op.id, exc)
        else:
            log.exception("read_order for %s", op.id)
        op.read_failures += 1
        op.first_read_failure_at = op.first_read_failure_at or self.clock()
        self._save_op(op)
        if self.clock() - op.first_read_failure_at >= self.escalate_after:
            with self.store.lock:
                s = self._get(op.shop, op.shipment_id)
                self._alert(
                    s,
                    f"CLIVE couldn't confirm the payment with {self._who(op)} for over an "
                    f"hour. Check the order (CLIVE reference {op.id}) in {self._who(op)} "
                    "before buying again. CLIVE keeps checking and will never pay twice.",
                )
                self.store.save(s)

    def reconcile_all(self) -> int:
        ops = self.store.open_ops()
        for op in ops:
            try:
                self.reconcile(op)
            except Exception:  # one broken operation must not leave the others unchecked
                log.exception("reconcile %s", op.id)
        return len(ops)

    # ------------------------------------------------------------------ reprint

    def reprint(
        self, shop: str, shipment_id: str, kind: DocumentKind = DocumentKind.shipping_label
    ) -> tuple[str, bytes]:
        """A document of the label already bought, again. Reads stored artifacts only: there
        is no path from here to the provider, so it can never buy or pay."""
        s = self._get(shop, shipment_id)
        doc = s.label.document(kind) if s.label else None
        if doc is None or not doc.artifact_id:
            raise ActionError("There's no stored document of that kind to print yet.")
        found = self.store.get_artifact(shop, doc.artifact_id)
        if not found:
            raise ActionError("The stored document is missing.", 404)
        with self.store.lock:
            s = self._get(shop, shipment_id)
            self._event(s, "reprinted", "system", {"document": kind.value})
            self.store.save(s)
        return found[1], found[2]

    # ------------------------------------------------------------------ results

    def _result(self, op: ProviderOp, replayed: bool = False) -> dict[str, Any]:
        s = self._get(op.shop, op.shipment_id)
        return {
            "operation": op.id,
            "operation_state": op.state.value,
            "status": s.status.value,
            "charged": op.state in (OpState.paid, OpState.done),
            "may_have_been_charged": op.state in (OpState.pay_sent, OpState.pay_unknown),
            "error": s.last_error,
            "replayed": replayed,
            "shipment": s,
        }
