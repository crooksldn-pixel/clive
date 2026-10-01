"""People cards (app/people/store.py), the owner's tools for them (app/people/tools.py), and who on the
team the door may let in (app/people/access.py, door.py)."""

from __future__ import annotations

import json
import stat

import pytest

from app.people import access, door
from app.people.store import PeopleError, PeopleStore, people
from app.people.tools import people_list, person_note
from app.tools import authority
from app.tools.registry import ToolError


@pytest.fixture(autouse=True)
def stores(tmp_path):
    people.configure(tmp_path / "people.json")
    access.configure(state_dir=tmp_path / "secret")
    yield tmp_path
    people.configure(None)
    access.configure(state_dir=None)


@pytest.fixture
def as_owner():
    with authority.acting_as(authority.for_owner("owner@example.com")):
        yield


@pytest.fixture
def as_staff():
    def run(person_id: str):
        return authority.acting_as(authority.for_staff(person_id, f"{person_id}@example.com"))
    return run


# ------------------------------------------------------------------ the cards

def test_a_card_from_the_owners_words_staff_and_contact(stores):
    mia, created = people.note({"name": "Mia", "kind": "staff", "role": "office: daily packing, emails, Instagram",
                                "areas": "packing, email, instagram and warehouse", "login": "Mia@Example.com"})
    assert created and mia.person_id == "mia" and mia.login == "mia@example.com"
    assert mia.areas == ["packing", "email", "instagram", "warehouse"]
    henry, _ = people.note({"name": "Henry Cole", "kind": "contact", "role": "graphic design",
                            "email": "henry@example.com", "instagram": "henrydraws",
                            "uses": "posters and post designs, not product design"})
    assert henry.instagram == "@henrydraws" and henry.login == ""
    assert [p.name for p in people.all()] == ["Mia", "Henry Cole"]          # the team first
    assert people.find("henry") is henry or people.find("henry").person_id == "henry-cole"
    assert stat.S_IMODE((stores / "people.json").stat().st_mode) == 0o600


def test_a_colleague_sees_who_someone_is_not_their_details_or_the_owners_notes(stores):
    henry, _ = people.note({"name": "Henry", "kind": "contact", "email": "henry@example.com", "phone": "07700 900000",
                            "notes": "slow to reply", "uses": "posters"})
    shown = henry.public(for_staff=True)
    assert set(shown) == {"person_id", "name", "kind", "role", "areas", "active"}


@pytest.mark.parametrize("fields, says", [
    ({"name": ""}, "a name is needed"),
    ({"name": "X", "kind": "boss"}, "staff"),
    ({"name": "X", "email": "not-an-email"}, "email"),
    ({"name": "X", "instagram": "has spaces in"}, "Instagram"),
    ({"name": "X", "login": "nope"}, "Tailscale"),
])
def test_what_cannot_be_kept_is_refused_in_words(fields, says):
    with pytest.raises(PeopleError, match=says):
        people.note(fields)


def test_one_login_belongs_to_one_person():
    people.note({"name": "Mia", "kind": "staff", "login": "mia@example.com"})
    with pytest.raises(PeopleError, match="already Mia's"):
        people.note({"name": "Kit", "kind": "staff", "login": "mia@example.com"})


def test_a_contact_has_no_login_even_if_one_was_given(stores):
    person, _ = people.note({"name": "Rosa", "kind": "staff", "login": "rosa@example.com"})
    person, _ = people.note({"name": "Rosa", "kind": "contact"})
    assert person.login == ""


def test_an_unreadable_record_is_a_refusal_never_an_empty_team(stores):
    (stores / "people.json").write_text("{not json")
    with pytest.raises(PeopleError):
        people.all()
    assert PeopleStore(None).all() == []


# ------------------------------------------------------------------ the owner's tools

async def test_person_note_is_the_owners_and_a_staff_login_waits_for_his_passkey(as_owner):
    out = await person_note(name="Mia", kind="staff", role="office", login="mia@example.com")
    assert out["created"] and out["person"]["access"] == "pending"
    assert "approve their login with your passkey" in out["next"]
    assert access.state("mia") == "pending" and access.person_for_login("mia@example.com") == ""


async def test_a_staff_member_cannot_keep_cards(as_staff):
    with as_staff("mia"):
        with pytest.raises(ToolError, match="Only the owner"):
            await person_note(name="Kit", kind="staff")


async def test_people_list_shows_the_owner_access_and_a_colleague_much_less(as_owner, as_staff):
    await person_note(name="Mia", kind="staff", login="mia@example.com", phone="07700 900000")
    owner_view = await people_list()
    assert owner_view["people"][0]["access"] == "pending" and owner_view["people"][0]["phone"]
    with as_staff("mia"):
        theirs = await people_list(who="mia")
    assert "phone" not in theirs["people"][0] and "access" not in theirs["people"][0]


async def test_taking_someone_off_closes_the_door_at_once(as_owner):
    await person_note(name="Mia", kind="staff", login="mia@example.com")
    access.approve("mia", login="mia@example.com", by="owner", passkey="pk")
    assert access.person_for_login("mia@example.com") == "mia"
    out = await person_note(name="Mia", active=False)
    assert out["person"]["access"] == "suspended" and access.person_for_login("mia@example.com") == ""


# ------------------------------------------------------------------ access

def test_access_ladder_and_a_changed_login_is_asked_again(stores):
    assert access.ask("mia", "mia@example.com") == "pending"
    access.approve("mia", login="mia@example.com", by="owner", passkey="pk")
    assert access.person_for_login("MIA@example.com") == "mia"
    assert access.ask("mia", "mia@example.com") == "active"          # the same login stays let in
    assert access.ask("mia", "mia.new@example.com") == "pending"     # a new one waits again
    assert access.person_for_login("mia@example.com") == "" and access.person_for_login("mia.new@example.com") == ""
    grants = json.loads((stores / "secret" / "access.json").read_text())["grants"]
    assert grants["mia"]["status"] == "pending"
    assert stat.S_IMODE((stores / "secret" / "access.json").stat().st_mode) == 0o600


def test_approving_needs_a_login_and_an_unreadable_record_lets_nobody_in(stores):
    with pytest.raises(access.AccessError):
        access.approve("nobody", login="nobody@example.com", by="owner", passkey="pk")
    access.ask("mia", "mia@example.com")
    access.approve("mia", login="mia@example.com", by="owner", passkey="pk")
    (stores / "secret" / "access.json").write_text("garbage")
    assert access.person_for_login("mia@example.com") == ""


def test_the_door_lets_in_only_an_active_staff_card_with_the_same_login(stores):
    people.note({"name": "Mia", "kind": "staff", "login": "mia@example.com"})
    access.ask("mia", "mia@example.com")
    assert door.staff_login("mia@example.com") == ""                 # pending
    access.approve("mia", login="mia@example.com", by="owner", passkey="pk")
    assert door.staff_login("mia@example.com") == "mia"
    people.note({"name": "Mia", "active": False})
    assert door.staff_login("mia@example.com") == ""                 # taken off the list
    people.note({"name": "Mia", "active": True, "kind": "contact"})
    assert door.staff_login("mia@example.com") == ""                 # no longer staff


def test_an_approval_lets_in_only_the_login_it_was_given_for(stores):
    """The 1 October review (M1): the owner approves a person with the login he was shown. A login
    changed after that (person_note, a mis-heard sentence, a line in an email) is not let in on it."""
    access.ask("mia", "mia@example.com")
    access.ask("mia", "someone.else@example.net")                  # changed before his passkey landed
    with pytest.raises(access.AccessError, match="no longer the one waiting"):
        access.approve("mia", login="mia@example.com", by="owner", passkey="pk")
    assert access.state("mia") == "pending"
    assert access.person_for_login("someone.else@example.net") == "" and access.person_for_login("mia@example.com") == ""
    with pytest.raises(access.AccessError):
        access.approve("mia", login="", by="owner", passkey="pk")
    access.approve("mia", login="Someone.Else@example.net", by="owner", passkey="pk")   # the one he saw, any case
    assert access.person_for_login("someone.else@example.net") == "mia"


@pytest.mark.parametrize("name, given", [("Owner", "owner-2"), ("CLIVE", "clive-2"), ("Local", "local-2")])
def test_a_person_never_takes_an_id_that_already_means_someone_else(name, given):
    """"owner" is George in the work list and its record: a member of the team called Owner would
    otherwise release his claims, read his record and have their changes recorded as his."""
    person, created = people.note({"name": name, "kind": "staff", "login": f"{given}@example.com"})
    assert created and person.person_id == given
    assert people.get("owner") is None


def test_a_card_written_under_a_reserved_id_is_never_anyone(stores):
    (stores / "people.json").write_text(json.dumps({"version": 1, "people": [
        {"person_id": "owner", "name": "Owner", "kind": "staff", "login": "x@example.com"}]}))
    assert people.get("owner") is None and people.all() == []
