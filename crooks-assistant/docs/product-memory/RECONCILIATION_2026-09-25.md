# Reconciliation - 2026-09-25

**Status:** the Director's reconciliation of the repository, the loops and product memory at `clive/trunk` `e847a2cb` (evening of 2026-09-25), checked against GitHub. Nothing was deleted or closed; every clean-up below is a proposal for the owner.

## 1. The trunk

Landed today, each on a green GitHub acceptance run on the exact SHA:

| PR | What |
|---|---|
| #12 | Trunk repair: the PWA test follows the microphone fix, the voice-credits fixture key is assembled at runtime, the tool matrix regenerated |
| #13 | Product memory for 2026-09-25: owner decisions, the self-knowledge doctrine, the next phase and captured ideas, infrastructure, the external review |
| #14 | Product-memory consolidation: both staged branches folded into the canonical files, stale records corrected |
| #15-#17 | Host-neutral owner-facing wording; Generative UI 2a (renderer and preview page) and 3a (a validated scene for every turn, behind `CLIVE_SCENES`, off by default) |

Earlier on the trunk (PRs #3-#11): the age-days floor, the judgment-ledger CI stream, needs-reply routing, the journal-safe loop repair, the microphone fix, the honest voice-credits message, Generative UI 1 and the memory staging.

Production still runs `ce791d03`. Everything from PR #5 onwards is on the trunk but not deployed. Deploying the trunk head needs its own exact-SHA review and the owner-gated deploy step.

## 2. Objectives across the loops

48 requests have been submitted to the two live loops (production host and clive-worker-01); the Mac loop is not live.

- **Completed and landed (13):** international-waiting-clock, operational-alpha-acceptance-repair-4, needs-reply-routing-3, remote-engineering-journal-safe-2, microphone-prompt-fix-3, voice-credits-honest-3, generative-ui-v1-evidence-scenes-4, generative-ui-v1-scene-renderer-2, generative-ui-v1-scene-planner, owner-facing-host-wording-6, trunk-repair-ci-2, product-memory-consolidation-4, and (through the Director's own branches) the memory records.
- **Completed, not landed (1):** clive-engineering-bridge-5 (Build from CLIVE 1, `a7f593c4`). It conflicts with the trunk only in the generated tool matrix, and needs two small fixes where it meets the wording change (words for its two tools in `web/app.js`, and "on the tablet" in its tool description). A session with a shell does it in one pass; the prompt is ready.
- **Running (1):** generative-ui-v1-settings-chrome-3, with the owner's microphone decision answering its open finding.
- **Blocked and superseded by a completed successor:** every earlier attempt at the objectives above (bridge 1-4, evidence-scenes 1-3, microphone 1-2, needs-reply 1-2, wording 1-5, voice-credits 1-2, journal-safe 1, consolidation 1-3, trunk-repair 1, settings 1-2, operational-alpha 1-3 including the OWNER_GATE on repair-3). Nothing in them is lost: each successor carried the work forward.
- **Blocked and still open (3):**
  - `uk-midnight-clock-sweep-2`: needs a shell to run the suite across midnight; the sweep is being run by hand on clive-worker-01, and its result turns into a precise fix.
  - `status-publishes-findings`: loop code, now protected; belongs in an owner-gated loop update.
  - `remote-engineering-review-findings-2`: three findings from the exact-SHA review of the loop pin `4c32bb3d`. The journalled-store defect was fixed by journal-safe-2 (PR #7); the other two need checking against the trunk, and they are loop code, so they go through the owner-gated route.

## 3. Branches

110 branches on GitHub; 40 are contained in the trunk.

### 3.1 Keep
- Control: `clive/control/owner-inbox`, `status`, `worker-01-inbox`, `worker-01-status` (the Mac's appear when it goes live).
- Evidence and audit: `clive/evidence/*`, `clive/engineering-state`, `crooks-ai-bridge` (the retired bridge's record).
- The storefront and other projects, which are not CLIVE and seed the theme project (NEXT_PHASE_2026-09-25.md section 3.1): `claude/crooksldn-theme-init-*`, the theme-gauntlet and behavioural and site audits, `experiment/flatlay-evidence-window`, `claude/order-confirmation-email-*`, `claude/sample-room-sync-testing-*`, `claude/shopify-theme-*`, and the Instagram skills on `claude/sleepy-cerf-*`.

### 3.2 Knowledge that exists only on unmerged branches
These documents are not in the trunk. Under the self-knowledge doctrine they should be, as history, verbatim:

| Branch | Documents |
|---|---|
| `chatgpt/ops-memory-2026-09-19` (open PR #2) | `docs/product-memory/OPS_RUNBOOK.md`: the 2026-09-19 recovery runbook |
| `claude/recovery-handoff-2026-09-22` | `docs/RECOVERY_HANDOFF_2026-09-22.md` and two handoff JSON files |
| `chatgpt/capability-registry-reconciliation-2026-09-22` | `docs/product-memory/ENGINEERING_CAPABILITY_REGISTRY.md` |
| `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | the Orchestrator V1 acceptance matrix, freeze contract, state API, traceability and watcher-identity remediation documents |
| `claude/builder-environment-review`, `-repair-review`, `claude/harness-hooks-experiment` | `DESIGN.md`, `docs/DEV_ENVIRONMENT.md`, `docs/dev-environment/*` including CONTRACT_TRIAL_ENV_REPRO_001 |
| `claude/mobile-experience-v1-review` | `docs/MOBILE_EXPERIENCE_V1.md` and its phone screenshots |

Proposal: one shell session copies each file unchanged into `crooks-assistant/docs/history/` under its branch's date, with an index naming the source branch and commit, and lands it like any other change. For each branch: `git checkout origin/<branch> -- <files>`, then move them under `docs/history/`.

### 3.3 Code that exists only on unmerged branches (owner decision)
- `chatgpt/control-plane-progress-v1` (2026-09-21): an orchestrator progress reporter and supervision module. The loop's status projection now covers progress; proposal: record as superseded.
- `claude/compassionate-johnson-*` (2026-09-13): the Phase 6 CROOKS Control redesign in Swift, never merged. It belongs with the Mac's Swift role; proposal: keep until the Mac loop is live, then decide.

### 3.4 Superseded, proposed for deletion after the owner agrees
- Objective branches whose objective completed through a successor (section 2), and the successors' own branches once landed.
- Memory branches folded in by PR #14: `claude/product-memory-truth-2026-09-23` (and r2-r4), `claude/product-memory-2026-09-24`, `chatgpt/product-memory-reconcile-2026-09-23`, `chatgpt/memory-reconcile-2026-09-19` (after the runbook import), `claude/product-memory-foundation`.
- Superseded feature lineages: `claude/support-investigator-v1-2026-09-23` (and r2-r5), `chatgpt/bridge-fable-*`, the remote-engineering diagnostics branches, `claude/release-secret-baseline-2026-09-24` (superseded by OWNER_DECISIONS_2026-09-25).
- Director branches already landed: `claude/owner-decisions-2026-09-25`, `claude/landing-genui-wording-2026-09-25`.

Deleting a branch is reversible for about 90 days only through GitHub support, so the rule is: import any unique knowledge first (section 3.2), then delete.

## 4. Open pull requests
- #1 (draft, 2026-09-18): the first product-memory foundation, targeting the old baseline. Superseded by the trunk.
- #2 (2026-09-19): the operator runbook, targeting the foundation branch. Its one unique document is in section 3.2.

Proposal: close both once the runbook is imported.

## 5. Waiting on the owner
- Top up or upgrade the ElevenLabs plan (voice and transcription stopped since 2026-09-22).
- Make the repository private.
- The deploy of the trunk head.
- The two sudo steps on clive-worker-01: the builder check tool's review rule and its branch push.
- The Mac loop's three credentials.
- clive-worker-01: iLO password, the second power cable, array alerting and backups.
- Before more than about thirteen parallel builders: the Claude API or a Team plan.
- The branch and pull-request clean-up above.
