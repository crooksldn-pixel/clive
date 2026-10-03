"""Every fact he gave about an order, scored together, and a verdict that says why.

"Look up Alysa who ordered the grey hoodie last week." Three facts. The strict search in
app/tools/shopify_tools.py (`_find_by_evidence`) holds each one as yes or no, which is right
when they are all true as said — and finds nothing when one of them was misheard, because the
customer is Alicia. This is the second pass, run only when that one finds nothing: each order
that could be it gets points for each fact it fits, a share of them for a fact it half fits,
none for a fact it does not, and the facts are weighed together, so no single one decides.

    name      3     how like it sounds (app/customers/names.py)
    item      3     the share of the words said that are on one of its lines
    when      2     inside the days the words mean, or near them (app/customers/when.py)
    amount    2     the order's total, to the penny or near it
    address   2.5   the postcode or the town on the parcel
    email     3     the address on the order, or 2 for a part of it ("alicia.g")
    number    4     the order number, or 1.5 for a part of it ("ends 42")

The verdict is one of four, and the line of words the owner reads beside it says what decided:

    one       one order fits clearly better than any other, on more than its name
    check     one order might be it, but what fits does not prove it
    several   two or three fit about as well: they are shown, and one short question asked
    none      nothing fits well enough to show

"Never hinge on the name alone": an order is never "one" on its name — at least one other fact
must fit it whole — and an order whose name does NOT fit can be "one" only when two other facts
fit it whole, and then the line says the name is not the one he said. The same holds the other
way: one fact that fits, against another he said that does not, is not shown at all. A fact this pass cannot
judge for an order (a postcode against a row that carries only the town) is neither for it nor
against it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.customers import names, when
from app.tools import shopify_tools as st

WEIGHTS = {"name": 3.0, "item": 3.0, "when": 2.0, "amount": 2.0, "address": 2.5, "email": 3.0, "number": 4.0}
# The points the best must lead the next by to be the one, and the share of what it could have
# scored it must reach. Below SHOWN an order is not put in front of him at all.
MARGIN = 1.5
CLEAR = 0.6
SHOWN = 0.45
MAX_SHOWN = 3
_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?(?:\s*\d[A-Z]{2})?$", re.I)
_FACT_ORDER = ("name", "item", "when", "amount", "address", "email", "number")


@dataclass
class Candidate:
    """One order, from whichever read had it, in the one shape every fact is held against."""

    order_id: str
    number: str = ""
    placed_at: str = ""
    day: date | None = None
    customer_id: str = ""
    customer_name: str = ""
    customer_email: str = ""
    order_email: str = ""
    parcel_name: str = ""
    address: dict[str, Any] = field(default_factory=dict)
    total: float | None = None
    currency: str = "GBP"
    # What was paid: the total before any refund, which is what an amount he says is held to.
    # None when the read does not know it (the cache keeps only what is left after a refund).
    paid: float | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    fulfillment: str = ""
    payment: str = ""
    cancelled: bool = False
    has_zip: bool = False

    @property
    def digits(self) -> str:
        return str(self.number or "").rsplit("-", 1)[-1].lstrip("#")


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def from_node(node: dict[str, Any]) -> Candidate:
    """An order as the evidence search reads it (shopify_tools.ORDER_EVIDENCE_QUERY)."""
    customer = node.get("customer") or {}
    address = node.get("shippingAddress") or {}
    money = ((node.get("currentTotalPriceSet") or {}).get("shopMoney") or {})
    paid = ((node.get("totalPriceSet") or {}).get("shopMoney") or {})
    stamp = node.get("processedAt") or node.get("createdAt") or ""
    return Candidate(
        order_id=str(node.get("id") or ""), number=str(node.get("name") or ""), placed_at=str(stamp),
        day=when.shop_day(stamp), customer_id=str(customer.get("id") or ""),
        customer_name=str(customer.get("displayName") or ""),
        customer_email=str(((customer.get("defaultEmailAddress") or {}).get("emailAddress")) or "").lower(),
        order_email=str(node.get("email") or "").lower(),
        parcel_name=" ".join(str(address.get(k) or "") for k in ("firstName", "lastName")).strip(),
        address={k: address.get(k) for k in ("address1", "address2", "city", "zip")},
        total=_float(money.get("amount")), currency=str(money.get("currencyCode") or "GBP"), paid=_float(paid.get("amount")),
        items=st._evidence_lines(node), fulfillment=str(node.get("displayFulfillmentStatus") or ""),
        payment=str(node.get("displayFinancialStatus") or ""), cancelled=bool(node.get("cancelledAt")),
        has_zip=bool(str(address.get("zip") or "").strip()),
    )


def from_cache_row(row: dict[str, Any]) -> Candidate:
    """An order as the read layer's cache holds it (app/analytics/cache.py `shape_order`): the
    town but not the street or the postcode, and no name on the parcel."""
    customer = row.get("customer") or {}
    total = _float(row.get("total"))
    return Candidate(
        order_id=str(row.get("order_id") or ""), number=str(row.get("order_number") or ""),
        placed_at=str(row.get("created_at") or ""), day=when.shop_day(row.get("created_at")),
        customer_id=str(customer.get("customer_id") or ""), customer_name=str(customer.get("name") or ""),
        customer_email=str(customer.get("email") or "").lower(), address={"city": row.get("city") or ""},
        total=total, currency=str(row.get("currency") or "GBP"),
        paid=total if not _float(row.get("refunded")) else None,
        items=[{"title": str(i.get("product") or ""), "variant": str(i.get("variant") or ""), "sku": str(i.get("sku") or ""),
                "quantity": i.get("quantity"), "variant_id": str(i.get("variant_id") or "")}
               for i in row.get("items") or [] if isinstance(i, dict)],
        fulfillment=str(row.get("fulfillment") or ""), payment=str(row.get("financial") or ""),
        cancelled=bool(row.get("cancelled")), has_zip=False,
    )


# --------------------------------------------------------------------------- the facts


@dataclass
class Evidence:
    """What he said, each fact in the form it is held in. `unread` is what was said and could
    not be understood (a date this build does not know), said back rather than dropped."""

    name: str = ""
    item: str = ""
    when: when.When | None = None
    when_said: str = ""
    amount: float | None = None
    amount_said: str = ""
    address: str = ""
    email: str = ""
    number: str = ""
    unread: list[str] = field(default_factory=list)

    def given(self) -> list[str]:
        out = []
        for fact in _FACT_ORDER:
            value = getattr(self, fact)
            if value not in ("", None):
                out.append(fact)
        return out


_AMOUNT = re.compile(r"(\d+(?:[.,]\d{1,2})?)")


def amount_of(said: Any) -> float | None:
    """"£45", "45 quid", "about 60", "45.50" → the number; None for anything else."""
    text = str(said or "").replace(",", "")
    found = _AMOUNT.search(text)
    if not found or len(_AMOUNT.findall(text)) != 1:
        return None
    value = _float(found.group(1))
    return value if value is not None and 0 < value < 100_000 else None


def evidence_from(asked: dict[str, Any], today: date) -> Evidence:
    """The facts as the search was given them (shopify_find_order's fields)."""
    ev = Evidence(name=str(asked.get("name") or ""), item=str(asked.get("item") or ""),
                  address=str(asked.get("address") or ""), email=str(asked.get("email") or "").strip().lower(),
                  number=str(asked.get("number") or ""))
    said_when = " ".join(str(asked.get("when") or "").split())
    if said_when:
        ev.when, ev.when_said = when.parse(said_when, today), said_when
        if ev.when is None:
            ev.unread.append(f"when ({said_when!r})")
    said_amount = " ".join(str(asked.get("amount") or "").split())
    if said_amount:
        ev.amount, ev.amount_said = amount_of(said_amount), said_amount
        if ev.amount is None:
            ev.unread.append(f"amount ({said_amount!r})")
    return ev


# --------------------------------------------------------------------------- scoring


@dataclass
class Scored:
    candidate: Candidate
    points: float
    possible: float
    facts: dict[str, dict[str, Any]]
    lines: list[dict[str, Any]]
    likeness: dict[str, Any]

    @property
    def confidence(self) -> float:
        return round(self.points / self.possible, 3) if self.possible else 0.0

    def fit(self, fact: str) -> str:
        return str((self.facts.get(fact) or {}).get("fit") or "")

    def whole(self, *, besides_name: bool = True) -> int:
        return sum(1 for k, v in self.facts.items() if v.get("fit") == "yes" and (k != "name" or not besides_name))


def _fact(fit: str, points: float, possible: float, words: str) -> dict[str, Any]:
    return {"fit": fit, "points": round(points, 3), "possible": possible, "words": words}


def _item_fact(c: Candidate, said: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    wanted = st.item_words(said)
    if not wanted:
        return _fact("unknown", 0.0, 0.0, ""), []
    best, share = [], 0.0
    for line in c.items:
        if said.strip().upper() == str(line.get("sku") or "").upper() and line.get("sku"):
            have = 1.0
        else:
            words = st.line_words(str(line.get("title") or ""), str(line.get("variant") or ""), str(line.get("sku") or ""))
            have = sum(1 for w in wanted if st._found(w, words)) / len(wanted)
        if have > share:
            best, share = [line], have
        elif have == share and have > 0:
            best.append(line)
    fit = "yes" if share >= 1.0 else "partly" if share > 0 else "no"
    words = f"{said} on it" if fit == "yes" else (f"part of '{said}' on it" if fit == "partly" else f"no {said} on it")
    return _fact(fit, WEIGHTS["item"] * share, WEIGHTS["item"], words), best


def _when_fact(c: Candidate, ev: Evidence, today: date) -> dict[str, Any]:
    share = ev.when.fit(c.day) if ev.when else 0.0
    placed = when.day_words(c.day, today)
    fit = "yes" if share >= 1.0 else "partly" if share > 0 else "no"
    words = f"ordered {placed}" + ("" if fit == "yes" else f", not {ev.when_said}" if fit == "no" else f", near {ev.when_said}")
    return _fact(fit, WEIGHTS["when"] * share, WEIGHTS["when"], words)


def _amount_fact(c: Candidate, ev: Evidence) -> dict[str, Any]:
    if c.paid is None or ev.amount is None:
        return _fact("unknown", 0.0, 0.0, "")
    gap = abs(c.paid - ev.amount)
    share = 1.0 if gap <= max(0.5, ev.amount * 0.01) else 0.7 if gap <= ev.amount * 0.05 else 0.3 if gap <= ev.amount * 0.15 else 0.0
    fit = "yes" if share >= 1.0 else "partly" if share > 0 else "no"
    shown = f"£{c.paid:,.2f} paid" if c.currency == "GBP" else f"{c.paid:,.2f} {c.currency} paid"
    return _fact(fit, WEIGHTS["amount"] * share, WEIGHTS["amount"], shown if fit == "yes" else f"{shown}, not {ev.amount_said}")


def _address_fact(c: Candidate, said: str) -> dict[str, Any]:
    if st.address_matches(said, c.address):
        return _fact("yes", WEIGHTS["address"], WEIGHTS["address"], f"to {said}")
    if _POSTCODE.match(said.strip()) and not c.has_zip:
        return _fact("unknown", 0.0, 0.0, "")
    return _fact("no", 0.0, WEIGHTS["address"], f"not to {said}")


def _email_fact(c: Candidate, said: str) -> dict[str, Any]:
    have = [e for e in (c.order_email, c.customer_email) if e]
    if not have:
        return _fact("unknown", 0.0, 0.0, "")
    if "@" in said and "." in said.split("@", 1)[1]:
        hit = said in have
        return _fact("yes" if hit else "no", WEIGHTS["email"] if hit else 0.0, WEIGHTS["email"], "the same email" if hit else "another email")
    part = re.sub(r"[^a-z0-9]", "", said)
    hit = len(part) >= 3 and any(part in re.sub(r"[^a-z0-9]", "", e) for e in have)
    return _fact("yes" if hit else "no", 2.0 if hit else 0.0, 2.0, f"email has '{said}'" if hit else f"email has no '{said}'")


def _number_fact(c: Candidate, said: str) -> dict[str, Any]:
    digits = re.sub(r"\D", "", said)
    if not digits:
        return _fact("unknown", 0.0, 0.0, "")
    if digits == c.digits:
        return _fact("yes", WEIGHTS["number"], WEIGHTS["number"], f"order {c.digits}")
    if len(digits) >= 2 and c.digits.endswith(digits):
        return _fact("yes", 1.5, 1.5, f"order number ends {digits}")
    return _fact("no", 0.0, WEIGHTS["number"] if len(digits) >= 4 else 1.5, f"order {c.digits}, not {digits}")


def score(c: Candidate, ev: Evidence, today: date) -> Scored:
    facts: dict[str, dict[str, Any]] = {}
    lines: list[dict[str, Any]] = []
    likeness: dict[str, Any] = {}
    if ev.name:
        likeness = names.name_likeness(ev.name, c.customer_name, c.parcel_name)
        lk = float(likeness.get("score") or 0.0)
        fit = "yes" if lk >= names.FITS else "partly" if lk >= names.DIFFERS else "no"
        facts["name"] = _fact(fit, WEIGHTS["name"] * lk if fit != "no" else 0.0, WEIGHTS["name"],
                              names.heard_words(ev.name, likeness))
    if ev.item:
        facts["item"], lines = _item_fact(c, ev.item)
    if ev.when is not None:
        facts["when"] = _when_fact(c, ev, today)
    if ev.amount is not None:
        facts["amount"] = _amount_fact(c, ev)
    if ev.address:
        facts["address"] = _address_fact(c, ev.address)
    if ev.email:
        facts["email"] = _email_fact(c, ev.email)
    if ev.number:
        facts["number"] = _number_fact(c, ev.number)
    points = sum(f["points"] for f in facts.values())
    possible = sum(f["possible"] for f in facts.values())
    return Scored(candidate=c, points=round(points, 3), possible=possible, facts=facts, lines=lines, likeness=likeness)


def rank(candidates: list[Candidate], ev: Evidence, today: date) -> list[Scored]:
    """Every order scored, best first; the newer of two that score the same."""
    unique: dict[str, Candidate] = {}
    for c in candidates:
        if c.order_id and (c.order_id not in unique or (c.has_zip and not unique[c.order_id].has_zip)):
            unique[c.order_id] = c
    scored = [score(c, ev, today) for c in unique.values()]
    return sorted(scored, key=lambda s: (s.points, s.confidence, s.candidate.placed_at), reverse=True)


# --------------------------------------------------------------------------- the verdict


def _plausible(s: Scored) -> bool:
    """Worth putting in front of him: enough of what he said fits, and never one fact alone when
    another fact he said is against it — the item alone is no more an answer than the name alone."""
    fitting = sum(1 for f in s.facts.values() if f.get("fit") in ("yes", "partly"))
    against = sum(1 for f in s.facts.values() if f.get("fit") == "no")
    if s.confidence < SHOWN or (s.whole() < 1 and s.fit("name") != "yes"):
        return False
    return fitting >= 2 or against == 0


def _clear(s: Scored, ev: Evidence) -> bool:
    if s.confidence < CLEAR or s.whole() < 1:
        return False
    if ev.name and s.fit("name") == "no":
        return s.whole() >= 2
    return True


def _digits_of(ref: Any) -> str:
    return str(ref or "").rsplit("/", 1)[-1]


def verdict(ranked: list[Scored], ev: Evidence, today: date, *, named: Any = ()) -> dict[str, Any]:
    """What to show and what to ask. See the module's comment for the rules.

    `named`: the customers the name he said IS (Shopify's ids, as the strict search found them).
    When the name is a real customer's and the order that fits best is somebody else's, it is a
    question, never the answer: "Alicia" and Ellis Moore's black cap is "Is it Ellis Moore's…?"."""
    if not ranked or not _plausible(ranked[0]):
        return {"kind": "none", "rows": []}
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    lead = top.points - (second.points if second else 0.0)
    theirs = {_digits_of(n) for n in named if n}
    someone_else = bool(theirs) and _digits_of(top.candidate.customer_id) not in theirs
    if _clear(top, ev) and lead >= MARGIN and not someone_else:
        out = {"kind": "one", "rows": [row(top, ev, today)]}
        if ev.name and top.fit("name") == "no":
            out["name_differs"] = True
        return out
    if someone_else and (_clear(top, ev) or lead >= MARGIN):
        return {"kind": "check", "rows": [row(top, ev, today)], "question": f"Is it {_who_when(top, today)}?",
                "someone_else": True}
    close = [s for s in ranked[:MAX_SHOWN] if _plausible(s) and top.points - s.points < MARGIN]
    if len(close) <= 1:
        return {"kind": "check", "rows": [row(top, ev, today)], "question": f"Is it {_who_when(top, today)}?"}
    shown = [row(s, ev, today) for s in close]
    named = [_who_when(s, today) for s in close]
    question = "Which one: " + ", ".join(named[:-1]) + f", or {named[-1]}?"
    return {"kind": "several", "rows": shown, "question": question}


def _who_when(s: Scored, today: date) -> str:
    c = s.candidate
    who = c.customer_name or (c.number and f"order {c.digits}") or "that order"
    item = (s.lines or c.items or [{}])[0].get("title") or ""
    bits = [b for b in (item, when.day_words(c.day, today) and f"on {when.day_words(c.day, today)}") if b]
    return f"{who}'s {' '.join(bits)}".strip() if bits else who


def why(s: Scored, ev: Evidence, today: date) -> str:
    """The one line he reads: "Alicia Grant — Loopback Hoodie (Grey / M), ordered Tue 22 Sep;
    name heard as 'Alysa'"."""
    c = s.candidate
    lines = s.lines or c.items[:1]
    goods = ", ".join(f"{line.get('title')}" + (f" ({line.get('variant')})" if line.get("variant") else "") for line in lines[:2] if line.get("title"))
    head = f"{c.customer_name or 'No customer'} — " + ", ".join(p for p in (goods, f"ordered {when.day_words(c.day, today)}" if c.day else "") if p)
    extras = []
    for fact in ("amount", "address", "email", "number"):
        detail = s.facts.get(fact)
        if detail and detail.get("fit") in ("yes", "partly") and detail.get("words"):
            extras.append(str(detail["words"]))
    if extras:
        head += ", " + ", ".join(extras)
    if ev.name and not s.likeness.get("exact"):
        name_fit = s.fit("name")
        if name_fit == "no":
            head += f"; the name on it is {c.customer_name or 'not given'}, not '{ev.name}'"
        else:
            head += f"; {names.heard_words(ev.name, s.likeness)}"
    return head


def row(s: Scored, ev: Evidence, today: date) -> dict[str, Any]:
    """One order as the model and the card are given it: who, what, when, and why."""
    c = s.candidate
    fits = [str(f["words"]) for k, f in s.facts.items() if f.get("fit") == "yes" and f.get("words") and k != "name"]
    if s.fit("name") in ("yes", "partly") and s.facts["name"].get("words"):
        fits.insert(0, str(s.facts["name"]["words"]))
    elif s.fit("name") == "yes":
        fits.insert(0, "the name")
    partly = [str(f["words"]) for k, f in s.facts.items() if f.get("fit") == "partly" and f.get("words") and k != "name"]
    misses = [str(f["words"]) for f in s.facts.values() if f.get("fit") == "no" and f.get("words")]
    shown_total = f"{c.total:.2f} {c.currency}" if c.total is not None else None
    return {
        "order_id": c.order_id, "order_number": c.number, "placed_at": c.placed_at,
        "customer_name": c.customer_name or None, "customer_id": c.customer_id or None,
        "customer_email": (c.order_email or c.customer_email) or None,
        "total": shown_total, "fulfillment": c.fulfillment or None, "payment": c.payment or None,
        "cancelled": c.cancelled or None,
        "why": why(s, ev, today), "fits": fits + partly, "misses": misses,
        "confidence": s.confidence,
        "matched_items": [{k: line.get(k) for k in ("title", "variant", "sku", "quantity", "variant_id")} for line in s.lines[:3]],
    }


INSTRUCTIONS = {
    "one": ("One order fits these facts clearly better than any other. Say it in one line from `why` — including "
            "how the name was heard — and do not ask which."),
    "one_name_differs": ("Everything but the name fits one order. Say whose order it is, that the name is not the one "
                         "he said, and ask him to confirm before doing anything with it."),
    "check": "One order might be it, but the facts do not prove it. Read `why` and ask if it is the one.",
    "check_someone_else": ("The name he said is a real customer's ({said}), but the order that fits the rest is "
                           "somebody else's. Say whose it is and ask `question`; do nothing with it until he says."),
    "several": "Several orders fit about as well. Ask `question`, in one short sentence; do not choose.",
}
