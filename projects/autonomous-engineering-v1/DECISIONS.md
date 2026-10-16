# Planning decisions

These are project-planning decisions only. They do not amend CLIVE's canonical DECISIONS.md. Once
implementation is approved, each stage is recorded there as a new DEC entry.

**Governing canonical decisions** (trunk `ef204bc2`):

| Decision | What it says |
|---|---|
| DEC-018 | In force in full (DEC-079 ruling 0) |
| DEC-079 | Ruling 4 (parallel engineering), ruling 5 (one Max plan), ruling 9 (filing authority) |
| DEC-064 | Landing |
| DEC-068 and DEC-076 | Built; they await the re-pin |
| DEC-071 | Ruling 9 (the loop is the normal path), ruling 11 (stop the production-host loop after the re-pin), ruling 12 (no Issues board) |
| DEC-072 | Deploy |
| DEC-012 and DEC-043 | Isolation |

## P-001 — Desktop is supervisor, not durable worker
Claude Desktop is the interactive client. The supervisor runs commands on worker-01 as a non-root
user (O-2). Durable execution belongs to the existing loop. Anthropic's documentation says a Desktop
SSH session is not to be counted on overnight.

## P-002 — reuse before replace
The audit found nothing that makes the dispatcher insufficient. Its gaps are small extensions at named
seams.

## P-003 — no automatic production deploy
Deploys are George's (DEC-072, DEC-071 rulings 6–8).

## P-004 — no agent swarm
The roles are supervisor, builder, sandbox and CI verification, and independent reviewer.

## P-005 — concurrency is an engineering setting chosen by measurement (DEC-079 ruling 4)
It is bounded by three things:
- host resources;
- the one Max plan, with live CLIVE and staff use first;
- DEC-012 and DEC-043.

RP1 runs at 2, and the ladder (PR 13) picks the standing value. It grants no authority.

## P-006 — CLI before engineering MCP
`clive-eng` is a thin `--json` shell over the shared engineering library.

## P-007 — selective skills and context
Skills are routed by path (`applies_to`) through the existing per-attempt plugin folder.

## P-008 — evidence-backed completion
A model statement is never proof. "Verified" needs evidence; DEC-082, the Director's, builds that.

## P-009 — delivery through two re-pins and two deploys
- **RP1:** today's trunk, which brings DEC-068 and DEC-076 into force. The largest bottleneck first.
- **D1:** the preflight and archive-safe ids.
- **RP2:** dependencies, FIFO, `land`, the plan-limit pause, self-description and routing.
- **D2:** the ruling-9 model, project rows and the supervisor's channel.

**Rollbacks:**
- **RP1:** re-pin the rehearsed pin (the A1 pin, unless RP1's rehearsal says otherwise).
- **D1:** revert PR 3 and keep PR 2, which rolls forward only once archived.
- **RP2:** re-pin a rehearsed target with `--no-land` until in-flight `land: false` work is terminal.
- **D2:** redeploy. Filing then needs his hold again.

## P-010 — dependencies gate intake, not the kernel
A dependent is deferred at the adapter (`waits.py` pattern) and admitted on a green trunk head that
contains its predecessors.

## P-011 — the Project is CLIVE's `Objective(kind=build)`
- **It holds:** the owner's words, purpose, done-when, `engineering[]`, typed blockers, attention,
  history, and owner-only authorise.
- **Requests carry** only `depends_on`, `supersedes` and `land`. The loop cannot read production
  objectives.
- **Project state is derived for Builds**, never stored.

There is no separate store and no manifest. An inert packet file on the inbox branch was proposed in
revision 3 and dropped in revision 4.

## P-012 — Bench is pre-deploy evidence in V1, not a landing gate
`clive-eng deploy-brief` shows an existing Bench report.

## P-013 — stay on the Claude Code CLI
No Agent SDK, `--bare` or API key.

## P-014 — no automatic reviewer failover

## P-015 — judge V1 on real work
- **Owner measures:** V1-real against B0. B0 is real work after RP1 and before D1.
- **Machine side:** B1 against history.
- **Replay chains** are a dependency drill, not a comparison.

## P-016 — owner answers act through his gesture, never a kernel owner adapter
- "Try again": his confirmed answer is the hold for that exact re-file (DEC-079; DEC-082 builds it).
- "Allow the change": his hold files the re-file and widens that item (PR 8).

## P-017 — scope is fixed at filing; no widening inside the loop (`dispatcher.py:828-829`)

## P-018 — no new fields on kernel records or `obj_x.json`
New facts go in optional request fields, the adapter sidecar, or the objective's design file.

## P-019 — nothing writes the loop's inbox except CLIVE's filing path
- The supervisor drafts, and CLIVE files.
- The loop never writes its own inbox.
- The Director archives once by hand after D1, until automatic archiving is approved.
- **After archiving, any request the Director still commits by hand is first checked against
  `archive/` and the status receipts.** One reused id makes the loop refuse every snapshot
  (`controller.py:245-249`).

## P-020 — nothing DEC-068 keeps private goes on GitHub
Re-files carry finding ids and dispositions, never finding text.

## P-021 — DEC-018 bounds V1
Inside V1:
- making approved things work;
- capacity (ruling 4);
- the ruling-9 model.

Outside V1:
- automatic decomposition into unseen work;
- proactive filing;
- self-adjusting policy;
- autonomy levels 5 and 6.

## P-022 — one implementation per behaviour
| Owner | Builds |
|---|---|
| The Director | DEC-080 (outside text), DEC-081 (draft orders, record writes, pinned dependencies, pinned Actions), DEC-082 ("verified", build items from loop records, the MAP and FEATURES check, "Try again") |
| This project | The ruling-9 model; the preflight inside `submit_engineering_request`; the re-pins and retiring the production-host loop; concurrency settings; "Allow the change"; triage; `depends_on`; project rows; archiving; `clive-eng`; metrics |

This plan rebases on DEC-081 and calls DEC-082's hook rather than duplicating it.

---

## Owner decisions, recorded 2026-10-15

**George approved the plan (revision 4, planning commit `701a27a8`) and authorised Stage A only.**
DEC-018 remains fully in force. These are his rulings, as given:

### O-1 — APPROVED: the ruling-9 filing-authority model ([FILING_AUTHORITY.md](FILING_AUTHORITY.md))

**Bounds, as proposed:**
- at most 2 retries;
- splits one level deep;
- at most 4 untapped filings per approved item.

**His conditions:**
- Retries, repairs, approved splits and dependency-ordered requests may file without another gesture
  **only while they stay inside the exact scope he already approved**.
- **The authorised boundary is determined from structured plan and request fields, allowed paths and
  acceptance criteria.**
- These **remain owner-gated under DEC-018**:
  - new scope;
  - new protected paths;
  - materially new acceptance objectives;
  - authority expansion;
  - proactive work;
  - decomposition he has not seen.
- **"Stop filing for this" immediately revokes the remaining authority.**

It is built in Stage D (PRs 7 and 8). Until then every filing waits for his hold, as today.

### O-2 — APPROVED, with the recommended design: the supervisor's identity

- A dedicated non-root supervisor identity on worker-01.
- **A narrow read group** for the owner-only stop reports (PR 6's `--stops-read-group`, at RP2),
  rather than loosening general permissions.
- **Only the minimum credential** needed to use CLIVE's legitimate filing and draft path.
- **It never receives** the engineering loop's token, production credentials, production secrets, or
  general production access.
- **It never pushes directly to the engineering inbox.**
- Claude Desktop on his Mac is the interactive client. Durable execution remains in CLIVE's worker and
  dispatcher.

### O-3 — DEFERRED until baseline: the OAMAB threshold

OAMAB is measured during V1 (B0, then V1-real) before a numerical threshold is chosen. It does not
block implementation. The baseline will be recorded and a threshold recommended from the measured
results.

### The audit disclosure — ACCEPTED

The incidental production `.git/index` refresh is accepted as an audit disclosure and does not block
Stage A. **It is not permission for any further production mutation.**

### Stage A authorisation, in his order
1. Run the read-only worker-01 audit (WORKER01_AUDIT.md).
2. Compare the actual pin, Claude Code version, concurrency, reviewer, service state and configuration
   with revision 4.
3. **On material unexpected drift: stop and report before changing the worker.**
4. Otherwise perform RP1 exactly as specified, at concurrency 2. That is an engineering setting, not
   a new owner-imposed limit, and it is not raised during Stage A.
5. Verify the re-pinned loop is healthy **before** disabling the stale production-host loop.
6. Then stop and disable the production-host loop (ruling 11).
7. Verify there is one canonical engineering loop.
8. Report the evidence.

Stage B and any V1 application code are not authorised yet.

**Open calls that V1 does not need** (listed so nothing is lost; no answer is required to start):

| Call | Status |
|---|---|
| Re-pin review model | GPT `root-repin.sh` or Claude (DEC-076's open call). V1 uses the existing script |
| Curated builder skills | His list (DEC-064). NEXT, once worker-01 runs a gated CLI |
| Heterogeneous dual review | NEXT |
| Workspace cleanup policy | NEXT; proposed 14 days for terminal objectives |
| Carrying `.mcp.json`, the planning agents or skills to trunk | Not done. An MCP server for every session would be his (DEC-064) |

## Owner decisions, recorded 2026-10-16

**George closed Stage A and started B0.** These are his rulings, as given.

### Stage A: COMPLETE, at the completed re-pin and migration state (planning commit `d4319a01`)
Its scope is not extended because further items were grouped under Stage A in the plan.

### B0: ACTIVE ([B0.md](B0.md))
**During B0:**
- the current worker-01 system is used as it is now;
- concurrency stays 2;
- Claude stays the reviewer;
- builder skills stay off on this worker;
- default repair rounds stay 2.

**Not during B0:**
- no change to filing authority;
- no tuning of retry or repair behaviour;
- no preflight, triage, `depends_on`, archiving, `clive-eng`, plan limits or other V1 behaviour;
- no deploy of PR 1's measurement or application-code changes.

**Real engineering work continues as normal,** so that the baseline reflects genuine use rather than
synthetic tests.

### What B0 records
The metrics the plan already defines, particularly:
- OAMAB;
- elapsed time to accepted build;
- completion and block rate;
- repair rounds;
- re-files;
- owner interruptions and actions;
- CI and check failures;
- reviewer stops and non-convergence;
- environment and base failures;
- scope failures;
- queue and concurrency behaviour.

### PR 0 and PR 1
- **PR 0:** only a genuinely documentation-only catch-up, if still useful. It must not alter runtime
  behaviour or B0 measurements.
- **PR 1:** not started until B0 is frozen, unless the existing system literally cannot collect a
  required baseline metric. In that case the missing measurement is reported to him first, rather
  than instrumentation being added silently.

### O-3
Remains deferred. No OAMAB target is invented before B0 gives the distribution.

### Plan state
```
Stage A: COMPLETE
B0: ACTIVE
Stage B/application implementation: NOT STARTED
```

## Settled by canonical records (removed from the owner list in revision 4)

| Former question | Settled by |
|---|---|
| Parallel builders, and the concurrency value | DEC-079 ruling 4: an engineering setting by measurement |
| The per-filing hold | DEC-079 ruling 9: removed in principle; its model is O-1 |
| Stopping the production-host loop | DEC-071 ruling 11: after the re-pin (RP1 step 5) |
| The Claude reviewer | DEC-071 ruling 10, DEC-076 |
| Landing without a gesture | DEC-064's four conditions |
| Deploy authority and the release service | DEC-071 rulings 6–8, DEC-072 |
| The loop as the normal path | DEC-071 ruling 9 |
| A GitHub Issues board | DEC-071 ruling 12: no |
| CI on worker-01 | DEC-071 ruling 5: only once the repository is private |
| Topology | worker-01 is the loop; production is not |
| One Max plan | DEC-079 ruling 5 |
| The private stops channel in production | DEC-068: it provides for it, set at D2 |
| Merging Director PRs | Existing practice: an independent pre-merge review at the exact SHA (DEC-071 ruling 6), then a non-author merge |
| The plan budget for measurement, the dependency-wait bound, where Bench runs, the fault-injection bar | Engineering settings under ruling 4, with live use first; reported to him, not asked |
| Public project packets | Moot: no packets. The project is the build objective, on production |
