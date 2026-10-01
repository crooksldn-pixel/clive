/* The screen page's visual flow, in a real Chromium at 1920 x 1080 (round 12).
 *
 *   node scripts/browser/tv_flow.js http://127.0.0.1:8765 [/dir/for/frames] [full,weak,calm]
 *
 * Driven by experience/tv_flow.py, which serves the real backend and does what this script asks
 * on its standard output (approve the screen with the code it shows; put a thing on it; take a
 * thing off), answering on its standard input. The last line printed is the report.
 *
 * The owner's complaint is that asking for something new on a screen sends it back to its home
 * (the clock) for a moment before the new thing comes, which adds a wait and looks clunky. So,
 * for every change in the walk, from the moment the page receives CLIVE's new answer this
 * records every frame the browser paints until the new thing is readable and a moment after:
 *
 *   clock   the home layer (the date, the line, the dot clock's own layer) is showing;
 *   empty   neither the old thing, nor the new one, nor a pane kept across the change is showing;
 *   kept    a pane that stays across the change (one beside it came or went) was hidden;
 *   ready   when the new thing's title is readable: fully opaque and no longer blurred.
 *
 * `full` is a TV with the dots (eight cores, as the page is told, whatever this machine has),
 * `weak` the lighter engine a small device gets (four cores, the SM-T290's, which is how
 * display.js decides it), `calm` reduced motion, and `portrait` a TV stood on its end. With a directory, each change is also filmed
 * (the browser's own screencast, so filming does not hold the page up) and frames at set moments
 * are written there; without one nothing is written and the timings are clean.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';
const OUT = process.argv[3] || '';
const MODES = (process.argv[4] || 'full,weak,calm').split(',').filter(Boolean);
const HEADERS = { 'Tailscale-User-Login': 'owner@example.com', 'X-Forwarded-For': '100.64.0.9' };
const VIEWPORT = { width: 1920, height: 1080 };
// Moments after the new answer arrives at which a frame is kept (milliseconds).
const MOMENTS = [0, 150, 350, 500, 650, 800, 950, 1100, 1300, 1600, 2000, 2500, 3500, 5000];
// From a replacement's answer arriving to the new thing being readable: the limit each
// replacement's result claims (`limit_ms`) and the verdict holds it to. About one second on an
// idle machine; the same bound tests/test_tv_flow.py holds the walk to.
const READY_MS = 2500;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The report's verdict, from everything it holds: false when any error was recorded (a page
// error, the page opening again, a step that threw), when nothing was measured, when any change
// never became readable, or when a measured time is over the limit its own result claims. It used
// to be false only when something threw, so a walk with page errors, or a view that never became
// readable, reported ok (the 2026-09-30 deploy review, SC1-01).
function verdict(report) {
  const why = [];
  const errors = (report && report.errors) || [];
  const results = (report && report.results) || [];
  for (const e of errors) why.push('error recorded: ' + e);
  if (!results.length) why.push('nothing was measured');
  for (const r of results) {
    const name = r.mode + ' ' + r.step;
    if (typeof r.ready_ms !== 'number') why.push(name + ': never became readable');
    else if (typeof r.limit_ms === 'number' && r.ready_ms > r.limit_ms) {
      why.push(name + ': readable after ' + r.ready_ms + ' ms, over its limit of ' + r.limit_ms + ' ms');
    }
  }
  return { ok: why.length === 0, why };
}

// ---- the line to experience/tv_flow.py ----------------------------------------------------
// Opened by main() alone, so that requiring this file (tests/web/followups-tv-flow.test.js)
// neither reads standard input nor needs a browser.
let lines = null;
const heard = [];
let waiting = null;
function listen() {
  lines = readline.createInterface({ input: process.stdin });
  lines.on('line', (line) => {
    let msg = null;
    try { msg = JSON.parse(line); } catch (e) { return; }
    if (waiting) { const w = waiting; waiting = null; w(msg); } else heard.push(msg);
  });
}
function ask(msg) {
  return new Promise((resolve) => {
    waiting = resolve;
    process.stdout.write(JSON.stringify(msg) + '\n');
    if (heard.length) { waiting = null; resolve(heard.shift()); }
  });
}

// ---- a stand-in for YouTube's player: its message protocol, and every command it is sent ----
const PLAYER = `<!doctype html><html><body style="margin:0;background:#101318;overflow:hidden">
<div style="position:absolute;inset:0;background:linear-gradient(160deg,#1b2638,#2d2a33 55%,#3b2f2a)"></div>
<div style="position:absolute;left:6%;bottom:8%;font:600 3vw system-ui,sans-serif;color:rgba(255,255,255,.85)">Studio playlist</div>
<script>
let state=-1,t=0,vol=100,muted=false,id=0;
window.__cmds=[];
function post(o){parent.postMessage(JSON.stringify(Object.assign({id,channel:'widget'},o)),'*')}
function info(){post({event:'infoDelivery',info:{playerState:state,currentTime:t,duration:213,volume:vol,muted}})}
addEventListener('message',(e)=>{let d;try{d=JSON.parse(e.data)}catch(x){return}
 if(d.event==='listening'){id=d.id;post({event:'onReady',info:null});info();return}
 if(d.event!=='command')return;window.__cmds.push(d.func);
 if(d.func==='playVideo')state=1;if(d.func==='pauseVideo')state=2;if(d.func==='mute')muted=true;if(d.func==='unMute')muted=false;
 if(d.func==='setVolume')vol=d.args[0];if(d.func==='seekTo')t=d.args[0];info()});
setInterval(()=>{if(state===1)t+=.5;info()},500);
</script></body></html>`;

// ---- in the page: when an answer arrives, and what each frame shows ------------------------
function probe() {
  const T = window.__tv = { arrivals: [], ticks: [], long: [] };
  // Every task that held the page up for more than 50 ms, and when.
  try {
    new PerformanceObserver((list) => { for (const e of list.getEntries()) T.long.push({ t: performance.timeOrigin + e.startTime, d: e.duration }); })
      .observe({ type: 'longtask', buffered: true });
  } catch (e) { /* not in this browser */ }
  // Every frame the browser paints, cheaply, for the frame rate across a change.
  const tick = () => { T.ticks.push(performance.timeOrigin + performance.now()); if (T.ticks.length > 4000) T.ticks.splice(0, 2000); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const real = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    return real(input, init).then((response) => {
      // An answer with something in it (a 204 says nothing new): when it reached the page.
      if (/\/displays\/scr_[0-9a-f]{12}\?v=/.test(url) && response.status === 200) T.arrivals.push(performance.timeOrigin + performance.now());
      return response;
    });
  };
  // How visible an element is: its opacity and blur, and every ancestor's, to the page — and a
  // reveal's mask (display.css cs-reveal, cs-resolve), which uncovers a page from the top: the
  // mask is 280% of the element's height, opaque to 46% of that and clear from 54%, and moves
  // from 100% to 0%, so at position p what is uncovered reaches down to (1.4 - 1.8p) of the
  // element. A title near the top counts once that line has passed a tenth of the way down. The
  // old page's wipe (cs-wipe) is the same mask turned over — clear at the top — so it covers the
  // page from the top, and a title near the top goes once that line has passed it.
  const chain = (node) => {
    let op = 1, blur = 0;
    for (let e = node; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return { op: 0, blur: 99 };
      op *= parseFloat(cs.opacity);
      const m = /blur\(([\d.]+)px\)/.exec(cs.filter || '');
      if (m) blur += parseFloat(m[1]);
      const image = cs.maskImage || cs.webkitMaskImage || 'none';
      if (image !== 'none') {
        const pos = /([\d.]+)%\s*$/.exec(cs.maskPosition || cs.webkitMaskPosition || '');
        const p = pos ? parseFloat(pos[1]) / 100 : 0;
        const wipe = /^linear-gradient\((?:180deg,\s*)?rgba\(0,\s*0,\s*0,\s*0\)/.test(image);
        op *= Math.max(0, Math.min(1, wipe ? (1.8 * p - 1.2) / 0.2 : (1.4 - 1.8 * p - 0.1) / 0.2));
      }
    }
    return { op, blur };
  };
  const seen = (title) => {
    let best = { op: 0, blur: 99, box: null };
    for (const n of document.querySelectorAll('#board .cs-h1, #board .cs-vtitle')) {
      if (n.textContent !== title) continue;
      const c = chain(n);
      if (c.op > best.op || (c.op === best.op && c.blur < best.blur)) best = Object.assign(c, { box: n.getBoundingClientRect() });
    }
    return best;
  };
  // Two titles drawn over each other, each plainly there: more than a third opaque. (The old page
  // dissolves to a veil at 0.3, blurred, and the soft edge of its wipe crosses the new page's; a
  // veil behind the new page is not a clash, a page at full strength under another is.)
  const clash = (a, b) => a.op > 0.35 && b.op > 0.35 && a.box && b.box
    && a.box.left < b.box.right && b.box.left < a.box.right && a.box.top < b.box.bottom && b.box.top < a.box.bottom;
  // Every frame from now — started before the change is asked for, so none is missed — until the
  // answer after the `n`th has arrived and the new thing has been readable for a moment: the home
  // layer, and the old, new and kept titles. Readiness is looked for only once the answer is in.
  T.watch = (asked, want, old, kept, home, panes) => new Promise((resolve) => {
    const frames = [];
    let readyAt = null;
    const stop = Date.now() + 20000;
    const step = () => {
      const now = performance.timeOrigin + performance.now();
      if (T.arrivals.length <= asked) { if (Date.now() > stop) { resolve({ frames, readyAt }); return; } requestAnimationFrame(step); return; }
      const idle = parseFloat(getComputedStyle(document.getElementById('idle')).opacity) || 0;
      const n = want.map(seen), o = old.map(seen), k = kept.map(seen);
      const newOp = n.length ? Math.min(...n.map((x) => x.op)) : 0;
      const newBlur = n.length ? Math.max(...n.map((x) => x.blur)) : 99;
      const oldOp = o.length ? Math.max(...o.map((x) => x.op)) : 0;
      const keptOp = k.length ? Math.min(...k.map((x) => x.op)) : 1;
      const anyNew = n.length ? Math.max(...n.map((x) => x.op)) : 0;
      const keptBlur = k.length ? Math.max(...k.map((x) => x.blur)) : 0;
      const count = document.querySelectorAll('#ui .cs-pane').length;
      // Readable: the new thing fully in and sharp; with nothing new (a pane taken off), the one
      // that stays sharp at its new size and the other gone.
      const ready = home ? idle >= 0.9
        : (want.length ? newOp >= 0.9 && newBlur <= 1.5 : oldOp <= 0.05)
          && (!k.length || (keptOp >= 0.9 && keptBlur <= 1.5)) && (!panes || count === panes);
      const collide = o.some((x) => n.concat(k).some((y) => clash(x, y)));
      frames.push({ t: now, idle, newOp, newBlur, oldOp, keptOp, anyNew, ready, collide });
      if (ready && readyAt === null) readyAt = now;
      if ((readyAt !== null && now - readyAt > 1200) || Date.now() > stop) { resolve({ frames, readyAt }); return; }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// What each change in the walk is: the store action, the titles it brings, the titles it takes
// away, and the titles that stay across it. `home` is a change that leaves nothing up.
const WALK = {
  full: [
    { name: 'first', act: { do: 'show', view: 'order-a' }, want: ['Order #2041'], old: [], kept: [] },
    { name: 'order-to-order', act: { do: 'show', view: 'order-b' }, want: ['Order #2042'], old: ['Order #2041'], kept: [], replace: true },
    { name: 'order-to-objective', act: { do: 'show', view: 'objective' }, want: ['Autumn samples'], old: ['Order #2042'], kept: [], replace: true },
    { name: 'objective-to-list', act: { do: 'show', view: 'list' }, want: ['Studio jobs'], old: ['Autumn samples'], kept: [], replace: true },
    { name: 'list-to-video', act: { do: 'show', view: 'video' }, want: ['Studio playlist'], old: ['Studio jobs'], kept: [], replace: true, video: 'up' },
    { name: 'beside-the-video', act: { do: 'show', view: 'beside', beside: true }, want: ['Packing today'], old: [], kept: ['Studio playlist'], replace: true, video: 'kept' },
    { name: 'video-to-order', act: { do: 'show', view: 'order-c', replace: 0 }, want: ['Order #2043'], old: ['Studio playlist'], kept: ['Packing today'], replace: true, video: 'gone' },
    { name: 'two-to-one', act: { do: 'off', pane: 0 }, want: [], old: ['Order #2043'], kept: ['Packing today'], panes: 1, replace: true },
    { name: 'off', act: { do: 'off' }, want: [], old: ['Packing today'], kept: [], home: true },
  ],
  short: [
    { name: 'first', act: { do: 'show', view: 'order-a' }, want: ['Order #2041'], old: [], kept: [] },
    { name: 'order-to-order', act: { do: 'show', view: 'order-b' }, want: ['Order #2042'], old: ['Order #2041'], kept: [], replace: true },
    { name: 'order-to-video', act: { do: 'show', view: 'video' }, want: ['Studio playlist'], old: ['Order #2042'], kept: [], replace: true, video: 'up' },
    { name: 'video-to-order', act: { do: 'show', view: 'order-c' }, want: ['Order #2043'], old: ['Studio playlist'], kept: [], replace: true, video: 'gone' },
    { name: 'off', act: { do: 'off' }, want: [], old: ['Order #2043'], kept: [], home: true },
  ],
};

async function film(context, page) {
  if (!OUT) return { stop: async () => [] };
  const cdp = await context.newCDPSession(page);
  const got = [];
  cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
    got.push({ t: metadata.timestamp * 1000, data });
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 75, maxWidth: 960, maxHeight: 960, everyNthFrame: 1 });
  return { stop: async () => { await cdp.send('Page.stopScreencast').catch(() => {}); await cdp.detach().catch(() => {}); return got; } };
}

async function runMode(browser, mode) {
  try { return await walkMode(browser, mode); } catch (e) { e.seen = (e.seen || []).concat(lastErrors); throw e; }
}
let lastErrors = [];
async function walkMode(browser, mode) {
  const name = { full: 'Office TV', weak: 'Packing TV', calm: 'Studio TV', portrait: 'Hall TV' }[mode];
  const viewport = mode === 'portrait' ? { width: 1080, height: 1920 } : VIEWPORT;
  const context = await browser.newContext({ viewport, extraHTTPHeaders: HEADERS, reducedMotion: mode === 'calm' ? 'reduce' : 'no-preference' });
  // How many cores the page is told the device has: display.js takes the weak path at four or fewer.
  const cores = mode === 'weak' ? 4 : 8;
  await context.addInitScript((n) => { Object.defineProperty(Navigator.prototype, 'hardwareConcurrency', { get: () => n, configurable: true }); }, cores);
  let playerLoads = 0;
  await context.route(/youtube-nocookie\.com\/embed\//, (route) => { playerLoads++; return route.fulfill({ contentType: 'text/html', body: PLAYER }); });
  await context.addInitScript(probe);
  const page = await context.newPage();
  const errors = lastErrors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  let opened = 0;
  page.on('framenavigated', (f) => { if (f === page.mainFrame() && ++opened > 1) errors.push('the page opened again: ' + f.url()); });
  await page.goto(BASE + '/display');
  // The first open names the screen and is approved with the code it shows, as the owner does.
  await page.waitForSelector('#namer:not([hidden])', { timeout: 60000 });
  await page.fill('#name-input', name);
  await page.click('#name-save');
  await page.waitForFunction(() => /^\d{3} \d{3}$/.test(document.getElementById('pair-code').textContent || ''), null, { timeout: 45000 });
  const code = (await page.textContent('#pair-code')).replace(/\D/g, '');
  const approved = await ask({ do: 'approve', name, code });
  if (!approved.ok) throw new Error('approve: ' + approved.error);
  await page.waitForFunction(() => document.getElementById('pairing').hidden && parseFloat(getComputedStyle(document.getElementById('idle')).opacity) > 0.9, null, { timeout: 45000 });
  await sleep(2500);

  const results = [];
  const walk = mode === 'full' || mode === 'portrait' ? WALK.full : WALK.short;
  for (const step of walk) {
    const before = await page.evaluate(() => window.__tv.arrivals.length);
    const camera = await film(context, page);
    const loadsBefore = playerLoads;
    const profiling = process.env.TV_FLOW_PROFILE === step.name ? await context.newCDPSession(page) : null;
    if (profiling) { await profiling.send('Profiler.enable'); await profiling.send('Profiler.setSamplingInterval', { interval: 200 }); await profiling.send('Profiler.start'); }
    const watching = page.evaluate(({ n, s }) => window.__tv.watch(n, s.want, s.old, s.kept, s.home, s.panes || 0), { n: before, s: step });
    const done = await ask(Object.assign({ name }, step.act));
    if (!done.ok) throw new Error(step.name + ': ' + done.error);
    const seen = await watching;
    let profile = null;
    if (profiling) {
      // Where the page's own time went across the change: self time by function, the largest first.
      const { profile: prof } = await profiling.send('Profiler.stop');
      const byId = new Map(prof.nodes.map((n) => [n.id, n]));
      const self = new Map();
      const dt = (prof.endTime - prof.startTime) / Math.max(1, prof.samples.length) / 1000;
      for (const id of prof.samples) {
        const n = byId.get(id);
        const f = n.callFrame;
        const key = (f.functionName || '(anonymous)') + ' ' + (f.url || '').split('/').pop() + ':' + (f.lineNumber + 1);
        self.set(key, (self.get(key) || 0) + dt);
      }
      profile = [...self.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14).map(([k, v]) => [k, Math.round(v)]);
      await profiling.detach().catch(() => {});
    }
    const arrived = await page.evaluate((n) => window.__tv.arrivals[n], before);
    if (arrived === undefined) throw new Error(step.name + ': the answer never arrived');
    const frames = seen.frames.filter((f) => f.t >= arrived);
    const ticks = await page.evaluate(({ a, b }) => window.__tv.ticks.filter((t) => t >= a && t <= b), { a: arrived, b: arrived + 2000 });
    const until = seen.readyAt === null ? Infinity : seen.readyAt;
    const inside = frames.filter((f) => f.t <= until);
    const out = {
      mode, step: step.name, replace: !!step.replace,
      ready_ms: seen.readyAt === null ? null : Math.round(seen.readyAt - arrived),
      // The limit this change is held to: a replacement's, READY_MS; none for the first thing
      // up or the screen going home, which only have to become readable at all.
      limit_ms: step.replace ? READY_MS : null,
      frames: inside.length,
      profile,
      // Every frame's reading across one named change, when asked for (TV_FLOW_TRACE).
      trace: process.env.TV_FLOW_TRACE === step.name ? frames.map((f) => [Math.round(f.t - arrived), +f.oldOp.toFixed(2), +f.keptOp.toFixed(2), +f.newOp.toFixed(2), +f.newBlur.toFixed(1)]) : undefined,
      fps: Math.round(ticks.length / 2),
      // The longest gaps between painted frames in those two seconds (ms): a long one is a stall.
      stalls: ticks.slice(1).map((t, i) => Math.round(t - ticks[i])).sort((a, b) => b - a).slice(0, 4),
      long_tasks: await page.evaluate((a) => window.__tv.long.filter((x) => x.t >= a - 100 && x.t <= a + 2500).map((x) => [Math.round(x.t - a), Math.round(x.d)]), arrived),
      clock_frames: step.home ? 0 : inside.filter((f) => f.idle > 0.05).length,
      empty_frames: step.home ? 0 : inside.filter((f) => f.idle <= 0.05 && f.anyNew <= 0.05 && f.oldOp <= 0.05 && (!step.kept.length || f.keptOp <= 0.05)).length,
      kept_hidden_frames: step.kept.length ? frames.filter((f) => f.keptOp < 0.3).length : 0,
      // Frames where something going and something new or staying are drawn over each other.
      collide_frames: frames.filter((f) => f.collide).length,
    };
    if (step.video) {
      await sleep(step.video === 'gone' ? 400 : 1500);
      const players = page.frames().filter((f) => /youtube-nocookie/.test(f.url()));
      const cmds = [];
      for (const f of players) cmds.push(await f.evaluate(() => window.__cmds.slice()).catch(() => []));
      out.video = { players: players.length, loads: playerLoads - loadsBefore, commands: cmds };
      if (step.video === 'gone') {
        await sleep(10000);
        out.video.left_on_board = await page.evaluate(() => document.querySelectorAll('#board .cs-vhost').length);
      }
    }
    const shots = await camera.stop();
    if (OUT && shots.length) {
      out.shots = [];
      out.filmed = shots.filter((x) => x.t >= arrived && x.t <= arrived + 3000).length;
      const last = shots.filter((s) => s.t < arrived).pop();
      if (last) { const file = `${mode}-${step.name}-before.jpg`; fs.writeFileSync(path.join(OUT, file), Buffer.from(last.data, 'base64')); out.shots.push(file); }
      for (const ms of MOMENTS) {
        const at = arrived + ms;
        const pick = shots.filter((s) => s.t <= at && s.t >= arrived - 20).pop();
        if (!pick) continue;
        const file = `${mode}-${step.name}-${String(ms).padStart(4, '0')}ms.jpg`;
        fs.writeFileSync(path.join(OUT, file), Buffer.from(pick.data, 'base64'));
        out.shots.push(file);
      }
    }
    results.push(out);
    await sleep(step.video === 'gone' ? 1500 : 2500);
  }
  // The weak path hides the bloom (display.js), on the page as it was and as it is.
  const weakened = await page.evaluate(() => document.getElementById('bloom').hidden);
  if (weakened !== (mode === 'weak')) throw new Error(mode + ': the page took the ' + (weakened ? 'weak' : 'full') + ' path');
  if (OUT) await page.screenshot({ path: path.join(OUT, `${mode}-end.png`) });
  await context.close();
  return { results, errors };
}

async function main() {
  listen();
  const { chromium } = require('playwright-core');
  const browser = await chromium.launch({ executablePath: process.env.CROOKS_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--autoplay-policy=no-user-gesture-required'] });
  const report = { ok: false, results: [], errors: [] };
  try {
    for (const mode of MODES) {
      const got = await runMode(browser, mode);
      report.results.push(...got.results);
      report.errors.push(...got.errors.map((e) => mode + ': ' + e));
    }
  } catch (e) {
    report.errors.push(String(e && e.stack || e));
    report.errors.push(...(e && e.seen ? e.seen : []));
  } finally {
    await browser.close();
  }
  const judged = verdict(report);
  report.ok = judged.ok;
  report.why = judged.why;
  process.stdout.write(JSON.stringify(report) + '\n');
  lines.close();
}

module.exports = { verdict, READY_MS, WALK };

if (require.main === module) main();
