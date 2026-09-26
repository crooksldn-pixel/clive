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
import re
import subprocess
import time
from pathlib import Path

import pytest

from scripts import control, update
from scripts import launch_common as lc
from tests.fake_credentials import (
    anthropic_key,
    credential_url,
    elevenlabs_key,
    github_token,
    shopify_token,
    tailscale_auth_key,
)
from tests.fake_launchd import LaunchdDouble

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


PRINTED_RUNNING = "\tstate = running\n\tpid = 4242\n\tlast exit code = 0\n"
LABELS = ("com.crooks.assistant", "com.crooks.whisper")


@pytest.fixture()
def fake_mac(tmp_path, monkeypatch):
    """A Mac, on a machine that is not one.

    Two login services registered, a launchctl that answers, a checkout with the two files
    preflight insists on, a clock that moves when something sleeps, and /health under the
    test's control. Everything the lifecycle layer reaches for goes through `Machine`, which
    is why substituting one is enough — and what it emphatically does NOT prove is that macOS
    accepts these launchctl invocations, because there is no launchctl here to accept them.
    """
    from scripts import service

    agent_dir = tmp_path / "LaunchAgents"
    agent_dir.mkdir()
    for label in LABELS:
        (agent_dir / f"{label}.plist").write_text("<plist/>", encoding="utf-8")
    root = tmp_path / "mac-checkout"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    clock = {"t": 0.0}
    # launchd, with the two facts launchd holds and the rule that goes with them: only
    # bootstrap loads a job, and kickstart on a job that is not loaded fails. The double this
    # replaced answered 0 to everything, which is why the Stop-then-Start defect could sit
    # here green.
    runner = LaunchdDouble(loaded=LABELS, running=LABELS)
    state = {"health": health_doc(), "port_open": True, "route": ("crooks.ts.net", ""),
             "runner": runner, "double": runner, "agent_dir": agent_dir, "root": root, "clock": clock}

    def sleep(seconds):
        clock["t"] += seconds

    machine = service.Machine(
        runner=runner,
        read_health=lambda fresh=False: state["health"],
        port_open=lambda: state["port_open"] or state["health"] is not None,
        ensure_route=lambda: state["route"],
        is_macos=lambda: True, sleep=sleep, now=lambda: clock["t"], log_dir=tmp_path / "logs",
    )
    state["machine"] = machine
    monkeypatch.setattr(control, "machine_for", lambda p: machine)
    monkeypatch.setattr(control, "launchd_for",
                        lambda m: service.Launchd(m, agent_dir=agent_dir, root=root, uid=501))
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
    # `pad` joined the list in Phase 6, directly under `tablet`, and the pairing is the point:
    # the row above it is the route (the door), this one is the tablet (whether anybody came
    # through it). The old list had only the door and called it "Tablet", which is §16's
    # complaint.
    assert keys == ["online", "build", "backend", "speech", "speaks", "claude", "shopify", "gmail",
                    "orders", "tablet", "pad", "mutation", "session", "branch", "known_good"]
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
    assert doc["rollback"]["commands"][0] == ["git", "checkout", "--detach", good, "--"], \
        "what the document says is what control.checkout actually runs"
    assert "detached HEAD" in doc["rollback"]["note"]


def test_the_rollback_names_the_restart_it_actually_performs(running, here):
    """The rollback's second command said `make restart` — a Terminal line, in a field the app
    draws, describing a step this program performs itself. It never was an instruction the
    owner had to carry out, and since the restart stage became service.restart() it is not even
    the right command: `make restart` is one line of a Makefile, and what runs is the same
    thing the app's own Restart button runs.
    """
    control.mark_good_document()
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "a build that turned out badly"], cwd=here, check=True)
    commands = control.status_document()["rollback"]["commands"]
    assert ["make", "restart"] not in commands, "a document the app draws still names a Makefile target"
    restart = commands[1]
    assert restart[-2:] == ["scripts/control.py", "restart"] or restart[-1] == "restart"
    assert Path(restart[-2]).name == "control.py" and restart[-1] == "restart", \
        "it names the same command the Restart button is"


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
    # "healthy" sits between the two now. Before Phase 6 the mark stage carried both the
    # decision and the evidence for it; splitting them out is what makes it possible to say,
    # in one line of the document, WHY a build was or was not recorded as good.
    assert [s["stage"] for s in doc["stages"]] == ["tablet", "healthy", "mark"]
    assert next(s for s in doc["stages"] if s["stage"] == "healthy")["state"] == "ok"
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


def test_a_health_check_that_does_not_come_back_puts_the_mac_back(running, here, monkeypatch, fake_mac):
    """Step 9 failed: the code moved and the backend did not answer.

    This test used to assert `next == "rollback"` — that the document OFFERED the rollback and
    stopped. That expectation was wrong, and §5.5 is why: the owner of this appliance has no
    Terminal and is looking at a menu bar. A Mac left half-updated with a suggestion attached
    is a broken Mac, and the suggestion is not a recovery. So the update now performs the
    rollback itself and reports what it did — and reports it as a FAILED update, because it
    was one.
    """
    good = head(here)
    control.mark_good_document()
    commit_upstream(here)
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda **kw: None)

    def unhealthy(**_kw):
        raise update.Stopped("The backend did not come back healthy within 90 seconds.")

    monkeypatch.setattr(control.update_module(), "stage_verify", unhealthy)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is False, "an update that had to be undone is not a success"
    assert doc["next"] == "rolled_back"
    assert doc["stop"]["stage"] == "verify" and "did not come back healthy" in doc["stop"]["reason"]
    assert doc["update"]["moved"] is True and doc["update"]["verified"] is False
    assert doc["rollback"]["safe"] is True and doc["rollback"]["sha"] == good
    assert doc["recovery"] == {"attempted": True, "ok": True, "sha": good, "short": good[:10],
                               "restarted": True, "human": f"Update failed. Restored {good[:10]}."}
    assert head(here) == good, "and the checkout really went back, not merely offered to"
    assert [s["stage"] for s in doc["stages"]] == ["restore", "restore_restart"]
    assert fake_mac["runner"].ran("kickstart"), "the restored build was actually restarted"
    assert control.read_known_good()["sha"] == good, "the record still names the build that worked"


def test_the_offer_without_the_doing_is_still_available_but_is_not_the_default(running, here, monkeypatch):
    """`--no-recover` keeps the old behaviour for whoever wants to look before anything moves.
    It is not the default, and the flag says so."""
    good = head(here)
    control.mark_good_document()
    candidate = commit_upstream(here)
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda **kw: None)
    monkeypatch.setattr(control.update_module(), "stage_verify",
                        lambda **_kw: (_ for _ in ()).throw(update.Stopped("The backend did not come back healthy.")))
    doc = control.apply_document(yes=True, run_tests=False, recover=False)
    assert doc["ok"] is False and doc["next"] == "rollback" and doc["recovery"] is None
    assert head(here) == candidate, "nothing moved back"
    assert doc["rollback"]["safe"] is True and doc["rollback"]["sha"] == good


def test_an_update_that_pulls_fine_and_comes_up_broken_is_a_failed_update(running, here, monkeypatch, fake_mac):
    """The §5.5 case in full, and the one a naive updater gets wrong: every command exits 0.
    git fast-forwards, the deps install, the suite passes, launchctl kickstarts, /health
    ANSWERS — and Shopify, which was working ten seconds ago, is now down. Exit codes say
    success. The product is broken. The verdict is taken from the health of the new build
    measured against the health of the old one, and nothing else."""
    good = head(here)
    control.mark_good_document()
    commit_upstream(here)
    broken = health_doc(build="b-broken")
    broken["checks"]["shopify"] = check(False, "ImportError: cannot import name 'Client'")
    upd = control.update_module()
    monkeypatch.setattr(upd, "stage_restart", lambda *, check_only, port: None)

    def verify(*, check_only, port):
        # The new build comes up. It answers. It is broken. Every exit code so far is 0.
        running["health"] = broken
        return broken

    monkeypatch.setattr(upd, "stage_verify", verify)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["update"]["ok"] is True and doc["update"]["verified"] is True, "every command exited 0"
    assert doc["ok"] is False, "and the update still failed, because the product is what failed"
    healthy = next(s for s in doc["stages"] if s["stage"] == "healthy")
    assert healthy["state"] == "fail" and "shopify" in healthy["detail"]
    assert doc["next"] == "rolled_back" and doc["recovery"]["ok"] is True
    assert doc["recovery"]["human"] == f"Update failed. Restored {good[:10]}."
    assert head(here) == good
    assert doc["marked_good"] is None, "a build that broke the store is never recorded as good"


def test_something_that_was_already_down_does_not_trigger_a_rollback(running, here, monkeypatch, fake_mac):
    """The other half of the same rule. Shopify was down before the update and is down after
    it; the update did not do that, and undoing the update will not fix it. Rolling back for
    an outage would be churn with an air of competence."""
    was_down = health_doc()
    was_down["checks"]["shopify"] = check(False, "the store is not answering")
    running["health"] = was_down
    control.write_known_good({"version": 1, "sha": head(here), "short": head(here)[:10], "recorded_at": 1.0})
    candidate = commit_upstream(here)
    upd = control.update_module()
    monkeypatch.setattr(upd, "stage_restart", lambda *, check_only, port: None)
    monkeypatch.setattr(upd, "stage_verify", lambda *, check_only, port: was_down)
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is True and doc["next"] == "done" and doc["recovery"] is None
    assert head(here) == candidate, "the update stands"
    assert next(s for s in doc["stages"] if s["stage"] == "healthy")["state"] == "ok"


def test_a_restore_that_cannot_restart_says_so_rather_than_claiming_it_worked(running, here, monkeypatch, fake_mac):
    """The worst available failure, and the one that must never be reported as a success: the
    files go back and the service does not come up. There is no "Restored" sentence here."""
    good = head(here)
    control.mark_good_document()
    commit_upstream(here)
    monkeypatch.setattr(control.update_module(), "stage_restart", lambda **kw: None)
    monkeypatch.setattr(control.update_module(), "stage_verify",
                        lambda **_kw: (_ for _ in ()).throw(update.Stopped("The backend did not come back healthy.")))
    fake_mac["health"] = None      # nothing answers, before or after the restore
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is False and doc["next"] == "recovery_failed"
    assert doc["recovery"]["ok"] is False and doc["recovery"]["restarted"] is False
    assert "Restored" not in doc["recovery"]["human"]
    assert "did not come back up" in doc["recovery"]["human"]
    assert head(here) == good, "the files did go back; it is the service that did not"


def test_dependencies_that_will_not_install_put_the_code_back_too(running, here, monkeypatch, fake_mac):
    """§5.4's dependency failure. The fast-forward has already happened when pip fails, so the
    code on disk has moved and the running build has not — the same half-updated state a
    failed health check leaves, and it gets the same answer."""
    good = head(here)
    control.mark_good_document()
    commit_upstream(here, path="pyproject.toml", text="[project]\nname='x'\nversion='2'\n")
    upd = control.update_module()
    monkeypatch.setattr(upd, "stage_restart", lambda **kw: pytest.fail("restarted a build whose dependencies are missing"))
    monkeypatch.setattr(upd, "stage_deps", lambda changed, *, check_only: (_ for _ in ()).throw(
        update.Stopped("Installing the dependencies failed:\nERROR: No matching distribution found for av>=13.1")))
    doc = control.apply_document(yes=True, run_tests=False)
    assert doc["ok"] is False and doc["stop"]["stage"] == "deps"
    assert doc["update"]["moved"] is True, "the pull had already happened"
    assert doc["next"] == "rolled_back" and doc["recovery"]["ok"] is True
    assert head(here) == good


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


TOKEN = shopify_token("control-status")
VOICE_KEY = elevenlabs_key("control-status")
MODEL_KEY = anthropic_key("control-status")


def test_no_secret_reaches_the_app_even_when_health_quotes_one(running, here, monkeypatch, capsys):
    """A real-looking credential in the environment AND echoed back inside a /health detail —
    which is how it would happen: a client library putting the token in an error message. The
    assertion is over the actual bytes the app would read."""
    monkeypatch.setenv("CROOKS_SHOPIFY_STATIC_TOKEN", TOKEN)
    monkeypatch.setenv("ELEVENLABS_API_KEY", VOICE_KEY)
    running["health"]["checks"]["shopify"] = check(False, f"401 Unauthorized for token {TOKEN}")
    running["health"]["checks"]["gmail"] = check(False, f"refresh failed: {MODEL_KEY}")
    running["health"]["voice"] = {"api_key": VOICE_KEY, "voice": "Derek"}
    assert control.main(["status"]) == 1
    out = capsys.readouterr().out
    assert TOKEN not in out and "shpat_" not in out
    assert VOICE_KEY not in out
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
                          "url": credential_url(github_token("control-field"), host="github.com", path="/o/r.git"),
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


# Start and Stop were the hole in this list, and the hole was the product defect: with no
# Start button the RED state had nothing to offer but a line of Terminal. "Stop recording"
# became "Stop & analyse" because stopping a session and then leaving the owner to press
# Generate report is three buttons for one intention.
REQUIRED_BUTTONS = {
    "start": "Start", "stop": "Stop",
    "open": "Open CROOKS OS", "restart": "Restart", "update": "Update", "check": "Check for update",
    "tests": "Run tests", "tests_ui": "Run UI tests", "session_start": "Start live recording",
    "session_status": "Recording status", "session_stop": "Stop & analyse",
    "report": "Generate report", "report_open": "Open latest report",
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
    """Stop joins the list; Start deliberately does not. Stopping takes the tablet down and
    the owner may have meant Restart. Starting is what the button says on it, and an appliance
    that asks whether you meant to turn it on is not an appliance."""
    asks = {action["id"] for action in buttons if action["confirm"]}
    assert asks == {"restart", "stop", "update", "rollback"}
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
    """Nothing but this script may WRITE logs/last_known_good.json.

    This used to be checked by asserting that the string "last_known_good" appeared in no file
    but this one and its test. That worked only by luck: the Swift side decoded the field under
    Swift's camelCase spelling, so a grep for the snake_case name missed it.

    Phase 6's Swift core has real tests, and its fixtures are documents captured from this very
    script — which of course contain `"last_known_good": null`, because that is what this
    script prints. Reading the key and naming it in a comment are not writing the file, and an
    assertion that cannot tell the difference would forbid any client from ever mentioning the
    field it is given. So the check is now on the writing: the two functions that touch the
    file live here and nowhere else.
    """
    import subprocess as sp

    for writer in ("write_known_good", "known_good_path"):
        hits = sp.run(["grep", "-rln", "--include=*.py", "--include=*.js", "--include=*.swift",
                       writer, "app", "config", "web", "scripts", "tests", "experience", "mac"],
                      cwd=PROJECT, capture_output=True, text=True).stdout.split()
        assert sorted(hits) == ["scripts/control.py", "tests/test_control.py"], (writer, hits)
    # And nothing inside CROOKS OS itself so much as names the record.
    named = sp.run(["grep", "-rln", "--include=*.py", "--include=*.js", "--include=*.html",
                    "last_known_good", "app", "config", "web", "experience"],
                   cwd=PROJECT, capture_output=True, text=True).stdout.strip()
    assert named == "", f"something inside CROOKS OS reads the known-good record:\n{named}"


# --------------------------------------------------------- the Swift side, as text only


SWIFT_DIR = PROJECT / "mac" / "CrooksControl"


def swift_sources() -> str:
    """The APP's own code: Sources/, not Tests/.

    Phase 6 split this package into a Foundation-only core and a SwiftUI layer, and gave the
    core real tests that run on any machine. Those tests contain, quite deliberately, the very
    strings the scans below forbid the app from carrying: a fake `shpat_` token whose whole
    purpose is to prove the redaction masks it, a `curl: (7) Connection refused` that the
    humanising test turns into a sentence a shopkeeper can act on, and the real actions
    document — captured from this script — with `pytest` in it. Scanning a test that proves a
    token is hidden and calling it a leak is the assertion measuring the opposite of what it
    means. These claims have always been about what the APP reaches for, so that is what is
    scanned.
    """
    files = sorted((SWIFT_DIR / "Sources").rglob("*.swift"))
    assert files, "there are no Swift sources to check"
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def swift_documents() -> str:
    """The files the JSON is decoded in. Phase 5 had one, Documents.swift, beside the views;
    Phase 6 has three, in the Foundation-only core where they can be tested."""
    base = SWIFT_DIR / "Sources" / "CrooksControlCore"
    names = ("StatusDocument.swift", "UpdateDocument.swift", "ActionsDocument.swift")
    return "\n".join((base / name).read_text(encoding="utf-8") for name in names)


def test_the_app_is_a_renderer_and_runs_no_command_of_its_own(buttons):
    """It cannot be compiled here, so what CAN be checked is checked: the app runs this script
    and the commands this script names, and nothing of its own.

    Phase 5 checked that by forbidding the words "git", "launchctl", "curl" and so on anywhere
    in the Swift. That proxy stopped telling the truth the moment the app grew prose about why
    it does NOT trust those things — "`launchctl kickstart` returns 0 the moment launchd
    accepts the job" is the comment above the rule that stops STARTING becoming ONLINE — and a
    table that turns "not a git repository" into a sentence. Both are the app refusing to have
    an opinion of its own, and the old assertion called them the opposite.

    So this now checks the thing the words were a proxy for: how many processes the app can
    start at all, and what it is allowed to point them at.
    """
    import re

    source = swift_sources()
    assert source.count("Process()") == 2, \
        "two, and only two: the control script, and a button the control script named"
    launches = re.findall(r"executableURL = (.+)$", source, flags=re.MULTILINE)
    assert launches == ["python", "URL(fileURLWithPath: first)"], launches
    # `first` is argv[0] out of the actions document. CommandGuard refuses a shell there, so a
    # tampered document cannot turn the renderer into an execution surface.
    assert "CommandGuard.refuse" in source
    assert "control.py" in source and "crooks-control" in source
    # No second opinion about how to update or restart this Mac, as a command.
    for forbidden in ('"git"', '"launchctl"', '"pytest"', '"curl"', '"tailscale"', "rm -rf"):
        assert forbidden not in source, f"the app reaches for {forbidden} itself"


def test_the_app_renders_the_colours_and_rows_this_side_produces(buttons):
    source = swift_sources()
    for colour in control.COLOURS:
        assert f'"{colour}"' in source, colour
    assert f"contract == {control.CONTRACT}" in source or f"contract: {control.CONTRACT}" in source or str(control.CONTRACT) in source
    for action in buttons:
        assert action["kind"] in source, action["kind"]


def test_the_app_does_not_carry_a_credential_or_an_endpoint_of_its_own():
    """Phase 5 forbade the literals "sk-ant" and "shpat_" anywhere in the Swift.

    Phase 6's core redacts on its own side as well as trusting this one to — because the app
    also shows text this script never saw, such as a button's stderr — and to redact a token
    it has to know what a token's prefix looks like. Those are the same prefixes SECRET_SHAPES
    uses, deliberately, so the two lists cannot drift apart. The old assertion would have made
    the app unable to hide a credential in order to prove it was not carrying one.

    So this asserts what was always meant: not the prefixes, but an actual credential-shaped
    string — a prefix WITH a value after it. SECRET_SHAPES is the judge, so this side and that
    side agree on the definition.
    """
    source = swift_sources()
    found = control.SECRET_SHAPES.search(source)
    assert found is None, f"the app carries something credential-shaped: {found and found.group(0)[:12]}…"
    assert "https://api." not in source, "the app talks to this Mac and to nothing else"


def test_the_bundle_is_a_control_centre_that_opens_a_window():
    """Phase 5's app was a menu-bar accessory: LSUIElement, no Dock icon, no window, and this
    test asserted exactly that.

    §5 asks for a control centre whose first viewport answers five questions at a glance —
    is CROOKS OS running, is the tablet connected, are services healthy, what version, is a
    test session on. A panel hanging off the menu bar has neither the room for that nor the
    permanence: it closes when you look away, and the whole product promise is that you turn
    the Mac on and CROOKS Control is simply there. So Phase 6 made it a window that opens at
    login, with a line in the menu bar for the glance when something else is in front of it.

    The old expectation was right for the old product and wrong for this one.
    """
    import plistlib

    with open(SWIFT_DIR / "Info.plist", "rb") as handle:
        plist = plistlib.load(handle)
    assert "LSUIElement" not in plist, "a control centre has a window and a Dock icon"
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
    """Phase 5 asserted `"dependencies" not in manifest`, meaning "it fetches nothing".

    Phase 6 splits the package into a Foundation-only core — every decision the app makes,
    with tests that run on any machine — and the SwiftUI layer that draws it. The SwiftUI
    target therefore has a TARGET dependency on the core, which is local and fetches nothing,
    and the word now appears in the manifest. The claim the old assertion was making is said
    precisely instead: no remote packages.
    """
    manifest = (SWIFT_DIR / "Package.swift").read_text(encoding="utf-8")
    assert "swift-tools-version:5.9" in manifest
    assert ".macOS(.v13)" in manifest, "MenuBarExtra is macOS 13"
    assert ".package(" not in manifest, "it depends on nothing it would have to fetch"
    assert "CrooksControlCore" in manifest, "the decisions live in a target that builds anywhere"
    assert "#if os(macOS)" in manifest, \
        "the SwiftUI target is declared only where it can be built, so the core's tests run elsewhere"


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
    #
    # The pattern used to be `^\s*let ` — no `public`. Phase 6 moved these types into a library
    # target, where every field is `public let`, and the old pattern quietly matched NOTHING:
    # the test went on passing while measuring an empty set. That is the worst way for a test
    # to fail, so the count is asserted below as well.
    declared = set(re.findall(r"^\s*(?:public )?let ([a-z][A-Za-z0-9]*):", source, flags=re.MULTILINE))
    assert len(declared) > 40, f"the field scan found only {sorted(declared)} — it has stopped measuring"

    # Named differently on the Swift side, via CodingKeys, and for a reason each.
    renamed = {
        "colour": "state, renamed because the app has its own `state` (the lifecycle) and two "
                  "things called state in one file is how the wrong one gets drawn",
        "health": "a row's state, same reason",
        "envelope": "not a key at all: the {contract, command, ok, at} four, boxed into one "
                    "value so every document carries them the same way",
    }
    # Fields the app reads that this script does not print YET. Each is optional on the Swift
    # side and has an honest fallback, so a control script without them loses a line rather
    # than blanking the app. They are listed here so that adding one to control.py is a
    # deliberate act and not a surprise. See mac/CrooksControl/README.md.
    forward = {
        "service": "the process truth: {state, detail, managed, pid, healthy}",
        "managed": "part of `service`",
        "pid": "part of `service` — shown in Developer Mode and never read as 'it is up'",
        "healthy": "part of `service` — /health answered; the only part that decides anything",
        "pad": "the CROOKS Pad's own check-in: {seen_at, agent, address, build}",
        "seenAt": "part of `pad`",
        "agent": "part of `pad`",
        "address": "part of `pad`",
        "uptimeS": "uptime as a number; the `online` row carries it as prose and the app "
                   "will not parse a duration back out of an English sentence",
        "needsPlan": "`needs_plan`, which actions_document() already sends on the update "
                     "button but contract_document() does not describe",
    }
    unknown = {name for name in declared if name not in printed and name not in renamed and name not in forward}
    assert unknown == set(), f"the app decodes {sorted(unknown)}, which crooks-control does not print"

    # And the other half of the same promise, in the other direction: NO field this script
    # prints may be required on the Swift side either. One renamed or dropped key in Python
    # would otherwise leave a Mac drawing nothing at all and saying only that it could not read
    # the answer — a worse failure than a missing line.
    #
    # The check is on the read, not on the type. `let agent: String` with a default is exactly
    # as tolerant as `let agent: String?`, and reads better; what matters is that absence goes
    # through the helpers rather than throwing.
    exempt = {"contract"} | set(renamed)  # `contract` is required on purpose: a document
    #                                       without a version is not this script's document.
    for name in sorted(declared - exempt):
        assert f"box.value(.{name}," in source or f"box.maybe(.{name})" in source, \
            f"{name} is decoded strictly, so one absent key would blank the whole app"


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


def test_the_restart_button_and_make_restart_are_one_mechanism_on_each_platform(buttons):
    """Two histories meet here, and both of their instincts survive.

    The Linux migration made `make restart` dispatch by platform and asserted the button ran
    the same line. Phase 6 made the button a "control" action, because a "shell" button can
    only show output and `make restart` printed launchctl's exit code — a backend that dies
    on import kickstarts perfectly well. What is asserted now:

      * the button runs `crooks-control restart`, on both platforms;
      * `make restart` runs `$(INSTALLER) --restart`, chosen by platform;
      * each installer's --restart, and control.py's restart document, go through the
        platform's lifecycle module — service.restart() on the Mac, service_linux.restart()
        on the server — and each reads /health back.

    So there is one mechanism per platform, and no button that can leave the machine in a
    state the typed command would not.
    """
    restart = next(action for action in buttons if action["id"] == "restart")
    assert restart["kind"] == "control"
    assert restart["command"][1].endswith("scripts/control.py") and restart["command"][2:] == ["restart"]

    makefile = (PROJECT / "Makefile").read_text(encoding="utf-8")
    assert "$(INSTALLER) --restart" in makefile
    assert "INSTALLER := scripts/install_launchd.py" in makefile
    assert "INSTALLER := scripts/install_systemd.py" in makefile

    launchd_installer = (PROJECT / "scripts" / "install_launchd.py").read_text(encoding="utf-8")
    assert "def restart" in launchd_installer and "kickstart" in launchd_installer
    assert "svc.restart(" in launchd_installer, "make restart on the Mac goes through the one mechanism"
    systemd_installer = (PROJECT / "scripts" / "install_systemd.py").read_text(encoding="utf-8")
    assert "def restart" in systemd_installer and "systemctl" in systemd_installer
    assert "svc.restart(" in systemd_installer, "make restart on the server goes through the one mechanism"

    control_src = (PROJECT / "scripts" / "control.py").read_text(encoding="utf-8")
    assert re.search(r"service_module\([^)]*\)\.restart\(", control_src)
    # And what supervises here is what the confirmation names, whichever platform this is.
    assert lc.service_labels()[0] in restart["confirm_text"]


def test_start_and_stop_are_the_buttons_that_did_not_exist(buttons):
    """§5.2, which is the whole reason for this phase's operations work. Before it, the
    actions document had thirteen entries and neither of these was one of them — so a Mac
    with nothing running had no button that could change that, and the status text said to
    open a Terminal and type `make up`."""
    by_id = {action["id"]: action for action in buttons}
    assert by_id["start"]["kind"] == "control" and by_id["start"]["command"][2:] == ["start"]
    assert by_id["stop"]["kind"] == "control" and by_id["stop"]["command"][2:] == ["stop"]
    assert by_id["start"]["confirm"] is False
    for action in (by_id["start"], by_id["stop"]):
        assert "make up" not in action["why"] and "Terminal" not in action["why"]


def test_no_button_and_no_status_line_tells_the_owner_to_open_a_terminal(buttons, running, monkeypatch):
    """The defect, asserted directly. With nothing answering at all — the state in which the
    old text appeared — no sentence the app would draw may name `make up` or `make install`."""
    monkeypatch.setattr(control, "read_health", lambda p, fresh=False: None)
    doc = control.status_document()
    drawn = json.dumps({"why": doc["why"], "rows": doc["rows"], "lifecycle": doc["lifecycle"],
                        "actions": buttons})
    # `make restart` appears in one button's "why", describing what that button is the same
    # thing as. That is a description of a button, not an instruction to go and type it, and
    # it is the distinction §5.2 draws: the RECOVERY PATH may not be a command line.
    for banned in ("make up", "make install", "open Terminal", "in Terminal"):
        assert banned not in drawn, f"a document the app draws still says {banned!r}"
    assert "Press Start" in doc["why"]


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
    token = github_token("update-fetch")
    monkeypatch.setenv("GIT_ACCESS_TOKEN", token)

    def fetch(branch):
        raise update.Stopped("fatal: could not read from "
                             + credential_url(token, user="x", host="github.com", path="/o/r.git"))

    monkeypatch.setattr(update, "stage_fetch", fetch)
    assert update.main(["--json"]) == 1
    out = capsys.readouterr().out
    assert "ghp_" not in out and control.MASK in out
    document = json.loads(out)
    assert document["stop"]["stage"] == "fetch" and "could not read from" in document["stop"]["reason"]


# ------------------------------------------------------- is the tablet there (§16)


def test_a_build_that_reports_no_heartbeat_is_not_a_tablet_that_has_gone_away(running):
    """Ignorance is not evidence. A backend that does not report a heartbeat leaves the row
    UNKNOWN and the colour alone — an unknown drawn as a red light is how a status screen
    teaches its owner to stop reading it."""
    doc = control.status_document()
    assert doc["pad"] == {"known": False, "alive": None, "age_s": None, "app": "", "version": "",
                          "build": "", "source": "absent",
                          "detail": "this build does not say whether the tablet has been heard from; the route being open is not a heartbeat"}
    assert doc["state"] == "GREEN" and "tablet" not in doc["degraded"]
    rows = {row["key"]: row for row in doc["rows"]}
    assert rows["pad"]["state"] == "off" and rows["pad"]["value"] == "unknown"


def test_a_tablet_heard_from_a_moment_ago_is_here(running):
    running["health"]["pad"] = {"last_seen_s": 4.0, "app": "CROOKS Pad", "version": "1.0", "build": "b-2"}
    doc = control.status_document()
    assert doc["pad"]["known"] is True and doc["pad"]["alive"] is True and doc["pad"]["age_s"] == 4.0
    assert doc["state"] == "GREEN"
    rows = {row["key"]: row for row in doc["rows"]}
    assert rows["pad"]["state"] == "ok" and rows["pad"]["value"] == "here · CROOKS Pad"
    assert "last heard from 4s ago" in rows["pad"]["detail"]


def test_a_routed_tailnet_with_a_silent_tablet_is_not_green(running):
    """§16's whole point. Tailscale is serving the address, the Tablet row is a tick, and the
    tablet itself has been off since yesterday. The route is the door; it is not the tablet,
    and until Phase 6 this side had no way to tell the owner which of the two it was reading."""
    running["health"]["pad"] = {"last_seen_s": 8 * 3600}
    doc = control.status_document()
    assert doc["tablet"]["host"], "the route is up"
    assert doc["state"] == "AMBER" and doc["degraded"] == ["tablet"]
    assert "CROOKS Pad not heard from for 8.0h" in doc["why"]
    rows = {row["key"]: row for row in doc["rows"]}
    assert rows["tablet"]["state"] == "ok" and rows["pad"]["state"] == "bad"


@pytest.mark.parametrize(("field", "alive"), [
    ({"last_seen_s": 10}, True),
    ({"age_s": 10}, True),
    ({"seen_s_ago": 10}, True),
    ({"last_seen_s": 9999}, False),
    ({"last_seen_at": None}, None),
    ({"connected": True, "last_seen_s": 9999}, True),
    ({"connected": False, "last_seen_s": 1}, False),
    ({"app": "CROOKS Pad"}, None),
])
def test_the_heartbeat_is_read_from_whichever_shape_the_backend_chose(field, alive):
    """This side and the backend side of Phase 6 were written at the same time, so the shape
    had to be agreed without either waiting for the other: an age under any of three names, an
    instant under either of two, and an explicit verdict from the backend outranking our own
    arithmetic, because the backend is the one holding the socket."""
    if "last_seen_at" in field:
        field, alive = {"last_seen_at": time.time() - 5}, True
    assert control.pad_status({"pad": field})["alive"] is alive


# CONTRACT 1: the `pad` block on GET /health, as the backend's PadRegistry.status() is settled
# to emit it. Said exactly: this fixture is written from the SETTLED CONTRACT, because the
# backend half of Phase 6 is not in this checkout — app/observability/pad.py is not here to be
# read. So what it proves is that this layer reads the agreed names, not that the backend
# sends them. It is still worth having: every key is one this layer must not have invented for
# itself, and the old spellings it used instead (`app`, `client`) are not among them.
#
# The other half of that seam — that PadRegistry.status() really does print these — can only
# be checked where both halves are in one tree, which is the merge. It is the one claim in
# this file that this machine cannot close.
B_PAD_BLOCK = {
    "connected": True, "state": "connected", "detail": "heartbeat 3s ago",
    "last_seen": 1_760_000_000.0, "last_seen_s": 3.0, "last_seen_text": "3 seconds ago",
    "app_version": "1.4.0", "device_model": "SM-T290", "os_version": "Android 11",
    "webview": "Chrome/120", "showing_crooks": True, "heartbeats": 412,
    "clock_skew_s": 0.4, "interval_s": 20, "stale_after_s": 60,
    "events": {"accepted": 12, "collapsed": 3, "rejected": 0, "rate_limited": 0},
}


def test_the_pad_block_the_backend_really_prints_is_read_by_its_real_names():
    """CONTRACT 1, this side of it. The backend's PadRegistry.status() is the authoritative
    wire shape and its key names are what this layer reads FIRST; the tolerant spellings
    underneath were only ever there because the two halves of Phase 6 were written at once.

    The one that was actually wrong: the backend calls the pad's version `app_version`, and
    this read `app` and then `client`. Against every real backend the row that says which
    CROOKS Pad is on the other end came out blank — and a blank is indistinguishable from a
    pad that has not said.
    """
    out = control.pad_status({"pad": dict(B_PAD_BLOCK)})
    assert out["known"] is True and out["alive"] is True
    assert out["age_s"] == 3.0, "`last_seen_s` is the backend's name for the age"
    assert out["app"] == "1.4.0", "`app_version` is what fills `app`"
    assert out["source"] == "pad"
    assert "3s ago" in out["detail"]


def test_the_pad_status_this_layer_prints_invents_no_key_and_drops_none():
    """The other half of the layering. B -> A -> D: the app decodes THIS function's key names
    and not the backend's, so the set is fixed, it is the same whatever the backend said, and
    `crooks-control contract` is where the app is told about it."""
    seen = control.pad_status({"pad": dict(B_PAD_BLOCK)})
    keys = {"known", "alive", "age_s", "app", "version", "build", "source", "detail"}
    assert set(seen) == keys
    assert set(control.pad_status(None)) == keys, "an absent pad has the same shape as a present one"
    named = control.contract_document()["documents"]["status"]["pad"]
    for key in sorted(keys):
        assert key in named, f"the contract does not tell the app about `{key}`"


def test_the_backend_still_spells_the_names_this_layer_reads():
    """CONTRACT 1's A->B seam, as far as one tree can close it.

    B_PAD_BLOCK above is written from the settled contract, and a fixture written from a
    document proves the document. The product claim underneath it is that the backend's
    PadRegistry really prints these names — and that can only be checked where both halves
    are in one tree. The moment app/observability/pad.py is in this checkout it is checked,
    and until then this says out loud that it has not been, rather than passing quietly and
    leaving the seam looking closed.

    A name check and not an API call, deliberately: this side must not grow an opinion about
    how the backend is constructed, only about what it is agreed to say.
    """
    backend = PROJECT / "app" / "observability" / "pad.py"
    if not backend.exists():
        pytest.skip("the backend half of Phase 6 is not in this checkout; this seam closes at the merge")
    source = backend.read_text(encoding="utf-8")
    for name in ("connected", "last_seen_s", "last_seen", "app_version", "stale_after_s"):
        assert f'"{name}"' in source or f"'{name}'" in source, \
            f"the backend no longer spells `{name}`, which scripts/control.py reads as a primary"


def test_the_backends_own_staleness_window_wins_over_this_sides_guess():
    """`stale_after_s` is the backend's number and the backend is the one holding the socket.
    Where it says so, this side does not keep a second opinion about when a pad is stale — the
    two disagreeing is how the Mac and the app end up drawing different colours."""
    silent = dict(B_PAD_BLOCK, stale_after_s=60, last_seen_s=90.0)
    silent.pop("connected")
    assert control.pad_status({"pad": silent})["alive"] is False, "90s is stale at the backend's 60"
    assert control.pad_status({"pad": dict(silent, stale_after_s=600)})["alive"] is True
    # And with no number from the backend, this side's own window still applies.
    assert control.pad_status({"pad": {"last_seen_s": 90.0}})["alive"] is True
    assert control.pad_status({"pad": {"last_seen_s": 9999.0}})["alive"] is False


def test_the_tablet_key_is_read_too_so_neither_side_had_to_wait_for_the_other():
    assert control.pad_status({"tablet": {"last_seen_s": 2}})["source"] == "tablet"
    assert control.pad_status({"pad": {"last_seen_s": 2}})["source"] == "pad"
    assert control.pad_status({"pad": {}, "tablet": {"last_seen_s": 2}})["source"] == "tablet", "an empty one is not an answer"
    assert control.pad_status(None)["known"] is False


# --------------------------------------------------------- start, stop, restart


def test_start_is_a_document_the_app_can_draw(running, here, fake_mac):
    double = fake_mac["double"]
    fake_mac["health"] = None
    fake_mac["port_open"] = False
    # Registered, and not a process until something kicks it. The two facts come apart, and
    # the whole lifecycle verdict turns on which one is being read.
    double.running.clear()
    double.on_kickstart = lambda _label: fake_mac.update(health=health_doc(), port_open=True)

    doc = control.start_document(wait_s=30.0)
    assert doc["command"] == "start" and doc["ok"] is True and doc["contract"] == control.CONTRACT
    assert doc["human"] == "CROOKS OS is running." and doc["problem"] is None
    assert doc["lifecycle"]["crooks_os"] == "running" and doc["lifecycle"]["supervised"] is True
    assert doc["before"]["crooks_os"] == "stopped"
    assert len(double.ran("kickstart")) == 2, "the backend and whisper-server"


def test_stop_is_a_document_and_says_it_will_come_back_at_login(running, here, fake_mac):
    fake_mac["double"].on_bootout = lambda _label: fake_mac.update(health=None, port_open=False)
    doc = control.stop_document()
    assert doc["command"] == "stop" and doc["ok"] is True and doc["next"] == "stopped"
    assert doc["lifecycle"]["crooks_os"] == "stopped"
    assert "starts again the next time this Mac is logged in" in doc["note"]


# ------------------------------------------- the update's own restart (§5.2, no Terminal)


@pytest.fixture()
def update_mac(fake_mac, monkeypatch):
    """`crooks-update`'s restart stage pointed at the same Mac the app's buttons use, so the
    typed command and the button cannot take different paths through this."""
    from scripts import service

    machine = fake_mac["machine"]
    launchd = service.Launchd(machine, agent_dir=fake_mac["agent_dir"], root=fake_mac["root"], uid=501)
    monkeypatch.setattr(update, "mac_for", lambda _port: (machine, launchd))
    return fake_mac


def test_an_update_restarts_a_mac_whose_services_launchd_does_not_hold(running, here, update_mac):
    """A3. The restart stage kickstarted the two agents directly. On a Mac where launchd does
    not have them loaded — which is every Mac that has ever been stopped, and every Mac that
    has never been installed — a kickstart does nothing at all and exits 3.

    service.py can register and start them now, so the update does that rather than stopping
    to tell the owner to open a Terminal.
    """
    double = update_mac["double"]
    double.loaded.clear()
    double.running.clear()
    update_mac["health"] = None
    update_mac["port_open"] = False
    double.on_kickstart = lambda _label: update_mac.update(health=health_doc(), port_open=True)

    update.stage_restart(check_only=False, port=8000)   # raises Stopped if it cannot

    assert double.loaded == set(LABELS), "it registered them itself"
    assert double.ran("kickstart"), "and then started them"
    assert update_mac["health"] is not None, "and read the backend back up"


def test_a_restart_the_update_cannot_do_names_a_button_and_never_a_command(running, here, update_mac):
    """A3's sentence. `raise Stopped("… run `make install` once …")` is the whole of §5.2's
    no-Terminal claim failing: the status screen was clean and the update was not, and the
    update is exactly where an owner ends up with his code moved and his Mac not running.
    """
    double = update_mac["double"]
    double.absent = True          # there is no launchctl on this Mac at all
    update_mac["health"] = None
    update_mac["port_open"] = False

    with pytest.raises(update.Stopped) as refused:
        update.stage_restart(check_only=False, port=8000)

    said = str(refused.value)
    for banned in ("make install", "make up", "make restart", "make venv", "Terminal", "launchctl "):
        assert banned not in said, f"the update still tells the owner {banned!r}"
    assert "CROOKS Control" in said, "it names what to press instead"
    assert "Your code IS updated" in said, "and still says what state the Mac was left in"


def test_no_stop_the_update_document_carries_tells_the_owner_to_type_anything(running, here, update_mac, monkeypatch):
    """The same sentence where the app actually reads it: apply_document carries a Stopped
    straight into `stop.reason`, which the app draws."""
    good = head(here)
    control.mark_good_document()
    commit_upstream(here)
    update_mac["double"].absent = True
    update_mac["health"] = None
    update_mac["port_open"] = False

    doc = control.apply_document(yes=True, run_tests=False, recover=False)
    assert doc["ok"] is False and doc["stop"]["stage"] == "restart"
    for banned in ("make install", "make up", "make restart", "Terminal"):
        assert banned not in json.dumps(doc), f"the apply document still says {banned!r}"
    assert "CROOKS Control" in doc["stop"]["reason"]
    assert good  # the known-good record is what the rollback button would use


def test_the_updater_names_no_shell_command_for_a_failed_restart(running):
    """Read as source, because the string that failed §5.2 was a literal in this file."""
    source = (PROJECT / "scripts" / "update.py").read_text(encoding="utf-8")
    assert "make install" not in source


def test_restart_reports_a_verdict_rather_than_an_exit_code(running, here, fake_mac):
    doc = control.restart_document(wait_s=10.0)
    assert doc["command"] == "restart" and doc["ok"] is True
    assert doc["human"] == "CROOKS OS restarted and is running."
    assert [s["stage"] for s in doc["stages"]] == ["check", "restart", "route", "verify"]
    assert "all good" in next(s for s in doc["stages"] if s["stage"] == "verify")["detail"]


def test_a_start_that_never_becomes_ready_is_a_failure_with_an_expansion(running, here, fake_mac, capsys):
    fake_mac["health"] = None
    fake_mac["port_open"] = False
    assert control.main(["start", "--wait", "5"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False and doc["command"] == "start"
    assert doc["problem"]["human"] == "CROOKS OS started but never became ready."
    assert "127.0.0.1" not in doc["problem"]["human"], "the owner's half carries no address"
    assert "127.0.0.1" in doc["problem"]["developer"], "and the developer's half does"


def test_the_lifecycle_of_a_running_mac_is_reported_on_every_status(running, here, fake_mac):
    doc = control.status_document()
    assert doc["lifecycle"]["state"] == "RUNNING" and doc["lifecycle"]["healthy"] is True
    assert "Closing this window will not stop it" in doc["lifecycle"]["human"]
    assert "does not stop CROOKS OS" in doc["lifecycle"]["window"]


def test_a_backend_run_from_a_terminal_window_is_named_as_one_on_the_status(running, here, fake_mac):
    """And the difference is the one §5.3 asks for: this one DOES stop when its window is
    closed, and an owner told otherwise will close it and wonder why the tablet died."""
    # Loaded, and no pid: `make up` ran it as a child of a Terminal, so nothing launchd holds
    # is the process answering on the port.
    fake_mac["double"].running.clear()
    doc = control.status_document()
    assert doc["lifecycle"]["state"] == "RUNNING_WINDOW" and doc["lifecycle"]["supervised"] is False
    assert "WILL stop it" in doc["lifecycle"]["human"]
    assert doc["lifecycle"]["crooks_os"] == "running", "it is still running; it is only unsupervised"


def test_no_secret_reaches_the_app_through_a_lifecycle_document(running, here, fake_mac, monkeypatch, capsys):
    """The redaction promise, extended to the documents that did not exist when it was made.
    A Tailscale error quoting an auth key is exactly the shape of thing that lands in a
    stage's detail, and a stage's detail is drawn."""
    key = tailscale_auth_key("lifecycle-restart")
    monkeypatch.setenv("TAILSCALE_AUTH_TOKEN", key)
    fake_mac["route"] = (None, f"tailscale serve failed: the auth key {key} has expired")
    control.main(["restart", "--wait", "5"])
    out = capsys.readouterr().out
    assert key not in out and control.MASK in out
    assert "the auth key" in out, "the diagnosis survives; only the credential goes"


# --------------------------------------------------------- the contract, version two


V1_FIELDS = {
    "status": {"state", "headline", "why", "issues", "degraded", "rows", "build", "tablet",
               "mutation", "test_session", "local_work", "rollback", "port"},
    "plan": {"update", "click", "build", "local_work", "rollback", "next", "stop"},
    "apply": {"update", "stages", "tablet", "marked_good", "build", "local_work", "rollback",
              "click", "stop", "next"},
    "rollback": {"rollback", "stages", "build", "stop", "next"},
    "mark-good": {"marked_good", "build", "stop", "next"},
    "actions": {"actions"},
    "contract": {"version", "envelope_keys", "documents", "states"},
}


def test_version_two_is_additive_and_took_nothing_away():
    """The reason 1 is still in `compatible_clients`. Every field a version-1 client decoded
    is still printed, unchanged, so a client willing to accept the number renders correctly.
    If a field is ever REMOVED or renamed this fails, the version stops being additive, and
    the Swift side has to move in the same change rather than afterwards."""
    documents = control.contract_document()["documents"]
    for name, fields in V1_FIELDS.items():
        missing = fields - set(documents[name])
        assert missing == set(), f"{name} no longer prints {sorted(missing)}, which version 1 decoded"
    assert control.CONTRACT == 2 and list(control.COMPATIBLE_CLIENTS) == [1, 2]


# What the Swift side declares, located by content rather than by filename — the app's file
# layout is the app's business and has already changed once.
SWIFT_UNDERSTOOD = re.compile(r"static let understood\s*(?::\s*Int\s*)?=\s*(\d+)")
SWIFT_READABLE = re.compile(r"static let readable\s*(?::[^=]+)?=\s*(?:Set\()?\[([0-9,\s]+)\]")


def test_the_app_and_this_side_agree_on_the_document_version():
    """A5, and CONTRACT 2 in one place. The test this replaces asserted

        int(declared) in control.COMPATIBLE_CLIENTS

    which is satisfied by an app declaring 1 — and an app declaring 1 REFUSES every document
    this side prints, because the documents are marked 2. So the gate stayed green for the
    whole time the product was unusable, which is the precise failure mode a contract test
    exists to prevent: it measured a set membership instead of the agreement.

    Both halves now, and neither is implied by the other:

      (a) the version the app UNDERSTANDS is exactly the version this side PRINTS, so the
          ordinary case — today's app reading today's script — is an agreement and not a
          coincidence of ranges;
      (b) every version the app is willing to READ is one this side promises to stay
          compatible with, so the app cannot claim to read a 3 that nothing here has agreed
          to keep printing.

    Which document versions count as newer and which as older is the app's own rule and is
    tested in Swift, where it can be executed. What cannot be checked here at all: that the
    app compiles or that it decodes any of this. There is no SwiftUI on this machine.
    """
    source = swift_sources()

    understood = SWIFT_UNDERSTOOD.search(source)
    assert understood, "the app no longer declares which document version it understands"
    assert int(understood.group(1)) == control.CONTRACT, (
        f"the app understands version {understood.group(1)} and this side prints "
        f"version {control.CONTRACT}; one of them has to move")

    readable = SWIFT_READABLE.search(source)
    assert readable, "the app no longer declares the SET of document versions it can read"
    versions = {int(number) for number in readable.group(1).replace(",", " ").split()}
    assert versions, "the app declares an empty readable set, so it can read nothing"
    assert int(understood.group(1)) in versions, "the app cannot read its own version"
    assert versions <= set(control.COMPATIBLE_CLIENTS), (
        f"the app reads {sorted(versions - set(control.COMPATIBLE_CLIENTS))}, which this side "
        f"does not promise; compatible_clients is {list(control.COMPATIBLE_CLIENTS)}")


def test_the_app_no_longer_gates_on_the_version_being_equal():
    """The other half of what made version 2 unusable: `answer.contract == Contract.expected`
    refuses anything but one number, so an additive version bump breaks every install until
    every app is rebuilt. A range is what makes a version additive at all.

    SCOPED TO THE CONTRACT, deliberately. The first version of this test forbade the substring
    `static let expected` anywhere in the Swift sources, and that is a word, not an identifier:
    `ActionsDocument.expected` is the list of action ids whose ABSENCE the app reports, which is
    invariant 12's machinery and has nothing to do with document versions. The broad form went
    red against correct code the moment the two workstreams met. A gate that fires on unrelated
    English teaches its owner to override it, and an overridden gate protects nothing.
    """
    contract = (SWIFT_DIR / "Sources" / "CrooksControlCore" / "Contract.swift").read_text(encoding="utf-8")
    assert "static let expected" not in contract, \
        "the contract declares a single `expected` version again instead of a readable range"
    assert "== Contract.expected" not in swift_sources(), \
        "something still compares the document version for equality against a single number"
    # And the positive half: the check has to actually consult the range, or `readable` is a
    # declaration the code never reads — which is how invariant 12 ended up decorative.
    assert "canRead(" in contract, "the contract no longer asks whether a version is readable"


# ----------------------------------------------------- the one git command that moves


def test_a_sha_that_is_really_a_flag_never_reaches_git(here, monkeypatch):
    """A6. `git checkout <sha>` reads an argument that begins with '-' as an OPTION, and one
    of git's options names a program to run (`--upload-pack`). The sha comes off disk, out of
    logs/known-good.json, so it is not this file's to trust.

    Pinning it with a leading `--` — the obvious reflex — would be worse than the bug: it
    tells git the argument is a PATHSPEC, and `git checkout -- <sha>` does not check the
    commit out at all (it exits 1, "pathspec did not match any file"). The rollback would
    stop working and say it had worked. So the argument is refused before git is reached,
    and the revision is named as a revision.
    """
    ran = []

    def spy(argv, **_kw):
        ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(control.subprocess, "run", spy)
    for pretend in ("--upload-pack=id", "-x", "--output=/tmp/x", "", "not-hex", "HEAD~1"):
        moved, detail = control.checkout(pretend)
        assert moved is False, f"{pretend!r} was accepted"
        assert "not a commit" in detail
    assert ran == [], "and git was never run at all"


def test_a_real_sha_is_still_checked_out_and_still_detaches(repo, monkeypatch):
    """The other half, against real git: the refusal above must not have cost the rollback the
    only thing it does. This is what `git checkout -- <sha>` would have broken."""
    monkeypatch.setattr(control, "ROOT", repo)
    first = head(repo)
    commit_upstream(repo)
    subprocess.run(["git", "pull", "-q", "--ff-only"], cwd=repo, check=True)
    assert head(repo) != first

    moved, detail = control.checkout(first)
    assert moved is True, detail
    assert head(repo) == first, "the checkout really moved"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD", "and left a detached HEAD"


def test_a_known_good_record_that_is_not_a_commit_id_is_refused_by_the_decision(here):
    """The same argument, one layer up. A rollback offered against a value that is not a
    commit is a button that cannot work, and `git cat-file -e -x^{commit}` is read as a
    switch exactly as the checkout was."""
    decision = control.rollback_decision(
        current={"sha": head(here)}, good={"sha": "--upload-pack=id"}, blocking=[])
    assert decision["available"] is False and decision["safe"] is False
    assert "not a commit" in decision["reason"]


def _canned_backend(*_a, **_kw) -> dict:
    """One answer that serves all three session endpoints, so the contract tests below touch
    neither the network nor the session files on disk."""
    return {"started": True, "test_session_id": "ts-x", "name": "x", "path": "/x/ts-x.jsonl",
            "started_at": 1.0, "active": False, "last": {},
            "stopped": False, "detail": "No test session is running."}


def test_every_document_the_command_line_offers_is_named_in_the_contract():
    """The `what` list and the contract cannot drift: a subcommand whose document nothing
    describes is a subcommand the next client has to guess at."""
    named = set(control.contract_document()["documents"])
    assert set(control.WHAT) == named, f"{sorted(set(control.WHAT) ^ named)} is in one and not the other"


def test_the_lifecycle_and_session_documents_carry_only_what_the_contract_names(running, here, fake_mac, monkeypatch):
    from scripts import session_ops

    monkeypatch.setattr(session_ops, "call", _canned_backend)
    contract = control.contract_document()
    envelope_keys = set(contract["envelope_keys"])
    documents = {
        "start": control.start_document(wait_s=5.0),
        "stop": control.stop_document(),
        "restart": control.restart_document(wait_s=5.0),
        "session-start": control.session_start_document("first hour"),
        "session-status": control.session_status_document(),
        "session-stop": control.session_stop_document(analyse=False),
    }
    for name, doc in documents.items():
        assert doc["command"] == name and doc["contract"] == control.CONTRACT
        assert set(doc) & envelope_keys == envelope_keys, f"{name} is missing an envelope field"
        unnamed = set(doc) - envelope_keys - set(contract["documents"][name])
        assert unnamed == set(), f"{name} returns {sorted(unnamed)}, which the contract does not name"
        json.dumps(doc), "and every one of them is something the app can decode"


def test_the_session_label_is_the_only_text_from_the_app_that_reaches_a_command(buttons):
    """And it reaches it as one element of an argv list, never as a string a shell will read.
    Everything else in the actions document is fixed, which is why there is nothing to escape."""
    asking = [action for action in buttons if action.get("ask")]
    assert [action["id"] for action in asking] == ["session_start"]
    assert asking[0]["ask"]["flag"] == "--label" and asking[0]["ask"]["optional"] is True
    for action in buttons:
        for word in action.get("command", []):
            assert not any(character in word for character in ";|&$`"), action["id"]
