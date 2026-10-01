/* CLIVE · Connections — add, test and remove CLIVE's keys and sign-ins (app/routes/connections.py).
 *
 * Every change asks for the owner's passkey at that moment: the server issues a challenge for
 * exactly that change, the device asks for Face ID, a fingerprint or its PIN, and the server
 * checks the answer before it touches anything. A key typed here goes to the server once, is
 * tested there before it replaces the one in use, and is never sent back: a saved secret shows
 * as "saved", never as its value. Nothing here is kept in the browser's storage.
 */
(function () {
  'use strict';

  const $ = (selector, root) => (root || document).querySelector(selector);
  const STATES = { connected: 'Connected', not_connected: 'Not connected', needs_attention: 'Needs attention' };
  const NOTICES = {
    signed_in: ['ok', 'Instagram is connected.'],
    signed_in_untested: ['bad', 'Signed in, but the new token did not pass its test: see the Instagram card.'],
    cancelled: ['bad', 'You cancelled the sign-in on Instagram. Nothing changed.'],
    stale: ['bad', 'That sign-in took too long or was already used. Start it again.'],
    refused: ['bad', 'Instagram did not accept the sign-in. Check the address on the Instagram card is in the Meta app exactly, then try again.'],
    needs_app: ['bad', 'Store the Instagram app ID and app secret first.'],
    exchange: ['bad', 'Instagram would not turn the sign-in into a lasting token. Check the app secret.'],
    unreachable: ['bad', 'Instagram could not be reached from the server. Try again.'],
    bad_code: ['bad', 'Instagram came back without a sign-in code. Start again.'],
    not_yours: ['bad', 'That sign-in was started by someone else.'],
    store_unavailable: ['bad', "This server can't keep keys for the app yet."],
  };
  let current = { connections: [], passkeys: [], changes: [], store: { ok: true, why: '' } };
  // An ID field's saved value, so Save sends only what changed. Kept here, not on the element.
  const savedIds = new WeakMap();

  // ------------------------------------------------------------ base64url, as WebAuthn needs it

  function enc(buffer) {
    const bytes = new Uint8Array(buffer);
    let text = '';
    for (let i = 0; i < bytes.length; i += 1) text += String.fromCharCode(bytes[i]);
    return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function dec(text) {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
    const raw = atob(padded);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  // ------------------------------------------------------------ talking to CLIVE

  async function call(path, body) {
    const options = { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: { Accept: 'application/json' }, cache: 'no-store' };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (error) {
      return { ok: false, detail: 'CLIVE could not be reached. Check you are on Tailscale.' };
    }
    let data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    if (!response.ok && data.ok === undefined) data.ok = false;
    if (!response.ok && !data.detail) data.detail = 'CLIVE refused that (' + response.status + ').';
    return data;
  }

  function passkeysWork() {
    return Boolean(window.PublicKeyCredential && navigator.credentials && window.isSecureContext);
  }

  function said(error) {
    if (error && error.name === 'NotAllowedError') return 'Cancelled, or the passkey prompt timed out. Nothing changed.';
    if (error && error.name === 'InvalidStateError') return 'This device already has a passkey here.';
    if (error && error.detail) return error.detail;
    return 'That did not work. Nothing changed.';
  }

  async function approve(action) {
    const asked = await call('/connections/approve', { action: action });
    if (!asked.ok) throw asked;
    const options = asked.publicKey;
    options.challenge = dec(options.challenge);
    options.allowCredentials = (options.allowCredentials || []).map((c) => ({ type: c.type, id: dec(c.id) }));
    const credential = await navigator.credentials.get({ publicKey: options });
    const r = credential.response;
    return {
      id: credential.id, rawId: enc(credential.rawId), type: credential.type,
      response: {
        clientDataJSON: enc(r.clientDataJSON), authenticatorData: enc(r.authenticatorData),
        signature: enc(r.signature), userHandle: r.userHandle ? enc(r.userHandle) : null,
      },
    };
  }

  // ------------------------------------------------------------ the passkey panel

  async function addPasskey() {
    const button = $('#passkey-add');
    button.disabled = true;
    try {
      const body = current.passkeys.length ? { approval: await approve('passkey:add') } : {};
      const begun = await call('/connections/passkeys/begin', body);
      if (!begun.ok) throw begun;
      const options = begun.publicKey;
      options.challenge = dec(options.challenge);
      options.user.id = dec(options.user.id);
      options.excludeCredentials = (options.excludeCredentials || []).map((c) => ({ type: c.type, id: dec(c.id) }));
      const credential = await navigator.credentials.create({ publicKey: options });
      const done = await call('/connections/passkeys', { credential: {
        id: credential.id, rawId: enc(credential.rawId), type: credential.type,
        response: { clientDataJSON: enc(credential.response.clientDataJSON),
          attestationObject: enc(credential.response.attestationObject) },
      } });
      if (!done.ok) throw done;
      notice('ok', 'Passkey set up on ' + done.passkey.label + '. Every change now asks for it.');
    } catch (error) {
      notice('bad', said(error));
    } finally {
      button.disabled = false;
      await load();
    }
  }

  async function removePasskey(id, label) {
    if (!window.confirm('Remove the passkey on ' + label + '? It will no longer approve changes.')) return;
    try {
      const approval = await approve('passkey:remove:' + id);
      const done = await call('/connections/passkeys/' + encodeURIComponent(id) + '/remove', { approval: approval });
      if (!done.ok) throw done;
      notice('ok', 'Passkey on ' + label + ' removed.');
    } catch (error) {
      notice('bad', said(error));
    }
    await load();
  }

  function drawPasskeys() {
    const lede = $('#passkey-lede');
    const list = $('#passkey-list');
    const add = $('#passkey-add');
    list.textContent = '';
    if (!passkeysWork()) {
      lede.textContent = "This browser can't use passkeys here. Open CLIVE in Safari or Chrome at its https Tailscale address.";
      add.hidden = true;
      return;
    }
    if (!current.passkeys.length) {
      lede.textContent = 'Every change here asks for Face ID, your fingerprint or your device PIN. Set it up once on this device.';
      add.textContent = 'Set up a passkey on this device';
    } else {
      lede.textContent = 'These approve every change. Add another device here, approved by one you already have.';
      add.textContent = 'Add this device';
      for (const key of current.passkeys) {
        const item = document.createElement('li');
        const text = document.createElement('span');
        text.textContent = key.label + ' · added ' + when(key.created_at) + (key.last_used_at ? ' · last used ' + when(key.last_used_at) : '');
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn small danger';
        remove.textContent = 'Remove';
        remove.addEventListener('click', () => removePasskey(key.id, key.label));
        item.append(text, remove);
        list.append(item);
      }
    }
    add.hidden = false;
  }

  // ------------------------------------------------------------ the cards

  function fieldRow(field) {
    const row = document.createElement('div');
    row.className = 'field';
    const id = 'f-' + field.key;
    const label = document.createElement('label');
    label.htmlFor = id;
    label.textContent = field.label;
    const where = document.createElement('span');
    where.className = 'where';
    where.textContent = '· ' + field.where;
    label.append(where);
    const line = document.createElement('div');
    line.className = 'input-row';
    const input = document.createElement('input');
    input.id = id;
    input.name = field.key;
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('autocorrect', 'off');
    if (field.secret) {
      input.type = 'password';
      input.placeholder = field.stored ? 'Saved. Paste a new one to replace it.' : 'Paste it here';
    } else {
      input.type = 'text';
      input.value = field.value || '';
      savedIds.set(input, field.value || '');
      input.placeholder = 'Paste it here';
    }
    line.append(input);
    if (field.secret) {
      const show = document.createElement('button');
      show.type = 'button';
      show.className = 'btn small';
      show.textContent = 'Show';
      show.addEventListener('click', () => {
        input.type = input.type === 'password' ? 'text' : 'password';
        show.textContent = input.type === 'password' ? 'Show' : 'Hide';
      });
      line.append(show);
    }
    row.append(label, line);
    if (field.hint) {
      const hint = document.createElement('p');
      hint.className = 'hint';
      hint.textContent = field.hint;
      row.append(hint);
    }
    return row;
  }

  function entered(form) {
    const values = {};
    for (const input of form.querySelectorAll('input')) {
      const value = input.value.trim();
      if (!value) continue;
      if (savedIds.has(input) && value === savedIds.get(input)) continue;
      values[input.name] = value;
    }
    return values;
  }

  function result(card, kind, text) {
    const line = $('.result', card);
    line.className = 'result small ' + (kind || '');
    line.textContent = text || '';
  }

  async function save(connection, card) {
    const form = $('.fields', card);
    const values = entered(form);
    if (!Object.keys(values).length) { result(card, 'bad', 'Paste something first.'); return; }
    busy(card, true);
    result(card, '', 'Asking for your passkey…');
    try {
      const approval = await approve('save:' + connection.name);
      result(card, '', 'Testing it with ' + connection.label + '…');
      const done = await call('/connections/' + connection.name, { values: values, approval: approval });
      if (!done.ok) throw done;
      for (const input of form.querySelectorAll('input[type="password"]')) input.value = '';
      result(card, 'ok', done.result.detail);
      await load(connection.name, done.result.detail);
    } catch (error) {
      result(card, 'bad', said(error));
    } finally {
      busy(card, false);
    }
  }

  async function test(connection, card) {
    busy(card, true);
    result(card, '', 'Testing…');
    const done = await call('/connections/' + connection.name + '/test', {});
    busy(card, false);
    if (!done.ok) { result(card, 'bad', said(done)); return; }
    result(card, done.result.ok ? 'ok' : 'bad', done.result.detail);
    await load(connection.name, done.result.detail, done.result.ok);
  }

  async function disconnect(connection, card) {
    if (!window.confirm('Disconnect ' + connection.label + '? CLIVE stops using it until you connect it again.')) return;
    busy(card, true);
    try {
      const approval = await approve('disconnect:' + connection.name);
      const done = await call('/connections/' + connection.name + '/disconnect', { approval: approval });
      if (!done.ok) throw done;
      await load(connection.name, connection.label + ' is disconnected.');
    } catch (error) {
      result(card, 'bad', said(error));
    } finally {
      busy(card, false);
    }
  }

  async function signIn(connection, card) {
    busy(card, true);
    result(card, '', 'Asking for your passkey…');
    try {
      const approval = await approve('signin:' + connection.name);
      const done = await call('/connections/' + connection.name + '/sign-in', { approval: approval });
      if (!done.ok) throw done;
      result(card, '', 'Opening Instagram…');
      window.location.assign(done.url);
    } catch (error) {
      result(card, 'bad', said(error));
      busy(card, false);
    }
  }

  function busy(card, on) {
    for (const button of card.querySelectorAll('button')) button.disabled = on;
  }

  function drawCard(connection) {
    const card = $('#card-template').content.firstElementChild.cloneNode(true);
    card.id = connection.name;
    $('.card-title', card).textContent = connection.label;
    const pill = $('.pill', card);
    pill.textContent = STATES[connection.state] || connection.state;
    pill.classList.add(connection.state);
    $('.card-what', card).textContent = connection.what;
    $('.card-detail', card).textContent = [connection.detail, connection.who ? '(' + connection.who + ')' : ''].join(' ').trim();
    $('.card-note', card).textContent = connection.note || '';
    const form = $('.fields', card);
    for (const field of connection.fields) form.append(fieldRow(field));
    form.addEventListener('submit', (event) => { event.preventDefault(); save(connection, card); });
    const saveButton = $('.save', card);
    const testButton = $('.test', card);
    const disconnectButton = $('.disconnect', card);
    saveButton.hidden = !connection.editable;
    testButton.hidden = !connection.testable || connection.state === 'not_connected';
    disconnectButton.hidden = !connection.editable || connection.state === 'not_connected';
    saveButton.addEventListener('click', () => save(connection, card));
    testButton.addEventListener('click', () => test(connection, card));
    disconnectButton.addEventListener('click', () => disconnect(connection, card));
    if (connection.sign_in) {
      const box = $('.signin', card);
      box.hidden = false;
      const go = $('.signin-go', box);
      go.textContent = connection.sign_in.label;
      go.disabled = !connection.sign_in.ready || !passkeysWork() || !current.passkeys.length;
      go.title = connection.sign_in.ready ? '' : 'Save the app ID and secret first';
      go.addEventListener('click', () => signIn(connection, card));
      $('.redirect', box).textContent = connection.sign_in.redirect_uri;
      $('.copy', box).addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(connection.sign_in.redirect_uri);
          $('.copy', box).textContent = 'Copied';
        } catch (error) {
          $('.copy', box).textContent = 'Select and copy it';
        }
      });
    }
    if (!current.store.ok && connection.editable) {
      saveButton.disabled = true;
      result(card, 'bad', "This server can't keep keys for the app yet: " + current.store.why);
    } else if (connection.editable && passkeysWork() && !current.passkeys.length) {
      // Every change asks for the passkey, so none can be made before there is one.
      saveButton.disabled = true;
      disconnectButton.disabled = true;
      result(card, '', 'Set up your passkey above first.');
    }
    return card;
  }

  // ------------------------------------------------------------ changes, notices, times

  function when(stamp) {
    if (!stamp) return '';
    const date = new Date(stamp);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }

  const ACTIONS = {
    saved: 'saved', refused: 'refused (its test failed)', failed: 'not saved', disconnected: 'disconnected',
    signed_in: 'signed in', sign_in_started: 'sign-in started', sign_in_cancelled: 'sign-in cancelled',
    sign_in_failed: 'sign-in failed', passkey_added: 'passkey added', passkey_removed: 'passkey removed',
    approval_refused: 'approval refused',
  };

  function drawChanges() {
    const list = $('#change-list');
    list.textContent = '';
    if (!current.changes.length) {
      const item = document.createElement('li');
      item.className = 'muted';
      item.textContent = 'No changes yet.';
      list.append(item);
      return;
    }
    for (const change of current.changes) {
      const item = document.createElement('li');
      const what = document.createElement('div');
      const subject = change.connection && change.connection.indexOf(':') === -1 ? change.connection : '';
      what.textContent = [subject, ACTIONS[change.action] || change.action].filter(Boolean).join(' ') +
        (change.device ? ' · from ' + change.device : '');
      if (!change.ok) what.className = 'failed';
      const stamp = document.createElement('div');
      stamp.className = 'when';
      stamp.textContent = when(change.at) + (change.who ? ' · ' + change.who : '');
      item.append(what, stamp);
      list.append(item);
    }
  }

  function notice(kind, text) {
    const box = $('#notice');
    box.className = 'notice ' + (kind || '');
    box.textContent = text;
    box.hidden = !text;
  }

  // ------------------------------------------------------------ load and draw

  async function load(focus, message, ok) {
    const data = await call('/connections/state');
    if (!data.ok) { notice('bad', data.detail || 'CLIVE would not show the connections.'); return; }
    current = data;
    drawPasskeys();
    const cards = $('#cards');
    cards.textContent = '';
    for (const connection of current.connections) cards.append(drawCard(connection));
    drawChanges();
    if (focus && message) {
      const card = document.getElementById(focus);
      if (card) result(card, ok === false ? 'bad' : 'ok', message);
    }
  }

  function fromAddress() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('done') || params.get('error');
    if (code && NOTICES[code]) notice(NOTICES[code][0], NOTICES[code][1]);
    else if (code) notice('bad', 'That did not work. Nothing changed.');
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#passkey-add').addEventListener('click', addPasskey);
    fromAddress();
    load();
  });
}());
