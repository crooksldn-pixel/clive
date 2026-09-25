# Infrastructure - 2026-09-25

**Status:** the machines CLIVE runs and builds on as of 2026-09-25, their roles and the lessons learned setting them up. Addresses, serial numbers and credentials are deliberately left out.

## Machines

| Machine | Role | Notes |
|---|---|---|
| `crooks-os-prod-1` (Hetzner VPS, Ubuntu 24.04) | Production: the CLIVE runtime and business credentials | Runs the trunk deployed on 2026-09-25 (`ce791d03`). Also runs a two-builder engineering loop until clive-worker-01 has proven itself; the owner approved moving engineering off it. |
| `clive-worker-01` (HPE ProLiant DL360 Gen10) | Engineering host: an eight-builder loop | 2x Xeon Silver 4110 (16 cores, 32 threads), 128 GB ECC, eight 1 TB 7.2K SAS drives in one RAID 1+0 (3.6 TiB) on a Smart Array P408i-a, iLO 5. Ubuntu 24.04, SSH keys only, firewall, Tailscale. About 96 W idle. |
| The owner's MacBook (M4, 36 GB) | Swift and iPhone app builds and tests, spare builder capacity | A Linux machine under OrbStack (`clive-builder`) hosts a loop; not yet live on 2026-09-25 because its credentials were entered incorrectly. |
| GitHub `crooksldn-pixel/clive` | Transport, trunk, CI on GitHub-hosted runners, product memory | Public on 2026-09-25; making it private is an open owner step. |

Each loop has its own inbox and status branch under `clive/control/` (production host: `owner-inbox` and `status`; clive-worker-01: `worker-01-inbox` and `worker-01-status`; Mac: `mac-inbox` and `mac-status`), its own engineering store, and fetches `clive/trunk` every five minutes.

## Open hardware items on clive-worker-01
- Power supply 2 has no input power; the server runs without redundancy until a cable is connected.
- The iLO administrator password inherited from the previous owner needs changing, and iLO firmware is 1.37 from 2018.
- RAID 10 is not a backup: array alerting and off-box encrypted backups are still to do.

## Lessons from 2026-09-24 and 2026-09-25
- The builder CLI must be pinned to a known version with auto-update off; an automatic update added a built-in plugin the loop's launch check refuses, and every builder launch failed.
- A loop only resolves base commits it has fetched; jobs based on a new trunk commit are refused until the five-minute trunk fetch has run.
- When builders' working copies live in memory, the engineering repository must live on the same filesystem, because git's local clone uses hard links; the repository is re-cloned from GitHub at boot.
- Secrets are entered by the owner through a helper that reads them hidden and reports the length saved; a truncated paste shows up as a wrong length.
- Builders have file tools only: no shell, no deletion, no network. Checks run in a separate sandbox after the builder reports.
- The suite runs about ten times slower from the spinning disks than from memory; test runs on this host belong in memory.
