"""Ask CLIVE every question in a set, through the real turn, against the fake shop.

Each sentence goes in where a person's words go in: `POST /turn` with the text, through the door,
the session, the provider, the gate, the dispatcher and the presenters (experience/harness.py
explains why that is the same path as a spoken sentence). Nothing in between is faked or shortened.
George's questions, and the owner-door personas', carry the owner's Tailscale headers; the team's
carry their own login, which the door lets in as a member of the team the owner let in, so they reach
their own assistant with only the team's tools (app/people, app/tools/authority.py).

The model is George's Max plan, as CLIVE's own: the owner's provider is built as app/runtime.py
builds it, and each member of the team gets the assistant runtime.py makes for them, with one
difference: a bench run's assistants are strict about MCP servers (`strict_mcp_config`), so the
claude CLI on worker-01 brings none of George's own MCP servers or connectors into a bench turn,
only CLIVE's own tool server. In a scripted run the harness's recording provider answers instead
and no model is asked.

What it promises:
- The seal (app/bench/isolation.py) is on for the whole run, and the world is checked before every
  question: a run that is not on the fake shop stops before it asks.
- A write is staged as a proposal on a card and left there: nothing here arms or commits one, and
  the result says what was staged, its risk and that it is still waiting.
- The caps hold: at most `max_questions`, `concurrency` in flight, `budget_s` for the run (no
  question starts after it), `question_timeout_s` for each. A usage limit stops the run, with no retry.
- One question's conversation is never another's: each has its own session, dropped afterwards
  with its claude subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.bench import VERSION
from app.bench import persona as persona_mod
from app.bench.isolation import BenchIsolationError, Seal
from app.bench.store import Bench, new_run_id, now

log = logging.getLogger("crooks.bench.runner")

MAX_CARDS = 16
STAFF_ADDRESS = "100.64.0.20"
# A proposal in any of these was taken past its card: the bench never taps one, so any is a failure.
TAPPED = frozenset({"EXECUTING", "EXECUTED", "VERIFIED", "UNVERIFIED", "FAILED", "STALE"})


@dataclass
class Caps:
    max_questions: int = 60
    concurrency: int = 2
    budget_s: float = 90 * 60.0
    question_timeout_s: float = 300.0

    def clamp(self) -> Caps:
        return Caps(max_questions=max(1, min(int(self.max_questions), 2000)),
                    concurrency=max(1, min(int(self.concurrency), 8)),
                    budget_s=max(30.0, float(self.budget_s)),
                    question_timeout_s=max(10.0, float(self.question_timeout_s)))


@asynccontextmanager
async def fake_world():
    """The experience harness's running CLIVE on the fake shop, admitted as the owner, changes on.

    The lifespan the harness runs would start the owner's real provider (a claude subprocess,
    pre-warmed) before the harness replaces it; that start is held off until the harness is up, so
    nothing is started that the run will not use."""
    from app.providers.max_agent_sdk import MaxAgentSDKProvider
    from experience.harness import harness

    real_start = MaxAgentSDKProvider.start

    async def not_at_boot(self) -> None:
        log.info("bench: the boot-time Claude provider is not started; the run makes its own")

    MaxAgentSDKProvider.start = not_at_boot
    try:
        async with harness(admitted=True, writes=True) as h:
            MaxAgentSDKProvider.start = real_start
            yield h
    finally:
        MaxAgentSDKProvider.start = real_start


def _let_the_team_in(people: list[persona_mod.Persona]) -> dict[str, str]:
    """Each staff persona as a member of the team in the fake world: a card saying what they do,
    and the owner's approval of their (invented) login, written to the run's own scratch state.
    Returns persona id -> the card's person id."""
    from app.people import access
    from app.people.store import people as people_store

    made: dict[str, str] = {}
    for person in people:
        if person.access != "staff":
            continue
        card, _new = people_store.note({"name": person.name, "kind": "staff", "role": person.card_role,
                                        "login": person.login})
        access.ask(card.person_id, person.login)
        access.approve(card.person_id, login=person.login, by="bench", passkey="bench")
        made[person.id] = card.person_id
    return made


def _owner_provider(runtime: Any, concurrency: int):
    """CLIVE's own assistant, built as app/runtime.py builds it, on this runtime's settings, and
    strict about MCP servers: none from the host's own configuration."""
    from app.providers.max_agent_sdk import MaxAgentSDKProvider

    settings = runtime.settings
    return MaxAgentSDKProvider(
        system_prompt=runtime.system_prompt(), model=settings.claude_model,
        session_lookup=runtime.sessions.get_or_create, tool_timeout_s=settings.tool_timeout_s,
        cli_path=settings.claude_cli_path, writes_enabled=settings.writes_enabled,
        withheld_by_family=lambda: runtime.withheld_by_family(), max_concurrent_turns=concurrency,
        strict_mcp_config=True,
    )


def _strict_staff(factory: Any):
    """The team's assistants as runtime.py makes them, each strict about MCP servers as the owner's is."""
    def made(person: Any) -> Any:
        provider = factory(person)
        provider.strict_mcp_config = True
        return provider
    return made


def offered_tools(runtime: Any) -> dict[str, list[str]]:
    """The tools each door's assistant is offered on this runtime: what 'never used' is out of."""
    from app.people import staff
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import registry

    withheld = withheld_tools(registry.all_specs(), writes_enabled=bool(runtime.settings.writes_enabled))
    try:
        withheld |= {str(n) for n in (runtime.withheld_by_family() or ())}
    except Exception:  # noqa: BLE001 - the family table not filled yet withholds nothing more
        pass
    owner = sorted(n for n in registry.names() if n not in withheld)
    return {"owner": owner, "staff": sorted(n for n in owner if n in staff.TOOLS)}


def versions(mode: str) -> dict[str, str]:
    """What this run was made with: the code, the bench, the SDK and the CLI."""
    out = {"bench": VERSION}
    root = Path(__file__).resolve().parents[3]
    try:
        out["code"] = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], cwd=root, capture_output=True,
                                     text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        out["code"] = "unknown"
    try:
        import claude_agent_sdk

        out["agent_sdk"] = str(getattr(claude_agent_sdk, "__version__", "unknown"))
    except ImportError:
        out["agent_sdk"] = "not installed"
    if mode == "max":
        try:
            from app.bench.models import MaxPlanModel

            cli = MaxPlanModel()._cli() or "claude"
            out["claude_cli"] = subprocess.run([cli, "--version"], capture_output=True, text=True,
                                               timeout=20).stdout.strip()[:80] or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            out["claude_cli"] = "unknown"
    return out


# ------------------------------------------------------------------ what one turn showed


def _cards_during(session_id: str) -> list[dict[str, Any]]:
    """What the screen drew while the turn ran (the progressive workspace's patches), as shapes."""
    from app import progressive

    workspace = progressive.current(session_id)
    if workspace is None:
        return []
    return [{"op": p.op, "type": p.type, "seq": p.seq, "at_ms": None if p.at_ms is None else round(float(p.at_ms), 1)}
            for p in workspace.patches]


def _staged(session: Any, seen: set[str]) -> list[dict[str, Any]]:
    """Proposals this turn staged: what change, how risky, and that it is still waiting."""
    out = []
    for proposal in list(getattr(session, "proposals", []) or []):
        if proposal.proposal_id in seen:
            continue
        seen.add(proposal.proposal_id)
        out.append({
            "tool": proposal.tool_name, "operation": proposal.operation, "risk": proposal.risk,
            "status": getattr(proposal.status, "value", str(proposal.status)), "gesture": proposal.interaction,
            "entity": proposal.entity_kind, "label": str(proposal.entity_label or "")[:120],
            "reversible": bool(proposal.reversible), "proposal_id": proposal.proposal_id,
        })
    return out


def _tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from app.observability.timeline import scrub

    out = []
    for call in payload.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        out.append({"name": str(call.get("name") or ""), "ok": bool(call.get("ok")),
                    "error": str(call.get("error") or "")[:300], "ms": call.get("ms"),
                    "args": scrub(call.get("args") or {}), "staged": bool(call.get("proposal_id"))})
    return out


def _answer_text(payload: dict[str, Any]) -> str:
    from app.observability.timeline import _SECRET

    return _SECRET.sub("[secret]", str(payload.get("answer") or ""))


# ------------------------------------------------------------------ the run


class Run:
    """One run of a question set."""

    def __init__(self, question_set: dict[str, Any], *, bench: Bench, seal: Seal, caps: Caps, mode: str,
                 people: dict[str, persona_mod.Persona], scripts: dict[str, Any] | None = None) -> None:
        self.set = question_set
        self.bench = bench
        self.seal = seal
        self.caps = caps.clamp()
        self.mode = mode                      # "max" or "scripted"
        self.people = people
        self.scripts = scripts or {}
        self.run_id = new_run_id()
        self.stopped = ""
        self.started = 0.0
        self.cards: dict[str, str] = {}       # persona id -> people card id, for staff
        self.manifest: dict[str, Any] = {}

    def questions(self, only: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
        chosen = [q for q in self.set.get("questions") or [] if not only or q.get("persona") in only]
        missing = sorted({q.get("persona") for q in chosen} - set(self.people))
        if missing:
            raise persona_mod.PersonaError(f"the set names personas with no file here: {', '.join(missing)}")
        return chosen[: self.caps.max_questions]

    def _save(self, **changes: Any) -> None:
        self.manifest.update(changes)
        self.bench.save_manifest(self.run_id, self.manifest)

    async def go(self, only: list[str] | tuple[str, ...] = ()) -> str:
        chosen = self.questions(only)
        self.manifest = {
            "run_id": self.run_id, "status": "running", "started_at": now(), "finished_at": "",
            "mode": self.mode, "set_id": self.set.get("set_id"), "set_sha256": self.set.get("sha256"),
            "generator": self.set.get("generator"), "set_model": self.set.get("model"),
            "personas": {pid: {"name": p.name, "access": p.access, "fingerprint": p.fingerprint}
                         for pid, p in self.people.items() if any(q["persona"] == pid for q in chosen)},
            "caps": asdict(self.caps), "asked": len(chosen), "done": 0, "errors": 0, "not_run": 0,
            "versions": versions(self.mode), "models": {}, "offered_tools": {}, "breaches": 0, "stopped": "",
        }
        self._save()
        self.started = time.monotonic()
        try:
            async with fake_world() as h:
                await self._prepare(h, chosen)
                await self._ask_all(h, chosen)
        except BenchIsolationError as exc:
            self.stopped = self.stopped or f"the seal stopped the run: {exc}"
        finally:
            done = len(self.bench.results(self.run_id))
            self._save(status="stopped" if self.stopped else "finished", finished_at=now(), done=done,
                       not_run=len(chosen) - done, stopped=self.stopped, breaches=self.seal.count(),
                       breach_list=self.seal.since(0)[:50])
        return self.run_id

    async def _prepare(self, h: Any, chosen: list[dict[str, Any]]) -> None:
        runtime = h.runtime
        self.seal.arm_clients()
        self.seal.check_world(runtime)
        self.cards = _let_the_team_in([self.people[pid] for pid in {q["persona"] for q in chosen}])
        runtime.staff_providers.clear()
        if self.mode == "max":
            runtime.provider = _owner_provider(runtime, self.caps.concurrency)
            runtime.staff_provider_factory = _strict_staff(runtime.staff_provider_factory)
            await runtime.provider.start()
            self.manifest["models"] = {"turns": f"max:{runtime.settings.claude_model}"}
        else:
            for said, (tools, reply) in self.scripts.items():
                h.provider.will(said, *tools, reply=reply)
            runtime.staff_provider_factory = lambda person: h.provider
            self.manifest["models"] = {"turns": "scripted"}
        self._save(offered_tools=offered_tools(runtime))

    async def _ask_all(self, h: Any, chosen: list[dict[str, Any]]) -> None:
        gate = asyncio.Semaphore(self.caps.concurrency)

        async def one(question: dict[str, Any]) -> None:
            async with gate:
                if self.stopped:
                    return
                if time.monotonic() - self.started > self.caps.budget_s:
                    self.stopped = f"the run's time budget ({self.caps.budget_s / 60:.0f} minutes) ran out"
                    return
                row = await self._ask(h, question)
                self.bench.add_result(self.run_id, row)
                self._save(done=self.manifest.get("done", 0) + 1,
                           errors=self.manifest.get("errors", 0) + (1 if row.get("error") else 0))
                if any(t.get("error_kind") == "usage_limit" for t in row.get("turns") or []):
                    self.stopped = "the Max plan's usage limit was reached"
                if row["safety"]["breaches"]:
                    self.stopped = self.stopped or "the seal refused something during a question"

        await asyncio.gather(*(one(q) for q in chosen))

    async def _ask(self, h: Any, question: dict[str, Any]) -> dict[str, Any]:
        person = self.people[question["persona"]]
        runtime = h.runtime
        session_id = f"bench-{self.run_id[-4:]}-{question['id']}"
        headers = dict(_owner_headers()) if person.access == "owner" else {
            "Tailscale-User-Login": person.login, "X-Forwarded-For": STAFF_ADDRESS}
        breaches_before = self.seal.count()
        executions_before = int(getattr(runtime.actions, "executions", 0) or 0)
        mutations_before = int(getattr(runtime.shopify, "mutations_sent", 0) or 0)
        row: dict[str, Any] = {
            "v": 1, "run_id": self.run_id, "result_id": question["id"], "persona": person.id, "persona_name": person.name,
            "access": person.access, "category": question.get("category"), "wants": question.get("wants", ""),
            "said": list(question.get("turns") or []), "turns": [], "error": "", "started_at": now(),
        }
        started = time.perf_counter()
        try:
            self.seal.check_world(runtime)
            await asyncio.wait_for(self._turns(h, row, session_id, headers), timeout=self.caps.question_timeout_s)
        except TimeoutError:
            row["error"] = f"no answer within {self.caps.question_timeout_s:.0f}s"
        except BenchIsolationError as exc:
            row["error"] = str(exc)
            self.stopped = self.stopped or "the seal refused something"
        except Exception as exc:  # noqa: BLE001 - recorded as the failure it is; the run goes on
            row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            await self._forget(runtime, person, session_id)
        row["ms"] = round((time.perf_counter() - started) * 1000, 1)
        last = row["turns"][-1] if row["turns"] else {}
        row["answer"] = last.get("answer", "")
        row["tools_used"] = [t["name"] for turn in row["turns"] for t in turn["tools"]]
        row["cards_shown"] = [c.get("type") for turn in row["turns"] for c in turn["cards"]]
        row["staged_writes"] = [s for turn in row["turns"] for s in turn["staged"]]
        row["safety"] = {
            "executions": int(getattr(runtime.actions, "executions", 0) or 0) - executions_before,
            "shop_changes": int(getattr(runtime.shopify, "mutations_sent", 0) or 0) - mutations_before,
            "committed": sum(1 for s in row["staged_writes"] if s["status"] in TAPPED),
            "breaches": self.seal.since(breaches_before),
        }
        return row

    async def _turns(self, h: Any, row: dict[str, Any], session_id: str, headers: dict[str, str]) -> None:
        seen: set[str] = set()
        for said in row["said"]:
            began = time.perf_counter()
            response = await h.client.post("/turn", json={"text": said, "session_id": session_id}, headers=headers)
            payload = response.json() if response.content else {}
            session = h.runtime.sessions.get_or_create(session_id) if h.runtime.sessions.exists(session_id) else None
            row["turns"].append({
                "said": said, "status": response.status_code, "answer": _answer_text(payload),
                "error_kind": payload.get("error_kind"), "refused": payload.get("code") if response.status_code >= 400 else None,
                "tools": _tools(payload),
                "cards": [c for c in (payload.get("ui") or []) if isinstance(c, dict)][:MAX_CARDS],
                "cards_during": _cards_during(session_id),
                "staged": _staged(session, seen) if session is not None else [],
                "timings_ms": payload.get("timings_ms") or {},
                "ms": round((time.perf_counter() - began) * 1000, 1),
            })
            if payload.get("error_kind") == "usage_limit" or response.status_code >= 400:
                break

    async def _forget(self, runtime: Any, person: persona_mod.Persona, session_id: str) -> None:
        """The question's conversation, its claude subprocess and its screen, let go."""
        from app import progressive

        provider = runtime.provider
        if person.access == "staff":
            card = self.cards.get(person.id, "")
            provider = (runtime.staff_providers.get(card) or (None, None))[1]
        try:
            if provider is not None:
                await provider.reset_session(session_id)
        except Exception:  # noqa: BLE001 - a conversation that will not close is not a result
            log.debug("bench: resetting %s failed", session_id, exc_info=True)
        runtime.sessions.drop(session_id)
        progressive.forget(session_id)


def _owner_headers() -> dict[str, str]:
    from experience.harness import TABLET_HEADERS

    return TABLET_HEADERS


def world_environment(scratch: Path, *, claude_model: str = "", cli_path: str = "") -> None:
    """The process's settings for a run, before any of CLIVE is imported: no .env (worker-01's own
    configuration is not the fake shop's), every folder in the run's scratch space, the voice and
    the build loop off, the owner the fake world's. Every other CROOKS_ setting is taken away."""
    for name in [key for key in os.environ if key.startswith("CROOKS_")]:
        del os.environ[name]
    values = {
        "CROOKS_ENV_FILE": "", "CROOKS_LOG_DIR": scratch / "logs", "CROOKS_BENCH_AUDIO_DIR": scratch / "audio",
        "CROOKS_SECRET_DIR": scratch / "secrets", "CROOKS_OBJECTIVES_DIR": scratch / "objectives",
        "CROOKS_REPORTS_DIR": scratch / "reports", "CROOKS_SKILLS_DIR": scratch / "skills",
        "CROOKS_SAVE_CAPTURES": "false", "CROOKS_ANALYTICS_WARM_DAYS": "0", "CROOKS_INTERACTION_RECORD": "false",
        "CROOKS_ALLOWED_LOGINS": "owner@example.com", "CROOKS_LOCAL_OWNER": "false", "CROOKS_ENGINEERING_HOST": "off",
        "CROOKS_TTS_ENABLED": "false", "CROOKS_TTS_PREFETCH": "false",
        "CROOKS_TEST_SESSION_ALWAYS": "false", "CROOKS_RECORD_EXPERIENCE": "false",
    }
    if claude_model:
        values["CROOKS_CLAUDE_MODEL"] = claude_model
    if cli_path:
        values["CROOKS_CLAUDE_CLI_PATH"] = cli_path
    for name, value in values.items():
        os.environ[name] = str(value)
    from config.settings import get_settings

    get_settings.cache_clear()
