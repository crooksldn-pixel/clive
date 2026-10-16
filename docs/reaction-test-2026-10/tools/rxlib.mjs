// Shared harness for the reaction test: Chromium through curl (preview cookie jar),
// third-party trackers blocked, optional local overrides for crooks-reaction.js/.css.
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
export const pw = require(require('child_process').execSync('npm root -g').toString().trim() + '/playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');

export const THEME = '207329132887';
export const BUILD = new URL('./build/', import.meta.url).pathname;

export async function open({ url, width = 1440, height = 900, mobile = false, js = true, local = false, jar, net, init = [], reduced = false }) {
  const browser = await pw.chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: mobile ? 3 : 2, isMobile: mobile, hasTouch: mobile,
    javaScriptEnabled: js, reducedMotion: reduced ? 'reduce' : 'no-preference',
    userAgent: mobile ? 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36' : undefined,
  });
  fs.mkdirSync(net, { recursive: true });
  let n = 0;
  const bytes = {};
  await ctx.route('**/*', async (route) => {
    const req = route.request(), u = req.url();
    if (u.startsWith('data:') || u.startsWith('blob:')) return route.continue();
    if (/monorail|trekkie|analytics\.js|google|facebook|tiktok|klaviyo|shop\.app|captcha|clients2|api\/collect|bugsnag|mida-app|omnisend|web-pixels@|wpm@/.test(u)) return route.abort();
    if (local && /\/assets\/crooks-reaction\.js/.test(u)) return route.fulfill({ status: 200, headers: { 'content-type': 'application/javascript' }, body: fs.readFileSync(BUILD + 'assets/crooks-reaction.js') });
    if (local && /\/assets\/crooks-reaction\.css/.test(u)) return route.fulfill({ status: 200, headers: { 'content-type': 'text/css' }, body: fs.readFileSync(BUILD + 'assets/crooks-reaction.css') });
    const f = `${net}/${n++}`;
    const args = ['-sS', '-L', '--compressed', '--max-time', '40', '--retry', '2', '-b', jar, '-c', jar, '-D', f + '.h', '-o', f + '.b',
      '-A', mobile ? 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36' : 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
      '-H', 'Accept: ' + (req.headers()['accept'] || '*/*'), '-X', req.method()];
    const pd = req.postDataBuffer();
    if (pd) { fs.writeFileSync(f + '.req', pd); args.push('--data-binary', '@' + f + '.req', '-H', 'Content-Type: ' + (req.headers()['content-type'] || 'application/octet-stream')); }
    args.push(u);
    try {
      execFileSync('curl', args, { timeout: 45000 });
      const heads = fs.readFileSync(f + '.h', 'utf8').split(/\r?\n\r?\n/).filter(Boolean).pop();
      const status = +(heads.match(/^HTTP\/[\d.]+ (\d+)/) || [0, 200])[1];
      const ct = (heads.match(/^content-type:\s*(.*)$/im) || [0, 'application/octet-stream'])[1].trim();
      const body = fs.readFileSync(f + '.b');
      bytes[u] = body.length;
      if (req.resourceType() === 'document' && u.split('?')[0] === url.split('?')[0]) {
        if (!body.toString('utf8').includes(`"id":${THEME},`)) { console.error('NOT THE PREVIEW THEME'); process.exit(2); }
      }
      await route.fulfill({ status, headers: { 'content-type': ct, 'access-control-allow-origin': '*' }, body });
    } catch (e) { await route.abort(); }
  });
  await ctx.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const st = document.createElement('style');
      st.textContent = '#shopify-pc__banner,.ctc-offer,#PBarNextFrameWrapper,#preview-bar-iframe{display:none!important}';
      document.head.appendChild(st);
    });
    // Collect layout shifts and the reaction events.
    window.__cls = 0; window.__shifts = [];
    try {
      new PerformanceObserver((l) => { for (const e of l.getEntries()) { if (!e.hadRecentInput) { window.__cls += e.value; window.__shifts.push({ v: e.value, t: Math.round(e.startTime), src: (e.sources || []).map((s) => s.node && (s.node.className || s.node.nodeName)).join(' | ') }); } } }).observe({ type: 'layout-shift', buffered: true });
    } catch (e) {}
    window.__rx = []; window.__pub = [];
    document.addEventListener('crk:reaction', (e) => window.__rx.push(e.detail.name));
  });
  for (const s of init) await ctx.addInitScript(s);
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push('pageerror: ' + e.message.slice(0, 200)));
  page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 200)); });
  return { browser, ctx, page, errs, bytes };
}

// Share of the canvas (inside the photo rect) that carries paint, from its alpha.
// Wrap Shopify's customer-events publisher (after load) so calls can be counted.
export async function spyPublish(page) {
  return page.evaluate(() => {
    const a = window.Shopify && window.Shopify.analytics;
    if (!a || typeof a.publish !== 'function') return 'no Shopify.analytics.publish';
    const orig = a.publish;
    a.publish = function (n, d) { window.__pub.push([n, d]); return orig.apply(this, arguments); };
    return 'wrapped';
  });
}

export async function coverage(page) {
  return page.evaluate(() => {
    const c = document.querySelector('[data-crk-rx-canvas]');
    if (!c || !c.width) return -1;
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let on = 0;
    for (let i = 3; i < d.length; i += 16) if (d[i] > 8) on++;
    return +(on / (d.length / 16)).toFixed(4);
  });
}

export async function state(page) {
  return page.evaluate(() => {
    const r = document.querySelector('[data-crk-reaction]');
    return {
      view: r.getAttribute('data-crk-rx-view'), mode: r.getAttribute('data-crk-rx-mode'), ready: r.getAttribute('data-crk-rx-ready'),
      touched: r.hasAttribute('data-crk-rx-touched'),
      word: r.querySelector('[data-crk-rx-word]').textContent, st: r.querySelector('[data-crk-rx-status]').getAttribute('data-crk-rx-state'),
      toggle: r.querySelector('[data-crk-rx-toggle]').textContent, resetDisabled: r.querySelector('[data-crk-rx-reset]').getAttribute('aria-disabled'),
      hintOpacity: getComputedStyle(r.querySelector('[data-crk-rx-hint]')).opacity,
      fullOpacity: getComputedStyle(r.querySelector('.crk-rx__full')).opacity,
      events: window.__rx.slice(), published: window.__pub.map((p) => p[0]),
    };
  });
}

export async function frameBox(page) {
  return page.evaluate(() => { const r = document.querySelector('[data-crk-rx-frame]').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
}
