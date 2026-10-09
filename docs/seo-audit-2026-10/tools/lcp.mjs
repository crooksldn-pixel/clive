import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const pw = require(require('child_process').execSync('npm root -g').toString().trim() + '/playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const [SP, outFile, ...urls] = process.argv.slice(2);
const browser = await pw.chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
const CJ = process.env.CJ || (SP + '/harness/cj-lcp'); let n = 0; fs.mkdirSync(SP + '/harness/net2', { recursive: true });
await ctx.route('**/*', async (route) => {
  const req = route.request(), u = req.url();
  if (u.startsWith('data:') || u.startsWith('blob:')) return route.continue();
  if (/monorail|trekkie|web-pixels|analytics|google|facebook|tiktok|klaviyo|shop\.app|captcha|mida|clients2|api\/collect|bugsnag/.test(u)) return route.abort();
  const f = `${SP}/harness/net2/${n++}`;
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
  // Shopify's cookie banner is text-heavy and can win LCP; hide it so the page's own content is measured.
  document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '#shopify-pc__banner{display:none!important}'; document.head.appendChild(st); });
  window.__lcp = null;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e; }).observe({ type: 'largest-contentful-paint', buffered: true });
});
const out = [];
for (const url of urls) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(2500);
    const r = await page.evaluate(() => {
      const e = window.__lcp; if (!e) return null; const el = e.element;
      return { tag: el && el.tagName, src: el && (el.currentSrc || el.src || '').slice(-90), loading: el && el.getAttribute && el.getAttribute('loading'), fetchpriority: el && el.getAttribute && el.getAttribute('fetchpriority'), size: e.size, text: el && el.tagName !== 'IMG' ? (el.textContent || '').trim().slice(0, 40) : '' };
    });
    out.push({ url, lcp: r });
  } catch (e) { out.push({ url, error: String(e).slice(0, 120) }); }
  await page.close();
}
fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1));
await browser.close();
