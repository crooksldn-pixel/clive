# CLIVE — Current Truth

**Purpose:** what is true now, in one place. Read [`MAP.md`](../../MAP.md) first; this file is its live state.
**Status:** ACTIVE. Rewrite it whenever production, the trunk, the loop or an owner decision changes, and move what it said before into the history file.
**As of:** 2026-10-07 (production is `b33ccbc2`; the trunk is three merged PRs ahead of it, none deployed).

Everything this file said before 5 October 2026 is kept word for word in [`docs/history/CURRENT_TRUTH_HISTORY.md`](../history/CURRENT_TRUTH_HISTORY.md), including the doctrine summary it used to carry. Decisions and their reasons are in [DECISIONS.md](./DECISIONS.md). How production is run and deployed is [`docs/DEPLOY_LINUX.md`](../DEPLOY_LINUX.md).

## Now — 2026-10-05

### What is live

| | SHA | What it is |
|---|---|---|
| **Production** (`crooks-os-prod-1`, `/opt/crooks-os`) | `b33ccbc2` | Live since **3 Oct, 17:48 UTC**. It is PR #95: the six notes of the post-deploy review of `cac1a9e7`, plus one found on the way. That review's verdict was **KEEP** (PR #95's description). The fixes: a voice's settings are never invented, and shipped, refunded or cancelled orders stay off the packing board. Deployed on **the owner's waiver** of the exact-SHA review. GitHub acceptance was green on the exact SHA (run `37128652668`). `/health` answered 200 with all 12 checks `ok` (build `83524b275b07`). `.env`, the unit and the drop-ins were unchanged. Record: [`reports/deploy-b33ccbc2.md`](../../reports/deploy-b33ccbc2.md). Rollback: `cac1a9e7` plus `/root/crooks-unit-before-b33ccbc2.main.service`. |
| **Trunk** (`clive/trunk`) | head | `b33ccbc2` plus four merges on 7 Oct: PR #97 (docs only) and PRs #96, #98 and #99, which are not deployed ("Merged, not deployed" below). |
| **The loop** (clive-worker-01) | not recorded | See "The build loop" below. |

The deploys before it, newest first:
- **`cac1a9e7`**, 3 Oct 13:01 UTC. PR #94, the overnight build: Connections, the interaction record, the team, customers and the Builds screen. It merged with no review and was deployed on the owner's waiver. The post-deploy review that followed said KEEP. Record: [`reports/deploy-cac1a9e7.md`](../../reports/deploy-cac1a9e7.md).
- **`4d2dc00f`** (voice settings on Connections, labelled orders kept on the list): live before `cac1a9e7`, deployed between 2 Oct 14:08 and 3 Oct 13:01 UTC, with no record of its own.
- **`66d3e05d`**, 2 Oct 13:49–14:08 UTC. PR #89 (settings and team sign-in) and PR #90 (Ship24), on the owner's waiver. His phone check passed. Record: [`reports/deploy-66d3e05d.md`](../../reports/deploy-66d3e05d.md).
- **`718fbc41`**, the night of 1 Oct. Sanctioned by the owner, with no record of its own; the `66d3e05d` record says so.

Three things not to miss:
- **The last three deploys waived the exact-SHA review**, which `DEPLOY_LINUX.md` still says every deploy needs. The 30 Sep ship rule changed what blocks a deploy, not whether a review runs. Which one stands is the owner's call.
- **GitHub Actions ran out of included minutes on 3 Oct** (17:52 UTC) and started no jobs until the owner made the repository public on 7 Oct; public repositories get GitHub's standard runners without a minute limit. The self-hosted runner decided on 30 Sep is still not set up.
- **The owner's phone check for `b33ccbc2` is not on record.** The deploy record left the `/whoami` line outstanding, and the procedure keeps a deploy only once that line appears.

### Production switches and what runs

The switches are as the `66d3e05d` deploy recorded them on 2 Oct; the two records since say `.env` was left untouched. Writes are on (`CROOKS_WRITES_ENABLED=true`), and each write waits for its card. Filing builds is on (`CROOKS_ENGINEERING_HOST=worker-01`, since 30 Sep 17:53 UTC). The host cannot act as the owner. The interaction record is on ([RECORDING](../RECORDING.md)): the `cac1a9e7` deploy found `logs/interactions/` created. Scenes are off. MAP.md has every switch.

What runs on it:
- **Voice:** hold to talk, ElevenLabs to hear and to answer, every sentence a model turn, and his JARVIS spec as the personality.
- **Tools:** 76 over Shopify, Gmail, analytics, Instagram (read-only), Ship24 and the TVs, with every write held on a card.
- **Home:** what needs him, his objectives, the next six weeks, and Builds.
- **Other pages:** the team at `/today` ([TEAM](../TEAM.md)), keys at `/connections` ([CONNECTIONS](../CONNECTIONS.md)), and the TVs at `/display`.

### CROOKS Returns: live beside CLIVE, not in it

CROOKS Returns is the owner's own returns and exchanges service, and it replaces AfterShip. It runs at `https://returns.crooksldn.com`, in its own Docker Compose container on `crooks-os-prod-1` (`/opt/clive/crooks-returns`). He built and deployed it himself on 3 Oct, **outside the CLIVE engineering kernel**: it has no kernel task, review or acceptance record ([DEC-066](./DECISIONS.md)). CLIVE's side is PR #96 (merged 7 Oct, **not deployed yet**): read-only returns tools, the home row, the order card and the customer's history, and one staged write (`return_action`) that runs CROOKS Returns' own preview and waits for the owner's approval, with his hold for anything that moves money or emails a customer. It switches on when he stores the service's read and write keys on Connections. The old stub (`app/returns/`, `app/families/returns.py`) is still on the trunk beside it.

### Open pull requests

- **#1 and #2** (18–19 Sep: the first product-memory foundation and an operator runbook) are still open and stale.

### Merged, not deployed

Production stays on `b33ccbc2` until these are deployed. None of them changes `.env`, the unit, `deploy/` or the loop's code, so no re-pin follows.

- **PR #96** (7 Oct): CROOKS Returns in CLIVE, and the design pass (the answer in full on the phone, Home, approval weights and "Not now", the dock on every tablet, colour). Both halves were reviewed SHIP before merging.
- **PR #98** (7 Oct): CLIVE can list the installed skills and read one as guidance (`skill_list`, `skill_read`). It finishes the loop's `skill-read-runtime-tool-4` by hand, which stopped at its repair limit on 1 Oct. Reviewed SHIP twice; each note was fixed with a test.
- **PR #99** (7 Oct): an objective's days left and the support investigator's dates count London's day, not UTC's, so they are right between midnight and 1am in summer time. It re-files the loop's `uk-midnight-clock-sweep-2` on today's trunk. Reviewed SHIP.

### The build loop

- **Quiet since 1 Oct.** Since 25 Sep, the loop on clive-worker-01 has taken 65 requests:
  - 21 COMPLETE;
  - 40 BLOCKED: 17 at the repair-round limit, 10 reported blocked by their builder, 7 on a red GitHub run, 4 on workspace errors and 2 on failed checks;
  - 2 OWNER_GATE;
  - 2 refused at intake.

  The last request was recorded on **1 Oct at 22:08 UTC**. It still publishes its status to `clive/control/worker-01-status` about every ten minutes (still on 7 Oct).
- **The loop landed 7 builds itself on 1 Oct.** Every trunk change after its last landing (`8ad7477d`, 1 Oct 22:27 UTC) came from builders outside it: PRs #89–#95, and two direct landings (`1d03efd6`, `4d2dc00f`).
- **Its pin is not recorded.** PR #72 records a re-pin to `b577bc97` on 1 Oct, at which the owner waived two findings. A later re-pin review of `b577bc97..4daf49e1` asked for changes, which PR #88 (`718fbc41`) answered. Which SHA the loop runs now is not recorded in the repository.

### Recorded in DECISIONS on 5 October

DEC-062 to DEC-065 record the owner decisions of 26 Sep, 28 Sep, 30 Sep and 1 Oct, which had never reached the log. DEC-066 records CROOKS Returns. DEC-027's status now says writes are on.

### Still the owner's

- The phone `/whoami` for `b33ccbc2`.
- Whether a deploy still needs the exact-SHA review, or the waivers become the rule.
- Whether the governed loop or direct builders are the normal way work lands.
- Whether the team page may act on "packed 2106" without the model (`web/today-say.js`), as an exception to 28 Sep.
- The parked items in MAP.md, each with its expiry date.
- Carried from 30 Sep, with no later record deciding them:
  - Jev access, and a data policy for business text leaving the host;
  - a recipient tap on new emails, and whether an email may go on a TV;
  - whether CLIVE may delete the unused drafts its Prepare leaves;
  - whether "open the inbox" after Add a note is held only by his tap;
  - the reviewer's monthly budget, and decisions 3 and 6 of the self-shipping plan;
  - clive-worker-01's hardware items, and the runner's registration token.

### Not verified from here

- The loop's current pin.
- The owner's phone check for `b33ccbc2`.
- Whether any item carried from 30 Sep has been settled outside the repository.
- Whether the Ship24 and Instagram keys are stored in production. Without them, those reads say they are not connected.
