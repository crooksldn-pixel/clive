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
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests import fake_credentials as fake

pytest.importorskip("websockets.sync.server")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_key_check.py"
LIFE_S = 15 * 60

# The secret store's genuine readers, captured at import, before conftest's `_no_secrets` replaces
# them for each test (as tests/test_linux_store.py does): the run inside the unit reads the key
# through them, from a credentials folder in a temporary directory, with the Linux dispatch forced.
from app.secrets import keychain  # noqa: E402

_REAL_READERS = {name: getattr(keychain, name) for name in ("get", "get_optional")}


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


def test_a_check_that_could_not_be_asked_is_never_a_pass(realtime, monkeypatch, tmp_path):
    module = _script()
    server = realtime("word")
    code = module.check(lambda: "", lambda token: module.OPENED, out=lambda line: None)
    assert code == 2
    base = f"ws://127.0.0.1:{server.port}/v1"
    code = module.check(lambda: "never-minted-key-0000", lambda t: module.open_once(module.socket_address(base, t), timeout_s=5),
                        out=lambda line: None)
    assert code == 2, "a key that never opened says nothing about reuse"
    import provision_secrets

    from app.routes import voice

    # No credential provisioned (an empty credentials folder, whatever this machine has), and no
    # key readable here: nothing asked.
    monkeypatch.setattr(provision_secrets, "CRED_DIR", tmp_path / "credentials")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setattr(voice, "_api_key", lambda: "")
    assert module.main([]) == 2


# ------------------------------------------------ the key the service reads: its unit's credential

# systemd-run, stood in for: it notes how it was asked, and says what the run inside the unit would
# say, with that run's exit code. The real one loads the credential and runs the check in the unit.
FAKE_SYSTEMD_RUN = """#!{python}
import json, os, sys
with open(os.environ["FAKE_SYSTEMD_RUN_LOG"], "w") as log:
    json.dump({{"argv": sys.argv[1:], "credentials": os.environ.get("CREDENTIALS_DIRECTORY")}}, log)
said = os.environ.get("FAKE_SAID", "")
if said:
    print(said, flush=True)
sys.exit(int(os.environ.get("FAKE_CODE", "0")))
"""


@pytest.fixture()
def unit_credential(tmp_path, monkeypatch):
    """A host where the ElevenLabs key is provisioned as an encrypted credential only a unit can
    read, and `systemd-run` answers as FAKE_SYSTEMD_RUN does. Returns (the script, the credential, the
    run's log, voice._api_key as the route has it)."""
    module = _script()
    import provision_secrets

    folder = tmp_path / "credentials"
    folder.mkdir()
    blob = folder / "elevenlabs_api_key.cred"
    blob.write_bytes(b"an encrypted blob, as systemd-creds writes one")
    monkeypatch.setattr(provision_secrets, "CRED_DIR", folder)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    runner = bin_dir / "systemd-run"
    runner.write_text(FAKE_SYSTEMD_RUN.format(python=sys.executable))
    runner.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    log = tmp_path / "systemd-run.json"
    monkeypatch.setenv("FAKE_SYSTEMD_RUN_LOG", str(log))

    from app.routes import voice

    real = voice._api_key

    def never(*_args):
        raise AssertionError("outside the unit the key is never read: the unit reads it")

    monkeypatch.setattr(voice, "_api_key", never)
    return module, blob, log, real


@pytest.mark.parametrize("expiry", [False, True])
def test_a_key_only_the_units_credential_holds_is_asked_for_inside_a_unit_that_loads_it(unit_credential, monkeypatch, capsys, expiry):
    """R9-C-C-02's deploy check, as the server keeps the key. The ElevenLabs key there is an
    encrypted systemd credential that a shell, root's included, cannot read (app/secrets/
    linux_store.py tier A), so a check run from a shell that only read the key itself would say
    NOT ASKED and settle nothing. Instead it asks again inside a transient unit that loads that very
    credential under its own name, in this checkout, with this interpreter — and its words and its
    exit code are the check's."""
    module, blob, log, _real = unit_credential
    monkeypatch.setenv("FAKE_SAID", "ok     a fresh key opened one socket\nVERDICT: the key is what ElevenLabs says it is")
    monkeypatch.setenv("FAKE_CODE", "0")
    assert module.main(["--expiry"] if expiry else []) == 0
    ran = json.loads(log.read_text())
    assert ran["argv"] == ["--quiet", "--wait", "--pipe", "--collect",
                           f"--property=LoadCredentialEncrypted=elevenlabs_api_key:{blob}",
                           f"--property=WorkingDirectory={SCRIPT.parents[1]}",
                           sys.executable, "-u", str(SCRIPT), "--in-unit", *(["--expiry"] if expiry else [])]
    assert ran["credentials"] is None, "the credential is systemd's to load, not this run's to hand over"
    out = capsys.readouterr().out
    assert "VERDICT: the key is what ElevenLabs says it is" in out
    monkeypatch.setenv("FAKE_SAID", "ok     a fresh key opened one socket\nFAIL   the same key opened a second socket: it is not single-use")
    monkeypatch.setenv("FAKE_CODE", "1")
    assert module.main([]) == 1, "the unit's FAIL is the check's"


@pytest.mark.parametrize("said, code", [
    ("", 1),                                               # systemd-run refused, or the run crashed
    ("ok     a fresh key opened one socket", 1),           # cut short after a line, no FAIL said
    ("", 0),                                               # a clean exit that said no verdict
    ("", 130),                                             # interrupted
])
def test_a_run_under_the_credential_that_did_not_finish_is_not_asked_never_a_pass_or_a_fail(unit_credential, monkeypatch, capsys, said, code):
    module, _blob, _log, _real = unit_credential
    monkeypatch.setenv("FAKE_SAID", said)
    monkeypatch.setenv("FAKE_CODE", str(code))
    assert module.main([]) == 2
    assert "NOT ASKED: the check under the service's credential did not finish" in capsys.readouterr().out


def test_without_systemd_run_a_key_only_a_unit_can_read_is_not_asked(unit_credential, monkeypatch, tmp_path, capsys):
    module, _blob, _log, _real = unit_credential
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert module.main([]) == 2
    assert "systemd-run is not here" in capsys.readouterr().out


def test_inside_the_unit_the_key_is_the_credential_systemd_loaded_and_it_asks_no_unit_of_its_own(unit_credential, realtime, monkeypatch, tmp_path, capsys):
    """The run inside the transient unit: the key is read from the credentials folder systemd made
    for it, through the service's own reader (voice._api_key -> the secret store), and the check
    runs there — it never asks for a unit again, though the encrypted credential is on disk."""
    module, _blob, log, real_api_key = unit_credential
    loaded = tmp_path / "loaded"
    loaded.mkdir()
    key = fake.elevenlabs_key("r11-unit")
    (loaded / "elevenlabs_api_key").write_text(key + "\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(loaded))
    monkeypatch.setenv("CROOKS_SECRET_DIR", str(tmp_path / "no-writable-store"))
    monkeypatch.setattr(keychain, "_on_linux", lambda: True)
    for name, reader in _REAL_READERS.items():
        monkeypatch.setattr(keychain, name, reader)
    from app.routes import voice

    monkeypatch.setattr(voice, "_api_key", real_api_key)      # inside the unit the route's own reader reads it
    server = realtime("word")
    asked_with: list[str] = []

    async def mint(with_key, base_url):
        asked_with.append(with_key)
        return server.mint(), ""

    monkeypatch.setattr(voice, "_mint", mint)
    import config.settings

    monkeypatch.setattr(config.settings, "get_settings",
                        lambda: config.settings.Settings(_env_file=None, elevenlabs_base_url=f"ws://127.0.0.1:{server.port}/v1"))
    assert module.main(["--in-unit"]) == 0
    assert asked_with and set(asked_with) == {key}, "minted with the key the unit's credential holds"
    assert not log.exists(), "no unit asked from inside the unit"
    out = capsys.readouterr().out
    assert "VERDICT: the key is what ElevenLabs says it is" in out and key not in out
    (loaded / "elevenlabs_api_key").unlink()
    assert module.main(["--in-unit"]) == 2
    assert "the service's credential was loaded and holds none" in capsys.readouterr().out
    assert not log.exists()

