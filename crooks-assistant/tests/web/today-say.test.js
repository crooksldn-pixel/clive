/* What a member of the team said or typed, read against their own list (web/today-say.js).
 *
 * The sentences a packer actually says are steps, done at once: "I've packed 2106", "done with the
 * hoodies", "I'll take the next one", "give it back", "undo". Everything else goes to their CLIVE:
 * a "not", a question, a word the list cannot place, two jobs at once. What only George may do
 * (a refund, a discount, cancelling an order, a price, the settings) is never a step: it comes back
 * as George's, and a question about it goes to CLIVE. Two jobs that fit equally are put to the
 * person, never guessed. Every name here is invented.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const SAY = require(path.join(__dirname, '..', '..', 'web', 'today-say.js'));

function card(key, kind, title, extra) {
  const lines = (extra && extra.lines) || [];
  return Object.assign({
    key, kind, title, mine: false, claimed: false, order: (/#\d{3,6}/.exec(title) || [''])[0], counts: [],
    words: SAY.titleWords([title, ...lines].join(' ')),
  }, extra || {});
}

const COUNT = card('w_1', 'stock_count', 'Count the hoodies on the back rail', { mine: true, claimed: true });
const ORDER_A = card('order:1', 'pack_order', 'Pack #2106: 2 items for Jane Okafor', { lines: ['Loopback Hoodie (M)', 'Getaway Tee (L)'] });
const ORDER_B = card('order:2', 'pack_order', 'Pack #2107: 1 item for Sam Reyes', { lines: ['Cuffs Cap'] });
const SHELF = card('w_2', 'job', 'Restock the tee shelf');
const EMAIL = card('email:1', 'reply_email', 'Reply to Tom Briggs: Where is my order #2098?');
const BOARD = { mine: [COUNT], grabs: [ORDER_A, ORDER_B, EMAIL, SHELF] };

test('the steps a packer says are read as steps on the right job', () => {
  const cases = [
    ["I've packed 2106", 'packed', ORDER_A],
    ['packed #2107', 'packed', ORDER_B],
    ['2106 packed and done', 'packed', ORDER_A],
    ['done with the hoodies', 'done', COUNT],
    ['finished the tee shelf', 'done', SHELF],
    ["I'll take 2107", 'claim', ORDER_B],
    ['grab the tee shelf', 'claim', SHELF],
    ['all done', 'done', COUNT],                     // the job in hand
    ['give it back', 'release', COUNT],
    ["I'll take the next one", 'claim', ORDER_A],   // the one shown next
    ['next', 'claim', ORDER_A],
    ['Replied to Tom Briggs', 'done', EMAIL],
    ['packed the cap one', 'packed', ORDER_B],        // by what is in it
    ['packed the hoodies', 'packed', ORDER_A],        // the order with a hoodie in it, never the count of them
  ];
  for (const [said, step, job] of cases) {
    const read = SAY.read(said, BOARD);
    assert.equal(read.do, step, said);
    assert.equal(read.job.key, job.key, said);
  }
});

test('undo, and what is next, are read without touching a job', () => {
  for (const said of ['undo', 'Undo that', 'oops', 'my mistake']) assert.deepEqual(SAY.read(said, BOARD), { do: 'undo' }, said);
  for (const said of ["what's next?", 'What now', 'what do I do next']) assert.deepEqual(SAY.read(said, BOARD), { do: 'show' }, said);
  assert.deepEqual(SAY.read('   ', BOARD), { do: 'none' });
});

test('what only George may do is never a step: it is his, and a question about it is CLIVE’s', () => {
  for (const said of ['refund 2106', 'can you refund order 2106 please', 'she wants her money back on 2107',
    'give him a 10% discount', 'cancel the order for Sam', 'cancel 2106', 'change the price of the cap',
    'change the address on 2109', 'open the settings']) {
    assert.deepEqual(SAY.read(said, BOARD), { do: 'george' }, said);
  }
  for (const said of ['how do refunds work?', 'do we do discounts', 'is 2106 cancelled?']) {
    assert.deepEqual(SAY.read(said, BOARD), { do: 'ask' }, said);
  }
});

test('anything more than one plain step goes to CLIVE, never half-read', () => {
  for (const said of [
    "I haven't packed 2106", "didn't finish the hoodies", 'done, left it by the door',
    'packed 2106 and 2107', 'packed 9999', 'done with the jackets', 'where is the tape',
    'what is in 2106?', 'the printer is jammed', 'packed the tee shelf',  // a job is not packed
  ]) {
    assert.equal(SAY.read(said, BOARD).do, 'ask', said);
  }
});

test('two jobs that fit equally are put to the person; the one in hand wins only when it is done', () => {
  const capCount = card('w_3', 'stock_count', 'Count the caps');
  const board = { mine: [], grabs: [ORDER_B, capCount] };
  const read = SAY.read('take the cap', board);
  assert.equal(read.do, 'pick');
  assert.deepEqual(read.jobs.map((j) => j.key), [ORDER_B.key, capCount.key]);
  const held = { mine: [Object.assign({}, capCount, { mine: true, claimed: true })], grabs: [ORDER_B] };
  assert.equal(SAY.read('done with the cap', held).job.key, 'w_3');
});

test('a sentence with no job to act on goes to CLIVE', () => {
  assert.equal(SAY.read('done', { mine: [], grabs: [SHELF] }).do, 'ask');      // nothing in hand
  assert.equal(SAY.read('next', { mine: [], grabs: [] }).do, 'ask');
  assert.equal(SAY.read('give back the shelf', BOARD).do, 'ask');              // not theirs to give back
});

test('only the steps a tap can take ever come back', () => {
  const steps = new Set();
  const sentences = ['packed 2106', 'done', 'take 2107', 'give it back', 'undo', 'refund 2106', 'what next',
    'delete everything', 'send an email to Jane', 'set the stock of the cap to 3', 'fulfil 2106 with tracking 123'];
  for (const said of sentences) steps.add(SAY.read(said, BOARD).do);
  for (const step of steps) assert.ok(['claim', 'packed', 'done', 'release', 'undo', 'show', 'pick', 'george', 'ask', 'none'].includes(step), step);
  assert.equal(SAY.read('send an email to Jane', BOARD).do, 'ask');
  assert.equal(SAY.read('fulfil 2106 with tracking 123', BOARD).do, 'ask');
});

test('“cancel it” is never a silent undo: the page is told to ask which they meant', () => {
  for (const said of ['cancel it', 'Cancel that', 'cancel', 'cancel this one please']) {
    assert.deepEqual(SAY.read(said, BOARD), { do: 'cancel' }, said);
  }
  assert.deepEqual(SAY.read('cancel the order for Sam', BOARD), { do: 'george' });   // plainly George's
  assert.deepEqual(SAY.read('undo that', BOARD), { do: 'undo' });                    // plainly an undo
});
