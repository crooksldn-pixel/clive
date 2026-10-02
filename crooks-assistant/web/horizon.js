/* The next six weeks, and each objective's mark in dots (objectives by touch, part B).
 *
 * The design George approved ("Home · pinch between three distances") has the home at the middle
 * of three distances: pinch out and the home becomes the next six weeks, one dot a day from
 * today, every live objective a row with its own days drawn on that line; spread into a row and
 * it becomes that one objective. This file is the far distance and the mark every row carries.
 * web/distances.js moves between the three.
 *
 *   the horizon   one dot a day for 42 days, today first and ringed. Each objective's row marks
 *                 its deadline with a ring and each stage's date with a larger dot: done blue, the
 *                 one it is at blue and breathing, the ones to come white. What will land late is
 *                 red, and said in words under the row: the deadline already gone, a stage past
 *                 its own date, or a stage due after the deadline (with the days it overruns).
 *                 A change to CLIVE (a build) has no date, so no days are drawn for it, only what
 *                 it waits on; any other objective with no date says so rather than having days
 *                 invented for it. Late rows come first, then by date, then builds, then undated.
 *   the mark      what an objective is, in dots, where every dot is something real: a project a
 *                 little road, one cluster a stage, lit as far as it has come; tasks a ring a
 *                 person with a dot inside for each task, lit when done (CLIVE's own ring blue);
 *                 a build the same road in steel through Filed, Built, Reviewed, Live, from what
 *                 the build loop says of it. The plain stage track a project's row already carries
 *                 (web/objective-cards.js) is drawn as dots too: a run a stage, red from the stage
 *                 that would land late.
 *
 * Everything is drawn from GET /objectives as it arrives (app/objectives/store.py `summary()`),
 * and the build loop's words (GET /objectives/builds): nothing is guessed, no row or day is made
 * up. Every word lands through textContent; no attribute is built from what the Mac sent (only
 * numbers this file computes and its own class names), and an objective's id goes on a row only
 * when it has an objective id's own shape. On the Tab A (html[data-lite]) the marks draw fewer
 * dots: one a stage, no road between; each day is still a dot, since each is a day.
 *
 * No dependency on the rest of the page, so the layout and the drawing run under Node against
 * tests/web/dom-shim.js (tests/web/horizon.test.js).
 */
(function (root, factory) {
  const api = factory();
  root.CliveHorizon = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const SPAN = 42;                         // days drawn, today first
  const NS = 'http://www.w3.org/2000/svg';
  const OBJECTIVE_ID = /^obj_[0-9a-f]{8}$/;
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const COUNT = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v, n) => (Array.isArray(v) ? v.slice(0, n).filter((x) => x && typeof x === 'object') : []);
  const strings = (v) => (Array.isArray(v) ? v.map(text).filter(Boolean) : []);
  const word = (n) => (n >= 0 && n < COUNT.length ? COUNT[n] : String(n));
  const lite = () => {
    try { const html = doc().documentElement; return Boolean(html && html.dataset && html.dataset.lite === '1'); } catch (e) { return false; }
  };

  // ---------------------------------------------------------------- days, in words

  // A calendar date the Mac sent (YYYY-MM-DD), read as a local date: no time zone moves it.
  function day(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text(value).slice(0, 10));
    if (!m) return null;
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function midnight(now) {
    const n = now instanceof Date ? now : new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }
  function plus(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
  // Whole days from `from` to `to`; rounded, so a clock change between them moves nothing.
  function between(from, to) { return Math.round((to - from) / 86400000); }
  function said(d, today) {
    const out = `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
    return today && d.getFullYear() !== today.getFullYear() ? `${out} ${d.getFullYear()}` : out;
  }
  // "Fri 2 Oct to Thu 12 Nov": the span, the way the design heads it.
  function range(today) {
    const from = midnight(today);
    return `${said(from)} to ${said(plus(from, SPAN - 1), from)}`;
  }

  // ---------------------------------------------------------------- what is late

  /* Lateness first, as the design orders it: before a question, before where it is. Late is the
   * deadline already gone with work still open, a stage still to finish past its own date, or a
   * stage due after the deadline. `from` is the first stage that is late, for the dots. */
  function lateness(o, now) {
    const none = { late: false, why: null, from: null, by: null };
    if (!o || typeof o !== 'object' || o.attention === 'done' || o.attention === 'dropped') return none;
    const today = midnight(now);
    const deadline = day(o.deadline);
    const stages = list(o.stages, 12);
    const open = (s) => s.state !== 'done';
    const firstOpen = stages.findIndex(open);
    // Every stage done is finished work, whatever the date said.
    const reached = counted(o) && day(counted(o).reached_on);
    if (deadline && between(today, deadline) < 0 && (!stages.length || firstOpen >= 0) && !reached) {
      return { late: true, why: `Was due ${said(deadline, today)}`, from: firstOpen >= 0 ? firstOpen : null, by: 'deadline' };
    }
    const overdue = stages.findIndex((s) => open(s) && day(s.due) && between(today, day(s.due)) < 0);
    if (overdue >= 0) {
      return { late: true, why: `${text(stages[overdue].name)} was due ${said(day(stages[overdue].due), today)}`, from: overdue, by: 'stage' };
    }
    if (deadline) {
      const after = stages.findIndex((s) => open(s) && day(s.due) && day(s.due) > deadline);
      if (after >= 0) return { late: true, why: `${text(stages[after].name)} would land after ${said(deadline, today)}`, from: after, by: 'stage' };
    }
    // A number the pace leaves short of its deadline, as the Mac counted it.
    const n = counted(o);
    if (n && n.late && deadline) {
      return { late: true, why: `${whole(n.by_deadline)} by ${said(deadline, today)}, ${whole(n.short)} short`, from: null, by: 'number' };
    }
    return none;
  }

  // ---------------------------------------------------------------- a number, as the Mac counted it

  const whole = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.floor(v)) : 0);
  // The summary's number, only when it was counted (app/routes/objectives.py adds the count).
  function counted(o) {
    const n = o && o.number && typeof o.number === 'object' ? o.number : null;
    return n && n.counted === true && whole(n.target) > 0 ? n : null;
  }
  // The day the pace reaches the target, if it has one (or the day it was reached).
  function landDay(o) {
    const n = counted(o);
    return n ? day(n.reached_on) || day(n.lands) : null;
  }
  // A ring of twenty, each a twentieth of the target, lit for the share sold.
  function ring(sold, target, late) {
    const out = [];
    const lit = Math.round(Math.max(0, Math.min(1, sold / target)) * 20);
    for (let i = 0; i < 20; i++) {
      const a = -Math.PI / 2 + i / 20 * Math.PI * 2;
      out.push({ x: 20 + Math.cos(a) * 15, y: 20 + Math.sin(a) * 15, r: 1.75, cls: i < lit ? `is-lit${late ? ' is-late' : ''}` : 'is-dim' });
    }
    out.push({ x: 20, y: 20, r: 2.2, cls: `is-now${late ? ' is-late' : ''}` });
    return out;
  }

  // ---------------------------------------------------------------- a build, as stages

  // The build loop's own word for where a request is (GET /objectives/builds), as the road's
  // stages. Blocked, or waiting on the owner, says nothing about which stage it reached: no road.
  const BUILD_STAGES = ['Filed', 'Built', 'Reviewed', 'Live'];
  const BUILD_AT = { queued: 0, building: 1, 'in review': 2, done: 3 };
  function buildAt(o, rows) {
    if (!o || o.kind !== 'build' || !list(o.engineering, 10).length) return null;
    const last = list(rows, 50).slice(-1)[0];
    if (!last) return 0;                      // filed, and the loop has not said more yet
    return Object.prototype.hasOwnProperty.call(BUILD_AT, text(last.progress)) ? BUILD_AT[text(last.progress)] : null;
  }
  const BUILD_WAIT = {
    queued: 'Waiting for a builder', building: 'Being built', 'in review': 'Waiting on the review',
    done: 'Built · waiting on you to merge it', blocked: 'The build is blocked', 'needs the owner': 'Waiting on you',
  };
  // What it waits on, from the record: the owner, a blocker, the build loop, or a stage's party.
  function waitsOn(o, rows) {
    if (strings(o.needs_you).length) return 'Waiting on you';
    const blocked = strings(o.blocked_by);
    if (blocked.length) return `Waiting on ${blocked[0]}`;
    if (o.kind === 'build') {
      const last = list(rows, 50).slice(-1)[0];
      if (last) return BUILD_WAIT[text(last.progress)] || text(last.progress);
      return list(o.engineering, 10).length ? 'Waiting for a builder' : 'Not filed with the builders yet';
    }
    const at = o.stage && typeof o.stage === 'object' ? o.stage : null;
    return at && text(at.waiting_on) ? `Waiting on ${text(at.waiting_on)}` : null;
  }

  // ---------------------------------------------------------------- the mark, as dots

  /* Each dot: {x, y, r, cls} in a 40×40 box. `cls` is one of this file's own class names, so the
   * stylesheet colours it: is-lit (done, blue), is-now (where it is: blue, breathing), is-dim (to
   * come), is-steel (CLIVE's own engineering), is-clive (CLIVE's ring), is-ring (a person). */
  function road(n, now, opts) {
    const o = opts || {};
    const out = [];
    if (n < 1) return out;
    const pts = [];
    for (let i = 0; i < n; i++) { const t = n === 1 ? 0.5 : i / (n - 1); pts.push([6.5 + t * 27, 33 - t * 26]); }
    const steel = o.steel ? ' is-steel' : '';
    const lit = (i) => (i < now || (now === n) ? 'is-lit' : i === now ? 'is-now' : 'is-dim') + steel;
    // Clusters only while they have room and the device has the dots to spare.
    const clusters = !o.lite && n <= 5;
    if (clusters) {
      for (let i = 0; i < n - 1; i++) {
        out.push({ x: (pts[i][0] + pts[i + 1][0]) / 2, y: (pts[i][1] + pts[i + 1][1]) / 2, r: 0.95, cls: (i < now ? 'is-lit' : 'is-dim') + steel });
      }
    }
    pts.forEach((c, i) => {
      if (!clusters) { out.push({ x: c[0], y: c[1], r: n > 7 ? 2 : 2.9, cls: lit(i) }); return; }
      for (let k = 0; k < 6; k++) {
        const a = k / 6 * Math.PI * 2 + Math.PI / 6;
        out.push({ x: c[0] + Math.cos(a) * 3, y: c[1] + Math.sin(a) * 3, r: 1.15, cls: lit(i) });
      }
      out.push({ x: c[0], y: c[1], r: 1.15, cls: lit(i) });
    });
    return out;
  }

  // Where each person's ring sits, for one to four people.
  const SPOTS = {
    1: [[20, 20, 12]],
    2: [[11, 20, 8.5], [29, 20, 8.5]],
    3: [[20, 10.5, 8], [10.5, 28.5, 8], [29.5, 28.5, 8]],
    4: [[11, 11, 7.5], [29, 11, 7.5], [11, 29, 7.5], [29, 29, 7.5]],
  };
  const MAX_TASK_DOTS = 7;     // a dot a task, as many as a ring holds
  function people(groups, opts) {
    const o = opts || {};
    const who = list(groups, 4);
    const spots = SPOTS[who.length] || [];
    const out = [];
    who.forEach((g, gi) => {
      const [cx, cy, rr] = spots[gi];
      const clive = text(g.who).trim().toLowerCase() === 'clive';
      const ringDots = o.lite ? 6 : 9;
      for (let k = 0; k < ringDots; k++) {
        const a = k / ringDots * Math.PI * 2;
        out.push({ x: cx + Math.cos(a) * rr, y: cy + Math.sin(a) * rr, r: o.lite ? 1.1 : 0.8, cls: clive ? 'is-ring is-clive' : 'is-ring' });
      }
      const done = Math.max(0, Number(g.done) || 0);
      const open = Math.max(0, Number(g.open) || 0);
      const n = Math.min(MAX_TASK_DOTS, done + open);
      const lit = Math.min(done, n);
      const r = n <= 3 ? Math.min(1.9, rr / 4.2) : Math.min(1.3, rr / 6);
      for (let i = 0; i < n; i++) {
        let x = cx; let y = cy;
        if (n > 1 && n <= 3) x = cx + (i - (n - 1) / 2) * Math.min(5, rr * 0.62);
        else if (n > 3 && i > 0) { const a = (i - 1) / (n - 1) * Math.PI * 2 - Math.PI / 2; x = cx + Math.cos(a) * rr * 0.46; y = cy + Math.sin(a) * rr * 0.46; }
        out.push({ x, y, r, cls: i < lit ? 'is-lit' : clive ? 'is-now is-clive' : 'is-dim' });
      }
    });
    return out;
  }

  // The dots for one objective's mark, or null for a kind whose mark is its row's own.
  function markDots(o, rows, opts) {
    if (!o || typeof o !== 'object') return null;
    const o2 = Object.assign({ lite: lite() }, opts || {});
    if (o.kind === 'project' && list(o.stages, 12).length) {
      const stages = list(o.stages, 12);
      let now = stages.findIndex((s) => s.state === 'current');
      if (now < 0) now = stages.every((s) => s.state === 'done') ? stages.length : -1;
      return road(stages.length, now, o2);
    }
    if (o.kind === 'tasks' && list(o.people_tasks, 4).length) return people(list(o.people_tasks, 4), o2);
    if (o.kind === 'build') {
      const at = buildAt(o, rows);
      if (at !== null) return road(BUILD_STAGES.length, at, Object.assign({}, o2, { steel: true }));
    }
    // Any other objective with a number counted: its ring.
    const n = counted(o);
    return n ? ring(whole(n.sold), whole(n.target), Boolean(n.late)) : null;
  }

  // ---------------------------------------------------------------- drawing

  function svg(tag, attrs) {
    const node = doc().createElementNS(NS, tag);
    for (const k of Object.keys(attrs || {})) node.setAttribute(k, String(attrs[k]));
    return node;
  }
  function el(tag, cls, words) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (words !== undefined && words !== null && words !== '') node.textContent = text(words);
    return node;
  }
  const n2 = (v) => Number(v).toFixed(2);

  function glyph(o, rows, size, opts) {
    const dots = markDots(o, rows, opts);
    if (!dots || !dots.length) return null;
    const box = svg('svg', { viewBox: '0 0 40 40', width: size, height: size, 'aria-hidden': 'true', class: 'hz-glyph', focusable: 'false' });
    for (const d of dots) box.appendChild(svg('circle', { cx: n2(d.x), cy: n2(d.y), r: n2(d.r), class: `hz-g ${d.cls}` }));
    return box;
  }

  /* The project's own stage track (web/objective-cards.js `row`), drawn as dots: each segment
   * keeps its element and its class, and carries a run of dots, red from the late stage on. */
  function paintTrack(track, lateFrom, opts) {
    if (!track || !track.childNodes) return track;
    const segs = track.childNodes.filter ? track.childNodes.filter((c) => c.nodeType === 1) : Array.prototype.slice.call(track.children || []);
    const n = segs.length;
    const per = (opts && opts.lite) || lite() ? 4 : n <= 4 ? 8 : n <= 6 ? 5 : 3;
    segs.forEach((seg, i) => {
      if (lateFrom !== null && lateFrom !== undefined && i >= lateFrom) seg.setAttribute('data-late', 'true');
      const run = svg('svg', { class: 'hz-run', 'aria-hidden': 'true', focusable: 'false' });
      for (let k = 0; k < per; k++) {
        const x = per === 1 ? 50 : 4 + k * (92 / (per - 1));
        run.appendChild(svg('circle', { cx: `${n2(x)}%`, cy: 5, r: 1.6, class: k === 0 ? 'hz-t is-first' : 'hz-t' }));
      }
      seg.appendChild(run);
    });
    return track;
  }

  // A build's road under its row: four runs, Filed to Live, in steel.
  function buildTrack(at, opts) {
    const bar = el('span', 'hz-track is-steel');
    bar.setAttribute('aria-hidden', 'true');
    BUILD_STAGES.forEach((_, i) => {
      const seg = el('i', `hz-seg ${i < at ? 'is-done' : i === at ? 'is-current' : 'is-upcoming'}`);
      bar.appendChild(seg);
    });
    return paintTrack(bar, null, opts);
  }

  /* What web/alpha.js asks for each home row: its mark (or null, and the row keeps its own
   * tile), the lateness line that comes first under its title, and what to draw under that.
   * `track` is the stage track the row already has, painted as dots in place. A deadline already
   * gone is said first on the row by the home itself ("past the date", before anything else), so
   * the line here is a stage's lateness, or a number's shortfall, which the home has no other way
   * to say. */
  function rowMark(o, rows, track, opts) {
    const now = opts && opts.now ? opts.now : new Date();
    const late = lateness(o, now);
    if (track && o && o.kind === 'project') paintTrack(track, late.from, opts);
    const at = buildAt(o, rows);
    return {
      glyph: glyph(o, rows, 40, opts),
      late: late.by === 'stage' || late.by === 'number' ? late.why : null,
      under: at !== null && !track ? buildTrack(at, opts) : null,
    };
  }

  // ---------------------------------------------------------------- the horizon, laid out

  const X0 = 1.2;                           // per cent of the row's width: the first day
  const STEP = 97.6 / (SPAN - 1);           // and the step to the next, so the last sits at 98.8
  const at = (d) => X0 + d * STEP;

  /* One objective's days: [{d, x, r, cls, ring}] in order, each a day of the 42. A stage still
   * open is late on its own day when the deadline is already gone or its date is after it. */
  function daysOf(o, late, today) {
    const deadline = day(o.deadline);
    const dIdx = deadline ? between(today, deadline) : null;
    const gone = dIdx !== null && dIdx < 0 && late.late;
    const stages = list(o.stages, 12);
    const marks = new Map();               // day index -> the stage marked there
    const rank = { 'is-late': 4, 'is-now': 3, 'is-next': 2, 'is-done': 1 };
    let overrunTo = null;
    stages.forEach((s) => {
      const due = day(s.due);
      if (!due) return;
      const d = between(today, due);
      const open = s.state !== 'done';
      const isLate = open && (gone || (dIdx !== null && d > dIdx));
      if (isLate && d >= 0) overrunTo = overrunTo === null ? d : Math.max(overrunTo, d);
      if (d < 0 || d >= SPAN) return;
      const state = !open ? 'is-done' : isLate ? 'is-late' : s.state === 'current' ? 'is-now' : 'is-next';
      const was = marks.get(d);
      if (!was || rank[state] > rank[was]) marks.set(d, state);
    });
    // A number: the day the pace reaches its target. Short of the deadline, the days from the
    // deadline to that day are an overrun like a late stage's.
    const land = landDay(o);
    const lIdx = land ? between(today, land) : null;
    const n = counted(o);
    if (n && n.late && lIdx !== null && lIdx >= 0) overrunTo = overrunTo === null ? lIdx : Math.max(overrunTo, lIdx);
    // The overrun: the days from the deadline to the last stage still due after it, or, with the
    // deadline already gone, from today to that stage. Days past a deadline with nothing due are
    // quiet, not red: nothing is known to land on them.
    const overrunFrom = gone ? 0 : dIdx !== null ? dIdx + 1 : null;
    const out = [];
    for (let d = 0; d < SPAN; d++) {
      const monday = plus(today, d).getDay() === 1;
      const lateDay = overrunFrom !== null && overrunTo !== null && d >= overrunFrom && d <= overrunTo;
      let cls = 'hz-d';
      if (marks.has(d)) cls = `hz-m ${marks.get(d)}`;
      else if (lateDay) cls = 'hz-d is-late';
      else if (lIdx !== null && d > 0 && d < lIdx && (dIdx === null || d <= dIdx)) cls = 'hz-d is-pace';
      else if (dIdx !== null && d > dIdx) cls = 'hz-d is-beyond';
      else if (monday) cls = 'hz-d is-monday';
      const r = marks.has(d) ? 3 : monday ? 1.5 : 1.2;
      const ring = d === 0 ? (late.late ? 'hz-today is-late' : 'hz-today') : d === dIdx ? (late.late ? 'hz-ring is-late' : 'hz-ring') : null;
      out.push({ d, x: at(d), r, cls, ring });
    }
    // The deadline on today itself is ringed as the deadline, inside today's ring.
    if (dIdx === 0) out[0].ring2 = late.late ? 'hz-ring is-late' : 'hz-ring';
    // The day the pace lands, ringed: inside the deadline's ring when it is the same day.
    if (lIdx !== null && lIdx >= 0 && lIdx < SPAN) {
      const lands = `hz-ring is-land${n && n.late ? ' is-late' : ''}`;
      if (out[lIdx].ring) out[lIdx].ring2 = lands; else out[lIdx].ring = lands;
    }
    return out;
  }

  // The first date that matters for the order: the deadline, or the next stage still to come.
  function keyDate(o, today) {
    const deadline = day(o.deadline);
    const next = list(o.stages, 12).filter((s) => s.state !== 'done').map((s) => day(s.due)).filter((d) => d && between(today, d) >= 0)
      .sort((a, b) => a - b)[0] || null;
    if (deadline && next) return next < deadline ? next : deadline;
    return deadline || next || landDay(o);
  }
  function dated(o) {
    return Boolean(day(o.deadline) || list(o.stages, 12).some((s) => day(s.due)) || landDay(o));
  }

  /* The horizon as data, from the home's own list. `opts`: {now, needs: [ids], builds: {id: rows}}. */
  function layout(objectives, opts) {
    const o2 = opts || {};
    const today = midnight(o2.now);
    const builds = o2.builds && typeof o2.builds === 'object' ? o2.builds : {};
    const needs = new Set(Array.isArray(o2.needs) ? o2.needs : []);
    const live = list(objectives, 200).filter((o) => o.attention !== 'done' && o.attention !== 'dropped');
    const rows = live.map((o, i) => {
      const rowsOf = builds[o.id] || [];
      const late = lateness(o, today);
      const build = o.kind === 'build';
      const hasDays = !build && dated(o);
      const deadline = day(o.deadline);
      const key = hasDays ? keyDate(o, today) : null;
      let detail = 'No date';
      const land = landDay(o);
      if (!build && deadline) detail = `Due ${said(deadline, today)}`;
      else if (land && !list(o.stages, 12).some((s) => day(s.due))) detail = `Lands ${said(land, today)}`;
      else if (hasDays) {
        const next = list(o.stages, 12).find((s) => s.state !== 'done' && day(s.due) && between(today, day(s.due)) >= 0);
        detail = next ? `${text(next.name)} ${said(day(next.due), today)}` : 'No date ahead';
      }
      // A number on pace says where it lands, beside its deadline.
      const n = counted(o);
      const paced = n && !late.late && land && deadline ? (n.reached_on ? `Reached ${said(land, today)}` : `Lands ${said(land, today)}`) : null;
      return {
        id: text(o.id), title: text(o.title), kind: text(o.kind), order: i,
        late: late.late, detail, line: late.why || paced || (hasDays ? null : waitsOn(o, rowsOf)),
        days: hasDays ? daysOf(o, late, today) : [],
        build, key, source: o, builds: rowsOf,
        group: late.late ? 0 : hasDays ? 1 : build ? 2 : 3,
      };
    });
    rows.sort((a, b) => a.group - b.group
      || ((a.key ? a.key.getTime() : Infinity) - (b.key ? b.key.getTime() : Infinity))
      || a.order - b.order);

    const weeks = [];
    for (let d = 0; d < SPAN; d++) {
      const x = plus(today, d);
      if (x.getDay() === 1) weeks.push({ d, x: at(d), text: x.getDate() <= 7 ? `${x.getDate()} ${MONTHS[x.getMonth()]}` : String(x.getDate()) });
    }

    // The line under the heading: what needs him, then what is heading late, else what lands last.
    const lateN = rows.filter((r) => r.late).length;
    const needN = live.filter((o) => needs.has(o.id)).length;
    const parts = [];
    if (needN) parts.push(needN === 1 ? 'One thing needs you.' : `${word(needN)} things need you.`);
    if (lateN) parts.push(lateN === 1 ? 'One is heading late.' : `${word(lateN)} are heading late.`);
    else {
      const inSpan = (r) => { const d = day(r.source.deadline); return Boolean(d) && between(today, d) >= 0 && between(today, d) < SPAN; };
      const last = rows.filter((r) => !r.build && inSpan(r))
        .sort((a, b) => day(b.source.deadline) - day(a.source.deadline))[0];
      if (last) parts.push(`${last.title} lands last, ${said(day(last.source.deadline), today)}.`);
      else if (live.length) parts.push('Nothing is due in the next six weeks.');
    }
    const summary = live.length ? parts.join(' ') : 'Nothing ongoing.';
    return { today, range: range(today), weeks, rows, summary, span: SPAN };
  }

  // ---------------------------------------------------------------- the horizon, drawn

  /* Draw the model into `host` (the horizon's section), replacing what was there. `on.open(id,
   * rowElement)` is a tap on a row; `on.home()` the way back without a gesture. */
  function draw(host, model, on) {
    const handlers = on || {};
    while (host.childNodes.length) host.removeChild(host.childNodes[0]);
    const back = el('button', 'hz-home');
    back.type = 'button';
    back.setAttribute('data-hz', 'home');
    const chev = svg('svg', { viewBox: '0 0 24 24', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false', class: 'hz-chev' });
    chev.appendChild(svg('path', { d: 'm15 6-6 6 6 6' }));
    back.appendChild(chev);
    back.appendChild(el('span', null, 'Home'));
    if (typeof handlers.home === 'function') back.addEventListener('click', () => handlers.home());

    const hello = el('div', 'hz-hello');
    hello.appendChild(el('p', 'hz-range', model.range));
    hello.appendChild(el('h1', 'hz-h1', 'Next six weeks'));
    hello.appendChild(el('p', 'hz-summary', model.summary));
    const head = el('div', 'hz-head');
    head.appendChild(hello);
    head.appendChild(back);
    host.appendChild(head);

    if (model.rows.length) {
      // The weeks: each Monday by its date, the first of a month with the month's name.
      const weeks = svg('svg', { class: 'hz-weeks', 'aria-hidden': 'true', focusable: 'false' });
      for (const w of model.weeks) {
        const t = svg('text', { x: `${n2(w.x)}%`, y: 13, class: 'hz-week' });
        t.textContent = w.text;
        weeks.appendChild(t);
      }
      host.appendChild(weeks);
    }

    const rows = el('div', 'hz-rows');
    for (const r of model.rows) {
      const row = el('button', `hz-row${r.late ? ' is-late' : ''}${r.days.length ? '' : ' is-undated'}`);
      row.type = 'button';
      row.setAttribute('data-hz', 'row');
      if (OBJECTIVE_ID.test(r.id)) row.setAttribute('data-objective', r.id);
      const top = el('span', 'hz-row-head');
      const mark = glyph(r.source, r.builds, 28);
      top.appendChild(mark || el('span', 'hz-glyph is-empty'));
      top.appendChild(el('span', 'hz-title', r.title));
      top.appendChild(el('span', `hz-detail${r.late ? ' is-late' : ''}`, r.detail));
      row.appendChild(top);
      if (r.days.length) {
        const strip = svg('svg', { class: 'hz-days', 'aria-hidden': 'true', focusable: 'false' });
        for (const d of r.days) {
          strip.appendChild(svg('circle', { cx: `${n2(d.x)}%`, cy: 11, r: n2(d.r), class: d.cls }));
          if (d.ring) strip.appendChild(svg('circle', { cx: `${n2(d.x)}%`, cy: 11, r: d.ring.startsWith('hz-today') ? 5.5 : 6.5, class: d.ring }));
          if (d.ring2) strip.appendChild(svg('circle', { cx: `${n2(d.x)}%`, cy: 11, r: 8.5, class: d.ring2 }));
        }
        row.appendChild(strip);
      }
      if (r.line) row.appendChild(el('span', `hz-line${r.late ? ' is-late' : ''}`, r.line));
      if (typeof handlers.open === 'function' && r.id) row.addEventListener('click', () => handlers.open(r.id, row));
      rows.appendChild(row);
    }
    host.appendChild(rows);
    return host;
  }

  return {
    SPAN, BUILD_STAGES,
    day, said, range, between, midnight,
    lateness, buildAt, waitsOn, markDots, road, people, ring,
    glyph, paintTrack, rowMark, layout, draw,
  };
});
