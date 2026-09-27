#!/usr/bin/env python3
"""`make accept`: everything that can be proved about CROOKS Assistant without a Mac, a store,
an inbox or a voice credit, in one command, with numbers.

    lint            ruff over app, config, scripts and tests
    syntax          node --check over every page script
    node tests      the renderer, the service worker and the telemetry under Node
    pytest          the offline suite (the live tests are deselected)
    server          a backend on a free port, its logs in a temporary directory
    latency         medians over repeated requests to the endpoints the tablet hits
    sizes           the prompt, the tool schemas, and the page files raw and gzipped
    browser         the page in a real Chromium, when Playwright is installed (skipped otherwise)

Exit status is non-zero when anything fails. Nothing here spends a credit or touches
production data: the browser checks answer /speak and /actions with stubs, and the backend
runs with writes off, as it ships.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv" / "bin"
PY = str(VENV / "python") if (VENV / "python").exists() else sys.executable
NODE = shutil.which("node")
BOLD, DIM, RED, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"

# What "fast enough on this machine" means for a request that does no external work. Generous
# on purpose: the point is a regression that turns 3 ms into 300 ms, not a slow laptop.
LATENCY_BOUNDS_MS = {"/ping": 150.0, "/state/none": 150.0, "/": 250.0, "/static/app.js": 250.0, "/manifest.webmanifest": 150.0}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool | None, str]] = []

    def add(self, name: str, ok: bool | None, detail: str = "") -> None:
        self.rows.append((name, ok, detail))
        mark = f"{GREEN}PASS{RESET}" if ok else (f"{YELLOW}SKIP{RESET}" if ok is None else f"{RED}FAIL{RESET}")
        print(f"  {mark}  {name}{(' · ' + DIM + detail + RESET) if detail else ''}", flush=True)

    @property
    def ok(self) -> bool:
        return all(ok is not False for _, ok, _ in self.rows)


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env or os.environ.copy(), capture_output=True, text=True, timeout=timeout)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, *, gzip_ok: bool = False, timeout: float = 10.0) -> tuple[int, bytes, dict]:
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"} if gzip_ok else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — loopback only
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def post(url: str, body: dict | None = None, *, timeout: float = 10.0) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body or {}).encode("utf-8"), method="POST", headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — loopback only
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            return {"code": f"http {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"code": f"{type(exc).__name__}: {exc}"}


def wait_for(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if get(url, timeout=2.0)[0] == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.15)
    return False


def median_ms(url: str, n: int, *, gzip_ok: bool = False) -> float:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        get(url, gzip_ok=gzip_ok)
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-browser", action="store_true", help="skip the Chromium checks even if Playwright is installed")
    parser.add_argument("--shots", default="", help="directory for the browser's screenshots (default: a temporary one, printed)")
    parser.add_argument("--json", default="", help="write the full report as JSON here")
    args = parser.parse_args()
    report = Report()
    started = time.time()
    metrics: dict = {}

    print(f"{BOLD}CROOKS Assistant · acceptance{RESET}  {DIM}{ROOT}{RESET}")

    # ---- static checks
    lint = run([str(VENV / "ruff"), "check", "app", "config", "scripts", "tests"])
    report.add("ruff", lint.returncode == 0, (lint.stdout + lint.stderr).strip().splitlines()[-1] if lint.returncode else "clean")
    if NODE:
        bad = [p.name for p in (ROOT / "web").glob("*.js") if run([NODE, "--check", str(p)]).returncode != 0]
        report.add("node --check", not bad, ", ".join(bad) or f"{len(list((ROOT / 'web').glob('*.js')))} files parse")
        for test in ("ui.test.js", "sw.test.js", "telemetry.test.js", "fold.test.js", "collide.test.js",
                     "notify.test.js", "touch.test.js"):
            result = run([NODE, "--test", str(ROOT / "tests" / "web" / test)], timeout=300)
            passed = next((line for line in result.stdout.splitlines() if line.startswith("# pass")), "")
            report.add(f"node {test}", result.returncode == 0 and "# fail 0" in result.stdout, passed.replace("# ", "") or result.stderr[-300:])
    else:
        report.add("node --check", None, "node is not installed here")

    # ---- the offline suite
    tests = run([str(VENV / "pytest"), "-q", "-m", "not live", "-p", "no:cacheprovider"], timeout=1200)
    summary = next((line for line in reversed(tests.stdout.splitlines()) if "passed" in line or "failed" in line), tests.stdout[-200:])
    report.add("pytest (offline)", tests.returncode == 0, summary.strip())
    metrics["pytest"] = summary.strip()

    # ---- a backend of its own
    state_dir = Path(tempfile.mkdtemp(prefix="crooks-accept-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({
        "CROOKS_LOG_DIR": str(state_dir / "logs"), "CROOKS_BENCH_AUDIO_DIR": str(state_dir / "bench"),
        "CROOKS_SAVE_CAPTURES": "false", "CROOKS_WRITES_ENABLED": "false",
        # Its own private backend, asked only from here: the owner-only routes (the test
        # session) answer the server itself, and nothing on it can apply a change.
        "CROOKS_ALLOWED_LOGINS": "acceptance@localhost.invalid", "CROOKS_WRITES_LOCAL_OWNER": "true",
    })
    log = open(state_dir / "uvicorn.log", "ab")
    server = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", str(port), "--no-proxy-headers"], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        t0 = time.perf_counter()
        up = wait_for(f"{base}/ping", 40)
        boot_ms = (time.perf_counter() - t0) * 1000
        report.add("server starts", up, f"{boot_ms:.0f} ms to /ping")
        metrics["boot_ms"] = round(boot_ms)
        if not up:
            print((state_dir / "uvicorn.log").read_text()[-1500:])
            return finish(report, args, metrics, started, state_dir)

        # ---- latency medians
        latency = {}
        for path, n in (("/ping", 30), ("/state/none", 20), ("/", 10), ("/static/app.js", 10), ("/manifest.webmanifest", 10)):
            latency[path] = round(median_ms(f"{base}{path}", n, gzip_ok=True), 1)
        slow = {p: ms for p, ms in latency.items() if ms > LATENCY_BOUNDS_MS[p]}
        report.add("latency medians", not slow, "  ".join(f"{p} {ms} ms" for p, ms in latency.items()))
        metrics["latency_ms"] = latency
        status, body, headers = get(f"{base}/health")
        health = json.loads(body) if status == 200 else {}
        checks = health.get("checks", {})
        report.add("/health answers", status == 200 and "checks" in health, ", ".join(f"{k}:{'ok' if v.get('ok') else 'x'}" for k, v in checks.items()))
        # "writes: ok" is true of a switched-off write path, which is not what it looks like.
        writes = health.get("writes") or {}
        report.add("writes state named, not just scored", bool(writes.get("state")),
                   f"{writes.get('state', '?')} — {writes.get('detail', '')[:80]}")

        # ---- sizes: what the tablet downloads and what the model reads
        sizes = {}
        for path in ("/", "/static/app.js", "/static/ui.js", "/static/telemetry.js", "/static/collide.js", "/static/touch.js", "/static/notify.js", "/static/style.css", "/static/orb.js", "/static/audio-viz.js", "/sw.js"):
            _, raw, _ = get(f"{base}{path}")
            _, packed, packed_headers = get(f"{base}{path}", gzip_ok=True)
            encoding = next((v for k, v in packed_headers.items() if k.lower() == "content-encoding"), "")
            sizes[path] = {"raw": len(raw), "wire": len(packed), "encoding": encoding}
        total_raw = sum(s["raw"] for s in sizes.values())
        total_wire = sum(s["wire"] for s in sizes.values())
        report.add("page files travel compressed", total_wire < total_raw * 0.5, f"{total_raw / 1024:.0f} KB raw → {total_wire / 1024:.0f} KB on the wire")
        metrics["sizes"] = sizes
        sys.path.insert(0, str(ROOT))
        from app.kb.loader import build_system_prompt, load
        from app.tools import gmail_tools, registry, shopify_tools  # noqa: F401
        from config.settings import get_settings

        prompt = build_system_prompt(load(get_settings().kb_dir))
        specs = [s for s in registry.all_specs() if not s.name.startswith("mock_") and s.write is None and s.batch is None and s.tier.value != "RED"]
        schema_chars = sum(len(json.dumps(s.input_schema)) + len(s.description) for s in specs)
        report.add("prompt and tools measured", True, f"prompt {len(prompt):,} chars · {len(specs)} read tools, {schema_chars:,} schema chars")
        metrics["prompt_chars"] = len(prompt)
        metrics["tools_offered_read_only"] = len(specs)
        metrics["tool_schema_chars"] = schema_chars

        # ---- the page in a real browser
        if args.no_browser or not NODE:
            report.add("browser checks", None, "skipped by request" if args.no_browser else "node is not installed here")
        else:
            probe = run([NODE, "-e", "require('playwright')"])
            if probe.returncode != 0:
                report.add("browser checks", None, "Playwright is not installed (npm i -g playwright); skipped")
            else:
                shots = Path(args.shots) if args.shots else state_dir / "shots"
                shots.mkdir(parents=True, exist_ok=True)
                # A test session for the browser run: the page joins it from /health, and what
                # it reports lands in the backend's own timeline, proven below.
                session = post(f"{base}/test-session/start", {"name": "acceptance"})
                report.add("test session starts on the Mac", bool(session.get("started")), session.get("test_session_id", session.get("detail", "")))
                browser = run([NODE, str(ROOT / "scripts" / "browser" / "accept.js"), base, str(shots)], timeout=600)
                try:
                    result = json.loads(browser.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    result = {"ok": False, "checks": [{"name": "browser run", "ok": False, "detail": (browser.stdout + browser.stderr)[-500:]}]}
                for check in result.get("checks", []):
                    report.add(f"browser · {check['name']}", bool(check["ok"]), check.get("detail", "")[:160])
                metrics["turn_timing_ms"] = result.get("timing", {})
                metrics["screenshots"] = str(shots)
                print(f"  {DIM}screenshots in {shots}{RESET}")
                stopped = post(f"{base}/test-session/stop")
                timeline_path = Path(str(stopped.get("path") or ""))
                time.sleep(0.3)
                events = [json.loads(line) for line in timeline_path.read_text(encoding="utf-8").splitlines() if line.strip()] if timeline_path.exists() else []
                tablet = [e for e in events if e.get("source") == "tablet"]
                report.add("the tablet's report reached the timeline", bool(stopped.get("stopped")) and any(e.get("kind") == "tablet_render" for e in tablet), f"{len(events)} events, {len(tablet)} from the tablet")
                try:
                    from app.observability.report import write_report

                    written = write_report(timeline_path, state_dir / "reports")
                    text = written.read_text(encoding="utf-8")
                    report.add("a report is written from the timeline", "## 12. Top improvement opportunities" in text and "## 7. UI usage" in text, str(written))
                    metrics["test_session_report"] = str(written)
                except Exception as exc:  # noqa: BLE001
                    report.add("a report is written from the timeline", False, f"{type(exc).__name__}: {exc}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    return finish(report, args, metrics, started, state_dir)


def finish(report: Report, args, metrics: dict, started: float, state_dir: Path) -> int:
    seconds = time.time() - started
    failed = [name for name, ok, _ in report.rows if ok is False]
    print()
    skipped = [name for name, ok, _ in report.rows if ok is None]
    if report.ok:
        note = f", {len(skipped)} skipped ({', '.join(skipped)})" if skipped else ""
        print(f"{GREEN}{BOLD}ACCEPTED{RESET}  {len(report.rows) - len(skipped)} checks in {seconds:.0f} s{note}")
    else:
        print(f"{RED}{BOLD}NOT ACCEPTED{RESET}  {len(failed)} failing: {', '.join(failed)}  {DIM}({seconds:.0f} s){RESET}")
    print(f"{DIM}server log: {state_dir / 'uvicorn.log'}{RESET}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "ok": report.ok, "seconds": round(seconds, 1), "metrics": metrics,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in report.rows],
        }, indent=2), encoding="utf-8")
        print(f"{DIM}report: {args.json}{RESET}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
