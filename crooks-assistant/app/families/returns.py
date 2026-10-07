"""Retired: the four returns rows this module registered, and nothing in their place.

It registered Taking an item back, Swapping an item, Sending a replacement and Sending it again,
each NOT_IMPLEMENTED, from app/returns/contract.py. They were retired because since 3 October
(DEC-066) returns and exchanges go through CROOKS Returns (app/tools/returns_tools.py), whose own
families — Reading returns and Acting on returns — say what CLIVE can do. The four rows told the
owner, and the model on every turn, that returns were not available while CLIVE could act on them.

No family is registered here. The file is kept only until it is deleted.
"""
