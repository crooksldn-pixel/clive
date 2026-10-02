/* The microphone is asked for by the hold-to-speak press and by nothing else (web/app.js);
 * web/alpha.js, loaded with it, never asks at all.
 *
 * On the owner's iPhone every getUserMedia from the home-screen app can be another "would
 * like to access the microphone", so a tap on the orders screen, a return to the app and a
 * reconnect must never open it; once a press has opened it, the next press records through
 * the same stream; and an ended track (Android, when another app takes the microphone) is
 * forgotten so the next press opens a fresh one.
 *
 * app.js is one page script with no module boundary, so this runs the real text of the parts
 * that matter — the visibility handler, the microphone, the recorder, the hold surfaces, the
 * microphone test and the reconnect loop — cut out by their section markers and run together
 * against stand-ins for everything else. The real touch machine (web/touch.js) decides who
 * owns each pointer. Nothing here touches Node's fetch, Response or FormData: loading those
 * compiles WebAssembly, which a checker with a capped address space cannot do.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shim = require('./dom-shim.js');
const Touch = require(path.join(__dirname, '..', '..', 'web', 'touch.js'));

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');

// From the line that starts `start` up to (not including) the line that holds `end`.
function cut(start, end) {
  const from = SOURCE.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer has ${JSON.stringify(start)}`);
  const to = SOURCE.indexOf(end, from + start.length);
  assert.notEqual(to, -1, `web/app.js no longer has ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  return SOURCE.slice(from, SOURCE.lastIndexOf('\n', to) + 1);
}

const PARTS = [
  cut('// Android drops the lock whenever the page is hidden', ' voices */'),
  cut('const MIC_CONSTRAINTS', '// Everything this page says goes through here'),
  cut('function showMicError(message)', ' context deck */'),
  cut('/* Every pointer on the page is classified here', '// What the owner touched on the cards'),
  cut("el.micTest.addEventListener('click'", ' developer */'),
  cut('const PING_TIMEOUT_MS', ' installed app */'),
].join('\n');

// Listeners by type, with the capture flag kept, for `document` and `window`.
function bus() {
  const listeners = [];
  return {
    add(type, fn, options) {
      const capture = options === true || Boolean(options && options.capture);
      listeners.push({ type, fn, capture, once: Boolean(options && options.once) });
    },
    remove(type, fn) {
      const i = listeners.findIndex((l) => l.type === type && l.fn === fn);
      if (i !== -1) listeners.splice(i, 1);
    },
    fire(type, event, capture) {
      for (const l of listeners.slice()) {
        if (l.type !== type || (capture !== undefined && l.capture !== capture)) continue;
        if (l.once) listeners.splice(listeners.indexOf(l), 1);
        l.fn(event);
      }
    },
  };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

// `permission` is what navigator.permissions.query answers; undefined means there is no query.
function boot(permission) {
  const asked = [];        // every getUserMedia call
  const streams = [];      // every stream it handed over
  const recorders = [];    // every MediaRecorder the page built
  const states = [];
  const calls = { setConn: [], pollHealth: [], reconcile: 0 };
  const network = { up: true };
  const docBus = bus();
  const winBus = bus();

  function openStream() {
    const listeners = {};
    const track = {
      readyState: 'live',
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      stop() { track.readyState = 'ended'; },
      // What Android does when another app takes the microphone.
      end() { track.readyState = 'ended'; for (const fn of listeners.ended || []) fn(); },
    };
    const stream = { track, getAudioTracks: () => [track], getTracks: () => [track] };
    streams.push(stream);
    return stream;
  }

  class FakeRecorder {
    constructor(stream, options) {
      this.stream = stream;
      this.mimeType = (options && options.mimeType) || '';
      this.state = 'inactive';
      recorders.push(this);
    }
    static isTypeSupported(type) { return type === 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; }
  }

  const make = (tag) => shim.document.createElement(tag);
  const el = {
    talk: make('button'), orbFrame: make('div'), talkLabel: make('span'),
    sub: make('p'), errline: make('p'), answer: make('p'), micTest: make('button'),
    system: make('div'), systemTitle: make('p'), systemSub: make('p'), systemNote: make('p'),
    settings: { open: false, close() {} },
  };
  const document = {
    hidden: false, visibilityState: 'visible', activeElement: null,
    addEventListener: docBus.add, removeEventListener: docBus.remove,
    querySelector: () => null,
    createElement: make,
  };
  // What app.js's hitUnder reads off the DOM, told directly: the two hold surfaces are the
  // voice target, a button anywhere else is a control, and anything else is bare page.
  const hitUnder = (event) => {
    const voice = event.target === el.talk || event.target === el.orbFrame;
    return {
      pointerId: event.pointerId, x: event.clientX, y: event.clientY, button: event.button,
      voice, approval: '', control: !voice && event.target.tagName === 'BUTTON' ? 'button' : '', scroll: false,
    };
  };

  const sandbox = {
    console, Blob, URL, AbortController, Uint8Array, atob,
    // Unreferenced, so a stray timer (the microphone test's three seconds) never holds the run open.
    setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); if (t && t.unref) t.unref(); return t; },
    clearTimeout,
    FormData: class { append() {} },
    document,
    navigator: {
      mediaDevices: { getUserMedia: async (constraints) => { asked.push(constraints); return openStream(); } },
      permissions: permission === undefined ? undefined : { query: async () => ({ state: permission }) },
      vibrate() { return true; },
    },
    MediaRecorder: FakeRecorder,
    isSecureContext: true,
    addEventListener: winBus.add,
    removeEventListener: winBus.remove,
    fetch: async () => {
      if (!network.up) throw new TypeError('network down');
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
    CrooksTouch: Touch,
    el,
    audio: null, orb: null, live: null,
    T: { record() {}, flush() {} },
    HAPTIC: { start: 1, release: 1, done: [1], error: [1] },
    TOO_SHORT: 'That was too short — hold while you speak.',
    pointers: Touch.create(),
    hitUnder,
    // The page's own state, as the rest of app.js keeps it.
    mediaRecorder: null, chunks: [], recording: false, busy: false, pendingStart: false,
    lastWasError: false, lastErrorTitle: '', speakingVia: null, recordingStartedAt: 0, lastRecordingMs: 0,
    focusedBranch: '', branches: [], turnAbort: null, turnStartedAt: 0, swRegistration: null,
    // And what it calls elsewhere.
    setState: (state, label, sub) => { states.push({ state, label, sub }); },
    setMode() {},
    setConn: (state) => { calls.setConn.push(state); },
    pollHealth: (fresh) => { calls.pollHealth.push(Boolean(fresh)); },
    reconcileActions: () => { calls.reconcile += 1; },
    acquireWakeLock() {}, stopSpeaking() {}, unlockSpeech() {}, haptic() {},
    watchForSpeech() {}, stopWatchingForSpeech() {}, sendAudio() {},
    cancelTurn() {}, cancelForm() { return null; }, mergeOrb() {},
  };
  sandbox.window = sandbox;
  vm.runInNewContext(`'use strict';\n${PARTS}`, sandbox, { filename: 'app.js (microphone parts)' });

  // A pointer as the browser delivers it: the document's capture listeners, the element's
  // own, then the document's bubble listeners.
  function pointer(type, target, pointerId) {
    const detail = { pointerId, button: 0, clientX: 300, clientY: 700 };
    const event = Object.assign({ type, target, preventDefault() {} }, detail);
    docBus.fire(type, event, true);
    target.dispatch(type, detail);
    docBus.fire(type, event, false);
  }
  return {
    sandbox, el, asked, streams, recorders, states, calls, network,
    press: (target, id) => pointer('pointerdown', target, id),
    release: (target, id) => pointer('pointerup', target, id),
    tap(target, id) { pointer('pointerdown', target, id); pointer('pointerup', target, id); },
    visible(yes) {
      document.hidden = !yes;
      document.visibilityState = yes ? 'visible' : 'hidden';
      docBus.fire('visibilitychange', { type: 'visibilitychange' });
    },
    online: () => winBus.fire('online', { type: 'online' }),
  };
}

test('in the whole page, getUserMedia has one caller, reached from the press and the granted load', () => {
  // Every script the page loads, web/alpha.js among them: only app.js names getUserMedia.
  const web = path.join(__dirname, '..', '..', 'web');
  const callers = fs.readdirSync(web).filter((name) => name.endsWith('.js'))
    .filter((name) => fs.readFileSync(path.join(web, name), 'utf8').includes('getUserMedia'));
  assert.deepEqual(callers, ['app.js']);
  assert.equal(SOURCE.split('getUserMedia(').length - 1, 1);
  const lines = (name) => SOURCE.split('\n').map((line) => line.trim())
    .filter((line) => line.includes(`${name}(`) && !/^(async )?function /.test(line));
  assert.deepEqual(lines('ensureMicStream'), [
    'ensureMicStream().catch(() => { /* the press will report the real error */ });',
    'const stream = micIsLive() ? micStream : await ensureMicStream();',
  ]);
  assert.deepEqual(lines('warmMic'), [".then((status) => { if (status && status.state === 'granted') warmMic(); })"]);
});

// web/alpha.js is loaded with the shell, so the rule covers it too. It never opens the
// microphone: it has no media call of its own, never presses a hold surface, and its one door
// into app.js, window.CliveAlpha, asks a typed question that reaches no part of the microphone.
test('web/alpha.js never asks for the microphone, itself or through app.js', () => {
  const ALPHA = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'alpha.js'), 'utf8');
  const MIC = ['getUserMedia', 'mediaDevices', 'getDisplayMedia', 'MediaRecorder',
    'ensureMicStream', 'warmMic', 'micStream', 'startRecording'];
  for (const name of [...MIC, 'talk', 'orb-frame', 'mic-test', 'dispatchEvent', '.click(']) {
    assert.ok(!ALPHA.includes(name), `web/alpha.js has ${JSON.stringify(name)}`);
  }
  // Its second door, round 12: window.CliveObjectiveCards draws an objective's shape
  // (web/objective-cards.js), and that file is held to the same rule as this one.
  // Objectives by touch (B): window.CliveHorizon draws the next six weeks and each row's mark
  // (web/horizon.js), window.CliveDistances moves between the three distances (web/distances.js),
  // and window.CliveHome is what those two may read and do. Both files are held to the rule too.
  assert.deepEqual([...new Set(ALPHA.match(/\bwindow\.\w+/g))].sort(),
    ['window.CliveAlpha', 'window.CliveDistances', 'window.CliveHome', 'window.CliveHorizon', 'window.CliveObjectiveCards']);
  const CARDS = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'objective-cards.js'), 'utf8');
  for (const name of [...MIC, 'talk', 'orb-frame', 'mic-test', 'dispatchEvent', '.click(', 'CliveAlpha']) {
    assert.ok(!CARDS.includes(name), `web/objective-cards.js has ${JSON.stringify(name)}`);
  }
  const HORIZON = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'horizon.js'), 'utf8');
  for (const name of [...MIC, 'talk', 'orb-frame', 'mic-test', 'dispatchEvent', '.click(', 'CliveAlpha']) {
    assert.ok(!HORIZON.includes(name), `web/horizon.js has ${JSON.stringify(name)}`);
  }
  const DISTANCES = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'distances.js'), 'utf8');
  for (const name of [...MIC, 'mic-test', 'dispatchEvent', '.click(', 'CliveAlpha']) {
    assert.ok(!DISTANCES.includes(name), `web/distances.js has ${JSON.stringify(name)}`);
  }
  // It names the voice target once, as what a pinch must never start on.
  assert.deepEqual(DISTANCES.match(/talk|orb-frame/g), ['talk', 'orb-frame']);
  assert.ok(DISTANCES.includes("const VOICE = '#talk, #orb-frame';"));
  const homeAt = ALPHA.indexOf('window.CliveHome = {');
  assert.notEqual(homeAt, -1);
  const home = ALPHA.slice(homeAt, ALPHA.indexOf('\n  };', homeAt));
  for (const name of MIC) assert.ok(!home.includes(name), `window.CliveHome reaches ${name}`);
  // Round 12: it also reads which conversation the page is in, to list objectives to it (web/lift.js
  // puts them on screens). A string, and nothing near the microphone: the loop below holds the door.
  assert.deepEqual([...new Set(ALPHA.match(/\bCliveAlpha\.\w+/g))].sort(), ['CliveAlpha.ask', 'CliveAlpha.isBusy', 'CliveAlpha.sessionId']);

  const door = cut('window.CliveAlpha = {', '\n};');
  assert.match(door, /submit\(\{ text: value, [^\n]*\}, false\)/, 'a typed ask is a text turn');
  const submit = cut('async function submit(body, isAudio)', '\n}\n');
  for (const name of MIC) {
    assert.ok(!door.includes(name), `window.CliveAlpha reaches ${name}`);
    assert.ok(!submit.includes(name), `submit() reaches ${name}`);
  }
});

test('a tap elsewhere on the page never asks for the microphone', async () => {
  const page = boot('prompt');
  await settle();
  const card = shim.document.createElement('button');   // a row on the orders screen
  const bare = shim.document.createElement('div');      // the page between the cards
  page.tap(card, 1);
  page.tap(bare, 2);
  page.tap(card, 3);
  await settle();
  assert.equal(page.asked.length, 0, 'a tap that was not a hold opened the microphone');
  assert.equal(page.recorders.length, 0);
});

test('a return to the app never asks for the microphone, before or after a press', async () => {
  const page = boot('prompt');
  await settle();
  page.visible(false);
  page.visible(true);
  await settle();
  assert.equal(page.calls.reconcile, 1, 'the return was seen');
  assert.equal(page.asked.length, 0, 'coming back to the app opened the microphone');

  // Granted by a press, let go when the page hid, and not reopened by coming back.
  page.press(page.el.talk, 1);
  await settle();
  page.release(page.el.talk, 1);
  assert.equal(page.asked.length, 1);
  page.visible(false);
  assert.equal(page.streams[0].track.readyState, 'ended', 'the microphone is let go while hidden');
  page.visible(true);
  await settle();
  assert.equal(page.asked.length, 1, 'coming back to the app reopened the microphone');
});

test('a reconnect never asks for the microphone', async () => {
  const page = boot('prompt');
  await settle();
  page.network.up = false;
  await page.sandbox.checkReachable();
  assert.equal(page.el.system.dataset.phase, 'offline');
  page.network.up = true;
  page.online();
  await settle();
  assert.equal(page.el.system.dataset.phase, 'online');
  assert.deepEqual(page.calls.setConn, ['connecting'], 'the reconnect was taken');

  // And the other way back: the Mac went away while the app was hidden.
  page.network.up = false;
  await page.sandbox.checkReachable();
  page.visible(false);
  page.network.up = true;
  page.visible(true);
  await settle();
  assert.equal(page.el.system.dataset.phase, 'online');
  assert.deepEqual(page.calls.setConn, ['connecting', 'connecting']);
  assert.equal(page.asked.length, 0, 'reconnecting opened the microphone');
});

test('two presses share one stream: the first asks, the second records through it', async () => {
  const page = boot('prompt');
  await settle();
  page.press(page.el.talk, 1);
  assert.equal(page.asked.length, 1, 'the hold is what asks');
  await settle();
  assert.equal(page.sandbox.recording, true);
  page.release(page.el.talk, 1);
  assert.equal(page.sandbox.recording, false);

  page.press(page.el.orbFrame, 2);
  // The warm path: the recorder starts inside the touch, with nothing awaited.
  assert.equal(page.sandbox.recording, true);
  page.release(page.el.orbFrame, 2);
  await settle();
  assert.equal(page.asked.length, 1, 'the second press asked again');
  assert.equal(page.recorders.length, 2);
  assert.equal(page.recorders[0].stream, page.recorders[1].stream);
  assert.equal(page.recorders[0].stream, page.streams[0]);
});

test('an ended track is forgotten, so the next press opens a fresh stream', async () => {
  const page = boot('prompt');
  await settle();
  page.press(page.el.talk, 1);
  await settle();
  page.release(page.el.talk, 1);
  page.streams[0].track.end();
  page.press(page.el.talk, 2);
  await settle();
  page.release(page.el.talk, 2);
  assert.equal(page.asked.length, 2);
  assert.equal(page.recorders[1].stream, page.streams[1]);
});

test('the page warms the microphone on load only where permission is reported granted', async () => {
  for (const permission of [undefined, 'prompt', 'denied']) {
    const page = boot(permission);
    await settle();
    assert.equal(page.asked.length, 0, `warmed on load with permission ${permission}`);
  }
  const page = boot('granted');
  await settle();
  assert.equal(page.asked.length, 1);
  page.press(page.el.talk, 1);
  assert.equal(page.sandbox.recording, true, 'the first press records through the warm stream');
  page.release(page.el.talk, 1);
  await settle();
  assert.equal(page.asked.length, 1);
  assert.equal(page.recorders[0].stream, page.streams[0]);
});

test('the microphone test never opens the microphone: it uses the live stream or says to hold first', async () => {
  const page = boot('prompt');
  await settle();
  page.el.micTest.dispatch('click');
  await settle();
  assert.equal(page.asked.length, 0, 'the microphone test opened the microphone');
  assert.equal(page.recorders.length, 0);
  assert.match(String(page.states[page.states.length - 1].sub), /Hold to speak/);

  page.press(page.el.talk, 1);
  await settle();
  page.release(page.el.talk, 1);
  page.el.micTest.dispatch('click');
  await settle();
  assert.equal(page.asked.length, 1);
  assert.equal(page.recorders.length, 2);
  assert.equal(page.recorders[1].stream, page.streams[0]);
});
