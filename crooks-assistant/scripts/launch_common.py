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


def fetch_health(url: str, timeout_s: float = 8.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 — loopback
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


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
    "terminology": "product names",
}


def summarise_health(data: dict | None) -> str:
    """One line: what is up, what is not, in the owner's words. The detail is in the settings
    sheet and the log."""
    if not data:
        return "the assistant is not answering"
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
