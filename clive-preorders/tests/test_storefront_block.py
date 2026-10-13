"""The storefront block sits inside the theme's product form on many themes (Horizon, and the
CROOKS "Product Record" section). Nothing in it may stop that form being sent, or ride along."""

import re
from html.parser import HTMLParser
from pathlib import Path

BLOCK = (
    Path(__file__).resolve().parents[2]
    / "crooks-returns/extensions/clive-preorders/blocks/preorder.liquid"
)


class Fields(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: list[dict[str, str | None]] = []
        self.forms = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "form":
            self.forms += 1
        if tag in ("input", "select", "textarea"):
            self.fields.append(dict(attrs))


def test_the_signup_never_blocks_or_joins_the_themes_add_to_cart_form():
    markup = re.sub(r"{%-?\s*comment.*?endcomment\s*-?%}", "", BLOCK.read_text(), flags=re.S)
    markup = re.sub(r"{%-?.*?-?%}|{{-?.*?-?}}", "", markup, flags=re.S)
    parsed = Fields()
    parsed.feed(markup)
    assert parsed.forms == 0  # a form nested in the product form is dropped by the browser
    assert parsed.fields
    for field in parsed.fields:
        # A field in the theme's form is validated when Add to cart is pressed: a hidden, empty,
        # required email stops the sale. `form` naming no form leaves it in no form at all.
        assert field.get("form"), field
