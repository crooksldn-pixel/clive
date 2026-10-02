/* CLIVE · Today, George's side of the team (3 October): who is on what, what is waiting for him,
 * handing out a job, and the people on the team.
 *
 * Before, this was five tabs of forms: a hand-out form with a date picker and a "Kind" menu, a second
 * form for routines, a People tab that talked of logins, and the record on a tab of its own. Now
 * there are three parts, each one screen:
 *
 *   Team      what the team asked him to do (their notes for George, from web/today.js), each person
 *             with what they have in hand and what they finished, tap a name for their day step by
 *             step, then the whole day's record.
 *   Hand out  one line for what needs doing, who (anyone, or a name), and when (now, tomorrow, every
 *             day, weekdays), a stock count by one switch; then the routines and the jobs not started.
 *   People    who is on the team and whether they can use CLIVE, letting someone in or taking access
 *             away with his passkey (app/routes/today.py), and adding someone in three fields.
 *
 * The routes are the ones the old page used; nothing here can do more than they could. Every word
 * from a record goes on the page as text, never markup.
 */
(function () {
  'use strict';

  const $ = (selector, root) => (root || document).querySelector(selector);
  const PARTS = [['team', 'Team'], ['hand', 'Hand out'], ['people', 'People']];
  const WHEN = [['now', 'Today'], ['tomorrow', 'Tomorrow'], ['daily', 'Every day'], ['weekdays', 'Weekdays']];
  let part = 'team';
  let open = '';                 // the person whose day is unfolded
  const draft = { who: '', when: 'now', count: false };

  const C = () => window.CliveToday;
  const el = (...args) => C().element(...args);

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
    const asked = await C().call('/connections/approve', { action: action });
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
    if (error && error.detail) return C().sentence(error.detail);
    return 'That did not work. Nothing changed.';
  }

  // ------------------------------------------------------------ the parts

  function segments() {
    const nav = $('#segments');
    nav.textContent = '';
    for (const [name, label] of PARTS) {
      const node = C().button(label, () => { part = name; show(); }, 'segment');
      node.setAttribute('aria-pressed', String(name === part));
      nav.append(node);
    }
  }

  function show() {
    for (const [name] of PARTS) $('#owner-' + name).hidden = name !== part;
    for (const node of document.querySelectorAll('#segments .segment')) {
      node.setAttribute('aria-pressed', String(node.textContent === (PARTS.find(([n]) => n === part) || [])[1]));
    }
  }

  function staff(state) {
    return (state.people || []).filter((p) => p.kind === 'staff' && p.active !== false);
  }

  // ------------------------------------------------------------ Team

  function summary(state) {
    const w = state.work;
    const waiting = (w.mine || []).filter((j) => j.assignee === 'owner' && j.status === 'open').length;
    const people = staff(state).filter((p) => p.access === 'active');
    const busy = people.filter((p) => holding(state, p.person_id).length).map((p) => p.name.split(' ')[0]);
    const bits = [];
    if (waiting) bits.push(waiting === 1 ? 'One thing is waiting for you.' : `${waiting} things are waiting for you.`);
    if (busy.length) bits.push(`${busy.join(' and ')} ${busy.length === 1 ? 'is' : 'are'} on a job.`);
    else if (people.length) bits.push('Nobody has a job in hand.');
    const pool = (w.found || []).length + (w.up_for_grabs || []).length;
    bits.push(pool ? `${pool} waiting for anyone.` : 'Nothing waiting for anyone.');
    return bits.join(' ');
  }

  function holding(state, who) {
    const w = state.work;
    const kept = (w.team || []).filter((j) => j.claimed_by === who && j.status === 'claimed');
    const found = (w.in_hand || []).filter((r) => r.claimed_by === who && r.status === 'claimed');
    return [...found, ...kept];
  }

  function doneBy(state, who) {
    return (state.work.done || []).filter((j) => j.done_by === who);
  }

  function drawTeam(state) {
    const box = $('#owner-team');
    box.textContent = '';
    const mine = (state.work.mine || []).filter((j) => j.status === 'open' || j.status === 'claimed');
    if (mine.length) {
      box.append(el('h2', 'part', 'Waiting for you'));
      const group = el('div', 'group');
      for (const job of mine) group.append(forYou(job));
      box.append(group);
    }
    box.append(el('h2', 'part', 'The team now'));
    const group = el('div', 'group');
    const people = staff(state);
    if (!people.length) group.append(el('p', 'quiet', 'Nobody on the team yet. Add them under People.'));
    for (const person of people) group.append(personRow(state, person));
    box.append(group);
    box.append(el('h2', 'part', 'Today, step by step'));
    const record = el('ol', 'record');
    for (const entry of told(state.record)) {
      const item = el('li');
      item.append(el('span', 'record-words', C().recordLine(entry)), el('span', 'record-when', C().when(entry.at)));
      record.append(item);
    }
    if (!told(state.record).length) record.append(el('li', 'quiet', 'Nothing yet today.'));
    box.append(record);
  }

  // The record as George reads it: a job CLIVE found is kept the moment someone takes it, and its
  // "set up" line beside "took" says nothing he needs.
  function told(record) {
    return (record || []).filter((e) => !(e.what === 'created' && e.ref && e.who !== 'owner'));
  }

  // Something the team asked him to do (a refund, a discount): who asked, in their words, and Done.
  function forYou(job) {
    const item = el('div', 'flag');
    const words = el('div', 'flag-words');
    words.append(el('span', 'row-big', job.title));
    const who = job.created_by_name || (job.created_by && job.created_by !== 'owner' ? job.created_by : '');
    const notes = C().jobNotes(job);
    words.append(el('span', 'row-small', [who ? `${who} asked, ${C().when(job.created_at)}` : C().when(job.created_at), ...notes]
      .filter(Boolean).join('. ')));
    item.append(words, C().button('Done', async () => {
      try {
        const doneJob = await C().post('/today/done', { item_id: job.item_id });
        await C().load();
        C().offerUndo(doneJob.job.item_id, ['done'], `Done: ${job.title}`);
      } catch (error) { C().bar().say(error.message, 'error'); }
    }, 'pill'));
    return item;
  }

  function personRow(state, person) {
    const wrap = el('div', 'person');
    const head = el('button', 'row');
    head.type = 'button';
    head.setAttribute('aria-expanded', String(open === person.person_id));
    const hands = holding(state, person.person_id);
    const done = doneBy(state, person.person_id);
    const words = el('span', 'row-words');
    words.append(el('span', 'row-big', person.name));
    const on = hands.length ? 'On ' + hands.map((j) => C().heading(C().cardOf(j, 'team')).big).join(', ')
      : person.access === 'active' ? 'Nothing in hand' : person.access === 'pending' ? 'Waiting for you to let them in' : 'Cannot use CLIVE';
    words.append(el('span', 'row-small', `${on}. ${done.length ? `${done.length} done today` : 'Nothing finished yet today'}.`));
    head.append(words, el('span', 'row-go', open === person.person_id ? 'Close' : 'Their day'));
    head.addEventListener('click', () => { open = open === person.person_id ? '' : person.person_id; drawTeam(state); });
    wrap.append(head);
    if (open === person.person_id) {
      const steps = told(state.record).filter((e) => e.who === person.person_id);
      const list = el('ol', 'record inset');
      for (const entry of steps) {
        const item = el('li');
        item.append(el('span', 'record-words', C().recordLine(entry)), el('span', 'record-when', C().when(entry.at)));
        list.append(item);
      }
      if (!steps.length) list.append(el('li', 'quiet', `${person.name} has not taken a step today.`));
      wrap.append(list);
    }
    return wrap;
  }

  // ------------------------------------------------------------ Hand out

  function label(words, forId) {
    const node = el('label', 'label', words);
    node.htmlFor = forId;
    return node;
  }

  function chips(options, chosen, onPick) {
    const row = el('div', 'chips');
    for (const [value, label] of options) {
      const chip = C().button(label, () => onPick(value), 'chip');
      chip.setAttribute('aria-pressed', String(value === chosen));
      row.append(chip);
    }
    return row;
  }

  function drawHand(state) {
    const box = $('#owner-hand');
    box.textContent = '';
    const form = el('form', 'compose');
    form.autocomplete = 'off';
    const what = el('input', 'field big');
    what.name = 'title';
    what.id = 'hand-what';
    what.required = true;
    what.maxLength = 160;
    const details = el('input', 'field');
    details.name = 'details';
    details.id = 'hand-details';
    details.maxLength = 400;
    const people = staff(state).map((p) => [p.person_id, p.name]);
    const redraw = () => {
      const keep = [what.value, details.value];
      drawHand(state);
      $('#hand-what').value = keep[0];
      $('#hand-details').value = keep[1];
    };
    form.append(label('What needs doing', 'hand-what'), what, label('Anything they need to know (if anything)', 'hand-details'), details,
      el('p', 'label', 'Who'), chips([['', 'Anyone'], ...people], draft.who, (v) => { draft.who = v; redraw(); }),
      el('p', 'label', 'When'), chips(WHEN, draft.when, (v) => { draft.when = v; redraw(); }));
    const count = C().button(draft.count ? 'A stock count: they put in the numbers' : 'A stock count?', () => { draft.count = !draft.count; redraw(); }, 'chip wide');
    count.setAttribute('aria-pressed', String(draft.count));
    const go = el('button', 'go', 'Hand it out');
    go.type = 'submit';
    form.append(count, go);
    form.addEventListener('submit', (event) => { event.preventDefault(); handOut(what.value.trim(), details.value.trim()); });
    box.append(el('h2', 'part', 'Hand out a job'), form);

    const routines = (state.routines || []);
    box.append(el('h2', 'part', 'Every day, by itself'));
    const group = el('div', 'group');
    if (!routines.length) group.append(el('p', 'quiet', 'No routines yet. Pick Every day or Weekdays above to make one.'));
    for (const routine of routines) {
      const item = el('div', 'flag');
      const words = el('div', 'flag-words');
      words.append(el('span', 'row-big', routine.title), el('span', 'row-small', [
        ({ daily: 'Every day', weekdays: 'Weekdays' }[routine.cadence] || 'Every ' + routine.cadence),
        routine.assignee_name || 'whoever is free', routine.created_via === C().VIA_CLIVE ? 'via CLIVE' : ''].filter(Boolean).join(', ')));
      item.append(words, C().button('Stop', async () => {
        if (!window.confirm(`Stop “${routine.title}”? It won't come back tomorrow.`)) return;
        const done = await C().call('/today/routine/stop', { routine_id: routine.routine_id });
        if (!done.ok) C().bar().say(C().sentence(done.detail), 'error'); else C().bar().say('Stopped. It won’t come back.');
        C().load();
      }, 'pill quiet-pill'));
      group.append(item);
    }
    box.append(group);

    const w = state.work;
    const notStarted = [...(w.up_for_grabs || []), ...(w.team || []).filter((j) => j.status === 'open')];
    if (notStarted.length) {
      box.append(el('h2', 'part', 'Handed out, not started'));
      const list = el('div', 'group');
      for (const job of notStarted) {
        const item = el('div', 'flag');
        const words = el('div', 'flag-words');
        words.append(el('span', 'row-big', job.title), el('span', 'row-small', [job.assignee_name ? 'For ' + job.assignee_name : 'For anyone',
          job.routine_id ? 'today’s, from the routine' : '', ...C().jobNotes(job)].filter(Boolean).join('. ')));
        item.append(words, C().button('Cancel', async () => {
          if (!window.confirm(`Cancel “${job.title}”?`)) return;
          const done = await C().call('/today/cancel', { item_id: job.item_id });
          if (!done.ok) C().bar().say(C().sentence(done.detail), 'error'); else C().bar().say('Cancelled.');
          C().load();
        }, 'pill quiet-pill'));
        list.append(item);
      }
      box.append(list);
    }
  }

  async function handOut(title, details) {
    if (!title) { C().bar().say('Say what needs doing first.', 'error'); return; }
    const kind = draft.count ? 'stock_count' : 'job';
    let path = '/today/assign';
    const body = { title, details, to: draft.who, kind };
    if (draft.when === 'daily' || draft.when === 'weekdays') {
      path = '/today/routine';
      body.cadence = draft.when;
    } else if (draft.when === 'tomorrow') {
      const day = new Date(Date.now() + 864e5);
      body.due = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
    }
    const done = await C().call(path, body);
    if (!done.ok) { C().bar().say(C().sentence(done.detail), 'error'); return; }
    const who = draft.who ? (staff(C().state()).find((p) => p.person_id === draft.who) || {}).name : 'anyone';
    C().bar().say(path === '/today/routine' ? `Set: “${title}”, ${draft.when === 'daily' ? 'every day' : 'weekdays'}.` : `Handed to ${who}: “${title}”.`);
    draft.count = false;
    $('#hand-what').value = '';
    await C().load();
  }

  // ------------------------------------------------------------ People

  async function accessStep(person, verb) {
    try {
      // Letting someone in signs the login shown beside their name, so the passkey approves that
      // login and no other (app/routes/today.py).
      const login = verb === 'approve' ? (person.login || '') : '';
      const approval = await approve('access:' + verb + ':' + person.person_id + (login ? ':' + login : ''));
      const done = await C().call('/today/access/' + encodeURIComponent(person.person_id) + '/' + verb,
        login ? { approval: approval, login: login } : { approval: approval });
      if (!done.ok) throw done;
      C().bar().say(verb === 'approve' ? `${person.name} can use CLIVE now, on their own phone.` : `${person.name} can't use CLIVE any more.`);
    } catch (error) {
      C().bar().say(said(error), 'error');
    }
    C().load();
  }

  function drawPeople(state) {
    const box = $('#owner-people');
    box.textContent = '';
    box.append(el('h2', 'part', 'The team'));
    const group = el('div', 'group');
    const team = (state.people || []).filter((p) => p.kind === 'staff');
    if (!team.length) group.append(el('p', 'quiet', 'Nobody yet. Add them below.'));
    for (const person of team) {
      const item = el('div', 'flag');
      const words = el('div', 'flag-words');
      const status = person.access || (person.login ? 'pending' : '');
      const where = !person.login ? 'No sign-in yet: add the one they use for Tailscale.'
        : status === 'active' ? `Can use CLIVE, signed in as ${person.login}`
          : status === 'suspended' ? `Access taken away (${person.login})` : `Waiting for you to let them in (${person.login})`;
      words.append(el('span', 'row-big', person.name), el('span', 'row-small', [person.role, where].filter(Boolean).join('. ')));
      item.append(words);
      if (person.login && status !== 'active') item.append(C().button('Let them in', () => accessStep(person, 'approve'), 'pill'));
      if (status === 'active') {
        item.append(C().button('Take access away', () => {
          if (window.confirm(`Take ${person.name}'s access away? They won't be able to use CLIVE.`)) accessStep(person, 'suspend');
        }, 'pill quiet-pill'));
      }
      group.append(item);
    }
    box.append(group);

    const contacts = (state.people || []).filter((p) => p.kind !== 'staff');
    if (contacts.length) {
      box.append(el('h2', 'part', 'People CLIVE can suggest'));
      const list = el('div', 'group');
      for (const person of contacts) {
        const item = el('div', 'flag');
        const words = el('div', 'flag-words');
        words.append(el('span', 'row-big', person.name), el('span', 'row-small',
          [person.role, person.uses ? 'for ' + person.uses : '', person.email, person.instagram].filter(Boolean).join('. ')));
        item.append(words);
        list.append(item);
      }
      box.append(list);
    }

    box.append(el('h2', 'part', 'Add someone to the team'));
    const form = el('form', 'compose');
    form.autocomplete = 'off';
    const name = el('input', 'field');
    name.name = 'name';
    name.id = 'add-name';
    name.required = true;
    name.maxLength = 80;
    const login = el('input', 'field');
    login.name = 'login';
    login.id = 'add-login';
    login.type = 'email';
    login.required = true;
    login.maxLength = 200;
    login.autocapitalize = 'none';
    login.spellcheck = false;
    const role = el('input', 'field');
    role.name = 'role';
    role.id = 'add-role';
    role.maxLength = 160;
    const go = el('button', 'go', 'Add to the team');
    go.type = 'submit';
    form.append(label('Name', 'add-name'), name, label('The email they sign in to Tailscale with', 'add-login'), login,
      label('What they do', 'add-role'), role,
      el('p', 'hint', 'They can use CLIVE once you tap Let them in and confirm with your passkey.'), go);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const done = await C().call('/today/people', { name: name.value.trim(), login: login.value.trim(), role: role.value.trim() });
      if (!done.ok) { C().bar().say(C().sentence(done.detail), 'error'); return; }
      C().bar().say(`${name.value.trim()} is added. Tap Let them in when they're ready.`);
      await C().load();
    });
    box.append(form);
  }

  // ------------------------------------------------------------ drawn by web/today.js

  function draw(state) {
    $('#owner').hidden = $('#talk').hidden === false;
    segments();
    drawTeam(state);
    drawHand(state);
    drawPeople(state);
    show();
    C().line(summary(state), 'READY');
  }

  window.CliveTodayOwner = { draw };
}());
