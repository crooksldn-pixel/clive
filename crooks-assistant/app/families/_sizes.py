"""The next size up, worked out from the product's own sizes and never guessed.

"Make a new order for them in the next size up" is one sentence to the owner and three facts
to the Mac: which option on the product IS the size, what order its values run in, and
whether the garment exists in that size in the same colour. Each of them can be wrong in a
way that sends a customer the wrong thing, so each is decided here from the product as
Shopify holds it, and each has a plain answer when it cannot be decided:

* The size option is the one CALLED a size ("Size", "Waist"). A product with no such option
  has no next size, and the answer says so rather than stepping through its colours.
* Its values are ordered as a size scale when they are one — letters (XXS … XXXL, and the
  paired S/M, M/L that streetwear uses) or numbers (6/8/10, 28/30/32) — and only then.
  Values that are neither ("Regular", "Tall", "One size") are not a scale anyone could step
  through, and nothing is stepped.
* The next size is the next one on that scale, in the SAME other options. When the product
  has no variant in that size and colour, that is the answer; the Mac does not skip to the
  size after it, because "one up" means one up.

Pure functions, no reads: the caller reads the product (app/families/order_create.py) and
hands it here, so every rule in this file is tested without a shop.
"""

from __future__ import annotations

import re
from typing import Any

# The letter scale, smallest first. A value is placed on it by its canonical spelling below.
LETTERS = ("XXXS", "XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL", "5XL")

# The other spellings of the same sizes, as shops write them.
_LETTER_ALIASES = {
    "3XS": "XXXS", "2XS": "XXS", "X-SMALL": "XS", "X SMALL": "XS", "EXTRA SMALL": "XS",
    "SMALL": "S", "SML": "S", "MEDIUM": "M", "MED": "M", "LARGE": "L", "LRG": "L",
    "X-LARGE": "XL", "X LARGE": "XL", "EXTRA LARGE": "XL", "2XL": "XXL", "XX-LARGE": "XXL",
    "XX LARGE": "XXL", "EXTRA EXTRA LARGE": "XXL", "3XL": "XXXL", "XXX-LARGE": "XXXL",
    "XXXX-LARGE": "4XL", "XXXXL": "4XL", "4X": "4XL", "XXXXXL": "5XL",
}

# A number, with the prefixes size labels carry: "UK 10", "EU 42", "W32", "32".
_NUMBER = re.compile(r"^(?:UK|EU|US|W|WAIST)?\s*(\d{1,3}(?:\.\d)?)$")

# The option names that ARE a size. "Waist" is how jeans are sold; "Length" is not a size
# anyone steps up through, so it is deliberately absent.
_SIZE_OPTION = re.compile(r"\bsize\b|\bwaist\b", re.I)


def _canonical(value: str) -> str:
    return " ".join(str(value or "").upper().replace("_", " ").split())


def letter_rank(value: str) -> float | None:
    """Where a letter size sits on the scale, or None. A pair ("S/M") sits between its two."""
    text = _canonical(value)
    if "/" in text:
        parts = [p.strip() for p in text.split("/")]
        ranks = [letter_rank(p) for p in parts]
        if len(parts) == 2 and all(r is not None for r in ranks) and ranks[1] == ranks[0] + 1:
            return (ranks[0] + ranks[1]) / 2
        return None
    text = _LETTER_ALIASES.get(text, text)
    return float(LETTERS.index(text)) if text in LETTERS else None


def number_rank(value: str) -> float | None:
    found = _NUMBER.match(_canonical(value))
    return float(found.group(1)) if found else None


def ladder(values: list[str]) -> tuple[list[str], str]:
    """The values in size order, and which scale ordered them: "letters", "numbers" — or
    ([], why) when they are not a scale. Duplicates on the scale (two spellings of M) are not
    a scale either: which of them is "one up" would be a guess."""
    values = [str(v) for v in values if str(v or "").strip()]
    if len(values) < 2:
        return [], "one size"
    for rank, basis in ((letter_rank, "letters"), (number_rank, "numbers")):
        ranks = [rank(v) for v in values]
        if all(r is not None for r in ranks) and len(set(ranks)) == len(ranks):
            return [v for _, v in sorted(zip(ranks, values, strict=True))], basis
    return [], "not a scale"


def size_option(product: dict[str, Any]) -> str:
    """The name of the product's size option, or "" when it has none."""
    for option in product.get("options") or []:
        name = str((option or {}).get("name") or "")
        if _SIZE_OPTION.search(name):
            return name
    return ""


def _options(variant: dict[str, Any]) -> dict[str, str]:
    return {str(o.get("name") or ""): str(o.get("value") or "")
            for o in variant.get("selectedOptions") or [] if isinstance(o, dict)}


def _values(product: dict[str, Any], option: str) -> list[str]:
    """The option's values as the product lists them, or — when the product did not say —
    in the order its variants carry them."""
    for entry in product.get("options") or []:
        if str((entry or {}).get("name") or "") == option and entry.get("values"):
            return [str(v) for v in entry["values"]]
    seen: list[str] = []
    for variant in product.get("variants") or []:
        value = _options(variant).get(option, "")
        if value and value not in seen:
            seen.append(value)
    return seen


def step(product: dict[str, Any], variant_id: str, by: int) -> dict[str, Any]:
    """The variant `by` sizes from `variant_id` on the same product, in the same other
    options — or why there is none, in the owner's words.

    `product` is {"title", "options": [{"name", "values"}], "variants": [{"id", "title",
    "selectedOptions", ...}]}, and may carry "start" — the variant itself, read on its own, which
    is where its options are taken from when given — and "complete": False when its variants were
    not all read. A read cut short is refused as incomplete: the size looked for may be among the
    variants not read, so "there is no such size" would be a guess (round-12 deploy review,
    S2Ba/F-03). Returns {"ok": True, "variant": <the variant>, "from": "M", "to": "L",
    "basis": "letters"} or {"ok": False, "why": "..."}.
    """
    title = str(product.get("title") or "That item")
    variants = [v for v in product.get("variants") or [] if isinstance(v, dict) and v.get("id")]
    if product.get("complete") is False:
        return {"ok": False, "why": f"I read only the first {len(variants)} of {title}'s variants, so the read was "
                                    "incomplete and I cannot say which is the next size."}
    given = product.get("start")
    if isinstance(given, dict) and str(given.get("id") or "") == str(variant_id):
        start = given
    else:
        start = next((v for v in variants if str(v["id"]) == str(variant_id)), None)
    if start is None:
        return {"ok": False, "why": f"I could not find that variant on {title}."}
    option = size_option(product)
    if not option:
        return {"ok": False, "why": f"{title} has no size option, so there is no other size to go to."}
    here = _options(start)
    current = here.get(option, "")
    order, basis = ladder(_values(product, option))
    if basis == "one size":
        return {"ok": False, "why": f"{title} comes in one size only."}
    if not order:
        listed = ", ".join(_values(product, option)[:6])
        return {"ok": False, "why": f"{title}'s sizes ({listed}) are not a scale I can step through, so I will not guess."}
    if current not in order:
        return {"ok": False, "why": f"{current or 'That size'} is not one of {title}'s sizes."}
    index = order.index(current) + int(by)
    if index >= len(order):
        return {"ok": False, "why": f"{current} is the largest size {title} comes in."}
    if index < 0:
        return {"ok": False, "why": f"{current} is the smallest size {title} comes in."}
    target = order[index]
    wanted = {**here, option: target}
    found = next((v for v in variants if _options(v) == wanted), None)
    if found is None:
        others = " ".join(value for name, value in here.items() if name != option)
        sizes = [s for s in order if any(_options(v) == {**here, option: s} for v in variants)]
        what = f"{others} {title}".strip()
        comes = f" It comes in {', '.join(sizes)}." if sizes else ""
        return {"ok": False, "why": f"There is no {what} in {target}.{comes}"}
    return {"ok": True, "variant": found, "from": current, "to": target, "basis": basis}


__all__ = ["LETTERS", "ladder", "letter_rank", "number_rank", "size_option", "step"]
