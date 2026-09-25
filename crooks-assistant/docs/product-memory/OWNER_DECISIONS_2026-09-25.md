# Owner Decisions - 2026-09-25

Recorded from the owner's explicit answers in the Opus 5.5 engineering session, after the external review brief of the same day (trunk red since PR #8, landings not gated on GitHub acceptance, safety core and loop code unprotected, engineering on the production host).

## Synthetic credentials in tests

Fake credentials in tests are assembled at runtime through one shared test helper, and that is the written rule; they are not listed in the secret-scan baseline. This supersedes the 2026-09-24 authorisation of a baseline entry for HumanisingTests.swift (branch `claude/release-secret-baseline-2026-09-24`, `99d8ace6`), which was retired on 2026-09-24 without the Director knowing it carried that decision. The scanner and its rules are unchanged, so every real credential is still caught.

## Loop update

Approved, as one reviewed change to the engineering loop taking effect only through an owner-gated re-pin: builders may run their objective's declared checks in the loop's check sandbox (no credentials reach a check, no network, advisory only); an objective counts as accepted, and a landing into `clive/trunk` may happen, only after a green GitHub acceptance run on that exact SHA; the product safety core, the evidence tools and the loop's own code join the protected paths (`app/tools/gate.py`, `app/readonly.py`, `app/tools/shopify_writes.py`, `app/tools/gmail_writes.py`, `app/actions/`, `scripts/acceptance_provenance.py`, `.gitleaks.toml`, `.gitleaks-baseline.json`, `pyproject.toml`, `app/remote_engineering/`, `scripts/remote_engineering.py`); builders read product memory from the trunk once the consolidation lands.

## Engineering off the production host

Approved: once clive-worker-01 has proven itself, the engineering loop on the production VPS is stopped and disabled, and its reviewer key and worker token are removed from that host. Production keeps only the CLIVE runtime and business credentials (IDEA-047: do not make production the development environment).

## The Mac's role

The owner's Mac hosts Swift and iPhone app builds and tests, which nothing else can run, and serves as spare builder capacity. It is not a production host.
