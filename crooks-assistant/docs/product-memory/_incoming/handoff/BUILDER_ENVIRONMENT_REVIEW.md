# Builder Environment — independent Director review

**Reviewed candidate:** `9a27bc441adad1e98e8a9ca257d1883246ee7eec`  
**Base:** `e43aecdb39b87b622f64b6ab434e428d216ef157`  
**Review date:** 2026-09-19  
**Verdict:** CHANGES REQUIRED before acceptance as a reproducible Dev Team foundation.

The published candidate is useful partial delivery: browser tooling and inventory are reported available on the existing builder, and the design/environment documents are versioned. It is not evidence of a complete, reproducible environment. This review makes no deployment change and issues no bridge instruction.

## 1. Scope and evidence standard

Git comparison confirms eight changed text files: root .gitignore, DESIGN.md, DEV_ENVIRONMENT.md, three supporting documents, manifest.json and scripts/dev_env.py. No application, web or existing test file changed in this candidate.

Independently examined the actual dev_env.py, committed manifest and supporting environment/configuration/browser-finding documentation. Reproductions imported the exact candidate script into a disposable local review directory. No bootstrap installation, package download, external API, live business operation, server SSH or secret access was performed.

The browser/pytest/skill-scan results below are builder-reported, not independently rerun here. A successful import or synthetic reproduction is not certification of the complete candidate.

## 2. Blocking findings

### BE-01 — bootstrap crashes on its own committed manifest
**Priority:** P1 — core promised operation fails  
**Location:** scripts/dev_env.py, cmd_bootstrap, lines 224–225

The binaries object includes a string-valued `$comment`. Unlike doctor, bootstrap does not skip metadata entries, and treats that string as a tool object.

**Reproduced:** calling cmd_bootstrap(load()) prints 18 lines and raises:

`TypeError: string indices must be integers, not 'str'`

No dependency installation is needed to reproduce this. The public command cannot complete with the committed inputs.

**Acceptance:** validate/filter manifest metadata consistently; run bootstrap's supported mode with the exact committed manifest; cover malformed entries and clean error reporting. An empty manifest or altered fixture is not a fix.

### BE-02 — doctor returns success with wrong versions and failed tools
**Priority:** P1 — unreliable environment precondition  
**Location:** scripts/dev_env.py, cmd_doctor, lines 100, 113, 125, 162, 172, 191

Only MISSING increments the failure count. Node/Python version mismatches and failed binary/tool commands produce WARN. Binary output is displayed alongside a desired version without comparing the two.

**Reproduced in a temporary fixture:**
- installed-version fixtures set to 0.0.0: nine version warnings, exit code 0, final summary `all present`;
- binary/uv help/version probes made to fail while browser prerequisites remain satisfied: nine failed-tool warnings, exit code 0.

This is a controlled test of the script's decision logic, not a claim that those tools are broken on the server.

**Acceptance:** explicitly separate required environment identity/health from advisory lint findings. Missing, failed or mismatched required tools must block. Verify expected versions/commits using tool-specific commands, with timeouts. Keep Biome/Pyright product-source warnings advisory where policy says so; that does not make a broken required executable acceptable.

### BE-03 — generated shell exports do not preserve literal paths
**Priority:** P2 security/correctness — conditional on checkout/environment text  
**Location:** scripts/dev_env.py, cmd_env, line 77

Python repr followed by quote replacement is not shell escaping. The documented eval usage interprets command substitution inside a generated double-quoted value.

**Harmless reproduction:**
- supplied checkout path: `/tmp/crooks-$(printf CROOKS_ENV_PROBE)`;
- expected NODE_PATH contains that literal directory name;
- actual NODE_PATH: `/tmp/crooks-CROOKS_ENV_PROBE/.tooling/node/node_modules`.

Only a fixed printf probe ran. No secret or external command was involved. No claim of exploitation or exposure on the existing builder.

**Acceptance:** use correct shell quoting, or replace eval-based consumption with a structured environment interface. Verify spaces, apostrophes, quotes, dollar signs, backticks and newlines round-trip without executing their content. Include PATH in the contract.

### BE-04 — a fresh checkout cannot reconstruct the reported environment
**Priority:** P1 — reproducibility gap  
**Evidence:** source and committed file inventory; fresh network bootstrap was not attempted

Beyond BE-01:
- bootstrap only prints instructions despite its install/idempotence contract;
- its first step assumes a pre-existing .tooling/node/package.json, but .tooling is ignored and no step generates that package file;
- binary installation is represented by comments listing versions/upstreams, not a complete install/check procedure;
- printed relative cd steps are not a coherent root-anchored sequence;
- sysroot packages resolve current distribution dependencies without a committed exact version/checksum inventory;
- complete dependency locks or equivalent resolved artifact identities are absent.

**Acceptance:** choose an honest interface: an actual explicit, idempotent installer, or a clearly named complete plan generator with a separately defined executor. Generate/commit all required inputs outside ignored mutable output; identify exact artifacts and integrity checks; use unambiguous paths; prove a clean isolated reconstruction and a second no-change run. Record necessary host prerequisites. Never widen the watcher sandbox to make the test pass.

## 3. Incomplete delivery and evidence limitations

- No skills, CLAUDE.md, .claude rules or hooks were installed. The outbox reports native permission refusal; it must not be bypassed through another tool, path or worker. Project configuration remains a separate blocked/deferred delivery.
- DESIGN.md is PROPOSED, not ratified. Its existing UI mechanisms must not override later explicit owner intent.
- The builder reports 593 browser checks with one reproducible Split press failure. Cause remains unattributed; keep it visible. A later decision to retire Split may supersede its behavioural tests, but must preserve relevant hit-testing, accidental speech activation and action-safety coverage.
- The builder reports 2806 passed / 8 skipped in serial and parallel runs; this is a different application/environment baseline from the Linux candidate's reported 2886 results. Counts must not be substituted for each other.
- Raw scanner, browser and timing artifacts are described as local ignored output. This review has not retrieved independently addressable, digest-bound raw artifacts. Require a durable evidence manifest before machine acceptance.
- DEV_ENVIRONMENT.md section 8 says the Impeccable scan did not finish, contradicting its section 5.3 and the outbox. Correct the status; do not infer an install/security approval from either summary.
- A clean reflog proves HEAD did not move, not that no working-tree bytes changed. Future production-untouched evidence should identify the actual observation method and its limits.

## 4. Current round handling

At 2026-09-19T06:38:39Z:
- bridge HEAD: `165c366c3132ef2dc3b42f3cc1ffaa5296b4af07`;
- current inbox: Mobile Experience V1, blob `24b713cce3d0e8c9ede3185ebef78cc107ece507`, published at 02:18:32Z;
- current outbox: Builder Environment result, blob `67e3da115963a1f5ba8e0b57ede74a00f5be2fb2`, acknowledging the preceding Builder inbox;
- no mobile review branch was listed.

The mobile instruction is unacknowledged. More than four hours since publication does not prove its process is running or stopped. Before sending a new task, obtain current watcher/attempt status and reconcile it; do not overwrite the inbox or launch a duplicate based solely on Git silence.

The watcher source's expected builder-branch guard and the mobile inbox's instruction to switch to a task branch also need reconciliation before the following round. A new isolated-worker design must not inherit incompatible branch assumptions.

## 5. Disposition

Retain the published candidate and its useful tooling evidence. Do not label the permanent environment complete or suitable for automatic provisioning of new workers yet.

Proposed next bounded foundation task: repair BE-01 through BE-04 and publish an exact evidence bundle. Queue only after the current mobile round is reconciled and appropriate execution authority exists. No instruction was dispatched by this review.

Use these demonstrated failures as a frozen acceptance fixture for Dev Team V1, rather than requiring faith in a worker's completion prose. See DEV_TEAM_V1_PILOT.md.
