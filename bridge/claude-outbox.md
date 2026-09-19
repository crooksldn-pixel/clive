# CLAUDE OUTBOX — latest handoff only

## 2026-09-19T16:45Z — ECC candidate audit for CROOKS harness reuse (read-only research/security audit)

**Inbox consumed:** yes. Blob SHA processed: `4f5bfb5eaa32ef151a02c153a0ecbb548ea110b8`
(`bridge/chatgpt-inbox.md`, heading "2026-09-19 — Audit ECC candidates for CROOKS engineering harness
reuse"). These instructions are now recorded as executed and must not be run again.

**Verdict up front.** Full ECC plugin/runtime/hook installation is **not justified** and the evidence is
specific (§5). Of the eleven candidate surfaces, the value that is real lives in **markdown** (ten
skills, all with no executable scripts) and in **one pure function** (`isDestructiveGit` in GateGuard,
the subject of the pinned commit). Recommended: **2 ADOPT STATIC**, **5 ADAPT/REIMPLEMENT**,
**1 DEFER-to-REJECT**, **3 REJECT** (including the hook graph as shipped). SkillSpector `--no-llm` at
the pinned commit: 8 of 10 skills **0 issues**; the two HIGHs are false positives read at the line
(§3). Separately, the headless engineering session **does inherit the owner's claude.ai business
connectors** (Gmail, Shopify, Google Drive, Resend, Omnisend) and four account-synced plugins into its
tool roster; one read-only probe of a non-business tool was **refused by the permission layer**, so an
unattended invocation is denied today, but the exposure is real and the isolation is untested (§6).
Nothing was installed, changed or committed. The Linux ratify/reverse decision was not touched.

---

## 1. What was asked

A read-only research/security audit of selected public components of `affaan-m/ECC` at commit
`07756cee15788a54506031462794ad645719b028`, against the accepted CROOKS Builder/Orchestrator contracts,
classifying each candidate (ADOPT STATIC CONTENT / ADAPT-REIMPLEMENT / DEFER / REJECT) with executable
surface, overlap, conflicts, value, safe integration form and provenance/scan evidence; a determination
on whether any full ECC installation is justified (default no); and an inspection of whether headless
Claude engineering sessions inherit user/business MCP connectors, with observed exposure and a safe
isolation design, **without changing settings**. Scratch clone/scan only; no installs, no npm, no
Builder/production/watcher/settings/systemd/Tailscale/secret/permission changes, no business
connectors, no commits.

## 2. Checkout state at start, and what was read

| Repo | Branch | HEAD | Status at start | Status at end |
|---|---|---|---|---|
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` (unit still says `claude/bridge-builder`; mismatch persists, untouched) | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` | clean | clean, unchanged |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | `91455ce9b99bb9f664f636f0746d3bbf940b9ed3` | clean | only `bridge/claude-outbox.md` modified |
| Production `/opt/crooks-os` (read-only) | `claude/linux-prod-migration-production` | `1cf3a0f3361b79f9de208d80f501543c53c244b5` | clean | clean, untouched |
| Product memory (origin, scratch clone) | `claude/product-memory-foundation` | `5d0bd4da42415edc07b157e59128105404e81098` (advanced since last round's `fe3ffa5f`) | — | clone deleted |
| ECC (scratch) | detached | `07756cee15788a54506031462794ad645719b028` | — | clone deleted |

Read at those refs: `ENGINEERING_STACK_REUSE_PLAN.md`, `CURRENT_TRUTH.md`,
`ENGINEERING_ORCHESTRATOR_V1.md`, `DEV_TEAM_V1_PILOT.md` (product memory `5d0bd4da`); accepted Builder
`docs/DEV_ENVIRONMENT.md` and `docs/dev-environment/CLAUDE_PROJECT_LAYOUT.md` (builder `295e483`);
previous outbox (bridge `91455ce`). ECC fetched with `git fetch --depth 1 origin <sha>` into
`/tmp/ecc-scratch` (65 MB excluding `.git`, no `npm install`, nothing executed from it).

**Scanner used:** the Builder's existing SkillSpector 2.11.2 at `.tooling/bin/skillspector`, `--no-llm`
(`llm_requested=false`, `filtering_mode=heuristic`). As CURRENT_TRUTH already records, this install is
the older local-path one: `direct_url.json` is `{"url":"file:///tmp/_skills/skillspector","dir_info":{}}`,
so `dev_env.py doctor` reports the expected single `FAIL` (skillspector commit unverifiable). The uv
cache checkout it was built from is at `d162d9b343e559be13df8ebba093df3bc9d58c90`, which matches the
pin by inspection, but the tool venv itself cannot prove it. `doctor` was run read-only; everything
else in it was `ok`.

## 3. Provenance and scan evidence

**ECC commit:** `07756cee15788a54506031462794ad645719b028`, author "Affaan Mustafa", 2026-09-19
02:58:33 -0400, subject "fix(gateguard): gate ref- and history-destroying git commands (#3154, #3151)
(#3170)". `VERSION` 2.2.1. License MIT (repo root). Plugin manifest: 68 agents, 292 skills, 94 legacy
command shims, 26 hook registrations across 8 events; 606 JS files; hook runtime = 55 scripts
(12,018 lines) + 75 lib files (19,781 lines); 4 runtime npm deps (`@iarna/toml`, `ajv`, `js-yaml`,
`sql.js`). `install.sh` runs `npm install` on first use then a Node installer that writes
`~/.claude/` (global user scope). `mcp-configs/mcp-servers.json` catalogues 36 servers, most as
`npx -y <pkg>` or `@latest` (unpinned) with placeholder credentials; repo `.mcp.json` enables
`chrome-devtools`.

**Content digests at the pinned commit (sha256), so the Director can pin exactly what was audited:**

| File | sha256 |
|---|---|
| skills/agent-architecture-audit/SKILL.md | `64f57e232c3533877403703bc95b3c75df9de23f657899a306f13c703009ff57` |
| skills/agent-harness-construction/SKILL.md | `e7fb390a6663b46ea5d3c2876753a5ce32ba3bad1889686b21a42894caa1742d` |
| skills/agent-eval/SKILL.md | `57fa683e356b6f5612bc6d7dc101ae39c126e6edf9a48f4ec53afea3e80d7e5d` |
| skills/ai-regression-testing/SKILL.md | `83f2f5c4083af5762dd658f742d4a390eb3a6f969d835f69e8f47efba296c127` |
| skills/automation-audit-ops/SKILL.md | `71aa878fd06ef02f0c8ca50eaaee0ec45995981d769d8701806b9b83ca8a2f2c` |
| skills/benchmark-methodology/SKILL.md | `753d54bbdb61aee7bba5b1d2df1b1d63eecef176b33aa2bc4924b3a6cb76a90e` |
| skills/security-review/SKILL.md | `fe6f9151fb15c1dffd47a55080c3ad147af7c95dd0ad3714735dec6824b060b7` |
| skills/security-review/cloud-infrastructure-security.md | `7d9a83852475a9396e04c59c73df84ac24ee0f41322016de7c11c62138c2a8ca` |
| skills/tdd-workflow/SKILL.md | `f5d8543733c557f0c53b688d40f14e9b870a6b2c7e405bab07433954e363828a` |
| skills/verification-loop/SKILL.md | `f0d56107f79e607d4de6c5543b8edfb1b58ab9ae4019b39831689cd91116543e` |
| skills/unified-memory/SKILL.md | `c42e96155783a44a50f13ab63e9d7f33c9d03b7a1f30777ef434401469c1630a` |
| skills/gateguard/SKILL.md | `88bd35f474aedac3aa20ce1ab529a84f65daf4d2b3d9f63f28e7e1b78e897f2b` |
| hooks/hooks.json | `df36c0945deb2ea0834fc1ffeec3c48d83bdb5b85c3324c687fe15b267c844cf` |
| hooks/hooks.metadata.json | `2d364ca7ccbb4dacb2e2eaeb16f16042588f4dbbf9ba20c13339e145253de338` |
| scripts/hooks/gateguard-fact-force.js (1,471 lines) | `005ce7a81dc30bae5e3320a005b49bab47add0d4db49607e85f66601503e19d9` |
| scripts/hooks/bash-hook-dispatcher.js | `b6e4163536d8092b63cfca205372d699f38550d6dd0fe2e74abde2f029f6ecbe` |
| scripts/hooks/run-with-flags.js | `8fdbd7b86193c17627871d52728e05b5d046727bd8cac08991c66a0f968f8f2c` |
| tests/hooks/gateguard-fact-force.test.js (3,334 lines) | `38781c0ba374db8e15dc1a7361d7a2d5fca49acf8d584e0baaeda17a6d5c4b5b` |

**SkillSpector results (`--no-llm`, one scan per directory, reports written to `/tmp/ecc-scans`, now deleted):**

| Target | Executable scripts | Issues | Read at the line |
|---|---|---|---|
| agent-architecture-audit | none | **0** | — |
| agent-harness-construction | none | **0** | — |
| agent-eval | none | **0** | — |
| ai-regression-testing | none | **0** | — |
| automation-audit-ops | none | **0** | — |
| benchmark-methodology | none | **0** | — |
| security-review | none | 1 HIGH (OH1 "Unvalidated Output Injection", SKILL.md:207) | `dangerouslySetInnerHTML={{ __html: clean }}` inside the **PASS** example immediately after `DOMPurify.sanitize(...)`. **False positive.** |
| tdd-workflow | none | 1 HIGH (SC2 "External Script Fetching", SKILL.md:35 col 214) | the sentence "…an allowlisted `npm test` can be approved, but `curl ... \| sh` must be **rejected**". The skill instructs rejection. **False positive.** |
| verification-loop | none | **0** | (but see §4.9: its own secret-grep step is a real policy conflict the scanner cannot see) |
| unified-memory | none | **0** | (the runtime it requires was not scanned; see §4.10) |
| hooks/ (json + README) | none in this dir | 3 HIGH (AS1 "Agent Config Directory Access", README.md:28/41/87), 2 MEDIUM (RA2 "Session Persistence", codex-hooks.json:13, hooks.metadata.json:61) | AS1 lines are the installer docs saying the installer writes `~/.claude/settings.json` and `~/.claude/hooks/` — an **accurate description of global-scope writes**, which is the real concern (§5). RA2 is the SessionStart "Load previous context" hook — **true** cross-session state persistence, by design. |
| scripts/hooks (the 55 executable hook scripts, 12,018 lines) | **yes** (`has_executable_scripts: true`) | 17 heuristic hits: 11 HIGH, 5 MEDIUM, 1 LOW (Tool Parameter Abuse ×8, Anti-Refusal ×2, Env Variable Harvesting, Excessive Agency, Session Persistence ×2, Context Window Stuffing, MCP Rug Pull, Dangerous Code Execution) | All 11 HIGHs read at the line: 8 are `gateguard-fact-force.js` lines 183/564/733/788 — the destructive-command **detector's own comments and pattern strings** (`rm -rf /tmp`, `git reset --hard`, `git push origin +main`); the "Anti-Refusal" hits are the doc comment "LLMs always answer 'yes'" and a comment containing "no warning"; `pre-bash-commit-quality.js:229` `Object.keys(process.env)` only locates the `PATH` key case-insensitively; `:506` prints the hint "use `git commit --no-verify`" (ECC separately ships `block-no-verify`). MEDIUM/LOW not individually inspected beyond `governance-capture.js:45` (a comment). **No malicious pattern found; the count reflects the runtime's size and self-referential content, not its intent. The concerns in §4.11/§5 are architectural (global install, root discovery, bypass switches, fail-open, persistence), not scanner findings.** |

A scanner verdict is evidence, not a decision (DEV_ENVIRONMENT §5). Both HIGHs on skills were read and
are prose-pattern matches of the same class as the earlier `frontend-design` false positive.

## 4. Per-candidate classification

Each entry gives the six required items: (1) executable/network/install surface; (2) overlap with
existing CROOKS Builder and canonical contracts; (3) conflicts or authority widening; (4) concrete
value; (5) exact safe integration form; (6) provenance/scan evidence (digests and scan rows are in §3).

### 4.1 `agent-architecture-audit` — **ADOPT STATIC CONTENT**
1. Single 16 KB SKILL.md. No scripts, no network, no install. Frontmatter `origin: oh-my-agent-check`
   (third-party-derived content redistributed under ECC's MIT; upstream not independently verified) and
   `tools: Read, Write, Edit, Bash, Grep, Glob`.
2. No existing CROOKS skill covers it. It fits the `safety-reviewer` / read-only specialist slots in
   CLAUDE_PROJECT_LAYOUT §5 and the Orchestrator's "architecture / difficult diagnosis" review class.
3. None material. The frontmatter grants Write/Edit to a diagnostic skill; strip to Read/Grep/Glob/Bash
   for a reviewer. "MANDATORY for releasing" wording is advisory prose, not authority.
4. High. CROOKS *is* an agent stack (Agent SDK child, tool routing, KB retrieval, proposal/action
   gating, TTS rendering). The 12-layer table and the fix order "code-gate tool requirements, never
   prompt text" restate DEC-005/DEC-007 doctrine; the report schema is a usable review artifact.
5. Vendor `SKILL.md` unchanged except frontmatter `tools:` narrowed, at
   `.claude/skills/agent-architecture-audit/`, with digest `64f57e23…` and the ECC commit recorded in
   `DEV_ENVIRONMENT.md` §5.1's table. Re-scan what lands.
6. 0 issues; digest above.

### 4.2 `agent-harness-construction` — **ADOPT STATIC CONTENT** (as reference, low weight)
1. 8 KB SKILL.md, no scripts/network/install.
2. Overlaps loosely with CROOKS capability-manifest design (`logs/capabilities.json`) and with the
   Orchestrator's tool/adapter design.
3. None.
4. Modest but clean: observation shape `{status, summary, next_actions, artifacts}`, "micro-tools for
   high-risk operations", "keep system prompt minimal, move guidance into on-demand skills" — the same
   principle CLAUDE_PROJECT_LAYOUT §2 already applies.
5. Vendor as a reference document (not a triggered skill) under `docs/dev-environment/reference/` or
   fold three bullets into `.claude/rules/`. No runtime.
6. 0 issues; digest above.

### 4.3 `agent-eval` — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC** (methodology yes, tool no)
1. 12 KB SKILL.md, no scripts — but it is a *wrapper* for an external CLI
   (`github.com/joaquinhuigomez/agent-eval`, "install from its repository after reviewing the source").
   That tool was **not** fetched or scanned. Frontmatter grants Write/Edit/Bash.
2. It is exactly the plan's P0 "evidence-based model/worker benchmark": YAML task, pinned base commit,
   per-run git worktree, ≥3 trials, pass rate/cost/time/consistency, deterministic judge first.
3. Its "LLM-as-judge" judge type conflicts with "what counts as VERIFIED is not outsourced"; allow it
   only as an advisory column, never for pass/fail.
4. High as a specification; the tool itself is an unreviewed third-party install and CROOKS already has
   worktree machinery.
5. Write `bench/` task schema and a small runner in the Builder (Python, stdlib) reusing existing clone
   isolation; deterministic judges = pytest/ruff/browser gate; record model/version/effort/base SHA per
   attempt (Orchestrator §10 manifest). Do **not** install `agent-eval`.
6. 0 issues; digest above.

### 4.4 `ai-regression-testing` — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC**
1. 16 KB SKILL.md, no scripts/network/install. Examples are Next.js/Vitest/Supabase.
2. Already partly practised: BE-01…BE-04 each got a named regression test (DEV_ENVIRONMENT §9).
3. None. It explicitly says "don't aim for coverage percentage", which is consistent with
   DEV_ENVIRONMENT §6 and *inconsistent* with `tdd-workflow`'s 80% mandate (§4.8).
4. Medium-high: the same-model blind spot (implementer reviewing its own fix), "test where bugs were
   found", sandbox/production parity (CROOKS: fixture world vs live), name tests after bug IDs, run
   tests before AI review.
5. Fold ~15 lines of principles into `.claude/rules/testing.md`; drop all JS code.
6. 0 issues; digest above.

### 4.5 `automation-audit-ops` — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC**
1. 12 KB SKILL.md, no scripts/network/install. References six ECC-native skills by name
   (`workspace-surface-audit`, `knowledge-ops`, `github-ops`, `ecc-tools-cost-audit`, `research-ops`,
   `verification-loop`) — coupling to the ECC catalogue.
2. Its method is what the last three bridge rounds did by hand: inventory the live surface, classify
   each item configured / authenticated / recently verified / stale-broken / missing, cite a proof
   path, end with keep / merge / cut / fix-next. §6 below uses it.
3. None.
4. Medium: a repeatable checklist for runtime/automation reconciliation rounds.
5. Rewrite as a ~40-line CROOKS "runtime inventory" checklist (in `docs/ENGINEERING_LOOP.md` or a
   project skill) with the ECC skill references removed.
6. 0 issues; digest above.

### 4.6 `benchmark-methodology` — **REJECT** (wrong domain)
1. 16 KB SKILL.md, no scripts; `license: MIT`.
2. None. It is a **marketing competitor-scoring rubric** (nine weighted dimensions: positioning, brand
   voice, visual craft, offer packaging, pricing…; sits between `competitive-platform-analysis` and
   `competitive-report-structure`). It has nothing to do with engineering or model benchmarking; the
   reuse plan's inclusion is a name match.
3. None, because it does not apply.
4. None for the harness. (If Marketing ever wants it, that is a separate, non-engineering decision.)
5. Nothing. The benchmark need is covered by §4.3.
6. 0 issues; digest above.

### 4.7 `security-review` — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC** (do not vendor)
1. 32 KB across SKILL.md and `cloud-infrastructure-security.md` (361 lines, AWS/IAM/Terraform). No
   scripts/network/install.
2. Overlaps with, and is weaker than, CROOKS' existing specific invariants (PRODUCT_BRAIN §9,
   DEC-005/006/007/020/027, DESIGN.md "no external resources") and existing tools (gitleaks, trivy).
3. **Real conflict:** §10 "Dependency Security" instructs `npm audit fix`, `npm update`, "Dependabot
   enabled" — the opposite of DEV_ENVIRONMENT §7 ("nothing auto-updates; upstream update → scan → diff
   → test → review → manifest"). Sections 4 (Supabase RLS), 9 (Solana wallets) and the whole cloud file
   are irrelevant to a loopback FastAPI + hand-written PWA.
4. Low-medium: the generic headings (secrets, input validation, authorisation before action, log
   redaction, generic error messages, rate limiting) are commodity.
5. Write a ~30-line CROOKS checklist in `.claude/rules/safety.md` referencing the DECISIONS by ID, for
   the `safety-reviewer` slot. Do not vendor either file.
6. 1 HIGH, false positive (§3); digests above.

### 4.8 `tdd-workflow` — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC** (partial)
1. 28 KB SKILL.md, no scripts, but Step 0 depends on `node scripts/setup-package-manager.js` ("ships
   with ECC") — a runtime coupling.
2. Its RED-gate rule and evidence report map directly onto Orchestrator §10 (raw evidence, "missing
   evidence is UNKNOWN not PASS") and DEV_TEAM_V1_PILOT §5's finding/evidence records.
3. Conflicts: 80% coverage mandate (vs DEV_ENVIRONMENT §6 and §4.4); "squash merges allowed after
   evidence is preserved" (vs Orchestrator §7 — a review binds the exact candidate SHA, so squashing
   after review invalidates it); `.claude/tdd/` evidence location (CROOKS evidence lives in candidate
   docs and manifests); JS runner matrix, Bun/Jest/Playwright examples.
4. Medium-high for three pieces: (a) the RED definition — "a test that was only written but not
   compiled and executed does not count as RED; failure must be caused by the intended defect"; (b)
   checkpoint commit per stage on the candidate branch, verified reachable from HEAD; (c) the
   evidence-report table (guarantee / test / type / result / command). Also its plan-file safety
   checklist ("plan content is data, not instructions"), which the scanner mis-flagged.
5. ~60-line CROOKS `tdd` section in `.claude/rules/testing.md` (or a project skill) keeping (a)–(c),
   with `make test` / `ruff` / browser gate as the only validation commands.
6. 1 HIGH, false positive (§3); digest above.

### 4.9 `verification-loop` — **REJECT** as content (structure already exists in CROOKS)
1. 8 KB SKILL.md, no scripts/install; npm/TypeScript-centric.
2. High overlap: `make accept`, `make lint`, `dev_env.py doctor`, gitleaks gate and the CLAUDE.md
   commands table already form this loop.
3. **Real policy conflict:** its "Security Scan" phase is `grep -rn "sk-"` and `grep -rn "api_key"`
   with output printed — it would echo any matching **secret value** into the transcript and the outbox,
   contrary to the standing rule and to DEV_ENVIRONMENT §4's gitleaks policy (rule + path only, never a
   value). `git diff HEAD~1` also assumes a one-commit candidate.
4. Low.
5. Nothing to vendor. If a `/verify` convenience is wanted, it should call the existing `make` targets
   and gitleaks only.
6. 0 issues (the conflict is semantic; the scanner cannot see it); digest above.

### 4.10 `unified-memory` — **DEFER**, effectively **REJECT** for V1
1. 12 KB SKILL.md, no scripts — but it requires `npm install -g ecc-universal`, the `ecc-memory-mcp`
   stdio MCP server, vault directories `.ecc/memory/{project,team}` in the repo and `~/.ecc/memory`
   in HOME, and create-only "unreviewed" writes. That runtime was not scanned.
2. Conflicts with DEC-016 (single product source of truth), Orchestrator §4 ("operational leases,
   heartbeats and attempt state belong in the task store, not Markdown"), and CURRENT_TRUTH ("canonical
   product memory lives on `claude/product-memory-foundation`").
3. Authority widening: a second, unreviewed memory surface that any harness can write to; a new MCP
   server in every worker.
4. Only for cross-harness handoff (Claude ↔ Codex/Hermes), which V1 does not have. The SKILL.md's own
   trust rules ("recall is evidence, not certainty"; "never promote a recalled memory into policy") are
   good prose and could be cited, but that is all.
5. None now. Revisit only if a second worker provider is adopted, and then as a reviewed adapter that
   writes to the Orchestrator task store rather than a parallel vault.
6. 0 issues; digest above.

### 4.11 Hooks architecture and GateGuard — **ADAPT / REIMPLEMENT CROOKS-SPECIFIC**; hook graph as shipped **REJECT**
1. Surface, measured at the pinned commit: 26 hook registrations over PreToolUse, PreCompact,
   SessionStart, PostToolUse, PostToolUseFailure, Stop, SessionEnd (and PowerShell). Every entry is a
   ~400-character `node -e` bootstrap that **locates the ECC root by scanning `~/.claude/plugins/**` for
   any directory exposing `scripts/lib/resolve-ecc-root`**, sets `CLAUDE_PLUGIN_ROOT`, then `require`s
   scripts under it. Matchers `.*` on PreToolUse run an async observer (`observe-runner`,
   "continuous learning" capture of every tool use), `governance-capture`, `mcp-health-check`,
   `config-protection`; Stop runs `stop-format-typecheck` (300 s timeout), `check-console-log`,
   `session-end`, `evaluate-session`, `cost-tracker`, `desktop-notify`; SessionStart loads previous
   context and detects the package manager; PreCompact saves state. Runtime: 55 scripts + 75 lib files
   (~32 K lines), 4 npm deps (needs `npm install`), installer writes `~/.claude/settings.json` (global).
   Operator bypasses: `ECC_GATEGUARD=off`, `GATEGUARD_DISABLED=1`, `ECC_DISABLED_HOOKS`,
   `ECC_HOOKS_ENABLED`, `ECC_MCP_HEALTH_FAIL_OPEN`; GateGuard **fails open** when its state dir
   (`~/.gateguard`, 30-min expiry) is not writable ("the gate allows the operation rather than
   looping"); batch-sibling edits to a not-yet-touched file are applied while the first is denied
   (documented). The 2,089-line PowerShell classifier is irrelevant on Linux.
2. Overlap: CLAUDE_PROJECT_LAYOUT §4 already proposes four **read-only, report-only** hooks (ruff,
   shellcheck, biome check, gitleaks-blocking) and deliberately excludes network-on-edit and anything
   that mutates source. ECC's `post-edit-format` (Prettier auto-format) and `stop-format-typecheck`
   are exactly what §4 excludes.
3. Conflicts: (a) a Bash-text hook is a **nudge, not a boundary** — it is bypassed by `python3 -c`,
   `sh -c`, aliases or encoding, and ECC's own 3,334-line test file documents that arms race; CROOKS'
   real boundaries are the watcher's systemd sandbox (`ProtectSystem=strict`, `ReadWritePaths`), the
   permission layer (`acceptEdits`, never `bypassPermissions`) and the builder/production directory
   split; (b) the global `~/.claude` install conflicts with the accepted project-scoped layout and
   with DEV_ENVIRONMENT §5.2's rejection of global-scope installers; (c) the plugin-root discovery by
   directory scan means whichever `~/.claude/plugins/**` entry resolves first supplies the code that
   runs on every tool call — a hijack surface; (d) env-var bypasses and fail-open defaults invert
   the CROOKS "fail closed" rule; (e) observer/session-persistence hooks write tool inputs (which can
   carry secret-bearing command lines) and session state under HOME, conflicting with sanitisation and
   with "operational state belongs in the task store".
4. **Concrete value, and it is real:** `isDestructiveGit()` + `findGitSubcommand()` in
   `gateguard-fact-force.js` (about lines 436–670; ~160 lines, pure, no I/O) — the subject of the
   pinned commit. It gates `reset --hard`, `checkout -- / . / -f`, `clean -f*`, `push --force` (and
   `--force-with-lease` when the destination is `main`/`master`/`develop`/`trunk`), `commit --amend`,
   `rm -rf`, `branch -D` / `--delete --force`, `stash drop|clear`, `reflog expire|delete`,
   `update-ref -d`, `restore` against the worktree, `switch --discard-changes|-f|-C`; handles
   `-c/-C/--git-dir` global options, `+refspec`, `refs/heads/` prefixes, quoted strings, `$(…)` and
   backtick subshells and heredoc bodies. Plus the "destructive command must state its targets and a
   one-line rollback" prompt shape, which is a good `additionalContext` payload.
5. Safe form: **reimplement, do not import.** `crooks-assistant/scripts/hooks/guard_bash.py`
   (stdlib only, ≤200 lines) registered as a project-scoped PreToolUse hook on `Bash` per
   CLAUDE_PROJECT_LAYOUT §4: fail closed on unparseable or oversized input, **no disable environment
   variable**, deny list = the ported `isDestructiveGit` table + a CROOKS path/command guard
   (`/opt/crooks-os`, `/etc/crooks-os`, `/etc/systemd`, writes under `/root/.claude`,
   `tailscale serve|funnel`, `systemctl start|enable|restart`, `make install|secrets`, `git push` to
   any production/product-memory ref), returning `additionalContext` that asks for targets + rollback
   line when a command is merely risky. Port a subset of ECC's test vectors into
   `tests/test_guard_bash.py` as fixtures (cite the digest). Explicitly **not** ported: observer /
   learning, Stop-time formatters and type-checkers, desktop-notify, mcp-health, session persistence,
   config-protection, the `node -e` bootstrap, the npm runtime.
6. hooks/ scan: 3 HIGH + 2 MEDIUM, all read and explained in §3; scripts/hooks scan: see §3 row;
   digests above.

## 5. Is any full ECC plugin/runtime/hook installation justified? **No.**

- Everything worth adopting (§4.1, §4.2, and the methodology in §4.3–4.5, §4.8) is **markdown with no
  executable scripts**; the one piece of code worth having (§4.11 item 4) is ~160 pure lines that are
  cheaper to port with tests than to host inside a 32 K-line runtime.
- The installer needs `npm install` and writes **global** `~/.claude/settings.json` and hook scripts —
  the same class of finding on which `web-interface-guidelines`' installer was rejected
  (DEV_ENVIRONMENT §5.2) and which the accepted project-scoped layout forbids.
- The hook graph resolves its own code by scanning `~/.claude/plugins/**`, carries operator bypass
  variables and fail-open paths, and persists per-tool-call observations and session state under HOME.
- The MCP catalogue is 36 servers, mostly `npx -y` at `@latest` with placeholder credentials — the
  unpinned-fetch vector DEV_ENVIRONMENT §5.2 already names.
- The plugin declares 292 skills / 68 agents / 94 command shims; installing it would put a large,
  mostly irrelevant instruction surface (business, prediction-market, media, supply-chain, i18n docs)
  into every engineering session — the "context/tool pollution" the reuse plan's success measure
  counts against.
- Cost/benefit: selective vendoring plus one reimplemented hook captures the value with ~0 executable
  surface, ~0 new dependencies, and provenance the Builder's existing gate can verify.

## 6. Inherited MCP connectors and tool surface in headless engineering sessions

**How the session is launched (from the installed unit and `bin/crooks-bridge-watcher` `run_claude`):**
`HOME=/root`, `cd /opt/crooks-builder`, prompt on stdin,
`claude --print --model claude-fable-5-1 --effort high --permission-mode acceptEdits --allowed-tools Read,Edit,Write,Glob,Grep,Bash`.
Claude Code 2.1.276.

**Observed exposure — in this session, by tool name and schema in the roster:**

| Source | What was loaded | Examples of mutating tools present |
|---|---|---|
| claude.ai connector: Gmail | 30 tools | `send_message`, `reply`, `forward`, `trash_thread`, `delete_draft`, label changes |
| claude.ai connector: Shopify | 42 tools | `create-product`, `update-product`, `set-inventory`, `create-discount`, `bulk-update-product-status`, `graphql_mutation` |
| claude.ai connector: Google Drive | 11 tools | `share_file`, `trash_file`, `update_file`, `create_file` |
| claude.ai connector: Resend | ~150 tools | `send-email`, `send-broadcast`, `create-api-key`, `remove-domain`, `revoke-oauth-grant` |
| claude.ai connector: Omnisend | 7 tools | `omnisend_create/update/delete` |
| claude.ai connector: Claude Docs | 6 tools | doc create/update |
| claude.ai connectors needing auth (not usable, still listed) | 14 | Base44, Figma, Linear, Notion, Slack, Atlassian, Intercom, HubSpot, Klaviyo, Canva, Ahrefs, Amplitude ×2, Supermetrics; Wix MCP; Similarweb failed to connect |
| account-synced plugins (`/root/.claude/plugins/synced/…`) | `design`, `marketing`, `base44`, `wix` — skills exposed as `design:*`, `marketing:*`, `base44:*`, `wix:*` slash commands; `design` and `marketing` manifests declare 9 and 13 connector MCP servers respectively; `wix` declares `wix-mcp` | — |
| other | `anthropic-skills:*` plugin skills; official marketplace with 45 plugins available; built-in `Agent`, `Workflow`, `WebFetch`, `WebSearch`, cron/schedule tools (none in the allowed list) | — |

**Where it comes from — not local configuration.** `/root/.claude.json` has `mcpServers: {}` globally
and for all three recorded projects (`/opt/crooks-os`, `/root`, `/opt/crooks-interactive`);
`enabledMcpjsonServers` empty; no `.mcp.json` in the Builder; `/root/.claude/settings.json` is
`{"theme":"dark"}`; no project or local settings files. The connectors and plugins arrive with the
**claude.ai Max account** whose login lives in `/root/.claude/.credentials.json`
(`claudeAiMcpEverConnected`, account plugin sync enabled). Because the watcher runs as root with
`HOME=/root` (needed for the OAuth refresh, per the unit's own comment), every headless engineering
run inherits the owner's personal connector grants.

**`--allowed-tools` does not narrow this.** Its help text is "list of tool names to allow"; it
auto-approves those tools under `acceptEdits`, it does not remove others from the roster.

**Probe (one call, read-only, non-business):** I invoked the Claude Docs `guide` tool with
`["topic.index"]` (Anthropic's documentation index; no business data, no external mutation). Result:
**refused by the permission layer** — "Claude requested permissions to use
mcp__claude_ai_Claude_Docs__guide, but you haven't granted it yet." I did not retry or seek a way
around it. So in the current launch mode an unattended connector invocation is **denied because nobody
can answer the prompt**; no business connector was invoked by this round.

**Why it still matters.**
1. The schemas are loaded on every turn (context cost) and are a concrete target for prompt injection
   from repository, inbox, log or fixture text; the model can be steered to *attempt* them.
2. The only thing stopping execution is prompt-denial behaviour, which disappears the moment permission
   mode is widened to `bypassPermissions` (the unit calls that "an owner decision, not a default") or
   a `--permission-prompt-tool` host auto-approves. Engineering permission must never grant business
   action permission (Orchestrator §2 safety contract) — today that separation is accidental.
3. ENGINEERING_STACK_REUSE_PLAN P0: "prove the effective MCP/tool surface at launch rather than
   trusting prompt text" — it is currently unproven, and this round shows the proof would fail.
4. Orchestrator §8 already states the shared `/root` home is not an isolation boundary; this is the
   concrete consequence.

**Safe isolation design (nothing applied; layered, cheapest first):**

| Layer | Change | Owner of the change | Verification |
|---|---|---|---|
| 1. Launch flags (watcher only) | add `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` ("Only use MCP servers from --mcp-config, ignoring all other MCP configurations"; the `--restricted` help confirms it "skip[s] MCP servers too"); `--permission-prompts none` (explicit auto-deny instead of implicit); `--disallowed-tools WebFetch,WebSearch,Agent` unless a task contract allows them; `--setting-sources project`; `--disable-slash-commands` or an explicit `--plugin-dir` allow-list instead of account sync | unit file edit → owner or an explicitly approved inbox | must be tested empirically: whether `--strict-mcp-config` also suppresses **account** connectors (as opposed to file-configured servers) is not documented in the help text and was not tried here |
| 2. Identity | a dedicated engineering login in a dedicated HOME (e.g. `/var/lib/crooks-worker/home`) for an account/workspace with **no** claude.ai connectors and no synced plugins; or API-key auth with `--bare` (drops OAuth, plugins, hooks and auto-discovery entirely — needs a provisioned key and spend) | owner: account/secret provisioning; unit `Environment=HOME=` | roster check (layer 3) |
| 3. Proof at launch | watcher runs the session with `--output-format stream-json`, reads the `system/init` message's `tools` and `mcp_servers`, and **fails closed** if any `mcp__*` tool or unexpected plugin is present; records the roster digest in the outbox | watcher source change (reviewed candidate; watcher has a test harness) | deterministic, testable with fake init messages |
| 4. Account | owner reviews claude.ai connector/plugin grants on the account used by the server; consider a separate automation seat | owner only | — |

Layer 3 is the one that turns "trust the prompt text" into evidence and should be built regardless of
which of layers 1–2 is chosen.

## 7. Ranked shortlist

| # | Candidate | Class | Why this rank |
|---|---|---|---|
| 1 | GateGuard `isDestructiveGit` table + prompt shape (§4.11) | REIMPLEMENT | Highest value per line, fresh at the pinned commit, large test corpus to port, zero runtime |
| 2 | `agent-architecture-audit` (§4.1) | ADOPT STATIC | Directly applicable to the CROOKS assistant; 0 issues; needs only a frontmatter edit |
| 3 | `agent-eval` methodology (§4.3) | ADAPT | Is the P0 benchmark spec; no install |
| 4 | `ai-regression-testing` + `tdd-workflow` RED-gate/evidence report (§4.4, §4.8) | ADAPT | Small rule-file additions with real review value |
| 5 | `automation-audit-ops` classification ladder (§4.5) | ADAPT | Formalises the reconciliation rounds |
| 6 | `agent-harness-construction` (§4.2) | ADOPT STATIC (reference) | Clean, small, low urgency |
| 7 | `security-review` (§4.7) | REIMPLEMENT (30 lines) | Content is wrong stack and conflicts with the pin policy |
| 8 | `verification-loop` (§4.9) | REJECT | Already exists as `make` targets; secret-grep conflicts |
| 9 | `unified-memory` (§4.10) | DEFER→REJECT | Runtime + parallel memory; no V1 need |
| 10 | `benchmark-methodology` (§4.6) | REJECT | Marketing rubric, wrong domain |
| — | ECC plugin / runtime / hook graph / MCP catalogue | REJECT | §5 |

## 8. Smallest safe next integration experiment (research gate 2 of the reuse plan)

On an isolated branch from the accepted Builder commit `295e483` (e.g. `claude/harness-hooks-experiment`),
with no production, service, secret or settings change:

1. Apply CLAUDE_PROJECT_LAYOUT §0 (`.gitignore` `.claude/*` + negations) and the minimum of §1–§4:
   short `CLAUDE.md`, `.claude/rules/{safety,testing,builder-vs-production}.md`, `.claude/settings.json`
   with exactly two hooks — gitleaks (blocking, rule + path only) on commit/publish commands and the
   new `scripts/hooks/guard_bash.py` on `Bash`.
2. `guard_bash.py` + `tests/test_guard_bash.py`: port the `isDestructiveGit` decision table and a
   subset of ECC's vectors (cite commit and digest), add the CROOKS path/command guard, fail closed,
   no bypass variable. Acceptance: negative cases denied (`git reset --hard`, `git push --force` to any
   ref, `git branch -D`, `rm -rf` under `/opt/crooks-os`, `tailscale serve …`, `systemctl start …`,
   `make install`), positive cases allowed (`git status`, `make test`, `ruff check`), unparseable input
   denied.
3. Vendor `agent-architecture-audit` at digest `64f57e23…` with `tools:` narrowed; re-scan what landed
   with the Builder's SkillSpector gate and record it in `DEV_ENVIRONMENT.md` §5.1.
4. Deliver, as **proposals only** (not installed): the watcher launch-flag change (layer 1) and a
   roster-assertion test for layer 3.
5. Evidence: `make test` + the new tests, ruff, gitleaks over the candidate, the exact candidate SHA.

**Precondition that is an owner decision:** the previous round found writes to
`/opt/crooks-builder/.claude/` **refused by the permission layer** (DEV_ENVIRONMENT §8). This experiment
needs that refusal resolved explicitly (an inbox that grants it, plus whatever permission change the
owner approves). If it is refused again the worker must report BLOCKED, not route around it.

## 9. What I changed, and state

**Changed:** this file only. No commit, checkout, switch, reset, fetch into an existing repo, push,
merge or tag anywhere. No install of ECC or any npm/pip package. No service, Tailscale, systemd,
secret, permission, Claude-settings or MCP change. No business connector invoked (the one probe in §6
was a non-business documentation tool and was refused).

**Scratch state:** `/tmp/ecc-scratch` (ECC at the pinned commit), `/tmp/pmf-scratch` (product-memory
shallow clone) and `/tmp/ecc-scans` (SkillSpector reports) were created and **deleted before
stopping**. Network use: one shallow clone of product memory and one depth-1 fetch of the ECC commit
from GitHub; SkillSpector's SC4 supply-chain check may have queried `api.osv.dev` with coordinates
only (all ten skills have no dependency files, so likely nothing was sent).

**Repository state (end of round):** see §2 table. **Production branch HEAD:
`1cf3a0f3361b79f9de208d80f501543c53c244b5` — unchanged.** Files changed this round:
`bridge/claude-outbox.md` only.

**Tests:** none of the CROOKS suites run (read-only round). Run: `dev_env.py doctor` (read-only; result
1 FAIL = the expected SkillSpector-provenance check, all else ok, browser gate AVAILABLE) and eleven
SkillSpector `--no-llm` scans plus one over `scripts/hooks` (§3).

**Service and server state (observed, unchanged):** `crooks-assistant.service` active,
`crooks-bridge-watcher.service` active (this run), `tailscaled` active. Listeners: `127.0.0.1:8000`
(assistant, loopback only), sshd 22, resolved 53, tailscaled 443 on tailnet addresses only. Nothing on
`0.0.0.0:8000`. `/health` was not called this round.

## 10. Errors, decisions and questions for review

- **Error/denial:** one permission-layer refusal (the §6 probe). Expected, recorded, not worked around.
- **Owner-only decisions surfaced (none taken):** (a) resolve the `.claude/` write refusal for the §8
  experiment; (b) approve the watcher launch-flag change (unit edit); (c) decide on a dedicated
  engineering login/HOME or API-key auth (provisioning + possible spend); (d) review the server
  account's claude.ai connector and plugin grants.
- **Director items:** the reuse plan lists `benchmark-methodology` under "highest-value skill
  candidates" — it is a marketing rubric and should be struck (§4.6). The plan's "hook ideas" list
  should say "port the destructive-git table" rather than "adapt the hook" (§4.11).
- **Standing discrepancies, untouched:** watcher unit branch `claude/bridge-builder` vs checkout
  `claude/builder-environment-repair`; Builder's SkillSpector install still the local-path one
  (`doctor` FAIL expected until reconciled per CURRENT_TRUTH); the Linux promotion ratify/reverse
  decision from the previous round remains with the owner.

## 11. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI bound to 127.0.0.1; port 8000 not
public; proposal/action/verification semantics untouched; no live Shopify, Gmail or ElevenLabs call
and no external mutation; V2 not begun; UI not redesigned; Mac deployment and rollback path untouched;
`/root/.claude` writable and not modified by me; no secret value read into, printed in or committed
with this handoff (config inspection redacted every key whose name suggested a credential). No
ECC or npm package installed; no persistent external account or service created; no money spent;
Orchestrator implementation not begun; nothing committed or pushed.

## 12. Stop

Round complete. Nothing further was done.

Inbox SHA processed: `4f5bfb5eaa32ef151a02c153a0ecbb548ea110b8`
