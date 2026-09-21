# CHATGPT INBOX

## Bounded repair — M-06 quantified adjective false-green

Repair exactly one bounded evaluator defect on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, currently exact HEAD `7f92215f0fc1a44f0865af316ce0f02780345417`. Resolve the remote branch identity yourself and STOP without changes if HEAD differs.

### Independent review finding M-06

The M-05 semantic-cardinality repair still has a reproducible false-green family in `_asserted_group_count`.

`_SINGULAR_QUANTIFIERS` contains ordinary noun modifiers including `new` and `existing`, and `_asserted_group_count` walks leftward from the group noun and immediately returns `1` when it encounters one of them. This can hide an explicit cardinal that appears immediately before the modifier.

Concrete mutation to reproduce against the normative one-group §3A row:

- `two new process groups are created`

For the `process groups` noun, the reverse walk sees `new` before `two` and returns `1`; the explicit `two` is never read. The declared group cardinality remains one, so this contradictory second-group semantics can be accepted. Adjacent forms to test include `three existing process groups are created`, `two new groups are provisioned`, and combinations where a true singular determiner/ordinal must still remain singular.

This is a material false green, not a stylistic concern. Call it **M-06**.

### Repair scope

Make the smallest test/evaluator-module-only repair needed so explicit cardinals governing the same noun phrase outrank non-cardinal modifiers such as `new`/`existing`, without causing quantifiers from neighbouring phrases to leak across constituent boundaries. Preserve fail-closed behavior for genuinely ambiguous plurality. Do not modify normative freeze/product-memory documents.

Add adversarial regression/mutation evidence proving at minimum:
- `two new process groups are created` fails the one-group invariant;
- `three existing process groups are created` fails;
- ordinary singular forms that genuinely assert one still pass;
- neighbouring-clause/phrase numbers do not get stolen;
- prior M-01..M-05, L-01, K-01, J-01, H-03/H-04 and R-02 protections remain intact.

Attack the repair yourself for adjacent adjective/quantifier ordering before handoff. Run the relevant freeze suite, static checks and secret scan available in the isolated repository context. Require clean worktree and exact resulting SHA evidence.

Do not self-certify the resulting candidate. Return a repair handoff only. A fresh independent reviewer that did not author the repair must review the resulting exact SHA before any acceptance can count.

Hard boundaries remain: repository-only isolated repair; no production/runtime/systemd/watcher changes, no secrets/credential reads, no connectors/MCP changes, no privilege expansion, no business writes, no deployment, no sequencing amendment, no owner-only adoption/merge/Phase0 authority.