#!/usr/bin/env python3
"""make up — everything the tablet needs, in one terminal window.

Starts the backend as a child of this process, prefixes its output, makes sure Tailscale is
serving port 8000 over HTTPS (once, in the background, where it persists), waits for /health and
prints the address to open. Ctrl-C stops it. If the backend dies it is restarted with a short
back-off.

`make dev` is the same backend with auto-reload for working on the code; `make install` is the
no-window way, a systemd service that starts at boot. The local whisper-server this used to start
beside the backend was deleted on the owner's ruling of 8 October (DEC-071, ruling 39).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402

from config.settings import Settings, get_settings  # noqa: E402

BACKOFF_S = (2, 4, 8, 16, 30)
# A child that dies this soon after starting, this many times in a row, is not going to start:
# a missing token, a port in use, a billing guard. Say so once and stop, rather than filling
# the window with the same traceback until the owner closes it.
QUICK_EXIT_S = 10.0
MAX_QUICK_EXITS = 4


def backend_command(settings: Settings, *, reload: bool = False) -> list[str]:
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", settings.host, "--port", str(settings.port),
        # The app judges who opened each connection itself (app/identity.py); uvicorn's own
        # proxy-header handling would replace that address with the forwarded one first.
        "--no-proxy-headers",
    ]
    if reload:
        cmd.append("--reload")
    return cmd


def commands(
    settings: Settings, *, reload: bool = False, port_open=lc.port_open,
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """(children to run, notes to print). The backend is skipped when something already
    answers on its port — the service from `make install`, usually — rather than started
    twice."""
    children: list[tuple[str, list[str]]] = []
    notes: list[str] = []
    if port_open(settings.host, settings.port):
        notes.append(
            f"the backend is already running on port {settings.port} — probably the service "
            "from `make install` (make status / make uninstall). Not starting a second."
        )
    else:
        children.append(("backend", backend_command(settings, reload=reload)))
    return children, notes


class Child:
    def __init__(self, name: str, cmd: list[str]) -> None:
        self.name = name
        self.cmd = cmd
        self.process: subprocess.Popen | None = None
        self.restarts = 0
        self.quick_exits = 0
        self.started_at = 0.0
        self.stopping = False
        self.given_up = False

    def start(self) -> None:
        import time

        self.started_at = time.time()
        self.process = subprocess.Popen(  # noqa: S603 — our own commands
            self.cmd, cwd=lc.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        threading.Thread(target=self._pump, args=(self.process,), daemon=True).start()

    def _pump(self, process: subprocess.Popen) -> None:
        prefix = f"[{self.name:<7}] "
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(prefix + line)
            sys.stdout.flush()

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        self.stopping = True
        if not self.alive:
            return
        assert self.process is not None
        try:
            self.process.terminate()
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev", action="store_true", help="run the backend with auto-reload")
    parser.add_argument("--no-tailscale", action="store_true", help="do not touch the Tailscale route")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # readable when piped through tee
    except (AttributeError, ValueError):
        pass

    settings = get_settings()
    children_spec, notes = commands(settings, reload=args.dev)
    print("CROOKS Assistant — starting\n" + "─" * 74)
    for note in notes:
        print(f"  note   {note}")

    children = [Child(name, cmd) for name, cmd in children_spec]
    for child in children:
        print(f"  start  {child.name}: {' '.join(child.cmd)}")
        child.start()
    if not children:
        # Everything is already running (the installed service, usually). The owner still
        # needs the address and a health line; then there is nothing for this window to do.
        if not args.no_tailscale:
            host, note = lc.ensure_serve(settings.port)
            print(f"  https  https://{host}/  ({note})" if host else f"  https  not available: {note}")
        print(f"  health {lc.summarise_health(lc.fetch_health(f'http://{settings.host}:{settings.port}/health'))}")
        print("  nothing to start here; the running copy is answering. `make status` for more.")
        return 0

    stop = threading.Event()

    def on_signal(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    if not args.no_tailscale:
        host, note = lc.ensure_serve(settings.port)
        if host:
            print(f"  https  https://{host}/  ({note})")
        else:
            print(f"  https  not available: {note}\n         run once: tailscale serve --bg {settings.port}")

    backend = next((c for c in children if c.name == "backend"), None)
    health = lc.wait_for_health(
        f"http://{settings.host}:{settings.port}/health", timeout_s=45,
        still_starting=(lambda: backend.alive) if backend is not None else None,
    )
    print("─" * 74)
    print(f"  health {lc.summarise_health(health)}")
    print("  Ctrl-C stops everything. Logs: logs/assistant.log (redacted) and this window.")
    print("─" * 74)

    import time

    exit_code = 0
    while not stop.is_set():
        for child in children:
            if child.alive or child.stopping or child.given_up:
                continue
            code = child.process.returncode if child.process else None
            if time.time() - child.started_at < QUICK_EXIT_S:
                child.quick_exits += 1
            else:
                child.quick_exits = 0
            if child.quick_exits >= MAX_QUICK_EXITS:
                child.given_up = True
                print(
                    f"[{child.name:<7}] keeps exiting straight away (code {code}); giving up on it. "
                    "The reason is in its output above. Fix it, then Ctrl-C and `make up` again."
                )
                exit_code = 1
                continue
            delay = BACKOFF_S[min(child.restarts, len(BACKOFF_S) - 1)]
            child.restarts += 1
            print(f"[{child.name:<7}] exited with {code}; restarting in {delay}s (restart {child.restarts})")
            if stop.wait(delay):
                break
            child.start()
        if children and all(c.given_up for c in children):
            print("  every service has given up; stopping.")
            break
        stop.wait(1.0)

    print("\n  stopping…")
    for child in reversed(children):
        child.stop()
    print("  stopped.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
