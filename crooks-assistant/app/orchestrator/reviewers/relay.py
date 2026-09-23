"""Reviewer drivers that exist today, and the one that does not.

``GptUnavailable`` stands in when the dispatcher has no OpenAI key file: the
programmatic reviewer (``gpt.GptResponsesReviewer``) exists, but without its
host-side credential it cannot run. It reports that gap
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
    "no programmatic GPT reviewer is configured for this dispatcher: it was started without "
    "--gpt-api-key-file (the OpenAI Responses API reviewer, reviewers/gpt.py); claude may not review "
    "(registry may_review false: one principal for every Claude session); provide the host-side key file, "
    "register another independent reviewer principal, or run this objective with --reviewer relay (courier)"
)


class GptUnavailable:
    principal_id = "gpt"
    mechanism = "none"
    courier = False

    def availability(self) -> tuple[bool, str]:
        return False, GPT_GAP

    def start(self, ctx: ReviewContext) -> None:
        """Nothing to launch. Reached only for a review already dispatched to gpt before this dispatcher
        lost its key file (a restart without it); the task waits, and a dispatcher with the key picks it up."""

    def poll(self, ctx: ReviewContext) -> list[bytes]:
        return []

    def problem(self, ctx: ReviewContext) -> str:
        return GPT_GAP


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
