# CHATGPT INBOX

## Bridge model verification round — no implementation

This round exists only to confirm the watcher launches the intended model after the unattended
pin was changed from `claude-fable-5-1` to `claude-opus-5`. It is a verification round, not
implementation, and not a review.

Do not modify, create or delete any file except `bridge/claude-outbox.md`. Do not commit, push,
merge, install, restart, deploy, reset, clean or stash anything. Do not change production,
account or global configuration, connectors, credentials, the watcher or its systemd unit,
privileges, or local Git configuration. No live external calls. Read-only everywhere else.

Report the following in the outbox:

1. Which model you are running as, stated exactly. Say how you determined it, and separate what
   you can actually verify from your runtime or session from what you are inferring. If you
   cannot verify it, say so plainly rather than guessing — an honest "I cannot confirm this from
   inside the session" is the correct answer if that is the case.
2. The reasoning effort and permission mode in force, and which tools you were allowed.
3. The builder checkout you are actually in: path, branch, HEAD and `git status`. The watcher
   unit declares `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`. State whether the branch
   you are actually on matches that. Do not switch branches either way — just report it.
4. The inbox blob SHA you consumed.

Keep it brief wherever the standing handoff format allows. Replace only
`bridge/claude-outbox.md`, then stop.
