"""Notify me: demand for sizes that can't be bought, and telling those people when they can.

Signups come from the storefront through the app proxy. One active signup per email and
variant. Notifying is an explicit action that shows the count first; each signup is notified at
most once per reason, and remembers when and why.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import sqlite3
from datetime import timedelta
from typing import Any

from preorders import domain
from preorders.comms import EmailOff, _page
from preorders.domain import CommerceState
from preorders.service import ActionError
from preorders.store import iso, new_id

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
RETENTION_DAYS = 365


class Waitlist:
    def __init__(self, svc: Any) -> None:
        self.svc = svc
        self.store = svc.store

    # --- tokens for the unsubscribe link (no account needed)

    def token(self, sub_id: str) -> str:
        secret = (self.svc.s.shopify_client_secret or "dev").encode()
        return hmac.new(secret, f"unsub:{sub_id}".encode(), hashlib.sha256).hexdigest()[:32]

    def unsubscribe_url(self, sub_id: str) -> str:
        return (
            f"{self.svc.s.store_url}/apps/returns/preorders/waitlist/unsubscribe"
            f"?id={sub_id}&t={self.token(sub_id)}"
        )

    # --- signups

    def signup(
        self,
        *,
        variant_id: str,
        email: str,
        source: str = "storefront",
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        email = (email or "").strip().lower()
        if not EMAIL.match(email):
            raise ActionError("Enter a valid email address.", 422, "bad_email")
        row = self.store.one("SELECT * FROM catalog WHERE variant_id = ?", (variant_id,))
        if row is None:
            raise ActionError("That size isn't known.", 404, "not_found")
        state = self.svc.state_of(variant_id)
        if state != CommerceState.NOTIFY_ME:
            return {
                "status": "available",
                "state": state.value,
                "message": "This size can be bought now.",
            }
        try:
            self.store.insert(
                "waitlist",
                {
                    "id": new_id("wl"),
                    "shop": self.svc.shop,
                    "product_id": row["product_id"],
                    "variant_id": variant_id,
                    "product_title": row["product_title"],
                    "variant_title": row["variant_title"],
                    "email": email,
                    "customer_id": customer_id,
                    "status": "ACTIVE",
                    "source": source[:40],
                    "subscribed_at": iso(self.svc.clock()),
                },
            )
        except sqlite3.IntegrityError:
            return {
                "status": "already",
                "message": "You're on the list. We'll email you when this size becomes available.",
            }
        return {
            "status": "joined",
            "message": "You're on the list. We'll email you when this size becomes available.",
        }

    def unsubscribe(self, sub_id: str, token: str) -> bool:
        if not hmac.compare_digest(self.token(sub_id), token or ""):
            return False
        self.store.x(
            "UPDATE waitlist SET status = 'UNSUBSCRIBED', unsubscribed_at = ? WHERE "
            "id = ? AND status = 'ACTIVE'",
            (iso(self.svc.clock()), sub_id),
        )
        return True

    def delete(self, sub_id: str, actor: str) -> None:
        """Privacy: the signup and its email address are removed, not flagged."""
        row = self.store.one("SELECT variant_id FROM waitlist WHERE id = ?", (sub_id,))
        self.store.x("DELETE FROM waitlist WHERE id = ?", (sub_id,))
        self.svc.store.event(
            self.svc.shop,
            "waitlist_deleted",
            row["variant_id"] if row else "",
            {"id": sub_id},
            actor,
        )

    def redact_email(self, email: str, order_ids: list[str] | None = None) -> int:
        """customers/redact or a deletion request: every signup for the address goes, and the
        name and email on their preorder lines (matched by address or by the orders Shopify
        names) and on the delivery log are replaced. Order facts (units, dates) stay."""
        email = (email or "").strip().lower()
        orders = order_ids or []
        with self.store.tx():
            n = self.store.x(
                "DELETE FROM waitlist WHERE shop = ? AND email = ?", (self.svc.shop, email)
            )
            self.store.x(
                "UPDATE communications SET recipient = '[redacted]' WHERE shop = ? AND "
                "recipient = ?",
                (self.svc.shop, email),
            )
            marks = ",".join("?" * len(orders)) or "NULL"
            self.store.x(
                "UPDATE preorder_lines SET customer_name = '[redacted]', customer_email = "
                f"'[redacted]' WHERE shop = ? AND (LOWER(customer_email) = ? OR order_id IN "
                f"({marks}))",
                (self.svc.shop, email, *orders),
            )
        return n

    def purge_old(self) -> int:
        """Retention: finished signups (notified, converted, unsubscribed) are kept a year."""
        cutoff = iso(self.svc.clock() - timedelta(days=RETENTION_DAYS))
        return self.store.x(
            "DELETE FROM waitlist WHERE status != 'ACTIVE' AND COALESCE(notified_at, "
            "converted_at, unsubscribed_at, subscribed_at) < ?",
            (cutoff,),
        )

    # --- demand

    def demand(self, view: str = "most_wanted") -> list[dict[str, Any]]:
        now = self.svc.clock()
        d7, d30 = iso(now - timedelta(days=7)), iso(now - timedelta(days=30))
        status = "NOTIFIED" if view == "notified" else "ACTIVE"
        rows = self.store.all(
            "SELECT w.variant_id, w.product_id, MAX(w.product_title) AS product, "
            "MAX(w.variant_title) AS variant, COUNT(*) AS signups, "
            "SUM(w.subscribed_at >= ?) AS d7, SUM(w.subscribed_at >= ?) AS d30, "
            "MAX(w.subscribed_at) AS last_signup, MAX(w.notified_at) AS last_notified "
            "FROM waitlist w WHERE w.shop = ? AND w.status = ? GROUP BY w.variant_id",
            (d7, d30, self.svc.shop, status),
        )
        out = []
        for r in rows:
            cat = (
                self.store.one(
                    "SELECT available, sku FROM catalog WHERE variant_id = ?", (r["variant_id"],)
                )
                or {}
            )
            inbound = int(
                self.store.value(
                    "SELECT COALESCE(SUM(bl.expected_quantity - bl.received_quantity), 0) FROM "
                    "batch_lines bl JOIN batches b ON b.id = bl.batch_id WHERE bl.variant_id = "
                    "? AND "
                    "b.status IN ('PLANNED','ORDERED','IN_TRANSIT','DELAYED','PARTIALLY_RECEIVED')",
                    (r["variant_id"],),
                )
                or 0
            )
            state = self.svc.state_of(r["variant_id"])
            out.append(
                {
                    **r,
                    "d7": int(r["d7"] or 0),
                    "d30": int(r["d30"] or 0),
                    "sku": cat.get("sku", ""),
                    "stock": max(int(cat.get("available") or 0), 0),
                    "inbound": inbound,
                    "state": state.value,
                }
            )
        if view == "now_available":
            out = [r for r in out if r["state"] != CommerceState.NOTIFY_ME]
        key = {
            "recent": lambda r: r["last_signup"] or "",
            "notified": lambda r: r["last_notified"] or "",
        }.get(view, lambda r: (r["signups"], r["d7"]))
        return sorted(out, key=key, reverse=True)

    def subscribers(self, variant_id: str) -> list[dict[str, Any]]:
        return self.store.all(
            "SELECT id, email, status, source, subscribed_at, notified_at, notification_reason, "
            "converted_at FROM waitlist WHERE shop = ? AND variant_id = ? ORDER BY "
            "subscribed_at DESC",
            (self.svc.shop, variant_id),
        )

    # --- telling them

    def notify_preview(self, variant_id: str) -> dict[str, Any]:
        state = self.svc.state_of(variant_id)
        count = int(
            self.store.value(
                "SELECT COUNT(*) FROM waitlist WHERE shop = ? AND "
                "variant_id = ? AND status = 'ACTIVE'",
                (self.svc.shop, variant_id),
            )
            or 0
        )
        reason = {
            CommerceState.PREORDER: "PREORDER_OPEN",
            CommerceState.IN_STOCK: "BACK_IN_STOCK",
        }.get(state)
        return {
            "count": count,
            "state": state.value,
            "reason": reason,
            "email_enabled": self.svc.comms.enabled,
        }

    def notify(self, variant_id: str, actor: str) -> dict[str, int]:
        preview = self.notify_preview(variant_id)
        if preview["reason"] is None:
            raise ActionError("This size still can't be bought: there's nothing to tell them yet.")
        if not self.svc.comms.enabled:
            raise ActionError(
                str(EmailOff("Email isn't set up on the server (PREORDERS_EMAIL_PROVIDER).")),
                503,
                "email_off",
            )
        cat = self.svc.variant(variant_id)
        reason = preview["reason"]
        ov = self.svc._live_offer_variant(variant_id)
        offer = self.svc.offer(ov["offer_id"]) if ov else None
        day = self.svc.offer_dispatch(offer) if offer else None
        url = (
            f"{self.svc.s.store_url}/products/{cat['handle']}"
            f"?variant={variant_id.rsplit('/', 1)[-1]}"
        )
        name = f"{cat['product_title']} ({cat['variant_title']})"
        counts = {"SENT": 0, "ALREADY": 0, "FAILED": 0, "UNKNOWN": 0}
        for sub in self.store.all(
            "SELECT * FROM waitlist WHERE shop = ? AND variant_id = ? AND status = 'ACTIVE'",
            (self.svc.shop, variant_id),
        ):
            if reason == "PREORDER_OPEN":
                subject = f"{cat['product_title']} is open for preorder"
                lead = (
                    f"{name} is open for preorder. {domain.dispatch_words(day)}. You pay "
                    "when you order."
                )
                button = "Preorder now"
            else:
                subject = f"{cat['product_title']} is back in stock"
                lead = f"{name} is back in stock."
                button = "Shop now"
            unsub = self.unsubscribe_url(sub["id"])
            text = (
                f"{lead}\n\n{url}\n\nYou asked us to tell you about this size. This is a "
                f"one-off alert, not a newsletter. Stop alerts: {unsub}\n\nCROOKS"
            )
            body = _page(
                subject,
                [html.escape(lead)],
                (button, url),
                footer="You asked us to tell you about this size. This is a one-off "
                f'alert, not a newsletter. <a href="{html.escape(unsub, quote=True)}">'
                "Stop alerts</a>.",
            )
            status = self.svc.comms.send(
                kind=f"WAITLIST_{reason}",
                recipient=sub["email"],
                dedupe_key=f"waitlist:{sub['id']}:{reason}",
                subject=subject,
                text=text,
                html_body=body,
                actor=actor,
                variant_id=variant_id,
            )
            counts[status] += 1
            if status in ("SENT", "ALREADY"):
                self.store.x(
                    "UPDATE waitlist SET status = 'NOTIFIED', notified_at = ?, "
                    "notification_reason = ? WHERE id = ? AND status = 'ACTIVE'",
                    (iso(self.svc.clock()), reason, sub["id"]),
                )
        self.svc.store.event(
            self.svc.shop, "waitlist_notified", variant_id, {"reason": reason, **counts}, actor
        )
        return counts
