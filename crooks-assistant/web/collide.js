/* CROOKS OS — what is actually on top of what, measured.
 *
 * The live tablet session recorded `clipped=0` for every render while the owner was looking at
 * overlapping text and controls. `clipped` was `scrollWidth > clientWidth` on a card: it can
 * only see a box that is too small for its own contents. It cannot see two boxes that are each
 * the right size and in the same place — which is what overlap is, and what he saw.
 *
 * So this measures geometry. It collects `getBoundingClientRect()` for every control, every
 * leaf of text, every notification and every piece of fixed chrome on screen, and reports the
 * pairs that are in the same place. Seven rules, named, each one a thing the owner would call
 * a fault:
 *
 *   control_over_control     two things a finger can press, in the same place
 *   text_over_control        words printed across a control
 *   notification_over_chrome a message covering the dock, the orb, the halves, the composer
 *   rail_over_content        an action rail laid over what it is about
 *   document_overflow_x      the page scrolls sideways by accident
 *   folded_action            a control that is on screen at no width, or a sliver of one
 *   content_under_chrome     something essential underneath the fixed furniture
 *
 * Phase 5 §9 asks for a NAMED verdict on fourteen specific pairs, and makes an interactive
 * overlap a hard release failure rather than a number in a report. Eight of the fourteen were
 * already inside the two generic rules above and said nothing about themselves when they
 * fired; the rest could not fire at all. So the pair rules below are SPECIALISATIONS: a hit is
 * classified into the most specific rule that describes it and counted exactly once, which
 * keeps `total` the same measurement the telemetry has been recording while giving every pair
 * §9 names its own line. `PAIRS` maps each of the fourteen to the rules that cover it.
 *
 *   split_under_voice        the Split chip painted or hit-tested under the voice target
 *   branch_under_voice       a branch chip, Merge or Close, ditto
 *   button_over_input        a control over a field
 *   button_over_navigation   a control over Back / Next / Home / the dock / the rail
 *   toast_over_navigation    a message over the navigation row
 *   toast_over_orb           a message over the orb
 *   toast_over_approval      a message over an approval surface
 *   floating_over_dock       a floating control over the dock
 *   tabs_over_content        a tab strip over the panel it switches
 *   name_over_action         a long customer or product name across an action
 *   chips_over_title         status chips across a card title
 *   keyboard_over_action     with the keyboard open, an action under the fixed furniture
 *   control_clipped_by_container
 *                            an interactive element cut off by the viewport or by a container
 *                            that clips it — no two rectangles intersect, so no pair rule can
 *                            see it, and `document_overflow_x` cannot either because the
 *                            overflow is CLIPPED rather than extending the document. It is how
 *                            the second branch chip came to hang off the right edge of a
 *                            601 px screen with every check green.
 *
 * `check()` also returns `interactive`: the number of hits in which at least one side is
 * something a finger presses. §9 is a hard gate on that number being zero, so it is computed
 * from the hits themselves rather than from a list of rule names that could drift.
 *
 * Two halves, deliberately: `check(records)` is arithmetic over plain rectangles and runs
 * anywhere, so the rules themselves are unit-testable without a browser; `collect(doc)` and
 * `scan(opts)` read a real document and are the only part that needs one. The tablet's
 * telemetry calls `scan` so a future session records the truth (web/telemetry.js), and
 * scripts/browser/collision.js calls it in Chromium so a defect fails a gate rather than
 * waiting for the owner to see it.
 *
 * Nothing here reads a word of what a card says. A record carries a selector — tag, id, the
 * first class — and a rectangle, and that is all.
 */
(function (root) {
  'use strict';

  const TOL = 2;              // px of overlap in BOTH axes before a pair counts
  const SLIVER = 8;           // a control narrower or shorter than this is folded away
  const TOUCH = 44;           // the practical hit area, in CSS px
  const MAX_HITS = 24;        // bounded: a report, not a dump

  const RULES = [
    'control_over_control',
    'text_over_control',
    'notification_over_chrome',
    'rail_over_content',
    'document_overflow_x',
    'folded_action',
    'content_under_chrome',
    // §9's named pairs. Specialisations of the seven above, or their own measurement.
    'split_under_voice',
    'branch_under_voice',
    'button_over_input',
    'button_over_navigation',
    'toast_over_navigation',
    'toast_over_orb',
    'toast_over_approval',
    'floating_over_dock',
    'tabs_over_content',
    'name_over_action',
    'chips_over_title',
    'keyboard_over_action',
    'control_clipped_by_container',
  ];

  /* §9's required pair checks, each naming the rules that answer it. The key is the brief's
     own word for the pair, so a gate can print the brief's list and nothing has to be
     translated by hand. A pair with more than one rule is answered by their sum. */
  const PAIRS = {
    'button-button': ['control_over_control', 'floating_over_dock'],
    'button-text': ['text_over_control', 'name_over_action', 'chips_over_title'],
    'button-input': ['button_over_input'],
    'button-navigation': ['button_over_navigation'],
    'Split-voice': ['split_under_voice'],
    'branch-voice': ['branch_under_voice'],
    'toast-navigation': ['toast_over_navigation'],
    'toast-orb': ['toast_over_orb'],
    'toast-approval': ['toast_over_approval'],
    'floating-controls-dock': ['floating_over_dock'],
    'tabs-content': ['tabs_over_content'],
    'long-name-action': ['name_over_action'],
    'chips-title': ['chips_over_title'],
    'keyboard-action': ['keyboard_over_action'],
  };

  // Not collisions: one is a property of the document, one of a single control. They are real
  // faults and keep their rules, but they are not what §9 counts.
  const NOT_A_COLLISION = ['document_overflow_x', 'folded_action'];

  // ---- what counts as what, as selectors. One list per kind; a node can be in several.
  const SEL = {
    // Something a finger presses. `#talk` is deliberately absent: it is the transparent
    // hold region that lies UNDER the dock by design, so counting it as a control would
    // report the design as a defect. It is chrome here, and a card control that strays into
    // its band is caught by `content_under_chrome` instead — which is the real fault.
    control: [
      'button:not(#talk)', '[role="button"]', '[role="tab"]', 'a[href]', 'input', 'select', 'textarea',
      'summary', '.action-surface', '.row.tappable', '.link-strip', '.variant-row', '.ws-opt',
    ],
    // A message. The three classes of web/notify.js, and the old floating bubble.
    notification: ['.note', '.toast', '[data-notify]'],
    // Furniture a message must never cover, and the controls the brief names: the dock, the
    // orb, the branch band, Back, Next, the composer, the approval surfaces. Split's chips,
    // Merge and Close went on 8 October (DEC-071, ruling 37), and nothing draws them now.
    chrome: [
      '#talk', '#talk-label', '.dock-btn', '#orb-frame', '#branch-zone', '#branch-bar',
      '#home-btn', '#back-btn', '#next-btn',
      '.action-surface', '.compose-btn', '.field-input', '.variant-add', '.armed',
    ],
    // An action rail: a group of controls that belongs beside its content, never over it.
    rail: ['.rail', '.actions', '.row-actions', '.compose-actions', '.link-chips', '.variant-foot', '.ws-options'],
    // What the first screenful has to carry. If one of these is underneath the furniture the
    // owner cannot read or reach it, whatever the backend returned.
    essential: [
      '.card-title', '.action-surface', '.rail-chip', '.compose-btn', '.field-input',
      '.variant-add', '.row.tappable', '.fold-head',
    ],
    // ---- §9's pair sides. Each one narrow on purpose: a pair rule that matches half the page
    // says nothing about the pair it is named after.
    //
    // The voice target. `#talk` is the transparent hold region and `#talk-label` the pill
    // inside it; in orb mode `.talk` is `inset:0`, so this is the whole screen. Nothing
    // interactive may be under it, which is the entire content of D-1.
    voice: ['#talk', '#talk-label'],
    // The way in and out: the navigation row and the dock. A control over one of these, or one
    // of these cut off, is a control the owner cannot use to leave where he is.
    navigation: [
      '#context-nav', '#home-btn', '#back-btn', '#next-btn', '#prev-btn', '#dock',
      '.chip-home', '.chip-step', '.dock-btn', '#stack', '#recent', '#attention',
    ],
    dock: ['#dock', '.dock-btn'],
    // The halves. Split was deleted (DEC-071, ruling 37) and nothing draws its controls, but
    // §9's Split-voice and branch-voice pairs still stand on these two groups, so each keeps
    // the one shape that would bring Split back to the screen: a `data-action="split"` control,
    // and a `.branch-chip` in the band the page still lays out empty and hidden.
    split: ['[data-action="split"]'],
    branch: ['.branch-chip', '#branch-bar', '#branch-rail', '#branch-head'],
    orb: ['#orb-frame', '#orb', '.orb-caption'],
    // Where a change is authorised. A message over one of these is a message over the only
    // thing on the tablet that can alter the shop.
    approval: ['.action-surface', '.armed', '.confirm', '.commit', '.undo-surface'],
    // A field, and the things that switch and act.
    input: ['input', 'select', 'textarea', '.field-input', '[contenteditable="true"]'],
    tabstrip: ['.tabs', '[role="tablist"]', '[role="tab"]'],
    panel: ['[role="tabpanel"]', '.panel', '.stats', '.kv', '.rows', '.card-body', '.cap-rows'],
    action: [
      '.action-surface', '.rail-chip', '.compose-btn', '.variant-add', '.row-btn',
      '.btn', '.link-btn', '.step-btn', '.armed-cancel', '.note-close',
    ],
    // A name the shop supplied, and the title it sits in: the two text runs §9 asks about by
    // name ("long-name-action", "chips-title").
    entityname: ['.card-title', '.card-sub', '.head-main', '.row-main', '.profile .card-title'],
    title: ['.card-title', '.card-head h2'],
    chip: ['.badge', '.chip', '.tag', '.badges', '.filter-chip'],
  };

  const sel = (kind) => SEL[kind].join(',');

  // ---- the arithmetic ------------------------------------------------------------------

  function overlap(a, b) {
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return w > TOL && h > TOL ? { w: Math.round(w), h: Math.round(h) } : null;
  }

  // Ancestry by path, so the rules never need a node. A record's path is its position in the
  // tree as "/0/3/1"; `a` contains `b` when a's path is a prefix of b's at a boundary.
  function contains(a, b) {
    return b.path.length > a.path.length && b.path.indexOf(a.path) === 0 && b.path.charAt(a.path.length) === '/';
  }
  const related = (a, b) => a.path === b.path || contains(a, b) || contains(b, a);

  const has = (record, kind) => record.kinds.indexOf(kind) !== -1;
  const onScreen = (r, view) => r.rect.right > 0 && r.rect.left < view.w && r.rect.bottom > 0 && r.rect.top < view.h;
  const drawn = (r) => r.rect.width > 0 && r.rect.height > 0;

  /* The rules, over records. Pure: the same records give the same hits, in the same order,
     in Node or in Chromium. */
  function check(records, opts) {
    const options = opts || {};
    const view = options.viewport || { w: 0, h: 0 };
    const hits = [];
    const box = (r) => (r ? `${Math.round(r.rect.left)},${Math.round(r.rect.top)} ${Math.round(r.rect.width)}x${Math.round(r.rect.height)}` : '');
    const add = (rule, a, b, over, note) => {
      hits.push({
        rule, a: a ? a.sel : '', b: b ? b.sel : '',
        at: box(a), bt: box(b),
        w: over ? over.w : 0, h: over ? over.h : 0,
        note: note || '',
        // Was a finger involved? §9's hard gate counts these and nothing else, so it is
        // recorded on the hit rather than inferred later from the rule's name.
        ia: Boolean(a && has(a, 'control')), ib: Boolean(b && has(b, 'control')),
      });
    };

    const visible = records.filter((r) => r.shown && (!view.w || onScreen(r, view)));
    const controls = visible.filter((r) => has(r, 'control') && drawn(r));
    const texts = visible.filter((r) => has(r, 'text') && drawn(r));
    const notes = visible.filter((r) => has(r, 'notification') && drawn(r));
    const chrome = visible.filter((r) => has(r, 'chrome') && drawn(r));
    const rails = visible.filter((r) => has(r, 'rail') && drawn(r));
    const voice = visible.filter((r) => has(r, 'voice') && drawn(r));

    /* Which of §9's pairs a control-over-control hit actually is. Most specific first, and
       exactly one answer, so `total` counts the collision once however many names describe it. */
    const controlPair = (a, b) => {
      const floating = (x, y) => x.floating && has(y, 'dock');
      if (floating(a, b) || floating(b, a)) return 'floating_over_dock';
      if (has(a, 'input') || has(b, 'input')) return 'button_over_input';
      if (has(a, 'navigation') || has(b, 'navigation')) return 'button_over_navigation';
      if ((has(a, 'tabstrip') && has(b, 'panel')) || (has(b, 'tabstrip') && has(a, 'panel'))) return 'tabs_over_content';
      return 'control_over_control';
    };

    /* And which a text-over-control hit is. `t` is the words, `c` the control. */
    const textPair = (t, c) => {
      if (has(t, 'entityname') && has(c, 'action')) return 'name_over_action';
      if (has(t, 'title') && has(c, 'chip')) return 'chips_over_title';
      if (has(c, 'tabstrip') && has(t, 'panel')) return 'tabs_over_content';
      if (has(c, 'navigation')) return 'button_over_navigation';
      return 'text_over_control';
    };

    // 1 · two controls in the same place.
    for (let i = 0; i < controls.length; i++) {
      for (let j = i + 1; j < controls.length; j++) {
        const a = controls[i]; const b = controls[j];
        if (related(a, b)) continue;
        const over = overlap(a.rect, b.rect);
        if (over) add(controlPair(a, b), a, b, over);
      }
    }

    // 2 · words across a control. A text leaf inside the control is its label, not a fault.
    for (const t of texts) {
      for (const c of controls) {
        if (related(t, c)) continue;
        const over = overlap(t.rect, c.rect);
        if (over) add(textPair(t, c), t, c, over);
      }
    }

    // 3 · a message over the furniture. Both directions of containment are excluded: a note
    // drawn INSIDE the composer is attached to it, which is the whole point of a local one.
    for (const n of notes) {
      for (const c of chrome) {
        if (related(n, c)) continue;
        const over = overlap(n.rect, c.rect);
        if (!over) continue;
        // §9 wants the three destinations named separately: the owner's three complaints about
        // a floating message were about the navigation row, the orb, and an approval card.
        const rule = has(c, 'navigation') ? 'toast_over_navigation'
          : has(c, 'orb') ? 'toast_over_orb'
            : has(c, 'approval') ? 'toast_over_approval'
              : 'notification_over_chrome';
        add(rule, n, c, over);
      }
    }

    /* 3b · D-1, named. The Split chip, the branch chips, Merge and Close, against the voice
       target — by geometry AND by hit test, because the defect was never an overlap the eye
       could see: `#branch-bar` is a child of `.orb-zone`, a positioned element at z-index 1,
       so no z-index inside it can lift a chip above a `#talk` painted at 3 with `inset:0`.
       The chips are drawn perfectly and the browser hands the touch to the microphone.

       This is the rule that must fail on the tree that produced the live session, and pass on
       the tree that fixes it. It is written against `#talk` deliberately: `#talk` is chrome
       here, not a control, so `control_over_control` cannot and should not see it. */
    // Split first and exclusively: the Split chip is a branch control too, and the same
    // unreachable button must not be counted twice under two names.
    for (const c of visible) {
      if (!has(c, 'control') || !drawn(c)) continue;
      const rule = has(c, 'split') ? 'split_under_voice' : has(c, 'branch') ? 'branch_under_voice' : '';
      if (!rule) continue;
      // `covered_by` is the selector the browser's own hit test returned at the control's
      // centre: `button#talk.talk`, or `span#talk-label.talk-label` for the pill inside it.
      if (c.covered_by && c.covered_by.indexOf('#talk') !== -1) {
        add(rule, c, null, null, `the hit test at its centre reaches ${c.covered_by}`);
        continue;
      }
      for (const v of voice) {
        if (related(c, v)) continue;
        const over = overlap(c.rect, v.rect);
        if (over) { add(rule, c, v, over, 'painted under the voice target'); break; }
      }
    }

    // 4 · a rail over content it does not own.
    for (const rail of rails) {
      for (const t of texts) {
        if (related(rail, t)) continue;
        const over = overlap(rail.rect, t.rect);
        if (over) add('rail_over_content', rail, t, over);
      }
    }

    // 5 · the document scrolls sideways.
    if (options.document && options.document.scroll_width > options.document.client_width + 1) {
      add('document_overflow_x', null, null, null,
        `${options.document.scroll_width} > ${options.document.client_width}`);
    }

    // 6 · a control that is on screen at no width, or a sliver of one. `shown` already
    // excludes display:none and [hidden]; what is left is a control the layout squeezed.
    for (const c of visible.filter((r) => has(r, 'control'))) {
      const asked = c.asked || c.rect;
      if (asked.width < 1 || asked.height < 1) add('folded_action', c, null, null, 'zero size');
      else if (asked.width < SLIVER || asked.height < SLIVER) {
        add('folded_action', c, null, null, `${Math.round(asked.width)}×${Math.round(asked.height)}`);
      }
    }

    // 7 · something essential underneath the furniture. The collector hit-tests each
    // essential element's own centre; `covered_by` is what the browser found on top.
    //
    // `essential` only. The collector hit-tests every CONTROL now as well, because §9's
    // Split-voice and branch-voice rules are occlusion questions and there is no other honest
    // way to ask them — but a control the owner has scrolled half under the dock is not the
    // same fault as an essential element buried by the furniture, and widening this rule to
    // every covered control would have changed what the telemetry has been counting.
    for (const e of visible) {
      if (!e.covered_by || !has(e, 'essential')) continue;
      add('content_under_chrome', e, null, null, e.covered_by);
    }

    /* 8 · §9's "keyboard-action": with the keyboard up, an action the owner is being asked to
       take is under the fixed furniture. Only measured when the caller says the keyboard is
       open, because the same geometry with the keyboard down is a different question — the
       viewport is half the height and every fixed thing has moved. */
    if (options.keyboard) {
      const fixedChrome = visible.filter((r) => has(r, 'chrome') && r.floating && drawn(r));
      for (const a of controls) {
        if (!has(a, 'action')) continue;
        for (const f of fixedChrome) {
          if (related(a, f)) continue;
          const over = overlap(a.rect, f.rect);
          if (over) { add('keyboard_over_action', a, f, over, 'the keyboard is open'); break; }
        }
      }
    }

    /* 9 · an interactive element cut off by the viewport, or by a container that clips it.
       No two rectangles intersect, so nothing above can see it; `document_overflow_x` cannot
       either, because the overflow is CLIPPED by an ancestor rather than extending the
       document — `scrollWidth === clientWidth` and the page looks fine. That is how the
       second branch chip came to hang off the right-hand edge of a 601 px screen with every
       check on this file green.

       Two firing conditions, and only two, so a scrolling deck does not produce noise:

         a. the control is part of the fixed furniture — the navigation row, the dock, the
            halves. Those must be wholly reachable WITHOUT scrolling: nothing on the glass
            says a navigation strip continues past the edge of the screen.
         b. nothing can scroll on the axis it is clipped on, so there is no way to reveal it
            at all.

       A card scrolled down the deck fails neither: it is not furniture, and the deck scrolls
       vertically. Which is right — that is the interaction, not a defect. */
    for (const c of records) {
      if (!has(c, 'control') || c.invisible) continue;
      const lostX = Math.round(c.clip_x || 0);
      const lostY = Math.round(c.clip_y || 0);
      if (lostX <= TOL && lostY <= TOL) continue;
      const furniture = has(c, 'navigation') || has(c, 'branch') || has(c, 'split') || has(c, 'dock');
      const trapped = (lostX > TOL && !c.scrollable_x) || (lostY > TOL && !c.scrollable_y);
      if (!furniture && !trapped) continue;
      const why = furniture ? 'fixed furniture must fit the screen' : 'nothing scrolls on that axis';
      add('control_clipped_by_container', c, null, null,
        `${lostX ? `${lostX}px off the side` : ''}${lostX && lostY ? ', ' : ''}${lostY ? `${lostY}px off the top or bottom` : ''} — ${why}`);
    }

    const counts = {};
    for (const rule of RULES) counts[rule] = 0;
    for (const hit of hits) counts[hit.rule] = (counts[hit.rule] || 0) + 1;
    // One example of every rule that fired, first; then as much of the tail as the cap allows.
    const kept = [];
    for (const rule of RULES) {
      const first = hits.find((h) => h.rule === rule);
      if (first) kept.push(first);
    }
    for (const hit of hits) {
      if (kept.length >= MAX_HITS) break;
      if (kept.indexOf(hit) === -1) kept.push(hit);
    }
    // §9's hard gate: how many of these involve something a finger presses. A sideways
    // document scroll does not; a control squeezed to a sliver is a different fault with its
    // own rule. Everything else that names an interactive element on either side counts.
    const interactive = hits.filter((h) => NOT_A_COLLISION.indexOf(h.rule) === -1 && (h.ia || h.ib));
    // And the fourteen §9 asked for by name, each with its own number, so a gate can print
    // the brief's own list.
    const pairs = {};
    for (const label of Object.keys(PAIRS)) {
      pairs[label] = PAIRS[label].reduce((sum, rule) => sum + (counts[rule] || 0), 0);
    }
    return {
      total: hits.length, counts, hits: kept,
      interactive: interactive.length,
      interactive_hits: interactive.slice(0, MAX_HITS),
      pairs,
    };
  }

  /* Controls too small for a thumb, and text-only actions with no box at all (section 29).
     Not a collision — reported beside them because it is the same measurement. */
  function touch(records, opts) {
    const options = opts || {};
    const floor = options.floor || TOUCH;
    const view = options.viewport || { w: 0, h: 0 };
    const small = [];
    for (const r of records) {
      if (!r.shown || !has(r, 'control') || !drawn(r)) continue;
      if (view.w && !onScreen(r, view)) continue;
      if (r.decorative) continue;
      const asked = r.asked || r.rect;
      const w = Math.round(asked.width); const h = Math.round(asked.height);
      if (Math.min(w, h) + 0.5 < floor) small.push({ sel: r.sel, w, h });
    }
    return small.slice(0, MAX_HITS);
  }

  // ---- reading a real document ---------------------------------------------------------

  function selectorOf(node) {
    const tag = String(node.tagName || '').toLowerCase();
    const id = node.id ? `#${node.id}` : '';
    const cls = String(node.className || '');
    const first = cls && typeof cls === 'string' ? cls.trim().split(/\s+/)[0] : '';
    return `${tag}${id}${first ? `.${first}` : ''}`;
  }

  // Its own words, not its children's: a text LEAF. A card is not text; the line inside it is.
  function ownText(node) {
    let out = '';
    const kids = node.childNodes || [];
    for (let i = 0; i < kids.length; i++) {
      const kid = kids[i];
      if (kid.nodeType === 3 && kid.data) out += kid.data;
    }
    return out.trim();
  }

  function matches(node, selector) {
    try { return typeof node.matches === 'function' && node.matches(selector); } catch { return false; }
  }

  const intersect = (a, b) => ({
    left: Math.max(a.left, b.left), top: Math.max(a.top, b.top),
    right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom),
  });
  const boxOf = (rect) => ({
    left: rect.left, top: rect.top,
    right: rect.right === undefined ? rect.left + rect.width : rect.right,
    bottom: rect.bottom === undefined ? rect.top + rect.height : rect.bottom,
  });

  /* Every node worth a rectangle, walked once, each one clipped by what is above it.
     `root` defaults to the document body, so a scan covers the chrome and the cards
     together — which is where the overlaps are. */
  function collect(doc, opts) {
    const options = opts || {};
    const scope = options.root || (doc.body || null);
    if (!scope) return [];
    const view = options.viewport || { w: 0, h: 0 };
    const styles = typeof options.styleOf === 'function'
      ? options.styleOf
      : (node) => (doc.defaultView && doc.defaultView.getComputedStyle ? doc.defaultView.getComputedStyle(node) : null);
    const out = [];
    const seen = [];
    const screen = { left: 0, top: 0, right: view.w || 1e6, bottom: view.h || 1e6 };

    const walk = (node, path, clip, scrollable, faded) => {
      if (!node || node.nodeType !== 1) return;
      const tag = String(node.tagName || '').toUpperCase();
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'SVG' || tag === 'TEMPLATE') return;
      const style = styles(node) || {};
      const display = style.display || '';
      const gone = Boolean(node.hidden) || display === 'none';
      if (gone) return;   // and its children with it: nothing under display:none has a place
      /* Invisibility is INHERITED, because `opacity` is not.
         `visibility:hidden` does inherit, so a child of `.context` computes `hidden` and was
         always caught. `opacity:0` does not: the footer is `body[data-mode="context"]
         .bottom{opacity:0;height:0;overflow:hidden}`, and `#recent` inside it computes
         `opacity:1` — so the walker read a fully visible 48 px navigation control that the
         layout had squeezed to nothing, and `control_clipped_by_container` reported the
         design as a defect ("48px off the top or bottom — fixed furniture must fit the
         screen"). Nothing inside a zero-opacity ancestor is on the glass, so the flag goes
         down the tree with the rest of the clip.

         THE LIMIT, named because R-1 is what happens when one is not. A faded element is
         still HIT-TESTABLE: `opacity:0` receives the touch, `visibility:hidden` does not.
         So this flag settles whether something is ON THE GLASS, and geometry must not be
         asked whether an invisible layer is swallowing taps — it cannot see that, and this
         change makes it see it less. The instrument for that question is the `hit_test` step
         in scripts/browser/replay.js, which asks `elementFromPoint` at the centre of a
         control what the browser would hand the finger to, and which catches a transparent
         overlay whatever its opacity. That is the D-1 instrument; this one measures layout. */
      const invisible = faded || style.visibility === 'hidden' || style.opacity === '0';
      const inert = style.pointerEvents === 'none';
      const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
      // Fixed furniture is not inside anybody's scroller: the dock, the hold band and the
      // sheet are painted against the screen, so their clip is the screen.
      const pinned = style.position === 'fixed';
      let here = pinned ? screen : clip;
      // Whether anything above this node can actually scroll to reveal what is cut off. Reset
      // for fixed furniture, which is not inside anybody's scroller by construction.
      let reveals = pinned ? { x: false, y: false } : scrollable;
      if (rect) {
        const own = boxOf(rect);
        const box = intersect(own, here);
        const clipped = box.right - box.left <= 0 || box.bottom - box.top <= 0;
        const kinds = [];
        // A control that cannot be touched is not a control: the transparent overlays and the
        // decorative layers would otherwise read as a screenful of collisions.
        if (!inert && !invisible && matches(node, sel('control'))) kinds.push('control');
        if (matches(node, sel('notification'))) kinds.push('notification');
        if (matches(node, sel('chrome'))) kinds.push('chrome');
        if (matches(node, sel('rail'))) kinds.push('rail');
        if (matches(node, sel('essential'))) kinds.push('essential');
        // §9's pair sides. Cheap: one `matches` per group, on the nodes that already earned a
        // record. A node can be several of these — a dock button is navigation AND dock.
        for (const kind of ['voice', 'navigation', 'dock', 'split', 'branch', 'orb', 'approval',
                            'input', 'tabstrip', 'panel', 'action', 'entityname', 'title', 'chip']) {
          if (matches(node, sel(kind))) kinds.push(kind);
        }
        if (!invisible && ownText(node)) kinds.push('text');
        if (kinds.length) {
          const record = {
            sel: selectorOf(node), path, kinds, shown: !invisible && !clipped,
            decorative: Boolean(node.getAttribute && node.getAttribute('aria-hidden') === 'true'),
            // The rectangle as it is DRAWN: what the element asked for, narrowed by every
            // scroller above it. A card scrolled half out of the deck is half a card here.
            rect: {
              left: box.left, top: box.top, right: box.right, bottom: box.bottom,
              width: Math.max(0, box.right - box.left), height: Math.max(0, box.bottom - box.top),
            },
            // And what it asked for, kept beside it: `folded_action` is about the layout
            // squeezing a control, not about the owner having scrolled past it.
            asked: { width: rect.width, height: rect.height },
            covered_by: '',
            // Whether it is painted against the screen rather than in flow: "floating", for
            // §9's floating-controls-dock pair and for the keyboard rule.
            floating: pinned || style.position === 'sticky',
            invisible,
            // How much of it the viewport and its clipping ancestors take away, per axis, and
            // whether anything can scroll to give it back. `control_clipped_by_container`.
            clip_x: Math.max(0, here.left - own.left) + Math.max(0, own.right - here.right),
            clip_y: Math.max(0, here.top - own.top) + Math.max(0, own.bottom - here.bottom),
            scrollable_x: Boolean(reveals && reveals.x),
            scrollable_y: Boolean(reveals && reveals.y),
          };
          out.push(record);
          seen.push(node);
        }
        // A scroller narrows everything inside it. Per axis, because `overflow-x:auto` on a
        // table wrapper says nothing about its height.
        const ox = style.overflowX || style.overflow || 'visible';
        const oy = style.overflowY || style.overflow || 'visible';
        if (ox !== 'visible' || oy !== 'visible') {
          here = {
            left: ox === 'visible' ? here.left : Math.max(here.left, own.left),
            right: ox === 'visible' ? here.right : Math.min(here.right, own.right),
            top: oy === 'visible' ? here.top : Math.max(here.top, own.top),
            bottom: oy === 'visible' ? here.bottom : Math.min(here.bottom, own.bottom),
          };
          // And whether what it clips away can be scrolled back into view. `auto` and `scroll`
          // can; `hidden` and `clip` cannot, and that is the difference between a deck the
          // owner scrolls and a strip that has simply lost its last chip. No scrollWidth
          // comparison: a box only clips at all when its contents exceed it, so asking again
          // whether they exceed it adds nothing — and scrollWidth is the one thing a DOM
          // stand-in cannot supply, which would make this rule untestable outside a browser.
          const reveal = (o) => o === 'auto' || o === 'scroll' || o === 'overlay';
          if (reveal(ox) || reveal(oy)) {
            reveals = {
              x: Boolean((reveals && reveals.x) || reveal(ox)),
              y: Boolean((reveals && reveals.y) || reveal(oy)),
            };
          }
        }
      }
      const kids = node.children || [];
      for (let i = 0; i < kids.length; i++) walk(kids[i], `${path}/${i}`, here, reveals, invisible);
    };
    // The document itself is the outermost scroller. `body{overflow:hidden}` on this page
    // means it is usually neither, which is precisely why a clipped control is unreachable.
    // The seed: can the SCREEN EDGE be scrolled away from? On this page, no — the shell is
    // `overflow:hidden` on html, body and `.app` by design, so anything past the edge of the
    // glass is gone. On an ordinary scrolling page it can, and this says so rather than
    // reporting every control below the fold.
    const canScrollAway = (node) => {
      const style = styles(node) || {};
      const ox = style.overflowX || style.overflow || 'visible';
      const oy = style.overflowY || style.overflow || 'visible';
      const reveal = (o) => o === 'auto' || o === 'scroll' || o === 'overlay' || o === 'visible';
      return { x: reveal(ox), y: reveal(oy) };
    };
    const atHtml = canScrollAway(doc.documentElement || scope);
    const atBody = canScrollAway(scope);
    walk(scope, '', screen, { x: atHtml.x && atBody.x, y: atHtml.y && atBody.y }, false);

    // The occlusion pass, which is the only honest way to ask "can he see it": take the
    // centre of each essential element and ask the browser what is on top there. Anything
    // that is neither the element nor part of it means something is over it.
    //
    // Every essential element, and — since §9 — every CONTROL as well. The Split chip is not
    // "essential content"; it is a button, drawn perfectly, that the browser hands to the
    // microphone. Only a hit test can say so, and `content_under_chrome` still reads only the
    // essential ones so the number the telemetry has been recording does not move.
    if (typeof doc.elementFromPoint === 'function' && view.w) {
      for (let i = 0; i < out.length; i++) {
        const record = out[i];
        const asks = record.kinds.indexOf('essential') !== -1 || record.kinds.indexOf('control') !== -1;
        if (!asks || !drawn(record)) continue;
        const x = Math.round(record.rect.left + record.rect.width / 2);
        const y = Math.round(record.rect.top + record.rect.height / 2);
        if (x < 1 || y < 1 || x > view.w - 1 || y > view.h - 1) continue;
        let top = null;
        try { top = doc.elementFromPoint(x, y); } catch { top = null; }
        if (!top) continue;
        const mine = seen[i];
        if (top === mine || (mine.contains && mine.contains(top)) || (top.contains && top.contains(mine))) continue;
        record.covered_by = selectorOf(top);
      }
    }
    return out;
  }

  /* One reading of the screen: the records, the rules, the thumb sizes and the viewport. */
  function scan(opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc) return { total: 0, counts: {}, hits: [], touch: [], records: 0, interactive: 0, interactive_hits: [], pairs: {} };
    const win = options.window || root;
    const viewport = options.viewport || {
      w: (win && win.innerWidth) || 0,
      h: (win && win.innerHeight) || 0,
    };
    const html = doc.documentElement || {};
    const records = collect(doc, { root: options.root, viewport, styleOf: options.styleOf });
    const result = check(records, {
      viewport,
      // The caller says whether the keyboard is up. Nothing here can tell: the tablet's
      // `interactive-widget=resizes-content` makes it look exactly like a short screen.
      keyboard: Boolean(options.keyboard),
      document: {
        scroll_width: html.scrollWidth || 0,
        client_width: html.clientWidth || (win && win.innerWidth) || 0,
        scroll_height: html.scrollHeight || 0,
        client_height: html.clientHeight || (win && win.innerHeight) || 0,
      },
    });
    result.touch = touch(records, { viewport, floor: options.touchFloor });
    result.records = records.length;
    result.viewport = viewport;
    return result;
  }

  const api = { RULES, PAIRS, NOT_A_COLLISION, SEL, TOL, SLIVER, TOUCH, check, touch, collect, scan, overlap, contains, intersect };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.CrooksCollide = api;
})(typeof window !== 'undefined' ? window : globalThis);
