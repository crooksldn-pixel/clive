"""`make up` and `make install`: what they would run, and what they would write.

Neither launches anything here. The supervisor's commands and the rendered launchd agents are
checked as data, because the failure that matters — a plist with a placeholder left in it, or
a backend started on the wrong port — is one launchd turns into a silent restart loop.
"""

from __future__ import annotations

import importlib.util
import json
import plistlib
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
whisper_server = load("whisper_server")
up = load("up")
installer = load("install_launchd")


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
    whisper_url = "http://127.0.0.1:8910"
    whisper_model = "large-v3-turbo"
    whisper_vad_pad_ms = 200

    def __init__(self, whisper_bin_dir: Path) -> None:
        self.whisper_bin_dir = whisper_bin_dir


def test_backend_command_uses_the_configured_address_and_no_reload_by_default(tmp_path):
    settings = FakeSettings(tmp_path)
    cmd = up.backend_command(settings)
    assert cmd[1:4] == ["-m", "uvicorn", "app.main:app"]
    assert "--host" in cmd and cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "8000"
    assert "--reload" not in cmd
    assert "--reload" in up.backend_command(settings, reload=True)


# The port probe is stubbed: on the owner's Mac whisper-server and the backend are usually
# listening while the suite runs, and `make test` must not depend on what is running.
NOTHING_LISTENING = lambda host, port: False  # noqa: E731


def test_up_runs_without_whisper_when_it_is_not_built_and_says_so(tmp_path):
    children, notes = up.commands(FakeSettings(tmp_path / "nowhere"), port_open=NOTHING_LISTENING)
    assert [name for name, _ in children] == ["backend"]
    assert any("whisper-server is NOT starting" in n for n in notes)
    assert any("ElevenLabs still hears you" in n for n in notes)


def test_up_runs_whisper_first_when_it_is_built(tmp_path):
    root = tmp_path / "whisper.cpp"
    (root / "build" / "bin").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "build" / "bin" / "whisper-server").write_text("")
    (root / "models" / "ggml-large-v3-turbo.bin").write_text("")
    (root / "models" / "ggml-silero-v5.1.2.bin").write_text("")
    children, notes = up.commands(FakeSettings(root), port_open=NOTHING_LISTENING)
    assert [name for name, _ in children] == ["whisper", "backend"]
    whisper_cmd = children[0][1]
    assert whisper_cmd[0].endswith("whisper-server")
    assert "--vad" in whisper_cmd and "--port" in whisper_cmd and whisper_cmd[whisper_cmd.index("--port") + 1] == "8910"
    # No Core ML encoder: a note, not a refusal.
    assert any("Metal" in n for n in notes)


def test_up_does_not_start_what_is_already_running(tmp_path):
    """The login-time agents may already hold both ports; `make up` must not fight them."""
    children, notes = up.commands(FakeSettings(tmp_path / "nowhere"), port_open=lambda host, port: True)
    assert children == []
    assert any("already running on port 8000" in n for n in notes)
    assert any("already running on port 8910" in n for n in notes)


def test_port_open_sees_a_real_listener():
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert lc.port_open("127.0.0.1", port)
    assert not lc.port_open("127.0.0.1", port)


def test_whisper_refuses_without_a_vad_model(tmp_path):
    root = tmp_path / "whisper.cpp"
    (root / "build" / "bin").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "build" / "bin" / "whisper-server").write_text("")
    (root / "models" / "ggml-large-v3-turbo.bin").write_text("")
    resolved = whisper_server.resolve(FakeSettings(root))
    assert resolved.cmd is None and "Silero" in resolved.problem


# --------------------------------------------------------------------------- launchd agents


def values(tmp_path: Path) -> dict[str, str]:
    return lc.plist_values(root=tmp_path / "checkout", python=tmp_path / ".venv" / "bin" / "python", home=tmp_path)


def test_every_template_renders_to_a_valid_plist_with_no_placeholder_left(tmp_path):
    rendered = installer.rendered_plists(values(tmp_path))
    assert set(rendered) == {"com.crooks.assistant", "com.crooks.whisper"}
    for label, body in rendered.items():
        assert "{{" not in body and "USERNAME" not in body
        plist = plistlib.loads(body.encode("utf-8"))
        assert plist["Label"] == label
        assert plist["ProgramArguments"][0] == str(tmp_path / ".venv" / "bin" / "python")
        assert plist["WorkingDirectory"] == str(tmp_path / "checkout")
        assert plist["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
        assert plist["ThrottleInterval"] >= 10
        assert plist["StandardOutPath"].startswith(str(tmp_path / "checkout" / "logs"))
        env = plist["EnvironmentVariables"]
        assert env["HOME"] == str(tmp_path)
        assert "/usr/bin" in env["PATH"].split(":")
        # Nothing that would bill per token, and no credential, is ever written into a plist.
        for forbidden in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "xi-api-key", "shpat_"):
            assert forbidden not in body


def test_the_backend_agent_names_the_cli_and_the_port(tmp_path):
    body = installer.rendered_plists(values(tmp_path))["com.crooks.assistant"]
    plist = plistlib.loads(body.encode("utf-8"))
    args = plist["ProgramArguments"]
    assert args[1:4] == ["-m", "uvicorn", "app.main:app"]
    assert args[args.index("--host") + 1] == "127.0.0.1" and args[args.index("--port") + 1] == "8000"
    assert "CROOKS_CLAUDE_CLI_PATH" in plist["EnvironmentVariables"]


def test_render_refuses_a_missing_placeholder():
    with pytest.raises(ValueError):
        lc.render("<string>{{ROOT}}</string>", {"PYTHON": "x"})


def test_launchd_path_starts_with_the_interpreter_that_will_run_it():
    path = lc.launchd_path([sys.executable]).split(":")
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
    assert "scripts/up.py" in makefile and "scripts/install_launchd.py" in makefile


# ------------------------------------------- `make status`: answering is not supervised


LABELS = ("com.crooks.assistant", "com.crooks.whisper")
HEALTHY = {"status": "ok", "build": "b-1", "checks": {"claude": {"ok": True}}}


def _installed_mac(monkeypatch, tmp_path, *, health, loaded=True, pid=True):
    """`make status` pointed at a Mac that is not one: a launchd that holds the two facts real
    launchd holds, and a /health under the test's control."""
    from tests.fake_launchd import LaunchdDouble

    svc = installer.svc
    agent_dir = tmp_path / "LaunchAgents"
    agent_dir.mkdir(exist_ok=True)
    for label in LABELS:
        (agent_dir / f"{label}.plist").write_text("<plist/>", encoding="utf-8")
    double = LaunchdDouble(loaded=LABELS if loaded else (),
                           running=LABELS if (loaded and pid) else ())
    machine = svc.Machine(
        runner=double, read_health=lambda fresh=False: health,
        port_open=lambda: health is not None, ensure_route=lambda: ("crooks.ts.net", ""),
        is_macos=lambda: True, sleep=lambda _s: None, now=lambda: 0.0, log_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(installer, "_machine", lambda _port: machine)
    monkeypatch.setattr(installer, "AGENT_DIR", agent_dir)
    monkeypatch.setattr(installer.lc, "serve_status", lambda _port: ("crooks.ts.net", ""))
    return double


def test_make_status_exits_zero_only_for_a_mac_under_launchd_supervision(tmp_path, monkeypatch, capsys):
    """A4. /health ANSWERING and the service being SUPERVISED are two different facts, and an
    exit code that conflates them is read by everything downstream.

    `make up` runs the backend as a child of somebody's Terminal. It answers /health perfectly
    — and it dies the moment that window is closed. Exiting 0 on that tells a setup script, a
    monitor, or the next person that this Mac is installed and supervised. It is neither.
    """
    _installed_mac(monkeypatch, tmp_path, health=HEALTHY, pid=False)
    code = installer.status(8000)
    printed = capsys.readouterr().out
    assert "Terminal window" in printed, "and it does say which it found"
    assert code != 0, "answering is not being supervised, and the exit code must not say it is"


def test_make_status_exits_zero_for_a_login_service_that_is_answering(tmp_path, monkeypatch, capsys):
    """The other half: the ordinary installed Mac still passes, or the check above would be a
    status command that never succeeds."""
    _installed_mac(monkeypatch, tmp_path, health=HEALTHY, pid=True)
    assert installer.status(8000) == 0
    assert "login service" in capsys.readouterr().out


def test_make_status_exits_non_zero_when_nothing_answers(tmp_path, monkeypatch, capsys):
    _installed_mac(monkeypatch, tmp_path, health=None, pid=False)
    assert installer.status(8000) != 0
    assert "not answering" in capsys.readouterr().out


def test_the_installer_keeps_no_second_way_to_run_launchctl(tmp_path):
    """A7. `launchctl(*args)` here was the installer's own wrapper, from before the verbs
    moved into scripts/service.py. Nothing has called it since. A second, unused path to the
    one external command this appliance runs is exactly what a security scan has to rule out
    by reading, so it is gone rather than explained."""
    source = (SCRIPTS / "install_launchd.py").read_text(encoding="utf-8")
    assert "def launchctl(" not in source
    assert "subprocess.run(" not in source, "every external command goes through service.Runner"
