# CLIVE - Remote Engineering Control V1: round 4 (gate and activate `11ab9070`)

Round 3 stopped correctly at its section 4. Round 4 was authored by Claude Opus 5.5 (chat): it
repairs both findings of the review of `ca047b89` and closes the same class one step further
out (intake refusals no longer quote supplied values). Everything in
`/root/clive-activation/clive-activation-c23f1935/RUNBOOK.md` section 0 still applies unchanged.
Execute this file end to end without asking George anything. This run is authorised to repair
and re-gate the candidate on its own (section 4b) until it is READY: George is not a trigger in
this loop. Stop only where a step says STOP.

```bash
SHA=11ab9070650abd12a7f8f990e462d5d328f2fbd9
PARENT=ca047b8963bcbf7124f71037a2fa14fc4853ab8d
REVIEWED_BASE=6c300c5f9a349bf2da397ecd2ac7a263849dbc60
BRANCH=claude/remote-engineering-control-v1-activation-successor-2026-09-24
E=/srv/clive-engineering  REPO=$E/repo  STORE=$E/state/engineering  RUNTIME=$E/runtime
TA=/srv/clive-engineering/src/crooks-assistant
PY=/home/user/clive/crooks-assistant/.venv/bin/python
KEY=/root/.config/clive-engineering/openai_api_key
R4=/root/clive-activation/round-4
```

## 1. Fetch and check

The review builder and proof request are round 3's, unchanged and already verified by you.

```bash
mkdir -p $R4
git -C $REPO fetch -q origin clive/evidence/activation-round-4
for f in RUNBOOK_ROUND4.md round4.patch SHA256SUMS; do git -C $REPO show FETCH_HEAD:round-4/$f > $R4/$f; done
git -C $REPO fetch -q origin clive/evidence/activation-round-3
for f in build_review_job.py proof-request-operational-alpha.json; do git -C $REPO show FETCH_HEAD:round-3/$f > $R4/$f; done
cd $R4 && sha256sum -c SHA256SUMS
git -C $REPO fetch -q origin clive/evidence/remote-engineering-activation
git -C $REPO show FETCH_HEAD:ca047b8963bcbf7124f71037a2fa14fc4853ab8d.review.json | python3 -c "import json,sys; d=json.load(sys.stdin); json.dump([{k: f[k] for k in ('finding_id','finding','required_repair')} for f in d['findings'] if f['material']], open('$R4/prior_findings_ca047b89.json','w'), indent=1)"
```
Any mismatch, or fewer than two prior findings extracted: STOP.

## 2. Recreate the exact candidate and publish it

```bash
git -C $REPO worktree add -q --detach /tmp/r4 $PARENT
cd /tmp/r4 && GIT_COMMITTER_NAME="Claude Opus 5.5 (CLIVE engineering)" GIT_COMMITTER_EMAIL="claude-opus-5-5@clive.invalid" git am -q --committer-date-is-author-date $R4/round4.patch
test "$(git rev-parse HEAD)" = "$SHA"
git -C $REPO push origin "$SHA:refs/heads/$BRANCH"
git -C $REPO worktree remove --force /tmp/r4
```
If HEAD is not exactly `$SHA`, or the push is not a fast-forward from `$PARENT`: STOP.

## 3. Gate A

RUNBOOK section 3 for `$SHA`, writing `$R4/ci-$SHA.json`.

## 4. Gate B, same frozen materiality standard as round 3

```bash
OUT=$RUNTIME/exact-sha-reviews/$SHA
cd $TA && PYTHONPATH=$TA $PY $R4/build_review_job.py --repo $REPO --candidate $SHA --reviewed-base $REVIEWED_BASE \
  --prior-findings $R4/prior_findings_ca047b89.json --ci-evidence $R4/ci-$SHA.json --materiality \
  --out $OUT --key-file $KEY
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=$OUT PYTHONPATH=$TA $PY -m app.orchestrator.reviewers.gpt $OUT
```
(The builder's prior-findings heading still names `abaefa52`; the findings listed are the
`ca047b89` review's. Cosmetic; do not edit the builder.) Accept only `candidate_sha == $SHA`,
principal `gpt`, verdict `READY`. `READY`: go to section 5. `CHANGES_REQUIRED`: section 4b.

## 4b. Repair autonomously until READY

On `CHANGES_REQUIRED`, author the successor yourself, as the first run did for rounds 1-2:

- one new commit on `$BRANCH` (fast-forward, no amend, no force) repairing every material
  finding, touching only `crooks-assistant/app/remote_engineering/`,
  `crooks-assistant/scripts/remote_engineering.py`, `crooks-assistant/tests/test_remote_engineering.py`
  and `crooks-assistant/docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md`;
- a regression test per finding that fails on the previous SHA; no existing assertion weakened;
  also check the finding's whole class, not only its example, so the next review has less to find;
- pre-flight ruff and `tests/test_remote_engineering.py` in the project's `NamespaceSandbox` as
  before, then push, Gate A (section 3), Gate B (section 4) with `--prior-findings` built from the
  latest review's material findings and `--reviewed-base` unchanged;
- after every round, append that SHA's `review.json`, `ci-*.json` and a short round section to
  `clive/evidence/remote-engineering-activation`, so progress is visible on GitHub.

From the first successor on, `$SHA` everywhere below means the newest successor's exact SHA.
Repeat until `READY`, then continue at section 5. STOP only if: a repair needs any other path, a
protected path, a credential, production or an owner decision; the material-finding count fails to
fall across two consecutive rounds (the DEC-057 convergence stop); six successor rounds have been
authored in this run; or Gate A fails twice on one SHA for a non-transient reason. On STOP, publish
(section 7) and end.

## 5. Activate (only after READY for exactly `$SHA`)

RUNBOOK sections 5 and 6 with `$SHA` in place of `c23f1935`, the proven flag set (add
`--check-ro-path /opt/node22` beside the venv path), and this production check in place of
RUNBOOK 6.4's `find ... -newer` test, which the live assistant's own logs and caches now trip
(your round-3 report R3.8). Take the baseline immediately before installing the unit:

```bash
prod_state() {
  for d in /opt/crooks-os /opt/crooks-interactive; do
    if git -C "$d" rev-parse --git-dir >/dev/null 2>&1; then
      echo "$d $(git -C "$d" rev-parse HEAD) $(git -C "$d" status --porcelain --untracked-files=no | sha256sum | cut -c1-16)"
    else
      echo "$d $(find "$d" -type f -not -path '*/logs/*' -not -path '*/.cache/*' -not -path '*/__pycache__/*' -not -name '.catalogue-cache.txt' -printf '%P %s %T@\n' 2>/dev/null | sort | sha256sum | cut -c1-16)"
    fi
  done
  systemctl cat crooks-assistant.service crooks-bridge-watcher.service 2>/dev/null | sha256sum | cut -c1-16
  systemctl is-active crooks-assistant.service crooks-bridge-watcher.service
}
prod_state > $R4/prod-before.txt
```
After the smoke cycle and again after the proof objective: `prod_state | diff $R4/prod-before.txt -`
must be empty. Non-empty: stop the new unit (`systemctl disable --now clive-remote-engineering`),
record the diff, STOP. Record which branch (git or manifest) each directory used.

## 6. Prove the no-courier path on real product work

Submit `$R4/proof-request-operational-alpha.json` unchanged as
`requests/operational-alpha-acceptance-repair.json` on top of `origin/clive/control/owner-inbox`
(fast-forward). Follow RUNBOOK section 7, watching only `clive/control/status:status.json`, and
record the resulting candidate's GitHub acceptance conclusion.

## 7. Publish

Append to `clive/evidence/remote-engineering-activation` (fast-forward) whatever section 4b has
not already published: the final SHA's `review.json` and `ci-*.json`, `prod-before.txt` if taken,
and a `# Round 4` section in `activation-report.md` in the same shape as round 3's, naming the
final SHA and whether the loop is live. Then tell George only one line: "Activated - loop live"
or "Stopped - evidence published".
