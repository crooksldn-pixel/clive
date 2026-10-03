/* CLIVE · Connections: asks CLIVE what it is connected to, and makes the owner's changes
 * (app/routes/connections.py). How each row looks is web/connections-view.js's, and the voice panel
 * inside ElevenLabs is web/connections-voice.js's.
 *
 * On opening, the screen draws what CLIVE last knew, then asks every connected service again
 * (POST /connections/check: at most once a minute each, however often the screen is opened) and
 * draws what is true now. It asks again when it comes back into view after a minute away.
 *
 * Every change asks for the owner's passkey at that moment, exactly as before: the server issues a
 * challenge for exactly that change, the device asks for Face ID, a fingerprint or its PIN, and the
 * server checks the answer before it touches anything. A key's approval signs the very text of the
 * values sent (sealed, below). To him it is one step: he taps Save, approves on his device, and the
 * button says what is happening until the row moves to Working. A key typed here goes to the server
 * once, is tested there before it replaces the one in use, and is never sent back. Nothing here is
 * kept in the browser's storage.
 */
(function () {
  'use strict';

  const View = window.CliveConnectionsView;
  const Voice = window.CliveConnectionsVoice;
  const $ = (selector, root) => (root || document).querySelector(selector);
  const NOTICES = {
    signed_in: ['ok', 'Instagram is connected.'],
    signed_in_untested: ['bad', 'Signed in, but the new token did not pass its test. See Instagram below.'],
    cancelled: ['bad', 'You cancelled the sign-in on Instagram. Nothing changed.'],
    stale: ['bad', 'That sign-in took too long or was already used. Start it again.'],
    refused: ['bad', "Instagram didn't accept the sign-in. Check the address in Instagram's details is in the Meta app exactly, then try again."],
    needs_app: ['bad', 'Save the Instagram app ID and app secret first.'],
    exchange: ['bad', "Instagram wouldn't turn the sign-in into a lasting token. Check the app secret."],
    unreachable: ['bad', "Instagram couldn't be reached from the server. Try again."],
    bad_code: ['bad', 'Instagram came back without a sign-in code. Start again.'],
    not_yours: ['bad', 'That sign-in was started by someone else.'],
    store_unavailable: ['bad', "This server can't keep keys for the app yet."],
  };
  const RECHECK_MS = 60 * 1000;

  let current = { connections: [], passkeys: [], changes: [], store: { ok: true, why: '' }, now: '' };
  let skew = 0;                       // the server's clock less this device's, for "2 min ago"
  let checking = new Set();
  let checkedAt = 0;
  let voiceState = null;
  let voiceAudio = null;
  const NAME = /^[a-z][a-z0-9]{1,19}$/;

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
      return { ok: false, detail: "CLIVE couldn't be reached. Check you're on Tailscale." };
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

  function canChange() {
    return passkeysWork() && current.store.ok !== false;
  }

  function said(error) {
    if (error && error.name === 'NotAllowedError') return 'Cancelled, or the passkey prompt timed out. Nothing changed.';
    if (error && error.name === 'InvalidStateError') return 'This device already has a passkey here.';
    if (error && error.detail) return error.detail;
    return "That didn't work. Nothing changed.";
  }

  async function seal(text) {
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
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

  // A change needs a passkey; with none yet, the one thing to do is set one up.
  function needPasskey(result) {
    if (current.passkeys.length) return false;
    const first = $('#first-passkey');
    if (first && !first.hidden) {
      first.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
      $('#first-passkey-add').focus();
    }
    if (result) say(result, 'bad', 'Set up your passkey first: every change asks for it.');
    return true;
  }

  function say(node, kind, text) {
    if (!node) return;
    node.className = node.className.replace(/\s*is-(ok|bad)\b/g, '') + (kind ? ' is-' + kind : '');
    node.textContent = text || '';
  }

  // ------------------------------------------------------------ the changes, each one step

  async function save(connection, form, inputs, button, result) {
    const values = {};
    for (const input of inputs) {
      const box = View.boxOf(input);
      const value = input.value.trim();
      if (!box || !value || (box.saved && value === box.saved)) continue;
      values[box.key] = value;
    }
    if (!Object.keys(values).length) { say(result, 'bad', 'Paste it in first.'); return; }
    if (needPasskey(result)) return;
    const words = button.textContent;
    const busy = (text) => { button.textContent = text; };
    button.disabled = true;
    form.classList.add('is-busy');
    say(result, '', '');
    try {
      // The passkey signs these very values: the server hashes the text it receives and refuses an
      // approval made for any other (app/routes/connections.py, sealed).
      const text = JSON.stringify(values);
      busy('Approve on your device…');
      const approval = await approve('save:' + connection.name + ':' + await seal(text));
      busy('Testing with ' + connection.label + '…');
      const done = await call('/connections/' + connection.name, { values_json: text, approval: approval });
      if (!done.ok) throw done;
      for (const input of inputs) input.value = '';
      notice('ok', about(connection, done.result.detail));
      await load({ fresh: connection.name });
    } catch (error) {
      say(result, 'bad', said(error));
      button.textContent = words;
      button.disabled = false;
      form.classList.remove('is-busy');
    }
  }

  async function check(connection, result) {
    say(result, '', 'Asking ' + connection.label + '…');
    const done = await call('/connections/' + connection.name + '/test', {});
    if (!done.ok) { say(result, 'bad', said(done)); return; }
    await load({ fresh: connection.name });
    notice(done.result.ok ? 'ok' : 'bad', about(connection, done.result.detail));
  }

  async function disconnect(connection, result) {
    if (!window.confirm('Disconnect ' + connection.label + '? CLIVE stops using it until you connect it again.')) return;
    if (needPasskey(result)) return;
    say(result, '', 'Approve on your device…');
    try {
      const approval = await approve('disconnect:' + connection.name);
      const done = await call('/connections/' + connection.name + '/disconnect', { approval: approval });
      if (!done.ok) throw done;
      notice('ok', connection.label + ' is disconnected.');
      await load({ fresh: connection.name });
    } catch (error) {
      say(result, 'bad', said(error));
    }
  }

  async function signIn(connection, button, result) {
    if (needPasskey(result)) return;
    button.disabled = true;
    say(result, '', 'Approve on your device…');
    try {
      const approval = await approve('signin:' + connection.name);
      const done = await call('/connections/' + connection.name + '/sign-in', { approval: approval });
      if (!done.ok) throw done;
      say(result, '', 'Opening Instagram…');
      window.location.assign(done.url);
    } catch (error) {
      say(result, 'bad', said(error));
      button.disabled = false;
    }
  }

  async function copy(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = 'Copied';
    } catch (error) {
      button.textContent = 'Select and copy it';
    }
  }

  async function addPasskey() {
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
    }
    await load();
  }

  async function removePasskey(key) {
    if (!window.confirm('Remove the passkey on ' + key.label + '? It will no longer approve changes.')) return;
    try {
      const approval = await approve('passkey:remove:' + key.id);
      const done = await call('/connections/passkeys/' + encodeURIComponent(key.id) + '/remove', { approval: approval });
      if (!done.ok) throw done;
      notice('ok', 'Passkey on ' + key.label + ' removed.');
    } catch (error) {
      notice('bad', said(error));
    }
    await load();
  }

  // ------------------------------------------------------------------ the voice, on ElevenLabs

  // The panel is web/connections-voice.js's; these are what it asks of CLIVE. Each answers in words
  // the panel shows ({ ok, detail }), and never throws.
  const voiceOwn = new Map();         // a voice's own settings, as ElevenLabs reported them, by voice id

  const voiceAsks = {
    list: () => call('/connections/voice/voices'),

    async details(voiceId) {
      if (voiceOwn.has(voiceId)) return voiceOwn.get(voiceId);
      const got = await call('/connections/voice/voices/' + encodeURIComponent(voiceId));
      if (!got.ok) return null;
      voiceOwn.set(voiceId, got.own || {});
      return got.own || {};
    },

    async preview(values) {
      try {
        const response = await fetch('/connections/voice/preview', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ values: values }), credentials: 'same-origin',
        });
        if (!response.ok) {
          let detail = "ElevenLabs wouldn't speak that.";
          try { detail = (await response.json()).detail || detail; } catch (error) { /* not JSON */ }
          return { ok: false, detail: detail };
        }
        if (voiceAudio) { voiceAudio.pause(); URL.revokeObjectURL(voiceAudio.src); }
        voiceAudio = new Audio(URL.createObjectURL(await response.blob()));
        await voiceAudio.play();
        return { ok: true };
      } catch (error) {
        return { ok: false, detail: "The preview couldn't be played here." };
      }
    },

    // The passkey signs the very text of the values sent, as a key's save does.
    async save(values, busy) {
      if (needPasskey(null)) return { ok: false, detail: 'Set up your passkey first: every change asks for it.' };
      try {
        const text = JSON.stringify(values);
        busy('Approve on your device…');
        const approval = await approve('voice:' + await seal(text));
        busy('Saving…');
        const done = await call('/connections/voice', { values_json: text, approval: approval });
        if (!done.ok) return { ok: false, detail: done.detail || 'The voice was not changed.' };
        voiceState.voice = done.voice;
        voiceState.chosen = done.chosen;
        notice('ok', 'CLIVE speaks as ' + done.voice.voice_name + ' from now on.');
        await load({ fresh: 'elevenlabs' });
        return { ok: true };
      } catch (error) {
        return { ok: false, detail: said(error) };
      }
    },
  };

  // "Use the voice's own settings": signed exactly as a save is, under a name of its own
  // (voice:reset:<SHA-256 of the text>), so an approval for one is never the other's.
  voiceAsks.reset = async function reset(busy) {
    if (needPasskey(null)) return { ok: false, detail: 'Set up your passkey first: every change asks for it.' };
    try {
      const text = JSON.stringify({ reset: true });
      busy('Approve on your device…');
      const approval = await approve('voice:reset:' + await seal(text));
      busy('Going back…');
      const done = await call('/connections/voice/reset', { values_json: text, approval: approval });
      if (!done.ok) return { ok: false, detail: done.detail || 'Nothing changed.' };
      voiceState.voice = done.voice;
      voiceState.chosen = false;
      notice('ok', 'CLIVE speaks as ' + done.voice.voice_name + ' again, in the voice\'s own settings.');
      await load({ fresh: 'elevenlabs' });
      return { ok: true };
    } catch (error) {
      return { ok: false, detail: said(error) };
    }
  };

  function voicePanel() {
    return voiceState ? Voice.panel(voiceState, { canChange: canChange(), on: voiceAsks }) : null;
  }

  // ------------------------------------------------------------ drawing

  // "GitHub accepted the token…" needs no "GitHub:" in front of it; "Not connected." does.
  function about(connection, detail) {
    const words = String(detail || '');
    return words.indexOf(connection.label) === 0 ? words : connection.label + ': ' + words;
  }

  function notice(kind, text) {
    const box = $('#notice');
    box.className = 'notice' + (kind ? ' is-' + kind : '');
    box.textContent = text || '';
    box.hidden = !text;
  }

  function context() {
    return {
      now: Date.now() + skew, checking, canChange: canChange(), extra: voicePanel,
      on: { save, check, disconnect, signIn, copy, addPasskey, removePasskey },
    };
  }

  // A redraw regroups every row by what is true now, and never wipes what the owner is in the
  // middle of: a row he is typing a key into (not the ID the page filled in itself), or working the
  // voice on, is kept as it is, in the place its new state puts it, with its words brought up to date.
  function draw({ fresh } = {}) {
    const ctx = context();
    $('#summary').textContent = View.summary(current, ctx);
    const holder = $('#groups');
    const active = document.activeElement;
    const kept = new Map();
    for (const row of holder.querySelectorAll('.conn[data-name]')) {
      if (View.inUse(row, active)) kept.set(row.dataset.name, row);
    }
    const open = new Set([...holder.querySelectorAll('.conn[data-name] details.conn-more[open]')]
      .map((d) => d.closest('.conn').dataset.name));
    holder.textContent = '';
    for (const section of View.groups(current, ctx)) holder.append(section);
    for (const [name, old] of kept) {
      const drawn = holder.querySelector('.conn[data-name="' + name + '"]');
      if (drawn) drawn.replaceWith(old);
    }
    // Taken out and put back, a kept row lost the cursor: it goes back where he left it.
    if (active && [...kept.values()].some((row) => row.contains(active))) active.focus({ preventScroll: true });
    touchStatuses(ctx);
    holder.setAttribute('aria-busy', checking.size ? 'true' : 'false');
    for (const name of open) {
      if (kept.has(name)) continue;
      const details = holder.querySelector('.conn[data-name="' + name + '"] details.conn-more');
      if (details) details.open = true;
    }
    if (fresh && NAME.test(fresh)) {
      const row = holder.querySelector('.conn[data-name="' + fresh + '"]');
      if (row) row.classList.add('is-fresh');
    }
    drawPasskeys(ctx);
    const changes = $('#change-list');
    changes.textContent = '';
    changes.append(View.changes(current));
  }

  function touchStatuses(ctx) {
    for (const c of current.connections) {
      if (!NAME.test(String(c.name || ''))) continue;
      const row = document.querySelector('.conn[data-name="' + c.name + '"]');
      if (!row) continue;
      const line = row.querySelector('.conn-status');
      if (line) {
        const words = View.status(c, ctx);
        line.textContent = words;
        line.hidden = !words;
      }
      const dot = row.querySelector('.dot');
      if (dot) dot.className = 'dot ' + View.tone(c, ctx);
    }
  }

  function drawPasskeys(ctx) {
    const first = $('#first-passkey');
    const section = $('#passkeys');
    if (!passkeysWork()) {
      first.hidden = true;
      section.hidden = true;
      notice('bad', "This browser can't approve changes here. Open CLIVE in Safari or Chrome at its https Tailscale address.");
      return;
    }
    first.hidden = current.passkeys.length > 0;
    section.hidden = current.passkeys.length === 0;
    const list = $('#passkey-list');
    list.textContent = '';
    if (current.passkeys.length) list.append(View.passkeys(current, ctx));
  }

  function take(data) {
    current = data;
    const server = Date.parse(data.now || '');
    if (!Number.isNaN(server)) skew = server - Date.now();
    if (data.store && data.store.ok === false) notice('bad', "This server can't keep keys for the app yet: " + data.store.why);
  }

  // Which rows the opening check will ask about: those with something to ask with that were not
  // asked within the last minute (the server keeps to the same rule, service.check_all).
  function due() {
    const now = Date.now() + skew;
    const every = (Number(current.check_every_s) || 60) * 1000;
    return new Set(current.connections.filter((c) => {
      if (!c.testable || c.state === 'not_connected') return false;
      const at = Date.parse(c.tested_at || '');
      return Number.isNaN(at) || now - at >= every;
    }).map((c) => c.name));
  }

  async function load({ fresh } = {}) {
    const data = await call('/connections/state');
    if (!data.ok) { notice('bad', data.detail || "CLIVE wouldn't show the connections."); return; }
    take(data);
    draw({ fresh });
  }

  // The connection the address names (#instagram, where Instagram's sign-in comes back to): the
  // rows are drawn after the page loads, so the browser cannot go there itself.
  function named() {
    const name = decodeURIComponent(window.location.hash.slice(1));
    return NAME.test(name) && current.connections.some((c) => c.name === name) ? name : '';
  }

  async function checkAll({ first = false } = {}) {
    checking = due();
    draw();
    const data = await call('/connections/check', {});
    checking = new Set();
    checkedAt = Date.now();
    if (data.ok) take(data);
    const name = first ? named() : '';
    draw({ fresh: name });
    if (name) {
      const row = document.getElementById(name);
      if (row) row.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
    $('#page').dataset.ready = 'true';
  }

  async function openScreen() {
    const heard = await call('/connections/voice');
    voiceState = heard.ok ? heard : null;
    const data = await call('/connections/state');
    if (!data.ok) {
      notice('bad', data.detail || "CLIVE wouldn't show the connections.");
      $('#summary').textContent = '';
      $('#page').dataset.ready = 'true';
      return;
    }
    take(data);
    await checkAll({ first: true });
  }

  function fromAddress() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('done') || params.get('error');
    if (code && NOTICES[code]) notice(NOTICES[code][0], NOTICES[code][1]);
    else if (code) notice('bad', "That didn't work. Nothing changed.");
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#first-passkey-add').addEventListener('click', addPasskey);
    fromAddress();
    openScreen();
    // "2 min ago" stays true while the screen is open, and coming back to it after a minute away
    // asks the services again.
    setInterval(() => touchStatuses(context()), 30 * 1000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && checkedAt && Date.now() - checkedAt > RECHECK_MS) checkAll();
    });
  });
}());
