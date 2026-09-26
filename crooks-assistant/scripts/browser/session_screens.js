/* The screens of a test session, drawn as pictures.
 *
 *   node scripts/browser/session_screens.js <screens dir> <out dir> [web dir]
 *   (or: make test-session-screens [SESSION=ts-…])
 *
 * With CROOKS_SCREEN_SNAPSHOTS on, the page sends a copy of what it was showing at each answer,
 * each question, each failure and each tap on the phone's home (web/telemetry.js), and the
 * backend keeps each one beside the session's timeline as `<n>-<reason>.json`. This draws every
 * one of them at the size and pixel density of the screen that sent it, with the app's own
 * stylesheets, and writes one PNG each plus `index.html`: the pictures in order, each with its
 * time, what it was taken for, its turn, and the failure that triggered it, if one did.
 *
 * Nothing in a copy runs. The page took its scripts and handlers out before sending it; here a
 * Content-Security-Policy refuses every script and every fetch besides, and the stylesheets are
 * read from the checkout and inlined, so drawing a session needs no server, no network and no
 * login. Animations are stopped at their last frame, so a picture shows where things landed.
 *
 * Prints one JSON object: { ok, drawn, failed, out }.
 */
'use strict';

const fs = require('fs');
const path = require('path');

function loadChromium() {
  try { return require('playwright').chromium; } catch { /* fall through */ }
  return require('playwright-core').chromium;
}

const SCREENS = process.argv[2];
const OUT = process.argv[3];
const WEB = process.argv[4] || path.join(__dirname, '..', '..', 'web');

if (!SCREENS || !OUT) {
  console.error('usage: node scripts/browser/session_screens.js <screens dir> <out dir> [web dir]');
  process.exit(2);
}

const escapeHtml = (value) => String(value == null ? '' : value)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function stylesheets() {
  return ['style.css', 'alpha.css']
    .map((name) => path.join(WEB, name))
    .filter((file) => fs.existsSync(file))
    .map((file) => `<style>${fs.readFileSync(file, 'utf8')}</style>`)
    .join('\n');
}

function page(copy, css) {
  const body = copy.body || {};
  const lite = copy.lite ? ' data-lite="1"' : '';
  return `<!doctype html>
<html lang="en-GB"${lite}>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:">
<meta name="viewport" content="width=device-width,initial-scale=1">
${css}
<style>
*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition-duration:0s!important;transition-delay:0s!important}
dialog[data-snap-dialog]{display:block}
</style>
</head>
<body class="${escapeHtml(body.class)}" data-mode="${escapeHtml(body.mode)}">
${copy.html}
</body>
</html>`;
}

function describe(trigger) {
  if (!trigger || typeof trigger !== 'object') return '';
  const bits = [];
  for (const key of ['kind', 'status', 'path', 'message', 'file', 'line', 'src', 'target', 'control', 'outcome', 'reason', 'code']) {
    if (trigger[key] !== undefined && trigger[key] !== null && trigger[key] !== '') bits.push(`${key}: ${trigger[key]}`);
  }
  return bits.join(' · ');
}

(async () => {
  const files = fs.existsSync(SCREENS)
    ? fs.readdirSync(SCREENS).filter((name) => name.endsWith('.json')).sort()
    : [];
  fs.mkdirSync(OUT, { recursive: true });
  const css = stylesheets();
  const chromium = loadChromium();
  const browser = await chromium.launch();
  const drawn = [];
  const failed = [];
  try {
    for (const name of files) {
      let copy;
      try { copy = JSON.parse(fs.readFileSync(path.join(SCREENS, name), 'utf8')); } catch (err) { failed.push({ name, why: 'unreadable' }); continue; }
      const vp = copy.viewport || {};
      const width = Math.max(320, Math.min(1600, Number(vp.w) || 390));
      const height = Math.max(480, Math.min(2400, Number(vp.h) || 844));
      const dpr = Math.max(1, Math.min(3, Number(vp.dpr) || 2));
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: dpr, offline: true });
      const tab = await context.newPage();
      try {
        await tab.setContent(page(copy, css), { waitUntil: 'load' });
        await tab.evaluate(() => {
          for (const node of document.querySelectorAll('[data-snap-top],[data-snap-left]')) {
            node.scrollTop = Number(node.getAttribute('data-snap-top') || 0);
            node.scrollLeft = Number(node.getAttribute('data-snap-left') || 0);
          }
        });
        const png = name.replace(/\.json$/, '.png');
        await tab.screenshot({ path: path.join(OUT, png) });
        drawn.push({ png, reason: copy.reason || '', t: copy.t || null, turn_id: copy.turn_id || '', trigger: describe(copy.trigger), size: `${width}×${height}` });
      } catch (err) {
        failed.push({ name, why: String(err && err.message || err).slice(0, 200) });
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }

  const when = (t) => (t ? new Date(t).toLocaleString('en-GB', { timeZone: 'Europe/London' }) : '');
  const cards = drawn.map((d) => `<figure class="${d.reason === 'error' || d.reason === 'offline' ? 'bad' : ''}">
<img src="${escapeHtml(d.png)}" alt="${escapeHtml(d.reason)} at ${escapeHtml(when(d.t))}" loading="lazy">
<figcaption><b>${escapeHtml(d.reason)}</b> · ${escapeHtml(when(d.t))}${d.turn_id ? ` · turn ${escapeHtml(d.turn_id)}` : ''}${d.trigger ? `<br><span>${escapeHtml(d.trigger)}</span>` : ''}</figcaption>
</figure>`).join('\n');
  fs.writeFileSync(path.join(OUT, 'index.html'), `<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CLIVE session screens</title>
<style>
body{margin:0;padding:24px;background:#0d0e11;color:#ececef;font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
h1{font-size:22px;margin:0 0 4px}p{margin:0 0 20px;color:#a3a3ad}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}
figure{margin:0;background:#16171b;border-radius:18px;padding:10px;border:1px solid #26272d}
figure.bad{border-color:#b4564a}
img{display:block;width:100%;border-radius:12px;background:#000}
figcaption{margin-top:8px;font-size:13px;color:#c9c9d1}figcaption span{color:#e38f82;word-break:break-word}
</style></head><body>
<h1>Session screens</h1>
<p>${drawn.length} drawn${failed.length ? `, ${failed.length} could not be drawn` : ''}. Red frames were taken for a failure.</p>
<main>
${cards}
</main>
</body></html>
`);
  console.log(JSON.stringify({ ok: failed.length === 0, drawn: drawn.length, failed, out: OUT }));
})().catch((err) => {
  console.error(err && err.stack || String(err));
  process.exit(1);
});
