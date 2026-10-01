/* The component vocabulary, rendered by hand.
 *
 * The backend sends `ui`: a list of { type, data } items chosen from a fixed vocabulary and
 * built from what the tools returned (app/presentation.py). This file turns those into DOM,
 * and it is the only file that does. Two rules hold throughout:
 *
 *   - Every string from outside — a customer's name, an email body, a product title — lands
 *     in the page through textContent. No innerHTML, no template strings into markup, no
 *     attribute built from data. What arrives as "<img onerror>" is shown as "<img onerror>".
 *   - Only the types listed in RENDERERS render. Anything else is reported as skipped and
 *     draws nothing. Claude cannot ask for a component; the presentation layer can.
 *
 * The file has no dependency on the rest of the app so that it can be exercised under Node
 * against a small DOM stand-in (tests/web/), where the two rules above are checked.
 */
(function (root, factory) {
  const api = factory();
  root.CrooksUI = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);

  // ------------------------------------------------------------------ safe DOM

  function h(tag, attrs, children) {
    const el = doc().createElement(tag);
    if (attrs) {
      for (const key in attrs) {
        const value = attrs[key];
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = String(value);
        else if (key === 'hidden') el.hidden = Boolean(value);
        else if (key === 'on' && typeof value === 'object') {
          for (const type in value) el.addEventListener(type, value[type]);
        } else if (key === 'data' && typeof value === 'object') {
          // Absent, not "null". Every other attribute here is dropped when its value is null
          // or undefined; `data` stringified it, so `{ ref: staged ? text(ref) : null }` wrote
          // `data-ref="null"` onto every chip that was not staged. That is not cosmetic: the
          // page has one delegated handler for `[data-command]`, so the instant a rail chip
          // carried `data-command="null"` every chip on every card posted the command "null"
          // to the Mac and got a 400 — an entire class of control quietly broken by a
          // ternary. A key with nothing behind it is simply not set.
          for (const d in value) {
            if (value[d] === null || value[d] === undefined) continue;
            el.dataset[d] = String(value[d]);
          }
        } else el.setAttribute(key, String(value));
      }
    }
    append(el, children);
    return el;
  }

  function append(el, children) {
    if (children === null || children === undefined || children === false) return;
    if (Array.isArray(children)) { for (const c of children) append(el, c); return; }
    if (typeof children === 'string' || typeof children === 'number') {
      el.appendChild(doc().createTextNode(String(children)));
      return;
    }
    el.appendChild(children);
  }

  const text = (value, fallback) => {
    if (value === null || value === undefined || value === '') return fallback === undefined ? '' : fallback;
    return String(value);
  };
  const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
  const list = (value, limit) => (Array.isArray(value) ? value.slice(0, limit || 50).filter((v) => v && typeof v === 'object') : []);
  // The same bound, for the fields the backend sends as plain strings. `list` drops anything
  // that is not an object — which is right for rows and wrong, silently, for an array of
  // sentences: the capability card's "Try asking" chips and the whole "Since the last build"
  // section were filtered to nothing and never appeared on screen at all, while the code that
  // draws them read as though they did.
  const strings = (value, limit) => (Array.isArray(value) ? value.slice(0, limit || 50).map((v) => text(v)).filter(Boolean) : []);

  // ------------------------------------------------------------------ formatting

  const DATE_FMT = { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' };
  const DAY_FMT = { day: 'numeric', month: 'short' };
  const DATE_DAY_YEAR = { day: 'numeric', month: 'short', year: 'numeric' };

  function formatDate(value, opts) {
    const raw = text(value);
    if (!raw) return '';
    const ms = Date.parse(raw);
    if (!Number.isFinite(ms)) return raw;
    try {
      return new Intl.DateTimeFormat('en-GB', opts || DATE_FMT).format(new Date(ms));
    } catch (error) {
      return raw;
    }
  }

  const STATUS_TONE = {
    fulfilled: 'ok', paid: 'ok', success: 'ok', delivered: 'ok', active: 'ok',
    unfulfilled: 'warn', 'partially fulfilled': 'warn', pending: 'warn', authorized: 'warn',
    'partially paid': 'warn', 'in progress': 'warn', 'on hold': 'warn', scheduled: 'warn',
    refunded: 'bad', 'partially refunded': 'bad', voided: 'bad', cancelled: 'bad', failure: 'bad',
    error: 'bad', restocked: 'bad',
  };
  const tone = (status) => STATUS_TONE[text(status).toLowerCase()] || '';

  function badge(label, cls) {
    const value = text(label);
    if (!value) return null;
    return h('span', { class: `badge ${cls || tone(value)}`.trim(), text: value });
  }

  function kicker(label) { return h('p', { class: 'card-kicker', text: label }); }

  // Two letters from a name, for the avatar disc that makes a person read as a person.
  function initials(name) {
    const parts = text(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '·';
    return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  function avatar(name, cls) { return h('span', { class: `avatar${cls ? ' ' + cls : ''}`, 'aria-hidden': 'true', text: initials(name) }); }

  // An order's life as a strip of steps, lit as far as it has got. What a packer looks for
  // first, before the number: has it been paid, has it gone.
  function orderTimeline(d) {
    const pay = text(d.payment).toLowerCase();
    const ful = text(d.fulfillment).toLowerCase();
    const shipped = list(d.fulfillments, 6).map((f) => f.shipped_at).filter(Boolean)[0];
    const cancelled = Boolean(d.cancelled_at);
    const steps = [
      { label: 'Placed', done: true, when: formatDate(d.placed_at, DAY_FMT) },
      { label: 'Paid', done: pay === 'paid' || pay === 'partially refunded' || pay === 'partially_refunded' || pay === 'refunded', partial: pay === 'partially paid' || pay === 'partially_paid' || pay === 'authorized' },
      cancelled
        ? { label: 'Cancelled', done: true, bad: true, when: formatDate(d.cancelled_at, DAY_FMT) }
        : { label: ful === 'fulfilled' ? 'Shipped' : 'To ship', done: ful === 'fulfilled', partial: ful === 'partial' || ful === 'partially fulfilled' || ful === 'partially_fulfilled', when: shipped ? formatDate(shipped, DAY_FMT) : '' },
    ];
    return h('ol', { class: 'tl', 'aria-label': 'Order progress' }, steps.map((st) => h('li', {
      class: `tl-step${st.done ? ' is-done' : ''}${st.partial ? ' is-partial' : ''}${st.bad ? ' is-bad' : ''}`,
    }, [h('span', { class: 'tl-dot', 'aria-hidden': 'true' }), h('span', { class: 'tl-label', text: st.label }), st.when ? h('span', { class: 'tl-when', text: st.when }) : null])));
  }

  function kv(pairs, opts) {
    const dl = h('dl', { class: 'kv' });
    for (const [k, v, cls] of pairs) {
      const value = text(v);
      if (!value) continue;
      dl.appendChild(h('dt', { text: k }));
      dl.appendChild(h('dd', { class: cls || null, text: value }));
    }
    return dl.childNodes && dl.childNodes.length === 0 && !opts ? null : dl;
  }

  // A card that can be held and put on a screen (web/lift.js) can be reached from the keyboard too:
  // focused, the context-menu key or Shift+F10 opens the same Displays tray a held finger does.
  function holdable(node) {
    if (node && text(node.dataset.ref)) node.setAttribute('tabindex', '0');
    return node;
  }

  function card(kind, children, opts) {
    opts = opts || {};
    const el = h('article', { class: `card card-${kind}${opts.className ? ' ' + opts.className : ''}`, data: { type: kind } }, children);
    if (opts.fixture) {
      el.classList.add('is-fixture');
      el.appendChild(h('span', { class: 'fixture-tag', text: 'Fixture · not live' }));
    }
    return el;
  }

  // ---------------------------------------------------------------- the shell (§7, D-5)
  //
  // A card that has not arrived yet. `turn_c8eb4cffe077` put NOTHING on the glass for 7,975
  // ms because the workspace was presented once, after the whole read graph resolved; the Mac
  // now stages a skeleton the moment it knows what kind of thing is coming (app/progressive.py)
  // and the real card takes its place. There is no skeleton TYPE — a shell is an ordinary
  // card whose data says `shell` — so the vocabulary the two sides agree on does not grow.
  //
  // It says what is coming and nothing else. A placeholder must never look like a value: the
  // bars carry no text at all, so there is no number on this screen that is not a number the
  // Mac read.
  function skeletonCard(kind, d, opts) {
    const rows = Math.max(1, Math.min(6, num(d.placeholder) === null ? 3 : d.placeholder));
    const bars = [];
    for (let i = 0; i < rows; i++) bars.push(h('span', { class: 'sk-row', 'aria-hidden': 'true' }));
    const node = card(kind, [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker(text(d.title, 'Reading')),
        h('p', { class: 'sk-note', text: 'Reading…' }),
      ])]),
      h('div', { class: 'sk-body' }, bars),
    ], Object.assign({ className: 'is-shell' }, opts || {}));
    node.dataset.shell = '1';
    node.setAttribute('aria-busy', 'true');
    return node;
  }

  // ---------------------------------------------------------------- the workspace itself (§15, §27)
  //
  // What Phase 4 got wrong about progressive rendering: it put grey boxes up and called that
  // progress. An empty box says nothing, so there is nothing on it to read. A compound task
  // establishes its IDENTITY first — what this workspace is, and one line per section, each
  // in a state —
  //
  //     TODAY'S ACTIVITY
  //     Orders        loading…
  //     Inbox         waiting…
  //
  // — and then each line is patched in place as its read lands: `Orders · 7`, `Inbox · 4`.
  // The card is ONE card for the life of the turn (identity `workspace_plan:<turn>`), so a
  // section arriving patches this node and never replaces the workspace, never reorders it
  // and never duplicates it.
  //
  // §27's five states, in words rather than colour alone. EMPTY IS NOT ERROR: a read that
  // found nothing says what it looked for and found none of, and the workspace stays.
  const PLAN_WORDS = { loading: 'loading…', waiting: 'waiting…', ready: '', empty: 'none', error: 'unavailable', partial: '' };
  const PLAN_STATE = { loading: 'Working', partial: 'Part way', ready: 'Ready', empty: 'Nothing found', error: 'Could not read' };

  function renderWorkspacePlan(d, opts) {
    const sections = list(d.sections, 6);
    const state = text(d.state, 'loading');
    const rows = sections.map((s) => {
      const name = text(s.name);
      const at = text(s.state, 'waiting');
      // The count when the Mac has read one, the section's own sentence when it found none
      // or could not be read, and the state's word while it is still coming. Never both, and
      // never a number that is not a number the Mac read.
      const said = text(s.value) || text(s.note) || PLAN_WORDS[at] || at;
      return h('li', {
        class: `row${at === 'error' ? ' bad' : ''}`, data: { section: name, state: at },
      }, [
        h('span', { class: 'row-main', text: text(s.label, name) }),
        h('span', { class: 'row-side' }, [h('span', { class: 'card-meta', text: said })]),
      ]);
    });
    const node = card('workspace_plan', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker(PLAN_STATE[state] || 'Working'),
        h('h2', { class: 'card-title', text: text(d.title, 'Workspace') }),
      ])]),
      rows.length ? h('ul', { class: 'rows tight' }, rows) : null,
    ], opts);
    node.dataset.state = state;
    if (state === 'loading' || state === 'partial') node.setAttribute('aria-busy', 'true');
    return node;
  }

  // A read that found nothing (D-15). `turn_69abe877ef14` asked for yesterday's orders, the
  // read came back with none, and the presentation layer drew NO CARD — one sentence over a
  // blank screen, recorded by the analyser as "(records without a card)". "None" is an answer
  // about the shop and it belongs on the glass, under the question it answers.
  function emptyNote(d) {
    if (d.empty !== true) return null;
    return h('p', { class: 'card-note empty-line', text: text(d.note, 'Nothing to show.') });
  }

  // The Mac's window ends at the start of the day after it ("until", exclusive). The day the
  // owner sees as the end is the one before that.
  function lastDayOf(until) {
    const ms = Date.parse(String(until || ''));
    return Number.isFinite(ms) ? new Date(ms - 1).toISOString() : until;
  }

  // ---------------------------------------------------------------- which tab (D-2)
  //
  // The owner's loudest complaint of the live session, at 20:18:12: "I'm not seeing any UI
  // here except email where there's nothing … I want to also be seeing his orders and his
  // history". It was all there, one tab away on the same card.
  //
  // `renderOpts().tab` was ONE value per BRANCH, handed to every card that had tabs. He
  // tapped Email once, on one customer, early in the session; from that moment every customer
  // card on that branch opened on Email — all seven cards of turn_be1b384ca420 included, for
  // seven customers he had never opened. The Email tab was tapped TWICE all session and was
  // active on 23 rendered cards, usually over an empty panel.
  //
  // So a tab belongs to a RECORD, and this is the only place that decides which one a card
  // opens on. It returns the candidates IN ORDER, and `tabs()` opens the first of them the
  // card actually has — a tab named for a workspace that does not have it falls through to
  // the next answer rather than to nothing:
  //
  //   1. `opts.tabNow` — the tab THIS card is open on at this moment. A patch that landed
  //      while the owner was reading Orders does not move him to Email (applyPatches).
  //   2. `opts.tabOf(id)` — the tab the owner left THIS record on, by render identity
  //      (web/app.js `cardTabs`, the Mac's copy in `branch.tabs`). Returning to a card he
  //      had left on a tab restores that card's tab, and his own choice about a record
  //      outranks the one composed for him.
  //   3. `d.tab` — the tab the TASK implies, composed by the Mac for THIS card and no other
  //      (app/presentation.py; `tab` is visual state in app/render.py, so naming it does not
  //      redraw the card). A request naming orders opens Orders on a record he has never
  //      opened.
  //   4. nothing: the card's own first panel.
  //
  // At no step is it a tab tapped on a different record. `opts.tab` is the same answer as a
  // single value, resolved PER CARD by `renderItem` before a renderer is called, so a
  // renderer that reads it cannot get a deck-wide value: there is no longer one to get.
  function tabFor(kind, d, opts) {
    const settings = opts || {};
    const wanted = [text(settings.tabNow), ownerTab(kind, d, settings), text(d && d.tab)];
    return wanted.filter(Boolean);
  }

  // The owner's own choice about this record, and nothing else — what `opts.tab` carries for
  // a renderer that asks for one value (the workspace cards of app/presentation.py let it
  // outrank the tab they composed, and fall back to that when it names a tab they lack).
  function ownerTab(kind, d, opts) {
    const settings = opts || {};
    if (text(settings.tabNow)) return text(settings.tabNow);
    if (typeof settings.tabOf !== 'function') return '';
    return text(settings.tabOf(surfaceId({ type: kind, data: d || {} }), kind));
  }

  // Report a tap to whoever is keeping the record's tab, naming the RECORD it was on — the
  // render identity, which is the same name the patch protocol addresses the card by.
  function tabReporter(kind, d, opts) {
    if (!opts || typeof opts.onTab !== 'function') return null;
    const id = surfaceId({ type: kind, data: d || {} });
    return (name, label) => opts.onTab(id, name, label, kind);
  }

  // A card of tabs. panels: [{ name, label, node }]. One panel is open at a time, which is
  // what keeps an order card the height of the screen instead of seven thousand pixels.
  //
  // `opts.initial` opens a named panel — decided by `tabFor` above, per card, never per
  // branch. `opts.onChange(name)` is called when the owner moves, so the page can remember
  // where he left THIS record and tell the Mac. The wrapper carries data-tab, so nothing has
  // to be scraped out of the DOM to know.
  function tabs(panels, opts) {
    const settings = opts || {};
    const kept = panels.filter((p) => p && p.node);
    const wrap = h('div', { class: 'tabbed' });
    if (!kept.length) return wrap;
    let open = 0;
    // `initial` is one name or, from `tabFor`, the candidates in order: the first one this
    // card actually HAS is the one that opens. A tab named for a record whose card does not
    // carry it — an order left on Shipping, drawn later without a shipping panel — falls
    // through to the next answer rather than silently to the first panel.
    for (const name of [].concat(settings.initial || [])) {
      const found = text(name) && kept.findIndex ? kept.findIndex((p) => p.name === text(name)) : -1;
      if (found >= 0) { open = found; break; }
    }
    const bar = h('div', { class: 'tabs', role: 'tablist' });
    const bodies = [];
    const show = (i) => {
      bodies.forEach((b, j) => {
        b.body.hidden = j !== i;
        b.tab.setAttribute('aria-selected', j === i ? 'true' : 'false');
      });
      wrap.dataset.tab = kept[i].name || String(i);
      if (typeof settings.onChange === 'function') settings.onChange(kept[i].name || String(i), kept[i].label);
    };
    kept.forEach((p, i) => {
      const body = h('div', { class: 'panel', role: 'tabpanel', hidden: i !== open, data: { panel: p.name || String(i) } }, p.node);
      const tab = h('button', {
        class: 'tab', type: 'button', role: 'tab', 'aria-selected': i === open ? 'true' : 'false', text: p.label,
        data: { tab: p.name || String(i) },
        on: { click: () => show(i) },
      });
      bodies.push({ body, tab });
      bar.appendChild(tab);
    });
    wrap.dataset.tab = kept[open].name || String(open);
    append(wrap, [bar, bodies.map((b) => b.body)]);
    return wrap;
  }

  // A region of a card behind one control: the thread's older messages, a long tail of rows.
  // The same discipline as `folded` below and deliberately not the same thing — `folded` wraps
  // a WHOLE CARD the Mac marked secondary, this is part of one. Nothing is removed: the body
  // is complete and in the DOM, and the header says what is inside it.
  function disclosure(node, label) {
    const body = h('div', { class: 'disc-body' }, node);
    body.hidden = true;
    const btn = h('button', { class: 'disc-head', type: 'button', 'aria-expanded': 'false' }, [
      h('span', { class: 'disc-label', text: label || 'More' }),
      h('span', { class: 'disc-mark', text: '+', 'aria-hidden': 'true' }),
    ]);
    btn.addEventListener('click', () => {
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', open ? 'false' : 'true');
      body.hidden = open;
      btn.querySelector('.disc-mark').textContent = open ? '+' : '−';
    });
    return h('section', { class: 'disc' }, [btn, body]);
  }

  function expandable(el, label) {
    // A clamp with a "more" control, for long bodies. Nothing is hidden from the reader.
    el.classList.add('clamp');
    const btn = h('button', { class: 'link-btn', type: 'button', text: label || 'More', on: { click: () => {
      const open = el.classList.toggle('is-open');
      btn.textContent = open ? 'Less' : (label || 'More');
    } } });
    return [el, btn];
  }

  // ------------------------------------------------------------------ components

  function renderAssistant(d) {
    const body = h('p', { class: 'card-body', text: text(d.text) });
    return card('assistant', [kicker('Assistant'), text(d.text).length > 420 ? expandable(body) : body]);
  }

  // A row that names an order opens it. The id has always been on the wire; nothing on the
  // page ever used it, so the list was a picture of the orders rather than a way into them —
  // the only route to #1938 from a list of today's orders was to say its number out loud.
  // `data-ref` and `data-kind` are what the deck's click handler posts to `open.entity`, which
  // is the same command the word "open that one" reaches.
  // Which state a row is in, for the list's own filter chips. Three words, from the two
  // status strings the Mac already sent — never a new fact about the order.
  function orderState(o) {
    if (o.cancelled_at) return 'cancelled';
    return text(o.fulfillment).toLowerCase() === 'fulfilled' ? 'shipped' : 'to-ship';
  }

  function orderRow(o) {
    const ref = text(o.order_id);
    return h('li', {
      class: ref ? 'row tappable' : 'row', role: ref ? 'button' : null, tabindex: ref ? '0' : null,
      /* `label` is what this record will be CALLED once it is opened: on the half chip, in
         the band above the cards and on the trail. Said here, where the number and the name
         are known, so the tap does not have to infer one from the row's text — which is how
         "#1927 Fionn Doherty28 Aug, 23:00£83.0…" reached the glass (web/app.js labelOf). */
      data: Object.assign({ state: orderState(o) },
        ref ? { ref, kind: 'order', label: `${text(o.order_number, '—')} ${text(o.customer_name)}`.trim() } : {}),
    }, [
      h('span', { class: 'row-main' }, [h('strong', { text: text(o.order_number, '—') }), ' ', text(o.customer_name)]),
      h('span', { class: 'row-sub', text: formatDate(o.placed_at) }),
      h('span', { class: 'row-side' }, [h('span', { class: 'amount', text: text(o.total) }), badge(o.fulfillment)]),
      ref ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }) : null,
    ]);
  }

  // ---- images. A card carries an image only as a path the Mac signed for it; the renderer
  // draws nothing for any other source. In fixture mode a small inline SVG stands in, so the
  // developer grid can show what a thumbnail looks like without a store behind it.
  const MEDIA_PATH = /^\/media\/shopify\/[0-9a-f]{32}\/\d{3}\?u=[A-Za-z0-9%._~-]+$/;
  const FIXTURE_IMAGE = /^data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+$/;

  function imageSource(value, opts) {
    const src = text(value);
    if (MEDIA_PATH.test(src)) return src;
    if (opts && opts.fixture && FIXTURE_IMAGE.test(src)) return src;
    return '';
  }

  function thumb(item, opts) {
    const box = h('span', { class: 'thumb', 'aria-hidden': 'true' }, [
      h('span', { class: 'thumb-mono', text: (text(item.title).trim().charAt(0) || '·').toUpperCase() }),
    ]);
    const src = imageSource(item.image, opts);
    if (src) {
      const img = h('img', { class: 'thumb-img', alt: '', loading: 'lazy', decoding: 'async', width: '64', height: '64', referrerpolicy: 'no-referrer' });
      img.addEventListener('load', () => box.classList.add('is-loaded'));
      img.addEventListener('error', () => box.classList.add('is-missing'));
      img.setAttribute('src', src);
      box.appendChild(img);
    }
    return box;
  }

  function stockWords(stock) {
    if (!stock || typeof stock !== 'object') return '';
    if (stock.tracked === false) return 'untracked';
    const n = num(stock.available);
    if (n === null) return '';
    if (n < 0) return `oversold by ${-n}`;
    if (n === 0) return 'none left';
    return `${n} left`;
  }
  function stockTone(stock) {
    if (!stock || typeof stock !== 'object' || stock.tracked === false) return '';
    const n = num(stock.available);
    if (n === null) return '';
    return n <= 0 ? 'bad' : n <= 5 ? 'warn' : '';
  }

  function section(kind, label, children, extra) {
    return h('section', { class: `sec sec-${kind}`, 'aria-label': label }, [
      h('p', { class: 'sec-kicker' }, [h('span', { text: label }), extra || null]),
    ].concat(children || []));
  }

  function itemsList(items, opts, truncated) {
    const rows = items.map((it) => h('li', { class: 'item' }, [
      thumb(it, opts),
      h('span', { class: 'item-main' }, [
        h('span', { class: 'item-title', text: text(it.title, '—') }),
        h('span', { class: 'item-sub', text: [text(it.variant), it.sku ? `SKU ${text(it.sku)}` : ''].filter(Boolean).join(' · ') }),
      ]),
      h('span', { class: 'item-side' }, [
        h('span', { class: 'amount', text: [num(it.quantity) !== null && it.quantity > 1 ? `× ${it.quantity}` : '', text(it.total)].filter(Boolean).join('  ') }),
        stockWords(it.stock) ? h('span', { class: `item-stock ${stockTone(it.stock)}`.trim(), text: stockWords(it.stock) }) : null,
      ]),
    ]));
    if (truncated) rows.push(h('li', { class: 'item item-more', text: 'More items than shown.' }));
    // The same rule the order list and the thread keep (ROWS_BEFORE_FOLD): the first few rows,
    // then the tail behind one control. A twelve-item order was 757 px of a 699 px first
    // screen once the deck stopped scrolling under the dock — the two fixes landed in the same
    // pass and the second one took back the 112 px the first had been borrowing. Nothing is
    // removed: every row is in the DOM and one tap away.
    if (rows.length <= ROWS_BEFORE_FOLD + 1) return h('ul', { class: 'items' }, rows);
    const shown = rows.slice(0, ROWS_BEFORE_FOLD);
    const tail = rows.slice(ROWS_BEFORE_FOLD);
    return h('div', { class: 'items-wrap' }, [
      h('ul', { class: 'items' }, shown),
      disclosure(h('ul', { class: 'items' }, tail), `${tail.length} more item${tail.length === 1 ? '' : 's'}`),
    ]);
  }

  function moneyBlock(d) {
    const m = d.money && typeof d.money === 'object' ? d.money : {};
    const zero = (v) => /^[^0-9]*0(?:\.00?)?$/.test(text(v));
    const pairs = [['Subtotal', m.subtotal], ['Shipping', m.shipping], ['Tax', m.tax]];
    if (m.discounts && !zero(m.discounts)) pairs.push(['Discounts', m.discounts]);
    if (m.refunded && !zero(m.refunded)) pairs.push(['Refunded', m.refunded, 'bad']);
    if (m.outstanding && !zero(m.outstanding)) pairs.push(['Outstanding', m.outstanding, 'warn']);
    pairs.push(['Total', d.total, 'total']);
    const dl = h('dl', { class: 'money' });
    for (const [k, v, cls] of pairs) {
      const value = text(v);
      if (!value) continue;
      dl.appendChild(h('dt', { text: k }));
      dl.appendChild(h('dd', { class: cls || null, text: value }));
    }
    return dl.childNodes.length ? dl : null;
  }

  function addressLines(a) {
    if (!a || typeof a !== 'object') return [];
    const streets = Array.isArray(a.lines) ? a.lines.slice(0, 3).map((l) => text(l)).filter(Boolean) : [];
    const town = [text(a.city), text(a.zip)].filter(Boolean).join(' ');
    return [text(a.name), text(a.company)].concat(streets, [town, text(a.province), text(a.country)]).filter(Boolean);
  }

  function addressBlock(a) {
    const rows = addressLines(a);
    if (!rows.length) return h('p', { class: 'card-note', text: 'No shipping address on the order.' });
    return h('address', { class: 'addr' }, rows.map((line) => h('span', { class: 'addr-line', text: line })));
  }

  function shippingBlock(d) {
    const fulfils = list(d.fulfillments, 6);
    const tracking = fulfils.length
      ? h('ul', { class: 'rows' }, fulfils.map((f) => h('li', { class: 'row' }, [
        h('span', { class: 'row-main', text: [text(f.carrier), text(f.number)].filter(Boolean).join(' · ') || 'Shipment' }),
        h('span', { class: 'row-sub', text: formatDate(f.shipped_at) }),
        h('span', { class: 'row-side' }, [badge(f.status)]),
      ])))
      : h('p', { class: 'card-note', text: d.cancelled_at ? 'Not shipped.' : 'Not shipped yet.' });
    return [
      d.shipping_method ? h('p', { class: 'ship-method', text: text(d.shipping_method) }) : null,
      addressBlock(d.shipping_address),
      tracking,
    ];
  }

  // ---- the customer's history, beside their order or on their own card.
  // Where a customer id may be tapped from: the shape, checked here because the renderer
  // cannot ask the Mac anything. The PERMISSION half is the Mac's — app/presentation.py
  // issues an order's customer id when it draws the order, which is what makes this control
  // resolvable rather than a `not_held` refusal (§18).
  const CUSTOMER_REF = /^gid:\/\/shopify\/Customer\/\d+$/;

  // The one control that walks from an ORDER to its CUSTOMER.
  //
  // The click-path audit found path 1 dead at step 4 of 8: an order card with its Customer
  // tab open offered nothing that opened the customer. Everything tappable in that tab went
  // to another ORDER. So the tab that is about a person now starts with a door to them, in
  // the same shape the email thread's card already uses for the same hop (`link-customer`).
  function customerDoor(who) {
    const ref = text((who || {}).customer_id);
    if (!CUSTOMER_REF.test(ref)) return null;
    return h('button', {
      class: 'link-chip link-customer', type: 'button', data: { ref, kind: 'customer' },
    }, [
      h('span', { class: 'link-chip-label', text: text((who || {}).customer_name, 'Open the customer') }),
      h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }),
    ]);
  }

  function historyBlock(hist, who) {
    const door = customerDoor(who);
    // Not found, and could not be read, are different facts and get different sentences. The
    // Phase 2 live test found a failed read printed as "No customer on this order." under a
    // header naming the customer — infrastructure turned into business truth.
    if (!hist || typeof hist !== 'object') return [door, h('p', { class: 'card-note', text: 'No customer is attached to this order.' })];
    // And the door stands even here — this is the case where it is worth most: the history
    // could not be read and the customer can still be opened.
    if (hist.available === false) return [door, h('p', { class: 'card-note unread-line', text: 'I couldn’t load the customer this time. Say “what else has this customer ordered?” to try again.' })];
    const orders = num(hist.orders);
    const stats = h('div', { class: 'stats three' }, [
      h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: orders === null ? '—' : String(orders) }), h('div', { class: 'stat-k', text: orders === 1 ? 'Order' : 'Orders' })]),
      h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: text(hist.spent, '—') }), h('div', { class: 'stat-k', text: 'Lifetime' })]),
      h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: formatDate(hist.since, { month: 'short', year: 'numeric' }) || '—' }), h('div', { class: 'stat-k', text: 'Since' })]),
    ]);
    const lines = [];
    if (hist.first_order_at) lines.push(h('li', { class: 'hist-line', text: `First order ${formatDate(hist.first_order_at, DATE_DAY_YEAR)}` }));
    const waiting = list(Array.isArray(hist.other_unfulfilled) ? hist.other_unfulfilled.map((n) => ({ n })) : [], 5).map((x) => text(x.n)).filter(Boolean);
    if (waiting.length) lines.push(h('li', { class: 'hist-line warn', text: `Also waiting to ship: ${waiting.join(', ')}` }));
    const recent = list(hist.recent, 5);
    if (hist.recent_truncated && recent.length && orders !== null) lines.push(h('li', { class: 'hist-line', text: `Last ${recent.length} of ${orders} orders shown` }));
    // A customer's earlier orders are the second-commonest hop in the whole graph — you are
    // looking at #1938 and you want the one before it — and they were plain text. The row that
    // names #1912 opens #1912, unless it names the order you are already on.
    const rows = recent.length ? h('ul', { class: 'rows compact hist-rows' }, recent.map((r) => {
      const ref = r.current ? '' : text(r.order_id);
      return h('li', {
        class: `row${r.current ? ' is-current' : ''}${ref ? ' tappable' : ''}`,
        role: ref ? 'button' : null, tabindex: ref ? '0' : null,
        data: ref ? { ref, kind: 'order' } : {},
      }, [
        h('span', { class: 'row-main' }, [h('strong', { text: text(r.order_number, '—') }), ' ', h('span', { class: 'card-meta', text: formatDate(r.placed_at, DAY_FMT) }), r.current ? badge('this order', 'quiet') : null]),
        h('span', { class: 'row-sub', text: text(r.items_brief) }),
        h('span', { class: 'row-side' }, [h('span', { class: 'amount', text: text(r.total) }), badge(r.cancelled ? 'cancelled' : r.fulfillment)]),
        ref ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }) : null,
      ]);
    })) : null;
    return [door, stats, lines.length ? h('ul', { class: 'hist-lines' }, lines) : null, rows];
  }

  // ---- email that is about this order, with how sure that is on every line.
  function relatedEmailBlock(email) {
    if (!email || typeof email !== 'object') return [h('p', { class: 'card-note', text: 'Email not checked.' })];
    if (email.available === false) {
      // Not configured is a setting; unavailable is a read that failed. Only one of them is
      // worth trying again, and only one of them must not be read as "no email".
      const reason = text(email.reason);
      if (/unavailable|read_failed|timeout/i.test(reason)) return [h('p', { class: 'card-note unread-line', text: 'I couldn’t check the inbox this time. Say “check the inbox for this order” to try again.' })];
      return [h('p', { class: 'card-note', text: `Email not checked${reason ? ' · ' + reason : ''}` })];
    }
    const threads = list(email.threads, 3);
    if (!threads.length) return [h('p', { class: 'card-note', text: 'No recent email from them about this.' })];
    return [h('ul', { class: 'rows mail' }, threads.map((t) => {
      // Three words for three certainties: the mail server vouched for the sender; the
      // From line matches the order and nothing else does; or the order is merely mentioned.
      const verified = t.verified_sender === true;
      const matches = verified || t.sender_match === true;
      // A DOOR, not a caption. The thread card has said which order it is about since Phase 2
      // (`linkedOrderStrip`) and the order card has listed its email for just as long — but
      // these rows carried `data-thread`, which nothing on the page opens on, and a click
      // handler that only expanded them. So the graph was navigable thread→order and not
      // order→thread: the owner could read that a customer had written and had no way to
      // reach what they wrote. `data-ref` + `data-kind` is what the deck's one click handler
      // posts to `open.entity` — the same door a list row goes through.
      const ref = text(t.thread_id);
      const row = h('li', {
        class: `row${ref ? ' tappable' : ''}`, role: ref ? 'button' : null, tabindex: ref ? '0' : null,
        data: ref ? { ref, kind: 'email_thread' } : {},
      }, [
        h('span', { class: 'row-main' }, [
          badge(verified ? 'From the customer · verified' : matches ? 'Sender matches' : 'Mentions the order', verified ? 'quiet ok' : matches ? 'quiet warn' : 'quiet'),
          ' ', h('strong', { text: text(t.subject, '(no subject)') }),
        ]),
        h('span', { class: 'row-sub', text: [text(t.from), text(t.snippet)].filter(Boolean).join(' — ') }),
        h('span', { class: 'row-side' }, [h('span', { class: 'card-meta', text: formatDate(t.date) })]),
        ref ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '›' }) : null,
      ]);
      if (!ref) row.addEventListener('click', () => row.classList.toggle('is-open'));
      return row;
    }))];
  }

  // ---- the rail: the changes the Mac says make sense for this order. A chip is not a
  // button that does something; it primes the hold with the words that ask for the change,
  // so the ask, the proposal and the gesture stay exactly what they are by voice. A chip the
  // Mac disabled shows its one reason and does nothing.
  //
  // THREE kinds of chip share the rail, and the Mac says which each one is.
  //
  //   "ask"    primes the hold with the words, and — when it carries a family — tells the Mac
  //            what the next sentence is about. The words it primed are then shown ON THE
  //            CHIP, because the dock label they used to be written to is 788px below the
  //            finger and is overwritten by the act of speaking.
  //   "stage"  a row action (app/actions/rows.py) on the record itself: the tap asks the Mac
  //            to PREPARE the change, and the card that comes back still waits for a gesture.
  //            `ref` is the record those chips act on; it is posted with the action id and
  //            nothing else.
  //   "open"   the tap posts the semantic command the Mac put on the chip (`data-command`,
  //            `data-args`) through the page's one delegated handler (web/app.js), and a
  //            screen comes back — the reply composer, an email to a customer. Reply is the
  //            first of these: it was rendered twenty-four times in the live session and
  //            tapped nought, because tapping it produced a label rather than a reply.
  //
  // And a rail is not a capability list. The Mac marks ONE chip `primary` (§25 — primary
  // action, secondary group, more); the rest — the fallbacks and every disabled one — go
  // behind one disclosure that says how many.
  //
  // THREE WAYS A CHIP IS NOT DRAWN AT ALL (§25/§19, Phase 5). Each was a control that looked
  // like a control and was not one:
  //
  //   no label      it was drawn as an em dash. A chip saying "—" does not explain itself,
  //                 and there is no reading of it that helps a thumb decide.
  //   nothing behind it   the Mac said `enabled`, and the page has no ref to stage against,
  //                 no command to post, or no words to prime. That is D-6 exactly — "the
  //                 control was drawn before its destination was known to exist" — and it
  //                 used to render as a dead chip with no reason on it, because `reason` is
  //                 empty precisely when the Mac thinks it is enabled.
  //   disabled and mute   §19: a control that is disabled must say WHY, in the owner's words.
  //                 One that cannot is removed instead, because a dead control that explains
  //                 nothing is worse than no control.
  function railChip(a, opts, ref) {
    const staged = text(a.mode) === 'stage';
    const opened = text(a.mode) === 'open';
    const enabled = a.enabled === true
      && (staged ? Boolean(text(ref)) : opened ? Boolean(text(a.command)) : Boolean(text(a.instruction)));
    if (!text(a.label)) return null;
    if (a.enabled === true && !enabled) return null;
    if (!enabled && !text(a.reason)) return null;
    const chip = h('button', {
      class: `rail-chip risk-${text(a.risk) === 'red' ? 'red' : 'amber'}${enabled ? '' : ' is-off'}`, type: 'button',
      'aria-disabled': enabled ? 'false' : 'true', title: staged ? text(a.detail) : null,
      // `family` is the spoken control this chip arms, when it arms one — the Mac's own
      // mapping (commands.SPOKEN_CONTROLS), carried here so the page never invents one and
      // so the armed chip can be found again when the Mac says it is listening. `command`
      // and `args` are what an "open" chip posts, built on the Mac; the page forwards them.
      data: {
        action: text(a.id), mode: text(a.mode, 'ask'), family: text(a.family),
        ref: staged ? text(ref) : null,
        command: enabled && opened ? text(a.command) : null,
        args: enabled && opened ? text(a.args) : null,
      },
    }, [
      h('span', { class: 'rail-label', text: text(a.label) }),
      !enabled && a.reason ? h('span', { class: 'rail-why', text: text(a.reason) }) : null,
    ]);
    if (enabled && staged) {
      chip.addEventListener('click', (event) => {
        if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
        if (!opts || typeof opts.onRowAction !== 'function' || chip.disabled) return;
        chip.disabled = true;
        opts.onRowAction(text(a.id), text(ref), chip);
      });
    } else if (enabled && opened) {
      // Nothing to wire: the deck's delegated [data-command] handler posts it and draws what
      // comes back. One handler for every command on every card is the whole reason a card
      // redrawn mid-gesture still has working buttons.
      chip.classList.add('is-open');
    } else if (enabled) {
      chip.addEventListener('click', () => {
        primedChip(chip, text(a.instruction));
        if (opts && typeof opts.onAction === 'function') opts.onAction(a, chip);
      });
    }
    return chip;
  }

  // The visible answer to a tap on an "ask" chip: the words it primed, on the chip that
  // primed them.
  //
  // This is the other half of D-11. An ask chip stages nothing by design — it puts a sentence
  // in the owner's mouth — and the only sign that it had done so was a line written to the
  // dock label 788 pixels below the finger, which "Release to send" overwrites the instant the
  // thumb goes down to speak. Eight chips, forty-odd renders, nought taps. The words now sit
  // on the chip, and stay there. `data-said` rather than `data-primed`, because `data-primed`
  // belongs to the Mac's armed state (web/app.js:drawArmed) and the two must not overwrite
  // each other: a chip with a family gets both, a chip without gets this.
  function primedChip(chip, words) {
    const rail_ = chip.parentNode && chip.parentNode.parentNode ? chip.parentNode.parentNode : chip.parentNode;
    const root = rail_ && typeof rail_.querySelectorAll === 'function' ? rail_ : null;
    const strip = (el) => {
      for (const said of el.querySelectorAll('.rail-said')) { if (said.parentNode) said.parentNode.removeChild(said); }
    };
    if (root) {
      for (const other of root.querySelectorAll('.rail-chip')) {
        if (other === chip) continue;
        other.classList.remove('is-primed');
        other.dataset.said = '';
        strip(other);
      }
    }
    strip(chip);
    chip.classList.add('is-primed');
    chip.dataset.said = 'true';
    if (words) chip.appendChild(h('span', { class: 'rail-said', text: `Hold the dock and say: “${words}”` }));
  }

  function rail(actions, opts, ref) {
    const list_ = list(actions, 6);
    if (!list_.length) return null;
    const primary = list_.filter((a) => text(a.priority) === 'primary');
    const rest = list_.filter((a) => text(a.priority) === 'secondary');
    // A rail the Mac did not weigh at all — an older payload, with no `priority` on anything
    // — is drawn as it always was. One it DID weigh is drawn as it was weighed, and that
    // includes the case where nothing was weighed primary: a rail of disabled chips used to
    // be promoted to full weight wholesale by `primary.length ? primary : list_`, so the one
    // rule the Mac is asked to guarantee — "a dead chip must not sit beside a live one" —
    // was undone by the renderer whenever there was no live one.
    const weighed = list_.some((a) => text(a.priority));
    const lead = weighed ? primary : list_;
    const behind = weighed ? rest : [];
    const chips = (group) => group.map((a) => railChip(a, opts, ref)).filter(Boolean);
    const front = chips(lead);
    const back = chips(behind);
    if (!front.length && !back.length) return null;   // nothing left that is a control
    const wrap = h('div', { class: 'rail', role: 'group', 'aria-label': 'Changes' });
    if (front.length) wrap.appendChild(h('div', { class: 'rail-primary' }, front));
    if (!back.length) return wrap;
    const behindCount = back.length;
    const body = h('div', { class: 'rail-rest', hidden: true }, back);
    // WHAT THE DISCLOSURE SAYS IT HOLDS. "2 more" reads correctly after a chip — more than
    // the one you can see — and reads as a question when there is nothing above it, which is
    // the case this pass created: an order that can no longer be cancelled, refunded or
    // shipped has only dead chips, and they no longer get promoted to full weight. So when
    // the rail leads with nothing, the control names what is behind it instead of counting
    // past something that is not there (§26 — a control explains itself).
    const allOff = back.every((c) => c.getAttribute('aria-disabled') === 'true');
    const label = !front.length && allOff
      ? `${behindCount} unavailable`
      : `${behindCount} more`;
    const more = h('button', {
      class: 'rail-more', type: 'button', 'aria-expanded': 'false',
    }, [h('span', { class: 'rail-more-label', text: label }),
        h('span', { class: 'rail-more-mark', 'aria-hidden': 'true', text: '+' })]);
    more.addEventListener('click', (event) => {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
      const open = more.getAttribute('aria-expanded') === 'true';
      more.setAttribute('aria-expanded', open ? 'false' : 'true');
      body.hidden = open;
      more.querySelector('.rail-more-mark').textContent = open ? '+' : '−';
    });
    append(wrap, [more, body]);
    return wrap;
  }

  // A note of a few lines reads in place. A longer one goes behind one control, which is the
  // same discipline as the thread's history and the list's tail (`disclosure`).
  //
  // The threshold is four lines, in the characters that make four lines: at 15px/1.5 in the
  // card's ~520px column a line holds about sixty. Measured at 601 x 889, a 308-character note
  // was 169 px of a 372 px Overview panel, and once the deck stopped scrolling under the dock
  // (the collision fix, same pass) the whole order card stood at 757 px against a 699 px
  // ceiling. Behind a control it is 44 px, and the card is 632 px.
  //
  // A `clamp` with a More button was tried first and saved nothing — the 44 px the control
  // needs for a thumb is exactly what the clamp gave back. Nothing is removed either way: the
  // note is complete in the DOM and, folded, one tap from the reader.
  const NOTE_LINES_BEFORE_FOLD = 4;
  const NOTE_CHARS_PER_LINE = 60;

  function noteSection(note) {
    const quote = h('blockquote', { class: 'note-quote', text: text(note) });
    if (text(note).length <= NOTE_LINES_BEFORE_FOLD * NOTE_CHARS_PER_LINE) return section('note', 'Note', [quote]);
    return disclosure(quote, 'Note');
  }

  function pendingLine(what) {
    return h('p', { class: 'card-note pending-line', text: what });
  }

  function renderOrder(d, opts) {
    const items = list(d.items, 12);
    const tags = Array.isArray(d.tags) ? d.tags.slice(0, 3).map((t) => text(t)).filter(Boolean) : [];
    // Number, who, how much, what state — the four things worth knowing in the first second,
    // on two lines. The "ORDER" kicker went because the card already says #1938 in 30px mono;
    // the customer's tags moved up beside their name because a VIP badge on a line of its own
    // cost 30px to say one word; and the money came UP here, which is the point of the change.
    // It was only in the Overview tab, so the total was never on screen with the status — and
    // it was then repeated in the Money breakdown below, so £84.00 appeared four times on one
    // card and not once in its header.
    const head = h('div', { class: 'card-head' }, [
      h('div', { class: 'head-main' }, [
        h('h2', { class: 'card-title mono', text: text(d.order_number, '—') }),
        h('p', { class: 'card-sub' }, [
          h('span', { text: text(d.customer_name) }),
          ...tags.map((t) => badge(t, 'quiet')),
        ]),
        d.customer_email ? h('p', { class: 'card-meta', text: text(d.customer_email) }) : null,
      ]),
      h('div', { class: 'head-side' }, [
        d.total ? h('p', { class: 'head-total mono', text: text(d.total) }) : null,
        h('div', { class: 'badges' }, [badge(d.fulfillment), badge(d.payment)]),
      ]),
    ]);
    // Placed and Total are in the header and the timeline now; repeating them here was most of
    // what made the Overview tab a second copy of the card it sits inside.
    const overview = kv([
      ['Ships to', d.ships_to],
      ['Cancelled', d.cancelled_at ? [formatDate(d.cancelled_at), text(d.cancel_reason)].filter(Boolean).join(' · ') : ''],
    ], true);
    if (!d.detail) {
      const brief = card('order', [head, orderTimeline(d), overview, h('p', { class: 'card-note', text: 'Ask for the order to see its items and shipping.' })], opts);
      brief.dataset.ref = text(d.order_id);
      holdable(brief);
      return brief;
    }
    const pending = Array.isArray(d.pending) ? d.pending.map((x) => text(x)) : [];
    const who = { customer_id: d.customer_id, customer_name: d.customer_name };
    const historyBody = pending.indexOf('history') !== -1
      // Even while the history is still being read, the door is there: who the order belongs
      // to is on the order, and waiting for a read to finish before offering the hop is how
      // step 4 of the click path came to be dead.
      ? [customerDoor(who), pendingLine('Reading their history…')]
      : historyBlock(d.history, who);
    const emailBody = pending.indexOf('email') !== -1 ? [pendingLine('Checking the inbox…')] : relatedEmailBlock(d.email);
    const standing = d.history && typeof d.history === 'object' ? text(d.history.standing) : '';
    // Five tabs, one open. The September session drew order cards 7,524 pixels tall against
    // 655 pixels of screen and recorded 131 scrolls; the same facts, one at a time, fit.
    const panels = [
      { name: 'overview', label: 'Overview', node: [
        overview,
        section('money', 'Money', [moneyBlock(d)]),
        d.note ? noteSection(d.note) : null,
      ] },
      { name: 'items', label: `Items${items.length ? ' · ' + items.length : ''}`, node: [
        section('items', `Items${items.length ? ' · ' + items.length : ''}`, [items.length ? itemsList(items, opts, Boolean(d.items_truncated)) : h('p', { class: 'card-note', text: 'No items on the order.' })]),
      ] },
      { name: 'shipping', label: 'Shipping', node: [section('shipping', 'Shipping', shippingBlock(d))] },
      { name: 'customer', label: 'Customer', node: [section('history', 'Customer', historyBody, standing ? badge(standing, 'quiet') : null)] },
      { name: 'email', label: 'Email', node: [section('email', 'Email', emailBody)] },
    ];
    // What this order NEEDS, on the order (§8: the first viewport answers what matters). The
    // attention card that carries the detail sits after this one — 709 px down a 671 px
    // screen, which is to say out of sight — so the headline comes up here beside the status.
    const attention = list(d.attention_top, 2);
    const full = card('order', [
      head,
      orderTimeline(d),
      attention.length ? h('ul', { class: 'attn-strip' }, attention.map((a) => h('li', {
        class: `attn-line ${a.level === 'red' ? 'bad' : a.level === 'green' ? 'ok' : 'warn'}`,
      }, [h('span', { class: 'attn-dot', 'aria-hidden': 'true' }), h('span', { text: text(a.title) })]))) : null,
      d.cancelled_at ? h('p', { class: 'card-note bad', text: `Cancelled ${formatDate(d.cancelled_at)}${d.cancel_reason ? ' · ' + text(d.cancel_reason) : ''}` }) : null,
      // The order is the record a staged chip on its rail acts on (round 11, W1-01): without
      // its ref, railChip drops an enabled "stage" chip as having nothing behind it.
      rail(d.actions, opts, d.order_id),
      tabs(panels, { initial: tabFor('order', d, opts), onChange: tabReporter('order', d, opts) }),
    ], opts);
    full.dataset.ref = text(d.order_id);
    holdable(full);
    full.dataset.pending = pending.join(' ');
    // Kept on the node because /context/order redraws this region later and its payload is
    // about the ORDER's regions, not about who it belongs to (app/presentation.py
    // `present_extension`) — so the door would have been dropped by the very read it was
    // waiting for.
    full.dataset.customer = text(d.customer_id);
    full.dataset.customerName = text(d.customer_name);
    return full;
  }

  // The rest of an order card, collected by the app from /context/order once the card is
  // up: the history and the inbox that missed the turn's budget. Returns what is still to
  // come, so the app knows whether to ask again.
  function hydrateOrder(node, ext) {
    if (!node || !ext || typeof ext !== 'object') return [];
    const pending = Array.isArray(ext.pending) ? ext.pending.map((x) => text(x)) : [];
    const fill = (kind, body) => {
      const sec = node.querySelector(`.sec-${kind}`);
      if (!sec) return;
      const keep = sec.querySelector('.sec-kicker');
      while (sec.firstChild) sec.removeChild(sec.firstChild);
      if (keep) sec.appendChild(keep);
      append(sec, body);
    };
    if (pending.indexOf('history') === -1 && Object.prototype.hasOwnProperty.call(ext, 'history')) {
      fill('history', historyBlock(ext.history, {
        customer_id: node.dataset.customer, customer_name: node.dataset.customerName,
      }));
      const k = node.querySelector('.sec-history') && node.querySelector('.sec-history').querySelector('.sec-kicker');
      const standing = ext.history && typeof ext.history === 'object' ? text(ext.history.standing) : '';
      if (k && standing && !k.querySelector('.badge')) k.appendChild(badge(standing, 'quiet'));
    }
    if (pending.indexOf('email') === -1 && Object.prototype.hasOwnProperty.call(ext, 'email')) fill('email', relatedEmailBlock(ext.email));
    if (Array.isArray(ext.attention)) placeAttention(node, ext.order_id, ext.attention);
    // A region the Mac tried and could not read: its tab says so, the way it does when the
    // tablet stops asking (settleOrder), so a closed tab is never an all-clear.
    for (const kind of (Array.isArray(ext.failed) ? ext.failed : [])) markTabUnread(node, kind);
    node.dataset.pending = pending.join(' ');
    return pending;
  }

  const TAB_OF_REGION = { email: 'email', history: 'customer' };
  function markTabUnread(node, kind) {
    const want = TAB_OF_REGION[kind] || kind;
    const tabs = node.querySelectorAll('[role="tab"]');
    const tab = tabs.find ? tabs.find((t) => (t.textContent || '').toLowerCase().indexOf(want) !== -1)
      : Array.prototype.find.call(tabs, (t) => (t.textContent || '').toLowerCase().indexOf(want) !== -1);
    if (tab && !tab.querySelector('.tab-mark')) {
      tab.setAttribute('data-unread', '1');
      tab.appendChild(h('span', { class: 'tab-mark', text: '?', title: 'not read' }));
    }
  }

  // What never arrived, said so. The tablet asks for the rest of an order three times and
  // then stops asking — and the panel it stopped asking for kept reading "Checking the
  // inbox…", byte for byte, 34.8 seconds later. Held in one hand, the card read as complete
  // and calm while the one thing that made the order urgent — a customer waiting on a reply —
  // had silently gone from the screen. A read that failed is drawn as a read that failed:
  // the region says so in words, with what to say to try again, and the tab it lives behind
  // carries a mark, so a closed tab is not an all-clear.
  function settleOrder(node, opts) {
    if (!node || !node.dataset) return [];
    const pending = text(node.dataset.pending).split(' ').filter(Boolean);
    if (!pending.length) return [];
    const number = text(opts && opts.number) || text((node.querySelector('.card-title') || {}).textContent).replace(/^#/, '');
    const words = {
      email: `The inbox could not be read this time. Say “check the inbox for ${number ? '#' + number : 'this order'}” to try again.`,
      history: 'Their history could not be read this time. Say “what else has this customer ordered?” to try again.',
    };
    for (const kind of pending) {
      const sec = node.querySelector(`.sec-${kind}`);
      if (sec) {
        const keep = sec.querySelector('.sec-kicker');
        while (sec.firstChild) sec.removeChild(sec.firstChild);
        if (keep) sec.appendChild(keep);
        sec.appendChild(h('p', { class: 'card-note unread-line', text: words[kind] || 'This could not be read this time.' }));
      }
      markTabUnread(node, kind);
    }
    node.dataset.pending = '';
    return pending;
  }

  // The attention card sits right after the order it reads; a later reading replaces it.
  function placeAttention(orderNode, orderId, items) {
    const parent = orderNode.parentNode;
    if (!parent) return null;
    const ref = text(orderId);
    const old = parent.querySelectorAll('.card-attention').filter ? parent.querySelectorAll('.card-attention').filter((n) => n.dataset.for === ref) : Array.prototype.filter.call(parent.querySelectorAll('.card-attention'), (n) => n.dataset.for === ref);
    old.forEach((n) => parent.removeChild(n));
    if (!items.length) return null;
    const fresh = renderAttention({ items, for: ref }, {});
    const siblings = Array.prototype.slice.call(parent.childNodes);
    const after = siblings[siblings.indexOf(orderNode) + 1] || null;
    if (after && typeof parent.insertBefore === 'function') parent.insertBefore(fresh, after); else parent.appendChild(fresh);
    return fresh;
  }

  // How many rows a list shows before the rest go behind one control. Measured at 601 × 889:
  // ten full rows of an order list is 1,100 px of an 889 px screen, so the first screen
  // answers what am I looking at / what matters / what can I do and the tail is one tap away
  // (§8, D-12). Nothing is removed — every row is in the DOM and reachable.
  const ROWS_BEFORE_FOLD = 5;

  function renderOrderList(d, opts) {
    const orders = list(d.orders, 10);
    const count = num(d.count);
    const whole = !d.truncated && count !== null ? count === orders.length : false;
    // The summary: what this list IS, before any row of it. A count, the money when the Mac
    // sent one, and how many are still to go out — which is the question an order list gets
    // asked, and is counted only when the list is the whole of what there is.
    const toShip = whole ? orders.filter((o) => orderState(o) === 'to-ship').length : null;
    const stats = [
      [count === null ? String(orders.length) : String(count), count === 1 ? 'Order' : 'Orders'],
      text(d.value) ? [text(d.value), 'Value'] : null,
      toShip === null ? null : [String(toShip), 'To ship'],
    ].filter(Boolean);

    const rows = orders.map(orderRow);
    const listEl = h('ul', { class: 'rows tight' }, rows);
    const position = h('p', { class: 'list-pos' });
    let filter = 'all';
    let expanded = false;

    const draw = () => {
      let shown = 0;
      for (const row of rows) {
        const state = row.dataset.state || '';
        const passes = filter === 'all' || state === filter;
        const room = expanded || shown < ROWS_BEFORE_FOLD;
        row.hidden = !(passes && room);
        if (passes) shown += 1;
      }
      const visible = expanded ? shown : Math.min(shown, ROWS_BEFORE_FOLD);
      const total = count === null ? orders.length : count;
      /* §26 · one statement per fact. When everything is on screen and nothing is filtered
         this line said "3 orders" — which is what the stat tile forty pixels below it says,
         in larger type, as `3 / ORDERS`. The visual pass photographed both, plus the same
         number again on the set chip. So the line speaks only when it has something the tile
         cannot give: which SUBSET is on screen. That is the case it was written for, and the
         one where the tile's total is not the answer.

         Emptied rather than removed: `position` is in the card head and `draw()` runs again
         on every filter tap, so the node has to stay for the next state to fill. */
      const all = visible >= total && filter === 'all';
      position.textContent = all
        ? ''
        : `Showing ${visible} of ${filter === 'all' ? total : shown}${d.truncated ? ` · ${total} in the window` : ''}`;
      position.hidden = all;
      if (more) {
        more.hidden = shown <= ROWS_BEFORE_FOLD;
        more.textContent = expanded ? 'Fewer' : `All ${shown}`;
      }
    };
    const more = h('button', { class: 'link-btn', type: 'button', text: 'All' });
    more.addEventListener('click', () => { expanded = !expanded; draw(); });

    // The filters. Only where there is a mix to filter: three chips over three rows that are
    // all in the same state is furniture, which is what §8 says not to spend the screen on.
    const states = [];
    for (const row of rows) if (states.indexOf(row.dataset.state) === -1) states.push(row.dataset.state);
    const chips = states.length > 1 ? h('div', { class: 'chips list-filter', role: 'group', 'aria-label': 'Show' },
      [['all', 'All']].concat(states.indexOf('to-ship') !== -1 ? [['to-ship', 'To ship']] : [], states.indexOf('shipped') !== -1 ? [['shipped', 'Shipped']] : [], states.indexOf('cancelled') !== -1 ? [['cancelled', 'Cancelled']] : [])
        .map(([name, label]) => {
          const chip = h('button', { class: 'chip', type: 'button', 'aria-pressed': name === 'all' ? 'true' : 'false', text: label, data: { filter: name } });
          chip.addEventListener('click', () => {
            filter = name;
            expanded = false;
            for (const other of chips.children) other.setAttribute('aria-pressed', other === chip ? 'true' : 'false');
            draw();
          });
          return chip;
        })) : null;

    const node = card('order_list', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker('Orders'),
        h('h2', { class: 'card-title', text: text(d.title, 'Orders') }),
        position,
      ])]),
      stats.length ? h('div', { class: `stats${stats.length === 3 ? ' three' : ''}` }, stats.map(([v, k]) => h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: v }), h('div', { class: 'stat-k', text: k })]))) : null,
      emptyNote(d),
      chips,
      orders.length ? listEl : null,
      orders.length ? more : null,
    ], opts);
    draw();
    return node;
  }

  function renderCustomer(d, opts) {
    const orders = num(d.orders);
    const standing = orders === null ? '' : orders === 0 ? 'No orders yet' : orders === 1 ? 'First order' : orders >= 4 ? 'Regular' : 'Returning';
    const node = card('customer', [
      h('div', { class: 'card-head profile' }, [
        avatar(d.name, 'lg'),
        h('div', {}, [kicker('Customer'), h('h2', { class: 'card-title', text: text(d.name, 'Customer') }), h('p', { class: 'card-sub', text: text(d.email) })]),
        standing ? h('div', { class: 'badges' }, [badge(standing, 'quiet')]) : null,
      ]),
      customerPanels(d, orders, opts),
    ], opts);
    node.dataset.ref = text(d.customer_id);
    return node;
  }

  // Overview, Orders, Email — and only the tabs there is something to put behind. A customer
  // card with nothing but a name is a card, not a tab bar with two empty panels.
  function customerPanels(d, orders, opts) {
    const overview = h('div', { class: 'stats' }, [
      h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: orders === null ? '—' : String(orders) }), h('div', { class: 'stat-k', text: 'Orders' })]),
      h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: text(d.spent, '—') }), h('div', { class: 'stat-k', text: 'Lifetime' })]),
    ]);
    const history = d.history && typeof d.history === 'object' ? section('history', 'Orders', historyBlock(d.history)) : null;
    const mail = d.related_email && typeof d.related_email === 'object' ? section('email', 'Email', relatedEmailBlock(d.related_email)) : null;
    if (!history && !mail) {
      return [overview, h('p', { class: 'card-note', text: 'Ask for their orders or their emails to see more.' })];
    }
    return tabs([
      { name: 'overview', label: 'Overview', node: [overview] },
      history ? { name: 'orders', label: 'Orders', node: [history] } : null,
      mail ? { name: 'email', label: 'Email', node: [mail] } : null,
    ].filter(Boolean), { initial: tabFor('customer', d, opts), onChange: tabReporter('customer', d, opts) });
  }

  function renderCustomerList(d, opts) {
    const customers = list(d.customers, 6);
    return card('customer_list', [
      h('div', { class: 'card-head' }, [h('div', {}, [kicker(d.ambiguous ? 'Which one?' : 'Customers'), h('h2', { class: 'card-title', text: text(d.title, 'Customers') })])]),
      emptyNote(d),
      h('ul', { class: 'rows tight' }, customers.map((c) => h('li', { class: 'row' }, [
        h('span', { class: 'row-main', text: text(c.name, '—') }),
        h('span', { class: 'row-sub', text: text(c.email) }),
        h('span', { class: 'row-side' }, [
          num(c.orders) !== null ? h('span', { class: 'card-meta', text: `${c.orders} order${c.orders === 1 ? '' : 's'}` }) : null,
          c.spent ? h('span', { class: 'amount', text: text(c.spent) }) : null,
        ]),
      ]))),
      d.ambiguous ? h('p', { class: 'card-note', text: 'Say which one you mean.' }) : null,
    ], opts);
  }

  function renderProduct(d, opts) {
    const products = list(d.products, 4);
    if (!products.length) {
      // A catalogue read that matched nothing. It used to draw NO CARD, which is the shape
      // of D-15: the payload named a type and the screen stayed empty.
      return card('product', [
        h('div', { class: 'card-head' }, [h('div', {}, [kicker('Product'), h('h2', { class: 'card-title', text: text(d.title, text(d.query, 'Product')) })])]),
        emptyNote(d) || h('p', { class: 'card-note', text: 'Nothing in the catalogue matched.' }),
      ], opts);
    }
    const p = products[0];
    const facts = kv([['Fabric', p.fabric], ['Cut', p.cut], ['Origin', p.origin], ['Care', p.care]], true);
    const desc = p.description ? expandable(h('p', { class: 'card-body', text: text(p.description) }), 'Read more') : null;
    let table = null;
    const measurements = list(p.measurements, 8);
    if (measurements.length) {
      const cols = Object.keys(measurements[0]);
      table = h('div', { class: 'table-wrap' }, h('table', { class: 'mtable' }, [
        h('thead', {}, h('tr', {}, cols.map((c) => h('th', { text: c })))),
        h('tbody', {}, measurements.map((m) => h('tr', {}, cols.map((c) => h('td', { text: text(m[c]) }))))),
      ]));
    }
    return card('product', [
      h('div', { class: 'card-head' }, [
        h('div', {}, [kicker('Product'), h('h2', { class: 'card-title', text: text(p.title, 'Product') }), h('p', { class: 'card-sub', text: text(p.subtitle) })]),
        h('div', { class: 'badges' }, [badge(p.status)]),
      ]),
      facts, desc, table,
      p.measurements_note && !measurements.length ? h('p', { class: 'card-note', text: text(p.measurements_note) }) : null,
      products.length > 1 ? h('p', { class: 'card-note', text: `Also matched: ${products.slice(1).map((x) => text(x.title)).filter(Boolean).join(', ')}` }) : null,
    ], opts);
  }

  const LEVEL_LABEL = { out: 'Out of stock', low: 'Low stock', oversold: 'Oversold', untracked: 'Not tracked', unknown: 'Unknown', ok: 'In stock' };
  const LEVEL_TONE = { out: 'bad', low: 'warn', oversold: 'bad', ok: 'ok', untracked: '', unknown: '' };

  function stockRow(v, withProduct) {
    const avail = num(v.available);
    const level = text(v.level, 'unknown');
    let amount = avail === null ? '—' : `${avail} left`;
    if (level === 'oversold') amount = `−${v.oversold_by}`;
    if (level === 'untracked') amount = 'untracked';
    return h('li', { class: 'row' }, [
      h('span', { class: 'row-main', text: withProduct ? text(v.product, 'Product') : text(v.variant, 'Variant') }),
      h('span', { class: 'row-sub', text: withProduct ? text(v.variant) : text(v.sku) }),
      h('span', { class: 'row-side' }, [h('span', { class: 'amount', text: amount }), badge(LEVEL_LABEL[level] || level, LEVEL_TONE[level] || '')]),
    ]);
  }

  function renderInventory(d, opts) {
    const products = list(d.products, 4);
    const exceptions = list(d.exceptions, 16);
    const children = [h('div', { class: 'card-head' }, [h('div', {}, [kicker('Inventory'), h('h2', { class: 'card-title', text: text(d.query, 'Stock') }), d.size ? h('p', { class: 'card-meta', text: `Size ${text(d.size)}` }) : null])])];
    if (d.empty === true) {
      children.push(emptyNote(d));
      return card('inventory', children, opts);
    }
    if (exceptions.length) {
      children.push(h('p', { class: 'card-kicker', text: 'Needs attention' }));
      children.push(h('ul', { class: 'rows' }, exceptions.map((e) => stockRow(e, true))));
    } else {
      children.push(h('p', { class: 'card-note', text: `Nothing at or below ${num(d.low_stock_at) === null ? 'the low-stock line' : d.low_stock_at + ' left'}.` }));
    }
    const all = products.map((p) => h('div', {}, [
      h('p', { class: 'card-kicker', text: [text(p.title), num(p.total_inventory) !== null ? `${p.total_inventory} total` : ''].filter(Boolean).join(' · ') }),
      h('ul', { class: 'rows' }, list(p.variants, 16).map((v) => stockRow(v, false))),
    ]));
    if (all.length) {
      const full = h('div', { class: 'panel' }, all);
      full.hidden = true;
      const toggle = h('button', { class: 'link-btn', type: 'button', text: 'All variants', on: { click: () => {
        full.hidden = !full.hidden;
        toggle.textContent = full.hidden ? 'All variants' : 'Hide all variants';
      } } });
      children.push(toggle, full);
    }
    return card('inventory', children, opts);
  }

  function renderSales(d, opts) {
    const days = list(d.by_day, 31).filter((day) => day && typeof day === 'object');
    const stats = [
      [text(d.orders === null || d.orders === undefined ? '—' : d.orders), 'Orders'],
      [text(d.aov, '—'), 'Avg order'],
    ];
    return card('sales_summary', [
      kicker(text(d.title, 'Sales')),
      h('div', { class: 'big', text: text(d.revenue, '—') }),
      h('p', { class: 'card-meta', text: num(d.days) === 1 || !d.until ? formatDate(d.since, DAY_FMT) : [formatDate(d.since, DAY_FMT), formatDate(lastDayOf(d.until), DAY_FMT)].filter(Boolean).join(' → ') }),
      h('div', { class: 'stats' }, stats.map(([v, k]) => h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: v }), h('div', { class: 'stat-k', text: k })]))),
      days.length > 1 ? salesBars(days) : null,
      days.length ? h('ul', { class: 'rows compact' }, days.map((day) => h('li', { class: 'row' }, [
        h('span', { class: 'row-main', text: formatDate(dayNoon(day.date), DAY_ROW_FMT) || text(day.date, '—') }),
        h('span', { class: 'row-side' }, [
          h('strong', { text: text(day.revenue, '—') }),
          h('span', { class: 'card-meta', text: num(day.orders) === null ? '' : ` · ${day.orders} order${num(day.orders) === 1 ? '' : 's'}` }),
        ]),
      ]))) : null,
      d.complete === false ? h('p', { class: 'card-note', text: text(d.caveat, 'Partial figure.') }) : null,
      d.basis ? h('p', { class: 'card-note', text: text(d.basis) }) : null,
    ], opts);
  }
  const DAY_ROW_FMT = { weekday: 'short', day: 'numeric', month: 'short' };

  // Revenue per day as bars, from the money strings the Mac formatted. The height is a
  // clamped number of our own making, never a value from outside written into the page.
  function moneyValue(value) {
    const n = parseFloat(text(value).replace(/[^0-9.\-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  }
  function salesBars(days) {
    const values = days.map((d) => moneyValue(d.revenue));
    const top = Math.max(1, ...values);
    return h('div', { class: 'bars', 'aria-hidden': 'true' }, days.map((d, i) => {
      const pct = Math.max(4, Math.min(100, Math.round((values[i] / top) * 100)));
      const bar = h('span', { class: 'bar', data: { pct: String(pct) } });
      if (bar.style) bar.style.height = `${pct}%`;
      return h('span', { class: 'bar-col', title: formatDate(dayNoon(d.date), DAY_ROW_FMT) }, [bar, h('span', { class: 'bar-day', text: formatDate(dayNoon(d.date), { weekday: 'narrow' }) })]);
    }));
  }
  // A calendar date with no time parses as UTC midnight, which is the previous evening west of
  // Greenwich; noon local is the same calendar day everywhere.
  function dayNoon(value) {
    const raw = text(value);
    return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T12:00:00` : raw;
  }

  function renderEmailList(d, opts) {
    const threads = list(d.threads, 10);
    // A badge that is on every row is not information. In the inbox it separates customers
    // from strangers and earns its place; on the work queue every row is a customer by
    // construction, so three identical green badges were three pieces of furniture.
    const mixed = threads.some((t) => !t.known_customer) && threads.some((t) => t.known_customer);
    return card('email_list', [
      h('div', { class: 'card-head' }, [h('div', {}, [kicker('Email'), h('h2', { class: 'card-title', text: text(d.title, 'Email') }), h('p', { class: 'card-meta', text: num(d.count) === null ? '' : `${d.count} thread${d.count === 1 ? '' : 's'}` })])]),
      emptyNote(d),
      h('ul', { class: 'rows tight' }, threads.map((t) => {
        const row = h('li', { class: 'row tappable', role: 'button', tabindex: '0', data: { ref: text(t.thread_id), kind: 'email_thread' } }, [
          h('span', { class: 'row-main' }, [h('strong', { text: text(t.from, '—') }), ' — ', text(t.subject, '(no subject)')]),
          h('span', { class: 'row-sub', text: text(t.snippet) }),
          h('span', { class: 'row-side' }, [
            h('span', { class: 'card-meta', text: formatDate(t.date) }),
            t.needs_reply === true ? badge('Needs reply', 'warn') : null,
            mixed && t.known_customer ? badge('Customer', 'quiet ok') : null,
            t.likely_bulk ? badge('Bulk', 'quiet') : null,
          ]),
          // Which record the message is about (§12). The Mac only sends a link it has made
          // good — kind, ref and a human label — so these are never the dead control of D-6;
          // where it sent none, there is no chip rather than a chip that goes nowhere.
          mailLinks(t),
          rowActions(t, opts),
          // The affordance instead of the sentence. This card used to end with 'Say "read that
          // one" to open a thread.' — a line of instruction under rows that gave no sign of
          // being tappable at all. A chevron says it on every row, once, and costs no height.
          h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }),
        ]);
        row.addEventListener('click', () => row.classList.toggle('is-open'));
        return row;
      })),
      d.note ? h('p', { class: 'card-note', text: text(d.note) }) : null,
    ], opts);
  }

  // The records an inbox row is about, as chips. The pair the deck posts to `open.entity`
  // rides on each one, and the label beside it is words (§26) — "Order #1962", a person's
  // name — never the ref itself.
  function mailLinks(t) {
    const links = [t.customer_link, t.order_link].filter((l) => l && typeof l === 'object');
    const chips = [];
    for (const l of links) {
      const ref = text(l.ref);
      const kind = text(l.kind);
      const label = text(l.label);
      if (!ref || !kind || !label) continue;
      chips.push(h('button', { class: 'row-btn', type: 'button', data: { ref, kind }, text: label }));
    }
    // `row-actions` and `row-btn`, the classes the row buttons already use: a 44 px target
    // and no new rule in web/style.css, whose layering is another workstream's this pass.
    return chips.length ? h('span', { class: 'row-actions' }, chips) : null;
  }

  // The buttons beside a row, exactly as the Mac listed them (app/actions/rows.py). The
  // tablet renders what it is given and posts back only WHICH action and WHICH row: the
  // arguments are built on the Mac, from a fresh read, and the change that comes back still
  // waits for a gesture. Nothing here decides what a button means.
  function rowActions(row, opts) {
    const actions = Array.isArray(row && row.actions) ? row.actions.slice(0, 3) : [];
    const ref = text(row && row.thread_id);
    if (!actions.length || !ref) return null;
    const onRow = opts && typeof opts.onRowAction === 'function' ? opts.onRowAction : null;
    // §25 · a row button the Mac did not name was drawn saying "Do". A control has to say
    // what it does or it is not a control, and "Do" beside an email is not an answer to
    // "what happens if I press this" — so an unnamed one is not drawn. Same rule as the
    // rail's chips, one function along.
    const named = actions.filter((a) => text(a && a.id) && text(a && a.label));
    if (!named.length) return null;
    return h('span', { class: 'row-actions' }, named.map((a) => {
      const id = text(a && a.id);
      const button = h('button', {
        class: 'row-btn', type: 'button', text: text(a && a.label),
        title: text(a && a.detail), data: { action: id, ref },
        disabled: a && a.enabled === false ? 'disabled' : null,
      });
      button.addEventListener('click', (event) => {
        if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
        if (!onRow || button.disabled) return;
        button.disabled = true;
        button.textContent = 'Preparing…';
        onRow(id, ref, button);
      });
      return button;
    }));
  }

  // An email thread, ordered so that the FIRST VIEWPORT answers the three questions (§8).
  //
  // The live session measured thread surfaces up to 1,999 px against a 680 px viewport, and
  // the reason was structural rather than decorative: every message was drawn open, one after
  // another, so the newest — the only one anybody was going to read — was at the bottom, and
  // the controls were above six screens of quoted text.
  //
  // So: who it is with and which order it is about; whether we owe them a reply; the newest
  // message, clamped, with More; Reply and Archive; and then the history, behind one control.
  // Every message is still in the DOM and one tap away — disclosure, not truncation.
  function threadMessage(m, last) {
    const msg = h('div', { class: `msg${last ? ' is-latest' : ' is-collapsed'}${m.outbound === true ? ' is-ours' : ''}` }, [
      avatar(m.from),
      h('div', { class: 'msg-main' }, [
        h('div', { class: 'msg-head' }, [
          h('div', {}, [
            h('div', { class: 'msg-from', text: text(m.from, '—') }),
            h('div', { class: 'msg-addr', text: text(m.from_email) }),
          ]),
          h('div', { class: 'msg-date', text: formatDate(m.date) }),
        ]),
        // The body, clamped where it is long, with a control that opens it. A 2,000-character
        // message is four lines and a "More" until the owner wants the rest of it.
        text(m.body).length > 320
          ? h('div', {}, expandable(h('p', { class: 'msg-body', text: text(m.body) }), 'More of this message'))
          : h('p', { class: 'msg-body', text: text(m.body) }),
      ]),
    ]);
    if (!last) msg.addEventListener('click', () => msg.classList.toggle('is-collapsed'));
    return msg;
  }

  function renderEmailThread(d, opts) {
    const messages = list(d.messages, 6);
    const nodes = messages.map((m, i) => threadMessage(m, i === messages.length - 1));
    const latest = messages.length ? messages[messages.length - 1] : null;
    const earlier = nodes.slice(0, -1);
    // Who is waiting on whom, from Gmail's own SENT label by way of the Mac — never read out
    // of the words. This is "what matters" for an email, and it was nowhere on the card.
    const waiting = d.awaiting_reply === true;
    const withWhom = latest && latest.outbound !== true ? text(latest.from) : '';
    const meta = [
      num(d.message_count) === null ? '' : `${d.message_count} message${d.message_count === 1 ? '' : 's'}`,
      latest ? formatDate(latest.date) : '',
      d.truncated ? 'older messages not shown' : '',
    ].filter(Boolean).join(' · ');
    const node = card('email_thread', [
      h('div', { class: 'card-head' }, [
        h('div', { class: 'head-main' }, [
          kicker('Email thread'),
          h('h2', { class: 'card-title clamp-2', text: text(d.subject, '(no subject)') }),
          withWhom ? h('p', { class: 'card-sub', text: `with ${withWhom}` }) : null,
          h('p', { class: 'card-meta', text: meta }),
        ]),
        h('div', { class: 'head-side' }, [
          h('div', { class: 'badges' }, [
            waiting ? badge('Needs a reply', 'warn') : (text(d.latest_direction) === 'outbound' ? badge('Replied', 'quiet ok') : null),
          ]),
        ]),
      ]),
      // Which order and which customer this is about: the relation, under the head, where the
      // owner looks for it before he decides what to say.
      linkedOrderStrip(d),
      emptyNote(d),
      // The rail. `rail()` was called from one place — the order card — so an email had no
      // controls on the tablet at all: Reply, Rewrite and Archive were on the Mac and
      // reachable only by a spoken sentence, and the only way out of a thread was to put the
      // tablet down. It sits ABOVE the history now: the primary action must be on the first
      // screen, not below however much quoted text the thread happens to carry.
      rail(d.actions, opts, d.thread_id),
      nodes.length ? h('div', { class: 'msg-latest' }, [nodes[nodes.length - 1]]) : null,
      earlier.length ? disclosure(h('div', { class: 'msg-history' }, earlier), `${earlier.length} earlier message${earlier.length === 1 ? '' : 's'}`) : null,
    ], opts);
    // Which thread this card is, so a proven archive can find it again (`settleThread`) and
    // so Back can tell one thread card from another.
    node.dataset.ref = text(d.thread_id);
    return node;
  }

  // The order this thread is about, under the head, from what the Mac worked out
  // (app/context/graph.py) and never from the words on the card. A confident link is one
  // tappable row; a possible one is up to three chips; nothing is a quiet line. `data-kind`
  // and `data-ref` are what the deck's click handler posts to `open.entity` — the same
  // command a tapped list row reaches — so the strip is a door, not a caption. The reasons
  // ride underneath in small type, because a wrong link on the thread the owner is about to
  // reply to is worse than none, and he can only judge it if he can see why it was drawn.
  function linkedOrderStrip(d) {
    const confidence = text(d.link_confidence, 'none');
    const why = strings(d.link_provenance, 4).join(' · ');
    const note = why ? h('p', { class: 'link-why', text: why }) : null;
    const chip = (o, cls) => {
      const ref = text(o.order_id);
      const words = [text(o.order_number, 'order'), text(o.total), text(o.fulfillment)].filter(Boolean).join(' · ');
      return h(ref ? 'button' : 'span', {
        class: `link-chip${cls ? ' ' + cls : ''}`, type: ref ? 'button' : null,
        data: ref ? { ref, kind: 'order' } : {},
      }, [h('span', { class: 'link-chip-label', text: words }), ref ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }) : null]);
    };
    const customer = d.linked_customer && typeof d.linked_customer === 'object' && text(d.linked_customer.customer_id)
      ? h('button', { class: 'link-chip link-customer', type: 'button', data: { ref: text(d.linked_customer.customer_id), kind: 'customer' } }, [
        h('span', { class: 'link-chip-label', text: text(d.linked_customer.name, 'Customer') }),
      ])
      : null;
    if (confidence === 'confident' && d.linked_order && typeof d.linked_order === 'object') {
      const o = d.linked_order;
      const ref = text(o.order_id);
      const row = h('div', {
        class: `link-strip is-confident${ref ? ' tappable' : ''}`, role: ref ? 'button' : null, tabindex: ref ? '0' : null,
        data: ref ? { ref, kind: 'order' } : {},
      }, [
        h('span', { class: 'link-kicker', text: 'Linked order' }),
        h('span', { class: 'link-main', text: [text(o.order_number, 'order'), text(o.total), text(o.fulfillment)].filter(Boolean).join(' · ') }),
        ref ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }) : null,
      ]);
      return h('div', { class: 'link-block' }, [row, customer ? h('div', { class: 'link-chips' }, [customer]) : null, note]);
    }
    const possible = list(d.possible_orders, 3);
    if (confidence === 'possible' && possible.length) {
      return h('div', { class: 'link-block is-possible' }, [
        h('span', { class: 'link-kicker', text: 'Possibly about' }),
        h('div', { class: 'link-chips' }, possible.map((o) => chip(o)).concat(customer ? [customer] : [])),
        note,
      ]);
    }
    return h('div', { class: 'link-block is-none' }, [
      h('p', { class: 'link-none', text: 'No confident order is linked' }),
      customer ? h('div', { class: 'link-chips' }, [customer]) : null,
      note,
    ]);
  }

  function renderEmailDraft(d, opts) {
    // An email after a proven change: saved as a draft in Gmail, or sent. There is no send
    // here — sending is a gesture on the confirmation card, answered by the Mac.
    const sent = text(d.state) === 'sent';
    return card('email_draft', [
      h('div', { class: 'card-head' }, [h('div', {}, [kicker(sent ? 'Sent' : 'Draft · saved in Gmail'), h('h2', { class: 'card-title', text: text(d.subject, '(no subject)') }), h('p', { class: 'card-sub', text: d.to ? `To ${text(d.to)}` : '' })]), h('div', { class: 'badges' }, [badge(sent ? 'Sent' : 'Draft', sent ? 'ok' : 'warn')])]),
      h('p', { class: 'msg-body', text: text(d.body) }),
      sent ? null : h('p', { class: 'future', text: 'Nothing has been sent. Say "send it" to send this draft, or send it from Gmail.' }),
    ], opts);
  }

  function renderAttention(d, opts) {
    const items = list(d.items, 8);
    const node = card('attention', [
      h('div', { class: 'card-head' }, [h('div', {}, [kicker('Attention'), h('h2', { class: 'card-title', text: `${items.length} require${items.length === 1 ? 's' : ''} attention` })])]),
      h('ul', { class: 'rows' }, items.map((a) => h('li', { class: 'row' }, [
        h('span', { class: 'row-main', text: text(a.title, '—') }),
        h('span', { class: 'row-sub', text: text(a.detail) }),
        h('span', { class: 'row-side' }, [badge(text(a.kind), a.level === 'red' ? 'bad' : a.level === 'green' ? 'ok' : 'warn')]),
      ]))),
    ], opts);
    if (d.for) node.dataset.for = text(d.for);
    return node;
  }

  // ------------------------------------------------------------------ actions
  //
  // A proposal the Mac has staged. The card shows what the Mac decided; the surface is how
  // the owner authorises it. The tap sends a proposal id and nothing else — no order, no
  // note, no argument — and the Mac executes what it stored.
  //
  // The dead time: a surface cannot be committed the instant it appears. A finger lifting
  // off the orb must never count as a tap on a card that materialised beneath it, so a
  // press that began before the surface armed does not commit when it ends, and nothing
  // commits while the app says it is busy (recording, submitting, waiting).

  // The grammar, as the tablet performs it. Each kind is one gesture with its own dead time:
  //   tap_commit        a tap, once the surface has armed
  //   swipe_commit      a swipe of the handle most of the way along the track, then release
  //   hold_to_arm       a hold of 900 ms (the Mac is told when it began), then a tap
  //   hold_drag_target  a hold of 900 ms, then, without lifting, the handle dragged onto the
  //                     target and released there
  // A hold is reported to the Mac the moment it begins (opts.onArm) and the Mac hands back a
  // token; the commit carries it. Nothing here decides what the change is or whether it may
  // be applied — the Mac decided both when it staged the card.
  const INTERACTIONS = ['tap_commit', 'swipe_commit', 'hold_to_arm', 'hold_drag_target'];
  const HOLD_MS = 900;
  const HOLD_MARGIN_MS = 150;       // the Mac measures the hold from its own clock, a round trip later
  const ARMED_FOR_MS = 5000;
  const SWIPE_FRACTION = 0.72;
  const SLOP_PX = 12;               // a wobble this big during a hold is a scroll, not a hold
  const DEFAULT_TRACK_PX = 300;

  function renderConfirmation(d, opts) {
    opts = opts || {};
    const risk = text(d.risk, text(d.tier, 'amber')) === 'red' ? 'red' : 'amber';
    const interaction = d.interaction && typeof d.interaction === 'object' ? d.interaction : {};
    const kind = text(interaction.kind, 'tap_commit');
    const supported = INTERACTIONS.indexOf(kind) !== -1;
    const armedAfter = num(interaction.armed_after_ms) === null ? 650 : Math.max(0, interaction.armed_after_ms);
    const status = text(d.status, 'pending');
    // The Mac already knows whether a gesture from this tablet could apply it. When it
    // cannot, the surface says so and never arms: an honest card beats a button that fails.
    const blocked = d.commit && typeof d.commit === 'object' && d.commit.allowed === false ? d.commit : null;
    const live = supported && status === 'pending' && Boolean(d.proposal_id) && !blocked;
    const label = live ? text(interaction.label, gestureLabel(kind)) : (blocked ? blockedLabel(blocked.code) : (supported ? settledLabel(status) : 'Needs a newer app build'));
    const surface = buildSurface(kind, label, text(interaction.target), live ? 'arming' : (blocked ? 'unavailable' : (supported ? status : 'unsupported')), live);
    const facts = list(d.facts, 8).filter((f) => text(f.value));
    const footer = text(interaction.footer, 'nothing happens until you tap');
    const node = card('confirmation', [
      h('div', { class: 'card-head' }, [
        h('div', { class: `mark ${risk === 'red' ? 'bad' : 'warn'}` }, h('span', { text: '!' })),
        h('div', {}, [
          kicker(blocked ? 'Prepared · cannot apply from here' : (risk === 'red' ? 'Proposed · needs care' : 'Proposed')),
          h('h2', { class: 'card-title', text: text(d.title, 'Confirm') }),
          h('p', { class: 'card-sub', text: text(d.entity, text(d.detail)) }),
        ]),
      ]),
      d.summary ? h('blockquote', { class: 'action-summary', text: text(d.summary) }) : null,
      // An email's whole text, when the change is an email: what the gesture sends, read here.
      d.body ? h('blockquote', { class: 'action-summary action-body' }, h('p', { class: 'msg-body', text: text(d.body) })) : null,
      // What the gesture authorises, fact by fact, from the Mac. The owner reads this, not
      // the model's sentence, before moving a hand.
      facts.length ? h('dl', { class: 'facts' }, facts.map((f) => [h('dt', { text: text(f.label) }), h('dd', { class: text(f.tone) || null, text: text(f.value) })]).flat()) : null,
      d.detail && d.entity ? h('p', { class: 'card-meta', text: text(d.detail) }) : null,
      surface,
      // The reason a gesture would be refused is the one line the owner must read: body
      // size, not the 11 px caption.
      blocked ? h('p', { class: 'card-sub action-why', text: text(blocked.reason) }) : null,
      h('p', { class: 'action-meta', text: live ? (num(d.ttl_s) !== null ? `Waits ${Math.round(d.ttl_s)} s · ${footer}` : capitalise(footer)) : '' }),
    ], Object.assign({ className: `tier-${risk} kind-${kind}` }, opts));
    node.dataset.proposal = text(d.proposal_id);
    node.dataset.ref = text(d.entity_ref);
    if (live) wireGesture(node, surface, kind, text(d.proposal_id), armedAfter, opts, num(d.ttl_s), (left) => `Waits ${left} s · ${footer}`);
    return node;
  }

  function capitalise(s) { const t = text(s); return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }

  function gestureLabel(kind) {
    return { tap_commit: 'Tap to apply', swipe_commit: 'Swipe to apply', hold_to_arm: 'Hold to arm, then tap', hold_drag_target: 'Hold, then drag to the target' }[kind] || 'Not available';
  }

  // The surface for a kind. A tap is a plain surface; a swipe and a drag carry a track with a
  // handle, and a drag carries a target at the far end that names the consequence.
  function buildSurface(kind, label, target, state, live) {
    const withTrack = kind === 'swipe_commit' || kind === 'hold_drag_target';
    const children = [h('span', { class: 'action-label', text: label }), h('span', { class: 'action-arm', 'aria-hidden': 'true' })];
    if (withTrack) {
      children.push(h('span', { class: 'action-track', 'aria-hidden': 'true' }, [
        h('span', { class: 'action-handle' }, [h('span', { class: 'action-grip', text: '›' })]),
        kind === 'hold_drag_target' ? h('span', { class: 'action-target', text: target || 'Drop to apply' }) : null,
      ]));
    }
    return h('div', {
      class: `action-surface kind-${kind}`, role: 'button', tabindex: live ? '0' : '-1', 'aria-disabled': 'true',
      data: { state, kind },
    }, children);
  }

  // Who is stopping the gesture, in five words: CLIVE's switch, its allow-list, this
  // device's login, or Shopify's grant. "This device" is blamed only when it is the reason,
  // and none of them names the machine CLIVE runs on (GENERATIVE_UI_V1 §4).
  function blockedLabel(code) {
    return {
      writes_disabled: 'Changes are switched off on the server', allow_list_missing: 'No allowed logins set on the server',
      not_authorised: "This device's login is not on the server's list", not_authorised_local: 'The server itself may not apply changes',
      scope_missing: 'Shopify has not granted the scope this needs',
    }[text(code)] || "Can't apply from here";
  }

  // The words for a status the Mac has already settled. One table, in web/action-state.js,
  // beside the named state each word means; the page reads the same one.
  function settledLabel(status) {
    const machine = actionState();
    return machine ? machine.labelFor(text(status), 'Not available') : 'Not available';
  }

  // The state machine, however this file was loaded: on the tablet it is on the window, and
  // under Node it is the module beside this one. Looked up when needed rather than at load,
  // so the order the two scripts are parsed in cannot matter.
  function actionState() {
    const global = typeof globalThis !== 'undefined' ? globalThis : null;
    if (global && global.CrooksActionState) return global.CrooksActionState;
    if (typeof require === 'function') {
      try { return require('./action-state.js'); } catch (error) { /* the page keeps it on the window */ }
    }
    return null;
  }

  // One wiring for every kind. The states a surface passes through, in the vocabulary of
  // web/action-state.js (the token each one writes into dataset.state in brackets):
  //   ARMING (arming) → ARMED (armed) → (ARMING/ARMED again while a hold runs: holding, held)
  //   → EXECUTING (committing) → VERIFYING (verifying) → one of the four terminal states.
  // Only the Mac settles a card into a terminal state, and a terminal card is never moved.
  // A press that began before arming never counts, whatever it ends as; nothing counts while
  // the app says it is busy; and a settled surface answers to nothing.
  function wireGesture(node, surface, kind, proposalId, armedAfter, opts, ttlS, word) {
    const now = opts.now || (() => Date.now());
    const shown = now();
    const timers = opts.timers || { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) };
    const trackWidth = () => {
      const track = surface.querySelector ? surface.querySelector('.action-track') : null;
      const w = track && typeof track.clientWidth === 'number' && track.clientWidth > 0 ? track.clientWidth : (num(opts.trackWidth) || DEFAULT_TRACK_PX);
      const handle = surface.querySelector ? surface.querySelector('.action-handle') : null;
      const hw = handle && typeof handle.clientWidth === 'number' && handle.clientWidth > 0 ? handle.clientWidth : 56;
      return Math.max(1, w - hw);
    };
    let committed = false;
    let press = null;        // { at, x, y, dx } for the press in progress
    let holdTimer = null;
    let heldTimer = null;
    let nonce = '';          // the Mac's token for the hold in progress
    let armRequest = 0;
    const armed = () => now() - shown >= armedAfter;
    const blocked = () => (typeof opts.blocked === 'function' ? Boolean(opts.blocked()) : false);
    const state = () => surface.dataset.state;
    const setState = (s) => { surface.dataset.state = s; surface.setAttribute('aria-disabled', s === 'armed' || s === 'held' ? 'false' : 'true'); };
    const labelEl = surface.childNodes[0];
    const baseLabel = labelEl.textContent;
    const say = (words) => { labelEl.textContent = String(words); };
    const handle = surface.querySelector ? surface.querySelector('.action-handle') : null;
    const moveHandle = (px) => { if (handle && handle.style && handle.style.setProperty) handle.style.setProperty('--dx', `${Math.round(px)}px`); surface.dataset.dx = String(Math.round(px)); };
    const needsHold = kind === 'hold_to_arm' || kind === 'hold_drag_target';
    const needsTrack = kind === 'swipe_commit' || kind === 'hold_drag_target';
    // The visible fill lasts exactly as long as the arming does: one number, ours.
    if (surface.style && surface.style.setProperty) surface.style.setProperty('--arm-ms', `${Math.round(armedAfter)}ms`);
    if (surface.style && surface.style.setProperty) surface.style.setProperty('--hold-ms', `${HOLD_MS + HOLD_MARGIN_MS}ms`);
    const armTimer = timers.set(() => { if (!committed && state() === 'arming') setState('armed'); }, armedAfter);
    const expiryTimer = ttlS !== null && ttlS !== undefined ? timers.set(() => {
      if (committed || ['arming', 'armed', 'holding', 'held'].indexOf(state()) === -1) return;
      node.settle('expired', 'Expired');
      // An offer that lapsed here has lapsed there too; the Mac is told, so that its own copy
      // stops being something the owner could still be waiting on. Nothing is applied by it.
      if (typeof opts.onExpire === 'function') opts.onExpire(proposalId);
    }, Math.max(0, ttlS * 1000 - 1000)) : null;
    const metas = node.querySelectorAll ? node.querySelectorAll('.action-meta') : [];
    const meta = metas.length ? metas[metas.length - 1] : null;
    let countdown = null;
    if (meta && word && ttlS !== null && ttlS !== undefined) {
      const tick = () => {
        const left = Math.max(0, Math.round(ttlS - (now() - shown) / 1000));
        if (committed) return;
        meta.textContent = word(left);
        if (left > 0) countdown = timers.set(tick, 1000);
      };
      countdown = timers.set(tick, 1000);
    }
    const clearHold = () => { if (holdTimer !== null) { timers.clear(holdTimer); holdTimer = null; } };
    const clearHeld = () => { if (heldTimer !== null) { timers.clear(heldTimer); heldTimer = null; } };
    const disarmHold = (why) => {
      // Back to armed: the hold did not complete, or it lapsed. The token is worthless now.
      clearHold(); clearHeld(); nonce = ''; press = null; moveHandle(0);
      if (!committed && ['holding', 'held'].indexOf(state()) !== -1) setState('armed');
      say(why || baseLabel);
      if (why) timers.set(() => { if (!committed && state() === 'armed') say(baseLabel); }, 1400);
    };
    const commit = () => {
      committed = true;
      clearHold(); clearHeld();
      setState('committing');
      say('Applying…');
      if (typeof opts.onCommit === 'function') opts.onCommit(proposalId, node, nonce);
    };
    node.settle = (s, label) => {
      timers.clear(armTimer);
      if (expiryTimer !== null) timers.clear(expiryTimer);
      if (countdown !== null) { timers.clear(countdown); countdown = null; }
      clearHold(); clearHeld();
      if (meta && s !== 'armed') meta.textContent = '';
      committed = s !== 'armed';
      press = null; nonce = '';
      moveHandle(0);
      setState(s);
      if (label !== undefined) say(label);
    };

    // ---- the hold: told to the Mac as it begins; completes only if the hand stays still.
    const beginHold = () => {
      setState('holding');
      const request = ++armRequest;
      nonce = '';
      const holdFor = (ms) => {
        clearHold();
        holdTimer = timers.set(() => {
          holdTimer = null;
          if (committed || state() !== 'holding' || !press) return;
          if (typeof opts.onArm === 'function' && !nonce) {
            // The hold is long enough but the Mac has not answered yet: keep holding a little.
            holdTimer = timers.set(() => {
              holdTimer = null;
              if (committed || state() !== 'holding' || !press) return;
              if (!nonce) { disarmHold("The server hasn't armed it"); return; }
              held();
            }, 1200);
            return;
          }
          held();
        }, ms);
      };
      if (typeof opts.onArm === 'function') {
        Promise.resolve(opts.onArm(proposalId)).then((token) => {
          if (request !== armRequest || committed) return;
          if (!token) { disarmHold("The server won't arm this"); return; }
          nonce = String(token);
          // The Mac measures the hold from when it stamped this token, which is never later
          // than now: the hold here runs its full length from now as well, so the Mac's
          // clock is met however long the round trip took.
          if (state() === 'holding' && press) holdFor(HOLD_MS + HOLD_MARGIN_MS);
        }).catch(() => { if (request === armRequest && !committed) disarmHold("The server won't arm this"); });
      }
      holdFor(HOLD_MS + HOLD_MARGIN_MS);
    };
    const held = () => {
      setState('held');
      say(kind === 'hold_drag_target' ? 'Now drag to the target' : 'Armed · tap to apply');
      // A tap or a drag must follow within the window the Mac keeps, or the arming lapses
      // here as it does there — the surface never says "held" about a hold the Mac forgot.
      heldTimer = timers.set(() => { if (!committed && state() === 'held') disarmHold('Hold again'); }, ARMED_FOR_MS);
    };

    const canBegin = () => armed() && !blocked() && !committed;

    surface.addEventListener('contextmenu', (e) => { if (e && e.preventDefault) e.preventDefault(); });
    surface.addEventListener('selectstart', (e) => { if (e && e.preventDefault) e.preventDefault(); });

    surface.addEventListener('pointerdown', (e) => {
      const x = e && typeof e.clientX === 'number' ? e.clientX : 0;
      const y = e && typeof e.clientY === 'number' ? e.clientY : 0;
      if (e && e.currentTarget && typeof e.currentTarget.setPointerCapture === 'function' && e.pointerId !== undefined) {
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch (error) { /* unsupported */ }
      }
      const s = state();
      if (!canBegin()) { press = null; return; }
      if (s === 'armed') {
        press = { at: now(), x, y, dx: 0 };
        surface.dataset.pressed = 'true';
        if (needsHold) beginHold();
        return;
      }
      if (s === 'held' && kind === 'hold_to_arm') {
        // The tap that follows the hold.
        press = { at: now(), x, y, dx: 0, tap: true };
        surface.dataset.pressed = 'true';
        return;
      }
      press = null;
    });

    surface.addEventListener('pointermove', (e) => {
      if (!press || committed) return;
      const x = e && typeof e.clientX === 'number' ? e.clientX : press.x;
      const y = e && typeof e.clientY === 'number' ? e.clientY : press.y;
      const dx = x - press.x;
      const dy = y - press.y;
      const s = state();
      if (s === 'holding') {
        if (Math.abs(dx) > SLOP_PX || Math.abs(dy) > SLOP_PX) { disarmHold('Hold still'); }
        return;
      }
      if (needsTrack && (s === 'armed' && kind === 'swipe_commit' || s === 'held' && kind === 'hold_drag_target')) {
        if (Math.abs(dy) > 2 * SLOP_PX && dx < SLOP_PX) { press = null; moveHandle(0); if (s === 'held') disarmHold(''); return; }   // the scroller wins
        press.dx = Math.max(0, Math.min(trackWidth(), dx));
        moveHandle(press.dx);
      }
    });

    const end = (cancelled) => {
      if (!press) { surface.dataset.pressed = 'false'; return; }
      const p = press;
      press = null;
      surface.dataset.pressed = 'false';
      const s = state();
      if (cancelled || committed || blocked() || !armed()) { if (s === 'holding' || s === 'held') disarmHold(''); moveHandle(0); return; }
      if (kind === 'tap_commit') { if (s === 'armed') commit(); return; }
      if (kind === 'swipe_commit') {
        if (s === 'armed' && p.dx >= SWIPE_FRACTION * trackWidth()) commit(); else moveHandle(0);
        return;
      }
      if (kind === 'hold_to_arm') {
        if (s === 'holding') { disarmHold(''); return; }          // lifted before the hold completed
        if (s === 'held' && p.tap && nonce) { commit(); return; }  // the tap after the hold
        return;                                                    // the lift that ends the hold itself
      }
      if (kind === 'hold_drag_target') {
        if (s === 'holding') { disarmHold(''); return; }
        if (s === 'held') { if (p.dx >= SWIPE_FRACTION * trackWidth() && nonce) commit(); else disarmHold(''); }
      }
    };
    surface.addEventListener('pointerup', () => end(false));
    surface.addEventListener('pointercancel', () => end(true));
    surface.addEventListener('pointerleave', () => { if (kind === 'tap_commit') end(true); });
    surface.addEventListener('keydown', (e) => {
      // A keyboard has no hold: Enter applies a tap kind only.
      if (kind !== 'tap_commit') return;
      if ((e.key === 'Enter' || e.key === ' ') && canBegin() && state() === 'armed') {
        if (e.preventDefault) e.preventDefault();
        commit();
      }
    });
  }

  // Kept for the success card's undo and for anyone who only ever needs a tap.
  function wireTapCommit(node, surface, proposalId, armedAfter, opts, ttlS, word) {
    return wireGesture(node, surface, 'tap_commit', proposalId, armedAfter, opts, ttlS, word);
  }

  const CHECK = () => {
    const svg = doc().createElementNS ? doc().createElementNS('http://www.w3.org/2000/svg', 'svg') : h('span');
    if (svg.setAttribute) {
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('aria-hidden', 'true');
      const path = doc().createElementNS ? doc().createElementNS('http://www.w3.org/2000/svg', 'path') : h('span');
      if (path.setAttribute) path.setAttribute('d', 'M5 12.5l4.5 4.5L19 7');
      svg.appendChild(path);
    }
    return svg;
  };

  // ---- a proven change to a thread's home, applied to the deck that is already on screen.
  //
  // Archive is the one verified change whose consequence is a card the owner is still looking
  // at: he archives a thread out of a queue and the queue still has it in it. The Mac names
  // the thread that left the inbox on the success card (`archived`, `restored` —
  // app/presentation.py:_inbox_change); this marks the thread's own card and takes its row out
  // of the active queue, and the undo puts both back. Nothing here decides what archiving
  // means, and nothing here asks the Mac anything: it is one fact, applied.
  function settleThread(root, d) {
    if (!root || typeof root.querySelectorAll !== 'function' || !d || typeof d !== 'object') return 0;
    const gone = d.archived && typeof d.archived === 'object' ? text(d.archived.ref) : '';
    const back = d.restored && typeof d.restored === 'object' ? text(d.restored.ref) : '';
    const ref = gone || back;
    if (!ref) return 0;
    let touched = 0;
    // `querySelectorAll` never matches the root, and the page hands this single CARDS as well
    // as decks — the copy of the queue on the back stack is one detached node, and it is the
    // one the owner returns to.
    const within = (sel) => {
      const found = Array.prototype.slice.call(root.querySelectorAll(sel));
      if (root.classList && root.classList.contains(sel.replace('.', ''))) found.unshift(root);
      return found;
    };
    // The thread's own card, if it is open: it says what it now is, in a word.
    for (const open of within('.card-email_thread')) {
      if (text(open.dataset.ref) !== ref && text(open.dataset.thread) !== ref) continue;
      touched += 1;
      const head = open.querySelector('.card-head');
      for (const mark of open.querySelectorAll('.thread-archived')) {
        if (mark.parentNode) mark.parentNode.removeChild(mark);
      }
      if (gone) {
        open.classList.add('is-archived');
        if (head) head.appendChild(h('span', { class: 'badge ok thread-archived', text: 'Archived · out of the inbox' }));
      } else {
        open.classList.remove('is-archived');
      }
    }
    // And the queue it was in. An archived thread is not a row with a line through it: it has
    // left, and the card says how many left so the count on screen is not a lie.
    for (const queue of within('.card-email_list')) {
      const rows = queue.querySelector('.rows');
      if (!rows) continue;
      if (gone) {
        for (const row of rows.querySelectorAll('.row')) {
          if (text(row.dataset.ref) !== ref) continue;
          rows.removeChild(row);
          touched += 1;
          const kept = Number(queue.dataset.archived || 0) + 1;
          queue.dataset.archived = String(kept);
          let note = queue.querySelector('.queue-note');
          if (!note) { note = h('p', { class: 'card-note queue-note' }); queue.appendChild(note); }
          note.textContent = `${kept} archived and out of this queue.`;
        }
      }
    }
    return touched;
  }

  function renderSuccess(d, opts) {
    opts = opts || {};
    // The deck the owner is looking at, settled from the one fact the Mac sent. Before the
    // new card is appended, because what it changes is the cards that are already there.
    const where = doc() && doc().body ? doc().body : null;
    if (where) settleThread(where, d);
    // And the screens the owner will come BACK to. The page keeps its own copies of those as
    // detached nodes, which nothing in the document can reach, so it settles them itself —
    // otherwise Back from a proven archive lands on a queue that still lists the thread.
    if (typeof opts.onThreadMoved === 'function' && (d.archived || d.restored)) {
      try { opts.onThreadMoved(d); } catch (error) { /* the proof is drawn either way */ }
    }
    const node = card('success', [
      h('div', { class: 'card-head' }, [h('div', { class: 'mark ok' }, CHECK()), h('div', {}, [kicker('Done'), h('h2', { class: 'card-title', text: text(d.title, 'Done') }), h('p', { class: 'card-sub', text: text(d.detail) })])]),
      // What the Mac's proof could not yet see: said on the card as well as out loud.
      d.note ? h('p', { class: 'card-meta note-line', text: text(d.note) }) : null,
    ], Object.assign({ className: 'success' }, opts));
    // Keyed by the proposal that is still live. The forward one is settled and nothing looks
    // it up again; the undo is the card the Mac may name in a turn's `revoked` list.
    // A reversible action offers its undo: a second proposal the Mac staged, authorised the
    // same way (its own dead time, its own tap) and executed by the same path.
    const undo = d.undo && typeof d.undo === 'object' && d.undo.proposal_id ? d.undo : null;
    // Which thread this card is the proof about, so a deck redrawn after the card lands can
    // be settled again from the card itself rather than from a payload nobody kept.
    if (d.archived && typeof d.archived === 'object' && text(d.archived.ref)) node.dataset.archived = text(d.archived.ref);
    if (d.restored && typeof d.restored === 'object' && text(d.restored.ref)) node.dataset.restored = text(d.restored.ref);
    if (!undo && d.proposal_id) node.dataset.proposal = text(d.proposal_id);
    if (undo) {
      const armedAfter = num(undo.armed_after_ms) === null ? 650 : undo.armed_after_ms;
      // The undo is as grave as the change it reverses: its kind comes from the Mac.
      const kind = INTERACTIONS.indexOf(text(undo.interaction)) !== -1 ? text(undo.interaction) : 'tap_commit';
      const surface = buildSurface(kind, kind === 'tap_commit' ? text(undo.label, 'Undo') : `${text(undo.label, 'Undo')} · ${gestureLabel(kind).toLowerCase()}`, '', 'arming', true);
      surface.classList.add('quiet');
      node.dataset.proposal = text(undo.proposal_id);
      // What this surface is: an offer against a change that is FINISHED, not a change still
      // waiting to be made. Anything counting work outstanding reads this and passes over it.
      node.dataset.undoOf = text(undo.undo_of || d.proposal_id);
      node.appendChild(surface);
      node.appendChild(h('p', { class: 'action-meta', text: num(undo.ttl_s) !== null ? `Undo available for ${Math.round(undo.ttl_s)} s` : '' }));
      // The undo has its own clock on the Mac, and says how much of it is left. When it runs
      // out the Mac is told, so an offer nobody took up stops being anything at all.
      const undoOpts = Object.assign({}, opts, { onExpire: opts.onUndoExpire });
      wireGesture(node, surface, kind, text(undo.proposal_id), armedAfter, undoOpts, num(undo.ttl_s), (left) => (left > 0 ? `Undo available for ${left} s` : 'The undo has expired.'));
    }
    return node;
  }

  function renderError(d, opts) {
    return card('error', [
      h('div', { class: 'card-head' }, [h('div', { class: 'mark bad' }, h('span', { text: '×' })), h('div', {}, [kicker(text(d.service, 'assistant')), h('h2', { class: 'card-title', text: text(d.title, 'Something went wrong') }), h('p', { class: 'card-sub', text: text(d.recovery) })])]),
    ], opts);
  }

  // ---- the read layer's cards: figures the Mac formatted, drawn as text and bars.

  function analyticHead(kicker_, d, fallback) {
    return h('div', { class: 'card-head' }, [h('div', {}, [kicker(kicker_), h('h2', { class: 'card-title', text: text(d.title, fallback) }), h('p', { class: 'card-meta', text: text(d.subtitle) })])]);
  }

  function analyticFoot(d) {
    return [
      d.complete === false ? h('p', { class: 'card-note', text: 'Partial: the server is still reading Shopify.' }) : null,
      d.truncated ? h('p', { class: 'card-note', text: 'More rows than shown.' }) : null,
      d.note ? h('p', { class: 'card-note', text: text(d.note) }) : null,
    ];
  }

  function legend(d) {
    const measured = Array.isArray(d.measured) ? d.measured : [];
    const derived = Array.isArray(d.derived) ? d.derived : [];
    if (!derived.length) return null;
    return h('p', { class: 'legend' }, [
      measured.length ? h('span', { text: `Measured: ${measured.join(', ')}` }) : null,
      h('span', { class: 'derived', text: `Derived: ${derived.join(', ')}` }),
    ]);
  }

  function renderRanking(d, opts) {
    const rows = list(d.rows, 25);
    const kick = d.mode === 'restock' ? 'Restock priority' : 'Ranking';
    return card('ranking', [
      analyticHead(kick, d, d.mode === 'restock' ? 'Restock priority' : 'Best sellers'),
      h('ol', { class: 'rank-rows' }, rows.map((r) => {
        const primary = r.primary && typeof r.primary === 'object' ? r.primary : {};
        const secondary = r.secondary && typeof r.secondary === 'object' ? r.secondary : null;
        const pct = num(r.pct);
        const fill = pct === null ? null : h('span', { class: 'rank-fill' });
        if (fill && fill.style && fill.style.setProperty) fill.style.setProperty('--w', `${Math.max(0, Math.min(100, pct))}%`);
        /* A row is tappable only where it has somewhere to go. `data-ref` used to be written
           unconditionally, so a ranking row for a product the Mac had never read still
           posted `open.entity` and took a `not_held` — D-6 exactly, and §33's click sweep
           found three of them in one products landing. The Mac now withholds the ref for a
           destination it could not open (`app/presentation.py:_withhold_dead_refs`), and
           this is the other half: no ref, no attributes, and a `data-label` so the name that
           travels with a tap is the row's own rather than every word on it run together. */
        const rref = text(r.ref);
        const rkind = text(r.kind);
        const opens = Boolean(rref && rkind);
        const li = h('li', {
          class: `rank${r.known === false ? ' is-unknown' : ''}${opens ? ' tappable' : ''}`,
          role: opens ? 'button' : null,
          tabindex: opens ? '0' : null,
          data: opens ? { ref: rref, kind: rkind, label: text(r.label) } : {},
        }, [
          h('span', { class: 'rank-n', text: num(r.rank) === null ? '' : String(r.rank) }),
          h('div', { class: 'rank-main' }, [
            h('div', { class: 'rank-label', text: text(r.label, '—') }),
            r.sublabel ? h('div', { class: 'rank-sub', text: text(r.sublabel) }) : null,
            fill ? h('div', { class: 'rank-track' }, fill) : null,
            list(r.lines, 6).length ? h('div', { class: 'rank-lines' }, list(r.lines, 6).map((l) => h('span', { class: l.derived ? 'derived' : '', text: `${text(l.value, '—')} ${text(l.label)}` }))) : null,
          ]),
          h('div', { class: 'rank-side' }, [
            h('div', { class: 'rank-v', text: text(primary.value, '—') }),
            h('div', { class: 'rank-k', text: text(primary.label) }),
            secondary ? h('div', { class: 'card-meta', text: `${text(secondary.value, '—')} ${text(secondary.label)}` }) : null,
          ]),
        ]);
        return li;
      })),
      // Whose totals these are, when they are not the rows' own (app/analytics/present.py).
      list(d.totals, 4).length && text(d.totals_label) ? h('p', { class: 'card-meta', text: text(d.totals_label) }) : null,
      list(d.totals, 4).length ? h('div', { class: `stats${list(d.totals, 4).length === 3 ? ' three' : ''}` }, list(d.totals, 4).map((t) => h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: text(t.value, '—') }), h('div', { class: 'stat-k', text: text(t.label) })]))) : null,
      legend(d),
    ].concat(analyticFoot(d)), opts);
  }

  function renderMetricGroup(d, opts) {
    const metrics = list(d.metrics, 6);
    return card('metric_group', [
      analyticHead('Figures', d, 'Sales'),
      h('div', { class: `stats${metrics.length === 3 ? ' three' : ''}` }, metrics.map((m) => h('div', { class: 'stat' }, [
        h('div', { class: 'stat-v', text: text(m.value, '—') }),
        h('div', { class: 'stat-k', text: `${text(m.label)}${m.measured === false ? ' · derived' : ''}` }),
      ]))),
    ].concat(analyticFoot(d)), opts);
  }

  function renderTable(d, opts) {
    const columns = list(d.columns, 8);
    const rows = list(d.rows, 25);
    return card('table', [
      analyticHead('Table', d, 'Table'),
      h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, [
        h('thead', {}, h('tr', {}, columns.map((c) => h('th', { class: c.numeric ? 'num' : '', text: text(c.label) })))),
        h('tbody', {}, rows.map((r) => h('tr', { data: { ref: text(r.ref) } }, (Array.isArray(r.cells) ? r.cells.slice(0, 8) : []).map((cell, i) => h('td', { class: columns[i] && columns[i].numeric ? 'num' : '', text: text(cell, '—') }))))),
      ])),
    ].concat(analyticFoot(d)), opts);
  }

  function renderComparison(d, opts) {
    const current = d.current && typeof d.current === 'object' ? d.current : {};
    const previous = d.previous && typeof d.previous === 'object' ? d.previous : {};
    const col = (side, cls) => h('div', { class: `compare-col ${cls}` }, [
      h('div', { class: 'compare-k', text: text(side.label, cls === 'now' ? 'This period' : 'Before') }),
      list(side.metrics, 4).map((m) => h('div', { class: 'compare-row' }, [h('span', { class: 'card-meta', text: text(m.label) }), h('strong', { text: text(m.value, '—') })])),
    ]);
    return card('comparison', [
      analyticHead('Compared', d, 'Compared'),
      h('div', { class: 'compare' }, [col(current, 'now'), col(previous, 'then')]),
      list(d.changes, 4).length ? h('div', { class: 'changes' }, list(d.changes, 4).map((c) => h('span', { class: `change ${text(c.direction, 'flat')}`, text: `${text(c.label)} ${text(c.delta, '')} (${text(c.pct, '—')})`.replace('  ', ' ') }))) : null,
    ].concat(analyticFoot(d)), opts);
  }

  function renderVariantMatrix(d, opts) {
    const rows = Array.isArray(d.rows) ? d.rows.slice(0, 12).map((r) => text(r)) : [];
    const cols = Array.isArray(d.cols) ? d.cols.slice(0, 10).map((c) => text(c)) : [];
    const cells = list(d.cells, 64);
    const at = (r, c) => cells.find((x) => text(x.row) === r && text(x.col) === c);
    let top = 0;
    for (const c of cells) top = Math.max(top, num(c.value) || 0);
    return card('variant_matrix', [
      analyticHead('By size', d, 'Sizes'),
      h('div', { class: 'matrix-wrap' }, h('table', { class: 'matrix' }, [
        h('thead', {}, h('tr', {}, [h('th', { text: text(d.row_label) })].concat(cols.map((c) => h('th', { text: c }))))),
        h('tbody', {}, rows.map((r) => h('tr', {}, [h('td', { text: r })].concat(cols.map((c) => {
          const cell = at(r, c);
          const value = cell ? num(cell.value) : null;
          return h('td', { class: value === null ? 'zero' : (top && value === top ? 'hot' : ''), text: cell ? text(cell.display, '—') : '·' });
        }))))),
      ])),
      d.metric ? h('p', { class: 'card-meta', text: text(d.metric) }) : null,
    ].concat(analyticFoot(d)), opts);
  }

  function renderTrend(d, opts) {
    const points = list(d.points, 31);
    const values = points.map((p) => Math.max(0, num(p.value) || 0));
    const top = Math.max(1, ...values);
    return card('trend', [
      analyticHead('Trend', d, 'Trend'),
      d.total ? h('div', { class: 'trend-total', text: text(d.total) }) : null,
      points.length ? h('div', { class: 'bars', 'aria-hidden': 'true' }, points.map((p, i) => {
        const pct = Math.max(4, Math.min(100, Math.round((values[i] / top) * 100)));
        const bar = h('span', { class: 'bar', data: { pct: String(pct) } });
        if (bar.style) bar.style.height = `${pct}%`;
        return h('span', { class: 'bar-col', title: text(p.label) }, [bar, h('span', { class: 'bar-day', text: text(p.label).slice(-2) })]);
      })) : null,
      points.length ? h('ul', { class: 'rows compact' }, points.slice(-7).map((p) => h('li', { class: 'row' }, [h('span', { class: 'row-main', text: text(p.label) }), h('span', { class: 'row-side' }, h('strong', { text: text(p.display, '—') }))]))) : null,
      d.metric ? h('p', { class: 'card-meta', text: text(d.metric) }) : null,
    ].concat(analyticFoot(d)), opts);
  }

  // The working set: what "these" means now, and what it comes to.
  //
  // This card always follows one that has just listed the very same members, and the nav bar
  // carries the set as a chip besides — so a full-dress card repeating the title, re-listing
  // "#1940 · #1938 · #1939" and explaining the word "these" was 276px of a 1280px screen to
  // say three things the owner had just read. What is genuinely only here is the arithmetic
  // over the set, so that is what is left: a strip of totals under the list they belong to.
  function renderWorkingSet(d, opts) {
    const lines = list(d.lines, 3);
    // Was 'These'. The three words on this strip say HOW the set came to be, and for a set
    // that was simply listed the answer was a demonstrative pronoun with nothing after it:
    // THESE · 3 orders. §26 asks for human words, and 'This list' is one — same axis as
    // Narrowed and Cross-referenced, and a phrase rather than a dangling 'these'.
    const where = d.step === 'filter' ? 'Narrowed' : d.step === 'correlate' ? 'Cross-referenced' : 'This list';
    const node = card('working_set', [
      h('p', { class: 'set-strip-head' }, [
        h('span', { class: 'set-strip-kicker', text: where }),
        h('span', { text: `${num(d.count) === null ? '?' : d.count} ${text(d.kind, 'items')}${d.truncated ? ' · first 500' : ''}` }),
        d.parent_label ? h('span', { class: 'set-strip-from', text: `from ${text(d.parent_label)}` }) : null,
      ]),
      lines.length ? h('div', { class: `stats${lines.length === 3 ? ' three' : ''}` }, lines.map((l) => h('div', { class: 'stat' }, [h('div', { class: 'stat-v', text: text(l.value, '—') }), h('div', { class: 'stat-k', text: text(l.label) })]))) : null,
    ], opts);
    node.classList.add('set-strip');
    node.dataset.set = text(d.set_id);
    return node;
  }

  // ---- what this build can do. The manifest, grouped by the part of the shop it touches.
  // Thirty capabilities read aloud are not a list; the sentence stays one line and this is
  // the list. Chips are questions the fast lane has a recipe for, so tapping one is answered
  // without the model — they post the same text a spoken question would.

  function capabilityRow(item) {
    const state = text(item.state);
    const tone = state === 'ready' ? 'good' : state === 'blocked' ? 'bad' : state === 'disabled' ? 'quiet' : 'quiet';
    const kindLabel = item.kind === 'change' ? 'Change' : item.kind === 'bulk' ? 'Bulk' : 'Read';
    return h('li', { class: 'cap-row' }, [
      h('div', { class: 'cap-main' }, [
        h('span', { class: 'cap-what', text: text(item.what, item.name) }),
        h('span', { class: 'cap-kind', text: kindLabel }),
      ]),
      state && state !== 'ready' ? badge(state, tone) : null,
    ]);
  }

  function renderCapability(d, opts) {
    const groups = list(d.groups, 8);
    const counts = d.counts && typeof d.counts === 'object' ? d.counts : {};
    const changed = d.changed && typeof d.changed === 'object' ? d.changed : null;
    const examples = strings(d.examples, 6);
    const meta = [];
    if (num(counts.reads) !== null) meta.push(`${counts.reads} readings`);
    if (num(counts.changes) !== null) meta.push(d.writes_enabled ? `${counts.changes} changes` : 'changes off');
    if (num(counts.bulk) !== null && counts.bulk) meta.push(`${counts.bulk} bulk`);
    const panels = groups.map((g) => ({
      name: text(g.area, 'other'),
      label: text(g.label, 'Other'),
      node: [
        h('ul', { class: 'cap-rows' }, list(g.items, 10).map(capabilityRow)),
        g.truncated ? h('p', { class: 'card-note', text: 'More than shown.' }) : null,
      ],
    }));
    const node = card('capability', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker('Capabilities'),
        h('h2', { class: 'card-title', text: text(d.title, 'What this can do') }),
        h('p', { class: 'card-meta', text: meta.join(' \u00b7 ') }),
      ])]),
      d.note ? h('p', { class: 'card-note', text: text(d.note) }) : null,
      changed && (strings(changed.added, 12).length || strings(changed.gone, 12).length)
        ? section('cap-changed', 'Since the last build', [
            strings(changed.added, 12).length
              ? h('ul', { class: 'cap-rows' }, strings(changed.added, 12).map((x) => h('li', { class: 'cap-row new', text: '+ ' + x })))
              : null,
            strings(changed.gone, 12).length
              ? h('ul', { class: 'cap-rows' }, strings(changed.gone, 12).map((x) => h('li', { class: 'cap-row gone', text: '\u2212 ' + x })))
              : null,
          ])
        : null,
      panels.length ? tabs(panels, { initial: tabFor('capability', d, opts), onChange: tabReporter('capability', d, opts) }) : null,
      examples.length
        ? section('cap-examples', 'Try asking', [
            h('div', { class: 'chips' }, examples.map((q) => {
              const chip = h('button', { class: 'chip', type: 'button', text: q });
              chip.dataset.ask = q;
              return chip;
            })),
          ])
        : null,
    ], opts);
    node.dataset.build = text(d.build);
    return node;
  }

  // ---- bulk changes: one card for many proposals, and the count afterwards. The gesture
  // wiring is the confirmation card's; the id it names is the batch's.

  function renderBatchAction(d, opts) {
    opts = opts || {};
    const risk = text(d.risk, 'amber') === 'red' ? 'red' : 'amber';
    const interaction = d.interaction && typeof d.interaction === 'object' ? d.interaction : {};
    const kind = text(interaction.kind, 'hold_to_arm');
    const supported = INTERACTIONS.indexOf(kind) !== -1;
    const armedAfter = num(interaction.armed_after_ms) === null ? 650 : Math.max(0, interaction.armed_after_ms);
    const status = text(d.status, 'pending');
    const blocked = d.commit && typeof d.commit === 'object' && d.commit.allowed === false ? d.commit : null;
    const live = supported && status === 'pending' && Boolean(d.batch_id) && !blocked;
    const label = live ? text(interaction.label, gestureLabel(kind)) : (blocked ? blockedLabel(blocked.code) : (supported ? settledLabel(status) : 'Needs a newer app build'));
    const surface = buildSurface(kind, label, text(interaction.target, 'Apply to all'), live ? 'arming' : (blocked ? 'unavailable' : (supported ? status : 'unsupported')), live);
    const scope = d.set && typeof d.set === 'object' ? d.set : {};
    const eligible = num(d.eligible) === null ? 0 : d.eligible;
    const requested = num(d.requested) === null ? eligible : d.requested;
    const excluded = list(d.excluded, 50);
    const members = Array.isArray(d.members) ? d.members.map((m) => text(m)).filter(Boolean).slice(0, 50) : [];
    const facts = list(d.facts, 8).filter((f) => text(f.value));
    const footer = text(interaction.footer, 'nothing happens until you hold the card');
    const preview = d.preview && typeof d.preview === 'object' ? d.preview : null;
    const node = card('batch_action', [
      h('div', { class: 'card-head' }, [
        h('div', { class: `mark ${risk === 'red' ? 'bad' : 'warn'}` }, h('span', { text: String(eligible) })),
        h('div', {}, [
          kicker(blocked ? 'Prepared · cannot apply from here' : `Proposed for ${eligible} of ${requested}`),
          h('h2', { class: 'card-title', text: text(d.title, 'Apply to all') }),
          h('p', { class: 'card-sub', text: `${text(scope.label, 'the set')} · ${num(scope.count) === null ? requested : scope.count} ${text(scope.kind, 'items')}` }),
        ]),
      ]),
      d.summary ? h('blockquote', { class: 'action-summary', text: text(d.summary) }) : null,
      // A draft campaign: one member's email as it will be saved is the card; the template
      // it was filled from sits behind a fold, named as a template.
      preview && (preview.subject || preview.body) ? h('div', { class: 'batch-preview' }, [
        h('p', { class: 'card-meta', text: `As it will be saved for ${text(preview.to, 'the first customer')}` }),
        preview.subject ? h('p', { class: 'batch-preview-subject', text: text(preview.subject) }) : null,
        preview.body ? h('p', { class: 'msg-body', text: text(preview.body) }) : null,
      ]) : null,
      d.body ? h('details', { class: 'batch-members' }, [
        h('summary', { text: preview ? 'The template · filled in for each one' : 'The text' }),
        h('p', { class: 'msg-body', text: text(d.body) }),
      ]) : null,
      facts.length ? h('dl', { class: 'facts' }, facts.map((f) => [h('dt', { text: text(f.label) }), h('dd', { class: text(f.tone) || null, text: text(f.value) })]).flat()) : null,
      d.detail ? h('p', { class: 'card-meta', text: text(d.detail) }) : null,
      // Who is left out, and why: read before the hand moves; a long list sits behind a fold.
      excluded.length ? (excluded.length <= 3
        ? h('div', { class: 'batch-excluded' }, [
          h('p', { class: 'card-note', text: `${excluded.length} excluded` }),
          h('ul', { class: 'batch-list' }, excluded.map((x) => h('li', {}, [h('span', { class: 'batch-item', text: text(x.label) }), h('span', { class: 'batch-why', text: text(x.reason) })]))),
        ])
        : h('details', { class: 'batch-members batch-excluded' }, [
          h('summary', { text: `${excluded.length} excluded · ${excluded.slice(0, 3).map((x) => text(x.label)).join(' · ')} …` }),
          h('ul', { class: 'batch-list' }, excluded.map((x) => h('li', {}, [h('span', { class: 'batch-item', text: text(x.label) }), h('span', { class: 'batch-why', text: text(x.reason) })]))),
        ])) : null,
      // Every member the gesture will touch, one tap away, never hidden behind a count.
      members.length ? h('details', { class: 'batch-members' }, [
        h('summary', { text: `All ${members.length} · ${members.slice(0, 4).join(' · ')}${members.length > 4 ? ' …' : ''}` }),
        h('ul', { class: 'batch-list' }, members.map((m) => h('li', {}, h('span', { class: 'batch-item', text: m })))),
      ]) : null,
      surface,
      blocked ? h('p', { class: 'card-sub action-why', text: text(blocked.reason) }) : null,
      h('p', { class: 'action-meta', text: live ? (num(d.ttl_s) !== null ? `Waits ${Math.round(d.ttl_s)} s · ${footer}` : capitalise(footer)) : '' }),
    ], Object.assign({ className: `tier-${risk} kind-${kind} batch` }, opts));
    node.dataset.proposal = text(d.batch_id);
    node.dataset.set = text(scope.set_id);
    if (live) wireGesture(node, surface, kind, text(d.batch_id), armedAfter, opts, num(d.ttl_s), (left) => `Waits ${left} s · ${footer}`);
    return node;
  }

  function renderBatchResult(d, opts) {
    opts = opts || {};
    const counts = d.counts && typeof d.counts === 'object' ? d.counts : {};
    const n = (k) => (num(counts[k]) === null ? 0 : counts[k]);
    const rows = list(d.rows, 50);
    const all = d.all_verified === true;
    const stat = (label, key) => (n(key) ? h('div', { class: `stat ${key === 'verified' ? 'ok' : 'warn'}` }, [h('div', { class: 'stat-v', text: String(n(key)) }), h('div', { class: 'stat-k', text: label })]) : null);
    const node = card('batch_result', [
      h('div', { class: 'card-head' }, [
        h('div', { class: `mark ${all ? 'ok' : 'warn'}` }, all ? CHECK() : h('span', { text: String(n('verified')) })),
        h('div', {}, [kicker(text(d.summary, all ? 'Done' : 'Done in part')), h('h2', { class: 'card-title', text: text(d.title, 'Done') }), h('p', { class: 'card-sub', text: text(d.detail) })]),
      ]),
      h('div', { class: 'stats counts' }, [stat('applied', 'verified'), stat('excluded', 'excluded'), stat('not applied', 'failed'), stat('changed meanwhile', 'stale'), stat('not confirmed', 'unverified'), stat('not attempted', 'not_attempted')].filter(Boolean)),
      d.note ? h('p', { class: 'card-note bad', text: text(d.note) }) : null,
      rows.length ? h('details', { class: 'batch-members', open: all ? null : '' }, [
        h('summary', { text: `Each of the ${rows.length}` }),
        h('ul', { class: 'batch-list' }, rows.map((r) => h('li', { class: text(r.code) === 'verified' ? 'ok' : (text(r.code) === 'excluded' ? '' : 'bad') }, [h('span', { class: 'batch-item', text: text(r.label) }), h('span', { class: 'batch-why', text: text(r.outcome) })]))),
      ]) : null,
    ], Object.assign({ className: all ? 'success' : 'partial' }, opts));
    // The undo the Mac staged for what was proven: a batch of its own, the same gesture.
    const undo = d.undo && typeof d.undo === 'object' && d.undo.batch_id ? d.undo : null;
    if (!undo && d.batch_id) node.dataset.proposal = text(d.batch_id);
    if (undo) {
      const armedAfter = num(undo.armed_after_ms) === null ? 650 : undo.armed_after_ms;
      const kind = INTERACTIONS.indexOf(text(undo.interaction)) !== -1 ? text(undo.interaction) : 'hold_to_arm';
      const surface = buildSurface(kind, kind === 'tap_commit' ? text(undo.label, 'Undo all') : `${text(undo.label, 'Undo all')} · ${gestureLabel(kind).toLowerCase()}`, 'Undo all', 'arming', true);
      surface.classList.add('quiet');
      node.dataset.proposal = text(undo.batch_id);
      node.appendChild(surface);
      node.appendChild(h('p', { class: 'action-meta', text: num(undo.ttl_s) !== null ? `Undo available for ${Math.round(undo.ttl_s)} s` : '' }));
      wireGesture(node, surface, kind, text(undo.batch_id), armedAfter, opts, num(undo.ttl_s), (left) => (left > 0 ? `Undo available for ${left} s` : 'The undo has expired.'));
    }
    return node;
  }

  // Who is waiting on whom in one thread, in one line: "Waiting since 5h ago · last from
  // Mia · no reply from us". The Mac worked it out from the thread's own labels and stamps
  // (app/families/order_email.py); the page prints the words it was given. Warn-toned while
  // the customer is the one waiting, because that is the only state that asks for a hand.
  function renderReplyState(d, opts) {
    const waiting = text(d.latest_direction) === 'inbound' && d.replied !== true;
    const parts = [];
    if (waiting && text(d.waiting_since)) parts.push(`Waiting since ${text(d.waiting_since)}`);
    else if (text(d.latest_direction) === 'outbound') parts.push(`We replied ${text(d.replied_since, 'already')}`);
    else if (text(d.latest_direction) === 'none') parts.push('No email either way');
    if (text(d.last_from)) parts.push(`last from ${text(d.last_from)}`);
    if (text(d.latest_direction) === 'inbound') parts.push(d.replied === true ? 'answered since' : 'no reply from us');
    const line = text(d.line) || parts.join(' · ');
    const ref = text(d.thread_id);
    const order = text(d.order_number);
    return card('reply_state', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker('Reply state'),
        h('p', { class: `reply-line${waiting ? ' warn' : ''}`, text: line || '—' }),
        h('p', { class: 'card-meta', text: [order ? `about ${order}` : '', text(d.confidence) ? `${text(d.confidence)} link` : ''].filter(Boolean).join(' · ') }),
      ])]),
      strings(d.provenance, 4).length ? h('p', { class: 'link-why', text: strings(d.provenance, 4).join(' · ') }) : null,
      ref ? h('button', { class: 'link-chip', type: 'button', data: { ref, kind: 'email_thread' } }, [h('span', { class: 'link-chip-label', text: 'Open the thread' })]) : null,
    ], opts);
  }

  // ---- which variant the owner means (app/families/order_edit.py). The one card in the
  // vocabulary that is drawn from a read and leads to a change, so its rules are the write
  // boundary's: the rows carry the variant ids the Mac issued and the price it read, the
  // stepper carries a small integer, and Add posts THOSE — never a price, never a total.
  // Everything the change will actually send is built on the Mac from a fresh read after
  // this button is pressed, and the card that comes back still waits for a hold.
  function renderVariantPicker(d, opts) {
    const rows = list(d.candidates, 8);
    const max = num(d.max_quantity) === null ? 20 : Math.max(1, d.max_quantity);
    const orderId = text(d.order_id);
    let chosen = rows.some((r) => text(r.variant_id) === text(d.confident_variant_id)) ? text(d.confident_variant_id) : '';
    let quantity = Math.max(1, Math.min(num(d.quantity) === null ? 1 : d.quantity, max));

    const add = h('button', {
      class: 'variant-add', type: 'button',
      data: { command: 'order_edit.stage', args: '{}' },
    }, [h('span', { class: 'variant-add-label', text: 'Add to order' })]);
    const count = h('span', { class: 'step-value', 'aria-live': 'polite', text: String(quantity) });

    function refresh() {
      // The button's payload, rebuilt whenever the choice or the number changes: three
      // identities and an integer, which is the whole of what the tablet is allowed to say.
      add.dataset.args = JSON.stringify({ order_id: orderId, variant_id: chosen, quantity: quantity });
      add.disabled = !chosen || !orderId;
      add.setAttribute('aria-disabled', add.disabled ? 'true' : 'false');
      if (add.disabled) add.classList.add('is-off'); else add.classList.remove('is-off');
      count.textContent = String(quantity);
    }

    const buttons = rows.map((r) => {
      const ref = text(r.variant_id);
      const options = strings(r.options, 4);
      const sale = r.for_sale !== false;
      const available = num(r.available);
      const row = h('button', {
        class: `variant-row${sale ? '' : ' is-off'}`, type: 'button',
        'aria-pressed': ref && ref === chosen ? 'true' : 'false',
        'aria-disabled': sale ? 'false' : 'true',
        data: { ref: ref, kind: 'variant' },
      }, [
        h('span', { class: 'variant-main' }, [
          h('span', { class: 'variant-title', text: text(r.title, '—') }),
          h('span', { class: 'variant-options', text: options.length ? options.join(' · ') : text(r.variant) }),
        ]),
        h('span', { class: 'variant-side' }, [
          h('span', { class: 'variant-price', text: text(r.price, '—') }),
          sale
            ? (available === null ? null : h('span', { class: 'variant-stock', text: `${available} in stock` }))
            : badge('not for sale', 'bad'),
        ]),
      ]);
      if (sale && ref) {
        row.addEventListener('click', () => {
          chosen = ref;
          for (const other of buttons) other.setAttribute('aria-pressed', other === row ? 'true' : 'false');
          refresh();
        });
      }
      return row;
    });

    function step(by, label) {
      return h('button', { class: 'step-btn', type: 'button', 'aria-label': label }, [h('span', { text: by < 0 ? '−' : '+' })]);
    }
    const down = step(-1, 'One fewer');
    const up = step(1, 'One more');
    down.addEventListener('click', () => { quantity = Math.max(1, quantity - 1); refresh(); });
    up.addEventListener('click', () => { quantity = Math.min(max, quantity + 1); refresh(); });

    // Add has no listener of its own, deliberately. The page does not know what "add" means
    // and must not: the button carries the command's NAME and its own data, and one delegated
    // handler on `#cards` posts them (web/app.js). A disabled button dispatches no click, so
    // "nothing chosen" is enforced by the same flag the eye reads.

    const node = card('variant_picker', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker(text(d.order_number) ? `Add to ${text(d.order_number)}` : 'Add an item'),
        h('h2', { class: 'card-title', text: rows.length === 1 ? 'One match' : `${num(d.count) === null ? rows.length : d.count} to choose from` }),
        h('p', { class: 'card-sub', text: 'Nothing is added until you confirm the card that follows.' }),
      ])]),
      h('div', { class: 'variant-rows', role: 'group', 'aria-label': 'Items' }, buttons),
      d.note ? h('p', { class: 'card-note', text: text(d.note) }) : null,
      h('div', { class: 'variant-foot' }, [
        h('div', { class: 'stepper', role: 'group', 'aria-label': 'How many' }, [down, count, up]),
        add,
      ]),
    ], opts);
    if (orderId) node.dataset.order = orderId;
    refresh();
    return node;
  }

  // ------------------------------------------------------------------ precision input
  //
  // A field the owner types into, for the values a microphone gets wrong: an address, a SKU,
  // a tracking number, a size, a quantity, a code, an amount. One component, so that every
  // family's field behaves the same way and there is one place where a keystroke's route to
  // the Mac is decided.
  //
  // It is CONTROLLED and it is the Mac that controls it. `value`, `status` and `hint` come off
  // the payload; typing posts `compose.field` (web/app.js), the Mac validates the characters
  // into its own copy and answers with the card again, and this draws what came back. Nothing
  // here decides whether a value is good, and nothing here is an argument to a change: the
  // execution arguments are built on the Mac from the Mac's copy when a gesture asks for them.
  //
  // Three statuses, three rings: ok, uncertain (heard rather than typed — look at it),
  // invalid. `uncertain` exists because a mis-heard address is a perfectly valid address
  // belonging to somebody else, and only the owner can tell.
  const FIELD_KINDS = {
    email:    { tag: 'input', type: 'email', inputmode: 'email', autocapitalize: 'none', autocomplete: 'off', spellcheck: 'false' },
    address:  { tag: 'textarea', rows: 3, inputmode: 'text', autocapitalize: 'words', spellcheck: 'false' },
    text:     { tag: 'textarea', rows: 6, inputmode: 'text', autocapitalize: 'sentences' },
    sku:      { tag: 'input', type: 'text', inputmode: 'text', autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false', pattern: '[A-Za-z0-9._-]+' },
    tracking: { tag: 'input', type: 'text', inputmode: 'text', autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false', pattern: '[A-Za-z0-9]+' },
    variant:  { tag: 'input', type: 'text', inputmode: 'text', autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false' },
    quantity: { tag: 'input', type: 'text', inputmode: 'numeric', autocapitalize: 'none', autocomplete: 'off', spellcheck: 'false', pattern: '[0-9]{1,4}' },
    code:     { tag: 'input', type: 'text', inputmode: 'text', autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false', pattern: '[A-Za-z0-9-]+' },
    money:    { tag: 'input', type: 'text', inputmode: 'decimal', autocapitalize: 'none', autocomplete: 'off', spellcheck: 'false', pattern: '[0-9]+([.][0-9]{1,2})?' },
  };
  const FIELD_STATUSES = ['ok', 'uncertain', 'invalid'];

  // ---- what the thumb has typed and the Mac has not answered for yet.
  //
  // D-9 §20: "preserve unsaved content across harmless redraws". A keystroke is posted after
  // 400 ms of quiet (web/app.js) and the Mac answers with the card again — but a card is also
  // redrawn for reasons the owner did not ask for: a background enrichment landing on the
  // order underneath, a sibling card settling, a half-swap. Every one of those draws the
  // field from the Mac's copy, which is one round trip behind the thumb, and each of them
  // used to silently delete the last few characters of an address.
  //
  // So the last typed value is kept here, keyed by card and field, and a render whose
  // incoming value does not match it shows the typed one and says so (`data-unsaved`). The
  // Mac is still the authority: the moment its copy agrees, the draft is dropped, and a
  // value the MAC changed afterwards (a rewrite it did itself) is then shown as it should be.
  // The TTL is the backstop — a draft is unsaved work for the next few seconds, never a
  // shadow copy of the email.
  const FIELD_DRAFT_TTL_MS = 15000;
  const DRAFTS = new Map();
  const nowMs = () => (typeof Date !== 'undefined' && Date.now ? Date.now() : 0);
  const draftKey = (composeId, name) => `${composeId}\u0000${name}`;   // the escape, not the byte: a literal NUL makes grep call this file binary
  // Which field the thumb is in, so a redraw puts the caret back where it was rather than at
  // the end of what was typed.
  let focusedField = '';

  function clearFieldDrafts() { DRAFTS.clear(); focusedField = ''; }
  // For the tests: move every draft back in time, rather than making the clock injectable
  // for one line of arithmetic.
  function ageFieldDrafts(ms) {
    for (const entry of DRAFTS.values()) entry.at -= Number(ms) || 0;
  }

  function fieldDraft(composeId, name) {
    const entry = DRAFTS.get(draftKey(composeId, name));
    if (!entry) return null;
    if (nowMs() - entry.at > FIELD_DRAFT_TTL_MS) { DRAFTS.delete(draftKey(composeId, name)); return null; }
    return entry;
  }

  // A single line of text, whatever the payload said. A field's LABEL and HINT are the Mac's
  // words; its value is the owner's.
  function fieldStatus(value) {
    return FIELD_STATUSES.indexOf(text(value)) !== -1 ? text(value) : 'ok';
  }

  function field(spec, opts) {
    const s = spec && typeof spec === 'object' ? spec : {};
    const settings = opts || {};
    const kind = FIELD_KINDS[text(s.kind)] ? text(s.kind) : 'text';
    const shape = FIELD_KINDS[kind];
    const name = text(s.name);
    const status = fieldStatus(s.status);
    const control = h(shape.tag, {
      class: 'field-input',
      type: shape.tag === 'input' ? shape.type : null,
      rows: shape.tag === 'textarea' ? String(num(s.rows) || shape.rows) : null,
      inputmode: shape.inputmode,
      pattern: shape.pattern || null,
      autocapitalize: shape.autocapitalize,
      autocomplete: shape.autocomplete || null,
      spellcheck: shape.spellcheck || null,
      placeholder: text(s.placeholder) || null,
      maxlength: num(s.maxlength) ? String(num(s.maxlength)) : null,
      'aria-label': text(s.label, name),
      'aria-invalid': status === 'invalid' ? 'true' : 'false',
      // What a keystroke posts: WHICH workspace and WHICH field. Never what to do with it.
      // `post` is the semantic command the Mac put on the card — `compose.field` for an
      // email, `discount.field` for a code being written — so that one component serves
      // every family and the page still does not know what any field MEANS. Absent, the
      // composer's own command is assumed, which is what every existing card sends.
      data: { compose: text(s.compose_id), field: name, kind, post: text(s.post, 'compose.field') },
    });
    // Both, because a textarea's text is its content and an input's is its value, and the
    // page reads `.value` for both. What is shown is the Mac's value — unless the thumb has
    // typed something the Mac has not answered for yet, in which case it is the thumb's, and
    // the field says so.
    const key = draftKey(text(s.compose_id), name);
    const draft = fieldDraft(text(s.compose_id), name);
    const unsaved = Boolean(draft && draft.value !== text(s.value));
    if (draft && !unsaved) DRAFTS.delete(key);          // the Mac has it: it is the authority again
    const shown = unsaved ? draft.value : text(s.value);
    control.value = shown;
    if (shape.tag === 'textarea') control.textContent = shown;
    // The deck holds a delegated click handler that opens a record from any [data-ref], a
    // pointer probe that records gestures, and — in orb mode — a hold surface over the whole
    // stage. A finger landing in a field must reach the field and go no further, or typing an
    // address would open a record or start a recording.
    const swallow = (event) => { if (event && typeof event.stopPropagation === 'function') event.stopPropagation(); };
    for (const type of ['pointerdown', 'pointerup', 'pointercancel', 'click', 'touchstart', 'keydown', 'keyup']) {
      control.addEventListener(type, swallow);
    }
    // Every keystroke into the draft, whether or not anything is listening for it. A field
    // drawn without an `onField` — a card rendered for a snapshot, a card whose handler is
    // delegated on the deck (which is how the app reads these) — still has to keep what was
    // typed across a redraw, so this is not inside the `onField` branch.
    control.addEventListener('input', () => {
      DRAFTS.set(key, {
        value: control.value === undefined ? '' : String(control.value), at: nowMs(),
        start: typeof control.selectionStart === 'number' ? control.selectionStart : null,
      });
      if (typeof settings.onField === 'function') settings.onField(name, control.value, control);
    });
    // Which field the keyboard is in, so a redraw can put it back. And, on the way in, the
    // field is scrolled into the middle of what is left of the screen: an 8-inch tablet's
    // keyboard covers the bottom half, and a Body field at the foot of a composer opened
    // underneath it (§20: "remain visible above the keyboard").
    control.addEventListener('focus', () => {
      focusedField = key;
      if (typeof control.scrollIntoView !== 'function' || typeof setTimeout !== 'function') return;
      setTimeout(() => {
        try { control.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch { /* older engine */ }
      }, 250);
    });
    control.addEventListener('blur', () => { if (focusedField === key) focusedField = ''; });
    // And the other half of it: this render replaced the node the thumb was in, so the
    // keyboard has to be given back to the new one. A macrotask, because the node is not in
    // the document until the caller has appended it.
    if (focusedField === key && typeof control.focus === 'function' && typeof setTimeout === 'function') {
      const at = draft && draft.start !== null ? draft.start : null;
      setTimeout(() => {
        try {
          control.focus({ preventScroll: true });
          if (at !== null && typeof control.setSelectionRange === 'function') control.setSelectionRange(at, at);
        } catch { /* a browser that will not move the caret still has the value */ }
      }, 0);
    }
    const hint = h('p', { class: 'field-hint', text: text(s.hint) });
    hint.hidden = !text(s.hint);
    const wrap = h('label', {
      class: `field field-${kind} is-${status}${unsaved ? ' is-unsaved' : ''}`,
      // `data-typable` is the machine-readable half of the affordance below: a browser check
      // can count the typing paths on a screen, which is how D-9 gets a regression test.
      data: { field: name, status, typable: 'true' },
    }, [
      h('span', { class: 'field-label' }, [
        h('span', { class: 'field-label-text', text: text(s.label, name) }),
        // D-9. The owner asked, out loud, "How do I type a separate hall for you?" — over a
        // build whose fields were real, tappable and completely unannounced. Two words and a
        // keyboard glyph on every label, so the answer is on the screen he was looking at.
        h('span', { class: 'field-type' }, [
          h('span', { class: 'field-type-mark', 'aria-hidden': 'true', text: '⌨' }),
          h('span', { class: 'field-type-word', text: 'Tap to type' }),
        ]),
      ]),
      control,
      hint,
    ]);
    if (unsaved) wrap.dataset.unsaved = 'true';
    return wrap;
  }

  // A value the owner may read and may not change: a reply's recipient, a reply's subject.
  // Drawn like a field so the card reads as one form, and carrying no control at all so
  // there is nothing to tap and no keystroke to refuse. The Mac decides which of its fields
  // are like this (`editable: false`) and refuses a keystroke for them on the wire too
  // (app/families/compose.py), so the card and the command agree.
  function fieldStatic(spec) {
    const s = spec && typeof spec === 'object' ? spec : {};
    const note = text(s.hint);
    return h('div', { class: 'field field-static', data: { field: text(s.name) } }, [
      h('span', { class: 'field-label' }, [h('span', { class: 'field-label-text', text: text(s.label, text(s.name)) })]),
      h('p', { class: 'field-value', text: text(s.value, '—') }),
      note ? h('p', { class: 'field-hint', text: note }) : null,
    ]);
  }

  // An email being written, before anything has been prepared (app/families/compose.py).
  // The one card with editable fields on it. Save draft and Send carry an action id and a
  // mode and nothing else — the words of the email are on the Mac, and the whole point of
  // this card is that they stay there until a gesture asks for them.
  function renderEmailCompose(d, opts) {
    const settings = opts || {};
    const id = text(d.compose_id);
    const reply = text(d.kind) === 'reply';
    const to = d.to && typeof d.to === 'object' ? d.to : {};
    const subject = d.subject && typeof d.subject === 'object' ? d.subject : {};
    const body = d.body && typeof d.body === 'object' ? d.body : {};
    const when = d.resolved_when && typeof d.resolved_when === 'object' ? d.resolved_when : null;
    const meta = [];
    if (when && text(when.date)) meta.push(`${text(when.phrase, 'when')} · ${text(when.date)}`);
    if (reply && text(d.thread_id)) meta.push('in the same thread');
    const buttons = list(d.actions, 5).map((a) => {
      const staged = text(a.mode) === 'stage';
      const mode = text(a.id) === 'send' ? 'send' : 'draft';
      // The command is the Mac's, on the card. The fallback is what this file used to decide
      // for itself, kept so a card built before that seam — or by a family that has not
      // caught up — still stages and still discards.
      const command = text(a.command) || (staged ? 'compose.stage' : 'compose.discard');
      const args = text(a.args) || (staged ? `compose_id=${id}&mode=${mode}` : `compose_id=${id}`);
      return h('button', {
        class: `compose-btn${text(a.risk) === 'red' ? ' risk-red' : ''}${staged ? '' : ' quiet'}`,
        type: 'button',
        // The whole payload of a gesture on this card: which command, and which composer or
        // thread it is about. `data-args` is read by the page's delegated handler
        // (web/app.js); there is no path from here to the body of the email.
        data: { command, args, action: text(a.id) },
      }, [h('span', { class: 'compose-btn-label', text: text(a.label) })]);
    });
    // Which boxes have a keyboard. The Mac says so per field, and says no for a reply's
    // recipient and subject — both belong to the thread and both are re-read there when the
    // change is prepared. A field the Mac fixed is drawn as a fact, not as a dead input:
    // there is then nothing to tap, and nothing for `compose.field` to refuse.
    const typable = (f, fallback) => (f && f.editable !== undefined ? f.editable !== false : fallback);
    const recipient = typable(to, !reply)
      ? field({
        kind: 'email', name: 'to', label: 'To', value: to.value, status: to.status, hint: to.hint,
        compose_id: id, maxlength: 254, placeholder: 'name@example.com',
      }, settings)
      : fieldStatic({
        name: 'to', label: reply ? 'Replying to' : 'To',
        value: [text(d.to_name), text(to.value)].filter(Boolean).join(' · '),
        // The Mac's own line when it has one: who sent the message, when the reply goes to the
        // address it asked for instead (round 13, S2b-01), or that the address is not yet read.
        hint: text(to.hint) || (reply ? 'whoever wrote last in this thread — read from the thread, not typed' : ''),
      });
    const line = typable(subject, true)
      ? field({
        kind: 'text', name: 'subject', label: 'Subject', value: subject.value, status: subject.status,
        hint: subject.hint, compose_id: id, maxlength: 120, rows: 2, placeholder: text(subject.placeholder),
      }, settings)
      : fieldStatic({ name: 'subject', label: 'Subject', value: subject.value, hint: "the thread's own subject" });
    const node = card('email_compose', [
      h('div', { class: 'card-head' }, [
        h('div', {}, [
          kicker(reply ? 'Reply · not sent' : 'New email · not sent'),
          h('h2', { class: 'card-title', text: text(d.about, reply ? 'A reply' : 'An email') }),
          h('p', { class: 'card-meta', text: meta.join(' · ') }),
        ]),
        h('div', { class: 'badges' }, [badge(reply ? 'Reply' : 'New', 'warn')]),
      ]),
      recipient,
      line,
      field({
        kind: 'text', name: 'body', label: 'Body', value: body.value, status: body.status,
        hint: body.hint, compose_id: id, maxlength: 2000, rows: 8, placeholder: text(body.placeholder),
      }, settings),
      // D-9, in the Mac's own words: how to put words in this card. It is above the buttons
      // because that is where the thumb is going next, and it names both ways in — the live
      // session had an owner asking out loud how to type and a system that had no answer.
      text(d.how) ? h('p', { class: 'compose-how', text: text(d.how) }) : null,
      text(d.original) ? h('p', { class: 'compose-said', text: `You said: ${text(d.original)}` }) : null,
      h('div', { class: 'compose-actions', role: 'group', 'aria-label': 'What to do with this email' }, buttons),
      h('p', { class: 'future', text: 'Nothing is saved or sent until you tap.' }),
    ], settings);
    node.dataset.compose = id;
    if (text(d.thread_id)) node.dataset.thread = text(d.thread_id);
    return node;
  }

  // Something being BUILT, before anything has been proposed (app/families/_workspace.py):
  // a discount code, an order made from nothing, a credit on a customer's account. One card
  // for all three, because the Mac sends what is on it — the fields and their kinds, the
  // closed choices, the facts it read, the notes it wants said, and the buttons — and this
  // file only decides how that looks.
  //
  // Everything a finger can do here carries a command NAME and its own arguments, which the
  // delegated handler on `#cards` posts (web/app.js). Nothing here knows what "prepare"
  // means and nothing here may: the values are the Mac's, the arguments of the change are
  // built there when a gesture asks for them, and this card cannot make one.
  function renderWorkspace(d, opts) {
    const settings = opts || {};
    const id = text(d.workspace_id);
    const post = text(d.field_command);
    const facts = list(d.facts, 10);
    const choices = list(d.choices, 4);
    const blocked = text(d.blocked);
    const settled = text(d.settled) === 'created' || text(d.settled) === 'unconfirmed' ? text(d.settled) : '';

    const factRows = facts.length ? h('dl', { class: 'ws-facts' }, facts.map((f) => h('div', { class: `ws-fact${text(f.tone) ? ' tone-' + text(f.tone) : ''}` }, [
      h('dt', { text: text(f.label) }),
      h('dd', { text: text(f.value, '—') }),
    ]))) : null;

    const choiceRows = choices.map((c) => h('div', { class: 'ws-choice', role: 'group', 'aria-label': text(c.label, text(c.name)) }, [
      h('span', { class: 'field-label', text: text(c.label, text(c.name)) }),
      h('div', { class: 'ws-options' }, list(c.options, 6).map((o) => h('button', {
        class: `ws-opt${o.selected === true ? ' is-on' : ''}`,
        type: 'button',
        'aria-pressed': o.selected === true ? 'true' : 'false',
        data: { command: text(d.choose_command, 'workspace.choose'), args: `workspace_id=${id}&field=${text(c.name)}&option=${text(o.id)}` },
      }, [h('span', { text: text(o.label, text(o.id)) })]))),
    ]));

    const inputs = list(d.fields, 8).map((f) => field({
      kind: text(f.kind, 'text'), name: text(f.name), label: text(f.label), value: f.value,
      status: f.status, hint: f.hint, compose_id: id, post, maxlength: num(f.maxlength) || 80,
      rows: num(f.rows) || null, placeholder: text(f.placeholder),
    }, settings));

    // What is ON it (an order's lines) and what is on OFFER for it ("which of these?"): rows the
    // Mac drew, each with at most one button, which names a command and the row it is about —
    // "Remove" posts the line's key, "Add" the variant the Mac offered — and nothing of what
    // either means. A discount and a stock warning are words on the row, never colour alone.
    const wsRow = (r, offered) => {
      const button = r.button && typeof r.button === 'object' && text(r.button.command) ? r.button : null;
      const shade = text(r.tone);
      const meta = [
        text(r.discount) ? h('span', { class: 'ws-row-off', text: text(r.discount) }) : null,
        text(r.stock) ? h('span', { class: `ws-row-stock${shade ? ' tone-' + shade : ''}`, text: text(r.stock) }) : null,
      ].filter(Boolean);
      return h('li', { class: `ws-row${offered ? ' is-offer' : ''}`, data: { key: text(r.key) } }, [
        num(r.number) !== null ? h('span', { class: 'ws-row-no', 'aria-hidden': 'true', text: String(r.number) }) : null,
        h('div', { class: 'ws-row-main' }, [
          h('span', { class: 'ws-row-title', text: text(r.title, '—') }),
          text(r.detail) ? h('span', { class: 'ws-row-detail', text: text(r.detail) }) : null,
          meta.length ? h('span', { class: 'ws-row-meta' }, meta) : null,
        ]),
        h('div', { class: 'ws-row-side' }, [
          h('span', { class: 'ws-row-amount', text: text(r.amount) }),
          text(r.was) ? h('s', { class: 'ws-row-was', text: text(r.was) }) : null,
          text(r.quantity) ? h('span', { class: 'ws-row-qty', text: text(r.quantity) }) : null,
        ]),
        button ? h('button', {
          class: `ws-row-btn${offered ? ' is-add' : ''}`, type: 'button',
          'aria-label': `${text(button.label)} ${text(r.title)} ${text(r.detail)}`.trim(),
          data: { command: text(button.command), args: text(button.args) },
        }, [h('span', { text: text(button.label) })]) : null,
      ]);
    };
    const lineRows = list(d.rows, 20);
    const pickRows = list(d.picks, 8);
    const lines = lineRows.length ? h('ol', { class: 'ws-rows', 'aria-label': 'On it' }, lineRows.map((r) => wsRow(r, false))) : null;
    const picks = pickRows.length ? h('div', { class: 'ws-picks', role: 'group', 'aria-label': text(d.picks_title, 'Which one?') }, [
      h('p', { class: 'ws-picks-title', text: text(d.picks_title, 'Which one?') }),
      h('ul', { class: 'ws-rows' }, pickRows.map((r) => wsRow(r, true))),
    ]) : null;

    const buttons = list(d.actions, 4).map((a) => {
      const button = h('button', {
        class: `compose-btn${text(a.risk) === 'red' ? ' risk-red' : ''}${a.enabled === false ? ' quiet' : ''}`,
        type: 'button',
        data: { command: text(a.command), args: text(a.args), action: text(a.id) },
      }, [h('span', { class: 'compose-btn-label', text: text(a.label) })]);
      // The property, not an attribute: a disabled button dispatches no click, so "this
      // cannot be prepared yet" is enforced by the same flag the eye reads on the card, and
      // the delegated handler in web/app.js reads exactly this.
      button.disabled = a.enabled === false;
      return button;
    });

    const node = card('workspace', [
      h('div', { class: 'card-head' }, [
        h('div', {}, [
          kicker(text(d.kicker, 'Not created yet')),
          h('h2', { class: 'card-title', text: text(d.title, 'Building') }),
          h('p', { class: 'card-sub', text: text(d.subtitle) }),
        ]),
        // Once it has made what it was for, it says so: "Created", or "Not confirmed" when the
        // change left and no answer came back (app/families/_workspace.py `settled`).
        h('div', { class: 'badges' }, [settled === 'created' ? badge(text(d.settled_word, 'Created'), 'ok')
          : settled ? badge(text(d.settled_word, 'Not confirmed'), 'warn') : badge(blocked ? 'Not ready' : 'Draft', blocked ? 'warn' : '')]),
      ]),
      lines,
      picks,
      factRows,
      inputs.length ? h('div', { class: 'ws-fields' }, inputs) : null,
      choiceRows.length ? h('div', { class: 'ws-choices' }, choiceRows) : null,
      blocked ? h('p', { class: 'card-note tone-warn', text: blocked }) : null,
      strings(d.notes, 4).map((n) => h('p', { class: 'card-note', text: n })),
      buttons.length ? h('div', { class: 'compose-actions', role: 'group', 'aria-label': 'What to do with this' }, buttons) : null,
      settled ? null : h('p', { class: 'future', text: 'Nothing is created until you authorise the card that follows.' }),
    ], settings);
    node.dataset.workspace = id;
    return node;
  }

  // ----------------------------------------------------- the composed workspaces (§3, §12)
  //
  // One record, composed. Not another card per read: the Mac folds every read of one record
  // into one canonical entity (app/entities.py) and composes the TASK's surface over it
  // (app/workspace.py), and this draws it.
  //
  // The whole payload is bounded and whitelisted on the Mac before it gets here, and these
  // two functions add nothing to it: every string arrives as textContent, every list is
  // capped again on the way in, and a section is drawn from its own `state` rather than from
  // whether its rows happen to be empty — because "the inbox is empty" and "nobody has looked
  // in the inbox" are different claims and §27 says so.
  //
  // §18 is drawn here as well as decided on the Mac: `data-ref`/`data-kind` — the pair the
  // deck's click handler turns into `open.entity` — go on a row only when the Mac has said
  // `open: true`, which it says only once the ref has passed the gate's shape check and been
  // issued to this conversation. A row it could not open is drawn, and drawn flat, with the
  // reason on it. There is no path here that makes a control out of a ref the Mac withheld.
  const WS_ROWS = 8;
  const WS_FACTS = 8;
  const WS_TONE = { ready: '', empty: 'quiet', unread: 'quiet', loading: 'quiet', error: 'bad' };

  // The header: WHAT IS THIS, WHAT MATTERS, WHAT CAN I DO, in that order and above the tabs
  // (§26). The live session's customer card answered none of the three — it opened on an
  // empty Email panel with a name and two numbers behind it.
  function wsHead(d, kindLabel, lead) {
    // `stat` and `stats counts`, not classes of this card's own: the auto-fit grid the
    // analytic cards already use fits three or four facts at 601 px, and web/style.css's
    // layering belongs to another workstream this pass. (`ws-fact` is taken, and taken by a
    // dl/dt/dd shape that is not this one.)
    const facts = list(d.header, WS_FACTS).map((f) => h('div', { class: 'stat' }, [
      h('div', { class: 'stat-v', text: text(f.value, '—') }),
      h('div', { class: 'stat-k', text: text(f.key) }),
    ]));
    const status = text(d.status);
    return [
      h('div', { class: 'card-head profile' }, [
        lead,
        h('div', {}, [
          kicker(kindLabel),
          h('h2', { class: 'card-title', text: text(d.title, kindLabel) }),
          text(d.subtitle) ? h('p', { class: 'card-sub', text: text(d.subtitle) }) : null,
        ]),
        status ? h('div', { class: 'badges' }, [badge(status)]) : null,
      ]),
      facts.length ? h('div', { class: 'stats counts' }, facts) : null,
      wsAttention(d),
      wsActions(d),
    ];
  }

  // What matters, where it is not a number: the one or two lines the Mac judged worth the
  // owner's attention. Absent where there is nothing — a badge that is always there is
  // furniture, and §12 asks for attention only where it is meaningful.
  function wsAttention(d) {
    const rows = list(d.attention, 3);
    if (!rows.length) return null;
    return h('ul', { class: 'rows compact' }, rows.map((a) => h('li', { class: 'row' }, [
      h('span', { class: 'row-main', text: text(a.title, '—') }),
      text(a.detail) ? h('span', { class: 'row-sub', text: text(a.detail) }) : null,
      h('span', { class: 'row-side' }, [badge(text(a.kind).replace(/_/g, ' '), text(a.level) === 'red' ? 'bad' : 'warn')]),
    ])));
  }

  // WHAT CAN I DO. Every offer is an `open.entity` the Mac has already made good: it named
  // the kind and the ref and issued the ref, so the button cannot be the dead control of D-6.
  // An offer the Mac marked disabled is drawn as disabled with its reason, never as a button.
  function wsActions(d) {
    const offers = list(d.actions, 4);
    if (!offers.length) return null;
    return h('div', { class: 'row-btns', role: 'group', 'aria-label': 'What you can do here' },
      offers.map((a) => {
        const ref = text(a.ref);
        const kind = text(a.kind);
        const live = a.enabled === true && ref && kind;
        /* Two shapes of offer, because the workspace now carries a write as well as its
           doors (§12). `open.entity` is the deck's own vocabulary — `data-ref` + `data-kind`,
           which the delegated click handler turns into an open — and anything else is a
           named command with its arguments, the same `data-command` + `data-args` pair every
           other Mac-built control on the page uses. The Mac decides which; this only draws
           it, and a name the page does not know is refused on the Mac.

           `Email <name>` is the first control of the second shape: the owner asked for "an
           email write box" on a customer card and there was no route to one from a
           workspace at all. */
        const command = text(a.command);
        const opens = !command || command === 'open.entity';
        const args = command === 'compose.to_person' ? `customer_id=${encodeURIComponent(ref)}`
          : text(a.args);
        // Disabled for real, not styled to look it: a control the Mac cannot stand behind
        // must not be pressable at all, and the reason is on the face of it rather than in a
        // tooltip a finger cannot reach.
        return h('button', {
          class: 'btn', type: 'button',
          disabled: live ? null : true,
          'aria-disabled': live ? null : 'true',
          data: live ? (opens ? { ref, kind } : { command, args }) : {},
        }, [
          h('span', { text: text(a.label, 'Open') }),
          live ? null : h('span', { class: 'card-meta', text: ` — ${text(a.reason, 'not available')}` }),
        ]);
      }));
  }

  // One section, from its own state. `ready` draws its facts and its rows; everything else
  // draws the Mac's own note and nothing that could be read as a value.
  function wsSection(sec, rowFn, opts) {
    const state = text(sec.state, 'unread');
    const children = [];
    if (state === 'ready') {
      const facts = kv(list(sec.facts, WS_FACTS).map((f) => [text(f.key), text(f.value)]));
      if (facts) children.push(facts);
      const rows = list(sec.rows, WS_ROWS);
      if (rows.length) children.push(h('ul', { class: 'rows' }, rows.map((r) => rowFn(r, opts))));
      if (sec.truncated === true) children.push(h('p', { class: 'card-note', text: 'More than shown.' }));
    } else {
      children.push(h('p', {
        class: `card-note ws-note is-${state}`,
        text: text(sec.note, state === 'loading' ? 'Reading…' : 'Nothing here.'),
      }));
    }
    return h('div', { class: `ws-sec is-${state}`, data: { section: text(sec.name), state } }, children);
  }

  // The tab bar, built from the sections the Mac composed and in its order. The count and the
  // state ride on the tab, so a tab with nothing behind it looks like one before it is tapped
  // — which is the other half of D-2: the owner should not have to open a panel to find out
  // it is empty.
  function wsPanels(d, rowFns, opts) {
    const out = [];
    const sections = d.sections && typeof d.sections === 'object' && !Array.isArray(d.sections) ? d.sections : {};
    for (const tab of list(d.tabs, 8)) {
      const name = text(tab.name);
      const sec = sections[name];
      if (!name || !sec || typeof sec !== 'object') continue;
      const count = num(sec.count);
      out.push({
        name,
        label: count !== null && count > 0 ? `${text(tab.label, name)} ${count}` : text(tab.label, name),
        node: [wsSection(Object.assign({ name }, sec), rowFns[name] || wsPlainRow, opts)],
      });
    }
    return out;
  }

  // A row the Mac said may be opened carries the pair the deck posts; one it did not carries
  // the reason instead. The two branches are the whole of §18 in the renderer.
  function wsRow(row, kindOfRow, children) {
    const live = row.open === true && text(row.order_id || row.thread_id || row.customer_id);
    const ref = text(row.order_id || row.thread_id || row.customer_id);
    return h('li', {
      class: live ? 'row tappable' : 'row is-closed',
      role: live ? 'button' : null,
      tabindex: live ? '0' : null,
      data: live ? { ref, kind: kindOfRow } : {},
    }, children.concat([
      live ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '›' })
           : (text(row.open_note) ? h('span', { class: 'row-sub', text: text(row.open_note) }) : null),
    ]));
  }

  function wsOrderRow(row) {
    return wsRow(row, 'order', [
      h('span', { class: 'row-main' }, [h('strong', { text: text(row.order_number, 'Order') }), ' ', text(row.items_brief)]),
      h('span', { class: 'row-sub', text: text(row.when) }),
      h('span', { class: 'row-side' }, [h('span', { class: 'amount', text: text(row.total) }), badge(row.fulfilment)]),
    ]);
  }

  function wsThreadRow(row) {
    return wsRow(row, 'email_thread', [
      h('span', { class: 'row-main' }, [h('strong', { text: text(row.subject, '(no subject)') })]),
      h('span', { class: 'row-sub', text: [text(row.from), text(row.snippet)].filter(Boolean).join(' · ') }),
      h('span', { class: 'row-side' }, [
        h('span', { class: 'card-meta', text: text(row.when) }),
        row.needs_reply === true ? badge('Needs reply', 'warn') : null,
      ]),
    ]);
  }

  function wsCustomerRow(row) {
    return wsRow(row, 'customer', [
      h('span', { class: 'row-main' }, [h('strong', { text: text(row.name, '—') })]),
      h('span', { class: 'row-sub', text: text(row.subtitle) }),
    ]);
  }

  // Items and shipments name no record of their own: a line on an order is not somewhere to
  // go, so these are rows and never controls.
  function wsPlainRow(row) {
    return h('li', { class: 'row' }, [
      h('span', { class: 'row-main', text: text(row.title || row.what, '—') }),
      h('span', { class: 'row-sub', text: [text(row.variant), text(row.sku) ? `SKU ${text(row.sku)}` : ''].filter(Boolean).join(' · ') }),
      h('span', { class: 'row-side' }, [
        h('span', { class: 'amount', text: [num(row.quantity) !== null && row.quantity > 1 ? `× ${row.quantity}` : '', text(row.total)].filter(Boolean).join('  ') }),
        text(row.when) ? h('span', { class: 'card-meta', text: text(row.when) }) : null,
        text(row.detail) ? h('span', { class: 'card-meta', text: text(row.detail) }) : null,
      ]),
    ]);
  }

  const WS_CUSTOMER_ROWS = { orders: wsOrderRow, inbox: wsThreadRow };
  const WS_ORDER_ROWS = { email: wsThreadRow, customer: wsCustomerRow };

  // Which tab opens: the Mac's `tab`, which is the tab the TASK implied unless that one has
  // nothing behind it. `opts.tab` — the tab the owner last chose — still wins, because a
  // choice he made outranks one the system inferred; where it names a tab this workspace does
  // not have, `tabs()` falls back to the composed one rather than to whatever is first.
  function wsWhichTab(d, opts) {
    const chosen = opts && opts.tab ? text(opts.tab) : '';
    const sections = d.sections && typeof d.sections === 'object' ? d.sections : {};
    if (chosen && sections[chosen]) return chosen;
    return text(d.tab) || 'overview';
  }

  function renderCustomerWorkspace(d, opts) {
    const settings = opts || {};
    const panels = wsPanels(d, WS_CUSTOMER_ROWS, settings);
    const node = card('customer_workspace', wsHead(d, 'Customer', avatar(d.title, 'lg')).concat([
      tabs(panels, {
        initial: wsWhichTab(d, settings),
        onChange: settings.onTab ? (name, label) => settings.onTab('customer', name, label) : null,
      }),
    ]), settings);
    node.dataset.ref = text(d.ref);
    node.dataset.workspace = 'customer';
    return node;
  }

  function renderOrderWorkspace(d, opts) {
    const settings = opts || {};
    const panels = wsPanels(d, WS_ORDER_ROWS, settings);
    const node = card('order_workspace', wsHead(d, 'Order', null).concat([
      tabs(panels, {
        initial: wsWhichTab(d, settings),
        onChange: settings.onTab ? (name, label) => settings.onTab('order', name, label) : null,
      }),
    ]), settings);
    node.dataset.ref = text(d.ref);
    node.dataset.workspace = 'order';
    holdable(node);
    return node;
  }

  // ---- the compact summary surface (§13; app/summaries.py).
  //
  // D-4: "has anyone bought today that has bought before, a returning customer?" was answered
  // — correctly, with "one" — by drawing SEVEN full customer cards, 265 px each, 1,949 px of
  // deck. A full card is the DRILLDOWN surface; a summary question wants the count and one
  // row each. This is that row.
  //
  // Two things this renderer will not do. It never prints `row.ref`: an id is how the tablet
  // names a record back to the Mac and is not something the owner reads (§26), so it lands in
  // a data attribute and nowhere else. And it offers a tap only where the Mac said the row
  // has somewhere to go — `row.tap`, decided by app/summaries.py `destination_for` against
  // the same rule `open.entity` will apply (§18). D-6 was a control drawn before its
  // destination was known to exist, refused `not_held`, with an empty half underneath it.

  function summaryRow(r) {
    const tap = r.tap === true && Boolean(text(r.ref)) && Boolean(text(r.kind));
    const lines = list(r.lines, 4);
    const tone = ['red', 'amber', 'good'].indexOf(text(r.tone)) === -1 ? '' : text(r.tone);
    return h('li', {
      // The list vocabulary the tablet already has — `.row`, `.row-main`, `.row-sub`,
      // `.row-side`, `.row-go`, `.hist-lines` — so a compact summary row looks and presses
      // exactly like a row on an order list, and this component needs no styling of its own.
      class: `row${tap ? ' tappable' : ''}`,
      role: tap ? 'button' : null,
      tabindex: tap ? '0' : null,
      data: tap ? { ref: text(r.ref), kind: text(r.kind) } : null,
    }, [
      h('span', { class: 'row-main' }, [h('strong', { text: text(r.label, '—') })]),
      text(r.sub) ? h('span', { class: 'row-sub', text: text(r.sub) }) : null,
      lines.length ? h('ul', { class: 'hist-lines' }, lines.map((l) => h('li', {
        class: `hist-line${tone === 'red' ? ' warn' : ''}`,
        text: text(l.label) ? `${text(l.label)}: ${text(l.value, '—')}` : text(l.value, '—'),
      }))) : null,
      h('span', { class: 'row-side' }, [
        text(r.badge) ? badge(r.badge, tone === 'red' ? 'bad' : tone === 'amber' ? 'warn' : tone === 'good' ? 'ok' : 'quiet') : null,
      ]),
      tap ? h('span', { class: 'row-go', 'aria-hidden': 'true', text: '\u203a' }) : null,
    ]);
  }

  function renderSummaryList(d, opts) {
    const rows = list(d.rows, 12);
    const count = num(d.count);
    // The headline the brief asks for: "RETURNING CUSTOMERS TODAY · 1". The count is the
    // WHOLE count even when the rows are capped, which is why it is not rows.length.
    const head = h('div', { class: 'card-head' }, [h('div', {}, [
      kicker(text(d.kicker, text(d.title, 'Summary'))),
      h('h2', { class: 'card-title' }, [
        h('span', { text: text(d.title, 'Summary') }),
        count === null ? null : h('span', { text: ` \u00b7 ${count}` }),
      ]),
      text(d.subtitle) ? h('p', { class: 'card-meta', text: text(d.subtitle) }) : null,
    ])]);
    const node = card('summary_list', [
      head,
      // Nothing found is an ANSWER and gets a card (D-15), in the Mac's own sentence: "no
      // returning customers" and "nothing needs attention" are different sentences, and the
      // second is not "no orders" — there were plenty of orders.
      rows.length ? h('ul', { class: 'rows tight' }, rows.map(summaryRow))
        : h('p', { class: 'card-note', text: text(d.empty_words, `No ${text(d.count_label, 'results')}.`) }),
      d.truncated ? h('p', { class: 'card-note', text: `Showing ${rows.length} of ${count === null ? rows.length : count}.` }) : null,
      text(d.note) ? h('p', { class: 'card-note', text: text(d.note) }) : null,
    ], opts);
    node.dataset.task = text(d.task);
    if (text(d.set_id)) node.dataset.set = text(d.set_id);
    return node;
  }

  // The owner's app as the remote for one of his screens (round 9, app/presentation.py
  // screen_remote). The app opens the remote the moment it draws this card (web/remote.js reads
  // data-remote-screen); the button opens it again later. Only the screen's id and name, and the
  // titles of what it shows, are on it.
  function renderScreenRemote(d, opts) {
    const id = text(d.screen_id);
    const shows = (Array.isArray(d.showing) ? d.showing : []).slice(0, 2).map((t) => text(t)).filter(Boolean);
    const open = h('button', {
      class: 'btn primary remote-open', type: 'button',
      data: /^scr_[0-9a-f]{12}$/.test(id) ? { remoteScreen: id, remoteName: text(d.name, 'Screen') } : null,
      text: 'Open the remote',
    });
    return card('screen_remote', [
      h('div', { class: 'card-head' }, [h('div', {}, [
        kicker('Remote'),
        h('h2', { class: 'card-title', text: text(d.name, 'Screen') }),
        h('p', { class: 'card-sub', text: shows.length ? shows.join(' · ') : 'Showing nothing' }),
      ])]),
      open,
    ], opts);
  }

  // One of the owner's objectives, in the shape of its kind (round 12). Drawn by
  // web/objective-cards.js, which the page loads beside this file; without it nothing is drawn.
  function renderObjective(d, opts) {
    const cards = typeof window !== 'undefined' ? window.CliveObjectiveCards : globalThis.CliveObjectiveCards;
    return cards ? cards.card(d, opts) : null;
  }

  const RENDERERS = {
    assistant: renderAssistant,
    order: renderOrder,
    order_list: renderOrderList,
    customer: renderCustomer,
    customer_list: renderCustomerList,
    customer_workspace: renderCustomerWorkspace,
    order_workspace: renderOrderWorkspace,
    product: renderProduct,
    inventory: renderInventory,
    sales_summary: renderSales,
    email_list: renderEmailList,
    email_thread: renderEmailThread,
    email_draft: renderEmailDraft,
    attention: renderAttention,
    confirmation: renderConfirmation,
    success: renderSuccess,
    error: renderError,
    metric_group: renderMetricGroup,
    ranking: renderRanking,
    table: renderTable,
    comparison: renderComparison,
    variant_matrix: renderVariantMatrix,
    trend: renderTrend,
    working_set: renderWorkingSet,
    batch_action: renderBatchAction,
    capability: renderCapability,
    summary_list: renderSummaryList,
    batch_result: renderBatchResult,
    reply_state: renderReplyState,
    variant_picker: renderVariantPicker,
    email_compose: renderEmailCompose,
    workspace: renderWorkspace,
    workspace_plan: renderWorkspacePlan,
    screen_remote: renderScreenRemote,
    objective: renderObjective,
  };
  const TYPES = Object.keys(RENDERERS).concat(['context_stack']);
  // Both Phase 5 workstreams added to this list and the merge produced two declarations of
  // it: B's composed workspaces and D's compact summary. Every one of them is a surface the
  // owner can navigate back to, so the two lists are unioned rather than chosen between.
  const CONTEXT_TYPES = ['order', 'order_list', 'customer', 'customer_list', 'customer_workspace', 'order_workspace', 'product', 'inventory', 'sales_summary', 'email_list', 'email_thread', 'email_draft', 'attention', 'confirmation', 'success', 'assistant',
    'metric_group', 'ranking', 'table', 'comparison', 'variant_matrix', 'trend', 'working_set', 'batch_action', 'batch_result', 'capability', 'summary_list',
    // The remote's card stays in the deck behind the remote, to open it again (round 9).
    'screen_remote',
    // Something being built — an order, a discount, a credit (app/families/_workspace.py).
    // Round 12: a spoken change to an order returns that order's card and nothing else, and
    // without this the page took a turn whose only card was the workspace for a turn with
    // nothing to show, and went back to the orb — the edit made, the screen gone.
    'workspace',
    // An objective opened, shown or changed by voice is what the owner asked to see (round 12).
    'objective'];

  function isValid(item) {
    return Boolean(item) && typeof item === 'object' && typeof item.type === 'string'
      && TYPES.indexOf(item.type) !== -1 && item.data !== null && typeof item.data === 'object' && !Array.isArray(item.data);
  }

  function renderItem(item, opts) {
    if (!isValid(item) || !RENDERERS[item.type]) return null;
    try {
      // Which tab THIS card's owner is on, resolved before the renderer is called (D-2). It
      // is handed down as `opts.tab` — the name every renderer with tabs already reads — so
      // that value is now about one record instead of the whole branch, and a renderer
      // cannot take a deck-wide tab because there is no longer one to take.
      const settings = opts || {};
      const mine = item.data.shell === true ? '' : ownerTab(item.type, item.data, settings);
      const drawWith = mine ? Object.assign({}, settings, { tab: mine }) : settings;
      // A card the Mac has promised but not yet read: one bounded placeholder, for every
      // type, from the same data shape. The renderer for the type is not called at all —
      // nothing on a skeleton comes from a payload that does not exist yet.
      const node = item.data.shell === true
        ? skeletonCard(item.type, item.data, drawWith)
        : RENDERERS[item.type](item.data, drawWith) || null;
      if (node && node.dataset && !node.dataset.render) node.dataset.render = surfaceId(item);
      return node;
    } catch (error) {
      return null;   // a malformed payload draws nothing; the spoken answer still stands
    }
  }

  // A supporting card, folded away behind its own title (brief section 22). The Mac decides
  // which cards are secondary — the second ranking of a turn, the second list — because it
  // is the one that knows what the answer was about; the tablet decides how that looks. The
  // card itself is untouched and complete: this is disclosure, not truncation, and the header
  // says what is inside so nothing is hidden from the reader.
  function folded(node, label) {
    const wrap = h('article', { class: 'card card-folded', data: { type: 'folded', of: node.dataset ? node.dataset.type || '' : '' } });
    const btn = h('button', { class: 'fold-head', type: 'button', 'aria-expanded': 'false' }, [
      h('span', { class: 'fold-label', text: label || 'More' }),
      h('span', { class: 'fold-mark', text: '+', 'aria-hidden': 'true' }),
    ]);
    const body = h('div', { class: 'fold-body', hidden: true }, [node]);
    btn.addEventListener('click', () => {
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', open ? 'false' : 'true');
      body.hidden = open;
      btn.querySelector('.fold-mark').textContent = open ? '+' : '−';
    });
    append(wrap, [btn, body]);
    return wrap;
  }

  // What a folded card says on its header: its own title where it has one, else its kind.
  const FOLD_WORDS = {
    ranking: 'Another ranking', order_list: 'Another list of orders', email_list: 'More email',
    table: 'Another table', metric_group: 'More numbers', comparison: 'Another comparison', trend: 'Another trend',
  };
  function foldLabel(item) {
    const title = item.data && typeof item.data.title === 'string' ? text(item.data.title) : '';
    return title || FOLD_WORDS[item.type] || 'More';
  }

  // ------------------------------------------------------------------ render identity (§25)
  //
  // Which card is which. The same table as app/render.py KEY_OF, held on both sides because
  // both sides have to agree about it: the Mac names a patch and the tablet has to find the
  // node it is about. `tests/test_progressive.py` reads this table out of this file and
  // compares it with the Mac's, so the two cannot drift.
  const KEY_OF = {
    order: ['order_id', 'order_number'],
    order_list: ['set_id', 'title', 'query'],
    customer: ['customer_id', 'email'],
    customer_list: ['title', 'query'],
    customer_workspace: ['ref'],
    order_workspace: ['ref'],
    product: ['product_id', 'query'],
    inventory: ['query'],
    sales_summary: ['title', 'since'],
    email_list: ['title', 'query'],
    email_thread: ['thread_id'],
    email_draft: ['subject', 'to'],
    attention: ['for'],
    confirmation: ['proposal_id'],
    success: ['proposal_id'],
    batch_action: ['batch_id'],
    batch_result: ['batch_id'],
    error: ['service', 'kind'],
    metric_group: ['title'],
    ranking: ['title', 'mode'],
    table: ['title'],
    comparison: ['title'],
    variant_matrix: ['title'],
    trend: ['title', 'metric'],
    working_set: ['set_id'],
    screen_remote: ['screen_id'],
    objective: ['objective_id'],
    capability: ['build'],
    summary_list: ['task', 'title'],
    reply_state: ['thread_id'],
    variant_picker: ['order_id'],
    email_compose: ['compose_id'],
    workspace: ['workspace_id'],
    workspace_plan: ['workspace_id'],
  };
  const NESTED_KEY_OF = { product: ['products', 'product_id'], inventory: ['products', 'product_id'] };
  const SHELL_SUFFIX = '~shell';

  function surfaceId(item) {
    if (!item || typeof item !== 'object' || typeof item.type !== 'string') return '';
    const kind = item.type;
    const d = item.data && typeof item.data === 'object' ? item.data : {};
    if (d.shell === true) return `${kind}:${SHELL_SUFFIX}`;
    const nested = NESTED_KEY_OF[kind];
    if (nested) {
      const rows = d[nested[0]];
      if (Array.isArray(rows) && rows.length && rows[0] && typeof rows[0] === 'object') {
        const found = text(rows[0][nested[1]]).trim();
        if (found) return `${kind}:${found.slice(0, 120)}`;
      }
    }
    for (const name of KEY_OF[kind] || []) {
      const value = d[name];
      if ((typeof value === 'string' || typeof value === 'number') && String(value).trim()) {
        return `${kind}:${String(value).trim().slice(0, 120)}`;
      }
    }
    return kind;
  }

  // ------------------------------------------------------------------ patching in place (§7)
  //
  // The five rules, each one a test in tests/web/progressive.test.js:
  //
  //   1. the page is not redrawn for an enrichment — only the card named by the patch moves;
  //   2. a control is not moved while a finger is on it — `opts.held()` defers the whole
  //      batch, and it is applied on the next call once the hand is off;
  //   3. keyboard focus survives — the focused field is found again by name on the new node
  //      and its caret is put back where it was;
  //   4. scroll position is not reset — nothing here touches scrollTop, and a replacement
  //      keeps its predecessor's place in the list rather than being appended;
  //   5. no flicker, no duplicate card, no repeated identical render — a replaced node is
  //      swapped in one operation and marked so the CSS does not run the entry animation
  //      again, and the Mac has already suppressed the renders that would change nothing.
  //
  // Returns what was done, in counts, for the telemetry: added, changed, visual, removed,
  // deferred. Nothing here decides WHAT a card says — the patch carries the payload the
  // presentation layer bounded, and it is drawn by the same renderer as always.
  function applyPatches(host, patches, opts) {
    const settings = opts || {};
    const out = { added: 0, changed: 0, visual: 0, removed: 0, deferred: 0, applied: [], nodes: {} };
    if (!host || !Array.isArray(patches) || !patches.length) return out;
    // Rule 2. A hand is on the glass: the whole batch waits. A card that moves under a
    // finger mid-gesture is the defect the live session's owner narrated out loud.
    if (typeof settings.held === 'function' && settings.held()) {
      out.deferred = patches.length;
      return out;
    }
    const focus = captureFocus(host, settings);
    for (const patch of patches) {
      if (!patch || typeof patch !== 'object') continue;
      const id = text(patch.id);
      const op = text(patch.op);
      if (!id) continue;
      const existing = byRender(host, id);
      if (op === 'remove') {
        if (existing && existing.parentNode) { existing.parentNode.removeChild(existing); out.removed += 1; out.applied.push(id); }
        continue;
      }
      const item = patch.item;
      if (!isValid(item)) continue;
      if (op === 'visual' && existing) {
        // Rule 5, the cheap half: the words are the same, so the DOM stays and one attribute
        // moves. This is where "folded", "still reading" and "which tab" land.
        applyVisual(existing, item.data);
        out.visual += 1;
        out.applied.push(id);
        out.nodes[id] = existing;
        continue;
      }
      // Rule 3's sibling, and the other half of D-2: a patch does not move the tab the owner
      // is READING. Whatever the payload would have opened, the card comes back on the tab it
      // was on — the same discipline as the keyboard and the caret below.
      // The card it takes the place of counts as well: one order read under its other key comes
      // as a patch that replaces its own earlier card (app/render.py `same_record`).
      const base = settings.opts || settings.renderOpts || {};
      const standin = text(patch.replaces) ? byRender(host, text(patch.replaces)) : null;
      const target = existing || standin;
      const reading = tabOpenOn(target);
      let node = renderItem(item, reading ? Object.assign({}, base, { tabNow: reading }) : base);
      if (!node) continue;
      node.dataset.render = id;
      if (target && target.parentNode) {
        // Rule 4 and rule 1: the new card takes the old one's PLACE. Nothing above or below
        // it is touched, the scroller keeps its offset, and the page is not rebuilt.
        node.dataset.patched = '1';
        target.parentNode.replaceChild(node, target);
        out[existing || op === 'data' ? 'changed' : 'added'] += 1;
      } else {
        host.appendChild(node);
        out.added += 1;
      }
      out.applied.push(id);
      out.nodes[id] = node;
    }
    restoreFocus(host, focus);
    return out;
  }

  // Which tab a card that is ON THE GLASS is open on. Read from the wrapper `tabs()` marks,
  // so nothing has to be inferred from which panel happens to be visible.
  function tabOpenOn(node) {
    const wrap = node && node.querySelector ? node.querySelector('.tabbed') : null;
    return wrap && wrap.dataset ? text(wrap.dataset.tab) : '';
  }

  // The first card under `host`, in document order, whose render id is `id`. The id is compared,
  // never put into a selector: one built from a title or a subject can hold a quote, a backslash
  // or a bracket, and an unescaped one made querySelectorAll throw and abort the whole batch.
  function byRender(host, id) {
    if (!host || !id) return null;
    const walk = (node) => {
      const kids = node.children || [];
      for (let i = 0; i < kids.length; i++) {
        const kid = kids[i];
        if (kid.dataset && kid.dataset.render === id) return kid;
        const inner = walk(kid);
        if (inner) return inner;
      }
      return null;
    };
    return walk(host);
  }

  // Rule 3. Which field the owner is typing in, by NAME, and where the caret is. A patch that
  // took the keyboard away from an address half-typed would be worse than not patching at
  // all — the live session's precision defect (D-9) with the enrichment layer on top.
  function captureFocus(host, settings) {
    const doc_ = doc();
    const active = settings && settings.activeElement ? settings.activeElement : (doc_ && doc_.activeElement) || null;
    if (!active || !active.dataset || !active.dataset.field) return null;
    const owner = closestCard(active);
    return {
      field: active.dataset.field,
      compose: active.dataset.compose || '',
      render: owner && owner.dataset ? owner.dataset.render || '' : '',
      start: typeof active.selectionStart === 'number' ? active.selectionStart : null,
      end: typeof active.selectionEnd === 'number' ? active.selectionEnd : null,
      value: typeof active.value === 'string' ? active.value : '',
    };
  }

  function closestCard(node) {
    let at = node;
    while (at) {
      if (at.dataset && at.dataset.type) return at;
      at = at.parentNode;
    }
    return null;
  }

  function restoreFocus(host, focus) {
    if (!focus || !focus.field) return;
    const owner = focus.render ? byRender(host, focus.render) : host;
    const scope = owner || host;
    const fields = scope.querySelectorAll ? scope.querySelectorAll(`[data-field="${focus.field}"]`) : [];
    const control = Array.prototype.filter.call(fields, (f) => f.tagName === 'INPUT' || f.tagName === 'TEXTAREA')[0];
    if (!control) return;
    // The characters the owner typed are his, and the Mac's copy of them may be one keystroke
    // behind. What was in the box stays in the box.
    if (focus.value && control.value !== focus.value) control.value = focus.value;
    if (typeof control.focus === 'function') control.focus();
    if (focus.start !== null && typeof control.setSelectionRange === 'function') {
      try { control.setSelectionRange(focus.start, focus.end === null ? focus.start : focus.end); } catch (error) { /* not a text field */ }
    }
  }

  // A visual-state change, applied without rebuilding anything: whether the card is folded,
  // which regions are still being read, and which tab it is open on.
  function applyVisual(node, data) {
    const d = data && typeof data === 'object' ? data : {};
    if (Array.isArray(d.pending)) node.dataset.pending = d.pending.map((x) => text(x)).filter(Boolean).join(' ');
    if (d.secondary === true) node.classList.add('is-secondary'); else node.classList.remove('is-secondary');
    if (d.shell !== true && node.dataset.shell) {
      delete node.dataset.shell;
      node.setAttribute('aria-busy', 'false');
      node.classList.remove('is-shell');
    }
    return node;
  }

  // ------------------------------------------------------------------ what stays on the glass
  //
  // Round 12. George: "a task is asked, a screen is shown, an edit is asked, the edit succeeds,
  // however the screen disappears." The Mac now says when an answer CONTINUES the screen that
  // is up (app/screen.py): the cards it carried over are marked `kept` (the card already on the
  // glass) or `refreshed` (the same record, read again). These three functions are the glass's
  // half of that, and nothing here decides what is on screen — the Mac's list does.

  // Which card a node on the glass is. A folded card is its wrapper on the glass and its card
  // inside it, and it is the card that has an identity.
  function renderIdOf(node) {
    if (!node || !node.dataset) return '';
    if (node.dataset.render) return node.dataset.render;
    if (node.dataset.type !== 'folded') return '';
    // `folded` wraps the card two levels down (the fold's body, then the card).
    for (const kid of node.children || []) {
      for (const inner of [kid].concat(kid.children || [])) {
        if (inner && inner.dataset && inner.dataset.render) return text(inner.dataset.render);
      }
    }
    return '';
  }

  // A card still waiting on the owner's hand — armed, held, being applied. Never redrawn by an
  // answer: its clock and its gesture are the owner's, and only the Mac settles it.
  function liveUnderHand(node) {
    const surface = node && node.querySelector ? node.querySelector('.action-surface') : null;
    if (!surface || !surface.dataset) return false;
    const machine = actionState();
    return machine ? machine.isLive(surface.dataset.state) : true;
  }

  // Draw an answer that continues the screen on `host`, keeping every node it can.
  //
  //   `kept`       the node already there stays exactly as it is: not redrawn, not re-animated,
  //                its tab, its open rows and anything typed into it untouched;
  //   `refreshed`  the same card with the Mac's newer copy, drawn in the old one's place;
  //   anything else already on the glass under the same identity is redrawn in its place too,
  //   except a card waiting on the owner's hand, which is never redrawn under it;
  //   anything new is drawn and comes in as new cards do;
  //   and a card on the glass the answer does not carry is taken away.
  //
  // Returns null — having touched nothing — when the answer is not a continuation, or when a
  // card the Mac says is kept is not on this glass (a reload, a local Back, a half switched):
  // the caller then draws the answer whole, which is what it always did. Otherwise it returns
  // what `render` returns, plus how many were kept, redrawn, added and removed, and `first`,
  // the first new card, so the caller can bring it into view.
  function continueScreen(host, items, opts) {
    if (!host || !Array.isArray(items) || !items.some((i) => i && (i.kept === true || i.refreshed === true))) return null;
    const onGlass = new Map();
    for (const node of Array.prototype.slice.call(host.children || [])) {
      const id = renderIdOf(node);
      if (id && !onGlass.has(id)) onGlass.set(id, node);
    }
    for (const item of items) {
      if (item && item.kept === true && isValid(item) && !onGlass.has(surfaceId(item))) return null;
    }
    const out = { nodes: [], skipped: [], stack: null, errors: [], hasContext: true, kept: 0, redrawn: 0, added: 0, removed: 0, first: null };
    for (const item of items.slice(0, 16)) {
      if (!isValid(item)) { out.skipped.push(item && typeof item.type === 'string' ? item.type : 'invalid'); continue; }
      if (item.type === 'context_stack') { out.stack = list(item.data.entries, 6); continue; }
      if (item.type === 'error') out.errors.push(item.data);
      const id = surfaceId(item);
      const there = onGlass.get(id);
      if (there && (item.kept === true || liveUnderHand(there))) {
        // Moving a node that is already up must not play its entrance again.
        there.dataset.patched = '1';
        out.nodes.push(there);
        out.kept += 1;
        continue;
      }
      let node = renderItem(item, opts);
      if (!node) { out.skipped.push(item.type); continue; }
      if (item.data && item.data.secondary === true) node = folded(node, foldLabel(item));
      if (there) {
        // In the old node's place: swapped now, so the reordering below finds it there.
        node.dataset.patched = '1';
        host.replaceChild(node, there);
        out.redrawn += 1;
      } else {
        out.added += 1;
        if (!out.first) out.first = node;
      }
      out.nodes.push(node);
    }
    // The glass becomes the list: what the answer does not carry goes, and each node takes its
    // place in the Mac's order. A node already in its place is not touched.
    const keep = new Set(out.nodes);
    for (const node of Array.prototype.slice.call(host.children || [])) {
      if (!keep.has(node)) { host.removeChild(node); out.removed += 1; }
    }
    out.nodes.forEach((node, index) => {
      const at = host.children[index] || null;
      if (at !== node) host.insertBefore(node, at);
    });
    return out;
  }

  // Whether the first patches of a NEW turn replace the screen that is up (§7's glass, round
  // 12). The last answer's screen stays until the new turn has something of its own to show:
  // a new record, a new list, a skeleton for something the screen does not already show.
  // Patches that only address cards already up — the same order read again, a skeleton for
  // the kind of card already there — change nothing yet ('hold'): the turn's own answer
  // settles those cards, and an order he is working on does not blink into a skeleton and
  // back while CLIVE thinks. Nor does a card for a change (`CHANGE_TYPES`): the card to tap
  // is ABOUT a screen, and it can reach the glass as a patch a moment before the answer that
  // says where it goes — on top of the record it changes, or as a screen of its own when it
  // changes something else. The context stack rides with it and is never a card at all.
  const CHANGE_TYPES = new Set(['confirmation', 'batch_action', 'success', 'batch_result', 'error', 'email_draft', 'variant_picker']);
  function landingOf(host, patches) {
    const shownTypes = new Set();
    const shownIds = new Set();
    for (const node of Array.prototype.slice.call((host && host.children) || [])) {
      const id = renderIdOf(node);
      if (id) shownIds.add(id);
      if (node.dataset && node.dataset.type && !node.dataset.shell) shownTypes.add(node.dataset.type);
    }
    for (const patch of patches || []) {
      if (!patch || typeof patch !== 'object' || text(patch.op) === 'remove') continue;
      const id = text(patch.id);
      if (!id) continue;
      const type = text(patch.type) || id.split(':')[0];
      if (CHANGE_TYPES.has(type) || type === 'context_stack') continue;
      if (id.endsWith(`:${SHELL_SUFFIX}`)) {
        if (!shownTypes.has(text(patch.type) || id.split(':')[0])) return 'replace';
        continue;
      }
      if (!shownIds.has(id)) return 'replace';
    }
    return 'hold';
  }

  // What the glass does with a turn's answer — as the Mac says, never guessed (round 12, the
  // second pass). Every /turn answer carries `screen` (app/screen.py `state_of`):
  //   'carry'  the Mac kept the screen and sent its cards, marked: drawn onto it (continueScreen);
  //   'keep'   the Mac kept the screen and sent no card of it: the glass stays as it is;
  //   'clear'  the Mac cleared it — words about another order (round 9's D2-05), "close that" —
  //            or there is nothing to show: the orb;
  //   'draw'   a screen of its own.
  // An answer from a Mac that does not say is drawn as answers always were: its cards, or the orb.
  function answerLanding(items, screen, glassUp) {
    const cards = (Array.isArray(items) ? items : []).filter((i) => i && typeof i === 'object' && i.type !== 'context_stack');
    if (screen === 'cleared') return 'clear';
    if (screen === 'kept') {
      if (cards.some((i) => i.kept === true || i.refreshed === true)) return 'carry';
      if (glassUp) return 'keep';
    }
    return cards.length ? 'draw' : 'clear';
  }

  // Whether a control is on the card of the half's cursor (round 12, C3). A listening chip —
  // Add a note, Reply — binds the CURSOR, never the card it is drawn on (web/app.js
  // `primeAction`), so on any other card it must not listen. The Mac takes the family off such
  // a chip and has the card redrawn (app/screen.py `listening_on_cursor`); this is the glass's
  // own check, for a node it kept from before the cursor moved. A control that is not on a
  // record's card has nothing to disagree with; a record's card with no cursor is not his.
  function onCursor(node, entity) {
    let card = node;
    while (card && !(card.dataset && card.dataset.render)) card = card.parentNode;
    if (!card || !text(card.dataset.ref)) return true;
    const here = entity && typeof entity === 'object' ? entity : null;
    if (!here || !text(here.ref)) return false;
    return sameRecord(text(card.dataset.ref), text(here.ref));
  }

  // One record, whether its id came with a query or not ("gid://shopify/Order/1938").
  function sameRecord(a, b) {
    if (a === b) return true;
    const gid = /^gid:\/\/[^/]+\/([^/]+)\/([^/?#]+)/;
    const x = gid.exec(a);
    const y = gid.exec(b);
    return Boolean(x && y && x[1] === y[1] && x[2] === y[2]);
  }

  function render(items, opts) {
    const out = { nodes: [], skipped: [], stack: null, errors: [], hasContext: false };
    const moved = [];
    if (!Array.isArray(items)) return out;
    for (const item of items.slice(0, 16)) {   // more than the vocabulary is long is a bug upstream
      if (!isValid(item)) { out.skipped.push(item && typeof item.type === 'string' ? item.type : 'invalid'); continue; }
      if (item.type === 'context_stack') { out.stack = list(item.data.entries, 6); continue; }
      if (item.type === 'error') out.errors.push(item.data);
      let node = renderItem(item, opts);
      if (!node) { out.skipped.push(item.type); continue; }
      if (item.data && item.data.secondary === true) node = folded(node, foldLabel(item));
      out.nodes.push(node);
      if (CONTEXT_TYPES.indexOf(item.type) !== -1) out.hasContext = true;
      // A proven archive comes with the thread it archived, so the owner lands back on the
      // conversation rather than on a receipt (app/presentation.py:_thread_card). The success
      // card is drawn FIRST, so at the moment it settles the deck that thread does not exist
      // yet — it is settled here instead, once every card in this answer has been built.
      if (item.type === 'success' && (item.data.archived || item.data.restored)) moved.push(item.data);
    }
    for (const fact of moved) for (const node of out.nodes) settleThread(node, fact);
    return out;
  }

  function renderStack(entries, opts) {
    // Chips for the context stack; the active one is pressed. Selection is the app's.
    opts = opts || {};
    return list(entries, 6).map((e) => h('button', {
      class: 'chip', type: 'button', 'aria-pressed': opts.active === e.ref ? 'true' : 'false',
      data: { kind: text(e.kind), ref: text(e.ref) },
      on: { click: () => opts.onSelect && opts.onSelect(e) },
    }, [h('span', { class: 'chip-kind', text: text(e.kind) }), h('span', { class: 'chip-label', text: text(e.label) })]));
  }

  return {
    render, renderItem, renderStack, hydrateOrder, settleOrder, isValid, formatDate,
    TYPES, CONTEXT_TYPES, h, field, fieldStatic, FIELD_KINDS,
    // The progressive workspace's seams: a patch applied to a card already drawn, and the
    // identity a patch addresses it by (web/app.js, tests/web/progressive.test.js).
    applyPatches, surfaceId, KEY_OF,
    // What stays on the glass (round 12): an answer that continues the screen, and whether a
    // new turn's first patches replace it (web/app.js, tests/web/keep.test.js).
    continueScreen, landingOf, renderIdOf, onCursor, answerLanding,
    // The email workspace's own seams: a proven archive applied to the deck on screen, and
    // the unsaved-typing store a redraw must not delete (web/app.js, tests/web/email.test.js).
    settleThread, clearFieldDrafts, ageFieldDrafts, fieldDraft, FIELD_DRAFT_TTL_MS,
  };
});
