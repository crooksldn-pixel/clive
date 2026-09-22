"""The lifecycle layer: start, stop, restart, and the difference between a window and a boiler.

WHAT THIS FILE CANNOT TEST, stated before anything it can. There is no launchctl on this
machine and no macOS for one to run on, so nothing here proves that `launchctl bootstrap
gui/501 …` is accepted, that `kickstart -k` is the right verb for this macOS, or that a
LaunchAgent written from these templates actually loads. Every one of those is asserted as
"this is the command we would run", and nothing more. What IS tested is the whole of the
decision-making around them — which command, in which order, in which state, and above all
what is concluded from each answer — because that is where this layer would lie.

The lie it would most likely tell is the §26 one, and it has its own test below: launchctl
exits 0, the service dies on its first import, and a layer that reports success from an exit
code tells the owner his appliance is running. It is not enough for the process to have been
started. /health has to answer.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from scripts import service
from tests.fake_launchd import LaunchdDouble

LABELS = ("com.crooks.assistant", "com.crooks.whisper")
# What `launchctl print gui/501/com.crooks.assistant` prints, trimmed to the three lines this
# layer reads. The real output is a hundred lines of tree; reading it by name rather than by
# position is why only these three have to be right.
PRINTED_RUNNING = """\tcom.crooks.assistant = {
\tactive count = 1
\tstate = running
\tpid = 4242
\tlast exit code = 0
}"""
# The same tree for a service launchd holds and has no process for. Kept because the reader
# of `printed_fields` has to be shown both shapes; the Mac double below expresses this state
# as `pid=False, last_exit_code=1` rather than as a blob of text.
PRINTED_CRASHED = """\tstate = not running
\tlast exit code = 1"""


def health_doc(**over) -> dict:
    doc = {"status": "ok", "build": "b-1", "checks": {"speech": {"ok": True, "detail": "scribe"},
                                                      "claude": {"ok": True, "detail": "cli"},
                                                      "shopify": {"ok": True, "detail": "store"}}}
    doc.update(over)
    return doc


class Mac:
    """A Mac, on a machine that is not one. Everything the layer asks goes through `machine`;
    everything it runs goes through a LaunchdDouble, which holds the two facts real launchd
    holds — which labels are LOADED and which of those have a process — and enforces the rule
    that made this file worth rewriting: kickstart on a job that is not loaded fails.

    The clock only moves when something sleeps, so a ninety-second wait costs a test nothing
    and can still be asserted about.

    `installed` writes the plist FILES; `loaded` is whether launchd has the jobs. They are
    separate arguments because they are separate facts, and confusing them is A1.
    """

    def __init__(self, tmp_path, *, installed=True, loaded=None, pid=True, last_exit_code=0,
                 health=None, port_open=False, route=("crooks.ts.net", ""), launchctl=True,
                 venv=True, repo=True, macos=True):
        self.agent_dir = tmp_path / "LaunchAgents"
        self.agent_dir.mkdir(exist_ok=True)
        if installed:
            for label in LABELS:
                (self.agent_dir / f"{label}.plist").write_text("<plist/>", encoding="utf-8")
        self.root = tmp_path / "checkout"
        if repo:
            (self.root / "app").mkdir(parents=True, exist_ok=True)
            (self.root / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
        if venv:
            (self.root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (self.root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        self.state = {"health": health, "port_open": port_open, "route": route}
        self.clock = {"t": 0.0}
        self.reads = 0
        has_jobs = installed if loaded is None else loaded
        self.double = LaunchdDouble(
            loaded=LABELS if has_jobs else (),
            running=LABELS if (has_jobs and pid) else (),
            last_exit_code=last_exit_code, absent=not launchctl,
        )
        self.runner = self.double
        self.machine = service.Machine(
            runner=self.runner, read_health=self._read, port_open=lambda: self.state["port_open"],
            ensure_route=lambda: self.state["route"], is_macos=lambda: macos,
            sleep=self._sleep, now=lambda: self.clock["t"], log_dir=tmp_path / "logs",
        )
        self.launchd = service.Launchd(self.machine, agent_dir=self.agent_dir, root=self.root, uid=501)

    # What else is true on this Mac when a service really starts, or really stops. These hang
    # off the double rather than off a replacement runner, so a test can say "and then it came
    # up" without also throwing away launchd's rules.

    def comes_up_when_started(self, doc=None):
        self.double.on_kickstart = lambda _label: self.state.update(health=doc or health_doc(), port_open=True)
        return self

    def dies_when_started(self):
        """kickstart exits 0, the process dies on its first import: §26's lie, in a hook."""
        self.double.on_kickstart = lambda _label: self.state.update(health=None)
        return self

    def goes_quiet_when_stopped(self):
        self.double.on_bootout = lambda _label: self.state.update(health=None, port_open=False)
        return self

    def launchd_drops_it_when_started(self):
        """kickstart exits 0 and what comes back is nothing: no pid and no longer loaded.
        This is the state waiting is pointless in, and the one `still_starting` exists for."""

        def gone(label):
            self.double.running.discard(label)
            self.double.loaded.discard(label)
            self.state["health"] = None

        self.double.on_kickstart = gone
        return self

    def _read(self, fresh=False):
        self.reads += 1
        return self.state["health"]

    def _sleep(self, seconds):
        self.clock["t"] += seconds

    def start(self, **kw):
        return service.start(self.machine, self.launchd, port=8000, **kw)

    def stop(self, **kw):
        return service.stop(self.machine, self.launchd, port=8000, **kw)

    def restart(self, **kw):
        return service.restart(self.machine, self.launchd, port=8000, **kw)

    def life(self, **kw):
        return service.lifecycle(self.machine, self.launchd, port=8000, **kw)

    def verbs(self) -> list[str]:
        """The launchctl verbs actually run, in order — which is most of what can be checked
        from a machine with no launchctl."""
        return [call[1] for call in self.machine.runner.calls
                if call and call[0] == "launchctl" and len(call) > 1]


# --------------------------------------------------------------- reading what launchd says


def test_the_three_lines_this_layer_reads_are_read_by_name():
    fields = service.printed_fields(PRINTED_RUNNING)
    assert fields["state"] == "running" and fields["pid"] == "4242" and fields["last exit code"] == "0"
    crashed = service.printed_fields(PRINTED_CRASHED)
    assert crashed["state"] == "not running" and crashed["last exit code"] == "1" and "pid" not in crashed
    assert service.printed_fields("") == {}
    assert service.printed_fields("no equals signs here") == {}


def test_an_agent_launchd_has_never_heard_of_is_not_loaded_and_is_not_an_error(tmp_path):
    mac = Mac(tmp_path, installed=False, loaded=False)
    row = mac.launchd.state("com.crooks.assistant")
    assert row["installed"] is False and row["loaded"] is False
    assert row["pid"] is None and row["last_exit_code"] is None


def test_a_crashing_agent_is_loaded_with_no_pid_and_a_reason(tmp_path):
    mac = Mac(tmp_path, pid=False, last_exit_code=1)
    row = mac.launchd.state("com.crooks.assistant")
    assert row["loaded"] is True and row["pid"] is None and row["last_exit_code"] == 1


# ------------------------------------------------- the window is not the boiler


def agent(*, loaded=True, pid=None, last_exit_code=0, installed=True) -> dict:
    return {"label": "x", "installed": installed, "loaded": loaded, "pid": pid,
            "last_exit_code": last_exit_code, "detail": ""}


@pytest.mark.parametrize(("answering", "health", "agents", "expected"), [
    (True, health_doc(), [agent(pid=1)], service.RUNNING),
    (True, health_doc(), [agent(pid=None)], service.RUNNING_WINDOW),
    (True, None, [agent(pid=1)], service.STALE),
    (False, None, [agent(pid=1)], service.STARTING),
    (False, None, [agent(pid=None, last_exit_code=1)], service.CRASH_LOOPING),
    (False, None, [agent(pid=None, last_exit_code=0)], service.STOPPED),
    (False, None, [agent(loaded=False, installed=False)], service.NOT_INSTALLED),
    (False, None, [], service.NOT_INSTALLED),
])
def test_every_state_the_mac_can_actually_be_found_in(answering, health, agents, expected):
    assert service.running_state(answering=answering, health=health, agents=agents)["state"] == expected


def test_running_but_unwell_is_still_running():
    """A Shopify outage is not the appliance being off, and an owner who is told "stopped"
    when it is running will press Start, which will do nothing, twice."""
    verdict = service.running_state(answering=True, health=health_doc(), agents=[agent(pid=1)],
                                    unwell=["shopify"])
    assert verdict["state"] == service.UNHEALTHY and verdict["crooks_os"] == "running"
    assert verdict["healthy"] is False and "shopify" in verdict["human"]


def test_the_verdict_has_no_input_at_all_for_whether_the_app_is_open():
    """§5.3, and the reason this function has the signature it has. Closing the CROOKS Control
    window must not be able to change the answer, and the way to guarantee that is for there
    to be nothing to pass in about the window. Four inputs: the port, /health, the Mac's
    agents, and which essentials the caller found down."""
    parameters = inspect.signature(service.running_state).parameters
    assert set(parameters) == {"answering", "health", "agents", "unwell"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    running = service.running_state(answering=True, health=health_doc(), agents=[agent(pid=1)])
    assert running["state"] == service.RUNNING and "not stop it" in running["human"]
    assert "does not stop CROOKS OS" in service.WINDOW_NOTE


def test_a_backend_started_in_a_terminal_window_is_named_as_one(tmp_path):
    """And it is a different fact from the login service being up, because the window closing
    WILL stop that one. An appliance that cannot tell them apart tells the owner his Mac is
    safe to close when it is not."""
    mac = Mac(tmp_path, health=health_doc(), pid=False)   # loaded, no pid
    life = mac.life()
    assert life["state"] == service.RUNNING_WINDOW and life["supervised"] is False
    assert "Closing that window WILL stop it" in life["human"]


# --------------------------------------------------------------------------- start


def test_start_from_a_mac_where_nothing_has_ever_been_installed(tmp_path):
    """The state §5.2 is about: nothing running, nothing registered, and the owner has never
    opened a Terminal. Start has to install the login service and then start it."""
    mac = Mac(tmp_path, installed=False, loaded=False, health=None).comes_up_when_started()
    out = mac.start()
    assert out["ok"] is True and out["next"] == "running"
    assert out["human"] == "CROOKS OS is running."
    assert [s["stage"] for s in out["stages"]] == ["check", "install", "start", "route", "verify"]
    assert "bootstrap" in mac.verbs() and "kickstart" in mac.verbs()
    assert all((mac.agent_dir / f"{label}.plist").exists() for label in LABELS), "the agents were written"


def test_stop_then_start_leaves_the_service_running(tmp_path):
    """A1. The most ordinary sequence an owner performs, and the one that did not work.

    Install, start, stop, start. A bootout leaves the plist FILE exactly where it was — the
    file means INSTALLED and has never meant RUNNING — so a Start that decides "already
    registered" from the file skips the bootstrap, kickstarts a job launchd no longer has,
    and is told "Could not find service". The owner presses Start, reads a refusal he can do
    nothing with, and the appliance stays off.

    Nothing but launchd knows whether a job is loaded, so nothing but launchd may be asked.
    """
    mac = Mac(tmp_path, installed=False, loaded=False, health=None)
    mac.comes_up_when_started().goes_quiet_when_stopped()

    first = mac.start()
    assert first["ok"] is True and first["next"] == "running"

    stopped = mac.stop()
    assert stopped["ok"] is True and stopped["next"] == "stopped"
    assert all((mac.agent_dir / f"{label}.plist").exists() for label in LABELS), \
        "the plists are still on disk — which is what made the file the wrong thing to read"
    assert mac.double.loaded == set(), "and launchd no longer has either job"

    again = mac.start()
    assert again["problem"] is None, again["problem"]
    assert again["ok"] is True and again["next"] == "running"
    assert again["human"] == "CROOKS OS is running."
    assert mac.double.loaded == set(LABELS), "the second start put the jobs back into launchd"
    assert [s["stage"] for s in again["stages"]] == ["check", "install", "start", "route", "verify"]


def test_the_plist_file_being_there_is_not_launchd_having_the_job(tmp_path):
    """A1, stated as the distinction rather than as the sequence. `installed` reads the disk;
    whether launchd has the job is a question only launchd can answer, and Start must ask it.
    """
    mac = Mac(tmp_path, installed=True, loaded=False, health=None).comes_up_when_started()
    assert all(mac.launchd.installed(label) for label in LABELS), "the files are there"
    assert all(not mac.launchd.state(label)["loaded"] for label in LABELS), "launchd is not"

    out = mac.start()
    assert out["ok"] is True, out["problem"]
    assert "bootstrap" in mac.verbs(), "it registered the job rather than assuming it was there"
    kicked = mac.double.ran("kickstart")
    assert kicked and all(mac.double.calls.index(k) > mac.double.calls.index(b)
                          for k in kicked for b in mac.double.ran("bootstrap")), \
        "and every kickstart came after the bootstrap that made it possible"


def test_a_start_on_a_mac_whose_login_service_manager_is_missing_says_which(tmp_path):
    """The install half of A2's distinction. 127 is the manager not being there at all —
    a broken PATH. "The Mac refused to register it as a login service" is a sentence about a
    launchd that had an opinion, and there was no launchd to have one; the owner reads it and
    goes looking for a permission problem that does not exist."""
    mac = Mac(tmp_path, installed=False, loaded=False, health=None, launchctl=False)
    out = mac.start()
    assert out["ok"] is False and out["problem"]["code"] == "supervisor_missing"
    assert out["human"] == "CROOKS OS couldn't start. The Mac's login-service manager did not answer."
    assert "not found" in out["problem"]["developer"]


def test_start_on_a_mac_that_is_already_running_touches_nothing(tmp_path):
    mac = Mac(tmp_path, health=health_doc())
    out = mac.start()
    assert out["ok"] is True and out["next"] == "already_running"
    assert mac.verbs() == ["print", "print"], "it asked, and it did not restart anything"


def test_start_says_so_in_english_when_the_python_side_is_not_installed(tmp_path):
    mac = Mac(tmp_path, venv=False)
    out = mac.start()
    assert out["ok"] is False and out["next"] == "blocked"
    assert out["problem"]["code"] == "python_missing"
    assert out["human"] == "CROOKS OS couldn't start. Python environment unavailable."
    assert ".venv/bin/python" in out["problem"]["developer"], "and the path is behind the expansion"
    assert "kickstart" not in mac.verbs(), "nothing was started on a Mac that cannot run it"


def test_start_says_so_when_the_project_folder_has_moved(tmp_path):
    out = Mac(tmp_path, repo=False, venv=False).start()
    assert out["problem"]["code"] == "repo_missing"
    assert "not where this Mac expects them" in out["human"]


def test_launchctl_exiting_zero_is_not_a_successful_start(tmp_path):
    """THE test in this file. Every command succeeds; the service is loaded; it has a pid; and
    /health never answers, because the backend is dying on an import and launchd is restarting
    it. A layer that reported success from an exit code would light the menu bar green over a
    Mac that cannot do anything at all."""
    mac = Mac(tmp_path, health=None)
    out = mac.start(wait_s=30.0)
    assert "kickstart" in mac.verbs(), "launchctl was run and was happy"
    assert out["ok"] is False and out["next"] == "blocked"
    assert out["problem"]["code"] == "health_timeout"
    assert out["human"] == "CROOKS OS started but never became ready."
    assert "assistant.err.log" in out["problem"]["developer"]
    assert mac.clock["t"] >= 30.0, "it really waited"


def test_a_service_launchd_has_given_up_on_fails_in_a_poll_rather_than_in_a_minute(tmp_path):
    """Waiting ninety seconds for something that is already gone teaches the owner that Start
    takes a minute and a half to fail, which is how a button stops being pressed."""
    mac = Mac(tmp_path, health=None, loaded=False).launchd_drops_it_when_started()
    out = mac.start(wait_s=90.0)
    assert out["problem"]["code"] == "health_timeout"
    assert mac.clock["t"] == 0.0, "it gave up on the first poll"


def test_a_missing_tablet_route_is_a_warning_and_not_a_failed_start(tmp_path):
    """The Mac is up; only the tablet's door is shut. Refusing to call that a start would be
    worse than saying so, and the colour goes AMBER on the next status either way."""
    mac = Mac(tmp_path, health=None, route=(None, "Tailscale is not serving port 8000"))
    mac.comes_up_when_started()
    out = mac.start()
    assert out["ok"] is True
    route = next(s for s in out["stages"] if s["stage"] == "route")
    assert route["state"] == "warn" and "not serving" in route["detail"]


def test_a_stuck_copy_of_our_own_is_cleared_before_starting(tmp_path):
    """Bound the port, will not answer /health. A second copy would fail to bind and restart
    for ever, so the stuck one goes first — and it is only touched because it is ours."""
    mac = Mac(tmp_path, health=None, port_open=True)
    mac.comes_up_when_started().goes_quiet_when_stopped()
    out = mac.start()
    assert out["ok"] is True and mac.double.ran("bootout"), "the stuck copy was really booted out"
    assert [s["stage"] for s in out["stages"]][:2] == ["check", "clear"]
    assert next(s for s in out["stages"] if s["stage"] == "clear")["state"] == "ok"


def test_an_address_held_by_something_that_is_not_ours_is_never_killed(tmp_path):
    """A port held by a process this layer did not register is not this layer's business. It
    says what it found and refuses; the alternative is an appliance that kills whatever is in
    its way, which is how an appliance ends up deleting somebody's work."""
    mac = Mac(tmp_path, installed=False, loaded=False, health=None, port_open=True)
    out = mac.start()
    assert out["ok"] is False and out["problem"]["code"] == "port_busy"
    assert "Something else is already using its address" in out["human"]
    assert mac.verbs() == ["print", "print"], "nothing was booted out and nothing was started"


# --------------------------------------------------------------------------- stop


def test_stop_boots_the_services_out_and_checks_the_address_is_free(tmp_path):
    mac = Mac(tmp_path, health=health_doc(), port_open=True).goes_quiet_when_stopped()
    out = mac.stop()
    assert out["ok"] is True and out["next"] == "stopped" and out["human"] == "CROOKS OS is stopped."
    assert [s["stage"] for s in out["stages"]] == ["stop", "verify"]
    assert "starts again the next time this Mac is logged in" in out["note"]


def test_a_stop_that_did_not_stop_it_says_so(tmp_path):
    """bootout exits 0 for a label that was never loaded, and exits 0 the instant the signal
    is sent. Neither is the fact being asked about."""
    mac = Mac(tmp_path, health=health_doc(), port_open=True)
    out = mac.stop(wait_s=10.0)
    assert out["ok"] is False and out["problem"]["code"] == "stop_refused"
    assert out["human"] == "CROOKS OS is still running."
    assert "bootout" in mac.verbs(), "and it did ask, and launchctl said yes"
    assert mac.clock["t"] >= 10.0


def test_a_bootout_that_never_reached_a_manager_is_not_a_stop_that_was_asked_for(tmp_path):
    """A2. 127 is the login-service manager not being there AT ALL — a Mac whose PATH has been
    broken, or a machine that is not a Mac. Nothing was asked of anything.

    What this said instead was "2 service(s) asked to stop", marked the stage ok, waited the
    full twenty seconds for a port nobody had asked anybody to release, and then reported
    `stop_refused` — "The Mac was asked to stop it and it has not", which is a sentence about
    a launchd that said no. There was no launchd. The outcome has to be honest at the moment
    it is known, and it is known on the first command.
    """
    mac = Mac(tmp_path, health=None, port_open=True, launchctl=False)
    out = mac.stop(wait_s=20.0)
    assert out["ok"] is False
    assert out["problem"]["code"] == "stop_supervisor_missing", "not a launchd that refused"
    assert mac.clock["t"] == 0.0, "it did not wait twenty seconds to say what it knew at once"
    said = next(s for s in out["stages"] if s["stage"] == "stop")
    assert said["state"] == "fail" and "asked to stop" not in said["detail"]
    assert "not found" in out["problem"]["developer"]


def test_a_stop_counts_what_was_actually_asked_and_not_what_it_meant_to_ask(tmp_path):
    """The other half of A2: the sentence names the number of services the Mac was really
    asked about. A bootout of a label launchd does not have exits 3 and asks nothing."""
    mac = Mac(tmp_path, health=None, port_open=True, loaded=False).goes_quiet_when_stopped()
    out = mac.stop(wait_s=10.0)
    asked = next(s for s in out["stages"] if s["stage"] == "stop")
    assert asked["detail"] == "0 service(s) asked to stop" and asked["state"] == "warn"


def test_stopping_something_already_stopped_is_not_a_failure(tmp_path):
    mac = Mac(tmp_path, health=None, pid=False, last_exit_code=1)
    out = mac.stop()
    assert out["ok"] is True and out["next"] == "already_stopped"
    assert "bootout" not in mac.verbs()


def test_a_backend_running_in_a_window_is_not_launchds_to_stop(tmp_path):
    mac = Mac(tmp_path, health=health_doc(), pid=False)   # loaded, no pid
    out = mac.stop()
    assert out["ok"] is False and out["problem"]["code"] == "not_supervised"
    assert "Terminal window" in out["human"] and "Close that window" in out["problem"]["fix"]
    assert "bootout" not in mac.verbs(), "it did not pretend to stop something it cannot"


# --------------------------------------------------------------------------- restart


def test_restart_kickstarts_and_then_reads_health_back(tmp_path):
    mac = Mac(tmp_path, health=health_doc())
    out = mac.restart()
    assert out["ok"] is True and out["next"] == "running"
    assert [s["stage"] for s in out["stages"]] == ["check", "restart", "route", "verify"]
    assert mac.verbs().count("kickstart") == len(LABELS)


def test_a_restart_that_does_not_come_back_is_a_failure(tmp_path):
    """`make restart` printed launchctl's exit code and called it done. This does not."""
    mac = Mac(tmp_path, health=health_doc()).dies_when_started()
    out = mac.restart(wait_s=20.0)
    assert len(mac.double.ran("kickstart")) == len(LABELS), "every service was kicked, and every kick exited 0"
    assert out["ok"] is False and out["problem"]["code"] == "health_timeout"


def test_restart_after_a_stop_is_a_start_and_not_a_kickstart_into_nothing(tmp_path):
    """A1, on the restart side — and this is the one that matters most, because the restore
    half of a failed update calls restart(). A restart that kickstarted a job launchd no
    longer had would report the Mac refusing, with the rolled-back code sitting there unrun.
    """
    mac = Mac(tmp_path, health=health_doc(), port_open=True)
    mac.comes_up_when_started().goes_quiet_when_stopped()
    assert mac.stop()["ok"] is True
    assert mac.double.loaded == set() and all((mac.agent_dir / f"{label}.plist").exists() for label in LABELS)

    out = mac.restart()
    assert out["ok"] is True, out["problem"]
    assert out["stages"][0]["detail"].startswith("not registered as a login service")
    assert mac.double.loaded == set(LABELS), "launchd has the jobs back"


def test_restarting_a_mac_that_was_never_set_up_starts_it(tmp_path):
    """An appliance whose Restart button says "there is nothing to restart" is a tool."""
    mac = Mac(tmp_path, installed=False, loaded=False, health=None).comes_up_when_started()
    out = mac.restart()
    assert out["ok"] is True
    assert out["stages"][0]["detail"].startswith("not registered as a login service")


# --------------------------------------------------------------------- the owner's words


def test_no_failure_the_owner_reads_is_written_for_a_developer():
    """The sentence this layer exists to make impossible is "Process returned exit status 127".
    Every human line is scanned for the words that mean it was written for the person who
    wrote the code, and every one of them has somewhere else to be."""
    for code, (human, fix) in service.PROBLEMS.items():
        text = f"{human} {fix}".lower()
        for word in service.DEVELOPERESE:
            assert word not in text, f"{code} says {word!r} to the owner"
        assert human.endswith("."), f"{code} is not a sentence"
        assert len(human) <= 120, f"{code} is a paragraph, not a headline"
        assert not re.search(r"\b\d{2,3}\b", human), f"{code} quotes a number at the owner"


def test_a_problem_keeps_the_developers_half_where_the_developer_can_find_it():
    made = service.problem("health_timeout", "no answer on 127.0.0.1:8000/health within 90s; see /x/logs/assistant.err.log")
    assert set(made) == {"code", "human", "fix", "developer"}
    assert "127.0.0.1" not in made["human"] and "127.0.0.1" in made["developer"]
    assert made["fix"] and made["fix"] != made["human"]


def test_every_problem_code_is_actually_reachable():
    """A table of beautifully worded errors nothing can raise is a table of fiction."""
    source = (service.HERE / "service.py").read_text(encoding="utf-8")
    for code in service.PROBLEMS:
        assert f'problem("{code}"' in source, f"nothing ever raises {code}"


def test_the_layer_runs_nothing_but_launchctl():
    """The security rule, checked rather than asserted in prose: this layer has one external
    command. No shell, no sudo, no killing by pid, no rm."""
    source = (service.HERE / "service.py").read_text(encoding="utf-8")
    for forbidden in ("shell=True", "os.system", "sudo", "pkill", "kill -", "rm -rf", "os.kill"):
        assert forbidden not in source, f"the lifecycle layer reaches for {forbidden!r}"
    verbs = set(re.findall(r'\[LAUNCHCTL, ([A-Z]+|"[a-z\-]+")', source))
    assert verbs <= {"BOOTSTRAP", "BOOTOUT", "KICKSTART", "PRINT", '"load"'}, verbs


def test_no_document_this_layer_produces_carries_anything_unserialisable(tmp_path):
    """The app reads JSON. A Path or a dataclass in a document is a document the app cannot
    decode, and it would be found on the Mac rather than here."""
    mac = Mac(tmp_path, health=health_doc())
    for out in (mac.start(), mac.stop(), mac.restart()):
        json.dumps(out)
