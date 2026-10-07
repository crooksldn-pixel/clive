"""Returns, exchanges, replacements and resends (§21): the contract, not the change.

    app/returns/contract.py     the request shapes, what each change would be, and the refusal

Nothing here mutates anything, and nothing here is a second mutation path. When the scope is
granted the reviewed mutation becomes a `WriteSpec` through app/actions/engine.py like every
other change.

Nothing registers the four as capability families any more: since DEC-066 returns and exchanges
go through CROOKS Returns, whose own families say what CLIVE can do. The contract is kept until
it is deleted.
"""

from app.returns.contract import (
    CAPABILITIES,
    REASONS,
    InvalidRequest,
    NotAvailable,
    ReturnLine,
    ReturnRequest,
    ReviewedCapability,
    get,
    plan,
    stage,
    words,
)

__all__ = [
    "CAPABILITIES", "InvalidRequest", "NotAvailable", "REASONS", "ReturnLine", "ReturnRequest",
    "ReviewedCapability", "get", "plan", "stage", "words",
]
