"""Instagram direct messages on the messaging core (app/messaging/instagram.py, app/clients/instagram.py
`send_text`): /hooks/instagram held to the same strictness as the other doors and signed with the
Instagram app's secret, each message stored once (Instagram's milliseconds read as seconds), echoes
of what the account sent kept as such and made CLIVE's own when they are its reply, "seen" kept, the
24-hour window with no human-agent tag, a send proved only by Instagram's message id, and the
conversations Instagram's API returns said exactly, nought included.

With a stand-in Meta (tests/meta_world.py). The existing read-only tools keep their own tests
(tests/test_instagram.py), which prove they still make GET requests only.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger
from app.clients import instagram
from app.connections import testers
from app.main import app
from app.messaging import guard as guard_module
from app.messaging import ingest, translate
from app.messaging import instagram as channel
from app.messaging.models import Message
from app.messaging.store import store
from app.people.store import people
from app.session.models import Session
from app.tools import authority, registry
from app.tools import messaging_tools as tools
from app.tools.dispatch import dispatch
from tests import meta_world
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}


@pytest.fixture()
def owner():
    granted = authority.for_owner(OWNER)
    token = authority.TOOL_AUTHORITY.set(granted)
    yield granted
    authority.TOOL_AUTHORITY.reset(token)
    granted.revoke()


@pytest.fixture()
def graph(monkeypatch, tmp_path):
    fake = meta_world.install(monkeypatch)
    instagram.configure(state_path=tmp_path / "instagram.json")
    store.configure(tmp_path / "messaging")
    people.configure(tmp_path / "people.json")
    guard_module.GUARD._seen.clear()
    heard: list[str] = []

    async def fake_complete(system, text, **_kw):
        heard.append(text)
        return "Do you ship to Spain?"

    translate.bind(fake_complete)
    fake.heard = heard
    yield fake
    translate.bind(None)
    store.configure(None)
    people.configure(None)
    instagram.reset()


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def engine(monkeypatch, tmp_path):
    clock = Clock()
    e = ActionEngine(ledger=ActionLedger(tmp_path / "logs"), clock=clock)
    e.test_clock = clock
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


def _closed_to_the_public(http):
    configure(http, logins=OWNER, local=False)
    http.runtime.settings = http.runtime.settings.model_copy(update={"local_owner": False})
    app.state.allowed_logins = http.runtime.allowed_logins


async def _post(http, payload, *, secret=meta_world.IG_SECRET, headers=None):
    body = meta_world.raw(payload)
    return await http.post("/hooks/instagram", content=body, headers={**meta_world.sign(body, secret), **(headers or {})})


def _wrote(text="Is the hoodie back in stock?", *, hours_ago=1.0, language="en"):
    thread = channel.dm_thread(meta_world.CUSTOMER, meta_world.IG_ACCOUNT)
    thread.who = f"@{meta_world.CUSTOMER_HANDLE}"
    store.upsert(thread)
    store.add(thread, Message(message_id=f"m_{time.time_ns()}", chat_id=thread.chat_id, direction="in", origin="contact",
                              text=text, at=time.time() - hours_ago * 3600, language=language, english=text,
                              translation_state="not_needed", remote_id=f"igmid.IN{time.time_ns()}"))
    return store.thread(thread.chat_id)


def _session(thread) -> Session:
    s = Session(session_id="ig1")
    s.issue(thread.chat_id)
    s.epoch = 1
    return s


def _lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def _stage_and_hold(engine, thread, english="Yes, back on Friday."):
    session = _session(thread)
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": english}, session=session, timeout_s=10)
    assert text.startswith("PROPOSED"), text
    proposal = session.proposals[-1]
    armed, why = engine.arm(proposal.proposal_id, session.session_id)
    assert armed is not None and not why
    engine.test_clock.now += 1.0
    result = await engine.commit(proposal.proposal_id, session.session_id, caller=OWNER, spec_lookup=_lookup,
                                 nonce=proposal.arm_nonce)
    return proposal, result


# ------------------------------------------------------------------ the door


async def test_metas_check_for_the_instagram_url_is_answered_only_for_its_verify_token(client, graph):  # noqa: F811
    _closed_to_the_public(client)
    query = {"hub.mode": "subscribe", "hub.verify_token": meta_world.IG_VERIFY, "hub.challenge": "2468"}
    answered = await client.get("/hooks/instagram", params=query, headers=STRANGER)
    assert (answered.status_code, answered.text) == (200, "2468")
    wrong = await client.get("/hooks/instagram", params={**query, "hub.verify_token": meta_world.WA_VERIFY})
    assert (wrong.status_code, wrong.content) == (403, b"")


async def test_a_signed_message_is_stored_once_with_instagrams_milliseconds_read_as_seconds_and_named(client, graph):  # noqa: F811
    _closed_to_the_public(client)
    at_ms = int((time.time() - 120) * 1000)
    payload = meta_world.ig_text("¿Hacéis envíos a España?", mid="igmid.IN1", at_ms=at_ms)
    response = await _post(client, payload, headers=STRANGER)
    assert (response.status_code, response.content) == (200, b"")
    await ingest.settle()
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert (thread.channel, thread.route, thread.contact, thread.who) == ("instagram", "dm", meta_world.CUSTOMER,
                                                                         f"@{meta_world.CUSTOMER_HANDLE}")
    assert abs(message.at - at_ms / 1000) < 1 and message.remote_id == "igmid.IN1"
    assert message.language == "other" and message.english == "Do you ship to Spain?"
    again = await _post(client, payload)
    await ingest.settle()
    assert again.status_code == 200 and len(store.messages(thread.chat_id)) == 1 and len(graph.heard) == 1


async def test_a_body_signed_with_the_meta_apps_secret_is_taken_and_any_other_is_not(client, graph):  # noqa: F811
    _closed_to_the_public(client)
    by_meta_app = await _post(client, meta_world.ig_text("hi", mid="igmid.M"), secret=meta_world.APP_SECRET)
    assert by_meta_app.status_code == 200
    for secret in ("not-the-secret", meta_world.IG_VERIFY):
        refused = await _post(client, meta_world.ig_text("hi", mid="igmid.N"), secret=secret)
        assert (refused.status_code, refused.content) == (403, b"")
    whatsapp_kind = await _post(client, meta_world.wa_text("hi", msg_id="wamid.Z"))
    assert whatsapp_kind.status_code == 403                    # signed, but not Instagram's object
    await ingest.settle()
    assert [m.remote_id for t in store.threads() for m in store.messages(t.chat_id)] == ["igmid.M"]


@pytest.mark.parametrize("change", ["unsigned", "garbage", "deep", "no_keys"])
async def test_anything_else_gets_an_empty_403_and_nothing_happens(client, graph, monkeypatch, change):  # noqa: F811
    _closed_to_the_public(client)
    body = meta_world.raw(meta_world.ig_text("hi", mid="igmid.X"))
    headers = meta_world.sign(body, meta_world.IG_SECRET)
    if change == "unsigned":
        headers = {}
    elif change == "garbage":
        body = b"{not json"
        headers = meta_world.sign(body, meta_world.IG_SECRET)
    elif change == "deep":
        body = b'{"object":"instagram","entry":' + b"[" * 30_000 + b"]" * 30_000 + b"}"
        headers = meta_world.sign(body, meta_world.IG_SECRET)
    elif change == "no_keys":
        monkeypatch.setattr(channel, "_stored", lambda name: "")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as raw:
        for extra in ({}, STRANGER, PROXIED):
            response = await raw.post("/hooks/instagram", content=body, headers={**headers, **extra})
            assert (response.status_code, response.content) == (403, b""), (change, extra)
    await ingest.settle()
    assert store.threads() == []


async def test_nothing_an_instagram_request_carried_reaches_the_log(client, graph, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    await _post(client, meta_world.ig_text("my address is 1 Lane", mid="igmid.LOG"))
    await _post(client, meta_world.ig_text("x", mid="igmid.LOG2"), secret="wrong")
    await ingest.settle()
    for private in ("1 Lane", meta_world.CUSTOMER, meta_world.CUSTOMER_HANDLE, "igmid.LOG", meta_world.IG_TOKEN,
                    meta_world.IG_SECRET, meta_world.IG_VERIFY):
        assert private not in caplog.text, private


# ------------------------------------------------------------------ echoes and seen


async def test_what_the_account_sent_from_the_app_is_kept_as_such_and_seen_marks_clives_reply_read(client, graph, owner, engine):  # noqa: F811
    thread = _wrote()
    await _post(client, meta_world.ig_echo("On its way!", mid="igmid.APP"))
    await ingest.settle()
    from_app = [m for m in store.messages(thread.chat_id) if m.remote_id == "igmid.APP"]
    assert [(m.direction, m.origin, m.status) for m in from_app] == [("out", "person", "sent")]
    proposal, result = await _stage_and_hold(engine, thread)
    assert result.code == "verified"
    await _post(client, meta_world.ig_read("igmid.SENT1"))
    await ingest.settle()
    mine = store.outgoing(thread.chat_id, proposal.execution["client_id"])
    assert mine.delivery == "read" and store.message(thread.chat_id, from_app[0].message_id).delivery == "read"


async def test_an_echo_of_clives_own_reply_that_arrives_first_becomes_clives_record(client, graph, owner, engine, monkeypatch):  # noqa: F811
    """Instagram echoes every message the account sends, CLIVE's included, and the echo can reach the
    door before the send's own answer. The send is still proved, once, as CLIVE's."""
    thread = _wrote()
    real = instagram.send_text

    async def echo_first(recipient, text):
        sent = await real(recipient, text)
        await _post(client, meta_world.ig_echo(text, mid=sent))
        return sent

    monkeypatch.setattr(instagram, "send_text", echo_first)
    proposal, result = await _stage_and_hold(engine, thread)
    await ingest.settle()
    assert result.code == "verified"
    outs = [m for m in store.messages(thread.chat_id) if m.direction == "out"]
    assert [(m.origin, m.remote_id, m.client_id) for m in outs] == [("clive", "igmid.SENT1", proposal.execution["client_id"])]


# ------------------------------------------------------------------ the reply


async def test_a_reply_inside_24_hours_is_held_sent_and_proved_by_instagrams_message_id(graph, owner, engine, tmp_path):
    thread = _wrote(hours_ago=2)
    proposal, result = await _stage_and_hold(engine, thread)
    card = registry.get("message_reply").write.present(proposal)
    assert card["title"] == "Send on Instagram" and {"label": "Instagram allows", "value": "open 21h more"} in card["facts"]
    assert result.code == "verified" and result.spoken == f"Sent to @{meta_world.CUSTOMER_HANDLE}."
    assert graph.sent == [{"recipient": {"id": meta_world.CUSTOMER}, "message": {"text": "Yes, back on Friday."}}]
    mine = store.outgoing(thread.chat_id, proposal.execution["client_id"])
    assert (mine.status, mine.remote_id) == ("sent", "igmid.SENT1")
    post = [r for r in graph.calls if r.method == "POST"]
    assert len(post) == 1 and meta_world.IG_TOKEN not in str(post[0].url)
    assert post[0].headers["authorization"] == f"Bearer {meta_world.IG_TOKEN}"


@pytest.mark.parametrize("case", ["late", "long"])
async def test_a_reply_instagram_would_not_take_is_refused_before_any_card(graph, owner, case):
    thread = _wrote(hours_ago=30 if case == "late" else 1, text="¿Hay tallas?" if case == "long" else "Hi",
                    language="other" if case == "long" else "en")
    args = {"chat_id": thread.chat_id, "english": "x" * 600 if case == "long" else "Hello."}
    if case == "long":
        args["translated"] = ("Sí, hay tallas grandes en la tienda. " * 17)[:600]   # with the English: over 1,000 bytes
    session = _session(thread)
    text = await dispatch("message_reply", args, session=session, timeout_s=10)
    assert text.startswith("ERROR") and session.proposals == [] and graph.sent == []
    expected = {"late": "more than 24 hours since they last wrote, so Instagram won't take",
                "long": "longer than Instagram takes (1,000 bytes)"}[case]
    assert expected in text, text


async def test_instagram_saying_the_window_closed_at_send_is_its_refusal_and_nothing_is_recorded(graph, owner, engine):
    thread = _wrote()
    graph.refuse[("graph.instagram.com", "me/messages")] = (
        400, {"code": 10, "error_subcode": 2534022, "message": "This message is sent outside of allowed window."})
    proposal, result = await _stage_and_hold(engine, thread)
    assert result.code == "refused" and result.spoken.startswith("Instagram refused that: It is more than 24 hours")
    assert "allowed window" not in result.spoken
    assert store.outgoing(thread.chat_id, proposal.execution["client_id"]) is None


async def test_a_send_whose_answer_never_came_back_names_instagram(graph, owner, engine):
    graph.timeout_sends = True
    _, result = await _stage_and_hold(engine, _wrote())
    assert result.code == "unverified"
    assert result.spoken == "I couldn't confirm the message went. Check Instagram before sending it again."


# ------------------------------------------------------------------ reading conversations from Instagram


async def test_reading_instagram_says_exactly_what_its_api_returned_nought_included(graph, owner):
    empty = await tools.messages_recent(channel="instagram")
    assert empty["threads"] == []
    assert empty["note"] == "Instagram's API returned 0 conversations just now. No messages have come in on Instagram yet."
    graph.conversations = [{"id": "convA", "updated_time": "2026-10-08T05:00:00+0000", "participants": {"data": [
        {"id": meta_world.IG_ACCOUNT, "username": "crooksldn"}, {"id": meta_world.CUSTOMER, "username": meta_world.CUSTOMER_HANDLE}]},
        "messages": {"data": [{"id": "igmid.API2", "created_time": "2026-10-08T05:00:00+0000",
                                "from": {"id": meta_world.CUSTOMER, "username": meta_world.CUSTOMER_HANDLE},
                                "message": "Any restock soon?"}]}}]
    graph.thread_messages["convA"] = [
        {"id": "igmid.API1", "created_time": "2026-10-08T04:00:00+0000", "from": {"id": meta_world.IG_ACCOUNT,
                                                                                  "username": "crooksldn"}, "message": "Hi!"},
        {"id": "igmid.API2", "created_time": "2026-10-08T05:00:00+0000",
         "from": {"id": meta_world.CUSTOMER, "username": meta_world.CUSTOMER_HANDLE}, "message": "Any restock soon?"}]
    read = await tools.messages_recent(channel="instagram")
    assert read["note"] == "Instagram's API returned 1 conversation just now, 2 new messages."
    [shown] = read["threads"]
    assert shown["from"] == f"@{meta_world.CUSTOMER_HANDLE}" and shown["channel"] == "Instagram"
    assert [m["english"] for m in shown["messages"]] == ["Hi!", "Any restock soon?"]
    assert [m["by"] for m in shown["messages"]] == ["the Instagram app", "them"]
    # The same conversation from the webhook is the same thread.
    assert store.threads()[0].chat_id == channel.dm_thread(meta_world.CUSTOMER).chat_id
    again = await tools.messages_recent(channel="instagram")
    assert again["note"] == "Instagram's API returned 1 conversation just now."


async def test_an_instagram_that_will_not_answer_is_said_so_never_passed_off_as_nothing_new(graph, owner):
    graph.refuse[("graph.instagram.com", "me/conversations")] = (400, {"code": 10, "message": "no"})
    read = await tools.messages_recent(channel="instagram")
    assert read["note"].startswith("Instagram wasn't read just now (Instagram says CLIVE isn't allowed to read that")
    assert "this is what CLIVE had already" in read["note"]


async def test_the_probe_reports_what_instagram_returned(graph):
    routes = {r.key: r for r in await channel.probe_routes()}
    assert routes["replies"].state == "ready"
    assert routes["conversations"].can == "Instagram's API returned 0 conversations."
    assert routes["conversations"].state == "unknown" and "Advanced Access" in routes["conversations"].switch_on
    assert routes["callback"].state == "ready" and routes["callback"].can.endswith("Instagram sends: messages, messaging_seen.")
    assert routes["human_agent"].state == "not_used"
    graph.ig_fields = []
    off = {r.key: r for r in await channel.probe_routes()}["callback"]
    assert off.state == "off" and "Instagram sends this account's events for: none" in off.switch_on
    assert [r.method for r in graph.calls] == ["GET"] * len(graph.calls)


async def test_the_connections_test_of_what_is_stored_adds_what_its_messages_can_do(graph, monkeypatch):
    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(graph.handler)))
    outcome = await testers.run("instagram", dict(graph.ig), None)
    assert outcome.ok and outcome.detail.startswith("Instagram accepted the token for @crooksldn. replies: ready; "
                                                    "Instagram's API returned 0 conversations; messages arriving: ready.")
    kept = await testers.run("instagram", dict(graph.ig), None, changed=frozenset({"instagram_webhook_verify_token"}))
    assert kept.ok and not kept.checked and "Meta checks it" in kept.detail
