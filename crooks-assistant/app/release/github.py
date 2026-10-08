"""GitHub, as far as the release service may use it: read the trunk, read acceptance, push its records.

Why it exists: the brief's least privilege. The service reads clive/trunk, the GitHub `acceptance`
run on one exact SHA, and a reviewer's record branch; the only thing it ever writes is a
claude/deploy-<sha8>-record branch. Every push goes through `record_refspec`, which refuses any
other ref, so no bug elsewhere can make it push the trunk, a control branch or a tag.

The token is the service's own (a fine-grained token for this one repository: Actions read,
Contents read and write, docs/RELEASE_SERVICE.md). systemd hands it to the unit as an encrypted
credential; it is read from that file at start, kept in a `Token`, and reaches git only through an
environment variable a credential helper reads, never an argument (a process's arguments are
readable by every user on the host). `Token.scrub` takes it out of any text before that text is
printed, recorded or pushed. GitHub itself accepts the token for Contents writes on any branch: the
narrowing to record branches is this file's, and the docs say so plainly.

The acceptance question is app/orchestrator/github_acceptance.py's, reused as it is: green only
when every acceptance run for the SHA completed with success and its acceptance job ran on it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from app.orchestrator.github_acceptance import AcceptanceChecks, GateResult, GitHubAcceptance, ask

TOKEN_ENV = "CLIVE_RELEASE_GIT_TOKEN"
# The helper reads the token from the environment git was given; the argument holds only its name.
_HELPER = '!f() { echo username=x-access-token; echo "password=${' + TOKEN_ENV + '}"; }; f'
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RECORD_BRANCH = re.compile(r"^claude/deploy-[0-9a-f]{8}-record$")


def git_url(repository: str) -> str:
    return f"https://github.com/{repository}.git"


def review_branch(sha: str) -> str:
    return f"claude/review-{sha[:8]}-record"


def record_branch(sha: str) -> str:
    return f"claude/deploy-{sha[:8]}-record"


def record_refspec(commit: str, branch: str) -> str:
    """The one refspec the service may push: an exact commit to a claude/deploy-<sha8>-record branch."""
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        raise ValueError("a record is pushed as an exact commit")
    if not isinstance(branch, str) or not _RECORD_BRANCH.fullmatch(branch):
        raise ValueError("the release service pushes only claude/deploy-<sha8>-record branches")
    return f"{commit}:refs/heads/{branch}"


class Token:
    """The service's GitHub token, or none. Its value never appears in repr, str or an argument."""

    def __init__(self, value: str | None) -> None:
        cleaned = (value or "").strip()
        self._value = cleaned or None

    @property
    def present(self) -> bool:
        return self._value is not None

    def __repr__(self) -> str:
        return "Token(present)" if self.present else "Token(none)"

    __str__ = __repr__

    def env(self) -> dict[str, str]:
        return {TOKEN_ENV: self._value} if self._value else {}

    def git_config(self) -> list[str]:
        """git -c options: no helper the host has configured, and ours only when there is a token."""
        options = ["-c", "credential.helper="]
        if self._value:
            options += ["-c", f"credential.helper={_HELPER}"]
        return options

    def source(self) -> Callable[[str], str | None]:
        return lambda _repository: self._value

    def scrub(self, text: str) -> str:
        if not self._value or not isinstance(text, str):
            return text
        return text.replace(self._value, "[the release token]")


def read_token(name: str) -> Token:
    """The token systemd decrypted for this unit ($CREDENTIALS_DIRECTORY/<name>), or none."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if not folder or "/" in name or not name:
        return Token(None)
    try:
        return Token((Path(folder) / name).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return Token(None)


def acceptance(token: Token, repository: str, sha: str, gate: AcceptanceChecks | None = None) -> GateResult:
    """GitHub's acceptance verdict on exactly `sha`; a gate that cannot answer is never green."""
    return ask(gate or GitHubAcceptance(token.source()), repository, sha)
