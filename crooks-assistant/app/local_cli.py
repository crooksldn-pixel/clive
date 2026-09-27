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
X-Crooks-Local-Key opens exactly the three test-session routes below, and only when made on the
server itself, straight to the port (never through `tailscale serve`, which a device uses).

It is not an owner. It opens no other route, no turn, no tool, no record and no write:
principal_verdict and caller_check never read it, and a test walks every other route to hold
that (tests/test_local_cli.py). A request that carries it where it does not apply — through the
proxy, or on any other route — is refused at the door outright, even from a device that would
pass the owner rule without it (round 7): the key means "the server's own command" or nothing.
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
})
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


def presented(request) -> bool:
    """Whether the request carries the key at all, valid or not."""
    return bool(request.headers.get(HEADER, ""))


def admits(request) -> bool:
    """Whether this request is one of the server's own test-session commands, with the key."""
    presented = request.headers.get(HEADER, "")
    if not presented or (request.method.upper(), request.url.path) not in ROUTES:
        return False
    from app.routes.actions import DIRECT, proxy_state

    if proxy_state(request)[0] != DIRECT:
        return False
    key = read_key()
    return bool(key) and hmac.compare_digest(presented.encode("utf-8"), key.encode("utf-8"))


def headers() -> dict[str, str]:
    """For the command line: the header to send, when this user can read the key."""
    key = read_key()
    return {HEADER: key} if key else {}
