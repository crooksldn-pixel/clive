"""scripts/live_key_check.py, the deploy's question to ElevenLabs about the live words' key (the
2026-09-28 deploy review, rounds 9 and 10, C-02).

Whether a single-use key opens one socket and lapses after fifteen minutes is ElevenLabs' to keep,
and only ElevenLabs can say so: the deploy runs the check against it. What a test can hold is that
the check asks the right question and reads the answer right, so here it is pointed at a realtime
socket on loopback that keeps its word, or breaks it, in each way ElevenLabs could: a used key
refused at the handshake or with an error as its first word, a reused key taken, an old key taken.
"""

from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests import fake_credentials as fake

pytest.importorskip("websockets.sync.server")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_key_check.py"
LIFE_S = 15 * 60


def _script():
    spec = importlib.util.spec_from_file_location("live_key_check_r11", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Realtime:
    """ElevenLabs' realtime socket, on loopback. `keeps` is what it does with a key: "word" (a
    used or lapsed key is refused at the handshake), "error" (such a key's socket opens and its
    first word is an auth error), "reuse" (a used key opens again), "forever" (a lapsed key opens)."""

    def __init__(self, keeps: str, clock) -> None:
        from websockets.sync.server import serve

        self.keeps, self.clock = keeps, clock
        self.minted: dict[str, float] = {}
        self.used: set[str] = set()
        self.paths: list[str] = []

        def refused(token: str) -> bool:
            if token not in self.minted:
                return True
            reused = token in self.used and self.keeps != "reuse"
            lapsed = self.clock() - self.minted[token] > LIFE_S and self.keeps != "forever"
            return reused or lapsed

        def process_request(connection, request):
            self.paths.append(request.path)
            token = parse_qs(urlsplit(request.path).query).get("token", [""])[0]
            if self.keeps in ("word", "reuse", "forever") and refused(token):
                return connection.respond(403, "no")
            return None

        def handler(connection):
            token = parse_qs(urlsplit(connection.request.path).query).get("token", [""])[0]
            if refused(token):
                connection.send(json.dumps({"message_type": "auth_error", "error": "Rowan's key is not valid"}))
                return
            self.used.add(token)
            connection.send(json.dumps({"message_type": "session_started", "session_id": "x"}))
            try:
                connection.recv(timeout=5)
            except Exception:  # noqa: BLE001 — the checker closes at once
                pass

        self.server = serve(handler, "127.0.0.1", 0, process_request=process_request)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def mint(self) -> str:
        token = fake.elevenlabs_single_use_token(f"r11-{len(self.minted)}")
        self.minted[token] = self.clock()
        return token

    def close(self) -> None:
        self.server.shutdown()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def realtime():
    made: list[Realtime] = []

    def make(keeps: str) -> Realtime:
        made.append(Realtime(keeps, Clock()))
        return made[-1]

    yield make
    for server in made:
        server.close()


def _run(module, server: Realtime, *, expiry: bool = False) -> tuple[int, list[str]]:
    said: list[str] = []
    base = f"ws://127.0.0.1:{server.port}/v1"
    code = module.check(server.mint, lambda token: module.open_once(module.socket_address(base, token), timeout_s=5),
                        expiry=expiry, sleep=server.clock.advance, out=said.append)
    return code, said


@pytest.mark.parametrize("keeps", ["word", "error"])
def test_a_key_that_keeps_its_word_passes_both_questions(realtime, keeps):
    module = _script()
    server = realtime(keeps)
    code, said = _run(module, server, expiry=True)
    assert code == 0, said
    assert "single-use" in said[1] and "opened nothing" in said[-2] and said[-1].startswith("VERDICT: the key is")
    path = server.paths[0]
    assert path.startswith("/v1/speech-to-text/realtime?") and "model_id=scribe_v2_realtime" in path and "commit_strategy=manual" in path
    printed = "\n".join(said)
    assert not any(token in printed for token in server.minted) and "Rowan" not in printed, "fixed words only"


def test_a_key_that_opens_a_second_socket_fails(realtime):
    code, said = _run(_script(), realtime("reuse"))
    assert code == 1 and "not single-use" in "\n".join(said) and "does NOT keep its word" in said[-1]


def test_a_key_that_outlives_its_fifteen_minutes_fails(realtime):
    code, said = _run(_script(), realtime("forever"), expiry=True)
    assert code == 1 and "still opened the socket" in "\n".join(said)


def test_a_check_that_could_not_be_asked_is_never_a_pass(realtime, monkeypatch):
    module = _script()
    server = realtime("word")
    code = module.check(lambda: "", lambda token: module.OPENED, out=lambda line: None)
    assert code == 2
    base = f"ws://127.0.0.1:{server.port}/v1"
    code = module.check(lambda: "never-minted-key-0000", lambda t: module.open_once(module.socket_address(base, t), timeout_s=5),
                        out=lambda line: None)
    assert code == 2, "a key that never opened says nothing about reuse"
    from app.routes import voice

    monkeypatch.setattr(voice, "_api_key", lambda: "")
    assert module.main([]) == 2
