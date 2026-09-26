"""Two read-only Gmail tools.

There is no send, no draft, no label, no trash and no modify anywhere in this module, and the
scope the client requests cannot perform any of them. The gate refuses those verbs by name as
well, so a write path would have to defeat both to exist.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from email.utils import parseaddr
from typing import Any

from app.clients.gmail import GmailAuthRequired, GmailClient
from app.logging.turnlog import redact_text
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.gmail_tools")

MAX_RESULTS = 25
# The operator's default tool budget is 8 s; a search is a listing, a batched fetch and, on a
# cold start, a credential refresh. Its own ceiling, still a hard one.
GMAIL_TIMEOUT_S = 15.0
MAX_BODY_CHARS = 1500
MAX_THREAD_MESSAGES = 12

# Gmail categories are ML heuristics and do misclassify genuine customer replies, so this is a
# base filter, not a verdict. Everything that survives it is flagged rather than hidden.
BASE_QUERY = "category:primary -from:me -in:chats -in:trash -in:spam"

_BULK_HEADERS = ("list-unsubscribe", "list-id", "precedence", "auto-submitted", "list-post")
_BULK_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?@|mailer@|bounce|newsletter|marketing@)",
    re.I,
)

_client: GmailClient | None = None
# Set by the runtime once Shopify is up. Optional by design: Gmail must keep working when
# Shopify is down, just with a less useful known_customer flag.
_customer_lookup = None


def bind(client: GmailClient, customer_lookup=None) -> None:
    global _client, _customer_lookup
    _client = client
    _customer_lookup = customer_lookup


def _c() -> GmailClient:
    if _client is None:
        raise ToolError("Gmail is not configured on this backend.")
    return _client


def _describe(exc: Exception) -> str:
    """googleapiclient errors embed the request URL — including the search query, which may
    contain an email address the owner typed. Strip URLs, then redact what is left."""
    text = re.sub(r"https?://\S+", "[url]", str(exc))
    return redact_text(text)[:200]


def _is_auth_failure(exc: Exception) -> bool:
    try:
        from google.auth.exceptions import RefreshError
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, (RefreshError, GmailAuthRequired)) or "invalid_grant" in str(exc)


def _headers(message: dict) -> dict[str, str]:
    """Header name → value, the FIRST of each: the receiving server's own Authentication-Results
    is the outermost, and a sender can append one of their own further in."""
    out: dict[str, str] = {}
    for h in (message.get("payload", {}).get("headers") or []):
        out.setdefault(str(h.get("name", "")).lower(), str(h.get("value", "")))
    return out


def _is_bulk(headers: dict[str, str]) -> bool:
    if any(h in headers for h in _BULK_HEADERS):
        return True
    return bool(_BULK_SENDER.search(headers.get("from", "")))


async def _known_customer(email: str) -> bool | None:
    """True/False if Shopify could be asked, None if it could not. None is not False."""
    if not email or _customer_lookup is None:
        return None
    try:
        return await _customer_lookup(email)
    except Exception as exc:  # noqa: BLE001 — Shopify being down must not break Gmail
        log.warning("customer cross-reference unavailable: %s", exc)
        return None


def _fetch_batched(service, stubs, get_request) -> list[dict] | None:
    """Fetch every message in one batch HTTP request. None when the client cannot batch (a
    test double, an old library), in which case the caller fetches one by one."""
    new_batch = getattr(service, "new_batch_http_request", None)
    if not stubs or new_batch is None or not callable(new_batch):
        return None
    results: dict[str, dict] = {}

    def collect(request_id, response, exception):
        if exception is not None:
            log.warning("could not fetch message %s: %s", request_id, _describe(exception))
        elif isinstance(response, dict):
            results[request_id] = response

    try:
        batch = new_batch(callback=collect)
        for stub in stubs:
            batch.add(get_request(stub), request_id=stub["id"])
        batch.execute()
    except Exception as exc:  # noqa: BLE001 — fall back to the one-by-one path
        log.warning("batched fetch failed (%s); fetching one by one", _describe(exc))
        return None
    return [results[stub["id"]] for stub in stubs if stub["id"] in results]


def _decode_part(part: dict) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    try:
        # Padded before decoding. Gmail's `body.data` is base64url and its padding is not
        # guaranteed — an unpadded string is a length that is not a multiple of four, which
        # `urlsafe_b64decode` raises on, which this except swallowed, which meant the message
        # HAD NO BODY. Every fixture message reads that way (experience/fixtures/data.py
        # encodes with the padding stripped, exactly as the API may), so every email body read
        # offline was empty: "what are they waiting for" had nothing to read but the subject.
        return base64.urlsafe_b64decode(data.encode() + b"=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _extract_body(payload: dict, *, limit: int = MAX_BODY_CHARS) -> str:
    """Walk a multipart MIME tree for text/plain, falling back to stripped HTML."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            plain.append(_decode_part(part))
        elif mime == "text/html":
            html.append(_decode_part(part))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    text = "\n".join(t for t in plain if t).strip()
    if not text and html:
        text = re.sub(r"<[^>]+>", " ", "\n".join(html))
        text = re.sub(r"\s+", " ", text).strip()
    # Quoted history adds length and no information to a spoken answer.
    text = re.split(r"\nOn .{0,80} wrote:\n|\n-{2,} ?Original Message", text)[0].strip()
    if len(text) > limit:
        text = text[:limit] + f"… [truncated, {len(text) - limit} more chars]"
    return text


_METADATA_HEADERS = [
    "From", "Reply-To", "Subject", "Date", "List-Unsubscribe", "List-Id",
    "Precedence", "Auto-Submitted", "List-Post", "Authentication-Results",
]

_AUTH_CLAUSE = re.compile(r"\b(dmarc|dkim|spf)=(pass|fail|none|neutral|softfail|temperror|permerror|policy)\b([^;]*)", re.I)
_SIGNER = re.compile(r"header\.(?:d|i)=@?([A-Za-z0-9.-]+)", re.I)


def authenticated(headers: dict[str, str], from_email: str = "") -> bool:
    """Whether the receiving server's own Authentication-Results vouch for the From address:
    a DMARC pass, or a DKIM pass whose signing domain is the From domain (or a parent of
    it). SPF alone proves the envelope sender's relay, not the From header a person reads,
    and is never enough. A From header is written by the sender; this line is Gmail's."""
    domain = from_email.rsplit("@", 1)[-1].strip().lower() if "@" in str(from_email or "") else ""
    for method, result, rest in _AUTH_CLAUSE.findall(headers.get("authentication-results", "")):
        if result.lower() != "pass":
            continue
        if method.lower() == "dmarc":
            return True
        if method.lower() == "dkim" and domain:
            match = _SIGNER.search(rest)
            signer = match.group(1).lower().strip(".") if match else ""
            if signer and (signer == domain or domain.endswith("." + signer) or signer.endswith("." + domain)):
                return True
    return False


def _authenticated(headers: dict[str, str], from_email: str = "") -> bool:
    return authenticated(headers, from_email)


async def _list_metadata(client: GmailClient, full_query: str, limit: int) -> list[dict]:
    """The listing and the metadata of every message in it, in one batched round trip.
    Raises ToolError with a readable reason; never a raw client exception."""

    # googleapiclient is synchronous. Run it in a thread so the event loop stays free and the
    # 8-second tool timeout can actually fire — awaiting blocking I/O directly makes the
    # timeout unenforceable and freezes every other request while Gmail stalls.
    def fetch_all() -> list[dict]:
        service = client.service()
        listing = (
            service.users()
            .messages()
            .list(userId="me", q=full_query, maxResults=limit)
            .execute()
        )
        stubs = listing.get("messages", []) or []

        # metadata format still costs 20 quota units, so the result count is the lever.
        def get_request(stub):
            return service.users().messages().get(
                userId="me", id=stub["id"], format="metadata", metadataHeaders=_METADATA_HEADERS,
            )

        # One round trip for all of them, not one each: a batch request carries every get in
        # a single HTTP call, which is most of a second saved on every email question.
        batched = _fetch_batched(service, stubs, get_request)
        if batched is not None:
            return batched
        messages: list[dict] = []
        for stub in stubs:
            try:
                messages.append(get_request(stub).execute())
            except Exception as exc:  # noqa: BLE001
                log.warning("could not fetch message %s: %s", stub["id"], _describe(exc))
        return messages

    try:
        return await asyncio.to_thread(fetch_all)
    except Exception as exc:  # noqa: BLE001
        if _is_auth_failure(exc):
            client.reset()
            raise ToolError(str(GmailAuthRequired("Gmail authorisation has expired."))) from exc
        raise ToolError(f"Gmail search failed: {_describe(exc)}") from exc


def _one_per_thread(messages: list[dict], include_bulk: bool) -> list[tuple[str, dict[str, str], dict]]:
    candidates: list[tuple[str, dict[str, str], dict]] = []
    seen_threads: set[str] = set()
    for message in messages:
        thread_id = message.get("threadId", "")
        if thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        headers = _headers(message)
        if _is_bulk(headers) and not include_bulk:
            continue
        candidates.append((thread_id, headers, message))
    return candidates


def _summary(thread_id: str, headers: dict[str, str], message: dict) -> dict[str, Any]:
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    return {
        "thread_id": thread_id,
        "message_id": str(message.get("id") or ""),
        "from": sender_name or sender_email,
        "from_email": sender_email,
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": (message.get("snippet") or "")[:300],
        "likely_bulk": _is_bulk(headers),
        "authenticated": authenticated(headers, sender_email),
    }


# Correlation looks this far back: an order is visible in Shopify for sixty days without the
# read_all_orders scope, and the conversation about it is rarely older than the order.
CORRELATION_DAYS = 60
CORRELATION_LIMIT = 3
_GMAIL_TERM = re.compile(r"[^\w@.+\-]")


async def threads_for(*, sender: str = "", terms: list[str] | tuple[str, ...] = (), days: int = CORRELATION_DAYS, limit: int = CORRELATION_LIMIT) -> dict[str, Any]:
    """Recent inbox threads from one sender, or mentioning one of a few exact terms (an
    order number). For the context layer, not the model: it never raises — an inbox that is
    not configured or not answering is reported as unavailable, and the order card is shown
    without its email. Metadata only; a body is read only when the owner asks for it."""
    if _client is None:
        return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
    clauses: list[str] = []
    sender = _GMAIL_TERM.sub("", (sender or "").strip().lower())
    if sender and "@" in sender:
        clauses.append(f"from:{sender}")
    for term in terms:
        term = _GMAIL_TERM.sub("", str(term or "").strip())
        if term:
            clauses.append(f'"{term}"')
    if not clauses:
        return {"available": True, "threads": []}
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), MAX_RESULTS))
    query = f"newer_than:{days}d -in:trash -in:spam -in:chats ({' OR '.join(clauses)})"
    try:
        messages = await _list_metadata(_c(), query, limit * 2)
    except ToolError as exc:
        log.warning("email correlation unavailable: %s", exc)
        return {"available": False, "reason": str(exc)[:160], "threads": []}
    threads = [_summary(t, h, m) for t, h, m in _one_per_thread(messages, include_bulk=False)]
    return {"available": True, "query": query, "threads": threads[:limit]}


# "Is anyone waiting on us" reads the inbox itself, not a list of customers. The listing is
# bounded; when it comes back full the window held more than was read, and `full` says so, so
# the answer can name what it covered instead of implying the whole inbox.
INBOX_LIMIT = 50


async def inbox_threads(*, days: int = 30, limit: int = INBOX_LIMIT) -> dict[str, Any]:
    """The inbox's recent threads from people, newest first, one summary per thread, bulk mail
    left out. The same query `gmail_search` reads ("the inbox"), for the context layer rather
    than the model: never raises, and metadata only."""
    if _client is None:
        return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), INBOX_LIMIT))
    query = f"newer_than:{days}d {BASE_QUERY}"
    try:
        messages = await _list_metadata(_c(), query, limit)
    except ToolError as exc:
        log.warning("inbox listing unavailable: %s", exc)
        return {"available": False, "reason": str(exc)[:160], "threads": []}
    threads = [_summary(t, h, m) for t, h, m in _one_per_thread(messages, include_bulk=False)]
    return {"available": True, "query": query, "threads": threads, "full": len(messages) >= limit}


async def replied(thread_id: str) -> bool | None:
    """Whether a message in this thread went out from here (Gmail's SENT label on any of its
    messages). None when the thread cannot be read."""
    if _client is None or not thread_id:
        return None
    try:
        labels = await asyncio.to_thread(_c().thread_labels, str(thread_id))
    except Exception as exc:  # noqa: BLE001 — unknown, said as such
        log.debug("thread labels unavailable for %s: %s", thread_id, type(exc).__name__)
        return None
    return "SENT" in labels


async def reply_state(thread_id: str) -> dict[str, Any] | None:
    """Who spoke last in this thread, and whether we have answered since.

    Returned per thread; the customer-level view is folded from several of these in
    app/tools/analytics_tools.py, WITHOUT merging the threads. A reply in one thread does
    not answer a newer message in another, and the September session showed exactly that
    case being missed. None when the thread cannot be read — unknown is an honest answer.
    """
    if _client is None or not thread_id:
        return None
    try:
        messages = await asyncio.to_thread(_c().thread_state, str(thread_id))
    except Exception as exc:  # noqa: BLE001 — unknown, said as such
        log.debug("thread state unavailable for %s: %s", thread_id, type(exc).__name__)
        return None
    if not messages:
        return None
    inbound = [m["at_ms"] for m in messages if "SENT" not in m["labels"] and "DRAFT" not in m["labels"] and m["at_ms"]]
    outbound = [m["at_ms"] for m in messages if "SENT" in m["labels"] and m["at_ms"]]
    latest_in = max(inbound) if inbound else None
    latest_out = max(outbound) if outbound else None
    # Their first message we have not answered: how long they have been waiting, which is not
    # the same as when they last wrote — a chase yesterday on a question from last week is a
    # week's wait.
    unanswered = [at for at in inbound if latest_out is None or at > latest_out]
    return {
        "thread_id": str(thread_id),
        "latest_inbound_at": latest_in,
        "latest_outbound_at": latest_out,
        "latest_direction": _direction(latest_in, latest_out),
        "has_reply_after_latest_inbound": bool(latest_in is not None and latest_out is not None and latest_out >= latest_in),
        "waiting_since": min(unanswered) if unanswered else None,
        "messages": len(messages),
    }


def _direction(latest_in: int | None, latest_out: int | None) -> str:
    if latest_in is None and latest_out is None:
        return "none"
    if latest_out is None:
        return "inbound"
    if latest_in is None:
        return "outbound"
    return "inbound" if latest_in > latest_out else "outbound"


# An email read as evidence for a change is read whole: an address at the foot of a long
# message is still the address.
EVIDENCE_BODY_CHARS = 20_000


async def message_evidence(message_id: str) -> dict[str, Any]:
    """One message, read in full, as evidence for a change the owner asked for: who sent it,
    whether the receiving server vouched for that sender, and its text. For the write tools
    on the Mac — never handed to the model, which cites a message by id and no more."""
    client = _c()
    message_id = str(message_id or "").strip()
    if not message_id:
        raise ToolError("No message id was given.")

    def fetch() -> dict:
        return client.service().users().messages().get(userId="me", id=message_id, format="full").execute()

    try:
        message = await asyncio.to_thread(fetch)
    except Exception as exc:  # noqa: BLE001
        if _is_auth_failure(exc):
            client.reset()
            raise ToolError(str(GmailAuthRequired("Gmail authorisation has expired."))) from exc
        raise ToolError(f"Could not read that email: {_describe(exc)}") from exc
    if not isinstance(message, dict) or not message.get("payload"):
        raise ToolError("That email could not be read.")
    headers = _headers(message)
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    return {
        "message_id": str(message.get("id") or message_id),
        "thread_id": str(message.get("threadId") or ""),
        "from": sender_name or sender_email,
        "from_email": sender_email.strip().lower(),
        "date": headers.get("date", ""),
        "subject": headers.get("subject", ""),
        "authenticated": authenticated(headers, sender_email),
        "body": _extract_body(message.get("payload", {}), limit=EVIDENCE_BODY_CHARS),
    }


# Looking for one string across a customer's whole correspondence. Bounded: the search is
# a Gmail query the Mac builds, and the bodies it reads are the threads that query returned.
FIND_MAX_THREADS = 12
FIND_BODY_CHARS = 20_000
FIND_EXCERPT = 160
FIND_CONCURRENCY = 3


@tool(
    name="gmail_find_in_email",
    description=(
        "Look for an exact string (a house number, a postcode, a tracking number) in the FULL "
        "TEXT of a customer's recent emails, not the snippets. Reads every thread it finds and "
        "says how many of how many it read. Use instead of reading threads one at a time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "contains": {"type": "string", "description": "The string to look for; case ignored."},
            "sender": {"type": "string", "description": "The customer's email address, from a search."},
            "mentions": {"type": "string", "description": "An order number the threads mention."},
            "days": {"type": "integer", "description": "How far back, default 60."},
        },
        "required": ["contains"],
    },
    tier=Tier.AMBER,
    timeout_s=20.0,
)
async def gmail_find_in_email(contains: str, sender: str = "", mentions: str = "", days: int = CORRELATION_DAYS) -> dict[str, Any]:
    needle = str(contains or "").strip()
    if len(needle) < 2:
        raise ToolError("Give me at least two characters to look for.")
    if not (sender.strip() or mentions.strip()):
        raise ToolError("Say whose email to look through: a sender's address, an order number, or both.")
    found = await threads_for(sender=sender, terms=[mentions] if mentions.strip() else [], days=days, limit=FIND_MAX_THREADS)
    if not found.get("available"):
        raise ToolError(str(found.get("reason") or "The inbox could not be read."))
    threads = [t for t in (found.get("threads") or []) if isinstance(t, dict) and t.get("thread_id")]
    total = len(threads)
    looked = threads[:FIND_MAX_THREADS]
    semaphore = asyncio.Semaphore(FIND_CONCURRENCY)
    matches: list[dict[str, Any]] = []
    checked = 0
    unreadable: list[str] = []

    async def scan(thread: dict) -> None:
        nonlocal checked
        thread_id = str(thread["thread_id"])
        async with semaphore:
            try:
                messages = await asyncio.to_thread(_c().thread_full, thread_id)
            except Exception as exc:  # noqa: BLE001 — a thread that will not open is said so
                unreadable.append(thread_id)
                log.debug("could not read thread %s: %s", thread_id, type(exc).__name__)
                return
        checked += 1
        for message in messages:
            body = _extract_body(message.get("payload") or {}, limit=FIND_BODY_CHARS)
            headers = _headers(message)
            where = _where(needle, headers.get("subject", ""), body)
            if where is None:
                continue
            matches.append({
                "thread_id": thread_id, "message_id": str(message.get("id") or ""),
                "subject": headers.get("subject", "")[:120], "date": headers.get("date", "")[:40],
                "from": parseaddr(headers.get("from", ""))[1].strip().lower(),
                "outbound": "SENT" in (message.get("labelIds") or []),
                "where": where[0], "excerpt": where[1],
            })

    await asyncio.gather(*(scan(t) for t in looked))
    return {
        "contains": needle, "threads_found": total, "threads_checked": checked,
        "threads_unreadable": len(unreadable), "complete": checked == total and not unreadable,
        "matches": matches, "match_count": len(matches),
        "coverage": f"checked {checked} of {total} thread(s)" + (f"; {len(unreadable)} could not be opened" if unreadable else ""),
        "source": f"Gmail, last {max(1, min(int(days or CORRELATION_DAYS), 365))} days",
    }


def _where(needle: str, subject: str, body: str) -> tuple[str, str] | None:
    """Where the string appears, and the line it is on. Subject first: it is the shortest
    honest answer. Nothing is returned when it does not appear at all."""
    lowered = needle.lower()
    if lowered in subject.lower():
        return "subject", subject.strip()[:FIND_EXCERPT]
    at = body.lower().find(lowered)
    if at < 0:
        return None
    start = body.rfind("\n", 0, at) + 1
    end = body.find("\n", at)
    line = body[start : end if end != -1 else len(body)].strip()
    return "body", (line or body[max(0, at - 40) : at + 80].strip())[:FIND_EXCERPT]


@tool(
    name="gmail_search",
    description=(
        'Search recent email in the CROOKS inbox: sender, subject, date and a snippet per thread, '
        'bulk mail flagged, senders matching a Shopify customer marked. Call it before reading a '
        'thread.'
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search terms, e.g. 'jeans' or 'from:jo@example.com'.",
                "default": "",
            },
            "days": {"type": "integer", "description": "Days back to look.",
                     "default": 1},
            "limit": {"type": "integer", "description": "Maximum threads (1-25).", "default": 10},
            "include_bulk": {
                "type": "boolean",
                "description": "Include newsletters and automated mail.",
                "default": False,
            },
        },
    },
    tier=Tier.GREEN,
    timeout_s=GMAIL_TIMEOUT_S,
)
async def gmail_search(
    query: str = "", days: int = 1, limit: int = 10, include_bulk: bool = False
) -> dict:
    client = _c()
    limit = max(1, min(int(limit), MAX_RESULTS))
    days = max(1, min(int(days), 365))
    full_query = f"newer_than:{days}d {BASE_QUERY}"
    if query.strip():
        full_query += f" {query.strip()}"

    messages = await _list_metadata(client, full_query, limit)
    candidates = _one_per_thread(messages, include_bulk)

    # Cross-reference every sender against Shopify concurrently, not one after another.
    senders = [parseaddr(h.get("from", ""))[1] for _, h, _ in candidates]
    known = await asyncio.gather(*(_known_customer(e) for e in senders))

    results: list[dict[str, Any]] = []
    for (thread_id, headers, message), is_known in zip(candidates, known, strict=True):
        results.append({**_summary(thread_id, headers, message), "known_customer": is_known})

    # The threads as a working set on the Mac, so "archive those" means exactly these.
    made = _threads_set(results, query.strip() or f"inbox, last {days} days")
    return {
        "query": full_query,
        "count": len(results),
        "threads": results,
        **({"set": made} if made else {}),
        "note": (
            "Gmail's Primary category is a heuristic and can misfile a genuine customer reply. "
            "Nothing here is guaranteed complete."
        ),
    }


def _threads_set(results: list[dict[str, Any]], words: str) -> dict[str, Any] | None:
    """The threads a search found, held on the Mac as a working set (app/analytics/sets.py):
    a read model's bookkeeping, nothing here touches the mailbox."""
    from app.analytics.sets import create as hold_working_set
    from app.tools.context import current_session

    session = current_session()
    ids = [str(r.get("thread_id")) for r in results if r.get("thread_id")]
    if session is None or not ids:
        return None
    labels = {str(r.get("thread_id")): str(r.get("subject") or "")[:60] or "(no subject)" for r in results if r.get("thread_id")}
    ws = hold_working_set(
        session, kind="emails", members=ids, label=f"email: {words}"[:80], provenance={"tool": "gmail_search", "step": "query", "query": {"words": words[:80]}},
        sample=[{"ref": tid, "label": labels[tid]} for tid in ids[:5]], labels=labels,
    )
    return ws.public()


@tool(
    name="gmail_read_thread",
    description=(
        "Read the messages in one email thread. Needs a thread_id from gmail_search. Prefer the "
        "search snippet when it already answers; read the thread only when the detail matters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "thread_id": {
                "type": "string",
                "description": "The thread_id returned by gmail_search.",
            }
        },
        "required": ["thread_id"],
    },
    tier=Tier.AMBER,
    issued_id_args=("thread_id",),
    timeout_s=GMAIL_TIMEOUT_S,
)
async def gmail_read_thread(thread_id: str) -> dict:
    client = _c()
    try:
        thread = await asyncio.to_thread(
            lambda: client.service()
            .users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        if _is_auth_failure(exc):
            client.reset()
            raise ToolError(str(GmailAuthRequired("Gmail authorisation has expired."))) from exc
        raise ToolError(f"Could not read thread {thread_id}: {_describe(exc)}") from exc

    # The NEWEST messages are the ones that matter — the customer's latest reply is at the end.
    messages = thread.get("messages", [])[-MAX_THREAD_MESSAGES:]
    out = []
    for message in messages:
        headers = _headers(message)
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        out.append(
            {
                "message_id": str(message.get("id") or ""),
                "from": sender_name or sender_email,
                "from_email": sender_email,
                "date": headers.get("date", ""),
                "subject": headers.get("subject", ""),
                "body": _extract_body(message.get("payload", {})),
                # Gmail's own label, not a guess from the address: who sent this one. The
                # thread card needs it to say whether anybody is waiting on us (section 8
                # asks the email surface for a needs-reply state), and `reply_state` above
                # already reads the same label for the same reason.
                "outbound": "SENT" in (message.get("labelIds") or []),
            }
        )

    directions = [bool(m["outbound"]) for m in out]
    return {
        "thread_id": thread_id,
        "message_count": len(thread.get("messages", [])),
        "messages_shown": len(out),
        "truncated": len(thread.get("messages", [])) > MAX_THREAD_MESSAGES,
        "messages": out,
        # Who spoke last, and whether we have answered since. "none" when the thread has no
        # readable message: unknown said as unknown, which is the rule everywhere else here.
        "latest_direction": ("none" if not directions else ("outbound" if directions[-1] else "inbound")),
        "awaiting_reply": bool(directions and not directions[-1]),
    }
