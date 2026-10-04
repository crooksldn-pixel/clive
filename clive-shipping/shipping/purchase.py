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

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from shipping.basis import basis
from shipping.models import Label, OpState, ProviderOp, Shipment
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
from shipping.store import OpenOperationExists, Store, new_id, now


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
        interrupted_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self.store = store
        self.provider = provider
        self.clock = clock
        self.confirm_unpaid_after = confirm_unpaid_after
        self.interrupted_after = interrupted_after

    # ------------------------------------------------------------------ helpers

    def _get(self, shop: str, shipment_id: str) -> Shipment:
        s = self.store.get(shop, shipment_id)
        if s is None:
            raise ActionError("Shipment not found.", 404)
        return s

    def _require_ready(self, s: Shipment) -> None:
        if s.status != S.ready:
            raise ActionError(
                NOT_READY.get(s.status, f"A label can't be bought while this is {s.status.value}.")
            )
        if s.quote is None or s.package is None:
            raise ActionError("Choose a package and a service first.")

    def _exact_price(self, s: Shipment) -> int:
        try:
            return self.provider.verify(s, s.quote)
        except ProviderRefused as exc:
            raise ActionError(
                f"{self.provider.name} won't take this parcel as it stands: {exc}. Nothing was "
                "bought.",
                422,
                "provider_refused",
            ) from exc
        except ProviderError as exc:
            raise ActionError(
                f"Couldn't get the exact price from {self.provider.name} ({exc}). Nothing was "
                "bought; try again in a minute.",
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
            self._event(s, "price_updated", "system", {"was": str(was), "now": str(s.quote.amount)})
            self.store.save(s)
        q, p = s.quote, s.package
        value = sum((ln.unit_value.minor * ln.quantity for ln in s.lines), 0)
        return {
            "will": [
                f"Buy {q.title} for {q.amount} from {self.provider.name}",
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
            "basis": basis(s),
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
            if basis_token != basis(s):
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
        with self.store.lock:
            s = self._get(shop, shipment_id)
            self._require_ready(s)
            if basis_token != basis(s):
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

    def _fail(self, op: ProviderOp, why: str, *, state: OpState = OpState.failed) -> None:
        with self.store.lock:
            op.state, op.last_error = state, why
            self.store.save_op(op)
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
        while True:
            s = self._get(op.shop, op.shipment_id)
            if op.state == OpState.authorised:
                try:
                    order = self.provider.create_order(s, s.quote, op.id)
                except ProviderUncertain as exc:
                    # An unpaid order may exist; we don't know its ref, so it can never be paid.
                    self._fail(
                        op,
                        f"{self.provider.name} didn't confirm the order ({exc}). "
                        "Nothing was paid; you can try again.",
                    )
                    return
                except (ProviderRefused, ProviderUnavailable) as exc:
                    self._fail(
                        op, f"{self.provider.name} refused the order: {exc}. Nothing was paid."
                    )
                    return
                op.provider_ref = order.ref
                op.state = OpState.order_created
                self.store.save_op(op)
                if order.amount_minor > op.amount.minor:
                    self._fail(
                        op,
                        f"{self.provider.name} priced the order at "
                        f"{Money(minor=order.amount_minor, currency=order.currency)}, more than "
                        f"the {op.amount} you agreed. It was not paid; check the price again.",
                    )
                    return
            elif op.state == OpState.order_created:
                # Saved before the call: from here a crash reads as "may have been charged".
                op.state, op.pay_sent_at = OpState.pay_sent, self.clock()
                self.store.save_op(op)
                try:
                    self.provider.pay(op.provider_ref)
                except (ProviderRefused, ProviderUnavailable) as exc:
                    self._fail(
                        op,
                        f"{self.provider.name} didn't take the payment: {exc}. You "
                        "weren't charged.",
                    )
                    return
                except ProviderUncertain as exc:
                    self._uncertain(op, str(exc))
                    self.reconcile(op)
                    return
                op.state = OpState.paid
                self.store.save_op(op)
                self._label_bought(op, "Paid; confirmed by the provider's reply.")
            elif op.state == OpState.paid:
                self._fetch_documents(op)
                return
            else:
                return

    def _uncertain(self, op: ProviderOp, why: str) -> None:
        with self.store.lock:
            op.state, op.last_error = OpState.pay_unknown, why
            self.store.save_op(op)
            s = self._get(op.shop, op.shipment_id)
            s.last_error = NOT_READY[S.reconciliation_required]
            if s.status == S.purchasing:
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
            if s.status in (S.purchasing, S.reconciliation_required):
                s.label = Label(
                    provider=self.provider.name,
                    provider_ref=op.provider_ref or "",
                    carrier=s.quote.carrier,
                    service_name=s.quote.service_name,
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

    def _fetch_documents(self, op: ProviderOp) -> None:
        try:
            docs = self.provider.documents(op.provider_ref)
        except ProviderError as exc:
            with self.store.lock:
                s = self._get(op.shop, op.shipment_id)
                s.last_error = (
                    f"The label is bought but its documents haven't arrived yet "
                    f"({exc}). They'll be fetched again shortly; don't buy again."
                )
                self.store.save(s)
            return
        with self.store.lock:
            s = self._get(op.shop, op.shipment_id)
            arts = dict(s.label.artifacts) if s.label else {}
            for kind, body in (
                ("label_4x6", docs.label_4x6),
                ("label_a4", docs.label_a4),
                ("customs", docs.customs),
            ):
                if body and kind not in arts:
                    arts[kind] = self.store.put_artifact(
                        op.shop, s.id, kind, "application/pdf", body
                    )
            if s.label:
                s.label = s.label.model_copy(
                    update={
                        "artifacts": arts,
                        "tracking_number": docs.tracking_number or s.label.tracking_number,
                        "tracking_url": docs.tracking_url or s.label.tracking_url,
                    }
                )
            s.last_error = None
            self._event(
                s,
                "documents_stored",
                "system",
                {"kinds": sorted(arts), "tracking": docs.tracking_number},
                verified=True,
            )
            self.store.save(s)
            op.state = OpState.done
            self.store.save_op(op)

    # ------------------------------------------------------------------ reconcile

    def reconcile(self, op: ProviderOp) -> None:
        """Settle an open operation from the provider's own records. Safe to call any time."""
        at = self.clock()
        if op.state in (OpState.pay_unknown, OpState.pay_sent):
            if op.state == OpState.pay_sent:  # a crash after sending: treat as unknown
                self._uncertain(op, "Interrupted after the payment was sent.")
            try:
                seen = self.provider.read_order(op.provider_ref)
            except ProviderError:
                return  # still unknown; the next sweep tries again
            if seen.paid:
                op.state = OpState.paid
                self.store.save_op(op)
                self._label_bought(op, "Payment confirmed by reading the order back.")
                self._fetch_documents(op)
                return
            op.unpaid_reads.append(at)
            self.store.save_op(op)
            first = op.unpaid_reads[0]
            if len(op.unpaid_reads) >= 2 and at - first >= self.confirm_unpaid_after:
                with self.store.lock:
                    op.state = OpState.abandoned
                    op.last_error = "Confirmed unpaid twice; this provider order is never paid."
                    self.store.save_op(op)
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
            self._fetch_documents(op)
        elif op.state in (OpState.authorised, OpState.order_created):
            # A process died before paying. Nothing was charged; give the decision back.
            if at - op.created_at >= self.interrupted_after:
                self._fail(
                    op,
                    "The purchase was interrupted before payment. You weren't "
                    "charged; buy again when you're ready.",
                    state=OpState.abandoned,
                )

    def reconcile_all(self) -> int:
        ops = self.store.open_ops()
        for op in ops:
            self.reconcile(op)
        return len(ops)

    # ------------------------------------------------------------------ reprint

    def reprint(self, shop: str, shipment_id: str, kind: str = "label_4x6") -> tuple[str, bytes]:
        """The label already bought, again. Never calls the provider; never spends money."""
        s = self._get(shop, shipment_id)
        if not s.label or not s.label.artifacts:
            raise ActionError("There's no stored label to print for this order yet.")
        artifact_id = s.label.artifacts.get(kind) or next(iter(s.label.artifacts.values()))
        found = self.store.get_artifact(shop, artifact_id)
        if not found:
            raise ActionError("The stored label is missing.", 404)
        self._event(s, "reprinted", "system", {"artifact": artifact_id})
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
