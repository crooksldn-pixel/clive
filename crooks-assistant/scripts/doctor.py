#!/usr/bin/env python3
"""make doctor — check every prerequisite and print what is missing.

Runs on a bare Python with no dependencies installed, because its whole job is to tell you what
is not installed yet.

Two hosts, one command. On macOS it checks the Mac it always checked — Xcode, Homebrew,
whisper.cpp with Core ML, the login Keychain, launchd — and none of that changed. On Linux it
checks the production server instead: systemd, the encrypted-credential tooling, the writable
secret directory's ownership and mode, the Claude CLI's own login under HOME, and the unit.

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


# The application parses this with pydantic, and the doctor must answer exactly what the
# application would do — not something close. Measured against config.settings rather than
# assumed: pydantic accepts this vocabulary, case-insensitively, and REJECTS anything else,
# including an empty value. tests/test_linux_ops.py re-measures it against the real parser, so
# if pydantic's vocabulary ever changes, that test fails rather than this drifting silently.
TRUE_WORDS = {"true", "1", "yes", "on", "t", "y"}
FALSE_WORDS = {"false", "0", "no", "off", "f", "n"}


def env_file_value(name: str) -> str | None:
    """One value from .env, read the way python-dotenv reads it — whitespace stripped and one
    layer of matching quotes removed — because that is what reaches pydantic from a file. The
    environment is NOT treated this way: os.environ is passed through untouched, and
    `CROOKS_WHISPER_ENABLED=" false "` exported into the environment really is invalid.
    """
    env_file = REPO / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return None


def whisper_setting() -> str:
    """"enabled", "disabled", or "invalid" — what the application would make of this host's
    CROOKS_WHISPER_ENABLED.

    Read by hand rather than through config.settings, because the doctor runs before the venv
    exists — that is its whole job — and pydantic-settings is one of the things it checks for.
    Three states and not two: a value the application cannot parse is not a third opinion about
    whisper, it is a host whose backend will refuse to start, and saying "enabled" or "disabled"
    about it would be inventing an answer the application never gives.
    """
    raw = os.environ.get("CROOKS_WHISPER_ENABLED")
    if raw is None:
        raw = env_file_value("CROOKS_WHISPER_ENABLED")
        if raw is None:
            return "enabled"  # unset: the Settings default, whisper_enabled = True
    lowered = raw.lower()
    if lowered in TRUE_WORDS:
        return "enabled"
    if lowered in FALSE_WORDS:
        return "disabled"
    return "invalid"


def whisper_disabled() -> bool:
    """Whether this host was deliberately configured without local speech. An unparseable value
    is NOT disabled — it is reported separately as a blocking failure, and the whisper checks
    still run, so an invalid line cannot quietly suppress them as well."""
    return whisper_setting() == "disabled"


def linux_checks(failures: int, warnings: int) -> tuple[int, int]:
    """The production server's own prerequisites: what supervises the assistant, what holds
    its secrets, and whether the Claude CLI's login can still refresh itself.

    Nothing here runs on the Mac, and nothing the Mac checks is repeated here.
    """
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

    mac = platform.system() == "Darwin"
    linux = platform.system() == "Linux"
    row(OK if (mac or linux) else WARN, "operating system", f"{platform.system()} {platform.release()}")
    if linux:
        print("       Production host. whisper.cpp, Core ML, the Keychain and launchd are the")
        print("       Mac's; this machine uses systemd, encrypted credentials and Scribe alone.")
        print("       See docs/DEPLOY_LINUX.md for what is deliberately absent here.")
    elif not mac:
        warnings += 1
        print(
            "       The assistant targets macOS on Apple Silicon: whisper.cpp with Core ML,\n"
            "       the Keychain and launchd are all macOS-specific. Everything else in this\n"
            "       repository is portable and its tests run anywhere."
        )

    if mac:
        row(OK, "macOS version", run(["sw_vers", "-productVersion"]) or "unknown")
        arch = platform.machine()
        row(OK if arch == "arm64" else BAD, "architecture", arch)
        if arch != "arm64":
            failures += 1
            print("       Not Apple Silicon — Core ML acceleration will not be available.")
        row(OK, "cpu", run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "unknown")

        xcode = run(["xcode-select", "-p"])
        row(OK if xcode else BAD, "xcode clt", xcode or "MISSING — run: xcode-select --install")
        failures += 0 if xcode else 1

        brew = shutil.which("brew")
        if brew:
            intel = brew.startswith("/usr/local")
            row(WARN if intel else OK, "homebrew", f"{brew} ({run(['brew', '--version']) or ''})")
            if intel:
                warnings += 1
                print("       Homebrew is on the Intel path — this shell may be running under")
                print("       Rosetta and will build x86 binaries. Expect /opt/homebrew.")
        else:
            row(BAD, "homebrew", "MISSING — https://brew.sh")
            failures += 1

    version = sys.version_info
    ok_python = version >= (3, 11)
    row(OK if ok_python else BAD, "python", f"{platform.python_version()} at {sys.executable}")
    if not ok_python:
        failures += 1
        print("       Python 3.11+ is required (3.12 preferred). A system 3.9 on PATH shadows newer ones;")
        print("       create the venv with an explicit interpreter: python3.12 -m venv .venv")
    py312 = shutil.which("python3.12")
    install_312 = "apt install python3.12-venv" if linux else "brew install python@3.12"
    row(OK if py312 else WARN, "python3.12", py312 or f"not on PATH — {install_312} (make venv needs it)")
    warnings += 0 if py312 else 1

    # cmake is here to build whisper.cpp. This host does not build it, so asking for it would
    # be demanding a compiler for something it was decided not to compile.
    tools = [("git", "apt install git")] if (linux and whisper_disabled()) else [
        ("git", "apt install git"), ("ffmpeg", "apt install ffmpeg"),
    ] if linux else [
        ("git", "brew install git"),
        ("cmake", "brew install cmake"),
        ("ffmpeg", "brew install ffmpeg"),
    ]
    for name, hint in tools:
        path = shutil.which(name)
        row(OK if path else BAD, name, run([name, "--version"]) or f"MISSING — {hint}")
        failures += 0 if path else 1

    claude = shutil.which("claude")
    row(OK if claude else BAD, "claude cli", f"{run(['claude', '--version']) or 'MISSING'}")
    if not claude:
        failures += 1
        print("       Install it, then open a NEW shell — PATH is only updated for new shells.")

    tailscale = shutil.which("tailscale") or (
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        if Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale").exists() else None
    )
    row(OK if tailscale else WARN, "tailscale", tailscale or "not found — the tablet needs its HTTPS address (make up sets the route)")
    warnings += 0 if tailscale else 1

    node = shutil.which("node")
    row(OK if node else WARN, "node", run(["node", "--version"]) or "not found — only the renderer tests need it (they skip)")

    # An unparseable setting is a blocking failure, not a whisper opinion: pydantic rejects it,
    # so the backend would refuse to start and every other row here would be describing a host
    # that never comes up. Reported before the whisper rows, because it outranks them.
    if whisper_setting() == "invalid":
        row(BAD, "whisper setting", "CROOKS_WHISPER_ENABLED is set to a value the application cannot parse")
        failures += 1
        print("       The backend would refuse to start. Use true/1/yes/on or false/0/no/off;")
        print("       an empty value is not a value. Unset it entirely to accept the default.")

    if whisper_disabled():
        # Deliberately absent, so it is reported as a decision and costs no warning. Two
        # permanent warnings for a thing nobody intends to install is how a doctor gets
        # skimmed, and then the real warning underneath gets skimmed with it.
        row(OK, "whisper.cpp", "not deployed here (CROOKS_WHISPER_ENABLED=false) — Scribe hears; no local fallback")
    else:
        whisper_root = Path.home() / "tools" / "whisper.cpp"
        whisper_bin = next((p for p in [whisper_root / "build" / "bin" / "whisper-server", whisper_root / "build" / "whisper-server"] if p.exists()), None)
        vad = next((whisper_root / "models").glob("ggml-silero*.bin"), None) if (whisper_root / "models").exists() else None
        row(OK if whisper_bin else WARN, "whisper.cpp", str(whisper_bin) if whisper_bin else "not built — make whisper-server prints the steps; ElevenLabs still hears without it")
        row(OK if vad else WARN, "whisper vad model", vad.name if vad else "absent — cd ~/tools/whisper.cpp && sh ./models/download-vad-model.sh silero-v5.1.2")
        warnings += (0 if whisper_bin else 1) + (0 if vad else 1)

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
        # On the Mac the ElevenLabs key is optional: whisper.cpp hears and Android speaks if
        # it is absent. On a host with whisper disabled there is nothing behind it — no key
        # means the assistant cannot be spoken to at all — so it is required here, and saying
        # otherwise would be repeating the Mac's reassurance on a machine it is not true of.
        deaf_without_scribe = whisper_disabled()
        optional_keys = {"claude_oauth_token", "shopify_static_token", "gmail_token", "elevenlabs_api_key"}
        if deaf_without_scribe:
            optional_keys.discard("elevenlabs_api_key")

        for key in keychain.KNOWN_KEYS:
            have = keychain.present(key)
            optional = key in optional_keys
            absent = {
                "elevenlabs_api_key": (
                    "NOT STORED — this host has no local recogniser; without it nothing can hear you"
                    if deaf_without_scribe
                    else "not stored (the Mac's own recogniser listens; the tablet speaks in its own voice)"
                ),
                "claude_oauth_token": "not stored (fine: the login you made with `claude` is what is used)",
                "media_signing_key": "not stored — generate once: python scripts/provision_secrets.py media_signing_key --generate",
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
        (REPO / "kb" / "terminology.md", "product names as you say them"),
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
