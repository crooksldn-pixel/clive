# Deploy record — `dc59047e` on `crooks-os-prod-1`

**Deployed:** 2026-10-14, install 19:46:11–19:46:22 UTC (the service was down from 19:46:13.5,
answering again at 19:46:20.3 — about 7 s).
**Host:** `crooks-os-prod-1`, checkout `/opt/crooks-os`.
**Procedure:** `crooks-assistant/docs/DEPLOY_LINUX.md`, "Deploying a new build".

| | |
|---|---|
| **Deployed SHA** | `dc59047ea462c604bdbe9055ca74b6c85359c348` (PR #124, on `clive/trunk`) |
| **Previous SHA** | `09b633cc8663a821e840917cc2f403dbf319687b` (PR #120) |
| **Build id now live** | `178961cc1877` (was `dbf4ae9d2587`) |
| **Outcome** | Installed and running. `/health` **200** and **every check `ok`** — the first deploy on this host to come up with nothing degraded. One step outstanding: the owner's phone `/whoami`. |

`dc59047e` was the head of `clive/trunk` at the time of the deploy.

## Rollback target

Both halves were captured **before anything changed**:

| What | Where |
|---|---|
| Code | `git -C /opt/crooks-os checkout --detach 09b633cc8663a821e840917cc2f403dbf319687b` |
| Unit — **the copy to restore** | `/root/crooks-unit-before-dc59047e.main.service` (0600, 92 lines, 5014 bytes, sha256 `e9a8ed50…`) |
| Unit — full capture, for the record only | `/root/crooks-unit-before-dc59047e.service` (0600, 119 lines, sha256 `29b95e12…`, `systemctl cat`) |

The live SHA was read from git (`git -C /opt/crooks-os log -1`), not from `CURRENT_TRUTH.md`,
which lags. It read `09b633cc` — the first of the three the deploy prompt allowed for; `7e08af0c`
(PR #122) and `b66d32ef` (PR #123) were never installed here, they are only intermediate commits
in this deploy's own range.

The main-unit-only copy is a byte-exact copy of `/etc/systemd/system/crooks-assistant.service`
taken from the file itself (`cmp` clean against it), not a slice of `systemctl cat` — so it
carries no `# /etc/...` header and no trailing blank. **Restore that one.** The 119-line capture
concatenates the main unit with `10-state-writable.conf`, `objectives.conf` and `scenes.conf`;
restoring it whole would fold the drop-ins into the main unit while they also still exist in
`crooks-assistant.service.d/`, applying them twice, silently. **The drop-ins were not touched**
by this deploy and must not be touched by a rollback.

Rollback, if it is ever wanted:

```bash
git -C /opt/crooks-os checkout --detach 09b633cc8663a821e840917cc2f403dbf319687b
install -m 0644 /root/crooks-unit-before-dc59047e.main.service \
  /etc/systemd/system/crooks-assistant.service
cd /opt/crooks-os/crooks-assistant && make install
```

No `pip install -e .` is needed in that line, unlike the previous deploy's: this build adds no
dependency (below), so `09b633cc`'s tree needs nothing re-pointed.

## What was checked before anything changed

| Check | Result |
|---|---|
| `clive-release.timer`, `clive-release-now.path`, `clive-release.service` | **none exists** (`not-found`), so there was nothing to stop. The release service is still not installed on this host. |
| `clive-trunk-fetch.timer` (which does exist, every 5 min) | left alone: it fetches one ref in `/srv/clive-engineering/repo` and names `/opt/crooks-os` in `ReadOnlyPaths=`. It cannot move this checkout. |
| Live SHA read from git | `09b633cc` — matches the stated rollback target |
| Target SHA present, and on `clive/trunk` | yes; `git branch -r --contains` lists `origin/clive/trunk` |
| Shape of the change | 4 commits, PRs #121–#124; 54 files, +11409/−146. `09b633cc` is an ancestor of `dc59047e`, so a plain fast-forward, no merge (`git merge-base --is-ancestor` confirms) |
| **Acceptance on the exact deployed SHA** | **run `37969677077`, `completed` / `success`**, 37 m 45 s, `headSha` `dc59047ea462…`, single `acceptance` job `success`. See the note on the two cancelled runs below. |
| `make doctor` | exit 0, "All prerequisites present. 17 warning(s)." (the previous deploy saw 8; the extra warnings are unstored WeCom/WhatsApp keys, which are not this deploy's business) |
| `tailnet_self_check()` (read-only, `app/identity.py`) | ok — "this host's own tailnet IPv4 and IPv6 addresses are on `tailscale0` and in its address tables" |
| tailscaled trust preconditions | `/usr/sbin/tailscaled` root:root 755; `/proc/817/exe` resolves to it; cgroup `system.slice/tailscaled.service` |
| `scripts/gap_clean_check.py` on the live record | **"VERDICT: nothing lost"** — 14 rows, every row "kept as it was"; rollback code (`3e77f215`) reads the result: yes |
| Baseline `/health` | **OK — all good**, all 12 checks `ok`, build `dbf4ae9d2587`. Gmail included; see below. |
| `.env` baseline | sha256 `e81225c5…`, 82 lines — the same as at the last two deploys |
| `~/.local/bin/crooks-control` | **absent** (`~/.local/bin` does not exist, and no `crooks-control` on `PATH`), so the `make commands` step was not needed |

### The two cancelled acceptance runs are not a failure

Three `acceptance` runs exist for `dc59047e`: `37969677077` **success**, and `38101693363` and
`38177085019` both **cancelled**. The cancelled pair were killed 3 m 02 s and 3 m 52 s in, against
a suite that takes ~38 minutes, so neither ever reached a verdict. The workflow explains it:

```yaml
concurrency:
  # One run per ref; a superseded commit's run is not worth finishing.
  group: acceptance-${{ github.ref }}
  cancel-in-progress: true
```

The group is keyed on the **ref**, not the commit, and `dc59047e` is also the head of
`experiment/fmhy-link-finder` and `planning/autonomous-engineering-v1`; pushes on those refs
re-ran acceptance on this same commit and were then superseded. The currently-live `09b633cc`
carries the **identical** pattern — `37861192607` success plus `37866756467` cancelled — and was
deployed on that basis. So this is the established reading, not a new allowance: a
concurrency-cancelled run is not evidence of a failure, and the one run allowed to finish on this
exact SHA was green.

### The deploy-sensitive diff is empty

`git diff --stat 09b633cc..dc59047e` over `deploy/`, `Makefile`, `pyproject.toml`,
`install_systemd.py` and `launch_common.py` is **empty** — not one of those paths changed. So:

* **no new dependency.** `pyproject.toml` is untouched, and the new research modules
  (`app.research.synthesis.run`, `app.research.synthesis.ideas`, `app.builds.research_ideas`,
  `app.routes.research`) all import in the existing venv. No `pip install` step was needed or run.
* **no new setting.** `deploy/env.production.example` is untouched, and no `.env` key is newly
  required.
* **the installer and the renderer are byte-for-byte the same code** as the build already running.

By `DEPLOY_LINUX.md` a change under `deploy/`, the Makefile, the installer, the dependencies or
`.github/` is what forces a hand deploy; none of that changed here. This was still done by hand
because the release service is not installed.

### The re-rendered unit is byte-identical to the live one

The gate that would have stopped this deploy. The new build's `rendered_unit()`
(`scripts/install_systemd.py`) was rendered **before** `make install` ran and compared against
`/etc/systemd/system/crooks-assistant.service` as the exact bytes `write_unit()` receives:

```
rendered bytes: 5014   sha256 e9a8ed50e816d40ca93aff4f296cae34dc6b3ca846f9f3856d72f3f5dccd376d
live     bytes: 5014   sha256 e9a8ed50e816d40ca93aff4f296cae34dc6b3ca846f9f3856d72f3f5dccd376d
IDENTICAL — diff empty
```

Which follows from the empty sensitive diff: both the template and the code that renders it are
unchanged. So "code and unit together" holds trivially, and the unit half of the rollback is a
no-op.

## The switches: nothing changed

No `.env` line was changed and no credential was written **by this deploy**. `.env` sha256 is
`e81225c5…`, 82 lines, before and after. The drop-ins' concatenated sha256 is `dba66649…` before
and after, mtimes untouched.

## The install

`make install` → exit 0. Its own gates, in order, all passed:

```
ok     unit → /etc/systemd/system/crooks-assistant.service
ok     crooks-assistant.service enabled (starts at boot)
ok     crooks-assistant.service started
https  https://crooks-os-prod-1.taildfb357.ts.net/  (already configured)
wait   backend starting…
health all good · Claude, ElevenLabs hearing, Shopify, Gmail, instagram, the voice, hearing,
       the knowledge base, writes, proxy_identity, housekeeping
ok     running with --no-proxy-headers, and /health says it can tell who opened each connection
```

That last line is `running_problems()`, which checks three things after the restart and rolls the
unit back if any fail: the running process's own command line has `--no-proxy-headers`,
`/health checks.proxy_identity` is `ok`, and `tailnet_self_check()` still holds. All three passed.
Note the `health` line names **Gmail among the working checks** — the first deploy here where it
does.

The live command line, read back from `/proc/1692674/cmdline`:

```
/opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers
```

`--timeout-graceful-shutdown 10` before `--no-proxy-headers`, as round 11 requires.

## Verification after the install

| Check | Result |
|---|---|
| `scripts/healthcheck.py` | **exit 0** — `OK  all good — no local speech fallback on this host (by design)`, build `178961cc1877` |
| Every check `ok`? | **Yes — all 12.** claude, gmail, housekeeping, instagram, knowledge_base, proxy_identity, scribe, shopify, speech, tts, writes, and `proxy_identity` |
| `GET /ping` | HTTP 200, `{"ok":true,"build":"178961cc1877"}` |
| Service state | `active (running)`, **`NRestarts=0`**, one `MainPID` 1692674, started 19:46:15 — no restart loop. (Judged from `NRestarts`/`MainPID`, not from `/health` `uptime_s`, which is cached and can read backwards.) |
| `.env` | sha256 unchanged (`e81225c5…`) |
| Main unit | sha256 unchanged (`e9a8ed50…`), `cmp` clean against the saved rollback copy |
| Drop-ins | sha256 of the three concatenated unchanged (`dba66649…`) |
| Reports privacy | `crooks-assistant/reports/` is `drwx------`, every report `-rw-------`, **no `.withheld/` at all** (so nothing had to be withheld); the service started, which it refuses to do if it cannot keep reports private |
| Journal since the restart | 37 lines, and **no** error, traceback, exception, `withheld` or `not confirmed on disk` line among them |

Startup was clean: graceful shutdown of PID 3544980 (`Application shutdown complete` 1.1 s after
`Shutting down`, well inside the 10 s drain), clean start of PID 1692674, `Application startup
complete` at 19:46:20.3.

## Gmail is green, and that changed outside this deploy

The previous record left Gmail as one of two outstanding items: its OAuth **refresh token** had
expired or been revoked, and `/health` had been `degraded` on that account since before the
`09b633cc` deploy.

It was re-authorised by hand on **14 October 2026 at 19:36 UTC**, about ten minutes before this
deploy, and the credential now reads:

```
ok    gmail    team@crooksldn.com · compose, modify (verified by Google)
```

That re-authorisation was **not part of this deploy** — it wrote a credential, which a deploy may
not do, and it is recorded here only because it is why the pre-deploy baseline and the post-deploy
verification both read "all good" where every previous record reads "degraded — Gmail". The grant
is in the secret store (`gmail_token`), its scopes are `gmail.modify` and `gmail.compose`, and
Google's `tokeninfo` confirmed them rather than them being taken as stored.

**It will lapse again in seven days** unless the Google consent screen for project
`project-jarvis-508011` is moved out of **Testing**: an app left in Testing issues refresh tokens
that expire after seven days, which `scripts/gmail_auth.py`'s own docstring warns about. Publishing
that consent screen is the fix, and it is the owner's to make. Until then this is a weekly outage.

## The exact-SHA review

`DEPLOY_LINUX.md`'s "Deploying a new build" asks for three things, and what each came to here:

1. **Acceptance green on the exact SHA** — yes, run `37969677077` (above).
2. **The PRs it carries were each independently reviewed before they merged** — this is recorded
   nowhere that can be checked from this host. PRs #121, #122, #123 and #124 each have **zero**
   GitHub reviews and an empty `reviewDecision`, and the engineering loop's own review store
   (`/srv/clive-engineering/state/engineering/reviews`) holds nothing dated later than
   **25 September 2026** — so these four did not come through the loop's reviewed-landing path
   either. This is **not new to this deploy**: PR #120, the currently-live build, is in exactly the
   same position, and the `09b633cc` record stood on the owner's own account that its range had
   been reviewed. The same applies here. It is noted rather than argued, so that the record does
   not read as though a review was verified when it was not.
3. **The owner's approval of that exact SHA** — given as the instruction to deploy
   `dc59047ea462c604bdbe9055ca74b6c85359c348` in the Termius Claude conversation on 14 October
   2026, naming the SHA, the PR, the acceptance run and the expected previous SHA. That instruction
   referred to George in the third person throughout ("George's re-auth", "when George asks"), so
   it was relayed rather than spoken by the owner directly. **If ruling 7 requires the owner's own
   word, this record wants his countersignature.** The deploy was carried out on the instruction as
   given.

The owner's ruling 6 (DEC-071) already removed the separate independent exact-SHA review, and the
`09b633cc` record noted that `DEPLOY_LINUX.md` is out of step with that ruling on this point. It
still is; the edit is still worth making.

`CURRENT_TRUTH.md` was not updated by this deploy. The live SHA is to be read from git.

## What this build changes

4 commits, PRs #121–#124; 54 files, +11409/−146.

- **PR #121** — `CURRENT_TRUTH.md` says what is on the trunk after PRs #109–#120. Documentation.
- **PR #122** — "CLIVE can file a build again: the build status and objective list stay small
  however many there are." The first half of the **"Filing failed: engineering status too large"**
  fix.
- **PR #123** — "Build status names every blocked build it leaves out, and a bad character can't
  stop filing." The second half of it.
- **PR #124** — **DEC-078**: research is evidence for CLIVE's understanding — one idea per
  proposition, with four separate answers, rather than a list of proposals per document. This is
  the bulk of the diff: `app/research/synthesis/*` (`run`, `ideas`, `store`, `quotes`, `words`,
  `migrate`), `app/builds/research_ideas.py`, `app/research/{flow,review}.py`,
  `app/routes/research.py`, `scripts/research.py`, `docs/RESEARCH.md`, and the product-memory
  entries for DEC-078.

**The Research section on the Builds screen looks exactly as it did before this deploy.** DEC-078's
own status line is the reason: it is live "once deployed **and** a synthesis generation is applied
on the server", and the Director compares the first generation against the old screen before it is
applied. Deploying the code changes nothing a user sees until that happens. No generation was
applied here.

## Outstanding

- **The owner's phone `/whoami`.** Open `https://crooks-os-prod-1.taildfb357.ts.net/whoami` on the
  owner's phone; it must answer `"owner": true`, and
  `journalctl -u crooks-assistant.service | grep 'whoami: id=<the check it showed>'` must show
  `through=tailscale owner=true refusal=none` with that same eight-character token. Per the
  procedure the deploy is **kept** only once that line appears with the phone's own token. This was
  outstanding on the previous deploy too and is the one check no request made on the server itself
  can stand in for.
- **This record wants the owner's countersignature** on point 3 above, if his own word is what
  ruling 7 means.
- **Publish the Google consent screen** for `project-jarvis-508011`, or Gmail lapses again within
  seven days.
- **The research synthesis run** was started separately, after this deploy, and is not part of it.
  It reads the six stored documents into ideas and stops at a generation that is *ready, not live*;
  applying it is the Director's call and `--apply` was not run.
