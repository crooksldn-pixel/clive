"""Follow-ups from the round-12 deploy review: the live words keep the start and the end of what he
says, the live-key check never passes on a network fault, and CLIVE's records, its watch and the
pad's health say what is true.

- S4-N01, S4-N02 (web/live-voice.js): run under Node, tests/web/followups-live-voice.test.js.
- SC2-02 (scripts/live_key_check.py): a connection, a timeout or a service failure is NOT ASKED,
  exit 2, never a refusal of the key and so never a pass. The transport is stood in for; nothing
  here opens a socket.
- O1-02 (app/observability/visible.py): a count or a depth a page sent that is not a number is
  unknown, not nought, and FOCUS_LOST is filed only between two that can be read.
- O2-N-03 (app/observability/claims.py): "open in the app" is a screen claim, read from the
  model's answer only, and the App Store is not the app.
- SC1-02 (scripts/watch.py): a screen claim is printed as one, with `claim` and `drew` let through
  only as their own controlled values.
- R9-F-observability2-F-OBS2-01 (app/observability/timeline.py, visible.py, touch.py): a told name
  a page sends in an identifier's shape is withheld as the plain name is, in the findings and in
  every table of the report.
- T1-04 (tests/test_pad.py _limited_to_liveness): the housekeeping check must be there, and is a
  verdict, passing or failing, and nothing else.

Every name, order and key here is invented; the keys are tests/fake_credentials.py's.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.observability import claims, timeline, visible
from app.observability.report import build_report, reconstruct
from app.observability.timeline import read_events
from scripts import watch
from tests import fake_credentials as fake
from tests.test_pad import (
    SECRET_DETAIL,
    _limited_to_liveness,
    _production_with_a_failing_check,
    client,  # noqa: F401 — the pad tests' app, lifespan and all
)

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


# ------------------------------------------------------------------ S4-N01, S4-N02: under Node


@needs_node
def test_the_live_words_keep_the_start_and_the_end_of_what_he_says_under_node():
    """The audio said while the worklet's module loads, the part of a batch the worklet holds at the
    release and the batches posted but not yet delivered all reach the socket before the commit
    (tests/web/followups-live-voice.test.js, running web/live-voice.js's own code)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "followups-live-voice.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


# ------------------------------------------------------------------ SC2-02: the live-key check

SCRIPT = ROOT / "scripts" / "live_key_check.py"
ADDRESS = "wss://example.test/v1/speech-to-text/realtime?token=stand-in"


def _key_check():
    spec = importlib.util.spec_from_file_location("live_key_check_followups", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Socket:
    """An open realtime socket whose first word (or what it raises instead) the test chooses."""

    def __init__(self, first: Any) -> None:
        self.first = first

    def __enter__(self) -> _Socket:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def recv(self, timeout: float | None = None) -> str:
        if isinstance(self.first, BaseException):
            raise self.first
        return self.first


def _transport(monkeypatch, *answers: Any) -> list[str]:
    """websockets' own connect, stood in for: each open takes the next answer — an exception the
    handshake raises, or the socket's first word (or what its recv raises). Returns the addresses
    asked for."""
    pytest.importorskip("websockets.sync.client")
    import websockets.sync.client

    asked: list[str] = []
    queue = list(answers)

    def connect(address: str, **_options: Any) -> _Socket:
        asked.append(address)
        answer = queue.pop(0)
        if isinstance(answer, tuple) and answer[0] == "handshake":
            raise answer[1]
        return _Socket(answer)

    monkeypatch.setattr(websockets.sync.client, "connect", connect)
    return asked


def _status(code: int) -> Exception:
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    return InvalidStatus(Response(code, "stand-in", Headers()))


def _closed() -> Exception:
    from websockets.exceptions import ConnectionClosedError

    return ConnectionClosedError(None, None)


SESSION_STARTED = json.dumps({"message_type": "session_started", "session_id": "x"})
AUTH_ERROR = json.dumps({"message_type": "auth_error", "error": "the key is not valid"})


def _explicit_refusals() -> list[tuple[str, Any]]:
    return [
        ("a handshake refused 401", ("handshake", _status(401))),
        ("a handshake refused 403", ("handshake", _status(403))),
        ("an auth error as the first word", AUTH_ERROR),
        ("an authentication error as the first word", json.dumps({"message_type": "authentication_error", "error": "no"})),
    ]


def _faults() -> list[tuple[str, Any]]:
    return [
        ("no connection", ("handshake", ConnectionRefusedError(111, "refused"))),
        ("a network that is unreachable", ("handshake", OSError(101, "unreachable"))),
        ("a handshake that timed out", ("handshake", TimeoutError("timed out"))),
        ("a service failing at the handshake (503)", ("handshake", _status(503))),
        ("a service throttling at the handshake (429)", ("handshake", _status(429))),
        ("a socket that closed without a word", _closed()),
        ("a socket open and quiet past the wait for its first word", TimeoutError("no word yet")),
        ("a bare error as the first word", json.dumps({"message_type": "error", "error": "no"})),
        ("an error with no type as the first word", json.dumps({"error": "no"})),
        ("an unlisted server error", json.dumps({"message_type": "internal_server_error", "error": "boom"})),
        ("an unlisted service error", json.dumps({"message_type": "service_unavailable_error", "error": "down"})),
        ("an unlisted error with no text", json.dumps({"message_type": "upstream_timeout_error"})),
        ("a quota exceeded", json.dumps({"message_type": "quota_exceeded_error", "error": "quota"})),
        ("a busy transcriber", json.dumps({"message_type": "resource_exhausted_error", "error": "busy"})),
        ("a rate limit", json.dumps({"message_type": "rate_limited_error", "error": "slow down"})),
        ("a commit throttled", json.dumps({"message_type": "commit_throttled_error", "error": "slow down"})),
        ("a full queue", json.dumps({"message_type": "queue_overflow_error", "error": "full"})),
        ("a rate limit without the ending", json.dumps({"message_type": "rate_limited", "error": "slow down"})),
        ("a rate limit without the ending or a text", json.dumps({"message_type": "rate_limited"})),
    ]


@pytest.mark.parametrize("kind", ["rate_limited_error", "commit_throttled_error"])
def test_a_service_limit_as_the_first_word_never_passes_single_use_or_expiry(kind, monkeypatch):
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    limit = json.dumps({"message_type": kind, "error": "the service is busy"})
    _transport(monkeypatch, limit)
    assert module.open_once(ADDRESS, timeout_s=1) == module.NOT_ASKED
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, limit)
    assert code == 2 and said[-1].startswith("NOT ASKED"), said
    assert not any(line.startswith("ok") and "single-use" in line for line in said), said
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, ("handshake", _status(401)), limit, expiry=True)
    assert code == 2 and said[-1].startswith("NOT ASKED"), said
    assert not any("opened nothing" in line for line in said), said


def test_open_once_tells_a_refusal_of_the_key_from_a_fault_on_the_way(monkeypatch):
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    for what, answer in _explicit_refusals():
        _transport(monkeypatch, answer)
        assert module.open_once(ADDRESS, timeout_s=1) == module.REFUSED, what
    for what, answer in _faults():
        _transport(monkeypatch, answer)
        assert module.open_once(ADDRESS, timeout_s=1) == module.NOT_ASKED, what
    _transport(monkeypatch, SESSION_STARTED)
    assert module.open_once(ADDRESS, timeout_s=1) == module.OPENED, "a first word that is not an error"


@pytest.mark.parametrize("kind", ["internal_server_error", "service_unavailable_error", "error"])
def test_an_error_that_is_not_a_refusal_of_the_key_passes_neither_single_use_nor_expiry(kind, monkeypatch):
    """Only an error that names the key refused (auth_error, authentication_error) is a refusal:
    a server or service error not listed anywhere, or a bare "error", is NOT ASKED."""
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    failing = json.dumps({"message_type": kind, "error": "the service is failing"})
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, failing)
    assert code == 2 and said[-1].startswith("NOT ASKED"), said
    assert not any(line.startswith("ok") and "single-use" in line for line in said), said
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, AUTH_ERROR, failing, expiry=True)
    assert code == 2 and said[-1].startswith("NOT ASKED"), said
    assert not any("opened nothing" in line for line in said), said


def test_a_socket_quiet_past_the_wait_for_its_first_word_is_not_asked_in_every_check(monkeypatch):
    """A receive timeout says nothing about the key: not that the first open took it, not that a
    second open or the held key's open did (a FAIL), and not that they were refused (a pass)."""
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    quiet = TimeoutError("no word yet")
    code, said, asked = _ask(module, monkeypatch, quiet)
    assert code == 2 and len(asked) == 1 and said == ["NOT ASKED: a fresh key would not open the socket even once"], said
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, quiet)
    assert code == 2 and said[-1].startswith("NOT ASKED: the second socket"), said
    assert not any(line.startswith(("FAIL", "VERDICT")) or ("single-use" in line and line.startswith("ok")) for line in said), said
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, AUTH_ERROR, quiet, expiry=True)
    assert code == 2 and said[-1].startswith("NOT ASKED: the held key's socket"), said
    assert not any(line.startswith(("FAIL", "VERDICT")) or "opened nothing" in line for line in said), said


KEYS = (fake.elevenlabs_single_use_token("followups-1"), fake.elevenlabs_single_use_token("followups-2"))


def _ask(module, monkeypatch, *answers: Any, expiry: bool = False) -> tuple[int, list[str], list[str]]:
    asked = _transport(monkeypatch, *answers)
    said: list[str] = []
    minted = iter(KEYS)
    code = module.check(lambda: next(minted), lambda token: module.open_once(f"{ADDRESS}-{len(token)}", timeout_s=1),
                        expiry=expiry, sleep=lambda _s: None, out=said.append)
    return code, said, asked


def test_a_network_fault_on_the_second_open_is_not_asked_never_single_use(monkeypatch):
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    for what, fault in _faults():
        code, said, asked = _ask(module, monkeypatch, SESSION_STARTED, fault)
        assert code == 2, (what, said)
        assert len(asked) == 2
        assert any(line.startswith("NOT ASKED") for line in said), (what, said)
        assert not any("single-use" in line and line.startswith("ok") for line in said), (what, said)
        assert not any(line.startswith("VERDICT") for line in said), (what, said)


def test_a_network_fault_on_the_held_key_is_not_asked_never_expired(monkeypatch):
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    for what, fault in _faults():
        code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, ("handshake", _status(403)), fault, expiry=True)
        assert code == 2, (what, said)
        assert "ok     the same key did not open a second socket: single-use" in said
        assert said[-1].startswith("NOT ASKED"), (what, said)
        assert not any("opened nothing" in line for line in said), (what, said)
    # A key already shown not to be single-use is still a fail, whatever the expiry check met.
    code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, SESSION_STARTED, ("handshake", OSError(101, "x")), expiry=True)
    assert code == 1 and any(line.startswith("FAIL") for line in said) and said[-1].startswith("NOT ASKED")


def test_an_explicit_refusal_still_passes_and_no_key_is_ever_printed(monkeypatch):
    pytest.importorskip("websockets.sync.client")
    module = _key_check()
    for what, refusal in _explicit_refusals():
        code, said, _asked = _ask(module, monkeypatch, SESSION_STARTED, refusal, refusal, expiry=True)
        assert code == 0, (what, said)
        assert said[-1].startswith("VERDICT: the key is"), said
        printed = "\n".join(said)
        assert not any(key in printed for key in KEYS) and "not valid" not in printed, "fixed words only"


# ------------------------------------------------------------------ O1-02: a malformed count is unknown


def _focus_reading(tmp_path: Path, name: str, *events: tuple[str, dict[str, Any]]):
    from tests.test_experience_analyser import Tape, render, turn

    tape = Tape(f"ts-20261001-090000-{name}")
    t = turn(tape, "turn_focus", said="write to the supplier", answer="The composer is open.", ui=["email_compose"])
    for kind, fields in events:
        if kind == "render":
            render(tape, t, [{"i": 0, "type": "email_compose"}])
        else:
            tape.add(kind, source="tablet", session_id="s1", turn_id=t, **fields)
    reading = visible.read(reconstruct(read_events(tape.write(tmp_path / name))))
    assert not reading.errors, reading.errors
    return [f for f in reading.findings if f.name == "FOCUS_LOST"]


def test_a_value_a_page_sent_that_is_not_a_number_is_unknown_not_nought():
    assert visible._whole(12) == 12 and visible._whole(" 12 ") == 12 and visible._whole(0) == 0
    assert visible._whole(874.0) == 874 and visible._whole("-3") == -3 and visible._whole(0.0) == 0
    for value in ("twelve", "", "12px", None, True, False, float("nan"), float("inf"), [12], {"n": 12},
                  fake.shopify_token("count"), 12.7, 0.4, -0.5, 874.5, "12.0"):
        assert visible._whole(value) is None, value


def test_a_fractional_count_or_depth_is_unknown_and_whole_floats_read_as_before(tmp_path):
    def field(chars: Any) -> tuple[str, dict[str, Any]]:
        return "tablet_compose_field", {"name": "body", "chars": chars}

    def scroll(depth: Any, height: Any = 1547) -> tuple[str, dict[str, Any]]:
        return "tablet_scroll", {"depth": depth, "height": height, "width": 680}

    for name, events in (
        ("chars-fraction-then-none", [field(12.7), ("render", {}), field(0)]),
        ("chars-valid-then-fraction", [field(12), ("render", {}), field(0.4)]),
        ("chars-fraction-between", [field(12), field(3.5), ("render", {}), field(0)]),
        ("scroll-deep-fraction", [scroll(874.5), ("render", {}), scroll(0)]),
        ("scroll-top-fraction", [scroll(874), ("render", {}), scroll(0.4)]),
        ("scroll-height-fraction", [scroll(874), ("render", {}), scroll(0, 1547.5)]),
    ):
        assert _focus_reading(tmp_path, f"fraction-{name}", *events) == [], name
    # A float that is whole is the number it says, so the cases that were real stay found.
    found = _focus_reading(tmp_path, "fraction-chars-whole", field(27.0), ("render", {}), field(0.0))
    assert [f.signal for f in found] == ["the composer's body held 27 character(s) and then held none"]
    found = _focus_reading(tmp_path, "fraction-scroll-whole", scroll(874.0, 1547.0), ("render", {}), scroll(0.0, 1547.0))
    assert [f.subject for f in found] == ["scroll"]


def test_a_composer_count_that_is_not_a_number_after_a_valid_one_is_not_a_field_emptied(tmp_path):
    token = fake.shopify_token("chars")
    field = {"name": "body"}
    for name, counts in (("token", [12, token, "twelve"]), ("word", [12, "twelve", 0]), ("missing", [12, None, 0]),
                         ("render", [12, "render", "lots"])):
        events = []
        for count in counts:
            if count == "render":
                events.append(("render", {}))
            else:
                events.append(("tablet_compose_field", {**field, "chars": count}))
        assert _focus_reading(tmp_path, f"chars-{name}", *events) == [], counts
    # Two counts that can both be read are as they were: something, a redraw, then nothing.
    found = _focus_reading(tmp_path, "chars-valid", ("tablet_compose_field", {"name": "to", "chars": 27}), ("render", {}),
                           ("tablet_compose_field", {"name": "to", "chars": 0}))
    assert [f.signal for f in found] == ["the composer's to held 27 character(s) and then held none"]


def test_a_scroll_depth_that_is_not_a_number_is_not_a_return_to_the_top(tmp_path):
    def scroll(depth: Any, height: Any = 1547) -> tuple[str, dict[str, Any]]:
        return "tablet_scroll", {"depth": depth, "height": height, "width": 680}

    for name, events in (
        ("top-word", [scroll(874), ("render", {}), scroll("top")]),
        ("top-token", [scroll(874), ("render", {}), scroll(fake.shopify_token("depth"))]),
        ("top-missing", [scroll(874), ("render", {}), scroll(None)]),
        ("between", [scroll(874), scroll("somewhere"), ("render", {}), scroll(0)]),
        ("deep-word", [scroll("deep"), ("render", {}), scroll(0)]),
        ("height-word", [scroll(874), ("render", {}), scroll(0, "tall")]),
    ):
        assert _focus_reading(tmp_path, f"scroll-{name}", *events) == [], name
    # A depth and a top that can both be read, in one document, are as they were.
    found = _focus_reading(tmp_path, "scroll-valid", scroll(874), ("render", {}), scroll(0))
    assert [f.subject for f in found] == ["scroll"]
    assert "the scroll was 874 px down the same 1547 px document and returned to the top" in found[0].signal


# ------------------------------------------------------------------ O2-N-03: "in the app"


@pytest.mark.parametrize("answer", [
    "Order #1938 is open in the app now.",
    "It's up in the app.",
    "Paid, not shipped. It's showing in your app.",
])
def test_open_or_up_in_the_app_is_a_claim_that_it_is_on_his_screen(answer):
    assert claims.claims_on_screen(answer)
    assert claims.NOT_ON_SCREEN in claims.without_the_claim(answer)


@pytest.mark.parametrize("answer", [
    "Is order #1938 open in the app?",                      # a question
    "Shall I put it up in the app?",
    "I can put #1938 up in the app.",                       # an offer
    "Want me to open it up in the app",
    "It will be up in the app in a moment.",                # the future
    "It'll be open in the app once it loads.",
    "If you tap Show, it's up in the app.",                 # a condition
    "It isn't open in the app yet.",                        # a negation
    "Order #1938 is not up in the app.",
    "The app is up in the App Store.",                      # the App Store, not the app
    "It's showing in the App Store now.",
    "You can find it in the app.",
])
def test_a_question_an_offer_the_future_a_condition_a_negation_or_the_app_store_is_not(answer):
    assert not claims.claims_on_screen(answer)


# ------------------------------------------------------------------ SC1-02: the watch


def _event(kind: str, **fields: Any) -> dict[str, Any]:
    event = {"kind": kind, "iso": "2026-10-01T09:00:00", "ts": 1_800_000_000.0, "turn_id": "turn_followups01",
             "session_id": "s1"}
    event.update(fields)
    return event


def test_a_screen_claim_is_printed_as_a_screen_claim():
    w = watch.Watch(colour=False, verbose=True)
    drew = w.lines(_event("unsupported_claim", **claims.screen_claim(drew="#1938", named=["1938"])))
    assert len(drew) == 1 and drew[0].endswith("said it was on screen when nothing was; drew #1938"), drew
    corrected = w.lines(_event("unsupported_claim", **claims.screen_claim(corrected=True)))
    assert corrected[0].endswith("said it was on screen when nothing was; corrected the answer"), corrected
    kind = w.lines(_event("unsupported_claim", **claims.screen_claim(drew="customer")))
    assert kind[0].endswith("drew customer"), kind
    # A decline claim is still printed as one.
    decline = w.lines(_event("unsupported_claim", false_unsupported=True, capabilities=["best_sellers"]))
    assert decline[0].endswith("said it cannot, though it can"), decline
    assert watch.line(_event("unsupported_claim", claim="on_screen", drew="#1940"), colour=False, verbose=True).endswith("drew #1940")


def test_claim_and_drew_pass_only_as_their_own_controlled_values():
    assert "claim" not in watch.SAFE and "drew" not in watch.SAFE
    w = watch.Watch(colour=False, verbose=True)
    name = "Zoe Quill"
    labelled = w.lines(_event("unsupported_claim", claim="on_screen", drew=name, corrected=False))
    assert labelled[0].endswith("drew a record") and "Zoe" not in labelled[0], labelled
    for drew in ("zoe_quill", "Order #1938 for Zoe Quill", {"label": name}, ["#1938"]):
        out = "\n".join(w.lines(_event("unsupported_claim", claim="on_screen", drew=drew)))
        assert out.endswith("drew a record") and "zoe" not in out.lower(), out
    # A claim that is not one of its values is not let through, nor anything it carries.
    odd = w.lines(_event("unsupported_claim", claim=f"{name} is on screen", drew="#1938"))
    assert "Zoe" not in "\n".join(odd) and "on screen" not in "\n".join(odd), odd


# ------------------------------------------------------------------ R9-F-observability2-F-OBS2-01

TOLD = "Zoe Quill"
JOINED = ("zoe_quill", "zoe.quill", "zoe-quill", "zoe:quill", "zoe/quill", "zoe#quill", "Zoe_Quill")


@pytest.fixture()
def told():
    """A customer name this process has been told (timeline.note_names), and nothing else."""
    timeline.forget_names()
    timeline.note_names([TOLD])
    yield TOLD
    timeline.forget_names()


def _leaks(text: str) -> list[str]:
    return [line for line in text.splitlines() if "zoe" in line.lower() or "quill" in line.lower()]


def test_the_timeline_takes_a_told_name_out_however_its_words_are_joined(told):
    for joined in JOINED:
        assert timeline.scrub_text(f"the keyboard left {joined} when a render ran") == "the keyboard left [name] when a render ran", joined
    written = timeline.scrub({"kind": "tablet_focus", "source": "tablet", "name": "zoe_quill", "cause": "zoe.quill",
                              "cards": [{"type": "zoe_quill", "actions": [{"id": "zoe-quill"}]}]})
    assert not _leaks(json.dumps(written)), written
    # Identifiers that are no told name stay as they are, an underscore and all.
    for kept in ("email_thread", "order.add_note", "composer-subject", "br_left", "turn_followups01"):
        assert timeline.scrub_text(kept) == kept


def _named_page_tape(tmp_path: Path) -> Path:
    from tests.test_analyser import Tape, _finished, _turn

    tape = Tape("ts-20261001-091500-names")
    t = _turn(tape, "turn_names", said="show me the orders", input_="text")
    tape.add("tablet_focus", source="tablet", turn_id=t, state="lost", name="zoe_quill", cause="zoe.quill")
    tape.add("tablet_focus", source="tablet", turn_id=t, state="blur", name="Zoe Quill", cause="zoe:quill")
    tape.add("tablet_hold", source="tablet", turn_id=t, phase="multitouch", fingers=2, target="zoe-quill")
    tape.add("tablet_collision", source="tablet", turn_id=t, a="zoe/quill", b="ask_bar", overlap=12)
    tape.add("tablet_notify", source="tablet", turn_id=t, name="zoe#quill")
    tape.add("tablet_rail_tap", source="tablet", turn_id=t, state="disabled", action="Zoe_Quill")
    tape.add("tablet_render", source="tablet", turn_id=t, screen="context",
             cards=[{"type": "zoe_quill", "actions": [{"id": "zoe.quill", "enabled": True}, {"id": "order.add_note", "enabled": True}]},
                    {"type": "order", "tabs": ["zoe-quill", "lines"]}],
             t=int(tape.now * 1000))
    # And identifiers that are no told name, which are kept.
    tape.add("tablet_focus", source="tablet", turn_id=t, state="lost", name="composer-subject", cause="render")
    _finished(tape, t, answer="Three orders came in.", question="show me the orders")
    t = _turn(tape, "turn_defect", said="log that the back button is broken", input_="text")
    tape.add("tablet_render", source="tablet", turn_id=t, screen="context", cards=[{"type": "zoe_quill"}], t=int(tape.now * 1000))
    _finished(tape, t, answer="Noted.", question="log that the back button is broken")
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tape.write(tmp_path)


def test_a_told_name_a_page_sends_as_an_identifier_leaves_no_finding(told, tmp_path):
    rec = reconstruct(read_events(_named_page_tape(tmp_path)))
    reading = visible.apply(rec)
    assert {"FOCUS_LOST", "COLLISION", "EMPTY_NOTIFICATION", "FAKE_CONTROL"} <= {f.name for f in reading.findings}
    carried = json.dumps([f.as_dict() for f in reading.findings]) + json.dumps([row.__dict__ for row in reading.rows]) \
        + json.dumps([t.signals for t in rec.turns]) + json.dumps(reading.ignored_feedback)
    assert not _leaks(carried), _leaks(carried)[:5]
    assert "[withheld]" in carried
    signals = [f.signal for f in reading.findings if f.name == "FOCUS_LOST"]
    assert "the keyboard left composer-subject when render" in signals, "an identifier that is no told name is kept"
    assert "the keyboard left [withheld] when [withheld]" in signals, signals
    for joined in JOINED:
        assert visible.as_identifier(joined) == visible.WITHHELD_MARK, joined
    assert [visible.as_identifier(kept) for kept in ("order.add_note", "ask_bar", "1938")] == ["order.add_note", "ask_bar", "1938"]
    assert visible.as_path("/media/zoe_quill/240") == visible.WITHHELD_MARK


def test_a_told_name_a_page_sends_as_an_identifier_is_not_in_the_report(told, tmp_path):
    rec, markdown = build_report(_named_page_tape(tmp_path))
    assert not _leaks(markdown), _leaks(markdown)[:5]
    assert "[withheld]" in markdown
    assert "order.add_note" in markdown and "'lines'" in markdown, "identifiers that are no told name are printed"
    assert [row["screen"] for row in rec.experience.ignored_feedback] == [["[withheld]"]]


def test_a_told_name_a_page_sends_as_a_field_name_is_not_in_the_reports_precision_table(told, tmp_path):
    """The report's "Precision input needed" table (report._precision_input, from touch.precision_evidence)
    names the composer field and the keyboard's field and reason a page sent: a told name joined
    as an identifier is withheld there as the plain name is, and an identifier is still named."""
    from tests.test_analyser import Tape, _finished, _turn

    tape = Tape("ts-20261001-093000-precision")
    t = _turn(tape, "turn_precision", said="write to the supplier", input_="text")
    tape.add("tablet_compose_field", source="tablet", turn_id=t, name="zoe_quill", chars=12)
    tape.add("tablet_keyboard", source="tablet", turn_id=t, state="shown", name="zoe.quill", reason="zoe-quill")
    tape.add("tablet_compose_field", source="tablet", turn_id=t, name="Zoe Quill", chars=3)
    tape.add("tablet_compose_field", source="tablet", turn_id=t, name="composer-subject", chars=9)
    _finished(tape, t, answer="The composer is open.", question="write to the supplier")
    tmp_path.mkdir(parents=True, exist_ok=True)
    _rec, markdown = build_report(tape.write(tmp_path))
    assert not _leaks(markdown), _leaks(markdown)[:5]
    rows = [line for line in markdown.splitlines() if line.startswith("| turn_precision |")]
    assert "| turn_precision | a value was typed into the composer ([withheld]) | 12 character(s) |" in rows, rows
    assert "| turn_precision | the keyboard was opened on [withheld] | [withheld] |" in rows, rows
    assert "| turn_precision | a value was typed into the composer ([withheld]) | 3 character(s) |" in rows, rows
    assert "| turn_precision | a value was typed into the composer (composer-subject) | 9 character(s) |" in rows, rows


# ------------------------------------------------------------------ T1-04: a refused caller's health


LIMITED = {"status": "degraded", "build": "b-followups", "uptime_s": 12.5, "limited": True,
           "checks": {"proxy_identity": {"ok": True, "detail": "served without proxy headers"}, "housekeeping": {"ok": False}}}


def _with_housekeeping(value: Any, *, drop: bool = False, extra: dict | None = None) -> dict:
    body = json.loads(json.dumps(LIMITED))
    if drop:
        del body["checks"]["housekeeping"]
    else:
        body["checks"]["housekeeping"] = value
    body["checks"].update(extra or {})
    return body


def test_the_limited_health_helper_requires_housekeeping_as_a_verdict_and_nothing_else():
    _limited_to_liveness(_with_housekeeping({"ok": False}))          # failing: a verdict all the same
    _limited_to_liveness(_with_housekeeping({"ok": True}))
    for broken in (_with_housekeeping(None, drop=True), _with_housekeeping({}), _with_housekeeping({"ok": "yes"}),
                   _with_housekeeping({"ok": None}), _with_housekeeping({"ok": 1}), _with_housekeeping(True),
                   _with_housekeeping({"ok": False, "detail": "a pass met a problem"}),
                   _with_housekeeping({"ok": True}, extra={"shopify": {"ok": True}})):
        with pytest.raises(AssertionError):
            _limited_to_liveness(broken)


def test_the_route_gives_a_refused_caller_a_failing_housekeeping_check_as_a_verdict_only():
    from app.routes import health

    whole = {"status": "degraded", "build": "b-followups", "uptime_s": 3.0, "sessions": 4,
             "checks": {"proxy_identity": {"ok": True, "detail": "served without proxy headers"},
                        "housekeeping": {"ok": False, "detail": SECRET_DETAIL}, "shopify": {"ok": False, "detail": SECRET_DETAIL}}}
    shown = health._liveness(whole)
    _limited_to_liveness(shown)
    assert shown["checks"]["housekeeping"] == {"ok": False}


@pytest.fixture()
def no_pad_after():
    from app.observability import pad as pad_module

    pad_module.reset()
    yield
    pad_module.reset()


async def test_a_refused_caller_reads_a_failing_housekeeping_pass_as_a_verdict_only(client, no_pad_after):  # noqa: F811
    from app.main import app

    await _production_with_a_failing_check(client)
    app.state.housekeeper.last_problem = SECRET_DETAIL
    body = (await client.get("/health")).json()
    _limited_to_liveness(body)
    assert body["checks"]["housekeeping"] == {"ok": False} and body["status"] == "degraded"
