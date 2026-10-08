"""V1 closure fixes: credentials of any character are refused, never a 500; the Parcel2Go
access hash is never shown, sent or logged; every event in the feed says where it came from;
one bad return never holds up collecting the others' labels."""

import json

from fastapi.testclient import TestClient

from returns.app import create_app
from returns.models import Postage, Resolution
from returns.service import Notifier, public_ref, redacted

from .test_service import act, submit

R = {"Authorization": "Bearer read-key"}


def client(svc):
    return TestClient(create_app(svc.s, svc))


def test_credentials_with_any_characters_are_refused_not_a_crash(svc):
    svc.s.p2g_webhook_secret = "hook-secret"
    c = client(svc)
    bad = {"Authorization": "Bearer clé".encode("latin-1")}
    assert c.get("/api/v1/returns", headers=bad).status_code == 403
    r = c.post(
        "/webhooks/shopify", content=b"{}", headers={"x-shopify-hmac-sha256": "é".encode("latin-1")}
    )
    assert r.status_code == 401
    signed = {"Id": "1", "Timestamp": "2026-10-08T10:00:00", "Type": "Tracking", "Signature": "é"}
    assert c.post("/webhooks/parcel2go", json=signed).status_code == 401
    assert c.post("/webhooks/parcel2go", content=b"not json").status_code == 400


def test_the_parcel2go_access_hash_is_never_shown_or_sent(svc):
    ret = submit(svc, Resolution.refund, Postage.self_ship)
    ret.postage.label_ref = "p2g:26633:45693:h+/=secret"
    svc.store.save(ret)
    assert public_ref(ret.postage.label_ref) == "p2g:26633:45693"
    assert svc.staff(ret)["postage"]["label_ref"] == "p2g:26633:45693"  # admin, CLIVE, ctl
    assert "secret" not in json.dumps(redacted(ret))  # the CLIVE webhook body
    doc = client(svc).get(f"/api/v1/returns/{ret.id}", headers=R).json()
    assert "secret" not in json.dumps(doc)
    assert ret.postage.label_ref.endswith("secret")  # kept whole where it's needed: the store


def test_the_webhook_body_uses_the_redacted_return(svc):
    import httpx

    ret = submit(svc, Resolution.refund, Postage.self_ship)
    ret.postage.label_ref = "p2g:1:2:topsecret"
    sent = []
    n = Notifier(svc.s)
    n.s.clive_webhook_url, n.s.clive_webhook_secret = "https://clive.test/hook", "s"
    n._http = httpx.Client(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200))
    )
    n.send("return.label", ret)
    assert len(sent) == 1 and b"topsecret" not in sent[0].content
    assert json.loads(sent[0].content)["return"]["postage"]["label_ref"] == "p2g:1:2"


def test_every_event_in_the_feed_says_where_it_came_from(svc, clock):
    from datetime import timedelta

    since = (clock() - timedelta(minutes=1)).isoformat()
    ret = submit(svc, Resolution.refund, Postage.self_ship)
    act(svc, ret, "note", text="hi")
    events = client(svc).get("/api/v1/events", params={"since": since}, headers=R).json()["events"]
    sources = {e["type"]: e["source"] for e in events}
    assert sources["requested"] == "portal"  # the customer's own request
    assert sources["note"] == "system"  # act() runs as source "system" (the default caller)
    assert all(e["source"] for e in events)  # never null


def test_one_bad_return_never_stops_collecting_the_others(svc, monkeypatch):
    from returns.models import Status

    a = submit(svc, Resolution.refund, Postage.self_ship)
    b = submit(
        svc, Resolution.store_credit, Postage.self_ship, fli="gid://shopify/FulfillmentLineItem/2"
    )
    for r in (a, b):
        r.status, r.postage.label_ref = Status.awaiting_label, f"p2g:{r.id}:1:h"
        svc.store.save(r)
    seen = []

    def collect(ret):
        seen.append(ret.id)
        raise RuntimeError("boom")  # an unexpected failure on every return

    monkeypatch.setattr(svc.labels, "collect", collect, raising=False)
    assert svc.collect_labels() == []  # no crash
    assert sorted(seen) == sorted([a.id, b.id])  # both were tried
