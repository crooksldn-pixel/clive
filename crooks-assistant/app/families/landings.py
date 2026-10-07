"""The dock's four landings — Orders, Inbox, Sales, Products — as workspaces (brief §4).

On the bench the dock "did not behave like useful navigation unless the assistant was already
in another interaction": each icon asked a sentence through the whole turn pipeline, and a
sentence about today's orders on a quiet afternoon drew an empty list. A landing is not a
question. It is a place, and a place has a fixed shape whatever was said before it:

    Orders    what has to go out (oldest first, a set to walk) and what came in today
    Inbox     who is waiting on a reply (the queue), then what else people have written
    Sales     the week against the week before, today so far, and what is selling
    Products  the best sellers of the month and what is closest to running out

Each is a recipe — deterministic reads through the read scheduler, no model — reached by a
tap: the dock posts the semantic command `open.area`, and `app/routes/command.py` runs the
named recipe. Home and Back land here too (app/commands.py). A sentence never does: "open the
inbox" said out loud is a model turn like every other sentence, and Claude reads the inbox
with its own tools.

The helpers below (the reply queue, the working set a listing opens, money and periods in
words) live here because the landings are the only thing left that uses them.

Read-only, like every recipe: `assert_read_only` holds for these too.
"""

from __future__ import annotations

import time
from typing import Any

from app import commands as commands_mod
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.recipes import CACHE_ANALYTICS, CACHE_EMAIL, Ctx, Recipe, RecipeAnswer, register

AREAS: dict[str, str] = {
    "orders": "landing_orders",
    "email": "landing_inbox",
    "sales": "landing_sales",
    "products": "landing_products",
}

# The same table, where `navigation.home` can find it. A command must not import a family —
# `app/commands.py` is the bottom of the stack and the families sit on top of it — so the
# families hand their landings down instead. Home is then "the recipe for this half's area",
# resolved in one place (app/commands.py:home_target).
commands_mod.LANDING_FOR.update(AREAS)


# ------------------------------------------------------------------ shared helpers


def _hedge(body: dict[str, Any]) -> str:
    """What the read itself says about its own completeness, added to the answer rather than
    left in the payload for nobody. The order cache says `complete: False` with a `note`
    while it is still filling — which is exactly the first questions after a restart."""
    if not isinstance(body, dict) or body.get("complete") is not False:
        return ""
    note = " ".join(str(body.get("note") or "").split())
    return f" {note}" if note else " The server is still reading recent orders, so this is what it holds so far."


def _how_many(body: dict[str, Any], shown: int) -> str:
    """How many there are, not how many fitted. A limit of 25 against 61 matching orders was
    being spoken as "25 orders are unfulfilled"."""
    total = body.get("row_count")
    if isinstance(total, int) and total > shown:
        return f"{total} (showing {shown})"
    return str(shown)


def _period_words(body: dict[str, Any], fallback: str = "the period") -> str:
    """The period as a person says it. The read layer's own label first; its slug, spelled
    out, second — "last_30_days" was being read aloud with the underscores in it."""
    period = body.get("period") if isinstance(body.get("period"), dict) else {}
    label = str(period.get("label") or "").strip()
    if label:
        return label
    slug = str(period.get("name") or period.get("period") or "").strip()
    return slug.replace("_", " ") if slug else fallback


# What the Mac's own reads call money. Shopify's shape is already a string with its currency
# in it ("45.00 GBP"); the read layer's is a bare number with the currency beside it. One
# answer must not contain both shapes.
_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}


def _money(value: Any, currency: str = "GBP") -> str:
    if isinstance(value, str):
        parts = value.split()
        if len(parts) == 2 and parts[1].isalpha():
            value, currency = parts[0], parts[1].upper()
    try:
        return f"{_SYMBOL.get(currency.upper(), currency.upper() + ' ')}{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value or "")


def _totals_line(totals: dict[str, Any], period: str, currency: str = "GBP") -> str:
    bits = []
    if totals.get("revenue") is not None:
        bits.append(_money(totals["revenue"], currency))
    if totals.get("orders") is not None:
        bits.append(f"{int(totals['orders'])} orders")
    if totals.get("aov") is not None:
        bits.append(f"{_money(totals['aov'], currency)} average")
    head = period[:1].upper() + period[1:] if period else "The period"
    return (f"{head}: " + ", ".join(bits) + ".") if bits else f"Nothing to report for {period}."


# How far back "waiting on us" looks in the inbox.
NEEDS_REPLY_DAYS = 30


def _set_id_of(body: Any, key: str = "set") -> str:
    """The working set a listing made. The read layer publishes it under `set` (the whole
    public shape) — `set_id` at the top level is what the batch tools' own results use — so
    both are looked for rather than one being assumed."""
    if not isinstance(body, dict):
        return ""
    held = body.get(key)
    if isinstance(held, dict) and held.get("set_id"):
        return str(held["set_id"])
    return str(body.get("set_id") or "")


# The same question, asked again inside this window, gets the short form: the owner has just
# heard who is waiting and how far back the inbox was read, and is asking whether anything has
# changed, not for the scope of the check read out a second time.
NEEDS_REPLY_REPEAT_S = 600.0


def _first_names(rows: list[dict[str, Any]], limit: int = 3, *, full: bool = False) -> str:
    names = [str(r.get("customer_name") or "someone") for r in rows[:limit]]
    names = names if full else [n.split()[0] for n in names]
    rest = len(rows) - len(names)
    if rest > 0:
        names.append(f"{rest} other{'s' if rest > 1 else ''}")
    if len(names) <= 1:
        return names[0] if names else "nobody"
    return ", ".join(names[:-1]) + " and " + names[-1]


def _asked_again(ctx: Ctx, *, clock=time.time) -> bool:
    """Whether this is a repeat of the question within the window; stamps the session either
    way. A session without the attribute (a bare stand-in in a test) is never a repeat."""
    now = float(clock())
    last = float(getattr(ctx.session, "last_needs_reply_at", 0.0) or 0.0)
    try:
        ctx.session.last_needs_reply_at = now
    except AttributeError:
        return False
    return bool(last) and 0 <= now - last < NEEDS_REPLY_REPEAT_S


def _waited_since(row: dict[str, Any]) -> float | None:
    """When this person started waiting on us: their first message we have not answered, or
    — from a read that does not say — their latest."""
    for key in ("waiting_since", "latest_inbound_at"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


# How many people the waiting card draws. The same slice is issued and walked, never more.
WAITING_SHOWN = 10


def _longest_waiting_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The order the answer names them in, the card lists them in and Next walks them in. The
    queue came out 11d, 13d, 13d, 5d, …, 1d — the read's own order, which is nobody's."""
    return sorted(rows, key=lambda r: (_waited_since(r) is None, _waited_since(r) or 0.0))


def _reply_scope(body: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[str, str]:
    """What was checked, in words: (the scope for the sentence, the note for the card).

    The answer said "10 of 25 customers checked" to a question about the inbox. Whatever this
    read covered is said as what it covered — never as the whole inbox when it was not."""
    if body.get("scope") != "inbox":
        counts = body.get("counts") or {}
        total = int(counts.get("contacted") or 0) + int(counts.get("not_contacted") or 0) + int(counts.get("unchecked") or 0) or len(rows)
        return f"of the {total} customers checked", ""
    days = int(body.get("days") or NEEDS_REPLY_DAYS)
    if body.get("window_complete") is False:
        listed = int(body.get("threads_listed") or 0)
        return (f"in the inbox's newest {listed} threads",
                f"The newest {listed} threads were checked; the last {days} days hold more.")
    return f"in the inbox's last {days} days", ""


def _needs_reply_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    body = result.values.get("mail")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the inbox did not come back")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    waiting = _longest_waiting_first([r for r in rows if r.get("needs_reply")])
    inbox = body.get("scope") == "inbox"
    counts = body.get("counts") or {}
    unchecked = int(counts.get("unchecked") or 0)
    scope, scope_note = _reply_scope(body, rows)
    again = _asked_again(ctx)
    # What "next" walks here is the MESSAGES, not the people. Opening the customers set meant
    # tapping Next on "Waiting on a reply" drew Mia Jones's customer profile — three orders,
    # £213 lifetime — instead of the message she is waiting on an answer to. The queue is a
    # queue of things to reply to, so its cursor moves along the threads.
    #
    # And the thread ids go into `issued_ids`, because this card puts them on the screen. The
    # gate's rule is that a conversation may only reach a record it was shown, and the surface
    # is built here rather than harvested from a tool result, so nothing else would have
    # issued them — which made every row of this card unopenable by the very check that
    # exists to protect it.
    # Only the threads the card draws are issued and walkable (the 2026-09-26 deploy review, F-04):
    # the gate's rule is that a conversation reaches only a record it was shown.
    _open_waiting_threads(ctx, body, waiting[:WAITING_SHOWN])
    waiting_set = _set_id_of(body, "set_needs_reply")
    if waiting_set and ctx.branch.workflow is None:
        _open_workflow(ctx, body, kind="customers", operation="reply", set_id=waiting_set)
    tail = (f" {unchecked} {'thread' if inbox else 'customer'}{'s' if unchecked != 1 else ''} could not be checked." if unchecked else "")
    unchecked_tail = tail   # before the sent-check caveat joins it
    # A reply sent as a new email that was not looked for everywhere is said, in the answer and on
    # the card: someone shown as waiting may already have been answered (the 2026-09-26 deploy
    # review, F-02). The scan logs why; the owner is told what it means.
    sent = str(body.get("sent_checked") or "all") if inbox else "all"
    caveat = _sent_caveat(sent) if waiting else ""
    if caveat:
        tail += " " + caveat
        scope_note = " ".join(filter(None, [scope_note, caveat]))
    # A list that may name people already answered is a partial answer, whichever way it is said.
    partial = bool(unchecked) or bool(caveat) or result.partial
    if len(waiting) > WAITING_SHOWN:
        scope_note = " ".join(filter(None, [scope_note, f"The {WAITING_SHOWN} longest waits are shown."]))
    # A repeat drops the scope sentence, but never what makes the answer less than whole: the
    # threads that could not be checked and a window that was cut short are said every time
    # (the 2026-09-26 deploy reviews, F-08).
    limits = ""
    if inbox and body.get("window_complete") is False:
        limits = f" Only the newest {int(body.get('threads_listed') or 0)} threads were checked."
    if not waiting:
        if again:
            answer = f"Still nobody.{unchecked_tail}{limits}"
        elif inbox:
            answer = f"Nobody is waiting on a reply {scope} — {int(body.get('threads_checked') or 0)} threads from people checked.{tail}"
        else:
            answer = f"Nobody is waiting on a reply — {len(rows)} {scope}.{tail}"
        return RecipeAnswer(answer=answer, calls=list(result.calls),
                          partial=partial, trace={"rows": len(rows), "waiting": 0, "unchecked": unchecked, "repeat": again})
    if again:
        # "Still just Mia." — no scope sentence: it was said the first time, and the owner is
        # asking whether anything moved, not how wide the check was. The sent-check caveat is
        # NOT the scope, though: it says this list may be wrong, and a repeat is the answer he
        # acts on, so it is said again (the deploy review of 9c37973f, F-02's repeat branch).
        answer = f"Still {'just ' if len(waiting) == 1 else ''}{_first_names(waiting)}.{unchecked_tail}{limits}" + (f" {caveat}" if caveat else "")
    elif inbox:
        who = "person is" if len(waiting) == 1 else "people are"
        answer = f"{len(waiting)} {who} waiting on a reply {scope}: {_first_names(waiting, full=True)}.{tail}"
    else:
        answer = f"{len(waiting)} {scope} {'is' if len(waiting) == 1 else 'are'} waiting on a reply: {_first_names(waiting, full=True)}.{tail}"
    return RecipeAnswer(
        answer=answer,
        surfaces=[_waiting_surface(waiting, unchecked=unchecked, scope=scope_note)], drawn=[],
        calls=list(result.calls), partial=partial,
        trace={"rows": len(rows), "waiting": len(waiting), "unchecked": unchecked, "repeat": again},
    )


def _sent_caveat(sent: str) -> str:
    """What a sent-mail check that was not complete means for a list of people waiting (the
    2026-09-26 deploy review, F-02): someone on it may already have been answered."""
    if sent == "all":
        return ""
    return ("Replies sent as new emails could not be checked, so some of these may already have been answered."
            if sent == "none" else
            "Only the newest sent emails were checked for replies, so some of these may already have been answered.")


# [checker, 8 Oct 2026] The queue for the model's own inbox read. ---------------------------
def waits_in_inbox(body: Any) -> bool:
    """Whether an `email_query` result is the inbox read with someone waiting on a reply."""
    return (isinstance(body, dict) and body.get("scope") == "inbox"
            and any(isinstance(r, dict) and r.get("needs_reply") for r in body.get("rows") or []))


def queue_for_model(body: Any, session: Any) -> list[dict[str, Any]]:
    """The waiting queue, drawn for the model's own call of the inbox read.

    Since 28 September "which customers need replying to?" is the model's, and the call it makes
    is the read this landing makes (`email_query` with no set). Its result was drawn by the read
    layer as a count and a table of everyone who wrote: no row could be opened, and the people
    already answered sat among those waiting, which is the screen `_waiting_surface` was written
    to replace. So the model's call draws the queue the Inbox landing draws: the people waiting,
    longest first, each row opening its thread, which is issued to this conversation as the
    landing issues it. Nobody waiting: nothing here, and the read layer's cards say who wrote.
    """
    if not waits_in_inbox(body):
        return []
    rows = [r for r in body.get("rows") or [] if isinstance(r, dict)]
    waiting = _longest_waiting_first([r for r in rows if r.get("needs_reply")])
    threads = [str(r.get("last_thread_id") or "") for r in waiting[:WAITING_SHOWN]]
    issue = getattr(session, "issue", None)
    if callable(issue) and any(threads):
        issue(*[t for t in threads if t])
    _scope, note = _reply_scope(body, rows)
    note = " ".join(filter(None, [note, _sent_caveat(str(body.get("sent_checked") or "all"))]))
    if len(waiting) > WAITING_SHOWN:
        note = " ".join(filter(None, [note, f"The {WAITING_SHOWN} longest waits are shown."]))
    unchecked = int((body.get("counts") or {}).get("unchecked") or 0)
    return [_waiting_surface(waiting, unchecked=unchecked, scope=note).as_ui()]
# [/checker] --------------------------------------------------------------------------------


def _open_waiting_threads(ctx: Ctx, body: dict[str, Any], waiting: list[dict[str, Any]]) -> None:
    """Make the queue walkable and its rows openable: one set of the threads being waited on."""
    from app.analytics import sets as working_sets

    threads = [str(r.get("last_thread_id") or "") for r in waiting]
    threads = [t for t in threads if t]
    if not threads:
        return
    issue = getattr(ctx.session, "issue", None)
    if callable(issue):
        issue(*threads)
    labels = {
        str(r.get("last_thread_id") or ""): str(r.get("customer_name") or r.get("last_subject") or "")[:60]
        for r in waiting if r.get("last_thread_id")
    }
    detail = {"tool": "email_query", "which": "waiting"}
    parent = working_sets.get(ctx.session, _set_id_of(body))
    if parent is not None:
        made = working_sets.derive(
            ctx.session, parent, members=threads, label="Waiting on a reply", step="correlate",
            kind="emails", labels=labels, detail=detail, focus=False,
        )
    else:
        # The inbox read starts from no set, so the queue is a set of its own.
        made = working_sets.create(
            ctx.session, kind="emails", members=threads, label="Waiting on a reply",
            provenance={**detail, "step": "correlate"}, labels=labels, focus=False,
        )
    _open_workflow(ctx, body, kind="emails", operation="reply", set_id=made.set_id)


def _since(when: Any, *, now: float | None = None) -> str:
    """How long ago, in the words a person would use. Worked out here because the Mac owns the
    clock and the shop's timezone; the renderer prints whatever string it is given."""
    import datetime as _dt

    text = str(when or "").strip()
    if not text:
        return ""
    # Gmail's own stamp is epoch milliseconds, which is what reaches here; an ISO string is
    # accepted too because the Shopify side speaks that. Anything else is handed back as it
    # came rather than guessed at — a wrong "3h ago" is worse than a date.
    if text.lstrip("-").isdigit():
        value = float(text)
        at = value / 1000.0 if abs(value) > 1e11 else value
    else:
        try:
            stamp = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=_dt.UTC)
        at = stamp.timestamp()
    seconds = (_dt.datetime.now(_dt.UTC).timestamp() if now is None else now) - at
    if seconds < 0:
        return "just now"
    if seconds < 90 * 60:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 36 * 3600:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _waiting_surface(waiting: list[dict[str, Any]], *, unchecked: int = 0, scope: str = ""):
    """The people waiting on us, as the thing the question asked for.

    This recipe used to hand its raw reads to `present()`, which built whatever the analytic
    results implied: a revenue RANKING of recent customers, a working set, a metric group, a
    table, and a second working set — 1,886 pixels, five cards, three of them titled "Recent
    customers", and not one of them saying who was waiting. The spoken answer named the three
    people correctly while the screen showed a leaderboard.

    So the answer is drawn from the rows the recipe already has, and says the three things the
    owner needs to decide without opening anything: who, what about, and how long they have
    been waiting. Tapping a row opens that thread — the thread id is on the row, so nothing has
    to be looked up again.
    """
    from app.surfaces import Freshness, Surface

    threads = []
    for row in waiting[:WAITING_SHOWN]:
        # The order numbers the THREADS name, when the correlation found any — that is what
        # the email is about — and the customer's recent orders otherwise. With how sure the
        # link between this person and these threads is, because the row is a decision to
        # reply and a wrong link is a reply to the wrong question.
        related = [str(o).lstrip("#") for o in (row.get("related_orders") or []) if o][:3]
        orders = [f"#{o}" for o in related] or [str(o) for o in (row.get("orders") or []) if o][:2]
        confidence = str(row.get("confidence") or "")
        count = int(row.get("thread_count") or row.get("threads") or 0)
        threads.append({
            "thread_id": str(row.get("last_thread_id") or ""),
            "from": str(row.get("customer_name") or row.get("customer_email") or "someone"),
            "subject": str(row.get("last_subject") or "(no subject)"),
            # What ties it to the shop, which is why this is one system and not two.
            # §26: the confidence in words, not in the correlator's own token. This line
            # read "#1938 · confident" on the glass — `confident` and `possible` are how
            # app/families/order_email.py grades a link, and neither is a thing a person
            # says. A certain link needs no adjective: the order number IS the claim. An
            # uncertain one must be visibly uncertain, because the row is a decision to
            # reply and a wrong link is a reply to the wrong question — so it says so.
            "snippet": " · ".join(filter(None, [
                # Where it came in: the store's contact form, whose subject is Shopify's own
                # "New customer message on …" and says nothing about what they asked.
                "contact form" if row.get("via") == "contact_form" else "",
                (f"maybe {', '.join(orders)}" if confidence == "possible" and orders
                 else ", ".join(orders)),
                "not sure which order" if confidence == "possible" and not orders else "",
                f"{count} threads" if count > 1 else "",
            ])),
            # How long they have waited — the figure the rows are ordered by, so the column
            # reads down from the longest wait rather than jumping about.
            "date": _since(int(waited)) if (waited := _waited_since(row)) else "",
            # The inbox read says who is a customer; a row from a set of customers is one.
            "known_customer": row.get("known_customer", True) is not False,
            "related_orders": related,
            "confidence": confidence[:12],
        })
    note = " ".join(filter(None, [scope, f"{unchecked} could not be checked." if unchecked else ""]))
    return Surface(
        surface_type="work_queue",
        ui_type="email_list",
        data={"title": "Waiting on a reply", "count": len(waiting), "threads": threads, "note": note},
        title="Waiting on a reply",
        subtitle=f"{len(waiting)} waiting" + (f" · {note}" if note else ""),
        freshness=Freshness(source="gmail", complete=not unchecked and not scope,
                            caveat=note or ""),
    )


# Which of the dock's places a set of each kind belongs to, so a listing lands the branch
# somewhere Home and Back can name. The reply queue lists CUSTOMERS and is the inbox.
SET_AREA = {"orders": "orders", "emails": "email", "customers": "email",
            "products": "products", "variants": "products"}


def _open_workflow(ctx: Ctx, body: dict[str, Any], *, kind: str, operation: str, set_id: str = "",
                   area: str = "") -> None:
    """A listing becomes something to work through: the branch takes its cursor to the top.
    "Next" is then arithmetic, which is the whole point.

    And the LISTING ITSELF becomes a stop on the trail. That is new, and it is what makes Back
    worth pressing: the owner starts at a list, opens a row, follows a relation, and the way
    back out was missing its first step — the list was never on the trail, because only
    records were, so the deepest Back he could reach was the first record he had opened.
    """
    from app.analytics import sets as working_sets
    from app.session.branch import LIST_KIND, Workflow

    set_id = set_id or _set_id_of(body)
    if not set_id:
        return
    ws = working_sets.get(ctx.session, set_id)
    if ws is None or not ws.members:
        return
    ctx.branch.set_id = ws.set_id
    # Before the first member, so the first tap on Next lands on it (app/commands.py
    # move_cursor counts from -1).
    workflow_id = f"wf_{int(time.time() * 1000) % 10**9:09d}"
    ctx.branch.workflow = Workflow(workflow_id=workflow_id, set_id=ws.set_id, kind=kind, label=ws.label, operation=operation, cursor=-1, total=len(ws.members))
    ctx.branch.enter(area=area or SET_AREA.get(kind, ""), kind=LIST_KIND, ref=ws.set_id,
                     label=ws.label, set_id=ws.set_id, set_kind=kind, set_label=ws.label,
                     total=len(ws.members), operation=operation, workflow_id=workflow_id)


# ------------------------------------------------------------------------------ orders

# What each place is called on the trail, so a Back that lands on one can name it.
AREA_LABELS = {"orders": "Orders", "email": "Inbox", "sales": "Sales", "products": "Products"}


def _arrived(ctx: Ctx, area: str) -> None:
    """This half is now in this place.

    A landing is a stop on the trail, and the place a Home goes back to. It is recorded here
    rather than in the command that names the recipe, because a landing that could not be
    drawn is not somewhere the owner arrived — and the two landings that open a working set
    refine this stop with the set a moment later (`_open_workflow`).
    """
    from app.session.branch import LANDING_KIND

    ctx.branch.enter(area=area, kind=LANDING_KIND, ref=area, label=AREA_LABELS.get(area, area))


# How far back the Orders landing looks for an order still to go out, before the thirty days
# its list shows. An unfulfilled order older than the list's window was absent from the answer
# that said "Nothing is waiting to go out" (the round-12 deploy review, F-02). The second read
# is the 335 days that END where the list's window begins, so the two never overlap and
# together are the year of orders the server keeps (app/analytics/periods.py MAX_DAYS); 335
# days is also within what one query may cost (app/analytics/query.py MAX_COST, a point per
# thirty days).
WINDOW_DAYS = 30
OLDER_DAYS = 335
WAITING_LIMIT = 25


def _orders_plan(ctx: Ctx) -> ReadPlan | None:
    """What must go out, and what came in, and whether anything older is still waiting. Three
    independent reads, in parallel."""
    return ReadPlan([
        Read("open", "commerce_query", {
            "entity": "orders", "period": f"last_{WINDOW_DAYS}_days", "filters": {"fulfillment": "unfulfilled"},
            "sort": [{"metric": "age_days", "direction": "desc"}], "limit": WAITING_LIMIT, "title": "To go out",
        }, source="shopify", cost=120.0),
        Read("today", "commerce_query", {
            "entity": "orders", "period": "today", "sort": [{"metric": "placed_at", "direction": "desc"}],
            "limit": 25, "title": "Today",
        }, source="shopify", cost=120.0),
        # Not staged as it lands: the render decides whether its list is drawn. `days_ago` puts
        # its end at the midnight the 30-day window starts from (app/analytics/periods.py _days).
        Read("older", "commerce_query", {
            "entity": "orders", "period": {"days": OLDER_DAYS, "days_ago": WINDOW_DAYS},
            "filters": {"fulfillment": "unfulfilled"},
            "sort": [{"metric": "age_days", "direction": "desc"}], "limit": WAITING_LIMIT, "title": "Still to go out",
        }, source="shopify", cost=120.0, draws=False),
    ], label="landing_orders")


def _rows(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    return [r for r in (body.get("rows") or []) if isinstance(r, dict)]


def _call_named(result: ReadResult, node: str):
    """The tool call behind a read node, so the card is drawn from exactly that read."""
    body = result.values.get(node)
    for call in result.calls:
        if getattr(call, "ok", False) and getattr(call, "result", None) is body and body is not None:
            return call
    return None


def _order_ref(row: dict[str, Any]) -> str:
    return str(row.get("order_id") or row.get("order_number") or "")


def _waiting_rows(open_body: Any, older_body: Any) -> tuple[list[dict[str, Any]], int]:
    """Every order still to go out that the two reads returned, once each and oldest first,
    and how many there are in all. The two windows do not overlap, so the count is the sum of
    each read's own; never fewer than the rows themselves."""
    def total(body: Any) -> int:
        shown = len(_rows(body))
        held = body.get("row_count") if isinstance(body, dict) else None
        return held if isinstance(held, int) and held >= shown else shown

    merged: dict[str, dict[str, Any]] = {}
    for row in _rows(older_body) + _rows(open_body):
        merged.setdefault(_order_ref(row), row)
    rows = sorted(merged.values(), key=lambda r: -float(r.get("age_days") or 0))
    return rows, max(total(open_body) + total(older_body), len(rows))


def _to_go_out_surface(rows: list[dict[str, Any]], count: int, *, window: str, note: str, caveat: str = "",
                       currency: str = "GBP"):
    """The orders still to go out, on a card that says what the read could not vouch for.

    Drawn by the landing itself when the read of older orders failed or came back incomplete:
    the 30-day list's own card would say nothing of it, and with nothing waiting in the window
    there would be no card at all — the answer would be one sentence over a blank half.
    `caveat` is the short form for the subtitle and freshness line, which are cut at 80
    characters; it is the note itself when none is given."""
    from app.analytics.present import _order_list
    from app.surfaces import Freshness, Surface

    listed = _order_list({"rows": rows[:WAITING_LIMIT], "totals": {"orders": count}, "title": "To go out",
                          "truncated": count > len(rows[:WAITING_LIMIT]), "period": {"label": window}}, currency)
    data = dict(listed[0]["data"]) if listed else {"title": "To go out", "query": window, "orders": [], "count": 0,
                                                    "truncated": False, "value": ""}
    data.update({"note": note, "complete": False})
    caveat = caveat or note
    return Surface(surface_type="order_list", ui_type="order_list", data=data, title="To go out", subtitle=caveat,
                   freshness=Freshness(source="shopify", complete=False, caveat=caveat))


def _orders_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    open_body, today_body = result.values.get("open"), result.values.get("today")
    older_body = result.values.get("older")
    if not isinstance(open_body, dict) and not isinstance(today_body, dict):
        return RecipeAnswer(answer="", defer="the order reads did not answer")
    _arrived(ctx, "orders")
    today = _rows(today_body)
    # A read that did not answer is not an empty list. Before this, the open-orders read
    # failing while today's answered said "Nothing is waiting to go out." — a false
    # operational answer on the one question this landing exists for (the 2026-09-28 deploy
    # review, round 9, E-06). Each half now says it could not be read, and the answer is
    # marked partial so the card says so too.
    open_read, today_read = isinstance(open_body, dict), isinstance(today_body, dict)
    older_read = isinstance(older_body, dict)
    # A read that answered but says it is not complete (the order cache still filling after a
    # restart) is not an empty list either: "nothing" is said only of a complete read. An
    # incomplete one says none are held SO FAR and that more may exist, and the answer is
    # partial (the round-10 deploy review, F-02 — the empty branch used to be taken whatever
    # `complete` said, with the hedge appended after a sentence it did not qualify).
    open_whole = open_read and open_body.get("complete") is not False
    today_whole = today_read and today_body.get("complete") is not False
    older_whole = older_read and older_body.get("complete") is not False
    # What is waiting is the 30-day list and whatever the read of the months before it found,
    # as one list oldest first: the count and "the oldest" cover every order named anywhere in
    # the answer, so no later sentence can name an order older than the one called the oldest.
    waiting, count = _waiting_rows(open_body, older_body if older_read else None) if open_read else ([], 0)
    beyond = bool(_rows(older_body)) and open_read
    window = _period_words(open_body, f"last {WINDOW_DAYS} days") if open_read else f"last {WINDOW_DAYS} days"
    # What the read of older orders could not vouch for, said wherever it matters.
    older_gap = ("" if older_whole else
                 f"Orders placed before the {window} could not be checked." if not older_read else
                 "The read of older orders is not complete, so more may be waiting.")
    # And what the 30-day read could not vouch for: its list is on the same card, so the card
    # says so too, not only the spoken hedge.
    open_gap = "" if open_whole or not open_read else f"The read of the {window} is not complete, so more may be waiting."
    own_card = open_read and not older_whole
    # The set the cursor walks is the operational one: the orders still to go out, oldest
    # first — the older read's when it found any, since the oldest is among them. On a day
    # with nothing waiting, today's orders are the set.
    primary = ("older" if beyond else "open") if waiting or not today_read else "today"
    body = {"open": open_body, "today": today_body, "older": older_body}[primary]
    if isinstance(body, dict):
        _open_workflow(ctx, body, kind="orders", operation="review")
    if waiting:
        oldest = waiting[0]
        shown = min(len(waiting), WAITING_LIMIT) if own_card else len(waiting)
        words = f"{_how_many({'row_count': count}, shown)} order{'s' if count != 1 else ''} to go out; the oldest is {str(oldest.get('order_number') or '').lstrip('#')} at {int(oldest.get('age_days') or 0)} days."
        if older_gap:
            words += f" {older_gap}"
    elif not open_read:
        words = "I could not read the orders still to go out, so I cannot say whether any are waiting."
    elif not open_whole:
        words = "None of the orders read so far are waiting to go out, but the read is not complete, so more may exist."
        if older_gap:
            words += f" {older_gap}"
    elif older_gap:
        words = (f"Nothing in the {window} is waiting to go out, but older orders could not be checked." if not older_read else
                 f"Nothing in the {window} is waiting to go out, but the read of older orders is not complete, so some may be waiting.")
    else:
        words = "Nothing is waiting to go out."
    waiting_words = words
    if not today_read:
        words += " Today's orders could not be read."
    elif today:
        words += f" {len(today)} order{'s' if len(today) != 1 else ''} today."
    elif not today_whole:
        words += " None of today's orders read so far, and more may exist."
    else:
        words += " None in today yet."
    surfaces = []
    if own_card:
        # Never zero cards and never a list that looks whole: the orders still to go out (or
        # none in the window), with what could not be checked written on the card.
        note = " ".join(gap for gap in (open_gap, older_gap) if gap) if waiting else waiting_words
        # With both reads short, one line names both, short enough for the card's caveat.
        caveat = "" if not (waiting and open_gap) else (
            f"The {window} read is incomplete; older orders could not be checked." if not older_read else
            f"The {window} read and the older orders read are both incomplete.")
        surfaces = [_to_go_out_surface(waiting, count, window=window, note=note, caveat=caveat,
                                       currency=str(open_body.get("currency") or "GBP"))]
        drawn = [c for c in (_call_named(result, "today"),) if c is not None]
    else:
        # The older orders' list is drawn when it holds any, first, beside the 30-day list:
        # an order still to go out is listed, never left out of a card that looks whole.
        order = ("older", "open", "today") if primary == "older" else (primary, "open" if primary == "today" else "today")
        drawn = [c for c in (_call_named(result, name) for name in order) if c is not None]
    return RecipeAnswer(answer=words + _hedge(open_body if open_read else today_body),
                      calls=list(result.calls), surfaces=surfaces, drawn=drawn,
                      partial=result.partial or not (open_read and today_read) or not (open_whole and today_whole) or not older_whole,
                      trace={"waiting": count, "today": len(today), "primary": primary,
                             "unread": [name for name, ok in (("open", open_read), ("today", today_read), ("older", older_read)) if not ok],
                             "incomplete": [name for name, ok, whole in (("open", open_read, open_whole), ("today", today_read, today_whole), ("older", older_read, older_whole)) if ok and not whole]})


# ------------------------------------------------------------------------------- inbox


# The recent threads beside the queue: a week of them, which is what the Inbox is a place for.
RECENT_DAYS = 7
RECENT_WHEN = "this week"
# How many MESSAGES the recent read lists. Gmail lists messages, newest first, and the search
# drops bulk mail and folds a thread's messages to one after the listing — so the bound is on
# emails, not on threads, and a listing that came back at it may have left part of the week
# unread (the round-12 deploy review, F-03).
RECENT_LIMIT = 12


def _recent_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:   # noqa: ARG001 — reads only the result
    body = result.values.get("inbox")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the inbox did not answer")
    threads = [t for t in (body.get("threads") or []) if isinstance(t, dict)]
    real = [t for t in threads if not t.get("likely_bulk")]
    # Said only of what was read. A listing that came back at its limit is the newest emails,
    # not the week: the answer says so, is partial, and draws a card of its own that says so,
    # because the search's own card would say nothing of where the read stopped.
    listed = body.get("listed")
    cut = isinstance(listed, int) and not isinstance(listed, bool) and listed >= RECENT_LIMIT
    trace = {"threads": len(real), "days": RECENT_DAYS, "listed": listed, "cut": cut}
    if cut:
        among = f"among the {RECENT_LIMIT} newest emails"
        rest = f"Older emails from {RECENT_WHEN} were not read."
        if real:
            newest = real[0]
            words = (f"{len(real)} thread{'s' if len(real) != 1 else ''} from people {among}; the newest is "
                     f"{newest.get('from') or 'someone'} about {newest.get('subject') or 'no subject'}. {rest}")
        else:
            words = f"Nothing from a person {among}. {rest}"
        note = f"Only the {RECENT_LIMIT} newest emails were read; older emails from {RECENT_WHEN} were not."
        return RecipeAnswer(answer=words, calls=list(result.calls), surfaces=[_recent_surface(real, note)], drawn=[],
                            partial=True, trace=trace)
    if not real:
        return RecipeAnswer(answer=f"Nothing from a person in the inbox {RECENT_WHEN}.", calls=list(result.calls),
                            partial=result.partial, trace=trace)
    newest = real[0]
    return RecipeAnswer(answer=f"{len(real)} threads from people {RECENT_WHEN}; the newest is {newest.get('from') or 'someone'} about {newest.get('subject') or 'no subject'}.",
                        calls=list(result.calls), partial=result.partial, trace=trace)


def _recent_surface(real: list[dict[str, Any]], note: str):
    """The recent threads from people, on a card that says where the read stopped. The rows are
    the search's own, shaped as the search's card shapes them (app/presentation.py)."""
    from app.presentation import MAX_THREADS, _thread_summary
    from app.surfaces import Freshness, Surface

    rows = [_thread_summary(t) for t in real[:MAX_THREADS]]
    return Surface(
        surface_type="email_list",
        ui_type="email_list",
        data={"title": "Email", "count": len(rows), "threads": rows, "note": note, "complete": False},
        title="Email",
        subtitle=note,
        freshness=Freshness(source="gmail", complete=False, caveat=note),
    )


def _inbox_plan(ctx: Ctx) -> ReadPlan | None:   # noqa: ARG001 — a place has one shape
    """The needs-reply queue's read of the inbox, and the recent threads beside it. Neither
    waits for the other."""
    return ReadPlan([
        Read("mail", "email_query", {"days": NEEDS_REPLY_DAYS}, source="gmail", cost=8.0, timeout_s=10.0, draws=False),
        Read("inbox", "gmail_search", {"query": "", "days": RECENT_DAYS, "limit": RECENT_LIMIT}, source="gmail", cost=2.0),
    ], label="landing_inbox", timeout_s=16.0)


def _inbox_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    queue = _needs_reply_render(ctx, result)
    recent = _recent_render(ctx, result)
    if queue.deferred and recent.deferred:
        return RecipeAnswer(answer="", defer=f"{queue.defer}; {recent.defer}")
    _arrived(ctx, "email")
    parts = [a.answer for a in (queue, recent) if not a.deferred and a.answer]
    # Half of the landing that did not answer is said as unread, and the answer is partial —
    # the rule `_orders_render` keeps for the Orders landing (the 2026-09-28 deploy review,
    # round 9, E-06). Silence would leave the recent threads standing in for "nobody waiting".
    if queue.deferred:
        parts.append("I could not read who is waiting on a reply.")
    if recent.deferred:
        parts.append("I could not read the recent threads.")
    surfaces = list(queue.surfaces) if not queue.deferred else []
    # The queue is the recipe's own card; the recent threads are drawn from the search read,
    # unless the read stopped short of the week and the recent half drew its own card saying so.
    surfaces += list(recent.surfaces) if not recent.deferred else []
    drawn = [c for c in [_call_named(result, "inbox")] if c is not None] if not recent.deferred and recent.drawn is None else []
    return RecipeAnswer(answer=" ".join(parts), calls=list(result.calls), surfaces=surfaces, drawn=drawn,
                      partial=result.partial or queue.partial or recent.partial or queue.deferred or recent.deferred,
                      trace={"queue": (queue.trace or {}).get("waiting"), "threads": (recent.trace or {}).get("threads")})


# ------------------------------------------------------------------------------- sales


def _sales_plan(ctx: Ctx) -> ReadPlan | None:
    return ReadPlan([
        Read("agg", "commerce_aggregate", {
            "entity": "orders", "period": "last_7_days", "metrics": ["revenue", "orders", "aov"],
            "compare": True, "view": "metrics", "title": "This week",
        }, source="shopify", cost=120.0),
        Read("today", "commerce_aggregate", {
            "entity": "orders", "period": "today", "metrics": ["revenue", "orders"], "view": "metrics", "title": "Today",
        }, source="shopify", cost=120.0),
        Read("top", "commerce_aggregate", {
            "entity": "order_line_items", "period": "last_7_days", "group_by": ["product"],
            "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}],
            "limit": 5, "view": "ranking", "title": "Selling this week",
        }, source="shopify", cost=120.0),
    ], label="landing_sales")


def _week_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:   # noqa: ARG001 — reads only the result
    body = result.values.get("agg")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the read layer did not answer")
    totals = body.get("totals") or {}
    period = _period_words(body)
    line = _totals_line(totals, period, str(body.get("currency") or "GBP"))
    # The engine's shape is {metric: {"from", "to", "delta", "pct"}}: the comparison was asked
    # for, so it is said.
    compare = body.get("compare") if isinstance(body.get("compare"), dict) else {}
    change = compare.get("change") if isinstance(compare.get("change"), dict) else {}
    moved = change.get("revenue") if isinstance(change.get("revenue"), dict) else change.get("orders")
    if isinstance(moved, dict) and isinstance(moved.get("pct"), (int, float)):
        pct = moved["pct"]
        before = _period_words(compare, fallback="the period before")
        line += f" That is {abs(pct):.0f}% {'up on' if pct >= 0 else 'down on'} {before}."
    return RecipeAnswer(answer=line + _hedge(body), calls=list(result.calls), partial=result.partial, trace={"period": period})


def _sales_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    week = _week_render(ctx, result)
    if week.deferred:
        return week
    _arrived(ctx, "sales")
    words = week.answer
    today = result.values.get("today")
    if isinstance(today, dict) and isinstance(today.get("totals"), dict) and today["totals"]:
        # Today's figure is said, not drawn: two metric cards on an 8-inch screen is one too
        # many, and "today so far" is a number the owner hears and moves on from.
        totals = today["totals"]
        revenue, orders = totals.get("revenue"), totals.get("orders")
        if isinstance(revenue, (int, float)):
            words += f" Today so far, {_money(revenue, str(today.get('currency') or 'GBP'))}"
            words += f" on {int(orders)} order{'s' if int(orders) != 1 else ''}." if isinstance(orders, (int, float)) else "."
    drawn = [c for c in (_call_named(result, "agg"), _call_named(result, "top")) if c is not None]
    return RecipeAnswer(answer=words, calls=list(result.calls), drawn=drawn, partial=result.partial,
                      trace={"today": bool(today), "top": len(_rows(result.values.get("top")))})


# ---------------------------------------------------------------------------- products


def _products_plan(ctx: Ctx) -> ReadPlan | None:
    return ReadPlan([
        Read("top", "commerce_aggregate", {
            "entity": "order_line_items", "period": "last_30_days", "group_by": ["product"],
            "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}],
            "limit": 8, "view": "ranking", "title": "Best sellers, 30 days",
        }, source="shopify", cost=120.0),
        Read("stock", "inventory_query", {"period": "last_7_days", "limit": 8}, source="shopify", cost=120.0),
    ], label="landing_products")


def _products_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    """The best seller and what is closest to running out. A read that did not answer is said
    as unread and the answer is partial, never "Nothing sold" or "Nothing is close to running
    out" — the Orders landing's rule (E-06), which this landing had the same hole for."""
    top = _rows(result.values.get("top"))
    stock = _rows(result.values.get("stock"))
    top_read, stock_read = isinstance(result.values.get("top"), dict), isinstance(result.values.get("stock"), dict)
    if not top_read and not stock_read:
        return RecipeAnswer(answer="", defer="the product reads did not answer")
    _arrived(ctx, "products")
    words = []
    if not top_read:
        words.append("I could not read this month's best sellers.")
    elif top:
        first = top[0]
        label = str(first.get("label") or first.get("product") or "").strip()
        units = first.get("units")
        words.append(f"Best seller this month: {label}" + (f", {int(units)} units." if units is not None else "."))
    else:
        words.append("Nothing sold this month.")
    if not stock_read:
        words.append("I could not read the stock levels, so I cannot say what is close to running out.")
    elif stock:
        first = stock[0]
        cover = first.get("days_cover")
        line = f"Closest to running out: {str(first.get('label') or '').strip()}"
        if isinstance(cover, (int, float)):
            line += f", about {cover:.0f} days of cover"
        words.append(line + ".")
    else:
        words.append("Nothing is close to running out.")
    drawn = [c for c in (_call_named(result, "top"), _call_named(result, "stock")) if c is not None]
    return RecipeAnswer(answer=" ".join(words), calls=list(result.calls), drawn=drawn,
                      partial=result.partial or not (top_read and stock_read),
                      trace={"top": len(top), "stock": len(stock),
                             "unread": [name for name, ok in (("top", top_read), ("stock", stock_read)) if not ok]})


# --------------------------------------------------------------------------- registration

register(Recipe(
    recipe_id="landing_orders", read_primitives=("commerce_query",), parallel_nodes=(("open", "today", "older"),),
    ui="order_list", cache_policy=CACHE_ANALYTICS, target_ms=1500, plan=_orders_plan, render=_orders_render,
))
register(Recipe(
    recipe_id="landing_inbox", read_primitives=("email_query", "gmail_search"), parallel_nodes=(("mail", "inbox"),),
    ui="email_list", cache_policy=CACHE_EMAIL, target_ms=4000, plan=_inbox_plan, render=_inbox_render,
))
register(Recipe(
    recipe_id="landing_sales", read_primitives=("commerce_aggregate",), parallel_nodes=(("agg", "today", "top"),),
    ui="metric_group", cache_policy=CACHE_ANALYTICS, target_ms=2500, plan=_sales_plan, render=_sales_render,
))
register(Recipe(
    recipe_id="landing_products", read_primitives=("commerce_aggregate", "inventory_query"), parallel_nodes=(("top", "stock"),),
    ui="ranking", cache_policy=CACHE_ANALYTICS, target_ms=2500, plan=_products_plan, render=_products_render,
))


def _open_area(ctx: CommandCtx) -> Outcome:
    """A dock icon. The command names the recipe; the route runs it (a command is synchronous
    and reads nothing itself — see app/commands.py — and a landing is three reads)."""
    area = ctx.arg("area") or ctx.arg("kind")
    recipe_id = AREAS.get(area)
    if not recipe_id:
        return Outcome.refused("unknown_area", f"There is no landing called {area!r}. The dock has {', '.join(AREAS)}.")
    return Outcome(answer="", changed={"recipe": recipe_id, "area": area})


register_command(Command("open.area", "Open a dock landing", _open_area, voice=False))
