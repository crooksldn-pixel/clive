"""Approving a return on a phone, in a real browser (Chromium with iPhone touch emulation).

The owner had pending returns on their phone and could not approve them. Measured in a
browser at phone height: the dialog's Approve sat below the screen (the dialog scrolled, but
nothing said so), and while its preview ran the button was only faded. This drives the real
page by touch: Approve must be on screen, big enough to hit, and a double tap approves once.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CHROMIUM = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium")


def _playwright_env() -> dict[str, str] | None:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm or not Path(CHROMIUM).exists():
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "NODE_PATH": root, "CHROMIUM": CHROMIUM}
    probe = subprocess.run([node, "-e", "require('playwright')"], env=env, capture_output=True)
    return env if probe.returncode == 0 else None


ENV = _playwright_env()
pytestmark = pytest.mark.skipif(ENV is None, reason="needs node, playwright and Chromium")


@pytest.fixture
def served():
    import uvicorn
    from fastapi import FastAPI

    from returns.app import build_service, create_app

    # The same fixture store and seeded returns as the browser checks use.
    spec = importlib.util.spec_from_file_location("dev_server", SCRIPTS / "dev_server.py")
    assert spec and spec.loader
    dev_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev_server)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    s = dev_server.settings(port)
    svc = build_service(s)
    dev_server.seed(svc)
    root = FastAPI()
    root.mount("/apps/returns", create_app(s, svc))
    server = uvicorn.Server(uvicorn.Config(root, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", svc
    server.should_exit = True
    thread.join(5)


@pytest.mark.parametrize("height", [560, 480])
def test_a_pending_return_is_approved_by_touch_on_a_phone(served, height):
    base, svc = served
    run = subprocess.run(
        ["node", str(HERE / "mobile_approve.cjs"), base, str(height)],
        env=ENV,
        capture_output=True,
        text=True,
        timeout=90,
    )
    found = json.loads(run.stdout.strip().splitlines()[-1])
    assert "error" not in found, found
    assert found["dialog_approve_on_screen"], found  # no hidden scrolling to find it
    assert found["hit"] == "go"  # nothing covers it
    assert found["detail_button_height"] >= 44 and found["dialog_approve_height"] >= 44
    # While the price check runs, Approve is disabled and says why, beside it.
    assert found["disabled_while_checking"] and "Checking" in found["why_while_checking"]
    assert found["dialog_closed"] and found["status_shown"] != "Needs approval"
    assert found["approve_posts"] == 1  # a double tap sends it once
    assert len(svc.shopify.called("returnCreate")) == 2  # the seeded one, and this one
    pending = [r for r in svc.store.search(limit=50) if r.status.value == "requested"]
    assert pending == []
