"""Level 1: the deterministic rules, and the table the learner predicts THROUGH.

A rule turns something the owner did into reads worth making now. Nothing here decides whether
a read actually happens — that is the engine's job, with its caps, its dedupe and its
cancellation — and nothing here reads anything itself. A rule is a pure function from a
`Signal` to a `Prediction`, which makes the whole of level 1 testable without a network.

The rules are also the vocabulary level 2 predicts in. A learned transition says an event name
("the owner usually checks the customer's history next"); `for_event` turns that event into the same
`Prediction` the deterministic rule would have made. So the learner cannot invent a read: it
can only bring one of these forward, and there is exactly one place — this table — where a
prediction acquires a tool name.

    order_opened  →  P1  the customer's history and the linked inbox
                     P2  the next record in the set, and the thread a reply would need

P1 is the record on screen: the owner is looking at it and the reads are ones the card itself
would ask for. P2 is a guess about where he goes next, and is the first thing cancelled.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.anticipation.models import (
    LEVEL_LEARNED,
    LEVEL_RULE,
    P1,
    P2,
    Prediction,
    Signal,
)

log = logging.getLogger("crooks.anticipation")

# How far back a linked-inbox prefetch looks, and how many threads it takes. Small: this is a
# speculative Gmail call and the point is not to spend the quota (§18: do not overload Gmail).
EMAIL_DAYS = 30
EMAIL_LIMIT = 5


@dataclass(frozen=True)
class Rule:
    """One deterministic anticipation rule."""

    rule_id: str
    events: tuple[str, ...]
    tier: str
    build: Callable[[Signal], Prediction | None]
    # The owner event this read anticipates, when there is one. This is the join between the
    # learned table (which speaks in events) and the reads (which speak in tools).
    predicts: str = ""


RULES: dict[str, Rule] = {}


def register_rule(rule: Rule) -> Rule:
    """The seam a later family adds a rule through, rather than editing this file."""
    if rule.rule_id in RULES and RULES[rule.rule_id] is not rule:
        raise ValueError(f"the anticipation rule {rule.rule_id!r} is registered twice")
    RULES[rule.rule_id] = rule
    return rule


def all_rules() -> list[Rule]:
    return [RULES[k] for k in sorted(RULES)]


# ------------------------------------------------------------------ the rules themselves


def _customer_history(signal: Signal) -> Prediction | None:
    customer = str(signal.ids.get("customer_id") or "")
    if not customer:
        return None
    from app.memory import ENTITY

    return Prediction(
        key=f"history:{customer}", tier=P1, tool="shopify_customer_history",
        args={"customer_id": customer}, source="shopify", why="order.customer_history",
        level=LEVEL_RULE, memory=(ENTITY, f"customer:{customer}"),
    )


def _linked_email(signal: Signal) -> Prediction | None:
    address = str(signal.ids.get("email") or "")
    if not address or "@" not in address:
        return None
    from app.memory import EMAIL

    return Prediction(
        key=f"inbox:{address}", tier=P1, tool="gmail_search",
        args={"query": f"from:{address}", "days": EMAIL_DAYS, "limit": EMAIL_LIMIT},
        source="gmail", why="order.linked_email", level=LEVEL_RULE,
        memory=(EMAIL, f"from:{address}"),
    )


def _email_thread(signal: Signal) -> Prediction | None:
    """The thread itself, when the order has one waiting.

    This is the "likely action prerequisite" of §18: drafting a reply needs the thread read,
    and the tablet's own drilldown into it reads the same entity key — so the prefetch pays for
    the tap as well as the draft. Speculative, because most orders with an email do not get a
    reply written to them.
    """
    thread = str(signal.ids.get("thread_id") or "")
    if not thread:
        return None
    from app.memory import ENTITY

    return Prediction(
        key=f"thread:{thread}", tier=P2, tool="gmail_read_thread",
        args={"thread_id": thread}, source="gmail", why="order.email_thread",
        level=LEVEL_RULE, memory=(ENTITY, f"email_thread:{thread}"),
    )


def _set_neighbour(signal: Signal) -> Prediction | None:
    """The likely next record: the one after this in the set being worked through. The single
    most-used gesture on the tablet is Next, and this is the read it costs."""
    neighbour = next((n for n in signal.neighbours if n and n != signal.ref), "")
    if not neighbour:
        return None
    from app.memory import ENTITY

    return Prediction(
        key=f"order:{neighbour}", tier=P2, tool="shopify_order_detail",
        args={"order_id": neighbour}, source="shopify", why="order.next_in_set",
        level=LEVEL_RULE, memory=(ENTITY, f"order:{neighbour}"),
    )


for _rule in (
    Rule("order.customer_history", ("order_opened",), P1, _customer_history, predicts="history_checked"),
    Rule("order.linked_email", ("order_opened",), P1, _linked_email, predicts="email_checked"),
    # "order.shipping_state" read the old Easyship boundary (app/shipping) through an internal
    # read, and went with it on 8 October (DEC-071, ruling 24).
    Rule("order.next_in_set", ("order_opened", "next_record"), P2, _set_neighbour, predicts="next_record"),
    Rule("order.email_thread", ("order_opened", "email_checked"), P2, _email_thread, predicts="reply_drafted"),
):
    register_rule(_rule)


# ------------------------------------------------------------------ what the engine asks for


def deterministic(signal: Signal) -> list[Prediction]:
    """Level 1: every rule that fires on this event, P1 before P2."""
    out: list[Prediction] = []
    for rule in all_rules():
        if signal.event not in rule.events:
            continue
        try:
            prediction = rule.build(signal)
        except Exception as exc:  # noqa: BLE001 — a broken rule is a skipped rule
            log.warning("anticipation rule %s failed: %s", rule.rule_id, type(exc).__name__)
            continue
        if prediction is not None:
            out.append(prediction)
    out.sort(key=lambda p: (0 if p.tier == P1 else 1, p.why))
    return out


def for_event(signal: Signal, event: str, *, confidence: float, observations: int) -> Prediction | None:
    """Level 2: the read that anticipates a learned next event, or nothing.

    Speculative by definition — the owner has not asked for it and the evidence is statistical
    — so it comes back at P2 whatever tier its rule normally carries, which puts it first in
    the queue to be cancelled when a real request arrives.
    """
    for rule in all_rules():
        if rule.predicts != event:
            continue
        try:
            prediction = rule.build(signal)
        except Exception as exc:  # noqa: BLE001
            log.warning("anticipation rule %s failed: %s", rule.rule_id, type(exc).__name__)
            return None
        if prediction is None:
            return None
        from dataclasses import replace

        return replace(
            prediction, tier=P2, level=LEVEL_LEARNED, confidence=float(confidence),
            observations=int(observations), why=f"learned:{signal.state}->{event}",
        )
    return None
