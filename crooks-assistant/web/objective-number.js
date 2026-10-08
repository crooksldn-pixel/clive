/* A number to reach, drawn (objectives by touch, part C: "Loopback Hoodie · a number").
 *
 * George, by voice: "Shift the last 200 hoodies by the 18th." The objective keeps what he said (what
 * is counted, the target, since when) and the Mac counts what has sold of it from the shop's orders
 * each time it is drawn (app/objectives/count.py). This file draws that count the way the approved
 * design does, from the card's `number` and `count` (app/objectives/cards.py) and nothing else:
 *
 *   the line    how many have sold of the target, and where the pace takes it ("At this pace: 200 by
 *               Wed 14 Oct, 4 days early"; red, "186 by Sun 18 Oct, 14 short", when it falls short).
 *               The pace is the average a day over the last 14 whole days, as the Mac counts it, and
 *               the same whole-number arithmetic runs here so a dragged target says its own day at
 *               once, and "lands after the deadline" and "short" can never disagree. A number counted
 *               for more than a year sends its latest days only: they are dated from the first day
 *               sent, with what sold before it carried into every total.
 *   the chart   one column a day, the matrix faint so every dot has a place. Total: what has sold so
 *               far, a dot for each ten (more when the target is too big for ten to fit, fewer when it
 *               is small; the line under it says which), today blue, the days ahead at the pace as
 *               rings up to where the pace meets the target, the target a row of light across, the
 *               deadline a column of dots, and what would be short of it red. Per day: what sold each
 *               day, a dot for each one, the days ahead at the pace, and what each day needs from
 *               here to reach the target by the deadline.
 *   the source  "From Shopify, counted 2 min ago. Counting Loopback Hoodie (Grey), Loopback Zip Hoodie.
 *               Each dot is ten hoodies.": what his words matched, by name, since matching by words is
 *               broad, the most sold first. Units are what is still on the orders after returns. Not
 *               counted (the shop could not be read, or the orders are still being read), it says so
 *               in the Mac's own words and draws no chart: nothing is drawn that was not counted.
 *
 * By touch (web/objective-touch.js): a double-tap on the chart switches Total and Per day (a line in
 * the bar that changes nothing); a tap says what that day holds; two fingers pinched on the chart show
 * more or fewer days (the three distances' own arithmetic, web/distances.js `levelOf`: doubling the
 * gap between the fingers halves the days), and a pinch that starts on the chart is the chart's, never
 * the sheet closing (distances.js leaves `.on-chart` alone); the target is dragged up or down a dot at
 * a time with a detent at each, the line and the chart answering before the finger lets go, and let go
 * it is the owner's route (POST /objectives/{id}/target) with Undo in the bar for six seconds. From the
 * keyboard: the target is a slider (arrows a dot, Page keys five, Enter keeps it, Escape puts it back)
 * and Total and Per day are two buttons. The design's homepage suggestion is not drawn: changing the
 * shop needs a hold, and nothing here can act on it.
 *
 * Every word lands through textContent and no attribute is built from what the Mac sent: positions are
 * numbers computed here, class names are this file's own. No dependency on the rest of the page, so it
 * runs under Node against tests/web/dom-shim.js (tests/web/objective-number.test.js).
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveObjectiveNumber = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const W = 540;               // the chart's own units: the width and height it is drawn in
  const H = 232;
  const PLOT_W = W - 78;       // the right-hand strip is the target's handle
  const PACE_DAYS = 14;        // app/objectives/count.py PACE_DAYS: the same pace, worked out here
  const FAR = 366;             // and the same "more than a year away"
  const ROWS_TOTAL = 30;       // at most this many dots up, in total
  const ROWS_DAY = 16;         // and per day
  const MIN_COLS = 7;          // a pinch shows at least a week
  const MAX_COLS = 90;         // and at most three months (the Tab A, half that)
  const STEPS = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000];
  const WORDS = { 1: 'one', 2: 'two', 5: 'five', 10: 'ten', 25: 'twenty-five', 50: 'fifty', 100: 'a hundred' };
  const NS = 'http://www.w3.org/2000/svg';
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const whole = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.floor(v)) : 0);
  const lite = () => {
    try { const html = doc().documentElement; return Boolean(html && html.dataset && html.dataset.lite === '1'); } catch (e) { return false; }
  };
  // "1,250": the Mac says a number this way too (app/objectives/count.py).
  const fmt = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const word = (n) => WORDS[n] || fmt(n);

  // ---------------------------------------------------------------- days

  // A calendar date the Mac sent (YYYY-MM-DD), read as a local date: no time zone moves it.
  function day(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text(value).slice(0, 10));
    if (!m) return null;
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const plus = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const between = (a, b) => Math.round((b - a) / 86400000);
  function said(d, today) {
    const out = `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
    return today && d.getFullYear() !== today.getFullYear() ? `${out} ${d.getFullYear()}` : out;
  }
  const short = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]}`;

  // ---------------------------------------------------------------- the count, and where it goes

  /* The number and its count, from the card: null when there is no number. `counted` only when the
   * Mac counted it; then the days run from the first day sent (index 0: `count.first`, or the day
   * counting began) to today (`today`), and what sold before the first day sent is `carried`, so a
   * number counted for more than a year still totals and dates every day as the Mac does. */
  function model(d) {
    const n = d && d.number && typeof d.number === 'object' ? d.number : null;
    if (!n || !text(n.of)) return null;
    const c = d.count && typeof d.count === 'object' ? d.count : null;
    const target = whole(n.target);
    const since = day(n.since);
    const m = { of: text(n.of), unit: text(n.unit), target, since, deadline: day(d.deadline), count: c, counted: false, asked: Boolean(c) };
    const per = c && c.counted === true && Array.isArray(c.per_day) ? c.per_day.map(whole) : null;
    const start = (c && day(c.first)) || since;
    if (!per || !per.length || !start || target < 1) return m;
    m.counted = true;
    m.start = start;
    m.carried = whole(c.carried);
    let run = m.carried;
    m.perDay = per;
    m.cum = per.map((x) => (run += x));
    m.total = run;
    m.today = per.length - 1;
    m.todayDate = plus(start, m.today);
    const recent = per.slice(0, -1).slice(-PACE_DAYS);
    // The pace as two whole numbers, as the Mac keeps it: units over whole days.
    m.paceSold = recent.reduce((a, b) => a + b, 0);
    m.paceDays = recent.length;
    m.pace = m.paceDays ? m.paceSold / m.paceDays : null;
    m.dIdx = m.deadline ? between(start, m.deadline) : null;
    m.atDeadline = typeof c.at_deadline === 'number' ? whole(c.at_deadline) : null;
    m.reachedOn = day(c.reached_on);
    m.matched = Array.isArray(c.matched) ? c.matched.slice(0, 3).map(text).filter(Boolean) : null;
    m.matchedMore = whole(c.matched_more);
    m.ageS = c && typeof c.age_s === 'number' ? c.age_s : null;
    return m;
  }

  // Whole-number division, exact for any count a shop sells: never a float that lands a hair over.
  function floorDiv(a, b) {
    let q = Math.floor(a / b);
    while (q * b > a) q -= 1;
    while ((q + 1) * b <= a) q += 1;
    return q;
  }
  const ceilDiv = (a, b) => -floorDiv(-a, b);
  // What the pace reaches by day `i` (after today), in whole units, as the Mac works it out.
  const reaches = (m, i) => m.total + floorDiv(m.paceSold * (i - m.today), m.paceDays);

  /* Where a target stands at the pace (app/objectives/count.py `project`, the same whole-number
   * arithmetic): the day it is reached (or was), days early when it lands on or before the deadline,
   * and when it lands after it (or not at all) late, with how many by then and how many short. Late
   * and short are one fact, so "days early" is never negative. Day indexes from the first day sent. */
  function standing(m, t) {
    const out = { t, reached: null, before: false, lands: null, far: false, early: null, by: null, short: null, late: false };
    if (m.total >= t) {
      if (m.carried >= t) {
        // Crossed before the first day sent: the Mac's own day for its target, else said as before it.
        out.reached = t === m.target && m.reachedOn ? between(m.start, m.reachedOn) : null;
        out.before = out.reached === null;
      } else {
        out.reached = m.cum.findIndex((x) => x >= t);
      }
      out.lands = out.reached;
    } else if (m.paceSold) {
      const ahead = ceilDiv((t - m.total) * m.paceDays, m.paceSold);
      if (ahead <= FAR) out.lands = m.today + ahead; else out.far = true;
    }
    if (m.dIdx === null) return out;
    if (out.lands !== null && out.lands <= m.dIdx) { out.early = m.dIdx - out.lands; return out; }
    if (out.reached !== null || out.before) return out;          // reached after its date: reached
    let by;
    if (m.dIdx < m.today) by = m.dIdx >= 0 ? m.cum[m.dIdx] : (m.atDeadline !== null ? m.atDeadline : 0);
    else if (m.pace === null) return out;                       // no whole day yet: nothing to project from
    else by = reaches(m, m.dIdx);
    if (by >= t) return out;                                    // a deadline past a year that the pace still makes
    out.by = by;
    out.short = t - by;
    out.late = true;
    return out;
  }

  // The line under the figure, in the words app/objectives/count.py `pace_words` uses.
  function paceLine(m, t) {
    const s = standing(m, t);
    const at = (i) => said(plus(m.start, i), m.todayDate);
    let words;
    if (s.before) words = `${fmt(t)} reached before ${short(m.start)}`;
    else if (s.reached !== null) words = `${fmt(t)} reached on ${at(s.reached)}`;
    else if (s.short) {
      words = m.dIdx < m.today ? `Was due ${at(m.dIdx)}: ${fmt(s.by)} by then, ${fmt(s.short)} short`
        : `At this pace: ${fmt(s.by)} by ${at(m.dIdx)}, ${fmt(s.short)} short`;
    } else if (s.lands === null) {
      words = s.far ? `At this pace, more than a year to ${fmt(t)}`
        : m.pace === null ? 'No whole day counted yet, so no pace to go by'
        : `Nothing sold in the last ${m.paceDays} days, so no pace to go by`;
    } else {
      words = `At this pace: ${fmt(t)} by ${at(s.lands)}`;
      if (s.early === 0) words += ', on the day';
      else if (s.early !== null && s.early > 0) words += `, ${s.early} day${s.early === 1 ? '' : 's'} early`;
    }
    return { late: s.late, text: words, s };
  }

  // What each day needs from here to reach `t` by the deadline: null without one still to come.
  function need(m, t) {
    if (m.dIdx === null || m.dIdx <= m.today || m.total >= t) return null;
    return (t - m.total) / (m.dIdx - m.today);
  }

  // ---------------------------------------------------------------- the chart, as numbers

  // The smallest step that lets `top` fit in `rows` dots, starting from `from` when it fits.
  function stepFor(top, rows, prefer) {
    if (prefer && Math.ceil(top / prefer) <= rows && Math.ceil(top / prefer) >= rows / 3) return prefer;
    return STEPS.find((s) => Math.ceil(top / s) <= rows) || STEPS[STEPS.length - 1];
  }

  // The days the chart runs to (exclusive): past the deadline and the day the pace lands, by a little.
  function edge(m) {
    const s = standing(m, m.target);
    const ends = [m.today];
    if (m.dIdx !== null) ends.push(m.dIdx);
    if (s.lands !== null) ends.push(s.lands);
    const far = Math.max(...ends);
    // [checker, 8 Oct 2026] Never further than a chart of the most columns can reach with the week
    // before today still in it. This said `today + 120` against at most 90 columns, so a pace landing
    // months after the deadline started the chart a month AFTER today: no day counted, no Today and
    // no deadline on it, and a stray date under it ("4 of 40 sold" drawn as a block of days to come).
    let cap = m.today + Math.min(120, maxCols() - (MIN_COLS - 1));
    // [checker, 8 Oct 2026, review note N3] But a deadline the chart has room for, with today, is
    // on it: the end reaches the deadline's day plus one whenever that is within today + the
    // columns (a deadline 84–87 days out at 90 columns, 39–42 at 45, fell between the two).
    if (m.dIdx !== null && m.dIdx + 1 <= m.today + maxCols()) cap = Math.max(cap, m.dIdx + 1);
    return Math.min(cap, far === m.today ? m.today + 8 : far + 3);
  }
  const maxCols = () => (lite() ? MAX_COLS / 2 : MAX_COLS);
  // The first day a chart ending at `to` may start on: never past a week before today, never before
  // the first day counted, never more than the columns allowed.
  function fromRange(m, to) {
    return { lo: Math.max(0, to - maxCols()), hi: Math.max(0, Math.min(m.today - (MIN_COLS - 1), to - MIN_COLS)) };
  }
  function firstShown(m, to) {
    const r = fromRange(m, to);
    return clamp(m.today - 41, r.lo, Math.max(r.lo, r.hi));
  }

  /* The chart, as circles and lines in its own units, for one view: {mode: 'total' | 'day', from,
   * to, target (the one to draw: the record's, or the one under the finger), scaleTarget (the record's,
   * which sets the scale, so the chart does not rescale under a dragging finger)}. */
  function layout(m, view) {
    const total = view.mode !== 'day';
    const t = view.target;
    const s = standing(m, t);
    const from = view.from;
    const to = view.to;
    const cols = Math.max(1, to - from);
    const col = PLOT_W / cols;
    const x = (i) => (i - from) * col + col / 2;
    const ahead = (i) => (i <= m.today ? m.cum[i] : Math.min(m.pace ? reaches(m, i) : m.total, Math.max(m.total, t)));
    let unit;
    let rows;
    if (total) {
      const top = Math.max(view.scaleTarget, m.total) * 1.5;
      unit = stepFor(top, ROWS_TOTAL, 10);
      rows = Math.max(3, Math.ceil(top / unit));
    } else {
      const shown = m.perDay.slice(Math.max(0, from), m.today + 1);
      const top = Math.max(1, ...shown, m.pace || 0, need(m, view.scaleTarget) || 0) * 1.3;
      unit = stepFor(top, ROWS_DAY, 1);
      rows = Math.max(4, Math.ceil(top / unit));
    }
    const rowH = (H - 14) / rows;
    const yOf = (units) => H - 8 - (units / unit) * rowH;
    const r = clamp(Math.min(col, rowH) * 0.3, 1.1, 3.4);
    const past = [];
    const live = [];
    const dot = (into, i, k, cls, rr) => into.push({ x: x(i), y: H - 8 - (k - 0.5) * rowH, r: rr || r, cls });
    const stack = (into, i, units, cls) => {
      const n = units / unit;
      const full = Math.floor(n + 1e-9);
      for (let k = 1; k <= full; k++) dot(into, i, k, cls);
      if (n - full > 0.25) dot(into, i, full + 1, `${cls} is-part`, r * 0.75);
    };
    for (let i = Math.max(0, from); i < to; i++) {
      if (i <= m.today) {
        stack(past, i, total ? m.cum[i] : m.perDay[i], i === m.today ? 'on-dot is-today' : 'on-dot is-past');
      } else if (total) {
        if (s.lands !== null && i <= s.lands) stack(live, i, ahead(i), 'on-dot is-ahead');
        else if (s.lands === null && m.pace) stack(live, i, ahead(i), 'on-dot is-ahead');
      } else if (m.pace) {
        stack(live, i, m.pace, 'on-dot is-ahead');
      }
    }
    const lines = [];
    const inView = (i) => i !== null && i >= from && i < to;
    if (inView(m.dIdx)) lines.push({ x1: x(m.dIdx), y1: 6, x2: x(m.dIdx), y2: H - 4, cls: `on-line is-deadline${s.late ? ' is-late' : ''}` });
    let targetY = null;
    if (total) {
      targetY = yOf(t);
      lines.push({ x1: 2, y1: targetY, x2: PLOT_W + 4, y2: targetY, cls: `on-line is-target${s.late ? ' is-late' : ''}` });
      if (inView(s.lands)) {
        live.push({ x: x(s.lands), y: targetY, r: 4.6, cls: `on-meet is-ring${s.late ? ' is-late' : ''}` });
        live.push({ x: x(s.lands), y: targetY, r: 2, cls: `on-meet${s.late ? ' is-late' : ''}` });
      }
      if (s.late && inView(m.dIdx) && m.dIdx >= m.today) {
        for (let u = Math.ceil(s.by / unit); u < t / unit; u++) live.push({ x: x(m.dIdx), y: H - 8 - (u + 0.5) * rowH, r, cls: 'on-dot is-short' });
      }
    } else {
      const each = need(m, t);
      if (each !== null && to > m.today + 1) {
        const y = yOf(each);
        lines.push({ x1: Math.max(0, x(m.today + 1) - col / 2), y1: y, x2: PLOT_W + 4, y2: y, cls: 'on-line is-need' });
      }
    }
    const labels = [];
    const label = (i, words, cls) => { if (inView(i)) labels.push({ x: (x(i) / W) * 100, text: words, cls }); };
    const near = (a, b, d) => a !== null && b !== null && Math.abs(x(a) - x(b)) < d;
    if (!near(from, m.today, 70) && !near(from, m.dIdx, 70)) label(from, short(plus(m.start, from)), 'is-from');
    if (!near(m.today, m.dIdx, 56)) label(m.today, 'Today', 'is-today');
    if (m.dIdx !== null) label(m.dIdx, short(m.deadline), s.late ? 'is-deadline is-late' : 'is-deadline');
    return {
      W, H, cols, col, from, to, unit, rows, rowH, r, past, live, lines, labels, targetY, s,
      matrix: { x: 0, y: H - 8 - rows * rowH, w: cols * col, h: rows * rowH, col, rowH, r: r * 0.55 },
      // The range a target can be dragged over, a dot at a time: one dot to the top of the chart.
      min: unit, max: rows * unit,
    };
  }

  // ---------------------------------------------------------------- words for the rows and the bar

  /* The home row's line for a number (web/objective-cards.js `row`): where it stands, from the
   * summary's `number` (app/routes/objectives.py adds the count to it). Late first, as the design
   * orders it; then where the pace takes it; uncounted, the Mac's own reason. */
  function rowWords(o, now) {
    const n = o && o.number && typeof o.number === 'object' ? o.number : null;
    if (!n || !text(n.of)) return null;
    const today = now instanceof Date ? new Date(now.getFullYear(), now.getMonth(), now.getDate()) : null;
    const target = whole(n.target);
    if (n.counted !== true) return { sub: text(n.why) || `Counting ${text(n.of)}`, late: false, meta: null };
    const sold = whole(n.sold);
    const meta = `${fmt(sold)} of ${fmt(target)}`;
    const deadline = day(o.deadline);
    if (n.reached_on && day(n.reached_on)) return { sub: `${fmt(target)} reached on ${said(day(n.reached_on), today)}`, late: false, meta };
    if (n.late && deadline) {
      const gone = today && between(today, deadline) < 0;
      return { sub: gone ? `Was due ${said(deadline, today)}: ${fmt(whole(n.by_deadline))} by then, ${fmt(whole(n.short))} short`
        : `${fmt(whole(n.by_deadline))} by ${said(deadline, today)}, ${fmt(whole(n.short))} short`, late: true, meta };
    }
    if (n.lands && day(n.lands)) return { sub: `On pace for ${fmt(target)} by ${said(day(n.lands), today)}`, late: false, meta };
    return { sub: n.far ? `More than a year to ${fmt(target)} at this pace` : 'No pace to go by yet', late: false, meta };
  }

  function ago(seconds) {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '';
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
    return `${Math.round(seconds / 3600)} h ago`;
  }
  // What his words matched, by name, since matching by words is broad: "Loopback Hoodie" is also in
  // "Loopback Zip Hoodie". Nothing said for a card that did not carry it.
  function counting(m) {
    if (!m.matched) return '';
    if (!m.matched.length) return ` Nothing has matched “${m.of}” yet.`;
    return ` Counting ${m.matched.join(', ')}${m.matchedMore ? ` and ${fmt(m.matchedMore)} more` : ''}.`;
  }
  function caption(m, L, total) {
    if (total) return `Each dot is ${word(L.unit)} ${L.unit === 1 ? 'sold' : m.unit || 'sold'}.`;
    return `Each dot is ${word(L.unit)} sold that day.`;
  }

  // ---------------------------------------------------------------- drawing

  function h(tag, cls, words) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (words !== undefined && words !== null) node.textContent = text(words);
    return node;
  }
  function svg(tag, attrs) {
    const node = doc().createElementNS(NS, tag);
    for (const k of Object.keys(attrs || {})) node.setAttribute(k, String(attrs[k]));
    return node;
  }
  const n2 = (v) => Number(v).toFixed(2);
  let patterns = 0;

  function paint(group, items) {
    while (group.childNodes.length) group.removeChild(group.childNodes[0]);
    for (const c of items) group.appendChild(svg('circle', { cx: n2(c.x), cy: n2(c.y), r: n2(c.r), class: c.cls }));
  }
  function paintLines(group, lines) {
    for (const l of lines) group.appendChild(svg('line', { x1: n2(l.x1), y1: n2(l.y1), x2: n2(l.x2), y2: n2(l.y2), class: l.cls }));
  }

  /* The Number shape for one card: `kit` is what web/objective-cards.js lends it when the drawing can
   * change the objective ({T, bar, now, tap, commit(tail, body), failed(error), load()}), or null for a
   * drawing that only shows. Returns the section. */
  function shape(d, kit) {
    const m = model(d);
    if (!m) return null;
    const wrap = h('section', 'oc-shape on-number');
    if (!m.counted) return uncounted(wrap, m, kit);
    const now = m.todayDate;
    const to = edge(m);
    const V = { mode: 'total', from: firstShown(m, to), to, target: m.target, scaleTarget: m.target, held: false };

    const sold = h('span', 'on-sold', fmt(m.total));
    const of = h('span', 'on-of');
    const seg = h('div', 'on-seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'Show');
    const modeButton = (label, mode) => {
      const b = h('button', 'on-mode', label);
      b.type = 'button';
      b.addEventListener('click', () => setMode(mode, true));
      seg.appendChild(b);
      return b;
    };
    const totalB = modeButton('Total', 'total');
    const dayB = modeButton('Per day', 'day');
    const pace = h('p', 'on-pace');
    const head = h('div', 'on-head');
    for (const el of [sold, of, seg]) head.appendChild(el);

    const chart = h('div', 'on-chart');
    const box = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'on-svg', 'aria-hidden': 'true', focusable: 'false' });
    const defs = svg('defs');
    patterns += 1;
    const pid = `on-m-${patterns}`;
    const pattern = svg('pattern', { id: pid, patternUnits: 'userSpaceOnUse' });
    const cell = svg('circle', { class: 'on-cell' });
    pattern.appendChild(cell);
    defs.appendChild(pattern);
    const matrix = svg('rect', { class: 'on-matrix', fill: `url(#${pid})` });
    const pastG = svg('g', { class: 'on-past' });
    const liveG = svg('g', { class: 'on-live' });
    for (const el of [defs, matrix, pastG, liveG]) box.appendChild(el);
    chart.appendChild(box);
    const handle = h('button', 'on-target');
    handle.type = 'button';
    const pill = h('span', 'on-pill');
    handle.appendChild(pill);
    chart.appendChild(handle);
    const labels = h('div', 'on-labels');
    labels.setAttribute('aria-hidden', 'true');
    const source = h('p', 'on-source');
    source.appendChild(h('i', 'on-src-dot'));
    const sourceWords = h('span', null);
    source.appendChild(sourceWords);

    let L = null;
    // The whole chart, for the view as it is now (a mode, a span of days, a scale).
    function drawAll() {
      L = layout(m, V);
      const mx = L.matrix;
      pattern.setAttribute('x', n2(0));
      pattern.setAttribute('y', n2(mx.y));
      pattern.setAttribute('width', n2(mx.col));
      pattern.setAttribute('height', n2(mx.rowH));
      cell.setAttribute('cx', n2(mx.col / 2));
      cell.setAttribute('cy', n2(mx.rowH / 2));
      cell.setAttribute('r', n2(mx.r));
      matrix.setAttribute('x', n2(mx.x));
      matrix.setAttribute('y', n2(mx.y));
      matrix.setAttribute('width', n2(mx.w));
      matrix.setAttribute('height', n2(mx.h));
      paint(pastG, L.past);
      drawLive();
      while (labels.childNodes.length) labels.removeChild(labels.childNodes[0]);
      for (const l of L.labels) {
        const el = h('span', `on-label ${l.cls}`, l.text);
        el.style.setProperty('--x', n2(l.x));
        labels.appendChild(el);
      }
      const totalOn = V.mode === 'total';
      totalB.classList.toggle('is-on', totalOn);
      dayB.classList.toggle('is-on', !totalOn);
      totalB.setAttribute('aria-pressed', totalOn ? 'true' : 'false');
      dayB.setAttribute('aria-pressed', totalOn ? 'false' : 'true');
      handle.hidden = !totalOn;
      chart.classList.toggle('is-day', !totalOn);
      const when = ago(m.ageS);
      sourceWords.textContent = `From Shopify${when ? `, counted ${when}` : ''}.${counting(m)} ${caption(m, L, totalOn)}`;
    }
    // What depends on the target: the days ahead, the target's row, where the pace meets it, the
    // line under the figure and the handle. Drawn again at each step a drag passes.
    function drawLive() {
      const fresh = layout(m, V);
      L.live = fresh.live;
      L.lines = fresh.lines;
      L.s = fresh.s;
      L.targetY = fresh.targetY;
      paint(liveG, fresh.live);
      paintLines(liveG, fresh.lines);
      const p = paceLine(m, V.target);
      of.textContent = `of ${fmt(V.target)} sold`;
      pace.textContent = p.text;
      pace.classList.toggle('is-late', p.late);
      pill.textContent = `Target ${fmt(V.target)}`;
      handle.classList.toggle('is-late', p.late);
      handle.classList.toggle('is-moving', V.held);
      if (fresh.targetY !== null) handle.style.setProperty('--y', n2((fresh.targetY / H) * 100));
      handle.setAttribute('aria-valuemin', String(L.min));
      handle.setAttribute('aria-valuemax', String(L.max));
      handle.setAttribute('aria-valuenow', String(V.target));
      handle.setAttribute('aria-valuetext', `Target ${fmt(V.target)}. ${p.text}`);
    }

    handle.setAttribute('role', 'slider');
    handle.setAttribute('aria-label', 'Target');
    handle.setAttribute('aria-orientation', 'vertical');
    drawAll();

    const parts = [head, pace, chart, labels, source];
    if (kit) {
      parts.push(h('p', 'oc-sr', 'Double-tap the chart for per day, or use Total and Per day. Pinch it for more or fewer days. The target is a slider: Enter keeps it.'));
      const el = { chart, box, handle, drawAll, drawLive, layoutNow: () => L, toggle: () => setMode(V.mode === 'total' ? 'day' : 'total', true) };
      chartTouch(m, V, kit, el);
      targetTouch(m, V, kit, el);
    } else {
      handle.disabled = true;
    }
    for (const el of parts) wrap.appendChild(el);
    return wrap;

    // A switch of view changes nothing on the record: it is said in the bar and leaves an Undo alone.
    function setMode(mode, sayIt) {
      if (V.mode === mode && !sayIt) return;
      const was = V.mode;
      V.mode = mode;
      drawAll();
      if (!kit) return;
      if (was !== mode) kit.T.haptic('snap');
      if (sayIt) kit.bar.say(modeWords());
    }
    function modeWords() {
      if (V.mode === 'total') return `In total: ${fmt(m.total)} of ${fmt(V.target)} sold.`;
      const each = need(m, V.target);
      const rate = m.pace === null ? 'No whole day counted yet.' : `${m.pace.toFixed(1)} a day over the last ${m.paceDays} day${m.paceDays === 1 ? '' : 's'}.`;
      return each === null ? `Per day: ${rate}` : `Per day: ${rate} ${each.toFixed(1)} a day gets you to ${fmt(V.target)} by ${said(m.deadline, now)}.`;
    }
  }

  // Not counted: what he set, and why there is no count, in the Mac's words. No chart is drawn.
  function uncounted(wrap, m, kit) {
    wrap.classList.add('is-uncounted');
    const what = `${m.target ? `${fmt(m.target)} ` : ''}${m.of}${m.since ? `, counted from ${short(m.since)}` : ''}`;
    wrap.appendChild(h('p', 'on-what', what));
    const why = h('p', 'on-source is-unread');
    why.appendChild(h('i', 'on-src-dot'));
    const words = h('span', null);
    why.appendChild(words);
    wrap.appendChild(why);
    if (m.asked) { words.textContent = text(m.count && m.count.why) || 'It could not be counted.'; return wrap; }
    // The model's card carries no count (its tools never read the shop): the owner's own route does.
    if (!kit || typeof kit.load !== 'function') { words.textContent = 'Counted from Shopify where the objective is opened.'; return wrap; }
    words.textContent = 'Counting from Shopify…';
    Promise.resolve().then(() => kit.load()).catch((error) => {
      words.textContent = `It could not be counted: ${text(error && error.message) || 'CLIVE did not answer'}.`;
    });
    return wrap;
  }

  // ---------------------------------------------------------------- touch: the chart

  const pinchLevel = (scale) => {
    const D = root.CliveDistances;
    return D && typeof D.levelOf === 'function' ? D.levelOf(0, scale) : Math.log2(Math.max(0.05, scale > 0 ? scale : 1));
  };

  /* A tap says what that day holds; a double-tap switches Total and Per day; two fingers on the chart
   * show more or fewer days. A pinch's own lift is not also a tap. */
  function chartTouch(m, V, k, el) {
    const { chart, box } = el;
    chart.classList.add('on-live');
    const fingers = new Map();
    let pinch = null;
    let swallowUntil = 0;
    const dayAt = (x) => {
      const r = rectOf(box);
      const L = el.layoutNow();
      if (!r || !r.width) return null;
      const u = ((x - r.left) / r.width) * W;
      return clamp(Math.floor(u / L.col) + L.from, L.from, L.to - 1);
    };
    chart.addEventListener('click', (event) => {
      // The handle's own click (a drag's end, or the keyboard) is the target's, not a day's.
      if (k.T.clock.now() < swallowUntil || within(event.target, el.handle)) return;
      const i = dayAt(Number(event.clientX));
      k.tap('number-chart', 'chart', {
        waits: true,
        single: () => { if (i !== null) k.bar.say(aboutDay(m, i)); },
        double: () => el.toggle(),
      });
    });
    const spread = () => {
      const [a, b] = Array.from(fingers.values());
      return Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
    };
    chart.addEventListener('pointerdown', (event) => {
      fingers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (fingers.size !== 2 || pinch) return;
      pinch = { d0: spread(), days0: V.to - V.from, shown: V.from };
      chart.classList.add('is-pinching');
      k.T.haptic('lift');
    });
    chart.addEventListener('pointermove', (event) => {
      const f = fingers.get(event.pointerId);
      if (!f) return;
      f.x = event.clientX; f.y = event.clientY;
      if (!pinch || fingers.size < 2) return;
      const level = pinchLevel(spread() / pinch.d0);
      const r = fromRange(m, V.to);
      const from = clamp(Math.round(V.to - pinch.days0 / Math.pow(2, level)), r.lo, Math.max(r.lo, r.hi));
      if (from === V.from) return;
      V.from = from;
      k.T.haptic('detent');
      el.drawAll();
    });
    const lift = (event) => {
      if (!fingers.delete(event.pointerId) || !pinch) return;
      const was = pinch;
      pinch = null;
      fingers.clear();
      chart.classList.remove('is-pinching');
      swallowUntil = k.T.clock.now() + 450;
      if (V.from === was.shown) return;
      k.bar.say(V.from === 0 && !m.carried ? `Since ${short(m.start)}: everything it has sold.`
        : `From ${short(plus(m.start, V.from))}: the last ${m.today - V.from + 1} days, and the rest of the run.`);
    };
    chart.addEventListener('pointerup', lift);
    chart.addEventListener('pointercancel', lift);
  }

  // What the record holds about one day, said when it is tapped.
  function aboutDay(m, i) {
    const when = said(plus(m.start, i), m.todayDate);
    if (i <= m.today) return `${when}: ${fmt(m.perDay[i])} sold, ${fmt(m.cum[i])} by then.`;
    if (!m.pace) return `${when}: no pace to say what it reaches by then.`;
    return `${when}: about ${fmt(reaches(m, i))} by then, at ${m.pace.toFixed(1)} a day.`;
  }

  // ---------------------------------------------------------------- touch: the target

  /* The target, dragged up or down a dot at a time from where it was, never jumping to the finger;
   * the line and the chart answer at each detent, and what would fall short turns red before the
   * finger lets go. Let go on another target and the Mac is asked; the same, or lost, and nothing
   * changes. From the keyboard: a slider. */
  function targetTouch(m, V, k, el) {
    const { handle, box } = el;
    let busy = false;
    let from = V.target;
    // The target the record holds, as this drawing last heard it: from the record it was drawn from,
    // then from each answer the Mac gives, whether or not that answer is drawn (an Undo sent since
    // makes it not the latest, and Escape must not then put back a target the Mac no longer has).
    let kept = m.target;
    const show = (t, held) => {
      const before = paceLine(m, V.target).late;
      V.target = t;
      V.held = held;
      el.drawLive();
      return before !== paceLine(m, t).late;
    };
    const keep = (t) => {
      if (t === kept) { show(kept, false); return; }
      show(t, false);
      busy = true;
      k.commit('/target', { target: t })
        .then((record) => {
          const held = record && ((record.number && record.number.target) || (record.card && record.card.number && record.card.number.target));
          if (held) kept = whole(held);
          show(held ? kept : (record && record.card ? V.target : kept), false);
        })
        .catch((error) => { show(kept, false); k.failed(error); })
        .then(() => { busy = false; });
    };
    const step = () => el.layoutNow().min;
    const bounded = (t) => clamp(t, el.layoutNow().min, el.layoutNow().max);
    let moving = false;
    k.T.press(handle, {
      arm: 0,
      start: () => { if (busy || V.mode !== 'total') return; moving = true; from = V.target; k.T.haptic('lift'); show(V.target, true); },
      move: (p) => {
        if (!moving) return;
        const r = rectOf(box);
        const L = el.layoutNow();
        const perPx = r && r.height ? (H / r.height) / L.rowH * L.unit : L.unit / L.rowH;
        const t = bounded(Math.round((from - (p.y - p.y0) * perPx) / step()) * step());
        if (t === V.target) return;
        k.T.haptic(show(t, true) ? 'snap' : 'detent');
      },
      end: () => { if (!moving) return; moving = false; keep(V.target); },
      cancel: () => { if (!moving) return; moving = false; show(kept, false); },
    });
    handle.addEventListener('keydown', (event) => {
      const by = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 5, PageDown: -5 }[event.key];
      const to = by !== undefined ? V.target + by * step() : event.key === 'Home' ? el.layoutNow().min : event.key === 'End' ? el.layoutNow().max : null;
      if (to !== null) { event.preventDefault(); if (!busy) show(bounded(to), true); return; }
      if (event.key === 'Enter') { event.preventDefault(); if (!busy) keep(V.target); return; }
      if (event.key === 'Escape' && V.target !== kept && !busy) { event.preventDefault(); show(kept, false); }
    });
    handle.addEventListener('blur', () => { if (!busy && !moving && V.target !== kept) show(kept, false); });
  }

  function within(node, ancestor) {
    for (let n = node; n; n = n.parentNode) if (n === ancestor) return true;
    return false;
  }
  function rectOf(node) {
    try {
      const r = node && typeof node.getBoundingClientRect === 'function' ? node.getBoundingClientRect() : null;
      return r && Number.isFinite(r.left) && Number.isFinite(r.top) ? r : null;
    } catch (e) { return null; }
  }

  return { W, H, PACE_DAYS, model, standing, paceLine, need, layout, edge, firstShown, fromRange, rowWords, aboutDay, shape, fmt };
});
