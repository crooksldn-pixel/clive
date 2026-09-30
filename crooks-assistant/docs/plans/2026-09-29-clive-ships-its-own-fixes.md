# CLIVE ships its own fixes — the plan, and the decisions only George can make

The owner, 29 September 2026: "clive cannot ship its own fixes."

He is right, and it is not a missing feature so much as three switches that are off by his own
rules, and one step that has never been built. This says what exists, what is off and why, what
would have to be built, and what he has to decide before any of it is. Nothing here is in force.

## What happens today, from a defect to production

| Step | What does it | State |
|---|---|---|
| 1. Hear the defect | The owner says it; `feedback.held_at_turn` records it against the screen he was on (round 11). | Works, during a test session. |
| 2. Turn it into work | `submit_engineering_request` files a repository-only request to the remote inbox (`clive/control/owner-inbox`), read by worker-01. | **Off.** `CROOKS_ENGINEERING_HOST` unset means filing is switched off (round 11, CFG-01), and the engineering token is parked in `/etc/crooks-os/credentials-parked/`. Both by the owner's standing rule since the round-6 security review. |
| 3. Build it | worker-01's deterministic dispatcher gives the objective to an isolated Claude worker, which works on a branch under the same tests and protected paths as anyone (`docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md`). | Runs. Loop update part 2 is waiting for the owner's re-pin: `sudo bash /home/george/clive-review/repin/root-repin.sh`. |
| 4. Review it | An independent GPT reviewer reviews the exact SHA; acceptance runs on GitHub. | Runs, but the reviewer's API account has run out of credits (round 10). |
| 5. Merge it | Only a PR whose exact head is green, merged with `expectedHeadSha`. | Runs. |
| 6. Deploy it | The exact-SHA deploy review on the production host (the Hetzner prompt), a staging copy, two phone checks, then code and unit in one operation with rollback. | **By hand.** The owner pastes a prompt into Termius, and taps his phone twice. |

So a fix CLIVE hears today reaches production only after the owner carries it by hand through
steps 2 and 6. "Ships its own fixes" means closing those two gaps without giving the assistant he
talks to any power over its own code.

## The line that does not move

The assistant George talks to never gets a tool that edits, deploys or restarts anything
(`docs/ENGINEERING_LOOP.md`, "What is never automatic"). A fix is never applied by the thing that
found it. Every step below runs outside CLIVE's model, with its own authority, and the step that
changes production waits for one gesture of George's, made on his own phone.

## The design

### Step 2 — from a defect he says to a request, with one hold

- A spoken defect ("log that the back button takes me to the wrong order") already becomes a
  recorded `owner_feedback` event. CLIVE then offers it as a **request card**: the defect in his
  words, the screen it was about, and "Fix this" — a hold-to-confirm, like every other change.
- His hold files one repository-only request to the inbox: the title, the outcome wanted, the
  turn ids, acceptance criteria written from the defect, and the protected paths it may not touch.
  The model drafts the words; the Mac builds the request, and the model cannot send one without
  his hold. An email, a customer or a web page can never cause a filing (owner authority only,
  as for every write today).
- Nothing about what a request may do changes: repository-only, no deploy, no secrets, no
  protected paths, no reviewer changes (`REMOTE_ENGINEERING_CONTROL_V1.md`, Authority).

Needs: filing switched on (**decision 1**).

### Steps 3 to 5 — unchanged

The loop that exists builds, tests, reviews and merges. Two things keep it moving:
the reviewer's credits (**decision 4**) and the re-pin (**decision 2**).

### Step 6 — a release service, and one hold

A small service on the production host, separate from CLIVE and from worker-01:

1. **It watches trunk** for a merged SHA whose acceptance run on that exact SHA is green.
2. **It reviews that SHA** exactly as the Hetzner prompt does today — preflight, the parts and the
   evidence packets, the owner's ship rule — and raises the staging copy. What the Termius Claude
   does by hand, done by the same checks on a timer. Anything that blocks is published on a branch
   and nothing changes, as now.
3. **It asks George once.** When the review is clean and the staging copy answers, CLIVE's home
   shows "Update ready — 14 changes, review clean", with what each change does in a line and the
   record's link. He holds to deploy.
   - The hold goes to the release service's own owner-only route, not to any tool the model can
     call.
   - That hold, made on his phone over Tailscale, **is** phone check 1: the route records his
     `/whoami` the way the check does today. So the two phone checks become one gesture before and
     one automatic check after.
4. **It deploys** with today's `deploy.sh`: code and unit in one operation, the same assertions,
   automatic rollback to the previous SHA on any failure, then phone check 2 is the tablet's own
   next request (which carries his identity through the same door).
5. **It reports** on CLIVE's home and on the record branch: deployed or rolled back, and why.

Needs: the service installed with the authority to deploy (**decision 3**), the rule it applies
(**decision 5**), and whether anything may ever ship without his hold (**decision 6**).

## The decisions, his alone

1. **Switch filing on?** Set `CROOKS_ENGINEERING_HOST=worker-01` and move the engineering token
   out of parking. It was parked after the round-6 review; the request path has since been
   hardened (owner-only, repository-only, filing off unless named). *Recommendation: yes, with the
   "Fix this" hold, so nothing is filed without his gesture.*
2. **Re-pin the worker loop.** One command, owed since 26 September. *Recommendation: yes.*
3. **Install a release service with the authority to deploy reviewed SHAs after his hold.** This
   is the real grant: a root service on production that can change what runs, gated on a clean
   review and his hold. *Recommendation: yes, but only after one more round goes through the
   manual path cleanly, so the automated review is proven to agree with the manual one.*
4. **The reviewer's budget.** Every review costs API credits (round 10 stopped when they ran
   out). A monthly cap with an alert, or auto top-up. *His call; a stopped review changes nothing,
   so the failure mode is safe, only slow.*
5. **The ship rule the service applies.** Today's rule (block on anything that can be exploited,
   lose data or leak data, including what is already in production), or the regression-only rule
   proposed on 28 September (block only on what this change makes worse). *His call; the service
   applies whichever he chooses, word for word.*
   **Decided 30 September:** regression-only, with one exception: anything shown to leak
   customer data, or to write to the shop or send an email he did not confirm, blocks whether
   new or old. The rule, word for word: [OWNER_DECISIONS_2026-09-30.md](../product-memory/OWNER_DECISIONS_2026-09-30.md).
6. **May anything ship without his hold?** *Recommendation: no. Not styling, not copy, nothing,
   until the service has a record he trusts.*

## What gets built once he says yes

In this order, each through the normal loop (tests, exact-SHA review, his merge):

1. The request card and its route — CLIVE side, behind decision 1.
2. The release service as code in the repository (`scripts/release/`), with its own tests: the
   watcher, the review runner (the Hetzner prompt's checks as a program), the staging copy, the
   owner-only hold route, and the report. Installed by one command George runs once, and only
   after decision 3.
3. The "Update ready" card on CLIVE's home, reading the release service's state.

Until then, the Hetzner prompt remains the way a change reaches production.
