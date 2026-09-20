# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze K-01

Perform exactly one bounded repository-only repair round on the existing freeze-candidate branch.

### Exact identities
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`
- review inbox consumed: `7c038f0cd016dbf261b38f43f6c573db358d2fff`
- review outbox blob: `9fb68c00e96a368ccdc198fb784bbffe7bddf626`
- verdict: `CHANGES REQUIRED BEFORE OWNER DECISION`
- only material blocker: K-01

Before editing, resolve canonical and candidate from fresh remote truth. Abort if identities or merge-base differ, or unrelated owner work is present. Never trust the known-stale tracking ref. Do not reset/clean/stash/discard owner work.

### Hard scope
This round is **test-module-only** unless a strictly necessary correction to the test's own documentation is inside that same module:
- allowed file: `crooks-assistant/tests/test_orchestrator_freeze_spec.py`
- do not change freeze-contract/state-API/acceptance/traceability prose; the independent review found the J-01/H-03/H-04 contract itself sound.
- no production/runtime/systemd/watcher changes, stale-refspec repair, secrets reads, account/global Claude changes, MCP/connector changes, privilege expansion, business writes, public exposure, destructive operations, spend, merge, adoption, DEC-046/047 changes, or Orchestrator implementation.
- do **not** take the review's optional non-blocking §3B row-504 hardening in this round. Keep this repair single-purpose.

### K-01 repair
The current helper `attempt_rows_committing_the_cleanup_handle()` only detects the literal phrase:
``lease.owned_process_group_handle` is committed`
so an operative second write in a real §3A row using ordinary paraphrases such as `is written` or `is rewritten` passes the gate.

Replace that single-verb detector with a structural/fail-closed classifier over every §3A transition-row mention of `lease.owned_process_group_handle`.

Requirements:
1. Every relevant §3A row/cell mentioning the cleanup handle must be classified into exactly one semantic class:
   - WRITES
   - PROHIBITS_WRITE
   - READS_ONLY
2. Use a closed, explicit marker set. WRITES must cover at least: committed, written, rewritten, updated, replaced, cleared, set, recorded, populated, assigned, superseded and normal grammatical variants needed by the actual spec.
3. Negated/prohibition forms such as `MUST NOT update, replace or clear` must classify as PROHIBITS_WRITE rather than WRITES.
4. Read-only/reference forms such as `identified from`, `read from`, `named by`, `proven by`, `MUST NOT be used as` must not count as writes.
5. Any handle mention that cannot be classified unambiguously must make the freeze gate fail closed. Unknown wording is not silently ignored.
6. Derive the real WRITES rows from actual §3A transition rows. Assert their count equals the declared cardinality and the sole write row equals the declared `CREATED -> STARTING` write point.
7. Keep the independent prohibition/cardinality checks. Do not solve this by adding another narrow blacklist.
8. Correct the test docstring so it claims only what the implementation actually proves.

### Required mutation proof
Add a parametrised test/harness that leaves §3A.3's prohibition and declared count `1` intact while injecting an operative second write into the real `STARTING -> RUNNING` row. At minimum prove each of these is caught:
- `is written`
- `is rewritten`
- `is updated to`
- `is replaced with`
- `is set to`

Also rerun the seven mutation cases from the review. All **7/7 must be caught** for structural/derived reasons, with the pristine candidate control green. Specifically the prior variants A/B that returned 63 passed must flip to a failing gate.

### Evidence
Prove failing-before against exact rejected SHA `c7c3d52` using immutable/hash-verified blobs or equivalent scratch without modifying owner work. Then run:
- committed freeze-spec suite;
- the required mutation suite/evidence;
- relevant Ruff/static checks;
- changed-file secret scan with no values printed.

Before publishing report exact base/rejected/new SHA, exact changed-file set (expected one file), tests/mutations, clean worktree and exact remote readback. Publish only to the existing freeze-candidate branch.

Do not self-certify. Previous verdict becomes stale for the changed SHA. State that exactly one fresh independent read-only adversarial review bound to the new exact SHA is required next.