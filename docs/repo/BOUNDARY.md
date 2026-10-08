# The boundary: what lives where

Why this page exists: the CROOKSLDN Shopify theme reached the CLIVE repository by accident. George
(7 October 2026): "it's important, so you need to make sure there is a clear boundary between the
two", and the repository should be clean, "no messy branches". This page says what lives where,
the rules that keep it that way, and the exact steps that finish the move.

## What lives where

| What | Where | How it ships |
|---|---|---|
| **CLIVE**, the assistant and its engineering control plane | `crooksldn-pixel/clive` (public), branch `clive/trunk`, folder `crooks-assistant/` | Pull request to `clive/trunk`, green acceptance on the exact head, then George's deploy ([DEPLOY_LINUX.md](../../crooks-assistant/docs/DEPLOY_LINUX.md)) |
| **The Shopify theme** (with the phone app `mobile/` and the returns desk) | `crooksldn-pixel/crooksldn-theme` (private), branch `main`. Until `move_theme.sh` has run, its source is the branch `claude/crooksldn-theme-init-bnen7a` in clive | Shopify CLI, from the theme repository. Never through CLIVE |
| **The sister apps**, CROOKS Returns and CLIVE Shipping (one embedded Shopify app, CROOKS Operations) | Branch `claude/compassionate-dirac-44hnee` in clive, for now | George's Docker Compose on the production host, outside CLIVE (DEC-066) |
| **The build loop's branches** | `clive/control/owner-inbox`, `clive/control/status`, `clive/control/worker-01-inbox`, `clive/control/worker-01-status`; `clive/evidence/*`; `clive/engineering-state`; and one `clive/objective/<id>` per build | Written by the loop, read by CLIVE's Builds page. The control, evidence and state branches are never archived. A `clive/objective/<id>` branch is archived once its build has landed or been superseded, never while it is in flight: only from the list, by `archive_branches.sh`, which refuses a branch that has moved since the list was made |
| **Kept records** | `crooks-ai-bridge` (the retired bridge's inbox and outbox), `claude/venture-engine-v1-2026-09-29` (parked by George) | Not shipped |
| **Archives** | Tags `archive/<branch, every / made ->` in clive, and in the theme repository for the theme's experiments and research | Never. A tag only keeps the commits |

The sister apps' branch was cut from the theme's line (commit `40e6bc6d`), so it also carries the
20 July theme snapshot. When the sister apps get a home of their own, that goes with them. CLIVE's
tests pin one of its commits (`crooks-assistant/tests/returns_service.py`), so it stays until then.

## The rules

1. **CLIVE work never touches the theme.** No theme file goes into clive. No CLIVE build pushes to
   the theme repository, or to a Shopify theme.
2. **Theme changes ship with the Shopify CLI from the theme repository**, to an unpublished theme
   first. Publishing is George's say-so, as before.
3. **clive is public.** Nothing secret and no customer data goes into it, on any branch.
4. **A branch that has landed is archived**: tagged `archive/<name>` at its tip, then deleted.
   `scripts/repo/archive_branches.sh` does it from a list, never by hand.

Before anyone uses `npm run push` from the theme repository, check its target. The theme's
`package.json` pushes to theme `202053779799`, which its README calls the unpublished staging
theme. The theme's own commits of 31 August say that theme became the published live theme
(`6a57758c`, `af3cef0c`). Shopify admin > Online Store > Themes settles which theme is live now.

## George's one step: make `clive/trunk` the default branch

GitHub's default branch is still `claude/shopify-theme-dev-setup-934mht`, a stale theme-only branch,
so a visitor to the public repository lands on a theme README. On github.com:
**crooksldn-pixel/clive > Settings > General > Default branch > the switch icon > `clive/trunk` >
Update > "I understand, update the default branch."**

Both scripts refuse to delete the default branch, so this has to happen before step 7 below.

Optional, also in Settings > General: under Pull Requests, "Automatically delete head branches"
deletes a branch when its pull request merges. Leave it off if you would rather keep landed
branches until they are archived with a tag.

## The order of operations (for the Termius Claude)

0. **Before you start:** this change is on `clive/trunk` (it carries the imported history; without
   it the 9 knowledge-only branches wait). George has made `clive/trunk` the default branch.
1. **Create the empty private repository** `crooksldn-pixel/crooksldn-theme`: no README, no
   .gitignore, no licence.
2. **`scripts/repo/move_theme.sh`**, then **`scripts/repo/move_theme.sh --apply`.** It pushes the
   theme branch as `main` with its full history, and the 11 other theme branches as archive tags.
   It reads each back.
3. **Verify:** `main` in the theme repository is `7b454b604e6372fd21df287e6b1b8528a6126758`, and
   the repository is private.
4. **Close the stale pull requests #1 and #2** (commands below).
5. **`scripts/repo/archive_branches.sh`**, then **`scripts/repo/archive_branches.sh --apply`.**
6. **Check the result:** the branches left are the kept ones, the held ones below, and any made
   since this list.
7. **`scripts/repo/move_theme.sh --apply --delete-public`.** Only now is the theme deleted from clive.

### Closing pull requests #1 and #2

Both are drafts from 18 and 19 September against branches that no longer matter. Close them after
this change is on `clive/trunk`, before `archive_branches.sh` deletes their branches:

```bash
gh api -X POST repos/crooksldn-pixel/clive/issues/1/comments -f body='Closed as stale: everything here reached clive/trunk (staged in _incoming/truth by PR #10 and folded in by PR #14). The branch is kept as the tag archive/claude-product-memory-foundation.'
gh api -X PATCH repos/crooksldn-pixel/clive/pulls/1 -f state=closed
gh api -X POST repos/crooksldn-pixel/clive/issues/2/comments -f body='Closed as stale: OPS_RUNBOOK.md is kept as history in crooks-assistant/docs/history/branches/2026-09-19-ops-runbook/, and later product memory replaced the rest. The branch is kept as the tag archive/chatgpt-ops-memory-2026-09-19.'
gh api -X PATCH repos/crooksldn-pixel/clive/pulls/2 -f state=closed
```

### The prompt to paste into the Termius Claude

```text
Finish the boundary between CLIVE and the Shopify theme in crooksldn-pixel/clive, exactly as its
docs/repo/BOUNDARY.md says. Do the steps in order. Stop at the first step that fails or refuses
something, and report it to George with the script's own words. Never work around a refusal.

Never: force-push; delete a branch or tag by hand; edit docs/repo/*.txt to get past a refusal;
open or print mobile/SETUP.md (it may hold a token George is rotating); touch clive/trunk,
clive/control/*, clive/evidence/*, clive/engineering-state, crooks-ai-bridge,
claude/compassionate-dirac-44hnee, claude/venture-engine-v1-2026-09-29 or claude/n2-*.

0. Get the scripts:
     git clone https://github.com/crooksldn-pixel/clive.git ~/clive-boundary   (or: cd to an existing clone and git fetch origin)
     cd ~/clive-boundary && git fetch origin && git checkout --detach origin/clive/trunk
   If scripts/repo/move_theme.sh is not there yet, run: git checkout --detach origin/claude/n2-boundary
   Read docs/repo/BOUNDARY.md.
1. Check the default branch: git ls-remote --symref origin HEAD
   It must say "ref: refs/heads/clive/trunk". If it does not, ask George to switch it
   (BOUNDARY.md, "George's one step") and carry on with steps 2 to 6; step 7 waits for it.
2. Create the EMPTY private repository:
     gh repo create crooksldn-pixel/crooksldn-theme --private --description "CROOKSLDN Shopify theme"
   (no README, no .gitignore, no licence). Without the GitHub CLI, ask George to create it on
   github.com the same way. Then git ls-remote https://github.com/crooksldn-pixel/crooksldn-theme.git
   must succeed and print nothing.
3. Move the theme:
     scripts/repo/move_theme.sh                 (dry run: expect "To push: 12" and "Refused: 0")
     scripts/repo/move_theme.sh --apply         (expect "in theme" twelve times, "Refused: 0. Failed: 0.")
   If GitHub refuses a push because it found a secret, STOP. Do not allow or bypass it. Tell George.
4. Verify:
     git ls-remote https://github.com/crooksldn-pixel/crooksldn-theme.git refs/heads/main
   must print 7b454b604e6372fd21df287e6b1b8528a6126758, and
     curl -s -o /dev/null -w '%{http_code}\n' https://api.github.com/repos/crooksldn-pixel/crooksldn-theme
   must print 404 (private).
5. If git cat-file -e origin/clive/trunk:crooks-assistant/docs/history/branches/README.md succeeds,
   close pull requests #1 and #2 with the four gh api commands in BOUNDARY.md. Otherwise skip
   this step and say so.
6. Archive the landed and superseded branches:
     scripts/repo/archive_branches.sh           (dry run: expect 229 on the list and "Refused: 0";
                                                 9 WAITING lines are expected if step 5 was skipped)
     scripts/repo/archive_branches.sh --apply 2>&1 | tee ~/archive-branches-$(date +%F).log
7. Only if step 1 said clive/trunk: delete the theme from clive:
     scripts/repo/move_theme.sh --apply --delete-public   (expect "Deleted from clive: 12")
8. Report to George: each step's summary line, the output of git ls-remote --heads origin (the
   branches left), and every REFUSED, WAITING or FAILED line with its reason. Remind him that
   anything that was public stays visible in old clones and forks, so the possible token in
   mobile/SETUP.md (commit af9d1dc9) must be rotated whatever happened.
```

## What stays public whatever happens

Deleting a branch does not unpublish it. Existing clones and forks keep it, and GitHub can serve an
old commit by its SHA for some time. `clive/trunk`'s own history starts with the 19 July theme
import and keeps the 20 July snapshot (`c7988fa4`) that sat at the root until this change; rewriting
trunk's history to remove it was not part of the approval. So the possible token in
`mobile/SETUP.md` (commit `af9d1dc9` on the theme branch) must be rotated regardless.

## The lists, and how they were made

- [`BRANCHES_TO_ARCHIVE.txt`](BRANCHES_TO_ARCHIVE.txt): 229 branches, each with its SHA and why it
  can go.
- [`THEME_BRANCHES.txt`](THEME_BRANCHES.txt): the theme branch, which becomes `main`, and 11 theme
  experiments and research branches, which become archive tags in the theme repository. All 12 are
  on the theme's own line (first commit `224acdc8`, the 19 July theme import) and hold no CLIVE
  file.

On 7 October every branch on the remote was fetched and checked against `clive/trunk` at
`a68536c6`, starting from the 7 October branch audit (BRANCHES.json). A branch is on the archive
list only when one of these checks passed:

| Reason | Check | Branches |
|---|---|---|
| Landed: an ancestor of clive/trunk | `git merge-base --is-ancestor` | 153 |
| Landed some other way | GitHub says its pull request merged with this exact head, and every file it changed is on trunk, or was in trunk's history before trunk moved on. Or it is an ancestor of a branch that landed that way (the night builds in `claude/overnight-build`, the Returns branches in `claude/returns-and-design`), or of the kept sister-apps branch (`codex/printnode-shipping`). Or its only other commit is patch-identical to PR #93 (the CI-proof branches). For lineages that landed squashed and were edited after (the support investigator, `skill-read-runtime-tool-4` in PR #98, `uk-midnight-clock-sweep-2` in PR #99, the product-memory branches), most of its added lines (75 to 98%) are on trunk | 40 |
| Superseded | A numbered successor of the same build is an ancestor of trunk; or DECISIONS records the retirement ("Retirements, 2026-09-24": the bridge watcher, engineering-team-activation-v1, the release secret baseline, the orchestrator-freeze and control-plane-progress streams); or PR #3 or PR #71 fixed the same thing another way | 27 |
| Knowledge-only | The documents that never reached trunk are copied verbatim into [`crooks-assistant/docs/history/branches/`](../../crooks-assistant/docs/history/branches/README.md), checked by `tests/test_repo_boundary.py` against `MANIFEST.txt`. These lines wait until that is on trunk | 9 |

The scripts check again when they run: a branch that moved since is refused.

### Kept (never on either list)

`clive/trunk`, `clive/control/*` (4), `clive/evidence/*` (3), `clive/engineering-state`,
`crooks-ai-bridge`, `claude/compassionate-dirac-44hnee`, `claude/venture-engine-v1-2026-09-29`,
the night builds `claude/n2-*`, and the theme branch until `move_theme.sh --delete-public` has run.
`archive_branches.sh` refuses to run if any of them is ever put on its list.

A `clive/objective/<id>` branch is kept while its build is in flight. The 67 on the archive list
had all landed or been superseded when the list was made, and on 8 October each was still at its
listed SHA. Five objective branches are not on it:
- `status-publishes-findings` is held for George (below);
- `fixture-clock-dst-nights` and `tool-audit-edge-cases` are BLOCKED in the loop's status, not
  landed, so they stay;
- `retire-returns-stub` and `skill-installer-followups` landed on `clive/trunk` on the night of
  7 October, after the list was made, so a later list can take them.

### Held: not archived, because George decides or a record would be lost

| Branch | SHA | Why it stays |
|---|---|---|
| `clive/objective/status-publishes-findings` | `2738f254` | George decides. Trunk took the opposite rule (the loop's status never publishes review findings). Close it, or re-file it as an owner-gated build |
| `claude/harness-hooks-experiment` | `2c2b0cc4` | George decides. Claude Code hooks that stop a builder writing to production. Its builder-environment documents are now imported; the recommendation was to close it |
| `claude/compassionate-johnson-lzl6dd` | `df668013` | George decides. The Phase 6 Mac menu-bar app (Swift). MAP parks the Mac runtime for deletion on his yes (19 October) |
| `claude/sleepy-cerf-k0f4zb` | `a5823252` | George decides. 13 Instagram agent skills, on the theme's line. Land them into `.claude/skills`, or close |
| `claude/deploy-review-round-6-findings` | `4e1da401` | The deploy-review round 6 record; PR #48 closed its findings. The record never reached trunk: import it into `crooks-assistant/reports/`, then archive |
| `claude/deploy-review-round-7-findings` | `5b6e67bb` | The same for round 7 (PR #49) |
| `claude/deploy-review-round-8-findings` | `74bd8301` | The same for round 8 (PR #51) |
| `claude/deploy-review-round-9-findings` | `0d04dfa5` | The same for round 9 (PR #54), with its 92 review files |
| `claude/deploy-review-round-10-findings` | `7510202c` | The same for round 10 (PR #55), with its 64 review files |
| `claude/deploy-review-round-12-findings` | `e6fa3d9d` | The same for round 12 (PR #58) |
| `claude/deploy-round-13-record` | `090d6f8f` | The record of round 13's deploy (`87e10c33`), never on trunk. Import, then archive |
| `claude/worker-01-findings-2026-09-27` | `bd121e12` | worker-01's findings of 27 September, never on trunk. Import, then archive |
