# The release service

**What it is.** A small program on the production host (`crooks-os-prod-1`) that deploys CLIVE the
way the Termius Claude does today: `docs/DEPLOY_LINUX.md`, "Deploying a new build", step by step,
with the same checks and the same record. It starts **the moment George approves a deploy in CLIVE**
(a systemd path unit watching the folder his approval is written into), and every five minutes from
a systemd timer as well.

**Why.** George, 7 Oct 2026, wants deploys "to just happen (or fix themselves) without him relaying
commands between Claude and the Termius Claude". He approved exactly: "Release service. I build it
tonight, switched off. It only deploys once you've said who holds deploy authority." (DEC-067).

**Where it stands.** Built and tested in the repository (`app/release/`, `deploy/release/`).
**Not installed** on the server, and **off** by default twice over: `CLIVE_RELEASE_ENABLED` is off,
and `CLIVE_RELEASE_RULE` is `off` in the code; and even then it is a dry run until
`CLIVE_RELEASE_DRY_RUN=false` is written in so many words. Production keeps being deployed by hand
until all three are set and the units are installed.

**What George decided on 8 October** ([DEC-071](product-memory/DECISIONS.md), rulings 6 to 8; how it
works: DEC-072):

- **Ruling 6:** the exact-SHA review is no longer required before a deploy. What is: green
  acceptance on the exact SHA, the pull requests' own independent reviews before they merged, and his
  approval (DEPLOY_LINUX.md, "Deploying a new build").
- **Ruling 7:** he approves each deploy, and his approval deploys at once: "i want to say yes to
  deploy - but, once deploy should be instant, not deploy and then the deploy service runs and takes
  hours. deploy as in, implement this now". So the rule is **`CLIVE_RELEASE_RULE=owner_waiver`**, and
  CLIVE's Builds screen has a **Deploy now** card: his hold, his passkey, and the deploy starts.
- **Ruling 8:** the service goes on, **in dry run**, after the next hand deploy (the one that carries
  this). Dry run stays the code default; he switches it off himself when its plans have matched.

---

## What starts a tick

- **George's approval** (DEC-072). His hold and passkey on CLIVE's Deploy now card make CLIVE write
  the approval into `/var/lib/crooks-assistant/objectives/release-waivers/<sha>.json`, CLIVE's own
  state folder. `clive-release-now.path` watches that folder (`PathChanged=`), and systemd starts one
  tick of `clive-release.service` at once: no timer wait. CLIVE needs no root for this and never starts
  a unit. It does run as root today, temporarily (`crooks-assistant.service` says so); the service's own
  checks do not depend on that: it believes only his passkey's signature, and reads CLIVE's folder as
  plain files only (no links, no pipes, at most 64 KiB each). When CLIVE moves to its own user, that
  user must own `release-waivers/` (the path unit creates it root's, 0700).
  An approval that lands while a tick is already running (systemd folds the start into it) is seen by
  that tick, which looks once more if it began no deploy itself.
- **The timer**, every five minutes, as before: the fallback if the path unit is not installed, and
  what notices everything else (a new trunk head, a halt removed).

A deploy itself takes minutes: the checks, `make install`, CLIVE's restart, 20 s to settle, then the
health and journal checks.

## What it does on each tick

1. **Off, or no rule named:** it writes one status line ("The release service is off…") and stops.
   It does not read GitHub or touch the checkout.
2. **Halted** (an earlier rollback failed, or an earlier deploy was stopped part way): it says so and
   stops, until a person removes `/var/lib/clive-release/HALT`.
3. **One at a time:** it takes `/var/lib/clive-release/deploy.lock`. A tick that finds it held does nothing.
   Holding the lock, it looks for a **started marker** (`deploys/<sha8>/started`), which a deploy writes
   before it changes production and removes once its outcome is on disk. One still there means the
   last deploy was stopped part way (a reboot, `systemctl stop`, systemd's time limit) with production
   perhaps half changed: the tick writes `HALT`, marks that SHA in `failed/`, and stops. It never reads
   that half-changed production as "up to date". It reads `HALT` again just before deciding, so a
   `HALT` written while it waited or read the facts still stops it.
4. **Reads the facts, changing nothing on production** (`app/release/facts.py`):
   - `clive/trunk`'s head, fetched into the service's own copy of the repository
     (`/var/lib/clive-release/repo.git`), never into production's checkout;
   - what production runs, from git in `/opt/crooks-os` (never from a document), and whether that
     checkout has local changes;
   - that production is behind the trunk's head on the trunk (a forward move only), and which paths
     the change touches;
   - GitHub `acceptance` on exactly that SHA, by the gate the build loop already uses
     (`app/orchestrator/github_acceptance.py`): every acceptance run for the SHA completed with
     success, and its acceptance job ran on that SHA;
   - the authorisation George's rule asks for (below).
5. **Decides** (`app/release/decide.py`). It deploys only when every one of these holds; each that
   does not is a sentence in the status line and the journal:
   - switched on, a rule named, not halted, running from its pinned copy, the lock free;
   - every fact read; the SHA is `clive/trunk`'s head; production is behind it on the trunk;
   - production's checkout is clean;
   - the change does not touch how CLIVE is installed: `deploy/`, the `Makefile`,
     `scripts/install_systemd.py`, `scripts/launch_common.py`, `pyproject.toml`, `uv.lock`,
     `requirements*` or any `.env` file. Those stay hand deploys, because `make install` installs no
     dependency and a program cannot judge, as a person can, whether a change to the installer is
     harmless. The change is listed with renames switched off (`git diff --no-renames`), so a file
     moved *out* of one of those paths is seen under its old name too;
   - nor how CLIVE is checked: `.github/`. The acceptance workflow lives there, and a commit that
     changed it would be passed by its own changed workflow;
   - the SHA was not tried before and rolled back, halted or stopped part way;
   - acceptance green on the exact SHA, and the authorisation.

   Each is required **positively**: production's SHA known, production known to be behind the trunk's
   head, acceptance known green, the authorisation known present. A fact that was never read is a
   reason not to deploy, never the absence of one.
6. **Dry run** (`CLIVE_RELEASE_DRY_RUN`, **on unless set to `false` in so many words**: a
   `release.env` that has lost the line stays a dry run): it says "Dry run: it would deploy “…” now.
   Nothing was changed." and stops.
7. **Deploys** (`app/release/deploy.py`), the hand procedure as code:

   | Stage | What it does | On failure |
   |---|---|---|
   | Before anything changes | production still on the SHA it read, checkout clean; the checkout and the unit folder writable; `make doctor`; `tailnet_self_check()`; `/health` well (read as the server's own reader, `scripts/healthcheck.py --json`); the live unit saved to `/var/lib/clive-release/deploys/<sha8>/unit-before.service`; `.env`'s and the drop-ins' fingerprints taken; the **live** build's installer (`scripts/install_systemd.py --print`, with the live unit's `HOME` and `PATH`) still renders the live unit byte for byte, so nothing in this service's environment or the credentials provisioned since would change it; the target's objects fetched into the checkout; the started marker written and read back | refuses; nothing changed; tried again next tick |
   | The change | `git checkout --detach <sha>`; the new build's `scripts/gap_clean_check.py`; the **new** build's unit rendered (`scripts/install_systemd.py --print` from the new checkout) and byte-identical to the live one, **before** `make install`, as the `b33ccbc2` deploy checked by hand (code outside the guarded paths feeds the unit: `config/settings.py`'s host and port, the secrets folder, the known keys behind the credentials block); `make install`, run with the `HOME` and `PATH` the live unit was rendered with | rolls back |
   | After | wait 20 s; `/health` well with no check that was ok before now not ok; the service `active (running)` with no restart; `.env` and the drop-ins untouched; the **new process's** journal (entries since the install began from the service's new systemd invocation, so not the old process's shutdown) free of tracebacks, `ERROR`/`CRITICAL`, `withheld`, `not confirmed on disk` and the process exiting; the unit `make install` wrote read back, byte-identical to the saved copy | rolls back |

   **Rollback:** the previous SHA checked out again; when `make install` ran, the saved unit put
   back, `systemctl daemon-reload` and `make install` on the previous SHA; then `/health` read
   again. The SHA is marked in `/var/lib/clive-release/failed/` and is not tried again on its own.
   **A rollback step that fails** writes `/var/lib/clive-release/HALT` and marks the SHA in
   `failed/` too, so removing `HALT` does not set the same deploy off again. The service does nothing
   more until a person has looked at production and removed that file.

   **Time limits.** Every command has its own; the unit's `TimeoutStartSec=4h` is above their sum for
   the longest tick, with the 20 s settle and an allowance for GitHub's acceptance asks (10,220 s for
   one look under `exact_sha_review`, measured by `tests/test_release_service.py`; 12,320 s for a look
   under `owner_waiver` followed by a second look when his approval arrived during the first, measured
   by `tests/test_deploy_now.py`), so systemd never stops a deploy part way that its own steps would
   still allow. A deploy stopped all the same leaves its
   started marker, and the next tick halts (step 3).
8. **Records** (`app/release/record.py`): the deploy record, in the shape of
   `reports/deploy-<sha8>.md` (rollback target, authority, every check, the installer's own status
   lines, verification, what is outstanding, the trunk commits it carries). It is kept in
   `/var/lib/clive-release/deploys/<sha8>/` and pushed as one commit on top of the SHA to the branch
   **`claude/deploy-<sha8>-record`**, ready to merge like the hand records. A rollback's record is
   `deploy-<sha8>-rolled-back.md`, a name `scripts/map.py` never takes for production. The record
   holds no journal line, no `/health` detail, nothing a customer wrote and none of George's own
   waiver words: the repository is public.
9. **Tells George** (below), as it goes: the status file says each stage as it is reached (started,
   checks, installing, health, then done, rolled back with why, stopped part way, or refused with
   why), and keeps the latest deploy on every later status, so the outcome is still there after the
   next tick says "up to date".

**Still outstanding after every deploy: his phone `/whoami`**, exactly as in DEPLOY_LINUX.md. The
deploy is kept once that line appears; the status line says so.

## What it never does

- Deploy anything but `clive/trunk`'s head, or move production backwards or sideways.
- Change `.env`, a credential, the CLIVE loop's unit, the door, or the procedure in DEPLOY_LINUX.md.
- Run from the checkout it deploys. It runs from its own pinned copy (`/srv/clive-release/pin`); a
  deploy can never change the program that decides the next one. Its code refuses to deploy if it
  finds itself inside `/opt/crooks-os`. Moving the pin is a person's act, after review.
- Push anything but a `claude/deploy-<sha8>-record` branch (`app/release/github.py`
  `record_refspec`, the one way it pushes).
- Print, record or push its token. The token reaches git through an environment variable read by a
  credential helper, never an argument; every printed or recorded text is scrubbed of it.
- Give the model anything. No tool reaches it. CLIVE reads its status file, and George's own
  owner-only routes write his approval into CLIVE's state folder (DEC-072); the model has no tool that
  calls them, and the service believes the approval only by its passkey signature.

---

## Who holds deploy authority: George (`owner_waiver`, his ruling 7 of 8 October)

`CLIVE_RELEASE_RULE` in `/etc/crooks-os/release.env`. Until it names one of these, nothing deploys.
Under either, acceptance must be green on the exact SHA, and only the trunk's head, forward, is
deployed. **He chose `owner_waiver`** (DEC-071, ruling 7): the setting to write is
`CLIVE_RELEASE_RULE=owner_waiver`. The two rules as built are below, for the record.

### `exact_sha_review`: an independent review of exactly that SHA

What `DEPLOY_LINUX.md` still says every deploy needs. The service deploys when a reviewer's record
for that exact SHA says **SHIP** with nothing blocking, measured against what production runs (or a
SHA behind it). The record is a file on a branch:

- branch `claude/review-<sha8>-record`, file `crooks-assistant/reports/review-<sha8>.json`:

```json
{"schema": "clive.release.review.v1",
 "sha": "<40 hex: the trunk SHA to deploy>",
 "base_sha": "<40 hex: what production ran when it was reviewed>",
 "verdict": "SHIP", "blocking": [],
 "reviewer": "<who reviewed>", "reviewed_at": "2026-10-08T09:00:00Z",
 "rule": "regression-only (OWNER_DECISIONS_2026-09-30)", "summary": "<one line>"}
```

**What this hands over:** deploy authority goes to whoever can push a branch to the repository:
the Director's review sessions today, and anything else holding a push credential. The trunk is
unprotected, so a push credential can already change the trunk; under this rule it can also put
that change on production, without George. No tap from him per deploy.

### `owner_waiver`: George's own waiver of the review, for exactly that SHA

How the last three deploys were made (`66d3e05d`, `cac1a9e7`, `b33ccbc2`). The service deploys when
George has waived the review for that exact SHA, in one of two forms:

- **Today, on the server.** At his word, the Termius Claude runs one line (below). The file goes into
  a root-only folder, and is believed only from there.
- **With his passkey, in CLIVE** (Deploy now, below; built 8 October). The waiver carries his
  passkey's own signature over a challenge CLIVE's server issued, bound to this repository, this
  exact SHA, and the moments it was issued and expires; the service checks that signature itself
  against his registered public key, refuses it once expired, and spends it before it deploys, so a
  tap for one SHA cannot deploy another, and one tap starts one deploy at most.

**What this keeps:** nothing reaches production without a gesture of his. One gesture per deploy.

**Recommendation:** `owner_waiver`. It is the rule the last three deploys actually followed, it keeps
the standing rule that nothing changes without his gesture, and the passkey step turns the relay into
one tap on his phone. `exact_sha_review` suits a day when reviews are routine and he trusts every
push credential with production.

### Two things George should know before he chooses (the independent review's notes 10 and 11)

1. **`exact_sha_review` hands deploy authority to anyone who can push.** Nothing checks that the
   reviewer is independent of the builder, and the review record is not signed: it is a JSON file on
   a branch. Every builder or reviewer session holding a push credential could write a SHIP record
   and put the trunk's head on production with no gesture from him. Acceptance must still be green
   on the exact SHA, and only the trunk's head, forward, is deployed. **His choice:** accept that
   (reviews routine, every push credential trusted with production), or keep `owner_waiver`.
2. **The passkey waiver's trust stops at CLIVE's own process.** Its signature is checked against the
   public keys in `/etc/crooks-os/secrets/app/passkeys.json`, and both that file and the passkey
   waiver folder can be written by CLIVE's process, which runs as root. A compromised CLIVE could add
   a key of its own and sign its own waiver; that would still deploy only the green trunk head, and a
   process running as root could do worse anyway. **Fixed on 8 October (DEC-072):** the challenge is
   now issued by CLIVE's server, held there for the passkey prompt (three minutes) and good once; its
   nonce and the moments it was issued and expires are inside what the passkey signs; CLIVE checks the
   passkey's signature counter as it does for every approval; and the service refuses a waiver past
   its expiry (ten minutes from the hold) or one already used (`/var/lib/clive-release/approvals-used/`).
   A captured waiver can no longer be replayed. Still so: keys are read from a file CLIVE's process
   can write. The host waiver (root-only folder) is not affected.

---

## How George turns it on

Rulings 7 and 8 (8 October): `owner_waiver`, switched on **in dry run**, after the next hand deploy.
The Termius Claude does all of it, as root on `crooks-os-prod-1`, after that hand deploy is done and
kept (its phone `/whoami` line seen). George makes the token (step 2) and later switches dry run off.

### 1. Install, on, in dry run (the Termius Claude, as root on `crooks-os-prod-1`)

`SHA` is the trunk SHA production now runs, carrying DEC-072 (`app/release/approve.py` is in it). The
service's unit names the token, so it cannot start without it: if George has not made the token yet
(step 2), stop after the pinned copy and come back.

```bash
SHA=<the 40-character clive/trunk SHA production now runs>
cd /opt/crooks-os && git fetch origin clive/trunk
test "$(git rev-parse HEAD)" = "$SHA" && echo "production runs it"
git merge-base --is-ancestor "$SHA" origin/clive/trunk && echo "on the trunk"
test -f crooks-assistant/app/release/approve.py && echo "it carries Deploy now"

# Where CLIVE writes George's approvals must be where the service reads them and the path unit
# watches: CLIVE's objectives folder plus /release-waivers. In production that is
# /var/lib/crooks-assistant/objectives (its StateDirectory). This must print exactly that line:
grep -E '^CROOKS_OBJECTIVES_DIR=' crooks-assistant/.env
# If it prints another folder, stop: the path unit's PathChanged= and CLIVE_RELEASE_PASSKEY_WAIVERS_DIR
# must both name <that folder>/release-waivers first (a person's change, not this procedure's).

# The pinned copy of the service's own code: an exact SHA, unpacked, never a checkout.
install -d -m 0755 "/srv/clive-release/$SHA"
git -C /opt/crooks-os archive "$SHA" | tar -x -C "/srv/clive-release/$SHA"
ln -sfn "/srv/clive-release/$SHA" /srv/clive-release/pin

# Its own GitHub token (step 2 makes it), encrypted for this host, apart from CLIVE's credentials.
install -d -m 0700 /etc/crooks-os/release /etc/crooks-os/release/waivers
read -rs TOKEN && printf %s "$TOKEN" | systemd-creds encrypt --name=clive_release_github_token - \
  /etc/crooks-os/release/clive_release_github_token.cred; unset TOKEN
chmod 0600 /etc/crooks-os/release/clive_release_github_token.cred

# The switches: shipped off, then on with George's rule, dry run kept (rulings 7 and 8).
install -m 0600 /srv/clive-release/pin/crooks-assistant/deploy/release/release.env.example /etc/crooks-os/release.env
sed -i -e 's/^CLIVE_RELEASE_ENABLED=false$/CLIVE_RELEASE_ENABLED=true/' \
       -e 's/^CLIVE_RELEASE_RULE=off$/CLIVE_RELEASE_RULE=owner_waiver/' /etc/crooks-os/release.env
grep -E '^CLIVE_RELEASE_' /etc/crooks-os/release.env
# must print exactly: CLIVE_RELEASE_ENABLED=true / CLIVE_RELEASE_RULE=owner_waiver / CLIVE_RELEASE_DRY_RUN=true

# The unit, its timer, and the path unit that starts it when George approves a deploy in CLIVE.
for unit in clive-release.service clive-release.timer clive-release-now.path; do
  install -m 0644 "/srv/clive-release/pin/crooks-assistant/deploy/release/$unit" /etc/systemd/system/
done
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/clive-release-now.path    # prints nothing

# One tick by hand: a dry run, changing nothing.
systemctl start clive-release.service
journalctl -u clive-release.service -n 5 --no-pager
cat /var/lib/clive-release/status.json            # "mode": "dry_run", "rule": "owner_waiver"

# What it would do now: changes nothing on production, pushes nothing, writes no status.
cd /srv/clive-release/pin/crooks-assistant && \
  /opt/crooks-os/crooks-assistant/.venv/bin/python -m app.release --env /etc/crooks-os/release.env plan

systemctl enable --now clive-release.timer clive-release-now.path
systemctl is-active clive-release-now.path        # active
ls -ld /var/lib/crooks-assistant/objectives/release-waivers    # drwx------ root root (MakeDirectory=)
```

CLIVE's Builds screen then shows the service's line in dry run. When a version is ahead of production
and green, the **Deploy now** card offers "Hold to try it (dry run)".

### First deploy through CLIVE (the trigger, proved in dry run)

1. George, on his phone: Builds → the Deploy now card → hold "Hold to try it (dry run)" → Face ID.
2. Within seconds, on the server: `journalctl -u clive-release.service --since -2min --no-pager` shows a
   tick that began then (started by the path unit, not the five-minute timer), ending "Dry run: it
   would deploy “…” now. Nothing was changed."; `cat /var/lib/clive-release/status.json` shows
   `"deploy"` with `"end": "dry_run"` and the approval's id. The card says the same.
3. After the dry-run days, when its plans have matched hand deploys, George sets
   `CLIVE_RELEASE_DRY_RUN=false` in `/etc/crooks-os/release.env` (the next tick reads it; nothing
   restarts). A hold he gave to try it in dry run deploys nothing after that: it was spent by its dry
   run and signed as a try. Once the card says "Hold to deploy", his hold deploys: the card follows
   it, started → checks → installing → health → done, and his phone keeps it (below).

### 2. The token (George, on github.com)

Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate:
resource owner **crooksldn-pixel**; **Only select repositories: clive**; repository permissions
**Actions: Read-only**, **Contents: Read and write** (Metadata: Read-only comes with it); nothing else;
an expiry he will notice (90 days). He pastes it at the `read -rs TOKEN` prompt above.

GitHub cannot limit "Contents: write" to some branches for a token. The narrowing to
`claude/deploy-*-record` is the service's own code (`record_refspec`), tested. Without the token the
service still reads the public repository, but cannot push its records (each stays in
`/var/lib/clive-release/deploys/`), and the unit will not start, because it names the credential.

### 3. The switches (George)

In `/etc/crooks-os/release.env`, as step 1 leaves them:

```
CLIVE_RELEASE_ENABLED=true
CLIVE_RELEASE_RULE=owner_waiver          # his ruling 7: he approves each deploy
CLIVE_RELEASE_DRY_RUN=true               # his ruling 8: dry run first
```

Then, when its dry-run lines have matched what a hand deploy would have done, `CLIVE_RELEASE_DRY_RUN=false`.
The next tick reads the file; nothing restarts. Only that line (or another value read as false:
`0`, `no`, `off`) turns dry run off: without the line the service stays a dry run, and a value it
cannot read stops the tick before it reads or changes anything.

### Giving a waiver on the server

His approval normally comes from CLIVE (Deploy now, below). At his word, on the server, it can still
be given as a host waiver:

```bash
cd /srv/clive-release/pin/crooks-assistant && /opt/crooks-os/crooks-assistant/.venv/bin/python \
  -m app.release waive <the 40-character SHA> --by George --words "<what he said>"
```

The next tick (at most five minutes: the path unit watches CLIVE's folder, not this root-only one)
deploys it if everything else holds. His `--words` stay in the
root-only waiver file on the server; they are **never** copied into the deploy record, which is pushed
to the public repository (a customer's name in them would otherwise become public). The same holds
for a passkey waiver's `words`.

### Deploying by hand while the service is installed

Changes to `deploy/`, the installer, the dependencies or `.github/` stay hand deploys. A hand deploy
does not hold the service's lock by itself, and a tick that started half way through one (after
`/health` is back, before the phone `/whoami`) could deploy the next waived or reviewed SHA on top of
a hand deploy nobody has finished checking. So, for every hand deploy, either:

- **switch the service off first** (simplest): `systemctl stop clive-release.timer clive-release-now.path`,
  then wait until `systemctl is-active clive-release.service` says `inactive` (a tick under way
  finishes); do the whole hand deploy, through the phone `/whoami`; then
  `systemctl start clive-release.timer clive-release-now.path`; or
- **hold its lock for the whole hand deploy:** `flock -n /var/lib/clive-release/deploy.lock bash`
  opens a shell that holds the lock until it exits (it refuses at once if a tick holds it now); run
  every step of the hand deploy in that shell and leave it only after the phone `/whoami` line. A
  tick that finds the lock held does nothing.

### The first deploy after this is merged is a hand deploy

Merging the release service adds `crooks-assistant/deploy/release/*` (and Deploy now adds
`clive-release-now.path` there), and `deploy/` is guarded, so until production has been deployed by
hand past that merge, the service refuses every SHA with "the change touches how CLIVE is installed",
and CLIVE's card says that change is deployed by hand. That hand deploy's own check of `deploy/` (DEPLOY_LINUX.md)
will also flag the new files: they are **harmless** to it, because `make install` renders only
`deploy/systemd/crooks-assistant.service` and never reads `deploy/release/`. Any later change to
`deploy/release/` is the same: a hand deploy, then the service carries on.

### Turning it off

`CLIVE_RELEASE_ENABLED=false` in `/etc/crooks-os/release.env` (the next tick stops, and CLIVE's card
then says the service is switched off instead of offering the hold), or
`systemctl disable --now clive-release.timer clive-release-now.path`. To remove it: also
`rm /etc/systemd/system/clive-release.{service,timer} /etc/systemd/system/clive-release-now.path && systemctl daemon-reload`.

### After a halt

`cat /var/lib/clive-release/HALT` says why: a rollback that did not finish, or a deploy stopped part
way (then there is no record, only `deploys/<sha8>/unit-before.service`). Look at production
(`make status`, `scripts/healthcheck.py -v`, `git -C /opt/crooks-os rev-parse HEAD`), put it right by
hand with the record's rollback lines, or the saved unit and the previous SHA the HALT names, then
`rm /var/lib/clive-release/HALT`. A SHA that rolled back or halted is retried only after
`rm /var/lib/clive-release/failed/<sha>.json`.

### Moving the pin

A new version of the service is a new pinned copy: the same three `SHA=…`, `archive` and `ln -sfn`
lines with the new SHA, after its own review. Nothing else changes.

---

## How George is told

- **CLIVE's Builds screen**, under the heading: the **Deploy now** card while a deploy is offered or
  under way (below), and otherwise the service's own line, how long ago, and a dot (blue: deploying,
  waiting, or deployed and waiting for his phone check; steel: production runs the trunk's latest;
  red: rolled back or halted; a ring: off, no rule, or not installed). Read from
  `/var/lib/clive-release/status.json` (`app/release/status.py`, `app/builds/read.py`,
  `web/builds.js`). While a card is shown, the line steps aside: the card says the same from fresher
  reads.
- **The record branch** `claude/deploy-<sha8>-record` on GitHub, and `journalctl -u clive-release`.
- **Not yet: a push to his phone.** CLIVE has no push channel: `web/notify.js` decides where a message
  sits on a page that is open, and the service worker (`web/sw.js`) has no push handler. When the
  messaging work (WeCom, and later WhatsApp) lands, one message per deploy outcome is the natural next
  step; the line it would send is the status line, as written.
- **Screens:** after a deploy, every open TV page reloads itself onto the new build at rest
  (`X-Clive-Build`, DEPLOY_LINUX.md).

## Deploy now: his hold and passkey in CLIVE (built 8 October, DEC-072)

1. **The card.** On the Builds screen, straight under the heading, when `clive/trunk`'s head is ahead
   of the commit CLIVE runs and GitHub acceptance is green on exactly that SHA
   (`app/release/offer.py`): "Ready to go live", the head's title, the pull requests since what is
   live in their own titles, and **Hold to deploy** (**Hold to try it (dry run)** in dry run). When his
   hold cannot deploy it, the card says why instead: the service not installed, off, not under
   `owner_waiver`, stopped, the change one that stays a hand deploy, or the service's own reason when
   it has looked at this SHA and finds more than his approval missing (`ready_for` in the status).
   Owner only: the team's routes do not include it, and their page never loads it.
2. **His hold** (0.9 s) asks `POST /release/deploy/challenge`, which reads the trunk again and issues a
   challenge for exactly that SHA: a fresh nonce, the moment issued and the moment it expires (ten
   minutes), and whether the hold deploys or only tries it (the card's dry run), bound into what the
   passkey signs (`app/release/authority.py` `waiver_challenge`), held by CLIVE for three minutes and
   good once (`app/release/approve.py`; `app/connections/passkeys.py` takes the caller's challenge).
3. **Face ID.** `POST /release/deploy` checks the passkey as every approval is checked (this CLIVE's
   address, his passkey, present and verified, its counter going up) and writes the waiver, with the
   assertion inside it and no words or login of his, to
   `/var/lib/crooks-assistant/objectives/release-waivers/<sha>.json`.
4. **At once**, `clive-release-now.path` starts a tick. The service verifies the signature itself
   against his registered public key, refuses it if expired or already used, marks it used, and
   deploys. In dry run it marks it used too, as a dry run, and changes nothing; a hold given as "Hold
   to try it (dry run)" is refused once the service deploys for real, so switching dry run off never
   turns a try into a deploy (the review of DEC-072, note 1). The card follows the status every three seconds: started → checks → installing → health →
   done, or rolled back / stopped / refused with why. Through CLIVE's restart it says CLIVE is
   restarting onto the new build.
5. **Kept.** Once the service says done and the CLIVE answering is the new build, the page asks
   `/whoami` itself and hands its token to `POST /release/kept`, which looks in CLIVE's own journal
   for `whoami: id=<check> through=tailscale owner=true refusal=none` since the deploy was done. Found,
   the deploy is kept (recorded in `objectives/release-kept/<sha>.json` with the approval that deploy
   answered, so a check after an earlier deploy of the same version never keeps a later one) and the
   card says "Deployed and kept". An approval that expired with no deploy of its own says what the
   service's record shows since (the version deployed another way, say), and "Nothing was deployed"
   only when it shows nothing. Any owner page of CLIVE does this as it opens; the tab he approved from reopens the Builds
   screen on it. The release record pushed to GitHub still lists the phone check as outstanding: CLIVE
   cannot write the service's record.

## Files

| File | What it is |
|---|---|
| `app/release/` | the service (its `__init__.py` lists each module) |
| `scripts/release.py` | the same command line as `python -m app.release` |
| `deploy/release/clive-release.service`, `.timer` | the unit and its timer, installed only by the steps above |
| `deploy/release/clive-release-now.path` | starts the unit when George approves a deploy in CLIVE (DEC-072) |
| `app/release/offer.py`, `approve.py`, `app/routes/release.py`, `web/deploy.js` | Deploy now: CLIVE's half (the card, his approval, kept) |
| `deploy/release/release.env.example` | the switches as shipped: off, no rule, dry run |
| `/etc/crooks-os/release.env` | the switches on the server (George's) |
| `/etc/crooks-os/release/` | the encrypted token and the root-only `waivers/` folder |
| `/srv/clive-release/pin` | the pinned copy the unit runs |
| `/var/lib/clive-release/` | its state: `status.json`, `deploy.lock`, `repo.git`, `deploys/<sha8>/` (the saved unit, the record, the `started` marker while a deploy is under way), `failed/`, `HALT` |
| `tests/test_release_service.py`, `tests/test_release_service_git.py` | every condition, failure point and rollback on a fake server; the git it runs, on real git |
| `tests/test_deploy_now.py`, `tests/web/deploy.test.js`, `tests/test_deploy_browser.py` | Deploy now: the card, the approval end to end with real signatures, the trigger, the progress, kept; in Chromium on the phone and the tablet |

The unit runs as root (it runs `make install`, which writes the crooks-assistant unit and restarts
it), under `ProtectSystem=strict` with only `/opt/crooks-os`, `/etc/systemd/system` and its own state
writable, `ProtectHome=read-only`, `NoNewPrivileges` and `PrivateTmp`. Before changing anything, each
deploy checks it can write what it must (`access(2)` sees a read-only mount), so a confinement too
narrow is a refusal with nothing changed, never a half-made deploy.
