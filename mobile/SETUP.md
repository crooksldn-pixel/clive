# CROOKSLDN app — setup

The app is built. What's left needs your accounts and your card. Everything
here is a one-off; after it, shipping an update is two commands.

## What the app does

| | |
|---|---|
| **Shop** | The live catalogue from Shopify. Category filters come from product types, sets are hidden (same as the website), sold out says so. |
| **Product** | Photos, price, every option labelled (Colour *and* Size on tees), sold-out sizes struck corner to corner, nothing pre-selected, one big "Add to bag — £25". |
| **Bag** | Change quantities, remove, subtotal. The bag is kept by Shopify, so it survives closing the app. |
| **Checkout** | Shopify's real checkout — Apple Pay, Shop Pay, discount codes, your checkout branding — slides up over the app. Nobody leaves the app to pay. |
| **Orders** | Orders placed in the app, "Track an order" (your AfterShip page), sign-in for full history, Contact/FAQ/Terms. |
| **Push** | After an order: "Want a notification when it ships?". Then: *On its way* (with the carrier's tracking link), *Out for delivery*, *Delivered*. Separately, opt-in **drop alerts** you send yourself. |

It reads the shop live. Add a product, change a price or sell out in Shopify
admin and the app shows it — no app update needed.

## What it costs

| | |
|---|---|
| Apple Developer Program | $99 / year (about £79) — needed for the App Store and iPhone push |
| Google Play Console | $25 once |
| Expo (builds the app in the cloud) | free plan is enough |
| Cloudflare (runs the push service) | free plan is enough |

---

## 1. Sign up (do these first — Apple takes a day or two to approve)

1. **Apple:** https://developer.apple.com/programs/enroll — enrol as an
   **organisation** (Crooks Clothing Company Ltd) so the App Store shows the
   company, not your name. You need the company's D-U-N-S number; Apple looks
   it up for you if you don't have it.
2. **Google:** https://play.google.com/console/signup — also as an
   organisation.
3. **Expo:** https://expo.dev/signup
4. **Cloudflare:** https://dash.cloudflare.com/sign-up

## 2. Get the code on your Mac

```bash
cd ~/Shopify-theme
git pull
cd mobile
npm install
```

You need Node 22 or newer (`node -v`). If it says 20, install 22 from
https://nodejs.org first.

## 3. Connect the app to your Expo account

```bash
npx eas-cli@latest login
npx eas-cli@latest init
```

`init` writes a project id into `app.json`. Commit that change.

## 4. Turn on the push service (about 10 minutes)

```bash
cd push-service
npm install
npx wrangler login
npx wrangler kv namespace create PUSH
```

The last command prints an `id`. Open `push-service/wrangler.toml` and paste
it over `REPLACE_WITH_KV_NAMESPACE_ID`. Then:

```bash
npx wrangler deploy
```

It prints your service's address, like
`https://crooksldn-push.<your-name>.workers.dev`. Keep it — it's used twice
below.

**Make the drop-alert password.** Any long random string; this makes one:

```bash
openssl rand -hex 24
```

Save it in your password manager, then:

```bash
npx wrangler secret put BROADCAST_SECRET
```

(paste it when asked).

**Tell Shopify to report orders and shipments.** In Shopify admin:
**Settings → Notifications → Webhooks → Create webhook**, three times:

| Event | Format | URL |
|---|---|---|
| Order creation | JSON | `https://crooksldn-push.<your-name>.workers.dev/v1/shopify/webhooks` |
| Fulfillment creation | JSON | same |
| Fulfillment update | JSON | same |

Under the list Shopify shows *"Your webhooks will be signed with …"*. Copy
that key, then:

```bash
npx wrangler secret put SHOPIFY_WEBHOOK_SECRET
```

(paste it when asked).

**Tell the app where the service is:**

```bash
cd ..
npx eas-cli@latest env:set --name EXPO_PUBLIC_PUSH_API_URL --value https://crooksldn-push.<your-name>.workers.dev --environment preview --environment production --visibility plaintext
```

Until this step is done the app simply never offers notifications — it
won't promise an update that nobody will send.

## 5. Android push (Firebase — about 5 minutes)

1. https://console.firebase.google.com → **Add project** → name it CROOKSLDN
   (Analytics can be off).
2. **Add app → Android**, package name `com.crooksldn.app`. Download
   `google-services.json` into the `mobile` folder.
3. ```bash
   npx eas-cli@latest env:set --name GOOGLE_SERVICES_JSON --type file --value ./google-services.json --environment preview --environment production --visibility secret
   ```
4. In Firebase: **Project settings → Service accounts → Generate new private
   key**. Then run `npx eas-cli@latest credentials`, choose **Android →
   production → Google Service Account → Push Notifications (FCM V1)** and
   give it that file.

iPhone push needs nothing here — the first iOS build sets it up (step 6).

## 6. Build and install

**iPhone (TestFlight):**

```bash
npx eas-cli@latest build --platform ios --profile production
```

Sign in with your Apple account when asked. When it asks **"set up Push
Notifications?" → yes**. When the build finishes:

```bash
npx eas-cli@latest submit --platform ios
```

About 15 minutes later it's in **TestFlight** on your phone (install the
TestFlight app). Send it to friends from App Store Connect → TestFlight.

**Android (straight to your phone):**

```bash
npx eas-cli@latest build --platform android --profile preview
```

It gives you a link; open it on the phone to install.

## 7. Test the whole loop once

1. On your phone: add something cheap (socks) → Checkout → pay.
2. When the thank-you page closes, tap **Notify me** → Allow.
3. In Shopify admin, fulfil that order with a tracking number.
4. Within a minute: **"On its way"**. Tap it — it opens the tracking page.
5. Refund and cancel the order in admin.

To watch it happen live: `cd push-service && npx wrangler tail`. You should
see `claim … confirmed` after step 2 and `fulfillment … shipped sent` after
step 3. If the claim stays `pending`, send me the `wrangler tail` output —
it means Shopify's order id and the checkout's id didn't line up and I'll
adjust the matching.

## 8. Publish

**App Store** (App Store Connect → your app):
- Screenshots: take them on your phone from the TestFlight build.
- Privacy policy URL: `https://crooksldn.com/policies/privacy-policy`
- App Privacy: *Identifiers → Device ID* (the push token), used for *App
  Functionality*, **not** linked to identity, **not** used for tracking.
  Purchases happen in Shopify's checkout under Shopify's own disclosures.
- Category: Shopping.
- Submit for review. First review is usually 1–3 days.

**Google Play:** build with `--profile production`. Google insists the very
first upload is done by hand: Play Console → create app → **Internal
testing → Create release** → upload the `.aab` from the build page. After
that, `npx eas-cli@latest submit --platform android` does it for you.

## Sending a drop alert

Goes to everyone who switched **Drop alerts** on in the Orders tab.

```bash
curl -X POST https://crooksldn-push.<your-name>.workers.dev/v1/broadcast \
  -H "Authorization: Bearer YOUR_DROP_ALERT_PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"title":"Drop 02 is live","body":"Pink set is back in every size.","path":"/products/pink-crsdr-hoodie"}'
```

- `title` up to 60 characters, `body` up to 180.
- `path` is where a tap lands: `/` for the catalogue, `/products/<handle>`
  for a product (the handle is the end of its website address).
- It replies with how many it reached.

Treat it like a text to your best customers: drops only. People who get
spammed switch notifications off for good.

## Optional: size charts in the app

Shopify only shares size charts (and product subtitles) with apps that have
a Storefront token. Without one the app works fully but the product page has
no measurements table.

Shopify admin → **Sales channels → Add "Headless"** → **Create storefront** →
copy the **public access token**, then:

```bash
npx eas-cli@latest env:set --name EXPO_PUBLIC_SHOPIFY_STOREFRONT_TOKEN --value THE_TOKEN --environment preview --environment production --visibility plaintext
```

and rebuild. The public token is designed to ship inside apps; it can only
read what the website already shows. (Do **not** use an Admin API token —
`shpat_…` — anywhere near the app.)

## Shipping an update later

```bash
npx eas-cli@latest build --platform all --profile production
npx eas-cli@latest submit --platform all
```

Product, price and stock changes never need this — the app reads Shopify
live.

---

## For a developer

```
mobile/
  src/app/            screens (Expo Router): (tabs)/index, bag, orders; products/[handle]
  src/components/     design system — tokens in src/theme/tokens.ts mirror crooks.css
  src/lib/            Storefront API client, cart, variants, checkout, push
  src/state/          bag + order history
  scripts/verify-api.ts   runs the real client against the live store
  push-service/       Cloudflare Worker (+ tests)
```

| Check | Command |
|---|---|
| Types | `npx tsc --noEmit` |
| Lint | `npx expo lint` |
| Live store API | `npm run verify:api` |
| Push service tests | `cd push-service && npm test` |
| Config health | `npx expo-doctor` |
| Run in a browser | `npx expo start --web` |

- Expo SDK 57, React Native 0.86, New Architecture. Native projects are
  generated by EAS (`ios/`, `android/` are not in git — never hand-edit).
- Checkout Kit is native: in Expo Go the app falls back to the system
  browser for checkout (order still completes; it's inferred from the cart
  disappearing). Push and the in-app checkout sheet need a real build.
- `.shopifyignore` at the repo root keeps `mobile/` out of
  `shopify theme push`.
- Storefront API `2026-07`, tokenless; `EXPO_PUBLIC_SHOPIFY_STOREFRONT_TOKEN`
  switches on metafields with no code change.
- Push privacy: the worker stores install ids, Expo push tokens and numeric
  order ids only. An order can be claimed by the first install to ask, and
  only while Shopify's `orders/create` for it is under six hours old.
