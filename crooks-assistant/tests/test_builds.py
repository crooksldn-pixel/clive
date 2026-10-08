"""The Builds screen's server side (app/builds/): every build in plain words, and George's decisions.

What is proved, on the worker-01 loop's own status as it stood on 2 Oct 2026 (tests/builds_fixture.py):

- the translators: every stopped request in the real status is said plainly, with who it waits on and
  no SHA or branch name; a reviewer's finding (two real ones, from the round-12 deploy review) reads
  as What's wrong, Why it matters and What fixes it, from its own fields; the loop's GitHub run ids
  survive the customer-shape redaction, and a planted secret does not;
- the board: 65 requests are 38 builds, grouped by the loop's retry convention, placed where George
  reads them (two need him, two stopped, the rest live in the commit production runs), newest first,
  with no SHA, branch or request id on any build's face; the running commit unknown, or the trunk
  unreadable, is said rather than guessed; CLIVE's own gap and objective records say why it matters;
- the decisions: the question, its answers and the recommendation, bound to the stop as published;
  every answer says only what is true today (nothing acts on an answer by itself: the independent
  review of fe36872f, B-1), and an answer that asks for something to be done keeps the build in
  Needs you, answered, until a new try is filed; an answer recorded as a valid owner judgment the
  kernel's own reader accepts, one ASCII line whatever the loop's data holds, 0600 whatever the file
  was; a change of mind a correction that keeps the first answer byte for byte, a ledger that was
  tampered with never appended to, and the read-back with its chain head;
- the routes: the owner's alone; a stale question records nothing; engineering_status carries the
  answer on the request it is about, and whether a new try has acted on it; GitHub is read once a
  minute, each title once, through one client per board; a request id outside the inbox's rule costs
  its own title and nothing else.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.actions.judgment_chain import chain_anchor, chain_ledger
from app.builds import board as board_module
from app.builds import decisions, plain, read
from app.objectives import store as store_module
from app.orchestrator.lifecycle import load_judgment_ledger
from app.tools import engineering_tools
from tests import builds_fixture
from tests.fake_credentials import github_token

HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
BRANCH = re.compile(r"\b(?:clive|claude)/")
OWNER = {"Tailscale-User-Login": "team@crooksldn.com", "X-Forwarded-For": "100.64.0.9"}

# The two findings of the round-12 deploy review's observability part (docs/review/
# deploy-review-round-12-findings.md on claude/deploy-review-round-12-findings), as the reviewer wrote them.
O1_01 = {
    "finding_id": "O1-01", "material": True,
    "finding": ("BLOCKS — This can lose already-written production timeline data if two writers append to the same "
                "session, and I cannot rule out that condition from the files supplied. Writers hold shared locks, so if one "
                "has a partial write, another appends a complete event, and the first then calls `_take_back`, truncation from "
                "the file’s current end removes the second writer’s bytes even though it counted that event as "
                "written. CANNOT TELL whether production session isolation prevents this interleaving without "
                "`crooks-assistant/app/observability/session.py` and `crooks-assistant/app/main.py`."),
    "evidence_ref": "crooks-assistant/app/observability/timeline.py:234-244, 470-493, 558-573",
    "required_repair": ("Supply the named session and startup files to establish whether writers can share a timeline path. "
                        "If they can, serialize append and partial-write recovery exclusively per file, and test an "
                        "interleaved short write so recovery cannot truncate another writer’s event."),
}
O1_02 = {
    "finding_id": "O1-02", "material": True,
    "finding": ("FOLLOW-UP — This misdiagnoses a screen event but does not itself permit exploitation, lose data, or "
                "leak data on the configured host. `_whole` converts malformed page counts to zero, so a composer field "
                "reporting a nonnumeric `chars` value after a valid positive count is classified as having lost its "
                "contents; malformed scroll depths can likewise be treated as a return to the top."),
    "evidence_ref": "crooks-assistant/app/observability/visible.py:1151-1170, 1173-1225",
    "required_repair": ("Represent malformed counts as unknown, and emit `FOCUS_LOST` only when both the prior and current "
                        "measurements needed for that inference are valid; add malformed-field and malformed-scroll cases."),
}


def _items() -> list[dict]:
    return engineering_tools._items(builds_fixture.status())


def _by_id(rid: str) -> dict:
    return next(i for i in _items() if i["request_id"] == rid)


def _requests() -> dict[str, dict]:
    out = {}
    for rid, text in builds_fixture.request_files().items():
        record = json.loads(text)
        out[rid] = {"title": record["title"], "asked": record["requested_outcome"], "base_sha": record["base_sha"],
                    "target_branch": record["target_branch"]}
    return out


def _commits() -> dict[str, dict]:
    return builds_fixture.git()["commits"]


def _board(**over) -> dict:
    args = {"requests": _requests(), "commits": _commits(), "running_known": True, "links": {}, "judgments": {},
            "as_of": builds_fixture.status()["generated_at"]}
    args.update(over)
    return board_module.board(_items(), **args)


def _all(payload: dict) -> list[dict]:
    return [b for g in payload["groups"] for b in g["builds"]]


def _face(build: dict) -> str:
    """Everything a build says outside its technical details."""
    parts = [build["title"], build["words"], build["serves"], build["matters"], build.get("note") or ""]
    if build["why"]:
        parts.append(build["why"]["says"])
    if build["decision"]:
        q = build["decision"]
        parts += [q["question"], q["context"], q["because"]] + [a["label"] + " " + a["then"] for a in q["answers"]]
    return "\n".join(parts)


@pytest.fixture()
def objectives(tmp_path, monkeypatch):
    fresh = store_module.ObjectiveStore(tmp_path / "objectives")
    monkeypatch.setattr(store_module, "_STORE", fresh)
    monkeypatch.setattr(decisions, "_LEDGER", None)
    return fresh


@pytest.fixture()
def loop(monkeypatch, objectives):
    fake = builds_fixture.FakeLoop()
    builds_fixture.bind(monkeypatch, fake)
    return fake


def _client() -> TestClient:
    from app.routes import objectives as objectives_route

    app = FastAPI()
    app.include_router(objectives_route.router)
    settings = SimpleNamespace(writes_local_owner=False, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=("team@crooksldn.com",), settings=settings)
    return TestClient(app)


# ------------------------------------------------------------------ the translators


def test_every_stopped_request_in_the_real_status_is_said_plainly_with_who_it_waits_on():
    expected = {
        "status-publishes-findings": ("review_limit", plain.YOU), "skill-read-runtime-tool-4": ("review_limit", plain.YOU),
        "skill-read-runtime-tool": ("owner_gate", plain.YOU), "followups-voice-and-records": ("owner_gate", plain.YOU),
        "expose-draft-order-s-payment-link-3": ("github_red", plain.DIRECTOR),
        "skill-read-runtime-tool-3": ("github_red", plain.DIRECTOR),
        "mark-packed-counts-as-packed": ("checks_failed", plain.DIRECTOR),
        "owner-facing-host-wording-4": ("build_server", plain.DIRECTOR),
        "mark-packed-counts-as-packed-2": ("builder_stopped", plain.DIRECTOR),
        "digester-curated-skill-list": ("refused", plain.DIRECTOR),
    }
    for rid, (kind, who) in expected.items():
        said = plain.why_stopped(_by_id(rid))
        assert (said["kind"], said["who"]) == (kind, who), rid
    stopped = [i for i in _items() if i.get("stage") in ("BLOCKED", "OWNER_GATE") or i.get("outcome") == "refused"]
    assert len(stopped) == 44
    for item in stopped:
        said = plain.why_stopped(item)
        assert said["says"] and said["says"].endswith("."), item["request_id"]
        assert not HEX.search(said["says"]) and not BRANCH.search(said["says"]), (item["request_id"], said["says"])
        assert said["kind"] != "other", item["request_id"]
        assert said["loop_words"], item["request_id"]


def test_the_loops_own_sentences_read_as_george_would_say_them():
    assert plain.why_stopped(_by_id("status-publishes-findings"))["says"] == (
        "The reviewer still found one problem (F-01) after all three repair rounds, so the loop stopped and left the "
        "next step to you.")
    assert plain.why_stopped(_by_id("work-list-review-fixes"))["findings"] == ["F-01"]
    red = plain.why_stopped(_by_id("skill-read-runtime-tool-3"))
    assert red["test"] == "a planner exception never breaks a turn"
    assert "The failing test: “a planner exception never breaks a turn”." in red["says"]
    assert plain.why_stopped(_by_id("mark-packed-counts-as-packed"))["says"] == (
        "CLIVE's own regression check failed on the builder's work twice, so the loop stopped trying.")
    assert "before any change" in plain.why_stopped(_by_id("mark-packed-counts-as-packed-2"))["says"]
    assert plain.why_stopped(_by_id("clive-voice-uses-the-clock"))["says"] == (
        "The builder stopped: it couldn't see why GitHub's tests failed.")
    gate = plain.why_stopped(_by_id("followups-voice-and-records"))
    assert "conflicts with an existing test" in gate["says"]


def test_a_test_is_said_as_its_name_reads_and_a_path_as_its_file():
    assert plain.test_name("tests/web/mic.test.js::nope") == ""
    assert plain.test_name("tests/test_families.py::test_the_families_that_already_worked_never_withhold_a_tool_from_the_model") == (
        "the families that already worked never withhold a tool from the model")
    said = plain.face("`tests/test_visible_privacy.py::test_a_focus_rule_given_counts_that_are_not_numbers_still_reads_the_rest` "
                      "fails at 2738f2543a9650b469c6dc637a43fb68f5c6acb9 in `crooks-assistant/app/tools/dispatch.py` on clive/trunk")
    assert "“a focus rule given counts that are not numbers still reads the rest”" in said
    assert "dispatch.py" in said and "crooks-assistant/" not in said
    assert not HEX.search(said) and "the trunk" in said


def test_a_reviewers_finding_reads_as_whats_wrong_why_it_matters_and_what_fixes_it():
    one = plain.finding(O1_01)
    assert one["id"] == "O1-01" and one["material"] is True
    # The label's reason is why it matters; the defect follows it; the reviewer's doubt stays technical.
    assert one["matters"].startswith("This can lose already-written production timeline data")
    assert one["wrong"].startswith("Writers hold shared locks") and "_take_back" in one["wrong"] and "`" not in one["wrong"]
    assert one["where"] == "Found in timeline.py, line 234."
    assert one["fix"] == "Supply the named session and startup files to establish whether writers can share a timeline path."
    assert "CANNOT TELL" not in one["wrong"] + one["matters"]
    assert one["technical"]["finding"].startswith("BLOCKS") and "CANNOT TELL" in one["technical"]["finding"]
    assert one["technical"]["repair"].endswith("another writer’s event.")
    two = plain.finding(O1_02)
    assert two["matters"].startswith("This misdiagnoses a screen event but does not itself permit exploitation")
    assert two["wrong"].startswith("_whole converts malformed page counts to zero")
    assert two["fix"].startswith("Represent malformed counts as unknown")
    # An unlabelled finding: its first sentence is what's wrong; with no harm said, the flag says why.
    plain_one = plain.finding({"finding_id": "F-01", "material": False, "finding": "The header comment names the old file.",
                               "evidence_ref": "Packet section DIFF", "required_repair": "Name the new file."})
    assert plain_one["wrong"] == "The header comment names the old file."
    assert plain_one["matters"] == "The reviewer noted it, but it doesn't stop the build."
    assert plain_one["where"] == "Found in what the reviewer was sent to review."
    assert plain.finding({"id": "F-02"})["wrong"] == "The reviewer gave no wording for it."


def test_findings_are_read_only_when_the_status_publishes_them():
    item = _by_id("status-publishes-findings")
    assert plain.findings_of(item) is None, "today's loop never publishes the findings' text"
    published = {**item, "findings": [O1_01, {"id": "F-02", "severity": "minor", "text": "One line of text."}]}
    found = plain.findings_of(published)
    assert [f["id"] for f in found] == ["O1-01", "F-02"]
    assert found[1]["matters"] == "The reviewer rated it minor."


def test_the_loops_run_ids_survive_redaction_and_a_secret_does_not():
    item = _by_id("let-objectives-marked-complete-or-removed-3")
    said = plain.why_stopped(item)["loop_words"]
    assert "run 36767084329 failure" in said and "[phone]" not in said
    planted = copy.deepcopy(item)
    token = github_token("planted-in-a-blocker")
    planted["blocker"] = f"worker reported blocked: it used {token} and wrote to owner@example.com, see run 36767084329."
    stopped = plain.why_stopped(planted)
    for words in (stopped["says"], stopped["loop_words"]):
        assert token not in words and "owner@example.com" not in words


# ------------------------------------------------------------------ the board


def test_sixty_five_requests_are_thirty_eight_builds_by_the_loops_retry_convention():
    titles = {rid: r["title"] for rid, r in _requests().items()}
    families = board_module.families(_items(), titles)
    assert len(_items()) == 65 and len(families) == 38
    by_key = {board_module.family_key(f[-1]["request_id"]): [i["request_id"] for i in f] for f in families}
    assert by_key["owner-facing-host-wording"] == ["owner-facing-host-wording-4", "owner-facing-host-wording-5",
                                                   "owner-facing-host-wording-6"]
    assert by_key["skill-read-runtime-tool"][-1] == "skill-read-runtime-tool-4"
    assert by_key["engineering-measures"] == ["engineering-measures"], "a different build that shares words is its own"
    # Two differently titled requests that only share a stem stay two builds.
    a, b = (dict(_by_id("trunk-repair-ci"), request_id="phase-2"), dict(_by_id("trunk-repair-ci-2"), request_id="phase-3"))
    assert len(board_module.families([a, b], {"phase-2": "One thing", "phase-3": "Another"})) == 2
    assert len(board_module.families([a, b], {"phase-2": "Same", "phase-3": "Same"})) == 1


def test_the_real_board_puts_each_build_where_george_reads_it():
    payload = _board()
    assert [g["key"] for g in payload["groups"]] == ["needs_you", "stopped", "live"]
    assert payload["counts"] == {"needs_you": 2, "answered": 0, "in_progress": 0, "queued": 0, "stopped": 2, "landed": 0,
                                 "live": 34}
    assert payload["summary"] == "Two builds need you. Nothing is being built right now."
    needs = payload["groups"][0]["builds"]
    assert [b["key"] for b in needs] == ["skill-read-runtime-tool", "status-publishes-findings"], "newest first"
    assert needs[0]["title"].startswith("Read-only skill tools for CLIVE's runtime")
    assert needs[0]["tries"] == 4 and needs[0]["road"] == {"stages": list(board_module.STAGES), "lit": 2, "mark": 2,
                                                          "mark_kind": "you"}
    assert needs[0]["when"] == {"event": "stopped", "at": "2026-10-01T23:29:16+00:00"}
    assert needs[0]["finding_ids"] == ["F-01"] and needs[0]["findings"] is None
    stopped = {b["key"]: b for b in payload["groups"][1]["builds"]}
    assert set(stopped) == {"expose-draft-order-s-payment-link", "let-objectives-marked-complete-or-removed"}
    assert all(b["words"] == "Waiting on the Director" and b["why"]["says"].endswith("The Director decides what happens next.")
               for b in stopped.values())
    live = payload["groups"][2]["builds"]
    assert all(b["road"]["lit"] == 5 for b in live)
    outside = next(b for b in live if b["key"] == "knowledge-digester-adapter-code")
    assert outside["note"] == "The loop stopped it, but its work is on the trunk: it was merged outside the loop."
    landed = next(b for b in live if b["key"] == "mark-packed-counts-as-packed")
    assert landed["when"]["event"] == "landed" and landed["words"] == "Live"
    for build in _all(payload):
        face = _face(build)
        assert build["title"], build["key"]
        assert not HEX.search(face), (build["key"], HEX.search(face).group(0))
        assert not BRANCH.search(face) and build["details"]["request_id"] not in face, build["key"]
    assert needs[0]["details"]["candidate"] == "e7d0e06356b4c8e487a839a9be3d4cfe10dafd5f"
    assert needs[0]["details"]["branch"] == "clive/objective/skill-read-runtime-tool-4"
    assert len(needs[0]["details"]["tries"]) == 4


def test_what_cannot_be_told_is_said_not_guessed():
    unknown_running = _board(running_known=False, commits={s: {"trunk": f["trunk"], "running": None}
                                                           for s, f in _commits().items()})
    assert unknown_running["counts"]["landed"] == 34 and unknown_running["counts"]["live"] == 0
    landed = unknown_running["groups"][-1]["builds"][0]
    assert landed["words"] == "On the trunk" and "can't tell which commit it is running" in landed["note"]
    assert unknown_running["summary"].endswith("34 on the trunk.")
    no_trunk = _board(commits={})
    # Twenty approved builds the trunk could not be checked for; one the loop would not land waits on the Director.
    assert no_trunk["counts"]["in_progress"] == 20 and no_trunk["counts"]["live"] == 0
    approved = no_trunk["groups"][1]["builds"][0]
    assert approved["words"] == "Approved, not on the trunk yet" and approved["note"] == "CLIVE couldn't check the trunk for it just now."
    assert approved["road"]["mark_kind"] == "now"


def test_every_stage_of_the_loop_has_its_place_and_words():
    base = _by_id("status-publishes-findings")
    cases = {
        ("RUNNING", None): ("building", "Being built", "started"),
        ("REJECTED", None): ("building", "Being repaired after review", "started"),
        ("EVIDENCE_READY", None): ("reviewing", "Waiting for GitHub's tests", "review"),
        ("EVIDENCE_READY", "green"): ("reviewing", "Waiting for the reviewer", "review"),
        ("REVIEWING", None): ("reviewing", "Being reviewed", "review"),
        ("READY", None): ("queued", "Waiting for a builder", "filed"),
    }
    for (stage, gate), (state, words, event) in cases.items():
        item = {**base, "stage": stage, "candidate_sha": None, "blocker": None,
                "github_acceptance": {"state": gate} if gate else None}
        build = board_module.build([item], {}, {}, True, {}, {})
        assert (build["state"], build["words"], build["when"]["event"]) == (state, words, event), stage
    waiting = board_module.build([{"request_id": "a-new-build", "outcome": "waiting", "recorded_at": base["recorded_at"]}],
                                 {}, {}, True, {}, {})
    assert waiting["group"] == "queued" and waiting["title"] == ""


def test_why_it_matters_comes_from_clives_own_gap_and_objective_records():
    links = {"status-publishes-findings": {
        "objective": {"id": "obj_1a2b3c4d", "title": "See why builds stop"},
        "gaps": [{"title": "Read the review's findings", "hits": 4, "last_seen": "2026-10-01T09:00:00+00:00"},
                 {"title": "Read a failing check's output", "hits": 1, "last_seen": "2026-09-30T09:00:00+00:00"}]}}
    build = next(b for b in _all(_board(links=links)) if b["key"] == "status-publishes-findings")
    assert build["serves"] == "For your objective “See why builds stop”. It closes a gap: “Read the review's findings”."
    assert build["matters"] == "CLIVE couldn't do this four times, most recently on 1 Oct. It closes one more gap too."
    assert build["matters_known"] is True
    unlinked = next(b for b in _all(_board()) if b["key"] == "status-publishes-findings")
    assert unlinked["matters"].startswith("No gap or objective of CLIVE's is linked to it") and not unlinked["matters_known"]
    assert unlinked["serves"].startswith("When the remote engineering loop blocks an objective")


# ------------------------------------------------------------------ the decisions


def _question(key: str = "status-publishes-findings", payload: dict | None = None) -> dict:
    build = next(b for b in _all(payload or _board()) if b["key"] == key)
    return build["decision"]


def test_a_stop_that_is_georges_puts_one_question_with_answers_and_a_recommendation():
    q = _question("skill-read-runtime-tool")
    assert q["question"] == "The reviewer still has F-01 open after every repair round. What should happen to it?"
    assert [a["key"] for a in q["answers"]] == ["retry", "later", "drop"]
    assert all(a["then"] for a in q["answers"]) and sum(a["recommended"] for a in q["answers"]) == 1
    assert q["recommended"] == "retry" and q["because"] == "GitHub's tests pass on it; only F-01 stands between it and the trunk."
    assert q["proposal_id"].startswith("build:skill-read-runtime-tool-4:r5:review_limit:")
    assert re.fullmatch(r"[0-9a-f]{64}", q["fingerprint"]) and q["attempt_id"] == "skill-read-runtime-tool-4-a5"
    assert _question("status-publishes-findings")["because"].startswith("A fresh try starts from the reviewer's findings")
    assert _question("skill-read-runtime-tool") == q, "the same stop is the same question"
    # The stop published in other words is another proposal.
    item = _by_id("skill-read-runtime-tool-4")
    moved = decisions.card({**item, "blocker": item["blocker"] + " "}, plain.why_stopped(item))
    assert moved["fingerprint"] != q["fingerprint"] and moved["proposal_id"] != q["proposal_id"]
    # The owner gates in the real status (each since filed again): the test the builder must change.
    for rid in ("followups-voice-and-records", "skill-read-runtime-tool"):
        gate = decisions.card(_by_id(rid), plain.why_stopped(_by_id(rid)))
        assert gate["question"] == "To do what you asked, the builder must change an existing test. Do you allow it?"
        assert [a["key"] for a in gate["answers"]] == ["allow", "keep", "later"] and gate["recommended"] == "allow"
    # Every answer says only what is true today: nothing acts on an answer by itself yet.
    for card in (q, decisions.card(_by_id("skill-read-runtime-tool"), plain.why_stopped(_by_id("skill-read-runtime-tool")))):
        said = " ".join(a["then"] for a in card["answers"])
        assert not re.search(r"Director (files|stops|looks)|builder goes on", said), said
        assert [a["key"] for a in card["answers"] if a["acts"]] in (["retry"], ["allow"])
        assert card["waiting"] == ("The build loop can't read answers yet, so nothing happens by itself: it stays in "
                                   "Needs you, answered, until a new try is filed.")
    # A stop that is the Director's puts no question to George.
    assert decisions.card(_by_id("expose-draft-order-s-payment-link-3"),
                          plain.why_stopped(_by_id("expose-draft-order-s-payment-link-3"))) is None


def test_his_answer_is_a_judgment_the_kernels_own_reader_accepts(tmp_path):
    ledger = decisions.ledger(tmp_path / "objectives")
    q = _question()
    record, added = decisions.decide(ledger, q, "retry", principal="team@crooksldn.com", session_id="a1b2c3d4e5f6a7b8")
    assert added and record.decision.value == "APPROVED" and record.reason_code.value == "ACCEPTED_AS_PROPOSED"
    assert (record.task_id, record.task_revision, record.attempt_id) == ("status-publishes-findings", 4, "status-publishes-findings-a4")
    assert record.provenance.source == "clive:builds-screen"
    assert oct(os.stat(ledger.path).st_mode & 0o777) == "0o600"
    loaded, _digest = load_judgment_ledger(ledger.path)
    assert loaded.records == (record,)
    # The same answer again adds nothing.
    again, added_again = decisions.decide(ledger, q, "retry", principal="team@crooksldn.com", session_id="a1b2c3d4e5f6a7b8")
    assert again == record and not added_again
    first_line = ledger.path.read_bytes()
    # A change of mind is a correction; the first answer stays byte for byte.
    later, _ = decisions.decide(ledger, q, "later", principal="team@crooksldn.com", session_id="a1b2c3d4e5f6a7b8")
    assert later.corrects_judgment_id == record.judgment_id and later.decision.value == "DEFERRED"
    assert ledger.path.read_bytes().startswith(first_line)
    assert decisions.chosen(ledger.effective()[q["proposal_id"]])["key"] == "later"
    with pytest.raises(decisions.DecisionError):
        decisions.decide(ledger, q, "allow", principal="team@crooksldn.com", session_id="a1b2c3d4e5f6a7b8")
    back = ledger.read_back()
    anchor = chain_anchor(chain_ledger(load_judgment_ledger(ledger.path)[0]))
    assert (back["entries"], back["head_hash"]) == (2, anchor.head_hash)
    assert [(j["answer"], j["effective"], j["request_id"]) for j in back["judgments"]] == [
        ("retry", False, "status-publishes-findings"), ("later", True, "status-publishes-findings")]


def test_a_ledger_that_was_tampered_with_is_never_appended_to(tmp_path):
    ledger = decisions.ledger(tmp_path / "objectives")
    q = _question()
    decisions.decide(ledger, q, "retry", principal="team@crooksldn.com", session_id="s1")
    tampered = ledger.path.read_text(encoding="utf-8").replace('"APPROVED"', '"APPROVED_BY_SOMEONE"')
    ledger.path.write_text(tampered, encoding="utf-8")
    with pytest.raises(decisions.DecisionError, match="could not be read"):
        decisions.decide(ledger, q, "drop", principal="team@crooksldn.com", session_id="s1")
    assert ledger.path.read_text(encoding="utf-8") == tampered


def test_an_answer_that_asks_for_nothing_takes_the_build_off_his_list(tmp_path):
    ledger = decisions.ledger(tmp_path / "objectives")
    q = _question()
    decisions.decide(ledger, q, "drop", principal="team@crooksldn.com", session_id="s1",
                     now=datetime(2026, 10, 2, 22, 0, tzinfo=UTC))
    payload = _board(judgments=ledger.effective())
    assert payload["counts"]["needs_you"] == 1 and payload["counts"]["answered"] == 0 and payload["counts"]["stopped"] == 3
    build = next(b for b in _all(payload) if b["key"] == "status-publishes-findings")
    assert build["state"] == "decided" and build["words"] == "Dropped by you" and build["road"]["mark_kind"] == "stop"
    assert build["chosen"]["label"] == "Drop it" and build["chosen"]["decided_at"] == "2026-10-02T22:00:00+00:00"
    assert build["chosen"]["waiting"] == "" and build["group"] == "stopped"
    assert build["decision"] == q, "the question stays, to change the answer"


def test_an_answer_that_asks_for_action_stays_in_needs_you_until_something_acts(tmp_path):
    """The review of fe36872f, B-1: nothing reads the ledger yet, so "Try again" must not drop the
    build out of his list as though it were in hand."""
    ledger = decisions.ledger(tmp_path / "objectives")
    q = _question()
    decisions.decide(ledger, q, "retry", principal="team@crooksldn.com", session_id="s1",
                     now=datetime(2026, 10, 2, 22, 0, tzinfo=UTC))
    payload = _board(judgments=ledger.effective())
    assert payload["counts"]["needs_you"] == 1 and payload["counts"]["answered"] == 1
    assert payload["summary"] == "One build needs you. One answered, waiting to be acted on. Nothing is being built right now."
    needs = payload["groups"][0]
    assert needs["key"] == "needs_you" and [b["key"] for b in needs["builds"]] == [
        "skill-read-runtime-tool", "status-publishes-findings"], "unanswered first"
    build = needs["builds"][1]
    assert build["state"] == "answered" and build["words"] == "Answered, waiting to be acted on"
    assert build["road"]["mark_kind"] == "wait" and build["when"]["event"] == "stopped"
    assert build["chosen"]["then"] == "Asks for a fresh try that starts from the reviewer's open findings."
    assert build["chosen"]["waiting"].startswith("The build loop can't read answers yet")
    # A new try filed for it is what acts on it: the build is then that try, and the question is gone.
    newer = dict(_by_id("status-publishes-findings"), request_id="status-publishes-findings-2", stage="RUNNING",
                 recorded_at="2026-10-02T23:00:00+00:00", blocker=None, candidate_sha=None)
    moved = board_module.board([*_items(), newer], requests=_requests(), commits=_commits(), running_known=True,
                               links={}, judgments=ledger.effective())
    build = next(b for b in _all(moved) if b["key"] == "status-publishes-findings")
    assert build["state"] == "building" and build["chosen"] is None and moved["counts"]["answered"] == 0


# ------------------------------------------------------------------ the routes and the reads


def test_the_board_and_the_answer_are_the_owners_alone(loop):
    client = _client()
    assert client.get("/objectives/builds/board").status_code == 403
    assert client.post("/objectives/builds/decide", json={}).status_code == 403
    assert client.get("/objectives/builds/decisions").status_code == 403
    payload = client.get("/objectives/builds/board", headers=OWNER).json()
    assert payload["connected"] and payload["counts"]["needs_you"] == 2 and payload["problems"] == []
    assert client.get("/objectives/builds/board?brief=1", headers=OWNER).json() == {
        "connected": True, "summary": payload["summary"], "counts": payload["counts"]}


def test_an_answer_to_the_question_as_drawn_is_recorded_and_a_stale_one_is_not(loop, objectives):
    client = _client()
    q = next(b for b in _all(client.get("/objectives/builds/board", headers=OWNER).json())
             if b["key"] == "status-publishes-findings")["decision"]
    body = {"build": "status-publishes-findings", "proposal_id": q["proposal_id"], "fingerprint": q["fingerprint"],
            "answer": "retry", "session_id": "a1b2c3d4e5f6a7b8"}
    ledger_path = objectives.root / decisions.LEDGER_NAME
    stale = client.post("/objectives/builds/decide", headers=OWNER, json={**body, "fingerprint": "0" * 64})
    assert stale.status_code == 409 and stale.json()["code"] == "moved_on" and stale.json()["question"] == q
    gone = client.post("/objectives/builds/decide", headers=OWNER, json={**body, "build": "trunk-repair-ci"})
    assert gone.status_code == 409 and gone.json()["code"] == "no_question"
    wrong = client.post("/objectives/builds/decide", headers=OWNER, json={**body, "answer": "allow"})
    assert wrong.status_code == 400
    assert not ledger_path.exists(), "nothing was recorded for a refused answer"
    done = client.post("/objectives/builds/decide", headers=OWNER, json=body).json()
    assert done["recorded"] is True and done["chosen"]["label"] == "Try again"
    assert done["board"]["counts"]["needs_you"] == 1 and done["board"]["counts"]["answered"] == 1
    (record,) = load_judgment_ledger(ledger_path)[0].records
    assert record.provenance.principal_id == "team@crooksldn.com" and record.provenance.session_id == "a1b2c3d4e5f6a7b8"
    back = client.get("/objectives/builds/decisions", headers=OWNER).json()
    assert back["entries"] == 1 and back["judgments"][0]["answer_words"] == "Try again"


async def test_engineering_status_carries_his_answer_on_the_request_it_is_about(loop, objectives):
    q = _question()
    decisions.decide(decisions.ledger(), q, "retry", principal="team@crooksldn.com", session_id="s1")
    out = await engineering_tools.engineering_status()
    row = next(r for r in out["requests"] if r["request_id"] == "status-publishes-findings")
    said = row["owner_decision"]
    assert said["answer"] == "Try again" and said["needs_acting_on"] is True
    assert said["means"] == "Asks for a fresh try that starts from the reviewer's open findings."
    assert said["acted_on"].startswith("No: the build loop cannot read the owner's answers")
    assert all("owner_decision" not in r for r in out["requests"] if r["request_id"] != "status-publishes-findings")
    # A try filed after his answer is what acted on it.
    later = dict(_by_id("status-publishes-findings"), request_id="status-publishes-findings-2", stage="RUNNING",
                 recorded_at="2099-01-01T00:00:00+00:00")
    loop.status["requests"].append(later)
    engineering_tools._progress_cache.clear()
    out = await engineering_tools.engineering_status()
    row = next(r for r in out["requests"] if r["request_id"] == "status-publishes-findings")
    assert row["owner_decision"]["acted_on"] == "Yes: status-publishes-findings-2 was filed after it."


async def test_github_is_read_sparingly_and_each_title_once(loop, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(engineering_tools.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(read.time, "monotonic", lambda: now[0])
    first = await read.current()
    assert first["counts"]["live"] == 34
    reads = len(loop.calls)
    assert sum(1 for c in loop.calls if c.startswith("/contents/requests/")) == 65
    await read.current()
    assert len(loop.calls) == reads, "within a minute nothing is read again"
    now[0] += 61
    await read.current()
    again = loop.calls[reads:]
    assert again.count("/contents/status.json") == 1 and not any(c.startswith("/contents/requests/") for c in again)
    # Only the commits not yet on the trunk are compared again: the stopped builds' four.
    assert sum(1 for c in again if c.startswith("/compare/")) == 4


async def test_a_request_file_that_is_not_what_the_loop_took_in_gives_no_title(loop):
    rid = "status-publishes-findings"
    loop.files[rid] = loop.files[rid].replace("Publish open review findings", "Publish something else")
    payload = await read.current()
    build = next(b for b in _all(payload) if b["key"] == rid)
    assert build["title"] == "" and payload["problems"] == [
        "1 request could not be read from GitHub yet, so its title is missing."]


async def test_one_board_read_is_one_github_client_four_at_a_time(loop, monkeypatch):
    from app.engineering_bridge.github import EngineeringInbox

    made, flying, most = [], [0], [0]
    new_client = EngineeringInbox._new_client

    def counted(self):
        made.append(1)
        return new_client(self)

    handle = loop.handle

    def watched(request):
        flying[0] += 1
        most[0] = max(most[0], flying[0])
        try:
            return handle(request)
        finally:
            flying[0] -= 1

    monkeypatch.setattr(EngineeringInbox, "_new_client", counted)
    monkeypatch.setattr(loop, "handle", watched)
    builds_fixture.bind(monkeypatch, loop)
    payload = await read.current()
    assert payload["counts"]["live"] == 34 and len(loop.calls) > 100
    assert len(made) == 1, "a cold start reads everything through one client"
    assert most[0] <= read.CONCURRENCY


async def test_a_request_id_outside_the_inbox_rule_costs_its_title_and_nothing_else(loop, objectives):
    odd = dict(_by_id("status-publishes-findings"), request_id="Not A Valid Id!", recorded_at="2026-10-02T09:00:00+00:00")
    loop.status["requests"].append(odd)
    payload = await read.current()
    assert payload["connected"] and payload["counts"]["needs_you"] == 3
    assert payload["problems"] == ["1 request could not be read from GitHub yet, so its title is missing."]
    assert not any("Not A Valid Id" in c for c in loop.calls), "no path is ever made from it"
    client = _client()
    assert client.get("/objectives/builds/board", headers=OWNER).status_code == 200
    q = _question(payload=payload)
    body = {"build": "status-publishes-findings", "proposal_id": q["proposal_id"], "fingerprint": q["fingerprint"],
            "answer": "drop", "session_id": "s1"}
    assert client.post("/objectives/builds/decide", headers=OWNER, json=body).status_code == 200


def test_a_ledger_line_is_ascii_whatever_the_loops_data_holds_and_the_file_is_0600(tmp_path):
    """The review of fe36872f: a U+2028 written as itself splits the line for the kernel's reader
    (str.splitlines), and a ledger that existed with a wider mode keeps it unless the write narrows it."""
    ledger = decisions.ledger(tmp_path / "objectives")
    ledger.path.parent.mkdir(parents=True)
    ledger.path.write_bytes(b"")
    os.chmod(ledger.path, 0o644)
    q = dict(_question(), attempt_id="status-publishes-findings-a4\u2028x\u0085y")
    record, _ = decisions.decide(ledger, q, "retry", principal="team@crooksldn.com", session_id="s1")
    raw = ledger.path.read_bytes()
    assert raw.isascii() and raw.count(b"\n") == 1 and "\\u2028" in raw.decode("ascii")
    loaded, _digest = load_judgment_ledger(ledger.path)
    assert loaded.records == (record,) and loaded.records[0].attempt_id.endswith("\u2028x\u0085y")
    assert oct(os.stat(ledger.path).st_mode & 0o777) == "0o600"


async def test_with_github_away_the_screen_says_so(loop):
    loop.down = True
    payload = await read.current()
    assert payload["connected"] is False and payload["groups"] == []
    assert "HTTP 503" in payload["summary"]


async def test_the_board_carries_the_release_services_own_line_or_says_it_is_not_installed(loop, tmp_path,
                                                                                         monkeypatch):
    from app.release import state as release_state
    from app.release import status as release_status
    from app.release.host import SystemHost

    monkeypatch.setenv("CLIVE_RELEASE_STATE_DIR", str(tmp_path / "release"))
    payload = await read.current()
    assert payload["release"] == {"installed": False, "state": "", "line": release_status.NOT_INSTALLED, "at": "",
                                  "mode": "", "rule": "", "ready_for": "", "sha": "", "title": "", "deploy": None}
    release_state.write_status(SystemHost(), tmp_path / "release", state="rolled_back",
                               line="Tried “X” and rolled back: /health after is not well.", at="2026-10-08T01:00:00Z",
                               mode="live")
    loop.down = True                       # the line is the server's own file, whatever GitHub says
    payload = await read.current()
    assert payload["release"]["state"] == "rolled_back" and payload["release"]["line"].startswith("Tried “X”")


def test_the_builds_screen_under_node(tmp_path):
    """web/builds.js with the page's own code, drawing this board (tests/web/builds.test.js)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed here")
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board()), encoding="utf-8")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([node, "--test", os.path.join(root, "tests", "web", "builds.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=root,
                            env={**os.environ, "BUILDS_BOARD": str(board)})
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout and "# skipped 0" in result.stdout


# ------------------------------------------------------------------ the build server's private record (7 Oct)

STOPPED_ON = "2738f2543a9650b469c6dc637a43fb68f5c6acb9"   # the candidate status-publishes-findings stopped on


def _private_stop(**over) -> dict:
    stop = {
        "request_id": "status-publishes-findings", "cause": "review_limit", "stage": "BLOCKED",
        "candidate_sha": STOPPED_ON,
        "review_rounds": [
            {"candidate_sha": "1" * 40, "findings": [{"finding_id": "F-00", "material": True,
                                                       "finding": "MARKER-OLD a finding the next round repaired",
                                                       "evidence_ref": "a.py", "required_repair": "fix a.py"}]},
            {"candidate_sha": STOPPED_ON, "findings": [O1_01]},
        ],
        "failed_checks": [{"what": "check", "name": "tests", "exit_code": 1,
                           "tail": "collected 3 items\nE   AssertionError: MARKER-TAIL for owner@example.com\n"}],
        "builder_report": {"status": "completed", "summary": "MARKER-BUILDER made the change", "reason": None},
    }
    stop.update(over)
    return stop


def test_a_stopped_build_shows_the_reviewers_own_words_from_the_build_servers_private_record():
    """The owner's loop upgrade of 7 Oct, item 1: the findings reach the screen through the build server's private
    channel, never GitHub. The round shown is the one on the candidate that stopped; an earlier, repaired one is
    not."""
    items = read.with_private(_items(), {"status-publishes-findings": _private_stop()})
    build = next(b for b in _all(_board_of(items)) if b["key"] == "status-publishes-findings")
    assert [f["id"] for f in build["findings"]] == ["O1-01"]
    assert build["findings"][0] == plain.finding(O1_01)
    details = build["details"]
    [printed] = details["check_output"]
    assert printed.startswith("tests (exit 1)\ncollected 3 items\nE   AssertionError: MARKER-TAIL")
    assert "owner@example.com" not in printed
    assert details["builder_said"] == "MARKER-BUILDER made the change"
    assert not HEX.search(_face(build)) and not BRANCH.search(_face(build))
    # the published status itself is never changed, and a build with no private record reads as before
    assert _by_id("status-publishes-findings").get("findings") is None
    plain_board = _board_of(_items())
    before = next(b for b in _all(plain_board) if b["key"] == "status-publishes-findings")
    assert before["findings"] is None and before["details"]["check_output"] == [] and before["details"]["builder_said"] == ""


def test_a_stop_for_another_reason_shows_no_findings_from_a_round_already_repaired():
    stop = _private_stop(cause="github_red", candidate_sha="3" * 40)
    items = read.with_private(_items(), {"status-publishes-findings": stop})
    build = next(b for b in _all(_board_of(items)) if b["key"] == "status-publishes-findings")
    assert build["findings"] is None and build["details"]["check_output"]


def _board_of(items: list[dict]) -> dict:
    return board_module.board(items, requests=_requests(), commits=_commits(), running_known=True, links={},
                              judgments={}, as_of=builds_fixture.status()["generated_at"])


async def test_the_board_reads_the_private_record_and_says_when_it_cannot(loop, monkeypatch):
    from app.engineering_bridge import private

    answers = [({"status-publishes-findings": _private_stop()}, ""), (None, private.UNREADABLE)]

    async def stops():
        return answers.pop(0)
    monkeypatch.setattr(private, "stops", stops)
    monkeypatch.setattr(private, "configured", lambda: True)
    payload = await read.current()
    build = next(b for b in _all(payload) if b["key"] == "status-publishes-findings")
    assert payload["private"] is True and payload["problems"] == [] and build["findings"][0]["id"] == "O1-01"
    payload = await read.current()
    assert payload["problems"] == [private.UNREADABLE]
    build = next(b for b in _all(payload) if b["key"] == "status-publishes-findings")
    assert build["findings"] is None


async def test_with_the_private_channel_off_the_board_is_as_it_was(loop):
    payload = await read.current()
    assert payload["private"] is False and payload["problems"] == []
