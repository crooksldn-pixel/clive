/* The live words on the app page (web/app.js), with the real web/live-voice.js and the real
 * web/telemetry.js, run under Node (node --test tests/web/live-words-page.test.js).
 *
 * Round 9, findings C-03, G-01 and G-02. What is proved, end to end through a hold:
 *   - The live words are display only. They reach the three text nodes marked `data-spoken` and
 *     nothing else: not a telemetry payload, not a storage write, not the console, not a request
 *     to the Mac (the question sent is the recording, and the form carries nothing else), and
 *     not the address bar. Once the Mac has said what it heard, or the turn is over, or the hold
 *     came to nothing, they are off the bar and live-voice.js has let them go (C-03).
 *   - The single-use key goes to one place: the socket's address. It is in no telemetry payload,
 *     storage write, console line or request to the Mac, and the page lets live-voice.js make
 *     no request but POST /voice/live (G-01).
 *   - When /turn answers before any /state poll has seen the Mac's transcript, the bar shows
 *     the question actually asked, not the live words; a turn that heard nothing clears them
 *     (G-02).
 *
 * app.js is one page script with no module boundary, so, as tests/web/mic.test.js does, this
 * runs the real text of the parts that matter, cut out by their own markers: the microphone and
 * the live words, the recorder, and the turn (state polling, submit, sendAudio). Everything else
 * is a stand-in the test controls: the socket, the recorder, the clock's timers and the Mac.
 * Nothing here touches Node's fetch, WebSocket, FormData or Blob.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shim = require('./dom-shim.js');

const WEB = path.join(__dirname, '..', '..', 'web');
const SOURCE = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
const LIVE_VOICE = fs.readFileSync(path.join(WEB, 'live-voice.js'), 'utf8');
const TELEMETRY = fs.readFileSync(path.join(WEB, 'telemetry.js'), 'utf8');

// What the real DOM has and the shared stand-in does not; added here, for this file's run only.
shim.Element.prototype.removeAttribute = function removeAttribute(name) { delete this.attributes[name]; };
shim.Element.prototype.hasAttribute = function hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); };
shim.Element.prototype.getBoundingClientRect = function getBoundingClientRect() { return { width: 320, height: 22 }; };

// From the line that starts `start` up to (not including) the line that holds `end`.
function cut(start, end) {
  const from = SOURCE.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer has ${JSON.stringify(start)}`);
  const to = SOURCE.indexOf(end, from + start.length);
  assert.notEqual(to, -1, `web/app.js no longer has ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  return SOURCE.slice(from, SOURCE.lastIndexOf('\n', to) + 1);
}

const PARTS = [
  cut('const MIC_CONSTRAINTS', '// Everything this page says goes through here'),
  cut('function showMicError(message)', ' context deck */'),
  cut('// While a turn is in flight, ask the backend what it is actually doing.', '/* ------------------------------------------------------------------ events */'),
].join('\n');

const settle = async (times = 6) => { for (let i = 0; i < times; i++) await new Promise((resolve) => setImmediate(resolve)); };

// What the owner says, and what the Mac made of the recording: a customer's name in both.
const LIVE = 'Refund Jane Doe';
const ASKED = "Refund Jane Doe's order 1042";
const KEY = 'single-use-stand-in-key-for-the-page';
const SECRETS = ['Jane', '1042', KEY];

function boot(options) {
  const opts = options || {};
  const make = (tag) => shim.document.createElement(tag);
  const nodes = { 'ask-bar': make('button'), 'ask-words': make('span'), 'ask-heard': make('span') };
  nodes['ask-words'].setAttribute('data-spoken', 'true');
  nodes['ask-heard'].setAttribute('data-spoken', 'true');
  const el = {
    body: make('body'), sub: make('p'), heard: make('p'), answer: make('p'), errline: make('p'),
    talk: make('button'), talkLabel: make('span'), timings: make('p'), speakToggle: { checked: false },
  };
  if (opts.alpha !== false) el.body.classList.add('alpha');

  // Timers the test runs when it chooses. Nothing runs on its own.
  const timers = [];
  let nextId = 1;
  const addTimer = (fn, ms, repeat) => { const id = nextId++; timers.push({ id, fn, ms, repeat, live: true }); return id; };
  const dropTimer = (id) => { for (const timer of timers) if (timer.id === id) timer.live = false; };

  // Every way something could leave the page, recorded.
  const out = { telemetry: [], stored: [], logged: [], requests: [], addressBar: [], states: [], rendered: [] };

  // The Mac. /turn answers when the test says so.
  const mac = { turn: null, state: { known: true, state: 'TRANSCRIBING', detail: null } };
  function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }
  const fetch = async (url, init) => {
    out.requests.push({ url: String(url), init: init || {} });
    if (url === '/voice/live') {
      return { ok: true, status: 200, json: async () => ({ token: KEY, url: 'wss://example.test/v1/speech-to-text/realtime', params: { model_id: 'scribe_v2_realtime', commit_strategy: 'manual' }, expires_in_s: 10 }) };
    }
    if (url === '/turn') {
      mac.turn = deferred();
      const answer = await mac.turn.promise;
      return { ok: answer.status === undefined || answer.status < 400, status: answer.status || 200, json: async () => answer.body };
    }
    if (String(url).startsWith('/state/')) return { ok: true, status: 200, json: async () => mac.state };
    return { ok: false, status: 404, json: async () => ({}) };
  };

  // The realtime socket, the microphone, its recorder.
  const sockets = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.sent = []; this.closed = false; sockets.push(this); }
    send(data) { if (this.closed) throw new Error('closed'); this.sent.push(JSON.parse(data)); }
    close() { this.closed = true; }
  }
  const taps = [];
  const ctx = {
    sampleRate: 16000, destination: {},
    createGain: () => ({ gain: { value: 1 }, connect() {}, disconnect() {} }),
    createScriptProcessor: () => { const node = { onaudioprocess: null, connect() {}, disconnect() {} }; return node; },
  };
  const audio = {
    context: ctx, hasMic: true,
    tapMic(node) { taps.push(node); return true; }, untapMic() {},
    resume() {}, attachMic() {}, detachMic() {}, micLevel: () => 0.4,
  };
  const recorders = [];
  class FakeRecorder {
    constructor(stream, options) { this.mimeType = (options && options.mimeType) || 'audio/webm'; this.state = 'inactive'; recorders.push(this); }
    static isTypeSupported(type) { return type === 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; }
  }
  class FakeBlob { constructor(parts, init) { this.parts = parts; this.type = init && init.type; this.size = parts.reduce((n, p) => n + (p.size || 0), 0); } }
  class FakeForm { constructor() { this.entries = []; } append(name, value, filename) { this.entries.push([name, value, filename]); } }
  const track = { readyState: 'live', addEventListener() {}, stop() {} };
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] };

  const recordingConsole = {};
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) recordingConsole[level] = (...args) => out.logged.push(args.map(String).join(' '));
  const storage = () => ({ setItem: (k, v) => out.stored.push(`${k}=${v}`), getItem: () => null, removeItem() {} });
  const location = {};
  for (const part of ['href', 'hash', 'search', 'pathname']) {
    Object.defineProperty(location, part, { get: () => '/', set: (value) => out.addressBar.push(String(value)) });
  }

  const document = {
    hidden: false, visibilityState: 'visible',
    getElementById: (id) => nodes[id] || null,
    addEventListener() {}, removeEventListener() {},
    createElement: make,
  };
  const sandbox = {
    console: recordingConsole, Uint8Array, Int16Array, Float32Array, DataView, Map, Set, WeakMap, Promise, JSON, Math, Date, Number, String, Object, Array, Error, TypeError, URLSearchParams,
    AbortController, Buffer, btoa: (text) => Buffer.from(text, 'binary').toString('base64'),
    setTimeout: (fn, ms) => addTimer(fn, ms, false), clearTimeout: dropTimer,
    setInterval: (fn, ms) => addTimer(fn, ms, true), clearInterval: dropTimer,
    document, location, localStorage: storage(), sessionStorage: storage(),
    navigator: { mediaDevices: { getUserMedia: async () => stream }, permissions: undefined, vibrate() { return true; } },
    isSecureContext: true, MediaRecorder: FakeRecorder, Blob: FakeBlob, FormData: FakeForm, WebSocket: FakeSocket,
    fetch,
    audio, el, orb: null, live: null,
    REDUCED: { matches: true }, LABELS: { LISTENING: ['Listening', 'Release to send'] },
    TOO_SHORT: 'That was too short — hold while you speak.', HAPTIC: { start: 1, release: 1, done: [1], error: [1] },
    TRANSIENT_ERRORS: ['speech', 'empty', 'audio_too_large'], LONG_THINK_MS: 6000,
    // The page's own state, as the rest of app.js keeps it.
    mediaRecorder: null, chunks: [], recording: false, busy: false, pendingStart: false, recordingStartedAt: 0, lastRecordingMs: 0,
    sessionId: 's1', turns: 0, currentTurnId: '', pendingBuild: null, lastWasError: false, lastErrorTitle: '',
    focusedBranch: '', turnStartedAt: 0, statePoll: null, historyIndex: 0, history: [{ entities: [] }],
    decks: new Map(), glass: { turn: '', cursor: 0, applied: 0, stale: false },
    store: { get: (key, fallback) => fallback, set: (key, value) => out.stored.push(`${key}=${value}`) },
    // And what it calls elsewhere.
    setState: (state) => { out.states.push(state); }, haptic() {}, watchForSpeech() {}, stopWatchingForSpeech() {},
    notify() {}, settleGlass() {}, speakAnswer() {}, cancelTurn() {}, liveActionSurface: () => null,
    noteBranch() {}, applyBranches() {}, settleProposals() {}, sayAndStay() {}, renderTurn: (data) => out.rendered.push(data),
    noteUseful() {}, renderTimings() {}, reconcileActions() {}, setConn() {}, checkReachable() {}, endJobs() {},
    applyUpdateWhenIdle() {}, applyWorkspace() {}, noteRunningTool() {}, detailWords: () => '',
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(TELEMETRY, sandbox, { filename: 'telemetry.js' });
  vm.runInContext(LIVE_VOICE, sandbox, { filename: 'live-voice.js' });
  // What app.js hands live-voice.js, kept so a test can drive the page's own callbacks.
  const wired = {};
  const realCreate = sandbox.CrooksLiveVoice.create;
  sandbox.CrooksLiveVoice.create = (options) => { Object.assign(wired, options); return realCreate(options); };
  sandbox.T = sandbox.CrooksTelemetry;
  sandbox.T.configure({ test_session: 'ts_live_words', screens: false });
  sandbox.T._setTransport((body) => out.telemetry.push(body));
  vm.runInContext(`'use strict';\n${PARTS}`, sandbox, { filename: 'app.js (microphone, live words, recorder and turn parts)' });

  const h = {
    sandbox, el, nodes, out, mac, sockets, recorders, timers, wired,
    get socket() { return sockets[sockets.length - 1]; },
    // A hold begins: the recorder starts and the live words ask for their key.
    async press() { await sandbox.startRecording(); await settle(); },
    // What the microphone hears, through the tap on it.
    speak(seconds) {
      const tap = taps[taps.length - 1];
      const block = new Float32Array(Math.round(16000 * seconds)).fill(0.2);
      if (tap && tap.onaudioprocess) tap.onaudioprocess({ inputBuffer: { getChannelData: () => block } });
    },
    say(message) { if (this.socket.onmessage) this.socket.onmessage({ data: JSON.stringify(message) }); },
    // The thumb lifts; the recorder hands over `bytes` of audio and stops.
    async release(bytes) {
      const recorder = recorders[recorders.length - 1];
      recorder.ondataavailable({ data: { size: bytes } });
      sandbox.stopRecording(false);
      recorder.onstop();
      await settle();
    },
    async answer(body, status) { mac.turn.resolve({ body, status }); await settle(); },
    // One look at /state, as the poll's interval would take it.
    async poll() {
      for (const timer of timers.filter((t) => t.live && t.repeat)) timer.fn();
      await settle();
    },
    bar() {
      return {
        words: nodes['ask-words'].textContent, wordsLines: nodes['ask-bar'].dataset.words,
        heard: nodes['ask-heard'].textContent, heardShown: nodes['ask-bar'].dataset.heard,
      };
    },
    // Everything that left the page, as one string, for looking through.
    leaked() {
      sandbox.T.flush(false);
      const requests = out.requests.map((r) => {
        const body = r.init.body;
        const form = body && body.entries ? body.entries.map(([k, v]) => `${k}=${typeof v === 'object' ? `[blob ${v.size}]` : v}`).join('&') : '';
        return `${r.url} ${typeof body === 'string' ? body : form}`;
      });
      return { telemetry: out.telemetry.join('\n'), stored: out.stored.join('\n'), logged: out.logged.join('\n'), requests: requests.join('\n'), addressBar: out.addressBar.join('\n') };
    },
  };
  return h;
}

async function holdAndSpeak(h) {
  const before = h.sockets.length;
  await h.press();
  assert.equal(h.sockets.length, before + 1, 'the live words opened a socket for this hold');
  h.socket.onopen();
  h.speak(0.3);
  h.say({ message_type: 'partial_transcript', text: LIVE });
  assert.equal(h.bar().words, LIVE, 'the live words are on the capsule while he holds');
}

// ------------------------------------------------------------------ G-02: the question asked, on the bar

test('when /turn answers before any /state poll saw the transcript, the bar shows the question asked (G-02)', async () => {
  const h = boot();
  await holdAndSpeak(h);
  await h.release(6000);
  assert.equal(h.bar().heard, `“${LIVE}”`, 'between the release and the answer, the live words stand for what was heard');
  assert.equal(h.out.requests.filter((r) => r.url.startsWith('/state/')).length, 0, 'no poll has run');
  await h.answer({ session_id: 's1', turns: 1, question: ASKED, answer: 'Done.', ui: [] });
  assert.equal(h.el.heard.textContent, `“${ASKED}”`);
  assert.deepEqual(h.bar(), { words: '', wordsLines: 'false', heard: `“${ASKED}”`, heardShown: 'true' },
    'the bar says what the Mac heard, and the live words are gone from it');
  assert.equal(h.socket.closed, true, 'and the live words\' socket is let go');
  // A committed word from the socket after that changes nothing.
  h.say({ message_type: 'committed_transcript', text: LIVE });
  assert.equal(h.bar().heard, `“${ASKED}”`);
  assert.equal(h.bar().words, '');
});

test('a spoken turn that heard nothing clears the live words from the bar rather than keep them (G-02)', async () => {
  const h = boot();
  await holdAndSpeak(h);
  await h.release(6000);
  await h.answer({ session_id: 's1', turns: 1, question: '', answer: 'I did not catch that.', ui: [], error_kind: 'empty' });
  assert.deepEqual(h.bar(), { words: '', wordsLines: 'false', heard: '', heardShown: 'false' });
});

test('when a /state poll sees the transcript first, the bar shows it at once, and the answer keeps it (G-02)', async () => {
  const h = boot();
  await holdAndSpeak(h);
  await h.release(6000);
  h.mac.state = { known: true, state: 'THINKING', heard: ASKED };
  await h.poll();
  assert.deepEqual(h.bar(), { words: '', wordsLines: 'false', heard: `“${ASKED}”`, heardShown: 'true' });
  assert.equal(h.socket.closed, true);
  await h.answer({ session_id: 's1', turns: 1, question: ASKED, answer: 'Done.', ui: [] });
  assert.equal(h.bar().heard, `“${ASKED}”`);
});

test('a turn that fails leaves no live words on the bar (C-03)', async () => {
  for (const status of [500, 403]) {
    const h = boot();
    await holdAndSpeak(h);
    await h.release(6000);
    await h.answer({}, status);
    assert.deepEqual(h.bar(), { words: '', wordsLines: 'false', heard: '', heardShown: 'false' }, `status ${status}`);
  }
});

test('a hold too short to be a question leaves no live words on the bar (C-03)', async () => {
  const h = boot();
  await holdAndSpeak(h);
  await h.release(200);            // under 800 bytes: not sent
  assert.equal(h.out.requests.filter((r) => r.url === '/turn').length, 0);
  assert.deepEqual(h.bar(), { words: '', wordsLines: 'false', heard: '', heardShown: 'false' });
  assert.equal(h.socket.closed, true);
});

// ------------------------------------------------------------------ C-03 and G-01: where the words and the key go

test('the live words and the key reach no telemetry, storage, console, request or address bar (C-03, G-01)', async () => {
  const h = boot();
  // One hold whose socket fails with an error that names her, and one whose words are committed.
  await holdAndSpeak(h);
  h.say({ message_type: 'Jane Doe 1042_error', error: `${LIVE}, order 1042` });
  await h.release(6000);
  await h.answer({ session_id: 's1', turns: 1, question: ASKED, answer: 'Done.', ui: [] });
  await holdAndSpeak(h);
  await h.release(6000);
  h.say({ message_type: 'committed_transcript', text: LIVE });
  await h.answer({ session_id: 's1', turns: 2, question: ASKED, answer: 'Done.', ui: [] });

  const leaked = h.leaked();
  assert.ok(leaked.telemetry.includes('live_transcript') && leaked.telemetry.includes('turn_submitted'), 'telemetry was on and sent');
  for (const [where, text] of Object.entries(leaked)) {
    for (const secret of SECRETS) assert.ok(!text.includes(secret), `${JSON.stringify(secret)} reached ${where}: ${text}`);
  }
  // The question sent is the recording and nothing more.
  for (const turn of h.out.requests.filter((r) => r.url === '/turn')) {
    assert.deepEqual(turn.init.body.entries.map(([name]) => name), ['audio', 'session_id', 'turns', 'speak']);
    assert.equal(turn.init.body.entries[0][1].size, 6000);
  }
  // The page's only requests: the key and the question, once per hold. No other destination.
  assert.deepEqual(h.out.requests.map((r) => r.url), ['/voice/live', '/turn', '/voice/live', '/turn']);
  assert.deepEqual(h.out.requests.filter((r) => r.url === '/voice/live').map((r) => [r.init.method, r.init.body, r.init.cache]),
    [['POST', '{}', 'no-store'], ['POST', '{}', 'no-store']]);
  // The key went to one place: the socket's address, one socket per hold.
  assert.equal(h.sockets.length, 2);
  for (const socket of h.sockets) assert.equal(new URL(socket.url).searchParams.get('token'), KEY);
  // Telemetry's live_transcript events carry this file's own words and numbers only.
  const events = h.out.telemetry.flatMap((body) => JSON.parse(body).events).filter((e) => e.kind === 'live_transcript');
  assert.equal(events.length, 2);
  for (const event of events) {
    const keys = Object.keys(event).filter((k) => !['kind', 't', 'seq', 'session_id', 'turn_id'].includes(k));
    for (const key of keys) assert.ok(['outcome', 'reason', 'ms', 'partials', 'count'].includes(key), key);
  }
  assert.deepEqual(events.map((e) => [e.outcome, e.reason]), [['error', 'provider_error'], ['committed', undefined]]);
});

test('the callbacks the page hands live-voice.js let it ask for its key, and record its own words, and nothing else (G-01)', async () => {
  const h = boot();
  // Its fetch: POST /voice/live reaches the Mac; anything else is refused before it leaves.
  for (const url of ['/turn', '/telemetry', 'https://elsewhere.example/collect', '/voice/live?token=x']) {
    await assert.rejects(h.wired.fetch(url, { method: 'POST', body: LIVE }), url);
  }
  assert.equal(h.out.requests.length, 0, 'none of them was made');
  await h.wired.fetch('/voice/live', { method: 'POST', body: '{}' });
  assert.deepEqual(h.out.requests.map((r) => r.url), ['/voice/live']);
  // Its record: the live_transcript event alone, in fixed words and whole numbers.
  h.wired.record('turn_submitted', { text: LIVE });
  h.wired.record('live_transcript', { outcome: LIVE, reason: `${LIVE}_error`, ms: LIVE, text: LIVE, token: KEY, count: 3 });
  const sent = h.leaked().telemetry;
  const events = h.out.telemetry.flatMap((body) => JSON.parse(body).events).filter((e) => e.kind !== 'session_joined');
  assert.deepEqual(events.map((e) => e.kind), ['live_transcript']);
  assert.deepEqual([events[0].outcome, events[0].reason, events[0].count, events[0].ms, events[0].text, events[0].token], ['other', 'other', 3, undefined, undefined, undefined]);
  for (const secret of SECRETS) assert.ok(!sent.includes(secret), secret);
  // Its words: to the bar, and only there.
  h.wired.onWords(LIVE);
  assert.equal(h.bar().words, LIVE);
});

test('on the tablet the line under the orb carries the words while he holds, marked so a copy of the screen masks them', async () => {
  const h = boot({ alpha: false });
  await holdAndSpeak(h);
  assert.equal(h.el.sub.textContent, LIVE);
  assert.equal(h.el.sub.hasAttribute('data-spoken'), true);
  await h.release(6000);
  assert.equal(h.el.sub.hasAttribute('data-spoken'), false, 'the line goes back to saying what the machine is doing');
});

test('in the whole page, no script puts the live words or the key into storage, the address bar or a log', () => {
  // The words live in three variables of app.js's live section and nowhere else in the page.
  const section = cut('/* ------------------------------------------------- live words and the real waveform */',
    '/* ------------------------------------------- live words and the real waveform · end */');
  for (const name of ['store.set', 'localStorage', 'sessionStorage', 'console.', 'history.', 'location', 'T.record(']) {
    const uses = section.split(name).length - 1;
    assert.equal(uses, name === 'T.record(' ? 1 : 0, `the live-words section uses ${name}`);
  }
  // No page script writes the address bar at all.
  for (const file of fs.readdirSync(WEB).filter((name) => name.endsWith('.js'))) {
    const text = fs.readFileSync(path.join(WEB, file), 'utf8');
    assert.ok(!/history\.(pushState|replaceState)\(/.test(text), `${file} writes the address bar`);
  }
});
