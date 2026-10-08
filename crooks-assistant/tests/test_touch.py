"""§7 and §8, from the suite's side: who owns a touch, and which layer may cover which.

Three kinds of check live here, and they are deliberately different kinds.

1. THE MACHINE, under Node. `web/touch.js` is pure — an owner per pointer id and arithmetic
   over rectangles — so every rule §7 states is asserted in `tests/web/touch.test.js` without a
   browser, including the 23:08:31 burst replayed tap for tap.

2. THE PAGE, read as text. The rules that are structural rather than behavioural: that the
   branch chrome is not inside the orb's stacking context, that the layer ladder is written
   down, that the voice target is bounded. A string test cannot prove a tap lands; it CAN prove
   that the one line that caused D-1 is gone and has not come back, which is what a regression
   test is for.

3. THE GLASS, in Chromium. `scripts/browser/touch.js` drives real CDP touch events at measured
   pixels, at 601 x 889 and 800 x 1280, and counts what the tablet would have done with them.
   That is the only kind of check that could ever have seen D-1: every other browser gate
   presses controls with `element.click()`, which dispatches straight at the node and cannot be
   swallowed by a transparent button painted over it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
TOUCH_JS = (WEB / "touch.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
STYLE = (WEB / "style.css").read_text(encoding="utf-8")
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


# --------------------------------------------------------------------------- the machine


@needs_node
def test_the_touch_ownership_rules_under_node():
    """§7's state machine, run rather than read (web/touch.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "touch.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


def test_the_page_routes_every_pointer_through_the_machine():
    """The page must not decide for itself whose touch this is.

    D-1's shape was that nothing decided at all: `onHoldStart` began a recording for any
    pointerdown that reached the talk overlay, and the overlay was the size of the stage. So the
    classification happens in one place — in capture, before any element's own handler — and
    `onHoldStart` asks the machine rather than assuming.
    """
    assert "window.CrooksTouch.create({" in APP_JS
    assert "document.addEventListener('pointerdown', (event) => {" in APP_JS
    hold = APP_JS[APP_JS.index("function onHoldStart(event)"):]
    hold = hold[:hold.index("\n}\n")]
    assert "const claim = pointers.down(hitUnder(event));" in hold
    assert "if (claim.owner !== window.CrooksTouch.OWNER.VOICE) {" in hold
    # And the recorder is only reached after that guard.
    assert hold.index("claim.owner !== window.CrooksTouch.OWNER.VOICE") < hold.index("startRecording();")


def test_a_control_beats_the_voice_on_the_same_pointer():
    """The rule that makes D-1 unreintroducible by a stylesheet change.

    §8 puts the voice target where it covers no control. This is the belt to that braces: even
    if a future rule paints a voice region over a control again, the pointer that STARTED on the
    control cannot become a sentence, because the machine settles that before geometry matters.
    """
    classify = TOUCH_JS[TOUCH_JS.index("function classify(hit)"):]
    classify = classify[:classify.index("\n  }")]
    assert classify.index("hit.control") < classify.index("hit.voice"), (
        "voice is tested before control, so a control inside the voice zone would arm the voice"
    )
    assert classify.index("hit.scroll") < classify.index("hit.voice")
    assert classify.index("hit.approval") < classify.index("hit.control")


def test_the_page_asks_the_dom_what_the_finger_landed_on():
    """`hitUnder` reads the deepest node, not the element the listener is bound to."""
    body = APP_JS[APP_JS.index("function hitUnder(event)"):]
    body = body[:body.index("\n}\n")]
    assert "const node = event.target;" in body, "the listener's own element is not what was touched"
    assert "close('#talk, #orb-frame')" in body, "voice is claimed from somewhere other than a voice target"
    assert "window.CrooksTouch.CONTROL_SELECTOR" in body
    assert "window.CrooksTouch.APPROVAL_SELECTOR" in body
    assert "#cards" in body, "a touch that begins on the deck is not classified as a scroll"


def test_a_second_finger_cancels_before_anything_can_be_submitted():
    """The ordering, not merely the fact. A page told "a pair formed" before the pending voice
    was cancelled could still flush the recorder in between; the machine cancels first and
    reports the cancel through `onCancelVoice` on its way out of `down`."""
    down = TOUCH_JS[TOUCH_JS.index("    function down(hit)"):]
    down = down[:down.index("\n    }\n")]
    assert down.index("cancelPendingVoice('multitouch')") < down.index("owner = OWNER.SPLIT")
    assert "onCancelVoice: (why) => {" in APP_JS
    hook = APP_JS[APP_JS.index("onCancelVoice: (why) => {"):]
    hook = hook[:hook.index("\n  },")]
    assert "stopRecording(true)" in hook, "the pending recording is not discarded"


def test_the_pointer_is_captured_only_for_the_voice():
    """Capturing a control's pointer would steal its click, so it is done on one path only."""
    hold = APP_JS[APP_JS.index("function onHoldStart(event)"):]
    hold = hold[:hold.index("\n}\n")]
    assert hold.index("claim.owner !== window.CrooksTouch.OWNER.VOICE") < hold.index("setPointerCapture")


def test_a_pointer_is_never_left_claimed_when_its_control_is_redrawn():
    """A tap on a branch chip redraws the branch bar, which removes the chip from the document
    while the thumb is still on it — and a pointerup dispatched at a node that is no longer in
    the tree never reaches `document`. The pointer stayed claimed in the machine for the rest of
    the session. The browser gate found it by counting what was still down at the end of a run;
    this is the fix, and the machine's own sweep is the backstop."""
    assert "{ once: true }" in APP_JS
    assert "lostpointercapture" in APP_JS
    assert "function sweep()" in TOUCH_JS
    assert "const STALE_MS" in TOUCH_JS


# --------------------------------------------------------------------------- §8, the layers


def test_the_branch_chrome_is_not_inside_the_orbs_stacking_context():
    """D-1's verified cause, asserted as structure.

    `#branch-bar` was the last child of `<section id="orb-zone">`. `.orb-zone` was
    `position:relative; z-index:var(--z-orb)` — a stacking context, and therefore a cap on every
    z-index inside it — while `#talk` was its sibling at a higher layer and, on the idle screen,
    `inset:0`. So the transparent voice target was hit-tested over Split, Merge and Close, and
    63 taps on them in one evening became recordings.
    """
    zone = INDEX[INDEX.index('<section id="orb-zone"'):]
    zone = zone[:zone.index("</section>")]
    assert 'id="branch-bar"' not in zone, "the branch chrome is back inside the orb zone"
    assert 'id="notes-orb"' not in zone, "the workspace messages are back inside the orb zone"
    # And nothing a finger presses is left in there at all, which is what makes a voice region
    # over the orb zone safe.
    assert "<button" not in zone and 'role="button"' not in zone

    # It is a band of the app, a sibling of the stage and the footer.
    # V0.5 invariant 1: the band still exists so the runtime can represent concurrency,
    # but it is no longer a user-facing pair of halves — it is hidden and named for what
    # it is internally.
    assert '<section id="branch-zone" class="branch-zone" aria-label="Internal concurrency" hidden>' in INDEX
    main = INDEX[INDEX.index("<main id=\"stage\""):INDEX.index("</main>")]
    assert 'id="branch-zone"' not in main, "the branch band is inside the stage, which #talk fills"

    # And the orb zone no longer creates a stacking context for whatever is put in it next.
    orb_rule = STYLE[STYLE.index("\n.orb-zone{"):]
    orb_rule = orb_rule[:orb_rule.index("}")]
    assert "z-index" not in orb_rule, "the orb zone is a stacking context again"


def test_the_layer_ladder_is_written_down_and_used():
    """Six layers, named, in the order the brief sets, each used by the elements named."""
    assert "--z-content:1; --z-actions:2; --z-nav:3; --z-branch:4; --z-voice:5; --z-sheet:20;" in STYLE
    for word in ("1  content", "2  actions", "3  navigation", "4  branch", "5  voice",
                 "20 emergency", "workspace-local actions"):
        assert word in STYLE, f"the layer block does not name {word!r}"
    assert "no layer may VISUALLY COVER another INTERACTIVE layer" in STYLE
    # Each layer is actually applied, not merely declared.
    assert "z-index:var(--z-branch)" in STYLE
    assert "z-index:var(--z-voice)" in STYLE
    assert "z-index:var(--z-nav)" in STYLE
    assert "z-index:var(--z-actions)" in STYLE


def test_the_voice_target_is_not_the_whole_screen_any_more():
    """`body[data-mode="orb"] .talk{inset:0}` survives, and the reason it is now safe is that
    the stage it fills holds nothing a finger presses — see the structural test above. What must
    NOT survive is a voice region the full width of the dock band: the dock's four icons are
    navigation chrome, and the hold pill has its own `--hold-w` slot between them."""
    talk = STYLE[STYLE.index('body[data-mode="context"] .talk{'):]
    talk = talk[:talk.index("}")]
    assert "width:var(--hold-w)" in talk, "the voice zone is the full width of the dock band"
    assert "left:0;right:0" not in talk
    # One token for the hold's slot and the hole the dock leaves for it, so they cannot drift.
    assert ".dock-gap{flex:none;width:var(--hold-w)}" in STYLE


def test_the_dock_is_navigation_and_the_bands_are_placed_by_name():
    """A grid item that is `display:none` takes no row, so a bare list of row sizes matched to
    children in document order moved every band up one whenever the global notification region
    was hidden — which is its normal state. The stage could then not shrink below the orb's
    340px, and the branch band came out 310px tall on the idle screen and 0px beside the cards.
    """
    # V0.5 adds a seventh band between the workspace messages and the branch chrome: the
    # work in flight (#job-zone). A band, not a layer, for exactly the reason this test
    # exists — it carries a retry button, and `#talk` is inset:0 over the stage.
    assert 'grid-template-areas:"notes" "top" "stage" "message" "work" "halves" "foot";' in STYLE
    for place in ("#notes-global{grid-area:notes}", ".top{grid-area:top}", ".stage{grid-area:stage}",
                  "#notes-orb{grid-area:message}", ".branch-zone{grid-area:halves}", ".bottom{grid-area:foot}"):
        assert place in STYLE, f"missing placement: {place}"
    assert "grid-template-rows:auto auto minmax(0,1fr) auto auto auto" in STYLE


def test_the_dock_band_is_reserved_once_for_the_whole_column():
    """It was reserved inside `.context`, which is a row of the stage and could say nothing
    about the bands beneath it — so the halves' chips landed inside the dock's 112px, on top of
    four navigation icons, and the branch layer paints above the navigation layer."""
    assert 'body[data-mode="context"] .app{padding-bottom:calc(var(--dock) + env(safe-area-inset-bottom, 0px))}' in STYLE
    assert 'body[data-mode="context"] .context{padding-bottom:0}' in STYLE


# --------------------------------------------------------------------------- §17 / §18 / §6


def test_the_branch_band_is_held_empty_and_takes_no_space():
    """The band, the rail and the header line drew the owner's Split: a chip for each half, Merge
    and Close, and which half the screen was. Split was deleted on his ruling of 8 October
    (DEC-071, ruling 37), so nothing makes a second half and there is never anything to draw in
    them. The elements stay in the page's layout so nothing around them moves — and the band
    must still take NO space, because a band held open for nothing cost the first viewport 54px
    and took three density fixtures past the screen-and-a-quarter ceiling.

    This was `test_the_two_halves_are_only_ever_drawn_in_their_own_band`, which held where
    Split's chips were drawn. The chips are gone; what is still live of it is the empty band
    collapsing, asserted here as it was there.
    """
    body = APP_JS[APP_JS.index("function drawBranchBar()"):]
    body = body[:body.index("\n}\n")]
    assert "for (const host of [el.branchBar, el.branchRail]) {" in body
    assert "if (host) { clear(host); host.hidden = true; }" in body
    assert "if (el.branchZone) el.branchZone.hidden = true;" in body
    assert "drawBranchHead();" in body
    for gone in ("branchChip(", "branchAct(", "holdsSomething(", "'branch-halves'", "'branch-divide'"):
        assert gone not in APP_JS, f"Split's chrome is drawn again: {gone}"
    assert 'id="branch-rail"' in INDEX
    # And the band collapses to nothing when it is holding nothing.
    assert ".branch-zone:has(> [hidden]){min-height:0;padding:0}" in STYLE


def test_the_branch_band_yields_when_the_keyboard_takes_the_screen():
    """`interactive-widget=resizes-content` shrinks the viewport rather than overlaying it, so
    with the keyboard open the tablet is 601 x 418. The collision gate found the band lying
    across the composer's own input there: `#branch-zone` was 108px of that 418px, with a chip
    at [21,240 274x48] over the field at [33,284 535x46], and four of its rules fired at once.
    A quarter of a 418px screen cannot be furniture \u2014 which is what the rest of that media
    query already says about the dock, the orb and the notifications \u2014 so the band yields with
    them. The halves are not what the owner is doing while he is typing into a field.
    """
    keyboard = STYLE[STYLE.index("@media (max-height:520px){"):]
    keyboard = keyboard[:keyboard.index("\n}")]
    assert 'body[data-mode="context"] .branch-zone{display:none}' in keyboard


def test_the_header_band_never_outlives_the_second_half():
    """Found in a screenshot: the band still read "half 1 of 2" over a conversation that had
    one half. A merge or a close came back through `applyBranches`, which redraws the bar — and
    the bar returned on the one-half path before the band was touched. `drawBranchHead` has to
    be asked on every redraw, and hide itself.

    Changed on the owner's ruling of 8 October (DEC-071, ruling 37): with Split deleted there is
    no two-half path, so the bar no longer has a `branches.length < 2` branch to look inside,
    and the header line no longer has anything to say. What this holds is unchanged: every
    redraw asks the header line, and the header line comes out hidden and empty.
    """
    body = APP_JS[APP_JS.index("function drawBranchBar()"):]
    body = body[:body.index("\n}\n")]
    assert "drawBranchHead();" in body, "the header band is left standing when a half goes"
    head = APP_JS[APP_JS.index("function drawBranchHead()"):]
    head = head[:head.index("\n}\n")]
    assert "node.textContent = '';" in head and "node.hidden = true;" in head


def test_a_way_out_of_a_half_either_works_or_says_why_it_cannot():
    """§6 / D-6, the other control in this territory. `turn_dd093f86b92d` posted `open.entity`,
    was refused `not_held`, and the half then drew `half_empty` — the control had been offered
    before its destination was known to exist, and pressing it produced a screen saying the
    half was empty. Two halves to the rule: an offer with no destination at all is drawn
    disabled with the reason on it, and one the Mac refuses stops being a control THEN, with
    the Mac's own words beside it, instead of staying live and dead."""
    chip = APP_JS[APP_JS.index("function offerChip(item)"):]
    chip = chip[:chip.index("\n}\n")]
    # Before the tap: no destination, no live control.
    assert "command === 'open.entity' ? (!item.kind || !item.ref)" in chip
    assert "command === 'open.area' ? !item.area" in chip
    assert "button.className = 'rail-chip is-off';" in chip
    assert "button.setAttribute('aria-disabled', 'true');" in chip
    assert "rail-why" in chip, "a disabled offer says nothing about why"
    # After the tap: the refusal settles the control the finger touched.
    assert "if (answered && answered.ok !== false) return;" in chip
    assert "button.classList.add('is-off');" in chip
    # Was `notifyControl(said, button);`, and that line came out.
    #
    # The rule this test is named for is unchanged and is still asserted, one line below: the
    # refused control stops being a control AND the Mac's own words end up beside it. What
    # changed is that it does so ONCE. `why()` writes the sentence into the button, puts it
    # in the title, and the button is disabled — so the notification was a second, worse
    # claim on the same event, which is the whole of web/notify.js's CONTROL_SHOWS and what
    # §10 forbids. It was also the only `notify` call site in the page carrying no `code`, so
    # two identical refusals could not be deduped; the notification-policy suite caught it
    # from that direction independently.
    #
    # Asserted as "the Mac's words reach the glass, by whatever route" rather than by naming
    # the function, so the next change of route does not need a test change with it.
    assert "why(said.slice(0, 60));" in chip, "the Mac's reason does not reach the control"
    # Over the CODE, not over the comments: the comment above the change names the call it
    # replaced, which is the point of it, and a substring search over the whole body would
    # then be satisfied by the explanation of the removal.
    code = "\n".join(line for line in chip.split("\n") if not line.lstrip().startswith(("//", "/*", "*")))
    assert "notifyControl(" not in code, (
        "a control that already carries its own reason must not also float one (\u00a710)")
    # Which needs both openers to report their outcome, rather than returning nothing.
    for opener in ("async function openEntity(kind, ref, label)", "async function openArea(area, fallback)"):
        body = APP_JS[APP_JS.index(opener):]
        body = body[:body.index("\n}\n")]
        assert "return opened" in body, f"{opener} tells its caller nothing"
    # And the renderer's own shape, so the collision suite's "every control either works, or
    # says why it cannot" sweep holds this to the same rule as a chip drawn in web/ui.js.
    assert "label.className = 'rail-label';" in chip


def test_the_list_step_back_carries_a_word():
    """It was a bare chevron, 44px wide and greyed at the start of a list: four kinds of control
    in one navigation row and this the only one with no name on it. Next says Next."""
    assert '<button id="prev-btn" class="chip chip-step" type="button" hidden aria-label="The one before it in this list">Previous</button>' in INDEX


# --------------------------------------------------------------------------- the glass


def test_the_touch_gate_is_in_the_default_browser_sweep():
    """A gate left out of the default tuple proves nothing between releases, which is exactly
    how accept.js came to be the only check that had ever seen the duplicate `replaceCard`."""
    from experience import browser

    source = Path(browser.__file__).read_text(encoding="utf-8")
    default = source[source.index("for script in (scripts if scripts is not None else"):]
    default = default[:default.index("):")]
    assert "TOUCH_SCRIPT" in default, "the touch gate is not in run_checks' default sweep"
    capture = source[source.index("for extra in (TABLET_SCRIPT"):]
    capture = capture[:capture.index("):")]
    assert "TOUCH_SCRIPT" in capture, "the touch gate takes no screenshots"
    assert browser.TOUCH_SCRIPT.exists()


def test_the_touch_gate_measures_both_viewports_and_uses_real_touches():
    """`element.click()` dispatches straight at the node and cannot be swallowed by anything
    painted over it, so no gate that uses it could ever have seen D-1."""
    gate = (ROOT / "scripts" / "browser" / "touch.js").read_text(encoding="utf-8")
    assert "601, height: 889" in gate.replace("width: ", "") or "width: 601, height: 889" in gate
    assert "width: 800, height: 1280" in gate
    assert "Input.dispatchTouchEvent" in gate
    # And nothing in it presses a control by reaching into the DOM.
    assert not re.search(r"\.click\(\)\s*;?\s*\}?\s*\)?,?\s*'(Split|Merge|Close)", gate)
    # The labels as the gate presses them: `tapControl(label, …)` reports "tap <label>".
    # The row-overflow check the collision gate cannot make.
    assert "async function railFits(where)" in gate
    assert "nav.scrollWidth" in gate and "nav.clientWidth" in gate
    # [checker, 8 Oct 2026] Split, Merge and Close were `tapControl(...)`, pressed with a finger. Split
    # is retired (DEC-050, 20 Sep), so the gate now holds that none of the three is on the screen,
    # under the same "tap <label>" names (scripts/browser/touch.js `absent`).
    for required in ("absent('Split'", "absent('Merge'", "absent('Close'",
                     "tapControl('Back'", "tapControl('Home'", "tapControl('Next'",
                     "tapControl('a text field'", "tapControl('a notification'",
                     "tapControl('an action chip on a card'", "tapControl('an order card\\'s row'",
                     "tapControl('a customer card\\'s tab'", "a scroll that begins",
                     "two fingers", "is still a question", "a dock icon",
                     # [checker, 8 Oct 2026, review note N2] The same taps on a list asked for out loud.
                     "'Home on an order opened from a list asked for out loud'",
                     "'Back on an order opened from a list asked for out loud'",
                     "'Next on an order opened from a list asked for out loud'"):
        assert required in gate, f"the gate does not cover: {required}"
    # The hard gate: zero, asserted as zero.
    assert "ZERO recordings were too short across the whole run" in gate
    assert "recording_too_short" in gate


def test_the_gate_itself_is_run_by_the_suite_and_its_names_are_guarded():
    """It is not run a second time from here, on purpose.

    `TOUCH_SCRIPT` is in `run_checks`' default sweep, so
    `tests/test_browser.py::test_the_page_works_in_a_real_browser` already drives it at both
    viewports — and that test asserts this gate's own check NAMES, which is how the collision
    suite is guarded in this repo. A second Chromium run of the same script would add six
    minutes to every suite run and prove the same thing twice. What is asserted here instead is
    that the guard exists: a run that quietly stopped measuring touches must be a FAILURE and
    not a smaller green number.
    """
    guard = (ROOT / "tests" / "test_browser.py").read_text(encoding="utf-8")
    for name in ("tap Split", "tap Merge", "tap Close",
                 "ZERO recordings were too short across the whole run",
                 "the layer ladder holds on the idle screen"):
        assert name in guard, f"tests/test_browser.py does not guard the touch gate's {name!r}"
