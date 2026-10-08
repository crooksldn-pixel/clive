"""The loop host's private channel: why each stopped build stopped, in full, for CLIVE and nobody else.

The repository is public (since 7 October 2026), so what the loop publishes on ``clive/control/<host>-status``
keeps counts and states (status.py). What whoever repairs a stopped build needs, the reviewer's findings, the
failing output and the builder's own report (``Dispatcher.stop_reports``), is served here instead, over the
tailnet, to the nodes the operator names:

    GET /v1/stops     ``clive.remote_engineering_private.v1``: one entry per stopped request

- **Tailnet only.** The server binds a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48) or loopback, never
  a wildcard or a public one. Nothing here is written to git or pushed anywhere.
- **Named nodes only.** Each connection's own address is put to ``tailscale whois``, which answers from the
  tailnet's state which node holds it (WireGuard authenticates the peer; an address cannot be forged inside the
  tailnet). A node the operator did not name (``--private-allow-node``, e.g. ``crooks-os-prod-1``), or an
  address Tailscale cannot place, is refused (403) before anything is read. The answer is cached for a minute.
- **Read-only.** GET of one path; any other path is 404 and any other method 405 (to a named node; every other
  node gets 403 whatever it asks); no request body is read, a connection that says nothing is dropped after
  ten seconds, and nothing is logged about who asked.
- **Never in the loop's way.** The loop starts the server itself and keeps going when it cannot (the tailnet
  address not up yet, the port taken): it says so in its cycle line and tries again a minute later
  (``PrivateChannel``). The private document is rebuilt every cycle either way.
- **Redacted.** Every text field is rebuilt through the status projection's redaction seam (status.py ``_clean``:
  credentials, URL userinfo, token shapes, and the app's customer shapes), bounded; output tails keep their lines.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.orchestrator.dispatcher import STOP_CAUSE_WORDS

from .receipts import ReceiptLog
from .status import _clean, _count, _sha, _text, _time

PRIVATE_SCHEMA = "clive.remote_engineering_private.v1"
PATH = "/v1/stops"
MAX_STOPS = 200
MAX_ROUNDS = 12
MAX_FINDINGS = 12
MAX_CHECKS = 12
MAX_FIELD = 4000
MAX_TAIL = 4000
MAX_INPUT = 20_000      # characters of one field put through the redaction at all
WHOIS_TIMEOUT_S = 3.0
WHOIS_CACHE_S = 60.0
REQUEST_TIMEOUT_S = 10.0
BIND_RETRY_S = 60.0
PRIVATE_UNAVAILABLE = "the private channel is not serving yet (its tailnet address or port could not be bound); retried each minute"

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_NODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
STAGES = frozenset({"BLOCKED", "OWNER_GATE"})
BUILDER_STATUSES = frozenset({"completed", "blocked", "owner_decision_required", "error"})

REFUSED_NODE = b'{"error": "this node is not allowed to read the build loop\'s private status"}'
NOT_FOUND = b'{"error": "not found"}'
NOT_ALLOWED = b'{"error": "read-only: GET only"}'


# ------------------------------------------------------------------ the document


def _block(value: object, limit: int = MAX_FIELD, *, tail: bool = False) -> str | None:
    """Text that keeps its lines (findings, output tails), redacted before it is cut, without control characters."""
    if not isinstance(value, str) or not value.strip():
        return None
    if len(value) > MAX_INPUT:
        # Bound the work, and drop the word the bound cut through: a cut secret no longer looks like one.
        value = value[-MAX_INPUT:].split(None, 1)[-1] if tail else value[:MAX_INPUT].rsplit(None, 1)[0]
    text = _CONTROL.sub("", _clean(value.replace("\r\n", "\n").replace("\r", "\n")))
    if len(text) <= limit:
        return text
    if tail:
        cut = text[-limit:]
        return cut.split("\n", 1)[1] if "\n" in cut[:200] else cut
    return text[: limit - 3].rstrip() + "..."


def _word(value: object, allowed: Iterable[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _ident(value: object) -> str | None:
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _finding(raw: Mapping) -> dict:
    return {"finding_id": _ident(raw.get("finding_id")),
            "material": raw.get("material") if isinstance(raw.get("material"), bool) else None,
            "finding": _block(raw.get("finding")), "evidence_ref": _block(raw.get("evidence_ref"), 1000),
            "required_repair": _block(raw.get("required_repair"))}


def _round(raw: Mapping) -> dict:
    findings = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    return {"revision": _count(raw.get("revision")), "attempt_id": _ident(raw.get("attempt_id")),
            "candidate_sha": _sha(raw.get("candidate_sha")), "reviewer": _text(raw.get("reviewer"), 120),
            "summary": _block(raw.get("summary")),
            "findings": [_finding(f) for f in findings[:MAX_FINDINGS] if isinstance(f, Mapping)]}


def _check(raw: Mapping) -> dict:
    return {"attempt_id": _ident(raw.get("attempt_id")), "what": _word(raw.get("what"), ("check", "generator")),
            "name": _text(raw.get("name"), 80), "exit_code": raw.get("exit_code") if isinstance(raw.get("exit_code"), int)
            and not isinstance(raw.get("exit_code"), bool) else None,
            "tail": _block(raw.get("tail"), MAX_TAIL, tail=True)}


def _red(raw: object) -> dict | None:
    if not isinstance(raw, Mapping):
        return None
    lines = raw.get("short_summary") if isinstance(raw.get("short_summary"), list) else []
    tests = raw.get("failing_tests") if isinstance(raw.get("failing_tests"), list) else []
    return {"sha": _sha(raw.get("sha")), "summary": _text(raw.get("summary"), 500),
            "failing_tests": [t for t in (_text(x, 200) for x in tests[:30]) if t],
            "short_summary": [t for t in (_text(x, 300) for x in lines[:30]) if t],
            "assertions": _block("\n".join(str(a) for a in raw.get("assertions") or [] if isinstance(a, str)), MAX_TAIL),
            "tail": _block(raw.get("tail"), MAX_TAIL, tail=True), "job": _text(raw.get("job"), 120),
            "run_url": _text(raw.get("run_url"), 200), "at": _time(raw.get("fetched_at"))}


def _builder(raw: object) -> dict | None:
    if not isinstance(raw, Mapping):
        return None
    return {"attempt_id": _ident(raw.get("attempt_id")), "status": _word(raw.get("status"), BUILDER_STATUSES),
            "summary": _block(raw.get("summary")), "reason": _block(raw.get("reason"))}


def stop_entry(report: Mapping, request_id: str) -> dict:
    """One stop report, rebuilt field by field: fixed words, ids, SHAs, times, and redacted bounded text."""
    rounds = report.get("review_rounds") if isinstance(report.get("review_rounds"), list) else []
    checks = report.get("failed_checks") if isinstance(report.get("failed_checks"), list) else []
    return {
        "request_id": request_id, "objective_id": _ident(report.get("objective_id")),
        "revision": _count(report.get("revision")), "attempt_id": _ident(report.get("attempt_id")),
        "stage": _word(report.get("stage"), STAGES), "cause": _word(report.get("cause"), STOP_CAUSE_WORDS),
        "at": _time(report.get("at")), "blocker": _block(report.get("blocker")),
        "candidate_sha": _sha(report.get("candidate_sha")), "max_repair_rounds": _count(report.get("max_repair_rounds")),
        "review_rounds": [_round(r) for r in rounds[-MAX_ROUNDS:] if isinstance(r, Mapping)],
        "failed_checks": [_check(c) for c in checks[:MAX_CHECKS] if isinstance(c, Mapping)],
        "github_failure": _red(report.get("github_failure")),
        "builder_report": _builder(report.get("builder_report")),
    }


def build_private(reports: Iterable[Mapping], *, receipts: ReceiptLog, now: datetime) -> dict:
    """The private document: each stopped request's report, by the request id the loop took it in under."""
    by_objective = {r.objective_id: r.request_id for r in receipts.read_all() if r.objective_id}
    stops = []
    for report in reports:
        objective = _ident(report.get("objective_id")) if isinstance(report, Mapping) else None
        if objective is None:
            continue
        stops.append(stop_entry(report, by_objective.get(objective, objective)))
    stops.sort(key=lambda s: s["request_id"])
    return {"schema_version": PRIVATE_SCHEMA, "generated_at": now.isoformat(), "stops": stops[:MAX_STOPS]}


class PrivateDocument:
    """The latest private document, as the bytes the server sends. Set by the loop each cycle; read by the server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bytes = json.dumps({"schema_version": PRIVATE_SCHEMA, "generated_at": None, "stops": []}).encode()

    def set(self, document: dict) -> None:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        with self._lock:
            self._bytes = payload

    def get(self) -> bytes:
        with self._lock:
            return self._bytes


# ------------------------------------------------------------------ who may read it


def _run_whois(cli: str, address: str) -> str:
    done = subprocess.run([cli, "whois", "--json", address], capture_output=True, text=True,
                          timeout=WHOIS_TIMEOUT_S, check=False)
    if done.returncode != 0:
        raise RuntimeError("tailscale could not place the address")
    return done.stdout


def node_name(whois: object) -> str | None:
    """The tailnet node name ``tailscale whois --json`` gives for an address (its machine name, lower case)."""
    node = whois.get("Node") if isinstance(whois, Mapping) else None
    if not isinstance(node, Mapping):
        return None
    name = node.get("ComputedName") or str(node.get("Name") or "").split(".", 1)[0]
    name = str(name or "").strip().lower()
    return name if _NODE.fullmatch(name) else None


class PeerCheck:
    """Whether the node at a connection's address is one the operator allowed, by ``tailscale whois``."""

    def __init__(self, allowed: Iterable[str], *, cli: str | None = None,
                 runner: Callable[[str, str], object] | None = None, clock: Callable[[], float] = time.monotonic):
        names = {str(n).strip().lower() for n in allowed}
        if not names or any(not _NODE.fullmatch(n) for n in names):
            raise ValueError("--private-allow-node names at least one tailnet machine (lowercase, digits, hyphens)")
        self.allowed = frozenset(names)
        self.cli = cli or shutil.which("tailscale")
        self._runner = runner or _run_whois
        self._clock = clock
        self._cache: dict[str, tuple[bool, float]] = {}
        self._lock = threading.Lock()

    def allows(self, address: str) -> bool:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(address)
            if hit is not None and now - hit[1] < WHOIS_CACHE_S:
                return hit[0]
        ok = False
        if self.cli:
            try:
                raw = self._runner(self.cli, address)
                ok = node_name(json.loads(raw) if isinstance(raw, str) else raw) in self.allowed
            except Exception:  # noqa: BLE001 -- an address Tailscale cannot place is refused, whatever went wrong
                ok = False
        with self._lock:
            self._cache[address] = (ok, now)
        return ok


# ------------------------------------------------------------------ the server


def parse_listen(value: str) -> tuple[str, int]:
    """``ADDRESS:PORT`` (``[v6]:PORT``) on a tailnet address or loopback; anything else is refused unechoed."""
    match = re.fullmatch(r"\[(?P<v6>[0-9a-fA-F:.]+)\]:(?P<p6>\d{1,5})|(?P<v4>[0-9.]+):(?P<p4>\d{1,5})", value or "")
    if match is None:
        raise ValueError("--private-listen is ADDRESS:PORT on this host's tailnet address")
    host, port = (match.group("v6"), int(match.group("p6"))) if match.group("v6") else (match.group("v4"),
                                                                                       int(match.group("p4")))
    ip = ipaddress.ip_address(host)
    if not (ip in TAILNET_V4 or ip in TAILNET_V6 or ip.is_loopback) or not 1 <= port <= 65535:
        raise ValueError("--private-listen must be this host's tailnet address (or loopback), never a public or "
                         "wildcard one")
    return host, port


class _Handler(BaseHTTPRequestHandler):
    server_version = "clive-private"
    sys_version = ""
    timeout = REQUEST_TIMEOUT_S

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self) -> bool:
        if self.server.peers.allows(self.client_address[0]):
            return True
        self._send(403, REFUSED_NODE)
        return False

    def do_GET(self) -> None:  # noqa: N802 -- the http.server name
        if not self._allowed():
            return
        if self.path != PATH:
            self._send(404, NOT_FOUND)
        else:
            self._send(200, self.server.document.get())

    def _refuse(self) -> None:
        if self._allowed():
            self._send(405, NOT_ALLOWED)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _refuse  # noqa: N815

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- who asked is not logged
        return


class PrivateServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], document: PrivateDocument, peers: PeerCheck) -> None:
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)
        self.document = document
        self.peers = peers


def serve(listen: str, document: PrivateDocument, peers: PeerCheck) -> PrivateServer:
    """Start the private channel in a daemon thread of the loop's own process; returns the running server."""
    server = PrivateServer(parse_listen(listen), document, peers)
    threading.Thread(target=server.serve_forever, name="clive-private", daemon=True).start()
    return server


class PrivateChannel:
    """The private document and its server, kept by the long-running loop. ``ensure`` starts the server when it is
    not running, at most once a minute, and never raises: a channel that cannot bind leaves the loop running."""

    def __init__(self, listen: str, peers: PeerCheck, *, clock: Callable[[], float] = time.monotonic) -> None:
        parse_listen(listen)            # refused before anything starts, unechoed
        self.listen = listen
        self.peers = peers
        self.document = PrivateDocument()
        self.server: PrivateServer | None = None
        self._clock = clock
        self._tried: float | None = None

    def ensure(self) -> str | None:
        """None while serving; otherwise the fixed sentence the cycle line carries."""
        if self.server is not None:
            return None
        now = self._clock()
        if self._tried is not None and now - self._tried < BIND_RETRY_S:
            return PRIVATE_UNAVAILABLE
        self._tried = now
        try:
            self.server = serve(self.listen, self.document, self.peers)
        except OSError:
            return PRIVATE_UNAVAILABLE
        return None

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
