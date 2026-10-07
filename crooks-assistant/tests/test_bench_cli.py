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
                          text=True, timeout=300)


def test_a_dry_run_from_the_command_line_makes_a_set_a_run_and_a_report(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CROOKS_", "ANTHROPIC_")) and k not in PROXIES}
    env.update({"CROOKS_ENV_FILE": "", "CROOKS_ALLOWED_LOGINS": "someone-else@example.com",
                "CROOKS_WRITES_ENABLED": "false", "CROOKS_ENGINEERING_HOST": "worker-01",
                "CROOKS_SECRET_DIR": str(tmp_path / "not-the-run's"), "CROOKS_OBJECTIVES_DIR": str(tmp_path / "objectives")})
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

    again = _bench("report", "--data-dir", str(data), env=env)
    assert again.returncode == 0 and manifest["run_id"] in again.stdout
