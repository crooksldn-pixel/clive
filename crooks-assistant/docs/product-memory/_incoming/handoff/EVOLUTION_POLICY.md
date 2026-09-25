# CROOKS OS — Evolution Without Ossification

**Status:** canonical release/evolution doctrine  
**Owner intent:** ACTIVE  
**Last consolidated:** 2026-09-19

## 1. Core rule

> Previous versions are evidence and acceleration, not a prison.

A new CROOKS release should inherit everything that is still valuable: validated product intent, safety invariants, proven capabilities, useful data, hard-won lessons, tests that still represent desired behaviour, and architectural knowledge.

It must **not** inherit obsolete implementation shape merely because that shape existed before.

Continuity means preserving what matters. It does not mean preserving every component, screen, abstraction, test, workflow, or historical design choice forever.

## 2. Current truth outranks historical form

When deciding what a new release should do, use this order:

1. explicit current owner intent,
2. active safety/security invariants,
3. current validated product contracts and desired outcomes,
4. current product/design/engineering doctrine,
5. recent evidence from real use and tests,
6. historical rationale where relevant,
7. old implementation form.

Old implementation form is the weakest source.

A previous architecture is not automatically a requirement.

## 3. Preserve outcomes, not mechanisms

A capability should survive when its outcome is still valuable.

Its old mechanism does not have to survive.

Examples:

- If a new event system makes an older polling path unnecessary, the polling path may be removed.
- If a new World/Attention layer completely replaces an old intermediate abstraction, that abstraction may become null and be deleted.
- If a new interaction model makes an old panel redundant, preserving the old panel is not “continuity.”
- If a new model/tool path replaces an old one with better verified behaviour, compatibility code should exist only where there is a real migration need.

The question is:

> “What value or contract does this preserve?”

not:

> “How do we keep the old thing alive?”

## 4. Null is a valid end state

A component may legitimately become unnecessary.

The system must be allowed to conclude:

- this feature is redundant,
- this adapter no longer serves a purpose,
- this compatibility layer can be retired,
- this UI surface should disappear,
- this worker/agent role has been subsumed,
- this data field is no longer useful,
- this test protects behaviour we no longer want.

Deletion is a first-class engineering outcome when evidence shows there is no remaining unique responsibility.

Do not create permanent zombie architecture.

## 5. Supersession is explicit

When an active idea, decision, design direction, capability or architecture is replaced:

1. identify the replacement,
2. state what value/contract is preserved,
3. state what is intentionally dropped,
4. mark the old item **SUPERSEDED** or **RETIRED**,
5. update current truth and relevant tests/docs,
6. remove obsolete runtime/code/config when safe,
7. keep historical rationale in Git rather than injecting it into every future model context.

Superseded material remains searchable history, not active instruction.

## 6. Release context must be curated

Every substantial release should be reasoned from a compact **Active Context Pack**, not from an indiscriminate dump of project history.

The pack should contain:

- current product principles,
- active safety invariants,
- current architecture contracts,
- current design direction,
- current capabilities,
- current known constraints,
- active decisions,
- relevant current tests/evidence,
- explicit task/release objective,
- known migration obligations,
- relevant recent failures/lessons.

It should normally exclude:

- superseded UI direction,
- dead implementation detail,
- old temporary workarounds,
- resolved incidents,
- obsolete model/provider assumptions,
- historical features with no remaining contract.

Historical context is retrieved on demand when it explains a constraint, regression, migration, or previous failure.

## 7. Tests are evidence, not fossils

Tests are valuable when they guard behaviour CROOKS still intends to preserve.

A test must not force obsolete product behaviour to survive forever.

When product intent deliberately changes:

- update or remove the obsolete test,
- add tests for the new desired behaviour,
- preserve migration/security/regression coverage that still matters,
- record the reason for changing the contract.

Never weaken a test merely to make a candidate pass.

But equally, never keep a bad product purely because an old test encodes it.

## 8. UI and design may change direction

DESIGN.md represents the **current** product language, not an eternal aesthetic.

A future CROOKS version may take a materially different visual direction if the owner/product direction changes.

Preserve relevant usability and safety outcomes such as:

- legibility,
- touch reachability,
- accessibility,
- interaction clarity,
- performance,
- device constraints,
- approval semantics,
- speech/screen responsibilities.

Do not preserve an old colour, glass treatment, layout, animation language, card shape, navigation pattern or density simply because it once existed.

Old visual directions remain in Git history and design evidence.

## 9. Compatibility has a sunset

Compatibility layers are acceptable when they support a real migration.

Each substantial compatibility layer should have:

- reason,
- consumers,
- migration condition,
- deletion condition.

“Something used to depend on this” is not enough to keep it forever.

## 10. Simplicity can be a release improvement

A release may be better while containing less code, fewer abstractions, fewer controls or fewer agents.

Quality is measured by outcomes:

- correctness,
- security,
- reliability,
- usability,
- maintainability,
- performance,
- owner attention removed,
- evidence from real use.

Code volume and feature count are not quality metrics.

## 11. Review questions for every major release

Before finalising a substantial version, ask:

1. What current value/contracts must survive?
2. Which constraints are genuinely active?
3. Which constraints are only historical?
4. What can now be deleted?
5. What can be simplified?
6. Which old assumptions have new evidence disproved?
7. Are any tests guarding archaeology rather than current intent?
8. Are compatibility layers still serving real consumers?
9. Is the new design being distorted to resemble the old one unnecessarily?
10. If CROOKS were being designed today with current knowledge, what would we choose?

## 12. Git is the archive; active context is the working memory

Git preserves historical truth.

Product memory preserves durable intent and rationale.

CURRENT_TRUTH.md preserves the compact active state.

Future agents should not be forced to load the entire archive to work correctly.

The system should remember enough to avoid repeating mistakes while remaining free to become substantially better.

## 13. Incidents create lessons, not permanent mechanisms

When an operational failure exposes a real weakness, preserve the **lesson, invariant and evidence** rather than automatically preserving the exact workaround used that day.

A local exclusion, temporary branch convention, manual restart, one-off command, current model choice, watcher implementation, UI control or even an entire orchestration component may be the correct short-term mechanism and still be replaced later.

Record:
- what failed;
- why the safety/control system behaved as it did;
- what property the future system must preserve;
- what temporary workaround was used;
- what remains unproven.

Do not convert emergency choreography into architecture by repetition.

No current implementation mechanism is sacred. Active owner intent, safety invariants, desired outcomes and verified lessons survive; mechanisms remain open to better evidence and better designs.
