# CHATGPT INBOX

## Bounded repair — M-08 postmodified coordinated group cardinality false-green

Repair exactly one bounded evaluator defect on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, currently expected exact HEAD `f06730aa361bb6054ae47bfa284539772a062782`. Resolve the remote branch identity yourself and STOP without changes if HEAD differs.

### Independent review verdict on exact f06730a

`REJECT — REPAIR REQUIRED`.

Fresh independent source review finds M-07 remains materially reachable through a plausible coordinated-NP shape the repair itself disclosed but treated as an acceptable residual limit:

- `a process group for the attempt and a group for the reviewer are created`

Semantic cardinality is 2. The current `_coordination_between` only recognises additive coordination when the coordinator begins the text directly between adjacent group heads. The first conjunct's postmodifier (`for the attempt`) therefore makes the relation return non-additive and `_coordinated_group_count` falls back to the largest individual reading, 1. Rewriting the one legitimate §3A creation clause to this wording can therefore leave the declared one-group invariant green while the prose creates two groups.

This is material, not merely an imprecise red count: unlike the comma-separated disclosed case (which may undercount 3 as 2 but still fails the one-group invariant), this postmodified-first-conjunct case can undercount 2 as exactly 1 and false-green the gate.

Call this **M-08**.

### Repair scope

Make the smallest test/evaluator-module-only repair needed to recognise additive coordination when the first group conjunct carries a bounded postmodifier before the coordinator, without converting clause coordination, apposition, relative clauses, prepositional back-references, or unrelated nouns into additive group creation.

Do not blindly search for any later `and`. Establish structural evidence that the coordinator joins the two group noun phrases governed by the same creation predicate. If that cannot be established safely, fail closed rather than assume one.

Add adversarial mutation evidence proving at minimum:
- `a process group for the attempt and a group for the reviewer are created` fails the one-group invariant with semantic count 2;
- quantified variants such as `two process groups for the attempt and another group for the reviewer are created` cannot be under-counted;
- active-voice equivalents are covered;
- same-entity/appositive/prepositional references are not spuriously summed;
- `the controller creates a process group for the attempt and records the group for cleanup` does not become a two-group creation;
- ordinary singular normative creation remains green;
- comma-separated coordination remains red even if its exact total is conservatively undercounted;
- prior M-01..M-07, L-01, K-01, J-01, H-03/H-04 and R-02 protections remain intact.

Attack your repair with nested postmodifiers, multiple prepositional phrases, relative clauses, active/passive voice, conjunction/disjunction and elided heads. Run the relevant freeze suite, static checks and secret scan available in the isolated repository context. Require clean worktree and exact resulting SHA evidence.

Do not modify normative freeze/product-memory documents. Do not self-certify the resulting candidate. Return a repair handoff only. The resulting exact SHA still requires a fresh independent review by a party that did not author the repair.

Hard boundaries remain: repository-only isolated repair; no production/runtime/systemd/watcher changes, no secrets/credential reads, no connectors/MCP changes, no privilege expansion, no business writes, no deployment, no sequencing amendment, no owner-only adoption/merge/Phase0 authority.