"""A second branch of a conversation, made directly, for the tests that hold per-branch isolation.

The owner can no longer divide the orb: user-facing Split was retired by DEC-050, and its routes
(fork, focus, background, merge and cancel in app/routes/branches.py) were deleted on the owner's
ruling of 8 October (DEC-071, ruling 37). What each branch keeps for itself — its own record,
list, trail, binding, pending changes and turn — is still CLIVE's code (app/session, app/routes/
turn.py, app/commands.py, app/actions), which DEC-050 keeps where it carries a responsibility of
its own. The tests that hold that code used `POST /branches/fork` to get a second branch; they
make it here instead. It inherits nothing from the first: what a fork inherited was Split's own
contract, and went with it.
"""

from __future__ import annotations

from app.session.branch import Branch, new_branch_id


def second_half(session, *, label: str = "second") -> str:
    """Add a second, ACTIVE branch beside the conversation's first, leave the focus where it was,
    and return the new branch's id."""
    first = session.branch()
    child = Branch(branch_id=new_branch_id(), session_id=session.session_id,
                   parent_id=first.branch_id, label=label)
    session.branches[child.branch_id] = child
    return child.branch_id
