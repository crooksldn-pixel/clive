# CLIVE - Remote Engineering Control V1: round 3 (gate and activate `ca047b89`)

The first run stopped correctly at RUNBOOK section 9 after two repairs. Round 3 was authored by
Claude Opus 5.5 (chat) and repairs the five findings of the review of `62f6e7e5`. Everything in
`/root/clive-activation/clive-activation-c23f1935/RUNBOOK.md` section 0 still applies unchanged.
Execute this file end to end; ask George only if a step says STOP.

```bash
SHA=ca047b8963bcbf7124f71037a2fa14fc4853ab8d
PARENT=62f6e7e51f72d87c3f7caae2552f0cc5eea66e85
REVIEWED_BASE=6c300c5f9a349bf2da397ecd2ac7a263849dbc60
BRANCH=claude/remote-engineering-control-v1-activation-successor-2026-09-24
E=/srv/clive-engineering  REPO=$E/repo  STORE=$E/state/engineering  RUNTIME=$E/runtime
TA=/srv/clive-engineering/src/crooks-assistant
PY=/home/user/clive/crooks-assistant/.venv/bin/python
KEY=/root/.config/clive-engineering/openai_api_key
R3=/root/clive-activation/round-3
```

## 1. Fetch this folder and check it

```bash
git -C $REPO fetch -q origin clive/evidence/activation-round-3
mkdir -p $R3 && for f in RUNBOOK_ROUND3.md build_review_job.py round3.patch proof-request-operational-alpha.json SHA256SUMS; do git -C $REPO show FETCH_HEAD:round-3/$f > $R3/$f; done
cd $R3 && sha256sum -c SHA256SUMS
git -C $REPO fetch -q origin clive/evidence/remote-engineering-activation
git -C $REPO show FETCH_HEAD:62f6e7e51f72d87c3f7caae2552f0cc5eea66e85.review.json | python3 -c "import json,sys; d=json.load(sys.stdin); json.dump([{k: f[k] for k in ('finding_id','finding','required_repair')} for f in d['findings'] if f['material']], open('$R3/prior_findings_62f6e7e5.json','w'), indent=1)"
```
Any mismatch, or fewer than five prior findings extracted: STOP.

## 2. Recreate the exact candidate and publish it

```bash
git -C $REPO worktree add -q --detach /tmp/r3 $PARENT
cd /tmp/r3 && GIT_COMMITTER_NAME="Claude Opus 5.5 (CLIVE engineering)" GIT_COMMITTER_EMAIL="claude-opus-5-5@clive.invalid" git am -q --committer-date-is-author-date $R3/round3.patch
test "$(git rev-parse HEAD)" = "$SHA"
git -C $REPO push origin "$SHA:refs/heads/$BRANCH"
git -C $REPO worktree remove --force /tmp/r3
```
If HEAD is not exactly `$SHA`, or the push is not a fast-forward from `$PARENT`: STOP.

## 3. Gate A

RUNBOOK section 3 for `$SHA`, writing `$R3/ci-$SHA.json`.

## 4. Gate B, with the owner's frozen materiality standard

```bash
OUT=$RUNTIME/exact-sha-reviews/$SHA
cd $TA && PYTHONPATH=$TA $PY $R3/build_review_job.py --repo $REPO --candidate $SHA --reviewed-base $REVIEWED_BASE \
  --prior-findings $R3/prior_findings_62f6e7e5.json --ci-evidence $R3/ci-$SHA.json --materiality \
  --out $OUT --key-file $KEY
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=$OUT PYTHONPATH=$TA $PY -m app.orchestrator.reviewers.gpt $OUT
```
`--materiality` adds DEC-057 and the 2026-09-23 self-referential convergence rule verbatim from
git: the round's criteria are frozen, credential leakage and every listed failure kind stay
material, other hardening is recorded as non-material backlog. Accept only a result with
`candidate_sha == $SHA`, principal `gpt` and verdict `READY`.

`CHANGES_REQUIRED`: STOP. Do not author a repair; publish (section 7 below) and end.

## 5. Activate (only after READY for exactly `$SHA`)

RUNBOOK sections 5 and 6, with `$SHA` in place of `c23f1935` everywhere (pin directory, unit,
smoke cycle). Use the proven flag set recorded in the first report: add
`--check-ro-path /opt/node22` beside the venv path.

## 6. Prove the no-courier path on real product work

Instead of the timing-parity request, submit `$R3/proof-request-operational-alpha.json` unchanged
as `requests/operational-alpha-acceptance-repair.json` on top of `origin/clive/control/owner-inbox`
(fast-forward). It repairs the failed operational alpha `f7be86f7`; its external oracle is full
GitHub acceptance of the resulting candidate. Then follow RUNBOOK section 7, watching only
`clive/control/status:status.json`, and record the candidate's GitHub acceptance conclusion.

## 7. Publish

Append to `clive/evidence/remote-engineering-activation` (fast-forward): `$SHA.review.json`,
`ci-$SHA.json`, and a `## Round 3` section in `activation-report.md` with the same content the
first report had for its sections. Then tell George only: "Round 3 finished - evidence published".
