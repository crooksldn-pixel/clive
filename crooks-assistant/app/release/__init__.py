"""The release service: CLIVE's deploys done by a program on the production host, instead of a prompt
George pastes into his Termius Claude.

Why it exists. George, 7 Oct 2026, wants deploys "to just happen (or fix themselves) without him
relaying commands between Claude and the Termius Claude", and approved exactly: "Release service. I
build it tonight, switched off. It only deploys once you've said who holds deploy authority."

    settings.py   the switches: off by default, and the deploy rule, "off" until George names one
    host.py       every command it runs and every file it touches, behind one seam tests replace
    facts.py      what is true now, only read: the trunk's head, production, acceptance, the diff
    authority.py  what the rule asks for: an exact-SHA review record, or George's waiver
    decide.py     deploy or not, with every reason in plain words (pure)
    deploy.py     DEPLOY_LINUX.md "Deploying a new build" as code, with automatic rollback
    record.py     the deploy record, in the shape of reports/deploy-<sha>.md, and its branch
    state.py      the lock, the status CLIVE shows, and the SHAs it will not try again
    service.py    one tick of the timer, and the plan a dry run prints
    status.py     the status, read-only, for CLIVE's Builds screen
    __main__.py   python -m app.release tick | plan | status | waive

  CLIVE's half of Deploy now (DEC-072), loaded by the running app, never by the service:
    offer.py      the version waiting to go live, whether his hold can deploy it, and the progress shown
    approve.py    his hold and passkey made into an approval for one SHA; his phone's /whoami keeps it

What it promises:
- Nothing happens unless CLIVE_RELEASE_ENABLED is on AND CLIVE_RELEASE_RULE names a rule, and
  nothing changes on production unless CLIVE_RELEASE_DRY_RUN is false in so many words.
- Only clive/trunk's head is deployed, only forward from what production runs, only with GitHub
  acceptance green on that exact SHA and the authorisation the rule asks for, one at a time.
- Any failure after a change rolls production back to the SHA and unit it ran before. A rollback
  that fails, or a deploy stopped part way, stops the service until a person looks.
- It never prints, records or pushes a secret, a journal line or a customer detail, and it pushes
  only claude/deploy-<sha8>-record branches.
- The model never reaches it: no tool. CLIVE reads its status, and George's own owner-only routes
  (app/routes/release.py) write his passkey-signed approval where the service looks; the service
  believes it only by that signature, for exactly one SHA, unexpired and unused.
"""
