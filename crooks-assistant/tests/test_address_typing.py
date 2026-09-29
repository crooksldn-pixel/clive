"""Correcting a delivery address with a thumb (§20, D-9).

The live session: four recordings under 150 ms, two transcripts the normaliser had to repair,
and an owner asking out loud how to type. The one exact value that appears in the fixture
world by name is an address with the house number missing — and the only way to put it right
was a sentence into that microphone.

What these hold is the shape, which is the same one the composer keeps: the tablet posts a
field NAME and the characters; the Mac validates them into its own copy; the execution
arguments are built HERE when a gesture asks for them; and the workspace starts from the
address as it stands, because correcting a house number is not re-entering an address.
"""

from __future__ import annotations

import pytest

from app.families import _workspace as ws
from app.families import address as family
from app.session.branch import Branch
from app.session.models import Session

ORDER_ID = "gid://shopify/Order/1936"
ORDER = {
    "order_id": ORDER_ID, "order_number": "CROOKS-1936", "fulfillment": "UNFULFILLED",
    "payment": "PAID", "fulfillments": [],
    "shipping_address": {
        "name": "Millie Fenwick", "lines": ["Sefton Park Road"], "city": "Bristol",
        "zip": "BS7 9AL", "country_code": "GB", "province_code": None,
    },
}


@pytest.fixture
def branch() -> Branch:
    return Branch(branch_id="br_address", session_id="s_address")


@pytest.fixture
def session() -> Session:
    return Session(session_id="s_address")


def _ctx(session, branch, **args):
    from app.commands import Ctx

    return Ctx(None, session, branch, args)


def _hold(session, order=None, *, order_id: str = ORDER_ID) -> None:
    from app.memory import ENTITY
    from app.memory import current as memory

    memory().put(ENTITY, f"order:{order_id}", dict(order if order is not None else ORDER), source="shopify")
    session.issue(order_id)


def _open(session, branch, **args):
    from app import commands

    return commands.run("address.open", _ctx(session, branch, order_id=ORDER_ID, **args))


# ------------------------------------------------------------------ the way in


def test_the_address_chip_opens_a_typing_path_and_not_a_microphone():
    from app.actions.available import available_actions

    caps = {"order_shipping_address_set": {"state": "ready"}}
    chip = next(a for a in available_actions(ORDER, caps) if a["id"] == "address")
    assert chip["mode"] == "open"
    assert chip["command"] == "address.open"
    assert chip["args"] == f"order_id={ORDER_ID}"
    # The spoken control still rides along, for the owner who would rather say it.
    assert chip["family"] == "order.change_address"


def test_an_order_with_no_id_falls_back_to_priming_the_words():
    from app.actions.available import available_actions

    caps = {"order_shipping_address_set": {"state": "ready"}}
    bare = {k: v for k, v in ORDER.items() if k != "order_id"}
    chip = next(a for a in available_actions(bare, caps) if a["id"] == "address")
    assert chip["mode"] == "ask" and not chip["command"]


def test_opening_it_starts_from_the_address_as_it_stands(branch, session):
    """The whole reason it is worth having: four characters typed, not an address retyped."""
    _hold(session)
    out = _open(session, branch)
    assert out.ok, out.detail
    data = out.surfaces[0].as_ui()["data"]
    values = {f["name"]: f["value"] for f in data["fields"]}
    assert values["address1"] == "Sefton Park Road"
    assert values["city"] == "Bristol"
    assert values["postcode"] == "BS7 9AL"
    assert values["country_code"] == "GB"
    assert values["name"] == "Millie Fenwick"
    assert data["field_command"] == "address.field"
    assert any("Tap any line to type" in n for n in data["notes"]), data["notes"]


def test_it_reads_nothing_and_stages_nothing(branch, session):
    _hold(session)
    out = _open(session, branch)
    assert out.calls == []
    assert "stage" not in out.changed


def test_every_field_has_a_kind_the_tablet_can_draw(branch, session):
    from pathlib import Path

    _hold(session)
    data = _open(session, branch).surfaces[0].as_ui()["data"]
    drawn = (Path(__file__).resolve().parents[1] / "web" / "ui.js").read_text()
    for spec in data["fields"]:
        assert f"    {spec['kind']}:" in drawn or f"{spec['kind']}:" in drawn, spec["kind"]
    assert {f["kind"] for f in data["fields"]} <= {"text", "address", "code"}


def test_the_tablet_cannot_open_an_order_it_was_never_given(branch, session):
    from app import commands
    from app.memory import ENTITY
    from app.memory import current as memory

    memory().put(ENTITY, "order:gid://shopify/Order/9999", dict(ORDER, order_id="gid://shopify/Order/9999"),
                 source="shopify")
    out = commands.run("address.open", _ctx(session, branch, order_id="gid://shopify/Order/9999"))
    assert not out.ok and out.code == "not_this_conversation"
    assert getattr(branch, "workspace", None) is None


def test_an_order_the_mac_has_dropped_says_so(branch, session):
    from app import commands

    session.issue("gid://shopify/Order/4242")
    out = commands.run("address.open", _ctx(session, branch, order_id="gid://shopify/Order/4242"))
    assert not out.ok and out.code == "order_not_held"


def test_opening_it_leaves_the_order_as_where_the_owner_is(branch, session):
    _hold(session)
    _open(session, branch)
    assert (branch.entity or {}).get("kind") == "order"
    assert (branch.entity or {}).get("ref") == ORDER_ID


# --------------------------------------------------------------- what may be typed


@pytest.mark.parametrize(("field", "typed", "value", "status"), [
    ("postcode", " bs7 8al ", "BS7 8AL", "ok"),
    ("postcode", "bs7", "BS7", "ok"),
    ("postcode", "", "", "invalid"),
    ("postcode", "no idea, sorry!", "NO IDEA, SOR", "invalid"),
    ("country_code", "gb", "GB", "ok"),
    # Truncated, never accepted: "BR" is Brazil, and a card that showed it as ok would
    # have sent a hoodie to the other side of the world.
    ("country_code", "britain", "BR", "invalid"),
    ("province_code", "", "", "ok"),
    ("province_code", "eng", "ENG", "ok"),
    ("province_code", "the north", "THENO", "invalid"),
    ("address1", "  41   Sefton Park Road ", "41 Sefton Park Road", "ok"),
    ("address1", "   ", "", "invalid"),
    ("city", "Bristol", "Bristol", "ok"),
    ("city", "", "", "invalid"),
])
def test_a_typed_value_is_validated_into_the_macs_own_copy(branch, session, field, typed, value, status):
    from app import commands

    _hold(session)
    ident = _open(session, branch).changed["workspace_id"]
    out = commands.run("address.field", _ctx(session, branch, workspace_id=ident, field=field, value=typed))
    assert out.ok, out.detail
    assert ws.value(branch.workspace, field) == value
    assert ws.status(branch.workspace, field) == status
    assert out.changed["status"] == status
    # And the card says what the Mac made of it, which is the only thing the owner can act on.
    drawn = {f["name"]: f for f in out.surfaces[0].as_ui()["data"]["fields"]}
    assert drawn[field]["value"] == value and drawn[field]["status"] == status
    if status == "invalid":
        assert drawn[field]["hint"], "invalid with no reason is a dead end"


def test_the_tablet_cannot_name_a_key_of_the_macs_own_dictionary(branch, session):
    from app import commands

    _hold(session)
    ident = _open(session, branch).changed["workspace_id"]
    for field in ("facts", "staged", "at", "values", "order_id", "why_not", ""):
        out = commands.run("address.field", _ctx(session, branch, workspace_id=ident, field=field, value="x"))
        assert not out.ok and out.code == "unknown_field", field
    assert ws.fact(branch.workspace, "order_id") == ORDER_ID


def test_typing_into_an_address_that_is_not_there_is_refused(branch, session):
    from app import commands

    out = commands.run("address.field", _ctx(session, branch, workspace_id="adr_nothing",
                                             field="postcode", value="BS7 9AL"))
    assert not out.ok and out.code == "no_workspace"


# --------------------------------------------------------------------- the gesture


def _typed(session, branch, fields: dict[str, str]) -> str:
    from app import commands

    ident = _open(session, branch).changed["workspace_id"]
    for name, typed in fields.items():
        commands.run("address.field", _ctx(session, branch, workspace_id=ident, field=name, value=typed))
    return ident


def test_the_gesture_names_the_tool_and_the_arguments_the_mac_built(branch, session):
    from app import commands

    _hold(session)
    ident = _typed(session, branch, {"address1": "41 Sefton Park Road"})
    out = commands.run("address.stage", _ctx(session, branch, workspace_id=ident))
    assert out.ok, out.detail
    staged = out.changed["stage"]
    assert staged["tool"] == "shopify_order_shipping_address_set"
    # Only what he changed, and the second line a new street takes with it (round 13, F/F-01):
    # the tool keeps every part it is not given exactly as the order has it.
    assert staged["args"] == {
        "order_id": ORDER_ID, "address1": "41 Sefton Park Road", "address2": "", "from_owner": True,
    }
    assert not out.calls, "the command itself must not prepare anything"


def test_the_tool_it_names_is_a_reviewed_write_tool_of_this_build():
    import app.tools.shopify_writes  # noqa: F401 — registers the tool this family names
    from app.tools import registry

    spec = registry.get(family.WRITE_TOOL)
    assert spec.write is not None and spec.write.complete
    assert spec.write.operation == "order_shipping_address_set"
    # Every argument the staging builds is one the tool actually takes.
    taken = set(spec.input_schema["properties"])
    built = {"order_id", "address1", "address2", "city", "postcode", "country_code",
             "province_code", "name", "from_owner"}
    assert built <= taken, built - taken


def test_an_address_that_has_not_changed_is_not_a_change(branch, session):
    from app import commands

    _hold(session)
    ident = _open(session, branch).changed["workspace_id"]
    out = commands.run("address.stage", _ctx(session, branch, workspace_id=ident))
    assert not out.ok and out.code == "not_ready"
    assert "changed" in out.detail.lower()


@pytest.mark.parametrize(("field", "typed"), [
    ("postcode", "not a postcode!"), ("address1", ""), ("city", ""), ("country_code", "x"),
])
def test_a_value_the_mac_refused_cannot_be_prepared(branch, session, field, typed):
    from app import commands

    _hold(session)
    ident = _typed(session, branch, {"address1": "41 Sefton Park Road", field: typed})
    out = commands.run("address.stage", _ctx(session, branch, workspace_id=ident))
    assert not out.ok and out.code == "not_ready"
    assert out.detail, "a refusal with no words is a dead end"


def test_a_shipped_or_cancelled_order_says_so_before_a_word_is_typed(branch, session):
    for order, word in (
        (dict(ORDER, fulfillment="FULFILLED", fulfillments=[{"status": "SUCCESS"}]), "shipped"),
        (dict(ORDER, cancelled_at="2026-09-08T10:00:00Z"), "cancelled"),
        ({k: v for k, v in ORDER.items() if k != "shipping_address"}, "no delivery address"),
    ):
        from app import commands

        _hold(session, order)
        out = _open(session, branch)
        assert out.ok, out.detail
        blocked = out.surfaces[0].as_ui()["data"]["blocked"]
        assert word in blocked.lower(), blocked
        staged = commands.run("address.stage", _ctx(session, branch,
                                                    workspace_id=out.changed["workspace_id"]))
        assert not staged.ok and staged.code == "not_ready"


def test_a_blocked_address_cannot_be_prepared_from_the_card_either(branch, session):
    _hold(session, dict(ORDER, fulfillment="FULFILLED", fulfillments=[{"status": "SUCCESS"}]))
    data = _open(session, branch).surfaces[0].as_ui()["data"]
    prepare = next(a for a in data["actions"] if a["id"] == "prepare")
    assert prepare["enabled"] is False, "a button the Mac would refuse must not be pressable"


def test_an_address_from_another_conversation_cannot_be_staged(branch, session):
    from app import commands

    _hold(session)
    ident = _typed(session, branch, {"address1": "41 Sefton Park Road"})
    session.issued_ids = frozenset(x for x in session.issued_ids if x != ident)
    out = commands.run("address.stage", _ctx(session, branch, workspace_id=ident))
    assert not out.ok and out.code == "not_held"


def test_discarding_leaves_nothing_behind(branch, session):
    from app import commands

    _hold(session)
    ident = _typed(session, branch, {"address1": "41 Sefton Park Road"})
    out = commands.run("address.discard", _ctx(session, branch, workspace_id=ident))
    assert out.ok and getattr(branch, "workspace", None) is None
    again = commands.run("address.stage", _ctx(session, branch, workspace_id=ident))
    assert not again.ok and again.code == "no_workspace"


def test_none_of_these_commands_can_be_spoken():
    from app import commands

    for name in ("address.open", "address.field", "address.stage", "address.discard"):
        spec = commands.get(name)
        assert spec is not None and spec.voice is False and spec.touch is True, name


def test_the_address_and_the_postcode_are_remembered_as_personal_data(branch, session):
    _hold(session)
    _typed(session, branch, {"address1": "41 Sefton Park Road"})
    assert "41 Sefton Park Road" in session.pii_seen
    assert "BS7 9AL" in session.pii_seen
