/* CROOKS orb — the assistant's body, drawn on a 2D canvas.
 *
 * Canvas 2D rather than CSS, SVG or WebGL. CSS cannot deform a shape organically or follow a
 * microphone; SVG filters (feTurbulence, feGaussianBlur) are rasterised on the CPU on this
 * tablet and stutter; WebGL would be smooth but a compiled shader pipeline running all day on
 * a 2019 Adreno is a battery and thermal cost the product does not need. A 340 px canvas with
 * a handful of radial gradients is GPU-composited by Chrome, costs a few milliseconds a frame,
 * and gives complete control over every state.
 *
 * The orb is drawn once at its full size and scaled by CSS when it recedes, so no state change
 * ever re-allocates the backing store. Every parameter is eased toward a per-state target, so
 * LISTENING → TRANSCRIBING → THINKING → SPEAKING is one continuous motion, never a cut.
 *
 * Frame rate is the budget: 60 fps only while something is happening, 20 fps idle, 8 fps after
 * a minute and a half, nothing at all after ten minutes or while the page is hidden. Reduced
 * motion draws a still frame per state and no loop.
 */
(function (root) {
  'use strict';

  const TAU = Math.PI * 2;

  // Every value is eased toward; none is applied as a cut.
  const BASE = {
    scale: 1, breathe: 0.012, breatheHz: 0.09, deform: 0.010, drift: 0.06, spin: 0.02,
    inner: 0.34, glow: 0.10, inward: 0, tension: 0, tint: 0, react: 0, fps: 20,
  };
  const STATES = {
    READY: {},
    LISTENING: { scale: 1.07, breathe: 0.02, breatheHz: 0.35, deform: 0.05, drift: 0.8, spin: 0.07, inner: 0.42, glow: 0.24, react: 1, fps: 60 },
    TRANSCRIBING: { scale: 0.985, breathe: 0.012, breatheHz: 1.1, deform: 0.03, drift: 1.6, spin: 0.18, inner: 0.7, glow: 0.18, fps: 40 },
    // The state the orb spends longest in; half the frames is invisible here and is what
    // keeps a 2019 tablet cool through an afternoon of questions.
    THINKING: { scale: 0.96, breathe: 0.008, breatheHz: 0.5, deform: 0.02, drift: 0.35, spin: 0.4, inner: 0.95, glow: 0.15, inward: 1, fps: 30 },
    SPEAKING: { scale: 1.035, breathe: 0.012, breatheHz: 0.6, deform: 0.032, drift: 1.0, spin: 0.1, inner: 0.5, glow: 0.26, react: 1, fps: 60 },
    SUCCESS: { scale: 1.02, breathe: 0.006, breatheHz: 0.3, deform: 0.008, drift: 0.2, spin: 0.03, inner: 0.4, glow: 0.3, tint: 1, fps: 60 },
    ERROR: { scale: 0.94, breathe: 0.004, breatheHz: 0.2, deform: 0.022, drift: 0.25, spin: 0.02, inner: 0.5, glow: 0.22, tint: -1, tension: 1, fps: 60 },
  };
  // Consulting an outside system is a different act from thinking: the orb tightens, spins
  // a little faster and takes a faint cast — cool for the store, warm for the inbox — so the
  // owner can tell from across the desk that it has gone somewhere.
  STATES['CHECKING SHOPIFY'] = Object.assign({}, STATES.THINKING, { spin: 0.65, drift: 0.5, inner: 0.9, glow: 0.2, tint: 0.5, fps: 30 });
  STATES['CHECKING EMAIL'] = Object.assign({}, STATES.THINKING, { spin: 0.55, drift: 0.45, inner: 0.9, glow: 0.2, tint: -0.45, fps: 30 });

  const NEUTRAL = [205, 208, 218];
  const GREEN = [121, 201, 150];
  const RED = [220, 127, 108];

  // A 2019 tablet cannot draw five radial gradients at sixty frames a second without heating
  // up and stuttering; the page marks itself lite on such a device and the orb halves its pace.
  const lite = () => typeof document !== 'undefined' && document.documentElement && document.documentElement.dataset.lite === '1';

  const HARMONICS = [
    { k: 2, w: 1.0, speed: 0.9 }, { k: 3, w: 0.7, speed: 1.3 }, { k: 4, w: 0.5, speed: 0.7 },
    { k: 5, w: 0.35, speed: 1.7 },
  ];
  // Translucent lobes inside the glass. Light and dark alternate, so THINKING reads as
  // density and folding rather than as a brighter LISTENING.
  const LOBES = [
    { r: 0.62, dist: 0.30, speed: 0.55, phase: 0.0, light: 1 },
    { r: 0.48, dist: 0.42, speed: -0.8, phase: 2.1, light: 0 },
    { r: 0.55, dist: 0.36, speed: 0.35, phase: 4.2, light: 1 },
    { r: 0.40, dist: 0.50, speed: -1.1, phase: 1.1, light: 0 },
  ];

  function mixTint(tint) {
    const to = tint > 0 ? GREEN : RED;
    const a = Math.min(1, Math.abs(tint));
    return [0, 1, 2].map((i) => Math.round(NEUTRAL[i] + (to[i] - NEUTRAL[i]) * a));
  }
  const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;

  function create(canvas, options) {
    options = options || {};
    const ctx = canvas.getContext('2d', { alpha: true });
    const getLevel = typeof options.getLevel === 'function' ? options.getLevel : () => 0;
    const maxDpr = options.maxDpr || 1.5;
    const isLite = lite();   // decided once, at load; not read back from the DOM every frame
    let size = options.size || canvas.clientWidth || 340;
    let reduced = Boolean(options.reducedMotion);

    let state = 'READY';
    const cur = Object.assign({}, BASE);
    let target = Object.assign({}, BASE);
    let running = false;
    let raf = 0;
    let last = 0;
    let lastDrawAt = 0;
    let t = 0;
    let stateChangedAt = 0;
    let level = 0;
    let kick = 0;
    let mark = null;          // { kind: 'check' | 'cross', progress: 0..1 }
    let disposed = false;
    const phases = HARMONICS.map((h, i) => (i * 1.7 + 0.4) % TAU);

    function now() { return (root.performance && performance.now()) || Date.now(); }

    function fit() {
      const dpr = Math.min(root.devicePixelRatio || 1, maxDpr);
      const px = Math.max(64, Math.round(size * dpr));
      if (canvas.width !== px || canvas.height !== px) {
        canvas.width = px;
        canvas.height = px;
      }
    }

    function setState(next) {
      const spec = STATES[next] || STATES.READY;
      state = STATES[next] ? next : 'READY';
      target = Object.assign({}, BASE, spec);
      stateChangedAt = now();
      if (state === 'SUCCESS') mark = { kind: 'check', progress: 0 };
      else if (state === 'ERROR') mark = { kind: 'cross', progress: 0 };
      else mark = null;
      if (reduced) { drawStill(); return; }
      start();
    }

    function pulse() { kick = 1; if (!reduced) start(); }

    function start() {
      if (running || disposed || reduced) return;
      running = true;
      last = now();
      raf = root.requestAnimationFrame(frame);
    }

    function stop() {
      running = false;
      if (raf) { root.cancelAnimationFrame(raf); raf = 0; }
    }

    function frame(ts) {
      if (!running) return;
      raf = root.requestAnimationFrame(frame);
      const dt = Math.min(0.05, Math.max(0.001, (ts - last) / 1000));
      last = ts;

      // Budget: fast while alive, slow while idle, still after a long idle.
      const idleFor = ts - stateChangedAt;
      let fps = target.fps;
      // A state left on screen is idle whatever it is called: an error nobody clears, a
      // success once its mark is drawn. Only the first moments of either earn full frames.
      const resting = (state === 'READY' || state === 'ERROR' || (state === 'SUCCESS' && idleFor > 1500));
      if (resting) {
        if (idleFor > 600000) { drawStill(); stop(); return; }
        fps = idleFor > 90000 ? 8 : 20;
      }
      if (isLite) fps = Math.min(fps, 30);
      if (ts - lastDrawAt < 1000 / fps - 2) return;
      lastDrawAt = ts;

      t += dt;
      const k = 1 - Math.exp(-dt * 5.5);
      for (const key in target) {
        if (key === 'fps') continue;
        cur[key] += (target[key] - cur[key]) * k;
      }
      const raw = Math.max(0, Math.min(1, Number(getLevel(state)) || 0));
      const lk = raw > level ? 1 - Math.exp(-dt * 28) : 1 - Math.exp(-dt * 7);
      level += (raw - level) * lk;
      kick *= Math.exp(-dt * 9);
      if (mark) mark.progress = Math.min(1, mark.progress + dt * 2.6);
      draw();
    }

    function drawStill() {
      // Reduced motion, or the long-idle frame: the state's shape and light, no motion at all.
      Object.assign(cur, target);
      const keepLevel = level; level = 0;
      const keepDeform = cur.deform; cur.deform = 0;
      if (mark) mark.progress = 1;
      draw();
      cur.deform = keepDeform; level = keepLevel;
    }

    function blob(c, R) {
      const path = new Path2D();
      const N = 72;
      const pts = new Array(N);
      const squash = 1 - 0.05 * cur.tension;
      const react = cur.react * level;
      for (let i = 0; i < N; i++) {
        const th = (i / N) * TAU;
        let r = 1;
        for (let h = 0; h < HARMONICS.length; h++) {
          const H = HARMONICS[h];
          r += cur.deform * H.w * Math.sin(H.k * th + phases[h] + t * H.speed * cur.drift * 2.2);
        }
        // Audio: outward pressure while listening, local distortion while speaking.
        r += react * 0.045 * Math.sin(6 * th + t * 11);
        r += react * 0.02 * Math.sin(9 * th - t * 7);
        pts[i] = [c + Math.cos(th) * R * r, c + Math.sin(th) * R * r * squash];
      }
      // Smooth closed curve through the midpoints.
      let [px, py] = [(pts[N - 1][0] + pts[0][0]) / 2, (pts[N - 1][1] + pts[0][1]) / 2];
      path.moveTo(px, py);
      for (let i = 0; i < N; i++) {
        const p = pts[i];
        const q = pts[(i + 1) % N];
        path.quadraticCurveTo(p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
      }
      path.closePath();
      return path;
    }

    // The orb, drawn once. It was drawn twice, as two lobes of one thing, while the owner's
    // Split divided the conversation; Split was deleted on his ruling of 8 October (DEC-071,
    // ruling 37), and the orb's divide with it.
    function draw() {
      const W = canvas.width;
      ctx.clearRect(0, 0, W, W);
      paintBody(1, 1);
    }

    function paintBody(alpha, shrink) {
      const W = canvas.width;
      const c = W / 2;
      const tint = mixTint(cur.tint);
      const react = cur.react * level;
      const s = cur.scale * (1 + cur.breathe * Math.sin(t * TAU * cur.breatheHz)) * (1 + react * 0.06 + kick * 0.03);
      const R = W * 0.31 * s * shrink;
      const glow = cur.glow + react * 0.28 + kick * 0.1;

      ctx.save();
      ctx.globalAlpha = alpha;

      // Halo: the light the glass throws on the surface it sits on.
      const halo = ctx.createRadialGradient(c, c, R * 0.86, c, c, R * 1.5);
      halo.addColorStop(0, rgba(tint, glow * 0.5));
      halo.addColorStop(0.45, rgba(tint, glow * 0.14));
      halo.addColorStop(1, rgba(tint, 0));
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(c, c, R * 1.5, 0, TAU); ctx.fill();

      // Body: black glass, lit from the upper left, rim caught on the lower right.
      const path = blob(c, R);
      const body = ctx.createRadialGradient(c - R * 0.35, c - R * 0.42, R * 0.08, c, c, R * 1.06);
      body.addColorStop(0, '#20212a');
      body.addColorStop(0.42, '#0f0f13');
      body.addColorStop(0.9, '#08080b');
      body.addColorStop(1, '#25262c');
      ctx.fillStyle = body;
      ctx.fill(path);

      ctx.save();
      ctx.clip(path);

      // Internal light, low and to the right, coloured only by a state that has a colour.
      const inner = ctx.createRadialGradient(c + R * 0.22, c + R * 0.38, 0, c + R * 0.22, c + R * 0.38, R * 1.0);
      inner.addColorStop(0, rgba(tint, 0.09 + glow * 0.4));
      inner.addColorStop(1, rgba(tint, 0));
      ctx.fillStyle = inner;
      ctx.fillRect(0, 0, W, W);

      // Membranes: lobes drifting round the centre; drawn inward and denser while thinking.
      for (let i = 0; i < LOBES.length; i++) {
        const L = LOBES[i];
        const ang = L.phase + t * cur.spin * L.speed * TAU;
        const fold = 1 - cur.inward * (0.45 + 0.3 * Math.sin(t * 1.4 + L.phase));
        const dist = R * L.dist * fold;
        const x = c + Math.cos(ang) * dist;
        const y = c + Math.sin(ang) * dist;
        const rr = R * L.r * (1 + react * 0.18 + cur.inward * 0.12);
        const g = ctx.createRadialGradient(x, y, 0, x, y, rr);
        if (L.light) {
          g.addColorStop(0, rgba(tint, cur.inner * 0.10));
          g.addColorStop(0.6, rgba(tint, cur.inner * 0.035));
          g.addColorStop(1, rgba(tint, 0));
        } else {
          g.addColorStop(0, `rgba(0,0,0,${(cur.inner * 0.32).toFixed(3)})`);
          g.addColorStop(1, 'rgba(0,0,0,0)');
        }
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, TAU); ctx.fill();
      }

      // Refraction: a thin bright arc inside the lower edge, the light bending through glass.
      ctx.beginPath();
      ctx.arc(c, c + R * 0.08, R * 0.9, 0.35 * Math.PI, 0.65 * Math.PI);
      ctx.strokeStyle = rgba(tint, 0.10 + glow * 0.25);
      ctx.lineWidth = Math.max(1, W * 0.006);
      ctx.stroke();

      // Specular highlight, top left. Small, soft, never white-hot.
      const spec = ctx.createRadialGradient(c - R * 0.44, c - R * 0.52, 0, c - R * 0.44, c - R * 0.52, R * 0.6);
      spec.addColorStop(0, 'rgba(255,255,255,0.20)');
      spec.addColorStop(0.3, 'rgba(255,255,255,0.05)');
      spec.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = spec;
      ctx.fillRect(0, 0, W, W);

      // Tension: the error state pulls the light inward and darkens the edge.
      if (cur.tension > 0.02) {
        const v = ctx.createRadialGradient(c, c, R * 0.55, c, c, R);
        v.addColorStop(0, 'rgba(0,0,0,0)');
        v.addColorStop(1, `rgba(0,0,0,${(cur.tension * 0.45).toFixed(3)})`);
        ctx.fillStyle = v;
        ctx.fillRect(0, 0, W, W);
      }
      ctx.restore();

      // Rim: soft edge illumination, brightest where the light enters.
      const rim = ctx.createLinearGradient(c - R, c - R, c + R, c + R);
      rim.addColorStop(0, 'rgba(255,255,255,0.40)');
      rim.addColorStop(0.5, 'rgba(255,255,255,0.07)');
      rim.addColorStop(1, rgba(tint, 0.22 + glow * 0.45));
      ctx.strokeStyle = rim;
      ctx.lineWidth = Math.max(1, W * 0.0042);
      ctx.stroke(path);

      if (mark) drawMark(c, R, tint);
      ctx.restore();
    }

    function drawMark(c, R, tint) {
      const p = mark.progress;
      const eased = 1 - Math.pow(1 - p, 3);
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.lineWidth = Math.max(2, canvas.width * 0.014);
      ctx.strokeStyle = rgba(tint, 0.55 + 0.35 * eased);
      ctx.beginPath();
      if (mark.kind === 'check') {
        const a = [c - R * 0.24, c + R * 0.02], b = [c - R * 0.06, c + R * 0.2], d = [c + R * 0.28, c - R * 0.18];
        const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(d[0] - b[0], d[1] - b[1]);
        const total = (l1 + l2) * eased;
        ctx.moveTo(a[0], a[1]);
        if (total <= l1) {
          const f = total / l1; ctx.lineTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f);
        } else {
          const f = (total - l1) / l2; ctx.lineTo(b[0], b[1]); ctx.lineTo(b[0] + (d[0] - b[0]) * f, b[1] + (d[1] - b[1]) * f);
        }
      } else {
        const r = R * 0.2 * eased;
        ctx.moveTo(c - r, c - r); ctx.lineTo(c + r, c + r);
        ctx.moveTo(c + r, c - r); ctx.lineTo(c - r, c + r);
      }
      ctx.stroke();
      ctx.restore();
    }

    function setReducedMotion(flag) {
      reduced = Boolean(flag);
      if (reduced) { stop(); drawStill(); } else start();
    }

    function setSize(px) {
      size = px || size;
      fit();
      if (reduced || !running) drawStill();
    }

    function destroy() {
      disposed = true;
      stop();
    }

    fit();
    setState('READY');
    if (reduced) drawStill();

    return {
      setState, pulse, start, stop, setSize, setReducedMotion, destroy,
      get state() { return state; },
      get running() { return running; },
      get level() { return level; },
    };
  }

  root.CrooksOrb = { create, STATES: Object.keys(STATES) };
})(typeof window !== 'undefined' ? window : globalThis);
