/* The geometry rules (web/collide.js), under Node.
 *
 * `check(records)` is arithmetic over plain rectangles, so every rule can be stated as a
 * picture of a screen and asserted without a browser. What is checked here is the rules
 * themselves: that they fire on the shapes the live session produced, and — just as
 * important — that they do NOT fire on the shapes that are correct, because a collision
 * report full of false positives is worth exactly as much as `clipped=0`.
 *
 * The browser half is scripts/browser/collision.js, which measures the real page at
 * 601 × 889 and 800 × 1280. This file is the arithmetic underneath it.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const C = require(path.join(__dirname, '..', '..', 'web', 'collide.js'));

const VIEW = { w: 601, h: 889 };

// A record, as `collect` builds them: a selector, a path in the tree, what kinds it is, and
// a rectangle. `at(x, y, w, h)` is the rectangle in the form a person can read.
function rec(sel, path, kinds, x, y, w, h, extra) {
  return Object.assign({
    sel, path, kinds, shown: true, decorative: false,
    rect: { left: x, top: y, right: x + w, bottom: y + h, width: w, height: h },
    asked: { width: w, height: h },
    covered_by: '',
  }, extra || {});
}

const fired = (result, rule) => result.counts[rule] || 0;

test('two controls in the same place is a collision; one inside the other is not', () => {
  const apart = C.check([
    rec('button.a', '/0/0', ['control'], 10, 100, 120, 48),
    rec('button.b', '/0/1', ['control'], 150, 100, 120, 48),
  ], { viewport: VIEW });
  assert.equal(fired(apart, 'control_over_control'), 0, 'two controls side by side');

  const over = C.check([
    rec('button.a', '/0/0', ['control'], 10, 100, 120, 48),
    rec('button.b', '/0/1', ['control'], 100, 120, 120, 48),
  ], { viewport: VIEW });
  assert.equal(fired(over, 'control_over_control'), 1);
  assert.equal(over.hits[0].a, 'button.a');
  assert.equal(over.hits[0].b, 'button.b');
  assert.deepEqual([over.hits[0].w, over.hits[0].h], [30, 28]);
  assert.ok(/10,100 120x48/.test(over.hits[0].at), `the hit carries the boxes: ${over.hits[0].at}`);

  // A stepper's buttons live inside the stepper, and an action surface contains its own
  // handle. Nesting is how a control is built, not a fault.
  const nested = C.check([
    rec('div.action-surface', '/0/0', ['control'], 10, 100, 400, 64),
    rec('div.action-handle', '/0/0/1', ['control'], 16, 106, 56, 52),
  ], { viewport: VIEW });
  assert.equal(fired(nested, 'control_over_control'), 0, 'a control inside a control');
});

test('a one-pixel touch of two boxes is not a collision, and three pixels is', () => {
  const kiss = C.check([
    rec('button.a', '/0/0', ['control'], 0, 0, 100, 44),
    rec('button.b', '/0/1', ['control'], 99, 43, 100, 44),
  ], { viewport: VIEW });
  assert.equal(fired(kiss, 'control_over_control'), 0, 'boxes that share an edge');
  const real = C.check([
    rec('button.a', '/0/0', ['control'], 0, 0, 100, 44),
    rec('button.b', '/0/1', ['control'], 96, 40, 100, 44),
  ], { viewport: VIEW });
  assert.equal(fired(real, 'control_over_control'), 1);
});

test('words printed across a control fire; a control\'s own label does not', () => {
  const label = C.check([
    rec('button.chip', '/0/0', ['control'], 10, 10, 120, 44),
    rec('span.chip-label', '/0/0/0', ['text'], 20, 22, 100, 20),
  ], { viewport: VIEW });
  assert.equal(fired(label, 'text_over_control'), 0, 'the label inside its own button');

  const across = C.check([
    rec('button.chip', '/0/0', ['control'], 10, 10, 120, 44),
    rec('p.card-sub', '/0/1', ['text'], 40, 30, 300, 20),
  ], { viewport: VIEW });
  assert.equal(fired(across, 'text_over_control'), 1);
});

test('the floating bubble the live session used is a collision, wherever it floats', () => {
  // 11 September, 00:24:53: "Merged. 2 changes still waiting over there." — a fixed bubble
  // 120px up from the bottom of a 889px screen, and the dock band underneath it. This is the
  // shape that rule exists for, and it fires whether the bubble is over the dock, over the
  // halves or over the orb.
  const dock = rec('button.dock-btn', '/9/0', ['chrome'], 57, 777, 64, 56);
  const halves = rec('button.branch-chip', '/2/3', ['chrome'], 120, 720, 160, 44);
  const orb = rec('div#orb-frame.orb-frame', '/1/0', ['chrome'], 130, 90, 340, 340);

  const bubble = rec('p#toast.toast', '/3', ['notification', 'text'], 40, 745, 520, 44);
  const over = C.check([dock, halves, orb, bubble], { viewport: VIEW });
  assert.equal(fired(over, 'notification_over_chrome'), 2, 'the dock and the halves, both');

  const onOrb = C.check([dock, halves, orb, rec('p#toast.toast', '/3', ['notification'], 40, 200, 520, 44)], { viewport: VIEW });
  assert.equal(fired(onOrb, 'notification_over_chrome'), 1, 'over the orb');

  // In flow above the deck — the three classes of web/notify.js — it touches none of them.
  const inFlow = C.check([dock, halves, orb, rec('p.note', '/2/4', ['notification'], 14, 470, 573, 44)], { viewport: VIEW });
  assert.equal(fired(inFlow, 'notification_over_chrome'), 0);
});

test('a message drawn inside the composer belongs to it and is not a collision', () => {
  const field = rec('input.field-input', '/2/5/0/1', ['chrome', 'control', 'essential'], 33, 300, 535, 48);
  const onIt = rec('p.note', '/2/5/0/1/0', ['notification'], 35, 306, 400, 40);
  assert.equal(fired(C.check([field, onIt], { viewport: VIEW }), 'notification_over_chrome'), 0);
});

test('an action rail over content fires; a rail below its content does not', () => {
  const rail = rec('div.rail', '/2/0/3', ['rail'], 33, 400, 535, 60);
  const below = rec('p.card-body', '/2/0/2', ['text'], 33, 320, 535, 60);
  assert.equal(fired(C.check([rail, below], { viewport: VIEW }), 'rail_over_content'), 0);
  const under = rec('p.card-body', '/2/0/2', ['text'], 33, 430, 535, 60);
  assert.equal(fired(C.check([rail, under], { viewport: VIEW }), 'rail_over_content'), 1);
});

test('a page that scrolls sideways is reported with the numbers', () => {
  const ok = C.check([], { viewport: VIEW, document: { scroll_width: 601, client_width: 601 } });
  assert.equal(fired(ok, 'document_overflow_x'), 0);
  const bad = C.check([], { viewport: VIEW, document: { scroll_width: 742, client_width: 601 } });
  assert.equal(fired(bad, 'document_overflow_x'), 1);
  assert.equal(bad.hits[0].note, '742 > 601');
});

test('a control folded away to nothing is reported, and a scrolled-off one is not', () => {
  const zero = C.check([rec('button.action', '/2/0/4', ['control'], 33, 300, 0, 44)], { viewport: VIEW });
  assert.equal(fired(zero, 'folded_action'), 1);
  assert.equal(zero.hits[0].note, 'zero size');

  const sliver = C.check([rec('button.action', '/2/0/4', ['control'], 33, 300, 4, 44)], { viewport: VIEW });
  assert.equal(fired(sliver, 'folded_action'), 1);
  assert.equal(sliver.hits[0].note, '4×44');

  // Half out of the deck: the box the layout gave it is fine, and the owner has simply not
  // scrolled to it. `asked` is what the rule reads, which is why it stays quiet.
  const scrolled = rec('button.action', '/2/0/4', ['control'], 33, 336, 200, 6, { asked: { width: 200, height: 48 } });
  assert.equal(fired(C.check([scrolled], { viewport: VIEW }), 'folded_action'), 0);
});

test('something the browser found another element on top of is reported', () => {
  const buried = rec('h2.card-title', '/2/0/0/0/1', ['essential', 'text'], 33, 800, 400, 30, { covered_by: 'button#talk.talk' });
  const result = C.check([buried], { viewport: VIEW });
  assert.equal(fired(result, 'content_under_chrome'), 1);
  assert.equal(result.hits[0].note, 'button#talk.talk');
});

test('nothing off screen or hidden is measured at all', () => {
  const off = C.check([
    rec('button.a', '/0/0', ['control'], -400, 100, 120, 48),
    rec('button.b', '/0/1', ['control'], -380, 110, 120, 48),
  ], { viewport: VIEW });
  assert.equal(off.total, 0, 'two controls that collide off the left of the screen');

  const hidden = C.check([
    rec('button.a', '/0/0', ['control'], 10, 100, 120, 48, { shown: false }),
    rec('button.b', '/0/1', ['control'], 20, 110, 120, 48, { shown: false }),
  ], { viewport: VIEW });
  assert.equal(hidden.total, 0);
});

test('every rule that fired keeps an example, however long the tail', () => {
  const many = [];
  for (let i = 0; i < 40; i++) many.push(rec(`button.n${i}`, `/0/${i}`, ['control'], 10, 100, 200, 48));
  many.push(rec('p.late', '/9', ['text'], 10, 100, 200, 48));
  const result = C.check(many, { viewport: VIEW, document: { scroll_width: 900, client_width: 601 } });
  assert.ok(result.total > 24, `a screen this bad has many hits: ${result.total}`);
  assert.ok(result.hits.length <= 24, 'and the report is bounded');
  for (const rule of ['control_over_control', 'text_over_control', 'document_overflow_x']) {
    assert.ok(result.hits.some((h) => h.rule === rule), `${rule} kept an example`);
  }
});

test('the thumb floor is measured on the box the layout gave, not on what is scrolled into view', () => {
  const small = C.touch([
    rec('button.row-btn', '/2/0/1', ['control'], 400, 200, 61, 34),
    rec('button.chip', '/2/1/0', ['control'], 14, 60, 120, 44),
    rec('span.badge', '/2/0/2', ['control'], 14, 20, 80, 26, { decorative: true }),
  ], { viewport: VIEW });
  assert.deepEqual(small, [{ sel: 'button.row-btn', w: 61, h: 34 }]);
  const halfScrolled = C.touch([
    rec('button.chip', '/2/1/0', ['control'], 14, 880, 120, 9, { asked: { width: 120, height: 44 } }),
  ], { viewport: VIEW });
  assert.deepEqual(halfScrolled, [], 'a control half out of the deck is not a small control');
});

// --------------------------------------------------------------------- the collector

/* A document just real enough to walk: tags, classes, children, rectangles and a computed
   style handed in. What is being tested is the clip — the reason the first run of the
   collision suite reported every tall card as colliding with the dock, when the card was
   simply scrolled and the part in the dock band was not drawn at all. */
function node(tag, cls, box, style, kids) {
  const el = {
    nodeType: 1, tagName: tag, className: cls || '', id: '', hidden: false,
    children: kids || [], childNodes: kids || [],
    _style: Object.assign({ display: 'block', position: 'static', overflowX: 'visible', overflowY: 'visible' }, style || {}),
    getBoundingClientRect: () => ({ left: box[0], top: box[1], width: box[2], height: box[3], right: box[0] + box[2], bottom: box[1] + box[3] }),
    getAttribute: () => null,
    matches(selector) {
      const wanted = String(selector).split(',').map((x) => x.trim());
      const classes = String(this.className).split(/\s+/).filter(Boolean);
      return wanted.some((w) => {
        // `button:not(#talk)` is in the real selector list, so the stand-in understands it.
        const not = w.match(/^(.*):not\(#([\w-]+)\)$/);
        if (not) return this.matches(not[1]) && this.id !== not[2];
        if (w.charAt(0) === '.') return classes.indexOf(w.slice(1)) !== -1;
        if (w.charAt(0) === '#') return this.id === w.slice(1);
        if (/^[a-z]+$/i.test(w)) return w.toLowerCase() === String(this.tagName).toLowerCase();
        return false;   // attribute selectors: not what this stand-in is for
      });
    },
    contains(other) { return other === this; },
  };
  return el;
}

test('a card scrolled past the bottom of the deck is measured as the part that is drawn', () => {
  // The deck is 174..342 and clips; the card inside it runs 161..804, which is a real
  // rectangle and mostly not on the screen. The dock band is 342..418.
  const button = node('BUTTON', 'action-surface', [33, 500, 535, 48]);
  const card = node('ARTICLE', 'card', [33, 161, 535, 643], { overflowX: 'hidden', overflowY: 'hidden' }, [button]);
  const cards = node('DIV', 'cards', [14, 174, 573, 168], { overflowX: 'auto', overflowY: 'auto', position: 'relative' }, [card]);
  const dockBtn = node('BUTTON', 'dock-btn', [57, 356, 64, 48]);
  const dock = node('NAV', 'dock', [0, 342, 601, 76], { position: 'fixed' }, [dockBtn]);
  const body = node('BODY', '', [0, 0, 601, 418], { overflowX: 'hidden', overflowY: 'hidden' }, [cards, dock]);

  const records = C.collect({ body }, { root: body, viewport: { w: 601, h: 418 }, styleOf: (n) => n._style });
  const surface = records.find((r) => r.sel === 'button.action-surface');
  assert.ok(surface, 'the surface was collected');
  assert.equal(surface.shown, false, 'and it is not drawn at all: the deck clipped it away');
  assert.deepEqual(surface.asked, { width: 535, height: 48 }, 'its own box is still recorded');

  // The dock is fixed, so the deck's clip does not apply to it: its rectangle is its own.
  const chrome = records.find((r) => r.sel === 'button.dock-btn');
  assert.ok(chrome && chrome.shown);
  assert.deepEqual([chrome.rect.top, chrome.rect.bottom], [356, 404]);

  const result = C.check(records, { viewport: { w: 601, h: 418 } });
  assert.equal(result.total, 0, 'a card scrolled under the dock is not a collision');
});

test('a control the deck really does draw in the dock band is a collision', () => {
  // The same screen, with the deck reaching the bottom of the page the way it did before the
  // section 9 pass: the surface is drawn in the dock's band, and a tap there never reaches it.
  const button = node('BUTTON', 'action-surface', [33, 350, 535, 48]);
  const card = node('ARTICLE', 'card', [33, 161, 535, 643], { overflowX: 'hidden', overflowY: 'hidden' }, [button]);
  const cards = node('DIV', 'cards', [14, 174, 573, 244], { overflowX: 'auto', overflowY: 'auto', position: 'relative' }, [card]);
  const dockBtn = node('BUTTON', 'dock-btn', [57, 356, 64, 48]);
  const dock = node('NAV', 'dock', [0, 342, 601, 76], { position: 'fixed' }, [dockBtn]);
  const body = node('BODY', '', [0, 0, 601, 418], { overflowX: 'hidden', overflowY: 'hidden' }, [cards, dock]);

  const records = C.collect({ body }, { root: body, viewport: { w: 601, h: 418 }, styleOf: (n) => n._style });
  const result = C.check(records, { viewport: { w: 601, h: 418 } });
  // §9 asks for "button-navigation" as a verdict of its own, and a dock button IS the
  // navigation: the hit is classified by the most specific pair that describes it, and
  // counted exactly once so `total` stays the number the telemetry has been recording.
  assert.equal(fired(result, 'button_over_navigation'), 1, JSON.stringify(result.hits));
  assert.equal(fired(result, 'control_over_control'), 0, 'and not counted twice');
  assert.equal(result.total, 1);
  assert.equal(result.pairs['button-navigation'], 1);
  assert.equal(result.hits[0].b, 'button.dock-btn');
  assert.equal(result.interactive, 1, 'and it is an interactive collision, which §9 fails on');
});

test('a control that cannot be touched is not counted as one', () => {
  const ghost = node('BUTTON', 'talk', [0, 342, 601, 76], { position: 'fixed', pointerEvents: 'none' });
  const dockBtn = node('BUTTON', 'dock-btn', [57, 356, 64, 48]);
  const body = node('BODY', '', [0, 0, 601, 418], {}, [ghost, dockBtn]);
  const records = C.collect({ body }, { root: body, viewport: { w: 601, h: 418 }, styleOf: (n) => n._style });
  const result = C.check(records, { viewport: { w: 601, h: 418 } });
  assert.equal(fired(result, 'control_over_control'), 0);
});

test('scan says nothing rather than throwing when there is no document to read', () => {
  const empty = C.scan({ document: null });
  assert.equal(empty.total, 0);
  assert.deepEqual(empty.hits, []);
});

/* ---- Phase 5 §9: the fourteen named pairs, and the hard verdict ------------------------- */

test('every pair §9 names by hand has a rule behind it', () => {
  const REQUIRED = ['button-button', 'button-text', 'button-input', 'button-navigation',
    'Split-voice', 'branch-voice', 'toast-navigation', 'toast-orb', 'toast-approval',
    'floating-controls-dock', 'tabs-content', 'long-name-action', 'chips-title', 'keyboard-action'];
  for (const label of REQUIRED) {
    assert.ok(C.PAIRS[label], `§9 requires a verdict for ${label}`);
    for (const rule of C.PAIRS[label]) {
      assert.ok(C.RULES.indexOf(rule) !== -1, `${label} names an unknown rule ${rule}`);
    }
  }
  // And a clean screen answers every one of them with a zero rather than with silence.
  const clean = C.check([rec('button.a', '/0/0', ['control'], 10, 100, 120, 48)], { viewport: VIEW });
  for (const label of REQUIRED) assert.equal(clean.pairs[label], 0, label);
  assert.equal(clean.interactive, 0);
});

test('D-1: the Split chip under the voice target, by geometry and by hit test', () => {
  // The live tree. `#talk` is `inset:0` in orb mode; the chip is drawn inside `.orb-zone`,
  // which caps it. Geometry alone sees it...
  const painted = C.check([
    rec('button#talk.talk', '/0/0', ['chrome', 'voice'], 0, 62, 601, 525),
    rec('button.branch-act', '/0/1/3', ['control', 'split', 'branch'], 271, 465, 58, 44),
  ], { viewport: VIEW });
  assert.equal(fired(painted, 'split_under_voice'), 1, JSON.stringify(painted.hits));
  assert.equal(painted.pairs['Split-voice'], 1);
  assert.equal(painted.interactive, 1, '§9 fails the release on this');

  // ...and the hit test sees it even when the rectangles are nowhere near each other, which
  // is the case that matters: a transparent parent can own the touch without covering the box.
  const tested = C.check([
    rec('button.branch-act', '/0/1/3', ['control', 'split', 'branch'], 271, 465, 58, 44,
      { covered_by: 'span#talk-label.talk-label' }),
  ], { viewport: VIEW });
  assert.equal(fired(tested, 'split_under_voice'), 1, JSON.stringify(tested.hits));
  assert.match(tested.hits[0].note, /hit test/);

  // Merge and Close are the same defect under their own name, because the owner named them
  // separately: "I cannot click the merge or close button".
  const halves = C.check([
    rec('button#talk.talk', '/0/0', ['chrome', 'voice'], 0, 62, 601, 525),
    rec('button.branch-chip', '/0/1/1', ['control', 'branch'], 20, 465, 120, 44),
    rec('button.branch-act', '/0/1/2', ['control', 'branch'], 150, 465, 80, 44),
  ], { viewport: VIEW });
  assert.equal(fired(halves, 'branch_under_voice'), 2, JSON.stringify(halves.hits));
  assert.equal(halves.pairs['branch-voice'], 2);
});

test('a fixed voice target that does NOT reach the branch bar is not a collision', () => {
  // The shape workstream A is building: the hold band is a dock, not the whole screen.
  const fixed = C.check([
    rec('button#talk.talk', '/0/0', ['chrome', 'voice'], 0, 700, 601, 120),
    rec('button.branch-act', '/0/1/3', ['control', 'split', 'branch'], 271, 465, 58, 44),
  ], { viewport: VIEW });
  assert.equal(fired(fixed, 'split_under_voice'), 0);
  assert.equal(fixed.interactive, 0, 'and the release gate is clear');
});

test('a message over the navigation, the orb and an approval are three different faults', () => {
  const result = C.check([
    rec('div.toast', '/0/0', ['notification'], 0, 100, 601, 60),
    rec('nav#context-nav.context-nav', '/0/1', ['chrome', 'navigation'], 0, 110, 601, 48),
    rec('div#orb-frame.orb-frame', '/0/2', ['chrome', 'orb'], 130, 120, 340, 340),
    rec('button.action-surface', '/0/3', ['chrome', 'approval', 'control', 'action'], 33, 130, 535, 48),
  ], { viewport: VIEW });
  assert.equal(fired(result, 'toast_over_navigation'), 1, JSON.stringify(result.counts));
  assert.equal(fired(result, 'toast_over_orb'), 1);
  assert.equal(fired(result, 'toast_over_approval'), 1);
  assert.equal(fired(result, 'notification_over_chrome'), 0, 'each one named, none counted twice');
  assert.equal(result.pairs['toast-navigation'], 1);
  assert.equal(result.pairs['toast-orb'], 1);
  assert.equal(result.pairs['toast-approval'], 1);
});

test('a long name across an action, and chips across a title, are named separately', () => {
  const result = C.check([
    rec('p.card-sub', '/0/0/1', ['text', 'entityname'], 33, 200, 400, 22),
    rec('button.rail-chip', '/0/0/2', ['control', 'action'], 300, 205, 120, 44),
    rec('h2.card-title', '/0/1/1', ['text', 'title'], 33, 400, 300, 30),
    rec('span.badge', '/0/1/2', ['control', 'chip'], 250, 405, 80, 24),
  ], { viewport: VIEW });
  assert.equal(fired(result, 'name_over_action'), 1, JSON.stringify(result.counts));
  assert.equal(fired(result, 'chips_over_title'), 1);
  assert.equal(fired(result, 'text_over_control'), 0, 'neither falls back to the generic rule');
  assert.equal(result.pairs['long-name-action'], 1);
  assert.equal(result.pairs['chips-title'], 1);
  assert.equal(result.pairs['button-text'], 2, 'and "button-text" is their sum');
});

test('a control over a field, and a tab strip over its own panel', () => {
  const result = C.check([
    rec('button.compose-btn', '/0/0', ['control', 'action'], 33, 300, 200, 44),
    rec('textarea.field-input', '/0/1', ['control', 'input'], 33, 310, 535, 120),
    rec('div.tabs', '/0/2', ['control', 'tabstrip'], 33, 500, 535, 40),
    rec('div.stats', '/0/3', ['control', 'panel'], 33, 520, 535, 200),
  ], { viewport: VIEW });
  assert.equal(fired(result, 'button_over_input'), 1, JSON.stringify(result.counts));
  assert.equal(fired(result, 'tabs_over_content'), 1);
  assert.equal(result.pairs['button-input'], 1);
  assert.equal(result.pairs['tabs-content'], 1);
});

test('with the keyboard open, an action under the fixed furniture is its own verdict', () => {
  const records = [
    rec('button.compose-btn', '/0/0', ['control', 'action'], 33, 380, 200, 44),
    rec('nav#dock.dock', '/0/1', ['chrome', 'navigation', 'dock'], 0, 370, 601, 76, { floating: true }),
  ];
  const shut = C.check(records, { viewport: { w: 601, h: 418 } });
  const open = C.check(records, { viewport: { w: 601, h: 418 }, keyboard: true });
  assert.equal(fired(open, 'keyboard_over_action'), 1, JSON.stringify(open.counts));
  assert.equal(open.pairs['keyboard-action'], 1);
  assert.equal(fired(shut, 'keyboard_over_action'), 0, 'the same geometry with the keyboard down is a different question');
});

/* Split was deleted on the owner's ruling of 8 October (DEC-071, ruling 37). Nothing on the page
   draws its chips, Merge, Close or the Split control any more, so a selector that names only
   them measures nothing and says nothing about the screen. What stays, and why, is in
   web/collide.js beside the two groups. */
test('no selector group names a Split control nothing draws any more', () => {
  const RETIRED = ['.branch-split', '.chip-split', '.chip-branch-act'];
  for (const kind of Object.keys(C.SEL)) {
    for (const sel of C.SEL[kind]) assert.ok(!RETIRED.includes(sel), `${kind} still names ${sel}`);
  }
  for (const sel of ['.branch-chip', '.branch-act', '[data-action="split"]']) {
    assert.ok(!C.SEL.chrome.includes(sel), `chrome still names ${sel}`);
  }
  assert.ok(!C.SEL.branch.includes('.branch-act'), 'branch still names .branch-act');
  // The two §9 pair sides still stand on something: an empty group would match nothing and
  // its rule would always pass (tests/test_collision_gate.py).
  assert.deepEqual(C.SEL.split, ['[data-action="split"]']);
  assert.ok(C.SEL.branch.includes('.branch-chip') && C.SEL.branch.includes('#branch-bar'));
});

/* The rule the coordinator's eye found on the before-shots, which nothing above can see: no
   two rectangles intersect and the document does not scroll sideways, because the overflow is
   CLIPPED by a container. An interactive control hangs off the edge of the glass and every
   check is green. (docs/phase5/VISUAL_CRITIQUE_BEFORE.md) */
test('a branch chip cut off by the right edge of the navigation strip fails', () => {
  const chip = node('BUTTON', 'branch-chip', [470, 180, 170, 44]);
  const nav = node('NAV', 'context-nav', [14, 174, 573, 56], { overflowX: 'auto', overflowY: 'hidden' }, [chip]);
  const body = node('BODY', '', [0, 0, 601, 889], { overflowX: 'hidden', overflowY: 'hidden' }, [nav]);
  const records = C.collect({ body }, { root: body, viewport: VIEW, styleOf: (n) => n._style });
  const result = C.check(records, { viewport: VIEW });
  assert.equal(fired(result, 'control_clipped_by_container'), 1, JSON.stringify(result.hits));
  assert.match(result.hits[0].note, /off the side/);
  assert.equal(result.interactive, 1, '§9 fails the release on this, the same as an overlap');
  assert.equal(fired(result, 'document_overflow_x'), 0, 'and the old rule still cannot see it');
});

test('a card scrolled down a deck is not a clipped control, because the deck scrolls', () => {
  // The false positive this rule must never produce: scrolling IS the interaction.
  const button = node('BUTTON', 'rail-chip', [33, 900, 200, 44]);
  const card = node('ARTICLE', 'card', [33, 200, 535, 900], { overflowX: 'hidden', overflowY: 'hidden' }, [button]);
  const cards = node('DIV', 'cards', [14, 174, 573, 500], { overflowX: 'hidden', overflowY: 'auto', position: 'relative' }, [card]);
  const body = node('BODY', '', [0, 0, 601, 889], { overflowX: 'hidden', overflowY: 'hidden' }, [cards]);
  const records = C.collect({ body }, { root: body, viewport: VIEW, styleOf: (n) => n._style });
  const result = C.check(records, { viewport: VIEW });
  assert.equal(fired(result, 'control_clipped_by_container'), 0, JSON.stringify(result.hits));
});

test('and a control trapped behind overflow:hidden is reported even though it is not furniture', () => {
  const button = node('BUTTON', 'rail-chip', [400, 300, 300, 44]);
  const card = node('ARTICLE', 'card', [33, 200, 400, 400], { overflowX: 'hidden', overflowY: 'hidden' }, [button]);
  const body = node('BODY', '', [0, 0, 601, 889], { overflowX: 'hidden', overflowY: 'hidden' }, [card]);
  const records = C.collect({ body }, { root: body, viewport: VIEW, styleOf: (n) => n._style });
  const result = C.check(records, { viewport: VIEW });
  assert.equal(fired(result, 'control_clipped_by_container'), 1, JSON.stringify(result.hits));
  assert.match(result.hits[0].note, /nothing scrolls on that axis/);
});

test('§31: tight is not broken — two controls six pixels apart are not a collision', () => {
  // The coordinator's other note. A chevron beside a badge, not touching it, is a judgement
  // about crowding and not a §9 fault, and a proximity rule here would fail every real screen.
  const result = C.check([
    rec('span.row-go', '/0/0', ['text'], 560, 300, 12, 20),
    rec('span.badge', '/0/1', ['control', 'chip'], 490, 300, 64, 20),
  ], { viewport: VIEW });
  assert.equal(result.total, 0, JSON.stringify(result.hits));
  assert.equal(result.interactive, 0);
});

/* The false positive that the A/G merge produced, and the reason it is a rule and not a
   fixture tweak. In context mode the footer is
   `body[data-mode="context"] .bottom{opacity:0;height:0;overflow:hidden}` — it is folded
   away, on purpose, with the dock taking its place. `#recent` inside it still ASKS for
   48 px, and `opacity` does not inherit as a computed value, so the walker saw a fully
   visible navigation control squeezed to nothing and reported
   `control_clipped_by_container: 48px off the top or bottom — fixed furniture must fit the
   screen`. Nothing inside a zero-opacity ancestor is on the glass. */
test('a control inside a faded-away ancestor is not on the glass, and is not a squeezed control', () => {
  const recent = node('BUTTON', 'recent', [0, 789, 601, 0]);
  recent.id = 'recent';
  // The real rule: the footer asks for nothing and hides what overflows. Its child asks for 48.
  recent.getBoundingClientRect = () => ({ left: 0, top: 789, width: 601, height: 48, right: 601, bottom: 837 });
  const footer = node('FOOTER', 'bottom', [0, 789, 601, 0],
    { opacity: '0', overflowX: 'hidden', overflowY: 'hidden' }, [recent]);
  const body = node('BODY', '', [0, 0, 601, 889], { overflowX: 'hidden', overflowY: 'hidden' }, [footer]);

  const records = C.collect({ body }, { root: body, viewport: VIEW, styleOf: (n) => n._style });
  const row = records.find((r) => r.sel === 'button#recent.recent');
  assert.ok(row, 'the control is still collected — it exists, it is simply not shown');
  assert.equal(row.invisible, true, 'its ancestor faded it out, so it is invisible too');
  assert.equal(row.shown, false);
  assert.equal(row.kinds.indexOf('control'), -1,
    'and it is not a control: a control nobody can see is not a control this gate measures');

  const result = C.check(records, { viewport: VIEW });
  assert.equal(fired(result, 'control_clipped_by_container'), 0,
    'the folded footer is the design, not a navigation strip that does not fit');
  assert.equal(result.interactive, 0, 'and nothing interactive is involved, so §9 stays zero');
});

/* The same shape with the footer OPEN, so the rule above cannot be passing by simply never
   firing. This is the genuine defect it must still catch: a navigation control the layout
   has cut in half while the owner can see it. */
test('and the same control, with its ancestor visible, is still reported when the layout cuts it', () => {
  const recent = node('BUTTON', 'recent', [0, 0, 0, 0]);
  recent.id = 'recent';
  recent.getBoundingClientRect = () => ({ left: 0, top: 860, width: 601, height: 48, right: 601, bottom: 908 });
  const footer = node('FOOTER', 'bottom', [0, 860, 601, 24],
    { opacity: '1', overflowX: 'hidden', overflowY: 'hidden' }, [recent]);
  const body = node('BODY', '', [0, 0, 601, 889], { overflowX: 'hidden', overflowY: 'hidden' }, [footer]);

  const records = C.collect({ body }, { root: body, viewport: VIEW, styleOf: (n) => n._style });
  const row = records.find((r) => r.sel === 'button#recent.recent');
  assert.equal(row.invisible, false);
  assert.ok(row.kinds.indexOf('control') !== -1, 'visible, so it is a control');

  const result = C.check(records, { viewport: VIEW });
  assert.equal(fired(result, 'control_clipped_by_container'), 1,
    'a visible navigation control with 24 of its 48 pixels taken away is the real fault');
});
