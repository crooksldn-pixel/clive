/* The Builds screen: every build of CLIVE itself, in plain words, and George's decisions on them.
 *
 * George's words (2 Oct 2026): "There is no way for me to simply see what is in progress. SHA and
 * 79bcbcbi848 (or whatever) bears no meaning to me, and better yet I cannot see any build queue,
 * what's in progress, why it stopped, why it's important anywhere".
 *
 * One screen, reached from the home's Builds row and by asking CLIVE what is being built (a turn in
 * which CLIVE read the build queue opens it). It draws GET /objectives/builds/board
 * (app/builds/board.py) as it comes: needs you, in progress, queued, stopped, on the trunk, live,
 * newest first in each. Each build says what it is for, where it is (a road of dots, Filed, Built,
 * Reviewed, On the trunk, Live, lit steel as far as it has come, the stage it is at in blue when it
 * moves or waits on him, red where it stopped), why it stopped and why it matters, with times in
 * words. No SHA, branch or request id is on the face: they sit in the technical details.
 *
 * A build that waits on George carries its question: two or three answers, each saying what happens
 * next, the recommended one marked with why. A tap picks an answer and a second tap on the button
 * records it (POST /objectives/builds/decide), bound to the question exactly as drawn; a build that
 * moved on meanwhile records nothing and shows the question as it now stands. What he chose then
 * stays on the build. Nothing here files, sends or changes anything else.
 *
 * Every word from the Mac lands through textContent; no attribute is built from what the Mac sent
 * (only this file's class names and numbers it computes). No dependency on the rest of the page, so
 * it runs under Node against tests/web/dom-shim.js (tests/web/builds.test.js).
 */
(function (root, factory) {
  const api = factory();
  root.CliveBuilds = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const STAGES = ['Filed', 'Built', 'Reviewed', 'On the trunk', 'Live'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const LIVE_SHOWN = 5;
  const TIMES = ['no times', 'once', 'twice', 'three times', 'four times', 'five times', 'six times', 'seven times', 'eight times', 'nine times'];
  const EVENTS = { filed: 'Filed', started: 'Started', review: 'Sent for review', stopped: 'Stopped',
    approved: 'Approved', landed: 'Landed', finished: 'Finished' };

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);

  function el(tag, cls, words) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (words !== undefined && words !== null && words !== '') node.textContent = text(words);
    return node;
  }
  function svg(tag, attrs) {
    const node = doc().createElementNS(NS, tag);
    for (const k of Object.keys(attrs || {})) node.setAttribute(k, String(attrs[k]));
    return node;
  }
  function add(parent, ...kids) {
    for (const kid of kids) if (kid) parent.appendChild(kid);
    return parent;
  }

  // ---------------------------------------------------------------- time, in words

  /* How long ago, as one says it: "just now", "4 min ago", "an hour ago", "yesterday", "3 days
   * ago", and past a week the day itself ("on 25 Sep"). Empty when the time is not one. */
  function ago(iso, now) {
    const then = new Date(text(iso));
    if (!text(iso) || Number.isNaN(then.getTime())) return '';
    const at = now instanceof Date ? now : new Date();
    const mins = Math.max(0, Math.round((at - then) / 60000));
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return hours === 1 ? 'an hour ago' : `${hours} hours ago`;
    const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const days = Math.round((startOf(at) - startOf(then)) / 86400000);
    if (days <= 1) return 'yesterday';
    if (days < 7) return `${days} days ago`;
    const year = then.getFullYear() !== at.getFullYear() ? ` ${then.getFullYear()}` : '';
    return `on ${then.getDate()} ${MONTHS[then.getMonth()]}${year}`;
  }
  // "Started 20 min ago", "Stopped yesterday", "Finished on 25 Sep".
  function whenWords(when, now) {
    const w = when && typeof when === 'object' ? when : {};
    const said = ago(w.at, now);
    const verb = EVENTS[text(w.event)] || '';
    return verb && said ? `${verb} ${said}` : '';
  }

  // ---------------------------------------------------------------- the road

  /* Five stages, each one of: lit (done, steel), now (where it is, moving: blue, breathing), you
   * (waiting on George: a blue ring, breathing), stop (where it stopped: red ring), wait (where it
   * waits on something else: a quiet ring), dim (to come). */
  function roadModel(road) {
    const r = road && typeof road === 'object' ? road : {};
    const lit = Math.max(0, Math.min(STAGES.length, Number(r.lit) || 0));
    const mark = Number.isInteger(r.mark) && r.mark >= 0 && r.mark < STAGES.length ? r.mark : null;
    const kind = ['now', 'you', 'stop', 'wait'].indexOf(text(r.mark_kind)) >= 0 ? text(r.mark_kind) : null;
    return STAGES.map((name, i) => ({ name, state: mark === i && kind ? kind : i < lit ? 'lit' : 'dim' }));
  }

  function drawRoad(road, opts) {
    const o = opts || {};
    const nodes = roadModel(road);
    const w = o.big ? 300 : 124;
    const h = o.big ? 28 : 16;
    // The big road's dots sit at the centres of five equal columns, so each name sits under its dot.
    const pad = o.big ? 30 : 7;
    const step = (w - pad * 2) / (nodes.length - 1);
    const cy = h / 2;
    const box = svg('svg', { viewBox: `0 0 ${w} ${h}`, class: o.big ? 'bd-road is-big' : 'bd-road', 'aria-hidden': 'true', focusable: 'false' });
    const r = o.big ? 5.2 : 3.6;
    nodes.forEach((n, i) => {
      const x = pad + i * step;
      if (i > 0) {
        // The run between two stages: three small dots, lit once the stage it leads to is reached.
        const reached = n.state === 'lit' || (nodes[i - 1].state === 'lit' && n.state !== 'dim');
        for (let k = 1; k <= 3; k++) {
          box.appendChild(svg('circle', { cx: (x - step + (step * k) / 4).toFixed(2), cy, r: o.big ? 1.4 : 1.05, class: reached ? 'bd-run is-lit' : 'bd-run' }));
        }
      }
      const cls = `bd-n is-${n.state}`;
      if (n.state === 'you' || n.state === 'stop' || n.state === 'wait') {
        box.appendChild(svg('circle', { cx: x.toFixed(2), cy, r: (r + 1).toFixed(2), class: `${cls} is-ring` }));
        if (n.state !== 'wait') box.appendChild(svg('circle', { cx: x.toFixed(2), cy, r: (r * 0.45).toFixed(2), class: `${cls} is-core` }));
      } else {
        box.appendChild(svg('circle', { cx: x.toFixed(2), cy, r: (n.state === 'dim' ? r * 0.72 : r).toFixed(2), class: cls }));
      }
    });
    if (!o.big) return box;
    const wrap = el('div', 'bd-roadbig');
    wrap.appendChild(box);
    const labels = el('div', 'bd-stages');
    nodes.forEach((n) => labels.appendChild(el('span', `bd-stage is-${n.state}`, n.name)));
    wrap.appendChild(labels);
    return wrap;
  }

  // ---------------------------------------------------------------- one finding

  function findingNode(f) {
    const box = el('div', 'bd-finding');
    add(box, el('p', 'bd-fid', text(f.id)));
    const rows = [["What's wrong", f.wrong], ['Why it matters', [text(f.matters), text(f.where)].filter(Boolean).join(' ')], ['What fixes it', f.fix]];
    for (const [label, words] of rows) {
      if (!text(words)) continue;
      add(box, el('p', 'bd-flabel', label), el('p', 'bd-ftext', words));
    }
    const t = f.technical && typeof f.technical === 'object' ? f.technical : {};
    if (text(t.finding) || text(t.evidence) || text(t.repair)) {
      const more = el('details', 'bd-tech is-inner');
      add(more, el('summary', 'bd-techsum', 'The reviewer’s own words'));
      for (const [label, words] of [['Finding', t.finding], ['Evidence', t.evidence], ['Required repair', t.repair]]) {
        if (text(words)) add(more, el('p', 'bd-tk', label), el('p', 'bd-tv', words));
      }
      box.appendChild(more);
    }
    return box;
  }

  // ---------------------------------------------------------------- the question he answers

  let questions = 0;   // a name per question for its answers' radio group, a number of this file's own

  function decisionNode(b, on) {
    const q = b.decision;
    const handlers = on || {};
    const box = el('div', 'bd-decision');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Your decision');
    add(box, el('p', 'bd-q', q.question));
    if (text(q.context)) add(box, el('p', 'bd-context', q.context));
    const name = `bd-q${++questions}`;
    const answers = el('div', 'bd-answers');
    answers.setAttribute('role', 'radiogroup');
    let picked = null;
    let pickedLabel = '';
    const choose = el('button', 'btn primary bd-choose', 'Pick an answer');
    choose.type = 'button';
    choose.disabled = true;
    const said = el('p', 'bd-said');
    said.setAttribute('role', 'status');
    for (const a of list(q.answers)) {
      const row = el('label', `bd-ans${a.recommended ? ' is-recommended' : ''}`);
      const input = el('input', 'bd-radio');
      input.type = 'radio';
      input.name = name;
      const words = el('span', 'bd-anstext');
      const top = el('span', 'bd-anshead');
      add(top, el('span', 'bd-anslabel', a.label), a.recommended ? el('span', 'bd-rec', 'Recommended') : null);
      add(words, top, el('span', 'bd-then', a.then));
      add(row, input, el('span', 'bd-dot'), words);
      const pick = () => {
        picked = text(a.key);
        pickedLabel = text(a.label);
        for (const other of answers.children) other.classList.remove('is-picked');
        row.classList.add('is-picked');
        input.checked = true;
        choose.disabled = false;
        choose.textContent = `Choose: ${text(a.label)}`;
      };
      input.addEventListener('change', pick);
      row.addEventListener('click', (event) => { if (!event || event.target !== input) pick(); });
      answers.appendChild(row);
    }
    box.appendChild(answers);
    const rec = list(q.answers).find((a) => a.recommended);
    if (rec && text(q.because)) add(box, el('p', 'bd-because', `Recommended: ${text(rec.label)}. ${text(q.because)}`));
    // What is true of an answer that asks for something to be done: nothing acts on it by itself yet.
    if (list(q.answers).some((a) => a.acts) && text(q.waiting)) add(box, el('p', 'bd-waiting', q.waiting));
    choose.addEventListener('click', async () => {
      if (!picked || typeof handlers.decide !== 'function') return;
      choose.disabled = true;
      choose.textContent = 'Recording…';
      said.textContent = '';
      const answer = await handlers.decide(b, picked);
      if (answer && answer.error) {
        said.textContent = answer.error;
        choose.disabled = false;
        choose.textContent = `Choose: ${pickedLabel}`;
      }
    });
    add(box, choose, said);
    return box;
  }

  function chosenNode(b, on) {
    const c = b.chosen;
    const box = el('div', 'bd-chosen');
    const when = ago(c.decided_at, on && on.now);
    add(box, el('p', 'bd-chose', `You chose ${text(c.label)}${when ? `, ${when}` : ''}.`), el('p', 'bd-then', c.then));
    if (text(c.waiting)) add(box, el('p', 'bd-waiting', c.waiting));
    if (b.decision) {
      const change = el('button', 'bd-link', 'Change your answer');
      change.type = 'button';
      change.addEventListener('click', () => {
        box.textContent = '';
        box.appendChild(decisionNode(b, on));
      });
      box.appendChild(change);
    }
    return box;
  }

  // ---------------------------------------------------------------- one build

  function fact(label, words) {
    if (!text(words)) return null;
    return add(el('div', 'bd-fact'), el('p', 'bd-flabel', label), el('p', 'bd-ftext', words));
  }

  function techNode(b) {
    const d = b.details && typeof b.details === 'object' ? b.details : {};
    const more = el('details', 'bd-tech');
    add(more, el('summary', 'bd-techsum', 'Technical details'));
    // [label, words, set as code]: ids and commits are set as code, everything else as prose.
    const rows = [
      ['Request', d.request_id, true], ['Branch', d.branch, true], ['Candidate commit', d.candidate, true],
      ['Started from', d.base, true], ['Revision', d.revision, false],
      ['GitHub runs', Array.isArray(d.github_runs) ? d.github_runs.map(text).join(', ') : '', true],
      ['GitHub', d.github, false], ['Review verdicts', Array.isArray(d.verdicts) ? d.verdicts.join(', ') : '', false],
      ['The loop’s words', d.loop_words, false], ['What was asked', d.asked, false],
    ];
    for (const [label, words, code] of rows) {
      if (text(words)) add(more, el('p', 'bd-tk', label), el('p', code ? 'bd-tv is-code' : 'bd-tv', words));
    }
    const tries = list(d.tries);
    if (tries.length > 1) {
      add(more, el('p', 'bd-tk', `Tries (${tries.length})`));
      tries.forEach((t, i) => add(more, el('p', 'bd-tv', `${i + 1}. ${text(t.request_id)}: ${text(t.words)}`)));
    }
    return more;
  }

  // "Being built, started 20 min ago": where it is, then when that began, in one line.
  function stateLine(b, now) {
    const when = whenWords(b.when, now);
    const words = text(b.words);
    if (!words) return when;
    if (when && when.split(' ')[0].toLowerCase() === words.toLowerCase()) return when;   // never "Stopped, stopped"
    return when ? `${words}, ${when.charAt(0).toLowerCase()}${when.slice(1)}` : words;
  }

  function buildNode(b, on) {
    const o = on || {};
    const item = el('details', `bd-build is-${text(b.state).replace(/[^a-z_]/g, '')}`);
    if (b.group === 'needs_you') item.setAttribute('open', '');
    const sum = el('summary', 'bd-sum');
    const head = el('span', 'bd-head');
    add(head, el('span', 'bd-title', text(b.title) || 'Title not read from GitHub yet'), el('span', 'bd-chev'));
    const line = el('span', 'bd-line');
    add(line, drawRoad(b.road), el('span', 'bd-state', stateLine(b, o.now)));
    add(sum, head, line);
    item.appendChild(sum);

    const body = el('div', 'bd-body');
    add(body, drawRoad(b.road, { big: true }), fact('What it’s for', b.serves));
    if (b.why && text(b.why.says)) add(body, fact('Why it stopped', b.why.says));
    const findings = Array.isArray(b.findings) ? b.findings : null;
    if (findings && findings.length) {
      const all = el('div', 'bd-findings');
      findings.forEach((f) => all.appendChild(findingNode(f)));
      body.appendChild(all);
    } else if (Array.isArray(b.finding_ids) && b.finding_ids.length) {
      const ids = b.finding_ids.map(text).join(', ');
      add(body, el('p', 'bd-muted', `What ${ids} ${b.finding_ids.length === 1 ? 'says is' : 'say is'} kept on the build server: the loop doesn't publish the reviewer's wording yet, so CLIVE can't show it here.`));
    }
    if (text(b.note)) add(body, el('p', 'bd-muted', b.note));
    // Why it matters, when a gap CLIVE recorded says so; without one, the plain fact, quietly.
    if (b.matters_known) add(body, fact('Why it matters', b.matters));
    else if (text(b.matters)) add(body, el('p', 'bd-muted', b.matters));
    if (b.chosen) body.appendChild(chosenNode(b, o));
    else if (b.decision) body.appendChild(decisionNode(b, o));
    if (Number(b.tries) > 1) add(body, el('p', 'bd-muted', `Filed ${TIMES[Number(b.tries)] || `${Number(b.tries)} times`}; the earlier tries are in the technical details.`));
    body.appendChild(techNode(b));
    item.appendChild(body);
    return item;
  }

  // ---------------------------------------------------------------- the screen

  function draw(host, payload, on) {
    const o = on || {};
    const p = payload && typeof payload === 'object' ? payload : {};
    while (host.childNodes.length) host.removeChild(host.childNodes[0]);
    const hello = el('div', 'bd-hello');
    add(hello, el('h1', 'bd-h1', 'Builds'), el('p', 'bd-summary', p.summary || ''));
    const read = ago(p.as_of, o.now);
    if (read) add(hello, el('p', 'bd-asof', `The build loop last reported ${read}.`));
    host.appendChild(hello);
    for (const problem of Array.isArray(p.problems) ? p.problems : []) add(host, el('p', 'bd-problem', problem));
    if (p.connected === false) return host;
    const groups = list(p.groups);
    if (!groups.length) add(host, el('p', 'bd-empty', 'The build loop has nothing filed. Ask CLIVE to build something and it shows here.'));
    for (const g of groups) {
      const section = el('section', 'bd-group');
      add(section, el('h2', 'bd-h2', g.title));
      const rows = el('div', 'bd-list');
      const builds = list(g.builds);
      const cut = g.key === 'live' && builds.length > LIVE_SHOWN && !o.allLive;
      for (const b of cut ? builds.slice(0, LIVE_SHOWN) : builds) {
        const node = buildNode(b, o);
        if (Array.isArray(o.drawn)) o.drawn.push([node, text(b.key)]);
        rows.appendChild(node);
      }
      section.appendChild(rows);
      if (cut) {
        const more = el('button', 'bd-more', `Show all ${builds.length} live builds`);
        more.type = 'button';
        more.addEventListener('click', () => { if (typeof o.showAll === 'function') o.showAll(); });
        section.appendChild(more);
      }
      host.appendChild(section);
    }
    return host;
  }

  // ---------------------------------------------------------------- on the page

  const S = { open: false, payload: null, brief: null, allLive: false, ui: null, timer: null, back: null, flash: '',
    drawn: [], opened: new Map() };

  async function getJson(path, body) {
    const f = typeof fetch === 'function' ? fetch : globalThis.fetch;
    const response = await f(path, body === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  // The conversation this page is in (web/app.js keeps it under 'crooks.session'): the session his
  // answer is recorded as made in. Nothing else of the page is read.
  function sessionId() {
    try { return text(globalThis.localStorage && globalThis.localStorage.getItem('crooks.session')); } catch (e) { return ''; }
  }

  async function decide(b, answer) {
    const q = b.decision || {};
    let got;
    try {
      got = await getJson('/objectives/builds/decide', { build: text(b.key), proposal_id: text(q.proposal_id),
        fingerprint: text(q.fingerprint), answer, session_id: sessionId() });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so nothing was recorded.' };
    }
    if (got.ok && got.data && got.data.board) {
      S.payload = got.data.board;
      S.flash = got.data.chosen ? `Recorded: ${text(got.data.chosen.label)}.` : '';
      render();
      return { ok: true };
    }
    if (got.status === 409) {
      S.flash = text(got.data && got.data.detail);
      await refresh();
      return { ok: false };
    }
    return { error: text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was recorded.` };
  }

  function ensureUi() {
    if (S.ui) return S.ui;
    const panel = el('section', 'bd');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'bd-title');
    panel.hidden = true;
    const top = el('div', 'bd-top');
    const back = el('button', 'bd-back');
    back.type = 'button';
    const chev = svg('svg', { viewBox: '0 0 24 24', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false', class: 'bd-backchev' });
    chev.appendChild(svg('path', { d: 'm15 6-6 6 6 6' }));
    add(back, chev, el('span', null, 'Home'));
    back.addEventListener('click', close);
    top.appendChild(back);
    const flash = el('p', 'bd-flash');
    flash.setAttribute('role', 'status');
    const scroll = el('div', 'bd-scroll');
    add(panel, top, flash, scroll);
    if (doc().body) doc().body.appendChild(panel);
    if (typeof panel.addEventListener === 'function') {
      panel.addEventListener('keydown', (event) => { if (event && event.key === 'Escape') close(); });
    }
    S.ui = { panel, scroll, flash, back };
    return S.ui;
  }

  function render() {
    const U = ensureUi();
    const keepTop = U.scroll.scrollTop || 0;
    // A build he opened stays open on a redraw, and one he closed stays closed: remembered by the
    // build's key, in memory only (never on an attribute).
    for (const [node, key] of S.drawn || []) S.opened.set(key, Boolean(node.open));
    const drawn = [];
    draw(U.scroll, S.payload || { summary: 'Reading the build loop\u2026', groups: [] }, {
      decide, now: new Date(), allLive: S.allLive, showAll: () => { S.allLive = true; render(); }, drawn,
    });
    for (const [node, key] of drawn) {
      if (!S.opened.has(key)) continue;
      if (S.opened.get(key)) node.setAttribute('open', '');
      else if (node.removeAttribute) node.removeAttribute('open');
    }
    S.drawn = drawn;
    const h1 = U.scroll.querySelector ? U.scroll.querySelector('.bd-h1') : null;
    if (h1) h1.setAttribute('id', 'bd-title');
    U.flash.textContent = S.flash || '';
    U.flash.hidden = !S.flash;
    if (S.flash) setTimeout(() => { S.flash = ''; if (S.ui) { S.ui.flash.textContent = ''; S.ui.flash.hidden = true; } }, 5000);
    U.scroll.scrollTop = keepTop;
  }


  async function refresh() {
    try {
      const got = await getJson('/objectives/builds/board');
      if (got.ok) S.payload = got.data;
      else S.payload = { connected: false, summary: text(got.data && got.data.detail) || `The build queue could not be read (CLIVE answered ${got.status}).`, groups: [] };
    } catch (e) {
      S.payload = { connected: false, summary: 'CLIVE could not be reached, so the build queue could not be read.', groups: [] };
    }
    if (S.open) render();
    return S.payload;
  }

  function open() {
    const U = ensureUi();
    S.open = true;
    S.back = doc().activeElement || null;
    U.panel.hidden = false;
    if (doc().body && doc().body.classList) doc().body.classList.add('bd-on');
    U.scroll.scrollTop = 0;   // opened again, it starts at the top: what needs him first
    render();
    setTimeout(() => { U.panel.classList.add('is-open'); if (U.back.focus) U.back.focus(); }, 16);
    refresh();
    if (!S.timer) S.timer = setInterval(() => { if (S.open && !(doc().hidden)) refresh(); }, 30000);
    return true;
  }

  function close() {
    if (!S.ui) return;
    S.open = false;
    S.ui.panel.classList.remove('is-open');
    if (doc().body && doc().body.classList) doc().body.classList.remove('bd-on');
    if (S.timer) { clearInterval(S.timer); S.timer = null; }
    setTimeout(() => { if (!S.open && S.ui) S.ui.panel.hidden = true; }, 380);
    if (S.back && S.back.focus) S.back.focus();
  }

  /* A turn in which CLIVE read the build queue for him opens the screen: never one that read it to
   * file a build (its parts asked for, or a filing proposed), and never over a card he must act on. */
  function shouldOpen(turn) {
    const t = turn && typeof turn === 'object' ? turn : {};
    const calls = list(t.tool_calls);
    const read = calls.some((c) => text(c.name) === 'engineering_status' && c.ok !== false
      && !/^true$/i.test(text(c.args && c.args.areas)));
    const filing = calls.some((c) => text(c.name) === 'submit_engineering_request' || c.proposal_id);
    const acting = list(t.ui).some((i) => text(i.type) === 'confirmation' || text(i.type) === 'batch_action');
    return read && !filing && !acting;
  }
  function fromTurn(turn) { return shouldOpen(turn) ? open() : false; }

  // The home's Builds row reads this (web/alpha.js): the counts and the line, as last read.
  async function brief() {
    try {
      const got = await getJson('/objectives/builds/board?brief=1');
      if (got.ok) S.brief = got.data;
    } catch (e) { /* the row keeps what it last said */ }
    return S.brief;
  }

  return {
    STAGES, ago, whenWords, stateLine, roadModel, drawRoad, findingNode, decisionNode, buildNode, draw,
    open, close, refresh, brief, briefNow: () => S.brief, fromTurn, shouldOpen, state: () => S,
  };
});
