"""FastAPI application.

Bound to loopback and served to the tablet by `tailscale serve`, which supplies the trusted
HTTPS origin that getUserMedia and speechSynthesis both require. Binding 0.0.0.0 and using the
LAN IP looks like it works and then fails on the browser API that actually matters.
"""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app import runtime as runtime_module
from app.logging.quiet import quieten
from app.logging.turnlog import RedactingFilter
from app.providers.max_agent_sdk import BillingGuardError, assert_no_payg_credentials
from app.routes import (
    actions,
    admin,
    batches,
    branches,
    command,
    context,
    health,
    media,
    observe,
    pad,
    speak,
    turn,
)
from config.settings import get_settings

log = logging.getLogger("crooks")


def configure_logging(log_dir: Path) -> None:
    """Every log line — stdout and file — passes through the redaction filter, and the file
    rotates. Under launchd stdout goes to a file that would otherwise grow forever."""
    from logging.handlers import RotatingFileHandler

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if getattr(root, "_crooks_configured", False):
        return
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(RedactingFilter())
    root.addHandler(stream)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(log_dir / "assistant.log", maxBytes=5_000_000, backupCount=5)
        rotating.setFormatter(fmt)
        rotating.addFilter(RedactingFilter())
        root.addHandler(rotating)
    except OSError as exc:
        log.warning("file logging disabled: %s", exc)
    quieten()
    root._crooks_configured = True  # type: ignore[attr-defined]

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The billing guard is the one startup failure that must stop the process outright. A
    # missing token can be fixed while the backend keeps serving /health; a present API key
    # cannot be allowed to serve a single turn.
    assert_no_payg_credentials()
    settings = get_settings()
    configure_logging(settings.log_dir)
    app.state.runtime = runtime_module.build(settings)
    app.state.health_cache = None   # /health answers from a recent result; none yet
    app.state.health_lock = None
    # The same list the write boundary reads, so the two can never disagree.
    app.state.allowed_logins = app.state.runtime.allowed_logins
    try:
        await app.state.runtime.provider.start()
    except BillingGuardError:
        raise
    except Exception as exc:  # noqa: BLE001
        # A missing Claude token must not stop the backend booting: /health then names the
        # problem, and each /turn retries start() so fixing it needs no restart.
        log.error("Claude provider did not start: %s", exc)
    app.state.runtime.warm_orders_soon()
    log.info("CROOKS Assistant ready (bind address is whatever uvicorn was started with)")
    yield
    await app.state.runtime.aclose()


app = FastAPI(title="CROOKS Assistant", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def guard_and_freshness(request: Request, call_next):
    """Two small things every request passes through.

    Who may ask: by default anyone who can reach the port — the tailnet is the owner's own
    private network and the backend binds to loopback behind it. When CROOKS_ALLOWED_LOGINS
    names Tailscale logins, `tailscale serve` tags every proxied request with the caller's
    login and only those callers are answered; a request that reaches the port without the
    header (curl on the Mac itself) is still allowed, because it is on the Mac.

    What the tablet keeps: the page and its scripts are served with no-cache, so a page open
    for a week picks up a new build on its next load rather than in a fortnight.
    """
    # A page from another site — another tailnet host, or anything the tablet's browser was
    # pointed at — must not be able to POST here with the tablet's own Tailscale identity.
    # Chrome names the relationship in Sec-Fetch-Site; an Origin that is neither this host nor
    # the forwarded one is refused too. Requests without either header (curl, scripts) pass.
    if request.method in _STATE_CHANGING and _cross_site(request):
        return JSONResponse(status_code=403, content={"error": "cross-site request refused"})
    allowed = getattr(request.app.state, "allowed_logins", ())
    login = request.headers.get("tailscale-user-login", "")
    # `tailscale serve` adds X-Forwarded-For to everything it proxies and a login only for
    # tailnet users: a proxied request with no login is Funnel or a tagged node, and is
    # refused whether or not an allow-list is set — nobody anonymous asks this assistant.
    # A request with neither header was made on the Mac itself.
    proxied = bool(request.headers.get("x-forwarded-for"))
    if proxied and not login:
        return JSONResponse(status_code=403, content={"error": "not allowed", "who": "unknown"})
    if allowed and login and login.lower() not in allowed:
        return JSONResponse(status_code=403, content={"error": "not allowed", "who": login})
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/sw.js", "/manifest.webmanifest") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _cross_site(request: Request) -> bool:
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site in ("cross-site", "same-site"):
        return True
    origin = request.headers.get("origin", "").strip().lower()
    if not origin or origin == "null":
        return bool(origin)   # "null" is an opaque origin: a sandboxed or file: page. Refuse.
    origin_host = origin.split("://", 1)[-1].split("/", 1)[0]
    hosts = {
        request.headers.get("host", "").strip().lower(),
        request.headers.get("x-forwarded-host", "").strip().lower(),
    }
    return origin_host not in hosts


# The page files travel compressed: 140 KB of script and style is 40 KB over the tailnet.
# Audio is excluded by default (an MP3 does not shrink) and the shell's cache keeps whatever
# encoding it received. Never a secret in a compressed body, so no compression-oracle concern.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(health.router)
app.include_router(turn.router)
app.include_router(speak.router)
app.include_router(admin.router)
app.include_router(actions.router)
app.include_router(batches.router)
app.include_router(branches.router)
app.include_router(command.router)
app.include_router(context.router)
app.include_router(media.router)
app.include_router(observe.router)
app.include_router(pad.router)

if WEB_DIR.exists():
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index(request: Request) -> Response:
        # The page carries the build it was made for, so a shell opened from the worker's
        # cache can tell at its first health poll that the Mac has moved on.
        source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        build = getattr(request.app.state.runtime, "build", "unknown")
        return Response(source.replace("__BUILD__", build), media_type="text/html; charset=utf-8")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        # At the root, like the worker, so the installed app's scope is the whole site.
        return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker(request: Request) -> Response:
        # Served from the root so its scope is the whole app, with the build id written in so
        # the file changes — and Chrome installs the new worker — whenever a page file does.
        source = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
        build = getattr(request.app.state.runtime, "build", "unknown")
        return Response(
            source.replace("__BUILD__", build),
            media_type="text/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        # Desktop Chrome asks for this on every visit; the page's own icon answers it rather
        # than a 404 in the log each time.
        return FileResponse(WEB_DIR / "icon-192.png", media_type="image/png")
