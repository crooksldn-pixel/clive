"""The lifecycle layer's shared verdict: which state CROOKS OS is in, and the boiler and the window.

scripts/service.py is the vocabulary scripts/service_linux.py is built from: the states, the one
verdict that decides between them, and the rule that nothing about any window is an input to it.
The server's start, stop and restart are tested in tests/test_service_linux.py against a
systemd double. This file tested the Mac's launchd lifecycle as well until the Mac runtime was
deleted on the owner's ruling of 8 October (DEC-071, ruling 38); what is left here is what the
server's lifecycle still decides through this file.
"""

from __future__ import annotations

import inspect

import pytest

from scripts import service


def health_doc(**over) -> dict:
    doc = {"status": "ok", "build": "b-1", "checks": {"speech": {"ok": True, "detail": "scribe"},
                                                      "claude": {"ok": True, "detail": "cli"},
                                                      "shopify": {"ok": True, "detail": "store"}}}
    doc.update(over)
    return doc


def agent(*, loaded=True, pid=None, last_exit_code=0, installed=True) -> dict:
    return {"label": "x", "installed": installed, "loaded": loaded, "pid": pid,
            "last_exit_code": last_exit_code, "detail": ""}


# ------------------------------------------------- the window is not the boiler


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
def test_every_state_the_service_can_actually_be_found_in(answering, health, agents, expected):
    assert service.running_state(answering=answering, health=health, agents=agents)["state"] == expected


def test_running_but_unwell_is_still_running():
    """A Shopify outage is not the service being off, and an owner who is told "stopped"
    when it is running will press Start, which will do nothing, twice."""
    verdict = service.running_state(answering=True, health=health_doc(), agents=[agent(pid=1)],
                                    unwell=["shopify"])
    assert verdict["state"] == service.UNHEALTHY and verdict["crooks_os"] == "running"
    assert verdict["healthy"] is False and "shopify" in verdict["human"]


def test_the_verdict_has_no_input_at_all_for_whether_a_window_is_open():
    """§5.3, and the reason this function has the signature it has. Closing a window must not
    be able to change the answer, and the way to guarantee that is for there to be nothing to
    pass in about the window. Four inputs: the port, /health, the supervisor's services, and
    which essentials the caller found down."""
    parameters = inspect.signature(service.running_state).parameters
    assert set(parameters) == {"answering", "health", "agents", "unwell"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    running = service.running_state(answering=True, health=health_doc(), agents=[agent(pid=1)])
    assert running["state"] == service.RUNNING and "running as a service" in running["human"]


def test_a_backend_started_in_a_terminal_session_is_named_as_one():
    """And it is a different fact from the service being up, because ending that session WILL
    stop it."""
    verdict = service.running_state(answering=True, health=health_doc(), agents=[agent(pid=None)])
    assert verdict["state"] == service.RUNNING_WINDOW and verdict["supervised"] is False
    assert "Ending that session WILL stop it" in verdict["human"]


def test_the_shared_vocabulary_names_no_mac():
    """The Mac's launchd half went on 8 October (DEC-071, ruling 38): nothing the server's
    lifecycle says through this file names a Mac, a login service or launchd."""
    source = (service.HERE / "service.py").read_text(encoding="utf-8")
    assert "class Launchd" not in source and "LAUNCHCTL" not in source
    for state in service.STATES:
        words = service.running_state(
            answering=state in (service.RUNNING, service.RUNNING_WINDOW, service.STALE),
            health=health_doc() if state in (service.RUNNING, service.RUNNING_WINDOW) else None,
            agents=[agent(pid=1 if state != service.RUNNING_WINDOW else None)],
        )["human"]
        assert "Mac" not in words and "login service" not in words, words
