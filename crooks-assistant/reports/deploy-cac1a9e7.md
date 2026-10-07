# Deploy record — `cac1a9e7` (PR #94, the overnight build)

**Host:** `crooks-os-prod-1` (`/opt/crooks-os`)
**Deployed:** 2026-10-03, 13:01:16–13:01:21 UTC (service stop → ready)
**Deployed by:** the owner's prompt, via Claude Code, following `crooks-assistant/docs/DEPLOY_LINUX.md`
**Outcome:** installed and healthy. **Not yet "kept"** — the two owner-device checks below are outstanding.

---

## What was live before

| | SHA | Build id |
|---|---|---|
| **Before** | `4d2dc00f0cd3ef17ff04e885c595ae9cacbb662b` — "Land claude/voice-settings-on-connections onto trunk" | `1c46b5c080da` |
| **After** | `cac1a9e7dede7fecd5d9deaf3d408d2184e75336` — "Overnight build: Connections, recording, team, customers, builds (PR #94)" | `fdf72e24cc1e` |

`healthcheck.py` exited 0 on the before-SHA, so the rollback target is known good.

**Rollback target:** `4d2dc00f0cd3ef17ff04e885c595ae9cacbb662b` plus the unit saved at
`/root/crooks-unit-before-cac1a9e7.service` (119 lines; `ExecStart` carries
`--timeout-graceful-shutdown 10 --no-proxy-headers`; all four `LoadCredentialEncrypted=` lines
including `github_engineering_inbox_token`).

**Read that saved file carefully before restoring it.** It is `systemctl cat` output, so it is the
main unit *concatenated with its three drop-ins* — `10-state-writable.conf`, `objectives.conf` and
`scenes.conf`, each introduced by a `# /etc/...` header line. Restoring the whole file as
`crooks-assistant.service` would fold the drop-ins into the main unit while they also still exist
on disk, applying them twice. The drop-ins are not touched by a deploy; only the main unit is
re-rendered. So a main-unit-only copy was saved beside it:

- `/root/crooks-unit-before-cac1a9e7.service` — full `systemctl cat` output, for the record;
- `/root/crooks-unit-before-cac1a9e7.main.service` — lines 1–94, the main unit alone, **this is the
  one to restore**.

For what it is worth, the re-rendered unit turned out to be byte-identical to the pre-deploy main
unit apart from one trailing blank line (`diff` reports only `93d92`): same `ExecStart`, same four
credential lines. The unit half of this deploy was a no-op.

Note: `docs/product-memory/CURRENT_TRUTH.md` still named `87e10c33` as production when this deploy
began. It was stale by several landings; the live checkout was `4d2dc00f`. Worth correcting.

## The review gate, and the waiver

`DEPLOY_LINUX.md` ("Deploying a new build") requires an independent exact-SHA review, and says in
terms that neither a green acceptance run nor the SHA's place on the trunk counts, because the trunk
is unprotected. **`cac1a9e7` had no such review:**

- PR #94 merged into `clive/trunk` with `reviews: []` — zero reviews — at 12:50:23Z, **27 seconds**
  before the acceptance run for this SHA started;
- the diff against production was **137 files, +24,962 / −1,247**;
- it touches the surfaces the ship rule names: `app/support/redact.py`, `app/tools/gate.py`,
  `app/tools/shopify_writes.py`, new `app/families/checkout_link.py` (+468), new
  `app/observability/interactions.py` (+832, on by default), new `app/customers/*` (~1,500).

This was put to the owner before anything was installed. **The owner waived the exact-SHA review and
asked for the deploy to proceed**, as he did for round 13 (CURRENT_TRUTH: "the owner waived a further
exact-SHA review at 22:23"). The waiver is the authority for this deploy; no review was run.

A spot-check of the three smallest high-risk diffs was done before installing, and found nothing
blocking — it is **not** a substitute for the review:

- `redact.py` now strips `CARD_ONLY` (card brand, last four) from refund rows before they leave;
- `shopify_writes.py` keeps the refund on the `Prepared` path, so nothing sends without a confirmed
  card; the change only drops the customer's held story after a refund;
- `gate.py` adds one read-only tool, `interaction_review`, with no mutation verb and no store, inbox,
  screen or message reachable from it.

## Pre-deploy checks (read-only, before anything changed)

| Check | Result |
|---|---|
| Acceptance on the exact SHA | **completed · success** — [run 37124177410](https://github.com/crooksldn-pixel/clive/actions/runs/37124177410), `head_sha=cac1a9e7…`. It was `in_progress` when the deploy was asked for and was waited out. |
| `app/identity.py` `tailnet_self_check` | **pass** — "this host's own tailnet IPv4 and IPv6 addresses are on tailscale0 and in its address tables" |
| `scripts/gap_clean_check.py` | **pass** — 13 gap rows before, 13 after, file unchanged, rollback code (`3e77f215`) reads the result. VERDICT: nothing lost |
| Live unit saved | `/root/crooks-unit-before-cac1a9e7.service` |
| Working tree | clean before checkout |
| Switches / `.env` / credentials | **untouched**, as the runbook requires |

The new writable paths both fall inside the unit's existing `ReadWritePaths`
(`/opt/crooks-os/crooks-assistant` for `logs/interactions/`, `/var/lib/crooks-assistant` for the
objectives folder), so `ProtectSystem=strict` needed no unit change for them.

## The install

`git checkout --detach cac1a9e7…` then `make install`, which **exited 0** — its automatic rollback
did not fire. It reported:

- unit written to `/etc/systemd/system/crooks-assistant.service`, enabled, started;
- `health all good` across offline hearing, Claude, Shopify, ElevenLabs hearing, Gmail, instagram,
  the voice, hearing, the knowledge base, writes, `proxy_identity`, `housekeeping`;
- "running with `--no-proxy-headers`, and /health says it can tell who opened each connection" —
  both halves of the check the runbook demands (the process's own `/proc/<MainPID>/cmdline` and
  `checks.proxy_identity`).

Running command line, confirmed afterwards:

```
/opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers
```

`ActiveState=active`, `SubState=running`, `NRestarts=0`, `MainPID=1173215`.

## Post-deploy checks

### 1. `/health` is 200 — **pass**

`HTTP 200` on loopback. `healthcheck.py -v` exits 0: "all good — no local speech fallback on this
host (by design)", build `fdf72e24cc1e`. Every check `ok`, including `proxy_identity`
("uvicorn started with --no-proxy-headers"), `writes` ("ready"), `housekeeping` ("last pass 17s
ago"), and `whisper` correctly "disabled … no local recogniser on this host". No check went from
green to red against the before-SHA.

### 2. The phone's `/whoami` journal line — **OUTSTANDING, needs the owner's phone**

Not verifiable from the server, by design. The only `/whoami` line since the install is this
record-taking loopback probe:

```
whoami: id=6d9ae683 through=direct owner=false refusal=not_authorised_local
```

which is exactly what the runbook says a request the server makes to itself must say. The required
line — `through=tailscale owner=true refusal=none`, carrying the phone's own eight-character
`check` token — can only be produced by opening `/whoami` on the owner's phone over
`https://crooks-os-prod-1.taildfb357.ts.net/`. **Per the runbook the deploy is kept only once that
line appears with the phone's own token.** Until then this deploy is installed, not kept.

### 3. The two new write surfaces — **pass**

- **`logs/interactions/`** — created at 13:01, folder `drwx------` (0700), containing
  `active.json` at `-rw-------` (0600). The day file is `ts-<day>.jsonl`, created on the first
  recorded turn; `app/observability/timeline.py` opens it
  `os.open(path, O_WRONLY|O_CREAT|O_APPEND, 0o600)`, so one file a day at 0600 is enforced at
  creation, not by a later `chmod`. Bounded by `CROOKS_INTERACTION_RECORD_KEEP_DAYS=7` and
  `CROOKS_INTERACTION_RECORD_DAY_MB=16`.
- **the objectives folder / `owner-judgments.jsonl`** — `/var/lib/crooks-assistant/objectives` is
  `drwx------` root and writable by the service: proved with a throwaway probe file, created and
  removed. The ledger itself is created lazily on the owner's first build decision
  (`app/builds/decisions.py` `LEDGER_NAME`, via `JudgmentLedger.append`); confirmed by constructing
  the real ledger class against a temp copy. **No judgment row was written to the production
  ledger** — fabricating an owner judgment to make a check go green would have been a false record.

### 4. `/connections`, `/today` and the Builds screen — **OUTSTANDING, needs the owner's device**

Not verifiable from the server, by design, and deliberately not forced. All four of
`/connections`, `/today`, `/builds` and `/objectives/builds/decisions` answer `403` on loopback with:

```
{"error":"not allowed","who":"not the owner","code":"not_authorised_local",
 "detail":"Requests made on the server itself may not use this
 (CROOKS_LOCAL_OWNER or CROOKS_WRITES_LOCAL_OWNER)."}
```

That is the correct refusal, not a regression: `CROOKS_LOCAL_OWNER` is unset and
`CROOKS_WRITES_LOCAL_OWNER=false`, so the host cannot act as the owner. It is **not** the round-10
`403 reload`. The owner rule fires ahead of routing, so a nonsense path answers `403` too and the
status code cannot be used to prove a route exists.

The repo's own browser checks (`scripts/browser/{connections,builds,customers,team,recording}.js`)
drive a **test** backend on `:8765` with spoofed `Tailscale-User-Login` and `X-Forwarded-For`
headers. They were **not** pointed at production: forging owner identity against the live host is
the one thing `--no-proxy-headers` and the local-owner rule exist to prevent, and it would not have
worked. What can be said from the server is that the new assets are in place — `web/builds.js`
(24,804 B) and `web/connections-view.js` (24,187 B), both written 13:01.

So the three screens must be opened on the owner's own device, over the tailnet HTTPS address.

### No settings were needed

Confirmed against `deploy/env.production.example`: the interaction record ships
`CROOKS_INTERACTION_RECORD=true` and is on unless set false, and the redesigns, customer lookup and
history, checkout links on hold and refund status need no new line. The server's `.env` was not
edited, and no credential was touched.

### The journal is clean

No traceback, `ERROR`, `CRITICAL` or failure since the install, other than the expected
`not_authorised_local` refusals of this record-taking's own loopback probes. `NRestarts=0`.

## Ship rule

The rule in force is regression-only (`OWNER_DECISIONS_2026-09-30.md`): block on a regression, a
shown customer-data leak, or a write or send the owner did not confirm. **Nothing found here blocks**
— no check regressed against `4d2dc00f`, no customer data was shown to leak, and nothing was written
or sent unconfirmed. Two checks are unrun rather than failed, and both need an owner device.

## If a rollback is wanted

```bash
systemctl stop crooks-assistant
git -C /opt/crooks-os checkout --detach 4d2dc00f0cd3ef17ff04e885c595ae9cacbb662b
# the main unit alone; leave the three drop-ins in place
install -m 0644 /root/crooks-unit-before-cac1a9e7.main.service \
  /etc/systemd/system/crooks-assistant.service
systemctl daemon-reload && systemctl start crooks-assistant
cd /opt/crooks-os/crooks-assistant && .venv/bin/python scripts/healthcheck.py -v
```

Because the unit was effectively unchanged, `git checkout` of the old SHA followed by
`make install` is the other way, and re-renders the same unit from the old checkout.

The gap record needs nothing: `gap_clean_check.py` reported the file unchanged, and the rollback
code reads it as it stands.
