"""Deploy now in Chromium, on the phone and the tablet (scripts/browser/deploy.js; DEC-072).

The page is the real one, served by the real backend on the golden world, with the build loop behind a
fake GitHub (tests/builds_fixture.py), the trunk's head ahead of what CLIVE runs and acceptance green on
it (a stand-in reader, app/release/offer.py `bind`), the owner's passkey in Chromium's virtual
authenticator, and the release service installed, on, under owner_waiver and waiting only for his
approval. What stands in for the server:

- systemd's path unit (deploy/release/clive-release-now.path): a watcher on the folder CLIVE writes his
  approval into, which starts one tick the moment it changes;
- the tick is the real release service (app/release/service.py), checking his passkey's signature
  itself, on the fake production host of tests/test_release_service.py, each stage held a few seconds so
  the page can be seen following it; then "CLIVE restarts" onto the new build;
- journald: the lines CLIVE's own logger writes, where the keep check looks for his phone's /whoami.

Judged on the glass: the card on both sizes before; the hold, the passkey, then each stage in order on
the phone, through Done to Kept with no tap of his after the hold; and the tablet showing the deploy kept.
Afterwards, read back: production on the trunk's head, the approval spent, the deploy kept on record.

Set DEPLOY_SHOTS to a folder to keep the screenshots. Skipped, loudly, when node, playwright-core or
Chromium are missing, never quietly passed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.objectives import store as store_module
from app.release import approve, offer, state, status
from app.release.settings import ReleaseSettings
from app.routes import release as release_route
from app.tools import engineering_tools
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from tests import builds_fixture
from tests.connections_world import _register_passkey, passkey_for_the_browser
from tests.test_deploy_now import READY, Reader, _trunk, _write_status
from tests.test_release_service import LIVE, TRUNK, UNIT, FakeHost, Gate, World

SCRIPT = ROOT / "scripts" / "browser" / "deploy.js"
EXPECTED_CHECKS = 21
STAGE_S = 4.5          # how long the stand-in production host holds each stage, so a poll sees it


class Lines(logging.Handler):
    """CLIVE's own log lines, as journald would keep them."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[float, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((record.created, record.getMessage()))


def release_settings(tmp: Path, waivers: Path, passkeys_file: Path) -> ReleaseSettings:
    settings = ReleaseSettings(enabled=True, rule="owner_waiver", dry_run=False, checkout=tmp / "opt",
                               state_dir=tmp / "release", unit_path=tmp / "etc" / "crooks-assistant.service",
                               waivers_dir=tmp / "host-waivers", passkey_waivers_dir=waivers,
                               passkeys_file=passkeys_file, settle_s=0)
    (tmp / "opt" / "crooks-assistant").mkdir(parents=True)
    (tmp / "opt" / "crooks-assistant" / ".env").write_text("CROOKS_WRITES_ENABLED=true\n")
    (tmp / "etc" / "crooks-assistant.service.d").mkdir(parents=True)
    settings.unit_path.write_bytes(UNIT)
    return settings


class PathUnit(threading.Thread):
    """clive-release-now.path, standing in: the folder changes, and one tick of the real service runs."""

    def __init__(self, settings: ReleaseSettings, monkeypatch) -> None:
        super().__init__(daemon=True)
        self.settings, self.monkeypatch = settings, monkeypatch
        self.world = World(settings)
        self.world.on_step = {step: (lambda: time.sleep(STAGE_S)) for step in ("doctor", "install", "health_after")}
        self.host = FakeHost(self.world)
        self.stop = threading.Event()
        self.ticks: list[tuple[int, list[str]]] = []

    def _seen(self) -> str:
        folder = self.settings.passkey_waivers_dir
        return "|".join(f"{p.name}:{p.stat().st_mtime_ns}" for p in sorted(folder.glob("*.json"))) if folder.is_dir() else ""

    def run(self) -> None:
        from app.release import github, service

        before = self._seen()
        while not self.stop.is_set():
            time.sleep(0.2)
            now = self._seen()
            if now == before:
                continue
            before = now
            self.host.clock = datetime.now(UTC)
            printed: list[str] = []
            code = service.tick(self.host, self.settings, token=github.Token(""), gate=Gate(), pinned=True,
                                out=printed.append)
            self.ticks.append((code, printed))
            if self.world.head == TRUNK:
                # make install restarted CLIVE: the process now runs the new build.
                self.monkeypatch.setattr(engineering_tools, "running_sha", lambda root=None: TRUNK)
                self.monkeypatch.setattr(release_route, "PROCESS_SHA", TRUNK)


async def test_deploy_now_on_the_phone_and_the_tablet(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.connections import passkeys, service

    previous = store_module._STORE
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    lines = Lines()
    logging.getLogger("crooks.identity").addHandler(lines)
    unit = None
    try:
        from app.main import app

        runtime = app.state.runtime
        origin = f"http://localhost:{port}"
        objectives = tmp_path / "objectives"
        runtime.settings = runtime.settings.model_copy(update={"local_owner": False, "public_origin": origin,
                                                               "objectives_dir": objectives})
        store_module.install(objectives)
        service.configure(state_dir=tmp_path / "secrets" / "app")
        passkeys.reset()
        device = _register_passkey(origin)
        builds_fixture.bind(monkeypatch, builds_fixture.FakeLoop(), running=LIVE)
        monkeypatch.setattr(release_route, "PROCESS_SHA", LIVE)
        monkeypatch.setenv("CLIVE_RELEASE_STATE_DIR", str(tmp_path / "release"))
        offer.bind(Reader(_trunk()))
        approve.reset()
        _write_status(tmp_path / "release", READY)

        def journal(line: str, since: float):
            return any(at >= since - 1 and said.endswith(line) for at, said in lines.lines)

        monkeypatch.setattr(approve, "journal_has", journal)
        settings = release_settings(tmp_path, objectives / approve.WAIVERS, passkeys._path())
        unit = PathUnit(settings, monkeypatch)
        unit.start()
        shots = os.environ.get("DEPLOY_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        flow = json.dumps({"passkey": passkey_for_the_browser(device)})
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://localhost:{port}", shots, flow],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
    finally:
        if unit is not None:
            unit.stop.set()
            unit.join(timeout=30)
        logging.getLogger("crooks.identity").removeHandler(lines)
        await _stop(server, task)
        store_module._STORE = previous
        offer.bind(None)
        approve.reset()
        passkeys.reset()
        service.configure(state_dir=None)
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-2000:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert payload.get("ok"), f"{len(failed)} deploy browser check(s) failed:\n{detail}\nticks: {unit.ticks}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")

    # Read back: production on the trunk's head, by exactly one deploy; the approval spent; kept.
    assert unit.world.head == TRUNK
    deployed = [code for code, _printed in unit.ticks if code == 0]
    assert deployed, unit.ticks
    final = status.read(tmp_path / "release")
    assert final["deploy"]["end"] == "done" and final["deploy"]["sha"] == TRUNK
    assert state.approval_used(unit.host, settings.state_dir, final["deploy"]["approval"]) is not None
    kept = json.loads((objectives / approve.KEPT / f"{TRUNK}.json").read_text())
    assert kept["how"] == approve.whoami_line(kept["check"])
    assert any(said.endswith(kept["how"]) for _at, said in lines.lines), "the very line his phone wrote"
