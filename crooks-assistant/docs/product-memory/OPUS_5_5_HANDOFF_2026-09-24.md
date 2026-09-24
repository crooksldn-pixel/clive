# OPUS 5.5 HANDOFF — CLIVE

Date: 2026-09-24
Owner: George Hinxman
Repository: `crooksldn-pixel/clive`

This document is the authoritative handoff for moving the current CLIVE engineering session into a fresh Opus 5.5 chat.

## 1. Product definition

CLIVE is intended to be a persistent intent-to-execution operational layer, not a chatbot, dashboard, or thin model wrapper.

Durable semantics:
- objectives;
- identity;
- evidence / provenance;
- time;
- uncertainty;
- authority / permissions;
- capabilities;
- commitments / dependencies;
- outcomes / verification.

Replaceable implementation:
- models/providers;
- agent frameworks;
- databases;
- user interfaces;
- orchestration;
- connectors;
- worker roles.

Core doctrine:

> Preserve accumulated understanding; make accumulated implementation expendable.

Target engineering hierarchy:

> Owner → GPT Director → deterministic engineering control plane → model workers → independent reviewer/integrator → owner gate where required.

Workers are replaceable capabilities, not CLIVE itself.

State invariant:

> NEEDED / PROPOSED ≠ AUTHORISED ≠ STARTED ≠ COMPLETED ≠ VERIFIED

Self-building does not mean self-deciding, self-certifying, or self-deploying.

## 2. Owner/operator preference

George does not want to remain a human terminal courier.

Desired workflow:

> Owner says what outcome is wanted → Director/control plane submits bounded engineering objective → CLIVE selects/launches workers → checks → exact-SHA independent review → bounded repair → verified candidate → owner only for genuine owner decisions.

Do not make George repeatedly copy shell output between GPT and Claude unless there is no safe alternative.

## 3. Permanent authority / safety invariants

Do not bypass these:

- No deployment/promotion, production service changes, runtime/systemd/watchers changes, permission/privilege changes, secrets/credential reads, public exposure, external spend, business writes, destructive cleanup, or owner-only decisions without explicit owner authority.
- Builders must not receive business connectors or credentials.
- Candidate code must not control its own acceptance machinery.
- Worker-authored checks must not run unsandboxed on the dispatcher host.
- Exact-SHA review verdicts do not transfer to successor SHAs.
- Never baseline a secret-looking value unless provenance proves it was synthetic/never live.
- Separate subject defects from verifier/environment defects.
- Production service paths `/opt/crooks-interactive` and `/opt/crooks-os` must not be changed by ordinary engineering objectives.
- GitHub is transport/projection only; canonical lifecycle truth remains the engineering store/kernel.

The unrestricted prose-freeze/parser loop remains PARKED unless George explicitly reopens it.

## 4. Engineering host layout

Host: `crooks-os-prod-1`

Engineering-only paths:
- source: `/srv/clive-engineering/src`
- store: `/srv/clive-engineering/state/engineering`
- repo: `/srv/clive-engineering/repo`
- runtime: `/srv/clive-engineering/runtime`
- workers: `/srv/clive-engineering/workers`
- integration: `/srv/clive-engineering/integration`
- Python venv: `/home/user/clive/crooks-assistant/.venv`
- Claude CLI: `/usr/local/bin/claude`

Host credential file paths only:
- OpenAI reviewer key: `/root/.config/clive-engineering/openai_api_key`
- Claude OAuth token: `/root/.config/clive-engineering/claude_oauth_token`

Do not print credential values.

## 5. Frozen engineering kernel / dispatcher

Frozen lifecycle kernel exact SHA:

`18c3153a2eec10c6343153b550776afed3bec2ba`

Main dispatcher implementation branch:

`claude/objective-intake-dispatcher-v1-uz8g7z`

Current dispatcher exact SHA:

`c566a955903a3a02e4a9ec97f0bab5a62e703fcd`

Important implemented behavior:
- multiple objectives;
- isolated worker workspace/home/session;
- detached Claude subprocess;
- bounded parallel builders;
- namespace/chroot/no-network checks;
- exact-SHA GPT reviewer using OpenAI Responses API, `gpt-5.6-sol`, high effort, `store:false`;
- deterministic integration path;
- bounded repair;
- worker OAuth injected into clean worker environment;
- no production deployment capability.

The dispatcher exits when all objectives are terminal; that is expected.

## 6. Completed self-engineering objectives

### Unified Derived Truth + Attention Semantics V1
Accepted/integrated exact SHA:

`cc5b6751fcff91f7ae34252c05da38560fc066e2`

Branch:

`clive/objective/derived-truth-attention-v1`

### Engineering Team Activation V1
Accepted/integrated exact SHA:

`e41e80b4153c5bca7e245b50e6ab7f899d6dd1ad`

Branch:

`clive/objective/engineering-team-activation-v1`

### Mobile dogfood voice wording
Accepted/integrated exact SHA:

`2bd139577a3d5505c4ef221184636dfe27647e31`

Branch:

`clive/objective/mobile-dogfood-voice-v1`

These were accepted under the dispatcher's narrower declared-check evidence model. Repository-wide CI later exposed that dispatcher COMPLETE and full GitHub acceptance were not yet equivalent.

That mismatch is a real architecture issue still to fix.

## 7. Product operational alpha

Product release branch:

`clive/release/operational-alpha-2026-09-23`

Exact SHA:

`f7be86f7f4676ca86de9a7ef18bac2342f29f62d`

This candidate is immutable failed evidence.

Focused tests passed, but full acceptance failed. Earlier GitHub evidence showed:
- control-plane checks green;
- repository full suite failures;
- secret-scan issue at the time.

Do not deploy this SHA.

Later investigation indicated the secret-shaped fixture was synthetic-looking, but never treat that as permission to baseline a credential-shaped value without proven provenance.

Operational-alpha repair remains backlog after Remote Engineering Control is activated.

## 8. Remote Engineering Control V1 — history

Spec branch:

`chatgpt/remote-engineering-control-v1-spec-2026-09-23`

Spec commit:

`d00267d7f5f96fa8515869f1a2be71073d74696a`

Purpose:
- bounded GitHub inbox;
- repository-only objectives;
- reuse existing Objective intake / Dispatcher / lifecycle records;
- no second source of truth;
- no arbitrary shell;
- no owner-gate bypass;
- no deploy/runtime/secrets/business-write authority.

### Initial worker candidate

`f496bf61f79a7fdf1bb049945e622e882d76e75e`

Focused suite failed 7 tests. Root causes:
- valid request IDs in tests were only 2 characters while canonical Objective IDs require minimum 3;
- rejected Pydantic values could echo credential-like input into refusal text;
- resulting intake failures cascaded into replay/status/idempotency tests.

### Repair 1 preserved commit

`a15f87edb1dba6d3c654c0399dfd62c9e2398b27`

Preserved changes in:
- `app/remote_engineering/controller.py`
- `app/remote_engineering/errors.py`
- `app/remote_engineering/requests.py`

Owner decision:
- preserve canonical Objective ID minimum length of 3;
- do not weaken `app/orchestrator/objectives.py`;
- fix invalid test fixture IDs instead.

### Repair 2 accepted by dispatcher

Branch:

`clive/objective/remote-engineering-control-v1-repair-2`

Exact SHA:

`6c300c5f9a349bf2da397ecd2ac7a263849dbc60`

This passed its declared Remote Engineering tests + ruff + exact-SHA GPT review under the dispatcher.

Full GitHub acceptance still failed at this exact SHA because:
- `REMOTE_ENGINEERING_CONTROL_V1.md` was not indexed from product-memory README;
- full offline suite showed 2 failures in that run.

### CI repair successor

Branch:

`chatgpt/remote-engineering-control-v1-ci-repair-2026-09-23`

Exact SHA:

`2426923baf2f419a08aadfb4cde156e364ee591a`

Change from `6c300c5f...`:
- only product-memory README index entry for `REMOTE_ENGINEERING_CONTROL_V1.md`.

First full CI run on `2426923b...` had one intermittent full-suite failure.

A separate diagnostic branch was used to improve failure visibility; that diagnostic branch passed.

Then the unchanged exact candidate `2426923b...` was rerun and passed full GitHub acceptance:
- `3208 passed`
- `14 skipped`
- `2 deselected`
- control plane: `44 passed`
- product-memory structure: PASS
- secret scan: PASS / no leaks found
- mechanical evidence: complete
- `eligible_for_acceptance_decision: true`

Important: the exact-SHA GPT review from `6c300c5f...` does NOT transfer to `2426923b...`.

As of this handoff, `2426923b...` is mechanically green but still needs a fresh independent exact-SHA review before it may be treated as accepted.

## 9. Owner activation authority

George explicitly wrote:

> authorise activation

This is owner authorization to activate Remote Engineering Control once the candidate has satisfied the required evidence/review gates.

Do not interpret this as permission to bypass exact-SHA review or activate an unreviewed successor.

No host activation has happened yet.

## 10. Activation-readiness branch — CURRENT WORK

Branch:

`chatgpt/remote-engineering-control-v1-activation-readiness-2026-09-24`

Current exact SHA:

`5fc4aa9457a13eb7a17dd39d71b00dca74fc6c96`

It is 5 commits ahead of mechanically-green `2426923b...`.

Commits:
1. `cf8cd69b...` — bounded GitHub status projection publisher
2. `d8481acb...` — intake → dispatcher tick → status projection cycle
3. `d54f6011...` — exports for loop/publisher
4. `328f53f5...` — long-lived `remote_engineering.py run` control loop
5. `5fc4aa94...` — tests for dispatcher loop and GitHub status projection

Files changed relative to `2426923b...`:
- modified `crooks-assistant/app/remote_engineering/__init__.py`
- added `crooks-assistant/app/remote_engineering/publisher.py`
- added `crooks-assistant/app/remote_engineering/runner.py`
- modified `crooks-assistant/scripts/remote_engineering.py`
- modified `crooks-assistant/tests/test_remote_engineering.py`

Intended behavior:
- poll bounded inbox branch;
- intake via canonical Objective path;
- call existing Dispatcher `tick()`;
- publish read-only status projection to bounded Git ref;
- repeat on interval;
- still no deploy/business-write/owner-gate authority.

GitHub acceptance run for exact SHA `5fc4aa94...`:

Run ID: `35933767452`

Status: CANCELLED.

Therefore this activation-readiness SHA is NOT accepted, NOT fully verified, and must NOT be activated.

Do not assume the cancellation was a code failure; inspect the run before deciding.

## 11. Handoff branch

This handoff itself lives on:

`chatgpt/opus-5-5-handoff-2026-09-24`

It is based on current activation-readiness SHA `5fc4aa94...` and contains handoff documentation only.

Do not treat the handoff commit as an engineering candidate.

## 12. What Opus should do next

Priority order:

1. Read this document and inspect the exact branches/SHAs above.
2. Inspect the cancelled CI run `35933767452` for `5fc4aa94...`.
3. Review the activation-readiness diff carefully against the Remote Engineering Control V1 spec and safety invariants.
4. Fix any defects on a successor SHA if required; do not rewrite failed/unreviewed SHAs.
5. Run focused Remote Engineering tests and repository-wide exact-SHA acceptance.
6. Require full mechanical evidence to be green.
7. Obtain independent GPT exact-SHA review for the exact activation candidate.
8. Only then use George's existing owner authorization to activate the bounded remote engineering loop on the engineering host.
9. Activation must not touch production application services or production checkouts.
10. After activation, prove the no-courier path with one real repository-only objective.
11. First useful post-activation engineering target: repair the failed operational-alpha line `f7be86f7...` into a new successor candidate with full CI + exact-SHA independent review.
12. Then address the wider governance gaps:
   - make full repository acceptance mandatory for dispatcher COMPLETE/acceptance;
   - publish lifecycle/journal evidence reliably;
   - expand protected paths to include product safety core and acceptance machinery;
   - route owner decisions into the Judgment Ledger;
   - reconcile dispatcher line `c566a955...` with accepted Engineering Team Activation `e41e80b4...`;
   - implement the real GPT Director runtime above the dispatcher.

## 13. Important architecture gap still open

The runtime GPT Director is still not implemented.

Current GPT capability is an exact-SHA independent reviewer, not the full Director.

Missing Director responsibilities:
- receive broad owner engineering objective;
- decide single coherent task vs decomposition;
- create dependency graph;
- choose specialists by capability/risk;
- reconcile several accepted candidates;
- maintain programme continuity;
- decide whether the broad release objective has actually been satisfied.

Implement this above the working dispatcher. Do not redesign the frozen lifecycle kernel to fake it.

## 14. Known lineage split

Do not merge all work into one mega-branch.

Product / operational alpha lineage:
- mobile alpha
- Derived Truth
- Mobile Dogfood wording
- operational alpha release

Engineering control-plane lineage:
- dispatcher `c566a955...`
- Engineering Team Activation `e41e80b4...`
- Remote Engineering Control

They have separate proof/deployment responsibilities and should be reconciled deliberately.

## 15. First instruction to the new Opus chat

Continue from repository evidence, not conversational assumptions.

Do not claim something is running, reviewed, accepted, deployed, or activated unless exact repository/CI/kernel evidence proves it.

Do not ask George to repeat information already present here or in Git.

