"""Named routines (ruling 31, DEC-074): saved steps started by name, and nothing run that a card did not hold.

George, 8 October 2026: "routines" are saved multi-step jobs he starts by name. "Save this as my
Friday drop routine" keeps the steps; "run my Friday drop routine" hands them to the model, which
calls each one through the gate as it would if he had asked in words: the reads run, and every
change is staged as a card for his gesture, never executed.

Held here: the store (private, proved by reading back, never mistaking an unreadable file for an
empty one, each person's own); the tools (a step checked against the registry, the gate and the
asker's own tools, an id never kept, a read or a change decided by the registry and not the model);
the run (each step handed over, a step that cannot run now marked with why); the card (each step as
the turn left it, matched by tool and order); and one end-to-end turn pair through the real /turn,
gate, action engine and presenters, with the model scripted (`experience/harness.py`).
"""

from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest

from app.people import staff as staff_rules
from app.providers.base import ToolCall
from app.tools import (  # noqa: F401 - registers the tools the steps name, and the test tools a step must not be
    authority,
    gate,
    gmail_tools,
    mock,
    registry,
    shopify_tools,
    shopify_writes,
)
from app.tools.registry import ToolError
from app.work import routine_cards, routine_tools
from app.work import tools as work_tools
from app.work.routines import (
    FILE,
    MAX_EACH,
    MAX_STEPS,
    NamedRoutine,
    RoutineBook,
    RoutineError,
    Step,
    book,
    clean_name,
    key_of,
)
from app.work.store import work

ORDER = "gid://shopify/Order/1940"


@pytest.fixture(autouse=True)
def folder(tmp_path):
    work.configure(tmp_path / "work")
    yield tmp_path / "work"
    work.configure(None)
    work_tools.bind(None)


def owner():
    return authority.acting_as(authority.for_owner("owner@example.com"))


def staff(person_id: str = "p_mia"):
    return authority.acting_as(authority.for_staff(person_id, f"{person_id}@example.com"))


def step(tool="shopify_list_orders", say="Today's orders", **args):
    return {"tool": tool, "say": say, "args": args}


FRIDAY = [
    step("shopify_list_orders", "This week's orders", days=7),
    step("gmail_search", "Who wrote today", query="newer_than:1d"),
    step("shopify_order_note_append", "Note 1940: packed first", order_id=ORDER, note="Packed first"),
]


async def save(name="Friday drop", steps=None):
    return await routine_tools.routine_note(action="save", name=name, steps=FRIDAY if steps is None else steps)


# ------------------------------------------------------------------ the store


def test_a_name_is_kept_without_my_or_routine_and_matched_by_its_words():
    assert clean_name("  my   Friday drop routine ") == "Friday drop"
    assert clean_name("The Monday check") == "Monday check"
    assert key_of("Friday-drop!") == key_of("friday drop") == "friday drop"
    with pytest.raises(RoutineError, match="say what the routine is called"):
        clean_name("my routine")


def test_a_routine_is_kept_private_beside_the_work_list_and_proved_by_reading_it_back(folder):
    made = book.save("owner", "Friday drop", [Step("shopify_list_orders", "Today's orders", {"days": 1}, "read")])
    path = folder / FILE
    assert path.exists() and stat.S_IMODE(path.stat().st_mode) == 0o600
    kept = json.loads(path.read_text())["routines"]
    assert [r["name"] for r in kept] == ["Friday drop"] and kept[0]["who"] == "owner"
    assert book.find("owner", "my friday drop routine").routine_id == made.routine_id
    assert book.find("owner", "friday").routine_id == made.routine_id


def test_an_unreadable_file_is_said_and_never_taken_for_no_routines(folder):
    book.save("owner", "Friday drop", [])
    (folder / FILE).write_text("{not json")
    with pytest.raises(RoutineError, match="could not be read"):
        book.of("owner")
    with pytest.raises(RoutineError, match="could not be read"):
        book.save("owner", "Monday check", [])
    assert (folder / FILE).read_text() == "{not json", "nothing was written over what could not be read"


def test_a_change_that_does_not_read_back_is_an_error(folder, monkeypatch):
    shelf = RoutineBook(work)
    monkeypatch.setattr(shelf, "_keep", lambda routines: None)      # a write that never lands
    with pytest.raises(RoutineError, match="could not be saved"):
        shelf.save("owner", "Friday drop", [])


def test_each_persons_routines_are_their_own():
    book.save("owner", "Friday drop", [])
    book.save("p_mia", "Packing", [])
    assert [r.name for r in book.of("owner")] == ["Friday drop"]
    assert [r.name for r in book.of("p_mia")] == ["Packing"]
    with pytest.raises(RoutineError, match="there is no routine called Friday drop; the saved ones are Packing"):
        book.find("p_mia", "Friday drop")
    with pytest.raises(RoutineError, match="nobody is asking"):
        book.of("")


def test_two_routines_that_could_be_meant_are_named_never_chosen():
    book.save("owner", "Friday drop", [])
    book.save("owner", "Friday restock", [])
    with pytest.raises(RoutineError, match="that could be Friday drop or Friday restock; say which"):
        book.find("owner", "friday")
    assert book.find("owner", "friday drop").name == "Friday drop"


def test_the_bounds_on_a_routine():
    with pytest.raises(RoutineError, match=f"at most {MAX_STEPS} steps"):
        book.save("owner", "Long", [Step("shopify_list_orders", "x")] * (MAX_STEPS + 1))
    with pytest.raises(RoutineError, match="at most 60 characters"):
        book.save("owner", "x" * 61, [])
    with pytest.raises(RoutineError, match="details are at most"):
        book.save("owner", "Big", [Step("gmail_search", "x", {"query": "y" * 1200})])
    for n in range(MAX_EACH):
        book.save("owner", f"Routine {n}", [])
    with pytest.raises(RoutineError, match=f"already {MAX_EACH} routines"):
        book.save("owner", "One more", [])
    with pytest.raises(RoutineError, match="already a routine called Routine 1"):
        book.change("owner", "Routine 2", new_name="routine 1")


# ------------------------------------------------------------------ keeping a routine


async def test_save_checks_each_step_and_keeps_no_id():
    with owner():
        said = await save()
    routine = said["routine"]
    assert said["said"] == "Saved" and routine["name"] == "Friday drop"
    assert [(s["tool"], s["kind"]) for s in routine["steps"]] == [
        ("shopify_list_orders", "read"), ("gmail_search", "read"), ("shopify_order_note_append", "change")]
    assert routine["steps"][2]["args"] == {"note": "Packed first"}, "the order's id is looked up again each run"
    assert said["ids_not_kept"] == ["step 3: order_id"]
    assert ORDER not in json.dumps(book.of("owner")[0].public())


async def test_a_step_is_a_read_or_a_change_by_the_registry_not_by_what_the_model_said():
    with owner():
        said = await save(steps=[{**step("shopify_order_note_append", "Note it", note="x"), "kind": "read"}])
    assert said["routine"]["steps"][0]["kind"] == "change"


@pytest.mark.parametrize(("tool", "why"), [
    ("shopify_no_such_thing", "CLIVE has no tool by that name"),
    ("mock_echo", "that is a test tool"),
    ("routine_run", "a routine cannot start a routine"),
])
async def test_a_step_the_gate_would_not_take_is_refused_when_it_is_saved(tool, why):
    with owner(), pytest.raises(ToolError, match=why):
        await save(steps=[step(tool, "x")])
    assert book.of("owner") == []


async def test_a_read_the_gate_does_not_know_is_refused_when_it_is_saved():
    @registry.tool(name="routine_probe_unlisted", description="x", input_schema={"type": "object", "properties": {}})
    async def _unlisted() -> dict:
        return {}

    try:
        with owner(), pytest.raises(ToolError, match="the gate does not run that tool"):
            await save(steps=[step("routine_probe_unlisted", "x")])
    finally:
        registry._REGISTRY.pop("routine_probe_unlisted", None)


async def test_an_argument_the_tool_does_not_take_is_refused():
    with owner(), pytest.raises(ToolError, match="shopify_list_orders does not take an argument called colour"):
        await save(steps=[step("shopify_list_orders", "x", colour="red")])


async def test_a_step_must_say_what_it_does():
    with owner(), pytest.raises(ToolError, match="Say what each step does"):
        await save(steps=[step("shopify_list_orders", "   ")])


async def test_nobody_asking_is_refused():
    with pytest.raises(ToolError, match="Nobody is asking"):
        await save()


async def test_a_member_of_the_team_keeps_routines_only_with_their_own_tools():
    with staff():
        said = await save("Packing", [step("shopify_list_orders", "Orders to pack", days=1),
                                      step("shopify_order_fulfil", "Fulfil the order I packed")])
        assert [s["kind"] for s in said["routine"]["steps"]] == ["read", "change"]
        with pytest.raises(ToolError, match="that is not one of your tools"):
            await save("Refunds", [step("shopify_refund_create", "Refund the return")])
        with pytest.raises(ToolError, match="that is not one of your tools"):
            await save("Cancels", [step("shopify_order_cancel", "Cancel the unpaid one")])
    with owner():
        assert (await routine_tools.routine_list())["routines"] == [], "the owner sees his own, not hers"


async def test_he_builds_a_routine_step_by_step_and_edits_it():
    with owner():
        await save("Monday check", [])
        said = await routine_tools.routine_note(action="add", name="monday check", steps=[step("shopify_list_orders", "Today's orders", days=1)])
        assert said["said"] == "Added step 1"
        said = await routine_tools.routine_note(action="add", name="monday check", at=1,
                                                steps=[step("gmail_search", "Who wrote", query="newer_than:1d")])
        assert said["said"] == "Added step 1" and [s["say"] for s in said["routine"]["steps"]] == ["Who wrote", "Today's orders"]
        said = await routine_tools.routine_note(action="move", name="monday check", at=2, to=1)
        assert said["said"] == "Moved step 2 to 1" and [s["say"] for s in said["routine"]["steps"]] == ["Today's orders", "Who wrote"]
        said = await routine_tools.routine_note(action="change", name="monday check", at=2,
                                                steps=[step("gmail_search", "Who wrote this week", query="newer_than:7d")])
        assert said["routine"]["steps"][1] == {"tool": "gmail_search", "say": "Who wrote this week",
                                               "args": {"query": "newer_than:7d"}, "kind": "read"}
        said = await routine_tools.routine_note(action="drop", name="monday check", at=1)
        assert said["said"] == "Took out step 1" and len(said["routine"]["steps"]) == 1
        with pytest.raises(ToolError, match="There is no step 4; it has 1"):
            await routine_tools.routine_note(action="drop", name="monday check", at=4)
        said = await routine_tools.routine_note(action="rename", name="monday check", new_name="Monday inbox")
        assert said["routine"]["name"] == "Monday inbox"
        shown = await routine_tools.routine_list(name="monday inbox")
        assert shown["view"] == "one" and shown["routine"]["steps"][0]["say"] == "Who wrote this week"
        gone = await routine_tools.routine_note(action="forget", name="monday inbox")
        assert gone["said"] == "Forgot Monday inbox" and gone["routines"] == []
        assert gone["forgotten"]["steps"][0]["tool"] == "gmail_search", "what was forgotten can be saved again"
    assert book.of("owner") == []


# ------------------------------------------------------------------ running one


async def test_run_hands_over_the_steps_and_executes_nothing(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(registry, "invoke", lambda *a, **k: called.append(a[0]))
    with owner():
        await save()
        run = await routine_tools.routine_run(name="my friday drop routine")
    assert run["view"] == "run" and run["routine"]["name"] == "Friday drop"
    assert [(r["step"], r["tool"], r["change"]) for r in run["run"]] == [
        (1, "shopify_list_orders", False), (2, "gmail_search", False), (3, "shopify_order_note_append", True)]
    assert run["run"][2]["args"] == {"note": "Packed first"} and "skip" not in run["run"][2]
    assert "only ever prepared as a card" in run["do"] and "find the record first" in run["do"]
    assert called == [], "routine_run calls no tool: each step is the model's own call, through the gate"
    kept = book.of("owner")[0]
    assert kept.runs == 1 and kept.last_ran_at


async def test_a_step_that_cannot_run_now_is_marked_with_why():
    runtime = SimpleNamespace(settings=SimpleNamespace(writes_enabled=False), withheld_by_family=lambda: {"gmail_search"})
    work_tools.bind(runtime)
    with owner():
        await save()
        run = await routine_tools.routine_run(name="friday drop")
    assert "skip" not in run["run"][0]
    assert run["run"][1]["skip"] == "that part of CLIVE is not connected right now"
    assert run["run"][2]["skip"] == "changes are switched off on this server"


async def test_a_staff_step_the_owner_has_since_taken_away_is_skipped(monkeypatch):
    with staff():
        await save("Packing", [step("shopify_list_orders", "Orders to pack", days=1),
                               step("shopify_order_fulfil", "Fulfil the order I packed")])
        monkeypatch.setattr(staff_rules, "TOOLS", staff_rules.TOOLS - {"shopify_order_fulfil"})
        run = await routine_tools.routine_run(name="packing")
    assert "skip" not in run["run"][0] and run["run"][1]["skip"] == "that is not one of your tools"


async def test_an_empty_or_unknown_routine_is_said():
    with owner():
        with pytest.raises(ToolError, match="There are no routines saved yet"):
            await routine_tools.routine_run(name="friday drop")
        await save("Monday check", [])
        with pytest.raises(ToolError, match="Monday check has no steps yet"):
            await routine_tools.routine_run(name="monday check")
        with pytest.raises(ToolError, match="There is no routine called sunday; the saved ones are Monday check"):
            await routine_tools.routine_run(name="sunday")


# ------------------------------------------------------------------ the gate and who may call them


def test_the_routine_tools_are_on_the_gate_as_reads_of_clives_own_records():
    for name in routine_tools.TOOLS:
        assert name in gate._KNOWN_TOOLS and not gate._looks_like_mutation(name) and name not in gate._PII_TOOLS
        decision = gate.classify(name, {"name": "friday drop", "action": "save"})
        assert decision.executes and decision.tier is gate.Tier.GREEN
        assert staff_rules.may_call(name), "a member of the team keeps their own"
        assert not authority.service_read(name), "never work that runs on after his answer"


# ------------------------------------------------------------------ the card


def _call(name, ok=True, proposal_id=None, result=None):
    return ToolCall(name=name, args={}, ok=ok, proposal_id=proposal_id, result=result or {"ok": True})


def _run_result():
    return {"view": "run", "routine": {"name": "Friday drop", "steps": []}, "run": [
        {"step": 1, "say": "This week's orders", "tool": "shopify_list_orders", "change": False},
        {"step": 2, "say": "Who wrote today", "tool": "gmail_search", "change": False},
        {"step": 3, "say": "Note 1940", "tool": "shopify_order_note_append", "change": True},
        {"step": 4, "say": "Track it", "tool": "track_parcel", "change": False, "skip": "that part of CLIVE is not connected right now"},
        {"step": 5, "say": "Today's orders again", "tool": "shopify_list_orders", "change": False},
    ]}


def test_the_run_card_says_each_step_as_the_turn_left_it():
    later = [_call("shopify_list_orders"), _call("gmail_search", ok=False), _call("shopify_find_order"),
             _call("shopify_order_note_append", proposal_id="prop_1")]
    data = routine_cards.card("routine_run", _run_result(), later)
    assert data["view"] == "run" and data["title"] == "Friday drop"
    assert [(s["n"], s["state"]) for s in data["steps"]] == [
        (1, "done"), (2, "failed"), (3, "waiting"), (4, "skipped"), (5, "not_done")]
    assert data["steps"][3]["why"] == "that part of CLIVE is not connected right now"
    assert data["counts"]["done"] == 1 and data["counts"]["not_done"] == 1


def test_a_wrong_turning_put_right_counts_as_the_step_done():
    later = [_call("shopify_list_orders"), _call("gmail_search", ok=False), _call("gmail_search")]
    states = [s["state"] for s in routine_cards.card("routine_run", _run_result(), later)["steps"]]
    assert states[:2] == ["done", "done"]


def test_before_the_run_is_known_no_step_is_said_to_be_not_done():
    states = {s["state"] for s in routine_cards.card("routine_run", _run_result(), None)["steps"]}
    assert states == {"pending", "skipped"}


def test_the_lookups_on_the_way_to_a_change_are_known_and_a_second_routine_starts_its_own_count():
    calls = [_call("routine_run", result=_run_result()), _call("shopify_list_orders"), _call("gmail_search"),
             _call("shopify_find_order"), _call("shopify_order_note_append", proposal_id="prop_1"),
             _call("routine_run", result={"view": "run", "routine": {}, "run": []}), _call("shopify_find_order")]
    assert routine_cards.lookups_on_the_way(calls) == frozenset({3, 6})
    assert routine_cards.ran(calls)
    assert not routine_cards.ran([_call("routine_list")])


def test_a_routine_screen_keeps_every_card_with_the_change_first():
    items = [{"type": "order_list", "data": {}}, {"type": "routine", "data": {}}, {"type": "email_list", "data": {}},
             {"type": "confirmation", "data": {}}]
    why: dict = {}
    assert [i["type"] for i in routine_cards.answer_cards(items, why)] == ["confirmation", "routine", "order_list", "email_list"]
    assert why == {"rule": "routine", "set_aside": []}


def test_the_list_and_one_views():
    with_two = {"view": "list", "routines": [
        NamedRoutine("nr_00000001", "Friday drop", "owner", [Step("a", "One", {}, "read"), Step("b", "Two", {}, "change")]).public(),
        NamedRoutine("nr_00000002", "Monday check", "owner", []).public()]}
    data = routine_cards.card("routine_list", with_two, [])
    assert data["routines"][0] == {"name": "Friday drop", "count": 2, "changes": 1, "says": ["One", "Two"], "more": 0}
    one = routine_cards.card("routine_note", {"view": "one", "said": "Saved", "ids_not_kept": ["step 1: order_id"],
                                              "routine": with_two["routines"][0]}, [])
    assert one["steps"] == [{"n": 1, "say": "One", "kind": "read"}, {"n": 2, "say": "Two", "kind": "change"}]
    assert one["looked_up"] is True and one["said"] == "Saved"


# ------------------------------------------------------------------ one save and one run, end to end


FRIDAY_SAID = [
    {"tool": "shopify_list_orders", "args": {"days": 1}, "say": "Today's orders"},
    {"tool": "gmail_search", "args": {"query": "newer_than:1d"}, "say": "Who wrote today"},
    {"tool": "shopify_order_note_append", "args": {"order_id": ORDER, "note": "Friday drop: pack first"},
     "say": "Note on 1940: pack it first"},
]


def _the_order_found(calls):
    """The model's change, on the order its own lookup this run found: no id came from the routine."""
    return {"order_id": calls[3].result["orders"][0]["order_id"], "note": "Friday drop: pack first"}


async def test_save_then_run_reads_run_and_the_change_waits_on_its_card(tmp_path):
    """"Save this as my Friday drop routine", then "run my Friday drop routine", through the real
    /turn, gate, action engine and presenters, with the model's calls scripted: the reads ran, the
    change is a card waiting for his gesture and was not made, and the screen is the change, then
    the routine step by step, then what the steps read, and never the lookup on the way."""
    from app import progressive
    from experience.harness import harness

    progressive.reset()
    async with harness(admitted=True) as h:
        work.configure(tmp_path / "work")
        saved = await h.ask("save this as my friday drop routine",
                            ("routine_note", {"action": "save", "name": "Friday drop", "steps": FRIDAY_SAID}),
                            session_id="routines", reply="Saved as Friday drop: three steps.")
        assert saved.status == 200 and not saved.unmakeable, saved.unmakeable
        cards = [c for c in saved.ui if c["type"] != "context_stack"]
        assert [(c["type"], c["data"]["view"]) for c in cards] == [("routine", "one")]
        assert [s["kind"] for s in cards[0]["data"]["steps"]] == ["read", "read", "change"]
        assert cards[0]["data"]["looked_up"] is True

        ran = await h.ask("run my friday drop routine", ("routine_run", {"name": "friday drop"}),
                          ("shopify_list_orders", {"days": 1}), ("gmail_search", {"query": "newer_than:1d"}),
                          ("shopify_find_order", {"query": "1940"}), ("shopify_order_note_append", _the_order_found),
                          session_id="routines", reply="Ran Friday drop. The note on 1940 is on its card.")
        assert ran.status == 200 and not ran.unmakeable, ran.unmakeable
        assert all(c.get("ok") for c in ran.raw["tool_calls"]), ran.raw["tool_calls"]
        cards = [c for c in ran.ui if c["type"] != "context_stack"]
        assert [c["type"] for c in cards] == ["confirmation", "routine", "order_list", "email_list"], [c["type"] for c in cards]
        run = cards[1]["data"]
        assert [(s["say"], s["state"]) for s in run["steps"]] == [
            ("Today's orders", "done"), ("Who wrote today", "done"), ("Note on 1940: pack it first", "waiting")]
        session = h.runtime.sessions.get("routines")
        assert [(p.operation, p.status.value) for p in session.proposals] == [("order_note_append", "PENDING")]
        assert cards[0]["data"]["proposal_id"] == session.proposals[0].proposal_id
        assert book.of("owner")[0].runs == 1


def test_a_routine_tool_that_failed_says_nothing_was_changed():
    """Not "Lookup failed, ask again": a routine not kept or not started is said as such, on its own card."""
    from app.presentation import present

    for name, title in (("routine_note", "Routine not changed"), ("routine_run", "Routine not started"),
                        ("routine_list", "Routines not read")):
        (card,) = present([ToolCall(name=name, args={}, ok=False, error="There is no routine called sunday.")])
        assert card["type"] == "error" and card["data"]["service"] == "routines"
        assert card["data"]["title"] == title and card["data"]["recovery"] == "Nothing was changed; the answer says why."
