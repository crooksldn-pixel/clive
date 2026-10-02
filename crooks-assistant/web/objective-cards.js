/* An objective, drawn in the shape of what it is for (round 12).
 *
 * George, 29 September: "telling clive that samples have started xyz shows the same as saying
 * give [two of the team] these tasks to do later." Each kind now looks like what it is:
 *
 *   project   its stages as a progression, the one it is at clearly the current one, each with
 *             its date and who or what it is waiting on;
 *   tasks     grouped by person, each task with a round tick the owner can tap, done or not;
 *   business, build   what CLIVE is doing and what comes next, as before.
 *
 * One payload draws all of it: the Mac's `objective` card (app/objectives/cards.py), which is
 * both the conversation's card (web/ui.js hands it here) and the body of the objective's sheet
 * on the home (web/alpha.js). The same two rules as web/ui.js hold: every string from outside
 * lands through textContent, never markup, and no attribute is built from data. A tick posts
 * the task's id and done-or-not to the owner's own route and nothing else; it changes CLIVE's
 * list, and nobody is told.
 *
 * By touch (the design's six gestures, with web/objective-touch.js when the page has it, and a
 * bar to say what a touch did). On a project: a tap on a stage has CLIVE say what the record holds
 * about it; a double-tap (or Enter) makes it the stage it is at now, or starts a project not yet
 * started; "now" dragged along the rail snaps stage to stage and lands where it is let go; and the
 * date it must land by is a ring on a strip of days, dragged a day at a time, the stages that
 * would land after it turning red while the finger is still down. On delegated tasks: the round
 * tick still ticks at a tap, a double-tap anywhere on the row ticks, a tap on the words says what
 * the task is, and a task pressed still for a moment can be dragged onto someone else's group to
 * hand it over (or, from the keyboard, given from a short menu). Each change is one of the owner's
 * routes; the Mac's answer redraws the shape and the bar offers Undo for six seconds. Without the
 * touch file, a read-only drawing, or no bar, the shape is drawn exactly as before.
 *
 * No dependency on the rest of the page, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveObjectiveCards = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const NS = 'http://www.w3.org/2000/svg';
  const TASK_ID = /^t_[0-9a-f]{8}$/;
  const OBJECTIVE_ID = /^obj_[0-9a-f]{8}$/;
  // The touch layer, read when it is needed: web/objective-touch.js, loaded before this file.
  const touchKit = () => {
    const kit = root && root.CliveObjectiveTouch;
    return kit && typeof kit.bar === 'function' ? kit : null;
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

  // A tick and nothing else, drawn as a path: never a glyph from a font.
  function tickMark() {
    const svg = doc().createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'oc-tick');
    const path = doc().createElementNS(NS, 'path');
    path.setAttribute('d', 'm6 12.5 4 4 8-9');
    svg.appendChild(path);
    return svg;
  }

  // ---------------------------------------------------------------- dates, in words

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  // A calendar date the Mac sent (YYYY-MM-DD), read as a local date: no time zone moves it.
  function day(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(text(value));
    if (!m) return null;
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function today(now) {
    const n = now || new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }
  function daysFrom(value, now) {
    const d = day(value);
    return d ? Math.round((d - today(now)) / 86400000) : null;
  }
  function dateWords(value, now, withDay) {
    const d = day(value);
    if (!d) return '';
    const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
    const out = withDay ? `${DAYS[d.getDay()]} ${base}` : base;
    return d.getFullYear() === today(now).getFullYear() ? out : `${out} ${d.getFullYear()}`;
  }
  function leftWords(days) {
    if (days === null || days === undefined) return '';
    if (days === 0) return 'today';
    if (days < 0) return `${-days} day${days === -1 ? '' : 's'} late`;
    return `${days} day${days === 1 ? '' : 's'} left`;
  }
  // Calendar days, counted on the tablet's own calendar (a clock change is not a day).
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const between = (a, b) => Math.round((b - a) / 86400000);
  const pad = (n) => String(n).padStart(2, '0');
  const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  // A list the way a person says it: "A", "A and B", "A, B and C".
  const spoken = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);
  const samePerson = (a, b) => text(a).trim().toLowerCase() === text(b).trim().toLowerCase();

  // ---------------------------------------------------------------- the words for a kind

  const KIND_WORD = { project: 'Project', tasks: 'Tasks', build: 'Build', business: 'Objective' };
  const kindOf = (d) => (KIND_WORD[text(d.kind)] ? text(d.kind) : 'business');

  function stageCount(d) {
    const stages = list(d.stages, 10);
    const at = stages.findIndex((s) => s.state === 'current');
    if (!stages.length) return '';
    if (at >= 0) return `Stage ${at + 1} of ${stages.length}`;
    return stages.every((s) => s.state === 'done') ? 'Every stage done' : 'Not started';
  }
  function taskCount(d) {
    let open = 0; let done = 0;
    for (const g of list(d.groups, 8)) { open += Number(g.open) || 0; done += Number(g.done) || 0; }
    return open + done ? `${done} of ${open + done} done` : '';
  }

  // The line under the title: where it is, and by when.
  function statusLine(d, now) {
    const parts = [];
    const kind = kindOf(d);
    if (kind === 'project') parts.push(stageCount(d));
    if (kind === 'tasks') parts.push(taskCount(d));
    if (text(d.deadline)) {
      const left = daysFrom(d.deadline, now);
      parts.push(`Due ${dateWords(d.deadline, now)}${left === null ? '' : ` · ${leftWords(left)}`}`);
    }
    return parts.filter(Boolean).join(' · ');
  }

  // ---------------------------------------------------------------- the shape itself

  // A project: its stages top to bottom on one rail, the stage it is at unmistakably the one
  // that is lit. Done stages carry a tick and when they were done; the current one says who it
  // is waiting on and by when; the ones to come are quiet.
  function stagesOf(d, opts, now) {
    const stages = list(d.stages, 10);
    const rail = h('ol', 'oc-steps');
    const steps = [];
    let pill = null;
    stages.forEach((s) => {
      const state = s.state === 'done' || s.state === 'current' ? s.state : 'upcoming';
      const node = h('span', 'oc-node', state === 'done' ? tickMark() : null);
      const facts = [];
      if (state === 'done' && text(s.done_at)) facts.push(`Done ${dateWords(s.done_at, now)}`);
      if (state !== 'done' && text(s.waiting_on)) facts.push(`Waiting on ${text(s.waiting_on)}`);
      if (state !== 'done' && text(s.due)) {
        const late = daysFrom(s.due, now);
        facts.push(`${late !== null && late < 0 ? 'Was due' : 'By'} ${dateWords(s.due, now)}`);
      }
      const late = state !== 'done' && text(s.due) && daysFrom(s.due, now) < 0;
      if (state === 'current') pill = h('span', 'oc-now', 'Now');
      const where = h('span', 'oc-rail', node);
      const name = h('span', 'oc-step-name', [text(s.name), state === 'current' ? pill : null]);
      const step = h('li', `oc-step is-${state}${late ? ' is-late' : ''}`, [
        where,
        h('span', 'oc-step-main', [
          name,
          facts.length ? h('span', 'oc-step-sub', facts.join(' · ')) : null,
        ]),
      ]);
      if (state === 'current') step.setAttribute('aria-current', 'step');
      rail.appendChild(step);
      steps.push({ s, state, li: step, rail: where, node, name });
    });
    const count = stageCount(d);
    const ctx = live(d, opts, now);
    const when = ctx ? landBy(d, steps, ctx) : null;
    if (ctx) stageTouch(rail, steps, ctx, pill || h('span', 'oc-now', 'Now'));
    return h('section', 'oc-shape oc-project', [
      track(stages),
      count ? h('p', 'oc-sr', count) : null,
      ctx ? h('p', 'oc-sr', 'Press Enter on a stage to make it the one it is at now.') : null,
      rail,
      when,
    ]);
  }

  // ---------------------------------------------------------------- touch: what every gesture shares

  // The touch layer for one drawing, when the page has it (web/objective-touch.js) and this drawing
  // can change the objective: an objective's own id, a bar to say what a touch did, not read-only.
  function live(d, opts, now) {
    const T = touchKit();
    const objective = text(d.objective_id);
    if (!T || !opts || opts.readOnly || !opts.bar || !OBJECTIVE_ID.test(objective)) return null;
    const tap = tapper(T);
    return {
      T, now, bar: opts.bar, key: objective,
      // Keyed by objective: a tap here and a tap on another drawing of it are the same element.
      tap: (key, part, how) => tap(`${objective}:${key}`, part, how),
      send: typeof opts.send === 'function' ? opts.send : T.post,
      url: (tail) => `/objectives/${encodeURIComponent(objective)}${tail}`,
      // The Mac's answer is what is drawn next: the card or the sheet redraws itself from it.
      redraw: (record) => { if (record && record.card && typeof opts.onChange === 'function') opts.onChange(record); },
    };
  }

  // One recogniser for every drawing: a tick's answer redraws the row before a double-tap's second
  // tap lands, and that tap must still be known as the second (one tick, never tick-and-untick).
  let taps = null;
  function tapper(T) {
    if (!taps || taps.T !== T) taps = { T, tap: T.taps() };
    return taps.tap;
  }

  // What was last sent for each objective, a touch or an Undo. Only the answer to the latest is
  // drawn: an Undo's answer that comes back after a newer touch's answer would otherwise draw the
  // objective as it was before that touch, which the Mac did make (review of PR #91).
  const LATEST = new Map();
  function sending(ctx) {
    const n = (LATEST.get(ctx.key) || 0) + 1;
    LATEST.set(ctx.key, n);
    return () => LATEST.get(ctx.key) === n;
  }

  // A touch, sent to the owner's own route: the answer redraws, and the bar says what it did.
  async function commit(ctx, tail, body) {
    const latest = sending(ctx);
    const record = await ctx.send(ctx.url(tail), body);
    if (latest()) ctx.redraw(record);
    offer(ctx, record);
    return record;
  }

  // What the Mac said a touch did, with Undo for six seconds; or, when it changed nothing, its line.
  function offer(ctx, record) {
    const undo = record && record.undo && typeof record.undo === 'object' ? record.undo : null;
    if (undo && typeof undo.token === 'string' && undo.token) {
      ctx.T.haptic('done');
      ctx.bar.did(text(undo.says), async () => {
        const latest = sending(ctx);
        const back = await ctx.send(ctx.url('/undo'), { token: undo.token });
        if (latest()) ctx.redraw(back);
        return text(back && back.said);
      });
    } else if (record && text(record.said)) {
      ctx.bar.say(text(record.said));
    }
  }

  function failed(ctx, error) {
    ctx.T.haptic('error');
    ctx.bar.say(`Not saved: ${text(error && error.message) || 'CLIVE did not answer'}`, 'error');
  }

  function rectOf(el) {
    try {
      const r = el && typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : null;
      return r && Number.isFinite(r.left) && Number.isFinite(r.top) ? r : null;
    } catch (e) { return null; }
  }
  const inside = (r, x, y) => Boolean(r) && x >= r.left && x <= r.left + r.width && y >= r.top && y <= r.top + r.height;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  function focusOn(el) { try { if (el && typeof el.focus === 'function') el.focus(); } catch (e) { /* not focusable */ } }

  // ---------------------------------------------------------------- touch: a project's stages

  // What the record holds about one stage, said when it is tapped. Only the record's own words.
  function aboutStage(s, state, now) {
    const parts = [state === 'current' ? `${text(s.name)}, now`
      : state === 'done' ? `${text(s.name)}: done${text(s.done_at) ? ` ${dateWords(s.done_at, now)}` : ''}`
      : `${text(s.name)}: to come`];
    if (state !== 'done' && text(s.waiting_on)) parts.push(`waiting on ${text(s.waiting_on)}`);
    if (state !== 'done' && text(s.due)) {
      const left = daysFrom(s.due, now);
      parts.push(`${left !== null && left < 0 ? 'was due' : 'by'} ${dateWords(s.due, now, left !== null && left >= 0 && left < 7)}`);
    }
    return `${parts.join(', ')}.`;
  }

  // The stages drawn with `at` as the one it is at now (-1: as the record has them), the "Now"
  // mark with it. Only the look changes; the Mac's answer draws the rest.
  function preview(steps, at, pill) {
    steps.forEach((st, i) => {
      const state = at < 0 ? st.state : i < at ? 'done' : i === at ? 'current' : 'upcoming';
      st.li.className = st.li.className.replace(/\bis-(done|current|upcoming)\b/, `is-${state}`);
    });
    if (pill.parentNode) pill.parentNode.removeChild(pill);
    const home = at < 0 ? steps.findIndex((st) => st.state === 'current') : at;
    if (home >= 0) steps[home].name.appendChild(pill);
  }

  function stageTouch(rail, steps, ctx, pill) {
    rail.classList.add('ot-live');
    const state = { busy: false };
    steps.forEach((st, i) => {
      st.li.setAttribute('tabindex', '0');
      st.li.addEventListener('click', () => ctx.tap(`stage:${i}`, 'stage', {
        waits: true,
        single: () => ctx.bar.say(aboutStage(st.s, st.state, ctx.now)),
        double: () => makeNow(steps, i, ctx, pill, state),
      }));
      st.li.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        makeNow(steps, i, ctx, pill, state);
      });
    });
    const at = steps.findIndex((st) => st.state === 'current');
    if (at >= 0) dragNow(steps, at, ctx, pill, state);
  }

  function makeNow(steps, i, ctx, pill, state) {
    if (steps[i].state === 'current') { ctx.bar.say(`${text(steps[i].s.name)} is already now.`); return; }
    if (!state.busy) moveTo(steps, i, ctx, pill, state, null);
  }

  // The project to stage `i`: shown at once, asked of the Mac, drawn again from its answer; put
  // back as it was, and said, when the Mac refuses or cannot be reached.
  function moveTo(steps, i, ctx, pill, state, settle) {
    state.busy = true;
    preview(steps, i, pill);
    const back = () => { preview(steps, -1, pill); if (settle) settle(); };
    commit(ctx, '/stage', { stage: text(steps[i].s.name) })
      .then((record) => { if (!(record && record.card)) back(); })   // nothing drawn from it: nothing shown
      .catch((error) => { back(); failed(ctx, error); })
      .then(() => { state.busy = false; });
  }

  // "Now", pressed and dragged along the rail: it snaps from stage to stage with a detent, the
  // stage under it shows as now, and letting go there makes it so. Let go where it started, or
  // lose the pointer, and nothing changes. A control of its own, so a still hold on it is not the
  // objective lifted to a screen (web/lift.js); a hold anywhere else on a stage still is.
  function dragNow(steps, at, ctx, pill, state) {
    const grip = h('button', 'ot-grip');
    grip.type = 'button';
    grip.setAttribute('tabindex', '-1');
    grip.setAttribute('aria-hidden', 'true');
    steps[at].rail.appendChild(grip);
    let centres = null;
    let shown = at;
    const rail = steps[at].li.parentNode;
    const place = (dy) => grip.style.setProperty('--dy', `${Math.round(dy)}px`);
    const settle = () => { grip.classList.remove('is-held'); if (rail) rail.classList.remove('is-moving'); place(0); };
    ctx.T.press(grip, {
      arm: 0,
      start: () => {
        if (state.busy) return;
        centres = steps.map((st) => { const r = rectOf(st.node); return r ? r.top + r.height / 2 : 0; });
        shown = at;
        grip.classList.add('is-held');
        if (rail) rail.classList.add('is-moving');
        ctx.T.haptic('lift');
      },
      move: (p) => {
        if (!centres) return;
        const y = give(centres[at] + p.y - p.y0, centres[0], centres[centres.length - 1]);
        place(y - centres[at]);
        const near = nearest(centres, y);
        if (near === shown) return;
        shown = near;
        ctx.T.haptic('detent');
        preview(steps, near, pill);
      },
      end: () => {
        const was = centres;
        centres = null;
        if (!was) return;
        if (shown === at) { preview(steps, -1, pill); settle(); return; }
        place(was[shown] - was[at]);
        if (rail) rail.classList.remove('is-moving');
        moveTo(steps, shown, ctx, pill, state, settle);
      },
      cancel: () => { if (!centres) return; centres = null; preview(steps, -1, pill); settle(); },
    });
  }
  // Past either end it gives, but only a little: it never covers what is above or below.
  function give(y, first, last) {
    if (y < first) return first - Math.min(16, Math.sqrt(first - y) * 2.5);
    if (y > last) return last + Math.min(16, Math.sqrt(y - last) * 2.5);
    return y;
  }
  function nearest(centres, y) {
    let best = 0;
    centres.forEach((c, i) => { if (Math.abs(c - y) < Math.abs(centres[best] - y)) best = i; });
    return best;
  }

  // ---------------------------------------------------------------- touch: the date it must land by

  const AFTER_DAYS = 7;     // the strip runs on a week past the later of the deadline and the last stage
  const MAX_DAYS = 366;

  // What a deadline means for the stages still to finish: how many would land after it, by name,
  // or that everything still lands in time. Nothing when no stage still to come has a date.
  function lands(late, dated) {
    if (late.length) return `${late.length} stage${late.length === 1 ? '' : 's'} would land late: ${spoken(late.map((st) => text(st.s.name)))}.`;
    return dated ? 'Everything still lands in time.' : '';
  }

  /* One dot a day, from today (or the deadline, if that has passed) to a week past the later of the
   * deadline and the last stage's date; the deadline ringed, each stage's date marked. The ring is
   * dragged a day at a time, or moved with the arrow keys (Enter keeps it, Escape puts it back);
   * while it moves, a stage still to come whose date would fall after it turns red, and the line
   * under the strip says how many would land late. Let go, and the Mac is asked. */
  function landBy(d, steps, ctx) {
    const deadline = day(d.deadline);
    if (!deadline) return null;
    const now = today(ctx.now);
    const first = deadline < now ? deadline : now;
    const dues = steps.map((st) => day(st.s.due)).filter(Boolean);
    const last = new Date(Math.max(deadline.getTime(), now.getTime(), ...dues.map((x) => x.getTime())));
    const n = Math.min(MAX_DAYS, between(first, last) + AFTER_DAYS + 1);
    const at = between(first, deadline);
    const pct = (i) => String(n > 1 ? Math.round((i / (n - 1)) * 10000) / 100 : 50);
    const dots = h('span', 'ot-dots');
    for (let i = 0; i < n; i += 1) {
      const date = addDays(first, i);
      const dot = h('i', `ot-day${between(now, date) === 0 ? ' is-today' : ''}${date.getDay() === 1 ? ' is-monday' : ''}`);
      dot.style.setProperty('--x', pct(i));
      dots.appendChild(dot);
    }
    const marks = steps.map((st) => {
      const due = day(st.s.due);
      const i = due ? between(first, due) : -1;
      if (i < 0 || i >= n) return null;
      dots.childNodes[i].classList.add('is-stage');
      if (st.state === 'done') dots.childNodes[i].classList.add('is-done');
      return dots.childNodes[i];
    });
    // A button in the role of a slider: a control of its own, so a still press on it is not the
    // objective lifted to a screen (web/lift.js leaves a control its own press).
    const ring = h('button', 'ot-ring', h('span', 'ot-ring-mark'));
    ring.type = 'button';
    ring.setAttribute('role', 'slider');
    ring.setAttribute('aria-label', 'The date it must land by');
    ring.setAttribute('aria-valuemin', '0');
    ring.setAttribute('aria-valuemax', String(n - 1));
    const flag = h('span', 'ot-flag');
    flag.setAttribute('aria-hidden', 'true');
    dots.setAttribute('aria-hidden', 'true');
    const days = h('div', 'ot-track', [dots, flag, ring]);
    const line = h('p', 'ot-lands');
    let cur = at;
    let busy = false;
    let moving = false;

    const show = (i, active) => {
      cur = i;
      const date = addDays(first, i);
      const iso = isoOf(date);
      const late = steps.filter((st) => st.state !== 'done' && day(st.s.due) && day(st.s.due) > date);
      const dated = steps.some((st) => st.state !== 'done' && day(st.s.due));
      steps.forEach((st, k) => {
        st.li.classList.toggle('is-after', late.indexOf(st) >= 0);
        if (marks[k]) marks[k].classList.toggle('is-after', late.indexOf(st) >= 0);
      });
      dots.childNodes.forEach((dot, k) => dot.classList.toggle('is-beyond', k > i));
      ring.style.setProperty('--x', pct(i));
      flag.style.setProperty('--x', pct(i));
      for (const el of [ring, flag, line]) el.classList.toggle('is-late', late.length > 0);
      ring.classList.toggle('is-moving', Boolean(active));
      const left = daysFrom(iso, ctx.now);
      flag.textContent = `Due ${dateWords(iso, ctx.now, true)}${active && left !== null ? ` · ${leftWords(left)}` : ''}`;
      line.textContent = lands(late, dated);
      ring.setAttribute('aria-valuenow', String(i));
      ring.setAttribute('aria-valuetext', `Due ${dateWords(iso, ctx.now, true)}${late.length
        ? `, ${late.length} stage${late.length === 1 ? '' : 's'} would land late` : dated ? ', everything lands in time' : ''}`);
    };
    const keep = (i) => {
      if (i === at) { show(at, false); return; }
      show(i, false);
      busy = true;
      commit(ctx, '/deadline', { deadline: isoOf(addDays(first, i)) })
        .then((record) => { if (!(record && record.card)) show(at, false); })
        .catch((error) => { show(at, false); failed(ctx, error); })
        .then(() => { busy = false; });
    };
    // The ring moves by how far the finger has gone along the days, from the day it was on, never
    // to wherever the finger happens to be: a press a little off the ring's centre, nudged, moved
    // the deadline by days (review of PR #91). A drag that sets off mostly up or down is not a
    // date drag at all, and moves nothing.
    let from = at;
    ctx.T.press(ring, {
      arm: 0,
      start: (p) => {
        if (busy || Math.abs(p.y - p.y0) > Math.abs(p.x - p.x0)) return;
        moving = true; from = cur; ctx.T.haptic('lift'); show(cur, true);
      },
      move: (p) => {
        const r = rectOf(days);
        if (!moving || !r || !r.width) return;
        const i = clamp(from + Math.round(((p.x - p.x0) / r.width) * (n - 1)), 0, n - 1);
        if (i === cur) return;
        ctx.T.haptic('detent');
        show(i, true);
      },
      end: () => { if (!moving) return; moving = false; keep(cur); },
      cancel: () => { if (!moving) return; moving = false; show(at, false); },
    });
    ring.addEventListener('keydown', (event) => {
      const by = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -7, PageUp: 7 }[event.key];
      const to = by !== undefined ? cur + by : event.key === 'Home' ? 0 : event.key === 'End' ? n - 1 : null;
      if (to !== null) { event.preventDefault(); if (!busy) show(clamp(to, 0, n - 1), true); return; }
      if (event.key === 'Enter') { event.preventDefault(); if (!busy) keep(cur); return; }
      if (event.key === 'Escape' && cur !== at && !busy) { event.preventDefault(); show(at, false); }
    });
    ring.addEventListener('blur', () => { if (!busy && !moving && cur !== at) show(at, false); });
    show(at, false);
    return h('div', 'ot-when', [days, line]);
  }

  // The progression at a glance: one segment per stage, filled up to where it is.
  function track(stages) {
    const bar = h('span', 'oc-track');
    bar.setAttribute('aria-hidden', 'true');
    for (const s of stages) bar.appendChild(h('i', `oc-seg is-${s.state === 'done' || s.state === 'current' ? s.state : 'upcoming'}`));
    return bar;
  }

  // Two letters from a name, for the disc that makes a person read as a person.
  function initials(name) {
    const parts = text(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '·';
    return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  // Delegated tasks: one group per person, their open tasks first. Each task is one button the
  // width of the row (the accessible name is its own words), with a round tick at its start.
  function groupsOf(d, opts, now) {
    const wrap = h('section', 'oc-shape oc-tasks');
    const ctx = live(d, opts, now);
    // Each person's group, for a task dragged onto it (`handOver`): its element and who it is.
    const people = [];
    for (const g of list(d.groups, 8)) {
      const open = Number(g.open) || 0;
      const done = Number(g.done) || 0;
      const head = h('div', 'oc-person', [
        h('span', 'oc-disc', initials(g.who)),
        h('span', 'oc-who', text(g.who)),
        h('span', 'oc-count', open === 0 && done ? 'All done' : `${done} of ${open + done} done`),
      ]);
      const rows = h('ul', 'oc-list');
      const group = h('div', `oc-group${open === 0 && done ? ' is-all-done' : ''}`, [head, rows]);
      const person = { el: group, who: text(g.who) };
      people.push(person);
      const hand = ctx ? { ctx, wrap, people, person } : null;
      for (const t of list(g.tasks, 12)) rows.appendChild(taskRow(d, t, opts, now, hand));
      if (Number(g.more) > 0) rows.appendChild(h('li', 'oc-more', `${Number(g.more)} more`));
      wrap.appendChild(group);
    }
    return wrap;
  }

  // The latest row drawn for each task, so a task handed over can settle into its new place.
  const drawn = new Map();

  function taskRow(d, t, opts, now, hand) {
    const done = t.done === true;
    const due = text(t.due);
    const left = due ? daysFrom(due, now) : null;
    const button = h('button', `oc-task${done ? ' is-done' : ''}${!done && left !== null && left < 0 ? ' is-late' : ''}`, [
      h('span', 'oc-check', tickMark()),
      h('span', 'oc-task-text', text(t.text)),
      due ? h('span', 'oc-due', dateWords(due, now, left !== null && left >= 0 && left < 7)) : null,
    ]);
    button.type = 'button';
    button.setAttribute('role', 'checkbox');
    button.setAttribute('aria-checked', done ? 'true' : 'false');
    const id = text(t.id);
    const objective = text(d.objective_id);
    if (!TASK_ID.test(id) || !OBJECTIVE_ID.test(objective) || !opts || opts.readOnly) {
      button.disabled = true;
    } else if (!hand) {
      button.addEventListener('click', () => toggle(button, objective, id, !done, opts, null));
    } else {
      touchRow(button, t, hand, () => toggle(button, objective, id, !done, opts, hand.ctx));
    }
    return h('li', 'oc-item', button);
  }

  // ---------------------------------------------------------------- touch: a task

  // What a task is, said when its words are tapped: who, what, by when. Only the record's words.
  function aboutTask(t, who, now) {
    const due = text(t.due);
    const left = due ? daysFrom(due, now) : null;
    const when = !due || t.done === true ? '' : left !== null && left < 0 ? `, was due ${dateWords(due, now)}`
      : `, by ${dateWords(due, now, left !== null && left >= 0 && left < 7)}`;
    return `${text(who)}: ${text(t.text)}${when}${t.done === true ? ', done' : ''}.`;
  }

  /* A row's touch. The round tick ticks at a tap, at once; a double-tap anywhere on the row ticks
   * (two taps on the tick are one tick, never tick-and-untick); a tap on the words has the bar
   * say what the task is, once it is clear no second tap is coming. A click that is not a pointer's
   * (Space or Enter on the focused row) ticks, as it always has. A press held still for a moment
   * and dragged hands the task over (`handOver`); the context-menu key does the same from a menu. */
  function touchRow(button, t, hand, tick) {
    const { ctx } = hand;
    const id = text(t.id);
    drawn.set(id, button);
    const held = handOver(button, t, hand);
    button.addEventListener('click', (event) => {
      if (held.took()) return;
      if (!(Number(event && event.detail) >= 1)) { tick(); return; }
      const part = ctx.T.within(event.target, 'oc-check', button) ? 'tick' : 'words';
      ctx.tap(`task:${id}`, part, {
        waits: part === 'words',
        single: () => (part === 'tick' ? tick() : ctx.bar.say(aboutTask(t, hand.person.who, ctx.now))),
        double: (first) => { if (first !== 'tick') tick(); },
      });
    });
    const menu = (event) => {
      event.preventDefault();
      if (!held.pressing()) showMenu(button, t, hand);     // a long press is the drag's, not a menu
    };
    button.addEventListener('contextmenu', menu);
    button.addEventListener('keydown', (event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) menu(event); });
  }

  /* Pressed still for a moment, the task lifts under the finger; let go over someone else's group
   * and it is theirs, settling into its place in their list (FLIP: drawn where it was let go, then
   * moved home). Let go over its own person or anywhere else, or held still and let go, and it
   * settles back and nothing changes. Until the press arms, a move is the sheet's scroll. */
  function handOver(button, t, hand) {
    const { ctx, wrap, people, person } = hand;
    let over = null;
    const place = (dx, dy) => {
      button.style.setProperty('--dx', `${Math.round(dx)}px`);
      button.style.setProperty('--dy', `${Math.round(dy)}px`);
    };
    const under = (p) => people.find((g) => inside(rectOf(g.el), p.x, p.y)) || null;
    const mark = (g) => people.forEach((x) => x.el.classList.toggle('is-over', x === g));
    const back = () => {
      wrap.classList.remove('is-dragging');
      person.el.classList.remove('is-from');
      mark(null);
      over = null;
      button.classList.remove('is-sending');
      if (!button.classList.contains('is-lifted')) return;
      button.classList.remove('is-lifted');
      button.classList.add('is-settling');
      place(0, 0);
      ctx.T.clock.later(() => button.classList.remove('is-settling'), 420);
    };
    return ctx.T.press(button, {
      arm: ctx.T.ARM_MS,
      ownClick: true,
      armed: () => {
        button.classList.add('is-lifted');
        wrap.classList.add('is-dragging');
        person.el.classList.add('is-from');
        ctx.T.haptic('lift');
      },
      move: (p) => {
        place(p.x - p.x0, p.y - p.y0);
        const g = under(p);
        const elsewhere = g && !samePerson(g.who, person.who) ? g : null;
        if (elsewhere === over) return;
        over = elsewhere;
        mark(over);
        if (over) ctx.T.haptic('detent');
      },
      end: (p) => {
        const g = under(p);
        if (!g || samePerson(g.who, person.who)) { back(); return; }
        mark(null);
        button.classList.add('is-sending');
        giveTo(button, t, g.who, hand, rectOf(button), back);
      },
      still: back,
      cancel: back,
    });
  }

  function giveTo(button, t, who, hand, from, back) {
    const id = text(t.id);
    commit(hand.ctx, `/tasks/${encodeURIComponent(id)}`, { who })
      .then(() => {
        back();
        const fresh = drawn.get(id);
        if (from && fresh && fresh !== button) flip(fresh, from, hand.ctx.T);
        else if (!from) focusOn(fresh);
      })
      .catch((error) => { back(); failed(hand.ctx, error); if (!from) focusOn(button); });
  }

  const frame = (fn) => (typeof root.requestAnimationFrame === 'function' ? root.requestAnimationFrame(fn) : setTimeout(fn, 16));
  // Drawn where it was let go, then settling into its new place. With motion turned down it is
  // simply there: nothing travels, the state changes.
  function flip(el, from, T) {
    const to = rectOf(el);
    if (!to || T.reduced()) return;
    el.classList.add('is-flying');
    el.style.setProperty('--dx', `${Math.round(from.left - to.left)}px`);
    el.style.setProperty('--dy', `${Math.round(from.top - to.top)}px`);
    frame(() => frame(() => {
      el.classList.add('is-settling');
      el.style.setProperty('--dx', '0px');
      el.style.setProperty('--dy', '0px');
      T.clock.later(() => el.classList.remove('is-flying', 'is-settling'), 480);
    }));
  }

  // From the keyboard (the context-menu key or Shift+F10 on a task), or a right click: the same
  // hand-over as a short menu of the other people on this objective. Escape puts it away.
  function showMenu(button, t, hand) {
    const item = button.parentNode;
    if (!item || item.querySelector('.ot-menu')) return;
    const others = hand.people.filter((g) => !samePerson(g.who, hand.person.who));
    if (!others.length) { hand.ctx.bar.say('There is no one else on this list to give it to.'); return; }
    const menu = h('div', 'ot-menu');
    menu.setAttribute('role', 'menu');
    const close = (refocus) => { if (menu.parentNode) menu.parentNode.removeChild(menu); if (refocus) focusOn(button); };
    const choice = (label, act) => {
      const b = h('button', 'ot-menu-item', label);
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.addEventListener('click', act);
      menu.appendChild(b);
      return b;
    };
    const items = others.map((g) => choice(`Give to ${g.who}`, () => { close(false); giveTo(button, t, g.who, hand, null, () => {}); }));
    items.push(choice('Cancel', () => close(true)));
    menu.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      event.preventDefault();
      const at = items.indexOf(doc().activeElement);
      focusOn(items[(at + (event.key === 'ArrowDown' ? 1 : items.length - 1) + items.length) % items.length]);
    });
    item.appendChild(menu);
    focusOn(items[0]);
  }

  // The tick: the circle fills at once, the Mac is asked, and the card is drawn again from what
  // the Mac then holds. Refused or unreachable, the circle goes back and says so. With the touch
  // layer, the bar then says what it did, with Undo.
  async function toggle(button, objectiveId, taskId, done, opts, ctx) {
    if (button.dataset.pending === '1') return;
    button.dataset.pending = '1';
    button.setAttribute('aria-checked', done ? 'true' : 'false');
    button.classList.toggle('is-done', done);
    try {
      const post = (opts && opts.post) || postTick;
      const record = await post(objectiveId, taskId, done);
      delete button.dataset.pending;
      if (record && record.card && opts && typeof opts.onChange === 'function') opts.onChange(record);
      if (ctx) offer(ctx, record);
    } catch (error) {
      delete button.dataset.pending;
      if (ctx) ctx.T.haptic('error');
      button.setAttribute('aria-checked', done ? 'false' : 'true');
      button.classList.toggle('is-done', !done);
      const where = button.parentNode;
      if (where) {
        const note = h('p', 'oc-error', `Not saved: ${text(error && error.message) || 'CLIVE did not answer'}`);
        note.setAttribute('role', 'status');
        where.appendChild(note);
        setTimeout(() => { if (note.parentNode) note.parentNode.removeChild(note); }, 5000);
      }
    }
  }

  async function postTick(objectiveId, taskId, done) {
    let response;
    try {
      response = await fetch(`/objectives/${encodeURIComponent(objectiveId)}/tasks/${encodeURIComponent(taskId)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done }), cache: 'no-store',
      });
    } catch (error) {
      throw new Error('CLIVE could not be reached');   // the browser's own words name no cause
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(text(data.detail) || `CLIVE answered ${response.status}`);
    return data;
  }

  // What CLIVE is doing and what comes next, for the kinds whose shape is its own work.
  function workOf(d) {
    const next = strings(d.next, 3);
    if (!text(d.doing) && !next.length) return null;
    return h('section', 'oc-shape oc-work', [
      text(d.doing) ? h('p', 'oc-line', [h('span', 'oc-label', 'Doing now'), text(d.doing)]) : null,
      next.length ? h('p', 'oc-label', 'Next') : null,
      next.length ? h('ul', 'oc-next', next.map((t) => h('li', null, t))) : null,
    ]);
  }

  // Why, what finished looks like, who is involved and how often to check in: only what the
  // owner said. Nothing here is drawn for a field that is empty.
  function factsOf(d) {
    const rows = [];
    const row = (label, value, cls) => rows.push(h('div', `oc-fact${cls ? ' ' + cls : ''}`, [h('dt', null, label), h('dd', null, value)]));
    if (text(d.purpose)) row('Why', text(d.purpose));
    if (text(d.done_when)) row('Done when', text(d.done_when));
    const people = list(d.people, 8).map((p) => (text(p.role) ? `${text(p.name)} (${text(p.role)})` : text(p.name))).filter(Boolean);
    if (people.length && kindOf(d) !== 'tasks') row('With', people.join(', '));
    const cadence = d.check_in && typeof d.check_in === 'object' ? d.check_in : null;
    if (cadence && Number(cadence.every_days) > 0) {
      const every = Number(cadence.every_days);
      const quiet = Number.isFinite(Number(cadence.quiet_days)) && cadence.quiet_days !== null ? Number(cadence.quiet_days) : null;
      row('Check in', cadence.due && quiet !== null
        ? `Due: no update for ${quiet} day${quiet === 1 ? '' : 's'}`
        : `Every ${every === 7 ? 'week' : every === 1 ? 'day' : `${every} days`}`, cadence.due ? 'is-due' : '');
    }
    return rows.length ? h('dl', 'oc-facts', rows) : null;
  }

  // What needs him and what is in the way, above everything else on the card.
  function attentionOf(d) {
    const needs = strings(d.needs_you, 2);
    const blocked = strings(d.blocked_by, 2);
    if (!needs.length && !blocked.length) return null;
    return h('div', 'oc-alerts', [
      ...needs.map((t) => h('p', 'oc-alert is-needs', [h('span', 'oc-label', 'Needs you'), t])),
      ...blocked.map((t) => h('p', 'oc-alert is-blocked', [h('span', 'oc-label', 'Blocked'), t])),
    ]);
  }

  // The shape of this objective, with its facts: what the sheet shows under its own header.
  function shape(d, opts) {
    const data = d && typeof d === 'object' ? d : {};
    const now = opts && opts.now ? opts.now : new Date();
    const kind = kindOf(data);
    const body = h('div', `oc-body is-${kind}`);
    if (kind === 'project' && list(data.stages, 10).length) body.appendChild(stagesOf(data, opts, now));
    if (list(data.groups, 8).length) body.appendChild(groupsOf(data, opts, now));
    // Every task taken off: that is the answer, and it is said rather than left blank.
    else if (kind === 'tasks') body.appendChild(h('p', 'card-note', 'No tasks on it.'));
    // The sheet lists CLIVE's own work items itself, with their approvals; the card does not.
    if ((kind === 'business' || kind === 'build') && !(opts && opts.sheet)) add(body, workOf(data));
    add(body, factsOf(data));
    return body;
  }

  // The conversation's card. Its head says what kind of thing this is and where it stands;
  // the body is the shape. A tick redraws this card in place from what the Mac then holds. With
  // the touch layer, the bar at its foot says what a touch on it did, with Undo.
  function card(d, opts) {
    const data = d && typeof d === 'object' ? d : {};
    const now = opts && opts.now ? opts.now : new Date();
    const kind = kindOf(data);
    const said = (opts && opts.bar) || (opts && opts.readOnly ? null : bar());
    const node = h('article', `card card-objective oc-card is-${kind}`);
    node.dataset.type = 'objective';
    // Which objective this is, so it can be held and put on a screen (web/lift.js), and focused
    // for the context-menu key to do the same. Only an id of an objective's own shape is carried.
    if (/^obj_[0-9a-f]{8}$/.test(text(data.objective_id))) {
      node.dataset.objective = text(data.objective_id);
      node.setAttribute('tabindex', '0');
    }
    const draw = (payload) => {
      const line = statusLine(payload, now);
      const settings = Object.assign({}, opts || {}, {
        bar: said,
        onChange: (record) => {
          draw(record.card);
          if (opts && typeof opts.onChange === 'function') opts.onChange(record);
        },
      });
      while (node.childNodes.length) node.removeChild(node.childNodes[0]);
      add(node, [
        h('div', 'card-head', h('div', 'oc-head', [
          h('p', 'card-kicker', KIND_WORD[kind]),
          h('h2', 'card-title', text(payload.title) || KIND_WORD[kind]),
          line ? h('p', 'card-sub oc-status', line) : null,
        ])),
        attentionOf(payload),
        shape(payload, settings),
        said ? said.el : null,
      ]);
    };
    draw(data);
    return node;
  }

  // A bar for a drawing of an objective (web/objective-touch.js), when the page has the touch
  // layer: the sheet on the home asks for one and keeps it at its foot through its redraws.
  function bar() {
    const kit = touchKit();
    return kit ? kit.bar() : null;
  }

  // ---------------------------------------------------------------- the home row

  // What a row on the home says under the title, in the kind's own terms, and the small
  // progression a project carries beside it. Null for a kind whose row is the home's own.
  function row(summary) {
    const o = summary && typeof summary === 'object' ? summary : {};
    const kind = text(o.kind);
    if (o.attention === 'check_in' && o.check_in && typeof o.check_in === 'object' && o.check_in.quiet_days !== null) {
      const quiet = Number(o.check_in.quiet_days);
      return { sub: `Check in: no update for ${quiet} day${quiet === 1 ? '' : 's'}`, track: kind === 'project' ? track(list(o.stages, 10)) : null };
    }
    if (kind === 'project') {
      const stages = list(o.stages, 10);
      const at = o.stage && typeof o.stage === 'object' ? o.stage : null;
      const sub = at ? (text(at.waiting_on) ? `${text(at.name)} · waiting on ${text(at.waiting_on)}` : text(at.name))
        : stages.length && stages.every((s) => s.state === 'done') ? 'Every stage done' : 'Not started';
      return { sub, track: stages.length ? track(stages) : null };
    }
    if (kind === 'tasks') {
      const people = list(o.people_tasks, 8);
      if (!people.length) return null;
      const sub = people.map((p) => {
        const open = Number(p.open) || 0; const done = Number(p.done) || 0;
        return open === 0 ? `${text(p.who)} done` : `${text(p.who)} ${done} of ${open + done}`;
      }).join(' · ');
      return { sub, track: null };
    }
    return null;
  }

  return { card, shape, row, bar, statusLine, dateWords, leftWords, initials, KIND_WORD };
});
