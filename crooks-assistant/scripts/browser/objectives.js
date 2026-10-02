/* Objectives in the shape of their kind, in a real browser (round 12).
 *
 *   node scripts/browser/objectives.js http://127.0.0.1:8765 [/path/to/screenshots]
 *
 * Driven by tests/test_objective_browser.py, which starts the real backend on the golden world,
 * gives it an objective written before round 12, and scripts the model's calls for the owner's
 * sentences. Here they are typed into the bar the way the tablet sends a sentence (POST /turn)
 * and the page is judged on what is on the glass:
 *
 *   - "samples have started for the AW drop with Northfield" draws a PROJECT: four stages on one
 *     rail, Sampling the current one, waiting on Northfield; no task list;
 *   - "give Rosa and Kit these tasks to do later: …" draws DELEGATED TASKS: one group per person,
 *     a round tick per task; a tap on a tick marks it done on the Mac and the card says so;
 *   - "move the AW drop on to approval" moves the project on the glass, and "production's
 *     started" said while that card is on the glass changes it in place;
 *   - the home shows a project's row with its progression and the tasks' row by person, and the
 *     objective written before round 12 reads as it did;
 *   - the sheets draw the same shapes, a tick in a sheet works, and nothing is wider than the
 *     screen or smaller than a finger, at the tablet's size (601 x 889 at DPR 1.33) and a
 *     phone's (390 x 844);
 *   - under reduced motion, and on the weak device, the current stage does not breathe.
 *
 * Prints one JSON object: { ok, checks: [{name, ok, detail}], shots: [...] }.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const BASE = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const OUT = process.argv[3] || '';
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const SIZES = {
  tablet: { viewport: { width: 601, height: 889 }, deviceScaleFactor: 1.33 },
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 },
};
const SAMPLES = 'Samples have started for the AW drop with Northfield';
const DELEGATE = 'Give Rosa and Kit these tasks to do later: Rosa, steam the AW samples and photograph the swatches; Kit, update the size chart';
const MOVE_ON = 'Move the AW drop on to approval';
const PRODUCTION = "The samples are approved, production's started";
const SHOW_PROJECT = 'Show me the AW drop';
const SHOW_TASKS = "Show me Rosa and Kit's tasks";

const checks = [];
const shots = [];
const check = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail).slice(0, 400) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function open(browser, size, extra) {
  const context = await browser.newContext(Object.assign({ isMobile: true, hasTouch: true, extraHTTPHeaders: HEADERS }, SIZES[size], extra || {}));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/\/speak|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.route('**/speak', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: '{"ok":false,"kind":"no_key"}' }));
  return { context, page, errors };
}

async function shot(page, name) {
  if (!OUT) return;
  const file = path.join(OUT, `${name}.png`);
  await page.waitForTimeout(500);
  await page.screenshot({ path: file, animations: 'disabled' });
  shots.push(path.basename(file));
}

async function home(page, query) {
  await page.goto(`${BASE}/?startup=off${query || ''}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#alpha-home .alpha-row[data-alpha="objective"]', { timeout: 15000 });
  await page.waitForTimeout(700);
}

// A sentence, the way the tablet sends one typed into the bar: tap, type, send.
async function say(page, words) {
  await page.click('#ask-bar');
  await page.fill('#alpha-input', words);
  const answered = page.waitForResponse((r) => r.url().endsWith('/turn') && r.request().method() === 'POST', { timeout: 20000 });
  await page.press('#alpha-input', 'Enter');
  const response = await answered;
  await page.waitForTimeout(900);
  return response.status();
}

const visibleCard = (page, kind) => page.evaluate((k) => {
  const all = Array.from(document.querySelectorAll('#cards .card[data-type="objective"]'));
  const card = all.reverse().find((c) => c.classList.contains(`is-${k}`) && c.getBoundingClientRect().height > 0);
  if (!card) return null;
  const r = card.getBoundingClientRect();
  return {
    kicker: (card.querySelector('.card-kicker') || {}).textContent || '',
    title: (card.querySelector('.card-title') || {}).textContent || '',
    status: (card.querySelector('.oc-status') || {}).textContent || '',
    steps: Array.from(card.querySelectorAll('.oc-step')).map((s) => ({ name: s.querySelector('.oc-step-name').firstChild.textContent, state: s.className.replace(/.*is-(done|current|upcoming).*/, '$1'), sub: (s.querySelector('.oc-step-sub') || {}).textContent || '' })),
    current: ((card.querySelector('.oc-step[aria-current="step"] .oc-step-name') || {}).firstChild || {}).textContent || '',
    groups: Array.from(card.querySelectorAll('.oc-group')).map((g) => ({ who: g.querySelector('.oc-who').textContent, count: g.querySelector('.oc-count').textContent, tasks: Array.from(g.querySelectorAll('.oc-task')).map((t) => ({ text: t.querySelector('.oc-task-text').textContent, checked: t.getAttribute('aria-checked'), h: Math.round(t.getBoundingClientRect().height) })) })),
    left: Math.round(r.left), right: Math.round(r.right), width: innerWidth,
  };
}, kind);

const overflow = (page) => page.evaluate(() => {
  const wide = document.documentElement.scrollWidth - innerWidth;
  // Any word of an objective cut off by its own box rather than wrapped.
  const cut = Array.from(document.querySelectorAll('.oc-task-text, .oc-step-name, .oc-who, .oc-fact dd, .card-objective .card-title'))
    .filter((n) => n.getBoundingClientRect().width > 0 && n.scrollWidth > n.clientWidth + 1).map((n) => n.textContent.slice(0, 40));
  return { wide, cut };
});

async function sheetFor(page, kind) {
  await page.click(`#alpha-home .alpha-row[data-alpha="objective"][data-kind="${kind}"]`);
  await page.waitForSelector('#alpha-sheet[open] .alpha-sheet-head', { timeout: 8000 });
  await page.waitForTimeout(500);
}
async function closeSheet(page) {
  await page.evaluate(() => { const s = document.getElementById('alpha-sheet'); if (s.open) s.close(); });
  await page.waitForTimeout(300);
}

async function tap(page, selector) {
  const box = await page.evaluate((sel) => {
    const n = document.querySelector(sel);
    if (!n) return null;
    n.scrollIntoView({ block: 'center' });
    const r = n.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }, selector);
  if (!box) return false;
  await page.waitForTimeout(250);
  await page.touchscreen.tap(box.x, box.y);
  return true;
}

async function record(page, kind) {
  return page.evaluate(async (k) => {
    const list = await (await fetch('/objectives', { cache: 'no-store' })).json();
    const row = (list.objectives || []).find((o) => o.kind === k);
    return row ? (await fetch(`/objectives/${row.id}`, { cache: 'no-store' })).json() : null;
  }, kind);
}

async function conversation(browser) {
  const { context, page, errors } = await open(browser, 'tablet');
  await home(page);
  const before = await page.evaluate(() => Array.from(document.querySelectorAll('#alpha-home .alpha-row[data-alpha="objective"]')).map((r) => ({ kind: r.dataset.kind, sub: (r.querySelector('.alpha-row-sub') || {}).textContent || '', track: Boolean(r.querySelector('.oc-track')) })));
  const old = before.find((r) => r.kind === 'business');
  check('an objective written before round 12 is on the home as it was: its question under its title, no progression',
    old && old.sub.includes('Which models do you want?') && !old.track, JSON.stringify(before));

  // ---- "samples have started for the AW drop with Northfield"
  check('the samples sentence is answered', (await say(page, SAMPLES)) === 200);
  const project = await visibleCard(page, 'project');
  check('it draws a project, not a list: four stages on one rail, Sampling current, waiting on Northfield',
    project && project.kicker === 'Project' && project.steps.length === 4 && project.current === 'Sampling'
      && project.steps[0].sub === 'Waiting on Northfield' && project.steps.slice(1).every((s) => s.state === 'upcoming') && !project.groups.length,
    JSON.stringify(project));
  check('its head says where it stands', project && project.status.startsWith('Stage 1 of 4'), project && project.status);
  let fit = await overflow(page);
  check('the project card fits the tablet: nothing wider than the screen, no word cut off', project && project.right <= project.width && fit.wide <= 0 && !fit.cut.length, JSON.stringify({ project: project && [project.left, project.right, project.width], fit }));
  await shot(page, 'tablet-01-project-card');

  // ---- "give Rosa and Kit these tasks to do later: …"
  check('the delegation sentence is answered', (await say(page, DELEGATE)) === 200);
  const tasks = await visibleCard(page, 'tasks');
  check('it draws delegated tasks: one group per person, each task with a tick, none done',
    tasks && tasks.kicker === 'Tasks' && tasks.groups.map((g) => g.who).join() === 'Rosa,Kit'
      && tasks.groups[0].tasks.map((t) => t.text).join('|') === 'Steam the AW samples|Photograph the swatches'
      && tasks.groups.every((g) => g.tasks.every((t) => t.checked === 'false')) && !tasks.steps.length,
    JSON.stringify(tasks));
  check('every task is at least a finger high', tasks && tasks.groups.every((g) => g.tasks.every((t) => t.h >= 44)), JSON.stringify(tasks && tasks.groups.map((g) => g.tasks.map((t) => t.h))));
  await shot(page, 'tablet-02-tasks-card');

  // ---- a tick on the card marks it done on the Mac
  await tap(page, '#cards .card-objective.is-tasks .oc-group .oc-task .oc-check');
  await page.waitForTimeout(900);
  const ticked = await visibleCard(page, 'tasks');
  const stored = await record(page, 'tasks');
  const rosa = stored && stored.tasks.find((t) => t.text === 'Steam the AW samples');
  check('a tap on a tick marks the task done on the Mac, and the card says so',
    ticked && ticked.groups[0].count === '1 of 2 done' && ticked.groups[0].tasks.some((t) => t.text === 'Steam the AW samples' && t.checked === 'true') && rosa && rosa.done === true,
    JSON.stringify({ card: ticked && ticked.groups[0], stored: rosa }));
  await shot(page, 'tablet-03-task-ticked');

  // ---- moved on by voice
  check('the move-on sentence is answered', (await say(page, MOVE_ON)) === 200);
  const moved = await visibleCard(page, 'project');
  check('the project on the glass is now at Approval, with Sampling done',
    moved && moved.current === 'Approval' && moved.steps[0].state === 'done' && moved.steps[0].sub.startsWith('Done '), JSON.stringify(moved));
  await shot(page, 'tablet-04-project-moved-on');

  // ---- moved on again while that very card is on the glass: the same card, changed in place
  check('the production sentence is answered', (await say(page, PRODUCTION)) === 200);
  const again = await visibleCard(page, 'project');
  const onGlass = await page.evaluate(() => Array.from(document.querySelectorAll('#cards .card[data-type="objective"]')).filter((c) => c.getBoundingClientRect().height > 0).length);
  check('with the project already on the glass, the card shows Production now, and only one of it',
    again && again.current === 'Production' && again.steps.slice(0, 2).every((st) => st.state === 'done') && onGlass === 1,
    JSON.stringify({ current: again && again.current, onGlass }));
  check('and shown again while it is on the glass, it is still there', (await say(page, SHOW_PROJECT)) === 200
    && ((await visibleCard(page, 'project')) || {}).current === 'Production');

  check('no error on the page through the conversation', !errors.length, errors.join(' | '));
  await context.close();

  // ---- the home, opened fresh as the owner opens the app
  const fresh = await open(browser, 'tablet');
  await home(fresh.page);
  const rows = await fresh.page.evaluate(() => Array.from(document.querySelectorAll('#alpha-home .alpha-row[data-alpha="objective"]')).map((r) => ({
    kind: r.dataset.kind, sub: (r.querySelector('.alpha-row-sub') || {}).textContent || '',
    segs: Array.from(r.querySelectorAll('.oc-seg')).map((s) => s.className.replace('oc-seg is-', '')),
  })));
  const projectRow = rows.find((r) => r.kind === 'project');
  const tasksRow = rows.find((r) => r.kind === 'tasks');
  check('the home shows the project by its stage, with its progression',
    projectRow && projectRow.sub.includes('Production') && projectRow.segs.join() === 'done,done,current,upcoming', JSON.stringify(projectRow));
  check('the home shows the tasks by person', tasksRow && tasksRow.sub.includes('Rosa 1 of 2') && tasksRow.sub.includes('Kit 0 of 1') && !tasksRow.segs.length, JSON.stringify(tasksRow));
  await shot(fresh.page, 'tablet-05-home');
  await fresh.context.close();
}

async function sheets(browser, size) {
  const { context, page, errors } = await open(browser, size);
  await home(page);
  await shot(page, `${size}-10-home`);
  let fit = await overflow(page);
  check(`${size}: the home is no wider than the screen`, fit.wide <= 0, JSON.stringify(fit));

  await sheetFor(page, 'project');
  const project = await page.evaluate(() => ({
    sub: document.querySelector('#alpha-sheet .alpha-sheet-head p').textContent,
    current: document.querySelector('#alpha-sheet .oc-step[aria-current="step"] .oc-step-name').firstChild.textContent,
    steps: document.querySelectorAll('#alpha-sheet .oc-step').length,
    done: Math.round(document.querySelector('#alpha-sheet .alpha-sheet-head .btn').getBoundingClientRect().width),
  }));
  check(`${size}: the project's sheet draws its stages with the current one lit`,
    project.steps === 4 && project.current === 'Production' && project.sub.startsWith('Project · Stage 3 of 4'), JSON.stringify(project));
  check(`${size}: the sheet's Done keeps its own size beside the title`, project.done < 160, project.done);
  fit = await overflow(page);
  check(`${size}: the project's sheet fits, no word cut off`, fit.wide <= 0 && !fit.cut.length, JSON.stringify(fit));
  await shot(page, `${size}-11-project-sheet`);
  await closeSheet(page);

  await sheetFor(page, 'tasks');
  const kitBefore = await record(page, 'tasks');
  await tap(page, '#alpha-sheet .oc-group:nth-of-type(2) .oc-task .oc-check');
  await page.waitForTimeout(900);
  const sheet = await page.evaluate(() => Array.from(document.querySelectorAll('#alpha-sheet .oc-group')).map((g) => ({ who: g.querySelector('.oc-who').textContent, count: g.querySelector('.oc-count').textContent })));
  const kitAfter = await record(page, 'tasks');
  const kitTask = (r) => r && r.tasks.find((t) => t.who === 'Kit');
  check(`${size}: a tick in the sheet changes Kit's task on the Mac and in the sheet`,
    kitTask(kitBefore) && kitTask(kitAfter) && kitTask(kitAfter).done !== kitTask(kitBefore).done
      && sheet[1] && sheet[1].count === (kitTask(kitAfter).done ? 'All done' : '0 of 1 done'),
    JSON.stringify({ sheet, before: kitTask(kitBefore), after: kitTask(kitAfter) }));
  fit = await overflow(page);
  check(`${size}: the tasks' sheet fits, no word cut off`, fit.wide <= 0 && !fit.cut.length, JSON.stringify(fit));
  await shot(page, `${size}-12-tasks-sheet`);
  await closeSheet(page);

  await sheetFor(page, 'business');
  const old = await page.evaluate(() => ({
    sub: document.querySelector('#alpha-sheet .alpha-sheet-head p').textContent,
    h3: Array.from(document.querySelectorAll('#alpha-sheet h3')).map((n) => n.textContent),
    shape: Boolean(document.querySelector('#alpha-sheet .alpha-shape')),
  }));
  check(`${size}: the objective written before round 12 opens as it did`,
    old.sub === 'By 2026-10-14 · Needs you' && old.h3[0] === 'Needs you' && old.h3.includes('What happens next') && !old.shape, JSON.stringify(old));
  await shot(page, `${size}-13-older-objective-sheet`);
  check(`${size}: no error on the page`, !errors.length, errors.join(' | '));
  await context.close();
}

// The stage it is at breathes; asked for less motion, or on the weak device, it holds still.
async function stillness(browser) {
  for (const [label, extra, query] of [['reduced motion', { reducedMotion: 'reduce' }, ''], ['the weak device', {}, '&lite=1']]) {
    const { context, page } = await open(browser, 'tablet', extra);
    await home(page, query);
    await sheetFor(page, 'project');
    const halo = await page.evaluate(() => {
      const node = document.querySelector('#alpha-sheet .oc-step.is-current .oc-node');
      const before = getComputedStyle(node, '::before');
      return { animation: before.animationName, glow: getComputedStyle(node).boxShadow };
    });
    check(`under ${label} the current stage does not breathe`, halo.animation === 'none'
      && (label !== 'the weak device' || halo.glow === 'none'), JSON.stringify(halo));
    await context.close();
  }
  const { context, page } = await open(browser, 'tablet');
  await home(page, '&lite=0');
  await sheetFor(page, 'project');
  const moving = await page.evaluate(() => getComputedStyle(document.querySelector('#alpha-sheet .oc-step.is-current .oc-node'), '::before').animationName);
  check('otherwise it does, so the two checks above can fail', moving === 'oc-breathe', moving);
  await context.close();
}

async function asks(browser) {
  // Reached from the conversation: the objective as it is now, shown again by voice.
  const { context, page } = await open(browser, 'phone');
  await home(page);
  check('phone: showing the AW drop again is answered', (await say(page, SHOW_PROJECT)) === 200);
  const project = await visibleCard(page, 'project');
  check('phone: the project card is drawn at a phone\'s width', project && project.current === 'Production' && project.right <= project.width, JSON.stringify(project));
  const fit = await overflow(page);
  check('phone: nothing wider than the screen, no word cut off', fit.wide <= 0 && !fit.cut.length, JSON.stringify(fit));
  await shot(page, 'phone-20-project-card');
  check('phone: showing the tasks again is answered', (await say(page, SHOW_TASKS)) === 200);
  const tasks = await visibleCard(page, 'tasks');
  check('phone: the tasks card is drawn at a phone\'s width', tasks && tasks.groups.length === 2 && tasks.right <= tasks.width, JSON.stringify(tasks));
  await shot(page, 'phone-21-tasks-card');
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  try {
    await conversation(browser);
    await sheets(browser, 'tablet');
    await sheets(browser, 'phone');
    await stillness(browser);
    await asks(browser);
  } catch (error) {
    check('the run finished', false, error && error.stack ? error.stack : error);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks, shots }));
})();
