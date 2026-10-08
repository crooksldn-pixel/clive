# CLIVE — Current Truth

**Purpose:** what is true now, in one place. Read [`MAP.md`](../../MAP.md) first; this file is its live state.
**Status:** ACTIVE. Rewrite it whenever production, the trunk, the loop or an owner decision changes, and move what it said before into the history file.
**As of:** 2026-10-08 (production is `b33ccbc2`; the trunk is fifteen merged PRs and four of the loop's own landings ahead of it, none recorded as deployed).

Everything this file said before 5 October 2026 is kept word for word in [`docs/history/CURRENT_TRUTH_HISTORY.md`](../history/CURRENT_TRUTH_HISTORY.md), including the doctrine summary it used to carry. Decisions and their reasons are in [DECISIONS.md](./DECISIONS.md). How production is run and deployed is [`docs/DEPLOY_LINUX.md`](../DEPLOY_LINUX.md).

## Now — 2026-10-05

### What is live

| | SHA | What it is |
|---|---|---|
| **Production** (`crooks-os-prod-1`, `/opt/crooks-os`) | `b33ccbc2` | Live since **3 Oct, 17:48 UTC**. It is PR #95: the six notes of the post-deploy review of `cac1a9e7`, plus one found on the way. That review's verdict was **KEEP** (PR #95's description). The fixes: a voice's settings are never invented, and shipped, refunded or cancelled orders stay off the packing board. Deployed on **the owner's waiver** of the exact-SHA review. GitHub acceptance was green on the exact SHA (run `37128652668`). `/health` answered 200 with all 12 checks `ok` (build `83524b275b07`). `.env`, the unit and the drop-ins were unchanged. Record: [`reports/deploy-b33ccbc2.md`](../../reports/deploy-b33ccbc2.md). Rollback: `cac1a9e7` plus `/root/crooks-unit-before-b33ccbc2.main.service`. |
| **Trunk** (`clive/trunk`) | head | `b33ccbc2` plus fifteen merged PRs on 7–8 Oct (#96 to #108, then WhatsApp and Instagram direct messages and research intake, the two PRs after #108) and four builds the loop landed itself on 7–8 Oct. None is recorded as deployed ("Merged, not deployed" below). |
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

Production stays on `b33ccbc2` until these are deployed. It is the last deploy on record: whether `a68536c6` (the trunk after PR #99) was deployed on 7 Oct is not recorded. None of these changes `.env` or CLIVE's own unit. Two reach past the app: PR #101 adds the release service's own unit and timer under `deploy/release/`, not installed, and PR #102 changes the loop's code, which takes effect only at worker-01's re-pin.

- **PR #96** (7 Oct): CROOKS Returns in CLIVE, and the design pass (the answer in full on the phone, Home, approval weights and "Not now", the dock on every tablet, colour). Both halves were reviewed SHIP before merging.
- **PR #97** (7 Oct, docs only): one map (`MAP.md`), this file rewritten for what is live, DEC-062 to DEC-066 caught up, and the deploy records landed.
- **PR #98** (7 Oct): CLIVE can list the installed skills and read one as guidance (`skill_list`, `skill_read`). It finishes the loop's `skill-read-runtime-tool-4` by hand, which stopped at its repair limit on 1 Oct. Reviewed SHIP twice; each note was fixed with a test.
- **PR #99** (7 Oct): an objective's days left and the support investigator's dates count London's day, not UTC's, so they are right between midnight and 1am in summer time. It re-files the loop's `uk-midnight-clock-sweep-2` on today's trunk. Reviewed SHIP.
- **PR #100** (8 Oct): this repository is CLIVE only. The old theme snapshot at its root is gone, and the steps that move the theme to its private repository and archive the old branches as tags are in `docs/repo/BOUNDARY.md`, ready to run.
- **PR #101** (8 Oct, [DEC-067](./DECISIONS.md)): a release service that can deploy CLIVE and roll back by itself, without the Termius relay. It is built and switched off; nothing deploys until he names who holds deploy authority as `CLIVE_RELEASE_RULE`.
- **PR #102** (8 Oct, [DEC-068](./DECISIONS.md)): the loop upgrade under "The build loop" below. It needs worker-01's re-pin before any of it is in force.
- **PR #103** (8 Oct): the bench. It bulk-tests CLIVE with generated questions from six personas through the real turn against the fake shop, judged, and rated by him on an owner page.
- **PR #104** (8 Oct): the real-looking personal details in tests, fixtures and screenshots are replaced with invented ones, now the repository is public.
- **PR #105** (8 Oct): WeChat with the manufacturer and forwarder through WeCom. He reads it in English with the original one tap away, and a reply goes only on his hold. It is on once he stores the WeCom values on Connections.
- **PR #106** (8 Oct): CLIVE Shipping. International orders by stage, a label bought on his hold at the service's own price check, and printing through the service's PrintNode. It is on once he stores its keys on Connections.
- **PR #107** (8 Oct, [DEC-069](./DECISIONS.md)): ask for something and see only the answer, with words saying what CLIVE is doing meanwhile. A reply or new email is one card he can edit and hold to send, with no Save draft step.
- **PR #108** (8 Oct): acceptance now runs every screen test in a real Chromium, and the screens he uses were walked at phone and tablet sizes and fixed.
- **WhatsApp and Instagram direct messages** (8 Oct, the PR after #108): both work through the same message tools as WeChat. He reads them in English, and a reply goes only on his hold and only inside the app's 24-hour window. Each is on once he stores its keys; who WhatsApp is for, and on which number, is still his to decide (`docs/WHATSAPP.md`). Instagram shows the DMs that reach its webhook; Meta's API returns no one else's conversations until the app has Advanced Access (`docs/INSTAGRAM_DMS.md`).
- **Research intake** (8 Oct, the PR after the WhatsApp one, [DEC-070](./DECISIONS.md)): George gives CLIVE research on the Builds screen or in the server's research folder, each recommendation is weighed against the map and put to him as Adopt, Park or Reject, and Adopt files a build request only on his hold. Reviewed SHIP; seven of its eight notes fixed with a test each, and the eighth (its rule check is advisory) said in `RESEARCH.md`. Its deploy is by hand: `pyproject.toml` now needs `pypdf>=6.19.0`.

The loop landed four builds itself on 7–8 Oct, also not deployed:
- **`retire-returns-stub`** (7 Oct): the old returns stub's four "not built" rows are gone, so CLIVE no longer tells him, or the model on every turn, that returns are not available while it can act on them through CROOKS Returns.
- **`skill-installer-followups`** (7 Oct): the skill installer leaves to him any skill that asks for shell access or carries a stored permissions finding, its final move never overwrites, and a skill's licence text is made harmless when written.
- **`deflake-reply-turn-enrichment`** (8 Oct, tests only): the 14 tests that use an order card's inbox wait for it the way the tablet does, so a slow test machine no longer fails them.
- **`fixture-clock-dst-nights-2`** (8 Oct, tests only): the test shop's "today" is worked out on London's clock, so the tests hold on the clock-change nights (25 Oct 2026, 28 Mar 2027).

### The build loop

- **Back at work on 7–8 Oct:** it landed the four builds listed under "Merged, not deployed". The counts in the next point stop at 7 Oct and are not updated here.
- **Quiet since 1 Oct.** Since 25 Sep, the loop on clive-worker-01 has taken 65 requests:
  - 21 COMPLETE;
  - 40 BLOCKED: 17 at the repair-round limit, 10 reported blocked by their builder, 7 on a red GitHub run, 4 on workspace errors and 2 on failed checks;
  - 2 OWNER_GATE;
  - 2 refused at intake.

  The last request was recorded on **1 Oct at 22:08 UTC**. It still publishes its status to `clive/control/worker-01-status` about every ten minutes (still on 7 Oct).
- **The loop landed 7 builds itself on 1 Oct.** Every trunk change after its last landing (`8ad7477d`, 1 Oct 22:27 UTC) came from builders outside it: PRs #89–#95, and two direct landings (`1d03efd6`, `4d2dc00f`).
- **Its pin is not recorded.** PR #72 records a re-pin to `b577bc97` on 1 Oct, at which the owner waived two findings. A later re-pin review of `b577bc97..4daf49e1` asked for changes, which PR #88 (`718fbc41`) answered. Which SHA the loop runs now is not recorded in the repository.
- **The loop upgrade of 7 Oct is on the trunk and not in force** ([DEC-068](./DECISIONS.md)). It takes effect only at clive-worker-01's re-pin, which the owner approved on the Director's go. From then:
  - why a build stopped (the reviewer's findings, the failing output, the builder's words) is kept on worker-01 and served over the tailnet only, to `crooks-os-prod-1` named by its full tailnet name. The Builds screen shows it once `CROOKS_ENGINEERING_PRIVATE_URL` is set in production's `.env`; until then it says the wording is kept on the build server;
  - a build filed again starts with the earlier try's findings, and a request without its own number gets the host's default repair rounds;
  - builders get the four design skills, but only on Claude CLI 2.1.285 or 2.1.293. On any other version the loop runs with `--no-builder-skills`;
  - checks can drive Chromium once it is installed on worker-01.

### Recorded in DECISIONS on 5 October

DEC-062 to DEC-065 record the owner decisions of 26 Sep, 28 Sep, 30 Sep and 1 Oct, which had never reached the log. DEC-066 records CROOKS Returns. DEC-027's status now says writes are on.

### Still the owner's

On 8 October he answered 43 open questions at once ([DEC-071](./DECISIONS.md)): deploys are his to approve and start at once (the waiver is now the rule); the worker-01 loop is the normal way work lands, with a Claude reviewer; Split, the Mac runtime, the local Whisper client, the CROOKS Pad and Easyship are retired; `web/today-say.js` is a recorded exception; emails may go on a TV; CLIVE may delete its own unused drafts; business text may go to other AI services. Still open:

- The phone `/whoami` for the next deploy.
- When the repository goes private again, and whether its history is rewritten (rulings 1–3: not now).
- Instagram Advanced Access and the human-agent tag (rulings 17–18: not now).
- Whether staff may read security and login emails (ruling 33: not yet).
- A recipient tap on new emails, and whether "open the inbox" after Add a note is held only by his tap (carried from 30 Sep).
- clive-worker-01's hardware items.

### Not verified from here

- The loop's current pin.
- The owner's phone check for `b33ccbc2`.
- Whether `a68536c6` was deployed on 7 Oct: no deploy record says so.
- Whether any item carried from 30 Sep has been settled outside the repository.
- Whether the Ship24 and Instagram keys are stored in production. Without them, those reads say they are not connected.
