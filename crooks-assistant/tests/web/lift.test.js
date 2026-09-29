/* Holding a record and putting it on a screen (web/lift.js): the rules, under Node.
 *
 * The page half — the press, the tray, the chip, the drop, with real fingers, a mouse and the
 * keyboard against the real backend — is scripts/browser/lift.js (tests/test_r12_lift_browser.py).
 * This is the arithmetic and the words underneath it, so a rule that is wrong is named here rather
 * than found as "the drag did not work" in a browser run.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const L = require(path.join(__dirname, '..', '..', 'web', 'lift.js'));
const WEB = path.join(__dirname, '..', '..', 'web');

test('a hold is a still press of about a third of a second; a flick wanders out of it first', () => {
  assert.equal(L.HOLD_MS, 350);
  const finger = { type: 'touch', x: 100, y: 400 };
  // A thumb is never perfectly still: a few pixels is still a hold.
  assert.equal(L.wandered(finger, 106, 404), false);
  assert.equal(L.wandered(finger, 100, 410), false);
  // A flick moves further than that long before the hold is due, and is a scroll.
  assert.equal(L.wandered(finger, 100, 389), true);
  assert.equal(L.wandered(finger, 120, 400), true);
  // A mouse is steadier than a finger, so it is held to less: a drag-to-select starts sooner.
  const mouse = { type: 'mouse', x: 100, y: 400 };
  assert.equal(L.wandered(mouse, 104, 400), false);
  assert.equal(L.wandered(mouse, 106, 400), true);
});

test('letting go: on a screen it goes there; where it lifted the tray stays; anywhere else it goes back', () => {
  const lift = { x0: 300, y0: 480 };
  assert.equal(L.release(lift, 300, 780, { screen: { id: 'scr_0123456789ab' } }), 'drop');
  assert.equal(L.release(lift, 310, 490, null), 'pick', 'let go where it lifted: choose by tapping');
  assert.equal(L.release(lift, 300, 480 + L.PICK_PX + 1, null), 'cancel', 'dragged, and let go on nothing');
  assert.equal(L.release(lift, 300, 90, null), 'cancel');
  assert.equal(L.release(lift, 300, 780, { cancel: true }), 'cancel', 'dropped on Cancel');
});

test('a thumb near a tile\'s edge still lands on it, and between two tiles on the one it is inside', () => {
  const rect = (top) => ({ left: 20, right: 580, top, bottom: top + 64 });
  const office = { screen: { id: 'a' }, rect: rect(700) };
  const packing = { screen: { id: 'b' }, rect: rect(772) };
  const targets = [office, packing];
  assert.equal(L.hitTest(targets, 300, 732), office);
  assert.equal(L.hitTest(targets, 300, 697), office, 'three pixels above its edge');
  assert.equal(L.hitTest(targets, 300, 800), packing);
  assert.equal(L.hitTest(targets, 300, 773), packing, 'inside the second, within the first one\'s margin');
  assert.equal(L.hitTest(targets, 300, 600), null);
  assert.equal(L.hitTest(targets, 15, 732), office, 'within the margin at the side');
  assert.equal(L.hitTest(targets, 5, 732), null);
  assert.equal(L.hitTest([], 300, 732), null);
});

test('the chip sits above a fingertip, beside a mouse, and always inside the screen', () => {
  const view = { w: 601, h: 889 };
  const above = L.placeChip(300, 500, 240, 56, view, 'touch');
  assert.equal(above.left, 180);
  assert.ok(above.top + 56 < 500, 'the finger does not cover it');
  const mouse = L.placeChip(300, 500, 240, 56, view, 'mouse');
  assert.ok(mouse.left > 300 && mouse.top > 500, 'beside the pointer, not under it');
  const corner = L.placeChip(5, 10, 240, 56, view, 'touch');
  assert.ok(corner.left >= 12 && corner.top >= 12, JSON.stringify(corner));
  const edge = L.placeChip(598, 880, 240, 56, view, 'mouse');
  assert.ok(edge.left + 240 <= 601 - 12 && edge.top + 56 <= 889 - 12, JSON.stringify(edge));
  // The phone.
  const phone = L.placeChip(195, 300, 300, 56, { w: 390, h: 844 }, 'touch');
  assert.ok(phone.left >= 12 && phone.left + 300 <= 390 - 12, JSON.stringify(phone));
});

test('each screen says whether it is on and what it shows now, in the words the tray uses', () => {
  assert.equal(L.stateLine({ online: true, showing: 'Order #1938' }), 'On · Showing Order #1938');
  assert.equal(L.stateLine({ online: true, showing: 'Order #1938', beside: 'Autumn drop shoot' }), 'On · Showing Order #1938 and Autumn drop shoot');
  assert.equal(L.stateLine({ online: true, showing: null }), 'On · Nothing up');
  assert.equal(L.stateLine({ online: false, showing: 'Today' }), 'Off · Showing Today');
  assert.equal(L.stateLine({ online: false }), 'Off');
  assert.equal(L.overLine({ online: true }), 'Let go to show it here');
  assert.equal(L.overLine({ online: false }), 'Off · It goes up when it’s next on');
});

test('what went where is said from CLIVE\'s own answer, on or off', () => {
  assert.equal(L.confirmation({ screen: 'Office TV', showing: 'Order #1938', on: true }), 'Order #1938 is on the Office TV.');
  assert.equal(L.confirmation({ screen: 'Packing screen', showing: 'Autumn drop shoot', on: false }),
    'Autumn drop shoot goes on the Packing screen when it’s next on.');
});

test('a refusal is said in CLIVE\'s words; with none, in plain ones that say what is known', () => {
  const detail = "That order wasn't shown in this conversation, so it can't go on a screen from here. Ask CLIVE for it, then hold it again.";
  assert.equal(L.refusal(403, { code: 'not_issued', detail }, 'Office TV'), detail);
  // The door's own refusal carries a spoken line; that is the one to show.
  assert.equal(L.refusal(403, { detail: 'not the owner', spoken: 'Requests from the server itself aren’t allowed to apply changes.' }, 'Office TV'),
    'Requests from the server itself aren’t allowed to apply changes.');
  assert.equal(L.refusal(0, {}, 'Office TV'), 'CLIVE couldn’t be reached, so nothing went on the Office TV.');
  assert.match(L.refusal(-1, {}, 'Office TV'), /isn’t known whether it went up\. Look at the Office TV\./);
  assert.equal(L.refusal(500, {}, 'Office TV'), 'That couldn’t be put on the Office TV.');
  assert.equal(L.refusal(409, { detail: 'x'.repeat(900) }, 'Office TV').length, 300);
});

test('the drop names the conversation and the record, and nothing else', () => {
  const body = L.bodyFor('s1', { kind: 'order', ref: 'gid://shopify/Order/1938', title: 'Order #1938', sub: 'Mia Jones' });
  assert.deepEqual(body, { session_id: 's1', kind: 'order', ref: 'gid://shopify/Order/1938' });
  assert.deepEqual(Object.keys(L.bodyFor('', { kind: 'objective', ref: 'obj_0123abcd' })).sort(), ['kind', 'ref', 'session_id']);
});

test('only a record a screen can show, with an id of its shape, is ever lifted', () => {
  assert.equal(L.screenable('order', 'gid://shopify/Order/1938'), true);
  assert.equal(L.screenable('objective', 'obj_0123abcd'), true);
  for (const [kind, ref] of [['order', 'gid://shopify/Customer/7'], ['order', '1938'], ['order', ''], ['objective', 'obj_XYZ'],
    ['objective', 'gid://shopify/Order/1'], ['email_thread', '18f2a9c0b1d2e3f4'], ['customer', 'gid://shopify/Customer/7']]) {
    assert.equal(L.screenable(kind, ref), false, `${kind} ${ref}`);
  }
  // An email and a customer are held too, and say why they do not lift.
  assert.equal(L.SAY.email_thread, 'A screen shows orders and objectives, not emails.');
  assert.equal(L.SAY.customer, 'A screen shows orders and objectives, not customers.');
  for (const selector of ['[data-kind="order"][data-ref]', '.card[data-type="order"][data-ref]', '.card[data-type="order_workspace"][data-ref]',
    '[data-objective]', '[data-kind="email_thread"][data-ref]', '[data-kind="customer"][data-ref]']) {
    assert.ok(L.HOLDABLE.split(',').map((s) => s.trim()).includes(selector), selector);
  }
});

test('the chip names an order by its number and whose it is, from what its card already says', () => {
  assert.deepEqual(L.orderWords('#1940 Priya Raman'), { title: 'Order #1940', sub: 'Priya Raman' });
  assert.deepEqual(L.orderWords('#1938', 'Mia Jones'), { title: 'Order #1938', sub: 'Mia Jones' });
  assert.deepEqual(L.orderWords('CROOKS-1938 · £60.00 · unfulfilled'), { title: 'Order CROOKS-1938', sub: '' });
  assert.deepEqual(L.orderWords('Order #1962'), { title: 'Order #1962', sub: '' });
  assert.deepEqual(L.orderWords('1938'), { title: 'Order #1938', sub: '' });
  assert.deepEqual(L.orderWords(''), { title: 'Order', sub: '' });
});

test('the page loads the tray and its styles, and the app shell keeps them for when CLIVE is away', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  assert.ok(index.includes('<script src="/static/lift.js"></script>'));
  assert.ok(index.includes('<link rel="stylesheet" href="/static/lift.css">'));
  assert.ok(index.indexOf('/static/lift.js') > index.indexOf('/static/app.js'), 'after the app, whose door it asks for the conversation');
  const worker = fs.readFileSync(path.join(WEB, 'sw.js'), 'utf8');
  assert.ok(worker.includes("'/static/lift.js'") && worker.includes("'/static/lift.css'"));
});

test('the words are put on the page as text, never as markup, and none names the server or a device', () => {
  const source = fs.readFileSync(path.join(WEB, 'lift.js'), 'utf8');
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(source));
  const css = fs.readFileSync(path.join(WEB, 'lift.css'), 'utf8');
  // One accent, iOS blue; no purple, no yellow.
  for (const colour of css.match(/#[0-9a-fA-F]{3,6}\b|rgba?\([^)]*\)/g) || []) {
    assert.ok(!/#(a855f7|8b5cf6|bf5af2|ffd60a|ffcc00|ff9f0a)/i.test(colour), colour);
  }
  // Everything moves only when motion is welcome.
  assert.ok(css.includes('@media (prefers-reduced-motion:reduce)'));
  assert.ok(css.includes('html[data-lite] .lift-tray'), 'solid, not blurred, on a weak device');
});
