"""What the tablet shows, chosen from what the tools returned — never from the prose.

The answer Claude speaks is free text. What the screen shows beside it is not: it is a short
list of `ui` items, each one a type from a fixed vocabulary and a bounded, whitelisted slice of
the data a tool actually returned this turn. The tablet renders those types with its own DOM
code and ignores anything else. Claude cannot ask for a component, cannot supply markup, and
cannot put a value on screen that a tool did not return — the prose and the cards are built
from the same tool results, so they cannot disagree.

Two rules, and both are here rather than on the tablet so that a test can hold them:

- Bounded. Every list is capped and every string truncated. A payload the tablet cannot
  render is a payload it should never have been sent.
- Whitelisted. Values are copied key by key. A new field in a tool result reaches the screen
  only when a line is added here to carry it.

Nothing in this module decides what a tool may do. The gate (app/tools/gate.py) did that
before the tool ran; this runs afterwards and only shapes what is already known.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.actions import grammar
from app.providers.base import ToolCall
from app.session.models import Session
from app.tools.gate import Disposition, classify

log = logging.getLogger("crooks.presentation")

# The component vocabulary. The tablet renders exactly these; anything else is dropped there
# too, so a typo here cannot become a blank card.
UI_TYPES = frozenset({
    "assistant", "order", "order_list", "customer", "customer_list", "product", "inventory",
    "sales_summary", "email_list", "email_thread", "email_draft", "attention", "confirmation",
    "success", "error", "context_stack",
    # the read layer's cards (app/analytics/present.py)
    "metric_group", "ranking", "table", "comparison", "variant_matrix", "trend", "working_set",
    # bulk changes (app/actions/batch.py): the card before the gesture, the count after it
    "batch_action", "batch_result",
    # what this build can do, grouped (app/capabilities/surface.py). Built from the manifest
    # rather than from a tool result: the manifest is read from the registry, not the shop.
    "capability",
    # the answer to a summary question, as compact rows (app/summaries.py): "returning
    # customers today · 1", one row per person, a tap that opens the full workspace. §13 —
    # D-4 answered exactly that question with seven full customer profiles.
    "summary_list",
    # who is waiting on whom in one thread (app/families/order_email.py): "Waiting since 5h
    # ago · last from Mia · no reply from us". Built by the recipe from the thread's own
    # reply state, never from the prose.
    "reply_state",
    # which variant the owner means (app/families/order_edit.py): candidate rows read from
    # the catalogue, a quantity stepper, and one button that asks the Mac to PREPARE the
    # addition. Nothing on it changes anything; the confirmation card that follows still
    # waits for the gesture. Built by a recipe, bounded by `variant_picker` below.
    "variant_picker",
    # an email being written (app/families/compose.py). The one card on the tablet with
    # editable fields on it, and it is still not a way round the write boundary: a keystroke
    # posts `compose.field` — an id, a field NAME and the typed value — which the Mac
    # validates into its own copy of the composer, and the execution arguments are built
    # from that copy when a gesture asks for them. Built by the family, not from a tool
    # result: nothing has been read and nothing has been staged when it is drawn.
    "email_compose",
    # something being BUILT, before anything is proposed (app/families/_workspace.py): the
    # discount code of §12, the order of §11, the store credit of §13. The same card for
    # all three — fields, a small closed choice or two, the facts the Mac read, and the
    # button that would prepare it — and the same rule as the composer above: a keystroke
    # posts the field's NAME and the characters, the Mac validates them into its own copy,
    # and the execution arguments are built from that copy when a gesture asks for them.
    "workspace",
    # one record, composed (app/workspace.py). Not another card per read: the TASK's surface,
    # built over the canonical entity of §6 and hydrated section by section, which is what
    # D-3 asked for and did not get — `turn_1e7f630eae7e` held two orders and £120 of
    # lifetime value and drew an email list. Each section carries its own state, so a new
    # read enriches the workspace and an empty or failed one cannot destroy it (§27).
    "customer_workspace", "order_workspace",
    # the workspace's own header, while it fills in (§15, §27 — app/progressive.py): its name
    # and one line per section, each in one of five states. The only card in this vocabulary
    # that `present()` never builds — it is staged by the progressive layer, from the reads
    # the turn has planned and landed, and patched in place as each section arrives.
    "workspace_plan",
    # the owner's app becoming the remote for one of his screens (round 9, screen_remote in
    # app/tools/display_tools.py, and screen_play when a video goes on one): the screen's id and
    # name only. The tablet opens its remote when it draws this card (web/remote.js), and the
    # card stays to open it again.
    "screen_remote",
    # one of the owner's objectives, in the shape of its kind (round 12, app/objectives/cards.py):
    # a project's stages with the one it is at, delegated tasks by person, or what CLIVE is doing
    # and what is next. Drawn when the model opens, shows or changes one, by web/objective-cards.js.
    "objective",
    # the orders that most nearly fit what he said when nothing fits all of it (app/customers/
    # match.py): one with the line that says why, or two or three and one short question. Never
    # drawn as an order card, because it is not one he named; a tap on a row opens the order.
    # Drawn by web/customers.js.
    "order_match",
})
MAX_BATCH_ROWS = 50
ANALYTIC_TOOLS = frozenset({"commerce_aggregate", "commerce_query", "inventory_query", "email_query"})
# The read tools that put a workspace on the owner's screen (app/families/_workspace.py).
# Each returns the Mac's own card under `_surfaces`, and `_from_result` below takes it as it
# is rather than re-shaping state that never came from the shop.
WORKSPACE_TOOLS = frozenset({"shopify_discount_open", "shopify_order_open", "shopify_order_build", "shopify_store_credit"})
# The objective tools that open, show or change one objective, each returning its card under
# `_surfaces` (app/objectives/tools.py). objective_list returns none: it is the model's lookup.
OBJECTIVE_TOOLS = frozenset({"objective_open", "objective_show", "objective_note"})

# One of the owner's screens (app/displays/store.py _ID).
_SCREEN_ID = re.compile(r"^scr_[0-9a-f]{12}$")

# Bounds. The tablet is 8 inches wide; more than this is a spreadsheet, not an answer.
MAX_ORDERS = 10
MAX_ITEMS = 12
MAX_CUSTOMERS = 6
MAX_PRODUCTS = 4
MAX_VARIANTS = 16
MAX_MEASUREMENTS = 8
MAX_BREAKDOWN_DAYS = 31
MAX_THREADS = 10
MAX_MESSAGES = 6
MAX_BODY_CHARS = 2_000
MAX_SNIPPET_CHARS = 300
MAX_TEXT_CHARS = 160
MAX_NOTE_CHARS = 400
MAX_EMAIL_BODY_CHARS = 2400
MAX_ATTENTION = 6
MAX_CONTEXT = 6

# The interaction grammar: how the owner authorises a proposal. The card names one of these
# and the tablet renders it; a kind the tablet does not implement renders as unavailable, never
# as a plain button. The table and its words live in app/actions/grammar.py.
INTERACTIONS = frozenset(grammar.KINDS)
# The dead time after an action card appears before a tap can count. A finger lifting off the
# orb must never land on a card that materialised under it.
ARMED_AFTER_MS = grammar.ARMED_AFTER_MS

# "What are we low on?" — the threshold that makes a variant an exception, not a row.
LOW_STOCK_AT = 5

_CURRENCY_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}

# Errors, named calmly. The spoken answer already explains; the card gives one recovery.
_TURN_ERRORS: dict[str, tuple[str, str, str]] = {
    # error_kind: (service, title, recovery)
    "speech": ("speech", "Couldn't understand that", "Hold and ask again, a little closer to the microphone."),
    "empty": ("speech", "Didn't catch that", "Hold the orb while you speak."),
    "audio_too_large": ("speech", "That recording was too long", "Ask it in a shorter sentence."),
    "lost_thread": ("assistant", "Lost the thread", "Ask again from the start."),
    "timeout": ("assistant", "That took too long", "Ask again."),
    "not_started": ("assistant", "Assistant still starting", "Wait a moment and ask again."),
    "usage_limit": ("assistant", "Claude usage limit reached", "Try again later."),
    "auth": ("assistant", "Claude needs signing in on the server", "On the server: run claude, then /login."),
    "max_turns": ("assistant", "Stopped part-way", "Ask a narrower question."),
    "api_error": ("assistant", "Assistant unavailable", "Try again in a moment."),
}


def present(
    calls: list[ToolCall] | None,
    *,
    session: Session | None = None,
    error_kind: str | None = None,
    writes: dict[str, Any] | None = None,
    question: str = "",
    pending: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """The `ui` list for one turn: the TASK's workspace where the task has one, context cards
    from the tool results, one error card per failed service, and the context stack when the
    conversation has accumulated one.

    `question` is what was asked, which is what decides the workspace (§3: intent first, not
    the last tool). It defaults to `session.heard` — set by /turn before a single read is
    issued — so the ordinary path needs to pass nothing and a caller with a better copy of
    the words may pass one. `pending` names sections whose read has not landed yet, for
    progressive hydration; a section in it says "Reading…" rather than claiming to be empty.
    """
    items: list[dict[str, Any]] = []
    errors: dict[str, dict[str, Any]] = {}
    calls = _with_redraws(list(calls or []))
    capabilities = writes.get("capabilities") if isinstance(writes, dict) and isinstance(writes.get("capabilities"), dict) else {}

    # What a row on a card may offer, decided here rather than by the tablet
    # (app/actions/rows.py). Empty while changes are off.
    row_actions = _row_actions(writes)

    for index, call in enumerate(calls):
        if not call.ok:
            if _recovered(call, calls[index + 1:]):
                # The gate refused a call and the model then did it properly — looked the
                # record up, called again. The owner sees the outcome, not the stumble.
                continue
            error = _tool_error(call, session)
            errors.setdefault(error["data"]["service"], error)
            continue
        if call.proposal_id and str(call.proposal_id).startswith("batch_"):
            batch = session.batches.get(call.proposal_id) if session is not None else None
            if batch is not None and not any(
                i["type"] == "batch_action" and i["data"].get("batch_id") == batch.batch_id for i in items
            ):
                items.append(_batch_card(batch, writes=writes))
        elif call.proposal_id:
            proposal = session.proposal(call.proposal_id) if session is not None else None
            if proposal is not None and not any(
                i["type"] == "confirmation" and i["data"].get("proposal_id") == proposal.proposal_id for i in items
            ):
                items.append(_confirmation(proposal, writes=writes))
            continue
        if not isinstance(call.result, dict):
            continue
        for item in _from_result(call.name, call.result) + _family_cards(call.name, call.result, session):
            if item["type"] == "email_list" and row_actions.get("email_thread"):
                for thread in item["data"].get("threads") or []:
                    if thread.get("thread_id"):
                        thread["actions"] = row_actions["email_thread"]
            if item["type"] == "order" and item["data"].get("detail"):
                # The rail: which changes make sense for this order, decided on the Mac from
                # the order's own state and what the store has granted this Mac.
                item["data"]["actions"] = _actions(call.result, capabilities)
            if item["type"] == "email_thread":
                # The same rail for an email. Reply arms the microphone for this thread;
                # Archive is the row action the list already carries, on the thread itself.
                item["data"]["actions"] = _email_actions(item["data"], capabilities, row_actions.get("email_thread"))
            items.append(item)
            if item["type"] == "order" and item["data"].get("detail"):
                # What the order needs, read on the Mac, as its own card after the order.
                attention = _attention_items(call.result)
                if attention:
                    # And the first two of them ON the order, as one line each. §8 asks the
                    # order's FIRST VIEWPORT for critical attention, and the card beneath it
                    # was 709 px down a 671 px screen: an unread reply on a paid order was on
                    # the glass and out of sight. The card keeps the detail and the recovery
                    # words; this is the headline, tone and all.
                    item["data"]["attention_top"] = [
                        {"title": a["title"], "level": a["level"], "kind": a["kind"]}
                        for a in sorted(attention, key=lambda a: 0 if a.get("level") == "red" else 1)[:2]
                    ]
                    items.append(_ui("attention", {"items": attention, "for": item["data"].get("order_id")}))

    items = _merge(items)
    # The task's own surface, over the canonical entity rather than over the last result.
    # Everything the workspace now contains comes out of the deck: a customer touched by
    # three reads is one customer (§6), not a card each.
    items = _compose_workspace(items, calls, session=session, question=question, pending=pending)
    # Something being BUILT this turn — an order, a discount, a credit — is the task, and the
    # records read to build it are its evidence. The owner asked for a new order for the
    # customer who bought the hoodie; the order that proves who that is sits under the new one,
    # not over it (round 12: "it tries to pull up a customer screen first").
    items = [i for i in items if i["type"] == "workspace"] + [i for i in items if i["type"] != "workspace"]
    if session is not None:
        _remember(items, session)
        # §18, as a SWEEP rather than one renderer at a time. After `_remember`, which is
        # what issues the ids a card's own offers rest on, so a row this turn legitimately
        # showed keeps its ref and only a row pointing at nothing loses it.
        _withhold_dead_refs(items, session)

    if error_kind:
        service, title, recovery = _TURN_ERRORS.get(
            error_kind, ("assistant", "Something went wrong", "Ask again.")
        )
        errors.setdefault(service, _error(service, error_kind, title, recovery))

    out = _only_empty_when_nothing_else(items) + list(errors.values())
    if session is not None and len(session.context) >= 2:
        out.append(_ui("context_stack", {"entries": [dict(c) for c in session.context[:MAX_CONTEXT]]}))
    kept = [item for item in out if item["type"] in UI_TYPES]
    if len(kept) != len(out):
        # A type outside the vocabulary is dropped here, as it always has been — and it used
        # to be dropped SILENTLY, which is how D-15 ("records without a card") could happen
        # and leave nothing to read afterwards. A builder that named a card the tablet cannot
        # draw is a bug in this repository, and it says so on the Mac's own log.
        log.warning(
            "dropped %s: not in the card vocabulary (app/presentation.py UI_TYPES and web/ui.js RENDERERS)",
            ", ".join(sorted({item["type"] for item in out if item["type"] not in UI_TYPES})),
        )
    return kept


#: The read that puts back something this conversation already showed (app/tools/show_again.py).
AGAIN_TOOL = "show_again"


def _with_redraws(calls: list[ToolCall]) -> list[ToolCall]:
    """Each `show_again` followed by the reads it made, as if the model had made them.

    `show_again` reads a record again through the registered read tool and hands the result
    back under `_reads`. Drawing that read through the ordinary path — rather than a card built
    inside the tool — is what gives the record its rail, its attention lines and the workspace
    composition, from the same code and the same writes table as the first time it was drawn.
    """
    out: list[ToolCall] = []
    for call in calls:
        out.append(call)
        if call.name != AGAIN_TOOL or not call.ok or not isinstance(call.result, dict):
            continue
        for read in call.result.get("_reads") or []:
            if isinstance(read, dict) and isinstance(read.get("result"), dict) and read.get("tool") != AGAIN_TOOL:
                out.append(ToolCall(name=str(read.get("tool") or ""), args={}, ok=True, result=read["result"]))
    return out


# --------------------------------------------------------------- the task's own workspace


def _compose_workspace(
    items: list[dict[str, Any]],
    calls: list[ToolCall],
    *,
    session: Session | None,
    question: str = "",
    pending: tuple[str, ...] | list[str] = (),
) -> list[dict[str, Any]]:
    """Replace `TOOL RETURNS X → DRAW X CARD` with the task's own surface (§3).

    D-3 is the whole reason this function exists. `turn_1e7f630eae7e` asked for a customer's
    history, his order count, his lifetime spend and whether he was in Gmail. The Mac held all
    of it and the answer said all of it; the only NEW read was `gmail_search`, so the screen
    became an email list. The task was a customer workspace.

    What happens here, in order:

    1. every read this turn is folded into the conversation's canonical entities (§6), so a
       customer touched by three reads is one customer and a fourth read PATCHES him;
    2. the question is asked what workspace it wants (`app/workspace.py:desired`) — and the
       answer is usually None, which is correct: an aggregate question wants a summary (§13,
       another workstream) and a single lookup is already served by its own card;
    3. the workspace is filled from the entity, section by section, each section carrying its
       own state;
    4. the cards the workspace now CONTAINS come out of the deck, and it goes in front.

    Nothing is lost by step 4: a card is absorbed only when every record on it is on the
    workspace. A list of other orders, an analytic summary, an email thread opened in its own
    right — those are different surfaces and they stay.
    """
    if session is None:
        return items
    from app import entities, workspace

    graph = entities.graph_for(session)
    filled: set[str] = set()
    failed: set[str] = set()
    for call in calls:
        if call.ok and isinstance(call.result, dict):
            graph.ingest(call.name, call.result)
            filled.update(entities.FILLS.get(call.name, ()))
        elif not call.ok:
            # The read fell over. Which SECTION that leaves unreadable, so the section can say
            # so and the rest of the workspace can carry on standing (§27).
            failed.update(entities.FILLS.get(call.name, ()))
    # An inbox row says who the message is from AND which record it is about (§12), from the
    # graph rather than from a new read. Done before the workspace question, because the rows
    # are the same rows either way: a thread that ends up in a customer workspace's Inbox
    # carries the same context as one on a list of its own.
    _link_inbox(items, graph, session)
    said = question or str(getattr(session, "heard", "") or "")
    if not said:
        return items
    plan = workspace.desired(said, graph=graph, calls=calls)
    if plan is None or not plan.composes:
        return items
    built = workspace.compose(
        plan, graph=graph, session=session,
        filled=filled, failed=failed - filled, pending=pending,
    )
    if built is None or built["type"] not in UI_TYPES:
        return items
    held = _workspace_keys(built["data"], plan)
    kept = [item for item in items if not _absorbed(item, held)]
    return [built, *kept]


def _link_inbox(items: list[dict[str, Any]], graph: Any, session: Session) -> None:
    """What each inbox row is ABOUT, added from what the Mac holds (§12's inbox list).

    A row used to carry the sender, the subject, the date and a snippet. §12 asks it for the
    customer, the order, whether we owe a reply, how old it is and how much it matters —
    which is the difference between a picture of an inbox and somewhere to work from.

    Every value comes from the canonical graph, so this costs no read. The evidence rules are
    `app/context/graph.py`'s, deliberately: the sender's address matched EXACTLY against a
    customer the conversation already knows, and an order link only where that customer has
    exactly one order in hand — a name is not evidence and a guess on the thread the owner is
    about to reply to is worse than no link at all.

    §18 all the way through: a link is only offered where the ref is a shape the gate accepts
    and the conversation has been issued it, and the issuing happens here because the row
    showing the link IS the conversation being shown the record.
    """
    from app import workspace

    for item in items:
        if item["type"] != "email_list" or not isinstance(item.get("data"), dict):
            continue
        for row in item["data"].get("threads") or []:
            if not isinstance(row, dict):
                continue
            thread = graph.get("email_thread", row.get("thread_id"))
            person = graph.customer_of(thread.key) if thread is not None else None
            if person is None:
                person = graph.find_by_email("customer", row.get("from_email"))
            orders = graph.orders_of(person.key) if person is not None else []
            if thread is not None and graph.orders_of(thread.key):
                orders = graph.orders_of(thread.key)      # the thread named one itself
            if person is not None:
                link = workspace.link_for(session, "customer", person)
                if link:
                    row["customer_link"] = link
            # Exactly one, or the link is a guess. `app/context/graph.py` calls several
            # recent orders "possible" rather than confident, and a row has space for one.
            if len(orders) == 1:
                link = workspace.link_for(session, "order", orders[0])
                if link:
                    row["order_link"] = link
            row["needs_reply"] = bool(row.get("needs_reply") or (thread is not None and thread.get("awaiting_reply")))
            row["priority"] = _inbox_priority(row, person)


def _inbox_priority(row: dict[str, Any], person: Any) -> str:
    """How much this row matters, from facts already on it and nothing else.

    Three words, so the list can be read at a glance and sorted by a renderer without asking
    the Mac a second question. Never a score: a number invites the owner to believe a
    precision that is not there.
    """
    if row.get("needs_reply"):
        return "high"
    if row.get("likely_bulk"):
        return "low"
    return "normal" if person is not None or row.get("known_customer") else "unknown"


def _workspace_keys(data: dict[str, Any], plan: Any) -> frozenset[str]:
    """Every record the workspace now shows, by canonical key. What a card has to be entirely
    about before it may be taken out of the deck."""
    from app import entities

    keys = {plan.key}
    for section in (data.get("sections") or {}).values():
        for row in section.get("rows") or []:
            for field, kind in (("order_id", "order"), ("thread_id", "email_thread"),
                                ("customer_id", "customer")):
                found = entities.key(kind, row.get(field))
                if found:
                    keys.add(found)
    return frozenset(keys)


def _absorbed(item: dict[str, Any], held: frozenset[str]) -> bool:
    """Whether this card is now a part of the workspace rather than a surface of its own.

    Every record on the card must be on the workspace. "Every" matters: a list with one
    unheld row on it still says something the workspace does not, and a list with no rows at
    all says nothing either way and is left for `_only_empty_when_nothing_else` to judge.
    """
    from app import entities

    kind, data = item["type"], item["data"]
    if not isinstance(data, dict) or data.get("empty"):
        return False
    if kind == "customer":
        return entities.key("customer", data.get("customer_id")) in held
    if kind == "order":
        return entities.key("order", data.get("order_id")) in held
    if kind == "attention":
        return entities.key("order", data.get("for")) in held
    rows, field, of = {
        "customer_list": (data.get("customers"), "customer_id", "customer"),
        "order_list": (data.get("orders"), "order_id", "order"),
        "email_list": (data.get("threads"), "thread_id", "email_thread"),
    }.get(kind, (None, "", ""))
    if not rows:
        return False
    refs = [entities.key(of, row.get(field)) for row in rows if isinstance(row, dict)]
    return bool(refs) and all(ref in held for ref in refs)


def _only_empty_when_nothing_else(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An empty-state card is the ANSWER, or it is nothing.

    "No orders yesterday" is worth a card when it is what the turn found (D-15). It is noise
    above the card that IS the answer — a note being staged on the order a first, wider lookup
    missed; a customer list offered because the order number matched nobody. So: where the
    turn produced anything substantive, the empties go.
    """
    substantive = [item for item in items if not (isinstance(item.get("data"), dict) and item["data"].get("empty"))]
    return substantive if substantive else items


# --------------------------------------------------------------------------- per tool


def _family_cards(name: str, result: dict[str, Any], session: Session | None) -> list[dict[str, Any]]:
    """The cards a family draws for its own read tool, when the model calls it.

    Built by the family that owns the read (app/summaries.py, app/families/abandoned.py),
    which validates them against the surface contract, so nothing is re-shaped here. They were
    drawn by the word-matching lane until that was removed on 28 September 2026; since every
    sentence is now the model's, the model's call of the same tool is where they come from, and
    a summary question still gets its compact rows rather than a paragraph.
    """
    if name == "commerce_summary":
        from app import summaries

        period = result.get("period") if isinstance(result.get("period"), dict) else {}
        label = str(period.get("label") or "")
        fresh = summaries.freshness_of(result.get("coverage"))
        task = str(result.get("task") or "")
        if task == "returning_customers":
            surface = summaries.returning_customers(result, session=session, period=label or "today", freshness=fresh)
        elif task == "orders_attention":
            surface = summaries.attention_rows(result, session=session, period=label if result.get("period_asked") else "",
                                               freshness=fresh)
        elif task == "order_list":
            surface = summaries.order_rows(result, session=session, period=label or "today",
                                           set_id=str(result.get("set_id") or ""), freshness=fresh)
        else:
            return []
        return [surface.as_ui()]
    if name == "shopify_abandoned_checkouts":
        from app.families.abandoned import cards

        return [surface.as_ui() for surface in cards(result)]
    return []


def _from_result(name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if name in ("screen_remote", "screen_play"):
        # Round 9: "become the remote". The screen's id (not a secret: its key is) and name, and
        # the titles of what it shows, bounded; the remote asks for the rest itself, as the owner.
        # A video put on a screen (screen_play) draws the same card, so the app is its remote.
        screen_id = _text(result.get("screen_id"), 20)
        if not _SCREEN_ID.fullmatch(screen_id):
            return []
        showing = [_text(t, MAX_TEXT_CHARS) for t in _list_strings(result.get("showing"), 2)]
        return [_ui("screen_remote", {"screen_id": screen_id, "name": _text(result.get("screen"), 40),
                                      "showing": showing, "on": bool(result.get("on"))})]
    if name in ("gmail_compose_open", "gmail_compose_fill"):
        # The composer's card is built by the family that owns the context
        # (app/families/compose.py `compose_surface`), which copies it key by key and bounds
        # every string exactly as this file does — it is the Mac's own state, not a tool
        # result to be re-shaped here. Only well-formed items of the one type are taken, and
        # `present()` filters against UI_TYPES again on the way out.
        return [item for item in (result.get("_surfaces") or [])
                if isinstance(item, dict) and item.get("type") == "email_compose" and isinstance(item.get("data"), dict)]
    if name == AGAIN_TOOL:
        # What `show_again` drew from the Mac's own copy — a workspace composed again, a
        # composer, a half-built order, a list as it was shown. Every one of them is a card
        # this module or a family built for this conversation before, and each is checked
        # against the vocabulary again on the way out of `present()`.
        # A plain order or thread card never comes this way: those are read again and drawn
        # from the read (`_with_redraws`), which is where their rail is decided.
        return [item for item in (result.get("_surfaces") or [])
                if isinstance(item, dict) and item.get("type") in UI_TYPES - {"order", "email_thread"}
                and isinstance(item.get("data"), dict)]
    if name in WORKSPACE_TOOLS:
        # The workspace's card, for exactly the same reason: it is built by the family that
        # owns the context (app/families/_workspace.py `surface`), which copies it key by key
        # and bounds every string as this file does, because it is the Mac's own state and
        # not a tool result to be re-shaped here. Only well-formed items of the one type are
        # taken, and `present()` filters against UI_TYPES again on the way out.
        return [item for item in (result.get("_surfaces") or [])
                if isinstance(item, dict) and item.get("type") == "workspace" and isinstance(item.get("data"), dict)]
    if name in OBJECTIVE_TOOLS:
        # The objective's card, for the same reason again: built by app/objectives/cards.py from
        # CLIVE's own record, bounded key by key there, and taken here as it is.
        return [item for item in (result.get("_surfaces") or [])
                if isinstance(item, dict) and item.get("type") == "objective" and isinstance(item.get("data"), dict)]
    if name in ANALYTIC_TOOLS:
        from app.analytics.present import build, working_set_items

        return build(result, tool=name) + working_set_items(result)
    if name == "shopify_order_detail":
        return [_ui("order", _order(result, detail=True))]
    if name == "shopify_find_order":
        orders = [_order(o) for o in _list(result.get("orders"), MAX_ORDERS)]
        out: list[dict[str, Any]] = []
        if not orders and result.get("likely"):
            # Nothing fits all of it; these nearly do, each with why (app/customers/match.py).
            return [_ui("order_match", _order_match(result))]
        if not orders and result.get("suggested"):
            return [_ui("customer_list", _suggested(result))]
        if len(orders) == 1:
            out.append(_ui("order", orders[0]))
        elif orders:
            # Found by what the owner remembered, and more than one fits: the card is the
            # choice he is being asked to make (app/tools/shopify_tools.py _find_by_evidence).
            evidence = isinstance(result.get("asked"), dict)
            out.append(_ui("order_list", {
                "title": "Which order?" if evidence and result.get("ambiguous") else "Orders",
                "query": _text(result.get("query")), "orders": orders,
                "count": len(orders), "truncated": bool(result.get("truncated")) if evidence else False,
            }))
        matched = _list(result.get("customers_matched"), MAX_CUSTOMERS)
        if result.get("ambiguous") and matched:
            out.append(_ui("customer_list", {
                "title": "Which customer?", "query": _text(result.get("query")),
                "customers": [_customer(c) for c in matched], "ambiguous": True,
            }))
        if not out:
            # Looked for, and not found. There is nothing else to say and it still gets said
            # on the screen — see `_empty` and D-15. Found by evidence, the tool's own sentence
            # says which fact nothing had, and that is what the card says.
            said = _text(result.get("note"), MAX_TEXT_CHARS) if isinstance(result.get("asked"), dict) else ""
            out.append(_empty("order_list", "Orders", said or (f"Nothing matched {_text(result.get('query'), 40)}." if result.get("query") else "No order matched.")))
        return out
    if name == "shopify_list_orders":
        orders = [_order(o) for o in _list(result.get("orders"), MAX_ORDERS)]
        if not orders:
            window = _window_title(result)
            return [_empty("order_list", window, f"No orders {_when_words(result)}.", extra={
                "since": _text(result.get("since")), "until": _text(result.get("until")),
                "days": _int(result.get("days")), "days_ago": _int(result.get("days_ago")),
            })]
        return [_ui("order_list", {
            "title": _window_title(result),
            "since": _text(result.get("since")), "until": _text(result.get("until")),
            "days": _int(result.get("days")), "days_ago": _int(result.get("days_ago")),
            "count": _int(result.get("count")) or len(orders),
            "truncated": bool(result.get("truncated")),
            "orders": orders,
            "value": "",
        })]
    if name == "shopify_customer_history":
        card = _customer(result)
        card["history"] = _history(result)
        card["related_email"] = _related_email(result.get("email_threads"))
        timeline = _timeline(result.get("timeline"))
        if timeline is not None:
            card["timeline"] = timeline
        return [_ui("customer", card)]
    if name == "shopify_find_customer":
        customers = [_customer(c) for c in _list(result.get("customers"), MAX_CUSTOMERS)]
        if not customers and result.get("suggested"):
            return [_ui("customer_list", _suggested(result))]
        if len(customers) == 1:
            return [_ui("customer", customers[0])]
        if customers:
            return [_ui("customer_list", {
                "title": "Which customer?" if result.get("ambiguous") else "Customers",
                "query": _text(result.get("query")), "customers": customers,
                "ambiguous": bool(result.get("ambiguous")),
            })]
        return [_empty("customer_list", "Customers", f"No customer matched {_text(result.get('query'), 40)}." if result.get("query") else "No customer matched.")]
    if name == "shopify_inventory":
        products = [_inventory_product(p) for p in _list(result.get("products"), MAX_PRODUCTS)]
        if not products:
            return [_empty("inventory", _text(result.get("product")) or "Stock", f"Nothing in the catalogue matched {_text(result.get('product'), 40)}." if result.get("product") else "No product matched.", extra={"products": [], "exceptions": [], "low_stock_at": LOW_STOCK_AT})]
        exceptions = [e for p in products for e in p.pop("_exceptions")]
        return [_ui("inventory", {
            "query": _text(result.get("product")), "size": _text(result.get("size")),
            "products": products,
            "exceptions": exceptions[:MAX_VARIANTS],
            "low_stock_at": LOW_STOCK_AT,
        })]
    if name == "shopify_sales_summary":
        orders = _int(result.get("orders"))
        revenue = _float(result.get("revenue"))
        currency = _text(result.get("currency")) or "GBP"
        return [_ui("sales_summary", {
            "title": _window_title(result),
            "since": _text(result.get("since")), "until": _text(result.get("until")),
            "days": _int(result.get("days")), "days_ago": _int(result.get("days_ago")),
            "orders": orders,
            "revenue": _money_display(revenue, currency),
            "aov": _money_display(revenue / orders, currency) if orders and revenue is not None else None,
            "currency": currency,
            "complete": bool(result.get("complete", True)),
            "by_day": [_sales_day(d, currency) for d in _list(result.get("by_day"), MAX_BREAKDOWN_DAYS)],
            "basis": _text(result.get("basis"), MAX_NOTE_CHARS),
            "caveat": _text(result.get("caveat"), MAX_NOTE_CHARS),
        })]
    if name == "shopify_product_info":
        products = [_product(p) for p in _list(result.get("products"), MAX_PRODUCTS)]
        if not products:
            return [_empty("product", _text(result.get("product")) or "Product", f"Nothing in the catalogue matched {_text(result.get('product'), 40)}." if result.get("product") else "No product matched.", extra={"products": []})]
        return [_ui("product", {
            "query": _text(result.get("product")), "size": _text(result.get("size")),
            "products": products,
        })]
    if name == "gmail_search":
        threads = [_thread_summary(t) for t in _list(result.get("threads"), MAX_THREADS)]
        if not threads:
            return [_empty("email_list", "Email", "Nothing in the inbox matched.", extra={"query": _text(result.get("query"), MAX_NOTE_CHARS), "threads": []})]
        return [_ui("email_list", {
            "title": "Email", "query": _text(result.get("query"), MAX_NOTE_CHARS),
            "count": _int(result.get("count")) or len(threads), "threads": threads,
        })]
    if name == "gmail_read_thread":
        messages = [_message(m) for m in _list(result.get("messages"), MAX_MESSAGES)]
        if not messages:
            return [_empty("email_thread", "Email thread", "That thread has no readable messages.", extra={"thread_id": _text(result.get("thread_id")), "messages": []})]
        return [_ui("email_thread", {
            "thread_id": _text(result.get("thread_id")),
            "subject": next((m["subject"] for m in messages if m["subject"]), ""),
            "message_count": _int(result.get("message_count")) or len(messages),
            "truncated": bool(result.get("truncated")) or len(messages) < (_int(result.get("messages_shown")) or 0),
            "messages": messages,
            # Who spoke last, and whether anybody is waiting on us. From Gmail's own SENT
            # label (app/tools/gmail_tools.py), never from reading the words: §8 asks the
            # email surface to answer "what matters" in its first viewport, and on a
            # customer's thread what matters is whether we owe them a reply.
            "awaiting_reply": bool(result.get("awaiting_reply")),
            "latest_direction": _text(result.get("latest_direction"), 12) or "none",
            # The order this thread is about, from the rows the Mac already holds — the
            # reverse of the order card's email region, and the strip the thread card draws
            # (Phase 2 P0 #10: a thread showed its words and hid its order). Bounded here;
            # the confidence and the reasons ride beside the link so a wrong one is visible.
            **_thread_links(result),
        })]
    return []


# --------------------------------------------------------------------------- shapes


def _order(o: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    out = {
        "order_id": _text(o.get("order_id")),
        "order_number": _order_number(o.get("order_number")),
        "placed_at": _text(o.get("placed_at")),
        "fulfillment": _status(o.get("fulfillment")),
        "payment": _status(o.get("payment")),
        "total": _money_text(o.get("total")),
        "customer_name": _text(o.get("customer_name")),
        "customer_id": _text(o.get("customer_id")),
        "customer_email": _text(o.get("customer_email")),
        "detail": detail,
    }
    if detail:
        money = o.get("money") if isinstance(o.get("money"), dict) else {}
        out.update({
            "items": [_item(i) for i in _list(o.get("items"), MAX_ITEMS)],
            "items_truncated": bool(o.get("items_truncated")),
            "fulfillments": [
                {
                    "status": _status(f.get("status")),
                    "shipped_at": _text(f.get("shipped_at")),
                    "carrier": _text(f.get("carrier")),
                    "number": _text(f.get("number")),
                    "url": _tracking_url(f.get("url")),
                }
                for f in _list(o.get("fulfillments"), 6)
            ],
            "cancelled_at": _text(o.get("cancelled_at")),
            "cancel_reason": _status(o.get("cancel_reason")),
            "note": _text(o.get("note"), MAX_NOTE_CHARS),
            "tags": [_text(t, 40) for t in (o.get("tags") or [])[:10] if isinstance(t, str)],
            "ships_to": _text(o.get("ships_to")),
            "shipping_method": _text(o.get("shipping_method")),
            "shipping_address": _address(o.get("shipping_address")),
            "money": {
                "subtotal": _money_text(money.get("subtotal")),
                "shipping": _money_text(money.get("shipping")),
                "tax": _money_text(money.get("tax")),
                "discounts": _money_text(money.get("discounts")),
                "refunded": _money_text(money.get("refunded")),
                "outstanding": _money_text(money.get("outstanding")),
            } if money else None,
            "refunds": [
                {"created_at": _text(r.get("created_at")), "amount": _money_text(r.get("amount")), "note": _text(r.get("note")),
                 # Whether the money has gone back, as the payment provider answered Shopify.
                 "state": _text(r.get("state"), 12), "landed": _text(r.get("landed"), 200)}
                for r in _list(o.get("refunds"), 6)
            ],
            "history": _history(o.get("history")),
            "email": _related_email(o.get("email")),
            "pending": [_text(p, 20) for p in (o.get("pending") or [])[:4] if isinstance(p, str)],
        })
    return out


def _row_actions(writes: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """The buttons each kind of row carries on this build, by kind. Read once per turn."""
    from app.actions.rows import BY_KIND, actions_for

    enabled = bool(isinstance(writes, dict) and writes.get("allowed"))
    if not enabled:
        return {}
    return {kind: actions_for(kind, writes_enabled=True) for kind in BY_KIND}


def _actions(order: dict[str, Any], capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    from app.actions.available import available_actions

    return [
        {
            "id": _text(a.get("id"), 20), "label": _text(a.get("label"), 20), "operation": _text(a.get("operation"), 40),
            "risk": "red" if a.get("risk") == "red" else "amber", "enabled": bool(a.get("enabled")),
            "reason": _text(a.get("reason"), 60), "instruction": _text(a.get("instruction"), 120), "mode": _text(a.get("mode"), 12) or "ask",
            "family": _text(a.get("family"), 40),
            # Where a tap on an "open" chip goes, and how loud the chip is. Both the Mac's.
            "command": _text(a.get("command"), 40), "args": _text(a.get("args"), 200),
            "priority": "secondary" if a.get("priority") == "secondary" else "primary",
        }
        for a in available_actions(order, capabilities)[:6]
    ]


def _email_actions(thread: dict[str, Any], capabilities: dict[str, Any],
                   row_actions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from app.actions.available import available_email_actions

    return [
        {
            "id": _text(a.get("id"), 20), "label": _text(a.get("label"), 20), "operation": _text(a.get("operation"), 40),
            "risk": "red" if a.get("risk") == "red" else "amber", "enabled": bool(a.get("enabled")),
            "reason": _text(a.get("reason"), 60), "instruction": _text(a.get("instruction"), 120), "mode": _text(a.get("mode"), 12) or "ask",
            "family": _text(a.get("family"), 40), "detail": _text(a.get("detail"), 160),
            "command": _text(a.get("command"), 40), "args": _text(a.get("args"), 200),
            "priority": "secondary" if a.get("priority") == "secondary" else "primary",
        }
        for a in available_email_actions(thread, capabilities, row_actions=row_actions)
    ]


def _item(i: dict[str, Any]) -> dict[str, Any]:
    stock = i.get("stock") if isinstance(i.get("stock"), dict) else None
    return {
        "title": _text(i.get("title")),
        "variant": _text(i.get("variant")),
        "sku": _text(i.get("sku")),
        "quantity": _int(i.get("quantity")),
        "total": _money_text(i.get("total")),
        "image": _media_path(i.get("image_url")),
        "variant_id": _text(i.get("variant_id")),
        "product_id": _text(i.get("product_id")),
        "stock": {
            "tracked": bool(stock.get("tracked", True)),
            "available": _int(stock.get("available")),
        } if stock else None,
    }


def _address(a: Any) -> dict[str, Any] | None:
    """The address as the card prints it: a name and a few lines. The postcode and country
    are what a change-of-address diff turns on, so they are kept as fields of their own."""
    if not isinstance(a, dict):
        return None
    lines = [_text(line, 120) for line in (a.get("lines") or [])[:3] if isinstance(line, str) and line.strip()]
    return {
        "name": _text(a.get("name")),
        "company": _text(a.get("company")),
        "lines": lines,
        "city": _text(a.get("city")),
        "province": _text(a.get("province")),
        "zip": _text(a.get("zip"), 20),
        "country": _text(a.get("country")),
        "country_code": _text(a.get("country_code"), 4),
    }


def _history(h: Any) -> dict[str, Any] | None:
    """The customer's history beside their order: the five questions the owner asks.

    None means the order has no customer. A dict with `available: False` means the customer
    exists and the read FAILED — kept distinct all the way to the glass, because "no customer
    on this order" and "I couldn't load the customer" are different facts about the world."""
    if not isinstance(h, dict):
        return None
    if h.get("available") is False:
        return {"available": False, "reason": _text(h.get("reason"), 30) or "read_failed", "customer_id": _text(h.get("customer_id"))}
    last = h.get("last_order") if isinstance(h.get("last_order"), dict) else None
    return {
        "customer_id": _text(h.get("customer_id")),
        "name": _text(h.get("name")),
        "orders": _int(h.get("orders")),
        "spent": _money_text(h.get("spent")),
        "since": _text(h.get("since")),
        "standing": _text(h.get("standing"), 20),
        "first_order_at": _text(h.get("first_order_at")),
        "last_order": {"order_id": _text(last.get("order_id")), "order_number": _order_number(last.get("order_number"))} if last else None,
        "recent": [
            {
                "order_id": _text(r.get("order_id")),
                "order_number": _order_number(r.get("order_number")),
                "placed_at": _text(r.get("placed_at")),
                "fulfillment": _status(r.get("fulfillment")),
                "payment": _status(r.get("payment")),
                "cancelled": bool(r.get("cancelled_at")),
                "total": _money_text(r.get("total")),
                "items_brief": _text(r.get("items_brief")),
                "current": bool(r.get("current")),
            }
            for r in _list(h.get("recent"), 5)
        ],
        "recent_truncated": bool(h.get("recent_truncated")),
        "other_unfulfilled": [_order_number(n) for n in (h.get("other_unfulfilled") or [])[:5] if isinstance(n, str)],
        "tags": [_text(t, 40) for t in (h.get("tags") or [])[:6] if isinstance(t, str)],
        "provenance": _text(h.get("provenance"), 20) or "SHOPIFY",
    }


def _related_email(e: Any) -> dict[str, Any] | None:
    """Email that is about this order, and how sure that is. Every thread carries its
    provenance: a verified sender is the customer; anything else is a mention."""
    if not isinstance(e, dict):
        return None
    return {
        "available": bool(e.get("available")),
        "reason": _text(e.get("reason")),
        "threads": [
            {
                **_thread_summary(t),
                "sender_match": bool(t.get("sender_match")),
                "verified_sender": bool(t.get("verified_sender")),
                "match": _text(t.get("match"), 20),
                "provenance": _text(t.get("provenance"), 20) or "UNKNOWN",
            }
            for t in _list(e.get("threads"), 3)
        ],
    }


def _tracking_url(value: Any) -> str:
    """A carrier's tracking link, shown only when it is an https link. Never opened by the
    tablet on its own; the owner taps it."""
    text = _text(value, 400)
    return text if text.lower().startswith("https://") else ""


def _media_path(value: Any) -> str:
    """An image reaches the tablet only as a same-origin path the Mac signed. A Shopify CDN
    URL the Mac does not recognise becomes no image at all."""
    from app.media import signed_path

    return signed_path(value) or ""


def present_extension(ext: dict[str, Any]) -> dict[str, Any]:
    """What GET /context/order returns: the parts of the order card that arrived after the
    turn, bounded the same way as the card itself."""
    history, email = _history(ext.get("history")), _related_email(ext.get("email"))
    # Which regions the Mac tried and could not read — as distinct from still reading (pending)
    # and from read-and-empty. The tablet settles a region on its own clock when the asking
    # ends; this lets it settle the moment the Mac knows.
    failed = [name for name, part in (("history", history), ("email", email))
              if isinstance(part, dict) and part.get("available") is False and str(part.get("reason") or "") in ("read_failed", "unavailable")]
    return {
        "order_id": _text(ext.get("order_id")),
        "pending": [_text(p, 20) for p in (ext.get("pending") or [])[:4] if isinstance(p, str)],
        "failed": failed,
        "history": history,
        "email": email,
        **({"attention": _attention_items(ext)} if isinstance(ext.get("attention"), list) else {}),
    }


def _attention_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    """The attention lines the Mac read from the order, bounded for the card. A "say" is
    printed as words the owner could use — the card never offers to do it."""
    out = []
    for a in _list(order.get("attention"), MAX_ATTENTION):
        if not isinstance(a, dict) or not a.get("title"):
            continue
        detail = _text(a.get("detail"), MAX_TEXT_CHARS)
        say = _text(a.get("say"), 80)
        if say:
            detail = f"{detail} — say “{say}”" if detail else f"Say “{say}”"
        out.append({
            "kind": _text(a.get("kind"), 20), "title": _text(a.get("title"), 80), "detail": _text(detail, 200),
            "level": a.get("level") if a.get("level") in ("red", "amber", "green") else "amber",
        })
    return out


# The customers' cards (app/customers): bounded and copied key by key, like every card here.
MAX_TIMELINE = 24
MAX_MATCHES = 3
_TIMELINE_KINDS = frozenset({"ordered", "cancelled", "shipped", "refund", "note", "email_in", "email_out", "email_about",
                             "work_packed", "work_claimed", "work_done", "work_flagged", "work_released",
                             "work_cancelled", "packed_screen", "clive", "objective"})
_REF_KINDS = frozenset({"order", "email_thread", "objective"})


def _order_match(result: dict[str, Any]) -> dict[str, Any]:
    """The orders that nearly fit, each with the line that says why and what did and did not fit."""
    verdict = _text(result.get("verdict"), 12)
    rows = []
    for row in _list(result.get("likely"), MAX_MATCHES):
        rows.append({
            "order_id": _text(row.get("order_id")), "order_number": _order_number(row.get("order_number")),
            "customer_name": _text(row.get("customer_name")), "customer_id": _text(row.get("customer_id")),
            "placed_at": _text(row.get("placed_at")), "total": _money_text(row.get("total")),
            "fulfillment": _status(row.get("fulfillment")), "payment": _status(row.get("payment")),
            "why": _text(row.get("why"), MAX_TEXT_CHARS),
            "fits": [_text(f, 80) for f in (row.get("fits") or [])[:5] if isinstance(f, str)],
            "misses": [_text(f, 80) for f in (row.get("misses") or [])[:4] if isinstance(f, str)],
            "items": [{"title": _text(i.get("title")), "variant": _text(i.get("variant"))}
                      for i in _list(row.get("matched_items"), 3)],
        })
    return {
        "title": {"one": "Best match", "several": "Which one?", "check": "Is it this one?"}.get(verdict, "Closest orders"),
        "verdict": verdict, "question": _text(result.get("question"), MAX_TEXT_CHARS),
        "note": _text(result.get("note"), MAX_TEXT_CHARS) if verdict != "one" else "",
        "asked": {k: _text(v, 80) for k, v in (result.get("asked") or {}).items() if isinstance(v, str)} if isinstance(result.get("asked"), dict) else {},
        "rows": rows,
    }


def _suggested(result: dict[str, Any]) -> dict[str, Any]:
    """Customers whose names sound like the one heard: a question, never an answer."""
    return {
        "title": "Did you mean?", "query": _text(result.get("query") or (result.get("asked") or {}).get("name")),
        "customers": [{**_customer(c), "why": _text(c.get("why"), 80)} for c in _list(result.get("suggested"), MAX_CUSTOMERS)],
        "ambiguous": True, "note": _text(result.get("question"), MAX_TEXT_CHARS),
    }


def _timeline(t: Any) -> dict[str, Any] | None:
    """The customer's story, newest first (app/customers/history.py), bounded for the card."""
    if not isinstance(t, dict):
        return None
    rows = []
    for row in _list(t.get("rows"), MAX_TIMELINE):
        kind = _text(row.get("kind"), 20)
        ref_kind = _text(row.get("ref_kind"), 20)
        rows.append({
            "at": _text(row.get("at"), 40), "when": _text(row.get("when"), 30),
            "kind": kind if kind in _TIMELINE_KINDS else "other",
            "what": _text(row.get("what"), 120), "detail": _text(row.get("detail"), MAX_TEXT_CHARS),
            "ref": _text(row.get("ref")) if ref_kind in _REF_KINDS else "", "ref_kind": ref_kind if ref_kind in _REF_KINDS else "",
            "source": _text(row.get("source"), 20),
        })
    sources = t.get("sources") if isinstance(t.get("sources"), dict) else {}
    return {"rows": rows, "count": _int(t.get("count")), "truncated": bool(t.get("truncated")),
            "sources": [{"name": _text(k, 30), "said": _text(v, 60)} for k, v in list(sources.items())[:8]]}


def _customer(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "customer_id": _text(c.get("customer_id") or c.get("id")),
        "name": _text(c.get("name")),
        "email": _text(c.get("email")),
        "orders": _int(c.get("orders")),
        "spent": _money_text(c.get("spent")),
    }


def _inventory_product(p: dict[str, Any]) -> dict[str, Any]:
    variants = []
    exceptions = []
    title = _text(p.get("title"))
    for v in _list(p.get("variants"), MAX_VARIANTS):
        available = _int(v.get("available"))
        oversold = _int(v.get("oversold_by")) or 0
        tracked = bool(v.get("tracked", True))
        level = _stock_level(available, oversold, tracked)
        row = {
            "variant_id": _text(v.get("variant_id")),
            "variant": _text(v.get("variant")),
            "sku": _text(v.get("sku")),
            "available": available,
            "oversold_by": oversold,
            "tracked": tracked,
            "level": level,
        }
        variants.append(row)
        if level in {"out", "low", "oversold"}:
            exceptions.append({"product": title, **row})
    return {
        "product_id": _text(p.get("product_id")),
        "title": title,
        "status": _status(p.get("status")),
        "total_inventory": _int(p.get("total_inventory")),
        "variants": variants,
        "_exceptions": exceptions,
    }


def _stock_level(available: int | None, oversold: int, tracked: bool) -> str:
    if not tracked:
        return "untracked"
    if oversold > 0:
        return "oversold"
    if available is None:
        return "unknown"
    if available == 0:
        return "out"
    if available <= LOW_STOCK_AT:
        return "low"
    return "ok"


def _product(p: dict[str, Any]) -> dict[str, Any]:
    measurements = []
    for m in _list(p.get("measurements"), MAX_MEASUREMENTS):
        if isinstance(m, dict):
            measurements.append({str(k)[:24]: _text(v, 40) for k, v in list(m.items())[:8]})
    return {
        "product_id": _text(p.get("product_id")),
        "title": _text(p.get("title")),
        "status": _status(p.get("status")),
        "description": _text(p.get("description"), 600),
        "subtitle": _text(p.get("subtitle")),
        "fabric": _text(p.get("fabric"), MAX_NOTE_CHARS),
        "cut": _text(p.get("cut"), MAX_NOTE_CHARS),
        "origin": _text(p.get("origin"), MAX_NOTE_CHARS),
        "care": _text(p.get("care"), MAX_NOTE_CHARS),
        "measurements": measurements,
        "measurements_note": _text(p.get("measurements_note")),
    }


def _thread_summary(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": _text(t.get("thread_id")),
        "from": _text(t.get("from")),
        "from_email": _text(t.get("from_email")),
        "subject": _text(t.get("subject")),
        "date": _text(t.get("date")),
        "snippet": _text(t.get("snippet"), MAX_SNIPPET_CHARS),
        "likely_bulk": bool(t.get("likely_bulk")),
        "known_customer": t.get("known_customer") if isinstance(t.get("known_customer"), bool) else None,
    }


def _message(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": _text(m.get("from")),
        "from_email": _text(m.get("from_email")),
        "date": _text(m.get("date")),
        "subject": _text(m.get("subject")),
        "body": _text(m.get("body"), MAX_BODY_CHARS),
        # Ours or theirs, from Gmail's SENT label. The thread card draws the latest message
        # open and the earlier ones behind a fold, and which side each one is on is the
        # difference between a conversation and a wall of text.
        "outbound": bool(m.get("outbound")),
    }


MAX_LINK_PROVENANCE = 4


def _linked_order(row: dict[str, Any]) -> dict[str, Any]:
    total = row.get("total")
    shown = _money_display(float(total), str(row.get("currency") or "GBP")) if isinstance(total, (int, float)) else _money_text(total)
    return {
        "order_id": _text(row.get("order_id")),
        "order_number": _order_number(row.get("order_number")),
        "total": shown,
        "fulfillment": _status(row.get("fulfillment")),
        "customer_name": _text(row.get("customer_name")),
        "customer_id": _text(row.get("customer_id")),
    }


def _thread_links(result: dict[str, Any]) -> dict[str, Any]:
    """The thread → order link, from `app/context/graph.py` over the order cache's rows.

    The presenter must not invent a read, so the only source is what the cache holds now. A
    cold cache — the first minute after a restart — is said plainly ("order cache not warm")
    rather than reported as "no order", which is the difference between "not yet" and "no".
    """
    from app.context import graph

    rows: list[dict[str, Any]] = []
    warm = False
    try:
        from app.tools.analytics_tools import cache

        held = cache()
        rows = held.rows()
        warm = bool(rows) and held.status().get("synced_at") is not None
    except Exception:  # noqa: BLE001 — no cache bound (tests, a Mac without Shopify) is a cold cache
        warm = False
    if warm:
        # The cache's clock, not the wall clock: the rows are stamped by it, and a test that
        # sets it sets what "recent" means.
        found = graph.linked_orders_for_thread(result, rows=rows, clock=getattr(held, "clock", None) or time.time)
    else:
        found = {"linked": [], "confidence": "none", "provenance": ["order cache not warm"], "customer": None}
    confidence = str(found.get("confidence") or "none")
    if confidence not in ("confident", "possible", "none"):
        confidence = "none"
    linked = [_linked_order(r) for r in _list(found.get("linked"), graph.MAX_POSSIBLE)]
    customer = found.get("customer") if isinstance(found.get("customer"), dict) else None
    return {
        "linked_order": linked[0] if confidence == "confident" and linked else None,
        "possible_orders": linked if confidence == "possible" else [],
        "linked_customer": {"customer_id": _text(customer.get("customer_id")), "name": _text(customer.get("name"))} if customer and customer.get("customer_id") else None,
        "link_confidence": confidence,
        "link_provenance": [_text(p, 120) for p in (found.get("provenance") or [])[:MAX_LINK_PROVENANCE] if isinstance(p, str)],
    }


# --------------------------------------------------------------------------- errors


def _recovered(call: ToolCall, later: list[ToolCall]) -> bool:
    """The gate refused this call and the model then did the same thing properly. The same
    thing: the same tool on the same entity — a note refused for one order is not made good
    by a note prepared for another, and the owner must see the refusal."""
    entity = _entity_of(call)
    return any(c.ok and c.name == call.name and (entity is None or _entity_of(c) == entity) for c in later)


def _entity_of(call: ToolCall) -> str | None:
    """The entity a call was about, as the store numbers it: "1938" whether the model wrote
    the bare number or the full gid. The refused call and the one that put it right are the
    same thing only when this matches."""
    for key, value in (call.args or {}).items():
        if key.endswith("_id") and isinstance(value, str) and value.strip():
            return value.rstrip("/").rsplit("/", 1)[-1].lower()
    return None


def _tool_error(call: ToolCall, session: Session | None) -> dict[str, Any]:
    name = call.name or ""
    issued = session.issued_ids if session is not None else ()
    blocked = classify(name, call.args or {}, issued).disposition is Disposition.DENY
    if name.startswith("shopify_"):
        service, title = "shopify", "Shopify unavailable"
    elif name.startswith("gmail_"):
        service, title = "gmail", "Email unavailable"
    else:
        service, title = "assistant", "Lookup failed"
    if blocked:
        # The assistant's own rules stopped it, not the owner's permissions: it asked for
        # something it may not do, or in a way it may not. Nothing left the Mac.
        return _error(service, "blocked", "Refused by the assistant's rules", "The assistant tried something outside what it may do. Nothing was changed.")
    return _error(service, "tool_failed", title, "Ask again in a moment; the answer says what happened.")


def _error(service: str, kind: str, title: str, recovery: str) -> dict[str, Any]:
    return _ui("error", {"service": service, "kind": kind, "title": title, "recovery": recovery})


# --------------------------------------------------------------------------- actions


def _confirmation(proposal, *, writes: dict[str, Any] | None = None) -> dict[str, Any]:
    """The action card, from the staged proposal and nothing else: the model chose no
    component and supplied no label. The tool's own `present` names the change; this bounds
    it and adds what the tablet needs to run the interaction and nothing it does not. When
    the Mac already knows a tap from this tablet would be refused, the card says so instead
    of arming a surface that would fail."""
    words = _present_words(proposal)
    interaction = proposal.interaction if proposal.interaction in INTERACTIONS else "unsupported"
    gesture = grammar.words_for(interaction)
    commit = _commit_words(proposal, writes)
    return _ui("confirmation", {
        "proposal_id": _text(proposal.proposal_id, 40),
        "status": _text(proposal.status.value.lower(), 20),
        "risk": "red" if proposal.risk == "RED" else "amber",
        "operation": _text(proposal.operation, 60),
        "title": _text(words.get("title")),
        "entity": _entity_line(proposal),
        "entity_kind": _text(proposal.entity_kind, 20),
        "entity_ref": _text(proposal.entity_ref, 200),
        "summary": _text(words.get("summary"), MAX_NOTE_CHARS),
        # An email's whole text, when the change is an email: the card is the draft.
        "body": _text(words.get("body"), MAX_EMAIL_BODY_CHARS),
        "detail": _text(words.get("detail")),
        # The facts the gesture authorises, printed above it: what the change will do and to
        # whom, built by the tool from what it read. Never a place for the model's words.
        "facts": [
            {"label": _text(f.get("label"), 40), "value": _text(f.get("value"), 120), "tone": _text(f.get("tone"), 10)}
            for f in _list(words.get("facts"), 8)
        ],
        "interaction": {
            "kind": interaction,
            "label": _text(words.get("confirm_label") or gesture["label"], 60),
            "footer": _text(gesture["footer"], 120),
            # The words on the target or the handle — the consequence, from the tool.
            "target": _text(words.get("target"), 60),
            "armed_after_ms": ARMED_AFTER_MS,
            "hold_ms": grammar.HOLD_MS,
            "armed_for_s": grammar.ARMED_FOR_S,
            "swipe_fraction": grammar.SWIPE_FRACTION,
        },
        "expires_at": proposal.public()["expires_at"],
        "ttl_s": proposal.ttl_s(),
        "reversible": bool(proposal.reversible),
        # Which change this card would put back, when it is an offer rather than a change
        # waiting. Everything that counts work outstanding reads this and passes over it: an
        # undo belongs to a change that is finished, and is not waiting on anybody.
        "undo_of": _text(proposal.undo_of or "", 40),
        "commit": commit if commit else {"allowed": True},
    })


# Why a tap would be refused from here, in the words the card shows under the change.
_COMMIT_BLOCKED_WORDS = {
    "writes_disabled": "Changes are switched off on the server (CROOKS_WRITES_ENABLED).",
    "allow_list_missing": "No allowed logins are set on the server (CROOKS_ALLOWED_LOGINS).",
    "not_authorised": "This device's login is not on the allowed list. Open /whoami to see it.",
    "not_authorised_local": "Asked on the server itself, which may not apply changes (CROOKS_WRITES_LOCAL_OWNER).",
    "scope_missing": "The store has not granted the permission this change needs.",
    "gmail_scope_missing": "The Gmail credential cannot make this change yet.",
    "identity_unverified": "The server could not confirm this device's identity with Tailscale.",
    "read_only": "This backend is in read-only test mode and cannot apply changes.",
}


def _present_words(proposal) -> dict[str, Any]:
    from app.tools import registry

    try:
        spec = registry.get(proposal.tool_name)
    except KeyError:
        return {}
    if spec.write is None:
        return {}
    try:
        words = spec.write.present(proposal)
    except Exception:  # noqa: BLE001 — a card with no words is still a card
        return {}
    return words if isinstance(words, dict) else {}


def _entity_line(proposal) -> str:
    kind = (proposal.entity_kind or "").capitalize()
    return _text(f"{kind} {proposal.entity_label}".strip())


# Which verified operations change where a thread LIVES, and therefore change a card the
# tablet already has on screen. A closed table: the only thing that may claim a thread left
# the inbox is the one operation that takes it out of the inbox.
_INBOX_OUT = frozenset({"gmail_thread_archive"})


def _thread_of(proposal) -> str:
    """The email thread this change was about, when it was about one. Read from what the MAC
    stored as the change's own identity — `entity_ref` for a reply and for an archive — never
    from what a model or a tablet said."""
    if not str(proposal.operation or "").startswith("gmail_"):
        return ""
    ref = _text(proposal.entity_ref, 120)
    execution = dict(getattr(proposal, "execution", None) or {})
    thread = _text(execution.get("thread_id"), 120) or ref
    return thread if thread and thread == ref else ""


def _thread_card(proposal) -> dict[str, Any] | None:
    """The thread as the Mac last read it, for the card that follows a proven email change."""
    if not _thread_of(proposal):
        return None
    from app.memory import ENTITY
    from app.memory import current as memory

    held = memory().get(ENTITY, f"email_thread:{_thread_of(proposal)}", allow_stale=True)
    value = getattr(held, "value", None) if held is not None else None
    if not isinstance(value, dict) or not value.get("messages"):
        return None
    drawn = _from_result("gmail_read_thread", value)
    return drawn[0] if drawn else None


def _inbox_change(proposal) -> dict[str, Any]:
    """`archived` or `restored`, when this proven change moved a thread out of the inbox or
    put it back. Empty for everything else — including for an archive whose own undo is what
    was proven, which is the `restored` case and not the `archived` one."""
    if str(proposal.operation or "").removesuffix("_undo") not in _INBOX_OUT:
        return {}
    ref = _text(proposal.entity_ref, 120)
    if not ref:
        return {}
    where = {"kind": "email_thread", "ref": ref}
    return {"restored": where} if proposal.undo_of else {"archived": where}


def present_action(result, *, session: Session | None = None, writes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What the tablet shows once a tap has been answered: a success card and the entity as
    it now is (from the verifying re-read), or a calm failure. Built from the engine's result,
    never from the tablet's expectation."""
    proposal = result.proposal
    if proposal is None:
        return []
    from app.families import _workspace as workspaces

    if workspaces.sent_not_confirmed(proposal):
        # It left for Shopify and nothing proved it made: not "Nothing was changed", whatever the
        # engine's one re-read said — the card it came from says sent, not confirmed, and so does this.
        return present_proposal_state(proposal, session=session, code="unverified", writes=writes, recovery=workspaces.SENT_NOT_CONFIRMED)
    recovery = result.spoken if result.code in ("stale", "unverified", "failed", "service_unavailable") else ""
    return present_proposal_state(proposal, session=session, code=result.code, writes=writes, recovery=recovery)


def _service_of(proposal) -> str:
    return "gmail" if str(proposal.tool_name or "").startswith("gmail_") else "shopify"


def _service_name(proposal) -> str:
    return "Gmail" if _service_of(proposal) == "gmail" else "Shopify"


# --------------------------------------------------------------------------- batches


def _batch_words(batch) -> dict[str, Any]:
    from app.tools import registry

    try:
        spec = registry.get(batch.tool_name)
    except KeyError:
        return {}
    if spec.batch is None:
        return {}
    try:
        words = spec.batch.present(batch)
    except Exception:  # noqa: BLE001 — a card with no words is still a card
        return {}
    return words if isinstance(words, dict) else {}


def _batch_scope(batch) -> dict[str, Any]:
    return {"set_id": _text(batch.set_id, 40), "label": _text(batch.set_label, 80), "kind": _text(batch.set_kind, 20), "count": int(batch.requested)}


def _batch_card(batch, *, writes: dict[str, Any] | None = None) -> dict[str, Any]:
    """The bulk-change card: how many, of what, with what consequence, who is excluded and
    why, every member by name to inspect, and the one gesture. Built from the batch the Mac
    staged and the tool's own words; the model chose none of it."""
    words = _batch_words(batch)
    interaction = batch.interaction if batch.interaction in INTERACTIONS else "unsupported"
    gesture = grammar.words_for(interaction)
    commit = _commit_words(batch, writes)
    preview = batch.summary.get("preview") if isinstance(batch.summary.get("preview"), dict) else {}
    return _ui("batch_action", {
        "batch_id": _text(batch.batch_id, 40),
        "status": _text(batch.status.value.lower(), 20),
        "risk": "red" if batch.risk == "RED" else "amber",
        "operation": _text(batch.operation, 60),
        "title": _text(words.get("title")),
        "summary": _text(words.get("summary"), MAX_NOTE_CHARS),
        "body": _text(words.get("body"), MAX_EMAIL_BODY_CHARS),
        "detail": _text(words.get("detail"), MAX_NOTE_CHARS),
        "set": _batch_scope(batch),
        "requested": int(batch.requested),
        "eligible": len(batch.eligible),
        "excluded_count": len(batch.excluded),
        "excluded": [{"label": _text(c.label, 60), "reason": _text(c.excluded, 120)} for c in batch.excluded[:MAX_BATCH_ROWS]],
        "members": [_text(c.label, 60) for c in batch.eligible[:MAX_BATCH_ROWS]],
        "facts": [
            {"label": _text(f.get("label"), 40), "value": _text(f.get("value"), 120), "tone": _text(f.get("tone"), 10)}
            for f in _list(words.get("facts"), 8)
        ],
        # One member's email as it will be saved: the campaign, previewed on the first.
        "preview": {"to": _text(preview.get("to")), "subject": _text(preview.get("subject"), 200), "body": _text(preview.get("body"), MAX_EMAIL_BODY_CHARS)} if preview else None,
        "interaction": {
            "kind": interaction,
            "label": _text(words.get("confirm_label") or gesture["label"], 60),
            "footer": _text(gesture["footer"], 120),
            "target": _text(words.get("target"), 60),
            "armed_after_ms": ARMED_AFTER_MS,
            "hold_ms": grammar.HOLD_MS,
            "armed_for_s": grammar.ARMED_FOR_S,
            "swipe_fraction": grammar.SWIPE_FRACTION,
        },
        "expires_at": batch.public()["expires_at"],
        "ttl_s": batch.ttl_s(),
        "reversible": bool(batch.reversible),
        "commit": commit if commit else {"allowed": True},
    })


_OUTCOME_LABELS = {
    "verified": "applied", "unverified": "not confirmed", "stale": "changed meanwhile, left alone", "failed": "not applied",
    "service_unavailable": "not applied", "refused": "refused", "not_attempted": "not attempted", "already_executed": "applied",
    "expired": "not attempted", "revoked": "not attempted", "in_progress": "not confirmed",
}


def present_batch(result, *, session: Session | None = None, writes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    batch = result.batch
    if batch is None:
        return []
    return present_batch_state(batch, session=session, code=result.code, writes=writes)


def present_batch_state(batch, *, session: Session | None = None, code: str | None = None, writes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What the tablet shows for a batch: the card while it waits, the count once it has run
    — every member with its outcome, and never a total the engine did not prove."""
    code = code or batch.code or batch.status.value.lower()
    status = batch.status.value.lower()
    words = _batch_words(batch)
    if status == "done":
        counts = {k: int(batch.counts.get(k) or 0) for k in ("requested", "eligible", "excluded", "verified", "unverified", "stale", "failed", "not_attempted")}
        rows = [{"label": _text(c.label, 60), "outcome": _text(_OUTCOME_LABELS.get(c.code, c.code or "not attempted"), 40), "code": _text(c.code, 30)} for c in batch.eligible[:MAX_BATCH_ROWS]]
        rows += [{"label": _text(c.label, 60), "outcome": "excluded: " + _text(c.excluded, 100), "code": "excluded"} for c in batch.excluded[: max(0, MAX_BATCH_ROWS - len(rows))]]
        title = _text(words.get("undone_title") or "Undone") if batch.undo_of else _text(words.get("done_title") or "Done")
        verified, eligible = counts["verified"], counts["eligible"]
        not_applied = eligible - verified
        # One denominator, the one the owner gestured for: the eligible members on the card.
        # The excluded were named there before the gesture and are not counted against it.
        return [_ui("batch_result", {
            "batch_id": _text(batch.batch_id, 40), "operation": _text(batch.operation, 60),
            "title": f"{title}: {verified} of {eligible}",
            "detail": f"{_text(batch.set_label, 80)} · {counts['requested']} {_text(batch.set_kind, 20)}" + (f" · {counts['excluded']} excluded before the gesture" if counts["excluded"] else ""),
            "all_verified": batch.all_verified,
            "summary": f"{verified} applied" + (f", {not_applied} not" if not_applied else ""),
            "counts": counts, "rows": rows,
            "note": "" if verified == eligible else f"The {not_applied} marked not applied were left as they were. Ask for the change again for those, or check them in Shopify.",
        })]
    if status == "pending":
        return [_batch_card(batch, writes=writes)]
    if status == "executing":
        return [_error("shopify" if not str(batch.child_tool).startswith("gmail_") else "gmail", "in_progress", *_OUTCOME_WORDS["in_progress"])]
    title, line = _OUTCOME_WORDS.get(code, _OUTCOME_WORDS["failed"])
    if code == "revoked" and batch.undo_of:
        line = "The undo was withdrawn when you moved on."
    return [_error("shopify" if not str(batch.child_tool).startswith("gmail_") else "gmail", _text(code, 40), title, _text(line, 200))]


def present_proposal_state(
    proposal, *, session: Session | None = None, code: str | None = None,
    writes: dict[str, Any] | None = None, recovery: str = "",
) -> list[dict[str, Any]]:
    code = code or proposal.code or proposal.status.value.lower()
    words = _present_words(proposal)
    entity_line = _entity_line(proposal)
    items: list[dict[str, Any]] = []
    status = proposal.status.value.lower()
    if status == "verified":
        title = _text(words.get("undone_title") or _undone_title(proposal)) if proposal.undo_of else _text(words.get("done_title") or _done_title(proposal))
        items.append(_ui("success", {
            "title": title, "detail": entity_line,
            "proposal_id": _text(proposal.proposal_id, 40), "operation": _text(proposal.operation, 60),
            # What the proof could not yet see ("the refund isn't showing yet"): on the card,
            # not only in the voice.
            "note": _text(proposal.note, 200),
            # A proven archive is the one verified change whose consequence is a card ALREADY
            # ON SCREEN: the thread the owner archived is still sitting in the queue he
            # archived it out of. The Mac says which thread left the inbox (and which came
            # back, on an undo) and the tablet settles its own deck from that
            # (web/ui.js:settleThread). Named rather than inferred, because "the operation
            # ended in _archive" is the sort of guess that eventually archives an order.
            **_inbox_change(proposal),
        }))
        if isinstance(proposal.entity, dict) and proposal.entity_kind == "order":
            items.append(_ui("order", _order(proposal.entity, detail=True)))
        elif isinstance(proposal.entity, dict) and proposal.entity.get("kind") == "email" and proposal.entity.get("body"):
            e = proposal.entity
            items.append(_ui("email_draft", {
                "to": _text(e.get("to")), "subject": _text(e.get("subject"), 200), "body": _text(e.get("body"), MAX_EMAIL_BODY_CHARS),
                "state": "sent" if e.get("state") == "sent" else "draft",
            }))
        # …and the conversation it was about, so the owner lands back on the thread rather
        # than on a receipt. §19: "see VERIFIED → return to the thread". Rebuilt from the read
        # the Mac already holds, so it costs nothing and asks Gmail nothing; absent when the
        # Mac has dropped it, which draws one card fewer and never a wrong one.
        thread = _thread_card(proposal)
        if thread is not None:
            items.append(thread)
    elif status == "pending":
        # Whether a tap from this request could work, on this card too: a card recovered
        # after a lost connection must not offer a tap the Mac would refuse.
        items.append(_confirmation(proposal, writes=writes))
    elif status in ("executing", "executed"):
        # Claimed, sent, or being proven: the outcome is not known yet, and the card must not
        # say "not applied" about a change that may be on the order this second.
        items.append(_error(_service_of(proposal), "in_progress", *_OUTCOME_WORDS["in_progress"]))
    else:
        title, words = _OUTCOME_WORDS.get(code, _OUTCOME_WORDS["failed"])
        if code == "refused":
            # The service answered and said no: its reason, bounded, is the one useful line.
            words = f"{_service_name(proposal)} refused it: {_text(proposal.reason, 140)}. Nothing was changed."
        elif code == "revoked" and proposal.undo_of:
            words = "The undo was withdrawn when you moved on."
        elif recovery:
            # The tool's own words for this outcome (the voice says the same): "a new message
            # arrived in that thread", "the stock moved" — never "the order" for an email.
            words = recovery
        items.append(_error(_service_of(proposal), _text(code, 40), title, _text(words, 200)))
    if session is not None:
        _remember(items, session)
        # §18, as a SWEEP rather than one renderer at a time. After `_remember`, which is
        # what issues the ids a card's own offers rest on, so a row this turn legitimately
        # showed keeps its ref and only a row pointing at nothing loses it.
        _withhold_dead_refs(items, session)
    return items


def _commit_words(proposal, writes: dict[str, Any] | None) -> dict[str, Any] | None:
    """Whether a gesture on THIS card could work, from this request's identity and from the
    capability of this card's own change — a fulfilment scope the store has not granted must
    not mark a note as blocked, and write_orders being granted must not mark an email as
    tappable. When it could not, the words name the permission the status carries."""
    if not isinstance(writes, dict):
        return None
    code, detail = "", ""
    if writes.get("allowed") is False:
        code, detail = str(writes.get("code") or ""), str(writes.get("detail") or "")
    else:
        capabilities = writes.get("capabilities") if isinstance(writes.get("capabilities"), dict) else {}
        operation = str(proposal.operation or "").removesuffix("_undo")
        entry = capabilities.get(operation)
        if isinstance(entry, dict) and entry.get("state") not in ("ready", "unknown"):
            from app.runtime import WriteStatus

            detail = str(entry.get("detail") or "")
            code = WriteStatus(str(entry.get("state") or "blocked"), detail).code
    if not code:
        return None
    reason = _COMMIT_BLOCKED_WORDS.get(code, "Changes cannot be applied from this device.")
    if code in ("scope_missing", "gmail_scope_missing") and detail:
        reason = f"{reason} ({_text(detail.replace('blocked — ', '', 1), 140)})"
    return {"allowed": False, "code": _text(code, 40), "reason": _text(reason, 200)}


def _done_title(proposal) -> str:
    return {
        "order_note_append": "Note added", "order_tags_add": "Tags added", "order_cancel": "Cancelled",
        "refund_create": "Refunded", "order_shipping_address_set": "Address changed", "fulfillment_create": "Shipped",
        "gmail_draft_reply": "Draft saved", "gmail_draft_new": "Draft saved", "gmail_send_reply": "Reply sent", "gmail_send_new": "Email sent",
        "gmail_thread_archive": "Archived", "inventory_set": "Stock adjusted", "order_tags_remove": "Tags removed",
        "fulfillment_tracking_set": "Tracking added", "checkout_link_send": "Checkout link sent",
    }.get(proposal.operation, "Done")


def _undone_title(proposal) -> str:
    return {
        "order_note_append_undo": "Note restored", "order_tags_add_undo": "Tags removed",
        "gmail_draft_reply_undo": "Draft deleted", "gmail_draft_new_undo": "Draft deleted", "gmail_thread_archive_undo": "Back in the inbox",
        "inventory_set_undo": "Stock put back", "order_tags_remove_undo": "Tags put back",
    }.get(proposal.operation, "Undone")


# What a settled-but-not-successful proposal says on the card. Calm, and nothing from Shopify.
# "Nothing was changed" appears only under codes the engine proves: a failure before the
# mutation left, or a re-read that still shows the order as it was. An ambiguous outcome says
# to check the order, and never guesses either way.
_OUTCOME_WORDS: dict[str, tuple[str, str]] = {
    "stale": ("Not applied", "The order changed since this was prepared. Ask again for a fresh one."),
    "expired": ("Expired", "That action waited too long. Ask again."),
    "revoked": ("Withdrawn", "You moved on to something else. Ask again if you still want it."),
    "unverified": ("Could not confirm", "The change could not be confirmed. Check the order before asking again."),
    "service_unavailable": ("Not applied", "Shopify could not be reached. Nothing was changed."),
    "already_executed": ("Already applied", "This was applied once already; it is not applied twice."),
    "in_progress": ("Applying", "Still being applied. Give it a moment."),
    "failed": ("Not applied", "That did not go through. Nothing was changed."),
    "refused": ("Refused", "The service answered and said no. Nothing was changed."),
}


# --------------------------------------------------------------------------- merging, memory


# The card kinds a turn may draw more than one of. The second and later are the answer's
# supporting evidence, not its headline, and are marked so the tablet can collapse them
# (brief section 22: reorganise, do not remove). An `order` is not here — two orders in one
# turn are two records, both wanted open; `_merge` already folds a repeat of the SAME one.
SECONDARY_KINDS = frozenset({"ranking", "order_list", "email_list", "table", "metric_group", "comparison", "trend"})


def _merge(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One card per entity. A find followed by a detail lookup of the same order in one turn
    yields the detail card only; the summary is a strict subset of it. An objective changed
    several times in one turn is one card, as the last change left it."""
    out: list[dict[str, Any]] = []
    seen_orders: dict[str, int] = {}
    seen_workspaces: dict[str, int] = {}
    seen_objectives: dict[str, int] = {}
    seen_customers: dict[str, int] = {}
    for item in items:
        if item["type"] == "workspace":
            # Opened and then changed in the same turn ("a new order for Mia, and add a
            # print"): one card, as it stands after the last change.
            ident = str((item.get("data") or {}).get("workspace_id") or "")
            if ident in seen_workspaces:
                out[seen_workspaces[ident]] = item
                continue
            seen_workspaces[ident] = len(out)
        if item["type"] == "objective":
            # Opened and then noted on in one turn is one objective: the last card is the whole
            # record as the turn left it, drawn where the first one was.
            ref = str(item["data"].get("objective_id") or "")
            if ref in seen_objectives:
                out[seen_objectives[ref]] = item
                continue
            seen_objectives[ref] = len(out)
        if item["type"] == "order":
            ref = item["data"].get("order_id") or item["data"].get("order_number")
            if ref in seen_orders:
                index = seen_orders[ref]
                if item["data"].get("detail") or not out[index]["data"].get("detail"):
                    out[index] = item
                continue
            seen_orders[ref] = len(out)
        if item["type"] == "customer":
            # The same rule for a person: found, then their history read, is one card — the one
            # with the history on it (app/customers/history.py), where the first one was drawn.
            ref = str(item["data"].get("customer_id") or "")
            if ref and ref in seen_customers:
                index = seen_customers[ref]
                if item["data"].get("history") or item["data"].get("timeline") or not out[index]["data"].get("history"):
                    out[index] = item
                continue
            if ref:
                seen_customers[ref] = len(out)
        out.append(item)
    return out


def compact(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One cursor per turn, and one headline per kind (brief section 22).

    Applied to the WHOLE screen, after a recipe's own surfaces have been put in front of the
    cards the tools produced — which is why it is not part of `_merge`. `_merge` runs inside
    `present()` and can only see the tool cards, so the Inbox landing, whose queue card is the
    recipe's and whose recent-threads card is the search read's, stacked two email lists:
    952 px on an 889 px screen, measured.

    Two rules, both measured at 601 x 889 (the tablet's own viewport):

    * One `working_set` card. Two cards each saying "these" are two claims to the same word —
      the same reason `working_set_items` refuses to draw a card per derived set — and the
      dock's Orders landing, which reads two lists, drew two of them (1,112 px → 671 px).
    * The second and later card of one analytic kind is marked `secondary`, and the tablet
      draws it folded behind its own title (web/ui.js:folded). The Products landing stacked
      two full rankings, 1,498 px; folded, the headline and the actions are on one screen and
      the second ranking is one tap away (→ 736 px). Nothing is removed: the folded card is
      the whole card.
    """
    # And the same rule once more over the WHOLE screen: a recipe's own card can be the answer
    # a tool read found none of, and "no orders yesterday" must not sit above it.
    items = _only_empty_when_nothing_else(list(items))
    out: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()
    have_set = False
    for item in items:
        kind = str(item.get("type") or "")
        data = item.get("data")
        if kind == "working_set":
            if have_set:
                continue
            have_set = True
        elif kind in SECONDARY_KINDS and isinstance(data, dict):
            if kind in seen_kinds:
                item = {**item, "data": {**data, "secondary": True}}
            seen_kinds.add(kind)
        out.append(item)
    return out


#: Where a row that OFFERS a record puts its destination, per card type. The tablet's deck
#: handler turns `ref` + `kind` into `open.entity`, so these are the lists a §18 sweep has to
#: walk. A card not named here offers nothing by row.
_ROWS_THAT_OFFER: dict[str, tuple[str, ...]] = {
    "ranking": ("rows",),
    "table": ("rows",),
    "customer_list": ("customers",),
    "inventory": ("rows", "variants"),
}


def _withhold_dead_refs(items: list[dict[str, Any]], session: Session) -> None:
    """A row whose destination the Mac could not open loses its destination (§18).

    D-6 is one row of one card: a product in the best-sellers ranking posted `open.entity`,
    was refused `not_held`, and the half drew `half_empty` with no word about why. The fix
    for the WORKSPACE rows was to decide openability before drawing them
    (`app/workspace.py:_open`). The analytic cards had no such rule, because they are built
    in `app/analytics/present.py`, which is handed a read result and no session and therefore
    cannot ask the question at all: `ranking` takes `ref`/`kind` straight off the aggregate's
    GROUP KEY, so every product the aggregate grouped by got a tappable row whether or not
    the Mac had ever read that product.

    Two things a per-renderer fix would not have given, which is why this is a sweep:

    * it closes the CLASS. §33's gate step `no_control_carries_unheld_ref` takes every
      `[data-ref]` on the glass and tries to open it, and after this there is one place that
      has to be right for all of them rather than one per card.
    * it runs where the session is, which is the only place the question can be answered.
      `may_open` is the permission half and the entity cache is the holding half, and the tap
      needs both — exactly the pair `app/families/compose.py:_held_record` and
      `app/routes/command.py` check when it actually arrives, asked here with the same keys
      before anything is drawn.

    A row that loses its ref is still DRAWN, with every figure on it: the ranking is the
    answer to "what sold best", and the only false thing about it was the promise that you
    could tap through to the product. `known: False` goes beside it so the renderer shows it
    flat rather than pretending it is pressable.
    """
    from app.commands import may_open
    from app.memory import ENTITY
    from app.memory import current as memory

    class _Ctx:                       # `may_open` wants a ctx; it reads only the session
        __slots__ = ("session",)

        def __init__(self, value: Session) -> None:
            self.session = value

    ctx = _Ctx(session)
    cache = memory()

    def openable(kind: str, ref: str) -> bool:
        if not kind or not ref:
            return False
        try:
            if not may_open(ctx, kind, ref):
                return False
            held = cache.get(ENTITY, f"{kind}:{ref}", allow_stale=True)
            return isinstance(getattr(held, "value", None), dict)
        except Exception:  # noqa: BLE001 — an unanswerable question is "not openable"
            return False

    for item in items:
        keys = _ROWS_THAT_OFFER.get(str(item.get("type") or ""))
        if not keys or not isinstance(item.get("data"), dict):
            continue
        for key in keys:
            rows = item["data"].get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or not row.get("ref"):
                    continue
                if openable(str(row.get("kind") or ""), str(row["ref"])):
                    continue
                row["ref"], row["kind"] = "", ""
                row["known"] = False


def _remember(items: list[dict[str, Any]], session: Session) -> None:
    """Push this turn's entities onto the session's context stack, oldest first so the most
    specific thing (a detail card) ends up at the front."""
    for item in items:
        kind, data = item["type"], item["data"]
        if kind == "order":
            session.remember_context("order", data.get("order_number") or "", data.get("order_id") or "", limit=MAX_CONTEXT)
            if data.get("customer_id"):
                # ISSUED, because the card offers a way to the customer and `open.entity`
                # refuses a ref this conversation was never shown. The same two lines, for the
                # same reason, as the email thread's order strip below: a REPLAYED order card
                # — Back, Next, a tap on a list row — is rebuilt from the entity cache rather
                # than from a tool result, so `_harvest_ids` never saw it and nothing else
                # issued it. The click-path audit found that as path 1 dead at step 4 of 8:
                # an order card with its Customer tab open and no way to the customer. The
                # card shows them; that is the showing (§18).
                session.issue(str(data["customer_id"]))
            if data.get("customer_name") and data.get("customer_id"):
                session.remember_context("customer", data["customer_name"], data["customer_id"], limit=MAX_CONTEXT)
        elif kind == "customer":
            session.remember_context("customer", data.get("name") or "", data.get("customer_id") or "", limit=MAX_CONTEXT)
        elif kind in ("customer_workspace", "order_workspace"):
            # The composed surface establishes its entity exactly as the single card did, and
            # with a HUMAN label (§26): "#1962", never the gid the tap posts.
            session.remember_context(str(data.get("kind") or ""), data.get("label") or "",
                                     data.get("ref") or "", limit=MAX_CONTEXT)
            # Every record the workspace shows is a record this conversation has been shown,
            # so `open.entity` on any of its rows cannot be refused `not_held` (§18). The
            # rows themselves were only marked openable once the ref passed the gate's shape
            # check (app/workspace.py:_open), which is where the issuing happens.
            for section in (data.get("sections") or {}).values():
                for row in section.get("rows") or []:
                    if row.get("open"):
                        session.issue(str(row.get("order_id") or row.get("thread_id") or row.get("customer_id") or ""))
        elif kind == "email_thread":
            session.remember_context("email", data.get("subject") or "(no subject)", data.get("thread_id") or "", limit=MAX_CONTEXT)
            # The strip's orders and customer came from the cache, not from a tool result, so
            # nothing else issued them — and `open.entity` refuses a ref the conversation was
            # never shown. The card shows them; that is the showing.
            for order in [data.get("linked_order"), *(data.get("possible_orders") or [])]:
                if isinstance(order, dict) and order.get("order_id"):
                    session.issue(str(order["order_id"]))
            bridged = data.get("linked_customer")
            if isinstance(bridged, dict) and bridged.get("customer_id"):
                session.issue(str(bridged["customer_id"]))
        elif kind in {"inventory", "product"}:
            for p in data.get("products", [])[:1]:
                session.remember_context("product", p.get("title") or "", p.get("product_id") or "", limit=MAX_CONTEXT)


# --------------------------------------------------------------------------- helpers


def _ui(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "data": data}


def _list(value: Any, limit: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [v for v in value[:limit] if isinstance(v, dict)]


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def _status(value: Any) -> str:
    """Shopify's SHOUTED_ENUMS, as words: PARTIALLY_FULFILLED -> "partially fulfilled"."""
    return _text(value).replace("_", " ").lower()


def _order_number(value: Any) -> str:
    """The store names orders "CROOKS-1928" and older ones "#1036"; the card says #1928.

    And where the value is a technical id it says nothing at all rather than saying the id.
    §26: "Order #1962", never "gid://shopify/Order/…" — and this fell through to `return text`,
    so a row whose `order_number` was a gid put the gid in the card's own title. Measured on
    this tree before the change:

        present([order_detail with order_number="gid://shopify/Order/1962"])
        -> {'order_number': 'gid://shopify/Order/1962'}   ← the card's heading

    The digits are in the gid, so the number is recoverable and is used; a gid of some other
    kind leaves the field empty, which the renderer already draws as "Order" with no number.
    """
    text = _text(value)
    if text.startswith("gid://"):
        tail = text.rstrip("/").rsplit("/", 1)[-1]
        return f"#{tail}" if tail.isdigit() else ""
    digits = text.rsplit("-", 1)[-1].lstrip("#").strip()
    return f"#{digits}" if digits.isdigit() else text


def _money_text(value: Any) -> str:
    """The tools return "430.50 GBP"; the card shows £430.50."""
    text = _text(value)
    if not text:
        return ""
    parts = text.split()
    if len(parts) == 2:
        amount, currency = parts
        try:
            return _money_display(float(amount), currency) or text
        except ValueError:
            return text
    return text


def _money_display(amount: float | None, currency: str) -> str | None:
    if amount is None:
        return None
    symbol = _CURRENCY_SYMBOL.get((currency or "").upper())
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {currency}".strip()


def _sales_day(day: object, currency: str) -> dict:
    day = day if isinstance(day, dict) else {}
    revenue = _float(day.get("revenue"))
    return {
        "date": _text(day.get("date")),
        "orders": _int(day.get("orders")),
        "revenue": _money_display(revenue, currency) if revenue is not None else None,
    }


# Which key on each card holds its rows. Used only to make an empty one well-formed: a card
# that says "none" must still be the shape the renderer draws, or it is a blank region.
_ROWS_OF = {
    "order_list": "orders", "customer_list": "customers", "email_list": "threads",
    "email_thread": "messages", "inventory": "products", "product": "products",
}


def _empty(kind: str, title: str, note: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """A read that found nothing, as a card (D-15).

    `turn_69abe877ef14` asked for orders, the read came back with none, and the presentation
    layer returned an empty list — so the turn drew NOTHING. The analyser recorded it as
    "(records without a card)" and the owner got one sentence over a blank screen. "None" is
    an answer about the world and belongs on the glass with the question it answers: the same
    card, the same title, `empty` true, a count of zero and one line saying what was looked
    for. `empty` is a visual state (app/render.py VISUAL_KEYS knows nothing of it and does not
    need to: a card that goes from none to some has changed its DATA).
    """
    data: dict[str, Any] = {
        "title": _text(title, 60), "count": 0, "empty": True, "note": _text(note, MAX_NOTE_CHARS),
    }
    rows = _ROWS_OF.get(kind)
    if rows:
        data[rows] = []
    for key, value in (extra or {}).items():
        data.setdefault(key, value)
        if key in data and value not in (None, ""):
            data[key] = value
    return _ui(kind, data)


def _when_words(result: dict[str, Any]) -> str:
    """"today", "yesterday", "in the last 7 days" — the window, in the words the empty card
    uses. The same arithmetic as `_window_title`, said as part of a sentence."""
    days = _int(result.get("days")) or 1
    ago = _int(result.get("days_ago")) or 0
    if days == 1 and ago == 0:
        return "today"
    if days == 1 and ago == 1:
        return "yesterday"
    if ago == 0:
        return f"in the last {days} days"
    return f"in that {days}-day window"


def _window_title(result: dict[str, Any]) -> str:
    days = _int(result.get("days")) or 1
    ago = _int(result.get("days_ago")) or 0
    if days == 1 and ago == 0:
        return "Today"
    if days == 1 and ago == 1:
        return "Yesterday"
    if days == 7 and ago == 0:
        return "Last 7 days"
    if ago == 0:
        return f"Last {days} days"
    return f"{days} day{'s' if days != 1 else ''}, ending {ago} day{'s' if ago != 1 else ''} ago"


# --------------------------------------------------------- the variant picker (order_edit)
#
# The one card in the vocabulary that is drawn from a READ and leads to a change. It is
# bounded here for the same reason every other card is: the recipe hands over a tool result,
# and what reaches the tablet is copied key by key with an explicit cap. A candidate row
# carries the variant id the tap sends back and nothing the tablet could turn into an
# execution argument — the price and the options on it are for the owner's eyes, and the Mac
# reads the price again from Shopify when it prepares the change.

MAX_PICKER_CANDIDATES = 8
MAX_PICKER_OPTIONS = 4
# What one tap may add. The stepper's ceiling on the glass and the write tool's own bound
# (app/tools/shopify_writes.py MAX_ADD_QUANTITY) are the same number, held in both places:
# the tablet cannot post its way past it and the Mac would refuse it anyway.
MAX_PICKER_QUANTITY = 20


def variant_picker(
    result: dict[str, Any], *, order_id: str, order_number: str, quantity: int = 1, note: str = "",
) -> dict[str, Any]:
    """The picker's data, from a `shopify_variant_search` result. Read-only, bounded, whitelisted."""
    candidates = []
    for candidate in _list(result.get("candidates"), MAX_PICKER_CANDIDATES):
        variant_id = _text(candidate.get("variant_id"), 200)
        if not variant_id:
            continue
        candidates.append({
            "variant_id": variant_id,
            "title": _text(candidate.get("title"), 80),
            "variant": _text(candidate.get("variant"), 60),
            "options": [_text(o, 30) for o in _list_strings(candidate.get("options"), MAX_PICKER_OPTIONS)],
            "sku": _text(candidate.get("sku"), 40),
            "price": _text(candidate.get("price_display") or candidate.get("price"), 20),
            "available": _int(candidate.get("available")),
            "for_sale": bool(candidate.get("for_sale")),
        })
    confident = candidates[0]["variant_id"] if (result.get("confident") and len(candidates) == 1) else None
    return {
        "order_id": _text(order_id, 200),
        "order_number": _order_number(order_number),
        "candidates": candidates,
        "count": _int(result.get("count")) or len(candidates),
        "quantity": max(1, min(int(quantity or 1), MAX_PICKER_QUANTITY)),
        "max_quantity": MAX_PICKER_QUANTITY,
        # Exactly one variant matched every word the owner gave: the row is pre-selected, and
        # the owner still taps Add. Never a reason to skip the card.
        "confident_variant_id": confident,
        "note": _text(note or result.get("note"), MAX_NOTE_CHARS),
    }


def _list_strings(value: Any, limit: int) -> list[str]:
    """A bounded list of plain strings. `_list` drops anything that is not an object, which is
    right for rows and silently wrong for a list of option words."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value[:limit] if isinstance(v, (str, int, float)) and str(v).strip()]
