"""Email Returns sends itself: the return label for a return staff issued (QR code, drop-off
points, items and refund). Everything else about a return the customer hears from Shopify.

A send is one email with one idempotency key. Resend keeps a key for 24 hours, so an email
whose outcome is unknown is retried with the same key only within that time (service.py).
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx


class EmailOff(Exception):
    """Email isn't set up on the server: nothing was sent."""


class EmailRefused(Exception):
    """A definite refusal: not sent."""


class EmailNotReached(Exception):
    """The email service was never reached: not sent, and safe to try again."""


class EmailUncertain(Exception):
    """No clear answer: it may have been sent."""


Attachment = dict[str, Any]  # {"filename", "content" (bytes), "content_id" (optional)}


class Mailer(Protocol):
    name: str
    enabled: bool

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html_body: str,
        key: str,
        attachments: list[Attachment],
    ) -> str: ...


class DisabledMailer:
    name, enabled = "off", False

    def send(self, **_: Any) -> str:
        raise EmailOff("Email isn't set up on the server (RETURNS_EMAIL_PROVIDER).")


class RecordingMailer:
    """For the tests and the dev server: keeps what would have been sent, delivering each
    key once, as Resend does, and answering a key reused for a different email as Resend
    does (409, so no clear answer)."""

    name, enabled = "recording", True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.delivered_keys: set[str] = set()
        self.bodies: dict[str, tuple[Any, ...]] = {}
        # "refused" | "unknown" | "unreached" | None: the next send only, or every send.
        self.fail_next: str | None = None
        self.fail_all: str | None = None

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html_body: str,
        key: str,
        attachments: list[Attachment],
    ) -> str:
        kind, self.fail_next = self.fail_next or self.fail_all, None
        if kind == "refused":
            raise EmailRefused("The address was refused (test).")
        if kind == "unreached":
            raise EmailNotReached("The email service couldn't be reached (test).")
        body = (to, subject, text, html_body, tuple(a["filename"] for a in attachments))
        if self.bodies.setdefault(key, body) != body:
            raise EmailUncertain("409: that key was used for a different email (test).")
        if key not in self.delivered_keys:
            self.delivered_keys.add(key)
            self.sent.append(
                {
                    "to": to,
                    "subject": subject,
                    "text": text,
                    "html": html_body,
                    "key": key,
                    "attachments": [
                        {k: v for k, v in a.items() if k != "content"} for a in attachments
                    ],
                    "files": attachments,  # with their bytes, for the dev server's preview
                }
            )
        if kind == "unknown":
            raise EmailUncertain("No answer from the email provider (test).")
        return f"msg_{abs(hash(key)) % 10**8}"


class ResendMailer:
    """Resend's API (POST https://api.resend.com/emails), with its Idempotency-Key header so a
    retried send is delivered once. Attachments are base64; one with a content_id shows inline
    where the HTML says src="cid:<id>" (Resend docs, embed inline images)."""

    name, enabled = "resend", True

    def __init__(
        self, api_key: str, sender: str, reply_to: str = "", http: httpx.Client | None = None
    ) -> None:
        self.api_key, self.sender, self.reply_to = api_key, sender, reply_to
        self._http = http or httpx.Client(timeout=20)

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html_body: str,
        key: str,
        attachments: list[Attachment],
    ) -> str:
        body: dict[str, Any] = {
            "from": self.sender,
            "to": [to],
            "subject": subject,
            "text": text,
            "html": html_body,
            "attachments": [
                {
                    "filename": a["filename"],
                    "content": base64.b64encode(a["content"]).decode("ascii"),
                    **({"content_id": a["content_id"]} if a.get("content_id") else {}),
                }
                for a in attachments
            ],
        }
        if self.reply_to:
            body["reply_to"] = self.reply_to
        try:
            r = self._http.post(
                "https://api.resend.com/emails",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key[:256]},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Never connected: nothing reached Resend.
            raise EmailNotReached(f"Resend couldn't be reached ({type(exc).__name__}).") from exc
        except httpx.HTTPError as exc:
            raise EmailUncertain(f"No answer from Resend ({type(exc).__name__}).") from exc
        if r.status_code in (200, 201):
            try:
                return str(r.json().get("id") or "")
            except ValueError:
                return ""
        if r.status_code in (408, 409, 429) or r.status_code >= 500:
            raise EmailUncertain(f"Resend answered {r.status_code}.")
        raise EmailRefused(f"Resend refused it ({r.status_code}).")


def build_mailer(settings: Any) -> Mailer:
    key = settings.resend_api_key.get_secret_value()
    if settings.email_provider == "resend" and key:
        return ResendMailer(key, settings.email_from, settings.email_reply_to)
    return DisabledMailer()
