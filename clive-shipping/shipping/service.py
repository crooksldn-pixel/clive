"""The shipping workflow for one shop: discover → prepare → (answer) → preview → buy → fulfil.

Purchases (purchase.py) owns the money boundary. This module owns everything around it:
reading Shopify, deciding readiness, remembering answers (and writing them back to Shopify),
choosing the package, describing duties honestly, and making Shopify reflect the label.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from shipping import duties, packages, rates, readiness
from shipping.models import (
    CustomsMode,
    DocumentKind,
    Event,
    PackagePlan,
    Question,
    Quote,
    Shipment,
)
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.providers.base import ProviderError, ShippingProvider
from shipping.purchase import ActionError, Purchases
from shipping.shopify import FoSnapshot, ShopifyError, ShopifyPort, ShopifyRefused
from shipping.states import move
from shipping.store import Conflict, Store, new_id, now

log = logging.getLogger("shipping.service")

# Shopify-known tracking company names make the number clickable in admin and emails.
TRACKING_COMPANY = {
    "dpd": "DPD UK",
    "evri": "Evri",
    "myhermes": "Evri",
    "hermes": "Evri",
    "ups": "UPS",
    "parcelforce": "Parcelforce",
    "royal mail": "Royal Mail",
    "dhl": "DHL Express",
    "fedex": "FedEx",
    "usps": "USPS",
    "asendia": "Asendia USA",
    "inpost": "InPost",
}

PRE_PURCHASE = (S.discovered, S.needs_attention, S.ready)


def tracking_company(carrier: str) -> str:
    key = carrier.lower()
    return next((v for k, v in TRACKING_COMPANY.items() if k in key), carrier)


class ShippingService:
    def __init__(
        self,
        store: Store,
        shopify: ShopifyPort,
        provider: ShippingProvider,
        purchases: Purchases | None = None,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.store = store
        self.shopify = shopify
        self.provider = provider
        self.clock = clock
        self.purchases = purchases or Purchases(store, provider, clock=clock)

    # ------------------------------------------------------------------ helpers

    def _get(self, shop: str, sid: str) -> Shipment:
        s = self.store.get(shop, sid)
        if s is None:
            raise ActionError("Shipment not found.", 404)
        return s

    def _event(
        self, s: Shipment, kind: str, actor: str, detail: dict | None = None, verified: bool = False
    ) -> None:
        s.timeline.append(
            Event(at=self.clock(), type=kind, actor=actor, detail=detail or {}, verified=verified)
        )

    def _to(
        self,
        s: Shipment,
        status: S,
        event: str,
        actor: str = "system",
        detail: dict | None = None,
        verified: bool = False,
    ) -> None:
        if s.status != status:
            move(
                s,
                status,
                at=self.clock(),
                actor=actor,
                event=event,
                detail=detail,
                verified=verified,
            )

    def _alert(self, s: Shipment, text: str) -> None:
        if text not in s.alerts:
            s.alerts.append(text)
            self._event(s, "alert", "system", {"text": text})

    # ------------------------------------------------------------------ discovery

    def sync(self, shop: str) -> dict[str, int]:
        """Find open international fulfillment orders; refresh what we already know."""
        cfg = self.store.config(shop)
        seen, made = set(), 0
        for snap in self.shopify.open_fulfillment_orders():
            if not snap.lines or not snap.destination.country:
                continue
            origin_country = (cfg.origin.country if cfg.origin else "") or snap.origin.country
            if snap.destination.country == origin_country:
                continue  # domestic: Shopify's own flow handles it
            if cfg.origin is None:
                cfg.origin, cfg.origin_location_id = snap.origin, snap.origin_location_id
                self.store.save_config(cfg)
            seen.add(snap.id)
            s = self._by_fo(shop, snap.id)
            if s is None:
                at = self.clock()
                s = Shipment(
                    id=new_id("shp"),
                    shop=shop,
                    order_id=snap.order_id,
                    order_name=snap.order_name,
                    fulfillment_order_id=snap.id,
                    destination=snap.destination,
                    status=S.discovered,
                    currency=snap.currency,
                    created_at=at,
                    updated_at=at,
                )
                self._event(s, "discovered", "system", {"order": snap.order_name})
                self.store.save(s)
                made += 1
            self._refresh(shop, s.id, snap)
        for s in self.store.shipments(shop, [x.value for x in PRE_PURCHASE]):
            if s.fulfillment_order_id not in seen:
                self._refresh(shop, s.id)  # re-reads it: closed or cancelled shipments drop out
        return {"open": len(seen), "new": made}

    def _by_fo(self, shop: str, fo_id: str) -> Shipment | None:
        return next(
            (s for s in self.store.shipments(shop) if s.fulfillment_order_id == fo_id), None
        )

    # ------------------------------------------------------------------ prepare

    def _refresh(self, shop: str, sid: str, snap: FoSnapshot | None = None) -> None:
        """prepare() for the background sync: if someone changed the shipment meanwhile (a
        purchase, an answer), their change stands and the next sync picks it up."""
        try:
            self.prepare(shop, sid, snap)
        except Conflict:
            log.info("shipment %s changed during refresh; left for the next sync", sid)

    def prepare(self, shop: str, sid: str, snap: FoSnapshot | None = None) -> Shipment:
        s = self._get(shop, sid)
        if snap is None:
            snap = self.shopify.fulfillment_order(s.fulfillment_order_id)
        if s.money_may_have_moved:
            alerts = len(s.alerts)
            self._watch_after_purchase(s, snap)
            # Only an alert is ever added after money moved; don't rewrite it otherwise (a
            # needless save here races the purchase's own saves).
            return self.store.save(s) if len(s.alerts) != alerts else s
        if snap is None or not snap.open:
            why = "cancelled" if snap is not None and snap.order_cancelled else "closed in Shopify"
            if s.status in PRE_PURCHASE:
                self._to(s, S.cancelled, "order_closed", detail={"why": why})
                s.questions, s.quote = [], None
            return self.store.save(s)

        cfg = self.store.config(shop)
        items = self.shopify.item_facts(
            [ln.inventory_item_id for ln in snap.lines if ln.inventory_item_id]
        )
        s.order_name, s.destination, s.currency = snap.order_name, snap.destination, snap.currency
        s.lines = readiness.resolve_lines(self.store, shop, snap, items)
        s.package = packages.plan(self.store, cfg, s.lines, s.package)
        value = Money(
            minor=sum(ln.unit_value.minor * ln.quantity for ln in s.lines), currency=s.currency
        )
        s.duties = duties.terms(
            cfg.duties, s.destination.country, value, postcode=s.destination.postcode
        )
        s.questions = readiness.questions(self.store, shop, s.lines, s.package is not None)
        if s.questions:
            s.quote = None
            self._to(
                s,
                S.needs_attention,
                "needs_attention",
                detail={"questions": [q.kind for q in s.questions]},
            )
            return self.store.save(s)
        try:
            options = self.provider.quotes(s)
        except ProviderError as exc:
            # Parcel2Go couldn't be asked: not the same as "no courier will take it".
            s.quote, s.rates = None, []
            s.questions = [
                Question(
                    kind="provider_unavailable",
                    subject="rates",
                    text=f"Couldn't get prices from {self.provider.name} just now ({exc}). "
                    "CLIVE tries again shortly; nothing needs changing.",
                )
            ]
            self._to(s, S.needs_attention, "provider_unavailable", detail={"why": str(exc)})
            return self.store.save(s)
        s.rates = options
        rec = self.recommendation(s)
        chosen = next(
            (q for q in options if s.service_choice and q.service_code == s.service_choice),
            None,
        )
        if chosen is None and s.service_choice:
            self._event(s, "service_choice_dropped", "system", {"was": s.service_choice})
            s.service_choice = None  # no longer offered: back to the recommendation
        choice = chosen or (rec.recommended.quote if rec.recommended else None)
        if choice is None:
            s.quote = None
            s.questions = [
                Question(
                    kind="no_rates",
                    subject="rates",
                    text=(
                        f"No courier offered a price for this parcel to {s.destination.country}. "
                        "Check the package and weight."
                    ),
                )
            ]
            self._to(s, S.needs_attention, "no_rates", detail={})
            return self.store.save(s)
        s.quote = choice
        self._to(
            s,
            S.ready,
            "ready",
            detail={"service": choice.title, "price": str(choice.amount)},
        )
        return self.store.save(s)

    def paperwork(self, shop: str, quote: Quote, country: str) -> rates.Paperwork:
        """What this shop's own labels showed for this service and country; before any, the
        dated sandbox evidence."""
        seen = self.store.paperwork(shop, quote.service_code, country)
        if seen:
            return rates.Paperwork(CustomsMode(seen[0]), seen[1], "your labels")
        return rates.sandbox_paperwork(quote.service_code)

    def recommendation(self, s: Shipment) -> rates.Recommendation:
        cfg = self.store.config(s.shop)
        return rates.recommend(
            s.rates,
            paperwork=lambda q: self.paperwork(s.shop, q, s.destination.country),
            preferred_carriers=cfg.preferred_carriers,
        )

    def _watch_after_purchase(self, s: Shipment, snap: FoSnapshot | None) -> None:
        """After money moved we never rewrite the shipment; we only tell a person if the order
        no longer matches the label."""
        if snap is None or snap.order_cancelled:
            self._alert(
                s,
                "The order was cancelled after the label was bought. If the parcel "
                "won't be sent, cancel the label at Parcel2Go for a refund.",
            )
            return
        if (
            snap.status in ("CLOSED",)
            and s.label
            and s.label.tracking_number in (snap.tracking_numbers or [])
        ):
            return
        bought = sorted((ln.fulfillment_order_line_item_id, ln.quantity) for ln in s.lines)
        now_ = sorted((ln.id, ln.quantity) for ln in snap.lines)
        if now_ and now_ != bought and s.status == S.label_purchased:
            self._alert(
                s,
                "The order changed after the label was bought. Check the parcel "
                "still matches before sending it.",
            )

    # ------------------------------------------------------------------ answers

    def answer(
        self, shop: str, sid: str, kind: str, subject: str, value: dict[str, Any], actor: str
    ) -> Shipment:
        s = self._get(shop, sid)
        if s.status not in PRE_PURCHASE:
            raise ActionError("This order is past the point of changing its details.")
        if kind == "package":
            cfg = self.store.config(shop)
            try:
                packages.add(
                    cfg,
                    name=str(value.get("name", "")),
                    length_cm=float(value.get("length_cm", 0)),
                    width_cm=float(value.get("width_cm", 0)),
                    height_cm=float(value.get("height_cm", 0)),
                    empty_weight_g=int(value.get("empty_weight_g", 0)),
                    actor=actor,
                )
            except (TypeError, ValueError) as exc:
                raise ActionError(str(exc), 422) from exc
            self.store.save_config(cfg)
            name = cfg.packages[-1].name
            self._commit(s, lambda x: self._event(x, "package_added", actor, {"name": name}))
            return self._prepare_after_answer(shop, sid)
        line = next((ln for ln in s.lines if (ln.product_id or ln.title) == subject), None)
        if line is None:
            raise ActionError("That product isn't on this order.", 422)
        before_alerts = list(s.alerts)
        if kind == "customs":
            hs = re.sub(r"\D", "", str(value.get("hs_code", "")))
            desc = str(value.get("description", "")).strip()
            if not 6 <= len(hs) <= 10:
                raise ActionError("An HS code has 6 to 10 digits, e.g. 6109.10.", 422)
            if not 3 <= len(desc) <= 100:
                raise ActionError("Describe it in a few words, e.g. 'Men's cotton T-shirt'.", 422)
            written = self._write_product(s, line, actor, hs_code=hs)
            self._remember(shop, "product", subject, "hs_code", hs, actor, line.title, written)
            self._remember(
                shop, "product", subject, "customs_description", desc, actor, line.title, True
            )
            if line.product_type:
                self._remember(
                    shop,
                    "product",
                    subject,
                    "product_type",
                    line.product_type,
                    actor,
                    line.title,
                    True,
                )
        elif kind == "origin":
            code = str(value.get("country", "")).strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", code) or code == "ZZ":
                raise ActionError("Choose the country it was made in.", 422)
            written = self._write_product(s, line, actor, origin_country=code)
            self._remember(
                shop, "product", subject, "origin_country", code, actor, line.title, written
            )
        elif kind == "weight":
            try:
                grams = int(value.get("grams", 0))
            except (TypeError, ValueError):
                grams = 0
            if not 1 <= grams <= 30000:
                raise ActionError("Give the weight in grams, e.g. 220.", 422)
            items = self._product_items(line)
            records = self.shopify.item_facts(items)
            missing = [i for i in items if not (records.get(i) and records[i].weight_g)]
            written = self._write_items(s, missing, actor, weight_g=grams)
            for item in missing:
                self._remember(
                    shop, "item", item, "weight_g", str(grams), actor, line.title, written
                )
        else:
            raise ActionError(f"Unknown question {kind}.", 422)
        new_alerts = [a for a in s.alerts if a not in before_alerts]

        def record(x: Shipment) -> None:
            for text in new_alerts:
                self._alert(x, text)
            self._event(x, "answered", actor, {"question": kind, "product": line.title})

        self._commit(s, record)
        return self._prepare_after_answer(shop, sid)

    def _commit(self, s: Shipment, apply: Callable[[Shipment], None]) -> Shipment:
        """Save what this request did to the shipment. If something else saved it meanwhile
        (a sync, a timer), re-apply our part to the fresh copy instead of losing it. `apply`
        must be safe to run twice (alerts are de-duplicated)."""
        apply(s)
        try:
            return self.store.save(s)
        except Conflict:
            fresh = self._get(s.shop, s.id)
            apply(fresh)
            return self.store.save(fresh)

    def _prepare_after_answer(self, shop: str, sid: str) -> Shipment:
        try:
            return self.prepare(shop, sid)
        except Conflict:
            return self._get(shop, sid)  # the answer is saved; the next sync re-prepares

    def _product_items(self, line) -> list[str]:
        items = self.shopify.product_items(line.product_id) if line.product_id else []
        return items or [line.inventory_item_id]

    def _write_product(self, s: Shipment, line, actor: str, **fields) -> bool:
        return self._write_items(s, self._product_items(line), actor, **fields)

    def _write_items(self, s: Shipment, items: list[str], actor: str, **fields) -> bool:
        """Write confirmed facts to Shopify (the record). If Shopify refuses, the answer is
        still kept here and used, so the merchant is not asked again."""
        try:
            for item in items:
                self.shopify.update_item(item, **fields)
        except ShopifyError as exc:
            self._alert(
                s,
                f"Saved in CLIVE, but Shopify didn't store it ({exc}). It's still "
                "used for shipping.",
            )
            return False
        return True

    def _remember(self, shop, scope, subject, fact, value, actor, label, written) -> None:
        self.store.put_fact(
            shop,
            scope,
            subject,
            fact,
            value,
            source="merchant",
            actor=actor,
            label=label,
            shopify_written=written,
        )

    # ------------------------------------------------------------------ package choice

    def choose_package(self, shop: str, sid: str, preset_id: str, actor: str) -> Shipment:
        s = self._get(shop, sid)
        if s.status not in PRE_PURCHASE:
            raise ActionError("This order is past the point of changing its package.")
        cfg = self.store.config(shop)
        chosen = packages.preset(cfg, preset_id)
        if chosen is None:
            raise ActionError("That package doesn't exist.", 422)
        s.package = PackagePlan(
            preset_id=chosen.id,
            name=chosen.name,
            length_mm=chosen.length_mm,
            width_mm=chosen.width_mm,
            height_mm=chosen.height_mm,
            empty_weight_g=chosen.empty_weight_g,
            items_weight_g=packages.items_weight_g(s.lines) or 0,
            source="merchant",
        )
        self._event(s, "package_chosen", actor, {"package": chosen.name})
        self.store.save(s)
        return self.prepare(shop, sid)

    def choose_service(self, shop: str, sid: str, service_code: str, actor: str) -> Shipment:
        """Use another quoted service instead of the recommendation. Changes what a preview
        shows, so any earlier preview no longer buys."""
        s = self._get(shop, sid)
        if s.status not in PRE_PURCHASE:
            raise ActionError("This order is past the point of changing its service.")
        chosen = next((q for q in s.rates if q.service_code == service_code), None)
        if chosen is None:
            raise ActionError("That service isn't offered for this parcel any more.", 422)
        rec = self.recommendation(s)
        back_to_recommended = bool(
            rec.recommended and rec.recommended.quote.service_code == service_code
        )

        def record(x: Shipment) -> None:
            x.service_choice = None if back_to_recommended else service_code
            x.quote = chosen
            self._event(x, "service_chosen", actor, {"service": chosen.title})

        return self._commit(s, record)

    def _learn_paperwork(self, shop: str, sid: str) -> None:
        """Once a label's customs settle, remember them for this service and destination."""
        s = self._get(shop, sid)
        label = s.label
        settled = label is not None and (
            label.customs == CustomsMode.paper
            or (label.customs == CustomsMode.electronic and label.customs_confirmed)
        )
        service = (label.service_code if label else "") or (s.quote.service_code if s.quote else "")
        if not settled or label is None or label.paperwork_learned or not service:
            return
        invoice = label.document(DocumentKind.commercial_invoice)
        copies = invoice.copies_required if invoice and invoice.must_print else 0

        def record(x: Shipment) -> None:
            if x.label is not None:
                x.label = x.label.model_copy(update={"paperwork_learned": True})

        self._commit(s, record)
        self.store.record_paperwork(
            shop,
            service,
            s.destination.country,
            label.customs.value,
            copies,
            self.clock(),
        )

    # ------------------------------------------------------------------ buying

    def preview(self, shop: str, sid: str) -> dict[str, Any]:
        out = self.purchases.preview(shop, sid)
        s = self._get(shop, sid)
        cfg = self.store.config(shop)
        if s.duties:
            out["will"].append(f"Customs terms {s.duties.incoterm}: {s.duties.summary}")
        out["will"].append(
            f"Mark {s.order_name} fulfilled in Shopify with the tracking number"
            + (" and email the customer" if cfg.notify_customer else "")
        )
        out["duties"] = s.duties.model_dump() if s.duties else None
        return out

    def buy(self, shop: str, sid: str, basis: str, actor: str, key: str) -> dict[str, Any]:
        out = self.purchases.buy(shop, sid, basis, actor, key)
        s = self._get(shop, sid)
        if s.status == S.label_purchased:
            if s.package and s.package.preset_id and not out.get("replayed"):
                self.store.record_package_choice(
                    shop, packages.signature(s.lines), s.package.preset_id
                )
            if s.label and s.label.tracking_number:
                try:
                    self.fulfil(shop, sid, actor)
                except Conflict:
                    # The label is bought; something else saved the shipment meanwhile. The
                    # timer's fulfilment retry finishes it (it reads Shopify first).
                    log.info("fulfilment of %s raced another save; left to the timer", sid)
        try:
            self._learn_paperwork(shop, sid)
        except Conflict:
            pass  # the timer learns it next time
        out["shipment"] = self._get(shop, sid)
        out["status"] = out["shipment"].status.value
        out["error"] = out["shipment"].last_error
        return out

    # ------------------------------------------------------------------ fulfilment

    def fulfil(self, shop: str, sid: str, actor: str) -> Shipment:
        """Make Shopify show the label. Safe to repeat: it reads Shopify first, so a retry
        after a lost reply never creates a second fulfillment."""
        s = self._get(shop, sid)
        if s.status == S.fulfilled:
            return s
        if s.status not in (S.label_purchased, S.fulfillment_failed):
            raise ActionError("There's no bought label to fulfil this order with yet.")
        if not (s.label and s.label.tracking_number):
            raise ActionError("Waiting for the tracking number from the provider.")
        number = s.label.tracking_number
        if self._fulfilled_in_shopify(s, number):
            return self._fulfilled(s, actor, "Already in Shopify")
        cfg = self.store.config(shop)
        try:
            self.shopify.create_fulfillment(
                s.fulfillment_order_id,
                [(ln.fulfillment_order_line_item_id, ln.quantity) for ln in s.lines],
                tracking_company(s.label.carrier),
                number,
                s.label.tracking_url,
                cfg.notify_customer,
            )
        except ShopifyRefused as exc:
            return self._fulfil_failed(s, actor, f"Shopify didn't mark it fulfilled: {exc}.")
        except ShopifyError:
            pass  # may have happened: the read-back decides
        if self._fulfilled_in_shopify(s, number):
            return self._fulfilled(s, actor, "Created and read back")
        return self._fulfil_failed(s, actor, "Shopify didn't confirm the fulfillment yet.")

    def _fulfilled_in_shopify(self, s: Shipment, number: str) -> bool:
        try:
            snap = self.shopify.fulfillment_order(s.fulfillment_order_id)
        except ShopifyError:
            return False
        return bool(snap and number in snap.tracking_numbers)

    def _fulfilled(self, s: Shipment, actor: str, how: str) -> Shipment:
        s.last_error = None
        self._to(
            s,
            S.fulfilled,
            "fulfilled",
            actor,
            {"tracking": s.label.tracking_number, "how": how},
            verified=True,
        )
        return self.store.save(s)

    def _fulfil_failed(self, s: Shipment, actor: str, why: str) -> Shipment:
        s.last_error = (
            f"The label is bought (no need to buy again). {why} It will be retried; "
            "you can also mark it fulfilled in Shopify with the tracking number."
        )
        if s.status != S.fulfillment_failed:
            move(
                s,
                S.fulfillment_failed,
                at=self.clock(),
                actor=actor,
                event="fulfillment_failed",
                detail={"why": why},
            )
        else:
            self._event(s, "fulfillment_retry_failed", actor, {"why": why})
        return self.store.save(s)

    # ------------------------------------------------------------------ the sweep

    def tick(self, shop: str) -> dict[str, int]:
        """Reconcile purchases, retry fulfilments, refresh open orders. Webhooks only hurry
        this up; correctness never depends on them."""
        reconciled = self.purchases.reconcile_all()
        retried = 0
        for s in self.store.shipments(shop, [S.label_purchased.value, S.fulfillment_failed.value]):
            if s.label and s.label.tracking_number:
                try:
                    self.fulfil(shop, s.id, "system")
                except Conflict:
                    continue  # changed meanwhile; the next tick retries
                retried += 1
        for s in self.store.shipments(
            shop, [S.label_purchased.value, S.fulfilled.value, S.fulfillment_failed.value]
        ):
            if s.label and not s.label.paperwork_learned:
                try:
                    self._learn_paperwork(shop, s.id)
                except Conflict:
                    continue
        found = self.sync(shop)
        return {"reconciled": reconciled, "fulfil_retried": retried, **found}
