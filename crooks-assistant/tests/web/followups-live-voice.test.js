/* The live words keep the start and the end of what he says (web/live-voice.js, the round-12
 * deploy review: S4-N01 and S4-N02), run under Node from tests/test_followups_voice_records.py.
 *
 * S4-N01: on a first hold the recording starts while the worklet's module is still loading, and
 * the tap used to wait for it, so what he said meanwhile never reached the words. Here the module
 * is held loading while audio reaches the tap: that audio reaches the socket, in order, ahead of
 * what follows, and a device with no worklet keeps its ScriptProcessor.
 *
 * S4-N02: the worklet posts whole 1,024-frame batches, and the release used to stop listening to it
 * at once, so the part of a batch it held and the batches already posted but not yet delivered were
 * lost before the commit. Here the processor is the page's own (WORKLET_SOURCE), run as the audio
 * thread would run it, behind a port whose messages the test delivers when it chooses: both reach
 * the socket before the commit, within FLUSH_MS, and a worklet that never answers holds the release
 * no longer than that.
 *
 * The stand-ins are the ones tests/web/live-voice.test.js uses (the context and its nodes, the
 * socket, the fetch, the clock), with the worklet's port and its module load under the test's hand.
 * The context runs at 16 kHz, so a sample said is a sample sent and the bytes can be compared
 * whole.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const LV = require(path.join(__dirname, '..', '..', 'web', 'live-voice.js'));

const settle = async (times = 4) => { for (let i = 0; i < times; i++) await new Promise((resolve) => setImmediate(resolve)); };

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

// Samples no two neighbours of which are alike, from `from`, so any loss or reordering shows.
function ramp(from, count) {
  const out = new Float32Array(count);
  for (let i = 0; i < count; i++) out[i] = ((((from + i) * 37) % 2001) - 1000) / 1100;
  return out;
}

function joined(...parts) {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}

// What the socket should be sent for these samples: 16 kHz PCM16, little-endian.
function pcmOf(samples) { return Buffer.from(LV.pcmBytes(LV.createResampler(16000, 16000)(samples))); }
function bytesSent(socket) { return Buffer.concat(socket.sent.map((m) => Buffer.from(m.audio_base_64, 'base64'))); }
function commits(socket) { return socket.sent.filter((m) => m.commit === true).length; }

// ------------------------------------------------------------------ the worklet, as the audio thread runs it

// The processor class WORKLET_SOURCE registers, built with the two names an AudioWorkletGlobalScope gives it.
function theProcessor() {
  let registered = null;
  class AudioWorkletProcessor { constructor() { this.port = { onmessage: null, postMessage() {} }; } }
  new Function('AudioWorkletProcessor', 'registerProcessor', LV.WORKLET_SOURCE)(
    AudioWorkletProcessor, (name, cls) => { registered = { name, cls }; });
  assert.ok(registered, 'WORKLET_SOURCE registers a processor');
  return registered;
}

// An AudioWorkletNode whose processor is the page's own, and whose port carries messages each way
// only when the test delivers them, in the order they were posted.
function workletNodes() {
  const { name: registered, cls: Processor } = theProcessor();
  const made = [];
  class FakeWorkletNode {
    constructor(ctx, name, options) {
      assert.equal(name, registered);
      this.kind = 'worklet';
      this.options = options;
      this.to = [];
      this.posted = [];          // everything the page posted to the processor
      this.toProcessor = [];     // posted by the page, not yet delivered
      this.toPage = [];          // posted by the processor, not yet delivered
      this.running = true;
      const node = this;
      this.processor = new Processor();
      this.processor.port.postMessage = (data) => node.toPage.push(data);
      this.port = { onmessage: null, postMessage(data) { node.posted.push(data); node.toProcessor.push(data); } };
      made.push(this);
    }
    connect(x) { this.to.push(x); }
    disconnect() { this.to = []; }
    // The audio thread: 128 frames a render quantum, until the processor says it is finished.
    render(samples) {
      for (let at = 0; at < samples.length && this.running; at += 128) {
        this.running = this.processor.process([[samples.subarray(at, at + 128)]]);
      }
    }
    deliverToProcessor() { for (const data of this.toProcessor.splice(0)) if (this.processor.port.onmessage) this.processor.port.onmessage({ data }); }
    deliverToPage() { for (const data of this.toPage.splice(0)) if (this.port.onmessage) this.port.onmessage({ data }); }
  }
  return { FakeWorkletNode, made };
}

// ------------------------------------------------------------------ the rest of the page's world

function fakeAudio(opts) {
  const log = { tapped: [], untapped: [], modules: [] };
  const ctx = {
    sampleRate: 16000,
    destination: { name: 'destination' },
    createGain() { return { gain: { value: 1 }, to: [], connect(node) { this.to.push(node); }, disconnect() { this.to = []; } }; },
  };
  if (!opts.noScriptProcessor) {
    ctx.createScriptProcessor = (size) => ({ kind: 'script', size, to: [], onaudioprocess: null, connect(x) { this.to.push(x); }, disconnect() { this.to = []; } });
  }
  if (opts.worklet) {
    ctx.audioWorklet = { addModule(url) { log.modules.push(url); return opts.addModule ? opts.addModule(url) : Promise.resolve(); } };
  }
  const audio = {
    context: ctx,
    hasMic: true,
    tapMic(node) { log.tapped.push(node); return true; },
    untapMic(node) { log.untapped.push(node); },
  };
  return { audio, ctx, log };
}

const KEY = 'single-use-stand-in-key';
const GRANTED = {
  token: KEY, url: 'wss://example.test/v1/speech-to-text/realtime',
  params: { model_id: 'scribe_v2_realtime', audio_format: 'pcm_16000', language_code: 'en', commit_strategy: 'manual' },
  expires_in_s: 10,
};

function harness(options) {
  const opts = options || {};
  const fake = fakeAudio(opts);
  const worklets = workletNodes();
  const made = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.sent = []; this.closed = false; made.push(this); }
    send(data) { if (this.closed) throw new Error('closed'); this.sent.push(JSON.parse(data)); }
    close() { this.closed = true; }
    open() { if (this.onopen) this.onopen({}); }
  }
  const words = [];
  const records = [];
  const timers = [];
  let t = 10000;
  const live = LV.create({
    audio: fake.audio,
    fetch: async () => ({ ok: true, status: 200, json: async () => GRANTED }),
    WebSocket: FakeSocket,
    AudioWorkletNode: opts.worklet ? worklets.FakeWorkletNode : undefined,
    Blob: class { constructor(parts, init) { this.parts = parts; this.type = init && init.type; } },
    URL: { createObjectURL: () => 'blob:crooks-live-tap', revokeObjectURL() {} },
    now: () => t,
    setTimeout: (fn, ms) => { timers.push({ fn, ms, at: t + ms, live: true }); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].live = false; },
    onWords: (text) => words.push(text),
    record: (kind, fields) => records.push({ kind, fields }),
  });
  return {
    live, fake, words, records, timers, worklets,
    get socket() { return made[made.length - 1]; },
    get tap() { return fake.log.tapped[fake.log.tapped.length - 1]; },
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
    // What the microphone says, through the tap that is hung now. A worklet's batches are left on
    // its port unless `deliver` is set.
    say(samples, deliver = true) {
      const tap = this.tap;
      if (tap.kind === 'script') {
        for (let at = 0; at < samples.length; at += 2048) {
          const block = samples.slice(at, at + 2048);
          if (tap.onaudioprocess) tap.onaudioprocess({ inputBuffer: { getChannelData: () => block } });
        }
        return;
      }
      tap.render(samples);
      if (deliver) tap.deliverToPage();
    },
  };
}

// ------------------------------------------------------------------ S4-N01: the start of what he says

test('on a first hold, what is said while the worklet module loads reaches the socket, in order, ahead of what follows (S4-N01)', async () => {
  const loading = deferred();
  const h = harness({ worklet: true, addModule: () => loading.promise });
  h.live.begin();
  await settle();
  assert.deepEqual(h.fake.log.modules, ['blob:crooks-live-tap'], 'the module is loading');
  h.advance(0);                               // the next turn of the page's event loop
  await settle();
  assert.equal(h.fake.log.tapped.length, 1, 'a tap is hung while the module is still loading');
  const whileLoading = ramp(0, 4000);          // a quarter of a second, said before the module is in
  h.say(whileLoading);
  loading.resolve();
  await settle();
  const after = ramp(4000, 2700);
  h.say(after);
  h.socket.open();
  h.live.release();
  await settle();
  assert.equal(commits(h.socket), 1);
  assert.equal(h.socket.sent[h.socket.sent.length - 1].commit, true, 'the commit is the last thing sent');
  assert.ok(bytesSent(h.socket).equals(pcmOf(joined(whileLoading, after))),
    'every sample said while the module loaded went, first, and then everything after it');
  assert.deepEqual(h.fake.log.untapped, h.fake.log.tapped, 'the tap comes down on the release');

  // The module, loaded now, is the next hold's tap, and it is not loaded twice.
  h.live.begin();
  await settle();
  assert.equal(h.tap.kind, 'worklet');
  assert.equal(h.fake.log.modules.length, 1);
  h.live.cancel();
});

test('a device with no worklet keeps its ScriptProcessor, hung at once, and every sample reaches the socket (S4-N01)', async () => {
  const h = harness();
  h.live.begin();
  await settle();
  assert.equal(h.tap.kind, 'script');
  assert.equal(h.timers.length, 0, 'nothing is waited for before the tap is hung');
  const said = ramp(0, 5000);
  h.say(said);
  h.socket.open();
  h.live.release();
  assert.equal(commits(h.socket), 1);
  assert.ok(bytesSent(h.socket).equals(pcmOf(said)));
});

test('with a worklet and no ScriptProcessor to hear with meanwhile, the module is waited for and is the tap (S4-N01)', async () => {
  const loading = deferred();
  const h = harness({ worklet: true, noScriptProcessor: true, addModule: () => loading.promise });
  h.live.begin();
  await settle();
  h.advance(10);
  await settle();
  assert.equal(h.fake.log.tapped.length, 0, 'there is nothing else to hang');
  loading.resolve();
  await settle();
  assert.equal(h.tap.kind, 'worklet');
  h.live.cancel();
});

// ------------------------------------------------------------------ S4-N02: the end of what he says

async function workletHold() {
  const h = harness({ worklet: true });
  h.live.begin();
  await settle();
  assert.equal(h.tap.kind, 'worklet', 'a module that loads at once is this hold\'s tap');
  return h;
}

test('a release part-way through a 1,024-frame batch: that part reaches the socket before the commit (S4-N02)', async () => {
  const h = await workletHold();
  h.socket.open();
  const said = ramp(0, 3 * 1024 + 500);        // three whole batches, and 500 frames of a fourth
  h.say(said);
  assert.equal(h.tap.toPage.length, 0, 'the three whole batches have arrived');
  const tap = h.tap;
  h.live.release();
  assert.deepEqual(tap.posted, ['flush'], 'the processor is asked for what it holds');
  assert.equal(commits(h.socket), 0, 'and nothing is committed before it has answered');
  tap.deliverToProcessor();
  tap.deliverToPage();
  assert.equal(commits(h.socket), 1);
  assert.equal(h.socket.sent[h.socket.sent.length - 1].commit, true);
  assert.ok(bytesSent(h.socket).equals(pcmOf(said)), 'all 3,572 frames, in order, the last 500 with them');
  assert.deepEqual(h.fake.log.untapped, [tap], 'then the tap comes down');
  assert.equal(tap.port.onmessage, null);
});

test('a release with batches posted and not yet delivered: they reach the socket before the commit (S4-N02)', async () => {
  const h = await workletHold();
  h.socket.open();
  const said = ramp(0, 2 * 1024);
  h.say(said, false);                         // posted by the processor, still on the port
  const tap = h.tap;
  assert.equal(tap.toPage.length, 2);
  h.live.release();
  tap.deliverToPage();                        // what was posted before the release arrives after it
  assert.equal(commits(h.socket), 0, 'the processor has not yet said it has posted everything');
  tap.deliverToProcessor();
  tap.deliverToPage();
  assert.equal(commits(h.socket), 1);
  assert.equal(h.socket.sent[h.socket.sent.length - 1].commit, true);
  assert.ok(bytesSent(h.socket).equals(pcmOf(said)));
});

test('a socket that opens while the worklet hands over: what it held still goes before the commit (S4-N02)', async () => {
  const h = await workletHold();
  const said = ramp(0, 1024 + 300);
  h.say(said);
  const tap = h.tap;
  h.live.release();
  h.socket.open();
  assert.equal(commits(h.socket), 0, 'not before the worklet has answered');
  tap.deliverToProcessor();
  tap.deliverToPage();
  assert.equal(commits(h.socket), 1);
  assert.equal(h.socket.sent[h.socket.sent.length - 1].commit, true);
  assert.ok(bytesSent(h.socket).equals(pcmOf(said)));
});

test('a worklet that never answers holds the release no longer than FLUSH_MS (S4-N02)', async () => {
  assert.ok(LV.FLUSH_MS > 0 && LV.FLUSH_MS <= 500, `FLUSH_MS ${LV.FLUSH_MS}`);
  const h = await workletHold();
  h.socket.open();
  const said = ramp(0, 2048);
  h.say(said);
  const tap = h.tap;
  h.live.release();                           // and the processor is never given the message
  h.advance(LV.FLUSH_MS - 1);
  assert.equal(commits(h.socket), 0);
  h.advance(1);
  assert.equal(commits(h.socket), 1, 'the commit goes at the bound');
  assert.ok(bytesSent(h.socket).equals(pcmOf(said)), 'with everything that had arrived');
  assert.deepEqual(h.fake.log.untapped, [tap]);
  // Whatever the processor says after that changes nothing.
  const sent = h.socket.sent.length;
  tap.deliverToProcessor();
  tap.deliverToPage();
  assert.equal(h.socket.sent.length, sent);
  assert.equal(h.records.length, 0, 'still waiting for the words, not ended');
});

test('a cancel while the worklet hands over commits nothing and takes the tap down (S4-N02)', async () => {
  const h = await workletHold();
  h.socket.open();
  h.say(ramp(0, 1500));
  const tap = h.tap;
  h.live.release();
  h.live.cancel();
  tap.deliverToProcessor();
  tap.deliverToPage();
  h.advance(LV.FLUSH_MS);
  assert.equal(commits(h.socket), 0);
  assert.equal(h.socket.closed, true);
  assert.deepEqual(h.fake.log.untapped, [tap]);
  assert.equal(h.records[0].fields.outcome, 'cancelled');
});
