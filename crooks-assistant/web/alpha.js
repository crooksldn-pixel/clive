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
    if (!response.ok) throw new Error(data.detail || `The Mac answered ${response.status}.`);
    return data;
  }

  // ------------------------------------------------------------------ layout
  document.body.classList.add('alpha');
  const home = h('section', { id: 'alpha-home', class: 'alpha-home', 'aria-label': 'What needs your attention' });
  const footer = document.querySelector('.bottom');
  footer.parentNode.insertBefore(home, footer);

  const input = h('input', { id: 'alpha-input', class: 'alpha-input', type: 'text', placeholder: 'Ask CLIVE…',
    autocomplete: 'off', enterkeyhint: 'send', 'aria-label': 'Ask CLIVE' });
  const send = h('button', { class: 'alpha-send', type: 'submit', 'aria-label': 'Send', text: '↑' });
  const composer = h('form', { id: 'alpha-composer', class: 'alpha-composer' }, input, send);
  document.getElementById('app').append(composer);
  composer.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || !window.CliveAlpha) return;
    if (window.CliveAlpha.isBusy()) { flash('CLIVE is still answering; one moment.'); return; }
    input.value = '';
    input.blur();
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

  function renderHome(needsYou, problem) {
    const cards = objectives.map((o) => {
      const lines = [];
      if (o.needs_you.length) lines.push(h('p', { class: 'alpha-needs', text: `Needs you: ${o.needs_you[0]}` }));
      else if (o.blocked_by.length) lines.push(h('p', { class: 'alpha-blocked', text: `Waiting for: ${o.blocked_by[0]}` }));
      if (o.doing) lines.push(h('p', { class: 'alpha-line', text: o.doing }));
      else if (o.next.length) lines.push(h('p', { class: 'alpha-line', text: `Next: ${o.next[0]}` }));
      const when = o.days_left == null ? null : (o.days_left < 0 ? 'past the date' : o.days_left === 0 ? 'today' : `${o.days_left} day${o.days_left === 1 ? '' : 's'} left`);
      return h('button', { class: 'alpha-card', type: 'button', onclick: () => openObjective(o.id) },
        h('span', { class: 'alpha-kicker', text: [labelFor(o.attention), when].filter(Boolean).join(' · ') }),
        h('span', { class: 'alpha-title', text: o.title }),
        ...lines);
    });
    const support = h('button', { class: 'alpha-card alpha-support', type: 'button', onclick: openSupport },
      h('span', { class: 'alpha-kicker', text: 'Crooks support' }),
      h('span', { class: 'alpha-title', text: 'Investigate a customer enquiry' }),
      h('p', { class: 'alpha-line', text: 'Paste a message: order, what happened, a reply to approve. Read-only.' }));
    const newObjective = h('button', { class: 'alpha-link', type: 'button', text: '+ New objective', onclick: openNewObjective });
    home.replaceChildren(...[
      h('p', { class: 'alpha-section', text: needsYou ? `What needs your attention · ${needsYou}` : 'What CLIVE is keeping alive' }),
      problem ? h('p', { class: 'alpha-blocked', text: `Objectives could not be read: ${problem}` }) : null,
      ...(cards.length ? cards : [h('p', { class: 'alpha-muted', text: 'Nothing ongoing. Tell CLIVE about something you want handled, and it stays here.' })]),
      support,
      newObjective,
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
