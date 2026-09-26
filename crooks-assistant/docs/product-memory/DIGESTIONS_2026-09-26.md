# Knowledge Digester: the first real digestions (2026-09-26)

**Status:** wave 4 of KNOWLEDGE_DIGESTER_V1.md section 9, built on `claude/digester-wave4-intake`, with a second pass the same day that makes the proposals worth reading and adds CLIVE's self mode (section 7). This is a summary: the quarantined copies, full reports, units and proposals stay on the engineering host (quarantine outside the repository, at `/tmp/claude-0/quarantine`), and third-party text appears here only as short fragments. Every artifact below is public.

## 1. What ran

- **Intake** (new, this wave): `app/digest/intake.py` and the handler registry `app/digest/intakes/` (git, archive, directory, file, url), with `scripts/digest_intake.py` on top. Each artifact was fetched over https at its default branch (CLIVE at `clive/trunk`), pinned to its commit, unpacked from `git archive` with every blob checked against `git ls-tree`, sealed read-only and named by its content digest.
- **Digest:** `pipeline.digest` (recognise, scan, decompose), then, from a driver outside the repository, `selfmodel.build_self_model` on this worktree (278 entries: 55 tools, 50 intent families, 10 scene primitives, 70 features, 89 ideas, 4 builder skills), `relate.relate` and `propose.propose`.
- Everything fetched was treated as data. The one place an artifact spoke to an AI agent in a way scan should notice (a guide quoting override phrases) was checked; see D4.
- Every artifact was digested before the repairs of section 4 and again after them; the numbers below are the final run unless marked "before".

## 2. Results at a glance

| Artifact | Pinned commit | Licence | Kinds (model) | Units | Outcome | Digest time |
|---|---|---|---|---|---|---|
| [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines) | `e3d624baaf29dc1fc645aff3e38f03e564d2d6b1` | MIT | document, configuration | 310 (before: 93) | digested | 0.06 s |
| [anthropics/skills](https://github.com/anthropics/skills) | `33375500bcea98d610eb30ce10ac4e59b89c390d` | none at the top; 14 skills Apache-2.0, 4 proprietary, 1 none | skill_collection, python_package, document, web_app | 0 (the 15 other skills alone: 4,312) | blocked: 4 proprietary sub-licences (before: also a false-positive injection block) | 2.4 s |
| [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli) | `74354ecc7a43da16d91a9bc54fa8db8283a3fcf5` | Apache-2.0 | skill_collection, node_package, document, configuration | 418 (before: 489) | digested | 0.17 s |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | `ce26fc25c0e5e8cab638f883de62d9a86ee5e45b` | MIT | skill_collection, document, media, configuration | 1,761 (before: 4,261) | digested | 0.69 s |
| [crooksldn-pixel/clive](https://github.com/crooksldn-pixel/clive) `clive/trunk` | `54b34378c6c3aad78f13dadf6a5b8dd57fd6f4ac` | none (no LICENSE) | 11 of the 14 model kinds | 10,434 | digested (before: blocked by 33 critical, all test fixtures) | 17.2 s |

Stage times on the shared two-CPU worker, final run (seconds):

| Artifact | Intake (fresh fetch) | Detect | Scan | Adapters | Relate | Propose |
|---|---|---|---|---|---|---|
| Vercel guidelines | 1.1 | 0.003 | 0.04 | 0.02 | 0.07 | 0.01 |
| anthropics/skills | 2.0 | 0.03 | 2.3 (before: 5.7) | 0.74 | 1.7 (open subset) | 0.24 |
| Playwright CLI | 0.9 | 0.006 | 0.12 | 0.04 | 0.13 | 0.02 |
| Taste Skill | 0.9 | 0.008 | 0.45 | 0.19 | 0.37 | 0.10 |
| CLIVE | 2.8 | 0.08 | 12.7 (before: 23.6) | 3.9 | 5.5 | 0.67 |

Nothing hung and nothing crashed. Scan is the slow stage everywhere (about 1.3 MB of text a second, half of it the wrapped-base64 decoder); the code adapter and relate are the next two on CLIVE.

## 3. Per artifact

### 3.1 Vercel's Web Interface Guidelines

- **What it is:** five files. README.md is the guidelines themselves (about a hundred rules under Interactions, Animation, Layout, Content, Forms, Performance, Design); AGENTS.md restates them as MUST/SHOULD lines for coding agents; command.md is a Claude Code slash command (front matter with `argument-hint`, a `$ARGUMENTS` placeholder) that reviews files against the rules; install.sh installs the command.
- **Recognition:** before the repairs only `agent_config` (from AGENTS.md), so README.md and command.md were never read: the guidelines were missing from their own digest (D1). Now also a documentation set ("mostly prose: 3 of 4 files").
- **Units:** 262 rules, 35 knowledge, 8 claims, 3 checks, 2 examples. Spot check of ten: all sensible after D8 and D9 (a "SHOULD: Layered shadows" line is a rule, not a step of a procedure; "**Links are links.** Use `<a>` for navigation" is a rule, not a claim to verify).
- **Scan:** `execute.script` on install.sh (true: it writes into the agent's command folder) and MIT permissive (true). No false positives.
- **Relate:** 169 units extend and 4 overlap CLIVE's builder skill `web-design-guidelines`.
- **Notable:** CLIVE already uses these guidelines, but its `web-design-guidelines` skill tells the agent to fetch `main/command.md` from GitHub before every review. That is unpinned third-party instruction text entering the agent's context at run time, which is exactly what the digester exists to stop (SOURCE_SHELF.md already said "freeze its live-fetched rules").
- **CLIVE should absorb:** the rules of command.md at `e3d624ba` as a pinned review-check set (one check per rule, each citing this Source; AGENTS.md's duplicates dropped), and the skill changed to read that pinned file instead of fetching. Removal handle: the check file and the skill edit. Hypothesis: fewer review rounds on storefront and Generative UI objectives. Watch: re-digest when upstream `main` moves, and re-prove.

### 3.2 anthropics/skills

- **What it is:** 19 skills under `skills/`, a Claude plugin marketplace manifest, a spec and a template. There is no licence at the top. Fourteen skills carry an Apache-2.0 LICENSE.txt; docx, pdf, pptx and xlsx carry "© 2025 Anthropic, PBC. All rights reserved", with use governed by the reader's agreement with Anthropic; doc-coauthoring has no licence file.
- **Outcome:** blocked before decomposition by four `licence.forbids_reuse` findings. They are true, and blocking is the policy (the owner decides on proprietary material). But the block stops the other fifteen skills too (R1). Before the repairs a fifth block came from `skills/claude-api/shared/model-migration.md:847`, a guide advising against override-style language that quotes three such phrases as examples; that was a false positive (D4), now `injection.mentioned` (warn).
- **The other fifteen skills, digested alone** (the four proprietary folders left out, as a subtree-scoped block would): 4,312 units, 56 procedures, 687 rules, 292 checks, 85 capabilities, 1,224 knowledge, 1,278 claims, 660 examples. Spot check of ten: sensible. Code (skill-creator's scripts, slack-gif-creator's validators) became capability and pattern units with signatures and docstrings; `mcp-builder/scripts/requirements.txt` became dependencies. Before D3, `prompt-caching.md` (a design guide with a numbered workflow) was read as 18 opaque "prompts".
- **Scan warnings:** 13 `injection.marker`, all API samples such as `system: "You are a helpful coding agent."` inside code blocks (benign, arguably true in shape); 15 `execute.script` (true: skill scripts); 1 `injection.mentioned` (the guide above).
- **CLIVE should absorb:**
  - `skill-creator` (Apache-2.0) as a builder skill for writing and evaluating CLIVE's own skills: its eval loop and description optimisation are what wave 5's builder-skill absorber needs. Removal: the skill folder.
  - `mcp-builder/reference/evaluation.md` as review checks on every future connector (for example that evaluation questions are read-only, independent and non-destructive). Removal: the check file.
  - `webapp-testing`'s start-servers, wait, run, clean-up pattern (`with_server.py`) for the proving ground's screenshot runs: a reference pattern, not an install.
  - `claude-api/shared/prompt-caching.md` (caching is a prefix match; order tools, then system, then messages; the optimisation workflow) as product-memory knowledge for the model gateway's cost work.
  - Reference only: the four proprietary skills, `doc-coauthoring` (no licence file, so no grant to reuse), `brand-guidelines` (Anthropic's own brand), `internal-comms`, `slack-gif-creator`.

### 3.3 Playwright CLI

- **What it is:** a Node package (bin `playwright-cli`), a skill `skills/playwright-cli` with ten reference guides (sessions, storage state, request mocking, tracing, video, test generation, PR attachments), CI and Azure pipelines, CLAUDE.md, and the maintainers' own `.claude/skills/dev`.
- **Units:** 418: 183 knowledge, 155 examples (the CLI commands), 50 rules, 21 claims, 3 capabilities (the bin, and two exported functions of skillCheck.js), 4 dependencies, 1 script, 1 check (the integration test). Before D2 the SKILL.md was read twice (489).
- **Scan:** new `execute.agent_permissions` (D12): the skill's front matter grants the agent `Bash(npx:*)` and `Bash(npm:*)` beside its own command. Installed as published, the agent could run any npm package without asking. Also `execute.ci` twice and `execute.script` (true). No false positives.
- **Relate:** CLIVE has no browser capability, so the bin is a gap (tool_connector); a few matches are word coincidences ("Navigation" commands against the `navigation_back` intent family, R6).
- **CLIVE should absorb:**
  - The skill as a builder skill for the proving ground, with its allowed-tools narrowed to the CLI itself: open, snapshot, click by reference, fill, screenshot, video and trace are the evidence the owner asked for on UI candidates. Installing `@playwright/cli` and its browsers is owner-only (SOURCE_ASSIMILATION_V1.md section 3); the skill is useless without it, so the proposal goes to the owner as one decision.
  - `references/test-generation.md` (plan, generate, heal, with a rule to give up rather than skip silently) as a native objective: storefront end-to-end tests.
  - `references/pr-attachments.md` as a loop procedure: screenshots and video attached to the PR as review evidence.

### 3.4 Taste Skill

- **What it is:** 13 skills, a research folder (on model "laziness"), images and a plugin manifest. The original upstream, pinned; SOURCE_SHELF.md warned that many same-named copies exist.
- **Notable:** CLIVE already carries three of these skills, byte-identical to this commit: `taste-skill` as `design-taste-frontend`, `soft-skill` as `high-end-visual-design`, and `image-to-code-skill` as `image-to-code` (relate: overlap, score 1.0). They have no provenance header and nothing watches upstream.
- **Units:** 1,761: 1,236 rules, 166 checks, 128 procedures, 114 knowledge, 104 claims. Before D2, D8, D10 and D13: 4,261, because every SKILL.md was read twice and 347 of 1,854 rules were a word or two ("premium", "Good text:"), while "Do not:" lists lost their "do not". Spot check of ten after: sensible, with some residual noise (a sentence fragment "**THIS IS NOT OPTIONAL." as a check).
- **Scan:** 3 `injection.marker` (example user prompts such as `User: "make a hero section..."` in imagegen-frontend-web; true in shape, benign), `execute.agent_settings` (the plugin manifest) and `execute.script` (skill.sh). Before the repair a fourth marker fired on a path template (`--<system>.md`), a false positive (D11).
- **CLIVE should absorb:**
  - Provenance for what it already has: the three copies pinned to `ce26fc25` with a source header, and upstream watched. Removal handle: the three folders.
  - `redesign-skill` (audit an existing site, then raise it to premium without breaking functionality) as a builder skill for the storefront overhaul objectives.
  - Reference only: `brandkit` (brand boards by image generation), the `imagegen-*` skills (only if CLIVE generates design images), `minimalist-skill` and `brutalist-skill` (styles, not the brand's), `taste-skill-v1` (superseded), `gpt-tasteskill` (mandates GSAP and a scripted randomiser), `output-skill` (overrides the model's own output behaviour, which is not a design rule), and the research folder's numeric claims, which are unverified.

### 3.5 CLIVE itself

- **What it is:** 1,411 files. Recognised as a Python package, a Shopify theme, Swift (the Mac app), Java/Kotlin (Android), a mobile app, CI, a skill collection, infrastructure, a Node package, a website, a documentation set, design tokens, images and JSON schemas.
- **Before the repairs:** blocked by 33 critical findings, every one in `tests/`: the scanner's own injection fixtures, bidi and homoglyph cases, and fake tokens (D6). Unblocked, scan still stopped after 32 MB with 230 files unread, because screenshots were read in full to be skipped (D5), and 66 theme JSON files (locales, templates, sections, settings) came back unparsed, because Shopify opens each with a `/* */` header (D7).
- **Units:** 10,434: 2,589 knowledge, 2,533 claims, 2,514 rules, 1,270 capabilities, 880 patterns, 318 checks, 154 examples, 79 interfaces, 58 procedures, 22 dependencies, 13 design tokens. 0 unparsed.
- **Scan warnings (144):** 42 `execute.script` (true); the test fixtures now reported as warnings (22 override, 4 hidden, 3 bidi, 2 encoded, the fake tokens); 31 `secret.assignment`, mostly test values; 13 `injection.address` in comments that describe instructions to the model (false positives in intent, warn only); 8 `deceptive.invisible` (a real BOM character in `interfaces.py` and test strings); 1 `licence.unknown` (true: the repository has no LICENSE).
- **What the self-digest shows:** relate cannot yet recognise CLIVE in its own repository. The self-model holds tools, intent families, scene primitives, features, ideas and skills, but not code, so CLIVE's own 1,270 functions come out as gaps, and propose suggests 1,269 tool connectors (for example for `trapFocus` in the theme's `assets/focus.js`) and 882 native objectives for its own patterns (R2). The units themselves are good raw material for the "why" index of CLIVE_SELF_KNOWLEDGE.md.
- **Gaps it exposed in the digester:** the Swift and Kotlin code is recognised but not decomposed (no adapter); the theme's JSON templates (which sections compose each page) are parsed but not read as design; the Liquid sections are.
- **CLIVE should absorb:** nothing. This digest is the input to the why index, once relate knows "self".

## 4. Defects found and fixed

Each has a regression test in the file named.

| ID | Where | Found on | What was wrong | Fix |
|---|---|---|---|---|
| D1 | detect.py | Vercel | An artifact that is mostly prose, or has a substantial README, was not a documentation set: the guidelines were never read | "mostly prose" and "substantial README" signals (test_digest_detect.py) |
| D2 | documents.py, skills.py | Taste, Playwright, skills | Every SKILL.md, AGENTS.md and prompt file was read by both adapters (160 of 854 spans in one file gave two Units) | The documents adapter leaves the skills adapter's files to it; the skills adapter now runs whenever documents does, pinned by a test over every detected kind |
| D3 | skills.py | skills | Any file with "prompt" in its name was a prompt library (`prompt-caching.md` became 18 "prompts") | Only files named as prompts (`prompts.json`, `system-prompt.md`, `x.prompt.md`) |
| D4 | scan.py | skills | A quoted example of override language blocked the whole collection | `injection.mentioned` (warn) for a short quotation that is nearly all the phrase, on a line that marks it as an example; hidden, encoded and payload-carrying quotations still block |
| D5 | scan.py | CLIVE | Binary files were read in full to be skipped, spending the byte budget: 230 files unread | The 8 KB probe decides; a binary is not read further |
| D6 | scan.py | CLIVE | CLIVE's own test fixtures and fake tokens blocked it | Injection, deceptive and credential findings in Python and Go test files are warnings; safe because the code adapter reads such files for test names and imports only (a test pins that coupling). JavaScript tests, whose titles reach Units, still block |
| D7 | adapters/interfaces.py | CLIVE | JSON with comments unparsed (66 theme files) | Comments between tokens are whitespace; an unclosed one is reported |
| D8 | adapters/skills.py | Vercel, Taste | Any bulleted list was a procedure ("Layered shadows", "premium") | Only numbered lists, steps headings, or lists whose items mostly tell the reader what to do; RFC 2119 "SHOULD" is a rule |
| D9 | adapters/documents.py | Vercel | "**Links are links.** Use `<a>`..." lost its rule; "Never substitute..." became a claim | A bold lead-in bullet is judged by the sentence after it too; a sentence opening with a directive "Never"/"Always" and a verb is not a claim for that word |
| D10 | adapters/skills.py | Taste, CLIVE | 347 of taste's 1,854 rules were a label or a word or two | Such items under a rules heading are one Unit for the section |
| D11 | scan.py | CLIVE, skills, Taste | Chat-role markers fired on `tool: str = ""`, `ASSISTANT: frozenset(...)`, Go `user := ...` and `--<system>.md` | Role-line patterns skipped in source code; `:=` and path templates excluded |
| D12 | scan.py | Playwright | A skill granting itself shell commands (`Bash(npx:*)`) went unreported | `execute.agent_permissions` (warn), counted, never quoted |
| D13 | adapters/skills.py | Taste | "Do not:" and "The output must feel:" were rules of their own and their lists lost the "do not" | A rule-bearing label and the list it introduces are one rule |
| D14 | adapters/skills.py | Playwright, skills | A link in a fenced example of CLI output, and `[Title](URL)` in a template, were "missing files" | Links in fences are example output (paths there are still followed); a target with no dot or slash is a placeholder |
| D15 | adapters/documents.py | skills | A fence opening on a list item's line (`2. ```sh`) left the rest of the guide read as code | The fence closes under its item |
| P1 | scan.py | skills, CLIVE | 42% of the skills repository's text is duplicate, and every credential pattern ran on every file | Content findings cached by digest; case-sensitive credential patterns skipped when their mandatory literal is absent (a test proves the findings are identical). CLIVE 23.6 s to 12.7 s while reading all of its text |

Found while building intake:

- `git archive` applies a repository's own `.gitattributes`: `export-subst` rewrites files, `export-ignore` drops them, `ident` expands `$Id$`, and a `filter=` attribute runs whatever filter that name is configured to on the machine (demonstrated: a configured smudge filter ran). This machine's global git config defines the `lfs` filter. Intake builds git's environment from nothing, neutralises every such attribute in `info/attributes` at the highest precedence, and checks every file and link written against `git ls-tree` by object id.
- Failures after materialisation (digesting, sealing, settling) escaped as raw `OSError`; every stage now raises an `IntakeError` type and leaves nothing that looks complete.

## 5. Defects in files this wave does not own

For the agent wiring relation and proposals into the pipeline (pipeline.py, relate.py, propose.py, selfmodel.py, report.py, model.py). Repro for each: `scripts/digest_intake.py URL --quarantine DIR`, then `relate.relate(result.units, selfmodel.build_self_model(<worktree>))` and `propose.propose(...)`.

- **R1 (pipeline.py) A block anywhere stops the whole artifact.** anthropics/skills at `33375500`: four sub-folder LICENSE.txt files block all 19 skills, 14 of them Apache-2.0. A block whose location is below the root (a nested licence, first of all) could exclude its subtree from decomposition instead: without the four folders the rest gives 4,312 units.
- **R2 (relate.py / selfmodel.py) CLIVE cannot recognise itself.** *Second pass: self mode, section 7.4.* `clive/trunk` at `54b34378`: 1,269 tool-connector and 882 native-objective proposals for CLIVE's own code (for example `trapFocus` in `assets/focus.js`), because the self-model has no code entries. Relate needs a self mode (a unit at a path the repository has is an overlap), or propose a why-index mode, when the artifact is CLIVE.
- **R3 (propose.py) One proposal per Unit, unranked and unbounded.** *Second pass: ranked and bounded, section 7.1.* CLIVE 10,434 proposals; taste 1,761 (1,402 review checks); Vercel 310 for about a hundred rules. Principle 5 (mass has a cost) needs grouping, de-duplication, ranking by relation score and a budget per target.
- **R4 (propose.py) Builder skills proposed per procedure, not per skill.** *Second pass: one per skill.* Taste: 126 builder-skill proposals from 13 skills, each a folder named after one procedure (for example `.claude/skills/the-anti-slop-manifesto-for-copilot-...`). For a skill collection the unit of absorption is the skill folder; the units carry `skill:<name>` tags to group by.
- **R5 (propose.py, pipeline.py) Licences are never consulted after scan.** *Second pass: each folder's licence decides.* Artifacts with no licence (anthropics/skills at the top, CLIVE) and units under a per-folder licence still get adding proposals. An unknown or forbidding licence should make the target `reference_only`, and a unit should carry the licence of its folder.
- **R6 (relate.py) Two shared words make a relation.** *Second pass: tuned evidence rule.* Playwright's "Navigation" commands extend the `navigation_back` intent family; taste's "premium card" rule extends `image-to-code` on "image" and "card". MIN_SHARED_TERMS = 2 lets coincidences through.
- **R7 (pipeline.py, report.py) Intake's notes have nowhere to go.** Withheld entries (links leading out, devices, version-control folders), submodules not fetched and Git LFS pointers are printed by `digest_intake.py` on standard error but reach neither the DigestResult nor the report. `digest(..., intake=...)` could turn them into quality findings.
- **R8 (model.py) Future kinds of source.** *Second pass: the `package` origin kind and handler.* `ORIGIN_KINDS` has no kind for a package-registry fetch (npm, PyPI) with the registry's own integrity hash; a handler for it is a new module in `app/digest/intakes/` plus that one word.
- **Coupling to note:** `scripts/digest_intake.py` imports `summary` and the exit codes from `scripts/digest.py`, so that the two print the same line. A change to `summary`'s signature must be followed there.

## 6. What the digester is and is not good at yet

It is good at:

- **Taking things in safely.** Five real repositories and every hostile case in the tests (escaping names, link chains, hard links out, devices, bombs by ratio, count, header and overlap, encrypted zips, a repository whose `.gitattributes` asks for a filter and whose hooks are plain files) went through intake without anything run or followed out; each copy is pinned, byte-checked against its commit, sealed and content-addressed.
- **Structured text written for agents**: skills, AGENTS.md and CLAUDE.md, guideline documents, and API and tool specifications. Rules, checks, procedures and examples now come out close to how a person would split them.
- **Code surface in Python and JavaScript/TypeScript**: modules, functions, CLI entries, dependencies and tests, with docstrings, never run.
- **Saying what it could not read**, and not quoting what it found.

It is not good at yet:

- **Knowing what matters.** Every Unit was proposed, unranked (R3, R4). Since the second pass proposals are grouped, ranked and bounded, and the first few of each artifact are mostly worth reading; below them, word coincidences still surface (section 7.3).
- **Understanding.** Classification is deterministic heuristics: a rule, claim or procedure is guessed from words and layout, and relation is word overlap (R6). The model-assisted understanding stage of the design is not built.
- **Knowing itself.** Pointed at CLIVE it saw CLIVE's code as gaps (R2). With `--self` it now traces a fifth of CLIVE's code to the product memory and names real drift, but by words only (section 7.4).
- **Scoping.** One blocked folder blocks the whole artifact (R1); licences stop at scan (R5).
- **Breadth.** No adapters yet for Swift, Kotlin, Go, Rust or Java code, for PDF or Office documents, for images, audio or video, for the page composition in Shopify JSON templates, or for live websites. Claude Code command files outside `.claude/commands/` are read as documents.
- **Speed at scale.** Scan reads about 1.3 MB of text a second and stops, with a warning, at 32 MB; a repository much larger than CLIVE is only partly scanned.

## 7. Second pass: proposals worth reading, and CLIVE as itself

Same five artifacts at the same pins (CLIVE's trunk had moved to `7ac748d1`, wave 3 landed), re-digested after the changes below. The self-model now has 370 entries: 55 tools, 50 intent families, 10 scene primitives, 5 review checks (the acceptance gates), 27 design-token families (web/style.css), 4 builder skills, 70 features, 89 ideas and 60 decisions, plus decided absorptions when a store is given.

### 7.1 What changed

- **Ranked and bounded (R3).** Each candidate is scored: target value x (0.4 + 0.6 x relation strength) x substance x cost, where a gap counts 0.3 of strength, and cost falls when the owner must decide, when there is no licence or an unrecognised one, when a licence sets conditions, when a claim must be verified, and when a skill is the artifact's own maintainers' tool. Near-repeats are folded into the best of them. Each target keeps a budget (builder skills 5, connectors 5, review checks 15, design system 5, native objectives 5, product memory 10, pointers 5). The rest are held back, counted in the report and listed by Unit, and `budget=None` records every one. Each proposal's reasoning ends with its rank and why.
- **One proposal for a whole (R4).** A skill (every Unit from its folder, whichever adapter read it) is one builder skill. So are a file's procedures. A file's rules and checks (three or more) are one review-check set, and a file's code is one native objective. A lone rule ranks as thin. Housekeeping (changelogs, licences, contribution guides) and the artifact's own tests are only pointed at.
- **Licences (R5).** `scan.licence_map` gives each folder its licence. A licence that forbids reuse makes a proposal a pointer. No licence, an unrecognised one or one with conditions makes the proposal the owner's to decide. A permissive licence travels as a "Licence:" part: keep the notice, from the file named.
- **Evidence (R6).** A relation needs the unit to name the entry, or three shared words, or two at a score of at least 0.35 (below that, nine in ten were coincidences on these artifacts). A generic-word stoplist was added, and extends moved from 0.2 to 0.25. A mixed-case word is compared whole and in parts (GitHub is "github" as a path spells it) but counts as one word. The artifact's own vocabulary, matched as one text, is evidence for its actionable units when it matches something CLIVE has at 0.45 or more: that is how Vercel's rules extend the `web-design-guidelines` skill.
- **Review items.** A remote API's read capability is now a connector with a client module that the owner approves (#7). A partly profiled dataset is not fed anywhere (#6, and the data adapter tags it `partial`). No title is quoted from a Unit whose title, path or file carries a credential (#5, propose side). The camel-case split is linear (#9). The self-model says when it stops short and never cuts a row (#14), and reads review checks, design tokens and the absorption ledger (#15). A foreign builder skill needs the owner. A gap is only a pointer when the self-model could not read CLIVE's registries. The relation tests run against a fixture product memory.
- **Packages (R8).** `npm:<name>[@<version>]` and `pypi:<name>[==<version>]` are taken in by a new `package` handler. The archive must match the registry's published digest (npm sha512, PyPI sha256), and the wrapper folder is taken off. Checked live on `left-pad@1.3.0`, `six==1.16.0` and `@types/node@20.11.0`.

### 7.2 Before and after: proposals by target

| Artifact | Before (one per Unit) | After (kept; held back) |
|---|---|---|
| Vercel guidelines | 310: review_check 264, product_memory 24, reference_only 22 | 8: review_check 3, reference_only 5; held reference_only 40 |
| Playwright CLI | 418: reference_only 348, review_check 51, product_memory 16, tool_connector 3 | 13: builder_skill 2, native_objective 2, product_memory 2, review_check 2, reference_only 5; held reference_only 97 |
| Taste Skill | 1,761: review_check 1,402, reference_only 163, builder_skill 126, product_memory 70 | 31: builder_skill 5, review_check 11, product_memory 10, reference_only 5; held builder_skill 6, product_memory 1, reference_only 151 |
| anthropics/skills (open subset) | 4,312: reference_only 2,803, review_check 979, product_memory 370, tool_connector 85, builder_skill 56, native_objective 19 | 13: builder_skill 5, review_check 2, product_memory 1, reference_only 5; held builder_skill 11, reference_only 178 |
| CLIVE, as an artifact | 10,434: product_memory 3,459, review_check 2,799, reference_only 1,969, tool_connector 1,269, native_objective 882, builder_skill 56 | 40: review_check 15, product_memory 10, native_objective 5, design_system 5, reference_only 5 (no tool connectors) |
| CLIVE, `--self` | (none) | 0: traced instead (7.4) |

anthropics/skills itself is still blocked as a whole by its four proprietary folders (R1, the other agent's).

### 7.3 The top proposals, and whether I would want them

Pointers are left out below, since they add nothing. "Owner" means the proposal says the owner must decide it.

**Vercel guidelines.** Three proposals add something. All three extend `web-design-guidelines` through the artifact as a whole (0.62), MIT, rank 0.54.

| # | Proposal | Want it? |
|---|---|---|
| 1 | Review-check set from README.md (121 rules) | No: the same list as #3, in prose |
| 2 | Review-check set from AGENTS.md (108 rules, 3 checks) | No: the same list again |
| 3 | Review-check set from command.md (33 rules) | Yes, pinned at `e3d624ba`, replacing the skill's live fetch of `main/command.md` |

The three are one list rendered three ways. They are paraphrases, so word overlap does not fold them. The deeper miss is that CLIVE already consumes this artifact live, but its self-model holds only the skill's description, not the URL it fetches, so relate cannot see that. Follow-up: record what a builder skill fetches. An artifact CLIVE already fetches is then an overlap, and the proposal becomes "pin it".

**Playwright CLI** (Apache-2.0).

| # | Proposal | Rank | Want it? |
|---|---|---|---|
| 1 | Builder skill `playwright-cli`, whole (owner) | 0.49 | Yes: the proving ground's browser evidence; the owner decides the install |
| 2 | Native objective: the code of skillCheck.js | 0.35 | No: it checks the skill's own installation |
| 3 | Native objective: the `playwright-cli` command | 0.35 | No: the skill already covers it |
| 4 | Product memory: "Commands > Tabs" | 0.29 | No: extends `order_tab_show` on "tab" and "list", a coincidence |
| 5-6 | Review-check sets of CLAUDE.md and README.md (4 rules each) | 0.14 | No: the project's own commit and install rules |
| 7 | Product memory: "Installing skills" (extends IDEA-045) | 0.13 | Marginal |
| 8 | Builder skill `dev`, the maintainers' own (owner) | 0.10 | No, and it now ranks last among the skills |

**Taste Skill** (MIT). All five builder skills are owner decisions.

| # | Proposal | Rank | Want it? |
|---|---|---|---|
| 1 | Builder skill `imagegen-frontend-web` (extends `image-to-code`) | 0.55 | Only if CLIVE generates design images |
| 2 | Builder skill `imagegen-frontend-mobile` | 0.55 | Same |
| 3 | Builder skill `design-taste-frontend-v1` (extends `design-taste-frontend`, 0.40) | 0.54 | No: the superseded version of the skill CLIVE has; its different name hides that |
| 4 | Builder skill `stitch-design-taste` | 0.54 | No: tied to one design tool |
| 5 | Builder skill `redesign-existing-projects` | 0.49 | Yes: the storefront overhaul |
| 6 | Review-check set of README.md (9 rules) | 0.35 | No: install notes |
| 7-10 | Product memory from the README's skill list | 0.30-0.32 | No: a catalogue |

The three skills CLIVE already carries are now pointers (644 units overlap by skill name). Six more builder skills are held back.

**anthropics/skills, the open fifteen** (Apache-2.0 per skill; no licence at the top).

| # | Proposal | Rank | Want it? |
|---|---|---|---|
| 1 | Builder skill `slack-gif-creator` (owner) | 0.53 | No; it ranks first on a coincidence ("ease", "cubic" against the ease tokens) |
| 2 | Builder skill `claude-api` (owner) | 0.51 | As knowledge for the model gateway, not as a skill |
| 3 | Builder skill `frontend-design` (owner) | 0.49 | Maybe: overlaps what CLIVE's design skills do |
| 4 | Builder skill `mcp-builder` (owner) | 0.49 | Yes: every future connector |
| 5 | Builder skill `skill-creator` (owner) | 0.49 | Yes: writing and evaluating CLIVE's own skills |
| 6-8 | Product memory and two README rules, marked "no licence" | 0.06-0.16 | No |

`webapp-testing`, one of the three I picked by hand in section 3.2, is among the 11 builder skills held back.

**CLIVE as an artifact** (no licence). The top 10 are review-check sets made of CLIVE's own product-memory documents, each extending one of its own decisions or ideas. None is wanted. It is the wrong mode: section 7.4 is the right one.

**Verdict.** Of the 29 proposals that would add something in these four top-ten lists, I would take 6: command.md pinned, `playwright-cli`, `redesign-existing-projects`, `mcp-builder`, `skill-creator`, and `claude-api` as knowledge. Two more are maybes. Before this pass, those six were buried among 6,801 proposals. The first proposal is right in two of the four artifacts (Playwright's skill, and Vercel's rule set if not its rendering) and wrong in two (Slack GIFs, image generation). What still gets through:

- a coincidence scoring 0.35 to 0.45 lifts a weak candidate (Slack GIFs, "Tabs");
- paraphrased repeats are not folded;
- a renamed old version of a skill CLIVE has reads as new.

### 7.4 CLIVE as itself: the why-index and drift

`scripts/digest.py --self` and `scripts/digest_intake.py --self` (or `digest(..., purpose="self")`) relate everything, propose nothing, and trace each Unit to the feature, idea or decision it serves. A Unit traces by one of three routes:

- **citation:** it cites the entry's id (FEAT-nnn, IDEA-nnn, DEC-nnn);
- **resemblance:** it resembles the entry by the relation's evidence rule;
- **file:** it is code whose file carries the entry's name. The name's words must weigh 0.75 of it, weighted by rarity across the code files, with at least two of them present and one rare.

On `7ac748d1`, in 30 seconds:

- **Coverage:** 4,150 of 10,463 Units traced. That is 512 of 2,458 code units (21%), in 104 of 705 code files. Before this pass: 0; with the per-unit rule alone, 75.
- **What the code serves most:**
  - FEAT-033 Anticipation engine (9 files)
  - FEAT-066 Voice-credits wording (8)
  - IDEA-071 clive-worker-01 as the engineering host (7)
  - FEAT-020 Event Ledger (6)
  - DEC-007 Unknown writes fail closed (5)
- **Real drift it names:**
  - FEAT-033 Anticipation engine is PLANNED / LATER in FEATURES.md, but `app/anticipation/` exists (engine, rules, signals, learning).
  - FEAT-020 Event Ledger is PLANNED, with code carrying it.
  - FEAT-013 is SUPERSEDED, but the bridge's code is still in the tree.
  - FEAT-069 Source Assimilation V1 is APPROVED, and code already carries it (the digester itself).
  - Eight approved or captured ideas have code, and so do FEAT-022 Attention engine (PLANNED), FEAT-043 GPT Director (CAPTURED) and FEAT-068 Generative UI V1 (BUILDING).
- **Shipped features with no code carrying them (9):**
  - Samsung PWA client, Hetzner deployment, iPhone responsive access, the GPT and Claude loop, Live Experience V0.5, mobile alpha, derived truth V1, mobile voice rules, and the microphone fix.
  - Most are deployment, device or front-end work that no code file names in words. It is a list to check, not a verdict. Before the file route it wrongly included Shopify and Gmail.
- **Decisions linked to the code that carries them out:**
  - DEC-007 to `app/actions/rows.py`
  - DEC-010 "Models are replaceable" to the reviewers package
  - DEC-028 and DEC-029 to the engineering bridge
  - DEC-024 to `app/secrets/linux_store.py`
  - DEC-026 to `scripts/provision_secrets.py`
  - DEC-023 to the Whisper-disabled tests
  - At least one of the twelve links is wrong: DEC-020 "Private-first networking" to `app/routes/pad.py`.
- **Code with nothing in memory:**
  - `scripts/` (245 of 357 code units) and `tests/` (166 of 191);
  - the Shopify theme (`snippets`, `assets`, `sections`: 285 units, none traced), because no feature row names the storefront;
  - `app/observability` (100 of 111) and `app/tools` (99 of 124).

**Would I use it?** Yes, as the start of the why-index. The anticipation and event-ledger rows are exactly the kind of FEATURES.md drift DRIFT_REVIEW_2026-09-26.md chases by hand. Its limits:

- it traces by words, so four fifths of the code is unexplained;
- a module whose name shares nothing with its feature is invisible;
- about one wrong decision link in ten.

A model-assisted understanding stage, or FEATURES.md rows that name their code folders, would close most of it.

