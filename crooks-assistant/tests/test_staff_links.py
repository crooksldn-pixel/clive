"""Staff links (ruling 35 of DEC-071, built as DEC-075; docs/STAFF_LINKS.md): a member of the team
joins CLIVE from their own phone with a link and a code, through the team's public door, and gets
exactly the team's own page and tools.

Every rule of the threat model is held here: the invite's whole life (made with George's passkey,
single use, expiry, cancelled, replaced), the code's brute force (per link, per address, overall),
replay, the phone's cookie (its flags, rotation, a copied one, idle and age expiry), revocation, every
owner route unreachable through the door, nobody through the door ever the owner or the server
itself, the staff tool set unchanged, cross-site requests refused, and no secret in any log or record.

Through the real app and its door (tests/test_actions_routes `client`), with Tailscale's own device
check off as those tests have it. A request through the team's door carries what the host's Caddy
adds (X-Clive-Door, the team's Host, X-Forwarded-For); the phone's cookie is sent by hand, since the
test client's jar rightly never sends a Secure cookie over plain http.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import stat

import pytest

from app.main import app
from app.people import access, links, staff, team_door
from app.people.store import people
from app.providers.base import TurnResult
from app.tools import authority
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
from tests.test_team import AS_MIA, MIA, ORDER_REF, team  # noqa: F401 - `team` is a fixture

HOST = "team.example.test"
DOOR = {"X-Clive-Door": "team", "Host": HOST, "X-Forwarded-For": "198.51.100.7"}
POST = {**DOOR, "Origin": f"https://{HOST}"}
# What the team may do, as the owner decided on 1 October (app/people/staff.py): pinned here, so a
# phone through the team's door is held to exactly the set a team member on Tailscale has.
TEAM_TOOLS = frozenset({
    "shopify_find_order", "shopify_list_orders", "shopify_order_detail", "shopify_order_address",
    "shopify_find_customer", "shopify_customer_history", "shopify_product_info", "shopify_variant_search",
    "shopify_inventory", "shopify_sales_summary", "shopify_abandoned_checkouts", "shopify_discount_check",
    "commerce_query", "commerce_aggregate", "commerce_summary", "commerce_capabilities", "inventory_query",
    "email_query", "gmail_search", "gmail_read_thread", "gmail_find_in_email",
    "instagram_inbox", "instagram_thread", "instagram_comments",
    "people_list", "work_list", "work_note",
    "shopify_order_fulfil", "shopify_fulfillment_tracking_set", "gmail_draft_reply", "gmail_send_reply",
    "shopify_inventory_adjust",
})


@pytest.fixture
def door(team, tmp_path, monkeypatch):  # noqa: F811 - fixtures imported from the suites they belong to
    """Mia on the team (her Tailscale login still waiting), the team's address set, links kept in a
    temporary root-only folder, and the join counters empty."""
    team.runtime.settings = team.runtime.settings.model_copy(update={"team_host": HOST})
    links.configure(state_dir=tmp_path / "secret")
    yield team
    links.configure(state_dir=None)


def cookie_of(response) -> str:
    raw = response.headers.get("set-cookie", "")
    match = re.match(rf"{re.escape(links.COOKIE)}=([^;]*)", raw)
    assert match, raw
    return match.group(1)


def signed_in(value: str) -> dict:
    return {**DOOR, "Cookie": f"{links.COOKIE}={value}"}


def posting(value: str) -> dict:
    return {**POST, "Cookie": f"{links.COOKIE}={value}"}


async def join(http, person="mia", *, address="198.51.100.7"):
    token, code, _ = links.make(person, by="owner")
    answer = await http.post("/join", json={"token": token, "code": code}, headers={**POST, "X-Forwarded-For": address})
    assert answer.status_code == 200, answer.text
    return cookie_of(answer)


# ------------------------------------------------------------------ the invite's life

async def test_george_makes_a_link_with_his_passkey_and_it_is_shown_once_and_kept_as_hashes(door, world, tmp_path):  # noqa: F811
    await register(world)
    path = "/staff-links/mia/make"
    missing = await world.post(path, json={}, headers=HEADERS)
    assert missing.status_code == 403 and missing.json()["code"] == "passkey_missing"
    other = await world.post(path, json={"approval": await approval(world, "access:suspend:mia")}, headers=HEADERS)
    assert other.status_code == 403 and other.json()["code"] == "passkey_stale"
    made = await world.post(path, json={"approval": await approval(world, "staff-link:make:mia")}, headers=HEADERS)
    assert made.status_code == 200 and made.headers["cache-control"] == "no-store"
    body = made.json()
    token = re.fullmatch(rf"https://{re.escape(HOST)}/join#([A-Za-z0-9_-]{{43}})", body["link"]).group(1)
    assert re.fullmatch(r"[0-9]{6}", body["code"]) and body["name"] == "Mia" and body["expires_at"]
    kept = tmp_path / "secret" / links.FILE_NAME
    text = kept.read_text(encoding="utf-8")
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert token not in text and body["code"] not in json.dumps(json.loads(text)["invites"])
    assert hashlib.sha256(token.encode()).hexdigest() in text
    # Shown once: what George's screen reads afterwards names the link's state, never the link.
    board = (await world.get("/today/state", headers=PROXIED)).json()
    assert board["links_ready"] is True and board["links"]["mia"]["link"]["state"] == "open"
    assert token not in json.dumps(board) and body["code"] not in json.dumps(board["links"])
    # Only someone on the team, and only with the team's address set.
    assert (await world.post("/connections/approve", json={"action": "staff-link:make:nobody"}, headers=HEADERS)).status_code == 400
    world.runtime.settings = world.runtime.settings.model_copy(update={"team_host": ""})
    unset = await world.post(path, json={"approval": await approval(world, "staff-link:make:mia")}, headers=HEADERS)
    assert unset.status_code == 409 and unset.json()["code"] == "no_team_host"


async def test_the_team_cannot_make_links_or_add_people(door):
    access.approve("mia", login=MIA, by="owner", passkey="pk")
    for path in ("/staff-links/mia/make", "/staff-links/add", "/staff-links/mia/cancel", "/staff-links/phones/p0/sign-out"):
        refused = await door.post(path, json={"name": "Kit"}, headers=AS_MIA)
        assert refused.status_code == 403, path
    phone = await join(door)
    for path in ("/staff-links/mia/make", "/staff-links/add"):
        assert (await door.post(path, json={}, headers=posting(phone))).status_code == 404, path


async def test_george_adds_someone_with_no_tailscale_login_and_their_link_lets_them_in(door):
    added = await door.post("/staff-links/add", json={"name": "Ana Fixture", "role": "packing"}, headers=PROXIED)
    assert added.status_code == 200 and added.json()["person"]["person_id"] == "ana-fixture"
    card = people.get("ana-fixture")
    assert card.kind == "staff" and card.login == "" and card.active
    assert access.state("ana-fixture") == ""                                          # no Tailscale grant at all
    phone = await join(door, "ana-fixture")
    state = await door.get("/today/state", headers=signed_in(phone))
    assert state.status_code == 200 and state.json()["me"] == {"id": "ana-fixture", "owner": False, "name": "Ana Fixture"}
    assert (await door.post("/staff-links/add", json={"name": ""}, headers=PROXIED)).json()["code"] == "missing"


async def test_joining_signs_the_phone_in_with_a_strict_cookie_once(door):
    token, code, _ = links.make("mia", by="owner")
    joined = await door.post("/join", json={"token": token, "code": code}, headers=POST)
    assert joined.status_code == 200 and joined.json() == {"ok": True, "name": "Mia"}
    raw = joined.headers["set-cookie"]
    parts = [p.strip() for p in raw.split(";")]
    assert parts[0].startswith("__Host-clive_team=") and "Domain" not in raw
    assert {"Path=/", "HttpOnly", "Secure", "SameSite=Strict", f"Max-Age={links.IDLE_S}"} <= set(parts)
    phone = cookie_of(joined)
    state = await door.get("/today/state", headers=signed_in(phone))
    assert state.status_code == 200 and state.json()["me"] == {"id": "mia", "owner": False, "name": "Mia"}
    assert state.headers["cache-control"] == "no-store" and state.headers["x-frame-options"] == "DENY"
    # The same link again, from anywhere: refused like any link that is not open.
    again = await door.post("/join", json={"token": token, "code": code}, headers={**POST, "X-Forwarded-For": "203.0.113.9"})
    assert again.status_code == 403 and again.json()["code"] == "not_valid"
    # Joining means nothing anywhere but the team's door.
    token, code, _ = links.make("mia", by="owner")
    for headers in ({"Origin": f"https://{HOST}"}, {**AS_MIA, "Origin": f"https://{HOST}"}):
        assert (await door.post("/join", json={"token": token, "code": code}, headers=headers)).status_code in (403, 404)
    assert links.summary()["mia"]["link"]["state"] == "open"


async def test_every_link_that_is_not_open_is_refused_the_same(door, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr(links.time, "time", lambda: clock[0])
    answers = []

    async def refused(token, code="000000"):
        answer = await door.post("/join", json={"token": token, "code": code}, headers=POST)
        answers.append((answer.status_code, answer.json()))

    used_token, used_code, _ = links.make("mia", by="owner")
    await door.post("/join", json={"token": used_token, "code": used_code}, headers=POST)
    await refused(used_token, used_code)                                               # used
    await refused("x" * 43)                                                            # never made
    old, old_code, _ = links.make("mia", by="owner")
    newer, newer_code, _ = links.make("mia", by="owner")
    await refused(old, old_code)                                                       # replaced by a newer one
    links.cancel("mia")
    await refused(newer, newer_code)                                                   # cancelled
    late, late_code, _ = links.make("mia", by="owner")
    clock[0] += links.INVITE_TTL_S + 1
    await refused(late, late_code)                                                     # run out
    gone, gone_code, _ = links.make("mia", by="owner")
    people.note({"name": "Mia", "active": False})
    await refused(gone, gone_code)                                                     # taken off the team
    assert len(answers) == 6 and {json.dumps(a, sort_keys=True) for a in answers} == {json.dumps(
        (403, {"ok": False, "code": "not_valid", "detail": links.NOT_VALID}), sort_keys=True)}


async def test_the_join_reads_no_more_than_a_link_and_a_code(door):
    big = await door.post("/join", content=b"{" + b" " * 5000 + b"}", headers={**POST, "Content-Type": "application/json"})
    assert big.status_code == 413 and big.json()["code"] == "too_large"
    for garbled in (b"\xff not json", b"[1, 2]"):
        answer = await door.post("/join", content=garbled, headers={**POST, "Content-Type": "application/json"})
        assert answer.status_code == 400 and answer.json()["code"] == "bad_request"


# ------------------------------------------------------------------ the code's brute force

async def test_five_wrong_codes_lock_the_link_for_good(door):
    token, code, _ = links.make("mia", by="owner")
    wrong = f"{(int(code) + 1) % 10 ** 6:06d}"
    for left in (4, 3, 2, 1):
        answer = await door.post("/join", json={"token": token, "code": wrong}, headers=POST)
        assert answer.status_code == 403 and answer.json()["code"] == "wrong_code" and answer.json()["tries_left"] == left
    locked = await door.post("/join", json={"token": token, "code": wrong}, headers=POST)
    assert locked.json()["code"] == "locked" and locked.json()["tries_left"] == 0
    right = await door.post("/join", json={"token": token, "code": code}, headers=POST)
    assert right.status_code == 403 and right.json()["code"] == "not_valid"
    assert links.summary()["mia"]["link"]["state"] == "locked" and links.summary()["mia"]["phones"] == []


async def test_failed_joins_are_limited_per_address_and_overall(door, monkeypatch):
    for _ in range(links.ADDRESS_FAILS):
        await door.post("/join", json={"token": "y" * 43, "code": "123456"}, headers=POST)
    token, code, _ = links.make("mia", by="owner")
    held = await door.post("/join", json={"token": "w" * 43, "code": "123456"}, headers=POST)
    assert held.status_code == 429 and held.json()["code"] == "too_many"               # another guess, from there
    elsewhere = await door.post("/join", json={"token": token, "code": code}, headers={**POST, "X-Forwarded-For": "203.0.113.4"})
    assert elsewhere.status_code == 200                                                 # the link was not spent by it
    links.configure(state_dir=links._CONFIG["state_dir"])
    monkeypatch.setattr(links, "ALL_FAILS", 3)
    for n in range(3):
        await door.post("/join", json={"token": "z" * 43, "code": "1"}, headers={**POST, "X-Forwarded-For": f"192.0.2.{n}"})
    overall = await door.post("/join", json={"token": "v" * 43, "code": "123456"}, headers={**POST, "X-Forwarded-For": "192.0.2.99"})
    assert overall.status_code == 429


async def test_made_up_joins_never_keep_a_real_link_out(door, monkeypatch):
    """The review's N2: the limits hold back joins with no open link, never one that is open (its own
    five-code lock holds that). Floods from one address and from everywhere, then the real link."""
    monkeypatch.setattr(links, "ALL_FAILS", 5)
    for n in range(links.ALL_FAILS):
        await door.post("/join", json={"token": "z" * 43, "code": "1"}, headers={**POST, "X-Forwarded-For": f"192.0.2.{n}"})
    for _ in range(links.ADDRESS_FAILS):
        await door.post("/join", json={"token": "y" * 43, "code": "123456"}, headers=POST)
    for token in ("x" * 43, "", "short"):
        guess = await door.post("/join", json={"token": token, "code": "123456"}, headers=POST)
        assert guess.status_code == 429 and guess.json()["code"] == "too_many", token     # unknown or none: held back
    token, code, _ = links.make("mia", by="owner")
    wrong = f"{(int(code) + 1) % 10 ** 6:06d}"
    slip = await door.post("/join", json={"token": token, "code": wrong}, headers=POST)
    assert slip.status_code == 403 and slip.json()["code"] == "wrong_code" and slip.json()["tries_left"] == 4
    real = await door.post("/join", json={"token": token, "code": code}, headers=POST)
    assert real.status_code == 200 and real.json()["name"] == "Mia"
    spent = await door.post("/join", json={"token": token, "code": code}, headers=POST)
    assert spent.status_code == 429                                                     # used: no longer open


# ------------------------------------------------------------------ the phone's sign-in

def test_the_cookie_rotates_and_a_replaced_one_used_late_signs_the_phone_out(door):
    t0 = 1_800_000_000.0
    token, code, _ = links.make("mia", by="owner", now=t0)
    first = cookie_of(type("R", (), {"headers": {"set-cookie": links.redeem(token, code, address="a", now=t0).cookie}})())
    assert links.check(first, now=t0 + 60) == links.Seen("mia", first.split(".")[0], "")
    due = links.check(first, now=t0 + links.ROTATE_S)
    assert due.person_id == "mia" and due.set_cookie.startswith(f"{links.COOKIE}=")
    assert links.check(first, now=t0 + links.ROTATE_S + 1).set_cookie == ""            # not handed twice at once
    second = due.set_cookie.split("=", 1)[1].split(";", 1)[0]
    assert links.check(second, now=t0 + links.ROTATE_S + 5).person_id == "mia"          # seen back: now the one
    assert links.check(first, now=t0 + links.ROTATE_S + 30).person_id == "mia"          # a request already on its way
    stolen = links.check(first, now=t0 + links.ROTATE_S + 5 + links.GRACE_S + 1)
    assert stolen.refused == "signed_out"                                               # a copy exists
    assert links.check(second, now=t0 + links.ROTATE_S + 200).refused == "signed_out"   # so the phone is out
    phone = links.summary(now=t0)["mia"]["phones"][0]
    assert phone["state"] == "signed_out" and "copy" in phone["why"]
    for nonsense in ("", "p123.abc", "x" * 61, first.split(".")[0] + "." + "A" * 43):
        assert links.check(nonsense, now=t0).refused


def _value(header: str) -> str:
    return header.split("=", 1)[1].split(";", 1)[0]


def _joined_at(t0: float) -> str:
    token, code, _ = links.make("mia", by="owner", now=t0)
    return _value(links.redeem(token, code, address="a", kind="iPhone", now=t0).cookie)


def _caught(cookies, at, t0):
    """Every one of these is refused, the phone is signed out as a copy, and George sees it on People."""
    for cookie in cookies:
        assert links.check(cookie, now=at).refused == "signed_out", cookie
    board = links.summary(now=at)["mia"]
    assert board["phones"][0]["state"] == "signed_out" and board["phones"][0]["why"] == links.COPIED
    assert board["copied"] == {"kind": "iPhone", "at": links._iso(at)}


def test_a_copy_renewed_twice_while_the_real_phone_sleeps_is_caught_when_the_real_phone_returns(door):
    """The review's first case: a copy of the cookie is used past two renewals (overnight, say), so the
    real phone's cookie is two sign-ins old when it comes back. That is a copy's tell: both are out."""
    t0 = 1_800_000_000.0
    real = _joined_at(t0)
    thief = real
    for hour in (1, 2):
        handed = links.check(thief, now=t0 + hour * (links.ROTATE_S + 60)).set_cookie
        assert handed, hour
        thief = _value(handed)
        assert links.check(thief, now=t0 + hour * (links.ROTATE_S + 60) + 10).person_id == "mia"
    back = t0 + 2 * (links.ROTATE_S + 60) + 600
    _caught([real, thief], back, t0)


def test_a_copy_that_renews_first_and_empties_the_waiting_list_is_caught_by_the_real_phones_new_cookie(door):
    """The review's second case: the copy and the real phone are each handed a new sign-in, the copy
    shows its own back first (which drops the real phone's from the waiting list), and the real phone
    then uses the one it was given. It was given it, so it is known: a copy exists, both are out."""
    t0 = 1_800_000_000.0
    real = _joined_at(t0)
    due = t0 + links.ROTATE_S
    thief = _value(links.check(real, now=due).set_cookie)
    mine = _value(links.check(real, now=due + links.GRACE_S + 1).set_cookie)
    assert thief != mine
    assert links.check(thief, now=due + links.GRACE_S + 5).person_id == "mia"           # the copy's is seen first
    assert links.check(mine, now=due + links.GRACE_S + 30).person_id == "mia"           # on its way: within the grace
    _caught([mine, thief], due + 2 * links.GRACE_S + 10, t0)


def test_past_what_a_phone_remembers_any_sign_in_it_does_not_know_is_a_copy(door, monkeypatch):
    """`given` is bounded. A guess at a phone that has forgotten nothing is refused and changes nothing;
    once it has had to forget, a sign-in it does not know can only be an old one: a copy."""
    monkeypatch.setattr(links, "KEEP_GIVEN", 2)
    t0 = 1_800_000_000.0
    first = _joined_at(t0)
    phone_id = first.split(".")[0]
    guess = f"{phone_id}.{'A' * 43}"
    assert links.check(guess, now=t0 + 5).refused == "signed_out"
    assert links.check(first, now=t0 + 6).person_id == "mia"                            # a guess ended nothing
    held = first
    for hour in (1, 2, 3):
        held = _value(links.check(held, now=t0 + hour * (links.ROTATE_S + 60)).set_cookie)
        assert links.check(held, now=t0 + hour * (links.ROTATE_S + 60) + 1).person_id == "mia"
    assert links.check(held, now=t0 + 3 * (links.ROTATE_S + 60) + 2).person_id == "mia"
    _caught([first, held], t0 + 3 * (links.ROTATE_S + 60) + 600, t0)


async def test_george_sees_a_copied_phone_on_people_until_a_phone_of_theirs_joins_again(door, monkeypatch):
    clock = [links.time.time()]
    monkeypatch.setattr(links.time, "time", lambda: clock[0])
    phone = await join(door)
    clock[0] += links.ROTATE_S
    renewed = _value(links.check(phone).set_cookie)
    clock[0] += 1
    assert links.check(renewed).person_id == "mia"
    clock[0] += links.GRACE_S + 1
    assert links.check(phone).refused == "signed_out"
    board = (await door.get("/today/state", headers=PROXIED)).json()["links"]["mia"]
    assert board["copied"]["kind"] and board["copied"]["at"] and phone not in json.dumps(board)
    assert (await door.get("/today/state", headers=signed_in(renewed))).status_code == 401
    clock[0] += 60
    await join(door, address="203.0.113.5")
    assert (await door.get("/today/state", headers=PROXIED)).json()["links"]["mia"]["copied"] is None


def test_a_phone_unused_for_a_fortnight_or_older_than_ninety_days_is_signed_out(door):
    t0 = 1_800_000_000.0
    token, code, _ = links.make("mia", by="owner", now=t0)
    idle = links.redeem(token, code, address="a", now=t0).cookie.split("=", 1)[1].split(";", 1)[0]
    assert links.check(idle, now=t0 + links.IDLE_S - 10).person_id == "mia"
    assert links.check(idle, now=t0 + 2 * links.IDLE_S).refused == "signed_out"
    token, code, _ = links.make("mia", by="owner", now=t0)
    busy = links.redeem(token, code, address="a", now=t0).cookie.split("=", 1)[1].split(";", 1)[0]
    at = t0
    while at < t0 + links.MAX_AGE_S - links.IDLE_S:
        at += links.IDLE_S - 60
        seen = links.check(busy, now=at)
        assert seen.person_id == "mia"
        if seen.set_cookie:
            busy = seen.set_cookie.split("=", 1)[1].split(";", 1)[0]
            links.check(busy, now=at + 1)
    assert links.check(busy, now=t0 + links.MAX_AGE_S + 1).refused == "signed_out"


async def test_the_door_hands_the_new_sign_in_with_an_answer_and_clears_a_dead_one(door, monkeypatch):
    phone = await join(door)
    clock = [links.time.time() + links.ROTATE_S + 1]
    monkeypatch.setattr(links.time, "time", lambda: clock[0])
    rotated = await door.get("/today/state", headers=signed_in(phone))
    assert rotated.status_code == 200 and cookie_of(rotated) != phone
    assert "HttpOnly" in rotated.headers["set-cookie"] and "SameSite=Strict" in rotated.headers["set-cookie"]
    links.sign_out_person("mia", by="owner", why="test")
    dead = await door.get("/today/state", headers=signed_in(cookie_of(rotated)))
    assert dead.status_code == 401 and dead.json()["code"] == "signed_out"
    assert dead.headers["set-cookie"].startswith(f"{links.COOKIE}=;") and "Max-Age=0" in dead.headers["set-cookie"]


# ------------------------------------------------------------------ revocation

async def test_george_signs_a_phone_out_and_a_new_phone_replaces_the_old(door):
    first = await join(door)
    second = await join(door, address="203.0.113.5")
    assert (await door.get("/today/state", headers=signed_in(first))).status_code == 401   # replaced by the new phone
    assert (await door.get("/today/state", headers=signed_in(second))).status_code == 200
    board = (await door.get("/today/state", headers=PROXIED)).json()["links"]["mia"]
    active = [p for p in board["phones"] if p["state"] == "active"]
    assert len(active) == 1 and set(active[0]) == {"phone_id", "kind", "state", "joined_at", "last_seen", "ended_at", "why"}
    out = await door.post(f"/staff-links/phones/{active[0]['phone_id']}/sign-out", json={}, headers=PROXIED)
    assert out.status_code == 200
    assert (await door.get("/today/state", headers=signed_in(second))).status_code == 401
    again = await door.post(f"/staff-links/phones/{active[0]['phone_id']}/sign-out", json={}, headers=PROXIED)
    assert again.status_code == 404


async def test_taking_access_away_or_someone_off_signs_out_their_phones_and_cancels_their_link(door, world):  # noqa: F811
    from app.people.tools import person_note

    await register(world)
    phone = await join(door)
    token, code, _ = links.make("mia", by="owner")
    gone = await world.post("/today/access/mia/suspend", headers=HEADERS,
                            json={"approval": await approval(world, "access:suspend:mia")})
    assert gone.status_code == 200
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401
    assert (await door.post("/join", json={"token": token, "code": code}, headers=POST)).json()["code"] == "not_valid"
    phone = await join(door)
    with authority.acting_as(authority.for_owner(OWNER)):
        await person_note(name="Mia", active=False)
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401
    with authority.acting_as(authority.for_owner(OWNER)):
        await person_note(name="Mia", active=True)
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401   # back on the list opens nothing
    assert (await door.post("/staff-links/mia/cancel", json={}, headers=PROXIED)).json()["code"] == "no_link"


async def test_a_phone_and_link_refused_for_being_off_the_team_stay_ended_when_the_card_is_put_back(door, monkeypatch):
    """The review's N3: the card taken off in the people record itself, as when person_note's access
    step fails before it signs the phones out. The refusal ends the phone and the link there and then,
    so putting the card back brings neither back. A record that cannot be read just now refuses once
    and ends nothing."""
    from app.people.store import PeopleError

    phone = await join(door)

    def unreadable(person_id):
        raise PeopleError("the people record on this server cannot be read")

    with monkeypatch.context() as patch:
        patch.setattr(people, "get", unreadable)
        assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 200    # nothing ended
    token, code, _ = links.make("mia", by="owner")
    people.note({"name": "Mia", "active": False})
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401
    assert (await door.post("/join", json={"token": token, "code": code}, headers=POST)).json()["code"] == "not_valid"
    people.note({"name": "Mia", "active": True})
    assert (await door.get("/today/state", headers=signed_in(phone))).status_code == 401
    assert (await door.post("/join", json={"token": token, "code": code}, headers=POST)).json()["code"] == "not_valid"
    board = links.summary()["mia"]
    assert board["phones"][0]["state"] == "signed_out" and board["phones"][0]["why"] == "taken off the team"
    assert board["link"]["state"] == "cancelled"


# ------------------------------------------------------------------ the door reaches the team's page and nothing else

def _served():
    served = [(template, method.upper()) for template, item in app.openapi()["paths"].items() for method in item]
    return served + [("/openapi.json", "GET"), ("/docs", "GET"), ("/redoc", "GET"), ("/sw.js", "GET"),
                     ("/manifest.webmanifest", "GET"), ("/favicon.ico", "GET"), ("/static/app.js", "GET"),
                     ("/static/connections.js", "GET"), ("/static/index.html", "GET"), ("/static/today.html", "GET")]


def _example(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "prop_0123456789ab", template)


async def test_every_route_but_the_teams_page_is_not_found_through_the_door(door):
    """Walks every route the app serves, as tests/test_team.py does on the tailnet: through the team's
    door a route is the team's page or one it calls, or it does not exist. Signed in or not, and with
    the owner's own Tailscale headers and the server's local key added for good measure."""
    phone = await join(door)
    forged = {"Tailscale-User-Login": OWNER, "Tailscale-User-Name": "George", "X-Crooks-Local-Key": "x"}
    reached = []
    for template, method in _served():
        path = _example(template)
        kind = team_door.allowed(method, path)
        for headers in (posting(phone), {**POST, **forged}, {**posting(phone), **forged}):
            answer = await door.request(method, path, headers=headers)
            if not kind:
                assert answer.status_code == 404 and answer.json() == {"detail": "Not Found"}, (method, path)
        if kind:
            reached.append((method, path))
    assert sorted(reached) == sorted([
        ("GET", "/"), ("GET", "/join"), ("POST", "/join"), ("GET", "/today"), ("GET", "/today/state"),
        ("POST", "/today/claim"), ("POST", "/today/release"), ("POST", "/today/packed"), ("POST", "/today/counts"),
        ("POST", "/today/done"), ("POST", "/today/undo"), ("POST", "/today/flag"), ("POST", "/turn"),
        ("GET", "/actions/prop_0123456789ab"), ("POST", "/actions/prop_0123456789ab/arm"),
        ("POST", "/actions/prop_0123456789ab/commit"),
    ])
    for owners in ("/connections", "/connections/state", "/objectives", "/bench", "/health", "/whoami", "/display",
                   "/hooks/wecom", "/hooks/whatsapp", "/today/assign", "/today/people", "/today/access/mia/approve",
                   "/staff-links/mia/make", "/speak", "/voice/live", "/tools", "/reset", "/actions/row",
                   "/actions/states", "/actions/prop_0123456789ab/decline", "/actions/prop_0123456789ab/dismiss"):
        for method in ("GET", "POST"):
            answer = await door.request(method, owners, headers={**posting(phone), **forged})
            assert answer.status_code == 404, (method, owners)


def _server_checks():
    """docs/STAFF_LINKS.md server step 4, as (method, path, headers, status, code) per curl line, and
    the paths the documented Caddy site forwards (its `@team path` matcher)."""
    import shlex
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "STAFF_LINKS.md").read_text(encoding="utf-8")
    step = text.split("4. **Check from outside the tailnet**", 1)[1].split("5. **Then a real join", 1)[0]
    forwarded = re.search(r"@team path ([^\n]+)", text).group(1).split()
    checks = []
    for command, status, code in re.findall(r"`(curl [^`]+)` → `(\d{3})`(?: `([a-z_]+)`)?", step):
        words = shlex.split(command.replace("<George's login>", OWNER).replace("team.crooksldn.com", HOST))
        method, headers, url = "GET", {}, ""
        for flag, value in zip(words, words[1:] + [""], strict=True):
            if flag == "-X":
                method = value
            elif flag == "-H":
                name, _, said = value.partition(":")
                headers[name.strip()] = said.strip()
            elif flag.startswith("https://"):
                url = flag
        checks.append((method, "/" + url.split("://", 1)[1].split("/", 1)[1], headers, int(status), code))
    return checks, forwarded


def _caddy_forwards(path: str, forwarded: list[str]) -> bool:
    return any(path == p or (p.endswith("*") and path.startswith(p[:-1])) for p in forwarded)


async def test_the_server_checks_in_the_docs_test_clives_own_door_and_get_what_they_say(door):
    """The review's N4: step 4's checks had only paths Caddy never forwards, which test Caddy and not
    CLIVE. Every documented check on a path Caddy forwards is run here through the door and must get
    exactly the answer the docs promise; the rest must be Caddy's own 404; and CLIVE's door is checked
    on the server with an owner step carrying George's login, a team-page owner step, a route next to
    the cards', and a file the team's pages do not load."""
    checks, forwarded = _server_checks()
    assert len(checks) >= 10, checks
    clives = []
    for method, path, headers, status, code in checks:
        if not _caddy_forwards(path, forwarded):
            assert status == 404, (method, path)                                        # Caddy's `respond 404`
            continue
        answer = await door.request(method, path, headers={**DOOR, **headers})
        assert answer.status_code == status, (method, path, answer.status_code)
        if code:
            assert answer.json()["code"] == code, (method, path)
        if status == 404:
            clives.append((method, path, "Tailscale-User-Login" in headers))
    assert {("POST", "/today/assign", True), ("POST", "/today/people", False), ("GET", "/actions/states", False),
            ("GET", "/static/app.js", False)} <= set(clives), clives


async def test_without_a_phone_signed_in_only_the_pages_and_the_join_answer(door):
    for method, path in sorted(team_door.SIGNED_IN):
        answer = await door.request(method, path, headers=POST)
        assert answer.status_code == 401 and answer.json()["code"] == "signed_out", path
    page = await door.get("/today", headers=DOOR)
    assert page.status_code == 200 and "today.js" in page.text and page.headers["x-frame-options"] == "DENY"
    joining = await door.get("/join", headers=DOOR)
    assert joining.status_code == 200 and "join.js" in joining.text
    assert "content-security-policy" in joining.headers
    front = await door.get("/", headers=DOOR, follow_redirects=False)
    assert front.status_code == 303 and front.headers["location"] == "/today"
    for name in team_door.STATIC:
        assert (await door.get(name, headers=DOOR)).status_code == 200, name


def test_the_door_serves_exactly_the_files_its_two_pages_load():
    from pathlib import Path

    web = Path(__file__).resolve().parent.parent / "web"
    loaded = set()
    for page in ("today.html", "join.html"):
        loaded |= set(re.findall(r'(?:src|href)="(/static/[^"?]+)', (web / page).read_text(encoding="utf-8")))
    assert loaded == set(team_door.STATIC)


def test_the_team_host_is_read_however_it_is_written():
    for written in ("team.crooksldn.com", "https://team.crooksldn.com/", " Team.CROOKSLDN.com "):
        assert team_door.configured_host(written) == "team.crooksldn.com"
    assert team_door._hostname("team.crooksldn.com:443") == "team.crooksldn.com"


def test_the_cards_the_door_lets_through_are_the_engines_own_ids():
    from app.actions.models import new_proposal_id

    for _ in range(20):
        made = new_proposal_id()
        assert team_door.CARD_READ.fullmatch(f"/actions/{made}") and team_door.CARD_STEP.fullmatch(f"/actions/{made}/commit")
    assert not team_door.CARD_READ.fullmatch("/actions/states")


# ------------------------------------------------------------------ nobody through the door is the owner

async def test_through_the_door_nobody_is_the_owner_or_the_server_itself(door):
    """Here a request made on the server itself is the owner (CROOKS_LOCAL_OWNER), as in production's
    worst case. Through the team's door, with no forwarding header, with the owner's own login, with
    the Host alone: never him, never the server."""
    from starlette.requests import Request

    from app.routes import actions as actions_route

    assert (await door.get("/today/state")).json()["me"]["owner"] is True                # the server itself, here
    phone = await join(door)
    for headers in ({"X-Clive-Door": "team"}, {"Host": HOST}, {"X-Forwarded-Host": HOST},
                    {"X-Clive-Door": "team", "Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}):
        bare = await door.get("/today/state", headers=headers)
        assert bare.status_code == 401, headers
        mine = await door.get("/today/state", headers={**headers, "Cookie": f"{links.COOKIE}={phone}"})
        assert mine.status_code == 200 and mine.json()["me"]["owner"] is False and mine.json()["me"]["id"] == "mia"
        assert "routines" not in mine.json() and "links" not in mine.json()
    scope = {"type": "http", "method": "GET", "path": "/today/state", "headers": [(b"x-clive-door", b"team")],
             "app": app, "query_string": b""}
    request = Request(scope)
    assert actions_route.proxy_state(request)[0] == actions_route.TEAM_DOOR
    assert actions_route.principal_verdict(request)[1] == "not_authorised"
    assert actions_route.caller_identity(request) == "team:" and not actions_route.made_on_this_server(request)


async def test_the_door_takes_every_identity_claim_off_what_it_passes_on(door):
    from fastapi.responses import Response
    from starlette.requests import Request

    passed = {}

    async def behind(request):
        passed["headers"] = [name for name, _ in request.scope["headers"]]
        passed["login"] = request.headers.get("tailscale-user-login")
        return Response("ok")

    headers = [(b"x-clive-door", b"team"), (b"host", HOST.encode()), (b"tailscale-user-login", OWNER.encode()),
               (b"Tailscale-User-Name", b"George"), (b"tailscale-user-profile-pic", b"x"), (b"x-crooks-local-key", b"k"),
               (b"x-forwarded-for", b"198.51.100.7")]
    request = Request({"type": "http", "method": "GET", "path": "/today", "headers": headers, "app": app,
                       "query_string": b""})
    request.headers.get("tailscale-user-login")                                          # read once, as a check might
    answer = await team_door.through(request, behind)
    assert answer.status_code == 200 and passed["login"] is None
    assert passed["headers"] == [b"x-clive-door", b"host", b"x-forwarded-for"]
    assert team_door.address(request) == "198.51.100.7"


async def test_a_phone_through_the_door_has_exactly_the_teams_tools_and_its_own_conversation(door):
    assert staff.TOOLS == TEAM_TOOLS
    held = []

    class Staff(FakeProvider):
        async def turn(self, session_id, text):
            held.append(authority.current())
            return TurnResult(text="Your list has one order to pack.", session_id=session_id)

    door.runtime.staff_provider_factory = lambda person: Staff()
    door.runtime.staff_providers.clear()
    phone = await join(door)
    answer = await door.post("/turn", json={"text": "What's mine?", "session_id": "m1"}, headers=posting(phone))
    assert answer.status_code == 200 and answer.json()["answer"] == "Your list has one order to pack."
    assert held[0].kind == authority.STAFF and held[0].who == "mia" and held[0].purpose == "team:mia"
    assert held[0].tools == TEAM_TOOLS and not held[0].permits("shopify_refund_create")
    assert not held[0].active                                                           # revoked with the answer
    owners = await door.post("/turn", json={"text": "Hello", "session_id": "o1"}, headers=PROXIED)
    assert owners.json()["answer"] == "fake answer"
    into_his = await door.post("/turn", json={"text": "What did George say?", "session_id": "o1"}, headers=posting(phone))
    assert into_his.status_code == 403 and into_his.json()["code"] == "wrong_session" and len(held) == 1


async def test_a_phones_tap_makes_only_the_changes_the_team_may_and_in_its_own_name(door, monkeypatch):
    phone = await join(door)
    with authority.acting_as(authority.for_owner(OWNER)):
        proposal = await staged(door, session_id="m1")
    door.runtime.sessions.get_or_create("m1").login = "team:mia"
    refused = await commit(door, proposal.proposal_id, session_id="m1", headers=posting(phone))
    assert refused.status_code == 403 and refused.json()["code"] == "not_yours_to_make"
    assert door.store.mutations == []
    monkeypatch.setattr(staff, "OPERATIONS_WITH_UNDO", frozenset({"order_note_append"}))   # as if the owner had allowed it
    made = await commit(door, proposal.proposal_id, session_id="m1", headers=posting(phone))
    assert made.status_code == 200 and made.json()["status"] == "verified"
    assert proposal.caller == "team:mia" and len(door.store.mutations) == 1


# ------------------------------------------------------------------ cross-site, and the tailnet as it was

async def test_a_post_through_the_door_must_come_from_the_teams_own_page(door):
    phone = await join(door)
    cookie = {"Cookie": f"{links.COOKIE}={phone}"}
    for headers in ({**DOOR, **cookie}, {**DOOR, **cookie, "Origin": "https://evil.example"},
                    {**DOOR, **cookie, "Origin": "null"}, {**posting(phone), "Sec-Fetch-Site": "cross-site"},
                    {**posting(phone), "Sec-Fetch-Site": "same-site"}):
        answer = await door.post("/today/claim", json={"ref": ORDER_REF}, headers=headers)
        assert answer.status_code == 403 and answer.json()["code"] == "cross_site", headers
    token, code, _ = links.make("mia", by="owner")
    assert (await door.post("/join", json={"token": token, "code": code}, headers=DOOR)).status_code == 403
    claimed = await door.post("/today/claim", json={"ref": ORDER_REF}, headers={**posting(phone), "Sec-Fetch-Site": "same-origin"})
    assert claimed.status_code == 200 and claimed.json()["job"]["claimed_by_name"] == "Mia"


async def test_the_tailnet_is_unchanged_and_a_team_cookie_means_nothing_there(door):
    phone = await join(door)
    cookie = {"Cookie": f"{links.COOKIE}={phone}"}
    stranger = {"Tailscale-User-Login": "kit@example.com", "X-Forwarded-For": "100.64.0.8"}
    assert (await door.get("/today/state", headers={**stranger, **cookie})).status_code == 403
    assert (await door.get("/today/state", headers={**AS_MIA, **cookie})).status_code == 403   # her login still waits
    access.approve("mia", login=MIA, by="owner", passkey="pk")
    assert (await door.get("/today/state", headers=AS_MIA)).json()["me"]["id"] == "mia"
    assert (await door.get("/today/state", headers=PROXIED)).json()["me"]["owner"] is True
    local = await door.get("/today/state", headers=cookie)                                # the server itself: not Mia
    assert local.json()["me"]["id"] == "owner"


# ------------------------------------------------------------------ nothing secret in logs or records

async def test_no_link_code_or_cookie_reaches_a_log_or_a_record(door, world, caplog, tmp_path):  # noqa: F811
    from app.connections import ledger
    from app.work.store import work

    caplog.set_level(logging.DEBUG)
    await register(world)
    made = (await world.post("/staff-links/mia/make", headers=HEADERS,
                             json={"approval": await approval(world, "staff-link:make:mia")})).json()
    token = made["link"].split("#", 1)[1]
    await door.post("/join", json={"token": token, "code": f"{(int(made['code']) + 1) % 10 ** 6:06d}"}, headers=POST)
    joined = await door.post("/join", json={"token": token, "code": made["code"]}, headers=POST)
    phone = cookie_of(joined)
    await door.get("/today/state", headers=signed_in(phone))
    await door.get("/connections", headers=signed_in(phone))
    secret = phone.split(".", 1)[1]
    records = json.dumps(ledger.recent()) + json.dumps(work.history(limit=50))
    for text in (token, made["code"], secret, phone):
        assert text not in caplog.text and text not in records, "a secret reached a log or a record"
    assert "phone_joined" in records and "link_made" in records and "staff_phone_joined" in records
