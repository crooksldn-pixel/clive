/* The live words and the real waveform (web/live-voice.js), run under Node
 * (node --test tests/web/live-voice.test.js).
 *
 * What is proved: the microphone's blocks become 16 kHz little-endian PCM16 whether the context
 * runs at 48 or 44.1 kHz, whatever the block sizes; a chunk is the message the realtime API
 * documents and nothing more; what is said while the socket opens is kept and sent the moment it
 * opens; partial words show and give way to the committed ones; an error, a refusal or a cancel
 * ends the words quietly and takes the tap down; and the waveform is drawn from the analyser's
 * values and nothing else, so a quiet room is a line that does not move.
 *
 * Everything the browser would provide is a stand-in the test controls: the context and its
 * nodes, the socket, the fetch, the clock and the frames. Nothing here touches Node's fetch or
 * WebSocket.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const FILE = path.join(__dirname, '..', '..', 'web', 'live-voice.js');
const SOURCE = fs.readFileSync(FILE, 'utf8');
const LV = require(FILE);

const settle = async (times = 4) => { for (let i = 0; i < times; i++) await new Promise((resolve) => setImmediate(resolve)); };

// ------------------------------------------------------------------ helpers

function sine(rate, seconds, hz, amplitude) {
  const out = new Float32Array(Math.round(rate * seconds));
  for (let i = 0; i < out.length; i++) out[i] = amplitude * Math.sin((2 * Math.PI * hz * i) / rate);
  return out;
}

// Feeds `samples` through `push` in awkward block sizes, as a real tap would hand them over.
function inBlocks(push, samples, sizes) {
  const parts = [];
  let at = 0;
  let k = 0;
  while (at < samples.length) {
    const size = sizes[k++ % sizes.length];
    parts.push(push(samples.subarray(at, at + size)));
    at += size;
  }
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Int16Array(total);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

function crossings(pcm) {
  let n = 0;
  for (let i = 1; i < pcm.length; i++) if ((pcm[i - 1] < 0) !== (pcm[i] < 0)) n += 1;
  return n;
}

function peak(pcm) { let p = 0; for (const v of pcm) p = Math.max(p, Math.abs(v)); return p; }

// ------------------------------------------------------------------ resampling

for (const rate of [48000, 44100]) {
  test(`resampling ${rate / 1000} kHz to 16 kHz PCM16 keeps the length, the pitch and the level`, () => {
    const input = sine(rate, 1, 440, 0.5);
    const out = inBlocks(LV.createResampler(rate, 16000), input, [128, 1000, 333, 2048, 7]);
    assert.ok(out instanceof Int16Array);
    assert.ok(Math.abs(out.length - 16000) <= 1, `one second is 16000 samples, got ${out.length}`);
    // 440 Hz crosses zero 880 times a second, at any sample rate.
    assert.ok(Math.abs(crossings(out) - 880) <= 4, `crossings ${crossings(out)}`);
    // Half scale stays about half scale: the box filter barely touches a voice's frequencies.
    assert.ok(Math.abs(peak(out) - 0.5 * 32767) < 0.05 * 32767, `peak ${peak(out)}`);
  });

  test(`resampling ${rate / 1000} kHz does not depend on how the blocks were cut`, () => {
    const input = sine(rate, 0.25, 300, 0.8);
    const whole = LV.createResampler(rate)(input);
    const cut = inBlocks(LV.createResampler(rate), input, [128, 5, 999]);
    assert.deepEqual(Array.from(cut), Array.from(whole));
  });
}

test('full scale, clipping and 16 kHz itself', () => {
  const same = LV.createResampler(16000, 16000)(new Float32Array([0, 1, -1, 2, -2, 0.5]));
  assert.deepEqual(Array.from(same), [0, 32767, -32768, 32767, -32768, 16384]);
  // Three 48 kHz samples make one 16 kHz sample: their average.
  assert.deepEqual(Array.from(LV.createResampler(48000)(new Float32Array([0.3, 0.3, 0.3, -0.6, -0.6, -0.6]))), [9830, -19661]);
});

test('the bytes are little-endian 16-bit, whatever the machine', () => {
  const bytes = LV.pcmBytes(new Int16Array([1, -2, 0x1234]));
  assert.deepEqual(Array.from(bytes), [0x01, 0x00, 0xfe, 0xff, 0x34, 0x12]);
});

// ------------------------------------------------------------------ the chunk

test('a chunk is the documented message and nothing more', () => {
  const bytes = LV.pcmBytes(new Int16Array([100, -100, 32767, -32768]));
  const middle = JSON.parse(LV.chunkMessage(bytes, false));
  assert.deepEqual(Object.keys(middle).sort(), ['audio_base_64', 'commit', 'message_type']);
  assert.equal(middle.message_type, 'input_audio_chunk');
  assert.equal(middle.commit, false);
  assert.deepEqual(Array.from(Buffer.from(middle.audio_base_64, 'base64')), Array.from(bytes));
  assert.equal(JSON.parse(LV.chunkMessage(bytes, true)).commit, true);
  assert.equal(LV.CHUNK_BYTES, 3200, '100 ms of 16 kHz mono PCM16');
});

// A stand-in for the single-use key, as long as a key is and named for what it is.
const KEY = 'single-use-stand-in-key';

test('the socket address is the one the Mac gave, with its query and the key, and never a keyterm', () => {
  const url = LV.socketUrl({
    token: KEY, url: 'wss://example.test/v1/speech-to-text/realtime',
    params: { model_id: 'scribe_v2_realtime', audio_format: 'pcm_16000', language_code: 'en', commit_strategy: 'manual', keyterms: 'CROOKS' },
  });
  const parsed = new URL(url);
  assert.equal(`${parsed.protocol}//${parsed.host}${parsed.pathname}`, 'wss://example.test/v1/speech-to-text/realtime');
  assert.deepEqual(Object.fromEntries(parsed.searchParams), {
    model_id: 'scribe_v2_realtime', audio_format: 'pcm_16000', language_code: 'en', commit_strategy: 'manual', token: KEY,
  });
  assert.equal(LV.socketUrl({ token: KEY, url: 'https://example.test/', params: {} }), '', 'only a wss: address is opened');
  assert.equal(LV.socketUrl({ url: 'wss://example.test/' }), '', 'no key, no socket');
  assert.equal(LV.socketUrl(null), '');
});

// ------------------------------------------------------------------ the session, with stand-ins

function fakeAudio(options) {
  const opts = options || {};
  const log = { tapped: [], untapped: [], gains: [], nodes: [], modules: [] };
  const ctx = {
    sampleRate: opts.rate || 48000,
    state: 'running',
    destination: { name: 'destination' },
    createGain() {
      const gain = { gain: { value: 1 }, to: [], connect(node) { this.to.push(node); }, disconnect() { this.to = []; } };
      log.gains.push(gain);
      return gain;
    },
    createScriptProcessor(size) {
      const node = { kind: 'script', size, to: [], onaudioprocess: null, connect(x) { this.to.push(x); }, disconnect() { this.to = []; } };
      log.nodes.push(node);
      return node;
    },
  };
  if (opts.worklet) {
    ctx.audioWorklet = { async addModule(url) { log.modules.push(url); if (opts.workletFails) throw new Error('refused'); } };
  }
  const audio = {
    context: opts.noContext ? null : ctx,
    hasMic: opts.noMic ? false : true,
    tapMic(node) { log.tapped.push(node); return true; },
    untapMic(node) { log.untapped.push(node); },
  };
  return { audio, ctx, log };
}

class FakeWorkletNode {
  constructor(ctx, name, options) {
    this.kind = 'worklet';
    this.name = name;
    this.options = options;
    this.to = [];
    const posted = [];
    this.port = { onmessage: null, posted, postMessage(message) { posted.push(message); } };
    FakeWorkletNode.made.push(this);
  }
  connect(x) { this.to.push(x); }
  disconnect() { this.to = []; }
}
FakeWorkletNode.made = [];

function sockets() {
  const made = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.sent = []; this.closed = false; made.push(this); }
    send(data) { if (this.closed) throw new Error('closed'); this.sent.push(JSON.parse(data)); }
    close() { this.closed = true; }
    open() { if (this.onopen) this.onopen({}); }
    say(message) { if (this.onmessage) this.onmessage({ data: JSON.stringify(message) }); }
  }
  return { FakeSocket, made };
}

function fakeFetch(answer) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    if (answer instanceof Error) throw answer;
    return { ok: answer.status >= 200 && answer.status < 300, status: answer.status, json: async () => answer.body };
  };
  fn.calls = calls;
  return fn;
}

const GRANTED = {
  status: 200,
  body: {
    token: KEY, url: 'wss://example.test/v1/speech-to-text/realtime',
    params: { model_id: 'scribe_v2_realtime', audio_format: 'pcm_16000', language_code: 'en', commit_strategy: 'manual' },
    expires_in_s: 10,
  },
};

function harness(options) {
  const opts = options || {};
  const fake = fakeAudio(opts);
  const net = sockets();
  const words = [];
  const records = [];
  const timers = [];
  let t = 10000;
  const fetch = opts.fetch || fakeFetch(opts.answer || GRANTED);
  const live = LV.create({
    audio: fake.audio,
    fetch,
    WebSocket: net.FakeSocket,
    AudioWorkletNode: opts.worklet ? FakeWorkletNode : undefined,
    Blob: class { constructor(parts, init) { this.parts = parts; this.type = init && init.type; } },
    URL: { createObjectURL: () => 'blob:crooks-live-tap', revokeObjectURL() {} },
    now: () => t,
    setTimeout: (fn, ms) => { timers.push({ fn, ms, at: t + ms, live: true }); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].live = false; },
    onWords: (text) => words.push(text),
    record: (kind, fields) => records.push({ kind, fields }),
  });
  return {
    live, fake, net, words, records, timers, fetch,
    tick(ms) { t += ms; },
    fireTimers() { for (const timer of timers.splice(0)) if (timer.live) timer.fn(); },
    // The clock moved on by `ms`, and every timer that fell due on the way ran, in order.
    advance(ms) {
      const until = t + ms;
      for (;;) {
        const due = timers.filter((timer) => timer.live && timer.at <= until).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        t = Math.max(t, due.at);
        due.live = false;
        due.fn();
      }
      t = until;
    },
    get socket() { return net.made[net.made.length - 1]; },
    // What the microphone says, through whichever tap was built.
    speak(seconds) {
      const rate = fake.ctx.sampleRate;
      const samples = sine(rate, seconds, 220, 0.3);
      const tap = fake.log.tapped[fake.log.tapped.length - 1];
      for (let at = 0; at < samples.length; at += 2048) {
        const block = samples.slice(at, at + 2048);
        if (tap.kind === 'script') { if (tap.onaudioprocess) tap.onaudioprocess({ inputBuffer: { getChannelData: () => block } }); } else if (tap.port.onmessage) tap.port.onmessage({ data: block });
      }
    },
  };
}

test('the tap hangs off the one microphone source, through a gain of zero, and asks for nothing', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  assert.equal(h.fake.log.tapped.length, 1, 'one tap, on the source audio-viz already has');
  const node = h.fake.log.tapped[0];
  assert.equal(node.kind, 'script', 'no worklet here: the ScriptProcessor fallback');
  const gain = h.fake.log.gains[0];
  assert.equal(gain.gain.value, 0, 'pulled, never heard');
  assert.deepEqual(node.to, [gain]);
  assert.deepEqual(gain.to, [h.fake.ctx.destination]);
  // The page's one microphone and its recorder are app.js's; this file names neither.
  for (const name of ['getUserMedia', 'mediaDevices', 'MediaRecorder', 'createMediaStreamSource', 'new AudioContext', 'webkitAudioContext']) {
    assert.ok(!SOURCE.includes(name), `web/live-voice.js names ${name}`);
  }
  h.live.cancel();
  assert.deepEqual(h.fake.log.untapped, [node], 'the tap comes down with the words');
});

test('an AudioWorklet is used where there is one, loaded once per context from a Blob URL', async () => {
  FakeWorkletNode.made = [];
  const h = harness({ worklet: true });
  h.live.begin();
  await settle();
  assert.deepEqual(h.fake.log.modules, ['blob:crooks-live-tap']);
  assert.equal(h.fake.log.tapped[0].kind, 'worklet');
  assert.equal(h.fake.log.tapped[0].options.channelCount, 1);
  h.speak(0.2);
  h.socket.open();
  assert.ok(h.socket.sent.length >= 1, 'the worklet feeds the socket');
  h.live.cancel();
  assert.deepEqual(h.fake.log.tapped[0].port.posted, ['stop'], 'the processor is told to stop');
  h.live.begin();
  await settle();
  assert.equal(h.fake.log.modules.length, 1, 'the module is not loaded twice into one context');
  h.live.cancel();
});

test('a worklet that will not load falls back to a ScriptProcessor', async () => {
  const h = harness({ worklet: true, workletFails: true });
  h.live.begin();
  await settle();
  assert.equal(h.fake.log.tapped[0].kind, 'script');
  h.live.cancel();
});

test('what is said while the socket opens is kept, and sent the moment it opens', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  assert.equal(h.fetch.calls.length, 1);
  assert.equal(h.fetch.calls[0].url, '/voice/live');
  assert.equal(h.fetch.calls[0].init.method, 'POST');
  assert.ok(h.socket, 'the socket is being opened');
  assert.match(h.socket.url, /^wss:\/\/example\.test\/v1\/speech-to-text\/realtime\?/);
  assert.equal(new URL(h.socket.url).searchParams.get('token'), KEY);
  h.speak(0.5);                        // half a second before it opens
  assert.equal(h.socket.sent.length, 0, 'nothing can be sent before it opens');
  h.socket.open();
  const flushed = h.socket.sent.slice();
  assert.equal(flushed.length, 5, 'half a second is five 100 ms chunks');
  for (const message of flushed) {
    assert.equal(message.message_type, 'input_audio_chunk');
    assert.equal(message.commit, false);
    assert.equal(Buffer.from(message.audio_base_64, 'base64').length, 3200);
  }
  h.speak(0.3);
  assert.equal(h.socket.sent.length, 8, 'and from then on, 100 ms at a time');
  h.live.release();
  const last = h.socket.sent[h.socket.sent.length - 1];
  assert.equal(last.commit, true, 'the release commits');
  assert.ok(h.socket.sent.slice(0, -1).every((m) => m.commit === false), 'and only the last chunk commits');
  h.live.cancel();
});

test('more than three seconds before the socket opens: the words give up quietly', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.speak(3.2);
  assert.equal(h.socket.closed, true);
  assert.equal(h.words[h.words.length - 1], '');
  assert.equal(h.records[0].fields.outcome, 'slow');
});

test('a release before the socket opens still commits, once it opens', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.speak(0.25);
  h.live.release();
  assert.equal(h.fake.log.untapped.length, 1, 'the tap comes down on the release');
  h.socket.open();
  const sent = h.socket.sent;
  assert.ok(sent.length >= 2);
  assert.equal(sent[sent.length - 1].commit, true);
});

test('partial words show as they come, then the committed words replace them', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.socket.say({ message_type: 'session_started', session_id: 'x' });
  h.tick(420);
  h.socket.say({ message_type: 'partial_transcript', text: 'Show me' });
  h.socket.say({ message_type: 'partial_transcript', text: "Show me today's" });
  h.socket.say({ message_type: 'partial_transcript', text: "Show me today's orders" });
  assert.deepEqual(h.words.slice(-3), ['Show me', "Show me today's", "Show me today's orders"]);
  h.speak(0.1);
  h.live.release();
  assert.equal(h.socket.closed, false, 'it waits for the committed words');
  h.socket.say({ message_type: 'committed_transcript', text: "Show me today's orders." });
  assert.equal(h.words[h.words.length - 1], "Show me today's orders.", 'the words stay on screen after the release');
  assert.equal(h.socket.closed, true, 'and the socket closes once they are in');
  assert.equal(h.records.length, 1);
  const { kind, fields } = h.records[0];
  assert.equal(kind, 'live_transcript');
  assert.equal(fields.outcome, 'committed');
  assert.equal(fields.ms, 420, 'the time to the first words');
  assert.equal(fields.partials, 3);
  // Telemetry carries how it went, never a word of it.
  assert.ok(!JSON.stringify(h.records).includes('Show me'), 'no words in telemetry');
  assert.deepEqual(Object.keys(fields).filter((k) => fields[k] !== undefined).sort(), ['count', 'ms', 'outcome', 'partials']);
});

test('committed words gather while he holds, with the partial after them', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.socket.say({ message_type: 'committed_transcript', text: 'Refund order 1042.' });
  h.socket.say({ message_type: 'partial_transcript', text: 'And email' });
  assert.equal(h.words[h.words.length - 1], 'Refund order 1042. And email');
  h.live.cancel();
});

test('with no committed words the release lets go after a second and a half, keeping what was shown', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.socket.say({ message_type: 'partial_transcript', text: 'Show me' });
  h.live.release();
  assert.equal(h.timers[0].ms, 1500);
  h.fireTimers();
  assert.equal(h.socket.closed, true);
  assert.equal(h.words[h.words.length - 1], 'Show me', 'kept until the Mac\'s transcript takes its place');
  assert.equal(h.records[0].fields.outcome, 'timeout');
});

// The reason telemetry gets is this file's own word for the error, looked up, never the
// socket's message_type itself (round 9, C-04; it was the message_type before).
for (const [name, message, word] of [
  ['quota', { message_type: 'quota_exceeded_error', error: 'Quota exceeded' }, 'quota'],
  ['auth', { message_type: 'authentication_error', error: 'Invalid token' }, 'auth'],
  ['silence', { message_type: 'insufficient_audio_activity_error', error: 'No audio' }, 'no_audio'],
  ['unknown', { message_type: 'something_new_error', error: 'x' }, 'provider_error'],
]) {
  test(`an error from the socket (${name}) stops the words quietly and takes the tap down`, async () => {
    const h = harness();
    h.live.begin();
    await settle();
    h.socket.open();
    h.socket.say({ message_type: 'partial_transcript', text: 'Show me' });
    h.socket.say(message);
    assert.equal(h.words[h.words.length - 1], '', 'the words go');
    assert.equal(h.socket.closed, true);
    assert.equal(h.fake.log.untapped.length, 1);
    assert.equal(h.records[0].fields.outcome, 'error');
    assert.equal(h.records[0].fields.reason, word);
    const sent = h.socket.sent.length;
    h.live.release();
    assert.equal(h.socket.sent.length, sent, 'nothing is sent after it stopped');
    assert.equal(h.live.active, false);
  });
}

for (const [name, answer, reason] of [
  ['a 503', { status: 503, body: { live: false, why: 'No ElevenLabs key is stored on the server.' } }, 'http_503'],
  ['a 429', { status: 429, body: { live: false, why: 'too often' } }, 'http_429'],
  ['no network', new TypeError('Failed to fetch'), 'fetch'],
  ['an answer with no socket', { status: 200, body: { token: KEY, url: 'http://example.test/', expires_in_s: 10 } }, 'bad_answer'],
]) {
  test(`${name} from the Mac means no words, quietly, and no socket`, async () => {
    const h = harness({ answer });
    h.live.begin();
    await settle();
    assert.equal(h.net.made.length, 0);
    assert.equal(h.words[h.words.length - 1], '');
    assert.equal(h.records[0].fields.outcome, 'unavailable');
    assert.equal(h.records[0].fields.reason, reason);
    assert.equal(h.fake.log.untapped.length, h.fake.log.tapped.length, 'any tap made comes down');
  });
}

test('after a refusal the next holds do not ask again for a while', async () => {
  const h = harness({ answer: { status: 503, body: { live: false, why: 'off' } } });
  h.live.begin();
  await settle();
  h.tick(5000);
  h.live.begin();
  await settle();
  assert.equal(h.fetch.calls.length, 1, 'resting');
  assert.equal(h.records[1].fields.reason, 'resting');
  h.tick(30000);
  h.live.begin();
  await settle();
  assert.equal(h.fetch.calls.length, 2);
});

test('no context or no microphone source: no words, and no key is asked for', async () => {
  for (const options of [{ noContext: true }, { noMic: true }]) {
    const h = harness(options);
    h.live.begin();
    await settle();
    assert.equal(h.fetch.calls.length, 0);
    assert.equal(h.records[0].fields.outcome, 'no_tap');
    assert.equal(h.words[h.words.length - 1], '');
  }
});

test('a cancel closes at once and clears the words, and commits nothing', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.speak(0.3);
  h.socket.say({ message_type: 'partial_transcript', text: 'Cancel that' });
  assert.equal(h.words[h.words.length - 1], 'Cancel that');
  h.live.cancel();
  assert.equal(h.words[h.words.length - 1], '');
  assert.equal(h.socket.closed, true);
  assert.ok(h.socket.sent.every((m) => m.commit === false), 'a cancel is not a question');
  assert.equal(h.records[0].fields.outcome, 'cancelled');
  assert.equal(h.fake.log.untapped.length, 1);
  // A late message on the closed socket changes nothing.
  h.socket.say({ message_type: 'partial_transcript', text: 'late' });
  assert.equal(h.words[h.words.length - 1], '');
});

test('a socket that closes while he holds ends the words quietly', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.socket.say({ message_type: 'partial_transcript', text: 'Show me' });
  h.socket.onclose({ code: 1006 });
  assert.equal(h.words[h.words.length - 1], '');
  assert.equal(h.records[0].fields.outcome, 'closed');
});

test('a new hold replaces an old session without its words leaking into the new one', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  const first = h.socket;
  first.open();
  first.say({ message_type: 'partial_transcript', text: 'old words' });
  h.live.begin();
  await settle();
  assert.equal(first.closed, true);
  first.say({ message_type: 'partial_transcript', text: 'still old' });
  assert.ok(!h.words.includes('still old'));
  h.live.cancel();
});

// ------------------------------------------------------------------ the waveform

function fakeCanvas(width, height) {
  const draws = [];
  let current = null;
  const g = {
    fillStyle: '', globalAlpha: 1,
    setTransform() {}, clearRect() { current = []; draws.push(current); },
    fillRect(x, y, w, hh) { current.push({ x, h: hh }); },
  };
  const canvas = { width: 0, height: 0, getContext: () => g, getBoundingClientRect: () => ({ width, height }) };
  return { canvas, draws };
}

function waveHarness(options) {
  const opts = options || {};
  const { canvas, draws } = fakeCanvas(60, 36);
  const frames = [];
  let t = 0;
  let level = 0;
  const wave = LV.wave({
    canvas: () => canvas,
    analyser: () => opts.analyser !== false,
    level: () => level,
    reduced: () => Boolean(opts.reduced),
    frame: (fn) => { frames.push(fn); return frames.length; },
    cancelFrame: () => {},
    now: () => t,
    dpr: 2,
  });
  return {
    wave, draws, frames,
    set level(v) { level = v; },
    // One step: 50 ms of frames at 60 Hz, the level held.
    step(v) {
      level = v;
      for (let i = 0; i < 3; i++) { t += 16.7; const fn = frames.shift(); if (fn) fn(t); }
    },
    heights() { return draws[draws.length - 1].map((b) => b.h); },
  };
}

const LOW = LV.barHeight(0, 36);

test('with no analyser the waveform is a still, quiet line and nothing is scheduled', () => {
  const h = waveHarness({ analyser: false });
  h.wave.start();
  assert.equal(h.wave.running, false);
  assert.equal(h.frames.length, 0, 'no frames: nothing will move');
  assert.equal(h.draws.length, 1);
  assert.ok(h.heights().length >= 8);
  assert.ok(h.heights().every((height) => height === LOW), 'every bar at the floor');
});

test('silence is low and flat, and a quiet room does not move', () => {
  const h = waveHarness();
  h.wave.start();
  h.step(0);
  h.step(0.01);
  h.step(0.03);   // the room's hum is under the floor
  const drawn = h.draws.slice(1);
  assert.ok(drawn.length >= 3);
  for (const bars of drawn) assert.ok(bars.every((b) => b.h === LOW));
  assert.deepEqual(drawn[drawn.length - 1], drawn[drawn.length - 2], 'the same level draws the same picture');
});

test('each bar is the level the analyser gave, entering on the right and stepping left', () => {
  const h = waveHarness();
  h.wave.start();
  h.step(0.9);
  let bars = h.heights();
  const tall = LV.barHeight(0.9, 36);
  assert.ok(tall > 30, `speech is tall: ${tall}`);
  assert.equal(bars[bars.length - 1], tall, 'the newest level is the rightmost bar');
  assert.ok(bars.slice(0, -1).every((height) => height === LOW));
  h.step(0.3);
  bars = h.heights();
  assert.equal(bars[bars.length - 1], LV.barHeight(0.3, 36));
  assert.equal(bars[bars.length - 2], tall, 'the older bar stepped one place left');
  // Heights follow the levels in order, and only them.
  assert.ok(LV.barHeight(0.3, 36) < tall && LV.barHeight(0.3, 36) > LOW);
  h.wave.stop();
  assert.ok(h.heights().every((height) => height === LOW), 'stopped: back to the still line');
  assert.equal(h.wave.running, false);
});

test('each bar is the loudest the analyser said in its 50 ms, not its last word', () => {
  const h = waveHarness();
  h.wave.start();
  const levels = [0.2, 0.8, 0.1];
  for (const v of levels) { h.level = v; const fn = h.frames.shift(); fn(); }
  // Three frames at t=0 did not reach a step; the next one past 50 ms does.
  h.step(0);
  const bars = h.heights();
  assert.equal(bars[bars.length - 1], LV.barHeight(0.8, 36));
});

test('with reduced motion nothing scrolls: the row says the current level where it stands', () => {
  const h = waveHarness({ reduced: true });
  h.wave.start();
  h.step(0.6);
  const first = h.draws[h.draws.length - 1];
  h.step(0.6);
  const second = h.draws[h.draws.length - 1];
  assert.deepEqual(second, first, 'the same level, the same picture: no lateral motion');
  assert.ok(Math.max(...second.map((b) => b.h)) > LOW);
  h.step(0);
  assert.ok(h.heights().every((height) => height === LOW), 'and silence is flat');
});

test('nothing in the waveform is invented', () => {
  for (const name of ['Math.random', 'Math.sin', 'Math.cos', 'performance.now() %']) {
    assert.ok(!SOURCE.includes(name), `web/live-voice.js uses ${name}`);
  }
});

// ------------------------------------------------------------------ the words stay on the phone

test('the words are kept out of a copy of the screen, as a typed field is', () => {
  const web = path.join(__dirname, '..', '..', 'web');
  const telemetry = fs.readFileSync(path.join(web, 'telemetry.js'), 'utf8');
  const copy = telemetry.slice(telemetry.indexOf('function copyScreen'), telemetry.indexOf('function takeScreen'));
  assert.match(copy, /hasAttribute\('data-spoken'\)\) b\.textContent = a\.textContent \? typedMask\(a\.textContent\) : ''/);
  const alpha = fs.readFileSync(path.join(web, 'alpha.js'), 'utf8');
  assert.match(alpha, /id: 'ask-words', class: 'ask-words', 'data-spoken': true/);
  assert.match(alpha, /id: 'ask-heard', class: 'ask-heard', 'data-spoken': true/);
  // And nothing here keeps them: no storage of any kind, and nothing written to the console.
  for (const name of ['localStorage', 'sessionStorage', 'indexedDB', 'console.']) {
    assert.ok(!SOURCE.includes(name), `web/live-voice.js uses ${name}`);
  }
});

// ------------------------------------------------------------------ round 9: the key's life (C-02)

// A fetch whose answer the test lets go of when it chooses: the Mac taking its time.
function heldFetch(body) {
  const calls = [];
  let letGo = null;
  const fn = async (url, init) => {
    calls.push({ url, init });
    await new Promise((resolve) => { letGo = resolve; });
    return { ok: true, status: 200, json: async () => body };
  };
  fn.calls = calls;
  fn.answer = () => letGo();
  return fn;
}

test('a key is used within the life the Mac gave it, counted from the ask, or not at all (C-02)', async () => {
  for (const [waited, opened] of [[9999, true], [10001, false]]) {
    const fetch = heldFetch(GRANTED.body);
    const h = harness({ fetch });
    h.live.begin();
    await settle();
    h.tick(waited);          // the answer took this long to come back
    fetch.answer();
    await settle();
    assert.equal(h.net.made.length, opened ? 1 : 0, `after ${waited} ms`);
    if (!opened) {
      assert.equal(h.records[0].fields.outcome, 'unavailable');
      assert.equal(h.records[0].fields.reason, 'expired');
    }
    h.live.cancel();
  }
});

test('an answer with no life the page can honour opens nothing, and a long one is held to a minute (C-02)', async () => {
  for (const life of [undefined, 0, -5, '10', null, Number.NaN]) {
    const body = Object.assign({}, GRANTED.body, { expires_in_s: life });
    const h = harness({ answer: { status: 200, body } });
    h.live.begin();
    await settle();
    assert.equal(h.net.made.length, 0, `expires_in_s ${String(life)}`);
    assert.equal(h.records[0].fields.reason, 'bad_answer');
  }
  assert.equal(LV.keyLife({ expires_in_s: 3600 }), LV.MAX_LIFE_S);
  const fetch = heldFetch(Object.assign({}, GRANTED.body, { expires_in_s: 3600 }));
  const h = harness({ fetch });
  h.live.begin();
  await settle();
  h.tick(LV.MAX_LIFE_S * 1000 + 1);
  fetch.answer();
  await settle();
  assert.equal(h.net.made.length, 0, 'an hour was asked for; a minute is the most the page gives');
});

test('an answer whose key is not key-shaped opens nothing (C-02)', async () => {
  for (const token of ['Jane Doe said hello there', 'short', 'x'.repeat(2049), 'a&b=c&d=e&f=g&h=i', 12345]) {
    const h = harness({ answer: { status: 200, body: Object.assign({}, GRANTED.body, { token }) } });
    h.live.begin();
    await settle();
    assert.equal(h.net.made.length, 0, String(token));
    assert.equal(h.records[0].fields.reason, 'bad_answer');
  }
});

test('one key, one socket, one hold: every hold asks afresh and no socket is ever opened twice (C-02)', async () => {
  let n = 0;
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    n += 1;
    return { ok: true, status: 200, json: async () => Object.assign({}, GRANTED.body, { token: `single-use-stand-in-key-${n}` }) };
  };
  fetch.calls = calls;
  const h = harness({ fetch });
  h.live.begin();
  await settle();
  const first = h.socket;
  first.open();
  first.onclose({ code: 1006 });           // it drops while he holds: the words end, and nothing reconnects
  await settle();
  assert.equal(h.net.made.length, 1);
  assert.equal(first.closed, true);
  h.live.begin();
  await settle();
  assert.equal(h.net.made.length, 2);
  assert.equal(calls.length, 2, 'each hold asks for its own key');
  const tokens = h.net.made.map((socket) => new URL(socket.url).searchParams.get('token'));
  assert.deepEqual(tokens, ['single-use-stand-in-key-1', 'single-use-stand-in-key-2']);
  h.live.cancel();
  assert.equal(h.net.made[1].closed, true);
  assert.equal(h.net.made.length, 2);
});

// ------------------------------------------------------------------ round 9: fixed words for telemetry (C-04)

test('nothing the socket says reaches telemetry: not its message type, its error text or its close reason (C-04)', async () => {
  const Telemetry = require(path.join(__dirname, '..', '..', 'web', 'telemetry.js'));
  Telemetry.reset();
  const bodies = [];
  Telemetry._setTransport((body) => bodies.push(body));
  Telemetry.configure({ test_session: 'ts_live_words' });
  const NAME = 'Jane Doe';
  const errors = [
    { message_type: `${NAME} order 1042_error`, error: `${NAME}, 12 High Street` },
    { message_type: 'error', error: `${NAME} said something`, detail: NAME },
    { message_type: 'authentication_error', error: `the key for ${NAME}` },
    { message_type: { nested: NAME }, error: NAME },
    { error: { text: NAME } },
  ];
  const records = [];
  for (const message of errors) {
    const h = harness();
    h.live.begin();
    await settle();
    h.socket.open();
    h.socket.say({ message_type: 'partial_transcript', text: `Refund ${NAME}` });
    h.socket.say(message);
    assert.equal(h.socket.closed, true, JSON.stringify(message));
    records.push(...h.records);
  }
  // A close, while he holds, with the provider's own code and reason.
  for (const code of [4001, 1008, 999, undefined]) {
    const h = harness();
    h.live.begin();
    await settle();
    h.socket.open();
    h.socket.onclose({ code, reason: `closed on ${NAME}` });
    records.push(...h.records);
  }
  for (const { kind, fields } of records) {
    assert.equal(kind, 'live_transcript');
    assert.ok(LV.OUTCOMES.has(fields.outcome), fields.outcome);
    assert.ok(fields.reason === undefined || LV.REASONS.has(fields.reason), fields.reason);
    for (const [key, value] of Object.entries(fields)) {
      assert.ok(['outcome', 'reason', 'ms', 'partials', 'count'].includes(key), key);
      if (key !== 'outcome' && key !== 'reason' && value !== undefined) assert.ok(Number.isInteger(value), key);
    }
    Telemetry.record(kind, LV.telemetryFields(fields));
  }
  assert.deepEqual(records.slice(0, 5).map((r) => r.fields.reason), ['provider_error', 'provider_error', 'auth', 'provider_error', 'provider_error']);
  assert.deepEqual(records.slice(5).map((r) => r.fields.reason), ['code_app', 'code_1008', 'code_other', 'code_other']);
  Telemetry.flush(false);
  const sent = bodies.join('\n');
  assert.ok(sent.includes('live_transcript'), 'the events were sent');
  assert.ok(!sent.includes('Jane') && !sent.includes('High Street') && !sent.includes('1042'), sent);
  Telemetry.reset();
});

test('telemetryFields keeps its own words and whole numbers, and nothing else', () => {
  assert.deepEqual(LV.telemetryFields({ outcome: 'committed', reason: 'code_1000', ms: 420, partials: 3, count: 8 }),
    { outcome: 'committed', reason: 'code_1000', ms: 420, partials: 3, count: 8 });
  assert.deepEqual(LV.telemetryFields({ outcome: 'Jane Doe', reason: 'Jane Doe_error', ms: 'Jane', partials: 1.5, count: -1, text: 'Jane Doe', words: 'x' }),
    { outcome: 'other', reason: 'other', ms: undefined, partials: undefined, count: undefined });
  assert.deepEqual(LV.telemetryFields(null), { outcome: 'other', reason: undefined, ms: undefined, partials: undefined, count: undefined });
  for (const word of [...LV.OUTCOMES, ...LV.REASONS]) assert.match(word, /^[a-z0-9_]{2,24}$/, word);
});

// ------------------------------------------------------------------ round 9: a release before the socket opens (C-05)

test('released before the socket opens, which then takes longer than the finish: the words are still committed (C-05)', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.speak(0.25);
  h.live.release();
  h.advance(LV.FINISH_MS + 100);         // the old finish timer had fired by now and thrown the audio away
  assert.equal(h.socket.closed, false, 'still waiting for the socket');
  assert.equal(h.records.length, 0);
  h.socket.open();
  const sent = h.socket.sent;
  assert.ok(sent.length >= 2, 'what was said while it opened went, and then the commit');
  assert.equal(sent[sent.length - 1].commit, true);
  const bytes = sent.reduce((total, message) => total + Buffer.from(message.audio_base_64, 'base64').length, 0);
  assert.equal(bytes, 8000, 'a quarter of a second of 16 kHz PCM16, all of it');
  // The finish is counted from the commit: a second and a half from the open, not from the release.
  h.advance(LV.FINISH_MS - 100);
  assert.equal(h.socket.closed, false);
  h.socket.say({ message_type: 'committed_transcript', text: 'Show me the orders.' });
  assert.equal(h.words[h.words.length - 1], 'Show me the orders.');
  assert.equal(h.socket.closed, true);
  assert.equal(h.records[0].fields.outcome, 'committed');
});

test('after the commit the words have a second and a half, however late the socket opened (C-05)', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.speak(0.1);
  h.live.release();
  h.advance(3000);
  h.socket.open();
  h.advance(LV.FINISH_MS - 1);
  assert.equal(h.socket.closed, false);
  h.advance(1);
  assert.equal(h.socket.closed, true);
  assert.equal(h.records[0].fields.outcome, 'timeout');
});

test('a socket that never opens is let go OPEN_WAIT_MS after the release, quietly (C-05)', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.speak(0.1);
  h.live.release();
  h.advance(LV.OPEN_WAIT_MS - 1);
  assert.equal(h.socket.closed, false);
  h.advance(1);
  assert.equal(h.socket.closed, true);
  assert.deepEqual([h.records[0].fields.outcome, h.records[0].fields.reason], ['slow', 'open_wait']);
  h.socket.open();                        // a late open changes nothing
  assert.equal(h.socket.sent.length, 0);
});

// ------------------------------------------------------------------ round 9: the words are display only (C-03)

test('the words go to onWords and nowhere else, and are forgotten when the hold is over (C-03)', async () => {
  const h = harness();
  const handle = h.live.begin();
  await settle();
  h.socket.open();
  h.speak(0.2);
  h.socket.say({ message_type: 'partial_transcript', text: 'Refund Jane Doe' });
  assert.equal(handle.words, 'Refund Jane Doe');
  h.live.release();
  h.socket.say({ message_type: 'committed_transcript', text: 'Refund Jane Doe, order 1042.' });
  assert.equal(handle.done, true);
  assert.equal(handle.words, '', 'nothing of them is kept here once the hold is over');
  assert.equal(h.words[h.words.length - 1], 'Refund Jane Doe, order 1042.', 'they were shown');
  // Nowhere else: not back up the socket, not to the Mac, not to telemetry.
  for (const message of h.socket.sent) assert.deepEqual(Object.keys(message).sort(), ['audio_base_64', 'commit', 'message_type']);
  assert.ok(h.socket.sent.every((message) => message.message_type === 'input_audio_chunk'));
  assert.deepEqual(h.fetch.calls.map((call) => [call.url, call.init.body]), [['/voice/live', '{}']]);
  assert.ok(!JSON.stringify(h.records).includes('Jane') && !JSON.stringify(h.records).includes('1042'));
});

test('drop(): once the Mac has said what it heard, the live words are cleared and their socket let go (C-03)', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  h.socket.open();
  h.socket.say({ message_type: 'partial_transcript', text: 'Show me' });
  h.live.release();
  h.live.drop();
  assert.equal(h.words[h.words.length - 1], '');
  assert.equal(h.socket.closed, true);
  assert.equal(h.records[0].fields.outcome, 'superseded');
  assert.equal(h.live.active, false);
  h.socket.say({ message_type: 'committed_transcript', text: 'Show me the orders.' });
  assert.equal(h.words[h.words.length - 1], '', 'a late word changes nothing');
});

test('this file reaches no storage, no address bar, no cookie, no console and no other endpoint', () => {
  for (const name of ['localStorage', 'sessionStorage', 'indexedDB', 'console.', 'history.', 'location', 'document.cookie', 'sendBeacon', 'caches.']) {
    assert.ok(!SOURCE.includes(name), `web/live-voice.js uses ${name}`);
  }
  // Its one request is to the Mac, for the key; its one socket is the address the Mac gave.
  assert.deepEqual(SOURCE.match(/deps\.fetch\('[^']*'/g), ["deps.fetch('/voice/live'"]);
  assert.equal(SOURCE.split('new deps.WebSocket(').length - 1, 1);
});
