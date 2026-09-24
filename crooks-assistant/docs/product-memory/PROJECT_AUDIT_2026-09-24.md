# Project Audit - 2026-09-24

**Status:** evidence snapshot taken 2026-09-24 around 22:40 UTC from the repository, the kernel's `clive/engineering-state` records and the remote loop's status projection. It is a finish list, not a new plan: every line is either work that exists but has not landed, work that was agreed but not built, or a record that no longer matches reality.

## 1. The systemic finding

"Done" has never meant "in the product". The kernel and the remote loop both integrate an accepted objective onto its own branch (`clive/objective/<id>` or a named `claude/...` branch), and nothing moves accepted work into one trunk. The result on 2026-09-24:

- 81 branches and three live code lineages: production `ca388cee` (mobile alpha, 2026-09-23), the alpha candidate `0bbcfb69` (production plus six commits) and the engineering line `4c32bb3d` (the running loop).
- Eight objectives the kernel records as accepted and done sit on their own branches; most never reached production or the alpha.
- Product memory is split across at least six branches with conflicting statements of what is live.

The fix is structural: one trunk, and an objective is finished only when its work is in the trunk and the trunk passes acceptance.

## 2. What is live in production (`ca388cee`)

Mobile alpha (conversation, Objective V0 and the support investigator on the phone), Live Experience V0.5 (merged at `d9621337`), the Linux migration, control-plane vNext phase 1, and everything earlier on that line. Not live: derived truth and attention, the mobile dogfood voice rules, the judgment ledger CI stream, the support investigator's later revisions, the age-days floor fix, and everything built on the engineering line.

## 3. Finished but not landed

| Work | Where it sits | Evidence it is finished | Gap |
|---|---|---|---|
| Age-days floor (an order's age reported as whole days, never rounded up) | `claude/ci-age-days-floor-2026-09-22` `ef3d08ff` | kernel acceptance, done | not in production or alpha; this is the bug that blocked tonight's deploy |
| Support Investigator V1 revisions r2-r5 (S-01, S-01R, S-01C: dispatch and cancellation claims) | `claude/support-investigator-v1-2026-09-23` `2dbb97bc` | kernel acceptance, two real cases verified read-only | 14 commits (21 lines in app/support) not in production or alpha; owner verification and first live run outstanding |
| Judgment ledger CI stream and corrections | `claude/ci-stream-integration-judgment-2026-09-22` `b68e6e82`, `claude/clive-recovery-handoff-pwuuse` `1958b327` | kernel acceptance, done | not in production, alpha or engineering line |
| Agent Environment state view and truth repairs | `claude/agent-environment-clive-state-2026-09-22` `84e12e77` | kernel acceptance, done | engineering line only; not in the product |
| Derived truth and attention V1 | `clive/objective/derived-truth-attention-v1` `cc5b6751` | kernel integration | in the alpha candidate, not in production |
| Mobile dogfood voice V1 | `clive/objective/mobile-dogfood-voice-v1` | content identical in the alpha | in the alpha candidate, not in production |
| Operational alpha repair | `clive/objective/operational-alpha-acceptance-repair-4` `0bbcfb69` | loop COMPLETE, GPT ready | deploy blocked by the age-days bug above |
| Product memory truth PM-01 to PM-04 | `claude/product-memory-truth-2026-09-23` `07459b85` | kernel acceptance, done | never merged with the reconcile, handoff or 2026-09-24 memory branches |
| Remote engineering loop and objective dispatcher | engineering line `4c32bb3d` | live on the host | not in the product lineage; two codebases now drift |

## 4. Started and stopped

- `engineering-team-activation-v1`: blocked since 2026-09-23 because no eligible independent reviewer was available; superseded in practice by the remote loop, not formally closed.
- `remote-engineering-journal-safe`: blocked tonight after two failed attempts; the loop still depends on a host-local exclude line.
- Harness hooks experiment (`claude/harness-hooks-experiment`, accepted for next gate at `2c2b0cc`): never landed.
- Instagram agent skill pack (`claude/sleepy-cerf-k0f4zb`), Mac app Phase 6 follow-ups (`claude/compassionate-johnson-lzl6dd`), mobile experience measurement (`claude/mobile-experience-v1-review`), capability registry reconciliation (docs), orchestrator freeze candidate and control-plane progress (ChatGPT streams): unlanded; each needs a keep-or-retire decision.
- Bridge watcher: still installed and running on the host, and its loaded model differs from its reviewed source; the remote loop now does its job.
- `claude/release-secret-baseline-2026-09-24`: a competing fix for the alpha that fails acceptance; abandon.

## 5. Agreed but not built

Roadmap NOW items not delivered: N3 perfect the current UI (now Generative UI V1, objective 1 of 4 running), N4 response behaviour (the 2026-09-24 misreading of "customers who need a reply" is the live example), N5 real-world test sessions (the dogfood week), Samsung verification.

Approved ideas with no implementation yet: Event Ledger (IDEA-005), casual statement to monitored expectation (IDEA-006), anticipation engine (IDEA-008), natural-language automation (IDEA-010), earned autonomy (IDEA-011), model gateway (IDEA-012), selective push notifications (IDEA-017), long-running background jobs (IDEA-021), Nightly Observer (IDEA-022), reproduction from logs (IDEA-023), historical replay gate (IDEA-024), one business state across devices (IDEA-041), liquid-glass material (IDEA-058). Partly built: attention (IDEA-007, in the alpha), persistent objectives (IDEA-009, V0 live), scene compiler (IDEA-013 and IDEA-057, Generative UI running), judgment ledger (IDEA-059, built but unlanded).

Approved on 2026-09-24 and not yet done: Generative UI objectives 2 to 4, Build from CLIVE objective 2, capability-gap bridge, Source Assimilation V1, builders on Opus 5.5, the Mac as a second loop, making the repository private.

## 6. Records that no longer match reality

- FEATURES and CURRENT_TRUTH give production as `1cf3a0f3` (2026-09-19); it is `ca388cee`.
- FEAT-059 says V0.5 is not deployed; it is in production.
- Gmail OAuth is listed as outstanding; it was provisioned on 2026-09-24.
- FEAT-006 lists the Derek voice as shipped; it is unavailable on the server.
- Production text still refers to a Mac runtime.

## 7. Finish order

1. **In flight:** let the loop finish Build from CLIVE 1, Generative UI 1 and the time-of-day fix (land `ef3d08ff` if the job duplicates it); requeue journal-safe with its failure cause; switch builders to Opus 5.5.
2. **One trunk:** create a trunk from the alpha candidate; land, in order, the age-days floor, the support investigator revisions, the judgment ledger stream and corrections, the agent environment view, then the engineering line, each through acceptance; deploy the trunk; from then on every objective targets the trunk.
3. **One product memory:** consolidate the product-memory branches into the trunk and regenerate FEATURES and CURRENT_TRUTH from what is actually deployed.
4. **Close gates:** the support investigator live verification and the dogfood week, Samsung verification, retire the bridge watcher and close engineering-team-activation as superseded, keep-or-retire each section 4 stream.
5. **Build the agreed:** Generative UI 2 to 4, Build from CLIVE 2, response behaviour (interpretation), capability-gap bridge, expectations and deadlines, selective notifications, then the Nightly Observer and morning report. Every other approved idea gets an explicit place in the order rather than staying silently approved.
