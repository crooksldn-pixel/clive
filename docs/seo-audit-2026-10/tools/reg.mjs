// Storefront regression pass. usage: CJ=<cookie jar> node reg.mjs <SP> <label>
// Walks home, mobile menu, collection, PDP (pick size, add to bag), cart, search,
// tracking and footer at 390px, recording checks, JS errors and screenshots.
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const pw = require(require('child_process').execSync('npm root -g').toString().trim() + '/playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const [SP, label] = process.argv.slice(2);
const CJ = process.env.CJ;
const OUT = `${SP}/audit/regression/${label}`; fs.mkdirSync(OUT, { recursive: true });
const browser = await pw.chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
let n = 0; fs.mkdirSync(`${SP}/harness/net3`, { recursive: true });
await ctx.route('**/*', async (route) => {
  const req = route.request(), u = req.url();
  if (u.startsWith('data:') || u.startsWith('blob:')) return route.continue();
  if (/monorail|trekkie|web-pixels|analytics|google|facebook|tiktok|klaviyo|shop\.app|captcha|clients2|api\/collect|bugsnag/.test(u)) return route.abort();
  const f = `${SP}/harness/net3/${n++}`;
  try {
    const args = ['-sS', '-L', '--compressed', '--max-time', '40', '-b', CJ, '-c', CJ, '-D', f + '.h', '-o', f + '.b', '-A', req.headers()['user-agent'] || 'Mozilla/5.0', '-H', 'Accept: ' + (req.headers()['accept'] || '*/*'), '-X', req.method()];
    if (req.postData()) args.push('--data-binary', req.postData(), '-H', 'Content-Type: ' + (req.headers()['content-type'] || 'application/json'));
    args.push(u);
    execFileSync('curl', args, { timeout: 45000 });
    const heads = fs.readFileSync(f + '.h', 'utf8').split(/\r?\n\r?\n/).filter(Boolean).pop();
    const status = +(heads.match(/^HTTP\/[\d.]+ (\d+)/) || [0, 200])[1];
    const ct = (heads.match(/^content-type:\s*(.*)$/im) || [0, 'application/octet-stream'])[1].trim();
    await route.fulfill({ status, headers: { 'content-type': ct, 'access-control-allow-origin': '*' }, body: fs.readFileSync(f + '.b') });
  } catch (e) { await route.abort(); }
});
await ctx.addInitScript(() => {
  document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '#shopify-pc__banner{display:none!important}'; document.head.appendChild(st); });
});
const page = await ctx.newPage();
let errs = [];
page.on('pageerror', (e) => errs.push('pageerror ' + e.message.slice(0, 200)));
page.on('console', (m) => { if (m.type() === 'error') errs.push('console ' + m.text().slice(0, 200)); });
const report = [];
const B = 'https://crooksldn.com';
const ONLY = (process.env.ONLY || '').split(',').filter(Boolean);
async function visit(name, path, fn) {
  if (ONLY.length && !ONLY.includes(name)) return;
  errs = [];
  const r = { name, path };
  try {
    const resp = await page.goto(B + path, { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(2000);
    r.status = resp.status();
    r.theme = await page.evaluate(() => window.Shopify && Shopify.theme && Shopify.theme.id);
    r.h1 = await page.evaluate(() => [...document.querySelectorAll('h1')].map((h) => ({ text: h.textContent.trim().slice(0, 40), visible: !!(h.offsetWidth || h.offsetHeight) })));
    await page.screenshot({ path: `${OUT}/${name}.png` });
    if (fn) Object.assign(r, await fn());
  } catch (e) { r.error = String(e).slice(0, 200); }
  r.errors = [...new Set(errs)];
  report.push(r); console.log(JSON.stringify(r));
}
const imgOk = (sel) => page.evaluate((s) => { const i = document.querySelector(s); return i ? { complete: i.complete, w: i.naturalWidth, loading: i.getAttribute('loading'), fp: i.getAttribute('fetchpriority') } : null; }, sel);

await visit('home', '/', async () => ({
  navLinks: await page.locator('header a[href]').count(),
  firstSighting: await imgOk('.crk-sight img, [class*="sight"] img'),
  footerLinks: await page.locator('footer a[href]').count(),
}));
await visit('menu', '/', async () => {
  const btn = page.locator('[data-crk-drawer-open]').first();
  const shown = await btn.isVisible();
  const box = await btn.boundingBox();
  const topEl = box && await page.evaluate(([x, y]) => { const e = document.elementFromPoint(x, y); return e && (e.tagName + '.' + e.className + ' #' + e.id).slice(0, 120); }, [box.x + box.width / 2, box.y + box.height / 2]);
  if (shown) await btn.click({ timeout: 5000 }).catch(async () => { await btn.evaluate((b) => b.click()); });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/menu-open.png` });
  return { menuButtonVisible: shown, box, topEl, expanded: await btn.getAttribute('aria-expanded'), drawerLinks: await page.locator('#crk-drawer a[href]').evaluateAll((as) => as.filter((a) => a.offsetWidth || a.offsetHeight).map((a) => a.textContent.trim()).slice(0, 12)) };
});
await visit('collection-denim', '/collections/denim', async () => ({
  cards: await page.locator('.crk-log__cell').count(),
  intro: await page.evaluate(() => { const d = document.querySelector('.crk-log__intro'); return d ? { text: d.textContent.trim(), visible: !!d.offsetHeight, color: getComputedStyle(d).color } : null; }),
  firstCardImg: await imgOk('.crk-log__cell img'),
}));
await visit('collection-all', '/collections/all', async () => ({ cards: await page.locator('.crk-log__cell').count(), firstCardImg: await imgOk('.crk-log__cell img') }));
await visit('pdp', '/products/blue-wash-yard-jeans', async () => {
  const out = {};
  out.price = await page.evaluate(() => (document.body.innerText.match(/£\d+(\.\d\d)?/) || [null])[0]);
  out.mainImg = await imgOk('img[fetchpriority="high"], main img');
  out.buyBefore = (await page.locator('[data-crk-buy]').first().textContent()).trim();
  const sizes = page.locator('.crk-size:not([disabled])');
  out.sizes = await sizes.count();
  await sizes.nth(Math.min(2, out.sizes - 1)).click();
  await page.waitForTimeout(600);
  out.buyAfterPick = (await page.locator('[data-crk-buy]').first().textContent()).trim().replace(/\s+/g, ' ');
  out.variantId = await page.locator('[data-crk-variant-id]').first().inputValue().catch(() => null);
  out.urlAfterPick = page.url().replace(B, '');
  await page.locator('[data-crk-buy]').first().click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/pdp-added.png` });
  out.cart = await page.evaluate(async () => { const c = await (await fetch('/cart.js')).json(); return { count: c.item_count, items: c.items.map((i) => i.title + ' x' + i.quantity), total: c.total_price }; });
  out.recommendations = await page.evaluate(() => document.querySelectorAll('product-recommendations, [class*="recommend"] a[href*="/products/"], [class*="related"] a[href*="/products/"]').length);
  return out;
});
await visit('cart', '/cart', async () => ({
  rows: await page.evaluate(() => document.querySelectorAll('[class*="cart-item"], .cart-items__table-row, tr.cart-items__table-row').length),
  checkout: await page.locator('button[name="checkout"], [name="checkout"]').count(),
  text: await page.evaluate(() => document.querySelector('main') && document.querySelector('main').innerText.replace(/\s+/g, ' ').slice(0, 220)),
}));
await visit('search', '/search?q=jeans', async () => ({ results: await page.locator('main a[href*="/products/"]').count() }));
await visit('search-empty', '/search', null);
await visit('tracking', '/pages/tracking', async () => ({ inputs: await page.locator('main input, .crk-track input').count() }));
await visit('faq', '/pages/faq', null);
fs.writeFileSync(`${OUT}/report${ONLY.length ? '-' + ONLY.join('-') : ''}.json`, JSON.stringify(report, null, 1));
await browser.close();
