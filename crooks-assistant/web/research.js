/* The Builds screen's Research section: the research George gave CLIVE, and his answer to each recommendation.
 *
 * George's words (7 Oct 2026): "a way to actually accept this research into part of the Clive design
 * and philosophy". He approved: each recommendation becomes a proposal checked against the map's rules
 * (adopt, park or reject, with a reason), and he answers them on the Builds screen.
 *
 * Drawn inside the Builds screen (web/builds.js places it under the heading, after any builds that wait
 * on him) from GET
 * /objectives/research (app/builds/research.py), as it comes:
 *   - one line to add research (a file: PDF, Word, Markdown, text, a saved page or a ChatGPT export),
 *     and what it takes, in the server's own words;
 *   - each document given, with a dot from a fixed table (blue while it waits or is read, steel once
 *     read, red when the safety scan stopped it or it could not be read) and why, in the server's words;
 *   - the recommendations, those waiting on him first: what the research says, its own words, CLIVE's
 *     view (adopt, park or reject) with the one-line reason and what it cites, what building it would
 *     touch, and the ideas or features it repeats. Three answers, CLIVE's marked as recommended; a tap
 *     picks one and a second tap on the button records it, bound to the proposal exactly as drawn.
 *   - Adopt prepares a build request: the card comes back to the conversation (window.CliveCards,
 *     web/app.js), the screen steps aside, and nothing is filed until he holds the card.
 *
 * Every word from the Mac lands through textContent; no attribute is built from what the Mac sent
 * (only this file's class names). No dependency on the rest of the page beyond window.CliveBuilds
 * (time in words, whether the screen is open, closing it) and window.CliveCards, so it runs under Node
 * against tests/web/dom-shim.js (tests/web/research.test.js).
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveResearch = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const DOT = { queued: 'is-blue', reading: 'is-blue', done: 'is-steel', stopped: 'is-red', failed: 'is-red' };
  const STATES = Object.keys(DOT);
  const BUILD_STATES = ['filed', 'waiting', 'not_prepared', 'unknown'];
  const GROUP_OPEN = { waiting: true };
  const ACCEPT = '.pdf,.docx,.md,.markdown,.txt,.html,.htm,.json,.zip';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);
  const words = (v) => (Array.isArray(v) ? v.map(text).filter(Boolean) : []);
  const ago = (iso, now) => (root.CliveBuilds && typeof root.CliveBuilds.ago === 'function' ? root.CliveBuilds.ago(iso, now) : '');

  function el(tag, cls, said) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (said !== undefined && said !== null && said !== '') node.textContent = text(said);
    return node;
  }
  function add(parent, ...kids) {
    for (const kid of kids) if (kid) parent.appendChild(kid);
    return parent;
  }
  function fact(label, said) {
    if (!text(said)) return null;
    return add(el('div', 'bd-fact'), el('p', 'bd-flabel', label), el('p', 'bd-ftext', said));
  }
  function button(cls, said) {
    const b = el('button', cls, said);
    b.type = 'button';
    return b;
  }

  // ---------------------------------------------------------------- a document given

  function documentNode(d, now) {
    const state = text(d.state);
    const row = el('details', `rs-doc is-${STATES.indexOf(state) >= 0 ? state : 'failed'}`);
    const sum = el('summary', 'rs-docsum');
    const dot = el('span', `rs-dot ${Object.prototype.hasOwnProperty.call(DOT, state) ? DOT[state] : 'is-red'}`);
    const when = ago(d.received_at, now);
    const line = [text(d.state_words), state === 'done' ? countWords(d) : '', when ? `given ${when}` : ''].filter(Boolean).join(' · ');
    const words_ = add(el('span', 'rs-docwords'), el('span', 'rs-docname', text(d.name) || 'A research file'), el('span', 'rs-docline', line));
    add(sum, dot, words_, el('span', 'bd-chev'));
    row.appendChild(sum);
    const body = el('div', 'rs-docbody');
    if (text(d.why)) add(body, el('p', state === 'stopped' || state === 'failed' ? 'rs-why is-bad' : 'rs-why', d.why));
    for (const note of words(d.notes)) add(body, el('p', 'bd-muted', note));
    const dropped = list(d.dropped);
    if (dropped.length) {
      add(body, el('p', 'bd-flabel', `Left out (${dropped.length})`));
      for (const item of dropped) add(body, el('p', 'bd-muted', `${text(item.title)}: ${text(item.why)}`));
    }
    if (Number(d.repeated) > 0) add(body, el('p', 'bd-muted', `${Number(d.repeated)} of its recommendations repeat earlier research and are shown there.`));
    if (text(d.model)) add(body, el('p', 'bd-muted', `Weighed by ${d.model === 'max-plan' ? 'Claude on your Max plan' : text(d.model)}.`));
    if (!body.childNodes.length) add(body, el('p', 'bd-muted', state === 'done' ? 'Nothing more to say about it.' : 'Nothing more is known yet.'));
    row.appendChild(body);
    return row;
  }

  function countWords(d) {
    const n = Number(d.proposals) || 0;
    if (text(d.repeat_of)) return `the same file as “${text(d.repeat_of)}”`;
    return n ? `${n} recommendation${n === 1 ? '' : 's'}` : 'nothing concrete to build';
  }

  // ---------------------------------------------------------------- one recommendation

  let groupsDrawn = 0;

  function citeWords(items) {
    return list(items).map((c) => `${text(c.label)}${text(c.status) ? ` (${text(c.status)})` : ''}`).join('; ');
  }

  function decisionNode(p, on) {
    const handlers = on || {};
    const box = el('div', 'bd-decision');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Your answer');
    add(box, el('p', 'bd-q', 'What should CLIVE do with it?'));
    const name = `rs-q${++groupsDrawn}`;
    const answers = el('div', 'bd-answers');
    answers.setAttribute('role', 'radiogroup');
    let picked = null;
    let pickedLabel = '';
    const choose = button('btn primary bd-choose', 'Pick an answer');
    choose.disabled = true;
    const said = el('p', 'bd-said');
    said.setAttribute('role', 'status');
    for (const a of list(p.answers)) {
      const row = el('label', `bd-ans${a.recommended ? ' is-recommended' : ''}`);
      const input = el('input', 'bd-radio');
      input.type = 'radio';
      input.name = name;
      const top = add(el('span', 'bd-anshead'), el('span', 'bd-anslabel', a.label), a.recommended ? el('span', 'bd-rec', 'CLIVE recommends') : null);
      add(row, input, el('span', 'bd-dot'), add(el('span', 'bd-anstext'), top, el('span', 'bd-then', a.then)));
      const pick = () => {
        picked = text(a.key);
        pickedLabel = text(a.label);
        for (const other of answers.children) other.classList.remove('is-picked');
        row.classList.add('is-picked');
        input.checked = true;
        choose.disabled = false;
        choose.textContent = `Choose: ${pickedLabel}`;
      };
      input.addEventListener('change', pick);
      row.addEventListener('click', (event) => { if (!event || event.target !== input) pick(); });
      answers.appendChild(row);
    }
    box.appendChild(answers);
    choose.addEventListener('click', async () => {
      if (!picked || typeof handlers.answer !== 'function') return;
      choose.disabled = true;
      choose.textContent = picked === 'adopt' ? 'Preparing the build request…' : 'Recording…';
      said.textContent = '';
      const got = await handlers.answer(p, picked);
      if (got && got.error) {
        said.textContent = got.error;
        choose.disabled = false;
        choose.textContent = `Choose: ${pickedLabel}`;
      }
    });
    add(box, choose, said);
    return box;
  }

  function chosenNode(p, on) {
    const o = on || {};
    const c = p.chosen;
    const box = el('div', 'bd-chosen');
    const when = ago(c.decided_at, o.now);
    const build = p.build && typeof p.build === 'object' ? p.build : null;
    // Where an adopted one's build request is says more than what Adopt means, so it says that instead.
    add(box, el('p', 'bd-chose', `You chose ${text(c.label)}${when ? `, ${when}` : ''}.`), build && text(build.words) ? null : el('p', 'bd-then', c.then));
    if (build && text(build.words)) add(box, el('p', `rs-build is-${BUILD_STATES.indexOf(text(build.state)) >= 0 ? text(build.state) : 'unknown'}`, build.words));
    const said = el('p', 'bd-said');
    said.setAttribute('role', 'status');
    if (build && (build.state === 'waiting' || build.state === 'not_prepared')) {
      const again = button('bd-link', 'Prepare the build request again');
      again.addEventListener('click', async () => {
        if (typeof o.prepare !== 'function') return;
        again.disabled = true;
        said.textContent = '';
        const got = await o.prepare(p);
        if (got && got.error) { said.textContent = got.error; again.disabled = false; }
      });
      box.appendChild(again);
    }
    const change = button('bd-link', 'Change your answer');
    change.addEventListener('click', () => {
      box.textContent = '';
      box.appendChild(decisionNode(p, o));
    });
    add(box, change, said);
    return box;
  }

  function proposalNode(p, on) {
    const o = on || {};
    const item = el('details', `rs-prop is-${p.chosen ? 'answered' : 'waiting'}`);
    if (!p.chosen && o.openFirst) item.setAttribute('open', '');
    const sum = el('summary', 'rs-sum');
    add(sum, add(el('span', 'bd-head'), el('span', 'rs-title', p.title), el('span', 'bd-chev')));
    const view = `CLIVE: ${text(p.verdict_words).toLowerCase()}`;
    const line = add(el('span', 'bd-line'), p.chosen ? null : el('span', 'rs-dot is-blue'),
      el('span', 'rs-state', [p.chosen ? `You: ${text(p.chosen.after || p.chosen.label).toLowerCase()}` : view, p.chosen ? view : '',
        text(p.document) ? `from ${text(p.document)}` : ''].filter(Boolean).join(' · ')));
    add(sum, line);
    item.appendChild(sum);
    const body = el('div', 'bd-body');
    add(body,
      fact('What the research recommends', p.says),
      text(p.quote) ? add(el('div', 'bd-fact'), el('p', 'bd-flabel', 'In its words'), el('p', 'rs-quote', `“${text(p.quote)}”`)) : null,
      fact(`CLIVE’s view: ${text(p.verdict_words)}`, p.reason),
      p.checked_by === 'rule' ? el('p', 'bd-muted', 'Set by CLIVE’s own check of the map’s rules, not by the model.') : null,
      fact('It rests on', citeWords(p.cites)),
      fact('Already written down', citeWords(p.same_as)),
      fact('Building it would touch', words(p.touches).join(', ')),
      fact('It would also need', words(p.protected).length ? `${words(p.protected).join(', ')}: protected, so builds from CLIVE can’t change them` : ''),
      p.verdict === 'reject' ? null : fact('Done when', words(p.done_when).join(' · ')),
      fact('Also recommended in', words(p.also_in).join(', ')));
    body.appendChild(p.chosen ? chosenNode(p, o) : decisionNode(p, o));
    item.appendChild(body);
    return item;
  }

  // ---------------------------------------------------------------- the section

  function addNode(payload, on) {
    const o = on || {};
    const box = el('div', 'rs-add');
    const input = el('input', 'rs-file');
    input.type = 'file';
    input.accept = ACCEPT;
    input.setAttribute('aria-hidden', 'true');
    input.tabIndex = -1;
    const pick = button('rs-addbtn', 'Add research');
    const said = el('p', 'bd-said');
    said.setAttribute('role', 'status');
    pick.addEventListener('click', () => { if (typeof input.click === 'function') input.click(); });
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file || typeof o.upload !== 'function') return;
      pick.disabled = true;
      pick.textContent = 'Taking it in…';
      said.textContent = '';
      const got = await o.upload(file);
      pick.disabled = false;
      pick.textContent = 'Add research';
      input.value = '';
      if (got && got.error) said.textContent = got.error;
    });
    add(box, pick, input, el('p', 'rs-accepts', text(payload.accepts) ? `It reads ${text(payload.accepts)}. Or put files in the research folder on the server.` : ''), said);
    return box;
  }

  function fill(section, payload, on) {
    const o = on || {};
    const p = payload && typeof payload === 'object' ? payload : {};
    while (section.childNodes.length) section.removeChild(section.childNodes[0]);
    // Its own heading class: the Builds screen's group headings (bd-h2) stay the builds' alone.
    add(section, el('h2', 'rs-h2', 'Research'), el('p', 'rs-summary', p.summary || ''));
    if (text(p.problem)) add(section, el('p', 'bd-problem', p.problem));
    section.appendChild(addNode(p, o));
    const docs = list(p.documents);
    if (docs.length) {
      const all = el('div', 'bd-list rs-docs');
      for (const d of docs) all.appendChild(documentNode(d, o.now));
      section.appendChild(all);
    }
    for (const g of list(p.groups)) {
      const group = el('details', 'rs-group');
      if (GROUP_OPEN[text(g.key)]) group.setAttribute('open', '');
      const count = list(g.proposals).length;
      add(group, el('summary', 'rs-h3', `${text(g.title)} (${count})`));
      const rows = el('div', 'bd-list');
      list(g.proposals).forEach((prop, i) => {
        const node = proposalNode(prop, Object.assign({}, o, { openFirst: g.key === 'waiting' && i === 0 }));
        if (Array.isArray(o.drawn)) o.drawn.push([node, text(prop.id)]);
        rows.appendChild(node);
      });
      group.appendChild(rows);
      section.appendChild(group);
    }
    return section;
  }

  function draw(payload, on) {
    // A region, not a <section>: the Builds screen's own groups are its sections, and stay its only ones.
    const section = el('div', 'rs');
    section.setAttribute('role', 'region');
    section.setAttribute('aria-label', 'Research');
    return fill(section, payload, on);
  }

  // ---------------------------------------------------------------- on the page

  const S = { payload: null, node: null, at: 0, timer: null, opened: new Map(), drawn: [] };

  async function call(path, init) {
    const f = typeof fetch === 'function' ? fetch : globalThis.fetch;
    const response = await f(path, Object.assign({ cache: 'no-store' }, init || {}));
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }
  const post = (path, body) => call(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function sessionId() {
    try { return text(globalThis.localStorage && globalThis.localStorage.getItem('crooks.session')); } catch (e) { return ''; }
  }
  const isOpen = () => Boolean(root.CliveBuilds && typeof root.CliveBuilds.state === 'function' && root.CliveBuilds.state().open);

  function render() {
    if (!S.node) S.node = draw(S.payload || { summary: 'Reading your research…' }, handlers());
    else {
      for (const [node, key] of S.drawn) S.opened.set(key, Boolean(node.open));
      S.drawn = [];
      fill(S.node, S.payload || { summary: 'Reading your research…' }, handlers());
    }
    for (const [node, key] of S.drawn) {
      if (!S.opened.has(key)) continue;
      if (S.opened.get(key)) node.setAttribute('open', '');
      else if (node.removeAttribute) node.removeAttribute('open');
    }
    return S.node;
  }

  function handlers() {
    S.drawn = [];
    return { answer, prepare, upload, now: new Date(), drawn: S.drawn };
  }

  // A staged build request's card goes to the conversation, and the screen steps aside for it.
  function showCard(staged) {
    if (!staged || !staged.ok) return false;
    const shown = Boolean(root.CliveCards && typeof root.CliveCards.show === 'function' && root.CliveCards.show(staged));
    if (shown && root.CliveBuilds && typeof root.CliveBuilds.close === 'function') root.CliveBuilds.close();
    return shown;
  }

  async function answer(p, key) {
    let got;
    try {
      got = await post('/objectives/research/answer', { proposal_id: text(p.id), fingerprint: text(p.fingerprint), answer: key, session_id: sessionId() });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so nothing was recorded.' };
    }
    if (got.ok && got.data && got.data.section) {
      S.payload = got.data.section;
      render();
      const staged = got.data.staged;
      if (key === 'adopt' && staged && !staged.ok) return { error: `Adopted. ${text(staged.detail)}` };
      if (staged && staged.ok) showCard(staged);
      return { ok: true };
    }
    if (got.status === 409 && got.data && got.data.section) { S.payload = got.data.section; render(); }
    return { error: text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was recorded.` };
  }

  async function prepare(p) {
    let got;
    try {
      got = await post('/objectives/research/prepare', { proposal_id: text(p.id), session_id: sessionId() });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so nothing was prepared.' };
    }
    if (got.ok && got.data) {
      if (got.data.section) { S.payload = got.data.section; render(); }
      const staged = got.data.staged;
      if (staged && staged.ok) { showCard(staged); return { ok: true }; }
      return { error: text(staged && staged.detail) || 'Nothing was prepared.' };
    }
    return { error: text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was prepared.` };
  }

  async function upload(file) {
    const form = new FormData();
    form.append('file', file, file.name);
    let got;
    try {
      got = await call('/objectives/research/upload', { method: 'POST', body: form });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so the file was not taken in.' };
    }
    if (got.ok && got.data && got.data.section) {
      S.payload = got.data.section;
      render();
      soon();
      return { ok: true };
    }
    return { error: text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so the file was not taken in.` };
  }

  async function refresh() {
    try {
      const got = await call('/objectives/research');
      S.payload = got.ok ? got.data : { summary: text(got.data && got.data.detail) || `Your research could not be read (CLIVE answered ${got.status}).` };
    } catch (e) {
      S.payload = { summary: 'CLIVE could not be reached, so your research could not be read.' };
    }
    S.at = Date.now();
    render();
    soon();
    return S.payload;
  }

  // While a document is being read, look again every few seconds, as long as the screen is open.
  function soon() {
    if (S.timer) { clearTimeout(S.timer); S.timer = null; }
    if (!S.payload || !(Number(S.payload.reading) > 0)) return;
    S.timer = setTimeout(() => { S.timer = null; if (isOpen()) refresh(); }, 4000);
  }

  /* web/builds.js calls this on every draw: the section goes under the heading (after the builds that wait
   * on him, when any do), and is read again when it is older than the screen's own refresh. */
  function place(host) {
    if (!host) return null;
    const node = S.node || render();
    // Under the heading, or after the builds that wait on him when there are any: what needs him first.
    const needs = host.querySelector ? host.querySelector('.is-needs-you') : null;
    const hello = host.querySelector ? host.querySelector('.bd-hello') : null;
    const anchor = needs && needs.parentNode === host ? needs : hello && hello.parentNode === host ? hello : null;
    const after = anchor ? anchor.nextSibling : host.firstChild;
    if (node.parentNode !== host) {
      if (after) host.insertBefore(node, after); else host.appendChild(node);
    }
    if (!S.at || Date.now() - S.at > 25000) { S.at = Date.now(); refresh(); }
    return node;
  }

  return { draw, documentNode, proposalNode, decisionNode, chosenNode, place, refresh, answer, prepare, upload, state: () => S };
});
