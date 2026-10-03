"""The team's own CLIVE (3 October): Undo for a member's own steps, George's things noted for him in
their words, and the typed and spoken path held to exactly what a member of the team may do.

George, 2 October: the team needs "a way where any way they intend to act can be accepted as input:
a click, speech, typing". The page (web/today.js) takes the same steps a tap took; these hold what
the Mac lets those steps be:

  undo     a member may take back their own latest steps on a job (claimed, packed, counted, done,
           gave back) for a short while, named as the screen saw them made: never someone else's,
           never stale, never a change a card made, and the record keeps both the step and its undoing.
  flag     what only George may do is noted for him as a job of his, in their words, and nothing
           else: it cannot be handed to anyone else or reach the shop.
  words    a sentence typed or said reaches their own CLIVE (POST /turn) under their own authority,
           and every tool that is not theirs is refused before it runs: refunds, cancellations,
           discounts, order and price edits, new emails, people, objectives, the engineering loop.

Through the real app and its door, as tests/test_team.py does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.people import access, staff
from app.people.prompt import build_staff_prompt
from app.people.store import people
from app.providers.base import TurnResult
from app.tools import authority, registry
from app.tools.dispatch import dispatch
from app.work import hooks
from app.work import store as work_store
from app.work import tools as work_tools
from app.work.store import work
from tests.test_actions import ORDER
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    PROXIED,
    FakeProvider,
    client,
)
from tests.test_team import (  # noqa: F401 - `team` is a fixture
    AS_MIA,
    MIA,
    ORDER_REF,
    let_mia_in,
    team,
)

KIT = "kit@example.com"
AS_KIT = {"Tailscale-User-Login": KIT, "X-Forwarded-For": "100.64.0.8"}


def let_kit_in():
    people.note({"name": "Kit", "kind": "staff", "role": "packing", "login": KIT})
    access.ask("kit", KIT)
    access.approve("kit", login=KIT, by="owner", passkey="pk")


async def claim_pack_finish(team):  # noqa: F811
    claimed = await team.post("/today/claim", json={"ref": ORDER_REF}, headers=AS_MIA)
    item_id = claimed.json()["job"]["item_id"]
    assert claimed.json()["step"] == "claimed"
    packed = await team.post("/today/packed", json={"item_id": item_id}, headers=AS_MIA)
    done = await team.post("/today/done", json={"item_id": item_id}, headers=AS_MIA)
    assert (packed.json()["step"], done.json()["step"]) == ("packed", "done")
    return item_id


# ------------------------------------------------------------------ undo

async def test_a_member_undoes_their_own_tap_and_the_order_is_back_as_it_was(team):  # noqa: F811
    let_mia_in()
    item_id = await claim_pack_finish(team)
    assert work.get(item_id).status == "done"
    undone = await team.post("/today/undo", json={"item_id": item_id, "steps": ["done", "packed", "claimed"]},
                             headers=AS_MIA)
    assert undone.status_code == 200 and undone.json()["taken"] == ["done", "packed", "claimed"]
    item = work.get(item_id)
    assert (item.status, item.claimed_by, item.done_by) == ("open", "", "")
    assert "packed" not in item.evidence and item.events[-1]["what"] == "undone"
    board = (await team.get("/today/state", headers=AS_MIA)).json()["work"]
    assert [row["ref"] for row in board["found"]] == [ORDER_REF] and board["done"] == []     # back on the list
    record = [e["what"] for e in work.history(who="mia")[:3]]
    assert record == ["claimed_undone", "packed_undone", "done_undone"]                     # the record keeps both
    again = await team.post("/today/undo", json={"item_id": item_id, "steps": ["claimed"]}, headers=AS_MIA)
    assert again.status_code == 409                                                          # nothing left to undo


async def test_only_the_steps_the_screen_saw_and_only_your_own_can_be_undone(team):  # noqa: F811
    let_mia_in()
    let_kit_in()
    item_id = await claim_pack_finish(team)
    for body, headers in (({"item_id": item_id, "steps": ["done"]}, AS_KIT),                # Kit, Mia's step
                          ({"item_id": item_id, "steps": ["packed"]}, AS_MIA),             # not the latest
                          ({"item_id": item_id, "steps": ["done", "packed", "claimed", "created"]}, AS_MIA)):
        refused = await team.post("/today/undo", json=body, headers=headers)
        assert refused.status_code in (403, 409), body
    for garbled in ({"item_id": item_id, "steps": "done"}, {"item_id": item_id, "steps": [1]}):
        assert (await team.post("/today/undo", json=garbled, headers=AS_MIA)).status_code == 400
    assert work.get(item_id).status == "done"                                                # nothing changed


async def test_undo_runs_out_and_never_reopens_a_job_a_card_closed(team, monkeypatch):  # noqa: F811
    let_mia_in()
    item_id = await claim_pack_finish(team)
    later = datetime.now(UTC) + timedelta(seconds=work_store.UNDO_WINDOW_S + 5)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(work_store, "datetime", Later)
    stale = await team.post("/today/undo", json={"item_id": item_id, "steps": ["done"]}, headers=AS_MIA)
    assert stale.status_code == 409 and "too long ago" in stale.json()["detail"]
    monkeypatch.undo()
    item = work.get(item_id)
    item.evidence["proposal_id"] = "prop_fulfilled"                                          # a card's change closed it
    work._save(item)
    closed = await team.post("/today/undo", json={"item_id": item_id, "steps": ["done"]}, headers=AS_MIA)
    assert closed.status_code == 409 and "card" in closed.json()["detail"]
    assert work.get(item_id).status == "done"


async def test_undoing_a_count_puts_the_count_before_it_back(team):  # noqa: F811
    let_mia_in()
    handed = await team.post("/today/assign", json={"title": "Count the hoodies", "kind": "stock_count", "to": "mia"},
                             headers=PROXIED)
    item_id = handed.json()["job"]["item_id"]
    await team.post("/today/claim", json={"item_id": item_id}, headers=AS_MIA)
    await team.post("/today/counts", json={"item_id": item_id, "counts": [{"item": "Hoodie M", "counted": "12"}]},
                    headers=AS_MIA)
    await team.post("/today/counts", json={"item_id": item_id, "counts": [{"item": "Hoodie M", "counted": "21"}]},
                    headers=AS_MIA)
    undone = await team.post("/today/undo", json={"item_id": item_id, "steps": ["counted"]}, headers=AS_MIA)
    assert undone.status_code == 200 and work.get(item_id).evidence["counts"][0]["counted"] == 12
    # Undo takes back the latest steps only: the first count is not undone by asking twice.
    twice = await team.post("/today/undo", json={"item_id": item_id, "steps": ["counted"]}, headers=AS_MIA)
    assert twice.status_code == 409 and work.get(item_id).evidence["counts"][0]["counted"] == 12


async def test_a_step_clive_took_for_them_in_words_is_offered_back_on_their_screen(team):  # noqa: F811
    let_mia_in()
    work_tools.bind(team.runtime)
    with authority.acting_as(authority.for_staff("mia", MIA)):
        claimed = await work_tools.work_note(action="claim", ref=ORDER_REF)
        await work_tools.work_note(action="done", item_id=claimed["job"]["item_id"], note="in the post bag")
    state = (await team.get("/today/state", headers=AS_MIA)).json()
    last = state["last_steps"]
    assert last["item_id"] == claimed["job"]["item_id"] and last["steps"] == ["done", "claimed"]
    assert (await team.get("/today/state", headers=PROXIED)).json()["last_steps"] is None     # hers, not his
    undone = await team.post("/today/undo", json={"item_id": last["item_id"], "steps": last["steps"]}, headers=AS_MIA)
    assert undone.status_code == 200 and "note" not in work.get(last["item_id"]).evidence


# ------------------------------------------------------------------ George's, noted for him

async def test_what_only_george_may_do_is_noted_for_him_in_their_words_and_nothing_else(team):  # noqa: F811
    let_mia_in()
    flagged = await team.post("/today/flag", headers=AS_MIA, json={
        "title": "refund 1930 please, she wants her money back", "ref": ORDER_REF, "to": "kit", "kind": "stock_count"})
    assert flagged.status_code == 200
    job = flagged.json()["job"]
    assert (job["assignee"], job["created_by"], job["status"], job["kind"]) == ("owner", "mia", "open", "job")
    assert job["created_via"] == ""                                                          # her words, not CLIVE's
    his = (await team.get("/today/state", headers=PROXIED)).json()
    [waiting] = [j for j in his["work"]["mine"] if j["item_id"] == job["item_id"]]
    assert waiting["created_by_name"] == "Mia" and waiting["title"].startswith("refund 1930")
    assert his["record"][0]["what"] == "flagged" and his["record"][0]["who_name"] == "Mia"
    hers = (await team.get("/today/state", headers=AS_MIA)).json()["work"]
    every = [row for key in ("mine", "up_for_grabs", "found", "in_hand", "team") for row in hers[key]]
    assert job["item_id"] not in {row.get("item_id") for row in every}                       # his, not on her list
    assert team.store.mutations == []                                                        # the shop untouched
    for bad in ({"title": ""}, {"title": "x", "ref": "javascript:alert(1)"}):
        assert (await team.post("/today/flag", json=bad, headers=AS_MIA)).status_code == 409


# ------------------------------------------------------------------ the typed and spoken path

def _owners_tools() -> list[str]:
    """Every tool this server has that is not the team's: the refund, the cancellation, the
    discount, the order and price edits, a new email, people, objectives, screens, engineering."""
    return sorted(name for name in registry.names() if not staff.may_call(name))


async def test_a_sentence_typed_or_said_reaches_no_tool_that_is_not_theirs(team):  # noqa: F811
    """The page sends what was typed, or what the phone heard, to POST /turn as text. Whatever the
    assistant then reaches for, under the member's authority every owner-only tool is refused before
    it runs, nothing is staged and the shop is never asked; the one thing it may do is note it for
    George."""
    let_mia_in()
    owners = _owners_tools()
    for expected in ("shopify_refund_create", "shopify_order_cancel", "shopify_discount_create", "shopify_store_credit_add", "gmail_send_new",
                     "shopify_order_shipping_address_set", "person_note", "objective_note"):
        assert expected in owners, expected
    tried: dict[str, str] = {}

    class TriesEverything(FakeProvider):
        async def turn(self, session_id, text):
            session = team.runtime.sessions.get_or_create(session_id)
            for name in owners:
                tried[name] = await dispatch(name, {"order_id": "gid://shopify/Order/1930"}, session=session, timeout_s=5)
            await dispatch("work_note", {"action": "flag", "title": "Refund asked for #1930"}, session=session, timeout_s=5)
            return TurnResult(text="That's George's to do; I've told him.", session_id=session_id)

    team.runtime.staff_provider_factory = lambda person: TriesEverything()
    team.runtime.staff_providers.clear()
    for said in ("refund 1930 she wants her money back", "give her a discount and cancel the order"):
        answer = await team.post("/turn", json={"text": said, "session_id": "m7"}, headers=AS_MIA)
        assert answer.status_code == 200 and answer.json()["answer"] == "That's George's to do; I've told him."
    assert tried and all(result.startswith("REFUSED") for result in tried.values()), [
        name for name, result in tried.items() if not result.startswith("REFUSED")]
    session = team.runtime.sessions.get("m7")
    assert session.proposals == [] and team.store.mutations == []
    assert [j.title for j in work.items() if j.assignee == "owner"] == ["Refund asked for #1930"] * 2


def test_their_assistant_is_never_offered_an_owner_only_tool_and_is_told_what_to_do_instead(team):  # noqa: F811
    made = team.runtime.staff_provider("mia")
    withheld = set(made._withheld_by_family())
    assert {"shopify_refund_create", "shopify_order_cancel", "shopify_discount_create", "gmail_send_new"} <= withheld
    prompt = build_staff_prompt(people.get("mia"), "")
    assert "work_note flag" in prompt and "\"That's George's to do; I've told him.\"" in prompt
    assert "do not look for another way" in prompt and "speaking rather than typing" in prompt


async def test_a_members_recording_is_still_refused_the_team_speaks_through_their_phone(team, monkeypatch):  # noqa: F811
    """Hold to speak on the team's page turns speech into words on the phone (web/today-voice.js):
    the Mac still never hears a member's recording, and the owner's live-words key stays his."""
    let_mia_in()
    heard: list = []
    monkeypatch.setattr(team.runtime.transcriber, "from_blob", lambda blob, **kw: heard.append(blob))
    refused = await team.post("/turn", data={"session_id": "m8"}, files={"audio": ("q.webm", b"\x1aE\xdf\xa3", "audio/webm")},
                              headers=AS_MIA)
    assert refused.status_code == 403 and refused.json()["code"] == "team_types" and heard == []
    assert (await team.post("/voice/live", headers=AS_MIA)).status_code == 403
    assert not staff.route_allowed("POST", "/voice/live")


@pytest.mark.parametrize("path", ["/today/undo", "/today/flag"])
async def test_the_new_steps_are_behind_the_door_like_every_other(team, path):  # noqa: F811
    stranger = {"Tailscale-User-Login": "nobody@example.com", "X-Forwarded-For": "100.64.0.99"}
    assert (await team.post(path, json={}, headers=stranger)).status_code == 403
    assert (await team.post(path, json={}, headers=AS_MIA)).status_code == 403              # waiting for his passkey


# ------------------------------------------------------------------ the review of 0a0e95fb (3 October)

def fulfilled(proposal_id="prop_fulfil0001"):
    """What the commit route hands the work list once a member's fulfilment card has been made."""
    return SimpleNamespace(operation="fulfillment_create", status=SimpleNamespace(value="VERIFIED"), caller=MIA,
                           entity_ref=ORDER, entity_label="#1930", proposal_id=proposal_id)


async def test_packed_in_one_tap_then_fulfilled_by_a_card_reads_finished_and_undo_cannot_reopen_it(team):  # noqa: F811
    """The blocker: Today's Packed packs and finishes at once, so when the fulfilment card landed the
    hook found the job already done and skipped it. The order sat as "packed, waiting for tracking"
    and Undo could reopen a job whose fulfilment stands in Shopify."""
    let_mia_in()
    item_id = await claim_pack_finish(team)
    hooks.after_commit(fulfilled())
    item = work.get(item_id)
    assert item.evidence["fulfilled"] is True and item.evidence["proposal_id"] == "prop_fulfil0001"
    board = (await team.get("/today/state", headers=AS_MIA)).json()["work"]
    assert [r for r in board["in_hand"] if r["ref"] == ORDER_REF] == []                     # not "packed, waiting"
    refused = await team.post("/today/undo", json={"item_id": item_id, "steps": ["done", "packed", "claimed"]},
                              headers=AS_MIA)
    assert refused.status_code == 409 and "card" in refused.json()["detail"]
    assert work.get(item_id).status == "done"
    hooks.after_commit(fulfilled("prop_fulfil0002"))                                         # a second change: kept as the first
    assert work.get(item_id).evidence["proposal_id"] == "prop_fulfil0001"


async def test_undo_takes_back_only_steps_that_are_all_still_recent(team):  # noqa: F811
    """The window held only the newest step: a claim from long ago was undone along with a packing
    step a second old."""
    let_mia_in()
    claimed = await team.post("/today/claim", json={"ref": ORDER_REF}, headers=AS_MIA)
    item_id = claimed.json()["job"]["item_id"]
    item = work.get(item_id)
    item.events[-1]["at"] = (datetime.now(UTC) - timedelta(seconds=work_store.UNDO_WINDOW_S + 60)).isoformat(timespec="seconds")
    work._save(item)
    await team.post("/today/packed", json={"item_id": item_id}, headers=AS_MIA)
    stale = await team.post("/today/undo", json={"item_id": item_id, "steps": ["packed", "claimed"]}, headers=AS_MIA)
    assert stale.status_code == 409 and "too long ago" in stale.json()["detail"]
    assert work.get(item_id).status == "claimed" and work.get(item_id).evidence.get("packed")
    fresh = await team.post("/today/undo", json={"item_id": item_id, "steps": ["packed"]}, headers=AS_MIA)
    assert fresh.status_code == 200 and not work.get(item_id).evidence.get("packed")


async def test_undoing_the_owners_give_back_hands_the_job_back_to_who_had_it(team):  # noqa: F811
    """George gave back Mia's job and undid it: the job came back as his, not hers."""
    let_mia_in()
    claimed = await team.post("/today/claim", json={"ref": ORDER_REF}, headers=AS_MIA)
    item_id = claimed.json()["job"]["item_id"]
    since = work.get(item_id).claimed_at
    given = await team.post("/today/release", json={"item_id": item_id}, headers=PROXIED)
    assert given.status_code == 200 and work.get(item_id).status == "open"
    undone = await team.post("/today/undo", json={"item_id": item_id, "steps": ["released"]}, headers=PROXIED)
    assert undone.status_code == 200
    item = work.get(item_id)
    assert (item.status, item.claimed_by, item.claimed_at) == ("claimed", "mia", since)
    assert [r["ref"] for r in (await team.get("/today/state", headers=AS_MIA)).json()["work"]["mine_found"]] == [ORDER_REF]
    # Her own give-back, undone, is hers again too.
    await team.post("/today/release", json={"item_id": item_id}, headers=AS_MIA)
    await team.post("/today/undo", json={"item_id": item_id, "steps": ["released"]}, headers=AS_MIA)
    assert work.get(item_id).claimed_by == "mia"
