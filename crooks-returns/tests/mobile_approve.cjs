// Approve a pending return on a phone-sized screen, by touch, as a person would.
// Usage: node mobile_approve.cjs BASE_URL HEIGHT   (prints one JSON line of findings)
const { chromium, devices } = require("playwright");

(async () => {
  const base = process.argv[2];
  const H = Number(process.argv[3] || 560);
  const browser = await chromium.launch(
    process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}
  );
  // iPhone SE in Shopify's mobile app: the frame is shorter than the phone.
  const ctx = await browser.newContext({ ...devices["iPhone SE"], viewport: { width: 375, height: H } });
  const page = await ctx.newPage();
  const posts = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname); });
  const out = {};
  // A person scrolls the page to what they want, then taps it.
  const tapCentre = async (loc) => {
    await loc.scrollIntoViewIfNeeded();
    const b = await loc.boundingBox();
    await page.touchscreen.tap(b.x + b.width / 2, b.y + b.height / 2);
  };
  // The first price check is slow (as on a phone signal), so its wait can be seen.
  let slowed = false;
  await page.route("**/approve/preview", async (route) => {
    if (!slowed) { slowed = true; await new Promise((r) => setTimeout(r, 1500)); }
    await route.continue();
  });
  try {
    await page.goto(`${base}/apps/returns/admin`);
    await tapCentre(page.locator("li.row", { hasText: "Needs approval" }).first());
    const approve = page.getByRole("button", { name: "Approve", exact: true }).first();
    await approve.waitFor();
    out.detail_button_height = Math.round((await approve.boundingBox()).height);
    await tapCentre(approve);
    // The tallest form: buy a label now, with its price check.
    const label = page.getByRole("radio", { name: /Book a return label now/ });
    if (await label.isEnabled()) await tapCentre(label);
    const go = page.locator(".scrim #go");
    out.disabled_while_checking = await go.isDisabled();
    out.why_while_checking = (await page.locator("#why").textContent({ timeout: 1000 }).catch(() => "")) || "";
    await page.waitForFunction(() => !document.querySelector(".scrim #go")?.disabled, null, { timeout: 10000 });
    const box = await go.boundingBox();
    out.dialog_approve_bottom = Math.round(box.y + box.height);
    out.viewport_height = H;
    out.dialog_approve_on_screen = box.y >= 0 && box.y + box.height <= H;
    out.dialog_approve_height = Math.round(box.height);
    out.hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("button")?.id || null,
      [box.x + box.width / 2, box.y + box.height / 2]);
    // A double tap: the second must never do it again.
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForFunction(() => !document.querySelector(".scrim"), null, { timeout: 10000 });
    out.dialog_closed = true;
    out.status_shown = (await page.locator(".badge").first().textContent()) || "";
  } catch (e) {
    out.error = String(e && e.message || e).slice(0, 300);
  }
  out.approve_posts = posts.filter((p) => /\/approve$/.test(p)).length;
  out.preview_posts = posts.filter((p) => /\/approve\/preview$/.test(p)).length;
  console.log(JSON.stringify(out));
  await browser.close();
})();
