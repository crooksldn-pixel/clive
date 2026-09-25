# External Review Brief - 2026-09-25

**Status:** a read-only external review provided by the owner on 2026-09-25, kept verbatim below as evidence. The owner's decisions on it are in OWNER_DECISIONS_2026-09-25.md; its directions are captured in NEXT_PHASE_2026-09-25.md section 3.8.

## CLIVE: external review brief for the builder (25 Sep 2026)

**How to use this.** This is a read-only external review. Every claim was checked against GitHub on 2026-09-25: branch contents, CI runs, and the `clive/control/*` status projections. Host-local state (the engineering store, systemd, disks, the Mac) isn't visible from GitHub, so verify it on the host before acting. **OWNER** marks decisions only the owner can make. Nothing here authorises a deploy, a privilege change or a baseline entry.

## Pinned references

| What | Exact SHA | State |
|---|---|---|
| `clive/trunk` head | `55a9bece632d5cbaf9360836162e7584cc25ecb3` | CI run 171 **red** |
| Last green trunk (PR #7) | `b022789ba2d86fb8406e11feb58ee9e386b0660e` | CI run 150 green |
| Production, deployed 25 Sep | `ce791d032dcc8cf9b761ca40ce0b08a259c897a2` | CI run 118 green; exact-SHA GPT review READY |
| Remote engineering loop pin | `4c32bb3d5f4935402c9cdc897914370950f7f206` | running as `clive-remote-engineering.service` |
| Dispatcher reference | `c566a955903a3a02e4a9ec97f0bab5a62e703fcd` | kernel files byte-identical on trunk |
| Frozen lifecycle kernel | `18c3153a2eec10c6343153b550776afed3bec2ba` | unchanged |
| Operational-alpha release | `f7be86f7f4676ca86de9a7ef18bac2342f29f62d` | immutable failed evidence |
| Owner-authorised baseline branch | `99d8ace60c3e5c12d101264e3ca6281d463a7db6` (`claude/release-secret-baseline-2026-09-24`) | **not in trunk** |

---

## 0. What changed since 24 Sep

- **One trunk.** `clive/trunk` now carries `lifecycle.py`, `dispatcher.py`, `objectives.py` and `routing.py` byte-identical to dispatcher `c566a955`. The engineering line was merged at `4c32bb3d`. In practice the lineage split is closed, and the `ci-age-days-floor` fix is in trunk (PR #3).
- **Deploys happen in the right order.** `ce791d03` went to `/opt/crooks-os` only after a green acceptance run on that exact SHA *and* an exact-SHA GPT review returned READY. Health, live reads and logs were recorded afterwards (`clive/evidence/remote-engineering-activation`).
- **Remote Engineering Control V1 is live.** The two status projections show 42 requests since activation. Nine were accepted by exact-SHA review and integrated:
  - `international-waiting-clock`
  - `operational-alpha-acceptance-repair-4`
  - `needs-reply-routing-3`
  - `remote-engineering-journal-safe-2`
  - `microphone-prompt-fix-3`
  - `voice-credits-honest-3`
  - `generative-ui-v1-evidence-scenes-4`
  - `generative-ui-v1-scene-renderer-2`
  - `clive-engineering-bridge-5`

  The rest are blocked, refused at intake (mostly superseded resubmissions), or still running. Each success took about 2–4 submissions, mainly because builders can't run checks and because of tool or scope limits (§1.5).
- **The ChatGPT↔Claude bridge watcher was stopped and disabled** by owner authority. While it stays disabled, its specific findings (CB-05/06/07/15) no longer apply to a running service. Two of them reappear in the new loop's unit (§1.4).
- **Builders behave honestly under real load.** Workers report "I couldn't run commands" and "blocked: my tools can't delete files" rather than faking a pass. The owner then re-scoped and requeued. That is the honesty property holding in production.

---

## 1. Open now, in priority order

### 1.1 Trunk has been red since PR #8, and three more PRs landed on it

| Landing | SHA | CI | Notes |
|---|---|---|---|
| PR #7 journal-safe-2 | `b022789b` | green | last green trunk |
| PR #8 microphone-prompt-fix-3 | `7914ed8d` | **red** | secret scan passed; another gate failed |
| PR #9 voice-credits-honest-3 | `ba6d7103` | **red** | adds a new secret-scan finding |
| PR #10 memory staging | `da50f973` | **red** | |
| PR #11 Generative UI 1 of 4 | `55a9bece` | **red** | `pytest_offline_full` 3 failed / 3,843 passed; `secret_scan` 1 finding |

- **New secret-scan finding:** `crooks-assistant/tests/test_voice_credits.py:31` (`generic-api-key`). It's the same synthetic ElevenLabs test-key pattern the baseline already excuses in `test_tts.py:20` and `test_scribe.py:24`, but in a new file. Reproduced locally with gitleaks 8.30.1 run exactly as CI invokes it. Trunk had 0 findings at PR #7 and PR #8, and 1 from PR #9 onwards.
- **Root cause (same as 23 Sep):** the loop's acceptance (declared checks plus GPT exact-SHA review) doesn't wait for the GitHub acceptance run, and neither do landings. The timestamps (all UTC) show it:

  | Objective | Candidate committed | Accepted | Integrated |
  |---|---|---|---|
  | `voice-credits-honest-3` | 15:20:22 | 15:21:16 | 15:21:17 |
  | `generative-ui-v1-evidence-scenes-4` | 15:34:25 | 15:35:09 | same second |
  | `generative-ui-v1-scene-renderer-2` | 16:15:10 | 16:16:03 | 16:16:04 |
  | `microphone-prompt-fix-3` | 09:45:46 | 09:47:41 | |

  An acceptance run takes about 4–5 minutes, so every acceptance was recorded before one could finish. The request template says as much: GitHub acceptance "runs automatically after your candidate is published".
- **Actions:**
  - (a) Stop landing on red. A green `acceptance` run on the exact landing SHA becomes a precondition for "Land … into trunk".
  - (b) Fix the 3 tests and the secret finding in one repair objective. The CI artifact doesn't name the failing tests, so run the suite on the host to list them.
  - (c) Add "green GitHub acceptance on this exact SHA" to the loop's required evidence before it records acceptance.

### 1.2 An explicit owner decision was overtaken without a new one

- **24 Sep 14:56.** The owner authorised one baseline entry for `HumanisingTests.swift:127`, plus the case-insensitive `/tests/` assertion it needs. The result is `99d8ace6`: the decision is quoted in the commit and both changes were verified. **It was never merged into trunk.**
- **24 Sep 21:47.** Objective `operational-alpha-acceptance-repair-4` rewrote the Swift fixture to assemble the fake keys at runtime, so the scanner no longer sees them. Trunk carries this; the baseline still has 5 entries. `4c32bb3d` did the same for request-id tests.
- **It isn't unsafe.** The values are obviously synthetic and the scanner is unchanged. But:
  1. It replaced an owner decision without a new recorded decision.
  2. It's the opposite of the repo's own rule, "made green by disclosure rather than by looking away". Every CI artifact reports what the baseline excuses; runtime assembly hides it.
  3. §1.1 shows the problem recurring in a new file.
- **OWNER:** choose one policy and record it. Either:
  - **A.** Disclosure: baseline synthetic test credentials on owner say-so, starting with `test_voice_credits.py:31`, and merge the `99d8ace6` approach.
  - **B.** Runtime assembly for all fake credentials in tests: document it as the rule and close the baseline branch.

  Either way, one shared test helper for fake credentials stops this recurring objective by objective.

### 1.3 Nothing ever runs the nine Swift test files

- CI is `ubuntu-latest` only. No workflow, script or loop check runs `swift test` or `xcodebuild`, and builders have no shell.
- `repair-4` edited `HumanisingTests.swift`, and no check has ever compiled or run that edit.
- This is the natural first job for a Mac (§4).

### 1.4 The new loop service is less confined than the watcher it replaced

- `clive-remote-engineering.service`:
  - runs as `User=root` on the production host;
  - holds the OpenAI reviewer key and the worker OAuth token;
  - has only `ReadOnlyPaths=` for `/srv/clive-engineering/remote-control`, `/opt/crooks-interactive` and `/opt/crooks-os`.
- It has no `ProtectSystem=strict` (the retired watcher had it), no `NoNewPrivileges`, no `PrivateTmp` and no network restriction.
- **OWNER (systemd and privilege change):**
  - add `ProtectSystem=strict` with explicit `ReadWritePaths=` for `/srv/clive-engineering/{state,repo,runtime,workers}`;
  - add `NoNewPrivileges=yes` and `PrivateTmp=yes`;
  - ideally run it as a dedicated non-root user.
- The stronger fix is to move the engineering loop off the production host (§5).

### 1.5 Loop friction: builders repair blind, and four requests died on one infrastructure fault

- **Blind repairs.** Builders have file tools only, so they never see a test result before reporting. Repairs cycle r1→r4, and `status-publishes-findings` hit the convergence limit (3 of 3). The sandbox for checks already exists (namespace/chroot/no-network). A builder-callable "run my declared checks in the sandbox" tool would cut repair rounds without ever running worker code unsandboxed on the host: read-only venv, no network, time-limited. This is a candidate objective.
- **One infrastructure fault blocked four requests** (`clive-engineering-bridge-4`, `generative-ui-v1-evidence-scenes-3`, `owner-facing-host-wording-4`, `voice-credits-honest-2`). The error is `fatal: failed to create link … Invalid cross-device link` while creating the worker's git copy. Git's local clone hard-links objects, which fails when the repo and `/srv/clive-engineering/workers` are on different filesystems or mounts. Fix it once: clone with `--no-hardlinks` (or `--no-local`), or keep both on one filesystem. This isn't a builder failure.
- **Stale product memory.** The loop feeds builders product memory from `origin/claude/product-memory-truth-2026-09-23`. That predates trunk and the bridge retirement. Repoint it to trunk once the consolidation lands.

### 1.6 Still unchanged from 24 Sep

- **Judgment Ledger:** still read-only. `lifecycle.py` loads and verifies it; nothing writes owner decisions. Today's decisions (the baseline authorisation, the bridge retirement, deploy approvals, the requeues) live in commit messages and chat, not the ledger. Start by recording today's.
- **Audit trail:** `clive/engineering-state` was last pushed 23 Sep. Reviews and acceptances are published only as the `clive/control/*` status projection. Either publish a cleaned-up journal again, or declare the projection the audit surface and include review verdict IDs and CI run IDs in it.
- **`PROTECTED_PATHS`** is unchanged: the same blob on trunk and at the loop pin. It still omits the product safety core and the evidence tools: `gate.py`, `readonly.py`, the Shopify/Gmail write funnels, `app/actions/`, `scripts/acceptance_provenance.py`, `.gitleaks*`, `pyproject.toml`.
- **New: the loop itself isn't protected.** `app/remote_engineering/` and `scripts/remote_engineering.py` aren't on `PROTECTED_PATHS`, and builders have already changed them: `remote-engineering-journal-safe-2` edited `requests.py`, `receipts.py` and `scripts/remote_engineering.py`, and it landed as PR #7. Today the only thing between a builder's change and the loop that accepts builders' work is the pin (`4c32bb3d`) and an owner re-pin. That fits the invariant "candidate code must not control its own acceptance machinery" only by convention. **OWNER:** either protect those paths, or write down that loop changes take effect only through an owner-gated re-pin after an exact-SHA review of the new pin.

---

## 2. Direction, carried forward from 24 Sep

### 2.1 One kernel, two domains (the key)

CLIVE has three separate propose → authorise → execute → verify engines, each with its own approval step:

- `app/actions` (tablet gesture)
- `app/objectives` (`authorise()`, standard-library only, no kernel)
- `app/orchestrator` (the kernel)

The ledger designed to hold the owner's authority sits empty between them. RECONCILIATION §9 already names the answer: "the same kernel operating in two domains".

The first step is reversible: a Support Investigator reply becomes a Gmail **draft** through the kernel. It gets an exact fingerprint, the owner approves/edits/declines through the ledger, and the kernel verifies it by reading the draft back.

- Business actions need classification by effect and reversibility: a refund doesn't roll back like a commit.
- It's more reachable now. The kernel runs continuously, and `clive-engineering-bridge` (CLIVE filing its own engineering objectives) is the engineering half of the same intake.

### 2.2 Self-audit: the observer side is still unshown

The bridge was retired by owner decision, so it can't serve as proof that CLIVE noticed something itself. Keep the method:

- a general §10 retirement audit that never names components;
- the owner's predictions sealed outside the repo, with only their hash recorded;
- negative controls chosen by the owner;
- timing scored ("not yet, because…" can be the right answer);
- CLIVE proposes; the owner decides through kernel and ledger, with rollback by disabling rather than deleting.

The bigger version is CLIVE arguing, with evidence, that one of its own `DECISIONS.md` entries should be superseded (the DIRECTOR_PROTOCOL SUPERSEDE procedure). **Builders must not ask for, infer or store the owner's sealed predictions or negative controls.** Once an expected answer is anywhere CLIVE reads, the test is spoiled.

### 2.3 Storage: SQLite on the host, not Supabase, and not yet

- **Not Supabase:**
  - its multi-user features aren't needed;
  - it breaks the README's "No database, no server anywhere else" and IDEA-046 (private-first);
  - it matches the July 2025 Supabase MCP demonstration, where text in a support ticket steered an agent holding the `service_role` key into leaking tables into a customer-visible reply;
  - it unblocks nothing.
- **A local SQLite store, when the first business objective runs through the kernel.** It gives:
  - **privacy:** the kernel's records and status projections are otherwise published to branches of a public repo;
  - **crash safety:** the store's undo log in `lifecycle.py` lives only in memory;
  - **queryable history** for the ledger;
  - **retirement** of the hand-built store code.
- `ENGINEERING_ORCHESTRATOR_V1.md` §4 already planned it ("A single-host SQLite implementation is a candidate"). `store.py:63` calls the JSON store a simulation.
- Keep git as the published, cleaned-up journal and hash anchor that GPT reads.
- **Rules:**
  - no model ever gets free-form query access, only narrow typed reads and writes through the kernel;
  - put the database under `InaccessiblePaths=` for the loop and builders;
  - put the schema and migrations on `PROTECTED_PATHS`;
  - take encrypted backups and test a restore.

## 3. The pattern to keep correcting

Most of the big ideas are already in the documents and remain unbuilt: one kernel, the SQLite store, the ledger as the authority record, the replay gate (IDEA-024) and the Nightly Observer (IDEA-022). Meanwhile the factory lands many small objectives. Today's rate is real progress. The failure mode is **landing faster than verification**: §1.1 and §1.2 are the same problem as 23 Sep in a new place.

---

## 4. The Mac

- **Not visible in GitHub.** No branch, document or commit mentions a Mac server. The recorded decisions point the other way:
  - "CROOKS runtime should not depend on the Mac being awake."
  - "Mac becomes optional control/development/rollback device."
  - `ROADMAP.md`: "keep Mac deployment as rollback".
  - Today's `owner-facing-host-wording` objectives remove Mac wording from owner-facing text. The new wording is host-neutral, so it stays true if a Mac hosts again.
- **OWNER:** if a Mac server is being set up, record what it will host before builders act. Otherwise objectives keep treating "Mac" as legacy.
- **What an Apple-silicon Mac is best at here:**
  1. Swift/Xcode builds and tests for CROOKS Control and any iPhone app. This closes §1.3, and Linux can't do it.
  2. Core ML/Metal speech: the M4 whisper.cpp/Core ML setup that `DECISIONS.md` chose not to reproduce on the Hetzner CPU VM.
  3. Quiet, low-power, always-on duties.
- **Don't register it as a GitHub self-hosted runner for this public repo** (§5.3). Run the Swift checks from the loop over Tailscale instead.

---

## 5. The local server (2× Xeon, 128 GB RAM, 3.8 TB RAID 10)

Nothing about this machine is in the repo. Most of what follows depends on which Xeon generation it is, so identify it first.

### 5.1 Identify it (read-only, one line)

```
lscpu | grep -E 'Model name|Socket|NUMA node\(s\)'; grep -o -w -E 'avx2|avx512f|avx512_vnni' /proc/cpuinfo | sort -u; free -g | head -2; sudo dmidecode -s system-product-name; sudo dmidecode -t memory | grep -E 'Error Correction Type|Configured Memory Speed' | sort | uniq -c; lsblk -d -o NAME,ROTA,SIZE,MODEL; cat /proc/mdstat; lspci | grep -i -E 'raid|sas'; grep . /sys/devices/system/cpu/vulnerabilities/* | cut -c1-110
```

How to read the output:

- **CPU generation:**
  - E5-26xx **v3/v4**: Haswell/Broadwell (2014–16), AVX2, 4 memory channels per CPU.
  - Xeon Scalable **x1xx/x2xx**: Skylake/Cascade Lake (2017–19), AVX-512, 6 channels per CPU. With 128 GB some channels may be empty, which cuts memory bandwidth.
- **"Multi-bit ECC"** means ECC memory.
- **ROTA 1** means spinning disks. Behind a hardware RAID controller this can be wrong, so check the controller tool.
- **A RAID/SAS line in `lspci`** means hardware RAID: use `perccli`/`storcli` for Dell or `ssacli` for HPE. Entries in `/proc/mdstat` mean Linux software RAID.

### 5.2 Good at

- **Being the engineering host.**
  - Builders, sandboxed checks, integration and full-suite runs are parallel, memory-hungry work. 128 GB and two sockets can run far more than today's `--max-concurrent 2`.
  - It can also run the full acceptance suite on every candidate before landing (§1.1), instead of finding red on GitHub afterwards.
  - Moving the loop here takes the reviewer key, the worker token and root-level builder activity off the production VM. IDEA-047 ("Do not make production the development environment") isn't met today: the loop runs on `crooks-os-prod-1`.
- **Private storage.** 3.8 TB on premises suits data that shouldn't go to GitHub or a third party:
  - the evidence and artifact store;
  - a replay corpus for IDEA-024;
  - recordings;
  - SQLite backups (§2.3).
- **Private batch AI.** CPU-only generation is limited by memory bandwidth, because every token reads all active weights from RAM. Rough speeds:

  | Model | Older Xeons (Broadwell) | Newer Xeons (Cascade Lake) |
  |---|---|---|
  | 8B dense | about 5 tokens/s measured | 15–25 tokens/s estimated |
  | ~30B mixture-of-experts, ~3B active | 8–15 tokens/s estimated | about 25 tokens/s measured on one socket |
  | 70B dense | about 1.4 tokens/s measured | 2–3 tokens/s |

  - Prompt processing is roughly 50–250× slower than on a GPU.
  - **Yes:** small MoE models for private triage, classification and redaction of customer email; embeddings; batch whisper transcription.
  - **No:** replacing Claude or GPT for reasoning.
  - Pin a model to one socket (NUMA). For MoE models the second socket adds little.
- **ECC memory and redundant disks** suit long-running stores. ECC is usual on these platforms; confirm it with `dmidecode`.

### 5.3 Bad at, and risks

- **Not a GitHub self-hosted runner for this public repo.** GitHub: *"We recommend that you only use self-hosted runners with private repositories. This is because forks of your public repository can potentially run dangerous code on your self-hosted runner machine by creating a pull request that executes the code in a workflow."* The acceptance workflow triggers on `pull_request`. Keep CI on GitHub-hosted runners, which are free for public repos, and let the loop drive this box over Tailscale.
- **RAID 10 is not a backup.**
  - It survives one failed disk per mirror pair. Losing both disks of any pair loses the array, and during a rebuild the surviving partner is a single point of failure.
  - It doesn't protect against deletion, corruption, ransomware, fire or theft.
  - It needs:
    - array alerting (`perccli`/`storcli`, `ssacli` or `mdadm --monitor`);
    - SMART checks through the controller;
    - a healthy controller cache battery;
    - off-box encrypted backups. The VPS and this server can back each other up.
- **Not the production host.** Office or home power and broadband are less available than a datacentre. Production (voice, Shopify/Gmail credentials) stays on the VPS. Tailscale reaches this box through NAT or CGNAT without opening ports.
- **Running cost and noise.**
  - Real-world idle for this class is roughly 100–150 W. Vendor minimum configurations test far lower, and heavy AVX load can pass 400 W.
  - At a 150 W average that's about 1,314 kWh a year: roughly £350 at the Oct–Dec 2026 domestic cap of about 26p/kWh, more on uncapped business tariffs.
  - Measure it with `ipmitool dcmi power reading` or a plug meter.
  - Rack servers are loud in a shared room.
- **Age.**
  - On older generations the management controller is out of support: iDRAC8 software maintenance ended in Feb 2024, and iLO 4's last firmware came out in 2023. Keep iDRAC/iLO off the internet and off the tailnet.
  - CPU vulnerability mitigations cost roughly 10–20% on syscall-heavy work such as git and pytest.
  - Per-core speed is below a modern Mac. This box wins on parallelism, not single-thread speed.
- **No GPU.** If fast local models become a goal, the fix is a GPU, not more RAM.

### 5.4 Proposed layout (OWNER decision)

| Machine | Role |
|---|---|
| VPS (`crooks-os-prod-1`) | Production only: CLIVE runtime, business credentials, exact-SHA deploys |
| Local Xeon server | Engineering host: loop, builders, sandboxed checks, integration, full-suite runs. Also the private evidence and replay store, and a backup target |
| Mac | Apple builds and Swift tests, Core ML speech, rollback runtime per ROADMAP |
| GitHub | Transport and projection; CI on GitHub-hosted runners |

Migrate in stages:

1. Identify the hardware.
2. Set up alerting and backups.
3. Install Linux and Tailscale.
4. Mirror the engineering store read-only.
5. Run the loop there in dry-run.
6. Owner-gated cutover, stopping the loop on the VPS. Credentials move only at cutover.

**Sources (verify before quoting):**

- GitHub self-hosted runners: https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners and https://docs.github.com/en/actions/reference/security/secure-use
- llama.cpp NUMA: https://github.com/ggml-org/llama.cpp/issues/1437
- MoE on a dual-Xeon R740: https://github.com/ikawrakow/ik_llama.cpp/discussions/2030
- 70B on E5-2683 v4: https://github.com/ikawrakow/ik_llama.cpp/discussions/164
- CPU vs GPU prompt speed: https://github.com/ggml-org/llama.cpp/discussions/15013
- RAID 10 on Dell PERC: https://dl.dell.com/topicspdf/perc10_ug_en-us.pdf
- iDRAC8 end of maintenance: https://www.dell.com/support/kbdoc/en-us/000178044
- Ofgem Oct–Dec 2026 cap: https://www.ofgem.gov.uk/news/changes-energy-price-cap-between-1-october-and-31-december-2026
- Tailscale without open ports: https://tailscale.com/kb/1082/firewall-ports

---

## 6. Priority list

1. **Trunk green again:** fix the 3 failing tests and `test_voice_credits.py:31`, and stop landing on red (§1.1). **OWNER:** choose the synthetic-credential policy (§1.2).
2. **Green GitHub acceptance on the exact SHA** becomes required evidence for loop acceptance and for landing (§1.1c).
3. **Harden `clive-remote-engineering.service` and protect the loop's own code** (§1.4, §1.6). OWNER-gated.
4. **Loop friction:** fix the `--no-hardlinks` clone fault, add the sandboxed check tool for builders, and repoint the product-memory ref (§1.5).
5. **Wire the Judgment Ledger** for owner decisions, starting with today's (§1.6).
6. **Swift tests on a Mac,** once the Mac's role is recorded (§1.3, §4).
7. **Move the engineering loop to the local server.** OWNER decision; identify the hardware first (§5).
8. **One-kernel first step:** Support Investigator → Gmail draft through kernel and ledger, with the SQLite store arriving at the same time (§2.1, §2.3).
9. **General self-audit,** method only (§2.2).
