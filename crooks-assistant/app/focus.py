"""What the answer is about — and only that — on the screen (DEC-069, 7 October 2026).

George, 7 October: "today I asked for the email reply to [a customer] and it showed [a customer]'s
total orders as a customer, then some random email from someone else, today's email threads and
today's orders when all I wanted to see was the reply to [a customer]."

`present()` draws a card for every read a turn made. Most of those reads are how CLIVE found the
thing — the customer looked up for his address, the inbox searched for his thread, today's
orders checked for a match — and the answer is about one of them, or about a change prepared
from them. This module takes the answer's cards out of that deck, by three rules over the cards
themselves and never over the words (MAP rule 7: nothing matches what was said), in order:

1. A CHANGE wins. A card waiting for his gesture, a step towards one (which variant), an email
   being written, a form being built: those are the screen, and nothing read on the way to them
   is. "The reply to [a customer] and nothing else." Two kinds of card stay beside it, because
   they are about the change and not how it was found: the attention lines of the record the
   change is to ("Chargeback open" beside a refund of that order), and a screen's remote.
2. Otherwise, a RECORD read in full wins over the searches that found it: an order read whole,
   a thread opened, a customer's history, an objective, or a workspace composed over a record
   that a read this turn returned whole. The lists and the one-line finds that led there are set
   aside; numbers and summaries stay beside the record. An order asked for by its own id or
   number is never one of those finds, even drawn as its line ("put 1938 and 1940 side by side":
   `records_asked_for`). A workspace composed over a record that only came up on a listing is
   not a record read in full: there the listings are the answer.
3. Otherwise the answer IS the listings and the numbers ("how many orders today"), and every
   card stays.

What it never sets aside, whatever the rule: an error (a failure is always said — `present()`
adds those after this has run, so they cannot reach it), any change card (rule 1 keeps them
all), and the tablet's bookkeeping. Nothing here reads, stages or invents: it only chooses among
cards `present()` already built from what the tools returned.
"""

from __future__ import annotations

from typing import Any

# The cards that are a change, or the thing a change is being made from: rule 1.
TASK = frozenset({"confirmation", "batch_action", "variant_picker", "email_compose", "workspace"})
# Cards that are the tablet's bookkeeping rather than an answer, and errors: never set aside.
ALWAYS = frozenset({"context_stack", "workspace_plan", "error"})
# Cards that are how a record was found: a listing, a one-line find, a choice between matches.
LISTINGS = frozenset({"order_list", "email_list", "customer_list", "order_match", "working_set"})
# Composed or opened records that are one thing in full.
WHOLE = frozenset({"email_thread", "customer_workspace", "order_workspace", "objective", "screen_remote"})
# The composed ones: a record in full only when a read returned that record whole this turn.
COMPOSED = frozenset({"customer_workspace", "order_workspace"})

CHANGE, RECORD, LISTING = "change", "record", "listing"


def _data(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _kind(item: Any) -> str:
    return str(item.get("type") or "") if isinstance(item, dict) else ""


def in_full(item: dict[str, Any], read_whole: frozenset[str] | None = None) -> bool:
    """Whether this card is one record read in full — what rule 2 stands on. `read_whole`, when
    given, is the records a read returned whole this turn (`records_read_whole`): a composed
    workspace counts only over one of them, not over a record it found on a listing."""
    kind, data = _kind(item), _data(item)
    if data.get("empty") or data.get("shell"):
        return False
    if kind == "order":
        return bool(data.get("detail"))
    if kind == "customer":
        return bool(data.get("history") or data.get("timeline"))
    if kind in COMPOSED and read_whole is not None:
        return str(data.get("ref") or "") in read_whole
    return kind in WHOLE


def records_read_whole(items: list[dict[str, Any]]) -> frozenset[str]:
    """The records a read returned whole, from the cards it drew before any workspace was
    composed over them: an order's detail, a customer's history, an opened thread."""
    refs = set()
    for item in items or []:
        if isinstance(item, dict) and _kind(item) in ("order", "customer", "email_thread") and in_full(item):
            data = _data(item)
            refs.add(str(data.get("order_id") or data.get("customer_id") or data.get("thread_id") or ""))
    return frozenset(refs - {""})


def _beside_a_change(item: dict[str, Any], refs: set[str]) -> bool:
    """Whether a card stays beside a change waiting for him (rule 1): the attention lines of the
    record a change is to — the risk he reads before he holds it — and a screen's remote, which
    is a control and not a search. `refs` is what the changes on the screen are to."""
    kind = _kind(item)
    if kind == "screen_remote":
        return True
    return kind == "attention" and str(_data(item).get("for") or "") in refs


def records_asked_for(calls: Any) -> frozenset[str]:
    """The orders a read this turn asked for by the order's own id or number, whatever card
    `present()` drew for each: one read whole (`shopify_order_detail`), or one looked up by its
    number and found alone (`shopify_find_order` matched on `name:<number>`, one order back).
    "Put 1938 and 1940 side by side" asks for both, and one of them may be drawn as its line
    without detail: it is still what the answer is about, not a search that found something
    else (rule 2). Read from the calls the model made and what they returned, never from his
    words (MAP rule 7)."""
    out: set[str] = set()
    for call in calls or []:
        result = getattr(call, "result", None)
        if not getattr(call, "ok", False) or not isinstance(result, dict):
            continue
        name = str(getattr(call, "name", "") or "")
        if name == "shopify_order_detail":
            out.add(str(result.get("order_id") or ""))
        elif name == "shopify_find_order" and str(result.get("matched_on") or "").startswith("name:"):
            orders = [o for o in result.get("orders") or [] if isinstance(o, dict)]
            if len(orders) == 1:
                out.add(str(orders[0].get("order_id") or ""))
    return frozenset(out - {""})


def _found_on_the_way(item: dict[str, Any], kept_orders: set[str]) -> bool:
    """Whether a card is one of the searches a record read in full was found by (rule 2).
    `kept_orders` is every order this answer is about: read in full, or asked for by its own
    id or number (`records_asked_for`) — an order of those is never a find, drawn whole or as
    its line."""
    kind, data = _kind(item), _data(item)
    if kind in ALWAYS or kind in TASK:
        return False
    if data.get("empty"):
        return True
    if kind in LISTINGS:
        return True
    if kind == "order" and str(data.get("order_id") or "") in kept_orders:
        return False
    if kind in ("order", "customer"):
        return not in_full(item)
    if kind == "attention":
        return str(data.get("for") or "") not in kept_orders
    return False


def answer_cards(items: list[dict[str, Any]], why: dict[str, Any] | None = None, *,
                 read_whole: frozenset[str] | None = None,
                 asked: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """The cards this answer is about, in the order `present()` built them. `why`, when given,
    is told which rule decided and the kinds of the cards set aside (for the interaction record:
    app/observability/interactions.py). `read_whole` is `records_read_whole` of the cards before
    a workspace was composed (see `in_full`). `asked` is `records_asked_for` of the turn's
    calls: an order in it is never set aside as a find by rule 2."""
    cards = [item for item in items or [] if isinstance(item, dict)]
    if any(_kind(item) in TASK for item in cards):
        rule = CHANGE
        refs = {str(_data(item).get("entity_ref") or "") for item in cards if _kind(item) in TASK} - {""}
        kept = [item for item in cards if _kind(item) in TASK or _kind(item) in ALWAYS or _beside_a_change(item, refs)]
    elif any(in_full(item, read_whole) for item in cards):
        rule = RECORD
        orders = {str(_data(item).get("order_id") or "") for item in cards if _kind(item) == "order" and in_full(item)}
        kept = [item for item in cards if not _found_on_the_way(item, (orders | set(asked or ())) - {""})]
    else:
        rule = LISTING
        kept = cards
    if why is not None:
        aside = [_kind(item) for item in cards if not any(item is k for k in kept)]
        why.update({"rule": rule, "set_aside": aside[:12]})
    return kept
