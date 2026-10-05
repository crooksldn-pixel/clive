// Browser walk of every admin state against the seeded dev server, with assertions.
//
//   cd clive-shipping && python scripts/dev_server.py 8120 &      # seeded fixture store
//   python scripts/dev_server.py 8121 --empty &                    # (optional) empty state
//   NODE_PATH=$(npm root -g) node scripts/ui_walk.cjs [OUT_DIR]
//
// Uses the dev server's /dev controls (order edits, charge count). Screenshots go to OUT_DIR
// (default /tmp/playwright-mcp/shipping-walk). Exits non-zero on the first failed check.
// Outside Shopify admin App Bridge logs "missing required configuration fields: shop" and a
// refused stale buy logs one 409; any other console error fails the walk.

const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.env.SHIPPING_DEV || "http://127.0.0.1:8120";
const EMPTY = process.env.SHIPPING_DEV_EMPTY || "http://127.0.0.1:8121";
const OUT = process.argv[2] || "/tmp/playwright-mcp/shipping-walk";
const PRIMARY = 's-page > s-button[slot="primary-action"]';

function check(ok, what) {
  if (!ok) { console.error(`FAIL: ${what}`); process.exit(1); }
  console.log(`ok   ${what}`);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch(
    fs.existsSync("/opt/pw-browsers/chromium") ? { executablePath: "/opt/pw-browsers/chromium" } : {});
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => {
    const t = `${m.text()} @ ${m.location()?.url || ""}`;
    if (m.type() === "error" && !/App Bridge Next|favicon|status of 409/.test(t)) errors.push(t);
    if (m.type() === "warning" && /polaris/i.test(t)) errors.push(t);
  });
  page.on("pageerror", (e) => { if (!/App Bridge Next/.test(String(e))) errors.push(String(e)); });

  const shot = async (name) => { await page.waitForTimeout(400); await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }); };
  // Visible text plus component headings (s-section/s-banner render them in shadow DOM).
  const text = () => page.evaluate(() => document.body.innerText + "\n" +
    [...document.querySelectorAll("[heading]")].map((e) => e.getAttribute("heading")).join("\n"));
  const badges = () => page.evaluate(() => [...document.querySelectorAll("s-badge")].map((b) => b.textContent.trim()));
  const charges = async () => (await (await page.request.get(`${BASE}/dev/charges`)).json()).charges;
  const open = async (order) => {
    await page.goto(`${BASE}/admin`); await page.waitForTimeout(700);
    await page.getByText(order, { exact: true }).click(); await page.waitForTimeout(900);
  };

  // Inbox
  await page.goto(`${BASE}/admin`); await page.waitForTimeout(900);
  const inbox = await text();
  for (const phrase of ["Needs attention", "Ready to ship", "Labels bought", "3 details needed",
    "Address needs attention", "No available service", "Provider unavailable",
    "Purchase requires reconciliation", "Label purchased — Shopify update needs retry"]) {
    check(inbox.includes(phrase), `inbox shows "${phrase}"`);
  }
  check(!/gid:\/\/|b1_|fake:/.test(inbox), "inbox shows no provider ids or hashes");
  await shot("01-inbox");

  // Needs attention → answered in place → ready
  await open("CROOKS-2146");
  check((await badges())[0] === "3 details needed", "2146 asks for three details");
  await shot("02-needs-attention");
  await page.evaluate(() => { document.getElementById("q0-grams").value = "650"; });
  await page.locator('s-button[data-action="answer"][data-q="0"]').click(); await page.waitForTimeout(900);
  await page.evaluate(() => { document.getElementById("q0-hs").value = "6110.20"; document.getElementById("q0-desc").value = "Men's cotton hoodie"; });
  await page.locator('s-button[data-action="answer"][data-q="0"]').click(); await page.waitForTimeout(900);
  await page.evaluate(() => { document.getElementById("q0-country").value = "PT"; });
  await page.locator('s-button[data-action="answer"][data-q="0"]').click(); await page.waitForTimeout(1000);
  check((await badges())[0] === "Ready", "2146 is ready once answered");
  await shot("03-customs-confirmed");

  // Buy with a double click: one charge
  await open("CROOKS-2145");
  check((await page.locator(PRIMARY).textContent()).startsWith("Buy label — £"), "ready order offers Buy label — £X");
  const before = await charges();
  await page.locator(PRIMARY).click(); await page.waitForTimeout(1000);
  await shot("04-preview");
  await page.locator("s-button#buy-button").dblclick(); await page.waitForTimeout(1500);
  check(await charges() === before + 1, "a double click on Buy charges once");
  check((await badges())[0] === "Fulfilled", "bought label is fulfilled in Shopify");
  check((await text()).includes("Electronic ✓"), "paperless customs shows Electronic ✓");
  await shot("05-purchase-success");

  // Print and reprint: stored file, no charge
  const [tab] = await Promise.all([context.waitForEvent("page"), page.locator(PRIMARY).click()]);
  await tab.waitForTimeout(1200); check(tab.url().startsWith("blob:"), "print opens the stored label"); await tab.close();
  await page.waitForTimeout(500);
  check((await page.locator(PRIMARY).textContent()).startsWith("Reprint"), "second print is a reprint");
  const [tab2] = await Promise.all([context.waitForEvent("page"), page.locator(PRIMARY).click()]);
  await tab2.waitForTimeout(800); await tab2.close();
  check(await charges() === before + 1, "print and reprint charge nothing");
  await shot("06-reprinted");

  // Paper customs
  await open("CROOKS-2149");
  check((await text()).includes("Customs paperwork required — Commercial invoice — 3 copies — A4"), "paper customs spelled out");
  await shot("07-paper");

  // Shopify failed after purchase → retry Shopify only
  await open("CROOKS-2150");
  const c2 = await charges();
  check((await page.locator(PRIMARY).textContent()) === "Retry Shopify update", "Shopify failure offers Retry Shopify update");
  await shot("08-shopify-failure");
  await page.locator(PRIMARY).click(); await page.waitForTimeout(1200);
  check((await badges())[0] === "Fulfilled" && await charges() === c2, "retry fixes Shopify without buying");
  await shot("09-shopify-retried");

  // Uncertain purchase: no buy, no service change
  await open("CROOKS-2151");
  check(await page.locator(PRIMARY).count() === 0, "uncertain purchase offers no buy");
  check(await page.locator('[data-action="choose"]').count() === 0, "uncertain purchase offers no service change");
  await shot("10-uncertain");

  for (const [order, phrase, name] of [["CROOKS-2153", "Provider unavailable", "11-provider-outage"],
    ["CROOKS-2152", "No available service", "12-no-service"], ["CROOKS-2147", "Address needs attention", "13-address"]]) {
    await open(order);
    check((await badges())[0] === phrase, `${order} says "${phrase}"`);
    await shot(name);
  }

  // Stale preview
  await open("CROOKS-2154");
  await page.locator(PRIMARY).click(); await page.waitForTimeout(1000);
  await page.request.post(`${BASE}/dev/order/2154/quantity?value=3`);
  const c3 = await charges();
  await page.locator("s-button#buy-button").click(); await page.waitForTimeout(1500);
  check(await page.evaluate(() => document.querySelector("s-banner")?.getAttribute("heading")) === "Order changed — refresh required", "stale preview refused in words");
  check(await charges() === c3, "stale preview bought nothing");
  await shot("14-stale");
  await page.locator('s-banner s-button[data-action="refresh"]').click(); await page.waitForTimeout(1200);
  check((await text()).includes("3 items"), "refresh shows the changed order");

  // Print all ready labels
  await page.goto(`${BASE}/admin`); await page.waitForTimeout(800);
  if (await page.locator(PRIMARY).count()) {
    const opened = [];
    context.on("page", (p) => opened.push(p));
    await page.locator(PRIMARY).click(); await page.waitForTimeout(3000);
    check(opened.length > 0, `print all opened ${opened.length} documents`);
    for (const p of opened) await p.close();
    check(await page.locator(PRIMARY).count() === 0, "nothing left to print");
  }
  await shot("15-printed-all");

  await page.goto(`${BASE}/admin?view=setup`); await page.waitForTimeout(900);
  check((await text()).includes("4×6"), "setup shows the 4×6 format");
  await shot("16-setup");

  try {
    await page.goto(`${EMPTY}/admin`); await page.waitForTimeout(900);
    check((await text()).includes("No international orders waiting"), "empty state");
    await shot("17-empty");
  } catch (e) { console.log("skip empty state (no server on " + EMPTY + ")"); }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE}/admin`); await page.waitForTimeout(900);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check(!overflow, "no sideways scroll at 390 px");
  await shot("18-mobile");

  check(errors.length === 0, `no unexpected console errors or Polaris warnings${errors.length ? ": " + errors.join(" | ") : ""}`);
  await browser.close();
})();
