"""Follow-ups from the round-12 deploy review: the app page, the cards it draws, the objectives it shows.

The page's own code is run under Node (tests/web/followups-app-page.test.js, with the edges, the
Displays tray and the objective sheet's existing files beside it), skipped only where Node is
absent, as tests/test_web_js.py does. The render ledger (app/render.py, AC2-01 and AC2-02) and the
owner's create route (app/routes/objectives.py, S6-05) are held here. Every name, address and
order in this file is invented.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import progressive
from app.objectives import store as store_module
from app.render import ADDED, DATA, RenderLedger, fingerprint, render_id

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


@needs_node
@pytest.mark.parametrize("name", ["followups-app-page.test.js", "edges.test.js", "lift.test.js", "alpha-open.test.js"])
def test_the_page_under_node(name):
    """S4A-01, S4A-02, W1-02, W2-04, W3-05 and TW-01 with the page's own code; and the soft edges,
    the Displays tray and the objective sheet as they were proved before."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / name)],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


# --------------------------------------------------------------------------- AC2-01: the envelope's words count

GID = "gid://shopify/Order/90417"


def order(**envelope) -> dict:
    item = {"type": "order", "data": {"order_id": GID, "order_number": "#4417", "detail": True, "total": "£40.00"}}
    item.update({
        "title": "Order #4417", "subtitle": "Ada Brightwell",
        "linked_entities": [{"kind": "customer", "ref": "gid://shopify/Customer/7701", "label": "Ada Brightwell"}],
        "freshness": {"source": "shopify", "age_s": 2.0},
    })
    item.update(envelope)
    return item


@pytest.mark.parametrize("change", [
    {"title": "Order #4417 · refunded"},
    {"subtitle": "Ada Brightwell-Okafor"},
    {"linked_entities": [{"kind": "email_thread", "ref": "18f2a9c0b1d2e3f4", "label": "Where is my parcel?"}]},
    {"freshness": {"source": "shopify", "age_s": 2.0, "caveat": "Read before the refund"}},
])
def test_a_card_whose_envelope_changed_is_patched_not_suppressed(change):
    ledger = RenderLedger()
    assert [p.op for p in ledger.stage([order()])] == [ADDED]
    changed = order(**change)
    assert changed["data"] == order()["data"], "the data is the same"
    assert fingerprint(changed) != fingerprint(order())
    patches = ledger.stage([changed])
    assert [p.op for p in patches] == [DATA], f"{sorted(change)} changed and the patch was suppressed"
    assert patches[0].item is changed, "the patch carries the new item"
    assert patches[0].public()["item"][next(iter(change))] == change[next(iter(change))]
    # The same item staged again is still suppressed.
    assert ledger.stage([order(**change)]) == []
    assert ledger.counts["suppressed"] == 1


def test_the_same_envelope_and_data_twice_is_still_one_render():
    ledger = RenderLedger()
    ledger.stage([order()])
    for _ in range(3):
        assert ledger.stage([order()]) == []
    assert ledger.counts["drawn"] == 1 and ledger.counts["suppressed"] == 3
    # A change of how the card is drawn, alone, is still only visual.
    assert [p.op for p in ledger.stage([order(data={**order()["data"], "secondary": True})])] == ["visual"]


# --------------------------------------------------------------------------- AC2-02: one order, one card

BOTH = {"type": "order", "data": {"order_id": GID, "order_number": "#4417", "detail": True}}
NUMBER = {"type": "order", "data": {"order_number": "#4417", "detail": False}}
GID_ONLY = {"type": "order", "data": {"order_id": GID, "detail": False}}


def orders_on_glass(ledger: RenderLedger) -> list[str]:
    return [i for i in ledger.order if i.startswith("order:")]


@pytest.mark.parametrize(("first", "then"), [(BOTH, NUMBER), (NUMBER, BOTH), (GID_ONLY, BOTH), (BOTH, GID_ONLY)])
def test_one_order_under_either_key_is_one_card(first, then):
    ledger = RenderLedger()
    added = ledger.stage([first])
    assert [p.op for p in added] == [ADDED]
    patches = ledger.stage([then])
    assert len(patches) == 1
    assert patches[0].op == DATA, "a patch of the card already up, never a second added card"
    # It takes the first card's place: the glass replaces that node rather than adding one.
    assert patches[0].render_id == render_id(then)
    assert patches[0].replaces in ("", added[0].render_id)
    if patches[0].render_id != added[0].render_id:
        assert patches[0].replaces == added[0].render_id
    assert orders_on_glass(ledger) == [render_id(then)], "one order, one card"
    assert ledger.counts["drawn"] == 1
    # And back again: still one card.
    again = ledger.stage([first])
    assert [p.op for p in again] == [DATA]
    assert orders_on_glass(ledger) == [render_id(first)]


def test_number_only_then_both_then_number_only_never_adds_a_second_card():
    ledger = RenderLedger()
    ops = [p.op for item in (NUMBER, BOTH, NUMBER, BOTH) for p in ledger.stage([item])]
    assert ops == [ADDED, DATA, DATA, DATA]
    assert len(orders_on_glass(ledger)) == 1


def test_two_different_orders_are_still_two_cards():
    ledger = RenderLedger()
    other = {"type": "order", "data": {"order_id": "gid://shopify/Order/90418", "order_number": "#4418", "detail": True}}
    assert [p.op for p in ledger.stage([BOTH, other])] == [ADDED, ADDED]
    assert [p.op for p in ledger.stage([{"type": "order", "data": {"order_number": "#4418"}}])] == [DATA]
    assert len(orders_on_glass(ledger)) == 2
    # An order that shares neither key is a third card; one whose gid disagrees is never merged.
    assert [p.op for p in ledger.stage([{"type": "order", "data": {"order_number": "#4419"}}])] == [ADDED]
    clash = {"type": "order", "data": {"order_id": "gid://shopify/Order/90499", "order_number": "#4417"}}
    assert [p.op for p in ledger.stage([clash])] == [ADDED]
    assert len(orders_on_glass(ledger)) == 4


def test_a_turn_that_found_the_order_by_number_and_answered_with_it_whole_ends_with_one_card():
    """Through the workspace (app/progressive.py): the read's card and the answer's are one order,
    and the answer's own reconciliation keeps that card rather than taking it down."""
    progressive.reset()
    try:
        workspace = progressive.Workspace("s1", clock=lambda: 0.0)
        workspace.facts([NUMBER])
        done = workspace.complete([BOTH])
        assert [p.op for p in done if p.type == "order"] == [DATA]
        assert not [p for p in done if p.op == "remove" and p.type == "order"]
        assert orders_on_glass(workspace.ledger) == [render_id(BOTH)]
    finally:
        progressive.reset()


# --------------------------------------------------------------------------- S6-05: the create route

@pytest.fixture
def owner(tmp_path):
    from app.routes import objectives

    store = store_module.install(tmp_path / "objectives")
    app = FastAPI()
    app.include_router(objectives.router)
    # The owner's server, asked from the server itself (writes_local_owner), as tests/test_objectives.py has it.
    settings = SimpleNamespace(writes_local_owner=True, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=("owner@example.test",), settings=settings)
    return SimpleNamespace(client=TestClient(app), store=store)


def test_a_project_is_created_with_its_stages(owner):
    made = owner.client.post("/objectives", json={
        "request": "Get the winter drop made", "title": "Winter drop", "kind": "project",
        "stages": ["Sampling", "Approval", "Production", "Delivery"], "deadline": "2026-11-20",
    })
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["kind"] == "project"
    assert [s["name"] for s in body["stages"]] == ["Sampling", "Approval", "Production", "Delivery"]
    assert [o.id for o in owner.store.live()] == [body["id"]]


def test_a_tasks_objective_is_created_with_its_tasks(owner):
    made = owner.client.post("/objectives", json={
        "request": "Give Rosa and Kit these to do", "title": "Studio jobs", "kind": "tasks",
        "tasks": [{"who": "Rosa", "text": "Steam the samples", "due": "2026-10-08"}, {"who": "Kit", "text": "Photograph the tees"}],
    })
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["kind"] == "tasks"
    assert sorted((t["who"], t["text"], t["due"]) for t in body["tasks"]) == [
        ("Kit", "Photograph the tees", None), ("Rosa", "Steam the samples", "2026-10-08")]
    assert len(owner.store.live()) == 1


@pytest.mark.parametrize("body", [
    {"request": "Get the winter drop made", "kind": "project"},
    {"request": "Give Rosa these", "kind": "tasks"},
    {"request": "Get the winter drop made", "kind": "project", "stages": ["Sampling", "sampling"]},
    {"request": "Give Rosa these", "kind": "tasks", "tasks": [{"who": "", "text": "Steam the samples"}]},
    {"request": "Get the winter drop made", "kind": "business", "stages": ["Sampling"]},
])
def test_a_create_the_store_refuses_says_why_and_records_nothing(owner, body):
    refused = owner.client.post("/objectives", json=body)
    assert 400 <= refused.status_code < 500
    detail = refused.json()["detail"]
    assert isinstance(detail, str) and detail.strip(), "a plain reason, in words"
    assert owner.store.live() == []


def test_a_business_create_behaves_as_before(owner):
    for body in ({"request": "Organise the van for Saturday", "deadline": "2026-10-11"},
                 {"request": "Find a new label printer", "kind": "business", "title": "Label printer"}):
        made = owner.client.post("/objectives", json=body)
        assert made.status_code == 200, made.text
        got = made.json()
        assert got["kind"] == "business" and got["stages"] == [] and got["tasks"] == []
    titles = sorted(o.title for o in owner.store.live())
    assert titles == ["Label printer", "Organise the van for Saturday"]
    # A kind the store does not know is refused as it always was.
    assert owner.client.post("/objectives", json={"request": "x", "kind": "errand"}).status_code == 400
