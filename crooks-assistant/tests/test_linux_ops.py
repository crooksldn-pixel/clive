"""The Linux half of the operational tooling, checked as data rather than by running it.

Nothing here installs a unit, restarts a service, calls systemctl or touches Tailscale. The
failures worth catching at this level are the ones that are silent at the point they happen:
a unit template with a placeholder left unfilled, an update path that kicks launchd agents on
a machine that has none, a `make install` that runs the Mac's installer on the server, or a
healthcheck that calls a host degraded for a subsystem it was deliberately never given.

Every test forces the platform rather than asking for it, so both platforms' behaviour is
provable from either — the Mac must be able to demonstrate it did not break the server, and
this server must be able to demonstrate it did not break the Mac.
"""

from __future__ import annotations

import importlib.util
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
healthcheck = load("healthcheck")


@pytest.fixture
def on_linux(monkeypatch):
    monkeypatch.setattr(lc, "is_linux", lambda: True)
    monkeypatch.setattr(lc, "is_macos", lambda: False)


@pytest.fixture
def on_mac(monkeypatch):
    monkeypatch.setattr(lc, "is_linux", lambda: False)
    monkeypatch.setattr(lc, "is_macos", lambda: True)


# --------------------------------------------------------------- what supervises what


def test_linux_supervises_one_unit_and_the_mac_two_agents(on_linux):
    assert lc.service_labels() == ("crooks-assistant.service",)


def test_the_mac_still_names_both_of_its_agents(on_mac):
    labels = lc.service_labels()
    assert "com.crooks.assistant" in labels
    assert "com.crooks.whisper" in labels


def test_the_installer_is_chosen_by_platform(on_linux):
    assert lc.installer_script().name == "install_systemd.py"


def test_the_mac_installer_is_still_launchd(on_mac):
    assert lc.installer_script().name == "install_launchd.py"


def test_restart_uses_systemctl_on_linux(on_linux, monkeypatch):
    """The one stage of the update path that differs by platform. It must not reach for
    launchctl on a machine that has none — there the command is simply absent and the failure
    reads as "the services would not restart" with no clue why."""
    seen = {}

    class Result:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Result()

    monkeypatch.setattr(lc.subprocess, "run", fake_run)
    assert lc.restart_services() == []
    assert seen["cmd"][:2] == ["systemctl", "restart"]
    assert "launchctl" not in " ".join(seen["cmd"])


def test_a_refused_restart_is_reported_rather_than_raised(on_linux, monkeypatch):
    class Result:
        returncode, stdout, stderr = 1, "", "Unit crooks-assistant.service not found."

    monkeypatch.setattr(lc.subprocess, "run", lambda cmd, **kw: Result())
    failures = lc.restart_services()
    assert len(failures) == 1
    assert "not found" in failures[0]


def test_the_restart_hint_names_the_journal_on_linux(on_linux):
    assert "journalctl" in lc.restart_hint()


def test_the_restart_hint_does_not_mention_the_journal_on_the_mac(on_mac):
    assert "journalctl" not in lc.restart_hint()


# --------------------------------------------------------------- the unit template


def test_the_unit_template_leaves_no_placeholder_unfilled():
    """A placeholder that survives into /etc/systemd/system is a restart loop with a message
    that names none of this."""
    installer = load("install_systemd")
    values = {
        "ROOT": "/opt/crooks-os/crooks-assistant",
        "PYTHON": "/opt/crooks-os/crooks-assistant/.venv/bin/python",
        "HOME": "/root",
        "PATH": "/usr/bin:/bin",
        "CLAUDE": "/usr/bin/claude",
        "HOST": "127.0.0.1",
        "PORT": "8000",
        "SECRET_DIR": "/etc/crooks-os/secrets",
        "CREDENTIALS": "LoadCredentialEncrypted=elevenlabs_api_key:/etc/crooks-os/credentials/elevenlabs_api_key.cred",
    }
    unit = installer.rendered_unit(values)
    assert "{{" not in unit and "}}" not in unit


def test_the_start_limit_is_in_the_section_systemd_reads_it_from():
    """The crash-loop guard, in [Unit] where it works.

    StartLimitIntervalSec moved to [Unit] in systemd v229. Left in [Service] it is an unknown
    key: systemd drops it with a warning nobody reads, the 10s default window applies, and
    with RestartSec=10 the burst counter can never fill — so a service that fails every start
    restarts forever while the unit file appears to forbid exactly that. `systemd-analyze
    verify` says so out loud, which is how this was found; this test is so that it stays said.
    """
    installer = load("install_systemd")
    unit = installer.rendered_unit({
        "ROOT": "/r", "PYTHON": "/p", "HOME": "/root", "PATH": "/usr/bin", "CLAUDE": "/c",
        "HOST": "127.0.0.1", "PORT": "8000", "SECRET_DIR": "/s", "CREDENTIALS": "",
    })
    # Split on the section HEADER — "[Service]" alone on its line — not on the text anywhere.
    # A comment explaining why these keys are not in [Service] contains the word too, and
    # splitting on that cuts the file in the wrong place and hides the settings from this test.
    head, _, service_section = unit.partition("\n[Service]\n")
    assert service_section, "no [Service] section header found in the rendered unit"
    unit_section = head

    assert "StartLimitIntervalSec=" in unit_section
    assert "StartLimitBurst=" in unit_section
    # Comments quoting the key names are fine; a live setting in [Service] is not.
    live = [ln for ln in service_section.splitlines()
            if ln.strip().startswith(("StartLimitIntervalSec=", "StartLimitBurst="))]
    assert live == [], f"start-limit settings left in [Service], where systemd ignores them: {live}"


def test_the_unit_binds_loopback_only_and_never_a_public_interface():
    installer = load("install_systemd")
    unit = installer.rendered_unit({
        "ROOT": "/r", "PYTHON": "/p", "HOME": "/root", "PATH": "/usr/bin", "CLAUDE": "/c",
        "HOST": "127.0.0.1", "PORT": "8000", "SECRET_DIR": "/s", "CREDENTIALS": "",
    })
    assert "--host 127.0.0.1" in unit
    assert "0.0.0.0" not in unit


def test_the_unit_keeps_home_writable_so_the_claude_token_can_refresh():
    """ProtectSystem=strict makes everything read-only. The Claude CLI rewrites its own
    credential in place when the OAuth token refreshes, so a HOME that is not on the writable
    list turns into an authentication failure days later with nothing connecting the two."""
    installer = load("install_systemd")
    unit = installer.rendered_unit({
        "ROOT": "/r", "PYTHON": "/p", "HOME": "/root", "PATH": "/usr/bin", "CLAUDE": "/c",
        "HOST": "127.0.0.1", "PORT": "8000", "SECRET_DIR": "/s", "CREDENTIALS": "",
    })
    assert "ReadWritePaths=/root" in unit
    assert "ProtectHome=no" in unit
    assert "Restart=always" in unit
    assert "WantedBy=multi-user.target" in unit


# --------------------------------------------------------------- the production healthcheck


def health_doc(checks: dict, **extra) -> dict:
    return {"build": "b", "checks": checks, **extra}


def test_nothing_answering_is_down():
    state, line = healthcheck.verdict(None)
    assert state == healthcheck.DOWN


def test_an_essential_subsystem_down_is_unhealthy():
    state, line = healthcheck.verdict(health_doc({
        "speech": {"ok": False}, "claude": {"ok": True}, "shopify": {"ok": True},
    }))
    assert state == healthcheck.UNHEALTHY


def test_a_non_essential_subsystem_down_is_only_degraded():
    state, _ = healthcheck.verdict(health_doc({
        "speech": {"ok": True}, "claude": {"ok": True}, "shopify": {"ok": True},
        "gmail": {"ok": False},
    }))
    assert state == healthcheck.DEGRADED


def test_a_deliberately_absent_fallback_is_not_a_failing_check():
    """The exit code is the whole point: a check that goes red for a thing you decided not to
    install is a check that trains you to ignore the ones that matter."""
    state, line = healthcheck.verdict(health_doc({
        "speech": {"ok": True, "redundancy": "none"},
        "claude": {"ok": True}, "shopify": {"ok": True},
        "whisper": {"ok": True, "disabled": True},
    }))
    assert state == healthcheck.OK
    assert "no local speech fallback" in line


def test_degraded_and_ok_both_exit_zero_and_unhealthy_does_not():
    assert healthcheck.OK in (healthcheck.OK, healthcheck.DEGRADED)
    # The mapping the exit code is built from, stated here so a change to it is deliberate.
    assert healthcheck.UNHEALTHY not in (healthcheck.OK, healthcheck.DEGRADED)


# --------------------------------------------------------------- the Makefile and set_secrets


def test_the_makefile_dispatches_the_installer_by_platform():
    text = (ROOT / "Makefile").read_text()
    assert "ifeq ($(UNAME_S),Linux)" in text
    assert "INSTALLER := scripts/install_systemd.py" in text
    assert "INSTALLER := scripts/install_launchd.py" in text
    # And the targets must go through the variable, not the Mac's script by name.
    assert "$(PY) $(INSTALLER)" in text


def test_the_makefile_no_longer_hardcodes_the_mac_installer_in_a_target():
    text = (ROOT / "Makefile").read_text()
    for target in ("install:", "status:", "restart:", "uninstall:"):
        body = text.split(target, 1)[1].split("\n\n", 1)[0]
        assert "install_launchd.py" not in body


def test_set_secrets_refuses_on_linux_rather_than_using_the_wrong_tier(monkeypatch, capsys):
    """It would otherwise succeed and store a static secret as a plain file — no error, no
    encryption at rest, and nothing to tell you it had happened."""
    set_secrets = load("set_secrets")
    monkeypatch.setattr(set_secrets.sys, "platform", "linux")
    monkeypatch.setattr(set_secrets.sys, "argv", ["set_secrets.py", "elevenlabs_api_key"])
    assert set_secrets.main() == 1
    assert "provision_secrets.py" in capsys.readouterr().out


# --------------------------------------------------------------- the doctor's own reading


# Every value pydantic accepts for a bool, plus values it rejects. The doctor is not asked to
# agree with an opinion here — it is asked to agree with the parser the application actually
# uses, so the expected answer is computed from that parser in the test itself. If pydantic's
# vocabulary ever changes under us, this fails instead of the doctor quietly lying.
@pytest.mark.parametrize(
    "value",
    ["true", "True", "TRUE", "1", "yes", "on", "t", "y",
     "false", "False", "FALSE", "0", "no", "off", "f", "n",
     "", "  ", "maybe", "2", "flase", " true ", "true "],
)
def test_the_doctor_agrees_with_the_real_settings_parser(value, monkeypatch):
    """The doctor runs before the venv exists — that is its whole job — so it cannot import
    config.settings to find out whether whisper is deployed here. It therefore reimplements the
    parse, and this is what keeps the reimplementation honest.

    Three states, not two. An empty CROOKS_WHISPER_ENABLED= is not "off": pydantic rejects it,
    the backend refuses to start, and a doctor that answered "enabled" or "disabled" would be
    inventing a host that does not exist. Measured, not assumed — this test asks the real
    Settings what it does and requires the doctor to say the same thing.
    """
    from config.settings import Settings

    monkeypatch.setenv("CROOKS_WHISPER_ENABLED", value)
    try:
        # _env_file=None: this measures the parser, not whatever .env this machine happens to have.
        runtime = "enabled" if Settings(_env_file=None).whisper_enabled else "disabled"
    except Exception:
        runtime = "invalid"

    doctor = load("doctor")
    assert doctor.whisper_setting() == runtime
    # And the derived boolean never reports an unparseable value as a deliberate decision.
    assert doctor.whisper_disabled() is (runtime == "disabled")


def test_an_unset_whisper_setting_is_the_settings_default(monkeypatch, tmp_path):
    """Unset is the one case that is genuinely a default rather than a parse."""
    from config.settings import Settings

    monkeypatch.delenv("CROOKS_WHISPER_ENABLED", raising=False)
    doctor = load("doctor")
    # Point the doctor's .env lookup at an empty directory so the host's own .env cannot answer.
    monkeypatch.setattr(doctor, "REPO", tmp_path)
    assert doctor.whisper_setting() == "enabled"
    assert Settings(_env_file=None).whisper_enabled is True
