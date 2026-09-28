/* One AudioContext, two analysers, no second copy of any sound.
 *
 * The orb wants to know how loud the microphone is while the owner speaks and how loud the
 * ElevenLabs voice is while it answers. Both come from the Web Audio API, under three rules
 * that outrank the visuals:
 *
 *   - One AudioContext for the life of the page, created inside the first touch (Chrome will
 *     not start one anywhere else) and resumed rather than recreated.
 *   - The player's MediaElementAudioSourceNode is created once, and only after the context
 *     is confirmed running: an element bound to a suspended context plays silence, and the
 *     binding cannot be undone. Its analyser is connected on to the destination — that is
 *     the only path the voice has left once the node exists.
 *   - The microphone analyser hangs off the existing warm MediaStream. It never opens a
 *     second stream and cannot touch what MediaRecorder captures from the same tracks.
 *   - The live words (web/live-voice.js) listen through the SAME microphone source node, by
 *     tapMic: one context, one source, one stream. The tap is the caller's node, and it must
 *     lead nowhere audible; like the analyser, it cannot reach what MediaRecorder captures.
 *
 * Every failure leaves the page exactly as it was without this file: the orb approximates.
 */
(function (root) {
  'use strict';

  function create() {
    let ctx = null;
    let failed = false;
    let playerSource = null;
    let playerAnalyser = null;
    let micSource = null;
    let micAnalyser = null;
    let micStream = null;
    let buffer = null;

    function ensure() {
      // Inside a user gesture. Returns the context, or null when this device has none.
      if (failed) return null;
      if (!ctx) {
        try {
          const AC = root.AudioContext || root.webkitAudioContext;
          if (!AC) { failed = true; return null; }
          ctx = new AC();
          ctx.addEventListener('statechange', () => {
            // "interrupted" is Android losing audio focus; try to take it back quietly.
            if (ctx.state === 'interrupted') resume();
          });
        } catch (error) {
          failed = true;
          return null;
        }
      }
      resume();
      return ctx;
    }

    function resume() {
      if (!ctx || ctx.state === 'running' || ctx.state === 'closed') return Promise.resolve();
      try { return ctx.resume().catch(() => {}); } catch (error) { return Promise.resolve(); }
    }

    function attachPlayer(player) {
      // Once, and only with a running context. Returns true when the voice now flows through
      // the analyser on its way to the speaker.
      if (!ctx || playerSource || ctx.state !== 'running') return Boolean(playerSource);
      try {
        const source = ctx.createMediaElementSource(player);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.55;
        source.connect(analyser);
        analyser.connect(ctx.destination);   // without this line the voice is silent
        playerSource = source;
        playerAnalyser = analyser;
        return true;
      } catch (error) {
        return false;
      }
    }

    function attachMic(stream) {
      if (!ctx || !stream || stream === micStream) return;
      detachMic();
      try {
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.5;
        source.connect(analyser);            // analysis only: nothing reaches the speaker
        micSource = source;
        micAnalyser = analyser;
        micStream = stream;
      } catch (error) {
        micSource = micAnalyser = micStream = null;
      }
    }

    function detachMic() {
      if (micSource) { try { micSource.disconnect(); } catch (error) { /* already gone */ } }
      micSource = micAnalyser = micStream = null;
    }

    // ---- the live words' tap (web/live-voice.js)
    // A node of the caller's, fed from the microphone source the analyser already reads. False
    // when there is no source to feed it from (no context yet, or the analyser never attached):
    // the caller then does without, and nothing here opens anything to make one.
    function tapMic(node) {
      if (!ctx || !micSource || !node) return false;
      try { micSource.connect(node); return true; } catch (error) { return false; }
    }

    function untapMic(node) {
      if (!micSource || !node) return;
      try { micSource.disconnect(node); } catch (error) { /* not connected, or already gone */ }
    }

    function level(analyser) {
      if (!analyser || !ctx || ctx.state !== 'running') return 0;
      if (!buffer || buffer.length !== analyser.fftSize) buffer = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i++) {
        const v = (buffer[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / buffer.length);
      return Math.min(1, rms * 4.5);
    }

    return {
      ensure,
      resume,
      attachPlayer,
      attachMic,
      detachMic,
      tapMic,
      untapMic,
      playerLevel: () => level(playerAnalyser),
      micLevel: () => level(micAnalyser),
      get hasPlayer() { return Boolean(playerSource); },
      get hasMic() { return Boolean(micSource); },
      get state() { return ctx ? ctx.state : 'none'; },
      get micStream() { return micStream; },
      // The one context, for a tap's own nodes (web/live-voice.js). Null before the first touch.
      get context() { return ctx; },
    };
  }

  root.CrooksAudio = { create };
})(typeof window !== 'undefined' ? window : globalThis);
