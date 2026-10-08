/* The messages card (web/messages.js) through the renderer (web/ui.js), under Node.
 *
 * What it must hold: a message shows its English and says when that is a machine translation; the
 * words they wrote are behind one tap, and a second tap hides them; a missing translation says so
 * and shows the original itself; a message CLIVE sent keeps its Chinese behind one tap; a failed
 * one says it did not arrive; the reply window has a dot that means something; and every string
 * arrives as text, never markup.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
globalThis.CliveMessages = require(path.join(__dirname, '..', '..', 'web', 'messages.js'));
const UI = require(path.join(__dirname, '..', '..', 'web', 'ui.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';

const THREAD = {
  type: 'messages',
  data: {
    key: 'thread:chat_0123456789abcdef0123', view: 'thread', title: 'Jessica', sub: 'WeChat · manufacturer',
    thread: {
      chat_id: 'chat_0123456789abcdef0123', who: 'Jessica', channel: 'WeChat', last: '7 Oct 14:02',
      reply_window: 'open 47h more, 5 replies left',
      messages: [
        { direction: 'in', by: 'them', at: '7 Oct 14:00', english: 'Is the sample ready?', original: '样衣好了吗？',
          translation: 'machine translation' },
        { direction: 'in', by: 'them', at: '7 Oct 14:01', original: '明天发货', translation: 'missing' },
        { direction: 'out', by: 'CLIVE', at: '7 Oct 14:02', english: 'Yes, Monday.', chinese: '是的，周一。' },
        { direction: 'out', by: 'CLIVE', at: '7 Oct 14:03', english: HOSTILE, chinese: '你好',
          status: 'not delivered: they refused the message' },
      ],
    },
  },
};

function all(node, cls) { return node.querySelectorAll(`.${cls}`); }

test('english first, labelled, with the original behind one tap', () => {
  const out = UI.render([THREAD]);
  assert.equal(out.nodes.length, 1);
  const card = out.nodes[0];
  const bubbles = all(card, 'msg-bubble');
  assert.equal(bubbles.length, 4);
  const first = bubbles[0];
  assert.equal(all(first, 'msg-words')[0].textContent, 'Is the sample ready?');
  assert.match(all(first, 'msg-meta-words')[0].textContent, /Machine translation/);
  const [button] = all(first, 'msg-reveal');
  const [behind] = all(first, 'msg-behind');
  assert.equal(button.textContent, 'Original');
  assert.equal(behind.hidden, true);
  assert.equal(behind.textContent, '样衣好了吗？');
  button.dispatch('click');
  assert.equal(behind.hidden, false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(button.textContent, 'Hide original');
  button.dispatch('click');
  assert.equal(behind.hidden, true);
});

test('a missing translation says so and shows the original itself', () => {
  const card = UI.render([THREAD]).nodes[0];
  const second = all(card, 'msg-bubble')[1];
  assert.equal(all(second, 'msg-words')[0].textContent, '明天发货');
  assert.match(all(second, 'msg-meta-words')[0].textContent, /Translation missing/);
  assert.equal(all(second, 'msg-reveal').length, 0);
});

test('what CLIVE sent keeps its Chinese behind a tap, and a failed one says it did not arrive', () => {
  const card = UI.render([THREAD]).nodes[0];
  const [, , sent, failed] = all(card, 'msg-bubble');
  assert.match(sent.className, /is-out/);
  assert.equal(all(sent, 'msg-reveal')[0].textContent, 'Chinese');
  assert.equal(all(sent, 'msg-behind')[0].textContent, '是的，周一。');
  assert.match(failed.className, /is-failed/);
  assert.equal(all(failed, 'msg-failed')[0].textContent, 'not delivered: they refused the message');
  assert.equal(all(failed, 'msg-words')[0].textContent, HOSTILE);           // text, never markup
  assert.equal(failed.querySelectorAll('img').length, 0);
});

test('the reply window has a dot that means open', () => {
  const card = UI.render([THREAD]).nodes[0];
  const [line] = all(card, 'msg-window');
  assert.match(line.className, /is-open/);
  assert.equal(all(line, 'msg-window-words')[0].textContent, 'WeChat replies: open 47h more, 5 replies left');
  const closed = JSON.parse(JSON.stringify(THREAD));
  closed.data.thread.reply_window = 'closed: their last message was over 48 hours ago';
  assert.match(all(UI.render([closed]).nodes[0], 'msg-window')[0].className, /is-closed/);
});

test('the recent conversations, each with its last messages, and an empty list says so', () => {
  const recent = { type: 'messages', data: { key: 'recent', view: 'recent', title: 'Messages', sub: '',
    threads: [THREAD.data.thread, { ...THREAD.data.thread, who: 'Forwarder', reply_window: '', messages: [] }] } };
  const card = UI.render([recent]).nodes[0];
  assert.deepEqual(all(card, 'msg-who').map((n) => n.textContent), ['Jessica', 'Forwarder']);
  assert.equal(all(card, 'msg-none')[0].textContent, 'No messages in this conversation yet.');
  const empty = { type: 'messages', data: { key: 'recent', view: 'recent', title: 'Messages', sub: 'No messages have come in on WeCom yet.', threads: [] } };
  assert.equal(all(UI.render([empty]).nodes[0], 'msg-none')[0].textContent, 'No messages have come in on WeCom yet.');
});

// [channels] WhatsApp and Instagram (8 Oct): the window line names the app the payload names; a reply
// sent in their language keeps it behind "As sent"; delivered and read show on CLIVE's own message
// only, and never on one that failed.
const WHATSAPP = {
  type: 'messages',
  data: {
    key: 'thread:chat_aaaaaaaaaaaaaaaaaaaa', view: 'thread', title: 'Ana', sub: 'WhatsApp · knitwear supplier',
    thread: {
      chat_id: 'chat_aaaaaaaaaaaaaaaaaaaa', who: 'Ana', channel: 'WhatsApp', last: '8 Oct 09:00',
      reply_window: 'open 20h more',
      messages: [
        { direction: 'in', by: 'them', at: '8 Oct 08:58', english: 'The sample is ready.', original: 'A amostra está pronta.',
          translation: 'machine translation' },
        { direction: 'out', by: 'CLIVE', at: '8 Oct 09:00', english: 'Thank you.', translated: 'Obrigado.', delivery: 'Read' },
        { direction: 'out', by: 'the WhatsApp app', at: '8 Oct 09:01', english: 'See you Friday.' },
        { direction: 'out', by: 'CLIVE', at: '8 Oct 09:02', english: 'Hello.', delivery: 'Delivered',
          status: 'not delivered: WhatsApp didn\'t say why' },
      ],
    },
  },
};

test('the window line names the app, and a reply in their language keeps it behind "As sent"', () => {
  const card = UI.render([WHATSAPP]).nodes[0];
  assert.equal(all(all(card, 'msg-window')[0], 'msg-window-words')[0].textContent, 'WhatsApp replies: open 20h more');
  const [, sent, fromApp, failed] = all(card, 'msg-bubble');
  assert.equal(all(sent, 'msg-reveal')[0].textContent, 'As sent');
  assert.equal(all(sent, 'msg-behind')[0].textContent, 'Obrigado.');
  assert.match(all(sent, 'msg-meta-words')[0].textContent, /CLIVE · 8 Oct 09:00 · Read/);
  assert.match(all(fromApp, 'msg-meta-words')[0].textContent, /the WhatsApp app/);
  assert.doesNotMatch(all(failed, 'msg-meta-words')[0].textContent, /Delivered/);
  const nameless = JSON.parse(JSON.stringify(WHATSAPP));
  delete nameless.data.thread.channel;
  assert.equal(all(UI.render([nameless]).nodes[0], 'msg-window-words')[0].textContent, 'Replies: open 20h more');
});
