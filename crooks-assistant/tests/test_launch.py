"""`make up` and `make install`: what they would run.

Neither launches anything here. The commands are checked as data, because the failure that
matters — a backend started on the wrong port, or with the wrong proxy handling — is one a
supervisor turns into a silent restart loop. The Mac's half of this file (the rendered launchd
agents, the whisper-server launcher, `make status` under launchd) went with the Mac runtime and
the local recogniser on the owner's ruling of 8 October (DEC-071, rulings 38 and 39); the
server's unit is checked in tests/test_linux_ops.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lc = load("launch_common")
up = load("up")


# --------------------------------------------------------------------------- tailscale


def test_serve_status_finds_the_host_proxying_our_port():
    status = json.dumps({
        "TCP": {"443": {"HTTPS": True}},
        "Web": {"crooks-assistant.taildfb357.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}}},
    })
    assert lc.parse_serve_status(status, 8000) == "crooks-assistant.taildfb357.ts.net"
    assert lc.parse_serve_status(status, 8910) is None


@pytest.mark.parametrize("text", ["", "{}", "not json", '{"Web": null}', "[]", '{"Web": {"h:443": {}}}'])
def test_serve_status_is_none_when_nothing_is_served(text):
    assert lc.parse_serve_status(text, 8000) is None


# --------------------------------------------------------------------------- the supervisor


class FakeSettings:
    host = "127.0.0.1"
    port = 8000

    def __init__(self, _unused: Path | None = None) -> None:
        pass


def test_backend_command_uses_the_configured_address_and_no_reload_by_default(tmp_path):
    settings = FakeSettings(tmp_path)
    cmd = up.backend_command(settings)
    assert cmd[1:4] == ["-m", "uvicorn", "app.main:app"]
    assert "--host" in cmd and cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "8000"
    assert "--reload" not in cmd
    assert "--reload" in up.backend_command(settings, reload=True)


# The port probe is stubbed: the backend may be listening while the suite runs, and `make test`
# must not depend on what is running.
NOTHING_LISTENING = lambda host, port: False  # noqa: E731


def test_up_runs_the_backend_and_nothing_else(tmp_path):
    """It started whisper-server beside the backend until the local recogniser was deleted
    (DEC-071, ruling 39): there is one child now, and no note about a second."""
    children, notes = up.commands(FakeSettings(tmp_path / "nowhere"), port_open=NOTHING_LISTENING)
    assert [name for name, _ in children] == ["backend"]
    assert not any("whisper" in n.lower() for n in notes)


def test_up_does_not_start_what_is_already_running(tmp_path):
    """The installed service may already hold the port; `make up` must not fight it."""
    children, notes = up.commands(FakeSettings(tmp_path / "nowhere"), port_open=lambda host, port: True)
    assert children == []
    assert any("already running on port 8000" in n for n in notes)


def test_port_open_sees_a_real_listener():
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert lc.port_open("127.0.0.1", port)
    assert not lc.port_open("127.0.0.1", port)


# --------------------------------------------------------------------------- the unit's pieces


def test_render_refuses_a_missing_placeholder():
    with pytest.raises(ValueError):
        lc.render("<string>{{ROOT}}</string>", {"PYTHON": "x"})


def test_the_service_path_starts_with_the_interpreter_that_will_run_it():
    path = lc.service_path([sys.executable]).split(":")
    assert str(Path(sys.executable).resolve().parent) in path
    assert "/usr/bin" in path and "/bin" in path


def test_health_summary_names_what_is_down():
    data = {"status": "degraded", "checks": {"claude": {"ok": True}, "shopify": {"ok": False}, "gmail": {"ok": True}}}
    line = lc.summarise_health(data)
    assert line.startswith("partly down") and "working: Claude, Gmail" in line and "NOT working: Shopify" in line
    assert lc.summarise_health(None) == "the assistant is not answering"
    assert lc.summarise_health({"status": "ok", "checks": {"claude": {"ok": True}}}) == "all good · Claude"


def test_the_makefile_has_the_targets_the_readme_promises():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("up:", "install:", "uninstall:", "status:", "restart:", "logs:"):
        assert f"\n{target}" in makefile
    assert "scripts/up.py" in makefile and "scripts/install_systemd.py" in makefile
    # The Mac's installer and the local recogniser's targets are gone with them (DEC-071).
    for gone in ("install_launchd.py", "whisper-server:", "bench_whisper.py", "control-app:", "mac/CrooksControl"):
        assert gone not in makefile, gone


def test_every_launcher_leaves_the_connections_own_address_alone(tmp_path):
    """F-05B: the app decides whether tailscaled opened a connection from the connection's own
    address; uvicorn's proxy-header handling would overwrite it with the forwarded one."""
    root = Path(__file__).resolve().parent.parent
    assert "--no-proxy-headers" in up.backend_command(FakeSettings(tmp_path))
    unit = (root / "deploy" / "systemd" / "crooks-assistant.service").read_text()
    (exec_start,) = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
    assert exec_start.endswith("--no-proxy-headers")
    assert "--no-proxy-headers" in (root / "Makefile").read_text().split("\ndev:", 1)[1].split("\n\n", 1)[0]
    assert '"--no-proxy-headers"' in (root / "scripts" / "accept.py").read_text()
