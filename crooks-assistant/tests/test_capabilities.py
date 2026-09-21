"""The capability manifest, and the delta between two builds.

"I updated your capabilities earlier. What more can you do now?" took seventy-five seconds
and zero tool calls in the September session, and answered wrongly. It is a comparison of two
generated manifests; these are the tests that keep it one.
"""

from __future__ import annotations

import json
import os

import pytest

import app.tools.analytics_tools  # noqa: F401
import app.tools.batch_tools  # noqa: F401
import app.tools.gmail_tools  # noqa: F401
import app.tools.gmail_writes  # noqa: F401
import app.tools.mock  # noqa: F401
import app.tools.shopify_tools  # noqa: F401
import app.tools.shopify_writes  # noqa: F401
from app.capabilities.delta import FILE_NAME, delta, record_build, spoken_delta
from app.capabilities.manifest import build, fingerprint, spoken_summary


@pytest.fixture()
def manifest():
    return build(build_id="b1")


def test_the_manifest_is_generated_from_the_registry_not_written_down(manifest):
    from app.tools import registry

    names = {e["name"] for e in manifest["reads"] + manifest["writes"] + manifest["batches"]}
    registered = {s.name for s in registry.all_specs() if not s.name.startswith("mock_")}
    from app.tools.gate import Tier

    red_reads = {s.name for s in registry.all_specs() if s.write is None and s.batch is None and s.tier is Tier.RED}
    assert names == registered - red_reads, "every tool, and only the tools"
    assert "mock_echo" not in names, "the diagnostics are not a capability"


def test_the_manifest_carries_the_semantic_tags_the_tablet_and_the_model_need(manifest):
    assert set(manifest) >= {"reads", "writes", "batches", "query_dimensions", "entity_types",
                             "ui_components", "data_sources", "risk_types", "gestures", "fingerprint"}
    dims = manifest["query_dimensions"]
    assert "size" in dims["group_by"] and "colour" in dims["group_by"] and "units" in dims["metrics"]
    assert "this_week" in dims["periods"] and "{days: N}" in dims["periods"]
    assert {"order", "customer", "email_thread", "working_set"} <= set(manifest["entity_types"])
    assert all(w["risk"] in manifest["risk_types"] for w in manifest["writes"])
    assert all(w["gesture"] in manifest["gestures"] for w in manifest["writes"])


def test_writes_off_means_the_manifest_says_so():
    off = build(build_id="b1", writes_enabled=False)
    assert off["writes"] == [] and off["batches"] == []
    assert "read only" in spoken_summary(off)


def test_the_fingerprint_moves_for_a_capability_and_not_for_a_rewording(manifest):
    reworded = json.loads(json.dumps(manifest))
    reworded["reads"][0]["what"] = "an entirely different sentence about the same tool"
    assert fingerprint(reworded) == manifest["fingerprint"], "prose is not a capability"
    fewer = json.loads(json.dumps(manifest))
    fewer["reads"] = fewer["reads"][1:]
    assert fingerprint(fewer) != manifest["fingerprint"]


def test_the_spoken_summary_names_what_it_does_not_what_it_is_made_of(manifest):
    words = spoken_summary(manifest)
    assert words.startswith("I can ") and words.endswith(".")
    assert "commerce_aggregate" not in words and "shopify_" not in words
    assert "sales" in words and "inbox" in words


def test_the_first_build_says_it_has_nothing_to_compare_against(tmp_path, manifest):
    record = record_build(manifest, tmp_path)
    assert delta(record)["first_build"] is True
    assert "first build" in spoken_delta(record)
    assert (tmp_path / FILE_NAME).exists()


def test_the_same_capabilities_on_a_new_build_id_are_not_a_change(tmp_path, manifest):
    record_build(manifest, tmp_path)
    again = record_build({**manifest, "build": "b2"}, tmp_path)
    assert delta(again)["first_build"] is True, "the previous build is still the one before this one"
    assert spoken_delta(again).startswith("This is the first build")


def test_a_gained_tool_is_a_real_delta_answered_from_two_manifests(tmp_path, manifest):
    smaller = json.loads(json.dumps(manifest))
    smaller["reads"] = [e for e in smaller["reads"] if e["name"] != "inventory_query"]
    smaller["batches"] = []
    smaller["fingerprint"] = fingerprint(smaller)
    record_build(smaller, tmp_path)
    record = record_build({**manifest, "build": "b2"}, tmp_path)
    moved = delta(record)
    assert moved["first_build"] is False
    assert moved["previous_build"] == "b1" and moved["current_build"] == "b2"
    added = {a["name"] for a in moved["added"]}
    assert "inventory_query" in added
    assert any(a["section"] == "batches" for a in moved["added"])
    spoken = spoken_delta(record)
    assert spoken.startswith("Since the last build") and "bulk" in spoken


def test_a_lost_tool_is_reported_as_gone(tmp_path, manifest):
    record_build(manifest, tmp_path)
    fewer = json.loads(json.dumps(manifest))
    fewer["reads"] = [e for e in fewer["reads"] if e["name"] != "gmail_search"]
    fewer["build"] = "b2"
    fewer["fingerprint"] = fingerprint(fewer)
    record = record_build(fewer, tmp_path)
    assert {r["name"] for r in delta(record)["removed"]} == {"gmail_search"}
    assert "gone:" in spoken_delta(record)


def test_a_new_query_dimension_is_a_delta_of_its_own(tmp_path, manifest):
    before = json.loads(json.dumps(manifest))
    before["query_dimensions"]["group_by"] = [g for g in before["query_dimensions"]["group_by"] if g != "colour"]
    before["fingerprint"] = fingerprint(before)
    record_build(before, tmp_path)
    record = record_build({**manifest, "build": "b2"}, tmp_path)
    added = delta(record)["added"]
    assert any(a["section"] == "query_dimensions" and "colour" in a["what"] for a in added)


def test_nothing_changed_is_said_plainly(tmp_path, manifest):
    changed = json.loads(json.dumps(manifest))
    changed["reads"] = changed["reads"][1:]
    changed["fingerprint"] = fingerprint(changed)
    record_build(changed, tmp_path)
    record = record_build({**manifest, "build": "b2"}, tmp_path)
    # Now record the same capabilities once more: previous stays put, so the delta stands.
    record = record_build({**manifest, "build": "b3"}, tmp_path)
    assert delta(record)["current_build"] == "b3"
    same = json.loads(json.dumps(record["current"]))
    record["previous"] = same
    assert spoken_delta(record) == "Nothing has changed since the last build — same tools, same questions, same cards."


def test_the_spoken_delta_is_one_breath_however_much_moved():
    """"What can you do now?" is READ ALOUD, and this pass is exactly the build that makes it
    long: the capability manifest went from nothing to eighteen families, so the delta had
    fifteen new things to recite. It came out at 435 characters — half a minute of the
    assistant listing tools at somebody who asked a one-line question — and the golden
    scenario's own oracle (under 400) caught it in `make experience` while the offline suite
    stayed green, because pytest builds a fresh harness with no previous build to compare to.

    The card carries the list. The sentence carries the shape of it: at most a few per section
    and the rest counted, and if that still runs long, only the counts.
    """
    from app.capabilities.delta import SPOKEN_CHARS, spoken_delta

    def manifest(reads, writes, batches, dims, cards):
        return {
            "build": "b", "fingerprint": "f",
            "reads": [{"name": f"read_{i}", "what": f"look up the thing numbered {i} in some detail"} for i in range(reads)],
            "writes": [{"name": f"write_{i}", "what": f"change the thing numbered {i} for you"} for i in range(writes)],
            "batches": [{"name": f"batch_{i}", "what": f"do the numbered thing {i} to a whole set"} for i in range(batches)],
            "query_dimensions": {"metrics": [f"metric_{i}" for i in range(dims)]},
            "ui_components": [f"card_{i}" for i in range(cards)],
        }

    # Nothing moved, and a modest move: both said in full.
    same = manifest(4, 2, 1, 2, 2)
    quiet = spoken_delta({"previous": same, "current": same})
    assert "Nothing has changed" in quiet, quiet

    modest = spoken_delta({"previous": same, "current": manifest(6, 3, 1, 3, 3)})
    assert len(modest) <= SPOKEN_CHARS, f"{len(modest)} chars: {modest}"
    assert "read_4" in modest or "look up the thing numbered 4" in modest, modest

    # And the build this pass actually is: a great deal moved at once.
    lots = spoken_delta({"previous": manifest(0, 0, 0, 0, 0),
                         "current": manifest(20, 9, 5, 12, 8)})
    assert len(lots) <= SPOKEN_CHARS, f"{len(lots)} chars, over the bound: {lots}"
    assert "Since the last build" in lots, lots
    # It says how much rather than pretending nothing was left out.
    assert "more" in lots or "on the card" in lots, lots


def test_the_spoken_delta_names_what_went_as_well_as_what_arrived():
    """A build that REMOVED something must say so — a delta that only ever adds would let a
    capability disappear quietly, which is the failure the manifest exists to prevent."""
    from app.capabilities.delta import SPOKEN_CHARS, spoken_delta

    before = {"build": "a", "reads": [{"name": "gone_read", "what": "the thing that went away"}],
              "writes": [], "batches": [], "query_dimensions": {}, "ui_components": []}
    after = {"build": "b", "reads": [], "writes": [], "batches": [],
             "query_dimensions": {}, "ui_components": []}
    said = spoken_delta({"previous": before, "current": after})
    assert "gone" in said.lower(), said
    assert len(said) <= SPOKEN_CHARS, said


def test_two_starts_against_one_log_directory_do_not_take_each_other_out(tmp_path):
    """The capability record is written atomically, and until this test the ATOMIC part was
    doing all the work while the source of the rename was a single shared `capabilities.tmp`.

    Two starts against the same log directory — `make up` overlapping the launchd agent
    through a restart, or two pytest workers — and whichever renamed first took the other's
    scratch file away, so the second os.replace raised FileNotFoundError out of record_build,
    out of runtime.build, out of the lifespan, and the backend did not come up.
    """
    import json
    import threading

    from app.capabilities.delta import record_build

    log_dir = tmp_path / "logs"
    starts = 12
    ready = threading.Barrier(starts)
    failures: list[BaseException] = []

    def start(n: int) -> None:
        try:
            ready.wait(timeout=10)
            record_build({"build": f"b{n}", "fingerprint": f"f{n}", "reads": [], "writes": [],
                          "batches": [], "query_dimensions": {}, "ui_components": []}, log_dir)
        except BaseException as error:  # noqa: BLE001 — the whole point is that none escapes
            failures.append(error)

    threads = [threading.Thread(target=start, args=(n,)) for n in range(starts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not failures, f"a start failed: {failures[0]!r}"
    # One file, whole and readable — a half-written record would be worse than a crash.
    written = sorted(p.name for p in log_dir.iterdir())
    assert written == ["capabilities.json"], f"scratch left behind: {written}"
    record = json.loads((log_dir / "capabilities.json").read_text(encoding="utf-8"))
    assert record["current"]["fingerprint"].startswith("f")


def test_each_write_names_its_own_scratch_file(monkeypatch, tmp_path):
    """The deterministic half of the test above: it is the UNIQUENESS of the scratch name
    that fixes the race, so that is asserted directly rather than only stressed for."""
    # `app.capabilities` re-exports the delta FUNCTION under that name, so `app.capabilities.delta`
    # as an attribute IS that function and `import … as` resolves to it. The module itself has
    # to be asked for by name.
    import importlib

    delta_module = importlib.import_module("app.capabilities.delta")

    sources: list[str] = []
    real_replace = delta_module.os.replace

    def watched(src, dst):
        sources.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(delta_module.os, "replace", watched)
    path = tmp_path / "capabilities.json"
    delta_module._write(path, {"current": {"build": "a"}})
    delta_module._write(path, {"current": {"build": "b"}})

    assert len(set(sources)) == 2, f"two writes shared one scratch file: {sources}"
    assert all(name.endswith(".tmp") for name in sources)
    assert all(str(os.getpid()) in name for name in sources), "the scratch name is not this process's"
