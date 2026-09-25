# CROOKS OS — Director Memory Protocol

**Purpose:** deterministic memory/recollection protocol for GPT Director, Claude managers, future orchestrators and human maintainers  
**Status:** ACTIVE  
**Last consolidated:** 2026-09-19

This file defines named memory operations. They are currently procedures, not magic commands. Future CROOKS tooling may expose them as first-class commands.

The goal is high continuity **without context accumulation becoming architectural gravity**.

## Command: BOOTSTRAP

Use at the start of a meaningful engineering/product round.

Read in this order:

1. `docs/product-memory/CURRENT_TRUTH.md`
2. `docs/product-memory/PRODUCT_BRAIN.md`
3. `docs/product-memory/EVOLUTION_POLICY.md`
4. active/relevant entries in `DECISIONS.md`
5. assigned feature/issue/roadmap item
6. `SELF_IMPROVEMENT.md` when autonomy, agents, deployment or self-modification are involved
7. `DESIGN.md` for current UI/product work, when present
8. latest relevant handoff/evidence

Do not load all Git history by default.

## Command: RELEASE_CONTEXT

Before planning a substantial new version, build a compact Active Context Pack.

Classify every potentially relevant constraint as one of:

- **ACTIVE INTENT**
- **SAFETY CONTRACT**
- **CURRENT PRODUCT CONTRACT**
- **MIGRATION OBLIGATION**
- **EVIDENCE**
- **HISTORICAL**
- **SUPERSEDED**
- **UNKNOWN / VERIFY**

Only the first five normally constrain implementation.

Historical/superseded material may explain decisions but must not silently become requirements.

Explicitly ask:

- what must survive?
- what may disappear?
- what can be simplified?
- what would we build today if no obsolete implementation existed?

## Command: CAPTURE

When the owner expresses a meaningful idea that is not yet implementation approval:

1. add/update `IDEAS.md`,
2. record date/context,
3. mark CAPTURED,
4. do not silently build it.

## Command: DECIDE

When the owner explicitly establishes product/architecture direction:

1. add/update `DECISIONS.md`,
2. record rationale,
3. update PRODUCT_BRAIN/ROADMAP when the decision changes durable direction,
4. update CURRENT_TRUTH if it changes active state.

## Command: SUPERSEDE

When a new direction replaces an old one:

1. identify old decision/design/component,
2. identify replacement,
3. record preserved outcomes,
4. record intentionally dropped behaviour,
5. mark old item SUPERSEDED/RETIRED,
6. update current docs/tests,
7. remove obsolete runtime code when migration permits,
8. keep history in Git.

Never keep both systems indefinitely simply to avoid deleting history.

## Command: PRUNE

Periodically reduce active-context noise.

Candidates:

- completed temporary migration notes,
- superseded design direction,
- stale implementation detail,
- dead compatibility instructions,
- old model/version assumptions,
- duplicate ideas,
- resolved transient blockers.

Pruning means removing them from **active context**, not falsifying history.

Git remains the archive.

## Command: HANDOFF

At the end of a meaningful engineering round, record only what the next round needs:

- objective,
- exact branch/commit/artifact,
- what changed,
- tests/evidence,
- unresolved blockers,
- approvals required,
- current runtime/deployment state,
- next recommended action.

Never include secret values.

If active system truth changed, update CURRENT_TRUTH.md.

## Command: REVIEW_CURRENTNESS

Before rejecting a new architecture because it differs from old behaviour:

1. locate the supposed constraint,
2. determine whether it is ACTIVE or merely historical,
3. identify the underlying outcome it protected,
4. decide whether the new design preserves that outcome in a better way,
5. if the old constraint is obsolete, supersede it explicitly.

This is the anti-ossification check.

## Command: QUALITY_GATE

For substantive engineering work:

- use the strongest appropriate intelligence,
- do not reduce code/product quality for cost or speed,
- require objective evidence,
- require independent review for material changes,
- escalate difficult/ambiguous work to stronger reasoning,
- do not treat a worker's own confidence as proof.

## Command: INFRA_CHANGE

For watcher/orchestrator/deployment/action-broker/systemd/privileged infrastructure:

candidate
→ deterministic tests
→ security review
→ independent review
→ exact artifact/version
→ owner approval when required
→ privileged installer/controller
→ health verification
→ rollback on failure
→ update CURRENT_TRUTH

The component being updated must not be its own sole approver.

## Command: MEMORY_AUDIT

Periodically check:

- Does CURRENT_TRUTH match reality?
- Are active decisions still active?
- Are any superseded decisions still being injected into prompts?
- Does ROADMAP reflect actual sequencing?
- Are temporary decisions still marked temporary?
- Are compatibility layers missing deletion criteria?
- Are completed items still marked BUILDING?
- Is product memory becoming transcript-like rather than decision-like?

Fix drift in product memory as part of normal engineering hygiene.

## Future executable forms

When the Engineering Orchestrator exists, these procedures may become deterministic operations such as:

- `crooks memory bootstrap`
- `crooks memory release-context <task>`
- `crooks memory capture`
- `crooks memory supersede <old> <new>`
- `crooks memory audit`
- `crooks memory handoff`

Those commands should generate/read structured context from Git-backed product memory. They should not invent truth or automatically promote brainstorming into approved decisions.
