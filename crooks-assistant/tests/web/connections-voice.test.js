/* The voice panel inside ElevenLabs' details (web/connections-voice.js), under Node.
 *
 * The post-deploy review of 3 October: picking a voice and saving without touching a slider stored
 * and sent stability 0.5, similarity 0.5, expression 0.5, speed 0.95 and speaker boost on, each
 * labelled "(the voice's own)", which it was not. What is held here: a save sends a slider or the
 * speaker boost only when he moved it or it is already stored; an untouched one shows the voice's
 * own value only when ElevenLabs reported it, and otherwise says so with no number.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;
const Voice = require(path.join(__dirname, '..', '..', 'web', 'connections-voice.js'));

const HOSTILE = '<img src=x onerror="alert(1)">';
const SLIDERS = { stability: { min: 0, max: 1 }, similarity_boost: { min: 0, max: 1 }, style: { min: 0, max: 1 }, speed: { min: 0.7, max: 1.2 } };
const MODELS = { eleven_flash_v2_5: 'Flash v2.5', eleven_turbo_v2_5: 'Turbo v2.5' };
const SETTINGS = ['stability', 'similarity_boost', 'style', 'speed', 'use_speaker_boost'];

function state(voice) {
  return { voice: Object.assign({ voice_id: 'Q0Et7LOU7VpeoeCRQAVS', voice_name: 'Derek', model: 'eleven_flash_v2_5' }, voice || {}),
    models: MODELS, sliders: SLIDERS, chosen: false };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
const one = (node, selector) => node.querySelector(selector);

// A panel whose asks are recorded: what a save and a preview were handed, and which voices'
// own settings were asked for. `own` is what "ElevenLabs" reports, by voice id.
function drawn(voice, own) {
  const saved = [];
  const previewed = [];
  const asked = [];
  const on = {
    details: async (id) => { asked.push(id); return (own || {})[id] || {}; },
    save: async (values) => { saved.push(values); return { ok: true }; },
    preview: async (values) => { previewed.push(values); return { ok: true }; },
    list: async () => ({ ok: true, voices: [{ voice_id: 'Q0Et7LOU7VpeoeCRQAVS', name: 'Derek', kind: 'premade' },
      { voice_id: '9375G6zswFk7v9bKTVQF', name: 'Vikram', kind: 'professional' }] }),
  };
  const panel = Voice.panel(state(voice), { canChange: true, on });
  return { panel, saved, previewed, asked };
}

const sliderShown = (panel, key) => one(panel, '.voice-' + key).parentNode.querySelector('.slider-value').textContent;

test('picking a voice and saving with no slider touched sends the voice and nothing it did not choose', async () => {
  const { panel, saved, previewed } = drawn();
  await tick();
  one(panel, '.voice-list').dispatch('click');
  await tick();
  const pick = one(panel, '.voice-pick');
  pick.value = '9375G6zswFk7v9bKTVQF';
  pick.dispatch('change');
  await tick();
  one(panel, '.voice-preview').dispatch('click');
  one(panel, '.voice-save').dispatch('click');
  await tick();
  assert.equal(saved.length, 1);
  for (const key of SETTINGS) {
    assert.ok(!(key in saved[0]), key + ' was sent although he never touched it');
    assert.ok(!(key in previewed[0]), key + ' was previewed although he never touched it');
  }
  assert.equal(saved[0].voice_id, '9375G6zswFk7v9bKTVQF');
  assert.equal(saved[0].model, 'eleven_flash_v2_5');
});

test('a slider he moved, or the speaker boost he switched, is sent; the rest are not', async () => {
  const { panel, saved } = drawn();
  await tick();
  const style = one(panel, '.voice-style');
  style.value = '0.3';
  style.dispatch('input');
  one(panel, '.voice-boost').checked = false;
  one(panel, '.voice-boost').dispatch('change');
  one(panel, '.voice-save').dispatch('click');
  await tick();
  assert.deepEqual(Object.keys(saved[0]).filter((k) => SETTINGS.includes(k)).sort(), ['style', 'use_speaker_boost']);
  assert.equal(saved[0].style, 0.3);
  assert.equal(saved[0].use_speaker_boost, false);
  assert.equal(sliderShown(panel, 'style'), '0.30');
});

test('what is already stored is shown as it is and sent again; nothing else is added', async () => {
  const { panel, saved } = drawn({ speed: 1.1, use_speaker_boost: false });
  await tick();
  assert.equal(sliderShown(panel, 'speed'), '1.10');
  one(panel, '.voice-save').dispatch('click');
  await tick();
  assert.deepEqual(Object.keys(saved[0]).filter((k) => SETTINGS.includes(k)).sort(), ['speed', 'use_speaker_boost']);
  assert.equal(saved[0].speed, 1.1);
  assert.equal(saved[0].use_speaker_boost, false);
});

test("an untouched slider says it is the voice's own setting, with no number, when ElevenLabs reported none", async () => {
  const { panel, asked } = drawn();
  await tick();
  assert.deepEqual(asked, ['Q0Et7LOU7VpeoeCRQAVS'], "the voice in use was asked for its own settings");
  for (const key of ['style', 'stability', 'similarity_boost', 'speed']) {
    const words = sliderShown(panel, key);
    assert.equal(words, Voice.OWN, key);
    assert.ok(!/\d/.test(words), key + ' shows a number nobody reported: ' + words);
    assert.ok(one(panel, '.voice-' + key).parentNode.classList.contains('is-own'), key + ' is dimmed');
  }
  const boost = one(panel, '.voice-boost');
  assert.equal(boost.indeterminate, true, 'the speaker boost is neither on nor off until he chooses');
  assert.match(one(panel, '.voice-switch').textContent, /the voice's own setting/);
});

test("the voice's own values are shown, and said to be its own, only as ElevenLabs reported them", async () => {
  const own = { Q0Et7LOU7VpeoeCRQAVS: { stability: 0.71, use_speaker_boost: true },
    '9375G6zswFk7v9bKTVQF': { style: 0.2 } };
  const { panel, saved } = drawn({}, own);
  await tick();
  assert.equal(sliderShown(panel, 'stability'), "0.71 (the voice's own)");
  assert.equal(sliderShown(panel, 'style'), Voice.OWN, 'not reported, so no number');
  assert.equal(one(panel, '.voice-boost').checked, true);
  assert.equal(one(panel, '.voice-boost').indeterminate, false);
  // Another voice: its own values, not the last one's.
  one(panel, '.voice-list').dispatch('click');
  await tick();
  const pick = one(panel, '.voice-pick');
  pick.value = '9375G6zswFk7v9bKTVQF';
  pick.dispatch('change');
  await tick();
  assert.equal(sliderShown(panel, 'style'), "0.20 (the voice's own)");
  assert.equal(sliderShown(panel, 'stability'), Voice.OWN);
  // Shown, but still not sent: they are the voice's own already.
  one(panel, '.voice-save').dispatch('click');
  await tick();
  assert.ok(!('style' in saved[0]) && !('stability' in saved[0]) && !('use_speaker_boost' in saved[0]));
});

test("an answer about a voice no longer picked is dropped", async () => {
  let release;
  const late = new Promise((resolve) => { release = resolve; });
  const on = { details: (id) => (id === 'Q0Et7LOU7VpeoeCRQAVS' ? late : Promise.resolve({})) };
  const panel = Voice.panel(state(), { canChange: true, on });
  const pick = one(panel, '.voice-pick');
  pick.value = '9375G6zswFk7v9bKTVQF';
  pick.dispatch('change');
  release({ style: 0.9 });
  await tick();
  assert.equal(sliderShown(panel, 'style'), Voice.OWN);
});

test('nothing from the server is read as markup, and Save is off where no passkey can be asked', () => {
  const panel = Voice.panel(Object.assign(state({ voice_name: HOSTILE }), { models: { eleven_flash_v2_5: HOSTILE } }),
    { canChange: false, on: {} });
  assert.ok(panel.allText().includes(HOSTILE), 'shown as text');
  assert.equal(one(panel, '.voice-save').disabled, true);
  assert.equal(Voice.panel(null, {}), null);
});

test("\"Use the voice's own settings\" is there once something is saved, says where it goes back to, and asks the page", async () => {
  const fresh = Voice.panel(state(), { canChange: true, on: {} });
  assert.equal(one(fresh, '.voice-reset'), null, 'nothing saved here: nothing to go back from');
  const asked = [];
  const chosen = Object.assign(state({ voice_id: '9375G6zswFk7v9bKTVQF', voice_name: 'Vikram', style: 0.4 }),
    { chosen: true, configured: { voice_id: 'Q0Et7LOU7VpeoeCRQAVS', voice_name: 'Derek', model: 'eleven_flash_v2_5' } });
  const panel = Voice.panel(chosen, { canChange: true, on: { reset: async (busy) => { busy('Approve on your device…'); asked.push('reset'); return { ok: false, detail: 'Cancelled.' }; } } });
  const reset = one(panel, '.voice-reset');
  assert.equal(reset.textContent, Voice.RESET_WORDS);
  assert.match(panel.allText(), /CLIVE speaks as Derek, the voice set up on the server, in its own settings\./);
  reset.dispatch('click');
  await tick();
  assert.deepEqual(asked, ['reset']);
  assert.equal(reset.textContent, Voice.RESET_WORDS, 'back to its own words once answered');
  assert.equal(one(panel, '.more-result').textContent, 'Cancelled.');
  const locked = Voice.panel(chosen, { canChange: false, on: {} });
  assert.equal(one(locked, '.voice-reset').disabled, true, 'no passkey possible here');
});
