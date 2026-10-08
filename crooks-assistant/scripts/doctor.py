#!/usr/bin/env python3
"""make doctor — check every prerequisite and print what is missing.

Runs on a bare Python with no dependencies installed, because its whole job is to tell you what
is not installed yet.

One host. CROOKS OS runs on the Linux server, and on Linux this checks what the server needs:
systemd, the encrypted-credential tooling, the writable secret directory's ownership and mode,
the Claude CLI's own login under HOME, and the unit. The Mac's checks — Xcode, Homebrew,
whisper.cpp with Core ML, launchd — went with the Mac runtime and the local recogniser on the
owner's ruling of 8 October (DEC-071, rulings 38 and 39; DEC-058: the Mac is not a CROOKS OS
host). On any other machine it says so, and checks what running the tests needs.

Anything it cannot check it says so about, rather than reporting an absence as a pass.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK, WARN, BAD = "  ok  ", " warn ", " FAIL "


def run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else None


def row(status: str, name: str, detail: str) -> None:
    print(f"[{status}] {name:<22} {detail}")


def linux_checks(failures: int, warnings: int) -> tuple[int, int]:
    """The production server's own prerequisites: what supervises the assistant, what holds
    its secrets, and whether the Claude CLI's login can still refresh itself."""
    print("─" * 74)

    systemctl = shutil.which("systemctl")
    row(OK if systemctl else BAD, "systemd",
        run(["systemctl", "--version"]) or "MISSING — nothing would keep the assistant alive")
    failures += 0 if systemctl else 1

    creds_tool = shutil.which("systemd-creds")
    row(OK if creds_tool else WARN, "systemd-creds",
        creds_tool or "not found — static secrets fall back to plain 0600 files, unencrypted at rest")
    warnings += 0 if creds_tool else 1

    unit = Path("/etc/systemd/system/crooks-assistant.service")
    if unit.is_file():
        active = run(["systemctl", "is-active", "crooks-assistant.service"]) or "inactive"
        enabled = run(["systemctl", "is-enabled", "crooks-assistant.service"]) or "not enabled"
        row(OK if active == "active" else WARN, "the service", f"{active} ({enabled} at boot)")
        warnings += 0 if active == "active" else 1
    else:
        row(WARN, "the service", "not installed — run: make install")
        warnings += 1

    secret_dir = Path(os.environ.get("CROOKS_SECRET_DIR") or "/etc/crooks-os/secrets")
    if secret_dir.is_dir():
        info = secret_dir.stat()
        mode, uid = stat.S_IMODE(info.st_mode), info.st_uid
        tight = mode == 0o700 and uid == 0
        row(OK if tight else WARN, "secret directory",
            f"{secret_dir} mode {mode:04o} uid {uid}" + ("" if tight else " — expected 0700, root-owned"))
        warnings += 0 if tight else 1
    else:
        row(WARN, "secret directory",
            f"{secret_dir} absent — run: python scripts/provision_secrets.py --all")
        warnings += 1

    # The Claude Max login. Not a secret this project stores: the CLI owns it, and it rewrites
    # the file in place when the OAuth token refreshes. A read-only HOME turns that into an
    # authentication failure days later with nothing in the log to connect the two, so the
    # writability is checked here rather than discovered then.
    home = Path(os.environ.get("HOME") or Path.home())
    cli_creds = home / ".claude" / ".credentials.json"
    if cli_creds.is_file():
        writable = os.access(cli_creds, os.W_OK) and os.access(cli_creds.parent, os.W_OK)
        row(OK if writable else BAD, "claude max login",
            str(cli_creds) if writable else f"{cli_creds} — NOT WRITABLE: the token refresh will fail")
        failures += 0 if writable else 1
    else:
        row(WARN, "claude max login", f"{cli_creds} absent — run `claude` once and log in")
        warnings += 1

    uid = os.geteuid()
    row(OK if uid == 0 else WARN, "running as",
        "root — temporary; see docs/DEPLOY_LINUX.md" if uid == 0 else f"uid {uid} (not root)")

    env_file = REPO / ".env"
    row(OK if env_file.is_file() else WARN, ".env",
        str(env_file) if env_file.is_file() else "absent — cp deploy/env.production.example .env")
    warnings += 0 if env_file.is_file() else 1

    tailscale = shutil.which("tailscale")
    if tailscale:
        serve = run([tailscale, "serve", "status"]) or ""
        routed = bool(serve) and "no serve config" not in serve.lower()
        row(OK if routed else WARN, "tailscale serve",
            serve if routed else "no HTTPS route yet — `make install` sets it; the tablet needs it")
        warnings += 0 if routed else 1

    return failures, warnings


def main() -> int:
    print("\nCROOKS Assistant — environment check\n" + "─" * 74)
    failures = 0
    warnings = 0

    linux = platform.system() == "Linux"
    row(OK if linux else WARN, "operating system", f"{platform.system()} {platform.release()}")
    if linux:
        print("       Production host: systemd, encrypted credentials, and ElevenLabs Scribe as")
        print("       the one recogniser. See docs/DEPLOY_LINUX.md for what is deliberately absent.")
    else:
        warnings += 1
        print(
            "       CROOKS OS runs on the Linux server, not here (DEC-058; the Mac runtime was\n"
            "       retired on 8 October, DEC-071). Everything in this repository is portable\n"
            "       and its tests run anywhere."
        )

    version = sys.version_info
    ok_python = version >= (3, 11)
    row(OK if ok_python else BAD, "python", f"{platform.python_version()} at {sys.executable}")
    if not ok_python:
        failures += 1
        print("       Python 3.11+ is required (3.12 preferred). A system 3.9 on PATH shadows newer ones;")
        print("       create the venv with an explicit interpreter: python3.12 -m venv .venv")
    py312 = shutil.which("python3.12")
    install_312 = "apt install python3.12-venv" if linux else "install Python 3.12"
    row(OK if py312 else WARN, "python3.12", py312 or f"not on PATH — {install_312} (make venv needs it)")
    warnings += 0 if py312 else 1

    # git alone. cmake and ffmpeg were here to build and feed whisper.cpp, which is gone.
    tools = [("git", "apt install git" if linux else "install git")]
    for name, hint in tools:
        path = shutil.which(name)
        row(OK if path else BAD, name, run([name, "--version"]) or f"MISSING — {hint}")
        failures += 0 if path else 1

    claude = shutil.which("claude")
    row(OK if claude else BAD, "claude cli", f"{run(['claude', '--version']) or 'MISSING'}")
    if not claude:
        failures += 1
        print("       Install it, then open a NEW shell — PATH is only updated for new shells.")

    tailscale = shutil.which("tailscale")
    row(OK if tailscale else WARN, "tailscale", tailscale or "not found — the tablet needs its HTTPS address (make install sets the route)")
    warnings += 0 if tailscale else 1

    node = shutil.which("node")
    row(OK if node else WARN, "node", run(["node", "--version"]) or "not found — only the renderer tests need it (they skip)")

    if linux:
        failures, warnings = linux_checks(failures, warnings)

    print("─" * 74)

    missing_modules = 0
    for module, extra in [
        ("fastapi", ""), ("uvicorn", ""), ("httpx", ""), ("pydantic_settings", ""),
        ("av", "PyAV — audio decode"), ("rapidfuzz", ""), ("jellyfish", ""),
        ("keyring", "macOS Keychain"), ("claude_agent_sdk", ""),
        ("googleapiclient", "Gmail"), ("google_auth_oauthlib", "Gmail"),
    ]:
        found = importlib.util.find_spec(module) is not None
        # keyring is the Mac's secret backend. On Linux the store is plain stdlib file
        # handling, so a missing keyring is a non-event rather than a blocking failure.
        if module == "keyring" and linux:
            row(OK, module, "not needed on Linux (systemd credentials + /etc/crooks-os/secrets)")
            continue
        row(OK if found else BAD, module, extra or ("installed" if found else "MISSING"))
        missing_modules += 0 if found else 1
    failures += missing_modules
    if missing_modules:
        print("       Missing Python packages — run: make venv")

    print("─" * 74)

    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        present = bool(os.environ.get(name))
        row(BAD if present else OK, name, "SET — must be unset" if present else "not set (correct)")
        failures += 1 if present else 0
    if any(os.environ.get(n) for n in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")):
        print("       The assistant runs on the Max subscription. A key in the environment")
        print("       would silently bill you per token. Check your shell profile.")

    print("─" * 74)

    try:
        sys.path.insert(0, str(REPO))
        from app.secrets import keychain

        try:
            keychain.get("claude_oauth_token")
        except keychain.KeychainUnavailable as exc:
            raise RuntimeError(str(exc)) from exc
        except keychain.SecretMissing:
            pass
        # The ElevenLabs key is required: there is no local recogniser behind Scribe (DEC-022),
        # so without it the assistant cannot be spoken to at all.
        optional_keys = {"claude_oauth_token", "shopify_static_token", "gmail_token", "local_cli_key"}

        for key in keychain.KNOWN_KEYS:
            have = keychain.present(key)
            optional = key in optional_keys
            absent = {
                "elevenlabs_api_key": "NOT STORED — there is no local recogniser; without it nothing can hear you",
                "claude_oauth_token": "not stored (fine: the login you made with `claude` is what is used)",
                "media_signing_key": "not stored — generate once: python scripts/provision_secrets.py media_signing_key --generate",
                "local_cli_key": "not stored yet — the backend makes it when it starts; until then make test-session-* is refused",
            }.get(key, "not stored (fallback only)")
            # Which tier holds it, never the value. On the Mac this is always "keychain"; on
            # the server it is the difference between an encrypted credential and a file.
            held = f"stored ({keychain.where(key)})" if have else ""
            row(
                OK if have else (WARN if optional else BAD),
                key,
                held or absent,
            )
            if not have and not optional:
                warnings += 1
    except Exception as exc:  # noqa: BLE001
        row(WARN, "keychain", f"unavailable to this process — secrets could not be checked: {str(exc)[:70]}")
        warnings += 1
    print("       Store a secret with: make secrets")

    print("─" * 74)
    for path, why in [
        (REPO / "kb" / "terminology.md", "product names as you say them, for the assistant to read"),
        (REPO / "credentials.json", "the Google Desktop client JSON (see README, Gmail)"),
    ]:
        row(OK if path.exists() else WARN, path.name, str(path) if path.exists() else f"absent — {why}")
    try:
        sys.path.insert(0, str(REPO))
        from app.secrets import keychain as kc

        gmail_ok = kc.present("gmail_token") or (REPO / "token.json").exists()
        where = "the writable secret store" if platform.system() == "Linux" else "the Keychain"
        row(OK if gmail_ok else WARN, "gmail credential",
            "stored" if gmail_ok else f"absent — run: make gmail (the credential goes to {where})")
    except Exception:  # noqa: BLE001
        row(OK if (REPO / "token.json").exists() else WARN, "gmail credential",
            "token.json present" if (REPO / "token.json").exists() else "absent — run: make gmail")

    print("─" * 74)
    if failures:
        print(f"\n{failures} blocking problem(s), {warnings} warning(s). Fix the failures first.\n")
        return 1
    print(f"\nAll prerequisites present. {warnings} warning(s).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
