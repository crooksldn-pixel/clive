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
 * No dependency on the rest of the page, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory();
  root.CliveObjectiveCards = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const NS = 'http://www.w3.org/2000/svg';

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
  function stagesOf(d, now) {
    const stages = list(d.stages, 10);
    const rail = h('ol', 'oc-steps');
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
      const step = h('li', `oc-step is-${state}${late ? ' is-late' : ''}`, [
        h('span', 'oc-rail', node),
        h('span', 'oc-step-main', [
          h('span', 'oc-step-name', [text(s.name), state === 'current' ? h('span', 'oc-now', 'Now') : null]),
          facts.length ? h('span', 'oc-step-sub', facts.join(' · ')) : null,
        ]),
      ]);
      if (state === 'current') step.setAttribute('aria-current', 'step');
      rail.appendChild(step);
    });
    const count = stageCount(d);
    return h('section', 'oc-shape oc-project', [
      track(stages),
      count ? h('p', 'oc-sr', count) : null,
      rail,
    ]);
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
    for (const g of list(d.groups, 8)) {
      const open = Number(g.open) || 0;
      const done = Number(g.done) || 0;
      const head = h('div', 'oc-person', [
        h('span', 'oc-disc', initials(g.who)),
        h('span', 'oc-who', text(g.who)),
        h('span', 'oc-count', open === 0 && done ? 'All done' : `${done} of ${open + done} done`),
      ]);
      const rows = h('ul', 'oc-list');
      for (const t of list(g.tasks, 12)) rows.appendChild(taskRow(d, t, opts, now));
      if (Number(g.more) > 0) rows.appendChild(h('li', 'oc-more', `${Number(g.more)} more`));
      wrap.appendChild(h('div', `oc-group${open === 0 && done ? ' is-all-done' : ''}`, [head, rows]));
    }
    return wrap;
  }

  const TASK_ID = /^t_[0-9a-f]{8}$/;
  const OBJECTIVE_ID = /^obj_[0-9a-f]{8}$/;

  function taskRow(d, t, opts, now) {
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
    } else {
      button.addEventListener('click', () => toggle(button, objective, id, !done, opts));
    }
    return h('li', 'oc-item', button);
  }

  // The tick: the circle fills at once, the Mac is asked, and the card is drawn again from what
  // the Mac then holds. Refused or unreachable, the circle goes back and says so.
  async function toggle(button, objectiveId, taskId, done, opts) {
    if (button.dataset.pending === '1') return;
    button.dataset.pending = '1';
    button.setAttribute('aria-checked', done ? 'true' : 'false');
    button.classList.toggle('is-done', done);
    try {
      const post = (opts && opts.post) || postTick;
      const record = await post(objectiveId, taskId, done);
      delete button.dataset.pending;
      if (record && record.card && opts && typeof opts.onChange === 'function') opts.onChange(record);
    } catch (error) {
      delete button.dataset.pending;
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
    if (kind === 'project' && list(data.stages, 10).length) body.appendChild(stagesOf(data, now));
    if (list(data.groups, 8).length) body.appendChild(groupsOf(data, opts, now));
    // Every task taken off: that is the answer, and it is said rather than left blank.
    else if (kind === 'tasks') body.appendChild(h('p', 'card-note', 'No tasks on it.'));
    // The sheet lists CLIVE's own work items itself, with their approvals; the card does not.
    if ((kind === 'business' || kind === 'build') && !(opts && opts.sheet)) add(body, workOf(data));
    add(body, factsOf(data));
    return body;
  }

  // The conversation's card. Its head says what kind of thing this is and where it stands;
  // the body is the shape. A tick redraws this card in place from what the Mac then holds.
  function card(d, opts) {
    const data = d && typeof d === 'object' ? d : {};
    const now = opts && opts.now ? opts.now : new Date();
    const kind = kindOf(data);
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
      ]);
    };
    draw(data);
    return node;
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

  return { card, shape, row, statusLine, dateWords, leftWords, initials, KIND_WORD };
});
