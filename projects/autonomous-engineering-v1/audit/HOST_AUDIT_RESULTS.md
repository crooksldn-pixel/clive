# Host audit results — 2026-10-14

**Window:** 11:40:35–11:45:49 UTC, plus the planning lead's own read-only checks from 11:39 UTC.
**Procedure:** [HOST_AUDIT.md](../HOST_AUDIT.md), followed read-only.
**Public-repository rule:** this repository is public (DEC-071 ruling 1). This record therefore names
services, versions, SHAs and flags. It does not name credential files, credential names, addresses,
ports, or tailnet devices other than the two engineering hosts already named in the docs.

## 1. Which host this is

**`crooks-os-prod-1`: the production host.** The planning SSH session (Claude Desktop, Code tab) runs
on it as root. It is **not** the worker host, and worker capacity must not be inferred from it.

**It runs two things:**

- **Production:** `crooks-assistant.service` from `/opt/crooks-os`, Caddy, and the CROOKS Returns,
  Shipping and Pre-orders containers.
- **A second, older engineering loop:** `clive-remote-engineering.service`, which is enabled and active.

**What can be known about `clive-worker-01` from here:**

- That it is on the tailnet and not offline.
- Everything else comes only from its public status projection,
  `origin/clive/control/worker-01-status`, generated 11:31:28 UTC.
- There is no SSH route from this host to worker-01: `/root/.ssh` holds only `authorized_keys` and
  `known_hosts`.

## 2. SHAs, recorded separately

| Item | Value | Source | Confidence |
|---|---|---|---|
| **Production** | **`09b633cc8663a821e840917cc2f403dbf319687b`** (PR #120), deployed 2026-10-09 00:41 UTC | `/opt/crooks-os` HEAD and reflog (`b33ccbc2 → 09b633cc` at 00:40:58 UTC). The service restarted at 00:41:53 and again at 14:40:54 that day. Deploy record `0de74401`, on branch `claude/deploy-09b633cc-record` only (not on trunk) | High; `/health` was not queried |
| **Trunk** | **`dc59047ea462c604bdbe9055ca74b6c85359c348`** (2026-10-09 18:55 +0100, DEC-078) | `origin/clive/trunk`, refreshed every 5 min by `clive-trunk-fetch.timer` (last at 11:43:10 UTC) | High |
| Trunk vs production | Trunk is 4 commits ahead (`ae865a6c` #121, `7e08af0c`, `b66d32ef` #123, `dc59047e`) | `git rev-list 09b633cc..origin/clive/trunk` | High |
| **worker-01 pin** | **UNKNOWN** | Not in the projection; CURRENT_TRUTH also says "not recorded" | — |
| Production-host loop pin | `4c32bb3d5f4935402c9cdc897914370950f7f206` (2026-09-24), **701 commits behind trunk** | Unit `ExecStart` path, plus `git rev-parse` of that tree | High |

**CURRENT_TRUTH.md is stale on three points.**

- Production is `09b633cc`, not `b33ccbc2`.
- The loop was not "quiet since 1 Oct": requests were filed and landed on 7–8 Oct.
- The production-host loop is still running.

## 3. Toolchain

| Tool | Version | Note |
|---|---|---|
| Claude CLI on PATH (`/usr/local/bin/claude`) | 2.1.276 | Used by the production app |
| Production-host loop's worker CLI (`/srv/clive-engineering/bin/claude`) | 2.1.280 | Dated 2026-09-25 |
| Also installed | `cli/2.1.280`, `cli/2.1.282` | Not referenced by the unit |
| This planning session | 2.1.295 | — |
| Node | v22.23.2 | — |
| npm | 10.9.8 | — |
| Python | 3.12.3 | — |
| git | 2.43.0 | — |
| gh | 2.45.0 | — |
| Sandbox tools | `unshare` present; bubblewrap absent; Docker present | — |
| Browser | Google Chrome 155 at `/opt/google/chrome` | Not bound into the check sandbox root. Playwright cache holds ffmpeg only |
| `claude auth status` | Not run | Avoids printing account identifiers |

None of the CLI versions on this host is one the builder-skills gate accepts (2.1.285, 2.1.293).
Worker-01's CLI version is UNKNOWN.

## 4. Engineering services on this host

| Unit | State | What it does |
|---|---|---|
| `clive-remote-engineering.service` | enabled; active since 2026-10-03 14:49 UTC (reboot) | The production-host loop: pin `4c32bb3d`, **`--max-concurrent 2`**, GPT reviewer only (the pinned source predates the Claude reviewer), worker model `claude-opus-5-5` at high effort. It polls `clive/control/owner-inbox` every 15 s and publishes `clive/control/status` (last 11:36:25 UTC today). Its last real work was 2026-09-25 09:47 UTC. Every tick since shows no dispatcher events. |
| `clive-trunk-fetch.timer` | enabled, every 5 min | Fetches only `clive/trunk` into `/srv/clive-engineering/repo` |
| `crooks-bridge-watcher.service` | disabled, inactive | Legacy ChatGPT-inbox watcher |
| Release service (PRs #101/#116) | **not installed** | — |

**Other legacy trees, all with no running process:**

- Last changed 18–23 Sep: `/opt/crooks-builder`, `/opt/crooks-review`, `/opt/crooks-watcher-review`,
  `/opt/crooks-workers/*`, `/opt/crooks-engineering-state`, `/opt/crooks-interactive`,
  `/opt/crooks-ai-bridge`.
- Last changed 25–26 Sep: `/srv/clive-engineering/{src,state,runtime,workers}`.

**The loop's repository checkout is on the wrong branch.** `/srv/clive-engineering/repo` is currently
checked out on `experiment/fmhy-link-finder`. The production-host loop uses it as `--repo`. It resolves
bases by SHA, so the branch checked out does not change what it builds, but the checkout is shared with
an experiment.

**The production unit's environment** does not name `CROOKS_ENGINEERING_HOST` or
`CROOKS_ENGINEERING_PRIVATE_URL`. If they are set, they are in `.env`, which was not read, so both are
UNKNOWN from here. MAP records `CROOKS_ENGINEERING_HOST=worker-01` from the 2 Oct deploy record.

## 5. Resource envelope (this host only; not the worker)

| Resource | Value |
|---|---|
| CPU | 4 vCPU |
| RAM | 7.6 GiB, no swap |
| Disk | 75 GB root, 26 GB free |
| Load | ~0.2 |

The production-host loop peaked at 3.2 GB memory during its 25–26 Sep run. On this host it shares
memory with production, the containers and the interactive sessions.

**worker-01's documented envelope:** HPE DL360 Gen10, 2× Xeon Silver 4110 (16 cores, 32 threads),
128 GB ECC, RAID 1+0 on spinning disks (INFRASTRUCTURE_2026-09-25.md). That is documentation, not
verification.

## 6. worker-01 facts from its projection only (generated 2026-10-14T11:31:28Z)

| Fact | Value |
|---|---|
| Records | 74 requests: 72 accepted at intake, 2 refused (base did not resolve) |
| Stages | BLOCKED 44 · COMPLETE 26 · OWNER_GATE 2 · waiting 0 |
| Reviewer actually used | **GPT for all 44 verdicts; 0 Claude verdicts.** The Claude reviewer (DEC-076) and the private stops channel's operation are not evidenced on worker-01 |
| Exact-SHA GitHub acceptance | 29 records: 22 green, 7 red |
| Landing | 12 loop self-landings on `clive/trunk` (1–8 Oct); 5 refused (convergence, or trunk moved past the refresh limit) |
| Repair limit | Set per request: 3 on 46 records, 2 on 26 |
| Concurrency | ≥4 builders overlapped on 2026-10-07 23:16–23:30 (inferred from candidate times). The configured value is UNKNOWN; the docs say eight |
| Last request | 2026-10-08 14:57Z |
| Last event | A landing at 2026-10-08 15:35:50Z |
| Heartbeat | Every ~10 min, still live |
| Not exposed | Pin, CLI version, max concurrency, reviewer configuration, Chromium, disk use |

## 7. Runtime classification (host evidence only)

| Capability | Classification |
|---|---|
| Dispatcher lifecycle | **PROVEN** on worker-01 (26 COMPLETE, 12 self-landings) and on this host (23–25 Sep). **ACTIVE** on both (heartbeats) |
| Workspace isolation | **PROVEN** on this host (per-attempt clones). worker-01: workspaces evidenced, including 4 EXDEV hard-link failures |
| Builder session isolation | **PROVEN** on this host (per-attempt session and home, minimal environment, 6 tools, no MCP). worker-01 UNKNOWN |
| Bounded repair | **PROVEN** (journal here; projection on worker-01) |
| Check sandbox | **PROVEN** here at `4c32bb3d`. worker-01 UNKNOWN |
| Browser-capable checks | **GAP** here. worker-01 UNKNOWN. Browser evidence is **PROVEN in exact-SHA CI** (acceptance.yml) |
| Exact-SHA acceptance | **PROVEN** on worker-01 (29 records) |
| Claude reviewer | Not ACTIVE on worker-01 (0 verdicts); **GAP** at this host's pin |
| GPT reviewer | **PROVEN** (44 verdicts on worker-01, last 8 Oct) |
| Remote inbox and status | **ACTIVE** on both |
| Engineering bridge | UNKNOWN (`.env` not read). 7 owner filings from CLIVE on 30 Sep are evidenced in the inbox history |
| Builds surface | BUILT and deployed (production carries it since `cac1a9e7`); runtime UNKNOWN (no HTTP request made) |
| Bench | UNKNOWN |
| Hash-pinned skills | UNKNOWN (worker-01 CLI version unknown) |
| Max concurrency | Here: 2 (ACTIVE). worker-01: ≥4 observed, configuration UNKNOWN |
| Landing enabled | worker-01: **PROVEN** |

## 8. Mutation statement

No fetch, checkout, restart, install, `docker exec`, SSH, curl, or `claude auth status` was run. These
were never read: `.env`, credential or token files, `/proc/*/environ`, and Claude credentials.

**One incidental write.** A read-only `git -C /opt/crooks-os status` let git refresh its index
stat cache, which rewrote `/opt/crooks-os/.git/index` at 11:40:50 UTC. HEAD, refs, the working tree
and the running service are unchanged. Every git command after that ran with `GIT_OPTIONAL_LOCKS=0`.
**Future read-only audits must set `GIT_OPTIONAL_LOCKS=0` from the first command.**
