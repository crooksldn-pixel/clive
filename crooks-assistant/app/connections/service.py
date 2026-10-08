"""Store, test, disconnect and record: what the Connections routes do once the door has let the
owner in and his passkey has approved the change (app/routes/connections.py).

A key is tested with the service before it replaces the one in use, and stored only if the test
passed. It goes to the app tier (app/secrets/vault.py), encrypted on this machine and read at the
next call, and the caches that held the old key are dropped at once, so the change is live without
a restart. Every change, refused or made, is recorded without its value (ledger.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.connections import catalog, instagram, ledger, passkeys, testers
from app.secrets import keychain, vault

log = logging.getLogger("crooks.connections")

FAMILY_REFRESH_S = 15.0
WHERE = {
    "app": "saved here",
    "app-off": "disconnected here",
    "app-unreadable": "saved here, but this server can no longer read it: save it again",
    "systemd-credential": "set at the server",
    "file": "set at the server",
    "keychain": "in the Mac's Keychain",
    "": "not set",
}
TROUBLED = ("TEMPORARILY_UNAVAILABLE", "MISSING_SCOPE", "DISCONNECTED")
# Where each state puts a row on the screen: what needs the owner first, then what works, then
# what he could add.
GROUPS = {"needs_attention": "attention", "connected": "working", "not_connected": "add"}
CHECK_EVERY_S = 60.0       # the screen asks each service again at most once a minute
CHECK_TIMEOUT_S = 12.0
EXPIRING_DAYS = 7          # a sign-in with less than a week left is the owner's to renew
_CHECKING: set[str] = set()


class ConnectionsError(Exception):
    """A request the service will not carry out, with a reason fit to show the owner."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def configure(*, state_dir: Path | None) -> None:
    """Called once by the runtime: where passkeys and the record of changes are kept."""
    passkeys.configure(state_dir=state_dir)
    ledger.configure(state_dir=state_dir)


def _where(key: str) -> str:
    try:
        return keychain.where(key)
    except Exception:  # noqa: BLE001 - a store that cannot be read holds nothing usable
        return ""


def _usable(key: str) -> bool:
    return _where(key) not in ("", "app-off", "app-unreadable")


def _current(connection: catalog.Connection) -> dict[str, str]:
    """What is stored now for this connection's fields: used to test a partial change against the
    rest of what is in use. Never returned to anyone."""
    out: dict[str, str] = {}
    for item in connection.fields:
        try:
            value = keychain.get_optional(item.key)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            out[item.key] = value
    return out


def _present(connection: catalog.Connection) -> bool:
    """Whether what this connection cannot work without is here. Gmail's credential may still be
    the token.json file of the original set-up (app/clients/gmail.py reads it when the store has
    none), and a credential that works is not "not connected" for living in a file."""
    if all(_usable(k) for k in connection.requires):
        return True
    if connection.name == "gmail":
        from app.clients import gmail

        try:
            return gmail.TOKEN_PATH.exists()
        except OSError:
            return False
    return False


def _expires_in_days(connection: catalog.Connection) -> int | None:
    """Days left on a sign-in that runs out (Instagram's), from what its client last learned."""
    if connection.name != "instagram":
        return None
    from app.clients import instagram as instagram_client

    expires = instagram_client.state().get("expires_at")
    if expires is None:
        return None
    try:
        return int((float(expires) - time.time()) // 86400)
    except (TypeError, ValueError):
        return None


def _unlocks(connection: catalog.Connection, families: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """What the connection lets CLIVE do, by the capability families' own labels and live states,
    then the abilities no family describes. A family that is not built yet is left out."""
    from app.capabilities import families as registry

    out: list[dict[str, str]] = []
    for key in connection.unlocks:
        family = registry.get(key)
        if family is None:
            continue
        live = families.get(key) or {}
        family_state = str(live.get("state") or family.state)
        if family_state == "NOT_IMPLEMENTED":
            continue
        out.append({"label": family.label, "state": family_state})
    out.extend({"label": words, "state": "READY"} for words in connection.abilities)
    return out


def _what(runtime: Any, connection: catalog.Connection) -> str:
    """The row's one line. The voice says whose voice it is, as it is now."""
    if connection.name == "elevenlabs":
        name = str(getattr(getattr(runtime, "voice", None), "voice_name", "") or "").strip()
        if name:
            return f"Hears you and speaks in {name}'s voice."
    return connection.what


def _without(runtime: Any, connection: catalog.Connection) -> str:
    """What stops without it. For the voice that depends on this server: whether it has a
    recogniser of its own to listen with when ElevenLabs is not there."""
    if connection.name != "elevenlabs":
        return connection.without
    settings = getattr(runtime, "settings", None)
    if str(getattr(settings, "stt_primary", "scribe")) != "scribe":
        return connection.without
    if getattr(settings, "whisper_enabled", False):
        return ("Without it CLIVE listens with the server's own recogniser instead, and speaks in each "
                "device's own built-in voice.")
    return "Without it CLIVE can't hear you, so you type instead, and it speaks in each device's own built-in voice."


def _to_connect(connection: catalog.Connection, sign_in_ready: bool) -> tuple[str, list[str]]:
    """What connecting it asks for: one sign-in, the keys still missing, or the server."""
    if not connection.fields:
        return "server", []
    if connection.sign_in:
        if sign_in_ready:
            return "signin", []
        return "key", [k for k in ("instagram_app_id", "instagram_app_secret") if not _usable(k)]
    return "key", [k for k in connection.requires if not _usable(k) and catalog.field(connection, k)]


def _expiring(connection: catalog.Connection, days: int) -> str:
    if days < 0:
        return f"The {connection.label} sign-in has run out. Sign in again to keep it working."
    left = "today" if days == 0 else f"in {days} day{'' if days == 1 else 's'}"
    return f"The {connection.label} sign-in runs out {left}, and CLIVE hasn't renewed it."


# What a sign-in that Instagram refuses needs, by the kind of refusal its client last met
# (app/clients/instagram.py): each is put right by signing in again.
SIGN_IN_TROUBLE = {
    "token": "{label} no longer accepts CLIVE's sign-in.",
    "permission": "{label}'s sign-in is missing a permission CLIVE needs: when you sign in again, allow messages "
                  "and comments.",
    "refresh_blocked": "CLIVE couldn't renew the {label} sign-in.",
}


def _trouble(connection: catalog.Connection, family: dict[str, Any], family_state: str,
             sign_in_ready: bool) -> tuple[str, str]:
    """A capability family in trouble while the keys are in: what to say, and what puts it right.
    A sign-in that is refused, or short of a scope, is signed in again; anything else is checked
    again (the review of 889f3284, note 3)."""
    detail = str(family.get("detail") or family_state.replace("_", " ").lower())
    if not (connection.sign_in and sign_in_ready):
        return detail, "retry"
    from app.clients import instagram as instagram_client

    kind = str(instagram_client.state().get("last_error_kind") or "")
    if family_state == "MISSING_SCOPE" or kind in SIGN_IN_TROUBLE:
        return SIGN_IN_TROUBLE.get(kind, SIGN_IN_TROUBLE["permission"]).format(label=connection.label), "signin"
    return detail, "retry"


def card(runtime: Any, connection: catalog.Connection, *, tests: dict[str, dict[str, Any]],
         families: dict[str, dict[str, Any]], origin: str) -> dict[str, Any]:
    """One connection as its row shows it: never a secret, an ID only because it is not one.

    Besides its state, a row says what would put it right (`fix`) and which keys, if any, to ask
    for now (`needs`): none for a connection that works, only the missing ones for one that is
    not connected, and the refused ones for one whose key the service turned down."""
    fields = []
    for item in connection.fields:
        where = _where(item.key)
        entry: dict[str, Any] = {"key": item.key, "label": item.label, "hint": item.hint, "secret": item.secret,
                                 "stored": where not in ("", "app-off", "app-unreadable"),
                                 "where": WHERE.get(where, "set at the server")}
        if not item.secret and entry["stored"]:
            try:
                entry["value"] = keychain.get_optional(item.key) or ""
            except Exception:  # noqa: BLE001
                entry["value"] = ""
        fields.append(entry)
    last = tests.get(connection.name) or {}
    family = families.get(connection.family) or {} if connection.family else {}
    family_state = str(family.get("state") or "")
    sign_in_ready = bool(connection.sign_in) and all(_usable(k) for k in ("instagram_app_id", "instagram_app_secret"))
    keys = [f.key for f in connection.fields] + list(connection.requires)
    unreadable = [k for k in dict.fromkeys(keys) if _where(k) == "app-unreadable"]
    present = _present(connection)
    days = _expires_in_days(connection) if present else None
    fix, needs = "", []
    if unreadable:
        state, detail = "needs_attention", "A key saved here can no longer be read on this server: save it again."
        fix, needs = "key", [k for k in unreadable if catalog.field(connection, k)]
    elif not present:
        state, detail = "not_connected", "Not connected."
        fix, needs = _to_connect(connection, sign_in_ready)
    elif last and not last.get("ok"):
        state, detail = "needs_attention", str(last.get("detail") or "The last test failed.")
        fix = str(last.get("fix") or ("server" if connection.set_up_at else "key"))
        if fix in ("key", "service") and sign_in_ready:
            fix = "signin"                 # a refused token, or one short of a permission: sign in again
        elif fix == "key":
            needs = [k for k in connection.requires if catalog.field(connection, k)]
            # The service said which of its keys it refused (CROOKS Returns): ask for those alone.
            named = [k for k in (last.get("refused") or []) if k in needs]
            needs = named or needs
    elif days is not None and days < EXPIRING_DAYS:
        state, detail = "needs_attention", _expiring(connection, days)
        fix, needs = ("signin", []) if sign_in_ready else ("key", ["instagram_access_token"])
    elif family_state in TROUBLED:
        state = "needs_attention"
        detail, fix = _trouble(connection, family, family_state, sign_in_ready)
    else:
        state, detail = "connected", str(last.get("detail") or "Connected.")
    out = {
        "name": connection.name, "label": connection.label, "what": _what(runtime, connection), "note": connection.note,
        "state": state, "detail": detail, "who": str(last.get("who") or ""), "tested_at": str(last.get("at") or ""),
        "tested": str(last.get("detail") or ""),     # what the last test itself found, for the details
        "fields": fields, "editable": bool(connection.fields), "testable": connection.name in CHECKS,
        "group": GROUPS[state], "fix": fix, "needs": needs, "unlocks": _unlocks(connection, families),
        "without": _without(runtime, connection), "set_up_at": connection.set_up_at, "expires_in_days": days,
        "requires": [k for k in connection.requires if catalog.field(connection, k)],
    }
    if connection.sign_in == "instagram":
        out["sign_in"] = {"label": "Sign in with Instagram", "redirect_uri": instagram.redirect_uri(origin),
                          "ready": sign_in_ready}
    return out


def state(runtime: Any, *, origin: str) -> dict[str, Any]:
    """Everything the Connections screen draws, in one answer."""
    tests = ledger.last_tests()
    families = getattr(runtime, "family_states_table", None) or {}
    ok, why = vault.check()
    try:
        keys = passkeys.registered()
    except passkeys.PasskeyRefused:
        keys = []
    return {
        "connections": [card(runtime, c, tests=tests, families=families, origin=origin) for c in catalog.CONNECTIONS],
        "passkeys": keys,
        "changes": ledger.recent(20),
        "store": {"ok": ok, "why": why},
        "now": ledger.now(),
        "check_every_s": int(CHECK_EVERY_S),
    }


# ------------------------------------------------------------------ the check on opening

async def _check_gmail(runtime: Any) -> testers.Outcome:
    """Gmail is set up at the server, so it is asked the way /health asks it: its profile and the
    scopes its credential holds, read-only. The mailbox's own address names the account."""
    client = getattr(runtime, "gmail", None)
    if client is None or not callable(getattr(client, "health", None)):
        return testers.Outcome(False, "Gmail is not set up on this server.", fix="server")
    try:
        ok, detail = await asyncio.wait_for(asyncio.to_thread(client.health), CHECK_TIMEOUT_S)
    except TimeoutError:
        return testers.Outcome(False, "Gmail did not answer in time. Check again in a minute.", fix="retry")
    except Exception:  # noqa: BLE001 - a check that cannot run is a failed check, never a crash
        return testers.Outcome(False, "Gmail could not be asked just now. Check again in a minute.", fix="retry")
    if ok:
        who = str(detail).split(" · ")[0].strip()
        return testers.Outcome(True, "Gmail answered.", who=who if "@" in who else "")
    if str(detail).startswith("Gmail check failed"):
        return testers.Outcome(False, "Gmail did not answer just now. Check again in a minute.", fix="retry")
    return testers.Outcome(False, "Google no longer accepts CLIVE's Gmail sign-in. It needs signing in again, "
                                  "at the server for now.", fix="server")


CHECKS = {**{name: None for name in testers.TESTERS}, "gmail": _check_gmail}


def _age_s(test: dict[str, Any] | None) -> float | None:
    from datetime import datetime

    try:
        return time.time() - datetime.fromisoformat(str((test or {}).get("at") or "")).timestamp()
    except ValueError:
        return None


async def _check_one(runtime: Any, connection: catalog.Connection) -> None:
    await test(runtime, connection.name)


async def check_all(runtime: Any, *, every_s: float = CHECK_EVERY_S) -> list[str]:
    """Ask every connected service again, as the Test button does, so the screen shows what is
    true now: each at most once in `every_s`, however many devices open the screen at once.
    Read-only and spending nothing (testers.py says what each asks). Returns the names asked.

    What is due is claimed before anything waits: a second screen opening meanwhile finds it taken
    rather than choosing it too (the review of 889f3284: five at once asked ElevenLabs five times)."""
    tests = ledger.last_tests()
    claimed: list[catalog.Connection] = []
    for connection in catalog.CONNECTIONS:
        if connection.name not in CHECKS or connection.name in _CHECKING:
            continue
        age = _age_s(tests.get(connection.name))
        if age is not None and 0 <= age < every_s:
            continue
        claimed.append(connection)
    _CHECKING.update(c.name for c in claimed)
    names: list[str] = []
    results: list[Any] = []
    try:
        due = [c for c in claimed if await asyncio.to_thread(_present, c)]
        names = [c.name for c in due]
        results = await asyncio.gather(*(_check_one(runtime, c) for c in due), return_exceptions=True)
    finally:
        _CHECKING.difference_update(c.name for c in claimed)
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("connections: the check of %s did not finish (%s)", name, type(result).__name__)
    refresh = getattr(runtime, "family_states", None)
    if names and not getattr(runtime, "family_states_table", None) and callable(refresh):
        try:
            await asyncio.wait_for(refresh(), FAMILY_REFRESH_S)
        except Exception as exc:  # noqa: BLE001 - the rows still say what each test found
            log.warning("connections: capability families not read for the screen (%s)", type(exc).__name__)
    return names


async def after_change(runtime: Any, keys: tuple[str, ...], *, new_token: bool = True) -> None:
    """Drop what held the old key, so the next call uses the new one with no restart, and ask the
    capability families again, so a connection made or lost shows in what the model is offered."""
    changed = set(keys)
    if "elevenlabs_api_key" in changed:
        for client in (getattr(runtime, "scribe", None), getattr(runtime, "voice", None)):
            for method in ("forget_key", "clear_cooldown"):
                call = getattr(client, method, None)
                if callable(call):
                    call()
    if changed & {"shopify_client_id", "shopify_client_secret", "shopify_static_token"}:
        call = getattr(getattr(runtime, "shopify", None), "forget_token", None)
        if callable(call):
            call()
    if "instagram_access_token" in changed and new_token:
        from app.clients import instagram as instagram_client

        instagram_client.adopt_new_token()
    if "ship24_api_key" in changed:
        from app.clients import ship24 as ship24_client

        ship24_client.forget_plan()            # a new key may be on the other plan
    if changed & {"crooks_returns_read_key", "crooks_returns_write_key"}:
        from app.clients import crooks_returns

        crooks_returns.forget()                # the open returns are read whole with the new key
    if any(key.startswith("wecom_") for key in changed):
        from app.clients import wecom

        wecom.forget()                         # [messaging] tokens minted with the old Secret go
    refresh = getattr(runtime, "family_states", None)
    if callable(refresh):
        try:
            await asyncio.wait_for(refresh(), FAMILY_REFRESH_S)
        except Exception as exc:  # noqa: BLE001 - the change is made; the next /health asks again
            log.warning("connections: capability families not refreshed after a change (%s)", type(exc).__name__)


def _cleaned(connection: catalog.Connection, values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        raise ConnectionsError("bad_request", "Nothing to save.")
    out: dict[str, str] = {}
    for key, raw in values.items():
        item = catalog.field(connection, str(key))
        if item is None:
            raise ConnectionsError("bad_field", f"{connection.label} has no field called that.")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue                                   # left empty: keep what is stored
        if not isinstance(raw, str):
            raise ConnectionsError("bad_field", f"{item.label}: paste it as text.")
        if item.env:
            raw = _from_env_line(raw, item.env)
        try:
            out[item.key] = vault.clean(raw)
        except ValueError as exc:
            raise ConnectionsError("bad_value", f"{item.label}: {exc}.") from None
    if not out:
        raise ConnectionsError("nothing", "Nothing was entered, so nothing changed.")
    return out


def _from_env_line(raw: str, name: str) -> str:
    """A key copied from a server's .env as grep printed it: `NAME=value` is the value, quotes
    round it go, and of a comma-separated list (keys being rotated) the first is taken."""
    text = raw.strip()
    if text.upper().startswith(f"{name.upper()}="):
        text = text.split("=", 1)[1].strip()
    text = text.strip("'\"").strip()
    return text.split(",", 1)[0].strip() if "," in text else text


async def save(runtime: Any, name: str, values: Any, *, who: str, device: str) -> testers.Outcome:
    """Test `values` (with whatever else this connection already has), then store them."""
    connection = catalog.get(name)
    if connection is None or not connection.fields:
        raise ConnectionsError("unknown", "That connection cannot be set from the app.")
    cleaned = _cleaned(connection, values)
    # systemd-creds runs off the event loop: CLIVE goes on answering while a key is encrypted.
    ok, why = await asyncio.to_thread(vault.check)
    if not ok:
        raise ConnectionsError("store_unavailable", f"This server cannot keep keys for the app yet: {why}.")
    settings = getattr(runtime, "settings", None)
    current = await asyncio.to_thread(_current, connection)
    outcome = await testers.run(name, {**current, **cleaned}, settings, changed=frozenset(cleaned))
    if not outcome.ok:
        ledger.record("refused", connection=name, keys=sorted(cleaned), who=who, device=device, ok=False,
                      detail=outcome.detail)
        log.info("connections: %s not stored; its test failed", name)
        return outcome
    before = {key: await asyncio.to_thread(vault.entry, key) for key in cleaned}
    stored: list[str] = []
    try:
        for key, value in cleaned.items():
            await asyncio.to_thread(vault.store, key, value)
            stored.append(key)
    except (vault.VaultUnavailable, ValueError, OSError) as exc:
        for key in stored:                 # put back what was there, so a half-saved pair never runs
            previous = before[key]
            try:
                if previous.kind == "value":
                    vault.store(key, previous.value)
                elif previous.kind == "off":
                    vault.disconnect(key)
                else:
                    vault.clear(key)
            except Exception:  # noqa: BLE001
                log.error("connections: could not put back %s after a failed save", key)
        reason = str(exc) if isinstance(exc, vault.VaultUnavailable) else type(exc).__name__
        ledger.record("failed", connection=name, keys=sorted(cleaned), who=who, device=device, ok=False,
                      detail=f"not saved: {reason}")
        raise ConnectionsError("store_failed", f"Nothing was changed: {reason}.") from None
    await after_change(runtime, tuple(cleaned))
    if outcome.checked:
        ledger.tested(name, outcome.as_dict())
    ledger.record("saved", connection=name, keys=sorted(cleaned), who=who, device=device, detail=outcome.detail)
    log.info("connections: %s saved from the app (%s)", name, ", ".join(sorted(cleaned)))
    return outcome


async def test(runtime: Any, name: str) -> testers.Outcome:
    """Ask the service again with what is stored now. Changes nothing but the card. Gmail, which
    is set up at the server, is asked as /health asks it."""
    connection = catalog.get(name)
    if connection is None or name not in CHECKS:
        raise ConnectionsError("unknown", "That connection is tested at the server for now.")
    if not await asyncio.to_thread(_present, connection):
        return testers.Outcome(False, "Not connected.")
    runtime_check = CHECKS.get(name)
    try:
        if runtime_check is not None:
            outcome = await runtime_check(runtime)
        else:
            current = await asyncio.to_thread(_current, connection)
            outcome = await testers.run(name, current, getattr(runtime, "settings", None))
    except Exception as exc:  # noqa: BLE001 - a check that broke is a failed check, and it was made
        log.warning("connections: the test of %s broke (%s)", name, type(exc).__name__)
        outcome = testers.Outcome(False, "CLIVE couldn't finish checking this. Check again in a minute.", fix="retry")
    if outcome.checked:
        ledger.tested(name, outcome.as_dict())
    return outcome


async def disconnect(runtime: Any, name: str, *, who: str, device: str) -> None:
    """Take away the keys this connection cannot work without, even where the server still holds
    them, until the owner connects it again. An app's own ID and secret stay."""
    connection = catalog.get(name)
    if connection is None or not connection.fields:
        raise ConnectionsError("unknown", "That connection cannot be changed from the app.")
    for key in connection.requires:
        vault.disconnect(key)
    await after_change(runtime, connection.requires)
    ledger.forget_test(name)
    ledger.record("disconnected", connection=name, keys=list(connection.requires), who=who, device=device)
    log.info("connections: %s disconnected from the app", name)


async def signed_in(runtime: Any, outcome: testers.Outcome, *, who: str, device: str) -> None:
    """After "Sign in with Instagram" stored its token: live at once, tested, recorded."""
    await after_change(runtime, ("instagram_access_token",), new_token=False)
    ledger.tested("instagram", outcome.as_dict())
    ledger.record("signed_in", connection="instagram", keys=["instagram_access_token"], who=who, device=device,
                  ok=outcome.ok, detail=outcome.detail)
