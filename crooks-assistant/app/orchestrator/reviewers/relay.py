"""Reviewer drivers that exist today, and the one that does not.

``GptUnavailable`` is the programmatic GPT reviewer as it actually stands: there
is none. No OpenAI credential is provisioned for CLIVE, no supported programmatic
ChatGPT review mechanism has been verified, and calling the OpenAI API would be a
new secret and new pay-as-you-go spend, both owner decisions. It reports that gap
through ``availability`` so the dispatcher blocks truthfully instead of dispatching
a review nobody will perform. It never falls back to a Claude process: the
principal registry records ``claude`` with ``may_review: false`` because every
Claude session on the host is one principal.

``RelayReviewer`` is the courier path, named as such (``courier = True``): the
dispatcher writes the exact-SHA packet to an outbox and waits for a typed
``clive.review_result.v1`` JSON file that a person carries back. It is the
bootstrap fallback, and a task reviewed through it is never evidence that the
no-courier milestone has been met.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import ReviewContext

__all__ = ["GptUnavailable", "RelayReviewer", "GPT_GAP"]

GPT_GAP = (
    "no programmatic GPT reviewer exists for CLIVE: no OpenAI credential is provisioned, no supported "
    "programmatic ChatGPT review mechanism has been verified, and the OpenAI API would be a new secret and "
    "new pay-as-you-go spend (owner decisions); claude may not review (registry may_review false: one "
    "principal for every Claude session); owner decision required: provision a GPT reviewer mechanism, "
    "register another independent reviewer principal, or run this objective with --reviewer relay (courier)"
)


class GptUnavailable:
    principal_id = "gpt"
    mechanism = "none"
    courier = False

    def availability(self) -> tuple[bool, str]:
        return False, GPT_GAP

    def start(self, ctx: ReviewContext) -> None:  # pragma: no cover - never available
        raise RuntimeError(GPT_GAP)

    def poll(self, ctx: ReviewContext) -> list[bytes]:  # pragma: no cover - never available
        return []


class RelayReviewer:
    """Packet out to a file, typed result back from a file. A person carries both."""

    mechanism = "relay"
    courier = True

    def __init__(self, root: Path, *, principal_id: str = "gpt") -> None:
        self.root = Path(root)
        self.principal_id = principal_id

    def _dir(self, ctx: ReviewContext) -> Path:
        return self.root / ctx.task_id / ctx.attempt_id

    def outbox(self, ctx: ReviewContext) -> Path:
        return self._dir(ctx) / f"dispatch.{ctx.dispatch_seq}.packet.md"

    def inbox(self, ctx: ReviewContext) -> Path:
        return self._dir(ctx) / f"dispatch.{ctx.dispatch_seq}.results"

    def availability(self) -> tuple[bool, str]:
        return True, f"relay: a person carries the packet to {self.principal_id} and the typed result back"

    def start(self, ctx: ReviewContext) -> None:
        out = self.outbox(ctx)
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            shutil.copyfile(ctx.packet_path, out)

    def poll(self, ctx: ReviewContext) -> list[bytes]:
        inbox = self.inbox(ctx)
        if not inbox.is_dir():
            return []
        return [p.read_bytes() for p in sorted(inbox.glob("*.json"))]

    def submit(self, ctx: ReviewContext, payload: bytes, *, stamp: str) -> Path:
        """Place a carried-back result where ``poll`` finds it: atomic, one new file per submission."""
        inbox = self.inbox(ctx)
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{stamp}.json"
        if path.exists():
            raise FileExistsError(f"{path} already exists")
        tmp = inbox / f".{stamp}.tmp"
        tmp.write_bytes(payload)
        os.replace(tmp, path)
        return path
