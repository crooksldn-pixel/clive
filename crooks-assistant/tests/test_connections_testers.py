"""Each service's test of a key before it is stored (app/connections/testers.py): what counts as
working, what each refusal is called in our words, that the key travels in a header or a body and
never an address, and that no answer ever quotes it back. Every service is a MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from app.connections import testers
from tests.fake_credentials import (
    DIGITS,
    HEX,
    bearer_token,
    body,
    elevenlabs_key,
    github_fine_grained_token,
    google_api_key,
)


class Settings:
    elevenlabs_base_url = "https://api.elevenlabs.io/v1"
    shopify_shop_domain = "x.myshopify.com"
    instagram_api_version = "v25.0"


def answering(monkeypatch, handler):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(record)))
    return seen


async def run(name, values, **kw):
    return await testers.run(name, values, Settings(), **kw)


# ------------------------------------------------------------------ ElevenLabs

@pytest.mark.parametrize("status, payload, ok, says", [
    (200, [{"model_id": "scribe_v1"}], True, "accepted the key."),
    (401, {"detail": {"status": "missing_permissions"}}, True, "limited to some products"),
    (401, {"detail": {"status": "invalid_api_key"}}, False, "refused that key"),
    (500, {}, False, "answered 500"),
])
async def test_elevenlabs(monkeypatch, status, payload, ok, says):
    key = elevenlabs_key("tester")
    seen = answering(monkeypatch, lambda r: httpx.Response(status, json=payload))
    outcome = await run("elevenlabs", {"elevenlabs_api_key": key})
    assert outcome.ok is ok and says in outcome.detail
    assert seen[0].url.path == "/v1/models" and seen[0].headers["xi-api-key"] == key and key not in str(seen[0].url)


# ------------------------------------------------------------------ YouTube

@pytest.mark.parametrize("status, text, ok, says", [
    (200, '{"items": []}', True, "accepted the key"),
    (400, '{"error": {"message": "API key not valid. Please pass a valid API key."}}', False, "not a valid API key"),
    (403, '{"error": {"errors": [{"reason": "accessNotConfigured"}]}}', False, "not switched on"),
    (403, '{"error": {"errors": [{"reason": "forbidden"}]}}', False, "restricted"),
])
async def test_youtube(monkeypatch, status, text, ok, says):
    key = google_api_key("tester")
    seen = answering(monkeypatch, lambda r: httpx.Response(status, text=text))
    outcome = await run("youtube", {"youtube_api_key": key})
    assert outcome.ok is ok and says in outcome.detail
    assert seen[0].headers["x-goog-api-key"] == key and key not in str(seen[0].url)


# ------------------------------------------------------------------ Shopify

@pytest.mark.parametrize("status, text, ok, says", [
    (200, '{"access_token": "minted", "expires_in": 86399}', True, "accepted the app's ID and secret"),
    (400, '{"error": "shop_not_permitted"}', False, "another organisation"),
    (401, '{"error": "invalid_client"}', False, "refused that ID and secret"),
])
async def test_shopify(monkeypatch, status, text, ok, says):
    secret = body("shopify-secret", 32, HEX)
    seen = answering(monkeypatch, lambda r: httpx.Response(status, text=text))
    outcome = await run("shopify", {"shopify_client_id": "client-id-1", "shopify_client_secret": secret})
    assert outcome.ok is ok and says in outcome.detail
    assert seen[0].method == "POST" and str(seen[0].url) == "https://x.myshopify.com/admin/oauth/access_token"
    assert secret not in str(seen[0].url) and secret in seen[0].content.decode()


async def test_shopify_without_a_shop_set_says_so(monkeypatch):
    class NoShop(Settings):
        shopify_shop_domain = ""

    answering(monkeypatch, lambda r: httpx.Response(200, text="{}"))
    outcome = await testers.run("shopify", {"shopify_client_id": "a", "shopify_client_secret": "b"}, NoShop())
    assert outcome.ok is False and "No shop is set" in outcome.detail


# ------------------------------------------------------------------ GitHub

@pytest.mark.parametrize("status, payload, ok, says", [
    (200, {"permissions": {"pull": True, "push": True}}, True, "accepted the token"),
    (200, {"permissions": {"pull": True, "push": False}}, False, "not write to it"),
    (401, {}, False, "refused that token"),
    (404, {}, False, "cannot see"),
])
async def test_github(monkeypatch, status, payload, ok, says):
    token = github_fine_grained_token("tester")
    seen = answering(monkeypatch, lambda r: httpx.Response(status, json=payload))
    outcome = await run("github", {"github_engineering_inbox_token": token})
    assert outcome.ok is ok and says in outcome.detail
    assert seen[0].url.path == "/repos/crooksldn-pixel/clive"
    assert seen[0].headers["authorization"] == f"Bearer {token}" and token not in str(seen[0].url)


# ------------------------------------------------------------------ Instagram

async def test_instagram_names_the_account_the_token_reads(monkeypatch):
    token = bearer_token("ig-tester")
    seen = answering(monkeypatch, lambda r: httpx.Response(200, json={"user_id": "1", "username": "crooksldn"}))
    outcome = await run("instagram", {"instagram_access_token": token}, changed=frozenset({"instagram_access_token"}))
    assert outcome.ok and outcome.who == "@crooksldn"
    assert seen[0].url.path == "/v25.0/me" and seen[0].headers["authorization"] == f"Bearer {token}"


async def test_instagram_asks_once_with_the_token_as_a_parameter_when_the_header_is_not_read(monkeypatch):
    token = bearer_token("ig-header")

    def handler(request):
        if "access_token" in request.url.params:
            return httpx.Response(200, json={"username": "crooksldn"})
        return httpx.Response(400, json={"error": {"code": 2500, "message": "An active access token must be used"}})

    seen = answering(monkeypatch, handler)
    outcome = await run("instagram", {"instagram_access_token": token}, changed=frozenset({"instagram_access_token"}))
    assert outcome.ok and len(seen) == 2


async def test_an_expired_instagram_token_is_named_and_meta_never_quoted(monkeypatch):
    answering(monkeypatch, lambda r: httpx.Response(400, json={"error": {"code": 190, "message": "MARKER expired"}}))
    outcome = await run("instagram", {"instagram_access_token": bearer_token("ig-old")},
                        changed=frozenset({"instagram_access_token"}))
    assert not outcome.ok and "expired" in outcome.detail and "MARKER" not in outcome.detail


async def test_the_app_id_and_secret_alone_wait_for_the_sign_in(monkeypatch):
    seen = answering(monkeypatch, lambda r: httpx.Response(500))
    outcome = await run("instagram", {"instagram_app_id": body("id", 16, DIGITS), "instagram_access_token": "old"},
                        changed=frozenset({"instagram_app_id"}))
    assert outcome.ok and outcome.checked is False and seen == []


# ------------------------------------------------------------------ what never happens

async def test_an_unreachable_service_is_a_failed_test_never_a_crash(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route")

    answering(monkeypatch, handler)
    outcome = await run("elevenlabs", {"elevenlabs_api_key": elevenlabs_key("down")})
    assert not outcome.ok and "could not be reached" in outcome.detail

    def slow(request):
        raise httpx.ReadTimeout("slow")

    answering(monkeypatch, slow)
    outcome = await run("elevenlabs", {"elevenlabs_api_key": elevenlabs_key("slow")})
    assert not outcome.ok and "did not answer in time" in outcome.detail


async def test_a_detail_never_carries_the_key_even_if_a_service_echoed_it(monkeypatch):
    key = elevenlabs_key("echo")
    monkeypatch.setitem(testers.TESTERS, "elevenlabs", _echoing)
    outcome = await run("elevenlabs", {"elevenlabs_api_key": key})
    assert key not in outcome.detail and "[the key]" in outcome.detail


async def _echoing(values, settings):
    return testers.Outcome(False, f"refused {values['elevenlabs_api_key']}")


async def test_a_missing_field_and_an_unknown_connection_are_failed_tests(monkeypatch):
    answering(monkeypatch, lambda r: httpx.Response(200, text="{}"))
    assert not (await run("shopify", {"shopify_client_id": "only-the-id"})).ok
    assert not (await run("gmail", {})).ok
