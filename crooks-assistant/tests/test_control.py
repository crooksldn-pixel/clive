"""CROOKS Control: the JSON the app renders, and the refusals behind the buttons.

The app itself is Swift and cannot be compiled here. That is the reason this file exists:
everything the app decides is decided by `scripts/control.py` and `scripts/update.py --json`,
and everything in those two is tested here — the four-colour roll-up, both SHAs, the
fast-forward-only rule, the dirty-tree stop, the rollback decision, and the promise that no
secret reaches the screen. The Swift side reads these documents and draws them; if it drifts
from this shape, the contract test below is what fails.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import control, update
from scripts import launch_common as lc

# The checkout these tests are part of, whatever directory pytest was started from.
PROJECT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- a real repo


@pytest.fixture()
def repo(tmp_path):
    """A tiny git repo with a remote, so the refusals can be tested against real git."""
    origin, work = tmp_path / "origin", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "T")):
        subprocess.run(["git", "config", key, value], cwd=work, check=True)
    (work / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (work / "app.py").write_text("print('one')\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "HEAD"], cwd=work, check=True)
    return work


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def commit_upstream(repo: Path, text: str = "print('two')\n", *, path: str = "app.py") -> str:
    """A commit on the remote and nowhere else: what an update has to fast-forward to."""
    clone = repo.parent / "other"
    if not clone.exists():
        subprocess.run(["git", "clone", "-q", str(repo.parent / "origin"), str(clone)], check=True)
        for key, value in (("user.email", "t@example.com"), ("user.name", "T")):
            subprocess.run(["git", "config", key, value], cwd=clone, check=True)
    else:
        subprocess.run(["git", "pull", "-q"], cwd=clone, check=True)
    (clone / path).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", f"upstream {path}"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q"], cwd=clone, check=True)
    return head(clone)


@pytest.fixture()
def here(repo, monkeypatch, tmp_path):
    """Both scripts pointed at the fixture repo, with a logs/ of its own."""
    monkeypatch.setattr(update, "ROOT", repo)
    monkeypatch.setattr(control, "ROOT", repo)
    monkeypatch.setattr(control, "LOG_DIR", repo / "logs")
    return repo


# --------------------------------------------------------- the path out of a status line


@pytest.mark.parametrize(("line", "expected"), [
    (" M app/routes/turn.py", "app/routes/turn.py"),
    ("M app/routes/turn.py", "app/routes/turn.py"),        # the first line, after git() stripped it
    ("?? .venv", ".venv"),
    (" M .env", ".env"),
    ("M .env", ".env"),
    ("MM Makefile", "Makefile"),
    (" D logs/assistant.out.log", "logs/assistant.out.log"),
    ('R  "old name.py" -> "new name.py"', "new name.py"),
    ("!! reports/x.md", "reports/x.md"),
    ("", ""),
])
def test_the_path_is_read_off_the_status_letters_not_a_fixed_column(line, expected):
    """`git()` strips its output, so an unstaged change on the first line arrives without its
    leading space. Reading from column three ate the first character — and a hand-edited
    `.env` became "env", which is not in NEVER_TOUCH, which stopped an update that should
    have gone ahead."""
    assert update._porcelain_path(line) == expected


def test_a_hand_edited_env_on_the_first_line_does_not_stop_the_update(here):
    """The bug above, end to end: the owner's own `.env`, modified, and nothing else."""
    (here / ".env").write_text("CROOKS_WRITES_ENABLED=true\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=here, check=True)
    subprocess.run(["git", "commit", "-qm", "env"], cwd=here, check=True)
    (here / ".env").write_text("CROOKS_WRITES_ENABLED=false\n", encoding="utf-8")
    assert update.dirty_paths() == [".env"]
    assert update.blocking_changes([".env"]) == []
    code, doc = update.run(check=True, quiet=True)
    assert code == 0 and doc["stop"] is None
    assert doc["local_work"] == {"dirty": [".env"], "blocking": [], "stops": False}
    assert (here / ".env").read_text(encoding="utf-8") == "CROOKS_WRITES_ENABLED=false\n"


# ------------------------------------------------------------ the update, as one document


def test_the_check_document_carries_both_shas_and_changes_nothing(here):
    before = head(here)
    candidate = commit_upstream(here)
    code, doc = update.run(check=True, quiet=True)
    assert code == 0 and doc["ok"] is True
    assert doc["contract"] == update.CONTRACT and doc["command"] == "crooks-update"
    assert doc["current"]["sha"] == before and doc["candidate"]["sha"] == candidate
    assert doc["current"]["short"] == before[:10] and len(doc["candidate"]["short"]) == 10
    assert doc["behind"] == 1 and doc["ahead"] == 0 and doc["fast_forward"] is True
    assert doc["next"] == "click_to_apply", "a check never applies; the click does"
    assert doc["moved"] is False and doc["restarted"] is False and doc["verified"] is False
    assert head(here) == before, "nothing moved"
    assert [s["stage"] for s in doc["stages"]] == ["repo", "branch", "fetch", "pull", "deps", "tests"]


def test_up_to_date_says_so_rather_than_offering_a_click(here):
    code, doc = update.run(check=True, quiet=True)
    assert code == 0 and doc["behind"] == 0 and doc["next"] == "up_to_date"
    assert doc["current"]["sha"] == doc["candidate"]["sha"]


def test_a_diverged_branch_is_refused_as_not_a_fast_forward(here):
    """The owner has a commit the remote does not. There is no fast-forward, so there is no
    update — and the commit is still there afterwards."""
    commit_upstream(here)
    (here / "mine.py").write_text("mine\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=here, check=True)
    subprocess.run(["git", "commit", "-qm", "mine"], cwd=here, check=True)
    mine = head(here)
    code, doc = update.run(quiet=True)
    assert code == 1 and doc["ok"] is False
    assert doc["fast_forward"] is False and doc["ahead"] == 1 and doc["behind"] == 1
    assert doc["stop"]["stage"] == "pull"
    assert "cannot fast-forward" in doc["stop"]["reason"]
    assert doc["next"] == "blocked"
    assert head(here) == mine, "the owner's commit is untouched"
    assert (here / "mine.py").exists()


def test_a_dirty_tree_stops_the_update_and_says_which_files(here):
    commit_upstream(here)
    (here / "app.py").write_text("print('mine, uncommitted')\n", encoding="utf-8")
    before = head(here)
    code, doc = update.run(quiet=True)
    assert code == 1 and doc["stop"]["stage"] == "branch"
    assert doc["local_work"]["blocking"] == ["app.py"] and doc["local_work"]["stops"] is True
    assert "app.py" in doc["stop"]["reason"] and "will not throw work away" in doc["stop"]["reason"]
    assert head(here) == before
    assert (here / "app.py").read_text(encoding="utf-8") == "print('mine, uncommitted')\n"


def test_the_fast_forward_moves_the_build_and_says_what_moved(here, monkeypatch):
    """The apply path, with the restart and the health read stubbed: launchd and /health are
    the Mac's, not this machine's. What is tested here is that the code moved, by a
    fast-forward, and that the document says so."""
    candidate = commit_upstream(here, path="pyproject.toml", text="[project]\nname='x'\nversion='2'\n")
    kicked: list[str] = []
    monkeypatch.setattr(update, "stage_deps", lambda changed, *, check_only: bool(update.dep_changes(changed)))
    monkeypatch.setattr(update, "stage_restart", lambda *, check_only, port: kicked.append("restart"))
    monkeypatch.setattr(update, "stage_verify", lambda *, check_only, port: {"build": "b-2", "status": "ok"})
    code, doc = update.run(quiet=True)
    assert code == 0 and doc["moved"] is True
    assert head(here) == candidate
    assert doc["current"]["sha"] != candidate, "the document names the build it started from"
    assert doc["deps"] == ["pyproject.toml"] and doc["changed_files"] == 1
    assert doc["restarted"] is True and doc["verified"] is True
    assert doc["current"]["build"] == "b-2" and doc["next"] == "verify_the_tablet"
    assert kicked == ["restart"]


def test_a_failing_suite_stops_before_anything_restarts(here, monkeypatch):
    commit_upstream(here)
    monkeypatch.setattr(update, "stage_restart", lambda **kw: pytest.fail("restarted a build that did not pass"))
    monkeypatch.setattr(update, "stage_verify", lambda **kw: pytest.fail("verified a build that did not pass"))
    (here / ".venv" / "bin").mkdir(parents=True)
    fake = here / ".venv" / "bin" / "pytest"
    fake.write_text("#!/bin/sh\necho '1 failed, 2 passed'\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    code, doc = update.run(test=True, quiet=True)
    assert code == 1 and doc["stop"]["stage"] == "tests"
    assert "did not pass" in doc["stop"]["reason"] and "1 failed" in doc["stop"]["reason"]
    assert doc["moved"] is True, "the code did move; that is what the rollback is for"
    assert doc["tested"] is False and doc["restarted"] is False


def test_the_suite_is_not_run_unless_it_is_asked_for(here):
    commit_upstream(here)
    code, doc = update.run(check=True, quiet=True)
    tests = [s for s in doc["stages"] if s["stage"] == "tests"]
    assert tests and tests[0]["state"] == "skip" and "not asked for" in tests[0]["detail"]
    assert code == 0


def test_the_json_switch_prints_one_document_and_no_lines(here, capsys):
    assert update.main(["--check", "--json"]) == 0
    out = capsys.readouterr().out
    doc = json.loads(out), "the whole of stdout parses as one JSON document"
    assert doc[0]["command"] == "crooks-update"
    assert "crooks-update" not in out.split("\n", 1)[0], "no human header above the JSON"


def test_the_typed_command_still_prints_its_lines(here, capsys):
    assert update.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("crooks-update  (check only")
    assert f"{update.OK} repo    " in out and f"{update.SKIP} pull    " in out
    assert "already up to date" in out, "the same seven lines it always printed"


# ------------------------------------------------------------------- what /health looks like


def check(ok: bool, detail: str = "") -> dict:
    return {"ok": ok, "detail": detail}


def family(state: str, *, label: str, scope: str = "", detail: str = "", operations=("order_note_append",)) -> dict:
    return {"key": label.lower().replace(" ", "_"), "label": label, "area": "orders", "what": "…",
            "state": state, "detail": detail or state.lower(), "scope": scope,
            "operations": list(operations), "tools": [], "offerable": state == "READY", "hide": False}


def health_doc(**over) -> dict:
    """A /health as the running backend answers it, everything well."""
    doc = {
        "status": "ok", "version": "0.1.0", "build": "b-2026-09-10-abc", "uptime_s": 7200.0, "sessions": 1,
        "checks": {
            "speech": check(True, "scribe_v2 (primary)"), "tts": check(True, "Derek"),
            "claude": check(True, "sonnet, CLI"), "shopify": check(True, "5wn03t-nm.myshopify.com"),
            "gmail": check(True, "george@crooksldn.com"), "whisper": check(True, "small.en"),
            "knowledge_base": check(True, "7 file(s)"), "terminology": check(True, "120 term(s)"),
            "writes": check(True, "ready"),
        },
        "speech": {"primary": "scribe", "effective": "scribe_v2"},
        "writes": {"state": "ready", "detail": "ready"},
        "families": {"order_note": family("READY", label="Order notes")},
        "manifest": {"reads": 40, "writes": 12, "batches": 3, "fingerprint": "deadbeefcafe"},
        "orders_cache": {"orders": 312, "age_s": 40, "days": 90},
        "observability": {"test_session": None, "name": None},
    }
    doc.update(over)
    return doc


@pytest.fixture()
def running(here, monkeypatch):
    """The control surface pointed at a well backend on a routed tailnet. Each test bends one
    thing and reads the colour back."""
    state = {"health": health_doc(), "host": "crooks-assistant.taildfb357.ts.net"}
    monkeypatch.setattr(control, "port", lambda: 8000)
    monkeypatch.setattr(control, "read_health", lambda p, fresh=False: state["health"])
    monkeypatch.setattr(control, "tablet_route", lambda p: (state["host"], "" if state["host"] else "Tailscale is not serving port 8000"))
    return state


# ----------------------------------------------------------------------- the four colours


def test_green_is_everything_answering_changes_ready_tablet_routed(running):
    doc = control.status_document()
    assert doc["state"] == "GREEN" and doc["headline"] == "CROOKS — Online"
    assert doc["ok"] is True and doc["degraded"] == [] and doc["issues"] == []
    assert doc["contract"] == control.CONTRACT


def test_blue_is_a_test_session_recording(running):
    running["health"]["observability"] = {"test_session": "ts-20260910-1200-first-hour", "name": "first hour"}
    doc = control.status_document()
    assert doc["state"] == "BLUE" and doc["headline"] == "CROOKS — Testing"
    assert "ts-20260910-1200-first-hour" in doc["why"]
    assert doc["test_session"] == {"active": True, "id": "ts-20260910-1200-first-hour", "name": "first hour"}


def test_amber_is_live_and_read_only(running):
    """The Mac as it normally runs: writes off, so every write family is READ_ONLY. Live, and
    the owner can see at a glance that nothing can be changed from the tablet."""
    running["health"]["writes"] = {"state": "disabled", "detail": "disabled — CROOKS_WRITES_ENABLED=false"}
    running["health"]["families"] = {"order_note": family("READ_ONLY", label="Order notes", detail="changes are off")}
    doc = control.status_document()
    assert doc["state"] == "AMBER" and doc["headline"] == "CROOKS — Read only"
    assert doc["mutation"]["state"] == "read_only" and doc["degraded"] == ["changes"]
    assert "read-only" in doc["why"]


def test_amber_is_also_something_non_essential_being_down(running):
    running["health"]["checks"]["gmail"] = check(False, "the token was revoked")
    doc = control.status_document()
    assert doc["state"] == "AMBER" and doc["headline"] == "CROOKS — Degraded"
    assert "gmail" in doc["degraded"] and "the token was revoked" in doc["why"]
    assert doc["ok"] is True, "degraded is live: the exit code is not an alarm"


def test_amber_is_also_a_tablet_with_no_route(running):
    running["host"] = None
    doc = control.status_document()
    assert doc["state"] == "AMBER" and "tablet route" in doc["degraded"]
    assert doc["tablet"]["host"] == "" and doc["tablet"]["local"] == "http://127.0.0.1:8000/"
    assert "Tailscale is not serving" in doc["why"]


def test_red_is_nothing_answering(running, monkeypatch):
    monkeypatch.setattr(control, "read_health", lambda p, fresh=False: None)
    doc = control.status_document()
    assert doc["state"] == "RED" and doc["headline"] == "CROOKS — Offline"
    assert doc["ok"] is False and "nothing is answering on 127.0.0.1:8000" in doc["why"]
    rows = {r["key"]: r for r in doc["rows"]}
    assert rows["online"]["state"] == "bad" and rows["build"]["value"] == "?"


@pytest.mark.parametrize("name", ["speech", "claude", "shopify"])
def test_red_is_one_of_the_three_it_cannot_work_without(running, name):
    running["health"]["checks"][name] = check(False, "not available")
    doc = control.status_document()
    assert doc["state"] == "RED" and doc["headline"] == "CROOKS — Issue"
    assert doc["issues"] == [name] and doc["ok"] is False


def test_an_issue_is_never_hidden_by_a_test_session(running):
    running["health"]["observability"] = {"test_session": "ts-x", "name": "an hour"}
    running["health"]["checks"]["claude"] = check(False, "the CLI is not on PATH")
    assert control.status_document()["state"] == "RED", "RED beats BLUE"


def test_a_test_session_outranks_something_merely_degraded(running):
    running["health"]["observability"] = {"test_session": "ts-x", "name": "an hour"}
    running["health"]["checks"]["gmail"] = check(False, "revoked")
    doc = control.status_document()
    assert doc["state"] == "BLUE" and "gmail" in doc["degraded"], "BLUE beats AMBER, and still says so"


def test_every_colour_is_reachable_and_no_fifth_one_is(running):
    """The oracle for the roll-up itself: four inputs, four colours, nothing else."""
    seen = set()
    for bend in (lambda: None,
                 lambda: running["health"]["observability"].update({"test_session": "ts-x"}),
                 lambda: running["health"]["checks"].update({"gmail": check(False, "revoked")}),
                 lambda: running["health"]["checks"].update({"claude": check(False, "down")})):
        running["health"] = health_doc()
        bend()
        seen.add(control.status_document()["state"])
    assert seen == set(control.COLOURS)


# ------------------------------------------------------------- mutation readiness, from /health


def test_mutation_readiness_is_read_from_the_capability_families(running):
    """Not from a notion of our own: app/capabilities/families.py states every family with the
    scope named, and /health carries the table."""
    running["health"]["families"] = {
        "order_note": family("READY", label="Order notes"),
        "discount": family("MISSING_SCOPE", label="Discount codes", scope="write_discounts",
                           detail="blocked — Shopify write_discounts scope missing"),
    }
    mutation = control.mutation_readiness(running["health"])
    assert mutation["state"] == "missing_scope" and mutation["source"] == "families"
    assert "write_discounts" in mutation["detail"]
    assert mutation["missing_scope"][0]["label"] == "Discount codes"
    assert mutation["ready"] == ["Order notes"]
    assert control.status_document()["state"] == "AMBER"


def test_a_family_that_is_off_on_this_store_is_not_a_fault(running):
    running["health"]["families"] = {
        "order_note": family("READY", label="Order notes"),
        "credit": family("NOT_SUPPORTED_BY_STORE", label="Store credit", detail="this store does not offer it"),
    }
    mutation = control.mutation_readiness(running["health"])
    assert mutation["state"] == "partial" and mutation["unavailable"][0]["label"] == "Store credit"


def test_readiness_falls_back_to_the_writes_line_on_a_build_with_no_family_table(running):
    running["health"]["families"] = {}
    running["health"]["writes"] = {"state": "ready", "detail": "ready"}
    assert control.mutation_readiness(running["health"])["state"] == "ready"
    assert control.mutation_readiness(running["health"])["source"] == "writes"
    running["health"]["writes"] = {"state": "disabled", "detail": "disabled — CROOKS_WRITES_ENABLED=false"}
    assert control.mutation_readiness(running["health"])["state"] == "read_only"


def test_writes_blocked_by_configuration_is_named_as_blocked(running):
    running["health"]["writes"] = {"state": "blocked", "detail": "blocked — CROOKS_ALLOWED_LOGINS not configured"}
    mutation = control.mutation_readiness(running["health"])
    assert mutation["state"] == "blocked" and "ALLOWED_LOGINS" in mutation["detail"]
    assert control.status_document()["state"] == "AMBER"


# ------------------------------------------------------------------------- the rows


def test_every_row_the_brief_asks_for_is_there_and_in_order(running):
    doc = control.status_document()
    keys = [row["key"] for row in doc["rows"]]
    assert keys == ["online", "build", "backend", "speech", "speaks", "claude", "shopify", "gmail",
                    "orders", "tablet", "mutation", "session", "branch", "known_good"]
    assert all(set(row) == {"key", "label", "state", "value", "detail"} for row in doc["rows"])
    assert all(row["state"] in ("ok", "off", "bad") for row in doc["rows"])
    rows = {row["key"]: row for row in doc["rows"]}
    assert rows["build"]["value"] == "b-2026-09-10-abc"
    assert rows["orders"]["value"] == "312 held, read 40s ago"
    assert rows["tablet"]["value"] == "https://crooks-assistant.taildfb357.ts.net/"
    assert rows["speech"]["value"].startswith("scribe_v2 · ")
    assert rows["branch"]["value"].endswith(control.current_build()["short"])


def test_a_row_the_build_does_not_report_says_so_rather_than_lying(running):
    del running["health"]["checks"]["gmail"]
    del running["health"]["orders_cache"]
    rows = {row["key"]: row for row in control.status_document()["rows"]}
    assert rows["gmail"]["state"] == "off" and "does not report" in rows["gmail"]["detail"]
    assert rows["orders"]["value"] == "cold"


# --------------------------------------------------------------- the last known-good build


def test_there_is_no_known_good_build_until_something_records_one(running):
    doc = control.status_document()
    assert doc["build"]["last_known_good"] is None
    assert doc["rollback"]["available"] is False and doc["rollback"]["safe"] is False
    assert "nothing to go back to" in doc["rollback"]["reason"]
    rows = {row["key"]: row for row in doc["rows"]}
    assert rows["known_good"]["value"] == "none recorded" and "mark-good" in rows["known_good"]["detail"]


def test_marking_the_running_build_good_writes_it_where_only_this_command_writes(running, here):
    doc = control.mark_good_document()
    assert doc["ok"] is True
    record = doc["marked_good"]
    assert record["sha"] == head(here) and record["build"] == "b-2026-09-10-abc"
    assert record["recorded_by"] == "crooks-control mark-good"
    path = control.known_good_path()
    assert path == here / "logs" / "last_known_good.json"
    assert json.loads(path.read_text(encoding="utf-8"))["sha"] == head(here)
    assert path.stat().st_mode & 0o777 == 0o600, "a file about this Mac, read by this Mac"
    assert control.read_known_good()["short"] == head(here)[:10]


def test_a_build_that_is_not_answering_is_never_recorded_as_good(running, monkeypatch):
    monkeypatch.setattr(control, "read_health", lambda p, fresh=False: None)
    doc = control.mark_good_document()
    assert doc["ok"] is False and doc["marked_good"] is None
    assert "not known to be good" in doc["stop"]["reason"]
    assert control.read_known_good() is None


def test_a_build_with_an_essential_down_is_never_recorded_as_good(running):
    running["health"]["checks"]["shopify"] = check(False, "401 from the store")
    doc = control.mark_good_document()
    assert doc["ok"] is False and "shopify is down" in doc["stop"]["reason"]
    assert control.read_known_good() is None


# ------------------------------------------------------------------ the rollback decision


def test_the_rollback_picks_the_last_known_good_build(running, here):
    good = head(here)
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "a build that turned out badly"], cwd=here, check=True)
    doc = control.status_document()
    assert doc["build"]["current"]["sha"] != good
    assert doc["rollback"]["available"] is True and doc["rollback"]["safe"] is True
    assert doc["rollback"]["sha"] == good and doc["rollback"]["short"] == good[:10]
    assert doc["rollback"]["commands"] == [["git", "checkout", good], ["make", "restart"]]
    assert "detached HEAD" in doc["rollback"]["note"]


def test_the_running_build_being_the_good_one_is_not_a_rollback(running, here):
    control.mark_good_document()
    doc = control.status_document()
    assert doc["rollback"]["available"] is False and "IS the last known-good one" in doc["rollback"]["reason"]


def test_a_known_good_commit_that_is_not_in_this_checkout_is_refused(running, here):
    control.write_known_good({"version": 1, "sha": "0" * 40, "short": "0" * 10, "recorded_at": 1.0})
    decision = control.status_document()["rollback"]
    assert decision["available"] is False and "not in this checkout" in decision["reason"]


def test_a_rollback_refuses_a_dirty_tree_and_leaves_the_work_alone(running, here):
    good = head(here)
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "later"], cwd=here, check=True)
    (here / "app.py").write_text("half-finished, mine\n", encoding="utf-8")
    doc = control.rollback_document(yes=True)
    assert doc["ok"] is False and doc["next"] == "blocked"
    assert doc["rollback"]["available"] is True and doc["rollback"]["safe"] is False
    assert "app.py" in doc["rollback"]["reason"] and "Nothing has been thrown away" in doc["rollback"]["reason"]
    assert head(here) != good, "it did not move"
    assert (here / "app.py").read_text(encoding="utf-8") == "half-finished, mine\n"


def test_a_rollback_needs_the_click_even_when_it_is_safe(running, here):
    good = head(here)
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "later"], cwd=here, check=True)
    doc = control.rollback_document(yes=False)
    assert doc["ok"] is False and doc["next"] == "click_to_apply"
    assert doc["rollback"]["safe"] is True and "rollback --yes" in doc["stop"]["reason"]
    assert head(here) != good, "nothing moved without the click"


def test_a_rollback_that_is_clicked_goes_back_and_restarts(running, here, monkeypatch):
    good = head(here)
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "a build that turned out badly"], cwd=here, check=True)
    (here / ".env").write_text("mine\n", encoding="utf-8")
    kicked = []
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda *, check_only, port: kicked.append(port))
    doc = control.rollback_document(yes=True)
    assert doc["ok"] is True and doc["next"] == "done"
    assert head(here) == good and kicked == [8000]
    assert [s["stage"] for s in doc["stages"]] == ["checkout", "restart", "verify"]
    assert doc["build"]["current"]["detached"] is True
    assert (here / ".env").read_text(encoding="utf-8") == "mine\n", "the owner's own file, untouched"


def test_a_rollback_whose_restart_is_refused_says_so_rather_than_claiming_success(running, here, monkeypatch):
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "later"], cwd=here, check=True)

    def refuse(**_kw):
        raise update.Stopped("The services would not restart: launchctl refused")

    monkeypatch.setattr(control.update_module(), "stage_restart", refuse)
    doc = control.rollback_document(yes=True)
    assert doc["ok"] is False and doc["next"] == "restart_by_hand"
    assert doc["stages"][-1]["state"] == "fail" and "launchctl refused" in doc["stop"]["reason"]


def test_the_detached_build_a_rollback_leaves_is_never_itself_marked_good(running, here, monkeypatch):
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "later"], cwd=here, check=True)
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda **kw: None)
    assert control.rollback_document(yes=True)["ok"] is True
    doc = control.mark_good_document()
    assert doc["ok"] is False and "detached HEAD" in doc["stop"]["reason"]


# ---------------------------------------------------------------- the update, on a click


def stub_restart_and_health(monkeypatch, running, *, build: str = "b-after", healthy: bool = True):
    """launchd and /health belong to the Mac. What is being tested here is the order of the
    stages and what the document says about them, so those two are stubbed and everything
    else — git, the fast-forward, the file that records the good build — is real."""
    upd = control.update_module()
    kicked: list[str] = []

    def restart(*, check_only, port):
        kicked.append("restart")
        upd.say(upd.OK, "restart", "kicked (stubbed here; launchd is the Mac's)")

    monkeypatch.setattr(upd, "stage_restart", restart)
    if healthy:
        after = health_doc(build=build)

        def verify(*, check_only, port):
            upd.say(upd.OK, "verify", f"all good · {after['build']}")
            return after

        monkeypatch.setattr(upd, "stage_verify", verify)
        running["health"] = after
    return kicked


def test_the_update_does_not_apply_without_the_click(running, here, monkeypatch):
    candidate = commit_upstream(here)
    stub_restart_and_health(monkeypatch, running)
    doc = control.apply_document(yes=False)
    assert doc["command"] == "apply" and doc["ok"] is False
    assert doc["next"] == "click_to_apply" and doc["stop"]["stage"] == "click"
    assert doc["build"]["candidate"]["sha"] == candidate
    assert doc["click"] == {"label": "Update now", "command": ["crooks-control", "apply", "--yes"], "enabled": True}
    assert head(here) != candidate, "it showed the plan and moved nothing"


def test_the_clicked_update_moves_the_build_verifies_it_and_marks_it_good(running, here, monkeypatch):
    was = head(here)
    candidate = commit_upstream(here)
    kicked = stub_restart_and_health(monkeypatch, running, build="b-after")
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is True and doc["next"] == "done"
    assert head(here) == candidate and kicked == ["restart"]
    assert doc["update"]["moved"] is True and doc["update"]["verified"] is True
    assert doc["build"]["was"]["sha"] == was and doc["build"]["current"]["sha"] == candidate
    assert [s["stage"] for s in doc["stages"]] == ["tablet", "mark"]
    assert doc["tablet"]["url"] == "https://crooks-assistant.taildfb357.ts.net/"
    assert doc["marked_good"]["sha"] == candidate and doc["marked_good"]["build"] == "b-after"
    assert doc["marked_good"]["recorded_by"] == "crooks-control apply"
    assert control.read_known_good()["sha"] == candidate, "and it is on disk, for the next rollback"


def test_a_tablet_with_no_route_is_a_warning_and_not_a_rollback(running, here, monkeypatch):
    """The Mac is well; only the tablet's door is shut. Rolling a good build back for that
    would be worse than saying so — and the colour goes AMBER on the next status either way."""
    candidate = commit_upstream(here)
    running["host"] = None
    stub_restart_and_health(monkeypatch, running)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is True and doc["next"] == "done"
    assert doc["stages"][0] == {"stage": "tablet", "state": "warn", "detail": "Tailscale is not serving port 8000"}
    assert doc["marked_good"]["sha"] == candidate
    assert control.status_document()["state"] == "AMBER"


def test_an_update_with_nothing_to_pull_marks_nothing(running, here, monkeypatch):
    stub_restart_and_health(monkeypatch, running)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is True and doc["next"] == "up_to_date"
    assert doc["update"]["moved"] is False and doc["marked_good"] is None
    assert control.read_known_good() is None, "an update that did nothing proves nothing"


def test_a_health_check_that_does_not_come_back_offers_the_rollback(running, here, monkeypatch):
    """Step 9 failed. The code moved and the backend did not answer, so the document's answer
    is the rollback — to the build that was recorded good before the update."""
    good = head(here)
    control.mark_good_document()
    commit_upstream(here)
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda **kw: None)

    def unhealthy(**_kw):
        raise update.Stopped("The backend did not come back healthy within 90 seconds.")

    monkeypatch.setattr(control.update_module(), "stage_verify", unhealthy)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is False and doc["next"] == "rollback"
    assert doc["stop"]["stage"] == "verify" and "did not come back healthy" in doc["stop"]["reason"]
    assert doc["update"]["moved"] is True and doc["update"]["verified"] is False
    assert doc["rollback"]["safe"] is True and doc["rollback"]["sha"] == good
    assert control.read_known_good()["sha"] == good, "the record still names the build that worked"


def test_an_update_that_never_moved_is_blocked_rather_than_rolled_back(running, here, monkeypatch):
    control.mark_good_document()
    commit_upstream(here)
    (here / "app.py").write_text("mine\n", encoding="utf-8")
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is False and doc["next"] == "blocked"
    assert doc["stop"]["stage"] == "branch" and "app.py" in doc["stop"]["reason"]
    assert (here / "app.py").read_text(encoding="utf-8") == "mine\n"


def test_the_update_runs_the_offline_suite_before_it_restarts(running, here, monkeypatch):
    commit_upstream(here)
    (here / ".venv" / "bin").mkdir(parents=True)
    fake = here / ".venv" / "bin" / "pytest"
    fake.write_text("#!/bin/sh\necho '1550 passed'\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    stub_restart_and_health(monkeypatch, running)
    doc = control.apply_document(yes=True)
    stages = {s["stage"]: s for s in doc["update"]["stages"]}
    assert doc["update"]["tested"] is True and "1550 passed" in stages["tests"]["detail"]
    order = [s["stage"] for s in doc["update"]["stages"]]
    assert order.index("tests") < order.index("restart"), "a build that fails never restarts"


# ------------------------------------------------------------------------- no secrets


TOKEN = "shpat_" + "9f3a" * 8


def test_no_secret_reaches_the_app_even_when_health_quotes_one(running, here, monkeypatch, capsys):
    """A real-looking credential in the environment AND echoed back inside a /health detail —
    which is how it would happen: a client library putting the token in an error message. The
    assertion is over the actual bytes the app would read."""
    monkeypatch.setenv("CROOKS_SHOPIFY_STATIC_TOKEN", TOKEN)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-secret-key-abcdefghijkl")
    running["health"]["checks"]["shopify"] = check(False, f"401 Unauthorized for token {TOKEN}")
    running["health"]["checks"]["gmail"] = check(False, "refresh failed: sk-ant-api03-Aa1Bb2Cc3Dd4Ee5")
    running["health"]["voice"] = {"api_key": "el-secret-key-abcdefghijkl", "voice": "Derek"}
    assert control.main(["status"]) == 1
    out = capsys.readouterr().out
    assert TOKEN not in out and "shpat_" not in out
    assert "el-secret-key-abcdefghijkl" not in out
    assert "sk-ant-api03" not in out
    assert out.count(control.MASK) >= 3, "and it says something was taken out"
    assert "401 Unauthorized for token" in out, "the diagnosis survives; only the credential goes"
    assert json.loads(out)["state"] == "RED"


def test_redaction_leaves_the_identifiers_the_app_needs(running, here, monkeypatch, capsys):
    """A SHA is forty hex characters and a build id is not a secret. A redactor that eats them
    is a control app that cannot tell two builds apart."""
    monkeypatch.setenv("CROOKS_SHOPIFY_STATIC_TOKEN", TOKEN)
    assert control.main(["status"]) == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["build"]["current"]["sha"] == head(here)
    assert doc["build"]["current"]["build"] == "b-2026-09-10-abc"
    assert doc["rows"][0]["value"] == "answering on 127.0.0.1:8000"


def test_a_field_whose_name_says_credential_goes_whatever_is_in_it():
    out = control.redact({"authorization": "Bearer abc", "token": "anything at all",
                          "url": "https://x-access-token:ghp_AbCdEf123456@github.com/o/r.git",
                          "sha": "a" * 40, "detail": "ready"}, secrets=[])
    assert out["authorization"] == control.MASK and out["token"] == control.MASK
    assert "ghp_" not in out["url"] and out["url"].startswith("https://x-access-token:")
    assert out["sha"] == "a" * 40 and out["detail"] == "ready"


def test_the_environment_is_read_for_shapes_not_for_use(monkeypatch):
    monkeypatch.setenv("SOMETHING_SECRET", "a-long-enough-value")
    monkeypatch.setenv("CROOKS_PORT", "8000")
    found = control.environment_secrets()
    assert "a-long-enough-value" in found
    assert "8000" not in found, "a port is not a credential, and a short value is not one either"


# --------------------------------------------------------------------- the buttons


REQUIRED_BUTTONS = {
    "open": "Open CROOKS OS", "restart": "Restart", "update": "Update", "check": "Check for update",
    "tests": "Run tests", "tests_ui": "Run UI tests", "session_start": "Start live recording",
    "session_stop": "Stop recording", "report": "Generate report", "report_open": "Open latest report",
    "logs": "Open logs", "folder": "Open project folder",
}


@pytest.fixture()
def buttons(monkeypatch):
    monkeypatch.setattr(control, "port", lambda: 8000)
    monkeypatch.setattr(control, "tablet_route", lambda p: ("crooks.ts.net", ""))
    return control.actions_document()["actions"]


def test_every_button_the_brief_asks_for_is_there(buttons):
    labels = {action["id"]: action["label"] for action in buttons}
    assert REQUIRED_BUTTONS.items() <= labels.items()
    assert "rollback" in labels, "and the one the update flow needs when health fails"


def test_every_button_runs_something_that_exists(buttons):
    """The point of the list: the app hard-codes no command. So every command here has to be
    real — an existing script, an existing folder, a URL."""
    for action in buttons:
        assert action["kind"] in ("shell", "control", "open_url", "open_path"), action["id"]
        if action["kind"] in ("shell", "control"):
            argv = action["command"]
            assert argv and Path(argv[0]).name in ("python", "python3", "pytest"), action
            for argument in argv[1:]:
                if argument.endswith(".py"):
                    assert Path(argument).is_file(), f"{action['id']} runs {argument}, which is not there"
            assert Path(action["cwd"]).is_dir()
        elif action["kind"] == "open_path":
            assert Path(action["path"]).parent.is_dir(), action["id"]
        else:
            assert action["url"].startswith("http"), action["id"]


def test_the_buttons_that_change_the_mac_ask_first(buttons):
    asks = {action["id"] for action in buttons if action["confirm"]}
    assert asks == {"restart", "update", "rollback"}
    for action in buttons:
        if action["confirm"]:
            assert "?" in action["confirm_text"], action["id"]


def test_no_button_runs_git_or_launchctl_itself(buttons):
    """Everything goes through the scripts that already exist. A button that shelled out to
    git would be a second updater, with its own idea of what is safe."""
    for action in buttons:
        for word in action.get("command", []):
            assert Path(word).name not in ("git", "launchctl", "sudo"), action


# ------------------------------------------------------- the contract the Swift side reads


def test_the_contract_names_every_field_each_document_returns(running, here, monkeypatch):
    """The --json contract test. If a document grows a field, or renames one, and the contract
    is not told, this fails — which is the only way the Swift side cannot silently drift."""
    contract = control.contract_document()
    assert contract["version"] == control.CONTRACT
    envelope_keys = set(contract["envelope_keys"])
    assert envelope_keys == {"contract", "command", "ok", "at"}
    stub_restart_and_health(monkeypatch, running)
    commit_upstream(here)
    documents = {
        "status": control.status_document(),
        "plan": control.plan_document(),
        "actions": control.actions_document(),
        "contract": contract,
        "mark-good": control.mark_good_document(),
        "rollback": control.rollback_document(yes=False),
        "apply": control.apply_document(yes=False),
    }
    for name, doc in documents.items():
        assert set(doc) & envelope_keys == envelope_keys, f"{name} is missing an envelope field"
        assert doc["contract"] == control.CONTRACT and doc["command"] == name
        named = set(contract["documents"][name])
        assert set(doc) - envelope_keys <= named, f"{name} returns {sorted(set(doc) - envelope_keys - named)}, which the contract does not name"
    # And the two the app polls are named exactly, not merely covered.
    for name in ("status", "actions"):
        assert set(documents[name]) - envelope_keys == set(contract["documents"][name])


def test_the_contract_names_the_four_colours_and_the_three_essentials():
    contract = control.contract_document()
    assert set(contract["states"]) == set(control.COLOURS)
    assert all(name in contract["states"]["RED"] for name in control.ESSENTIAL)


def test_the_command_line_prints_one_document_per_subcommand(running, here, capsys):
    for what, expected in (("status", 0), ("actions", 0), ("contract", 0), ("mark-good", 0)):
        assert control.main([what]) == expected, what
        doc = json.loads(capsys.readouterr().out)
        assert doc["command"] == what and doc["contract"] == control.CONTRACT


def test_a_failure_inside_the_control_command_still_prints_a_document(monkeypatch, capsys):
    monkeypatch.setattr(control, "status_document", lambda **kw: 1 / 0)
    assert control.main(["status"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False and doc["command"] == "status"
    assert "ZeroDivisionError" in doc["stop"]["reason"]


def test_nothing_in_crooks_os_calls_the_updater_or_the_control_command():
    """The updater's own docstring: it runs when George types it, and not otherwise. The app
    is a click, which is the same thing; the backend is not."""
    import subprocess as sp

    hits = sp.run(["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.html",
                   "-e", "scripts.update", "-e", "scripts/update.py", "-e", "crooks-update",
                   "-e", "scripts.control", "-e", "crooks-control", "app", "config", "web", "experience"],
                  cwd=PROJECT, capture_output=True, text=True).stdout.strip()
    assert hits == "", f"something inside CROOKS OS reaches the updater:\n{hits}"


def test_only_the_control_command_writes_the_known_good_build():
    import subprocess as sp

    hits = sp.run(["grep", "-rln", "--include=*.py", "--include=*.swift", "--include=*.md",
                    "last_known_good", "app", "config", "web", "scripts", "tests", "experience", "mac"],
                  cwd=PROJECT, capture_output=True, text=True).stdout.split()
    assert sorted(hits) == ["scripts/control.py", "tests/test_control.py"], hits


# --------------------------------------------------------- the Swift side, as text only


SWIFT_DIR = PROJECT / "mac" / "CrooksControl"


def swift_sources() -> str:
    files = sorted(SWIFT_DIR.rglob("*.swift"))
    assert files, "there are no Swift sources to check"
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def swift_documents() -> str:
    """The one file the JSON is decoded in. Every type the app reads is here, which is what
    lets the field scan below mean something."""
    return (SWIFT_DIR / "Sources" / "CrooksControl" / "Documents.swift").read_text(encoding="utf-8")


def test_the_app_is_a_renderer_and_runs_no_command_of_its_own(buttons):
    """It cannot be compiled here, so what CAN be checked is checked: the app knows the name
    of this script and nothing else. No git, no launchctl, no pytest, no curl — every one of
    those would be a second opinion about how to update or restart this Mac."""
    source = swift_sources()
    for forbidden in ("git ", "\"git\"", "launchctl", "pytest", "curl", "tailscale", "uvicorn", "rm -rf"):
        assert forbidden not in source, f"the app reaches for {forbidden!r} itself"
    assert "control.py" in source and "crooks-control" in source


def test_the_app_renders_the_colours_and_rows_this_side_produces(buttons):
    source = swift_sources()
    for colour in control.COLOURS:
        assert f'"{colour}"' in source, colour
    assert f"contract == {control.CONTRACT}" in source or f"contract: {control.CONTRACT}" in source or str(control.CONTRACT) in source
    for action in buttons:
        assert action["kind"] in source, action["kind"]


def test_the_app_does_not_carry_a_credential_or_an_endpoint_of_its_own():
    source = swift_sources()
    assert "sk-ant" not in source and "shpat_" not in source
    assert "https://api." not in source, "the app talks to this Mac and to nothing else"


def test_the_bundle_is_a_menu_bar_app_that_starts_no_window():
    """LSUIElement is what makes it a menu-bar app rather than one with a Dock icon and a
    window: the plist is checked here because nothing else on this machine can."""
    import plistlib

    with open(SWIFT_DIR / "Info.plist", "rb") as handle:
        plist = plistlib.load(handle)
    assert plist["LSUIElement"] is True
    assert plist["CFBundleExecutable"] == "CrooksControl"
    assert plist["CFBundleIdentifier"] == "com.crooks.control"
    assert plist["LSMinimumSystemVersion"] == "13.0"


def test_the_build_script_is_posix_and_refuses_to_run_anywhere_but_the_mac():
    script = SWIFT_DIR / "build.sh"
    assert script.stat().st_mode & 0o111, "it has to be runnable"
    checked = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    text = script.read_text(encoding="utf-8")
    assert "Darwin" in text and "has to run on the Mac" in text
    assert "set -eu" in text, "a build script that carries on after a failure builds nothing"
    assert plistless(text), "the bundle's Info.plist is copied, not written by hand twice"


def plistless(text: str) -> bool:
    return "cp \"$HERE/Info.plist\"" in text


def test_the_package_declares_the_platform_the_app_needs():
    manifest = (SWIFT_DIR / "Package.swift").read_text(encoding="utf-8")
    assert "swift-tools-version:5.9" in manifest
    assert ".macOS(.v13)" in manifest, "MenuBarExtra is macOS 13"
    assert "dependencies" not in manifest, "it depends on nothing it would have to fetch"


def test_the_app_reads_every_document_field_from_the_contract_and_no_other(buttons):
    """Every key the Swift side decodes has to be a key this side prints. Swift's
    convertFromSnakeCase turns last_known_good into lastKnownGood, so the comparison is made
    in that direction."""
    import re

    def camel(name: str) -> str:
        head, *rest = name.split("_")
        return head + "".join(part.capitalize() for part in rest)

    printed = set()
    for document in (control.contract_document()["documents"].values()):
        printed.update(camel(key) for key in document)
    printed.update(camel(key) for key in ("contract", "command", "ok", "at"))
    # Everything /health and the update document carry, which the app also decodes.
    printed.update(camel(key) for key in (
        "sha", "short", "branch", "detached", "subject", "build", "version", "recorded_at",
        "dirty", "blocking", "stops", "available", "safe", "reason", "note", "commands",
        "stage", "state", "detail", "key", "label", "value", "id", "kind", "group",
        "command", "cwd", "url", "path", "confirm", "confirm_text", "why", "actions",
        "behind", "ahead", "fast_forward", "deps", "changed_files", "moved", "tested",
        "restarted", "verified", "stages", "stop", "current", "candidate", "was",
        "active", "name", "host", "local", "port", "issues", "degraded", "rows", "next",
        "state", "headline", "enabled", "documents", "states", "envelope_keys",
        "marked_good", "last_known_good", "local_work", "test_session", "click", "update",
        "tablet", "mutation", "rollback", "check", "at",
    ))
    source = swift_documents()
    # `let x: T` in a Decodable struct is a field the app expects to be there.
    declared = set(re.findall(r"^\s*let ([a-z][A-Za-z0-9]*):", source, flags=re.MULTILINE))
    unknown = {name for name in declared if name not in printed}
    assert unknown == set(), f"the app decodes {sorted(unknown)}, which crooks-control does not print"


def test_a_quiet_run_does_not_silence_the_next_one(here, capsys):
    """The quiet is per run, not for the life of the process. It leaked once — a JSON run in
    one test left the printed lines out of every later one — and the three tests that caught
    it were in another file, which is a bad way to find out."""
    update.run(check=True, quiet=True)
    capsys.readouterr()
    update.stage_deps(["app/routes/turn.py"], check_only=False)
    assert "unchanged" in capsys.readouterr().out
    code, _doc = update.run(check=True, quiet=False)
    assert code == 0 and "crooks-update" in capsys.readouterr().out


def test_the_restart_button_is_the_line_make_restart_runs(buttons):
    """Not the supervisor's command directly, and not an uninstall-and-install: the same script
    `make restart` runs, which restarts what was installed and leaves it installed. That is how
    the backend keeps starting when the machine starts.

    The installer is chosen by platform now — install_launchd.py on the Mac, install_systemd.py
    on the server — so what is checked here is the PAIRING rather than either name: whatever
    `make restart` runs is what the button runs. Hard-coding one of the two names is what this
    test used to do, and it would now pass on one machine and fail on the other while the thing
    it cares about was true on both.
    """
    restart = next(action for action in buttons if action["id"] == "restart")
    makefile = (PROJECT / "Makefile").read_text(encoding="utf-8")
    assert "$(INSTALLER) --restart" in makefile
    assert "INSTALLER := scripts/install_launchd.py" in makefile
    assert "INSTALLER := scripts/install_systemd.py" in makefile

    installer_name = lc.installer_script().name
    assert restart["command"][1].endswith(f"scripts/{installer_name}")
    assert restart["command"][2:] == ["--restart"]

    installer = (PROJECT / "scripts" / installer_name).read_text(encoding="utf-8")
    assert "def restart" in installer
    # It restarts what is already installed; it does not reinstall it.
    assert ("kickstart" if installer_name == "install_launchd.py" else "systemctl") in installer


def test_the_run_tests_button_is_the_offline_suite_make_test_runs(buttons):
    tests = next(action for action in buttons if action["id"] == "tests")
    makefile = (PROJECT / "Makefile").read_text(encoding="utf-8")
    assert 'pytest -q -m "not live"' in makefile
    assert Path(tests["command"][0]).name == "pytest"
    assert tests["command"][1:] == ["-q", "-m", "not live"]
    assert list(update.TEST_COMMAND[1:]) == tests["command"][1:], "and the update runs the same ones"


def test_the_ui_test_button_is_the_command_that_already_exists(buttons):
    ui = next(action for action in buttons if action["id"] == "tests_ui")
    assert ui["command"][1].endswith("scripts/experience.py") and ui["command"][2] == "--ui"
    from scripts import install_commands

    assert install_commands.COMMANDS["crooks-test-ui"] == ("scripts/experience.py", "--ui")


def test_opening_crooks_os_prefers_the_tablet_address_and_falls_back_to_this_mac(monkeypatch):
    monkeypatch.setattr(control, "port", lambda: 8000)
    monkeypatch.setattr(control, "tablet_route", lambda p: ("crooks.ts.net", ""))
    routed = next(a for a in control.actions_document()["actions"] if a["id"] == "open")
    assert routed["url"] == "https://crooks.ts.net/"
    monkeypatch.setattr(control, "tablet_route", lambda p: (None, "not serving"))
    local = next(a for a in control.actions_document()["actions"] if a["id"] == "open")
    assert local["url"] == "http://127.0.0.1:8000/"


def test_a_git_error_quoting_a_token_is_masked_in_the_json_too(here, monkeypatch, capsys):
    """The other door: `crooks-update --json`, typed. A remote URL with a credential in it is
    exactly what a failed fetch quotes back, so that document goes through the same redactor
    the app's documents do."""
    monkeypatch.setenv("GIT_ACCESS_TOKEN", "ghp_" + "b7" * 12)

    def fetch(branch):
        raise update.Stopped("fatal: could not read from https://x:ghp_b7b7b7b7b7b7b7b7b7b7b7b7@github.com/o/r.git")

    monkeypatch.setattr(update, "stage_fetch", fetch)
    assert update.main(["--json"]) == 1
    out = capsys.readouterr().out
    assert "ghp_" not in out and control.MASK in out
    document = json.loads(out)
    assert document["stop"]["stage"] == "fetch" and "could not read from" in document["stop"]["reason"]
