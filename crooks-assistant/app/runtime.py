"""The composition root: one place where every component is constructed and wired together."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.actions.engine import ActionEngine
from app.actions.engine import install as install_engine
from app.actions.ledger import ActionLedger
from app.clients.elevenlabs import ScribeClient
from app.clients.elevenlabs_tts import VoiceClient
from app.clients.gmail import GmailClient
from app.clients.shopify import ShopifyClient
from app.clients.whisper import WhisperClient
from app.kb.loader import KnowledgeBase, build_system_prompt, load
from app.logging.turnlog import TurnLog
from app.providers.base import ClaudeProvider
from app.providers.max_agent_sdk import MaxAgentSDKProvider
from app.session.manager import SessionManager, get_manager
from app.speech.normalise import Normaliser, from_file
from app.speech.transcribe import Transcriber
from config.settings import Settings, get_settings

log = logging.getLogger("crooks.runtime")

CATALOGUE_TTL_S = 3600  # M7: refresh the live product catalogue hourly


@dataclass
class Runtime:
    settings: Settings
    sessions: SessionManager
    whisper: WhisperClient
    scribe: ScribeClient
    voice: VoiceClient
    normaliser: Normaliser
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
    build: str = ""
    _catalogue_refreshed_at: float = 0.0
    _catalogue_task: asyncio.Task | None = None

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

    def refresh_catalogue_soon(self) -> None:
        """Kick the hourly catalogue refresh off beside the current turn rather than in front
        of it. A turn never waits on Shopify for a list it does not need to answer."""
        if time.time() - self._catalogue_refreshed_at < CATALOGUE_TTL_S:
            return
        if self._catalogue_task is not None and not self._catalogue_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._catalogue_task = loop.create_task(self.maybe_refresh_catalogue())

    async def aclose(self) -> None:
        """Release what the process holds open: the provider's subprocesses and every kept
        HTTPS connection."""
        if self._catalogue_task is not None and not self._catalogue_task.done():
            self._catalogue_task.cancel()
        await self.provider.stop()
        for client in (self.voice, self.scribe, self.whisper, self.shopify):
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 — shutting down; nothing to do about it
                    log.debug("closing %s failed", type(client).__name__, exc_info=True)

    async def maybe_refresh_catalogue(self) -> None:
        """Repoint the normaliser at the live Shopify catalogue, hourly, cached to disk.

        Failure here is not fatal: the seed terminology file keeps working, which is the whole
        reason M3 built against a file rather than waiting for M7.
        """
        if time.time() - self._catalogue_refreshed_at < CATALOGUE_TTL_S:
            return
        self._catalogue_refreshed_at = time.time()
        try:
            from app.tools.shopify_tools import catalogue_terms

            live = await catalogue_terms()
        except Exception as exc:  # noqa: BLE001
            log.warning("live catalogue unavailable, keeping the seed list: %s", exc)
            return
        if not live:
            return
        seed = list(self.normaliser.catalogue.terms)
        cache = self.settings.kb_dir / ".catalogue-cache.txt"
        try:
            # Products only. Customer names are personal data and do not belong in a file.
            cache.write_text("\n".join(t for t in live if t in set(live[: live_product_count(live)])), encoding="utf-8")
        except OSError:
            pass
        # Live terms first, hand-written seed (with its aliases) LAST: the Whisper prompt is
        # truncated from the front, so the terms the owner wrote must be the ones that survive.
        merged = live + seed
        # Everything after the boundary is a person. Those names still correct transcripts on
        # this Mac; they are held back from the Scribe keyterms, which leave it.
        # `seed` carries last hour's terms forward, so the names already marked personal are
        # carried forward with them — a name is never quietly un-marked by the next refresh.
        # (Catalogue stores personal entries in comparison form; cleaning them twice is a no-op.)
        customers = live[live_product_count(live) + 1 :] + list(self.normaliser.catalogue.personal)
        self.normaliser.repoint(
            merged, aliases=self.normaliser.catalogue.aliases, personal=customers
        )
        log.info("normaliser repointed at live catalogue: %d terms", len(merged))

    def reload_kb(self) -> KnowledgeBase:
        self.kb = load(self.settings.kb_dir)
        return self.kb

    def system_prompt(self) -> str:
        return build_system_prompt(self.kb, writes_enabled=self.settings.writes_enabled)

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
        needed = {scope for op, scope in self._write_scopes().items() if operation is None or op == operation}
        if operation is not None and operation not in self._write_scopes():
            return WriteStatus("blocked", f"blocked — {operation.replace('_', ' ')} is not a change this Mac can make")
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


def build(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.bench_audio_dir.mkdir(parents=True, exist_ok=True)

    sessions = get_manager(settings.session_idle_timeout_s)
    whisper = WhisperClient(settings.whisper_url, model=settings.whisper_model)
    scribe = ScribeClient(
        model=settings.scribe_model,
        language=settings.scribe_language,
        timeout_s=settings.scribe_timeout_s,
        base_url=settings.elevenlabs_base_url,
        max_keyterms=settings.scribe_max_keyterms,
        cooldown_s=settings.scribe_cooldown_s,
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
    )
    voice.prefetch_enabled = settings.tts_prefetch
    normaliser = _build_normaliser(settings)
    transcriber = Transcriber(
        whisper,
        normaliser,
        scribe=scribe,
        primary=settings.stt_primary,
        whisper_enabled=settings.whisper_enabled,
        keyterms=settings.scribe_keyterms,
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
    # recipes, intent families and capability states register on import, after the core tools.
    from app.families import load_all as load_families
    from app.tools import (  # noqa: F401
        analytics_tools,
        batch_tools,
        gmail_tools,
        gmail_writes,
        mock,
        shopify_tools,
        shopify_writes,
    )

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
                               own_address=gmail.address)
    gmail_tools.bind(gmail, customer_lookup=_make_customer_lookup(shopify))

    kb = load(settings.kb_dir)
    provider = MaxAgentSDKProvider(
        system_prompt=build_system_prompt(kb, writes_enabled=settings.writes_enabled),
        model=settings.claude_model,
        session_lookup=sessions.get_or_create,
        tool_timeout_s=settings.tool_timeout_s,
        cli_path=settings.claude_cli_path,
        writes_enabled=settings.writes_enabled,
        # Late-bound: the runtime is built a few lines down, and the table it reads is
        # filled by the first /health or capability probe after that.
        withheld_by_family=lambda: runtime.withheld_by_family(),
    )
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
            "the allow-list). Open /whoami on the tablet and put its login in .env."
        )
    from app.actions import ledger as ledger_module
    from app.observability import hooks as observe_hooks
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline
    from app.observability.timeline import install as install_timeline

    tests = TestSessions(settings.log_dir)
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

    # The manifest, and the fast lane's recipes, before the first question. Importing the
    # library is what registers the recipes; asserting they are read-only is what keeps them
    # honest, and it happens here so a mistake stops the process rather than a turn.
    from app.capabilities.delta import record_build
    from app.capabilities.manifest import build as build_manifest
    from app.fastpath import library as _recipes  # noqa: F401 — imported for its registrations
    from app.fastpath import recipes as recipe_registry
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
        normaliser=normaliser,
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
    return runtime


def live_product_count(live: list[str]) -> int:
    """catalogue_terms() returns products then customers; a sentinel marks the boundary."""
    try:
        return live.index(CUSTOMER_BOUNDARY)
    except ValueError:
        return len(live)


CUSTOMER_BOUNDARY = "\x00customers"


def _build_normaliser(settings: Settings) -> Normaliser:
    seed = settings.kb_dir / "terminology.md"
    normaliser = from_file(seed)
    cache = settings.kb_dir / ".catalogue-cache.txt"
    if cache.exists():
        # A warm start uses last hour's live catalogue rather than falling back to the seed.
        try:
            cached = [t for t in cache.read_text(encoding="utf-8").splitlines() if t.strip()]
            normaliser.repoint(
                cached + list(normaliser.catalogue.terms), aliases=normaliser.catalogue.aliases
            )
        except OSError:
            pass
    return normaliser


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
