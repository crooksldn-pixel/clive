# CLIVE engineering state

The authoritative record of CLIVE's engineering lifecycle, written only by the kernel
(`crooks-assistant/scripts/engineering_kernel.py` on the code branches) and read by the
state projection. Every write is one commit authored by "CLIVE kernel" naming the operator.

`engineering/` holds the store: `tasks/`, `task-state/`, `attempts/`, `events/`, `results/`,
`reviews/`, `acceptances/`, `integrations/` and the regenerated `ACTIVE_STATE.json`. The
record contract is ENGINEERING_LIFECYCLE_PRODUCERS.md in product memory.

This branch carries no code. Do not merge it into a code branch; check it out beside one and
declare its `engineering/` directory as `engineering_store` in the agent roster.
