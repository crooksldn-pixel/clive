# CLAUDE OUTBOX — latest handoff only

## 2026-09-20T07:53:04Z — Bridge model verification round — VERIFIED, one mismatch to decide

**Inbox consumed:** yes. Blob SHA processed:
`2dc4abb4ef01e992a1797bd7d772ab6a3c2e606b` (`bridge/chatgpt-inbox.md`, heading "Bridge model
verification round — no implementation"). `git rev-parse HEAD:bridge/chatgpt-inbox.md` and
`git hash-object` of the working file both return that SHA, so the instructions I executed are
exactly the committed ones. These instructions are now recorded as executed and must not be run
again.

**This was a VERIFICATION round — not implementation, not review.** Nothing was modified,
created or deleted except this outbox. No commit, push, merge, install, restart, deploy, reset,
clean or stash. No change to production, account or global configuration, connectors,
credentials, the watcher or its systemd unit, privileges, or local Git configuration. No live
external call. Read-only everywhere else.

---

### What was asked

Confirm the watcher launches the intended model after the unattended pin was changed from
`claude-fable-5-1` to `claude-opus-5`. Report (1) which model I am running as, separating what I
can verify from what I am inferring; (2) reasoning effort, permission mode, allowed tools; (3) the
builder checkout path/branch/HEAD/status and whether the branch matches the unit's declared
`CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`, without switching; (4) the inbox SHA.

### 1. Model — VERIFIED as `claude-opus-5`

**Stated exactly: I am running as `claude-opus-5` (Claude Opus 5).**

**What I can actually verify from inside this session.** I traced my own process ancestry rather
than trusting configuration. My Bash tool's shell (`pid 1067275`) has as its direct parent
`pid 1066856`, whose command line is, verbatim:

```
claude --print --model claude-opus-5 --effort high --permission-mode acceptEdits \
       --allowed-tools Read,Edit,Write,Glob,Grep,Bash
```

Its parent is `pid 1066854`, `timeout --signal=TERM --kill-after=60 7200 claude --print --model
claude-opus-5 ...`. So the process I am executing inside was demonstrably invoked with `--model
claude-opus-5`. That is direct observation of the live invocation, not a reading of config that
might not have been applied.

Corroborating (weaker) signals: `CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5` is in my inherited
environment; the watcher unit declares `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`
(line 54 of `systemctl cat`), with no `claude-fable-5-1` anywhere in the launch path; and my own
runtime context self-reports Opus 5, exact ID `claude-opus-5`.

**What I am inferring, not verifying:** that the API actually *served* `claude-opus-5` on each
turn. I have no wire-level receipt from inside the session — I cannot read response headers or a
per-turn model echo, so a silent server-side alias or fallback would be invisible to me. What is
proven is the request side. Given the invocation, the environment and the self-report all agree
and the stale pin is gone, **the pin change has taken effect and this verification passes.**

### 2. Effort, permission mode, tools

Read from the same live command line (`pid 1066856`):

- **Reasoning effort:** `--effort high`
- **Permission mode:** `--permission-mode acceptEdits`
- **Allowed tools (CLI flag):** `Read, Edit, Write, Glob, Grep, Bash`
- **Timeout wrapper:** 7200 s (SIGTERM, SIGKILL after 60 s)

One caveat worth a reviewer's attention. The `--allowed-tools` flag lists those six, but the
session additionally exposes a large set of MCP connector tools (Shopify, Gmail, Google Drive,
Resend, Omnisend, Claude Docs) plus Agent/Task tooling, inherited from account-level connector
configuration rather than from the watcher's flag. **I used none of them** — this round was
read-only and no live external call was made — but the unattended bridge's tool surface is wider
than the `--allowed-tools` line alone suggests. Flagged, not acted on. Several further MCP servers
are configured but unauthenticated or failed to connect; none were touched.

### 3. Builder checkout — BRANCH MISMATCH (reported, not corrected)

| | |
|---|---|
| Path | `/opt/crooks-builder` |
| Branch actually checked out | `claude/builder-environment-repair` |
| HEAD | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| `git status` | clean — nothing to commit, nothing modified, nothing untracked |
| Unit declares | `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder` (unit line 43) |
| **Match?** | **No.** |

**The branch does not match the unit declaration.** Detail, so this is not misread as damage:
`claude/bridge-builder` exists at `9a27bc4` and is a strict ancestor of HEAD
(`git merge-base --is-ancestor claude/bridge-builder HEAD` → true). The checked-out branch is
**2 commits ahead** of it:

```
295e483 The BLOCKED half of BE-04, unblocked and then actually run
326c150 The four findings that rejected the builder environment, each repaired against its reproduction
9a27bc4 The builder environment, and the browser gate it turns back on   <-- claude/bridge-builder
```

So this is a fast-forwardable divergence — work done on a topic branch off `bridge-builder` that
`bridge-builder` was never advanced to — not a conflicting or unrelated branch. Per the inbox I
did **not** switch, merge or move any ref.

A second worktree exists and was left untouched:
`/opt/crooks-builder/.worktrees/harness-hooks-experiment` at `2c2b0cc [claude/harness-hooks-experiment]`.

### 4. Inbox SHA

`2dc4abb4ef01e992a1797bd7d772ab6a3c2e606b` — consumed and recorded above.

---

### Production branch HEAD

Read-only inspection of `/opt/crooks-os/crooks-assistant` (not edited, not switched, not reset):

- Branch: `claude/linux-prod-migration-production`
- HEAD: `1cf3a0f3361b79f9de208d80f501543c53c244b5` — "Linux production migration (Phases 1-4) for review"
- `git status`: clean.

### Files changed

**One: `bridge/claude-outbox.md` (this file), replaced in full.** Nothing else created, modified,
deleted, staged, committed or pushed in any of the three checkouts. Builder and production trees
were clean before this round and are clean after it; `/opt/crooks-ai-bridge` shows only this
outbox as modified, so the watcher's publish precondition is satisfied.

### Test results

None run. Verification round with no code change; running the suite would have exceeded the
inbox's scope.

### Service and server state

- `crooks-assistant.service` — active (running), up since 2026-09-19 06:30:10 UTC. Not restarted.
- `crooks-bridge-watcher.service` — active (running). Not touched.
- FastAPI listener: `127.0.0.1:8000` only (`ss -ltn`) — loopback-bound, port 8000 not publicly exposed.
- `CROOKS_WRITES_ENABLED=false`, `CROOKS_WRITES_LOCAL_OWNER=false` in production `.env` — unchanged.
- `/root/.claude` writable: yes.
- No live Shopify, Gmail or ElevenLabs call; no external mutation; proposal/action/verification
  safety semantics unchanged; V2 not begun; UI not redesigned; Mac deployment and rollback path
  preserved.

### Errors

None. Every command succeeded. Nothing was blocked by my permission layer.

### Decisions / questions needing review

1. **Builder branch vs. unit declaration.** The watcher declares `claude/bridge-builder`; the
   builder worktree sits on `claude/builder-environment-repair`, 2 commits ahead. Either the unit's
   declared branch is updated, or `claude/bridge-builder` is fast-forwarded to `295e483`, or future
   rounds are told to check out `bridge-builder` explicitly. Note that resetting the worktree to
   `bridge-builder` would strand the two builder-environment repair commits, so this should not be
   done reflexively.
2. **Unattended MCP tool surface** (§2): the bridge session carries live account connectors well
   beyond the six `--allowed-tools` entries. Worth an explicit decision on whether the unattended
   builder should have them at all.

### Exact proposed next step

**Reply in the next inbox naming which branch reconciliation you want — (a) change
`Environment=CROOKS_BRIDGE_BUILDER_BRANCH` in the watcher unit to
`claude/builder-environment-repair`, or (b) fast-forward `claude/bridge-builder` to `295e483` and
leave the unit as-is.** Both touch state I am forbidden to change unattended (the systemd unit in
case (a); a branch ref plus a probable watcher restart in either), so I am **stopping here and
waiting for the owner's decision** rather than picking one. Nothing is left half-done: both trees
are clean, both services are running, and no work is queued.

---

*No API key, password, OAuth token, cookie, private key or other secret value appears in this
handoff. Secrets are referred to by name only.*
