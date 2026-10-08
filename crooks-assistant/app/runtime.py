"""The composition root: one place where every component is constructed and wired together."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.actions.engine import ActionEngine
from app.actions.engine import install as install_engine
from app.actions.ledger import ActionLedger
from app.clients.elevenlabs import ScribeClient
from app.clients.elevenlabs_account import AccountCredit
from app.clients.elevenlabs_tts import VoiceClient
from app.clients.gmail import GmailClient
from app.clients.shopify import ShopifyClient
from app.clients.whisper import WhisperClient
from app.kb.loader import KnowledgeBase, build_system_prompt, load
from app.logging.turnlog import TurnLog
from app.providers.base import ClaudeProvider
from app.providers.max_agent_sdk import MaxAgentSDKProvider
from app.session.manager import SessionManager, get_manager
from app.speech.transcribe import Transcriber
from config.settings import Settings, get_settings

log = logging.getLogger("crooks.runtime")


class NoStaffAssistant(LookupError):
    """A team member's request on a runtime that cannot make their assistant (no factory set)."""


@dataclass
class Runtime:
    settings: Settings
    sessions: SessionManager
    whisper: WhisperClient
    scribe: ScribeClient
    voice: VoiceClient
    transcriber: Transcriber
    shopify: ShopifyClient
    gmail: GmailClient
    provider: ClaudeProvider
    kb: KnowledgeBase
    turnlog: TurnLog
    actions: ActionEngine
    # Bulk changes over the same engine (app/actions/batch.py).
    batches: Any = None
    # The test-session timeline (app/observability): off unless a session is active.
    tests: Any = None
    timeline: Any = None
    # The recent orders the read layer answers from (app/analytics/cache.py).
    order_cache: Any = None
    # A real customer id, for the capability probes that can only answer a question about
    # somebody. Store credit is the one that needs it: whether a store HAS store credit is a
    # per-store Shopify setting, not a scope, and the only way to find out is to ask about an
    # account. Read from the order cache the Mac warms at start-up (see `store_credit_sample`)
    # rather than fetched, so a probe costs nothing and no customer is read for its own sake.
    # What this build can do, generated from the registries (app/capabilities), and the
    # record that holds the previous build's beside it — so "what more can you do now?" is a
    # comparison the Mac makes locally rather than a question for the model.
    manifest: Any = None
    capability_record: Any = None
    # The last per-change table `capabilities()` worked out, kept so the capability card can
    # say which changes are actually ready without asking Shopify for its scopes again. The
    # card read this attribute from the day it was written and NOTHING EVER SET IT, so every
    # change and every bulk row came back "unknown" — on the one card whose whole job is
    # answering "what can you do?", where a change blocked for want of a scope then looked
    # exactly like one that is ready.
    capability_states: dict[str, dict[str, str]] = field(default_factory=dict)
    # The capability FAMILIES' states (app/capabilities/families.py), kept beside the operations
    # by family_states() so a turn can tell the model without probing anything.
    family_states_table: dict[str, dict[str, Any]] = field(default_factory=dict)
    # The tiered read cache (app/memory). Never consulted by a write.
    memory: Any = None
    started_at: float = field(default_factory=time.time)
    # Each team member's own assistant (app/people): their prompt, only their tools, their own
    # conversations. Made the first time they ask, and again when their card changes.
    staff_providers: dict[str, tuple[str, Any]] = field(default_factory=dict)
    staff_provider_factory: Any = None
    # Assistants made again (a card or the knowledge base changed): stopped at the next chance
    # no turn is running in them.
    retired_providers: list[Any] = field(default_factory=list)
    # How many turns are running in each assistant, by its id: a retired one is never stopped mid-turn.
    turns_in_flight: dict[int, int] = field(default_factory=dict, repr=False)
    build: str = ""

    @property
    def uptime_s(self) -> float:
        return time.time() - self.started_at

    def warm_orders_soon(self) -> None:
        """Start reading the recent window of orders in the background, so the first question
        about sales or stock is answered from memory. Never awaited by a turn."""
        self._warm_analytics()

    @property
    def store_credit_sample(self) -> str:
        """One customer id from what the order cache already holds, or "".

        `app/families/store_credit.py::_probe` asks Shopify whether that customer has a store
        credit account: the grants can both be present and the feature still be off, because
        Shopify enables store credit per store. Without an id the probe returned READY with
        "proven on first use" — and READY means the write tool IS offered to the model, so the
        first time the owner asked, Claude would attempt it and the shop would refuse. That is
        precisely the fifteen seconds of attempting-refused-operations that section 29 exists
        to remove, so the probe is made conclusive here instead.

        Empty is a fine answer: no cache yet, or a warm that found no order with a customer
        on it. The probe then says READY-unproven, as it did before, and nothing is claimed
        that was not checked.
        """
        cache = self.order_cache
        if cache is None:
            return ""
        try:
            rows = cache.rows()
        except Exception:  # noqa: BLE001 — a probe input is never a reason to fail a health check
            return ""
        for row in rows:
            customer = row.get("customer") if isinstance(row, dict) else None
            if isinstance(customer, dict) and customer.get("customer_id"):
                return str(customer["customer_id"])
        return ""

    def _warm_analytics(self) -> None:
        if self.order_cache is None or int(getattr(self.settings, "analytics_warm_days", 0) or 0) <= 0:
            return
        try:
            self.order_cache.warm(int(self.settings.analytics_warm_days))
        except Exception as exc:  # noqa: BLE001 — a cold cache is a slower first answer, not a fault
            log.debug("order cache warm-up not started: %s", exc)

    # Deliberately NOT warmed at boot. The lifespan runs before anything can swap the clients,
    # so a boot-time scope read goes to whatever client `build()` made — the real store, in a
    # fixture run — which is how the order cache used to hang the harness on the network. The
    # table fills instead on the first /health poll or the first turn that checks whether a
    # change may be applied, both of which happen within seconds of the tablet waking up; until
    # then the card says "unknown", which is the honest answer when nobody has checked.

    async def aclose(self) -> None:
        """Release what the process holds open: the provider's subprocesses and every kept
        HTTPS connection."""
        await self.provider.stop()
        self._retire_staff_providers()
        # Shutting down: the team's idle assistants go now; one still answering is stopped when its
        # last turn ends (`running`), and the close waits for that rather than cutting it off.
        await self._stop_retired()
        while self.retired_providers:
            await asyncio.sleep(0.05)
        for client in (self.voice, self.scribe, self.whisper, self.shopify):
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 — shutting down; nothing to do about it
                    log.debug("closing %s failed", type(client).__name__, exc_info=True)

    def reload_kb(self) -> KnowledgeBase:
        self.kb = load(self.settings.kb_dir)
        # The team's assistants carry the knowledge base in their prompts: made again next time.
        self._retire_staff_providers()
        return self.kb

    def provider_for(self, held: Any) -> Any:
        """The assistant a request talks to: a team member's own (app/people), or the owner's.

        A team member's request with no way to make their assistant fails closed: it is never
        answered by the owner's, which holds his conversations and his tools."""
        if held is not None and getattr(held, "kind", "") == "staff":
            if self.staff_provider_factory is None:
                raise NoStaffAssistant(str(getattr(held, "who", "") or ""))
            return self.staff_provider(str(held.who))
        return self.provider

    async def ensure_started(self, provider: Any) -> None:
        """A team member's assistant is started the first time it is asked, with the same checks
        as the owner's (no pay-as-you-go key, the CLI found); any it replaced are stopped once no
        turn is running in them."""
        await self._stop_retired()
        if provider is not self.provider and not getattr(provider, "started", True):
            await provider.start()

    @asynccontextmanager
    async def running(self, provider: Any) -> AsyncIterator[None]:
        """A turn running in this assistant, counted while it runs. A retired assistant is stopped
        when its last running turn ends, never by somebody else's turn while it is answering."""
        key = id(provider)
        self.turns_in_flight[key] = self.turns_in_flight.get(key, 0) + 1
        try:
            yield
        finally:
            left = self.turns_in_flight.get(key, 1) - 1
            if left > 0:
                self.turns_in_flight[key] = left
            else:
                self.turns_in_flight.pop(key, None)
                if any(retired is provider for retired in self.retired_providers):
                    await self._stop_retired()

    def staff_provider(self, person_id: str) -> Any:
        """This member of the team's assistant, made from their card as it is now: kept while the
        card is unchanged, made again (and the old one stopped) once it is not."""
        import json
        from dataclasses import asdict

        from app.people.store import people

        person = people.get(person_id)
        if person is None:
            raise KeyError(person_id)
        stamp = json.dumps(asdict(person), sort_keys=True, default=str)
        held = self.staff_providers.get(person_id)
        if held is not None and held[0] == stamp:
            return held[1]
        if held is not None:
            self.retired_providers.append(held[1])
        made = self.staff_provider_factory(person)
        self.staff_providers[person_id] = (stamp, made)
        return made

    def _retire_staff_providers(self) -> None:
        self.retired_providers.extend(made for _stamp, made in self.staff_providers.values())
        self.staff_providers.clear()

    async def _stop_retired(self) -> None:
        """Stop the retired assistants no turn is running in; one still answering is kept until
        its last turn ends (`running`)."""
        idle = [p for p in self.retired_providers if not self.turns_in_flight.get(id(p))]
        self.retired_providers[:] = [p for p in self.retired_providers if not any(p is i for i in idle)]
        for retired in idle:
            try:
                await retired.stop()
            except Exception:  # noqa: BLE001 - an old assistant that will not stop is no reason to refuse a new one
                log.debug("stopping a team member's old assistant failed", exc_info=True)

    def system_prompt(self) -> str:
        return build_system_prompt(self.kb, writes_enabled=self.settings.writes_enabled,
                                   skills=offered_skills(self.withheld_by_family()))

    @property
    def allowed_logins(self) -> tuple[str, ...]:
        return tuple(
            login.strip().lower() for login in self.settings.allowed_logins.split(",") if login.strip()
        )

    async def write_status(self, operation: str | None = None) -> WriteStatus:
        """Can a proposal execute here, now? Deterministic and read-only: configuration, the
        allow-list, and the scopes the store has granted (a query, cached). Never a mutation.
        With an operation, only that change's own scope counts: a fulfilment scope the store
        has not granted does not stop a note."""
        settings = self.settings
        if not settings.writes_enabled:
            return WriteStatus("disabled", "disabled — CROOKS_WRITES_ENABLED=false")
        if not self.allowed_logins:
            return WriteStatus("blocked", "blocked — CROOKS_ALLOWED_LOGINS not configured")
        # An undo is the change it reverses, judged by the same scope: "order_note_append_undo"
        # needs what "order_note_append" needs, nothing else.
        if operation is not None and operation.endswith("_undo"):
            operation = operation[: -len("_undo")]
        if operation is not None and operation in self._gmail_operations():
            entry = (await self._gmail_capabilities()).get(operation) or {}
            return WriteStatus(str(entry.get("state") or "blocked"), str(entry.get("detail") or "blocked"))
        if operation is not None and operation in self._github_operations():
            # Filing an engineering request needs no store scope and no Gmail grant. Its token is
            # read when the change runs; without one the change says GitHub is not connected and
            # sends nothing.
            return WriteStatus("ready", f"ready — {operation.replace('_', ' ')}")
        if operation is not None and operation in self._returns_operations():
            # A CROOKS Returns action needs no store scope: the service holds its own Shopify app.
            # It needs the write key, read when the change runs.
            from app.clients import crooks_returns

            if not crooks_returns.write_key():
                return WriteStatus("blocked", "blocked — CROOKS Returns has no write key on this server")
            return WriteStatus("ready", f"ready — {operation.replace('_', ' ')}")
        if operation is not None and operation in self._messaging_operations():
            # [messaging] A message needs no store scope: it is sent with its app's own keys (WeCom,
            # WhatsApp, Instagram), read when it is sent, and only after the owner's hold
            # (app/tools/messaging_tools.py). Which app a reply may go through is checked per
            # conversation when its card is prepared.
            from app.messaging import adapter as messaging_adapters

            if not messaging_adapters.any_configured():
                return WriteStatus("blocked", "blocked — no messaging app is connected on this server")
            return WriteStatus("ready", f"ready — {operation.replace('_', ' ')}")
        if operation is not None and operation in self._shipping_operations():
            # [shipping] A CLIVE Shipping change (a label bought or printed) needs no store scope: the
            # service holds its own Shopify app and its own PrintNode. It needs the write key, read
            # when the change runs.
            from app.clients import crooks_shipping

            if not crooks_shipping.write_key():
                return WriteStatus("blocked", "blocked — CLIVE Shipping has no write key on this server")
            return WriteStatus("ready", f"ready — {operation.replace('_', ' ')}")
        needed = {scope for op, scope in self._write_scopes().items() if operation is None or op == operation}
        if operation is not None and operation not in self._write_scopes():
            return WriteStatus("blocked", f"blocked — {operation.replace('_', ' ')} is not a change the assistant can make")
        try:
            granted = await self.shopify.access_scopes()
        except Exception as exc:  # noqa: BLE001
            # Shopify did not answer. That says nothing about what the app may do: refusing
            # here would tell the owner, out loud, that the store has not granted a scope it
            # may well have granted. The tap decides, and Shopify decides the tap.
            log.warning("could not read the Shopify app's scopes: %s", exc)
            return WriteStatus("unknown", f"ready, unverified — Shopify did not answer the scope check ({type(exc).__name__})")
        granted = set(granted)
        missing = sorted(needed - granted)
        if operation is not None:
            if missing:
                return WriteStatus("blocked", f"blocked — Shopify {', '.join(missing)} scope missing")
            return WriteStatus("ready", f"ready — {operation.replace('_', ' ')}")
        # The whole: blocked only when the store has granted none of it. A scope one change
        # needs and the store has not granted is named, and does not stop the others.
        scopes = self._write_scopes()
        ready_ops = sorted(op.replace("_", " ") for op, scope in scopes.items() if scope in granted)
        held_ops = sorted((op.replace("_", " "), scope) for op, scope in scopes.items() if scope not in granted)
        if not ready_ops:
            return WriteStatus("blocked", f"blocked — Shopify {', '.join(missing) or 'write'} scope missing")
        detail = f"ready — {', '.join(ready_ops)}"
        if held_ops:
            detail += "; " + ", ".join(f"{op} needs {scope}" for op, scope in held_ops)
        # The email changes, in the same line: what the credential allows and what it does not.
        gmail = await self._gmail_capabilities()
        gmail_ready = sorted(op.replace("_", " ") for op, entry in gmail.items() if entry.get("state") == "ready")
        gmail_held = sorted(op for op, entry in gmail.items() if entry.get("state") not in ("ready", "unknown"))
        if gmail_ready:
            detail += f"; {', '.join(gmail_ready)}"
        if gmail_held:
            first = str(gmail[gmail_held[0]].get("detail", "")).replace("blocked — ", "", 1)
            detail += f"; {', '.join(op.replace('_', ' ') for op in gmail_held)} held: {first}"
        return WriteStatus("ready", detail)

    def _write_scopes(self) -> dict[str, str]:
        """operation → the Admin API scope its reviewed mutation needs, for every registered write."""
        from app.clients.shopify import REVIEWED_MUTATIONS
        from app.tools.registry import all_specs

        return {
            s.write.operation: REVIEWED_MUTATIONS[s.write.mutation].scope
            for s in all_specs()
            if s.write is not None and s.write.mutation in REVIEWED_MUTATIONS and not s.name.startswith("mock_")
        }

    def _gmail_operations(self) -> dict[str, str]:
        """operation → the kind of Gmail call it makes (draft, send, labels), for every
        registered Gmail write. The kind is what the credential's scopes are checked against."""
        from app.tools.registry import all_specs

        return {
            s.write.operation: s.write.mutation.split(":", 1)[1]
            for s in all_specs()
            if s.write is not None and s.write.mutation.startswith("gmail:") and not s.name.startswith("mock_")
        }

    def _github_operations(self) -> set[str]:
        """Every registered GitHub write (app/tools/engineering_tools.py): the operations that
        file into the engineering loop's inbox."""
        from app.tools.registry import all_specs

        return {
            s.write.operation
            for s in all_specs()
            if s.write is not None and s.write.mutation.startswith("github:") and not s.name.startswith("mock_")
        }

    def _messaging_operations(self) -> set[str]:
        """[messaging] Every registered message send (app/tools/messaging_tools.py)."""
        from app.tools.registry import all_specs

        return {
            s.write.operation
            for s in all_specs()
            if s.write is not None and s.write.mutation.startswith("messages:") and not s.name.startswith("mock_")
        }

    def _returns_operations(self) -> set[str]:
        """Every registered CROOKS Returns write (app/tools/returns_tools.py)."""
        from app.tools.registry import all_specs

        return {
            s.write.operation
            for s in all_specs()
            if s.write is not None and s.write.mutation.startswith("returns:") and not s.name.startswith("mock_")
        }

    def _shipping_operations(self) -> set[str]:
        """[shipping] Every registered CLIVE Shipping write (app/tools/shipping_tools.py)."""
        from app.tools.registry import all_specs

        return {
            s.write.operation
            for s in all_specs()
            if s.write is not None and s.write.mutation.startswith("shipping:") and not s.name.startswith("mock_")
        }

    async def _gmail_capabilities(self) -> dict[str, dict[str, str]]:
        """Every email change, and whether the credential allows it: read back from Google
        (cached), never from a comment about what was once authorised. Re-authorisation is
        named only when Google itself refused the credential."""
        from app.clients.gmail import OPERATIONS, GmailAuthRequired, short_scopes

        operations = self._gmail_operations()
        if not operations:
            return {}
        settings = self.settings
        if not settings.writes_enabled:
            return {op: {"state": "disabled", "detail": "disabled — CROOKS_WRITES_ENABLED=false", "scope": f"gmail:{kind}"} for op, kind in operations.items()}
        if not self.allowed_logins:
            return {op: {"state": "blocked", "detail": "blocked — CROOKS_ALLOWED_LOGINS not configured", "scope": f"gmail:{kind}"} for op, kind in operations.items()}
        try:
            report = await asyncio.to_thread(self.gmail.scopes)
        except GmailAuthRequired as exc:
            return {op: {"state": "blocked", "detail": f"blocked — {exc}", "scope": f"gmail:{kind}"} for op, kind in operations.items()}
        except Exception as exc:  # noqa: BLE001 — Google not answering says nothing about the grant
            log.warning("could not read the Gmail credential's scopes: %s", exc)
            return {op: {"state": "unknown", "detail": f"ready, unverified — the Gmail scope check did not answer ({type(exc).__name__})", "scope": f"gmail:{kind}"} for op, kind in operations.items()}
        out: dict[str, dict[str, str]] = {}
        for op, kind in sorted(operations.items()):
            needs = short_scopes(OPERATIONS[kind][:2])
            if report.allows(kind):
                detail = f"ready — {op.replace('_', ' ')}" + ("" if report.verified else " (scopes as stored, unverified)")
                out[op] = {"state": "ready", "detail": detail, "scope": f"gmail:{kind}"}
            else:
                out[op] = {"state": "blocked", "detail": f"blocked — Gmail {kind} needs {needs}; the credential has {short_scopes(report.scopes)}", "scope": f"gmail:{kind}"}
        return out

    async def capabilities(self) -> dict[str, dict[str, str]]:
        """Every change the Mac knows how to make, and whether it could make it now: the
        table /health shows and the order card's rail is built from. One scope read, cached,
        serves all of them; no mutation is ever sent to find out."""
        settings = self.settings
        scopes = self._write_scopes()
        out: dict[str, dict[str, str]] = {}
        if not settings.writes_enabled:
            state, detail, granted = "disabled", "disabled — CROOKS_WRITES_ENABLED=false", None
        elif not self.allowed_logins:
            state, detail, granted = "blocked", "blocked — CROOKS_ALLOWED_LOGINS not configured", None
        else:
            state, detail = "ready", ""
            try:
                granted = set(await self.shopify.access_scopes())
            except Exception as exc:  # noqa: BLE001
                state, detail, granted = "unknown", f"ready, unverified — Shopify did not answer the scope check ({type(exc).__name__})", None
        for operation, scope in sorted(scopes.items()):
            if state == "ready" and granted is not None and scope not in granted:
                out[operation] = {"state": "blocked", "detail": f"blocked — Shopify {scope} scope missing", "scope": scope}
            else:
                out[operation] = {"state": state, "detail": detail or f"ready — {operation.replace('_', ' ')}", "scope": scope}
        try:
            out.update(await self._gmail_capabilities())
        except Exception as exc:  # noqa: BLE001
            # Gmail not answering says nothing about the Shopify half, and the Shopify half is
            # most of the table. Losing all of it to one failed credential check is not an
            # improvement on losing none of it.
            log.warning("could not read the Gmail capabilities: %s", exc)
        # Whoever asked — /health, the order card's rail, a write preflight — has just paid for
        # this, so the answer is kept where the capability card looks for it. Set before the
        # return rather than at the call sites so a half answer is still an answer.
        self.capability_states = out

        return out

    async def family_states(self) -> dict[str, dict[str, Any]]:
        """Every capability FAMILY and its state (app/capabilities/families.py) — the answer to
        "can this Mac create a discount code?", which has more shapes than the per-operation
        table: written but the scope is missing, not offered by the store, no provider
        connected, not built yet. Derived from the operation table where a family has
        operations and from its own probe where it has one. Cached with the operations."""
        from app.capabilities import families

        operations = self.capability_states or await self.capabilities()
        out = await families.states(self, operations=operations)
        self.family_states_table = out
        return out

    def withheld_by_family(self) -> set[str]:
        """The tools the model should not be offered because their capability family cannot
        work on this Mac right now (brief section 29): every tool of a family the store does
        not support, has no provider for, or that is not built; the WRITE tools of a family
        whose scope is missing or that is read-only, whose reads still work. Read from the
        table the last probe left; an unprobed family keeps its static state. The point is
        the live test's fifteen seconds of Claude trying an operation the store could only
        refuse — a tool that is not offered is not tried."""
        from app.capabilities import families
        from app.tools import registry

        table = self.family_states_table or {}
        out: set[str] = set()
        for family in families.all_families():
            state = str((table.get(family.key) or {}).get("state") or family.state)
            if state in ("NOT_SUPPORTED_BY_STORE", "DISCONNECTED", "NOT_IMPLEMENTED"):
                out.update(family.tools)
            elif state in ("MISSING_SCOPE", "READ_ONLY"):
                for name in family.tools:
                    try:
                        spec = registry.get(name)
                    except KeyError:
                        continue
                    if spec.write is not None or spec.batch is not None:
                        out.add(name)
        return out


@dataclass(frozen=True)
class WriteStatus:
    state: str     # "disabled" | "blocked" | "unknown" | "ready"
    detail: str

    @property
    def ready(self) -> bool:
        # "unknown" is the scope check having failed, not a refusal: a change may be applied
        # and Shopify has the final word on it.
        return self.state in ("ready", "unknown")

    @property
    def code(self) -> str:
        """The controlled refusal code a commit answers with while writes are not ready. The
        code names the system that is short of a permission; the detail names the permission."""
        if self.state == "ready":
            return ""
        if "WRITES_ENABLED" in self.detail:
            return "writes_disabled"
        if "ALLOWED_LOGINS" in self.detail:
            return "allow_list_missing"
        if "gmail" in self.detail.lower():
            return "gmail_scope_missing"
        return "scope_missing"



def connections_dir(settings: Any) -> Path:
    """Where the Connections screen keeps passkeys and its record of changes (never a key)."""
    import sys

    if sys.platform.startswith("linux"):
        from app.secrets import linux_store, vault

        return linux_store.store_dir() / vault.DIR_NAME
    return Path(settings.objectives_dir) / "connections"

def build(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.bench_audio_dir.mkdir(parents=True, exist_ok=True)

    sessions = get_manager(settings.session_idle_timeout_s)
    whisper = WhisperClient(settings.whisper_url, model=settings.whisper_model)
    # Speaking and listening are two products on one ElevenLabs plan and one key, so what the
    # account says about its credit is one fact. Scribe is the only one of the two that probes
    # it; the voice reads the answer here rather than paying for a synthesis to find out.
    account = AccountCredit()
    scribe = ScribeClient(
        model=settings.scribe_model,
        language=settings.scribe_language,
        timeout_s=settings.scribe_timeout_s,
        base_url=settings.elevenlabs_base_url,
        cooldown_s=settings.scribe_cooldown_s,
        account=account,
    )
    voice = VoiceClient(
        voice_id=settings.tts_voice_id,
        voice_name=settings.tts_voice_name,
        model=settings.tts_model,
        output_format=settings.tts_output_format,
        timeout_s=settings.tts_timeout_s,
        base_url=settings.elevenlabs_base_url,
        max_chars=settings.tts_max_chars,
        cooldown_s=settings.tts_cooldown_s,
        enabled=settings.tts_enabled,
        account=account,
    )
    voice.prefetch_enabled = settings.tts_prefetch
    # The voice the owner chose on the Connections screen wins over the configured one, and his
    # sliders over the voice's own defaults. Nothing stored means nothing changes: the `.env`
    # voice speaks and no voice_settings are sent (app/speech/voice_prefs.py).
    from app.speech import voice_prefs

    voice_prefs.configure(state_dir=connections_dir(settings))
    chosen = voice_prefs.read()
    if chosen:
        voice.apply(voice_id=chosen.get("voice_id", ""), voice_name=chosen.get("voice_name", ""),
                    model=chosen.get("model", ""), voice_settings=voice_prefs.voice_settings(chosen),
                    chosen_here=bool(chosen.get("voice_id")))
    # The transcript is what was said: no term list biases either recogniser and nothing
    # rewrites the words afterwards (app/speech/transcribe.py).
    transcriber = Transcriber(
        whisper,
        scribe=scribe,
        primary=settings.stt_primary,
        whisper_enabled=settings.whisper_enabled,
        save_dir=settings.bench_audio_dir if settings.save_captures else None,
        max_saved=settings.max_saved_captures,
    )

    shopify = ShopifyClient(
        settings.shopify_shop_domain,
        settings.shopify_api_version,
        auth_mode=settings.shopify_auth_mode,
    )
    gmail = GmailClient()

    # Register the tool modules. Importing them is what runs the @tool decorators.
    # The Phase 3 capability families, one module each (app/families/*): their tools, commands,
    # tap recipes and capability states register on import, after the core tools.
    from app.families import load_all as load_families
    from app.objectives import (
        tools as _objective_tools,  # noqa: F401 — registers the objective tools
    )
    from app.objectives.store import install as install_objectives
    from app.people import tools as people_tools  # noqa: F401 - registers people_list, person_note
    from app.tools import (  # noqa: F401
        analytics_tools,
        batch_tools,
        close_screen,
        display_tools,
        engineering_tools,
        gmail_tools,
        gmail_writes,
        instagram_tools,
        interaction_tools,
        messaging_tools,
        mock,
        returns_tools,
        ship24_tools,
        shipping_tools,
        shopify_tools,
        shopify_writes,
        show_again,
        skill_tools,
    )
    from app.work import tools as work_tools_module  # noqa: F401 - registers work_list, work_note

    objectives = install_objectives(settings.objectives_dir)
    # What CLIVE cannot do yet, beside the objectives that name it; the gaps already recorded
    # as blockers are counted once, the first time (app/objectives/gaps.py).
    from app.objectives import gaps as gaps_module

    gaps_module.install(settings.objectives_dir / "gaps.json").seed(objectives.all())
    # The owner's screens, beside the objectives (app/displays/store.py).
    from app.displays import store as displays_module

    displays_module.install(settings.objectives_dir / "displays.json")

    load_families()

    # The anticipation layer's learned table (§19): local, private, on this Mac, beside its
    # own logs. Installed here so every process shares one — and so a test, which points
    # CROOKS_LOG_DIR at a temporary directory, never writes into the owner's.
    from app.anticipation.learning import Learner
    from app.anticipation.learning import install as install_learner

    install_learner(Learner(path=settings.log_dir / "anticipation" / "transitions.json"))

    # The shipping provider (§20). Easyship is the provider this shop is going to use and it
    # is NOT integrated, so what is installed is its adapter in the only state it can honestly
    # be in: refusing, and naming both halves of what is missing. Installing it rather than
    # nothing is what makes the capability row and the shipping context say "Easyship is not
    # connected: CROOKS_EASYSHIP_TOKEN is unset and the client is not written" instead of the
    # vaguer "no provider" — the owner can act on the first and not on the second.
    from app.shipping import install as install_shipping
    from app.shipping.easyship import EasyshipProvider

    install_shipping(EasyshipProvider())

    shopify_tools.bind(shopify)
    from app.analytics.cache import OrderCache

    order_cache = OrderCache(lambda: runtime.shopify)
    analytics_tools.bind(order_cache)
    # `own_address` is what tells an inbound customer email from our own reply and from a
    # carrier report addressed to us: half the needs-reply noise filter is inert without it,
    # which is how the September queue offered an automated carrier report as somebody
    # waiting. Passed as the bound method, not its result — the profile is one network call
    # and it is made lazily, once, the first time a thread is actually judged.
    analytics_tools.bind_email(gmail_tools.threads_for, gmail_tools.replied, gmail_tools.reply_state,
                               own_address=gmail.address, inbox_for=gmail_tools.inbox_threads, sent_for=gmail_tools.sent_to)
    gmail_tools.bind(gmail, customer_lookup=_make_customer_lookup(shopify))
    # The engineering loop's inbox and status on GitHub. Its token is read from the secret
    # store at each call, so a Mac without one builds the same and says it is not connected.
    # With CROOKS_ENGINEERING_HOST unset (production: filing is deferred) the tools are bound to
    # an inbox that refuses every call before a token is read (app/engineering_switch.py, CFG-01).
    from app import engineering_switch

    engineering_tools.bind(engineering_switch.inbox_for(settings.engineering_host))
    engineering_tools.configure(check_python=settings.engineering_check_python)
    # [loop upgrade, 7 Oct] Why each stopped build stopped, in full, from the build server's private channel over
    # the tailnet, for the Builds screen; off unless CROOKS_ENGINEERING_PRIVATE_URL names it.
    from app.engineering_bridge import private as engineering_private

    engineering_private.configure(settings.engineering_private_url)
    # Instagram (read-only): its token is read from the secret store at each call, so a server
    # without one builds the same and says it is not connected. What is known about the token's
    # life (never the token) is kept beside CLIVE's other records, for /health.
    instagram_tools.configure(api_version=settings.instagram_api_version,
                              state_path=settings.objectives_dir / "instagram.json")
    # CROOKS Returns, the owner's returns service: where it answers (CROOKS_RETURNS_BASE_URL). Its
    # keys are read from the secret store at each call (app/clients/crooks_returns.py).
    from app.clients import crooks_returns

    crooks_returns.configure(base_url=settings.returns_base_url)
    # [messaging] WeChat and WeCom: the private store of conversations beside CLIVE's other records
    # (app/messaging/store.py), and translation by the provider built below, late-bound so a provider
    # swapped later (a test's, a team member's) is the one asked. Its keys are read at each call.
    from app.messaging import translate as messaging_translate
    from app.messaging.store import store as messaging_store

    messaging_store.configure(Path(settings.objectives_dir).parent / "messaging")
    # [shipping] CLIVE Shipping, the owner's international shipping service: where it answers
    # (CROOKS_SHIPPING_BASE_URL). Its keys are read from the secret store at each call
    # (app/clients/crooks_shipping.py).
    from app.clients import crooks_shipping

    crooks_shipping.configure(base_url=settings.shipping_base_url)
    # The Connections screen (app/connections): the owner's passkeys and the record of changes to
    # connections live beside the keys stored from the app, in the root-only secret directory on
    # Linux; on a Mac, whose keys are in the Keychain, beside CLIVE's other records.
    from app.connections import service as connections_service
    from app.people import access as staff_access

    connections_service.configure(state_dir=connections_dir(settings))
    # Who on the team the owner has let in is kept beside his passkeys: a line there opens the door.
    staff_access.configure(state_dir=connections_dir(settings))
    # The skills the installer adopted, in this runtime's settings.skills_dir: read by skill_list
    # and skill_read, never run (app/tools/skill_tools.py). Set before the prompt below names them,
    # so the prompt and the tools read the same folder.
    skill_tools.configure(skills_dir=settings.skills_dir)

    kb = load(settings.kb_dir)
    provider = MaxAgentSDKProvider(
        system_prompt=build_system_prompt(kb, writes_enabled=settings.writes_enabled, skills=offered_skills()),
        model=settings.claude_model,
        session_lookup=sessions.get_or_create,
        tool_timeout_s=settings.tool_timeout_s,
        cli_path=settings.claude_cli_path,
        writes_enabled=settings.writes_enabled,
        # Late-bound: the runtime is built a few lines down, and the table it reads is
        # filled by the first /health or capability probe after that.
        withheld_by_family=lambda: runtime.withheld_by_family(),
    )
    messaging_translate.bind(lambda system, text, **kw: runtime.provider.complete(system, text, **kw))
    # The action engine is installed process-wide: the dispatcher stages into it from inside a
    # Claude turn, and the tablet's tap reaches it through the runtime. One index for both.
    actions = install_engine(ActionEngine(ledger=ActionLedger(settings.log_dir)))
    # A session the store lets go takes its proposals with it: nothing stays tappable, and
    # nothing of it stays in memory, once the conversation is over.
    if actions.forget_session not in sessions.on_drop:
        sessions.on_drop.append(actions.forget_session)
    from app.actions.batch import BatchEngine
    from app.actions.batch import install as install_batches

    batches = install_batches(BatchEngine(actions, ledger=actions.ledger))
    if batches.forget_session not in sessions.on_drop:
        sessions.on_drop.append(batches.forget_session)

    if not settings.allowed_logins:
        log.warning(
            "CROOKS_ALLOWED_LOGINS is empty: any tailnet login may ask (reads only; changes need "
            "the allow-list). Open /whoami on the owner's device and put its login in .env."
        )
    from app.actions import ledger as ledger_module
    from app.observability import hooks as observe_hooks
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline
    from app.observability.timeline import install as install_timeline

    tests = TestSessions.from_settings(settings)
    if settings.test_session_always:
        log.info("test mode is ALWAYS ON: each day is one test session (logs/test-sessions/, kept %s days)%s",
                 settings.test_session_keep_days, "; screen snapshots on" if settings.screen_snapshots else "")
    timeline = install_timeline(Timeline(tests))
    ledger_module.observe(observe_hooks.ledger_observer)
    # The production experience recorder (brief section 26), if it has been asked for. It hangs
    # off the timeline as a second sink, so recording costs the turn's path nothing and adds no
    # line to it; and it writes to its own directory, so `make test-session-report` can never
    # take a recording for a test session. Off, this is one boolean.
    if settings.record_experience:
        from app.observability import recorder as recorder_module

        recordings = recorder_module.Recordings(settings.log_dir)
        timeline.mirror = recorder_module.install(
            recorder_module.Recorder(recordings, keep_transcripts=settings.record_transcripts)
        )
        log.info("experience recording is ON (transcripts %s); logs/%s/",
                 "kept" if settings.record_transcripts else "as shape only", recorder_module.DIR_NAME)
    # [recording] The interaction record (app/observability/interactions.py): every turn and
    # gesture of normal use, so CLIVE can look at what it drew and why. In front of whatever
    # mirror is there, which still gets every event. CROOKS_INTERACTION_RECORD=false turns it off.
    from app.observability import interactions

    if settings.interaction_record:
        timeline.mirror = interactions.install(
            interactions.InteractionRecord.from_settings(settings, behind=timeline.mirror))
        log.info("the interaction record is ON: logs/%s/, %s days kept, words %s", interactions.DIR_NAME,
                 settings.interaction_record_keep_days, "kept" if settings.interaction_record_words else "by their shape")
    else:
        interactions.install(None)

    # The manifest, and the recipes the taps name, before the first tap. The families
    # registered their recipes when they loaded above; asserting they are read-only is what
    # keeps them honest, and it happens here so a mistake stops the process rather than a tap.
    from app import recipes as recipe_registry
    from app.capabilities.delta import record_build
    from app.capabilities.manifest import build as build_manifest
    from app.memory import Memory
    from app.memory import install as install_memory

    recipe_registry.assert_read_only()
    memory = install_memory(Memory())
    manifest = build_manifest(build_id=web_build_id(), writes_enabled=settings.writes_enabled)
    capability_record = record_build(manifest, settings.log_dir)

    runtime = Runtime(
        build=web_build_id(),
        settings=settings,
        sessions=sessions,
        whisper=whisper,
        scribe=scribe,
        voice=voice,
        transcriber=transcriber,
        shopify=shopify,
        gmail=gmail,
        provider=provider,
        kb=kb,
        turnlog=TurnLog(settings.log_dir),
        actions=actions,
        batches=batches,
        tests=tests,
        timeline=timeline,
        order_cache=order_cache,
        manifest=manifest,
        capability_record=capability_record,
        memory=memory,
    )
    # A change applied to an order makes what the cache holds of it stale: dropped, re-read.
    shopify_tools.hydrator().on_forget.append(order_cache.invalidate)
    # The write policy (refund on cancel, restock, notify) is the runtime's settings, read
    # at prepare time, so a test's configured runtime is what the card prints.
    shopify_writes.bind_policy(lambda: runtime.settings)
    gmail_writes.bind(gmail, policy=lambda: runtime.settings)
    # The team (app/people, app/work): their cards and the work list beside CLIVE's other records,
    # and an assistant for each of them made from their card, offered only the tools the owner
    # allowed them (app/people/staff.py). Nothing of the owner's conversations is in it.
    from app.people.store import people as people_store
    from app.work import tools as work_tools
    from app.work.store import work as work_store

    people_store.configure(Path(settings.objectives_dir).parent / "people.json")
    work_store.configure(Path(settings.objectives_dir).parent / "work")
    work_tools.bind(runtime)
    runtime.staff_provider_factory = lambda person: _staff_provider(runtime, person)
    return runtime


def offered_skills(withheld: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """The installed skills' names for the system prompt, only while skill_list and skill_read
    are both offered; none otherwise, so the prompt is what it was without them. Never raises:
    the skills folder holds files written outside CROOKS, and nothing in it may stop the app
    starting (`build`) or the knowledge base reloading (`Runtime.system_prompt`)."""
    from app.tools import registry, skill_tools

    try:
        registered = set(registry.names())
        if any(name not in registered or name in withheld for name in skill_tools.TOOLS):
            return []
        return skill_tools.names()
    except Exception as exc:  # noqa: BLE001 - a prompt without the skills' names, rather than no app
        log.warning("the installed skills could not be named in the prompt: %s", type(exc).__name__)
        return []


def _staff_provider(runtime: Runtime, person: Any) -> Any:
    """A team member's own assistant: their prompt, the knowledge base, and only their tools."""
    from app.people import staff
    from app.people.prompt import build_staff_prompt
    from app.tools import registry

    settings = runtime.settings
    not_theirs = {name for name in registry.names() if name not in staff.TOOLS}
    return MaxAgentSDKProvider(
        system_prompt=build_staff_prompt(person, runtime.kb.text),
        model=settings.claude_model,
        session_lookup=runtime.sessions.get_or_create,
        tool_timeout_s=settings.tool_timeout_s,
        cli_path=settings.claude_cli_path,
        writes_enabled=settings.writes_enabled,
        withheld_by_family=lambda: set(runtime.withheld_by_family()) | not_theirs,
    )


def _make_customer_lookup(shopify: ShopifyClient):
    """Cross-reference an email sender against Shopify customers, cached per process.

    Gmail must keep working when Shopify does not, so a failure here returns None ("could not
    check"), never False ("not a customer") — those are different answers.
    """
    cache: dict[str, bool] = {}
    max_entries = 2000

    async def lookup(email: str) -> bool | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        if email in cache:
            return cache[email]
        from app.tools.shopify_tools import _search_customers

        matches = await _search_customers(shopify, f"email:{email}", limit=1)
        if len(cache) >= max_entries:
            cache.clear()
        cache[email] = bool(matches)
        return cache[email]

    return lookup


def web_build_id(web_dir: Path | None = None) -> str:
    """A short fingerprint of the tablet page's files, so a page that has been open for days
    can tell that the Mac now serves a newer one."""
    import hashlib

    web_dir = web_dir or (Path(__file__).resolve().parent.parent / "web")
    digest = hashlib.sha1()
    try:
        for path in sorted(web_dir.glob("*")):
            if path.is_file():
                stat = path.stat()
                digest.update(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}\n".encode())
    except OSError:
        return "unknown"
    return digest.hexdigest()[:12]


def seed_paths(settings: Settings) -> list[Path]:
    return [settings.kb_dir, settings.bench_audio_dir, settings.log_dir]
