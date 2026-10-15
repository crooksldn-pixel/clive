# Autonomy maturity levels

These levels describe operating maturity, not marketing claims.

## Level 0 — interactive
Claude codes while George actively supervises.

## Level 1 — delegated build
One bounded implementation can finish without continuous owner presence.

## Level 2 — closed-loop engineering
Build → checks → review → bounded repair can complete without George relaying failures.

## Level 3 — concurrent engineering
Several independent objectives progress safely under measured resource limits.

## Level 4 — project orchestration
A Project DAG coordinates dependent and parallel objectives with owner decisions separated from mechanical work.

## Level 5 — proactive engineering proposals
Bench, real-use gaps and research can generate candidate projects, but owner authority still decides what becomes engineering work.

## Level 6 — bounded continuous improvement
Low-risk improvements may progress under explicit policy, with consequential product/security/deploy decisions still reserved.

## Promotion rule

Do not advance a level because the code exists. Require:
- ACTIVE runtime evidence;
- PROVEN drills/benchmarks;
- no unacceptable ABER increase;
- owner-attention benefit;
- rollback path;
- explicit authority boundary.

## Where CLIVE stands on 2026-10-14 (evidence: CURRENT_ENGINEERING_REALITY, audit/BASELINE_EVIDENCE)

| Level | Status | Why |
|---|---|---|
| 1 Delegated build | **Reached** | One bounded change completes without the owner present: 26 COMPLETE on worker-01 |
| 2 Closed-loop engineering | **Partly reached** | Build, checks, exact-SHA CI, review, repair and landing run with no relay: 12 loop self-landings since 1 Oct. But only 35% of requests complete, and 49 of 101 requests were hand-written re-files, so the Director and George are still couriers for scope and environment stops |
| 3 Concurrent engineering | **Running without promotion** | At least 4 overlapping builders observed, but never owner-ratified, never measured against a baseline, and with no plan-limit pause or review cap |
| 4 Project orchestration | Not reached | No dependency, priority or project grouping in the loop |
| 5–6 | Not started | — |

V1's targets:

- **Level 2 fully:** review convergence restored by the re-pin, spec and environment stops caught by
  the preflight, and owner answers acted on.
- **Level 3 by measurement:** under DEC-079 ruling 4.
- **Level 4 for authorised plans of 2–6 requests on a build objective.**

**DEC-018 stays in force** (DEC-079 ruling 0). Levels 5 and 6 (proactive proposals, bounded
continuous improvement) are the expansion it holds back: automatic decomposition, proactive filing and
self-adjusting policy. They are not part of V1, and are not built until George changes DEC-018. The promotion rule above still
applies: no level is claimed until its drills and measurements pass.
