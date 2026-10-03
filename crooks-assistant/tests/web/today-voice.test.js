/* Hold to speak, for the team (web/today-voice.js), under Node with a stand-in recogniser.
 *
 * What is held: the phone's own recogniser is asked in British English for live words; the words
 * appear as they are heard; letting go ends the hold and hands over exactly the sentence heard,
 * once; a hold with nothing heard, a blocked microphone and a phone with no recogniser each say so
 * in this file's own words and send nothing; cancelling sends nothing; and nothing here uploads,
 * fetches or records anything (the owner's voice path, and the Mac's transcriber, are never asked:
 * app/routes/turn.py refuses a team member's recording).
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const FILE = path.join(__dirname, '..', '..', 'web', 'today-voice.js');

// A recogniser that does what a test tells it to, when it is told.
class Fake {
  constructor() { Fake.last = this; this.started = false; this.stopped = false; this.aborted = false; }
  start() { this.started = true; }
  stop() { this.stopped = true; }
  abort() { this.aborted = true; }
  say(text, final) {
    const result = [{ transcript: text }];
    result.isFinal = Boolean(final);
    this.onresult({ resultIndex: 0, results: [result] });
  }
  end() { this.onend(); }
  fail(error) { this.onerror({ error }); this.onend(); }
}

function fresh(engine) {
  delete require.cache[require.resolve(FILE)];
  globalThis.SpeechRecognition = engine;
  globalThis.webkitSpeechRecognition = undefined;
  return require(FILE);
}

function hooks() {
  const seen = { words: [], ended: [], failed: [], states: [] };
  return { seen, on: {
    onWords: (t) => seen.words.push(t), onEnd: (t) => seen.ended.push(t),
    onFail: (r) => seen.failed.push(r), onState: (s) => seen.states.push(s),
  } };
}

test('holding, speaking and letting go hands over the sentence heard, once', () => {
  const V = fresh(Fake);
  const { seen, on } = hooks();
  const voice = V.create(on);
  assert.equal(voice.supported, true);
  assert.equal(voice.start(), true);
  const rec = Fake.last;
  assert.equal(rec.lang, 'en-GB');
  assert.equal(rec.interimResults, true);
  assert.equal(rec.started, true);
  rec.say("I've packed", false);
  rec.say("I've packed 2106", true);
  assert.deepEqual(seen.words, ["I've packed", "I've packed 2106"]);
  voice.stop();
  assert.equal(rec.stopped, true);
  rec.stop = () => { throw new Error('InvalidStateError'); };   // a recogniser already stopping
  voice.stop();                                                 // the finger lifting after a tap to stop
  assert.deepEqual(seen.ended, []);                             // nothing sent early
  rec.end();
  rec.end();                                       // a second end is not a second sentence
  assert.deepEqual(seen.ended, ["I've packed 2106"]);
  assert.deepEqual(seen.failed, []);
  assert.deepEqual(seen.states, ['listening', 'settling', 'idle']);
  assert.equal(voice.listening, false);
});

test('nothing heard, a blocked microphone and no recogniser each say so and send nothing', () => {
  let V = fresh(Fake);
  let { seen, on } = hooks();
  let voice = V.create(on);
  voice.start();
  voice.stop();
  Fake.last.end();
  assert.deepEqual(seen.ended, []);
  assert.deepEqual(seen.failed, ['unheard']);

  ({ seen, on } = hooks());
  voice = V.create(on);
  voice.start();
  Fake.last.fail('not-allowed');
  assert.deepEqual(seen.failed, ['blocked']);
  assert.match(V.REASONS.blocked, /Type it/);

  V = fresh(undefined);
  ({ seen, on } = hooks());
  voice = V.create(on);
  assert.equal(voice.supported, false);
  assert.equal(voice.start(), false);
  assert.deepEqual(seen.failed, ['unsupported']);
  for (const reason of Object.values(V.REASONS)) assert.ok(!/—/.test(reason) && reason.length < 120, reason);
});

test('cancelling forgets what was heard', () => {
  const V = fresh(Fake);
  const { seen, on } = hooks();
  const voice = V.create(on);
  voice.start();
  Fake.last.say('refund 2106', true);
  voice.cancel();
  assert.equal(Fake.last.aborted, true);
  assert.deepEqual(seen.ended, []);
  assert.equal(voice.listening, false);
});

test('the team’s voice never uploads, fetches or records: only the words leave, as typing does', () => {
  // The code, without the comments that explain why (they name the owner's routes on purpose).
  const source = fs.readFileSync(FILE, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  for (const forbidden of ['fetch(', 'XMLHttpRequest', 'MediaRecorder', 'getUserMedia', '/voice/live', '/turn', 'sendBeacon', 'localStorage']) {
    assert.ok(!source.includes(forbidden), forbidden);
  }
});
