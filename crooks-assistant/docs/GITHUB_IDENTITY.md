# GitHub identity for the Director and for CLIVE

George ruled on 8 October 2026 that the Director and CLIVE should each get their own GitHub identity (DEC-071, ruling 13; recorded with its steps in DEC-076). A GitHub App gives each one, so neither works as his account.

This page gives:

- what George creates, click by click;
- where each private key lives (never in the repository);
- what switches each one over, and what is not switched yet.

`scripts/github_app_token.py` mints the tokens. It is tested in `tests/test_github_app_token.py`, and both files are protected paths.

## What it acts as today

| Who | Where it runs | What it uses on GitHub today |
|---|---|---|
| **The Director** (the Claude Code sessions that review, merge and file) | the build machine | George's own account. The session's GitHub connection supplies his credential (see below). |
| **The build loop** | clive-worker-01, the unit `clive-remote-engineering` | Whatever git holds for the remote of the unit's `--repo` clone: a personal token of George's. The loop uses it to fetch the inbox, push candidates, land on `clive/trunk` and push the status branch. The GitHub acceptance gate reads Actions with the same credential (`git_remote_token`, `app/orchestrator/github_acceptance.py`). |
| **CLIVE in production** (filing a build, reading its status) | crooks-os-prod-1 | The secret `github_engineering_inbox_token` (`app/engineering_bridge/github.py`). |

**Checked from the build machine on 8 Oct 2026:** the session's GitHub proxy replaces any `Authorization` header with George's credential. A request sent with a made-up token came back as `crooksldn-pixel`. So inside these sessions, a Director App's token cannot take effect. See "The Director" below for what that means.

## 1. George creates two GitHub Apps (about 10 minutes, in a browser)

The repository belongs to his personal account, `crooksldn-pixel`. Both Apps are created there and installed on `clive` only. Do this twice, once per row:

| | The Director's App | CLIVE's App (the loop, then production) |
|---|---|---|
| **GitHub App name** (must be unique on GitHub) | `CLIVE Director (CROOKSLDN)` | `CLIVE (CROOKSLDN)` |
| **Contents** | Read and write | Read and write |
| **Pull requests** | Read and write | Read and write |
| **Actions** | Read-only | Read-only |
| **Workflows** | Read and write: see the note below | Read and write: see the note below |
| **Metadata** | Read-only (GitHub sets it) | Read-only (GitHub sets it) |
| **Everything else** | No access | No access |

1. On github.com, signed in as `crooksldn-pixel`: **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. **GitHub App name:** from the table. **Homepage URL:** `https://github.com/crooksldn-pixel/clive`.
3. **Webhook:** untick **Active**. No webhook is needed.
4. **Permissions → Repository permissions:** exactly the column above. Leave Organization and Account permissions at No access.
5. **Where can this GitHub App be installed?** Choose **Only on this account**. Then **Create GitHub App**.
6. On the page that opens, write down the **App ID** (under About).
7. Scroll to **Private keys → Generate a private key**. A `.pem` file downloads. It is the App's only secret: move it as in step 2 below, then delete the download.
8. In the left menu, choose **Install App → Install** next to `crooksldn-pixel`. Choose **Only select repositories → clive → Install**.
9. The page you land on is `https://github.com/settings/installations/<number>`. That number is the **installation ID**. Write it down.

**What Workflows allows.** A token with it may create, change or delete files under `.github/workflows/`, by a push or through the API. GitHub refuses that to an App without it. A workflow file decides what GitHub Actions runs, with whatever Actions secrets the repository holds, so this is the strongest permission either App has. It does not run, re-run or cancel a workflow; that would be Actions write, which neither App gets.

**Why CLIVE's App needs Workflows.** The loop pushes a commit of its own that can carry a workflow change it did not write: its refresh merge. When `clive/trunk` moves on while a build is under way, the loop merges the trunk head into the objective's branch before landing (`Dispatcher._refresh_merge`, `app/orchestrator/dispatcher.py`). If the trunk gained a `.github/workflows/` change in the meantime, as PR #108's `acceptance.yml` change did, that merge brings the change onto the objective's branch. GitHub then refuses the push from an App without Workflows, and the build stalls before landing.

The loop still never writes a workflow of its own. `.github` is a protected path (`PROTECTED_PATHS`, `app/orchestrator/objectives.py`), and the loop checks it three times:

- at intake, an objective whose scope covers `.github` is refused;
- a builder's candidate that changes anything under `.github` is refused (`_protected_refusal`);
- at landing, any change under `.github` between `clive/trunk` and the SHA being landed is refused, so the loop lands only what the trunk already holds.

The permission lets the loop carry the trunk's own workflow files. It does not let a builder change one.

**Why the Director's App has Workflows: tick it knowingly.** Without it the Director can neither push nor merge a change to `.github/workflows/`, and PR #108 was one. With it, anyone holding a Director token can change what GitHub Actions runs.

**Why CLIVE's App has Pull requests.** The ruling named it. The loop lands on `clive/trunk` directly and opens no pull request today. The token helper asks for only the permissions a caller names, so the loop can be narrowed later without touching the App.

## 2. Where each private key lives

Never in the repository, the engineering store, a builder's workspace or the loop's runtime folder. Each key is one file only its owner can read: mode 600, in a folder of mode 700.

- **CLIVE's App, on clive-worker-01:** `/etc/clive/github/clive-app.pem`, owned by the user the loop's unit runs as. Its token cache is `/etc/clive/github/cache/`. The Termius Claude puts the key there by pasting it into `cat > /etc/clive/github/clive-app.pem`.

  **A builder cannot read it, while the unit gives builders no `--worker-bash-prefix`.** Today a builder's environment is built from nothing, its file tools are confined to its workspace, and it has no shell (`app/orchestrator/workers/claude.py`). Its checks run in the sandbox, whose `/etc` is a curated copy without `/etc/clive`. A `--worker-bash-prefix` would change that: a prefix allowlist is not a sandbox (`git diff --no-index` reads any file the unit's user can; `ENGINEERING_DISPATCHER_V1.md`), so a builder could read the key. A `--check-ro-path` of `/`, `/etc` or `/etc/clive` would show it to checks. §3 checks the unit for both before the key is placed, and again at every re-pin.
- **The Director's App:** on the host the Director runs on, at `~/.config/clive/github/director-app.pem`. That host is not the build machine yet, for the reason below.
- **Losing a key, or leaving the project:** App settings → **Private keys** → delete it, then generate a new one. Uninstalling the App cuts it off at once.

## 3. What switches each one over

### The build loop (clive-worker-01): configuration only, no code change

Everything the loop does on GitHub goes through git's credential for `https://github.com` in its `--repo` clone. That covers fetching the inbox, pushing candidates, landing and the status branch. The GitHub acceptance gate asks the same credential through `git credential fill`.

So pointing git's credential helper at the App switches all of it. `tests/test_github_app_token.py` proves this for the gate: `git_remote_token` returns the App's token once the helper is configured.

**The helper lives at a stable path, never in the pinned tree.** The pinned tree changes or goes at the next re-pin. A helper line pointing into it would then break every fetch, push and acceptance check the loop makes. So the reviewed helper at the pin is copied to `/usr/local/lib/clive/github_app_token.py`, owned by root with mode 0755. The unit's user can run it but not change it. The helper line names only that path, and it never changes.

The Termius Claude does this, as root:

```sh
U=<the unit's User=>; R=<the unit's --repo>; PY=<the python in the unit's ExecStart>; T=<the pinned tree>
# 1. The key stays unreadable to builders only while the unit gives them no shell:
systemctl cat clive-remote-engineering | grep -nE -- '--worker-bash-prefix|--check-ro-path'
#    STOP if it prints any --worker-bash-prefix, or a --check-ro-path of /, /etc or /etc/clive: tell the Director.
# 2. The helper, copied from the pinned tree to its stable path:
install -d -m 755 -o root -g root /usr/local/lib/clive
install -m 755 -o root -g root "$T/crooks-assistant/scripts/github_app_token.py" /usr/local/lib/clive/github_app_token.py
case "$PY" in "$T"/*) echo "PY lies in the pinned tree: use /usr/bin/python3 instead";; esac
sudo -u "$U" "$PY" -c 'import cryptography' && echo "PY ok"         # must print: PY ok
#    If PY lies in the pinned tree, set PY=/usr/bin/python3 and repeat the line above. If that fails too,
#    run `apt-get install python3-cryptography` first.
# 3. The key:
install -d -m 700 -o "$U" /etc/clive/github /etc/clive/github/cache
# paste the .pem into /etc/clive/github/clive-app.pem, then:
chown "$U" /etc/clive/github/clive-app.pem && chmod 600 /etc/clive/github/clive-app.pem
# 4. git asks the App, and nothing else, for github.com:
H="!$PY /usr/local/lib/clive/github_app_token.py --app-id <APP ID> --installation-id <INSTALLATION ID> --key-file /etc/clive/github/clive-app.pem --cache-dir /etc/clive/github/cache --permission contents=write --permission actions=read --permission workflows=write credential"
sudo -u "$U" git -C "$R" config --unset-all credential.https://github.com.helper || true
sudo -u "$U" git -C "$R" config --add credential.https://github.com.helper ""     # no other helper is asked first
sudo -u "$U" git -C "$R" config --add credential.https://github.com.helper "$H"
sudo -u "$U" git -C "$R" remote get-url origin | sed 's#//[^@]*@#//<removed>@#'   # must print https://github.com/crooksldn-pixel/clive
```

If the last line shows anything between `//` and `github.com`, the old token is in the URL. Remove it with `sudo -u "$U" git -C "$R" remote set-url origin https://github.com/crooksldn-pixel/clive`.

**Prove it before restarting anything:**

```sh
sudo -u "$U" git -C "$R" ls-remote origin refs/heads/clive/trunk          # prints the trunk's SHA
sudo -u "$U" git -C "$R" push --dry-run origin "$(sudo -u "$U" git -C "$R" rev-parse origin/clive/control/worker-01-status):refs/heads/clive/control/worker-01-status"
```

Restart the loop only when no builder or review is running, as the re-pin does. The next status push on GitHub then shows `clive-crooksldn[bot]` (or whatever GitHub derived from the App's name) as the pusher.

**Test a refresh merge that carries a workflow change, before revoking the personal token.** This pushes, with the App's credential, a merge shaped like the loop's refresh merge. The objective's branch sits before the trunk's last workflow change, and the merge brings that change in. It uses a throwaway branch, and its commits say `[skip ci]`, so no acceptance run starts:

```sh
B=clive/test/app-workflows; G=(sudo -u "$U" git -C "$R" -c user.name="CLIVE loop" -c user.email=loop@clive.invalid)
TR=$("${G[@]}" rev-parse origin/clive/trunk)
WF=$("${G[@]}" log -1 --format=%H "$TR" -- .github/workflows)    # the trunk's last workflow change
OLD=$("${G[@]}" rev-parse "$WF^1")                                # the trunk just before it
P=$("${G[@]}" commit-tree "$OLD^{tree}" -p "$OLD" -m "App Workflows test: the objective's branch [skip ci]")
M=$("${G[@]}" commit-tree "$TR^{tree}" -p "$P" -p "$TR" -m "App Workflows test: its refresh merge [skip ci]")
"${G[@]}" diff --name-only "$P" "$M" -- .github/workflows         # must list at least one workflow file
"${G[@]}" push origin "$P:refs/heads/$B"                          # the objective's branch: must succeed
"${G[@]}" push origin "$M:refs/heads/$B"                          # the refresh merge: must succeed
"${G[@]}" push origin --delete "$B"
```

- **If the `diff` line lists no workflow file,** the trunk's last workflow change was later undone. Take the one before it, `WF=$("${G[@]}" log -2 --format=%H "$TR" -- .github/workflows | tail -1)`, and carry on from `OLD=`.
- **If the merge's push is refused** with "refusing to allow a GitHub App to create or update workflow … without `workflows` permission", the App or its token lacks Workflows. The fix:
  1. Check the App's **Permissions → Workflows** says Read and write.
  2. If it was changed after installation, accept the new permission at `https://github.com/settings/installations`: the App → **Configure** → accept.
  3. Check the helper line names `--permission workflows=write`: `sudo -u "$U" git -C "$R" config --get-all credential.https://github.com.helper`.
  4. Run the test again.

  Until it passes, keep the personal token. Putting the old helper or URL back restores the loop.

**After the test passes and the App's first landing:** revoke the old personal token in **Settings → Developer settings → Personal access tokens**. Its name is not recorded in the repository. It is the one in the clone's old credential (the URL or the store).

**At every later re-pin to a tree T2,** while the loop is stopped:

- copy the reviewed helper at the new pin to its stable path: `install -m 755 -o root -g root "$T2/crooks-assistant/scripts/github_app_token.py" /usr/local/lib/clive/github_app_token.py`. The helper line in git's configuration stays as it is;
- check the new ExecStart again with step 1's `grep`, while the App's key is on the host.

### CLIVE in production: a follow-up, not switched

The bridge reads one static token from the secret store at each call. An App's token lives an hour, so it cannot be stored once. Switching needs a small change in `app/engineering_bridge/github.py`: `read_token` would mint through `scripts/github_app_token.py`'s `token()`, with CLIVE's App key stored on the production host.

That file is a protected path, outside this workstream's brief, so it is not done here. Until it is, production keeps `github_engineering_inbox_token`. When it moves, the minted token asks for `contents=write` only (filing writes one file to the inbox branch; reading the status needs no more).

### The Director: not switchable from inside these sessions

The Director works in Claude Code sessions on the build machine. Their GitHub traffic passes a proxy that puts George's credential on every request (checked 8 Oct, above). A token the Director mints there would be replaced on the way out. The Director App can only take effect in one of two ways:

- **The Director runs on a host whose GitHub traffic is its own.** Then configure that host's checkout exactly as for the loop, with the Director's App ID, installation ID and key, and the permissions `--permission contents=write --permission pull_requests=write --permission actions=read --permission workflows=write` (any `--permission` replaces the defaults, so all four are named). Use `GH_TOKEN="$(… github_app_token.py … token)"` for API calls. Set the commit identity to the App's bot:

  ```sh
  git config user.name "clive-director-crooksldn[bot]"
  git config user.email "<id>+clive-director-crooksldn[bot]@users.noreply.github.com"
  ```

  where `<id>` is what `gh api /users/clive-director-crooksldn%5Bbot%5D --jq .id` prints.
- **The sessions' GitHub connection itself is changed** to act as the Director's App. That is a setting of the claude.ai GitHub connection, not of this repository. Whether it can be done is not verified here.

Until one of those happens, the Director's merges and pushes keep showing as `crooksldn-pixel`.

On the build machine as it is today, every Claude session (the Director and every builder) runs as one user. A Director key kept there would be readable by every builder session. That is one more reason not to keep it there.

## What this does not change

- No review, gate, protected path or approval changes. The loop's exact-SHA review and the GitHub acceptance gate work as before. Only who pushes changes.
- `clive/trunk` has no branch protection and the repository has no rulesets (checked 8 Oct). Nothing has to let the App through.
- **Optional, later:** a ruleset on `clive/trunk` allowing only George and the two Apps would stop any other credential from moving the trunk.
