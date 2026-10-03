/* Customers as the owner talks about them: the order he meant, their story, a refund landing.
 *
 * Three drawings, each from one bounded payload the Mac built (app/presentation.py):
 *
 *   matchBody(d)     the orders that most nearly fit what he said, when nothing fits all of it
 *                    (app/customers/match.py): each with the one line that says why, and a dot
 *                    per fact — blue for a fact it fits, orange for one it does not. One is the
 *                    answer; two or three come with one short question. A tap opens the order.
 *   timeline(t)      one customer's story, newest first (app/customers/history.py): orders and
 *                    what became of them, email both ways, packing, CLIVE's own changes. A dot
 *                    per row says where it came from. A row about an order or a thread opens it.
 *   refunds(list)    under an order's money: each refund and whether the money has gone back,
 *                    in the payment provider's answer (app/customers/payments.py).
 *
 * The same two rules as web/ui.js: every string lands through textContent, never markup, and no
 * attribute is built from a customer's details — a row carries the record's own id, its kind and
 * its number, which is what a tap needs and all it gets. No dependency on the rest of the page,
 * so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveCustomers = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const ORDER_REF = /^gid:\/\/shopify\/Order\/\d+$/;
  const THREAD_REF = /^[0-9a-f]{6,}$/i;

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
  const strings = (v, n) => (Array.isArray(v) ? v.slice(0, n).map(text).filter(Boolean) : []);

  // A row that opens a record: the record's id and kind, and its number as its name — never a
  // customer's name or email, which the row shows in its text and nowhere else.
  function opener(node, kind, ref, label) {
    const ok = (kind === 'order' && ORDER_REF.test(ref)) || (kind === 'email_thread' && THREAD_REF.test(ref));
    if (!ok) return node;
    node.classList.add('tappable');
    node.setAttribute('role', 'button');
    node.setAttribute('tabindex', '0');
    node.dataset.kind = kind;
    node.dataset.ref = ref;
    if (/^#?\d{1,10}$/.test(label)) node.dataset.label = label;
    return node;
  }

  function day(iso) {
    const t = Date.parse(text(iso));
    if (Number.isNaN(t)) return '';
    const d = new Date(t);
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/London' });
  }

  // ------------------------------------------------------------------ the order he meant

  function factDots(fits, misses) {
    const dots = [];
    for (const f of strings(fits, 5)) dots.push(h('li', 'cm-fact is-fit', [h('span', 'cm-dot'), h('span', 'cm-fact-w', f)]));
    for (const f of strings(misses, 4)) dots.push(h('li', 'cm-fact is-miss', [h('span', 'cm-dot'), h('span', 'cm-fact-w', f)]));
    return dots.length ? h('ul', 'cm-facts', dots) : null;
  }

  function matchRow(r, one) {
    const ref = text(r.order_id);
    const number = text(r.order_number);
    // One statement per fact: the why line names the goods and the day, so the row does not say
    // them again, and the name the row already shows is not repeated at the head of the line.
    const who = text(r.customer_name);
    const why = who && text(r.why).startsWith(`${who} — `) ? text(r.why).slice(who.length + 3) : text(r.why);
    const row = h('li', `row cm-row${one ? ' is-one' : ''}`, [
      h('span', 'row-main', [h('strong', null, number || '—'), ' ', who]),
      h('span', 'row-side', [h('span', 'amount', text(r.total))]),
      h('p', 'cm-why', why || day(r.placed_at)),
      factDots(r.fits, r.misses),
    ]);
    return opener(row, 'order', ref, number);
  }

  function matchBody(d) {
    const rows = list(d.rows, 3);
    const one = text(d.verdict) === 'one';
    return [
      text(d.note) ? h('p', 'card-note cm-note', text(d.note)) : null,
      rows.length ? h('ul', 'rows cm-rows', rows.map((r) => matchRow(r, one))) : h('p', 'card-note', 'Nothing fits well enough to show.'),
      text(d.question) && !one ? h('p', 'cm-question', text(d.question)) : null,
    ];
  }

  // ------------------------------------------------------------------ their story

  const SOURCE_CLASS = { Shopify: 'is-shop', Gmail: 'is-mail', CLIVE: 'is-clive' };

  function timeline(t) {
    if (!t || typeof t !== 'object') return null;
    const rows = list(t.rows, 24);
    const sources = list(t.sources, 8);
    const body = rows.length
      ? h('ol', 'cst-tl', rows.map((r) => {
        const kind = text(r.ref_kind);
        const row = h('li', `cst-row ${SOURCE_CLASS[text(r.source)] || ''} k-${text(r.kind).replace(/[^a-z_]/g, '')}`, [
          h('span', 'cst-dot'),
          h('span', 'cst-when', text(r.when)),
          h('span', 'cst-what', text(r.what)),
          text(r.detail) ? h('span', 'cst-detail', text(r.detail)) : null,
        ]);
        const label = (text(r.what).match(/#\d{1,10}/) || [''])[0];
        return opener(row, kind, text(r.ref), label);
      }))
      : h('p', 'card-note', 'Nothing is recorded about them yet.');
    const said = sources.map((s) => `${text(s.name)}: ${text(s.said)}`).filter((s) => s.length > 2).join(' · ');
    return h('div', 'cst-wrap', [
      body,
      t.truncated ? h('p', 'card-meta', `The newest ${rows.length} of ${text(t.count)} things.`) : null,
      said ? h('p', 'card-meta cst-sources', said) : null,
    ]);
  }

  // ------------------------------------------------------------------ a refund landing

  const STATE_CLASS = { succeeded: 'is-fit', partly: 'is-wait', pending: 'is-wait', failed: 'is-miss', unknown: 'is-wait', recorded: 'is-wait' };

  function refunds(rows) {
    const landed = list(rows, 6).filter((r) => text(r.landed));
    if (!landed.length) return null;
    return h('ul', 'cm-refunds', landed.map((r) => h('li', `cm-refund ${STATE_CLASS[text(r.state)] || 'is-wait'}`, [
      h('span', 'cm-dot'), h('span', 'cm-refund-w', text(r.landed)),
    ])));
  }

  return { matchBody, timeline, refunds };
});
