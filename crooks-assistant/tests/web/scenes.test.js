/* The scene renderer (web/scenes.js) and its gallery (web/scene-fixtures.js), under Node.
 *
 * Every primitive renders; every string arrives as text, never markup; an element's
 * justification is never drawn; row limits and drill-downs hold; and a control dispatches its
 * event and does nothing else. The gallery's cases are rendered here too, so the page the
 * owner opens on his phone is the one these tests drew.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const shim = require('./dom-shim.js');
globalThis.document = shim.document;

// The shim records listeners but has no dispatchEvent: here an event bubbles up through
// parentNode to every listener for its type, as it does in the DOM.
shim.Element.prototype.dispatchEvent = function dispatchEvent(event) {
  for (let node = this; node; node = node.parentNode) {
    for (const fn of (node.listeners && node.listeners[event.type]) || []) fn(event);
    if (!event.bubbles) break;
  }
  return true;
};
if (typeof globalThis.CustomEvent !== 'function') {
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, init) { this.type = type; this.detail = (init || {}).detail; this.bubbles = Boolean((init || {}).bubbles); }
  };
}

const WEB = path.join(__dirname, '..', '..', 'web');
const Scenes = require(path.join(WEB, 'scenes.js'));
const Fixtures = require(path.join(WEB, 'scene-fixtures.js'));

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>&lt;b&gt;';
const SVG_NS = 'http://www.w3.org/2000/svg';

function host() { return shim.document.createElement('div'); }

// What a person sees: text in nodes that are not hidden.
function visibleText(node) {
  if (node.nodeType === 3) return node.data;
  if (node.hidden) return '';
  return node.childNodes.map(visibleText).join('');
}

function visible(nodes) { return nodes.filter((n) => { for (let p = n; p; p = p.parentNode) if (p.hidden) return false; return true; }); }

function walk(node, fn) {
  fn(node);
  for (const child of node.childNodes || []) if (child.nodeType === 1) walk(child, fn);
}

function heard(target, type) {
  const events = [];
  target.addEventListener(type, (event) => events.push(event));
  return events;
}

function rows(n, h) {
  return Array.from({ length: n }, (_, i) => ({ record: `r${i + 1}`, cells: [`Customer ${i}${h}`, String(i + 1)] }));
}

function everything(h) {
  h = h || '';
  return {
    answer: { id: 'answer', type: 'answer', text: `3 customers are waiting on a reply.${h}`, justification: `JUSTIFY answer${h}` },
    elements: [
      { id: 'e1', type: 'finding', justification: `JUSTIFY e1${h}`, significance: 'ACTION_REQUIRED', text: `They need a reply.${h}`,
        values: [{ label: `Waiting${h}`, text: `3${h}` }],
        sources: [{ evidence: 'ev-mail', label: `Who has emailed${h}`, found_text: `25 found${h}`, checked: `just now${h}` }] },
      { id: 'e2', type: 'entity', justification: `JUSTIFY e2${h}`, caption: `Order${h}`, fields: [{ label: `Total${h}`, text: `£86.00${h}` }] },
      { id: 'e3', type: 'collection', justification: `JUSTIFY e3${h}`, caption: `Who has emailed${h}`, evidence: 'ev-mail',
        columns: [{ field: 'customer_name', label: `Customer${h}`, numeric: false }, { field: 'threads', label: 'Threads', numeric: true }],
        rows: rows(12, h), limit: 8, total: 12 },
      { id: 'e4', type: 'measure', justification: `JUSTIFY e4${h}`, label: `To ship${h}`, value: `£1,234.50${h}`, unit: `orders${h}`, period: `last 7 days${h}` },
      { id: 'e5', type: 'comparison', justification: `JUSTIFY e5${h}`, label: `Sales${h}`,
        current: { label: 'Sales', text: `£3,100.00${h}` }, previous: { label: `Sales before${h}`, text: '£2,800.00' },
        direction: 'up', difference: `Up £300.00 (11%)${h}` },
      { id: 'e6', type: 'trend', justification: `JUSTIFY e6${h}`, label: `Daily spend${h}`, values: [1, 3, 2, 5], latest: `£5.00${h}`, from: `Friday${h}`, to: 'today' },
      { id: 'e7', type: 'timeline', justification: `JUSTIFY e7${h}`, caption: `Email thread${h}`,
        rows: [{ record: 'r1', at: `yesterday at 4:05pm${h}`, at_iso: '2026-09-23T15:05:00+00:00', label: `Return request${h}` }] },
      { id: 'e8', type: 'proposal', justification: `JUSTIFY e8${h}`, action: 'act-1', text: `Draft the replies.${h}` },
      { id: 'e9', type: 'question', justification: `JUSTIFY e9${h}`, text: `Shall I draft them?${h}`, options: [`Yes${h}`, 'Not now'] },
    ],
    drilldown: null,
  };
}

const CHECKED = {
  id: 'drilldown',
  sources: [
    { evidence: 'ev-orders', label: 'Recent orders', found: 8, found_text: '8 found', checked: 'just now' },
    { evidence: 'ev-threads', label: 'Inbox', found: 7, found_text: '7 found', checked: 'just now' },
    { evidence: 'ev-customers', label: 'Who has emailed', found: 25, found_text: '25 found', checked: 'just now' },
  ],
};

// ------------------------------------------------------------------ every primitive

test('every primitive renders, in the order the scene gives', () => {
  assert.deepEqual(new Set(Scenes.TYPES), new Set(['finding', 'entity', 'collection', 'measure', 'comparison', 'trend', 'timeline', 'proposal', 'question']));
  const c = host();
  const out = Scenes.renderScene(everything(), c);
  assert.equal(c.childNodes.length, 1);
  assert.equal(c.childNodes[0], out);
  assert.equal(out.querySelector('.scene-answer').textContent, '3 customers are waiting on a reply.');
  const drawn = out.querySelectorAll('.scene-el');
  assert.deepEqual(drawn.map((n) => n.dataset.type), ['finding', 'entity', 'collection', 'measure', 'comparison', 'trend', 'timeline', 'proposal', 'question']);
  assert.deepEqual(drawn.map((n) => n.dataset.sceneId), ['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7', 'e8', 'e9']);
  const [finding, entity, collection, measure, comparison, trend, timeline, proposal, question] = drawn;

  assert.equal(finding.querySelector('.scene-sig').textContent, 'Needs you');
  assert.equal(finding.querySelector('.scene-finding-text').textContent, 'They need a reply.');
  assert.equal(entity.querySelector('.scene-caption').textContent, 'Order');
  assert.deepEqual(entity.querySelectorAll('dt').map((n) => n.textContent), ['Total']);
  assert.deepEqual(entity.querySelectorAll('dd').map((n) => n.textContent), ['£86.00']);
  assert.deepEqual(collection.querySelectorAll('th').map((n) => n.textContent), ['Customer', 'Threads']);
  assert.deepEqual(collection.querySelectorAll('th').map((n) => n.className), ['', 'scene-num']);
  assert.equal(measure.querySelector('.scene-big').textContent, '£1,234.50');
  assert.equal(measure.querySelector('.scene-unit').textContent, 'orders');
  assert.equal(measure.querySelector('.scene-period').textContent, 'last 7 days');
  assert.equal(comparison.querySelector('.scene-big').textContent, '£3,100.00');
  assert.equal(comparison.querySelector('.scene-diff').textContent, 'Up £300.00 (11%)');
  assert.equal(comparison.querySelector('.scene-diff').dataset.direction, 'up');
  assert.match(visibleText(comparison), /Sales before £2,800\.00/);
  const svg = trend.querySelector('svg');
  assert.ok(svg && svg.namespaceURI === SVG_NS, 'a trend is an inline SVG sparkline');
  assert.equal(svg.querySelector('polyline').getAttribute('points').split(' ').length, 4);
  assert.equal(trend.querySelector('.scene-big').textContent, '£5.00');
  assert.equal(trend.querySelector('.scene-period').textContent, 'Friday – today');
  const time = timeline.querySelector('time');
  assert.equal(time.textContent, 'yesterday at 4:05pm');
  assert.equal(time.getAttribute('datetime'), '2026-09-23T15:05:00+00:00');
  assert.equal(timeline.querySelector('.scene-what').textContent, 'Return request');
  assert.equal(proposal.querySelector('.scene-proposal-text').textContent, 'Draft the replies.');
  assert.equal(proposal.querySelector('button').textContent, 'Review');
  assert.deepEqual(question.querySelectorAll('.scene-chip').map((n) => n.textContent), ['Yes', 'Not now']);
  for (const b of out.querySelectorAll('button')) assert.equal(b.getAttribute('type'), 'button');
});

test('a finding says its significance in plain words, and the unknown is context', () => {
  const words = { ACTION_REQUIRED: 'Needs you', DECISION_REQUIRED: 'Decide', RISK: 'Risk', UNCERTAINTY: 'Unsure', LIMITATION: 'Limit', CONTEXT: 'Context', LOUD: 'Context' };
  for (const [code, word] of Object.entries(words)) {
    const out = Scenes.renderScene({ answer: { text: 'Fine.' }, elements: [{ id: 'e1', type: 'finding', significance: code, text: 'Something.' }] }, host());
    assert.equal(out.querySelector('.scene-sig').textContent, word, code);
    assert.equal(out.querySelector('.scene-finding').dataset.significance, code === 'LOUD' ? 'CONTEXT' : code);
  }
});

test('a trend with fewer than two points draws no line', () => {
  const out = Scenes.renderScene({ answer: { text: 'Fine.' }, elements: [{ id: 'e1', type: 'trend', label: 'Sales', values: [3, 'x', null], latest: '£3.00' }] }, host());
  assert.equal(out.querySelector('svg'), null);
  assert.equal(out.querySelector('.scene-big').textContent, '£3.00');
});

// ------------------------------------------------------------------ text only

test('every string is text, never markup, and the justification is never drawn', () => {
  const out = Scenes.renderScene(everything(HOSTILE), host());
  // Open everything that opens, so hidden text is checked too.
  for (const b of out.querySelectorAll('.scene-finding-head')) b.dispatch('click');
  const all = out.allText();
  assert.ok(all.split(HOSTILE).length - 1 >= 20, 'every hostile string is shown as the characters it is');
  assert.equal(out.querySelectorAll('img').length, 0);
  assert.equal(out.querySelectorAll('script').length, 0);
  assert.ok(!all.includes('JUSTIFY'), 'a justification is for the trace, not the screen');
  walk(out, (node) => {
    for (const v of Object.values(node.attributes)) assert.ok(!v.includes('JUSTIFY'), v);
    for (const v of Object.values(node.dataset)) assert.ok(!v.includes('JUSTIFY'), v);
  });
  const source = fs.readFileSync(path.join(WEB, 'scenes.js'), 'utf8');
  assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(source));
});

test('unknown and malformed elements draw nothing, and a malformed payload draws only an answer', () => {
  const out = Scenes.renderScene({
    answer: { text: 'Fine.' },
    elements: [{ type: 'hologram', html: '<b>x</b>' }, null, 42, 'finding', { type: 'answer', text: 'again' },
      { type: 'toString' }, { type: '__proto__' }, [1, 2]],
  }, host());
  assert.equal(out.querySelectorAll('.scene-el').length, 0);
  assert.equal(out.querySelector('.scene-elements'), null);
  assert.equal(visibleText(out), 'Fine.');
  for (const bad of [null, undefined, 42, 'scene', [], { answer: 'text' }]) {
    const drawn = Scenes.renderScene(bad, host());
    assert.equal(drawn.querySelectorAll('.scene-el').length, 0);
    assert.equal(drawn.querySelectorAll('.scene-answer').length, 1);
  }
});

test('a render replaces what the container held', () => {
  const c = host();
  Scenes.renderScene(everything(), c);
  Scenes.renderScene({ answer: { text: 'Nothing needs you right now.' } }, c);
  assert.equal(c.childNodes.length, 1);
  assert.equal(visibleText(c), 'Nothing needs you right now.');
});

// ------------------------------------------------------------------ rows and drill-downs

test('a collection shows its row limit, and "show all" opens the rest in place', () => {
  const c = host();
  const drill = heard(c, 'scene-drilldown');
  const out = Scenes.renderScene(everything(), c);
  const collection = out.querySelector('.scene-collection');
  assert.equal(collection.querySelectorAll('.scene-row').length, 12);
  assert.equal(visible(collection.querySelectorAll('.scene-row')).length, 8);
  const more = collection.querySelector('.scene-more');
  assert.equal(more.textContent, 'Show all 12');
  more.dispatch('click');
  assert.equal(visible(collection.querySelectorAll('.scene-row')).length, 12);
  assert.equal(more.hidden, true);
  assert.equal(drill.length, 0, 'everything was already in the scene');
});

test('past what the scene holds, "show all" is a drill-down it asks for and does not open itself', () => {
  const c = host();
  const drill = heard(c, 'scene-drilldown');
  const item = { id: 'e1', type: 'collection', evidence: 'ev-mail', columns: [{ label: 'Customer' }], rows: rows(8, ''), limit: 8, total: 25 };
  const out = Scenes.renderScene({ answer: { text: 'Fine.' }, elements: [item] }, c);
  const before = out.countNodes();
  assert.equal(visible(out.querySelectorAll('.scene-row')).length, 8);
  const more = out.querySelector('.scene-more');
  assert.equal(more.textContent, 'Show all 25');
  more.dispatch('click');
  assert.equal(drill.length, 1);
  assert.deepEqual(drill[0].detail, { id: 'e1', evidence: 'ev-mail' });
  assert.equal(out.countNodes(), before);
  assert.equal(visible(out.querySelectorAll('.scene-row')).length, 8);

  // Within its limit there is nothing to show all of.
  const small = Scenes.renderScene({ answer: { text: 'Fine.' }, elements: [{ ...item, rows: rows(5, ''), total: 5 }] }, host());
  assert.equal(small.querySelector('.scene-more'), null);
  // A limit the scene never gave is its rows, all of them.
  const unbounded = Scenes.renderScene({ answer: { text: 'Fine.' }, elements: [{ ...item, rows: rows(5, ''), limit: 'lots', total: 5 }] }, host());
  assert.equal(visible(unbounded.querySelectorAll('.scene-row')).length, 5);
});

test('when only the answer is shown, it is one line and a tap opens what was checked', () => {
  const out = Scenes.renderScene({ answer: { id: 'answer', text: 'Nobody is waiting on a reply.' }, elements: [], drilldown: CHECKED }, host());
  const answer = out.querySelector('.scene-answer');
  assert.equal(answer.tagName, 'BUTTON');
  assert.equal(answer.getAttribute('aria-expanded'), 'false');
  const panel = out.querySelector('.scene-drilldown');
  assert.equal(panel.hidden, true);
  assert.equal(visibleText(out), 'Nobody is waiting on a reply.');

  answer.dispatch('click');
  assert.equal(panel.hidden, false);
  assert.equal(answer.getAttribute('aria-expanded'), 'true');
  assert.equal(panel.querySelector('.scene-drilldown-line').textContent, 'Checked Recent orders, Inbox, Who has emailed');
  assert.deepEqual(panel.querySelectorAll('.scene-source').map((n) => n.textContent), [
    'Recent orders8 found · just now', 'Inbox7 found · just now', 'Who has emailed25 found · just now']);
  answer.dispatch('click');
  assert.equal(panel.hidden, true);

  // With nothing checked there is nothing to open: the answer is a plain line.
  const plain = Scenes.renderScene({ answer: { text: 'Nothing needs you right now.' }, drilldown: { sources: [] } }, host());
  assert.equal(plain.querySelector('.scene-answer').tagName, 'P');
  assert.equal(plain.querySelector('.scene-drilldown'), null);
});

test('a tap on a finding reveals its evidence', () => {
  const out = Scenes.renderScene(everything(), host());
  const finding = out.querySelector('.scene-finding');
  const head = finding.querySelector('.scene-finding-head');
  const evidence = finding.querySelector('.scene-evidence');
  assert.equal(evidence.hidden, true);
  assert.ok(!visibleText(finding).includes('Who has emailed'));
  head.dispatch('click');
  assert.equal(evidence.hidden, false);
  assert.equal(head.getAttribute('aria-expanded'), 'true');
  assert.match(visibleText(finding), /Waiting3/);
  assert.match(visibleText(finding), /Who has emailed25 found · just now/);
});

// ------------------------------------------------------------------ events, not actions

test('a proposal and a question dispatch their events and do nothing else', () => {
  const calls = [];
  const saved = globalThis.fetch;
  globalThis.fetch = (...args) => { calls.push(args); throw new Error('a scene control must not fetch'); };
  try {
    const c = host();
    const proposals = heard(c, 'scene-proposal');
    const answers = heard(c, 'scene-answer');
    const out = Scenes.renderScene(everything(), c);
    const before = out.countNodes();
    const text = out.allText();

    out.querySelector('.scene-proposal').querySelector('button').dispatch('click');
    assert.equal(proposals.length, 1);
    assert.equal(proposals[0].type, 'scene-proposal');
    assert.equal(proposals[0].bubbles, true);
    assert.deepEqual(proposals[0].detail, { id: 'e8', action: 'act-1' });

    const chips = out.querySelectorAll('.scene-chip');
    chips[1].dispatch('click');
    chips[0].dispatch('click');
    assert.deepEqual(answers.map((e) => e.detail), [{ id: 'e9', option: 'Not now', index: 1 }, { id: 'e9', option: 'Yes', index: 0 }]);

    assert.equal(calls.length, 0);
    assert.equal(out.countNodes(), before);
    assert.equal(out.allText(), text);
  } finally {
    globalThis.fetch = saved;
  }
});

// ------------------------------------------------------------------ the gallery

function renderCase(id) {
  const item = Fixtures.CASES.find((c) => c.id === id);
  assert.ok(item, id);
  const c = host();
  return { item, c, out: Scenes.renderScene(item.payload, c) };
}

test('the gallery has every case the owner asked to see, and together they draw every primitive', () => {
  const ids = Fixtures.CASES.map((c) => c.id);
  for (const id of ['customers-reply-2026-09-24', 'nothing-needs-you', 'ads-connector', 'collection-over-limit', 'proposal', 'question']) {
    assert.ok(ids.includes(id), id);
  }
  const types = new Set();
  for (const item of Fixtures.CASES) {
    assert.ok(item.title && item.note, item.id);
    const out = Scenes.renderScene(item.payload, host());
    for (const node of out.querySelectorAll('.scene-el')) types.add(node.dataset.type);
    assert.equal(out.querySelectorAll('.scene-el').length, item.payload.elements.length, item.id);
    assert.ok(item.payload.elements.length <= 3, `${item.id}: the answer and at most three more`);
    assert.ok(!out.allText().includes('@'), `${item.id}: no email address`);
  }
  assert.deepEqual([...types].sort(), [...Scenes.TYPES].sort());
});

test('the 2026-09-24 case is one Answer and its drill-down', () => {
  const { out } = renderCase('customers-reply-2026-09-24');
  assert.equal(out.querySelectorAll('.scene-el').length, 0);
  assert.equal(visibleText(out), 'Nobody is waiting on a reply: all 7 customers who emailed have been answered.');
  const panel = out.querySelector('.scene-drilldown');
  assert.equal(panel.hidden, true);
  out.querySelector('.scene-answer').dispatch('click');
  assert.equal(panel.querySelector('.scene-drilldown-line').textContent, 'Checked Recent orders, Inbox, Who has emailed');
  assert.equal(panel.querySelectorAll('.scene-source').length, 3);
});

test('the nothing-needs-you case is one line', () => {
  const { out } = renderCase('nothing-needs-you');
  assert.equal(out.querySelectorAll('.scene-el').length, 0);
  assert.equal(visibleText(out), 'Nothing needs you right now.');
  const lines = [];
  walk(out, (node) => { if (visible([node]).length && node.childNodes.some((n) => n.nodeType === 3)) lines.push(node); });
  assert.equal(lines.length, 1);
});

test('the ads-connector case is an Answer, a Finding and a Trend', () => {
  const { out } = renderCase('ads-connector');
  assert.deepEqual(out.querySelectorAll('.scene-el').map((n) => n.dataset.type), ['finding', 'trend']);
  assert.equal(out.querySelector('.scene-finding').dataset.significance, 'RISK');
  assert.ok(out.querySelector('.scene-trend').querySelector('polyline'));
});

test('the collection case is over its row limit', () => {
  const { item, c, out } = renderCase('collection-over-limit');
  const collection = item.payload.elements.find((e) => e.type === 'collection');
  assert.ok(collection.total > collection.limit);
  assert.equal(visible(out.querySelectorAll('.scene-row')).length, collection.limit);
  const drill = heard(c, 'scene-drilldown');
  out.querySelector('.scene-more').dispatch('click');
  assert.equal(drill.length, 1);
});

test('the proposal and question cases dispatch their events', () => {
  const p = renderCase('proposal');
  const proposals = heard(p.c, 'scene-proposal');
  p.out.querySelector('.scene-proposal').querySelector('button').dispatch('click');
  assert.deepEqual(proposals.map((e) => e.detail), [{ id: 'e2', action: 'act-2107' }]);
  const q = renderCase('question');
  const answers = heard(q.c, 'scene-answer');
  q.out.querySelector('.scene-chip').dispatch('click');
  assert.equal(answers.length, 1);
});

// ------------------------------------------------------------------ nothing the app loads changes

test('the gallery stands alone and nothing the app loads mentions a scene', () => {
  const page = fs.readFileSync(path.join(WEB, 'scenes-gallery.html'), 'utf8');
  const scripts = [...page.matchAll(/<script\b[^>]*>/g)].map((m) => m[0]);
  assert.deepEqual(scripts.map((s) => (/src="([^"]+)"/.exec(s) || [])[1]), ['/static/scenes.js', '/static/scene-fixtures.js']);
  assert.deepEqual([...page.matchAll(/href="([^"]+)"/g)].map((m) => m[1]), ['/static/style.css', '/static/scenes.css']);
  for (const name of ['index.html', 'app.js', 'sw.js', 'ui.js', 'style.css']) {
    assert.ok(!/scene/i.test(fs.readFileSync(path.join(WEB, name), 'utf8')), `${name} mentions a scene`);
  }
});

test('the scene styles use the existing design tokens and nothing new', () => {
  const css = fs.readFileSync(path.join(WEB, 'scenes.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const tokens = new Set([...fs.readFileSync(path.join(WEB, 'style.css'), 'utf8').matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
  const used = [...css.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((m) => m[1]);
  assert.ok(used.length > 20);
  for (const token of used) assert.ok(tokens.has(token), `${token} is not a token in web/style.css`);
  assert.ok(!/#[0-9a-f]{3,8}\b/i.test(css), 'a colour written by hand');
  assert.ok(!/\b(?:rgba?|hsla?|hwb|lab|lch|oklch|oklab|color)\(/i.test(css), 'a colour written by hand');
  assert.ok(!/@font-face|@import|url\(/i.test(css), 'a font or a file from elsewhere');
  assert.ok(!/(?:^|[;{\s])--[a-z0-9-]+\s*:/.test(css), 'a new token');
  for (const m of css.matchAll(/font(?:-family)?\s*:\s*([^;}]+)/g)) {
    if (/^font-family/.test(m[0])) assert.match(m[1].trim(), /^var\(--(?:font|mono)\)$/);
    else assert.match(m[1], /var\(--(?:font|mono)\)\s*$/, m[0]);
  }
});
