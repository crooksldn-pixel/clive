"""A stand-in Meta for the WhatsApp and Instagram tests: the values George's Meta app and numbers have,
a fake graph.facebook.com (WhatsApp Cloud API) and graph.instagram.com (Instagram API with Instagram
Login) that answer the calls CLIVE makes, record them, and can be told to refuse; and webhook
payloads signed exactly as Meta signs them (HMAC-SHA256 of the raw body under the app's secret).

Nothing here is real: the ids are made up, the phone numbers are Ofcom's drama numbers (07700 900xxx),
and every token and secret is built at runtime (owner rule B, tests/fake_credentials.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.clients import instagram as instagram_client
from app.clients import whatsapp
from app.secrets import keychain
from tests import fake_credentials
from tests.fake_credentials import HEX, LOWER_ALNUM

# WhatsApp ------------------------------------------------------------------------------------
PHONE_ID = "100000000000001"
WABA_ID = "200000000000002"
DISPLAY = "44 7700 900123"
SUPPLIER = "447700900456"            # a supplier's WhatsApp id (their number), Ofcom's drama range
SUPPLIER_NAME = "Ana Fixture"
WA_TOKEN = fake_credentials.bearer_token("wa-system-user", length=60)
APP_SECRET = fake_credentials.body("meta-app-secret", 32, HEX)
WA_VERIFY = "clive-" + fake_credentials.body("wa-verify", 24, LOWER_ALNUM)
WA_VALUES = {whatsapp.PHONE_NUMBER_ID: PHONE_ID, whatsapp.BUSINESS_ACCOUNT_ID: WABA_ID,
             whatsapp.ACCESS_TOKEN: WA_TOKEN, whatsapp.APP_SECRET: APP_SECRET, whatsapp.VERIFY_TOKEN: WA_VERIFY}

# Instagram -----------------------------------------------------------------------------------
IG_ACCOUNT = "17841400000000001"     # the CROOKS professional account's id (webhooks' entry.id)
IG_APP_SCOPED = "9000000000000001"   # /me's own id
CUSTOMER = "5550000000000001"        # an Instagram-scoped id of someone who wrote in
CUSTOMER_HANDLE = "jo.customer"
IG_TOKEN = fake_credentials.bearer_token("ig-user", length=60)
IG_SECRET = fake_credentials.body("ig-app-secret", 32, HEX)
IG_VERIFY = "clive-" + fake_credentials.body("ig-verify", 24, LOWER_ALNUM)


def sign(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    """The headers Meta sends with `body`."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


def raw(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class FakeGraph:
    """Answers by host and path. `refuse[(host, path)] = (status, error)` makes every call to that path
    answer with that error; `answers[(host, path)]` overrides a success."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.sent: list[dict[str, Any]] = []
        self.refuse: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        self.answers: dict[tuple[str, str], dict[str, Any]] = {}
        self.phone_status = "CONNECTED"
        self.subscribed = [{"whatsapp_business_api_data": {"id": "77", "name": "CLIVE"}}]
        self.conversations: list[dict[str, Any]] = []
        self.thread_messages: dict[str, list[dict[str, Any]]] = {}
        self.ig_fields = ["messages", "messaging_seen"]
        self.timeout_sends = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host = request.url.host
        path = request.url.path.split("/", 2)[-1] if request.url.path.count("/") >= 2 else request.url.path
        key = (host, path)
        if key in self.refuse:
            status, error = self.refuse[key]
            return httpx.Response(status, json={"error": error})
        if key in self.answers:
            return httpx.Response(200, json=self.answers[key])
        if host == "graph.facebook.com":
            return self._whatsapp(request, path)
        if host == "graph.instagram.com":
            return self._instagram(request, path)
        return httpx.Response(404, json={"error": {"code": 803}})

    def _whatsapp(self, request: httpx.Request, path: str) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {WA_TOKEN}":
            return httpx.Response(401, json={"error": {"code": 190, "message": "token"}})
        if path == PHONE_ID and request.method == "GET":
            return httpx.Response(200, json={"id": PHONE_ID, "display_phone_number": DISPLAY, "verified_name": "CROOKS LDN",
                                             "status": self.phone_status, "quality_rating": "GREEN",
                                             "code_verification_status": "VERIFIED"})
        if path == WABA_ID:
            return httpx.Response(200, json={"id": WABA_ID, "name": "CROOKS LDN"})
        if path == f"{WABA_ID}/subscribed_apps" and request.method == "POST":
            self.subscribed = [{"whatsapp_business_api_data": {"id": "77", "name": "CLIVE"}}]
            return httpx.Response(200, json={"success": True})
        if path == f"{WABA_ID}/subscribed_apps":
            return httpx.Response(200, json={"data": self.subscribed})
        if path == f"{PHONE_ID}/register" and request.method == "POST":
            self.registered = json.loads(request.content)
            return httpx.Response(200, json={"success": True})
        if path == f"{PHONE_ID}/messages" and request.method == "POST":
            if self.timeout_sends:
                raise httpx.ReadTimeout("no answer")
            body = json.loads(request.content)
            self.sent.append(body)
            return httpx.Response(200, json={"messaging_product": "whatsapp",
                                             "contacts": [{"input": body["to"], "wa_id": body["to"]}],
                                             "messages": [{"id": f"wamid.SENT{len(self.sent)}"}]})
        return httpx.Response(400, json={"error": {"code": 100}})

    def _instagram(self, request: httpx.Request, path: str) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {IG_TOKEN}":
            return httpx.Response(401, json={"error": {"code": 190, "message": "expired"}})
        if path == "me" and request.method == "GET":
            return httpx.Response(200, json={"id": IG_APP_SCOPED, "user_id": IG_ACCOUNT, "username": "crooksldn",
                                             "name": "CROOKS", "account_type": "BUSINESS"})
        if path == "me/messages" and request.method == "POST":
            if self.timeout_sends:
                raise httpx.ReadTimeout("no answer")
            body = json.loads(request.content)
            self.sent.append(body)
            return httpx.Response(200, json={"recipient_id": body["recipient"]["id"], "message_id": f"igmid.SENT{len(self.sent)}"})
        if path == "me/conversations":
            return httpx.Response(200, json={"data": self.conversations})
        if path == "me/subscribed_apps" and request.method == "POST":
            self.ig_fields = request.url.params["subscribed_fields"].split(",")
            return httpx.Response(200, json={"success": True})
        if path == "me/subscribed_apps":
            return httpx.Response(200, json={"data": [{"subscribed_fields": self.ig_fields}] if self.ig_fields else []})
        if path in self.thread_messages:
            return httpx.Response(200, json={"id": path, "participants": {"data": [
                {"id": IG_ACCOUNT, "username": "crooksldn"}, {"id": CUSTOMER, "username": CUSTOMER_HANDLE}]},
                "messages": {"data": self.thread_messages[path]}})
        if path == CUSTOMER:
            return httpx.Response(200, json={"id": CUSTOMER, "username": CUSTOMER_HANDLE, "name": "Jo"})
        return httpx.Response(404, json={"error": {"code": 803}})


def install(monkeypatch, *, whatsapp_values: dict[str, str] | None = None, instagram: bool = True) -> FakeGraph:
    """Point the WhatsApp and Instagram clients at a fresh FakeGraph, with their keys stored."""
    fake = FakeGraph()
    wa = dict(WA_VALUES if whatsapp_values is None else whatsapp_values)
    ig = {instagram_client.TOKEN_KEY: IG_TOKEN, instagram_client.APP_SECRET_KEY: IG_SECRET,
          "instagram_webhook_verify_token": IG_VERIFY} if instagram else {}
    monkeypatch.setattr(whatsapp, "_stored", lambda name: wa.get(name, ""))
    monkeypatch.setattr(keychain, "get_optional", lambda key: ig.get(key))
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(whatsapp, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=transport, timeout=timeout_s, follow_redirects=False))
    monkeypatch.setattr(instagram_client, "http_client", lambda: httpx.AsyncClient(transport=transport, timeout=5.0))
    instagram_client.reset()
    fake.wa, fake.ig = wa, ig
    return fake


# --- WhatsApp payloads, as the messages webhook reference gives them ---------------------------

def wa_envelope(value: dict[str, Any], *, phone_id: str = PHONE_ID, field: str = "messages") -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": WABA_ID, "changes": [{"value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": DISPLAY.replace(" ", ""),
                                                      "phone_number_id": phone_id}, **value}, "field": field}]}]}


def wa_text(text: str, *, msg_id: str, sender: str = SUPPLIER, name: str = SUPPLIER_NAME, at: float | None = None,
            phone_id: str = PHONE_ID) -> dict[str, Any]:
    return wa_envelope({"contacts": [{"profile": {"name": name}, "wa_id": sender}],
                        "messages": [{"from": sender, "id": msg_id, "timestamp": str(int(at or time.time())),
                                      "type": "text", "text": {"body": text}}]}, phone_id=phone_id)


def wa_status(remote_id: str, status: str, *, recipient: str = SUPPLIER, code: int = 0) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": remote_id, "status": status, "timestamp": str(int(time.time())), "recipient_id": recipient}
    if code:
        entry["errors"] = [{"code": code, "title": "something Meta wrote", "message": "something Meta wrote",
                            "error_data": {"details": "something Meta wrote"}}]
    return wa_envelope({"statuses": [entry]})


# --- Instagram payloads, as the Instagram messaging webhook reference gives them ---------------

def ig_envelope(events: list[dict[str, Any]], *, account: str = IG_ACCOUNT) -> dict[str, Any]:
    return {"object": "instagram", "entry": [{"id": account, "time": int(time.time() * 1000), "messaging": events}]}


def ig_text(text: str, *, mid: str, sender: str = CUSTOMER, at_ms: int | None = None) -> dict[str, Any]:
    return ig_envelope([{"sender": {"id": sender}, "recipient": {"id": IG_ACCOUNT},
                         "timestamp": at_ms or int(time.time() * 1000), "message": {"mid": mid, "text": text}}])


def ig_echo(text: str, *, mid: str, to: str = CUSTOMER) -> dict[str, Any]:
    return ig_envelope([{"sender": {"id": IG_ACCOUNT}, "recipient": {"id": to}, "timestamp": int(time.time() * 1000),
                         "message": {"mid": mid, "text": text, "is_echo": True}}])


def ig_read(mid: str, *, reader: str = CUSTOMER) -> dict[str, Any]:
    return ig_envelope([{"sender": {"id": reader}, "recipient": {"id": IG_ACCOUNT}, "timestamp": int(time.time() * 1000),
                         "read": {"mid": mid}}])
