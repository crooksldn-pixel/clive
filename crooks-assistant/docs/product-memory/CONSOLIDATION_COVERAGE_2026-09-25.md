# Product-memory consolidation coverage — 2026-09-25

Status: evidence record for the `product-memory-consolidation-3` objective. It is bound to the commit that contains it. It maps every document, decision, idea, feature and roadmap item in the two staged source trees to its single canonical destination, and it gives the commands that reproduce each claim at that commit. It decides nothing and authorises nothing.

Sources, both staged unchanged under `_incoming/` at base `55a9bece632d5cbaf9360836162e7584cc25ecb3`:

- `_incoming/truth/`: the kernel-accepted PM-01 to PM-04 truth branch, built on the 2026-09-23 reconciliation (23 files).
- `_incoming/handoff/`: the Opus 5.5 handoff documents (28 files).

The third source is the 2026-09-24 records already in this directory. They are listed at the end.

How the claims were gathered: the builder had file tools only, no shell. Identifier sets and headings were read at the candidate tree with a search tool. The builder could not compute blob hashes. The commands in "Reproduce" produce the SHA-bound manifests (`git ls-tree`) and repeat every set comparison mechanically.

## 1. Document manifest

T = present in `_incoming/truth/`, H = present in `_incoming/handoff/`. Every file is Markdown. Neither tree has subdirectories or other files. Each canonical destination is the file of the same name in this directory, and each is linked exactly once in the README "Files" list. The exception is `README.md`, which is the index itself.

| Source file | T | H | Canonical destination | Canonical state |
| --- | --- | --- | --- | --- |
| BUILDER_ENVIRONMENT_REVIEW.md | T | H | [BUILDER_ENVIRONMENT_REVIEW.md](./BUILDER_ENVIRONMENT_REVIEW.md) | history |
| CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md | T | H | [CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md](./CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md) | active doctrine |
| CLIVE_IDENTITY_AND_HOME_SURFACE.md | T | H | [CLIVE_IDENTITY_AND_HOME_SURFACE.md](./CLIVE_IDENTITY_AND_HOME_SURFACE.md) | active doctrine |
| CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md | T | H | [CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md](./CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md) | active doctrine |
| CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md | T | H | [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md) | active doctrine |
| CURRENT_TRUTH.md | T | H | [CURRENT_TRUTH.md](./CURRENT_TRUTH.md) | active; merged, 2026-09-25 state on top |
| DECISIONS.md | T | H | [DECISIONS.md](./DECISIONS.md) | active register (§2) |
| DEV_TEAM_V1_PILOT.md | T | H | [DEV_TEAM_V1_PILOT.md](./DEV_TEAM_V1_PILOT.md) | proposed / history |
| DIRECTOR_PROTOCOL.md | T | H | [DIRECTOR_PROTOCOL.md](./DIRECTOR_PROTOCOL.md) | active |
| ENGINEERING_CONTROL_PLANE_VNEXT.md | T | H | [ENGINEERING_CONTROL_PLANE_VNEXT.md](./ENGINEERING_CONTROL_PLANE_VNEXT.md) | plan / history |
| ENGINEERING_DISPATCHER_V1.md | — | H | [ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md) | active, inside the remote loop; 2026-09-23 limits kept as dated history |
| ENGINEERING_LIFECYCLE_PRODUCERS.md | — | H | [ENGINEERING_LIFECYCLE_PRODUCERS.md](./ENGINEERING_LIFECYCLE_PRODUCERS.md) | active (frozen kernel) |
| ENGINEERING_ORCHESTRATOR_V1.md | T | H | [ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md) | proposed / history |
| ENGINEERING_STACK_REUSE_PLAN.md | T | H | [ENGINEERING_STACK_REUSE_PLAN.md](./ENGINEERING_STACK_REUSE_PLAN.md) | proposed |
| EVOLUTION_POLICY.md | T | H | [EVOLUTION_POLICY.md](./EVOLUTION_POLICY.md) | active doctrine |
| FEATURES.md | T | H | [FEATURES.md](./FEATURES.md) | active register (§4) |
| HARNESS_ACCEPTANCE_2C2B0CC.md | T | H | [HARNESS_ACCEPTANCE_2C2B0CC.md](./HARNESS_ACCEPTANCE_2C2B0CC.md) | history |
| IDEAS.md | T | H | [IDEAS.md](./IDEAS.md) | active register (§3) |
| JUDGMENT_LEDGER_CONTRACT.md | — | H | [JUDGMENT_LEDGER_CONTRACT.md](./JUDGMENT_LEDGER_CONTRACT.md) | active contract |
| MIGRATION_HANDOFF.md | T | H | [MIGRATION_HANDOFF.md](./MIGRATION_HANDOFF.md) | SUPERSEDED, kept as history |
| OPUS_5_5_HANDOFF_2026-09-24.md | — | H | [OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) | SUPERSEDED, kept as history |
| OPUS_5_5_START_PROMPT_2026-09-24.md | — | H | [OPUS_5_5_START_PROMPT_2026-09-24.md](./OPUS_5_5_START_PROMPT_2026-09-24.md) | SUPERSEDED, kept as history |
| OWNER_DECISION_PACKET_2026-09-21.md | T | — | [OWNER_DECISION_PACKET_2026-09-21.md](./OWNER_DECISION_PACKET_2026-09-21.md) | Gate B open; Gate C decided; Gate A superseded |
| PRODUCT_BRAIN.md | T | H | [PRODUCT_BRAIN.md](./PRODUCT_BRAIN.md) | active |
| README.md | T | H | `README.md` (the index; both source indexes merged into it) | active |
| RECONCILIATION_2026-09-23.md | T | — | [RECONCILIATION_2026-09-23.md](./RECONCILIATION_2026-09-23.md) | history; its supersession doctrine stays active |
| REMOTE_ENGINEERING_CONTROL_V1.md | — | H | [REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md) | active loop |
| REVIEW_ACCEPTANCE_CONTRACT.md | — | H | [REVIEW_ACCEPTANCE_CONTRACT.md](./REVIEW_ACCEPTANCE_CONTRACT.md) | active contract |
| ROADMAP.md | T | H | [ROADMAP.md](./ROADMAP.md) | active register (§5) |
| SELF_IMPROVEMENT.md | T | H | [SELF_IMPROVEMENT.md](./SELF_IMPROVEMENT.md) | active |

Totals: 30 distinct file names (21 in both trees, 2 in the truth tree only, 7 in the handoff tree only), so 29 indexed documents plus the index.

## 2. Decisions

| Source | Identifiers | Canonical destination |
| --- | --- | --- |
| truth `DECISIONS.md` | DEC-001 to DEC-057, one `## DEC-` heading each | `DECISIONS.md` DEC-001 to DEC-057, same identifiers and titles |
| handoff `DECISIONS.md` | DEC-001 to DEC-054, one `## DEC-` heading each | `DECISIONS.md` DEC-001 to DEC-054, same identifiers and titles |
| handoff `OPUS_5_5_HANDOFF_2026-09-24.md` §8–§9 (unnumbered owner statements: "authorise activation"; the Objective ID floor of 3) | none in source | DEC-059 (new identifier) |
| 2026-09-24 records (`OWNER_DECISIONS_2026-09-24.md`) | none in source | DEC-058 (new identifier) |

Both trees carry the same DEC-001 to DEC-054 headings. DEC-055 to DEC-057 exist only in the truth tree and are carried over. The builder compared DEC-046 to DEC-057 of the truth tree with the canonical text line by line. They differ only in blank lines, apart from DEC-048's status line. DEC-001 to DEC-045 start on the same lines in all three files. Status lines were changed only where a later fact superseded a state, and the old state is kept: DEC-048 reads "HISTORY — … its limits on authority remain". DEC-058 records the other supersessions (bridge watcher, `engineering-team-activation-v1`, the Gmail gap) as consequences, and leaves the older decisions' text in place.

Canonical result: 59 headings, DEC-001 to DEC-059, contiguous, each exactly once.

## 3. Ideas

| Source | Identifiers | Canonical destination |
| --- | --- | --- |
| truth `IDEAS.md` | IDEA-001 to IDEA-059 | `IDEAS.md` IDEA-001 to IDEA-059 |
| handoff `IDEAS.md` | IDEA-001 to IDEA-058 | `IDEAS.md` IDEA-001 to IDEA-058 |

IDEA-059 (Judgment Ledger and explicit proposal outcomes) exists only in the truth tree and is carried over. Headings and titles are identical across all three files. Canonical result: 59 headings, IDEA-001 to IDEA-059, contiguous, each exactly once.

## 4. Features

| Source | Identifiers | Canonical destination |
| --- | --- | --- |
| truth `FEATURES.md` | FEAT-001 to FEAT-059 (59 rows) | `FEATURES.md` rows FEAT-001 to FEAT-059, same identifiers and names |
| handoff `FEATURES.md` | FEAT-001 to FEAT-054 (54 rows) | `FEATURES.md` rows FEAT-001 to FEAT-054, same identifiers and names |
| 2026-09-24 records and the 2026-09-25 facts | none in source | FEAT-060 to FEAT-064 (new identifiers) |

Statuses were corrected to the 2026-09-25 facts. Many corrected rows carry a dated "History" note with their former status. For the rest, the former status is in `_incoming/truth/FEATURES.md` at the base and in Git. Superseded and retired rows stay in the table (FEAT-013 SUPERSEDED, FEAT-014 RETIRED, FEAT-044 SUPERSEDED). Canonical result: 64 rows, FEAT-001 to FEAT-064, contiguous, each exactly once.

## 5. Roadmap items

Both source `ROADMAP.md` files carry the same 57 item headings: N1–N7, D1–D11, Q1–Q6, X1–X8, I1–I7, L1–L5, S1–S6, Y1–Y3, P1–P4. `ROADMAP.md` carries the same 57 headings, each once, after a new "Status as of 2026-09-25" section. Items were updated by status line and dated notes, not removed.

## 6. The 2026-09-24 records (canonical side, not in either tree)

[GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md), [OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md), [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md), [SOURCE_ASSIMILATION_V1.md](./SOURCE_ASSIMILATION_V1.md) and [SOURCE_SHELF.md](./SOURCE_SHELF.md) remain, as do [MOBILE_ALPHA.md](./MOBILE_ALPHA.md) and [SUPPORT_INVESTIGATOR_V1.md](./SUPPORT_INVESTIGATOR_V1.md). Each is indexed once. With the 29 documents from §1 and this record, the README indexes 37 documents, and 38 Markdown files sit in this directory counting the README.

## 7. What the automated checks do and do not prove

`scripts/product_memory_check.py` proves that every top-level Markdown file in this directory is linked from the README and that no README link dangles. It also checks titles and escape corruption. It compares link sets, so it does not detect a document linked twice, and it does not check identifier uniqueness (CURRENT_TRUTH, "Backlog recorded by this documentation round"). The exactly-once and uniqueness claims above therefore rest on the commands below, not on that check.

## 8. Reproduce

Run with bash from `crooks-assistant/docs/product-memory` at the candidate commit. Every command that checks a property prints nothing when the property holds.

```bash
BASE=55a9bece632d5cbaf9360836162e7584cc25ecb3

# _incoming is unchanged against the base; the manifests with blob SHAs
git diff --exit-code "$BASE" HEAD -- _incoming
git ls-tree -r HEAD _incoming/truth
git ls-tree -r HEAD _incoming/handoff

# every source document has a canonical file, linked exactly once
for f in $(ls _incoming/truth _incoming/handoff | grep -E '[.]md$' | sort -u); do
  test -f "$f" || echo "missing $f"
  [ "$f" = README.md ] && continue
  n=$(grep -oF "](./$f)" README.md | wc -l)
  [ "$n" -eq 1 ] || echo "$f indexed $n times"
done
# no README link repeats
grep -oE '[]][(][.]/[A-Za-z0-9_.-]+[.]md[)]' README.md | sort | uniq -d

# every source decision, idea, feature and roadmap heading is present
dec()  { grep -E '^## DEC-[0-9]+ ' "$1" | sort; }
idea() { grep -E '^## IDEA-[0-9]+ ' "$1" | sort; }
feat() { grep -oE '^[|] FEAT-[0-9]+ [|] [^|]+[|]' "$1" | sort; }
road() { grep -E '^## [A-Z][0-9]+[.] ' "$1" | sort; }
for t in truth handoff; do
  comm -23 <(dec  _incoming/$t/DECISIONS.md) <(dec  DECISIONS.md)
  comm -23 <(idea _incoming/$t/IDEAS.md)     <(idea IDEAS.md)
  comm -23 <(feat _incoming/$t/FEATURES.md)  <(feat FEATURES.md)
  comm -23 <(road _incoming/$t/ROADMAP.md)   <(road ROADMAP.md)
done

# identifiers are unique in the canonical registers
grep -oE '^## DEC-[0-9]+'    DECISIONS.md | sort | uniq -d
grep -oE '^## IDEA-[0-9]+'   IDEAS.md     | sort | uniq -d
grep -oE '^[|] FEAT-[0-9]+ ' FEATURES.md  | sort | uniq -d
grep -oE '^## [A-Z][0-9]+[.]' ROADMAP.md  | sort | uniq -d

# expected counts: 59, 59, 64, 57
grep -cE '^## DEC-[0-9]+ '  DECISIONS.md
grep -cE '^## IDEA-[0-9]+ ' IDEAS.md
grep -cE '^[|] FEAT-[0-9]+ ' FEATURES.md
grep -cE '^## [A-Z][0-9]+[.] ' ROADMAP.md

# content of each shared prose document against its source: expect dated notes added and nothing recorded removed
for f in $(ls _incoming/truth _incoming/handoff | grep -E '[.]md$' | sort -u); do
  for t in truth handoff; do
    [ -f "_incoming/$t/$f" ] && git diff --no-index --stat "_incoming/$t/$f" "$f"
  done
done
```
