"""Finding a product's commodity code without researching it: plain English in, a code the UK
Trade Tariff confirms out, and the merchant decides.

    "jorts" → a classifier reads what is known (title, type, variant, the customs description,
    the merchant's own words) → the official tariff tree for the heading it points to is walked,
    level by level, by those facts → where one fact can't be known it asks for exactly that, with
    the tariff's own wording as the choices → the leaf code is checked against the UK Trade
    Tariff (it exists, it can be declared, it is in force) → the merchant confirms it, and only
    then is it saved, through the same path as a code typed by hand.

Two roles, kept apart:

  * CommodityClassifier: understands words. Here a small set of rules (garment, knitted or woven,
    fibre, who it is cut for); another (an AI service, say) can replace it. It never decides a
    code and is never the proof one exists.
  * CommodityTariffSource: the authority. UkTradeTariff reads the official UK Trade Tariff
    (www.trade-tariff.service.gov.uk, DBT/HMRC). Only what it returns is offered.

A suggestion is not a fact: nothing here saves anything. Codes are strings (leading zeros kept);
a UK commodity code is ten digits, an export HS code six, and the code is used as confirmed.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

log = logging.getLogger("shipping.commodity")

TARIFF_BASE = "https://www.trade-tariff.service.gov.uk/uk/api"
SCHEME = "UK Global Tariff (UK Trade Tariff)"


class TariffUnavailable(Exception):
    """The UK Trade Tariff couldn't be read. Nothing is guessed; manual entry still works."""


@dataclass(frozen=True)
class TariffNode:
    code: str  # goods_nomenclature_item_id, ten digits as given (leading zeros kept)
    suffix: str  # producline_suffix: "80" is a real line, others are grouping headers
    description: str
    indent: int
    leaf: bool
    declarable: bool


@dataclass(frozen=True)
class TariffEntry:
    """A commodity code the UK Trade Tariff confirms, with its official wording."""

    code: str
    description: str  # the official description of the line itself
    path: list[str]  # the official wording from the heading down to the line
    declarable: bool
    in_force: bool
    source: str  # where it was checked
    checked_at: str  # when, ISO


class CommodityTariffSource(Protocol):
    def heading(self, heading: str) -> list[TariffNode]: ...
    def commodity(self, code: str) -> TariffEntry | None: ...


class UkTradeTariff:
    """The official UK Trade Tariff API, read only. Headings are kept for a day (the tariff
    changes rarely); single codes are always read fresh when confirming."""

    def __init__(
        self, base: str = TARIFF_BASE, http: httpx.Client | None = None, ttl_s: int = 86400
    ) -> None:
        self.base = base.rstrip("/")
        self._http = http or httpx.Client(timeout=10, headers={"Accept": "application/json"})
        self._cache: dict[str, tuple[float, list[TariffNode]]] = {}
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

    def _get(self, path: str) -> dict[str, Any] | None:
        try:
            r = self._http.get(f"{self.base}{path}")
        except httpx.HTTPError as exc:
            raise TariffUnavailable(f"The UK Trade Tariff couldn't be reached ({exc}).") from exc
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise TariffUnavailable(f"The UK Trade Tariff answered {r.status_code}.")
        try:
            body = r.json()
        except ValueError as exc:
            raise TariffUnavailable("The UK Trade Tariff sent an unreadable answer.") from exc
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise TariffUnavailable("The UK Trade Tariff sent an unexpected answer.")
        return body

    def heading(self, heading: str) -> list[TariffNode]:
        if not re.fullmatch(r"\d{4}", heading):
            raise ValueError("A heading is four digits.")
        with self._lock:
            hit = self._cache.get(heading)
            if hit and time.monotonic() - hit[0] < self.ttl_s:
                return hit[1]
        body = self._get(f"/headings/{heading}")
        if body is None:
            return []
        nodes = [
            TariffNode(
                code=str(a.get("goods_nomenclature_item_id") or ""),
                suffix=str(a.get("producline_suffix") or "80"),
                description=str(a.get("description") or ""),
                indent=int(a.get("number_indents") or 0),
                leaf=bool(a.get("leaf")),
                declarable=bool(a.get("declarable")),
            )
            for i in body.get("included") or []
            if i.get("type") == "commodity" and (a := i.get("attributes") or {})
        ]
        with self._lock:
            self._cache[heading] = (time.monotonic(), nodes)
        return nodes

    def commodity(self, code: str) -> TariffEntry | None:
        """The official entry for a ten-digit code, or None when the tariff has no such
        commodity (a heading or a grouping line is not one)."""
        if not re.fullmatch(r"\d{10}", code):
            return None
        body = self._get(f"/commodities/{code}")
        if body is None or body["data"].get("type") != "commodity":
            return None
        a = body["data"].get("attributes") or {}
        included = body.get("included") or []
        heading = next((i for i in included if i.get("type") == "heading"), None)
        ancestors = sorted(
            (i["attributes"] for i in included if i.get("type") == "commodity"),
            key=lambda x: int(x.get("number_indents") or 0),
        )
        path = (
            [str((heading or {}).get("attributes", {}).get("description") or "")]
            + [str(x.get("description") or "") for x in ancestors]
            + [str(a.get("description") or "")]
        )
        ends = a.get("validity_end_date")
        in_force = not ends or str(ends) > datetime.now(UTC).isoformat()
        return TariffEntry(
            code=str(a.get("goods_nomenclature_item_id") or code),
            description=str(a.get("description") or ""),
            path=[p for p in path if p],
            declarable=bool(a.get("declarable")),
            in_force=in_force,
            source=f"{self.base}/commodities/{code}",
            checked_at=datetime.now(UTC).isoformat(),
        )


# ------------------------------------------------------------------ understanding the words


@dataclass
class Facts:
    """What decides the code, each with how it is known ("you said", "from the title"...)."""

    garment: str | None = None  # trousers, shorts, skirt, tshirt, sweatshirt
    construction: str | None = None  # knitted, woven
    fibre: str | None = None  # cotton, synthetic, artificial, wool, other
    gender: str | None = None  # men, women
    denim: bool | None = None
    corduroy: bool | None = None
    why: dict[str, str] = field(default_factory=dict)

    def set(self, name: str, value: Any, why: str) -> None:
        if getattr(self, name) is None:
            setattr(self, name, value)
            self.why[name] = why


class CommodityClassifier(Protocol):
    def facts(self, text: str, answers: dict[str, str]) -> Facts: ...


GARMENTS = [  # (words, garment, implied facts with the reason)
    (r"jorts?", "shorts", {"denim": (True, "jorts are denim shorts")}),
    (r"jeans?", "trousers", {"denim": (True, "jeans are denim")}),
    (r"shorts?", "shorts", {}),
    (r"joggers?|jogging bottoms|sweatpants|track ?pants|trackies", "trousers", {}),
    (r"trousers?|pants|chinos?|cargos?|slacks", "trousers", {}),
    (r"skirts?", "skirt", {"gender": ("women", "skirts are women's garments in the tariff")}),
    (r"t-?shirts?|tees?", "tshirt", {
        "construction": ("knitted", "a T-shirt is knitted jersey (heading 6109)"),
    }),
    (r"hood(?:ie|y)s?|sweatshirts?|jumpers?|sweaters?|crew ?necks?|pullovers?", "sweatshirt", {
        "construction": ("knitted", "hoodies and sweatshirts are knitted (heading 6110)"),
    }),
]  # fmt: skip
FIBRES = [
    (r"cotton", "cotton"),
    (r"polyester|nylon|polyamide|acrylic|synthetic", "synthetic"),
    (r"viscose|rayon|modal|lyocell|tencel", "artificial"),
    (r"cashmere", "cashmere"),
    (r"wool|merino|lambswool", "wool"),
    (r"linen|flax|ramie", "flax"),
    (r"silk|hemp", "other"),
]
GENDERS = [
    (r"women'?s|womens|ladies|female|girls'?", "women"),
    (r"men'?s|mens|male|boys'?", "men"),
]


def _has(pattern: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){pattern}(?![a-z])", text) is not None


class RuleClassifier:
    """Plain words to tariff facts, by rules that only ever claim what the words say (or what
    a garment is by definition: jeans are denim, a T-shirt is knitted)."""

    def facts(self, text: str, answers: dict[str, str]) -> Facts:
        f = Facts()
        for name, value in answers.items():  # what the merchant chose wins over anything read
            if name in ("garment", "construction", "fibre", "gender") and value:
                f.set(name, value, "you said")
            elif name in ("denim", "corduroy") and value in ("yes", "no"):
                f.set(name, value == "yes", "you said")
        words = text.lower()
        for pattern, garment, implied in GARMENTS:
            if _has(pattern, words):
                f.set("garment", garment, f'"{re.search(pattern, words).group(0)}"')  # type: ignore[union-attr]
                for name, (value, why) in implied.items():
                    f.set(name, value, why)
                break
        for pattern, fibre in FIBRES:
            if _has(pattern, words):
                f.set("fibre", fibre, f"{fibre} in the description")
                break
        for pattern, gender in GENDERS:
            if _has(pattern, words):
                f.set("gender", gender, f"{gender}'s in the description")
                break
        if _has("unisex", words):
            f.set("gender", "unisex", "unisex in the description")
        if _has(r"jersey|knit(?:ted)?|fleece", words):
            f.set("construction", "knitted", "knitted fabric in the description")
        if _has(r"woven|denim|twill|canvas|corduroy|cord", words):
            f.set("construction", "woven", "woven fabric in the description")
        if f.denim:
            f.set("construction", "woven", "denim is woven")
        if _has(r"corduroy|cord", words):
            f.set("corduroy", True, "corduroy in the description")
        if f.gender == "unisex":
            # Chapters 61 and 62, note 9: a garment that can't be identified as men's or women's
            # is classified with women's (read from the UK Trade Tariff chapter notes).
            f.gender = "women"
            f.why["gender"] = "unisex: classified as women's (Chapters 61/62, note 9)"
        return f


# ------------------------------------------------------------------ walking the tariff


@dataclass
class Question:
    fact: str  # which fact the answer sets
    text: str
    options: list[dict[str, str]]  # {"value", "label"}: labels are the tariff's own words


@dataclass
class Suggestion:
    """The outcome of one look-up: a question to answer, a candidate to confirm, or nothing
    (enter the code by hand). Never saved by itself."""

    state: str  # question, candidate, manual
    message: str = ""
    question: Question | None = None
    code: str | None = None
    entry: TariffEntry | None = None
    reasons: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)


KNIT_OR_WOVEN = Question(
    "construction",
    "Knitted or woven?",
    [
        {"value": "knitted", "label": "Knitted or crocheted (jersey, fleece, sweatshirt fabric)"},
        {"value": "woven", "label": "Woven (denim, twill, canvas, poplin)"},
    ],
)
CUT_FOR = Question(
    "gender",
    "Who is it cut for?",
    [
        {"value": "men", "label": "Men's or boys'"},
        {"value": "women", "label": "Women's or girls'"},
        {"value": "unisex", "label": "Unisex (classified as women's: Chapters 61/62, note 9)"},
    ],
)


def heading_for(f: Facts) -> tuple[str | None, Question | None]:
    """The four-digit heading, or the one fact needed to choose it."""
    if f.garment is None:
        return None, None
    if f.garment == "tshirt":
        if f.construction == "woven":
            return None, None  # a woven "T-shirt" is a shirt in the tariff: enter it by hand
        return "6109", None
    if f.garment == "sweatshirt":
        if f.construction == "woven":
            return None, None  # not a knitted jersey: beyond this helper, enter it by hand
        return "6110", None
    if f.construction is None:
        return None, KNIT_OR_WOVEN
    if f.gender is None:
        return None, CUT_FOR
    knitted = f.construction == "knitted"
    if f.gender == "men":
        if f.garment == "skirt":
            return None, None
        return ("6103" if knitted else "6203"), None
    return ("6104" if knitted else "6204"), None


# How a line of the official tree reads, as the facts it stands for.
CLAIMS: list[tuple[str, str, Any]] = [
    (r"^of cotton$", "fibre", "cotton"),
    (r"^of synthetic fibres$", "fibre", "synthetic"),
    (r"^of artificial fibres$", "fibre", "artificial"),
    (r"^of wool or fine animal hair$", "fibre", {"wool", "cashmere"}),
    (r"^of wool$", "fibre", "wool"),
    (r"^of kashmir \(cashmere\) goats$", "fibre", "cashmere"),
    (r"^of man-made fibres$", "fibre", {"synthetic", "artificial"}),
    (r"^of wool or fine animal hair or man-made fibres$", "fibre",
     {"wool", "cashmere", "synthetic", "artificial"}),
    (r"^of flax or ramie$", "fibre", "flax"),
    (r"^of other textile materials$", "fibre", "*"),
    (r"^of denim$", "weave", "denim"),
    (r"^of cut corduroy$", "weave", "corduroy"),
    (r"^hand-made\b", "special", "hand-made"),
    (r"^men's or boys'$", "gender", "men"),
    (r"^women's or girls'$", "gender", "women"),
    (r"^industrial and occupational$", "special", "occupational"),
    (r'^hand-printed by the "batik" method$', "special", "batik"),
    (r"^t-shirts$", "garment", "tshirt"),
    (r"^trousers and breeches$", "garment", "trousers"),
    (r"^bib and brace overalls$", "garment", "overalls"),
    (r"^skirts and divided skirts$", "garment", "skirt"),
    (r"^trousers, bib and brace overalls, breeches and shorts$", "garment", {"trousers", "shorts"}),
    (r"^jerseys, pullovers, cardigans, waistcoats and similar articles$", "garment", "sweatshirt"),
    (r"^lightweight fine knit roll, polo or turtleneck jumpers", "garment", "rollneck"),
]  # fmt: skip


def claim(description: str) -> tuple[str, Any] | None:
    d = re.sub(r"\s+", " ", description.strip().lower())
    for pattern, fact, value in CLAIMS:
        if re.match(pattern, d):
            return fact, value
    return None


def _fits(value: Any, known: Any) -> bool:
    return known in value if isinstance(value, set) else value == known


class Navigator:
    def __init__(self, tariff: CommodityTariffSource) -> None:
        self.tariff = tariff

    def walk(self, heading: str, f: Facts) -> tuple[str | None, Question | None, list[str]]:
        """Down the official tree from the heading to one line. Returns (code, None, path) when a
        line is reached, (None, question, path) when one fact is missing, or (None, None, path)
        when the facts don't lead to any line (enter it by hand)."""
        nodes = self.tariff.heading(heading)
        path: list[str] = []
        start, depth = 0, None
        while True:
            children = self._children(nodes, start, depth)
            if not children:
                return None, None, path
            pick, question = self._choose(children, f)
            if question is not None:
                return None, question, path
            if pick is None:
                return None, None, path
            i, node = pick
            path.append(node.description)
            if node.leaf:
                return (node.code if node.declarable else None), None, path
            start, depth = i + 1, node.indent

    @staticmethod
    def _children(
        nodes: list[TariffNode], start: int, parent_indent: int | None
    ) -> list[tuple[int, TariffNode]]:
        out: list[tuple[int, TariffNode]] = []
        want = None
        for i in range(start, len(nodes)):
            n = nodes[i]
            if parent_indent is not None and n.indent <= parent_indent:
                break
            if want is None:
                want = n.indent
            if n.indent == want:
                out.append((i, n))
        return out

    @staticmethod
    def _choose(
        children: list[tuple[int, TariffNode]], f: Facts
    ) -> tuple[tuple[int, TariffNode] | None, Question | None]:
        claimed = [(c, claim(c[1].description)) for c in children]
        named = [(c, cl) for c, cl in claimed if cl is not None]
        others = [c for c, cl in claimed if cl is None and c[1].description.lower() == "other"]
        unread = [c for c, cl in claimed if cl is None and c[1].description.lower() != "other"]
        if not named:
            return None, None  # lines that read nothing we understand: the merchant decides
        if unread and not any(cl[0] == "garment" for _, cl in named):
            # A line turns on something not asked here (a weight, silk...): never assume it
            # doesn't apply. (Beside a garment line, the others are other garments: suits,
            # jackets, dresses.)
            return None, None
        dims = {cl[0] for _, cl in named}
        dim = next(iter(dims)) if len(dims) == 1 else None
        if dim is None:
            return None, None
        if dim == "special":
            # Workwear, batik prints, hand-made: not ordinary clothing unless the merchant says
            # so; the chosen path shows "Other" for them to see before confirming.
            return (others[0] if others else None), None
        if dim == "weave":
            weave = "denim" if f.denim else "corduroy" if f.corduroy else None
            if weave is None and f.denim is False and f.corduroy is False:
                weave = "neither"
            if weave is None:
                options = [{"value": value, "label": c[1].description} for c, (_, value) in named]
                options.append({"value": "neither", "label": "Neither (another woven fabric)"})
                return None, Question("weave", "Which is the fabric?", options)
            for c, (_, value) in named:
                if value == weave:
                    return c, None
            return (others[0] if others else None), None
        known = getattr(f, dim, None)
        if known is None:
            if dim == "fibre":
                options = [
                    {"value": "cotton", "label": "Mostly cotton"},
                    {"value": "synthetic", "label": "Mostly synthetic (polyester, nylon, acrylic)"},
                    {"value": "artificial", "label": "Mostly viscose, modal or lyocell"},
                    {"value": "wool", "label": "Mostly wool"},
                    {"value": "cashmere", "label": "Mostly cashmere"},
                    {"value": "flax", "label": "Mostly linen"},
                    {"value": "other", "label": "Mostly something else (silk, hemp...)"},
                ]
                return None, Question("fibre", "What is it mostly made of?", options)
            if dim == "gender":
                return None, CUT_FOR
            return None, None
        for c, (_, value) in named:
            if value != "*" and _fits(value, known):
                return c, None
        star = [c for c, (_, value) in named if value == "*"]
        if star:  # "Of other textile materials": any fibre not named beside it
            return star[0], None
        return (others[0] if others else None), None


# ------------------------------------------------------------------ the helper


class CommodityAssistant:
    def __init__(
        self,
        tariff: CommodityTariffSource,
        classifier: CommodityClassifier | None = None,
    ) -> None:
        self.tariff = tariff
        self.classifier = classifier or RuleClassifier()

    def suggest(self, text: str, answers: dict[str, str] | None = None) -> Suggestion:
        answers = dict(answers or {})
        if answers.get("weave"):  # one question sets denim/corduroy
            weave = answers.pop("weave")
            answers["denim"] = "yes" if weave == "denim" else "no"
            answers["corduroy"] = "yes" if weave == "corduroy" else "no"
        inputs = {"text": text, "answers": answers}
        try:
            f = self.classifier.facts(text, answers)
        except Exception:  # an optional classifier failing must not block anything
            log.exception("commodity classifier failed")
            return Suggestion(
                "manual",
                "Couldn't read that description. Enter the code by hand.",
                inputs=inputs,
            )
        heading, question = heading_for(f)
        if question is not None:
            return Suggestion("question", question=question, inputs=inputs)
        if heading is None:
            return Suggestion(
                "manual",
                "CLIVE can find codes for jeans, jorts, shorts, joggers, trousers, skirts, "
                "T-shirts and hoodies. Enter this one by hand, or describe it as one of those.",
                inputs=inputs,
            )
        try:
            code, question, path = Navigator(self.tariff).walk(heading, f)
            if question is not None:
                return Suggestion("question", question=question, inputs=inputs)
            entry = self.tariff.commodity(code) if code else None
        except TariffUnavailable as exc:
            return Suggestion("manual", f"{exc} Enter the code by hand.", inputs=inputs)
        if entry is None or not entry.declarable or not entry.in_force:
            return Suggestion(
                "manual",
                "The UK Trade Tariff has no current line for this. Enter the code by hand.",
                inputs=inputs,
            )
        return Suggestion(
            "candidate",
            code=entry.code,
            entry=entry,
            reasons=[_reason(f, name, why) for name, why in f.why.items()],
            inputs=inputs,
        )

    def check(self, code: str) -> TariffEntry | None:
        """A typed or suggested code, read back from the UK Trade Tariff (None: no such current,
        declarable line). Raises TariffUnavailable when it can't be read."""
        entry = self.tariff.commodity(code)
        return entry if entry and entry.declarable and entry.in_force else None


WORDS = {"men": "men's", "women": "women's", "tshirt": "T-shirt", "sweatshirt": "jersey/hoodie"}


def _reason(f: Facts, name: str, why: str) -> str:
    """ "fibre: cotton (you said)", "construction: knitted (a T-shirt is knitted jersey)"."""
    value = getattr(f, name)
    shown = "yes" if value is True else "no" if value is False else WORDS.get(value, value)
    return f"{name}: {shown} ({why})"


def spaced(code: str) -> str:
    """6203429000 → 6203 42 90 00, as the tariff writes it."""
    return " ".join(x for x in (code[:4], code[4:6], code[6:8], code[8:10]) if x)
