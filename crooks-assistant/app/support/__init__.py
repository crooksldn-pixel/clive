"""The Customer Support Investigator, V1: one enquiry about an existing order, investigated
read-only, with the evidence exposed and a reply drafted for the owner to approve.

    app/support/enquiry.py      what the customer is asking, and the identifiers they gave
    app/support/evidence.py     the evidence bundle: what was read, from where, when
    app/support/investigate.py  identification, verified facts, inference, unknowns
    app/support/reply.py        the customer-facing draft, built only from verified facts
    app/support/report.py       the internal summary the owner reads to check the conclusion

Nothing in this package writes anywhere: no email, no SMS, no refund, no cancellation, no
order, fulfilment, tracking or note change. The draft is text for the owner; sending it, or
doing anything the customer asks for, is a separate act that this package cannot perform.
"""

from __future__ import annotations

from typing import Any

from app.support.enquiry import Enquiry, parse_enquiry
from app.support.evidence import EvidenceBundle, gather
from app.support.investigate import investigate
from app.support.reply import draft_reply
from app.support.report import render_markdown

__all__ = [
    "Enquiry",
    "EvidenceBundle",
    "draft_reply",
    "gather",
    "investigate",
    "investigate_bundle",
    "parse_enquiry",
    "render_markdown",
    "run_investigation",
]


def investigate_bundle(bundle: EvidenceBundle, *, signature: str = "CROOKS") -> dict[str, Any]:
    """The whole read-only pipeline over an evidence bundle that was already gathered: the
    investigation, the draft and the internal summary, as one JSON-serialisable document."""
    investigation = investigate(bundle)
    draft = draft_reply(investigation, bundle, signature=signature)
    return {
        "enquiry": bundle.enquiry,
        "identification": investigation.identification,
        "what_happened": investigation.what_happened,
        "facts": [f.as_dict() for f in investigation.facts],
        "inferences": [f.as_dict() for f in investigation.inferences],
        "unknowns": [f.as_dict() for f in investigation.unknowns],
        "owner_decisions": list(investigation.owner_decisions),
        "evidence": bundle.evidence_index(),
        "sources": dict(bundle.sources),
        "problems": list(bundle.problems),
        "reply_draft": draft.as_dict(),
        "approval": {
            "required": True,
            "state": "awaiting_owner",
            "external_effects_so_far": "none",
            "what_approval_would_permit": "sending the reply, by the owner, outside this tool",
        },
        "markdown": render_markdown(investigation, draft, bundle),
    }


async def run_investigation(text: str, *, subject: str = "", sender_email: str = "", gather_with,
                            signature: str = "CROOKS") -> dict[str, Any]:
    """Parse the enquiry, gather the evidence with the given readers, investigate, draft."""
    enquiry = parse_enquiry(text, subject=subject, sender_email=sender_email)
    bundle = await gather(enquiry, **gather_with)
    return investigate_bundle(bundle, signature=signature)
