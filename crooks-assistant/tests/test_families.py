"""The capability families: one table, three readers.

A family's state has more shapes than ready/blocked — written but the scope is missing, not
offered by the store, no provider connected, not built. These assert that a registered family
reaches /health and the manifest with its state, that the model is told the ones it must not
attempt, and that the state derivation from the per-operation table is right.
"""

from __future__ import annotations

import pytest

from app.capabilities import families


@pytest.fixture
def family():
    key = "test_family_zz"
    fam = families.register(families.CapabilityFamily(
        key=key, label="Test family", area="orders", what="a thing the tests can do",
        operations=("test_op",), scopes=("write_test",), state="READY",
    ))
    try:
        yield fam
    finally:
        families.REGISTRY.pop(key, None)


def test_a_state_must_be_one_of_the_seven():
    with pytest.raises(ValueError):
        families.register(families.CapabilityFamily(key="bad_zz", label="x", area="orders", what="x", state="MAYBE"))
    families.REGISTRY.pop("bad_zz", None)


@pytest.mark.asyncio
async def test_the_state_follows_the_operation_table(family):
    ready = await families.states(None, operations={"test_op": {"state": "ready", "detail": "ready", "scope": "write_test"}})
    assert ready[family.key]["state"] == "READY" and ready[family.key]["offerable"] is True
    missing = await families.states(None, operations={"test_op": {"state": "blocked", "detail": "blocked — Shopify write_test scope missing", "scope": "write_test"}})
    assert missing[family.key]["state"] == "MISSING_SCOPE" and missing[family.key]["scope"] == "write_test" and not missing[family.key]["offerable"]
    off = await families.states(None, operations={"test_op": {"state": "disabled", "detail": "disabled — CROOKS_WRITES_ENABLED=false", "scope": "write_test"}})
    assert off[family.key]["state"] == "READ_ONLY"


@pytest.mark.asyncio
async def test_a_probe_has_the_last_word_and_a_failing_probe_is_a_state():
    async def not_offered(_runtime):
        return {"state": "NOT_SUPPORTED_BY_STORE", "detail": "the store has no store credit"}

    async def broken(_runtime):
        raise RuntimeError("no network")

    for key, probe in (("probe_zz", not_offered), ("broken_zz", broken)):
        families.register(families.CapabilityFamily(key=key, label=key, area="customers", what="x", state="READY", probe=probe))
    try:
        table = await families.states(None, operations={})
        assert table["probe_zz"]["state"] == "NOT_SUPPORTED_BY_STORE"
        assert table["broken_zz"]["state"] == "TEMPORARILY_UNAVAILABLE" and "RuntimeError" in table["broken_zz"]["detail"]
    finally:
        families.REGISTRY.pop("probe_zz", None)
        families.REGISTRY.pop("broken_zz", None)


def test_the_model_is_told_what_not_to_attempt(family):
    table = {
        family.key: {"label": "Test family", "state": "MISSING_SCOPE", "detail": "blocked — Shopify write_test scope missing"},
        "other": {"label": "Other", "state": "READY", "detail": "ready"},
    }
    lines = families.words(table)
    # State and reason first, then who: the model reads this to answer "can you do X", and
    # the state is the answer. The instruction is at the head of the block, once, rather than
    # on every line (app/routes/turn.py FAMILY_LINE_PREFIX).
    assert any("MISSING_SCOPE" in line and "Test family" in line for line in lines), lines
    assert not any("Do not attempt" in line for line in lines), lines
    # The ready ones are NOT on the prompt: they are the tools the model is offered, and
    # `runtime.withheld_by_family` has taken the rest away, so a line saying "READY" is model
    # context spent to say nothing — fifteen of them, every turn (brief section 25).
    assert not any("Other" in line for line in lines)
    # The surfaces the OWNER reads want the whole list, and ask for it.
    everything = families.words(table, only_unavailable=False)
    assert any(line == "- Other: READY." for line in everything)
    # And the owner's list DOES carry the instruction on each line: it is read on a card by
    # somebody who asked, not paid for on every turn.
    assert any("Test family" in line and "Do not attempt it" in line for line in everything), everything


def test_the_scope_to_grant_is_named_even_when_the_reason_does_not_say_it(family):
    """The scope is the one thing the owner cannot work out from the tablet; it has to be in
    the words whether or not Shopify's own message mentions it."""
    lines = families.words({family.key: {"label": "Test family", "state": "MISSING_SCOPE",
                                         "detail": "the shop has not granted it", "scope": "write_test"}})
    assert any("write_test" in line for line in lines)
    # And never twice when it does.
    once = families.words({family.key: {"label": "Test family", "state": "MISSING_SCOPE",
                                        "detail": "missing the write_test scope", "scope": "write_test"}})
    assert once and once[0].count("write_test") == 1


def test_the_manifest_carries_the_families(family):
    from app.capabilities import manifest

    built = manifest.build(build_id="t", writes_enabled=True)
    rows = {f["key"]: f for f in built["families"]}
    assert family.key in rows and rows[family.key]["state"] == "READY" and rows[family.key]["scopes"] == ["write_test"]
    # A family changing state is a build change the delta can see.
    a = manifest.fingerprint(built)
    built["families"] = [dict(f, state="NOT_IMPLEMENTED") if f["key"] == family.key else f for f in built["families"]]
    assert manifest.fingerprint(built) != a


def test_every_family_module_loads():
    from app.families import load_all

    loaded = load_all()
    assert isinstance(loaded, list)


# ------------------------------------------------- the capabilities that already existed


def _core_table():
    """Every family, with every tool module imported — the registry only holds what has been
    imported, and app/runtime.py imports the tools before the families."""
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.capabilities import families
    from app.families import load_all

    load_all()
    return {f.key: f for f in families.all_families()}


def _shipped(spec) -> bool:
    """A tool the assistant ships, as opposed to a double another test module registered into
    the process-global registry. Told apart by where the handler is defined: a double lives in
    tests/. Without this the assertions below fail depending on which other test module ran
    first, which is a flaky test rather than a true one."""
    return str(getattr(spec.handler, "__module__", "")).startswith("app.")


def test_every_existing_write_operation_belongs_to_a_named_family():
    """The family table was built for Phase 3's additions and started empty, so /health
    listed nothing and the settings sheet could say nothing about the fourteen write
    operations that already worked. A manifest that lists only the new things is not one."""
    from app.tools import registry

    families = _core_table()
    claimed = {op for f in families.values() for op in f.operations}
    registered = {s.write.operation for s in registry.all_specs() if s.write is not None and _shipped(s)}
    assert registered, "no write tools are registered at all — the check would pass vacuously"
    assert registered <= claimed, f"no family names these operations: {sorted(registered - claimed)}"


def test_every_read_tool_the_model_is_offered_belongs_to_a_named_family():
    from app.tools import registry

    families = _core_table()
    claimed = {tool for f in families.values() for tool in f.tools}
    reads = {
        s.name for s in registry.all_specs()
        if s.write is None and s.batch is None and not s.name.startswith("mock_") and _shipped(s)
    }
    assert reads, "no read tools are registered at all — the check would pass vacuously"
    assert reads <= claimed, f"no family names these read tools: {sorted(reads - claimed)}"


async def test_a_write_family_reads_read_only_when_changes_are_off():
    """Derived, not declared: the family says READY, and the per-operation table — which knows
    the store, the scopes and whether writes are switched on — is what turns it into
    READ_ONLY or MISSING_SCOPE. This is what the settings sheet shows the owner."""
    from app.capabilities import families

    class Runtime:
        pass

    off = {op: {"state": "disabled", "detail": "changes are switched off on this Mac"}
           for op in ("order_cancel", "refund_create", "gmail_send_reply")}
    table = await families.states(Runtime(), operations=off)
    assert table["order_cancel"]["state"] == "READ_ONLY"
    assert "switched off" in table["order_cancel"]["detail"]
    assert table["email_sends"]["state"] == "READ_ONLY"
    assert table["order_cancel"]["offerable"] is False
    # A read family has no operations to derive from and is unaffected.
    assert table["order_reads"]["state"] == "READY" and table["order_reads"]["offerable"] is True


async def test_a_missing_scope_names_the_scope_to_grant():
    from app.capabilities import families

    class Runtime:
        pass

    blocked = {"inventory_set": {"state": "blocked", "detail": "the app is missing the write_inventory scope",
                                 "scope": "write_inventory"}}
    table = await families.states(Runtime(), operations=blocked)
    assert table["inventory_set"]["state"] == "MISSING_SCOPE"
    assert table["inventory_set"]["scope"] == "write_inventory"


def test_the_families_that_already_worked_never_withhold_a_tool_from_the_model():
    """`withheld_by_family` exists to stop the model attempting what the store cannot do. It
    must not take away anything that worked before this table existed: a family with no tools
    of its own withholds nothing, and a READY one withholds nothing either."""
    from app.capabilities.families import OFFERABLE

    families = _core_table()
    for key, family in families.items():
        if family.state in OFFERABLE:
            continue
        assert not family.tools, f"{key} is not READY and names tools that would be withheld: {family.tools}"


async def test_no_family_shows_the_owner_a_url_where_a_scope_should_be():
    """The scope in a family's row is read by the owner in the settings sheet and by the model
    in one line of prompt. A Gmail scope is a URL to the API and a sentence to nobody; one
    family registered the full one, and the settings sheet would have printed it beside
    "gmail.compose" from the family next to it. Shortened once, where the row is built, so the
    next family to register a URL is also fine."""
    from app.capabilities import families as families_mod
    from app.families import load_all

    load_all()
    table = await families_mod.states(None)
    assert table, "the family table did not load — the check would pass vacuously"
    urls = {key: row.get("scope") for key, row in table.items() if "://" in str(row.get("scope") or "")}
    assert not urls, f"these rows show a URL as the scope: {urls}"
    # And the shortening keeps the grant identifiable rather than blanking it.
    assert families_mod._said("https://www.googleapis.com/auth/gmail.compose") == "gmail.compose"
    assert families_mod._said("write_order_edits") == "write_order_edits"


async def test_the_standing_capability_line_is_paid_for_once_per_turn_and_stays_small():
    """This block goes on EVERY model-path prompt, so its length is a per-turn cost.

    It grew to 1,293 characters as Phase 3 registered families: 287 of that was the sentence
    "Do not attempt it; say so if asked." repeated on all seven lines, and 248 was four
    NOT_IMPLEMENTED families each restating the same reason word for word. Neither bought
    anything — `_family_lines` says the instruction once at the head, and families that are
    unavailable for the same reason now share a line, state and reason first because the state
    is what the model reads to answer "can you do X".

    The bound is deliberately loose enough to absorb another family or two and tight enough
    that a regression to a line-per-family with the instruction on each would fail.
    """
    import asyncio  # noqa: F401 — the test is async; the import documents that states() is

    from app.capabilities import families as families_mod
    from app.families import load_all
    from app.routes.turn import FAMILY_LINE_PREFIX

    load_all()
    table = await families_mod.states(None)
    unavailable = [k for k, r in table.items() if r["state"] != "READY"]
    assert len(unavailable) >= 5, f"only {len(unavailable)} unavailable — the check would be weak"

    block = FAMILY_LINE_PREFIX + "\n".join(families_mod.words(table)) + "]"
    # 920 is Instagram (app/tools/instagram_tools.py): "- DISCONNECTED — no token stored:
    # Instagram", +44 characters measured (872 before, 916 after), said only on a server with no
    # Instagram token stored. Once one is, the family is READY and this line costs nothing.
    # 1,003 is CROOKS Returns (app/tools/returns_tools.py): "- DISCONNECTED — no CROOKS Returns
    # keys stored: Acting on returns, Reading returns", +83 characters measured (854 before, 937
    # after, with the two families sharing one line), said only on a server with no returns keys.
    # 1,074 is WeChat through WeCom (app/tools/messaging_tools.py): "- DISCONNECTED — no WeCom keys
    # stored: WeChat messages, WeChat replies", +71 characters measured (998 before, 1,069 after, the
    # two families sharing one line), said only on a server with no WeCom keys stored.
    assert len(block) <= 1_074, f"{len(block)} chars on every model turn:\n{block}"

    # The instruction appears once, at the head, and never on a line.
    assert block.count("Do not attempt") == 1, block
    # Every unavailable family is still named — shorter must not mean quieter.
    for key in unavailable:
        assert table[key]["label"] in block, f"{key} vanished from the block"
    # And every state is still said, because that is what the model answers with.
    for key in unavailable:
        assert table[key]["state"] in block, f"{key}'s state vanished"


async def test_the_owner_gets_the_whole_list_in_full_where_it_costs_nothing():
    """The short form is for the prompt. The settings sheet is read on a card, once, by a
    person who asked — so it keeps every family, its own line, and the reason unclipped."""
    from app.capabilities import families as families_mod
    from app.families import load_all

    load_all()
    table = await families_mod.states(None)
    full = families_mod.words(table, only_unavailable=False)

    assert len(full) == len(table), "the owner's list drops a family"
    assert sum(1 for line in full if "READY." in line) >= 15, full[:3]
    # A reason the model saw clipped is whole here.
    joined = "\n".join(full)
    assert "…" not in joined, "the owner's list should not be clipped"
