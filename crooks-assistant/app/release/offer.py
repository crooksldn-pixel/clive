"""Deploy now, what CLIVE shows: the version waiting to go live, whether George's hold can deploy it now,
and a deploy he approved followed through to the end (DEC-072; the owner's rulings 6, 7 and 8 of
8 October 2026).

Why it exists. George approves each deploy (ruling 7), and his approval starts it at once. So the
Builds screen needs to know, truthfully, three things, and this file decides them from what it reads:

    the offer      clive/trunk's head, when it is ahead of the commit this CLIVE runs on the trunk and
                   GitHub acceptance is green on exactly that SHA: its title, the pull requests since
                   what is live, in their own titles. Nothing else is a card.
    the hold       whether his hold can deploy it now, and if not, why, in a sentence: the release
                   service installed, on, following owner_waiver, not stopped; the change not one that
                   stays a hand deploy (app/release/facts.py `guarded`, the service's own list); and,
                   when the service has already looked at this SHA, nothing but his approval missing
                   (its `ready_for`). Dry run is said, and the hold then only tries.
    the progress   the deploy his approval started, from the release service's own status, stage by
                   stage: started, checks, installing, health, done (or rolled back, stopped or refused,
                   with why), then kept, once his phone's /whoami got through on the new build.

The reads (the trunk's head, the comparison, acceptance) are GitHub's, with the engineering inbox's
token (app/engineering_bridge/github.py read_token), each kept a minute; nothing here writes anywhere.
The decisions (`offer`, `progress`) are pure, so a test can drive every case without a network.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.orchestrator.github_acceptance import GateResult, GateState, GitHubAcceptance, ask
from app.release import facts as release_facts
from app.release.settings import OWNER_WAIVER, TRUNK

API_URL = "https://api.github.com"
TIMEOUT_S = 15.0
CACHE_S = 60.0
CHANGES_SHOWN = 8
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PR = re.compile(r"\s*\(PR #(\d+)\)\s*$")
# The loop's own merges of the trunk into a build's branch: plumbing, not something that was built.
_PLUMBING = re.compile(r"^Merge (clive/trunk|branch|remote-tracking branch) ")
STAGES = (("started", "Started"), ("checks", "Checks"), ("installing", "Installing"), ("health", "Health"),
          ("done", "Done"), ("kept", "Kept"))
TAKES = "Deploying takes a few minutes: checks, the install, a restart, then a health check."


@dataclass
class Trunk:
    """What GitHub says of the trunk against what runs here."""
    sha: str = ""
    title: str = ""
    ahead: bool | None = None                  # the trunk's head has what runs here behind it
    changes: list[str] = field(default_factory=list)   # titles since what runs here, newest first
    count: int = 0                             # commits since what runs here
    files: list[str] | None = None             # what the change touches; None when GitHub listed only part
    acceptance: GateResult | None = None
    problem: str = ""


def plain(subject: str) -> str:
    """A commit's title in plain words: its first line, without the "(PR #111)" GitHub adds."""
    first = " ".join(str(subject or "").splitlines()[0].split()) if str(subject or "").strip() else ""
    return _PR.sub("", first)[:200]


# ------------------------------------------------------------------ reading GitHub


class GitHubTrunk:
    """The trunk's head, the comparison with what runs here, and acceptance on the head: three reads."""

    def __init__(self, repository: str, *, token_source=None, transport: httpx.AsyncBaseTransport | None = None,
                 sync_transport: httpx.BaseTransport | None = None, api_url: str = API_URL) -> None:
        if token_source is None:
            from app.engineering_bridge.github import read_token

            token_source = read_token
        self.repository = repository
        self._token_source = token_source
        self._transport = transport
        self._sync_transport = sync_transport
        self._api_url = api_url

    def _token(self) -> str | None:
        try:
            token = self._token_source()
        except Exception:  # noqa: BLE001 - a token that cannot be read is no token
            return None
        return token if isinstance(token, str) and token.strip() else None

    async def _get(self, client: httpx.AsyncClient, path: str, what: str) -> Any:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "clive-deploy-now"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        try:
            response = await client.get(path, headers=headers)
            if response.status_code in (401, 403) and token:
                # The repository is public: a token refused for this read is asked without.
                headers.pop("Authorization")
                response = await client.get(path, headers=headers)
        except httpx.HTTPError as exc:
            raise LookupError(f"GitHub could not be reached for {what} ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise LookupError(f"GitHub could not give {what} (HTTP {response.status_code})")
        try:
            return response.json()
        except ValueError:
            raise LookupError(f"GitHub's answer about {what} was not JSON") from None

    async def read(self, live: str) -> Trunk:
        out = Trunk()
        try:
            async with httpx.AsyncClient(base_url=self._api_url, transport=self._transport, timeout=TIMEOUT_S,
                                         follow_redirects=False) as client:
                ref = await self._get(client, f"/repos/{self.repository}/git/ref/heads/{TRUNK}", "the trunk's head")
                target = ref.get("object") if isinstance(ref, dict) else None
                sha = target.get("sha") if isinstance(target, dict) else None
                if not isinstance(sha, str) or not _SHA.fullmatch(sha):
                    raise LookupError("GitHub did not name the trunk's head")
                out.sha = sha
                if sha == live:
                    return out
                compared = await self._get(client, f"/repos/{self.repository}/compare/{live}...{sha}",
                                           "what changed since the live version")
        except LookupError as exc:
            out.problem = str(exc)
            return out
        compare(out, compared)
        if out.ahead:
            out.acceptance = await asyncio.to_thread(self._acceptance, out.sha)
        return out

    def _acceptance(self, sha: str) -> GateResult:
        """The loop's own gate on exactly `sha`; asked again without the token when GitHub would not
        answer with it (a token without Actions: read), since the repository's runs are public."""
        found = ask(GitHubAcceptance(lambda _repository: self._token(), transport=self._sync_transport),
                    self.repository, sha)
        if found.state is GateState.UNAVAILABLE and self._token():
            found = ask(GitHubAcceptance(lambda _repository: None, transport=self._sync_transport), self.repository, sha)
        return found


def compare(out: Trunk, body: Any) -> None:
    """GitHub's comparison of what runs here with the trunk's head, into `out`: ahead or not, the
    titles of what was merged since (first parents, newest first, the loop's plumbing merges left
    out), and the files, when GitHub listed every one."""
    if not isinstance(body, dict):
        out.problem = "GitHub's comparison was not in the expected shape"
        return
    out.ahead = body.get("status") == "ahead"
    commits = [c for c in body.get("commits") or [] if isinstance(c, dict) and isinstance(c.get("sha"), str)]
    by_sha = {c["sha"]: c for c in commits}
    ahead_by = body.get("ahead_by")
    out.count = ahead_by if isinstance(ahead_by, int) and not isinstance(ahead_by, bool) and ahead_by >= 0 \
        else len(commits)
    chain, at = [], out.sha
    while at in by_sha and len(chain) < len(commits):
        chain.append(by_sha[at])
        parents = by_sha[at].get("parents") or []
        at = parents[0].get("sha") if parents and isinstance(parents[0], dict) else ""
    subjects = [plain(str((c.get("commit") or {}).get("message") or "")) for c in (chain or reversed(commits))]
    out.changes = [s for s in subjects if s and not _PLUMBING.match(s)]
    if out.changes and not out.title:
        out.title = out.changes[0]
    head = by_sha.get(out.sha)
    if head is not None:
        out.title = plain(str((head.get("commit") or {}).get("message") or "")) or out.title
    files = body.get("files")
    listed = [f.get("filename") for f in files if isinstance(f, dict) and isinstance(f.get("filename"), str)] \
        if isinstance(files, list) else None
    # GitHub lists at most 300 files and 250 commits in a comparison: past either, what it touches is not known.
    out.files = listed if listed is not None and len(listed) < 300 and len(commits) < 250 else None


_READER: Any = None
_CACHE: dict[str, tuple[float, Trunk]] = {}


def bind(reader: Any) -> None:
    """Tests: read the trunk from `reader` (anything with `async read(live) -> Trunk`); None: GitHub."""
    global _READER
    _READER = reader
    _CACHE.clear()


async def trunk(live: str, repository: str, *, fresh: bool = False) -> Trunk:
    """The trunk against what runs here, read at most once a minute unless `fresh`."""
    kept = _CACHE.get(live)
    if not fresh and kept is not None and time.monotonic() - kept[0] < CACHE_S:
        return kept[1]
    reader = _READER or GitHubTrunk(repository)
    found = await reader.read(live)
    _CACHE.clear()
    _CACHE[live] = (time.monotonic(), found)
    return found


# ------------------------------------------------------------------ the decisions (pure)


def offer(found: Trunk, *, live: str, release: dict[str, Any]) -> dict[str, Any] | None:
    """The Deploy now card, or None: only when the trunk's head is ahead of what runs here and GitHub
    acceptance is green on exactly that SHA."""
    if not live or not found.sha or found.sha == live or found.ahead is not True:
        return None
    if found.acceptance is None or not found.acceptance.green or found.acceptance.sha != found.sha:
        return None
    changes = found.changes[:CHANGES_SHOWN]
    runs = [run.id for run in found.acceptance.runs]
    why, note = hold(found, release)
    dry = release.get("mode") == "dry_run"
    return {
        "sha": found.sha, "short": found.sha[:8], "title": found.title or found.sha[:8],
        "changes": changes, "more": max(0, len(found.changes) - len(changes)), "count": found.count,
        "acceptance": {"green": True, "runs": runs},
        "hold": {"can": why == "", "why_not": why, "note": note, "dry_run": dry,
                 "label": "Hold to try it (dry run)" if dry else "Hold to deploy"},
        "takes": TAKES,
    }


def hold(found: Trunk, release: dict[str, Any]) -> tuple[str, str]:
    """(why his hold cannot deploy this now, or "", a note to show beside the hold, or "")."""
    if not release.get("installed"):
        return "The release service isn't installed on this server yet, so this one is deployed by hand.", ""
    state = release.get("state") or ""
    if not state:
        return str(release.get("line") or "The release service's status could not be read."), ""
    if state == "off":
        return "The release service is switched off (CLIVE_RELEASE_ENABLED), so this one is deployed by hand.", ""
    if state == "halted":
        return str(release.get("line") or "The release service has stopped until a person looks."), ""
    if state == "would_deploy" and release.get("mode") == "live":
        return f"A deploy is under way now. {release.get('line') or ''}".strip(), ""
    if state == "no_rule" or release.get("rule") != OWNER_WAIVER:
        return ("The release service doesn't take your approval: its rule (CLIVE_RELEASE_RULE) isn't "
                "owner_waiver."), ""
    if found.files is not None:
        guarded = [path for path in found.files if release_facts.guarded(path)]
        if guarded:
            named = ", ".join(guarded[:3]) + (f" and {len(guarded) - 3} more" if len(guarded) > 3 else "")
            return f"This one changes how CLIVE is installed or checked ({named}), so it is deployed by hand.", ""
    looked = release.get("sha") == found.sha
    if looked and release.get("ready_for") == found.sha:
        return "", ""
    if looked and state == "would_deploy" and release.get("mode") == "dry_run":
        return "", ""
    if looked and state in ("waiting", "rolled_back"):
        return str(release.get("line") or ""), ""
    if found.files is None:
        return ("This change is too large for CLIVE to check from here, and the release service hasn't "
                "looked at it yet."), ""
    return "", "The release service checks everything again the moment you hold."


def _stages(reached: dict[str, str], end: str, kept: bool, checking: bool) -> list[dict[str, str]]:
    keys = [key for key, _label in STAGES]
    last = max((keys.index(k) for k in reached if k in keys), default=-1)
    out = []
    for i, (key, label) in enumerate(STAGES):
        if key == "kept":
            state = "lit" if kept else "now" if checking else "dim"
        elif i < last or (i == last and end == "done"):
            state = "lit"
        elif i == last:
            state = "stop" if end in ("rolled_back", "halted", "refused") else "lit" if end == "dry_run" else "now"
        else:
            state = "dim"
        out.append({"key": key, "label": label, "state": state, "at": reached.get(key, "")})
    return out


def progress(approval: dict[str, Any] | None, release: dict[str, Any], *, kept: dict[str, Any] | None,
             process_sha: str, now: float) -> dict[str, Any] | None:
    """The deploy George's latest approval started, as far as it has gone, in words; None without one."""
    if not approval:
        return None
    deploy = release.get("deploy") if isinstance(release.get("deploy"), dict) else None
    ours = deploy if deploy and deploy.get("approval") == approval["approval"] else None
    out = {"sha": approval["sha"], "short": approval["sha"][:8], "approval": approval["approval"],
           "title": approval.get("title") or (ours or {}).get("title") or approval["sha"][:8],
           "given_at": approval["given_at"], "end": "", "line": "", "keep_check": False, "kept_at": "",
           "final": False}
    if ours is None:
        return _not_started(out, approval, release, now)
    reached = {step["stage"]: step["at"] for step in ours.get("steps") or []}
    end = ours.get("end") or ""
    reason = ours.get("reason") or ""
    is_kept = kept is not None and end == "done"
    checking = end == "done" and not is_kept and process_sha == approval["sha"]
    out.update(end=end, stages=_stages(reached, end, is_kept, checking), started_at=reached.get("started", ""))
    if end == "done":
        out["final"] = is_kept
        out["kept_at"] = str((kept or {}).get("kept_at") or "")
        out["keep_check"] = checking
        out["line"] = ("Deployed and kept: your phone got through on the new build." if is_kept else
                       "Deployed. Checking that your phone gets through on the new build…" if checking else
                       "Deployed. CLIVE is restarting onto the new build…")
    elif end == "rolled_back":
        out.update(final=True, line=f"Rolled back: {reason or 'a check after the install failed'}. "
                                    "Production is back on the version it ran before.")
    elif end == "halted":
        out.update(final=True, line=f"Stopped part way: {reason or 'the rollback did not finish'}. The release "
                                    "service has stopped until a person looks at production.")
    elif end == "refused":
        out.update(final=True, line=f"Not deployed: {reason or 'a check before the change failed'}. Nothing was "
                                    "changed.")
    elif end == "dry_run":
        out.update(final=True, line="Dry run: the release service checked everything and would deploy it now. "
                                    "Nothing was changed.")
    else:
        current = next((label for key, label in reversed(STAGES) if key in reached), "Started")
        out["line"] = {"Started": "Started.", "Checks": "Checking production before anything changes…",
                       "Installing": "Installing the new build…",
                       "Health": "Installed. Checking CLIVE's health on the new build…"}.get(current, "Started.")
    return out


def _not_started(out: dict[str, Any], approval: dict[str, Any], release: dict[str, Any], now: float) -> dict[str, Any]:
    """His approval, before the release service has started a deploy for it."""
    out["stages"] = _stages({}, "", False, False)
    looked_after = (release.get("sha") == approval["sha"] and release.get("state") == "waiting"
                    and (release.get("at") or "") > approval["given_at"])
    if looked_after:
        # Final only after a minute: a tick that began before his approval landed writes its own word
        # first, and then looks again (app/release/service.py), so the page keeps asking meanwhile.
        out.update(end="not_started", final=now - approval["given"] > 60,
                   line=f"The release service looked and didn't deploy it. {release.get('line') or ''}".strip())
    elif now > approval["expires"]:
        out.update(end="expired", final=True, line="Your approval expired before the release service started it "
                                                   "(an approval lasts ten minutes). Nothing was deployed.")
    elif now - approval["given"] > 60:
        out["line"] = ("Approved. The release service hasn't started yet; without its instant trigger it starts "
                       "within five minutes.")
    else:
        out["line"] = "Approved. Starting the release service…"
    return out
