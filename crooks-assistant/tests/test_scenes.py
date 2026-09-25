"""app/scenes: typed evidence, the scene-plan schema and the validator (Generative UI V1, 1 of 4).

The rule under test: connectors describe data, CLIVE decides what to show, the screen shows
findings not sources. Everything here is synthetic and offline; nothing touches a live system.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scenes import DEFAULT, Evidence, SceneContext, ScenePlan, to_evidence, validate_scene
from app.scenes.evidence import FieldDescriptor, Kind, Money, Registry, Series, ToolDescriptors
from app.scenes.scene import Answer, Finding, Question
from app.scenes.validate import FALLBACK_ANSWER, asks_for_list

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "app" / "scenes"
TOOLS = ROOT / "app" / "tools"
NOW = datetime(2026, 9, 24, 17, 0, tzinfo=UTC)
SESSION = "sess-0924"


# ------------------------------------------------------------------ synthetic reads


def _order(n: int) -> dict:
    return {
        "order_id": f"gid://shopify/Order/{5000 + n}", "order_number": f"CROOKS-{1900 + n}",
        "placed_at": (NOW - timedelta(hours=5 * n)).isoformat(), "fulfillment": "UNFULFILLED" if n % 3 == 0 else "FULFILLED",
        "payment": "PAID", "total": f"{40 + 7 * n}.00 GBP", "customer_name": f"Customer {n}",
        "customer_id": f"gid://shopify/Customer/{700 + n}", "customer_email": f"customer{n}@example.com",
    }


def _thread(n: int) -> dict:
    return {
        "thread_id": f"t{n}", "message_id": f"m{n}", "from": f"Customer {n}", "from_email": f"customer{n}@example.com",
        "subject": f"Re: order CROOKS-{1900 + n}", "date": f"Wed, 24 Sep 2026 09:{10 + n:02d}:00 +0100",
        "snippet": "Thanks, that's arrived.", "likely_bulk": False, "authenticated": True, "known_customer": True,
    }


def _customer_row(n: int, *, waiting: bool = False) -> dict:
    emailed = waiting or n < 7
    return {
        "customer_id": f"gid://shopify/Customer/{700 + n}", "customer_name": f"Customer {n}", "customer_email": f"customer{n}@example.com",
        "orders": [f"CROOKS-{1900 + n}"], "emailed": emailed, "threads": 1 if emailed else 0,
        "replied": (not waiting) if emailed else None, "last_subject": "Where is my order?" if emailed else "", "last_date": "",
        "last_thread_id": f"t{n}" if emailed else "", "checked": True, "thread_count": 1 if emailed else 0,
        "latest_inbound_at": 1_790_000_000_000 + 60_000 * n if emailed else None,
        "latest_outbound_at": (1_790_000_900_000 + n) if emailed and not waiting else None,
        "latest_direction": ("inbound" if waiting else "outbound") if emailed else "none",
        "has_reply_after_latest_inbound": (not waiting) if emailed else None, "needs_reply": waiting,
        "related_orders": [], "confidence": "confident" if emailed else "none", "provenance": {},
    }


def _email_query(rows: list[dict]) -> dict:
    counts = {
        "contacted": sum(1 for r in rows if r["emailed"]), "not_contacted": sum(1 for r in rows if not r["emailed"]),
        "replied": sum(1 for r in rows if r["replied"]), "needs_reply": sum(1 for r in rows if r["needs_reply"]), "unchecked": 0,
    }
    return {"set_id": "ws1", "set_label": "customers, last 30 days", "kind": "customers", "days": 30, "customers": len(rows),
            "counts": counts, "rows": rows, "source": "Gmail threads from each customer", "note": ""}


def _commerce_orders(n: int) -> dict:
    rows = [{
        "order_id": f"gid://shopify/Order/{6000 + i}", "order_number": f"CROOKS-{2000 + i}", "placed_at": (NOW - timedelta(days=i + 3)).isoformat(),
        "age_days": float(i + 3), "fulfillment": "UNFULFILLED", "payment": "PAID", "total": 50.0 + i, "currency": "GBP",
        "customer_name": f"Buyer {i}", "customer_id": f"gid://shopify/Customer/{900 + i}", "customer_email": f"buyer{i}@example.com",
        "country_code": "GB", "tags": [], "items": 1, "has_tracking": False, "cancelled": False,
    } for i in range(n)]
    revenue = round(sum(r["total"] for r in rows), 2)
    return {
        "entity": "orders", "period": {"label": "last 90 days"}, "filters": {"fulfillment": "unfulfilled"}, "group_by": [], "metrics": [],
        "rows": rows, "row_count": n, "truncated": False, "currency": "GBP", "complete": True,
        "totals": {"orders": n, "revenue": revenue, "unfulfilled_value": revenue, "units": n, "customers": n, "refunded": 0.0},
    }


def _september_evidence() -> list:
    """The 2026-09-24 reads: forty rows across orders, threads and customers, and in all of
    them nobody waiting on a reply."""
    orders = to_evidence(
        "shopify_list_orders",
        {"since": "2026-09-17T23:00:00Z", "until": "2026-09-24T23:00:00Z", "timezone": "Europe/London", "days": 7, "days_ago": 0,
         "count": 8, "truncated": False, "orders": [_order(n) for n in range(8)]},
        handle="ev-orders", args={"days": 7, "limit": 20}, observed_at=NOW, session_id=SESSION,
    )
    threads = to_evidence(
        "gmail_search", {"query": "newer_than:7d category:primary", "count": 7, "threads": [_thread(n) for n in range(7)], "note": ""},
        handle="ev-threads", args={"days": 7}, observed_at=NOW, session_id=SESSION,
    )
    customers = to_evidence(
        "email_query", _email_query([_customer_row(n) for n in range(25)]),
        handle="ev-customers", args={"set_id": "ws1", "days": 30}, observed_at=NOW, session_id=SESSION,
    )
    return [orders, threads, customers]


def _final(trace) -> dict:
    """Each target's one final decision, kept or dropped. A target decided twice fails."""
    out: dict = {}
    for entry in trace:
        if entry.decision in ("kept", "dropped"):
            assert entry.target not in out, f"{entry.target} was decided twice"
            out[entry.target] = entry
    return out


def _reductions(trace, target: str) -> list[str]:
    return [e.reason for e in trace if e.target == target and e.decision == "reduced"]


def _no_pii(scene) -> None:
    assert not any(b.pii for b in scene.bound())
    dumped = json.dumps(scene.as_dict())
    assert "@" not in dumped and "example.com" not in dumped


# ------------------------------------------------------------------ the cases


def test_the_2026_09_24_case_is_one_answer_and_a_drill_down():
    """'any customers who need a reply': one correct sentence, and the five cards today's
    screen drew beside it — three lists of sources, a ranking with an invented count, and a
    customer's email address. Only the sentence survives, with a reference to what it checked."""
    evidence = _september_evidence()
    assert sum(len(ev.records) for ev in evidence) == 40
    plan = {
        "answer": {
            "text": "Nobody is waiting on a reply: all {0} customers who emailed have been answered.",
            "values": [{"evidence": "ev-customers", "field": "replied"}],
            "justification": "The owner asked whether any customer needs a reply.",
        },
        "elements": [
            {"type": "collection", "evidence": "ev-customers", "columns": ["customer_name", "customer_email", "threads", "replied"],
             "limit": 25, "justification": "The customers that were checked."},
            {"type": "collection", "evidence": "ev-orders", "columns": ["order_number", "customer_email", "total"], "limit": 8},
            {"type": "collection", "evidence": "ev-threads", "columns": ["from", "from_email", "subject"], "limit": 7, "justification": ""},
            {"type": "finding", "significance": "CONTEXT", "text": "Top 25 customers ranked by lifetime spend.",
             "evidence": ["ev-customers"], "justification": "Context on who was checked."},
            {"type": "entity", "evidence": "ev-customers", "record": "gid://shopify/Customer/700", "fields": ["customer_email"],
             "justification": "The biggest customer."},
        ],
    }
    context = SceneContext.for_request("any customers who need a reply", session_id=SESSION)
    assert context.list_requested is False

    scene, trace = validate_scene(plan, evidence, context)

    assert scene.elements == ()
    assert scene.answer.text() == "Nobody is waiting on a reply: all 7 customers who emailed have been answered."
    assert scene.drilldown is not None
    assert scene.drilldown.handles == ("ev-orders", "ev-threads", "ev-customers")
    assert sum(s.records for s in scene.drilldown.sources) == 40
    _no_pii(scene)

    final = _final(trace)
    assert final["answer"].decision == "kept"
    assert "lists a source" in final["elements[0] collection"].reason
    assert _reductions(trace, "elements[0] collection") == [
        "customer_email: pii stripped; the task does not need contact details",
        "rows 25 → 8: the most shown unless the request asks to see a list",
    ]
    assert "justification" in final["elements[1] collection"].reason
    assert "justification" in final["elements[2] collection"].reason
    assert "number" in final["elements[3] finding"].reason
    assert "no chosen field" in final["elements[4] entity"].reason
    assert all(final[f"elements[{i}] {t}"].decision == "dropped" for i, t in enumerate(["collection"] * 3 + ["finding", "entity"]))
    assert final["drilldown"].decision == "kept"


def test_nothing_needs_you_is_one_line():
    mail = to_evidence("email_query", _email_query([_customer_row(n) for n in range(5)]), handle="ev-mail", observed_at=NOW, session_id=SESSION)
    overdue = to_evidence("commerce_query", _commerce_orders(0), handle="ev-overdue", observed_at=NOW, session_id=SESSION)
    plan = {"answer": {"text": "Nothing needs you right now.", "justification": "No customer is waiting and no order is overdue."}}

    scene, trace = validate_scene(plan, [mail, overdue], SceneContext.for_request("anything need me?", session_id=SESSION))

    assert scene.elements == ()
    assert scene.answer.text() == "Nothing needs you right now."
    assert len(scene.answer.text().splitlines()) == 1
    # The drill-down is a reference to open, not a line on the screen.
    assert scene.drilldown is not None and scene.drilldown.handles == ("ev-mail", "ev-overdue")
    assert [(e.target, e.decision) for e in trace] == [("answer", "kept"), ("drilldown", "kept")]
    _no_pii(scene)


def test_nothing_checked_means_no_drill_down():
    scene, trace = validate_scene({"answer": {"text": "Nothing needs you right now.", "justification": "Asked."}}, [])
    assert scene.elements == () and scene.drilldown is None
    assert [(e.target, e.decision) for e in trace] == [("answer", "kept")]


def test_an_adversarial_plan_is_reduced_and_every_reduction_is_traced():
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 3) for n in range(12)]),
                       handle="ev-mail", observed_at=NOW, session_id=SESSION)
    orders = to_evidence("commerce_query", _commerce_orders(20), handle="ev-orders", observed_at=NOW, session_id=SESSION)
    ghost = to_evidence("shopify_sales_summary", {"orders": 3, "revenue": 120.0, "currency": "GBP", "complete": True},
                        handle="ev-ghost", observed_at=NOW, session_id="someone-else")
    plan = {
        "answer": {"text": "{0} customers are waiting on a reply from you.", "values": [{"evidence": "ev-mail", "field": "needs_reply"}],
                   "justification": "The owner asked what needs doing."},
        "elements": [
            {"type": "finding", "significance": "ACTION_REQUIRED", "text": "{0} customers have been waiting since yesterday.",
             "values": [{"evidence": "ev-mail", "field": "needs_reply"}], "evidence": ["ev-mail"], "justification": "They need answering today."},
            {"type": "finding", "significance": "RISK", "text": "Revenue is down 40% on last week.", "evidence": ["ev-orders"],
             "justification": "A worrying drop."},
            {"type": "finding", "significance": "RISK", "text": "<b>Urgent</b>: refunds are pending.", "evidence": ["ev-orders"],
             "justification": "Refunds matter."},
            {"type": "collection", "evidence": "ev-mail", "columns": ["customer_name", "customer_email", "last_subject"], "limit": 30,
             "justification": "Who is waiting."},
            {"type": "collection", "evidence": "ev-orders", "columns": ["order_number", "total"], "limit": 5, "justification": "   "},
            {"type": "measure", "value": {"evidence": "ev-ghost", "field": "revenue"}, "justification": "Sales this week."},
            {"type": "finding", "significance": "UNCERTAINTY", "text": "Profit was about {0} this week.",
             "values": [{"evidence": "ev-orders", "field": "profit"}], "evidence": ["ev-orders"], "justification": "Margins."},
            {"type": "proposal", "action": "act-999", "justification": "Refund them all."},
            {"type": "entity", "evidence": "ev-mail", "record": "gid://shopify/Customer/700", "fields": ["customer_email"],
             "justification": "Who to write to first."},
            {"type": "finding", "significance": "DECISION_REQUIRED", "text": "{0} orders are still to ship.",
             "values": [{"evidence": "ev-orders", "field": "row_count"}], "evidence": ["ev-orders"], "justification": "They may need chasing."},
            {"type": "proposal", "action": "act-1", "justification": "Draft the replies."},
            {"type": "measure", "value": {"evidence": "ev-orders", "field": "unfulfilled_value"}, "justification": "Money waiting to ship."},
        ],
    }
    context = SceneContext.for_request("anything I need to do today?", session_id=SESSION, actions=frozenset({"act-1"}))

    scene, trace = validate_scene(plan, [mail, orders, ghost], context)

    # What survives: the answer, the finding, the list it is about, and the second finding.
    assert scene.answer.text() == "3 customers are waiting on a reply from you."
    assert [s.element.type for s in scene.elements] == ["finding", "collection", "finding"]
    assert scene.elements[0].text() == "3 customers have been waiting since yesterday."
    collection = scene.elements[1]
    assert collection.element.columns == ["customer_name", "last_subject"]
    assert collection.element.limit == 8 and len(collection.rows) == 8
    assert scene.elements[2].text() == "20 orders are still to ship."
    assert scene.drilldown is None
    assert {b.evidence for b in scene.bound()} == {"ev-mail", "ev-orders"}
    _no_pii(scene)

    final = _final(trace)
    assert len([t for t in final if t.startswith("elements[")]) == len(plan["elements"])
    decided = {t: e.decision for t, e in final.items()}
    assert decided["elements[0] finding"] == decided["elements[3] collection"] == decided["elements[9] finding"] == "kept"
    reasons = {t: e.reason for t, e in final.items()}
    assert "number" in reasons["elements[1] finding"]
    assert "markup" in reasons["elements[2] finding"]
    assert "justification" in reasons["elements[4] collection"]
    assert "ev-ghost is not evidence from this session" in reasons["elements[5] measure"]
    assert "no field profit" in reasons["elements[6] finding"]
    assert "act-999 is not an existing action" in reasons["elements[7] proposal"]
    assert "no chosen field" in reasons["elements[8] entity"]
    assert "attention budget" in reasons["elements[10] proposal"]
    assert "attention budget" in reasons["elements[11] measure"]
    assert _reductions(trace, "elements[3] collection") == [
        "customer_email: pii stripped; the task does not need contact details",
        "rows 30 → 8: the most shown unless the request asks to see a list",
    ]
    assert _reductions(trace, "elements[8] entity") == ["customer_email: pii stripped; the task does not need contact details"]
    assert any(e.target == "evidence ev-ghost" and e.decision == "ignored" for e in trace)


def test_an_answer_that_cannot_be_shown_is_replaced_never_dropped():
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n == 0) for n in range(4)]), handle="ev-mail",
                       observed_at=NOW, session_id=SESSION)
    for text, values, why in (
        ("Sales are up 12% this week.", [], "number"),
        ("<script>alert()</script> nobody is waiting.", [], "markup"),
        ("Write to {0} today.", [{"evidence": "ev-mail", "field": "customer_email", "record": "gid://shopify/Customer/700"}], "pii"),
        ("{0} are waiting.", [{"evidence": "ev-other", "field": "needs_reply"}], "not evidence from this session"),
    ):
        scene, trace = validate_scene({"answer": {"text": text, "values": values, "justification": "Asked."}}, [mail],
                                      SceneContext(session_id=SESSION))
        assert scene.answer.element.text == FALLBACK_ANSWER
        assert scene.drilldown is not None and scene.drilldown.handles == ("ev-mail",)
        replaced = [e for e in trace if e.target == "answer"]
        assert len(replaced) == 1 and replaced[0].decision == "replaced" and why in replaced[0].reason
        _no_pii(scene)


def test_contact_details_are_kept_only_when_the_task_needs_them():
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 2) for n in range(4)]), handle="ev-mail",
                       observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "Write to {0} today.", "values": [{"evidence": "ev-mail", "field": "customer_email", "record": "gid://shopify/Customer/700"}],
                   "justification": "The owner asked for their address."},
        "elements": [
            {"type": "finding", "significance": "ACTION_REQUIRED", "text": "{0} customers are waiting.",
             "values": [{"evidence": "ev-mail", "field": "needs_reply"}], "evidence": ["ev-mail"], "justification": "They need a reply."},
            {"type": "collection", "evidence": "ev-mail", "columns": ["customer_name", "customer_email"], "limit": 2, "justification": "Who to write to."},
        ],
    }
    scene, trace = validate_scene(plan, [mail], SceneContext(request="their email addresses please", session_id=SESSION, contact_details=True))
    assert scene.answer.text() == "Write to customer0@example.com today."
    assert scene.elements[1].element.columns == ["customer_name", "customer_email"]
    assert not [e for e in trace if e.decision == "reduced"]


def test_a_list_asked_for_is_shown_without_a_finding_up_to_the_list_limit():
    assert asks_for_list("list every customer who emailed")
    assert not asks_for_list("any customers who need a reply")
    mail = to_evidence("email_query", _email_query([_customer_row(n) for n in range(30)]), handle="ev-mail", observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "Here are the customers I checked.", "justification": "The owner asked for the list."},
        "elements": [{"type": "collection", "evidence": "ev-mail", "columns": ["customer_name", "replied"], "limit": 40, "justification": "The list asked for."}],
    }
    scene, trace = validate_scene(plan, [mail], SceneContext.for_request("list every customer who emailed", session_id=SESSION))
    assert len(scene.elements) == 1 and len(scene.elements[0].rows) == 25
    assert _reductions(trace, "elements[0] collection") == ["rows 40 → 25: the most a list shows"]


def test_value_bearing_primitives_bind_to_evidence_of_the_right_kind():
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 3) for n in range(6)]), handle="ev-mail",
                       observed_at=NOW, session_id=SESSION)
    sales = to_evidence("commerce_aggregate", {
        "entity": "orders", "group_by": [], "rows": [], "currency": "GBP", "totals": {"orders": 40, "revenue": 3100.0},
        "compare": {"totals": {"orders": 35, "revenue": 2800.0}},
    }, handle="ev-sales", observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "Sales are ahead of last week.", "justification": "Asked how the week is going."},
        "elements": [
            {"type": "finding", "significance": "ACTION_REQUIRED", "text": "{0} customers are waiting.",
             "values": [{"evidence": "ev-mail", "field": "needs_reply"}], "evidence": ["ev-mail"], "justification": "They need a reply."},
            {"type": "timeline", "evidence": "ev-mail", "at": "latest_inbound_at", "label": "customer_name", "limit": 3, "justification": "When they wrote."},
            {"type": "comparison", "current": {"evidence": "ev-sales", "field": "revenue"}, "previous": {"evidence": "ev-sales", "field": "previous_revenue"},
             "justification": "This week against last."},
        ],
    }
    scene, trace = validate_scene(plan, [mail, sales], SceneContext(session_id=SESSION))
    assert [s.element.type for s in scene.elements] == ["finding", "timeline", "comparison"]
    timeline = scene.elements[1]
    assert len(timeline.rows) == 3 and all(row[0].kind is Kind.DATETIME for row in timeline.rows)
    current, previous = scene.elements[2].values
    assert current.value == Money(Decimal("3100.0"), "GBP") and previous.value == Money(Decimal("2800.0"), "GBP")

    wrong = {
        "answer": {"text": "Sales are ahead of last week.", "justification": "Asked."},
        "elements": [
            {"type": "measure", "value": {"evidence": "ev-mail", "field": "set_label"}, "justification": "Words are not a quantity."},
            {"type": "trend", "series": {"evidence": "ev-sales", "field": "revenue"}, "justification": "Not a series."},
            {"type": "timeline", "evidence": "ev-mail", "at": "customer_name", "label": "customer_name", "limit": 3, "justification": "Not a time."},
            {"type": "comparison", "current": {"evidence": "ev-sales", "field": "revenue"}, "previous": {"evidence": "ev-sales", "field": "orders"},
             "justification": "Different kinds."},
            {"type": "question", "text": "Shall I draft the 3 replies?", "options": ["Yes", "No"], "justification": "Needs the owner."},
        ],
    }
    scene, trace = validate_scene(wrong, [mail, sales], SceneContext(session_id=SESSION))
    assert scene.elements == ()
    final = _final(trace)
    assert "not a quantity" in final["elements[0] measure"].reason
    assert "not a series" in final["elements[1] trend"].reason
    assert "not a time" in final["elements[2] timeline"].reason
    assert "same kind" in final["elements[3] comparison"].reason
    assert "number" in final["elements[4] question"].reason


# -------------------------------------------------------------------- the schema


@pytest.mark.parametrize("plan", [
    {"answer": {"text": "Fine.", "html": "<b>Fine</b>"}},
    {"answer": {"text": "Fine."}, "elements": [{"type": "chart", "justification": "A chart."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "measure", "value": 42, "justification": "A raw number."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "collection", "evidence": "ev", "columns": ["a"], "limit": 3, "rows": [["x"]]}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "collection", "evidence": "ev", "columns": ["a"], "limit": "8"}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "finding", "significance": "URGENT", "text": "Fine."}]},
    {"answer": {"text": "One.\nTwo.\nThree."}},
    {"answer": {"text": "Fine.", "values": [{"evidence": "ev", "field": "total", "value": 99}]}},
    {"answer": {"text": "Fine."}, "elements": [{"type": "proposal", "action": "act-1", "mutation": "refund_create"}]},
    # Prose has words once trimmed, and its lines are counted at every line boundary.
    {"answer": {"text": "   "}},
    {"answer": {"text": "\t\t"}},
    {"answer": {"text": "\r"}},
    {"answer": {"text": " \r\n \t "}},
    {"answer": {"text": "One.\rTwo.\rThree."}},
    {"answer": {"text": "One.\r\nTwo.\r\nThree."}},
    {"answer": {"text": "Fine."}, "elements": [{"type": "finding", "significance": "CONTEXT", "text": " \t ", "evidence": ["ev"], "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "finding", "significance": "CONTEXT", "text": "\r", "evidence": ["ev"], "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "finding", "significance": "CONTEXT", "text": "One.\rTwo.", "evidence": ["ev"], "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "question", "text": "   ", "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "question", "text": "\t\r\n", "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "question", "text": "Shall I?\rNow?", "justification": "Why."}]},
    {"answer": {"text": "Fine."}, "elements": [{"type": "question", "text": "Shall I?", "options": ["  "], "justification": "Why."}]},
])
def test_the_plan_schema_is_strict(plan):
    with pytest.raises(ValidationError):
        ScenePlan.model_validate(plan)


def test_prose_is_trimmed_and_its_lines_counted_at_every_boundary():
    plan = ScenePlan.model_validate({
        "answer": {"text": "  Nobody is waiting.\r\nAll answered.\t"},
        "elements": [{"type": "question", "text": " Shall I draft replies? ", "options": [" Yes "], "justification": "Why."}],
    })
    assert plan.answer.text == "Nobody is waiting.\r\nAll answered."
    assert plan.elements[0].text == "Shall I draft replies?" and plan.elements[0].options == ["Yes"]


def test_the_validator_refuses_blank_or_overlong_prose_it_is_handed_directly():
    """A plan built without the schema's checks meets the same rule in the validator."""
    mail = to_evidence("email_query", _email_query([_customer_row(n) for n in range(3)]), handle="ev-mail", observed_at=NOW, session_id=SESSION)
    for text, why in (("   ", "only whitespace"), ("\t", "only whitespace"), ("\r", "only whitespace"), (" \r\n ", "only whitespace"),
                      ("One.\rTwo.\rThree.", "line")):
        plan = ScenePlan.model_construct(
            answer=Answer.model_construct(text=text, values=[], justification="Asked."),
            elements=[
                Finding.model_construct(significance="CONTEXT", text=text, values=[], evidence=["ev-mail"], justification="Context."),
                Question.model_construct(text=text, options=[], justification="Needs the owner."),
                Finding.model_construct(significance="CONTEXT", text="Nobody is waiting.\rReally.", values=[], evidence=["ev-mail"],
                                        justification="Context."),
                Finding.model_construct(significance="CONTEXT", text="Nobody is waiting.", values=[], evidence=["ev-mail"],
                                        justification="Context.\rAnd more."),
            ],
        )
        scene, trace = validate_scene(plan, [mail], SceneContext(session_id=SESSION))

        assert scene.answer.element.text == FALLBACK_ANSWER and scene.elements == ()
        answer = [e for e in trace if e.target == "answer"]
        assert len(answer) == 1 and answer[0].decision == "replaced" and why in answer[0].reason
        final = _final(trace)
        assert why in final["elements[0] finding"].reason and why in final["elements[1] question"].reason
        assert "line" in final["elements[2] finding"].reason
        assert "no one-line justification" in final["elements[3] finding"].reason
        assert all(final[t].decision == "dropped" for t in final if t.startswith("elements["))


# ------------------------------------------------------------------- session provenance


def test_evidence_from_another_session_is_refused_even_without_a_session():
    ours = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 2) for n in range(4)]), handle="ev-ours",
                       observed_at=NOW, session_id=SESSION)
    foreign = to_evidence("email_query", _email_query([_customer_row(n, waiting=True) for n in range(9)]), handle="ev-foreign",
                          observed_at=NOW, session_id="someone-else")
    untagged = to_evidence("email_query", _email_query([_customer_row(n, waiting=True) for n in range(5)]), handle="ev-untagged",
                           observed_at=NOW)

    # With no session established, nothing is this session's: tagged or not, it is refused.
    for handle, ev in (("ev-foreign", foreign), ("ev-untagged", untagged), ("ev-ours", ours)):
        plan = {"answer": {"text": "{0} customers are waiting on a reply.", "values": [{"evidence": handle, "field": "needs_reply"}],
                           "justification": "Asked."}}
        for context in (None, SceneContext(), SceneContext(session_id=""), SceneContext.for_request("anyone waiting?")):
            scene, trace = validate_scene(plan, [ev], context)
            assert scene.answer.element.text == FALLBACK_ANSWER and scene.answer.values == ()
            assert scene.drilldown is None and list(scene.bound()) == []
            assert [(e.target, e.decision) for e in trace if e.target.startswith("evidence")] == [(f"evidence {handle}", "ignored")]
            answer = [e for e in trace if e.target == "answer"]
            assert f"{handle} is not evidence from this session" in answer[0].reason

    # In a session, only its own evidence is bound; foreign and untagged evidence beside it is not.
    mixed = {
        "answer": {"text": "{0} customers are waiting on a reply.", "values": [{"evidence": "ev-ours", "field": "needs_reply"}],
                   "justification": "Asked."},
        "elements": [
            {"type": "measure", "value": {"evidence": "ev-foreign", "field": "needs_reply"}, "justification": "Another session's."},
            {"type": "measure", "value": {"evidence": "ev-untagged", "field": "needs_reply"}, "justification": "Nobody's."},
        ],
    }
    scene, trace = validate_scene(mixed, [ours, foreign, untagged], SceneContext(session_id=SESSION))
    assert scene.answer.text() == "2 customers are waiting on a reply."
    assert scene.elements == () and {b.evidence for b in scene.bound()} == {"ev-ours"}
    assert scene.drilldown is not None and scene.drilldown.handles == ("ev-ours",)
    assert {e.target for e in trace if e.decision == "ignored"} == {"evidence ev-foreign", "evidence ev-untagged"}
    final = _final(trace)
    assert "ev-foreign is not evidence from this session" in final["elements[0] measure"].reason
    assert "ev-untagged is not evidence from this session" in final["elements[1] measure"].reason


# --------------------------------------------------------- what a drill-down says it asked


def test_a_drill_down_never_carries_the_address_or_postcode_that_was_searched_for():
    """An address search's arguments are a street address and a postcode. A scene without
    contact details refers to those reads, and neither value is anywhere in it."""
    found = to_evidence("gmail_find_in_email", {
        "contains": "E1 6AN", "threads_found": 1, "threads_checked": 1, "threads_unreadable": 0, "complete": True, "match_count": 1,
        "matches": [{"message_id": "m1", "thread_id": "t1", "subject": "New address", "date": "2026-09-23T10:00:00Z",
                     "from": "jo@example.com", "outbound": False, "where": "body", "excerpt": "12 Acacia Avenue, London E1 6AN"}],
    }, handle="ev-found", args={"contains": "E1 6AN", "address": "12 Acacia Avenue, London"}, observed_at=NOW, session_id=SESSION)
    searched = to_evidence("gmail_search", {"count": 0, "threads": []}, handle="ev-searched",
                           args={"query": "\"12 Acacia Avenue\" OR E1 6AN", "days": 30}, observed_at=NOW, session_id=SESSION)
    told = to_evidence("shopify_find_order", {"orders": []}, handle="ev-told", observed_at=NOW, session_id=SESSION,
                       query="orders shipping to 12 Acacia Avenue, postcode E1 6AN, where contains='E1 6AN'")
    direct = Evidence(handle="ev-direct", tool="gmail_search", observed_at=NOW, session_id=SESSION,
                      query="threads mentioning Flat 3, 12 Acacia Avenue E1 6AN")

    # A default summary names the arguments, never their values; a given one keeps only known words.
    assert found.query == "Search in email by contains, address"
    assert searched.query == "Inbox by query, days"
    assert told.query == "orders shipping to [value], postcode [value], where contains [value]"
    assert direct.query == "threads mentioning [value]"

    plan = {"answer": {"text": "Nobody has written to us from that address.", "justification": "The owner asked about an address."}}
    context = SceneContext.for_request("has anyone at that address emailed us?", session_id=SESSION)
    assert context.contact_details is False
    scene, trace = validate_scene(plan, [found, searched, told, direct], context)

    assert scene.elements == ()
    assert scene.drilldown is not None and scene.drilldown.handles == ("ev-found", "ev-searched", "ev-told", "ev-direct")
    serialised = json.dumps(scene.as_dict()) + json.dumps(scene.drilldown.as_dict()) + json.dumps([e.reason for e in trace])
    for value in ("E1 6AN", "6AN", "Acacia", "Avenue", "Flat 3"):
        assert value not in serialised
        assert all(value not in source.query for source in scene.drilldown.sources)
    _no_pii(scene)


GIVEN_SUMMARIES = [
    # A phone number in a form no pattern for UK numbers knows.
    ("customer phone 415-555-1212", "customer phone [value]", ("415", "555", "1212")),
    ("orders for +1 (415) 555 1212 or 415.555.1212", "orders for [value] or [value]", ("415", "555", "1212")),
    # Addresses and postcodes from other countries.
    ("orders shipping to 1600 Amphitheatre Parkway, Mountain View, CA 94043", "orders shipping to [value]",
     ("1600", "Amphitheatre", "Parkway", "Mountain", "View", "CA", "94043")),
    ("orders to Rue de Rivoli 75001 Paris, Canada K1A 0B1", "orders to [value]", ("Rivoli", "75001", "Paris", "Canada", "K1A", "0B1")),
    ("orders to 〒100-0001 東京都千代田区", "orders to [value]", ("〒", "100-", "東京")),
    # Who it was about.
    ("orders for Jo Bloggs of Hauptstraße, Berlin", "orders for [value] of [value]", ("Bloggs", "Hauptstraße", "Berlin")),
    ("orders for jo.bloggs@example.co.uk", "orders for [value]", ("bloggs", "@", "example")),
]


def test_a_given_summary_keeps_only_known_words():
    """What a caller says was asked is kept word by word only where the word is known to be
    safe; any other word, and every number, is `[value]` — whatever country's form it takes."""
    evidence = []
    for n, (query, expected, _) in enumerate(GIVEN_SUMMARIES):
        told = to_evidence("shopify_find_order", {"orders": []}, handle=f"ev-told-{n}", query=query, observed_at=NOW, session_id=SESSION)
        direct = Evidence(handle=f"ev-direct-{n}", tool="gmail_search", observed_at=NOW, session_id=SESSION, query=query)
        assert told.query == expected and direct.query == expected
        evidence += [told, direct]

    plan = {"answer": {"text": "Nobody has ordered from there.", "justification": "The owner asked about a customer."}}
    scene, trace = validate_scene(plan, evidence, SceneContext.for_request("has anyone there ordered?", session_id=SESSION))

    assert scene.elements == () and scene.drilldown is not None and len(scene.drilldown.sources) == len(evidence)
    serialised = json.dumps(scene.as_dict(), ensure_ascii=False) + json.dumps([e.reason for e in trace], ensure_ascii=False)
    for _, _, secrets in GIVEN_SUMMARIES:
        for secret in secrets:
            assert secret not in serialised, secret
    _no_pii(scene)


def test_values_in_words_or_as_addresses_are_refused_unless_bound():
    """A number spelled out, a fraction, a multiple or an email address is a value, and a
    value comes from evidence through a slot: citing an evidence handle does not bind it."""
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 3) for n in range(12)]), handle="ev-mail",
                       observed_at=NOW, session_id=SESSION)

    def finding(text: str) -> dict:
        return {"type": "finding", "significance": "ACTION_REQUIRED", "text": text, "evidence": ["ev-mail"], "justification": "They need a reply."}

    plan = {
        "answer": {"text": "{0} customers are waiting on a reply.", "values": [{"evidence": "ev-mail", "field": "needs_reply"}],
                   "justification": "The owner asked who is waiting."},
        "elements": [
            finding("Forty customers are waiting."),
            finding("Half of them have waited since yesterday."),
            finding("Replies now take double the usual time."),
            finding("Twenty-five customers wrote this month."),
            finding("Email jo@example.com first."),
            finding("The newest are listed at crooks.example.com today."),
            {"type": "question", "text": "Shall I answer the dozen oldest?", "justification": "Needs the owner."},
            finding("{0} customers are waiting since yesterday.") | {"values": [{"evidence": "ev-mail", "field": "needs_reply"}]},
        ],
    }
    scene, trace = validate_scene(plan, [mail], SceneContext(session_id=SESSION))

    assert scene.answer.text() == "3 customers are waiting on a reply."
    assert [s.text() for s in scene.elements] == ["3 customers are waiting since yesterday."]
    final = _final(trace)
    for index in range(4):
        assert final[f"elements[{index}] finding"].decision == "dropped"
        assert "a number in the text that is not bound to evidence" in final[f"elements[{index}] finding"].reason
    for index in (4, 5):
        assert final[f"elements[{index}] finding"].decision == "dropped"
        assert "email or web address" in final[f"elements[{index}] finding"].reason
    assert "number" in final["elements[6] question"].reason
    assert final["elements[7] finding"].decision == "kept"
    _no_pii(scene)

    for text, why in (
        ("Forty customers are waiting on a reply.", "number"),
        ("About half of them are waiting.", "number"),
        ("Orders doubled on last week.", "number"),
        ("Write to jo@example.com today.", "email or web address"),
    ):
        scene, trace = validate_scene({"answer": {"text": text, "justification": "Asked."}}, [mail], SceneContext(session_id=SESSION))
        assert scene.answer.element.text == FALLBACK_ANSWER
        answer = [e for e in trace if e.target == "answer"]
        assert len(answer) == 1 and answer[0].decision == "replaced" and why in answer[0].reason
        _no_pii(scene)


def test_a_personal_time_is_not_shown_on_a_timeline():
    """A connector may say a time is personal. A Timeline cannot show it without the task
    needing contact details: its time is stripped like any other pii field, and a timeline
    without its time is dropped, in the trace."""
    registry = Registry()
    registry.register(ToolDescriptors(
        tool="visits_log", label="Visits", records="visits", record_id="visit_id",
        fields=(
            FieldDescriptor("visit_id", Kind.LINK, "Visit id"),
            FieldDescriptor("seen_at", Kind.DATETIME, "Seen at", pii=True),
            FieldDescriptor("page", Kind.TEXT, "Page"),
        ),
    ))
    result = {"visits": [{"visit_id": f"v{n}", "seen_at": f"2026-09-2{n}T10:1{n}:00Z", "page": "Returns"} for n in range(3)]}
    visits = registry.to_evidence("visits_log", result, handle="ev-visits", observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "People are reading the returns page.", "justification": "The owner asked what visitors look at."},
        "elements": [
            {"type": "finding", "significance": "CONTEXT", "text": "Visitors keep returning to the returns page.", "evidence": ["ev-visits"],
             "justification": "Interest in returns can mean a problem."},
            {"type": "timeline", "evidence": "ev-visits", "at": "seen_at", "label": "page", "limit": 3, "justification": "When they looked."},
        ],
    }

    scene, trace = validate_scene(plan, [visits], SceneContext(session_id=SESSION))
    assert [s.element.type for s in scene.elements] == ["finding"]
    final = _final(trace)
    assert final["elements[1] timeline"].decision == "dropped" and "its time may not be shown" in final["elements[1] timeline"].reason
    assert _reductions(trace, "elements[1] timeline") == ["seen_at: pii stripped; the task does not need contact details"]
    assert not any(b.pii for b in scene.bound())
    assert "2026-09-2" not in json.dumps(scene.as_dict()).replace(NOW.isoformat(), "")

    scene, trace = validate_scene(plan, [visits], SceneContext(session_id=SESSION, contact_details=True))
    assert [s.element.type for s in scene.elements] == ["finding", "timeline"]
    assert len(scene.elements[1].rows) == 3 and all(row[0].field == "seen_at" for row in scene.elements[1].rows)


def test_a_justification_is_plain_words_with_nothing_in_it_to_show():
    """A justification is kept beside its element and in the trace, so it meets the rule the
    prose does: no markup, no unbound value, no contact detail. The Answer is always kept, with
    its justification replaced when it cannot be shown."""
    mail = to_evidence("email_query", _email_query([_customer_row(n, waiting=n < 2) for n in range(6)]), handle="ev-mail",
                       observed_at=NOW, session_id=SESSION)
    waiting = [{"evidence": "ev-mail", "field": "needs_reply"}]

    def finding(justification: str) -> dict:
        return {"type": "finding", "significance": "ACTION_REQUIRED", "text": "{0} customers are waiting.", "values": waiting,
                "evidence": ["ev-mail"], "justification": justification}

    plan = {
        "answer": {"text": "{0} customers are waiting on a reply.", "values": waiting,
                   "justification": "<i>Asked</i> by jo@example.com"},
        "elements": [
            finding("<b>Urgent</b>: they need a reply."),
            finding("Write to jo@example.com first."),
            finding("Forty of them are cross."),
            finding("See {0}."),
            {"type": "measure", "value": {"evidence": "ev-mail", "field": "needs_reply"}, "justification": "[Waiting](https://evil.example)"},
            {"type": "proposal", "action": "act-1", "justification": "Phone them on 07700 900123."},
            finding("They need a reply today."),
        ],
    }
    scene, trace = validate_scene(plan, [mail], SceneContext(session_id=SESSION, actions=frozenset({"act-1"})))

    assert scene.answer.text() == "2 customers are waiting on a reply."
    assert scene.answer.element.justification == "The answer to what was asked."
    answer = [(e.decision, e.reason) for e in trace if e.target == "answer"]
    assert [d for d, _ in answer] == ["reduced", "kept"] and "justification" in answer[0][1]
    assert [s.element.justification for s in scene.elements] == ["They need a reply today."]
    final = _final(trace)
    for target in ("elements[0] finding", "elements[1] finding", "elements[2] finding", "elements[3] finding",
                   "elements[4] measure", "elements[5] proposal"):
        assert final[target].decision == "dropped" and "justification" in final[target].reason, target
    assert final["elements[6] finding"].decision == "kept"

    serialised = json.dumps(scene.as_dict()) + json.dumps([(e.target, e.reason) for e in trace])
    for literal in ("<i>", "<b>", "Urgent", "jo@", "example.com", "evil", "Forty", "07700", "900123", "See "):
        assert literal not in serialised, literal
    _no_pii(scene)


# ------------------------------------------------------- a connector by descriptors alone


ADS = ToolDescriptors(
    tool="ads_campaign_report", label="Ad campaigns", records="campaigns", record_id="campaign_id",
    fields=(
        FieldDescriptor("campaign_id", Kind.LINK, "Campaign id"),
        FieldDescriptor("name", Kind.TEXT, "Campaign"),
        FieldDescriptor("spend", Kind.MONEY, "Spend"),
        FieldDescriptor("roas", Kind.RATIO, "Return on ad spend", unit="x"),
    ),
    facts=(
        FieldDescriptor("spend", Kind.MONEY, "Spend", path="totals.spend"),
        FieldDescriptor("roas", Kind.RATIO, "Return on ad spend", unit="x", path="totals.roas"),
        FieldDescriptor("daily_spend", Kind.SERIES, "Daily spend", currency="GBP", points=("day", "spend"), path="totals.daily"),
    ),
)


def test_a_connector_registered_only_through_descriptors_yields_a_valid_scene():
    registry = Registry()
    registry.register(ADS)
    daily = [90, 110, 150, 130, 120, 115, 125.5]
    result = {
        "campaigns": [
            {"campaign_id": "c1", "name": "Autumn denim", "spend": {"amount": "512.40", "currency": "GBP"}, "roas": 1.4},
            {"campaign_id": "c2", "name": "Hoodies", "spend": {"amount": "328.10", "currency": "GBP"}, "roas": 4.2},
        ],
        "totals": {"spend": "840.50 GBP", "roas": 2.5,
                   "daily": [{"day": f"2026-09-{d}", "spend": s} for d, s in zip(range(18, 25), daily, strict=True)]},
    }
    ads = registry.to_evidence("ads_campaign_report", result, handle="ads-1", args={"period": "last_7_days"}, observed_at=NOW, session_id=SESSION)
    assert ads.facts["spend"] == Money(Decimal("840.50"), "GBP")
    assert ads.facts["roas"] == 2.5
    assert isinstance(ads.facts["daily_spend"], Series) and len(ads.facts["daily_spend"].points) == 7
    assert ads.facts["daily_spend"].currency == "GBP"
    assert ads.record("c1").values["spend"] == Money(Decimal("512.40"), "GBP")

    plan = {
        "answer": {"text": "Ads cost {0} this week at a return on spend of {1}.",
                   "values": [{"evidence": "ads-1", "field": "spend"}, {"evidence": "ads-1", "field": "roas"}],
                   "justification": "The owner asked how the ads did."},
        "elements": [
            {"type": "finding", "significance": "RISK", "text": "{0} returned only {1} on its spend.",
             "values": [{"evidence": "ads-1", "field": "name", "record": "c1"}, {"evidence": "ads-1", "field": "roas", "record": "c1"}],
             "evidence": ["ads-1"], "justification": "The weakest campaign is barely paying for itself."},
            {"type": "trend", "series": {"evidence": "ads-1", "field": "daily_spend"}, "justification": "Where the week's spend went."},
        ],
    }
    scene, trace = validate_scene(plan, [ads], SceneContext.for_request("how did the ads do this week", session_id=SESSION))

    assert [s.element.type for s in scene.elements] == ["finding", "trend"]
    assert [b.kind for b in scene.answer.values] == [Kind.MONEY, Kind.RATIO]
    assert scene.answer.text() == "Ads cost 840.50 GBP this week at a return on spend of 2.5 x."
    assert scene.elements[0].text() == "Autumn denim returned only 1.4 x on its spend."
    assert scene.elements[1].values[0].kind is Kind.SERIES
    assert all(e.decision == "kept" for e in _final(trace).values())
    assert DEFAULT.get("ads_campaign_report") is None   # registered in its own registry, nowhere else


def test_no_connector_specific_code_in_app_scenes():
    """The ads connector above lives only in this test. And only descriptors.py knows the name of
    any connector at all: the model, the schema and the validator decide from kinds."""
    for path in SCENES.glob("*.py"):
        words = set(re.findall(r"[a-z]+", path.read_text().lower()))
        assert not words & {"ads", "roas", "campaign", "campaigns"}, path.name
        if path.name != "descriptors.py":
            assert not words & {"shopify", "gmail", "commerce", "inventory"}, path.name


# ------------------------------------------------------------ the existing read tools


def _read_tools(path: Path) -> list[str]:
    """Every tool the module registers that is not a write or a batch, read from its source."""
    names = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) == "tool":
                keywords = {k.arg: k.value for k in decorator.keywords}
                if "write" not in keywords and "batch" not in keywords:
                    names.append(keywords["name"].value)
    return names


def test_every_existing_read_tool_has_descriptors():
    tools = [name for module in ("shopify_tools.py", "gmail_tools.py", "analytics_tools.py") for name in _read_tools(TOOLS / module)]
    assert len(tools) >= 18
    assert "shopify_order_note_append" not in tools
    assert [t for t in tools if DEFAULT.get(t) is None] == []


def test_customer_contact_fields_are_pii():
    for tool in DEFAULT.tools():
        spec = DEFAULT.get(tool)
        for d in spec.fields + spec.facts:
            if d.kind in (Kind.TEXT, Kind.PERSON) and re.search(r"email|phone|address|postcode|zip", f"{d.name} {d.path or ''} {d.label}".lower()):
                assert d.pii, (tool, d.name)


def test_adapters_type_what_the_tools_return():
    order = to_evidence("shopify_find_order", {"query": "1901", "orders": [_order(1)]}, handle="o", args={"query": "jo@example.com"}, observed_at=NOW)
    record = order.records[0]
    assert record.id == "gid://shopify/Order/5001"
    assert record.values["total"] == Money(Decimal("47.00"), "GBP")
    assert record.values["placed_at"] == NOW - timedelta(hours=5)
    assert order.descriptor("customer_email").pii and not order.descriptor("customer_name").pii
    assert order.query == "Orders found by query"

    detail = to_evidence("shopify_order_detail", {
        **_order(2), "money": {"subtotal": "40.00 GBP", "shipping": "4.95 GBP", "refunded": None}, "items": [{}, {}],
        "shipping_address": {"name": "Jo Bloggs", "lines": ["1 High Street"], "city": "London", "zip": "E1 6AN", "country": "United Kingdom"},
        "customer": {"orders": 3, "spent": "212.00 GBP"}, "email": {"available": True, "threads": [{}]},
    }, handle="d", observed_at=NOW)
    values = detail.records[0].values
    assert values["subtotal"] == Money(Decimal("40.00"), "GBP") and values["refunded"] is None
    assert values["items"] == 2 and values["customer_orders"] == 3 and values["email_threads"] == 1
    assert "E1 6AN" in values["shipping_address"] and detail.descriptor("shipping_address").pii

    address = to_evidence("shopify_order_address", {"order_id": "o1", "order_number": "CROOKS-1", "written": "1 High Street, London",
                                                    "phone": "07700 900123", "shipping_address": {"zip": "E1 6AN", "country": "United Kingdom"}},
                          handle="a", observed_at=NOW)
    assert all(address.descriptor(n).pii for n in ("address", "phone", "postcode", "city", "recipient"))

    sales = to_evidence("shopify_sales_summary", {
        "orders": 5, "revenue": 250.5, "currency": "GBP", "complete": True,
        "by_day": [{"date": "2026-09-22", "orders": 2, "revenue": 100.0}, {"date": "2026-09-23", "orders": 3, "revenue": 150.5}],
    }, handle="s", observed_at=NOW)
    assert sales.facts["revenue"] == Money(Decimal("250.5"), "GBP")
    assert [p.value for p in sales.facts["revenue_by_day"].points] == [100.0, 150.5]
    assert sales.facts["revenue_by_day"].currency == "GBP"
    assert [r.id for r in sales.records] == ["2026-09-22", "2026-09-23"]

    by_day = to_evidence("commerce_aggregate", {
        "entity": "orders", "group_by": ["day"], "currency": "GBP", "totals": {"revenue": 30.0},
        "rows": [{"key": {"day": "2026-09-23"}, "label": "2026-09-23", "revenue": 20.0}, {"key": {"day": "2026-09-22"}, "label": "2026-09-22", "revenue": 10.0}],
    }, handle="c", observed_at=NOW)
    assert [(p.at, p.value) for p in by_day.facts["revenue_trend"].points] == [("2026-09-22", 10.0), ("2026-09-23", 20.0)]

    thread = to_evidence("gmail_read_thread", {"thread_id": "t1", "message_count": 1, "awaiting_reply": True, "messages": [
        {"message_id": "m1", "from": "Jo", "from_email": "jo@example.com", "date": "Wed, 24 Sep 2026 09:15:00 +0100", "body": "Hi", "outbound": False},
    ]}, handle="t", observed_at=NOW)
    assert thread.records[0].values["date"] == datetime(2026, 9, 24, 8, 15, tzinfo=UTC)
    assert thread.records[0].values["outbound"] == "no" and thread.facts["awaiting_reply"] == "yes"

    stock = to_evidence("shopify_inventory", {"products": [{"title": "Yard Jeans", "variants": [
        {"variant_id": "v1", "variant": "32 / Black", "available": 4, "tracked": True}, {"variant_id": "v2", "variant": "34 / Black", "available": None, "tracked": False},
    ]}]}, handle="i", observed_at=NOW)
    assert [(r.values["product"], r.values["available"]) for r in stock.records] == [("Yard Jeans", 4), ("Yard Jeans", None)]


def test_evidence_refuses_what_it_does_not_describe():
    with pytest.raises(KeyError):
        to_evidence("no_such_tool", {}, handle="x", observed_at=NOW)
    with pytest.raises(ValueError):
        FieldDescriptor("Spend", Kind.MONEY, "Spend")
    with pytest.raises(ValueError):
        FieldDescriptor("spend", Kind.TEXT, "Spend", currency="GBP")
    with pytest.raises(ValueError):
        Money(Decimal("1.00"), "pounds")
    registry = Registry()
    registry.register(ADS)
    with pytest.raises(ValueError):
        registry.register(ADS)
