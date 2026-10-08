# CROOKS Builder — development environment

**Scope:** the builder worktree (`/opt/crooks-builder`, branch `claude/bridge-builder`) only.
**Not** the production checkout at `/opt/crooks-os/crooks-assistant`, and **not** the
`crooks-assistant` service. Nothing described here runs in production, listens on a socket, or
needs a secret.

The machine-readable source of truth is **`docs/dev-environment/manifest.json`**. This file is the
prose around it: why each thing is here, what it may and may not do, and what is still missing.

```
python3 scripts/dev_env.py doctor      # is this the pinned environment       (read-only)
python3 scripts/dev_env.py env         # the exports a browser run needs      (read-only)
python3 scripts/dev_env.py plan        # the steps that rebuild it            (read-only)
eval "$(python3 crooks-assistant/scripts/dev_env.py env)"
```

All three are read-only. **`plan` prints a plan; it does not install anything** — see §9 for why
the command that used to be called `bootstrap` is not called that any more.

`doctor` **fails closed**. A tool that is missing, that will not run, or that reports a version
other than the pinned one is a failure and exits non-zero, so it can be used as a precondition.
A finding that genuinely cannot be decided here is printed as `advisory` **with the reason on the
same line**, and advisory findings never change the exit code. There is currently exactly one
(§9.3).

> **This file describes candidate `claude/builder-environment-repair`.** Candidate `9a27bc4` was
> independently reviewed and rejected with four blocking findings — BE-01 to BE-04 — recorded in
> product memory as `BUILDER_ENVIRONMENT_REVIEW.md`. §9 is what was repaired and what was proved.
> BE-04's last part needed an owner decision on package fetching; that decision was given on
> 2026-09-19 and §10 is the boundary it drew and the reconstruction it made possible. The
> regression tests are `crooks-assistant/tests/test_dev_env.py`.

---

## 1. Why this exists

Two problems, both observed in this round:

1. **The CROOKS browser harness was inert on this server.** `experience/browser.py` and the
   eleven scripts in `scripts/browser/` have always required Playwright and a Chromium at
   `chromium-1194`. Neither was installed here, and the builder had no `.venv` at all, so every
   browser check reported itself *skipped* — honestly, but it proved nothing.
2. **The environment lived in a chat.** Nothing recorded which versions were used or why, so it
   could not be rebuilt on a fresh server.

Everything below is pinned, and nothing self-updates.

---

## 2. Layout

| Path | Contents | Committed? |
|---|---|---|
| `.tooling/bin` | single static binaries | no — gitignored |
| `.tooling/node` | pinned npm project (Playwright, axe, Biome) | no |
| `.tooling/browsers` | Playwright's Chromium 1194 | no |
| `.tooling/sysroot` | Chromium's shared libraries, extracted locally | no |
| `.tooling/uv-tools` | isolated env for SkillSpector | no |
| `.tooling/scans` | SkillSpector reports | no |
| `crooks-assistant/.venv` | project venv + builder test tooling | no |
| `crooks-assistant/docs/dev-environment/manifest.json` | the pins | **yes** |
| `crooks-assistant/docs/dev-environment/node-package.json` | the npm project `plan` installs | **yes** |
| `crooks-assistant/docs/dev-environment/node-package-lock.json` | the resolved npm tree, with integrity hashes | **yes** |
| `crooks-assistant/docs/dev-environment/sysroot-packages.txt` | the 89 `.deb`s, as `name=version` | **yes** |
| `crooks-assistant/docs/dev-environment/sysroot-packages.sha256` | their digests | **yes** |
| `crooks-assistant/docs/dev-environment/binaries.sha256` | digests of the nine pinned binaries | **yes** |
| `crooks-assistant/docs/dev-environment/binary-assets.sha256` | digests of the eight upstream release assets they come from | **yes** |
| `crooks-assistant/scripts/dev_env.py` | doctor / env / plan | **yes** |
| `.tooling/downloads` | what step 4 fetches, before and after unpacking | no — gitignored |

`.tooling/` (~1.8 GB) and `.venv/` (~630 MB) are gitignored. Only manifests, scripts and docs are
committed.

**Nothing `plan` reads lives under `.tooling/`.** That is the point of the six inventory files
above: an input that exists only in gitignored output can be read on the machine that already
has the environment and nowhere else, which is BE-04. `doctor` checks them against the manifest
so the three copies of the node pins cannot drift apart silently. `.tooling/downloads` is the one
directory the plan *writes* into before verifying — it is gitignored on purpose, so a download
can never become a committed file by accident.

---

## 3. The browser stack, and the one non-obvious thing

### 3.1 Playwright 1.56.1 was chosen to match existing CROOKS source

`experience/browser.py` already reads:

```python
CHROMIUM = os.environ.get("CROOKS_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
```

Playwright **1.56.1** is the release that ships Chromium build **1194**. The pin was selected to
match the build number CROOKS already expects, not by taking the newest release. Changing this pin
changes the build number and silently breaks the default path.

### 3.2 `NODE_PATH` is required, and its absence looks like "not installed"

`scripts/browser/*.js` do `require('playwright')`. Node resolves that from the **script's own
directory**, not the working directory. With the tooling in `.tooling/node/node_modules`, the
scripts cannot see it unless `NODE_PATH` is set. Without it, `experience.browser.available()`
reports `playwright-core is not installed` even though it is.

`dev_env.py env` sets it. This is the single most likely thing to go wrong.

### 3.3 Chromium's shared libraries, and the read-only `/usr`

Chromium needs 12 shared libraries that are not present on this host:

```
libnspr4 libnss3 libnssutil3 libsmime3 libatk-1.0 libatk-bridge-2.0 libatspi
libcairo libcups libpango-1.0 libasound libXdamage
```

`apt-get install` cannot supply them: **`/usr` is read-only in the watcher sandbox, deliberately,
and must stay that way.** Rather than weaken the sandbox, the `.deb` payloads are downloaded and
extracted into `.tooling/sysroot/root`, and Chromium is run with `LD_LIBRARY_PATH` pointing there.

- 89 packages extracted; nothing outside `/opt/crooks-builder` is written.
- `libc6`, `libgcc-s1`, `libstdc++6` and `gcc-14-base` are **deliberately excluded** so the system
  C runtime is never shadowed.

If the owner would rather install these properly, the exact command is in
`manifest.json → sysroot.owner_approved_alternative`. **It has not been run** — it needs owner
approval and a writable `/usr`.

### 3.4 What was proven in this round

Against a local fixture page, with no live business API:

| Capability | Result |
|---|---|
| Chromium starts | Chromium **141.0.7390.37** |
| Renders and executes JS | yes |
| Screenshot at 601×889 DPR 1.33 | 34 KB PNG written |
| Console capture | `[console.log] probe: page script ran` |
| ARIA snapshot | heading / paragraph / button captured |
| axe-core audit | executed — 13 passes, 2 moderate violations on the fixture |
| Browser closes cleanly | no lingering processes |
| `experience.browser.available()` | **AVAILABLE** |

### 3.5 The visual verification matrix

Defined in `DESIGN.md` §13, and the workflow it supports:

```
before screenshot → implement → after screenshot → interaction test
→ CROOKS collision/browser gate → accessibility audit → visual comparison
→ bounded specialist critique
```

**Playwright augments the existing CROOKS harnesses; it does not replace them.** The collision,
touch, experience and physical-test harnesses stay exactly as they are. axe-core cannot see two
boxes that are each the right size and in the same place — which is the defect class
`collision.js` exists for.

---

## 4. Installed tools

Full pins in `manifest.json`. Summary, with the policy attached to each:

| Tool | Version | Policy |
|---|---|---|
| shellcheck | 0.11.0 | advisory |
| shfmt | 3.12.0 | **check only** (`-d`), never `-w` on existing shell |
| gitleaks | 8.30.1 | pre-publication gate; reports rule + path, **never a value** |
| fd | 10.3.0 | — |
| ast-grep | 0.40.0 | the `sg` alias upstream ships is **deleted** — `/usr/bin/sg` is `newgrp` |
| hyperfine | 1.20.0 | — |
| trivy | 0.74.0 | downloads a vulnerability DB on first use |
| uv | 0.9.9 | — |
| playwright | 1.56.1 | pinned to Chromium 1194, see §3.1 |
| @axe-core/playwright | 4.11.1 | supplements, never replaces, CROOKS harnesses |
| @biomejs/biome | 2.5.14 | **advisory, check-only.** Not a gate. See §4.1 |
| pyright | 1.1.407 | **advisory, check-only.** Not a gate |
| pytest-xdist / -timeout / -cov | 3.8.0 / 2.4.0 / 7.0.0 | see §6 |
| hypothesis | 6.145.1 | only where property testing genuinely helps |
| skillspector | 2.11.2 @ `d162d9b` | `--no-llm` mandatory; see §5 |

Already present and **not** duplicated: `ripgrep 14.1.1` (bundled with Claude Code), `node
v22.23.2`, `npm 10.9.8`, `python 3.12.3`, `jq`, `git`, `ruff 0.16.8` (via the project's own
`[dev]` extra).

### 4.1 Why Biome is advisory

First run over `web/`: **20 errors, 272 warnings, 18 infos across 14 files** — and
`No fixes applied`, with `web/` verifiably unmodified afterwards.

A warning-heavy new tool is not a gate until a baseline exists. **Do not bulk-reformat CROOKS
JS/CSS.** `web/style.css` and `web/ui.js` carry extensive load-bearing commentary and a
hand-maintained token ladder; a reformat would destroy review history for no product gain.

Worth a future, *deliberate* look (not this round, which does not touch the UI):

- `lint/a11y/useAriaPropsSupportedByRole` — 3 errors
- `lint/a11y/useSemanticElements` — 2 errors
- `lint/suspicious/noDuplicateProperties` — 1 error

---

## 5. The third-party skill security gate

**No third-party Agent Skill is installed without passing this gate first.**

```bash
skillspector scan <path> --no-llm --format json --output .tooling/scans/<name>.json
```

`--no-llm` is mandatory here. It keeps file contents local, requires no API key, and none is
provisioned. The SC4 supply-chain check still queries `api.osv.dev` with dependency
**coordinates only** — never file contents — and falls back to a bundled list offline.

The gate is: inspect the real repository → pin an exact commit → scan → read the flagged lines
yourself → record triggers, network needs and overlap with CROOKS instructions.

**A scanner verdict is evidence, not a decision.** Both outcomes happened in this round: a HIGH
that was a false positive, and MEDIUMs that were real.

### 5.1 Results

| Skill | Upstream | Pinned commit | Scan | Verdict |
|---|---|---|---|---|
| `frontend-design` | `anthropics/skills` | `34040c9` | 1 HIGH | **CLEARED** — false positive |
| `webapp-testing` | `anthropics/skills` | `34040c9` | 2 HIGH, 3 MED | **REJECTED** |
| `web-interface-guidelines` | `vercel-labs/web-interface-guidelines` | `e3d624b` | 3 MED | **CLEARED, content only** |
| `create-design-md` | `ibelick/ui-skills` | `d07392a` | 4 MED | **NOT INSTALLED** — methodology used instead |
| `redesign-skill` | `Leonxlnx/taste-skill` | `e79ca9e` | **0 issues** | **CLEARED** |
| `image-to-code-skill` | `Leonxlnx/taste-skill` | `e79ca9e` | **0 issues** | **CLEARED** |
| `taste-skill` | `Leonxlnx/taste-skill` | `e79ca9e` | 2 HIGH, 4 MED | **REJECTED** |
| `impeccable` | `pbakaus/impeccable` | `f2c7051` | 39 HIGH, 34 MED | **REJECTED for now** — §5.3 |

**None of them is actually installed.** See §8 — writing to `.claude/` is blocked here.

### 5.2 The reasoning, per skill

**`frontend-design` — cleared.** The single HIGH is category *Anti-Refusal* at `SKILL.md:69`,
columns 163–178. Those columns are the literal string `" don't apologize"`, inside the sentence
*"Errors don't apologize, and they are never vague about what happened."* That is UI copy guidance
about error tone, matched by a jailbreak pattern. The skill has **no executable scripts**
(`has_executable_scripts: false`). Confirmed false positive.

**`webapp-testing` — rejected.** Two HIGH *Tool Misuse* plus a MEDIUM *Dangerous Code Execution*,
all at `scripts/with_server.py:69`: `subprocess.Popen(server['cmd'], shell=True)` on a
caller-supplied command string. That is a real pattern, not a false positive. It is also
**redundant**: CROOKS already has an eleven-script Playwright harness that is strictly more
capable, and Phase 6's rule is not to duplicate an adequate installed tool. Per the standing rule
— do not install around a material finding — it is left uninstalled and recorded here.

**`web-interface-guidelines` — cleared, content only; never run `install.sh`.** Two things are
wrong with the installer and both matter:

1. It `curl`s from `refs/heads/main` **unpinned** at install time. What you get is whatever `main`
   says that day — the rug-pull vector, and it defeats pinning entirely.
2. It writes to `$HOME/.claude/commands/` — **global user scope**, not project scope — and probes
   for and writes into six other agent tools besides.

The *content* (`command.md`, `AGENTS.md`) is MIT-licensed static markdown with no executable
content. The correct adoption is to vendor the pinned files from commit `e3d624b` and never
execute the installer.

> Naming: the inbox asked for Vercel **`web-design-guidelines`**. No such repository exists under
> `vercel/` or `vercel-labs/`; the search hits are unrelated low-star lookalikes. The real artifact
> is **`vercel-labs/web-interface-guidelines`** (MIT). The lookalikes were **not** used.

**`create-design-md` — not installed; methodology applied directly.** Its four MEDIUM findings are
`npx @google/design.md` invocations (lint / export / diff). `npx` on an unpinned package fetches
and executes whatever version is current — a genuine rug-pull vector in a skill that would
otherwise run routinely. The methodology itself is sound and was followed by hand to write
`DESIGN.md`, so nothing ever invokes the unpinned package. Its `@google/design.md` frontmatter
schema was **not** adopted, because it cannot be validated offline and CROOKS needs its own
section set.

**`redesign-skill` and `image-to-code-skill` — cleared, 0 issues, no executable scripts.** These
are the inbox's "redesign-existing-projects" and "image-to-code". Per CROOKS precedence,
`redesign-skill` is the relevant one for existing product UI, and `image-to-code-skill` activates
only when a reference image is supplied or explicitly requested.

**`taste-skill` — rejected.** This is the inbox's "design-taste-frontend". Two HIGH and four
MEDIUM, and unlike the `frontend-design` HIGH these are substantive:

- Two HIGH at `SKILL.md:272–329` instruct the agent to emit **remote image URLs**
  (`picsum.photos`, Unsplash, Pexels) into generated markup. CROOKS loads **no** external
  resources — not even a web font (`DESIGN.md` §4) — precisely because the tablet is often on poor
  connectivity. A skill whose default output injects third-party URLs is contrary to the product.
- MEDIUM *Excessive Agency* at `SKILL.md:51`: *"Do not ask the user to edit this file — overrides
  happen conversationally."* A skill instructing the agent **not** to consult the owner conflicts
  directly with the authority order in `DESIGN.md` §0 (owner request is rank 1) and with
  `DEC-017`.

The inbox's own precedence rule already said this skill is not the authority for CROOKS
operational screens. The scan agrees, for independent reasons.

### 5.3 `impeccable` — not installed in this round

The scan completed on a second attempt (the first exceeded a 420 s budget). Result: **73 issues —
39 HIGH, 34 MEDIUM**.

| Category | Count |
|---|---|
| Prompt Injection | 35 |
| Excessive Agency | 15 |
| Server-Side Request Forgery | 12 |
| MCP Rug Pull | 4 |
| Anti-Refusal | 3 |
| Memory Poisoning | 2 |
| Data Exfiltration | 2 |

**The count overstates the risk, and saying so matters.** Sampling the HIGH findings shows the
same class of match as the `frontend-design` false positive — e.g. a HIGH *Prompt Injection* at
`SKILL.src.md:21` whose finding text is *"Load the request's playbook: its Commands-table
reference…"*, which is ordinary instructional prose. A large instructional skill will always
accumulate these.

**What is not a false positive is the executable surface.** `impeccable` ships
`has_executable_scripts: true` and, among others:

- `scripts/live-browser.js` — **547 KB** of bundled JavaScript, carrying all 12 SSRF findings
- `scripts/impeccable` — an executable entry point
- `scripts/modern-screenshot.umd.js`, `scripts/live-browser-*.js`

Half a megabyte of bundled JS cannot be meaningfully reviewed in this round, and the standing rule
is not to install around a material finding. **Not installed.** This is a "needs a dedicated
review", not a permanent verdict — it is the most directly relevant of the candidates for existing
CROOKS product UI, so it is worth the review.

Two further things need a decision regardless of the scan:

- It ships **`PRODUCT.md`** at its repository root. CROOKS must not gain a second product source
  of truth — `PRODUCT_BRAIN.md` and `DECISIONS.md` are canonical (`DEC-016`). If adopted, point it
  at product memory, or add only a minimal pointer.
- It ships **four sub-agents** (`impeccable-finish-reviewer`, `impeccable-manual-edit-applier`,
  `impeccable-documenter`, `impeccable-asset-producer`). `impeccable-manual-edit-applier` **edits
  source**, which needs an explicit decision before it exists in this repo.

---

## 6. Python test quality

The offline suite collects **2814 tests** (`-m "not live"`, 2 deselected). Host: 4 CPUs, 7 GB RAM.

- **pytest-timeout, pytest-cov** — installed, explicit use.
- **pytest-xdist** — installed, **recommended, not yet enabled by default.**

  Measured on this host (4 CPUs, 7 GB, quiet machine, `-p no:cacheprovider`, `-m "not live"`):

  | Run | Wall | Result |
  |---|---|---|
  | serial | 490.3 s | — |
  | serial | 495.7 s | — |
  | serial | 514.4 s | **2806 passed, 8 skipped, 2 deselected** |
  | `-n 4` | 220.4 s | **2806 passed, 8 skipped** |
  | `-n 4` | 224.4 s | **2806 passed, 8 skipped** |

  **2.2× faster — 8.2 min down to 3.7 min — with the identical outcome.** Both parallel runs match
  each other *and* match serial, so there is no evidence of shared-state or ordering dependence at
  `-n 4`. All three adoption criteria (deterministic, no race failures, unchanged semantics) are
  met on this host.

  It is left **off by default** anyway. `make test` is unchanged; use `-n 4` explicitly. Two
  reasons: the evidence is two runs on one host, which is enough to recommend and not enough to
  make it the default for everyone; and the serial ordering is what every previous result in this
  repo was measured under. Flip the default in a separate, deliberate change.
- **Hypothesis** — installed, applied nowhere yet. It belongs on parsers, serialization, the
  proposal/action state machine, and future Event Ledger logic. **Do not rewrite existing tests
  merely to claim Hypothesis usage.**
- **No retry plugin, ever.** A flaky test is never hidden behind a rerun.

---

## 7. Update policy

**Nothing here auto-updates.** To move any pin:

```
upstream update → security scan → diff → test → review → update manifest.json
```

For a third-party skill, "security scan" means the full §5 gate again, including reading the
flagged lines rather than accepting the verdict.

---

## 8. Not done, and why

- **Project-scoped Claude configuration (`CLAUDE.md`, `.claude/rules/`, project skills, hooks) was
  NOT created, and no skill was installed.** Writes to `/opt/crooks-builder/.claude/` are refused
  by the agent's permission layer. The refusal was not worked around. The proposed layout is
  specified in `docs/dev-environment/CLAUDE_PROJECT_LAYOUT.md` so it can be applied in one
  reviewed step.
- **`.gitignore` still ignores `.claude/`.** Adopting the layout requires changing that line to
  `.claude/*` plus explicit negations — git cannot re-include a file inside an excluded
  *directory*, so negations under `.claude/` are dead until the trailing slash goes. Left
  unchanged because the configuration was not installed.
- **The `impeccable` scan did not finish** (§5.3).
- **No system package was installed**; `/usr` is untouched and still read-only.
- **No service was installed, started or changed. Tailscale untouched. Writes still disabled.
  No live Shopify, Gmail or ElevenLabs call was made** — the browser gate runs against the
  fixture world on loopback.

---

## 9. The four rejected findings, and what each repair actually proves

Candidate `9a27bc4` was published, independently reviewed and **rejected**. Its own outbox said
the environment worked; three of the four findings were reproduced against the committed code
anyway. That is the useful part: a worker's prose about its own result is not evidence, and the
repairs below are each pinned to a test that fails against the rejected code.

### 9.1 BE-01 — the plan generator crashed on the manifest committed beside it

`binaries` carries a string-valued `$comment` so the pins stay readable. `doctor` skipped
`$`-prefixed keys; `bootstrap` did not, so it reached `spec['version']` on a string and raised
`TypeError: string indices must be integers, not 'str'` eighteen printed lines in. No install, no
network and no missing tool were needed to reproduce it.

Two callers deciding separately what counts as a tool is the actual defect, so there is now one:
`entries()`. It filters prose and requires every surviving entry to be an object carrying the
fields its section needs; anything else is a `ManifestError` naming the key, reported as a message
and not a traceback.

### 9.2 BE-02 — `doctor` returned success for wrong versions and failed tools

It counted only `MISSING`. A binary that ran and printed anything at all was `ok` — the pin was
*displayed beside* the output and never compared with it, which is why `shellcheck` reporting
`0.0.0` passed. Version mismatches and failed probes were `warn`, and `warn` did not count. A
fixture with every tool present and every tool wrong finished `all present`, exit 0.

Now: each tool is run through **its own `verify` command from the manifest** (`shlex.split`, never
a shell), all of its output is read rather than the first line, and the pinned version must appear
in it. Missing, unrunnable and mismatched are all `FAIL`. Chromium is compared against
`browsers.chromium.chromium_version`, the venv against `python.interpreter`, and the nine pinned
binaries against `binaries.sha256` — a version number is a claim the artifact makes about itself,
so the bytes are checked too.

Both directions are proved:
`test_be02_doctor_fails_closed_when_tools_are_present_but_wrong` and
`test_be02_doctor_passes_the_same_fixture_when_everything_matches`. Fail-closed that always fails
is not a check.

**Advisory still means advisory, and is now narrow.** Biome and Pyright findings *over product
source* remain advisory (§4.1) — `doctor` does not run them and never did. What `doctor` reports
is required environment identity, and the only advisory line in it is §9.3.

### 9.3 The thing `doctor` could not decide — now decided

`uv tool install --from <local clone>` records a filesystem path and no revision, so the installed
SkillSpector carried nothing to compare `uv_tools.skillspector.commit` against, and `doctor` could
only print it as `advisory` with that reason on the line.

It is no longer undecidable, because the install changed. Step 6 now installs from the pinned git
requirement

```
git+https://github.com/NVIDIA/skillspector@d162d9b343e559be13df8ebba093df3bc9d58c90
```

which makes uv write PEP 610 provenance into the tool venv's
`skillspector-2.11.2.dist-info/direct_url.json`, including `vcs_info.commit_id`. `doctor` reads
that file and compares it with the pin. Four outcomes, one of them `ok`:

| What the artifact records | `doctor` |
|---|---|
| `vcs_info.commit_id` equal to the pin | `ok` |
| `vcs_info.commit_id` different from the pin | **FAIL**, both shown |
| `dir_info` — a local-path install | **FAIL**, "records no revision", with the command that fixes it |
| no `direct_url.json` at all | **FAIL** |

An environment installed the old way therefore fails this check, which is correct: the pin was
never verified there and saying so is the whole point. `test_be04_skillspector_provenance_decides_rather_than_excuses`
covers all four.

**What is still advisory, and it is smaller.** Four of the eight pinned upstreams — shellcheck,
fd, ast-grep and hyperfine — publish no checksum file of their own. Their committed asset digests
in `binary-assets.sha256` are enforced on every reconstruction but are first-fetch observations
rather than an independent attestation by the project. `doctor` prints one advisory line naming
exactly those four. The other four (shfmt, gitleaks, trivy, uv) publish checksums, and the
committed digests were compared with them and matched.

### 9.4 BE-03 — generated exports executed what was in the checkout path

`cmd_env` built each line with Python's `repr` and then replaced the quotes, which produces a
**double**-quoted shell word. Double quotes do not stop the shell. A checkout at
`/tmp/crooks-$(printf CROOKS_ENV_PROBE)` exported
`NODE_PATH=/tmp/crooks-CROOKS_ENV_PROBE/.tooling/node/node_modules` — the wrong directory, and a
command the generator chose to run, in output whose documented use is `eval`.

`shlex.quote` is the fix: single quotes, and an embedded single quote is escaped rather than
ending the string. `plan` quotes its paths the same way. The regression cases are the original
`$(printf …)` probe, and one directory name carrying spaces, an apostrophe, a double quote, `$`,
a backtick, a semicolon and a newline at once — read back NUL-separated, `PATH` included.

### 9.5 BE-04 — a fresh checkout could not reconstruct this

Four separate things, and one of them is still open.

**Fixed — the interface is honest.** `bootstrap` was documented as "install whatever doctor says is
missing" and as idempotent. It printed instructions. Its exit code therefore meant only that text
had been printed. It is now `plan`, which is what it always was; `bootstrap` exits 2 and says so
rather than remaining a silent alias.

**Fixed — the inputs are committed.** Step 1 was `cd .tooling/node && npm install`, and `.tooling/`
is gitignored: on a fresh checkout that directory does not exist and the `package.json` it
installed from had never been committed anywhere. The npm project and its lock are now committed
under `docs/dev-environment/`, `plan` copies them into place before npm runs, and the step is
`npm ci` — a lock that is committed and then not installed from is decoration.

**Fixed — the steps are root-anchored.** Bare `cd`s that later commands inherited are gone; a `cd`
appears only inside a subshell that closes on the same line.

**Fixed — the artifacts are identified.** `sysroot-packages.txt` pins all 89 `.deb`s as
`name=version`, replacing a recursive `apt-cache depends` resolution that returned whatever the
distribution offered on the day it ran. `sysroot-packages.sha256` and `binaries.sha256` carry a
digest each. They were recorded by observing the artifacts installed on this builder — see §10.2
for what that observation is now worth, which is more than it was.

**Fixed — the plan executes.** This was the open part. It needed an owner decision, the decision
was given on 2026-09-19, and §10 is what came of it.

---

## 10. The approved fetch boundary, and the reconstruction it makes possible

On **2026-09-19** the owner approved bounded, read-only package fetching for the sole purpose of
reconstructing this declared environment from a fresh checkout. This section is what that approval
was spent on. It is deliberately specific: an approval recorded as "we may download things" is not
a boundary anybody can check later.

### 10.1 What may be fetched, and how that is enforced rather than promised

| Step | Contacts | Installs from |
|---|---|---|
| 1 | `registry.npmjs.org` | the committed `node-package-lock.json`, via `npm ci` |
| 2 | Playwright's CDN | the Chromium build the pinned Playwright asks for |
| 3 | the configured apt mirror | the 89 `name=version` pins in `sysroot-packages.txt` |
| 4 | `github.com` release assets | the eight `asset_url`s pinned in `manifest.json` |
| 5 | PyPI | `pyproject.toml` `[dev]` plus the five pinned builder-only packages |
| 6 | `github.com` | SkillSpector at the pinned commit, as a git requirement |

Nothing else is contacted. Every fetch is anonymous: **no credential, token or key is used or
needed anywhere in this plan**, and none is stored in this repository.

The rule "only from the declared dependency's own authoritative upstream" is the kind of rule that
decays into whoever last remembered it, so it is a precondition in code instead. `fetch_spec()`
requires every binary's URL to be exactly

```
<upstream>/releases/download/<release_tag>/<asset>
```

built from that same entry's own fields. A URL pointing at a mirror, at another project, at a
different tag, or at a non-release path is a `ManifestError` naming the tool, and **no fetch step
is emitted at all**. `test_be04_an_asset_url_outside_the_tools_own_upstream_is_refused` walks all
five of those cases.

The release tags and asset URLs are **pinned, not derived**. Computing eight GitHub URLs from a
naming convention at run time would put the strings that decide what executes on this machine
outside review — the same defect as BE-01, one layer down. They are written into `manifest.json`
where a reviewer can read them.

### 10.2 Integrity, twice, failing closed

```
curl -fsSL --proto '=https' --tlsv1.2  ->  .tooling/downloads/
( cd .tooling/downloads && sha256sum -c …/binary-assets.sha256 )   <- before anything unpacks
tar / unzip / install -m 755           ->  .tooling/bin/
sha256sum -c …/binaries.sha256                                     <- after install
```

The order carries the weight. Verifying an archive *after* extracting it checks the wrong thing:
`tar` and `unzip` have already interpreted the bytes. `test_be04_downloads_are_verified_before_anything_unpacks_them`
asserts the ordering, not just the presence, of both gates. The `.deb`s get the same treatment
against `sysroot-packages.sha256` before `dpkg-deb -x`, and npm gets it from `npm ci` against the
committed lock.

**What the observed digests are now worth.** `binaries.sha256` was recorded by reading the bytes
off this builder, and the previous round was careful to say that this was an observation and not
an upstream attestation. Under the approved fetch, every one of the eight assets was downloaded
from its pinned upstream release and extracted, and **all nine installed-binary digests were
reproduced exactly**. The observation and the upstream release agree. Separately, the four
projects that publish a checksum file — shfmt, gitleaks, trivy, uv — were compared with it and
matched. The remaining four publish none, and `doctor` says so on an advisory line naming them
rather than letting "verified" quietly cover a gap.

`sysroot-packages.sha256` remains observed. It is enforced on every reconstruction, so a mirror
that returns other bytes fails the check; what it is not is an attestation from Ubuntu.

### 10.3 Provenance for the skill gate

Step 6 installs SkillSpector from `git+<upstream>@<commit>` rather than from a local clone,
because that is the difference between uv recording a revision and uv recording a path. See §9.3:
the pin is now checked, and an install that cannot prove its revision fails.

### 10.4 Running it, and what "idempotent" means here

From the repository root of a fresh checkout:

```sh
python3 crooks-assistant/scripts/dev_env.py plan          # read it first; it installs nothing
```

then run the steps. `plan` is still a generator and still writes nothing — that separation is why
it is not called `bootstrap` (§9.5). Each step is individually re-runnable: `npm ci` rebuilds
`node_modules` from the lock, `playwright install` skips a browser it already has, `apt-get
download` and `dpkg-deb -x` overwrite, `install -m 755` overwrites, and `uv tool install` replaces
the tool venv. Running the whole plan a second time therefore ends in the same environment, which
is the property worth having; it is **not** a claim that the second run performs no work.

The end-to-end execution record — run 1, run 2, and `doctor` after each, from a disposable
checkout containing no `.tooling/` and no `.venv/` — is bound to the candidate's commit SHA in
that round's handoff, because a tree cannot contain a verified statement about itself.

### 10.5 Still outside the boundary

Nothing here installs a service, opens a listening socket, writes outside the builder worktree,
touches `/usr`, needs a credential, or runs on or against production. The approval covered
reconstruction fetches and nothing else.
