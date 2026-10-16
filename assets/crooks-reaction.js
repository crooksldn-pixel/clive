/* ============================================================
   CROOKSLDN — reaction test (snippets/crooks-reaction.liquid)

   The reacted photo comes through wherever the pointer passes, like water or
   heat on the shell. Canvas 2D: a soft brush builds an alpha mask, and the
   reacted photo is drawn through it with 'destination-in'. Revealed areas
   stay until RESET.

   - Pointer Events for mouse, pen and touch. A finger that lands on the
     garment paints in any direction and never moves the page (its touch
     events are cancelled). A finger on the empty ground around it, or on the
     text and buttons, scrolls as usual; there the frame's touch-action: pan-y
     lets a vertical swipe scroll, and only a sideways one paints.
   - Nothing runs at rest. A frame is requested only when there is new paint,
     plus a loop that lives only while a pointer is held down (holding still
     soaks or heats the spot a little more).
   - Canvas resolution is capped at 2x. The mask lives in image space, so a
     resize or rotation keeps every revealed area where it was.
   - The canvas is set up only when the card nears the viewport.
   - Events go to Shopify customer events (Shopify.analytics.publish), to
     window.dataLayer when a tag manager has made one, and out as a DOM event
     'crk:reaction' on the card. Nothing is loaded for this.

   Config travels as data-* attributes — no Liquid inside script tags.
   ============================================================ */
(function () {
  'use strict';

  var DPR_CAP = 2;
  var MASK_LONG = 640;      // mask long side in px; the brush is soft, so this is plenty
  var GRID = 24;            // coverage grid for interaction_engaged
  var ENGAGED_AT = 0.12;    // share of the frame painted by the shopper
  var STEP = 0.2;           // stamp spacing, as a share of the brush radius

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* One soft brush per reaction, drawn once and scaled. Water: a wet core with
     a short feathered edge. Heat: a long, even falloff, the way warmth spreads. */
  function makeBrush(kind) {
    var n = 128;
    var c = document.createElement('canvas');
    c.width = n; c.height = n;
    var g = c.getContext('2d');
    var grad = g.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
    if (kind === 'heat') {
      grad.addColorStop(0, 'rgba(255,255,255,1)');
      grad.addColorStop(0.3, 'rgba(255,255,255,0.8)');
      grad.addColorStop(0.65, 'rgba(255,255,255,0.3)');
      grad.addColorStop(1, 'rgba(255,255,255,0)');
    } else {
      grad.addColorStop(0, 'rgba(255,255,255,1)');
      grad.addColorStop(0.5, 'rgba(255,255,255,0.92)');
      grad.addColorStop(0.8, 'rgba(255,255,255,0.4)');
      grad.addColorStop(1, 'rgba(255,255,255,0)');
    }
    g.fillStyle = grad;
    g.fillRect(0, 0, n, n);
    return c;
  }

  function initReaction(root) {
    var frame = root.querySelector('[data-crk-rx-frame]');
    var canvas = root.querySelector('[data-crk-rx-canvas]');
    var full = root.querySelector('.crk-rx__full');
    var ring = root.querySelector('[data-crk-rx-ring]');
    var status = root.querySelector('[data-crk-rx-status]');
    var word = root.querySelector('[data-crk-rx-word]');
    var btnView = root.querySelector('[data-crk-rx-toggle]');
    var btnReset = root.querySelector('[data-crk-rx-reset]');
    if (!frame || !full || !btnView || !btnReset) return null;

    var kind = root.getAttribute('data-crk-rx-type') === 'heat' ? 'heat' : 'water';
    var ratio = parseFloat(root.getAttribute('data-crk-rx-ratio')) || 1;
    var states = (root.getAttribute('data-crk-rx-states') || '').split('|');
    var labelFull = root.getAttribute('data-crk-rx-label-full') || btnView.textContent;
    var labelOrig = root.getAttribute('data-crk-rx-label-original') || labelFull;
    var brushShare = (parseFloat(root.getAttribute('data-crk-rx-brush')) || 12) / 100;
    var teaserOn = root.getAttribute('data-crk-rx-teaser') === 'true';
    var alphaStroke = kind === 'heat' ? 0.24 : 0.3;

    var ctx = null;
    try { ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null; } catch (x) { ctx = null; }
    var paintable = !!(ctx && window.PointerEvent && window.requestAnimationFrame);
    root.setAttribute('data-crk-rx-mode', paintable ? 'paint' : 'view');

    var analytics = {
      component: 'crooks_reaction',
      reaction: kind,
      test: root.getAttribute('data-crk-rx-test') || '',
      placement: root.getAttribute('data-crk-rx-placement') || '',
      product_id: root.getAttribute('data-crk-rx-product') || '',
      product_handle: root.getAttribute('data-crk-rx-handle') || ''
    };
    function track(name, extra) {
      var data = {}, k;
      for (k in analytics) data[k] = analytics[k];
      if (extra) for (k in extra) data[k] = extra[k];
      try {
        var sa = window.Shopify && window.Shopify.analytics;
        if (sa && typeof sa.publish === 'function') sa.publish(name, data);
      } catch (x) { /* analytics never breaks the page */ }
      try {
        var dl = window.dataLayer;
        if (dl && typeof dl.push === 'function') {
          var ev = { event: name };
          for (k in data) ev[k] = data[k];
          dl.push(ev);
        }
      } catch (x) { /* as above */ }
      try {
        root.dispatchEvent(new CustomEvent('crk:reaction', { bubbles: true, detail: { name: name, data: data } }));
      } catch (x) { /* old browsers: no CustomEvent constructor */ }
    }

    /* ---- state ---- */
    var view = 'paint';
    var painted = false;
    var started = false;
    var engaged = false;
    var touched = false;
    var teaserDone = false;
    var visible = false;
    var imgReady = false;
    var setUp = false;
    var cells = new Uint8Array(GRID * GRID);
    var cellCount = 0;
    var dirty = null;
    var frameReq = 0;
    var holdReq = 0;
    var teaserReq = 0;
    var ptr = null;
    var io = null, ioTeaser = null, ro = null;

    /* ---- views and status ---- */
    function refresh() {
      var state = view === 'full' ? 'full' : (painted ? 'active' : 'idle');
      var w = states[state === 'full' ? 2 : (state === 'active' ? 1 : 0)] || '';
      if (status && status.getAttribute('data-crk-rx-state') !== state) {
        status.setAttribute('data-crk-rx-state', state);
        if (word) word.textContent = w;
      }
      var canReset = painted || view === 'full';
      btnReset.setAttribute('aria-disabled', canReset ? 'false' : 'true');
    }

    function setView(v, fromButton) {
      if (v === view) return;
      view = v;
      root.setAttribute('data-crk-rx-view', v);
      btnView.textContent = v === 'full' ? labelOrig : labelFull;
      if (v === 'full' && full.loading === 'lazy') full.loading = 'eager';
      if (fromButton) track(v === 'full' ? 'view_full_reaction' : 'view_original');
      refresh();
    }

    btnView.addEventListener('click', function () {
      setView(view === 'full' ? 'paint' : 'full', true);
    });
    btnReset.addEventListener('click', function () {
      if (btnReset.getAttribute('aria-disabled') === 'true') return;
      clearPaint();
      setView('paint', false);
      teaserDone = true;
      track('reset');
      refresh();
    });

    refresh();
    if (!paintable) return { destroy: function () {} };

    /* ---- canvas, mask and layout ---- */
    var mask = document.createElement('canvas');
    var mw, mh;
    if (ratio >= 1) { mw = MASK_LONG; mh = Math.max(1, Math.round(MASK_LONG / ratio)); }
    else { mh = MASK_LONG; mw = Math.max(1, Math.round(MASK_LONG * ratio)); }
    mask.width = mw; mask.height = mh;
    var mctx = mask.getContext('2d');
    var brush = makeBrush(kind);

    // Where the photo sits inside the canvas (object-fit: contain), in canvas px.
    var L = { w: 0, h: 0, dpr: 1, dx: 0, dy: 0, dw: 0, dh: 0 };

    function measure() {
      var r = frame.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
      var w = Math.max(1, Math.round(r.width * dpr));
      var h = Math.max(1, Math.round(r.height * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      L.w = w; L.h = h; L.dpr = dpr;
      if (w / h > ratio) { L.dh = h; L.dw = h * ratio; L.dx = (w - L.dw) / 2; L.dy = 0; }
      else { L.dw = w; L.dh = w / ratio; L.dx = 0; L.dy = (h - L.dh) / 2; }
      dirty = { x0: 0, y0: 0, x1: mw, y1: mh };
      draw();
    }

    function schedule() {
      if (!frameReq) frameReq = requestAnimationFrame(draw);
    }

    function draw() {
      frameReq = 0;
      if (!dirty || !L.w) return;
      var d = dirty;
      dirty = null;
      var sx = L.dw / mw, sy = L.dh / mh;
      var x0 = Math.max(0, Math.floor(L.dx + d.x0 * sx) - 2);
      var y0 = Math.max(0, Math.floor(L.dy + d.y0 * sy) - 2);
      var x1 = Math.min(L.w, Math.ceil(L.dx + d.x1 * sx) + 2);
      var y1 = Math.min(L.h, Math.ceil(L.dy + d.y1 * sy) + 2);
      if (x1 <= x0 || y1 <= y0) return;
      ctx.save();
      ctx.beginPath();
      ctx.rect(x0, y0, x1 - x0, y1 - y0);
      ctx.clip();
      ctx.clearRect(x0, y0, x1 - x0, y1 - y0);
      if (imgReady && painted) {
        ctx.globalCompositeOperation = 'source-over';
        ctx.drawImage(full, L.dx, L.dy, L.dw, L.dh);
        ctx.globalCompositeOperation = 'destination-in';
        ctx.drawImage(mask, L.dx, L.dy, L.dw, L.dh);
      }
      ctx.restore();
    }

    function grow(x0, y0, x1, y1) {
      if (!dirty) { dirty = { x0: x0, y0: y0, x1: x1, y1: y1 }; return; }
      if (x0 < dirty.x0) dirty.x0 = x0;
      if (y0 < dirty.y0) dirty.y0 = y0;
      if (x1 > dirty.x1) dirty.x1 = x1;
      if (y1 > dirty.y1) dirty.y1 = y1;
    }

    function mark(x, y, r) {
      var cw = mw / GRID, ch = mh / GRID;
      var i0 = Math.max(0, Math.floor((x - r) / cw)), i1 = Math.min(GRID - 1, Math.floor((x + r) / cw));
      var j0 = Math.max(0, Math.floor((y - r) / ch)), j1 = Math.min(GRID - 1, Math.floor((y + r) / ch));
      for (var j = j0; j <= j1; j++) {
        for (var i = i0; i <= i1; i++) {
          var cx = (i + 0.5) * cw - x, cy = (j + 0.5) * ch - y;
          if (cx * cx + cy * cy <= r * r && !cells[j * GRID + i]) { cells[j * GRID + i] = 1; cellCount++; }
        }
      }
    }

    function stamp(x, y, r, a, byShopper) {
      if (kind === 'water') {
        // A little uneven, like water finding its way into the weave.
        r *= 0.85 + Math.random() * 0.3;
        x += (Math.random() - 0.5) * r * 0.3;
        y += (Math.random() - 0.5) * r * 0.3;
      }
      mctx.globalAlpha = a;
      mctx.drawImage(brush, x - r, y - r, r * 2, r * 2);
      grow(x - r, y - r, x + r, y + r);
      if (byShopper) mark(x, y, r * 0.7);
      painted = true;
    }

    // Lays stamps from a to b at a fixed spacing; returns where the last one landed.
    function segment(a, b, r, alpha, byShopper) {
      var dx = b.x - a.x, dy = b.y - a.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var step = Math.max(0.5, r * STEP);
      if (dist < step) return a;
      var n = Math.floor(dist / step);
      for (var i = 1; i <= n; i++) {
        var t = (i * step) / dist;
        stamp(a.x + dx * t, a.y + dy * t, r, alpha, byShopper);
      }
      var tn = (n * step) / dist;
      return { x: a.x + dx * tn, y: a.y + dy * tn };
    }

    function clearPaint() {
      if (!mctx) return;
      if (teaserReq) { cancelAnimationFrame(teaserReq); teaserReq = 0; }
      mctx.clearRect(0, 0, mw, mh);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      painted = false;
      dirty = null;
    }

    /* ---- brush size: a share of the photo's width, never under a fingertip ---- */
    function radiusCss(type) {
      var cssW = L.dw / L.dpr;
      return Math.max(brushShare * cssW, type === 'touch' ? 44 : 24) / 2;
    }
    function radiusMask(type) {
      var cssW = L.dw / L.dpr;
      return cssW ? (radiusCss(type) / cssW) * mw : 0;
    }

    function toMask(clientX, clientY) {
      var r = frame.getBoundingClientRect();
      var x = (clientX - r.left) * L.dpr, y = (clientY - r.top) * L.dpr;
      return { x: ((x - L.dx) / L.dw) * mw, y: ((y - L.dy) / L.dh) * mh };
    }

    /* ---- where the garment is: a coarse map of the normal photo's alpha ----
       Built once the photo has loaded, grown by one cell so the edge counts.
       Until then, or for a photo with no transparency, or if the image cannot
       be read, the whole photo counts as garment. */
    var base = root.querySelector('.crk-rx__base');
    var hit = null;
    function buildHit() {
      if (!base || !base.naturalWidth) return;
      var gw = 48, gh = Math.max(1, Math.round(48 / ratio));
      try {
        var c = document.createElement('canvas');
        c.width = gw; c.height = gh;
        var g = c.getContext('2d');
        g.drawImage(base, 0, 0, gw, gh);
        var d = g.getImageData(0, 0, gw, gh).data;
        var m = new Uint8Array(gw * gh), x, y, i, j;
        for (i = 0; i < gw * gh; i++) m[i] = d[i * 4 + 3] > 24 ? 1 : 0;
        var grown = new Uint8Array(gw * gh);
        for (y = 0; y < gh; y++) {
          for (x = 0; x < gw; x++) {
            for (j = Math.max(0, y - 1); j <= Math.min(gh - 1, y + 1) && !grown[y * gw + x]; j++) {
              for (i = Math.max(0, x - 1); i <= Math.min(gw - 1, x + 1); i++) {
                if (m[j * gw + i]) { grown[y * gw + x] = 1; break; }
              }
            }
          }
        }
        hit = { w: gw, h: gh, m: grown };
      } catch (x) { hit = null; }
    }
    if (base) {
      base.addEventListener('load', buildHit);
      if (base.complete) buildHit();
    }
    function onGarment(clientX, clientY) {
      if (!L.w) measure();
      if (!L.w) return false;
      var p = toMask(clientX, clientY);
      var nx = p.x / mw, ny = p.y / mh;
      if (nx < 0 || ny < 0 || nx >= 1 || ny >= 1) return false;
      if (!hit) return true;
      return !!hit.m[Math.floor(ny * hit.h) * hit.w + Math.floor(nx * hit.w)];
    }

    /* A finger that lands on the garment owns the gesture: cancelling its
       touch events stops the page scrolling. Pointer events still arrive. */
    var touchLock = false;
    function onTouchStart(e) {
      touchLock = e.touches.length === 1 && onGarment(e.touches[0].clientX, e.touches[0].clientY);
      if (touchLock && e.cancelable) e.preventDefault();
    }
    function onTouchMove(e) {
      if (touchLock && e.cancelable) e.preventDefault();
    }
    function onTouchEnd(e) {
      if (!e.touches || !e.touches.length) touchLock = false;
    }

    /* ---- pointer ---- */
    function now() { return window.performance && performance.now ? performance.now() : Date.now(); }

    function arm() {
      if (!L.w) measure();
      ptr.armed = true;
      ptr.r = radiusMask(ptr.type);
      if (view === 'full') setView('paint', false);
      if (teaserReq) { cancelAnimationFrame(teaserReq); teaserReq = 0; }
      teaserDone = true;
      if (!touched) { touched = true; root.setAttribute('data-crk-rx-touched', 'true'); }
      if (!started) { started = true; track('interaction_start', { input: ptr.type }); }
      try { frame.setPointerCapture(ptr.id); } catch (x) { /* already released */ }
      var p = toMask(ptr.sx, ptr.sy);
      stamp(p.x, p.y, ptr.r, alphaStroke, true);
      ptr.last = p;
      ptr.cur = p;
      ptr.movedAt = now();
      schedule();
      refresh();
      if (!holdReq) holdReq = requestAnimationFrame(hold);
    }

    // Holding still soaks (water) or heats (heat) the spot: it spreads a little.
    function hold(ts) {
      holdReq = 0;
      if (!ptr || !ptr.armed) return;
      var t = now();
      var still = t - ptr.movedAt;
      if (still > 140 && t - ptr.heldAt > 50) {
        var spread = Math.min(1 + (still - 140) / 1600, kind === 'heat' ? 1.5 : 1.35);
        stamp(ptr.cur.x, ptr.cur.y, ptr.r * spread, alphaStroke * 0.45, true);
        ptr.heldAt = t;
        schedule();
        checkEngaged();
      }
      holdReq = requestAnimationFrame(hold);
    }

    function checkEngaged() {
      if (started && !engaged && cellCount >= ENGAGED_AT * GRID * GRID) {
        engaged = true;
        track('interaction_engaged', { coverage: Math.round((cellCount / (GRID * GRID)) * 100) });
      }
    }

    function end() {
      if (ptr) { try { frame.releasePointerCapture(ptr.id); } catch (x) { /* not captured */ } }
      ptr = null;
      if (holdReq) { cancelAnimationFrame(holdReq); holdReq = 0; }
      refresh();
    }

    function onDown(e) {
      if (ptr || e.isPrimary === false) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      ptr = {
        id: e.pointerId,
        type: e.pointerType || 'mouse',
        sx: e.clientX, sy: e.clientY,
        armed: false, last: null, cur: null, r: 0,
        movedAt: now(), heldAt: 0
      };
      // A mouse or pen paints at once, and so does a finger on the garment.
      // A finger on the empty ground waits to see whether it is scrolling the
      // page (vertical) or painting (sideways, or a tap).
      if (ptr.type !== 'touch') { e.preventDefault(); arm(); }
      else if (onGarment(e.clientX, e.clientY)) arm();
    }

    function onMove(e) {
      if (e.pointerType === 'mouse') moveRing(e);
      if (!ptr || e.pointerId !== ptr.id) return;
      if (!ptr.armed) {
        var dx = e.clientX - ptr.sx, dy = e.clientY - ptr.sy;
        if (dx * dx + dy * dy < 64) return;
        if (Math.abs(dy) > Math.abs(dx)) { ptr = null; return; }
        arm();
      }
      var list = typeof e.getCoalescedEvents === 'function' ? e.getCoalescedEvents() : null;
      if (!list || !list.length) list = [e];
      for (var i = 0; i < list.length; i++) {
        var p = toMask(list[i].clientX, list[i].clientY);
        ptr.last = segment(ptr.last, p, ptr.r, alphaStroke, true);
        ptr.cur = p;
      }
      ptr.movedAt = now();
      schedule();
      checkEngaged();
      if (e.cancelable) e.preventDefault();
    }

    function onUp(e) {
      if (!ptr || e.pointerId !== ptr.id) return;
      if (!ptr.armed && ptr.type === 'touch') arm(); // a tap leaves a dab
      end();
    }

    function onCancel(e) {
      if (ptr && e.pointerId === ptr.id) end();
    }

    /* Thin brush outline for a mouse only, so the brush size is legible. */
    var fine = !!(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
    function moveRing(e) {
      if (!ring || !fine || !L.w) return;
      var r = frame.getBoundingClientRect();
      var d = radiusCss('mouse') * 2;
      ring.style.width = d + 'px';
      ring.style.height = d + 'px';
      ring.style.transform = 'translate(' + (e.clientX - r.left - d / 2) + 'px,' + (e.clientY - r.top - d / 2) + 'px)';
      if (ring.hidden) ring.hidden = false;
    }
    function hideRing() { if (ring) ring.hidden = true; }

    /* ---- one sample stroke when the card comes into view ---- */
    function maybeTeaser() {
      if (!teaserOn || teaserDone || touched || !imgReady || !visible || !L.w) return;
      teaserDone = true;
      var n = 24;
      var pts = [];
      for (var i = 0; i <= n; i++) {
        var t = i / n;
        pts.push({ x: (0.3 + 0.4 * t) * mw, y: (0.47 - 0.05 * Math.sin(t * Math.PI)) * mh });
      }
      var r = radiusMask('mouse') * 1.1;
      var alpha = kind === 'heat' ? 0.3 : 0.36;
      var last = pts[0];
      var laid = 0;
      stamp(last.x, last.y, r, alpha, false);
      function upto(k) {
        while (laid < k) { laid++; last = segment(last, pts[laid], r, alpha, false); }
        schedule();
        refresh();
      }
      if (prefersReducedMotion()) { upto(n); return; }
      var t0 = 0;
      function step(ts) {
        teaserReq = 0;
        if (touched) return;
        if (!t0) t0 = ts;
        upto(Math.min(n, Math.floor(((ts - t0) / 900) * n)));
        if (laid < n) teaserReq = requestAnimationFrame(step);
      }
      teaserReq = requestAnimationFrame(step);
    }

    /* ---- the reacted photo: drawn only once decoded ---- */
    function onImg() {
      if (!full.naturalWidth) return;
      var go = function () {
        imgReady = true;
        root.setAttribute('data-crk-rx-ready', 'true');
        dirty = { x0: 0, y0: 0, x1: mw, y1: mh };
        schedule();
        maybeTeaser();
      };
      if (typeof full.decode === 'function') full.decode().then(go, go);
      else go();
    }
    full.addEventListener('load', onImg); // also fires when a larger srcset candidate arrives
    if (full.complete) onImg();

    /* ---- set up near the viewport; listen ---- */
    var onResize = function () { if (setUp) measure(); };
    function setup() {
      if (setUp) return;
      setUp = true;
      measure();
      frame.addEventListener('pointerdown', onDown);
      frame.addEventListener('pointermove', onMove);
      frame.addEventListener('pointerup', onUp);
      frame.addEventListener('pointercancel', onCancel);
      frame.addEventListener('lostpointercapture', onCancel);
      frame.addEventListener('pointerleave', hideRing);
      frame.addEventListener('touchstart', onTouchStart, { passive: false });
      frame.addEventListener('touchmove', onTouchMove, { passive: false });
      frame.addEventListener('touchend', onTouchEnd);
      frame.addEventListener('touchcancel', onTouchEnd);
      if (window.ResizeObserver) {
        var pending = 0;
        ro = new ResizeObserver(function () {
          if (pending) return;
          pending = requestAnimationFrame(function () { pending = 0; measure(); });
        });
        ro.observe(frame);
      } else {
        window.addEventListener('resize', onResize);
      }
      if (window.IntersectionObserver) {
        ioTeaser = new IntersectionObserver(function (en) {
          visible = en[0].isIntersecting;
          if (visible) maybeTeaser();
        }, { threshold: 0.5 });
        ioTeaser.observe(frame);
      } else {
        visible = true;
        maybeTeaser();
      }
    }

    if (window.IntersectionObserver) {
      io = new IntersectionObserver(function (en) {
        if (en[0].isIntersecting) { io.disconnect(); io = null; setup(); }
      }, { rootMargin: '400px 0px' });
      io.observe(frame);
    } else {
      setup();
    }

    return {
      destroy: function () {
        if (io) io.disconnect();
        if (ioTeaser) ioTeaser.disconnect();
        if (ro) ro.disconnect();
        window.removeEventListener('resize', onResize);
        if (frameReq) cancelAnimationFrame(frameReq);
        if (holdReq) cancelAnimationFrame(holdReq);
        if (teaserReq) cancelAnimationFrame(teaserReq);
      }
    };
  }

  function mountAll(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var nodes = root.querySelectorAll('[data-crk-reaction]');
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i]._crkRx) nodes[i]._crkRx = initReaction(nodes[i]) || { destroy: function () {} };
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(document); });
  } else {
    mountAll(document);
  }
  document.addEventListener('shopify:section:load', function (e) { mountAll(e.target); });
  document.addEventListener('shopify:section:unload', function (e) {
    var nodes = e.target && e.target.querySelectorAll ? e.target.querySelectorAll('[data-crk-reaction]') : [];
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i]._crkRx) nodes[i]._crkRx.destroy();
    }
  });
})();
