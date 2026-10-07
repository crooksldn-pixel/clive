#!/usr/bin/env bash
# archive_branches.sh: archive the branches listed in docs/repo/BRANCHES_TO_ARCHIVE.txt.
#
# Why it exists: crooksldn-pixel/clive had about 265 branches, most of them work that landed or
# was superseded long ago. George asked for a clean repository. Deleting a branch loses nothing
# here, because each one is first kept as a tag.
#
# What it promises, for every line of the list:
#   - It touches a branch only if the branch is still at the SHA on its line. A branch that has
#     moved since the list was made is refused, never archived at its new tip.
#   - It pushes the tag archive/<branch, every / made -> at that SHA, reads the tag back from the
#     remote, and deletes the branch only after the tag has been read back at that SHA.
#   - The delete is leased on that SHA too, so a push that lands in between makes the delete fail
#     instead of throwing the new work away.
#   - It never touches GitHub's default branch, a line whose "requires" path is not yet on
#     clive/trunk, or any branch that must be kept (see KEPT below), whatever the list says.
#   - Without --apply it changes nothing: it prints what it would do and why.
#   - Running it again is safe: a branch already archived (gone, tag in place) is reported as
#     done, and a tag already pushed is not pushed again.
#
# Usage, from any clone of crooksldn-pixel/clive:
#   scripts/repo/archive_branches.sh              # dry run: the plan, nothing changed
#   scripts/repo/archive_branches.sh --apply      # do it
# Options: --list FILE (default docs/repo/BRANCHES_TO_ARCHIVE.txt beside this script),
#          --remote NAME-OR-URL (default origin, which must be crooksldn-pixel/clive).
# Exit status: 0 when every line is done or doable, 1 when any line was refused, is waiting or
# failed (the other lines are still processed), 2 when the list or the arguments are wrong.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIST="$HERE/../../docs/repo/BRANCHES_TO_ARCHIVE.txt"
REMOTE="origin"
REMOTE_GIVEN=0
APPLY=0
CHUNK=50
NS="refs/archive-branches-run"

# Never archived, whatever the list says: the trunk, the loop's control and evidence branches, its
# frozen state, the retired bridge's record, the sister apps, the theme (move_theme.sh moves it),
# the venture engine George parked, and the night builds of 7-8 October.
KEPT='^(clive/trunk|clive/control/.*|clive/evidence/.*|clive/engineering-state|crooks-ai-bridge|claude/compassionate-dirac-44hnee|claude/crooksldn-theme-init-bnen7a|claude/venture-engine-v1-2026-09-29|claude/n2-.*)$'

die() { echo "archive_branches: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --list) [ $# -ge 2 ] || die "--list needs a file"; LIST="$2"; shift ;;
    --remote) [ $# -ge 2 ] || die "--remote needs a name or URL"; REMOTE="$2"; REMOTE_GIVEN=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

git rev-parse --git-dir >/dev/null 2>&1 || die "run this inside a clone of crooksldn-pixel/clive"
[ -f "$LIST" ] || die "no list at $LIST"
if [ "$REMOTE_GIVEN" = 0 ]; then
  url="$(git remote get-url "$REMOTE" 2>/dev/null)" || die "this clone has no remote called $REMOTE"
  echo "$url" | grep -Eq 'crooksldn-pixel/clive(\.git)?/?$' || die "$REMOTE is $url, not crooksldn-pixel/clive; pass --remote to choose"
fi

WORK="$(mktemp -d)"
cleanup() {
  git for-each-ref --format='%(refname)' "$NS/" | while read -r ref; do git update-ref -d "$ref"; done
  rm -rf "$WORK"
}
trap cleanup EXIT

tag_of() { echo "archive/${1//\//-}"; }

# --- read and check the list ------------------------------------------------------------------
: > "$WORK/lines"
n=0
while IFS= read -r raw || [ -n "$raw" ]; do
  case "$raw" in ''|'#'*) continue ;; esac
  read -r branch sha requires reason <<<"$raw"
  n=$((n + 1))
  [ -n "${reason:-}" ] || die "line $n has no reason: $raw"
  git check-ref-format --branch "$branch" >/dev/null 2>&1 || die "not a branch name: $branch"
  echo "$sha" | grep -Eq '^[0-9a-f]{40}$' || die "$branch: not a full SHA: $sha"
  if echo "$branch" | grep -Eq "$KEPT"; then die "$branch must be kept and is on the list; fix the list"; fi
  printf '%s %s %s %s\n' "$branch" "$sha" "$requires" "$(tag_of "$branch")" >> "$WORK/lines"
done < "$LIST"
[ "$n" -gt 0 ] || die "the list is empty"
dupe="$(awk '{print $1}' "$WORK/lines" | sort | uniq -d | head -1)"
[ -z "$dupe" ] || die "listed twice: $dupe"
dupe="$(awk '{print $4}' "$WORK/lines" | sort | uniq -d | head -1)"
[ -z "$dupe" ] || die "two branches would share the tag $dupe"

# --- what the remote holds now ----------------------------------------------------------------
snapshot() { git ls-remote "$REMOTE" 'refs/heads/*' 'refs/tags/archive/*' > "$WORK/remote" || die "cannot read $REMOTE"; }
remote_sha() { awk -v r="$1" '$2 == r { print $1 }' "$WORK/remote"; }
snapshot
default="$(git ls-remote --symref "$REMOTE" HEAD | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2 }')"
git fetch --quiet --no-tags "$REMOTE" "+refs/heads/*:$NS/heads/*" || die "cannot fetch from $REMOTE"

# --- the plan ---------------------------------------------------------------------------------
: > "$WORK/todo"; : > "$WORK/report"
refused=0; waiting=0; done_before=0
while read -r branch sha requires tag; do
  head="$(remote_sha "refs/heads/$branch")"
  tagged="$(remote_sha "refs/tags/$tag")"
  if [ -z "$head" ]; then
    if [ "$tagged" = "$sha" ]; then
      echo "done      $branch (already archived as $tag)" >> "$WORK/report"; done_before=$((done_before + 1))
    else
      echo "REFUSED   $branch: not on the remote, and $tag is not at ${sha:0:8}" >> "$WORK/report"; refused=$((refused + 1))
    fi
  elif [ "$head" != "$sha" ]; then
    echo "REFUSED   $branch: it is at ${head:0:8} now, not ${sha:0:8}; it moved after the list was made" >> "$WORK/report"; refused=$((refused + 1))
  elif [ "$branch" = "$default" ]; then
    echo "REFUSED   $branch: it is GitHub's default branch; make clive/trunk the default first" >> "$WORK/report"; refused=$((refused + 1))
  elif [ -n "$tagged" ] && [ "$tagged" != "$sha" ]; then
    echo "REFUSED   $branch: $tag already exists at ${tagged:0:8}" >> "$WORK/report"; refused=$((refused + 1))
  elif [ "$requires" != "-" ] && ! git cat-file -e "$NS/heads/clive/trunk:$requires" 2>/dev/null; then
    echo "WAITING   $branch: $requires is not on clive/trunk yet" >> "$WORK/report"; waiting=$((waiting + 1))
  elif ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    echo "REFUSED   $branch: ${sha:0:8} could not be fetched" >> "$WORK/report"; refused=$((refused + 1))
  else
    printf '%s %s %s %s\n' "$branch" "$sha" "$tag" "${tagged:+tagged}" >> "$WORK/todo"
  fi
done < "$WORK/lines"
todo="$(wc -l < "$WORK/todo" | tr -d ' ')"

echo "List: $n branches. To archive now: $todo. Already archived: $done_before. Waiting: $waiting. Refused: $refused."
grep -v '^done' "$WORK/report" || true
if [ "$APPLY" = 0 ]; then
  [ "$todo" = 0 ] || awk '{ printf "would archive  %s  %s -> %s\n", substr($2, 1, 8), $1, $3 }' "$WORK/todo"
  echo "Dry run: nothing was changed. Run again with --apply to archive the $todo branches above."
  [ $((refused + waiting)) = 0 ] || exit 1
  exit 0
fi

# --- 1. the tags, in chunks; a failed chunk is caught by the read-back below --------------------
awk '$4 != "tagged" { print $2 ":refs/tags/" $3 }' "$WORK/todo" > "$WORK/tag-specs"
split -l "$CHUNK" "$WORK/tag-specs" "$WORK/tag-chunk." 2>/dev/null || true
for chunk in "$WORK"/tag-chunk.*; do
  [ -s "$chunk" ] || continue
  # shellcheck disable=SC2046
  git -c push.negotiate=false push --quiet --no-verify "$REMOTE" $(cat "$chunk") || echo "archive_branches: a tag push reported an error; checking each tag" >&2
done

# --- 2. read every tag back; only a branch whose tag is there at its SHA goes ------------------
snapshot
: > "$WORK/verified"; failed=0
while read -r branch sha tag _; do
  if [ "$(remote_sha "refs/tags/$tag")" = "$sha" ]; then
    echo "$branch $sha $tag" >> "$WORK/verified"
  else
    echo "FAILED    $branch: $tag could not be read back at ${sha:0:8}; the branch was left alone"; failed=$((failed + 1))
  fi
done < "$WORK/todo"

# --- 3. delete, each leased on its SHA, in chunks ----------------------------------------------
split -l "$CHUNK" "$WORK/verified" "$WORK/del-chunk." 2>/dev/null || true
for chunk in "$WORK"/del-chunk.*; do
  [ -s "$chunk" ] || continue
  # shellcheck disable=SC2046
  git -c push.negotiate=false push --quiet --no-verify \
    $(awk '{ print "--force-with-lease=refs/heads/" $1 ":" $2 }' "$chunk") \
    "$REMOTE" $(awk '{ print ":refs/heads/" $1 }' "$chunk") \
    || echo "archive_branches: a delete push reported an error; checking each branch" >&2
done

# --- 4. read the branches back --------------------------------------------------------------------
snapshot
archived=0
while read -r branch sha tag; do
  if [ -z "$(remote_sha "refs/heads/$branch")" ]; then
    echo "archived  ${sha:0:8}  $branch -> $tag"; archived=$((archived + 1))
  else
    echo "FAILED    $branch: still on the remote after the delete (its tag $tag is in place)"; failed=$((failed + 1))
  fi
done < "$WORK/verified"

echo "Archived $archived of $todo. Already archived before: $done_before. Waiting: $waiting. Refused: $refused. Failed: $failed."
[ $((refused + waiting + failed)) = 0 ] || exit 1
