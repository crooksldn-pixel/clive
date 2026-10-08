"""What a channel must provide to plug into messaging, and the list of channels that have.

Why it exists: WeCom was the first channel; WhatsApp (app/messaging/whatsapp.py) and Instagram's
direct messages (app/messaging/instagram.py) are the next. Each is one adapter with the same jobs,
so the public door (app/routes/hooks.py), the store, the tools and the Connections card never need
to know which app a message came through:

    verify_inbound   is this request really from the channel? (signature first, then the
                     channel's own checks); returns what it carried, or raises Refused. The
                     request's headers are passed too: Meta signs in X-Hub-Signature-256
    carried          what a verified callback carries itself, read with no call (a team member's
                     message to WeCom's app; everything WhatsApp and Instagram send: messages, and
                     what became of the ones CLIVE sent): stored at the door, before it answers,
                     so a busy server never loses one (app/messaging/ingest.py)
    receive          the rest of what a verified callback stands for, after the door has
                     answered (for WeCom's customer service: reading them with sync_msg)
    send             one text to one thread; returns the channel's own message id only when
                     its API confirmed the send, and raises (with `refused` and plain words)
                     otherwise; why_not says beforehand why the channel would not take it, and
                     too_long whether the words fit what it takes
    reply_window     how long the channel will still take a reply in a thread, in plain words
    probe            what this channel's account can do right now, route by route, in plain
                     words, with exactly what to switch on where it can't
    max_body         the largest callback body the door reads for this channel (WeCom's are
                     small; Meta's batches may be up to 3 MB)

An adapter never logs a message, a name or a contact id, and never sends without being asked by
the action engine after the owner's hold (app/tools/messaging_tools.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.messaging.models import Message, Thread


class Refused(Exception):
    """An inbound request that is not the channel's. `why` is a short kind for the count of
    refusals (signature, replay, size, crypto, unconfigured), never anything the request said."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class Inbound:
    """A verified inbound request. `echo` is the answer to a URL check (WeCom's GET, Meta's
    hub.challenge); otherwise `fields` is the decrypted event (WeCom) and `payload` the verified
    JSON (Meta), and `key` is what makes a repeat of it recognisable."""

    channel: str
    echo: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    key: str = ""
    timestamp: float = 0.0
    payload: Any = None


@dataclass(frozen=True)
class Received:
    """One message the channel delivered, and the thread it belongs to."""

    thread: Thread
    message: Message


@dataclass(frozen=True)
class Failure:
    """The channel said later that a message it had accepted did not arrive."""

    thread: Thread
    remote_id: str
    reason: str


@dataclass(frozen=True)
class Delivery:
    """The channel said a message CLIVE's account sent reached them ("delivered") or was seen
    ("read"). `and_before`: the channel names only the newest message read (Instagram)."""

    thread: Thread
    remote_id: str
    state: str
    and_before: bool = False


@dataclass(frozen=True)
class Route:
    """One way a channel can reach people, as the owner is told about it."""

    key: str              # "kf", "member", "external_contact", "archive", "appchat", "callback",
                          # "number", "replies", "templates", "conversations", "human_agent"
    label: str            # "WeChat contacts, through customer service"
    state: str            # "ready", "off" (he can switch it on), "not_used" (CLIVE does not use it), "unknown"
    can: str              # what it does, plainly
    switch_on: str = ""   # exactly what to do in the channel's console when it is off

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "state": self.state, "can": self.can, "switch_on": self.switch_on}


class Adapter(Protocol):
    channel: str
    label: str
    max_body: int

    def configured(self) -> bool: ...

    def verify_inbound(self, method: str, query: Mapping[str, str], body: bytes,
                       headers: Mapping[str, str] | None = None) -> Inbound: ...

    def carried(self, inbound: Inbound) -> list[Received | Failure | Delivery]: ...

    async def receive(self, inbound: Inbound) -> list[Received | Failure]: ...

    async def why_not(self, thread: Thread) -> str: ...

    def too_long(self, text: str) -> str: ...

    def reply_window(self, thread: Thread, now: float | None = None) -> str: ...

    async def send(self, thread: Thread, text: str, *, client_id: str) -> str: ...

    async def names(self, threads: list[Thread]) -> dict[str, str]: ...

    async def probe(self) -> list[Route]: ...


ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    ADAPTERS[adapter.channel] = adapter
    return adapter


def get(channel: str) -> Adapter | None:
    return ADAPTERS.get(str(channel or ""))


def any_configured() -> bool:
    """Whether any channel has its keys stored: the messaging tools are offered only then."""
    return any(adapter.configured() for adapter in ADAPTERS.values())
