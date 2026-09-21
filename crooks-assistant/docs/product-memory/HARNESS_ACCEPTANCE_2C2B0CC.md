# Harness acceptance — 2c2b0cc

**Status:** ACCEPTED FOR NEXT GATE  
**Date:** 2026-09-20  
**Branch:** `claude/harness-hooks-experiment`  
**Accepted candidate:** `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`  
**Parent:** `c16d6db8cd5b7d7a7048462e367339218d178a11`  
**Accepted Builder base:** `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`

## Independent review verdict

The sixth independent adversarial review returned **ACCEPT FOR NEXT GATE**. The reviewer independently verified the remote candidate identity, exact parent and one-commit relationship, and an exact two-file repair diff: `crooks-assistant/scripts/hooks/guard_bash.py` plus `crooks-assistant/tests/test_harness_review_c16d6db_repairs.py`.

The review reproduced the previously rejected A-01/A-02 defects and adjacent heredoc-reader siblings against the parent, then verified them closed on the accepted candidate. New adversarial vectors covering coreutils destination grammar, nested/backtick/comment substitution states, malformed-later-state laundering, heredocs inside substitutions, gitleaks publication paths, and previously closed D/F/R contracts found no substantive remaining defect within scope.

## Evidence bound to accepted candidate

- New repair regression: **558 passed**.
- Prior harness regression files: **896 passed**.
- Full offline suite under xdist: **4661 passed, 10 skipped, 2 errors**; both errors were the known unchanged product-code `capabilities.tmp -> capabilities.json` parallel writer race and both passed serially. Candidate touches no `app/` code.
- Ruff: **all checks passed** when run alone.
- Pinned gitleaks 8.30.1 over `c16d6db..2c2b0cc`: **no leaks found, exit 0**.
- Candidate worktree: clean before and after review.
- Production remained clean and untouched at ratified SHA `1cf3a0f3361b79f9de208d80f501543c53c244b5`.
- No merge, deployment, project `.claude/` activation, production/global/account/connector/credential/watcher/systemd/local-Git-config mutation occurred.

## Remaining limits

D-19 remains unresolved and owner-held. This acceptance does not authorise production deployment, merge/promotion, new secrets, privilege expansion, connector/MCP changes, business writes, public exposure, destructive cleanup, or activation of project `.claude/` files beyond the exact approvals in DEC-049.

## Next gate

Engineering Orchestrator V1 may proceed under the owner's existing implementation authorisation and the canonical `ENGINEERING_ORCHESTRATOR_V1.md` / `DEV_TEAM_V1_PILOT.md` safety and review contracts. Start with the smallest repository-only deterministic control-plane slice and retain the existing bridge/watcher as the reliable single-worker path while V1 is built.
