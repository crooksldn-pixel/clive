# Deploy record — `09b633cc` on `crooks-os-prod-1`

**Deployed:** 2026-10-09, install 00:41:50–00:42:01 UTC (the service was down from 00:41:52,
answering again at 00:41:59 — about 7 s).
**Host:** `crooks-os-prod-1`, checkout `/opt/crooks-os`.
**Procedure:** `crooks-assistant/docs/DEPLOY_LINUX.md`, "Deploying a new build".

| | |
|---|---|
| **Deployed SHA** | `09b633cc8663a821e840917cc2f403dbf319687b` (PR #120, on `clive/trunk`) |
| **Previous SHA** | `b33ccbc29fd48de998abbd7b5bee967d232a0828` (PR #95) |
| **Build id now live** | `dbf4ae9d2587` (was `83524b275b07`) |
| **Outcome** | Installed and running. `/health` **200**, and every check `ok` **except Gmail**, which was already down before this deploy. Two steps outstanding: the owner's phone `/whoami`, and re-authorising Gmail. |

`09b633cc` is not the trunk head: the head at the time of the deploy was `ae865a6c` (PR #121, a
`CURRENT_TRUTH.md` edit). The exact SHA asked for was deployed.

## Rollback target

Both halves were captured **before anything changed**:

| What | Where |
|---|---|
| Code | `git -C /opt/crooks-os checkout --detach b33ccbc29fd48de998abbd7b5bee967d232a0828` |
| Unit — **the copy to restore** | `/root/crooks-unit-before-09b633cc.main.service` (0600, 92 lines, sha256 `e9a8ed50…`) |
| Unit — full capture, for the record only | `/root/crooks-unit-before-09b633cc.service` (0600, 119 lines, `systemctl cat`) |

The live SHA was read from git (`git -C /opt/crooks-os log -1`), not from `CURRENT_TRUTH.md`:
`b33ccbc2`, the first of the three the deploy prompt allowed for. The two SHAs offered on 7 and 8
October were never installed here.

The main-unit-only copy is a byte-exact copy of `/etc/systemd/system/crooks-assistant.service`
taken from the file itself (`cmp` clean against it), not a slice of `systemctl cat` — so it
carries no `# /etc/...` header and no trailing blank. **Restore that one.** The 119-line capture
concatenates the main unit with `10-state-writable.conf`, `objectives.conf` and `scenes.conf`;
restoring it whole would fold the drop-ins into the main unit while they also still exist in
`crooks-assistant.service.d/`, applying them twice, silently. **The drop-ins were not touched**
by this deploy and must not be touched by a rollback.

Rollback, if it is ever wanted:

```bash
git -C /opt/crooks-os checkout --detach b33ccbc29fd48de998abbd7b5bee967d232a0828
install -m 0644 /root/crooks-unit-before-09b633cc.main.service \
  /etc/systemd/system/crooks-assistant.service
cd /opt/crooks-os/crooks-assistant && .venv/bin/pip install -e . && make install
```

The `pip install -e .` is in the rollback line because this deploy added a runtime dependency
(`pypdf`); `b33ccbc2` does not need it, but the editable install must be re-pointed at that
tree's metadata. `make install` rolls the *unit* back itself if any of its own gates fail, but by
its own docstring the code in the checkout is not its to roll back — that is the line above.

Nothing else needs undoing: the gap record was not rewritten (below), and `b33ccbc2`'s code
reads it as it stands.

## What was checked before anything changed

| Check | Result |
|---|---|
| `clive-release.timer`, `clive-release-now.path` | **neither exists** (`not-found`), so there was nothing to stop. Consistent with this deploy not installing the release service. |
| `clive-trunk-fetch.timer` (which does exist, every 5 min) | left alone: it fetches one ref in `/srv/clive-engineering/repo` and names `/opt/crooks-os` in `ReadOnlyPaths=`. It cannot move this checkout. |
| Live SHA read from git | `b33ccbc2` — matches the stated rollback target |
| Target SHA present, and on `clive/trunk` | yes; `git merge-base --is-ancestor` confirms it is on the trunk |
| Shape of the change | 37 commits, PRs #96–#120; `b33ccbc2` is an ancestor of `09b633cc`, so a plain fast-forward, no merge |
| **Acceptance on the exact deployed SHA** | **run `37861192607`, `completed` / `success`**, 34 m 32 s, `headSha` `09b633cc8663…`, single `acceptance` job `success` — every step green, including "Install the pinned browser for the screen tests" and "Run the acceptance gates and record provenance". Artifact `acceptance-09b633cc8663a821e840917cc2f403dbf319687b`, not expired. |
| `make doctor` | exit 0, "All prerequisites present. 8 warning(s)." — the same verdict as the last deploy |
| `tailnet_self_check()` (read-only, `app/identity.py`) | ok — "this host's own tailnet IPv4 and IPv6 addresses are on `tailscale0` and in its address tables" |
| tailscaled trust preconditions | `/usr/sbin/tailscaled` root:root 755; `/proc/817/exe` resolves to it; cgroup `system.slice/tailscaled.service`; that folder and its `cgroup.procs` root-owned |
| `scripts/gap_clean_check.py` on the live record | **"VERDICT: nothing lost"** — 13 rows before, 13 after, every row "kept as it was", *file unchanged*, rollback code (`3e77f215`) reads the result: yes |
| Baseline `/health` | **DEGRADED — Gmail down**; the other 11 checks `ok`; build `83524b275b07`. See "Gmail" below. |
| `.env` baseline | sha256 `e81225c5…`, 82 lines — the same as at the last deploy |
| `~/.local/bin/crooks-control` | **absent** (`~/.local/bin` does not exist, and no `crooks-control` anywhere on `PATH`), so the `make commands` step was not needed |

### The deploy-sensitive diff is what was expected

`git diff --stat b33ccbc2..09b633cc` over `deploy/`, `Makefile`, `pyproject.toml`,
`install_systemd.py` and `launch_common.py`:

```
 crooks-assistant/Makefile                          |  50 ++------
 crooks-assistant/deploy/env.production.example     |  13 +-
 .../deploy/release/clive-release-now.path          |  33 +++++
 .../deploy/release/clive-release.service           |  62 +++++++++
 .../deploy/release/clive-release.timer             |  15 +++
 .../deploy/release/release.env.example             |  18 +++
 crooks-assistant/pyproject.toml                    |  10 +-
 crooks-assistant/scripts/install_systemd.py        |   9 +-
 crooks-assistant/scripts/launch_common.py          | 142 ++++++---------------
 9 files changed, 196 insertions(+), 156 deletions(-)
```

`deploy/release/*` is new and was **not installed** — the four units are files in the checkout
and nothing on this host references them. **Nothing under `deploy/systemd` changed**, which is
the template the unit is rendered from.

### The re-rendered unit is byte-identical to the live one

The gate that would have stopped this deploy. The new build's `rendered_unit()` was rendered
*before* `make install` ran and compared against `/etc/systemd/system/crooks-assistant.service`
as the exact bytes `write_unit()` receives (`rendered_unit().encode("utf-8")`):

```
rendered bytes: 5014   sha256 e9a8ed50e816d40ca93aff4f296cae34dc6b3ca846f9f3856d72f3f5dccd376d
live     bytes: 5014   sha256 e9a8ed50e816d40ca93aff4f296cae34dc6b3ca846f9f3856d72f3f5dccd376d
IDENTICAL — diff empty
```

That is not luck, and the reading of the two changed files bears it out:

* `install_systemd.py`'s nine changed lines are a module docstring, two docstrings and one
  message about the Mac. `rendered_unit()` and `unit_values()` are untouched.
* `launch_common.py` lost the Mac: `LAUNCHD_DIR`, `AGENTS`, `TAILSCALE_APP`, `plist_values`,
  `launchd_path`, `is_macos`, `uid`, `url_port`, and the launchd halves of `service_labels`,
  `restart_services`, `installer_script` and `restart_hint`. Of the names the unit is rendered
  from — `ROOT`, `VENV_PYTHON`, `SYSTEMD_TEMPLATE`, `service_path`, `find_claude`, `render` —
  none changed in behaviour. `find_tailscale()` lost its Mac-bundle fallback, which on this host
  never applied: `shutil.which("tailscale")` answers.

So "code and unit together" holds trivially here, and the unit half of the rollback is a no-op.

## pyproject.toml: the new dependency

`pyproject.toml` adds a runtime dependency, `pypdf>=6.19.0` (for `app/research/pdf_reader.py`),
and `pypdf>=6.0` plus `reportlab>=4.0` to the test-only extra. So, after the checkout and before
`make install`:

```
cd /opt/crooks-os/crooks-assistant && .venv/bin/pip install -e .
```

pip reached PyPI (no STOP), and `Successfully installed crooks-assistant-0.1.0 pypdf-6.19.0`:

```
.venv/bin/python -c "import pypdf; print(pypdf.__version__)"  →  6.19.0
```

6.19.0, so at or past the 6.19 the deploy prompt required. It was absent before
(`ModuleNotFoundError`), which is why it had to be installed rather than upgraded.

## The switches: nothing changed

No `.env` line was changed and no credential was written. `.env` sha256 is `e81225c5…` before
and after, unchanged. `CROOKS_WHISPER_ENABLED` and `CROOKS_STT_PRIMARY` are both still in the
server's `.env` and were **left exactly as they were**; this build ignores them as it ignores any
unknown key, which `deploy/env.production.example` now says in place of the two lines it dropped.
That example file is not read by the running service.

## The install

`make install` → exit 0. Its own gates, in order, all passed:

```
ok     unit → /etc/systemd/system/crooks-assistant.service
ok     crooks-assistant.service enabled (starts at boot)
ok     crooks-assistant.service started
https  https://crooks-os-prod-1.taildfb357.ts.net/  (already configured)
wait   backend starting…
health partly down · working: Claude, ElevenLabs hearing, Shopify, instagram, the voice,
       hearing, the knowledge base, writes, proxy_identity, housekeeping · NOT working: Gmail
ok     running with --no-proxy-headers, and /health says it can tell who opened each connection
```

That last line is `running_problems()`, which checks three things after the restart and rolls the
unit back if any fail: the running process's own command line has `--no-proxy-headers`,
`/health checks.proxy_identity` is `ok`, and `tailnet_self_check()` still holds. All three passed.

The live command line, read back from `/proc/<MainPID>/cmdline`:

```
/opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers
```

`--timeout-graceful-shutdown 10` before `--no-proxy-headers`, as round 11 requires.

Note that the `health` line in that output already has **no whisper check** in it, and names
Gmail as the one thing not working.

## Verification after the install

| Check | Result |
|---|---|
| `GET /health` | **HTTP 200**, `"status":"degraded"`, build `dbf4ae9d2587`, 11 checks |
| Every check `ok`? | **No — `gmail` is `false`.** The other ten are `ok`. Gmail was down before this deploy too; see below. |
| **No whisper check** | confirmed — `"whisper" in checks` is `False` (it was `ok`/disabled on the old build, one of 12). `checks["speech"]` carries `redundancy: "none"` and reads "scribe_v2 · no local fallback on this host (by design)". |
| **No pad block** | confirmed — no `pad` key at `/health` top level or in `checks`, and no key anywhere in the document containing "pad" |
| `GET /ping` | HTTP 200, `{"ok":true}`, build `dbf4ae9d2587` |
| `scripts/healthcheck.py -v` | `DEGRADED  working, but down: Gmail` — the same one failure as the pre-deploy baseline, and the same verdicts on everything else |
| Service state | `active (running)`, `NRestarts=0`, one `MainPID` 3296161, uptime climbing — no restart loop |
| `.env` | sha256 unchanged (`e81225c5…`) |
| Main unit | sha256 unchanged (`e9a8ed50…`), `cmp` clean against the saved rollback copy |
| Drop-ins | sha256 of the three concatenated unchanged (`dba66649…`), mtimes untouched |
| Switches | untouched — no `.env` line and no credential written |
| Reports privacy | `crooks-assistant/reports/` is `drwx------`, every report `-rw-------`, **no `.withheld/` at all** (so nothing had to be withheld); the service started, which it refuses to do if it cannot keep reports private |
| Gap record | no `gap record cleaned at startup` line in the journal, and `gaps.json` mtime is still 2026-10-02 21:47 — nothing written to an already-clean record, as round 9 specifies |
| Journal since the restart | 45 lines, and no error, traceback, unexplained refusal, `withheld` or `not confirmed on disk` line among them. The only refusal lines are the ones the read-only checks below *provoked* — two `/hooks` refusals, three `/pad` and one `/definitely-not-a-route-xyz` owner-rule refusals, and the `/whoami` line — each matched to a request made here. |

Startup was clean: graceful shutdown of PID 94587, clean start of PID 3296161, test-session and
interaction records opened, Claude provider ready on `auth=cli`, Shopify token minted
(`expires_in=86399`).

### The screens kept polling

`scr_59ec76128358` resumed within a minute of the restart — `GET /displays/scr_59ec76128358?v=58`
→ `204 No Content`, three at 00:42 and three at 00:43 — with the **same screen id and the same
`v=58`**, so it kept its name and its approval and was not re-named. `displays.json` was rewritten
at 00:42.

The cadence is bursty with long gaps, and that is how it was before the deploy too: polls
clustered at 00:15, 00:31, 00:34 and 00:35 before the restart (a 16-minute gap among them) and at
00:42 and 00:43 after it. A quiet few minutes is this screen's normal, not a stall.

No one-time `/display` reload is needed: that belongs to the first deploy carrying round 10, which
is long past. Round 10's own mechanism applies instead — the pages open on the TVs are from
`83524b275b07`, so each will reload itself once it is resting on its clock.

### The `/whoami` journal line works

A request the server made to itself over the HTTPS tailnet route answered HTTP 200 with
`"check":"7eda15c4"`, `"through":"this_host"`, `"owner":false`, and the journal carried the
matching line:

```
00:45:53 INFO crooks.identity whoami: id=7eda15c4 through=this_host owner=false refusal=not_authorised_local
```

Exactly what the procedure says a server-to-self request should look like. It confirms the route
is up and that the token-matching works — it is **not** the owner-device check, which only a real
phone can give.

## Gmail is down, and it was down before this deploy

**This is the one way the deploy misses "every check ok", and the deploy did not cause it.**

The pre-deploy baseline, taken before anything changed and on the old build `83524b275b07`,
already read:

```
DEGRADED  working, but down: Gmail  (build 83524b275b07)
  DOWN  gmail   Gmail check failed: EOF occurred in violation of protocol (_ssl.c:2417)
```

Repeated three times, the same answer each time. After the deploy the check still fails, but the
new process says why:

```
  DOWN  gmail   Gmail refresh was rejected (('invalid_grant: Token has been expired or revoked.', …
```

So the cause is the stored Gmail OAuth **refresh token**, which has expired or been revoked. The
old build's TLS `EOF` was the same outage reported less usefully; a fresh process got the real
answer from Google. It is not a network block on this host: a plain TLS request from the service's
own venv reaches `gmail.googleapis.com` and is answered `401 Unauthorized` without a token, and
`oauth2.googleapis.com` resolves and completes its handshake.

It is also not `gmail_token` going missing — `make doctor` reports `gmail_token stored (file)` and
`gmail credential stored`. The token is there; Google will no longer refresh it.

When it was last well: the journal has `tool=gmail_search` succeeding and two Gmail proposals
reaching `VERIFIED` on **7 October at 17:08**. So the grant lapsed between then and now, before
this deploy.

**Nothing was done about it here.** Repairing it means a new OAuth grant — `make gmail` /
`make gmail-verify` — which stores a credential, and this deploy was to change no `.env` line and
no credential. It is the owner's to do, and it is listed under Outstanding.

Everything downstream of Gmail is affected while it lasts: reading the inbox, drafting and sending
replies, and the Gmail half of the team's five permitted writes.

## The read-only checks

Nothing was changed and nothing was stored for any of these.

**(a) Builds has a Research section and its Deploy card; Settings has Test bench (`/bench`).**
Confirmed. `web/index.html` loads both panels — `<script src="/static/research.js">` ("Its
Research section … which the Builds screen places under its heading") and
`<script src="/static/deploy.js">` ("Deploy now … which the Builds screen places straight under
its heading") — and `web/builds.js` places them:

```
483:  if (globalThis.CliveResearch && typeof globalThis.CliveResearch.place === 'function') globalThis.CliveResearch.place(U.scroll);
486:  if (globalThis.CliveDeploy   && typeof globalThis.CliveDeploy.place   === 'function') globalThis.CliveDeploy.place(U.scroll);
```

Their routes answer too: `/objectives/research`, `/objectives/research/{answer,prepare,upload}`
and `/objectives/builds`, `/objectives/builds/{board,decide,decisions}`. Settings carries Test
bench in its "Connections and team" section, `web/index.html:315`:

```html
<a class="orow olink" role="listitem" id="open-bench" href="/bench"><span class="oname">Test bench</span>…
```

and that row is in the shell the server actually serves (`GET /` → 200, and "Test bench" is in
the body). `/bench` and five `/bench/*` routes exist, and `research.js`, `deploy.js`, `builds.js`
and `bench.html` are all served 200 from `/static/`.

**How this was checked, and its limit:** by the documents and assets the running service serves
plus its own route table, not by a browser render. Every screen route refuses a request made on
the server itself (`not_authorised_local`, below), so a render from this host would show a refusal
rather than the screens, and the owner's own device is the only thing that can see them. The
screen tests in a real Chromium are what acceptance run `37861192607` ran green on this SHA.

**(b) Connections lists WeCom, WhatsApp, CLIVE Shipping and CROOKS Returns' Events secret as not
connected.** Confirmed, read from `app/connections/catalog.py` against the secret store, reading
presence only and never a value:

| Connection | Keys it needs | Stored |
|---|---|---|
| WeCom | `wecom_corp_id`, `wecom_agent_id`, `wecom_app_secret`, `wecom_callback_token`, `wecom_encoding_aes_key` (+ optional `wecom_kf_secret`) | none → **not connected** |
| WhatsApp | `whatsapp_phone_number_id`, `whatsapp_business_account_id`, `whatsapp_access_token`, `whatsapp_app_secret`, `whatsapp_verify_token` | none → **not connected** |
| CLIVE Shipping | `crooks_shipping_read_key`, `crooks_shipping_write_key` | none → **not connected** |
| CROOKS Returns | `crooks_returns_read_key`, `crooks_returns_write_key` | none → **not connected** |
| CROOKS Returns → **Events secret (optional)** | `crooks_returns_hook_secret` | **not stored** |

**(c) The two hooks answer 403 with an empty body.** Both confirmed, `content-length: 0` and zero
bytes read back:

```
GET  /hooks/wecom    → HTTP/1.1 403 Forbidden · cache-control: no-store · content-length: 0
POST /hooks/returns  → HTTP/1.1 403 Forbidden · cache-control: no-store · content-length: 0
```

The journal names each: `hooks: refused a wecom request (unconfigured); 1 so far` and
`hooks: refused a returns request (unset); 1 so far` — refused for want of keys, which matches (b).

**(d) `/pad` — it answers 403 here, not 404, and the Pad is nevertheless gone.** This is the one
observation that did not come out as the deploy prompt expected, so what is true:

* The Pad route **does not exist**. It is in none of the 129 paths the running app documents, and
  nothing matching `pad` is in its route table.
* The 403 is the owner rule, which runs **before** routing and so answers for paths that do not
  exist at all. `GET /definitely-not-a-route-xyz` — which certainly is not a route — answers 403
  too, with the same body:

```
GET /pad                        → 403   {"error":"not allowed","who":"not the owner","code":"not_authorised_local",…}
GET /definitely-not-a-route-xyz → 403   (the same)
GET /ping  (public)             → 200
```

So a request made **on the server itself** cannot see a 404 for anything, and the 404 the deploy
prompt expects is what the owner's own device will get, past the owner rule, for a route that is
no longer there. Worth knowing for the next deploy's checks: from this host, `/pad` answering 403
is the expected answer and is not evidence the Pad survived.

**(e) Is an Instagram token stored?** **No.** `instagram_access_token` is not stored, nor are
`instagram_app_id`, `instagram_app_secret` or `instagram_webhook_verify_token`. `/health` reads
`instagram: not connected (no instagram_access_token stored)` and `make doctor` reports it not
stored. No value was read or printed.

## The exact-SHA review

`DEPLOY_LINUX.md` still says a production deploy "happens only after an independent exact-SHA
review of that SHA", and that neither a green acceptance run nor the SHA's place on the trunk
counts. **The owner waived it, and his ruling 6 makes the waiver the standing rule rather than a
one-off.** That is his call, recorded here rather than argued, and noted only so the record does
not read as though a review happened.

What stands behind this build instead, on his account of it: every PR in the range #96–#120 was
independently reviewed before it was merged, every finding fixed with a test, and acceptance is
green on this exact SHA (run `37861192607`). The procedure document is now out of step with the
ruling on this point, which is worth an edit to `DEPLOY_LINUX.md` when someone is next in it.

`CURRENT_TRUTH.md` was not updated by this deploy. The live SHA was taken from git.

## Outstanding

- **The owner's phone `/whoami`.** Open `https://crooks-os-prod-1.taildfb357.ts.net/whoami` on the
  owner's phone; it must answer `"owner": true`, and
  `journalctl -u crooks-assistant.service | grep 'whoami: id=<the check it showed>'` must show
  `through=tailscale owner=true refusal=none` with that same eight-character token. Per the
  procedure the deploy is **kept** only once that line appears with the phone's own token.
- **Gmail needs a new grant.** The refresh token has expired or been revoked (above). `make gmail`
  then `make gmail-verify`. Until then `/health` stays `degraded` and nothing of CLIVE's that
  touches the inbox works.

## What this build changes

37 commits, PRs #96–#120; 1145 files, +74065/−159221. The deletions are the bulk of it, and one
commit carries most of them — PR #113, "Retire Split, the Mac runtime, local Whisper, the Pad and
Easyship (rulings 24, 37–40)". The Mac runtime (`mac/`, the CROOKS Control menu-bar app,
`launchd/`, `install_launchd.py`) and the local Whisper client went on the rulings of 8 October
that `DEPLOY_LINUX.md` now cites (DEC-071, rulings 38 and 39; DEC-058, the Mac is not a CROOKS OS
host), and the Pad (`android/.../com/crooks/pad/`) went with them. Verified against the trees:
those paths exist at `b33ccbc2` and are gone at `09b633cc`. `DEPLOY_LINUX.md` was rewritten
around it: one host, one installer, one recogniser with no local fallback.

What that costs and what it does not: the Mac is no longer a rollback path, and this record's
rollback target is the previous SHA on this host. The server's own arrangements — the unit, the
drop-ins, the secret tiers, the owner rule, the Tailscale route — are untouched, which the
byte-identical unit above is the evidence for.

The head of the range, PR #120, is the one the commit is named for: staff join CLIVE with a link
and a code from George, on `team.crooksldn.com` (DEC-075, ruling 35).

Also in it, and visible in the checks above: the Builds screen's Research section and its Deploy
now card (DEC-072), the Test bench on Settings, the WeCom and WhatsApp connections, CLIVE Shipping
and CROOKS Returns as connections with their own keys, the Returns Events secret and the
`/hooks/returns` route it guards (DEC-077), and `pypdf` for reading the research PDFs George gives
CLIVE.

The release service (`deploy/release/*` — `clive-release.timer`, `clive-release-now.path`,
`clive-release.service`, `release.env.example`) arrived in the checkout with this build and is
**not installed**; neither unit exists on this host.
