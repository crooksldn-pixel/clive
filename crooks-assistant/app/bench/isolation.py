"""The seal around a bench run: nothing leaves this machine, and nothing changes anywhere.

A bench run is CLIVE's real turn, end to end, asked thousands of things by people who are not
George, some of them trying to break it. The fake shop (experience/fixtures) is what it is pointed
at; this file is what makes sure that is all it can reach, and that the run stops the moment it
is not.

What the seal does while it is on, every layer on its own:

    no network       this process opens no internet connection at all: socket connects of any
                     internet address are refused, loopback included (a local proxy would carry a
                     request out), and names other than loopback do not resolve. The claude CLI is
                     a separate process and keeps its own connection to Claude.
    no real client   once the fake shop is bound (`arm_clients`; CLIVE's start-up builds its real
                     clients first and the harness swaps them out, unused, behind a shut network),
                     building one is refused on the spot: any httpx network transport (every HTTP
                     client CLIVE has, Shopify, Instagram, Ship24, ElevenLabs, CROOKS Returns,
                     GitHub, YouTube, and whatever is added next), Gmail's Google service and its
                     credentials, and the Shopify, ElevenLabs and Whisper client classes themselves.
    no secrets       every key reads as absent, but two kinds: the Max plan's own token, only when a
                     token file was handed in, and a key CLIVE makes for itself while it runs (its
                     media signing key, the server's local command key), which is kept in this
                     process's memory and never written to a store.
    no change        the read-only latch (app/readonly.py) goes down for good: Shopify's mutate,
                     every Gmail change and the action engine's commit refuse. The bench never
                     commits anyway; this is the floor under that.
    the fake world   `check_world` holds every client the tools are bound to to the fixture's, and
                     is asked before every question. Anything else stops the run.

Every refusal is recorded as a breach with what was tried and where from, so a run that tripped
the seal says so on every result it touched, not only in a log. The refusals are OSErrors, so the
code that tried treats them as the network failure they are, and CLIVE reports a failed tool.

What it promises: on leaving, every seam is put back as it was, except the latch, which by design
has no way back (a process that latched stays read-only for its life).
"""

from __future__ import annotations

import inspect
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.bench.store import now

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
SERVED_SECRET = "claude_oauth_token"


class BenchIsolationError(OSError):
    """Something in a bench run tried to reach outside the fake shop, or to build a client that could."""


def _caller() -> str:
    """The first frame in CLIVE's own code that led here: what tried, named by module and line."""
    for frame in inspect.stack()[2:40]:
        module = frame.frame.f_globals.get("__name__", "")
        if module.startswith(("app.", "experience.")) and not module.startswith("app.bench.isolation"):
            return f"{module}:{frame.lineno}"
    return "outside CLIVE's code"


class Seal:
    """On for the length of a `with` block. `token_file` serves the Max plan's token; `latch`
    is off only in the test suite, which must not latch the whole test process read-only."""

    def __init__(self, *, token_file: Path | None = None, latch: bool = True, scratch: Path | None = None) -> None:
        self.token_file = Path(token_file) if token_file else None
        self.latch = latch
        self.scratch = scratch
        self.breaches: list[dict[str, str]] = []
        self._lock = threading.Lock()
        self._undo: list[Callable[[], None]] = []
        self.on = False
        self.armed = False

    # ---------------------------------------------------------------- the record

    def breach(self, what: str, detail: str) -> BenchIsolationError:
        row = {"what": what, "detail": str(detail)[:300], "from": _caller(), "at": now()}
        with self._lock:
            self.breaches.append(row)
        return BenchIsolationError(f"bench isolation: {what} refused ({detail})")

    def count(self) -> int:
        with self._lock:
            return len(self.breaches)

    def since(self, index: int) -> list[dict[str, str]]:
        with self._lock:
            return list(self.breaches[index:])

    # ---------------------------------------------------------------- on and off

    def _swap(self, owner: Any, name: str, replacement: Any) -> None:
        """Put `replacement` in place of `owner.name`, and remember how to put it back: a class's
        own attribute is restored, an inherited one is removed again so the inheritance shows."""
        if isinstance(owner, type) and name not in owner.__dict__:
            setattr(owner, name, replacement)
            self._undo.append(lambda: delattr(owner, name))
            return
        original = owner.__dict__[name] if isinstance(owner, type) else getattr(owner, name)
        setattr(owner, name, replacement)
        self._undo.append(lambda: setattr(owner, name, original))

    def __enter__(self) -> Seal:
        from app.providers.max_agent_sdk import assert_no_payg_credentials

        assert_no_payg_credentials()
        try:
            self._network()
            self._secrets()
        except BaseException:
            self._restore()
            raise
        if self.latch:
            from app import readonly

            readonly.engage("bench run: the fake shop only, nothing is ever committed")
        self.on = True
        return self

    def arm_clients(self) -> None:
        """Refuse every real outward client from now on. Called once the fake shop is bound: CLIVE's
        start-up builds its real clients before the harness swaps them out, and none of them is
        used or reaches anything (the network is already shut), but from here on building one is
        a breach."""
        if not self.on or self.armed:
            return
        self._clients()
        self.armed = True

    def __exit__(self, *exc: Any) -> None:
        self._restore()

    def _restore(self) -> None:
        while self._undo:
            self._undo.pop()()
        self.on = False
        self.armed = False

    # ---------------------------------------------------------------- the layers

    def _network(self) -> None:
        seal = self
        real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
        real_resolve = socket.getaddrinfo
        internet = (socket.AF_INET, socket.AF_INET6)

        def connect(sock, address, *args, **kwargs):
            if sock.family in internet:
                raise seal.breach("a network connection", repr(address))
            return real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):
            if sock.family in internet:
                raise seal.breach("a network connection", repr(address))
            return real_connect_ex(sock, address, *args, **kwargs)

        def create_connection(address, *args, **kwargs):
            raise seal.breach("a network connection", repr(address))

        def getaddrinfo(host, *args, **kwargs):
            name = (host.decode() if isinstance(host, bytes) else str(host or "")).lower()
            if name and name not in LOOPBACK_NAMES and not name.startswith("127."):
                raise seal.breach("looking up a host", name)
            return real_resolve(host, *args, **kwargs)

        self._swap(socket.socket, "connect", connect)
        self._swap(socket.socket, "connect_ex", connect_ex)
        self._swap(socket, "create_connection", create_connection)
        self._swap(socket, "getaddrinfo", getaddrinfo)

    def _refuse(self, what: str) -> Callable[..., Any]:
        seal = self

        def refused(*args: Any, **kwargs: Any) -> Any:
            raise seal.breach(what, "a bench run reaches only the fake shop")

        return refused

    def _refuse_real_init(self, cls: type, what: str) -> None:
        """Refuse building `cls` itself or a subclass of it from CLIVE's own code (a real client);
        the fake shop's own subclasses, made in experience/, are built before the seal and allowed."""
        seal = self
        original = cls.__init__

        def init(instance, *args: Any, **kwargs: Any) -> None:
            if type(instance).__module__.startswith("app."):
                raise seal.breach(what, type(instance).__name__)
            original(instance, *args, **kwargs)

        self._swap(cls, "__init__", init)

    def _clients(self) -> None:
        import httpx

        from app.clients import gmail as gmail_client
        from app.clients.elevenlabs import ScribeClient
        from app.clients.elevenlabs_tts import VoiceClient
        from app.clients.shopify import ShopifyClient
        from app.clients.whisper import WhisperClient

        self._swap(httpx.HTTPTransport, "__init__", self._refuse("a real HTTP client"))
        self._swap(httpx.AsyncHTTPTransport, "__init__", self._refuse("a real HTTP client"))
        self._swap(gmail_client.GmailClient, "_build", self._refuse("a real Gmail service"))
        self._swap(gmail_client, "load_credentials", self._refuse("Gmail's real credentials"))
        self._swap(ShopifyClient, "_client", self._refuse("a real Shopify connection"))
        self._refuse_real_init(ShopifyClient, "a real Shopify client")
        self._refuse_real_init(ScribeClient, "a real ElevenLabs Scribe client")
        self._refuse_real_init(VoiceClient, "a real ElevenLabs voice client")
        self._refuse_real_init(WhisperClient, "a real Whisper client")

    def _secrets(self) -> None:
        from app.clients import gmail as gmail_client
        from app.secrets import keychain

        # What CLIVE makes for itself while it runs (its media signing key at import, the server's
        # local command key at start-up) is kept here, in this process's memory, and nowhere else:
        # a key made in a bench run is nobody's credential and never reaches a store.
        made: dict[str, str] = {}

        def served(key: str) -> str | None:
            keychain._validate(key)
            if key in made:
                return made[key]
            if key == SERVED_SECRET and self.token_file is not None:
                value = self.token_file.read_text(encoding="utf-8").strip()
                return value or None
            return None

        def get(key: str) -> str:
            value = served(key)
            if value is None:
                raise keychain.SecretMissing(key)
            return value

        def keep(key: str, value: str, *args: Any, **kwargs: Any) -> None:
            keychain._validate(key)
            made[key] = str(value)

        def forget(key: str, *args: Any, **kwargs: Any) -> None:
            keychain._validate(key)
            made.pop(key, None)

        self._swap(keychain, "get", get)
        self._swap(keychain, "get_optional", served)
        self._swap(keychain, "present", lambda key: served(key) is not None)
        self._swap(keychain, "set_secret", keep)
        self._swap(keychain, "delete", forget)
        nowhere = (self.scratch or Path("/nonexistent")) / "no-gmail-token.json"
        self._swap(gmail_client, "TOKEN_PATH", nowhere)

    # ---------------------------------------------------------------- the world

    def check_world(self, runtime: Any) -> None:
        """Every client the tools reach the shop and the inbox through is the fake shop's. Asked
        before every question; anything else stops the run here, before it is asked."""
        from app.tools import gmail_tools, gmail_writes, shopify_tools

        problems: list[str] = []
        shops = {"runtime": getattr(runtime, "shopify", None), "the read tools": shopify_tools._client}
        cache = getattr(runtime, "order_cache", None)
        if cache is not None:
            shops["the order cache"] = cache._client()
        for where, client in shops.items():
            if type(client).__name__ != "FixtureShopify":
                problems.append(f"{where} hold {type(client).__name__}, not the fake shop")
        mails = {"runtime": getattr(runtime, "gmail", None), "the inbox tools": gmail_tools._client,
                 "the email writes": gmail_writes._client}
        for where, client in mails.items():
            if type(getattr(client, "_service", None)).__name__ != "FixtureGmailService":
                problems.append(f"{where} hold an inbox that is not the fake one")
        settings = getattr(runtime, "settings", None)
        if str(getattr(settings, "engineering_host", "off") or "off") != "off":
            problems.append("filing build requests is switched on")
        if problems:
            raise self.breach("a world that is not the fake shop", "; ".join(problems))
