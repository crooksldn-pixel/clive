/* CLIVE · CROOKS Returns: the returns card, an order's returns, and the home's Needs you row.
 *
 * Three drawings, each from one bounded payload the Mac built (app/returns/views.py `card`, and
 * app/presentation.py for an order's), and one small read for the home:
 *
 *   body(d)          the "returns" card: the open returns with what each needs from the owner and
 *                    the paid labels never posted (view "open"); one return in full, where it is
 *                    and its timeline (view "one"); or a period's numbers with the size findings
 *                    (view "stats"). A row about an order opens that order.
 *   onOrder(list)    under an order's money: each return on it, where it stands and what it needs.
 *   brief()          GET /returns/brief, the counts behind the home's row (app/routes/returns.py):
 *                    how many returns need him and why, never who. briefNow() is the last answer.
 *   announce(list)   [returns-events] what just happened that needs him, from the brief's `notices`
 *                    (CROOKS Returns rang CLIVE's door: app/returns/events.py, DEC-077): each shown
 *                    once on this device, through web/notify.js, until he dismisses it. A return to
 *                    approve is a Note, one that needs his look a Check, a failure Failed.
 *
 * Dots that mean something: blue is something for him to answer (a return to approve), iOS
 * orange is something waiting on him that has gone past its time or needs his look (a label
 * overdue, a parcel delivered and not checked, a decision), red is an error CROOKS Returns
 * recorded. A return that needs nothing has a quiet dot.
 *
 * The same two rules as web/ui.js: every string lands through textContent, never markup, and no
 * attribute is built from what the Mac sent — a row carries the order's own id, its kind and its
 * number, checked against their shapes, which is what a tap needs and all it gets. No dependency
 * on the rest of the page, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveReturns = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const ORDER_REF = /^gid:\/\/shopify\/Order\/\d+$/;
  const NUMBER = /^#\d{1,10}$/;
  const TONE = {
    error: 'is-bad', needs_decision: 'is-warn', delivered_unchecked: 'is-warn',
    awaiting_label_overdue: 'is-warn', needs_approval: 'is-ask',
  };

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

  // A row that opens its order: the order's id and number, and only when both are what they should be.
  function opener(node, ref, label) {
    if (!ORDER_REF.test(text(ref))) return node;
    node.classList.add('tappable');
    node.setAttribute('role', 'button');
    node.setAttribute('tabindex', '0');
    node.dataset.kind = 'order';
    node.dataset.ref = text(ref);
    if (NUMBER.test(text(label))) node.dataset.label = text(label);
    return node;
  }

  function tone(attention) {
    const first = strings(attention, 5)[0];
    return TONE[first] || 'is-quiet';
  }

  function day(iso) {
    const t = Date.parse(text(iso));
    if (Number.isNaN(t)) return '';
    return new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'Europe/London' });
  }

  function clock(iso) {
    const t = Date.parse(text(iso));
    if (Number.isNaN(t)) return '';
    return new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' });
  }

  function moneyLine(money) {
    return list(money, 6).map((m) => `${text(m.label)} ${text(m.shown)}`.trim()).filter(Boolean).join(' · ');
  }

  function tracking(r) {
    const number = text(r.tracking);
    return number ? `Tracking ${number}${text(r.carrier) ? ' · ' + text(r.carrier) : ''}` : '';
  }

  // ------------------------------------------------------------------ one row

  function row(r) {
    const needs = strings(r.attention_words, 5);
    const node = h('li', `rt-row ${tone(r.attention)}`, [
      h('span', 'rt-dot'),
      h('span', 'rt-main', [h('strong', 'rt-number', text(r.order_number) || '—'), ' ', h('span', 'rt-who', text(r.customer_name))]),
      h('span', 'rt-side', text(r.resolution)),
      h('p', 'rt-state', needs.length ? needs.join(' · ') : text(r.status_words)),
      text(r.summary) ? h('p', 'rt-what', text(r.summary)) : null,
      moneyLine(r.money) ? h('p', 'rt-money', moneyLine(r.money)) : null,
      tracking(r) ? h('p', 'rt-meta', tracking(r)) : null,
      text(r.error) ? h('p', 'rt-error', text(r.error)) : null,
    ]);
    return opener(node, r.order_id, r.order_number);
  }

  // ------------------------------------------------------------------ the views

  function openBody(d) {
    const rows = list(d.rows, 25);
    const counts = list(d.counts, 5);
    const unused = list(d.unused_labels, 10);
    const out = [];
    if (counts.length) {
      out.push(h('ul', 'rt-counts', counts.map((c) => h('li', `rt-count ${TONE[text(c.key)] || 'is-quiet'}`, [
        h('span', 'rt-dot'), h('span', 'rt-count-n', text(c.count)), ' ', h('span', 'rt-count-w', text(c.words)),
      ]))));
    }
    out.push(rows.length ? h('ol', 'rt-rows', rows.map(row)) : h('p', 'card-note', 'No returns are open.'));
    if (d.truncated) out.push(h('p', 'card-meta', `The first ${rows.length} of ${text(d.open)}.`));
    if (unused.length) {
      out.push(h('section', 'rt-unused', [
        h('p', 'sec-kicker', 'Labels never posted · cancel on parcel2go.com'),
        h('ul', 'rt-rows', unused.map((u) => h('li', 'rt-row is-warn', [
          h('span', 'rt-dot'),
          h('span', 'rt-main', [h('strong', 'rt-number', text(u.order_number) || '—'), ' ', h('span', 'rt-who', text(u.customer_name))]),
          h('span', 'rt-side', text(u.paid)),
          h('p', 'rt-state', [text(u.carrier), text(u.service), u.days !== null && u.days !== undefined ? `bought ${text(u.days)} days ago` : '']
            .filter(Boolean).join(' · ')),
          text(u.parcel2go_order) ? h('p', 'rt-meta', `Parcel2Go order ${text(u.parcel2go_order)}`) : null,
        ]))),
      ]));
    }
    if (clock(d.checked_at)) out.push(h('p', 'card-meta', `CROOKS Returns, read at ${clock(d.checked_at)}`));
    return out;
  }

  function event(e) {
    return h('li', `rt-ev${e.verified ? ' is-verified' : ''}`, [
      h('span', 'rt-ev-dot'),
      h('span', 'rt-ev-when', day(e.at)),
      h('span', 'rt-ev-what', text(e.what)),
      text(e.detail) || text(e.by) ? h('span', 'rt-ev-detail', [text(e.detail), text(e.by) ? `by ${text(e.by)}` : '']
        .filter(Boolean).join(' · ')) : null,
    ]);
  }

  function oneBody(d) {
    const found = list(d.returns, 4);
    if (!found.length) return [h('p', 'card-note', text(d.note) || 'No return found.')];
    return found.map((r) => h('div', 'rt-one', [
      h('ol', 'rt-rows', [row(r)]),
      text(r.where) ? h('p', 'rt-where', text(r.where)) : null,
      list(r.lines, 8).length ? h('ul', 'rt-lines', list(r.lines, 8).map((ln) => h('li', 'rt-line', [
        h('span', 'rt-line-what', [text(ln.title), text(ln.variant) ? ` (${text(ln.variant)})` : ''].join('')),
        h('span', 'rt-line-why', [text(ln.reason), text(ln.exchange_for) ? `swap for ${text(ln.exchange_for)}` : '',
          text(ln.direction)].filter(Boolean).join(' · ')),
      ]))) : null,
      list(r.timeline, 12).length ? h('ol', 'rt-tl', list(r.timeline, 12).map(event)) : null,
      r.timeline_total > list(r.timeline, 12).length ? h('p', 'card-meta', `The newest ${list(r.timeline, 12).length} of ${text(r.timeline_total)} entries.`) : null,
    ]));
  }

  function figure(label, value) {
    return text(value) ? h('div', 'rt-fig', [h('span', 'rt-fig-v', text(value)), h('span', 'rt-fig-l', label)]) : null;
  }

  function counted(title, rows) {
    const items = list(rows, 6).filter((r) => text(r.label));
    if (!items.length) return null;
    return h('section', 'rt-counted', [h('p', 'sec-kicker', title), h('ul', 'rt-bars', items.map((r) => h('li', 'rt-bar', [
      h('span', 'rt-bar-l', text(r.label)), h('span', 'rt-bar-n', text(r.count)),
    ])))]);
  }

  function statsBody(d) {
    const findings = strings(d.findings, 4);
    const products = list(d.products, 8).filter((p) => p.size_up || p.size_down);
    return [
      h('div', 'rt-figs', [figure('kept', d.kept_share), figure('returned', d.value_returned), figure('kept as credit or swap', d.value_kept),
        figure('bonus given', d.bonus_given), figure('label fees recovered', d.label_fees_recovered)]),
      findings.length ? h('ul', 'rt-findings', findings.map((f) => h('li', 'rt-finding', [h('span', 'rt-dot'), h('span', null, f)]))) : null,
      counted('Why they came back', d.reasons),
      counted('Most returned', d.top_skus),
      products.length ? h('section', 'rt-counted', [h('p', 'sec-kicker', 'Size swaps'), h('ul', 'rt-bars', products.map((p) => h('li', 'rt-bar', [
        h('span', 'rt-bar-l', text(p.title)), h('span', 'rt-bar-n', [p.size_up ? `${text(p.size_up)} up` : '', p.size_down ? `${text(p.size_down)} down` : '']
          .filter(Boolean).join(' · ')),
      ])))]) : null,
    ];
  }

  function title(d) {
    const view = text(d.view);
    if (view === 'open') {
      const needs = Number(d.needs_you) || 0;
      return needs ? `${needs} ${needs === 1 ? 'return needs' : 'returns need'} you` : 'Returns';
    }
    if (view === 'one') {
      const found = list(d.returns, 4);
      const number = text(d.order_number) || (found[0] ? text(found[0].order_number) : '');
      return number ? `Return on ${number}` : 'Return';
    }
    if (view === 'stats') return d.days ? `Returns · last ${text(d.days)} days` : 'Returns';
    return 'Returns';
  }

  function sub(d) {
    const view = text(d.view);
    if (view === 'open') return `${text(d.open || 0)} open`;
    if (view === 'stats' && d.returns !== null && d.returns !== undefined) return `${text(d.returns)} returns`;
    return '';
  }

  function body(d) {
    const view = text(d.view);
    if (view === 'open') return openBody(d);
    if (view === 'one') return oneBody(d);
    if (view === 'stats') return statsBody(d);
    return [h('p', 'card-note', 'Nothing to show.')];
  }

  // ------------------------------------------------------------------ on an order card

  function onOrder(rows, note) {
    const found = list(rows, 4);
    if (!found.length) return text(note) ? [h('p', 'card-note', text(note))] : [];
    return found.map((r) => h('div', `rt-on-order ${r.attention_words && r.attention_words.length ? 'is-warn' : 'is-quiet'}`, [
      h('p', 'rt-state', [text(r.resolution), strings(r.attention_words, 5).join(' · ') || text(r.status_words)].filter(Boolean).join(' · ')),
      text(r.where) ? h('p', 'rt-where', text(r.where)) : null,
      moneyLine(r.money) ? h('p', 'rt-money', moneyLine(r.money)) : null,
      text(r.error) ? h('p', 'rt-error', text(r.error)) : null,
    ]));
  }

  // ------------------------------------------------------------------ the home's row

  let last = null;
  async function brief() {
    if (typeof fetch !== 'function') return null;
    try {
      const response = await fetch('/returns/brief', { cache: 'no-store' });
      if (!response.ok) return last;
      const data = await response.json();
      last = data && typeof data === 'object' ? data : null;
    } catch {
      return last;
    }
    if (last) announce(last.notices);   // [returns-events]
    return last;
  }
  function briefNow() { return last; }
  function seed(value) { last = value && typeof value === 'object' ? value : null; }

  // ------------------------------------------------------------------ [returns-events] notices
  // What the Mac's notices are allowed to be: its own handle, one of three names, a tone each name
  // decides here (never the Mac's), and its words. Shown once on this device: the handles shown are
  // kept in this browser (the last 50), so a reload or the next poll never says it twice.
  const NOTICE_ID = /^rn_[0-9a-f]{24}$/;
  const NOTICE_TONE = { return_to_approve: 'info', return_needs_you: 'warn', return_problem: 'bad' };
  const SEEN_KEY = 'clive.returns.notices';
  const MAX_SAID = 3;
  let seen = null;
  // The row each name has on screen and the sentences it holds: a notice of the same kind joins the
  // row that is still up, rather than web/notify.js folding it in and keeping only the newest words.
  const up = {};

  function seenIds() {
    if (seen) return seen;
    seen = new Set();
    try {
      const kept = JSON.parse((root.localStorage && root.localStorage.getItem(SEEN_KEY)) || '[]');
      if (Array.isArray(kept)) for (const id of kept) if (NOTICE_ID.test(text(id))) seen.add(text(id));
    } catch { /* a private window keeps nothing: this page still says each once */ }
    return seen;
  }
  function keepSeen() {
    try { root.localStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(seenIds()).slice(-50))); } catch { /* as above */ }
  }

  function announce(notices) {
    const say = root.CrooksNotify;
    if (!say || typeof say.show !== 'function') return [];
    const fresh = list(notices, 10).filter((n) => NOTICE_ID.test(text(n.id)) && NOTICE_TONE[text(n.code)]
      && text(n.words).trim() && !seenIds().has(text(n.id)));
    const shown = [];
    for (const code of Object.keys(NOTICE_TONE)) {
      const mine = fresh.filter((n) => text(n.code) === code);
      if (!mine.length) continue;
      const before = up[code];
      const still = before && typeof say.list === 'function' && say.list().some((e) => e.id === before.id);
      const all = (still ? before.words : []).concat(mine.map((n) => text(n.words).trim()))
        .filter((w, i, every) => every.indexOf(w) === i);
      const words = all.slice(0, MAX_SAID);
      if (all.length > MAX_SAID) words.push(`And ${all.length - MAX_SAID} more.`);
      if (still && typeof say.dismiss === 'function') say.dismiss(before.id);
      const drawn = say.show({ class: 'workspace', code, tone: NOTICE_TONE[code], text: words.join(' '), persist: true });
      if (!drawn) continue;   // refused or nowhere to draw it: asked again at the next brief
      up[code] = { id: drawn.id, words: all };
      for (const n of mine) seenIds().add(text(n.id));
      shown.push(code);
    }
    if (shown.length) keepSeen();
    return shown;
  }

  return { body, title, sub, onOrder, row, brief, briefNow, seed, announce };
});
