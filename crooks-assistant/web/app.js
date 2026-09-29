/* CROOKS — the tablet client.
 *
 * Voice first: the owner holds the orb, speaks, releases. The backend transcribes, thinks,
 * looks things up and answers; the answer is spoken by the ElevenLabs voice generated on the
 * Mac and sent here as an MP3 by POST /speak, and shown beside cards the backend chose from
 * the tool results (the `ui` list — see app/presentation.py and ui.js). Android's own
 * speechSynthesis is still here, but only as the fallback for when ElevenLabs cannot answer.
 *
 * Four Android/Chrome behaviours dictate most of the awkward code here, and all four fail
 * silently rather than throwing:
 *   1. Media will not play until the user has touched the page. The hold region is that
 *      touch: the first pointerdown primes the <audio> element, speechSynthesis and the
 *      AudioContext that lets the orb see the voice.
 *   2. speechSynthesis needs a real user gesture too, so the same handler fires a zero-length
 *      utterance to unlock it.
 *   3. speechSynthesis truncates long utterances. We chunk to ~200 characters on sentence
 *      boundaries and chain on `onend`.
 *   4. getVoices() returns [] on the first call. We read it eagerly AND listen for
 *      `voiceschanged`.
 * speechSynthesis.pause() is never called: on Android it behaves as cancel(), so a "pause" is
 * unrecoverable. One <audio> element is reused for every answer — creating one per turn leaks
 * a decoder per question and eventually stops playing anything at all.
 *
 * The microphone is opened once and kept warm. Opening it on every press was the cause of the
 * first word of each question being clipped: getUserMedia takes a few hundred milliseconds to
 * hand over a live track, and the owner had already started speaking.
 * It is opened only by the hold-to-speak press (or on load, where the permission query says
 * it is already granted) — never by another touch, a return to the app or a reconnect. On
 * iOS every opening can be another "would like to access the microphone" while the owner is
 * only reading.
 */

'use strict';

// The Galaxy Tab A 8.0 (2019) has four slow cores and two gigabytes; blur behind the settings
// sheet and a sixty-frame orb are what make it stutter and warm. A device that reports few
// cores or little memory is marked lite: same design, fewer effects, half the orb's frames.
(function markLiteDevice() {
  try {
    const cores = navigator.hardwareConcurrency || 8;
    const memory = navigator.deviceMemory || 8;
    const tabA = /SM-T29\d/.test(navigator.userAgent || '');
    if (cores <= 4 || memory <= 3 || tabA) document.documentElement.dataset.lite = '1';
    // `?lite=0` / `?lite=1` overrides the guess, so the cost of the full design can be measured
    // on a machine that is not lite, and the lite design checked on one that is.
    const forced = new URLSearchParams(location.search).get('lite');
    if (forced === '0') delete document.documentElement.dataset.lite;
    if (forced === '1') document.documentElement.dataset.lite = '1';
  } catch { /* leave the defaults */ }
})();

const $ = (id) => document.getElementById(id);

const el = {
  body: document.body, stage: $('stage'), conn: $('conn'), connText: $('conn-text'),
  system: $('system'), systemTitle: $('system-title'), systemSub: $('system-sub'), systemNote: $('system-note'),
  orb: $('orb'), orbFrame: $('orb-frame'), state: $('state-label'), sub: $('state-sub'),
  heard: $('heard'), answer: $('answer'), errline: $('errline'), timings: $('timings'),
  notesGlobal: $('notes-global'), notesOrb: $('notes-orb'), notesDeck: $('notes-deck'),
  context: $('context'), nav: $('context-nav'), stack: $('stack'), homeBtn: $('home-btn'), backBtn: $('back-btn'),
  armed: $('armed'), armedWhat: $('armed-what'), armedCancel: $('armed-cancel'), dock: $('dock'), branchRail: $('branch-rail'),
  nextBtn: $('next-btn'), prevBtn: $('prev-btn'),
  deck: $('deck'), cards: $('cards'),
  attention: $('attention'), attentionCount: $('attention-count'), attentionText: $('attention-text'),
  recent: $('recent'), recentLabel: $('recent-label'), branchBar: $('branch-bar'), orbZone: $('orb-zone'),
  branchZone: $('branch-zone'), jobZone: $('job-zone'),
  branchHead: $('branch-head'),
  svc: { shopify: $('svc-shopify'), gmail: $('svc-gmail'), voice: $('svc-voice'), changes: $('svc-changes') },
  talk: $('talk'), talkLabel: $('talk-label'),
  settings: $('settings'), settingsBtn: $('settings-btn'), closeSettings: $('close-settings'),
  voiceStatus: $('voice-status'), voiceName: $('voice-name'),
  voiceSelect: $('voice-select'), voiceNote: $('voice-note'), preview: $('preview-voice'),
  micTest: $('mic-test'), speakToggle: $('speak-toggle'), streamToggle: $('stream-toggle'), timingToggle: $('timing-toggle'),
  health: $('health-detail'), families: $('families'), resetSession: $('reset-session'),
  setCanDo: $('set-can-do'), canDo: $('can-do'), setReach: $('set-reach'), reach: $('reach'),
  setNeeds: $('set-needs'), needs: $('needs'),
  dev: $('dev'), devToggle: $('dev-toggle'), devGrid: $('dev-grid'), devText: $('dev-text'),
};

const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

// The developer gate: where the Developer view switch at the bottom of the sheet starts. Off
// unless it was turned on in this browser — by the switch, or by ?dev=1 (?dev=0 turns it off);
// the choice persists so the URL can be plain afterwards. Nothing else reads this flag.
const DEV = (() => {
  try {
    const params = new URLSearchParams(location.search);
    if (params.has('dev')) store.set('crooks.dev', params.get('dev') === '0' ? '0' : '1');
  } catch { /* no URL API */ }
  return store.get('crooks.dev', '0') === '1';
})();

const REDUCED = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false, addEventListener() {} };

// The id names this conversation to the Mac, and /state answers for it: drawn from the
// browser's random source, never from Math.random.
function newSessionId() {
  try {
    const bytes = new Uint8Array(9);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
  } catch { return Math.random().toString(36).slice(2, 14) + Math.random().toString(36).slice(2, 6); }
}
let sessionId = store.get('crooks.session', '') || newSessionId();
store.set('crooks.session', sessionId);
// How many turns this conversation has had, as far as the tablet knows. Sent with each turn
// so the backend can tell "new conversation" from "I restarted and forgot yours".
let turns = parseInt(store.get('crooks.turns', '0'), 10) || 0;
let statePoll = null;

let mediaRecorder = null;
let chunks = [];
let recording = false;
let busy = false;
let wakeLock = null;
let speechUnlocked = false;
let voices = [];
let speakGeneration = 0;     // bumped on every stop; anything from an older generation gives up
let speakAbort = null;       // aborts an in-flight /speak so a new answer never queues behind it
let currentAudioUrl = null;  // the object URL the player is holding, revoked when it is done
let pendingStart = false;    // true between pointerdown and the recorder actually starting
let lastWasError = false;    // so an error stays on screen after it has been read out
let lastErrorTitle = '';
let speakingVia = null;      // 'player' while the ElevenLabs MP3 plays, 'browser' for the fallback
let speakRequestedAt = 0;    // when /speak was asked for the answer now playing
let currentTurnId = '';      // the Mac's id for the last answered turn, sent back with /speak and telemetry
let recordingStartedAt = 0;
let lastRecordingMs = 0;
let scrollMax = 0;           // how far down the cards the owner went since the last render

// What the tablet did, for a test session running on the Mac (web/telemetry.js). Off, every
// call here is a boolean test; nothing on this page ever waits for it.
const T = window.CrooksTelemetry || { record() {}, configure() {}, setContext() {}, flush() {}, snapshot() { return {}; }, pathOnly() { return ''; } };

// The one action state machine (web/action-state.js): the named states a card passes
// through, which of them are terminal, and the rule that the Mac's terminal status settles a
// card from any state that is not. The renderer reads the same file.
const AS = window.CrooksActionState;

// One player, for the life of the page. 2ms of silence, used once inside the first touch to
// prove to Chrome that this element is allowed to make sound.
const player = new Audio();
player.addEventListener('playing', () => {
  if (speakingVia !== 'player') return;
  setState('SPEAKING');
  T.record('speak', { via: 'player', ms: speakRequestedAt ? Date.now() - speakRequestedAt : undefined });
});
player.preload = 'auto';
const SILENT_WAV = 'data:audio/wav;base64,UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YRAAAACAgICAgICAgICAgICAgICA';

/* ------------------------------------------------------------- orb + audio */

// One AudioContext, created on the first touch. The orb reads two levels from it: the warm
// microphone while LISTENING, the ElevenLabs playback while SPEAKING. If either analyser is
// not available the orb falls back to a quiet synthetic pulse — never to silence on screen,
// and never at the cost of the audio itself.
const audio = window.CrooksAudio ? window.CrooksAudio.create() : null;

function syntheticLevel() {
  const t = performance.now();
  return 0.18 + 0.16 * Math.abs(Math.sin(t / 140)) * Math.abs(Math.sin(t / 310));
}

function orbLevel(state) {
  if (state === 'LISTENING') return audio && audio.hasMic ? audio.micLevel() : 0.12;
  if (state === 'SPEAKING') {
    if (speakingVia === 'player' && audio && audio.hasPlayer) return audio.playerLevel();
    return syntheticLevel();
  }
  return 0;
}

const ORB_SIZE = 340;          // drawn size beside nothing
const ORB_SIZE_DOCKED = 140;   // drawn size beside the cards, where it is shown at ~99 px
const orb = window.CrooksOrb
  ? window.CrooksOrb.create(el.orb, { size: ORB_SIZE, reducedMotion: REDUCED.matches, getLevel: orbLevel })
  : null;
REDUCED.addEventListener('change', (event) => { if (orb) orb.setReducedMotion(event.matches); });

/* ------------------------------------------------- the one interaction state */

// V0.5 invariant 2. `live` decides what CLIVE is doing; setState below only paints it, and
// it paints what `live` was told. Every call into it is an EVENT — a thumb went down, the
// words settled, a job started — never an assignment, and never a reading of the DOM.
// web/live-state.js holds the table of what may follow what.
const live = window.CrooksLiveState ? window.CrooksLiveState.create() : null;

// Partial speech while the owner is still speaking, on a tablet whose transcription happens
// on the Mac after the release. There are no interim words to show, so the honest signal is
// the microphone's own energy: above the room's floor, CLIVE is hearing something. Invariant
// 4 forbids an unexplained dead interval more strongly than it demands words.
const HEARING_FLOOR = 0.14;
const HEARING_POLL_MS = 120;
let hearingPoll = null;
function watchForSpeech() {
  stopWatchingForSpeech();
  if (!live || !audio) return;
  hearingPoll = setInterval(() => {
    // Only the FIRST crossing matters here: HEARING is entered once per hold, so a loud room
    // cannot fill the evidence history with four hundred identical transitions.
    if (!recording || live.state !== 'LISTENING') return;
    if (audio.hasMic && audio.micLevel() >= HEARING_FLOOR) live.partial(0);
  }, HEARING_POLL_MS);
}
function stopWatchingForSpeech() { if (hearingPoll) { clearInterval(hearingPoll); hearingPoll = null; } }

/* --------------------------------------------------------- the work in flight */

// Slice C. The jobs of one turn, as objects with names, drawn on the band below the stage.
// No retry is offered from here: the Mac has no endpoint that re-runs a single read, and a
// button that cannot do what it says is worse than no button. web/jobs.js draws one the
// moment there is somewhere safe for it to go.
const jobs = window.CrooksJobs ? window.CrooksJobs.create({ onChange: drawJobs }) : null;
function drawJobs(list) {
  if (window.CrooksJobs) window.CrooksJobs.render(el.jobZone, list);
}

// The Mac reports ONE running tool at a time on /state. A tool that was running and is not
// any more has finished — that is the whole derivation, and it is what makes two reads show
// as two jobs finishing in the order they actually finished rather than as one word.
let runningJob = '';
function noteRunningTool(name) {
  if (!jobs) return;
  const words = DETAIL_WORDS[String(name || '')];
  if (!words) return;                       // a tool with no words of its own is not a job
  if (runningJob === name) return;
  if (runningJob) jobs.done(runningJob);
  runningJob = String(name);
  jobs.note(runningJob, { verb: words[0], object: words[1], state: 'WORKING', writes: words[2] === true });
}

// The turn is over. Whatever was still named as running has finished with it, and the strip
// keeps only work that is unfinished or a failure nobody has read (web/jobs.js endTurn).
function endJobs() {
  if (!jobs) return;
  if (runningJob) { jobs.done(runningJob); runningJob = ''; }
  jobs.endTurn();
}

/* ------------------------------------------------------------------ state */

// What the orb says beneath itself. The first line is the state; the second is what is
// happening in plain words, so the screen reads before the voice does.
const LABELS = {
  READY: ['CLIVE ready', 'Ask, interrupt, or continue'],
  LISTENING: ['Listening', 'Release to send'],
  TRANSCRIBING: ['Heard', 'Working out what you said'],
  THINKING: ['Thinking', 'Working it out'],
  'CHECKING SHOPIFY': ['Shopify', 'Reading the store'],
  'CHECKING EMAIL': ['Email', 'Reading the inbox'],
  SPEAKING: ['Speaking', 'Hold to interrupt'],
  SUCCESS: ['Done', 'Verified'],
  ERROR: ['Something went wrong', 'Hold to try again'],
};

function setState(state, label, sub) {
  // The machine first: the word being painted is translated into the one canonical state
  // (live-state.js's FROM_PRESENTATION). A word it refuses is still painted — a missed
  // mapping should show up in live.refusals(), not take the screen down — but it is the
  // machine, never this line, that anything else asks what CLIVE is doing.
  if (live) live.fromPresentation(state);
  el.stage.dataset.state = state;
  const [title, defaultSub] = LABELS[state] || [state, ''];
  el.state.textContent = label || title;
  el.sub.textContent = sub || defaultSub;
  // The dock says what a hold does right now: cut the voice off, or ask.
  if (!recording) el.talkLabel.textContent = state === 'SPEAKING' ? 'Hold to interrupt' : 'Hold to speak';
  if (orb) orb.setState(state);
}

// What the Mac is doing, in the owner's words. The /state poll carries the running tool's
// name; the screen never shows a tool name.
// What the Mac is doing, in the owner's words. A verb, an object, and whether it CHANGES
// something — never a tool name (invariant 7). One table, read by two surfaces: the sub-line
// under the orb joins the verb and the object into a sentence, and the job strip keeps them
// apart so a long object can ellipse without taking the verb with it.
//
// Every tool the Mac can run has a row, and nothing here names a tool it cannot. That is a
// gate, not an aspiration: tests/test_live_experience_v05_contract.py reads this table against
// the live registry and fails on either side of the mismatch. It found two rows for tools that
// had been gone for some time (`shopify_customer_orders`, `gmail_recent`) and thirty-nine
// tools with nothing to say — which on the job strip meant most of a turn's work showing as
// no work at all.
//
// The third element is the write flag, and it is the Mac's own `ToolSpec.write` rather than a
// judgement made here — a test compares every row against it. Nothing reads it yet; the moment
// a retry is offered it is what stops the tablet offering to re-run a refund (web/jobs.js,
// invariant 9).
const DETAIL_WORDS = {
  // Reading the shop
  shopify_find_order: ['Finding', 'the order'], shopify_order_detail: ['Reading', 'the order'], shopify_list_orders: ['Listing', 'orders'],
  shopify_order_open: ['Opening', 'the order'], shopify_order_build: ['Changing', 'the new order'],
  shopify_order_address: ['Reading', "the order's address"],
  shopify_find_customer: ['Finding', 'the customer'], shopify_customer_history: ['Reading', 'their history'],
  shopify_sales_summary: ['Adding up', 'sales'], shopify_inventory: ['Checking', 'stock'],
  shopify_product_info: ['Reading', 'the product'], shopify_variant_search: ['Finding', 'the size'],
  shopify_abandoned_checkouts: ['Checking', 'abandoned baskets'], shopify_store_credit: ['Checking', 'store credit'],
  shopify_discount_check: ['Checking', 'the discount'], shopify_discount_open: ['Opening', 'the discount'],
  // Changing the shop
  shopify_order_note_append: ['Preparing', 'the note', true], shopify_order_tags_add: ['Tagging', 'the order', true],
  shopify_order_tags_remove: ['Removing', "the order's tag", true], shopify_order_add_item: ['Adding', 'the item', true],
  shopify_order_cancel: ['Cancelling', 'the order', true], shopify_order_create: ['Creating', 'the order', true],
  shopify_order_fulfil: ['Fulfilling', 'the order', true], shopify_refund_create: ['Refunding', 'the order', true],
  shopify_order_shipping_address_set: ['Changing', 'the delivery address', true],
  shopify_fulfillment_tracking_set: ['Adding', 'the tracking number', true],
  shopify_inventory_adjust: ['Changing', 'the stock count', true], shopify_store_credit_add: ['Adding', 'store credit', true],
  shopify_discount_create: ['Creating', 'the discount', true],
  // Reading the inbox
  gmail_search: ['Searching', 'the inbox'], gmail_read_thread: ['Reading', 'the thread'],
  gmail_find_in_email: ['Searching', 'the message'], gmail_compose_open: ['Opening', 'the reply'],
  gmail_compose_fill: ['Writing', 'the reply'],
  // Objectives (CLIVE's own records, nothing outside)
  objective_open: ['Opening', 'the objective'], objective_list: ['Checking', 'your objectives'],
  objective_show: ['Reading', 'the objective'], objective_note: ['Updating', 'the objective'],
  // Changing the inbox
  gmail_draft_reply: ['Drafting', 'the reply', true], gmail_draft_new: ['Drafting', 'a new message', true],
  gmail_send_reply: ['Sending', 'the reply', true], gmail_send_new: ['Sending', 'the message', true],
  gmail_thread_archive: ['Archiving', 'the thread', true],
  // Several at once. These STAGE a batch; the change itself goes through the confirmation
  // path afterwards, so the Mac does not call them writes and neither does this.
  batch_email_drafts: ['Drafting', 'the replies'], batch_email_send: ['Preparing', 'the replies'],
  batch_email_archive: ['Preparing', 'the messages'], batch_order_tags_add: ['Preparing', "the orders' tags"],
  batch_order_tags_remove: ['Preparing', "the orders' tags"],
  // The query layer, which answers without naming one shop read
  commerce_query: ['Reading', 'the shop'], commerce_summary: ['Summarising', 'the shop'],
  commerce_aggregate: ['Adding up', 'the numbers'], commerce_capabilities: ['Checking', 'what the shop allows'],
  email_query: ['Reading', 'the inbox'], inventory_query: ['Checking', 'stock'],
  // Engineering (the remote build loop)
  engineering_status: ['Checking', 'the build queue'],
  submit_engineering_request: ['Preparing', 'a build request', true],
  // The owner's screens
  screen_list: ['Checking', 'your screens'], screen_show: ['Putting', 'it on the screen'],
  screen_pair: ['Approving', 'the screen'],
  // Round 9, the screens remote (web/remote.js): turning a screen off, and this app becoming its remote.
  screen_off: ['Turning', 'the screen off'], screen_remote: ['Opening', 'the remote'],
  // YouTube on a screen: finding a video and putting it on, and working what plays.
  screen_play: ['Finding', 'it on YouTube'], screen_video: ['Telling', 'the video'],
};
const detailSentence = (name) => (DETAIL_WORDS[name] ? `${DETAIL_WORDS[name][0]} ${DETAIL_WORDS[name][1]}` : undefined);
const LONG_THINK_MS = 6000;
let turnStartedAt = 0;
// "2 of 3 read" — the Mac's own count of the reads it is making for this answer
// (app/reads/scheduler.py). Matched as a shape, not a phrase, so a wider plan still reads.
const COUNTED = /^(\d+) of (\d+) read$/;

function detailWords(detail, state) {
  const name = String(detail || '');
  if (DETAIL_WORDS[name]) return detailSentence(name);
  const counted = COUNTED.exec(name);
  if (counted) return `${counted[1]} of ${counted[2]} checked`;
  if (name.indexOf('refused ') === 0) return 'Trying another way';
  const waited = turnStartedAt ? Date.now() - turnStartedAt : 0;
  if (state === 'THINKING' && waited > LONG_THINK_MS) return `Still working · ${Math.round(waited / 1000)} s`;
  return undefined;
}

function setMode(mode) {
  if (el.body.dataset.mode === mode) return;
  el.body.dataset.mode = mode;
  if (mode === 'orb') lightDock([]);
  drawBranchBar();
  // A workspace message follows the workspace: under the orb's caption on the orb screen,
  // above the deck beside cards. Both are in flow, so neither can cover anything.
  if (window.CrooksNotify) window.CrooksNotify.remode();
  el.talk.setAttribute('aria-label', mode === 'orb' ? 'Hold to speak' : 'Hold to speak (dock)');
  // Beside the cards the orb is shown at under a third of its size; it draws at that size
  // rather than painting twelve times the pixels it shows.
  if (orb && typeof orb.setSize === 'function') orb.setSize(mode === 'orb' ? ORB_SIZE : ORB_SIZE_DOCKED);
}

const TOO_SHORT = 'That was too short — hold while you speak.';
// Answers that are about the microphone rather than about the shop. They get a line, not a
// screen: whatever the owner was looking at stays where it is.
const TRANSIENT_ERRORS = ['speech', 'empty', 'audio_too_large'];
const HAPTIC = { start: 12, release: 8, done: [10, 60, 10], error: [40, 50, 40] };
function haptic(pattern) {
  try { if (navigator.vibrate) navigator.vibrate(pattern); } catch { /* unsupported */ }
}

/* -------------------------------------------------------------- wake lock */

async function acquireWakeLock() {
  if (!('wakeLock' in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } catch { /* denied or unsupported; the screen will just sleep */ }
}

// Android drops the lock whenever the page is hidden, so re-acquire on every return. Hidden
// also means: stop talking, stop drawing, and let go of the microphone unless mid-sentence.
// Coming back does not reopen it: the next hold does.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    acquireWakeLock();
    if (orb) orb.start();
    pollHealth();
    // Coming back to a tablet that has been asleep: ask the Mac what actually happened to
    // every card still on screen before believing any of them.
    reconcileActions('wake');
  } else {
    stopSpeaking();
    if (orb) orb.stop();
    if (!recording) releaseMicStream();
  }
});
window.addEventListener('pagehide', () => { stopSpeaking(); releaseMicStream(); });

/* ------------------------------------------------------------------ voices */

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function loadVoices() {
  const list = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  if (!list.length) return;                       // first call is empty in Chrome — wait for the event
  voices = list;
  const saved = store.get('crooks.voice', '');
  clear(el.voiceSelect);
  const sorted = [...voices].sort((a, b) => {
    const rank = (v) => (v.lang === 'en-GB' ? 0 : v.lang.startsWith('en') ? 1 : 2);
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
  for (const voice of sorted) {
    const option = document.createElement('option');
    option.value = voice.name;
    option.textContent = `${voice.name} · ${voice.lang}${voice.localService ? ' · offline' : ''}`;
    if (voice.name === saved) option.selected = true;
    el.voiceSelect.appendChild(option);
  }
  const anyLocalGB = voices.some((v) => v.lang === 'en-GB' && v.localService);
  el.voiceNote.textContent = anyLocalGB
    ? 'A British offline fallback voice is installed.'
    : 'No offline British fallback voice found. Settings → General management → Text-to-speech → Install voice data.';
}
if (window.speechSynthesis) {
  loadVoices();
  window.speechSynthesis.addEventListener('voiceschanged', loadVoices);
}
el.voiceSelect.addEventListener('change', () => store.set('crooks.voice', el.voiceSelect.value));

/* ------------------------------------------------------------------ speech */

function unlockSpeech() {
  // Must happen inside a user gesture, for both engines and for the AudioContext. Chrome M71
  // removed speech without user activation and blocks audio the same way; the failure mode
  // for each is total silence with no error anywhere, so all three are primed on the first
  // touch and never again.
  if (speechUnlocked) return;
  speechUnlocked = true;
  if (audio) audio.ensure();
  try {
    player.src = SILENT_WAV;
    player.volume = 1.0;
    const primed = player.play();
    if (primed && primed.then) {
      primed.then(() => {
        player.pause();
        player.removeAttribute('src');
        // The context is running by now if it ever will be; bind the player to it once.
        if (audio) audio.attachPlayer(player);
      }).catch(() => {});
    }
  } catch { /* the play() below will show whether it mattered */ }
  if (!window.speechSynthesis) return;
  try {
    const primer = new SpeechSynthesisUtterance('');
    primer.volume = 0;
    window.speechSynthesis.speak(primer);
  } catch { /* nothing more we can do */ }
}

function releaseAudioUrl() {
  if (!currentAudioUrl) return;
  URL.revokeObjectURL(currentAudioUrl);
  currentAudioUrl = null;
}

// Silence, immediately and completely, whichever engine is talking. Called before every
// recording and before every new answer, so the assistant can never talk over itself or be
// recorded talking to itself.
function stopSpeaking() {
  speakGeneration += 1;   // anything still running belongs to an old generation now
  if (speakAbort) { try { speakAbort.abort(); } catch { /* noop */ } speakAbort = null; }
  try {
    player.pause();
    player.onended = null;
    player.onerror = null;
    player.removeAttribute('src');
    player.load();        // drops the decoder; without this Chrome keeps the last buffer alive
  } catch { /* nothing was playing */ }
  releaseAudioUrl();
  if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch { /* noop */ } }
  speakingVia = null;
}

// Where the screen lands once nothing is speaking any more.
function settle(isError) {
  speakingVia = null;
  if (!busy && !recording) setState(isError ? 'ERROR' : 'READY', isError ? lastErrorTitle : '');
  // The answer named the build it was made for; if this page is older, take the new one now
  // that nothing is being said.
  if (pendingBuild) { const build = pendingBuild; pendingBuild = null; maybeReloadForNewBuild(build); }
}
let pendingBuild = null;   // the build id the last /turn answered with, checked once speech ends

function chunkForSpeech(text, limit = 200) {
  // A full stop between digits is a decimal point ("£430.50"), not a sentence end.
  const sentences = text.match(/(?:[^.!?]|\.(?=\d))+[.!?]*\s*/g) || [text];
  const out = [];
  let current = '';
  for (const sentence of sentences) {
    if ((current + sentence).length > limit && current) { out.push(current.trim()); current = ''; }
    if (sentence.length > limit) {
      for (const piece of sentence.match(new RegExp(`.{1,${limit}}(\\s|$)`, 'g')) || [sentence]) {
        out.push(piece.trim());
      }
    } else {
      current += sentence;
    }
  }
  if (current.trim()) out.push(current.trim());
  return out.filter(Boolean);
}

// The fallback voice: Android's own, used only when ElevenLabs could not speak this answer.
// `reason` is logged rather than shown — the owner wants the answer, not an apology.
function browserSpeak(text, { isError = false, reason = '' } = {}) {
  T.record('speak', { via: 'browser', reason: reason || undefined, ms: speakRequestedAt ? Date.now() - speakRequestedAt : undefined });
  if (!window.speechSynthesis || !el.speakToggle.checked || !text) { settle(isError); return; }
  console.warn(`[crooks] ElevenLabs voice unavailable (${reason || 'unknown'}) — using the Android voice`);
  const generation = speakGeneration;
  const parts = chunkForSpeech(text);
  const chosen = voices.find((v) => v.name === el.voiceSelect.value);
  let index = 0;
  const finish = () => { if (generation === speakGeneration) settle(isError); };
  const next = () => {
    if (generation !== speakGeneration) return;      // cancelled: do not re-arm the chain
    if (index >= parts.length) { finish(); return; }
    const utterance = new SpeechSynthesisUtterance(parts[index++]);
    if (chosen) { utterance.voice = chosen; utterance.lang = chosen.lang; }
    else utterance.lang = 'en-GB';
    utterance.rate = 1.0;
    utterance.onstart = () => { if (generation === speakGeneration && speakingVia === 'browser') setState('SPEAKING'); };
    utterance.onend = next;
    utterance.onerror = next;   // a failed chunk moves on; a cancelled chain stops above
    window.speechSynthesis.speak(utterance);
  };
  speakingVia = 'browser';
  el.sub.textContent = 'Getting the voice…';
  next();
}

// The normal voice. The answer text is already on screen; this asks the Mac to say it.
//
// The MP3 arrives as one response and is played once it is complete. ElevenLabs streams it and
// the backend forwards it as it arrives, so the wait is the generation, not a second copy of
// the file — and for a two-sentence answer in eleven_flash_v2_5 that is a few hundred
// milliseconds. Every way this can fail ends in browserSpeak, never in silence.
async function speakAnswer(text, { isError = false } = {}) {
  if (!text) { settle(isError); return; }
  if (!el.speakToggle.checked) { settle(isError); return; }
  stopSpeaking();
  const generation = speakGeneration;
  speakRequestedAt = Date.now();
  // The orb says Speaking when sound plays (the player's own event), not now: a voice that
  // is still being fetched is not speaking, and the screen must not say so over silence.
  el.sub.textContent = 'Getting the voice…';
  const controller = new AbortController();
  speakAbort = controller;
  // The Mac gives up on ElevenLabs after ten seconds; a voice whose headers have not arrived
  // by then is not coming, and Android's should start. The body may stream for longer.
  const headersTimer = setTimeout(() => { controller.timedOut = true; controller.abort(); }, SPEAK_HEADERS_TIMEOUT_MS);
  let response;
  try {
    response = await fetch('/speak', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, session_id: sessionId, turn_id: currentTurnId }),
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(headersTimer);
    T.record('speak_headers', { status: response.status, ms: Date.now() - speakRequestedAt });
    if (generation !== speakGeneration) return;    // interrupted while it was generating
    if (response.status === 204) { settle(isError); return; }   // nothing worth saying
    if (!response.ok) {
      let kind = `http ${response.status}`;
      try { kind = (await response.json()).kind || kind; } catch { /* not JSON */ }
      browserSpeak(text, { isError, reason: kind });
      return;
    }
    if (el.streamToggle.checked && canStream() && response.body) {
      // Play as the bytes arrive: the first sentence starts while the last is still being
      // generated. Every failure inside falls back to the whole-file path, then to Android.
      await playStream(response, text, generation, isError);
      return;
    }
    const blob = await response.blob();
    if (generation !== speakGeneration) return;
    if (!blob.size) { browserSpeak(text, { isError, reason: 'empty audio' }); return; }
    playAudio(blob, text, generation, isError);
  } catch (error) {
    clearTimeout(headersTimer);
    if (generation !== speakGeneration) return;
    // An abort is the owner interrupting, not a failure: they are already holding the orb —
    // unless it was the timer, in which case the Mac's voice is not coming.
    if (controller.signal.aborted && !controller.timedOut) return;
    browserSpeak(text, { isError, reason: controller.timedOut ? 'voice timed out' : 'the server unreachable' });
  } finally {
    if (speakAbort === controller) speakAbort = null;
  }
}

// Media Source Extensions: the MP3 is appended to the player as it streams from the Mac.
// Chrome on Android supports the mp3 byte stream; if this tablet ever does not, or anything
// goes wrong mid-stream, the bytes already received are played whole instead.
function canStream() {
  try {
    return Boolean(window.MediaSource) && typeof MediaSource.isTypeSupported === 'function'
      && MediaSource.isTypeSupported('audio/mpeg');
  } catch { return false; }
}

async function playStream(response, text, generation, isError) {
  const source = new MediaSource();
  const url = URL.createObjectURL(source);
  releaseAudioUrl();
  currentAudioUrl = url;
  const received = [];        // every chunk, so a fallback needs no second request
  const queue = [];
  let buffer = null;
  let ended = false;
  let failed = false;
  let total = 0;

  const fallback = (reason) => {
    if (failed) return;
    failed = true;
    console.warn(`[crooks] streaming playback stopped (${reason}); playing whole`);
  };
  const pump = () => {
    if (failed || !buffer || buffer.updating) return;
    if (queue.length) {
      try { buffer.appendBuffer(queue.shift()); } catch (error) { fallback('append failed'); }
      return;
    }
    if (ended && source.readyState === 'open') {
      try { source.endOfStream(); } catch { /* already ended */ }
    }
  };
  source.addEventListener('sourceopen', () => {
    if (generation !== speakGeneration) return;
    try {
      buffer = source.addSourceBuffer('audio/mpeg');
      buffer.addEventListener('updateend', pump);
      buffer.addEventListener('error', () => fallback('buffer error'));
      pump();
    } catch (error) {
      fallback('no source buffer');
    }
  });

  const done = () => {
    if (generation !== speakGeneration) return;
    releaseAudioUrl();
    settle(isError);
  };
  player.onended = done;
  player.onerror = () => {
    if (generation !== speakGeneration) return;
    fallback('player error');
  };
  if (audio) { audio.resume(); audio.attachPlayer(player); }
  speakingVia = 'player';
  player.src = url;
  player.volume = 1.0;
  const started = player.play();
  if (started && started.catch) {
    started.then(() => guardSilentContext(generation, () => fallback('audio context suspended')))
      .catch(() => fallback('autoplay blocked'));
  }

  const reader = response.body.getReader();
  try {
    for (;;) {
      const { done: finished, value } = await reader.read();
      if (generation !== speakGeneration) { try { reader.cancel(); } catch { /* noop */ } return; }
      if (finished) break;
      if (value && value.length) { received.push(value); queue.push(value); total += value.length; pump(); }
    }
  } catch (error) {
    fallback('stream broke');
  }
  ended = true;
  pump();
  if (generation !== speakGeneration) return;
  if (!total) { releaseAudioUrl(); browserSpeak(text, { isError, reason: 'empty audio' }); return; }
  if (failed) {
    // Whatever stopped the stream, the answer is in hand: play it the plain way, from where
    // the stream got to rather than from the start — the owner should not hear it twice.
    let reached = 0;
    try { reached = player.currentTime || 0; player.pause(); } catch { /* noop */ }
    playAudio(new Blob(received, { type: 'audio/mpeg' }), text, generation, isError, reached);
  }
}

// A player bound to an AudioContext that is not running plays silence. That is the one
// failure the analyser path can cause, so it is the one both playback paths check for.
function guardSilentContext(generation, onSilent) {
  if (!audio || !audio.hasPlayer || audio.state === 'running') return;
  setTimeout(() => {
    if (generation !== speakGeneration || audio.state === 'running') return;
    onSilent();
  }, 400);
}

function playAudio(blob, text, generation, isError, startAt = 0) {
  const url = URL.createObjectURL(blob);
  releaseAudioUrl();
  currentAudioUrl = url;
  if (startAt > 0.5) {
    player.addEventListener('loadedmetadata', () => {
      if (generation === speakGeneration) { try { player.currentTime = startAt; } catch { /* not seekable */ } }
    }, { once: true });
  }
  const done = () => {
    if (generation !== speakGeneration) return;   // a newer answer owns the player now
    releaseAudioUrl();
    settle(isError);
  };
  player.onended = done;
  player.onerror = () => {
    if (generation !== speakGeneration) return;
    releaseAudioUrl();
    browserSpeak(text, { isError, reason: 'this device could not play the audio' });
  };
  // The analyser path: resume the context if Android suspended it, and bind the player to it
  // if the first touch did not manage to (the context was still starting). Binding is a
  // one-off; attachPlayer is a no-op once done. Playback is never delayed for it.
  if (audio) { audio.resume(); audio.attachPlayer(player); }
  speakingVia = 'player';
  player.src = url;
  player.volume = 1.0;
  const started = player.play();
  if (started && started.catch) {
    started.then(() => {
      guardSilentContext(generation, () => {
        try { player.pause(); } catch { /* noop */ }
        releaseAudioUrl();
        browserSpeak(text, { isError, reason: 'audio context suspended' });
      });
    }).catch(() => {
      // Chrome refused to play without a gesture. The hold is one, so this should not happen
      // after the first question — but the answer still gets spoken.
      if (generation !== speakGeneration) return;
      releaseAudioUrl();
      browserSpeak(text, { isError, reason: 'autoplay blocked' });
    });
  }
}

/* ------------------------------------------------------------------ health */

// The badge names the thing that is down, in the owner's words, worst first.
function faultLabel(checks) {
  const down = (k) => checks[k] && checks[k].ok === false;
  // The owner's word for what is down, not the provider's name (GENERATIVE_UI_V1 §4).
  if (down('claude')) return 'CLIVE cannot answer';
  /* Was "Cannot hear you", and the visual pass was right about it: on the most prominent
     band of the page, in amber, beside an amber diamond, that reads as the assistant
     refusing to listen rather than as a service being down. §27's question is whether an
     error state is really an error — and this one is: `checks.speech.ok === false` means the
     recogniser is not there. So the amber stays and the WORDS change, to the shape its four
     siblings already use. "Speech offline" names the thing that is down, points at the row
     in the settings sheet that says what to do about it, and does not suggest he is being
     ignored. The footer's own Voice dot says the same thing in the same breath. */
  if (down('speech')) return 'Speech offline';
  if (down('shopify') && down('gmail')) return 'Shopify and Gmail offline';
  if (down('shopify')) return 'Shopify offline';
  if (down('gmail')) return 'Gmail offline';
  if (down('tts') || down('scribe')) return 'Voice fallback in use';
  if (down('whisper')) return 'No offline recogniser';
  return 'Partly offline';
}

// The build this page was made for, stamped into it by the Mac. A page opened from the
// worker's cache while the Mac was away compares itself against the Mac's first answer.
let knownBuild = (() => {
  try {
    const stamp = document.querySelector('meta[name="crooks-build"]');
    const value = stamp ? String(stamp.content || '') : '';
    return value && value !== '__BUILD__' ? value : null;
  } catch { return null; }
})();
function maybeReloadForNewBuild(build) {
  if (!build) return;
  if (knownBuild === null) { knownBuild = build; return; }
  if (build === knownBuild) return;
  // The Mac now serves newer page files. Take them the moment nothing is in progress.
  if (!idle()) return;
  knownBuild = build;
  if (swRegistration) {
    // Let the worker fetch the new build first, so the reload lands on a shell that is
    // already cached; if no new worker takes over, reload anyway after a grace period.
    swRegistration.update().catch(() => {});
    setTimeout(() => { if (!reloadingForUpdate && idle()) location.reload(); }, UPDATE_GRACE_MS);
    return;
  }
  location.reload();
}

function setService(name, ok) {
  const node = el.svc[name];
  if (!node) return;
  // true / false / 'off' (deliberately switched off: not broken, not ready) / unknown.
  node.dataset.ok = ok === true ? 'true' : ok === false ? 'false' : ok === 'off' ? 'off' : 'unknown';
}

// One health request in flight at a time, and never one that waits forever. Without both, a
// pad on a bad link queues a poll every interval and releases them all at once when the link
// returns — hundreds of requests in a second, seen on a second pad — and the Mac runs a
// whisper inference for each.
let healthInFlight = false;
const HEALTH_TIMEOUT_MS = 20000;   // the Mac's own checks give up at 6 s each

async function pollHealth(fresh = false) {
  // Not while a question is in flight: the Mac's checks run whisper and four remote probes,
  // and the answer is what the owner is waiting for.
  if (document.hidden || healthInFlight || (busy && !fresh)) return;
  healthInFlight = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const response = await fetch(fresh ? '/health?fresh=1' : '/health', { cache: 'no-store', signal: controller.signal });
    // The Mac answers 403 to a login it does not list, on every path. That is not "online":
    // the system layer says NOT ALLOWED and the badge must not contradict it every 45 s.
    if (response.status === 403) { wentRefused(); return; }
    if (!response.ok) throw new Error(`health ${response.status}`);
    const data = await response.json();
    T.configure(data.observability);
    if (reachable !== true) wentOnline();
    applyUpdateWhenIdle();
    const checks = data.checks || {};
    const failed = Object.entries(checks).filter(([, c]) => !c.ok).map(([k]) => k);
    // Whether the header says anything about it is decided against what the owner is doing
    // (drawConn): the checks travel with the state for that.
    if (!failed.length) setConn('ok', 'Online');
    else setConn('degraded', faultLabel(checks), checks);
    maybeReloadForNewBuild(data.build);
    setService('shopify', checks.shopify ? checks.shopify.ok : null);
    setService('gmail', checks.gmail ? checks.gmail.ok : null);
    const canHear = !checks.speech || checks.speech.ok;
    const canSpeak = !checks.tts || checks.tts.ok;
    setService('voice', canHear && canSpeak);
    // Whether a prepared change could be applied from here at all — visible on the ready
    // screen, before anyone proposes one and taps into a refusal.
    const writesState = data.writes && data.writes.state;
    setService('changes', writesState === 'ready' ? true : writesState === 'disabled' ? 'off' : writesState ? false : null);
    renderHealthRows(checks);
    renderFamilies(data.families);
    drawOwnerSettings(data);
    const voice = data.voice || {};
    if (voice.voice) {
      el.voiceName.textContent = voice.enabled ? voice.voice : "This device's own voice";
      el.preview.textContent = voice.enabled ? `Preview ${voice.voice}` : 'Preview voice';
    }
    el.voiceStatus.textContent = voice.ok === false ? 'Unavailable' : voice.enabled === false ? 'Off' : 'Ready';
    el.voiceStatus.className = `badge quiet ${voice.ok === false ? 'bad' : voice.enabled === false ? 'warn' : 'ok'}`;
  } catch {
    setConn('down', 'Offline');
    setService('shopify', null); setService('gmail', null); setService('voice', null); setService('changes', null);
    clear(el.health);
    el.health.appendChild(healthRow(false, 'the server', 'Cannot reach the assistant. Is the server up, and is the assistant running on it?'));
    if (el.families) { clear(el.families); el.families.appendChild(familyRow({ label: 'Everything', state: 'TEMPORARILY_UNAVAILABLE', detail: 'the server cannot be reached' })); }
    // Nothing is known about the services while CLIVE cannot be reached, so the owner's
    // sections that are drawn from them are left out rather than kept from the last answer.
    drawOwnerSettings(null);
    el.voiceStatus.textContent = 'Unknown';
    el.voiceStatus.className = 'badge quiet';
    wentOffline();
  } finally {
    clearTimeout(timer);
    healthInFlight = false;
  }
}
const HEALTH_NAMES = {
  claude: 'Claude', speech: 'Hearing', scribe: 'ElevenLabs hearing', whisper: 'Offline hearing',
  tts: 'Voice', shopify: 'Shopify', gmail: 'Gmail', knowledge_base: 'Knowledge', terminology: 'Product names',
  writes: 'Changes',
};
function healthRow(ok, name, detail) {
  const row = document.createElement('div');
  row.className = 'hrow';
  row.dataset.ok = ok ? 'true' : 'false';
  const dot = document.createElement('span'); dot.className = 'hdot';
  const label = document.createElement('span'); label.className = 'hname'; label.textContent = name;
  const text = document.createElement('span'); text.className = 'hdetail'; text.textContent = detail || '';
  row.appendChild(dot); row.appendChild(label); row.appendChild(text);
  return row;
}
// What the assistant can do, by family, with the reason when it cannot (brief section 29).
// The states come from the Mac (app/capabilities/families.py) and are shown as they are: the
// tablet never decides that store credit is unavailable, it reports that the Mac said so.
// The same table decides which tools the model is offered at all, so this section explains
// what the owner will and will not be able to ask for — before he asks.
const FAMILY_WORDS = {
  READY: 'Ready', READ_ONLY: 'Read only', MISSING_SCOPE: 'Needs permission',
  NOT_SUPPORTED_BY_STORE: 'Not on this store', DISCONNECTED: 'Not connected',
  NOT_IMPLEMENTED: 'Not built yet', TEMPORARILY_UNAVAILABLE: 'Not answering',
};
function familyRow(family) {
  const state = String(family.state || 'NOT_IMPLEMENTED');
  const row = document.createElement('div');
  row.className = 'frow';
  row.setAttribute('role', 'listitem');
  row.dataset.state = state;
  row.dataset.ready = state === 'READY' ? 'true' : 'false';
  const name = document.createElement('span'); name.className = 'fname'; name.textContent = family.label || family.key || '';
  const word = document.createElement('span'); word.className = 'fstate'; word.textContent = FAMILY_WORDS[state] || state;
  row.appendChild(name); row.appendChild(word);
  // The reason, in the Mac's words. A missing scope names the scope, which is what the owner
  // has to grant in Shopify — the one thing he cannot work out from the tablet.
  const detail = String(family.detail || '');
  if (detail && state !== 'READY') {
    const line = document.createElement('span'); line.className = 'fdetail';
    line.textContent = family.scope && detail.indexOf(family.scope) === -1 ? `${detail} (${family.scope})` : detail;
    row.appendChild(line);
  }
  return row;
}
function renderFamilies(families) {
  if (!el.families) return;
  clear(el.families);
  const rows = Object.keys(families || {}).map((key) => ({ key, ...(families[key] || {}) }))
    // A family the Mac says to hide is hidden; the rest are grouped by area so the list reads
    // like the shop rather than like a registry, unavailable ones first — those are the ones
    // worth reading.
    .filter((f) => !f.hide && f.key !== '_error')
    .sort((a, b) => (a.state === 'READY') - (b.state === 'READY') || String(a.area).localeCompare(String(b.area)) || String(a.label).localeCompare(String(b.label)));
  if (!rows.length) {
    el.families.appendChild(familyRow({ label: 'Capabilities', state: 'TEMPORARILY_UNAVAILABLE', detail: 'the server did not list them this time' }));
    return;
  }
  for (const family of rows) el.families.appendChild(familyRow(family));
}

function renderHealthRows(checks) {
  clear(el.health);
  const order = ['claude', 'speech', 'tts', 'shopify', 'gmail', 'writes', 'scribe', 'whisper', 'knowledge_base', 'terminology'];
  for (const key of order) {
    const c = checks[key];
    if (!c) continue;
    el.health.appendChild(healthRow(c.ok, HEALTH_NAMES[key] || key, c.detail));
  }
}

/* ----------------------------------------------------- the owner's settings */

// GENERATIVE_UI_V1 §4: the sheet is the owner's. What CLIVE can do for you, who and what it can
// reach, and what it needs from you — in plain words, drawn from the /health answer the page
// already polls, and never naming the machine CLIVE runs on. The backend's own detail strings
// are engineering text, so they stay in the Developer view; these rows use the words the Mac
// already writes for a person (`what`, `reason`) or say it plainly here. A section with nothing
// true to say is left out, never filled with a placeholder.

// "voice is paused because …" → "Voice is paused because ….": the backend's plain reasons are
// clauses, and the sheet prints sentences.
function plainSentence(words) {
  const said = String(words || '').trim();
  if (!said) return '';
  const first = said.charAt(0).toUpperCase() + said.slice(1);
  return /[.!?]$/.test(first) ? first : `${first}.`;
}

// The actions CLIVE may prepare: every family that stages a change and is ready to. Each one
// is a proposal the owner taps to apply, which the section's own line says once.
function canDoRows(families) {
  return Object.keys(families || {}).map((key) => ({ key, ...(families[key] || {}) }))
    .filter((f) => f.key !== '_error' && !f.hide && f.state === 'READY' && Array.isArray(f.operations) && f.operations.length)
    .sort((a, b) => String(a.area).localeCompare(String(b.area)) || String(a.label).localeCompare(String(b.label)))
    .map((f) => ({ name: String(f.label || f.key), detail: plainSentence(f.what) }));
}

// What a failed Shopify or Gmail check means for the owner. /health sends the check's own words,
// which are engineering text — an exception name, a status code, a stored credential — so they
// are sorted here into a few kinds with a plain reason and what to do, and the words themselves
// stay in the Developer view. Only a kind known to clear by itself says so: access that was
// refused or never set up waits for a person. First match wins, so the narrower kinds come
// first: an app and a shop in different Shopify organisations is refused access too, but for a
// reason reconnecting the same way will not fix.
const SERVICE_FAULT_KINDS = {
  shopify: [
    ['organisation', /shop_not_permitted|different shopify organi[sz]ations?/i],
    ['setup', /no shopify_static_token|not configured|not stored/i],
    ['busy', /\b429\b|rate-limit|throttl/i],
    ['unreachable', /could not reach|timed out|timeout|\b5\d\d\b/i],
    ['access', /\b40[13]\b|revoked|rejected the token|token request failed|not released|installed/i],
  ],
  gmail: [
    ['setup', /no gmail token stored/i],
    ['unreachable', /timed out|timeout|could not reach|unable to find the server|\b5\d\d\b/i],
    ['access', /RefreshError|invalid_grant|refresh|authoris|authoriz|expired|credential|token|\b40[13]\b/i],
  ],
};
const SERVICE_WORDS = {
  shopify: { name: 'Shopify', place: 'your shop', purpose: 'read your orders, products and sales' },
  gmail: { name: 'Gmail', place: 'your inbox', purpose: 'read your email' },
};
// The kinds that wait for the owner, and the word each has among the owner's steps. The others —
// busy, unreachable, unknown — establish no step: they clear by themselves or are not the owner's.
const SERVICE_STEP_WORDS = { setup: 'Not connected', access: 'Needs reconnecting', organisation: 'Needs reconnecting' };
function serviceFault(key, check) {
  const said = String((check && check.detail) || '');
  const found = (SERVICE_FAULT_KINDS[key] || []).find(([, pattern]) => pattern.test(said));
  const kind = found ? found[0] : 'unknown';
  const { name, place, purpose } = SERVICE_WORDS[key];
  const word = 'Needs attention';
  if (kind === 'setup') {
    return { kind, word, detail: `${name} is not connected to CLIVE yet. Connect ${name} so CLIVE can ${purpose}.` };
  }
  if (kind === 'organisation') {
    return {
      kind, word,
      detail: `CLIVE's Shopify connection belongs to a different Shopify organisation from ${place}, so ${place} will not let it in. `
        + `Reconnect ${place} to CLIVE through ${place}'s own Shopify organisation so CLIVE can ${purpose}.`,
    };
  }
  if (kind === 'access') {
    const why = key === 'gmail'
      ? 'Google has stopped letting CLIVE into your inbox — a Google password change does this, for example.'
      : 'Shopify has stopped letting CLIVE into your shop — its access was withdrawn or has run out.';
    return { kind, word, detail: `${why} Reconnect ${name} to CLIVE so it can ${purpose} again.` };
  }
  if (kind === 'busy') {
    return { kind, word: 'Busy', detail: `${name} asked CLIVE to slow down for a moment. It picks up again by itself; there is nothing to do.` };
  }
  const why = kind === 'unreachable'
    ? `CLIVE could not reach ${place} on its last check.`
    : `${name} did not answer CLIVE as expected on its last check.`;
  return { kind, word, detail: `${why} If it stays like this for more than a few minutes, ask for CLIVE's connection to ${name} to be checked.` };
}

// What a failed voice or transcription check means for the owner. /health sends the failure's
// kind and a plain reason for it; the reason says what happened but not always what to do, so
// the kind decides the next step. Credits used up wait for a top-up (the owner's step, in
// needsRows); a slow, busy or unreachable moment clears by itself; a key or voice that is wrong
// does not, and waits for a person. Anything else — no kind, a kind not listed here, a cooldown
// after a failure of either sort — is watched for a few minutes and then escalated.
const SPEECH_FAULT_KINDS = {
  credit: ['credit'],
  passing: ['timeout', 'network', 'server_error', 'rate', 'cancelled', 'prefetch', 'bad_response', 'empty', 'truncated'],
  setup: ['no_key', 'rejected', 'forbidden', 'no_voice', 'off'],
};
const SPEECH_WORDS = {
  voice: {
    subject: "CLIVE's voice", credit: 'Voice is paused because the ElevenLabs credits are used up.',
    unknown: "CLIVE's voice is not answering.", retry: '',
  },
  transcription: {
    subject: "CLIVE's listening", credit: 'Speech recognition is paused because the ElevenLabs credits are used up.',
    unknown: 'CLIVE cannot hear you just now.', retry: ' Try speaking again then.',
  },
};
function speechFault(which, kind, reason) {
  const words = SPEECH_WORDS[which];
  const group = Object.keys(SPEECH_FAULT_KINDS).find((g) => SPEECH_FAULT_KINDS[g].indexOf(kind) !== -1) || 'unknown';
  const why = plainSentence(reason) || (group === 'credit' ? words.credit : words.unknown);
  const steps = {
    credit: 'Top up the ElevenLabs plan to bring it back.',
    passing: `It usually clears by itself within a few minutes; there is nothing to do.${words.retry}`,
    setup: `This does not clear by itself: ask for ${words.subject} to be checked.`,
    unknown: `If it stays like this for more than a few minutes, ask for ${words.subject} to be checked.`,
  };
  return { kind: group, detail: `${why} ${steps[group]}` };
}

// Each connected service, as connected or as needing attention with the plain reason and what
// to do. Only the services /health reports: a check it did not run is not a row.
function reachRows(data) {
  const checks = (data && data.checks) || {};
  const voice = (data && data.voice) || {};
  const speech = (data && data.speech) || {};
  const rows = [];
  const connected = (name) => ({ name, state: 'ok', word: 'Connected' });
  const attention = (name, detail) => ({ name, state: 'attention', word: 'Needs attention', detail });
  for (const key of ['shopify', 'gmail']) {
    if (!checks[key]) continue;
    const name = SERVICE_WORDS[key].name;
    if (checks[key].ok) { rows.push(connected(name)); continue; }
    const fault = serviceFault(key, checks[key]);
    rows.push({ name, state: 'attention', word: fault.word, detail: fault.detail });
  }
  if (checks.tts || (data && data.voice)) {
    if (voice.enabled === false) {
      rows.push({ name: 'Voice', state: 'off', word: 'Off', detail: "Answers are spoken in this device's own voice." });
    } else if (voice.ok === false || (checks.tts && checks.tts.ok === false)) {
      const fault = speechFault('voice', voice.failure_kind, voice.reason);
      rows.push(attention('Voice', `${fault.detail} Until then, answers are spoken in this device's own voice.`));
    } else {
      rows.push(connected('Voice'));
    }
  }
  if (checks.speech) {
    rows.push(checks.speech.ok ? connected('Transcription')
      : attention('Transcription', speechFault('transcription', speech.scribe_failure_kind, speech.scribe_reason).detail));
  }
  return rows;
}

// A family's `what` cut to its first clause and started in lower case, to sit inside a sentence:
// "Create a discount code — a percentage or …" → "create a discount code".
function shortWhat(what) {
  const said = String(what || '').split(/ — |, /)[0].trim().replace(/[.!?]$/, '');
  return said ? said.charAt(0).toLowerCase() + said.slice(1) : '';
}

// Which service holds a family's permission, and what must be connected for a family that is
// not: said as the owner would, never as the scope or the provider's identifier. The exact
// scope and the backend's reason stay in the Developer view's list of families.
function permissionHolder(f) {
  return /gmail|googleapis/i.test(String(f.scope || '')) || f.area === 'email' ? 'Gmail' : 'Shopify';
}
// A disconnected family's subject comes from its reported reason where that is narrower than
// its area (a carrier, not any shipping provider), and otherwise from the area. An area with no
// service to name has no step to give, so nothing is said rather than "the service it needs".
const CONNECT_SUBJECTS = {
  shipping: 'a shipping provider', email: 'Gmail',
  orders: 'Shopify', customers: 'Shopify', products: 'Shopify', analytics: 'Shopify',
};
function connectSubject(f) {
  const said = String(f.detail || '');
  if (/\bcarrier\b/i.test(said)) return 'a carrier';
  if (/\bshipping provider\b/i.test(said)) return 'a shipping provider';
  if (/\bgmail\b/i.test(said)) return 'Gmail';
  if (/\bshopify\b/i.test(said)) return 'Shopify';
  return CONNECT_SUBJECTS[f.area] || '';
}

// Only the open steps /health already names as the owner's: a service to connect or reconnect,
// a permission a change is waiting for, a family whose service is not connected, and credits
// that have run out — each as the task it turns on and the one thing the owner does.
function needsRows(data) {
  const checks = (data && data.checks) || {};
  const families = (data && data.families) || {};
  const voice = (data && data.voice) || {};
  const speech = (data && data.speech) || {};
  const rows = [];
  for (const key of ['shopify', 'gmail']) {
    if (!checks[key] || checks[key].ok !== false) continue;
    const fault = serviceFault(key, checks[key]);
    const word = SERVICE_STEP_WORDS[fault.kind];
    if (word) rows.push({ name: SERVICE_WORDS[key].name, state: 'attention', word, detail: fault.detail });
  }
  for (const key of Object.keys(families).sort()) {
    const f = families[key] || {};
    if (key === '_error' || f.hide) continue;
    const task = shortWhat(f.what);
    if (f.state === 'MISSING_SCOPE') {
      const holder = permissionHolder(f);
      const detail = task
        ? `CLIVE does not yet have ${holder}'s permission to ${task}. Allow it in ${holder} to turn this on.`
        : `CLIVE does not yet have the ${holder} permission this needs. Allow it in ${holder} to turn this on.`;
      rows.push({ name: String(f.label || key), state: 'attention', word: 'Needs your permission', detail });
    } else if (f.state === 'DISCONNECTED') {
      const subject = connectSubject(f);
      if (!subject) continue;
      const tell = /^(whether|what|which|when|where|who|how)\b/.test(task) ? ` so CLIVE can tell you ${task}` : ' to turn this on';
      rows.push({ name: String(f.label || key), state: 'attention', word: 'Not connected', detail: `Connect ${subject}${tell}.` });
    }
  }
  if (voice.failure_kind === 'credit' || speech.scribe_failure_kind === 'credit') {
    rows.push({
      name: 'ElevenLabs plan', state: 'attention', word: 'Top up',
      detail: voice.failure_kind === 'credit'
        ? speechFault('voice', 'credit', voice.reason).detail
        : speechFault('transcription', 'credit', speech.scribe_reason).detail,
    });
  }
  return rows;
}

function ownerRow(row) {
  const node = document.createElement('div');
  node.className = 'orow';
  node.setAttribute('role', 'listitem');
  node.dataset.state = row.state || 'ok';
  const name = document.createElement('span'); name.className = 'oname'; name.textContent = row.name;
  node.appendChild(name);
  if (row.word) { const word = document.createElement('span'); word.className = 'ostate'; word.textContent = row.word; node.appendChild(word); }
  if (row.detail) { const line = document.createElement('span'); line.className = 'odetail'; line.textContent = row.detail; node.appendChild(line); }
  return node;
}

function fillSection(section, list, rows) {
  if (!section || !list) return;
  clear(list);
  for (const row of rows) list.appendChild(ownerRow(row));
  section.hidden = !rows.length;
}

// `null` when nothing is known — CLIVE cannot be reached — and every section drawn from /health
// is left out rather than kept from the last answer.
function drawOwnerSettings(data) {
  fillSection(el.setCanDo, el.canDo, data ? canDoRows(data.families) : []);
  fillSection(el.setReach, el.reach, data ? reachRows(data) : []);
  fillSection(el.setNeeds, el.needs, data ? needsRows(data) : []);
}

// The header says something only while something is wrong AND it matters to what the owner is
// doing (invariant 8, GENERATIVE_UI_V1 §4). Offline always matters, and so do CLIVE being
// unable to answer or to hear. A service matters while the screen is reading from it — the shop
// behind Orders, Sales and Products, the inbox behind Inbox. The voice falls back by itself and
// a missing offline recogniser changes nothing the owner does, so neither is ever the header's.
// When all is well the header shows nothing at all.
const FAULT_REACH = { claude: '*', speech: '*', shopify: ['orders', 'sales', 'products'], gmail: ['email'] };
function relevantFaults(checks, area) {
  const out = {};
  for (const key of Object.keys(checks || {})) {
    const check = checks[key];
    const where = FAULT_REACH[key];
    if (!check || check.ok !== false || !where) continue;
    if (where === '*' || where.indexOf(area) !== -1) out[key] = check;
  }
  return Object.keys(out).length ? out : null;
}

let connState = 'connecting';
let connText = 'Connecting';
let connChecks = null;
function setConn(state, text, checks) {
  connState = state;
  connText = text;
  connChecks = checks || null;
  drawConn();
}
// Drawn again whenever the area on screen changes (lightDock), because a fault that did not
// matter on the orb screen matters the moment the owner opens the place it breaks.
function drawConn() {
  let state = connState;
  let text = connText;
  if (state === 'degraded') {
    const faults = relevantFaults(connChecks, el.body.dataset.area || '');
    if (faults) text = faultLabel(faults);
    else state = 'ok';
  }
  el.conn.dataset.state = state;
  el.connText.textContent = text;
  el.conn.hidden = state !== 'down' && state !== 'degraded';
}

pollHealth();
setInterval(() => pollHealth(false), 45000);   // /ping watches reachability far more often; this is the detail

/* ------------------------------------------------------------- microphone */

const MIC_CONSTRAINTS = {
  audio: {
    echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    channelCount: 1,
    sampleRate: { ideal: 16000 },   // ideal, never exact — exact fails outright on some devices
  },
};
let micStream = null;     // the one warm stream; the recorder and the analyser both use it
let micOpening = null;    // the in-flight getUserMedia, shared so two presses open one stream

function micIsLive() {
  return Boolean(micStream) && micStream.getAudioTracks().some((track) => track.readyState === 'live');
}

async function ensureMicStream() {
  if (micIsLive()) return micStream;
  if (micOpening) return micOpening;
  micOpening = (async () => {
    const stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
    for (const track of stream.getAudioTracks()) {
      // Android ends the track when another app takes the microphone. Forget the stream so
      // the next press opens a fresh one rather than recording silence.
      track.addEventListener('ended', () => {
        if (micStream === stream) { micStream = null; if (audio) audio.detachMic(); }
      });
    }
    micStream = stream;
    if (audio) audio.attachMic(stream);   // analysis only; MediaRecorder reads the same tracks
    return stream;
  })();
  try { return await micOpening; } finally { micOpening = null; }
}

function releaseMicStream() {
  if (!micStream) return;
  if (audio) audio.detachMic();
  for (const track of micStream.getTracks()) track.stop();
  micStream = null;
}

function warmMic() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  ensureMicStream().catch(() => { /* the press will report the real error */ });
}

// Warm on load only when the permission query says, positively, that it is already granted.
// Otherwise the first hold-to-speak press opens it: never any other touch, a return to the
// app or a reconnect, each of which asked the owner again on iOS while only reading.
if (navigator.permissions && navigator.permissions.query) {
  navigator.permissions.query({ name: 'microphone' })
    .then((status) => { if (status && status.state === 'granted') warmMic(); })
    .catch(() => {});
}

function pickMimeType() {
  const candidates = [
    'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4',
  ];
  for (const type of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

/* ------------------------------------------------- live words and the real waveform */
/* web/live-voice.js, wired here because the microphone is here. While the owner holds, the ask
 * bar's capsule draws what the microphone actually hears (audio-viz's analyser, never a guess)
 * and the words ElevenLabs makes of it so far. They are for him to watch and nothing else: the
 * recording is still sent whole on release, its transcript is the one CLIVE answers, and when
 * it comes back it takes the live words' place. Anything that fails here goes quiet and the
 * hold carries on as it always did; without web/live-voice.js none of this runs at all.
 *
 * Where the words go (round 9, C-03 and G-01), and the only places: `onWords` puts them in three
 * text nodes marked `data-spoken` (#ask-words, #ask-heard, and the tablet's line under the orb
 * while he holds), which a copy of the screen masks (web/telemetry.js copyScreen). Never into
 * telemetry: `record` takes the `live_transcript` event alone, through the file's own
 * telemetryFields (fixed words and whole numbers). Never into a question: sendAudio sends the
 * recording, and the question on the glass is the Mac's transcript. Never kept: once the Mac has
 * said what it heard, or the turn is over, or the hold came to nothing, settleLiveWords takes
 * them off the bar and live-voice.js lets them go. The single-use key is live-voice.js's alone:
 * the one request this file lets it make is POST /voice/live. */
const LiveVoice = window.CrooksLiveVoice || null;
const liveWords = LiveVoice ? LiveVoice.create({
  audio,
  // Its one request, to the Mac, for the key. Anything else it asked for would be refused here.
  fetch: (url, init) => (url === '/voice/live' ? fetch(url, init) : Promise.reject(new Error('not a request live words may make'))),
  // How it went, in its own fixed words and numbers; never a word of what was said.
  record: (kind, fields) => { if (kind === 'live_transcript') T.record(kind, LiveVoice.telemetryFields(fields)); },
  onWords: (text) => showLiveWords(text),
}) : null;
const liveWave = LiveVoice ? LiveVoice.wave({
  canvas: () => document.getElementById('ask-wave'),
  analyser: () => Boolean(audio && audio.hasMic),
  level: () => (audio ? audio.micLevel() : 0),
  reduced: () => REDUCED.matches,
}) : null;
let liveHeardFinal = false;   // the Mac's own transcript is on the bar; the live words give way to it
let liveHold = 0;             // which hold the words on the bar are from: a turn settles only its own

function liveBegin(stream) {
  if (!LiveVoice) return;
  // A stream warmed at load, before the first touch made the context, has no analyser (and so
  // no level and nothing to tap). Attaching now is a no-op when it already has one.
  if (audio) { audio.resume(); audio.attachMic(stream); }
  liveHold += 1;
  liveHeardFinal = false;
  showLiveWords('');
  if (liveWave) liveWave.start();
  if (liveWords) liveWords.begin();
}

function liveEnd(discard) {
  if (!LiveVoice) return;
  if (liveWave) liveWave.stop();
  if (liveWords) { if (discard) liveWords.cancel(); else liveWords.release(); }
  // The line under the orb goes back to saying what the machine is doing (setState writes it).
  el.sub.removeAttribute('data-spoken');
}

function showLiveWords(text) {
  const words = String(text || '');
  const bar = document.getElementById('ask-bar');
  const box = document.getElementById('ask-words');
  if (box) box.textContent = words;
  // One line or two: the capsule grows to what is there, never to an empty line.
  const lines = !words ? 'false' : box && box.getBoundingClientRect().height > 30 ? '2' : '1';
  if (bar) bar.dataset.words = lines;
  if (!liveHeardFinal) showHeardWords(words, false);
  // The tablet's layout has no capsule: the line under the orb carries them while he holds,
  // marked as the bar's own boxes are so that a copy of the screen keeps how much, not what.
  if (!el.body.classList.contains('alpha') && recording) {
    el.sub.textContent = words || LABELS.LISTENING[1];
    if (words) el.sub.setAttribute('data-spoken', ''); else el.sub.removeAttribute('data-spoken');
  }
}

// What the bar's "Working on it" face says was heard: the live words, then the Mac's transcript.
function showHeardWords(text, final = true) {
  if (!LiveVoice) return;
  const words = String(text || '').trim();
  if (final && words) liveHeardFinal = true;
  const bar = document.getElementById('ask-bar');
  const heard = document.getElementById('ask-heard');
  if (heard) heard.textContent = words ? `“${words}”` : '';
  if (bar) bar.dataset.heard = words ? 'true' : 'false';
}

/* The live words have done their job: the Mac has said what it heard (`question`, which the bar
 * then shows in their place), or the turn is over without saying (`question` empty: the bar is
 * cleared, never left showing words that were not the question asked), or the hold came to
 * nothing. The words leave the bar and live-voice.js lets them and their socket go. `hold` is
 * the hold they must be from; words from a newer hold, on the bar or still being heard, are
 * left alone (round 9, G-02 and C-03). */
function settleLiveWords(question, hold) {
  if (!LiveVoice) return;
  if (hold !== undefined && hold !== liveHold) return;
  if (recording) return;   // a new hold has begun: the bar is its words now
  liveHeardFinal = true;   // before the drop, so its '' does not also clear the Mac's words
  if (liveWords) liveWords.drop();
  const box = document.getElementById('ask-words');
  const bar = document.getElementById('ask-bar');
  if (box) box.textContent = '';
  if (bar) bar.dataset.words = 'false';
  const words = String(question || '').trim();
  showHeardWords(words, true);
}

// The app went away mid-hold: the words stop with it, and the next hold starts them afresh.
if (LiveVoice) document.addEventListener('visibilitychange', () => { if (document.hidden && liveWords) liveWords.cancel(); });
/* ------------------------------------------- live words and the real waveform · end */

// Everything this page says goes through here, and web/notify.js decides where it appears:
// on the control, in the workspace, or — for the two states of the machine itself — above the
// wordmark, in flow. Nothing floats over the dock, the orb, the halves or the composer any
// more, because nothing here is positioned over anything.
//
// D-10: `toast(words)` IS GONE. It was the one way to say something without naming it, and
// eleven of the live session's sixteen notifications came through it — recorded as
// `{name:"workspace", tone:"info"}` and nothing else, because a code is the only thing that
// makes a message nameable, deduplicable, testable, or refusable. Every caller in this file
// now says WHICH message it is, and web/notify.js refuses one that does not.
function notify(message, where) {
  const words = String(message || '').trim();
  const api = typeof window !== 'undefined' ? window.CrooksNotify : null;
  if (!words || !api) return null;
  const spec = Object.assign({ text: words, class: 'workspace', tone: 'info' }, where || {});
  // A message about a half is that half's. The live session threw "Merged. 2 changes still
  // waiting over there." over the half the owner was reading; a branch-scoped message is
  // hidden while the other half is focused, and is still there when he comes back to it.
  if (spec.branch === undefined && spec.class === 'workspace' && focusedBranch) spec.branch = focusedBranch;
  return api.show(spec);
}

// A NAME for a message whose name came off the wire. web/notify.js requires every message to
// carry a lower_snake_case `code` and refuses one that does not — which would silently lose a
// refusal whose code the Mac spelled some other way. The boundary normalises it here rather
// than the policy loosening for it.
function codeOf(raw, fallback) {
  const name = String(raw || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return /^[a-z][a-z0-9_]*$/.test(name) ? name : fallback;
}

// CONTROL-LOCAL: the words appear directly after the control they are about, inside its own
// card, so they scroll with it and cover nothing. A control with no parent on screen any more
// falls back to the workspace rather than being dropped.
function notifyControl(message, control, where) {
  const host = control && control.parentNode ? control.parentNode : null;
  if (!host) return notify(message, where);
  return notify(message, Object.assign({ class: 'control', host, after: control }, where || {}));
}

// Heard nothing, or nothing usable. Say so on one line and leave the screen alone: the
// cards, the tab and the scroll are all exactly where the owner left them. A recogniser
// that missed a word must not cost him what he was reading.
function sayAndStay(data) {
  // A FALLBACK, because `data.answer` can be empty and a message with no words is not a
  // message — one of the eleven. And `warn` rather than `bad`: a missed word is not a
  // failure that has to be acknowledged before the screen can be used again, and the whole
  // point of this path is to leave the screen alone.
  notify(String(data.answer || '').trim() || 'Nothing usable was heard. Say it again.',
    { tone: 'warn', code: 'not_heard' });
  el.answer.textContent = '';
  setState('READY', '');
  speakAnswer(data.answer, { isError: true });
  renderTimings(data.timings_ms, data.transcript);
}

function showMicError(message) {
  lastWasError = true;
  lastErrorTitle = 'Microphone unavailable';
  el.errline.textContent = message;
  setState('ERROR', lastErrorTitle);
  haptic(HAPTIC.error);
}

async function startRecording() {
  if (recording || busy || pendingStart) return;
  pendingStart = true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    pendingStart = false;
    showMicError(window.isSecureContext
      ? 'This browser has no microphone support.'
      : 'The microphone needs a secure HTTPS connection. Open the tailscale ts.net address, not the LAN address.');
    return;
  }
  try {
    // Warm path: no await, so the recorder starts inside the same task as the touch.
    const stream = micIsLive() ? micStream : await ensureMicStream();
    if (!pendingStart) return;   // the thumb lifted while permission was being granted
    discardRecording = false;
    const mimeType = pickMimeType();
    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 32000 } : {});
    chunks = [];
    mediaRecorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    mediaRecorder.onstop = () => {
      // The stream stays open: the next press starts recording on the first sample.
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
      if (discardRecording) { discardRecording = false; setState('READY'); return; }
      if (blob.size > 800) { sendAudio(blob); return; }
      // Too short to be a question. The sub-line is hidden beside the cards, so this goes
      // where it can always be read, with the buzz that says the tablet noticed.
      setState('READY');
      settleLiveWords('');   // no question was asked, so no live words are left on the bar
      el.sub.textContent = TOO_SHORT;
      el.errline.textContent = TOO_SHORT;
      haptic(HAPTIC.error);
      T.record('recording_too_short', { ms: lastRecordingMs });
    };
    mediaRecorder.start(250);
    recording = true;
    recordingStartedAt = Date.now();
    el.talk.dataset.recording = 'true';
    el.talkLabel.textContent = 'Release to send';
    setState('LISTENING');
    watchForSpeech();
    liveBegin(stream);   // the capsule's live words and waveform (web/live-voice.js)
    if (orb) orb.pulse();
    haptic(HAPTIC.start);
  } catch (error) {
    showMicError(error && error.name === 'NotAllowedError'
      ? 'Microphone permission was refused. Allow it in the browser settings, choosing "While using the app".'
      : 'Could not open the microphone. Check nothing else is using it.');
    console.warn('[crooks] microphone', error);
  } finally {
    pendingStart = false;
  }
}

function stopRecording(discard = false) {
  pendingStart = false;      // a release before the recorder started cancels the start
  if (!recording) return;
  recording = false;
  discardRecording = discard;
  el.talk.dataset.recording = 'false';
  el.talkLabel.textContent = 'Hold to speak';
  // The thumb lifted: say so now, on this frame. The encoder takes its time to flush and
  // the orb must not keep listening to the room while it does.
  lastRecordingMs = recordingStartedAt ? Date.now() - recordingStartedAt : 0;
  T.record('hold', { phase: 'release', ms: lastRecordingMs, outcome: discard ? 'discarded' : 'sent' });
  stopWatchingForSpeech();
  liveEnd(discard);   // a cancel clears the live words; a release commits them and keeps them on screen
  // The instant the owner starts waiting. Everything after it is measured from here, so it
  // is marked here rather than backdated from whatever happens to land first.
  if (live && !discard) live.released();
  if (discard) setState('READY');
  else { setState('TRANSCRIBING'); haptic(HAPTIC.release); }
  try { mediaRecorder.stop(); } catch { /* already stopped */ }
}
// A cancelled pointer — a palm, an edge swipe, the notification shade — ends the recording
// without sending it. Half a sentence is not a question.
let discardRecording = false;

/* ------------------------------------------------------------ context deck */

// What is on the surface, most recent last. Each entry is one turn's cards (or a fixture),
// kept as DOM so going back is a move, not a re-render. Bounded, because it is DOM.
const history = [];
const MAX_HISTORY = 6;
let historyIndex = -1;
let currentStack = [];

// One deck per half. The variables above are the FOCUSED half's; the others' are kept here
// and swapped in when the owner taps a half. The Phase 2 live test found that tapping the
// other half changed who was listening and nothing visible — the previous half's cards
// stayed on screen while the owner talked to a half that was looking at something else.
const decks = new Map();      // branch_id -> { history, index, stack, set, answer, heard }
let deckBranch = '';          // which half the variables above belong to

function stashDeck() {
  if (!deckBranch) return;
  decks.set(deckBranch, {
    history: history.slice(), index: historyIndex, stack: currentStack, set: currentSet,
    answer: el.answer.textContent, heard: el.heard.textContent,
  });
}

// Bring a half's deck in. True when it had cards to show.
function restoreDeck(branchId) {
  const saved = decks.get(branchId);
  history.length = 0; historyIndex = -1; currentStack = []; currentSet = null;
  // The other half's deck is not this half's screen: whatever was being patched into the one
  // we are leaving has nothing to do with the nodes we are about to put up.
  resetGlass();
  deckBranch = branchId;
  if (!saved || !saved.history.length) { clear(el.cards); renderStackChips(); return false; }
  for (const entry of saved.history) history.push(entry);
  historyIndex = Math.min(saved.index, history.length - 1);
  currentStack = saved.stack || [];
  currentSet = saved.set || null;
  el.answer.textContent = saved.answer || '';
  el.heard.textContent = saved.heard || '';
  showHistory(historyIndex);
  return true;
}
let attentionItems = [];

function entitiesOf(items) {
  const out = [];
  for (const item of items || []) {
    const d = item && item.data ? item.data : {};
    if (item.type === 'order' && d.order_id) out.push(String(d.order_id));
    if (item.type === 'customer' && d.customer_id) out.push(String(d.customer_id));
    if (item.type === 'email_thread' && d.thread_id) out.push(String(d.thread_id));
    if ((item.type === 'inventory' || item.type === 'product') && d.products && d.products[0] && d.products[0].product_id) {
      out.push(String(d.products[0].product_id));
    }
  }
  return out;
}

function pushContext(nodes, items, question, restoreTo) {
  history.push({ nodes, entities: entitiesOf(items), question: question || '' });
  while (history.length > MAX_HISTORY) history.shift();
  showHistory(history.length - 1, { scrollTo: restoreTo });
  renderRecent();
  armDeckExpiry();
  for (const node of nodes) collectPending(node);
  T.record('navigate', { nav: 'new', index: historyIndex, entities: history[historyIndex].entities });
  snapshotSoon({ fixture: typeof question === 'string' && question.startsWith('fixture:') ? question.slice(8) : undefined });
}

// The same, for a screen that is ALREADY DRAWN. `pushContext` clears the deck and appends —
// which is right for an answer that arrives whole, and is exactly the whole-page redraw §7
// forbids for one that arrived in pieces: it would throw away the nodes the patches built,
// reset the scroll and drop the keyboard, at the very end of the turn. So the history takes
// the nodes that are on the glass, and the glass is left alone.
function adoptContext(nodes, items, question) {
  history.push({ nodes, entities: entitiesOf(items), question: question || '' });
  while (history.length > MAX_HISTORY) history.shift();
  showHistory(history.length - 1, { keep: true });
  renderRecent();
  armDeckExpiry();
  for (const node of nodes) collectPending(node);
  T.record('navigate', { nav: 'patched', index: historyIndex, entities: history[historyIndex].entities });
  // No snapshot here. This runs from `renderTurn`, which takes one for the whole answer —
  // two snapshots of one screen is half of D-8's seven renders of one turn.
}

/* --------------------------------------------- what stays on the glass (round 12)
 *
 * George: "a task is asked, a screen is shown, an edit is asked, the edit succeeds, however the
 * screen disappears. This is a persistent issue." An answer whose only card was the change —
 * the note waiting for his tap, a refusal — or that answered in words was drawn as a screen of
 * its own, and the order he was working on went with the screen before it.
 *
 * The Mac now says when an answer continues the screen (app/screen.py): the cards it carried
 * over are marked, and web/ui.js `continueScreen` draws the answer onto the glass keeping every
 * node it can. What is decided here is only what the deck makes of that: it is the same stop
 * on the deck, not a new one, the owner is not thrown back to the top of it, and a card that
 * has just arrived — the one to tap — is brought into view if it is out of it. */

// The answer drawn onto the screen that is up, or null when it does not continue it (or the
// glass is not the screen the Mac thinks it is, and the answer must be drawn whole).
function continueDeck(items) {
  if (!window.CrooksUI || typeof window.CrooksUI.continueScreen !== 'function' || historyIndex < 0) return null;
  return window.CrooksUI.continueScreen(el.cards, items, renderOpts());
}

// The deck's own copy of a screen that carried on: this stop, as it now stands.
function carryContext(carried, items, question) {
  history[historyIndex] = { nodes: carried.nodes.slice(), entities: entitiesOf(items), question: question || '' };
  showHistory(historyIndex, { keep: true });
  renderRecent();
  armDeckExpiry();
  for (const node of carried.nodes) collectPending(node);
  if (carried.first) bringIntoView(carried.first);
  T.record('navigate', {
    nav: 'carried', index: historyIndex, entities: history[historyIndex].entities,
    kept: carried.kept || undefined, changed: carried.redrawn || undefined, added: carried.added || undefined,
    removed: carried.removed || undefined,
  });
}

// A card that has just arrived above where the owner is reading is scrolled to, the least
// distance that shows it; one already in view is left alone. Calm, and instant when he has
// asked for less motion.
function bringIntoView(node) {
  if (!node || typeof node.scrollIntoView !== 'function') return;
  const go = () => {
    try { node.scrollIntoView({ block: 'nearest', behavior: REDUCED.matches ? 'auto' : 'smooth' }); } catch { /* an old WebView: it is there when he scrolls */ }
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(go); else go();
}

// An answer to a tap, drawn: onto the screen when it carries it on, as a new stop otherwise.
function drawTapAnswer(items, words) {
  const carried = continueDeck(items);
  if (carried) { carryContext(carried, items, words); return true; }
  const rendered = window.CrooksUI.render(items, renderOpts());
  if (!rendered.nodes.length) return false;
  pushContext(rendered.nodes, items, words);
  return true;
}

/* ------------------------------------------- the workspace, as it arrives (§7, D-5)
 *
 * The Mac stages the screen in pieces now: a skeleton the moment it knows what kind of thing
 * is coming, each read's cards as that read lands, and the turn's own presentation reconciled
 * against what is already here (app/progressive.py). The patches ride back on the /state poll
 * this page was already making every 400 ms to say CHECKING SHOPIFY — no stream, no second
 * socket, nothing to keep alive on a tablet that sleeps.
 *
 * `turn_c8eb4cffe077` put nothing on the glass for 7,975 ms and the owner said the system
 * "waits and then dumps a large chunk". This is the other end of that.
 */
// `fresh`: a new turn has begun and nothing of it is on the glass yet — the last answer's
// screen is still the one up (round 12).
const glass = { turn: '', cursor: 0, applied: 0, stale: false, fresh: false };

// Rule: never move a control the owner is touching, and never take the keyboard or the
// microphone away mid-gesture. While any of these is true the whole batch waits — the cursor
// is not advanced, so the next poll offers the same patches again.
const deckPointers = new Set();
function deckHeld() {
  return deckPointers.size > 0 || recording || pendingStart || liveActionSurface();
}

function resetGlass() {
  glass.turn = '';
  glass.cursor = 0;
  glass.applied = 0;
  glass.stale = false;
  glass.fresh = false;
}

// A turn that never answered — the Mac asleep, the tailnet dropped, two minutes gone — leaves
// its skeletons standing. The live session's "Checking the inbox…" was still on the glass 34.8
// seconds after the asking had stopped, read as calm while a customer waited; a placeholder is
// removed the moment nothing is coming to fill it. The error line says what happened.
function settleGlass(why) {
  const shells = el.cards.querySelectorAll('[data-shell]');
  for (const node of shells) if (node.parentNode) node.parentNode.removeChild(node);
  if (shells.length) T.record('workspace_settled', { count: shells.length, name: why || '' });
  resetGlass();
  if (!el.cards.children.length && el.body.dataset.mode === 'context') setMode('orb');
}

// Apply what the Mac has staged. Returns true when anything was drawn.
// Something the owner can actually read has landed — a section of the workspace patched in
// while the turn is still running. Not a spinner and not a state word: this is the
// measurement the whole slice exists to move.
function noteUseful(why) {
  if (live && live.state !== 'IDLE') live.usefulResult(why);
}

function applyWorkspace(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (!window.CrooksUI || typeof window.CrooksUI.applyPatches !== 'function') return false;
  const turnId = String(payload.turn_id || '');
  if (turnId && glass.turn !== turnId) {
    // A new question. The last answer's screen stays up until this one has something of its
    // own to show (round 12): the glass used to be cleared at the first poll, so the order the
    // owner was editing vanished the moment he asked for the edit, and stayed gone while CLIVE
    // thought — and for good when the answer was only the card for the change.
    resetGlass();
    glass.turn = turnId;
    glass.fresh = true;
  }
  if (payload.gap) { glass.stale = true; return false; }
  const patches = Array.isArray(payload.patches) ? payload.patches : [];
  if (!patches.length) return false;
  if (glass.fresh) {
    // The first patches of this turn. New cards take the screen: the old one's nodes are
    // still in the history array, so Back still reaches it. Patches that only touch cards
    // already up are held — the cursor does not move, so they come again with whatever
    // follows — and the turn's own answer settles those cards (`renderTurn`).
    const landing = window.CrooksUI.landingOf ? window.CrooksUI.landingOf(el.cards, patches) : 'replace';
    // Held only while that screen is actually up: over the orb there is nothing to keep.
    if (landing === 'hold' && historyIndex >= 0 && el.body.dataset.mode === 'context') return false;
    // And never taken away from under a finger: the whole batch waits for the hand, as a
    // patch does (web/ui.js applyPatches, rule 2).
    if (deckHeld()) { T.record('workspace_deferred', { count: patches.length, name: recording ? 'recording' : 'gesture' }); return false; }
    clear(el.cards);
    glass.fresh = false;
  }
  const out = window.CrooksUI.applyPatches(el.cards, patches, { held: deckHeld, opts: renderOpts() });
  if (out.deferred) {
    T.record('workspace_deferred', { count: out.deferred, name: recording ? 'recording' : 'gesture' });
    return false;
  }
  glass.cursor = Math.max(glass.cursor, Number(payload.revision) || 0);
  const drawn = out.added + out.changed + out.visual + out.removed;
  if (!drawn) return false;
  glass.applied += drawn;
  noteUseful('workspace patch');
  // A working screen, from the first patch: the deck comes up rather than the orb sitting
  // there until the whole read graph has resolved.
  if (el.body.dataset.mode !== 'context') setMode('context');
  lightDock(Array.prototype.slice.call(el.cards.children));
  T.record('workspace_patch', {
    added: out.added || undefined, changed: out.changed || undefined, visual: out.visual || undefined,
    removed: out.removed || undefined, index: glass.cursor,
    detail: (payload.timings_ms && payload.timings_ms.time_to_first_actionable_surface) || undefined,
  });
  return true;
}

// The turn has answered. Its cards are reconciled against what the patches already drew
// rather than the page being rebuilt under the owner's finger — which is the whole of §7's
// "cards PATCH IN PLACE". Returns false when the glass and the payload disagree about what
// is on screen, and the caller then draws the answer the old way; a page that patched itself
// into a state the Mac does not recognise must redraw, not guess.
function adoptWorkspace(data) {
  const payload = data && data.workspace;
  if (!payload || glass.stale) return null;
  if (String(payload.turn_id || '') !== glass.turn || !glass.applied) return null;
  applyWorkspace(payload);
  const want = [];
  for (const item of data.ui || []) {
    if (!item || item.type === 'context_stack') continue;
    const id = window.CrooksUI.surfaceId(item);
    if (id) want.push(id);
  }
  const nodes = Array.prototype.slice.call(el.cards.children);
  const have = nodes.map((n) => (n.dataset ? n.dataset.render || '' : ''));
  for (const id of want) if (have.indexOf(id) === -1) return null;
  return nodes;
}

// The screen as structure, once it has been laid out: card types, tabs, the rail, sizes.
//
// D-8: `turn_f0628fcf7be5` recorded `order_list + working_set + folded` SEVEN times — #2
// through #7 at 0.0 s apart — and nine of the session's twenty-one long-scroll surfaces are
// that one turn. Six identical snapshots in one instant is a deck drawn, recorded, and drawn
// again: the answer's own draw, the adoption of the patches that had already drawn it, and a
// navigation landing on the screen it was already on. Each one cost the scroll position, and
// he was scrolling (26 reports, deepest 971 px).
//
// So a draw whose RESULT is the screen that is already there is not a render and is not
// counted as one. It is not swallowed either: `render_repeat` says it happened, with the
// count, so the timeline keeps the truth about how often the page redrew itself while the
// `render` events stay one-per-screen.
let deckPrint = '';
let deckRepeats = 0;
function screenPrint() {
  const cards = Array.prototype.slice.call(el.cards.children)
    .map((n) => `${(n.dataset && n.dataset.type) || ''}:${(n.dataset && n.dataset.render) || (n.dataset && n.dataset.ref) || ''}`);
  return `${currentTurnId}|${el.body.dataset.mode || ''}|${cards.join(',')}`;
}
function snapshotSoon(extra) {
  const take = () => {
    const print = screenPrint();
    if (print === deckPrint) {
      deckRepeats += 1;
      T.record('render_repeat', { count: deckRepeats, name: 'same_screen' });
      return;
    }
    deckPrint = print;
    deckRepeats = 0;
    T.record('render', T.snapshot(el.cards, extra));
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(take); else take();
}

/* ------------------------------------------------------- the rest of an order */

// An order card that is still waiting for the customer's history or the inbox asks the Mac
// for them once the card is up — GET /context/order, session-bound, no model in the loop —
// and fills the sections in place. A few tries, then the card stays as it is; the sections
// say "reading…" and nothing pretends to be known.
const CONTEXT_WAITS_MS = [300, 2500, 6000];
function collectPending(node, attempt = 0) {
  if (!node || !node.dataset || node.dataset.type !== 'order' || !node.dataset.pending || !node.dataset.ref) return;
  if (!window.CrooksUI || typeof window.CrooksUI.hydrateOrder !== 'function') return;
  const orderId = node.dataset.ref;
  // When the asking ends without an answer, the card says so. It used to stop asking and
  // leave "Checking the inbox…" standing — a failure drawn as work in progress, forever.
  const settle = (why) => {
    const regions = typeof window.CrooksUI.settleOrder === 'function' ? window.CrooksUI.settleOrder(node) : [];
    if (regions.length) T.record('context_unread', { order_id: orderId, detail: regions.join(' '), name: why });
  };
  if (attempt >= CONTEXT_WAITS_MS.length) { settle('gave_up'); return; }
  setTimeout(async () => {
    if (!node.dataset.pending || !node.isConnected && !history.some((entry) => entry.nodes.indexOf(node) !== -1)) return;
    try {
      const response = await fetch(`/context/order/${encodeURIComponent(orderId)}?session_id=${encodeURIComponent(sessionId)}`, { cache: 'no-store' });
      if (!response.ok) { T.record('context_failed', { order_id: orderId, status: response.status, index: attempt }); settle('refused'); return; }   // not this session's order any more, or the Mac cannot say
      const ext = await response.json();
      const still = window.CrooksUI.hydrateOrder(node, ext);
      T.record(still.length ? 'context_pending' : 'context_landed', { order_id: orderId, context_request_id: ext && ext.context_request_id, index: attempt, detail: still.length ? still.join(' ') : undefined });
      if (still.length) collectPending(node, attempt + 1);
    } catch { T.record('context_failed', { order_id: orderId, status: 0, index: attempt }); collectPending(node, attempt + 1); }
  }, CONTEXT_WAITS_MS[attempt]);
}

// The Mac forgets a conversation after half an hour of silence; the screen forgets with it.
// A customer's name and address do not stay on a desk-top tablet all night.
const DECK_IDLE_MS = 30 * 60 * 1000;
let deckExpiryTimer = null;
function armDeckExpiry() {
  clearTimeout(deckExpiryTimer);
  deckExpiryTimer = setTimeout(() => {
    if (busy || recording || speakingVia || liveActionSurface()) { armDeckExpiry(); return; }
    history.length = 0; historyIndex = -1; currentStack = []; currentSet = null; decks.clear();
    resetGlass();
    clear(el.cards); renderStackChips(); renderRecent();
    el.heard.textContent = ''; el.answer.textContent = '';
    setMode('orb');
  }, DECK_IDLE_MS);
}

// Is there anywhere BACK from here? The Mac's trail decides, and the local render cache
// stands in only when the Mac cannot be reached. Kept in one place because two writers set
// the Back chip — showHistory on every draw, noteBranch on every reply — and they used to
// disagree about what Back was for.
//
// What used to be here as well: `workflow && !workflow.at_start`. While a list was open the
// chip meant "the cursor can step back", so Back stepped the LIST and not the trail — one
// pair of buttons over two different cursors, which is what the owner was describing when he
// said the back button and the next button had both regressed. The list's own step back is
// its own chip now (#prev-btn), and Back is the trail's.
function canGoBack(index) {
  if (branchState && typeof branchState.can_back === 'boolean') return branchState.can_back;
  return typeof index === 'number' ? index > 0 : historyIndex > 0;
}

// Which area the screen is showing, from the card types on it — the Mac's description of
// the record, never the last thing tapped. A tap on Orders that lands on a list lights Orders;
// so does "show me today's orders" said out loud; so does Back arriving at that list.
const AREA_OF = {
  order: 'orders', order_list: 'orders', attention: 'orders',
  email_list: 'email', email_thread: 'email', email_draft: 'email', work_queue: 'email', email_queue: 'email',
  sales_summary: 'sales', metric_group: 'sales', trend: 'sales', comparison: 'sales',
  ranking: 'products', product: 'products', inventory: 'products', table: 'products', matrix: 'products',
};
function lightDock(nodes) {
  if (!el.dock) return;
  // The Mac says which of its places this workspace belongs to, and it is right about stops
  // the cards alone cannot describe — a landing that drew a ranking is still Products, and a
  // Back that lands on a list arrives with the area on it. The card types stand in when the
  // branch has not said.
  let area = (branchState && branchState.area) || '';
  if (!area) {
    for (const node of nodes || []) {
      const type = node && node.dataset ? node.dataset.type : '';
      if (AREA_OF[type]) { area = AREA_OF[type]; break; }
    }
  }
  for (const btn of el.dock.querySelectorAll('.dock-btn')) {
    btn.setAttribute('aria-pressed', btn.dataset.area === area ? 'true' : 'false');
  }
  el.body.dataset.area = area;
  // A service fault is the header's only while the owner is in the place it breaks.
  drawConn();
}

// `opts.keep` draws nothing: the nodes for this entry are already the deck's children,
// because they were patched in there as the reads landed (adoptContext). Everything else —
// which dock light is on, the two chips, the mode — is the same work either way, which is why
// it is one function and not two.
//
// `opts.scrollTo` is how far down the owner was when he left this stop. Back to a list three
// screens down is back to where he was IN it; the depth comes from the Mac's stop, not from
// the page, so it survives a reload and a branch switch.
function showHistory(index, opts) {
  if (index < 0 || index >= history.length) return;
  const keep = Boolean(opts && opts.keep);
  historyIndex = index;
  if (!keep) {
    clear(el.cards);
    for (const node of history[index].nodes) el.cards.appendChild(node);
  }
  lightDock(history[index].nodes);
  // A patch leaves the owner where he was reading. A redraw starts at the top, unless the
  // stop says how far down he was, in which case it goes back there (`surface.scroll` reports
  // the depth as the thumb moves).
  if (!keep) {
    const restoreTo = opts && typeof opts.scrollTo === 'number' ? opts.scrollTo : null;
    el.cards.scrollTop = 0;
    if (restoreTo !== null && restoreTo > 0) {
      const settle = () => { el.cards.scrollTop = restoreTo; scrollMax = restoreTo; };
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(settle); else settle();
    }
    scrollMax = restoreTo !== null ? Math.max(0, restoreTo) : 0;
  }
  el.deck.dataset.depth = String(Math.min(2, index));
  drawWalkChips(index);
  renderStackChips();
  setMode('context');
}

// Back, Previous and Next: three controls over two cursors, each drawn from the one the Mac
// says it belongs to. Back is the TRAIL (`can_back`); Previous and Next are the open LIST
// (`workflow`), and the two of them appear and disappear together.
//
// None of the three is a permanent strip (GENERATIVE_UI_V1 §4). They appear only while the
// owner is INSIDE something: a list (Previous and Next, and Back beside them) or a drill-down
// (Back, because there is somewhere to go back to). On a landing with neither, the row carries
// none of them.
//
// Inside a list, every chip keeps its slot for the whole walk and greys out at the ends rather
// than vanishing. Back used to be `hidden` at the start of a list, so the FIRST Next tap made it
// appear — and Next slid 68px (9.1mm) to the right, out from under the thumb that had just
// pressed it, onto the spot the 60px Back chip now occupied. Driven with real taps at one
// fixed point, tap one advanced the list and tap two at the identical point hit BACK. Walking
// a queue one-handed is a repeated press in one place; the control under that place must not
// change identity between presses — which is why Back is shown, greyed, for the whole of a
// list even where the trail has nowhere to go.
function drawWalkChips(index) {
  const workflow = branchState && branchState.workflow;
  const back = canGoBack(index);
  el.backBtn.hidden = !back && !workflow;
  el.backBtn.disabled = !back;
  if (el.prevBtn) {
    el.prevBtn.hidden = !workflow;
    el.prevBtn.disabled = Boolean(workflow && workflow.at_start);
  }
  if (el.nextBtn) {
    // Next belongs to the list, not to the history: it exists while a set is open, and greys
    // at the end of it. It used to hide itself on `at_end`, which shuffled the rail a third
    // time at exactly the moment the owner was tapping fastest.
    el.nextBtn.hidden = !workflow;
    el.nextBtn.disabled = Boolean(workflow && workflow.at_end);
  }
}

// Back is the Mac's to decide, not this page's.
//
// This used to walk a local array of already-rendered nodes and tell nobody. Saying "go back"
// moved the branch's own stack on the Mac; tapping Back moved this one. The two positions
// diverged the moment either was used, and never came back together — so "next" after a
// tapped Back walked from somewhere the owner was not looking at.
//
// So the tap asks the Mac, and the Mac answers with the record it landed on. The local
// history stays as a render cache and a fallback: if the request fails — the Mac asleep, the
// tailnet dropped — the screen still goes back, because a Back button that does nothing when
// the network hiccups is worse than one that is occasionally out of step.
//
// Back is the TRAIL, and only the trail. It was wired to `workflow.previous` whenever a list
// was open, which made one pair of buttons drive two cursors: Back stepped the list, Next
// stepped the list, and nothing on the glass returned to the screen the owner had come from.
// That is the pairing the owner reported as "the back button and the next button" having
// regressed, and it is why he could not get out of a queue he had walked into. The list's own
// step back is now its own chip (#prev-btn), which is also how `workflow.previous` keeps the
// caller it needs.
//
// What comes back is a WORKSPACE: the record or the list, the tab, the set, the cursor's
// place in it, and how far down it was (app/commands.py:_back). The scroll is applied here,
// because it is the one part of a workspace only the page can put back.
async function goBack() {
  T.record('navigate', { nav: 'back', from: historyIndex, to: historyIndex > 0 ? historyIndex - 1 : -1 });
  const landed = await semanticCommand('navigation.back');
  if (landed && landed.ok && Array.isArray(landed.ui) && landed.ui.length) {
    const rendered = window.CrooksUI.render(landed.ui, renderOpts());
    if (rendered.nodes.length) {
      const stop = (landed.changed || {}).workspace || {};
      pushContext(rendered.nodes, landed.ui, landed.answer || '', Number(stop.scroll) || 0);
      // Say where it landed. This used to write #answer only on the FAILURE branch, so a
      // successful Back left the previous turn's sentence standing over a different record —
      // measured reading "That is the last one." above member 1 of 3, twice in a row.
      if (landed.answer) el.answer.textContent = landed.answer;
      return;
    }
  }
  if (landed && landed.ok) {
    // The Mac answered, and answered that there is nowhere further back. Say so and STAY.
    // This used to fall through to the local walk below, which is worse than doing nothing:
    // `pushContext` appends, so a tapped Back had already grown the local stack, and
    // `historyIndex - 1` was therefore the card the owner had just navigated AWAY from. The
    // screen went forwards while the voice said there was nothing behind it.
    if (landed.answer) el.answer.textContent = landed.answer;
    return;
  }
  // Only now: the request itself failed — the Mac asleep, the tailnet dropped — and a Back
  // button that does nothing when the network hiccups is worse than one briefly out of step.
  if (historyIndex > 0) showHistory(historyIndex - 1);
  else goHome();
}

// The open list, one member at a time. The same two commands the words "next" and "previous"
// reach, so the cursor is one cursor: tapping and saying it alternate correctly rather than
// each keeping a count. Neither of them is Back — Back is the trail (`goBack`), and the
// position these two move is the set's.
async function stepSet(command, way) {
  const moved = await semanticCommand(command);
  if (!moved) return;
  if (moved.ok && Array.isArray(moved.ui) && moved.ui.length) {
    const rendered = window.CrooksUI.render(moved.ui, renderOpts());
    if (rendered.nodes.length) {
      pushContext(rendered.nodes, moved.ui, moved.answer || '');
      // `_member_words` (app/commands.py) already returns "Priya Raman. 1 of 3." and this
      // threw it away, passing it to pushContext as a history LABEL and writing #answer only
      // when the move failed. Measured: three successful Next taps, three different orders,
      // and one unchanged line reading "3 orders today; 2 still to go out." over all of them.
      if (moved.answer) el.answer.textContent = moved.answer;
      T.record('navigate', { nav: way, cursor: (moved.changed || {}).cursor, total: (moved.changed || {}).total });
      return;
    }
  }
  // At an end of the list, or nothing to draw: say what happened rather than going quiet.
  if (moved.answer) el.answer.textContent = moved.answer;
}

const goNext = () => stepSet('workflow.next', 'next');
const goPrevious = () => stepSet('workflow.previous', 'previous');

// Open a record the current screen linked to. The same command the words reach, so a tap on
// the third row and "open the third one" land in exactly the same place — and neither asks the
// model to work out which record was meant.
/* What to CALL the record a row names, for the Mac to print back at the owner.
   This was `(link.textContent || '').trim().slice(0, 60)` — every word on the row, in DOM
   order, with nothing between them, because adjacent spans have no separator in
   `textContent`. The label travels to `open.entity`, is stored as the entity's label, and is
   then printed on the half chip, in the band above the cards and on the trail. So a tap on
   an order row put this on the glass:

       #1927 Fionn Doherty28 Aug, 23:00£83.0…

   — the number, the name, the date and the money run together and then cut off at 40
   characters by `Branch.headline`. Four facts pretending to be a name.

   A row's NAME is its primary line. The renderers say which that is (`data-label` where the
   name is known; `.row-main` and its siblings otherwise), so nothing is guessed from a blob
   of text. And the fallback joins with a separator rather than concatenating, so even a
   shape this function has never seen cannot produce "Doherty28". */
function labelOf(node) {
  if (!node) return '';
  const said = String(node.dataset && node.dataset.label ? node.dataset.label : '').trim();
  if (said) return said.slice(0, 60);
  /* The primary line, in the vocabulary the renderers use for one — and ITS OWN, not a
     descendant's. `querySelector` here would search the whole subtree, so a tap that
     resolves to a card carrying both `data-ref` and `data-kind` would take the name off the
     first row inside it: a different record's name, on this record's chip. Nearest first,
     then the subtree, which is still bounded by `closest` having picked the nearest element
     that names a record at all. */
  const NAMES = '.row-main, .link-chip-label, .hist-main, .card-title, .sec-title';
  let main = null;
  for (const kid of (node.children || [])) {
    if (kid.matches && kid.matches(NAMES)) { main = kid; break; }
  }
  if (!main && node.querySelector) main = node.querySelector(NAMES);
  const first = main ? String(main.textContent || '').replace(/\s+/g, ' ').trim() : '';
  if (first) return first.slice(0, 60);
  // Nothing named itself. Join what is there with a separator, so the worst case is a label
  // that says too much rather than one that says a wrong word.
  const parts = [];
  for (const kid of (node.children || [])) {
    if (kid.getAttribute && kid.getAttribute('aria-hidden') === 'true') continue;
    const words = String(kid.textContent || '').replace(/\s+/g, ' ').trim();
    if (words) parts.push(words);
  }
  if (parts.length) return parts.join(' \u00b7 ').slice(0, 60);
  return String(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
}

async function openEntity(kind, ref, label) {
  if (!kind || !ref) return;
  T.record('navigate', { nav: 'open_entity', name: kind, entity: ref });
  haptic(HAPTIC.start);
  const opened = await semanticCommand('open.entity', { kind, ref, label });
  if (opened && opened.ok && Array.isArray(opened.ui) && opened.ui.length) {
    const rendered = window.CrooksUI.render(opened.ui, renderOpts());
    if (rendered.nodes.length) {
      pushContext(rendered.nodes, opened.ui, opened.answer || '');
      if (opened.answer) el.answer.textContent = opened.answer;
      return;
    }
  }
  // The Mac cannot open it. Say so — and where the refusal names somewhere to go instead,
  // put those on the glass as controls. `open.entity ok=False code=not_held` reached the owner
  // in the live session as one sentence with nothing under it, which is a dead control.
  if (opened && opened.answer) el.answer.textContent = opened.answer;
  else if (opened && opened.detail) el.answer.textContent = opened.detail;
  if (opened && opened.changed && Array.isArray(opened.changed.offer) && opened.changed.offer.length) {
    if (historyIndex >= 0) offerBeside(opened.answer || opened.detail || '', opened.changed);
    else drawEmptyHalf({ answer: opened.answer || opened.detail || '', changed: opened.changed });
  }
  // Handed back so the control that was tapped can settle ITSELF (§6, D-6): a chip that has
  // just been refused must stop being a live control, and must say why on itself.
  return opened || null;
}

// One semantic command, posted the way the tablet posts everything else: which command, and
// which record. Never what the command should do — the Mac decides that (app/commands.py).
async function semanticCommand(name, extra) {
  const form = new FormData();
  form.set('session_id', sessionId);
  form.set('command', name);
  if (branchState && branchState.branch_id) form.set('branch_id', branchState.branch_id);
  for (const key of Object.keys(extra || {})) {
    if (extra[key] !== undefined && extra[key] !== null) form.set(key, String(extra[key]));
  }
  try {
    const response = await fetch('/command', { method: 'POST', body: form, cache: 'no-store' });
    if (!response.ok && response.status >= 500) return null;
    const payload = await response.json();
    // The Mac answers every command with the branch as it now stands. Taking it here rather
    // than at each call site is the point: while only the /turn handler called noteBranch,
    // the page kept a second copy of the cursor and the tab that commands were already
    // correcting, and the Next button's visibility was decided from whatever the last SPOKEN
    // turn had said — so tapping through a list left Next showing at the end of it.
    if (payload && payload.branch) noteBranch(payload.branch);
    return payload;
  } catch {
    return null;   // offline: the caller falls back to what it can do locally
  }
}

// The Assistant chip: this half's LANDING workspace.
//
// It is not a move along the trail. While it was one it walked the branch to `nav[0]` and
// redrew whatever record was oldest — in the live session an email thread from nine minutes
// earlier, redrawn eight times in twenty-two seconds while the owner pressed the chip again
// because nothing useful was happening. The Mac now answers with the dock landing for the
// area this half is in (app/commands.py:_home), which is a place with a fixed shape: it
// cannot be a stale record, and it is the same screen every time it is pressed.
async function goHome() {
  T.record('navigate', { nav: 'home', from: historyIndex });
  const landed = await semanticCommand('navigation.home');
  if (landed && landed.ok && Array.isArray(landed.ui) && landed.ui.length) {
    const rendered = window.CrooksUI.render(landed.ui, renderOpts());
    if (rendered.nodes.length) {
      pushContext(rendered.nodes, landed.ui, landed.answer || '');
      if (landed.answer) el.answer.textContent = landed.answer;
      return;
    }
  }
  // The Mac is unreachable, or has no landing to draw: the orb screen, as before. A refusal
  // says why rather than leaving the owner to guess from a screen that changed on its own —
  // and it says SOMETHING even when the Mac sent no reason, which is how a message with no
  // words happens. The guard used to require `landed.detail`, so a refusal with an empty
  // detail changed the screen and explained nothing: one of the eleven, in the one place a
  // message was most owed.
  if (landed && landed.ok === false) {
    notify(String(landed.detail || '').trim() || 'There is nothing on this half to come back to.',
      { tone: 'warn', code: 'no_landing' });
  }
  setMode('orb');
  renderRecent();
}

// The orb screen keeps one quiet way back to what was last shown.
function renderRecent() {
  const entry = history[history.length - 1];
  if (!entry) { el.recent.hidden = true; return; }
  el.recent.hidden = false;
  el.recentLabel.textContent = entry.question && !entry.question.startsWith('fixture:')
    ? entry.question : 'Last context';
}

// The working set the conversation holds: a chip that stays in the nav while the owner
// opens an order and comes back, so "these" keeps its meaning on screen.
//
// It follows the BRANCH, not whatever card happened to be drawn. Reading it off a working_set
// card meant the chip only changed when one appeared — so asking "which customers need
// replying to?" after a list of orders left the chip reading "3 ORDERS · Orders" while the
// Mac's cursor had moved to three customers. The chip is the one thing on screen that says
// what "these" means, and it was naming the wrong set.
let currentSet = null;
function noteWorkingSet(workflow) {
  if (!workflow || !workflow.set_id) { currentSet = null; return; }
  if (currentSet && currentSet.set_id === workflow.set_id) return;
  currentSet = {
    set_id: String(workflow.set_id),
    label: String(workflow.label || ''),
    count: Number(workflow.total) || 0,
    kind: String(workflow.kind || ''),
  };
  T.record('working_set', { id: currentSet.set_id, count: currentSet.count, label: currentSet.label, name: currentSet.kind });
}
function setChip() {
  if (!currentSet) return null;
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'chip chip-set';
  chip.dataset.set = currentSet.set_id;
  chip.setAttribute('aria-pressed', 'false');
  // Where you are in the list, not just how long it is. Nothing on the tablet said "2 of 3":
  // the position lived in a sentence that was overwritten by the next turn, so walking a
  // queue was walking blind — there was no way to tell the third order from the end of it,
  // or to know whether a tap you half-saw had registered. The numbers are already on the
  // branch (`Workflow.position` / `.total`, app/session/branch.py:61), and they change on
  // every step, so they are read live rather than off `currentSet`, which caches identity.
  const workflow = branchState && branchState.workflow;
  const at = workflow && workflow.set_id === currentSet.set_id ? Number(workflow.position) || 0 : 0;
  const kind = document.createElement('span'); kind.className = 'chip-kind';
  // The kicker counts; the label names. It used to read "3 ORDERS" beside a label already
  // reading "Orders", which spent rail width saying one word twice.
  kind.textContent = at > 0 ? `${at} of ${currentSet.count}` : `${currentSet.count}`;
  const label = document.createElement('span'); label.className = 'chip-label'; label.textContent = currentSet.label || currentSet.kind;
  chip.appendChild(kind); chip.appendChild(label);
  chip.addEventListener('click', () => {
    T.record('navigate', { nav: 'set_chip', id: currentSet ? currentSet.set_id : '' });
    for (let i = history.length - 1; i >= 0; i--) {
      if (history[i].nodes.some((n) => n.dataset && n.dataset.set === (currentSet ? currentSet.set_id : ''))) { showHistory(i); haptic(HAPTIC.start); return; }
    }
  });
  return chip;
}

function renderStackChips() {
  clear(el.stack);
  const set = setChip();
  if (set) el.stack.appendChild(set);
  if (!window.CrooksUI || !currentStack.length) return;
  const active = history[historyIndex] ? history[historyIndex].entities : [];
  const chips = window.CrooksUI.renderStack(currentStack, {
    active: active.find((ref) => currentStack.some((e) => e.ref === ref)) || '',
    onSelect: (entry) => {
      // Bring the most recent cards for that entity forward, if we still hold them: that is
      // instant and needs nobody.
      for (let i = history.length - 1; i >= 0; i--) {
        if (history[i].entities.indexOf(entry.ref) !== -1) { T.record('navigate', { nav: 'stack_chip', entity: entry.ref, to: i }); showHistory(i); haptic(HAPTIC.start); return; }
      }
      // Otherwise ask the Mac. This used to be a dead end — the chip was greyed out and the
      // tap recorded as 'dead_chip' — because liveness was decided from the TABLET's render
      // history. So the CUSTOMER chip was disabled on the very first turn, when it is the
      // only link on screen, and after four orders every customer chip in the bar was dead.
      // The Mac can read a record it does not hold; the tablet is not the one to say no.
      openEntity(entry.kind, entry.ref, entry.label);
    },
  });
  for (const chip of chips) el.stack.appendChild(chip);
  // The rail's far edge fades only when there is more beyond it. Measured after layout.
  if (el.nav) {
    const mark = () => { el.nav.dataset.overflow = el.nav.scrollWidth > el.nav.clientWidth + 1 ? '1' : ''; };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(mark); else mark();
  }
}

function renderAttentionSurface() {
  if (!attentionItems.length) { el.attention.hidden = true; return; }
  el.attention.hidden = false;
  el.attentionCount.textContent = String(attentionItems.length);
  el.attentionText.textContent = attentionItems.length === 1 ? 'Requires attention' : 'Require attention';
}

// The answer to a turn: cards first, then the mode they need.
function renderTurn(data) {
  // An answer that continues the screen that is up (the Mac marked what it carried over) is
  // drawn onto it, keeping every card it can — round 12, "the screen disappears". Anything
  // else is drawn whole, as it always was.
  const carried = continueDeck(data.ui);
  const ui = carried || (window.CrooksUI ? window.CrooksUI.render(data.ui, renderOpts()) : { nodes: [], skipped: [], stack: null, errors: [], hasContext: false });
  // Round 9, the screens remote: CLIVE's screen_remote card (his answer when the owner asks for a
  // remote) opens the remote for its screen over the app (web/remote.js). The card is drawn as usual.
  if (window.CliveRemote) window.CliveRemote.fromTurn(data.ui);
  if (ui.skipped.length) console.warn('[crooks] skipped ui items:', ui.skipped.join(', '));
  el.errline.textContent = '';
  lastErrorTitle = '';
  if (ui.errors.length) {
    lastErrorTitle = ui.errors[0].title || 'Something went wrong';
    el.errline.textContent = ui.errors[0].recovery || '';
  }
  if (ui.stack) currentStack = ui.stack;
  // The attention surface shows only what this turn returned; a count from this morning
  // must not sit on the screen at four o'clock as if it were still true.
  const attention = (data.ui || []).filter((i) => i && i.type === 'attention' && i.data && Array.isArray(i.data.items));
  attentionItems = attention.length ? attention[0].data.items : [];
  renderAttentionSurface();

  // A composer the Mac drew but has not written the words of yet asks for them (compose
  // block, end of this file). Deferred inside, because this turn is still in flight.
  const answer = data.answer || '';
  const renderInfo = { skipped: ui.skipped.length ? ui.skipped : undefined, errors: ui.errors.length ? ui.errors.map((e) => e.title || 'error') : undefined, attention: attentionItems.length || undefined, answer_chars: answer.length };
  if (carried) {
    if (answer.length > 200 && window.CrooksUI) {
      // Too long to read in the band above the cards: it gets a card of its own, on top of the
      // screen it is about rather than instead of it.
      const said = window.CrooksUI.renderItem({ type: 'assistant', data: { text: answer } });
      if (said) { el.cards.insertBefore(said, el.cards.firstChild); carried.nodes.unshift(said); carried.first = said; }
    }
    carryContext(carried, data.ui, data.question);
    snapshotSoon(Object.assign({ kept: true }, renderInfo));
    return;
  }
  if (ui.hasContext && onlyLiveCardsAlreadyShown(data.ui)) {
    // The Mac re-presented a card that is already live on this screen (a spoken yes): the
    // deck stays as it is, the order beside it included — but it is brought back into view,
    // because the answer is about a card the owner may have left behind.
    setMode('context');
    snapshotSoon(Object.assign({ kept: true }, renderInfo));
    return;
  }
  // The cards arrived in pieces while the reads landed, and they are on the glass already:
  // the answer reconciles against them instead of the page being rebuilt at the end of the
  // turn (§7 — cards patch in place; do not redraw the whole page for an enrichment). When
  // the glass and the payload disagree about what is on screen, this returns nothing and the
  // ordinary path below redraws, because a page in a state the Mac does not recognise must
  // redraw rather than guess.
  const patched = ui.hasContext ? adoptWorkspace(data) : null;
  if (patched) {
    adoptContext(patched, data.ui, data.question);
    snapshotSoon(Object.assign({ patched: true }, renderInfo));
    return;
  }
  if (ui.hasContext) {
    pushContext(ui.nodes, data.ui, data.question);
  } else if (answer.length > 200 && window.CrooksUI) {
    // Too long to read beneath the orb: give it a card and the room that comes with one.
    const node = window.CrooksUI.renderItem({ type: 'assistant', data: { text: answer } });
    if (node) pushContext([node].concat(ui.nodes), [], data.question);
    else setMode('orb');
  } else {
    setMode('orb');
    snapshotSoon(renderInfo);
  }
}

/* ----------------------------------------------------------------- actions */

// The owner tapped a proposal. Send its id — and only its id — to the Mac, which executes
// what it stored when the proposal was staged, proves it, and answers with what to show.
// Never sent twice: if the connection drops mid-tap the tablet asks what happened instead.
const ACTION_TIMEOUT_MS = 30000;   // a precondition read, the change, a verifying read
// A batch is that, member by member, a few at a time: the Mac's own budget for a run is
// ninety seconds, and the tablet waits for all of it rather than guessing at the count.
const BATCH_TIMEOUT_MS = 120000;

// A tap counts only when the voice interaction is quiet. Holding to speak wins.
function actionBlocked() {
  return recording || pendingStart || busy;
}

// An undo offer the owner never took up. Its surface has just lapsed here; the Mac is told,
// so its copy stops being something that could still be waiting on him. It is a dismissal of
// an OFFER — nothing is applied, nothing else is withdrawn, and the Mac refuses anything
// that is not an undo.
function dismissUndo(proposalId) {
  if (!proposalId || !sessionId) return;
  const form = new FormData();
  form.append('session_id', sessionId);
  fetch(`/actions/${encodeURIComponent(proposalId)}/dismiss`, { method: 'POST', body: form, cache: 'no-store' })
    .then(() => T.record('undo_dismissed', { proposal_id: proposalId, reason: 'expired' }))
    .catch(() => { /* the Mac's own clock expires it too */ });
}

function renderOpts() {
  return {
    onCommit: commitAction, onArm: armAction, blocked: actionBlocked, onAction: primeAction,
    onUndoExpire: dismissUndo,
    // Which tab a card opens on, and where a change of tab is reported. Per RECORD, never per
    // branch: `tab: branchState.tab` was here, one value handed to every card with tabs, and
    // it is D-2 — one tap on Email put twenty-three later cards on Email, for records the
    // owner had never opened. The renderer decides per card (web/ui.js `tabFor`); this hands
    // it the place the answer is kept, and the Mac's copy is `branch.tabs`.
    tabOf: tabOfCard,
    onTab: noteTab,
    // A button beside a row. The tablet posts which action and which row and nothing else.
    onRowAction: rowAction,
    // A proven archive moved a thread out of the inbox. `renderSuccess` settles the deck that
    // is on screen; this settles the screens the owner will come BACK to, which the page
    // holds as detached nodes and nothing in the document can reach.
    onThreadMoved: threadMoved,
  };
}

// One proven change to where a thread LIVES, applied to every screen this page is holding.
// The Mac names the thread on the success card (app/presentation.py:_inbox_change) and
// web/ui.js:settleThread does the marking; all this adds is the back stack, because the queue
// the owner archived from is usually one Back away and would otherwise still list it.
function threadMoved(moved) {
  if (!window.CrooksUI || typeof window.CrooksUI.settleThread !== 'function') return;
  for (const entry of history) {
    for (const node of (entry && entry.nodes) || []) {
      if (node && node.nodeType === 1) window.CrooksUI.settleThread(node, moved);
    }
  }
}

// ------------------------------------------------------- where the branch is

// The halves of this conversation, as the Mac last listed them. The page draws them; it
// does not decide what they are, and it never keeps a branch the Mac has closed.
let branches = [];
let focusedBranch = '';

// Semantic states only. A background half says what it is doing in a word — the brief is
// explicit that there are no fake percentages, because nothing here can compute one.
const TASK_WORDS = { queued: 'queued', working: 'working', waiting: 'waiting', ready: 'ready', failed: 'failed' };

function applyBranches(shape) {
  if (!shape || typeof shape !== 'object' || !Array.isArray(shape.branches)) return;
  branches = shape.branches;
  focusedBranch = String(shape.focused || '');
  const one = branches.find((b) => b.branch_id === focusedBranch);
  if (one) branchState = one;
  // The deck follows the focus. A half that has gone (merged, closed) takes its deck with it.
  for (const id of Array.from(decks.keys())) if (!branches.some((b) => b.branch_id === id)) decks.delete(id);
  if (focusedBranch && deckBranch !== focusedBranch) {
    if (deckBranch && branches.some((b) => b.branch_id === deckBranch)) stashDeck();
    restoreDeck(focusedBranch);
  }
  drawBranchBar();
  // Whose messages these are. A message about the other half stays where it is and stops
  // being drawn, which is the fix for the merge line that landed over the wrong workspace.
  if (window.CrooksNotify) window.CrooksNotify.focusBranch(focusedBranch);
  const split = branches.length > 1 ? 1 : 0;
  const which = branches.length > 1 && branches[1] && branches[1].branch_id === focusedBranch ? 1 : 0;
  if (orb && typeof orb.setSplit === 'function') orb.setSplit(split, which);
  // What `busy` means changed with the focus: this half's turn, not the other's.
  syncBusy();
  T.record('branches', { count: branches.length, id: focusedBranch });
}

/* The word the GLASS says for the Mac's own area token. ORDERS, INBOX, SALES and PRODUCTS are
   the shop's own words and pass through untouched. EMPTY and WORKSPACE are not words: they are
   database states that reached the glass, and the Phase 5 visual pass caught a chip reading
   "EMPTY To go out" — a control saying at once that it holds nothing and that it is about its
   parent's working set. The Mac keeps its tokens (they are what `branch.headline` is asserted
   on); the chip says something a person would say. */
const AREA_WORDS = { EMPTY: 'NOTHING YET', WORKSPACE: 'THIS HALF' };

/* Is there anything on that half worth folding back into this one? Every field here is one
   the Mac sends with the branch; none of it is inferred from the screen.

   WHY THIS DECIDES WHETHER MERGE IS DRAWN, and why the first answer written here was wrong.
   The first version of this said a Merge over an empty half is §18 fake UI — "a control that
   cannot succeed". That is false, and the live session says so in its own record:
   `merge_close_tap.observed.merge_status: 200`, on a half whose `cards` array was empty.
   `POST /branches/{id}/merge` folds an empty half back perfectly well; it returns a summary
   with nothing in it, which is the truth. So §18 is not the reason.

   The reason is §25 and §26. Divided, the owner has at most two distinct outcomes: stop
   having two halves AND KEEP what the other one found (Merge), or stop having two halves and
   LET IT GO (Close). When the other half holds nothing those are not two outcomes, they are
   one — there is nothing to keep or let go of — and §25 says a control that does not earn
   its space comes off the glass. §26 says which of the two words survives: "Merge" over a
   half with nothing in it describes a fold that does not happen, and "Close" is simply true.

   That is also F's §25 finding answered where it belongs. The gate measured Merge at x=590
   and Close at x=664 on a 601 px screen — a 571 px strip carrying 807 px of controls, two of
   them off the glass. §25's answer to a strip that does not fit is to remove a control, not
   to shrink four, and this is the control that had nothing to do on the screen where the
   strip was worst: the idle divided one.

   So the rule is COUNT THE OUTCOMES, and the gate asserts it in that form
   (`undivide_controls` in scripts/browser/replay.js): one control per distinct outcome, each
   one hit-testable. Which means this function must never make Merge disappear from a half
   that holds something — that would be the opposite defect, and the merge_close_tap replay
   is the fixture that would catch it. */
function holdsSomething(half) {
  if (!half || typeof half !== 'object') return false;
  if (String(half.state || '').toUpperCase() === 'READY') return true;          // work that finished
  return Boolean(half.has_workspace || half.entity || half.set_id
    || half.building || half.compose || half.workflow);
}

/* One half, as §17 asks for it: which half it is, what it is about, what it is DOING, and
   whether it holds a workspace at all. Four facts, all four from the Mac. */
function branchChip(half, index) {
  const head = half.headline && typeof half.headline === 'object' ? half.headline : {};
  const state = String(half.state || '').toLowerCase();
  const word = TASK_WORDS[state] || (half.status === 'BACKGROUND' ? 'aside' : '');
  const token = String(head.area || half.label || (index === 0 ? 'FIRST' : 'SECOND'));
  const area = AREA_WORDS[token.toUpperCase()] || token;
  // A half the Mac describes with a STATE rather than a place holds nothing identifiable, and
  // a half that holds nothing must not also carry a task label. The visual pass caught the
  // chip saying both: "EMPTY To go out" — it holds nothing, AND it is about its parent's
  // working set. A fork inherits its parent's set and trail (app/session/branch.py:fork_from,
  // deliberately) so `headline.detail` falls back to that set's label; that is the right
  // answer for a half that is working on it, and no answer at all for one that is not.
  const bare = Object.prototype.hasOwnProperty.call(AREA_WORDS, token.toUpperCase());
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = `branch-chip${state === 'ready' ? ' is-ready' : ''}${state === 'failed' ? ' is-failed' : ''}`;
  chip.setAttribute('aria-pressed', half.branch_id === focusedBranch ? 'true' : 'false');
  // WHICH half, before anything else. The Phase 3 session recorded six taps between two halves
  // in nine seconds looking for the difference; "HALF 1" is the difference that never depends
  // on what either half happens to hold.
  const which = document.createElement('span');
  which.className = 'branch-which';
  which.textContent = `HALF ${index + 1}`;
  chip.appendChild(which);
  const name = document.createElement('span');
  name.className = 'branch-area';
  name.textContent = area;
  chip.appendChild(name);
  // The task, and only when it is a task rather than the state said twice, or the identity
  // said twice — "NOTHING YET · nothing yet" is the same contradiction in the other order.
  const detail = String(head.detail || '');
  const says = detail.toLowerCase();
  if (!bare && detail && says !== state && says !== area.toLowerCase() && says !== 'nothing yet') {
    const what = document.createElement('span');
    what.className = 'branch-detail';
    what.textContent = detail;
    chip.appendChild(what);
  }
  if (word) {
    const doing = document.createElement('span');
    doing.className = 'branch-state';
    doing.textContent = word;
    chip.appendChild(doing);
  }
  // Whether there is a SCREEN on that half, which is a different question from what it is
  // DOING, and the one the owner was asking when he tapped a half and saw nothing. Not said
  // when the identity line is already saying it: "NOTHING YET / no screen yet" is the
  // contradiction this chip exists to have stopped making, in the other direction.
  if (!half.has_workspace && !bare) {
    const nothing = document.createElement('span');
    nothing.className = 'branch-bare';
    nothing.textContent = 'no screen yet';
    chip.appendChild(nothing);
  }
  chip.dataset.branch = half.branch_id;
  chip.dataset.head = head.title || '';
  chip.setAttribute('aria-label',
    `Half ${index + 1} of 2, ${head.title || area}${word ? `, ${word}` : ''}${half.has_workspace ? '' : ', nothing on it yet'}`);
  chip.addEventListener('click', () => focusBranch(half.branch_id));
  return chip;
}

/* Merge and Close, each with its destination RESOLVED BEFORE IT IS DRAWN (§6). The id is
   closed over here, not looked up in a click handler — a control whose target is worked out
   when the thumb lands is a control that can silently do nothing, which is what
   `branchCommand(undefined, 'merge')` did: it returned on its first line. */
function branchAct(label, verb, branchId, why) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'branch-act';
  button.dataset.action = verb;
  button.dataset.branch = branchId;
  button.textContent = label;
  button.setAttribute('aria-label', why);
  button.title = why;
  button.addEventListener('click', () => branchCommand(branchId, verb));
  return button;
}

/* The halves, named, and the way in. TWO HOMES, and which is which is the whole of the rule:
 *
 *   THE HALVES — both chips, Merge and Close — are ALWAYS in the branch band of `.app`
 *   (`#branch-zone`), in both modes. That is D-1's fix: the band is a row of `.app`, outside
 *   the stage `#talk` is positioned in, so the voice target cannot reach it and the chips need
 *   no z-index argument to be pressable.
 *
 *   THE INVITATION — one Split chip, while there is one half — is in the band on the idle
 *   screen, where there is room to say what it is for, and in the navigation rail beside Back
 *   and Next when cards are up.
 *
 * Two defects set that division, and it is the only shape that answers both. Drawing the
 * HALVES into the nav rail made it six heterogeneous controls wide — a landing, a trail step,
 * a list step, a set cursor and two branch chips — which at 601 CSS px RAN OFF THE RIGHT EDGE
 * and cut the second half's chip in half. (The collision gate cannot see that: it looks for
 * overlapping rectangles, not for a flex row whose last child is clipped by its own
 * container.) And holding the band open in context mode for the ONE chip cost the first
 * viewport 54px, which took three density fixtures past the screen-and-a-quarter ceiling
 * (tests/test_density.py) — a zone is not free, and this one is worth its space when there are
 * two halves in it and not when there is one chip.
 *
 * With one half there is always a chip, wherever it is: the feature must not depend on a
 * secret gesture.
 */
function drawBranchBar() {
  const inRail = branches.length < 2 && el.body.dataset.mode === 'context' && el.branchRail;
  const host = inRail ? el.branchRail : el.branchBar;
  if (!host) return;
  for (const other of [el.branchBar, el.branchRail]) {
    if (other && other !== host) { clear(other); other.hidden = true; }
  }
  clear(host);

  // V0.5 retires user-facing Split. Concurrency remains an internal capability, but the
  // owner no longer has to allocate CLIVE's attention by manufacturing "halves". Existing
  // two-branch sessions are still rendered below so an in-flight legacy session is not
  // stranded; a single normal session exposes no Split invitation or branch chrome.
  if (branches.length < 2) {
    host.hidden = true;
    if (el.branchZone) el.branchZone.hidden = true;
    drawBranchHead();
    return;
  }

  host.hidden = false;
  if (el.branchZone) el.branchZone.hidden = false;
  // Two halves, divided visibly: a column each, a rule between them, and neither column able
  // to push the other off the screen (`minmax(0,1fr)` in the stylesheet).
  const halves = document.createElement('div');
  halves.className = 'branch-halves';
  branches.forEach((half, index) => {
    if (index) {
      const rule = document.createElement('span');
      rule.className = 'branch-divide';
      rule.setAttribute('aria-hidden', 'true');
      halves.appendChild(rule);
    }
    halves.appendChild(branchChip(half, index));
  });
  host.appendChild(halves);

  const other = branches.find((b) => b.branch_id !== focusedBranch) || null;
  const otherId = other && other.branch_id ? other.branch_id : '';
  const acts = document.createElement('div');
  acts.className = 'branch-acts';
  if (otherId) {
    const name = ((other.headline || {}).area) || other.label || 'the other half';
    // One control per distinct outcome (§25/§26 — the reasoning is above `holdsSomething`).
    // Keep what the other half found, or let it go: two acts while it holds something, one
    // act when it does not, and the word that is true either way is the one that is drawn.
    if (holdsSomething(other)) {
      acts.appendChild(branchAct('Merge', 'merge', otherId, `Fold ${name} back into this half`));
    }
    acts.appendChild(branchAct('Close', 'cancel', otherId, `Let ${name} go`));
  }
  if (acts.childNodes.length) host.appendChild(acts);
  drawBranchHead();
}

// The line on the screen itself, above the cards: which half this is, and what it is doing.
// The chips say it too, but they sit in a rail of eight other controls, and the owner's
// question was about the SCREEN — two of them looked the same. Drawn only when the orb is
// divided: with one half there is nothing to tell apart.
function drawBranchHead() {
  const node = el.branchHead;
  if (!node) return;
  const half = branches.find((b) => b.branch_id === focusedBranch) || branchState;
  const head = half && half.headline && typeof half.headline === 'object' ? half.headline : null;
  if (branches.length < 2 || !head) { node.textContent = ''; node.hidden = true; node.dataset.state = ''; return; }
  clear(node);
  /* The band says what the chip says, in the same words, from the same place. The Mac sends
     `headline.words` for exactly this (app/session/branch.py SAID_ALOUD); AREA_WORDS below
     is the fallback for a Mac older than this tablet build, and the two tables are held
     equal by a test so they cannot drift.

     A token that is a STATE rather than a place becomes one sentence and NO detail. This
     band was drawing "EMPTY Orders" over a focused empty half — a line saying at once that
     the half holds nothing and that it is about its parent's working set, which is the
     §26 repetition and the §18 contradiction in six words. (A fork inherits its parent's
     set and trail by design, app/session/branch.py fork_from, so `detail` falls back to
     that set's label: the right answer for a half working on it, and no answer at all for
     one that is not.) `.head-area` is uppercased by the stylesheet, so the Mac's sentence
     case and this fallback's capitals render the same. */
  const token = String(head.area || '');
  const bare = Object.prototype.hasOwnProperty.call(AREA_WORDS, token.toUpperCase());
  const area = document.createElement('span');
  area.className = 'head-area';
  area.textContent = bare ? (head.words || AREA_WORDS[token.toUpperCase()]) : token;
  node.appendChild(area);
  if (head.detail && !bare) {
    const detail = document.createElement('span');
    detail.className = 'head-detail';
    detail.textContent = head.detail;
    node.appendChild(detail);
  }
  const which = branches.findIndex((b) => b.branch_id === focusedBranch);
  const side = document.createElement('span');
  side.className = 'head-which';
  side.textContent = which === 0 ? 'half 1 of 2' : 'half 2 of 2';
  node.appendChild(side);
  node.dataset.state = String(head.state || '').toLowerCase();
  node.hidden = false;
}

/* One way out of a half, as a control that either WORKS or SAYS WHY IT CANNOT. §6/D-6:
 * `turn_dd093f86b92d` posted `open.entity`, was refused `not_held`, and the half then drew
 * `half_empty` — the control had been offered before its destination was known to exist, and
 * pressing it produced a screen that said the half was empty. §18 puts it plainly: a control
 * is drawn when its destination is resolved, or drawn disabled with the reason on it.
 *
 * Two halves, because there are two ways a destination can fail to be there:
 *
 *   BEFORE the tap   the offer carries no destination at all — an `open.entity` with no kind
 *                    or no ref, an `open.area` with no area. Drawn disabled, saying so, rather
 *                    than drawn live over nothing.
 *   AFTER the tap    the Mac refuses. The chip is disabled THEN, with the Mac's own reason
 *                    beside it, so the owner is not left pressing a control that has already
 *                    told him no once. The refusal's own ways forward are drawn by
 *                    `openEntity` as usual; this is about the control he touched.
 */
function offerChip(item) {
  const command = String((item && item.command) || '');
  /* The same shape the renderer draws a rail chip in (web/ui.js): a `.rail-label`, `is-off`
     and `aria-disabled` when it cannot be used, and the reason in `.rail-why` beside the
     label. The collision suite's "every control either works, or says why it cannot" sweep
     reads exactly that, so an offer drawn here is held to the rule one drawn there is. */
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.offer = command;
  const label = document.createElement('span');
  label.className = 'rail-label';
  label.textContent = String((item && item.words) || '—').slice(0, 40);
  button.appendChild(label);
  const why = (reason) => {
    const said = document.createElement('span');
    said.className = 'rail-why';
    said.textContent = reason;
    button.appendChild(said);
    button.title = reason.slice(0, 120);
  };
  const missing = command === 'open.entity' ? (!item.kind || !item.ref)
    : command === 'open.area' ? !item.area
      : true;
  if (missing) {
    button.className = 'rail-chip is-off';
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');
    why(command === 'open.entity' ? 'the server did not say which record'
      : command === 'open.area' ? 'the server did not say which place'
        : 'this build does not know that command');
    return button;
  }
  button.className = 'rail-chip';
  button.setAttribute('aria-disabled', 'false');
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    const answered = command === 'open.entity'
      ? await openEntity(item.kind, item.ref, item.label)
      : await openArea(item.area, '');
    if (answered && answered.ok !== false) return;
    // Refused. It stops being a control, and it says why where the eye already is.
    button.classList.add('is-off');
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');
    const said = String((answered && (answered.answer || answered.detail)) || 'The server would not open that.');
    // The reason goes ON the control and nowhere else. There was a `notifyControl(said,
    // button)` here as well, and F's notification policy caught it twice over: it carried no
    // `code`, so two identical refusals could not be deduped, and §10 forbids it outright
    // either way — `why()` has just written the sentence into the button and put it in the
    // title, and the button is visibly disabled. A floating message beside a control that
    // already says why is the second, worse claim on one event, which is the whole of
    // web/notify.js's CONTROL_SHOWS.
    why(said.slice(0, 60));
  });
  return button;
}

// A way forward, as the Mac named it: what this half holds, said in a line, and each thing
// that can be done from here as a control. The Mac decides the words and the commands
// (`app/commands.py:offer_for`); this only draws them. The alternative the owner met was a
// blank screen under one chip and a line of toast that had gone by the time he looked up.
function wayForward(words, changed) {
  const head = (changed && changed.headline) || {};
  const offer = changed && Array.isArray(changed.offer) ? changed.offer.slice(0, 5) : [];
  const panel = document.createElement('section');
  panel.className = 'card half-empty';
  panel.dataset.type = 'half_empty';
  const kicker = document.createElement('p');
  kicker.className = 'card-kicker';
  kicker.textContent = head.title || 'Nothing here';
  panel.appendChild(kicker);
  const said = document.createElement('p');
  said.className = 'card-body';
  said.textContent = String(words || 'This half holds nothing yet.');
  panel.appendChild(said);
  if (offer.length) {
    const rail = document.createElement('div');
    rail.className = 'rail';
    for (const item of offer) rail.appendChild(offerChip(item));
    panel.appendChild(rail);
  }
  return panel;
}

// A half with nothing on it, drawn as a half with nothing on it. The cards are replaced,
// because there are none of this half's to keep.
function drawEmptyHalf(shown) {
  const changed = (shown && shown.changed) || {};
  clear(el.cards);
  el.cards.appendChild(wayForward(shown && shown.answer, changed));
  renderStackChips();
  setMode('context');
  drawBranchHead();
  T.record('render', { name: 'half_empty', items: ['half_empty'], id: changed.branch_id });
}

// A refusal on a screen that already has cards on it. The way forward goes UNDER them: the
// list the owner was looking at when he tapped is not his fault and is not taken away.
function offerBeside(words, changed) {
  for (const stale of document.querySelectorAll('#cards .half-empty')) stale.remove();
  el.cards.appendChild(wayForward(words, changed));
  T.record('render', { name: 'offer_beside', items: ['half_empty'] });
}

// Tapping a half is switching workspaces (§3D of the Phase 3 brief). Focusing it on the Mac
// is half of that; the other half is drawing what THAT branch is looking at, which the Mac
// holds per branch and hands back through `branch.show`.
async function focusBranch(branchId) {
  if (!branchId || branchId === focusedBranch) return;
  const before = screenFingerprint();
  const data = await branchCommand(branchId, 'focus');   // applyBranches swaps the decks
  if (!data) return;
  haptic(HAPTIC.start);
  // `applyBranches` has already swapped this half's deck in, so its own cards are on the
  // glass when the tablet still holds them; when it does not, the Mac's copy of that half's
  // screen is asked for — and a half that holds nothing draws THAT, rather than leaving the
  // other half's cards standing under a different chip.
  const drawn = historyIndex >= 0 || await showBranchWorkspace(branchId);
  if (!drawn) {
    clear(el.cards);
    renderStackChips();
    el.answer.textContent = '';
    el.heard.textContent = '';
    setMode('orb');
    // Not "this half is empty" — a half that holds nothing draws its own screen above
    // (showBranchWorkspace, from the Mac's own words and its offer of ways out). Reaching
    // here means the Mac did not answer for it at all.
    notify('That half could not be read from the server.', { tone: 'bad', code: 'half_unreachable', branch: branchId });
  }
  drawBranchHead();
  // Whether the SCREEN changed, not whether the focus did. A tap that moved the focus and
  // left the glass identical is a defect, and this is the line that makes it visible in the
  // timeline rather than only on the owner's face: the report could say no more than "focus
  // changed with nothing redrawn", four times, without being able to say what the screen was.
  T.record('branch_switch', {
    id: branchId, name: screenFingerprint() === before ? 'same_screen' : 'redrawn',
    detail: (data.branches || []).map((b) => (b.headline || {}).title || '').join(' | ').slice(0, 120),
  });
}

// What is on the glass, in one short string: the header, and the cards in order with what
// each is about. Compared before and after a switch, and never shown to anybody.
function screenFingerprint() {
  const cards = Array.from(document.querySelectorAll('#cards .card'))
    .map((c) => `${c.dataset.type || ''}:${c.dataset.ref || ''}`).join(',');
  return `${el.branchHead ? el.branchHead.textContent : ''}|${cards}`;
}

// What a branch is looking at, drawn. Filled in with the per-branch decks below.
async function showBranchWorkspace(branchId) {
  const shown = await semanticCommand('branch.show', { branch_id: branchId });
  if (shown && shown.ok && Array.isArray(shown.ui) && shown.ui.length) {
    const rendered = window.CrooksUI.render(shown.ui, renderOpts());
    if (rendered.nodes.length) {
      pushContext(rendered.nodes, shown.ui, shown.answer || '');
      el.answer.textContent = shown.answer || '';
      el.heard.textContent = shown.changed && shown.changed.question ? `“${shown.changed.question}”` : '';
      // A card waiting for a gesture is drawn as the Mac last presented it; whether it still
      // waits is the Mac's to say. Never trusted from a copy.
      if (liveProposalIds().length) reconcileActions('workspace restored');
      drawBranchHead();
      return true;
    }
  }
  if (shown && shown.ok && shown.changed && shown.changed.empty) {
    // A half that holds nothing. The Mac says what it holds and what can be done from here,
    // and that is drawn as a screen of its own — never the other half's cards left standing,
    // and never a line of toast that has gone by the time he looks up.
    el.answer.textContent = shown.answer || '';
    el.heard.textContent = '';
    drawEmptyHalf(shown);
    return true;
  }
  return false;
}

// After a reload the Mac still holds the conversation: which halves there are, which one is
// focused, and what each was looking at. The deck used to come back empty — a screen that
// forgot everything the Mac remembered. Asked of the Mac, never read from browser storage.
async function restoreWorkspace() {
  if (!sessionId) return;
  try {
    const response = await fetch(`/branches?session_id=${encodeURIComponent(sessionId)}`, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    applyBranches(data);
    const focused = branches.find((b) => b.branch_id === focusedBranch);
    // With one half and nothing on it there is nothing to put back. With two, the half being
    // looked at is asked for either way: a half that holds nothing draws what it holds and the
    // ways out of it, and a reload that left the owner on a blank screen under one of two
    // identical chips is the state this whole section is about.
    if (!focused || (!focused.has_workspace && branches.length < 2)) return;
    const drawn = await showBranchWorkspace(focusedBranch);
    T.record('navigate', { nav: 'restore', name: drawn ? 'drawn' : 'nothing', id: focusedBranch });
  } catch { /* offline: the idle screen is the honest one */ }
}

// Every branch verb is one POST and one answer the page redraws itself from. The tablet
// never decides that a half has moved, merged or closed.
async function branchCommand(branchId, verb) {
  if (!branchId && verb !== 'fork') return;
  const form = new FormData();
  form.append('session_id', sessionId);
  const path = verb === 'fork' ? '/branches/fork' : `/branches/${encodeURIComponent(branchId)}/${verb}`;
  try {
    const response = await fetch(path, { method: 'POST', body: form, cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    T.record('branch_command', { action: verb, status: response.status, id: branchId || undefined });
    if (!response.ok) { notify(String(data.detail || 'That is not possible just now.'), { tone: 'bad', code: 'branch_refused' }); return null; }
    applyBranches(data);
    if (verb === 'merge' && data.merged) {
      const waiting = Array.isArray(data.merged.still_waiting) ? data.merged.still_waiting.length : 0;
      // D-10. "Merged. 2 things it looked at came back." IS GONE, and so is every other way
      // of saying `merged`: the orb visibly becoming one orb, the two chips becoming one and
      // the deck gaining what came back are the notification. Three of the live session's
      // five texted notifications were `divided` and two were `merged`; they are all zero
      // now, and web/notify.js refuses either code outright (SCREEN_SHOWS).
      //
      // What the screen does NOT show is a change the other half had staged and nobody has
      // authorised yet — it survived the merge and is still waiting for a gesture. That is a
      // meaningful task outcome with nowhere else to live, so it stays, as a WARN with its
      // own name, and only when there is one. On the session's own timeline, where zero
      // proposals were ever staged, this says nothing at all.
      if (waiting) {
        notify(`${waiting} change${waiting === 1 ? '' : 's'} came back still waiting for you.`,
          { tone: 'warn', code: 'merge_waiting', branch: focusedBranch });
      }
    }
    if (verb === 'cancel' && Array.isArray(data.revoked) && data.revoked.length) {
      settleProposals(data.revoked, 'revoked', 'Withdrawn');
    }
    return data;
  } catch {
    notify('The server did not answer.', { class: 'global', machine: true, tone: 'bad', code: 'backend_silent' });
    return null;
  }
}

// The gestures the orb itself carries. Two fingers pulled apart divide it; pinched together
// they merge it. A tap on a half while it is divided is how the owner chooses which one he
// is talking to. Everything a gesture does, the chips below do too — an eight-inch tablet on
// a workbench should never have exactly one way to do a thing.
// The spread and the pinch themselves are measured on the hold surfaces (onHoldMove), where
// the fingers actually are. They used to be touch listeners on the orb zone, which the talk
// overlay covers in orb mode — so in the one mode the owner would try the gesture, it fired
// nothing. The Split chip and the gesture post the same command.
async function splitOrb(how) {
  if (branches.length > 1) return;
  T.record('navigate', { nav: 'split', name: how });
  const data = await branchCommand('', 'fork');
  // D-10. "Divided. Tap a half to talk to it; the other keeps working." IS GONE. It was said
  // three times in the live session, over a screen that had just visibly become two halves
  // with two named chips under it. The haptic stays: it is the confirmation a thumb gets
  // without looking, and it is not a message.
  if (data) haptic(HAPTIC.done);
}
async function mergeOrb(how) {
  const other = (branches.find((b) => b.branch_id !== focusedBranch) || {}).branch_id;
  if (!other) return;
  T.record('navigate', { nav: 'merge', name: how });
  await branchCommand(other, 'merge');
}

function wireOrbGestures() {
  const zone = el.orbZone;
  if (!zone || !zone.addEventListener) return;
  zone.addEventListener('click', (event) => {
    if (branches.length < 2) return;
    const box = zone.getBoundingClientRect ? zone.getBoundingClientRect() : null;
    if (!box) return;
    const half = event.clientX < box.left + box.width / 2 ? 0 : 1;
    const wanted = branches[half];
    if (wanted && wanted.branch_id !== focusedBranch) branchCommand(wanted.branch_id, 'focus');
  });
}

// The half of the orb this screen belongs to, as the Mac last described it. Every /turn
// answers with it; nothing here is inferred from what is on screen.
let branchState = null;

function noteBranch(branch) {
  if (!branch || typeof branch !== 'object' || !branch.branch_id) return;
  branchState = branch;
  // The set chip comes with the branch, so a tap that moves the cursor and a sentence that
  // opens a different list both keep it honest.
  noteWorkingSet(branch.workflow);
  const before = focusedBranch;
  focusedBranch = branch.branch_id;
  if (!deckBranch) deckBranch = branch.branch_id;
  branches = branches.map((b) => (b.branch_id === branch.branch_id ? branch : b));
  if (!branches.some((b) => b.branch_id === branch.branch_id)) branches = [branch];
  // The first answer names the half the tablet had been calling '_' until now.
  if (!before && inflight.has('_')) { inflight.set(turnKey(focusedBranch), inflight.get('_')); inflight.delete('_'); }
  if (before !== focusedBranch) syncBusy();
  drawBranchBar();      // which redraws the header band with it
  // All three walk chips, from the branch that just answered: Back from its trail, Previous
  // and Next from its open list. Two writers used to set the Back chip and disagreed about
  // what Back was for; there is one function now (`drawWalkChips`).
  drawWalkChips();
  drawArmed(branch.listening_for);
  T.record('branch', { id: branch.branch_id, name: branch.status, depth: branch.depth, label: branch.label || undefined });
}

// What the next sentence will be applied to, while the Mac is listening for it.
//
// `branch.listening_for` arrives on EVERY /command and /turn reply and was discarded, so
// even a binding made by another route left the screen saying "Hold to speak" and nothing
// else. Pixel-diffing the tap that arms it: 9,961 pixels changed on an 800x1280 screen, 0 of
// them on the card and 0 on the chip — all 9,925 meaningful ones in a dock pill 788px below
// the finger, in 11px uppercase, wiped as soon as the thumb went down to speak.
//
// It is drawn from the branch and never from the tap, so it is right after a reload, after a
// binding made by voice, and after the Mac lets one expire.
function drawArmed(listening) {
  const on = Boolean(listening && listening.family);
  // What the next sentence will do, and to whom: "Replying to Damon". The Mac's phrase, never
  // the thread's subject — which is what clipped on the bench in a band that could not wrap.
  const words = on ? String(listening.phrase || listening.prompt || 'Listening') : '';
  document.body.dataset.listeningFor = on ? String(listening.family) : '';
  // The chip itself, which never changed by a single pixel: same class, same background, same
  // border, no aria-pressed. The one the finger touched is the one that should look touched.
  let armedChip = null;
  for (const chip of document.querySelectorAll('#cards .rail-chip[data-family]')) {
    const armed = on && chip.dataset.family === String(listening.family);
    chip.dataset.primed = armed ? '1' : '';
    chip.setAttribute('aria-pressed', armed ? 'true' : 'false');
    if (armed && !armedChip) armedChip = chip;
  }
  // The pill sits ON the control that was armed — directly under its rail, inside the card —
  // so it is attached to the thing it is about, covers nothing, and wraps rather than clips
  // at 601px. When the armed control is not on this screen (a binding made by voice, or on
  // another card), the band above the deck stands in.
  for (const stale of document.querySelectorAll('#cards .armed-inline')) stale.remove();
  const rail = armedChip ? armedChip.closest('.rail') : null;
  if (on && rail && rail.parentNode) {
    const pill = document.createElement('div');
    pill.className = 'armed armed-inline';
    pill.setAttribute('role', 'status');
    const dot = document.createElement('span'); dot.className = 'armed-dot'; dot.setAttribute('aria-hidden', 'true');
    const what = document.createElement('span'); what.className = 'armed-what'; what.textContent = words;
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'armed-cancel'; cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => { if (el.armedCancel) el.armedCancel.click(); });
    pill.appendChild(dot); pill.appendChild(what); pill.appendChild(cancel);
    rail.insertAdjacentElement('afterend', pill);
    if (el.armed) el.armed.hidden = true;
    return;
  }
  if (el.armed) {
    el.armed.hidden = !on;
    if (on && el.armedWhat) el.armedWhat.textContent = words;
  }
}

/* ------------------------------------------------------ which tab, per record (D-2)
 *
 * 20:18:12: "I'm not seeing any UI here except email where there's nothing … I want to also
 * be seeing his orders and his history". It was there, one tab away on the same card.
 *
 * `renderOpts().tab` was ONE value per BRANCH. He tapped Email once, on one customer; from
 * then on every card with tabs opened on Email — twenty-three of them, over a panel that was
 * usually empty, for records he had never opened. So a tab belongs to a RECORD, and the key
 * is the render identity: the same name the patch protocol addresses that card by, so the
 * page, the Mac (`branch.tabs`) and the renderer all mean the same card.
 *
 * Per half as well as per record: the same customer, open on two halves of the orb, is two
 * screens and the owner may be reading a different part of him on each.
 */
const cardTabs = new Map();
const MAX_CARD_TABS = 48;
function tabKeyOf(id) { return `${focusedBranch || '_'}|${id}`; }

// The tab this record was left on: what the page has been told, and failing that the Mac's
// own copy, which is what survives a reload, a branch switch and a half put aside. The local
// answer wins because it is the newer of the two — the POST below may still be in flight.
function tabOfCard(id) {
  const mine = cardTabs.get(tabKeyOf(id));
  if (mine) return mine;
  const held = branchState && branchState.tabs ? branchState.tabs[id] : '';
  return typeof held === 'string' ? held : '';
}

// A tab was chosen, on a particular record. The Mac keeps it against that record and against
// the branch's current stop, so going back and coming forward again puts THAT card back on
// the tab it was left on — and nothing else on it.
function noteTab(id, name, label, kind) {
  if (id && name) {
    cardTabs.delete(tabKeyOf(id));
    cardTabs.set(tabKeyOf(id), name);
    while (cardTabs.size > MAX_CARD_TABS) cardTabs.delete(cardTabs.keys().next().value);
  }
  T.record('tab', { name: kind || '', label: label || name, detail: id || undefined });
  if (!branchState) return;
  const form = new FormData();
  form.append('session_id', sessionId);
  form.append('tab', name);
  form.append('of', id || '');
  fetch(`/branches/${encodeURIComponent(branchState.branch_id)}/mark`, { method: 'POST', body: form, cache: 'no-store' }).catch(() => {});
}

// A row's own button. The answer is a staged change with its card; it still waits for a
// gesture, exactly as one the assistant proposed does.
async function rowAction(action, ref, button) {
  // A rail chip carries its label in a span; a row button IS its label. Both come here.
  const label = button ? (button.querySelector('.rail-label') || button) : null;
  const was = label ? label.textContent : '';
  if (label && !button.querySelector('.rail-label')) label.textContent = 'Preparing…';
  const restore = () => { if (button) { button.disabled = false; if (label) label.textContent = was; } };
  const form = new FormData();
  form.append('session_id', sessionId);
  form.append('action', action);
  form.append('ref', ref);
  try {
    const response = await fetch('/actions/row', { method: 'POST', body: form, cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    T.record('row_action', { action, status: response.status, outcome: response.ok ? 'staged' : 'refused', proposal_id: data && data.proposal_id });
    if (!response.ok) {
      // CONTROL-LOCAL: a refusal about THIS chip belongs beside it, where the thumb is.
      notifyControl(String((data && data.detail) || 'That could not be prepared.'), button,
        { tone: 'bad', code: 'row_refused' });
      restore();
      return;
    }
    if (label) label.textContent = 'Waiting for you';
    if (data && Array.isArray(data.ui) && data.ui.length && window.CrooksUI) {
      // The list the row is on stays, with the card above it (round 12).
      if (drawTapAnswer(data.ui, 'Archive')) speakAnswer('That one is ready to archive. Tap the card.');
    }
  } catch {
    T.record('row_action', { action, status: 0, outcome: 'refused' });
    notifyControl('The server did not answer.', button, { tone: 'bad', code: 'offline' });
    restore();
  }
}

// A proposal and a batch are authorised by the same gestures at different routes. The id
// says which: the Mac issues both, and the tablet forwards either with nothing else.
function isBatch(id) {
  return String(id || '').startsWith('batch_');
}

// The owner's hold began on a card whose gesture is a hold. Tell the Mac now; it hands back
// a single-use token the commit will carry. No token, no commit — the surface says so.
async function armAction(proposalId) {
  if (actionBlocked()) return null;
  const form = new FormData();
  form.append('session_id', sessionId);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const response = isBatch(proposalId)
      ? await fetch(`/batches/${encodeURIComponent(proposalId)}/arm`, { method: 'POST', body: form, signal: controller.signal, cache: 'no-store' })
      : await fetch(`/actions/${encodeURIComponent(proposalId)}/arm`, { method: 'POST', body: form, signal: controller.signal, cache: 'no-store' });
    if (!response.ok) { T.record('action_arm', { proposal_id: proposalId, status: response.status, outcome: 'refused' }); return null; }
    const data = await response.json();
    T.record('action_arm', { proposal_id: proposalId, status: response.status, outcome: data && data.nonce ? 'armed' : 'no_token' });
    return data && data.nonce ? String(data.nonce) : null;
  } catch { T.record('action_arm', { proposal_id: proposalId, status: 0, outcome: 'unreachable' }); return null; } finally { clearTimeout(timer); }
}

// A rail chip: the Mac says this change makes sense for the order. The chip does not stage
// anything — it puts the words in the owner's mouth. The dock says what to say; the hold
// asks; the Mac prepares; the gesture applies. Nothing shortcuts that.
let primedInstruction = '';
async function primeAction(action, chip) {
  const words = String(action && action.instruction || '').trim();
  if (!words || actionBlocked()) return;
  if (liveActionSurface()) {
    // A card is waiting for a gesture: a new ask would withdraw it. Say so instead of
    // silently replacing what the owner may be about to apply.
    //
    // BESIDE THE CHIP, not through #state-sub: that element is `display:none` in context
    // mode (web/style.css), and a card waiting for a gesture is ALWAYS context mode — so this
    // sentence, and the one below it, were written to an invisible element in every state
    // where they could occur. Measured shown:false in every context-mode sample.
    notifyControl('Finish or leave the card that is waiting first.', chip, { tone: 'bad', code: 'card_waiting' });
    haptic(HAPTIC.error);
    T.record('action_primed', { action: String(action.id || ''), outcome: 'blocked_by_live_card' });
    return;
  }
  primedInstruction = words;
  haptic(HAPTIC.start);

  // Tell the Mac what the next sentence is about.
  //
  // This is the whole of the touch→voice continuation, and until now the tablet did not do
  // it. `voice.bind` has been on the Mac since Phase 1 — it binds the family and the record,
  // annotates the sentence that follows as `[This continues order.add_note on the order the
  // owner is looking at (#1938)…]`, expires after 120s, and is abandoned by "go back" rather
  // than captured by it. The string "voice.bind" appeared ZERO times in web/, so the sentence
  // the tablet actually sent was bare and unannotated: the chip put the words in the owner's
  // mouth and then applied them to whatever the model happened to infer. Every test of the
  // mechanism posted the bind through the harness, so nothing caught it.
  //
  // A chip with no family is unchanged: it primes the words and binds nothing.
  const family = String(action && action.family || '').trim();
  const entity = branchState && branchState.entity ? branchState.entity : null;
  if (!family) {
    // No spoken control behind this chip: it primes the words and binds nothing, which is
    // what every chip did. The dock carries it, and gives up after eight seconds.
    el.talkLabel.textContent = `Hold and say: “${words}”`;
    clearTimeout(busyHintTimer);
    busyHintTimer = setTimeout(() => { if (!recording && primedInstruction === words) { primedInstruction = ''; el.talkLabel.textContent = 'Hold to speak'; } }, 8000);
    T.record('action_primed', { action: String(action.id || ''), outcome: 'primed' });
    return;
  }
  const bound = await semanticCommand('voice.bind', {
    family, kind: entity ? entity.kind : undefined, ref: entity ? entity.ref : undefined,
  });
  const listening = bound && bound.ok && bound.changed ? bound.changed.listening_for : null;
  if (!listening) {
    // The Mac refused — there is no record of that kind open. Say the reason it gave rather
    // than leaving the owner holding a primed sentence that will not land where he thinks.
    primedInstruction = '';
    notifyControl((bound && (bound.answer || bound.detail)) || 'There is nothing open to do that to.', chip, { tone: 'bad', code: 'nothing_open' });
    T.record('action_primed', { action: String(action.id || ''), outcome: 'refused' });
    return;
  }
  // Nothing is written to the dock. `noteBranch` has already drawn the band from the branch
  // this reply carried, and the band is where the armed state belongs: #talk-label is
  // overwritten by 'Release to send' the instant the thumb goes down to speak, so the one
  // piece of feedback there was got wiped by the act of using it and never came back.
  T.record('action_primed', { action: String(action.id || ''), outcome: 'primed', name: family });
}

// No surface may sit in EXECUTING or VERIFYING once the Mac has finished with its proposal.
// The commit's own answer normally settles it; when that answer is lost — a dropped tailnet,
// a tab the system froze, a re-render — this is what notices. It asks the Mac and believes
// the answer; it never re-sends the change.
const WATCHDOG_MS = 20000;
const WATCHDOG_TRIES = 6;

function watchCommit(node, tries) {
  setTimeout(() => {
    if (!AS.isInFlight(AS.tokenOf(node))) return;   // settled by its own answer, as it should be
    reconcileActions('watchdog');
    if (tries > 1) watchCommit(node, tries - 1);
  }, WATCHDOG_MS);
}

async function commitAction(proposalId, node, nonce) {
  if (actionBlocked()) { settleActionNode(node, 'armed', 'Tap to apply'); T.record('action_commit', { proposal_id: proposalId, outcome: 'blocked_busy' }); return; }
  haptic(HAPTIC.start);
  watchCommit(node, WATCHDOG_TRIES);
  const commitStartedAt = Date.now();
  const form = new FormData();
  form.append('session_id', sessionId);
  let payload = null;
  let status = 0;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), isBatch(proposalId) ? BATCH_TIMEOUT_MS : ACTION_TIMEOUT_MS);
  // The arming token, when the gesture was a hold, travels as a header: the body carries
  // the session and nothing else, and the token is an authorisation, not an argument.
  const headers = nonce ? { 'X-Crooks-Arm': String(nonce) } : {};
  try {
    const response = isBatch(proposalId)
      ? await fetch(`/batches/${encodeURIComponent(proposalId)}/commit`, { method: 'POST', body: form, headers, signal: controller.signal, cache: 'no-store' })
      : await fetch(`/actions/${encodeURIComponent(proposalId)}/commit`, { method: 'POST', body: form, headers, signal: controller.signal, cache: 'no-store' });
    status = response.status;
    payload = await response.json();
  } catch {
    // The request may have reached the Mac. It is never resent; the Mac's record decides.
    payload = await recoverActionState(proposalId);
  } finally {
    clearTimeout(timer);
  }
  T.record('action_commit', { proposal_id: proposalId, status: payload ? String(payload.status || '') : '', code: payload ? String(payload.code || '') : '', outcome: payload ? 'answered' : 'unknown', ms: Date.now() - commitStartedAt, detail: status ? String(status) : undefined });
  settleAction(node, payload, status);
}

async function recoverActionState(proposalId) {
  // A single change settles in seconds; a batch may still be applying its members, and the
  // Mac says so ("executing") until the count is final: keep asking, never tap again.
  const attempts = isBatch(proposalId) ? 40 : 4;
  for (let attempt = 0; attempt < attempts; attempt++) {
    await new Promise((r) => setTimeout(r, isBatch(proposalId) ? 3000 : 1500 * (attempt + 1)));
    try {
      const response = isBatch(proposalId)
        ? await fetch(`/batches/${encodeURIComponent(proposalId)}?session_id=${encodeURIComponent(sessionId)}`, { cache: 'no-store' })
        : await fetch(`/actions/${encodeURIComponent(proposalId)}?session_id=${encodeURIComponent(sessionId)}`, { cache: 'no-store' });
      const data = await response.json();
      if (data && data.status && data.status !== 'executing' && data.status !== 'executed') return data;
    } catch { /* still unreachable; try again */ }
  }
  return null;
}

// Everything on screen follows from what the Mac answered. Success is shown only when the
// Mac says VERIFIED; anything else is shown as exactly what it is.
function settleAction(node, payload, status) {
  if (!payload) {
    settleActionNode(node, 'unknown', "Couldn't reach the server · check the order");
    el.errline.textContent = 'The server did not confirm that. Check the order before trying again.';
    haptic(HAPTIC.error);
    return;
  }
  const code = String(payload.code || payload.status || (status >= 400 ? 'refused' : 'failed'));
  if (code === 'not_armed') {
    // The Mac did not see the hold: the card stays live for the hold that was meant.
    settleActionNode(node, 'armed', 'Hold first');
    haptic(HAPTIC.error);
    return;
  }
  if (code === 'in_progress' && !payload._recovered) {
    // The Mac is still proving the change: ask again until it knows, never tap again. The
    // surface says so in its own state — sent, being proven — rather than staying in the one
    // that means "this page is still waiting for an answer to its own request".
    settleActionNode(node, 'verifying', 'Applying…');
    recoverActionState(node.dataset.proposal || '').then((later) => settleAction(node, later ? Object.assign({ _recovered: true }, later) : null, 200));
    return;
  }
  const items = Array.isArray(payload.ui) ? payload.ui : [];
  if (payload.status === 'verified' && payload.undo && items.length && items[0].type === 'success') {
    items[0].data.undo = Object.assign({ label: 'Undo', armed_after_ms: 650 }, payload.undo);
  }
  // A batch that ran: its card is the count, and the undo the Mac staged is a batch too.
  const batchDone = payload.status === 'done' && items.length && items[0].type === 'batch_result';
  if (batchDone && payload.undo && payload.undo.batch_id) {
    items[0].data.undo = Object.assign({ label: 'Undo all', armed_after_ms: 650 }, payload.undo);
  }
  const proven = payload.status === 'verified' || (batchDone && payload.all_verified === true);
  const rendered = window.CrooksUI ? window.CrooksUI.render(items, renderOpts()) : { nodes: [] };
  // A card that already records something that happened — "Note added" and its undo — is
  // never replaced by the answer to a tap that did not happen: the undo's surface settles
  // and the proof stays on screen.
  const keepTheCard = node.classList && node.classList.contains('card-success') && payload.status !== 'verified' && payload.status !== 'done';
  const ref = node.dataset ? String(node.dataset.ref || '') : '';
  if (rendered.nodes.length && !keepTheCard) {
    // The Apply affordance goes and the proof takes its place — carrying the entity as the
    // Mac has just re-read it, and the undo as a control of its own. The deck's history is
    // patched in place (replaceCardNodes), so where the owner is does not move.
    replaceCardNodes(node, rendered.nodes);
    // The record the proof re-read goes on filling in as a turn's does: its history and its
    // inbox are collected after it is up rather than left saying "reading…" (round 12).
    for (const fresh of rendered.nodes) collectPending(fresh);
  } else {
    settleActionNode(node, code === 'verified' ? 'verified' : code, AS.labelFor(code, 'Not applied'));
  }
  if (proven) {
    // The entity has moved. Any other card still offering a change to it was prepared
    // against the state that has just changed, and the Mac would refuse it as stale: it says
    // so now, rather than after a gesture that cannot work.
    const retired = retireStaleAffordances(ref, String(node.dataset ? node.dataset.proposal || '' : ''), rendered.nodes);
    if (retired.length) T.record('action_stale_affordance', { count: retired.length, entity: ref.slice(0, 80) });
  }
  if (status >= 400 && !items.length) {
    const surface = node.querySelector ? node.querySelector('.action-surface') : null;
    notifyControl(ACTION_REASONS[code] || String(payload.detail || 'That could not be applied.'),
      surface, { tone: 'bad', code: codeOf(`action_${code}`, 'action_refused') });
  }
  // Whatever this page believes just happened, ask the Mac. It is the only one that knows.
  reconcileActions('gesture');
  haptic(proven ? HAPTIC.done : HAPTIC.error);
  if (proven && !busy && !recording) {
    // The one moment the green orb is for: the Mac proved the change — every member of it.
    setState('SUCCESS');
    setTimeout(() => { if (!busy && !recording && el.stage.dataset.state === 'SUCCESS') setState('READY'); }, 1400);
  }
  if (payload.spoken) speakAnswer(String(payload.spoken), { isError: !proven });
}

// The words for every outcome either side can produce live in web/action-state.js, beside the
// state each of them means (AS.labelFor). This page kept a second copy of that table until
// the two disagreed about what `executed` said.
//
// And these are the lines under a refusal: not what the surface says, but what the owner is
// told to do about it, which is this page's business and nobody else's.
const ACTION_REASONS = {
  refused: 'The service refused that. The card says why.',
  not_authorised: "This device's login is not on the server's allowed list (CROOKS_ALLOWED_LOGINS).",
  not_authorised_local: 'Requests made on the server itself may not apply changes (CROOKS_WRITES_LOCAL_OWNER).',
  writes_disabled: 'Changes are switched off on the server (CROOKS_WRITES_ENABLED).',
  allow_list_missing: 'No allowed logins are configured on the server (CROOKS_ALLOWED_LOGINS).',
  identity_unverified: "The server could not confirm this device's identity with Tailscale.",
  unknown: 'The server is no longer holding that change — it was restarted, or it waited too long. Ask again.',
  wrong_session: 'That proposal belongs to another conversation.',
};

// One card, settled — unless it is already finished, which nothing may undo.
function settleActionNode(node, state, label) {
  return AS.settleCard(node, state, label);
}

// Every other card still offering a change to an entity that has just changed. A proposal is
// prepared from a read; once the thing it was prepared against has moved, the Mac's own
// precondition will refuse it, so the affordance goes now with the reason on it.
function retireStaleAffordances(ref, keep, fresh) {
  return AS.staleAffordances(visibleCards(), ref, keep, fresh);
}

// True when every card in this answer is a confirmation whose surface is already arming or
// armed on the current screen: nothing new to show.
function onlyLiveCardsAlreadyShown(items) {
  const cards = (items || []).filter((i) => i && i.type !== 'context_stack');
  if (!cards.length || cards.some((i) => i.type !== 'confirmation' && i.type !== 'batch_action')) return false;
  return cards.every((i) => {
    const id = String(i.data && (i.data.proposal_id || i.data.batch_id) || '').replace(/["\\]/g, '');
    const node = el.cards ? el.cards.querySelector(`[data-proposal="${id}"] .action-surface`) : null;
    if (!node) return false;
    const state = AS.stateOf(node.dataset.state);
    return state === 'ARMING' || state === 'ARMED';
  });
}

// Letting go of a question in flight. The Mac answers with the cards it withdrew — anything
// proposed under the question being abandoned — and exactly those are settled here.
function cancelTurn(form, whyItIsSafeToIgnore) {
  fetch('/cancel', { method: 'POST', body: form })
    .then((response) => (response.ok ? response.json() : null))
    .then((data) => {
      if (data && Array.isArray(data.revoked) && data.revoked.length) settleProposals(data.revoked, 'revoked', 'Withdrawn');
    })
    .catch(() => { /* whyItIsSafeToIgnore */ });
}

// The cards the Mac named, wherever the deck still holds them.
// ------------------------------------------------- what the Mac says is true

// Every card the deck is holding, wherever it is: the history's entries and whatever is on
// screen now. The state machine walks exactly this list.
function visibleCards() {
  const nodes = [];
  for (const entry of history) for (const node of entry.nodes) nodes.push(node);
  if (el.cards) for (const node of Array.from(el.cards.children)) nodes.push(node);
  return nodes;
}

// Every card on this screen that has not finished, by proposal id. A terminal card is never
// asked about again: the live session's tablet re-submitted two settled proposals to every
// reconcile for six turns, one HTTP round trip each, correcting nothing.
function liveProposalIds() {
  return AS.liveProposalIds(visibleCards());
}

// The September session ended with two batches this page reported committed that the Mac
// never claimed. A gesture is a request; only the Mac knows what became of it. So the page
// asks — after every gesture and whenever it comes back to itself — and believes the answer.
// Nothing here infers an outcome from the fact that a finger moved.
// What the Mac's statuses do to the cards on screen is AS.SETTLED, in web/action-state.js,
// and this page no longer keeps its own copy of it. PENDING, EXECUTING and EXECUTED settle
// nothing there — the change is still being made or proven, and an outcome the owner has not
// been given is not shown to him as one.
let reconciling = false;
// What the last reconciliation did: which cards the Mac's answer settled, and which were
// still in flight after that and had to be corrected by force. `stuck` is meant to be empty
// for ever; a browser check asserts that it is (scripts/browser/action_state.js), so that a
// correction path which has quietly stopped working cannot hide behind the watchdog.
let lastReconcile = null;

async function reconcileActions(reason) {
  const ids = liveProposalIds();
  if (!ids.length || reconciling) return;
  reconciling = true;
  try {
    const response = await fetch(`/actions/states?session_id=${encodeURIComponent(sessionId)}&ids=${encodeURIComponent(ids.join(','))}`, { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    const states = (data && data.states) || {};
    // Every card the Mac has finished with is settled, from whatever state it is in. The one
    // exception is a card that is already terminal, which nothing may touch.
    const { corrected, stuck } = AS.reconcile(visibleCards(), states);
    // The watchdog. A surface still EXECUTING or VERIFYING after its proposal reached a
    // terminal state on the Mac is the September defect itself, and it is reported as one
    // rather than quietly repaired: the state was written by force above because nothing on
    // the page could ask that surface to settle.
    for (const surface of stuck) {
      T.record('action_watchdog', { reason, proposal_id: surface.proposal_id, before: surface.was, after: surface.state, status: surface.status });
    }
    // An id the Mac has never heard of cannot be applied by any gesture, so it must stop
    // looking as though it can — but only when the Mac is holding this conversation. A Mac
    // that has restarted, or a conversation that idled out, knows nothing about any
    // proposal, and its silence is not evidence that a card is dead.
    const unknown = data && data.session_known ? (Array.isArray(data.unknown) ? data.unknown : []) : [];
    if (unknown.length) settleProposals(unknown, 'settled', 'No longer waiting');
    lastReconcile = { reason, asked: ids, corrected, stuck, cancelled: unknown };
    if (corrected.length || unknown.length || stuck.length) {
      T.record('reconcile', { reason, count: ids.length, kept: corrected.length, cancelled: unknown.length, errors: stuck.length || undefined });
    }
  } catch {
    // The Mac did not answer. The cards stay as they are and the next reconcile tries again.
  } finally {
    reconciling = false;
  }
}

// The Mac has spoken about these proposals. Every card showing one of them settles — from
// ARMING, from ARMED, from EXECUTING, from anything that is not already finished. Settling
// from two states only is what left a proved send saying "Applying…" all session.
function settleProposals(ids, state, label) {
  return AS.settleProposals(ids, state, label, visibleCards());
}

// A settled action replaces its card, and a verified re-read of the entity replaces every
// card that showed that entity, so the screen shows Shopify as it now is.
//
// Takes NODES that are already drawn. `replaceComposeCard` below takes a ui list and draws
// it. They were both called `replaceCard` until Phase 4: JavaScript hoists the second over
// the first, so every call here silently reached the other one and settleAction handed DOM
// nodes to CrooksUI.render. The name says which one it is now.
function replaceCardNodes(oldNode, newNodes) {
  // Round 12: the record the proof re-read is usually already up — the order under the card,
  // kept there while the change waited. It is redrawn where it stands, with its new state; only
  // the rest (the proof) take the card's place. Appending it after the proof put the same
  // order on the glass twice, the stale copy above the fresh one.
  const inPlace = refreshInPlace(oldNode, newNodes);
  const here = newNodes.filter((node) => inPlace.indexOf(node) === -1);
  for (const entry of history) {
    const at = entry.nodes.indexOf(oldNode);
    if (at !== -1) entry.nodes.splice(at, 1, ...here);
  }
  if (oldNode.parentNode) {
    const parent = oldNode.parentNode;
    if (here.length) {
      parent.replaceChild(here[0], oldNode);
      let after = here[0];
      for (const node of here.slice(1)) { parent.insertBefore(node, after.nextSibling); after = node; }
    } else {
      parent.removeChild(oldNode);
    }
  }
  for (const node of newNodes) {
    if (node.dataset && node.dataset.type === 'order' && node.dataset.ref) refreshEntityCards(node);
  }
}

// Each new node whose card is already on the glass, elsewhere than `oldNode`, put in that
// card's place (and in the deck's copies of it), without replaying its entrance. Returns the
// nodes placed.
function refreshInPlace(oldNode, newNodes) {
  const placed = [];
  if (!el.cards || !window.CrooksUI || typeof window.CrooksUI.renderIdOf !== 'function') return placed;
  const up = Array.prototype.slice.call(el.cards.children).filter((node) => node !== oldNode);
  for (const fresh of newNodes) {
    const id = window.CrooksUI.renderIdOf(fresh);
    const stale = id ? up.find((node) => window.CrooksUI.renderIdOf(node) === id) : null;
    if (!stale || !stale.parentNode) continue;
    fresh.dataset.patched = '1';
    stale.parentNode.replaceChild(fresh, stale);
    for (const entry of history) {
      const at = entry.nodes.indexOf(stale);
      if (at !== -1) entry.nodes[at] = fresh;
    }
    up.splice(up.indexOf(stale), 1);
    placed.push(fresh);
  }
  return placed;
}

function refreshEntityCards(fresh) {
  const ref = fresh.dataset.ref;
  const replaceIn = (list) => {
    for (let i = 0; i < list.length; i++) {
      const node = list[i];
      if (node !== fresh && node.dataset && node.dataset.type === 'order' && node.dataset.ref === ref) {
        const copy = fresh.cloneNode(true);
        copy.dataset.ref = ref;
        if (node.parentNode) node.parentNode.replaceChild(copy, node);
        list[i] = copy;
      }
    }
  };
  for (const entry of history) replaceIn(entry.nodes);
}

/* -------------------------------------------------------------------- turn */

function renderTimings(timings, transcript) {
  if (!el.timingToggle.checked || !timings) { el.timings.hidden = true; return; }
  el.timings.hidden = false;
  const parts = Object.entries(timings).map(([k, v]) => `${k} ${v}ms`);
  if (transcript && transcript.engine) parts.unshift(`heard by ${transcript.engine}`);
  el.timings.textContent = parts.join('  ·  ');
}

// While a turn is in flight, ask the backend what it is actually doing. The state on screen
// is driven by the tool that is running, never inferred from the question.
const STATE_POLL_MS = 400;
const STATE_POLL_TIMEOUT_MS = 5000;
function startStatePolling() {
  stopStatePolling();
  let inFlight = false;   // a tick while the last poll is still out is skipped, never stacked
  const tick = async () => {
    if (!busy || inFlight || document.hidden) return;
    inFlight = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), STATE_POLL_TIMEOUT_MS);
    try {
      const url = `/state/${encodeURIComponent(sessionId)}?since=${encodeURIComponent(String(glass.cursor))}`
        + (focusedBranch ? `&branch_id=${encodeURIComponent(focusedBranch)}` : '');
      const data = await (await fetch(url, { cache: 'no-store', signal: controller.signal })).json();
      if (!busy || !data.known) return;
      // The workspace as it stands, patched in place. A card the reads have already produced
      // is readable NOW; the turn's own answer reconciles against it when it comes.
      if (data.workspace) applyWorkspace(data.workspace);
      noteRunningTool(data.detail);
      if (data.state && data.state !== 'READY' && data.state !== 'ERROR') setState(data.state, undefined, detailWords(data.detail, data.state));
      else if (busy && Date.now() - turnStartedAt > LONG_THINK_MS) el.sub.textContent = `Still working · ${Math.round((Date.now() - turnStartedAt) / 1000)} s`;
      // The transcript, the moment the Mac has it: a mis-heard question shows before the
      // answer to it is paid for.
      if (data.heard && !el.heard.textContent) {
        el.heard.textContent = `“${data.heard}”`;
        settleLiveWords(data.heard);   // and on the bar, in place of the live words
        // The words are on the glass: that, and not the release, is UNDERSTOOD. The machine
        // is handed the LENGTH — it is never told what was said (invariant 11).
        if (live) live.final(String(data.heard).length);
      }
    } catch { /* the turn response will carry the outcome */ } finally {
      clearTimeout(timer);
      inFlight = false;
    }
  };
  // The first look is immediate: the transcript should be on screen the moment the Mac has
  // it, not one interval later.
  statePoll = setInterval(tick, STATE_POLL_MS);
  setTimeout(tick, 60);
}
function stopStatePolling() { if (statePoll) { clearInterval(statePoll); statePoll = null; } }

const SPEAK_HEADERS_TIMEOUT_MS = 6000;    // the Mac gives a prefetch 4 s for its first byte; past this, Android speaks
let turnAbort = null;         // the focused half's in-flight /turn, so holding through a slow one can drop it
const TURN_TIMEOUT_MS = 130000; // a little over the backend's own 120 s turn timeout

// The turns in flight, one per half of the orb. Each half thinks on its own conversation on
// the Mac (app/providers/max_agent_sdk.py), so a question to the right half is not queued
// behind a thirty-second one on the left: it is asked now, and answered when it is answered.
// `busy` — which every hold, tap and card reads — is about the half on screen: its turn is
// in flight, or it is free. Switching halves switches what `busy` means (syncBusy).
const inflight = new Map();   // branch key -> { controller, startedAt, timeout }
function turnKey(branchId) { return branchId || '_'; }
function syncBusy() {
  const mine = inflight.get(turnKey(focusedBranch));
  busy = Boolean(mine);
  el.talk.dataset.busy = busy ? 'true' : 'false';
  turnAbort = mine ? mine.controller : null;
  if (mine) { turnStartedAt = mine.startedAt; startStatePolling(); } else stopStatePolling();
}
function cancelForm(branchId) {
  const form = new FormData();
  form.append('session_id', sessionId);
  if (branchId) form.append('branch_id', branchId);
  return form;
}

async function submit(body, isAudio) {
  // The half this question is for, fixed now: the owner may tap the other half while it
  // is being answered, and the answer must still land on the half that asked.
  const key = turnKey(focusedBranch);
  const askedBranch = focusedBranch;
  if (inflight.has(key)) return;   // one question at a time per half; the hold gate makes this unreachable
  // A card cannot be tapped while a question is in flight (actionBlocked). Whether this
  // question withdraws it is the Mac's decision, answered with the turn: a fumbled hold or
  // a recording that said nothing withdraws nothing.
  el.errline.textContent = '';
  el.heard.textContent = '';
  if (!isAudio) showHeardWords('', false);   // a typed question: no words left over from the last hold
  const hold = isAudio ? liveHold : undefined;   // the hold whose words this turn settles
  const startedAt = Date.now();
  T.record('turn_submitted', {
    screen: el.body.dataset.mode || '', index: historyIndex, entities: history[historyIndex] ? history[historyIndex].entities : [],
    audio_ms: isAudio ? lastRecordingMs : undefined, turns, before: liveActionSurface() ? 'live_card' : undefined,
    branch: askedBranch || undefined, concurrent: inflight.size || undefined,
  });
  // A dock shortcut or a typed ask was never held, so there is no acknowledgement and
  // nothing to transcribe — but the owner starts waiting here just the same, and the turn
  // is measured from it exactly as a spoken one is.
  if (live && !isAudio) live.asked(0);
  setState(isAudio ? 'TRANSCRIBING' : 'THINKING');
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
    // The Mac may still be holding the turn; tell it to let go so the next question is not
    // queued behind a dead one.
    cancelTurn(cancelForm(askedBranch), 'it will time out on its own');
  }, TURN_TIMEOUT_MS);
  inflight.set(key, { controller, startedAt, timeout });
  syncBusy();
  // Whether the owner is still looking at the half that asked. Checked when the answer
  // lands: an answer for the other half goes to the Mac's copy of that half's screen
  // (branch.show draws it when its chip is tapped), never over the cards on screen.
  const stillHere = () => key === '_' || turnKey(focusedBranch) === key;
  try {
    const options = isAudio
      ? { method: 'POST', body, signal: controller.signal }
      : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal };
    const response = await fetch('/turn', options);
    if (!response.ok) {
      T.record('turn_failed', { status: response.status, ms: Date.now() - startedAt });
      settleGlass('turn_failed');
      if (!stillHere()) { decks.delete(askedBranch); notify('The other half hit a problem.', { tone: 'bad', code: 'half_failed', branch: askedBranch }); return; }
      lastWasError = true;
      lastErrorTitle = response.status === 403 ? 'Not allowed' : 'The server hit a problem';
      el.errline.textContent = response.status === 403
        ? "The server refused this device: its login is not on the allowed list (CROOKS_ALLOWED_LOGINS)."
        : `The assistant on the server answered with an error (${response.status}). Try again.`;
      setState('ERROR', lastErrorTitle);
      haptic(HAPTIC.error);
      // A voice-first device says its errors: the owner is looking at their hands.
      speakAnswer(response.status === 403 ? 'This device is not allowed to ask.' : 'The server hit a problem. Ask again.', { isError: true });
      return;
    }
    const data = await response.json();

    sessionId = data.session_id || sessionId;
    store.set('crooks.session', sessionId);
    currentTurnId = data.turn_id ? String(data.turn_id) : '';
    if ('test_session_id' in data) T.configure({ test_session: data.test_session_id || null });
    T.setContext({ session_id: sessionId, turn_id: currentTurnId });
    T.record('turn_response', { ms: Date.now() - startedAt, error_kind: data.error_kind || undefined, items: (data.ui || []).map((i) => i && i.type), answer_chars: String(data.answer || '').length, turns: data.turns, elsewhere: !stillHere() || undefined });
    turns = typeof data.turns === 'number' ? data.turns : turns + 1;
    if (data.lost_thread) turns = 0;
    store.set('crooks.turns', String(turns));
    if (!stillHere()) {
      // The owner is talking to the other half. This half's chip says READY (the Mac marked
      // it so, seeing the focus elsewhere) and pulses once; its cards are the Mac's to redraw
      // when tapped. Nothing here is spoken, written or thrown over the conversation he is
      // having now — the brief is explicit: READY on the selector, no toast over the other
      // branch. The chip IS the notification.
      decks.delete(askedBranch);
      if (data.branches) applyBranches(data.branches);
      if (Array.isArray(data.revoked) && data.revoked.length) settleProposals(data.revoked, 'revoked', 'Withdrawn');
      haptic(HAPTIC.done);
      // No message over the conversation he is having: the chip says READY and pulses, and
      // he comes to it. The live session's floating "the other half has an answer" landed on
      // top of the half he was reading.
      return;
    }
    el.heard.textContent = data.question ? `“${data.question}”` : '';
    // And on the bar: the question actually asked, whether or not a /state poll saw it first
    // (round 9, G-02). A spoken turn that heard nothing clears the live words rather than
    // leaving them there as if they had been asked.
    if (isAudio) settleLiveWords(data.question, hold);
    el.answer.textContent = data.answer;
    lastWasError = Boolean(data.error_kind);
    if (data.build) pendingBuild = String(data.build);
    haptic(lastWasError ? HAPTIC.error : HAPTIC.done);
    // The cards first, so the headline is this answer's and not the last one's; then the
    // state; then the voice, which never waits on audio.
    noteBranch(data.branch);
    if (data.branches) applyBranches(data.branches);
    if (TRANSIENT_ERRORS.indexOf(String(data.error_kind || '')) !== -1) {
      sayAndStay(data);
      return;
    }
    renderTurn(data);
    if (!lastWasError) noteUseful('answer');
    setState(lastWasError ? 'ERROR' : 'READY', lastWasError ? lastErrorTitle : '');
    speakAnswer(data.answer, { isError: lastWasError });   // deliberately not awaited
    renderTimings(data.timings_ms, data.transcript);
    // Exactly the cards this instruction withdrew, as the Mac decided; no others.
    if (Array.isArray(data.revoked) && data.revoked.length) settleProposals(data.revoked, 'revoked', 'Withdrawn');
    reconcileActions('turn');
  } catch (error) {
    if (controller.signal.aborted && controller.cancelled) {
      // The owner moved on: nothing to report, the next question is already being asked. Its
      // skeletons go with it — a placeholder for a read nobody is waiting for any more.
      settleGlass('cancelled');
      if (stillHere()) { el.heard.textContent = ''; el.answer.textContent = ''; setState('READY'); }
      return;
    }
    T.record('turn_failed', { status: 0, aborted: controller.signal.aborted, ms: Date.now() - startedAt });
    settleGlass(controller.signal.aborted ? 'timed_out' : 'unreachable');
    if (!stillHere()) { decks.delete(askedBranch); notify('The other half hit a problem.', { tone: 'bad', code: 'half_failed', branch: askedBranch }); return; }
    lastWasError = true;
    lastErrorTitle = controller.signal.aborted ? 'The server took too long' : 'The server did not answer';
    el.errline.textContent = controller.signal.aborted
      ? 'That question was abandoned after two minutes. Ask again.'
      : 'Is the server up, and is the assistant running on it?';
    setState('ERROR', lastErrorTitle);
    setConn('down', 'Offline');
    haptic(HAPTIC.error);
    // The Mac did not answer, so this goes to the Android voice by way of a failed /speak.
    speakAnswer(controller.signal.aborted ? 'That took too long. Ask again.' : 'I cannot reach the server.', { isError: true });
    if (!controller.signal.aborted) setTimeout(checkReachable, 0);   // after `finally` clears busy
  } finally {
    clearTimeout(timeout);
    inflight.delete(key);
    // However the turn ended (answered on the other half, refused, failed, cancelled), the live
    // words of the hold that asked it are not kept: settled with the Mac's question when it said
    // one, and cleared when it did not.
    if (isAudio && hold === liveHold && liveHeardFinal === false) settleLiveWords('', hold);
    endJobs();
    // Invariant 11: what this turn FELT like, in milliseconds and counts only. No transcript,
    // no answer, no entity — the machine was never given any of them to leak.
    if (live) {
      const marks = live.marks();
      T.record('live_marks', {
        ack_ms: marks.acknowledgedMs === null ? undefined : marks.acknowledgedMs,
        transcript_ms: marks.transcriptMs === null ? undefined : marks.transcriptMs,
        progress_ms: marks.progressMs === null ? undefined : marks.progressMs,
        useful_ms: marks.usefulMs === null ? undefined : marks.usefulMs,
        responding_ms: marks.respondingMs === null ? undefined : marks.respondingMs,
        partials: marks.partials || undefined, heard_chars: marks.heardChars || undefined,
        interruptions: marks.interruptions || undefined, faults: marks.faults || undefined,
        state: live.state,
      });
    }
    syncBusy();
    if (!inflight.size) applyUpdateWhenIdle();
    // If speech is off there is no onend to settle the state, so do it here.
    if (!el.speakToggle.checked && stillHere()) setState(lastWasError ? 'ERROR' : 'READY', lastWasError ? lastErrorTitle : '');
  }
}

function sendAudio(blob) {
  const form = new FormData();
  form.append('audio', blob, 'turn.webm');
  form.append('session_id', sessionId);
  form.append('turns', String(turns));
  form.append('speak', el.speakToggle.checked ? '1' : '0');
  // Which half of a divided orb is being spoken to. Empty is the one the Mac has focused,
  // which is the usual case and the case when there is only one.
  if (focusedBranch) form.append('branch_id', focusedBranch);
  submit(form, true);
}

/* ------------------------------------------------------------------ events */

/* The hold, and §7's answer to D-1: every pointer on this page has exactly ONE owner, and it
 * is decided on the way down from what the finger actually landed on — CONTROL, SCROLL, VOICE,
 * SPLIT_GESTURE, APPROVAL_GESTURE or nothing. The machine itself is web/touch.js, which is
 * pure and unit-tested (tests/web/touch.test.js); everything here is the DOM half: what is
 * under the finger, and what the page does about the answer.
 *
 * WHY. 11 September: 132 hold-starts, 131 of them reporting `target:"dock"` because nothing
 * else on the page ever got a touch. `body[data-mode="orb"] .talk{inset:0}` made the voice
 * target the size of the viewport, the branch chips were capped inside `.orb-zone`'s stacking
 * context beneath it, and 63 taps on Split, Merge and Close became recordings — 26 of them in
 * ten consecutive seconds, while he said "wherever I press just leads to you listening".
 *
 * The stylesheet and index.html fixed the geometry (§8: the voice zone overlaps nothing, and
 * the branch chrome is a band of `.app` that `#talk` cannot reach). This is the belt to that
 * braces: a pointer that begins on a control can never become a sentence even if the geometry
 * is broken again by a future stylesheet, because CONTROL beats VOICE inside the machine.
 *
 * Two fingers are a gesture, never a sentence. The pending recording is discarded the moment
 * the second finger lands — the machine cancels it BEFORE it returns, so there is no window in
 * which a release could submit — and the pair is then measured for a spread (divide) or a
 * pinch (merge) until every finger lifts.
 */
const SPLIT_TRAVEL = 70;   // CSS px of change in separation; about 9mm on the Tab A at its DPR
const pointers = window.CrooksTouch.create({
  splitTravel: SPLIT_TRAVEL,
  // Reported by the machine the instant a pair forms, before anything else learns of it.
  onCancelVoice: (why) => {
    if (recording || pendingStart) stopRecording(true);
    if (cancelHoldTimer) { clearTimeout(cancelHoldTimer); cancelHoldTimer = null; }
    holding = false;
    setState('READY');
    haptic(HAPTIC.start);
    T.record('hold', { phase: 'multitouch', fingers: pointers.count(), outcome: 'discarded', name: why });
  },
});
// Read by scripts/browser/touch.js to prove the count it asserts on — downs by owner, and
// submits. Nothing on the page reads it, and it carries no content of any kind.
window.__crooksTouch = pointers;

/* What the finger came down on, read off the DOM. The deepest node decides: `event.target`,
   not the element the listener happens to be on. */
function hitUnder(event) {
  const node = event.target;
  const close = (selector) => (node && node.closest ? node.closest(selector) : null);
  const voice = Boolean(close('#talk, #orb-frame'));
  const approval = close(window.CrooksTouch.APPROVAL_SELECTOR);
  const control = approval ? null : close(window.CrooksTouch.CONTROL_SELECTOR);
  // A scroll container, and the deck in particular: a thumb that starts on a card is scrolling
  // it. `#cards` is the one that scrolls, and `.sheet-scroll` and `.tabs` are the others.
  const scroller = close('#cards, .deck, .sheet-scroll, .tabs, .context-nav');
  return {
    pointerId: event.pointerId, x: event.clientX, y: event.clientY, button: event.button,
    voice,
    approval: approval ? selectorName(approval) : '',
    control: control ? selectorName(control) : '',
    scroll: Boolean(scroller),
  };
}
/* A node, named, for the telemetry line and nothing else. `className` on an SVG element is an
   SVGAnimatedString rather than a string — the dock's four icons are SVG — so it is read
   through `baseVal`, or the whole name came out "[object SVGAnimatedString]". */
function selectorName(node) {
  const raw = typeof node.className === 'string' ? node.className
    : (node.className && node.className.baseVal) || '';
  const first = String(raw).split(' ').filter(Boolean)[0] || '';
  return `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ''}${first ? `.${first}` : ''}`;
}

/* Every pointer on the page is classified here, in CAPTURE, before any element's own handler
   can act on it — so the owner is settled before anything can start a recording. It records
   and nothing else: no preventDefault, no stopPropagation. A control keeps its click, a field
   keeps its focus, a card keeps its scroll. */
document.addEventListener('pointerdown', (event) => {
  pointers.down(hitUnder(event));
  /* And the lift, listened for ON THE NODE ITSELF, once. The document listener below catches
     the ordinary case; this catches the one it cannot. A tap on a branch chip REDRAWS the
     branch bar, which removes the chip from the document while the thumb is still on it — and
     a pointerup dispatched at a node that is no longer in the tree never reaches `document`,
     so the pointer stayed claimed in the machine for the rest of the session. A listener bound
     to the node fires wherever the node has got to. The gate found this by counting the
     pointers still down at the end of a run: it was never zero. */
  for (const type of ['pointerup', 'pointercancel']) {
    event.target.addEventListener(type, (lift) => {
      // Never the voice's own pointers: the hold surfaces answer for those, and the orb's
      // canvas is a DESCENDANT of one of them — this listener would run first and consume the
      // claim, so the recording would never be stopped by the thumb that started it.
      const owner = pointers.owner(lift.pointerId);
      if (owner === window.CrooksTouch.OWNER.VOICE || owner === window.CrooksTouch.OWNER.SPLIT) return;
      pointers.up({ pointerId: lift.pointerId, cancelled: lift.type === 'pointercancel' });
    }, { once: true });
  }
}, true);
// And released in the BUBBLE phase, after the hold surfaces have had their answer — a capture
// listener here would consume the lift before `onHoldEnd` could ask who owned it.
for (const type of ['pointerup', 'pointercancel']) {
  document.addEventListener(type, (event) => {
    pointers.up({ pointerId: event.pointerId, cancelled: event.type === 'pointercancel' });
  }, false);
}

function onHoldStart(event) {
  if (event.button !== undefined && event.button !== 0) return;
  // `down` is idempotent per pointer: the capture listener above has already classified this
  // one, and this asks for the same answer back rather than assigning a second.
  const claim = pointers.down(hitUnder(event));
  if (claim.owner !== window.CrooksTouch.OWNER.VOICE) {
    // A control, a scroll, an approval drag, or one of a pair. None of them is a question, and
    // the ones that are somebody else's keep their own default behaviour.
    if (claim.owner === window.CrooksTouch.OWNER.SPLIT) event.preventDefault();
    return;
  }
  event.preventDefault();
  // Capture the pointer so pointerup reaches this element even if the thumb drifts off it —
  // otherwise a slightly sliding thumb means the recording never stops. Deliberately only on
  // the VOICE path: capturing a control's pointer would steal its click.
  try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* unsupported */ }
  holding = true;
  unlockSpeech();          // must be inside the gesture
  stopSpeaking();          // before anything else: the voice must not be recorded answering itself
  acquireWakeLock();
  T.record('hold', { phase: 'start', state: busy ? 'busy' : 'ready', target: event.currentTarget === el.orbFrame ? 'orb' : 'talk' });
  if (busy) {
    // A turn is in flight. Say so; and if the hold goes on, take it as "forget that one".
    showBusyHint();
    clearTimeout(cancelHoldTimer);
    cancelHoldTimer = setTimeout(cancelTurnAndListen, CANCEL_HOLD_MS);
    return;
  }
  // Synchronously, inside the gesture: the acknowledgement the owner is waiting for is
  // this, not the recorder starting, and the machine measures it from here.
  if (live) live.pointerDown();
  setState('LISTENING');   // the orb wakes on the touch itself, not on the recorder
  startRecording();        // start before any other UI work, or the first word is clipped
}
let busyHintTimer = null;
let cancelHoldTimer = null;
let holding = false;         // the thumb is down on a hold surface
const CANCEL_HOLD_MS = 900;   // hold this long through a turn in flight to abandon it

function showBusyHint() {
  el.talkLabel.textContent = 'Keep holding to ask something else';
  if (orb) orb.pulse();
  clearTimeout(busyHintTimer);
  busyHintTimer = setTimeout(() => { if (!recording) el.talkLabel.textContent = 'Hold to speak'; }, 1600);
}

// The owner is still holding: the question in flight is not the one he wants answered.
// Drop it on the tablet, tell the Mac to stop thinking about it, and start listening.
function cancelTurnAndListen() {
  cancelHoldTimer = null;
  if (!busy || !turnAbort) return;
  T.record('turn_cancelled', { ms: Date.now() - turnStartedAt });
  if (live) live.interrupt('held through the turn');
  turnAbort.cancelled = true;
  turnAbort.abort();
  // This half's turn, and only this half's: the other half may be mid-thought about
  // something else, and a cancel here must not stop it.
  cancelTurn(cancelForm(focusedBranch), 'the abort already freed the page');
  haptic(HAPTIC.start);
  // submit()'s finally clears busy once the abort lands; start listening right after it —
  // if the thumb is still down. A thumb that lifted meanwhile just wanted the question gone.
  setTimeout(() => { if (holding && !busy && !recording) { setState('LISTENING'); startRecording(); } }, 60);
}

// V0.5 no longer lets a spread create user-visible Split state. Multi-touch still belongs to
// the gesture machine (so it never becomes accidental speech), and a pinch can collapse an
// already-existing legacy two-branch session. New concurrency is owned by CLIVE internally.
function onHoldMove(event) {
  const moved = pointers.move({ pointerId: event.pointerId, x: event.clientX, y: event.clientY });
  if (!moved) return;
  if (moved.gesture === 'pinch' && branches.length > 1) mergeOrb('gesture');
}

function onHoldEnd(event) {
  const done = pointers.up({ pointerId: event.pointerId, cancelled: event.type === 'pointercancel' });
  try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* noop */ }
  // The hold surfaces sit inside the document, so this runs FIRST and the document's own
  // release listener below gets `null` for the same pointer. A `null` here means the pointer
  // was never ours: released already, or cleared by a mode change.
  if (!done) return;
  // A pair, or a control, or a scroll: nothing to send, whichever finger lifted first, and the
  // machine has already counted it as submitting nothing.
  if (done.owner !== window.CrooksTouch.OWNER.VOICE) {
    if (done.owner === window.CrooksTouch.OWNER.SPLIT) {
      event.preventDefault();
      if (done.remaining === 0) holding = false;
    }
    return;
  }
  event.preventDefault();
  holding = false;
  if (cancelHoldTimer) { clearTimeout(cancelHoldTimer); cancelHoldTimer = null; }   // a tap, not a hold
  stopRecording(done.discard);
}
for (const target of [el.talk, el.orbFrame]) {
  target.addEventListener('pointerdown', onHoldStart);
  target.addEventListener('pointermove', onHoldMove);
  target.addEventListener('pointerup', onHoldEnd);
  target.addEventListener('pointercancel', onHoldEnd);
  // The capture went away without a lift — the element was removed, or Android took the
  // gesture. A pointer left down in the machine would pair with the next finger for the rest
  // of the session, so the voice would simply stop working. It is released here instead.
  target.addEventListener('lostpointercapture', (event) => {
    const done = pointers.up({ pointerId: event.pointerId, cancelled: true });
    if (done && done.owner === window.CrooksTouch.OWNER.VOICE) { holding = false; stopRecording(true); }
  });
  target.addEventListener('contextmenu', (event) => event.preventDefault());
}
// The app went away with a thumb down: nothing is held, and nothing is sent.
for (const type of ['blur', 'pagehide']) window.addEventListener(type, () => { pointers.clear(type); });
document.addEventListener('visibilitychange', () => { if (document.hidden) pointers.clear('hidden'); });
// What the owner touched on the cards, and what failed to load, for the test session.
// Delegated, so the renderer stays free of it; captured, so an image's error (which does
// not bubble) is seen. Nothing here reads the cards' text.
el.cards.addEventListener('click', (event) => {
  const target = event.target;
  const tab = target && target.closest ? target.closest('[role="tab"]') : null;
  if (tab) {
    const card = tab.closest('.card');
    T.record('tab', { label: tab.textContent.trim().slice(0, 40), name: card && card.dataset ? card.dataset.type : '', entity: card && card.dataset ? card.dataset.ref : '' });
    return;
  }
  const chip = target && target.closest ? target.closest('.rail-chip') : null;
  if (chip) {
    T.record('rail_tap', { action: chip.dataset.action || '', state: chip.getAttribute('aria-disabled') === 'true' ? 'disabled' : 'enabled' });
    return;
  }
  // A row that names a record opens it. `open.entity` has existed on the Mac since Phase 1 and
  // nothing on the page ever posted it, so the only way from a list of today's orders to one of
  // them was to say its number — the graph was navigable by voice and by voice alone. The row
  // carries the kind and the id it was given on the card, so nothing is looked up again.
  const link = target && target.closest ? target.closest('[data-ref][data-kind]') : null;
  if (link && !busy) {
    openEntity(link.dataset.kind, link.dataset.ref, labelOf(link));
    return;
  }
  // A chip carrying a question asks it. The capability card draws six of these and their
  // comment has always promised "tapping one is answered without the model — they post the
  // same text a spoken question would"; nothing listened, so they were styled, tappable
  // buttons that did nothing at all. They post the same body the transcript path posts, so
  // the question takes the same lane, the same recipe and the same presenter.
  const ask = target && target.closest ? target.closest('[data-ask]') : null;
  if (ask && !busy) {
    const text = (ask.dataset.ask || '').trim();
    if (!text) return;
    T.record('chip_ask', { text: text.slice(0, 60) });
    unlockSpeech();
    stopSpeaking();
    submit({ text, session_id: sessionId, turns, speak: el.speakToggle.checked }, false);
  }
});
el.cards.addEventListener('error', (event) => {
  const target = event.target;
  if (target && target.tagName === 'IMG') T.record('image_failed', { src: T.pathOnly(target.getAttribute('src')) });
}, true);
// A hand on the deck. While one is down nothing is patched under it: a control that moves
// mid-gesture is the defect the owner narrated out loud, and §7 forbids it outright.
//
// By pointer id, and released on the DOCUMENT rather than on the deck — a thumb that slides
// off a card still lifts, and a count that could be left stuck above zero would block every
// patch for the rest of the session, which is worse than the thing it was guarding.
el.cards.addEventListener('pointerdown', (event) => {
  deckPointers.add(event && event.pointerId !== undefined ? event.pointerId : 1);
}, true);
for (const type of ['pointerup', 'pointercancel']) {
  document.addEventListener(type, (event) => {
    deckPointers.delete(event && event.pointerId !== undefined ? event.pointerId : 1);
  }, true);
}
for (const type of ['pointerdown', 'pointerup', 'pointercancel']) {
  el.cards.addEventListener(type, (event) => {
    const surface = event.target && event.target.closest ? event.target.closest('.action-surface') : null;
    if (!surface) return;
    const card = surface.closest('.card');
    T.record('gesture', { gesture: type.slice(7), name: (surface.className.match(/kind-([a-z_]+)/) || [])[1] || '', state: surface.dataset.state || '', proposal_id: card && card.dataset ? card.dataset.proposal : '' });
  }, true);
}
let scrollReportTimer = null;
// How far down the cards the thumb went. Two destinations, and they are different things:
// the telemetry line is how the deep-scroll defect was measured, and `surface.scroll` tells
// the MAC, which keeps it against the stop the screen is on so a Back returns to it. It is
// the one part of a workspace the Mac cannot know by itself, and it was going nowhere but a
// log — so every Back landed at the top of a list the owner had come halfway down.
let scrollTold = -1;
el.cards.addEventListener('scroll', () => {
  scrollMax = Math.max(scrollMax, el.cards.scrollTop);
  if (scrollReportTimer) return;
  scrollReportTimer = setTimeout(() => {
    scrollReportTimer = null;
    const depth = Math.round(el.cards.scrollTop);
    T.record('scroll', { depth: Math.round(scrollMax), height: el.cards.scrollHeight, width: el.cards.clientHeight });
    // Only when it has actually moved, and never while a question is in flight: a depth is
    // worth one small post, not one per scroll event.
    if (Math.abs(depth - scrollTold) < 24 || busy) return;
    scrollTold = depth;
    semanticCommand('surface.scroll', { depth });
  }, 1500);
}, { passive: true });
window.addEventListener('error', (event) => {
  T.record('exception', { message: String(event && event.message || '').slice(0, 200), file: T.pathOnly(event && event.filename), line: event && event.lineno, col: event && event.colno });
});
window.addEventListener('unhandledrejection', (event) => {
  const reason = event && event.reason;
  T.record('exception', { message: String(reason && reason.message || reason || '').slice(0, 200), file: 'promise' });
});
window.addEventListener('pagehide', () => T.flush(true));
document.addEventListener('visibilitychange', () => { if (document.hidden) T.flush(true); });

// Keyboard: hold Space or Enter on the talk control.
el.talk.addEventListener('keydown', (event) => {
  if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {
    event.preventDefault(); unlockSpeech(); stopSpeaking(); if (!busy) { setState('LISTENING'); startRecording(); }
  }
});
el.talk.addEventListener('keyup', (event) => {
  if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); stopRecording(); }
});

el.homeBtn.addEventListener('click', goHome);
// `voice.cancel` was registered on the Mac in Phase 1 and had no affordance on the glass at
// all: an armed microphone could only be waited out.
if (el.armedCancel) {
  el.armedCancel.addEventListener('click', async () => {
    haptic(HAPTIC.error);
    primedInstruction = '';
    el.talkLabel.textContent = 'Hold to speak';
    const released = await semanticCommand('voice.cancel');
    // The reply carries the branch, so `noteBranch` has already taken the band down. If the
    // Mac could not be reached, take it down here rather than leaving a band that lies.
    if (!released) drawArmed(null);
  });
}
// A dock icon opens a place. It posts the semantic command `open.area` — which area, nothing
// else — and the Mac runs that landing's recipe: fixed reads, no model, the same presenter a
// sentence reaches (app/families/landings.py). The lit item is decided by what comes back.
// On the bench the dock asked a sentence through the whole turn pipeline, and "show me
// today's orders" on a quiet afternoon drew an empty list: a place must have a shape whatever
// was said before it. The sentence survives as the fallback for a landing the Mac cannot
// draw just now (a source that did not answer), so the tap still does something.
if (el.dock) {
  el.dock.addEventListener('click', (event) => {
    const btn = event.target && event.target.closest ? event.target.closest('.dock-btn[data-area]') : null;
    if (!btn || busy) return;
    const area = (btn.dataset.area || '').trim();
    if (!area) return;
    haptic(HAPTIC.start);
    T.record('navigate', { nav: 'dock', name: area });
    unlockSpeech();
    stopSpeaking();
    openArea(area, (btn.dataset.ask || '').trim());
  });
}
async function openArea(area, fallback) {
  const opened = await semanticCommand('open.area', { area });
  if (opened && opened.ok && Array.isArray(opened.ui) && opened.ui.length) {
    const rendered = window.CrooksUI.render(opened.ui, renderOpts());
    if (rendered.nodes.length) {
      pushContext(rendered.nodes, opened.ui, opened.answer || '');
      el.heard.textContent = '';
      if (opened.answer) el.answer.textContent = opened.answer;
      T.record('render', { name: `dock:${area}`, items: opened.ui.map((i) => i && i.type), ms: opened.served_ms });
      return opened;
    }
  }
  T.record('chip_ask', { text: fallback.slice(0, 60), name: `dock:${area}:fallback`, detail: opened ? String(opened.code || opened.detail || '').slice(0, 80) : 'offline' });
  // A dock tap has a sentence to fall back on, so something DID happen: the caller is told so
  // (§6) rather than being left to treat a working control as a refused one.
  if (fallback) { submit({ text: fallback, session_id: sessionId, turns, speak: el.speakToggle.checked }, false); return { ok: true, fallback: true }; }
  // No sentence to fall back on — the tap came from a half's own way-forward rail rather than
  // from the dock. Say what happened, and leave the ways forward the refusal named on screen:
  // `landing_unavailable` reached the owner as one sentence he could not act on.
  if (opened && (opened.answer || opened.detail)) el.answer.textContent = opened.answer || opened.detail;
  if (opened && opened.changed && Array.isArray(opened.changed.offer) && opened.changed.offer.length) {
    if (historyIndex >= 0) offerBeside(opened.answer || opened.detail || '', opened.changed);
    else drawEmptyHalf({ answer: opened.answer || opened.detail || '', changed: opened.changed });
  }
  // Handed back so the control that was tapped can settle itself (§6, D-6).
  return opened || null;
}
el.backBtn.addEventListener('click', goBack);
if (el.nextBtn) el.nextBtn.addEventListener('click', goNext);
if (el.prevBtn) el.prevBtn.addEventListener('click', goPrevious);
el.recent.addEventListener('click', () => { T.record('navigate', { nav: 'recent', to: history.length - 1 }); if (history.length) showHistory(history.length - 1); });
el.attention.addEventListener('click', () => {
  T.record('navigate', { nav: 'attention_open', count: attentionItems.length });
  if (!window.CrooksUI || !attentionItems.length) return;
  const node = window.CrooksUI.renderItem({ type: 'attention', data: { items: attentionItems } });
  if (node) pushContext([node], [], '');
});

el.settingsBtn.addEventListener('click', () => { unlockSpeech(); loadVoices(); pollHealth(true); el.settings.showModal(); });
el.closeSettings.addEventListener('click', () => el.settings.close());
el.settings.addEventListener('click', (event) => { if (event.target === el.settings) el.settings.close(); });
el.preview.addEventListener('click', () => {
  // Previews the real voice, through the real path — which is also the quickest way to tell
  // whether ElevenLabs is answering from the tablet itself.
  unlockSpeech();
  const previous = el.speakToggle.checked;
  el.speakToggle.checked = true;
  speakAnswer('Twelve orders today, four hundred and thirty pounds.');
  el.speakToggle.checked = previous;
});
el.timingToggle.addEventListener('change', () => { if (!el.timingToggle.checked) el.timings.hidden = true; });
el.streamToggle.checked = store.get('crooks.stream', '1') !== '0';
el.streamToggle.addEventListener('change', () => store.set('crooks.stream', el.streamToggle.checked ? '1' : '0'));
el.resetSession.addEventListener('click', async () => {
  const form = new FormData();
  form.append('session_id', sessionId);
  try { await fetch('/reset', { method: 'POST', body: form }); } catch { /* noop */ }
  sessionId = newSessionId();
  store.set('crooks.session', sessionId);
  turns = 0;
  store.set('crooks.turns', '0');
  history.length = 0;
  historyIndex = -1;
  currentStack = [];
  currentSet = null;
  clear(el.cards);
  renderStackChips();
  renderRecent();
  el.heard.textContent = '';
  el.answer.textContent = '';
  el.errline.textContent = '';
  lastWasError = false;
  el.settings.close();
  setMode('orb');
  setState('SUCCESS', 'New conversation');
  haptic(HAPTIC.done);
  setTimeout(() => { if (!busy && !recording && el.stage.dataset.state === 'SUCCESS') setState('READY'); }, 1400);
});

// M2's diagnostic, kept: records three seconds through the warm stream and reports what the
// backend actually decoded, then plays it back. It never opens the microphone itself — only
// the hold-to-speak press does — so with no live stream it says to hold to speak first.
el.micTest.addEventListener('click', async () => {
  el.settings.close();
  setMode('orb');
  if (!micIsLive()) {
    setState('READY', 'Microphone test', 'Hold to speak once first, then run the test again.');
    return;
  }
  setState('LISTENING', 'Microphone test');
  el.sub.textContent = 'Recording three seconds…';
  try {
    const stream = micStream;
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    const parts = [];
    recorder.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
    recorder.onstop = async () => {
      try {
        const form = new FormData();
        form.append('audio', new Blob(parts, { type: recorder.mimeType }), 'test.webm');
        const response = await fetch('/audio-test', { method: 'POST', body: form });
        if (!response.ok) throw new Error(`backend answered ${response.status}`);
        const data = await response.json();
        setState(data.ok && data.usable ? 'READY' : 'ERROR', data.ok && data.usable ? 'Microphone OK' : 'Microphone problem');
        el.answer.textContent = data.ok
          ? `${data.duration_s}s, ${data.sample_rate}Hz ${data.channels}ch, peak ${data.peak_dbfs}dBFS, RMS ${data.rms_dbfs}dBFS, clipped ${(data.clipped_ratio * 100).toFixed(2)}% (${data.clipped_ms}ms) — ${data.usable ? 'usable' : 'too quiet or clipped'}. Recorded as ${data.mime_type}. Playing back what the backend heard.`
          : `Decode failed: ${data.error}`;
        if (data.ok && data.wav_base64) {
          // Play back exactly what the backend decoded — the M2 "is it intelligible" check.
          const bytes = Uint8Array.from(atob(data.wav_base64), (c) => c.charCodeAt(0));
          const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
          const playback = new Audio(url);
          playback.onended = () => URL.revokeObjectURL(url);
          playback.onerror = () => URL.revokeObjectURL(url);
          playback.play().catch(() => { /* autoplay blocked: the stats still tell the story */ });
        }
      } catch (error) {
        setState('ERROR', 'Microphone test failed');
        el.errline.textContent = String(error && error.message ? error.message : error);
      }
    };
    recorder.start(250);
    setTimeout(() => recorder.stop(), 3000);
  } catch (error) {
    showMicError('Microphone test failed: the microphone could not be recorded.');
  }
});

/* ------------------------------------------------------------- developer */

// Diagnostics and fixtures live behind one clearly labelled switch at the bottom of the sheet,
// "Developer view", off unless it was turned on (GENERATIVE_UI_V1 §4). Turning it on shows the
// developer section and, the first time, loads the fixtures; turning it off hides both again
// and stops the timings line, so nothing of it is left on the owner's screen.
let devBanner = null;
function setDeveloperView(on) {
  el.devToggle.checked = on;
  el.dev.hidden = !on;
  store.set('crooks.dev', on ? '1' : '0');
  if (on) loadDeveloperTools();
  if (devBanner) devBanner.hidden = !on;
  if (!on) { el.timingToggle.checked = false; el.timings.hidden = true; }
}
el.devToggle.addEventListener('change', () => setDeveloperView(el.devToggle.checked));

function loadDeveloperTools() {
  if (devBanner) return;
  const banner = document.createElement('div');
  banner.className = 'dev-banner';
  banner.textContent = 'Developer view · fixtures are not live data';
  document.body.appendChild(banner);
  devBanner = banner;
  const script = document.createElement('script');
  script.src = '/static/fixtures.js';
  script.onload = () => {
    const fixtures = window.CrooksFixtures ? window.CrooksFixtures.list : [];
    for (const fixture of fixtures) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn';
      button.textContent = fixture.label;
      button.addEventListener('click', () => {
        el.settings.close();
        const ui = window.CrooksUI.render(fixture.items, Object.assign(renderOpts(), { fixture: true }));
        if (ui.stack) { currentStack = ui.stack; }
        el.heard.textContent = `Fixture: ${fixture.label}`;
        el.answer.textContent = '';
        if (fixture.id === 'success') setState('SUCCESS');
        else if (fixture.id === 'error') setState('ERROR', ui.errors[0] ? ui.errors[0].title : '');
        else setState('READY');
        pushContext(ui.nodes, fixture.items, `fixture:${fixture.id}`);
      });
      el.devGrid.appendChild(button);
    }
  };
  document.body.appendChild(script);
  el.devText.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || busy) return;
    event.preventDefault();   // closing the sheet moves focus to a button; Enter must not press it
    const text = el.devText.value.trim();
    if (!text) return;
    el.devText.value = '';
    el.settings.close();
    unlockSpeech();
    stopSpeaking();
    submit({ text, session_id: sessionId, turns, speak: el.speakToggle.checked }, false);
  });
}
setDeveloperView(DEV);

/* ------------------------------------------------------------- system layer */

// The Mac is the only server. While it cannot be reached the page is a fixture with nothing
// behind it, so it says so in CROOKS's own words, keeps asking quietly, and comes back on its
// own. /ping costs the Mac nothing and is never cached, so the answer is always the truth.
const PING_TIMEOUT_MS = 4000;
const RECONNECT_MIN_MS = 3000;
const RECONNECT_MAX_MS = 15000;
let reachable = null;            // null until the first answer, then true or false
let reconnectTimer = null;
let reconnectDelay = RECONNECT_MIN_MS;
let pingInFlight = false;

// Nothing is being asked, heard or said. The system layer (offline, refused) may take the
// screen when this holds — a live card is no reason to hide that the Mac has gone.
function quiet() {
  return !busy && !recording && !speakingVia && !pendingStart && !el.settings.open;
}

// Quiet, and no card the owner may be about to tap or has just tapped: what a reload or a
// worker takeover must wait for.
function idle() {
  return quiet() && !liveActionSurface();
}

// A card the owner may be about to tap, or has just tapped. A reload under it would lose
// the tap, or the answer to it.
function liveActionSurface() {
  return Boolean(document.querySelector('.action-surface[data-state="arming"], .action-surface[data-state="armed"], .action-surface[data-state="committing"]'));
}

function setSystem(phase, title, sub, note) {
  el.system.dataset.phase = phase;
  if (title !== undefined) el.systemTitle.textContent = title;
  if (sub !== undefined) el.systemSub.textContent = sub;
  if (note !== undefined) el.systemNote.textContent = note;
}

async function checkReachable() {
  if (pingInFlight) return;
  pingInFlight = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PING_TIMEOUT_MS);
  try {
    const response = await fetch('/ping', { cache: 'no-store', signal: controller.signal });
    if (response.status === 403) { wentRefused(); return; }
    if (!response.ok) throw new Error(`ping ${response.status}`);
    const data = await response.json();
    if (!data.ok) throw new Error('ping not ok');
    wentOnline();
  } catch {
    wentOffline();
  } finally {
    clearTimeout(timer);
    pingInFlight = false;
  }
}

function wentOnline() {
  const wasDown = reachable === false;
  if (wasDown) T.record('connectivity', { state: 'online' });
  reachable = true;
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  reconnectDelay = RECONNECT_MIN_MS;
  setSystem('online');
  if (wasDown) {
    // Back after an outage: the pill, the sheet's rows and the lock all need re-establishing,
    // and a build shipped while we were away should be taken. The microphone waits for the
    // next hold.
    setConn('connecting', 'Connecting');
    pollHealth(true);
    acquireWakeLock();
    if (swRegistration) swRegistration.update().catch(() => {});
  }
}

// The Mac answered, and said no: this tablet's login is not on its allowed list. That is a
// configuration to fix on the Mac, not an outage, and the screen must not call it one.
function wentRefused() {
  if (reachable !== false) T.record('connectivity', { state: 'refused' });
  reachable = false;
  if (quiet()) {
    setSystem('refused', 'Not allowed', "This device's login is not on the server's allowed list.", 'CROOKS_ALLOWED_LOGINS on the server · open /whoami · tap to check again');
  }
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(checkReachable, RECONNECT_MAX_MS);
}

function wentOffline() {
  if (reachable !== false) T.record('connectivity', { state: 'offline' });
  reachable = false;
  // Never over a question in flight, a recording, or the voice mid-sentence: the turn's own
  // error copy covers those, and the layer takes over once the screen is quiet.
  if (quiet()) {
    setSystem('offline', 'System offline', 'Waiting for CLIVE…', 'Checking quietly · tap to check now');
  }
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(checkReachable, reconnectDelay);
  reconnectDelay = Math.min(Math.round(reconnectDelay * 1.6), RECONNECT_MAX_MS);
}

el.system.addEventListener('click', () => { if (reachable === false) { reconnectDelay = RECONNECT_MIN_MS; checkReachable(); } });
window.addEventListener('online', () => { if (reachable !== true) checkReachable(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && reachable === false) checkReachable();
});

/* ------------------------------------------------------------- installed app */

// The service worker keeps the shell — page, scripts, styles, icons — and nothing else, so the
// installed app opens instantly and opens at all when the Mac is away. A newer build installs
// in the background and is taken only when nothing is in progress; the page then reloads
// once onto the shell the new worker has already cached.
const UPDATE_GRACE_MS = 20000;
let swRegistration = null;
let updateWaiting = null;        // a newer build, installed and waiting for an idle moment
let updateApplied = false;       // we asked it to take over; the next controllerchange is ours
let reloadingForUpdate = false;

function applyUpdateWhenIdle() {
  if (!updateWaiting || !idle()) return;
  const worker = updateWaiting;
  updateWaiting = null;
  updateApplied = true;
  worker.postMessage({ type: 'SKIP_WAITING' });
}

function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js').then((registration) => {
    swRegistration = registration;
    if (registration.waiting && navigator.serviceWorker.controller) {
      updateWaiting = registration.waiting;
      applyUpdateWhenIdle();
    }
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      if (!worker) return;
      worker.addEventListener('statechange', () => {
        // Installed behind a running page: a new build is ready. Without a controller it is
        // the first install, and the page is already the current build.
        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
          updateWaiting = worker;
          applyUpdateWhenIdle();
        }
      });
    });
  }).catch(() => { /* the page works without it; only instant, offline startup is lost */ });
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!updateApplied || reloadingForUpdate) return;
    reloadingForUpdate = true;
    location.reload();
  });
}

// The three places a message may appear, handed over once. `mode` is asked rather than
// pushed, because a workspace message drawn while the orb is the screen belongs under the
// caption and the same message drawn beside cards belongs above the deck.
if (window.CrooksNotify) {
  window.CrooksNotify.init({
    document,
    global: el.notesGlobal,
    orbWorkspace: el.notesOrb,
    deckWorkspace: el.notesDeck,
    mode: () => el.body.dataset.mode || 'orb',
    record: (kind, fields) => T.record(kind, fields),
  });
}

wireOrbGestures();
registerServiceWorker();
checkReachable();
acquireWakeLock();
setMode('orb');
setState('READY');

/* ============================================================ compose · begin
 *
 * The email being written (app/families/compose.py). Three things, and the third is the one
 * that mattered on the bench.
 *
 * (a) A keystroke in a field posts `compose.field` — WHICH composer, WHICH field, and the
 *     characters — after 400 ms of quiet. The Mac validates the characters into its own copy
 *     of the email and answers with the card again; the card is swapped in place and the
 *     caret is put back where the thumb left it. That is what makes the typed value safe: the
 *     tablet has posted a value, not an argument, and the arguments of the change are still
 *     built on the Mac from the Mac's copy when a gesture asks for them.
 *
 * (b) A button carrying `data-command` posts that command with `data-args`. Save draft and
 *     Send carry a composer id and "draft" or "send"; the email itself is never on the wire.
 *     Another half of this build adds the same generic handler, so this one is registered
 *     once, under a flag, whichever lands first.
 *
 * (c) Typing must never start a recording, and the hold-to-talk on the dock must still work
 *     with a field focused. The field swallows its own pointer events (web/ui.js), so the
 *     deck's handlers never see them; the keyboard path is closed here, because the space bar
 *     inside an address is a space and not a hold.
 */

// Where the thumb was, per field, so a re-render does not throw the caret to the end.
const composeDebounce = new Map();
const COMPOSE_DEBOUNCE_MS = 400;

// The card a field belongs to: the composer, or any other card the Mac has put precision
// fields on (app/families/_workspace.py draws a discount code, an order and a credit the
// same way). `.card` is on every one of them, and `closest` finds the nearest — so a field
// inside a folded card still redraws the card it is in and not the fold around it.
function composeCardFor(node) {
  return node && node.closest ? node.closest('.card') : null;
}

// A re-render of one card, in place, from the ITEMS the Mac answered with. `pushContext` is
// wrong here — a corrected address is not a new screen, and pushing one would put the composer
// on the back stack once per keystroke.
//
// NAMED FOR THE COMPOSER, and that name is load-bearing. This was `replaceCard`, which is also
// the name the action engine's own card swap had 800 lines above it (now
// `replaceCardNodes(oldNode, newNodes)`, which takes NODES). Two top-level function declarations with one name is not two
// functions: the later one wins for every call site in the file, including
// `settleAction`'s. So every committed change handed its rendered NODES to this, which passed
// them to `CrooksUI.render` as if they were payload items, got nothing back, and returned
// null — leaving the card that had just been applied saying "Applying…" for ever, with the
// change proven on the Mac. That is the visible half of D-1, and the browser run that drives a
// commit with a finger (scripts/browser/email.js) is what found it: no ASGI test can see a
// function name collide.
function replaceComposeCard(oldNode, items) {
  if (!oldNode || !oldNode.parentNode || !window.CrooksUI) return null;
  const rendered = window.CrooksUI.render(items, renderOpts());
  const fresh = rendered.nodes[0];
  if (!fresh) return null;
  oldNode.parentNode.replaceChild(fresh, oldNode);
  // The deck's own copy of what is on screen, so Back and a half-swap redraw the corrected
  // card rather than the one before the correction.
  const entry = history[historyIndex];
  if (entry && Array.isArray(entry.nodes)) {
    const at = entry.nodes.indexOf(oldNode);
    if (at !== -1) entry.nodes[at] = fresh;
  }
  return fresh;
}

async function composeFieldChanged(control) {
  const composeId = control.dataset.compose || '';
  const name = control.dataset.field || '';
  if (!composeId || !name) return;
  const card = composeCardFor(control);
  const caret = typeof control.selectionStart === 'number' ? control.selectionStart : null;
  const value = String(control.value === undefined ? '' : control.value);
  // Which command a keystroke in THIS field posts. The Mac put it on the card
  // (web/ui.js `field`), because the page must not have to know that a discount code's
  // characters go to the discount family and an address's go to the composer. Absent — an
  // older card, a card built before this seam — the composer's own command, which is what
  // every field on the tablet posted before there was a second kind.
  const post = control.dataset.post || 'compose.field';
  const answered = await semanticCommand(post, { compose_id: composeId, field: name, value });
  if (!answered) return;                                   // offline: the field keeps what was typed
  // CONTROL-LOCAL: a rejected value is about the FIELD it was typed into. It used to be a
  // workspace line — a message about the screen, printed for something that happened inside
  // one control, 788px from the thumb that typed it.
  if (!answered.ok) { notifyControl(String(answered.detail || 'That could not be applied.'), control, { tone: 'bad', code: 'field_refused' }); return; }
  if (!Array.isArray(answered.ui) || !answered.ui.length || !card) return;
  const fresh = replaceComposeCard(card, answered.ui);
  if (!fresh) return;
  T.record('compose_field', { name, status: String((answered.changed || {}).status || '') });
  // The owner is still typing into this field. Put the focus and the caret back, or the
  // second character of an address lands at the front of it.
  const again = fresh.querySelector(`[data-field="${name}"] .field-input`) || fresh.querySelector(`.field-input[data-field="${name}"]`);
  if (!again) return;
  try {
    again.focus({ preventScroll: true });
    if (caret !== null && typeof again.setSelectionRange === 'function') again.setSelectionRange(caret, caret);
  } catch { /* a browser that will not move the caret still has the value */ }
}

el.cards.addEventListener('input', (event) => {
  const control = event.target && event.target.closest ? event.target.closest('[data-field].field-input') : null;
  if (!control) return;
  const key = `${control.dataset.compose}:${control.dataset.field}`;
  clearTimeout(composeDebounce.get(key));
  composeDebounce.set(key, setTimeout(() => { composeDebounce.delete(key); composeFieldChanged(control); }, COMPOSE_DEBOUNCE_MS));
});
// Leaving the field, or a picker committing a value, does not wait out the debounce: the
// thumb is on its way to Send.
el.cards.addEventListener('change', (event) => {
  const control = event.target && event.target.closest ? event.target.closest('[data-field].field-input') : null;
  if (!control) return;
  const key = `${control.dataset.compose}:${control.dataset.field}`;
  clearTimeout(composeDebounce.get(key));
  composeDebounce.delete(key);
  composeFieldChanged(control);
});

// (b) One delegated handler for every button that names a semantic command. Guarded because
// another family adds the same one; whichever loads first owns it, and both draw the reply
// the same way.
// What a card wrote on its button, whichever way it wrote it.
//
// Two Phase 3 families each added a delegated handler for [data-command], each guarded by the
// same flag, and they disagreed: one parsed `data-args` as a query string, the other as JSON.
// The guard meant only the first ever ran — so the variant picker's Add button, which writes
// JSON, posted one nonsense key and no order_id, no variant_id and no quantity. It was
// enabled, it looked interactive, and it could not do its job.
//
// One handler now, and it reads both. JSON first because it is unambiguous: a query string
// never starts with `{`, so there is no encoding a card can choose that this gets wrong.
/* An id out of a payload, safe inside an attribute selector. `CSS.escape` where the
   browser has it; otherwise everything outside the id alphabet is dropped, which for a
   `cmp_`/`prop_` id is a no-op and for anything else makes the selector match nothing
   rather than become a different selector. */
function cssEscape(value) {
  const said = String(value == null ? '' : value);
  if (typeof CSS !== 'undefined' && CSS && typeof CSS.escape === 'function') return CSS.escape(said);
  return said.replace(/[^\w-]/g, '');
}

function commandArgs(raw) {
  const text = String(raw || '').trim();
  if (!text) return {};
  if (text.charAt(0) === '{') {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch { /* not JSON after all; fall through to the query string */ }
    return {};
  }
  const args = {};
  for (const [key, value] of new URLSearchParams(text)) args[key] = value;
  return args;
}

if (!window.__crooksCommandDelegate) {
  window.__crooksCommandDelegate = true;
  el.cards.addEventListener('click', async (event) => {
    const button = event.target && event.target.closest ? event.target.closest('[data-command]') : null;
    if (!button || button.disabled) return;
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    const name = (button.dataset.command || '').trim();
    if (!name || busy) return;
    // `data-args` is a query string the MAC put on the card. Only identities and small
    // values travel in it; the Mac decides what they mean, and a name it does not know is
    // refused there.
    const args = commandArgs(button.dataset.args);
    button.disabled = true;
    haptic(HAPTIC.start);
    unlockSpeech();
    stopSpeaking();
    const answered = await semanticCommand(name, args);
    button.disabled = false;
    T.record('command_tap', { command: name, ok: Boolean(answered && answered.ok), code: String((answered || {}).code || '') });
    // CONTROL-LOCAL, not a toast. A refusal is about THIS button, so it belongs beside it,
    // where the thumb already is and where it scrolls with the card. A toast over the dock
    // is a message about the screen, and this is not one.
    if (!answered) { notifyControl('The server did not answer.', button, { tone: 'bad', code: 'offline' }); return; }
    if (!answered.ok) { notifyControl(String(answered.detail || 'That could not be done.'), button, { tone: 'bad', code: codeOf(answered.code, 'command_refused') }); return; }
    /* A card the Mac has just taken away goes off the glass (§19: visual state outranks
       the spoken claim). `compose.discard` answers "Gone. Nothing was saved." and sends
       `changed.discarded` — the composer's own id — and NO `ui`, because there is nothing
       to draw. Nothing here acted on that, so Cancel spoke, the composer stayed exactly
       where it was, and the owner's next tap on it was refused `no_composer`: the Mac had
       discarded it and the screen had not. The click-path gate called it
       "INERT — Cancel does nothing even when activated directly", which was the second tap
       being answered rather than the first being ignored.

       Removed rather than redrawn: a discarded composer has no later state, and `pushContext`
       with an empty deck would push a stop onto the trail for a screen with nothing on it. */
    if (answered.changed && answered.changed.discarded) {
      const gone = String(answered.changed.discarded);
      for (const card of document.querySelectorAll(`#cards [data-compose="${cssEscape(gone)}"]`)) card.remove();
      T.record('render', { name: 'compose_discarded', items: [], id: gone });
    }
    if (Array.isArray(answered.ui) && answered.ui.length && window.CrooksUI) {
      // Onto the screen when the answer carries it on — Add on the variant picker, Save draft
      // on the composer: the order or the thread stays with the card under it (round 12).
      drawTapAnswer(answered.ui, answered.answer || '');
    }
    if (answered.answer) { el.answer.textContent = answered.answer; speakAnswer(answered.answer); }
  });
}

// (c) A field has the keyboard, and the microphone is still the dock's.
//
// Typing cannot start a recording, and it is the DOM that guarantees it rather than a check:
// the hold surface (#talk) is a SIBLING of the deck and not an ancestor, so a key pressed in
// a field never reaches its keydown handler; and in context mode #talk is the 112px band at
// the bottom, so it does not sit over the card either. The field swallows its own pointer
// events (web/ui.js), so a finger in it never reaches the deck's delegated click handler or
// its gesture probe.
//
// What does need doing is the other direction. A thumb landing on the dock while a field has
// focus must send what was typed BEFORE the turn redraws the deck — otherwise the last few
// characters of an address are lost to the debounce — and must put the keyboard away, or the
// answer arrives behind it. Capture, so it runs before onHoldStart; it stops nothing, so the
// hold itself behaves exactly as it does anywhere else.
el.talk.addEventListener('pointerdown', () => {
  const active = document.activeElement;
  if (!active || !active.classList || !active.classList.contains('field-input')) return;
  const key = `${active.dataset.compose}:${active.dataset.field}`;
  if (composeDebounce.has(key)) {
    clearTimeout(composeDebounce.get(key));
    composeDebounce.delete(key);
    composeFieldChanged(active);
  }
  active.blur();
}, true);


/* ============================================================== compose · end */

// ------------------------------------------------------------------ boot
// After every declaration above. The Split control is on the idle screen from the first
// frame — one chip while there is one half — and a reload asks the Mac for the screen it
// still holds rather than starting from nothing.
drawBranchBar();
restoreWorkspace();

/* A card's own command is handled by the single delegate above (`commandArgs`). A second,
   never-reachable copy of it lived here behind the same guard flag; it is gone. The
   collision branch improved that copy — control-local notifications instead of a toast —
   and those improvements were carried up into the live delegate, not lost with the dead
   one. */

// ------------------------------------------------------------------ mobile alpha
// The one door web/alpha.js uses into this file: ask CLIVE a typed question through the same
// submit() the microphone and the developer field use, so a typed turn is an ordinary turn.
window.CliveAlpha = {
  ask(text) {
    const value = String(text || '').trim();
    if (!value || busy) return Promise.resolve(false);
    unlockSpeech();
    stopSpeaking();
    return Promise.resolve(submit({ text: value, session_id: sessionId, turns, speak: el.speakToggle.checked }, false)).then(() => true);
  },
  isBusy() { return busy; },
  // The conversation this page is in: the home lists objectives to it, and a record held and put
  // on a screen names it (web/alpha.js, web/lift.js).
  sessionId() { return sessionId; },
};

// ------------------------------------------------------------------ the ask bar
/* The phone's one bar, drawn by web/alpha.js as `#ask-bar`: a tap types, a hold speaks.
 *
 * The tap is the bar's own click, which web/alpha.js answers by opening the keyboard. The hold
 * is decided HERE, where the microphone lives, so web/alpha.js never reaches the recorder. The
 * recorder starts ASK_HOLD_MS after the touch rather than on it — that wait is what lets a tap
 * be a tap without opening the microphone — and the click that follows a hold is swallowed so
 * it cannot also open the keyboard. Sliding the thumb ASK_CANCEL_PX away before lifting drops
 * the recording; the bar shows it (`data-cancel`) before the thumb lifts.
 *
 * The bar is a <button>, so the touch machine files it as a control, never as voice: the
 * orb's and #talk's pointers are untouched by this. */
const ASK_HOLD_MS = 260;
const ASK_CANCEL_PX = 90;
let askPress = null;
let askSwallowUntil = 0;
document.addEventListener('pointerdown', (event) => {
  const bar = event.target && event.target.closest ? event.target.closest('#ask-bar') : null;
  if (!bar || askPress || (event.button !== undefined && event.button !== 0)) return;
  try { bar.setPointerCapture(event.pointerId); } catch { /* unsupported */ }
  unlockSpeech();   // inside the gesture, so the answer can be spoken
  const press = { id: event.pointerId, x: event.clientX, y: event.clientY, bar, held: false, live: false, cancel: false };
  askPress = press;
  press.timer = setTimeout(() => {
    if (askPress !== press) return;
    press.held = true;
    if (busy || recording || pendingStart) { if (busy) showBusyHint(); return; }
    stopSpeaking();   // the voice must not be recorded answering itself
    acquireWakeLock();
    if (live) live.pointerDown();
    press.live = true;
    T.record('hold', { phase: 'start', target: 'ask_bar', state: busy ? 'busy' : 'ready' });
    setState('LISTENING');
    startRecording();
  }, ASK_HOLD_MS);
});
document.addEventListener('pointermove', (event) => {
  const press = askPress;
  if (!press || !press.live || event.pointerId !== press.id) return;
  const away = Math.hypot(event.clientX - press.x, event.clientY - press.y) > ASK_CANCEL_PX;
  if (away === press.cancel) return;
  press.cancel = away;
  press.bar.dataset.cancel = away ? 'true' : 'false';
});
function endAskPress(event) {
  const press = askPress;
  if (!press || event.pointerId !== press.id) return;
  askPress = null;
  clearTimeout(press.timer);
  press.bar.dataset.cancel = 'false';
  if (press.held) askSwallowUntil = Date.now() + 700;
  if (press.live) stopRecording(press.cancel || event.type === 'pointercancel');
  T.record('ask_bar', { outcome: !press.held ? 'type' : !press.live ? 'busy' : press.cancel ? 'slid_away' : event.type === 'pointercancel' ? 'cancelled' : 'sent' });
}
document.addEventListener('pointerup', endAskPress);
document.addEventListener('pointercancel', endAskPress);
document.addEventListener('click', (event) => {
  if (Date.now() > askSwallowUntil) return;
  if (!event.target || !event.target.closest || !event.target.closest('#ask-bar')) return;
  askSwallowUntil = 0;
  event.preventDefault();
  event.stopPropagation();
}, true);
// The capture went away with no lift (the bar redrawn, Android taking the gesture): nothing
// was said on purpose, so nothing is sent, and the next press is not refused as a second one.
document.addEventListener('lostpointercapture', (event) => {
  if (askPress && event.pointerId === askPress.id) endAskPress({ pointerId: event.pointerId, type: 'pointercancel' });
});

// ------------------------------------------------------------------ the phone home, observed
/* What the owner does on the phone's home and its sheets (web/alpha.js), for a test session:
 * which row, which shortcut, which control — never a title. web/alpha.js marks its controls
 * with data attributes and never reaches the telemetry itself; this reads the marks. */
document.addEventListener('click', (event) => {
  const node = event.target && event.target.closest ? event.target.closest('[data-alpha]') : null;
  if (!node) return;
  T.record('alpha_tap', {
    target: node.dataset.alpha,
    attention: node.dataset.attention || undefined,
    control: node.closest('#alpha-sheet') ? 'sheet' : node.closest('#alpha-home') ? 'home' : 'composer',
  });
});

/* A request the server refused or could not answer, whoever made it. The page's own reads
 * report their failures in their own words; the phone home's (objectives, support) only
 * flashed a line on the glass, and a test session saw nothing. Path and status only. */
if (typeof window.fetch === 'function') {
  const pageFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const request = pageFetch(input, init);
    request.then((response) => {
      if (response && !response.ok) {
        let path = '';
        try { path = new URL(response.url || String(input), location.href).pathname; } catch { path = ''; }
        if (path && !path.startsWith('/telemetry')) T.record('http_error', { path: path.slice(0, 80), status: response.status });
      }
    }, () => {});
    return request;
  };
}
