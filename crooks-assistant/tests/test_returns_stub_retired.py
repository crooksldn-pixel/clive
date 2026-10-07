"""The returns stub is retired: CLIVE no longer says returns are not available.

app/families/returns.py registered four NOT_IMPLEMENTED rows from app/returns/contract.py —
Taking an item back, Swapping an item, Sending a replacement, Sending it again — and they reached
every model turn while CROOKS Returns (DEC-066) could act on returns. These are the oracles that
the four are gone from the families table and the per-turn block, that CROOKS Returns' own
families are still there as they were, and that the module left behind holds nothing but its
header. The guards that no Shopify return mutation is registered or reviewed are
tests/test_returns.py and tests/test_crooks_returns.py, unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from app.returns import contract

ROOT = Path(__file__).resolve().parent.parent
RETIRED = ("return_create", "return_exchange", "replacement_item", "resend_shipment")
LABELS = ("Taking an item back", "Swapping an item", "Sending a replacement", "Sending it again")


async def _table() -> dict:
    import app.tools.returns_tools  # noqa: F401
    from app.capabilities import families
    from app.families import load_all

    load_all()
    return await families.states(None)


async def test_the_four_rows_are_not_in_the_families_table():
    from app.capabilities import families

    table = await _table()
    assert table, "the family table did not load — the check would pass vacuously"
    assert sorted(RETIRED) == sorted(contract.CAPABILITIES)
    for key in RETIRED:
        assert families.get(key) is None, f"{key} is still registered as a family"
        assert key not in table, f"{key} still has a row: {table.get(key)}"


async def test_the_per_turn_block_no_longer_says_returns_are_not_available():
    from app.routes.turn import _family_lines

    table = await _table()
    lines = _family_lines(SimpleNamespace(family_states_table=table))
    block = "\n".join(lines)
    assert block, "the per-turn block is empty — the check would pass vacuously"
    for label in LABELS:
        assert label not in block, f"{label!r} is still said on every turn:\n{block}"
    assert "write_returns" not in block, block


async def test_crooks_returns_families_are_still_there_as_they_were():
    """With no CROOKS Returns keys stored (the test keychain has none), both families say
    DISCONNECTED for that one reason, as they did before the stub was retired."""
    from app.routes.turn import _family_lines
    from app.tools import returns_tools

    table = await _table()
    assert table["returns_reads"]["label"] == "Reading returns"
    assert table["returns_actions"]["label"] == "Acting on returns"
    assert table["returns_reads"]["tools"] == list(returns_tools.READS)
    assert table["returns_actions"]["operations"] == [returns_tools.WRITE]
    for key, probe in (("returns_reads", returns_tools._probe_reads), ("returns_actions", returns_tools._probe_actions)):
        probed = await probe(None)
        assert (table[key]["state"], table[key]["detail"]) == (probed["state"], probed["detail"])
        assert (table[key]["state"], table[key]["detail"]) == ("DISCONNECTED", returns_tools.NO_KEYS)
        assert table[key]["offerable"] is False
    block = "\n".join(_family_lines(SimpleNamespace(family_states_table=table)))
    assert f"DISCONNECTED — {returns_tools.NO_KEYS}: Acting on returns, Reading returns" in block, block


def test_the_retired_module_is_only_its_header():
    from app.families import load_all, loaded

    path = ROOT / "app" / "families" / "returns.py"
    tree = ast.parse(path.read_text())
    assert len(tree.body) == 1 and ast.get_docstring(tree), "app/families/returns.py holds more than its header"
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    header = ast.get_docstring(tree)
    assert "CROOKS Returns" in header and "DEC-066" in header and "deleted" in header
    load_all()
    assert "returns" in loaded(), "the empty module should still load, registering nothing"


def test_the_contract_is_kept_and_says_nothing_registers_it():
    assert set(contract.CAPABILITIES) == set(RETIRED)
    for path in ("app/returns/contract.py", "app/returns/__init__.py"):
        doc = " ".join((ast.get_docstring(ast.parse((ROOT / path).read_text())) or "").split())
        assert "app/families/returns.py." not in doc and "is in app/families/returns.py" not in doc, path
        assert "Nothing registers the four as capability families any more" in doc, path
        assert "kept until it is deleted" in doc, path
