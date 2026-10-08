"""crooks-update (scripts/update.py): the fast-forward-only update of the server, as lines and
as one --json document, and the redactor every such document leaves through.

These lived in tests/test_control.py, beside the CROOKS Control menu-bar app's documents, until
the app and scripts/control.py went with the Mac runtime on the owner's ruling of 8 October
(DEC-071, ruling 38). The updater stays — it is how the server is brought up to date by hand —
so its tests moved here unchanged, with two exceptions said where they are: the redactor's tests
call it where it now lives (update.redact), and the restart stage is driven against the server's
systemd double (tests/test_service_linux.py) rather than the Mac's launchd one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import update
from tests.fake_credentials import (
    anthropic_key,
    credential_url,
    elevenlabs_key,
    github_token,
    shopify_token,
)
from tests.test_service_linux import Server, SystemdDouble

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
    """The updater pointed at the fixture repo."""
    monkeypatch.setattr(update, "ROOT", repo)
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


def test_a_git_error_quoting_a_token_is_masked_in_the_json_too(here, monkeypatch, capsys):
    """The other door: `crooks-update --json`, typed. A remote URL with a credential in it is
    exactly what a failed fetch quotes back, so that document goes through the same redactor
    every document of this command does."""
    token = github_token("update-fetch")
    monkeypatch.setenv("GIT_ACCESS_TOKEN", token)

    def fetch(branch):
        raise update.Stopped("fatal: could not read from "
                             + credential_url(token, user="x", host="github.com", path="/o/r.git"))

    monkeypatch.setattr(update, "stage_fetch", fetch)
    assert update.main(["--json"]) == 1
    out = capsys.readouterr().out
    assert "ghp_" not in out and update.MASK in out
    document = json.loads(out)
    assert document["stop"]["stage"] == "fetch" and "could not read from" in document["stop"]["reason"]


# ------------------------------------------------------------------------- no secrets


TOKEN = shopify_token("control-status")
VOICE_KEY = elevenlabs_key("control-status")
MODEL_KEY = anthropic_key("control-status")


def test_no_secret_survives_the_redactor_even_when_a_detail_quotes_one(monkeypatch):
    """A real-looking credential in the environment AND echoed back inside a detail — which is
    how it would happen: a client library putting the token in an error message. Held against
    the status document of the menu-bar app's command until it went (DEC-071, ruling 38); held
    here against the redactor that command and this one shared."""
    monkeypatch.setenv("CROOKS_SHOPIFY_STATIC_TOKEN", TOKEN)
    monkeypatch.setenv("ELEVENLABS_API_KEY", VOICE_KEY)
    doc = {"checks": {"shopify": {"ok": False, "detail": f"401 Unauthorized for token {TOKEN}"},
                      "gmail": {"ok": False, "detail": f"refresh failed: {MODEL_KEY}"}},
           "voice": {"api_key": VOICE_KEY, "voice": "Derek"}}
    out = json.dumps(update.redact(doc))
    assert TOKEN not in out and "shpat_" not in out
    assert VOICE_KEY not in out
    assert "sk-ant-api03" not in out
    assert out.count(update.MASK) >= 3, "and it says something was taken out"
    assert "401 Unauthorized for token" in out, "the diagnosis survives; only the credential goes"


def test_redaction_leaves_the_identifiers_a_reader_needs(monkeypatch):
    """A SHA is forty hex characters and a build id is not a secret. A redactor that eats them
    is a document that cannot tell two builds apart."""
    monkeypatch.setenv("CROOKS_SHOPIFY_STATIC_TOKEN", TOKEN)
    sha = "0123456789abcdef0123456789abcdef01234567"
    out = update.redact({"current": {"sha": sha, "build": "b-2026-09-10-abc"},
                         "stages": [{"stage": "repo", "detail": "answering on 127.0.0.1:8000"}]})
    assert out["current"]["sha"] == sha and out["current"]["build"] == "b-2026-09-10-abc"
    assert out["stages"][0]["detail"] == "answering on 127.0.0.1:8000"


def test_a_field_whose_name_says_credential_goes_whatever_is_in_it():
    out = update.redact({"authorization": "Bearer abc", "token": "anything at all",
                          "url": credential_url(github_token("control-field"), host="github.com", path="/o/r.git"),
                          "sha": "a" * 40, "detail": "ready"}, secrets=[])
    assert out["authorization"] == update.MASK and out["token"] == update.MASK
    assert "ghp_" not in out["url"] and out["url"].startswith("https://x-access-token:")
    assert out["sha"] == "a" * 40 and out["detail"] == "ready"


def test_the_environment_is_read_for_shapes_not_for_use(monkeypatch):
    monkeypatch.setenv("SOMETHING_SECRET", "a-long-enough-value")
    monkeypatch.setenv("CROOKS_PORT", "8000")
    found = update.environment_secrets()
    assert "a-long-enough-value" in found
    assert "8000" not in found, "a port is not a credential, and a short value is not one either"


# --------------------------------------------------------------------- the boundary


def test_nothing_in_crooks_os_calls_the_updater_or_the_control_command():
    """The updater's own docstring: it runs when it is typed, and not otherwise; the backend
    never calls it. (crooks-control, the menu-bar app's command, is gone with the app, and
    staying out of CROOKS OS is still asserted for it.)"""
    import subprocess as sp

    hits = sp.run(["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.html",
                   "-e", "scripts.update", "-e", "scripts/update.py", "-e", "crooks-update",
                   "-e", "scripts.control", "-e", "crooks-control", "app", "config", "web", "experience"],
                  cwd=PROJECT, capture_output=True, text=True).stdout.strip()
    assert hits == "", f"something inside CROOKS OS reaches the updater:\n{hits}"


def test_the_updater_names_no_shell_command_for_a_failed_restart():
    """Read as source, because the string that failed §5.2 was a literal in this file."""
    source = (PROJECT / "scripts" / "update.py").read_text(encoding="utf-8")
    assert "make install" not in source


# ------------------------------------------- the update's own restart (§5.2, no Terminal)


@pytest.fixture()
def update_server(tmp_path, monkeypatch):
    """`crooks-update`'s restart stage pointed at a server that is not one: the systemd double
    tests/test_service_linux.py holds the lifecycle to, and a /health under the test's control."""
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    monkeypatch.setattr(update, "server_for", lambda _port: (server.machine, server.supervisor()))
    return server


def test_an_update_restarts_a_server_whose_service_systemd_does_not_hold(here, update_server):
    """A3, on the server. A restart of a service systemd does not have is not a restart — it
    fails, "Unit not found" — so the update registers the service and starts it rather than
    stopping to tell anyone to run an installer. (It was the Mac's launchd agents, until the
    Mac runtime went: DEC-071, ruling 38.)"""
    systemd = update_server.systemd
    systemd.on_restart = update_server.comes_up

    update.stage_restart(check_only=False, port=8000)   # raises Stopped if it cannot

    assert systemd.loaded and systemd.enabled, "it registered the service itself"
    assert "restart" in systemd.verbs(), "and then started it"
    assert update_server.health is not None, "and read the backend back up"


def test_a_restart_the_update_cannot_do_says_where_the_reason_is_and_never_an_installer(here, update_server):
    """A3's sentence. `raise Stopped("… run `make install` once …")` is the whole of §5.2's
    no-Terminal claim failing. What the update says when the restart is what failed is where
    the reason is written down, and that the code did move."""
    update_server.systemd.absent = True          # there is no systemctl on this server at all

    with pytest.raises(update.Stopped) as refused:
        update.stage_restart(check_only=False, port=8000)

    said = str(refused.value)
    for banned in ("make install", "make up", "make restart", "make venv", "Terminal", "launchctl "):
        assert banned not in said, f"the update still tells the operator {banned!r}"
    assert "journalctl" in said, "it names where the reason is"
    assert "Your code IS updated" in said, "and still says what state the server was left in"
