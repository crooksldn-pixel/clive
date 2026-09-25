/* When the page asks for the microphone (web/app.js), under Node.
 *
 * On the owner's iPhone the browser kept asking "would like to access the microphone" over the
 * orders screen: the page opened the microphone on the first touch anywhere, on every return to
 * the app and after every reconnect, and an iPhone home-screen app asks again each time. The
 * rule proved here: only the hold-to-speak press asks; a tap elsewhere, a return and a
 * reconnect never do; once granted, later presses share the one live stream; an ended track is
 * forgotten; and the page warms on load only where the permission query says "granted".
 *
 * The page is one long script. The pieces that decide this are taken out of the real file (not
 * copied) and run together in one context, with everything else they touch stood in for, so
 * what is proved is what ships.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const { document: shim, Element } = require('./dom-shim');

const APP = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'app.js'), 'utf8');

function piece(start, end) {
  const from = APP.indexOf(start);
  assert.notEqual(from, -1, `web/app.js no longer contains ${start}`);
  const to = typeof end === 'function' ? end(from) : APP.indexOf(end, from);
  assert.ok(to > from, `web/app.js: no end found for the piece starting ${start}`);
  return APP.slice(from, to);
}
// Up to, not including, the section header that names `title`.
const beforeHeader = (title) => (from) => APP.lastIndexOf('/*', APP.indexOf(`${title} */`, from));
// A top-level function, to its closing brace at column 0.
const toClosingBrace = (from) => APP.indexOf('\n}\n', from) + 3;

const PIECES = [
  // The stream, its release, and the one warm-up on load.
  piece('const MIC_CONSTRAINTS', 'function pickMimeType()'),
  // The press and the release.
  piece('async function startRecording()', beforeHeader('context deck')),
  // Hidden and back again.
  piece('// Android drops the lock whenever the page is hidden', beforeHeader('voices')),
  // Back after an outage.
  piece('function wentOnline()', toClosingBrace),
].join('\n');

// The page's own state that those pieces read and write, declared where the page declares it.
const PRELUDE = `'use strict';
let recording = false;
let busy = false;
let pendingStart = false;
let mediaRecorder = null;
let chunks = [];
let recordingStartedAt = 0;
let lastRecordingMs = 0;
let reachable = true;
let reconnectTimer = null;
let reconnectDelay = 0;
const RECONNECT_MIN_MS = 1000;
const swRegistration = null;
const audio = null;
const orb = null;
const live = null;
const TOO_SHORT = 'Too short.';
const HAPTIC = { start: [1], release: [1], error: [1] };
`;

const TRAILER = `
function micState() { return { stream: micStream, recording, pendingStart }; }
function dropConnection() { reachable = false; }
`;

// A MediaStream with one audio track. The track is a shim element, so it can be sent `ended`.
function fakeStream(n) {
  const track = new Element('track');
  track.kind = 'audio';
  track.readyState = 'live';
  track.stop = () => { track.readyState = 'ended'; };
  return { id: `stream-${n}`, track, getAudioTracks: () => [track], getTracks: () => [track] };
}

// `permission`: what navigator.permissions.query says — 'granted', 'prompt', 'denied', or
// 'unreliable' (it rejects); absent means the browser has no permission query at all.
function boot(options) {
  const permission = (options || {}).permission;
  const opened = [];       // every getUserMedia call, with the stream it handed back
  const recorders = [];    // every MediaRecorder the page built, with the stream it was given
  const errors = [];       // anything the page said was wrong with the microphone
  const queried = [];

  const page = new Element('#document');
  page.visibilityState = 'visible';
  const win = new Element('#window');
  win.isSecureContext = true;

  const navigator = {
    mediaDevices: {
      getUserMedia(constraints) {
        const stream = fakeStream(opened.length + 1);
        opened.push({ constraints, stream });
        return Promise.resolve(stream);
      },
    },
  };
  if (permission) {
    navigator.permissions = {
      query(descriptor) {
        queried.push(descriptor && descriptor.name);
        if (permission === 'unreliable') return Promise.reject(new TypeError('not a permission name here'));
        return Promise.resolve({ state: permission });
      },
    };
  }

  class FakeRecorder {
    constructor(stream, settings) {
      this.stream = stream;
      this.settings = settings;
      this.mimeType = '';
      this.state = 'inactive';
      recorders.push(this);
    }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; }
  }

  const nothing = () => {};
  const sandbox = {
    console, setTimeout, clearTimeout,
    document: page,
    window: win,
    navigator,
    MediaRecorder: FakeRecorder,
    el: {
      talk: shim.createElement('button'), talkLabel: shim.createElement('span'),
      sub: shim.createElement('div'), errline: shim.createElement('div'),
    },
    T: { record: nothing },
    pickMimeType: () => '',
    showMicError: (message) => { errors.push(message); },
    setState: nothing, setConn: nothing, setSystem: nothing, haptic: nothing,
    watchForSpeech: nothing, stopWatchingForSpeech: nothing, stopSpeaking: nothing,
    acquireWakeLock: nothing, pollHealth: nothing, reconcileActions: nothing, sendAudio: nothing,
  };
  vm.createContext(sandbox);
  vm.runInContext(PRELUDE + PIECES + TRAILER, sandbox, { filename: 'web/app.js (microphone pieces)' });

  const tapElsewhere = () => {
    for (const type of ['pointerdown', 'touchstart', 'pointerup', 'click']) {
      page.dispatch(type, { pointerId: 7, button: 0 });
      win.dispatch(type, { pointerId: 7, button: 0 });
    }
  };
  const setVisible = (visible) => {
    page.visibilityState = visible ? 'visible' : 'hidden';
    page.hidden = !visible;
    page.dispatch('visibilitychange');
  };
  return {
    opened, recorders, errors, queried,
    state: () => sandbox.micState(),
    press: () => sandbox.startRecording(),
    release: () => sandbox.stopRecording(),
    tapElsewhere,
    hide: () => setVisible(false),
    show: () => setVisible(true),
    reconnect: () => { sandbox.dropConnection(); sandbox.wentOnline(); },
  };
}

// Let every promise the page started run out.
async function settle() {
  for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

test('a tap elsewhere, a return to the app and a reconnect never ask for the microphone', async () => {
  for (const permission of [undefined, 'prompt', 'denied', 'unreliable']) {
    const page = boot({ permission });
    await settle();
    page.tapElsewhere();
    page.hide();
    page.show();
    page.reconnect();
    page.tapElsewhere();
    await settle();
    assert.equal(page.opened.length, 0, `permission ${permission}: getUserMedia was called without a press`);
  }
});

test('nor after the owner has granted it once: only a press ever asks', async () => {
  const page = boot({ permission: 'prompt' });
  await settle();
  await page.press();
  page.release();
  assert.equal(page.opened.length, 1);

  page.tapElsewhere();
  page.reconnect();
  await settle();
  assert.equal(page.opened.length, 1, 'a tap or a reconnect asked again');

  // Hidden still lets go of the microphone; coming back does not take it again.
  page.hide();
  assert.equal(page.state().stream, null, 'a hidden page kept the microphone');
  page.show();
  page.tapElsewhere();
  page.reconnect();
  await settle();
  assert.equal(page.opened.length, 1, 'returning to the app asked for the microphone');

  // The next press is what asks.
  await page.press();
  assert.equal(page.opened.length, 2);
  assert.deepEqual(page.errors, []);
});

test('the press asks inside the touch itself, before it yields', async () => {
  const page = boot();
  const pending = page.press();
  assert.equal(page.opened.length, 1, 'getUserMedia must be called in the same task as the press');
  await pending;
  assert.equal(page.recorders.length, 1);
  assert.equal(page.recorders[0].stream, page.opened[0].stream);
  assert.equal(page.state().recording, true);
  assert.deepEqual(page.errors, []);
});

test('two presses share one stream', async () => {
  const page = boot({ permission: 'prompt' });
  await settle();
  await page.press();
  page.release();
  await page.press();
  page.release();
  assert.equal(page.opened.length, 1, 'the second press opened the microphone again');
  assert.equal(page.recorders.length, 2);
  assert.equal(page.recorders[0].stream, page.recorders[1].stream);
  assert.equal(page.state().stream, page.opened[0].stream);
  assert.deepEqual(page.errors, []);
});

test('where the permission query reports granted, the page warms on load and the press reuses it', async () => {
  const page = boot({ permission: 'granted' });
  await settle();
  assert.deepEqual(page.queried, ['microphone']);
  assert.equal(page.opened.length, 1);
  await page.press();
  page.release();
  assert.equal(page.opened.length, 1, 'the press opened a second stream beside the warm one');
  assert.equal(page.recorders[0].stream, page.opened[0].stream);
});

test('an ended track is forgotten, so the next press opens a fresh stream', async () => {
  const page = boot();
  await page.press();
  page.release();
  const first = page.opened[0].stream;
  first.track.readyState = 'ended';
  first.track.dispatch('ended');
  assert.equal(page.state().stream, null);
  await page.press();
  assert.equal(page.opened.length, 2);
  assert.equal(page.recorders[1].stream, page.opened[1].stream);
  assert.deepEqual(page.errors, []);
});

// ------------------------------------------------------------------ the whole page, as source

const LINES = APP.split('\n');

// The top-level statement a position in app.js belongs to: the nearest line above it that
// starts at column 0 with a letter.
function headOf(index) {
  for (let i = APP.slice(0, index).split('\n').length - 1; i >= 0; i -= 1) {
    if (/^[A-Za-z]/.test(LINES[i])) return LINES[i];
  }
  return '';
}

test('across the whole page, getUserMedia is reached only from the hold-to-speak press', () => {
  // Each name, and the only top-level statements allowed to call it. The two that are not the
  // press are the warm-up on load where permission is already granted, and the settings sheet's
  // microphone test, which the owner opens to use the microphone.
  const allowed = {
    getUserMedia: ['async function ensureMicStream('],
    ensureMicStream: ['async function ensureMicStream(', 'async function startRecording(', 'function warmMic(', "el.micTest.addEventListener('click'"],
    warmMic: ['function warmMic(', 'if (navigator.permissions'],
    // The hold on the talk region or the orb, the same hold kept through a turn in flight,
    // and Space or Enter held on the talk control.
    startRecording: ['async function startRecording(', 'function onHoldStart(', 'function cancelTurnAndListen(', "el.talk.addEventListener('keydown'"],
  };
  for (const [name, heads] of Object.entries(allowed)) {
    const found = [...APP.matchAll(new RegExp(`\\b${name}\\(`, 'g'))].map((match) => headOf(match.index));
    assert.ok(found.length > 0, `${name} is no longer in the page`);
    for (const head of found) {
      assert.ok(heads.some((prefix) => head.startsWith(prefix)), `${name}() is reached from: ${head}`);
    }
  }
  assert.equal(APP.match(/\bgetUserMedia\(/g).length, 1);
});
