"""Transactional email to customers: preorder updates, delays, and Notify me alerts.

Rules (docs/preorders/IMPLEMENTATION_PLAN.md):
- Nothing is sent by a change of data: only by a person's explicit Send, after seeing how many
  people it will reach.
- Every message is written down before it is sent, under a dedupe key: the same message to the
  same person for the same reason is sent once, whatever the retries. A lost reply is UNKNOWN and
  is retried only with the same provider idempotency key.
- A Notify me signup is a transactional alert, never marketing consent.

The provider is an interface; Resend is the first implementation. Without one configured,
sending is refused with a reason (nothing pretends to have been sent).
"""

from __future__ import annotations

import html
import json
import logging
import sqlite3
from typing import Any, Protocol

import httpx

from preorders.store import iso, new_id

REDACTED = "[redacted]"  # as set by Waitlist.redact_email

log = logging.getLogger("preorders.comms")


class EmailOff(Exception):
    pass


class EmailRefused(Exception):
    """A definite refusal: not sent."""


class EmailUncertain(Exception):
    """No clear answer: it may have been sent."""


class Mailer(Protocol):
    name: str

    def send(self, *, to: str, subject: str, text: str, html_body: str, key: str) -> str: ...


class DisabledMailer:
    name = "off"

    def send(self, *, to: str, subject: str, text: str, html_body: str, key: str) -> str:
        raise EmailOff("Email isn't set up on the server (PREORDERS_EMAIL_PROVIDER).")


class RecordingMailer:
    """For the tests and the dev server: keeps what would have been sent."""

    name = "recording"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.keys: set[str] = set()
        self.fail_next: str | None = None

    def send(self, *, to: str, subject: str, text: str, html_body: str, key: str) -> str:
        kind, self.fail_next = self.fail_next, None
        if kind == "refused":
            raise EmailRefused("The address was refused.")
        if kind == "unknown":
            self.keys.add(key)  # it did go out; the reply was lost
            self.sent.append({"to": to, "subject": subject, "text": text, "key": key})
            raise EmailUncertain("No answer from the email provider.")
        if key not in self.keys:  # the provider's idempotency key: sent once
            self.keys.add(key)
            self.sent.append({"to": to, "subject": subject, "text": text, "key": key})
        return f"msg_{abs(hash(key)) % 10**8}"


class ResendMailer:
    """Resend's API (https://resend.com/docs/api-reference/emails/send-email), with its
    Idempotency-Key header so a retried send is delivered once."""

    name = "resend"

    def __init__(
        self, api_key: str, sender: str, reply_to: str = "", http: httpx.Client | None = None
    ) -> None:
        self.api_key, self.sender, self.reply_to = api_key, sender, reply_to
        self._http = http or httpx.Client(timeout=15)

    def send(self, *, to: str, subject: str, text: str, html_body: str, key: str) -> str:
        body: dict[str, Any] = {
            "from": self.sender,
            "to": [to],
            "subject": subject,
            "text": text,
            "html": html_body,
        }
        if self.reply_to:
            body["reply_to"] = self.reply_to
        try:
            r = self._http.post(
                "https://api.resend.com/emails",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key[:256]},
            )
        except httpx.HTTPError as exc:
            raise EmailUncertain(f"Resend couldn't be reached ({type(exc).__name__}).") from exc
        if r.status_code in (200, 201):
            try:
                return str(r.json().get("id") or "")
            except ValueError:
                return ""
        if r.status_code in (408, 409, 429) or r.status_code >= 500:
            raise EmailUncertain(f"Resend answered {r.status_code}.")
        raise EmailRefused(f"Resend refused it ({r.status_code}).")


def build_mailer(settings: Any) -> Mailer:
    if settings.email_provider == "resend" and settings.resend_api_key.get_secret_value():
        return ResendMailer(
            settings.resend_api_key.get_secret_value(), settings.email_from, settings.email_reply_to
        )
    return DisabledMailer()


# ------------------------------------------------------------------ the words


def _page(
    title: str, paragraphs: list[str], button: tuple[str, str] | None = None, footer: str = ""
) -> str:
    parts = [f'<p style="margin:0 0 16px">{p}</p>' for p in paragraphs]
    if button:
        parts.append(
            f'<p style="margin:24px 0"><a href="{html.escape(button[1], quote=True)}" '
            'style="background:#111;color:#fff;padding:12px 20px;text-decoration:none;'
            f'display:inline-block">{html.escape(button[0])}</a></p>'
        )
    if footer:
        parts.append(f'<p style="margin:24px 0 0;color:#666;font-size:12px">{footer}</p>')
    return (
        '<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;'
        'line-height:1.5;color:#111;max-width:520px"><h1 style="font-size:20px;'
        f'margin:0 0 16px">{html.escape(title)}</h1>{"".join(parts)}</div>'
    )


def long_date(value: str | None) -> str:
    if not value:
        return "to be confirmed"
    from datetime import date

    d = date.fromisoformat(value[:10])
    return f"{d.day} {d:%B}"


class Communications:
    def __init__(self, svc: Any, mailer: Mailer) -> None:
        self.svc = svc
        self.store = svc.store
        self.mailer = mailer

    @property
    def enabled(self) -> bool:
        return not isinstance(self.mailer, DisabledMailer)

    def send(
        self,
        *,
        kind: str,
        recipient: str,
        dedupe_key: str,
        subject: str,
        text: str,
        html_body: str,
        actor: str,
        order_id: str | None = None,
        variant_id: str | None = None,
        batch_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> str:
        """Send one message once. Returns SENT, ALREADY (sent before), FAILED or UNKNOWN."""
        if not self.enabled:
            raise EmailOff("Email isn't set up on the server (PREORDERS_EMAIL_PROVIDER).")
        with self.store.tx():
            row = self.store.one("SELECT * FROM communications WHERE dedupe_key = ?", (dedupe_key,))
            if row and row["status"] == "SENT":
                return "ALREADY"
            if row is None:
                row = {
                    "id": new_id("msg"),
                    "shop": self.svc.shop,
                    "kind": kind,
                    "recipient": recipient,
                    "dedupe_key": dedupe_key,
                    "order_id": order_id,
                    "variant_id": variant_id,
                    "batch_id": batch_id,
                    "status": "PENDING",
                    "detail": json.dumps(detail or {}, default=str),
                    "actor": actor,
                    "created_at": iso(self.svc.clock()),
                }
                try:
                    self.store.insert("communications", row)
                except sqlite3.IntegrityError:
                    return "ALREADY"
        try:
            provider_id = self.mailer.send(
                to=recipient, subject=subject, text=text, html_body=html_body, key=dedupe_key
            )
        except EmailRefused as exc:
            self.store.update(
                "communications", "id", row["id"], {"status": "FAILED", "error": str(exc)[:300]}
            )
            log.info("%s to message %s refused: %s", kind, row["id"], exc)
            return "FAILED"
        except EmailUncertain as exc:
            self.store.update(
                "communications", "id", row["id"], {"status": "UNKNOWN", "error": str(exc)[:300]}
            )
            log.warning("%s message %s outcome unknown: %s", kind, row["id"], exc)
            return "UNKNOWN"
        self.store.update(
            "communications",
            "id",
            row["id"],
            {
                "status": "SENT",
                "provider_id": provider_id,
                "error": None,
                "sent_at": iso(self.svc.clock()),
            },
        )
        log.info("%s message %s sent", kind, row["id"])
        return "SENT"

    # --- preorder customers

    def _batch_orders(self, batch_id: str) -> list[dict[str, Any]]:
        """One entry per order still waiting on the batch, with its lines."""
        rows = self.store.all(
            "SELECT * FROM preorder_lines WHERE batch_id = ? AND cancelled_at IS NULL AND state "
            "IN ('AWAITING_STOCK', 'READY') ORDER BY order_name",
            (batch_id,),
        )
        orders: dict[str, dict[str, Any]] = {}
        for r in rows:
            o = orders.setdefault(
                r["order_id"],
                {
                    "order_id": r["order_id"],
                    "order_name": r["order_name"],
                    # A redacted customer can't be written to.
                    "email": None if r["customer_email"] == REDACTED else r["customer_email"],
                    "name": None if r["customer_name"] == REDACTED else r["customer_name"],
                    "lines": [],
                },
            )
            o["lines"].append(r)
        return list(orders.values())

    def audience(self, batch_id: str) -> dict[str, Any]:
        orders = self._batch_orders(batch_id)
        reachable = [o for o in orders if o["email"]]
        return {
            "orders": len(orders),
            "customers": len({o["email"] for o in reachable}),
            "units": sum(
                x["current_quantity"] - x["fulfilled_quantity"] for o in orders for x in o["lines"]
            ),
            "without_email": len(orders) - len(reachable),
            "email_enabled": self.enabled,
        }

    def notify_delay(self, batch_id: str, actor: str) -> dict[str, int]:
        """'Update to your preorder': each order's original and new expected dispatch."""
        counts = {"SENT": 0, "ALREADY": 0, "FAILED": 0, "UNKNOWN": 0, "no_email": 0}
        store_url = self.svc.s.store_url
        for o in self._batch_orders(batch_id):
            if not o["email"]:
                counts["no_email"] += 1
                continue
            new = o["lines"][0]["current_dispatch_at"]
            old = o["lines"][0]["promised_dispatch_at"]
            items = [x["title"] for x in o["lines"]]
            text = (
                f"Hi {o['name'] or 'there'},\n\nThere's an update to your CROOKS preorder "
                f"{o['order_name']} ({', '.join(items)}).\n\n"
                f"Original expected dispatch: {long_date(old)}\n"
                f"New expected dispatch: {long_date(new)}\n\n"
                "Nothing else changes: your order is safe and we'll send it as soon as it's "
                "ready. If you'd rather not wait, reply to this email.\n\nCROOKS"
            )
            body = _page(
                "Update to your preorder",
                [
                    f"Hi {html.escape(o['name'] or 'there')},",
                    f"There's an update to your CROOKS preorder {html.escape(o['order_name'])} "
                    f"({html.escape(', '.join(items))}).",
                    f"Original expected dispatch: <strong>{long_date(old)}</strong><br>"
                    f"New expected dispatch: <strong>{long_date(new)}</strong>",
                    "Nothing else changes: your order is safe and we'll send it as soon as it's "
                    "ready. If you'd rather not wait, reply to this email.",
                ],
                ("View the store", store_url),
            )
            status = self.send(
                kind="PREORDER_DELAY",
                recipient=o["email"],
                dedupe_key=f"delay:{o['order_id']}:{new}",
                subject="Update to your preorder",
                text=text,
                html_body=body,
                actor=actor,
                order_id=o["order_id"],
                batch_id=batch_id,
                detail={"old": old, "new": new},
            )
            counts[status] += 1
        self.svc.store.event(self.svc.shop, "delay_notified", batch_id, counts, actor)
        return counts

    def notify_update(self, batch_id: str, actor: str) -> dict[str, int]:
        """'Your CROOKS preorder is still on the way' (no date change), at most once a day."""
        counts = {"SENT": 0, "ALREADY": 0, "FAILED": 0, "UNKNOWN": 0, "no_email": 0}
        today = self.svc.today().isoformat()
        for o in self._batch_orders(batch_id):
            if not o["email"]:
                counts["no_email"] += 1
                continue
            when = long_date(o["lines"][0]["current_dispatch_at"])
            text = (
                f"Hi {o['name'] or 'there'},\n\nYour CROOKS preorder {o['order_name']} is "
                f"still on the way. Expected dispatch: {when}.\n\nCROOKS"
            )
            body = _page(
                "Your CROOKS preorder is still on the way",
                [
                    f"Hi {html.escape(o['name'] or 'there')},",
                    f"Your CROOKS preorder {html.escape(o['order_name'])} is still on the way.",
                    f"Expected dispatch: <strong>{when}</strong>",
                ],
            )
            status = self.send(
                kind="PREORDER_UPDATE",
                recipient=o["email"],
                dedupe_key=f"update:{o['order_id']}:{today}",
                subject="Your CROOKS preorder is still on the way",
                text=text,
                html_body=body,
                actor=actor,
                order_id=o["order_id"],
                batch_id=batch_id,
            )
            counts[status] += 1
        self.svc.store.event(self.svc.shop, "update_notified", batch_id, counts, actor)
        return counts

    def log(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.all(
            "SELECT id, kind, recipient, order_id, variant_id, batch_id, status,"
            " provider_id, error, actor, created_at, sent_at FROM communications"
            " WHERE shop = ? ORDER BY created_at DESC LIMIT ?",
            (self.svc.shop, limit),
        )
