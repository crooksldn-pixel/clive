# Failure and recovery plan

Durability is a first-class acceptance requirement.

## Required drills

Deliberately test:
1. close Claude Desktop during a running project;
2. drop SSH;
3. kill the interactive supervisor Claude process;
4. restart the dispatcher;
5. terminate a builder process;
6. crash a reviewer process;
7. reboot the worker host;
8. make GitHub temporarily unavailable;
9. make Claude temporarily unavailable/rate limited;
10. move trunk while a candidate is under review;
11. make a candidate/workspace stale;
12. attempt duplicate dispatch;
13. partially fail status publication.

## Required outcome

No scenario may cause lost accepted work, duplicate authoritative execution, silent scope widening, false COMPLETE, review against the wrong SHA, automatic production deploy, or unrecoverable state without a clear blocker.

## Recovery principles

- durable state lives outside Desktop/SSH session state;
- attempt identity is explicit;
- candidate SHA is immutable once dispatched to review;
- retries are idempotent or create a new explicit attempt;
- reviewer result is bound to task/revision/attempt/SHA;
- stale candidates are rejected or revalidated;
- restart reconstructs state from durable records;
- owner sees a concise blocker only when autonomous recovery is exhausted.

## FMHY lesson

The standalone FMHY experiment showed the immediate failure mode: an interactive Claude process died when its SSH terminal disappeared while work remained uncommitted on disk. Autonomous Engineering V1 must make that irrelevant for durable CLIVE engineering work.
