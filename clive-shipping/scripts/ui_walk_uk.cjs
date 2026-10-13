// Browser walk of the UK (Shopify Shipping) states against the dev server, with assertions.
//
//   cd clive-shipping && python scripts/dev_server.py 8122 --domestic &
//   NODE_PATH=$(npm root -g) node scripts/ui_walk_uk.cjs [OUT_DIR]
//
// Desktop (1280 px) and phone (390 px). Screenshots go to OUT_DIR (default
// /tmp/playwright-mcp/shipping-uk). Outside Shopify admin App Bridge logs "missing required
// configuration fields: shop" and a favicon 404; any other console error fails the walk.

const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.env.SHIPPING_DEV || "http://127.0.0.1:8122";
const OUT = process.argv[2] || "/tmp/playwright-mcp/shipping-uk";
const PRIMARY = 's-page > s-button[slot="primary-action"]';

function check(ok, what) {
  if (!ok) { console.error(`FAIL: ${what}`); process.exit(1); }
  console.log(`ok   ${what}`);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch(
    fs.existsSync("/opt/pw-browsers/chromium") ? { executablePath: "/opt/pw-browsers/chromium" } : {});
  const errors = [];
  const watch = (page) => {
    page.on("console", (m) => {
      const t = m.text();
      if (m.type() === "error" && !/missing required configuration fields: shop|favicon|status of 404/.test(t)) errors.push(t);
    });
    page.on("pageerror", (e) => {
      if (!/missing required configuration fields: shop/.test(String(e))) errors.push(String(e));
    });
  };
  const desktop = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await desktop.newPage();
  watch(page);
  const shot = (name, p = page) => p.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  const text = (p = page) => p.evaluate(() => document.body.innerText + "\n" +
    [...document.querySelectorAll("[heading]")].map((e) => e.getAttribute("heading")).join("\n"));
  const badges = (p = page) => p.evaluate(() => [...document.querySelectorAll("s-badge")].map((b) => b.textContent.trim()));
  const counts = async () => (await (await page.request.get(`${BASE}/dev/charges`)).json());
  const rows = async () => (await (await page.request.get(`${BASE}/admin/api/inbox?stage=all`)).json()).rows;
  const id = async (order) => (await rows()).find((r) => r.order === order).id;
  const open = async (order, p = page) => {
    await p.goto(`${BASE}/admin?shipment=${await id(order)}`); await p.waitForTimeout(1000);
  };

  // Inbox: the page is "Shipping", UK rows name the service and Shopify Shipping, no price.
  await page.goto(`${BASE}/admin?stage=ready`); await page.waitForTimeout(1000);
  let t = await text();
  check(t.includes("Shipping") && !t.includes("International shipping"), "inbox heading is Shipping");
  check(t.includes("Royal Mail Tracked 24 · Shopify Shipping"), "ready UK row names service and seller");
  check(t.includes("DPD · £10.69"), "international rows keep their price");
  await shot("01-ready-tab");

  // A ready UK order: service from checkout, no customs, Buy label with no amount.
  await open("CROOKS-3001");
  t = await text();
  check(t.includes("Royal Mail Tracked 24 · via Shopify Shipping"), "3001 shows service and seller");
  check(t.includes("Shopify Shipping sets the price when the label is bought"), "3001 says who prices it");
  check(t.includes("From the checkout delivery method “Tracked 24”"), "3001 says where the service came from");
  check(t.includes("No customs (UK parcel)") && !t.includes("Review"), "3001 has no customs");
  check(!t.includes("Edit product customs"), "3001 offers no customs editing");
  check((await page.locator(PRIMARY).textContent()).trim() === "Buy label", "primary is Buy label, no price");
  await shot("02-uk-ready");

  // Preview, then a double click: one Shopify Shipping purchase.
  const before = await counts();
  await page.locator(PRIMARY).click(); await page.waitForTimeout(1200);
  t = await text();
  check(t.includes("Buy Royal Mail Tracked 24 from Shopify Shipping"), "preview names the service");
  check(t.includes("The price is set by Shopify Shipping when the label is bought"), "preview says no price before buying");
  check(t.includes("Shopify bill"), "preview says how it's charged");
  check((await page.locator("s-button#buy-button").textContent()).trim() === "Buy label", "modal button has no made-up price");
  await shot("03-uk-preview");
  await page.locator("s-button#buy-button").dblclick(); await page.waitForTimeout(2500);
  const after = await counts();
  check(after.shopify_shipping_mutations === before.shopify_shipping_mutations + 1, "double click sent one purchase");
  t = await text();
  check(t.includes("Label purchased") && t.includes("Price set by Shopify Shipping"), "label section names no amount");
  check(/RM\d+GB/.test(t), "tracking number shown");
  check(t.includes("4×6 label printer"), "the stored label is a 4x6 label");
  await shot("04-uk-bought");

  // An unmapped checkout line: Which service? answered for this order only.
  await page.goto(`${BASE}/admin?stage=attention`); await page.waitForTimeout(1000);
  check((await text()).includes("Which service?"), "attention tab says Which service?");
  await open("CROOKS-3003");
  t = await text();
  check(t.includes("Which service: Tracked 24 or Tracked 48?") && t.includes("“Next day by 1pm”"), "3003 asks which service and why");
  await shot("05-which-service");
  await page.locator('s-button[data-action="answer"][data-service="tracked_48"]').click(); await page.waitForTimeout(1500);
  t = await text();
  check((await badges())[0] === "Ready", "3003 ready once a person chose");
  check(t.includes("Chosen for this order by"), "3003 says who chose");
  await shot("06-service-chosen");

  // A label Shopify gave as US Letter: said, never scaled.
  await open("CROOKS-3006");
  t = await text();
  check(t.includes("Shopify's label file is US Letter, not 4×6") && t.includes("isn't scaled"), "3006 says the file is Letter");
  await shot("07-letter-label");

  // A label found on the order after a lost reply: no file, says where to print it.
  await open("CROOKS-3007");
  t = await text();
  check(t.includes("Print it from the order in Shopify admin"), "3007 says where to print it");
  check(await page.locator(PRIMARY).count() === 0, "3007 offers no Print that can't work");
  await shot("08-adopted");

  // Still being bought: no buy button, the reconciliation banner.
  await open("CROOKS-3008");
  check((await badges())[0] === "Purchase requires reconciliation", "3008 is being checked");
  check(await page.locator(PRIMARY).count() === 0, "3008 offers no buy");
  await shot("09-pending");

  // Shopify said another purchase was running: a person checks Shopify, then allows buying.
  await open("CROOKS-3014");
  t = await text();
  check((await badges())[0] === "Check Shopify for a label", "3014 waits for a person to check Shopify");
  check(await page.locator(PRIMARY).count() === 0, "3014 offers no buy meanwhile");
  await shot("09b-label-check");
  await page.locator('s-button[data-action="answer"]').click(); await page.waitForTimeout(1500);
  check((await badges())[0] === "Ready", "3014 ready once a person checked");

  // International unchanged: price on the button, customs with Review.
  await open("CROOKS-2145");
  t = await text();
  check((await page.locator(PRIMARY).textContent()).startsWith("Buy label — £"), "2145 still offers Buy label — £X");
  check(t.includes("Customs") && !t.includes("No customs (UK parcel)"), "2145 keeps customs");
  await shot("10-international");

  // Bulk review mixing a UK and an international label.
  await page.goto(`${BASE}/admin?stage=ready`); await page.waitForTimeout(1000);
  for (const order of ["CROOKS-3002", "CROOKS-2145"]) {
    await page.locator(`input[data-select="${await id(order)}"]`).check();
  }
  await page.waitForTimeout(300);
  await page.locator('s-button[data-action="bulk-buy"]').click(); await page.waitForTimeout(1500);
  t = await text();
  check(t.includes("Set by Shopify Shipping"), "bulk review: UK row has no amount");
  check(t.includes("£10.69 + 1 UK label priced by Shopify Shipping"), "bulk total says the UK label isn't in it");
  await shot("11-bulk-review");

  // Phone: inbox list and a UK order.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  const mp = await phone.newPage();
  watch(mp);
  await mp.goto(`${BASE}/admin?stage=ready`); await mp.waitForTimeout(1200);
  const wide = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(wide <= 1, "phone inbox has no sideways scroll");
  check((await text(mp)).includes("Royal Mail Tracked 48 · Shopify Shipping"), "phone inbox shows the UK row");
  await shot("12-phone-inbox", mp);
  await open("CROOKS-3002", mp);
  const wide2 = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(wide2 <= 1, "phone detail has no sideways scroll");
  check((await text(mp)).includes("Shopify Shipping sets the price"), "phone detail says who prices it");
  await shot("13-phone-uk-detail", mp);

  check(errors.length === 0, `no unexpected console errors${errors.length ? ": " + errors.join(" | ") : ""}`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
