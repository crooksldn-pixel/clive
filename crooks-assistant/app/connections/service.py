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


def card(runtime: Any, connection: catalog.Connection, *, tests: dict[str, dict[str, Any]],
         families: dict[str, dict[str, Any]], origin: str) -> dict[str, Any]:
    """One connection as its card shows it: never a secret, an ID only because it is not one."""
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
    if any(_where(k) == "app-unreadable" for k in [f.key for f in connection.fields] + list(connection.requires)):
        state, detail = "needs_attention", "A key saved here can no longer be read on this server: save it again."
    elif not all(_usable(k) for k in connection.requires):
        state, detail = "not_connected", "Not connected."
    elif last and not last.get("ok"):
        state, detail = "needs_attention", str(last.get("detail") or "The last test failed.")
    elif family_state in TROUBLED:
        state, detail = "needs_attention", str(family.get("detail") or family_state.replace("_", " ").lower())
    else:
        state, detail = "connected", str(last.get("detail") or "Connected.")
    out = {
        "name": connection.name, "label": connection.label, "what": connection.what, "note": connection.note,
        "state": state, "detail": detail, "who": str(last.get("who") or ""), "tested_at": str(last.get("at") or ""),
        "fields": fields, "editable": bool(connection.fields), "testable": connection.name in testers.TESTERS,
    }
    if connection.sign_in == "instagram":
        out["sign_in"] = {"label": "Sign in with Instagram", "redirect_uri": instagram.redirect_uri(origin),
                          "ready": all(_usable(k) for k in ("instagram_app_id", "instagram_app_secret"))}
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
    }


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
        try:
            out[item.key] = vault.clean(raw)
        except ValueError as exc:
            raise ConnectionsError("bad_value", f"{item.label}: {exc}.") from None
    if not out:
        raise ConnectionsError("nothing", "Nothing was entered, so nothing changed.")
    return out


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
    """Ask the service again with what is stored now. Changes nothing but the card."""
    connection = catalog.get(name)
    if connection is None or name not in testers.TESTERS:
        raise ConnectionsError("unknown", "That connection is tested at the server for now.")
    if not all(_usable(k) for k in connection.requires):
        return testers.Outcome(False, "Not connected.")
    outcome = await testers.run(name, _current(connection), getattr(runtime, "settings", None))
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
