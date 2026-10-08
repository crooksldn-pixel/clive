/* CLIVE · Messages: WeChat and WeCom conversations, in English, with each original one tap away.
 *
 * One drawing, from one bounded payload the Mac built (app/messaging/views.py `card`):
 *
 *   body(d)   view "recent": the latest conversations, each with who it is, when, and its last few
 *             messages; view "thread": one conversation in full, and how long WeChat will still take
 *             a reply in it (48 hours from their last message, five replies).
 *
 * Every message shows its English. When the English is a machine translation it says so, and the
 * words they actually wrote are behind one tap ("Original"); when the translation is missing it
 * says so and shows the original itself. A message CLIVE sent shows the English the owner held and,
 * behind one tap, the Chinese that went with it.
 *
 * Dots that mean something: blue is a conversation WeChat will still take a reply in, red is a
 * message that did not arrive, and a quiet dot is one that can't be answered from CLIVE now.
 *
 * The same two rules as web/ui.js: every string lands through textContent, never markup, and no
 * attribute is built from what the Mac sent. No dependency on the rest of the page, so it runs under
 * Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveMessages = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const MAX_THREADS = 12;
  const MAX_MESSAGES = 30;

  function h(tag, cls, kids) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    add(node, kids);
    return node;
  }
  function add(node, kids) {
    if (kids === null || kids === undefined || kids === false) return;
    if (Array.isArray(kids)) { for (const k of kids) add(node, k); return; }
    node.appendChild(typeof kids === 'string' || typeof kids === 'number' ? doc().createTextNode(String(kids)) : kids);
  }
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v, n) => (Array.isArray(v) ? v.slice(0, n).filter((x) => x && typeof x === 'object') : []);

  // One tap shows what is behind it, a second hides it again. The button says which.
  function reveal(label, hiddenText, cls) {
    const shown = h('p', `msg-behind ${cls || ''}`.trim(), text(hiddenText));
    shown.hidden = true;
    const button = h('button', 'msg-reveal', label);
    button.type = 'button';
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('click', (event) => {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      shown.hidden = !shown.hidden;
      button.setAttribute('aria-expanded', shown.hidden ? 'false' : 'true');
      button.textContent = shown.hidden ? label : `Hide ${label.toLowerCase()}`;
    });
    return [button, shown];
  }

  function message(m) {
    const out = text(m.direction) === 'out';
    const failed = Boolean(text(m.status));
    const bubble = h('li', `msg-bubble ${out ? 'is-out' : 'is-in'}${failed ? ' is-failed' : ''}`);
    const english = text(m.english);
    const original = text(m.original);
    const chinese = text(m.chinese);
    const said = english || original;
    add(bubble, h('p', 'msg-words', said));
    const meta = [];
    const by = text(m.by);
    if (by && by !== 'them') meta.push(by);
    if (text(m.at)) meta.push(text(m.at));
    const translation = text(m.translation);
    if (translation === 'machine translation') meta.push('Machine translation');
    else if (translation === 'missing') meta.push('Translation missing');
    else if (translation) meta.push(`Translation ${translation}`);
    const line = h('div', 'msg-meta', [h('span', 'msg-meta-words', meta.join(' · '))]);
    let behind = null;
    if (english && original && original !== english) {
      const [button, shown] = reveal('Original', original, 'is-original');
      add(line, button);
      behind = shown;
    } else if (chinese) {
      const [button, shown] = reveal('Chinese', chinese, 'is-original');
      add(line, button);
      behind = shown;
    }
    add(bubble, line);
    if (behind) add(bubble, behind);
    if (failed) add(bubble, h('p', 'msg-failed', text(m.status)));
    return bubble;
  }

  function windowLine(t) {
    const words = text(t.reply_window);
    if (!words) return null;
    const open = words.indexOf('open') === 0;
    return h('div', `msg-window ${open ? 'is-open' : 'is-closed'}`, [
      h('span', 'msg-dot', null), h('span', 'msg-window-words', `WeChat replies: ${words}`)]);
  }

  function thread(t, messages) {
    const rows = list(t.messages, messages).map(message);
    return h('ol', 'msg-thread', rows.length ? rows : [h('li', 'msg-none', 'No messages in this conversation yet.')]);
  }

  function recent(d) {
    const threads = list(d.threads, MAX_THREADS);
    if (!threads.length) return [h('p', 'msg-none', text(d.sub) || 'No conversations yet.')];
    return [h('ul', 'msg-threads', threads.map((t) => h('li', 'msg-convo', [
      h('div', 'msg-convo-head', [
        h('span', 'msg-who', text(t.who)),
        h('span', 'msg-side', [text(t.channel), text(t.last)].filter(Boolean).join(' · ')),
      ]),
      text(t.role) ? h('p', 'msg-role', text(t.role)) : null,
      windowLine(t),
      thread(t, 3),
    ])))];
  }

  function body(d) {
    if (text(d.view) === 'thread' && d.thread && typeof d.thread === 'object') {
      return [windowLine(d.thread), thread(d.thread, MAX_MESSAGES)].filter(Boolean);
    }
    return recent(d);
  }

  function title(d) {
    return text(d.title) || 'Messages';
  }

  function sub(d) {
    return text(d.view) === 'thread' ? text(d.sub) : (list(d.threads, 1).length ? text(d.sub) : '');
  }

  return { body, title, sub, message };
});
