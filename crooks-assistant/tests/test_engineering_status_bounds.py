"""engineering_status stays small however many requests the loop has recorded (9 Oct 2026).

On 9 Oct the owner said "yes" to CLIVE filing a build and it failed: engineering_status listed every
request the loop had ever recorded (74, 56 KB as the model reads it, 60 KB with the areas), the claude
CLI handed the model a note that the result was too large in its place, and without the inbox id
nothing could be filed. These hold the answer to MAX_ANSWER_BYTES whatever the loop publishes, with
invented statuses only (the repository is public: no real request, title or blocker is copied here):

- 500 requests with every text at its longest: the answer stays under the ceiling, carries the inbox
  id and the base, and names every request waiting on the owner and every blocked one, up to the bound;
- today's shape (74 requests, texts as long as today's): the answer the parent built was over the
  size at which the CLI starts counting, and this one passes it uncounted, and filing goes through;
- every character four bytes long: still under the ceiling, the inbox id still on it;
- `request_ids` returns those requests in full; the areas are bounded; the inbox id comes first.

Why 16,000 bytes is the ceiling is written beside MAX_ANSWER_BYTES in app/tools/engineering_tools.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.session.models import Session
from app.tools import engineering_tools
from app.tools.dispatch import dispatch
from tests.test_engineering_bridge import (  # noqa: F401 - fixtures
    BASE_SHA,
    HEAD,
    SUBMIT_TOOL,
    ask,
    bound,
    fake,
    inbox,
)

STATUS_TOOL = "engineering_status"
# The claude CLI passes an MCP result on uncounted while a quarter of its characters is under half of
# MAX_MCP_OUTPUT_TOKENS (25,000 by default): 50,000 characters (app/tools/engineering_tools.py).
CLI_UNCOUNTED_CHARS = 50_000

WORDS = ("the review asked for a test of the new branch \"quoted\" and a path C:\\tmp\\x — café build "
         "stopped at the repair limit after GitHub's acceptance run failed on tests/test_invented.py ")


def _text(chars: int, words: str = WORDS) -> str:
    return (words * (chars // len(words) + 1))[:chars]


def _rid(n: int) -> str:
    return f"invented-request-{n:03d}-" + "x" * (80 - len(f"invented-request-{n:03d}-"))


def _at(n: int) -> str:
    """The n-th request's time: a later n is a later request, ten minutes apart."""
    return (datetime(2026, 9, 20, tzinfo=UTC) + timedelta(minutes=10 * n)).isoformat()


def _maximal(n: int, stage: str) -> dict:
    """One request with every field the loop publishes at its longest."""
    long = _text(8 * engineering_tools.MAX_BLOCKER_CHARS)
    item = {
        "request_id": _rid(n), "outcome": "accepted", "stage": stage, "recorded_at": _at(n),
        "blocker": long if stage in ("BLOCKED", "OWNER_GATE") else None, "stage_reason": long, "reason": long,
        "owner_gate": stage == "OWNER_GATE", "candidate_sha": f"{n:040x}"[-40:],
        "build_history": {"attempts": 9, "max_repair_rounds": 5, "review_changes_requested": 7,
                          "revisions": [{"revision": r, "kind": "repair", "attempts": 3, "transient": 2, "refused": 1}
                                        for r in range(1, 30)]},
        # Each attempt is counted, never quoted: its reason is kept short so the fake stays quick.
        "attempts": [{"attempt_id": f"a{a}", "revision": a % 5, "outcome": "refused", "reason": _text(200)}
                     for a in range(60)],
        "repairs": {"review": 2, "ci": 3, "max": 5},
        "generated": [f"crooks-assistant/app/invented/generated_module_{g:03d}.py" for g in range(60)],
        "review": {"verdicts": [{"verdict": _text(400)} for _ in range(10)]},
        "github_acceptance": {"state": "red"},
    }
    if stage == "COMPLETE":
        item["landing"] = {"state": "refused", "reason": long, "at": _at(n)}
    return item


def _status(requests: list[dict]) -> dict:
    long = _text(5000)
    return {"generated_at": "2026-10-09T01:12:13+00:00", "schema_version": "clive.remote_engineering_status.v1",
            "adapter": {"intake_error": long, "trunk_fetch_error": long}, "requests": requests, "waiting_requests": []}


@pytest.fixture()
def loop(fake, bound):  # noqa: F811 - the bridge suite's fake GitHub, bound to the tools
    return fake


async def _read(session_id: str, **args) -> tuple[str, dict]:
    text = await dispatch(STATUS_TOOL, args, session=Session(session_id=session_id), timeout_s=5)
    return text, json.loads(text)


# ------------------------------------------------------------------ 500 requests, every text at its longest


@pytest.mark.usefixtures("owner_asking")
@pytest.mark.parametrize("areas", [False, True])
async def test_500_maximal_requests_stay_under_the_ceiling_and_name_every_owner_and_blocked_one(loop, areas):
    owner, open_ = [480, 485, 490, 495], [482, 486, 492, 498]
    blocked = [n for n in range(481, 500) if n not in owner and n not in open_]
    assert len(blocked) == 12
    stages = {**{n: "OWNER_GATE" for n in owner}, **{n: "BLOCKED" for n in blocked}, **{n: "RUNNING" for n in open_}}
    loop.status = _status([_maximal(n, stages.get(n, "COMPLETE")) for n in range(500)])

    text, out = await _read("eng-500", areas=areas)

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES, len(text.encode("utf-8"))
    assert out["inbox"]["id"] == HEAD and out["base"] == {"ref": "clive/trunk", "sha": BASE_SHA}
    named = [row["request_id"] for row in out["requests"]]
    assert len(named) == engineering_tools.MAX_LISTED
    assert {_rid(n) for n in owner + blocked + open_} == set(named), "every one waiting on the owner, blocked or open"
    assert out["summary"].startswith("500 engineering requests: ")
    assert out["not_listed"].startswith("480 more requests not listed")
    assert "request_ids" in out["not_listed"] and "request_ids" in out["detail"]
    assert "a blocked build needs the Director" in out["blocked_means"]
    if areas:
        assert out["areas"] and "tests" in out


@pytest.mark.usefixtures("owner_asking")
async def test_more_blocked_than_the_bound_names_the_owners_first_then_the_newest(loop):
    owner = [3, 100, 250]                      # old ones: waiting on the owner comes first whatever its age
    blocked = list(range(300, 500, 3))         # 67 blocked, more than the bound
    stages = {**{n: "OWNER_GATE" for n in owner}, **{n: "BLOCKED" for n in blocked}}
    loop.status = _status([_maximal(n, stages.get(n, "COMPLETE")) for n in range(500)])

    text, out = await _read("eng-crowded", areas=True)

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES
    assert out["inbox"]["id"] == HEAD
    # After the owner's: the newest of the blocked and of the MAX_RECENT newest requests, done or not.
    recent = range(500 - engineering_tools.MAX_RECENT, 500)
    newest = sorted(set(blocked) | set(recent), reverse=True)[: engineering_tools.MAX_LISTED - len(owner)]
    named = [row["request_id"] for row in out["requests"]]
    assert set(named) == {_rid(n) for n in owner + newest}
    assert named == [_rid(n) for n in sorted(owner + newest, reverse=True)], "said newest first"


@pytest.mark.usefixtures("owner_asking")
async def test_every_character_four_bytes_long_still_fits_and_keeps_the_inbox_id(loop, monkeypatch):
    wide = "\U0001f9f5 " * 6000
    requests = [_maximal(n, "BLOCKED") for n in range(500)]
    for item in requests:
        item["request_id"] = item["request_id"][:20] + "\U0001f9f5" * 15
        item["blocker"] = item["stage_reason"] = wide
    loop.status = _status(requests)
    loop.status["adapter"] = {"intake_error": wide, "trunk_fetch_error": wide}

    text, out = await _read("eng-wide", areas=True)

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES
    assert out["inbox"]["id"] == HEAD and out["base"]["sha"] == BASE_SHA
    assert out["requests"], "the bound leaves room for requests, fewer of them"
    assert out["not_listed"].startswith(f"{500 - len(out['requests'])} more requests not listed")


# ------------------------------------------------------------------ today's shape


def _todays_shape() -> dict:
    """An invented status shaped like the live one on 9 Oct: 74 requests, 44 blocked, 26 done,
    2 waiting on the owner and 2 refused at intake, their texts as long as the live ones."""
    requests = []
    for n in range(74):
        stage = "BLOCKED" if n < 44 else "COMPLETE" if n < 70 else "OWNER_GATE" if n < 72 else None
        blocker = _text(300 + (n * 97) % 691)
        item = {"request_id": f"invented-build-{n:02d}", "outcome": "refused" if stage is None else "accepted",
                "stage": stage, "recorded_at": _at(n * 6), "owner_gate": stage == "OWNER_GATE",
                "blocker": blocker if stage in ("BLOCKED", "OWNER_GATE") else None,
                "stage_reason": f"blocked: {blocker}" if stage == "BLOCKED" else None,
                "reason": _text(200) if stage is None else None,
                "candidate_sha": f"{n + 1:040x}" if stage == "COMPLETE" else None,
                "build_history": {"attempts": 1 + n % 4, "max_repair_rounds": 3, "review_changes_requested": n % 3,
                                  "revisions": [{"revision": r + 1, "kind": "repair" if r else "build",
                                                 "attempts": 1 + (n + r) % 2, "transient": (n + r) % 2, "refused": 0}
                                                for r in range(1 + n % 4)]},
                "attempts": [], "repairs": {"review": n % 3, "ci": n % 2, "max": 3}, "generated": [],
                "landing": ({"state": "landed", "sha": f"{n + 7:040x}", "at": _at(n * 6), "reason": None, "by": "loop"}
                            if stage == "COMPLETE" and n % 3 == 0 else None)}
        requests.append(item)
    return _status(requests) | {"adapter": {"intake_error": None}}


@pytest.mark.usefixtures("owner_asking")
async def test_todays_shape_passes_the_cli_uncounted_where_the_parents_answer_did_not(loop):
    loop.status = _todays_shape()
    rows = [engineering_tools.progress(item) for item in engineering_tools._items(loop.status)]
    # The parent's answer listed every request whole: the same status, said that way, is past the size
    # at which the CLI counts it (and on 9 Oct, past its limit; the live one was 56 KB).
    parent = {"connected": True, "summary": "x" * 80, "requests": rows, "inbox": {"id": HEAD}, "areas": []}
    assert len(json.dumps(parent, ensure_ascii=False)) > CLI_UNCOUNTED_CHARS

    session = Session(session_id="eng-today")
    text = await dispatch(STATUS_TOOL, {"areas": True}, session=session, timeout_s=5)
    out = json.loads(text)

    assert len(text) <= CLI_UNCOUNTED_CHARS and len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES
    assert out["inbox"]["id"] == HEAD and out["areas"]
    assert {"invented-build-70", "invented-build-71"} <= {row["request_id"] for row in out["requests"]}
    assert out["summary"] == "74 engineering requests: 46 blocked, 26 done, 2 needs the owner."
    # And the yes he gave goes through: the id this read issued is the one the filing takes.
    filed = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask()}, session=session, timeout_s=5)
    assert filed.startswith("PROPOSED ("), filed


# ------------------------------------------------------------------ named requests, areas, order


@pytest.mark.usefixtures("owner_asking")
async def test_request_ids_return_those_requests_in_full(loop):
    loop.status = _todays_shape()
    listed = await engineering_tools.engineering_status()
    assert "invented-build-01" not in {row["request_id"] for row in listed["requests"]}, "old and blocked: counted only"

    out = await engineering_tools.engineering_status(request_ids=["invented-build-01", "no-such-build", "invented-build-50"])

    assert [row["request_id"] for row in out["requests"]] == ["invented-build-01", "invented-build-50"]
    whole = {row["request_id"]: row for row in (engineering_tools.progress(i) for i in loop.status["requests"])}
    assert out["requests"][0] == whole["invented-build-01"], "the line in full: its history and next step"
    assert "history" in out["requests"][0] and "next_step" in out["requests"][0]
    assert "no-such-build" in out["not_found"] and out["inbox"]["id"] == HEAD
    one = await engineering_tools.engineering_status(request_ids="invented-build-02")
    assert [row["request_id"] for row in one["requests"]] == ["invented-build-02"]
    nothing_named = await engineering_tools.engineering_status(request_ids=[" "])
    assert nothing_named["requests"] == listed["requests"], "nothing usable named: the listing"
    many = await engineering_tools.engineering_status(request_ids=[f"invented-build-{n:02d}" for n in range(9)])
    assert len(many["requests"]) == engineering_tools.MAX_NAMED and many["not_listed"].startswith("4 of the requests")


@pytest.mark.usefixtures("owner_asking")
async def test_named_requests_are_left_out_whole_rather_than_cut(loop):
    loop.status = _status([_maximal(n, "BLOCKED") for n in range(10)])

    text, out = await _read("eng-named", request_ids=[_rid(n) for n in range(5)], areas=True)

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES and out["inbox"]["id"] == HEAD
    whole = {row["request_id"]: row for row in (engineering_tools.progress(i) for i in loop.status["requests"])}
    assert out["requests"] and all(row == whole[row["request_id"]] for row in out["requests"])
    shown = len(out["requests"])
    if shown < 5:
        assert out["not_listed"].startswith(f"{5 - shown} of the requests named are not shown")


async def test_the_areas_are_bounded_and_the_real_ones_fit_whole(monkeypatch):
    real = engineering_tools.buildable_areas()
    assert engineering_tools._areas(real) == {"areas": real}
    assert len(json.dumps(real).encode("utf-8")) <= engineering_tools.MAX_AREAS_BYTES

    many = [f"crooks-assistant/app/invented/area_{n:03d}/with/a/long/path/to/it" for n in range(400)]
    out = engineering_tools._areas(many)
    assert len(json.dumps(out["areas"]).encode("utf-8")) <= engineering_tools.MAX_AREAS_BYTES
    assert out["areas"] == many[: len(out["areas"])]
    assert out["areas_not_listed"].startswith(f"{400 - len(out['areas'])} more areas are not listed")


@pytest.mark.usefixtures("owner_asking")
async def test_the_inbox_id_and_base_come_before_any_request(loop):
    loop.status = _todays_shape()
    text, _out = await _read("eng-order")
    assert text.index(HEAD) < text.index('"requests"') and text.index(BASE_SHA) < text.index('"requests"')


@pytest.mark.usefixtures("owner_asking")
async def test_a_few_requests_are_still_said_whole(loop):
    loop.status = _todays_shape()
    loop.status["requests"] = loop.status["requests"][40:48]
    out = await engineering_tools.engineering_status()
    assert len(out["requests"]) == 8 and "not_listed" not in out and "detail" not in out
    assert all("history" in row for row in out["requests"])


# ------------------------------------------------------------------ text the loop cannot have meant


@pytest.mark.usefixtures("owner_asking")
async def test_a_lone_surrogate_in_the_status_never_makes_the_read_fail(loop):
    """A log cut through an emoji leaves half of it: the read is said and filing goes on (review N1)."""
    loop.status = _status([{"request_id": "invented-half-emoji", "outcome": "accepted", "stage": "BLOCKED",
                            "recorded_at": _at(1), "blocker": "ci log \udcff bytes"}])
    session = Session(session_id="eng-surrogate")

    text = await dispatch(STATUS_TOOL, {"areas": True}, session=session, timeout_s=5)

    assert not text.startswith("ERROR"), text
    out = json.loads(text)
    assert out["inbox"]["id"] == HEAD and out["requests"][0]["request_id"] == "invented-half-emoji"
    filed = await dispatch(SUBMIT_TOOL, {"inbox_id": HEAD, **ask()}, session=session, timeout_s=5)
    assert filed.startswith("PROPOSED ("), filed
    assert engineering_tools._areas(["crooks-assistant/app/half\udcff"])["areas"] == ["crooks-assistant/app/half\udcff"]


# ------------------------------------------------------------------ what a listing leaves out


def _plain(n: int, stage: str) -> dict:
    return {"request_id": f"invented-left-{n:03d}", "outcome": "accepted", "stage": stage, "recorded_at": _at(n),
            "owner_gate": stage == "OWNER_GATE", "blocker": "an invented blocker" if stage != "COMPLETE" else None}


@pytest.mark.usefixtures("owner_asking")
async def test_what_is_left_out_is_said_by_state_and_each_one_not_done_can_be_named(loop):
    """The review's shape (N2): 30 old requests waiting on the owner, 10 newer blocked, 80 done. Twenty of
    the owner's are named; the rest were said to be "done, or older", which the 10 blocked were not, and
    none of them could be named in request_ids because the model was never given an id."""
    loop.status = _status([_plain(n, "OWNER_GATE" if n < 30 else "BLOCKED" if n < 40 else "COMPLETE")
                           for n in range(120)])

    text, out = await _read("eng-left-out")

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES and out["inbox"]["id"] == HEAD
    assert [row["request_id"] for row in out["requests"]] == [f"invented-left-{n:03d}" for n in range(29, 9, -1)]
    assert out["not_listed"] == ("100 more requests not listed: 10 needs the owner, 10 blocked, 80 done. "
                                 "not_listed_ids names each one not done; name any in request_ids to see it in full.")
    left = [f"invented-left-{n:03d}" for n in [*range(9, -1, -1), *range(39, 29, -1)]]
    assert out["not_listed_ids"] == left, "the owner's first, then the newest"
    for at in range(0, len(left), engineering_tools.MAX_NAMED):
        asked = left[at:at + engineering_tools.MAX_NAMED]
        named = await engineering_tools.engineering_status(request_ids=asked)
        assert [row["request_id"] for row in named["requests"]] == asked


@pytest.mark.usefixtures("owner_asking")
async def test_the_ids_left_out_are_bounded_and_say_how_many_are_counted_only(loop):
    loop.status = _status([_maximal(n, "BLOCKED" if n % 2 else "COMPLETE") for n in range(500)])

    text, out = await _read("eng-left-many", areas=True)

    assert len(text.encode("utf-8")) <= engineering_tools.MAX_ANSWER_BYTES and out["inbox"]["id"] == HEAD
    ids = out["not_listed_ids"]
    assert len(json.dumps(ids, ensure_ascii=False).encode("utf-8")) <= engineering_tools.MAX_IDS_BYTES
    blocked_left = 250 - sum(1 for row in out["requests"] if row["progress"] == "blocked")
    assert " blocked, " in out["not_listed"] and f"not_listed_ids names {len(ids)} of the {blocked_left} not done" in \
        out["not_listed"]
    assert ids == [_rid(n) for n in range(499, -1, -1) if n % 2 and _rid(n) not in
                   {row["request_id"] for row in out["requests"]}][: len(ids)], "the newest first"
