"""The category screen: what the engine refuses outright, what it puts to the owner, and what it
lets through to be scored. It runs before any score, and a block is a veto, not a discount.

Outcomes:
    BLOCK  the engine will not propose the product. Each finding names what would clear it.
    OWNER  a safety decision for the owner, with rejection as the default.
    CLEAR  no rule here blocked the product. That is not legal clearance: the rules below are
           the ones the 2026-09-29 research found, for the categories it looked at.

Categories and documents are closed sets, so a misspelt tag is an error rather than a product
that quietly skips a rule. Each rule cites the regulation it comes from; the research read most
of these through summaries rather than the regulators' own pages, and VENTURE_ENGINE_V1.md lists
what still needs checking against the source."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.ventures.markets import REGIONS

CATEGORIES: dict[str, str] = {
    "child_restraint": "car seats, car beds or anything that holds a child in a vehicle",
    "carrier": "infant, toddler or shoulder carriers, rider saddles included",
    "ride_on": "ride-on toys",
    "costume": "costumes and dress-up clothing",
    "toy": "toys",
    "garment": "clothing",
    "footwear": "footwear and footwear attachments",
    "spark_device": "anything made to throw sparks",
    "button_battery": "contains button or coin cell batteries",
    "lithium_battery": "contains lithium batteries",
    "cosmetic": "cosmetics and skincare",
    "supplement": "food supplements",
    "food": "food and drink",
    "medical_claim": "anything sold with a health or medical claim",
    "mains_electrical": "mains-powered electrical goods",
    "weapon": "weapons and weapon accessories",
    "licensed_character": "features a brand, character or franchise",
}

DOCUMENTS: dict[str, str] = {
    "children_product_certificate": "a US Children's Product Certificate for this exact SKU",
    "cpsc_lab_report": "test reports from a CPSC-accepted third-party laboratory",
    "flammability_report": "a flammability test report (US 16 CFR 1610; UK and EU EN 71-2)",
    "en71": "EN 71 toy safety test reports",
    "ukca": "UKCA or CE marking with a UK declaration of conformity",
    "ce": "CE marking with an EU declaration of conformity",
    "reeses_law": "evidence of compliance with Reese's Law (US 16 CFR 1263)",
    "eu_responsible_person": "an appointed EU responsible economic operator",
    "gpsr_safety_info": "the safety information the EU GPSR requires on the listing",
    "battery_transport": "a UN 38.3 test summary for the lithium battery",
    "licence": "a licence for the brand, character or franchise",
}

_TRADEMARK_WORDS = re.compile(r"\b(dupes?|replicas?|knock[- ]?offs?|inspired by)\b", re.IGNORECASE)
_CHILD_TOYS = {"toy", "costume", "ride_on"}
_REGULATED_ELSEWHERE = {"cosmetic", "supplement", "food", "medical_claim", "mains_electrical"}


@dataclass(frozen=True, slots=True)
class ProductFacts:
    """What the product is, who it is for, and which compliance documents are held for this exact
    SKU. ``for_children`` means made or marketed for children (12 or younger in the US, under 14
    for UK and EU toys)."""

    categories: frozenset[str]
    for_children: bool
    documents: frozenset[str] = frozenset()
    hood_or_neck_drawstrings: bool = False
    listing_text: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.categories) - CATEGORIES.keys()
        if unknown:
            raise ValueError(f"unknown categories: {', '.join(sorted(unknown))}")
        unknown = set(self.documents) - DOCUMENTS.keys()
        if unknown:
            raise ValueError(f"unknown documents: {', '.join(sorted(unknown))}")
        object.__setattr__(self, "categories", frozenset(self.categories))
        object.__setattr__(self, "documents", frozenset(self.documents))


@dataclass(frozen=True, slots=True)
class Finding:
    outcome: str
    rule: str
    why: str
    clears_with: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Screen:
    outcome: str
    regions: tuple[str, ...]
    findings: tuple[Finding, ...]

    @property
    def summary(self) -> str:
        if self.outcome == "BLOCK":
            return "Blocked: the engine will not propose this product as it stands."
        if self.outcome == "OWNER":
            return "Needs your safety decision; the default is to reject."
        return "No rule in this screen blocked it. That is not legal clearance."


def screen(facts: ProductFacts, regions: Iterable[str]) -> Screen:
    """Screen one product for the regions it would sell in."""
    where = tuple(sorted(set(regions)))
    if not where:
        raise ValueError("screen at least one region")
    if set(where) - set(REGIONS):
        raise ValueError(f"regions must be among {', '.join(REGIONS)}")
    cats, docs = facts.categories, facts.documents
    findings: list[Finding] = []

    def block(rule: str, why: str, *needs: str) -> None:
        missing = tuple(n for n in needs if n not in docs)
        findings.append(Finding("BLOCK", rule, why, missing))

    def owner(rule: str, why: str) -> None:
        findings.append(Finding("OWNER", rule, why))

    if "child_restraint" in cats:
        block("child-restraint", "child restraints need type approval (US FMVSS 213; UK R44 or R129) "
              "and are safety-critical; the engine does not sell them")
    if "weapon" in cats:
        block("weapon", "weapons and weapon accessories are restricted by the ad platforms and the store")
    if "spark_device" in cats and facts.for_children:
        block("spark-device-child", "a device that throws sparks is never sold for children")
    if facts.for_children and "US" in where and not {"children_product_certificate", "cpsc_lab_report"} <= docs:
        block("us-childrens-product", "US children's products need a Children's Product Certificate "
              "backed by a CPSC-accepted laboratory, and since 8 July 2026 its data is filed at entry "
              "whatever the shipment's size", "children_product_certificate", "cpsc_lab_report")
    if facts.for_children and cats & _CHILD_TOYS:
        if "UK" in where and not {"ukca", "en71"} <= docs:
            block("uk-toy-safety", "UK Toys (Safety) Regulations 2011: toys, costumes included, need "
                  "marking and EN 71 testing", "ukca", "en71")
        if "EU" in where and not {"ce", "en71"} <= docs:
            block("eu-toy-safety", "EU toy safety rules: toys, costumes included, need CE marking and "
                  "EN 71 testing", "ce", "en71")
    if "costume" in cats and facts.for_children and "flammability_report" not in docs:
        block("costume-flammability", "children's costumes need flammability testing (US 16 CFR 1610; "
              "EN 71-2); the UK regulator found over 80% of 128 children's Halloween costumes failing "
              "flammability or strangulation checks", "flammability_report")
    if facts.for_children and cats & {"garment", "costume"} and facts.hood_or_neck_drawstrings:
        block("child-drawstrings", "hood or neck drawstrings on children's clothing are a strangulation "
              "hazard (US 16 CFR 1120; EN 14682); no document clears it")
    if "button_battery" in cats and "US" in where and "reeses_law" not in docs:
        block("reeses-law", "products with button or coin cells sold in the US must meet Reese's Law "
              "(16 CFR 1263)", "reeses_law")
    if "lithium_battery" in cats and "battery_transport" not in docs:
        block("battery-transport", "lithium batteries need a UN 38.3 test summary to be shipped",
              "battery_transport")
    if "EU" in where and not {"eu_responsible_person", "gpsr_safety_info"} <= docs:
        block("eu-gpsr", "the EU General Product Safety Regulation needs an EU responsible economic "
              "operator and safety information on the listing before sale (Articles 16 and 19)",
              "eu_responsible_person", "gpsr_safety_info")
    if "licensed_character" in cats and "licence" not in docs:
        block("licence", "a brand, character or franchise needs a licence on file", "licence")
    if _TRADEMARK_WORDS.search(facts.listing_text):
        block("trademark-wording", "'dupe', 'replica', 'knock-off' and 'inspired by' invite trademark "
              "claims and platform removal; the listing must be rewritten")
    if "spark_device" in cats and not facts.for_children:
        owner("spark-device-adult", "no safety standard covers footwear that throws sparks; it is a "
              "fire and traffic hazard (the best-known seller warns against fuel, dry grass and traffic)")
    if "carrier" in cats:
        owner("carrier", "carriers hold children and falls are their main hazard (US soft carriers: "
              "16 CFR 1226); shoulder rider saddles may fall outside that standard")
    if "ride_on" in cats:
        owner("ride-on", "ride-on toys carry fall, tip and battery hazards and their own standards")
    for cat in sorted(cats & _REGULATED_ELSEWHERE):
        owner(f"regulated-{cat.replace('_', '-')}", "this screen does not cover the regulation of "
              f"{CATEGORIES[cat]}")

    if any(f.outcome == "BLOCK" for f in findings):
        outcome = "BLOCK"
    elif findings:
        outcome = "OWNER"
    else:
        outcome = "CLEAR"
    return Screen(outcome, where, tuple(findings))
