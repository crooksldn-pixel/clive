# Product-memory consolidation coverage — 2026-09-25

Status: evidence record for the `product-memory-consolidation-3` objective. It is bound to the commit that contains it. It decides nothing and authorises nothing.

It covers two sources, both staged under `_incoming/` at base `55a9bece632d5cbaf9360836162e7584cc25ecb3`:

- `_incoming/truth/`: the kernel-accepted PM-01 to PM-04 truth branch, built on the 2026-09-23 reconciliation (23 files).
- `_incoming/handoff/`: the Opus 5.5 handoff documents (28 files).

For every source document it shows:

- where the document's content lives in the canonical files;
- every place where the canonical text differs from the source, and what happened to the source text there;
- that every decision, idea, feature and roadmap identifier is present once;
- that every document is indexed once.

## 1. How this evidence was produced, and its limits

The builder had file tools only: a ripgrep-based search tool (Grep), a glob tool (Glob) and a file reader. It had no shell and no git. Every count, list and line number below is the output of one of those tools, run on the candidate tree after the last edit to any file other than this one. Nothing here is estimated.

What the tools cannot do is hash bytes or run `diff`. So this record gives no blob SHAs. Instead, identity and correspondence rest on three kinds of tool output:

- **Six line-class counts per file** (Grep, count mode):
  - L: all lines (`^`);
  - N: non-blank lines (`\S`);
  - D: lines containing a digit (`[0-9]`);
  - C: lines containing a comma (`,`);
  - P: lines ending in a full stop (`\.$`);
  - H: lines starting with `#`.
- **Line maps.** For each differing document, its headings were listed with their line numbers (Grep `-n`) in the source and in the canonical file, and the changed regions were read in both. A document's unchanged runs keep a constant line offset, and every change of offset is accounted for by a hunk listed in §4.
- **Probes.** A probe runs Grep in content mode with `-n`, `offset = k - 1` and `head_limit = 2`. It returns the k-th and (k+1)-th matching lines. If the k-th match is at or before line X and the next one is after X, then exactly k matching lines lie in lines 1 to X. That lets a range of a canonical file be counted and compared with its source.

These are strong but not byte-level. A same-length word substitution inside a line that changes none of the six classes would not show. Byte-level confirmation needs the commands in §9, which neither the builder nor its checks ran. CLIVE's scope check sees the changed-path list, and `_incoming/` must not appear in it.

This attempt's builder made no edits under `_incoming/`. Earlier attempts are covered by the changed-path check only.

## 2. Manifests

Glob `_incoming/**/*` returned only the Markdown files below. Neither tree has subdirectories or other files. The six counts come from the Grep runs described in §1.

Relation codes:

- **same**: all six counts equal the canonical file's.
- **diff**: at least one count differs, and §4 lists every hunk.
- **T=C**: the truth copy and the canonical file are the same, but the handoff copy differs.

| File | truth L N D C P H | handoff L N D C P H | canonical L N D C P H | Relation |
| --- | --- | --- | --- | --- |
| BUILDER_ENVIRONMENT_REVIEW.md | 105 69 32 27 31 10 | 105 69 32 27 31 10 | 105 69 32 27 31 10 | same |
| CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md | 257 165 28 39 56 15 | 257 165 28 39 56 15 | 257 165 28 39 56 15 | same |
| CLIVE_IDENTITY_AND_HOME_SURFACE.md | 126 79 20 14 25 10 | 126 79 20 14 25 10 | 126 79 20 14 25 10 | same |
| CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md | 281 148 31 54 79 19 | 281 148 31 54 79 19 | 281 148 31 54 79 19 | same |
| CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md | 657 460 78 54 110 47 | 657 460 78 54 110 47 | 657 460 78 54 110 47 | same |
| CURRENT_TRUTH.md | 285 190 64 108 100 22 | 192 132 36 77 69 12 | 398 271 104 135 128 30 | diff (§4.11) |
| DECISIONS.md | 853 540 140 142 178 60 | 756 485 129 123 153 57 | 892 571 162 152 196 62 | diff (§4.13) |
| DEV_TEAM_V1_PILOT.md | 133 99 26 21 23 9 | 133 99 26 21 23 9 | 133 99 26 21 23 9 | same |
| DIRECTOR_PROTOCOL.md | 188 132 30 45 24 13 | 188 132 30 45 24 13 | 188 132 30 45 24 13 | same |
| ENGINEERING_CONTROL_PLANE_VNEXT.md | 350 253 25 29 58 21 | 295 211 22 23 49 19 | 370 269 38 38 67 21 | diff (§4.10) |
| ENGINEERING_DISPATCHER_V1.md | — | 217 149 26 91 66 12 | 234 160 35 100 71 12 | diff (§4.6) |
| ENGINEERING_LIFECYCLE_PRODUCERS.md | — | 92 68 8 49 29 9 | 92 68 8 49 29 9 | same |
| ENGINEERING_ORCHESTRATOR_V1.md | 287 192 45 104 69 18 | 287 192 45 104 69 18 | 287 192 45 104 69 18 | same |
| ENGINEERING_STACK_REUSE_PLAN.md | 193 150 26 22 42 16 | 193 150 26 22 42 16 | 193 150 26 22 42 16 | same |
| EVOLUTION_POLICY.md | 225 149 38 77 48 14 | 225 149 38 77 48 14 | 225 149 38 77 48 14 | same |
| FEATURES.md | 82 75 60 13 4 2 | 77 70 55 9 4 2 | 108 98 74 36 15 2 | diff (§4.15) |
| HARNESS_ACCEPTANCE_2C2B0CC.md | 33 23 14 6 12 5 | 33 23 14 6 12 5 | 33 23 14 6 12 5 | same |
| IDEAS.md | 990 729 142 221 127 61 | 958 707 140 220 120 60 | 991 730 143 222 128 61 | diff (§4.14) |
| JUDGMENT_LEDGER_CONTRACT.md | — | 80 58 14 12 11 7 | 81 59 14 13 11 7 | diff (§4.1) |
| MIGRATION_HANDOFF.md | 385 272 60 89 58 21 | 383 271 59 88 57 21 | 387 274 61 90 59 21 | diff (§4.5) |
| OPUS_5_5_HANDOFF_2026-09-24.md | — | 398 262 86 13 72 23 | 400 263 87 14 73 23 | diff (§4.3) |
| OPUS_5_5_START_PROMPT_2026-09-24.md | — | 46 34 14 8 16 1 | 48 35 15 9 17 1 | diff (§4.2) |
| OWNER_DECISION_PACKET_2026-09-21.md | 58 37 6 9 16 5 | — | 60 38 7 10 17 5 | diff (§4.4) |
| PRODUCT_BRAIN.md | 515 356 50 183 78 35 | 497 344 49 181 73 34 | 515 356 50 183 78 35 | T=C; handoff diff (§4.9) |
| README.md | 95 69 21 30 46 6 | 98 72 21 34 49 5 | 110 84 34 45 61 6 | diff (§4.12) |
| RECONCILIATION_2026-09-23.md | 501 334 83 97 117 30 | — | 510 342 87 98 122 30 | diff (§4.8) |
| REMOTE_ENGINEERING_CONTROL_V1.md | — | 120 81 10 15 31 11 | 196 142 31 66 50 11 | diff (§4.7) |
| REVIEW_ACCEPTANCE_CONTRACT.md | — | 84 61 10 4 11 8 | 84 61 10 4 11 8 | same |
| ROADMAP.md | 762 547 90 61 64 68 | 762 547 90 61 64 68 | 829 601 128 75 82 69 | diff (§4.16) |
| SELF_IMPROVEMENT.md | 811 588 86 204 123 40 | 811 588 86 204 123 40 | 811 588 86 204 123 40 | same |

Totals:

- 30 distinct file names: 21 in both trees, 2 in the truth tree only and 7 in the handoff tree only.
- 23 truth rows and 28 handoff rows, which match the trees' sizes.
- 14 file names are **same** in every copy they exist in.
- The truth and handoff copies of `ROADMAP.md` are also identical to each other: equal counts, and all 57 item headings at the same line numbers (Grep `^## [A-Z][0-9]+\.` with `-n` on both).

## 3. Index, identifiers and the no-loss comparisons

### 3.1 Exactly-once indexing

- Glob `*.md` in this directory returns 38 files. That is the 30 destinations above, the 2026-09-24 records [GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md), [OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md), [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md), [SOURCE_ASSIMILATION_V1.md](./SOURCE_ASSIMILATION_V1.md) and [SOURCE_SHELF.md](./SOURCE_SHELF.md), then [MOBILE_ALPHA.md](./MOBILE_ALPHA.md), [SUPPORT_INVESTIGATOR_V1.md](./SUPPORT_INVESTIGATOR_V1.md) and this file.
- In `README.md`, Grep `-o -n` of the index-link pattern that `scripts/product_memory_check.py` uses returns 37 matches on 37 distinct lines (15 to 31, 33, and 35 to 53). The 37 targets are 37 distinct names. Together they are exactly the 37 files other than `README.md`. So every document is linked once, and nothing is linked twice.
- `README.md` is itself the destination of both source indexes (§4.12).

### 3.2 Decisions

Grep count of `^## DEC-[0-9]{3} ` over the whole directory matches only three files:

| File | Headings | Identifiers |
| --- | --- | --- |
| truth `DECISIONS.md` | 57 | DEC-001 to DEC-057 |
| handoff `DECISIONS.md` | 54 | DEC-001 to DEC-054 |
| `DECISIONS.md` | 59 | DEC-001 to DEC-059, contiguous, so each appears once |

The heading lines, with their titles, are the same in all three files for DEC-001 to DEC-057. No other canonical file defines a `DEC-` heading. There are two new identifiers:

- DEC-058 records the 2026-09-24 owner decisions from [OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md). That is a canonical-side record.
- DEC-059 records the owner's statements in handoff `OPUS_5_5_HANDOFF_2026-09-24.md`: "authorise activation" at line 272 (§9), and the Objective ID minimum length of 3 at lines 203 and 217 (§8). Those statements had no identifier in the source.

### 3.3 Ideas

Grep count of `^## IDEA-[0-9]{3} ` matches only three files:

| File | Headings | Identifiers |
| --- | --- | --- |
| truth `IDEAS.md` | 59 | IDEA-001 to IDEA-059 |
| handoff `IDEAS.md` | 58 | IDEA-001 to IDEA-058 |
| `IDEAS.md` | 59 | IDEA-001 to IDEA-059 |

Grep `-o` on the canonical file lists IDEA-001 to IDEA-059 in order, with no gap and no repeat. The titles of IDEA-045 to IDEA-059 are the same in all three files. Earlier titles sit at the same line numbers in all three files, because lines 1 to 947 are unchanged (§4.14).

### 3.4 Features

Grep count of `^\| FEAT-[0-9]{3} \|` matches only three files:

| File | Rows | Identifiers |
| --- | --- | --- |
| truth `FEATURES.md` | 59 | FEAT-001 to FEAT-059 |
| handoff `FEATURES.md` | 54 | FEAT-001 to FEAT-054 |
| `FEATURES.md` | 64 | FEAT-001 to FEAT-064 |

Grep `-o` on the canonical file lists FEAT-001 to FEAT-064 in order, with no gap and no repeat. FEAT-060 to FEAT-064 are new identifiers for the 2026-09-24 records and the 2026-09-25 facts. The feature-name column is the same as the sources for FEAT-001 to FEAT-059.

### 3.5 Roadmap items

Grep count of `^## [A-Z][0-9]+\. ` returns 57 for truth `ROADMAP.md`, 57 for handoff `ROADMAP.md` and 57 for `ROADMAP.md`. The items are:

- N1 to N7;
- D1 to D11;
- Q1 to Q6;
- X1 to X8;
- I1 to I7;
- L1 to L5;
- S1 to S6;
- Y1 to Y3;
- P1 to P4.

The titles are the same in all three files.

## 4. Disposition of every differing document

Line numbers are S (source) and C (canonical, at this commit). Each hunk's disposition is one of:

- **kept**: the source lines are present verbatim at the canonical lines given;
- **added**: the lines are only in the canonical file, and no source line is displaced;
- **superseded**: a source line was replaced because a later fact overtook it. Its former wording is kept either in the canonical file at the place given or verbatim in this record;
- **whitespace**: only blank lines differ.

### 4.1 JUDGMENT_LEDGER_CONTRACT.md (handoff → canonical)

- S1–43 → C1–43: kept.
- S44 → C44. Every word of S44 is kept. The canonical line adds the correction rule that a correction carries "the same `task_revision` and `attempt_id` as the corrected entry". That text is the judgment-ledger corrections revision, which is in production (FEAT-056).
- S45–59 → C45–59: kept.
- S60 → C60. Kept, and extended with "task revision or attempt (a `task_revision` or `attempt_id` changed, added or dropped)".
- S61–73 → C61–73: kept.
- C74: added. It is the matching adversarial-test bullet.
- S74–80 → C75–81: kept.
- Count check: N +1 and C +1 (C74), with D and P unchanged.

### 4.2 OPUS_5_5_START_PROMPT_2026-09-24.md (handoff → canonical)

- S1–2 → C1–2: kept.
- C3–4: added. It is the dated SUPERSEDED notice and a blank line.
- S3–46 → C5–48: kept.
- Count check: N, D, C and P each +1, all from C3.

### 4.3 OPUS_5_5_HANDOFF_2026-09-24.md (handoff → canonical)

- S1–2 → C1–2: kept.
- C3–4: added. It is the dated SUPERSEDED notice and a blank line.
- S3–398 → C5–400: kept. All 23 headings sit at +2.
- Count check: N, D, C and P each +1, all from C3.

### 4.4 OWNER_DECISION_PACKET_2026-09-21.md (truth → canonical)

- S1–2 → C1–2: kept.
- C3–4: added. It is the dated status and a blank line.
- S3–58 → C5–60: kept.
- Count check: N, D, C and P each +1, all from C3.

### 4.5 MIGRATION_HANDOFF.md

Truth → canonical:

- S1–3 → C1–3: kept, including the 2026-09-23 supersession notice.
- C4–5: added. It is the 2026-09-25 note.
- S4–5 → C6–7: kept.
- S6 `**Status:** ACTIVE` → C8 `**Status:** SUPERSEDED — kept as history (was ACTIVE)`: superseded. The prior value is kept in the line.
- S7–385 → C9–387: kept. All 11 `##` headings sit at +2.
- Count check: N +2, and D, C and P +1.

Handoff → canonical:

- S1–2 → C1–2: kept.
- C3–6: the truth tree's notice plus C4–5.
- S3 → C7: kept.
- S4 status → C8: superseded, as above.
- S5–383 → C9–387: kept, at +4.

### 4.6 ENGINEERING_DISPATCHER_V1.md (handoff → canonical)

- S1–2 → C1–2: kept.
- S3 → C3–10: superseded. The C3–8 status of 2026-09-25 replaces it. S3's authority sentence ("It authorises no deployment, no runtime, service, watcher or systemd change, no secret, no permission or connector change, no business write and no spend.") is kept verbatim at C8. The rest of S3 is restated as dated history at C10. S3 read verbatim: "Status: repository-only implementation, awaiting independent exact-SHA review. It authorises no deployment, no runtime, service, watcher or systemd change, no secret, no permission or connector change, no business write and no spend. It does not by itself prove the no-courier milestone. That milestone is met only when a separate, real, bounded product objective enters through this intake and reaches independently reviewed COMPLETE, BLOCKED or OWNER_GATE without anyone relaying messages between workers."
- S4–112 → C11–119: kept, at +7.
- S113 "State of the reviewer side, as found:" → C120–126: superseded. C120–124 give the reviewer state of 2026-09-25. C126 re-introduces the original list as "History (2026-09-23): the reviewer side as found when this document was written."
- S114–207 → C127–220: kept, at +13. That includes the three original reviewer bullets at C128–130.
- S208 → C221: kept. It is a blank line.
- C222–225: added. They are the "As of 2026-09-25" note and the history marker.
- S209–217 → C226–234: kept, at +17.
- Count check: N +11 = 5 (C3–10 replacing S3) + 4 (C120–126 replacing S113) + 2 (C222, C224).

### 4.7 REMOTE_ENGINEERING_CONTROL_V1.md (handoff → canonical)

- S1–4 → C1–4: kept.
- C5–14: added. It is the "As of 2026-09-25" block.
- S5–78 → C15–88: kept, at +10.
- C89–134: added. These are the projection, intake, echo, crash-safety, identifier and journal-safe bounds of the activation successors. They are present in the canonical file and in neither tree.
- S79–114 → C135–170: kept, at +56.
- C171–190: added. These are the successors' test bullets.
- S115–120 → C191–196: kept, at +76.
- Count check: N +61 = 9 + 32 + 20.

### 4.8 RECONCILIATION_2026-09-23.md (truth → canonical)

- S1–2 → C1–2: kept.
- C3–11: added. It is the dated status block and a blank line.
- S3–501 → C12–510: kept. All 18 `##` headings sit at +9.
- Count check: N +8, D +4, C +1, P +5 and H 0. All of it lies in C3–10.

### 4.9 PRODUCT_BRAIN.md (handoff → canonical; the truth copy is the same as canonical, §2)

- S1–205 → C1–205: kept.
- C206–223: added from the truth tree. It is "### 2.14 Explicit disagreement is higher-value state than silence".
- S206 "### 2.14 Engineering is multi-model by role, …" → C224 "### 2.15 …": renumbered, as in the truth tree.
- S207–497 → C225–515: kept, at +18.
- Grep `-o -n ,` on both files lists every comma occurrence by line. Each handoff comma line n maps to canonical line n (for n up to 205) or n + 18 (from 206). The only canonical comma lines with no source are C208 and C210, which are inside the added section.

### 4.10 ENGINEERING_CONTROL_PLANE_VNEXT.md

This attempt added C7–20, C27–28 and C311–312 in response to review finding F-02.

Truth → canonical:

- S1–2 → C1–2: kept.
- S3 `**Status:** ACTIVE ENGINEERING DIRECTION / IMPLEMENTATION PLAN` → C3: superseded. C3 keeps the prior value as "(was ACTIVE ENGINEERING DIRECTION / IMPLEMENTATION PLAN)".
- S4–6 → C4–6: kept.
- C7–20: added. It is the dated status notice. It names the bridge, the §11 phases and the replaced sequencing as history, and it lists the durable requirements that stay active.
- S7–12 → C21–26: kept.
- C27–28: added. It is the §1–§3 history marker.
- S13–175 → C29–191: kept, at +16.
- C192–193: added. It is the "Phase 1 identity limitation" paragraph, from handoff S134.
- S176–292 → C194–310: kept, at +18.
- C311–312: added. It is the §11 history marker.
- S293–350 → C313–370: kept, at +20.
- Count check: N +16 = 13 + 1 + 1 + 1. D +13, which is all from the added lines and the changed C3.

Handoff → canonical:

- S1–6 → C1–6. S3 is superseded as above.
- S7–12 → C21–26: kept.
- S13–121 → C29–137: kept.
- C138–179: added from truth. It is "## 5.1 Observable work-in-progress is first-class state".
- S122–173 → C180–231: kept, at +58.
- C232–245: added from truth. It is "## 8.1 Verification must have a stopping rule".
- S174 "## 8.1 Obvious continuation …" → C246 "## 8.2 …": renumbered, as in truth.
- S175–238 → C247–310: kept, at +72.
- C311–312: added. It is the §11 history marker.
- S239–247 → C313–321: kept, at +74.
- S248 "- define task/result JSON schemas;" → C322 "- define task/result/progress-event JSON schemas;": truth's later wording.
- S249 → C323: kept.
- S250 "- implement generated ACTIVE_STATE;" → C324 "… with current progress projection;": truth's later wording.
- C325: added from truth. It is "- add a compact Termius/operator progress view;".
- S251–295 → C326–370: kept, at +75.

### 4.11 CURRENT_TRUTH.md

Truth → canonical:

- S1–4 → C1–4: kept.
- S5 `**As of:** 2026-09-23` → C5 `2026-09-25`: superseded. The 2026-09-23 state is kept below as dated sections.
- S6–10 → C6–10: kept.
- C11–97: added. This is "State as of 2026-09-25", the objective's stated facts.
- S11–12 → C98–99: kept.
- C100–101: added. It is a history note.
- S13–50 → C102–139: kept, at +89.
- C140–141: added. It is a history note.
- S51–80 → C142–171: kept, at +91. A dated note is appended in the same line to S71 (C162).
- C172–173: added. They are the history marker before "Where the documents are", and a blank line.
- S81–93 → C174–186: kept, at +93. A dated note is appended in the same line to S93 (C186).
- S94–138 → C187–231: kept.
- C232–233: added. It is the Generative UI V1 pointer.
- S139–189 → C234–284: kept, at +95. A dated note is appended to S157 (C252).
- C286–295: added. It is the history note on the bridge-era bullets, and a blank line.
- S190–211 → C285, C296–316: kept. Dated notes are appended in the same line to S193, S194, S195, S196, S197, S201 and S209 (C298, C299, C300, C301, C302, C306 and C314).
- C318–319: added. It is the note on the fixed role list.
- S212–264 → C317, C320–371: kept, at +107.
- C372–377: added. It is the 2026-09-25 note on the near-term order.
- S265–285 → C378–398: kept, at +113. A dated note is appended to S285.
- Probe check: canonical lines 1 to 97 hold 68 non-blank lines. Lines 1 to 10 hold 6 of them, so C11–97 holds 62. The added non-blank lines total 62 + 1 + 1 + 1 + 1 + 9 + 1 + 5 = 81, which equals N 271 − 190.

Handoff (the 2026-09-21 predecessor) → canonical:

- S1–4 → C1–4.
- S5 `**As of:** 2026-09-21`: superseded.
- S6–10 → C6–10.
- S11–23 → C188–200.
- S25–53 → C203–231.
- S55–65 → C236–246.
- S67–97 → C248–278.
- S99 → C284.
- S101–105 → C296–300.
- S107–119 → C302–314.
- S121 → C316.
- S123–171 → C320–368.
- S173 → C370.
- S175–190 → C380–395.
- S192 → C398.
- All of these are kept, with dated notes appended as listed above. The handoff tree has none of the truth tree's 2026-09-23 sections, and the canonical file carries them.
- The one handoff line not kept verbatim is S106. The truth tree had already replaced it (truth S196 → C301) after the 2026-09-23 live probe contradicted its claim of a verified model baseline. Superseded. S106 read verbatim: "- The CROOKS bridge watcher is installed and enabled. Its runtime is now explicitly pinned to `claude-fable-5-1` at `high` effort from reviewed source revision `5ada7b47f13547f107be1f53beeb79021cc48c24`; the corrected installer upgrade-order regression suite passed `126 passed, 0 failed`. A real unattended post-install smoke round consumed inbox blob `5d659fbc9418f378a10ddc5666e79ffc5b94ae7c`, published a new outbox, made no application/infrastructure/production changes, and returned the watcher to `pending no`, `failures 0`, `lock free`. The single-worker bridge therefore has a verified deterministic Claude model/effort baseline; future Engineering Orchestrator routing remains task-specific rather than permanently fixed to this one model."

### 4.12 README.md

Truth → canonical:

- S1–4 → C1–4: kept.
- S5 → C5: superseded. The per-branch reading locations were replaced by `clive/trunk`, and C5 lists the old branches as history. S5's branch map is also kept verbatim in CURRENT_TRUTH C174, "Where the documents are".
- S6–28 → C6–28: kept, except the S23 description. This attempt replaced "active control-plane upgrade plan: …" at C23 with the SUPERSEDED description, which still carries the same topic list (F-02).
- S29 → C29 (MIGRATION_HANDOFF entry): superseded. It was "current GPT-conversation migration entry point: exact active state, in-flight work, control-plane status, and continuation instructions."
- S30 → C30 (RECONCILIATION entry): superseded. It was "current reconciliation checkpoint for …", and its topic list is kept.
- S31–37 → C32–38: kept.
- S38 (OWNER_DECISION_PACKET entry) → C31: kept, moved, with the gate status added.
- C39–53: added. These are the handoff-only documents, the 2026-09-24 records and this file.
- S39–95 → C54–110: kept, at +15.

Handoff → canonical:

- S1–4 → C1–4.
- S5: superseded, as above.
- S6–28 → C6–28.
- S29: superseded, as above.
- S31–38 → C33–40.
- S39 → C43.
- S40 → C44: extended. S40 ended "repository-only, and not by itself the no-courier milestone."; C44 records that the dispatcher has been active since 2026-09-25 and that its 2026-09-23 limits are dated history.
- S41 → C45.
- S43 → C51, C52 and C55. S43 was a single line holding two index entries and the "## Status model" heading, fused by literal backslash-n escape sequences. That is the corruption `scripts/product_memory_check.py` rejects. The canonical file splits it. The two entries' former descriptions were "current CLIVE engineering handoff for a fresh Opus 5.5 session; exact branches, SHAs, safety invariants, activation state and next steps." and "paste-ready startup prompt for the new Opus 5.5 chat." Both are superseded by the SUPERSEDED descriptions.
- S44–98 → C56–110: kept, at +12.

### 4.13 DECISIONS.md

Handoff → canonical:

- S1–756 → C1–756. All 54 headings sit at the same line numbers.
- Four lines differ, all **Status** lines, and each is superseded:
  - DEC-028 at C305. Prior value `ACTIVE`. Now "RETIRED 2026-09-25 as a transport, with the bridge watcher (DEC-058); …".
  - DEC-029 at C315. Prior value `ACTIVE`. Now "RETIRED 2026-09-25 with the bridge watcher (DEC-058); kept as history".
  - DEC-030 at C323. Prior value `ACTIVE`. Now "RETIRED … the fail-closed workspace principle continues in DEC-012/DEC-043".
  - DEC-048 at C594. Prior value `ACTIVE`. Now "HISTORY — … superseded by the 2026-09-25 trunk deployment …; its limits on authority remain".
  - The decisions' own text is unchanged. DEC-058 records why each changed.
- Probes on canonical lines 1 to 756 return 485 non-blank lines (source 485), 133 digit lines (source 129, plus the 4 status lines that now carry dates), 125 comma lines (source 123, plus DEC-028 and DEC-048) and 153 full-stop lines (source 153).
- C757–845: added from truth. This is DEC-055 to DEC-057.
- C846–892: added. This is DEC-058 and DEC-059.

Truth → canonical:

- S1–572 → C1–572: kept, with the same four status lines superseded.
- Whitespace: runs of 2 or 3 blank lines between decisions were collapsed to one. S573–574 → C573, S592–593 → C591, S635–636 → C633, S704–706 → C701, S762–763 → C757, S787–788 → C781 and S831–832 → C824. That makes 8 lines in all.
- The remaining ranges are kept: S575–591 → C574–590, S594–634 → C592–632, S637–703 → C634–700, S707–761 → C702–756, S764–786 → C758–780, S789–830 → C782–823 and S833–853 → C825–845.
- Probes on canonical lines 1 to 846 return 540 non-blank lines (source 540), 144 digit lines (140 + 4), 144 comma lines (142 + 2) and 178 full-stop lines (178).

### 4.14 IDEAS.md

Truth → canonical:

- S1–947 → C1–947: kept.
- S948–950: whitespace. A duplicated `---` separator and its blank lines were removed.
- S951–979 → C948–976: kept. This is IDEA-059.
- C977–980: added. It is the 2026-09-25 update note on IDEA-059, a blank line and the separator.
- S980–990 → C981–991: kept.

Handoff → canonical:

- S1–947 → C1–947: kept.
- C948–980: added. This is IDEA-059 from truth, plus the note.
- S948–958 → C981–991: kept.

Probes on canonical lines 1 to 947 return 698 non-blank lines, 215 comma lines, 140 digit lines and 118 full-stop lines. Those are the handoff file's own counts for lines 1 to 947. The truth file's non-blank probe also returns 698 up to its line 946.

### 4.15 FEATURES.md

The header changed as follows:

- Truth S3 ("**Last consolidated:** 2026-09-23 (rows FEAT-010 to FEAT-014 updated and FEAT-055 to FEAT-059 added from the 2026-09-23 engineering state; earlier rows as consolidated on 2026-09-19)") → C3, C6 and C7: kept as dated lines.
- Handoff S3 ("**Last consolidated:** 2026-09-19") → C7.
- C5 and C11–15: added. They are the 2026-09-25 line and the production statement.
- Truth S5 and S69–82 → C9 and C95–108: kept.
- C84–93: added. It is the FEAT-063 detail.

These rows are unchanged from both trees: FEAT-001, 002, 003, 007, 009, 018–021, 023, 025–033, 035–037, 039–042 and 046–054.

Every other row changed status or note. For each, the prior status and note below are copied verbatim from the truth tree. The handoff value is given where it differs from truth.

- FEAT-004: `SHIPPED / HARDENING`, "Linux token persistence being formalised." It is kept in C22 as a dated history note.
- FEAT-005: `SHIPPED`, "Primary STT." It is kept, with a note added.
- FEAT-006: `SHIPPED`, "Existing voice output." It is now `NOT SHIPPED ON SERVER`, with the prior value kept in C24.
- FEAT-008: `SHIPPED / POLISH`, "Needs UX/UI refinement." It is kept, with a note added.
- FEAT-010: `SHIPPED`, "Linux production ratified at `1cf3a0f3…` on 2026-09-19 (DEC-048); no deployment since." The handoff had `BUILDING`, "Linux/systemd/Tailscale migration in review." It is superseded by the `ce791d03` deploy, and the ratification history is kept in C28.
- FEAT-011: `TESTING`, "Gmail OAuth still outstanding; new secret provisioning remains separately gated." The handoff had `TESTING`, "Static vs mutable secret handling under review." It is now `SHIPPED`, with the 2026-09-23 note kept in C29.
- FEAT-012: this row is the same in truth and canonical. The handoff had `TESTING`, "Code path prepared; live activation pending." The truth tree had already superseded it.
- FEAT-013: `SHIPPED / HARDENING`, "Manual bridge works." It is now `SUPERSEDED`, with the prior note kept in C31.
- FEAT-014: `SHIPPED / HARDENING`. The note read: "Installed and enabled; the hourly supervisor is disabled. Reviewed source revision `5ada7b47…` pins the installer's runtime to `claude-fable-5-1` at high effort, but the most recent verified live probe, a read-only live-host review on 2026-09-23 reported in the packet-20 review verdict relayed by the owner, found the loaded systemd unit (no drop-ins) carrying `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`. Runtime truth comes from probes, not from this register; the model and effort in force are whatever the next probe shows." The handoff had `TESTING`, "Built; review required before install." It is now `RETIRED`. The facts are kept in C32 and in CURRENT_TRUTH C301.
- FEAT-015: `PLANNED`, "Initial via web/PWA; native later." It is now `SHIPPED (ALPHA)`, with the prior value kept in C33.
- FEAT-016: `PLANNED`, "Highest product priority after deployment." It is now `BUILDING`.
- FEAT-017: `PLANNED`, "Entity focus, verbosity, tool routing, speed." It is now `BUILDING`, with the note kept.
- FEAT-022: `PLANNED`, "“What needs my attention?”" It is now `BUILDING`, with the note kept.
- FEAT-024: `PLANNED`, "Scheduled/event/conditional/stateful/goal-based." It is now `BUILDING`, with the note kept.
- FEAT-034: `PLANNED`, "Contextual UI generation." It is now `BUILDING`, with the note kept.
- FEAT-038: `PLANNED`, "Isolated candidate development." It is kept, with a note added.
- FEAT-043: `CAPTURED`, "Independent top-level engineering reviewer." It is kept, with a note added.
- FEAT-044: `CAPTURED`, "Iterative engineering without owner message ferrying." It is now `SUPERSEDED` by FEAT-063.
- FEAT-045: `CAPTURED` / `SOMEDAY`, "User no longer directly operates Claude Code." It is now `BUILDING` / `NOW`, with the prior value kept in C63.
- FEAT-055: `TESTING`. The note read: "Accepted and frozen at `18c3153a…` (packet 14 READY); records on `clive/engineering-state`; further kernel work only on dogfood evidence of a core-invariant failure. Not deployed as a service." It is now `SHIPPED (ENGINEERING LOOP)`, with every fact kept in C73.
- FEAT-056: `TESTING`. The note read: "On the CI stream at `b68e6e82…`; the `acceptance` workflow runs five gates on every push; mechanical gates produce evidence, not permission." It is now `SHIPPED`.
- FEAT-057: `TESTING`, "Read-only projection of kernel records; truth repairs accepted at `84e12e77…`." It is kept, with a note added.
- FEAT-058: `TESTING`. The note read: "COMPLETE in the kernel at `2dbb97bc…` after packets 15–18; two real cases verified read-only; owner verification, first live run, CI-stream landing and deployment pending. Cannot write." It is now `SHIPPED`.
- FEAT-059: `BUILDING`. The note read: "Implementation stream `chatgpt/clive-live-experience-v0-5`; production-lineage integration candidate `d9621337…` is owner-gated (fixture baseline authorisation and two product answers outstanding); not accepted, not deployed." It is now `SHIPPED`.

### 4.16 ROADMAP.md (truth and handoff are the same, §2)

- S1–2 → C1–2: kept.
- S3 `**Last consolidated:** 2026-09-19` → C3: superseded.
- S4–7 → C4–7: kept.
- S8 → C8: kept, with a dated note appended.
- S9–11 → C9–11: kept.
- C12–63: added. This is "Status as of 2026-09-25".
- S12–15 → C64–67, where S15 is the N1 status. N1 gets a new status at C67, and the prior status is kept verbatim at C68.
- S16–32 → C69–85, where S32 is the N2 status. N2 gets a new status at C85, and the prior status is kept at C86.
- S33–124 → C87–178, where S124 is the N7 status. N7 gets a new status at C178, and the prior status is kept at C179.
- S125–208 → C180–263, where S208 is the D7 status. D7 gets a new status at C263, and the prior status is kept at C264.
- S209–282 → C265–338, where S282 is the Q1 status. Q1 gets a new status at C338, and the prior status is kept at C339.
- S283–647 → C340–704: kept.
- C705–706: added. It is the dated note on the Someday engineering stage.
- S648–758 → C707–817: kept.
- C819–826: added. It is the 2026-09-25 note on the Sequencing rule.
- S759–762 → C818 and C827–829: kept.
- Status lines changed in place, with their prior values:
  - N3 at C105 was `PLANNED`.
  - N4 at C123 was `PLANNED`.
  - N5 at C136 was `PLANNED`, which is kept as its prefix.
  - N6 at C161 was `BUILDING / ACTIVE`.
  - X5 at C438 was `APPROVED DIRECTION`, which is kept as its prefix.
  - L3 at C580 was `APPROVED DIRECTION`, which is kept as its prefix.
  - L4 at C593 was `APPROVED DIRECTION`, which is kept as its prefix.
  - Y2 at C726 was `CAPTURED`.
  - Y3 at C735 was `CAPTURED`.
- Count check:
  - N +54 = 42 (C12–63) + 5 (history lines) + 1 (C705) + 6 (C819–826).
  - D +38 = 18 + 2 + 1 + 6, plus 11 status lines that now carry dates or identifiers.
  - P +18 = 13 + 6, minus 1 for S8, whose full stop now sits before the appended note.
  - The Grep `-o -n` list of full-stop lines in both files maps every source line through the offsets above.

## 5. Documents whose counts are identical

For each document marked **same** in §2, all six counts are equal in every copy. The 2026-09-25 state is carried by the documents in §4 and by CURRENT_TRUTH. So the counts show no change from either source. Each of these files is indexed once (§3.1):

- BUILDER_ENVIRONMENT_REVIEW
- CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE
- CLIVE_IDENTITY_AND_HOME_SURFACE
- CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY
- CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI
- DEV_TEAM_V1_PILOT
- DIRECTOR_PROTOCOL
- ENGINEERING_LIFECYCLE_PRODUCERS
- ENGINEERING_ORCHESTRATOR_V1
- ENGINEERING_STACK_REUSE_PLAN
- EVOLUTION_POLICY
- HARNESS_ACCEPTANCE_2C2B0CC
- REVIEW_ACCEPTANCE_CONTRACT
- SELF_IMPROVEMENT

## 6. Superseded documents

Each of these is marked SUPERSEDED or as history at its top and in its README entry, and is kept:

- MIGRATION_HANDOFF;
- OPUS_5_5_HANDOFF_2026-09-24;
- OPUS_5_5_START_PROMPT_2026-09-24;
- RECONCILIATION_2026-09-23, whose doctrine remains active;
- ENGINEERING_CONTROL_PLANE_VNEXT, whose durable requirements remain active and are listed in its notice;
- OWNER_DECISION_PACKET_2026-09-21, where Gate A is superseded, Gate C decided and Gate B open.

## 7. What the automated checks prove

`scripts/product_memory_check.py` and `tests/test_product_memory_structure.py` prove structure only:

- titles are present;
- there is no escape corruption;
- every top-level Markdown file is linked from the README;
- no README link dangles.

They compare link sets, so they do not detect a document linked twice. They do not check identifier uniqueness either (CURRENT_TRUTH, "Backlog recorded by this documentation round"). Those two properties rest on §3.

## 8. Not covered by this record

- Byte identity of the **same** documents and of the kept ranges (§1).
- That `_incoming/` is unchanged against the base. That is shown by the changed-path list CLIVE computes for the candidate.

## 9. Reproduce

Run with bash from `crooks-assistant/docs/product-memory` at the candidate commit. The builder could not run these. Each check prints nothing when its property holds, except `ls-tree`, `wc`, `grep -c` and `diff`. `diff` should show only the hunks in §4.

```bash
BASE=55a9bece632d5cbaf9360836162e7584cc25ecb3
git diff --exit-code "$BASE" HEAD -- _incoming
git ls-tree -r HEAD _incoming/truth _incoming/handoff

grep -oE '[]][(][.]/[A-Za-z0-9_.-]+[.]md[)]' README.md | sort | uniq -d
for f in *.md; do [ "$f" = README.md ] && continue
  n=$(grep -cF "](./$f)" README.md); [ "$n" -eq 1 ] || echo "$f indexed $n times"; done

grep -oE '^## DEC-[0-9]+'     DECISIONS.md | sort | uniq -d
grep -oE '^## IDEA-[0-9]+'    IDEAS.md     | sort | uniq -d
grep -oE '^[|] FEAT-[0-9]+ '  FEATURES.md  | sort | uniq -d
grep -oE '^## [A-Z][0-9]+[.]' ROADMAP.md   | sort | uniq -d

for t in truth handoff; do for f in _incoming/$t/*.md; do
  b=$(basename "$f"); cmp -s "$f" "$b" || { echo "== $f"; diff "$f" "$b"; }
done; done
```
