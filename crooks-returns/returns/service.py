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
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from returns import policy, verify
from returns.labels import Label, LabelError, LabelPort, tracking_url
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
    declared_value_pence,
    gbp,
    to_amount,
)
from returns.settings import Settings, parse_order_numbers
from returns.shopify import ShopifyError, ShopifyPort, ShopifyUncertain
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

# How long a change that got no answer may still be landing in Shopify. Until then, finding
# nothing there doesn't prove it wasn't made.
SETTLE = timedelta(minutes=2)

# How couriers are named to customers (Parcel2Go still calls Evri "MyHermes").
COURIER_NAMES = {"evri": "Evri", "inpost": "InPost", "royal-mail": "Royal Mail"}

ACTIONS = ("approve", "decline", "label", "tracking", "receive", "complete", "cancel", "note")
ACTION_WORDS = {
    "approve": "Approving",
    "decline": "Declining",
    "label": "Adding the label",
    "tracking": "Adding tracking",
    "receive": "Receiving",
    "complete": "Completing",
    "cancel": "Cancelling",
    "note": "Adding the note",
}


def _after(stamp: str | None, since: datetime, *, slack_s: int) -> bool:
    """Whether Shopify's ISO timestamp is at or after `since`, allowing for clock skew."""
    if not stamp:
        return False
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return at >= since - timedelta(seconds=slack_s)


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
        self.by_order = verify.RateLimiter(limit=settings.lookup_order_limit, window_s=900)
        self.by_ip = verify.RateLimiter(limit=settings.lookup_ip_limit, window_s=900)

    # ===================================================================== the portal

    def lookup(self, order_number: str, proof: str, ip: str) -> tuple[str, Order]:
        digits = verify.normalise_order_number(order_number)
        if not digits or not (proof or "").strip():
            raise ActionError(verify.NOT_FOUND, 404)
        pilot = self.pilot_orders()
        if pilot and digits not in pilot:
            raise ActionError("Online returns are not open yet. Please contact us.", 403)
        if self.by_order.blocked(digits) or self.by_ip.blocked(ip):
            raise ActionError(verify.LOCKED, 429)
        matches = [o for o in self.shopify.find_orders(digits) if verify.proof_matches(o, proof)]
        if len(matches) != 1:
            self.by_order.hit(digits)
            self.by_ip.hit(ip)
            raise ActionError(verify.NOT_FOUND, 404)
        order = matches[0]
        return verify.session_for(order.id, self.s.session_secret, self.s.session_ttl_s), order

    def pilot_orders(self) -> set[str]:
        """Order numbers allowed to use the portal while testing; empty means open to all.
        Set from the admin screen once, after which it overrides RETURNS_PILOT_ORDER_NUMBERS."""
        saved = self.store.get_option("pilot_order_numbers")
        return self.s.pilot_orders() if saved is None else parse_order_numbers(saved)

    def set_pilot_orders(self, numbers: str, actor: str) -> set[str]:
        pilot = parse_order_numbers(numbers)
        self.store.set_option("pilot_order_numbers", ",".join(sorted(pilot)))
        log.info("pilot set to %s by %s", ",".join(sorted(pilot)) or "everyone", actor)
        return pilot

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
                    # The size they have and the product's size chart (crooks.measurements).
                    "size": line.size,
                    "size_chart": line.size_chart,
                }
            )
        notice = None
        if not order.lines:
            notice = (
                "This order hasn't been sent yet, so there's nothing to return. "
                "If you need to change or cancel it, contact us."
                if order.fulfilled_at is None
                else "Everything on this order has already been returned."
            )
        return {
            "order": order.name,
            "notice": notice,
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
        courier: str | None = None,
    ) -> Return:
        drop_off = None
        if courier and postage in (Postage.free_label, Postage.paid_label):
            drop_off = next(
                (o for o in self.drop_off_options(order) if o["courier"] == courier), None
            )
            if drop_off is None:
                raise ActionError("That drop-off option isn't available. Choose another.", 422)
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
                    line.exchange_price_pence = v.price_pence
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
                    chosen=postage,
                    paid_by="customer" if chosen.fee_pence else "crooks",
                    service=drop_off["courier"] if drop_off else None,
                    service_name=drop_off["name"] if drop_off else None,
                    carrier=drop_off["courier_name"] if drop_off else None,
                    shops=drop_off["shops"] if drop_off else [],
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
                    "drop_off": ret.postage.service_name,
                    "summary": self.summary(ret),
                },
            )
            self._stamp(ret, 0, "portal")
            self.store.save(ret)
        self.notifier.send("return.requested", ret)
        return ret

    def drop_off_options(self, order: Order) -> list[dict[str, Any]]:
        """Where the customer could drop a free label return, with the nearest shops, when
        labels come from a service that offers a choice (Parcel2Go). Empty otherwise."""
        options_for = getattr(self.labels, "options", None)
        address = order.shipping_address or {}
        postcode = address.get("zip") or order.shipping_zip
        if not options_for or not postcode or (address.get("countryCodeV2") or "GB") != "GB":
            return []
        if not self.labels.available()[0]:
            return []
        try:
            found = options_for(postcode)
        except LabelError as exc:
            log.warning("drop-off options for %s: %s", order.name, exc)
            return []
        return [
            {
                "courier": o.courier,
                "courier_name": COURIER_NAMES.get(o.courier, o.courier_name),
                "name": o.service_name,
                "printer": o.printer,
                "locker": o.locker,
                "price_pence": o.price_pence,
                "shops": [
                    {
                        "name": sh.name,
                        "address": sh.address,
                        "postcode": sh.postcode,
                        "distance_m": sh.distance_m,
                        "hours": sh.hours,
                    }
                    for sh in o.shops
                ],
            }
            for o in found
        ]

    def customer_tracking(self, order: Order, return_id: str, number: str) -> Return:
        ret = self._get(return_id)
        if ret.order_id != order.id:
            raise ActionError("Return not found.", 404)
        return self.execute(
            return_id,
            "tracking",
            {"number": number},
            "customer",
            f"customer-tracking-{number}",
            source="portal",
        )["return_doc"]

    def courier_tracking(
        self, order_line_id: str, stage: str, description: str, event_id: str
    ) -> Return | None:
        """A tracking update from Parcel2Go for a label we bought. Dropped off moves the return
        to in transit; delivered flags it for staff to check and receive."""
        if event_id and self.store.remembered(f"p2g-webhook:{event_id}") is not None:
            return None
        with self.store.lock:
            ret = next(
                (
                    r
                    for r in self.store.search(open_only=True, limit=5000)
                    if (r.postage.label_ref or "").startswith("p2g:")
                    and r.postage.label_ref.split(":")[2] == order_line_id
                ),
                None,
            )
            if ret is None or ret.postage.courier_stage == stage:
                return ret
            first = len(ret.timeline)
            ret.postage.courier_stage = stage
            moving = stage in (
                "DroppedOff",
                "Collected",
                "InTransit",
                "AtDepot",
                "DeliveryScheduled",
            )
            if stage == "Delivered" or (
                moving and ret.status in (Status.awaiting_shipment, Status.awaiting_label)
            ):
                if ret.status in (Status.awaiting_shipment, Status.awaiting_label):
                    ret.status = Status.in_transit
                self._event(
                    ret,
                    "delivered_to_us" if stage == "Delivered" else "in_transit",
                    "Parcel2Go",
                    {"stage": stage, "courier": description},
                    verified=True,
                )
            self._stamp(ret, first, "system")  # the courier's webhook
            self.store.save(ret)
            if event_id:
                self.store.remember(f"p2g-webhook:{event_id}", {"return": ret.id})
        self.notifier.send(f"return.courier.{stage.lower()}", ret)
        return ret

    # ===================================================================== actions

    def _get(self, return_id: str) -> Return:
        ret = self.store.get(return_id)
        if ret is None:
            raise ActionError("Return not found.", 404)
        return ret

    @staticmethod
    def _stamp(ret: Return, first: int, source: str) -> None:
        for e in ret.timeline[first:]:
            e.source = e.source or source

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
                    will.append(self._label_plan(ret))
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
            if ret.shopify.create_unknown_at is not None and not ret.shopify.return_id:
                will.append(
                    "First check Shopify for a return the earlier approval may have made, and "
                    "cancel it there if it did."
                )
                calls += ["orderReturns", "returnCancel (only if found)"]
                will.append(f"Decline: {params.get('reason') or 'no reason given'}.")
            else:
                will.append(
                    f"Decline: {params.get('reason') or 'no reason given'}. "
                    "Nothing in Shopify changes."
                )
        elif action == "label":
            self._require(ret, Status.awaiting_label)
            if params.get("tracking"):
                will.append(f"Attach tracking {params['tracking']} to the Shopify return.")
            else:
                will.append(self._label_plan(ret))
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
            if ret.shopify.create_unknown_at is not None and not ret.shopify.return_id:
                will.append(
                    "Check Shopify for a return the earlier approval may have made, cancel it "
                    "there if it did, then cancel this one."
                )
                calls += ["orderReturns", "returnCancel (only if found)"]
            else:
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

    def _label_plan(self, ret: Return) -> str:
        """What buying the label will do, with the real price where the provider quotes."""
        name = getattr(self.labels, "name", "the label service")
        options_for = getattr(self.labels, "options", None)
        if not options_for:
            return f"Buy a return label in {name} and email it to the customer."
        order = self.shopify.get_order(ret.order_id)
        address = (order.shipping_address if order else None) or {}
        value = declared_value_pence(ret.lines)
        try:
            options = options_for(address.get("zip") or "", value, with_shops=False)
        except LabelError as exc:
            return f"Try to book a label, but {name} answered: {exc}"
        pick = next((o for o in options if o.courier == ret.postage.service), None)
        pick = pick or (options[0] if options else None)
        if pick is None:
            return (
                f"{name} has no drop-off service for this address, so it will wait as "
                "awaiting_label for you to add tracking."
            )
        balance = getattr(self.labels, "balance_pence", lambda: None)()
        low = balance is not None and balance < pick.price_pence
        return (
            f"Book {COURIER_NAMES.get(pick.courier, pick.courier_name)} ({pick.service_name}) "
            f"for {gbp(pick.price_pence)} from {name} PrePay"
            + (f", balance {gbp(balance)}" if balance is not None else "")
            + (" - NOT ENOUGH, top up first" if low else "")
            + ". The customer gets the label by email and "
            + ("a QR code on the returns page." if not pick.printer else "prints it.")
        )

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
        self,
        return_id: str,
        action: str,
        params: dict[str, Any],
        actor: str,
        key: str,
        source: str = "system",
    ) -> dict[str, Any]:
        """The one way a return changes, whoever asks: the screen, CLIVE, the command line or
        the customer. `source` is recorded on every event the action makes."""
        if action not in ACTIONS:
            raise ActionError(f"Unknown action {action}.", 404)
        if not key:
            raise ActionError("An idempotency key is required.", 422)
        scoped = f"{return_id}:{action}:{key}"
        asked = hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
        with self.store.lock:
            done = self.store.remembered(scoped)
            if done is not None:
                if done.get("_params", asked) != asked:
                    # A retry must be the same request; a new request needs a new key.
                    raise ActionError(
                        "That key was already used for a different request. Use a new key.",
                        409,
                    )
                done = {k: v for k, v in done.items() if not k.startswith("_")}
                return {**done, "replayed": True, "return_doc": self._get(return_id)}
            self.preview(return_id, action, params)  # every rule a preview checks, execute checks
            ret = self._get(return_id)
            before = ret.status
            first_event = len(ret.timeline)
            try:
                getattr(self, f"_do_{action}")(ret, params, actor)
            except Exception as exc:
                # Keep what was done before the failure: a label paid for, a Shopify return
                # made. Lost, a retry would buy or create it again; kept, the retry settles it.
                interrupted = not isinstance(exc, ActionError)
                if interrupted:
                    log.exception("%s on %s was interrupted", action, return_id)
                    ret.last_error = (
                        f"{ACTION_WORDS.get(action, action)} was interrupted before it finished. "
                        "What was done is saved; look at the return before repeating it."
                    )
                    self._event(
                        ret,
                        "action_interrupted",
                        actor,
                        {"action": action, "error": type(exc).__name__},
                    )
                self._stamp(ret, first_event, source)
                self.store.save(ret)
                if interrupted:
                    raise ActionError(ret.last_error or "Interrupted.", 503) from exc
                raise
            self._stamp(ret, first_event, source)
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
            self.store.remember(scoped, {**out, "_params": asked})
        self.notifier.send(f"return.{action}", ret)
        return {**out, "return_doc": ret}

    # -------------------------------------------------------------- action bodies

    def _do_approve(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        mode = self._mode(ret, params)
        ret.postage.mode = mode
        if not ret.shopify.return_id and ret.shopify.create_unknown_at is not None:
            if not self._reconcile_return(ret, actor):
                return
        if not ret.shopify.return_id:
            # Written down before it is sent: if the answer is lost, or this process stops
            # before the outcome is saved, the next approval checks Shopify instead of making
            # a second return.
            ret.shopify.create_unknown_at = self.clock()
            self.store.save(ret)
            try:
                created = self.shopify.create_return(ret, self.shopify.reason_ids())
            except ShopifyUncertain as exc:
                ret.last_error = (
                    "Shopify didn't answer, so it may have created the return. Approving again "
                    "checks Shopify first and never makes a second one."
                )
                self._event(ret, "approve_unknown", actor, {"error": str(exc)})
                return
            except ShopifyError as exc:
                ret.shopify.create_unknown_at = None  # a definite refusal: nothing was made
                ret.last_error = f"Shopify did not create the return: {exc}"
                self._event(ret, "approve_failed", actor, {"error": str(exc)})
                return
            ret.shopify.create_unknown_at = None
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

    def _reconcile_return(self, ret: Return, actor: str) -> bool:
        """After an uncertain returnCreate: adopt the return it made, or prove it made none.
        True when it is safe to go on (adopted, or nothing there); False to stop and say why."""
        try:
            found = self.shopify.order_returns(ret.order_id)
        except ShopifyError as exc:
            ret.last_error = (
                f"Couldn't check Shopify for the earlier attempt ({exc}); nothing was sent again."
            )
            self._event(ret, "approve_unknown", actor, {"error": str(exc), "check": "failed"})
            return False
        want = {ln.fulfillment_line_item_id for ln in ret.lines}
        since = ret.shopify.create_unknown_at
        mine = {r.shopify.return_id for r in self.store.search(limit=100_000) if r.id != ret.id}
        matches = [
            c
            for c in found
            if set(c.get("return_line_item_ids") or {}) == want
            and c.get("status") in ("OPEN", "REQUESTED")
            and c.get("return_id") not in mine
            and (since is None or _after(c.get("created_at"), since, slack_s=300))
        ]
        if len(matches) > 1:
            ret.last_error = (
                f"Shopify has {len(matches)} returns that could be this one. Check the order in "
                "Shopify; nothing was sent again."
            )
            self._event(ret, "approve_unknown", actor, {"candidates": len(matches)})
            return False
        if not matches and since is not None and self.clock() < since + SETTLE:
            # A request that timed out here can still be finishing in Shopify: "none yet" only
            # proves "none" once it has had time to land.
            ret.last_error = (
                "Shopify may still be finishing the earlier attempt. Try again in a couple of "
                "minutes; nothing was sent again."
            )
            self._event(ret, "approve_unknown", actor, {"check": "too soon to tell"})
            return False
        ret.shopify.create_unknown_at = None
        if matches:
            fields = {k: v for k, v in matches[0].items() if k not in ("status", "created_at")}
            for k, v in fields.items():
                setattr(ret.shopify, k, v)
            self._event(
                ret,
                "approve_reconciled",
                actor,
                {"shopify_return": ret.shopify.return_name},
                verified=True,
            )
        else:
            self._event(ret, "approve_reconciled", actor, {"found": "none: safe to create"})
        return True

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
        address = dict((order.shipping_address if order else None) or {})
        # Couriers want a phone for the sender: the address's, else the order's.
        address["phone"] = address.get("phone") or (order.phone if order else None)
        address["email"] = address.get("email") or (
            (order.email or order.customer_email) if order else None
        )

        def keep(ref: str) -> None:
            # Written down before the provider is asked for money: if its answer is lost or
            # this process stops, the next try settles this order and never pays another.
            ret.postage.label_ref = ref
            ret.postage.pay_sent_at = self.clock()
            ret.last_error = (
                "Paying for the label. If this message stays, try the label again: it checks "
                "the courier first and never pays twice."
            )
            self.store.save(ret)

        try:
            label = self.labels.create(ret, address, keep)
        except LabelError as exc:
            if exc.ref:  # an order exists: keep it so a retry settles it, never buys twice
                ret.postage.label_ref = exc.ref
            if exc.paid is not None:  # the provider answered: paid, or definitely not
                ret.postage.pay_sent_at = None
            ret.last_error = str(exc)
            if exc.paid:
                self._event(ret, "label_paid_not_collected", actor, {"why": str(exc)})
            self._await_label(ret, actor, str(exc))
            return
        self._label_ready(ret, actor, label)

    def _label_ready(self, ret: Return, actor: str, label: Label) -> None:
        """Keep a bought label, then give it to the customer through Shopify."""
        file_id = self.store.put_file(ret.id, "application/pdf", label.pdf) if label.pdf else None
        ret.postage.carrier, ret.postage.label_ref = label.carrier, label.ref
        ret.postage.pay_sent_at = None  # paid: nothing is in flight
        ret.postage.tracking = label.tracking
        ret.postage.tracking_url = label.tracking_url or (
            tracking_url(label.tracking) if label.tracking else None
        )
        ret.postage.label_file_id = file_id
        if label.qr_png:
            ret.postage.qr_file_id = self.store.put_file(ret.id, "image/png", label.qr_png)
        ret.postage.drop_off_text = label.drop_off_code
        if label.service:
            ret.postage.service = label.service
        ret.postage.service_name = label.service_name or ret.postage.service_name
        ret.postage.label_price_pence = label.price_pence
        self._event(
            ret,
            "label_bought",
            actor,
            {
                "service": label.service_name or label.carrier,
                "cost": gbp(label.price_pence) if label.price_pence is not None else None,
                "ref": label.ref.split(":")[1] if label.ref.startswith("p2g:") else label.ref,
                "qr_code": bool(label.qr_png),
            },
            verified=True,
        )
        # Shopify's return email links the label; the QR code is on the returns page.
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
        if ret.shopify.attach_unknown_at is not None:
            # An earlier hand-over got no answer: it may already have emailed the customer.
            settled = self._reconcile_attach(ret, actor)
            if settled is not None:
                return settled
        # Written down before it is sent, as for returnCreate.
        ret.shopify.attach_unknown_at = self.clock()
        self.store.save(ret)
        try:
            ret.shopify.reverse_delivery_id = self.shopify.attach_shipping(
                ret.shopify.reverse_fulfillment_order_ids[0],
                ret.postage.tracking,
                ret.postage.tracking_url,
                label_url,
                notify,
            )
        except ShopifyUncertain as exc:
            ret.last_error = (
                "Shopify didn't answer, so the label may already be with the customer. It is "
                "checked in Shopify before it is ever sent again."
            )
            self._event(ret, "shipping_attach_unknown", actor, {"error": str(exc)})
            return False
        except ShopifyError as exc:
            ret.shopify.attach_unknown_at = None  # a definite refusal: nothing was sent
            ret.last_error = f"Shopify did not take the shipping details: {exc}"
            self._event(ret, "shipping_attach_failed", actor, {"error": str(exc)})
            return False
        ret.shopify.attach_unknown_at = None
        ret.last_error = None
        self._event(
            ret,
            "shipping_attached",
            actor,
            {
                "tracking": ret.postage.tracking,
                # Parcel2Go refs carry the order's access hash: show the order number only.
                "label_ref": (ret.postage.label_ref or "").split(":")[1]
                if (ret.postage.label_ref or "").startswith("p2g:")
                else ret.postage.label_ref,
                "reverse_delivery": ret.shopify.reverse_delivery_id,
            },
            verified=True,
        )
        return True

    def _reconcile_attach(self, ret: Return, actor: str) -> bool | None:
        """True: the earlier hand-over happened (adopted). False: couldn't tell, stop. None: it
        didn't happen, so sending it now is safe."""
        assert ret.shopify.return_id
        target = ret.shopify.reverse_fulfillment_order_ids[0]
        try:
            node = self.shopify.read_return(ret.shopify.return_id)
        except ShopifyError as exc:
            ret.last_error = (
                f"Couldn't check Shopify for the earlier hand-over ({exc}); not sent again."
            )
            return False
        found = [
            d["id"]
            for rfo in (node.get("reverseFulfillmentOrders") or {}).get("nodes") or []
            if rfo.get("id") == target
            for d in (rfo.get("reverseDeliveries") or {}).get("nodes") or []
        ]
        since = ret.shopify.attach_unknown_at
        if not found and since is not None and self.clock() < since + SETTLE:
            ret.last_error = (
                "Shopify may still be finishing the earlier hand-over. Try again in a couple of "
                "minutes; it was not sent again."
            )
            return False
        ret.shopify.attach_unknown_at = None
        if not found:
            return None
        ret.shopify.reverse_delivery_id = found[0]
        ret.last_error = None
        self._event(
            ret,
            "shipping_attached",
            actor,
            {"reverse_delivery": found[0], "reconciled": True},
            verified=True,
        )
        return True

    def _settle_unknown_create(self, ret: Return, actor: str) -> None:
        """Before a return is ended here, settle an earlier returnCreate that got no answer, so
        a return it may have made in Shopify is never left open behind this one."""
        if ret.shopify.return_id or ret.shopify.create_unknown_at is None:
            return
        if not self._reconcile_return(ret, actor):
            raise ActionError(ret.last_error or "Couldn't check Shopify; nothing changed.", 409)

    def _cancel_in_shopify(self, ret: Return, actor: str) -> bool:
        assert ret.shopify.return_id
        try:
            self.shopify.cancel_return(ret.shopify.return_id)
        except ShopifyUncertain as exc:
            ret.last_error = (
                "Shopify didn't answer, so the return may already be cancelled there. Check the "
                "order in Shopify; this return has not been changed."
            )
            self._event(ret, "cancel_unknown", actor, {"error": str(exc)})
            return False
        except ShopifyError as exc:
            ret.last_error = f"Shopify did not cancel the return: {exc}"
            self._event(ret, "cancel_failed", actor, {"error": str(exc)})
            return False
        return True

    def _do_decline(self, ret: Return, params: dict[str, Any], actor: str) -> None:
        self._settle_unknown_create(ret, actor)
        if ret.shopify.return_id and not self._cancel_in_shopify(ret, actor):
            return  # the earlier approval did make one, and it couldn't be cancelled
        ret.status = Status.declined
        ret.decline_reason = (params.get("reason") or "").strip() or None
        detail: dict[str, Any] = {"reason": ret.decline_reason}
        if ret.shopify.return_id:  # the earlier approval had made one: cancelled above
            detail["shopify_return_cancelled"] = ret.shopify.return_name
        self._event(ret, "declined", actor, detail)

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
        self._settle_unknown_create(ret, actor)
        if ret.shopify.return_id and not self._cancel_in_shopify(ret, actor):
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
            # One exchange line per unit (see return_input), so each is processed singly.
            assert len(ret.shopify.exchange_line_item_ids) == sum(ln.quantity for ln in exchanged)
            payload["exchangeLineItems"] = [
                {"id": eid, "quantity": 1} for eid in ret.shopify.exchange_line_item_ids
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
        must show its new items free to ship (not held). Anything else stays unverified, and
        says so."""
        try:
            node = self.shopify.read_return(ret.shopify.return_id)
        except ShopifyError:
            return False
        ret.shopify.refund_ids = [r["id"] for r in (node.get("refunds") or {}).get("nodes", [])]
        if ret.resolution == Resolution.exchange:
            line_ids = [
                li["id"]
                for n in (node.get("exchangeLineItems") or {}).get("nodes", [])
                for li in n.get("lineItems") or []
            ]
            if not line_ids:
                return False
            # Shopify holds an exchange it thinks is owed money; that is not a finished swap.
            try:
                holds = self.shopify.exchange_holds(ret.order_id, line_ids)
            except ShopifyError:
                return False
            if holds:
                ret.last_error = (
                    "Shopify is holding the exchange item ("
                    + ", ".join(sorted(set(holds)))
                    + "). Check the order's balance, then release the hold in the order."
                )
                return False
            return True
        return bool(ret.shopify.refund_ids)

    # ===================================================================== upkeep

    def collect_labels(self) -> list[str]:
        """Finish returns whose label is bought but never reached the customer: the label
        wasn't released in time, or Shopify didn't take it. Only labels Parcel2Go confirms are
        paid are collected; nothing is ever paid for here."""
        collect = getattr(self.labels, "collect", None)
        done = []
        for found in self.store.search(status=[Status.awaiting_label.value], limit=1000):
            if not (found.postage.label_ref or "").startswith("p2g:"):
                continue
            with self.store.lock:
                ret = self._get(found.id)
                if ret.status != Status.awaiting_label:
                    continue
                first = len(ret.timeline)
                if ret.postage.label_file_id or ret.postage.qr_file_id:
                    # Collected before; only handing it to Shopify failed.
                    label = (
                        self.label_link(ret.postage.label_file_id)
                        if ret.postage.label_file_id
                        else None
                    )
                    if self._attach(
                        ret, "system", label_url=label, notify=self.s.shopify_notify_customer
                    ):
                        ret.status = Status.awaiting_shipment
                elif collect is not None:
                    try:
                        label = collect(ret)
                    except LabelError as exc:
                        ret.last_error = str(exc)
                        self.store.save(ret)
                        continue
                    self._label_ready(ret, "system", label)
                else:
                    continue
                self._stamp(ret, first, "system")  # the timer
                self.store.save(ret)
            if ret.status == Status.awaiting_shipment:
                self.notifier.send("return.label", ret)
                done.append(ret.id)
        return done

    def tick(self) -> list[str]:
        """Collect bought labels and flag labels that are overdue. Run on a timer (or by
        CLIVE)."""
        try:
            self.collect_labels()
        except Exception:  # one bad return must not stop the overdue check
            log.exception("collecting labels")
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
                    self._stamp(ret, len(ret.timeline) - 1, "system")
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
            first = len(ret.timeline)
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
            self._stamp(ret, first, "system")  # Shopify's webhook
            self.store.save(ret)
        self.notifier.send("return.synced", ret)
        return ret

    # ===================================================================== reporting

    def stats(self, since: datetime | None = None) -> dict[str, Any]:
        rows = self.store.search(since=since, limit=100_000)
        live = [r for r in rows if r.status.value not in ("declined", "cancelled")]
        value = sum(r.money.items_pence for r in live)
        kept = sum(r.money.items_pence for r in live if r.resolution != Resolution.refund)
        return {
            "returns": len(rows),
            "by_status": Counter(r.status.value for r in rows),
            "by_resolution": Counter(r.resolution.value for r in live),
            "by_reason": Counter(ln.reason.value for r in live for ln in r.lines),
            "by_sku": Counter(ln.sku or ln.title for r in live for ln in r.lines).most_common(20),
            "size_swaps": Counter(
                ln.exchange_direction for r in live for ln in r.lines if ln.exchange_direction
            ),
            "value_returned": gbp(value),
            "value_kept": gbp(kept),
            "kept_share": round(kept / value, 3) if value else None,
            "bonus_given": gbp(sum(r.money.bonus_pence for r in live)),
            "label_fees_recovered": gbp(sum(r.money.fee_pence for r in live)),
        }

    # ===================================================================== setup check

    def checks(self) -> list[dict[str, str]]:
        """Read-only: is everything connected and set the way the returns need it?
        state is ok, fix (something to sort before going live) or note."""
        from returns.shopify import REQUIRED_SCOPES

        s, out = self.s, []

        def say(group: str, ok: bool | None, text: str) -> None:
            out.append(
                {
                    "group": group,
                    "state": {True: "ok", False: "fix", None: "note"}[ok],
                    "text": text,
                }
            )

        try:
            scopes = set(self.shopify.app_scopes())
            missing = [x for x in REQUIRED_SCOPES if x not in scopes]
            say(
                "Shopify",
                not missing,
                "App permissions" + (f": missing {', '.join(missing)}" if missing else ""),
            )
            found = len(self.shopify.reason_ids())
            say("Shopify", found == 6, f"Return reasons matched: {found} of 6")
        except ShopifyError as exc:
            say("Shopify", False, f"Cannot reach the store: {exc}")
        pilot = sorted(self.pilot_orders(), key=int)
        say(
            "Settings",
            None,
            "Testing: only orders " + ", ".join(pilot) if pilot else "Open to every order",
        )
        say(
            "Settings",
            bool(s.restock_location_id),
            "Restock location "
            + ("set" if s.restock_location_id else "not set: returned stock is not restocked"),
        )
        say(
            "Settings",
            bool(s.returns_address_line1 and s.returns_address_postcode),
            "Returns address "
            + (", ".join(self._return_address()) if s.returns_address_line1 else "not set"),
        )
        labels_ok, why = self.labels.available()
        say(
            "Settings",
            True if labels_ok else None,
            f"{getattr(self.labels, 'name', 'Labels')} "
            + ("connected" if labels_ok else f"off ({why})"),
        )
        balance_of = getattr(self.labels, "balance_pence", None)
        if labels_ok and balance_of:
            balance = balance_of()
            say(
                "Settings",
                None if balance is None else balance >= 1000,
                "PrePay balance "
                + (
                    "unknown (Parcel2Go didn't answer)"
                    if balance is None
                    else gbp(balance) + ("" if balance >= 1000 else ": running low, top up")
                ),
            )
        say(
            "Settings",
            None,
            "Label price "
            + (
                gbp(s.return_label_cost_pence)
                if s.return_label_cost_pence is not None
                else "not set: change-of-mind refunds are self-ship only"
            ),
        )
        say(
            "Settings",
            bool(s.keys("read")),
            "CLIVE keys " + ("set" if s.keys("read") else "not set"),
        )
        return out

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
            # How staff approved it, which can differ from what the customer picked.
            "postage_mode": ret.postage.mode.value if ret.postage.mode else None,
            "label_url": label,
            # A printer-free label: the code to show at the shop and where the shops are.
            "drop_off": {
                "courier": ret.postage.carrier,
                "service": ret.postage.service_name,
                "qr_url": self.label_link(ret.postage.qr_file_id)
                if ret.postage.qr_file_id
                else None,
                "code": ret.postage.drop_off_text,
                "shops": ret.postage.shops,
            }
            if ret.status == Status.awaiting_shipment
            and (ret.postage.qr_file_id or ret.postage.shops)
            else None,
            "tracking": ret.postage.tracking,
            "tracking_url": ret.postage.tracking_url,
            "needs_tracking": ret.status == Status.awaiting_shipment
            and ret.postage.mode == PostageMode.self_ship
            and not ret.postage.tracking,
            "refund": gbp(ret.money.refund_pence) if ret.resolution == Resolution.refund else None,
            "credit": gbp(ret.money.credit_pence)
            if ret.resolution == Resolution.store_credit
            else None,
            # Only while they still have to post it.
            "return_address": self._return_address()
            if ret.postage.mode == PostageMode.self_ship and ret.status == Status.awaiting_shipment
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
            *(
                ["delivered_unchecked"]
                if ret.status == Status.in_transit and ret.postage.courier_stage == "Delivered"
                else []
            ),
        ]
        doc["label_url"] = (
            self.label_link(ret.postage.label_file_id) if ret.postage.label_file_id else None
        )
        return doc
