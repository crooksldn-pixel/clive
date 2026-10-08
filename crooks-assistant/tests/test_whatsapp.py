"""WhatsApp on the messaging core (app/clients/whatsapp.py, app/messaging/whatsapp.py, app/messaging/meta.py):
the public door /hooks/whatsapp held to the same strictness as /hooks/wecom, Meta's signature checked
before anything is read, each message stored once in English with its original, what became of each
reply, the 24-hour window, a send proved only by WhatsApp's message id, and nothing private logged.

Through the real app and its middleware for the door (the `client` fixture of
tests/test_actions_routes.py), with a stand-in Meta (tests/meta_world.py) signing payloads exactly as
Meta does. Meta publishes no complete signature vector (its example hash comes without the secret and
body behind it), so the HMAC-SHA256 underneath is proved against RFC 4231's published vectors.
"""

from __future__ import annotations

import logging
import time

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger
from app.clients import whatsapp
from app.connections import testers
from app.main import app
from app.messaging import guard as guard_module
from app.messaging import ingest, translate
from app.messaging import meta as meta_hooks
from app.messaging import whatsapp as channel
from app.messaging.models import Message
from app.messaging.store import store
from app.people.store import people
from app.session.models import Session
from app.tools import authority, registry
from app.tools import messaging_tools as tools
from app.tools.dispatch import dispatch
from tests import meta_world, wecom_world
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
PORTUGUESE = "Olá, a amostra está pronta para envio amanhã."
ENGLISH_BACK = "Hello, the sample is ready to ship tomorrow."


@pytest.fixture()
def owner():
    granted = authority.for_owner(OWNER)
    token = authority.TOOL_AUTHORITY.set(granted)
    yield granted
    authority.TOOL_AUTHORITY.reset(token)
    granted.revoke()


@pytest.fixture()
def said():
    heard: list[str] = []

    async def fake_complete(system, text, **_kw):
        heard.append(text)
        return ENGLISH_BACK

    translate.bind(fake_complete)
    yield heard
    translate.bind(None)


@pytest.fixture()
def meta(monkeypatch, tmp_path, said):
    fake = meta_world.install(monkeypatch)
    store.configure(tmp_path / "messaging")
    people.configure(tmp_path / "people.json")
    guard_module.GUARD._seen.clear()
    yield fake
    store.configure(None)
    people.configure(None)


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
    """Production's door: the owner's login listed, nothing on the server speaking for him."""
    configure(http, logins=OWNER, local=False)
    http.runtime.settings = http.runtime.settings.model_copy(update={"local_owner": False})
    app.state.allowed_logins = http.runtime.allowed_logins


async def _post(http, payload, *, secret=meta_world.APP_SECRET, headers=None):
    body = meta_world.raw(payload)
    return await http.post("/hooks/whatsapp", content=body, headers={**meta_world.sign(body, secret), **(headers or {})})


def _wrote(text="Is the order ready?", *, hours_ago=1.0, language="en", english=None, msg_id=None):
    thread = channel.wa_thread(meta_world.PHONE_ID, meta_world.SUPPLIER)
    thread.who = meta_world.SUPPLIER_NAME
    store.upsert(thread)
    store.add(thread, Message(message_id=f"m_{time.time_ns()}", chat_id=thread.chat_id, direction="in", origin="contact",
                              text=text, at=time.time() - hours_ago * 3600, language=language,
                              english=english if english is not None else text,
                              translation_state="not_needed" if language == "en" else "done",
                              remote_id=msg_id or f"wamid.IN{time.time_ns()}"))
    return store.thread(thread.chat_id)


def _session(thread) -> Session:
    s = Session(session_id="wa1")
    s.issue(thread.chat_id)
    s.epoch = 1
    return s


def _lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def _hold(engine, proposal, session):
    armed, why = engine.arm(proposal.proposal_id, session.session_id)
    assert armed is not None and not why
    engine.test_clock.now += 1.0
    return await engine.commit(proposal.proposal_id, session.session_id, caller=OWNER, spec_lookup=_lookup,
                               nonce=proposal.arm_nonce)


# ------------------------------------------------------------------ the signature


def test_the_hmac_under_metas_signature_matches_rfc_4231():
    """RFC 4231 test cases 1 and 2 (HMAC-SHA256), in X-Hub-Signature-256's form."""
    for key, data, expected in (
            (chr(0x0b) * 20, b"Hi There", "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"),
            ("Jefe", b"what do ya want for nothing?", "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843")):
        assert meta_hooks.signature(key, data) == f"sha256={expected}"
        assert meta_hooks.signed(f"sha256={expected}", data, [key])
        assert meta_hooks.signed(f"sha256={expected.upper()}", data, [key])          # hex in either case


@pytest.mark.parametrize("given", ["", "sha256=", "sha1=" + "0" * 40, "sha256=" + "0" * 64, "sha256=" + "z" * 64,
                                   "SHA256=5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"])
def test_anything_but_the_bodys_own_signature_is_not_signed(given):
    assert not meta_hooks.signed(given, b"what do ya want for nothing?", ["Jefe"])


def test_a_signature_under_another_secret_or_over_another_body_is_not_signed():
    good = meta_hooks.signature("Jefe", b"what do ya want for nothing?")
    assert not meta_hooks.signed(good, b"what do ya want for nothing!", ["Jefe"])
    assert not meta_hooks.signed(good, b"what do ya want for nothing?", ["Jeff", ""])
    assert meta_hooks.signed(good, b"what do ya want for nothing?", ["", "Jeff", "Jefe"])      # any of George's own


# ------------------------------------------------------------------ the door: Meta's check


async def test_metas_url_check_is_answered_with_the_challenge_only_for_the_verify_token(client, meta):  # noqa: F811
    _closed_to_the_public(client)
    query = {"hub.mode": "subscribe", "hub.verify_token": meta_world.WA_VERIFY, "hub.challenge": "1158201444"}
    answered = await client.get("/hooks/whatsapp", params=query, headers=STRANGER)
    assert answered.status_code == 200 and answered.text == "1158201444"
    for wrong in ({**query, "hub.verify_token": meta_world.WA_VERIFY + "x"}, {**query, "hub.mode": "unsubscribe"},
                  {k: v for k, v in query.items() if k != "hub.challenge"}, {**query, "hub.challenge": "<b>hi</b>"},
                  {**query, "hub.challenge": "9" * 200}, {}):
        for headers in ({}, STRANGER):
            refused = await client.get("/hooks/whatsapp", params=wrong, headers=headers)
            assert (refused.status_code, refused.content) == (403, b""), (wrong, headers)


async def test_with_no_whatsapp_keys_the_door_is_shut(client, meta, monkeypatch):  # noqa: F811
    monkeypatch.setattr(whatsapp, "_stored", lambda name: "")
    query = {"hub.mode": "subscribe", "hub.verify_token": meta_world.WA_VERIFY, "hub.challenge": "1"}
    assert (await client.get("/hooks/whatsapp", params=query)).status_code == 403
    response = await _post(client, meta_world.wa_text("hi", msg_id="wamid.A"))
    assert (response.status_code, response.content) == (403, b"") and store.threads() == []


# ------------------------------------------------------------------ the door: messages


async def test_a_signed_message_is_stored_once_in_english_with_the_original_and_the_name_whatsapp_gave(client, meta, said):  # noqa: F811
    _closed_to_the_public(client)
    payload = meta_world.wa_text(PORTUGUESE, msg_id="wamid.IN1")
    response = await _post(client, payload, headers=STRANGER)
    assert (response.status_code, response.content) == (200, b"")
    await ingest.settle()
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert (thread.channel, thread.route, thread.who, thread.account) == ("whatsapp", "wa", meta_world.SUPPLIER_NAME,
                                                                         meta_world.PHONE_ID)
    assert message.text == PORTUGUESE and message.language == "other" and message.remote_id == "wamid.IN1"
    assert message.english == ENGLISH_BACK and message.translation == "machine translation"
    assert thread.last_in_language == "other" and said == [f"<message>\n{PORTUGUESE}\n</message>"]
    # Meta's retry of the same delivery, and the same message in another batch, change nothing.
    again = await _post(client, payload)
    other_batch = meta_world.wa_text(PORTUGUESE, msg_id="wamid.IN1")
    other_batch["entry"][0]["id"] = meta_world.WABA_ID + " "
    await _post(client, other_batch)
    await ingest.settle()
    assert again.status_code == 200 and len(store.messages(thread.chat_id)) == 1 and len(said) == 1


async def test_english_is_kept_as_it_is_and_never_sent_to_the_model(client, meta, said):  # noqa: F811
    await _post(client, meta_world.wa_text("Can you send the invoice?", msg_id="wamid.EN"))
    await ingest.settle()
    [message] = store.messages(store.threads()[0].chat_id)
    assert (message.language, message.translation_state, message.english) == ("en", "not_needed", "Can you send the invoice?")
    assert said == []


@pytest.mark.parametrize("words", ["Café hoodie restock?", "Naïve question: do u ship to Spain", "Résumé attached"])
async def test_english_the_translator_hands_back_unchanged_is_answered_in_english_alone(client, meta, owner, words):  # noqa: F811
    """[channels] Review note 5: an accent and no listed English word make the first guess "other";
    the translator giving the words back unchanged shows they were English, so the message, the
    thread, and what a reply needs follow it: the English alone, never an invented translation."""
    heard: list[str] = []

    async def hands_back(system, text, **_kw):
        heard.append(text)
        return text.removeprefix("<message>\n").removesuffix("\n</message>")

    translate.bind(hands_back)
    assert translate.language_of(words) == "other"
    await _post(client, meta_world.wa_text(words, msg_id="wamid.ACCENT"))
    await ingest.settle()
    [thread] = store.threads()
    [message] = store.messages(thread.chat_id)
    assert heard and (message.language, message.english, message.translation_state, message.translation) == (
        "en", words, "not_needed", "")
    assert thread.last_in_language == "en"
    session = _session(thread)
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Yes, back on Friday."},
                          session=session, timeout_s=10)
    assert text.startswith("PROPOSED"), text
    assert session.proposals[-1].execution["text"] == "Yes, back on Friday."


async def test_a_translation_that_changed_the_words_keeps_their_language(client, meta, owner, said):  # noqa: F811
    await _post(client, meta_world.wa_text(PORTUGUESE, msg_id="wamid.PT"))
    await ingest.settle()
    [thread] = store.threads()
    assert thread.last_in_language == "other" and store.messages(thread.chat_id)[0].language == "other"
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Thank you."},
                          session=_session(thread), timeout_s=10)
    assert text.startswith("ERROR") and "give the same words in their language" in text


@pytest.mark.parametrize("change", ["unsigned", "wrong_secret", "other_body", "garbage", "not_an_object", "wrong_object",
                                    "utf16", "deep"])
async def test_anything_not_signed_by_meta_for_this_app_gets_an_empty_403_and_nothing_happens(client, meta, said, change):  # noqa: F811
    _closed_to_the_public(client)
    body = meta_world.raw(meta_world.wa_text("hi", msg_id="wamid.X"))
    headers = meta_world.sign(body)
    if change == "unsigned":
        headers = {"Content-Type": "application/json"}
    elif change == "wrong_secret":
        headers = meta_world.sign(body, meta_world.IG_SECRET)
    elif change == "other_body":
        body = body.replace(b"hi", b"ho")
    elif change == "garbage":
        body = b"not json at all"
        headers = meta_world.sign(body)
    elif change == "not_an_object":
        body = b'[{"object": "whatsapp_business_account"}]'
        headers = meta_world.sign(body)
    elif change == "wrong_object":
        body = meta_world.raw({**meta_world.wa_text("hi", msg_id="wamid.X"), "object": "page"})
        headers = meta_world.sign(body)
    elif change == "utf16":
        body = meta_world.raw(meta_world.wa_text("hi", msg_id="wamid.X")).decode().encode("utf-16")
        headers = meta_world.sign(body)
    elif change == "deep":
        body = b'{"object":"whatsapp_business_account","entry":' + b"[" * 30_000 + b"]" * 30_000 + b"}"
        headers = meta_world.sign(body)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as raw:
        for extra in ({}, STRANGER, PROXIED):
            response = await raw.post("/hooks/whatsapp", content=body, headers={**headers, **extra})
            assert (response.status_code, response.content) == (403, b""), (change, extra)
    await ingest.settle()
    assert store.threads() == [] and said == []


async def test_a_change_for_another_of_the_apps_numbers_is_answered_and_left_alone(client, meta):  # noqa: F811
    response = await _post(client, meta_world.wa_text("hi", msg_id="wamid.OTHER", phone_id="999999999999999"))
    await ingest.settle()
    assert response.status_code == 200 and store.threads() == []


async def test_the_body_cap_is_metas_three_megabytes_for_whatsapp_not_wecoms_64_kilobytes(client, meta):  # noqa: F811
    batch = meta_world.wa_text("hi", msg_id="wamid.BIG")
    batch["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "x" * (200 * 1024)
    assert len(meta_world.raw(batch)) > guard_module.MAX_BODY_BYTES
    accepted = await _post(client, batch)
    assert accepted.status_code == 200
    too_big = b"{" + b" " * meta_hooks.MAX_BODY_BYTES + b"}"
    refused = await client.post("/hooks/whatsapp", content=too_big, headers=meta_world.sign(too_big))
    lying = await client.post("/hooks/whatsapp", content=b"{}", headers={**meta_world.sign(b"{}"),
                                                                         "Content-Length": str(meta_hooks.MAX_BODY_BYTES + 1)})
    assert (refused.status_code, refused.content) == (403, b"") and lying.status_code == 403
    await ingest.settle()


async def test_the_door_carries_no_authority_into_what_it_starts(client, meta, monkeypatch):  # noqa: F811
    seen = []
    real = ingest.process

    async def watching(adapter, inbound):
        seen.append(authority.current())
        return await real(adapter, inbound)

    monkeypatch.setattr(ingest, "process", watching)
    await _post(client, meta_world.wa_text("hi", msg_id="wamid.AUTH"), headers=PROXIED)
    await ingest.settle()
    assert seen == [None]


async def test_nothing_a_whatsapp_request_carried_reaches_the_log(client, meta, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    await _post(client, meta_world.wa_text(PORTUGUESE, msg_id="wamid.LOG"))
    await _post(client, meta_world.wa_text("x", msg_id="wamid.LOG2"), secret="wrong")
    await client.get("/hooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "5"})
    await ingest.settle()
    for private in (PORTUGUESE, ENGLISH_BACK, meta_world.SUPPLIER, meta_world.SUPPLIER_NAME, "wamid.LOG",
                    meta_world.WA_TOKEN, meta_world.APP_SECRET, meta_world.WA_VERIFY, meta_world.PHONE_ID):
        assert private not in caplog.text, private


def test_the_whatsapp_doors_query_never_reaches_the_access_log():
    from app.logging.quiet import QuietPollsFilter

    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("203.0.113.1:5", "GET", "/hooks/whatsapp?hub.verify_token=abc&hub.challenge=1", "1.1", 200),
                               None)
    assert QuietPollsFilter().filter(record)
    assert record.args[2] == "/hooks/whatsapp?[not logged]"


# ------------------------------------------------------------------ what became of a reply


async def test_delivered_read_and_failed_are_kept_on_the_reply_and_never_go_backwards(client, meta):  # noqa: F811
    thread = _wrote()
    for n in (1, 2):
        store.add(thread, Message(message_id=f"m_out{n}", chat_id=thread.chat_id, direction="out", origin="clive",
                                  text="ok", at=time.time(), status="sent", remote_id=f"wamid.OUT{n}", client_id=f"c{n}"))
    await _post(client, meta_world.wa_status("wamid.OUT1", "read"))
    await _post(client, meta_world.wa_status("wamid.OUT1", "delivered"))      # late, and never backwards
    await _post(client, meta_world.wa_status("wamid.OUT2", "failed", code=131047))
    await ingest.settle()
    first, second = (store.outgoing(thread.chat_id, c) for c in ("c1", "c2"))
    assert first.delivery == "read" and first.status == "sent"
    assert second.status == "failed" and second.fail_reason.startswith("It is more than 24 hours since they last wrote")
    from app.messaging import views

    shown = [views.message_view(m, channel="whatsapp") for m in store.messages(thread.chat_id)]
    assert shown[1]["delivery"] == "Read" and shown[2]["status"].startswith("not delivered: It is more than 24 hours")
    assert "something Meta wrote" not in str(shown)


# ------------------------------------------------------------------ the reply


async def test_a_reply_inside_the_24_hours_is_staged_held_sent_and_proved_by_whatsapps_message_id(meta, owner, engine, tmp_path):
    thread = _wrote(hours_ago=3)
    session = _session(thread)
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Yes, Friday at noon."},
                          session=session, timeout_s=10)
    assert text.startswith("PROPOSED") and meta.sent == []
    proposal = session.proposals[-1]
    card = registry.get("message_reply").write.present(proposal)
    assert card["title"] == "Send on WhatsApp" and card["body"] == "Yes, Friday at noon."
    assert {"label": "To", "value": meta_world.SUPPLIER_NAME} in card["facts"]
    assert {"label": "WhatsApp allows", "value": "open 20h more"} in card["facts"]
    assert not [f for f in card["facts"] if "translation" in f["value"]] and card["detail"] == "Sends now. It cannot be unsent."
    result = await _hold(engine, proposal, session)
    assert result.code == "verified" and result.spoken == f"Sent to {meta_world.SUPPLIER_NAME.split()[0]}."
    [sent] = meta.sent
    assert sent == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": meta_world.SUPPLIER,
                    "type": "text", "text": {"preview_url": False, "body": "Yes, Friday at noon."}}
    mine = store.outgoing(thread.chat_id, proposal.execution["client_id"])
    assert (mine.status, mine.remote_id, mine.english, mine.translated) == ("sent", "wamid.SENT1", "Yes, Friday at noon.", "")
    ledger = (tmp_path / "logs" / "actions.jsonl").read_text()
    for private in ("Friday at noon", meta_world.SUPPLIER, meta_world.SUPPLIER_NAME):
        assert private not in ledger


async def test_someone_who_writes_another_language_is_answered_in_theirs_first(meta, owner, engine):
    thread = _wrote(PORTUGUESE, language="other", english=ENGLISH_BACK)
    session = _session(thread)
    missing = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Thank you."}, session=session,
                             timeout_s=10)
    assert missing.startswith("ERROR") and "give the same words in their language" in missing
    english_only = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Thank you.",
                                                    "translated": "Thank you very much."}, session=session, timeout_s=10)
    assert english_only.startswith("ERROR") and "reads as English" in english_only
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Thank you, send it Friday.",
                                            "translated": "Obrigado, envie na sexta-feira."}, session=session, timeout_s=10)
    assert text.startswith("PROPOSED"), text
    proposal = session.proposals[-1]
    card = registry.get("message_reply").write.present(proposal)
    assert card["body"] == "Obrigado, envie na sexta-feira.\n\nThank you, send it Friday."
    assert any(f["label"] == "Their language" and "machine translation" in f["value"] for f in card["facts"])
    assert card["detail"] == "Sends now, their language first, then your English. It cannot be unsent."
    assert (await _hold(engine, proposal, session)).code == "verified"
    mine = store.outgoing(thread.chat_id, proposal.execution["client_id"])
    assert mine.translated == "Obrigado, envie na sexta-feira." and mine.chinese == ""


async def test_an_english_writer_is_sent_the_english_alone(meta, owner):
    thread = _wrote()
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Thanks.", "translated": "Obrigado."},
                          session=_session(thread), timeout_s=10)
    assert text.startswith("ERROR") and "send the English alone" in text and meta.sent == []


@pytest.mark.parametrize("case", ["late", "never", "other_number"])
async def test_a_reply_whatsapp_would_not_take_is_refused_in_plain_words_before_any_card(meta, owner, case):
    thread = _wrote(hours_ago=25 if case == "late" else 1)
    if case == "never":
        held = store.thread(thread.chat_id)
        held.last_in_at = 0.0
        store._save(held, [])
        thread = store.thread(thread.chat_id)
    if case == "other_number":
        meta.wa[whatsapp.PHONE_NUMBER_ID] = "100000000000099"
    session = _session(thread)
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    assert text.startswith("ERROR") and session.proposals == [] and meta.sent == []
    expected = {"late": "more than 24 hours since they last wrote", "never": "haven't written to your WhatsApp number",
                "other_number": "a WhatsApp number CLIVE no longer sends from"}[case]
    assert expected in text, text


async def test_a_card_made_inside_the_24_hours_and_held_after_them_is_refused_before_anything_goes(meta, owner, engine):
    """[channels] Review note 6: CLIVE checks the window again at the hold, not only Meta."""
    thread = _wrote(hours_ago=23.5)
    session = _session(thread)
    text = await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    assert text.startswith("PROPOSED"), text
    held = store.thread(thread.chat_id)
    held.last_in_at -= 3600                                  # an hour passes before the hold: 24h30
    store._save(held, store.messages(thread.chat_id))
    proposal = session.proposals[-1]
    result = await _hold(engine, proposal, session)
    assert result.code == "refused" and result.spoken.startswith("WhatsApp refused that: It is more than 24 hours")
    assert result.spoken.endswith("Nothing was changed.")
    assert meta.sent == [] and not [r for r in meta.calls if r.method == "POST"]
    assert store.outgoing(thread.chat_id, proposal.execution["client_id"]) is None


async def test_a_send_whatsapp_refuses_is_said_in_its_words_and_nothing_is_recorded(meta, owner, engine):
    thread = _wrote()
    session = _session(thread)
    await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    proposal = session.proposals[-1]
    meta.refuse[("graph.facebook.com", f"{meta_world.PHONE_ID}/messages")] = (
        400, {"code": 131047, "message": "Re-engagement message", "error_data": {"details": "something Meta wrote"}})
    result = await _hold(engine, proposal, session)
    assert result.code == "refused" and result.spoken.startswith("WhatsApp refused that: It is more than 24 hours")
    assert "something Meta wrote" not in result.spoken and "Re-engagement" not in result.spoken
    assert store.outgoing(thread.chat_id, proposal.execution["client_id"]) is None


async def test_a_reply_names_its_app_by_its_own_summary_key_never_service(meta, owner):
    """[channels] The app a reply goes through is the summary's `sent_through`: a summary's `service`
    is another write's own business (a label buy's carrier, tests/test_crooks_shipping.py)."""
    thread = _wrote()
    session = _session(thread)
    await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    proposal = session.proposals[-1]
    assert proposal.summary[engine_module.SENT_THROUGH] == "WhatsApp" and "service" not in proposal.summary
    write = registry.get("message_reply").write
    assert engine_module.service_name("message_reply", write, proposal) == "WhatsApp"
    proposal.summary["service"] = "Royal Mail · Tracked 48"                     # never read for the app
    assert engine_module.service_name("message_reply", write, proposal) == "WhatsApp"


@pytest.mark.parametrize("status, error", [
    (500, {"code": 131000, "message": "Something went wrong"}), (503, {"code": 2, "message": "Service unavailable"}),
    (500, {"code": 1, "message": "An unknown error occurred"}), (502, {}),
    (500, {"code": 131047, "message": "Re-engagement message"})])
async def test_a_send_whatsapp_answered_with_a_5xx_is_unconfirmed_never_nothing_changed(meta, owner, engine, status,
                                                                                        error):
    """[channels] Any 5xx, with a Meta code or without one: it doesn't prove the message didn't go, so the
    owner is told to check WhatsApp before sending again, never "Nothing was changed"."""
    from app.presentation import present_action

    thread = _wrote()
    session = _session(thread)
    await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    proposal = session.proposals[-1]
    meta.refuse[("graph.facebook.com", f"{meta_world.PHONE_ID}/messages")] = (status, error)
    result = await _hold(engine, proposal, session)
    assert result.code == "unverified", result.spoken
    assert result.spoken == "I couldn't confirm the message went. Check WhatsApp before sending it again."
    (card,) = present_action(result)
    assert "Nothing was changed" not in str(card) and "refused" not in str(card)
    assert store.outgoing(thread.chat_id, proposal.execution["client_id"]) is None


async def test_a_send_whose_answer_never_came_back_is_not_called_sent_and_names_whatsapp(meta, owner, engine):
    thread = _wrote()
    session = _session(thread)
    await dispatch("message_reply", {"chat_id": thread.chat_id, "english": "Hello."}, session=session, timeout_s=10)
    meta.timeout_sends = True
    result = await _hold(engine, session.proposals[-1], session)
    assert result.code == "unverified"
    assert result.spoken == "I couldn't confirm the message went. Check WhatsApp before sending it again."


async def test_an_answer_with_no_message_id_is_never_counted_as_sent(meta, owner):
    meta.answers[("graph.facebook.com", f"{meta_world.PHONE_ID}/messages")] = {"messaging_product": "whatsapp", "messages": []}
    with pytest.raises(whatsapp.WhatsAppError, match="gave no message id"):
        await whatsapp.send_text(meta_world.SUPPLIER, "hi")


# ------------------------------------------------------------------ people, on more than one app


async def test_one_supplier_on_wechat_and_whatsapp_is_one_card_with_both_conversations(meta, owner, monkeypatch):
    from app.messaging.wecom import kf_thread

    wecom_world.install(monkeypatch)
    wechat = kf_thread(wecom_world.KF, wecom_world.JESSICA)
    store.upsert(wechat)
    store.add(wechat, Message(message_id="m_wc", chat_id=wechat.chat_id, direction="in", origin="contact", text="你好",
                              at=time.time() - 60, language="zh", english="Hello", translation_state="done", remote_id="w1"))
    on_whatsapp = _wrote()
    people.note({"name": "Ana", "kind": "contact", "role": "knitwear supplier"})
    await tools.message_contact(wechat.chat_id, "Ana")
    await tools.message_contact(on_whatsapp.chat_id, "Ana")
    assert people.find("Ana").channels == [wechat.channel_key, on_whatsapp.channel_key]
    hers = await tools.messages_recent(person="Ana")
    assert sorted(t["channel"] for t in hers["threads"]) == ["WeChat", "WhatsApp"]
    assert all(t["from"] == "Ana" and t["role"] == "knitwear supplier" for t in hers["threads"])
    only_whatsapp = await tools.messages_recent(channel="whatsapp")
    assert [t["channel"] for t in only_whatsapp["threads"]] == ["WhatsApp"] and only_whatsapp["title"] == "Messages on WhatsApp"


# ------------------------------------------------------------------ what the number can do


async def test_the_connections_test_says_what_meta_answered_and_what_to_do(meta):
    outcome = await testers.run("whatsapp", dict(meta_world.WA_VALUES), None)
    assert outcome.ok, outcome.detail
    assert outcome.detail == (f"Meta accepted the WhatsApp keys. {meta_world.DISPLAY} (CROOKS LDN): Meta says its status is "
                              "CONNECTED, quality GREEN; replies: ready; messages arriving: ready.")
    meta.subscribed = []
    unsubscribed = await testers.run("whatsapp", dict(meta_world.WA_VALUES), None)
    assert "messages arriving: off" in unsubscribed.detail and "no app is subscribed" in unsubscribed.detail
    meta.phone_status = "PENDING"
    pending = await testers.run("whatsapp", dict(meta_world.WA_VALUES), None)
    assert "Meta says its status is PENDING" in pending.detail and "replies: off" in pending.detail
    assert "register it for the Cloud API" in pending.detail
    for words in (outcome.detail, unsubscribed.detail, pending.detail):
        assert meta_world.WA_TOKEN not in words and meta_world.APP_SECRET not in words and meta.sent == []


async def test_the_connections_test_names_the_key_meta_refused(meta):
    bad_token = await testers.run("whatsapp", {**meta_world.WA_VALUES, whatsapp.ACCESS_TOKEN: "not-the-token"}, None)
    assert not bad_token.ok and bad_token.refused == (whatsapp.ACCESS_TOKEN,) and "permanent" in bad_token.detail
    bad_secret = await testers.run("whatsapp", {**meta_world.WA_VALUES, whatsapp.APP_SECRET: "short"}, None)
    assert not bad_secret.ok and bad_secret.refused == (whatsapp.APP_SECRET,)
    bad_verify = await testers.run("whatsapp", {**meta_world.WA_VALUES, whatsapp.VERIFY_TOKEN: "a b"}, None)
    assert not bad_verify.ok and bad_verify.refused == (whatsapp.VERIFY_TOKEN,)
    bad_id = await testers.run("whatsapp", {**meta_world.WA_VALUES, whatsapp.PHONE_NUMBER_ID: "+44 7700"}, None)
    assert not bad_id.ok and bad_id.refused == (whatsapp.PHONE_NUMBER_ID,)
    assert whatsapp.value(whatsapp.ACCESS_TOKEN) == meta_world.WA_TOKEN          # tried, never stored


async def test_the_probe_and_the_client_send_the_token_in_the_header_never_an_address(meta):
    await channel.probe_routes()
    await whatsapp.send_text(meta_world.SUPPLIER, "hi")
    assert meta.calls and all(meta_world.WA_TOKEN not in str(r.url) for r in meta.calls)
    assert all(r.headers["authorization"] == f"Bearer {meta_world.WA_TOKEN}" for r in meta.calls)
    assert [r.method for r in meta.calls].count("POST") == 1                   # the probe sends nothing


async def test_the_two_set_up_steps_meta_takes_only_by_api_are_made_by_hand_and_send_nothing(meta):
    """scripts/whatsapp.py register and subscribe: Meta's settings, never a message."""
    from app.clients import instagram

    meta.subscribed = []
    assert await whatsapp.subscribe() is True and await whatsapp.subscribed_apps() == ["CLIVE"]
    with pytest.raises(whatsapp.WhatsAppError, match="six digits"):
        await whatsapp.register("12345")
    assert await whatsapp.register("246810") is True
    assert meta.registered == {"messaging_product": "whatsapp", "pin": "246810"} and meta.sent == []
    meta.ig_fields = []
    assert await instagram.subscribe() is True and await instagram.subscribed_fields() == ["messages", "messaging_seen"]
    assert all(meta_world.WA_TOKEN not in str(r.url) and meta_world.IG_TOKEN not in str(r.url) for r in meta.calls)


async def test_one_apps_conversations_are_a_card_of_their_own(meta, owner):
    """Asking about Instagram after WhatsApp adds a card; it doesn't overwrite WhatsApp's list."""
    from app.messaging import views

    _wrote()
    only = views.card("messages_recent", await tools.messages_recent(channel="whatsapp"))
    every = views.card("messages_recent", await tools.messages_recent())
    assert (only["key"], only["title"], every["key"]) == ("recent:WhatsApp", "Messages on WhatsApp", "recent")
    with pytest.raises(registry.ToolError, match="wechat, whatsapp or instagram"):
        await tools.messages_recent(channel="telegram")


async def test_nothing_yet_names_only_the_apps_that_are_connected(meta, owner, monkeypatch):
    from app.clients import instagram

    monkeypatch.setattr(instagram, "token", lambda: "")
    assert (await tools.messages_recent())["note"] == "No messages have come in on WhatsApp yet."
    wecom_world.install(monkeypatch)
    assert (await tools.messages_recent())["note"] == "No messages have come in on WeChat or WhatsApp yet."
