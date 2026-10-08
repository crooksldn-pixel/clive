# CLIVE recovery handoff — 22 September 2026

An independent audit of what CLIVE engineering was actually doing, and the state
control is handed back in. Machine-readable companion:
`docs/handoff/recovery-handoff-2026-09-22.json`. Reviewer identities:
`config/review_principals.json`.

Nothing in this document is taken from a status report. Every claim below was
read off the running system or the GitHub API.

## The finding

**There is no autonomous engineering loop, and there never was one.** Branch
existence was being read as worker execution, and so was session existence.

Three things looked like work in progress and were not:

- `crooks-bridge-watcher.service` reports `active (running)` and has for two
  days. It is edge-triggered on the blob SHA of `bridge/chatgpt-inbox.md` and
  runs an agent **once** per inbox change, generating no successor task — by
  design, since watching HEAD would self-trigger forever. Last dispatch
  07:16:51Z, last completion 07:58:53Z, nothing since. Healthy, and with
  nothing to do.
- The V0.5 "parallel worker" is an interactive agent in a tmux pane. Its
  transcript's last entry is **2026-09-21T12:58:35Z**. A terminal agent does one
  turn per human message; it finished its turn and has waited ~29 hours.
- The control-plane reviewer "worker" is a bash prompt with **0.00 seconds of
  CPU**. No agent was ever launched in it.

The control plane that would fix this has never executed. `app/orchestrator/` is
library code on an unmerged branch — not imported by `app/main.py`, absent from
production entirely. `TaskRuntimeState`, leases, heartbeats and `owner_gate`
exist as models with no producer bound to reality. There are no runtime tasks,
locks or leases on this host; the only real runtime state is four small files in
`/var/lib/crooks-bridge`.

The "session died when Termius closed" hypothesis is **wrong**. tmux kept both
sessions alive. They did not die; they went idle and nothing woke them.

## The part that was moving, and going red

The GPT principal has been committing hourly to
`claude/ci-provenance-acceptance-2026-09-22` — nine commits on 22 September, one
file each, pure additions. Despite the `claude/` prefix, that work is GPT's.

**CI has been failing since 10:44Z.** Runs at 07:54 and 09:42 passed; the eight
after it failed, and commits continued through all of them. The acceptance gates
built at `3640c54a` are working exactly as designed and catching real breakage.
Nothing was reading them.

## The three failing gates

Reproduced locally at `100b8998`. Exact fixes, and which are safe:

| Gate | Failure | Fix | Safe repo-only? |
| --- | --- | --- | --- |
| `ruff` | 7 × `I001`, un-sorted imports, all in this stream's own files | `ruff check --fix app config scripts tests` | **Yes — mechanical** |
| `product_memory_structure` | `JUDGMENT_LEDGER_CONTRACT.md is not linked from README.md` | one index line in `docs/product-memory/README.md` | **Yes — mechanical** |
| `pytest_offline_full` | exit 2, 2 collection errors, suite never runs | implement two absent APIs — see below | **No** |

The third is not a lint problem. Two tests were written against APIs that have
never existed on this branch:

- `tests/test_judgment.py` imports `ReasonCode` from `app.actions.judgment`,
  which exposes only `OwnerDecision`, `JudgmentValidationError`,
  `OwnerProvenance` and `JudgmentRecord`. The test needs at least
  `ReasonCode.ACCEPTED_AS_PROPOSED`.
- `tests/test_review_result_gate.py` imports
  `app.orchestrator.reviewer_routing`, which does not exist. **This is not a
  rename**: the real reviewer-routing module is `app/orchestrator/routing.py`
  and it does not contain `ReviewerProvenance` either.

That is the review-acceptance surface itself, and it must not be self-approved
by whoever writes it.

## Reviewer independence — preserved, not weakened

The rule in `app/orchestrator/routing.py` is unchanged. **GPT is recorded as the
independent reviewer principal**, which satisfies `SAME_PRINCIPAL` and
`SAME_SESSION` by being a genuinely different principal rather than by any
exemption. No member of the `Ineligibility` enum was removed or relaxed.

The remaining five reasons still apply in full to every GPT review:
`SAME_WORKSPACE`, `STALE_CONTEXT`, `CANDIDATE_SHA_DRIFT`,
`REVIEWER_WORKSPACE_IS_WRITABLE`, `REVIEWER_WORKSPACE_IS_DIRTY`,
`REVIEWER_NOT_AT_CANDIDATE`. Each review must be pinned to an exact 40-character
SHA, re-resolved at decision time, from a clean read-only workspace checked out
at that commit.

**The rule is symmetric.** GPT may not review GPT's own work — which bites
immediately, since `100b8998` is GPT-authored. It has no eligible reviewer today
and is red besides.

## V0.5 — where it actually is

The implementation is on `claude/v05-parallel-worker-20260921` at `33968c92`:
**+2409/−50 across 23 files** against `ff7e2279`, including `web/live-state.js`
(336 lines), `web/jobs.js` (222), and +172 to `app.js`. Slices A, B, C and E are
done; D is partial.

`ff7e2279` — the branch that was being watched — is **+169/−41 across 4 files**:
the contract document, a 39-line contract test, and the Split-retirement rebrand.
It is the contract plus slice A's first pass, not a nearly-complete V0.5.

**Why no visible change: nothing has ever been deployed.** Production serves
`/opt/crooks-os/crooks-assistant` at `1cf3a0f3`, committed **18 September
21:38Z**, before any V0.5 work existed. `web/live-state.js` and `web/jobs.js`
are absent from the production checkout.

The five open questions, classified — three of them should never have reached
the owner as product decisions:

| # | Question | Class |
| --- | --- | --- |
| 1 | Per-job retry endpoint | `SAFE_ENGINEERING_DECISION` |
| 2 | Partial speech recogniser | `OWNER_PRODUCT_DECISION` — privacy, not engineering |
| 3 | CLIVE vs CROOKS OS naming | `OWNER_PRODUCT_DECISION` |
| 4 | No browser/device evidence possible | `ENVIRONMENT_INFRASTRUCTURE_GATE` |
| 5 | `test_no_terminal.py` red pre-existing | `SAFE_ENGINEERING_DECISION` |

Item 2 is the owner's only because on-device recognition sends the owner's
speech to a third-party browser speech service. The wiring either way is a
one-line change; the privacy question is not.

Item 4 is a missing dependency — `/opt/pw-browsers` does not exist — not a
decision.

## Secret scan — inspected, nothing changed

Five findings, all rule `generic-api-key`, all in `tests/`, none in application
code or configuration. Inspected for location and usage only; **no candidate
value was printed, transmitted or recorded, and nothing was baselined or
rotated.**

| Path | Line | Pattern |
| --- | --- | --- |
| `tests/test_observability_redaction.py` | 279 | `authorization=` / `args={'token': …}` into `emit()`, then asserts redaction |
| `tests/test_observability.py` | 81 | header value into `emit()` in a session named `scrub` |
| `tests/test_scribe.py` | 24 | module `SECRET`, injected, then asserted **absent** from the request body |
| `tests/test_scribe.py` | 448 | inline `client._key = …` |
| `tests/test_tts.py` | 20 | module `SECRET`, commented "the Keychain is never read in a test" |

All five read as deliberate fixtures: the string exists so a negative assertion
can prove it does not leak. **The assessment is structural, not cryptographic** —
gitleaks flags on entropy and cannot tell a synthetic string from a real key.
The one thing structure cannot rule out is a fixture originally copied from a
live ElevenLabs key. Only the owner knows that, and if so it must be rotated at
the provider rather than baselined.

## Deployment handoff — prepared, not executed

Nothing was deployed. Preconditions, in order:

1. Independent GPT review of `33968c92` at that exact SHA
2. An acceptance run against `33968c92` — it has never been run against CI
3. Owner answers to V0.5 questions 2 and 3
4. Explicit owner authorisation to deploy

When authorised: record `1cf3a0f3` as the rollback target, check out `33968c92`
in the production checkout, restart `crooks-assistant.service`, confirm
`web/live-state.js` and `web/jobs.js` are served, and on failure return to
`1cf3a0f3`.

One caveat: a rollback leaves the checkout detached, and from that state CROOKS
Control can neither mark-good nor update (V0.5 open item 5). Rolling back is
safe; recovering forward from a rollback currently needs a person at a shell.

## What this handoff did not touch

No systemd, watcher or runtime configuration. No production deployment. No
secrets read, exposed, baselined or rotated. No permissions, no external
services, no spend. No commits to the failing CI stream. `a8005721` is unchanged.
The parked prose-freeze/parser loop was not restarted.
