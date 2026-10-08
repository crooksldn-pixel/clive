"""The seal around a bench run: nothing leaves this machine, and nothing changes anywhere.

A bench run is CLIVE's real turn, end to end, asked thousands of things by people who are not
George, some of them trying to break it. The fake shop (experience/fixtures) is what it is pointed
at; this file is what makes sure that is all it can reach, and that the run stops the moment it
is not.

What the seal does while it is on, every layer on its own:

    no network       this process opens no internet connection: a socket connect to any internet
                     address is refused, loopback included (a local proxy would carry a request
                     out); a send to, a listening port on, or a lookup of anything but loopback is
                     refused; and below all of that an audit hook (sys.addaudithook) refuses every
                     socket connect, send, bind and host lookup Python's socket module makes that
                     is not loopback, which is what catches the calls that never pass through the
                     socket class (the C-level _socket, gethostbyname and the rest). Loopback is
                     judged by the address (ipaddress), and only `localhost` by name. What the
                     hook cannot see: a compiled library that opens its own sockets (CLIVE has
                     none; httpx and asyncio use the socket module), and the name a raw _socket
                     call resolves in C before its connect or send is audited (the connect or
                     send itself is still refused). The claude CLI is a separate process and
                     keeps its own connection to Claude.
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
has no way back (a process that latched stays read-only for its life), and the audit hook, which
Python cannot remove: it stays installed and, with no seal on, lets everything through.
"""

from __future__ import annotations

import inspect
import ipaddress
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.bench.store import now

LOOPBACK_NAMES = frozenset({"localhost"})
SERVED_SECRET = "claude_oauth_token"
INTERNET = frozenset({socket.AF_INET, socket.AF_INET6})
# Socket families that never leave this machine: a socket file, the kernel's own netlink (CLIVE asks
# the kernel its interface addresses that way, app/identity.py), and the kernel's crypto. Any other
# family that is not the internet's (raw frames, vsock, ...) is refused as the internet's is.
LOCAL_FAMILIES = frozenset(f for f in (getattr(socket, n, None) for n in ("AF_UNIX", "AF_NETLINK", "AF_ALG")) if f is not None)
# The socket module's audit events that put traffic on, or open a port to, a network, and what each is
# recorded as. The lookups name a host; the rest name a socket and an address.
AUDITED = {
    "socket.connect": "a network connection",
    "socket.sendto": "sending on the network",
    "socket.sendmsg": "sending on the network",
    "socket.bind": "a port open to the network",
    "socket.getaddrinfo": "looking up a host",
    "socket.gethostbyname": "looking up a host",
    "socket.gethostbyaddr": "looking up a host",
    "socket.getnameinfo": "looking up a host",
}

# The seal the audit hook answers to: set while a seal is on, None otherwise.
_watching: Seal | None = None
_hooked = False


def is_loopback(host: Any) -> bool:
    """Whether a host is this machine's loopback: `localhost` by name, otherwise an address that
    ipaddress says is loopback (127.0.0.0/8, ::1, and 127.x mapped into IPv6). A name that merely
    starts "127." is a name like any other, and is looked up on the internet."""
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    name = str(host or "").strip().lower().rstrip(".")
    if name in LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return bool((mapped or address).is_loopback)


def leaves_the_machine(family: Any, address: Any) -> bool:
    """Whether a socket of this family, connecting, sending or listening at `address`, reaches past
    this machine. The internet's families by the address's host; local families never; any other
    family always (fail closed)."""
    if family in LOCAL_FAMILIES:
        return False
    if family in INTERNET:
        host = address[0] if isinstance(address, tuple) and address else address
        return not is_loopback(host)
    return True


def _audit(event: str, args: tuple) -> None:
    """The audit hook: every socket call Python makes, judged while a seal is on. Called for every
    audited event in the process, so it does nothing at all until a seal is on and the event is a
    socket's that can reach a network."""
    seal = _watching
    if seal is None:
        return
    what = AUDITED.get(event)
    if what is None:
        return
    if what == "looking up a host":
        host = args[0] if args else None
        if event == "socket.getnameinfo":
            host = host[0] if isinstance(host, tuple) and host else host
        if event == "socket.getaddrinfo" and not host:
            return                                   # no host: the local wildcard, nothing looked up
        if not is_loopback(host):
            raise seal.breach(what, repr(host))
        return
    sock, address = (tuple(args) + (None, None))[:2]
    if address is None:
        return                                       # a send on a socket already connected (and judged then)
    if leaves_the_machine(getattr(sock, "family", None), address):
        raise seal.breach(what, repr(address))


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
        real_sendto, real_sendmsg = socket.socket.sendto, socket.socket.sendmsg
        real_resolve = socket.getaddrinfo

        def connect(sock, address, *args, **kwargs):
            if sock.family in INTERNET:
                raise seal.breach("a network connection", repr(address))
            return real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):
            if sock.family in INTERNET:
                raise seal.breach("a network connection", repr(address))
            return real_connect_ex(sock, address, *args, **kwargs)

        # A send names its address, and C looks a name up before the audit hook hears of the send:
        # judged here first, so the lookup never happens.
        def sendto(sock, data, *rest):
            if rest and leaves_the_machine(sock.family, rest[-1]):
                raise seal.breach("sending on the network", repr(rest[-1]))
            return real_sendto(sock, data, *rest)

        def sendmsg(sock, buffers, *rest):
            address = rest[2] if len(rest) > 2 else None
            if address is not None and leaves_the_machine(sock.family, address):
                raise seal.breach("sending on the network", repr(address))
            return real_sendmsg(sock, buffers, *rest)

        def create_connection(address, *args, **kwargs):
            raise seal.breach("a network connection", repr(address))

        def getaddrinfo(host, *args, **kwargs):
            if host and not is_loopback(host):
                raise seal.breach("looking up a host", str(host.decode("ascii", "replace") if isinstance(host, bytes) else host))
            return real_resolve(host, *args, **kwargs)

        self._swap(socket.socket, "connect", connect)
        self._swap(socket.socket, "connect_ex", connect_ex)
        self._swap(socket.socket, "sendto", sendto)
        self._swap(socket.socket, "sendmsg", sendmsg)
        self._swap(socket, "create_connection", create_connection)
        self._swap(socket, "getaddrinfo", getaddrinfo)
        # Under all of it, the audit hook: installed once for the process (Python has no way to take
        # one out), and listening only while this seal is the one it answers to.
        global _hooked
        if not _hooked:
            sys.addaudithook(_audit)
            _hooked = True
        self._swap(sys.modules[__name__], "_watching", self)

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
