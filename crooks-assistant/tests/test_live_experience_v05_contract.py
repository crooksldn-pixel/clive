from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
APP = WEB / "app.js"
INDEX = WEB / "index.html"


def test_v05_removes_user_facing_split_entry_points_but_keeps_internal_branch_support() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "split.textContent = 'Split';" not in source
    assert "splitOrb('gesture')" not in source

    # Internal/legacy branch mechanics still exist so concurrency has not been deleted;
    # V0.5 changes who manages it, not whether the runtime can represent it.
    assert "async function splitOrb(" in source
    assert "if (branches.length < 2) {" in source
    assert "if (branches.length > 1)" in source


def test_v05_ready_copy_no_longer_frames_clive_as_an_empty_command_prompt() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "READY: ['CLIVE ready', 'Ask, interrupt, or continue']" in source
    assert "READY: ['System ready.', 'What do you need?']" not in source


def test_v05_initial_html_matches_clive_ready_framing_before_javascript_runs() -> None:
    source = INDEX.read_text(encoding="utf-8")

    assert ">CLIVE ready</p>" in source
    assert ">Ask, interrupt, or continue</p>" in source
    assert 'aria-label="Back to CLIVE"' in source
    assert "<span>CLIVE</span>" in source
    assert ">System ready.</p>" not in source
    assert ">What do you need?</p>" not in source


LIVE_STATE = WEB / "live-state.js"
SW = WEB / "sw.js"


def test_v05_ships_one_client_side_state_authority() -> None:
    """Invariant 2/B: one state machine, and it is a real file the page loads — not a
    convention spread across the call sites that write `stage.dataset.state`."""
    assert LIVE_STATE.is_file()
    source = LIVE_STATE.read_text(encoding="utf-8")

    for state in ("IDLE", "LISTENING", "HEARING", "UNDERSTOOD", "THINKING", "WORKING", "RESPONDING"):
        assert f"'{state}'" in source, f"the canonical state {state} is missing"
    # "Error, interruption and recovery states must be explicit."
    for state in ("INTERRUPTED", "FAULT", "RECOVERING"):
        assert f"'{state}'" in source, f"{state} must be a state, not an implication"

    # "Do not infer state from arbitrary DOM text." The authority cannot: past the two lines
    # that publish it on the global, there is no browser in the file at all.
    body = source[source.index("})(typeof window"):]
    body = body[body.index("'use strict';"):]
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    body = "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())
    for forbidden in ("document", "querySelector", "dataset", "textContent", "window", "navigator"):
        assert forbidden not in body, f"the state authority reaches for {forbidden}"

    # The page loads it, and the worker keeps it in the shell so it survives going offline.
    assert '<script src="/static/live-state.js"></script>' in INDEX.read_text(encoding="utf-8")
    assert "'/static/live-state.js'," in SW.read_text(encoding="utf-8")


def test_v05_state_transitions_are_events_and_not_assignments() -> None:
    """B: the page reports what HAPPENED; the machine decides what that means."""
    source = APP.read_text(encoding="utf-8")

    # Pointer-down enters LISTENING synchronously, and it is the machine that is told first.
    assert "if (live) live.pointerDown();\n  setState('LISTENING');" in source
    # The release is marked where it happens, so every later measurement has a true origin.
    assert "if (live && !discard) live.released();" in source
    # The transcript settling on screen is what UNDERSTOOD means here — and the machine is
    # handed a LENGTH, never the words (invariant 11).
    assert "live.final(String(data.heard).length);" in source
    assert "live.final(data.heard)" not in source
    # A question that was never spoken is still a turn.
    assert "if (live && !isAudio) live.asked(0);" in source
    # Everything else still speaks presentation words, and there is exactly one translator.
    assert "if (live) live.fromPresentation(state);" in source


def test_v05_measures_the_four_latencies_the_evidence_gate_names() -> None:
    """Evidence gate: pointer-down → acknowledgement, release → final transcript, release →
    first progress indication, release → first useful result."""
    machine = LIVE_STATE.read_text(encoding="utf-8")
    for mark in ("acknowledgedMs", "transcriptMs", "progressMs", "usefulMs"):
        assert mark in machine, f"{mark} is not measured"

    source = APP.read_text(encoding="utf-8")
    # A useful result is a thing the owner can read, reported from where one actually lands.
    assert "noteUseful('workspace patch');" in source
    assert "noteUseful('answer');" in source
    # And the turn's evidence is emitted as numbers and counts only.
    assert "T.record('live_marks', {" in source
    for field in ("ack_ms", "transcript_ms", "progress_ms", "useful_ms"):
        assert field in source, f"live_marks does not carry {field}"
    # Every value in it comes from the machine, which was never given a word of the
    # conversation: lengths and counts, never text. `heard_chars` is how MUCH was said.
    marks = source[source.index("T.record('live_marks', {"):]
    marks = marks[:marks.index("});")]
    values = re.findall(r":\s*([A-Za-z][\w.]*)", marks)
    for value in values:
        assert value.startswith("marks.") or value == "live.state" or value == "undefined", \
            f"live_marks reads {value!r}, which is not one of the machine's own measurements"
    assert "heard_chars: marks.heardChars" in marks
    for leak in ("el.heard", "data.answer", "data.question", "textContent"):
        assert leak not in marks, f"the evaluation record carries {leak!r}"


JOBS = WEB / "jobs.js"
STYLE = WEB / "style.css"


def test_v05_ships_a_progressive_job_surface() -> None:
    """Slice C: a compact work surface, present only while there is meaningful work."""
    assert JOBS.is_file()
    source = JOBS.read_text(encoding="utf-8")
    for state in ("QUEUED", "WORKING", "DONE", "FAILED"):
        assert f"'{state}'" in source

    index = INDEX.read_text(encoding="utf-8")
    assert '<script src="/static/jobs.js"></script>' in index
    assert "'/static/jobs.js'," in SW.read_text(encoding="utf-8")
    # It starts hidden: an empty strip is not a surface, and the idle screen is unchanged.
    assert '<section id="job-zone" class="job-zone" aria-label="Work in progress" role="status" aria-live="polite" hidden>' in index


def test_v05_job_surface_is_a_band_of_the_app_and_not_under_the_voice_target() -> None:
    """D-1's rule, applied to the new surface: it carries a button, and in orb mode `#talk`
    is inset:0 over the whole stage. A control inside the stage could never be pressed."""
    index = INDEX.read_text(encoding="utf-8")
    main = index[index.index('<main id="stage"'):index.index("</main>")]
    assert 'id="job-zone"' not in main
    zone = index[index.index('<section id="orb-zone"'):]
    assert 'id="job-zone"' not in zone[:zone.index("</section>")]
    # And it is a ROW of the app grid, so nothing above it can cover it.
    style = STYLE.read_text(encoding="utf-8")
    assert '"stage" "message" "work" "halves" "foot"' in style
    assert ".job-zone{grid-area:work}" in style


def test_v05_job_surface_keeps_the_liquid_glass_rules() -> None:
    """Slice D's rules for translucency, applied where the new surface uses them: one pane
    that communicates grouping, restrained blur, a thin highlight, and no motion at rest."""
    style = STYLE.read_text(encoding="utf-8")
    strip = style[style.index("/* ------------------------------------------------------------ work in flight */"):]
    strip = strip[:strip.index(".branch-zone{\n  position:relative")]

    panes = [line for line in strip.splitlines() if "backdrop-filter:blur" in line]
    assert len(panes) == 1, "the strip is one translucent surface, not a pane per row"
    # The same restrained value the rest of the chrome uses, not a frosted slab of its own.
    assert "blur(var(--blur-surface))" in strip
    assert "inset 0 1px 0 rgba(255,255,255,.07)" in strip, "the thin highlight along the top edge"
    # Depth from opacity, border and shadow — never from something that keeps moving.
    assert "animation" not in strip and "@keyframes" not in strip
    for transition in re.findall(r"transition:([^;}]+)", strip):
        assert "transform" not in transition or "var(--t-1)" in transition
    # The 2019 tablet in lite mode pays for no blur it did not ask for.
    assert "html[data-lite] .job-list{-webkit-backdrop-filter:none;backdrop-filter:none}" in style


def _detail_words() -> dict[str, tuple[str, str, bool]]:
    """The tablet's table of what the Mac is doing, read out of web/app.js."""
    source = APP.read_text(encoding="utf-8")
    table = source[source.index("const DETAIL_WORDS = {"):]
    table = table[:table.index("\n};")]
    out: dict[str, tuple[str, str, bool]] = {}
    for name, verb, obj, writes in re.findall(
        r"(\w+): \[('[^']+'|\"[^\"]+\"), ('[^']+'|\"[^\"]+\")(, true)?\]", table
    ):
        out[name] = (verb.strip("'\""), obj.strip("'\""), bool(writes))
    return out


def test_v05_job_labels_never_carry_a_tool_name() -> None:
    """Invariant 7: architecture must not leak into interaction language."""
    words = _detail_words()
    assert len(words) >= 40
    for name, (verb, obj, _writes) in words.items():
        for part in (verb, obj):
            assert "_" not in part, f"{name} leaks its tool name onto the glass"
            assert not part.lower().startswith(("shopify", "gmail", "commerce", "batch")), \
                f"{name} names the vendor on the glass: {part!r}"
        assert verb[:1].isupper() and verb[:1].isalpha(), f"{name} has no verb"
        assert obj.strip(), f"{name} has no object"


def _shipped_tools() -> dict[str, bool]:
    """Every tool the Mac ships, and whether it writes — name -> ToolSpec.write.

    Filtered by where the handler comes from, never by what it is called. Two things are not
    shipped work: another test module's own doubles, which land in this process-wide registry
    and under `-n 4` share a worker with this file; and `app/tools/mock.py`, three tools that
    exist only to prove the gate refuses a RED one. The capabilities manifest already draws
    the same line — "the diagnostics are not a capability" — and the words on the glass follow
    it rather than inventing a second one.

    A name-prefix rule would have quietly grown into one that could swallow a real tool, so
    the diagnostics module is excluded by module and asserted to still be there.
    """
    from experience import tool_matrix

    tool_matrix.load()
    # Imported here, not left to whichever test module ran before this one in the worker: run
    # alone, or after a different neighbour, this file found the diagnostics missing and failed
    # (seen on trunk run alone, and in round 12's first full run).
    import app.tools.mock  # noqa: F401
    from app.tools import registry

    DIAGNOSTICS = "app.tools.mock"
    shipped, diagnostics = {}, 0
    for name, spec in registry._REGISTRY.items():
        module = getattr(spec.handler, "__module__", "")
        if module == DIAGNOSTICS:
            diagnostics += 1
        elif module.startswith("app."):
            shipped[name] = bool(spec.write)
    assert diagnostics, f"{DIAGNOSTICS} registered nothing — this exclusion has stopped matching"
    return shipped


def test_v05_every_tool_the_mac_can_run_has_words_and_no_others() -> None:
    """The job strip is only as honest as this table. A tool with no row shows as no work at
    all, which on a turn of four reads means most of it invisible — and a row for a tool the
    Mac no longer has is a promise about something that cannot happen.

    Both were true when this was first run: two rows named tools that had been gone for some
    time, and thirty-nine tools had nothing to say."""
    shipped = set(_shipped_tools())
    described = set(_detail_words())
    assert not (shipped - described), \
        "the Mac can run these and the tablet has no words for them: " + ", ".join(sorted(shipped - described))
    assert not (described - shipped), \
        "the tablet has words for tools the Mac does not have: " + ", ".join(sorted(described - shipped))


def test_v05_the_write_flag_is_the_macs_answer_and_not_the_tablets_guess() -> None:
    """Invariant 9. Nothing reads the flag yet; the moment a retry is offered it is what stops
    the tablet offering to re-run a refund, so it has to agree with the Mac before then — and
    it must agree by being COPIED from it, not by being reasoned about on this side.

    Written as an exact comparison because a guess was wrong on the first attempt: the five
    batch tools read as changes ("Sending the replies") but only STAGE one, and the change
    itself goes through the confirmation path afterwards. The Mac has always said so."""
    shipped = _shipped_tools()
    words = _detail_words()
    disagree = {
        name: (words[name][2], writes)
        for name, writes in shipped.items()
        if name in words and words[name][2] != writes
    }
    assert not disagree, "tablet says / Mac says: " + ", ".join(
        f"{name} {tablet} / {mac}" for name, (tablet, mac) in sorted(disagree.items())
    )
    assert sum(shipped.values()) >= 15, "a registry with no writes in it would pass vacuously"


def test_v05_jobs_are_derived_from_what_the_mac_says_is_running() -> None:
    """/state names one running tool at a time, so a tool that was running and is not any more
    has finished. That is the whole derivation, and it is what makes two reads show as two
    jobs completing in the order they really completed."""
    source = APP.read_text(encoding="utf-8")
    assert "noteRunningTool(data.detail);" in source
    assert "if (runningJob) jobs.done(runningJob);" in source
    assert "endJobs();" in source
    # And the work's own nature travels with it, so a failure reported later cannot make a
    # refund look re-runnable.
    assert "writes: words[2] === true" in source


def test_v05_offers_no_retry_it_cannot_honour() -> None:
    """Invariant 9: the safe semantics are preserved, which here means not drawing a control
    the Mac has no endpoint for. jobs.js can draw one; the page does not ask it to yet."""
    source = APP.read_text(encoding="utf-8")
    assert "window.CrooksJobs.render(el.jobZone, list);" in source
    assert "onRetry" not in source
    assert "onRetry" in JOBS.read_text(encoding="utf-8"), "the affordance exists for when it can be honoured"


def test_v05_moves_persistent_service_status_out_of_the_idle_surface() -> None:
    """Slice D / invariant 8: connection and service health is contextual. The four service
    pills leave the idle footer for Diagnostics; a fault still reaches the primary flow."""
    index = INDEX.read_text(encoding="utf-8")

    footer = index[index.index("<footer class=\"bottom\">"):index.index("</footer>")]
    assert 'id="services"' not in footer
    for name in ("svc-shopify", "svc-gmail", "svc-voice", "svc-changes"):
        assert name not in footer, f"{name} is still on the idle surface"
        assert name in index, f"{name} was deleted rather than moved"

    # In the settings sheet, under Diagnostics — which sits in the Developer view, after the
    # owner's own sections (GENERATIVE_UI_V1 §4).
    sheet = index[index.index('<dialog id="settings"'):]
    diagnostics = sheet[sheet.index("<h3>Diagnostics</h3>"):sheet.index("<h3>Every capability</h3>")]
    assert '<div class="services" id="services" aria-label="Service status">' in diagnostics
    assert "svc-shopify" in diagnostics and "svc-changes" in diagnostics

    # A fault in the current objective still has somewhere to appear in the main flow.
    assert 'id="conn"' in index[:index.index("<main")]
    assert 'id="notes-global"' in index


ACCEPTANCE = Path(__file__).resolve().parent / "web" / "acceptance-v05.test.js"


def test_v05_acceptance_harness_says_it_is_a_fixture_and_does_not_claim_otherwise() -> None:
    """§E: 'use an honest fixture/fake adapter … and label it as such. Do not pretend fixture
    data is live.' A harness that reads as a measurement is exactly the failure that rule is
    written against."""
    assert ACCEPTANCE.is_file()
    source = ACCEPTANCE.read_text(encoding="utf-8")

    assert "FIXTURE RUN" in source
    assert "proves nothing about how fast the Mac is" in source
    assert "FIXTURE: true" in source, "the harness answers for itself, not only in a comment"
    # And no test in it claims to be anything it is not. (The header quotes the contract's
    # own "live Gmail/model access" clause, so the check is on what the TESTS say they did.)
    for name in re.findall(r"^test\('([^']*)'", source, flags=re.M):
        # Whole words: CLIVE is the assistant's name, not a claim about this run.
        for claim in ("live", "real", "device", "measured"):
            assert not re.search(rf"\b{claim}\b", name, re.I), \
                f"the harness test {name!r} claims to be {claim!r}"

    # And it covers the five things the evidence gate names by name.
    for scenario in (
        "interrupts the answer and keeps the work in flight",
        "the first useful result does not wait for the slowest job",
        "one job failing leaves the others",
        "adds a job, not a Split",
        "no interval passes with nothing on screen to explain it",
    ):
        assert scenario in source, f"the harness does not cover: {scenario}"
