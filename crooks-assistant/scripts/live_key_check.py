#!/usr/bin/env python3
"""Does ElevenLabs keep its word about the live words' key? (the 2026-09-28 deploy review, round 9
and 10, C-02). For the deploy, on the server, as the service's user.

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

Exit 0 when every property asked about holds; 1 when one does not (a key that opens a second
socket, or one past its life) — the design then has to stop handing the browser a bearer key; 2
when it could not be asked (no ElevenLabs key stored, no key minted, or a fresh key that would not
open even once). It prints fixed words only: never the server's key, the minted key, or anything
ElevenLabs said.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPENED, REFUSED = "opened", "refused"
# Past ElevenLabs' fifteen minutes, with a minute to spare.
EXPIRY_WAIT_S = 16 * 60
FIRST_WORD_S = 5.0


def socket_address(base_url: str, token: str) -> str:
    """The realtime socket's address with this key, as web/live-voice.js builds it from the
    route's answer: the socket beside the REST base, the route's own query, then the key."""
    from app.routes import voice

    return f"{voice.socket_url(base_url)}?{urlencode({**voice.PARAMS, 'token': token})}"


def open_once(address: str, *, timeout_s: float = 10.0) -> str:
    """OPENED when the socket's handshake succeeds and its first word is not an error; REFUSED when
    the handshake is refused, the socket closes first, or its first word is an error (message_type
    "error" or "…_error"). The socket is closed at once either way; nothing is sent on it."""
    from websockets.exceptions import WebSocketException
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
            return REFUSED if kind == "error" or kind.endswith("_error") or (isinstance(said, dict) and said.get("error")) else OPENED
    except (WebSocketException, OSError):
        return REFUSED


def check(mint: Callable[[], str], opens: Callable[[str], str], *, expiry: bool = False,
          wait_s: float = EXPIRY_WAIT_S, sleep: Callable[[float], None] = time.sleep,
          out: Callable[[str], None] = print) -> int:
    """Ask each property of fresh keys; the exit code as the module says."""
    token = mint()
    if not token:
        out("NOT ASKED: no key could be minted")
        return 2
    if opens(token) != OPENED:
        out("NOT ASKED: a fresh key would not open the socket even once")
        return 2
    out("ok     a fresh key opened one socket")
    failed = False
    if opens(token) == OPENED:
        out("FAIL   the same key opened a second socket: it is not single-use")
        failed = True
    else:
        out("ok     the same key did not open a second socket: single-use")
    if expiry:
        held = mint()
        if not held:
            out("NOT ASKED: no second key could be minted for the expiry check")
            return 1 if failed else 2
        out(f"wait   holding a fresh key unused for {wait_s / 60:.0f} minutes")
        sleep(wait_s)
        if opens(held) == OPENED:
            out(f"FAIL   a key held unused for {wait_s / 60:.0f} minutes still opened the socket")
            failed = True
        else:
            out(f"ok     a key held unused for {wait_s / 60:.0f} minutes opened nothing")
    out("VERDICT: " + ("ElevenLabs does NOT keep its word about the key" if failed else "the key is what ElevenLabs says it is"))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--expiry", action="store_true", help="also hold a key past its life (16 minutes)")
    args = parser.parse_args(argv)

    from app.routes import voice
    from config.settings import get_settings

    key = voice._api_key()
    if not key:
        print("NOT ASKED: no ElevenLabs key is stored here (run as the service's user)")
        return 2
    base = getattr(get_settings(), "elevenlabs_base_url", "") or "https://api.elevenlabs.io/v1"

    def mint() -> str:
        token, _why = asyncio.run(voice._mint(key, base))
        return token

    return check(mint, lambda token: open_once(socket_address(base, token)), expiry=args.expiry)


if __name__ == "__main__":
    raise SystemExit(main())
