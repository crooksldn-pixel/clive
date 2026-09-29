"""The venture brief and its command line, on the example candidates in fixtures/ventures."""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.ventures.__main__ import main
from app.ventures.brief import (
    SCHEMA_OUT,
    brief_to_dict,
    build_brief,
    load_candidate,
    render_markdown,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ventures"
TODAY = date(2026, 9, 29)


def _raw(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"), parse_float=Decimal)


def _brief(name: str, **changes):
    data = _raw(name)
    data.update(changes)
    return build_brief(load_candidate(data), TODAY)


def test_spark_attachment_needs_the_owners_safety_decision_first():
    brief = _brief("spark_attachment_uk")
    assert brief.verdict == "NEEDS_OWNER"
    assert brief.asks[0].startswith("SAFETY:")
    assert brief.asks[-1].startswith("PRODUCT_DIRECTION: fund a test of up to £108.00")
    assert brief.floor.shown_minimum == Decimal("25.94")
    assert brief.price == Decimal("25.99")
    assert brief.launch.feasible


def test_childrens_costume_is_blocked_and_proposes_nothing():
    brief = _brief("childrens_costume_us")
    assert brief.verdict == "BLOCKED"
    assert brief.asks == ()
    assert brief.score.excluded
    text = render_markdown(brief)
    assert "Nothing: the product is not proposed." in text
    assert "## Test plan" not in text
    assert "Too late for Halloween" in text


def test_cable_organiser_is_ready_and_reads_its_results():
    brief = _brief("cable_organiser_uk")
    assert brief.verdict == "READY_TO_PROPOSE"
    assert [a.split(":")[0] for a in brief.asks] == ["PRODUCT_DIRECTION"]
    assert brief.results is not None
    actions = dict((name, d.action) for name, d in brief.results.concepts)
    assert actions == {"desk before and after": "CONTINUE", "cable chaos POV": "KILL",
                       "gift for a desk worker": "KILL"}


def test_an_owner_price_under_the_floor_is_not_viable():
    brief = _brief("cable_organiser_uk", price="14.99")
    assert brief.verdict == "NOT_VIABLE"
    assert "the floor is £20.20" in brief.headline


def test_an_order_losing_money_before_ads_is_not_viable():
    brief = _brief("cable_organiser_uk", price="4.99")
    assert brief.verdict == "NOT_VIABLE"
    assert brief.order.break_even_roas is None


@pytest.mark.parametrize("price", [None, "99.99"])
def test_targets_no_price_can_meet_are_not_viable_even_at_the_owners_price(price):
    changes = {"target_margin": "0.95"} | ({} if price is None else {"price": price})
    brief = _brief("cable_organiser_uk", **changes)
    assert brief.floor is None
    assert brief.verdict == "NOT_VIABLE"
    assert brief.headline == "No price can pay £8.00 per purchase and keep 95%."
    assert brief.asks == ()
    assert any(note.startswith("no price can pay these rates") for note in brief.notes)
    assert "- No floor: no price meets the targets (see the notes)." in render_markdown(brief)


def test_a_candidate_must_be_an_object():
    with pytest.raises(ValueError, match="candidate must be an object"):
        load_candidate(["name"])


def test_the_brief_says_nothing_happened_and_compares_with_the_median():
    text = render_markdown(_brief("spark_attachment_uk"))
    assert "nothing was spent, listed, published or sent" in text
    assert "an order would lose £1.54 after advertising" in text
    assert _raw("spark_attachment_uk")["name"] in text


def test_break_even_roas_is_rounded_up_because_it_is_a_bar_to_clear():
    brief = _brief("cable_organiser_uk")
    assert Decimal("1.88") < brief.order.break_even_roas < Decimal("1.89")
    assert "Break-even ROAS 1.89;" in render_markdown(brief)
    assert brief_to_dict(brief)["order"]["break_even_roas"] == "1.89"


def test_json_form_is_stable_and_declares_no_external_effects():
    data = brief_to_dict(_brief("cable_organiser_uk"))
    assert data["schema"] == SCHEMA_OUT
    assert data["external_effects"] == "none"
    assert data["price"] == "20.99"
    assert data["kill_lines"][0] == {"spend": "24.00", "max_purchases": 0, "false_kill": 0.0498}
    assert json.loads(json.dumps(data)) == data


def test_the_same_candidate_always_gives_the_same_brief():
    first = render_markdown(_brief("spark_attachment_uk"))
    second = render_markdown(_brief("spark_attachment_uk"))
    assert first == second


@pytest.mark.parametrize(("path", "value", "message"), [
    (("costs", "tip_jar"), "1", "unknown keys"),
    (("colour",), "red", "unknown keys"),
    (("costs", "product"), 3.8, "not float"),
    (("market",), "MARS", "unknown market"),
    (("event",), "diwali", "event must be"),
    (("price_style",), "fancy", "price_style"),
    (("product", "categories"), ["hoverboard"], "unknown categories"),
    (("product", "for_children"), "no", "true or false"),
    (("delivery_days",), -3, "whole number"),
    (("schema",), "something.else", "schema must be"),
])
def test_bad_candidates_are_refused(path, value, message):
    data = copy.deepcopy(_raw("cable_organiser_uk"))
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((ValueError, TypeError), match=message):
        load_candidate(data)


def test_missing_required_keys_are_named():
    data = _raw("cable_organiser_uk")
    del data["target_cpa"]
    with pytest.raises(ValueError, match="missing: target_cpa"):
        load_candidate(data)


def test_cli_brief_markdown_and_json(capsys):
    assert main(["brief", str(FIXTURES / "spark_attachment_uk.json"), "--today", "2026-09-29"]) == 0
    assert "Verdict: NEEDS OWNER" in capsys.readouterr().out
    assert main(["brief", str(FIXTURES / "cable_organiser_uk.json"), "--today", "2026-09-29", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "READY_TO_PROPOSE"


def test_cli_reports_bad_input_without_a_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "x"}', encoding="utf-8")
    assert main(["brief", str(bad)]) == 2
    assert capsys.readouterr().err.startswith("error: candidate is missing")
    assert main(["brief", str(tmp_path / "absent.json")]) == 2


def test_cli_dates(capsys):
    assert main(["dates", "--market", "UK", "--today", "2026-09-29"]) == 0
    out = capsys.readouterr().out
    assert "2026-11-27  Black Friday" in out
    assert "2027-03-07  Mothering Sunday" in out
    assert "Golden Week supplier slowdown" in out
    assert main(["dates", "--days", "0"]) == 2
