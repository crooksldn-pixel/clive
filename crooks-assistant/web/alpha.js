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
  };

  // The one bar. A tap opens the keyboard (here); a hold is the microphone, and that is decided
  // in app.js (its ask bar section), the only file that reaches it. The bar's faces follow the
  // stage's own state through the stylesheet, so an orb hold lights the bar the same way.
  const bars = h('span', { class: 'ask-bars', 'aria-hidden': 'true' },
    ...Array.from({ length: 28 }, (_, i) => h('span', { style: `height:${10 + ((i * 37) % 26)}px;animation-delay:${(i * 53) % 700}ms` })));
  const bar = h('button', { id: 'ask-bar', class: 'ask-bar', type: 'button', 'aria-label': 'Ask CLIVE. Tap to type, hold to speak.' },
    h('span', { class: 'ask-face ask-idle' }, h('span', { class: 'ask-text', text: 'Ask CLIVE' }), h('span', { class: 'ask-voice' }, icon(ICON.wave))),
    h('span', { class: 'ask-face ask-listen' },
      h('span', { class: 'ask-head' }, h('span', { class: 'ask-dot' }), 'Listening'),
      bars,
      h('span', { class: 'ask-hint', text: 'Release to send · slide away to cancel' })),
    h('span', { class: 'ask-face ask-drop', text: 'Release to cancel' }),
    h('span', { class: 'ask-face ask-busy', text: 'Working on it' }));
  const input = h('input', { id: 'alpha-input', class: 'alpha-input', type: 'text', placeholder: 'Ask CLIVE…',
    autocomplete: 'off', enterkeyhint: 'send', 'aria-label': 'Ask CLIVE' });
  const send = h('button', { class: 'alpha-send', type: 'submit', 'aria-label': 'Send' }, icon(ICON.up, 18));
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
  function openSheet(...kids) {
    sheet.replaceChildren(h('div', { class: 'sheet-grip', 'aria-hidden': 'true' }), h('div', { class: 'sheet-scroll alpha-scroll' }, ...kids.filter(Boolean)));
    if (!sheet.open) sheet.showModal();
  }
  function closeSheet() { if (sheet.open) sheet.close(); }
  function head(title, sub) {
    return h('div', { class: 'alpha-sheet-head' },
      h('div', {}, h('h2', { text: title }), sub ? h('p', { class: 'alpha-muted', text: sub }) : null),
      h('button', { class: 'btn primary', type: 'button', text: 'Done', onclick: closeSheet }));
  }
  function flash(text) {
    const note = h('p', { class: 'alpha-flash', role: 'status', text });
    home.prepend(note);
    setTimeout(() => note.remove(), 4000);
  }

  // ------------------------------------------------------------------ home
  let objectives = [];
  async function refresh() {
    try {
      const data = await api('/objectives');
      objectives = data.objectives || [];
      renderHome(data.needs_you || 0);
    } catch (err) {
      renderHome(0, String(err.message || err));
    }
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

  function renderHome(needsYou, problem) {
    const now = new Date();
    const hour = now.getHours();
    const part = hour < 12 ? 'Morning' : hour < 18 ? 'Afternoon' : 'Evening';
    const needs = objectives.filter((o) => o.attention === 'needs_you' || o.attention === 'blocked');
    const moving = objectives.filter((o) => needs.indexOf(o) < 0 && o.attention !== 'dropped');
    const summary = needs.length
      ? `${needs.length === 1 ? 'One thing needs' : `${needs.length} things need`} you.${moving.length ? ' The rest is in motion.' : ''}`
      : (moving.length ? 'Nothing needs you. The rest is in motion.' : 'Nothing needs you right now.');

    const row = (o) => {
      const blocked = o.attention === 'blocked';
      const sub = o.attention === 'needs_you' && o.needs_you.length ? o.needs_you[0]
        : o.blocked_by.length ? `Waiting for: ${o.blocked_by[0]}`
        : o.doing || (o.next.length ? `Next: ${o.next[0]}` : '');
      const when = whenFor(o);
      const lead = needs.indexOf(o) >= 0
        ? h('span', { class: `alpha-tile${blocked ? ' is-blocked' : ''}` }, icon(blocked ? ICON.wait : ICON.ask, 18))
        : h('span', { class: `alpha-state is-${o.attention}` }, o.attention === 'done' ? icon(ICON.tick, 15) : null);
      return h('button', { class: 'alpha-row', type: 'button', onclick: () => openObjective(o.id) },
        lead, rowMain(o.title, sub, when), icon(ICON.chev, 16));
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
      h('div', { class: 'alpha-group alpha-tools' },
        h('button', { class: 'alpha-row', type: 'button', onclick: openSupport },
          h('span', { class: 'alpha-tile is-quiet' }, icon(ICON.search, 18)),
          rowMain('Investigate a customer enquiry', 'Paste their message. Read-only.'), icon(ICON.chev, 16)),
        h('button', { class: 'alpha-row', type: 'button', onclick: openNewObjective },
          h('span', { class: 'alpha-tile is-quiet' }, icon(ICON.plus, 18)),
          rowMain('New objective', 'Something for CLIVE to keep alive'), icon(ICON.chev, 16))),
    ].filter(Boolean));
  }

  function labelFor(attention) {
    return { needs_you: 'Needs you', blocked: 'Blocked', doing: 'Doing', idle: 'Idle', done: 'Done', dropped: 'Dropped' }[attention] || attention;
  }

  // ------------------------------------------------------------------ one objective
  const STATE = { proposed: 'Proposed', authorised: 'Approved by you', started: 'In progress', completed: 'Done by CLIVE', verified: 'Verified' };

  async function openObjective(id) {
    let o;
    try { o = await api(`/objectives/${encodeURIComponent(id)}`); } catch (err) { flash(String(err.message || err)); return; }
    const open = (list) => list.filter((x) => !x.resolved_at);
    const blocks = [head(o.title, o.deadline ? `By ${o.deadline} · ${labelFor(o.summary.attention)}` : labelFor(o.summary.attention))];

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
            openObjective(o.id);
          },
        }, answer, h('button', { class: 'btn primary', type: 'submit', text: 'Answer' }))));
      }
    }

    const live = o.items.filter((i) => i.state !== 'verified');
    if (live.length) {
      blocks.push(h('h3', { text: 'What happens next' }));
      for (const item of live) {
        const approve = item.needs_owner && item.state === 'proposed'
          ? h('button', { class: 'btn', type: 'button', text: 'Approve', onclick: async () => {
              if (!confirm(`Approve: ${item.text}?\n\nThis records your approval. CLIVE still cannot book, pay, submit or send anything itself yet.`)) return;
              try { await api(`/objectives/${o.id}/items/${item.id}/authorise`, {}); } catch (err) { flash(String(err.message || err)); return; }
              openObjective(o.id);
            } })
          : null;
        blocks.push(h('div', { class: 'alpha-item', 'data-state': item.state },
          h('p', { text: item.text }),
          h('p', { class: 'alpha-muted', text: `${STATE[item.state] || item.state}${item.needs_owner && item.state === 'proposed' ? ' · needs your approval' : ''}` }),
          approve));
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
    }, note, h('button', { class: 'btn primary', type: 'submit', text: 'Send' })));

    blocks.push(h('h3', { text: 'History' }));
    for (const e of o.events.slice(-12).reverse()) {
      blocks.push(h('p', { class: 'alpha-event' }, h('span', { class: 'alpha-src', text: `${e.at.slice(5, 16).replace('T', ' ')} · ${e.by} · ` }), e.text));
    }
    blocks.push(h('div', { class: 'row-btns' },
      h('button', { class: 'btn', type: 'button', text: 'Mark done', onclick: async () => {
        if (!confirm('Close this objective as done?')) return;
        await api(`/objectives/${o.id}/status`, { status: 'done' }).catch((err) => flash(String(err.message || err)));
        closeSheet(); refresh();
      } })));
    openSheet(...blocks);
  }

  function openNewObjective() {
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
    }, request, h('button', { class: 'btn primary alpha-wide', type: 'submit', text: 'Give it to CLIVE' })));
  }

  // ------------------------------------------------------------------ support
  function openSupport() {
    const message = h('textarea', { class: 'alpha-text', rows: '6', placeholder: "Paste the customer's message", 'aria-label': "Customer's message" });
    const sender = h('input', { class: 'alpha-field', type: 'email', placeholder: "Customer's email (optional)", 'aria-label': "Customer's email" });
    const out = h('div', { class: 'alpha-support-out', 'aria-live': 'polite' });
    const go = h('button', { class: 'btn primary alpha-wide', type: 'submit', text: 'Investigate' });
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
      h('div', { class: 'row-btns' }, h('button', { class: 'btn', type: 'button', text: 'Copy draft', onclick: async () => {
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
