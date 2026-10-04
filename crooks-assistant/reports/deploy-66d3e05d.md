# Deploy record — 66d3e05d

**2 October 2026, 13:49–14:08 UTC. Host: crooks-os-prod-1 (/opt/crooks-os).**

## The SHA now running

`66d3e05d7c66b80bd2eb72bf17d8c5439c924869` — `clive/trunk`, "Settings and team sign-in:
reachable, kept, and honest when someone is not let in" (PR #89).

It replaced `718fbc41652a47e6538b8e61b3de1a8a290c5b7e`. **No rollback happened.**

`66d3e05d` is a merge commit (parents `14f72538` and `12ddd3e6`). GitHub acceptance run
**37010017833** ("acceptance", finished 13:10:23Z today) was green on **exactly this SHA** —
`headSha` is `66d3e05d7c66b80bd2eb72bf17d8c5439c924869` — so the installed tree
(`b90d3b84be1b638088477417e82c3bd6c5b3304d`) is the tree that passed acceptance and nothing
else. No tree comparison was needed, unlike round 13.

George decided on **2 October 2026** to deploy `66d3e05d` now, **waiving the independent
exact-SHA review and the on-host test run**, on the grounds that GitHub acceptance is green on
this exact SHA. His **ship rule of 30 September — regression-only** — applies, and is what the
one open finding below was judged against. No multi-part review was run.

`docs/DEPLOY_LINUX.md` states that a deploy happens only after an independent exact-SHA review,
and that neither a green acceptance run nor a SHA's place on the unprotected trunk counts as
review. That review was waived for this SHA. Six commits went live
(`718fbc41..66d3e05d`): PR #89 (settings and team sign-in) and PR #90 (Ship24 parcel tracking),
plus their pre-merge commits, a generated-files commit and one loop check commit. The trunk is
unprotected, so green acceptance on the exact SHA is the whole of the assurance these six
commits carry.

## The expected starting SHA was wrong, and why

The deploy instruction expected `/opt/crooks-os` at `87e10c3382c42186c7ce9f31f98efe8cabee146e`
(round 13). It was at **`718fbc41`**. Work stopped there and the owner was asked before anything
was changed. He confirmed `718fbc41` was a sanctioned deploy made on the night of 1 October that
never got its record. The rollback target for *this* deploy was therefore `718fbc41` and the unit
**as it stood at the start of this deploy**, saved to `/root/crooks-unit-before-66d3e05d.service`
— not `/root/crooks-unit-before-718fbc41.service`, which is the unit from before last night's
deploy. See "The 1 October deploy of 718fbc41" below.

## Step by step

| Step | Result |
| --- | --- |
| 1a. HEAD and unit recorded | **pass** — `718fbc41`; unit saved to `/root/crooks-unit-before-66d3e05d.service` (sha256 `e9a8ed50…`, byte-identical to the live unit at the time) |
| 1b. Fetch | **pass** — `clive/trunk` moved `718fbc41..66d3e05d` |
| 1b. Target SHA resolves | **pass** — `66d3e05d^{commit}` is the full SHA above |
| 1b. `87e10c33` is an ancestor | **pass** |
| 1b. `718fbc41` (running) is an ancestor | **pass** — a forward move; nothing reverted |
| 1c. Six switches, before | **pass** — as listed below |
| 1c. `.env` size and mtime | **pass** — 3547 bytes, 30 September 17:53:21 UTC |
| 1c. Tailscale read-only checks | **pass** — all four properties held |
| 1c. Tailnet self-check | **pass** — `tailnet_self_check()` ok, IPv4 and IPv6 |
| 1c. Free disk | **pass** — 35 GB free, 53% used; inodes 15% used |
| 1c. `gap_clean_check.py` as root | **pass** — exit 0, "VERDICT: nothing lost" |
| 1c. venv has `cryptography>=42` | **pass** — 50.0.1 already installed; nothing was installed |
| 2. `make install` | **pass** — exit 0; code and re-rendered unit in one operation |
| 3. `make status` | **pass** — exit 0 |
| 3. `healthcheck.py -v` | **pass** — exit 0, "OK all good" |
| 3. `/health checks.proxy_identity` | **pass** — `true` |
| 3. Running process's own cmdline | **pass** — both flags, in the runbook's order |
| 3. Six switches and `.env`, after | **pass** — unchanged, byte for byte |
| 3. Journal since restart | **pass** — 20 lines, 0 errors, 0 tracebacks, 0 warnings |
| 3. people.json / work list / key store | **one finding** — see "The one open finding" |
| 4. Phone check | **pass** — `id=770a4cd3 through=tailscale owner=true refusal=none`, 18 s after being asked |

## The switches

Identical before and after. No `.env` line was changed: the file's size is still 3547 bytes and
its modification time is still 30 September 17:53:21 UTC, to the nanosecond.

    CROOKS_SCREEN_SNAPSHOTS=false
    CROOKS_LOCAL_OWNER            unset
    CROOKS_WRITES_LOCAL_OWNER=false
    CROOKS_ENGINEERING_HOST=worker-01
    CROOKS_TAILSCALE_VERIFY        unset
    CROOKS_WRITES_ENABLED=true

No credential was moved, added or re-provisioned. `/etc/crooks-os/credentials-parked/` is empty
and has been since 30 September 17:48, before this deploy; round 13 recorded the engineering
inbox credential as parked there, and the engineering-filing change of 30 September moved it.
The unit still carries four `LoadCredentialEncrypted=` entries.

`ship24_api_key` is new in this delta as an **optional** encrypted credential, normally pasted on
the Connections screen rather than provisioned on the unit. Nothing was stored for it, so parcel
tracking reads as not connected, which is the documented behaviour without a key.

## The unit

The re-rendered unit starts uvicorn with both `--timeout-graceful-shutdown 10` and
`--no-proxy-headers`, in that order, and so does the running process, checked against its own
`/proc/<MainPID>/cmdline` rather than the unit file alone:

    /opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app \
      --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers

The re-rendered unit's **content is byte-identical** to the one it replaced (sha256
`e9a8ed50…`); only its modification time moved, to 14:01:21. That is expected and was checked
rather than assumed: `deploy/systemd/crooks-assistant.service` and `scripts/install_systemd.py`
are byte-identical across `87e10c33 → 718fbc41 → 66d3e05d`, so there was nothing in the template
for this delta to change.

## Health

`healthcheck.py -v` exited **0 before and 0 after**, with every check `ok` both times. Unlike
round 13 there was no pre-existing ElevenLabs failure to gate around: `scribe`, `speech` and
`tts` were all `ok` at pre-flight and remain so.

Build id moved `27e11e647512` to `8edac3283036`.

## Journal since the restart

20 lines, 14:01:22 to 14:01:29. **0 errors, 0 tracebacks, 0 warnings**, 0 lines matching
critical or exception. No permission, denial, read-only, `EACCES`, `EROFS`, withheld or refusal
line. No "gap record cleaned at startup" line — the record was already clean, which
`gap_clean_check.py` had predicted ("file unchanged; 11 gap rows before, 11 after"). No
reports-privacy failure. Shopify minted its token, Gmail refreshed, and the Claude provider came
up on `auth=cli`.

## The one open finding: people.json and the work list are on a read-only path

This is **not a regression and does not meet the ship rule's bar for rollback**, but it means
the headline feature of PR #89 cannot work on this host.

`app/runtime.py` configures the two stores at the **parent** of the objectives directory:

    people_store.configure(Path(settings.objectives_dir).parent / "people.json")
    work_store.configure(Path(settings.objectives_dir).parent / "work")

which is `/var/lib/crooks-assistant/people.json` and `/var/lib/crooks-assistant/work`. The unit
runs `ProtectSystem=strict` and grants only three writable paths —
`/opt/crooks-os/crooks-assistant`, `/root`, and `-/etc/crooks-os/secrets` — plus
`StateDirectory=crooks-assistant/objectives`, which makes
`/var/lib/crooks-assistant/**objectives**` writable and leaves its parent read-only.

Verified from inside the running service's own mount namespace (`nsenter -t <MainPID> -m`):

| Path | As the service sees it |
| --- | --- |
| `/var/lib/crooks-assistant` | **read-only** |
| `/var/lib/crooks-assistant/objectives` | writable |
| `/opt/crooks-os/crooks-assistant` | writable |
| `/etc/crooks-os/secrets` | writable |

An `open(…, O_CREAT)` on `people.json` and an `mkdir` of `work`, run in that namespace, both
returned **`EROFS` — Read-only file system**. Both probes were removed; nothing was left behind
and `/var/lib/crooks-assistant/` still holds only `objectives`.

Why it is not a regression, and why the deploy was kept:

- The two broken `configure` lines were **already in `718fbc41`** and are byte-identical in
  `66d3e05d`. They do **not** exist in `87e10c33`. So the fault arrived with last night's
  unrecorded deploy, not with this one, and has been live since 1 October 23:03.
- Nothing that worked before this deploy stops working. The only writes added to these stores in
  `718fbc41..66d3e05d` are the two inside the new route; no previously-working path gains a write
  that would now fail.
- Neither store had been created, so nothing was lost: no `people.json` and no `work/` exist, and
  no write to either has ever succeeded on this host.
- Nothing wrote to them at start-up, which is why the journal is clean. The failure needs a user
  action to appear.

What this costs now: `POST /today/people` is **new in this delta** and is the People tab's "add
someone to the team". It calls `people.note(...)` and then `work.record(...)`, neither guarded
against `OSError`, and `work.record` opens its file directly. So the first time the owner adds a
team member from Settings it will fail on `EROFS` rather than save. The same holds for anything
else that writes the work list. PR #89's validation fixes — accepting `name@github` and
`name@passkey` logins, and treating a card given a login as staff — are correct in themselves and
untested on this host, because the write behind them cannot land.

This wants a fix of its own, in a build of its own. It is one line of unit template either way —
grant `/var/lib/crooks-assistant` or move `StateDirectory` to the parent — and a unit change is
not this deploy's to make. Nothing was changed here.

The **Connections key store is sound**: `/etc/crooks-os/secrets` is `root:root` 0700 with its
three files 0600, writable to the service, and the Gmail token was rewritten there at 14:01 after
the restart — a successful write, which is the evidence that tier works. The app tier
(`<secret dir>/app/<key>.cred`, where a key pasted on Connections lands, including
`ship24_api_key`) does not exist yet because nothing has been stored from that screen; when it is,
`app/secrets/vault.py` creates the folder 0700 and the file 0600 and corrects the folder's mode if
it is wrong. The systemd-creds tier is working: Shopify, ElevenLabs and Gmail all report `ok`,
which they cannot do without decrypting their credentials.

## The phone check

The required line appeared **18 seconds** after the owner was asked to open `/whoami`, well
inside the 10 minutes step 4 allows — unlike round 13, where it took 26 minutes:

    14:07:30 INFO  crooks.identity  whoami: id=770a4cd3 through=tailscale owner=true refusal=none

`through=tailscale`, `owner=true`, `refusal=none`. The check value is **`770a4cd3`**. Matching it
against what the phone displayed as `"check"` is George's to confirm; the journal side is
recorded here. The request was answered `200 OK`, and `GET /` followed a second later, also 200.

**No request from the phone was refused, so no rollback was triggered.**

## The 1 October deploy of 718fbc41

Recorded here because it has no record of its own, and because this deploy started from it.

- **When it ran.** The checkout `87e10c33 → 718fbc41` is in the reflog at **1 October 23:03:40
  UTC**. `718fbc41` itself was authored 1 October 22:24:54 +0100.
- **`make install` completed, and the unit was re-rendered.** The service was stopped at 23:03:41
  and started again at 23:03:43, cleanly ("Deactivated successfully"), and was up within seconds
  — the restart, enable and health gates of `install()` all passed, since any of them failing
  would have rolled the unit back and exited non-zero. The unit file's own modification time is
  **1 October 23:03:40**, the same second as the checkout, so it was rewritten, not left alone.
  Its content, though, is **byte-identical** to `/root/crooks-unit-before-718fbc41.service`
  (sha256 `e9a8ed50…`), the unit saved from before that deploy. That is correct rather than
  suspicious: `deploy/systemd/crooks-assistant.service` and `scripts/install_systemd.py` are
  byte-identical between `87e10c33` and `718fbc41`, so the render had nothing to change. The unit
  before round 13's deploy differs (sha256 `3808af03…`) — that is the one without
  `--timeout-graceful-shutdown`.
- **No `whoami` phone line ever appeared for it.** Between 1 October 23:03 and this deploy's
  restart at 2 October 14:01 there is exactly **one** `whoami: id=` line in the journal, at
  **13:58:48 today** (`id=c6e21a88 through=tailscale owner=true refusal=none`) — about 15 hours
  after that deploy, and three minutes before this one began. So that deploy's step-4 phone check
  was never satisfied in its own window; the owner device's first confirmed pass under `718fbc41`
  came only minutes before it was replaced.
- **Why the service had been running only since 06:21 UTC today**, while the code had been
  `718fbc41` since 23:03 the previous night: **nothing to do with CLIVE**. `unattended-upgrade`
  ran under `apt-daily-upgrade.service` at 06:20:38 and upgraded **openssl, libssl3t64 and
  libssl-dev** (3.0.13-0ubuntu3.15 → 3.0.13-0ubuntu3.16) at 06:20:55, which asked systemd to
  re-execute — `systemd[1]: Reexecuting requested from client PID … (unit
  apt-daily-upgrade.service)` at 06:21:00 — and services were restarted with it at 06:21:01,
  `crooks-assistant` among them, alongside ssh, packagekit, networkd, resolved, timesyncd and
  `clive-remote-engineering`. It was a clean stop and start, not a crash: no watchdog, no OOM, no
  "Main process exited", no "Scheduled restart". `libheif` and `libauthen-sasl-perl` were upgraded
  in the same window and are not implicated.

## Committing this record

`crooks-assistant/reports/` is gitignored (`reports/*`, with only `.gitkeep` exempt), on the
grounds that a report is a record of a run on one machine and not source. This file was added
with `git add -f` because the deploy instructions asked for it at this path.
