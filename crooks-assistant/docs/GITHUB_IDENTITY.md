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
| **Workflows** | Read and write: see the note below | No access |
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

**Why only the Director gets Workflows.** GitHub refuses an App's push that changes a file under `.github/workflows/` unless the App has the Workflows permission. The Director sometimes merges such a change (PR #108 changed `acceptance.yml`). The loop never may: `.github/workflows` is a protected path for its builders. So CLIVE's App gets no Workflows permission, and GitHub itself refuses such a push from it.

**Why CLIVE's App has Pull requests.** The ruling named it. The loop lands on `clive/trunk` directly and opens no pull request today. The token helper asks for only the permissions a caller names, so the loop can be narrowed later without touching the App.

## 2. Where each private key lives

Never in the repository, the engineering store, a builder's workspace or the loop's runtime folder. Each key is one file only its owner can read: mode 600, in a folder of mode 700.

- **CLIVE's App, on clive-worker-01:** `/etc/clive/github/clive-app.pem`, owned by the user the loop's unit runs as. Its token cache is `/etc/clive/github/cache/`. The Termius Claude puts the key there by pasting it into `cat > /etc/clive/github/clive-app.pem`. A builder cannot read it: a builder's environment is built from nothing, its file tools are confined to its workspace, and it has no shell (`app/orchestrator/workers/claude.py`).
- **The Director's App:** on the host the Director runs on, at `~/.config/clive/github/director-app.pem`. That host is not the build machine yet, for the reason below.
- **Losing a key, or leaving the project:** App settings → **Private keys** → delete it, then generate a new one. Uninstalling the App cuts it off at once.

## 3. What switches each one over

### The build loop (clive-worker-01): configuration only, no code change

Everything the loop does on GitHub goes through git's credential for `https://github.com` in its `--repo` clone. That covers fetching the inbox, pushing candidates, landing and the status branch. The GitHub acceptance gate asks the same credential through `git credential fill`.

So pointing git's credential helper at the App switches all of it. `tests/test_github_app_token.py` proves this for the gate: `git_remote_token` returns the App's token once the helper is configured. The Termius Claude does this, as root:

```sh
U=<the unit's User=>; R=<the unit's --repo>; PY=<the python in the unit's ExecStart>; T=<the pinned tree>
install -d -m 700 -o "$U" /etc/clive/github /etc/clive/github/cache
# paste the .pem into /etc/clive/github/clive-app.pem, then:
chown "$U" /etc/clive/github/clive-app.pem && chmod 600 /etc/clive/github/clive-app.pem
H="!$PY $T/crooks-assistant/scripts/github_app_token.py --app-id <APP ID> --installation-id <INSTALLATION ID> --key-file /etc/clive/github/clive-app.pem --cache-dir /etc/clive/github/cache --permission contents=write --permission actions=read credential"
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

**After the first landing by the App:** revoke the old personal token in **Settings → Developer settings → Personal access tokens**. Its name is not recorded in the repository. It is the one in the clone's old credential (the URL or the store).

### CLIVE in production: a follow-up, not switched

The bridge reads one static token from the secret store at each call. An App's token lives an hour, so it cannot be stored once. Switching needs a small change in `app/engineering_bridge/github.py`: `read_token` would mint through `scripts/github_app_token.py`'s `token()`, with CLIVE's App key stored on the production host.

That file is a protected path, outside this workstream's brief, so it is not done here. Until it is, production keeps `github_engineering_inbox_token`. When it moves, the minted token asks for `contents=write` only (filing writes one file to the inbox branch; reading the status needs no more).

### The Director: not switchable from inside these sessions

The Director works in Claude Code sessions on the build machine. Their GitHub traffic passes a proxy that puts George's credential on every request (checked 8 Oct, above). A token the Director mints there would be replaced on the way out. The Director App can only take effect in one of two ways:

- **The Director runs on a host whose GitHub traffic is its own.** Then configure that host's checkout exactly as for the loop, with the Director's App ID, installation ID and key, and no `--permission` flags beyond the defaults plus `--permission workflows=write`. Use `GH_TOKEN="$(… github_app_token.py … token)"` for API calls. Set the commit identity to the App's bot:

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
