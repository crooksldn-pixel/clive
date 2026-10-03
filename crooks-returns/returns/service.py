"""The returns workflow. Every consequential step is an action with a preview (what will happen,
in pounds, before anything moves) and an execute (the change, then a read-back from Shopify
that marks it verified). Customers, staff and CLIVE all go through the same actions, so the
timeline of a return always says who did what and whether it was confirmed.

    requested -> awaiting_label -> awaiting_shipment -> in_transit -> received -> completed
             \\-> declined          (any step before received) -> cancelled
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from returns import policy, verify
from returns.labels import LabelError, LabelPort, tracking_url
from returns.models import (
    REASON_LABELS,
    Event,
    Money,
    Order,
    Postage,
    PostageMode,
    PostageState,
    Resolution,
    Return,
    Selection,
    Status,
    gbp,
    to_amount,
)
from returns.settings import Settings
from returns.shopify import ShopifyError, ShopifyPort
from returns.store import Store, new_id, now

log = logging.getLogger("returns.service")


class ActionError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


CUSTOMER_STATUS = {
    Status.requested: "Return requested. We'll confirm it shortly.",
    Status.awaiting_label: "Approved. Your return label is being prepared and will be emailed to you.",
    Status.awaiting_shipment: "Approved. Send your return back to us.",
    Status.in_transit: "On its way back to us.",
    Status.received: "Arrived back with us. We're checking it over.",
    Status.completed: "Complete.",
    Status.declined: "We couldn't accept this return.",
    Status.cancelled: "Cancelled.",
}

ACTIONS = ("approve", "decline", "label", "tracking", "receive", "complete", "cancel", "note")


class Notifier:
    """Signed webhooks to CLIVE. Delivery never blocks or fails an action."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._http = httpx.Client(timeout=5)

    def send(self, event: str, ret: Return) -> None:
        if not self.s.clive_webhook_url:
            return
        body = json.dumps(
            {"event": event, "at": now().isoformat(), "return": json.loads(ret.model_dump_json())}
        ).encode()
        sig = hmac.new(self.s.clive_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            self._http.post(
                self.s.clive_webhook_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Crooks-Returns-Event": event,
                    "X-Crooks-Returns-Signature": sig,
                },
            )
        except httpx.HTTPError as exc:
            log.warning("webhook %s for %s not delivered: %s", event, ret.id, exc)


class ReturnsService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        shopify: ShopifyPort,
        labels: LabelPort,
        notifier: Notifier | None = None,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.s = settings
        self.store = store
        self.shopify = shopify
        self.labels = labels
        self.notifier = notifier or Notifier(settings)
        self.clock = clock
        self.by_order = verify.RateLimiter(limit=5, window_s=900)
        self.by_ip = verify.RateLimiter(limit=30, window_s=900)

    # ===================================================================== the portal

    def lookup(self, order_number: str, proof: str, ip: str) -> tuple[str, Order]:
        digits = verify.normalise_order_number(order_number)
        if not digits or not (proof or "").strip():
            raise ActionError(verify.NOT_FOUND, 404)
        if self.by_order.blocked(digits) or self.by_ip.blocked(ip):
            raise ActionError(verify.LOCKED, 429)
        matches = [o for o in self.shopify.find_orders(digits) if verify.proof_matches(o, proof)]
        if len(matches) != 1:
            self.by_order.hit(digits)
            self.by_ip.hit(ip)
            raise ActionError(verify.NOT_FOUND, 404)
        order = matches[0]
        return verify.session_for(order.id, self.s.session_secret, self.s.session_ttl_s), order

    def order_for_session(self, session: str) -> Order:
        order_id = verify.order_from_session(session, self.s.session_secret)
        order = self.shopify.get_order(order_id) if order_id else None
        if order is None:
            raise ActionError("Your session has expired. Look up your order again.", 401)
        return self.available(order)

    def available(self, order: Order) -> Order:
        """Take out quantities already in a request Shopify has not been told about yet."""
        order = order.model_copy(deep=True)
        for line in order.lines:
            line.returnable_qty = max(
                0, line.returnable_qty - self.store.open_reserved_qty(line.fulfillment_line_item_id)
            )
        return order

    def today(self):
        return policy.today_in(self.s, self.clock())

    def portal_order(self, order: Order) -> dict[str, Any]:
        today = self.today()
        lines = []
        for line in order.lines:
            check = policy.check_line(order, line, today, self.s)
            lines.append(
                {
                    "id": line.fulfillment_line_item_id,
                    "title": line.title,
                    "variant": line.variant_title,
                    "image": line.image_url,
                    "price": gbp(line.unit_paid_pence),
                    "returnable_qty": check.returnable_qty,
                    "eligible": bool(check.allowed_reasons),
                    "message": check.message,
                    "reasons": [r.value for r in check.allowed_reasons],
                    "window_ends": check.window_ends.isoformat() if check.window_ends else None,
                }
            )
        return {
            "order": order.name,
            "lines": lines,
            "reasons": policy.reason_list(),
            "returns": [self.public(r) for r in self.store.for_order(order.id)],
        }

    def quote(self, order: Order, selections: list[Selection]) -> policy.Quote:
        try:
            return policy.quote(order, selections, self.today(), self.s)
        except policy.PolicyError as exc:
            raise ActionError(str(exc), 422) from exc

    def submit(
        self,
        order: Order,
        selections: list[Selection],
        resolution: Resolution,
        postage: Postage,
        exchange_to: dict[str, str] | None = None,
    ) -> Return:
        with self.store.lock:
            order = self.available(self.shopify.get_order(order.id) or order)
            q = self.quote(order, selections)
            option = next((o for o in q.options if o.resolution == resolution), None)
            if option is None:
                raise ActionError("That option isn't available for these items.", 422)
            chosen = next((p for p in option.postage if p.choice == postage), None)
            if chosen is None:
                raise ActionError("That postage option isn't available.", 422)
            lines = q.lines
            if resolution == Resolution.exchange:
                by_id = {ln.fulfillment_line_item_id: ln for ln in order.lines}
                for line in lines:
                    want = (exchange_to or {}).get(line.fulfillment_line_item_id)
                    allowed = {
                        v.id: v for v in option.exchange_choices[line.fulfillment_line_item_id]
                    }
                    if want not in allowed:
                        raise ActionError(f"Choose what {line.title} should be swapped for.", 422)
                    v = allowed[want]
                    line.exchange_variant_id, line.exchange_variant_title = v.id, v.title
                    line.exchange_sku = v.sku
                    line.exchange_direction = policy.exchange_direction(
                        by_id[line.fulfillment_line_item_id], v.id
                    )
            money = Money(items_pence=q.items_pence, fee_pence=chosen.fee_pence)
            if resolution == Resolution.store_credit:
                money.bonus_pence = option.bonus_pence
                money.credit_pence = q.items_pence + option.bonus_pence
            elif resolution == Resolution.refund:
                money.shipping_refund_pence = option.shipping_refund_pence
                money.refund_pence = chosen.total_pence
            at = self.clock()
            ret = Return(
                id=new_id("ret"),
                order_id=order.id,
                order_name=order.name,
                customer_id=order.customer_id,
                customer_name=order.customer_name,
                customer_email=order.email or order.customer_email,
                currency=order.currency,
                created_at=at,
                updated_at=at,
                status=Status.requested,
                resolution=resolution,
                lines=lines,
                money=money,
                postage=PostageState(
                    chosen=postage, paid_by="customer" if chosen.fee_pence else "crooks"
                ),
                offers_shown=[o.resolution.value for o in q.options],
            )
            self._event(
                ret,
                "requested",
                "customer",
                {
                    "resolution": resolution.value,
                    "postage": postage.value,
                    "summary": self.summary(ret),
                },
            )
            self.store.save(ret)
        self.notifier.send("return.requested", ret)
        return ret

    def customer_tracking(self, order: Order, return_id: str, number: str) -> Return:
        ret = self._get(return_id)
        if ret.order_id != order.id:
            raise ActionError("Return not found.", 404)
        return self.execute(
            return_id, "tracking", {"number": number}, "customer", f"customer-tracking-{number}"
        )["return_doc"]

    # ===================================================================== actions

    def _get(self, return_id: str) -> Return:
        ret = self.store.get(return_id)
        if ret is None:
            raise ActionError("Return not found.", 404)
        return ret

    def _event(
        self,
        ret: Return,
        kind: str,
        actor: str,
        detail: dict[str, Any] | None = None,
        verified: bool = False,
    ) -> None:
        ret.timeline.append(
            Event(at=self.clock(), type=kind, actor=actor, detail=detail or {}, verified=verified)
        )

    def _require(self, ret: Return, *statuses: Status) -> None:
        if ret.status not in statuses:
            allowed = ", ".join(s.value for s in statuses)
            raise ActionError(f"This return is {ret.status.value}; that needs {allowed}.")

    def summary(self, ret: Return) -> str:
        items = ", ".join(
            f"{ln.quantity}x {ln.title}{f' ({ln.variant_title})' if ln.variant_title else ''}"
            + (f" -> {ln.exchange_variant_title}" if ln.exchange_variant_id else "")
            + f" [{REASON_LABELS[ln.reason]}]"
            for ln in ret.lines
        )
        if ret.resolution == Resolution.exchange:
            outcome = "exchange"
        elif ret.resolution == Resolution.store_credit:
            outcome = (
                f"store credit {gbp(ret.money.credit_pence)} "
                f"(incl. {gbp(ret.money.bonus_pence)} bonus)"
            )
        else:
            outcome = f"refund {gbp(ret.money.refund_pence)}"
            if ret.money.fee_pence:
                outcome += f" after {gbp(ret.money.fee_pence)} label"
        return f"{ret.order_name}: {items}; {outcome}"

    def preview(self, return_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        ret = self._get(return_id)
        will: list[str] = []
        calls: list[str] = []
        if action == "approve":
            self._require(ret, Status.requested)
            mode = self._mode(ret, params)
            will.append(f"Create Shopify return on {ret.order_name} for: {self.summary(ret)}.")
            calls.append("returnCreate")
            if mode == PostageMode.label_now:
                ok, why = self.labels.available()
                if ok:
                    will.append("Buy a Royal Mail return label in Click & Drop and email it.")
                    calls.append("reverseDeliveryCreateWithShipping")
                else:
                    will.append(
                        f"No label can be made yet ({why}); the return will wait as awaiting_label."
                    )
            elif mode == PostageMode.self_ship:
                will.append("Ask the customer to send it back themselves and add tracking.")
            elif mode == PostageMode.label_later:
                will.append(f"Hold it as awaiting_label; overdue after {self.s.label_due_hours}h.")
            else:
                will.append("Nothing comes back. " + self._outcome_sentence(ret))
                calls.append("returnProcess")
        elif action == "decline":
            self._require(ret, Status.requested)
            will.append(
                f"Decline: {params.get('reason') or 'no reason given'}. Nothing in Shopify changes."
            )
        elif action == "label":
            self._require(ret, Status.awaiting_label)
            if params.get("tracking"):
                will.append(f"Attach tracking {params['tracking']} to the Shopify return.")
            else:
                will.append("Buy a Royal Mail return label in Click & Drop and email it.")
            calls.append("reverseDeliveryCreateWithShipping")
        elif action == "tracking":
            self._require(ret, Status.awaiting_shipment, Status.awaiting_label)
            will.append(f"Record tracking {params.get('number')} and mark it in transit.")
            calls.append("reverseDeliveryCreateWithShipping")
        elif action in ("receive", "complete"):
            if action == "receive":
                self._require(
                    ret, Status.awaiting_label, Status.awaiting_shipment, Status.in_transit
                )
                condition = (params.get("condition") or "ok").lower()
                will.append(f"Mark received in condition '{condition}'.")
                if condition != "ok":
                    will.append("Stop there for a decision, because the items are not as expected.")
                    return self._preview_out(ret, action, will, calls)
            else:
                self._require(ret, Status.received)
            will.append(self._outcome_sentence(ret))
            calls.append("returnProcess")
            if ret.resolution == Resolution.store_credit and ret.money.bonus_pence:
                calls.append("storeCreditAccountCredit")
        elif action == "cancel":
            self._require(ret, Status.requested, Status.awaiting_label, Status.awaiting_shipment)
            will.append(
                "Cancel the return" + (" in Shopify too." if ret.shopify.return_id else ".")
            )
            if ret.shopify.return_id:
                calls.append("returnCancel")
        elif action == "note":
            will.append("Add a note to the timeline.")
        else:
            raise ActionError(f"Unknown action {action}.", 404)
        return self._preview_out(ret, action, will, calls)

    def _preview_out(
        self, ret: Return, action: str, will: list[str], calls: list[str]
    ) -> dict[str, Any]:
        return {
            "return_id": ret.id,
            "action": action,
            "status": ret.status.value,
            "will": will,
            "shopify_calls": calls,
            "money": ret.money.model_dump(),
        }

    def _outcome_sentence(self, ret: Return) -> str:
        if ret.resolution == Resolution.exchange:
            swaps = "; ".join(
                f"{ln.title} {ln.variant_title} -> {ln.exchange_variant_title}" for ln in ret.lines
            )
            return f"Release the exchange to ship: {swaps}."
        if ret.resolution == Resolution.store_credit:
            return (
                f"Credit {gbp(ret.money.items_pence)} to store credit, then a "
                f"{gbp(ret.money.bonus_pence)} bonus (total {gbp(ret.money.credit_pence)})."
            )
        extra = (
            f", including {gbp(ret.money.shipping_refund_pence)} delivery"
            if ret.money.shipping_refund_pence
            else ""
        )
        fee = f", after the {gbp(ret.money.fee_pence)} label" if ret.money.fee_pence else ""
        return f"Refund {gbp(ret.money.refund_pence)} to the original payment method{extra}{fee}."

    def _mode(self, ret: Return, params: dict[str, Any]) -> PostageMode:
        if params.get("postage_mode"):
            try:
                return PostageMode(params["postage_mode"])
            except ValueError as exc:
                raise ActionError(
                    "postage_mode must be label_now, self_ship, no_return or label_later.", 422
                ) from exc
        return (
            PostageMode.self_ship
            if ret.postage.chosen == Postage.self_ship
            else PostageMode.label_now
        )

    def execute(
        self, return_id: str, action: str, params: dict[str, Any], actor: str, key: str
    ) -> dict[str, Any]:
        if action not in ACTIONS:
            raise ActionError(f"Unknown action {action}.", 404)
        if not key:
            raise ActionError("An idempotency key is required.", 422)
        scoped = f"{return_id}:{action}:{key}"
        with self.store.lock:
            done = self.store.remembered(scoped)
            if done is not None:
                return {**done, "replayed": True, "return_doc": self._get(return_id)}
            self.preview(return_id, action, params)  # every rule a preview checks, execute checks
            ret = self._get(return_id)
            before = ret.status
            getattr(self, f"_do_{action}")(ret, params, actor)
            self.store.save(ret)
            last = ret.timeline[-1] if ret.timeline else None
            out = {
                "return_id": ret.id,
                "action": action,
                "from": before.value,
                "status": ret.status.value,
                "verified": bool(last and last.verified),
                "error": ret.last_error,
                "evidence": ret.shopify.model_dump(),
            }
            self.store.remember(scoped, out)
        self.notifier.send(f"return.{action}", ret)
        return {**out, "return_doc": ret}

    # -------------------------------------------------------------- action bodies

    def _do_approve(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        mode = self._mode(ret, params)
        ret.postage.mode = mode
        if not ret.shopify.return_id:
            try:
                created = self.shopify.create_return(ret, self.shopify.reason_ids())
            except ShopifyError as exc:
                ret.last_error = f"Shopify did not create the return: {exc}"
                self._event(ret, "approve_failed", actor, {"error": str(exc)})
                return
            for k, v in created.items():
                setattr(ret.shopify, k, v)
        ret.last_error = None
        self._event(
            ret,
            "approved",
            actor,
            {"postage_mode": mode.value, "shopify_return": ret.shopify.return_name},
            verified=bool(ret.shopify.return_id),
        )
        if mode == PostageMode.label_now:
            self._make_label(ret, actor)
        elif mode == PostageMode.self_ship:
            ret.status = Status.awaiting_shipment
        elif mode == PostageMode.label_later:
            self._await_label(ret, actor, "Label to follow.")
        else:
            ret.status = Status.received
            self._event(ret, "no_return", actor, {"note": "Customer keeps the item."})
            self._process(ret, actor)

    def _await_label(self, ret: Return, actor: str, why: str) -> None:
        ret.status = Status.awaiting_label
        ret.postage.label_due_at = self.clock() + timedelta(hours=self.s.label_due_hours)
        self._event(
            ret, "awaiting_label", actor, {"why": why, "due": ret.postage.label_due_at.isoformat()}
        )

    def label_link(self, file_id: str) -> str:
        token = verify.sign(
            {"kind": "file", "id": file_id, "exp": int(self.clock().timestamp()) + 60 * 86400},
            self.s.session_secret,
        )
        return f"{self.s.public_base_url.rstrip('/')}/files/{file_id}?t={token}"

    def _make_label(self, ret: Return, actor: str) -> None:
        order = self.shopify.get_order(ret.order_id)
        try:
            label = self.labels.create(ret, order.shipping_address if order else {})
        except LabelError as exc:
            ret.last_error = str(exc)
            self._await_label(ret, actor, str(exc))
            return
        file_id = self.store.put_file(ret.id, "application/pdf", label.pdf) if label.pdf else None
        ret.postage.carrier, ret.postage.label_ref = label.carrier, label.ref
        ret.postage.tracking = label.tracking
        ret.postage.tracking_url = tracking_url(label.tracking) if label.tracking else None
        ret.postage.label_file_id = file_id
        self._label_attached(ret, actor, self.label_link(file_id) if file_id else None)

    def _label_attached(self, ret: Return, actor: str, label_url: str | None) -> None:
        if self._attach(ret, actor, label_url=label_url, notify=self.s.shopify_notify_customer):
            ret.status = Status.awaiting_shipment
        else:
            self._await_label(ret, actor, ret.last_error or "Label not attached.")

    def _attach(self, ret: Return, actor: str, label_url: str | None, notify: bool) -> bool:
        if not ret.shopify.reverse_fulfillment_order_ids:
            ret.last_error = "The Shopify return has no reverse fulfilment order to attach to."
            return False
        try:
            ret.shopify.reverse_delivery_id = self.shopify.attach_shipping(
                ret.shopify.reverse_fulfillment_order_ids[0],
                ret.postage.tracking,
                ret.postage.tracking_url,
                label_url,
                notify,
            )
        except ShopifyError as exc:
            ret.last_error = f"Shopify did not take the shipping details: {exc}"
            self._event(ret, "shipping_attach_failed", actor, {"error": str(exc)})
            return False
        ret.last_error = None
        self._event(
            ret,
            "shipping_attached",
            actor,
            {
                "tracking": ret.postage.tracking,
                "label_ref": ret.postage.label_ref,
                "reverse_delivery": ret.shopify.reverse_delivery_id,
            },
            verified=True,
        )
        return True

    def _do_decline(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        ret.status = Status.declined
        ret.decline_reason = (params.get("reason") or "").strip() or None
        self._event(ret, "declined", actor, {"reason": ret.decline_reason})

    def _do_label(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        if params.get("tracking"):
            ret.postage.carrier = params.get("carrier") or "Royal Mail"
            ret.postage.tracking = params["tracking"].strip()
            ret.postage.tracking_url = params.get("tracking_url") or (
                tracking_url(ret.postage.tracking) if ret.postage.carrier == "Royal Mail" else None
            )
            self._label_attached(ret, actor, params.get("label_url"))
        else:
            self._make_label(ret, actor)

    def _do_tracking(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        number = "".join((params.get("number") or "").split()).upper()
        if not 6 <= len(number) <= 40:
            raise ActionError("That tracking number doesn't look right.", 422)
        ret.postage.tracking = number
        ret.postage.carrier = params.get("carrier") or ret.postage.carrier
        royal_mail = (ret.postage.carrier or "Royal Mail") == "Royal Mail"
        ret.postage.tracking_url = tracking_url(number) if royal_mail else None
        if ret.shopify.reverse_delivery_id is None:
            # Recorded here either way; a Shopify refusal is kept in last_error for staff.
            self._attach(ret, actor, label_url=None, notify=False)
        ret.status = Status.in_transit
        self._event(ret, "in_transit", actor, {"tracking": number})

    def _do_receive(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        condition = (params.get("condition") or "ok").lower()
        ret.inspection = {
            "condition": condition,
            "restock": bool(params.get("restock", True)),
            "note": params.get("note") or "",
            "by": actor,
            "at": self.clock().isoformat(),
        }
        ret.status = Status.received
        self._event(ret, "received", actor, ret.inspection)
        if condition == "ok":
            self._process(ret, actor)

    def _do_complete(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        self._process(ret, actor)

    def _do_cancel(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        if ret.shopify.return_id:
            try:
                self.shopify.cancel_return(ret.shopify.return_id)
            except ShopifyError as exc:
                ret.last_error = f"Shopify did not cancel the return: {exc}"
                self._event(ret, "cancel_failed", actor, {"error": str(exc)})
                return
        ret.status = Status.cancelled
        self._event(
            ret,
            "cancelled",
            actor,
            {"reason": params.get("reason")},
            verified=bool(ret.shopify.return_id),
        )

    def _do_note(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        self._event(ret, "note", actor, {"text": (params.get("text") or "")[:2000]})

    # -------------------------------------------------------------- moving the money

    def process_payload(self, ret: Return) -> dict[str, Any]:
        restock = bool((ret.inspection or {}).get("restock", True))
        lines = []
        for line in ret.lines:
            item: dict[str, Any] = {
                "id": ret.shopify.return_line_item_ids[line.fulfillment_line_item_id],
                "quantity": line.quantity,
            }
            rfo_line = ret.shopify.rfo_line_item_ids.get(line.fulfillment_line_item_id)
            if (
                self.s.restock_location_id
                and rfo_line
                and ret.postage.mode != PostageMode.no_return
            ):
                item["dispositions"] = [
                    {
                        "reverseFulfillmentOrderLineItemId": rfo_line,
                        "quantity": line.quantity,
                        "dispositionType": "RESTOCKED" if restock else "NOT_RESTOCKED",
                        **({"locationId": self.s.restock_location_id} if restock else {}),
                    }
                ]
            lines.append(item)
        payload: dict[str, Any] = {
            "returnId": ret.shopify.return_id,
            "returnLineItems": lines,
            "notifyCustomer": self.s.shopify_notify_customer,
        }
        if ret.resolution == Resolution.exchange:
            exchanged = [ln for ln in ret.lines if ln.exchange_variant_id]
            payload["exchangeLineItems"] = [
                {"id": eid, "quantity": ln.quantity}
                for eid, ln in zip(ret.shopify.exchange_line_item_ids, exchanged, strict=True)
            ]
        elif ret.resolution == Resolution.store_credit:
            payload["financialTransfer"] = {
                "issueRefund": {
                    "orderTransactions": [],
                    "refundMethods": [
                        {
                            "storeCreditRefund": {
                                "amount": {
                                    "amount": to_amount(ret.money.items_pence),
                                    "currencyCode": ret.currency,
                                }
                            }
                        }
                    ],
                }
            }
        else:
            payload["financialTransfer"] = {
                "issueRefund": {"orderTransactions": self._allocate(ret, ret.money.refund_pence)}
            }
            if ret.money.shipping_refund_pence:
                payload["refundShipping"] = {
                    "shippingRefundAmount": {
                        "amount": to_amount(ret.money.shipping_refund_pence),
                        "currencyCode": ret.currency,
                    }
                }
        return payload

    def _allocate(self, ret: Return, pence: int) -> list[dict[str, Any]]:
        """Spread a refund over the order's successful payments, largest first."""
        money = self.shopify.order_money(ret.order_id)
        paid = sorted(
            (
                t
                for t in money.transactions
                if t.kind in ("SALE", "CAPTURE") and t.status == "SUCCESS"
            ),
            key=lambda t: t.amount_pence,
            reverse=True,
        )
        out, left = [], pence
        for t in paid:
            if left <= 0:
                break
            take = min(left, t.amount_pence)
            out.append(
                {
                    "parentId": t.id,
                    "transactionAmount": {"amount": to_amount(take), "currencyCode": ret.currency},
                }
            )
            left -= take
        if left > 0:
            raise ActionError(f"The order's payments do not cover a {gbp(pence)} refund.", 422)
        return out

    def _process(self, ret: Return, actor: str) -> None:
        if not ret.shopify.return_id:
            ret.last_error = "There is no Shopify return to process; approve it first."
            return
        if not ret.shopify.processed:
            try:
                self.shopify.process_return(self.process_payload(ret), f"{ret.id}:process")
            except (ShopifyError, ActionError) as exc:
                ret.last_error = f"Shopify did not process the return: {exc}"
                self._event(ret, "process_failed", actor, {"error": str(exc)})
                return
            ret.shopify.processed = True
            self._event(ret, "processed", actor, {"outcome": self._outcome_sentence(ret)})
        if (
            ret.resolution == Resolution.store_credit
            and ret.money.bonus_pence
            and not ret.shopify.store_credit_transaction_id
        ):
            try:
                ret.shopify.store_credit_transaction_id = self.shopify.credit(
                    ret.customer_id, ret.money.bonus_pence, ret.currency, f"{ret.id}:bonus"
                )
            except ShopifyError as exc:
                ret.last_error = f"Credit issued, but the bonus was not: {exc}"
                self._event(ret, "bonus_failed", actor, {"error": str(exc)})
                return
            self._event(
                ret,
                "bonus_credited",
                actor,
                {
                    "amount": gbp(ret.money.bonus_pence),
                    "transaction": ret.shopify.store_credit_transaction_id,
                },
                verified=True,
            )
        ret.last_error = None
        ret.status = Status.completed
        self._event(
            ret,
            "completed",
            actor,
            {"summary": self.summary(ret)},
            verified=self._verify_closed(ret),
        )

    def _verify_closed(self, ret: Return) -> bool:
        """Read the return back. Money resolutions must show a refund in Shopify; an exchange
        must show its exchange lines. Anything else stays unverified, and says so."""
        try:
            node = self.shopify.read_return(ret.shopify.return_id)
        except ShopifyError:
            return False
        ret.shopify.refund_ids = [r["id"] for r in (node.get("refunds") or {}).get("nodes", [])]
        if ret.resolution == Resolution.exchange:
            return bool((node.get("exchangeLineItems") or {}).get("nodes"))
        return bool(ret.shopify.refund_ids)

    # ===================================================================== upkeep

    def tick(self) -> list[str]:
        """Flag labels that are overdue. Run on a timer (or by CLIVE)."""
        flagged = []
        for ret in self.store.search(status=[Status.awaiting_label.value], limit=1000):
            due = ret.postage.label_due_at
            if (
                due
                and due < self.clock()
                and not any(e.type == "label_overdue" for e in ret.timeline)
            ):
                with self.store.lock:
                    self._event(ret, "label_overdue", "system", {"due": due.isoformat()})
                    self.store.save(ret)
                self.notifier.send("return.awaiting_label.overdue", ret)
                flagged.append(ret.id)
        return flagged

    def shopify_changed(self, shopify_return_id: str, topic: str) -> Return | None:
        """Staff can still work in the Shopify admin: keep our record in step with it."""
        ret = self.store.by_shopify_id(shopify_return_id)
        if ret is None:
            return None
        try:
            node = self.shopify.read_return(shopify_return_id)
        except ShopifyError:
            return ret
        state = node.get("status")
        with self.store.lock:
            ret = self._get(ret.id)
            if state == "CLOSED" and ret.status != Status.completed:
                ret.status = Status.completed
                self._event(ret, "completed", "shopify_admin", {"topic": topic}, verified=True)
            elif state == "CANCELED" and ret.status != Status.cancelled:
                ret.status = Status.cancelled
                self._event(ret, "cancelled", "shopify_admin", {"topic": topic}, verified=True)
            elif state == "DECLINED" and ret.status != Status.declined:
                ret.status = Status.declined
                self._event(ret, "declined", "shopify_admin", {"topic": topic}, verified=True)
            else:
                return ret
            self.store.save(ret)
        self.notifier.send("return.synced", ret)
        return ret

    # ===================================================================== views

    def public(self, ret: Return) -> dict[str, Any]:
        """What the customer sees: no internal ids, notes or errors."""
        label = self.label_link(ret.postage.label_file_id) if ret.postage.label_file_id else None
        return {
            "id": ret.id,
            "status": ret.status.value,
            "message": CUSTOMER_STATUS[ret.status],
            "created_at": ret.created_at.isoformat(),
            "resolution": ret.resolution.value,
            "items": [
                {
                    "title": ln.title,
                    "variant": ln.variant_title,
                    "quantity": ln.quantity,
                    "reason": REASON_LABELS[ln.reason],
                    "exchange_for": ln.exchange_variant_title,
                }
                for ln in ret.lines
            ],
            "postage": ret.postage.chosen.value,
            "label_url": label,
            "tracking": ret.postage.tracking,
            "tracking_url": ret.postage.tracking_url,
            "needs_tracking": ret.status == Status.awaiting_shipment
            and ret.postage.mode == PostageMode.self_ship
            and not ret.postage.tracking,
            "refund": gbp(ret.money.refund_pence) if ret.resolution == Resolution.refund else None,
            "credit": gbp(ret.money.credit_pence)
            if ret.resolution == Resolution.store_credit
            else None,
            "return_address": self._return_address()
            if ret.postage.mode == PostageMode.self_ship
            else None,
            "decline_reason": ret.decline_reason,
        }

    def _return_address(self) -> list[str]:
        s = self.s
        return [
            x
            for x in (
                s.returns_address_name,
                s.returns_address_line1,
                s.returns_address_line2,
                s.returns_address_city,
                s.returns_address_postcode,
            )
            if x
        ]

    def staff(self, ret: Return) -> dict[str, Any]:
        """What CLIVE and staff see: everything, plus the derived flags that need attention."""
        doc = json.loads(ret.model_dump_json())
        overdue = bool(
            ret.status == Status.awaiting_label
            and ret.postage.label_due_at
            and ret.postage.label_due_at < self.clock()
        )
        doc["summary"] = self.summary(ret)
        doc["attention"] = [
            *(["awaiting_label_overdue"] if overdue else []),
            *(["error"] if ret.last_error else []),
            *(
                ["needs_decision"]
                if ret.status == Status.received
                and ret.inspection
                and ret.inspection.get("condition") != "ok"
                else []
            ),
            *(["needs_approval"] if ret.status == Status.requested else []),
        ]
        doc["label_url"] = (
            self.label_link(ret.postage.label_file_id) if ret.postage.label_file_id else None
        )
        return doc
