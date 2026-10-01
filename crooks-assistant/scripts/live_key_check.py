#!/usr/bin/env python3
"""Does ElevenLabs keep its word about the live words' key? (the 2026-09-28 deploy review, round 9
and 10, C-02). For the deploy, on the server, as root, from the checkout being deployed.

    python scripts/live_key_check.py             one key: one socket opens with it, a second does not
    python scripts/live_key_check.py --expiry    and a fresh key held unused past fifteen minutes
                                                 opens nothing (waits 16 minutes)

POST /voice/live (app/routes/voice.py) hands the owner's phone a single-use key for ElevenLabs'
realtime speech-to-text socket. ElevenLabs says of that key that it opens one session and lapses
fifteen minutes after it is minted. The server cannot see either happen — it never sees the key
used — and the tests cannot reach ElevenLabs, so this asks ElevenLabs itself, with the server's own
key and the route's own mint (voice._mint) and socket address (voice.socket_url, voice.PARAMS),
exactly as the phone would: it opens the socket with a fresh key, closes it at once, and tries the
same key again. No audio is sent.

The server's ElevenLabs key is the one the service reads. On the server that is an encrypted
systemd credential (scripts/provision_secrets.py), which systemd decrypts into a private folder for
a unit that loads it, and the secret store (app/secrets/linux_store.py) reads it only there — so run
from a shell, root's included, this could not read it and would only ever say NOT ASKED. When that
credential is on disk, then, this asks again inside a transient unit that loads it as the service's
unit does (`systemd-run … --property=LoadCredentialEncrypted=elevenlabs_api_key:<blob>`, in this
checkout, with this interpreter) and says what that run said. systemd decrypts the key for that unit
alone, as it does for the service; it is never on a command line, and never passes through the run
that asked.

Exit 0 when every property asked about holds; 1 when one does not (a key that opens a second
socket, or one past its life) — the design then has to stop handing the browser a bearer key; 2
when it could not be asked (no ElevenLabs key stored, no key minted, a fresh key that would not
open even once, a later open that met a connection, timeout or service failure rather than a
refusal of the key, or the run under the service's credential could not be made or did not finish). It
prints fixed words only: never the server's key, the minted key, or anything ElevenLabs said.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))      # provision_secrets, as the other scripts import it

# The secret the route mints with (voice._api_key), and the flag the run inside the transient unit
# is given, so that it reads the key there and never asks a unit of its own.
KEY_NAME = "elevenlabs_api_key"
IN_UNIT = "--in-unit"

# What one open says about the key: it took it, it refused it, or nothing (round 12, SC2-02: a
# connection, a timeout or a service failure was read as a refusal, so a network fault could pass
# the single-use and expiry checks).
OPENED, REFUSED, NOT_ASKED = "opened", "refused", "not asked"
# Past ElevenLabs' fifteen minutes, with a minute to spare.
EXPIRY_WAIT_S = 16 * 60
FIRST_WORD_S = 5.0
# A handshake refused with one of these is the key refused; any other status is the service
# failing (a 429, a 5xx), which says nothing about the key.
REFUSAL_STATUSES = frozenset({401, 403})
# A first word that is the service failing rather than refusing the key: the error message types
# web/live-voice.js reads as a quota, a throttle, a busy service or a transcriber's failure, and the
# realtime service's other names for a limit or a full queue, with and without the "_error" ending.
# Each says the service would not serve now, not that the key was refused, so none can pass the
# single-use or expiry check (round 12, SC2-02).
SERVICE_FAILURES = frozenset({
    "quota_exceeded_error", "quota_exceeded",
    "throttled_error", "throttled",
    "rate_limited_error", "rate_limited",
    "commit_throttled_error", "commit_throttled",
    "resource_exhausted_error", "resource_exhausted",
    "queue_overflow_error", "queue_overflow",
    "transcriber_error",
})


def socket_address(base_url: str, token: str) -> str:
    """The realtime socket's address with this key, as web/live-voice.js builds it from the
    route's answer: the socket beside the REST base, the route's own query, then the key."""
    from app.routes import voice

    return f"{voice.socket_url(base_url)}?{urlencode({**voice.PARAMS, 'token': token})}"


def open_once(address: str, *, timeout_s: float = 10.0) -> str:
    """OPENED when the socket's handshake succeeds and its first word is not an error; REFUSED only
    when the service refuses the key in so many words: the handshake refused for authorisation
    (REFUSAL_STATUSES), or a first word that is an error (message_type "error" or "…_error", or an
    `error`) other than a service failure. Anything else is NOT_ASKED: no connection, a timeout, a
    handshake refused for another reason, a socket that closed without a word, or a first word that
    is the service failing. The socket is closed at once either way; nothing is sent on it."""
    from websockets.exceptions import InvalidStatus, WebSocketException
    from websockets.sync.client import connect

    try:
        with connect(address, open_timeout=timeout_s, close_timeout=2.0) as socket:
            try:
                first = socket.recv(timeout=FIRST_WORD_S)
            except TimeoutError:
                return OPENED            # open, and quiet: it took the key
            try:
                said = json.loads(first)
            except (TypeError, ValueError):
                return OPENED
            kind = str(said.get("message_type") or "") if isinstance(said, dict) else ""
            if kind in SERVICE_FAILURES:
                return NOT_ASKED
            return REFUSED if kind == "error" or kind.endswith("_error") or (isinstance(said, dict) and said.get("error")) else OPENED
    except InvalidStatus as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return REFUSED if status in REFUSAL_STATUSES else NOT_ASKED
    except (WebSocketException, OSError):
        return NOT_ASKED


def check(mint: Callable[[], str], opens: Callable[[str], str], *, expiry: bool = False,
          wait_s: float = EXPIRY_WAIT_S, sleep: Callable[[float], None] = time.sleep,
          out: Callable[[str], None] = print) -> int:
    """Ask each property of fresh keys; the exit code as the module says. Only a refusal of the key
    passes a property; an open that met a connection, timeout or service failure (NOT_ASKED) leaves
    it unasked, exit 2 (1 when another property has already failed)."""
    token = mint()
    if not token:
        out("NOT ASKED: no key could be minted")
        return 2
    if opens(token) != OPENED:
        out("NOT ASKED: a fresh key would not open the socket even once")
        return 2
    out("ok     a fresh key opened one socket")
    failed = False
    second = opens(token)
    if second == OPENED:
        out("FAIL   the same key opened a second socket: it is not single-use")
        failed = True
    elif second == REFUSED:
        out("ok     the same key did not open a second socket: single-use")
    else:
        out("NOT ASKED: the second socket met a connection, timeout or service failure, not a refusal of the key")
        return 2
    if expiry:
        held = mint()
        if not held:
            out("NOT ASKED: no second key could be minted for the expiry check")
            return 1 if failed else 2
        out(f"wait   holding a fresh key unused for {wait_s / 60:.0f} minutes")
        sleep(wait_s)
        late = opens(held)
        if late == OPENED:
            out(f"FAIL   a key held unused for {wait_s / 60:.0f} minutes still opened the socket")
            failed = True
        elif late == REFUSED:
            out(f"ok     a key held unused for {wait_s / 60:.0f} minutes opened nothing")
        else:
            out("NOT ASKED: the held key's socket met a connection, timeout or service failure, not a refusal of the key")
            return 1 if failed else 2
    out("VERDICT: " + ("ElevenLabs does NOT keep its word about the key" if failed else "the key is what ElevenLabs says it is"))
    return 1 if failed else 0


def _say(line: str) -> None:
    print(line, flush=True)


def credential_blob() -> Path | None:
    """The encrypted credential the ElevenLabs key is provisioned as (scripts/provision_secrets.py
    encrypted_path), which the service's unit loads with LoadCredentialEncrypted= and a shell cannot
    read; None when there is none."""
    import provision_secrets

    blob = provision_secrets.encrypted_path(KEY_NAME)
    return blob if blob.is_file() else None


def unit_command(blob: Path, args: list[str]) -> list[str]:
    """This check again, inside a transient unit that loads the key as the service's unit does: the
    same credential under the same name (systemd refuses it under any other), this checkout as its
    working directory (so its .env is read, as the service reads it), this interpreter, unbuffered so
    each line arrives as it is said. --wait and --pipe: its output and its exit code are this run's."""
    return ["systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            f"--property=LoadCredentialEncrypted={KEY_NAME}:{blob}",
            f"--property=WorkingDirectory={ROOT}",
            sys.executable, "-u", str(Path(__file__).resolve()), IN_UNIT, *args]


def under_the_units_credential(blob: Path, args: list[str], *, spawn=subprocess.Popen,
                               out: Callable[[str], None] = _say) -> int:
    """Ask inside a transient unit that holds the service's credential, say each line it says, and
    return its exit code — but only a code its own words back: 0 after its passing verdict, 1 after
    a FAIL, 2 after NOT ASKED. Anything else (systemd-run missing or refused, the unit not started,
    the run cut short or crashed) is 2: it could not be asked, which is never a pass or a fail."""
    if shutil.which("systemd-run") is None:
        out("NOT ASKED: the ElevenLabs key is a systemd credential and systemd-run is not here to load it")
        return 2
    try:
        child = spawn(unit_command(blob, args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    except OSError as exc:
        out(f"NOT ASKED: the check could not be started under the service's credential ({type(exc).__name__})")
        return 2
    said: list[str] = []
    for line in child.stdout:
        said.append(line.rstrip("\n"))
        out(said[-1])
    code = child.wait()
    backed = {0: any(line.startswith("VERDICT: the key is") for line in said),
              1: any(line.startswith("FAIL") for line in said),
              2: any(line.startswith("NOT ASKED") for line in said)}
    if backed.get(code):
        return code
    out(f"NOT ASKED: the check under the service's credential did not finish (systemd-run exit {code})")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expiry", action="store_true", help="also hold a key past its life (16 minutes)")
    parser.add_argument(IN_UNIT, action="store_true", dest="in_unit", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    # The key the service uses: its unit's credential when one is provisioned, read where systemd
    # puts it for a unit and nowhere else. Asked once, from outside a unit; inside one, never again.
    if not args.in_unit and not os.environ.get("CREDENTIALS_DIRECTORY"):
        blob = credential_blob()
        if blob is not None:
            return under_the_units_credential(blob, ["--expiry"] if args.expiry else [])

    from app.routes import voice
    from config.settings import get_settings

    key = voice._api_key()
    if not key:
        print("NOT ASKED: no ElevenLabs key could be read here "
              + ("(the service's credential was loaded and holds none)" if args.in_unit
                 else "(none is provisioned: python scripts/provision_secrets.py elevenlabs_api_key)"))
        return 2
    base = getattr(get_settings(), "elevenlabs_base_url", "") or "https://api.elevenlabs.io/v1"

    def mint() -> str:
        token, _why = asyncio.run(voice._mint(key, base))
        return token

    return check(mint, lambda token: open_once(socket_address(base, token)), expiry=args.expiry)


if __name__ == "__main__":
    raise SystemExit(main())
