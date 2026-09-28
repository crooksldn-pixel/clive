"""Shared by `make up` (scripts/up.py) and `make install` (scripts/install_launchd.py).

Three things have to be true for the tablet to work: the backend is up on 127.0.0.1:8000,
whisper-server is up on 127.0.0.1:8910 (the fallback recogniser), and Tailscale is serving
port 8000 over HTTPS. This module knows how to find the binaries involved, how to read and set
the Tailscale route, and how to read /health back — so the two launchers can share one answer
to "is it running?".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
LOG_DIR = ROOT / "logs"
LAUNCHD_DIR = ROOT / "launchd"
AGENTS = {
    "com.crooks.assistant": "com.crooks.assistant.plist",
    "com.crooks.whisper": "com.crooks.whisper.plist",
}

# The Linux half. One unit, not two: whisper.cpp is not deployed on the server (no Core ML,
# no model, no build toolchain), so there is nothing for a second service to supervise.
# docs/DEPLOY_LINUX.md says what that costs and why it is deliberate.
SERVICE_UNIT = "crooks-assistant.service"
SYSTEMD_DIR = Path("/etc/systemd/system")
SYSTEMD_UNIT_PATH = SYSTEMD_DIR / SERVICE_UNIT
SYSTEMD_TEMPLATE = ROOT / "deploy" / "systemd" / "crooks-assistant.service"

# The Mac App Store / standalone Tailscale app keeps its CLI inside the bundle.
TAILSCALE_APP = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")


# --------------------------------------------------------------------------- binaries


def find_tailscale() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    return str(TAILSCALE_APP) if TAILSCALE_APP.exists() else None


def find_claude() -> str | None:
    """The claude CLI. `which` first; then the places the installers put it, because launchd
    does not read a shell profile and a PATH-only answer is not enough there."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".claude" / "local" / "claude",
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def service_path(extra: list[str | None] = ()) -> str:
    """A PATH for a supervised service: the directories of every binary the backend spawns,
    then the usual places. Neither launchd nor systemd reads a shell profile — both start with
    almost nothing — and `claude` is a node script that needs `node` beside it."""
    dirs: list[str] = []
    for binary in [find_claude(), shutil.which("node"), find_tailscale(), sys.executable, *extra]:
        if binary:
            directory = str(Path(binary).resolve().parent)
            if directory not in dirs:
                dirs.append(directory)
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
                      str(Path.home() / ".local" / "bin")):
        if directory not in dirs:
            dirs.append(directory)
    return ":".join(dirs)


# The name the Mac has always called it. Same construction on both platforms; the extra
# /opt/homebrew entries are simply absent on Linux and cost nothing.
launchd_path = service_path


# --------------------------------------------------------------------------- supervision


def service_labels() -> tuple[str, ...]:
    """What supervises the assistant here, named as the platform names it. One definition, so
    `crooks-update`, CROOKS Control and the installers cannot disagree about what to restart."""
    return (SERVICE_UNIT,) if is_linux() else tuple(AGENTS)


def restart_services(timeout_s: float = 120.0) -> list[str]:
    """Restart the assistant through whatever supervises it. Returns the failures, empty when
    all is well — the caller decides whether a failure stops a run.

    This is the one place the two platforms differ in the update path: `launchctl kickstart`
    on the Mac, `systemctl restart` on the server. Everything either side of it — the
    fast-forward, the dependency install, the offline suite, the health read — is the same
    code doing the same thing.
    """
    if is_linux():
        out = subprocess.run(
            ["systemctl", "restart", SERVICE_UNIT], capture_output=True, text=True, timeout=timeout_s
        )
        if out.returncode == 0:
            return []
        return [f"{SERVICE_UNIT}: {(out.stderr or out.stdout).strip() or 'systemctl refused'}"]

    domain = f"gui/{uid()}"
    failed = []
    for label in AGENTS:
        out = subprocess.run(
            ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if out.returncode != 0:
            failed.append(f"{label}: {(out.stderr or '').strip() or 'launchctl refused'}")
    return failed


def installer_script() -> Path:
    """The install/status/restart command for this platform, for the Makefile and for the
    buttons CROOKS Control draws."""
    return Path(__file__).resolve().parent / ("install_systemd.py" if is_linux() else "install_launchd.py")


def restart_hint() -> str:
    """What to try when a restart fails, named for the platform the operator is standing on."""
    if is_linux():
        return (
            "If the unit was never installed, run `make install` once. Your code IS updated; "
            f"only the restart failed. Look in: journalctl -u {SERVICE_UNIT} -n 50"
        )
    return (
        "If they were never installed, run `make install` once. Your code IS updated; only "
        "the restart failed."
    )


# --------------------------------------------------------------------------- tailscale serve


def parse_serve_status(text: str, port: int) -> str | None:
    """The ts.net host that `tailscale serve status --json` says is proxying to this port, or
    None when nothing is."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    web = data.get("Web") or {}
    for host_port, spec in web.items():
        handlers = (spec or {}).get("Handlers") or {}
        for handler in handlers.values():
            proxy = str((handler or {}).get("Proxy", "")).rstrip("/")
            if proxy.endswith(f":{port}"):
                return str(host_port).split(":")[0]
    return None


def serve_status(port: int) -> tuple[str | None, str]:
    """(host, problem). host is set when Tailscale is already serving the port."""
    tailscale = find_tailscale()
    if not tailscale:
        return None, "Tailscale is not installed (or its CLI is not on PATH)."
    try:
        out = subprocess.run(
            [tailscale, "serve", "status", "--json"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"could not ask Tailscale: {exc}"
    if out.returncode != 0:
        return None, (out.stderr or out.stdout).strip() or "tailscale serve status failed"
    host = parse_serve_status(out.stdout, port)
    return host, "" if host else f"Tailscale is not serving port {port}"


def ensure_serve(port: int) -> tuple[str | None, str]:
    """Make Tailscale serve the port over HTTPS, in the background, so it survives this
    process and the next reboot. Returns (host, note)."""
    host, problem = serve_status(port)
    if host:
        return host, "already configured"
    tailscale = find_tailscale()
    if not tailscale:
        return None, problem
    try:
        out = subprocess.run(
            [tailscale, "serve", "--bg", str(port)], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"tailscale serve failed: {exc}"
    if out.returncode != 0:
        return None, (out.stderr or out.stdout).strip() or "tailscale serve --bg failed"
    host, problem = serve_status(port)
    return host, "configured now (persists across restarts)" if host else problem


# --------------------------------------------------------------------------- ports


def port_open(host: str, port: int, timeout_s: float = 0.5) -> bool:
    """Is something already listening here? Starting a second copy would fail to bind and
    restart forever, so the launchers ask first."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def url_port(url: str, default: int) -> int:
    try:
        return int(url.rstrip("/").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return default


# --------------------------------------------------------------------------- health


def _loopback(url: str) -> bool:
    """A plain-HTTP URL on this machine's own loopback address, by literal address only."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return False
    return parts.scheme == "http" and host in ("127.0.0.1", "::1")


# Tests: `check(sock) -> (ok, why)` in place of asking the kernel who took the connection.
_listener_check = None


def bind_listener_check(check) -> None:
    global _listener_check
    _listener_check = check


def _server_key(url: str) -> dict[str, str]:
    """The server's own key (app/local_cli.py), for a request to it on loopback, when this user
    can read it and the connection it goes on can be shown to be the service's; nothing otherwise,
    and never for any other address. Only a Linux server can show that (from /proc), so elsewhere
    the key is not even read: a Mac that speaks for the owner answers its own readers in full."""
    if not _loopback(url) or (_listener_check is None and not is_linux()):
        return {}
    try:
        from app import local_cli

        return local_cli.headers()
    except Exception:  # noqa: BLE001 — no key readable here: the reader gets what anyone gets
        return {}


def _taken_by_the_service(sock) -> tuple[bool, str]:
    """Whether the far end of this open connection is held by the service itself (ok, why): the
    kernel's answer (app/identity.py far_end_held_by), never the port's."""
    if _listener_check is not None:
        return _listener_check(sock)
    try:
        from app import identity

        return identity.far_end_held_by(tuple(sock.getsockname()[:2]), tuple(sock.getpeername()[:2]), SERVICE_UNIT)
    except Exception as exc:  # noqa: BLE001 — cannot say is no
        return False, f"who took the connection could not be read: {type(exc).__name__}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed (round 9, A1B-KEY): /health answers where it is asked, and an
    answer that points somewhere else is not the service's."""

    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None


def _open(request: urllib.request.Request, timeout_s: float):
    """Straight to the address, never through an HTTP proxy the environment names and never on to
    wherever a redirect points."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout_s)  # noqa: S310 — loopback


def _read(url: str, headers: dict[str, str], timeout_s: float) -> dict | None:
    try:
        with _open(urllib.request.Request(url, headers=headers), timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _one_connection(url: str, method: str, body: bytes | None, headers: dict[str, str],
                    key: dict[str, str], timeout_s: float) -> tuple[int, bytes] | None:
    """One request, down one connection opened here, to a loopback URL: (status, body).

    With `key` (the server's own, _server_key), the request goes only once the kernel has said the
    service itself took this very connection (round 9, A1B-KEY) — never a second connection that
    another process could have taken in between — and None means that could not be shown and
    nothing at all was sent. Straight to the address: http.client reads no proxy from the
    environment. Never on to a redirect: http.client follows none, so a 3xx is an answer like any
    other and its Location goes nowhere. Raises as the connection does: OSError
    (ConnectionRefusedError when nothing listens, TimeoutError) and http.client.HTTPException."""
    import http.client
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or 80
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    sock = socket.create_connection((host, port), timeout=timeout_s)
    connection = http.client.HTTPConnection(host, port, timeout=timeout_s)
    connection.sock = sock
    try:
        if key:
            ok, _why = _taken_by_the_service(sock)
            if not ok:
                return None
        connection.request(method, target, body=body, headers={**headers, **key, "Connection": "close"})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _read_keyed(url: str, key: dict[str, str], timeout_s: float) -> dict | None:
    """/health with the server's key, down one connection the kernel says the service took
    (_one_connection). Anything but a 200 with a JSON body is None; None too when the far end is
    not shown to be the service, and the key has then not been sent."""
    import http.client

    try:
        answered = _one_connection(url, "GET", None, {}, key, timeout_s)
    except (OSError, http.client.HTTPException):
        return None
    if answered is None or answered[0] != 200:
        return None
    try:
        data = json.loads(answered[1].decode("utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _keyed_route(method: str, path: str) -> bool:
    """Whether the server's key opens this route at all (app/local_cli.py ROUTES): it is sent on
    no other."""
    try:
        from app import local_cli

        return (method.upper(), path.split("?", 1)[0]) in local_cli.ROUTES
    except Exception:  # noqa: BLE001 — no app to ask: no route is the key's
        return False


def call_service(port: int, method: str, path: str, body: bytes | None = None, *,
                 timeout_s: float = 5.0) -> tuple[int, bytes]:
    """One request to the service on this machine's loopback, for the server's own commands
    (scripts/session_ops.py: `make test-session-*` and CROOKS Control's session buttons):
    (status, body), whatever the status.

    The server's key goes with it only on a route the key opens (_keyed_route), only where this
    user can read it and the far end can be shown at all (_server_key), and only down a
    connection the kernel says the service took (_one_connection) — the rule `fetch_health` keeps,
    and for the same reason (S1-KEY-SENDER: this path used urllib, which followed a redirect with
    the key on it, read a proxy from the environment, and never asked who held the port). When
    the service cannot be shown to hold the connection, the same request is made plainly on a
    fresh one and the key stays here: the answer is then what a request made on the server
    without it gets. Raises as the connection does (_one_connection)."""
    url = f"http://127.0.0.1:{port}{path}"
    headers = {"content-type": "application/json"}
    key = _server_key(url) if _keyed_route(method, path) else {}
    if key:
        answered = _one_connection(url, method, body, headers, key, timeout_s)
        if answered is not None:
            return answered
    answered = _one_connection(url, method, body, headers, {}, timeout_s)
    assert answered is not None     # without a key nothing is withheld
    return answered


def fetch_health(url: str, timeout_s: float = 8.0) -> dict | None:
    """/health, or None when nothing answers.

    Where this user can read the server's own key (app/local_cli.py) and the address is its
    loopback, it is asked once, with the key, on a connection the kernel says the service itself
    took — so the host's own readers get the whole document. The key is decided on before anything
    is asked, never because a plain answer came back limited (round 9, A1B-KEY: whatever holds the
    port while the service restarts can answer `limited` to be sent the key). When the service
    cannot be shown to hold the connection, or will not take the key (a build from before it
    opened /health to it), the question is asked plainly instead and the key is not sent. Without
    the key the answer to a reader the owner rule refuses is liveness alone (`limited`), and the
    readers say so rather than read an absent check as a working one."""
    key = _server_key(url)
    if key:
        whole = _read_keyed(url, key, timeout_s)
        if whole is not None:
            return whole
    return _read(url, {}, timeout_s)


def health_limited(data: dict | None) -> bool:
    """Whether /health answered with liveness alone: this reader is not the owner and could not
    read the server's key (app/routes/health.py _liveness)."""
    return isinstance(data, dict) and data.get("limited") is True


def wait_for_health(url: str, timeout_s: float = 45.0, still_starting=None) -> dict | None:
    """Poll /health until it answers or the time is up. `still_starting`, when given, is asked
    each second; False means the thing being waited for has already died, so stop waiting."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = fetch_health(url, timeout_s=8.0)
        if data is not None:
            return data
        if still_starting is not None and not still_starting():
            return None
        time.sleep(1.0)
    return None


PLAIN_NAMES = {
    "claude": "Claude", "speech": "hearing", "scribe": "ElevenLabs hearing", "whisper": "offline hearing",
    "tts": "the voice", "shopify": "Shopify", "gmail": "Gmail", "knowledge_base": "the knowledge base",
}


def summarise_health(data: dict | None) -> str:
    """One line: what is up, what is not, in the owner's words. The detail is in the settings
    sheet and the log."""
    if not data:
        return "the assistant is not answering"
    if health_limited(data):
        return (f"answering ({data.get('status') or '?'}), but the detail is the owner's: "
                "run this as the service's user (root on the server) to read it")
    checks = data.get("checks") or {}
    name = lambda k: PLAIN_NAMES.get(k, k)  # noqa: E731
    ok = [name(k) for k, check in checks.items() if check.get("ok")]
    bad = [name(k) for k, check in checks.items() if not check.get("ok")]
    if not bad:
        return "all good · " + ", ".join(ok)
    return f"partly down · working: {', '.join(ok) or 'nothing'} · NOT working: {', '.join(bad)}"


# --------------------------------------------------------------------------- plists


def render(template: str, values: dict[str, str]) -> str:
    """Fill {{KEY}} placeholders. Every placeholder must be supplied — a plist with a literal
    {{ROOT}} in it is a launchd agent that restarts forever."""
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    if "{{" in out:
        start = out.index("{{")
        raise ValueError(f"unfilled placeholder near: {out[start:start + 30]!r}")
    return out


def plist_values(root: Path = ROOT, python: Path | None = None, home: Path | None = None) -> dict[str, str]:
    python = python or VENV_PYTHON
    home = home or Path.home()
    return {
        "ROOT": str(root),
        "PYTHON": str(python),
        "HOME": str(home),
        "LOGS": str(root / "logs"),
        "PATH": launchd_path([str(python)]),
        "CLAUDE": find_claude() or "",
    }


def env_line(key: str, value: str | int) -> str:
    return f"{key}={value}"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def uid() -> int:
    return os.getuid()
