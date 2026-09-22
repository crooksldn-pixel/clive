from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

# Tests must not write into the Mac's own logs/, bench/audio/ or capture store: the turn log
# is a record of real turns, and the assistant log is where the real voice is diagnosed. Set
# before any Settings() is built, which is before any app module is imported.
_TEST_STATE = tempfile.mkdtemp(prefix="crooks-tests-")
os.environ.setdefault("CROOKS_LOG_DIR", os.path.join(_TEST_STATE, "logs"))
os.environ.setdefault("CROOKS_BENCH_AUDIO_DIR", os.path.join(_TEST_STATE, "bench"))
os.environ.setdefault("CROOKS_SAVE_CAPTURES", "false")
# The read layer's cache is not warmed at boot under test: each test binds the store it wants.
os.environ.setdefault("CROOKS_ANALYTICS_WARM_DAYS", "0")
# The Linux secret store, pointed away from the real one. app/media.py loads its signing key
# at import — before any fixture has run — and on Linux that would otherwise create and write
# /etc/crooks-os/secrets as a side effect of collecting the suite. Set here, with the three
# above, because "before any Settings() is built" is also before any app module is imported.
os.environ.setdefault("CROOKS_SECRET_DIR", os.path.join(_TEST_STATE, "secrets"))

# The environment every offline test is given, whatever the Mac it runs on has in its own.
# Built from the four above so a deliberate override on the command line still works, and
# applied by _offline_environment below — which also takes everything else away.
_TEST_ENV = {
    name: os.environ[name]
    for name in (
        "CROOKS_LOG_DIR", "CROOKS_BENCH_AUDIO_DIR", "CROOKS_SAVE_CAPTURES",
        "CROOKS_ANALYTICS_WARM_DAYS", "CROOKS_SECRET_DIR",
    )
}
# No .env. This is the one that matters: `.env` is the owner's own configuration and
# pydantic-settings reads it in every process, so without this line the offline suite is
# testing his allow-list, his voice and whether his changes are switched on. See settings.py.
_TEST_ENV["CROOKS_ENV_FILE"] = ""

from app.clients.shopify import ShopifyClient  # noqa: E402 — after the environment above
from app.secrets import keychain  # noqa: E402
from config.settings import get_settings  # noqa: E402


def shopify_configured() -> bool:
    try:
        return keychain.present("shopify_client_id") or keychain.present("shopify_static_token")
    except Exception:  # noqa: BLE001 — no keyring backend at all
        return False


def gmail_configured() -> bool:
    from app.clients.gmail import TOKEN_PATH

    if TOKEN_PATH.exists():
        return True
    try:
        return keychain.present("gmail_token")
    except Exception:  # noqa: BLE001
        return False


# --- what an offline test is allowed to see -----------------------------------------------
#
# Three things reach into a test run from the Mac it happens to be running on: the owner's
# `.env`, the secrets in his login Keychain, and the network those secrets open. Each of the
# three fixtures below takes one of them away for every test that is not marked `live`, so
# that the suite's result is a fact about the code and not about the machine. `make test-live`
# selects the marked tests and they keep all three: reaching the real store is their purpose.


@pytest.fixture(autouse=True)
def _offline_environment(request, monkeypatch):
    """No .env, and no CROOKS_* inherited from the shell: one fixed configuration."""
    live = request.node.get_closest_marker("live") is not None
    if not live:
        for name in [key for key in os.environ if key.startswith("CROOKS_")]:
            monkeypatch.delenv(name, raising=False)
        for name, value in _TEST_ENV.items():
            monkeypatch.setenv(name, value)
        # Settings are built once and cached, and the cached one may have read a .env before
        # this ran. Cleared again on the way out so a live test rebuilds from the real thing.
        get_settings.cache_clear()
    yield
    if not live:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_secrets(request, monkeypatch):
    """No Keychain: every secret reads as absent, and nothing is written. All three readers
    are replaced rather than only get(), so the guarantee does not rest on the other two
    still being the versions that call it. It is not a detail of the harness — a real ElevenLabs key here means the voice
    reports "network" where the code says "no_key", and a real Gmail credential means /health
    goes to Google to read its scopes. Writing is refused outright: a test must never put
    anything into, or take anything out of, the owner's login Keychain."""
    if request.node.get_closest_marker("live"):
        return

    def absent(key: str) -> str:
        keychain._validate(key)
        raise keychain.SecretMissing(key)

    def refuse(key: str, *args) -> None:
        keychain._validate(key)
        raise AssertionError(f"a test tried to write {key!r} to the Keychain")

    monkeypatch.setattr(keychain, "get", absent)
    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    monkeypatch.setattr(keychain, "present", lambda key: False)
    monkeypatch.setattr(keychain, "set_secret", refuse)
    monkeypatch.setattr(keychain, "delete", refuse)
    # token.json beside the repository is the documented fallback for the Gmail credential,
    # and it is a file, so an absent Keychain is not by itself an absent credential.
    from app.clients import gmail

    monkeypatch.setattr(gmail, "TOKEN_PATH", pathlib.Path(_TEST_STATE) / "no-such-token.json")


# No test may reach the network. "Tests never spend ElevenLabs credit" must not rest on every
# author remembering the transport double: any lookup of a host that is not this machine
# fails here, loudly, before a socket opens. The live tests are marked and skipped by name.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "t", "testserver", "fake", "x.myshopify.com"}
# A proxy turns the guard above into a formality: the client resolves the proxy's name, which
# is a real host it is allowed to reach, and the request goes out to the address it was really
# for. httpx, requests and urllib all read these from the environment by default.
_PROXY_VARS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "ftp_proxy",
)


def _is_local_address(address) -> bool:
    """A connection this machine is allowed to make. Anything that is not a host/port pair —
    a unix socket path — is local by construction."""
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0] or "").lower()
    return (
        host in _LOCAL_HOSTS
        or host.startswith("127.")
        or host.startswith("::ffff:127.")
        or host in ("::", "::1")
        or host.endswith(".local")
    )


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    import socket

    if request.node.get_closest_marker("live"):
        return
    real = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def guarded(host, *args, **kwargs):
        name = str(host or "").lower()
        if name in _LOCAL_HOSTS or name.startswith("127.") or name.endswith(".local"):
            return real(host, *args, **kwargs)
        raise OSError(f"test tried to reach the network: {host!r}")

    def guarded_connect(self, address, *args, **kwargs):
        if not _is_local_address(address):
            raise OSError(f"test tried to reach the network: {address!r}")
        return real_connect(self, address, *args, **kwargs)

    def guarded_create(address, *args, **kwargs):
        if not _is_local_address(address):
            raise OSError(f"test tried to reach the network: {address!r}")
        return real_create(address, *args, **kwargs)

    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", guarded)
    # The name is only half of it: a resolved address, or a proxy read from somewhere this
    # fixture cannot reach, still opens a socket. This is where that stops.
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)


@pytest.fixture(autouse=True)
def _fresh_read_layer():
    """One test's reads are not another's.

    The read layer keeps two process-wide things: what has just been read, so two callers
    asking for one entity make one request (app/reads/dedupe.py), and how much of each source
    is in flight (app/reads/budget.py). Both are right in a running Mac, where there is one
    shop and one inbox — and both are wrong across a suite, where each test binds its own
    fixture world and a twelve-second reuse window is longer than the whole run. Reset for the
    same reason .env, the Keychain and the network are taken away: the suite's result must be
    a fact about the code.
    """
    from app.reads import budget, dedupe

    dedupe.current().reset()
    budget.throttle().reset()
    yield
    dedupe.current().reset()
    budget.throttle().reset()


needs_shopify = pytest.mark.skipif(
    not shopify_configured(), reason="no Shopify credentials in the Keychain (M6 not done)"
)
needs_gmail = pytest.mark.skipif(
    not gmail_configured(), reason="no Gmail token.json (M8 not done)"
)


class FakeShopify(ShopifyClient):
    """A ShopifyClient that returns canned GraphQL payloads. Lets the tools' shaping logic —
    which is where the bugs live — be tested without a network or a store."""

    def __init__(self, responses: list[dict], timezone: str = "Europe/London") -> None:
        super().__init__("fake.myshopify.com", "2025-07")
        self._responses = list(responses)
        self.queries: list[tuple[str, dict]] = []
        self._shop = {
            "name": "CROOKS LDN", "myshopifyDomain": "fake.myshopify.com",
            "ianaTimezone": timezone, "currencyCode": "GBP",
        }
        from zoneinfo import ZoneInfo

        self._tz = ZoneInfo(timezone)

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        self.queries.append((query, variables or {}))
        if not self._responses:
            raise AssertionError("FakeShopify ran out of canned responses")
        return self._responses.pop(0)


@pytest.fixture()
def fake_shopify():
    return FakeShopify
