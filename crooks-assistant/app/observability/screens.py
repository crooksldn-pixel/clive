"""A copy of the screen, made safe to keep: parsed, never pattern-matched as text.

`POST /telemetry/screen` takes markup from a page, and a page is not trusted to have cleaned it
(the 2026-09-26 deploy reviews, F-02): whatever arrives is parsed here and written back out
element by element, so quoting style, attribute order and entity tricks do not decide what
survives.

- Nothing that runs or fetches survives: script, iframe, object, embed, link, meta, base,
  style, template and noscript are dropped with everything inside them, every `on…` handler
  is dropped, `href` and every other URL-bearing attribute is dropped, and so is every `src`,
  inline images included: an image's pixels cannot be read here, and a picture of a label or a
  customer's message is as much the customer's as its text (the 2026-09-27 deploy review, round
  6, F-02). An image is kept as an empty box of its size. Comments, doctypes and processing
  instructions are dropped.
- What was typed never survives: an input's value and a textarea's text become a run of dots
  as long as what was there (at most 24); a hidden input's value is dropped.
- What is being said never survives either (round 9, F-02): the text of an element marked
  `data-spoken` (the ask bar's live words) and of everything inside it is masked the same way,
  and the words-bearing attributes there (a title, a label) are kept empty. `data-words` is kept
  empty wherever it is.
- Every other piece of text, and every attribute value, passes the timeline's own rule
  (`scrub_text`): credentials (Shopify, Anthropic, Google, Slack, GitHub, JWTs, bearer values),
  email addresses, phone numbers, postcodes, card numbers and the customer names this process
  has been shown.
- Attribute NAMES are written down too, so they come only from fixed lists written here: the
  HTML and SVG names the page draws with, the WAI-ARIA states and properties, and the data-
  names CLIVE's own pages use (a test holds that list to the pages). Nothing is read from disk
  to decide it, so the rule cannot change under a running process or go missing with a folder.
- Free-form drawing values are not kept at all: an SVG path's `d`, `points` and `transform`
  can spell anything in digits and spaces ("M 07700 900123" is a phone number), so they are
  dropped, and a copy draws without its icons. What is kept is a single short number
  (`x`, `r`, `width`…) or a viewBox of four; no leading zeros, at most four digits before
  the point.
- data- values that are free text by what they are for (a row's label, a question, a
  customer, what was said, a command's arguments) are kept empty; the rest are kept only as
  a short token (a state word, an id, a number).

The result draws as the page did, less what it must not keep.

What a copy carries beside the markup — what triggered it, the viewport, the page's own mode —
is not scrubbed but rebuilt (screen_metadata): only the keys the page is known to send, each to
its own kind of value, so no key and no value the page did not mean to send is ever written down.
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
# Free-form drawing values: digits and spaces can spell anything, so these are not kept.
_FREEFORM_DRAWING = frozenset({"d", "points", "transform"})
# One number each; kept only as a short number.
_NUMBER_ATTRS = frozenset({"x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "width", "height",
                           "stroke-width", "offset"})
# The parser lowers every attribute name; SVG's camel-cased ones are given back their case.
_SVG_CASE = {n.lower(): n for n in ("viewBox", "preserveAspectRatio", "gradientUnits", "gradientTransform",
                                    "patternUnits", "patternTransform", "clipPathUnits", "maskUnits", "markerWidth",
                                    "markerHeight", "refX", "refY", "stdDeviation", "textLength", "lengthAdjust")}
# Attribute names are kept only from this list and the ARIA and data- lists below: a name is
# written down too, and an arbitrary one could carry anything (F-02, third and fourth rounds).
_KNOWN = frozenset({
    "class", "id", "style", "type", "role", "title", "alt", "placeholder", "name", "for", "value", "src", "width",
    "height", "hidden", "disabled", "checked", "selected", "readonly", "tabindex", "rows", "cols", "maxlength",
    "min", "max", "step", "open", "lang", "dir", "colspan", "rowspan", "inert", "autocomplete", "enterkeyhint",
    "inputmode", "xmlns", "xmlns:xlink", "viewbox", "fill", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset", "fill-rule", "clip-rule",
    "opacity", "fill-opacity", "stroke-opacity", "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r",
    "rx", "ry", "offset", "stop-color", "preserveaspectratio", "focusable", "loading", "decoding", "draggable",
    "contenteditable", "spellcheck", "translate",
})
# The WAI-ARIA 1.2 states and properties (https://www.w3.org/TR/wai-aria-1.2/#state_prop_def),
# and no other aria- name: "aria-" followed by anything at all would let a name carry a word.
_ARIA = frozenset({
    "aria-activedescendant", "aria-atomic", "aria-autocomplete", "aria-braillelabel", "aria-brailleroledescription",
    "aria-busy", "aria-checked", "aria-colcount", "aria-colindex", "aria-colindextext", "aria-colspan",
    "aria-controls", "aria-current", "aria-describedby", "aria-description", "aria-details", "aria-disabled",
    "aria-dropeffect", "aria-errormessage", "aria-expanded", "aria-flowto", "aria-grabbed", "aria-haspopup",
    "aria-hidden", "aria-invalid", "aria-keyshortcuts", "aria-label", "aria-labelledby", "aria-level", "aria-live",
    "aria-modal", "aria-multiline", "aria-multiselectable", "aria-orientation", "aria-owns", "aria-placeholder",
    "aria-posinset", "aria-pressed", "aria-readonly", "aria-relevant", "aria-required", "aria-roledescription",
    "aria-rowcount", "aria-rowindex", "aria-rowindextext", "aria-rowspan", "aria-selected", "aria-setsize",
    "aria-sort", "aria-valuemax", "aria-valuemin", "aria-valuenow", "aria-valuetext",
})
# The data- names CLIVE's own pages use, written out (the 2026-09-27 deploy review, F-02: a list
# read from the web folder at run time is only as sound as that folder, and is stale for the
# life of the process after a deploy). tests/test_screen_privacy.py reads the pages and fails if
# one of them uses a data- name that is missing here, so a new one is added deliberately.
DATA_NAMES = frozenset({
    "data-action", "data-alpha", "data-archived", "data-area", "data-args", "data-ask", "data-attention",
    "data-branch", "data-build", "data-busy", "data-cancel", "data-col", "data-command", "data-compose",
    "data-customer", "data-customer-name", "data-dead", "data-depth", "data-direction", "data-dot", "data-dx",
    "data-family", "data-field", "data-for", "data-head", "data-job", "data-kind", "data-label",
    "data-listening-for", "data-lite", "data-mark", "data-mode", "data-name", "data-notify", "data-offer",
    "data-ok", "data-order", "data-overflow", "data-patched", "data-pending", "data-phase", "data-post",
    "data-pressed", "data-primed", "data-proposal", "data-ready", "data-recording", "data-ref", "data-render",
    "data-restored", "data-said", "data-scene-id", "data-set", "data-shell", "data-significance",
    "data-snap-dialog", "data-snap-left", "data-snap-top", "data-state", "data-tab", "data-task", "data-thread",
    "data-tone", "data-typable", "data-type", "data-undo-of", "data-unread", "data-unsaved", "data-workspace",
    # The ask bar's live words (web/live-voice.js): whether it shows some, whether it says what was
    # heard, and the mark that keeps the words themselves out of a copy of the screen.
    "data-heard", "data-spoken", "data-words",
    # Round 9, the screens remote: a pane's place, an item's place, and the screen a card opens
    # the remote for (its id, and its name, which is free text).
    "data-pane", "data-tick", "data-remote-screen", "data-remote-name",
    # Round 12, holding a record to put it on a screen (web/lift.js): which objective a row on the
    # home is, and which screen a tile in the Displays tray is. Ids, never words.
    "data-objective", "data-screen",
    # Objectives by touch, part B (web/distances.js, web/horizon.js): which of the three distances
    # the page is at, the horizon's own controls and rows, and a home row that will land late.
    # Words of the page's own ("home", "horizon", "row", "true"), never the owner's.
    "data-distance", "data-hz", "data-late",
    # [flow, DEC-068] The message card (web/ui.js `messageBlock`): its opaque key ("msg_" and 16
    # hex, minted on the Mac with nothing of who it is to in it), whether typed words are still on
    # their way ("true"), and its channel from a closed set. Never the message's words or address.
    "data-message", "data-typing", "data-channel",
})
# data- names whose values are free text by what they are for: kept, but empty. `data-words` is
# the ask bar's account of the live words it shows (round 9, F-02): whatever the page puts there,
# it is about what was said, so it is kept as a name and nothing more. So is `data-spoken`, the
# mark itself (round 11): the page writes it bare or "true", and a word written there instead is
# on the element that holds his words, so the mark is kept and its value never.
DATA_FREE_TEXT = frozenset({"data-args", "data-ask", "data-customer", "data-customer-name", "data-label",
                            "data-name", "data-said", "data-remote-name", "data-words", "data-spoken"})
# The mark the page puts on an element whose text is what the owner is saying, word by word (the
# ask bar's live words, web/live-voice.js): everything written inside it is masked like a
# textarea's, whatever it holds (round 9, F-02) — dictation is not a credential or a contact
# detail the timeline's rule would recognise, and it is his words all the same.
SPOKEN_MARK = "data-spoken"
# Attributes whose values are words a person reads. Inside a spoken element they are kept empty.
_WORDS_ATTRS = frozenset({"title", "alt", "placeholder", "value", "aria-label", "aria-valuetext", "aria-description",
                          "aria-placeholder", "aria-roledescription", "aria-braillelabel",
                          "aria-brailleroledescription", "aria-colindextext", "aria-rowindextext",
                          "aria-keyshortcuts"})
# Any other data- value: a short token (a state word, an id, a number) or nothing.
_DATA_TOKEN = re.compile(r"^[A-Za-z0-9_.:/#-]{0,64}$")
# What a drawing number may be: no leading zero, at most four digits before the point.
_NUM = r"-?(?:0|[1-9]\d{0,3})(?:\.\d{1,3})?"
_NUMBER_VALUE = re.compile(rf"^{_NUM}(?:px|%|em|rem)?$")
_VIEWBOX_VALUE = re.compile(rf"^{_NUM}(?:[\s,]+{_NUM}){{3}}$")
_NAME = re.compile(r"^[a-zA-Z_:][-a-zA-Z0-9_:.]{0,60}$")
_TAG = re.compile(r"^[a-zA-Z][a-zA-Z0-9:-]{0,40}$")
_CSS_URL = re.compile(r"url\s*\([^)]*\)", re.I)


# An identifier as CLIVE's pages write one where a field, a control, a card or a state is named:
# lower-case letters and digits joined by . _ : / # or - (`composer-subject`, `ask_bar`,
# `order.add_note`, `br_left`, `1938`), or a Shopify id; at most 64 characters. A page's value in
# such a field that is not one is withheld wherever the report would print it (round 11,
# F-OBS2-01: app/observability/visible.py, report.py, touch.py): a customer's name is not an
# identifier, and nothing that names a thing needs to be anything else.
PAGE_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[_.:/#-][a-z0-9]+)*|gid://shopify/[A-Za-z]+/[0-9]+")
WITHHELD = "[withheld]"


def page_identifier(value: Any) -> str:
    """A value a page sent, as the report may name it: an identifier as it is, anything else
    WITHHELD ('' stays '')."""
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    return text if len(text) <= 64 and PAGE_IDENTIFIER.fullmatch(text) else WITHHELD


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
        # The elements open now, each with whether it is, or is inside, a spoken one.
        self._open: list[tuple[str, bool]] = []

    def _spoken(self) -> bool:
        return bool(self._open) and self._open[-1][1]

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
        spoken = self._spoken() or any(k.lower() == SPOKEN_MARK for k, _v in attrs)
        kept = self._attrs(name, attrs, spoken=spoken)
        text = f"<{tag}{kept}{' /' if closed else ''}>"
        self.out.append(text)
        if not closed and name not in _VOID:
            self._open.append((name, spoken))
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
        # Closes the innermost open element of its name, and whatever was left open inside it.
        for at in range(len(self._open) - 1, -1, -1):
            if self._open[at][0] == name:
                del self._open[at:]
                break
        self.out.append(f"</{tag}>")

    # ---- text
    def handle_data(self, data: str) -> None:
        if self._dropping or not data:
            return
        if self._in_textarea or self._spoken():
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
    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]], *, spoken: bool = False) -> str:
        typed = tag == "input"
        kind = next((str(v or "").lower() for k, v in attrs if k.lower() == "type"), "")
        parts: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if not _NAME.fullmatch(raw_name) or name.startswith("on") or name in _URL_ATTRS:
                continue
            if name in _FREEFORM_DRAWING:
                continue
            if name not in _KNOWN and name not in _ARIA and name not in DATA_NAMES:
                continue
            value = "" if raw_value is None else str(raw_value)
            if spoken and name in _WORDS_ATTRS:
                value = ""
            elif typed and name == "value":
                if kind in ("hidden", "password"):
                    continue
                value = _mask(value)
            elif name == "src":
                continue
            elif name == "style":
                value = _clean(_CSS_URL.sub("none", value))
            elif name in _NUMBER_ATTRS:
                # One short number, or the attribute is not kept at all.
                if not _NUMBER_VALUE.fullmatch(value.strip()):
                    continue
                value = value.strip()
            elif name == "viewbox":
                if not _VIEWBOX_VALUE.fullmatch(value.strip()):
                    continue
                value = " ".join(value.replace(",", " ").split())
            elif name in DATA_FREE_TEXT:
                value = ""
            elif name.startswith("data-"):
                value = _clean(value)
                if not _DATA_TOKEN.fullmatch(value):
                    value = ""
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


# What the page sends beside the markup (web/telemetry.js wantScreen and copyScreen), key by key.
# Anything else is not written down, whatever it is called.
_TRIGGER_TOKENS = ("kind", "status", "target", "control", "outcome", "reason", "code")
_TRIGGER_PLACES = ("file", "src", "path")
_TOKEN = re.compile(r"^[A-Za-z0-9_.:#-]{1,64}$")


def _token(value: Any) -> str | None:
    """A short word the page uses as a label (a state, a code), and only one the timeline's
    rule would keep as it is: a token-shaped credential is a word too."""
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    return text if _TOKEN.fullmatch(text) and _clean(text) == text else None


def _place(value: Any) -> str | None:
    """Where an error happened, as a path on this app: never a host, a query or a fragment."""
    from urllib.parse import urlsplit

    if not isinstance(value, str):
        return None
    try:
        path = urlsplit(value[:400]).path
    except ValueError:
        return None
    path = _clean(path)[:120]
    return path if re.fullmatch(r"[A-Za-z0-9_./-]{1,120}", path or "") else None


def _number(value: Any, top: float) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return max(0, min(value, top))


def screen_metadata(kind: str, value: Any) -> dict[str, Any] | None:
    """One of a copy's metadata blocks, rebuilt from the keys the page sends and nothing else
    (round 6, F-02): `trigger` (what event it was, where), `viewport` (three numbers) or `body`
    (the page's class words and mode). Values are tokens, numbers or an app path; a message is
    scrubbed text. None for anything else."""
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    if kind == "trigger":
        for key in _TRIGGER_TOKENS:
            token = _token(value.get(key))
            if token is not None:
                out[key] = token
        for key in _TRIGGER_PLACES:
            place = _place(value.get(key))
            if place is not None:
                out[key] = place
        line = _number(value.get("line"), 10_000_000)
        if line is not None:
            out["line"] = int(line)
        if isinstance(value.get("message"), str):
            out["message"] = _clean(" ".join(value["message"][:1200].split()))[:300]
    elif kind == "viewport":
        for key, top in (("w", 20_000), ("h", 20_000), ("dpr", 8)):
            number = _number(value.get(key), top)
            if number is not None:
                out[key] = number
    elif kind == "body":
        words = str(value.get("class") or "")[:400].split() if isinstance(value.get("class"), str) else []
        out["class"] = " ".join(w for w in words[:24] if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", w) and _clean(w) == w)
        mode = _token(value.get("mode"))
        out["mode"] = mode or ""
    else:
        return None
    return out
