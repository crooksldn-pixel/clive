"""The owner's two measures, from fixture records only: no loop, no repository, no network.

The fixture is four requests over four days. ``req-a`` lands directly as a merge's second
parent; ``req-b`` was repaired once and lands only inside a later merge of a follow-up
branch; ``req-c`` never lands; ``req-r`` was refused at intake. 2026-09-22 has objectives
but no deploy.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.engineering_measures import (
    FIELD_SEP,
    MeasuresError,
    TrunkCommit,
    measure,
    parse_graph_log,
    parse_trunk_log,
    render_markdown,
    trunk_landings,
)
from scripts import engineering_measures as cli

ROOT_SHA = "0" * 40
BEFORE_ROOT = "e" * 40
T1 = "1" * 40
T2 = "2" * 40
T3 = "3" * 40
CAND_A = "a" * 40
CAND_B = "b" * 40
CAND_C = "c" * 40
FOLLOW_UP = "d" * 40
UNRELATED = "9" * 40


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def trunk_history() -> list[TrunkCommit]:
    """``git log --first-parent`` order: newest first."""
    return [
        TrunkCommit(T3, (T2, FOLLOW_UP), at("2026-09-23T15:00"), "Merge pull request #13 from clive/b-follow-up"),
        TrunkCommit(T2, (T1, UNRELATED), at("2026-09-22T10:00"), "Merge pull request #12 from clive/x"),
        TrunkCommit(T1, (ROOT_SHA, CAND_A), at("2026-09-21T12:00"), "Merge pull request #11 from clive/a"),
        TrunkCommit(ROOT_SHA, (BEFORE_ROOT,), at("2026-09-20T09:00"), "Start of history"),
    ]


def commit_graph() -> dict[str, tuple[str, ...]]:
    return {
        T3: (T2, FOLLOW_UP),
        T2: (T1, UNRELATED),
        T1: (ROOT_SHA, CAND_A),
        FOLLOW_UP: (CAND_B,),
        CAND_B: (ROOT_SHA,),
        CAND_A: (ROOT_SHA,),
        UNRELATED: (T1,),
        ROOT_SHA: (BEFORE_ROOT,),
        BEFORE_ROOT: (),
    }


def verdict(outcome: str) -> dict:
    return {"outcome": outcome, "verdict": "x", "reviewer": "r", "reasons": [], "at": "2026-09-21T09:30:00+00:00"}


def request(request_id: str, recorded_at: str, **task) -> dict:
    item = {
        "request_id": request_id,
        "source": f"inbox/{request_id}.json",
        "request_sha256": "0" * 64,
        "outcome": "accepted",
        "reason": None,
        "objective_id": f"obj-{request_id[4:]}",
        "task_id": f"task-{request_id[4:]}",
        "recorded_at": recorded_at,
    }
    item.update(task)
    return item


def status_projection() -> dict:
    return {
        "schema_version": "clive.remote_engineering_status.v1",
        "generated_at": "2026-09-24T00:00:00+00:00",
        "requests": [
            request(
                "req-a", "2026-09-21T08:00:00+00:00", revision=1, stage="COMPLETE", candidate_sha=CAND_A,
                review={"verdicts": [verdict("accepted")]},
                acceptance={"sha": CAND_A, "at": "2026-09-21T09:45:00+00:00", "by": "r"},
                integration={"sha": CAND_A, "at": "2026-09-21T10:00:00+00:00", "method": "fast_forward"},
            ),
            request(
                "req-b", "2026-09-21T09:00:00+00:00", revision=2, stage="COMPLETE", candidate_sha=CAND_B,
                review={"verdicts": [verdict("refused"), verdict("accepted")]},
                acceptance={"sha": CAND_B, "at": "2026-09-22T08:00:00+00:00", "by": "r"},
                integration={"sha": CAND_B, "at": "2026-09-22T09:00:00+00:00", "method": "fast_forward"},
            ),
            request(
                "req-c", "2026-09-22T09:00:00+00:00", revision=1, stage="BLOCKED", candidate_sha=CAND_C,
                review={"verdicts": [verdict("rejected_by_verdict")]}, acceptance=None, integration=None,
            ),
            {
                "request_id": "req-r",
                "source": "inbox/req-r.json",
                "request_sha256": "1" * 64,
                "outcome": "refused",
                "reason": "outside the allowed paths",
                "objective_id": None,
                "task_id": None,
                "recorded_at": "2026-09-22T11:00:00+00:00",
            },
        ],
        "refused_records": [],
    }


def deploy_log() -> list[dict]:
    return [
        {"sha": T1, "deployed_at": "2026-09-21T18:00:00+00:00"},
        {"sha": T3, "deployed_at": "2026-09-24T09:00:00+00:00"},
    ]


def attention_log() -> list[dict]:
    return [
        {"at": "2026-09-21T08:30:00+00:00", "minutes": 5, "about": "req-a"},
        {"at": "2026-09-22T10:00:00+00:00", "minutes": 7, "about": "PR #13"},
        {"at": "2026-09-22T12:00:00+00:00", "minutes": 3, "about": "obj-c"},
        {"at": "2026-09-23T09:00:00+00:00", "minutes": 4, "about": "#12"},
        {"at": "2026-09-23T10:00:00+00:00", "minutes": 2, "about": "general loop health"},
    ]


def full_report() -> dict:
    return measure(
        status_projections=[status_projection()],
        trunk=trunk_history(),
        graph=commit_graph(),
        deploy_log=deploy_log(),
        attention_log=attention_log(),
    )


def rows_by_id(report: dict) -> dict[str, dict]:
    return {row["request_id"]: row for row in report["objectives"]}


def days_by_date(report: dict) -> dict[str, dict]:
    return {day["day"]: day for day in report["days"]}


# ------------------------------------------------------------------ per objective


def test_both_measures_per_objective_from_every_input():
    rows = rows_by_id(full_report())

    a = rows["req-a"]
    assert a["hours_to_complete"] == 2.0
    assert (a["landed_via"], a["pull_request"], a["hours_to_trunk"]) == (T1, "#11", 4.0)
    assert (a["deployed_sha"], a["hours_to_production"]) == (T1, 10.0)
    assert a["review_rounds"] == 1
    assert a["owner_minutes"] == 5.0

    b = rows["req-b"]
    assert b["hours_to_complete"] == 24.0
    # One earlier revision rejected, plus the admitted verdict on this one; the refused
    # verdict was never a review round.
    assert b["review_rounds"] == 2
    assert b["owner_minutes"] == 7.0  # attributed through the pull request that landed it


def test_objective_that_never_landed_has_no_trunk_or_production_time():
    c = rows_by_id(full_report())["req-c"]
    assert c["completed_at"] is None and c["hours_to_complete"] is None
    assert c["landed_at"] is None and c["hours_to_trunk"] is None
    assert c["deployed_at"] is None and c["hours_to_production"] is None
    assert c["review_rounds"] == 1
    assert c["owner_minutes"] == 3.0


def test_refused_request_is_counted_with_empty_measures():
    r = rows_by_id(full_report())["req-r"]
    assert r["outcome"] == "refused"
    assert r["review_rounds"] is None
    assert r["hours_to_complete"] is None and r["hours_to_trunk"] is None
    assert r["owner_minutes"] == 0.0


def test_candidate_landed_through_a_later_merge():
    rows = rows_by_id(full_report())
    b = rows["req-b"]
    # B was never a merge parent: it reached the trunk inside the follow-up branch merged by T3,
    # after T2 had already merged something else.
    assert (b["landed_via"], b["pull_request"]) == (T3, "#13")
    assert b["landed_at"] == "2026-09-23T15:00:00+00:00"
    assert b["hours_to_trunk"] == 54.0
    assert (b["deployed_sha"], b["hours_to_production"]) == (T3, 72.0)


def test_without_the_commit_graph_only_merge_parents_are_known():
    report = measure(status_projections=[status_projection()], trunk=trunk_history(), deploy_log=deploy_log())
    rows = rows_by_id(report)
    assert rows["req-a"]["landed_via"] == T1
    assert rows["req-b"]["landed_at"] is None
    assert rows["req-b"]["hours_to_production"] is None


def test_landings_start_at_the_oldest_supplied_commit():
    landings = trunk_landings(trunk_history(), commit_graph())
    assert landings[ROOT_SHA].position == 0
    assert landings[UNRELATED].trunk_sha == T2
    assert BEFORE_ROOT not in landings  # predates the history: when it landed is unknown


def test_a_later_deploy_on_the_trunk_covers_earlier_landings():
    deploys = [{"sha": T3, "deployed_at": "2026-09-24T09:00:00+00:00"}]
    report = measure(
        status_projections=[status_projection()], trunk=trunk_history(), graph=commit_graph(), deploy_log=deploys
    )
    assert rows_by_id(report)["req-a"]["deployed_sha"] == T3


def test_a_deploy_of_the_candidate_itself_needs_no_trunk():
    deploys = [{"sha": CAND_C.upper(), "deployed_at": "2026-09-22T12:00:00+00:00"}]
    report = measure(status_projections=[status_projection()], deploy_log=deploys)
    assert rows_by_id(report)["req-c"]["hours_to_production"] == 3.0
    assert rows_by_id(report)["req-a"]["hours_to_production"] is None


# ------------------------------------------------------------------ per day


def test_totals_and_medians_per_day():
    days = days_by_date(full_report())
    assert sorted(days) == ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]

    first = days["2026-09-21"]
    assert (first["objectives"], first["completed"], first["landed"], first["deployed"]) == (2, 2, 2, 2)
    assert first["deploys"] == 1
    assert (first["total_hours_to_complete"], first["median_hours_to_complete"]) == (26.0, 13.0)
    assert (first["total_hours_to_trunk"], first["median_hours_to_trunk"]) == (58.0, 29.0)
    assert (first["total_hours_to_production"], first["median_hours_to_production"]) == (82.0, 41.0)
    assert (first["review_rounds"], first["median_review_rounds"]) == (3, 1.5)
    assert (first["owner_minutes_attributed"], first["median_owner_minutes"]) == (12.0, 6.0)
    assert first["owner_minutes_logged"] == 5.0


def test_day_without_deploys_has_no_production_median():
    second = days_by_date(full_report())["2026-09-22"]
    assert second["objectives"] == 2
    assert (second["deploys"], second["deployed"]) == (0, 0)
    assert second["median_hours_to_production"] is None and second["total_hours_to_production"] is None
    # req-c never landed and req-r was refused: no completion or trunk hours to add up.
    assert second["landed"] == 0 and second["median_hours_to_trunk"] is None
    assert second["total_hours_to_trunk"] is None and second["total_hours_to_complete"] is None
    assert second["owner_minutes_logged"] == 10.0


def test_days_with_only_attention_or_deploys_are_reported():
    days = days_by_date(full_report())
    third = days["2026-09-23"]
    assert third["objectives"] == 0 and third["deploys"] == 0
    assert third["owner_minutes_logged"] == 6.0 and third["owner_minutes_attributed"] == 0
    assert third["median_hours_to_complete"] is None and third["total_hours_to_complete"] is None
    assert days["2026-09-24"]["deploys"] == 1
    assert days["2026-09-24"]["total_hours_to_production"] is None  # the deploy covers objectives of earlier days


def test_totals_and_unattributed_minutes():
    report = full_report()
    totals = report["totals"]
    assert (totals["objectives"], totals["completed"], totals["landed"], totals["deployed"]) == (4, 2, 2, 2)
    assert (totals["total_hours_to_complete"], totals["total_hours_to_trunk"]) == (26.0, 58.0)
    assert totals["total_hours_to_production"] == 82.0
    assert totals["owner_minutes_attributed"] == 15.0
    assert totals["owner_minutes_logged"] == 21.0
    unattributed = {entry["about"]: entry for entry in report["unattributed_attention"]}
    assert set(unattributed) == {"#12", "general loop health"}
    assert "no objective landed through pull request #12" in unattributed["#12"]["reason"]


# ------------------------------------------------------------------ missing inputs


def test_missing_inputs_leave_their_columns_empty():
    report = measure(status_projections=[status_projection()])
    assert report["inputs"] == {
        "status_projections": 1,
        "trunk_history": False,
        "commit_graph": False,
        "deploy_log": False,
        "attention_log": False,
    }
    for row in report["objectives"]:
        for column in ("landed_at", "hours_to_trunk", "pull_request", "deployed_at", "hours_to_production", "owner_minutes"):
            assert row[column] is None, (row["request_id"], column)
    assert rows_by_id(report)["req-a"]["hours_to_complete"] == 2.0  # the status projection was supplied
    for aggregate in (*report["days"], report["totals"]):
        for column in ("landed", "deployed", "deploys", "owner_minutes_attributed", "median_owner_minutes",
                       "owner_minutes_logged", "median_hours_to_trunk", "median_hours_to_production",
                       "total_hours_to_trunk", "total_hours_to_production"):
            assert aggregate[column] is None, column
    assert report["totals"]["total_hours_to_complete"] == 26.0  # the status projection was supplied
    assert report["unattributed_attention"] == []


def test_supplied_but_empty_logs_are_facts_not_gaps():
    report = measure(status_projections=[status_projection()], deploy_log=[], attention_log=[])
    assert report["totals"]["deploys"] == 0 and report["totals"]["deployed"] == 0
    assert rows_by_id(report)["req-a"]["owner_minutes"] == 0.0
    assert rows_by_id(report)["req-a"]["hours_to_production"] is None


def test_pull_request_attention_without_trunk_is_not_attributed():
    report = measure(status_projections=[status_projection()], attention_log=attention_log())
    assert rows_by_id(report)["req-b"]["owner_minutes"] == 0.0
    reasons = {entry["about"]: entry["reason"] for entry in report["unattributed_attention"]}
    assert "without the trunk history" in reasons["PR #13"]


def test_attention_naming_several_objectives_is_not_split():
    projection = status_projection()
    projection["requests"][1]["objective_id"] = "obj-a"
    report = measure(
        status_projections=[projection], attention_log=[{"at": "2026-09-21T09:00:00Z", "minutes": 6, "about": "obj-a"}]
    )
    assert all(row["owner_minutes"] == 0.0 for row in report["objectives"])
    assert report["unattributed_attention"][0]["reason"].startswith("names 2 objectives")


def test_several_projections_merge_and_the_latest_wins():
    later = {
        "generated_at": "2026-09-25T00:00:00+00:00",
        "requests": [
            request("req-c", "2026-09-22T09:00:00+00:00", revision=2, stage="COMPLETE", candidate_sha=CAND_C,
                    review={"verdicts": [verdict("accepted")]},
                    integration={"sha": CAND_C, "at": "2026-09-23T09:00:00+00:00"}),
            request("req-z", "2026-09-24T09:00:00+00:00", revision=1, stage="RUNNING", candidate_sha=None),
        ],
    }
    report = measure(status_projections=[later, status_projection()])
    rows = rows_by_id(report)
    assert set(rows) == {"req-a", "req-b", "req-c", "req-r", "req-z"}
    assert rows["req-c"]["hours_to_complete"] == 24.0
    assert rows["req-c"]["review_rounds"] == 2
    assert [row["request_id"] for row in report["objectives"]] == ["req-a", "req-b", "req-c", "req-r", "req-z"]


def test_naive_or_malformed_timestamps_are_refused():
    projection = status_projection()
    projection["requests"][0]["recorded_at"] = "2026-09-21T08:00:00"
    with pytest.raises(MeasuresError, match="no timezone"):
        measure(status_projections=[projection])
    with pytest.raises(MeasuresError, match="deploy log record 1"):
        measure(status_projections=[status_projection()], deploy_log=[{"sha": T1, "deployed_at": "soon"}])
    with pytest.raises(MeasuresError, match="minutes"):
        measure(status_projections=[status_projection()], attention_log=[{"at": "2026-09-21T09:00:00Z", "minutes": "5", "about": "x"}])


# ------------------------------------------------------------------ parsing and rendering


def test_git_log_output_parses_into_the_same_history():
    first_parent = "\n".join(
        FIELD_SEP.join((c.sha, " ".join(c.parents), c.committed_at.isoformat(), c.subject)) for c in trunk_history()
    )
    graph = "\n".join(FIELD_SEP.join((sha, " ".join(parents))) for sha, parents in commit_graph().items())
    assert parse_trunk_log(first_parent + "\n") == trunk_history()
    assert parse_graph_log(graph) == commit_graph()
    with pytest.raises(MeasuresError, match="trunk log line 1"):
        parse_trunk_log("not a log line")


def test_markdown_renders_empty_cells_not_none():
    markdown = render_markdown(measure(status_projections=[status_projection()]))
    assert "## Per objective" in markdown and "## Per day" in markdown and "## Totals" in markdown
    assert "None" not in markdown
    assert "deploy log: not supplied" in markdown


def test_markdown_shows_daily_hour_totals():
    lines = render_markdown(full_report()).splitlines()
    header = next(line for line in lines if line.startswith("| Day |"))
    titles = [cell.strip() for cell in header.strip("|").split("|")]

    def day_cells(day: str) -> dict[str, str]:
        row = next(line for line in lines if line.startswith(f"| {day} |"))
        return dict(zip(titles, (cell.strip() for cell in row.strip("|").split("|")), strict=True))

    first = day_cells("2026-09-21")
    assert (first["Total h to complete"], first["Total h to trunk"], first["Total h to production"]) == ("26", "58", "82")
    second = day_cells("2026-09-22")
    assert (second["Total h to complete"], second["Total h to trunk"], second["Total h to production"]) == ("", "", "")


# ------------------------------------------------------------------ the script


def write_inputs(tmp_path) -> list[str]:
    status = tmp_path / "status.json"
    status.write_text(json.dumps(status_projection()), encoding="utf-8")
    deploys = tmp_path / "deploys.jsonl"
    deploys.write_text("\n".join(json.dumps(record) for record in deploy_log()) + "\n", encoding="utf-8")
    attention = tmp_path / "attention.jsonl"
    attention.write_text("\n".join(json.dumps(record) for record in attention_log()) + "\n", encoding="utf-8")
    return ["--status", str(status), "--deploy-log", str(deploys), "--attention-log", str(attention)]


def test_script_reads_the_trunk_with_git_log(tmp_path, monkeypatch):
    calls = []
    first_parent = "\n".join(
        FIELD_SEP.join((c.sha, " ".join(c.parents), c.committed_at.isoformat(), c.subject)) for c in trunk_history()
    )
    graph = "\n".join(FIELD_SEP.join((sha, " ".join(parents))) for sha, parents in commit_graph().items())

    def fake_git_log(repo, *args):
        calls.append(args)
        return first_parent if "--first-parent" in args else graph

    monkeypatch.setattr(cli, "_git_log", fake_git_log)
    out = tmp_path / "measures.json"
    assert cli.main([*write_inputs(tmp_path), "--json", str(out), "--markdown", str(tmp_path / "m.md")]) == 0
    assert all(args[-2:] == ("clive/trunk", "--") for args in calls)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rows_by_id(report)["req-b"]["landed_via"] == T3
    assert report["inputs"]["trunk_source"].startswith("clive/trunk")
    assert (tmp_path / "m.md").read_text(encoding="utf-8").startswith("# Engineering measures")


def test_script_leaves_trunk_columns_empty_when_the_ref_is_unreadable(tmp_path, monkeypatch, capsys):
    def unreadable(repo, ref):
        raise cli.TrunkUnavailable("unknown revision clive/trunk")

    monkeypatch.setattr(cli, "read_trunk", unreadable)
    assert cli.main([*write_inputs(tmp_path), "--format", "json"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert all(row["landed_at"] is None for row in report["objectives"])
    assert report["totals"]["landed"] is None
    assert "unavailable" in captured.err


def test_script_refuses_malformed_logs(tmp_path, capsys):
    arguments = write_inputs(tmp_path)
    (tmp_path / "deploys.jsonl").write_text("{not json\n", encoding="utf-8")
    assert cli.main([*arguments, "--no-trunk"]) == 2
    assert "deploy log line 1" in capsys.readouterr().err
