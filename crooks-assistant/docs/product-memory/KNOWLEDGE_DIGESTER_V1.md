# Knowledge Digester V1

**Status:** owner direction of 2026-09-26 ("aim high": digest every kind of application or file, never a single hard-to-unwrite task); this V1 design is PROPOSED and its first objectives are building. It extends SOURCE_ASSIMILATION_V1.md, which remains the authority and policy layer, and it is step 3 of the approved next phase (NEXT_PHASE_2026-09-25.md section 2).

## 1. Purpose

The Knowledge Digester is how CLIVE consumes the world's technology instead of being made obsolete by it. Given any artifact (a git repository, an agent skill, a document, an API or tool specification, a dataset, a website or web app, a theme or design system, media, an application, or CLIVE's own history), it produces provenance-tagged, reversible units of knowledge and capability, relates them to what CLIVE already is, proposes how to use them, and keeps only what proves its worth.

It answers the Adaptation filter's sixth and ninth questions directly: it makes CLIVE more capable of incorporating future capabilities, and it lets CLIVE consume technology that would otherwise obsolete it.

## 2. Principles

1. **Digesting is reading.** The digest stages never execute, import or install anything they read. Execution happens only in the proving stage, inside the sandbox, on purpose.
2. **Everything has a source.** No unit exists without its Source: origin, pinned reference, content digest, licence, time of intake.
3. **Everything can be unwritten.** Every absorption records exactly what it added (its removal handle) and can be taken out cleanly, with the suite still green afterwards. A single bespoke change that cannot be reversed is not digestion.
4. **One representation, open registries.** Every artifact kind becomes the same Units (procedure, rule, check, capability, interface, pattern, knowledge, data_schema, design_token, example, dependency, script, claim). New kinds arrive as new recognisers, adapters and absorbers, never as edits to the others.
5. **Prove or drop, and mass has a cost.** Each absorption states a hypothesis and a measure. What does not earn its place is removed. A budget per target keeps CLIVE fast (the owner's agar.io image, including its catch).
6. **CLIVE proposes; the owner decides; trust is earned.** Low-risk classes (reference knowledge, review checks) can earn automatic absorption after evidence; new keys, spend, data leaving the host and changes to live behaviour stay owner-gated.
7. **The same machine understands CLIVE itself.** Pointed at CLIVE's repository, product memory and engineering history, the digester builds the "why" index of CLIVE_SELF_KNOWLEDGE.md: which idea, decision and review produced each capability.

## 3. The pipeline

| Stage | What happens | Where |
|---|---|---|
| Intake | Fetch or receive the artifact, pin it (commit SHA, content digest), copy it read-only into quarantine, record its Source | engineering host (network) |
| Recognise | Detect every kind the artifact is, with evidence (`app/digest/detect.py`) | library, offline |
| Scan | Agent-directed instructions, deceptive characters, credentials, would-execute files, licence (`app/digest/scan.py`) | library, offline |
| Decompose | Kind-specific adapters turn the artifact into Units with exact locations | library, offline |
| Understand | Classify, summarise and link Units: deterministic first; model-assisted later, with the model's output itself provenance-tagged and treated as data | library; model gateway later |
| Relate | Compare Units with CLIVE's self-model: overlap, gap, novel, conflict | library |
| Propose | Absorption proposals, each with target, reasoning, hypothesis, measure and removal handle | library, reports |
| Decide | The owner, or earned autonomy for low-risk classes | phone (Generative UI), ledger |
| Absorb | Target-specific absorbers apply the change and record the removal handle | loop objectives or direct writes, per target |
| Prove | Measure the hypothesis: evaluations, review rounds, screenshots, usage | loop, proving ground |
| Keep, revise or drop | Removal is a first-class operation, verified by the suite | loop |
| Watch | Sources change; re-digest the difference and re-prove what depended on it | engineering host |

## 4. What it will digest

| Artifact kind | Typical units | Typical absorption |
|---|---|---|
| Agent skills, harness configuration, prompt libraries | procedures, rules, checks, scripts | builder skills, review checks |
| Code repositories | repository map, capabilities (commands, functions), patterns, dependencies, tests | objectives to build natively, reference patterns |
| Interface specifications (OpenAPI, GraphQL, JSON Schema, MCP tool manifests) | capabilities, interfaces, auth scopes | connector scaffolds behind the write gate |
| Documents (markdown, PDF, Word, HTML) | knowledge, rules, claims | product memory, business policies |
| Datasets (CSV, JSON, SQLite) | data schemas, distributions | business-memory feeds, world-model entities |
| Websites and web apps (read through a sandboxed browser) | operational procedures for sites without APIs | field operations (courier tracking, supplier portals) |
| Themes and design systems | design tokens, components, patterns | Generative UI tokens, taste checks, the storefront project |
| Media (images, audio, video) | transcripts, visual references | knowledge, brand and taste references |
| Applications | capability surface from documentation and interface | connectors or objectives |
| CLIVE itself | decisions, objectives, reviews, commits, deploys | the why index, drift detection |

## 5. CLIVE's self-model

Relating needs an up-to-date picture of what CLIVE already has: the tool registry and intent families, the builder skills, the review checks, the Generative UI primitives and tokens, the product-memory features and ideas, and the absorption ledger itself. The self-model is generated from those sources, never maintained by hand, so it cannot drift from the code.

## 6. Absorption targets and their removal handles

| Target | What is added | Removal handle |
|---|---|---|
| Builder skill | a skill folder with a provenance header | the folder path and its digest |
| Review check | a rule in the reviewer's rubric or an automated check | the rule id or check file |
| Tool or connector | a registered tool behind the gate, with tests | the registry entry, module and tests |
| Product-memory knowledge | an entry citing its Source | the entry id |
| Objective | a loop request built natively from the idea | the objective's commits |
| Design tokens or patterns (`design_system`) | a named token set in the Generative UI's token sheet (`web/style.css`), or a component folder beside the scene renderer (`web/components/`), with provenance; a token set needs the owner | the token set or component path |
| Reference only | a pointer in the digest report | nothing to remove |

## 7. Authority and safety

SOURCE_ASSIMILATION_V1.md section 3 governs. In addition: digestion has no network and executes nothing; quarantine is read-only; a block-severity finding stops the artifact before decomposition; content is data, never instructions, including to any model used in understanding; licences constrain reuse; credentials found are reported without their values. The repository is public, so digest reports of private business material stay on the engineering host, not in git.

## 8. Measures

The share of proposals the owner accepts; time from intake to working capability; review rounds saved on objectives that used absorbed skills or checks; absorptions still in use after 30 days; active absorptions per target against its budget; and removals that leave the suite green.

## 9. Delivery

- **Wave 1, building on 2026-09-26:** the model and absorption ledger; the quarantine scanner; recognition of every artifact kind.
- **Wave 2:** adapters for skills and agent configuration, documents, code repositories, interface specifications, datasets, and web themes and design tokens; one pipeline call `digest(path)`; a command-line entry and a report renderer.
- **Wave 3:** the generated self-model, relation and absorption proposals, as stages of the one `digest(root, source, store, self_model=...)` call: every Unit related to the self-model, one proposal per Unit written once to the ledger (a re-digest appends nothing), and both in the report and the command line (`scripts/digest.py`, related to CLIVE's own repository by default).
- **Wave 4, on the engineering host:** the intake fetcher and quarantine; the first real digestions (Playwright CLI, Taste Skill, Vercel's interface guidelines, a public skills collection, and CLIVE's own repository).
- **Wave 5:** absorbers for each target with removal, measurement and the watchlist; digest proposals shown on the phone as Generative UI scenes; "digest this" through Build from CLIVE.
- **Later:** model-assisted understanding through the model gateway, sandboxed browser digestion of live sites and apps, media, and earned autonomy for low-risk absorption classes.
