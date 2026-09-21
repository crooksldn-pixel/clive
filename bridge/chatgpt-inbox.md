# CHATGPT INBOX

## Bounded repair — M-07 coordinated noun cardinality false-green

Repair exactly one bounded evaluator defect on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, currently exact HEAD `450cc524e4da1397b44df022ac6e2fa546edd13d`. Resolve the remote branch identity yourself and STOP without changes if HEAD differs.

### Independent review finding M-07

Fresh ChatGPT source review of exact `450cc524e4da1397b44df022ac6e2fa546edd13d` found a material false-green in `group_creations`.

The function computes `_asserted_group_count` for every live group noun in one creation verb's segment, then uses `max(counts)`. `max` is fail-closed only when the nouns are alternate descriptions of the same created object(s). It under-counts when one creation predicate coordinates multiple additive noun phrases.

Concrete mutation to reproduce by rewriting the one normative §3A clause that legitimately creates the attempt group, without adding another creation verb or transition row:

- `one process group and another group are created`

There is one creation verb. The first noun phrase asserts 1; `another group` asserts 1. `max([1, 1]) == 1`, so the asserted group cardinality can remain equal to the normative declaration of one even though the sentence semantically creates two groups.

Also attack quantified variants such as:
- `two process groups and another group are created` (semantic total 3, current max can report 2);
- `a process group and a further group are created`;
- active-voice equivalents where one creation verb governs coordinated objects.

Call this **M-07**.

### Repair scope

Make the smallest test/evaluator-module-only repair needed to distinguish additive coordinated created-group noun phrases from multiple references/descriptions of the same created group. Do not blindly replace `max` with `sum`: prove that the new derivation does not double-count aliases/appositives or unrelated group nouns sharing a segment. If semantic cardinality cannot be established safely, fail closed rather than assume one.

Add adversarial regression/mutation evidence proving at minimum:
- `one process group and another group are created` fails the one-group invariant;
- `two process groups and another group are created` cannot be under-counted;
- ordinary normative singular creation remains green;
- same-entity/appositive or otherwise non-additive noun mentions are not spuriously summed;
- prior M-01..M-06, L-01, K-01, J-01, H-03/H-04 and R-02 protections remain intact.

Attack the repair yourself with coordinated subjects/objects, conjunctions/disjunctions, appositives, and active/passive voice. Run the relevant freeze suite, static checks and secret scan available in the isolated repository context. Require clean worktree and exact resulting SHA evidence.

Do not modify normative freeze/product-memory documents. Do not self-certify the resulting candidate. Return a repair handoff only. A fresh independent reviewer that did not author the repair must review the resulting exact SHA before any acceptance can count.

Hard boundaries remain: repository-only isolated repair; no production/runtime/systemd/watcher changes, no secrets/credential reads, no connectors/MCP changes, no privilege expansion, no business writes, no deployment, no sequencing amendment, no owner-only adoption/merge/Phase0 authority.