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

Projection bounds (activation successor of `abaefa52`):

- each request's task fields come from the task's highest recorded revision, so a repair revision's stage, candidate, review, acceptance and integration are what the Director sees (`revision` is included);
- the status branch must be under `clive/control/` and never the owner inbox, and an existing status branch is only extended when its tip holds exactly `status.json`; pushes are plain fast-forwards from a freshly fetched head, never forced; every git call is time-bounded;
- content identical apart from `generated_at` is republished at most every `--status-heartbeat-s` (default 600 s), which doubles as the loop's liveness signal: a `generated_at` older than the heartbeat plus one interval means the loop is not running;
- `adapter.intake_error` reports a cycle whose inbox could not be read or held a changed request id. A changed request is named by its validated request id only; any other intake failure is a fixed sentence, never raw git/transport output.

Loop failure isolation: an inbox or projection transport failure admits nothing new but never stops the existing Dispatcher from supervising already-recorded objectives; kernel, store and Dispatcher errors still stop the loop (fail closed), and exit status 4 means another dispatcher holds the runtime lock. Dispatcher transitions are journalled under `--dispatcher-operator` (default `clive-dispatcher@<host>`), intake under `--operator`.

Intake and reporting bounds (activation successor of `c23f1935`):

- admission is atomic per poll. The whole discovered snapshot is preflighted before the first write, so a snapshot that re-presents an already-decided request id with different bytes, or that carries one id twice with different bytes, admits nothing at all. Whether a changed request id is refused no longer depends on filename order, and no cycle is left half-applied;
- nothing this loop reports carries git's output, in either direction. A transport failure reports a fixed sentence on the projection *and* in the value the host prints to its own log; git names the remote it was talking to, and an authenticated remote URL carries a credential in its userinfo, so that output never enters an exception message (`TransportError`). The operator diagnoses a transport failure from git's stderr at the console;
- a rejected value is never echoed back. A record whose `schema_version` is wrong is refused without repeating the value supplied, because a requester chose it and it could itself be a credential;
- an inbox record too malformed to yield a request id earns no receipt, but is still visible: `refused_records` projects it, keyed by the bounded inbox path it came from plus the digest of its exact bytes rather than by an id this adapter never trusted, carrying a redacted schema diagnostic only. It is regenerated deterministically from the same snapshot on every poll, so it survives a restart;
- `--interval` (1-3600 s) and `--status-heartbeat-s` (1-86400 s) must be finite and inside those ranges, and are refused before the loop starts. `argparse` accepts `nan` and `inf` for a float: a NaN interval kills the loop on its first sleep, an infinite one parks it for ever, and a non-positive or NaN heartbeat silently disables `generated_at` suppression, turning an idle loop back into one status commit per cycle.

Echo bounds (activation successor of `05fe8046`). Nothing a requester or a mistyped flag supplied is ever repeated back into a receipt, a host log or the status projection:

- `base_ref` is a bounded git ref validated by the request schema, before `git rev-parse` is asked anything. Its character set excludes `:`, `@`, `~`, `^` and whitespace and its first character must be alphanumeric, so it can be neither a URL (which could carry a credential) nor a revision expression, and it can never be read as an option by the command it is interpolated into. A ref that resolves to something other than the declared `base_sha` is refused without repeating the ref;
- validation locations are filtered through the field labels this host itself defined. For a forbidden extra field pydantic's location segment *is* the requester's key name, so a credential placed in an unknown key's **name** would otherwise travel exactly as one in its value would; unknown labels become `<redacted>`;
- `source` is only ever `<directory>/<request_id>.json` -- a path that repeats nothing the projection does not already publish beside it. A bounded character set is no defence for a filename, because a credential is alphanumeric and `sk-....json` is well formed; so every other path, and every record too malformed to have a trusted id, is located by `<directory>/#<sha256 of its exact bytes>` instead;
- an invalid remote, branch, directory or status path is refused without printing the rejected value, so a one-shot `poll` cannot print a credential an operator mistyped into `--remote`.

Crash-safe provenance (activation successor of `11ab9070`). The lifecycle write and the receipt cannot be one atomic act, so the window between them is closed from the front:

- before the first lifecycle write, an id is bound to the exact bytes being admitted under it by a write-once **claim** (`<adapter-root>/claims/<request_id>.json`, schema `clive.remote_engineering_claim.v1`). Like a receipt it is adapter provenance, never authority: it admits nothing and advances nothing;
- the claim also pins `created_at`. A resumed admission therefore rebuilds the *byte-identical* objective rather than a merely equivalent one. Without this, a replay after a crash reaches the objective store with a later timestamp, is refused as "already recorded differently", and a durable **refused** receipt is written for a request that was in fact admitted -- so the public projection permanently contradicts a live task;
- on restart only the claimed digest resumes. Every other byte sequence for that id is refused, including bytes that differ only in formatting and parse to the same request, so provenance cannot be replaced by a later submission;
- a claimed-but-unreceipted id participates in the snapshot preflight too, so an interrupted admission refuses its whole cycle before any write, exactly as an already-receipted one does;
- claims and receipts are created with an atomic create-if-absent (`os.link`), so two processes that both find an id unclaimed cannot both write it: the create decides, and the loser reads back the winner's record and continues under its `claimed_at`, converging on one byte-identical objective. A winner holding a different digest is refused before any lifecycle write;
- every newly created directory on the claim path has its *parent* flushed as the path is built, not only the file's own directory. On the first ever intake both `remote_engineering/` and `claims/` are new, and flushing only the innermost one would let a crash lose the claims directory while the lifecycle writes beneath the store survive -- reopening the window the claim exists to close.

Identifier shape (activation successor of `71c4ed6a`). The Director keeps choosing `request_id`, and it stays the objective/task id that outbound visibility promises; what is constrained is its shape, which is adapter-owned:

- `request_id` must be a readable slug, `^[a-z][a-z0-9]{0,15}(-[a-z0-9]{1,16}){1,7}$`: lowercase words of at most 16 characters joined by hyphens. Underscores, mixed case, dots and long high-entropy runs are refused, which excludes credential shapes in practice while admitting every id this system uses. The id is requester-chosen and reaches a durable claim, a receipt, a task id and the public projection, so constraining it is what keeps a secret out of all four without making the Director's own handle opaque;
- `target_branch` must equal `clive/objective/<request_id>` exactly, so the one ref the dispatcher publishes carries the slug and nothing else;
- both are refused without echoing the rejected value, like every other schema refusal.

Journal-safe adapter records and admitted id length (successor of `4c32bb3d`):

- claims and receipts live under the **adapter root**, `--adapter-root` (default `<store>/remote_engineering`, the location existing hosts already hold their records in). The kernel's journal refuses every verb while the store holds untracked files, and intake writes its claim before the canonical door, so adapter records that are untracked in the store would have every request refused with its id already claimed. **Chosen: refuse to start.** With a journalled store (anything but `--no-journal`), `poll` and `run` refuse to start, with one fixed message and before anything is claimed, when the adapter root is inside the store's git work tree and its `claims/` and `receipts/` directories themselves are not ignored by that work tree's rules. The directories are what is checked, never a sample record: git cannot re-include anything beneath an ignored directory, so only that covers every request id and every temporary file, and a rule matching only some file names (say `claims/*.json`) is refused. The supported configuration is an `--adapter-root` outside the store's work tree, which needs no ignore rule of any kind. An ignore rule also satisfies the check, but only a committed `.gitignore` goes with a clone: a host-local `.git/info/exclude` line satisfies it on that host only, and a new host without it refuses to start rather than burning ids. The message never repeats a path. `status` only reads and is not checked;
- the slug pattern alone admits up to 135 characters, but the id becomes the objective id (the canonical pattern caps it at 80), the task id, the claim and the receipt (120 each). The request schema therefore also caps `request_id` at 80 (`REQUEST_ID_MAX_LENGTH`), the shortest of those. The longest admitted id reaches a durable accepted receipt in `run` and in one-shot `poll`, and a longer one is refused by the schema before any claim, without being echoed.

Why a task is stuck (successor of `7914ed8d`). A blocked objective used to publish only `convergence limit: ... findings F-01, F-02 ... remain` or `result_refused: checks failed on <sha>: wording (exit 1)`, so the Director could not requeue it without the owner reading the host. Every request with a task now also carries three fields, each read from what the kernel (or, for a worker's report, the dispatcher's runtime) recorded and nothing inferred:

- `open_findings`: the material findings of the task's latest admitted independent verdict, across its revisions (a refused verdict decided nothing and is skipped; a READY verdict leaves the list empty). Each is `{finding_id, finding}`, plus `severity` when the verdict records one (the current `clive.review_result.v1` has no severity field, so it is absent today). At most `MAX_FINDINGS` (10) findings in verdict order, each `finding` cut to `MAX_FINDING_CHARS` (600). The text is read from the verdict payload the kernel stores beside its admission (`<store>/reviews/<task>/<attempt>/verdict.<n>.evidence.txt`);
- `failed_checks`: when the task's current (or, with none current, latest) attempt was cancelled `result_refused:`, each failing check of that attempt as `{name, exit_code, output_tail}`, at most `MAX_FAILED_CHECKS` (5) in the objective's check order. `output_tail` is stdout then stderr, cut to the last `MAX_CHECK_TAIL_LINES` (40) lines and then the last `MAX_CHECK_TAIL_CHARS` (4000) characters. It is read from the check evidence file whose path and sha256 the kernel recorded (`check-<name>` evidence); a file that is missing, larger than 256 KiB, or no longer matches its recorded digest is not published. The list is empty whenever the current attempt was not refused, so a retry that is running shows no stale failure;
- `worker_report`: for a task BLOCKED or OWNER_GATE because the worker itself reported `blocked` or `owner_decision_required`, the complete report text (`reason`, or `summary` when there is no reason, exactly as the dispatcher words the block), redacted and then cut to `MAX_WORKER_REPORT_CHARS` (4000); otherwise `null`. The kernel's blocker record holds only `worker reported blocked: <reason or summary>` truncated to 990 characters (`Dispatcher._block`), so the complete report is read from its authoritative runtime record: the current attempt's stream log, `<runtime-root>/logs/<attempt_id>.stream.jsonl`, whose final `result` event carries the worker's `structured_output` (only the last 1 MiB of the log is read). The loop passes the Dispatcher's `runtime_root` to `build_status`. The log's report is published only when its status matches the block and the kernel's blocker is its start, so it is the report the kernel recorded; when the log is missing, unreadable or does not match (and for the local `status` verb, which has no runtime root), the blocker's own text is published instead.

Redaction and bounds. Everything added passes through `redact_published` (`app/remote_engineering/errors.py`) *before* it is cut, so a cut can never leave half a secret that its shape would have matched: private key blocks (including one whose BEGIN line a tail cut off, or whose END it cut off), URL userinfo, known token shapes (`sk-`, `sk-ant-`, `ghp_`/`github_pat_`, `glpat-`, `xox?-`, `AKIA`, `AIza`, Shopify, Google OAuth, JWTs), `Bearer`/`Basic` credentials, the value of anything assigned to a secret-like name (`password=`, `"api_key": ...`, `Authorization: ...`; a quoted value goes whole, whitespace and escaped characters included, to the end of its line if unclosed) and any path into a credential location (`.ssh/`, `.gnupg/`, `.aws/`, `secrets/`, `credentials/`, `.netrc`, `.git-credentials`, `id_rsa`/`id_ed25519`, `*.pem`, `*.key`, `*.p12` ...) become `<redacted>`. A credential path needs no separator at all -- a bare `id_ed25519`, `.netrc` or a relative `client.pem` is redacted -- and `/` and `\` are both separators; a diagnostic suffix after the name (`id_ed25519:12`, `client.pem:7:3.`) does not hide it, and the whole word, suffix included, is redacted; only the ordinary words `secret(s)` and `credential(s)` count as a location solely beside a separator; it then applies the loop's existing `redact_supplied`. Unlike `redact_refusal` it keeps quoted literals, because here they are the substance (an assertion's operands), not an echo of rejected input. The published `blocker` and `stage_reason` pass through the same function, because for a worker-reported block they carry the same text as `worker_report`. The additions are deterministic functions of the records, so an unchanged task republishes byte-identical content, and each request grows by at most about 10 x 600 + 5 x 4000 + 4000 characters.

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
- a changed request id admits nothing else in the same snapshot, including a valid request that sorts before it;
- a transport failure's message, the published projection and the host's own log all omit git output;
- a malformed record is visible in the projection, keyed by source and digest, and survives a restart;
- non-finite and out-of-range loop timings are refused before any poll, tick or publication.
- a URL-bearing, option-like, over-long or revision-expression `base_ref` is refused before git is asked anything, and never echoed;
- a credential placed in an unknown key's name is absent from outcomes, loop result, receipts and published status;
- an untrusted or nested request filename is replaced by an opaque digest locator, while a conventional one is still reported as itself;
- a one-shot `poll` given a credential-bearing `--remote` prints neither the URL nor the credential.
- the claim is on disk before the canonical door is called at all;
- a crash between intake and the receipt recovers idempotently on the original bytes, with one task and the claimed `created_at`, even though the clock has moved;
- the same crash refuses changed or merely reformatted bytes for that id, and does not replace what was admitted;
- an interrupted id refuses its whole snapshot, so a fresh request beside it is not admitted either;
- a claim is write-once and carries pointers only.
- a non-slug or credential-shaped `request_id`, and a `target_branch` that is not exactly `clive/objective/<request_id>`, are refused, admit nothing and are never echoed;
- every id the Director and the runbooks actually use is still admitted;
- the first ever claim flushes each newly created directory's parent, and a later claim still flushes its own;
- two claims for the same bytes converge on one record and one `claimed_at`, and a loser holding a different digest is refused before any lifecycle write.
- a request is admitted end to end through a journalled store (a real git work tree, `journal=True`) to an accepted receipt, with no `.git/info/exclude` entry and no host git configuration, leaving the store's work tree clean;
- `poll` and `run` refuse to start, claiming nothing, while the adapter root would be unignored state in the store's work tree, including when ignore rules match only some record file names rather than the record directories;
- the longest admitted `request_id` reaches an accepted receipt through the journalled store in both `run` and one-shot `poll`, and an id one character longer, or at the old pattern's 135-character maximum, is refused before any claim and never echoed.
- a convergence-limited objective publishes its open material findings, at most 10, each at most 600 characters, with a planted token in a finding redacted;
- a refused result publishes each failing check's name, exit code and output tail, at most 40 lines and 4000 characters, with a planted token, private key, credential path and password in the check output redacted; a check evidence file changed after it was recorded is not published;
- a worker-reported block publishes the worker's report, with a planted token and credential path redacted from it and from `blocker`;
- a worker report longer than the blocker's 990 characters is published whole from the attempt's stream log through the loop, and one longer than 4000 characters is cut to 4000, with a planted token, `client.pem` and bare `id_ed25519` redacted;
- a credential path is redacted without a forward slash: bare `id_ed25519` and `.netrc`, relative `client.pem` and `gpt.key`, and backslash paths; the ordinary words `secret` and `credentials` are left alone;
- a multi-word quoted secret assignment (`password="correct horse battery staple"`, a single-quoted value with an escaped quote) and location-suffixed `id_ed25519:12` and `certs/client.pem:7:3.` are redacted whole from a worker report, a finding and a check's output tail, and none of the original values appears in the published status;
- a request whose task is not stuck publishes empty findings and checks and no worker report, and ordinary check output passes redaction unchanged.

## Definition of done

Repository-only candidate passes focused tests and independent GPT exact-SHA review. It is not deployed by this objective.

After acceptance, the owner may separately authorise one host-side activation of the polling adapter. Once activated, routine repository-only engineering should no longer require the owner to relay terminal commands.
