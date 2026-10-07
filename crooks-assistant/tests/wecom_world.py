"""A stand-in WeCom for the messaging tests: the six values George's app has, and a fake
qyapi.weixin.qq.com that answers the calls CLIVE makes, records them, and can be told to refuse.

Nothing here is real: the CorpID, Secrets and contact ids are made up, and the callback crypto
uses WeCom's published example key (tests/test_wecom_crypto.py) so a test can seal a callback
exactly as WeCom would.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.clients import wecom
from tests import fake_credentials

CORP = "ww00000000000test"
AGENT = "1000002"
# A WeCom app Secret is 43 letters and digits; built at runtime (owner rule B, tests/fake_credentials.py).
SECRET = fake_credentials.body("wecom-app-secret", 43)
TOKEN = "QDG6eK"
AES = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"
KF = "wkTESTACCOUNT0000000000000000"
JESSICA = "wmTESTCONTACT00000000000000000"
VALUES = {wecom.CORP_ID: CORP, wecom.AGENT_ID: AGENT, wecom.APP_SECRET: SECRET,
          wecom.CALLBACK_TOKEN: TOKEN, wecom.AES_KEY: AES}


class FakeWeCom:
    """Answers by path. `refuse[path] = [errcode, ...]` makes the next calls to that path answer
    with those errcodes in turn; `answers[path]` overrides a success."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.refuse: dict[str, list[int]] = {}
        self.answers: dict[str, dict[str, Any]] = {}
        self.minted = 0
        self.inbox: list[dict[str, Any]] = []      # what kf/sync_msg hands out, in order
        self.sent: list[dict[str, Any]] = []
        self.state = 0
        self.errmsg = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/cgi-bin")
        params = dict(request.url.params)
        body = json.loads(request.content or b"{}") if request.method == "POST" else {}
        self.calls.append((path, params, body))
        queued = self.refuse.get(path) or []
        if queued:
            code = queued.pop(0)
            return httpx.Response(200, json={"errcode": code, "errmsg": self.errmsg or f"refused {code}"})
        if path in self.answers:
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", **self.answers[path]})
        if path == "/gettoken":
            self.minted += 1
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "access_token": f"token-{self.minted}",
                                             "expires_in": 7200})
        if path == "/kf/sync_msg":
            page, self.inbox = self.inbox, []
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "next_cursor": f"cur{len(self.calls)}",
                                             "has_more": 0, "msg_list": page})
        if path == "/kf/send_msg":
            self.sent.append(body)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": body.get("msgid") or "auto"})
        if path == "/message/send":
            self.sent.append(body)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": "appmsg1", "invaliduser": ""})
        if path == "/kf/service_state/get":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "service_state": self.state})
        if path == "/kf/customer/batchget":
            ids = body.get("external_userid_list") or []
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "customer_list": [
                {"external_userid": i, "nickname": "Jessica Factory"} for i in ids]})
        if path == "/agent/get":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "agentid": int(AGENT), "name": "CLIVE", "close": 0})
        if path == "/kf/account/list":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "account_list": [
                {"open_kfid": KF, "name": "CROOKS 客服", "manage_privilege": True}]})
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})


def install(monkeypatch, *, values: dict[str, str] | None = None) -> FakeWeCom:
    """Point app/clients/wecom.py at a fresh FakeWeCom, with the six values stored."""
    fake = FakeWeCom()
    held = dict(VALUES if values is None else values)
    monkeypatch.setattr(wecom, "_stored", lambda name: held.get(name, ""))
    monkeypatch.setattr(wecom, "http_client",
                        lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler),
                                                            timeout=timeout_s, follow_redirects=False))
    monkeypatch.setattr(wecom, "TOKENS", wecom.Tokens())
    fake.values = held
    return fake


def kf_text(text: str, *, msgid: str, contact: str = JESSICA, at: float | None = None, origin: int = 3) -> dict[str, Any]:
    return {"msgid": msgid, "open_kfid": KF, "external_userid": contact, "send_time": int(at or time.time()),
            "origin": origin, "msgtype": "text", "text": {"content": text}}


def sealed_callback(fields: dict[str, str], *, timestamp: int | None = None, nonce: str = "nonce1") -> tuple[dict[str, str], bytes]:
    """A callback exactly as WeCom would send it: (query, body)."""
    crypto = wecom.CallbackCrypto(TOKEN, AES, CORP)
    inner = "<xml>" + "".join(f"<{k}><![CDATA[{v}]]></{k}>" for k, v in fields.items()) + "</xml>"
    encrypt = crypto.encrypt(inner)
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    query = {"msg_signature": wecom.signature(TOKEN, stamp, nonce, encrypt), "timestamp": stamp, "nonce": nonce}
    body = (f"<xml><ToUserName><![CDATA[{CORP}]]></ToUserName><AgentID><![CDATA[{AGENT}]]></AgentID>"
            f"<Encrypt><![CDATA[{encrypt}]]></Encrypt></xml>").encode()
    return query, body


def kf_event(*, token: str = "ENCtoken", timestamp: int | None = None, nonce: str = "nonce1") -> tuple[dict[str, str], bytes]:
    return sealed_callback({"ToUserName": CORP, "CreateTime": str(int(time.time())), "MsgType": "event",
                            "Event": "kf_msg_or_event", "Token": token, "OpenKfId": KF}, timestamp=timestamp, nonce=nonce)
