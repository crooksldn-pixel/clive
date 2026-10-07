"""Durable reviewed batches orchestrate the existing individual safety protocols."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from shipping import lifecycle
from shipping.models import OpState, ShipmentStatus
from shipping.physical_printing import PhysicalPrinting
from shipping.printing import PrintError
from shipping.providers.base import ProviderError
from shipping.providers.reporting import quote_failure
from shipping.purchase import ActionError
from shipping.service import ShippingService
from shipping.store import new_id, now

log = logging.getLogger("shipping.operations")


class Operations:
    def __init__(self, service: ShippingService, physical: PhysicalPrinting):
        self.service, self.physical, self.store = service, physical, service.store

    @staticmethod
    def safe_problem(exc: ActionError | PrintError) -> str:
        cause = exc.__cause__
        if isinstance(cause, ProviderError):
            return quote_failure("Provider", cause).safe_message
        return str(exc)

    def get(self, shop: str, bid: str) -> dict[str, Any]:
        record = self.store.batch(shop, bid)
        if record is None:
            raise ActionError("Batch not found.", 404)
        return record

    def preview(self, shop: str, kind: str, ids: list[str], actor: str, key: str):
        if kind not in ("buy", "print") or not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids):
            raise ActionError("Choose 1–100 distinct shipments and Buy or Print.", 422)
        old = self.store.batch_by_key(shop, key)
        if old:
            if old["kind"] != kind or [c["shipment_id"] for c in old["children"]] != ids:
                raise ActionError("This request key belongs to another selection.", 409)
            return old
        children = []
        for sid in ids:
            s = self.store.get(shop, sid)
            child = dict(
                shipment_id=sid,
                order=s.order_name if s else "Not found",
                key=new_id("child"),
                state="review",
                message="",
                basis=None,
                provider=None,
                service=None,
                amount_minor=0,
                currency="GBP",
            )
            try:
                if s is None:
                    raise ActionError("Shipment not found.", 404)
                printed = self.physical.summary(shop, sid)
                where = lifecycle.stage(s, printed)
                if kind == "buy":
                    if not lifecycle.may_bulk_buy(where):
                        raise ActionError(f"In {lifecycle.TITLES[where]}, not Ready to ship.")
                    if s.status != ShipmentStatus.ready or s.label or s.money_may_have_moved:
                        raise ActionError(
                            "Not ready to buy, already purchased, or awaiting reconciliation."
                        )
                    if not self.service.may_buy(s):
                        raise ActionError("Buying is not authorised for this order.", 403)
                    p = self.service.preview(shop, sid)
                    assert s.quote is not None
                    child.update(
                        basis=p["basis"],
                        provider=s.quote.provider,
                        service=p["service"]["name"],
                        amount_minor=p["money"]["shipping_minor"],
                        currency=p["money"]["currency"],
                    )
                else:
                    status = printed
                    if where in ("in_transit", "delivered"):
                        raise ActionError(
                            f"{lifecycle.TITLES[where]}: the carrier already has it. "
                            "Use explicit Reprint if a copy is needed."
                        )
                    if not status or not status["first_print_available"]:
                        raise ActionError(
                            "Already attempted/sent or uncertain. "
                            "Use explicit Reprint for an additional attempt."
                        )
                    self.physical.validate_for_print(shop, sid)
                    if s.label is None:
                        raise ActionError("No purchased label.")
                    child.update(provider=s.label.provider, service=s.label.service_name)
            except (ActionError, PrintError) as exc:
                child.update(state="excluded", message=self.safe_problem(exc))
            except Exception:
                log.exception("preflight for %s failed", sid)
                child.update(
                    state="excluded",
                    message="Preflight unavailable. Refresh this shipment and review again.",
                )
            children.append(child)
        currencies = {c["currency"] for c in children if c["state"] == "review"}
        if len(currencies) > 1:
            raise ActionError("Review different currencies in separate batches.", 422)
        record = dict(
            id=new_id("bulk"),
            kind=kind,
            state="review",
            created_at=now().isoformat(),
            expires_at=(now() + timedelta(minutes=10)).isoformat(),
            actor=actor,
            children=children,
            total_minor=sum(c["amount_minor"] for c in children if c["state"] == "review"),
            currency=next(iter(currencies), "GBP"),
        )
        with self.store.atomic():
            old = self.store.batch_by_key(shop, key)
            if old:
                if old["kind"] != kind or [c["shipment_id"] for c in old["children"]] != ids:
                    raise ActionError("This request key belongs to another selection.", 409)
                return old
            self.store.add_batch(shop, key, record)
        return record

    def confirm(self, shop: str, bid: str, actor: str):
        with self.store.atomic():
            b = self.get(shop, bid)
            if b["state"] != "review":
                return b  # A duplicate confirmation never resets finished children.
            if datetime.fromisoformat(b["expires_at"]) <= now():
                raise ActionError("Review expired. Create a fresh review.", 409)
            b.update(state="queued", confirmed_by=actor, confirmed_at=now().isoformat())
            for c in b["children"]:
                if c["state"] == "review":
                    c["state"] = "queued"
            self.store.save_batch(shop, b)
        return b

    def run(self, shop: str, bid: str):
        while True:
            with self.store.atomic():
                b = self.get(shop, bid)
                if b["state"] != "queued":
                    return
                child = next(
                    (c for c in b["children"] if c["state"] in ("queued", "running")), None
                )
                if child is None:
                    b["state"] = "complete"
                    self.store.save_batch(shop, b)
                    return
                if child["state"] == "running":
                    return  # Another process owns it; never skip ahead or submit it again.
                child.update(state="running", started_at=now().isoformat())
                self.store.save_batch(shop, b)
                c = dict(child)
            try:
                if datetime.fromisoformat(b["expires_at"]) <= now():
                    raise ActionError("Review expired before execution. Review this row again.")
                if b["kind"] == "buy":
                    out = self.service.buy(
                        shop, c["shipment_id"], c["basis"], b["confirmed_by"], c["key"]
                    )
                    c["state"] = (
                        "uncertain"
                        if out["may_have_been_charged"]
                        else "purchased"
                        if out["charged"]
                        else "failed"
                    )
                    c["message"] = {
                        "uncertain": "Purchase uncertain; reconciliation required. Do not retry.",
                        "purchased": "Label purchased",
                        "failed": "Not purchased. Check shipment details.",
                    }[c["state"]]
                else:
                    status = self.physical.summary(shop, c["shipment_id"])
                    if not status or not status["first_print_available"]:
                        c.update(
                            state="skipped",
                            message="Already attempted/sent; no additional copy submitted.",
                        )
                    else:
                        intent = self.physical.print_label(
                            shop, c["shipment_id"], b["confirmed_by"], c["key"]
                        )
                        c.update(
                            state={
                                "accepted": "sent",
                                "unknown": "uncertain",
                                "failed": "failed",
                            }.get(intent["state"], "uncertain"),
                            print_intent=intent["id"],
                            job_id=intent["provider_job_id"],
                            message="Sent to printer"
                            if intent["state"] == "accepted"
                            else "Print failed or uncertain. Check shipment; no automatic retry.",
                        )
            except (ActionError, PrintError) as exc:
                c.update(state="failed", message=self.safe_problem(exc))
            except Exception:
                log.exception("batch %s child %s interrupted", bid, c["shipment_id"])
                c.update(
                    state="uncertain",
                    message="Outcome uncertain. Check this shipment; no automatic retry.",
                )
            c["finished_at"] = now().isoformat()
            with self.store.atomic():
                current = self.get(shop, bid)
                index = next(
                    i
                    for i, x in enumerate(current["children"])
                    if x["shipment_id"] == c["shipment_id"]
                )
                current["children"][index] = c
                self.store.save_batch(shop, current)

    def resume(self, shop: str):
        # Continue only unclaimed children of confirmed reviews. Interrupted submissions are
        # never called again. The normal purchase reconciliation still runs in service.tick.
        for b in self.store.batches(shop):
            if b["state"] != "queued":
                continue
            with self.store.atomic():
                current = self.get(shop, b["id"])
                for c in current["children"]:
                    if c["state"] == "running" and now() - datetime.fromisoformat(
                        c["started_at"]
                    ) > timedelta(minutes=15):
                        c.update(
                            state="uncertain",
                            message="Interrupted attempt. Check shipment; no automatic retry.",
                        )
                self.store.save_batch(shop, current)
            self.run(shop, b["id"])
        # Refresh status evidence using GET only; never print again.
        for s in self.store.shipments(shop):
            for intent in self.store.print_intents_for(shop, s.id):
                if intent["state"] == "accepted" and intent.get("provider_state") not in (
                    "done",
                    "error",
                    "expired",
                ):
                    self.physical.status(shop, intent["id"])

        # Reconciliation can strengthen an uncertain child using its own ledger key only.
        # This is evidence refresh, never another call to buy/pay/print.
        for old in self.store.batches(shop):
            with self.store.atomic():
                b = self.get(shop, old["id"])
                changed = False
                for c in b["children"]:
                    if b["kind"] == "buy" and c["state"] == "uncertain":
                        op = self.store.op_by_key(shop, c["key"])
                        if op and op.state in (OpState.paid, OpState.done):
                            c.update(
                                state="purchased", message="Purchase confirmed by reconciliation."
                            )
                            changed = True
                        elif op and op.state in (OpState.failed, OpState.abandoned):
                            c.update(
                                state="failed",
                                message="Provider confirmed this attempt was not purchased.",
                            )
                            changed = True
                    elif b["kind"] == "print" and c.get("print_intent"):
                        intent = self.store.print_intent(shop, c["print_intent"])
                        if (
                            intent
                            and intent["state"] in ("failed", "expired")
                            and c["state"] != "failed"
                        ):
                            c.update(
                                state="failed",
                                message="PrintNode reported failure; check this shipment.",
                            )
                            changed = True
                if changed:
                    self.store.save_batch(shop, b)
