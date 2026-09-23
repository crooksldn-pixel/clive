"""The evidence bundle: everything the investigation reads, with where it came from and when.

Every item is a fact from one source at one moment, kept as the source gave it (bounded) and
named by a reference the internal summary cites, so the owner can check any conclusion against
the source system. The bundle is JSON: gathered live from the store, the inbox and the knowledge
base, or loaded from a capture, and the investigation cannot tell the difference, which is what
makes a captured real case a fair acceptance test and a synthetic one a fair unit test.

The readers are injected: functions that answer the four questions the bundle asks. The live
ones are the application's own read-only tools (`app/support/live.py`); nothing here holds a
client, and nothing here can write.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.support.enquiry import Enquiry

MAX_CANDIDATES = 5
MAX_THREADS = 3
MAX_MESSAGES = 6
MAX_BODY = 1500
MAX_POLICY_LINE = 400

FindOrder = Callable[[str], Awaitable[dict[str, Any]]]
OrderDetail = Callable[[str], Awaitable[dict[str, Any]]]
ThreadsFor = Callable[..., Awaitable[dict[str, Any]]]
ReadThread = Callable[[str], Awaitable[dict[str, Any]]]

# The knowledge-base lines the investigation may quote, by name: the section heading each
# lives under, and the phrase that picks the line. A line is quoted as it is in the file.
_POLICY_LINES: tuple[tuple[str, str, str, str], ...] = (
    ("dispatch", "shipping-policy.md", "## When it ships", "Orders placed before"),
    ("delivery_windows", "shipping-policy.md", "## When it lands", "Once dispatched"),
    ("tracking_emailed", "shipping-policy.md", "## When it lands", "Tracking is emailed"),
    ("lost_or_damaged", "shipping-policy.md", "## Lost or damaged in transit", "That is on us"),
    ("duties", "shipping-policy.md", "## Overseas duties", "Import duties"),
    ("returns", "cs-rules.md", "## The three questions", "Wrong size or changed"),
    ("photo", "cs-rules.md", "## Tone and promise", "To help fastest"),
    ("reply_time", "cs-rules.md", "## Tone and promise", "We reply within"),
    ("visibility", "cs-rules.md", "## What the assistant", "more than sixty days old"),
    ("discretion", "cs-rules.md", "## Discretion", "The owner has not yet written"),
)


@dataclass
class EvidenceBundle:
    enquiry: dict[str, Any]
    gathered_at: str
    sources: dict[str, str] = field(default_factory=dict)
    order_search: dict[str, Any] | None = None
    order: dict[str, Any] | None = None
    threads: list[dict[str, Any]] = field(default_factory=list)
    policy: dict[str, dict[str, str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ serialisation
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "clive.support_evidence_bundle.v1",
            "enquiry": self.enquiry,
            "gathered_at": self.gathered_at,
            "sources": self.sources,
            "order_search": self.order_search,
            "order": self.order,
            "threads": self.threads,
            "policy": self.policy,
            "problems": self.problems,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceBundle:
        if data.get("schema") != "clive.support_evidence_bundle.v1":
            raise ValueError("not a clive.support_evidence_bundle.v1 document")
        return cls(
            enquiry=dict(data.get("enquiry") or {}),
            gathered_at=str(data.get("gathered_at") or ""),
            sources=dict(data.get("sources") or {}),
            order_search=data.get("order_search"),
            order=data.get("order"),
            threads=list(data.get("threads") or []),
            policy=dict(data.get("policy") or {}),
            problems=list(data.get("problems") or []),
        )

    @property
    def parsed_enquiry(self) -> Enquiry:
        return Enquiry.from_dict(self.enquiry)

    # ------------------------------------------------------------------ refs
    @property
    def order_ref(self) -> str:
        return f"shopify:order:{(self.order or {}).get('order_id') or '?'}"

    @property
    def search_ref(self) -> str:
        return f"shopify:order_search:{(self.order_search or {}).get('query') or '?'}"

    @staticmethod
    def thread_ref(thread: dict[str, Any]) -> str:
        return f"gmail:thread:{thread.get('thread_id') or '?'}"

    @staticmethod
    def policy_ref(name: str) -> str:
        return f"kb:{name}"

    def evidence_index(self) -> list[dict[str, Any]]:
        """Every piece of evidence, one line each, so the owner can check a conclusion."""
        out: list[dict[str, Any]] = []
        if self.order_search is not None:
            orders = self.order_search.get("orders") or []
            out.append({"ref": self.search_ref, "source": "shopify", "kind": "order_search",
                        "summary": f"search {self.order_search.get('query')!r}: {len(orders)} order(s) matched"
                                   + (" (ambiguous customers)" if self.order_search.get("ambiguous") else "")})
        if self.order:
            o = self.order
            out.append({"ref": self.order_ref, "source": "shopify", "kind": "order",
                        "summary": f"order {o.get('order_number')}: {o.get('fulfillment')}, {o.get('payment')}, "
                                   f"placed {o.get('placed_at')}, {len(o.get('fulfillments') or [])} fulfilment(s)"})
            history = o.get("history") if isinstance(o.get("history"), dict) else None
            if history:
                out.append({"ref": f"{self.order_ref}#history", "source": "shopify", "kind": "customer_history",
                            "summary": f"customer history: {history.get('orders')} order(s)"})
        for t in self.threads:
            out.append({"ref": self.thread_ref(t), "source": "gmail", "kind": "thread",
                        "summary": f"thread {t.get('subject')!r}: {t.get('message_count', len(t.get('messages') or []))} message(s), "
                                   f"latest {t.get('latest_direction')}, match {t.get('match')}"})
        if self.sources.get("gmail") == "live":
            out.append({"ref": "gmail:search", "source": "gmail", "kind": "thread_search",
                        "summary": f"inbox searched for the customer's address and the order number (last sixty days): {len(self.threads)} thread(s) read"})
        for name, line in self.policy.items():
            out.append({"ref": self.policy_ref(name), "source": "kb", "kind": "policy",
                        "summary": f"{line.get('file')}: {line.get('text')}"})
        out.append({"ref": "enquiry", "source": "enquiry", "kind": "enquiry",
                    "summary": f"the customer's message ({self.enquiry.get('kind')})"})
        return out


# ---------------------------------------------------------------------- policy


def policy_lines(kb_dir: Path) -> dict[str, dict[str, str]]:
    """The named knowledge-base lines, quoted as they are in the files."""
    out: dict[str, dict[str, str]] = {}
    cache: dict[str, str] = {}
    for name, filename, heading, phrase in _POLICY_LINES:
        if filename not in cache:
            path = Path(kb_dir) / filename
            try:
                cache[filename] = path.read_text(encoding="utf-8")
            except OSError:
                cache[filename] = ""
        text = cache[filename]
        if not text:
            continue
        section = _section(text, heading)
        for raw in section.splitlines():
            line = raw.strip().lstrip("-").strip()
            if phrase.lower() in line.lower():
                out[name] = {"file": filename, "heading": heading.lstrip("# ").strip(), "text": _joined(section, raw)[:MAX_POLICY_LINE]}
                break
    return out


def _section(text: str, heading: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _joined(section: str, first_line: str) -> str:
    """A bullet and its continuation lines, as one sentence."""
    lines = section.splitlines()
    try:
        index = lines.index(first_line)
    except ValueError:
        return first_line.strip().lstrip("-").strip()
    parts = [lines[index].strip().lstrip("-").strip()]
    for line in lines[index + 1:]:
        if not line.strip() or line.lstrip().startswith("-") or line.lstrip().startswith("#"):
            break
        parts.append(line.strip())
    return " ".join(parts)


# ---------------------------------------------------------------------- gather


def _bounded_thread(thread: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    messages = []
    for m in (thread.get("messages") or [])[-MAX_MESSAGES:]:
        if not isinstance(m, dict):
            continue
        messages.append({
            "message_id": str(m.get("message_id") or ""),
            "from_email": str(m.get("from_email") or "").strip().lower(),
            "date": str(m.get("date") or ""),
            "outbound": bool(m.get("outbound")),
            "body": str(m.get("body") or "")[:MAX_BODY],
        })
    return {
        "thread_id": str(thread.get("thread_id") or summary.get("thread_id") or ""),
        "subject": str(summary.get("subject") or (messages and thread.get("subject")) or ""),
        "from_email": str(summary.get("from_email") or "").strip().lower(),
        "date": str(summary.get("date") or ""),
        "authenticated": bool(summary.get("authenticated")),
        "match": str(summary.get("match") or ""),
        "message_count": int(thread.get("message_count") or len(messages)),
        "latest_direction": str(thread.get("latest_direction") or ("none" if not messages else ("outbound" if messages[-1]["outbound"] else "inbound"))),
        "awaiting_reply": bool(thread.get("awaiting_reply", bool(messages) and not messages[-1]["outbound"])),
        "messages": messages,
    }


async def gather(
    enquiry: Enquiry,
    *,
    find_order: FindOrder,
    order_detail: OrderDetail,
    threads_for: ThreadsFor | None,
    read_thread: ReadThread | None,
    kb_dir: Path | None,
    now: Callable[[], datetime] | None = None,
) -> EvidenceBundle:
    """Read what the enquiry points at. Every reader failure is a named problem, never a
    silent gap, and nothing is inferred here: the bundle is what was read."""
    stamp = (now() if now else datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = EvidenceBundle(enquiry=enquiry.as_dict(), gathered_at=stamp)

    # 1. Which order: by the number the customer gave, else by the address they wrote from.
    queries: list[str] = list(enquiry.order_numbers[:2])
    if enquiry.sender_email:
        queries.append(enquiry.sender_email)
    queries.extend(enquiry.emails_mentioned[:1])
    search: dict[str, Any] | None = None
    for query in queries:
        try:
            result = await find_order(query)
        except Exception as exc:  # noqa: BLE001 — the store not answering is evidence, not a crash
            bundle.problems.append(f"order search {query!r} failed: {type(exc).__name__}: {str(exc)[:160]}")
            bundle.sources["shopify"] = f"unavailable: {str(exc)[:120]}"
            continue
        bundle.sources.setdefault("shopify", "live")
        orders = list(result.get("orders") or [])[:MAX_CANDIDATES]
        search = {**result, "query": query, "orders": orders}
        if orders:
            break
    if not queries:
        bundle.problems.append("no identifier in the enquiry: no order number and no sender address")
    bundle.order_search = search

    # 2. The order itself, when exactly one candidate stands.
    chosen = _choose(enquiry, search)
    if chosen:
        try:
            bundle.order = await order_detail(str(chosen.get("order_id")))
        except Exception as exc:  # noqa: BLE001
            bundle.problems.append(f"order detail failed: {type(exc).__name__}: {str(exc)[:160]}")

    # 3. The conversation: from the customer's own address, or naming the order.
    customer_email = str((bundle.order or {}).get("customer_email") or "").strip().lower() or enquiry.sender_email
    digits = _digits((bundle.order or {}).get("order_number")) or (enquiry.order_numbers[0] if enquiry.order_numbers else "")
    if threads_for is None or read_thread is None:
        bundle.sources["gmail"] = "not configured"
    elif customer_email or digits:
        try:
            found = await threads_for(sender=customer_email, terms=[digits] if digits else [])
        except Exception as exc:  # noqa: BLE001
            found = {"available": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}", "threads": []}
        if not found.get("available", True):
            bundle.sources["gmail"] = f"unavailable: {str(found.get('reason') or '')[:120]}"
            bundle.problems.append(f"inbox unavailable: {str(found.get('reason') or '')[:160]}")
        else:
            bundle.sources["gmail"] = "live"
            for summary in (found.get("threads") or [])[:MAX_THREADS]:
                thread_id = str(summary.get("thread_id") or "")
                if not thread_id:
                    continue
                try:
                    thread = await read_thread(thread_id)
                except Exception as exc:  # noqa: BLE001
                    bundle.problems.append(f"thread {thread_id} could not be read: {type(exc).__name__}")
                    continue
                matched = _match(summary, customer_email=customer_email, digits=digits)
                bundle.threads.append(_bounded_thread(thread, {**summary, "match": matched}))

    # 4. The policy lines the reply may quote.
    if kb_dir is not None:
        bundle.policy = policy_lines(kb_dir)
        bundle.sources["kb"] = str(kb_dir)
    return bundle


def _digits(number: Any) -> str:
    return str(number or "").rsplit("-", 1)[-1].lstrip("#").strip()


def _choose(enquiry: Enquiry, search: dict[str, Any] | None) -> dict[str, Any] | None:
    """The one candidate the evidence supports, or nothing: never a guess between two."""
    if not search:
        return None
    orders = [o for o in search.get("orders") or [] if isinstance(o, dict)]
    if not orders:
        return None
    if enquiry.order_numbers:
        named = [o for o in orders if _digits(o.get("order_number")) in enquiry.order_numbers]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            return None
    if len(orders) == 1 and not search.get("ambiguous"):
        return orders[0]
    return None


def _match(summary: dict[str, Any], *, customer_email: str, digits: str) -> str:
    sender = str(summary.get("from_email") or "").strip().lower()
    text = f"{summary.get('subject', '')} {summary.get('snippet', '')}"
    mentions = bool(digits) and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", text) is not None
    matches = bool(customer_email) and sender == customer_email
    if matches and mentions:
        return "both"
    if matches:
        return "sender"
    if mentions:
        return "order_number"
    return "none"
