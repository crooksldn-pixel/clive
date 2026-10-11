# Baseline and measurement plan

Do not claim autonomy or speed improvement without a baseline.

## Primary metrics

### OAMAB
Owner Active Minutes per Accepted Build.

Count active owner effort only:
- clarifying requirements;
- making product decisions;
- manually relaying errors;
- terminal/branch management performed by George;
- reviewing final evidence.

Do not count passive waiting.

### ETAB
Elapsed Time per Accepted Build.

Record request, ready, assigned, builder start, candidate ready, checks complete, GitHub acceptance complete, review complete, repairs, accepted and trunk landing.

### ABER
Accepted Build Escape Rate.

A defect that should have been caught before acceptance but is discovered after acceptance/trunk/live, depending on the comparison window.

## Secondary metrics
- owner interruptions per project;
- first-pass review pass rate;
- repair rounds;
- check duration;
- CI duration;
- review duration;
- queue time;
- conflict/rebase rate;
- worker failure rate;
- Bench regression count;
- blocked-reason distribution.

## Representative baseline set

Choose 5–10 real or reproducible CLIVE jobs spanning:
1. small bug fix;
2. focused backend feature;
3. UI + backend feature;
4. external API integration;
5. test-only repair;
6. behavioral/prompt/tool-routing change;
7. cross-component refactor;
8. one ambiguous request that should require owner judgment.

Prefer historical tasks that can be reconstructed without touching production.

## Baseline rule

Measure how George actually builds today. Do not make the current workflow artificially worse.

After V1, rerun the same or equivalent tasks under one durable worker, measured multi-worker mode and Project/DAG mode where appropriate. Compare OAMAB, ETAB and ABER. Targets discussed elsewhere remain hypotheses until measured.
