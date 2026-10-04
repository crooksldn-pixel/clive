"""Label documents: what a PDF is, whether customs paperwork must be printed, and what to print.

Evidence (Parcel2Go sandbox, 2026-10-05, eight paid orders to Germany and the USA):
  - the genuine 4x6 label is one 283 x 425 pt page (100 x 150 mm); A4 is 595 x 842 pt;
  - each commercial invoice is one A4 page;
  - services that file customs electronically (DPD, Landmark, OCS) return no additional
    documents; paper services return the copies to print (Evri International 3, UPS Access
    Point 4), to go in an envelope marked "Customs Documents" on the outside of the parcel;
  - "everything" = label pages + 1 invoice page + additional pages, in every order.

PDFs are read without a PDF library: Parcel2Go's files have plain page objects (no object
streams), so counting pages and reading MediaBox is reliable for them. Anything that doesn't
parse reads as unknown, never as a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shipping.models import CustomsMode, DocumentKind, Label, PageSize

PT_TO_MM = 25.4 / 72
_PAGE = re.compile(rb"/Type\s*/Page(?![s\w])")
_BOX = re.compile(rb"/MediaBox\s*\[\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\]")

ENVELOPE = 'Put them in an envelope marked "Customs Documents" on the outside of the parcel.'


def is_pdf(body: bytes | None) -> bool:
    return bool(body) and body.lstrip()[:5] == b"%PDF-"  # type: ignore[union-attr]


def pdf_pages(body: bytes) -> int:
    """Number of pages; 0 if it can't be read (object streams, not a PDF)."""
    if not is_pdf(body) or b"/ObjStm" in body:
        return 0
    return len(_PAGE.findall(body))


def pdf_page_sizes_mm(body: bytes) -> list[tuple[int, int]]:
    """(width, height) in whole millimetres for each MediaBox found, in file order."""
    sizes = []
    for x0, y0, x1, y1 in _BOX.findall(body):
        w = abs(float(x1) - float(x0)) * PT_TO_MM
        h = abs(float(y1) - float(y0)) * PT_TO_MM
        sizes.append((round(w), round(h)))
    return sizes


def _near(size: tuple[int, int], target: tuple[int, int], tol: int = 3) -> bool:
    (w, h), (tw, th) = sorted(size), sorted(target)
    return abs(w - tw) <= tol and abs(h - th) <= tol


def page_size(body: bytes) -> PageSize:
    sizes = set(pdf_page_sizes_mm(body))
    if not sizes:
        return PageSize.other
    kinds = set()
    for s in sizes:
        if _near(s, (100, 150)) or _near(s, (102, 152)):
            kinds.add(PageSize.label_4x6)
        elif _near(s, (210, 297)):
            kinds.add(PageSize.a4)
        else:
            kinds.add(PageSize.other)
    if len(kinds) > 1:
        return PageSize.mixed
    return kinds.pop()


@dataclass
class CustomsEvidence:
    """What the provider returned, for deciding whether customs paperwork must be printed."""

    route_requires_customs: bool
    additional_pages: int | None  # None: the request failed (unknown); 0: none exist (404)
    invoice_pages: int | None  # the commercial invoice on its own; None if unavailable
    label_pages: int | None
    all_pages: int | None  # label + invoice + additional, from the provider's "all" view


def customs_mode(e: CustomsEvidence) -> tuple[CustomsMode, int]:
    """(mode, copies to print). Electronic only when two independent views agree there is
    nothing extra to print; any gap or disagreement is UNKNOWN, never electronic."""
    if not e.route_requires_customs:
        return CustomsMode.not_required, 0
    if None in (e.additional_pages, e.label_pages, e.all_pages):
        return CustomsMode.unknown, 0
    invoice = e.invoice_pages or 0
    extra_in_all = e.all_pages - e.label_pages - invoice  # type: ignore[operator]
    if e.additional_pages == 0:
        return (CustomsMode.electronic, 0) if extra_in_all == 0 else (CustomsMode.unknown, 0)
    if extra_in_all != e.additional_pages:
        return CustomsMode.unknown, 0
    return CustomsMode.paper, e.additional_pages or 0


@dataclass
class PrintLine:
    text: str
    must_print: bool
    printer: str  # "thermal" (the 4x6 roll), "a4", or "" when nothing is printed


@dataclass
class PrintPlan:
    ready: bool  # everything needed to send the parcel is known and stored
    lines: list[PrintLine]
    extra_documents: int  # documents beyond the label that must be printed

    @property
    def summary(self) -> str:
        if not self.ready:
            return "Not ready to print yet"
        if not self.extra_documents:
            return "Ready to print"
        n = self.extra_documents
        return f"{n} extra document{'s' if n > 1 else ''} required"


def print_plan(label: Label) -> PrintPlan:
    lines: list[PrintLine] = []
    shipping = label.document(DocumentKind.shipping_label)
    if shipping and shipping.artifact_id:
        where = "4×6 thermal" if shipping.page_size == PageSize.label_4x6 else shipping.page_size
        printer = "thermal" if shipping.page_size == PageSize.label_4x6 else "a4"
        lines.append(PrintLine(f"Shipping label — {where}", True, printer))
    else:
        lines.append(PrintLine("Shipping label — not downloaded yet", True, ""))
    extra = 0
    if label.customs == CustomsMode.electronic:
        lines.append(PrintLine("Customs — filed electronically, nothing to print", False, ""))
    elif label.customs == CustomsMode.not_required:
        pass
    elif label.customs == CustomsMode.unknown:
        lines.append(PrintLine("Customs paperwork — still being checked", True, ""))
    for doc in label.documents:
        if doc.kind == DocumentKind.shipping_label or not doc.must_print:
            continue
        extra += 1
        name = doc.kind.value.replace("_", " ").capitalize()
        copies = f"print {doc.copies_required} copies" if doc.copies_required > 1 else "print"
        lines.append(PrintLine(f"{name} — {copies} ({doc.page_size})", True, "a4"))
    return PrintPlan(ready=label.complete, lines=lines, extra_documents=extra)
