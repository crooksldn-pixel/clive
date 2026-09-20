# CHATGPT INBOX

## Bounded repair of F-6 on harness candidate `fe96bb661140089647c3e6cb90a269c869a076fa`

Read fresh canonical product memory from `claude/product-memory-foundation` and the latest outbox first. The independent review at 2026-09-19T23:55Z returned `REJECT — REPAIR REQUIRED` with exactly one new bounded High finding, F-6. This round is implementation only; do not self-certify acceptance.

### Exact starting identity
- candidate branch: `claude/harness-hooks-experiment`
- current rejected head: `fe96bb661140089647c3e6cb90a269c869a076fa`
- its parent: `d7911b24979be2306749b7333ec60edc28cba857`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- production must remain exactly `1cf3a0f3361b79f9de208d80f501543c53c244b5`

Verify the remote branch still points exactly to `fe96bb6…` and the candidate worktree is clean before editing. Use explicit branch fetches if needed; the known stale Builder refspec remains owner-held and must not be changed.

### Repair scope — F-6 only
The review proved that redirect operators glued to a preceding word evade the write checks, and read-only base commands with those redirects can write protected targets while the guard returns ALLOW. Exact demonstrated examples include:

- `echo pwned>/opt/crooks-os/app/main.py`
- `printf x>/etc/crooks-os/x`
- `echo x>/root/.bashrc`
- `cd /opt/crooks-os && echo pwned>app/main.py`
- `cd /opt/crooks-os && printf x>>app/routes.py`
- `cd /opt/crooks-os && cat /tmp/x>config/settings.py`
- `cd /opt/crooks-os && echo x>{app,config}/main.py`
- hook cwd `/opt/crooks-os/app`: `echo pwned>main.py`

Observed: ALLOW. Required: DENY (`PROTECTED-PATH`, or fail-closed `PROTECTED-CWD` where exact resolution is impossible).

Root cause from independent review: redirect target collection only recognises an operator at the start of a shlex token, while Bash treats `>`/`>>`/`>|`/`&>`/`&>>` as metacharacters even when glued after ordinary text. In addition, protected-target/write checking is incorrectly coupled to the base command being classified non-read-only. A command such as `echo` or `cat` becomes a write when it has an output redirect.

Implement the smallest auditable fix at the parser/write-target layer. Do not paper over only the listed strings. Redirect target extraction must correctly identify unquoted output redirect operators even when glued after preceding text and route their RHS through the same protected-target resolution used by spaced redirects. Output redirects must be treated as writes independently of whether the base command is otherwise read-only. Preserve existing heredoc/here-string/fd redirect semantics and fail closed when parsing cannot be proven safe.

### Required regression evidence
Add failing-before/passing-after tests covering at least:
- operators `>`, `>>`, `>|`, `&>`, `&>>` glued after a word;
- base commands `echo`, `printf`, and `cat`;
- relative protected destinations after `cd /opt/crooks-os`;
- absolute protected destinations under `/opt/crooks-os`, `/etc`, and `/root`;
- hook cwd already inside a protected directory;
- brace/glob/path traversal forms where applicable;
- positive controls that remain allowed: `echo x>out.txt`, `cd /tmp && echo x>y`, `echo done>/tmp/log` and equivalent benign glued redirects.

Also add interaction tests sufficient to prove this parser change does not reopen F-2…F-5 or earlier redirect/heredoc/here-string behaviour. Use new tests rather than weakening old assertions.

### Verification and publication
After repair, run:
1. the new F-6 regression tests;
2. prior harness repair files plus guard/gitleaks/roster/layout/dev-environment targeted tests;
3. full offline suite (record parallel/environmental failures accurately and re-run suspicious unrelated failures serially; do not falsely claim them fixed);
4. Ruff;
5. pinned redacted gitleaks over `fe96bb6…<new-candidate>`.

Require clean candidate worktree, exact remote SHA evidence and an exact one-commit publication on top of `fe96bb6…`. Replace only `bridge/claude-outbox.md` with exact identity, diff, tests/scans, invariant checks, and the new candidate SHA. STOP. The new candidate requires a fresh independent adversarial review; implementation is not acceptance.

### Hard boundaries
No merge/deploy/install/restart; no production writes; no `.claude/` activation; no `/root/.claude`, account/global Claude, MCP, connector, identity, credential or secret changes; no watcher/systemd/local Git-config changes; no reset/clean/stash; no external spend; no scope expansion. D-19 remains empirically unproven. Do not touch the owner-side `.git/info/exclude` workaround.