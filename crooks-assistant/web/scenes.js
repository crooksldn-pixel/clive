/* The scene renderer: a render payload (app/scenes/payload.py) drawn as a work surface.
 *
 * The payload is a validated scene with every value already resolved and worded, so this file
 * formats nothing and decides nothing: it places text. It draws the closed set of primitives
 * — Answer, Finding, Entity, Collection, Measure, Comparison, Trend, Timeline, Proposal,
 * Question — and the drill-down to what an answer checked. Anything else draws nothing.
 *
 *   - Every string lands through textContent. No markup is ever built from a string.
 *   - A control asks, it never acts: a Proposal's button dispatches CustomEvent('scene-proposal'),
 *     a Question's chip CustomEvent('scene-answer'), a Collection's "show all" past what the
 *     scene holds CustomEvent('scene-drilldown'). Whatever hosts the scene decides what follows.
 *   - An element's justification is for the trace and is never drawn.
 *
 * Not loaded by the app yet: web/scenes-gallery.html is its only page. Like web/ui.js it has no
 * dependency on the rest of the app, so it runs under Node against tests/web/dom-shim.js.
 */
(function (root, factory) {
  const api = factory();
  root.CliveScenes = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // The significance of a Finding, in the owner's words.
  const SIGNIFICANCE = {
    ACTION_REQUIRED: 'Needs you',
    DECISION_REQUIRED: 'Decide',
    RISK: 'Risk',
    UNCERTAINTY: 'Unsure',
    LIMITATION: 'Limit',
    CONTEXT: 'Context',
  };

  // ------------------------------------------------------------------ safe DOM

  const str = (value) => (value === null || value === undefined ? '' : String(value));
  const arr = (value) => (Array.isArray(value) ? value : []);
  const isObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

  function el(tag, cls, text) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  }

  function svg(tag, attrs) {
    const node = doc().createElementNS(SVG_NS, tag);
    for (const key in attrs) node.setAttribute(key, String(attrs[key]));
    return node;
  }

  function button(cls, text) {
    const node = el('button', cls, text);
    node.setAttribute('type', 'button');
    return node;
  }

  // A control that opens and closes a panel beneath it, and does nothing else.
  function disclose(control, panel) {
    panel.hidden = true;
    control.setAttribute('aria-expanded', 'false');
    control.addEventListener('click', () => {
      const open = panel.hidden;
      panel.hidden = !open;
      control.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  function emit(node, type, detail) {
    if (typeof node.dispatchEvent !== 'function' || typeof CustomEvent !== 'function') return;
    node.dispatchEvent(new CustomEvent(type, { bubbles: true, detail }));
  }

  function caption(text) { return str(text) ? el('p', 'scene-caption', text) : null; }

  function add(parent, child) { if (child) parent.appendChild(child); return parent; }

  // One read an answer or a finding checked: what it was, what it found, when.
  function sourceRow(source) {
    const row = el('li', 'scene-source');
    row.appendChild(el('span', 'scene-source-label', source.label));
    const meta = [str(source.found_text), str(source.checked)].filter(Boolean).join(' · ');
    add(row, meta ? el('span', 'scene-source-meta', meta) : null);
    return row;
  }

  function sources(list) {
    const items = arr(list).filter(isObject);
    if (!items.length) return null;
    const out = el('ul', 'scene-sources');
    for (const source of items) out.appendChild(sourceRow(source));
    return out;
  }

  // Label and value rows, for an Entity and for the values behind a Finding.
  function fieldRows(values) {
    const items = arr(values).filter(isObject);
    if (!items.length) return null;
    const out = el('dl', 'scene-fields');
    for (const value of items) {
      const row = el('div', 'scene-field');
      row.appendChild(el('dt', 'scene-field-label', value.label));
      row.appendChild(el('dd', 'scene-field-value', value.text));
      out.appendChild(row);
    }
    return out;
  }

  // ------------------------------------------------------------------ the answer

  function renderAnswer(answer, drilldown) {
    const text = str(answer.text);
    if (!drilldown) {
      const line = el('p', 'scene-answer', text);
      line.dataset.sceneId = str(answer.id) || 'answer';
      return line;
    }
    // Only the Answer is shown: it is the one line on the screen, and a tap on it opens the
    // line of what was checked. The checked evidence opens only on request.
    const wrap = el('div', 'scene-lead');
    const line = button('scene-answer', text);
    line.dataset.sceneId = str(answer.id) || 'answer';
    const panel = el('div', 'scene-drilldown');
    panel.dataset.sceneId = str(drilldown.id) || 'drilldown';
    const items = arr(drilldown.sources).filter(isObject);
    const labels = items.map((s) => str(s.label)).filter(Boolean);
    panel.appendChild(el('p', 'scene-drilldown-line', `Checked ${labels.join(', ')}`));
    add(panel, sources(items));
    disclose(line, panel);
    wrap.appendChild(line);
    wrap.appendChild(panel);
    return wrap;
  }

  // ------------------------------------------------------------------ primitives

  function renderFinding(item) {
    const code = str(item.significance);
    const node = el('div', 'scene-el scene-finding');
    node.dataset.significance = SIGNIFICANCE[code] ? code : 'CONTEXT';
    const head = button('scene-finding-head');
    head.appendChild(el('span', 'scene-sig', SIGNIFICANCE[code] || SIGNIFICANCE.CONTEXT));
    head.appendChild(el('span', 'scene-finding-text', item.text));
    const panel = el('div', 'scene-evidence');
    add(panel, fieldRows(item.values));
    add(panel, sources(item.sources));
    node.appendChild(head);
    node.appendChild(panel);
    disclose(head, panel);
    return node;
  }

  function renderEntity(item) {
    const node = el('div', 'scene-el scene-entity');
    add(node, caption(item.caption));
    add(node, fieldRows(item.fields));
    return node;
  }

  function renderCollection(item) {
    const node = el('div', 'scene-el scene-collection');
    add(node, caption(item.caption));
    const columns = arr(item.columns).filter(isObject);
    const rows = arr(item.rows).filter(isObject);
    const limit = Number.isInteger(item.limit) && item.limit > 0 ? item.limit : rows.length;
    const total = Math.max(Number.isInteger(item.total) ? item.total : 0, rows.length);

    const table = el('table', 'scene-table');
    const head = el('thead');
    const headRow = el('tr');
    for (const column of columns) headRow.appendChild(el('th', column.numeric ? 'scene-num' : '', column.label));
    head.appendChild(headRow);
    table.appendChild(head);
    const body = el('tbody');
    const hidden = [];
    rows.forEach((row, index) => {
      const tr = el('tr', 'scene-row');
      const cells = arr(row.cells);
      columns.forEach((column, n) => tr.appendChild(el('td', column.numeric ? 'scene-num' : '', str(cells[n]))));
      // Past its row limit a row waits behind "show all".
      if (index >= limit) { tr.hidden = true; hidden.push(tr); }
      body.appendChild(tr);
    });
    table.appendChild(body);
    node.appendChild(table);

    const shown = Math.min(rows.length, limit);
    if (total > shown) {
      const more = button('scene-more', `Show all ${total}`);
      more.addEventListener('click', () => {
        for (const tr of hidden) tr.hidden = false;
        // What the scene does not hold is opened by whatever hosts it.
        if (total > rows.length) emit(more, 'scene-drilldown', { id: str(item.id), evidence: str(item.evidence) });
        else more.hidden = true;
      });
      node.appendChild(more);
    }
    return node;
  }

  function renderMeasure(item) {
    const node = el('div', 'scene-el scene-measure');
    add(node, caption(item.label));
    const figure = el('p', 'scene-figure');
    figure.appendChild(el('span', 'scene-big', item.value));
    add(figure, str(item.unit) ? el('span', 'scene-unit', item.unit) : null);
    node.appendChild(figure);
    add(node, str(item.period) ? el('p', 'scene-period', item.period) : null);
    return node;
  }

  function renderComparison(item) {
    const node = el('div', 'scene-el scene-comparison');
    const current = isObject(item.current) ? item.current : {};
    const previous = isObject(item.previous) ? item.previous : {};
    add(node, caption(item.label || current.label));
    const figure = el('p', 'scene-figure');
    figure.appendChild(el('span', 'scene-big', current.text));
    node.appendChild(figure);
    const diff = el('p', 'scene-diff', item.difference);
    diff.dataset.direction = ['up', 'down', 'same'].includes(item.direction) ? item.direction : 'unknown';
    node.appendChild(diff);
    node.appendChild(el('p', 'scene-period', `${str(previous.label)} ${str(previous.text)}`.trim()));
    return node;
  }

  function sparkline(values, label) {
    const points = arr(values).filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (points.length < 2) return null;
    const width = 100;
    const height = 28;
    const pad = 3;
    const low = Math.min(...points);
    const span = Math.max(...points) - low || 1;
    const xy = points.map((v, i) => [
      (i / (points.length - 1)) * width,
      height - pad - ((v - low) / span) * (height - 2 * pad),
    ]);
    const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, class: 'scene-spark', role: 'img', 'aria-label': str(label) });
    chart.appendChild(svg('polyline', {
      points: xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' '),
      'vector-effect': 'non-scaling-stroke',
    }));
    const [lastX, lastY] = xy[xy.length - 1];
    chart.appendChild(svg('circle', { cx: lastX.toFixed(2), cy: lastY.toFixed(2), r: 1.6 }));
    return chart;
  }

  function renderTrend(item) {
    const node = el('div', 'scene-el scene-trend');
    add(node, caption(item.label));
    const figure = el('p', 'scene-figure');
    figure.appendChild(el('span', 'scene-big scene-big-sm', item.latest));
    node.appendChild(figure);
    add(node, sparkline(item.values, item.label));
    const range = [str(item.from), str(item.to)].filter(Boolean).join(' – ');
    add(node, range ? el('p', 'scene-period', range) : null);
    return node;
  }

  function renderTimeline(item) {
    const node = el('div', 'scene-el scene-timeline');
    add(node, caption(item.caption));
    const list = el('ol', 'scene-times');
    for (const row of arr(item.rows).filter(isObject)) {
      const li = el('li', 'scene-time');
      const when = el('time', 'scene-when', row.at);
      if (str(row.at_iso)) when.setAttribute('datetime', str(row.at_iso));
      li.appendChild(when);
      li.appendChild(el('span', 'scene-what', row.label));
      list.appendChild(li);
    }
    node.appendChild(list);
    return node;
  }

  function renderProposal(item) {
    const node = el('div', 'scene-el scene-proposal');
    node.appendChild(el('p', 'scene-proposal-text', item.text));
    const review = button('scene-button', 'Review');
    review.addEventListener('click', () => {
      emit(review, 'scene-proposal', { id: str(item.id), action: str(item.action) });
    });
    node.appendChild(review);
    return node;
  }

  function renderQuestion(item) {
    const node = el('div', 'scene-el scene-question');
    node.appendChild(el('p', 'scene-question-text', item.text));
    const chips = el('div', 'scene-chips');
    arr(item.options).map(str).filter(Boolean).forEach((option, index) => {
      const chip = button('scene-chip', option);
      chip.addEventListener('click', () => {
        emit(chip, 'scene-answer', { id: str(item.id), option, index });
      });
      chips.appendChild(chip);
    });
    add(node, chips.childNodes.length ? chips : null);
    return node;
  }

  const PRIMITIVES = {
    finding: renderFinding,
    entity: renderEntity,
    collection: renderCollection,
    measure: renderMeasure,
    comparison: renderComparison,
    trend: renderTrend,
    timeline: renderTimeline,
    proposal: renderProposal,
    question: renderQuestion,
  };

  // ------------------------------------------------------------------ the scene

  function renderScene(payload, container) {
    const scene = isObject(payload) ? payload : {};
    const answer = isObject(scene.answer) ? scene.answer : {};
    const drilldown = isObject(scene.drilldown) && arr(scene.drilldown.sources).some(isObject) ? scene.drilldown : null;
    const root = el('section', 'scene');
    root.appendChild(renderAnswer(answer, drilldown));
    const list = el('div', 'scene-elements');
    for (const item of arr(scene.elements)) {
      if (!isObject(item) || !Object.prototype.hasOwnProperty.call(PRIMITIVES, item.type)) continue;
      const node = PRIMITIVES[item.type](item);
      node.dataset.sceneId = str(item.id);
      node.dataset.type = item.type;
      list.appendChild(node);
    }
    add(root, list.childNodes.length ? list : null);
    if (container) {
      container.textContent = '';
      container.appendChild(root);
    }
    return root;
  }

  return { renderScene, SIGNIFICANCE, TYPES: Object.keys(PRIMITIVES) };
});
