/* CLIVE · CLIVE Shipping: the shipping card.
 *
 * One drawing per view of the "shipping" card the Mac built (app/tools/shipping_views.py `card`):
 *
 *   view "open"     the international orders still going out, counted by stage (the service's own
 *                   tabs), each row with what blocks it or what it waits for; or one stage's orders.
 *   view "one"      one order in full: payment, the label, the print and the carrier, each apart, as
 *                   CLIVE Shipping holds it (also the card after a label is bought or printed).
 *   view "events"   what changed, newest first: on which order, what, who, and whether it was checked.
 *
 * Dots that mean something: blue is something for the owner to do (a ready order's label to buy, a
 * bought label to print), iOS orange is something that stops an order, red is a print that failed or
 * may not have, or an error the service recorded. An order on its way needs nothing: a quiet dot. On
 * the timeline, a filled blue dot is an event the service checked against Shopify, the courier or
 * the printer; a hollow one was only recorded.
 *
 * The same two rules as web/ui.js: every string lands through textContent, never markup, and no
 * attribute is built from what the Mac sent: a row carries its order's own id and number, checked
 * against their shapes, which is what a tap needs and all it gets. No tracking link is drawn: a
 * link's address would be an attribute built from data. No dependency on the rest of the page, so
 * it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveShipping = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const ORDER_REF = /^gid:\/\/shopify\/Order\/\d+$/;
  const NUMBER = /^#\d{1,10}$/;
  const TONE = { ask: 'is-ask', warn: 'is-warn', bad: 'is-bad', quiet: 'is-quiet' };
  const STAGE_TONE = { attention: 'is-warn', ready: 'is-ask', bought: 'is-ask' };

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
  const joined = (parts) => parts.map(text).filter(Boolean).join(' · ');

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

  function when(iso) {
    const t = Date.parse(text(iso));
    if (Number.isNaN(t)) return '';
    const d = new Date(t);
    const day = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'Europe/London' });
    const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London' });
    return `${day} ${time}`;
  }

  function day(iso) {
    const t = Date.parse(text(iso));
    if (Number.isNaN(t)) return '';
    return new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'Europe/London' });
  }

  // What the row says it waits for: what blocks it, else where it is.
  function state(r) {
    const reasons = strings(r.reasons, 6);
    if (text(r.stage) === 'attention') return reasons.length ? reasons.join(' · ') : text(r.status);
    if (text(r.stage) === 'bought' && text(r.print)) return `${text(r.stage_words)} · ${text(r.print)}`;
    if (text(r.stage) === 'in_transit' || text(r.stage) === 'delivered') return joined([r.stage_words, r.carrier !== r.stage_words ? r.carrier : '']);
    return text(r.stage_words) || text(r.status);
  }

  // ------------------------------------------------------------------ one row

  function row(r) {
    const node = h('li', `sh-row ${TONE[text(r.tone)] || 'is-quiet'}`, [
      h('span', 'sh-dot'),
      h('span', 'sh-main', [h('strong', 'sh-number', text(r.order_number) || '—'), text(r.country) ? ' ' : '',
        text(r.country) ? h('span', 'sh-country', text(r.country)) : null]),
      h('span', 'sh-side', text(r.price)),
      h('p', 'sh-state', state(r)),
      joined([r.service, r.tracking_number ? `tracking ${text(r.tracking_number)}` : '']) ? h('p', 'sh-meta', joined([r.service, r.tracking_number ? `tracking ${text(r.tracking_number)}` : ''])) : null,
    ]);
    return opener(node, r.order_id, r.order_number);
  }

  // ------------------------------------------------------------------ the views

  function openBody(d) {
    const rows = list(d.shipments, 25);
    const counts = list(d.counts, 7);
    const out = [];
    if (counts.length && !text(d.stage)) {
      out.push(h('ul', 'sh-counts', counts.map((c) => h('li', `sh-count ${STAGE_TONE[text(c.stage)] || 'is-quiet'}`, [
        h('span', 'sh-dot'), h('span', 'sh-count-n', text(c.count)), ' ', h('span', 'sh-count-w', text(c.words)),
      ]))));
    }
    out.push(rows.length ? h('ol', 'sh-rows', rows.map(row))
      : h('p', 'card-note', text(d.stage) ? 'No orders in this stage.' : 'No international orders are going out.'));
    if (d.truncated) out.push(h('p', 'card-meta', `The first ${rows.length} of ${text(d.total)}.`));
    if (when(d.checked_at)) out.push(h('p', 'card-meta', `CLIVE Shipping, read ${when(d.checked_at)}`));
    return out;
  }

  function fact(label, value, extra, cls) {
    if (!text(value)) return null;
    return h('div', `sh-fact${cls ? ' ' + cls : ''}`, [
      h('dt', 'sh-fact-l', label),
      h('dd', 'sh-fact-v', [text(value), text(extra) ? h('span', 'sh-fact-x', text(extra)) : null]),
    ]);
  }

  function oneBody(d) {
    const found = list(d.shipments, 4);
    if (!found.length) return [h('p', 'card-note', text(d.note) || 'No order found.')];
    return found.map((r) => {
      const label = r.label && typeof r.label === 'object' ? r.label : null;
      const printing = r.printing && typeof r.printing === 'object' ? r.printing : null;
      const carrier = r.carrier_view && typeof r.carrier_view === 'object' ? r.carrier_view : null;
      const printBad = printing && /failed|unknown/.test(text(printing.state));
      return h('div', 'sh-one', [
        h('ol', 'sh-rows', [row(r)]),
        h('dl', 'sh-facts', [
          fact('Payment', r.payment, r.payment_note),
          fact('Service', joined([r.service, r.price])),
          label ? fact('Label', joined([label.provider, label.service]),
            label.tracking_number ? `tracking ${text(label.tracking_number)}` : 'no tracking number yet') : fact('Label', 'Not bought'),
          printing ? fact('Print', printing.label, joined([printing.via, printing.reprints ? `${text(printing.reprints)} extra cop${printing.reprints === 1 ? 'y' : 'ies'}` : '']),
            printBad ? 'is-bad' : '') : null,
          printing && text(printing.error) ? h('p', 'sh-error', text(printing.error)) : null,
          carrier ? fact('Carrier', carrier.label, joined([carrier.note,
            day(carrier.estimated_delivery_at) ? `expected ${day(carrier.estimated_delivery_at)}` : '',
            when(carrier.checked_at) ? `checked ${when(carrier.checked_at)}` : ''])) : null,
        ]),
        strings(r.alerts, 4).length ? h('ul', 'sh-alerts', strings(r.alerts, 4).map((a) => h('li', 'sh-alert', [h('span', 'sh-dot'), h('span', null, a)]))) : null,
        text(r.error) ? h('p', 'sh-error', text(r.error)) : null,
      ]);
    });
  }

  function event(e) {
    return h('li', `sh-ev${e.verified ? ' is-verified' : ''}`, [
      h('span', 'sh-ev-dot'),
      h('span', 'sh-ev-when', when(e.at)),
      h('span', 'sh-ev-what', joined([e.order_number, e.what])),
      text(e.detail) || text(e.by) ? h('span', 'sh-ev-detail', joined([e.detail, text(e.by) ? `by ${text(e.by)}` : ''])) : null,
    ]);
  }

  function eventsBody(d) {
    const events = list(d.events, 30);
    if (!events.length) return [h('p', 'card-note', 'Nothing changed in that time.')];
    const out = [h('ol', 'sh-tl', events.map(event))];
    if (d.truncated) out.push(h('p', 'card-meta', `The newest ${events.length} of ${text(d.total)}.`));
    return out;
  }

  function title(d) {
    const view = text(d.view);
    if (view === 'open') {
      const needs = Number(d.needs_you) || 0;
      if (text(d.stage)) {
        const first = list(d.counts, 1)[0];
        return first ? text(first.words) : 'International orders';
      }
      return needs ? `${needs} ${needs === 1 ? 'order needs' : 'orders need'} you` : 'International orders';
    }
    if (view === 'one') {
      const number = text(d.order_number) || (list(d.shipments, 1)[0] ? text(list(d.shipments, 1)[0].order_number) : '');
      return number ? `${d.tracking ? 'Tracking' : 'Shipping'} for ${number}` : 'Shipping';
    }
    if (view === 'events') return d.hours ? `What changed · last ${text(d.hours)} hours` : 'What changed';
    return 'Shipping';
  }

  function sub(d) {
    const view = text(d.view);
    if (view === 'open') return `${text(d.total || 0)} ${text(d.stage) ? 'orders' : 'going out'}`;
    if (view === 'events') return `${text(d.total || 0)} updates`;
    return '';
  }

  function body(d) {
    const view = text(d.view);
    if (view === 'open') return openBody(d);
    if (view === 'one') return oneBody(d);
    if (view === 'events') return eventsBody(d);
    return [h('p', 'card-note', 'Nothing to show.')];
  }

  return { body, title, sub, row };
});
