/* Round 13 (the round-12 deploy review, S2b-01): the reply card says where the reply goes.
 *
 * The Mac decides the recipient as the write tool does — the Reply-To when a message names one
 * that is not its sender — and says so in the field's hint, with a button to confirm it
 * (app/families/compose.py). The card used to print its own fixed line under a reply's
 * recipient, "whoever wrote last in this thread — read from the thread, not typed", whatever the
 * Mac said, so a reply going to a Reply-To looked like one going to the sender.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const THREAD = '1b3c5d7e9f0a2c4e';
const ID = 'cmp_ab12cd34ef';

function composer(to, extra) {
  return UI.renderItem({ type: 'email_compose', data: Object.assign({
    compose_id: ID, kind: 'reply', thread_id: THREAD, to, to_name: 'Elsewhere Desk',
    subject: { value: 'Re: About my parcel', status: 'ok', editable: false },
    body: { value: 'It went out today.', status: 'ok', editable: true },
    actions: [
      { id: 'confirm_to', label: 'Yes, reply to this address', command: 'compose.confirm_to', args: `compose_id=${ID}` },
      { id: 'send', label: 'Send', mode: 'stage', risk: 'red', command: 'compose.stage', args: `compose_id=${ID}&mode=send` },
    ],
  }, extra || {}) }, {});
}

test('a reply going to a Reply-To shows the sender beside it, in the Mac\'s own words', () => {
  const node = composer({ value: 'replies@elsewhere.example', status: 'uncertain', editable: false,
    hint: 'sent by ann.sender@example.com, asking for replies here — confirm it below' });
  const to = node.querySelectorAll('.field-static').find((s) => s.dataset.field === 'to');
  const said = to.allText();
  assert.match(said, /replies@elsewhere\.example/);
  assert.match(said, /sent by ann\.sender@example\.com/);
  assert.doesNotMatch(said, /whoever wrote last/, 'the fixed line is not printed over what the Mac said');
});

test('the confirm button posts the Mac\'s command and nothing of the email', () => {
  const node = composer({ value: 'replies@elsewhere.example', status: 'uncertain', editable: false, hint: 'sent by a@x' });
  const confirm = node.querySelectorAll('.compose-btn').find((b) => b.dataset.action === 'confirm_to');
  assert.equal(confirm.dataset.command, 'compose.confirm_to');
  assert.equal(confirm.dataset.args, `compose_id=${ID}`);
});

test('a reply with no hint of its own still says where it goes', () => {
  const node = composer({ value: 'ann.sender@example.com', status: 'ok', editable: false, hint: '' });
  const to = node.querySelectorAll('.field-static').find((s) => s.dataset.field === 'to');
  assert.match(to.allText(), /whoever wrote last in this thread/);
});
