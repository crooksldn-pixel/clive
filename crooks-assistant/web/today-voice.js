/* Hold to speak, for the team: the words come from the phone itself, and only words leave it.
 *
 * George, 2 October: the team "can't speak to CLIVE like I can". His hold-to-speak sends the
 * recording to the Mac, which turns it into words with his own ElevenLabs allowance, and shows the
 * live words with a key only he may mint (web/live-voice.js, POST /voice/live). Both are his:
 * the Mac refuses a team member's recording before anything hears it ("The team types to CLIVE",
 * app/routes/turn.py, held by tests/test_staff_turn_hardening.py), and /voice/live is not one of
 * the team's routes (app/people/staff.py). Widening either spends his allowance on the team.
 *
 * So the team's hold uses the recogniser the phone already has (the Web Speech API: Chrome on
 * Android, Safari on an iPhone): the same gesture as his, the same live words under the finger,
 * and what reaches CLIVE is the sentence, sent exactly as if it had been typed. Nothing is
 * recorded, nothing is uploaded to the Mac, and nothing here touches the owner's voice path.
 *
 *   create({ onWords(text, final), onEnd(text), onState(state), onFail(reason) })
 *     .supported      whether this phone has a recogniser at all
 *     .start()        the finger went down (or a tap began listening)
 *     .stop()         the finger came up: what was heard so far is final, and onEnd gets it
 *     .cancel()       forget it: nothing is sent
 *
 * `reason` is one of this file's own words (REASONS), never the browser's message, so nothing the
 * recogniser says reaches the page as text. The words heard go to the callbacks and nowhere else:
 * not stored, not logged, not sent anywhere but where the page sends a typed sentence.
 *
 * No dependency on the page, so it runs under Node with a stand-in recogniser
 * (tests/web/today-voice.test.js), and a browser check can put a scripted one in its place.
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveTeamVoice = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  // What the page says for each way it can go wrong, in plain words.
  const REASONS = {
    unsupported: "This phone can't turn speech into words here. Type it instead.",
    blocked: 'The microphone is switched off for CLIVE. Type it, or allow the microphone in the browser settings.',
    unheard: "I didn't catch that. Hold the button and speak, or type it.",
    offline: "The phone's speech service can't be reached. Type it instead.",
    busy: 'Another app is using the microphone. Type it instead.',
  };
  const BROWSER = {
    'not-allowed': 'blocked', 'service-not-allowed': 'blocked', 'no-speech': 'unheard', 'aborted': 'unheard',
    'network': 'offline', 'audio-capture': 'busy', 'language-not-supported': 'unsupported',
  };
  const SETTLE_MS = 1800;      // after the finger comes up, how long the last words may take to arrive

  function engine() {
    return root.SpeechRecognition || root.webkitSpeechRecognition || null;
  }

  function create(hooks) {
    const on = hooks || {};
    const Engine = engine();
    let rec = null;
    let heard = '';
    let live = '';
    let ended = true;
    let stopping = false;
    let settle = 0;
    let failed = '';

    function call(name, ...args) {
      try { if (typeof on[name] === 'function') on[name](...args); } catch (e) { /* the page's own fault */ }
    }

    function finish() {
      if (ended) return;
      ended = true;
      if (settle) { clearTimeout(settle); settle = 0; }
      const text = `${heard} ${live}`.replace(/\s+/g, ' ').trim();
      heard = ''; live = '';
      rec = null;
      call('onState', 'idle');
      if (failed && !text) { call('onFail', failed); return; }
      if (!stopping) return;
      if (text) call('onEnd', text); else call('onFail', 'unheard');
    }

    function start() {
      if (!Engine) { call('onFail', 'unsupported'); return false; }
      if (!ended) return true;
      heard = ''; live = ''; failed = ''; stopping = false; ended = false;
      try {
        rec = new Engine();
        rec.lang = 'en-GB';
        rec.interimResults = true;
        rec.continuous = true;
        rec.maxAlternatives = 1;
      } catch (e) {
        ended = true;
        call('onFail', 'unsupported');
        return false;
      }
      rec.onresult = (event) => {
        let final = '';
        let interim = '';
        const results = event.results || [];
        for (let i = event.resultIndex || 0; i < results.length; i++) {
          const best = results[i] && results[i][0];
          if (!best) continue;
          if (results[i].isFinal) final += ` ${best.transcript}`; else interim += ` ${best.transcript}`;
        }
        if (final) heard = `${heard} ${final}`.trim();
        live = interim.trim();
        call('onWords', `${heard} ${live}`.trim(), !live);
      };
      rec.onerror = (event) => { failed = BROWSER[event && event.error] || 'unheard'; };
      rec.onend = () => finish();
      try { rec.start(); } catch (e) { ended = true; rec = null; call('onFail', 'busy'); return false; }
      call('onState', 'listening');
      return true;
    }

    function stop() {
      if (ended || !rec || stopping) return;      // a second "stop" while the words settle is the same stop
      stopping = true;
      call('onState', 'settling');
      try { rec.stop(); } catch (e) { finish(); return; }
      // A recogniser that never says it has ended still ends: what was heard is used.
      settle = setTimeout(finish, SETTLE_MS);
    }

    function cancel() {
      if (ended || !rec) return;
      stopping = false;
      heard = ''; live = '';
      try { rec.abort(); } catch (e) { /* already gone */ }
      finish();
    }

    return {
      get supported() { return Boolean(Engine); },
      get listening() { return !ended; },
      start, stop, cancel,
    };
  }

  return { create, REASONS, supported: () => Boolean(engine()) };
});
