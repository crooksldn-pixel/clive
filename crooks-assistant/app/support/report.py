"""The internal summary: what happened, in three kinds of statement, with the evidence beside it.

Written for the owner to check a conclusion against the source systems before approving the
draft. Nothing here is customer-facing.
"""

from __future__ import annotations

from app.support.evidence import EvidenceBundle
from app.support.investigate import Investigation
from app.support.reply import ReplyDraft


def render_markdown(investigation: Investigation, draft: ReplyDraft, bundle: EvidenceBundle) -> str:
    ident = investigation.identification
    enquiry = bundle.parsed_enquiry
    out: list[str] = ["# Support investigation (read-only, V1)", ""]
    out.append(f"Gathered at {bundle.gathered_at}. Sources: " + ", ".join(f"{k}: {v}" for k, v in bundle.sources.items()) + ".")
    out.append("")
    out.append("## The enquiry")
    out.append("")
    out.append(f"- Kind: **{enquiry.kind}**" + (f"; subject: {enquiry.subject!r}" if enquiry.subject else ""))
    out.append(f"- Identifiers given: order number(s) {', '.join(enquiry.order_numbers) or 'none'}; sender {'given' if enquiry.sender_email else 'unknown'}")
    for ask in enquiry.asks:
        out.append(f"- Asks: {ask}")
    out.append("")
    out.append("## Identification")
    out.append("")
    out.append(f"- Status: **{ident.get('status')}** (confidence: {ident.get('confidence')})")
    if ident.get("order_number"):
        out.append(f"- Order: {ident.get('order_number')}")
    for reason in ident.get("reasons") or []:
        out.append(f"- {reason}")
    for c in ident.get("candidates") or []:
        out.append(f"- Candidate: {c.get('order_number')} placed {c.get('placed_at')}, {c.get('fulfillment')}" + (" (same sender)" if c.get("same_sender") else ""))
    out.append("")
    out.append("## What happened")
    out.append("")
    out.append(investigation.what_happened or "(nothing could be established)")
    out.append("")
    for title, findings in (("Verified facts", investigation.facts), ("Reasonable inference", investigation.inferences), ("Unknown", investigation.unknowns)):
        out.append(f"## {title}")
        out.append("")
        if not findings:
            out.append("- none")
        for f in findings:
            out.append(f"- {f.text}" + (f"  \n  evidence: {', '.join(f.evidence)}" if f.evidence else ""))
        out.append("")
    out.append("## Evidence used")
    out.append("")
    out.append("| ref | source | kind | summary |")
    out.append("| --- | --- | --- | --- |")
    for e in bundle.evidence_index():
        out.append(f"| `{e['ref']}` | {e['source']} | {e['kind']} | {str(e['summary']).replace('|', '/')} |")
    out.append("")
    if investigation.owner_decisions:
        out.append("## Decisions for the owner")
        out.append("")
        for d in investigation.owner_decisions:
            out.append(f"- {d}")
        out.append("")
    out.append("## Reply draft (requires the owner's approval; nothing has been sent)")
    out.append("")
    out.append(f"Subject: {draft.subject}")
    out.append("")
    out.append("```")
    out.append(draft.body)
    out.append("```")
    out.append("")
    out.append("Based on: " + ", ".join(f"`{r}`" for r in draft.based_on))
    if draft.not_said:
        out.append("")
        out.append("Deliberately not said (unknown): " + "; ".join(draft.not_said))
    out.append("")
    return "\n".join(out)
