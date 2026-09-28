"""scripts/gap_clean_check.py with no path, and with a path that names nothing (the 2026-09-28
deploy review, round 10, SC-GAPCHECK-DEFAULT).

Run bare from a review checkout, the check resolved the gap record inside that checkout
(<checkout>/.state/objectives/gaps.json), found nothing there, printed "no gap record at …" and
exited 0: a pass that looked like a real one and checked nothing. Now a missing record is exit 2
with a plain "NOTHING CHECKED", and with no path the record is the one the service at this checkout
is configured with — CROOKS_OBJECTIVES_DIR from the environment or the checkout's own .env, as the
service reads it — never the checkout's own .state.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gap_clean_check.py"
RECORD = {"version": 1, "gaps": {}, "builds": {}, "misjudged": {}, "seeded": "2026-09-27T01:07:06+00:00"}


@pytest.fixture()
def gap_check(tmp_path, monkeypatch):
    """The script, run from a checkout of its own (a temporary folder standing for a review
    checkout) that has a gap record in its own .state — the one it must never take for the
    server's — and with nothing configured: no CROOKS_OBJECTIVES_DIR, no .env file named."""
    spec = importlib.util.spec_from_file_location("gap_clean_check_r11", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "review-checkout"
    own = checkout / ".state" / "objectives"
    own.mkdir(parents=True)
    (own / "gaps.json").write_text(json.dumps(RECORD))
    monkeypatch.setattr(module, "ROOT", checkout)
    monkeypatch.delenv("CROOKS_OBJECTIVES_DIR", raising=False)
    monkeypatch.delenv("CROOKS_ENV_FILE", raising=False)
    checked: list[Path] = []
    monkeypatch.setattr(module, "check", lambda live, out=print: checked.append(live) or 0)
    return module, checkout, checked


def test_with_nothing_configured_a_bare_run_checks_nothing_and_says_so(gap_check, capsys):
    module, checkout, checked = gap_check
    assert module.main([]) == module.NOTHING_CHECKED == 2
    said = capsys.readouterr().out
    assert said.startswith("NOTHING CHECKED:") and "CROOKS_OBJECTIVES_DIR" in said and "give the record's path" in said
    assert checked == [], "the checkout's own .state record is never taken for the server's"


def test_a_bare_run_checks_the_configured_record_from_the_environment(gap_check, tmp_path, monkeypatch):
    module, _checkout, checked = gap_check
    live = tmp_path / "var-lib" / "objectives"
    live.mkdir(parents=True)
    (live / "gaps.json").write_text(json.dumps(RECORD))
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(live))
    assert module.main([]) == 0 and checked == [live / "gaps.json"]


def test_a_bare_run_reads_the_checkouts_own_env_as_the_service_does(gap_check, tmp_path):
    module, checkout, checked = gap_check
    live = tmp_path / "var-lib" / "objectives"
    live.mkdir(parents=True)
    (live / "gaps.json").write_text(json.dumps(RECORD))
    (checkout / ".env").write_text(f"CROOKS_OBJECTIVES_DIR={live}\n")
    assert module.main([]) == 0 and checked == [live / "gaps.json"]
    (checkout / ".env").write_text("CROOKS_OBJECTIVES_DIR=state/objectives\n")
    (checkout / "state" / "objectives").mkdir(parents=True)
    (checkout / "state" / "objectives" / "gaps.json").write_text(json.dumps(RECORD))
    assert module.main([]) == 0 and checked[-1] == checkout / "state" / "objectives" / "gaps.json", \
        "a relative folder is the service's, beside its working directory"


def test_a_record_that_is_not_there_is_never_a_pass(gap_check, tmp_path, monkeypatch, capsys):
    module, _checkout, checked = gap_check
    missing = tmp_path / "nowhere" / "gaps.json"
    assert module.main([str(missing)]) == 2
    assert f"NOTHING CHECKED: no gap record at {missing}" in capsys.readouterr().out
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(tmp_path / "nowhere"))
    assert module.main([]) == 2 and checked == []


def test_the_real_check_still_runs_on_a_record_that_is_there(tmp_path, monkeypatch, capsys):
    """Nothing stood in for: a real record at a configured folder is checked, and passes."""
    spec = importlib.util.spec_from_file_location("gap_clean_check_r11_real", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    live = tmp_path / "objectives"
    live.mkdir(mode=0o700)
    (live / "gaps.json").write_text(json.dumps(RECORD, indent=2))
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(live))
    assert module.main([]) == 0
    assert "VERDICT: nothing lost" in capsys.readouterr().out
