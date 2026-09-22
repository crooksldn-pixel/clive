/* The one interaction state, run under Node (node --test tests/web/live-state.test.js).
 *
 * V0.5 invariant 2 is a machine, so it is tested as one: the spine in order, every transition
 * the contract names as explicit, the refusals that keep the screen honest, and the four
 * latencies the evidence gate asks for. Nothing here touches a DOM — that is the point of the
 * file under test. Time is the test's, never the clock's.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const LS = require(path.join(__dirname, '..', '..', 'web', 'live-state.js'));

// A machine whose clock the test winds by hand, so a latency is an arithmetic fact.
function machine() {
  let t = 1000;
  const seen = [];
  const m = LS.create({ now: () => t });
  m.subscribe((to, from, reason) => seen.push(`${from}->${to}:${reason}`));
  return { m, seen, tick: (ms) => { t += ms; }, at: () => t };
}

// The whole turn the acceptance scenario describes, with nothing skipped. The thumb lifts
// before the words settle, because on this tablet the Mac does the transcribing.
function fullTurn(h) {
  h.m.pointerDown();
  h.tick(300); h.m.partial(6);
  h.tick(900); h.m.partial(48);
  h.tick(200); h.m.released();
  h.tick(400); h.m.final(52);
  h.tick(150); h.m.thinking();
  h.tick(400); h.m.working('orders');
  h.tick(600); h.m.usefulResult('orders done');
  h.tick(300); h.m.responding();
  h.tick(500); h.m.idle();
}

test('the spine runs in the order the contract sets', () => {
  const h = machine();
  assert.equal(h.m.state, 'IDLE');
  fullTurn(h);
  const path_ = h.seen.map((line) => line.split('->')[1].split(':')[0]);
  assert.deepEqual(path_, [
    'LISTENING', 'HEARING', 'HEARING', 'UNDERSTOOD', 'THINKING', 'WORKING', 'RESPONDING', 'IDLE',
  ]);
  assert.equal(h.m.state, 'IDLE');
  assert.deepEqual(h.m.refusals(), []);
});

test('pointer-down acknowledges synchronously, before anything else can be true', () => {
  const h = machine();
  h.m.pointerDown();
  assert.equal(h.m.state, 'LISTENING');
  assert.equal(h.m.marks().acknowledgedMs, 0, 'the orb wakes on the touch, not on the recorder');
  assert.equal(h.m.turn, 1);
});

test('the four latencies the evidence gate asks for are measured from the right instants', () => {
  const h = machine();
  fullTurn(h);
  const marks = h.m.marks();
  assert.equal(marks.acknowledgedMs, 0);          // pointer-down -> visual acknowledgement
  assert.equal(marks.transcriptMs, 400);          // release -> final transcript
  assert.equal(marks.progressMs, 550);            // release -> first progress indication
  assert.equal(marks.usefulMs, 1550);             // release -> first useful result
  assert.equal(marks.respondingMs, 1850);         // release -> speech
  assert.equal(marks.partials, 2);
});

test('a useful result lands before speech, and is not a state of its own', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking(); h.m.working('orders');
  h.tick(700);
  h.m.usefulResult('first order card');
  assert.equal(h.m.state, 'WORKING', 'a card arriving does not move the turn on by itself');
  assert.equal(h.m.marks().usefulMs, 700);
  h.tick(100);
  h.m.usefulResult('second card');
  assert.equal(h.m.marks().usefulMs, 700, 'FIRST useful result — a later one never overwrites it');
});

test('speech never waits for every job: WORKING may follow RESPONDING and back again', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking(); h.m.working('orders'); h.m.responding();
  assert.ok(h.m.working('email'), 'a slow job finishing while CLIVE speaks is normal');
  assert.equal(h.m.state, 'WORKING');
  assert.ok(h.m.responding('final summary'));
  assert.deepEqual(h.m.refusals(), []);
});

test('a fast path answers without ever naming a tool', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking();
  assert.ok(h.m.responding(), 'THINKING -> RESPONDING is a real turn, not a skipped step');
  assert.deepEqual(h.m.refusals(), []);
});

test('holding through an answer is an interruption, and it starts a new turn', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking(); h.m.responding();
  const interrupted = h.m.marks();
  h.m.pointerDown();
  assert.equal(h.m.state, 'LISTENING');
  assert.equal(h.m.turn, 2, 'the second question is its own turn');
  assert.ok(h.seen.some((line) => line === 'RESPONDING->INTERRUPTED:barge-in'),
    'the interruption is a state, not a silent reset');
  assert.equal(interrupted.interruptions, 0, 'counted on the turn that was cut off, once it is');
});

test('a second pointer-down while listening is refused and keeps the hold it interrupted', () => {
  const h = machine();
  h.m.pointerDown();
  h.tick(400); h.m.partial(12);
  const before = h.m.marks();
  assert.equal(h.m.pointerDown(), false);
  assert.equal(h.m.turn, 1, 'no new turn');
  assert.deepEqual(h.m.marks(), before, 'the live hold keeps its marks');
  assert.equal(h.m.refusals().length, 1);
  assert.equal(h.m.refusals()[0].reason, 'already capturing');
});

test('a fault is explicit, and leaving one is explicit too', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking();
  assert.ok(h.m.fault('the Mac cannot be reached'));
  assert.equal(h.m.state, 'FAULT');
  assert.equal(h.m.marks().faults, 1);
  assert.equal(h.m.recover(), true);
  assert.equal(h.m.state, 'RECOVERING');
  assert.ok(h.m.idle());
  assert.equal(h.m.state, 'IDLE');
});

test('holding after a fault recovers through RECOVERING rather than pretending nothing failed', () => {
  const h = machine();
  h.m.pointerDown(); h.m.fault('microphone refused');
  h.m.pointerDown();
  assert.ok(h.seen.some((line) => line === 'FAULT->RECOVERING:hold after fault'));
  assert.equal(h.m.state, 'LISTENING');
});

test('recover() outside a fault is refused, not obeyed', () => {
  const h = machine();
  h.m.pointerDown();
  assert.equal(h.m.recover(), false);
  assert.equal(h.m.state, 'LISTENING');
  assert.equal(h.m.refusals()[0].reason, 'not in fault');
});

test('nothing heard ends the turn where it started', () => {
  const h = machine();
  h.m.pointerDown();
  h.tick(120);
  assert.ok(h.m.heardNothing('too short'));
  assert.equal(h.m.state, 'IDLE');
  assert.deepEqual(h.m.refusals(), []);
});

test('an illegal transition does not happen, is counted, and leaves the state alone', () => {
  const h = machine();
  assert.equal(h.m.responding(), false, 'IDLE cannot start speaking');
  assert.equal(h.m.state, 'IDLE');
  assert.equal(h.m.working(), false);
  assert.equal(h.m.interrupt(), false, 'there is nothing to interrupt');
  assert.equal(h.m.refusals().length, 3);
  assert.equal(h.seen.length, 0, 'a refusal is never announced as a transition');
});

test('a partial outside capture is refused: HEARING cannot be reached from a turn in flight', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking();
  assert.equal(h.m.partial(30), false);
  assert.equal(h.m.state, 'THINKING');
  assert.equal(h.m.refusals()[0].reason, 'partial outside capture');
});

test('the machine is given lengths, never words', () => {
  const h = machine();
  h.m.pointerDown();
  h.m.partial('check today’s orders'.length);
  h.m.final('check today’s orders please'.length);
  const blob = JSON.stringify({ marks: h.m.marks(), history: h.m.history(), refusals: h.m.refusals() });
  assert.ok(!/orders/i.test(blob), 'nothing that leaves this file can repeat what was said');
  assert.equal(h.m.marks().heardChars, 27);
});

test('the old presentation words each mean exactly one state', () => {
  const h = machine();
  h.m.pointerDown();
  assert.ok(h.m.fromPresentation('TRANSCRIBING'), 'still working the words out is still hearing');
  assert.equal(h.m.state, 'HEARING');
  h.m.released(); h.m.final(10);
  assert.ok(h.m.fromPresentation('THINKING'));
  assert.equal(h.m.state, 'THINKING');
  assert.ok(h.m.fromPresentation('CHECKING SHOPIFY'));
  assert.equal(h.m.state, 'WORKING');
  assert.ok(h.m.fromPresentation('CHECKING EMAIL'));
  assert.equal(h.m.state, 'WORKING');
  assert.ok(h.m.fromPresentation('SPEAKING'));
  assert.equal(h.m.state, 'RESPONDING');
  assert.ok(h.m.fromPresentation('SUCCESS'), 'a verified change is CLIVE answering');
  assert.equal(h.m.state, 'RESPONDING');
  assert.ok(h.m.fromPresentation('READY'));
  assert.equal(h.m.state, 'IDLE');
});

test('an unknown presentation word is refused rather than guessed', () => {
  const h = machine();
  assert.equal(h.m.fromPresentation('CHECKING THE WEATHER'), false);
  assert.equal(h.m.state, 'IDLE');
  assert.equal(h.m.refusals()[0].reason, 'unknown presentation word');
});

test('a presentation ERROR is a fault, and is counted as one', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10);
  assert.ok(h.m.fromPresentation('ERROR'));
  assert.equal(h.m.state, 'FAULT');
  assert.equal(h.m.marks().faults, 1);
});

test('every state the contract names exists, and every state can be left', () => {
  for (const name of ['IDLE', 'LISTENING', 'HEARING', 'UNDERSTOOD', 'THINKING', 'WORKING', 'RESPONDING']) {
    assert.ok(LS.STATES.indexOf(name) >= 0, `${name} is missing`);
  }
  for (const name of ['INTERRUPTED', 'FAULT', 'RECOVERING']) {
    assert.ok(LS.STATES.indexOf(name) >= 0, `${name} must be explicit, not implied`);
  }
  for (const name of LS.STATES) {
    const out = LS.ALLOWED[name] || [];
    assert.ok(out.length > 0, `${name} is a trap: nothing leaves it`);
    assert.ok(out.some((to) => to !== name), `${name} can only loop on itself`);
    for (const to of out) assert.ok(LS.STATES.indexOf(to) >= 0, `${name} -> ${to} is not a state`);
  }
});

test('every state IDLE cannot be reached from directly can still get home', () => {
  // A machine with no way back to IDLE is a machine the owner has to reload out of.
  const reaches = new Set(['IDLE']);
  for (let i = 0; i < LS.STATES.length; i += 1) {
    for (const name of LS.STATES) {
      if ((LS.ALLOWED[name] || []).some((to) => reaches.has(to))) reaches.add(name);
    }
  }
  for (const name of LS.STATES) assert.ok(reaches.has(name), `${name} cannot reach IDLE`);
});

test('a subscriber that throws does not stop the machine', () => {
  const m = LS.create({ now: () => 0 });
  m.subscribe(() => { throw new Error('a renderer blew up'); });
  const seen = [];
  m.subscribe((to) => seen.push(to));
  m.pointerDown();
  assert.equal(m.state, 'LISTENING');
  assert.deepEqual(seen, ['LISTENING']);
});

test('the history is bounded, so a long session cannot grow the page without end', () => {
  const m = LS.create({ now: () => 0 });
  for (let i = 0; i < 400; i += 1) { m.pointerDown(); m.heardNothing(); }
  assert.ok(m.history().length <= 200);
  assert.equal(m.turn, 400, 'bounding the history never loses count of the turns');
});


test('release is marked where it happens, not backdated from whatever lands next', () => {
  const h = machine();
  h.m.pointerDown();
  h.tick(1200);
  h.m.released();
  assert.equal(h.m.state, 'LISTENING', 'lifting the thumb changes who is waiting, not what CLIVE knows');
  h.tick(800);
  h.m.final(30);
  assert.equal(h.m.state, 'UNDERSTOOD');
  assert.equal(h.m.marks().transcriptMs, 800, 'the wait for the words is 800ms, not 0 and not 2000');
});

test('the transcript settles on screen before reasoning is claimed', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released();
  assert.equal(h.m.thinking(), false, 'THINKING cannot precede the words it is about');
  assert.equal(h.m.refusals().length, 1);
  h.m.final(30);
  assert.ok(h.m.thinking());
});

test('a question nobody spoke still has a turn, and is still measured', () => {
  const h = machine();
  assert.ok(h.m.asked(24), 'a dock shortcut is a question');
  assert.equal(h.m.state, 'UNDERSTOOD');
  assert.equal(h.m.turn, 1);
  assert.equal(h.m.marks().acknowledgedMs, null, 'there was no hold to acknowledge');
  assert.equal(h.m.marks().transcriptMs, 0, 'and nothing to transcribe');
  h.tick(250); h.m.working('orders');
  h.tick(400); h.m.usefulResult('order card');
  assert.equal(h.m.marks().progressMs, 250);
  assert.equal(h.m.marks().usefulMs, 650);
});

test('tapping a shortcut over an answer interrupts it, exactly as holding does', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking(); h.m.responding();
  assert.ok(h.m.asked(12));
  assert.ok(h.seen.some((line) => line === 'RESPONDING->INTERRUPTED:new question'));
  assert.equal(h.m.turn, 2);
});


test('a useful result is written down but never announced as a transition', () => {
  const h = machine();
  h.m.pointerDown(); h.m.released(); h.m.final(10); h.m.thinking(); h.m.working('orders');
  const announced = h.seen.length;
  h.tick(500);
  h.m.usefulResult('order card');
  assert.equal(h.seen.length, announced,
    'a card landing is not a change of state; repainting the caption for it would show WORKING twice');
  assert.equal(h.m.marks().usefulMs, 500, 'and it is still measured');
  assert.ok(h.m.history().some((step) => step.reason === 'order card'), 'and still written down');
});
