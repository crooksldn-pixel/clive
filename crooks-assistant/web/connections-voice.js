/* CLIVE · Connections: the voice, inside ElevenLabs' details. Which voice CLIVE speaks in and how it
 * sounds. web/connections.js asks CLIVE and makes the change; this draws the panel and decides what a
 * save or a preview sends.
 *
 * Promises, held by tests/web/connections-voice.test.js:
 *   - a save (and a preview) sends the voice and the model, and a slider or the speaker boost only
 *     when he moved it or it is already stored. One he never touched is not sent, so ElevenLabs keeps
 *     using the voice's own setting for it (app/speech/voice_prefs.py), as it did before he opened
 *     the panel. Opening it and saving a voice changes the voice and nothing else;
 *   - an untouched slider shows the voice's own value only when ElevenLabs reported it, and says so;
 *     otherwise it says "the voice's own setting" with no number. Nothing on it is made up;
 *   - every word from the server goes in as text; no attribute is built from what it sent.
 *
 * No network and no dependency on the page: what it needs is handed in (ctx.on), so it runs under
 * Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory();
  root.CliveConnectionsVoice = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  // The sliders, in the order they are shown, with the words the owner uses rather than
  // ElevenLabs' own field names. "Expression" is `style`.
  const SLIDER_WORDS = [
    ['style', 'Expression', 'Flatter, or more performed.'],
    ['stability', 'Stability', 'Lower varies more between takes; higher stays even.'],
    ['similarity_boost', 'Similarity', 'How closely it holds to the original voice.'],
    ['speed', 'Speed', 'How fast it talks.'],
  ];
  const BOOST = 'use_speaker_boost';
  const OWN = "the voice's own setting";

  function make(tag, cls, text) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  }

  function add(parent, ...children) {
    for (const child of children) if (child) parent.appendChild(child);
    return parent;
  }

  function option(text, value) {
    const node = make('option', '', text);
    node.value = String(value || '');
    return node;
  }

  function say(node, kind, text) {
    node.className = node.className.replace(/\s*is-(ok|bad)\b/g, '') + (kind ? ' is-' + kind : '');
    node.textContent = text || '';
  }

  const has = (held, key) => Boolean(held) && held[key] !== undefined && held[key] !== null;

  // What a save or a preview sends: the voice and the model always; a slider or the speaker boost
  // only when he moved it or it is already stored, so an untouched one stays the voice's own.
  function values(form) {
    const out = { model: form.model.value };
    if (form.pick.value) {
      out.voice_id = form.pick.value;
      out.voice_name = form.names.get(form.pick.value) || '';
    }
    for (const [key, input] of Object.entries(form.sliders)) {
      if (form.moved.has(key) || has(form.held, key)) out[key] = Number(input.value);
    }
    if (form.boost && (form.moved.has(BOOST) || has(form.held, BOOST))) out[BOOST] = Boolean(form.boost.checked);
    return out;
  }

  // The words beside a slider: its value when he set it (now or before), the voice's own value when
  // ElevenLabs reported one, and otherwise no number at all.
  function sliderWords(value, { moved, held, own }) {
    if (moved || (held !== undefined && held !== null)) return Number(value).toFixed(2);
    if (own !== undefined && own !== null) return Number(own).toFixed(2) + " (the voice's own)";
    return OWN;
  }

  function panel(state, ctx) {
    if (!state) return null;
    const on = (ctx && ctx.on) || {};
    const voice = state.voice || {};
    const held = voice;                    // what is stored comes back inside the voice in use
    const form = { held, moved: new Set(), names: new Map(), sliders: {}, boost: null, own: {}, rows: {} };
    const root = make('section', 'voice');
    root.setAttribute('aria-label', 'The voice');
    add(root, make('h4', 'more-h', 'The voice'),
      make('p', 'voice-help', 'Which voice CLIVE speaks in, and how it sounds. A change counts from the next answer; nothing restarts.'));
    const result = make('p', 'more-result');
    result.setAttribute('role', 'status');

    // ------------------------------------------------------------ the voice and the model
    const pickRow = make('div', 'voice-row');
    const pickLabel = make('label', 'voice-label', 'Voice');
    const pick = make('select', 'voice-pick');
    pick.id = 'voice-pick';
    pickLabel.htmlFor = pick.id;
    // Until the voices are fetched the only option is the one speaking now: the panel is useful
    // before ElevenLabs has been asked, and asking is one tap rather than every page load.
    add(pick, option(voice.voice_name || 'The voice in use', voice.voice_id));
    form.names.set(String(voice.voice_id || ''), voice.voice_name || '');
    pick.value = String(voice.voice_id || '');
    form.pick = pick;
    const list = make('button', 'btn quiet voice-list', 'More voices');
    list.type = 'button';
    list.addEventListener('click', async () => {
      list.disabled = true;
      list.textContent = 'Asking ElevenLabs…';
      const got = on.list ? await on.list() : null;
      list.disabled = false;
      list.textContent = 'More voices';
      if (!got || !got.ok) { say(result, 'bad', (got && got.detail) || "ElevenLabs wouldn't list the voices."); return; }
      const voices = Array.isArray(got.voices) ? got.voices : [];
      pick.textContent = '';
      form.names.clear();
      for (const item of voices) {
        add(pick, option(item.kind ? item.name + ', ' + item.kind : item.name, item.voice_id));
        form.names.set(String(item.voice_id), String(item.name || ''));
      }
      if (!voices.some((v) => v.voice_id === voice.voice_id)) {
        add(pick, option((voice.voice_name || 'The voice') + ', in use', voice.voice_id));
        form.names.set(String(voice.voice_id || ''), voice.voice_name || '');
      }
      pick.value = String(voice.voice_id || '');
      say(result, 'ok', voices.length + (voices.length === 1 ? ' voice' : ' voices') + ' on this account.');
    });
    pick.addEventListener('change', () => ownOf(pick.value));
    add(pickRow, pickLabel, pick, list);

    const modelRow = make('div', 'voice-row');
    const modelLabel = make('label', 'voice-label', 'Model');
    const model = make('select', 'voice-model');
    model.id = 'voice-model';
    modelLabel.htmlFor = model.id;
    for (const [id, words] of Object.entries(state.models || {})) add(model, option(words, id));
    model.value = String(voice.model || '');
    form.model = model;
    add(modelRow, modelLabel, model);
    add(root, pickRow, modelRow);

    // ------------------------------------------------------------ the sliders and the boost
    const sliders = make('div', 'sliders');
    for (const [key, label, hint] of SLIDER_WORDS) {
      const bounds = (state.sliders || {})[key];
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
      // A slider needs somewhere to sit. Untouched and with no value of the voice's own reported, it
      // sits in the middle, dimmed, and says it is the voice's own setting rather than a number.
      input.value = has(held, key) ? held[key] : (Number(bounds.min) + Number(bounds.max)) / 2;
      input.addEventListener('input', () => { form.moved.add(key); shownFor(key); });
      form.sliders[key] = input;
      form.rows[key] = { row, shown };
      add(head, name, shown);
      add(row, head, input, make('p', 'slider-hint', hint));
      add(sliders, row);
      shownFor(key);
    }
    add(root, sliders);

    const boostRow = make('label', 'voice-switch');
    const boost = make('input', 'voice-boost');
    boost.type = 'checkbox';
    const boostText = make('span', 'voice-switch-words', 'Speaker boost');
    const boostWords = make('span', 'voice-switch-own');
    add(boostText, boostWords);
    if (has(held, BOOST)) boost.checked = Boolean(held[BOOST]);
    boost.addEventListener('change', () => { form.moved.add(BOOST); boostShown(); });
    form.boost = boost;
    add(boostRow, boost, boostText);
    add(root, boostRow);
    boostShown();

    function shownFor(key) {
      const input = form.sliders[key];
      const { row, shown } = form.rows[key];
      const moved = form.moved.has(key);
      const own = form.own[key];
      if (!moved && !has(held, key) && own !== undefined) input.value = own;
      shown.textContent = sliderWords(input.value, { moved, held: held[key], own });
      row.classList.toggle('is-own', !moved && !has(held, key) && own === undefined);
    }

    function boostShown() {
      const untouched = !form.moved.has(BOOST) && !has(held, BOOST);
      const own = form.own[BOOST];
      if (untouched && own !== undefined) boost.checked = Boolean(own);
      // Untouched, with nothing reported, the box is neither ticked nor clear: it is the voice's own.
      boost.indeterminate = untouched && own === undefined;
      boostWords.textContent = !untouched ? '' : own === undefined ? ' · ' + OWN : " · the voice's own";
    }

    // The voice's own settings, as ElevenLabs reports them: asked for the voice on show, and again
    // whenever another is picked. An answer for a voice no longer picked is dropped.
    async function ownOf(voiceId) {
      form.own = {};
      for (const key of Object.keys(form.sliders)) shownFor(key);
      boostShown();
      if (!voiceId || !on.details) return;
      const own = await on.details(voiceId);
      if (pick.value !== voiceId || !own) return;
      form.own = Object.assign({}, own);
      for (const key of Object.keys(form.sliders)) shownFor(key);
      boostShown();
    }

    // ------------------------------------------------------------ preview and save
    const actions = make('div', 'more-actions');
    const preview = make('button', 'btn voice-preview', 'Preview');
    preview.type = 'button';
    preview.addEventListener('click', async () => {
      preview.disabled = true;
      preview.textContent = 'Speaking…';
      const heard = on.preview ? await on.preview(values(form)) : null;
      say(result, heard && heard.ok ? 'ok' : 'bad', heard && heard.ok ? "That's how it will sound." : (heard && heard.detail) || "ElevenLabs wouldn't speak that.");
      preview.disabled = false;
      preview.textContent = 'Preview';
    });
    const keep = make('button', 'btn primary voice-save', 'Save the voice');
    keep.type = 'button';
    keep.disabled = !(ctx && ctx.canChange);
    keep.addEventListener('click', async () => {
      keep.disabled = true;
      say(result, '', '');
      const done = on.save ? await on.save(values(form), (text) => { keep.textContent = text; }) : null;
      keep.disabled = !(ctx && ctx.canChange);
      keep.textContent = 'Save the voice';
      if (!done || !done.ok) say(result, 'bad', (done && done.detail) || 'The voice was not changed.');
    });
    add(actions, preview, keep);
    add(root, actions, result);
    ownOf(pick.value);
    return root;
  }

  return { panel, values, sliderWords, SLIDER_WORDS, OWN };
});
