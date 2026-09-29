/* Cards that form out of CLIVE's dots, and go back into them (round 12).
 *
 * The owner, 29 September: "the dots that currently make up the tv screen in text and animation
 * work well and i want to see that used elsewhere such as on clive as an active animation instead
 * of boxes just appearing." On a screen (web/dots.js) CLIVE's orb breathes out its dots and they
 * fly to where the page's letters and panels are, then hand over to the real page. This is that,
 * for the app's cards, kept small enough for the owner's tablet:
 *
 * - A card put in the deck forms out of the orb. Its outline and its words are sampled once, as
 *   points; dots leave the orb's centre, arc to those points (the top of the card first) and
 *   settle; the real card fades in under them and they fade away. The card itself is shown by the
 *   stylesheet on a fixed clock (web/dots-app.css): hidden for 190ms, fully there by 340ms,
 *   whatever the dots are doing, so reading is never held up by a slow frame.
 * - A card taken out of the deck goes back as dots: its outline and a loose grid of its body, as
 *   a shape with no words in it, drift towards the orb and fade.
 * - A card replaced in place (the same card with new words: a patch, an action's result) is left
 *   alone, as the stylesheet already leaves it (`.card[data-patched]`).
 *
 * One canvas over the page, shown only while there are dots on it and emptied the moment there are
 * none. On the weak path (four cores or fewer, or a device web/app.js marks lite: the Galaxy Tab
 * A) there are at most 700 dots, drawn at no more than the tablet's own pixels, the words are
 * sampled as the lines they sit on rather than letter by letter, and the whole entrance runs on a
 * brisker clock (BRISK); the sampling and every frame's drawing are timed (stats) so a browser
 * check can hold them under 16ms. Under
 * prefers-reduced-motion none of this runs: the cards appear as they always have.
 *
 * Privacy. The deck is the owner's own screen, so a customer's name drawn in dots there is drawn
 * where it is already written. Nothing leaves the canvas: no pixel is read back from it and nothing
 * is sent anywhere. When a card is taken away, every dot that was drawing its words is dropped and
 * the canvas is drawn again at once without them (drop); what goes back to the orb is its outline.
 *
 * How it is hooked in: it watches the deck (#cards) for cards added and removed, so every path
 * that puts a card there (a turn's answer, a patch, Back and Next, a half's own deck) is covered
 * without a call in each of them. web/app.js and web/ui.js are not changed by it.
 */
'use strict';

(function (root) {
  const TAU = Math.PI * 2;
  // The clock, in ms from the first frame that draws a card after it is put in the deck. The
  // stylesheet's clock (dots-app.css, dots-card-in) starts in that same frame (a CSS animation
  // starts when its style is first worked out), so the two stay together however long the page
  // took to lay the card out.
  const T = {
    STAGGER: 45,        // the top of a card leaves first; its bottom this much later
    JITTER: 15,
    FLY_MIN: 130,       // each dot's flight from the orb: every one has landed by 240ms
    FLY_MAX: 180,
    SHOW_FROM: 190,     // the real card starts to show under the dots (css)
    SHOWN_BY: 340,      // and is fully there (css)
    FADE_FROM: 250,     // the dots start to go
    DONE: 430,          // and are gone; the canvas is emptied and hidden
    QUICK_FROM: 200,    // dots standing for a line of words (not its letters) go sooner
    QUICK_DONE: 320,
    GO_MIN: 300,        // a card going back: each dot's drift
    GO_MAX: 420,
  };
  // The weak path runs the same entrance on a brisker clock (0.7 of it: the card fully there 238ms
  // after its first frame, not 340). On the tablet the page's own layout of a new deck can take
  // most of 200ms before that first frame, and the whole must stay close to 400ms from the moment
  // the card is put in. The stylesheet has the same clock for it (`.dots-brisk`).
  const BRISK = 0.7;
  // How many dots one arrival may use at most, all its cards together.
  const BUDGET = { strong: 2200, weak: 700 };
  // Colours: the words are white, the outline and the going shape steel (as the screens have them).
  const INK = { words: [240, 244, 250], shape: [178, 188, 206] };

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  const ease = {
    inout: (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2),
    out: (k) => 1 - Math.pow(1 - k, 3),
    in: (k) => k * k * k,
  };

  // ---- what a card is made of, as points --------------------------------------------------

  // The outline of a rounded rectangle, one point every `step` px, clipped to what is on screen.
  function outline(r, radius, step, view) {
    const out = [];
    const rad = Math.max(0, Math.min(radius, r.w / 2, r.h / 2));
    const add = (x, y) => { if (x >= 0 && y >= 0 && x <= view.w && y <= view.h) out.push({ x, y }); };
    for (let x = r.x + rad; x <= r.x + r.w - rad; x += step) { add(x, r.y); add(x, r.y + r.h); }
    for (let y = r.y + rad; y <= r.y + r.h - rad; y += step) { add(r.x, y); add(r.x + r.w, y); }
    const arc = Math.max(2, Math.round((Math.PI / 2) * rad / step));
    const corners = [[r.x + rad, r.y + rad, Math.PI], [r.x + r.w - rad, r.y + rad, 1.5 * Math.PI], [r.x + r.w - rad, r.y + r.h - rad, 0], [r.x + rad, r.y + r.h - rad, 0.5 * Math.PI]];
    for (const [cx, cy, a0] of corners) {
      for (let i = 1; i < arc; i++) { const a = a0 + (i / arc) * (Math.PI / 2); add(cx + Math.cos(a) * rad, cy + Math.sin(a) * rad); }
    }
    return out;
  }
  // A loose grid over a rectangle's body: a shape, with nothing of what it says.
  function body(r, step, view) {
    const out = [];
    const y0 = Math.max(r.y + step, 0), y1 = Math.min(r.y + r.h - step, view.h);
    const x0 = Math.max(r.x + step, 0), x1 = Math.min(r.x + r.w - step, view.w);
    for (let y = y0; y <= y1; y += step) for (let x = x0; x <= x1; x += step) out.push({ x, y });
    return out;
  }
  // The lines a card's words sit on, as runs of points along each line (what the weak path draws,
  // and what the strong path draws for small type).
  // Rows across where the letters' bodies are (from a little above the middle of the line to its
  // baseline), so a line of dots reads as a line of words and never as a line struck through.
  function lineDots(rect, fontPx, step) {
    const out = [];
    const rows = fontPx >= 17 ? 3 : 2;
    const top = rect.y + rect.h * 0.42, bottom = rect.y + rect.h * 0.72;
    for (let j = 0; j < rows; j++) {
      const y = top + ((bottom - top) * j) / (rows - 1);
      for (let x = rect.x + step / 2; x < rect.x + rect.w; x += step) out.push({ x, y });
    }
    return out;
  }
  // At most `max` of them, spread over the whole set rather than the first `max`.
  function thin(list, max) {
    if (list.length <= max) return list;
    const out = [];
    const k = list.length / max;
    for (let i = 0; i < max; i++) out.push(list[Math.floor(i * k)]);
    return out;
  }

  // ---- the engine --------------------------------------------------------------------------

  function create(env) {
    const win = env.win, doc = env.doc, deck = env.deck;
    const now = env.now || (() => (win.performance && win.performance.now ? win.performance.now() : Date.now()));
    const raf = env.raf || ((fn) => win.requestAnimationFrame(fn));
    const rnd = env.random || Math.random;
    const weak = typeof env.weak === 'boolean' ? env.weak : isWeak(win, doc);
    // This engine's clock: the design's, or the weak path's brisker one.
    const C = {};
    for (const k of Object.keys(T)) C[k] = T[k] * (weak ? BRISK : 1);
    const reducedQuery = safeMatch(win, '(prefers-reduced-motion: reduce)');
    const reduced = () => (typeof env.reduced === 'function' ? env.reduced() : !!(reducedQuery && reducedQuery.matches));

    let canvas = env.canvas || null, ctx = null, dpr = 1, cw = 0, ch = 0;
    let dots = [];                 // { sx, sy, tx, ty, rx, ry, kx, ky, t0, d, a, s, ink, quick, card, going, born }
    let frameAsked = 0, drawing = false;
    const glyph = { el: null, ctx: null, metrics: new Map() };   // the letter-shape canvas, kept
    function makeGlyph() {
      if (glyph.ctx) return;
      glyph.el = doc.createElement('canvas');
      glyph.ctx = glyph.el.getContext('2d', { willReadFrequently: true });
    }
    const pending = [];            // cards waiting for the next frame to be sampled
    const forming = new Map();     // card -> when it was put in, then the first frame that drew it
    const geom = new WeakMap();    // card -> its last measured rectangle, and the deck's scroll then
    let scrollTop = deck ? deck.scrollTop || 0 : 0;
    let measureAsked = false;      // the deck's cards to be measured again at the next frame
    // How long drawing a frame took at most (maxMs), and sampling the cards of one arrival (sampleMs).
    const stats = { frames: 0, maxMs: 0, totalMs: 0, sampleMs: 0, events: 0, lastDots: 0, formed: 0, dissolved: 0 };

    function view() { return { w: win.innerWidth || 0, h: win.innerHeight || 0 }; }
    function ensureCanvas() {
      if (!canvas) {
        canvas = doc.createElement('canvas');
        canvas.className = 'app-dots';
        canvas.setAttribute('aria-hidden', 'true');
        (doc.body || doc.documentElement).appendChild(canvas);
      }
      const v = view();
      // The weak tablet's own ratio (1.33) and no more; elsewhere up to 2, for crisp dots.
      const want = Math.min(weak ? 1.34 : 2, win.devicePixelRatio || 1);
      const w = Math.max(1, Math.round(v.w * want)), h = Math.max(1, Math.round(v.h * want));
      if (!ctx || w !== cw || h !== ch || want !== dpr) {
        dpr = want; cw = w; ch = h;
        canvas.width = w; canvas.height = h;
        ctx = canvas.getContext('2d');
      }
      return ctx;
    }
    function show(on) { if (canvas && canvas.classList) canvas.classList.toggle('is-on', !!on); }
    function blank() {
      if (ctx) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cw, ch); }
    }

    // Where CLIVE is on the glass: the orb, or the ask bar when the orb is not showing.
    function source() {
      const v = view();
      for (const id of ['orb-frame', 'ask-bar']) {
        const node = doc.getElementById(id);
        if (!node || typeof node.getBoundingClientRect !== 'function') continue;
        const r = node.getBoundingClientRect();
        if (r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < v.h) return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: Math.min(r.width, r.height) / 2 };
      }
      return { x: v.w / 2, y: v.h - 40, r: 20 };
    }

    // A card's points: its outline, and its words. On the strong path the words are letter shapes,
    // drawn as the browser drew them and read back as points (a run on one line drawn whole, a run
    // that wraps word by word). On the weak path they are the lines the words sit on: setting up
    // the fonts and reading the pixels back cost the tablet more than a frame (measured at 10 to
    // 24ms with the CPU slowed four times), and lines cost almost nothing. Only what is on screen.
    function sample(card, budget) {
      const v = view();
      const b = card.getBoundingClientRect();
      const r = { x: b.left, y: b.top, w: b.width, h: b.height };
      if (r.w < 8 || r.h < 8 || r.y > v.h || r.y + r.h < 0 || r.x > v.w || r.x + r.w < 0) return { rect: r, points: [] };
      const radius = cornerOf(card);
      const edge = outline(r, radius, weak ? 9 : 6, v).map((p) => Object.assign(p, { a: weak ? 0.5 : 0.42, s: weak ? 1.6 : 1.3, ink: 'shape' }));
      const words = [];
      const glyphs = weak ? null : glyphCanvas(r, v);
      const styles = new Map();
      const styleOf = (node) => {
        const host = node.parentNode;
        if (!styles.has(host)) { let cs = null; try { cs = win.getComputedStyle(host); } catch (e) { cs = null; } styles.set(host, cs); }
        return styles.get(host);
      };
      for (const t of textRuns(card, r, v)) {
        if (glyphs) {
          const cs = styleOf(t.node);
          if (cs && t.rects.length === 1 && glyphs.draw(t.value, t.rects[0], cs)) continue;
          if (cs && glyphs.drawWords(t, cs)) continue;
        }
        for (const q of t.rects) {
          for (const p of lineDots(q, q.h / 1.3, weak ? 5 : 4)) {
            if (p.y >= 0 && p.y <= v.h) words.push({ x: p.x, y: p.y, a: weak ? 0.8 : 0.5, s: weak ? 1.8 : 1.3, ink: 'words', quick: true });
          }
        }
      }
      if (glyphs) for (const p of glyphs.points(2)) words.push(Object.assign(p, { a: 0.9, s: 1.4, ink: 'words' }));
      // The outline is kept whole where it can be; the words take what is left.
      const keepEdge = thin(edge, Math.floor(budget * 0.3));
      return { rect: r, points: keepEdge.concat(thin(words, Math.max(0, budget - keepEdge.length))) };
    }
    function cornerOf(card) {
      try {
        const cs = win.getComputedStyle(card);
        return parseFloat(cs.borderTopLeftRadius) || 20;
      } catch (e) { return 20; }
    }
    // Every run of text in the card that is on screen, and the boxes of its lines.
    function textRuns(card, r, v) {
      const out = [];
      if (typeof doc.createTreeWalker !== 'function' || typeof doc.createRange !== 'function') return out;
      const walker = doc.createTreeWalker(card, 4 /* NodeFilter.SHOW_TEXT */);
      const range = doc.createRange();
      let node = walker.nextNode();
      let guard = 0;
      while (node && guard++ < 400) {
        const value = node.nodeValue || '';
        if (value.trim()) {
          // Its line boxes, from layout alone (a hidden element has none): no style is asked for
          // here, because on the weak tablet asking for every run's style was most of the cost.
          range.selectNodeContents(node);
          const rects = [];
          for (const q of (range.getClientRects ? Array.from(range.getClientRects()) : [])) {
            if (q.width < 2 || q.height < 2) continue;
            if (q.bottom < Math.max(0, r.y) || q.top > Math.min(v.h, r.y + r.h)) continue;
            rects.push({ x: q.left, y: q.top, w: q.width, h: q.height });
          }
          if (rects.length) out.push({ rects, node, value, range });
        }
        node = walker.nextNode();
      }
      return out;
    }
    // The one size letter shapes are drawn at before scaling, and where a font's letters sit in its
    // line at that size (measured once per font, then remembered).
    const REF = 32;
    function refFont(fontStyle, weight, family) { return `${fontStyle || 'normal'} ${weight || '400'} ${REF}px ${family}`; }
    function refMetrics(g, font) {
      if (!glyph.metrics.has(font)) {
        const m = g.measureText('Hg');
        glyph.metrics.set(font, { asc: m.fontBoundingBoxAscent || REF * 0.8, dsc: m.fontBoundingBoxDescent || REF * 0.2 });
      }
      return glyph.metrics.get(font);
    }
    // Made ready while the page is idle, on the strong path: the app's type in each weight a card
    // uses, and its monospace (order numbers). The first use of a font was most of the cost of
    // sampling a card's letters; this moves it out of the frame that draws the card.
    function warmFonts() {
      if (weak || !glyph.ctx) return;
      const g = glyph.ctx;
      let body = '', mono = '';
      try {
        body = win.getComputedStyle(doc.body).fontFamily;
        mono = win.getComputedStyle(doc.documentElement).getPropertyValue('--mono').trim();
      } catch (e) { return; }
      for (const family of [body, mono]) {
        if (!family) continue;
        for (const weight of ['400', '500', '600', '700']) {
          g.font = refFont('normal', weight, family);
          refMetrics(g, g.font);
        }
      }
    }
    // Letter shapes: text drawn as the browser drew it (its font, weight, size, spacing, case) onto
    // a canvas the size of the card, then read back as points on a grid.
    function glyphCanvas(r, v) {
      const x0 = Math.max(0, Math.floor(r.x)), y0 = Math.max(0, Math.floor(r.y));
      const w = Math.min(Math.ceil(r.w), Math.ceil(v.w) - x0), h = Math.min(Math.ceil(r.h), Math.ceil(v.h) - y0);
      if (w <= 0 || h <= 0) return null;
      // One canvas for this, kept between arrivals: making a 2D context is a cost.
      let g = null;
      try {
        makeGlyph();
        glyph.el.width = w; glyph.el.height = h;       // sized afresh, which also empties it
        g = glyph.ctx;
      } catch (e) { g = null; }
      if (!g || typeof g.fillText !== 'function' || typeof g.getImageData !== 'function') return null;
      let drew = 0, styled = null, k = 1;
      const inked = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };   // what was drawn on
      // Every size of a weight is drawn from the one font at REF px, scaled to the size wanted, so a
      // card needs a font per weight and family rather than one per size (and those few can be made
      // ready while the page is idle: warmFonts).
      function style(cs) {
        if (styled === cs) return;
        styled = cs;
        const size = parseFloat(cs.fontSize) || 16;
        k = size / REF;
        const font = refFont(cs.fontStyle, cs.fontWeight, cs.fontFamily);
        if (g.font !== font) g.font = font;
        if ('letterSpacing' in g) {
          const ls = parseFloat(cs.letterSpacing);
          g.letterSpacing = cs.letterSpacing && cs.letterSpacing !== 'normal' && ls ? `${ls / k}px` : '0px';
        }
        g.fillStyle = '#fff';
        g.textBaseline = 'alphabetic';
      }
      // `text` set in the box `q` (a line box the browser gave it), on its baseline.
      function put(text, q, cs) {
        let t = String(text).replace(/\s+/g, ' ').trim();
        if (cs.textTransform === 'uppercase') t = t.toUpperCase();
        else if (cs.textTransform === 'lowercase') t = t.toLowerCase();
        if (!t) return false;
        style(cs);
        const m = refMetrics(g, g.font);
        const asc = m.asc * k, dsc = m.dsc * k;
        g.setTransform(k, 0, 0, k, q.x - x0, q.y - y0 + (q.h - asc - dsc) / 2 + asc);
        g.fillText(t, 0, 0);
        g.setTransform(1, 0, 0, 1, 0, 0);
        drew++;
        // Where ink can be: the box, a little wider for letters that lean or spread past it.
        inked.x0 = Math.min(inked.x0, q.x - x0 - 4); inked.y0 = Math.min(inked.y0, q.y - y0 - 2);
        inked.x1 = Math.max(inked.x1, q.x - x0 + q.w + 4); inked.y1 = Math.max(inked.y1, q.y - y0 + q.h + 2);
        return true;
      }
      return {
        draw(value, q, cs) {
          // Leading spaces take no ink but do take room at the start of the box.
          const lead = value.length - value.trimStart().length;
          if (lead) { style(cs); q = { x: q.x + g.measureText(value.slice(0, lead)).width * k, y: q.y, w: q.w, h: q.h }; }
          return put(value, q, cs);
        },
        // A run that wraps: each word where the browser put it.
        drawWords(t, cs) {
          const text = t.value;
          const re = /\S+/g;
          let m = re.exec(text), n = 0;
          while (m && n < 80) {
            t.range.setStart(t.node, m.index);
            t.range.setEnd(t.node, m.index + m[0].length);
            const b = t.range.getBoundingClientRect();
            if (b.width > 0 && b.height > 0) { put(m[0], { x: b.left, y: b.top, w: b.width, h: b.height }, cs); n++; }
            m = re.exec(text);
          }
          return n > 0;
        },
        // Read back only the part that was drawn on, not the whole card.
        points(step) {
          if (!drew) return [];
          const bx = Math.max(0, Math.floor(inked.x0)), by = Math.max(0, Math.floor(inked.y0));
          const bw = Math.min(w, Math.ceil(inked.x1)) - bx, bh = Math.min(h, Math.ceil(inked.y1)) - by;
          if (bw <= 0 || bh <= 0) return [];
          const d = g.getImageData(bx, by, bw, bh).data;
          const out = [];
          for (let yy = 0; yy < bh; yy += step) {
            for (let xx = 0; xx < bw; xx += step) {
              if (d[(yy * bw + xx) * 4 + 3] > 110) out.push({ x: x0 + bx + xx, y: y0 + by + yy });
            }
          }
          return out;
        },
      };
    }

    // ---- what happens to a card ---------------------------------------------------------

    function enabled() { return !!deck && !reduced() && !(doc.hidden); }

    // Put in the deck: hidden by the stylesheet at once (before it is ever painted), sampled on the
    // next frame, when the page has laid it out.
    function form(card) {
      if (!enabled()) return;
      card.classList.add('dots-forming');
      if (weak) card.classList.add('dots-brisk');
      forming.set(card, now());
      pending.push(card);
      ask();
    }
    function begin() {
      if (!pending.length) return;
      const cards = pending.splice(0).filter((c) => forming.has(c) && c.isConnected !== false);
      if (!cards.length) return;
      ensureCanvas();
      const from = source();
      const total = weak ? BUDGET.weak : BUDGET.strong;
      // Every card on screen sampled against the whole budget, then all of them thinned by the
      // same share: a deck of four with one on screen gives that one everything.
      // The page lays the new cards out first (it would in this frame anyway); what is timed is the
      // sampling alone.
      void deck.offsetHeight;
      const began = now();
      const samples = cards.map((card) => ({ card, got: sample(card, total) }));
      const took = now() - began;
      if (took > stats.sampleMs) stats.sampleMs = took;
      const sum = samples.reduce((n, x) => n + x.got.points.length, 0);
      const share = sum > total ? total / sum : 1;
      stats.events++;
      const t = now();
      for (const { card, got } of samples) {
        forming.set(card, t);
        if (share < 1) got.points = thin(got.points, Math.floor(got.points.length * share));
        remember(card, got.rect);
        const top = got.rect.y, span = Math.max(1, got.rect.h);
        for (const p of got.points) {
          const dx = p.x - from.x, dy = p.y - from.y, dist = Math.hypot(dx, dy) || 1;
          const bend = (rnd() < 0.5 ? -1 : 1) * dist * (0.1 + rnd() * 0.12);
          const a = rnd() * TAU, rr = rnd() * from.r * 0.5;
          // Held as a place ON the card (rx, ry), not on the glass: the deck can still be moving
          // when the card arrives (the orb's band shrinking as the screen changes, a scroll), and
          // every frame puts the dot where that place on the card is now.
          dots.push({
            sx: from.x + Math.cos(a) * rr, sy: from.y + Math.sin(a) * rr, tx: p.x, ty: p.y,
            rx: p.x - got.rect.x, ry: p.y - got.rect.y,
            kx: (-dy / dist) * bend, ky: (dx / dist) * bend,
            t0: t + clamp01((p.y - top) / span) * C.STAGGER + rnd() * C.JITTER,
            d: C.FLY_MIN + rnd() * (C.FLY_MAX - C.FLY_MIN), a: p.a, s: p.s, ink: p.ink, quick: !!p.quick, card, going: false, born: t,
          });
        }
        stats.formed++;
      }
      // One colour after the other, so a frame sets its colour twice rather than per dot.
      dots.sort((a, b) => (a.ink === b.ink ? 0 : a.ink === 'words' ? -1 : 1));
      stats.lastDots = dots.length;
      ask();
    }
    // The card is the stylesheet's throughout: fully shown by SHOWN_BY, when its entrance simply
    // ends (it holds nothing after, so an archived thread's own dimming still applies). At DONE,
    // on the same clock as the dots, it stops being counted as forming. Its class stays: taking it
    // off would start the ordinary entrance again, and changing it would restyle the card for
    // nothing. A card put back in the deck later starts its entrance afresh, as any inserted
    // element does.
    function settle(card) {
      forming.delete(card);
    }
    // Taken out of the deck: its shape (never its words) drifts back towards the orb and fades.
    function dissolve(card) {
      drop(card);
      if (!enabled()) return;
      const g = geom.get(card);
      if (!g) return;
      const v = view();
      const r = { x: g.x, y: g.y - (scrollTop - g.scroll), w: g.w, h: g.h };
      if (r.y > v.h || r.y + r.h < 0 || r.w < 8 || r.h < 8) return;
      ensureCanvas();
      const to = source();
      const t = now();
      const pts = thin(outline(r, g.radius, weak ? 12 : 7, v).concat(body(r, weak ? 26 : 16, v)), weak ? 260 : 900);
      for (const p of pts) {
        const k = 0.35 + rnd() * 0.25;
        dots.push({
          sx: p.x, sy: p.y, tx: p.x + (to.x - p.x) * k + (rnd() - 0.5) * 24, ty: p.y + (to.y - p.y) * k - rnd() * 20,
          kx: (rnd() - 0.5) * 30, ky: (rnd() - 0.5) * 30,
          t0: t + rnd() * 60, d: T.GO_MIN + rnd() * (T.GO_MAX - T.GO_MIN), a: 0.5, s: 1.3, ink: 'shape', card: null, going: true, born: t,
        });
      }
      stats.dissolved++;
      ask();
    }
    // A card gone: every dot drawing it (its words above all) is dropped, and the canvas is drawn
    // again now without them — not at the next frame.
    function drop(card) {
      const was = forming.has(card);
      forming.delete(card);
      const i = pending.indexOf(card);
      if (i !== -1) pending.splice(i, 1);
      if (card.classList) { card.classList.remove('dots-forming'); card.classList.remove('dots-brisk'); }
      const before = dots.length;
      if (before) dots = dots.filter((d) => d.card !== card);
      if (was || dots.length !== before) paint(now());
    }
    function remember(card, rect) {
      geom.set(card, { x: rect.x, y: rect.y, w: rect.w, h: rect.h, scroll: scrollTop, radius: cornerOf(card) });
    }
    // Where every card in the deck is, for the moment one is taken away (it cannot be measured
    // once it has gone).
    function measureDeck() {
      if (!deck) return;
      scrollTop = deck.scrollTop || 0;
      for (let c = deck.firstElementChild; c; c = c.nextElementSibling) {
        if (!isCard(c)) continue;
        const b = c.getBoundingClientRect();
        if (b.width || b.height) remember(c, { x: b.left, y: b.top, w: b.width, h: b.height });
      }
    }

    // ---- drawing ------------------------------------------------------------------------

    function ask() {
      if (frameAsked) return;
      frameAsked = raf(frame) || 1;
    }
    function frame() {
      frameAsked = 0;
      if (pending.length) begin();
      if (measureAsked) { measureAsked = false; measureDeck(); }
      const t = now();
      paint(t);
      for (const [card, born] of Array.from(forming)) if (t - born >= C.DONE) settle(card);
      if (dots.length || forming.size) ask();
    }
    function paint(t) {
      if (!dots.length) {
        if (drawing) { blank(); show(false); drawing = false; }
        return;
      }
      // Where each forming card is now, read once per frame. This is the layout the page does in
      // this frame anyway (the deck can be moving under the card), so it is not counted below.
      const at = new Map();
      for (const d of dots) {
        if (!d.card || at.has(d.card)) continue;
        const b = d.card.getBoundingClientRect();
        at.set(d.card, { x: b.left, y: b.top });
      }
      const t0 = now();
      const g = ctx || ensureCanvas();
      if (!drawing) { show(true); drawing = true; }
      blank();
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.globalCompositeOperation = 'lighter';
      const keep = [];
      let lastInk = '';
      for (const d of dots) {
        if (d.card) { const o = at.get(d.card); d.tx = o.x + d.rx; d.ty = o.y + d.ry; }
        const k = (t - d.t0) / d.d;
        let x, y, a;
        if (d.going) {
          if (k >= 1) continue;
          const e = ease.in(clamp01(k)), u = 1 - e;
          const mx = (d.sx + d.tx) / 2 + d.kx, my = (d.sy + d.ty) / 2 + d.ky;
          x = u * u * d.sx + 2 * u * e * mx + e * e * d.tx;
          y = u * u * d.sy + 2 * u * e * my + e * e * d.ty;
          a = d.a * (1 - ease.out(clamp01(k)));
        } else {
          const age = t - d.born;
          if (age >= C.DONE) continue;
          const kk = clamp01(k), e = ease.inout(kk), u = 1 - e;
          const mx = (d.sx + d.tx) / 2 + d.kx, my = (d.sy + d.ty) / 2 + d.ky;
          x = u * u * d.sx + 2 * u * e * mx + e * e * d.tx;
          y = u * u * d.sy + 2 * u * e * my + e * e * d.ty;
          // Dots on a line of words (not its letters) go first, before the words they stand for
          // are fully there; letters stay a moment longer, over their own letters.
          const f0 = d.quick ? C.QUICK_FROM : C.FADE_FROM, f1 = d.quick ? C.QUICK_DONE : C.DONE;
          if (age >= f1) continue;
          const out = age <= f0 ? 1 : 1 - ease.in(clamp01((age - f0) / (f1 - f0)));
          a = k <= 0 ? 0 : d.a * clamp01(kk / 0.35) * out;
        }
        keep.push(d);
        if (a <= 0.01) continue;
        if (d.ink !== lastInk) {
          const c = INK[d.ink] || INK.shape;
          g.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
          lastInk = d.ink;
        }
        g.globalAlpha = a > 1 ? 1 : a;
        const s = d.s;
        g.fillRect(x - s / 2, y - s / 2, s, s);
      }
      g.globalAlpha = 1;
      g.globalCompositeOperation = 'source-over';
      dots = keep;
      const ms = now() - t0;
      stats.frames++; stats.totalMs += ms; if (ms > stats.maxMs) stats.maxMs = ms;
      if (!dots.length) { blank(); show(false); drawing = false; }
    }

    // ---- watching the deck --------------------------------------------------------------

    function isCard(n) { return !!n && n.nodeType === 1 && n.classList && n.classList.contains('card'); }
    function cardsIn(list) {
      const out = [];
      for (const n of list || []) if (isCard(n)) out.push(n);
      return out;
    }
    // One batch of changes to the deck. A record that takes cards out and puts cards in at the
    // same place is a replacement in place (replaceChild: a patch, an action's result): neither
    // forms nor goes. A card both taken out and put back (moved, or its deck shown again in the
    // same breath) is neither too.
    function onMutations(records) {
      const added = [], removed = [];
      for (const r of records) {
        const adds = cardsIn(r.addedNodes), rems = cardsIn(r.removedNodes);
        const inPlace = adds.length > 0 && rems.length > 0;
        for (const c of rems) removed.push({ card: c, inPlace });
        if (!inPlace) for (const c of adds) added.push(c);
      }
      const back = new Set(added);
      for (const { card, inPlace } of removed) {
        if (back.has(card) || card.isConnected) continue;
        if (inPlace) drop(card); else dissolve(card);
      }
      for (const c of added) {
        if (!c.isConnected && c.isConnected !== undefined) continue;
        if (c.dataset && c.dataset.patched) continue;
        if (removed.some((x) => x.card === c)) continue;
        form(c);
      }
      measureAsked = true;
      ask();
    }

    function stopAll() {
      for (const card of Array.from(forming.keys())) settle(card);
      pending.length = 0;
      dots = [];
      paint(now());
    }

    let observer = null, sizes = null;
    function start() {
      if (!deck) return;
      if (typeof win.MutationObserver === 'function') {
        observer = new win.MutationObserver(onMutations);
        observer.observe(deck, { childList: true });
      }
      if (typeof deck.addEventListener === 'function') deck.addEventListener('scroll', () => { scrollTop = deck.scrollTop || 0; }, { passive: true });
      if (typeof win.ResizeObserver === 'function') {
        sizes = new win.ResizeObserver(() => { measureAsked = true; ask(); });
        sizes.observe(deck);
      }
      if (typeof win.addEventListener === 'function') win.addEventListener('resize', () => { measureAsked = true; ask(); }, { passive: true });
      if (typeof doc.addEventListener === 'function') doc.addEventListener('visibilitychange', () => { if (doc.hidden) stopAll(); });
      if (reducedQuery && typeof reducedQuery.addEventListener === 'function') reducedQuery.addEventListener('change', () => { if (reduced()) stopAll(); });
      measureAsked = true;
      ask();
      // The canvas is made and first drawn to while the page is idle, once: the first draw to a
      // new canvas is where its memory is found, and on the tablet that was the slowest frame of a
      // card's first arrival. Never under reduced motion, where it is never needed.
      if (!reduced()) {
        const warm = () => {
          try {
            if (reduced()) return;
            ensureCanvas(); blank();
            if (!weak) { makeGlyph(); warmFonts(); }
          } catch (e) { /* made when first needed */ }
        };
        if (typeof win.requestIdleCallback === 'function') win.requestIdleCallback(warm, { timeout: 4000 });
        else if (typeof win.setTimeout === 'function') win.setTimeout(warm, 2500);
      }
    }

    return {
      start, form, dissolve, drop, onMutations, frame, stopAll, measureDeck,
      busy: () => dots.length > 0 || pending.length > 0,
      dotCount: () => dots.length,
      wordsFor: (card) => dots.filter((d) => d.card === card && d.ink === 'words').length,
      isForming: (card) => forming.has(card),
      stats: () => Object.assign({ weak, avgMs: stats.frames ? stats.totalMs / stats.frames : 0 }, stats),
      canvas: () => canvas,
      destroy: () => { if (observer) observer.disconnect(); if (sizes) sizes.disconnect(); stopAll(); },
    };
  }

  function isWeak(win, doc) {
    try {
      const html = doc.documentElement;
      if (html && html.dataset && html.dataset.lite === '1') return true;
      return (win.navigator && (win.navigator.hardwareConcurrency || 8)) <= 4;
    } catch (e) { return true; }
  }
  function safeMatch(win, q) {
    try { return typeof win.matchMedia === 'function' ? win.matchMedia(q) : null; } catch (e) { return null; }
  }

  const api = { create, outline, body, lineDots, thin, TIMING: T, BRISK, BUDGET, isWeak };
  root.CliveAppDots = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  // In the page: watch the deck from now on.
  if (typeof window !== 'undefined' && root === window && typeof document !== 'undefined') {
    try {
      const deck = document.getElementById('cards');
      if (deck) {
        const engine = create({ win: window, doc: document, deck });
        engine.start();
        api.page = engine;
      }
    } catch (e) { /* the cards appear as they always have */ }
  }
})(typeof window !== 'undefined' ? window : globalThis);
