"""Gmail tool behaviour, and the standing proof that no write path exists."""

from __future__ import annotations

import base64
import inspect

import pytest

from app.tools import gmail_tools
from tests.conftest import needs_gmail


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def headers(**kwargs) -> list[dict]:
    return [{"name": k.replace("_", "-"), "value": v} for k, v in kwargs.items()]


# --- the property that must never regress -----------------------------------

def test_module_contains_no_write_capability():
    source = inspect.getsource(gmail_tools)
    for forbidden in (
        ".send(", ".trash(", ".untrash(", ".modify(", ".insert(", ".batchModify(",
        ".batchDelete(", "drafts()", ".create(", "gmail.compose", "gmail.modify", "gmail.send",
    ):
        assert forbidden not in source, f"{forbidden} appears in gmail_tools — Day 1 is read-only"


def test_the_scopes_asked_for_are_modify_and_compose_and_never_the_whole_mailbox():
    from app.clients.gmail import REQUESTED_SCOPES, SCOPE_COMPOSE, SCOPE_FULL, SCOPE_MODIFY

    assert set(REQUESTED_SCOPES) == {SCOPE_MODIFY, SCOPE_COMPOSE} and SCOPE_FULL not in REQUESTED_SCOPES


def test_the_gmail_reads_are_two_and_every_other_gmail_tool_is_a_staged_write():
    from app.families import load_all
    from app.tools import gmail_writes  # noqa: F401 — registers the writes
    from app.tools.registry import all_specs

    # A Phase 3 family may add a Gmail tool of its own, and the point of this test is that a
    # tool it adds cannot be a write in disguise. Loading them makes the assertion cover them
    # rather than depending on whether an earlier test module happened to import one.
    load_all()
    reads = sorted(s.name for s in all_specs() if s.name.startswith("gmail_") and s.write is None)
    writes = sorted(s.name for s in all_specs() if s.name.startswith("gmail_") and s.write is not None)
    # The composer's two (app/families/compose.py) change only the Mac's own copy of an email
    # nobody has prepared yet: no source is touched and neither can reach a Gmail write method.
    assert reads == ["gmail_compose_fill", "gmail_compose_open", "gmail_find_in_email", "gmail_read_thread", "gmail_search"]
    assert writes == ["gmail_draft_new", "gmail_draft_reply", "gmail_send_new", "gmail_send_reply", "gmail_thread_archive"]
    assert all(s.write.complete and s.write.mutation.startswith("gmail:") for s in all_specs() if s.name in writes)
    assert all(s.batch is None for s in all_specs() if s.name in reads), "a read is not a bulk change either"


# --- bulk detection ----------------------------------------------------------

@pytest.mark.parametrize(
    "hdrs",
    [
        {"from": "News <news@brand.com>", "list-unsubscribe": "<https://x/u>"},
        {"from": "x@y.com", "list-id": "<promo.brand.com>"},
        {"from": "x@y.com", "precedence": "bulk"},
        {"from": "x@y.com", "auto-submitted": "auto-generated"},
        {"from": "noreply@shopify.com"},
        {"from": "no-reply@stripe.com"},
        {"from": "notifications@github.com"},
        {"from": "Marketing <marketing@brand.com>"},
    ],
)
def test_bulk_mail_is_detected(hdrs):
    assert gmail_tools._is_bulk(hdrs) is True


@pytest.mark.parametrize(
    "hdrs",
    [
        {"from": "Anna Dummy <anna@example.com>"},
        {"from": "jo@smallshop.example.com", "subject": "my order hasn't arrived"},
    ],
)
def test_real_people_are_not_flagged_as_bulk(hdrs):
    assert gmail_tools._is_bulk(hdrs) is False


# --- body extraction ---------------------------------------------------------

def test_multipart_body_is_walked():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("The jeans arrived torn.")}},
            {"mimeType": "text/html", "body": {"data": b64("<p>The jeans arrived torn.</p>")}},
        ],
    }
    assert gmail_tools._extract_body(payload) == "The jeans arrived torn."


def test_html_only_message_falls_back_to_stripped_html():
    payload = {"mimeType": "text/html", "body": {"data": b64("<div><b>Where</b> is my order?</div>")}}
    body = gmail_tools._extract_body(payload)
    assert "Where is my order?" in body
    assert "<" not in body


def test_nested_multipart_is_walked():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [{"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/plain", "body": {"data": b64("nested body")}},
        ]}],
    }
    assert gmail_tools._extract_body(payload) == "nested body"


def test_quoted_history_is_dropped():
    text = "Any update?\n\nOn Mon, 1 Sept 2026 at 09:00, CROOKS wrote:\n> your order shipped"
    payload = {"mimeType": "text/plain", "body": {"data": b64(text)}}
    assert gmail_tools._extract_body(payload) == "Any update?"


def test_long_bodies_are_truncated_with_a_marker():
    payload = {"mimeType": "text/plain", "body": {"data": b64("x" * 5000)}}
    body = gmail_tools._extract_body(payload)
    assert len(body) < 5000
    assert "truncated" in body


def test_undecodable_body_does_not_raise():
    payload = {"mimeType": "text/plain", "body": {"data": "!!!not base64!!!"}}
    assert isinstance(gmail_tools._extract_body(payload), str)


def test_empty_payload_returns_empty_string():
    assert gmail_tools._extract_body({}) == ""


# --- Shopify cross-reference degrades, it does not fail ----------------------

async def test_customer_lookup_absent_returns_none_not_false():
    """None means 'could not check'; False means 'not a customer'. Conflating them makes a
    Shopify outage look like every sender is a stranger."""
    gmail_tools.bind(gmail_tools.GmailClient(), customer_lookup=None)
    assert await gmail_tools._known_customer("a@b.com") is None


async def test_customer_lookup_failure_returns_none():
    async def exploding(_email):
        raise RuntimeError("Shopify is down")

    gmail_tools.bind(gmail_tools.GmailClient(), customer_lookup=exploding)
    assert await gmail_tools._known_customer("a@b.com") is None


async def test_customer_lookup_success_is_passed_through():
    gmail_tools.bind(gmail_tools.GmailClient(), customer_lookup=lambda e: _true())
    assert await gmail_tools._known_customer("a@b.com") is True


async def _true() -> bool:
    return True


# --- base query --------------------------------------------------------------

def test_base_query_excludes_the_obvious_noise():
    for clause in ("category:primary", "-from:me", "-in:chats", "-in:trash", "-in:spam"):
        assert clause in gmail_tools.BASE_QUERY


# --- live inbox (skipped without a token) ------------------------------------

@pytest.mark.live
@needs_gmail
async def test_live_search_returns_expected_shape():
    gmail_tools.bind(gmail_tools.GmailClient())
    result = await gmail_tools.gmail_search(days=7, limit=3)
    assert {"query", "count", "threads"} <= result.keys()
    for thread in result["threads"]:
        assert {"thread_id", "from", "subject", "likely_bulk"} <= thread.keys()


# --- the review's findings ---------------------------------------------------

def test_error_descriptions_drop_urls_and_personal_data():
    exc = RuntimeError("HttpError 400 requesting https://gmail.googleapis.com/v1/users/me/messages?q=from%3Ajo%40example.com returned bad")
    out = gmail_tools._describe(exc)
    assert "googleapis" not in out and "[url]" in out


def test_gmail_token_can_live_in_the_keychain():
    from app.secrets import keychain

    assert "gmail_token" in keychain.KNOWN_KEYS


async def test_read_thread_keeps_the_newest_messages():
    """A customer's latest reply is at the END of a long thread."""
    from unittest.mock import MagicMock

    fake = MagicMock()
    messages = [
        {"id": str(i), "payload": {"headers": [{"name": "From", "value": f"p{i}@x.com"}, {"name": "Subject", "value": "s"}, {"name": "Date", "value": "d"}], "mimeType": "text/plain", "body": {"data": b64(f"msg {i}")}}}
        for i in range(20)
    ]
    fake.users().threads().get().execute.return_value = {"messages": messages}
    client = gmail_tools.GmailClient()
    client._service = fake
    gmail_tools.bind(client)
    out = await gmail_tools.gmail_read_thread("t1")
    assert out["messages_shown"] == 12 and out["truncated"]
    assert out["messages"][-1]["body"] == "msg 19"
    assert out["messages"][0]["body"] == "msg 8"


# --------------------------------------------------------------------------- one round trip


class FakeBatch:
    """googleapiclient's BatchHttpRequest, as far as gmail_search uses it."""

    def __init__(self, callback, responses: dict, fail: bool = False) -> None:
        self.callback = callback
        self.responses = responses
        self.fail = fail
        self.added: list[str] = []
        self.executions = 0

    def add(self, request, request_id=None):
        self.added.append(request_id)

    def execute(self):
        self.executions += 1
        if self.fail:
            raise RuntimeError("batch endpoint unavailable")
        for request_id in self.added:
            response = self.responses.get(request_id)
            self.callback(request_id, response, None if response else RuntimeError("gone"))


def _message(mid: str, sender: str, subject: str) -> dict:
    return {
        "id": mid, "threadId": f"t-{mid}", "snippet": subject,
        "payload": {"headers": headers(From=sender, Subject=subject, Date="Mon, 8 Sep 2026 10:00:00 +0100")},
    }


def _service_with(fake_batch_factory):
    from unittest.mock import MagicMock

    service = MagicMock()
    service.users().messages().list().execute.return_value = {"messages": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
    service.users().messages().get().execute.side_effect = [
        _message("1", "Jo <jo@example.com>", "Order 1930"),
        _message("2", "Sam <sam@example.com>", "Sizing"),
        _message("3", "Kit <kit@example.com>", "Returns"),
    ]
    if fake_batch_factory is None:
        del service.new_batch_http_request
    else:
        service.new_batch_http_request = fake_batch_factory
    return service


async def test_search_fetches_every_message_in_one_batch_round_trip(monkeypatch):
    batches = []

    def factory(callback):
        batch = FakeBatch(callback, {
            "1": _message("1", "Jo <jo@example.com>", "Order 1930"),
            "2": _message("2", "Sam <sam@example.com>", "Sizing"),
            "3": _message("3", "Kit <kit@example.com>", "Returns"),
        })
        batches.append(batch)
        return batch

    service = _service_with(factory)
    client = gmail_tools._c()
    client._service = service
    monkeypatch.setattr(gmail_tools, "_known_customer", _no_lookup)
    result = await gmail_tools.gmail_search(query="", days=1, limit=10, include_bulk=True)
    assert [t["subject"] for t in result["threads"]] == ["Order 1930", "Sizing", "Returns"]
    assert len(batches) == 1 and batches[0].executions == 1 and batches[0].added == ["1", "2", "3"]
    assert service.users().messages().get().execute.call_count == 0


async def test_a_message_missing_from_the_batch_is_skipped_not_fatal(monkeypatch):
    def factory(callback):
        return FakeBatch(callback, {"1": _message("1", "Jo <jo@example.com>", "Order 1930")})

    client = gmail_tools._c()
    client._service = _service_with(factory)
    monkeypatch.setattr(gmail_tools, "_known_customer", _no_lookup)
    result = await gmail_tools.gmail_search(query="", days=1, limit=10, include_bulk=True)
    assert [t["subject"] for t in result["threads"]] == ["Order 1930"]


async def test_a_broken_batch_falls_back_to_one_by_one(monkeypatch):
    def factory(callback):
        return FakeBatch(callback, {}, fail=True)

    service = _service_with(factory)
    client = gmail_tools._c()
    client._service = service
    monkeypatch.setattr(gmail_tools, "_known_customer", _no_lookup)
    result = await gmail_tools.gmail_search(query="", days=1, limit=10, include_bulk=True)
    assert len(result["threads"]) == 3
    assert service.users().messages().get().execute.call_count == 3


async def test_a_client_without_batching_fetches_one_by_one(monkeypatch):
    service = _service_with(None)
    client = gmail_tools._c()
    client._service = service
    monkeypatch.setattr(gmail_tools, "_known_customer", _no_lookup)
    result = await gmail_tools.gmail_search(query="", days=1, limit=10, include_bulk=True)
    assert len(result["threads"]) == 3


async def _no_lookup(email: str):
    return None


# --------------------------------------------------------------------------- thread safety

def test_each_thread_gets_its_own_gmail_service(monkeypatch):
    """googleapiclient's httplib2 transport is not thread-safe. The health check and a search
    run in different worker threads; sharing one service between them corrupted the TLS state
    and took the backend down with a double free. One credential, one service per thread."""
    import threading

    from app.clients import gmail as gmail_client

    built: list[int] = []

    def fake_build(name, version, credentials=None, cache_discovery=True):
        assert (name, version, credentials) == ("gmail", "v1", "creds")
        built.append(threading.get_ident())
        return object()

    monkeypatch.setattr("googleapiclient.discovery.build", fake_build)
    loads: list[int] = []
    monkeypatch.setattr(gmail_client, "load_credentials", lambda: loads.append(1) or "creds")

    client = gmail_client.GmailClient()
    seen: dict[str, tuple[object, object]] = {}

    def grab(key: str) -> None:
        seen[key] = (client.service(), client.service())

    workers = [threading.Thread(target=grab, args=(f"t{i}",)) for i in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    grab("main")

    for pair in seen.values():
        assert pair[0] is pair[1], "cached within a thread"
    assert len({id(pair[0]) for pair in seen.values()}) == 3, "distinct across threads"
    assert len(built) == 3 and len(loads) == 1, "one credential, refreshed once, shared"

    # A reset forgets the credential; the next call on any thread rebuilds around a new one.
    client.reset()
    grab("main")
    assert len(loads) == 2 and len(built) == 4
    assert seen["main"][0] is not pair[0]


def test_an_injected_service_is_used_from_every_thread():
    """Tests hand the client a fake; it must not be shadowed by a per-thread build."""
    import threading

    from app.clients import gmail as gmail_client

    client = gmail_client.GmailClient()
    fake = object()
    client._service = fake
    got: list[object] = []
    t = threading.Thread(target=lambda: got.append(client.service()))
    t.start()
    t.join()
    assert got == [fake] and client.service() is fake


# --- authentication ----------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("mx.google.com; dkim=pass header.i=@example.com; spf=pass", True),
    ("mx.google.com; dkim=pass header.d=mail.example.com; spf=pass", True),
    ("mx.google.com; dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=example.com", True),
    ("mx.google.com; spf=pass (google.com: domain of x designates y as permitted sender)", False),
    ("mx.google.com; dkim=pass header.i=@evil.example; spf=pass smtp.mailfrom=bounce@evil.example", False),
    ("mx.google.com; dkim=fail header.i=@example.com; spf=pass", False),
    ("mx.google.com; dkim=fail; spf=softfail", False),
    ("", False),
])
def test_a_sender_is_verified_by_dmarc_or_a_dkim_signature_aligned_with_the_from_domain_never_spf_alone(value, expected):
    assert gmail_tools.authenticated({"authentication-results": value}, "daniel@example.com") is expected
    assert gmail_tools.authenticated({}, "daniel@example.com") is False
    assert gmail_tools.authenticated({"authentication-results": "mx.google.com; dkim=pass header.i=@example.com"}, "") is False, "no From domain, no alignment"


def test_the_first_authentication_results_header_is_the_one_read():
    """Gmail's own line is the outermost; a sender can append one further in that says pass."""
    message = {"payload": {"headers": [
        {"name": "Authentication-Results", "value": "mx.google.com; dkim=fail header.i=@example.com; spf=fail"},
        {"name": "Authentication-Results", "value": "attacker.example; dkim=pass header.i=@example.com"},
        {"name": "From", "value": "Daniel <daniel@example.com>"},
    ]}}
    headers = gmail_tools._headers(message)
    assert headers["authentication-results"].startswith("mx.google.com") and gmail_tools.authenticated(headers, "daniel@example.com") is False
