"""What the tablet is allowed to know, and what it must do with the voice.

The client is JavaScript and there is no browser in this suite, so these are read as source
(the renderer itself is exercised under Node — see test_web_js.py). That is weaker than driving
Chrome, and it is not nothing: the things that would be most expensive to discover on the
tablet — a credential in a file served to the browser, a voice that talks over the microphone,
a second microphone stream, markup built from a customer's email — are all visible here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
UI_JS = (WEB / "ui.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
JS_FILES = sorted(p.name for p in WEB.glob("*.js"))


def section(source: str, start: str, end: str | None = None) -> str:
    body = source[source.index(start):]
    return body[: body.index(end)] if end else body


def function_body(source: str, signature: str) -> str:
    """The text of one top-level function, up to its closing brace at column 0."""
    body = source[source.index(signature):]
    return body[: body.index("\n}")]


def inner_body(source: str, signature: str) -> str:
    """The text of one function inside a module wrapper, up to its closing brace at column 2
    (web/action-state.js and web/ui.js are written inside one)."""
    body = source[source.index(signature):]
    return body[: body.index("\n  }") + 4]


# --------------------------------------------------------------------------- the credential


@pytest.mark.parametrize("path", sorted(p.name for p in WEB.iterdir() if p.is_file()))
def test_no_credential_is_served_to_the_browser(path):
    """The key is read from the Keychain on the Mac and used in one header there. Anything
    that looks like a key, a key header, or a direct call to ElevenLabs is a leak."""
    source = (WEB / path).read_bytes().decode("utf-8", errors="ignore")   # icons are binary
    lowered = source.lower()
    for forbidden in ("xi-api-key", "elevenlabs.io", "api.elevenlabs", "elevenlabs_api_key", "shpat_", "myshopify.com"):
        assert forbidden not in lowered, f"{path} names {forbidden}"
    # Key shapes: ElevenLabs keys are sk_ or xi_ followed by a long hex-ish run.
    assert not re.search(r"\b(?:sk|xi)_[A-Za-z0-9]{20,}", source), f"{path} contains a key"


def test_the_tablet_talks_only_to_its_own_backend():
    """Every fetch in the client is a same-origin path. A cross-origin one would be either a
    leak or a dependency the office cannot see."""
    for name in JS_FILES:
        source = (WEB / name).read_text(encoding="utf-8")
        for url in re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", source):
            assert url.startswith("/"), f"{name}: cross-origin fetch: {url}"
    for src in re.findall(r"<script[^>]+src=\"([^\"]+)\"", INDEX):
        assert src.startswith("/static/"), f"index.html loads {src}"
    for href in re.findall(r"href=\"([^\"]+)\"", INDEX):
        assert href.startswith("/static/") or href == "/manifest.webmanifest", f"index.html links {href}"


# --------------------------------------------------------------------------- the renderer


@pytest.mark.parametrize("name", JS_FILES)
def test_no_markup_is_built_from_strings(name):
    """External data reaches the page through textContent and safe DOM construction only."""
    source = (WEB / name).read_text(encoding="utf-8")
    for forbidden in (".innerHTML", ".outerHTML", "insertAdjacentHTML(", "document.write(", "eval(", "new Function(", "srcdoc"):
        assert forbidden not in source, f"{name} uses {forbidden}"


def test_the_renderer_owns_the_vocabulary_and_matches_the_backend():
    from app.presentation import UI_TYPES

    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", UI_JS, re.M))
    assert renderers | {"context_stack"} == set(UI_TYPES)
    # Unknown types draw nothing; there is no generic "render whatever arrived" path.
    assert "if (!isValid(item) || !RENDERERS[item.type]) return null;" in UI_JS


def test_the_frontend_never_chooses_a_component_from_the_prose():
    """The cards come from data.ui, never from answer.includes('order')."""
    assert "CrooksUI.render(data.ui" in APP_JS
    assert not re.search(r"answer\s*\.\s*(includes|match|indexOf|search)\(", APP_JS)
    assert not re.search(r"question\s*\.\s*(includes|match|indexOf)\(", APP_JS)


def test_fixtures_are_behind_the_developer_gate():
    """index.html never loads fixtures.js; app.js injects it only when the Developer view
    switch is turned on (off by default), and everything it renders is marked as a fixture."""
    assert "fixtures.js" not in INDEX
    dev = function_body(APP_JS, "function loadDeveloperTools()")
    assert "script.src = '/static/fixtures.js'" in dev
    assert "'/static/fixtures.js'" not in APP_JS[: APP_JS.index("function loadDeveloperTools()")]
    assert "{ fixture: true }" in dev
    assert "crooks.dev" in APP_JS and "params.has('dev')" in APP_JS
    assert "if (on) loadDeveloperTools();" in function_body(APP_JS, "function setDeveloperView(on)")
    assert '<input type="checkbox" id="dev-toggle"> Developer view' in INDEX
    assert '<section id="dev" class="dev" hidden>' in INDEX
    fixtures = (WEB / "fixtures.js").read_text(encoding="utf-8")
    assert "@example.com" in fixtures and not re.search(r"@(?!example\.com)[\w.-]+\.\w+", fixtures)


def test_the_only_write_path_is_a_proposal_id():
    """No card can send, fulfil, refund or cancel anything, and the one route to a change
    carries a proposal id and a session — never an argument."""
    for name in JS_FILES:
        source = (WEB / name).read_text(encoding="utf-8")
        # /cancel abandons a question in flight; it is the only "cancel" here and changes nothing.
        for verb in ("/send", "/fulfil", "/refund", "/cancel-order", "/cancel_order", "mutation"):
            assert verb not in source, f"{name} mentions {verb}"
    # /command is a read: it moves the branch's own position and redraws what the Mac already
    # holds. What makes it safe to be on this list is that the tablet posts a NAME and a
    # REFERENCE and nothing else — the write boundary's rule applied to the read side, so a
    # tap can never carry the arguments of the thing it triggers.
    posted = function_body(APP_JS, "async function semanticCommand(name, extra)")
    assert "form.set('command', name)" in posted, "semanticCommand is where /command posts are built"
    for field in ("note", "body", "amount", "reason", "address", "subject", "tags"):
        assert f"'{field}'" not in posted, f"the tablet posts {field!r} with a command"

    for endpoint in re.findall(r"fetch\(\s*[`'\"]([^`'\"]+)", APP_JS):
        base = endpoint.split("?")[0].rstrip("/")
        # /branches (a GET, the halves as the Mac holds them) is what a reload asks for.
        assert base in {"/speak", "/health", "/ping", "/turn", "/audio-test", "/reset", "/cancel", "/command", "/branches"} or endpoint.startswith("/state/") or endpoint.startswith("/actions/") or endpoint.startswith("/batches/") or endpoint.startswith("/context/order/") or endpoint.startswith("/branches/"), endpoint
    # The context read carries the session and an order id and nothing else, and is a GET.
    body = function_body(APP_JS, "function collectPending(node, attempt = 0)")
    assert "method:" not in body and "session_id=" in body and "body:" not in body
    body = function_body(APP_JS, "async function commitAction(proposalId, node, nonce)")
    assert body.count("form.append(") == 1 and "form.append('session_id', sessionId)" in body
    assert "/commit`" in body and "method: 'POST'" in body
    # A batch is the same tap at another route: the id the Mac issued and the session, nothing else.
    assert "fetch(`/batches/${encodeURIComponent(proposalId)}/commit`" in body and "fetch(`/actions/${encodeURIComponent(proposalId)}/commit`" in body
    assert "members" not in body and "set_id" not in body
    for forbidden in ("note", "order_id", "amount", "desired"):
        assert f"'{forbidden}'" not in body, f"the tablet must not send {forbidden}"


def test_a_lost_connection_asks_what_happened_rather_than_tapping_again():
    body = function_body(APP_JS, "async function recoverActionState(proposalId)")
    assert "method: 'POST'" not in body and "/commit" not in body
    assert "fetch(`/actions/${encodeURIComponent(proposalId)}?session_id=" in body
    assert "fetch(`/batches/${encodeURIComponent(proposalId)}?session_id=" in body
    commit = function_body(APP_JS, "async function commitAction(proposalId, node, nonce)")
    assert "payload = await recoverActionState(proposalId);" in commit


def test_voice_wins_over_a_tap():
    body = function_body(APP_JS, "function actionBlocked()")
    assert "recording || pendingStart || busy" in body
    submit = function_body(APP_JS, "async function submit(body, isAudio)")
    # The Mac decides what an instruction withdraws and names the cards in its answer; the
    # tablet settles exactly those. A fumbled hold withdraws nothing on either side.
    assert "settleProposals(data.revoked, 'revoked', 'Withdrawn')" in submit
    assert "settlePendingActions('revoked'" not in submit
    assert "renderOpts()" in function_body(APP_JS, "function renderTurn(data)")


def test_success_is_shown_only_from_the_verified_answer():
    body = function_body(APP_JS, "function settleAction(node, payload, status)")
    assert "payload.status === 'verified'" in body
    assert "if (payload.spoken) speakAnswer(String(payload.spoken)" in body
    assert "window.confirm" not in APP_JS and "alert(" not in APP_JS and "prompt(" not in APP_JS


# --------------------------------------------------------------------------- the voice


def test_the_answer_is_spoken_through_the_backend():
    assert "'/speak'" in APP_JS
    assert "speakAnswer(data.answer" in APP_JS


def test_the_answer_text_is_not_made_to_wait_for_the_audio():
    """The text goes on screen, then the cards, then the voice is asked for."""
    body = APP_JS[APP_JS.index("const response = await fetch('/turn', options);"):]
    assert body.index("el.answer.textContent = data.answer") < body.index("renderTurn(data)") < body.index("speakAnswer(data.answer")
    # Not awaited: awaiting it would keep the hold region busy while the voice spoke.
    assert "await speakAnswer(" not in APP_JS


def test_the_browser_voice_is_only_the_fallback():
    """browserSpeak is reachable only from a failure path inside speakAnswer, never directly
    from the turn — otherwise Android would quietly become the normal voice again."""
    assert "browserSpeak(data.answer" not in APP_JS
    for call in re.findall(r"browserSpeak\((.*?)\)", APP_JS, re.S):
        assert "reason:" in call or "text," in call


def test_every_failure_of_the_voice_ends_in_the_fallback():
    speak_answer = section(APP_JS, "async function speakAnswer", "/* ------------------------------------------------------------------ health */")
    for failure in ("!response.ok", "!blob.size", "} catch (error) {", "player.onerror", "audio context suspended"):
        assert failure in speak_answer
    # Five of them: a bad status, an empty body, a dead backend, a player that will not play,
    # and a player bound to an AudioContext that Android will not run.
    assert speak_answer.count("browserSpeak(") >= 5


# --------------------------------------------------------------------------- interruption


def test_holding_the_orb_silences_the_voice_first():
    """The assistant must never be recorded answering itself, and the orb must go straight to
    LISTENING on the touch — no READY flash between SPEAKING and the next question."""
    handler = function_body(APP_JS, "function onHoldStart(event)")
    assert handler.index("unlockSpeech();") < handler.index("stopSpeaking();") < handler.index("setState('LISTENING')") < handler.index("startRecording();")
    # Both hold surfaces use the same handler: the transparent region and the orb itself.
    assert "for (const target of [el.talk, el.orbFrame])" in APP_JS
    assert "target.addEventListener('pointerdown', onHoldStart);" in APP_JS
    # And the recorder stops it again on its own path, for the microphone-test route in.
    assert "stopSpeaking();" in section(APP_JS, "async function startRecording")


def test_a_new_answer_cancels_the_one_before_it():
    speak_answer = section(APP_JS, "async function speakAnswer")
    assert speak_answer.index("stopSpeaking();") < speak_answer.index("await fetch('/speak'")
    # A generation counter, so a response that arrives after the interruption is dropped
    # rather than played over the next question.
    assert speak_answer.count("generation !== speakGeneration") >= 4


def test_stopping_actually_stops_both_engines_and_the_request():
    stop = function_body(APP_JS, "function stopSpeaking()")
    assert "player.pause()" in stop
    assert "speakAbort.abort()" in stop
    assert "speechSynthesis.cancel()" in stop
    assert "speakGeneration += 1" in stop


# --------------------------------------------------------------------------- the microphone


def test_the_microphone_is_opened_once_and_kept_warm():
    """getUserMedia is called in exactly one place, behind a shared promise, and the recorder
    is built from that stream. Stopping tracks after a recording is the first-word clip."""
    assert APP_JS.count("getUserMedia(") == 1
    ensure = function_body(APP_JS, "async function ensureMicStream()")
    assert "if (micIsLive()) return micStream;" in ensure
    assert "if (micOpening) return micOpening;" in ensure
    start = function_body(APP_JS, "async function startRecording()")
    assert "micIsLive() ? micStream : await ensureMicStream()" in start
    assert "new MediaRecorder(stream" in start
    assert "track.stop()" not in start
    # The only place tracks are stopped is the deliberate release, used when the page hides.
    assert APP_JS.count("track.stop()") == 1
    assert "track.stop()" in function_body(APP_JS, "function releaseMicStream()")
    # The microphone test reuses the live stream when there is one, and otherwise tells the
    # owner to hold to speak first: it never opens the microphone itself.
    mic_test = section(APP_JS, "el.micTest.addEventListener", "/* ------------------------------------------------------------- developer */")
    assert ("if (!micIsLive()) {" in mic_test and "Hold to speak once first" in mic_test
            and "const stream = micStream;" in mic_test and "ensureMicStream(" not in mic_test)


def test_the_analysers_hang_off_the_existing_streams():
    """One AudioContext; the mic analyser is attached to the warm stream and the player
    analyser is created once and reconnected to the destination."""
    viz = (WEB / "audio-viz.js").read_text(encoding="utf-8")
    assert viz.count("new AC()") == 1
    assert "createMediaElementSource(player)" in viz
    assert "if (!ctx || playerSource || ctx.state !== 'running') return" in viz
    assert "analyser.connect(ctx.destination)" in viz
    assert "createMediaStreamSource(stream)" in viz
    assert "getUserMedia" not in viz
    assert "audio.attachMic(stream)" in function_body(APP_JS, "async function ensureMicStream()")
    assert "audio.attachPlayer(player)" in APP_JS


# --------------------------------------------------------------------------- resources


def test_one_player_for_the_life_of_the_page():
    """A new Audio element per answer leaks a decoder per question and eventually plays
    nothing at all. The microphone test is the one exception and is a manual diagnostic."""
    assert "const player = new Audio();" in APP_JS
    assert APP_JS.count("new Audio(") == 2  # the shared player, and the mic-test playback


def test_object_urls_are_revoked():
    assert "function releaseAudioUrl()" in APP_JS
    assert "URL.revokeObjectURL(currentAudioUrl)" in APP_JS
    # Revoked when it ends, when it fails, when it is interrupted, and when the context stalls.
    assert APP_JS.count("releaseAudioUrl()") >= 6


def test_the_volume_is_normal():
    settings = re.findall(r"player\.volume\s*=\s*([^;]+);", APP_JS)
    assert settings and set(settings) == {"1.0"}


def test_nothing_runs_while_the_page_is_hidden():
    hidden = section(APP_JS, "document.addEventListener('visibilitychange'", "});")
    assert "orb.stop()" in hidden and "stopSpeaking()" in hidden and "releaseMicStream()" in hidden
    assert "if (document.hidden || healthInFlight || (busy && !fresh)) return;" in function_body(APP_JS, "async function pollHealth(")
    orb = (WEB / "orb.js").read_text(encoding="utf-8")
    assert "cancelAnimationFrame" in orb
    assert "prefers-reduced-motion" in APP_JS and "reducedMotion" in orb


def test_the_voice_streams_and_every_streaming_failure_plays_whole():
    """MSE playback starts on the first chunk; anything that goes wrong mid-stream replays the
    bytes already received rather than asking ElevenLabs again or going silent."""
    assert "MediaSource.isTypeSupported('audio/mpeg')" in APP_JS
    stream = function_body(APP_JS, "async function playStream(")
    assert "received.push(value)" in stream
    assert "playAudio(new Blob(received, { type: 'audio/mpeg' })" in stream
    assert "generation !== speakGeneration" in stream
    assert "reader.cancel()" in stream
    # The whole-file path and the Android voice remain behind it, untouched.
    assert "function playAudio(blob, text, generation, isError, startAt = 0)" in APP_JS


def test_both_playback_paths_guard_against_a_silent_context():
    """A player bound to a suspended AudioContext plays nothing. Streaming and whole-file
    playback both hand that case to the fallback, through one shared check."""
    assert APP_JS.count("guardSilentContext(generation") >= 2
    assert "function guardSilentContext(generation, onSilent)" in APP_JS
    assert "playAudio(new Blob(received, { type: 'audio/mpeg' }), text, generation, isError, reached)" in APP_JS


def test_a_turn_in_flight_can_be_abandoned_by_holding():
    assert "const controller = new AbortController();" in function_body(APP_JS, "async function submit(body, isAudio)")
    cancel = function_body(APP_JS, "function cancelTurnAndListen()")
    # The cancel names the half it is abandoning: with the orb divided the other half may be
    # mid-thought about something else, and its turn must survive this one being dropped
    # (app/routes/turn.py:/cancel, app/providers/max_agent_sdk.py:interrupt).
    assert "turnAbort.abort()" in cancel and "cancelTurn(cancelForm(focusedBranch)," in cancel and "startRecording()" in cancel
    assert "form.append('branch_id', branchId)" in function_body(APP_JS, "function cancelForm(branchId)")
    assert "fetch('/cancel'" in function_body(APP_JS, "function cancelTurn(form, whyItIsSafeToIgnore)")
    hold = function_body(APP_JS, "function onHoldStart(event)")
    assert "cancelHoldTimer = setTimeout(cancelTurnAndListen, CANCEL_HOLD_MS)" in hold
    assert "clearTimeout(cancelHoldTimer)" in function_body(APP_JS, "function onHoldEnd(event)")


def test_the_owner_is_told_about_the_mac_not_a_backend():
    for word in ("backend", "Backend"):
        for line in APP_JS.splitlines():
            if word in line and ("textContent" in line or "lastErrorTitle" in line or "healthRow(" in line):
                raise AssertionError(f"owner-facing copy says backend: {line.strip()}")
    assert "'Degraded'" not in APP_JS
    assert "function faultLabel(checks)" in APP_JS


def test_a_new_build_reloads_the_page_only_when_idle():
    body = function_body(APP_JS, "function maybeReloadForNewBuild(build)")
    assert "if (!idle()) return;" in body
    assert "location.reload()" in body


def test_the_turn_says_whether_the_voice_will_be_asked_for():
    assert "form.append('speak', el.speakToggle.checked ? '1' : '0');" in APP_JS
    assert "speak: el.speakToggle.checked" in APP_JS


def test_the_context_deck_is_bounded():
    assert "const MAX_HISTORY = 6;" in APP_JS
    assert "while (history.length > MAX_HISTORY) history.shift();" in APP_JS


# --------------------------------------------------------------------------- autoplay


def test_the_first_touch_unlocks_all_three_engines():
    """Android plays neither audio nor speechSynthesis until the page has been touched, and
    an AudioContext will not start anywhere else. The hold is that touch."""
    unlock = function_body(APP_JS, "function unlockSpeech()")
    assert "player.play()" in unlock
    assert "SpeechSynthesisUtterance" in unlock
    assert "audio.ensure()" in unlock
    assert "unlockSpeech();" in function_body(APP_JS, "function onHoldStart(event)")


# --------------------------------------------------------------------------- the settings sheet


def test_the_settings_sheet_says_which_voice_is_which():
    assert "Fallback voice" in INDEX
    assert "Speak answers aloud" in INDEX and "Show timings" in INDEX
    assert "Microphone test" in INDEX and "New conversation" in INDEX
    assert 'id="health-detail"' in INDEX
    # The real voice's name comes from the backend, never hard-coded here.
    assert "data.voice" in APP_JS and "voice.voice" in APP_JS


def test_the_shell_is_the_orb_not_a_dashboard():
    assert 'id="orb"' in INDEX and "<canvas" in INDEX
    assert 'id="talk"' in INDEX and "Hold to speak" in INDEX
    # V0.5 invariant 2: the idle line names the assistant and says the session is
    # continuous. "System ready. / What do you need?" framed CLIVE as an empty command
    # prompt that forgets between questions, which is the opposite of what it is.
    assert "CLIVE ready" in INDEX and "Ask, interrupt, or continue" in INDEX
    assert "How can I help" not in INDEX
    # Two navs and no more: the context rail (where the conversation has been) and the dock
    # (four areas, either side of the hold). No sidebar, no menu, no tabs across the top —
    # the orb is the shell, and the dock is a shortcut into what the orb already answers.
    assert INDEX.count("<nav") == 2 and 'id="context-nav"' in INDEX and 'id="dock"' in INDEX
    assert "<aside" not in INDEX and "sidebar" not in INDEX.lower() and "<menu" not in INDEX
    # Every dock icon asks a sentence the fast lane answers; none is a route of its own.
    import re
    asks = re.findall(r'class="dock-btn"[^>]*data-ask="([^"]+)"', INDEX)
    assert len(asks) == 4 and all(a.strip() for a in asks)


def test_the_voice_request_cannot_hang_the_tablet():
    """If the Mac's voice has not even answered its headers in fifteen seconds, Android's
    voice starts; an abort by the timer is a failure, an abort by the owner is not."""
    speak = section(APP_JS, "async function speakAnswer", "/* ------------------------------------------------------------------ health */")
    assert "SPEAK_HEADERS_TIMEOUT_MS" in speak and "controller.timedOut = true" in speak
    assert "if (controller.signal.aborted && !controller.timedOut) return;" in speak
    assert "reason: controller.timedOut ? 'voice timed out'" in speak


def test_the_pollers_never_stack_requests():
    """A pad on a bad link must not queue a poll per tick and release them all at once when
    the link returns — hundreds of /state and /health hits in one second, each /health a
    whisper inference on the Mac. One request in flight per poller, and none that waits
    forever."""
    health = section(APP_JS, "async function pollHealth", "const HEALTH_NAMES")
    assert "if (document.hidden || healthInFlight || (busy && !fresh)) return;" in health
    assert "signal: controller.signal" in health and "healthInFlight = false" in health
    assert "HEALTH_TIMEOUT_MS" in health
    state = section(APP_JS, "function startStatePolling", "function stopStatePolling")
    assert "if (!busy || inFlight || document.hidden) return;" in state
    assert "signal: controller.signal" in state and "inFlight = false" in state
    assert "STATE_POLL_TIMEOUT_MS" in state


def test_a_card_already_on_screen_is_not_pushed_again():
    """A spoken yes re-presents the waiting card; the tablet keeps the one it shows (and the
    order beside it) rather than pushing a second copy onto the deck."""
    body = function_body(APP_JS, "function renderTurn(data)")
    assert "if (ui.hasContext && onlyLiveCardsAlreadyShown(data.ui))" in body
    keep = function_body(APP_JS, "function onlyLiveCardsAlreadyShown(items)")
    # The states are named once, in web/action-state.js; this reads them from there.
    assert "'confirmation'" in keep and "'ARMING'" in keep and "'ARMED'" in keep


def test_letting_go_of_a_question_settles_the_cards_the_mac_withdrew():
    """/cancel withdraws whatever the abandoned question proposed and names those cards; the
    tablet settles exactly those, so none is left armed for a tap the Mac would refuse."""
    body = function_body(APP_JS, "function cancelTurn(form, whyItIsSafeToIgnore)")
    assert "fetch('/cancel'" in body
    assert "settleProposals(data.revoked, 'revoked', 'Withdrawn')" in body
    assert "cancelTurn(cancelForm(askedBranch)," in function_body(APP_JS, "async function submit(body, isAudio)")


def test_the_action_states_are_named_in_one_place_and_both_files_read_it():
    """D-1: `committing` was a bare string in the renderer and the correction path settled two
    other bare strings, so the one state that could be stuck was the one nothing touched. The
    states are named once now, and the page and the renderer both read that file."""
    machine = (WEB / "action-state.js").read_text(encoding="utf-8")
    for state in ("READY", "STAGED", "ARMING", "ARMED", "EXECUTING", "VERIFYING", "VERIFIED", "FAILED", "EXPIRED", "UNDONE"):
        assert f"'{state}'" in machine, state
    assert "const TERMINAL = ['VERIFIED', 'FAILED', 'EXPIRED', 'UNDONE'];" in machine
    assert "const IN_FLIGHT = ['EXECUTING', 'VERIFYING'];" in machine
    # The page takes its vocabulary, its labels and its settling from there, and keeps no
    # second copy of any of them.
    assert "const AS = window.CrooksActionState;" in APP_JS
    assert "AS.labelFor(code, 'Not applied')" in APP_JS, "the page keeps no second label table"
    assert "ACTION_LABELS" not in APP_JS
    assert "RECONCILE_SETTLED" not in APP_JS, "nor a second table of what the Mac's statuses mean"
    assert "actionState()" in UI_JS, "the renderer reads the same machine"
    # And the page is served it before either of them.
    assert INDEX.index("/static/action-state.js") < INDEX.index("/static/ui.js") < INDEX.index("/static/app.js")


def test_a_card_settles_from_every_state_but_a_terminal_one():
    """The old guard settled `arming` and `armed` only, and a committed card is in
    `committing`: a send the Mac had proved said "Applying…" for the rest of the session."""
    machine = (WEB / "action-state.js").read_text(encoding="utf-8")
    settle = inner_body(machine, "  function settleCard(node, token, label)")
    assert "if (isTerminal(tokenOf(node))) return false;" in settle
    assert "'arming'" not in settle and "'armed'" not in settle, "no state is named in the guard"
    assert "node.settle(token, label);" in settle
    # And the page's own settleProposals is that function, over the cards it is holding.
    body = function_body(APP_JS, "function settleProposals(ids, state, label)")
    assert "AS.settleProposals(ids, state, label, visibleCards())" in body


def test_a_surface_stuck_in_flight_is_corrected_and_recorded_as_a_defect():
    """The watchdog. A surface still EXECUTING or VERIFYING after its proposal reached a
    terminal state on the Mac is the September defect itself, so it is recorded as one rather
    than quietly repaired — and a commit whose answer never comes back is chased."""
    body = function_body(APP_JS, "async function reconcileActions(reason)")
    assert "AS.reconcile(visibleCards(), states)" in body
    assert "T.record('action_watchdog'" in body
    assert "for (const surface of stuck)" in body
    watch = function_body(APP_JS, "function watchCommit(node, tries)")
    assert "AS.isInFlight(AS.tokenOf(node))" in watch and "reconcileActions('watchdog')" in watch
    assert "watchCommit(node, WATCHDOG_TRIES);" in function_body(APP_JS, "async function commitAction(proposalId, node, nonce)")
    # Nothing is ever re-sent by any of it: the Mac's record decides, and it is only asked.
    assert "fetch(`/actions/${encodeURIComponent(proposalId)}/commit`" not in body


def test_the_page_stops_asking_about_a_card_the_mac_has_finished_with():
    """Six reconciles of two settled proposals, one round trip each, correcting nothing: the
    live session's telemetry recorded the bug once a turn and nobody read it."""
    body = function_body(APP_JS, "function liveProposalIds()")
    assert "AS.liveProposalIds(visibleCards())" in body
    machine = (WEB / "action-state.js").read_text(encoding="utf-8")
    live = inner_body(machine, "  function liveProposalIds(nodes)")
    assert "if (isTerminal(card.token)" in live


def test_a_proved_change_replaces_its_own_affordance_and_retires_the_others():
    """On VERIFIED: the Apply surface goes and the proof takes its place — carrying the entity
    as the Mac has just re-read it, and the undo as a control of its own — the deck's history
    is patched where it stands so navigation does not move, and any other card still offering
    a change to the thing that has just moved says so."""
    body = function_body(APP_JS, "function settleAction(node, payload, status)")
    assert "replaceCardNodes(node, rendered.nodes);" in body, "the affordance is replaced, not appended"
    assert "pushContext(" not in body, "a settled change never pushes a new screen"
    assert "retireStaleAffordances(ref," in body and "if (proven) {" in body
    # The fresh entity is patched into every other card showing it, in place. This assertion
    # was written against `function replaceCard(oldNode, newNodes)` and passed for as long as
    # that text existed in the file — while the browser, which hoists the LAST declaration of
    # a name, ran a different function of the same name and never reached this one. The
    # assertion is the same; it now names the function the call site above actually calls.
    replace = function_body(APP_JS, "function replaceCardNodes(oldNode, newNodes)")
    assert "entry.nodes.splice(at, 1, ...newNodes)" in replace and "refreshEntityCards(node)" in replace


def test_no_two_functions_in_the_page_share_a_name():
    """D-1's neighbour, found in Phase 4. `function f(){}` twice in one script is not an error
    in JavaScript: the second declaration is hoisted over the first and every call in the file
    — including the ones written above it — reaches the second. web/app.js declared
    `replaceCard` twice, one taking drawn NODES and one taking a ui list, so settleAction's
    `replaceCard(node, rendered.nodes)` handed DOM nodes to CrooksUI.render and the proof of a
    verified change was never drawn. A string test cannot see this by reading one body, so it
    is asserted over the whole file, for every script the tablet loads."""
    for path in sorted(p for p in WEB.iterdir() if p.suffix == ".js"):
        names = re.findall(r"^function ([A-Za-z0-9_$]+)\(", path.read_text(encoding="utf-8"), re.M)
        twice = sorted({n for n in names if names.count(n) > 1})
        assert not twice, f"{path.name} declares {', '.join(twice)} more than once"


def test_an_undo_offer_is_not_counted_as_a_change_still_waiting():
    """D-2. The offer is a property of a change that is finished; the renderer marks it as
    one, and an offer that lapses on the glass is let go on the Mac — never applied there."""
    assert "node.dataset.undoOf = text(undo.undo_of || d.proposal_id);" in UI_JS
    body = function_body(APP_JS, "function dismissUndo(proposalId)")
    assert "/dismiss" in body and "method: 'POST'" in body
    assert "onUndoExpire: dismissUndo," in function_body(APP_JS, "function renderOpts()")
    machine = (WEB / "action-state.js").read_text(encoding="utf-8")
    split = inner_body(machine, "  function waiting(states)")
    assert "if (entry.undo_of) undoable.push(String(id)); else pending.push(String(id));" in split


def test_the_tablet_never_erases_what_it_has_already_proved():
    """A tap that did not go through — an undo the Mac has withdrawn, say — settles its own
    surface. It never replaces the card that records the change that did go through."""
    body = function_body(APP_JS, "function settleAction(node, payload, status)")
    assert "card-success" in body and "payload.status !== 'verified'" in body
    assert "if (rendered.nodes.length && !keepTheCard)" in body


def test_a_recording_too_short_to_send_is_seen_and_felt():
    """The sub-line is hidden beside the cards, which is exactly when this happens most."""
    assert "el.errline.textContent = TOO_SHORT;" in APP_JS
    assert "const TOO_SHORT = 'That was too short — hold while you speak.';" in APP_JS


# ------------------------------------------------------- what the assistant can do, on screen


def test_the_settings_sheet_reports_every_capability_state_from_the_mac():
    """Brief section 29: the tablet uses the family states to enable, disable, hide or EXPLAIN
    — without guessing. The owner could not tell "I can't do that" from "the shop has not
    granted that permission", and the second is the one he can fix.
    """
    assert 'id="families"' in INDEX, "the settings sheet has nowhere to report them"
    # Read from the health payload, not decided here.
    assert "renderFamilies(data.families)" in function_body(APP_JS, "async function pollHealth(fresh = false)")
    words = function_body(APP_JS, "const FAMILY_WORDS = {")
    for state in ("READY", "READ_ONLY", "MISSING_SCOPE", "NOT_SUPPORTED_BY_STORE",
                  "DISCONNECTED", "NOT_IMPLEMENTED", "TEMPORARILY_UNAVAILABLE"):
        assert state in words, f"{state} would be printed to the owner as a machine word"
    row = function_body(APP_JS, "function familyRow(family)")
    # The reason is shown when there is something to explain, and the scope named when the
    # Mac's sentence does not already carry it: that scope is the one thing the owner has to
    # go and grant in Shopify.
    assert "state !== 'READY'" in row and "family.scope" in row
    listing = function_body(APP_JS, "function renderFamilies(families)")
    assert "!f.hide" in listing, "a family the Mac says to hide would still be listed"
    assert "(a.state === 'READY') - (b.state === 'READY')" in listing, "the unavailable ones are the ones worth reading first"
    # Offline, the section says so rather than keeping the last good list on screen.
    assert "the server cannot be reached" in function_body(APP_JS, "async function pollHealth(fresh = false)")


def test_one_delegate_owns_a_card_button_and_it_can_read_what_the_card_wrote():
    """A card's button must reach the Mac with the arguments the card put on it.

    Two Phase 3 families each appended a delegated click handler for `[data-command]`, each
    guarded by `window.__crooksCommandDelegate`. The guard did its job — the second never runs
    — and that is the defect, because the two parse `data-args` DIFFERENTLY:

        the live one   for (const [k, v] of new URLSearchParams(button.dataset.args || ''))
        the dead one   JSON.parse(button.dataset.args || '{}')

    and `web/ui.js` writes the variant picker's Add button with `JSON.stringify`. Parsing that
    JSON as a query string yields ONE nonsense key and no `order_id`, no `variant_id`, no
    `quantity`: the button is enabled, looks interactive, and cannot do its job. That is the
    brief's fake UI exactly, and the existing test asserted only that the guard was present —
    it tested the mechanism that caused the bug.

    So: exactly one registration, and whatever encoding a card writes, the delegate reads.
    """
    registrations = APP_JS.count("window.__crooksCommandDelegate = true")
    assert registrations == 1, (
        f"{registrations} command delegates are registered; all but the first are dead code, "
        "and a card whose arguments only the dead one could read has a button that does nothing"
    )

    # Every encoding a card actually writes.
    writes_json = "dataset.args = JSON.stringify(" in UI_JS
    writes_query = bool(re.search(r"dataset\.args\s*=\s*new URLSearchParams", UI_JS))
    assert writes_json or writes_query, "no card writes data-args at all — the check would be vacuous"

    # Follow the call rather than guessing at a slice: the delegate hands `data-args` to one
    # named parser, and that parser is what has to read both encodings.
    delegate = section(APP_JS, "window.__crooksCommandDelegate = true", "el.talk.addEventListener")
    assert "commandArgs(button.dataset.args)" in delegate, (
        "the delegate should read its arguments through one named parser, so this test can "
        "check that parser rather than re-reading the handler's internals"
    )
    parser = function_body(APP_JS, "function commandArgs(raw)")
    if writes_json:
        assert "JSON.parse(" in parser, "a card writes JSON args and the parser does not read JSON"
    if writes_query:
        assert "URLSearchParams(" in parser, "a card writes query-string args and the parser does not read them"
    # And it reads the OTHER encoding too, so neither card style can regress silently.
    assert "JSON.parse(" in parser and "URLSearchParams(" in parser, parser[:200]


def test_a_card_the_mac_has_taken_away_leaves_the_glass():
    """§19 — visual state outranks the spoken claim — asserted at the one place it failed.

    `compose.discard` answers "Gone. Nothing was saved.", sets `branch.compose = None` and
    sends `changed.discarded` with the composer's id and NO `ui`, because a discarded
    composer has nothing left to draw. Nothing on the tablet acted on that key, so Cancel
    SPOKE and the composer stayed exactly where it was — and the owner's next tap on it was
    refused `no_composer`, the Mac having discarded a card the screen still showed.

    §33's click-path matrix is what found it, and the finding is worth quoting because it
    reads as the opposite of the defect:

        PATH 3-customer-inbox-compose-cancel · step 7 · the discard action → no email_compose
        INERT — "Cancel" does nothing even when activated directly. email_compose is still
        on the glass · the Mac said: /command 200 answer="There is no email open on this
        half to do that to."

    That refusal is the SECOND tap. The first worked; the glass did not follow. Instrumenting
    the refusal to print what it was comparing said so in one run:
    `asked='cmp_77b0e6b06c' held=None branch='br_64e4ee1'`.

    This assertion is deliberately about the MECHANISM rather than the one command: any
    `changed.discarded` the Mac sends takes its card off the deck, so a second Mac-side
    removal does not need a second tablet-side fix.
    """
    handler = APP_JS[APP_JS.index("const answered = await semanticCommand(name, args);"):]
    handler = handler[:handler.index("\n}\n")]
    assert "changed.discarded" in handler, (
        "a /command reply that says a card is gone does not take it off the glass")
    assert 'data-compose="' in handler and ".remove()" in handler, handler[-400:]
    # And the selector is built through an escape, not by interpolating a payload value raw.
    assert "cssEscape(" in handler, "an id from the wire goes into a selector unescaped"
    assert "function cssEscape(" in APP_JS
