"""One order, its email, and the reply that has to be written (brief §16).

The worst turn of the September session was one sentence:

    "Check whether they've emailed us about this, tell me what they're waiting for,
     and draft the reply"

Thirty-five seconds, almost all of it Claude, and two `gmail_read_thread` calls REFUSED
because the thread ids had never been issued to the session — the model had guessed them from
a listing it had summarised earlier. Everything that turn spent thirty seconds discovering is
already on the Mac: which order is open, who the customer is, which threads are theirs (the
hydrator correlates them with every order read), and which of those threads is about this
order.

So the Mac does all of the reading and all of the drawing, deterministically:

    the order card          from shopify_order_detail
    the email_thread card   from gmail_read_thread, with the linked_order strip
                            (app/context/graph.py, drawn by app/presentation.py)
    a reply_state line      who spoke last, how long they have been waiting

and Claude is left with the one part of the sentence that needs judgement: saying what they
are waiting for, and writing the words. Both ids are ISSUED before the handover, so the two
refusals of the bench turn cannot happen again.

THE MUTATION SIGNAL. `intent.resolve` refuses any sentence carrying one, and "draft" is in
MUTATION_SOFT — so how this family is reached depends on how the sentence opens, and that is
deliberate, not a workaround:

    "CHECK whether they've emailed us … and draft the reply"   opens with a question word,
                                                               so `mutating()` is False and
                                                               this family takes it
    "draft the reply" / "and draft the reply"                   opens with the verb: a
                                                               mutation, refused by resolve,
                                                               and it goes to Claude

That second case is left exactly as it is. `gmail_draft_reply` WRITES — it puts a draft in the
mailbox — and a lane that cannot write must not appear to serve a bare instruction to write.
The fast lane's part is the reading; the write stays where every write in this system lives,
behind the model's tool call and the owner's gesture. Nothing here stages, arms or commits
anything (`assert_read_only` holds for these recipes like every other).

WHAT IS HANDED OVER, AND HOW. `continuation_prompt()` builds the model's side of the turn —
the thread's text, the latest message each way, both issued ids, and the instruction to say
one sentence and call `gmail_draft_reply` — bounded to CONTINUATION_CHARS so a long thread
cannot turn a small job back into a big one. The handover itself uses the machinery that
already exists: the branch is armed with the `email.reply` spoken continuation on that thread
(`app/commands.py:SPOKEN_CONTROLS`), so the next sentence reaches Claude with the record named
and applies to nothing else; the reads are in memory under `email_thread:<id>` and
`order:<id>`, so the model's own read of either is served from the Mac; and both ids are
issued. What is NOT here is a way for a fast answer to hand Claude that prompt WITHIN the same
turn: `app/routes/turn.py` returns as soon as a recipe answers, and it is not this family's
file to change. The prompt is built, bounded and tested; wiring it into that return is one
line in turn.py and is named in the handoff notes rather than smuggled in here.

The prompt is never written to the timeline or the turn log. It carries a customer's own words,
and the observability rule is that telemetry carries ids, counts and controlled words — so the
trace records the tool that was handed over and how many characters it was given, and nothing
of what was said.
"""

from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from typing import Any

from app.context import graph
from app.fastpath import library
from app.fastpath.intent import Family, extend
from app.fastpath.models import Ctx, FastAnswer
from app.fastpath.recipes import CACHE_ENTITY, Recipe, register
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.surfaces import Entity, Freshness, Surface

# How far back the inbox is searched — and therefore exactly what the deterministic answer is
# allowed to claim. "No email … in the last 30 days" has to be the window that was looked at:
# the order's own correlation reaches sixty days (gmail_tools.CORRELATION_DAYS), so this
# family runs its own search rather than borrowing a window it did not choose.
WINDOW_DAYS = 30
# What Claude is given. Small on purpose: everything in it was read by the Mac, so the model
# needs enough of the thread to answer and none of the rest. A thread of forty messages must
# not put the turn back where it started.
CONTINUATION_CHARS = 1500
# Per message, inside that budget.
QUOTE_CHARS = 320
# Threads considered for one order. The correlation itself caps at three (order.py) and the
# search adds the ones that name the number from another address.
MAX_CANDIDATES = 6


# ------------------------------------------------------------------ what the Mac holds


def _rows() -> list[dict[str, Any]]:
    """The order cache's rows, or nothing when the cache is not warm.

    Same source and same caution as the thread card's own strip (`presentation._thread_links`):
    a cold cache is "not yet", never "no", so a caller that gets nothing back must not conclude
    that a thread is about no order.
    """
    try:
        from app.tools.analytics_tools import cache

        held = cache()
        rows = held.rows()
        return list(rows) if rows and held.status().get("synced_at") is not None else []
    except Exception:  # noqa: BLE001 — no cache bound (a Mac without Shopify, a unit test) is a cold cache
        return []


def _digits(number: Any) -> str:
    return str(number or "").rsplit("-", 1)[-1].lstrip("#").strip()


def _first_name(who: str) -> str:
    word = str(who or "").strip().split(",")[0].strip().split(" ")[0].strip(" <>\"'")
    return word if word and "@" not in word else ""


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _stamp(value: Any) -> float | None:
    """One message's date as epoch seconds, from any of the three shapes that reach here.

    Gmail's own stamp is epoch milliseconds; the thread reader hands on the RFC 2822 `Date`
    header ("Thu, 10 Sep 2026 12:00:00 +0100"), which is what `library._since` cannot parse and
    would have printed verbatim — "Waiting since Thu, 10 Sep 2026 12:00:00 +0100" on the card.
    Unparseable is None, which is said as unknown rather than guessed at.
    """
    import datetime as dt

    text = str(value or "").strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        number = float(text)
        return number / 1000.0 if abs(number) > 1e11 else number
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=dt.UTC)).timestamp()


# ------------------------------------------------------- is this thread about THIS order


def about_this_order(thread: dict[str, Any], *, order: dict[str, Any], rows: list[dict[str, Any]],
                     clock=time.time) -> tuple[str, list[str]]:
    """(confidence, reasons) that this thread is about this order. Never inferred from a name.

    The strong reading is `app/context/graph.py` over the rows the Mac holds: it knows the
    sender's OTHER orders, so it can tell "she wrote about #1938" from "she wrote about
    something else" — which is the whole difference between a reply that answers the customer
    and a reply about the wrong parcel. A thread it links confidently to a different order of
    ours is not this order's thread, and that is reported as a reason rather than swallowed.

    Cold cache, or an order too old to be in it, falls back to the narrow rule the order side
    of the correlation already uses (`order.py:correlate_threads`): the customer's own address
    AND this order's number in the thread is confident; either alone is possible. Possible is
    never good enough to reply from — see `_choose`.
    """
    order_id = str(order.get("order_id") or "")
    digits = _digits(order.get("order_number"))
    customer = str(order.get("customer_email") or "").strip().lower()
    sender = str(thread.get("from_email") or "").strip().lower()
    named = graph.order_numbers_in(f"{thread.get('subject', '')} {thread.get('snippet', '')}")

    if rows:
        found = graph.linked_orders_for_thread(thread, rows=rows, clock=clock)
        linked = [str(o.get("order_id") or "") for o in found.get("linked") or []]
        reasons = [str(r) for r in found.get("provenance") or []]
        if order_id and order_id in linked:
            return str(found.get("confidence") or "none"), reasons
        if found.get("confidence") == "confident" and linked:
            about = str((found["linked"][0] or {}).get("order_number") or "another order")
            return "none", [f"the thread is about {about}, not this order"]

    if sender and sender == customer:
        if digits and digits in named:
            return "confident", ["from the customer's own address", f"order {digits} in the thread"]
        if named:
            return "none", [f"from the customer's own address, but the thread names {named[0]} and not {digits or 'this order'}"]
        return "possible", ["from the customer's own address", "the thread does not name an order"]
    if digits and digits in named:
        return "possible", [f"order {digits} in the thread", "but not from the customer's address"]
    return "none", ["not from the customer's address and it does not name the order"]


def _choose(candidates: list[dict[str, Any]], *, order: dict[str, Any], rows: list[dict[str, Any]],
            clock=time.time) -> tuple[dict[str, Any] | None, str, list[str]]:
    """The one thread a reply would be written into, and why — or nothing.

    Only a CONFIDENT link is chosen. A possible one is worth showing on a card, where the owner
    can see the reasons beside it, and is not worth opening a reply on: the cost of being wrong
    is a message to a customer about somebody else's parcel.
    """
    graded = []
    for thread in candidates:
        confidence, reasons = about_this_order(thread, order=order, rows=rows, clock=clock)
        graded.append((confidence, reasons, thread))
    confident = [(r, t) for c, r, t in graded if c == "confident"]
    if confident:
        # Newest first, so a customer who has written twice about one order is answered on the
        # message they are actually waiting on.
        reasons, thread = sorted(confident, key=lambda pair: _stamp(pair[1].get("date")) or 0.0, reverse=True)[0]
        return thread, "confident", reasons
    possible = [(r, t) for c, r, t in graded if c == "possible"]
    if possible:
        reasons, thread = possible[0]
        return None, "possible", reasons
    return None, "none", (graded[0][1] if graded else ["nothing in the inbox from this customer"])


# ------------------------------------------------------------------------ the reply state


def reply_state(messages: list[dict[str, Any]], *, customer_email: str, now: float | None = None) -> dict[str, Any]:
    """Who spoke last in this thread, and whether we have answered since.

    Worked out from the thread's own messages rather than from Gmail's SENT label, because the
    label is not in the read model the card is drawn from — and the rule this uses is the only
    one this system trusts anywhere: an exact match on the customer's address is them, and
    anything else in a thread the Mac has already tied to this customer is our side. (A third
    party copied into the thread would therefore read as us. It would take a reply we did not
    send to be reported as ours, which is the safe direction: it can only make the queue say
    someone is NOT waiting, never invent a customer who is.)

    `now` comes back with the stamps so that every "5h ago" in this turn — the card's, the
    sentence's and the prompt's — is measured from one instant. Two clocks in one answer is how
    a card says 4h and the voice says 5h.
    """
    theirs = str(customer_email or "").strip().lower()
    inbound: list[float] = []
    outbound: list[float] = []
    latest: tuple[float, bool, str] | None = None
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        when = _stamp(message.get("date"))
        if when is None:
            continue
        sender = str(message.get("from_email") or "").strip().lower()
        mine = bool(theirs) and sender == theirs
        (inbound if mine else outbound).append(when)
        if latest is None or when >= latest[0]:
            latest = (when, mine, str(message.get("from") or sender or ""))
    latest_in = max(inbound) if inbound else None
    latest_out = max(outbound) if outbound else None
    if latest_in is None and latest_out is None:
        direction = "none"
    elif latest_out is None:
        direction = "inbound"
    elif latest_in is None:
        direction = "outbound"
    else:
        direction = "inbound" if latest_in > latest_out else "outbound"
    return {
        "latest_direction": direction,
        "latest_inbound_at": latest_in,
        "latest_outbound_at": latest_out,
        # "Have we answered what they last said" — not "has anything ever gone out".
        "replied": bool(latest_in is not None and latest_out is not None and latest_out >= latest_in),
        "last_from": ("us" if latest is not None and not latest[1] else _first_name(latest[2]) if latest else ""),
        "messages": len([m for m in messages or [] if isinstance(m, dict)]),
        "now": float(now if now is not None else time.time()),
    }


def _ago(when: float | None, *, now: float) -> str:
    """How long ago, in the words the queue already uses (`library._since`, one clock)."""
    return library._since(str(int(when * 1000)), now=now) if when else ""


# ------------------------------------------------------------------- what Claude is given


def continuation_prompt(*, order: dict[str, Any], thread: dict[str, Any], state: dict[str, Any],
                        limit: int = CONTINUATION_CHARS) -> str:
    """The model's side of this turn, bounded.

    Everything in it was read by the Mac a moment ago and is in memory, so the model is told
    not to read it again; both ids are named as ISSUED, because the bench failure was two calls
    refused for ids that never were. The instruction is assembled LAST and is never what gets
    cut: a prompt trimmed to fit that had lost its instruction would be a thread of somebody
    else's email with no question attached to it.
    """
    thread_id = str(thread.get("thread_id") or "")
    order_id = str(order.get("order_id") or "")
    number = str(order.get("order_number") or "")
    who = str(order.get("customer_name") or "the customer")
    now = float(state.get("now") or time.time())
    messages = [m for m in (thread.get("messages") or []) if isinstance(m, dict)]
    theirs = str(order.get("customer_email") or "").strip().lower()
    inbound = [m for m in messages if str(m.get("from_email") or "").strip().lower() == theirs]
    outbound = [m for m in messages if str(m.get("from_email") or "").strip().lower() != theirs]

    head = [
        f"The owner asked what {_clip(who, 60)} is waiting for on order {_clip(number, 20)}, and for the reply to be drafted.",
        "CLIVE has already read all of this. Do not read it again.",
        # And has already SAID the mechanical half out loud — `_render`'s sentence leads the
        # answer this turn returns (app/routes/turn.py). Repeating it would have the owner hear
        # who wrote and whether we replied twice in one breath.
        "The owner has already been told who wrote, when, and whether we have replied. Do not repeat that.",
        f"Order {_clip(number, 20)}: {_clip(order.get('total'), 20)}, {_clip(order.get('fulfillment'), 24).lower()}, placed {_clip(order.get('placed_at'), 30)}."
        f" Customer {_clip(who, 60)} <{_clip(theirs, 80)}>, order_id={order_id} (issued to you).",
        f"Thread \"{_clip(thread.get('subject'), 90)}\", {int(state.get('messages') or len(messages))} message(s),"
        f" thread_id={thread_id} (issued to you). Last message {'from them' if state.get('latest_direction') == 'inbound' else 'from us'}"
        f"{'; we have not replied since' if not state.get('replied') and state.get('latest_direction') == 'inbound' else ''}.",
    ]
    tail = [
        f"In one sentence say what they actually want done — the thing behind the email, not its"
        f" state — then call gmail_draft_reply(thread_id='{thread_id}', order_id='{order_id}', body=…).",
        "A draft only. The owner applies it with a gesture on the screen; never send it yourself, and never say it has been sent.",
    ]
    fixed = "\n".join(head + tail)
    room = limit - len(fixed) - 2
    quotes: list[str] = []
    for label, group in (("Latest from them", inbound), ("Latest from us", outbound)):
        if room <= 40 or not group:
            continue
        newest = sorted(group, key=lambda m: _stamp(m.get("date")) or 0.0)[-1]
        text = _clip(newest.get("body") or newest.get("snippet"), min(QUOTE_CHARS, room - 40))
        if not text:
            continue
        line = f"{label} ({_ago(_stamp(newest.get('date')), now=now) or 'unknown'}): {text}"
        quotes.append(line)
        room -= len(line) + 1
    if not outbound:
        line = "Nothing has gone out from us in this thread."
        if room > len(line):
            quotes.append(line)
    return "\n".join(head + quotes + tail)


# ---------------------------------------------------------------------------- the surface


def _reply_surface(*, order: dict[str, Any], thread: dict[str, Any], state: dict[str, Any],
                   confidence: str, provenance: list[str]) -> Surface:
    """The one line the owner reads before deciding: who is waiting, since when, and on what.

    The renderer composes the words from these fields (`web/ui.js:renderReplyState`) rather than
    being handed a sentence, so the card and the spoken answer are the same three facts said
    twice and cannot drift apart.
    """
    thread_id = str(thread.get("thread_id") or "")
    now = float(state.get("now") or time.time())
    return Surface(
        surface_type="reply_state",
        ui_type="reply_state",
        data={
            "thread_id": thread_id,
            "order_number": str(order.get("order_number") or ""),
            "latest_direction": str(state.get("latest_direction") or "none"),
            "replied": bool(state.get("replied")),
            "waiting_since": _ago(state.get("latest_inbound_at"), now=now),
            "replied_since": _ago(state.get("latest_outbound_at"), now=now),
            "last_from": str(state.get("last_from") or ""),
            "confidence": confidence,
            "provenance": [str(p) for p in provenance[:4]],
        },
        entity=Entity("email_thread", thread_id, _clip(thread.get("subject"), 60)) if thread_id else None,
        title="Reply state",
        subtitle=_clip(order.get("order_number"), 20),
        freshness=Freshness(source="gmail", complete=True),
    )


# ------------------------------------------------------------------------- the recipe


def _threads_args(values: dict[str, Any]) -> dict[str, Any] | None:
    """The inbox search behind the answer: this customer's own address, or this order's number
    from anyone. The same two clauses the order correlation uses, in the window this family's
    sentence actually claims (WINDOW_DAYS), and parenthesised because they are an OR."""
    order = values.get("detail")
    if not isinstance(order, dict):
        return None
    email = str(order.get("customer_email") or "").strip().lower()
    digits = _digits(order.get("order_number"))
    clauses = [f"from:{email}" if "@" in email else "", f'"{digits}"' if digits else ""]
    clauses = [c for c in clauses if c]
    if not clauses:
        return None
    return {"query": f"({' OR '.join(clauses)})", "days": WINDOW_DAYS, "limit": MAX_CANDIDATES}


def _candidates(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Every thread that could be this order's, from both sources, newest first, deduplicated.

    Two sources because they see different things: the order's own correlation (the hydrator,
    `app/context/order.py`) reaches sixty days and carries its sender/number match, and the
    search covers the thread that arrived in the last thirty from an address the order does not
    know. Neither is trusted about WHICH order the thread is about — that is `_choose`.
    """
    out: dict[str, dict[str, Any]] = {}
    order = values.get("detail") if isinstance(values.get("detail"), dict) else {}
    email = (order.get("email") if isinstance(order.get("email"), dict) else {}) or {}
    found = values.get("threads") if isinstance(values.get("threads"), dict) else {}
    for thread in list(email.get("threads") or []) + list((found or {}).get("threads") or []):
        if not isinstance(thread, dict):
            continue
        thread_id = str(thread.get("thread_id") or "")
        if thread_id and thread_id not in out and not thread.get("likely_bulk"):
            out[thread_id] = thread
    return sorted(out.values(), key=lambda t: _stamp(t.get("date")) or 0.0, reverse=True)[:MAX_CANDIDATES]


def _thread_args(values: dict[str, Any]) -> dict[str, Any] | None:
    """Read the thread the reply would go into — and only that one.

    The choice is made here and again in the render, from the same pure function over the same
    values, so what was read and what is said about it cannot disagree. No confident thread is
    `None`: the read is skipped, nothing is opened, and the answer is the deterministic "no
    email about this order" one.
    """
    order = values.get("detail")
    if not isinstance(order, dict):
        return None
    chosen, confidence, _ = _choose(_candidates(values), order=order, rows=_rows())
    return {"thread_id": str(chosen.get("thread_id"))} if chosen and confidence == "confident" else None


_NUMBER_SAID = re.compile(r"\b\d{3,6}\b")


def _names_a_record(ctx: Ctx) -> bool:
    """Whether the sentence names a record by number instead of pointing at the open one.

    This family's whole subject is "this" — the order the owner is looking at. A number in the
    sentence is him naming something, and `spoken_order_numbers` deliberately will not extract
    a bare one (a bare 2025 is a year, "over 500" is money), so what reaches here cannot be
    told apart: "any email from him about 1938" may be the open order, another order, a
    tracking number or a date. `library._names_another_order` guards the same hazard for the
    order recipes — "the right shape of answer, the wrong customer's address, spoken aloud".

    It is deliberately the cautious version of that guard: ANY number, even one that matches
    the order on screen, sends the turn to Claude, which can look up whatever was said and ask.
    What it costs is one phrasing ("any email from him about 1938") answered in a model turn,
    the way it was in September. What it buys is that a family which opens a customer's thread
    and offers to write to them never does so on a number it could not parse.
    """
    return bool(_NUMBER_SAID.search(ctx.text or ""))


def _plan(ctx: Ctx) -> ReadPlan | None:
    """The order, then the inbox around it, then the one thread. Three waves, because each
    genuinely needs the one before it: the search needs the customer's address, and the thread
    read needs to know which thread is worth opening.

    The order is always the one the conversation is ON. Both families block `order_number` and
    the plan declines a bare one, so there is no "find it first" wave here; with nothing open
    the runner defers before the plan is asked for at all (`required_entities`).
    """
    known = ctx.entity("order")
    if not known or _names_a_record(ctx):
        return None
    return ReadPlan([
        Read("detail", "shopify_order_detail", {"order_id": known}, source="shopify", cost=90.0),
        Read("threads", "gmail_search", _threads_args, source="gmail", after=("detail",), cost=2.0),
        Read("thread", "gmail_read_thread", _thread_args, source="gmail", after=("threads",), cost=1.0),
    ], label="order_email_reply", timeout_s=10.0)


def _call(result: ReadResult, node: str):
    """The tool call behind a read, so a card is drawn from exactly that read and the search
    that only found candidates draws nothing."""
    body = result.values.get(node)
    for call in result.calls:
        if getattr(call, "ok", False) and getattr(call, "result", None) is body and body is not None:
            return call
    return None


def _inbox_answered(result: ReadResult) -> bool:
    """Whether the inbox was actually read. A search that failed is not an empty inbox, and
    "no email" must never be said about a mailbox nobody could reach."""
    found = result.values.get("threads")
    if isinstance(found, dict):
        return True
    order = result.values.get("detail")
    part = (order or {}).get("email") if isinstance(order, dict) else None
    return bool(isinstance(part, dict) and part.get("available"))


# Words that ask for a reply to be MADE. Deliberately not "reply" or "answer" on their own:
# "did she reply to that" is a question about what already happened, and arming the mailbox for
# a sentence like that would leave a reply half-offered that nobody asked for.
_COMPOSE = frozenset({"draft", "drafts", "drafting", "write", "writing", "compose", "composing"})


def _asks_to_draft(ctx: Ctx) -> bool:
    """Whether this sentence asked for the reply itself, not just for its state.

    It decides two things and nothing else: whether the branch is armed for the next sentence,
    and whether the answer offers to draft. It must be the words the OWNER said — never the
    continuation note a previous turn may have added to them, which is why it reads the
    resolved signals rather than `ctx.text`.
    """
    return bool(set(getattr(ctx.intent.signals, "words", ()) or ()) & _COMPOSE)


def _may_draft(ctx: Ctx) -> bool:
    """Whether a draft can be prepared at all on this Mac right now. Never assumed on: telling
    the owner "say the word and I'll draft it" while changes are off is a promise this build
    cannot keep, and the September report counts that as a false claim."""
    settings = getattr(ctx.runtime, "settings", None)
    return bool(getattr(settings, "writes_enabled", False))


def _arm(ctx: Ctx, *, thread_id: str, subject: str) -> bool:
    """Hand the thread to the next sentence.

    `email.reply` is the spoken control the tablet already has for this (`SPOKEN_CONTROLS`), so
    the branch says what it is listening for, the screen shows it, and whatever the owner says
    next reaches Claude with this thread named and applied to nothing else
    (`app/routes/turn.py:_with_continuation`). One sentence, taken or abandoned.
    """
    try:
        from app.commands import SPOKEN_CONTROLS, listening_phrase

        family = "email.reply"
        prompt = SPOKEN_CONTROLS[family][1]
        phrase = listening_phrase(family, kind="email_thread", ref=thread_id, label=subject)
        ctx.branch.bind_voice(family, kind="email_thread", ref=thread_id, label=subject, prompt=prompt, phrase=phrase)
    except Exception:  # noqa: BLE001 — a branch that cannot listen still gets the answer and the cards
        return False
    return True


def _render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    if _names_a_record(ctx):
        return FastAnswer(answer="", defer="the sentence names a record by number rather than the one open")
    order = result.values.get("detail")
    if not isinstance(order, dict) or not order.get("order_id"):
        return FastAnswer(answer="", defer="the order did not resolve to one record")
    number = str(order.get("order_number") or "")
    who = _first_name(str(order.get("customer_name") or "")) or "the customer"
    # The conversation stays on the ORDER, on its Email tab: the thread is what the order is
    # waiting on, not somewhere else the owner has been taken. A follow-up ("what are they
    # waiting for") still finds an open order, which is what this family requires.
    library._remember(ctx, "order", str(order["order_id"]), number, tab="email")

    candidates = _candidates(result.values)
    chosen, confidence, provenance = _choose(candidates, order=order, rows=_rows())
    detail_call = _call(result, "detail")

    if chosen is None:
        if not _inbox_answered(result):
            # Not "no email": nobody could read the inbox. Claude can search it and say so.
            return FastAnswer(answer="", defer="the inbox could not be read")
        words = f"No email from {who} about {number} in the last {WINDOW_DAYS} days."
        if candidates:
            # They HAVE written — about something else, or from an address that is not theirs.
            # Saying only "no email" here would be true of the order and wrong about the person.
            why = provenance[0] if provenance else "nothing ties what they wrote to this order"
            words += f" {who} has written, but not about this order: {why}."
        return FastAnswer(
            answer=words, calls=list(result.calls), drawn=[c for c in (detail_call,) if c is not None],
            trace={"threads_considered": len(candidates), "confidence": confidence, "drafted": False},
        )

    thread = result.values.get("thread")
    thread_call = _call(result, "thread")
    if not isinstance(thread, dict) or not thread.get("messages"):
        # The thread was chosen and would not open. The order and the link are still worth
        # drawing; what the owner must not get is a reply state invented from a summary.
        return FastAnswer(
            answer=f"{who} emailed about {number} — {_clip(chosen.get('subject'), 60)} — but the thread would not open.",
            calls=list(result.calls), drawn=[c for c in (detail_call,) if c is not None], partial=True,
            trace={"threads_considered": len(candidates), "confidence": confidence, "thread": "unread", "drafted": False},
        )

    state = reply_state(thread.get("messages") or [], customer_email=str(order.get("customer_email") or ""))
    now = float(state["now"])
    subject = _clip(thread.get("subject") or chosen.get("subject"), 80)
    thread_id = str(thread.get("thread_id") or chosen.get("thread_id") or "")
    # Both ids, before anything is handed over. The thread's came from a read and the order's
    # from another, so both are issued already — issuing them here is the guarantee rather than
    # the accident, and it is what the bench turn's two refusals were missing.
    ctx.session.issue(thread_id, str(order["order_id"]))

    waiting = state["latest_direction"] == "inbound" and not state["replied"]
    since = _ago(state["latest_inbound_at"], now=now)
    if waiting:
        words = f"{who} emailed about {number}{f' {since}' if since else ''} — {subject} — and we have not replied."
    elif state["latest_direction"] == "outbound":
        answered = _ago(state["latest_outbound_at"], now=now)
        words = f"{who} emailed about {number} — {subject} — and we replied{f' {answered}' if answered else ''}."
    else:
        words = f"{who}'s thread about {number} — {subject} — has no dated message on it."

    prompt = continuation_prompt(order=order, thread=thread, state=state)
    # Armed only for a sentence that asked for the reply. A continuation left behind by a
    # sentence that did not ask for one is worse than none: the NEXT thing said is then read as
    # words for that reply (`turn.py:_with_continuation`), which is how "what are they waiting
    # for" — this family's own second phrasing — ended up on Claude's desk as dictation.
    asked = _asks_to_draft(ctx)
    armed = asked and _may_draft(ctx) and _arm(ctx, thread_id=thread_id, subject=subject)
    if armed:
        # Nothing added. The owner asked for the draft and it is being written in this same
        # turn — the continuation below puts it to Claude with the thread already read. Saying
        # "say the word and I will draft the reply" to somebody who just said the word is the
        # second ask this recipe exists to remove.
        pass
    elif asked and not _may_draft(ctx):
        words += " Changes are switched off, so I cannot draft a reply."
    elif _may_draft(ctx):
        words += " Ask me to draft the reply and I will."

    return FastAnswer(
        answer=words,
        calls=list(result.calls),
        # The order and the thread. The search only found candidates: an inbox list beside them
        # would be a third card answering a question nobody asked.
        drawn=[c for c in (detail_call, thread_call) if c is not None],
        surfaces=[_reply_surface(order=order, thread=thread, state=state, confidence=confidence, provenance=provenance)],
        # The reading is done; the sentence about what they are waiting for and the draft itself
        # are Claude's, so this turn is not the whole answer and does not claim to be.
        partial=True,
        # And Claude is asked in THIS turn: `app/routes/turn.py` carries these cards into the
        # model turn and puts this prompt in front of it, so one answer comes back with the
        # workspace already drawn. Only when the owner asked for the reply — a sentence that
        # only asked whether they had written is answered, not handed on.
        # Handed over only when the draft can actually be made: `armed` is asked AND allowed AND
        # the thread accepted the binding. Putting the prompt to the model while changes are off
        # would ask it for a `gmail_draft_reply` the gate refuses, and the owner would hear a
        # refusal after being told plainly, one sentence earlier, that changes are off.
        continuation=prompt if armed else "",
        trace={
            "threads_considered": len(candidates), "confidence": confidence,
            "waiting": waiting, "replied": bool(state["replied"]),
            # The handover, in controlled words and counts. Never the prompt itself: it quotes
            # a customer, and the timeline carries ids, counts and tool names only.
            "continuation": "gmail_draft_reply", "continuation_chars": len(prompt),
            "asked_to_draft": asked, "listening_for": "email.reply" if armed else "",
            "ids_issued": 2, "drafted": False,
        },
    )


# --------------------------------------------------------------------------- registration

# Two recipes, one procedure. `recipe_for` maps ONE intent family to one recipe, and the two
# ways this gets asked cannot be one family: "have they emailed about this" carries the inbox
# signal and no waiting, "what are they waiting for" carries waiting and no inbox, and a
# family's `needs` are all required. Splitting them on that signal — the way
# customer_history_lookup and customer_purchase_lookup split on a name — keeps them out of each
# other's way: the second blocks `email`, so a sentence carrying both (the bench's compound
# one) matches the first alone and never lands in an ambiguous tie.
_PLAN_AND_RENDER = {"plan": _plan, "render": _render}
_READS = ("shopify_order_detail", "gmail_search", "gmail_read_thread")
# Three waves, each waiting on the one before it. Documented here so a dependency added to
# `_plan` without saying so is caught by tests/test_fastpath.py rather than on the workbench.
_WAVES = (("detail",), ("threads",), ("thread",))

register(Recipe(
    recipe_id="order_email_reply", intent_family="order_email_draft", required_entities=("order",),
    read_primitives=_READS, parallel_nodes=_WAVES, ui="email_thread", cache_policy=CACHE_ENTITY,
    min_confidence=0.72, target_ms=2500, **_PLAN_AND_RENDER,
))
register(Recipe(
    recipe_id="order_email_waiting", intent_family="order_email_waiting", required_entities=("order",),
    read_primitives=_READS, parallel_nodes=_WAVES, ui="email_thread", cache_policy=CACHE_ENTITY,
    min_confidence=0.72, target_ms=2500, **_PLAN_AND_RENDER,
))

# What both families rule out. Every one of these means a different question about the record
# that is open — where is it, what does it cost, what else have they bought, read it again —
# and each already has a family that answers it. `mutation` is first because it is the one that
# matters: a sentence that opens with "draft…" never reaches here.
_NOT_THIS = (
    "mutation", "metric", "ranking", "stock", "running_out", "period", "status", "address",
    "bought", "again", "possessive_name", "known_name",
    # And a number. This family's subject is the record in front of the owner — "this" — and a
    # sentence carrying BOTH a pronoun and an order number has two candidate subjects: "any
    # email from him about 1938" is the customer on screen and an order that may be somebody
    # else's. Choosing between them is a judgement, not a lookup, so it goes to Claude, which
    # can look up both and ask. (It is also how that question was answered in the September
    # recording — one model turn, one gmail_search — and there was nothing wrong with it.)
    "order_number",
)
extend([
    # "Check whether they've emailed us about this" / "have they emailed about this order" /
    # the whole compound sentence. `deixis` and an open order are what make it this family and
    # not the inbox: "what's in the inbox" points at nothing and stays inbox_state.
    Family("order_email_draft", needs=("email", "deixis", "has_entity"),
           boosts=("waiting", "question", "order", "customer", "delayed"), blocks=_NOT_THIS,
           entities=("order",), base=0.90, floor=0.72, max_words=20),
    # "What are they waiting for" — the same procedure, asked without the word for email.
    Family("order_email_waiting", needs=("waiting", "deixis", "has_entity"),
           boosts=("question", "order", "customer", "delayed"), blocks=_NOT_THIS + ("email",),
           entities=("order",), base=0.90, floor=0.72, max_words=12),
])
