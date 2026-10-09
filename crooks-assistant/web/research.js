/* The Builds screen's Research section: the research George gave CLIVE, what CLIVE learnt from it, and his answers.
 *
 * George's words (7 Oct 2026): "a way to actually accept this research into part of the Clive design
 * and philosophy". He approved: each recommendation becomes a proposal checked against the map's rules
 * (adopt, park or reject, with a reason), and he answers them on the Builds screen.
 *
 * Then (9 Oct 2026, DEC-078): "CLIVE should not accumulate research. CLIVE should learn from research."
 * and "George should not need to review 113 recommendations." Once a synthesis is live the server sends
 * `mode: "ideas"`: everything the research says about one thing is one idea, with four separate answers
 * (direction, already in CLIVE?, when, work approved?) instead of one verdict.
 *
 * Drawn inside the Builds screen (web/builds.js places it under the heading, after any builds that wait
 * on him) from GET /objectives/research (app/builds/research.py), as it comes. Two modes:
 *
 * Ideas (DEC-078), when a synthesis is live:
 *   - one line to add research, and what it takes, in the server's own words;
 *   - What your research says: its plain points, "If we build what it agrees on, CLIVE goes from … to …",
 *     and one line of counts made only from the numbers the server sent (a missing one is left out);
 *   - Needs you: each idea that waits on him, why it is there in the server's words, its question, its
 *     plain-English view and his three choices;
 *   - Now / Next / Later / No date: one compact row per idea (a dot from a fixed table on its direction,
 *     how many documents back it, how much it matters, and how far its work is once approved). Tapped:
 *     the plain-English view first, then the four answers, then a folded Engineering detail (sources and
 *     their own words, what argues against it, CLIVE's keys, where it is in the code, its history), then
 *     his choices. A tap picks one and a second tap on the button records it, bound to the idea exactly
 *     as drawn (its fingerprint). "Approve the work" prepares a build request: its card comes back to the
 *     conversation (window.CliveCards, web/app.js), the screen steps aside, and nothing is filed until he
 *     holds the card;
 *   - the documents given: how many recommendations each one gave, whether it is in the ideas yet, and
 *     what couldn't be placed, with why.
 *
 * Proposals (DEC-070), before any synthesis is live, exactly as before:
 *   - each document given, with a dot from a fixed table (blue while it waits or is read, steel once
 *     read, red when the safety scan stopped it or it could not be read) and why, in the server's words;
 *   - the recommendations, those waiting on him first: what the research says, its own words, CLIVE's
 *     view (adopt, park or reject) with the one-line reason and what it cites, what building it would
 *     touch, what it calls done, and the ideas or features it repeats. Three answers, CLIVE's marked as
 *     recommended; Adopt prepares a build request on a card exactly as Approve does above;
 *   - and, while CLIVE re-reads the research into ideas, one quiet line saying how far it has got.
 *
 * A refusal that comes back with the section (409: the idea moved on since he saw it) redraws the
 * section and says why where he answered, so the words are never lost with the old drawing.
 *
 * Every word from the server lands through textContent; no attribute is built from what it sent (only
 * this file's class names, chosen from fixed tables, with a neutral one for a key it doesn't know). No
 * dependency on the rest of the page beyond window.CliveBuilds (time in words, whether the screen is
 * open, closing it) and window.CliveCards, so it runs under Node against tests/web/dom-shim.js
 * (tests/web/research.test.js).
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveResearch = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const DOT = { queued: 'is-blue', reading: 'is-blue', done: 'is-steel', stopped: 'is-red', failed: 'is-red' };
  const STATES = Object.keys(DOT);
  const BUILD_STATES = ['filed', 'waiting', 'not_prepared', 'unknown', 'done', 'blocked'];
  const GROUP_OPEN = { waiting: true };
  const ACCEPT = '.pdf,.docx,.md,.markdown,.txt,.html,.htm,.json,.zip';

  // Ideas (DEC-078): fixed tables. A key not in one gets the neutral class or no words, never a guess.
  const JUDGMENT_DOT = { ADOPT: 'is-steel', ADOPT_PARTLY: 'is-steel', INVESTIGATE: 'is-dim', CONFLICT: 'is-amber', REJECT: 'is-red' };
  const NEUTRAL = 'is-none';
  const GROUP_ORDER = ['now', 'next', 'later', 'unscheduled'];
  const IDEA_GROUP_OPEN = { needs: true, now: true, next: true };
  const SYNTH_WORDS = { absorbed: 'Absorbed into the ideas', waiting: 'Waiting for the first synthesis', reading: 'Being read into the ideas', failed: 'Couldn’t be absorbed' };
  const SYNTH_DOT = { absorbed: 'is-steel', waiting: 'is-blue', reading: 'is-blue', failed: 'is-red' };
  const STANCE_WORDS = { supports: 'Supports it', opposes: 'Argues against it', refines: 'Refines it' };
  const CENTRALITY_WORDS = { central: 'central to the document', supporting: 'a supporting point', passing: 'said in passing' };
  const LEVEL_WORDS = { none: 'Not in CLIVE yet', partial: 'Partly in CLIVE', substantial: 'Mostly in CLIVE', complete: 'Already in CLIVE' };
  const RUN_STAGE_WORDS = { extract: 'reading the documents', match: 'matching recommendations to ideas', consolidate: 'merging repeats',
    judge: 'judging', summary: 'writing the summary' };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);
  const words = (v) => (Array.isArray(v) ? v.map(text).filter(Boolean) : []);
  const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : null);
  const has = (table, key) => Object.prototype.hasOwnProperty.call(table, key);
  const ago = (iso, now) => (root.CliveBuilds && typeof root.CliveBuilds.ago === 'function' ? root.CliveBuilds.ago(iso, now) : '');
  // A count the server sent, or null: never a zero it didn't send.
  const count = (v) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.round(v) : null);
  const many = (n, one, more) => `${n} ${n === 1 ? one : more}`;

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
  function statusLine(words_) {
    const said = el('p', 'bd-said', words_);
    said.setAttribute('role', 'status');
    return said;
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

  /* His answer, in two steps: a tap picks one, a second tap on the button records it. `how` says what is
   * asked and how it is sent; without it, a research proposal's three answers (Adopt, Park, Reject). */
  function decisionNode(p, on, how) {
    const handlers = on || {};
    const h = how || { choices: p.answers, ask: 'What should CLIVE do with it?', send: handlers.answer, busy: 'adopt' };
    const box = el('div', 'bd-decision');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Your answer');
    add(box, el('p', 'bd-q', h.ask));
    const name = `rs-q${++groupsDrawn}`;
    const answers = el('div', 'bd-answers');
    answers.setAttribute('role', 'radiogroup');
    let picked = null;
    let pickedLabel = '';
    const choose = button('btn primary bd-choose', 'Pick an answer');
    choose.disabled = true;
    const said = statusLine(h.said);
    for (const a of list(h.choices)) {
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
      if (!picked || typeof h.send !== 'function') return;
      choose.disabled = true;
      choose.textContent = picked === h.busy ? 'Preparing the build request…' : 'Recording…';
      said.textContent = '';
      const got = await h.send(p, picked);
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
      // Whatever CLIVE's view: Adopt files these as the build's acceptance criteria, so he sees them first.
      fact('Done when', words(p.done_when).join(' · ')),
      fact('Also recommended in', words(p.also_in).join(', ')));
    body.appendChild(p.chosen ? chosenNode(p, o) : decisionNode(p, o));
    item.appendChild(body);
    return item;
  }

  // ---------------------------------------------------------------- ideas (DEC-078): what the research says

  // One line of counts, made only from the numbers the server sent: a part without its number is left out.
  function countsLine(counts) {
    const c = obj(counts) || {};
    const [claims, docs, ideas] = [count(c.claims), count(c.documents), count(c.ideas)];
    const from = docs !== null ? ` from ${many(docs, 'document', 'documents')}` : '';
    let first = '';
    if (claims !== null && ideas !== null) first = `${many(claims, 'recommendation', 'recommendations')}${from} became ${many(ideas, 'idea', 'ideas')}.`;
    else if (ideas !== null) first = `${docs !== null ? many(docs, 'document', 'documents') : 'Your research'} became ${many(ideas, 'idea', 'ideas')}.`;
    else if (claims !== null) first = `${many(claims, 'recommendation', 'recommendations')} read${from}.`;
    else if (docs !== null) first = `${many(docs, 'document', 'documents')} read.`;
    const [converged, split, valid, changed, unplaced] = [count(c.converged), count(c.disagreements), count(c.validations), count(c.changes), count(c.unplaced)];
    const second = [converged !== null ? `${converged} ${converged === 1 ? 'is' : 'are'} backed by more than one report` : '',
      split !== null ? `${split} ${split === 1 ? 'has' : 'have'} disagreement` : ''].filter(Boolean).join('; ');
    const third = [valid !== null ? `${valid} confirm${valid === 1 ? 's' : ''} CLIVE’s direction` : '',
      changed !== null ? `${changed} change${changed === 1 ? 's' : ''} CLIVE’s understanding` : ''].filter(Boolean).join('; ');
    const fourth = unplaced ? `${many(unplaced, 'recommendation', 'recommendations')} couldn’t be placed.` : '';
    return [first, second ? `${second}.` : '', third ? `${third}.` : '', fourth].filter(Boolean).join(' ');
  }

  function saysNode(s, now) {
    const syn = obj(s);
    if (!syn) return null;
    const box = el('div', 'rs-says');
    add(box, el('h3', 'rs-h3 rs-h3s', 'What your research says'));
    const points = words(syn.points);
    if (points.length) {
      const ol = el('ol', 'rs-points bd-list');
      for (const point of points) ol.appendChild(el('li', 'rs-point', point));
      box.appendChild(ol);
    }
    // Where it takes CLIVE: from the line before to the line after, each as the server wrote it, so a
    // whole sentence ("CLIVE loses work…") and a fragment ("a pile of…") both read right.
    const fromTo = [['From', syn.before], ['To', syn.after]].filter(([, said]) => text(said));
    if (fromTo.length) {
      const ba = add(el('div', 'rs-ba'), el('p', 'rs-bahead', 'If we build what it agrees on, CLIVE goes'));
      for (const [label, said] of fromTo) add(ba, add(el('p', 'rs-baline'), el('span', 'rs-balabel', label), el('span', 'rs-baval', said)));
      box.appendChild(ba);
    }
    const line = countsLine(syn.counts);
    if (line) add(box, el('p', 'rs-counts', line));
    const when = ago(syn.at, now);
    if (when) add(box, el('p', 'rs-asof', `Brought together ${when}.`));
    return box.childNodes.length > 1 ? box : null;
  }

  // ---------------------------------------------------------------- one idea

  function answerOf(idea, key) {
    const a = obj(obj(idea.answers) && idea.answers[key]);
    return { key: a ? text(a.key) : '', words: a ? text(a.words) : '' };
  }
  const dotFor = (key) => (has(JUDGMENT_DOT, key) ? JUDGMENT_DOT[key] : NEUTRAL);

  function backedWords(idea) {
    const b = obj(idea.backed_by);
    if (!b) return '';
    const [n, of] = [count(b.count), count(b.of)];
    if (n === null) return '';
    return of !== null ? `Backed by ${n} of ${of}` : `Backed by ${many(n, 'document', 'documents')}`;
  }

  // The row: its name, a dot on its direction, how widely it is backed, how much it matters, its work once approved.
  function rowWords(idea) {
    const exec = answerOf(idea, 'execution');
    const mine = obj(idea.owner_answer);
    return [answerOf(idea, 'judgment').words, backedWords(idea), answerOf(idea, 'importance').words,
      exec.key && exec.key !== 'NOT_AUTHORISED' ? exec.words : '',
      mine && mine.current !== false && text(mine.label) ? `You: ${text(mine.label)}` : ''].filter(Boolean).join(' · ');
  }

  function chips(label, items) {
    const all = words(items);
    if (!all.length) return null;
    const row = el('div', 'rs-chips');
    for (const item of all) row.appendChild(el('span', 'rs-chip', item));
    return add(el('div', 'bd-fact'), el('p', 'bd-flabel', label), row);
  }

  // The plain-English view first. Without one, CLIVE's own statement and where it stands, said plainly.
  function viewNode(idea) {
    const v = obj(idea.owner_view);
    const box = el('div', 'rs-view');
    if (v) {
      add(box, fact('What it means', v.means), fact('Today', v.today), fact('After', v.after), fact('A real example', v.example),
        fact('Before → after', v.before_after), chips('Why you’d care', v.why_care), fact('When you’d notice', v.notice));
      if (box.childNodes.length) return box;
    }
    const today = obj(idea.today) || {};
    add(box, el('p', 'bd-muted', 'There is no plain-English view of this one yet, so this is CLIVE’s own statement of it.'),
      fact('What it is', idea.statement), fact('Today', today.says));
    return box;
  }

  function answerLine(label, said, why) {
    if (!text(said)) return null;
    const line = add(el('div', 'rs-aline'), el('span', 'rs-alabel', label), el('span', 'rs-aval', said));
    if (text(why)) add(line, el('span', 'rs-awhy', why));
    return line;
  }

  // The four answers, as four short lines; then how sure CLIVE is, how much it matters, what it does to what CLIVE knows.
  function answersNode(idea) {
    const reasons = obj(idea.reasons) || {};
    const held = list(idea.timing_held_by).map((k) => text(k.label) || text(k.key)).filter(Boolean);
    const when = [text(reasons.timing), held.length ? `Held by ${held.join(' and ')}.` : ''].filter(Boolean).join(' ');
    const box = add(el('div', 'rs-answers'),
      answerLine('Direction', answerOf(idea, 'judgment').words, reasons.judgment),
      answerLine('Already in CLIVE?', answerOf(idea, 'relationship').words),
      answerLine('When', answerOf(idea, 'timing').words, when),
      answerLine('Work approved?', answerOf(idea, 'execution').words));
    const [sure, weight, knows] = [answerOf(idea, 'confidence').words, answerOf(idea, 'importance').words, answerOf(idea, 'knowledge').words];
    const more = [sure ? `Confidence: ${sure}` : '', weight ? `Importance: ${weight}` : '', knows ? `CLIVE’s understanding: ${knows}` : ''].filter(Boolean).join(' · ');
    if (more) add(box, el('p', 'rs-amore', more));
    return box.childNodes.length ? box : null;
  }

  function day(iso, now) {
    const at = new Date(text(iso));
    if (!text(iso) || Number.isNaN(at.getTime())) return '';
    const ref = now instanceof Date ? now : new Date();
    return `${at.getDate()} ${MONTHS[at.getMonth()]}${at.getFullYear() !== ref.getFullYear() ? ` ${at.getFullYear()}` : ''}`;
  }

  function sourceNode(s) {
    const box = el('div', 'rs-source');
    add(box, el('p', 'rs-srcwhere', [text(s.document), text(s.section)].filter(Boolean).join(' · ')));
    if (text(s.quote)) add(box, el('p', 'rs-quote', `“${text(s.quote)}”`));
    const stance = has(STANCE_WORDS, text(s.stance)) ? STANCE_WORDS[text(s.stance)] : text(s.stance);
    const weight = has(CENTRALITY_WORDS, text(s.centrality)) ? CENTRALITY_WORDS[text(s.centrality)] : text(s.centrality);
    const meta = [stance, weight].filter(Boolean).join(', ');
    if (meta) add(box, el('p', 'rs-srcmeta', meta));
    return box;
  }

  // Out of the way: where it came from, what argues against it, the keys, the code, what would change CLIVE's view, its history.
  function detailNode(idea, now) {
    const more = el('details', 'bd-tech rs-tech');
    add(more, el('summary', 'bd-techsum', 'Engineering detail'));
    const tk = (label) => el('p', 'bd-tk', label);
    if (obj(idea.owner_view) && text(idea.statement)) add(more, tk('CLIVE’s statement of it'), el('p', 'bd-tv', idea.statement));
    const sources = list(idea.sources);
    if (sources.length) add(more, tk(`Sources (${sources.length})`), ...sources.map(sourceNode));
    const against = list(idea.against);
    if (against.length) add(more, tk('What argues against it'), ...against.map((a) => el('p', 'bd-tv', [text(a.document), text(a.says)].filter(Boolean).join(': '))));
    if (text(idea.how_they_differ)) add(more, tk('How the reports differ'), el('p', 'bd-tv', idea.how_they_differ));
    const keys = list(idea.keys);
    if (keys.length) add(more, tk('CLIVE’s keys'), ...keys.map((k) => el('p', 'bd-tv', [text(k.label) || text(k.key), text(k.how)].filter(Boolean).join(': '))));
    const today = obj(idea.today);
    if (today) {
      const level = has(LEVEL_WORDS, text(today.level)) ? LEVEL_WORDS[text(today.level)] : '';
      const where = words(today.where);
      const says = [level, text(today.says)].filter(Boolean).join('. ');
      if (says || where.length) {
        add(more, tk('Today'), says ? el('p', 'bd-tv', says) : null, ...where.map((w) => el('p', 'bd-tv is-code', w)));
        if (today.verified === false) add(more, el('p', 'rs-unchecked', 'Not checked against the code.'));
      }
    }
    if (text(idea.revisit)) add(more, tk('What would change CLIVE’s view'), el('p', 'bd-tv', idea.revisit));
    if (words(idea.effects).length) add(more, tk('What it does'), el('p', 'bd-tv', words(idea.effects).join(' · ')));
    const history = list(idea.history).filter((h) => text(h.said));
    if (history.length) {
      add(more, tk(`History (${history.length})`));
      for (const h of history) {
        const when = day(h.at, now);
        add(more, el('p', 'bd-tv rs-hline', when ? `${when}: ${text(h.said)}` : text(h.said)));
      }
    }
    return more.childNodes.length > 1 ? more : null;
  }

  function ideaDecision(idea, o, said) {
    return decisionNode(idea, o, { choices: idea.choices, ask: 'What should CLIVE do?', send: o.answerIdea, busy: 'go', said });
  }

  // His answer: what he chose and when; for "Approve the work", where its build request is.
  function ideaChosenNode(idea, o, note) {
    const mine = obj(idea.owner_answer);
    const box = el('div', 'bd-chosen');
    const when = ago(mine.at, o.now);
    const label = text(mine.label) || text(mine.key);
    const build = obj(idea.build);
    const choice = list(idea.choices).find((c) => text(c.key) === text(mine.key));
    add(box, el('p', 'bd-chose', `You chose ${label}${when ? `, ${when}` : ''}.`),
      build && text(build.words) ? null : el('p', 'bd-then', choice ? choice.then : ''));
    if (build && text(build.words)) add(box, el('p', `rs-build is-${BUILD_STATES.indexOf(text(build.state)) >= 0 ? text(build.state) : 'unknown'}`, build.words));
    const said = statusLine(note);
    if (text(mine.key) === 'go' && build && (build.state === 'waiting' || build.state === 'not_prepared')) {
      const again = button('bd-link', 'Prepare the build request again');
      again.addEventListener('click', async () => {
        if (typeof o.prepareIdea !== 'function') return;
        again.disabled = true;
        said.textContent = '';
        const got = await o.prepareIdea(idea);
        if (got && got.error) { said.textContent = got.error; again.disabled = false; }
      });
      box.appendChild(again);
    }
    const change = button('bd-link', 'Change your answer');
    change.addEventListener('click', () => {
      box.textContent = '';
      box.appendChild(ideaDecision(idea, o));
    });
    add(box, change, said);
    return box;
  }

  function choiceNode(idea, o, note) {
    const mine = obj(idea.owner_answer);
    if (!mine) return ideaDecision(idea, o, note);
    if (mine.current !== false) return ideaChosenNode(idea, o, note);
    // His answer was to an earlier view of this idea: said, and the choices offered again.
    const when = ago(mine.at, o.now);
    const box = el('div', 'rs-earlier');
    add(box, el('p', 'rs-earlierline', `You chose ${text(mine.label) || text(mine.key)}${when ? `, ${when}` : ''}: your answer to an earlier view. CLIVE’s view has changed since, so it asks again.`),
      ideaDecision(idea, o, note));
    return box;
  }

  function ideaNode(idea, on) {
    const o = on || {};
    const needs = o.needs ? obj(idea.needs_you) : null;
    const mine = obj(idea.owner_answer);
    const item = el('details', `rs-prop rs-idea is-${needs ? 'needs' : mine && mine.current !== false ? 'answered' : 'open'}`);
    const note = o.notice && !o.notice.shown && text(o.notice.id) === text(idea.id) ? o.notice : null;
    if (note) note.shown = true;
    if (o.openFirst || note) item.setAttribute('open', '');
    const sum = el('summary', 'rs-sum');
    add(sum, add(el('span', 'bd-head'), el('span', 'rs-title', text(idea.name) || text(idea.statement) || text(idea.id)), el('span', 'bd-chev')));
    const line = needs ? [text(needs.trigger_words), backedWords(idea)].filter(Boolean).join(' · ') : rowWords(idea);
    add(sum, add(el('span', 'bd-line'), el('span', `rs-dot ${dotFor(answerOf(idea, 'judgment').key)}`), el('span', 'rs-state', line)));
    item.appendChild(sum);
    const body = el('div', 'bd-body');
    // Why it is here is the row's own line, above; the body opens on the question it asks him.
    if (needs && text(needs.question)) add(body, add(el('div', 'rs-needs'), el('p', 'bd-q', needs.question)));
    add(body, viewNode(idea), answersNode(idea), detailNode(idea, o.now));
    body.appendChild(choiceNode(idea, o, note ? note.words : ''));
    item.appendChild(body);
    return item;
  }

  // ---------------------------------------------------------------- ideas: the documents given

  // How many recommendations it gave. None is said only once it is in the ideas: before that, none may mean not yet.
  function claimsWords(d) {
    const n = count(d.claims);
    if (n === null) return '';
    if (n) return `${many(n, 'recommendation', 'recommendations')} read`;
    return text(d.synthesis_state) === 'absorbed' ? 'No recommendations in it' : '';
  }

  function ideaDocumentNode(d, now) {
    const state = text(d.state);
    const synth = text(d.synthesis_state);
    const done = state === 'done';
    const row = el('details', `rs-doc is-${STATES.indexOf(state) >= 0 ? state : 'failed'}`);
    const sum = el('summary', 'rs-docsum');
    let dot = has(DOT, state) ? DOT[state] : 'is-red';
    if (done && synth) dot = has(SYNTH_DOT, synth) ? SYNTH_DOT[synth] : NEUTRAL;
    const when = ago(d.received_at, now);
    const line = [done ? claimsWords(d) : text(d.state_words), done && has(SYNTH_WORDS, synth) ? SYNTH_WORDS[synth] : '',
      when ? `given ${when}` : ''].filter(Boolean).join(' · ');
    add(sum, el('span', `rs-dot ${dot}`), add(el('span', 'rs-docwords'), el('span', 'rs-docname', text(d.name) || 'A research file'),
      el('span', 'rs-docline', line)), el('span', 'bd-chev'));
    row.appendChild(sum);
    const body = el('div', 'rs-docbody');
    if (text(d.why)) add(body, el('p', state === 'stopped' || state === 'failed' || synth === 'failed' ? 'rs-why is-bad' : 'rs-why', d.why));
    for (const note of words(d.notes)) add(body, el('p', 'bd-muted', note));
    const unplaced = list(d.unplaced);
    if (unplaced.length) {
      add(body, el('p', 'bd-flabel', `Couldn’t place (${unplaced.length})`));
      for (const item of unplaced) add(body, el('p', 'bd-muted', [text(item.title), text(item.why)].filter(Boolean).join(': ')));
    }
    if (!body.childNodes.length) add(body, el('p', 'bd-muted', done ? 'Nothing more to say about it.' : 'Nothing more is known yet.'));
    row.appendChild(body);
    return row;
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

  // While CLIVE re-reads the research into ideas (not live yet): how far it has got, from the run's own fields only.
  function runLine(synthesis, now) {
    const run = obj(obj(synthesis) && synthesis.run);
    if (!run) return null;
    const stage = text(run.stage);
    const pairs = [['done', 'of'], ['done', 'total'], ['documents_done', 'documents']];
    const pair = pairs.find(([a, b]) => count(run[a]) !== null && count(run[b]) !== null);
    const progress = pair ? `${count(run[pair[0]])} of ${count(run[pair[1]])}` : '';
    if (text(run.finished_at) && !(Array.isArray(run.errors) && run.errors.length)) {
      const when = ago(run.finished_at, now);
      return el('p', 'rs-run', `CLIVE has re-read your research into ideas${when ? ` (${when})` : ''}. They aren’t live yet.`);
    }
    const doing = [has(RUN_STAGE_WORDS, stage) ? RUN_STAGE_WORDS[stage] : '', progress].filter(Boolean).join(', ');
    return doing ? el('p', 'rs-run', `CLIVE is re-reading your research into ideas: ${doing}.`) : null;
  }

  function head(section, p) {
    // Its own heading class: the Builds screen's group headings (bd-h2) stay the builds' alone.
    add(section, el('h2', 'rs-h2', 'Research'), el('p', 'rs-summary', p.summary || ''));
  }

  function fill(section, payload, on) {
    const o = on || {};
    const p = payload && typeof payload === 'object' ? payload : {};
    while (section.childNodes.length) section.removeChild(section.childNodes[0]);
    if (p.mode === 'ideas') return fillIdeas(section, p, o);
    head(section, p);
    add(section, runLine(p.synthesis, o.now));
    if (text(p.problem)) add(section, el('p', 'bd-problem', p.problem));
    const notice = noticeNode(o);
    if (notice) section.appendChild(notice);
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
      const count_ = list(g.proposals).length;
      add(group, el('summary', 'rs-h3', `${text(g.title)} (${count_})`));
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

  // Words for an answer the server refused, when the idea it was about is no longer drawn: said under the heading.
  function noticeNode(o) {
    if (!o.notice || o.notice.shown || !text(o.notice.words)) return null;
    o.notice.shown = true;
    return statusLine(o.notice.words);
  }

  function ideaGroup(key, title, ideas, o, extra) {
    const group = el('details', `rs-group rs-igroup is-${key === 'needs' ? 'needs' : GROUP_ORDER.indexOf(key) >= 0 ? key : 'other'}`);
    if (IDEA_GROUP_OPEN[key]) group.setAttribute('open', '');
    add(group, el('summary', 'rs-h3', `${title} (${ideas.length})`));
    const rows = el('div', 'bd-list');
    ideas.forEach((idea, i) => {
      const node = ideaNode(idea, Object.assign({}, o, extra || {}, { openFirst: key === 'needs' && i === 0 }));
      if (Array.isArray(o.drawn)) o.drawn.push([node, text(idea.id)]);
      rows.appendChild(node);
    });
    group.appendChild(rows);
    if (Array.isArray(o.drawn)) o.drawn.push([group, `group:${key}`]);
    return group;
  }

  // Now, Next, Later, No date in that order; a group the server sent that this file doesn't know comes after.
  function orderedGroups(groups) {
    const rank = (g) => { const i = GROUP_ORDER.indexOf(text(g.key)); return i >= 0 ? i : GROUP_ORDER.length; };
    return list(groups).map((g, i) => [g, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([g]) => g);
  }

  function fillIdeas(section, p, o) {
    head(section, p);
    if (text(p.problem)) add(section, el('p', 'bd-problem', p.problem));
    const spot = el('div', 'rs-noticespot');
    section.appendChild(spot);
    section.appendChild(addNode(p, o));
    add(section, saysNode(p.synthesis, o.now));
    // What needs him first. An idea drawn there is not drawn again in its group.
    const needs = list(p.needs_you).filter((idea) => obj(idea.needs_you));
    const shown = new Set(needs.map((idea) => text(idea.id)));
    if (needs.length) section.appendChild(ideaGroup('needs', 'Needs you', needs, o, { needs: true }));
    for (const g of orderedGroups(p.groups)) {
      const ideas = list(g.ideas).filter((idea) => !shown.has(text(idea.id)));
      if (!ideas.length) continue;
      section.appendChild(ideaGroup(text(g.key), text(g.title) || text(g.key), ideas, o));
    }
    const docs = list(p.documents);
    if (docs.length) {
      const group = el('details', 'rs-group rs-igroup is-documents');
      // Folded once every document is in the ideas; open while one is being read, waits, or failed.
      const busy = docs.some((d) => text(d.state) !== 'done' || ['waiting', 'reading', 'failed'].indexOf(text(d.synthesis_state)) >= 0);
      if (busy) group.setAttribute('open', '');
      add(group, el('summary', 'rs-h3', `Documents (${docs.length})`));
      const all = el('div', 'bd-list rs-docs');
      for (const d of docs) all.appendChild(ideaDocumentNode(d, o.now));
      group.appendChild(all);
      if (Array.isArray(o.drawn)) o.drawn.push([group, 'group:documents']);
      section.appendChild(group);
    }
    const notice = noticeNode(o);
    if (notice) spot.appendChild(notice);
    else section.removeChild(spot);
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

  const S = { payload: null, node: null, at: 0, timer: null, opened: new Map(), drawn: [], notice: null };

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
      // The idea a refusal was about stays open, so its words are seen.
      if (S.notice && text(S.notice.id)) S.opened.set(text(S.notice.id), true);
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
    const notice = S.notice ? Object.assign({}, S.notice, { shown: false }) : null;
    return { answer, prepare, upload, answerIdea, prepareIdea, now: new Date(), drawn: S.drawn, notice };
  }

  // A staged build request's card goes to the conversation, and the screen steps aside for it.
  function showCard(staged) {
    if (!staged || !staged.ok) return false;
    const shown = Boolean(root.CliveCards && typeof root.CliveCards.show === 'function' && root.CliveCards.show(staged));
    if (shown && root.CliveBuilds && typeof root.CliveBuilds.close === 'function') root.CliveBuilds.close();
    return shown;
  }

  // The section the server sent back, drawn; with words to say where he answered, when there are any.
  function redraw(section, id, words_) {
    S.payload = section;
    S.notice = text(words_) ? { id: text(id), words: text(words_) } : null;
    render();
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
    const why = text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was recorded.`;
    if (got.status === 409 && got.data && got.data.section) redraw(got.data.section, p.id, why);
    return { error: why };
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

  // His answer to one idea, bound to the fingerprint of the idea as drawn. "go" may come back with a card.
  async function answerIdea(idea, key) {
    let got;
    try {
      got = await post('/objectives/research/idea/answer', { idea_id: text(idea.id), fingerprint: text(idea.fingerprint), answer: key, session_id: sessionId() });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so nothing was recorded.' };
    }
    if (got.ok && got.data && got.data.section) {
      const staged = got.data.staged;
      const failed = key === 'go' && staged && !staged.ok ? `Approved. ${text(staged.detail)}`.trim() : '';
      redraw(got.data.section, idea.id, failed);
      if (staged && staged.ok) showCard(staged);
      return failed ? { error: failed } : { ok: true };
    }
    const why = text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was recorded.`;
    if (got.status === 409 && got.data && got.data.section) redraw(got.data.section, idea.id, why);
    return { error: why };
  }

  async function prepareIdea(idea) {
    let got;
    try {
      got = await post('/objectives/research/idea/prepare', { idea_id: text(idea.id), session_id: sessionId() });
    } catch (e) {
      return { error: 'CLIVE could not be reached, so nothing was prepared.' };
    }
    if (got.ok && got.data) {
      const staged = got.data.staged;
      const failed = staged && staged.ok ? '' : text(staged && staged.detail) || 'Nothing was prepared.';
      if (got.data.section) redraw(got.data.section, idea.id, failed);
      if (staged && staged.ok) { showCard(staged); return { ok: true }; }
      return { error: failed };
    }
    const why = text(got.data && got.data.detail) || `CLIVE answered ${got.status}, so nothing was prepared.`;
    if (got.status === 409 && got.data && got.data.section) redraw(got.data.section, idea.id, why);
    return { error: why };
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
    S.notice = null;
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

  return { draw, documentNode, proposalNode, decisionNode, chosenNode, ideaNode, ideaDocumentNode, countsLine, runLine,
    JUDGMENT_DOT, place, refresh, answer, prepare, answerIdea, prepareIdea, upload, state: () => S };
});
