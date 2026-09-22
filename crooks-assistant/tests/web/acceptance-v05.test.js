/* §E of the V0.5 contract, as a deterministic harness (node --test).
 *
 * The acceptance scenario is written for a real device, a real microphone, a real Gmail and a
 * real model. None of those exist here, and the contract says so: "If live Gmail/model access
 * is still gated, use an honest fixture/fake adapter for the acceptance harness and label it
 * as such. Do not pretend fixture data is live."
 *
 * So this is a FIXTURE RUN and nothing else. Every number below — the 40ms to the first
 * partial, the 260ms transcription, the 1.2s orders read, the 3.4s email read — is invented
 * by this file and proves nothing about how fast the Mac is. What it does prove is the SHAPE
 * of the scenario, which is the part the tablet owns and the part that kept going wrong:
 *
 *   - the acknowledgement is on the pointer, not on the recorder;
 *   - the words settle before reasoning is claimed;
 *   - there is no interval that nothing on screen explains;
 *   - orders and email are two jobs, not one word;
 *   - the first useful result does not wait for the slowest job;
 *   - speaking begins while a job is still running;
 *   - an interruption keeps the work that was already in flight;
 *   - a second question adds a background job, with no Split anywhere;
 *   - and one job failing leaves every other one exactly as it was.
 *
 * Timings from a REAL device belong in the evidence directory, taken from the live_marks the
 * page posts (app/routes/observe.py), and must never be read off this file.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const LS = require(path.join(__dirname, '..', '..', 'web', 'live-state.js'));
const JOBS = require(path.join(__dirname, '..', '..', 'web', 'jobs.js'));

// A stand-in for the tablet: the two modules the page owns, one clock the test winds, and a
// record of every state the caption would have shown. Explicitly a FIXTURE — it is named so
// that a reader who skims cannot mistake its numbers for measurements.
function fixtureTablet() {
  let t = 0;
  const captions = [];
  const strip = shim.document.createElement('div');
  strip.ownerDocument = shim.document;

  const live = LS.create({ now: () => t });
  live.subscribe((to) => captions.push(to));
  const jobs = JOBS.create({ now: () => t, onChange: (list) => JOBS.render(strip, list) });

  return {
    live, jobs, strip, captions,
    FIXTURE: true,
    tick(ms) { t += ms; },
    at: () => t,
    onStrip: () => strip.querySelectorAll('.job').map((row) => row.allText()),
    // What the owner would be looking at: the state, and the work named beneath it.
    screen: () => ({ state: live.state, jobs: jobs.visible().map((job) => `${job.label} · ${job.state}`) }),
  };
}

// §E's sentence, written down once so the tests below can prove no part of it ever reaches
// the state machine. The page hands the machine its LENGTH; this constant never leaves this
// file, and exists only so that "never" can be asserted against something real.
const SPOKEN = "Clive, check today's orders, see if anyone important is waiting for a reply "
  + 'and tell me what I need to deal with first.';

// §E's question, run against the fixture above.
function askTheAcceptanceQuestion(tablet) {
  const { live, jobs } = tablet;

  live.pointerDown();                       // thumb down on the orb
  tablet.tick(40); live.partial(0);         // the room has speech in it
  tablet.tick(3200); live.released();       // thumb up
  tablet.tick(260); live.final(SPOKEN.length);  // the Mac's transcript lands on the glass

  tablet.tick(180); live.thinking();        // the model has the turn, no tool named yet
  tablet.tick(220);
  live.working('orders'); jobs.start('orders', 'Checking', "today's orders");
  jobs.queue('email', 'Checking', 'who is waiting for a reply');
  return tablet;
}

test('the fixture is labelled a fixture, and says so to anything that asks', () => {
  const tablet = fixtureTablet();
  assert.equal(tablet.FIXTURE, true);
});

test('§E: the acknowledgement is on the touch, and the words settle before reasoning', () => {
  const tablet = fixtureTablet();
  const { live } = tablet;

  live.pointerDown();
  assert.equal(live.state, 'LISTENING', 'immediate LISTENING acknowledgement');
  assert.equal(live.marks().acknowledgedMs, 0);

  tablet.tick(40); live.partial(0);
  assert.equal(live.state, 'HEARING', 'speech activity while speaking');

  tablet.tick(3200); live.released();
  assert.equal(live.state, 'HEARING', 'still working the words out — and the caption says so');

  tablet.tick(260); live.final(SPOKEN.length);
  assert.equal(live.state, 'UNDERSTOOD', 'final transcript visible on release');
  assert.equal(live.marks().transcriptMs, 260);

  tablet.tick(180);
  assert.ok(live.thinking(), 'explicit THINKING transition');
  assert.equal(live.marks().progressMs, 440, 'release → first progress indication');
});

test('§E: no interval passes with nothing on screen to explain it', () => {
  const tablet = fixtureTablet();
  askTheAcceptanceQuestion(tablet);
  tablet.tick(1200); tablet.jobs.done('orders', '14 today, 3 unfulfilled');
  tablet.live.usefulResult('order list');
  tablet.tick(300); tablet.live.responding();
  tablet.tick(1900);
  tablet.jobs.start('email', 'Checking', 'who is waiting for a reply');
  tablet.jobs.done('email', '2 waiting');
  tablet.live.idle();

  // Every state the machine passed through, in order, with nothing between them: the whole
  // turn is accounted for, and IDLE is only ever at the ends.
  const seen = tablet.captions;
  assert.deepEqual(seen, [
    'LISTENING', 'HEARING', 'UNDERSTOOD', 'THINKING', 'WORKING', 'RESPONDING', 'IDLE',
  ]);
  assert.deepEqual(tablet.live.refusals(), [], 'nothing was asked for that could not happen');
});

test('§E: orders and email are two jobs, and they progress independently', () => {
  const tablet = fixtureTablet();
  askTheAcceptanceQuestion(tablet);
  assert.deepEqual(tablet.screen(), {
    state: 'WORKING',
    jobs: ["Checking today's orders · WORKING", 'Checking who is waiting for a reply · QUEUED'],
  });
  assert.equal(tablet.onStrip().length, 2, 'two lines on the strip, not one word under the orb');
});

test('§E: the first useful result does not wait for the slowest job', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);

  tablet.tick(1200);
  jobs.done('orders', '14 today, 3 unfulfilled');
  live.usefulResult('order list');
  const useful = live.marks().usefulMs;

  jobs.start('email', 'Checking', 'who is waiting for a reply');
  tablet.tick(2200);
  jobs.done('email', '2 waiting');
  live.usefulResult('the waiting customers');

  assert.equal(live.marks().usefulMs, useful, 'the FIRST useful result is the one measured');
  assert.ok(useful < 2200, 'and it landed long before the slow job did');
});

test('§E: CLIVE speaks while a job is still running, and the strip keeps it', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  tablet.tick(1200); jobs.done('orders', '14 today, 3 unfulfilled');
  jobs.start('email', 'Checking', 'who is waiting for a reply');
  live.usefulResult('order list');

  tablet.tick(300);
  assert.ok(live.responding(), 'the answer begins on what is already known');
  assert.equal(jobs.running(), 1, 'the email read is still going');
  assert.ok(tablet.onStrip().some((line) => line.includes('Checking who is waiting for a reply')));
});

test('§E: "Open the second customer" interrupts the answer and keeps the work in flight', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  tablet.tick(1200); jobs.done('orders', '14 today, 3 unfulfilled');
  jobs.start('email', 'Checking', 'who is waiting for a reply');
  live.usefulResult('order list');
  tablet.tick(300); live.responding();

  tablet.tick(700);
  live.pointerDown();                       // the owner cuts in
  assert.equal(live.state, 'LISTENING');
  assert.equal(live.turn, 2, 'a new turn');
  assert.ok(tablet.captions.includes('INTERRUPTED'), 'the barge-in is a state, not a silent reset');
  assert.equal(jobs.get('email').state, 'WORKING', 'invariant 5: the email read was not cancelled');
});

test('§E: "while you’re doing that, prepare the packing list" adds a job, not a Split', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  jobs.start('email', 'Checking', 'who is waiting for a reply');

  tablet.tick(900);
  live.pointerDown(); tablet.tick(1400); live.released(); live.final(52);
  live.working('packing');
  jobs.queue('packing', 'Preparing', 'packing list');

  assert.deepEqual(tablet.screen().jobs, [
    "Checking today's orders · WORKING",
    'Checking who is waiting for a reply · WORKING',
    'Preparing packing list · QUEUED',
  ]);
  // Three pieces of work, one session, one state. Nothing divided, nothing to merge.
  assert.equal(live.state, 'WORKING');
  assert.equal(jobs.running(), 3);
});

test('§E: one job failing leaves the others, and the answer, exactly as they were', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  jobs.start('email', 'Checking', 'who is waiting for a reply');

  tablet.tick(3400);
  jobs.fail('email', 'Gmail did not answer');
  assert.equal(live.state, 'WORKING', 'a job failing is not the turn failing');

  tablet.tick(200);
  jobs.done('orders', '14 today, 3 unfulfilled');
  live.usefulResult('order list');
  assert.ok(live.responding(), 'CLIVE still answers, on what it does know');

  const strip = tablet.onStrip();
  assert.ok(strip.some((line) => line.includes('Gmail did not answer')), 'and says what it does not');
  assert.equal(tablet.live.marks().faults, 0, 'one job failing is not a fault of the interaction');
});

test('§E: the turn ending leaves no dashboard behind', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  jobs.start('email', 'Checking', 'who is waiting for a reply');
  jobs.done('orders', '14 today'); jobs.done('email', '2 waiting');
  live.usefulResult('the summary'); live.responding(); live.idle();
  jobs.endTurn();

  assert.deepEqual(tablet.screen(), { state: 'IDLE', jobs: [] });
  assert.equal(tablet.strip.hidden, true, 'the idle screen is the screen it was');
});

test('§E: the whole run is accounted for, and carries no word of what was said', () => {
  const tablet = fixtureTablet();
  const { live, jobs } = tablet;
  askTheAcceptanceQuestion(tablet);
  tablet.tick(1200); jobs.done('orders', '14 today'); live.usefulResult('order list');
  tablet.tick(300); live.responding();
  tablet.tick(400); live.idle();

  const marks = live.marks();
  for (const name of ['acknowledgedMs', 'transcriptMs', 'progressMs', 'usefulMs', 'respondingMs']) {
    assert.equal(typeof marks[name], 'number', `${name} was not measured`);
  }
  assert.ok(marks.usefulMs < marks.respondingMs, 'something was readable before anything was spoken');
  // The machine holds how MUCH was said and nothing else. The reasons in its history are
  // words this page chose — 'orders' there is the job's key, not the owner's sentence — and
  // what must never appear is any part of what was actually spoken.
  assert.equal(marks.heardChars, SPOKEN.length, 'the length, which is all it was ever given');
  const blob = JSON.stringify({ marks, history: live.history() });
  assert.ok(!blob.includes(SPOKEN));
  for (const fragment of ['Clive', 'anyone important', 'waiting for a reply', 'deal with first']) {
    assert.ok(!blob.includes(fragment), `the evidence repeats "${fragment}"`);
  }
});
