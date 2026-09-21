# CHATGPT INBOX

## Fresh independent adversarial review — exact freeze SHA f06730a

Review exact SHA `f06730aa361bb6054ae47bfa284539772a062782` on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`.

This is a review-only round. Do not modify the candidate. Do not carry any prior verdict across SHAs. Do not accept the repair handoff as evidence; independently re-derive behaviour from source and tests.

The immediately preceding round was the M-07 repair authored by Claude. The reviewer for this round must be independent of that repair authorship. If this bridge instance cannot satisfy that independence requirement, return a clear routing block rather than self-certifying.

Attack the evaluator rather than trusting its green suite. In particular:
- invent new coordinated-subject/object cases beyond the added table;
- test elided heads such as “two process groups and three more”;
- test “both … and …”, nested/appositive coordination, compounds/hyphenation, conjunction/disjunction ambiguity, active/passive variants, and punctuation/comma coordination;
- independently assess the disclosed postmodified-first-conjunct and comma-separated under-counts;
- decide whether the deliberate fail-closed `None` behaviour for unreadable coordination is an acceptable conservative gate or a material false-red defect;
- look for adjacent false-greens and false-reds not mentioned by the repair author;
- independently re-derive that M-01..M-06, L-01, K-01, J-01, H-03/H-04 and R-02 remain intact;
- require mutation/adversarial evidence and semantic recomputation, not just passing test counts.

Return exactly one engineering verdict bound to this exact SHA:
- `ACCEPT FOR NEXT GATE`, only if no material defect remains; or
- `REJECT — REPAIR REQUIRED`, with bounded concrete defect(s) and reproducing counterexample(s).

Engineering acceptance is not owner adoption. Do not merge, deploy, amend DEC-046/047 sequencing, change runtime/systemd/watcher state, read new secrets/credentials, widen connector/MCP permissions, perform business writes, or make production changes.
