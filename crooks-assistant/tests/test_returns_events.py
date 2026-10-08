"""[returns-events] CROOKS Returns' doorbell at /hooks/returns (app/routes/returns_hook.py,
app/returns/events.py, DEC-077, the owner's ruling 20 of 8 October).

Through the real app and its door (the `client` fixture of tests/test_actions_routes.py), with the
stand-in service of tests/returns_stub.py behind CLIVE's real client. Every post is made as the
service makes it (its returns/doorbell.py: the five fields, signed over the raw body). What is held:

- the door: only what the stored secret signed, in its exact shape, sent in the last five minutes
  and not seen before, at most 4 KB, gets in; everything else, and every GET, is an empty 403;
- an event wakes the returns view: the open returns are read again through the API at once;
- an event that can make a return need George makes a notice only when CLIVE's own read of that
  return says it needs him for that reason, and the notice goes when the open returns say it is
  resolved; its words are an order number and what happened, never the customer;
- nothing an event carried reaches the log, and the door carries no authority into what it starts;
- the events secret is an optional field of the CROOKS Returns card, stored like its keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app.clients import crooks_returns as rc
from app.connections import catalog
from app.messaging.guard import GUARD
from app.returns import events
from app.routes import hooks
from app.secrets import keychain, linux_store
from tests.returns_stub import READ, WRITE, StubReturns, ret
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

SECRET = hashlib.sha256(b"returns-events-test-secret").hexdigest()
BASE = "https://returns.example.com"
RID = "ret_0a1b2c3d4e"
OTHER = "ret_0a1b2c3d4f"
STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
EVENT_N = iter(range(1, 10_000))


def event(kind: str = "requested", return_id: str = RID, *, sent_at: float | None = None, **extra) -> dict:
    n = next(EVENT_N)
    return {"id": f"evt_{n:024x}", "type": kind, "return_id": return_id, "at": "2026-10-08T11:59:00+00:00",
            "sent_at": int(time.time() if sent_at is None else sent_at), **extra}


def signed(payload: dict | bytes, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"Content-Type": "application/json", "X-Crooks-Returns-Signature": sig}


@pytest.fixture()
def held(monkeypatch):
    keys = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE, events.SECRET_KEY: SECRET}
    monkeypatch.setattr(keychain, "get_optional", lambda key: keys.get(key))
    return keys


@pytest.fixture()
async def door(client, held, monkeypatch):  # noqa: F811
    """Production's door (the owner's login listed, nothing on the server speaking for him), the
    stand-in service behind CLIVE's client, and a fresh doorbell."""
    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    from app.main import app

    app.state.allowed_logins = client.runtime.allowed_logins
    service = StubReturns([ret(RID, 2131), ret(OTHER, 2132, status="in_transit", attention=[])])
    transport = service.transport()
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=transport))
    rc.configure(base_url=BASE)
    rc.forget()
    events.DOOR.forget()
    GUARD.refused.clear()
    client.service = service
    yield client
    await events.DOOR.settle()
    events.DOOR.forget()
    rc.configure(base_url=rc.DEFAULT_BASE_URL)
    rc.forget()


async def ring(http, payload, *, secret: str = SECRET, headers: dict | None = None):
    raw, sig = signed(payload, secret)
    answer = await http.post(hooks.RETURNS_HOOK, content=raw, headers={**sig, **(headers or {})})
    await events.DOOR.settle()
    return answer


def asked(service, path: str = "") -> list[str]:
    return [f"{c['method']} {c['path']}" for c in service.calls if not path or c["path"].endswith(path)]


# ------------------------------------------------------------------ the door


def test_the_doorbell_is_on_the_exact_path_list_and_its_secret_is_a_known_static_key():
    assert hooks.RETURNS_HOOK == "/hooks/returns" and hooks.is_hook("/hooks/returns")
    for near in ("/hooks/returns/", "/hooks/Returns", "/hooks/returns/x", "/hooks/return"):
        assert not hooks.is_hook(near), near
    assert events.SECRET_KEY in keychain.KNOWN_KEYS and events.SECRET_KEY in linux_store.STATIC_KEYS
    from scripts import provision_secrets

    assert "RETURNS_CLIVE_WEBHOOK_SECRET" in provision_secrets.HELP[events.SECRET_KEY]


async def test_a_signed_event_gets_an_empty_200_from_anyone_and_wakes_the_returns_view(door):
    rows, _ = await rc.OPEN.get()
    door.service.calls.clear()
    for headers in ({}, STRANGER):
        answer = await ring(door, event("note"), headers=headers)
        assert (answer.status_code, answer.content) == (200, b""), headers
    assert asked(door.service) == ["GET /api/v1/returns", "GET /api/v1/returns"], (
        "each event read the open returns again at once, through the API, and a note reads nothing else")
    assert events.DOOR.counts["accepted"] == 2


@pytest.mark.parametrize("why", ["no secret", "unsigned", "wrong secret", "another body", "bad header",
                                 "a customer's detail", "a field missing", "stale", "from the future",
                                 "sent_at not a number", "bad id", "bad type", "bad return id", "bad time",
                                 "not json", "not utf-8", "a list"])
async def test_anything_else_gets_an_empty_403_and_changes_nothing(door, held, why):
    payload = event()
    raw, headers = signed(payload)
    if why == "no secret":
        held.pop(events.SECRET_KEY)
    elif why == "unsigned":
        headers.pop("X-Crooks-Returns-Signature")
    elif why == "wrong secret":
        raw, headers = signed(payload, "f" * 64)
    elif why == "another body":
        _, headers = signed(event())
    elif why == "bad header":
        headers["X-Crooks-Returns-Signature"] = headers["X-Crooks-Returns-Signature"][len("sha256="):]
    elif why == "a customer's detail":
        raw, headers = signed({**payload, "customer_email": "sam@example.com"})
    elif why == "a field missing":
        raw, headers = signed({k: v for k, v in payload.items() if k != "at"})
    elif why == "stale":
        raw, headers = signed({**payload, "sent_at": int(time.time()) - 301})
    elif why == "from the future":
        raw, headers = signed({**payload, "sent_at": int(time.time()) + 301})
    elif why == "sent_at not a number":
        raw, headers = signed({**payload, "sent_at": str(int(time.time()))})
    elif why == "bad id":
        raw, headers = signed({**payload, "id": "evt_../../x"})
    elif why == "bad type":
        raw, headers = signed({**payload, "type": "Requested <b>"})
    elif why == "bad return id":
        raw, headers = signed({**payload, "return_id": "ret_zz/../health"})
    elif why == "bad time":
        raw, headers = signed({**payload, "at": "yesterday"})
    elif why == "not json":
        raw, headers = signed(b"{not json")
    elif why == "not utf-8":
        raw, headers = signed(json.dumps(payload).encode("utf-16"))
    elif why == "a list":
        raw, headers = signed(json.dumps([payload]).encode())
    door.service.calls.clear()
    answer = await door.post(hooks.RETURNS_HOOK, content=raw, headers=headers)
    await events.DOOR.settle()
    assert (answer.status_code, answer.content) == (403, b""), why
    assert door.service.calls == [] and events.DOOR.counts["accepted"] == 0, "nothing is asked of the service"
    assert sum(n for kind, n in GUARD.refused.items() if kind.startswith("returns:")) == 1


@pytest.mark.parametrize("sent_at", [float("nan"), float("inf"), float("-inf"), 10**400],
                         ids=["NaN", "Infinity", "-Infinity", "too long for a float"])
async def test_a_sent_at_that_is_not_a_finite_moment_is_an_empty_403(door, sent_at):
    """JSON lets NaN and Infinity in, and NaN is never more than five minutes from anything: a
    signed body carrying one would pass the window for ever. Refused as a shape, whenever it is."""
    raw, headers = signed({**event(), "sent_at": sent_at})
    with pytest.raises(events.Refused) as ten_years_on:
        events.verify(raw, headers["X-Crooks-Returns-Signature"], key=SECRET, now=time.time() + 10 * 365 * 86400)
    assert ten_years_on.value.why == "shape"
    door.service.calls.clear()
    answer = await door.post(hooks.RETURNS_HOOK, content=raw, headers=headers)
    await events.DOOR.settle()
    assert (answer.status_code, answer.content) == (403, b"")
    assert door.service.calls == [] and events.DOOR.counts["accepted"] == 0
    assert {k: n for k, n in GUARD.refused.items() if k.startswith("returns:")} == {"returns:shape": 1}


async def test_a_body_over_4_kb_is_refused_before_it_is_read_whole(door):
    big = signed(event(note="x" * 5000))
    answer = await door.post(hooks.RETURNS_HOOK, content=big[0], headers=big[1])
    assert (answer.status_code, answer.content) == (403, b"")
    raw, headers = signed(event())
    lying = await door.post(hooks.RETURNS_HOOK, content=raw, headers={**headers, "Content-Length": "999999"})
    assert lying.status_code in (400, 403)
    assert GUARD.refused.get("returns:size", 0) >= 1


async def test_a_get_is_an_empty_403_and_near_misses_meet_the_owners_door(door):
    answer = await door.get(hooks.RETURNS_HOOK, headers=STRANGER)
    assert (answer.status_code, answer.content) == (403, b"")
    raw, headers = signed(event())
    for path in ("/hooks/returns/", "/hooks/Returns", "/hooks/returns/x"):
        for who in ({}, STRANGER):
            response = await door.post(path, content=raw, headers={**headers, **who})
            assert response.status_code == 403 and "not allowed" in response.text, (path, who)
    for method in ("PUT", "DELETE", "PATCH"):
        response = await door.request(method, hooks.RETURNS_HOOK, content=raw, headers=headers)
        assert response.status_code == 403 and "not allowed" in response.text, method


async def test_a_repeat_is_answered_and_dropped_however_late(door):
    first = event("requested")
    assert (await ring(door, first)).status_code == 200
    door.service.calls.clear()
    # The service retries an event whose answer it lost: the same id, signed afresh, later.
    again = {**first, "sent_at": int(time.time()) + 60}
    answer = await ring(door, again)
    assert (answer.status_code, answer.content) == (200, b"")
    assert door.service.calls == [] and events.DOOR.counts["repeats"] == 1


async def test_a_full_door_turns_the_next_away_unread(door, monkeypatch):
    monkeypatch.setattr(hooks, "MAX_READING", 0)
    answer = await ring(door, event())
    assert (answer.status_code, answer.content) == (403, b"")
    assert GUARD.refused.get("returns:busy") == 1


async def test_the_door_carries_no_authority_into_what_it_starts(door, monkeypatch):
    from app.tools import authority

    seen = []
    real = rc.get_return

    async def watching(value):
        seen.append(authority.current())
        return await real(value)

    monkeypatch.setattr(rc, "get_return", watching)
    await ring(door, event("requested"), headers=PROXIED)
    assert seen == [None]


async def test_a_read_already_out_when_the_service_rang_is_not_kept_as_fresh(monkeypatch):
    """The open returns were being read when the doorbell rang: that answer began before the change,
    so the next look asks again instead of keeping it for the minute."""
    clock = [1_000.0]
    open_returns = rc.OpenReturns(clock=lambda: clock[0])
    gate, calls = asyncio.Event(), []

    async def slow(**kw):
        calls.append(kw)
        if len(calls) == 1:
            await gate.wait()
        return []

    monkeypatch.setattr(rc, "list_returns", slow)
    first = asyncio.create_task(open_returns.get())
    await asyncio.sleep(0)
    clock[0] += 1
    open_returns.touch()
    gate.set()
    await first
    await open_returns.get()
    assert len(calls) == 2
    await open_returns.get()
    assert len(calls) == 2, "a read begun after the ring is kept for its minute as before"


# ------------------------------------------------------------------ what George sees


async def brief(http) -> dict:
    return (await http.get("/returns/brief", headers=PROXIED)).json()


async def test_a_return_to_approve_is_read_again_and_said_by_its_order_never_its_customer(door):
    door.service.calls.clear()
    await ring(door, event("requested"))
    assert asked(door.service, RID) == [f"GET /api/v1/returns/{RID}"], "the hook is a doorbell: the return is read"
    said = await brief(door)
    [notice] = said["notices"]
    assert (notice["code"], notice["tone"], notice["words"]) == (
        "return_to_approve", "info", "Return on #2131: waiting for your approval.")
    assert notice["id"].startswith("rn_") and RID not in json.dumps(said)
    assert "Sam Taylor" not in json.dumps(said) and "sam@example.com" not in json.dumps(said)
    assert said["needs"] == 1


async def test_a_failure_the_service_recorded_is_a_problem_notice(door):
    door.service.returns[OTHER].update(attention=["error"], last_error="Shopify did not process the return: refused")
    await ring(door, event("process_failed", OTHER))
    [notice] = (await brief(door))["notices"]
    assert (notice["code"], notice["tone"], notice["words"]) == (
        "return_problem", "bad", "Return on #2132: Shopify didn't move the money.")


async def test_an_event_that_rings_during_the_last_read_is_read_before_the_work_stops(door, monkeypatch):
    """The open returns are being read, the last thing an event's work does, when the service rings
    again: that ring starts no second task, so the running one goes round again and reads it."""
    door.service.returns[OTHER].update(attention=["error"], last_error="Shopify did not process the return: refused")
    real, reading, go = rc.OPEN.get, asyncio.Event(), asyncio.Event()

    async def held_open(*args, **kwargs):
        if not reading.is_set():
            reading.set()
            await go.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(rc.OPEN, "get", held_open)
    door.service.calls.clear()
    raw, headers = signed(event("requested"))
    assert (await door.post(hooks.RETURNS_HOOK, content=raw, headers=headers)).status_code == 200
    await asyncio.wait_for(reading.wait(), 5)  # A's return is read; now the open returns are
    raw, headers = signed(event("process_failed", OTHER))
    assert (await door.post(hooks.RETURNS_HOOK, content=raw, headers=headers)).status_code == 200
    go.set()
    await asyncio.wait_for(events.DOOR.settle(), 5)
    assert asked(door.service, OTHER) == [f"GET /api/v1/returns/{OTHER}"], "the second ring's return was read"
    assert events.DOOR._pending == {}, "nothing left waiting for a next ring"
    said = await brief(door)
    assert sorted((n["code"], n["words"]) for n in said["notices"]) == [
        ("return_problem", "Return on #2132: Shopify didn't move the money."),
        ("return_to_approve", "Return on #2131: waiting for your approval.")]


async def test_no_notice_when_the_return_as_read_does_not_need_him_for_that_reason(door):
    # The service said the money failed, but by the time CLIVE reads it there is no error.
    await ring(door, event("process_failed", OTHER))
    # And an event that cannot make a return need him is not read on its own at all.
    door.service.calls.clear()
    await ring(door, event("note", RID))
    assert asked(door.service, RID) == []
    assert (await brief(door))["notices"] == []


async def test_a_notice_goes_when_the_open_returns_say_it_is_resolved(door):
    await ring(door, event("requested"))
    assert len((await brief(door))["notices"]) == 1
    door.service.returns[RID].update(status="awaiting_shipment", attention=[], updated_at="2026-10-08T12:01:00+00:00")
    await ring(door, event("approved"))
    said = await brief(door)
    assert said["notices"] == [] and said["needs"] == 0, "read afresh: approved, nothing needs him"


async def test_a_return_that_cannot_be_read_makes_no_notice_and_is_logged_by_kind(door, caplog):
    caplog.set_level(logging.DEBUG)
    door.service.fail[f"/returns/{RID}"] = 503
    await ring(door, event("requested"))
    assert (await brief(door))["notices"] == []
    assert "could not be read again (trouble)" in caplog.text


async def test_nothing_an_event_carried_reaches_the_log(door, caplog):
    caplog.set_level(logging.DEBUG)
    payload = event("requested")
    await ring(door, payload)
    await ring(door, {**payload, "sent_at": 1})
    await ring(door, payload, secret="f" * 64)
    await brief(door)
    raw, headers = signed(payload)
    for private in (RID, payload["id"], SECRET, headers["X-Crooks-Returns-Signature"][7:], "Sam Taylor", "#2131"):
        assert private not in caplog.text, private


def test_without_the_returns_keys_nothing_is_said_and_the_brief_is_as_before():
    """Not connected, the brief is the same answer it always was (tests/test_crooks_returns.py
    holds it exactly), with no notices: there is nothing CLIVE could have read."""
    rows = [ret(RID, 2131)]
    door = events.Door()
    door._consider(RID, {"requested"}, rows[0])
    assert [n["words"] for n in door.notices(rows)] == ["Return on #2131: waiting for your approval."]
    assert door.notices([]) == [], "a return no longer open says nothing"


def test_a_notice_is_kept_twelve_hours_at_most():
    now = [1_000_000.0]
    door = events.Door(clock=lambda: now[0])
    row = ret(RID, 2131)
    door._consider(RID, {"requested"}, row)
    now[0] += events.NOTICE_KEEP_S + 1
    assert door.notices([row]) == []


# ------------------------------------------------------------------ the Connections card


def test_the_events_secret_is_an_optional_field_of_the_returns_card():
    card = catalog.get("returns")
    field = catalog.field(card, events.SECRET_KEY)
    assert field is not None and field.secret and field.env == "RETURNS_CLIVE_WEBHOOK_SECRET"
    assert "Same command" in field.hint
    assert events.SECRET_KEY not in card.requires, "without it returns work as before"


async def test_the_returns_test_checks_the_events_secret_and_says_whether_events_flow(monkeypatch):
    from app.connections import testers

    service = StubReturns([ret(RID, 2131)])
    health = {"ok": True, "clive": {"read_keys": True, "webhook": False}}

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=health) if request.url.path == "/health" else service(request)

    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    keys = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE}
    short = await testers.run("returns", {**keys, events.SECRET_KEY: "abc123"}, None)
    assert not short.ok and "too short" in short.detail and short.fix == "key"
    quiet = await testers.run("returns", {**keys, events.SECRET_KEY: SECRET}, None)
    assert quiet.ok and "isn't sending its events yet" in quiet.detail
    assert "RETURNS_CLIVE_WEBHOOK_URL=https://hooks.crooksldn.com/hooks/returns" in quiet.detail
    health["clive"]["webhook"] = True
    assert (await testers.run("returns", {**keys, events.SECRET_KEY: SECRET}, None)).detail.endswith(
        "checked the first time you approve an action."), "both sides set: nothing more to say"
    unsigned = await testers.run("returns", keys, None)
    assert unsigned.ok and "no events secret" in unsigned.detail
    assert SECRET not in quiet.detail


# ------------------------------------------------------------------ the page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_the_page_says_each_notice_once_under_node():
    """web/returns.js `announce`, under Node (tests/web/returns-events.test.js)."""
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([shutil.which("node"), "--test", str(root / "tests" / "web" / "returns-events.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=root)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
