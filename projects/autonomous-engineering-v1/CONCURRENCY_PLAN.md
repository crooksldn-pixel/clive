# Concurrency and scheduling plan

## Goal

Maximize accepted throughput without increasing owner attention or defect escape. The goal is not the largest worker count.

## Experiment ladder

Benchmark:
- 1 worker;
- 2 workers;
- 4 workers;
- 6 only if 4 is healthy;
- 8 only if evidence justifies it.

## Record at each level
- tasks/hour;
- ETAB;
- OAMAB;
- first-pass acceptance;
- repair rate;
- worker crashes;
- CPU;
- RAM;
- disk pressure;
- Claude plan/rate-limit behavior;
- CI queue;
- review queue;
- merge/path conflicts.

## Scheduler V1 inputs

Add only what is necessary:
- priority;
- dependency readiness;
- path conflict metadata;
- resource class.

Possible resource classes:
- normal;
- browser-heavy;
- test-heavy;
- exclusive-path.

Do not add duration prediction or complex optimization before basic scheduling is measured.

## Project DAG rule

An objective may start only when its dependencies are satisfied, required owner decisions are resolved, dispatcher capacity exists, and no declared conflict/resource rule blocks it.

Path overlap is a signal, not automatic proof of conflict. The final implementation plan should define conservative conflict rules and integration tasks where parallel work intentionally converges.

## Stop conditions

Do not raise concurrency if ABER, reviewer defect density, repair rate, merge conflicts, worker stability, owner interruptions or effective throughput materially worsen.
