"""app/scenes: the evidence model, the scene-plan schema and the pure validator.

Nothing here touches app/presentation.py, app/render.py or a route: app/scenes is not wired to
anything yet. These tests build evidence and plans directly, the way a later objective's planner
will, and check what app/scenes/validate.py does with them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.scenes import descriptors
from app.scenes.evidence import (
    Evidence,
    FieldDescriptor,
    FieldKind,
    evidence_map,
    money,
    series_point,
)
from app.scenes.scene import (
    Answer,
    Collection,
    Entity,
    EvidenceRef,
    Finding,
    Measure,
    MeasureRef,
    Proposal,
    Question,
    ScenePlan,
    Significance,
    Trend,
)
from app.scenes.validate import ValidationContext, validate_scene

OBSERVED_AT = "2026-09-24T09:00:00+00:00"


# --------------------------------------------------------------------------- the 2026-09-24 case


def test_september_24_case_validates_to_one_answer_plus_drilldown_with_no_pii():
    order_rows = [
        {
            "order_id": f"gid://shopify/Order/{7000 + i}",
            "order_number": f"CROOKS-{7000 + i}",
            "placed_at": f"2026-09-{10 + (i % 10):02d}T10:00:00+01:00",
            "age_days": float(i + 1),
            "fulfillment": "FULFILLED",
            "payment": "PAID",
            "total": 45.0 + i,
            "currency": "GBP",
            "customer_name": f"Customer {i}",
            "customer_email": f"customer{i}@example.com",
            "country_code": "GB",
            "items": 1,
            "tags": [],
            "has_tracking": True,
            "cancelled": False,
        }
        for i in range(15)
    ]
    thread_rows = [
        {
            "thread_id": f"thread-{i}",
            "message_id": f"msg-{i}",
            "from": f"Customer {i}",
            "from_email": f"customer{i}@example.com",
            "subject": "Delivery update",
            "date": "Thu, 24 Sep 2026 08:00:00 +0100",
            "snippet": "Thanks for letting me know.",
            "likely_bulk": False,
            "authenticated": True,
        }
        for i in range(15)
    ]
    customer_rows = [
        {
            "customer_id": f"gid://shopify/Customer/{i}",
            "customer_name": f"Customer {i}",
            "customer_email": f"customer{i}@example.com",
            "orders": [f"CROOKS-{7000 + i}"],
            "emailed": True,
            "threads": 1,
            "replied": True,
            "last_subject": "Delivery update",
            "last_date": "Thu, 24 Sep 2026 08:00:00 +0100",
            "checked": True,
            "thread_count": 1,
            "latest_direction": "outbound",
            "has_reply_after_latest_inbound": True,
            "needs_reply": False,
            "related_orders": [f"{7000 + i}"],
            "confidence": "confident",
        }
        for i in range(10)
    ]

    orders_evidence = descriptors.from_commerce_query(
        {"entity": "orders", "rows": order_rows}, handle="orders_today", observed_at=OBSERVED_AT
    )
    threads_evidence = descriptors.from_gmail_search(
        {"query": "inbox, last 1 day", "threads": thread_rows}, handle="inbox_recent", observed_at=OBSERVED_AT
    )
    customers_evidence = descriptors.from_email_query(
        {"set_label": "customers this week", "days": 30, "rows": customer_rows},
        handle="customers_checked", observed_at=OBSERVED_AT,
    )
    evidence = [orders_evidence, threads_evidence, customers_evidence]

    # About forty rows across orders, threads and customers, as the objective describes.
    assert sum(len(e.records) for e in evidence) == 40

    plan = ScenePlan(
        answer=Answer(
            lines=["Nobody is waiting on a reply."],
            evidence=[EvidenceRef(handle="customers_checked", field="needs_reply")],
            justification="checked needs_reply for every customer in the working set",
        ),
        elements=[],
    )
    context = ValidationContext(session_evidence_handles=frozenset(e.handle for e in evidence))

    scene, trace = validate_scene(plan, evidence, context)

    assert scene.answer.lines == ["Nobody is waiting on a reply."]
    assert scene.elements == []
    assert scene.drilldown == [EvidenceRef(handle="customers_checked", field="needs_reply")]
    assert any(t.element == "drilldown" and t.kept for t in trace)

    ev_map = evidence_map(evidence)
    for ref in scene.answer.evidence:
        descriptor = ev_map[ref.handle].field(ref.field)
        assert descriptor is not None
        assert descriptor.pii is False
    # No email address anywhere the accepted scene points at.
    assert not any(ev_map[ref.handle].field(ref.field).pii for ref in scene.drilldown)


# ----------------------------------------------------------------------- nothing needs you today


def test_nothing_needs_you_case_is_one_line():
    sales_evidence = descriptors.from_shopify_sales_summary(
        {"since": "2026-09-24", "until": "2026-09-25", "orders": 0, "revenue": 0.0, "currency": "GBP", "complete": True},
        handle="sales_today", observed_at=OBSERVED_AT,
    )
    plan = ScenePlan(
        answer=Answer(
            lines=["Nothing needs you today."],
            evidence=[EvidenceRef(handle="sales_today", field="orders")],
            justification="checked today's orders and nothing is outstanding",
        ),
        elements=[],
    )
    context = ValidationContext(session_evidence_handles=frozenset({"sales_today"}))

    scene, _ = validate_scene(plan, [sales_evidence], context)

    assert len(scene.answer.lines) == 1
    assert scene.elements == []


# ------------------------------------------------------------------------------ the adversarial plan


def test_adversarial_plan_is_reduced_with_every_reduction_in_the_trace():
    customers_evidence = descriptors.from_shopify_find_customer(
        {
            "query": "big spenders",
            "customers": [
                {"name": "Alex Kim", "email": "alex@example.com", "orders": 5, "spent": "500.00 GBP"},
                {"name": "Jo Ellis", "email": "jo@example.com", "orders": 3, "spent": "220.00 GBP"},
            ],
        },
        handle="customers", observed_at=OBSERVED_AT,
    )
    evidence = [customers_evidence]
    context = ValidationContext(session_evidence_handles=frozenset({"customers"}))

    plan = ScenePlan(
        answer=Answer(
            lines=["Two customers spent over £200 this month."],
            evidence=[EvidenceRef(handle="customers", field="spent")],
            justification="checked lifetime spend for the matched customers",
        ),
        elements=[
            # An invented number: evidence from outside this session.
            Finding(
                significance=Significance.RISK,
                text="A much bigger spender was found.",
                evidence=[EvidenceRef(handle="ev_invented", field="orders")],
                justification="testing an unbound reference",
            ),
            # Markup in the text.
            Finding(
                significance=Significance.CONTEXT,
                text="<b>Top spender</b> this month is Alex Kim.",
                evidence=[EvidenceRef(handle="customers", field="spent")],
                justification="testing markup in the text",
            ),
            # No justification.
            Question(
                text="Should we follow up with everyone?",
                evidence=[],
                justification="",
            ),
            # An over-budget collection with a pii column.
            Collection(
                handle="customers",
                columns=["customer_name", "customer_email", "orders"],
                limit=50,
                justification="show the customers found",
            ),
            Measure(
                ref=MeasureRef(evidence=EvidenceRef(handle="customers", field="spent"), period="this_month"),
                justification="the total spend measure",
            ),
            # A pii field on an entity.
            Entity(
                handle="customers",
                record=0,
                fields=["customer_name", "customer_email"],
                justification="show the top customer",
            ),
            # A fourth otherwise-valid element: over the attention budget of three.
            Proposal(
                action_ref="draft_reply_to_customer",
                justification="propose a follow-up",
            ),
        ],
    )

    scene, trace = validate_scene(plan, evidence, context)
    by_element = {t.element: t for t in trace}

    # The invented reference: dropped, and recorded twice — the reference and the element.
    assert by_element["finding:0.evidence:ev_invented.orders"].kept is False
    assert "not bound to evidence from this session" in by_element["finding:0.evidence:ev_invented.orders"].reason
    assert by_element["finding:0"].kept is False

    # The markup.
    assert by_element["finding:1"].kept is False
    assert "markup" in by_element["finding:1"].reason

    # The unjustified element.
    assert by_element["question:2"].kept is False
    assert "justification" in by_element["question:2"].reason

    # The pii column and the over-budget row limit, both reduced rather than dropped whole.
    assert by_element["collection:3.column:customer_email"].kept is False
    assert "pii" in by_element["collection:3.column:customer_email"].reason
    assert by_element["collection:3.limit"].kept is False
    assert "8" in by_element["collection:3.limit"].reason
    assert by_element["collection:3"].kept is True

    # The measure, unaffected.
    assert by_element["measure:4"].kept is True

    # The pii field on the entity.
    assert by_element["entity:5.field:customer_email"].kept is False
    assert "pii" in by_element["entity:5.field:customer_email"].reason
    assert by_element["entity:5"].kept is True

    # The fourth valid element: over the attention budget.
    assert by_element["proposal:6"].kept is False
    assert "attention budget" in by_element["proposal:6"].reason

    assert [type(e).__name__ for e in scene.elements] == ["Collection", "Measure", "Entity"]
    kept_collection = scene.elements[0]
    assert kept_collection.columns == ["customer_name", "orders"]
    assert kept_collection.limit == 8
    kept_entity = scene.elements[2]
    assert kept_entity.fields == ["customer_name"]


# --------------------------------------------------------------------- a connector app/scenes never saw


def test_synthetic_ads_connector_needs_no_code_in_app_scenes():
    """Registered only through app/scenes/evidence.py primitives — nothing added to
    app/scenes/descriptors.py for it, and nothing added anywhere else in this package."""
    ads_evidence = Evidence(
        handle="ads_week",
        source_tool="synthetic_ads_connector",
        observed_at=OBSERVED_AT,
        query_summary="Ad spend, last 7 days",
        fields=[
            FieldDescriptor(name="spend", kind=FieldKind.MONEY, label="Spend", currency="GBP"),
            FieldDescriptor(name="roas", kind=FieldKind.RATIO, label="ROAS"),
            FieldDescriptor(name="daily_spend", kind=FieldKind.SERIES, label="Daily spend"),
        ],
        records=[
            {
                "spend": money(250.0, "GBP"),
                "roas": 3.2,
                "daily_spend": [
                    series_point("2026-09-18", 30.0),
                    series_point("2026-09-19", 32.0),
                    series_point("2026-09-20", 40.0),
                    series_point("2026-09-21", 55.0),
                    series_point("2026-09-22", 45.0),
                    series_point("2026-09-23", 28.0),
                    series_point("2026-09-24", 20.0),
                ],
            }
        ],
    )
    context = ValidationContext(session_evidence_handles=frozenset({"ads_week"}))

    plan = ScenePlan(
        answer=Answer(
            lines=["Ad spend is up this week and still paying back."],
            evidence=[EvidenceRef(handle="ads_week", field="spend")],
            justification="checked spend and ROAS for the week",
        ),
        elements=[
            Finding(
                significance=Significance.CONTEXT,
                text="Return on spend held above target through the week.",
                evidence=[EvidenceRef(handle="ads_week", field="roas")],
                justification="ROAS is the figure that matters here",
            ),
            Trend(
                evidence=EvidenceRef(handle="ads_week", field="daily_spend"),
                label="Daily spend",
                justification="shows the shape of the week",
            ),
        ],
    )

    scene, trace = validate_scene(plan, [ads_evidence], context)

    assert len(scene.elements) == 2
    assert [type(e).__name__ for e in scene.elements] == ["Finding", "Trend"]
    assert all(t.kept for t in trace if t.element in ("answer", "finding:0", "trend:1"))


# ------------------------------------------------------------------------------------ the schema


def test_scene_elements_forbid_extra_fields():
    with pytest.raises(ValidationError):
        Answer(lines=["hello"], justification="x", made_up_field="nope")
