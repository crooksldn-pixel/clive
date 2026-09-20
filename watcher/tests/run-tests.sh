#!/usr/bin/env bash
#
# Tests for the CROOKS AI bridge watcher.
#
# Everything the watcher touches is replaced by a stub on PATH — gh, claude and git — and pointed
# at temporary directories, so a test run reaches no network, starts no Claude, publishes nothing,
# and cannot touch /var/lib, /run, the builder worktree, the bridge worktree or production.
#
#   ./tests/run-tests.sh          run them all
#   ./tests/run-tests.sh -v       and show the watcher's own output
#
# What these are actually for: the watcher decides, unattended, whether a set of instructions has
# been carried out. Every test below is a way that decision could be wrong — running twice, running
# never, running two at once, or marking work done that nobody was told about.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="$HERE/../bin/crooks-bridge-watcher"
VERBOSE="${1:-}"

PASS=0; FAIL=0; FAILED_NAMES=()

# --------------------------------------------------------------------------- harness

setup() {
    SANDBOX="$(mktemp -d)"
    STUB="$SANDBOX/stub"; BIN="$SANDBOX/bin"; STATE="$SANDBOX/state"
    BRIDGE="$SANDBOX/bridge"; BUILDER="$SANDBOX/builder"; PRODUCTION="$SANDBOX/production"
    mkdir -p "$STUB" "$BIN" "$STATE" "$BRIDGE" "$BUILDER" "$PRODUCTION"
    LOCK="$SANDBOX/watcher.lock"

    printf 'inbox-A\n'  > "$STUB/inbox_sha"
    printf 'outbox-1\n' > "$STUB/outbox_sha"
    printf '0\n'        > "$STUB/claude_exit"
    # What Claude leaves behind in the bridge worktree: the one file it is allowed to write.
    printf ' M bridge/claude-outbox.md\n' > "$STUB/bridge_status"
    : > "$STUB/claude_runs"; : > "$STUB/claude_args"; : > "$STUB/claude_stdin"; : > "$STUB/git_ops"

    cat > "$BIN/gh" <<'GH'
#!/usr/bin/env bash
[ -f "$STUB/gh_fail" ] && exit 1
for arg in "$@"; do
  case "$arg" in
    *chatgpt-inbox.md*)  tr -d '\n' < "$STUB/inbox_sha";  echo; exit 0 ;;
    *claude-outbox.md*)  tr -d '\n' < "$STUB/outbox_sha"; echo; exit 0 ;;
  esac
done
exit 1
GH

    # claude: records that it ran, with what, and CRUCIALLY from which directory. It never
    # commits or pushes anything — that is the point of the new design, and test
    # `claude never publishes anything itself` depends on this stub staying innocent.
    cat > "$BIN/claude" <<'CLAUDE'
#!/usr/bin/env bash
date +%s%N >> "$STUB/claude_runs"
printf '%s\n' "$*" >> "$STUB/claude_args"
cat > "$STUB/claude_stdin"
pwd -P > "$STUB/claude_cwd"
[ -f "$STUB/claude_sleep" ] && sleep "$(cat "$STUB/claude_sleep")"
[ -f "$STUB/claude_new_inbox" ] && cat "$STUB/claude_new_inbox" > "$STUB/inbox_sha"
exit "$(cat "$STUB/claude_exit")"
CLAUDE

    # git: answers per working directory, and records every operation so a test can assert
    # exactly what was staged, committed and pushed.
    cat > "$BIN/git" <<'GIT'
#!/usr/bin/env bash
dir=""; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -C) dir="$2"; shift 2 ;;
    -c) shift 2 ;;
    *)  args+=("$1"); shift ;;
  esac
done
sub="${args[0]:-}"
case "$sub" in
  status)
    if [ "$dir" = "$BRIDGE_T" ]; then cat "$STUB/bridge_status" 2>/dev/null
    else [ -f "$STUB/dirty" ] && printf ' M some/file\n?? another/file\n'; fi ;;
  add)    printf 'add %s :: %s\n' "$dir" "${args[*]}" >> "$STUB/git_ops" ;;
  diff)   if [ -f "$STUB/staged" ]; then cat "$STUB/staged"; else printf 'bridge/claude-outbox.md\n'; fi ;;
  commit) printf 'commit %s :: %s\n' "$dir" "${args[*]}" >> "$STUB/git_ops" ;;
  push)
    printf 'push %s :: %s\n' "$dir" "${args[*]}" >> "$STUB/git_ops"
    [ -f "$STUB/push_fail" ] && exit 1
    [ -f "$STUB/push_noop" ] || printf 'outbox-%s\n' "$(date +%s%N)" > "$STUB/outbox_sha" ;;
  rev-parse)
    if [ -f "$STUB/linked_worktree" ]; then printf '%s/.git/worktrees/builder\n' "$PRODUCTION_T"
    else printf '%s/.git\n' "$dir"; fi ;;
  fetch|merge) : ;;
esac
exit 0
GIT

    chmod +x "$BIN/gh" "$BIN/claude" "$BIN/git"
    export STUB
}

teardown() { [ -n "${SANDBOX:-}" ] && rm -rf "$SANDBOX"; }

watch() {
    PATH="$BIN:$PATH" STUB="$STUB" BRIDGE_T="$BRIDGE" PRODUCTION_T="$PRODUCTION" \
    CROOKS_BRIDGE_STATE_DIR="$STATE" \
    CROOKS_BRIDGE_LOCK="$LOCK" \
    CROOKS_BRIDGE_WORKTREE="$BRIDGE" \
    CROOKS_BRIDGE_WORKDIR="${WORKDIR_OVERRIDE:-$BUILDER}" \
    CROOKS_BRIDGE_PRODUCTION_DIR="$PRODUCTION" \
    CROOKS_BRIDGE_PRODUCTION_REPO_ROOT="${PROD_ROOT_OVERRIDE:-$PRODUCTION}" \
    CROOKS_BRIDGE_POLL_S=1 \
    CROOKS_BRIDGE_BACKOFF_BASE_S=60 \
    CROOKS_BRIDGE_BACKOFF_MAX_S=900 \
    CROOKS_BRIDGE_CLAUDE_TIMEOUT_S=30 \
    CROOKS_BRIDGE_CLAUDE_LISTER="${LISTER:-true}" \
    CROOKS_BRIDGE_ALLOW_DIRTY="${ALLOW_DIRTY:-0}" \
        bash "$WATCHER" "$@" 2>&1
}

runs()     { wc -l < "$STUB/claude_runs" | tr -d ' '; }
recorded() { [ -f "$STATE/last-inbox-sha" ] && tr -d '\n' < "$STATE/last-inbox-sha" || printf ''; }
failures() { [ -f "$STATE/failures" ] && tr -d '\n' < "$STATE/failures" || printf ''; }
ops()      { cat "$STUB/git_ops" 2>/dev/null; }

check() {
    local name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS+1)); printf '  ok    %s\n' "$name"
    else
        FAIL=$((FAIL+1)); FAILED_NAMES+=("$name")
        printf '  FAIL  %s\n         expected: %s\n         actual:   %s\n' "$name" "$expected" "$actual"
    fi
}

contains() {
    local name="$1" haystack="$2" needle="$3"
    case "$haystack" in
        *"$needle"*) PASS=$((PASS+1)); printf '  ok    %s\n' "$name" ;;
        *) FAIL=$((FAIL+1)); FAILED_NAMES+=("$name")
           printf '  FAIL  %s\n         looked for: %s\n' "$name" "$needle" ;;
    esac
}

lacks() {
    local name="$1" haystack="$2" needle="$3"
    case "$haystack" in
        *"$needle"*) FAIL=$((FAIL+1)); FAILED_NAMES+=("$name")
           printf '  FAIL  %s\n         unexpectedly found: %s\n' "$name" "$needle" ;;
        *) PASS=$((PASS+1)); printf '  ok    %s\n' "$name" ;;
    esac
}

# --------------------------------------------------------------- triggering

t_unchanged_inbox_never_starts_claude() {
    printf 'inbox-A\n' > "$STATE/last-inbox-sha"
    watch --once >/dev/null
    check "an unchanged inbox starts nothing" "0" "$(runs)"
    check "  and the recorded SHA is left alone" "inbox-A" "$(recorded)"
}

t_a_changed_inbox_runs_claude_once() {
    watch --once >/dev/null
    check "a changed inbox runs Claude exactly once" "1" "$(runs)"
    check "  and the processed SHA is recorded" "inbox-A" "$(recorded)"
    check "  and the failure count is clear" "0" "$(failures)"
}

t_the_same_inbox_is_not_processed_twice() {
    watch --once >/dev/null; watch --once >/dev/null; watch --once >/dev/null
    check "the same inbox is processed once, not three times" "1" "$(runs)"
}

t_the_outbox_moving_does_not_retrigger() {
    watch --once >/dev/null
    printf 'outbox-moved\n' > "$STUB/outbox_sha"
    watch --once >/dev/null
    check "an outbox push does not retrigger the watcher" "1" "$(runs)"
}

t_github_unreachable_starts_nothing() {
    touch "$STUB/gh_fail"
    watch --once >/dev/null
    check "an unreadable GitHub starts no Claude" "0" "$(runs)"
    check "  records nothing" "" "$(recorded)"
    check "  and backs off" "60" "$(cat "$STATE/.next-delay")"
}

t_seed_records_without_running_claude() {
    watch seed >/dev/null
    check "seed records the current inbox" "inbox-A" "$(recorded)"
    check "  without running Claude" "0" "$(runs)"
    watch --once >/dev/null
    check "  so a seeded watcher waits for a real change" "0" "$(runs)"
}

# --------------------------------------------------------------- where Claude runs

t_claude_runs_in_the_builder_worktree() {
    watch --once >/dev/null
    check "Claude's working directory is the builder worktree" \
        "$(cd "$BUILDER" && pwd -P)" "$(cat "$STUB/claude_cwd")"
}

t_the_production_checkout_is_never_the_target() {
    # Pointed at production by configuration — which is exactly the mistake the guard exists for.
    local out; out="$(WORKDIR_OVERRIDE="$PRODUCTION" watch --once)"
    check "aiming the watcher at production starts no Claude" "0" "$(runs)"
    check "  and records nothing" "" "$(recorded)"
    contains "  and it says why" "$out" "inside the production repository"
}

t_a_missing_builder_worktree_refuses() {
    local out; out="$(WORKDIR_OVERRIDE="$SANDBOX/not-there" watch --once)"
    check "a missing builder worktree starts no Claude" "0" "$(runs)"
    contains "  and prints the one command that creates it" "$out" "git clone --no-hardlinks"
}

t_a_dirty_builder_refuses_and_discards_nothing() {
    touch "$STUB/dirty"
    local out; out="$(watch --once)"
    check "a dirty builder worktree starts no Claude" "0" "$(runs)"
    check "  and the inbox is left unprocessed" "" "$(recorded)"
    contains "  and it explains itself" "$out" "REFUSING"
    lacks "  and nothing was reset, cleaned or checked out" "$(ops)" "reset"
}

t_a_dirty_builder_can_be_overridden_deliberately() {
    touch "$STUB/dirty"
    ALLOW_DIRTY=1 watch --once >/dev/null
    check "a deliberate override runs anyway" "1" "$(runs)"
    check "  and records the inbox" "inbox-A" "$(recorded)"
}

# --------------------------------------------------------------- one at a time

t_a_held_lock_suppresses_a_second_claude() {
    flock -x "$LOCK" -c 'sleep 2' &
    local holder=$!
    sleep 0.3
    watch --once >/dev/null
    check "no second Claude starts while one holds the lock" "0" "$(runs)"
    check "  and nothing is recorded as processed" "" "$(recorded)"
    wait "$holder" 2>/dev/null
    watch --once >/dev/null
    check "  the inbox is picked up once the lock frees" "1" "$(runs)"
}

t_another_claude_in_the_tree_refuses_to_start() {
    ( cd "$BUILDER" && exec sleep 5 ) &
    local intruder=$!
    printf '#!/usr/bin/env bash\necho %s\n' "$intruder" > "$BIN/fake-lister"; chmod +x "$BIN/fake-lister"
    local out; out="$(LISTER="$BIN/fake-lister" watch --once)"
    check "another Claude in the tree starts no second one" "0" "$(runs)"
    check "  and the inbox is left unprocessed" "" "$(recorded)"
    contains "  and it names the other process" "$out" "another Claude is already working"
    kill "$intruder" 2>/dev/null; wait "$intruder" 2>/dev/null
    watch --once >/dev/null
    check "  and the run proceeds once that process is gone" "1" "$(runs)"
}

t_a_claude_elsewhere_on_the_box_is_not_confused_for_one_here() {
    ( cd / && exec sleep 5 ) &
    local elsewhere=$!
    printf '#!/usr/bin/env bash\necho %s\n' "$elsewhere" > "$BIN/fake-lister"; chmod +x "$BIN/fake-lister"
    LISTER="$BIN/fake-lister" watch --once >/dev/null
    check "a Claude outside the tree does not block the run" "1" "$(runs)"
    kill "$elsewhere" 2>/dev/null; wait "$elsewhere" 2>/dev/null
}

t_a_newer_inbox_mid_run_is_taken_next_cycle() {
    printf 'inbox-B\n' > "$STUB/claude_new_inbox"
    watch --once >/dev/null
    check "the SHA recorded is the one actually handed to Claude" "inbox-A" "$(recorded)"
    rm -f "$STUB/claude_new_inbox"
    watch --once >/dev/null
    check "  and the newer inbox is processed on the next cycle" "2" "$(runs)"
    check "  leaving the newer SHA recorded" "inbox-B" "$(recorded)"
}

# --------------------------------------------------------------- publication is the watcher's

t_claude_never_publishes_anything_itself() {
    # The stub Claude cannot commit or push — it only writes. The round must still complete,
    # which is the whole point: publication no longer depends on Claude's permission layer.
    watch --once >/dev/null
    check "a Claude that never pushes still completes the round" "inbox-A" "$(recorded)"
    contains "  because the WATCHER pushed" "$(ops)" "push $BRIDGE"
    contains "  and the prompt tells Claude not to" \
        "$(tr '\n' ' ' < "$STUB/claude_stdin")" "Do NOT run git add, git commit or git push"
}

t_the_watcher_publishes_exactly_the_outbox() {
    watch --once >/dev/null
    local o; o="$(ops)"
    contains "exactly bridge/claude-outbox.md is staged" "$o" "add $BRIDGE :: add -- bridge/claude-outbox.md"
    contains "  a commit is made"                        "$o" "commit $BRIDGE"
    contains "  and only the bridge branch is pushed"    "$o" "push $BRIDGE :: push origin crooks-ai-bridge"
    lacks "  no other branch is pushed"                  "$o" "bridge-builder"
    lacks "  and nothing is pushed with --all"           "$o" "--all"
}

t_unexpected_bridge_changes_refuse_to_publish() {
    printf ' M bridge/claude-outbox.md\n M bridge/chatgpt-inbox.md\n' > "$STUB/bridge_status"
    local out; out="$(watch --once)"
    check "an edited inbox in the bridge worktree is not published" "" "$(recorded)"
    contains "  and it refuses out loud" "$out" "unexpected changes in the bridge worktree"
    contains "  naming the offending path" "$out" "bridge/chatgpt-inbox.md"
    lacks "  nothing was committed" "$(ops)" "commit"
    lacks "  nothing was pushed"    "$(ops)" "push"
    check "  and it counts as a failure" "1" "$(failures)"
}

t_application_code_cannot_ride_the_bridge_branch() {
    printf ' M bridge/claude-outbox.md\n M crooks-assistant/app/main.py\n' > "$STUB/bridge_status"
    watch --once >/dev/null
    check "app code in the bridge worktree is never published" "" "$(recorded)"
    lacks "  nothing was pushed" "$(ops)" "push"
}

t_a_run_that_wrote_no_outbox_is_a_failure() {
    : > "$STUB/bridge_status"
    local out; out="$(watch --once)"
    check "exit 0 with no outbox written is not success" "" "$(recorded)"
    contains "  and it says so" "$out" "wrote no outbox"
    check "  and it counts as a failure" "1" "$(failures)"
}

t_a_failed_push_does_not_mark_the_inbox_processed() {
    touch "$STUB/push_fail"
    local out; out="$(watch --once)"
    check "a failed push leaves the inbox unprocessed" "" "$(recorded)"
    contains "  and says the outbox is committed but unpublished" "$out" "committed locally but not published"
    check "  and it counts as a failure" "1" "$(failures)"
    rm -f "$STUB/push_fail"
    watch --once >/dev/null
    check "  and the next cycle retries and succeeds" "inbox-A" "$(recorded)"
}

t_a_push_that_changed_nothing_is_not_success() {
    # The push reported success but the remote blob is identical: nobody was told anything.
    touch "$STUB/push_noop"
    local out; out="$(watch --once)"
    check "a push that moved no blob is not success" "" "$(recorded)"
    contains "  and it says which blob did not change" "$out" "remote outbox blob did not change"
}

t_a_successful_watcher_push_marks_it_processed() {
    watch --once >/dev/null
    check "a published outbox marks the inbox processed" "inbox-A" "$(recorded)"
    check "  and clears the failure count" "0" "$(failures)"
}

t_staging_more_than_the_outbox_refuses_to_commit() {
    printf 'bridge/claude-outbox.md\nbridge/chatgpt-inbox.md\n' > "$STUB/staged"
    local out; out="$(watch --once)"
    check "a staged set wider than the outbox is not committed" "" "$(recorded)"
    contains "  and it refuses explicitly" "$out" "staged set is not exactly"
    lacks "  nothing was committed" "$(ops)" "commit"
}

# --------------------------------------------------------------- failure handling

t_a_failed_run_is_not_recorded() {
    printf '1\n' > "$STUB/claude_exit"
    watch --once >/dev/null
    check "a failed Claude does not mark the inbox processed" "" "$(recorded)"
    check "  and the failure is counted" "1" "$(failures)"
    lacks "  and nothing was published" "$(ops)" "push"
}

t_a_failed_run_is_retried_next_cycle() {
    printf '1\n' > "$STUB/claude_exit"
    watch --once >/dev/null
    printf '0\n' > "$STUB/claude_exit"
    watch --once >/dev/null
    check "a failed inbox is retried and then recorded" "inbox-A" "$(recorded)"
    check "  over two Claude runs" "2" "$(runs)"
    check "  and the failure count resets on success" "0" "$(failures)"
}

t_backoff_grows_then_caps() {
    printf '1\n' > "$STUB/claude_exit"
    local first second third
    watch --once >/dev/null; first="$(cat "$STATE/.next-delay")"
    watch --once >/dev/null; second="$(cat "$STATE/.next-delay")"
    watch --once >/dev/null; third="$(cat "$STATE/.next-delay")"
    check "backoff after 1 failure is 60s" "60" "$first"
    check "backoff after 2 failures is 120s" "120" "$second"
    check "backoff after 3 failures is 240s" "240" "$third"
    check "backoff is capped, never unbounded" "900" \
        "$(bash -c 'source <(sed -n "/^backoff_for()/,/^}/p" '"$WATCHER"'); BACKOFF_BASE_S=60; BACKOFF_MAX_S=900; POLL_INTERVAL=30; backoff_for 9')"
}

# --------------------------------------------------------------- the contract with Claude

t_anything_inside_the_production_repo_is_refused() {
    # Not just the app subdirectory. The mistake wears many paths; the guard checks the root.
    mkdir -p "$PRODUCTION/some/nested/dir"
    local out; out="$(WORKDIR_OVERRIDE="$PRODUCTION/some/nested/dir" watch --once)"
    check "a path nested inside the production repo is refused" "0" "$(runs)"
    contains "  and it says it is inside production" "$out" "inside the production repository"
    check "  and records nothing" "" "$(recorded)"
}

t_a_linked_worktree_of_production_is_refused() {
    # A linked worktree keeps its metadata in production's .git, so writing to it writes into
    # production — the isolation hole that standalone clones exist to close.
    touch "$STUB/linked_worktree"
    local out; out="$(watch --once)"
    check "a linked worktree of production starts no Claude" "0" "$(runs)"
    contains "  and it names the problem" "$out" "LINKED WORKTREE"
    contains "  and gives the clone command" "$out" "git clone --no-hardlinks"
    check "  and records nothing" "" "$(recorded)"
}

t_a_standalone_clone_is_accepted() {
    # The converse, so the guard cannot pass by refusing everything.
    rm -f "$STUB/linked_worktree"
    watch --once >/dev/null
    check "a standalone builder clone is accepted" "1" "$(runs)"
}

# --------------------------------------------------------------- packaging

t_staging_installs_exactly_the_runtime_payload() {
    local rt="$SANDBOX/runtime"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    check "the watcher is staged"        "1" "$(test -f "$rt/bin/crooks-bridge-watcher" && echo 1 || echo 0)"
    check "  the unit is staged"         "1" "$(test -f "$rt/systemd/crooks-bridge-watcher.service" && echo 1 || echo 0)"
    check "  a manifest is written"      "1" "$(test -f "$rt/MANIFEST.sha256" && echo 1 || echo 0)"
    check "  the watcher is executable"  "755" "$(stat -c '%a' "$rt/bin/crooks-bridge-watcher")"
    check "  the unit is not executable" "644" "$(stat -c '%a' "$rt/systemd/crooks-bridge-watcher.service")"
    check "  tests are NOT shipped into runtime" "0" "$(test -e "$rt/tests" && echo 1 || echo 0)"
}

t_the_staged_runtime_is_byte_identical_to_source() {
    local rt="$SANDBOX/runtime"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    check "the staged watcher is byte-identical to source" "same" \
        "$(cmp -s "$HERE/../bin/crooks-bridge-watcher" "$rt/bin/crooks-bridge-watcher" && echo same || echo DIFFERENT)"
    check "  and so is the unit" "same" \
        "$(cmp -s "$HERE/../systemd/crooks-bridge-watcher.service" "$rt/systemd/crooks-bridge-watcher.service" && echo same || echo DIFFERENT)"
}

t_staging_is_safe_to_repeat() {
    local rt="$SANDBOX/runtime" first second
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    first="$(sha256sum "$rt/bin/crooks-bridge-watcher" | cut -d' ' -f1)"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    local rc=$?
    second="$(sha256sum "$rt/bin/crooks-bridge-watcher" | cut -d' ' -f1)"
    check "installing twice is not an error" "0" "$rc"
    check "  and leaves the same bytes"      "$first" "$second"
}

t_verify_detects_a_runtime_that_drifted_from_source() {
    # The whole point: "approve commit X" must never install something else.
    local rt="$SANDBOX/runtime" unit="$SANDBOX/installed-unit"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    cp "$HERE/../systemd/crooks-bridge-watcher.service" "$unit"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" CROOKS_BRIDGE_UNIT_DST="$unit" bash "$HERE/../install.sh" verify >/dev/null 2>&1
    check "a freshly staged runtime verifies" "0" "$?"

    printf '\n# tampered\n' >> "$rt/bin/crooks-bridge-watcher"
    local out; out="$(CROOKS_BRIDGE_RUNTIME_DIR="$rt" CROOKS_BRIDGE_UNIT_DST="$unit" bash "$HERE/../install.sh" verify 2>&1)"
    local rc=$?
    check "  a drifted runtime fails verification" "1" "$rc"
    contains "  and names the file that differs" "$out" "DIFFERS from source"
}

t_upgrade_can_verify_new_payload_before_replacing_old_unit() {
    # A legitimate upgrade necessarily has an OLD installed unit while the NEW runtime is staged.
    # That expected mismatch must not block the installer before it gets a chance to replace it.
    local rt="$SANDBOX/runtime" unit="$SANDBOX/installed-unit" out rc
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    printf '# old installed unit\n' > "$unit"

    CROOKS_BRIDGE_RUNTIME_DIR="$rt" CROOKS_BRIDGE_UNIT_DST="$unit"         bash "$HERE/../install.sh" verify --runtime-only >/dev/null 2>&1
    check "a staged upgrade payload verifies before unit replacement" "0" "$?"

    out="$(CROOKS_BRIDGE_RUNTIME_DIR="$rt" CROOKS_BRIDGE_UNIT_DST="$unit" bash "$HERE/../install.sh" verify 2>&1)"
    rc=$?
    check "  full verification still rejects the old installed unit" "1" "$rc"
    contains "  and names the expected unit drift" "$out" "installed unit DIFFERS from runtime"

    cp "$HERE/../systemd/crooks-bridge-watcher.service" "$unit"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" CROOKS_BRIDGE_UNIT_DST="$unit"         bash "$HERE/../install.sh" verify >/dev/null 2>&1
    check "  full verification passes after unit replacement" "0" "$?"
}

t_the_manifest_records_where_it_came_from() {
    local rt="$SANDBOX/runtime"
    CROOKS_BRIDGE_RUNTIME_DIR="$rt" bash "$HERE/../install.sh" stage >/dev/null 2>&1
    contains "the manifest records the source directory" "$(cat "$rt/MANIFEST.sha256")" "installed-from:"
    contains "  and the source revision"                 "$(cat "$rt/MANIFEST.sha256")" "source-revision:"
    contains "  and a checksum per file"                 "$(cat "$rt/MANIFEST.sha256")" "bin/crooks-bridge-watcher"
}

t_the_unit_does_not_grant_write_access_to_production() {
    local unit; unit="$(cat "$HERE/../systemd/crooks-bridge-watcher.service")"
    lacks "the unit does not make /opt/crooks-os writable" "$unit" "ReadWritePaths=/opt/crooks-os
"
    contains "  the builder clone is writable"  "$unit" "ReadWritePaths=/opt/crooks-builder"
    contains "  the bridge clone is writable"   "$unit" "ReadWritePaths=/opt/crooks-ai-bridge"
    contains "  production is explicitly read-only" "$unit" "ReadOnlyPaths=/opt/crooks-os"
    contains "  and the filesystem is strict by default" "$unit" "ProtectSystem=strict"
    contains "  the unit pins Opus 5" "$unit" "Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5"
    contains "  the unit pins high effort" "$unit" "Environment=CROOKS_BRIDGE_CLAUDE_EFFORT=high"
}

t_the_prompt_carries_the_safety_contract() {
    watch --once >/dev/null
    local args prompt
    args="$(tr '\n' ' ' < "$STUB/claude_args" | tr -s ' ' | tr '[:upper:]' '[:lower:]')"
    prompt="$(tr '\n' ' ' < "$STUB/claude_stdin" | tr -s ' ' | tr '[:upper:]' '[:lower:]')"
    for phrase in "never fabricate" "writes_enabled stays false" "127.0.0.1" "never its value" \
                  "stop at that point" "do not run git add, git commit or git push" \
                  "never edit, switch or reset" "do not widen your permissions"; do
        contains "the prompt says: $phrase" "$prompt" "$phrase"
    done
    contains "runs with Opus 5 pinned" "$args" "--model claude-opus-5"
    contains "runs with high effort pinned" "$args" "--effort high"
    contains "runs with acceptEdits" "$args" "--permission-mode acceptedits"
    lacks "the prompt is not passed as a positional argument" "$args" "you have been started automatically"
    lacks "no bypassPermissions"     "$args" "bypasspermissions"
    lacks "no dangerous skip flag"   "$args" "dangerously"
    contains "the prompt is delivered on stdin" "$prompt" "you have been started automatically"
}

# --------------------------------------------------------------------------- run

printf '\nCROOKS AI bridge watcher — tests\n%s\n' "──────────────────────────────────────────────────────────────"
for t in \
    t_unchanged_inbox_never_starts_claude \
    t_a_changed_inbox_runs_claude_once \
    t_the_same_inbox_is_not_processed_twice \
    t_the_outbox_moving_does_not_retrigger \
    t_github_unreachable_starts_nothing \
    t_seed_records_without_running_claude \
    t_claude_runs_in_the_builder_worktree \
    t_the_production_checkout_is_never_the_target \
    t_a_missing_builder_worktree_refuses \
    t_a_dirty_builder_refuses_and_discards_nothing \
    t_a_dirty_builder_can_be_overridden_deliberately \
    t_a_held_lock_suppresses_a_second_claude \
    t_another_claude_in_the_tree_refuses_to_start \
    t_a_claude_elsewhere_on_the_box_is_not_confused_for_one_here \
    t_a_newer_inbox_mid_run_is_taken_next_cycle \
    t_claude_never_publishes_anything_itself \
    t_the_watcher_publishes_exactly_the_outbox \
    t_unexpected_bridge_changes_refuse_to_publish \
    t_application_code_cannot_ride_the_bridge_branch \
    t_a_run_that_wrote_no_outbox_is_a_failure \
    t_a_failed_push_does_not_mark_the_inbox_processed \
    t_a_push_that_changed_nothing_is_not_success \
    t_a_successful_watcher_push_marks_it_processed \
    t_staging_more_than_the_outbox_refuses_to_commit \
    t_a_failed_run_is_not_recorded \
    t_a_failed_run_is_retried_next_cycle \
    t_backoff_grows_then_caps \
    t_anything_inside_the_production_repo_is_refused \
    t_a_linked_worktree_of_production_is_refused \
    t_a_standalone_clone_is_accepted \
    t_staging_installs_exactly_the_runtime_payload \
    t_the_staged_runtime_is_byte_identical_to_source \
    t_staging_is_safe_to_repeat \
    t_verify_detects_a_runtime_that_drifted_from_source \
    t_upgrade_can_verify_new_payload_before_replacing_old_unit \
    t_the_manifest_records_where_it_came_from \
    t_the_unit_does_not_grant_write_access_to_production \
    t_the_prompt_carries_the_safety_contract
do
    printf '\n%s\n' "${t#t_}" | tr '_' ' '
    setup
    "$t"
    teardown
done

printf '\n%s\n' "──────────────────────────────────────────────────────────────"
if [ "$FAIL" -eq 0 ]; then printf '%s passed, 0 failed.\n\n' "$PASS"; exit 0; fi
printf '%s passed, %s FAILED:\n' "$PASS" "$FAIL"
for n in "${FAILED_NAMES[@]}"; do printf '  - %s\n' "$n"; done
printf '\n'; exit 1
