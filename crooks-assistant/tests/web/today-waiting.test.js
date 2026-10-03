/* "Packed, waiting for tracking" on Today (web/today.js and web/today-owner.js), under Node.
 *
 * The post-deploy review of 3 October: the team rewrite dropped `!job.labelled`, so a job whose order
 * Shopify already called fulfilled (its label was bought) showed, once packed, under "Packed, waiting
 * for tracking" with a Fulfil offer, on the team's page and on George's. What is held: the waiting list
 * leaves such orders out, and both sides of the page build it from that one list, never their own.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.window = globalThis;
globalThis.document = Object.assign(shim.document, { addEventListener() {} });
require(path.join(__dirname, '..', '..', 'web', 'today.js'));
const { waitingForTracking } = globalThis.CliveToday;

const WEB = path.join(__dirname, '..', '..', 'web');
const code = (name) => fs.readFileSync(path.join(WEB, name), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const row = (number, extra) => Object.assign({ ref: 'order:gid://shopify/Order/' + number, kind: 'pack_order',
  order_number: '#' + number, status: 'packed', labelled: false }, extra || {});

test('an order already fulfilled in Shopify is never waiting for tracking', () => {
  const rows = [row(2106), row(2107, { labelled: true }), row(2109, { status: 'claimed' })];
  assert.deepEqual(waitingForTracking(rows).map((r) => r.order_number), ['#2106']);
  assert.deepEqual(waitingForTracking(undefined), []);
});

test("the team's page and George's both build the waiting list from that one list", () => {
  const team = code('today.js');
  const owner = code('today-owner.js');
  assert.match(team, /const waiting = waitingForTracking\(work\.in_hand\)/);
  assert.match(owner, /C\(\)\.waitingForTracking\(state\.work\.in_hand\)/);
  // A list of packed rows made any other way would bring the lost guard back.
  assert.equal((team.match(/status === 'packed'/g) || []).length, 1, 'only inside waitingForTracking');
  assert.equal((owner.match(/status === 'packed'/g) || []).length, 0);
});
