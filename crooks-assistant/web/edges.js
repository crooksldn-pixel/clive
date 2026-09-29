/* Soft scroll edges: what leaves a scrolling area fades out as it goes, and nothing is cut off
 * by an invisible line.
 *
 * The owner, 29 September: "when text scrolls out of view it should not be clipped but gradually
 * blur, same as at the bottom row. text that appears from no where or hidden behind an invisible
 * barrier looks cheap and unintentional." The bottom row he meant is the home list, whose last
 * 28px faded into the ask bar through a mask that was always on; its top edge, and both edges of
 * the cards, the sheets, the remote and every sideways strip, were a hard cut.
 *
 * So every scrolling area of the app is given the same edge, on every side that has content
 * beyond it, and only while it has:
 *
 * - The fade on an edge grows with how far there is to scroll past it, up to its full size. At
 *   the top of a list there is no top fade at all; scroll ten pixels and the first line starts to
 *   soften; scroll the edge's length and it is the full fade. The bottom does the same in reverse,
 *   so the last line of a list scrolled right to the end is never faded. This is the iOS scroll
 *   edge: tied to the scroll itself, with no timer and no transition to fall behind the finger.
 * - It is a CSS mask (a linear gradient with an eased ramp), written on the element itself. An
 *   area that has nothing beyond either edge carries no mask at all, so it costs nothing.
 * - Measured in one animation frame per burst of changes: a scroll, a resize, a card added or
 *   grown, a tab switched. The measurement reads four numbers per area; a mask is written only
 *   when a whole pixel of it changed.
 *
 * Which areas: named once, below, by the selectors the stylesheets give them. An area that is
 * added later (a sheet opened, a card with a table in it) is found as it is put on the page.
 *
 * Nothing here reads what any area says; it measures boxes.
 */
'use strict';

(function (root) {
  // The scrolling areas of the app, and how long each one's fade is at most (CSS px). The two
  // big lists get the longest; strips inside a card get a short one, because a card's own edge
  // is a few pixels away.
  // `veil`: the area also gets a blur band at each fading edge (below), where the device can
  // afford one.
  const AREAS = [
    { sel: '.cards', axis: 'y', size: 44, veil: true },          // the deck beside the orb (#cards)
    { sel: '.alpha-home', axis: 'y', size: 44, veil: true },     // the home: needs you, in motion
    { sel: '.sheet-scroll', axis: 'y', size: 36, veil: true },   // settings, an objective and its history, support
    { sel: '.rm-body', axis: 'y', size: 36, veil: true },        // the remote for a screen
    { sel: '.notes', axis: 'y', size: 18 },            // the notification bands, when they scroll
    { sel: '.health', axis: 'y', size: 18 },           // the diagnostics list in settings
    { sel: '.context-nav', axis: 'x', size: 32 },      // the trail of chips
    { sel: '.tabs', axis: 'x', size: 22 },             // a card's tabs
    { sel: '.table-wrap', axis: 'x', size: 22 },       // tables inside cards
    { sel: '.tbl-wrap', axis: 'x', size: 22 },
    { sel: '.matrix-wrap', axis: 'x', size: 22 },
  ];
  const SELECTOR = AREAS.map((a) => a.sel).join(',');
  // An edge fade never takes more than this share of what the area shows.
  const MAX_SHARE = 0.25;

  // How much fade each edge of an area gets, in whole CSS px: the distance there is still to
  // scroll past that edge, up to the area's size. {start, end}: top and bottom, or left and right.
  function fadeFor(pos, view, content, size) {
    const most = Math.max(0, Math.min(size, Math.floor(view * MAX_SHARE)));
    const past = Math.max(0, pos);
    const beyond = Math.max(0, content - view - past);
    return {
      start: Math.round(Math.min(most, past)),
      end: Math.round(Math.min(most, beyond)),
    };
  }

  // The mask for those fades. Eased, not linear: a straight ramp reads as a band with a hard
  // top; the smoothstep curve (0, .16, .5, .84, 1 at the quarters) reads as the words going
  // soft. An empty string when neither edge fades, so the area carries no mask at all.
  const RAMP = [0, 0.156, 0.5, 0.844, 1];
  function maskFor(axis, start, end) {
    if (!start && !end) return '';
    const dir = axis === 'x' ? 'to right' : 'to bottom';
    const a = (k) => (k >= 1 ? '#000' : k <= 0 ? 'rgba(0,0,0,0)' : `rgba(0,0,0,${k})`);
    const stops = [];
    if (start) for (let i = 0; i < RAMP.length; i++) stops.push(`${a(RAMP[i])} ${start * i / 4}px`);
    else stops.push('#000 0px');
    if (end) {
      for (let i = RAMP.length - 1; i >= 0; i--) {
        const back = end * i / 4;
        stops.push(`${a(RAMP[i])} ${back ? `calc(100% - ${back}px)` : '100%'}`);
      }
    } else stops.push('#000 100%');
    return `linear-gradient(${dir}, ${stops.join(', ')})`;
  }

  // One area's edges, now. Returns the fades it drew, for the tests and the browser checks.
  function measure(el, spec) {
    const y = spec.axis !== 'x';
    const pos = y ? el.scrollTop : el.scrollLeft;
    const view = y ? el.clientHeight : el.clientWidth;
    const content = y ? el.scrollHeight : el.scrollWidth;
    return fadeFor(pos, view, content, spec.size);
  }

  // The blur band ("veil"): a strip over each fading edge of a big area whose backdrop is blurred,
  // most at the edge and not at all at its inner side (web/edges.css), so words going out of view
  // go soft as well as faint — the iOS scroll edge. Its strength follows the fade. Only where the
  // device is not marked lite (web/app.js marks the Galaxy Tab A lite; there the fade alone does
  // the work, since a live blur under a moving list costs a weak GPU frames) and where the engine
  // has backdrop-filter at all.
  function veilsWanted(win, doc) {
    try {
      const html = doc.documentElement;
      if (html && html.dataset && html.dataset.lite === '1') return false;
      const css = win.CSS;
      return !!(css && typeof css.supports === 'function'
        && (css.supports('backdrop-filter', 'blur(2px)') || css.supports('-webkit-backdrop-filter', 'blur(2px)')));
    } catch (e) { return false; }
  }

  function create(win, doc) {
    const areas = new Map();                  // element -> { spec, mask, start, end, veils, placed }
    const dirty = new Set();
    let raf = 0, veils = null;                // veils: whether this device gets blur bands, asked once
    const wantVeils = () => (veils === null ? (veils = veilsWanted(win, doc)) : veils);
    const R = typeof win.requestAnimationFrame === 'function' ? win.requestAnimationFrame.bind(win) : (fn) => setTimeout(fn, 16);
    const resizes = typeof win.ResizeObserver === 'function' ? new win.ResizeObserver((entries) => {
      for (const e of entries) {
        const target = e.target;
        // A child grew or shrank: its area has more (or less) beyond its edges.
        const area = areas.has(target) ? target : target.parentNode;
        if (area && areas.has(area)) dirty.add(area);
      }
      schedule();
    }) : null;

    function specFor(el) {
      for (const a of AREAS) {
        try { if (el.matches(a.sel)) return a; } catch (e) { /* an old engine without :matches */ }
      }
      return null;
    }
    function draw(el) {
      const state = areas.get(el);
      if (!state) return null;
      if (!el.isConnected) { forget(el); return null; }
      const f = measure(el, state.spec);
      // The bands follow the area even when its fades stay the same (it moved or was resized).
      if (state.spec.veil) placeVeils(el, state, f);
      if (f.start === state.start && f.end === state.end) return f;
      state.start = f.start; state.end = f.end;
      const mask = maskFor(state.spec.axis, f.start, f.end);
      if (mask !== state.mask) {
        state.mask = mask;
        el.style.webkitMaskImage = mask;
        el.style.maskImage = mask;
      }
      // What it drew is kept here, not on the element: a copy of the screen (web/telemetry.js)
      // keeps only the data- names app/observability/screens.py lists, and these say nothing
      // about the business. A check reads it with state().
      return f;
    }
    // The two bands sit beside the area (its next sibling, so they share its containing block),
    // laid over its top and bottom edges. Made the first time an edge fades, never before.
    function placeVeils(el, state, f) {
      if (!wantVeils()) { if (state.veils) dropVeils(state); return; }
      if (!f.start && !f.end && !state.veils) return;
      if (!state.veils) {
        const make = (edge) => {
          const v = doc.createElement('div');
          v.className = `edge-veil edge-veil-${edge}`;
          v.setAttribute('aria-hidden', 'true');
          return v;
        };
        state.veils = { start: make('start'), end: make('end') };
      }
      const parent = el.parentNode;
      if (!parent) return;
      const { start, end } = state.veils;
      if (start.parentNode !== parent || start.previousSibling !== el) parent.insertBefore(start, el.nextSibling);
      if (end.parentNode !== parent || end.previousSibling !== start) parent.insertBefore(end, start.nextSibling);
      const top = el.offsetTop + el.clientTop, left = el.offsetLeft + el.clientLeft;
      const w = el.clientWidth, h = el.clientHeight;
      const most = Math.max(1, Math.min(state.spec.size, Math.floor(h * MAX_SHARE)));
      // Written only when something about them changed: a scroll that moves no fade writes nothing.
      const key = `${top},${left},${w},${h},${f.start},${f.end}`;
      if (key === state.placed) return;
      state.placed = key;
      const put = (v, y, k) => {
        v.style.left = left + 'px'; v.style.top = y + 'px'; v.style.width = w + 'px'; v.style.height = most + 'px';
        v.style.opacity = k > 0 ? String(Math.min(1, k)) : '0';
      };
      put(start, top, f.start / most);
      put(end, top + h - most, f.end / most);
    }
    function dropVeils(state) {
      if (!state.veils) return;
      for (const v of [state.veils.start, state.veils.end]) if (v.parentNode) v.parentNode.removeChild(v);
      state.veils = null;
      state.placed = '';
    }
    function flush() {
      raf = 0;
      const list = Array.from(dirty);
      dirty.clear();
      for (const el of list) draw(el);
    }
    function schedule() { if (!raf && dirty.size) raf = R(flush); }
    function touch(el) { if (areas.has(el)) { dirty.add(el); schedule(); } }
    function everything() { for (const el of areas.keys()) dirty.add(el); schedule(); }

    function watchChildren(el) {
      if (!resizes) return;
      for (let c = el.firstElementChild; c; c = c.nextElementSibling) resizes.observe(c);
    }
    function adopt(el) {
      if (areas.has(el)) return;
      const spec = specFor(el);
      if (!spec) return;
      const state = { spec, mask: '', start: -1, end: -1, veils: null, placed: '', onScroll: () => touch(el) };
      areas.set(el, state);
      el.addEventListener('scroll', state.onScroll, { passive: true });
      if (resizes) { resizes.observe(el); watchChildren(el); }
      dirty.add(el);
      schedule();
    }
    function forget(el) {
      const state = areas.get(el);
      if (!state) return;
      areas.delete(el);
      dirty.delete(el);
      dropVeils(state);
      el.removeEventListener('scroll', state.onScroll);
      if (resizes) {
        resizes.unobserve(el);
        for (let c = el.firstElementChild; c; c = c.nextElementSibling) resizes.unobserve(c);
      }
    }
    // Every area under a node that was just put on the page, the node itself included.
    function find(node) {
      if (!node || node.nodeType !== 1) return;
      if (specFor(node)) adopt(node);
      if (typeof node.querySelectorAll === 'function') for (const el of node.querySelectorAll(SELECTOR)) adopt(el);
    }
    function scan() { find(doc.body || doc.documentElement); }

    // Anything added anywhere may be a new area, or new content in one. Content changing inside
    // an area is caught by the size of its children (above); a child added or taken away here.
    const watcher = typeof win.MutationObserver === 'function' ? new win.MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          find(n);
          if (resizes && n.nodeType === 1 && areas.has(r.target)) resizes.observe(n);
        }
        let area = r.target;
        while (area && area.nodeType === 1 && !areas.has(area)) area = area.parentNode;
        if (area && areas.has(area)) dirty.add(area);
      }
      for (const el of areas.keys()) if (!el.isConnected) forget(el);
      schedule();
    }) : null;

    function start() {
      scan();
      if (watcher && (doc.body || doc.documentElement)) watcher.observe(doc.body || doc.documentElement, { childList: true, subtree: true });
      if (typeof win.addEventListener === 'function') {
        win.addEventListener('resize', everything, { passive: true });
        // A picture that loads, or a font that arrives, makes a list longer with no other sign.
        win.addEventListener('load', everything, { passive: true, capture: true });
      }
      // A tab switched or a section folded changes an area's height by class or attribute.
      if (typeof doc.addEventListener === 'function') doc.addEventListener('click', () => { everything(); }, { passive: true, capture: true });
    }

    return {
      start, adopt, forget, scan, flush, touch, everything,
      // What an area shows now, for checks: { start, end, mask } or null.
      state: (el) => {
        const s = areas.get(el);
        return s ? { start: s.start, end: s.end, mask: s.mask } : null;
      },
      size: () => areas.size,
    };
  }

  const api = { AREAS, fadeFor, maskFor, measure, create, veilsWanted };
  root.CliveEdges = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  // In the page: begin at once. The script is at the end of the body, so the page is there.
  if (typeof window !== 'undefined' && root === window && typeof document !== 'undefined' && document.body) {
    try {
      const edges = create(window, document);
      edges.start();
      api.page = edges;
    } catch (e) { /* the areas keep their plain edges */ }
  }
})(typeof window !== 'undefined' ? window : globalThis);
