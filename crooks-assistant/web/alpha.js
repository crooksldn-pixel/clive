/* CLIVE mobile alpha: the attention home, objectives, support, and a typed composer.
 *
 * Everything here is drawn from the Mac's own records (GET /objectives, POST /support/investigate)
 * and every typed question goes through the app's ordinary turn (window.CliveAlpha.ask). Nothing
 * here can send, book, pay or change an order: the only writes are the owner's own answers,
 * approvals and notes on an objective, which is CLIVE's own record.
 *
 * Data is only ever inserted as text (textContent), never as HTML.
 */
'use strict';

(function cliveAlpha() {
  const $ = (id) => document.getElementById(id);
  const h = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return node;
  };

  async function api(path, body) {
    const response = await fetch(path, body === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `The server answered ${response.status}.`);
    return data;
  }

  // ------------------------------------------------------------------ layout
  document.body.classList.add('alpha');
  const home = h('section', { id: 'alpha-home', class: 'alpha-home', 'aria-label': 'What needs your attention' });
  const footer = document.querySelector('.bottom');
  footer.parentNode.insertBefore(home, footer);

  // Icons are drawn as stroke paths, sized by the stylesheet, never as text glyphs.
  const NS = 'http://www.w3.org/2000/svg';
  function icon(paths, size = 20) {
    const node = document.createElementNS(NS, 'svg');
    node.setAttribute('viewBox', '0 0 24 24');
    node.setAttribute('width', String(size));
    node.setAttribute('height', String(size));
    node.setAttribute('aria-hidden', 'true');
    node.setAttribute('class', 'alpha-icon');
    for (const d of paths) {
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', d);
      node.append(path);
    }
    return node;
  }
  const ICON = {
    wave: ['M4 10v4', 'M8 7v10', 'M12 4v16', 'M16 7v10', 'M20 10v4'],
    up: ['M12 19V5', 'm5 12 7-7 7 7'],
    close: ['M6 6l12 12', 'M18 6 6 18'],
    chev: ['m9 6 6 6-6 6'],
    ask: ['M4 5h16v11H10l-5 4v-4H4z', 'M8 9.5h8', 'M8 12.5h5'],
    wait: ['M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18', 'M12 7v5l3 2'],
    search: ['M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14', 'm20 20-4-4'],
    plus: ['M12 5v14', 'M5 12h14'],
    tick: ['m5 12.5 4.5 4.5L19 7.5'],
    build: ['m4 20 9-9', 'M11 5.5 14.5 2l7.5 7.5-3.5 3.5z'],
    plug: ['M9 3v5', 'M15 3v5', 'M7 8h10v3a5 5 0 0 1-10 0z', 'M12 16v5'],
  };

  // The one bar. A tap opens the keyboard (here); a hold is the microphone, and that is decided
  // in app.js (its ask bar section), the only file that reaches it. The bar's faces follow the
  // stage's own state through the stylesheet, so an orb hold lights the bar the same way.
  // ---- live words and the real waveform: app.js fills #ask-words, draws #ask-wave from the
  // microphone's own level (web/live-voice.js) and puts what was heard in #ask-heard. Empty until
  // then, and they stay empty when there is nothing real to put in them. `data-spoken` keeps the
  // words out of a copy of the screen (web/telemetry.js), as a typed field's are.
  const bar = h('button', { id: 'ask-bar', class: 'ask-bar', type: 'button', 'aria-label': 'Ask CLIVE. Tap to type, hold to speak.' },
    h('span', { class: 'ask-face ask-idle' }, h('span', { class: 'ask-text', text: 'Ask CLIVE' }), h('span', { class: 'ask-voice' }, icon(ICON.wave))),
    h('span', { class: 'ask-face ask-listen' },
      h('span', { class: 'ask-head' }, h('span', { class: 'ask-dot' }), 'Listening'),
      h('span', { class: 'ask-words-frame', 'aria-hidden': 'true' }, h('span', { id: 'ask-words', class: 'ask-words', 'data-spoken': true })),
      h('canvas', { id: 'ask-wave', class: 'ask-wave', 'aria-hidden': 'true' }),
      h('span', { class: 'ask-hint', text: 'Release to send · slide away to cancel' })),
    h('span', { class: 'ask-face ask-drop', text: 'Release to cancel' }),
    h('span', { class: 'ask-face ask-busy' },
      h('span', { id: 'ask-heard', class: 'ask-heard', 'data-spoken': true }),
      h('span', { class: 'ask-busy-text', text: 'Working on it' })));
  const input = h('input', { id: 'alpha-input', class: 'alpha-input', type: 'text', placeholder: 'Ask CLIVE…',
    autocomplete: 'off', enterkeyhint: 'send', 'aria-label': 'Ask CLIVE' });
  const send = h('button', { class: 'alpha-send', type: 'submit', 'aria-label': 'Send', 'data-alpha': 'send' }, icon(ICON.up, 18));
  const stopTyping = h('button', { class: 'alpha-close', type: 'button', 'aria-label': 'Stop typing', onclick: () => closeTyping() }, icon(ICON.close, 16));
  const typeRow = h('div', { class: 'alpha-typerow' }, stopTyping, input, send);
  typeRow.inert = true;
  const composer = h('form', { id: 'alpha-composer', class: 'alpha-composer' }, bar, typeRow);
  document.getElementById('app').append(composer);
  function openTyping() {
    typeRow.inert = false;
    composer.classList.add('is-typing');
    input.focus();
  }
  function closeTyping() {
    composer.classList.remove('is-typing');
    typeRow.inert = true;
    input.blur();
  }
  bar.addEventListener('click', openTyping);
  bar.addEventListener('contextmenu', (event) => event.preventDefault());   // a long press is a question, not a menu
  input.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeTyping(); });
  // Tapping away from an empty field puts the bar back; a half-written question stays open.
  input.addEventListener('blur', () => {
    setTimeout(() => { if (!input.value.trim() && document.activeElement !== input) closeTyping(); }, 160);
  });
  composer.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || !window.CliveAlpha) return;
    if (window.CliveAlpha.isBusy()) { flash('CLIVE is still answering; one moment.'); return; }
    input.value = '';
    closeTyping();
    closeSheet();
    await window.CliveAlpha.ask(text);
    refresh();
    setTimeout(refresh, 2500);  // a turn's objective notes can land just after its answer
  });

  const sheet = h('dialog', { id: 'alpha-sheet', class: 'sheet alpha-sheet', 'aria-label': 'Details' });
  document.body.append(sheet);
  sheet.addEventListener('click', (event) => { if (event.target === sheet) closeSheet(); });
  // Which sheet the owner asked for last. Opening any sheet, or putting it away, takes the next
  // number; an answer from the Mac for a sheet asked for before that is never drawn (round 13,
  // W2-03). Mark done acts on the objective its sheet was drawn from, so that sheet must be the
  // one he tapped last, whatever order the answers come back in.
  let sheetSeq = 0;
  function openSheet(...kids) {
    sheet.replaceChildren(h('div', { class: 'sheet-grip', 'aria-hidden': 'true' }), h('div', { class: 'sheet-scroll alpha-scroll' }, ...kids.filter(Boolean)));
    if (!sheet.open) sheet.showModal();
  }
  function closeSheet() {
    sheetSeq += 1;
    if (sheet.open) sheet.close();
  }
  function head(title, sub) {
    return h('div', { class: 'alpha-sheet-head' },
      h('div', {}, h('h2', { text: title }), sub ? h('p', { class: 'alpha-muted', text: sub }) : null),
      h('button', { class: 'btn primary', type: 'button', text: 'Done', 'data-alpha': 'done', onclick: closeSheet }));
  }
  function flash(text) {
    const note = h('p', { class: 'alpha-flash', role: 'status', text });
    home.prepend(note);
    setTimeout(() => note.remove(), 4000);
  }

  // ------------------------------------------------------------------ home
  let objectives = [];
  // Build objectives' engineering requests, in the loop's own words (GET /objectives/builds,
  // read from the loop's published status at most once a minute). Drawn when they arrive.
  let builds = {};
  // What CLIVE cannot do yet (GET /objectives/gaps): each gap, how often it came up and what
  // became of it. Drawn when it arrives; the home does not wait for it.
  let gaps = { gaps: [], summary: {} };
  async function refresh() {
    let needsYou = 0;
    try {
      // With this page's conversation, so each objective listed is one it has been shown: held, it
      // can be put on a screen (web/lift.js, app/displays/put.py).
      const conversation = window.CliveAlpha && window.CliveAlpha.sessionId ? window.CliveAlpha.sessionId() : '';
      const data = await api(conversation ? `/objectives?session_id=${encodeURIComponent(conversation)}` : '/objectives');
      objectives = data.objectives || [];
      needsYou = data.needs_you || 0;
      renderHome(needsYou);
    } catch (err) {
      renderHome(0, String(err.message || err));
      return;
    }
    try {
      gaps = await api('/objectives/gaps');
      if (objectives.some((o) => o.kind === 'build' && (o.engineering || []).length)) {
        builds = (await api('/objectives/builds')).builds || {};
      }
      renderHome(needsYou);
    } catch { /* the rows already say what the objectives say */ }
  }
  const BUILD_WORDS = { queued: 'Build queued', building: 'Being built', 'in review': 'Being reviewed',
    done: 'Built · ready for you to merge', blocked: 'Build blocked', 'needs the owner': 'The build needs you' };
  function buildLine(o) {
    const rows = builds[o.id] || [];
    const last = rows[rows.length - 1];
    if (last) return BUILD_WORDS[last.progress] || last.progress;
    return (o.engineering || []).length ? 'Filed with the builders' : '';
  }

  const OWNER = 'George';
  let firstRender = true;
  function whenFor(o) {
    if (o.attention === 'done') return 'Done';
    if (o.days_left == null) return null;
    return o.days_left < 0 ? 'past the date' : o.days_left === 0 ? 'today' : `${o.days_left} day${o.days_left === 1 ? '' : 's'} left`;
  }
  function rowMain(title, sub, meta) {
    return h('span', { class: 'alpha-row-main' },
      h('span', { class: 'alpha-row-title', text: title }),
      sub || meta ? h('span', { class: 'alpha-row-sub' },
        meta ? h('span', { class: 'alpha-row-meta', text: meta }) : null,
        meta && sub ? ' · ' : null,
        sub || null) : null);
  }

  const GAP_STAGE = { open: 'no build yet', proposed: 'build proposed', filed: 'build filed', building: 'being built',
    built: 'built, not merged yet', merged: 'merged, not live yet', live: 'fixed and live' };
  function gapLine(g) {
    const times = `Came up ${g.hits} time${g.hits === 1 ? '' : 's'}`;
    const back = g.stage === 'live' && g.hits_after_fix ? `, came back ${g.hits_after_fix} time${g.hits_after_fix === 1 ? '' : 's'}` : '';
    return `${times} · ${GAP_STAGE[g.stage] || g.stage}${back}`;
  }
  function openGaps() {
    return (gaps.gaps || []).filter((g) => g.stage !== 'live' || g.hits_after_fix).slice(0, 3);
  }

  function renderHome(needsYou, problem) {
    const now = new Date();
    const hour = now.getHours();
    const part = hour < 12 ? 'Morning' : hour < 18 ? 'Afternoon' : 'Evening';
    // A build objective the builders are working on is in motion, whatever gap it is blocked by:
    // the gap is what the build is closing. It needs the owner only if he has a question or the
    // loop says so.
    const beingBuilt = (o) => {
      if (o.kind !== 'build' || !(o.engineering || []).length || (o.attention === 'needs_you' && o.needs_you.length)) return false;
      const rows = builds[o.id] || [];
      const last = rows[rows.length - 1];
      return !last || (last.progress !== 'blocked' && last.progress !== 'needs the owner');
    };
    // A check-in the owner asked for that has lapsed needs him as much as a question does.
    const needs = objectives.filter((o) => !beingBuilt(o) && (o.attention === 'needs_you' || o.attention === 'blocked' || o.attention === 'check_in'));
    const moving = objectives.filter((o) => needs.indexOf(o) < 0 && o.attention !== 'dropped');
    const summary = needs.length
      ? `${needs.length === 1 ? 'One thing needs' : `${needs.length} things need`} you.${moving.length ? ' The rest is in motion.' : ''}`
      : (moving.length ? 'Nothing needs you. The rest is in motion.' : 'Nothing needs you right now.');

    const row = (o) => {
      const blocked = o.attention === 'blocked';
      const building = o.kind === 'build' ? buildLine(o) : '';
      // A project's row says the stage it is at and carries its progression; delegated tasks
      // say how far each person has got (web/objective-cards.js). A question or a blocker
      // still comes first.
      const shaped = window.CliveObjectiveCards ? window.CliveObjectiveCards.row(o) : null;
      const sub = o.attention === 'needs_you' && o.needs_you.length ? o.needs_you[0]
        : building || (o.blocked_by.length ? `Waiting for: ${o.blocked_by[0]}`
        : (shaped && shaped.sub) || o.doing || (o.next.length ? `Next: ${o.next[0]}` : ''));
      const when = whenFor(o);
      const lead = o.kind === 'build' && !(o.attention === 'needs_you' && o.needs_you.length)
        ? h('span', { class: 'alpha-tile is-build' }, icon(ICON.build, 18))
        : needs.indexOf(o) >= 0
        ? h('span', { class: `alpha-tile${blocked ? ' is-blocked' : ''}` }, icon(blocked || o.attention === 'check_in' ? ICON.wait : ICON.ask, 18))
        : h('span', { class: `alpha-state is-${o.attention}` }, o.attention === 'done' ? icon(ICON.tick, 15) : null);
      const main = rowMain(o.title, sub, when);
      if (shaped && shaped.track) main.append(shaped.track);
      // `data-objective`: which objective the row is, for holding it and putting it on a screen (web/lift.js).
      return h('button', { class: 'alpha-row', type: 'button', 'data-alpha': 'objective', 'data-attention': o.attention, 'data-kind': o.kind, 'data-objective': o.id, onclick: () => openObjective(o.id) },
        lead, main, icon(ICON.chev, 16));
    };

    home.classList.toggle('is-first', firstRender);
    firstRender = false;
    home.replaceChildren(...[
      h('div', { class: 'alpha-hello' },
        h('p', { class: 'alpha-date', text: now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) }),
        h('h1', { class: 'alpha-h1', text: `${part}, ${OWNER}.` }),
        h('p', { class: 'alpha-summary', text: summary })),
      problem ? h('p', { class: 'alpha-blocked', text: `Objectives could not be read: ${problem}` }) : null,
      needs.length ? h('h2', { class: 'alpha-h2', text: 'Needs you' }) : null,
      needs.length ? h('div', { class: 'alpha-group' }, ...needs.map(row)) : null,
      moving.length ? h('h2', { class: 'alpha-h2', text: 'In motion' }) : null,
      moving.length ? h('div', { class: 'alpha-group' }, ...moving.map(row)) : null,
      !objectives.length && !problem ? h('p', { class: 'alpha-muted', text: 'Nothing ongoing. Tell CLIVE about something you want handled, and it stays here.' }) : null,
      openGaps().length ? h('h2', { class: 'alpha-h2', text: 'CLIVE can’t do yet' }) : null,
      openGaps().length ? h('div', { class: 'alpha-group' }, ...openGaps().map((g) =>
        h('button', { class: 'alpha-row', type: 'button', 'data-alpha': 'gap', onclick: () => openGap(g) },
          h('span', { class: 'alpha-tile is-quiet' }, icon(ICON.plug, 18)), rowMain(g.title || g.label, gapLine(g)), icon(ICON.chev, 16)))) : null,
      h('div', { class: 'alpha-group alpha-tools' },
        h('button', { class: 'alpha-row', type: 'button', 'data-alpha': 'support', onclick: openSupport },
          h('span', { class: 'alpha-tile is-quiet' }, icon(ICON.search, 18)),
          rowMain('Investigate a customer enquiry', 'Paste their message. Read-only.'), icon(ICON.chev, 16)),
        h('button', { class: 'alpha-row', type: 'button', 'data-alpha': 'new_objective', onclick: openNewObjective },
          h('span', { class: 'alpha-tile is-quiet' }, icon(ICON.plus, 18)),
          rowMain('New objective', 'Something for CLIVE to keep alive'), icon(ICON.chev, 16))),
    ].filter(Boolean));
  }

  function labelFor(attention) {
    return { needs_you: 'Needs you', blocked: 'Blocked', check_in: 'Check-in due', doing: 'Doing', idle: 'Idle', done: 'Done', dropped: 'Dropped' }[attention] || attention;
  }

  // ------------------------------------------------------------------ one gap
  function openGap(g) {
    sheetSeq += 1;
    const titles = (g.objectives || []).map((id) => (objectives.find((o) => o.id === id) || {}).title).filter(Boolean);
    const s = gaps.summary || {};
    const title = g.title || g.label;
    const blocks = [head(title.length > 48 ? `${title.slice(0, 45)}…` : title, gapLine(g))];
    if (g.label !== title) blocks.push(h('p', { class: 'alpha-line', text: g.label }));
    const src = g.sources || {};
    blocks.push(h('p', { class: 'alpha-line', text: [
      src.blocker ? `Recorded as a blocker ${src.blocker} time${src.blocker === 1 ? '' : 's'}` : '',
      src.tool ? `reached for a tool it does not have ${src.tool} time${src.tool === 1 ? '' : 's'}` : '',
    ].filter(Boolean).join('; ') + '.' }));
    if (titles.length) {
      blocks.push(h('h3', { text: 'Holding up' }));
      for (const t of titles) blocks.push(h('p', { class: 'alpha-line', text: t }));
    }
    if ((g.builds || []).length) {
      blocks.push(h('h3', { text: 'Builds' }));
      for (const b of g.builds) {
        const where = b.live_at ? 'live' : b.merged_at ? 'merged, not live yet' : b.built_at ? 'built, waiting for you to merge' : b.filed_at ? (b.progress || 'filed') : 'proposed, not filed';
        blocks.push(h('p', { class: 'alpha-line' }, `${b.request_id}: ${where}`));
      }
    }
    if (g.stage === 'open') {
      blocks.push(h('div', { class: 'row-btns' }, h('button', { class: 'btn primary', type: 'button', text: 'Build it', 'data-alpha': 'build_gap', onclick: async () => {
        closeSheet();
        const on = (g.objectives || [])[0];
        const where = on ? `It is holding up my objective ${on}; file the build for that objective.` : 'Open a build objective for it, then file the build.';
        await window.CliveAlpha.ask(`Build a fix so you can do this: "${g.label}". It has come up ${g.hits} time${g.hits === 1 ? '' : 's'}. ${where}`);
        refresh();
        setTimeout(refresh, 2500);
      } })));
    }
    blocks.push(h('h3', { text: 'How CLIVE is choosing' }));
    blocks.push(h('p', { class: 'alpha-muted', text: `Of the ${s.top || 0} gaps that come up most, ${s.top_proposed || 0} ${s.top_proposed === 1 ? 'has' : 'have'} a build proposed. `
      + `${s.live || 0} fix${s.live === 1 ? '' : 'es'} live${s.live ? ` (${s.fixes_held || 0} held, ${s.fixes_recurred || 0} came back)` : ''}. `
      + `It said it couldn't do something it could ${s.misjudged || 0} time${s.misjudged === 1 ? '' : 's'}.` }));
    openSheet(...blocks);
  }

  // ------------------------------------------------------------------ one objective
  const STATE = { proposed: 'Proposed', authorised: 'Approved by you', started: 'In progress', completed: 'Done by CLIVE', verified: 'Verified' };

  async function openObjective(id) {
    const seq = ++sheetSeq;
    let o;
    try { o = await api(`/objectives/${encodeURIComponent(id)}`); } catch (err) { if (seq === sheetSeq) flash(String(err.message || err)); return; }
    if (seq !== sheetSeq) return;   // another sheet was asked for, or this one put away, meanwhile
    drawObjective(o, false, seq);
  }

  // The sheet for one objective, from the record the Mac returned. Drawn again, in place and at
  // the same scroll, when a tick on it comes back, so its header and history agree with it; but
  // only while it is still the sheet the owner has open (`seq`, above). Anything a control on it
  // does after an answer from the Mac is done only while that holds, too.
  function drawObjective(o, keepScroll, seq) {
    const current = () => seq === sheetSeq && sheet.open;
    const open = (list) => list.filter((x) => !x.resolved_at);
    const cards = window.CliveObjectiveCards;
    const shapedKind = cards && o.card && (o.kind === 'project' || o.kind === 'tasks');
    // A project or delegated tasks say what they are and where they stand; any other objective
    // keeps the line it always had.
    const standing = ['needs_you', 'blocked', 'check_in', 'done', 'dropped'].includes(o.summary.attention) ? labelFor(o.summary.attention) : '';
    const sub = shapedKind
      ? [cards.KIND_WORD[o.kind], cards.statusLine(o.card), standing].filter(Boolean).join(' · ')
      : o.deadline ? `By ${o.deadline} · ${labelFor(o.summary.attention)}` : labelFor(o.summary.attention);
    // The head and the shape are the objective itself: held, either lifts it to put on a screen
    // (web/lift.js); the head is focusable for the context-menu key to do the same.
    const lead = head(o.title, sub);
    lead.dataset.objective = o.id;
    lead.setAttribute('tabindex', '0');
    const blocks = [lead];

    const asks = open(o.attention);
    if (asks.length) {
      blocks.push(h('h3', { text: 'Needs you' }));
      for (const a of asks) {
        const answer = h('input', { class: 'alpha-field', type: 'text', placeholder: 'Your answer', 'aria-label': `Answer: ${a.text}` });
        blocks.push(h('div', { class: 'alpha-ask' }, h('p', { text: a.text }), h('form', {
          class: 'alpha-row', onsubmit: async (event) => {
            event.preventDefault();
            try { await api(`/objectives/${o.id}/answer/${a.id}`, { text: answer.value }); } catch (err) { flash(String(err.message || err)); return; }
            await refresh();
            if (current()) openObjective(o.id);
          },
        }, answer, h('button', { class: 'btn primary', type: 'submit', text: 'Answer', 'data-alpha': 'answer' }))));
      }
    }

    // The objective's shape — a project's stages, the tasks by person — and what the owner said
    // it is for, drawn from the same payload as the conversation's card. A tick redraws the sheet
    // and the home. Nothing is drawn for a field nobody filled, so an older objective reads as before.
    const body = cards && o.card
      ? cards.shape(o.card, { sheet: true, onChange: (record) => { if (current()) drawObjective(record, true, seq); refresh(); } }) : null;
    if (body && body.childNodes.length) blocks.push(h('div', { class: 'alpha-shape', 'data-objective': o.id }, body));

    const live = o.items.filter((i) => i.state !== 'verified');
    if (live.length) {
      blocks.push(h('h3', { text: 'What happens next' }));
      for (const item of live) {
        const approve = item.needs_owner && item.state === 'proposed'
          ? h('button', { class: 'btn', type: 'button', text: 'Approve', 'data-alpha': 'approve', onclick: async () => {
              if (!confirm(`Approve: ${item.text}?\n\nThis records your approval. CLIVE still cannot book, pay, submit or send anything itself yet.`)) return;
              try { await api(`/objectives/${o.id}/items/${item.id}/authorise`, {}); } catch (err) { flash(String(err.message || err)); return; }
              if (current()) openObjective(o.id);
            } })
          : null;
        blocks.push(h('div', { class: 'alpha-item', 'data-state': item.state },
          h('p', { text: item.text }),
          h('p', { class: 'alpha-muted', text: `${STATE[item.state] || item.state}${item.needs_owner && item.state === 'proposed' ? ' · needs your approval' : ''}` }),
          approve));
      }
    }

    const filed = (builds[o.id] || []);
    if ((o.engineering || []).length) {
      blocks.push(h('h3', { text: 'Being built' }));
      for (const e of o.engineering.slice(-3)) {
        const row = filed.find((r) => r.request_id === e.request_id);
        blocks.push(h('p', { class: 'alpha-line' }, row ? row.words : `${e.request_id} is filed with the builders.`,
          h('span', { class: 'alpha-src', text: ` · ${e.target_branch || ''}` })));
      }
    }

    const blockers = open(o.blockers);
    if (blockers.length) {
      blocks.push(h('h3', { text: 'Blocked by' }));
      for (const b of blockers) blocks.push(h('p', { class: 'alpha-blocked', text: `${b.text}${b.kind === 'missing_capability' ? ' (CLIVE cannot do this yet)' : ''}` }));
    }
    const unknowns = open(o.unknowns);
    if (unknowns.length) {
      blocks.push(h('h3', { text: 'Still unknown' }));
      for (const u of unknowns) blocks.push(h('p', { class: 'alpha-line', text: u.text }));
    }
    if (o.facts.length) {
      blocks.push(h('h3', { text: 'What CLIVE knows' }));
      for (const f of o.facts) blocks.push(h('p', { class: 'alpha-line' }, f.text, h('span', { class: 'alpha-src', text: ` · ${f.source}` })));
    }

    const note = h('input', { class: 'alpha-field', type: 'text', placeholder: 'Tell CLIVE something new about this', 'aria-label': 'Continue this objective' });
    blocks.push(h('h3', { text: 'Continue' }), h('form', {
      class: 'alpha-row', onsubmit: async (event) => {
        event.preventDefault();
        const text = note.value.trim();
        if (!text) return;
        closeSheet();
        await window.CliveAlpha.ask(`About my objective "${o.title}" (${o.id}): ${text}`);
        refresh();
        setTimeout(refresh, 2500);
      },
    }, note, h('button', { class: 'btn primary', type: 'submit', text: 'Send', 'data-alpha': 'continue' })));

    blocks.push(h('h3', { text: 'History' }));
    for (const e of o.events.slice(-12).reverse()) {
      blocks.push(h('p', { class: 'alpha-event' }, h('span', { class: 'alpha-src', text: `${e.at.slice(5, 16).replace('T', ' ')} · ${e.by} · ` }), e.text));
    }
    // Why Mark done did not close it, said on the sheet itself, where the owner is looking.
    const notDone = h('p', { class: 'alpha-blocked', role: 'status', 'data-alpha': 'mark_done_failed', hidden: true });
    blocks.push(h('div', { class: 'row-btns' },
      h('button', { class: 'btn', type: 'button', text: 'Mark done', 'data-alpha': 'mark_done', onclick: async () => {
        // Named, so the owner confirms the objective this closes, not whichever he thinks is open.
        if (!confirm(`Close "${o.title}" as done?`)) return;
        notDone.textContent = '';
        notDone.hidden = true;
        try {
          await api(`/objectives/${o.id}/status`, { status: 'done' });
        } catch (err) {
          // The server did not confirm it, so it is still open: its sheet stays up and says why,
          // and the home is not redrawn as though it had closed.
          const why = `Not marked done. ${String(err.message || err)}`;
          if (current()) { notDone.textContent = why; notDone.hidden = false; } else flash(why);
          return;
        }
        if (current()) closeSheet();
        refresh();
      } })), notDone);
    const was = sheet.querySelector('.sheet-scroll');
    const top = keepScroll && was ? was.scrollTop : 0;
    openSheet(...blocks);
    const now = sheet.querySelector('.sheet-scroll');
    if (keepScroll && now) now.scrollTop = top;
  }

  function openNewObjective() {
    sheetSeq += 1;
    const request = h('textarea', { class: 'alpha-text', rows: '5', placeholder: 'What do you want handled? Include any date.', 'aria-label': 'Objective' });
    openSheet(head('New objective', 'CLIVE keeps it alive and works out the steps.'), h('form', {
      onsubmit: async (event) => {
        event.preventDefault();
        const text = request.value.trim();
        if (!text) return;
        closeSheet();
        // Through the conversation, so CLIVE records it AND works out the first steps in one turn.
        await window.CliveAlpha.ask(`New objective: ${text}`);
        refresh();
        setTimeout(refresh, 2500);
      },
    }, request, h('button', { class: 'btn primary alpha-wide', type: 'submit', text: 'Give it to CLIVE', 'data-alpha': 'create_objective' })));
  }

  // ------------------------------------------------------------------ support
  function openSupport() {
    sheetSeq += 1;
    const message = h('textarea', { class: 'alpha-text', rows: '6', placeholder: "Paste the customer's message", 'aria-label': "Customer's message" });
    const sender = h('input', { class: 'alpha-field', type: 'email', placeholder: "Customer's email (optional)", 'aria-label': "Customer's email" });
    const out = h('div', { class: 'alpha-support-out', 'aria-live': 'polite' });
    const go = h('button', { class: 'btn primary alpha-wide', type: 'submit', text: 'Investigate', 'data-alpha': 'investigate' });
    openSheet(head('Support enquiry', 'Read-only. Nothing is sent or changed.'), h('form', {
      onsubmit: async (event) => {
        event.preventDefault();
        if (!message.value.trim()) return;
        go.disabled = true; go.textContent = 'Investigating…';
        out.replaceChildren();
        try {
          renderSupport(out, await api('/support/investigate', { text: message.value, sender_email: sender.value.trim() }));
        } catch (err) {
          out.replaceChildren(h('p', { class: 'alpha-blocked', text: `The investigation could not run: ${err.message || err}` }));
        } finally { go.disabled = false; go.textContent = 'Investigate again'; }
      },
    }, message, sender, go), out);
  }

  function renderSupport(out, r) {
    const id = r.identification || {};
    const src = r.sources || {};
    const missing = ['shopify', 'gmail'].filter((k) => src[k] && src[k] !== 'live');
    const list = (title, items, cls) => items && items.length ? [h('h3', { text: title }), ...items.map((x) => h('p', { class: cls || 'alpha-line', text: typeof x === 'string' ? x : x.text }))] : [];
    const draft = r.reply_draft || {};
    const body = h('textarea', { class: 'alpha-text alpha-draft', rows: '9', readonly: true, 'aria-label': 'Reply draft' });
    body.value = draft.body || '';
    out.replaceChildren(...[
      missing.length ? h('p', { class: 'alpha-blocked', text: `Partial evidence: CLIVE could not read ${missing.map((k) => (k === 'gmail' ? 'the inbox' : 'the store')).join(' or ')} on this server, so what follows uses only what could be read. Nothing is guessed.` }) : null,
      (missing.length || (r.problems || []).length) ? h('details', { class: 'alpha-evidence' }, h('summary', { text: 'Why (for setup)' }),
        ...missing.map((k) => h('p', { class: 'alpha-event', text: `${k === 'gmail' ? 'Gmail' : 'Shopify'}: ${src[k]}` })),
        ...(r.problems || []).map((p) => h('p', { class: 'alpha-event', text: typeof p === 'string' ? p : (p.detail || p.problem || JSON.stringify(p)) }))) : null,
      h('h3', { text: 'Who and which order' }),
      h('p', { class: id.status === 'identified' ? 'alpha-line' : 'alpha-blocked',
        text: id.status === 'identified' ? `${id.customer_name || 'Customer'} · ${id.order_number || ''} (${id.confidence || ''})` : (missing.includes('shopify') ? 'Not identified: the store could not be searched.' : `Not identified: ${(id.reasons || []).join('; ') || id.status}`) }),
      h('h3', { text: 'What happened' }), h('p', { class: 'alpha-line', text: r.what_happened || '' }),
      ...list('Verified', r.facts),
      ...list('Likely, not verified', r.inferences),
      ...list('Unknown', r.unknowns, 'alpha-blocked'),
      ...list('Your decisions', r.owner_decisions, 'alpha-needs'),
      h('h3', { text: 'Reply draft · needs your approval' }),
      h('p', { class: 'alpha-muted', text: `${draft.subject || ''} — nothing has been sent. Copy it into your mail to send it yourself.` }),
      body,
      h('div', { class: 'row-btns' }, h('button', { class: 'btn', type: 'button', text: 'Copy draft', 'data-alpha': 'copy_draft', onclick: async () => {
        try { await navigator.clipboard.writeText(draft.body || ''); flash('Draft copied.'); } catch { body.select(); }
      } })),
      h('details', { class: 'alpha-evidence' }, h('summary', { text: `Evidence (${(r.evidence || []).length})` }),
        ...(r.evidence || []).map((e) => h('p', { class: 'alpha-event', text: `${e.source}: ${e.summary}` }))),
    ].filter(Boolean));
  }

  // ------------------------------------------------------------------ keep it current
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
