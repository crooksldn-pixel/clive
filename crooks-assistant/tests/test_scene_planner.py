"""app/scenes/planner.py: a scene plan for every turn, by rules (Generative UI V1, 3a of 4).

The turn's answer is the Answer; a Collection appears only when the question asks to see a
list; a Finding only where a read carries a reason for attention; everything else is reached
through the drill-down. Everything here is synthetic and offline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.providers.base import ToolCall
from app.scenes import SceneContext, plan_scene, scene_for_turn, turn_evidence, validate_scene
from app.scenes.scene import Answer, Collection, Finding, ScenePlan
from app.scenes.validate import FALLBACK_ANSWER, LIST_ROWS

NOW = datetime(2026, 9, 24, 17, 0, tzinfo=UTC)
SESSION = "sess-0924"
REPLY_QUESTION = "any customers who need a reply"
REPLY_ANSWER = "No customer is waiting on a reply from us."


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
        "checked": True, "latest_inbound_at": 1_790_000_000_000 + 60_000 * n if emailed else None,
        "latest_outbound_at": (1_790_000_900_000 + n) if emailed and not waiting else None,
        "latest_direction": ("inbound" if waiting else "outbound") if emailed else "none",
        "needs_reply": waiting, "confidence": "confident" if emailed else "none",
    }


def _email_query(rows: list[dict]) -> dict:
    counts = {
        "contacted": sum(1 for r in rows if r["emailed"]), "not_contacted": sum(1 for r in rows if not r["emailed"]),
        "replied": sum(1 for r in rows if r["replied"]), "needs_reply": sum(1 for r in rows if r["needs_reply"]), "unchecked": 0,
    }
    return {"set_id": "ws1", "set_label": "customers, last 30 days", "kind": "customers", "days": 30, "customers": len(rows),
            "counts": counts, "rows": rows, "source": "Gmail threads from each customer", "note": ""}


def _orders_call(n: int) -> ToolCall:
    return ToolCall(
        name="shopify_list_orders", args={"days": 7, "limit": 50},
        result={"since": "2026-09-17T23:00:00Z", "until": "2026-09-24T23:00:00Z", "days": 7, "count": n, "truncated": False,
                "orders": [_order(i) for i in range(n)]},
    )


def _september_calls() -> list[ToolCall]:
    """The 2026-09-24 turn's reads: forty rows across orders, threads and customers, and in all
    of them nobody waiting on a reply."""
    return [
        _orders_call(8),
        ToolCall(name="gmail_search", args={"days": 7},
                 result={"query": "newer_than:7d category:primary", "count": 7, "threads": [_thread(n) for n in range(7)], "note": ""}),
        ToolCall(name="email_query", args={"set_id": "ws1", "days": 30}, result=_email_query([_customer_row(n) for n in range(25)])),
    ]


def _context(question: str) -> SceneContext:
    return SceneContext.for_request(question, session_id=SESSION)


def _no_pii(dumped: str) -> None:
    assert "@" not in dumped and "example.com" not in dumped


# ------------------------------------------------------------------ the cases


def test_the_2026_09_24_turn_is_one_answer_and_a_drill_down():
    """'any customers who need a reply', answered truly, over forty rows of orders, threads and
    customers in which nobody is waiting: the plan is the answer alone, and the scene is that
    answer and a reference to what it checked — no list, no ranking, no email address."""
    calls = _september_calls()
    context = _context(REPLY_QUESTION)
    assert context.list_requested is False

    plan = plan_scene(REPLY_QUESTION, REPLY_ANSWER, calls, context)
    assert plan.answer.text == REPLY_ANSWER
    assert plan.elements == []

    evidence = turn_evidence(calls, session_id=SESSION, observed_at=NOW)
    assert [ev.handle for ev in evidence] == ["ev1", "ev2", "ev3"]
    assert sum(len(ev.records) for ev in evidence) == 40
    scene, trace = validate_scene(plan, evidence, context)
    assert scene.elements == () and scene.answer.text() == REPLY_ANSWER
    assert not any(b.pii for b in scene.bound())
    assert [(e.target, e.decision) for e in trace] == [("answer", "kept"), ("drilldown", "kept")]

    out = scene_for_turn(REPLY_QUESTION, REPLY_ANSWER, calls, session_id=SESSION, observed_at=NOW)
    assert out["answer"]["text"] == REPLY_ANSWER
    assert out["elements"] == []
    assert [s["evidence"] for s in out["drilldown"]["sources"]] == ["ev1", "ev2", "ev3"]
    assert sum(s["found"] for s in out["drilldown"]["sources"]) == 40
    assert [(e["target"], e["decision"]) for e in out["trace"]] == [("answer", "kept"), ("drilldown", "kept")]
    dumped = json.dumps(out)
    _no_pii(dumped)
    assert "Customer 1" not in dumped and "CROOKS-19" not in dumped, "no row of what was checked is on the screen"


def test_a_question_asking_for_a_list_keeps_a_bounded_collection():
    calls = [_orders_call(30)]
    question, answer = "list this week's orders", "Here are the orders from this week."

    plan = plan_scene(question, answer, calls, _context(question))
    (listed,) = plan.elements
    assert isinstance(listed, Collection) and listed.evidence == "ev1"
    assert listed.limit == LIST_ROWS
    assert not {"order_id", "customer_id", "customer_email"} & set(listed.columns), "no id and nothing personal"

    out = scene_for_turn(question, answer, calls, session_id=SESSION, observed_at=NOW)
    (element,) = out["elements"]
    assert element["type"] == "collection"
    assert len(element["rows"]) == LIST_ROWS and element["total"] == 30
    assert [c["field"] for c in element["columns"]] == listed.columns
    assert out["drilldown"] is None
    _no_pii(json.dumps(out))

    # The same reads, not asked for as a list: the answer, and the drill-down.
    plan = plan_scene("how are this week's orders", answer, calls, _context("how are this week's orders"))
    assert plan.elements == []


def test_findings_only_where_a_read_carries_an_attention_reason():
    calls = [
        _orders_call(3),
        ToolCall(name="email_query", args={"set_id": "ws1", "days": 30},
                 result=_email_query([_customer_row(n, waiting=n < 2) for n in range(6)])),
        ToolCall(name="gmail_read_thread", args={"thread_id": "t1"}, result={
            "thread_id": "t1", "message_count": 2, "messages_shown": 2, "truncated": False, "latest_direction": "inbound",
            "awaiting_reply": True, "messages": [
                {"message_id": "m1", "from": "Jo", "from_email": "jo@example.com", "date": "Wed, 24 Sep 2026 09:10:00 +0100",
                 "subject": "Sizing", "body": "Hello", "outbound": False},
            ],
        }),
        ToolCall(name="shopify_order_detail", args={"order_id": "gid://shopify/Order/1930"}, result={
            **_order(30), "attention": [{"kind": "refund", "level": "red", "title": "Cancelled but not refunded"}],
        }),
        # An attention line that is context, not attention: no finding.
        ToolCall(name="shopify_order_detail", args={"order_id": "gid://shopify/Order/1931"}, result={
            **_order(31), "attention": [{"kind": "customer", "level": "green", "title": "Regular customer"}],
        }),
    ]
    question, answer = "anything need me today", "Some customers are waiting on a reply."
    plan = plan_scene(question, answer, calls, _context(question))
    assert all(isinstance(e, Finding) for e in plan.elements)
    assert [(e.significance, e.text, e.evidence) for e in plan.elements] == [
        ("ACTION_REQUIRED", "Waiting on a reply from us: {0}.", ["ev2"]),
        ("ACTION_REQUIRED", "Someone is waiting on a reply from us.", ["ev3"]),
        ("ACTION_REQUIRED", "Something here needs your attention now.", ["ev4"]),
    ]

    out = scene_for_turn(question, answer, calls, session_id=SESSION, observed_at=NOW)
    assert out["answer"]["text"] == answer
    assert [e["text"] for e in out["elements"]] == [
        "Waiting on a reply from us: 2.", "Someone is waiting on a reply from us.", "Something here needs your attention now.",
    ]
    assert all(e["type"] == "finding" for e in out["elements"])
    assert out["drilldown"] is None
    _no_pii(json.dumps(out))

    # An amber line is a risk, not an action.
    amber = [ToolCall(name="shopify_order_detail", args={"order_id": "gid://shopify/Order/1932"}, result={
        **_order(32), "attention": [{"kind": "payment", "level": "amber", "title": "Not paid yet"}]})]
    (finding,) = plan_scene(question, "An order is not paid yet.", amber, _context(question)).elements
    assert (finding.significance, finding.text) == ("RISK", "Something here may need your attention.")


def test_the_plan_is_deterministic():
    calls = _september_calls() + [_orders_call(12)]
    for question in (REPLY_QUESTION, "list the orders"):
        context = _context(question)
        plans = [plan_scene(question, REPLY_ANSWER, calls, context).model_dump() for _ in range(3)]
        assert plans[0] == plans[1] == plans[2]
        scenes = [json.dumps(scene_for_turn(question, REPLY_ANSWER, calls, session_id=SESSION, observed_at=NOW)) for _ in range(3)]
        assert scenes[0] == scenes[1] == scenes[2]


def test_only_the_turns_own_reads_become_evidence():
    calls = [
        ToolCall(name="shopify_list_orders", args={"days": 7}, ok=False, error="timed out"),
        _orders_call(2),
        ToolCall(name="shopify_add_note", args={"order_id": "gid://shopify/Order/1", "note": "x"}, proposal_id="p1", result={}),
        ToolCall(name="no_such_read", args={}, result={"rows": [{"a": 1}]}),
        ToolCall(name="gmail_search", args={"days": 1}, result=None),
    ]
    evidence = turn_evidence(calls, session_id=SESSION, observed_at=NOW)
    assert [(ev.handle, ev.tool, ev.session_id) for ev in evidence] == [("ev2", "shopify_list_orders", SESSION)]
    plan = plan_scene("list the orders", "Here are the orders.", calls, _context("list the orders"))
    assert [e.evidence for e in plan.elements] == ["ev2"]


def test_an_answer_the_schema_cannot_hold_is_still_one_answer():
    long = ("The orders are all out. " * 20) + "\n\nNothing else needs you."
    plan = plan_scene("anything need me", long, [], _context("anything need me"))
    assert len(plan.answer.text) <= 280 and "\n" not in plan.answer.text
    assert plan.answer.text.endswith("out.")
    assert plan_scene("anything need me", "  ", [], _context("anything need me")).answer.text == FALLBACK_ANSWER
    unbroken = "x" * 400
    assert len(plan_scene("anything", unbroken, [], _context("anything")).answer.text) == 280


def test_the_planner_can_be_swapped_and_is_still_validated():
    """A model planner takes the same four arguments and returns a ScenePlan; the validator
    decides what it may show, whoever planned it."""
    seen = []

    def model_planner(question, answer, calls, context):
        seen.append((question, answer, len(calls), context.session_id, context.list_requested))
        return ScenePlan(answer=Answer(text=answer, justification="The answer to what was asked."), elements=[
            Finding(significance="CONTEXT", text="Everyone has been answered.", evidence=["ev3"], justification="Who was checked."),
            Finding(significance="CONTEXT", text="Nothing here.", evidence=["ev9"], justification="A read that was not made."),
        ])

    out = scene_for_turn(REPLY_QUESTION, REPLY_ANSWER, _september_calls(), session_id=SESSION, planner=model_planner, observed_at=NOW)
    assert seen == [(REPLY_QUESTION, REPLY_ANSWER, 3, SESSION, False)]
    assert [e["text"] for e in out["elements"]] == ["Everyone has been answered."]
    dropped = [e for e in out["trace"] if e["decision"] == "dropped"]
    assert [e["target"] for e in dropped] == ["elements[1] finding"] and "not evidence from this session" in dropped[0]["reason"]
