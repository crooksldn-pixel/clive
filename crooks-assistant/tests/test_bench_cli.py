"""`python -m app.bench` from a terminal, as George's worker-01 runs it (docs/BENCH.md), with --dry-run:
the questions are the persona files' own examples, no model is asked, nothing is scored.

In a process of its own, because a run latches its process read-only for good (app/readonly.py),
and because that is how the command is really run: the settings a run needs are set before any of
CLIVE is imported, whatever the shell it starts from holds. Its CROOKS_ settings are deliberately
nonsense here, to show none of them reaches the fake shop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROXIES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}


def _bench(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "app.bench", *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=300, umask=0o022)


def _env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CROOKS_", "ANTHROPIC_")) and k not in PROXIES}
    env.update({"CROOKS_ENV_FILE": "", "CROOKS_ALLOWED_LOGINS": "someone-else@example.com",
                "CROOKS_WRITES_ENABLED": "false", "CROOKS_ENGINEERING_HOST": "worker-01",
                "CROOKS_SECRET_DIR": str(tmp_path / "not-the-run's"), "CROOKS_OBJECTIVES_DIR": str(tmp_path / "objectives")})
    return env


def test_a_dry_run_from_the_command_line_makes_a_set_a_run_and_a_report(tmp_path):
    env = _env(tmp_path)
    data = tmp_path / "data"

    listed = _bench("personas", env=env)
    assert listed.returncode == 0 and "bad-actor" in listed.stdout and "staff" in listed.stdout

    made = _bench("generate", "--dry-run", "--data-dir", str(data), env=env)
    assert made.returncode == 0, made.stdout + made.stderr
    [set_file] = (data / "bench" / "questions").glob("qs-*.json")
    question_set = json.loads(set_file.read_text())
    assert question_set["model"] == "scripted" and len(question_set["questions"]) == 24

    ran = _bench("run", "--dry-run", "--data-dir", str(data), "--personas", "emily-and-the-packers,george",
                 "--max-questions", "8", "--judge", env=env)
    assert ran.returncode == 0, ran.stdout[-3000:] + ran.stderr[-3000:]
    [run_dir] = (data / "bench" / "runs").iterdir()
    manifest = json.loads((run_dir / "run.json").read_text())
    assert (manifest["status"], manifest["mode"], manifest["done"], manifest["breaches"]) == ("finished", "scripted", 8, 0)
    assert manifest["caps"]["max_questions"] == 8 and manifest["models"] == {"turns": "scripted", "judge": "scripted"}
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    assert {(r["persona"], r["access"]) for r in rows} == {("emily-and-the-packers", "staff"), ("george", "owner")}
    assert all(r["turns"][0]["status"] == 200 and r["safety"]["executions"] == 0 for r in rows)
    verdicts = [json.loads(line) for line in (run_dir / "judged.jsonl").read_text().splitlines()]
    assert len(verdicts) == 8 and all("not_judged" in v for v in verdicts)        # a dry run scores nothing
    assert (run_dir / "report.md").read_text().startswith("# Bench run") and "# Bench run" in ran.stdout
    assert not (tmp_path / "not-the-run's").exists()                              # the shell's settings reached nothing
    # Every folder it made is 0700 and every file 0600, under an ordinary umask (review note N3).
    made_here = [data / "bench", *(data / "bench").rglob("*")]
    assert {str(p.relative_to(data)): oct(p.stat().st_mode & 0o777) for p in made_here if p.is_dir()} == dict.fromkeys(
        ["bench", "bench/questions", "bench/runs", f"bench/runs/{run_dir.name}"], "0o700")
    assert {oct(p.stat().st_mode & 0o777) for p in made_here if p.is_file()} == {"0o600"}
    assert {p.name for p in run_dir.iterdir()} >= {"run.json", "results.jsonl", "judged.jsonl", "report.json", "report.md"}

    again = _bench("report", "--data-dir", str(data), env=env)
    assert again.returncode == 0 and manifest["run_id"] in again.stdout


def _one_line(got: subprocess.CompletedProcess | None, err: str = "") -> str:
    """A refusal's whole say: exactly one line on stderr, no traceback."""
    text = got.stderr if got is not None else err
    assert "Traceback" not in text, text[-2000:]
    [line] = text.strip().splitlines()
    return line


def test_an_api_key_is_refused_in_one_plain_line(tmp_path):
    """Review note N6 (8 Oct): the refusal worked, but it came out as a traceback."""
    env, data = _env(tmp_path), tmp_path / "data"
    assert _bench("generate", "--dry-run", "--data-dir", str(data), "--personas", "george", env=env).returncode == 0
    assert _bench("run", "--dry-run", "--data-dir", str(data), "--max-questions", "1", env=env).returncode == 0
    before = sorted(str(p.relative_to(data)) for p in data.rglob("*"))
    env["ANTHROPIC_API_KEY"] = "a-pay-as-you-go-key"
    for command in ("generate", "run", "judge"):
        got = _bench(command, "--dry-run", "--data-dir", str(data), env=env)
        assert got.returncode == 2, (command, got.stdout[-1000:], got.stderr[-2000:])
        assert _one_line(got).startswith("bench: refused: ANTHROPIC_API_KEY is set in this environment."), command
    assert sorted(str(p.relative_to(data)) for p in data.rglob("*")) == before            # nothing was written


def test_a_folder_this_user_may_not_write_is_one_plain_line(tmp_path, monkeypatch, capsys):
    """Review note N6: run on the server as a user who cannot write the data directory, the bench said so
    in a traceback. It says so in one line now, with the folder and what to do."""
    from app.bench import cli
    from app.bench.store import Bench

    def denied(self, path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(Bench, "folder", denied)
    data = tmp_path / "data"
    assert cli.main(["generate", "--dry-run", "--data-dir", str(data), "--personas", "george"]) == 2
    assert _one_line(None, capsys.readouterr().err) == (
        f"bench: not allowed to use {data / 'bench' / 'questions'} as this user: run it as the user that owns it, "
        "or give --data-dir a folder this user can write")


def test_the_runbook_commands_are_ones_that_work():
    """docs/BENCH.md, run as written. Review note N2 (8 Oct): its rsync named two remote hosts, which rsync
    refuses, and copied into a folder nothing had made. Every rsync now names at most one remote, after an
    install that makes every bench folder it copies into, 0700; every `app.bench` line parses as the CLI's."""
    from app.bench.cli import parser

    blocks = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8").split("```")[1::2]
    lines = [line.split("#", 1)[0].strip() for block in blocks for line in block.splitlines()]
    made: set[str] = set()
    rsyncs = commands = 0
    for words in (line.split() for line in lines if line):
        if words[:3] == ["install", "-d", "-m"] and words[3] == "700":
            made.update(w.rstrip("/") for w in words[4:])
        elif words[0] == "rsync":
            rsyncs += 1
            remote = [w for w in words[1:] if not w.startswith("-") and ":" in w.split("/", 1)[0]]
            assert len(remote) <= 1, f"rsync copies between this host and one other: {words}"
            target = words[-1].rstrip("/")
            assert {target, target.rsplit("/", 1)[0]} <= made, f"nothing made {target} (and its bench folder) 0700 first"
        elif words[1:3] == ["-m", "app.bench"]:
            parser().parse_args(words[3:])
            commands += 1
    assert rsyncs == 1 and commands >= 6
