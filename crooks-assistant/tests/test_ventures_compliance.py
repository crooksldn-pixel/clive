"""The category screen: blocks, owner decisions and what clears them."""

from __future__ import annotations

import pytest

from app.ventures.compliance import CATEGORIES, DOCUMENTS, ProductFacts, screen


def _facts(*categories, children=False, documents=(), drawstrings=False, text=""):
    return ProductFacts(frozenset(categories), children, frozenset(documents), drawstrings, text)


def _rules(result):
    return {finding.rule: finding for finding in result.findings}


def test_child_restraints_are_always_blocked():
    everything = frozenset(DOCUMENTS)
    result = screen(_facts("child_restraint", children=True, documents=everything), ["UK", "US", "EU"])
    assert result.outcome == "BLOCK"
    assert "child-restraint" in _rules(result)


def test_us_childrens_products_need_certificate_and_lab_reports():
    result = screen(_facts("toy", children=True), ["US"])
    finding = _rules(result)["us-childrens-product"]
    assert finding.clears_with == ("children_product_certificate", "cpsc_lab_report")
    cleared = screen(_facts("toy", children=True, documents=("children_product_certificate", "cpsc_lab_report")), ["US"])
    assert cleared.outcome == "CLEAR"


def test_childrens_costumes_need_flammability_and_toy_marking():
    result = screen(_facts("costume", children=True), ["UK"])
    rules = _rules(result)
    assert {"uk-toy-safety", "costume-flammability"} <= rules.keys()
    cleared = screen(_facts("costume", children=True, documents=("ukca", "en71", "flammability_report")), ["UK"])
    assert cleared.outcome == "CLEAR"


def test_drawstrings_on_childrens_clothing_cannot_be_cleared_by_a_document():
    result = screen(_facts("garment", children=True, documents=tuple(DOCUMENTS), drawstrings=True), ["UK"])
    assert result.outcome == "BLOCK"
    assert _rules(result)["child-drawstrings"].clears_with == ()


def test_spark_devices_blocked_for_children_and_owner_gated_for_adults():
    assert _rules(screen(_facts("spark_device", "footwear", children=True), ["UK"]))["spark-device-child"].outcome == "BLOCK"
    adult = screen(_facts("spark_device", "footwear"), ["UK"])
    assert adult.outcome == "OWNER"
    assert "default is to reject" in adult.summary


def test_carriers_and_ride_ons_go_to_the_owner():
    assert screen(_facts("carrier"), ["UK"]).outcome == "OWNER"
    assert screen(_facts("ride_on"), ["UK"]).outcome == "OWNER"


def test_batteries():
    assert _rules(screen(_facts("button_battery"), ["US"]))["reeses-law"].outcome == "BLOCK"
    assert screen(_facts("button_battery", documents=("reeses_law",)), ["US"]).outcome == "CLEAR"
    assert screen(_facts("button_battery"), ["UK"]).outcome == "CLEAR"
    assert _rules(screen(_facts("lithium_battery"), ["UK"]))["battery-transport"].outcome == "BLOCK"


def test_eu_needs_a_responsible_person_and_safety_information_for_everything():
    result = screen(_facts("garment"), ["EU"])
    assert _rules(result)["eu-gpsr"].clears_with == ("eu_responsible_person", "gpsr_safety_info")
    assert screen(_facts("garment", documents=("eu_responsible_person", "gpsr_safety_info")), ["EU"]).outcome == "CLEAR"


def test_trademark_wording_and_licences():
    assert _rules(screen(_facts("garment", text="A cheap dupe of the famous one"), ["UK"]))["trademark-wording"]
    assert _rules(screen(_facts("garment", text="Inspired by a famous brand"), ["UK"]))["trademark-wording"]
    assert screen(_facts("garment", text="Duplicate-free stitching"), ["UK"]).outcome == "CLEAR"
    assert _rules(screen(_facts("licensed_character"), ["UK"]))["licence"].clears_with == ("licence",)


def test_regulated_categories_the_screen_does_not_cover_go_to_the_owner():
    result = screen(_facts("cosmetic", "supplement"), ["UK"])
    assert result.outcome == "OWNER"
    assert {"regulated-cosmetic", "regulated-supplement"} <= _rules(result).keys()
    assert screen(_facts("weapon"), ["UK"]).outcome == "BLOCK"


def test_clear_is_not_legal_clearance():
    result = screen(_facts("garment"), ["UK"])
    assert result.outcome == "CLEAR"
    assert "not legal clearance" in result.summary


def test_unknown_tags_and_regions_are_refused():
    with pytest.raises(ValueError, match="unknown categories"):
        _facts("hoverboard")
    with pytest.raises(ValueError, match="unknown documents"):
        _facts("toy", documents=("vibes",))
    with pytest.raises(ValueError):
        screen(_facts("toy"), ["CA"])
    with pytest.raises(ValueError):
        screen(_facts("toy"), [])


def test_every_category_and_document_is_described():
    assert all(text for text in CATEGORIES.values())
    assert all(text for text in DOCUMENTS.values())
