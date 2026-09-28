/* The live words and the real waveform, while the owner holds the ask bar.
 *
 * What he asked for: "the voice receiver needs to actually show the audio it's hearing, and
 * maybe like the iOS screen version show a live transcription of what you're saying before
 * you release it". Two parts, both wired by web/app.js, where the microphone lives:
 *
 *   wave()    The capsule's waveform, drawn from the microphone analyser's level and from
 *             nothing else. About every 50 ms a bar enters on the right, sized by that level,
 *             and the older ones step left. Silence is low and flat; with no analyser the line
 *             is still; with reduced motion nothing scrolls. Nothing here moves on its own.
 *   create()  The words. The page asks the Mac for a single-use key (POST /voice/live), opens
 *             ElevenLabs' realtime speech-to-text with it, and streams what the warm microphone
 *             hears as 16 kHz PCM through a tap on audio-viz's one context. What comes back is
 *             shown, and nothing else is done with it: the recording is still sent whole on
 *             release, and that transcript is the one CLIVE answers.
 *
 * Rules that outrank the words:
 *   - The hold works exactly as it did without this file. Every failure (no key, a refusal, a
 *     socket that will not open or says it cannot go on) ends the words quietly; the waveform
 *     and the recording carry on.
 *   - One microphone stream and one AudioContext. The tap hangs off audio-viz's own source node
 *     (tapMic) and reaches the speaker through a gain of zero: pulled, never heard. It never asks
 *     for the microphone and never touches the recorder.
 *   - The Mac's ElevenLabs key never reaches the page. The single-use key it mints is used
 *     once, for the hold that asked for it, within the life the Mac gives it (expires_in_s) or
 *     not at all, and no copy is kept once its socket is closed. It is never stored, logged,
 *     put in the address bar or sent to telemetry.
 *   - The words are for the owner's eyes and nothing else. They go to `onWords` and nowhere
 *     more: never stored, logged or sent to telemetry, never into a question (the recording is
 *     what is sent), and forgotten here when the hold's words end. Telemetry gets how it went,
 *     in this file's own fixed words (OUTCOMES, REASONS) and numbers, and nothing the socket
 *     said: a provider's message type, error text or close reason is looked up, never copied.
 */
(function (root) {
  'use strict';

  const TARGET_RATE = 16000;
  const CHUNK_BYTES = 3200;                        // 100 ms of 16 kHz mono PCM16
  const EARLY_BYTES = 3 * TARGET_RATE * 2;         // what is kept while the socket opens: 3 s
  const FINISH_MS = 1500;                          // after the commit, how long to wait for the words to settle
  const OPEN_WAIT_MS = 5000;                       // released before the socket opened: how long it may still take
  const MAX_LIFE_S = 60;                           // the longest life the page will honour for a key, whatever it is told
  const QUIET_AFTER_REFUSAL_MS = 30000;            // a refused key is not asked for again on every hold
  const TAP_NAME = 'crooks-live-tap';

  // ------------------------------------------------------------------ audio to PCM16

  /* A streaming resampler to 16 kHz. Each output sample is the average of the input samples that
   * fall in its interval, which is a box filter: cheap, and enough to keep what is above 8 kHz
   * from folding back into speech. It carries its position from one call to the next, so the
   * blocks the tap hands over can be any length. Returns an Int16Array. */
  function createResampler(fromRate, toRate) {
    const target = toRate || TARGET_RATE;
    const ratio = Number(fromRate) > 0 ? Number(fromRate) / target : 1;
    let consumed = 0;          // input samples seen, in all
    let edge = ratio;          // the input position where the current output sample ends
    let sum = 0;
    let count = 0;
    let last = 0;
    return function push(input) {
      const out = [];
      for (let i = 0; i < input.length; i++) {
        sum += input[i];
        count += 1;
        consumed += 1;
        if (consumed >= edge) {
          last = sum / count;
          // A rate below the target repeats a sample rather than inventing one.
          do { out.push(last); edge += ratio; } while (consumed >= edge);
          sum = 0;
          count = 0;
        }
      }
      const pcm = new Int16Array(out.length);
      for (let i = 0; i < out.length; i++) {
        const s = Math.max(-1, Math.min(1, out[i]));
        pcm[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
      }
      return pcm;
    };
  }

  // Little-endian, whatever the machine: the stream is declared as pcm_16000.
  function pcmBytes(samples) {
    const bytes = new Uint8Array(samples.length * 2);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < samples.length; i++) view.setInt16(i * 2, samples[i], true);
    return bytes;
  }

  function toBase64(bytes) {
    if (typeof root.btoa === 'function') {
      let text = '';
      for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return root.btoa(text);
    }
    return root.Buffer ? root.Buffer.from(bytes).toString('base64') : '';
  }

  // One message of audio, as the realtime API takes it. `commit` on the last one only.
  function chunkMessage(bytes, commit) {
    return JSON.stringify({ message_type: 'input_audio_chunk', audio_base_64: toBase64(bytes), commit: Boolean(commit) });
  }

  // What a key may look like: the Mac's own rule (app/routes/voice.py TOKEN_SHAPE), kept here
  // too, so the page opens nothing with an answer that is not one.
  const TOKEN_SHAPE = /^[A-Za-z0-9._~+/=-]{16,2048}$/;

  // The socket's address, from what the Mac answered. Only a wss: address is opened, only with a
  // key-shaped key, and no keyterms are ever passed on: the owner had them removed because they
  // rewrote his words.
  function socketUrl(data) {
    const base = String((data && data.url) || '');
    if (!/^wss:\/\/[^\s?#]+$/.test(base) || typeof data.token !== 'string' || !TOKEN_SHAPE.test(data.token)) return '';
    const query = new URLSearchParams();
    const params = data.params && typeof data.params === 'object' ? data.params : {};
    for (const [name, value] of Object.entries(params)) {
      if (/keyterm/i.test(name) || name === 'token') continue;
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') query.set(name, String(value));
    }
    query.set('token', data.token);
    return `${base}?${query.toString()}`;
  }

  // How long the Mac says a key may be held, in seconds; 0 when the answer gives none this page
  // can honour (missing, not a number, not positive), and never more than MAX_LIFE_S.
  function keyLife(data) {
    const life = typeof (data && data.expires_in_s) === 'number' ? data.expires_in_s : NaN;
    return Number.isFinite(life) && life > 0 ? Math.min(life, MAX_LIFE_S) : 0;
  }

  /* What telemetry may be told of how the words went: these words and no others (round 9,
   * C-04). The socket's messages decide WHICH word, and never supply one: its message_type is
   * looked up in PROVIDER_ERRORS, a close code in CLOSE_CODES, the Mac's status in HTTP_STATUSES,
   * and anything not listed is 'provider_error' or 'other'. So a message type, an error's text
   * or a close reason with a customer's name in it reaches nothing. */
  const PROVIDER_ERRORS = new Map([
    ['error', 'provider_error'], ['auth_error', 'auth'], ['authentication_error', 'auth'],
    ['quota_exceeded_error', 'quota'], ['throttled_error', 'throttled'], ['rate_limited', 'throttled'],
    ['resource_exhausted_error', 'busy'], ['session_time_limit_exceeded_error', 'time_limit'],
    ['invalid_request_error', 'invalid_request'], ['chunk_size_exceeded_error', 'chunk_size'],
    ['insufficient_audio_activity_error', 'no_audio'], ['transcriber_error', 'transcriber'],
  ]);
  const HTTP_STATUSES = [400, 401, 403, 404, 405, 408, 413, 429, 500, 502, 503, 504];
  const CLOSE_CODES = [1000, 1001, 1002, 1003, 1005, 1006, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014, 1015];
  const OUTCOMES = new Set(['committed', 'timeout', 'cancelled', 'replaced', 'superseded', 'error', 'unavailable', 'slow', 'closed', 'no_tap', 'other']);
  const REASONS = new Set([
    ...PROVIDER_ERRORS.values(), 'provider_error',
    'send', 'socket', 'no_socket', 'fetch', 'bad_answer', 'expired', 'resting', 'open_wait', 'connect',
    ...HTTP_STATUSES.map((status) => `http_${status}`), 'http_other',
    ...CLOSE_CODES.map((code) => `code_${code}`), 'code_app', 'code_other', 'other',
  ]);

  // What the socket can say that means it will not go on.
  function isError(message) {
    const type = typeof message.message_type === 'string' ? message.message_type : '';
    return Boolean(message.error) || PROVIDER_ERRORS.has(type) || /_error$/.test(type);
  }
  function providerReason(message) {
    const type = typeof message.message_type === 'string' ? message.message_type : '';
    return PROVIDER_ERRORS.get(type) || 'provider_error';
  }
  function httpReason(status) {
    return HTTP_STATUSES.indexOf(status) !== -1 ? `http_${status}` : 'http_other';
  }
  function closeReason(code) {
    if (CLOSE_CODES.indexOf(code) !== -1) return `code_${code}`;
    return Number.isInteger(code) && code >= 3000 && code <= 4999 ? 'code_app' : 'code_other';
  }

  // The one shape a `live_transcript` event may have: an outcome and a reason from the lists
  // above, and three whole numbers. Anything else in `fields` is dropped, and an unknown word is
  // 'other'. web/app.js passes what reaches it through this again before telemetry sees it.
  function telemetryFields(fields) {
    const f = fields || {};
    const whole = (v) => (Number.isInteger(v) && v >= 0 && v < 1e7 ? v : undefined);
    return {
      outcome: OUTCOMES.has(f.outcome) ? f.outcome : 'other',
      reason: f.reason === undefined || f.reason === '' ? undefined : REASONS.has(f.reason) ? f.reason : 'other',
      ms: whole(f.ms), partials: whole(f.partials), count: whole(f.count),
    };
  }

  // ------------------------------------------------------------------ the tap

  // The processor, loaded from a Blob URL so the page needs no second file. It batches 1024
  // frames per message rather than posting every 128, and stops when told.
  const WORKLET_SOURCE = [
    'class CrooksLiveTap extends AudioWorkletProcessor {',
    '  constructor() {',
    '    super();',
    '    this.frames = new Float32Array(1024); this.n = 0; this.done = false;',
    '    this.port.onmessage = () => { this.done = true; };',
    '  }',
    '  process(inputs) {',
    '    const channel = inputs[0] && inputs[0][0];',
    '    if (channel) {',
    '      for (let i = 0; i < channel.length; i++) {',
    '        this.frames[this.n++] = channel[i];',
    '        if (this.n === this.frames.length) { this.port.postMessage(this.frames); this.frames = new Float32Array(1024); this.n = 0; }',
    '      }',
    '    }',
    '    return !this.done;',
    '  }',
    '}',
    `registerProcessor('${TAP_NAME}', CrooksLiveTap);`,
  ].join('\n');

  // A processor name can be registered once per context, so the module is loaded once per context.
  const loaded = typeof WeakMap === 'function' ? new WeakMap() : null;
  function loadWorklet(ctx, deps) {
    if (!ctx.audioWorklet || typeof deps.AudioWorkletNode !== 'function' || !deps.Blob || !deps.URL || !deps.URL.createObjectURL) {
      return Promise.resolve(false);
    }
    if (loaded && loaded.has(ctx)) return loaded.get(ctx);
    let url = '';
    const loading = Promise.resolve()
      .then(() => {
        url = deps.URL.createObjectURL(new deps.Blob([WORKLET_SOURCE], { type: 'application/javascript' }));
        return ctx.audioWorklet.addModule(url);
      })
      .then(() => true, () => false)
      .then((ok) => { if (url) { try { deps.URL.revokeObjectURL(url); } catch { /* gone */ } } return ok; });
    if (loaded) loaded.set(ctx, loading);
    return loading;
  }

  /* A tap on the microphone source audio-viz already has: an AudioWorkletNode, or a
   * ScriptProcessorNode where there is no worklet, into a zero gain into the destination (a node
   * nothing pulls is never run). Resolves to { rate, close() }, or null when there is no context
   * or no source to hang it from. */
  async function openTap(audio, onFrames, deps) {
    const ctx = audio && audio.context;
    if (!ctx || typeof audio.tapMic !== 'function' || !audio.hasMic) return null;
    let silent = null;
    let node = null;
    let quiet = () => {};
    try {
      silent = ctx.createGain();
      silent.gain.value = 0;
      silent.connect(ctx.destination);
    } catch { return null; }
    if (await loadWorklet(ctx, deps)) {
      try {
        node = new deps.AudioWorkletNode(ctx, TAP_NAME, { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit' });
        node.port.onmessage = (event) => onFrames(event.data);
        quiet = () => { node.port.onmessage = null; try { node.port.postMessage('stop'); } catch { /* closed */ } };
      } catch { node = null; }
    }
    if (!node && typeof ctx.createScriptProcessor === 'function') {
      try {
        node = ctx.createScriptProcessor(2048, 1, 1);
        node.onaudioprocess = (event) => onFrames(event.inputBuffer.getChannelData(0).slice(0));
        quiet = () => { node.onaudioprocess = null; };
      } catch { node = null; }
    }
    const undo = () => {
      quiet();
      if (node) { audio.untapMic(node); try { node.disconnect(); } catch { /* gone */ } }
      try { silent.disconnect(); } catch { /* gone */ }
    };
    if (!node) { undo(); return null; }
    try { node.connect(silent); } catch { undo(); return null; }
    if (!audio.tapMic(node)) { undo(); return null; }
    return { rate: ctx.sampleRate, close: undo };
  }

  // ------------------------------------------------------------------ the words

  /* The live words for one hold at a time. `begin()` on LISTENING, then `release()` or
   * `cancel()`, and `drop()` once the Mac's own transcript has taken their place. What is heard
   * so far goes to `onWords(text)`: the committed words and the current partial, and '' when
   * there is nothing to show. That is the only place the words go. */
  function create(options) {
    const opts = options || {};
    const deps = {
      audio: opts.audio || null,
      fetch: opts.fetch || (root.fetch ? root.fetch.bind(root) : null),
      WebSocket: opts.WebSocket || root.WebSocket,
      AudioWorkletNode: opts.AudioWorkletNode || root.AudioWorkletNode,
      Blob: opts.Blob || root.Blob,
      URL: opts.URL || root.URL,
      now: opts.now || (() => Date.now()),
      setTimeout: opts.setTimeout || ((fn, ms) => setTimeout(fn, ms)),
      clearTimeout: opts.clearTimeout || ((id) => clearTimeout(id)),
    };
    const onWords = typeof opts.onWords === 'function' ? opts.onWords : () => {};
    const record = typeof opts.record === 'function' ? opts.record : () => {};
    let current = null;
    let quietUntil = 0;

    function begin() {
      if (current) current.close('replaced', '', true);
      current = session();
      return current;
    }

    function session() {
      const s = {
        held: true,              // the thumb is still down
        open: false,             // the socket is open and taking audio
        done: false,
        committed: '',
        partial: '',
        pending: [],             // PCM16 bytes not sent yet, oldest first
        pendingBytes: 0,
        resample: null,
        tap: null,
        socket: null,
        controller: null,
        timer: null,
        startedAt: deps.now(),
        firstPartialMs: null,
        partials: 0,
        chunks: 0,
      };

      const words = () => `${s.committed} ${s.partial}`.replace(/\s+/g, ' ').trim();

      function frames(block) {
        if (s.done || !s.held || !s.tap) return;
        if (!s.resample) s.resample = createResampler(s.tap.rate, TARGET_RATE);
        const bytes = pcmBytes(s.resample(block));
        if (!bytes.length) return;
        s.pending.push(bytes);
        s.pendingBytes += bytes.length;
        // Three seconds and the socket still not open: the words would arrive after the point.
        if (!s.open && s.pendingBytes > EARLY_BYTES) { stop('slow'); return; }
        pump(false);
      }

      function take(size) {
        const out = new Uint8Array(size);
        let at = 0;
        while (at < size && s.pending.length) {
          const head = s.pending[0];
          const need = size - at;
          if (head.length <= need) { out.set(head, at); at += head.length; s.pending.shift(); } else {
            out.set(head.subarray(0, need), at); at += need; s.pending[0] = head.subarray(need);
          }
        }
        s.pendingBytes -= at;
        return out;
      }

      function send(bytes, commit) {
        try { s.socket.send(chunkMessage(bytes, commit)); s.chunks += 1; return true; } catch { stop('error', 'send'); return false; }
      }

      // Everything whole that is waiting, 100 ms at a time; on the release, the rest with the commit.
      function pump(last) {
        if (!s.open || s.done) return;
        while (s.pendingBytes >= CHUNK_BYTES) if (!send(take(CHUNK_BYTES), false)) return;
        if (last) {
          // A commit carries some audio: 50 ms of silence when the last whole chunk took it all.
          const rest = s.pendingBytes ? take(s.pendingBytes) : new Uint8Array(1600);
          send(rest, true);
        }
      }

      // The thumb has lifted and the socket is open: what is left goes with the commit, and the
      // words have FINISH_MS from then to settle. Never started before the socket is open, so a
      // socket that takes longer than FINISH_MS to open still gets the commit (round 9, C-05);
      // how long it may take is OPEN_WAIT_MS, counted from the release (`release`).
      function finish() {
        if (s.timer !== null) { deps.clearTimeout(s.timer); s.timer = null; }
        pump(true);
        if (s.done) return;
        s.timer = deps.setTimeout(() => close('timeout'), FINISH_MS);
      }

      function heard(message) {
        const type = typeof message.message_type === 'string' ? message.message_type : '';
        // Which word telemetry gets is looked up; nothing of the message is carried (C-04).
        if (isError(message)) { stop('error', providerReason(message)); return; }
        if (type === 'partial_transcript') {
          s.partial = String(message.text || '');
          s.partials += 1;
          if (s.firstPartialMs === null && s.partial) s.firstPartialMs = deps.now() - s.startedAt;
          onWords(words());
        } else if (type === 'committed_transcript') {
          const text = String(message.text || '').trim();
          if (text) s.committed = `${s.committed} ${text}`.trim();
          s.partial = '';
          onWords(words());
          if (!s.held) close('committed');
        }
      }

      /* One key, one socket, for this hold. The key is asked for here, checked (its shape and
       * its life), put into the socket's address and so into the socket, and held nowhere else:
       * not on `s`, not in a log, not in telemetry. Its life is counted from the ask rather than
       * the answer, because the page's clock and the Mac's need not agree and the ask is the
       * earlier of the two. A key that arrives too late, or with no life this page can honour,
       * is dropped unused. */
      async function connect() {
        if (!deps.fetch || typeof deps.WebSocket !== 'function') { stop('unavailable', 'no_socket'); return; }
        s.controller = typeof AbortController === 'function' ? new AbortController() : null;
        const askedAt = deps.now();
        let data = null;
        try {
          const response = await deps.fetch('/voice/live', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', cache: 'no-store',
            signal: s.controller ? s.controller.signal : undefined,
          });
          if (s.done) return;
          if (!response.ok) { quietUntil = deps.now() + QUIET_AFTER_REFUSAL_MS; stop('unavailable', httpReason(response.status)); return; }
          data = await response.json();
        } catch {
          if (!s.done) stop('unavailable', 'fetch');
          return;
        }
        if (s.done) return;
        const life = keyLife(data);
        const url = life ? socketUrl(data) : '';
        data = null;
        if (!url) { stop('unavailable', 'bad_answer'); return; }
        if (deps.now() - askedAt > life * 1000) { stop('unavailable', 'expired'); return; }
        let socket;
        try { socket = new deps.WebSocket(url); } catch { stop('error', 'socket'); return; }
        s.socket = socket;
        socket.onopen = () => {
          if (s.done) return;
          s.open = true;
          // What was said while it opened; and when the thumb has already lifted, the commit.
          if (s.held) pump(false); else finish();
        };
        socket.onmessage = (event) => {
          if (s.done) return;
          let message = null;
          try { message = JSON.parse(String(event.data)); } catch { return; }
          if (message && typeof message === 'object') heard(message);
        };
        socket.onerror = () => { if (!s.done) stop('error', 'socket'); };
        socket.onclose = (event) => {
          if (s.done) return;
          if (s.held) stop('closed', closeReason(event && event.code));
          else close('closed');
        };
      }

      async function start() {
        const audio = deps.audio;
        // No context or no source to tap: nothing to send, so no key is asked for either.
        if (!audio || !audio.context || !audio.hasMic) { stop('no_tap'); return; }
        if (deps.now() < quietUntil) { stop('unavailable', 'resting'); return; }
        // Never a rejection left for the page's own handler to report: its text could carry
        // the socket's address, and so the key.
        connect().catch(() => { if (!s.done) stop('error', 'connect'); });
        const tap = await openTap(audio, frames, deps);
        if (s.done || !s.held) { if (tap) tap.close(); if (!tap && !s.done) stop('no_tap'); return; }
        if (!tap) { stop('no_tap'); return; }
        s.tap = tap;
      }

      function closeTap() {
        if (s.tap) { const tap = s.tap; s.tap = null; tap.close(); }
      }

      // The end of it, whichever end. Recorded once: how it went, in this file's own words and
      // numbers (telemetryFields), never a word of what was said. Then the words, the socket and
      // with it the key are let go: nothing of this hold is kept once it is over.
      function close(outcome, reason, clear) {
        if (s.done) return;
        s.done = true;
        s.held = false;
        if (s.timer !== null) { deps.clearTimeout(s.timer); s.timer = null; }
        closeTap();
        if (s.controller) { try { s.controller.abort(); } catch { /* done */ } }
        if (s.socket) {
          const socket = s.socket;
          socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
          try { socket.close(); } catch { /* closed */ }
        }
        s.socket = null;
        s.controller = null;
        s.pending = [];
        s.pendingBytes = 0;
        if (clear) onWords('');
        record('live_transcript', telemetryFields({
          outcome, reason: reason || undefined,
          ms: s.firstPartialMs === null ? undefined : Math.round(s.firstPartialMs),
          partials: s.partials || undefined, count: s.chunks || undefined,
        }));
        s.committed = '';
        s.partial = '';
      }

      // Something went wrong: the words go quietly. While he holds they are cleared, because
      // words that stop mid-sentence read as what was heard; after the release they stay on
      // screen until the Mac's own transcript takes their place (web/app.js).
      function stop(outcome, reason) { close(outcome, reason, s.held); }

      const handle = {
        release() {
          if (s.done) return;
          s.held = false;
          closeTap();
          if (s.open) finish();
          else s.timer = deps.setTimeout(() => stop('slow', 'open_wait'), OPEN_WAIT_MS);
        },
        cancel() { close('cancelled', '', true); },
        // The Mac's transcript is on the bar: these words have done their job.
        drop() { close('superseded', '', true); },
        close,
        get words() { return words(); },
        get done() { return s.done; },
      };
      start().catch(() => { if (!s.done) stop('no_tap'); });
      return handle;
    }

    return {
      begin,
      release() { if (current) current.release(); },
      cancel() { if (current) current.cancel(); },
      drop() { if (current) current.drop(); },
      get active() { return Boolean(current && !current.done); },
    };
  }

  // ------------------------------------------------------------------ the waveform

  const STEP_MS = 50;
  const BAR = 3;
  const GAP = 3;
  const LOW = 3;            // a bar's height in silence: a dot, not nothing
  const FLOOR = 0.04;       // below this the analyser is hearing the room, not a voice

  // How tall a bar is for a level from audio-viz (0 to 1): the room's hum stays flat.
  function barHeight(level, height) {
    const top = Math.max(LOW, height);
    const heard = Math.max(0, Math.min(1, ((Number(level) || 0) - FLOOR) / (1 - FLOOR)));
    return LOW + (top - LOW) * Math.pow(heard, 0.7);
  }

  /* The capsule's waveform. options: canvas() → the canvas or null; analyser() → whether there
   * is a real level to read; level() → that level, 0 to 1; reduced() → prefers-reduced-motion.
   * Bars are placed in fixed slots and move only when a new level arrives, so a quiet room draws
   * a line that does not move. */
  function wave(options) {
    const opts = options || {};
    const frame = opts.frame || ((fn) => (root.requestAnimationFrame ? root.requestAnimationFrame(fn) : setTimeout(() => fn(Date.now()), 16)));
    const unframe = opts.cancelFrame || ((id) => (root.cancelAnimationFrame ? root.cancelAnimationFrame(id) : clearTimeout(id)));
    const now = opts.now || (() => (root.performance ? root.performance.now() : Date.now()));
    const analyser = opts.analyser || (() => false);
    const level = opts.level || (() => 0);
    const reduced = opts.reduced || (() => false);
    let levels = [];          // newest last
    let handle = null;
    let stepAt = 0;
    let peak = 0;
    let size = { w: 0, h: 0 };

    function context() {
      const canvas = opts.canvas ? opts.canvas() : null;
      if (!canvas || !canvas.getContext) return null;
      const g = canvas.getContext('2d');
      if (!g) return null;
      const rect = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: canvas.width, height: canvas.height };
      const dpr = opts.dpr || root.devicePixelRatio || 1;
      if (rect.width !== size.w || rect.height !== size.h || canvas.width !== Math.round(rect.width * dpr)) {
        size = { w: rect.width, h: rect.height };
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
      }
      if (g.setTransform) g.setTransform(dpr, 0, 0, dpr, 0, 0);
      return g;
    }

    function bar(g, x, h) {
      const y = (size.h - h) / 2;
      if (g.roundRect) { g.beginPath(); g.roundRect(x, y, BAR, h, BAR / 2); g.fill(); } else g.fillRect(x, y, BAR, h);
    }

    function draw() {
      const g = context();
      if (!g || !size.w || !size.h) return;
      g.clearRect(0, 0, size.w, size.h);
      g.fillStyle = '#ffffff';
      const pitch = BAR + GAP;
      const slots = Math.floor((size.w + GAP) / pitch);
      const left = (size.w - (slots * pitch - GAP)) / 2;
      if (reduced()) {
        // No scrolling: the row stands still and says how loud it is now, highest in the middle.
        const current = levels.length ? levels[levels.length - 1] : 0;
        for (let i = 0; i < slots; i++) {
          const middle = 1 - Math.abs((i + 0.5) / slots - 0.5) * 1.4;
          g.globalAlpha = 0.9;
          bar(g, left + i * pitch, barHeight(current * middle, size.h));
        }
        g.globalAlpha = 1;
        return;
      }
      // Newest on the right; the older a bar, the further left and the fainter.
      for (let slot = 0; slot < slots; slot++) {
        const age = slots - 1 - slot;
        const value = age < levels.length ? levels[levels.length - 1 - age] : 0;
        g.globalAlpha = 0.35 + 0.65 * Math.min(1, slot / (slots * 0.35));
        bar(g, left + slot * pitch, barHeight(value, size.h));
      }
      g.globalAlpha = 1;
    }

    function tick() {
      handle = null;
      const t = now();
      peak = Math.max(peak, Number(level()) || 0);
      if (t - stepAt >= STEP_MS) {
        levels.push(peak);
        if (levels.length > 240) levels = levels.slice(-120);
        peak = 0;
        stepAt = t;
        draw();
      }
      handle = frame(tick);
    }

    function stop() {
      if (handle !== null) unframe(handle);
      handle = null;
      levels = [];
      peak = 0;
      draw();
    }

    function start() {
      stop();
      if (!analyser()) return;   // no analyser: the still, quiet line stop() just drew
      if (!opts.canvas || !opts.canvas()) return;   // nowhere to draw (the tablet's own layout)
      stepAt = now();
      handle = frame(tick);
    }

    return {
      start,
      stop,
      get running() { return handle !== null; },
      get levels() { return levels.slice(); },
    };
  }

  const api = {
    create, wave, createResampler, pcmBytes, toBase64, chunkMessage, socketUrl, barHeight, isError, keyLife,
    telemetryFields, OUTCOMES, REASONS,
    CHUNK_BYTES, EARLY_BYTES, FINISH_MS, OPEN_WAIT_MS, MAX_LIFE_S, TARGET_RATE, STEP_MS,
  };
  root.CrooksLiveVoice = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
