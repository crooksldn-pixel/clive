"""The server's own test-session commands, let in by a key of their own (the 2026-09-27 deploy
review, round 6, F-05A).

`make test-session-start`, `-status` and `-stop` (scripts/test_session.py, and the Control
app's scripts/session_ops.py) run on the server and call the backend on loopback. With the
production switches — CROOKS_LOCAL_OWNER and CROOKS_WRITES_LOCAL_OWNER both off — a request made
on the server is nobody's, so those commands were refused; and the obvious way round it,
switching CROOKS_WRITES_LOCAL_OWNER on, would also let any process on the server apply changes
to the store, because the write boundary reads the same switch.

So the commands carry a key instead. The backend makes it the first time it starts and keeps it
where only root can read it — the secret store's writable tier on Linux
(/etc/crooks-os/secrets/local_cli_key, 0600 in a 0700 folder; the service runs as root), the
login Keychain on the Mac — and the command line reads it from the same place, so only someone
who could already read every credential the service holds can use it. A request carrying it in
X-Crooks-Local-Key opens exactly the routes below, and only when made on the server itself,
straight to the port (never through `tailscale serve`, which a device uses): the three
test-session routes, and the whole of GET /health, which the server's own status readers
(`make health`, crooks-status, `make install`) need and a caller the owner rule refuses does not
get (round 8, F-NEW-PAD).

It is not an owner. It opens no other route, no turn, no tool, no record and no write:
principal_verdict and caller_check never read it, and a test walks every other route to hold
that (tests/test_local_cli.py). A request that carries it where it does not apply — through the
proxy, or on any other route — is refused at the door outright, even from a device that would
pass the owner rule without it (round 7): the key means "the server's own command" or nothing.
Carrying it means carrying the header at all, whatever its value: an empty one is refused like a
wrong one (round 8, F-05A), and so are two of them.
"""

from __future__ import annotations

import hmac
import logging
import secrets

log = logging.getLogger("crooks.local_cli")

KEY_NAME = "local_cli_key"
HEADER = "X-Crooks-Local-Key"
# Method and path, exactly: nothing beneath them and nothing beside them.
ROUTES = frozenset({
    ("POST", "/test-session/start"),
    ("GET", "/test-session/status"),
    ("POST", "/test-session/stop"),
    # The whole health document for the server's own status readers (round 8, F-NEW-PAD). /health
    # is public, so without the key they would get only the liveness a stranger gets.
    ("GET", "/health"),
})
_HEADER_NAME = HEADER.lower().encode("latin-1")
_MIN_LENGTH = 32
_UNSET = object()
_bound: object = _UNSET   # tests hand in a key, or None for "there is none"


def bind_key(value: object = _UNSET) -> None:
    """Tests: the key to use in place of the secret store (None: there is none). No argument
    puts the store back."""
    global _bound
    _bound = value


def read_key() -> str | None:
    """The key, if one has been made and this process may read it; None otherwise."""
    if _bound is not _UNSET:
        stored = _bound if isinstance(_bound, str) else None
    else:
        try:
            from app.secrets import keychain

            stored = keychain.get_optional(KEY_NAME)
        except Exception:  # noqa: BLE001 — not readable by this user, or no store here: no key
            return None
    return stored if stored and len(stored) >= _MIN_LENGTH else None


def ensure_key() -> bool:
    """Made once, by the backend at start-up, and kept for the life of the machine. Never raises:
    without it the commands are refused, as they were before, and nothing else changes."""
    if read_key():
        return True
    if _bound is not _UNSET:
        return False
    try:
        from app.secrets import keychain

        keychain.set_secret(KEY_NAME, secrets.token_urlsafe(32))
    except Exception as exc:  # noqa: BLE001
        log.warning("the local command key could not be made (%s): make test-session-* will be refused", type(exc).__name__)
        return False
    return bool(read_key())


def _carried(request) -> list[bytes]:
    """Every value the request carries under the key's header name, empty ones included, read
    from the raw header list rather than through a mapping that keeps only one of them."""
    scope = getattr(request, "scope", None) or {}
    raw = scope.get("headers") or []
    return [bytes(value) for name, value in raw if bytes(name).lower() == _HEADER_NAME]


def presented(request) -> bool:
    """Whether the request carries the header at all, whatever its value. Presence, not
    truthiness (round 8, F-05A): `X-Crooks-Local-Key:` with nothing after it is a request that
    claims to be the server's own command, and is judged as one — and refused wherever the key
    does not apply, like any other value."""
    return bool(_carried(request))


def admits(request) -> bool:
    """Whether this request is one of the server's own commands, with the key: exactly one
    header, holding the key, on one of ROUTES, made straight to the port."""
    carried = _carried(request)
    # One value, or none of them counts: two headers are two claims, and which one a framework
    # would read is not a question this answers (round 8, F-05A).
    if len(carried) != 1 or not carried[0] or (request.method.upper(), request.url.path) not in ROUTES:
        return False
    from app.routes.actions import DIRECT, proxy_state

    if proxy_state(request)[0] != DIRECT:
        return False
    key = read_key()
    return bool(key) and hmac.compare_digest(carried[0], key.encode("utf-8"))


def headers() -> dict[str, str]:
    """For the command line: the header to send, when this user can read the key."""
    key = read_key()
    return {HEADER: key} if key else {}
