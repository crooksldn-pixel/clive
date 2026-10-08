"""What the model does for each sentence the browser gates type (8 October 2026).

Why this exists. Since 28 September every typed or spoken sentence is a model turn (DEC-063): the
word-matching lane that used to answer "show me today's orders" before the model saw it is gone.
The browser gates in `experience/browser.py` (experience.js, email.js, touch.js and the rest)
were written while that lane existed, and they kept typing sentences into a fixture backend whose
model was unscripted. Every one came back as "[model answer]" with nothing drawn, so about sixty
checks failed for a reason that had nothing to do with the screens they were checking.

What it promises. For each sentence a gate types, the fixture model makes the calls Claude makes
for it, through the real gate and the real presenters, exactly as the golden scenarios and the
other browser tests already do (`experience.harness.RecordingProvider.will`). Nothing here decides
what a sentence means for the product: it only stands in for Claude in a test world. Every call
is one Claude could make on this runtime (`experience.harness.model_could_make`), and the browser
gates report a failed check if one is not (`unmakeable`).

One sentence is left to the model's words on purpose: "what's happened today?" is typed by the
screens matrix only to show that a turn which draws nothing keeps the screen it was asked over
(shots 17 to 19, which say so). Scripting a read for it would answer a different question.
"""

from __future__ import annotations

from typing import Any

from experience.fixtures import data
from experience.harness import RecordingProvider, model_could_make, order_reads, todays_orders_reads

#: Mia Jones, the golden world's customer behind order 1938 (experience/fixtures/data.py).
MIA = data.MIA

#: The inbox read Claude makes for "who is waiting on a reply": the inbox itself, no set
#: (`email_query`'s own description says so), over its default 30 days.
INBOX = (("email_query", {"days": 30}),)


def _mia(*, email: bool = False) -> tuple[tuple[str, Any], ...]:
    """Mia Jones by name: find her, read her whole history, and, when the sentence asks, her mail."""
    calls: tuple[tuple[str, Any], ...] = (
        ("shopify_find_customer", {"query": "Mia Jones"}),
        ("shopify_customer_history", {"customer_id": MIA.customer_id}),
    )
    if email:
        calls += (("gmail_search", {"query": MIA.email, "days": 365}),)
    return calls


#: Sentence -> (calls, the words the model says back). Keyed by the exact sentence each gate
#: types; `RecordingProvider` matches case- and whitespace-insensitively.
SCRIPT: dict[str, tuple[tuple[tuple[str, Any], ...], str]] = {
    "show me today's orders": (todays_orders_reads(), "Today's orders."),
    "show me order 1938": (order_reads("1938"), "Order 1938."),
    "show me order 1939": (order_reads("1939"), "Order 1939."),
    "show me order 1940": (order_reads("1940"), "Order 1940."),
    "which customers need replying to?": (INBOX, "Here is who is waiting on a reply."),
    "find emails needing replies": (INBOX, "Here is who is waiting on a reply."),
    # The model reads its own capability table and answers in words; no tool draws a card for it.
    "what can you do now?": ((("commerce_capabilities", {}),), "Orders, customers, email, sales and stock."),
    "has anyone bought today that has bought before, a returning customer?": (
        (("commerce_summary", {"task": "returning_customers", "period": "today"}),), "Here is who came back."),
    "what are the best sellers this month?": (
        (("commerce_aggregate", {"period": "this_month", "group_by": ["product"], "metrics": ["units", "revenue"],
                                 "view": "ranking"}),), "This month's best sellers."),
    # The customer the gate has on screen when it asks is Mia (order 1938).
    "what else has this customer ordered?": (
        (("shopify_customer_history", {"customer_id": MIA.customer_id}),), "Her history."),
    "show me mia jones's orders in her lifetime": (_mia(), "Mia's orders."),
    "can you expand mia jones's customer page?": (_mia(), "Mia's page."),
    "pull up the history of mia jones and her orders, see how much she spent, and see if she is in gmail anywhere": (
        _mia(email=True), "Mia's history, and her mail."),
    ("pull up the history of mia jones and her orders, see how many times she has ordered, see how much she "
     "spent in total, and see if she is in gmail anywhere"): (_mia(email=True), "Mia's history, and her mail."),
}


def script(provider: RecordingProvider, runtime: Any) -> None:
    """Teach the fixture model every sentence above, bound to this runtime."""
    provider.runtime = runtime
    for said, (calls, reply) in SCRIPT.items():
        provider.will(said, *calls, reply=reply)


def unmakeable(provider: RecordingProvider, runtime: Any) -> list[dict[str, Any]]:
    """Every call the gates stood in for Claude with that Claude could not make, as failed checks."""
    out = []
    for name, args in provider.made:
        why = model_could_make(runtime, name, args)
        if why:
            out.append({"name": f"the gate's model made a call Claude could make: {name}", "ok": False,
                        "detail": why})
    return out
