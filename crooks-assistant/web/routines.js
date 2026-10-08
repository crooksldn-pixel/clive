/* CLIVE · named routines: the "routine" card (DEC-074).
 *
 * One drawing per view of the card the Mac built (app/work/routine_cards.py `card`):
 *
 *   view "list"   the asker's routines: each name, how many steps, how many are changes, and the
 *                 first few steps in the words they were saved with.
 *   view "one"    one routine as it is saved now: its steps in order, each a read, a change, or a
 *                 step that acts at once, with what it changes ("Puts it on the Office TV each run").
 *   view "run"    one routine as this turn ran it: each step done, waiting for his gesture on its own
 *                 card, what a step that acts at once changed ("Put on the Office TV", never "Done"),
 *                 failed, skipped with why, or not done.
 *
 * Dots that mean something and nothing else: blue is waiting for him (a change staged on its card,
 * which sits above this one); iOS orange is a step that did not happen (skipped, not done); red is a
 * step that failed; a quiet dot is a read that ran, or a read in a saved routine; a solid light dot
 * is a step that changes something at once, with no card (a screen, the work list), and its words say
 * what. In a saved routine a change has a hollow blue ring: when it runs, it will wait for him.
 *
 * The same two rules as web/ui.js: every string lands through textContent, never markup, and no
 * attribute is built from what the Mac sent. Nothing here is tappable: a routine is run or changed by
 * saying so. No dependency on the rest of the page, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveRoutines = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const RUN = {
    done: ['is-quiet', 'Done'],
    waiting: ['is-ask', 'Waiting for you on its card'],
    acted: ['is-acts', 'Changed at once'],
    failed: ['is-bad', 'Could not be done'],
    skipped: ['is-warn', 'Skipped'],
    not_done: ['is-warn', 'Not done'],
    pending: ['is-pending', 'Not yet'],
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
  const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function row(cls, main, state, meta) {
    return h('li', `rn-row ${cls}`, [
      h('span', 'rn-dot', null),
      h('span', 'rn-main', main),
      state ? h('p', 'rn-state', state) : null,
      meta ? h('p', 'rn-meta', meta) : null,
    ]);
  }

  function title(d) {
    const view = text(d && d.view);
    if (view === 'list') return 'Routines';
    return text(d && d.title) || 'Routine';
  }

  function sub(d) {
    const view = text(d && d.view);
    const said = text(d && d.said);
    if (view === 'list') {
      const n = list(d.routines, 30).length;
      const kept = n ? count(n, 'routine', 'routines') + ' saved' : 'None saved yet';
      return said ? `${said}. ${kept}` : kept;
    }
    if (view === 'run') {
      const c = (d && d.counts) || {};
      const parts = [];
      if (c.done) parts.push(`${c.done} done`);
      if (c.waiting) parts.push(`${c.waiting} waiting for you`);
      if (c.acted) parts.push(`${c.acted} changed at once`);
      if (c.failed) parts.push(`${c.failed} failed`);
      if (c.skipped) parts.push(`${c.skipped} skipped`);
      if (c.not_done) parts.push(`${c.not_done} not done`);
      return parts.length ? `Ran: ${parts.join(' · ')}` : 'Running';
    }
    const steps = list(d && d.steps, 30);
    const changes = steps.filter((s) => s.kind === 'change').length;
    const shape = steps.length
      ? count(steps.length, 'step', 'steps') + (changes ? `, ${count(changes, 'change', 'changes')}` : '')
      : 'No steps yet';
    return said ? `${said}. ${shape}` : shape;
  }

  function listBody(d) {
    const routines = list(d.routines, 30);
    if (!routines.length) return [];   // the line under the title says none are saved
    return [h('ul', 'rn-rows', routines.map((r) => {
      const n = Number(r.count) || 0;
      const changes = Number(r.changes) || 0;
      const says = (Array.isArray(r.says) ? r.says : []).map(text).filter(Boolean);
      const more = Number(r.more) || 0;
      const shape = count(n, 'step', 'steps') + (changes ? `, ${count(changes, 'change', 'changes')}` : '');
      const meta = says.length ? says.join(' · ') + (more ? ` · and ${more} more` : '') : 'No steps yet';
      return row('is-quiet', [h('span', 'rn-name', text(r.name)), h('span', 'rn-side', shape)], '', meta);
    }))];
  }

  function oneBody(d) {
    const steps = list(d.steps, 30);
    if (!steps.length) return [];      // the line under the title says it has no steps yet
    const out = [h('ol', 'rn-rows', steps.map((s) => {
      const change = s.kind === 'change';
      const acts = s.kind === 'acts';
      const state = change ? 'A change: waits for you on its card' : acts ? (text(s.does) || 'Changes something at once') : '';
      return row(change ? 'is-change' : acts ? 'is-acts' : 'is-read', [h('span', 'rn-n', text(s.n)), h('span', 'rn-say', text(s.say))],
        state, '');
    }))];
    // What is true (the review's N4): no id is kept, and each run finds its records again from the step's words,
    // which may name the same order every time ("Note on 1940").
    if (d.looked_up) out.push(h('p', 'card-note', "No id is kept: each run looks its records up again from the step's words."));
    return out;
  }

  function runBody(d) {
    const steps = list(d.steps, 30);
    return [h('ol', 'rn-rows', steps.map((s) => {
      const [cls, said] = RUN[text(s.state)] || RUN.not_done;
      const why = text(s.why);
      const line = text(s.state) === 'acted' ? (text(s.did) || said) : why ? `${said}: ${why}` : said;
      return row(cls, [h('span', 'rn-n', text(s.n)), h('span', 'rn-say', text(s.say))], line, '');
    }))];
  }

  function body(d) {
    const view = text(d && d.view);
    if (view === 'list') return listBody(d);
    if (view === 'one') return oneBody(d);
    if (view === 'run') return runBody(d);
    return [h('p', 'card-note', 'Nothing to show.')];
  }

  return { body, title, sub };
});
