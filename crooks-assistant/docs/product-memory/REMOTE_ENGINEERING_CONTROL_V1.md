# Remote Engineering Control V1

Status: design mandate for repository-only implementation. This does not authorise deployment, production changes, secrets access, business writes, permission changes, or owner-only decisions.

## Objective

Restore the no-courier operator experience:

Owner -> GPT Director -> bounded remote engineering inbox -> existing deterministic dispatcher -> isolated Claude worker(s) -> independent GPT exact-SHA review -> accepted/integrated candidate.

The owner must not have to paste routine test, repair, review, or worker-routing commands into a terminal.

## Transport

Use GitHub as a transport only, never as engineering lifecycle truth.

A dedicated remote ref carries immutable request files. V1 default:

`refs/remotes/origin/clive/control/owner-inbox`

The adapter may fetch that ref from the configured existing repository remote. It must not accept arbitrary remote URLs.

Requests are strict JSON records with a schema/version and immutable request id. They carry only fields needed to create repository-only engineering objectives: title, requested outcome, base ref/SHA, allowed paths, acceptance criteria, checks, target branch and repair limit.

Do not encode credentials, deployment instructions, business actions, owner judgments, or shell strings with hidden authority.

## Authority

Remote ingress has exactly the same or less authority as existing CLI objective intake.

- repository_only only;
- reuse the existing Objective/Check validation and PROTECTED_PATHS rules;
- default prohibited actions remain mandatory;
- a request cannot resume BLOCKED/OWNER_GATE, alter reviewer principals, change dispatcher/kernel/runtime code, deploy, touch services, or change secrets;
- remote origin is declared, not cryptographically owner-verified;
- owner-only actions remain owner-only.

No request-file wording may elevate authority.

## Idempotence and replay safety

- Immutable request id maps deterministically to one engineering objective id.
- Reprocessing the same exact request is idempotent.
- Same request id with different bytes is REFUSED.
- Maintain durable receipt/provenance in the existing engineering store or a separate append-only runtime receipt that never becomes lifecycle truth.
- Restart must not duplicate an objective, worker attempt, review, or integration.

## Controller behaviour

Provide a small repository-only adapter/CLI that can:

1. fetch/read the dedicated inbox ref;
2. discover unseen immutable request records;
3. validate them;
4. intake accepted requests through the existing Objective intake;
5. advance the existing Dispatcher, not a second lifecycle engine;
6. expose machine-readable status/results suitable for a GPT Director polling through GitHub;
7. optionally run as a long-lived polling loop with bounded interval.

It may import and call existing orchestrator components. It must not modify the frozen kernel or protected dispatcher surfaces.

Results are observed from authoritative kernel records and published candidate refs. Do not create a second task state database.

## Outbound visibility

The GPT Director must be able to determine from GitHub-visible state, without SSH:

- request accepted/refused;
- objective/task id;
- current lifecycle stage;
- blocker/owner gate;
- candidate exact SHA;
- review mechanism/verdict;
- accepted/integrated exact SHA;
- evidence summary sufficient to decide the next engineering action.

A read-only status projection file/ref may be published if necessary, but it is explicitly a projection of kernel records, never authority. Do not expose transcripts containing secrets.

V1 activation uses a dedicated disposable status ref, `refs/heads/clive/control/status`, containing only `status.json`. The long-lived `remote_engineering.py run` loop performs one bounded inbox poll, one existing Dispatcher tick, publishes that projection, then sleeps for the configured interval. It does not alter production services or application runtime.

## Safety and process execution

- No arbitrary shell execution from inbox content.
- Checks use the existing structured Check argv model and existing sandbox.
- Never interpolate request text into a shell.
- No credential values may be logged or written to git.
- Host-side credential file paths may be supplied by the operator exactly as the existing dispatcher accepts them; the adapter never publishes or echoes their contents.
- Fail closed on malformed requests, protected scope, changed request bytes, unknown schema, remote mismatch, or inability to establish safe dispatcher/check execution.
- Candidate publication may use the existing dispatcher `--publish-remote` semantics only.

## V1 files

Prefer a self-contained implementation outside protected authority surfaces, for example:

- `crooks-assistant/app/remote_engineering/`
- `crooks-assistant/scripts/remote_engineering.py`
- `crooks-assistant/tests/test_remote_engineering.py`

Do not change `app/orchestrator/dispatcher.py`, `objectives.py`, the frozen lifecycle kernel, reviewer registry, CI workflow, systemd, watchers, or secrets tooling.

## Tests

At minimum prove:

- valid request becomes exactly one existing Objective/task;
- replay is idempotent;
- same id/different bytes is refused;
- protected paths are refused by reused canonical validation;
- malformed schema fails closed;
- no arbitrary shell field is accepted/executed;
- OWNER_GATE/BLOCKED cannot be lifted remotely;
- restart/re-poll does not duplicate work;
- status output is derived from existing records;
- credential values never enter request/status serialization;
- remote ref/remote name is bounded and cannot become arbitrary URL execution;
- no second lifecycle truth is created.

## Definition of done

Repository-only candidate passes focused tests and independent GPT exact-SHA review. It is not deployed by this objective.

After acceptance, the owner may separately authorise one host-side activation of the polling adapter. Once activated, routine repository-only engineering should no longer require the owner to relay terminal commands.
