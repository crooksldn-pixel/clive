"""A copy of the screen, made safe to keep: parsed, never pattern-matched as text.

`POST /telemetry/screen` takes markup from a page, and a page is not trusted to have cleaned it
(the 2026-09-26 deploy reviews, F-02): whatever arrives is parsed here and written back out
element by element, so quoting style, attribute order and entity tricks do not decide what
survives.

- Nothing that runs or fetches survives: script, iframe, object, embed, link, meta, base,
  style, template and noscript are dropped with everything inside them, every `on…` handler
  is dropped, `href` and every other URL-bearing attribute is dropped, and `src` survives only
  as an inline image (a canvas the page drew). Comments, doctypes and processing
  instructions are dropped.
- What was typed never survives: an input's value and a textarea's text become a run of dots
  as long as what was there (at most 24); a hidden input's value is dropped.
- Every other piece of text, and every attribute value, passes the timeline's own rule
  (`scrub_text`): credentials (Shopify, Anthropic, Google, Slack, GitHub, JWTs, bearer values),
  email addresses, phone numbers, postcodes, card numbers and the customer names this process
  has been shown. Drawing attributes (an SVG path's `d`, `points`, `viewBox`, `transform`) are
  numbers that look like phone numbers to that rule, so they get the credential rule only.

The result draws as the page did, less what it must not keep.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from typing import Any

# Dropped with everything inside them.
_DROP = frozenset({"script", "iframe", "object", "embed", "link", "meta", "base", "style", "template", "noscript",
                   "frame", "frameset", "applet", "audio", "video", "source", "track", "portal"})
_VOID = frozenset({"area", "br", "col", "hr", "img", "input", "wbr", "path", "circle", "rect", "line", "polyline",
                   "polygon", "ellipse", "use", "stop"})
# Attributes that carry a URL, and so a place for a token or a tracking address to hide.
_URL_ATTRS = frozenset({"href", "xlink:href", "action", "formaction", "poster", "ping", "srcset", "background",
                        "cite", "longdesc", "manifest", "codebase", "data", "lowsrc", "dynsrc", "usemap"})
_DRAWING = frozenset({"d", "points", "viewbox", "transform", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx",
                      "ry", "width", "height", "stroke-width", "offset"})
# The parser lowers every attribute name; SVG's camel-cased ones are given back their case.
_SVG_CASE = {n.lower(): n for n in ("viewBox", "preserveAspectRatio", "gradientUnits", "gradientTransform",
                                    "patternUnits", "patternTransform", "clipPathUnits", "maskUnits", "markerWidth",
                                    "markerHeight", "refX", "refY", "stdDeviation", "textLength", "lengthAdjust")}
# Attribute names are kept only from this list, or as aria-/data- names of letters and hyphens:
# a name is written down too, and an arbitrary one could carry anything (F-02, third round).
_KNOWN = frozenset({
    "class", "id", "style", "type", "role", "title", "alt", "placeholder", "name", "for", "value", "src", "width",
    "height", "hidden", "disabled", "checked", "selected", "readonly", "tabindex", "rows", "cols", "maxlength",
    "min", "max", "step", "open", "lang", "dir", "colspan", "rowspan", "inert", "autocomplete", "enterkeyhint",
    "inputmode", "xmlns", "xmlns:xlink", "viewbox", "d", "points", "fill", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "fill-rule", "clip-rule",
    "opacity", "fill-opacity", "stroke-opacity", "transform", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r",
    "rx", "ry", "offset", "stop-color", "preserveaspectratio", "focusable", "loading", "decoding", "draggable",
    "contenteditable", "spellcheck", "translate",
})
_OPEN_NAME = re.compile(r"^(?:aria|data)-[a-z]+(?:-[a-z]+){0,5}$")
# What a drawing attribute may hold: numbers and path or transform words, nothing else; and no
# run of seven or more digits, which no coordinate has and a phone number does.
_DRAWING_VALUE = re.compile(r"^(?:[\s,.+\-eE0-9MmLlHhVvCcSsQqTtAaZz()]|matrix|translate|scale|rotate|skewX|skewY)*$")
_LONG_NUMBER = re.compile(r"\d{7,}")
_NAME = re.compile(r"^[a-zA-Z_:][-a-zA-Z0-9_:.]{0,60}$")
_TAG = re.compile(r"^[a-zA-Z][a-zA-Z0-9:-]{0,40}$")
_INLINE_IMAGE = re.compile(r"^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/=\s]+$")
_CSS_URL = re.compile(r"url\s*\([^)]*\)", re.I)


def _mask(text: str) -> str:
    return "•" * min(24, len(text)) if text else ""


def _clean(text: str) -> str:
    from app.observability.timeline import scrub_text

    return scrub_text(text)


class _Sanitiser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._dropping = 0          # depth inside a dropped element
        self._drop_tag: list[str] = []
        self._in_textarea = 0

    # ---- elements
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closed=True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, closed: bool) -> None:
        name = tag.lower()
        if self._dropping:
            if name == self._drop_tag[-1] and not closed and name not in _VOID:
                self._dropping += 1
            return
        if name in _DROP:
            if not closed and name not in _VOID:
                self._dropping = 1
                self._drop_tag.append(name)
            return
        if not _TAG.fullmatch(tag):
            return
        kept = self._attrs(name, attrs)
        text = f"<{tag}{kept}{' /' if closed else ''}>"
        self.out.append(text)
        if name == "textarea" and not closed:
            self._in_textarea += 1

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if self._dropping:
            if name == self._drop_tag[-1]:
                self._dropping -= 1
                if not self._dropping:
                    self._drop_tag.pop()
            return
        if name in _DROP or not _TAG.fullmatch(tag):
            return
        if name == "textarea" and self._in_textarea:
            self._in_textarea -= 1
        self.out.append(f"</{tag}>")

    # ---- text
    def handle_data(self, data: str) -> None:
        if self._dropping or not data:
            return
        if self._in_textarea:
            self.out.append(_mask(data))
            return
        self.out.append(escape(_clean(data), quote=False))

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    # ---- attributes
    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        typed = tag == "input"
        kind = next((str(v or "").lower() for k, v in attrs if k.lower() == "type"), "")
        parts: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if not _NAME.fullmatch(raw_name) or name.startswith("on") or name in _URL_ATTRS:
                continue
            if name not in _KNOWN and not (_OPEN_NAME.fullmatch(name) and len(name) <= 40 and _clean(name) == name):
                continue
            value = "" if raw_value is None else str(raw_value)
            if typed and name == "value":
                if kind in ("hidden", "password"):
                    continue
                value = _mask(value)
            elif name == "src":
                if not _INLINE_IMAGE.fullmatch(value):
                    continue
            elif name == "style":
                value = _clean(_CSS_URL.sub("none", value))
            elif name in _DRAWING:
                # Numbers only: a drawing value that is anything else is not kept at all.
                if not _DRAWING_VALUE.fullmatch(value) or _LONG_NUMBER.search(value):
                    continue
            else:
                value = _clean(value)
            parts.append(f' {_SVG_CASE.get(name, raw_name)}="{escape(value, quote=True)}"')
        return "".join(parts)


def sanitise_markup(html: str) -> str:
    """Untrusted markup, parsed and written back out with only what may be kept."""
    parser = _Sanitiser()
    try:
        parser.feed(str(html or ""))
        parser.close()
    except Exception:  # noqa: BLE001 - markup that cannot be parsed is not kept at all
        return ""
    return "".join(parser.out)


def sanitise_metadata(value: Any) -> Any:
    """Everything else a copy carries (what triggered it, the body's class, the viewport), by
    the rule every timeline event passes: withheld keys, credentials and contact details out."""
    from app.observability.timeline import scrub

    return scrub(value)
