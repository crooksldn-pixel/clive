/* CLIVE's dots: one pool of points that plays every part on a screen and in the app's start-up.
 *
 * The same dots are CLIVE's orb (a turning point-cloud sphere), the ring of dust around it, the
 * dot-matrix clock, the drifting dust, and whatever CLIVE puts on a screen: they fly to where the
 * real page's letters, panels and badges are, land as coarse blocks top first, sharpen as a scan
 * passes, and hand over to the real page. Each dot is either in a role (orb, ring, dust, rest) or
 * flying a queued segment. They are added, not painted, into one pixel buffer, with a quarter-size
 * copy blurred beneath for bloom; a second canvas carries the light that is not dots (the start-up's
 * spark, flash and glints, and the orb's glass body).
 *
 * Nothing here reads or sends anything: the pages decide what the dots form (web/display.js,
 * web/startup.js). Paused when off screen or hidden; cheaper when shown small.
 *
 * Round 11. On a screen the page the dots form can carry a customer's details, as the shapes of
 * its letters. So what a page drew can be let go of at once (forget); the check for a slip
 * marked packed comes out of the orb rather than out of the slip (packOut); and an engine
 * destroyed forgets every dot's place and empties its canvases there and then (destroy).
 *
 * Round 12. Something new put in place of what is up goes straight there (swap): the dots come
 * out of the small orb in the corner to the new page, with no journey home to the clock first.
 * A forgotten dot is put back in the orb, so it keeps not even the position of what it drew.
 */
'use strict';

(function (root) {
  const TAU = Math.PI * 2;
  // The colours dots take in their roles. A screen (web/display.js, the one layout with a dot
  // clock) and the app's start-up are both steel and white, as the approved designs have them (the
  // owner took the purple out of the app on 28 Sep 2026). `tint` (1) fades either toward GREY, the
  // neutral light of the start-up's flash.
  //   back, mid, front: the orb's far side, its rim and its lit face · ring, dust: their dots ·
  //   seed: a dot before it has a role · spark: the orb's burst · fading: dots on their way out ·
  //   home: stray dots poured back into the orb · pour: a typed name poured in · done: the check.
  const PALETTES = {
    steel: {
      back: [62, 68, 80], mid: [156, 164, 184], front: [250, 252, 255], ring: [206, 214, 228], dust: [198, 206, 220],
      seed: [220, 226, 236], spark: [228, 234, 244], fading: [198, 206, 220], home: [232, 236, 244], pour: [240, 244, 250], done: [48, 209, 88],
    },
  };
  const GREY = { back: [60, 66, 78], mid: [152, 162, 182], front: [244, 246, 252], ring: [215, 222, 235], dust: [200, 208, 222] };

  function create(o) {
    const L = o.L, W = o.W, H = o.H, U = L.u || 1, rnd = Math.random;
    const canvas = o.canvas, bloomEl = o.bloom || null, fxEl = o.fx || null, host = o.root;
    let speed = o.speed || 1;
    const calm = !!o.calm;
    const drift = typeof o.drift === 'function' ? o.drift : () => ({ x: 0, y: 0 });
    const N = Math.max(3000, Math.min(26000, Math.round(o.density || 14000)));
    const ORB_N = Math.min(2800, Math.round(N * 0.2));
    const CLOCK_N = L.clock ? Math.min(4200, Math.round(N * 0.24)) : 0;
    const DUST_N = Math.min(900, Math.round(N * 0.05));
    const RING_N = Math.min(560, Math.round(N * 0.04));
    const P = [], ORBS = [], RINGS = [], RES = [];
    const C = PALETTES[o.palette] || PALETTES.steel;
    const orbHome = L.orb || { cx: W / 2, cy: H / 2, R: Math.min(W, H) * 0.2 };
    const orb = {
      cx: orbHome.cx, cy: orbHome.cy, R: orbHome.R, e: 0, tcx: orbHome.cx, tcy: orbHome.cy, tR: orbHome.R, te: 1,
      idle: 1, tidle: 1, tint: 0, ttint: 0, rip: -99, ax: 0, ay: 1, az: 0,
    };
    const body = { a: 0, ta: 0 }, net = { a: 0, ta: 0 };
    let T = 0, dustLevel = 0, dustTarget = calm ? 0.18 : 0.34, nextRip = 4, dx = 0, dy = 0;
    let shimC = { x: W / 2, y: H / 2, t0: -99 };
    let noise = null;
    let uiSet = [], clockLive = [], nameLive = [];
    let bootT0 = -99, bootOn = false, bootS = { x: W / 2, y: H / 2 }, glints = [], stillGlint = null, resCur = 0;
    const cbs = [];
    const tmp = { x: 0, y: 0, r: 0, g: 0, b: 0, a: 0, s: 0 };
    const f3 = (v) => (v > 1 ? 1 : v < 0 ? 0 : v).toFixed(3);

    for (let i = 0; i < N; i++) {
      const home = i < ORB_N ? 'orb' : i < ORB_N + CLOCK_N ? 'clock' : i < ORB_N + CLOCK_N + DUST_N ? 'dust' : 'res';
      const p = {
        i, home, role: 'gone', x: orbHome.cx, y: orbHome.cy, r: C.seed[0], g: C.seed[1], b: C.seed[2], a: 0, s: 1.4,
        q: [], seg: null, tx: 0, ty: 0, ta: 0, ts: 1.5, shim: 0, dr: false, ph: rnd(), fade: null, uiT: null,
        keep: false, ring: false, ox: 0, oy: 0, oz: 0, rt: 0, rr: 1.6, ry: 0, _k: 0,
      };
      if (home === 'orb') {
        const kk = i + 0.5, phi = Math.acos(1 - 2 * kk / ORB_N), th = Math.PI * (1 + Math.sqrt(5)) * kk;
        p.ox = Math.cos(th) * Math.sin(phi); p.oy = Math.cos(phi); p.oz = Math.sin(th) * Math.sin(phi);
        p.role = 'orb';
        p.keep = i % 6 === 0;
        ORBS.push(p);
      } else if (home === 'dust') {
        p.role = 'dust'; p.x = rnd() * W; p.y = rnd() * H; p.s = (1 + rnd() * 0.8) * Math.min(1.3, 0.5 + U * 0.5);
      } else if (home === 'res' && RINGS.length < RING_N) {
        p.ring = true; p.role = 'ring'; p.rt = rnd() * TAU; p.rr = 1.45 + rnd() * 0.35; p.ry = (rnd() - 0.5) * 12;
        RINGS.push(p);
      } else if (home === 'res') {
        RES.push(p);
      }
      P.push(p);
    }

    // A loose network across the sphere's surface (the start-up's glass orb).
    const pairs = [];
    (function () {
      const pick = [];
      for (let i = 0; i < 110 && ORBS.length; i++) pick.push(ORBS[Math.floor(rnd() * ORBS.length)]);
      for (let i = 0; i < pick.length; i++) {
        const a = pick[i];
        let b1 = null, d1 = 1e9, b2 = null, d2 = 1e9;
        for (let j = 0; j < pick.length; j++) {
          const b = pick[j];
          if (b === a) continue;
          const dd = (a.ox - b.ox) * (a.ox - b.ox) + (a.oy - b.oy) * (a.oy - b.oy) + (a.oz - b.oz) * (a.oz - b.oz);
          if (dd < 0.004) continue;
          if (dd < d1) { b2 = b1; d2 = d1; b1 = b; d1 = dd; } else if (dd < d2) { b2 = b; d2 = dd; }
        }
        if (b1) pairs.push([a, b1]);
        if (b2) pairs.push([a, b2]);
      }
    })();

    // ---- the parts ----------------------------------------------------------------------
    const cP = Math.cos(0.42), sP = Math.sin(0.42);
    function orbAt(p, out) {
      const yaw = T * 0.16, c = Math.cos(yaw), s = Math.sin(yaw);
      const x1 = p.ox * c + p.oz * s, z1 = -p.ox * s + p.oz * c, y1 = p.oy;
      const y2 = y1 * cP - z1 * sP, z2 = y1 * sP + z1 * cP;
      const n = Math.sin(p.ox * 3.1 + T * 0.8) * Math.sin(p.oy * 2.6 - T * 0.62) * Math.sin(p.oz * 3.4 + T * 0.47);
      let w = 0;
      const rt = (T - orb.rip) * 1.5;
      if (rt > 0 && rt < 3.4) {
        const dot = p.ox * orb.ax + p.oy * orb.ay + p.oz * orb.az;
        const ang = Math.acos(dot < -1 ? -1 : dot > 1 ? 1 : dot);
        const q = ang - rt;
        w = Math.exp(-(q * q) / 0.045) * (1 - rt / 3.4);
      }
      const rr = orb.R * (1 + 0.065 * n + 0.13 * w);
      const d01 = (z2 + 1) * 0.5, persp = 1 + z2 * 0.14;
      out.x = orb.cx + dx + x1 * rr * persp;
      out.y = orb.cy + dy + y2 * rr * persp;
      const sc = orb.R / 250 < 0.5 ? 0.5 : orb.R / 250 > 1 ? 1 : orb.R / 250;
      out.s = (0.85 + 1.7 * d01) * sc + w * 0.9;
      const mini = orb.R < 60 ? 0.4 + 0.6 * (orb.R / 60) : 1;
      out.a = (0.14 + 0.8 * Math.pow(d01, 1.4)) * (1 + 1.3 * w) * orb.e * mini;
      const lo = d01 < 0.5, t = lo ? d01 * 2 : (d01 - 0.5) * 2;
      const c0 = lo ? C.back : C.mid, c1 = lo ? C.mid : C.front, n0 = lo ? GREY.back : GREY.mid, n1 = lo ? GREY.mid : GREY.front;
      const r = c0[0] + (c1[0] - c0[0]) * t, g = c0[1] + (c1[1] - c0[1]) * t, b = c0[2] + (c1[2] - c0[2]) * t;
      const r2 = n0[0] + (n1[0] - n0[0]) * t, g2 = n0[1] + (n1[1] - n0[1]) * t, b2 = n0[2] + (n1[2] - n0[2]) * t;
      const m = orb.tint;
      out.r = r + (r2 - r) * m; out.g = g + (g2 - g) * m; out.b = b + (b2 - b) * m;
    }
    const cT = Math.cos(-0.3), sT = Math.sin(-0.3);
    function ringAt(p, out) {
      const th = p.rt + T * 0.11;
      const ex = Math.cos(th) * p.rr * orb.R, ey = Math.sin(th) * p.rr * orb.R * 0.24 + p.ry * (orb.R / 250);
      const x = ex * cT - ey * sT, y = ex * sT + ey * cT;
      const front = Math.sin(th) > 0;
      const vis = Math.max(0, Math.min(1, (orb.R - 40) / 60));
      let a = (front ? 0.5 : 0.2) * orb.e * vis;
      if (!front && x * x + y * y < orb.R * orb.R * 0.9) a *= 0.12;
      out.x = orb.cx + dx + x; out.y = orb.cy + dy + y;
      out.a = a; out.s = (front ? 1.5 : 1.1) * Math.min(1, 0.45 + orb.R / 400);
      const m = orb.tint;
      out.r = C.ring[0] + (GREY.ring[0] - C.ring[0]) * m; out.g = C.ring[1] + (GREY.ring[1] - C.ring[1]) * m; out.b = C.ring[2] + (GREY.ring[2] - C.ring[2]) * m;
    }
    function dustStep(p, dt) {
      const k = Math.max(0.5, U * 0.42);
      const vx = (Math.sin(p.y * 0.0042 + T * 0.07 + p.ph * 6) + 0.6 * Math.cos(p.x * 0.0031 - T * 0.05)) * 10 * k;
      const vy = ((Math.cos(p.x * 0.0037 - T * 0.06 + p.ph * 3) + 0.6 * Math.sin(p.y * 0.0029 + T * 0.04)) * 8 - 3) * k;
      p.x += vx * dt; p.y += vy * dt;
      if (p.x < -20) p.x += W + 40; else if (p.x > W + 20) p.x -= W + 40;
      if (p.y < -20) p.y += H + 40; else if (p.y > H + 20) p.y -= H + 40;
      const m = orb.tint;
      p.r = C.dust[0] + (GREY.dust[0] - C.dust[0]) * m; p.g = C.dust[1] + (GREY.dust[1] - C.dust[1]) * m; p.b = C.dust[2] + (GREY.dust[2] - C.dust[2]) * m;
      p.a = dustLevel * (0.3 + 0.7 * (0.5 + 0.5 * Math.sin(T * 0.8 + p.ph * 40)));
    }

    // ---- flight -------------------------------------------------------------------------
    const EASE = {
      out: (k) => 1 - (1 - k) * (1 - k) * (1 - k),
      inout: (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2),
      back: (k) => { const c1 = 1.5, c3 = c1 + 1, m = k - 1; return 1 + c3 * m * m * m + c1 * m * m; },
    };
    function startSeg(p, sg) {
      if (sg.from) { p.x = sg.from[0]; p.y = sg.from[1]; }
      if (sg.fromA !== undefined) p.a = sg.fromA;
      sg.sx = p.x; sg.sy = p.y; sg.r0 = p.r; sg.g0 = p.g; sg.b0 = p.b; sg.a0 = p.a; sg.s0 = p.s;
      p.seg = sg; p.role = 'seg'; p.fade = null;
    }
    function endSeg(p, sg) {
      p.seg = null;
      p.x = sg.tx; p.y = sg.ty; p.r = sg.r1; p.g = sg.g1; p.b = sg.b1; p.a = sg.a1; p.s = sg.s1;
      const th = sg.then || 'rest';
      if (th === 'rest') {
        p.role = 'rest'; p.ta = sg.a1; p.ts = sg.s1; p.shim = sg.shim || 0; p.dr = !!sg.dr;
        if (sg.dr) { p.tx = sg.bx; p.ty = sg.by; } else { p.tx = sg.tx; p.ty = sg.ty; }
      } else if (th === 'orb' || th === 'ring' || th === 'dust') {
        p.role = th;
      } else {
        p.role = 'gone'; p.a = 0;
      }
    }
    function stepSeg(p) {
      const sg = p.seg;
      if (sg.then === 'orb' || sg.then === 'ring') {
        if (sg.then === 'orb') orbAt(p, tmp); else ringAt(p, tmp);
        sg.tx = tmp.x; sg.ty = tmp.y; sg.r1 = tmp.r; sg.g1 = tmp.g; sg.b1 = tmp.b; sg.a1 = tmp.a; sg.s1 = tmp.s;
      } else if (sg.dr) {
        sg.tx = sg.bx + dx; sg.ty = sg.by + dy;
      }
      let k = (T - sg.t0) / sg.d;
      if (k >= 1) { endSeg(p, sg); return; }
      if (k < 0) k = 0;
      const e = EASE[sg.ease || 'inout'](k), u = 1 - e;
      const mx = (sg.sx + sg.tx) * 0.5 + (sg.kx || 0), my = (sg.sy + sg.ty) * 0.5 + (sg.ky || 0);
      p.x = u * u * sg.sx + 2 * u * e * mx + e * e * sg.tx;
      p.y = u * u * sg.sy + 2 * u * e * my + e * e * sg.ty;
      const kl = k * 1.2 > 1 ? 1 : k * 1.2;
      p.r = sg.r0 + (sg.r1 - sg.r0) * kl; p.g = sg.g0 + (sg.g1 - sg.g0) * kl; p.b = sg.b0 + (sg.b1 - sg.b0) * kl;
      p.a = sg.a0 + (sg.a1 - sg.a0) * kl; p.s = sg.s0 + (sg.s1 - sg.s0) * kl;
    }
    function stepRest(p) {
      let x = p.tx, y = p.ty;
      if (p.dr) { x += dx; y += dy; }
      p.x = x + Math.sin(T * 1.3 + p.ph * 40) * 0.35;
      p.y = y + Math.cos(T * 1.1 + p.ph * 30) * 0.35;
      let a = p.ta, s = p.ts;
      if (p.shim === 1) {
        const pos = ((T * 240) % (W + 1400)) - 500;
        const q = (p.tx * 0.8 + p.ty * 0.35 - pos) / 70;
        const b = Math.exp(-q * q);
        a *= 1 + 0.8 * b; s += 0.8 * b;
      } else if (p.shim === 2) {
        const pos = (T - shimC.t0) * 520;
        if (pos > 0) {
          const dd = Math.hypot(p.tx - shimC.x, p.ty - shimC.y);
          const q = (dd - (pos % 1100)) / 46;
          const b = Math.exp(-q * q);
          a *= 1 + 1.1 * b; s += 0.9 * b;
        }
      }
      if (p.fade) {
        const f = p.fade, k = (T - f.t0) / f.d;
        if (k >= 1) {
          p.fade = null;
          if (f.then === 'dust') { p.role = 'dust'; } else { p.role = 'gone'; p.a = 0; return; }
        } else if (k > 0) a *= 1 - k;
      }
      p.a = a; p.s = s;
    }
    function update(dt) {
      T += dt;
      const kE = 1 - Math.exp(-dt / 0.3), kS = 1 - Math.exp(-dt / 0.9), kB = 1 - Math.exp(-dt / 0.35), kT = 1 - Math.exp(-dt / 0.8);
      orb.cx += (orb.tcx - orb.cx) * kE; orb.cy += (orb.tcy - orb.cy) * kE; orb.R += (orb.tR - orb.R) * kE;
      orb.e += (orb.te - orb.e) * kS; orb.idle += (orb.tidle - orb.idle) * kE; orb.tint += (orb.ttint - orb.tint) * kT;
      body.a += (body.ta - body.a) * kB; net.a += (net.ta - net.a) * kB;
      dustLevel += (dustTarget - dustLevel) * kS;
      const d = drift(Date.now() / 1000);
      dx = d.x * orb.idle; dy = d.y * orb.idle;
      if (!calm && orb.tidle === 1 && T > nextRip) {
        const z = rnd() * 2 - 1, a = rnd() * TAU, r = Math.sqrt(1 - z * z);
        orb.ax = r * Math.cos(a); orb.ay = z; orb.az = r * Math.sin(a);
        orb.rip = T; nextRip = T + 7 + rnd() * 5;
      }
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        if (p.q.length && T >= p.q[0].t0) startSeg(p, p.q.shift());
        const r = p.role;
        if (r === 'orb' || r === 'ring') {
          if (r === 'orb') orbAt(p, tmp); else ringAt(p, tmp);
          p.x = tmp.x; p.y = tmp.y; p.r = tmp.r; p.g = tmp.g; p.b = tmp.b; p.a = tmp.a; p.s = tmp.s;
        } else if (r === 'dust') dustStep(p, dt);
        else if (r === 'seg') stepSeg(p);
        else if (r === 'rest') stepRest(p);
      }
      while (cbs.length && T >= cbs[0].t) {
        const cb = cbs.shift();
        try { cb.fn(T); } catch (e) { /* a page callback never stops the dots */ }
      }
    }

    // ---- drawing ------------------------------------------------------------------------
    let rs = 0, CW = 0, CH = 0, ctx = null, img = null, buf = null, u32 = null, bctx = null, fctx = null;
    function sizeCanvas(s) {
      rs = s; CW = Math.max(1, Math.round(W * s)); CH = Math.max(1, Math.round(H * s));
      canvas.width = CW; canvas.height = CH;
      ctx = canvas.getContext('2d');
      img = ctx.createImageData(CW, CH); buf = img.data; u32 = new Uint32Array(buf.buffer);
      if (fxEl) { fxEl.width = CW; fxEl.height = CH; fctx = fxEl.getContext('2d'); }
      if (bloomEl) {
        bloomEl.width = Math.max(1, CW >> 2); bloomEl.height = Math.max(1, CH >> 2);
        bctx = bloomEl.getContext('2d');
      }
    }
    // One soft square dot, box-filtered so it moves smoothly between pixels; added, not painted.
    function splat(px, py, sz, r, g, b, a) {
      if (sz < 1) { a *= sz; sz = 1; }
      const x0 = px - sz * 0.5, y0 = py - sz * 0.5, x1 = x0 + sz, y1 = y0 + sz;
      let ix0 = Math.floor(x0), iy0 = Math.floor(y0), ix1 = Math.ceil(x1) - 1, iy1 = Math.ceil(y1) - 1;
      if (ix1 < 0 || iy1 < 0 || ix0 >= CW || iy0 >= CH) return;
      if (ix0 < 0) ix0 = 0;
      if (iy0 < 0) iy0 = 0;
      if (ix1 >= CW) ix1 = CW - 1;
      if (iy1 >= CH) iy1 = CH - 1;
      const R = r * a, G = g * a, B = b * a;
      for (let yy = iy0; yy <= iy1; yy++) {
        const wy = Math.min(yy + 1, y1) - Math.max(yy, y0);
        if (wy <= 0) continue;
        let idx = (yy * CW + ix0) * 4;
        for (let xx = ix0; xx <= ix1; xx++, idx += 4) {
          const w = (Math.min(xx + 1, x1) - Math.max(xx, x0)) * wy;
          if (w <= 0) continue;
          buf[idx] += R * w; buf[idx + 1] += G * w; buf[idx + 2] += B * w;
        }
      }
    }
    function noiseLevel() {
      if (!noise || T < noise.t0) return 0;
      if (T > noise.t1) {
        const k = (T - noise.t1) / 0.4;
        if (k >= 1) { noise = null; return 0; }
        return 1 - k;
      }
      return Math.min(1, (T - noise.t0) / 0.5);
    }
    function noiseFront() {
      const k = (T - noise.tf) / noise.fd;
      return k <= 0 ? 0 : k >= 1 ? H : k * H;
    }
    function arm(x0, y0, x1, y1, I, w) {
      if (I <= 0.002) return;
      const g = fctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, 'rgba(210,222,245,0)');
      g.addColorStop(0.5, 'rgba(255,255,255,' + f3(I) + ')');
      g.addColorStop(1, 'rgba(210,222,245,0)');
      fctx.strokeStyle = g; fctx.lineWidth = w;
      fctx.beginPath(); fctx.moveTo(x0, y0); fctx.lineTo(x1, y1); fctx.stroke();
    }
    function glow(x, y, r, a) {
      if (r <= 0 || a <= 0.002) return;
      const g = fctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, 'rgba(255,255,255,' + f3(a) + ')');
      g.addColorStop(0.3, 'rgba(226,234,248,' + f3(a * 0.45) + ')');
      g.addColorStop(1, 'rgba(200,214,240,0)');
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, r, 0, TAU); fctx.fill();
    }
    // Black glass: lit from the upper left, a rim, a soft halo, a faint lower reflection.
    function drawBody() {
      const x = orb.cx + dx, y = orb.cy + dy, R = Math.max(1, orb.R * 0.98), a = body.a;
      let g = fctx.createRadialGradient(x - R * 0.3, y - R * 0.35, R * 0.05, x, y, R);
      g.addColorStop(0, 'rgba(46,50,58,' + f3(0.95 * a) + ')');
      g.addColorStop(0.55, 'rgba(14,15,18,' + f3(a) + ')');
      g.addColorStop(1, 'rgba(6,6,8,' + f3(a) + ')');
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, R, 0, TAU); fctx.fill();
      g = fctx.createRadialGradient(x, y, R * 0.95, x, y, R * 1.45);
      g.addColorStop(0, 'rgba(190,204,224,' + f3(0.14 * a) + ')');
      g.addColorStop(1, 'rgba(190,204,224,0)');
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, R * 1.45, 0, TAU); fctx.fill();
      fctx.lineWidth = Math.max(1, R * 0.012);
      fctx.strokeStyle = 'rgba(214,224,238,' + f3(0.35 * a) + ')';
      fctx.beginPath(); fctx.arc(x, y, R, 0, TAU); fctx.stroke();
      g = fctx.createRadialGradient(x - R * 0.42, y - R * 0.48, 0, x - R * 0.42, y - R * 0.48, R * 0.2);
      g.addColorStop(0, 'rgba(255,255,255,' + f3(0.7 * a) + ')');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x - R * 0.42, y - R * 0.48, R * 0.2, 0, TAU); fctx.fill();
      fctx.lineWidth = Math.max(1, R * 0.02);
      fctx.strokeStyle = 'rgba(200,212,230,' + f3(0.12 * a) + ')';
      fctx.beginPath(); fctx.arc(x, y, R * 0.9, Math.PI * 0.2, Math.PI * 0.8); fctx.stroke();
    }
    let fxDirty = true;
    function drawFx() {
      const bt = T - bootT0;
      const busy = body.a > 0.01 || net.a > 0.01 || (bootOn && bt < 7);
      if (!busy && !fxDirty) return;
      fctx.setTransform(1, 0, 0, 1, 0, 0);
      fctx.clearRect(0, 0, fxEl.width, fxEl.height);
      fxDirty = busy;
      if (!busy) return;
      fctx.setTransform(rs, 0, 0, rs, 0, 0);
      fctx.globalCompositeOperation = 'source-over';
      if (body.a > 0.01) drawBody();
      fctx.globalCompositeOperation = 'lighter';
      if (net.a > 0.01) {
        fctx.lineWidth = Math.max(0.5, 0.6 * U);
        for (let i = 0; i < pairs.length; i++) {
          const a = pairs[i][0], b = pairs[i][1];
          if (a.role !== 'orb' || b.role !== 'orb') continue;
          const al = net.a * Math.min(a.a, b.a) * 0.3;
          if (al < 0.01) continue;
          fctx.strokeStyle = 'rgba(206,218,238,' + f3(al) + ')';
          fctx.beginPath(); fctx.moveTo(a.x, a.y); fctx.lineTo(b.x, b.y); fctx.stroke();
        }
      }
      if (bootOn) {
        const S = bootS;
        if (bt >= 0 && bt < 1.6) {
          const k = Math.min(1, bt / 0.95), grow = k * k * k;
          let I = bt < 0.95 ? 0.3 + 0.7 * grow : Math.max(0, 1 - (bt - 0.95) / 0.6);
          I *= 0.92 + 0.08 * Math.sin(T * 47);
          const len = bt < 0.95 ? grow : 1;
          glow(S.x, S.y, U * (8 + 90 * len), 0.95 * I);
          arm(S.x - W * 0.5 * len, S.y, S.x + W * 0.5 * len, S.y, I, U * 1.6);
          arm(S.x, S.y - H * 0.34 * len, S.x, S.y + H * 0.34 * len, I * 0.8, U * 1.2);
        }
        if (bt > 0.85 && bt < 2.4) {
          const peak = calm ? 0.15 : 0.6;
          const a = bt < 1.0 ? (bt - 0.85) / 0.15 * peak : peak * Math.exp(-(bt - 1.0) * 4.2);
          if (a > 0.004) {
            fctx.globalCompositeOperation = 'source-over';
            const g = fctx.createRadialGradient(S.x, S.y, 0, S.x, S.y, Math.max(W, H) * 0.9);
            g.addColorStop(0, 'rgba(244,247,252,' + f3(a) + ')');
            g.addColorStop(0.35, 'rgba(214,222,236,' + f3(a * 0.75) + ')');
            g.addColorStop(1, 'rgba(160,172,192,' + f3(a * 0.4) + ')');
            fctx.fillStyle = g; fctx.fillRect(0, 0, W, H);
            fctx.globalCompositeOperation = 'lighter';
          }
        }
        for (let i = 0; i < glints.length; i++) {
          const gl = glints[i];
          let k = (bt - gl.t) / 0.42;
          if (stillGlint && stillGlint.i === i) k = stillGlint.k;
          if (k <= 0 || k >= 1) continue;
          const I = Math.sin(Math.PI * k);
          const cx = gl.x0 - gl.len * 0.5 + k * (gl.x1 - gl.x0 + gl.len);
          arm(cx - gl.len * 0.5, gl.y, cx + gl.len * 0.5, gl.y, 0.85 * I, U * 1.1);
          const near = Math.max(0, 1 - Math.abs(cx - gl.xi) / (U * 50));
          if (near > 0) glow(gl.xi, gl.y, U * 26, 0.8 * near * I);
        }
      }
      fctx.globalCompositeOperation = 'source-over';
    }
    function render() {
      if (!u32 || !alive) return;   // destroyed: never drawn again, not even the frame it was destroyed in
      u32.fill(0xff000000);
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        if (p.role === 'gone' || p.a < 0.004) continue;
        splat(p.x * rs, p.y * rs, p.s * rs, p.r, p.g, p.b, p.a > 1 ? 1 : p.a);
      }
      // Static below the scan while the picture is still forming, like a diffusion preview.
      const lv = noiseLevel();
      if (lv > 0.002 && noise) {
        const front = noiseFront();
        const n = Math.round(3000 * lv * rs * rs * (H - front) / H);
        for (let j = 0; j < n; j++) splat(rnd() * W * rs, (front + rnd() * (H - front)) * rs, 1.3 * rs, C.dust[0], C.dust[1], C.dust[2], 0.16);
      }
      ctx.putImageData(img, 0, 0);
      // The bloom is blurred here, at a quarter of the size, and scaled up by the page: a CSS
      // blur over the whole screen costs a weak screen half its frames.
      if (bctx) { bctx.filter = 'blur(2px)'; bctx.clearRect(0, 0, bloomEl.width, bloomEl.height); bctx.drawImage(canvas, 0, 0, bloomEl.width, bloomEl.height); }
      if (fctx) { try { drawFx(); } catch (e) { fxDirty = true; } }
    }

    // ---- the loop: paused off screen and when hidden, cheaper when shown small ----------
    let raf = 0, last = 0, alive = true, visible = true, frameN = 0, frozen = false, dirty = true, lowFps = false;
    function checkScale() {
      let shown = 1;
      try { shown = host.getBoundingClientRect().width / W; } catch (e) { shown = 1; }
      const eff = shown * ((typeof window !== 'undefined' && window.devicePixelRatio) || 1);
      const cap = o.maxScale || 1;
      const want = Math.min(cap, eff > 1.3 ? 2 : eff > 0.62 ? 1 : 0.5);
      lowFps = eff < 0.3;
      if (want !== rs) { sizeCanvas(want); dirty = true; fxDirty = true; }
    }
    function frame(ts) {
      if (!alive) return;
      raf = requestAnimationFrame(frame);
      if (!visible || (typeof document !== 'undefined' && document.hidden)) { last = 0; return; }
      frameN++;
      if (frameN % 40 === 1) checkScale();
      if (lowFps && (frameN & 1)) return;
      const dtReal = last ? Math.min(0.066, (ts - last) / 1000) : 0.016;
      last = ts;
      if (!frozen) { update(dtReal * speed); dirty = true; }
      if (dirty) { render(); dirty = false; }
      if (o.onTick && frameN % 6 === 0) o.onTick();
    }
    let io = null;
    try {
      io = new IntersectionObserver((es) => { for (let i = 0; i < es.length; i++) visible = es[i].isIntersecting; }, { threshold: 0 });
      io.observe(host);
    } catch (e) { io = null; }
    sizeCanvas(1);
    raf = requestAnimationFrame(frame);

    // ---- choreography -------------------------------------------------------------------
    function at(t, fn) { cbs.push({ t, fn }); cbs.sort((a, b) => a.t - b.t); }
    function fit(tg, M) {
      if (tg.length <= M) return tg;
      return tg.map((t) => ({ t, k: t.a + rnd() * 0.6 })).sort((a, b) => b.k - a.k).slice(0, M).map((x) => x.t);
    }
    function moversList() {
      return P.filter((p) => !(p.home === 'orb' && p.keep) && !(p.home === 'dust' && p.i % 3 !== 0));
    }
    function take(n) {
      const out = [];
      for (let j = 0; j < RES.length && out.length < n; j++) {
        const p = RES[(resCur + j) % RES.length];
        if (p.role === 'gone' && !p.q.length) out.push(p);
      }
      resCur = (resCur + out.length) % Math.max(1, RES.length);
      return out;
    }
    // Re-form a set of resting dots into new targets, left to right, arcing over.
    function morph(cur, pool, tg, opts) {
      const T0 = T + (opts.delay || 0);
      tg = tg.slice().sort((a, b) => a.x - b.x || a.y - b.y);
      cur = cur.slice().sort((a, b) => a.tx - b.tx || a.ty - b.ty);
      const minX = tg.length ? tg[0].x : 0;
      const span = Math.max(1, (tg.length ? tg[tg.length - 1].x : 1) - minX);
      const next = [];
      for (let i = 0; i < tg.length; i++) {
        const t = tg[i];
        const spawn = i >= cur.length;
        const p = spawn ? pool.pop() : cur[i];
        if (!p) break;
        const xk = (t.x - minX) / span;
        const sg = {
          t0: calm ? T : T0 + xk * (opts.sweep || 0.5) + rnd() * 0.15,
          d: calm ? 0.02 : (opts.d || 0.75) + rnd() * 0.3, ease: 'inout',
          bx: t.x, by: t.y, tx: t.x, ty: t.y, kx: (rnd() - 0.5) * 40, ky: -(30 + rnd() * 80),
          r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest', shim: calm ? 0 : (opts.shim || 0), dr: !!opts.dr,
        };
        if (spawn) {
          sg.from = opts.spawn ? opts.spawn(t) : [t.x + (rnd() - 0.5) * 160, t.y - 60 - rnd() * 120];
          sg.fromA = 0;
        }
        p.q = [sg]; p.fade = null;
        next.push(p);
      }
      for (let i = tg.length; i < cur.length; i++) {
        const p = cur[i];
        p.q = [{ t0: calm ? T : T0 + rnd() * 0.3, d: calm ? 0.02 : 0.6, ease: 'out', tx: p.x + (rnd() - 0.5) * 80, ty: p.y - 50 - rnd() * 70, r1: p.r, g1: p.g, b1: p.b, a1: 0, s1: p.s, then: 'gone' }];
      }
      return next;
    }
    function clockTo(tg, opts) {
      opts = opts || {};
      if (!CLOCK_N) return;
      const inCur = new Set(clockLive);
      const pool = P.filter((p) => p.home === 'clock' && !inCur.has(p) && p.role === 'gone' && !p.q.length);
      let spawn = null;
      if (opts.intro) spawn = () => [rnd() * W, rnd() * H];
      else if (opts.fromOrb) spawn = () => [orb.tcx + (rnd() - 0.5) * orb.tR, orb.tcy + (rnd() - 0.5) * orb.tR];
      clockLive = morph(clockLive, pool, tg, { delay: opts.delay || 0, sweep: opts.intro ? 0.9 : 0.5, d: opts.intro ? 1.3 : 0.75, shim: 1, dr: true, spawn });
    }
    function reset() {
      cbs.length = 0;
      stillGlint = null; noise = null;
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        p.q = []; p.seg = null; p.fade = null; p.shim = 0; p.dr = false; p.uiT = null;
        if (p.home === 'dust') p.role = 'dust';
        else { p.role = 'gone'; p.a = 0; }
      }
      uiSet = []; clockLive = []; nameLive = [];
    }
    function idleIntro(ck) {
      orb.e = 0; orb.te = 1; orb.idle = 1; orb.tidle = 1;
      dustLevel = 0; dustTarget = calm ? 0.18 : 0.34;
      clockTo(ck, { intro: true, delay: 0.3 });
    }
    // Straight to idle with no journey: after the page is resized.
    function idleNow(ck) {
      reset();
      orb.cx = orb.tcx = L.orb.cx; orb.cy = orb.tcy = L.orb.cy; orb.R = orb.tR = L.orb.R;
      orb.e = orb.te = 1; orb.idle = orb.tidle = 1; orb.tint = orb.ttint = 0;
      body.a = body.ta = 0; net.a = net.ta = 0;
      dustLevel = dustTarget = calm ? 0.18 : 0.34;
      for (let i = 0; i < ORBS.length; i++) ORBS[i].role = 'orb';
      for (let i = 0; i < RINGS.length; i++) RINGS[i].role = 'ring';
      const pool = P.filter((p) => p.home === 'clock');
      for (let i = 0; i < ck.length && i < pool.length; i++) {
        const p = pool[i], t = ck[i];
        p.role = 'rest'; p.tx = t.x; p.ty = t.y; p.ta = t.a; p.ts = t.s; p.r = t.r; p.g = t.g; p.b = t.b; p.shim = calm ? 0 : 1; p.dr = true;
        clockLive.push(p);
      }
    }
    function plan(p, t, T0) {
      const yk = t.y / H, cell = L.cell || 24;
      const cx = Math.floor(t.x / cell) * cell + cell / 2 + (rnd() - 0.5) * cell * 0.4;
      const cy = Math.floor(t.y / cell) * cell + cell / 2 + (rnd() - 0.5) * cell * 0.4;
      const segs = [];
      const hidden = p.role === 'gone';
      let sx = p.x, sy = p.y;
      if (p.home === 'orb' || p.home === 'res') {
        const ang = rnd() * TAU, rad = L.orb.R * (1.2 + rnd() * 2.2);
        const bx = L.orb.cx + Math.cos(ang) * rad, by = L.orb.cy + Math.sin(ang) * rad * 0.82;
        const sg = { t0: T0 + 0.3 + rnd() * 0.1, d: 0.55 + rnd() * 0.3, ease: 'out', tx: bx, ty: by, kx: -Math.sin(ang) * rad * 0.4, ky: Math.cos(ang) * rad * 0.4, r1: C.spark[0], g1: C.spark[1], b1: C.spark[2], a1: 0.5, s1: 1.5, then: 'rest' };
        if (hidden) {
          const a2 = rnd() * TAU, r2 = rnd() * L.orb.R * 0.7;
          sg.from = [L.orb.cx + Math.cos(a2) * r2, L.orb.cy + Math.sin(a2) * r2];
          sg.fromA = 0;
        }
        segs.push(sg);
        sx = bx; sy = by;
      }
      const sgn = p.ph > 0.5 ? 1 : -1;
      segs.push({ t0: T0 + 0.8 + yk * 0.7 + rnd() * 0.25, d: 0.85 + rnd() * 0.35, ease: 'inout', tx: cx, ty: cy, kx: sgn * (cy - sy) * 0.3, ky: -sgn * (cx - sx) * 0.3, r1: t.r, g1: t.g, b1: t.b, a1: 0.3, s1: cell * 0.15, then: 'rest' });
      segs.push({ t0: T0 + 2.0 + yk * 0.9 + rnd() * 0.1, d: 0.5, ease: 'back', tx: t.x, ty: t.y, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest' });
      p.q = segs; p.fade = null;
    }
    function planExtra(p, T0) {
      if (p.home === 'clock' || p.home === 'dust') {
        if (p.role === 'gone') { p.q = []; return; }
        p.q = [{ t0: T0 + 0.5 + rnd() * 0.6, d: 1.2, ease: 'out', tx: p.x + (rnd() - 0.5) * 300, ty: p.y + (rnd() - 0.5) * 300, r1: p.r, g1: p.g, b1: p.b, a1: 0, s1: p.s, then: 'gone' }];
        return;
      }
      if (p.role === 'gone') { p.q = []; return; }
      const ang = rnd() * TAU, rad = L.orb.R * (1.4 + rnd() * 3.2);
      const bx = L.orb.cx + Math.cos(ang) * rad, by = L.orb.cy + Math.sin(ang) * rad * 0.82;
      p.q = [
        { t0: T0 + 0.3 + rnd() * 0.1, d: 0.6 + rnd() * 0.3, ease: 'out', tx: bx, ty: by, kx: -Math.sin(ang) * rad * 0.4, ky: Math.cos(ang) * rad * 0.4, r1: C.spark[0], g1: C.spark[1], b1: C.spark[2], a1: 0.45, s1: 1.4, then: 'rest' },
        { t0: T0 + 1.0 + rnd() * 1.2, d: 1.4, ease: 'out', tx: bx + (rnd() - 0.5) * 400, ty: by + (rnd() - 0.5) * 300, r1: C.fading[0], g1: C.fading[1], b1: C.fading[2], a1: 0, s1: 1.2, then: 'gone' },
      ];
    }
    // Something is put on the screen: the orb breathes in and bursts, and its dots travel to
    // where the page's letters and panels are, coarse blocks first, then each row sharpens.
    function push(tg) {
      const T0 = T;
      orb.tR = L.orb.R * 0.82; orb.tidle = 0; orb.te = 1; orb.ttint = 0;
      at(T0 + 0.32, () => { orb.tcx = L.mini.cx; orb.tcy = L.mini.cy; orb.tR = L.mini.R; });
      dustTarget = 0.1;
      const movers = moversList();
      const M = movers.length;
      const tgt = fit(tg, M);
      for (let i = 0; i < M; i++) { const p = movers[i]; p._k = (p.role === 'gone' ? L.orb.cy : p.y) + (rnd() - 0.5) * H * 0.5; }
      movers.sort((a, b) => a._k - b._k);
      const order = tgt.map((t) => ({ t, k: t.y + (rnd() - 0.5) * H * 0.3 })).sort((a, b) => a.k - b.k);
      const nT = order.length;
      const chosen = new Set();
      uiSet = [];
      for (let j = 0; j < nT; j++) {
        const p = movers[Math.min(M - 1, Math.floor(j * M / nT))];
        chosen.add(p);
        p.uiT = order[j].t;
        uiSet.push(p);
        plan(p, order[j].t, T0);
      }
      for (let j = 0; j < M; j++) {
        const p = movers[j];
        if (!chosen.has(p)) { p.uiT = null; planExtra(p, T0); }
      }
      clockLive = []; nameLive = [];
      noise = calm ? null : { t0: T0 + 0.6, tf: T0 + 2.0, fd: 0.9, t1: T0 + 4.4 };
    }
    // The dots under the revealed page fade out in step with the reveal's sweep.
    function sweepOut(tRev, dur) {
      for (let i = 0; i < uiSet.length; i++) {
        const p = uiSet[i];
        const y = p.uiT ? p.uiT.y : p.y;
        p.fade = { t0: tRev + dur * (0.2 + 0.56 * y / H), d: 0.32, then: rnd() < 0.04 ? 'dust' : 'gone' };
      }
      noise = null;
    }
    // Something already up, without the journey (after a resize, or opening onto it).
    function place(tg) {
      reset();
      orb.cx = orb.tcx = L.mini.cx; orb.cy = orb.tcy = L.mini.cy; orb.R = orb.tR = L.mini.R;
      orb.e = orb.te = 1; orb.idle = orb.tidle = 0; orb.tint = orb.ttint = 0;
      body.a = body.ta = 0; net.a = net.ta = 0;
      dustLevel = dustTarget = 0.1;
      for (let i = 0; i < ORBS.length; i++) if (ORBS[i].keep) ORBS[i].role = 'orb';
      const movers = moversList();
      const M = movers.length, tgt = fit(tg, M), n = tgt.length;
      for (let j = 0; j < n; j++) {
        const p = movers[Math.floor(j * M / n)];
        p.uiT = tgt[j];
        uiSet.push(p);
      }
    }
    // What a page drew is let go of, now (round 11: NEW-B-LOCAL-SLIP and B2-04). Every dot that
    // holds a place sampled from a page — which, on a screen, can be a customer's name, address or
    // note, as the shape of its letters — is taken out of it where it is: gone at once, with no
    // place, no flight queued back to it and none of its colour. The canvas is drawn again at
    // once without them, not at the next frame. Nothing sampled from that page is drawn again.
    // Round 12: not even where it was. Each forgotten dot is put back in the orb, so a flight
    // that later starts from where a dot happens to be (the clock's, a push's) never starts from
    // the shape of the page it drew.
    function forgetPage() {
      const inUi = new Set(uiSet);
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        if (!p.uiT && !inUi.has(p)) continue;
        p.uiT = null; p.q = []; p.seg = null; p.fade = null; p.shim = 0; p.dr = false;
        p.role = 'gone'; p.a = 0; p.r = C.seed[0]; p.g = C.seed[1]; p.b = C.seed[2];
        p.x = orb.cx; p.y = orb.cy;
      }
      uiSet = []; noise = null;
    }
    function forget() {
      forgetPage();
      if (alive && u32) render();
    }
    // The canvases emptied now: what they last showed is not left on them (destroy).
    function blank() {
      try {
        if (u32) { u32.fill(0xff000000); ctx.putImageData(img, 0, 0); }
        if (bctx) bctx.clearRect(0, 0, bloomEl.width, bloomEl.height);
        if (fctx) { fctx.setTransform(1, 0, 0, 1, 0, 0); fctx.clearRect(0, 0, fxEl.width, fxEl.height); }
      } catch (e) { /* a canvas already gone holds nothing */ }
    }
    // Marked done: the check. The dots that drew the page let go of it first, at once (forget),
    // so they never form it again on their way — what it showed of a customer is not drawn a
    // moment longer (round 11, B2-04) — and the check swirls out of the orb instead, in a sweep
    // around its centre. packIn then takes these dots from the check into the page's done state.
    function packOut(ck) {
      forget();
      const T0 = T, cx = L.check.cx, cy = L.check.cy;
      shimC = { x: cx, y: cy, t0: T0 + 1.3 };
      const pool = moversList().filter((p) => p.role === 'gone' && !p.q.length);
      const pts = fit(ck, pool.length).map((t) => ({ t, k: Math.atan2(t.y - cy, t.x - cx) + rnd() * 0.3 })).sort((a, b) => a.k - b.k).map((x) => x.t);
      const n = pts.length, set = [];
      for (let i = 0; i < n; i++) {
        const p = pool[i], t = pts[i];
        const a = rnd() * TAU, r = rnd() * Math.max(4, orb.R);
        p.q = [{ t0: T0 + 0.2 + (i / Math.max(1, n)) * 0.45 + rnd() * 0.1, d: 0.85 + rnd() * 0.25, ease: 'inout',
          from: [orb.cx + Math.cos(a) * r, orb.cy + Math.sin(a) * r], fromA: 0, tx: t.x, ty: t.y,
          kx: (rnd() - 0.5) * 200, ky: (rnd() - 0.5) * 200, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest', shim: 2 }];
        p.fade = null;
        set.push(p);
      }
      uiSet = set;
    }
    // Something new in place of what is up (round 12). The owner asked for one thing and then
    // another: the screen goes straight from the one to the other — no journey home to the clock,
    // and no burst. The orb, small in its corner while something is shown, swells a moment and
    // the new page's dots stream out of it to where its letters and panels are, landing as
    // coarse blocks top first and then sharp, while the page above dissolves what was there.
    // `rev` says when the page starts to resolve under them and for how long (seconds from now);
    // each dot fades as that sweep passes its row, once it has landed (a fade set before a dot's
    // last leg began would be dropped when the leg starts, so it is part of the flight).
    // Never a dot of what was there: the page has the engine forget it first (forget), and
    // every dot here starts in the orb, none from where it last was. Returns how long, from now,
    // until the last dot has landed.
    function swap(tg, rev) {
      const T0 = T, mini = L.mini || orbHome, cell = L.cell || 24;
      const revAt = rev && rev.at > 0 ? rev.at : 0.45, revD = rev && rev.d > 0 ? rev.d : 0.9;
      noise = null;
      orb.tcx = mini.cx; orb.tcy = mini.cy; orb.tR = mini.R * 1.6; orb.te = 1; orb.tidle = 0; orb.ttint = 0;
      at(T0 + 0.4, () => { orb.tR = mini.R; });
      const pool = moversList().filter((p) => p.role === 'gone' && !p.q.length);
      const M = pool.length, tgt = fit(tg, M), n = tgt.length;
      const order = tgt.map((t) => ({ t, k: t.y + (rnd() - 0.5) * H * 0.15 })).sort((a, b) => a.k - b.k);
      uiSet = [];
      let last = 0;
      for (let j = 0; j < n; j++) {
        const p = pool[Math.min(M - 1, Math.floor(j * M / n))], t = order[j].t;
        const yk = Math.max(0, Math.min(1, t.y / H));
        const a = rnd() * TAU, r = rnd() * mini.R;
        const cx = Math.floor(t.x / cell) * cell + cell / 2 + (rnd() - 0.5) * cell * 0.4;
        const cy = Math.floor(t.y / cell) * cell + cell / 2 + (rnd() - 0.5) * cell * 0.4;
        const t1 = T0 + 0.05 + yk * 0.3 + rnd() * 0.12, d1 = 0.45 + rnd() * 0.2;
        const t2 = Math.max(T0 + 0.72 + yk * 0.3 + rnd() * 0.08, t1 + d1);
        const t3 = Math.max(T0 + revAt + revD * (0.2 + 0.56 * yk), t2 + 0.32);
        p.q = [
          { t0: t1, d: d1, ease: 'out', from: [mini.cx + Math.cos(a) * r, mini.cy + Math.sin(a) * r], fromA: 0,
            tx: cx, ty: cy, kx: (rnd() - 0.5) * 60, ky: (rnd() - 0.5) * 60, r1: t.r, g1: t.g, b1: t.b, a1: 0.32, s1: cell * 0.15, then: 'rest' },
          { t0: t2, d: 0.32, ease: 'back', tx: t.x, ty: t.y, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest' },
          { t0: t3, d: 0.32, ease: 'out', tx: t.x, ty: t.y, r1: t.r, g1: t.g, b1: t.b, a1: 0, s1: t.s, then: rnd() < 0.04 ? 'dust' : 'gone' },
        ];
        p.fade = null;
        p.uiT = t;
        uiSet.push(p);
        last = Math.max(last, t2 + 0.32 - T0);
      }
      return last;
    }
    // ...and back out of the check into the page, now in its done state.
    function packIn(tg, t0) {
      const cx = L.check.cx, cy = L.check.cy;
      const angOf = (x, y) => Math.atan2(y - cy, x - cx);
      const set = uiSet.slice();
      for (let i = 0; i < set.length; i++) set[i]._k = angOf(set[i].x, set[i].y);
      set.sort((a, b) => a._k - b._k);
      const pts = fit(tg, set.length).map((t) => ({ t, k: angOf(t.x, t.y) })).sort((a, b) => a.k - b.k).map((x) => x.t);
      const n = set.length, m = pts.length;
      const next = [];
      for (let i = 0; i < n; i++) {
        const p = set[i];
        let t = null;
        if (m >= n) t = pts[Math.floor(i * m / n)];
        else if (m > 0 && (i === 0 || Math.floor(i * m / n) !== Math.floor((i - 1) * m / n))) t = pts[Math.floor(i * m / n)];
        if (t) {
          p.uiT = t;
          next.push(p);
          p.q = [{ t0: t0 + (t.y / H) * 0.5 + rnd() * 0.15, d: 0.8 + rnd() * 0.2, ease: 'inout', tx: t.x, ty: t.y, kx: (rnd() - 0.5) * 160, ky: (rnd() - 0.5) * 160, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest' }];
        } else {
          p.uiT = null;
          p.q = [{ t0: t0 + rnd() * 0.4, d: 0.9, ease: 'out', tx: p.x + (rnd() - 0.5) * 240, ty: p.y + (rnd() - 0.5) * 240, r1: p.r, g1: p.g, b1: p.b, a1: 0, s1: p.s, then: 'gone' }];
        }
      }
      uiSet = next;
    }
    // Cleared: everything goes home, the bottom of the screen first: orb dots to their place on
    // the sphere, ring dots to the ring, clock dots to the time.
    function clear(ck) {
      const T0 = T;
      orb.tcx = L.orb.cx; orb.tcy = L.orb.cy; orb.tR = L.orb.R; orb.te = 1; orb.tidle = 1; orb.ttint = 0;
      dustTarget = calm ? 0.18 : 0.34; noise = null;
      const inUi = new Set(uiSet);
      const ct = ck.slice().sort((a, b) => a.x - b.x || a.y - b.y);
      const clocks = P.filter((p) => p.home === 'clock');
      for (let i = 0; i < clocks.length; i++) { const p = clocks[i]; p._k = inUi.has(p) && p.uiT ? p.uiT.x : 1e6 + rnd(); }
      clocks.sort((a, b) => a._k - b._k);
      const ctOf = new Map();
      for (let i = 0; i < clocks.length && i < ct.length; i++) ctOf.set(clocks[i], ct[i]);
      const cminX = ct.length ? ct[0].x : 0, cspan = Math.max(1, (ct.length ? ct[ct.length - 1].x : 1) - cminX);
      const newClock = [];
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        if (p.home === 'orb' && p.keep) continue;
        if (p.home === 'dust' && p.i % 3 !== 0) continue;
        const u = inUi.has(p) ? p.uiT : null;
        const segs = [];
        if (u) segs.push({ t0: T0, d: 0.28 + rnd() * 0.12, ease: 'out', from: [u.x, u.y], fromA: 0, tx: u.x, ty: u.y, r1: u.r, g1: u.g, b1: u.b, a1: u.a, s1: u.s, then: 'rest' });
        const y0 = u ? u.y : p.y;
        const t1 = T0 + 0.4 + (1 - Math.max(0, Math.min(H, y0)) / H) * 0.7 + rnd() * 0.15;
        const visible = !!u || p.role !== 'gone';
        let sg = null;
        if (p.home === 'orb') {
          sg = { t0: t1, d: 0.95 + rnd() * 0.35, ease: 'inout', kx: (rnd() - 0.5) * 300, ky: (rnd() - 0.5) * 300, then: 'orb', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 };
          if (!visible) { sg.from = [L.orb.cx + (rnd() - 0.5) * L.orb.R, L.orb.cy + (rnd() - 0.5) * L.orb.R]; sg.fromA = 0; }
        } else if (p.ring) {
          sg = { t0: t1 + 0.2, d: 1.1 + rnd() * 0.3, ease: 'inout', kx: (rnd() - 0.5) * 300, ky: (rnd() - 0.5) * 200, then: 'ring', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 };
          if (!visible) { sg.from = [L.orb.cx + (rnd() - 0.5) * L.orb.R * 3, L.orb.cy + (rnd() - 0.5) * L.orb.R]; sg.fromA = 0; }
        } else if (p.home === 'clock') {
          const t = ctOf.get(p);
          if (t) {
            const xk = (t.x - cminX) / cspan;
            sg = { t0: t1 + 0.35 + xk * 0.3, d: 0.9 + rnd() * 0.25, ease: 'inout', bx: t.x, by: t.y, tx: t.x, ty: t.y, kx: (rnd() - 0.5) * 120, ky: -(40 + rnd() * 100), r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest', shim: calm ? 0 : 1, dr: true };
            if (!visible) { sg.from = [t.x + (rnd() - 0.5) * 200, t.y + 80 + rnd() * 160]; sg.fromA = 0; }
            newClock.push(p);
          } else if (visible) {
            sg = { t0: t1, d: 0.7, ease: 'out', tx: (u ? u.x : p.x) + (rnd() - 0.5) * 120, ty: (u ? u.y : p.y) - 60 - rnd() * 80, r1: C.fading[0], g1: C.fading[1], b1: C.fading[2], a1: 0, s1: 1.2, then: 'gone' };
          }
        } else if (p.home === 'dust') {
          sg = { t0: t1, d: 1.2, ease: 'out', tx: rnd() * W, ty: rnd() * H, r1: C.dust[0], g1: C.dust[1], b1: C.dust[2], a1: 0.12, s1: 1.3, then: 'dust' };
          if (!visible) { sg.from = [sg.tx, sg.ty]; sg.fromA = 0; }
        } else if (visible) {
          const a = rnd() * TAU, r = rnd() * L.orb.R * 0.5;
          sg = { t0: t1, d: 0.9 + rnd() * 0.3, ease: 'inout', tx: L.orb.cx + Math.cos(a) * r, ty: L.orb.cy + Math.sin(a) * r, kx: (rnd() - 0.5) * 300, ky: (rnd() - 0.5) * 300, r1: C.home[0], g1: C.home[1], b1: C.home[2], a1: 0, s1: 1.2, then: 'gone' };
        }
        if (sg) segs.push(sg);
        p.q = segs; p.fade = null;
      }
      uiSet = []; clockLive = newClock;
    }
    // Naming a screen: the typed name in dots; saving pours it into the orb.
    function nameIntro() {
      reset();
      orb.e = 0; orb.te = 0; orb.tint = orb.ttint = 0; dustLevel = 0; dustTarget = calm ? 0.16 : 0.26;
      for (let i = 0; i < ORBS.length; i++) ORBS[i].role = 'orb';
      for (let i = 0; i < RINGS.length; i++) RINGS[i].role = 'ring';
    }
    function nameTo(tg) {
      const inCur = new Set(nameLive);
      const pool = RES.filter((p) => !inCur.has(p) && p.role === 'gone' && !p.q.length);
      nameLive = morph(nameLive, pool, tg, { sweep: 0.35, d: 0.7, shim: 1, spawn: () => [rnd() * W, rnd() * H * 0.9] });
    }
    function nameToOrb(ck) {
      const T0 = T;
      orb.te = 1; orb.tidle = 1; dustTarget = calm ? 0.18 : 0.34;
      const list = nameLive.slice().sort((a, b) => a.tx - b.tx);
      const n = list.length;
      for (let i = 0; i < n; i++) {
        const p = list[i];
        const a = rnd() * TAU, r = rnd() * L.orb.R * 0.45;
        p.q = [{ t0: calm ? T0 : T0 + (i / Math.max(1, n)) * 0.45 + rnd() * 0.1, d: calm ? 0.02 : 0.9 + rnd() * 0.3, ease: 'inout', tx: L.orb.cx + Math.cos(a) * r, ty: L.orb.cy + Math.sin(a) * r, kx: (rnd() - 0.5) * 260, ky: -(80 + rnd() * 200), r1: C.pour[0], g1: C.pour[1], b1: C.pour[2], a1: 0, s1: 1.2, then: 'gone' }];
      }
      nameLive = [];
      clockTo(ck, { delay: calm ? 0 : 1.1, fromOrb: true });
    }

    // ---- start-up ------------------------------------------------------------------------
    function settleHome(B, T1) {
      orb.tcx = B.home.cx; orb.tcy = B.home.cy; orb.tR = B.home.R; orb.te = 1; orb.tidle = 1; orb.ttint = B.endTint;
      body.ta = B.homeBody; net.ta = 0; dustTarget = calm ? 0.16 : 0.3;
      if (B.clock && B.clock.length) clockTo(B.clock, { delay: calm ? 0 : 0.9, fromOrb: true });
      at(T1 + 1.4, () => { bootOn = false; });
    }
    function nameIntoHome(B, T1) {
      const mk = B.markTargets ? B.markTargets() : [];
      const ps = take(mk.length);
      let minX = 1e9, maxX = -1e9;
      for (let i = 0; i < mk.length; i++) { if (mk[i].x < minX) minX = mk[i].x; if (mk[i].x > maxX) maxX = mk[i].x; }
      const span = Math.max(1, maxX - minX);
      for (let j = 0; j < ps.length; j++) {
        const t = mk[j], p = ps[j];
        const a = rnd() * TAU, rr = rnd() * B.home.R * 0.5;
        p.q = [
          { t0: T1, d: 0.22, ease: 'out', from: [t.x, t.y], fromA: 0, tx: t.x, ty: t.y, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest' },
          { t0: T1 + 0.25 + ((t.x - minX) / span) * 0.3 + rnd() * 0.1, d: calm ? 0.3 : 0.85 + rnd() * 0.25, ease: 'inout', tx: B.home.cx + Math.cos(a) * rr, ty: B.home.cy + Math.sin(a) * rr, kx: (rnd() - 0.5) * 200 * U, ky: -(40 + rnd() * 120) * U, r1: 230, g1: 226, b1: 250, a1: 0, s1: 1, then: 'gone' },
        ];
      }
    }
    // The full start-up: a point of light grows a cross flare and flashes; the flash becomes the
    // orb; C L I V E condense out of it one by one with a glint across each; the letters swing
    // into the name (the page moves them; the dots throw sparks along their path); then the
    // name pours into the orb, which settles at home. `B.handoffAt` (seconds) is when; the page
    // may hold it back (web/startup.js waits for the app to be ready) by calling handoff().
    function boot(B) {
      reset();
      const T0 = T;
      bootT0 = T0; bootOn = true; bootS = B.S; glints = B.glints || [];
      orb.cx = orb.tcx = B.S.x; orb.cy = orb.tcy = B.S.y; orb.R = orb.tR = B.R;
      orb.e = orb.te = 1; orb.idle = orb.tidle = 0; orb.tint = orb.ttint = 1;
      body.a = body.ta = 0; net.a = net.ta = 0;
      dustLevel = 0; dustTarget = calm ? 0.1 : 0.16;
      for (let i = 0; i < ORBS.length; i++) {
        ORBS[i].q = [{ t0: T0 + 1.0 + rnd() * 0.12, d: 0.8 + rnd() * 0.35, ease: 'out', from: [B.S.x + (rnd() - 0.5) * 6, B.S.y + (rnd() - 0.5) * 6], fromA: 0, kx: (rnd() - 0.5) * B.R * 1.2, ky: (rnd() - 0.5) * B.R * 1.2, then: 'orb', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 }];
      }
      for (let i = 0; i < RINGS.length; i++) {
        RINGS[i].q = [{ t0: T0 + 1.25 + rnd() * 0.45, d: 1.1 + rnd() * 0.3, ease: 'out', from: [B.S.x, B.S.y], fromA: 0, kx: (rnd() - 0.5) * B.R * 2, ky: (rnd() - 0.5) * B.R, then: 'ring', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 }];
      }
      at(T0 + 1.05, () => { body.ta = 1; });
      at(T0 + 1.5, () => { net.ta = 1; });
      at(T0 + 2.45, () => { orb.tR = B.R * 0.8; orb.te = 0.4; body.ta = 0.35; net.ta = 0.12; });
      const rows = B.rows || [];
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const ps = take(row.targets.length);
        for (let j = 0; j < ps.length; j++) {
          const t = row.targets[j], p = ps[j];
          const a = rnd() * TAU, rr = B.R * (0.45 + rnd() * 0.35);
          p.r = 235; p.g = 240; p.b = 250; p.s = t.s;
          p.q = [{ t0: T0 + 2.5 + i * 0.13 + rnd() * 0.12, d: 0.5 + rnd() * 0.15, ease: 'inout', from: [B.S.x + Math.cos(a) * rr, B.S.y + Math.sin(a) * rr], fromA: 0, tx: t.x, ty: t.y, kx: (rnd() - 0.5) * 60 * U, ky: (rnd() - 0.5) * 60 * U, r1: t.r, g1: t.g, b1: t.b, a1: t.a, s1: t.s, then: 'rest' }];
        }
        at(T0 + 3.05 + i * 0.13, () => { for (let j = 0; j < ps.length; j++) ps[j].fade = { t0: T, d: 0.35 }; });
      }
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const ps = take(26);
        for (let s = 0; s < ps.length; s++) {
          const kk = s / ps.length, e = EASE.inout(kk);
          const x = row.col.x + (row.mark.x - row.col.x) * e, y = row.col.y + (row.mark.y - row.col.y) * e;
          const p = ps[s];
          p.r = 240; p.g = 244; p.b = 252; p.s = 1.2 * U;
          p.q = [{ t0: T0 + 4.35 + i * 0.05 + kk * 0.75, d: 0.55, ease: 'out', from: [x + (rnd() - 0.5) * 8 * U, y + (rnd() - 0.5) * 8 * U], fromA: 0.8, tx: x + (rnd() - 0.5) * 24 * U, ty: y + (6 + rnd() * 18) * U, r1: 235, g1: 240, b1: 250, a1: 0, s1: 0.8 * U, then: 'gone' }];
        }
      }
      if (B.handoffAt !== null && B.handoffAt !== undefined) at(T0 + B.handoffAt, () => handoff(B));
    }
    function handoff(B) {
      const T1 = T;
      nameIntoHome(B, T1);
      settleHome(B, T1);
    }
    // Every other open: just the name and its line, then into the orb.
    function quick(B) {
      reset();
      const T0 = T;
      bootT0 = T0; bootOn = false; glints = [];
      orb.cx = orb.tcx = B.home.cx; orb.cy = orb.tcy = B.home.cy; orb.R = orb.tR = B.home.R;
      orb.e = 0; orb.te = 0; orb.tint = orb.ttint = B.endTint; orb.idle = orb.tidle = 1;
      body.a = 0; body.ta = 0; net.a = net.ta = 0;
      dustLevel = 0; dustTarget = calm ? 0.16 : 0.3;
      if (B.handoffAt !== null && B.handoffAt !== undefined) at(T0 + B.handoffAt, () => quickHandoff(B));
    }
    function quickHandoff(B) {
      const T1 = T;
      nameIntoHome(B, T1);
      orb.te = 1;
      const bx = B.markBox;
      for (let i = 0; i < ORBS.length; i++) {
        ORBS[i].q = [{ t0: T1 + 0.2 + rnd() * 0.35, d: calm ? 0.3 : 0.8 + rnd() * 0.3, ease: 'inout', from: [bx.x0 + rnd() * (bx.x1 - bx.x0), bx.y0 + rnd() * (bx.y1 - bx.y0)], fromA: 0, kx: (rnd() - 0.5) * 120 * U, ky: -(20 + rnd() * 80) * U, then: 'orb', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 }];
      }
      for (let i = 0; i < RINGS.length; i++) {
        RINGS[i].q = [{ t0: T1 + 0.5 + rnd() * 0.4, d: calm ? 0.3 : 1.0, ease: 'out', from: [B.home.cx, B.home.cy], fromA: 0, then: 'ring', tx: 0, ty: 0, r1: 0, g1: 0, b1: 0, a1: 0, s1: 1 }];
      }
      settleHome(B, T1);
    }
    // Move the orb's home (the app's own orb can move under the start-up while it loads).
    function setHome(h) { orb.tcx = h.cx; orb.tcy = h.cy; orb.tR = h.R; }
    function simulate(toT) {
      let guard = 0;
      while (T < toT && guard < 2000) { update(Math.min(1 / 30, toT - T + 1e-6)); guard++; }
      dirty = true;
    }
    return {
      time: () => T,
      setSpeed: (s) => { speed = Math.max(0.2, Math.min(3, s || 1)); },
      at,
      idleIntro, idleNow, clockTo, push, sweepOut, place, packOut, packIn, clear, forget, swap,
      nameIntro, nameTo, nameToOrb,
      boot, quick, handoff: (B) => (B.quick ? quickHandoff(B) : handoff(B)), setHome,
      simulate,
      stillGlint: (g) => { stillGlint = g; dirty = true; fxDirty = true; },
      freeze: (b) => { frozen = !!b; dirty = true; },
      // Stopped for good (round 11, NEW-B-LOCAL-SLIP): nothing it was asked to do later happens,
      // every dot lets go of whatever it was drawing (reset: no place, no flight, no page), and its
      // canvases are emptied now rather than left showing the last frame.
      destroy: () => { alive = false; cancelAnimationFrame(raf); if (io) io.disconnect(); reset(); blank(); },
    };
  }

  // Text drawn big and sampled on a regular grid: a dot-matrix face (the clock, a typed name).
  function textTargets(text, spec, W, H, colour, alpha, family) {
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const c = cv.getContext('2d', { willReadFrequently: true });
    let size = spec.size;
    c.font = '700 ' + size + 'px ' + family;
    let w = c.measureText(text).width;
    if (spec.max && w > spec.max) {
      size = Math.max(40, Math.floor(size * spec.max / w));
      c.font = '700 ' + size + 'px ' + family;
      w = c.measureText(text).width;
    }
    c.fillStyle = '#ffffff';
    c.textBaseline = 'alphabetic';
    const x0 = spec.align === 'center' ? Math.round(spec.x - w / 2) : Math.round(spec.x);
    c.fillText(text, x0, spec.base);
    const top = Math.max(0, Math.floor(spec.base - size * 1.05));
    const bot = Math.min(H, Math.ceil(spec.base + size * 0.3));
    if (bot <= top) return [];
    const d = c.getImageData(0, top, W, bot - top).data;
    const st = spec.step, out = [];
    const ox = ((x0 % st) + st) % st;
    for (let y = Math.floor(st / 2); y < bot - top; y += st) {
      for (let x = ox; x < W; x += st) {
        if (d[(y * W + x) * 4 + 3] > 100) out.push({ x, y: y + top, r: colour.r, g: colour.g, b: colour.b, a: alpha, s: spec.dot });
      }
    }
    return out;
  }

  const api = { create, textTargets };
  root.CliveDots = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
