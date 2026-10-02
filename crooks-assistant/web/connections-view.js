/* CLIVE · Connections: how each connection is drawn (web/connections.js asks and acts; this draws).
 *
 * The screen's one job: show at a glance what CLIVE is connected to and what each connection lets
 * it do, put right whatever is broken, and add what is missing. So the rows are grouped by what
 * the owner has to do, never by how they are built:
 *
 *   Needs you   broken, running out or failing its test, each with the one thing that puts it right
 *   Working     one quiet row each: what it unlocks, and "Connected · checked 2 min ago"
 *   Add         what he could connect, with a Connect button and no key box until he taps it
 *
 * Promises, held by tests/web/connections.test.js and scripts/browser/connections.js:
 *   - a key box is drawn only where the service needs a key and has no working one: a working row
 *     draws none until "Replace key" is tapped; a refused key asks for exactly the keys refused;
 *     a service not yet added draws its box only after Connect;
 *   - technical detail (where a key is kept, the account, the last test's words, the IDs) is in a
 *     details disclosure that starts closed;
 *   - every string from the server goes in as text; no attribute is built from what it sent, only
 *     from this file's own fixed words (a connection's name is used only when it is one of ours).
 *
 * No network and no dependency on the page, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory();
  root.CliveConnectionsView = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const NAME = /^[a-z][a-z0-9]{1,19}$/;
  const GROUPS = [
    ['attention', 'Needs you'],
    ['working', 'Working'],
    ['add', 'Not connected'],
  ];
  // A capability family's state, said in the owner's words beside what it does; ready says nothing.
  // A service that did not answer the registry's own probe is left to the row's status, which comes
  // from asking the service itself and says what is actually wrong.
  const FAMILY_WORDS = {
    READ_ONLY: 'changes off', MISSING_SCOPE: 'needs a permission', NOT_SUPPORTED_BY_STORE: 'not on your plan',
    DISCONNECTED: 'not connected',
  };
  const WHERE_WORDS = { 'saved here': 'Saved here', 'set at the server': 'Set at the server' };
  const ACTIONS = {
    saved: 'key saved', refused: 'key refused (its test failed)', failed: 'key not saved', disconnected: 'disconnected',
    signed_in: 'signed in', sign_in_started: 'sign-in started', sign_in_cancelled: 'sign-in cancelled',
    sign_in_failed: 'sign-in failed', passkey_added: 'Passkey added', passkey_removed: 'Passkey removed',
    approval_refused: 'An approval was refused', voice_changed: 'voice changed',
    access_approved: 'Let onto the team', access_suspended: 'Taken off the team',
  };

  function el(tag, cls, text) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  }

  function add(parent, ...children) {
    for (const child of children) if (child) parent.appendChild(child);
    return parent;
  }

  function button(cls, text, on) {
    const node = el('button', cls, text);
    node.type = 'button';
    if (on) node.addEventListener('click', on);
    return node;
  }

  function str(value) { return value === undefined || value === null ? '' : String(value); }

  // Which stored key each box is for, and the ID it showed: kept here, never in an attribute.
  const BOXES = new WeakMap();
  function boxOf(input) { return BOXES.get(input) || null; }

  // ------------------------------------------------------------------ time, in words

  function stamp(value) {
    const ms = Date.parse(str(value));
    return Number.isNaN(ms) ? null : ms;
  }

  function ago(value, now) {
    const at = stamp(value);
    if (at === null) return '';
    const seconds = Math.max(0, Math.round((now - at) / 1000));
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return minutes + ' min ago';
    const hours = Math.round(minutes / 60);
    if (hours < 24) return hours === 1 ? '1 hour ago' : hours + ' hours ago';
    return 'on ' + day(at);
  }

  function day(ms) {
    return new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  }

  function clock(value) {
    const at = stamp(value);
    if (at === null) return '';
    return new Date(at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  // ------------------------------------------------------------------ what each row says

  // The status line under a row's name. Nothing is said that the server did not establish.
  function status(c, ctx) {
    if (ctx.checking && ctx.checking.has(c.name)) return 'Checking now…';
    if (c.state === 'connected') {
      const when = ago(c.tested_at, ctx.now);
      return when ? 'Connected · checked ' + when : 'Connected';
    }
    if (c.state === 'not_connected' && c.set_up_at === 'server') return 'Connects at the server for now';
    return '';
  }

  function tone(c, ctx) {
    if (ctx.checking && ctx.checking.has(c.name)) return 'is-busy';
    return { connected: 'is-ok', needs_attention: 'is-warn' }[c.state] || 'is-off';
  }

  function summary(state, ctx) {
    const rows = (state && state.connections) || [];
    if (!rows.length) return '';
    const count = (group) => rows.filter((c) => c.group === group).length;
    const working = count('working');
    const attention = count('attention');
    if (ctx.checking && ctx.checking.size) return 'Checking each connection now.';
    if (!attention) return working ? 'All ' + working + ' working.' : 'Nothing is connected yet.';
    return working + ' working, ' + attention + (attention === 1 ? ' needs you.' : ' need you.');
  }

  // "Replace API key", "Replace client ID and client secret": named by what it replaces.
  function replaceWords(c) {
    const keys = replaceKeys(c);
    // "Client ID" reads "client ID" mid-sentence; "API key" keeps its capitals.
    const labels = keys.map((k) => fieldOf(c, k)).filter(Boolean)
      .map((f) => f.label.replace(/ \(.*\)$/, '').replace(/^([A-Z])(?=[a-z])/, (first) => first.toLowerCase()));
    if (c.sign_in) return 'Paste a token instead';
    return labels.length ? 'Replace ' + labels.join(' and ') : 'Replace key';
  }

  // The keys a connection cannot work without (an Instagram token, Shopify's ID and secret).
  function replaceKeys(c) {
    const required = (c.fields || []).filter((f) => (c.requires || []).indexOf(f.key) !== -1).map((f) => f.key);
    return required.length ? required : (c.fields || []).filter((f) => f.secret).map((f) => f.key);
  }

  function fieldOf(c, key) { return (c.fields || []).find((f) => f.key === key) || null; }

  // ------------------------------------------------------------------ the key form

  // Exactly the fields asked for, and nothing typed is ever put back into one: a secret field
  // starts empty; an ID field may show its saved ID, which is not a secret.
  function keyForm(c, keys, ctx, { cancel, label } = {}) {
    const form = el('form', 'key-form');
    form.setAttribute('autocomplete', 'off');
    form.setAttribute('novalidate', '');
    const inputs = [];
    for (const key of keys) {
      const field = fieldOf(c, key);
      if (!field) continue;
      const id = 'key-' + (NAME.test(c.name) ? c.name : 'x') + '-' + inputs.length;
      const wrap = el('div', 'key-field');
      const name = el('label', 'key-label', field.label);
      name.htmlFor = id;
      const line = el('div', 'key-row');
      const input = el('input', 'key-input');
      input.id = id;
      input.type = field.secret ? 'password' : 'text';
      input.autocomplete = 'off';
      input.spellcheck = false;
      input.setAttribute('autocapitalize', 'off');
      input.setAttribute('autocorrect', 'off');
      input.placeholder = field.secret ? 'Paste it here' : 'Paste the ID here';
      if (!field.secret && field.value) input.value = str(field.value);
      BOXES.set(input, { key: field.key, saved: field.secret ? '' : str(field.value) });
      add(line, input);
      if (field.secret) {
        const show = button('btn quiet show', 'Show', () => {
          input.type = input.type === 'password' ? 'text' : 'password';
          show.textContent = input.type === 'password' ? 'Show' : 'Hide';
        });
        show.setAttribute('aria-label', 'Show or hide ' + field.label);
        add(line, show);
      }
      add(wrap, name, line);
      if (field.hint) add(wrap, el('p', 'key-hint', field.hint));
      add(form, wrap);
      inputs.push(input);
    }
    const actions = el('div', 'key-actions');
    const save = el('button', 'btn primary conn-act key-save', label || 'Save');
    save.type = 'submit';
    if (!ctx.canChange) save.disabled = true;
    add(actions, save);
    if (cancel) add(actions, button('btn quiet key-cancel', 'Cancel', cancel));
    const result = el('p', 'key-result');
    result.setAttribute('role', 'status');
    add(form, actions, result);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (ctx.on && ctx.on.save) ctx.on.save(c, form, inputs, save, result);
    });
    return form;
  }

  // ------------------------------------------------------------------ the details disclosure

  function facts(c, ctx) {
    const list = el('dl', 'facts');
    const fact = (term, value, cls) => {
      if (!value) return;
      const row = el('div', 'fact');
      add(row, el('dt', '', term), el('dd', cls || '', value));
      add(list, row);
    };
    fact('Account', c.who);
    if (c.tested_at && c.state !== 'not_connected') fact('Last check', clock(c.tested_at) + '. ' + str(c.tested || c.detail));
    if (typeof c.expires_in_days === 'number' && c.state !== 'not_connected') {
      fact('Sign-in runs out', c.expires_in_days < 0 ? 'Already ran out' : c.expires_in_days === 0 ? 'Today'
        : 'In ' + c.expires_in_days + ' day' + (c.expires_in_days === 1 ? '' : 's'));
    }
    for (const field of c.fields || []) {
      if (!field.secret && field.value) fact(field.label, field.value, 'mono');
    }
    const kept = (c.fields || []).filter((f) => f.stored && f.secret);
    const places = [...new Set(kept.map((f) => WHERE_WORDS[f.where] || f.where))];
    if (places.length === 1) fact(kept.length > 1 ? 'Keys' : 'Key', places[0]);
    else for (const f of kept) fact(f.label, WHERE_WORDS[f.where] || f.where);
    if (c.set_up_at === 'server') fact('Set up', 'At the server, with make gmail. Sign in with Google from here comes next.');
    return list.childNodes.length ? list : null;
  }

  function abilities(c) {
    const items = c.unlocks || [];
    if (!items.length) return null;
    const box = el('div', 'unlocks');
    add(box, el('h4', 'more-h', 'What it lets CLIVE do'));
    const list = el('ul', 'abilities');
    for (const item of items) {
      const words = FAMILY_WORDS[item.state];
      const li = el('li', 'ability' + (words && c.state !== 'not_connected' ? ' is-limited' : ''), item.label);
      if (words && c.state !== 'not_connected') add(li, el('span', 'ability-note', words));
      add(list, li);
    }
    add(box, list);
    if (c.without) add(box, el('p', 'without', c.without));
    return box;
  }

  function redirect(c, ctx) {
    if (!c.sign_in || !c.sign_in.redirect_uri) return null;
    const box = el('div', 'redirect');
    add(box, el('p', 'redirect-help', 'In the Meta app, under Instagram, API setup with Instagram login, Business login settings, add this address to the OAuth redirect URIs exactly:'));
    const row = el('div', 'copy-row');
    const code = el('code', 'redirect-uri', c.sign_in.redirect_uri);
    const copy = button('btn quiet copy', 'Copy', () => { if (ctx.on && ctx.on.copy) ctx.on.copy(c.sign_in.redirect_uri, copy); });
    add(row, code, copy);
    add(box, row);
    return box;
  }

  function more(c, ctx, { head } = {}) {
    const details = el('details', 'conn-more');
    details.open = false;
    const summaryNode = el('summary', 'conn-summary');
    if (head) add(summaryNode, head);
    else add(summaryNode, el('span', 'more-label', 'Details'));
    add(summaryNode, el('span', 'chev'));
    add(details, summaryNode);
    const body = el('div', 'more-body');
    if (c.name === 'elevenlabs' && c.state !== 'not_connected' && ctx.extra) add(body, ctx.extra(c));
    add(body, abilities(c), facts(c, ctx));
    if (c.name === 'instagram' && c.state !== 'not_connected') add(body, redirect(c, ctx));
    const actions = el('div', 'more-actions');
    const result = el('p', 'more-result');
    result.setAttribute('role', 'status');
    const holder = el('div', 'more-form');
    if (c.testable && c.state !== 'not_connected') {
      add(actions, button('btn conn-check', 'Check now', () => ctx.on && ctx.on.check && ctx.on.check(c, result)));
    }
    // An attention row whose key was refused already shows the box: no second way to the same thing.
    const asking = c.group === 'attention' && c.fix === 'key' && (c.needs || []).length;
    if (c.editable && c.state !== 'not_connected') {
      const replace = button('btn conn-replace', replaceWords(c), () => {
        if (holder.firstChild) { holder.textContent = ''; replace.setAttribute('aria-expanded', 'false'); return; }
        add(holder, keyForm(c, replaceKeys(c), ctx, { cancel: () => { holder.textContent = ''; replace.setAttribute('aria-expanded', 'false'); } }));
        replace.setAttribute('aria-expanded', 'true');
        const first = holder.querySelector('input');
        if (first && first.focus) first.focus();
      });
      replace.setAttribute('aria-expanded', 'false');
      if (!asking) add(actions, replace);
      if (c.sign_in) {
        const app = button('btn conn-app', 'Change the Meta app', () => {
          if (holder.firstChild) { holder.textContent = ''; return; }
          add(holder, keyForm(c, ['instagram_app_id', 'instagram_app_secret'], ctx, { cancel: () => { holder.textContent = ''; } }));
        });
        add(actions, app);
      }
      add(actions, button('btn danger conn-disconnect', 'Disconnect', () => ctx.on && ctx.on.disconnect && ctx.on.disconnect(c, result)));
    }
    if (actions.childNodes.length) add(body, actions);
    add(body, holder, result);
    add(details, body);
    return details;
  }

  // ------------------------------------------------------------------ a row

  // Inside a disclosure's summary (a working row) the head is built of spans, which is what a
  // summary may hold beside its heading; elsewhere of blocks.
  function headNode(c, ctx, { inSummary = false } = {}) {
    const block = inSummary ? 'span' : 'div';
    const para = inSummary ? 'span' : 'p';
    const head = el(block, 'conn-head');
    const dot = el('span', 'dot ' + tone(c, ctx));
    dot.setAttribute('aria-hidden', 'true');
    const main = el(block, 'conn-main');
    add(main, el('h3', 'conn-name', c.label), el(para, 'conn-line', c.what));
    const said = status(c, ctx);
    const line = el(para, 'conn-status', said);
    if (!said) line.hidden = true;
    add(main, line);
    if (c.state === 'needs_attention' && !(ctx.checking && ctx.checking.has(c.name))) add(main, el(para, 'conn-problem', c.detail));
    add(head, dot, main);
    return head;
  }

  // What puts an attention row right: one thing, already open.
  function fixNode(c, ctx) {
    const box = el('div', 'conn-fix');
    if (c.fix === 'key' && (c.needs || []).length) {
      add(box, keyForm(c, c.needs, ctx, {}));
    } else if (c.fix === 'signin' && c.sign_in) {
      add(box, signInButton(c, ctx, 'Sign in again'));
    } else if (c.fix === 'server') {
      add(box, el('p', 'fix-note', 'This is put right at the server for now: run make gmail there.'));
    } else if (c.testable) {
      const result = el('p', 'more-result');
      result.setAttribute('role', 'status');
      add(box, button('btn primary conn-act conn-check', 'Check again', () => ctx.on && ctx.on.check && ctx.on.check(c, result)), result);
    }
    return box.childNodes.length ? box : null;
  }

  function signInButton(c, ctx, words) {
    const wrap = el('div', 'signin');
    const result = el('p', 'more-result');
    result.setAttribute('role', 'status');
    const go = button('btn primary conn-act conn-signin', words, () => ctx.on && ctx.on.signIn && ctx.on.signIn(c, go, result));
    if (!ctx.canChange || !c.sign_in.ready) go.disabled = true;
    add(wrap, go, result);
    return wrap;
  }

  // What adding it asks for, drawn only once the owner taps Connect.
  function connectNode(c, ctx, close) {
    const box = el('div', 'conn-fix');
    if (c.fix === 'signin' && c.sign_in) {
      add(box, signInButton(c, ctx, c.sign_in.label || 'Sign in with Instagram'));
    } else if (c.sign_in) {
      add(box, el('p', 'fix-step', 'First, the Meta app CLIVE signs in through.'), redirect(c, ctx));
      add(box, keyForm(c, c.needs || [], ctx, { cancel: close, label: 'Save the app' }));
    } else {
      add(box, keyForm(c, c.needs || [], ctx, { cancel: close }));
    }
    return box;
  }

  function row(c, ctx) {
    const node = el('article', 'conn');
    if (NAME.test(str(c.name))) {
      node.dataset.name = c.name;
      node.id = 'conn-' + c.name;
    }
    node.dataset.state = { connected: 'connected', needs_attention: 'needs_attention', not_connected: 'not_connected' }[c.state] || 'unknown';
    if (c.group === 'working') {
      // One quiet line: the whole row opens its details.
      add(node, more(c, ctx, { head: headNode(c, ctx, { inSummary: true }) }));
      node.classList.add('is-quiet');
      return node;
    }
    const head = headNode(c, ctx);
    add(node, head);
    if (c.group === 'attention') {
      add(node, fixNode(c, ctx), more(c, ctx));
      return node;
    }
    // Something he could add. Gmail connects at the server, so it has nothing to tap here.
    if (c.set_up_at !== 'server') {
      const holder = el('div', 'conn-connect');
      const connect = button('btn conn-act conn-open', 'Connect', () => {
        connect.hidden = true;
        add(holder, connectNode(c, ctx, () => { holder.textContent = ''; connect.hidden = false; if (connect.focus) connect.focus(); }));
        const first = holder.querySelector('input');
        if (first && first.focus) first.focus();
      });
      add(head, connect);
      add(node, holder);
    }
    add(node, more(c, ctx));
    return node;
  }

  function groups(state, ctx) {
    const out = [];
    const rows = (state && state.connections) || [];
    for (const [key, title] of GROUPS) {
      const members = rows.filter((c) => c.group === key);
      if (!members.length) continue;
      const section = el('section', 'group');
      section.dataset.group = key;
      const heading = el('h2', 'group-title', title);
      heading.id = 'group-' + key;
      section.setAttribute('aria-labelledby', heading.id);
      const list = el('div', 'cells');
      for (const c of members) add(list, row(c, ctx));
      add(section, heading, list);
      out.push(section);
    }
    return out;
  }

  // ------------------------------------------------------------------ passkeys and the record

  function passkeys(state, ctx) {
    const keys = (state && state.passkeys) || [];
    const list = el('div', 'cells');
    for (const key of keys) {
      const item = el('div', 'cell');
      const main = el('div', 'cell-main');
      const used = key.last_used_at ? ' · last used ' + ago(key.last_used_at, ctx.now) : '';
      add(main, el('p', 'cell-title', key.label), el('p', 'cell-sub', 'Added ' + ago(key.created_at, ctx.now) + used));
      add(item, main, button('btn danger quiet passkey-remove', 'Remove', () => ctx.on && ctx.on.removePasskey && ctx.on.removePasskey(key)));
      add(list, item);
    }
    const last = el('div', 'cell');
    add(last, button('btn passkey-add', keys.length ? 'Add this device' : 'Set up a passkey on this device',
      () => ctx.on && ctx.on.addPasskey && ctx.on.addPasskey()));
    add(list, last);
    return list;
  }

  function changes(state) {
    const items = (state && state.changes) || [];
    const labels = {};
    for (const c of (state && state.connections) || []) labels[c.name] = c.label;
    const people = new Set(items.map((x) => str(x.who)).filter(Boolean));
    const list = el('ol', 'changes');
    if (!items.length) add(list, el('li', 'change muted', 'No changes yet.'));
    for (const change of items) {
      const subject = labels[change.connection] || '';
      const verb = ACTIONS[change.action] || str(change.action).replace(/_/g, ' ');
      let what = subject ? subject + ' ' + verb : verb.charAt(0).toUpperCase() + verb.slice(1);
      if (change.action === 'voice_changed' && change.detail) what = 'Voice changed to ' + change.detail;
      if (/^access_/.test(str(change.action)) && change.detail) what = verb + ': ' + change.detail;
      const item = el('li', 'change' + (change.ok === false ? ' is-failed' : ''));
      const where = [change.device ? 'from ' + change.device : '', clock(change.at), people.size > 1 ? str(change.who) : '']
        .filter(Boolean).join(' · ');
      add(item, el('p', 'change-what', what), el('p', 'change-when', where));
      add(list, item);
    }
    return list;
  }

  return { groups, row, summary, passkeys, changes, ago, status, keyForm, replaceWords, boxOf, GROUPS };
});
