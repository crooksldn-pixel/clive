"""The three words on the PATH, and the event count that said zero.

crooks-update is the one command that changes this Mac, so most of what is tested here is
what it REFUSES to do: move a dirty tree, rewrite history, or throw local work away.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import install_commands, update, watch

# ------------------------------------------------------------------ the count

def test_the_event_count_is_read_from_the_file_not_from_a_counter(tmp_path):
    """`make test-session-status` reported "events written=0" against a session holding a
    thousand: the counters are per-process and the supervisor had restarted the backend.
    The session is the file, so the count comes from the file."""
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline, count_events

    store = TestSessions(tmp_path)
    timeline = Timeline(store)
    session = timeline.start("an hour")
    for i in range(5):
        timeline.emit("turn_started", turn_id=f"turn_{i}")
    assert timeline.flush()
    path = store.timeline_path(session)
    assert count_events(path) == 6, "the start event and five turns"
    assert timeline.counts["written"] == 6 and timeline.counts["on_disk"] == 6

    # A fresh process — the supervisor restarted the backend — knows nothing of those events.
    restarted = Timeline(store)
    assert restarted.counts["this_process"] == 0
    assert restarted.counts["written"] == 6, "but the session still holds them"
    restarted.emit("turn_started", turn_id="turn_after")
    assert restarted.flush()
    assert restarted.counts["written"] == 7 and restarted.counts["this_process"] == 1


def test_the_count_still_answers_once_the_session_has_stopped(tmp_path):
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline

    timeline = Timeline(TestSessions(tmp_path))
    timeline.start("an hour")
    timeline.emit("turn_started", turn_id="t1")
    assert timeline.stop() is not None
    assert timeline.counts["written"] == 3, "started, the turn, stopped"


def test_counting_a_file_that_is_not_there_is_zero_not_an_error(tmp_path):
    from app.observability.timeline import count_events

    assert count_events(tmp_path / "nothing.jsonl") == 0


# ------------------------------------------------------------------- the watch

def test_the_watch_prints_what_the_owner_said_and_scrubs_what_is_somebody_else_s():
    """§35 asks for `VOICE "reply to anna"`, and it is what makes a live watch legible: every
    other line is an id, and without the sentence there is no telling which question they
    belong to. It is the owner's own speech, on his own Mac, in a session he started.

    What is taken out of it before it reaches the terminal is the shapes that are somebody's
    data whoever said them — an email address, a street, a postcode, a telephone number, a
    long run of digits — which is the same rule the production recorder keeps
    (app/observability/recorder.py), written once in `watch.said`."""
    rendered = watch.line({
        "kind": "stt", "iso": "2026-09-09T20:31:03", "turn_id": "turn_abc123", "ok": True,
        "engine": "scribe", "raw_text": "reply to anna about the hoodie",
        "text": "reply to anna about the hoodie",
    }, colour=False)
    assert "scribe" in rendered
    assert 'VOICE  “reply to anna about the hoodie”' in rendered

    private = watch.line({
        "kind": "stt", "iso": "2026-09-09T20:31:03", "turn_id": "turn_abc123", "ok": True, "engine": "scribe",
        "text": "send it to 14 Ravensbourne Road, BR3 4RT, or email anna@example.com on 07700 900123",
    }, colour=False)
    for shape in ("Ravensbourne", "BR3", "anna@example.com", "900123"):
        assert shape not in private, shape
    assert "[street]" in private or "[email]" in private

    quiet = watch.line({"kind": "stt", "iso": "2026-09-09T20:31:03", "turn_id": "t", "ok": False,
                        "engine": "scribe", "reason": "I did not catch any speech there."}, colour=False)
    assert "no speech" in quiet and "catch" not in quiet


def test_the_watch_refuses_a_field_it_was_never_told_about():
    rendered = watch.line({
        "kind": "tool_finished", "iso": "2026-09-09T20:31:03", "turn_id": "t", "tool": "shopify_order_address",
        "outcome": "ok", "ms": 120.0, "street": "12 Elm Road", "authorization": "Bearer abc",
    }, colour=False)
    assert "shopify_order_address ok" in rendered
    assert "Elm" not in rendered and "Bearer" not in rendered


def test_the_watch_says_which_lane_and_which_recipe():
    rendered = watch.line({"kind": "lane", "iso": "2026-09-09T20:31:03", "turn_id": "turn_a", "lane": "FAST",
                           "why": "order_lookup at 0.93", "recipe_id": "order_lookup"}, colour=False)
    assert "FAST" in rendered and "order_lookup" in rendered


def test_the_watch_flags_a_recipe_that_missed_its_target():
    slow = watch.line({"kind": "fast_path", "iso": "2026-09-09T20:31:03", "turn_id": "t", "recipe_id": "working_set_next",
                       "hit": True, "ms": 2400.0, "target_ms": 750}, colour=False)
    quick = watch.line({"kind": "fast_path", "iso": "2026-09-09T20:31:03", "turn_id": "t", "recipe_id": "working_set_next",
                        "hit": True, "ms": 400.0, "target_ms": 750}, colour=False)
    assert "over target" in slow and "over target" not in quick


def test_the_watch_says_nothing_about_an_event_it_has_no_line_for():
    assert watch.line({"kind": "something_new", "iso": "2026-09-09T20:31:03"}, colour=False) is None


def test_the_watch_follows_a_file_and_stops_at_the_end_of_a_session(tmp_path, capsys):
    path = tmp_path / "ts-x.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"kind": "session_started", "iso": "2026-09-09T20:00:00"},
        {"kind": "lane", "iso": "2026-09-09T20:00:01", "turn_id": "turn_1", "lane": "FAST", "recipe_id": "order_lookup", "why": "x"},
        {"kind": "session_stopped", "iso": "2026-09-09T20:00:02"},
    ]) + "\n", encoding="utf-8")
    assert watch.follow(path, once=False, colour=False) == 0
    out = capsys.readouterr().out
    assert "session started" in out and "FAST" in out and "session stopped" in out


# ------------------------------------------------------------------ the update

@pytest.fixture()
def repo(tmp_path):
    """A tiny git repo with a remote, so the update's refusals can be tested for real."""
    origin, work = tmp_path / "origin", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "T")):
        subprocess.run(["git", "config", key, value], cwd=work, check=True)
    (work / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "HEAD"], cwd=work, check=True)
    return work


def branch_of(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def test_a_clean_tree_on_the_right_branch_is_allowed_through(repo, monkeypatch):
    monkeypatch.setattr(update, "ROOT", repo)
    here = branch_of(repo)
    assert update.stage_branch(here) == here
    assert update.stage_branch("") == here, "with no branch named, whatever is checked out"


def test_local_work_stops_the_update_and_is_not_thrown_away(repo, monkeypatch):
    monkeypatch.setattr(update, "ROOT", repo)
    (repo / "pyproject.toml").write_text("[project]\nname='changed by hand'\n", encoding="utf-8")
    with pytest.raises(update.Stopped, match="will not throw work away"):
        update.stage_branch("")
    assert "changed by hand" in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_an_env_file_left_lying_about_does_not_stop_anything(repo, monkeypatch):
    monkeypatch.setattr(update, "ROOT", repo)
    (repo / ".env").write_text("SHOPIFY_TOKEN=secret\n", encoding="utf-8")
    assert update.stage_branch("") == branch_of(repo)
    assert (repo / ".env").read_text(encoding="utf-8") == "SHOPIFY_TOKEN=secret\n", "and it is still there afterwards"


def test_the_wrong_branch_stops_the_update(repo, monkeypatch):
    monkeypatch.setattr(update, "ROOT", repo)
    with pytest.raises(update.Stopped, match="does not switch branches"):
        update.stage_branch("some-other-branch")


def test_a_branch_ahead_of_the_remote_is_never_rewritten(repo, monkeypatch):
    monkeypatch.setattr(update, "ROOT", repo)
    (repo / "new.txt").write_text("mine\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "mine"], cwd=repo, check=True)
    with pytest.raises(update.Stopped, match="will not rewrite your history"):
        update.stage_pull(branch_of(repo), behind=1, ahead=1, check_only=False)
    assert (repo / "new.txt").exists(), "the local commit is still here"


def test_nothing_to_pull_is_not_a_pull(repo, monkeypatch, capsys):
    monkeypatch.setattr(update, "ROOT", repo)
    moved, changed = update.stage_pull(branch_of(repo), behind=0, ahead=0, check_only=False)
    assert moved is False and changed == []
    assert "already up to date" in capsys.readouterr().out


def test_check_only_changes_nothing(repo, monkeypatch, capsys):
    monkeypatch.setattr(update, "ROOT", repo)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout
    moved, _ = update.stage_pull(branch_of(repo), behind=3, ahead=0, check_only=True)
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert moved is False and before == after
    assert "would fast-forward" in capsys.readouterr().out


def test_dependencies_are_reinstalled_only_when_they_changed(capsys):
    assert update.stage_deps(["app/routes/turn.py", "web/app.js"], check_only=False) is False
    assert "unchanged" in capsys.readouterr().out
    assert update.stage_deps(["pyproject.toml"], check_only=True) is False
    assert "would reinstall" in capsys.readouterr().out


DESTRUCTIVE = {"reset", "checkout", "clean", "rebase", "restore", "stash", "push", "commit", "rm"}


def test_the_update_runs_no_git_command_that_could_lose_work():
    """Every git verb this command can reach, read off the source. A comment or a docstring
    that mentions `reset` is prose; a call that runs it is not, and there are none."""
    import re

    source = Path("scripts/update.py").read_text(encoding="utf-8")
    verbs = set(re.findall(r'git\(\s*"([a-z-]+)"', source))
    assert verbs, "the scan found no git calls at all, so it is not testing anything"
    assert not verbs & DESTRUCTIVE, f"crooks-update reaches {sorted(verbs & DESTRUCTIVE)}"
    assert verbs <= {"rev-parse", "status", "fetch", "config", "rev-list", "diff", "merge"}, sorted(verbs)
    assert '"merge", "--ff-only"' in source, "the only merge there is"
    assert "--force" not in source.split('"""', 2)[-1]


def test_the_update_leaves_secrets_and_logs_alone():
    source = Path("scripts/update.py").read_text(encoding="utf-8")
    assert "NEVER_TOUCH" in source
    assert update.NEVER_TOUCH == (".env", "logs", "reports", ".venv")


# ---------------------------------------------------------------- the commands

def test_the_commands_point_at_the_checkout_rather_than_copying_it(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(install_commands, "BIN", bin_dir)
    assert install_commands.install(root=Path.cwd(), bin_dir=bin_dir) == 0
    for name, (script, _fixed) in install_commands.COMMANDS.items():
        wrapper = bin_dir / name
        assert wrapper.exists() and wrapper.stat().st_mode & 0o111, name
        body = wrapper.read_text(encoding="utf-8")
        assert str(Path.cwd() / script) in body, "the wrapper runs the checkout's own file"
        assert "exec" in body and len(body.splitlines()) <= 6, "a wrapper, not a copy"
    assert install_commands.remove(bin_dir=bin_dir) == 0
    assert not any((bin_dir / name).exists() for name in install_commands.COMMANDS)


def test_the_commands_are_the_ones_the_brief_asked_for():
    """Three for running it, four for testing it, and the one the Mac app reads. The four are
    one script with a switch each, so a change to the runner cannot leave one of them
    behind."""
    assert sorted(install_commands.COMMANDS) == [
        "crooks-control", "crooks-status", "crooks-test", "crooks-test-live",
        "crooks-test-scenario", "crooks-test-ui", "crooks-update", "crooks-watch",
    ]
    test_commands = {n: a for n, (s, a) in install_commands.COMMANDS.items() if n.startswith("crooks-test")}
    assert {n for n, (s, _) in install_commands.COMMANDS.items() if n.startswith("crooks-test")
            and s == "scripts/experience.py"} == set(test_commands), "one runner, four doors"
    assert test_commands == {"crooks-test": "", "crooks-test-ui": "--ui",
                             "crooks-test-live": "--live", "crooks-test-scenario": "--scenario"}


# ------------------------------------------------------------------- the bench

@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_lane_bench_runs_offline_and_every_row_is_measured(capsys):
    """The bench is a test as well as a bench: it fails if a recipe stops answering, and it
    never reaches a network — the sources are the suite's own doubles."""
    from scripts import bench_lanes

    assert await bench_lanes.main(["--orders", "60", "--latency-ms", "1"]) == 0
    out = capsys.readouterr().out
    assert "answered with no model call" in out
    answered = int(out.split("\n")[out.split("\n").index(next(x for x in out.split("\n") if "answered with no model call" in x))].split()[0])
    total = int(next(x for x in out.split("\n") if "answered with no model call" in x).split()[2])
    assert answered == total, f"{total - answered} row(s) fell out of the fast lane"
    assert "OVER" not in out, "a recipe missed its own latency target"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_lane_bench_puts_the_clock_back_when_it_is_done(capsys):
    """It runs in THIS process, so what it patches is what every later test reads.

    `london_now` freezes the clock the analytic tools read. The bench used to apply it with a
    shim that had no undo — correct for a standalone process, silently wrong here: every
    harness read of "today's orders" three files later came back empty, and the golden
    navigation scenario walked a list of nothing. The bench restores what it replaced now, and
    this asserts it rather than trusting it.
    """
    from app.tools import analytics_tools
    from scripts import bench_lanes

    before = analytics_tools.datetime
    assert await bench_lanes.main(["--orders", "4", "--latency-ms", "0"]) == 0
    capsys.readouterr()
    assert analytics_tools.datetime is before, (
        "the bench left its frozen clock behind; every later test's idea of today is now its own"
    )


def test_the_bench_quotes_the_session_it_says_it_quotes():
    """Every baseline figure in the bench is one the September report actually carries."""
    from scripts.bench_lanes import BASELINE

    assert BASELINE["capability_delta"][1:] == (76_585, 75_530, 0)
    assert BASELINE["working_set_next"][1:] == (30_430, 29_440, 0)
    assert BASELINE["needs_reply"][1:] == (29_010, 28_099, 0)
    assert BASELINE["order_address_lookup"][1:] == (36_812, 35_236, 1)
