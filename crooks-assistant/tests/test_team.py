"""The team at the door and on their own screen (app/people door, staff rules; app/routes/today.py):
a member of the team the owner let in with his passkey reaches the team's routes and nothing else,
talks to their own assistant with only their tools, works their list, and may confirm only the
changes the owner allowed them, recorded as theirs.

Through the real app and its door (tests/test_actions_routes `client`), with Tailscale's identity
check switched off as those tests switch it off, and the door's verification asked directly.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.main import app
from app.people import access, door, staff
from app.people.prompt import build_staff_prompt
from app.people.store import people
from app.providers.base import TurnResult
from app.providers.max_agent_sdk import MaxAgentSDKProvider
from app.tools import authority
from app.tools.dispatch import dispatch
from app.work import found as live
from app.work.store import work
from tests.fake_passkey import ORIGIN, RP_ID
from tests.test_actions import ORDER, TOOL
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    FakeProvider,
    client,
    commit,
    configure,
    staged,
)
from tests.test_connections_routes import (  # noqa: F401 - `world` is a fixture
    HEADERS,
    approval,
    register,
    world,
)

MIA = "mia@example.com"
AS_MIA = {"Tailscale-User-Login": MIA, "X-Forwarded-For": "100.64.0.7"}
ORDER_REF = f"order:{ORDER}"


@pytest.fixture
def team(client, tmp_path, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    """The owner's server with Mia on the team, her login waiting for his passkey, and an order
    CLIVE found to pack. Configured after the app has started, which configures its own."""
    configure(client, logins=OWNER)
    people.configure(tmp_path / "people.json")
    access.configure(state_dir=tmp_path / "secret")
    work.configure(tmp_path / "work")
    live.reset()
    answers = {"orders": {"available": True, "items": [{
        "ref": ORDER_REF, "kind": "pack_order", "title": "Pack #1930: 1 item for Jane", "details": "",
        "lines": [{"item": "Hoodie (M)", "sku": "HD-M", "quantity": 1}], "since": "2026-10-01T08:00:00Z"}]},
        "emails": {"available": True, "items": []}, "instagram": {"available": True, "items": []}}

    async def found(runtime, *, fresh=False):
        return answers

    monkeypatch.setattr(live, "found", found)
    people.note({"name": "Mia", "kind": "staff", "role": "office: packing, emails, Instagram", "login": MIA})
    access.ask("mia", MIA)
    client.runtime.staff_providers.clear()
    yield client
    people.configure(None)
    access.configure(state_dir=None)
    work.configure(None)
    live.reset()


def let_mia_in():
    access.approve("mia", login=MIA, by="owner", passkey="pk")


# ------------------------------------------------------------------ the door

async def test_a_member_of_the_team_gets_in_only_once_the_owner_has_let_them(team):
    assert (await team.get("/today/state", headers=AS_MIA)).status_code == 403          # waiting for his passkey
    let_mia_in()
    state = await team.get("/today/state", headers=AS_MIA)
    assert state.status_code == 200 and state.headers["cache-control"] == "no-store"
    assert state.json()["me"] == {"id": "mia", "owner": False, "name": "Mia"}
    assert state.json()["people"] == [people.get("mia").public(for_staff=True)]
    assert "routines" not in state.json()
    access.suspend("mia", by="owner")
    assert (await team.get("/today/state", headers=AS_MIA)).status_code == 403
    access.approve("mia", login=MIA, by="owner", passkey="pk")
    people.note({"name": "Mia", "active": False})
    assert (await team.get("/today/state", headers=AS_MIA)).status_code == 403          # taken off the list
    stranger = {"Tailscale-User-Login": "kit@example.com", "X-Forwarded-For": "100.64.0.8"}
    assert (await team.get("/today/state", headers=stranger)).status_code == 403
    local = await team.get("/today/state")                                                # the server itself, in these tests
    assert local.status_code == 200 and local.json()["me"]["owner"] is True                 # the owner (CROOKS_LOCAL_OWNER)


async def test_every_route_but_the_teams_stays_the_owners(team):
    """Walks every route the app serves, as tests/test_proxy_identity.py does for strangers: a route
    added later is the owner's alone unless app/people/staff.py names it."""
    from app.main import is_public

    let_mia_in()
    served = [(template, method.upper()) for template, item in app.openapi()["paths"].items() for method in item]
    served += [("/openapi.json", "GET"), ("/docs", "GET"), ("/redoc", "GET")]
    theirs, refused = [], []
    for template, method in served:
        path = re.sub(r"\{[^}]+\}", "scr_000000000000", template)
        if is_public(path):
            continue
        if staff.route_allowed(method, path):
            theirs.append((method, path))
            continue
        response = await team.request(method, path, headers=AS_MIA)
        assert response.status_code == 403, (method, path, response.status_code)
        refused.append(path)
    assert sorted(theirs) == sorted([
        ("POST", "/turn"), ("GET", "/today"), ("GET", "/today/state"),
        ("POST", "/today/claim"), ("POST", "/today/release"), ("POST", "/today/packed"), ("POST", "/today/counts"),
        ("POST", "/today/done"), ("POST", "/today/assign"), ("POST", "/today/cancel"), ("POST", "/today/routine"),
        ("POST", "/today/routine/stop"), ("POST", "/today/access/scr_000000000000/approve"),
        ("POST", "/today/access/scr_000000000000/suspend"),
        ("POST", "/actions/row"), ("POST", "/actions/scr_000000000000/arm"), ("POST", "/actions/scr_000000000000/commit"),
        ("POST", "/actions/scr_000000000000/dismiss"), ("GET", "/actions/states"), ("GET", "/actions/scr_000000000000"),
    ])
    for owners in ("/connections/state", "/objectives", "/speak", "/tools", "/state/scr_000000000000", "/reset",
                   "/cancel", "/openapi.json"):
        assert owners in refused, owners


async def test_the_front_page_sends_the_team_to_their_own(team):
    let_mia_in()
    sent = await team.get("/", headers=AS_MIA, follow_redirects=False)
    assert sent.status_code == 303 and sent.headers["location"] == "/today"
    assert (await team.get("/", headers=PROXIED)).status_code == 200                     # the owner's own page
    page = await team.get("/today", headers=AS_MIA)
    assert page.status_code == 200 and "today.js" in page.text and page.headers["x-frame-options"] == "DENY"


def test_the_doors_second_rule_asks_tailscale_whose_device_it_is(team, monkeypatch):
    from app import identity
    from app.routes import actions as actions_route

    let_mia_in()
    asked = []
    monkeypatch.setattr(actions_route, "proxy_state", lambda request: (actions_route.TAILSCALE, ""))
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")

    def verify(address, login, *, cli):
        asked.append((address, login))
        return verdict_now

    monkeypatch.setattr(identity, "verify", verify)
    request = SimpleNamespace(headers={"tailscale-user-login": "MIA@example.com", "x-forwarded-for": "100.64.0.7"},
                              app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(
                                  settings=SimpleNamespace(tailscale_verify=True, tailscale_cli="")))))
    verdict_now = (True, "")
    assert door.verdict(request) == ("mia", MIA, "") and asked == [("100.64.0.7", MIA)]
    verdict_now = (False, "that device is someone else's")
    assert door.verdict(request) == ("", "", "Tailscale could not confirm this device's identity: that device is someone else's")
    monkeypatch.setattr(actions_route, "proxy_state", lambda request: (actions_route.DIRECT, ""))
    assert door.verdict(request)[0] == ""                                                   # never from the server itself


# ------------------------------------------------------------------ the owner lets them in

async def test_the_owner_lets_a_member_in_and_takes_access_away_with_his_passkey(team, world):  # noqa: F811
    from app.connections import ledger

    await register(world)
    path = "/today/access/mia/approve"
    missing = await world.post(path, json={}, headers=HEADERS)
    assert missing.status_code == 403 and missing.json()["code"] == "passkey_missing"
    other = await world.post(path, json={"approval": await approval(world, "disconnect:elevenlabs")}, headers=HEADERS)
    assert other.status_code == 403 and other.json()["code"] == "passkey_stale"
    assert access.state("mia") == "pending"
    done = await world.post(path, json={"approval": await approval(world, f"access:approve:mia:{MIA}"), "login": MIA},
                            headers=HEADERS)
    assert done.status_code == 200 and done.json()["access"] == "active"
    assert (await world.get("/today/state", headers=AS_MIA)).status_code == 200
    assert work.history(who="owner")[0] | {"at": ""} == {"at": "", "who": "owner", "what": "access_approved",
                                                          "item_id": "mia", "detail": "Mia"}
    assert "access_approved" in [entry["action"] for entry in ledger.recent()]
    gone = await world.post("/today/access/mia/suspend", headers=HEADERS,
                            json={"approval": await approval(world, "access:suspend:mia")})
    assert gone.status_code == 200 and (await world.get("/today/state", headers=AS_MIA)).status_code == 403
    nobody = await world.post("/connections/approve", json={"action": "access:approve:henry"}, headers=HEADERS)
    assert nobody.status_code in (400, 403, 404)                                             # not a member of the team


async def test_an_approval_is_for_the_login_he_saw_and_never_his_own(team, world):  # noqa: F811
    """The 1 October review (M1): the passkey signs the person and the login shown beside them. A login
    swapped after he saw it, or one of the owner's own, is refused and nobody is let in."""
    await register(world)
    path = "/today/access/mia/approve"
    people.note({"name": "Mia", "login": "someone.else@example.net"})       # changed under him
    access.ask("mia", "someone.else@example.net")
    stale = await world.post(path, headers=HEADERS,
                             json={"approval": await approval(world, f"access:approve:mia:{MIA}"), "login": MIA})
    assert stale.status_code == 409 and stale.json()["code"] == "login_changed"
    assert access.state("mia") == "pending" and access.person_for_login("someone.else@example.net") == ""
    unsigned = await world.post(path, headers=HEADERS, json={
        "approval": await approval(world, f"access:approve:mia:{MIA}"), "login": "someone.else@example.net"})
    assert unsigned.status_code == 403 and unsigned.json()["code"] == "passkey_stale"   # signed for another login
    assert access.state("mia") == "pending"
    people.note({"name": "Mia", "login": OWNER})
    access.ask("mia", OWNER)
    own = await world.post(path, headers=HEADERS,
                           json={"approval": await approval(world, f"access:approve:mia:{OWNER}"), "login": OWNER})
    assert own.status_code == 409 and own.json()["code"] == "owner_login" and access.state("mia") == "pending"
    loginless = await world.post("/connections/approve", json={"action": "access:approve:mia"}, headers=HEADERS)
    assert loginless.status_code == 400                                       # an approval always names the login


async def test_the_server_itself_is_refused_letting_someone_in_and_said_so(team):
    """The server is the owner for his reads here (CROOKS_LOCAL_OWNER), but letting someone in needs his
    passkey from his own device: refused in this route's own shape, never an unhandled error."""
    for verb in ("approve", "suspend"):
        refused = await team.post(f"/today/access/mia/{verb}", json={"login": MIA}, headers={"Origin": ORIGIN, "Host": RP_ID})
        assert refused.status_code == 403 and refused.json()["code"] == "not_from_the_server", verb
    assert access.state("mia") == "pending"


async def test_the_owners_steps_are_refused_to_the_team(team):
    let_mia_in()
    for path, body in (("/today/assign", {"title": "Do my job"}), ("/today/routine", {"title": "x", "cadence": "daily"}),
                       ("/today/cancel", {"item_id": "w_261001_00000000"}), ("/today/routine/stop", {"routine_id": "r_1"}),
                       ("/today/access/mia/approve", {}), ("/today/access/mia/suspend", {})):
        refused = await team.post(path, json=body, headers=AS_MIA)
        assert refused.status_code == 403 and refused.json()["code"] == "owners", path
    assert work.items() == []


# ------------------------------------------------------------------ their list, through the page

async def test_a_member_claims_packs_and_finishes_an_order_and_the_owner_sees_who(team):
    let_mia_in()
    state = (await team.get("/today/state", headers=AS_MIA)).json()
    assert [row["ref"] for row in state["work"]["found"]] == [ORDER_REF]
    claimed = await team.post("/today/claim", json={"ref": ORDER_REF}, headers=AS_MIA)
    assert claimed.status_code == 200 and claimed.json()["job"]["claimed_by_name"] == "Mia"
    item_id = claimed.json()["job"]["item_id"]
    assert (await team.post("/today/packed", json={"item_id": item_id}, headers=AS_MIA)).status_code == 200
    assert (await team.post("/today/done", json={"item_id": item_id, "note": "in the post bag"}, headers=AS_MIA)).status_code == 200
    gone = await team.post("/today/claim", json={"ref": "order:gid://shopify/Order/5"}, headers=AS_MIA)
    assert gone.status_code == 409 and gone.json()["code"] == "gone"

    board = (await team.get("/today/state", headers=PROXIED)).json()
    assert board["me"]["owner"] is True and board["people"][0]["access"] == "active" and board["people"][0]["login"] == MIA
    assert [(e["who_name"], e["what"]) for e in board["record"][:3]] == [("Mia", "done"), ("Mia", "packed"), ("Mia", "claimed")]
    assert [(r["status"], r["done_by_name"]) for r in board["work"]["in_hand"]] == [("packed", "Mia")]
    own = (await team.get("/today/state", headers=AS_MIA)).json()["record"]
    assert {e["who"] for e in own} == {"mia"}


async def test_the_owner_hands_out_a_count_and_the_count_comes_back(team):
    let_mia_in()
    handed = await team.post("/today/assign", json={"title": "Count the hoodies", "kind": "stock_count", "to": "mia"},
                             headers=PROXIED)
    assert handed.status_code == 200 and handed.json()["job"]["assignee_name"] == "Mia"
    item_id = handed.json()["job"]["item_id"]
    assert (await team.post("/today/assign", json={"title": "x", "to": "nobody"}, headers=PROXIED)).status_code == 404
    mine = (await team.get("/today/state", headers=AS_MIA)).json()["work"]["mine"]
    assert [j["item_id"] for j in mine] == [item_id]
    await team.post("/today/claim", json={"item_id": item_id}, headers=AS_MIA)
    unread = await team.post("/today/counts", json={"item_id": item_id, "counts": "twelve"}, headers=AS_MIA)
    assert unread.status_code == 400
    counted = await team.post("/today/counts", headers=AS_MIA,
                              json={"item_id": item_id, "counts": [{"item": "Hoodie M", "counted": "12"}]})
    assert counted.status_code == 200 and counted.json()["job"]["evidence"]["counts"][0]["counted"] == 12
    assert (await team.post("/today/done", json={"item_id": item_id}, headers=AS_MIA)).status_code == 200


async def test_what_the_page_sends_is_held_to_a_job_s_size(team):
    let_mia_in()
    garbled = await team.post("/today/claim", content=b"\xff not json", headers={**AS_MIA, "Content-Type": "application/json"})
    assert garbled.status_code == 400 and garbled.json()["code"] == "bad_request"
    listed = await team.post("/today/claim", json=["a", "list"], headers=AS_MIA)
    assert listed.status_code == 400
    huge = await team.post("/today/done", json={"item_id": "w_261001_00000000", "note": "x" * 70_000}, headers=AS_MIA)
    assert huge.status_code == 413


# ------------------------------------------------------------------ their own assistant

class StaffProvider(FakeProvider):
    def __init__(self, asked):
        self.asked = asked

    async def turn(self, session_id, text):
        self.asked.append((session_id, text))
        return TurnResult(text="Your list has one order to pack.", session_id=session_id)


async def test_a_member_talks_to_their_own_assistant_and_never_into_the_owners_conversation(team):
    let_mia_in()
    asked: list = []
    team.runtime.staff_provider_factory = lambda person: StaffProvider(asked)
    answer = await team.post("/turn", json={"text": "What's mine today?", "session_id": "m1"}, headers=AS_MIA)
    assert answer.status_code == 200 and answer.json()["answer"] == "Your list has one order to pack."
    assert [s for s, _ in asked] == ["m1"] and "What's mine today?" in asked[0][1]
    owners = await team.post("/turn", json={"text": "Hello", "session_id": "o1"}, headers=PROXIED)
    assert owners.json()["answer"] == "fake answer" and len(asked) == 1                    # the owner's own, untouched
    into_his = await team.post("/turn", json={"text": "What did George say?", "session_id": "o1"}, headers=AS_MIA)
    assert into_his.status_code == 403 and into_his.json()["code"] == "wrong_session"
    assert len(asked) == 1


def test_a_members_assistant_is_made_from_their_card_with_only_their_tools(team):
    runtime = team.runtime
    made = runtime.staff_provider("mia")
    assert isinstance(made, MaxAgentSDKProvider)
    assert "You are talking with Mia, who works for CROOKS: office: packing, emails, Instagram." in made._system_prompt
    withheld = set(made._withheld_by_family())
    assert {"objective_list", "objective_note", "engineering_status", "submit_engineering_request", "screen_show",
            "shopify_refund_create", "shopify_order_cancel", "gmail_send_new", "person_note", "close_screen"} <= withheld
    assert not (staff.TOOLS & withheld) - set(runtime.withheld_by_family())                # all theirs, unless down for all
    assert runtime.provider_for(authority.for_staff("mia", MIA)) is made
    assert runtime.provider_for(authority.for_owner(OWNER)) is runtime.provider
    assert runtime.staff_provider("mia") is made                                            # kept while the card holds
    people.note({"name": "Mia", "role": "packing and the stock counts"})
    again = runtime.staff_provider("mia")
    assert again is not made and "packing and the stock counts" in again._system_prompt
    assert runtime.retired_providers == [made]                                              # stopped at the next turn


def test_the_teams_prompt_is_written_to_them_and_holds_nothing_of_the_owners():
    person = SimpleNamespace(name="Mia Rose", role="")
    prompt = build_staff_prompt(person, "Returns: 30 days.")
    assert prompt.startswith("You are CLIVE") and "You are talking with Mia Rose, who works for CROOKS: one of the team." in prompt
    assert "Help Mia get through today's work" in prompt and "# What CROOKS knows\n\nReturns: 30 days." in prompt
    for owners in ("objective", "engineering", "screen_show", "refund_create", "{", "}"):
        assert owners not in prompt, owners
    assert "do not have that to hand" in build_staff_prompt(person, "  ")


# ------------------------------------------------------------------ what they may change

def test_a_staff_authority_names_its_tools_and_may_stage_only_those():
    held = authority.for_staff("mia", MIA)
    assert held.kind == authority.STAFF and held.who == "mia" and held.purpose == MIA and held.active
    assert held.permits("shopify_order_fulfil") and held.permits("work_note") and held.may_stage()
    for owners in ("shopify_refund_create", "objective_list", "person_note", "gmail_send_new", "mock_danger"):
        assert not held.permits(owners), owners
    assert not authority.Authority(authority.STAFF, "mia", expires_at=held.expires_at, tools=frozenset()).active
    assert authority.for_owner(OWNER).may_stage()
    service = authority.for_owner(OWNER).derive("look", 30.0, tools=("shopify_find_order",))
    assert service is not None and not service.may_stage()


async def test_a_member_may_stage_a_change_the_owner_allowed_and_nothing_else(team, monkeypatch):
    session = team.runtime.sessions.get_or_create("m1")
    session.issue(ORDER)
    session.epoch = max(session.epoch, 1)
    with authority.acting_as(authority.for_staff("mia", MIA)):
        refused = await dispatch(TOOL, {"order_id": ORDER, "note": "x"}, session=session, timeout_s=5)
    assert refused.startswith("REFUSED") and not session.proposals
    monkeypatch.setattr(staff, "TOOLS", staff.TOOLS | {TOOL})                               # as if the owner had allowed it
    with authority.acting_as(authority.for_staff("mia", MIA)):
        allowed = await dispatch(TOOL, {"order_id": ORDER, "note": "Packed by Mia"}, session=session, timeout_s=5)
    assert allowed.startswith("PROPOSED") and len(session.proposals) == 1


async def test_a_members_tap_makes_only_the_changes_the_owner_allowed_them_in_their_name(team, monkeypatch):
    let_mia_in()
    with authority.acting_as(authority.for_owner(OWNER)):
        proposal = await staged(team, session_id="m1")
    team.runtime.sessions.get_or_create("m1").login = MIA
    assert proposal.operation == "order_note_append"
    refused = await commit(team, proposal.proposal_id, session_id="m1", headers=AS_MIA)
    assert refused.status_code == 403 and refused.json()["code"] == "not_yours_to_make"
    armed = await team.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "m1"}, headers=AS_MIA)
    assert armed.status_code == 403 and armed.json()["code"] == "not_yours_to_make"
    assert team.store.mutations == [] and proposal.status.value == "PENDING"
    theirs = await team.get(f"/actions/{proposal.proposal_id}", params={"session_id": "m1"}, headers=PROXIED)
    assert theirs.status_code == 403 and theirs.json()["code"] == "wrong_session"          # her conversation, not his
    monkeypatch.setattr(staff, "OPERATIONS_WITH_UNDO", frozenset({"order_note_append"}))    # as if the owner had allowed it
    made = await commit(team, proposal.proposal_id, session_id="m1", headers=AS_MIA)
    assert made.status_code == 200 and made.json()["status"] == "verified"
    assert proposal.caller == MIA and len(team.store.mutations) == 1


async def test_the_owners_tap_on_his_own_card_is_unchanged(team):
    with authority.acting_as(authority.for_owner(OWNER)):
        proposal = await staged(team, session_id="o1")
    made = await commit(team, proposal.proposal_id, session_id="o1", headers=PROXIED)
    assert made.status_code == 200 and made.json()["status"] == "verified" and proposal.caller == OWNER
