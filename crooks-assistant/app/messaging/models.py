"""A thread and a message, as every channel's adapter hands them to the core and the store keeps
them. Plain dataclasses, serialised with to_dict and read back with from_dict, so the store's file
is exactly these fields and nothing a channel invented.

A message carries its original words, the language they were detected as, and — for words not
in English — an English translation labelled as a machine translation, or a note that the
translation is missing. Outgoing messages carry the English and the Chinese they were drafted in,
what was actually sent, and the channel's own message id once the channel confirmed it.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any

MACHINE_TRANSLATION = "machine translation"
DIRECTIONS = ("in", "out")
# How a message came: from the contact; from CLIVE, on the owner's hold; or typed by a person in
# the channel's own app (a WeCom customer-service agent), which CLIVE records but did not send.
ORIGINS = ("contact", "clive", "person")
STATUSES = ("received", "sent", "failed")
TRANSLATION_STATES = ("done", "pending", "missing", "not_needed")


def new_message_id() -> str:
    return f"m_{secrets.token_hex(8)}"


def chat_id_for(channel: str, route: str, account: str, contact: str) -> str:
    """One thread per (channel, route, account, contact), named the same way every time it is
    met, so a callback and a read agree on which thread a message belongs to without a lookup.
    A digest, so the id carries no contact id of the channel's."""
    digest = hashlib.sha256(f"{channel}|{route}|{account}|{contact}".encode()).hexdigest()
    return f"chat_{digest[:20]}"


def _known(cls, data: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


@dataclass
class Message:
    message_id: str
    chat_id: str
    direction: str                     # "in" or "out"
    origin: str                        # see ORIGINS
    text: str                          # the original words, as received or as sent
    at: float                          # when the channel says it was sent
    language: str = ""                 # "zh", "en", "other", "" when there are no words
    english: str = ""                  # the words in English (the text itself when it is English)
    translation: str = ""              # MACHINE_TRANSLATION when `english` came from a model
    translation_state: str = "not_needed"
    kind: str = "text"                 # text, image, file, voice, ... (only text carries words)
    status: str = "received"
    remote_id: str = ""                # the channel's own id for it (WeCom's msgid)
    client_id: str = ""                # CLIVE's id for an outgoing one, before the channel answered
    chinese: str = ""                  # an outgoing message's Chinese, as drafted
    fail_reason: str = ""
    stored_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(**_known(cls, data))


@dataclass
class Thread:
    chat_id: str
    channel: str                       # "wecom"
    route: str                         # how the channel reaches them: "kf" (WeChat, through
                                       # customer service) or "member" (someone in the company)
    account: str                       # the channel account it is on (WeCom: open_kfid or agent id)
    contact: str                       # the channel's id for them (external_userid or userid)
    who: str = ""                      # the name the channel gives them (a WeChat nickname)
    created_at: float = field(default_factory=time.time)
    last_at: float = 0.0
    last_in_at: float = 0.0            # their last message: the 48-hour clock starts here
    last_in_id: str = ""
    sends_since_in: int = 0            # replies CLIVE sent since their last message (WeChat allows 5)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Thread:
        return cls(**_known(cls, data))

    @property
    def channel_key(self) -> str:
        """How a person's card names this contact (app/people/store.py `channels`)."""
        return f"{self.channel}:{self.route}:{self.contact}"
