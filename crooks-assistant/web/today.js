/* CLIVE · Today: the team's own CLIVE, on their phones and on the shared tablet (3 October).
 *
 * George, 2 October: "Workers get basically a screen of buttons, not their own CLIVE ... the
 * work-claiming screen is terrible ... These are teenagers / low-skill workers who need a way where
 * any way they intend to act can be accepted as input: a click, speech, typing." So the page is:
 *
 *   the line   CLIVE's orb and one sentence that always says what happens next.
 *   now        the one job in hand (or the one to take next) in big type, with one obvious action:
 *              Take it, Packed, Done, Write the reply. Holding the card does the same.
 *   after      the next few, quietly, and every job one tap away; what they finished today.
 *   the dock   on every screen: type, or hold the button and speak (web/today-voice.js, the phone's
 *              own recogniser), or just say what you did. A short sentence about one job ("I've
 *              packed 2106", "done with the hoodies") is done at once (web/today-say.js); anything
 *              else goes to their own CLIVE (POST /turn), whose answer comes back here as cards.
 *   the bar    what a step did, with Undo for six seconds (web/objective-touch.js, the objectives'
 *              own bar), so a mis-tap is put right on the spot (POST /today/undo).
 *
 * What a member of the team may do is unchanged and decided by the Mac (app/people/staff.py): the
 * page can only take the steps their taps already could. Something only George may do (a refund, a
 * discount, a change to an order's money, the settings) is never tried: it is noted for him in
 * their words (POST /today/flag) and the page says "That's George's to do. I've told him."
 *
 * The owner's side (who is on what, handing out, people) is web/today-owner.js, on this page.
 * Every name and every message is put on the page as text, never as markup.
 */
(function () {
  'use strict';

  const $ = (selector, root) => (root || document).querySelector(selector);
  const T = window.CliveObjectiveTouch;
  const SAY = window.CliveSay;
  const VOICE = window.CliveTeamVoice;
  const SESSION_KEY = 'clive.today.session';
  const POLL_MS = 30000;
  const HOLD_MS = 600;           // holding the job in hand this long does its one action
  // A job or routine CLIVE's assistant set up, not George with his own taps: what it read may have
  // steered it, so the team can tell the two apart (app/work/store.py VIA_CLIVE).
  const VIA_CLIVE = 'clive';
  const RECORD_WORDS = {
    created: 'set up', claimed: 'took', released: 'gave back', packed: 'packed', counted: 'counted',
    done: 'finished', cancelled: 'cancelled', fulfilled: 'fulfilled', tracking_added: 'added tracking to',
    replied: 'replied to', reply_drafted: 'drafted a reply to', stock_set: 'set the stock of',
    routine_set: 'set a routine:', routine_stopped: 'stopped a routine:', access_approved: 'let in',
    access_suspended: 'took access away from', person_added: 'added to the team:', flagged: 'asked George to:',
    fulfilled_undone: 'undid the fulfilment of', tracking_added_undone: 'undid the tracking on',
    replied_undone: 'undid the reply to', reply_drafted_undone: 'deleted the draft reply to',
    stock_set_undone: 'put back the stock of',
    claimed_undone: 'undid taking', released_undone: 'took back', packed_undone: 'undid packing',
    counted_undone: 'undid the count on', done_undone: 'reopened',
  };
  const OPERATION_WORDS = {
    fulfillment_create: 'Fulfil', fulfillment_tracking_set: 'Add tracking', gmail_draft_reply: 'Save the draft reply',
    gmail_send_reply: 'Send the reply', inventory_set: 'Set the stock',
  };
  // A step CLIVE took for them, said in the bar with its Undo.
  const STEP_WORDS = { claimed: 'took', released: 'gave back', packed: 'packed', counted: 'saved the count for', done: 'finished' };
  // Orders first (a customer is waiting on a parcel), then the people waiting on a reply, then the rest.
  const ORDER_OF_KINDS = { pack_order: 0, reply_email: 1, reply_instagram: 2, stock_count: 3, job: 4 };

  let state = null;
  let drawnOnce = false;
  let busy = false;              // a step or a question is under way
  let focusKey = '';             // the job they chose to look at, if not the first
  let view = 'work';             // work | list | talk
  let picking = null;            // { step, jobs } while the page asks which one
  let bar = null;
  let orb = null;
  let voice = null;

  // ------------------------------------------------------------ talking to the Mac

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
      return { ok: false, unreached: true, detail: "CLIVE can't be reached. Check the phone is online and on Tailscale." };
    }
    let data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    if (!response.ok && data.ok === undefined) data.ok = false;
    if (response.ok && data.ok === undefined) data.ok = true;
    if (!response.ok && !data.detail) data.detail = response.status === 403 ? "That isn't yours to do. Ask CLIVE." : 'That did not work. Nothing changed.';
    return data;
  }

  // The Mac's refusals are lower-case clauses ("that job is someone else's"): said as a sentence.
  function sentence(text) {
    const s = String(text || '').trim();
    if (!s) return '';
    return s.charAt(0).toUpperCase() + s.slice(1) + (/[.!?]$/.test(s) ? '' : '.');
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function button(label, onClick, className) {
    const node = element('button', className || 'link', label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  function when(stamp) {
    if (!stamp) return '';
    const date = new Date(stamp);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }

  function firstName(name) { return String(name || '').split(' ')[0]; }

  // ------------------------------------------------------------ the line and the orb

  function line(text, mood) {
    $('#line').textContent = text || '';
    if (orb) orb.setState(mood || (busy ? 'THINKING' : 'READY'));
  }

  function greeting() {
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Morning' : hour < 17 ? 'Afternoon' : 'Evening';
    return `${part}, ${firstName(state.me.name)}. `;
  }

  // ------------------------------------------------------------ the board, as jobs the page shows

  // One job as the page shows it, whichever list it came from: kept jobs (app/work/store.py) and what
  // CLIVE found (app/work/found.py) carry different fields, and the page needs the same few of each.
  function cardOf(row, place) {
    const kind = row.kind || 'job';
    const order = row.order_number || ((/#\d{3,6}/.exec(row.title || '') || [''])[0]);
    const lines = (row.lines || []).map((l) => ({ quantity: Number(l.quantity) || 0, item: String(l.item || '') }));
    const evidence = row.evidence || {};
    return {
      key: row.item_id || row.ref || row.title, item_id: row.item_id || '', ref: row.ref || '', kind,
      mine: place === 'mine', claimed: row.status === 'claimed', order, lines, title: row.title || 'A job',
      details: row.details || '', snippet: row.snippet || '', due: row.due || '',
      packed: Boolean(evidence.packed || row.packed), labelled: Boolean(row.labelled),
      counts: evidence.counts || [], row,
      words: SAY.titleWords([row.title || '', ...lines.map((l) => l.item)].join(' ')),
    };
  }

  function board() {
    const work = state.work;
    const mine = [...work.mine_found, ...work.mine].map((r) => cardOf(r, 'mine'));
    // In their hands first, then what was handed to them, each in the order the list keeps.
    mine.sort((a, b) => (b.claimed - a.claimed));
    const grabs = [...work.found, ...work.up_for_grabs].map((r) => cardOf(r, 'grabs'));
    grabs.sort((a, b) => (ORDER_OF_KINDS[a.kind] ?? 9) - (ORDER_OF_KINDS[b.kind] ?? 9));
    const waiting = (work.in_hand || []).filter((r) => r.status === 'packed').map((r) => cardOf(r, 'waiting'));
    return { mine, grabs, waiting, done: work.done || [] };
  }

  function focused(b) {
    const all = [...b.mine, ...b.grabs];
    return all.find((c) => c.key === focusKey) || b.mine[0] || b.grabs[0] || null;
  }

  // What a job is called, big and small, in plain words.
  function heading(card) {
    const title = card.title;
    if (card.kind === 'pack_order') {
      const rest = (/^Pack #\d+:\s*(.*)$/.exec(title) || [])[1] || '';
      return { big: card.order || title, small: rest };
    }
    if (card.kind === 'reply_email') {
      const at = title.indexOf(': ');
      return at > 0 ? { big: title.slice(0, at), small: title.slice(at + 2) } : { big: title, small: '' };
    }
    if (card.kind === 'reply_instagram') {
      const who = (/@[\w.]+/.exec(title) || [''])[0];
      return { big: who || title, small: who ? 'is waiting on Instagram' : '' };
    }
    return { big: title, small: '' };
  }

  // The notes under a job's name: its details, made through CLIVE or not, and when it is due.
  function jobNotes(job) {
    const bits = [job.details];
    if (job.created_via === VIA_CLIVE) bits.push('via CLIVE');
    if (job.due && job.due > new Date().toISOString().slice(0, 10)) bits.push('for ' + new Date(job.due).toLocaleDateString('en-GB', { weekday: 'long' }));
    if (job.evidence && job.evidence.note) bits.push('“' + job.evidence.note + '”');
    return bits.filter(Boolean).map((b) => String(b).replace(/\.$/, ''));
  }

  // An order's details are the found row's ("placed 2 hours ago; Royal Mail Tracked 48; label
  // already printed; note: ..."): kept as they are, said once each.
  function orderNotes(card) {
    return String(card.details || '').split('; ').map((s) => s.replace(/^label already printed$/, 'label printed'))
      .filter(Boolean).map((s) => s.charAt(0).toUpperCase() + s.slice(1));
  }

  // What the job asks for now, and what happens after. `act` is a step the page can take.
  function primary(card) {
    if (!card.mine || !card.claimed) {
      return { label: card.mine ? 'Start' : 'Take it', act: 'claim',
        next: `Tap ${card.mine ? 'Start' : 'Take it'}, or say “I'll take it”.` };
    }
    if (card.kind === 'pack_order') {
      if (card.packed) return { label: 'Done', act: 'done', next: 'Packed. Tap Done once it is in the post pile.' };
      return { label: 'Packed', act: 'packed', next: 'Pack these, then tap Packed or say “packed”.' };
    }
    if (card.kind === 'reply_email') {
      return { label: 'Write the reply', act: 'reply', next: 'I write the reply with you. You read it, then hold Send.' };
    }
    if (card.kind === 'reply_instagram') {
      return { label: 'Replied', act: 'done', next: 'Reply in the Instagram app, then tap Replied.' };
    }
    if (card.kind === 'stock_count') {
      if (card.counts.length) return { label: 'Done', act: 'done', next: 'Count saved. Tap Done if that is everything.' };
      return { label: 'Save the count', act: 'count', next: 'Count them, put the numbers in, then Save the count.' };
    }
    return { label: 'Done', act: 'done', next: "Tap Done when it's finished, or tell me what's in the way." };
  }

  // ------------------------------------------------------------ steps on the list

  async function post(path, body) {
    const done = await call(path, body);
    if (!done.ok) {
      const error = new Error(sentence(done.detail) || 'That did not work. Nothing changed.');
      error.unreached = Boolean(done.unreached);
      throw error;
    }
    return done;
  }

  // Each act is the routes a tap uses, in order; the steps it took are kept, newest first, so Undo
  // can put back exactly those (app/work/store.py take_back).
  async function act(card, what, extra) {
    if (busy) return;
    busy = true;
    line(what === 'claim' ? 'Taking it…' : 'One moment…', 'THINKING');
    const steps = [];
    let itemId = card.item_id;
    try {
      if (!(card.mine && card.claimed) && what !== 'release') {
        const claimed = await post('/today/claim', itemId ? { item_id: itemId } : { ref: card.ref });
        itemId = claimed.job.item_id;
        if (claimed.step === 'claimed') steps.unshift('claimed');
      }
      if (what === 'packed' || (what === 'done' && card.kind === 'pack_order' && !card.packed)) {
        await post('/today/packed', { item_id: itemId });
        steps.unshift('packed');
      }
      if (what === 'count') {
        await post('/today/counts', { item_id: itemId, counts: extra || [] });
        steps.unshift('counted');
      }
      if (what === 'release') {
        await post('/today/release', { item_id: itemId });
        steps.unshift('released');
      }
      if (what === 'done' || what === 'packed') {
        await post('/today/done', { item_id: itemId, note: (extra && extra.note) || '' });
        steps.unshift('done');
      }
    } catch (error) {
      busy = false;
      T.haptic('error');
      await load();
      // What did go through can still be undone; what went wrong is said over it.
      if (steps.length) offerUndo(itemId, steps, didWords(card, steps));
      bar.say(error.message, 'error');
      return;
    }
    busy = false;
    focusKey = what === 'claim' || what === 'count' ? itemId : '';
    T.haptic('done');
    picking = null;
    await load();
    offerUndo(itemId, steps, didWords(card, steps));
  }

  function didWords(card, steps) {
    const name = heading(card).big;
    const top = steps[0];
    if (top === 'done' && steps.includes('packed')) return `Packed ${name}. Done.`;
    if (top === 'done') return `Done: ${name}.`;
    if (top === 'packed') return `Packed ${name}.`;
    if (top === 'counted') return `Count saved for ${name}.`;
    if (top === 'released') return `Gave back ${name}.`;
    if (top === 'claimed') return `${name} is yours.`;
    return `${name}.`;
  }

  function offerUndo(itemId, steps, words) {
    if (!steps.length || !itemId) return;
    bar.did(words, async () => {
      const done = await call('/today/undo', { item_id: itemId, steps });
      if (!done.ok) {
        const error = new Error(sentence(done.detail));
        error.unreached = Boolean(done.unreached);
        throw error;
      }
      focusKey = itemId;
      await load();
      return 'Undone. It is back as it was.';
    });
  }

  // Undo said in words, or Undo for a step CLIVE took for them: the bar's own offer if it has one,
  // else what the Mac says can still be taken back.
  async function undoLatest() {
    const shown = bar.state();
    if (shown.undo) { await bar.undo(); return; }
    const last = state && state.last_steps;
    if (!last) { bar.say('Nothing to undo just now.'); return; }
    offerUndo(last.item_id, last.steps, `Undo: ${last.title}`);
    await bar.undo();
  }

  // ------------------------------------------------------------ drawing: the job in hand

  function drawNow(b) {
    const box = $('#now');
    box.textContent = '';
    box.className = 'now';
    if (picking) { drawPick(box); return; }
    const card = focused(b);
    if (!card) {
      box.classList.add('empty');
      box.append(element('p', 'now-kick', 'All clear'), element('h1', 'now-big', 'Nothing waiting'),
        element('p', 'now-small', 'New orders, emails and jobs show up here by themselves.'));
      return;
    }
    const head = heading(card);
    const what = primary(card);
    box.dataset.kind = card.kind;
    box.dataset.key = card.key;
    box.dataset.state = card.mine && card.claimed ? 'yours' : 'next';
    const kick = card.mine && card.claimed ? 'Yours now' : card.mine ? 'Handed to you' : 'Next up';
    box.append(element('p', 'now-kick', kick), element('h1', 'now-big', head.big));
    if (head.small) box.append(element('p', 'now-small', head.small));
    if (card.kind === 'pack_order') {
      const list = element('ul', 'lines');
      for (const l of card.lines) {
        const row = element('li', 'line-row');
        row.append(element('span', 'qty', String(l.quantity)), element('span', 'item', l.item));
        list.append(row);
      }
      if (card.lines.length) box.append(list);
      const notes = orderNotes(card);
      if (notes.length) box.append(element('p', 'notes', notes.join('. ')));
    } else {
      const notes = jobNotes(card.row);
      if (notes.length) box.append(element('p', 'notes', notes.join('. ')));
    }
    if (card.snippet) box.append(element('blockquote', 'said', card.snippet));
    if (card.kind === 'stock_count' && card.mine && card.claimed) box.append(countEditor(card));
    const go = element('button', 'go', what.label);
    go.type = 'button';
    go.addEventListener('click', () => run(card, what.act));
    box.append(go);
    const others = element('div', 'others');
    if (card.mine && card.claimed) others.append(button('Give it back', () => act(card, 'release')));
    if (card.kind === 'reply_email' && card.mine && card.claimed) others.append(button('Already replied', () => act(card, 'done')));
    if (card.kind === 'reply_instagram') {
      const open = element('a', 'link', 'Open Instagram');
      open.href = 'https://www.instagram.com/direct/inbox/';
      open.target = '_blank';
      open.rel = 'noopener noreferrer';
      others.append(open);
    }
    others.append(button('Something wrong?', () => prefill(`Problem with ${head.big}: `)));
    box.append(others);
    holdToAct(box, () => run(card, what.act));
  }

  function run(card, what) {
    if (what === 'count') {
      const counts = readCounts();
      if (!counts.length) { bar.say('Put in at least one count first.', 'error'); return; }
      act(card, 'count', counts);
      return;
    }
    if (what === 'reply') { replyWith(card); return; }
    act(card, what);
  }

  // Holding the job in hand does its one action: a still press, so a scroll is never a step.
  function holdToAct(box, fire) {
    let timer = 0;
    let from = null;
    const clear = () => { box.classList.remove('holding'); if (timer) clearTimeout(timer); timer = 0; from = null; };
    box.addEventListener('pointerdown', (event) => {
      if (event.target.closest('button, a, input, textarea, select, blockquote') || busy) return;
      from = { x: event.clientX, y: event.clientY };
      box.classList.add('holding');
      timer = setTimeout(() => { clear(); T.haptic('done'); fire(); }, HOLD_MS);
    });
    for (const type of ['pointerup', 'pointercancel', 'pointerleave']) box.addEventListener(type, clear);
    box.addEventListener('pointermove', (event) => {
      if (from && Math.hypot(event.clientX - from.x, event.clientY - from.y) > T.SLOP) clear();   // a scroll
    });
  }

  // A stock count: what was counted and how many, a line at a time, with big steppers.
  function countEditor(card) {
    const box = element('div', 'count');
    box.id = 'count';
    const rows = element('div', 'count-rows');
    function addRow(item, number) {
      const row = element('div', 'count-row');
      const name = element('input', 'count-name');
      name.placeholder = 'What you counted';
      name.value = item || '';
      name.setAttribute('aria-label', 'What you counted');
      const less = button('−', () => { field.value = String(Math.max(0, (parseInt(field.value, 10) || 0) - 1)); }, 'step');
      less.setAttribute('aria-label', 'One fewer');
      const field = element('input', 'count-number');
      field.type = 'number';
      field.min = '0';
      field.inputMode = 'numeric';
      field.value = number === undefined ? '' : String(number);
      field.placeholder = '0';
      field.setAttribute('aria-label', 'How many');
      const more = button('+', () => { field.value = String((parseInt(field.value, 10) || 0) + 1); }, 'step');
      more.setAttribute('aria-label', 'One more');
      row.append(name, less, field, more);
      rows.append(row);
    }
    if (card.counts.length) card.counts.forEach((c) => addRow(c.item || c.sku, c.counted)); else addRow('', undefined);
    box.append(rows, button('Add another line', () => addRow('', undefined)));
    return box;
  }

  function readCounts() {
    const counts = [];
    for (const row of document.querySelectorAll('#count .count-row')) {
      const name = $('.count-name', row).value.trim();
      const number = $('.count-number', row).value.trim();
      if (!name && !number) continue;
      counts.push({ item: name || 'Unnamed line', counted: number || '0' });
    }
    return counts;
  }

  // Two or three jobs fitted what they said equally: they choose, never the page.
  function drawPick(box) {
    box.classList.add('pick');
    box.append(element('p', 'now-kick', 'Which one?'), element('h1', 'now-big', 'Tap the one you mean'));
    for (const job of picking.jobs) {
      const head = heading(job);
      const choice = element('button', 'choice', `${head.big}${head.small ? '. ' + head.small : ''}`);
      choice.type = 'button';
      choice.addEventListener('click', () => { const step = picking.step; picking = null; act(job, step); });
      box.append(choice);
    }
    box.append(button('None of these', () => { picking = null; draw(); }));
  }

  // ------------------------------------------------------------ drawing: after this, and done

  function row(card, onTap) {
    const head = heading(card);
    const node = element('button', 'row');
    node.type = 'button';
    const words = element('span', 'row-words');
    words.append(element('span', 'row-big', head.big));
    if (head.small) words.append(element('span', 'row-small', head.small));
    node.append(words, element('span', 'row-go', card.mine && card.claimed ? 'Yours' : 'Open'));
    node.addEventListener('click', onTap);
    return node;
  }

  function show(card) {
    focusKey = card.key;
    picking = null;
    setView('work');
    draw();
    window.scrollTo({ top: 0, behavior: T.reduced() ? 'auto' : 'smooth' });
  }

  function drawAfter(b) {
    const box = $('#after');
    box.textContent = '';
    const now = focused(b);
    const rest = [...b.mine, ...b.grabs].filter((c) => !now || c.key !== now.key);
    if (!rest.length) return;
    box.append(element('h2', 'part', 'After this'));
    const group = element('div', 'group');
    for (const card of rest.slice(0, 3)) group.append(row(card, () => show(card)));
    if (rest.length > 3) {
      const all = element('button', 'row row-more');
      all.type = 'button';
      all.append(element('span', 'row-big', `Every job (${rest.length + (now ? 1 : 0)})`));
      all.addEventListener('click', () => setView('list'));
      group.append(all);
    }
    box.append(group);
  }

  function drawMore(b) {
    const box = $('#more');
    box.textContent = '';
    if (b.waiting.length) {
      box.append(element('h2', 'part', 'Packed, waiting for tracking'));
      const group = element('div', 'group');
      for (const card of b.waiting) {
        group.append(row(card, () => prefill(`Fulfil ${card.order || heading(card).big} with tracking number `)));
      }
      box.append(group);
    }
    box.append(element('h2', 'part', b.done.length ? `Done today (${b.done.length})` : 'Done today'));
    const group = element('div', 'group done');
    if (!b.done.length) group.append(element('p', 'quiet', 'Nothing yet. It fills up as you go.'));
    for (const job of b.done.slice(0, 8)) {
      const item = element('div', 'done-row');
      item.append(element('span', 'tick', '✓'), element('span', 'row-big', heading(cardOf(job, 'done')).big),
        element('span', 'row-small', when(job.done_at)));
      group.append(item);
    }
    box.append(group);
  }

  function drawList(b) {
    const box = $('#list');
    box.textContent = '';
    box.append(button('Back to my work', () => setView('work'), 'back'));
    const parts = [['Yours', b.mine], ['Up for grabs', b.grabs]];
    for (const [title, cards] of parts) {
      if (!cards.length) continue;
      box.append(element('h2', 'part', title));
      const group = element('div', 'group');
      for (const card of cards) group.append(row(card, () => show(card)));
      box.append(group);
    }
  }

  function draw() {
    if (!state || state.me.owner) return;
    const b = board();
    const card = focused(b);
    if (focusKey && !card) focusKey = '';
    drawNow(b);
    drawAfter(b);
    drawMore(b);
    if (view === 'list') drawList(b);
    if (view === 'work' && !busy) line((drawnOnce ? '' : greeting()) + guidance(card));
    drawnOnce = true;
  }

  function guidance(card) {
    if (picking) return 'More than one job fits that. Tap the one you mean.';
    if (!card) return 'Nothing waiting right now. I will put new orders here as they come in.';
    return primary(card).next;
  }

  // ------------------------------------------------------------ the views

  function setView(name) {
    view = name;
    $('#work').hidden = name !== 'work';
    $('#list').hidden = name !== 'list';
    $('#talk').hidden = name !== 'talk';
    if (name === 'list' && state) drawList(board());
    if (name === 'work') draw();
  }

  // ------------------------------------------------------------ the dock: typing and speaking

  function prefill(text) {
    const field = $('#ask-text');
    field.value = text;
    sync();
    field.focus();
    field.setSelectionRange(text.length, text.length);
  }

  function sync() {
    const typed = Boolean($('#ask-text').value.trim());
    $('#send').hidden = !typed;
    $('#mic').hidden = typed;
  }

  // Whatever they typed or said: a step on their own list when it plainly is one, George's when it
  // is his, and otherwise a question for their CLIVE.
  async function handle(text) {
    const said = String(text || '').trim();
    if (!said || !state) return;
    if (state.me.owner) { await askClive(said); return; }
    const b = board();
    const read = SAY.read(said, { mine: b.mine, grabs: b.grabs });
    if (read.do === 'claim' && read.job.mine && read.job.claimed) { show(read.job); bar.say(`${heading(read.job).big} is already yours.`); return; }
    if (['claim', 'packed', 'done', 'release'].includes(read.do)) {
      if (read.do === 'done' && read.job.kind === 'stock_count' && !read.job.counts.length) {
        show(read.job);
        if (read.job.mine && read.job.claimed) bar.say('Put the numbers in first, then Save the count.', 'error');
        else await act(read.job, 'claim');
        return;
      }
      if (read.do === 'done' && read.job.kind === 'reply_email' && !(read.job.mine && read.job.claimed)) { await askClive(said); return; }
      show(read.job);
      await act(read.job, read.do);
      return;
    }
    if (read.do === 'undo') { await undoLatest(); return; }
    if (read.do === 'show') { setView('work'); focusKey = ''; draw(); return; }
    if (read.do === 'pick') { picking = { step: read.step, jobs: read.jobs }; setView('work'); draw(); return; }
    if (read.do === 'george') { await tellGeorge(said, b); return; }
    await askClive(said);
  }

  async function tellGeorge(said, b) {
    const number = (/#?(\d{3,6})/.exec(said) || [])[1];
    const about = number ? [...b.mine, ...b.grabs].find((c) => c.order === `#${number}` && c.ref) : null;
    setView('talk');
    youSaid(said);
    const done = await call('/today/flag', { title: said.slice(0, 160), details: '', ref: about ? about.ref : '' });
    if (!done.ok) {
      cliveSaid(`I couldn't put that on George's list: ${sentence(done.detail)} Tell him yourself for now.`, 'error');
      line('That did not reach George.', 'ERROR');
      return;
    }
    georgeCard(said);
    line("That's George's to do. I've told him.", 'SUCCESS');
    T.haptic('done');
  }

  function wireDock() {
    const form = $('#ask');
    const field = $('#ask-text');
    field.addEventListener('input', sync);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = field.value.trim();
      if (!text || busy) return;
      field.value = '';
      sync();
      field.blur();
      handle(text);
    });
    wireMic();
  }

  // Hold to speak, or tap to start and tap again to stop. The words appear above the bar as they are
  // heard; letting go sends them exactly as if they had been typed.
  function wireMic() {
    const mic = $('#mic');
    const heard = $('#heard');
    let downAt = 0;
    let toggled = false;
    const quiet = () => { heard.hidden = true; heard.textContent = ''; heard.parentNode.classList.remove('hearing'); };
    voice = VOICE.create({
      onWords(text) { heard.hidden = false; heard.textContent = text; heard.parentNode.classList.add('hearing'); },
      onState(s) {
        mic.classList.toggle('listening', s === 'listening');
        document.body.classList.toggle('listening', s === 'listening');
        if (s === 'listening') line('Listening. Let go when you have said it.', 'LISTENING');
        if (s === 'idle' && !busy) line(guidance(state ? focusedCard() : null));
      },
      onEnd(text) { quiet(); handle(text); },
      onFail(reason) {
        quiet();
        bar.say(VOICE.REASONS[reason] || VOICE.REASONS.unheard, 'error');
        if (reason === 'unsupported' || reason === 'blocked') $('#ask-text').focus();
      },
    });
    mic.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      if (busy) { bar.say('One moment, CLIVE is still on the last one.'); return; }
      if (voice.listening) { toggled = false; voice.stop(); return; }
      downAt = Date.now();
      toggled = false;
      if (voice.start()) T.haptic('lift');
    });
    const up = () => {
      if (!voice.listening || toggled) return;
      if (Date.now() - downAt < 350) { toggled = true; return; }    // a tap: keep listening until the next tap
      voice.stop();
    };
    mic.addEventListener('pointerup', up);
    mic.addEventListener('pointercancel', () => { if (voice.listening && !toggled) voice.cancel(); });
    mic.addEventListener('contextmenu', (event) => event.preventDefault());
    mic.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      if (voice.listening) voice.stop(); else { toggled = true; voice.start(); }
    });
  }

  function focusedCard() {
    if (!state || state.me.owner) return null;
    return focused(board());
  }

  // ------------------------------------------------------------ talking to their CLIVE

  function sessionId() {
    let id = '';
    try { id = window.localStorage.getItem(SESSION_KEY) || ''; } catch (error) { id = ''; }
    if (!/^[a-f0-9]{12}$/.test(id)) {
      id = Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, '0')).join('');
      try { window.localStorage.setItem(SESSION_KEY, id); } catch (error) { /* a private window keeps it for the page */ }
    }
    return id;
  }

  function youSaid(text) {
    const log = $('#talk-log');
    if (!document.querySelector('.talk-back')) log.before(button(state && state.me.owner ? 'Back' : 'Back to my work', closeTalk, 'back talk-back'));
    const node = element('p', 'you', text);
    log.append(node);
    return node;
  }

  function cliveSaid(text, kind) {
    const node = element('p', 'said-clive' + (kind ? ' ' + kind : ''), text);
    $('#talk-log').append(node);
    node.scrollIntoView({ block: 'nearest', behavior: T.reduced() ? 'auto' : 'smooth' });
    return node;
  }

  function georgeCard(said) {
    const card = element('div', 'card george');
    card.append(element('p', 'card-title', "That's George's to do. I've told him."),
      element('p', 'card-body', `It is on his list now, in your words: “${said}”`),
      element('p', 'card-note', 'Carry on with your work. He will sort it.'));
    $('#talk-log').append(card);
  }

  function closeTalk() {
    const back = document.querySelector('.talk-back');
    if (back) back.remove();
    $('#talk-log').textContent = '';
    setView(state && state.me.owner ? 'owner' : 'work');
    if (state && state.me.owner) { $('#talk').hidden = true; $('#owner').hidden = false; }
  }

  async function askClive(text) {
    busy = true;
    if (state && state.me.owner) $('#owner').hidden = true;
    setView('talk');
    youSaid(text);
    const waiting = cliveSaid('On it…', 'waiting');
    line('On it. CLIVE is working it out.', 'THINKING');
    const before = { steps: state && state.last_steps, flag: lastFlag(state) };
    const answer = await call('/turn', { text, session_id: sessionId() });
    busy = false;
    waiting.classList.remove('waiting');
    waiting.textContent = answer.answer || sentence(answer.detail) || 'CLIVE did not answer that one. Try again.';
    if (!answer.ok && answer.code === 'no_staff_assistant') waiting.classList.add('error');
    for (const tool of answer.tool_calls || []) {
      if (tool.proposal_id) await confirmCard(tool.proposal_id);
    }
    await load();
    // A step CLIVE took on their list, or a note it left for George, said here as the page's own would be.
    if (lastFlag(state) !== before.flag) georgeCard(text);
    const now = state && state.last_steps;
    if (now && (!before.steps || now.at !== before.steps.at || now.item_id !== before.steps.item_id)) {
      offerUndo(now.item_id, now.steps, `CLIVE ${STEP_WORDS[now.steps[0]] || 'changed'} ${now.title}.`);
    }
    line(answer.ok ? 'Read it below. Back to my work when you are ready.' : 'That did not work. Try again, or ask it another way.',
      answer.ok ? 'SUCCESS' : 'ERROR');
  }

  // Their newest note for George on the record, so a new one is seen whatever the record's length.
  function lastFlag(s) {
    const entry = ((s && s.record) || []).find((e) => e.what === 'flagged' && e.who === s.me.id);
    return entry ? `${entry.at}|${entry.item_id}` : '';
  }

  // A change their CLIVE prepared (fulfil, a reply, stock): what it will do, and the gesture that
  // makes it. Nothing changes until they confirm it themselves (app/routes/actions.py).
  async function confirmCard(proposalId) {
    const session = sessionId();
    const card = await call('/actions/' + encodeURIComponent(proposalId) + '?session_id=' + encodeURIComponent(session));
    if (!card.ok || !card.proposal_id || card.status !== 'pending') return;
    const shown = ((card.ui || []).find((item) => item && item.type === 'confirmation') || {}).data || {};
    const box = element('div', 'card change');
    box.append(element('p', 'card-title', shown.title || ((OPERATION_WORDS[card.operation] || 'A change') + (card.entity_label ? ': ' + card.entity_label : ''))));
    if (shown.entity) box.append(element('p', 'card-note', shown.entity));
    if (shown.summary) box.append(element('p', 'card-body', shown.summary));
    if ((shown.facts || []).length) {
      const facts = element('dl', 'facts');
      for (const fact of shown.facts) facts.append(element('dt', '', fact.label), element('dd', '', fact.value));
      box.append(facts);
    }
    if (shown.body) box.append(element('div', 'body', shown.body));
    if (card.note) box.append(element('p', 'card-note', card.note));
    const result = element('p', 'result');
    const hold = card.interaction === 'hold_to_arm' || card.interaction === 'hold_drag_target';
    const go = element('button', 'go', hold ? 'Hold to confirm' : 'Confirm');
    go.type = 'button';
    if (shown.commit && shown.commit.allowed === false) {
      go.disabled = true;
      result.className = 'result bad';
      result.textContent = shown.commit.reason || 'This change cannot be made from here.';
    }
    let nonce = '';
    let timer = null;
    async function commit() {
      const form = new URLSearchParams({ session_id: session });
      const done = await call('/actions/' + encodeURIComponent(proposalId) + '/commit', form, nonce ? { headers: { 'X-Crooks-Arm': nonce } } : undefined);
      go.disabled = true;
      const made = done.ok && ['verified', 'unverified', 'executed'].includes(String(done.status));
      result.className = 'result ' + (made ? 'ok' : 'bad');
      result.textContent = done.spoken || sentence(done.detail) || (done.ok ? 'Done.' : 'That did not go through.');
      T.haptic(made ? 'done' : 'error');
      load();
    }
    if (hold) {
      const start = () => {
        go.classList.add('holding');
        timer = window.setTimeout(async () => {
          const armed = await call('/actions/' + encodeURIComponent(proposalId) + '/arm', new URLSearchParams({ session_id: session }));
          go.classList.remove('holding');
          if (!armed.ok) { result.className = 'result bad'; result.textContent = sentence(armed.detail); return; }
          nonce = armed.nonce;
          go.textContent = 'Tap to confirm';
          T.haptic('lift');
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
    box.append(go, result);
    $('#talk-log').append(box);
  }

  // Their email job's one action: CLIVE writes the reply with them, as a card they read and confirm.
  function replyWith(card) {
    const head = heading(card);
    askClive(`Draft a reply to the email from ${head.big.replace(/^Reply to /, '')} about “${head.small}”.`);
  }

  // ------------------------------------------------------------ the record, in words

  function recordLine(entry) {
    const verb = RECORD_WORDS[entry.what] || entry.what;
    return (entry.who_name || entry.who || 'Someone') + ' ' + verb + ' ' + (entry.detail || '') +
      (entry.note ? ' (' + entry.note + ')' : '') + (entry.via === VIA_CLIVE ? ' · via CLIVE' : '');
  }

  // ------------------------------------------------------------ load

  async function load(fresh) {
    const data = await call('/today/state' + (fresh ? '?fresh=true' : ''));
    if (!data.ok) {
      line(sentence(data.detail) || "CLIVE wouldn't show the work list.", 'ERROR');
      return false;
    }
    const was = JSON.stringify(state && [state.work, state.record, state.people]);
    state = data;
    document.body.dataset.who = state.me.owner ? 'owner' : 'team';
    $('#home').hidden = !state.me.owner;
    if (state.me.owner) {
      $('#work').hidden = true;
      if (view !== 'talk') $('#owner').hidden = false;
      if (window.CliveTodayOwner && was !== JSON.stringify([state.work, state.record, state.people])) window.CliveTodayOwner.draw(state);
      return true;
    }
    if (view === 'work') $('#work').hidden = false;
    // Typing a count, or holding a job: not redrawn under the finger.
    const at = document.activeElement;
    const typing = at && at.matches && at.matches('#now input');
    if (!typing) draw();
    return true;
  }

  function poll() {
    if (document.visibilityState !== 'visible' || busy || (voice && voice.listening)) return;
    if ($('#ask-text').value.trim() || $('#now').classList.contains('holding')) return;
    load();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bar = T.bar();
    $('#bar-slot').append(bar.el);
    if (window.CrooksOrb) {
      try { orb = window.CrooksOrb.create($('#orb'), { size: 48, reducedMotion: T.reduced() }); } catch (error) { orb = null; }
    }
    wireDock();
    load(true);
    window.setInterval(poll, POLL_MS);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') poll(); });
  });

  // What the owner's side (web/today-owner.js) shares with this page.
  window.CliveToday = {
    call, post, element, button, when, sentence, recordLine, jobNotes, heading, cardOf, load, line,
    ask: askClive, handle, offerUndo, bar: () => bar, state: () => state, RECORD_WORDS, VIA_CLIVE,
  };
}());
