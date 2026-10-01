/* CLIVE · Today — the team's work list (app/routes/today.py), and the owner's board.
 *
 * A member of the team sees their jobs, what is up for grabs (jobs for anyone, and what CLIVE
 * found: orders to pack, emails and Instagram messages waiting), and what they finished today.
 * They claim, mark packed, enter counts and finish with a note; anything that changes the shop or
 * the inbox goes through CLIVE (Ask), as a card they confirm. The owner also hands out jobs and
 * routines, reads who did what, and lets a member of the team in with his passkey.
 *
 * Every name and every message is put on the page as text, never as markup.
 */
(function () {
  'use strict';

  const $ = (selector, root) => (root || document).querySelector(selector);
  let state = null;
  let tab = 'work';
  const SESSION_KEY = 'clive.today.session';
  const SOURCE_WORDS = { orders: 'Orders', emails: 'Emails', instagram: 'Instagram' };
  const KIND_WORDS = { pack_order: 'Order', reply_email: 'Email', reply_instagram: 'Instagram', stock_count: 'Stock count', job: 'Job' };
  const RECORD_WORDS = {
    created: 'set up', claimed: 'claimed', released: 'gave back', packed: 'packed', counted: 'counted',
    done: 'finished', cancelled: 'cancelled', fulfilled: 'fulfilled', tracking_added: 'added tracking to',
    replied: 'replied to', reply_drafted: 'drafted a reply to', stock_set: 'set the stock of',
    routine_set: 'set a routine:', routine_stopped: 'stopped a routine:', access_approved: 'let in',
    access_suspended: 'took access away from', flagged: 'flagged for George:',
    fulfilled_undone: 'undid the fulfilment of', tracking_added_undone: 'undid the tracking on',
    replied_undone: 'undid the reply to', reply_drafted_undone: 'deleted the draft reply to',
    stock_set_undone: 'put back the stock of',
  };
  // A job or routine CLIVE's assistant set up, not George with his own taps: what it read may have
  // steered it, so the team can tell the two apart (app/work/store.py VIA_CLIVE).
  const VIA_CLIVE = 'clive';
  const OPERATION_WORDS = {
    fulfillment_create: 'Fulfil', fulfillment_tracking_set: 'Add tracking', gmail_draft_reply: 'Save the draft reply',
    gmail_send_reply: 'Send the reply', inventory_set: 'Set the stock',
  };

  // ------------------------------------------------------------ talking to CLIVE

  async function call(path, body, options) {
    const init = { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json' } };
    if (body instanceof URLSearchParams) {
      init.body = body;
    } else if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    Object.assign(init.headers, (options && options.headers) || {});
    let response;
    try { response = await fetch(path, init); } catch (error) {
      return { ok: false, detail: 'CLIVE could not be reached. Check you are on Tailscale.' };
    }
    let data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    if (!response.ok && data.ok === undefined) data.ok = false;
    if (response.ok && data.ok === undefined) data.ok = true;
    if (!response.ok && !data.detail) data.detail = 'CLIVE refused that (' + response.status + ').';
    return data;
  }

  function notice(kind, text) {
    const box = $('#notice');
    box.className = 'notice ' + (kind || '');
    box.textContent = text || '';
    box.hidden = !text;
  }

  function when(stamp) {
    if (!stamp) return '';
    const date = new Date(stamp);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function button(label, onClick, className) {
    const node = element('button', 'btn small' + (className ? ' ' + className : ''), label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  // ------------------------------------------------------------ the owner's passkey

  function enc(buffer) {
    const bytes = new Uint8Array(buffer);
    let text = '';
    for (let i = 0; i < bytes.length; i += 1) text += String.fromCharCode(bytes[i]);
    return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function dec(text) {
    const raw = atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4));
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function approve(action) {
    const asked = await call('/connections/approve', { action: action });
    if (!asked.ok) throw asked;
    const options = asked.publicKey;
    options.challenge = dec(options.challenge);
    options.allowCredentials = (options.allowCredentials || []).map((c) => ({ type: c.type, id: dec(c.id) }));
    const credential = await navigator.credentials.get({ publicKey: options });
    const r = credential.response;
    return { id: credential.id, rawId: enc(credential.rawId), type: credential.type, response: {
      clientDataJSON: enc(r.clientDataJSON), authenticatorData: enc(r.authenticatorData),
      signature: enc(r.signature), userHandle: r.userHandle ? enc(r.userHandle) : null } };
  }

  function said(error) {
    if (error && error.name === 'NotAllowedError') return 'Cancelled, or the passkey prompt timed out. Nothing changed.';
    if (error && error.detail) return error.detail;
    return 'That did not work. Nothing changed.';
  }

  // ------------------------------------------------------------ a job

  async function step(path, body, line) {
    line.className = 'result small';
    line.textContent = 'One moment…';
    const done = await call(path, body);
    if (!done.ok) { line.className = 'result small bad'; line.textContent = said(done); return false; }
    await load();
    return true;
  }

  function countForm(job, root) {
    const box = $('.job-count', root);
    box.hidden = false;
    const rows = element('div', '');
    const counted = (job.evidence && job.evidence.counts) || [];
    function addRow(item, number) {
      const row = element('div', 'count-row');
      const name = element('input');
      name.placeholder = 'Item or SKU';
      name.value = item || '';
      const count = element('input');
      count.type = 'number';
      count.min = '0';
      count.inputMode = 'numeric';
      count.placeholder = '0';
      count.value = number === undefined ? '' : String(number);
      const drop = button('×', () => row.remove());
      drop.setAttribute('aria-label', 'Remove this line');
      row.append(name, count, drop);
      rows.append(row);
    }
    if (counted.length) counted.forEach((c) => addRow(c.item || c.sku, c.counted)); else addRow('', undefined);
    const add = button('Add a line', () => addRow('', undefined));
    const save = button('Save counts', async () => {
      const counts = [];
      for (const row of rows.querySelectorAll('.count-row')) {
        const [name, count] = row.querySelectorAll('input');
        if (!name.value.trim() && !count.value.trim()) continue;
        counts.push({ item: name.value.trim(), counted: count.value.trim() });
      }
      await step('/today/counts', { item_id: job.item_id, counts: counts }, $('.result', root));
    }, 'primary');
    box.append(rows, add, save);
  }

  function ask(text) {
    switchTo('ask');
    const field = $('#ask-text');
    field.value = text;
    field.focus();
  }

  function drawJob(job, place) {
    const root = $('#job-template').content.firstElementChild.cloneNode(true);
    const me = state.me;
    $('.job-title', root).textContent = job.title;
    const pill = $('.pill', root);
    const kind = KIND_WORDS[job.kind] || 'Job';
    if (job.status === 'claimed' && job.claimed_by === me.id) { pill.textContent = 'Yours'; pill.classList.add('mine'); }
    else if (job.status === 'claimed') { pill.textContent = (job.claimed_by_name || 'Someone') + ' has it'; }
    else if (job.status === 'packed') { pill.textContent = 'Packed by ' + (job.done_by_name || 'someone'); pill.classList.add('wait'); }
    else if (job.status === 'done') { pill.textContent = 'Done' + (job.done_by_name ? ' by ' + job.done_by_name : ''); }
    else { pill.textContent = job.assignee_name ? 'For ' + job.assignee_name : kind; }
    const bits = [job.details];
    if (job.created_via === VIA_CLIVE) bits.push('via CLIVE');
    if (job.due) bits.push('due ' + job.due);
    if ((job.evidence && job.evidence.packed) || job.packed) bits.push(('packed ' + when((job.evidence && job.evidence.packed_at) || job.packed_at)).trim());
    if (job.evidence && job.evidence.note) bits.push('“' + job.evidence.note + '”');
    $('.job-details', root).textContent = bits.filter(Boolean).join(' · ');
    $('.job-snippet', root).textContent = job.snippet || '';
    const lines = $('.job-lines', root);
    for (const line of job.lines || []) lines.append(element('li', '', line.quantity + ' × ' + line.item + (line.sku ? ' (' + line.sku + ')' : '')));
    const actions = $('.actions', root);
    const result = $('.result', root);
    const mine = job.status === 'claimed' && job.claimed_by === me.id;
    const id = job.item_id;
    if (place === 'grabs') {
      // A kept job is claimed by its id; something CLIVE found, by what it is about.
      actions.append(button('Claim', () => step('/today/claim', id ? { item_id: id } : { ref: job.ref }, result), 'primary'));
    } else if (mine || (place === 'mine' && job.status === 'open')) {
      if (job.status === 'open') actions.append(button('Start it', () => step('/today/claim', { item_id: id }, result), 'primary'));
      if (job.kind === 'pack_order' && !(job.evidence && job.evidence.packed) && !job.packed) {
        actions.append(button('Packed', () => step('/today/packed', { item_id: id }, result), 'primary'));
      }
      if (job.kind === 'pack_order') actions.append(button('Fulfil with CLIVE', () => ask('Fulfil ' + orderName(job) + ' with tracking number ')));
      if (job.kind === 'reply_email') actions.append(button('Draft a reply with CLIVE', () => ask('Draft a reply to the email: ' + job.title.replace(/^Reply to /, '') + '. ')));
      if (job.kind === 'reply_instagram') actions.append(element('span', 'muted small', 'Reply in the Instagram app, then mark it done.'));
      if (job.kind === 'stock_count') countForm(job, root);
      if (job.status === 'claimed') {
        const note = element('input');
        note.placeholder = 'A note (optional)';
        note.maxLength = 300;
        actions.append(note, button('Done', () => step('/today/done', { item_id: id, note: note.value }, result)),
          button('Give it back', () => step('/today/release', { item_id: id }, result)));
      }
    } else if (place === 'hand' && job.status === 'packed' && job.kind === 'pack_order') {
      // Packed and waiting: whoever is at the desk can fulfil it, through CLIVE, as a card.
      actions.append(button('Fulfil with CLIVE', () => ask('Fulfil ' + orderName(job) + ' with tracking number ')));
    } else if (place === 'team' && me.owner && job.item_id && ['open', 'claimed'].includes(job.status)) {
      actions.append(button('Cancel the job', () => { if (window.confirm('Cancel this job?')) step('/today/cancel', { item_id: id }, result); }, 'danger'));
    }
    return root;
  }

  function orderName(job) {
    const match = /#\d+/.exec(job.title || '');
    return match ? 'order ' + match[0] : 'this order';
  }

  function fill(list, jobs, place, empty) {
    list.textContent = '';
    for (const job of jobs) list.append(drawJob(job, place));
    if (empty) empty.hidden = jobs.length > 0;
  }

  // ------------------------------------------------------------ the board

  function drawWork() {
    const work = state.work;
    const mine = [...work.mine_found, ...work.mine];
    fill($('#mine'), mine, 'mine', $('#mine-empty'));
    fill($('#grabs'), [...work.up_for_grabs, ...work.found], 'grabs', $('#grabs-empty'));
    fill($('#hand'), work.in_hand, 'hand');
    $('#hand-box').hidden = !work.in_hand.length;
    $('#hand-title').textContent = state.me.owner ? 'In other hands' : 'Packed, waiting to be fulfilled';
    fill($('#done'), work.done, 'done');
    const down = Object.entries(work.sources || {}).filter(([, s]) => !s.available)
      .map(([name, s]) => (/shopify|gmail|instagram/i.test(s.reason) ? '' : (SOURCE_WORDS[name] || name) + ' ') + String(s.reason).replace(/\.$/, ''));
    $('#sources').textContent = down.length ? 'Not checked just now: ' + down.join('; ') + '.' : '';
  }

  function drawTeam() {
    fill($('#team'), state.work.team || [], 'team');
    for (const select of [$('#assign-to'), $('#routine-to')]) {
      const keep = select.value;
      select.textContent = '';
      select.append(new Option('Whoever is free', ''));
      for (const person of state.people.filter((p) => p.kind === 'staff' && p.active)) select.append(new Option(person.name, person.person_id));
      select.value = keep;
    }
    const routines = $('#routines');
    routines.textContent = '';
    for (const routine of state.routines || []) {
      const item = element('li', 'job');
      item.append(element('div', 'job-title', routine.title));
      item.append(element('p', 'muted small', ({ daily: 'Every day', weekdays: 'Weekdays' }[routine.cadence] || 'Every ' + routine.cadence) +
        (routine.assignee_name ? ' · ' + routine.assignee_name : ' · whoever is free') +
        (routine.created_via === VIA_CLIVE ? ' · via CLIVE' : '')));
      const actions = element('div', 'actions');
      actions.append(button('Stop it', async () => { await call('/today/routine/stop', { routine_id: routine.routine_id }); load(); }, 'danger'));
      item.append(actions);
      routines.append(item);
    }
  }

  async function accessStep(person, verb) {
    try {
      // Letting someone in signs the login shown beside their name, so the passkey approves that
      // login and no other (app/routes/today.py).
      const login = verb === 'approve' ? (person.login || '') : '';
      const approval = await approve('access:' + verb + ':' + person.person_id + (login ? ':' + login : ''));
      const done = await call('/today/access/' + encodeURIComponent(person.person_id) + '/' + verb,
        login ? { approval: approval, login: login } : { approval: approval });
      if (!done.ok) throw done;
      notice('ok', verb === 'approve' ? person.name + ' can use CLIVE now, from their own phone.' : person.name + "'s access is taken away.");
    } catch (error) {
      notice('bad', said(error));
    }
    load();
  }

  function drawPeople() {
    const list = $('#people');
    list.textContent = '';
    for (const person of state.people) {
      const item = element('li', 'job');
      const head = element('div', 'job-head');
      head.append(element('span', 'job-title', person.name), element('span', 'pill', person.kind === 'staff' ? 'Team' : 'Can be asked'));
      item.append(head);
      item.append(element('p', 'job-details muted small', [person.role, (person.areas || []).join(', ')].filter(Boolean).join(' · ')));
      const contact = [person.email, person.instagram, person.phone, person.uses ? 'use for: ' + person.uses : ''].filter(Boolean).join(' · ');
      if (contact) item.append(element('p', 'small', contact));
      if (person.kind === 'staff') {
        const actions = element('div', 'actions');
        const status = person.access || (person.login ? 'pending' : '');
        if (!person.login) actions.append(element('span', 'muted small', 'Tell CLIVE their Tailscale login to let them in.'));
        else if (status === 'pending' || status === 'suspended') actions.append(element('span', 'muted small', person.login + ' · ' + (status === 'pending' ? 'waiting for you' : 'access taken away')),
          button('Let them in', () => accessStep(person, 'approve'), 'primary'));
        else if (status === 'active') actions.append(element('span', 'muted small', person.login + ' · can use CLIVE'),
          button('Take access away', () => { if (window.confirm('Take ' + person.name + "'s access away?")) accessStep(person, 'suspend'); }, 'danger'));
        item.append(actions);
      }
      list.append(item);
    }
    if (!state.people.length) list.append(element('li', 'muted small', 'Nobody yet. Tell CLIVE who works with you.'));
  }

  function drawRecord() {
    const list = $('#record');
    list.textContent = '';
    for (const entry of state.record || []) {
      const item = element('li');
      const verb = RECORD_WORDS[entry.what] || entry.what;
      item.append(element('div', '', (entry.who_name || entry.who || 'Someone') + ' ' + verb + ' ' + (entry.detail || '') +
        (entry.note ? ' (' + entry.note + ')' : '') + (entry.via === VIA_CLIVE ? ' · via CLIVE' : '')));
      item.append(element('div', 'when', when(entry.at)));
      list.append(item);
    }
    if (!(state.record || []).length) list.append(element('li', 'muted', 'Nothing yet today.'));
  }

  // ------------------------------------------------------------ Ask CLIVE

  function sessionId() {
    let id = '';
    try { id = window.localStorage.getItem(SESSION_KEY) || ''; } catch (error) { id = ''; }
    if (!/^[a-f0-9]{12}$/.test(id)) {
      id = Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, '0')).join('');
      try { window.localStorage.setItem(SESSION_KEY, id); } catch (error) { /* a private window keeps it for the page */ }
    }
    return id;
  }

  function say(kind, text) {
    const node = element('div', 'msg ' + kind, text);
    $('#chat').append(node);
    node.scrollIntoView({ block: 'nearest' });
    return node;
  }

  async function confirmCard(proposalId) {
    const session = sessionId();
    const card = await call('/actions/' + encodeURIComponent(proposalId) + '?session_id=' + encodeURIComponent(session));
    if (!card.ok || !card.proposal_id || card.status !== 'pending') return;
    // What the change will do, as the tool built it from what it read (app/presentation.py
    // `_confirmation`): the same facts the owner's card prints, and an email's whole text.
    const shown = ((card.ui || []).find((item) => item && item.type === 'confirmation') || {}).data || {};
    const box = element('div', 'card');
    box.append(element('div', 'what', shown.title || ((OPERATION_WORDS[card.operation] || 'A change') + (card.entity_label ? ': ' + card.entity_label : ''))));
    if (shown.entity) box.append(element('div', 'small', shown.entity));
    if (shown.summary) box.append(element('p', 'small', shown.summary));
    if ((shown.facts || []).length) {
      const facts = element('dl', 'facts small');
      for (const fact of shown.facts) facts.append(element('dt', '', fact.label), element('dd', '', fact.value));
      box.append(facts);
    }
    if (shown.body) box.append(element('div', 'body small', shown.body));
    if (card.note) box.append(element('div', 'small', card.note));
    const line = element('p', 'result small');
    const actions = element('div', 'actions');
    const hold = card.interaction === 'hold_to_arm' || card.interaction === 'hold_drag_target';
    const go = element('button', 'btn primary', hold ? 'Hold to confirm' : 'Confirm');
    go.type = 'button';
    if (shown.commit && shown.commit.allowed === false) {
      go.disabled = true;
      line.className = 'result small bad';
      line.textContent = shown.commit.reason || 'This change cannot be made from here.';
    }
    let nonce = '';
    let timer = null;
    async function commit() {
      const form = new URLSearchParams({ session_id: session });
      const done = await call('/actions/' + encodeURIComponent(proposalId) + '/commit', form, nonce ? { headers: { 'X-Crooks-Arm': nonce } } : undefined);
      go.disabled = true;
      line.className = 'result small ' + (done.ok && ['verified', 'unverified', 'executed'].includes(String(done.status)) ? 'ok' : 'bad');
      line.textContent = done.spoken || done.detail || (done.ok ? 'Done.' : 'That did not go through.');
      load();
    }
    if (hold) {
      const start = () => {
        go.classList.add('holding');
        timer = window.setTimeout(async () => {
          const armed = await call('/actions/' + encodeURIComponent(proposalId) + '/arm', new URLSearchParams({ session_id: session }));
          go.classList.remove('holding');
          if (!armed.ok) { line.className = 'result small bad'; line.textContent = said(armed); return; }
          nonce = armed.nonce;
          go.textContent = 'Tap to confirm';
        }, 900);
      };
      const stop = () => { go.classList.remove('holding'); if (timer) window.clearTimeout(timer); timer = null; };
      go.addEventListener('pointerdown', () => { if (!nonce) start(); });
      go.addEventListener('pointerup', stop);
      go.addEventListener('pointerleave', stop);
      go.addEventListener('click', () => { if (nonce) commit(); });
    } else {
      go.addEventListener('click', commit);
    }
    actions.append(go);
    box.append(actions, line);
    $('#chat').append(box);
  }

  async function send(event) {
    event.preventDefault();
    const field = $('#ask-text');
    const text = field.value.trim();
    if (!text) return;
    field.value = '';
    say('me', text);
    const waiting = say('clive', '…');
    $('#ask-go').disabled = true;
    const answer = await call('/turn', { text: text, session_id: sessionId() });
    $('#ask-go').disabled = false;
    waiting.textContent = answer.answer || answer.detail || 'CLIVE did not answer that one. Try again.';
    for (const tool of answer.tool_calls || []) {
      if (tool.proposal_id) await confirmCard(tool.proposal_id);
    }
  }

  // ------------------------------------------------------------ tabs, load

  function switchTo(name) {
    tab = name;
    for (const section of ['work', 'ask', 'team', 'people', 'record']) $('#s-' + section).hidden = section !== name;
    for (const node of document.querySelectorAll('#tabs button')) node.setAttribute('aria-current', node.value === name ? 'page' : 'false');
  }

  function drawTabs() {
    const tabs = [['work', 'Work'], ['ask', 'Ask CLIVE']];
    if (state.me.owner) tabs.push(['team', 'Team'], ['people', 'People'], ['record', 'Who did what']);
    else tabs.push(['record', 'My record']);
    const nav = $('#tabs');
    nav.textContent = '';
    for (const [name, label] of tabs) {
      const node = element('button', '', label);
      node.type = 'button';
      node.value = name;
      node.addEventListener('click', () => switchTo(name));
      nav.append(node);
    }
    switchTo(tabs.some(([name]) => name === tab) ? tab : 'work');
  }

  async function load(fresh) {
    const data = await call('/today/state' + (fresh ? '?fresh=true' : ''));
    if (!data.ok) { notice('bad', data.detail || 'CLIVE would not show the work list.'); return; }
    state = data;
    $('#hello').textContent = state.me.owner ? 'Today' : 'Hi ' + state.me.name.split(' ')[0];
    $('#lede').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) +
      (state.me.owner ? ' · the whole team' : ' · your work, and what is up for grabs');
    $('#back').hidden = !state.me.owner;
    drawTabs();
    drawWork();
    drawRecord();
    if (state.me.owner) { drawTeam(); drawPeople(); }
  }

  async function submitForm(form, path, after) {
    const body = Object.fromEntries(new FormData(form).entries());
    const done = await call(path, body);
    if (!done.ok) { notice('bad', said(done)); return; }
    form.reset();
    notice('ok', after);
    load();
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#ask').addEventListener('submit', send);
    $('#assign').addEventListener('submit', (event) => { event.preventDefault(); submitForm(event.target, '/today/assign', 'Handed out.'); });
    $('#routine').addEventListener('submit', (event) => { event.preventDefault(); submitForm(event.target, '/today/routine', 'Routine set.'); });
    load(true);
    window.setInterval(() => { if (document.visibilityState === 'visible' && tab !== 'ask') load(); }, 60000);
  });
}());
