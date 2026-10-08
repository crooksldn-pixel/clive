#!/usr/bin/env bash
# move_theme.sh: move the Shopify theme out of crooksldn-pixel/clive into its own private
# repository, crooksldn-pixel/crooksldn-theme.
#
# Why it exists: the theme reached the CLIVE repository by accident, and George wants a clear
# boundary between the two. The live theme's source is the branch claude/crooksldn-theme-init-bnen7a;
# the other branches in docs/repo/THEME_BRANCHES.txt are theme experiments and shop research on
# the theme's own line. None of them holds CLIVE code.
#
# What it promises:
#   - The theme branch becomes main in the theme repository with its full history, and each other
#     listed branch is kept there as the tag on its line. Everything pushed is read back from the
#     theme repository and must be at the listed SHA (main may have moved on from it since).
#   - It refuses to push anywhere it can see is public: the theme repository must be private.
#     Every form git accepts for a github.com address is checked (https, http, ssh, git@host:,
#     with or without user@ or credentials, www. or .git, a remote name or an insteadOf alias).
#     An address that names github.com but no owner/repo stops the run: it never pushes unchecked.
#   - It never prints a credential: user:password@ or token@ in any address is shown as ***@,
#     in its own messages and in git's.
#   - It touches a branch only if it is still at the SHA on its line.
#   - Without --apply it changes nothing: it prints what it would do.
#   - Only with --delete-public (and --apply) does it delete the listed branches from clive, each
#     only after the theme repository has been read back holding it, each leased on its SHA, and
#     never GitHub's default branch.
#   - Running it again is safe: what is already in the theme repository is not pushed again.
#
# What it cannot do: anything that was ever public stays public. Existing clones and forks of
# clive keep these branches, GitHub can serve an old commit by its SHA for some time, and clive's
# own history keeps the 20 July theme snapshot it started from. So the possible token in
# mobile/SETUP.md (commit af9d1dc9 on the theme branch) must be rotated whatever this script does.
#
# Usage, from any clone of crooksldn-pixel/clive, after George (or you) created the EMPTY private
# repository crooksldn-pixel/crooksldn-theme (no README, no licence, no .gitignore):
#   scripts/repo/move_theme.sh                            # dry run
#   scripts/repo/move_theme.sh --apply                    # push to the theme repo and check it
#   scripts/repo/move_theme.sh --apply --delete-public    # then delete the branches from clive
# Options: --list FILE (default docs/repo/THEME_BRANCHES.txt beside this script),
#          --public URL (default: this clone's origin, which must be crooksldn-pixel/clive),
#          --theme URL (default: origin's URL with clive replaced by crooksldn-theme).
# Exit status: 0 when every line is done, 1 when any line was refused or failed, 2 when the
# arguments, the list or a precondition are wrong.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIST="$HERE/../../docs/repo/THEME_BRANCHES.txt"
PUBLIC=""
THEME=""
APPLY=0
DELETE_PUBLIC=0
NS="refs/move-theme-run"

die() { echo "move_theme: $*" >&2; exit 2; }

# Never print a credential: whatever sits before the @ of an address's host is shown as ***.
redact() { sed -E 's#([A-Za-z][A-Za-z0-9+.-]*://)[^/[:space:]]*@#\1***@#g'; }
shown() { printf '%s' "$1" | redact; }

# The owner/repo of a github.com address in any form git accepts, or nothing. User, credentials,
# www., a port, .git and a trailing / are dropped; anything else (another host, a deeper path)
# gives nothing, and the caller then refuses an address that still mentions github.com.
github_slug() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed -nE '
    s#^(https?|ssh|git\+ssh|ssh\+git|git)://([^/]*@)?(www\.)?github\.com(:[0-9]+)?/#/#
    t path
    s#^([^/:]*@)?(www\.)?github\.com:#/#
    t path
    d
    :path
    s#/+$##
    s#\.git$##
    s#^/([a-z0-9][a-z0-9-]*/[a-z0-9._-]+)$#\1#p'
}
mentions_github() { printf '%s' "$1" | grep -qi 'github\.com'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --delete-public) DELETE_PUBLIC=1 ;;
    --list) [ $# -ge 2 ] || die "--list needs a file"; LIST="$2"; shift ;;
    --public) [ $# -ge 2 ] || die "--public needs a URL"; PUBLIC="$2"; shift ;;
    --theme) [ $# -ge 2 ] || die "--theme needs a URL"; THEME="$2"; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done
[ "$DELETE_PUBLIC" = 0 ] || [ "$APPLY" = 1 ] || die "--delete-public needs --apply as well"

git rev-parse --git-dir >/dev/null 2>&1 || die "run this inside a clone of crooksldn-pixel/clive"
[ -f "$LIST" ] || die "no list at $LIST"
if [ -z "$PUBLIC" ]; then
  PUBLIC="$(git remote get-url origin 2>/dev/null)" || die "this clone has no origin; pass --public"
  echo "$PUBLIC" | grep -Eq 'crooksldn-pixel/clive(\.git)?/?$' || die "origin is $(shown "$PUBLIC"), not crooksldn-pixel/clive; pass --public"
fi
if [ -z "$THEME" ]; then
  echo "$PUBLIC" | grep -Eq 'crooksldn-pixel/clive(\.git)?/?$' || die "cannot work out the theme repository from $(shown "$PUBLIC"); pass --theme"
  THEME="$(echo "$PUBLIC" | sed -E 's#crooksldn-pixel/clive(\.git)?/?$#crooksldn-pixel/crooksldn-theme.git#')"
fi
[ "$PUBLIC" != "$THEME" ] || die "the public and the theme repository are the same"
PUBLIC_SHOWN="$(shown "$PUBLIC")"
THEME_SHOWN="$(shown "$THEME")"

# Which GitHub repository the theme goes to: from the address as given, or as git will really
# reach it (a remote name or an insteadOf alias expanded). Decided before anything talks to a
# remote; an address on github.com that does not say which repository stops here.
slug=""
for url in "$THEME" "$(git ls-remote --get-url "$THEME" 2>/dev/null || true)"; do
  [ -z "$slug" ] || break
  slug="$(github_slug "$url")"
  if [ -z "$slug" ] && mentions_github "$url"; then
    die "$(shown "$url") is on github.com but does not say which repository (owner/repo), so it cannot be checked for privacy; pass --theme https://github.com/<owner>/<repo>.git"
  fi
done

WORK="$(mktemp -d)"
cleanup() {
  git for-each-ref --format='%(refname)' "$NS/" | while read -r ref; do git update-ref -d "$ref"; done
  rm -rf "$WORK"
}
trap cleanup EXIT

# Run a git command that talks to a remote, with its error output redacted.
remote_git() {
  local status=0
  git "$@" 2> "$WORK/git.err" || status=$?
  redact < "$WORK/git.err" >&2
  return "$status"
}

# --- read and check the list ------------------------------------------------------------------
: > "$WORK/lines"
n=0; mains=0
while IFS= read -r raw || [ -n "$raw" ]; do
  case "$raw" in ''|'#'*) continue ;; esac
  read -r branch sha target reason <<<"$raw"
  n=$((n + 1))
  [ -n "${reason:-}" ] || die "line $n has no description: $raw"
  git check-ref-format --branch "$branch" >/dev/null 2>&1 || die "not a branch name: $branch"
  echo "$sha" | grep -Eq '^[0-9a-f]{40}$' || die "$branch: not a full SHA: $sha"
  case "$target" in
    refs/heads/main) mains=$((mains + 1)) ;;
    refs/tags/archive/*) git check-ref-format "$target" || die "not a tag name: $target" ;;
    *) die "$branch: its target must be refs/heads/main or refs/tags/archive/<name>, not $target" ;;
  esac
  printf '%s %s %s\n' "$branch" "$sha" "$target" >> "$WORK/lines"
done < "$LIST"
[ "$mains" = 1 ] || die "exactly one line must become refs/heads/main (found $mains)"
[ -z "$(awk '{print $1}' "$WORK/lines" | sort | uniq -d)" ] || die "a branch is listed twice"
[ -z "$(awk '{print $3}' "$WORK/lines" | sort | uniq -d)" ] || die "two branches have the same target"

# --- the theme repository must exist, be readable, and be private ----------------------------
remote_git ls-remote "$THEME" > "$WORK/theme" || \
  die "cannot read $THEME_SHOWN. Create the EMPTY private repository crooksldn-pixel/crooksldn-theme first."
if [ -n "$slug" ]; then
  # Asked without credentials: GitHub answers 200 for a public repository and 404 for a private one.
  code="$(curl -s -o /dev/null -w '%{http_code}' "https://api.github.com/repos/$slug" || true)"
  case "$code" in
    404) echo "The theme repository $slug is private (GitHub does not show it without credentials)." ;;
    200) die "$slug is PUBLIC. Make it private (Settings > General > Danger Zone > Change visibility) and run this again." ;;
    *) die "could not check that $slug is private (GitHub answered '$code'); check it in its Settings, then run again" ;;
  esac
else
  echo "The theme repository $THEME_SHOWN is not on github.com; not checking its visibility."
fi

# --- what clive holds now ---------------------------------------------------------------------
remote_git ls-remote "$PUBLIC" 'refs/heads/*' > "$WORK/public" || die "cannot read $PUBLIC_SHOWN"
default="$(remote_git ls-remote --symref "$PUBLIC" HEAD | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2 }')"
sha_in() { awk -v r="$2" '$2 == r { print $1 }' "$WORK/$1"; }
fetch_specs=""
while read -r branch _ _; do
  [ -z "$(sha_in public "refs/heads/$branch")" ] || fetch_specs="$fetch_specs +refs/heads/$branch:$NS/public/$branch"
done < "$WORK/lines"
# shellcheck disable=SC2086
[ -z "$fetch_specs" ] || remote_git fetch --quiet --no-tags "$PUBLIC" $fetch_specs || die "cannot fetch the theme branches from $PUBLIC_SHOWN"
if [ -n "$(sha_in theme refs/heads/main)" ]; then
  remote_git fetch --quiet --no-tags "$THEME" "+refs/heads/main:$NS/theme/main" || die "cannot fetch main from $THEME_SHOWN"
fi

# A line is in the theme repository when its target is at its SHA, or, for main, when main has
# moved on from it (the theme repository is where theme work happens now).
in_theme() {
  local sha="$1" target="$2" there
  there="$(sha_in theme "$target")"
  [ -n "$there" ] || return 1
  [ "$there" = "$sha" ] && return 0
  [ "$target" = refs/heads/main ] && git merge-base --is-ancestor "$sha" "$NS/theme/main" 2>/dev/null
}

# --- the plan ---------------------------------------------------------------------------------
: > "$WORK/push"; : > "$WORK/moved"
refused=0
while read -r branch sha target; do
  head="$(sha_in public "refs/heads/$branch")"
  if [ -n "$head" ] && [ "$head" != "$sha" ]; then
    echo "REFUSED   $branch: it is at ${head:0:8} on clive now, not ${sha:0:8}"; refused=$((refused + 1))
  elif in_theme "$sha" "$target"; then
    echo "$branch $sha $target" >> "$WORK/moved"
  elif [ -n "$(sha_in theme "$target")" ]; then
    echo "REFUSED   $branch: $target in the theme repository is something else ($(sha_in theme "$target" | cut -c1-8))"; refused=$((refused + 1))
  elif [ -z "$head" ]; then
    echo "REFUSED   $branch: not on clive, and not in the theme repository"; refused=$((refused + 1))
  else
    echo "$branch $sha $target" >> "$WORK/push"
  fi
done < "$WORK/lines"
# main first: the first branch pushed to an empty GitHub repository becomes its default branch.
sort -k3,3 -o "$WORK/push" "$WORK/push"
echo "Theme list: $n branches. Already in the theme repository: $(wc -l < "$WORK/moved" | tr -d ' '). To push: $(wc -l < "$WORK/push" | tr -d ' '). Refused: $refused."
awk '{ printf "to push   %s  %s -> %s\n", substr($2, 1, 8), $1, $3 }' "$WORK/push"

if [ "$APPLY" = 0 ]; then
  echo "Dry run: nothing was changed. Run again with --apply to push to $THEME_SHOWN."
  [ "$refused" = 0 ] || exit 1
  exit 0
fi

# --- push, then read everything back ----------------------------------------------------------
failed=0
while read -r branch sha target; do
  if ! remote_git -c push.negotiate=false push --quiet --no-verify "$THEME" "$sha:$target"; then
    echo "FAILED    $branch: the push to $target was refused (if GitHub named a secret, stop: George rotates it first)"
    failed=$((failed + 1))
  fi
done < "$WORK/push"
remote_git ls-remote "$THEME" > "$WORK/theme" || die "cannot read $THEME_SHOWN back"
if [ -n "$(sha_in theme refs/heads/main)" ]; then
  remote_git fetch --quiet --no-tags "$THEME" "+refs/heads/main:$NS/theme/main" || die "cannot fetch main from $THEME_SHOWN"
fi
: > "$WORK/held"
while read -r branch sha target; do
  if in_theme "$sha" "$target"; then
    echo "in theme  ${sha:0:8}  $branch -> $target"
    echo "$branch $sha $target" >> "$WORK/held"
  else
    echo "FAILED    $branch: $target could not be read back from the theme repository at ${sha:0:8}"; failed=$((failed + 1))
  fi
done < <(cat "$WORK/moved" "$WORK/push")

# --- only now, and only when asked: delete them from clive ------------------------------------
deleted=0
if [ "$DELETE_PUBLIC" = 1 ]; then
  while read -r branch sha target; do
    head="$(sha_in public "refs/heads/$branch")"
    if [ -z "$head" ]; then
      echo "gone      $branch (already deleted from clive)"
    elif [ "$branch" = "$default" ]; then
      echo "REFUSED   $branch: it is clive's default branch on GitHub; make clive/trunk the default, then run again"
      refused=$((refused + 1))
    elif remote_git -c push.negotiate=false push --quiet --no-verify --force-with-lease="refs/heads/$branch:$sha" "$PUBLIC" ":refs/heads/$branch"; then
      deleted=$((deleted + 1))
    else
      echo "FAILED    $branch: the delete from clive was refused"; failed=$((failed + 1))
    fi
  done < "$WORK/held"
  remote_git ls-remote "$PUBLIC" 'refs/heads/*' > "$WORK/public" || die "cannot read $PUBLIC_SHOWN back"
  while read -r branch sha target; do
    if [ -n "$(sha_in public "refs/heads/$branch")" ] && [ "$branch" != "$default" ]; then
      echo "FAILED    $branch: still on clive after the delete"; failed=$((failed + 1))
    fi
  done < "$WORK/held"
  echo "Deleted from clive: $deleted."
else
  echo "Nothing was deleted from clive. When George has checked the theme repository, run again with --apply --delete-public."
fi

echo "Reminder: whatever was public stays public in existing clones, forks and GitHub's cache of old commits. Rotate the possible token in mobile/SETUP.md (af9d1dc9) regardless."
echo "Refused: $refused. Failed: $failed."
[ $((refused + failed)) = 0 ] || exit 1
