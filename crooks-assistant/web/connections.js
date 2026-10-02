/* CLIVE · Connections: asks CLIVE what it is connected to, and makes the owner's changes
 * (app/routes/connections.py). How each row looks is web/connections-view.js's.
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
  const voiceNames = new WeakMap();   // an option's voice name, kept here rather than in an attribute
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

  // The sliders, in the order they are shown, with the words the owner uses rather than
  // ElevenLabs' own field names. "Expression" is `style`.
  const SLIDER_WORDS = [
    ['style', 'Expression', 'Flatter, or more performed.'],
    ['stability', 'Stability', 'Lower varies more between takes; higher stays even.'],
    ['similarity_boost', 'Similarity', 'How closely it holds to the original voice.'],
    ['speed', 'Speed', 'How fast it talks.'],
  ];

  function make(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function voiceValues(panel) {
    // What the screen is asking for, as the server takes it. A slider never touched is still sent:
    // the owner opened the panel and chose to save, so what he sees is what he gets.
    const pick = $('.voice-pick', panel);
    const values = { model: $('.voice-model', panel).value };
    if (pick.value) {
      values.voice_id = pick.value;
      const option = pick.selectedOptions[0];
      values.voice_name = option ? voiceNames.get(option) || option.textContent : '';
    }
    for (const [key] of SLIDER_WORDS) {
      const input = $('.voice-' + key, panel);
      if (input) values[key] = Number(input.value);
    }
    const boost = $('.voice-boost', panel);
    if (boost) values.use_speaker_boost = boost.checked;
    return values;
  }

  function voicePanel() {
    if (!voiceState) return null;
    const voice = voiceState.voice || {};
    const panel = make('section', 'voice');
    panel.setAttribute('aria-label', 'The voice');
    panel.append(make('h4', 'more-h', 'The voice'),
      make('p', 'voice-help', 'Which voice CLIVE speaks in, and how it sounds. A change counts from the next answer; nothing restarts.'));
    const result = make('p', 'more-result');
    result.setAttribute('role', 'status');

    const pickRow = make('div', 'voice-row');
    const pickLabel = make('label', 'voice-label', 'Voice');
    const pick = make('select', 'voice-pick');
    pick.id = 'voice-pick';
    pickLabel.htmlFor = pick.id;
    // Until the voices are fetched the only option is the one speaking now: the panel is useful
    // before ElevenLabs has been asked, and asking is one tap rather than every page load.
    pick.append(new Option(voice.voice_name || 'The voice in use', voice.voice_id || ''));
    const list = make('button', 'btn quiet voice-list', 'More voices');
    list.type = 'button';
    list.addEventListener('click', async () => {
      list.disabled = true;
      list.textContent = 'Asking ElevenLabs…';
      const got = await call('/connections/voice/voices');
      list.disabled = false;
      list.textContent = 'More voices';
      if (!got.ok) { say(result, 'bad', got.detail || "ElevenLabs wouldn't list the voices."); return; }
      pick.textContent = '';
      for (const item of got.voices) {
        const option = new Option(item.kind ? item.name + ', ' + item.kind : item.name, item.voice_id,
          false, item.voice_id === voice.voice_id);
        voiceNames.set(option, item.name);
        pick.append(option);
      }
      if (!got.voices.some((v) => v.voice_id === voice.voice_id)) {
        pick.append(new Option((voice.voice_name || 'The voice') + ', in use', voice.voice_id || '', true, true));
      }
      say(result, 'ok', got.voices.length + (got.voices.length === 1 ? ' voice' : ' voices') + ' on this account.');
    });
    pickRow.append(pickLabel, pick, list);

    const modelRow = make('div', 'voice-row');
    const modelLabel = make('label', 'voice-label', 'Model');
    const model = make('select', 'voice-model');
    model.id = 'voice-model';
    modelLabel.htmlFor = model.id;
    for (const [id, words] of Object.entries(voiceState.models || {})) model.append(new Option(words, id, false, id === voice.model));
    modelRow.append(modelLabel, model);
    panel.append(pickRow, modelRow);

    const sliders = make('div', 'sliders');
    for (const [key, label, hint] of SLIDER_WORDS) {
      const bounds = (voiceState.sliders || {})[key];
      if (!bounds) continue;
      const row = make('div', 'slider');
      const head = make('div', 'slider-head');
      const name = make('label', 'slider-label', label);
      const shown = make('span', 'slider-value');
      const input = make('input', 'voice-' + key);
      input.type = 'range';
      input.id = 'voice-' + key;
      name.htmlFor = input.id;
      input.min = bounds.min;
      input.max = bounds.max;
      input.step = 0.05;
      // Nothing stored means the voice's own default, which only ElevenLabs knows: the slider
      // starts in the middle of what it accepts and says so, rather than inventing a number.
      const held = voice[key];
      const middle = (Number(bounds.min) + Number(bounds.max)) / 2;
      input.value = held === undefined ? middle : held;
      const show = () => { shown.textContent = Number(input.value).toFixed(2) + (held === undefined && Number(input.value) === middle ? " (the voice's own)" : ''); };
      input.addEventListener('input', show);
      show();
      head.append(name, shown);
      row.append(head, input, make('p', 'slider-hint', hint));
      sliders.append(row);
    }
    panel.append(sliders);

    const boostRow = make('label', 'voice-switch');
    const boost = make('input', 'voice-boost');
    boost.type = 'checkbox';
    boost.checked = voice.use_speaker_boost !== false;
    boostRow.append(boost, document.createTextNode('Speaker boost'));
    panel.append(boostRow);

    const actions = make('div', 'more-actions');
    const preview = make('button', 'btn voice-preview', 'Preview');
    preview.type = 'button';
    preview.addEventListener('click', async () => {
      preview.disabled = true;
      preview.textContent = 'Speaking…';
      try {
        const response = await fetch('/connections/voice/preview', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ values: voiceValues(panel) }), credentials: 'same-origin',
        });
        if (!response.ok) {
          let detail = "ElevenLabs wouldn't speak that.";
          try { detail = (await response.json()).detail || detail; } catch (error) { /* not JSON */ }
          say(result, 'bad', detail);
        } else {
          if (voiceAudio) { voiceAudio.pause(); URL.revokeObjectURL(voiceAudio.src); }
          voiceAudio = new Audio(URL.createObjectURL(await response.blob()));
          await voiceAudio.play();
          say(result, 'ok', "That's how it will sound.");
        }
      } catch (error) {
        say(result, 'bad', "The preview couldn't be played here.");
      }
      preview.disabled = false;
      preview.textContent = 'Preview';
    });
    const keep = make('button', 'btn primary voice-save', 'Save the voice');
    keep.type = 'button';
    keep.disabled = !canChange();
    keep.addEventListener('click', async () => {
      if (needPasskey(result)) return;
      keep.disabled = true;
      try {
        const text = JSON.stringify(voiceValues(panel));
        keep.textContent = 'Approve on your device…';
        const approval = await approve('voice:' + await seal(text));
        const done = await call('/connections/voice', { values_json: text, approval: approval });
        if (!done.ok) { say(result, 'bad', done.detail || 'The voice was not changed.'); return; }
        voiceState.voice = done.voice;
        notice('ok', 'CLIVE speaks as ' + done.voice.voice_name + ' from now on.');
        await load({ fresh: 'elevenlabs' });
      } catch (error) {
        say(result, 'bad', said(error));
      } finally {
        keep.disabled = false;
        keep.textContent = 'Save the voice';
      }
    });
    actions.append(preview, keep);
    panel.append(actions, result);
    return panel;
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

  // A redraw must never wipe a key being typed: while a box holds something, only the words
  // that change with time are brought up to date.
  function typing() {
    const at = document.activeElement;
    return [...document.querySelectorAll('input.key-input')].some((input) => input.value) ||
      Boolean(at && at.matches && at.matches('input, select, textarea') && at.closest('.key-form, .voice'));
  }

  function draw({ fresh } = {}) {
    const ctx = context();
    $('#summary').textContent = View.summary(current, ctx);
    if (typing()) { touchStatuses(ctx); return; }
    const open = new Set([...document.querySelectorAll('.conn[data-name] > details[open], .conn[data-name] details.conn-more[open]')]
      .map((d) => d.closest('.conn').dataset.name));
    const holder = $('#groups');
    holder.textContent = '';
    for (const section of View.groups(current, ctx)) holder.append(section);
    holder.setAttribute('aria-busy', checking.size ? 'true' : 'false');
    for (const name of open) {
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
      const line = document.querySelector('.conn[data-name="' + c.name + '"] .conn-status');
      if (!line) continue;
      const words = View.status(c, ctx);
      line.textContent = words;
      line.hidden = !words;
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

  async function checkAll() {
    checking = due();
    draw();
    const data = await call('/connections/check', {});
    checking = new Set();
    checkedAt = Date.now();
    if (data.ok) take(data);
    draw();
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
    await checkAll();
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
