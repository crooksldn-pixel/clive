# Prompt for the Base44 builder

The backend functions in this folder do the Shopify work. A few screens in the
Partner Hub need to change to use them properly. Paste the prompt below into
the Base44 AI chat for **crooks-partner-hub** in one go. It doesn't touch the
backend functions.

Do this **after** deploying the functions and **before** pressing SYNC for the
first time. The first sync marks the old test order CROOKS-1869 as
`cancelled`, and until step 7 is in, the influencer portal shows any status it
doesn't know as "Overdue".

---

```text
The backend functions shopifyCreateSend, shopifySyncCatalog, shopifySyncTracking,
shopifySyncUsage, sendMarkShipped, shopifyCheckConnection, shopifyWebhook,
portalCheckAvailable and partnerApi are maintained outside the builder. Do NOT
create, edit, regenerate or delete any of them, and do not call Shopify from the
frontend. Only make the frontend and entity changes below. Keep the existing
look (purple #542578, font-heading, square corners, small uppercase labels).

1. ENTITIES. Add these optional fields; do not remove or rename existing fields.
   - Send: influencerEmail (string), shopifyOrderUrl (string), trackingUrl
     (string), deliveredAt (string, date-time), cancelledAt (string, date-time),
     retailValueGbp (number), createdByEmail (string), lastSyncedAt (string,
     date-time). Status may also be "cancelled". Each entry of items may also
     have variantId, quantity, sku and components.
   - Product: shopifyProductId (string), shopifyStatus (string), syncedAt
     (string, date-time). Each entry of variants may also have price, sku,
     tracked and isBundle. type may also be "outerwear".

2. ADMIN > INFLUENCER PAGE > "CREATE SEND" DIALOG. Rebuild it:
   - List every product the influencer flagged (their Interest records), not
     only in-stock ones. Each row has a variant dropdown built from the
     product's variants, showing "<variant label> · <stock> left". Default to the
     interest's variantId if that variant exists, otherwise the first in-stock
     variant whose size equals the interest's size. Variants with 0 stock are
     disabled; if none are available the row is greyed out with "Out of stock".
   - Each row has a checkbox and a quantity selector (1 to 10, default 1).
   - Below the rows, an "ADD ANOTHER ITEM" picker listing every Product (also
     ones hidden from influencers) and its variants with stock, to add rows.
   - An optional "Note for the order" text field.
   - The button "CREATE SHOPIFY ORDER (n)" calls
     base44.functions.invoke("shopifyCreateSend", {
       influencerId,
       items: checkedRows.map(r => ({ variantId: r.variantId, quantity: r.quantity, name: r.productName, size: r.variantLabel })),
       note
     })
   - On success: "Shopify order <orderName> created." with orderName linking to
     response.data.orderAdminUrl (new tab). Show each of response.data.warnings
     as a small note. If response.data.duplicate is true, say "This order already
     existed — no second order was created." Keep locking the address for 14
     days after success, exactly as now.
   - On failure: show error.response.data.error. If
     error.response.data.details.problems exists, also show each problem's
     message on the row whose variantId matches (problems for pieces of a set
     match the set's row by name; otherwise show them under the error).

3. ADMIN > INFLUENCER PAGE > SEND HISTORY:
   - The Order cell links to send.shopifyOrderUrl when it exists (new tab).
   - The Tracking cell links to send.trackingUrl when it exists, otherwise use
     the existing carrier link.
   - Status "cancelled" shows as "Cancelled" in grey.
   - Rows with status "preparing" and a shopifyOrderName get a "MARK SHIPPED"
     button. It opens a small form: Carrier (select: Royal Mail, DPD, Evri,
     Parcelforce, DHL, Other with a text box), Tracking number, optional
     Tracking link. Submit calls
     base44.functions.invoke("sendMarkShipped", { sendId, carrier, trackingNumber, trackingUrl })
     then reloads the page data. On failure show error.response.data.error.
     Add a hint: "Buying the label in Shopify fills this in automatically."
   - Rows with status dispatched, delivered or overdue get a "RECORD POST"
     button asking for the post's URL; save with
     base44.entities.Send.update(send.id, { postedUrl, postedAt: new Date().toISOString(), status: "posted" }).

4. ADMIN > INFLUENCER PAGE HEADER: under the username, show the TikTok and
   Instagram handles as links to their profiles (use profileUrl, or
   https://www.tiktok.com/@<handle> and https://www.instagram.com/<handle>/ when
   profileUrl is empty). Keep the existing profile buttons.

5. ADMIN > INFLUENCERS LIST: make the "TT" and "IG" markers links to the
   profiles (open in a new tab and stop the click from opening the row). Under
   the TikTok handle, also link it. Add a "Last send" column showing the most
   recent send's status and order name.

6. ADMIN HEADER BUTTONS:
   - The existing SYNC button keeps calling shopifySyncCatalog,
     shopifySyncUsage and shopifySyncTracking in that order, but runs all three
     even if one fails, then shows a short summary instead of reloading
     straight away, e.g. "Catalogue: 25 products (2 new, 1 hidden) · Tracking: 3
     updated · Codes: 4 updated", plus any error messages
     (error.response.data.error). Then refresh the page data.
   - Add a "CHECK SHOPIFY" button calling
     base44.functions.invoke("shopifyCheckConnection", { registerWebhooks: true })
     and show the result in a dialog: shop.name, auth, apiVersion,
     scopes.missing (each scope and its "why"), each webhooks entry (topic +
     status), partnerApi, partnerApiWrites, and warnings. Green tick if ok is
     true.

7. INFLUENCER PORTAL > MY SENDS: status "cancelled" shows "Cancelled" (today
   any unknown status shows "Overdue"). Hide cancelled sends older than 30
   days. The tracking link uses trackingUrl when it exists.

8. INFLUENCER PORTAL > CONNECT INSTAGRAM: remove the fake connection that makes
   up followers, media count and a pravatar.cc avatar with Math.random. Replace
   it with an "Instagram username" field that saves a SocialAccount with
   platform "instagram", handle, profileUrl https://www.instagram.com/<handle>/
   and connectedAt, leaving followers, likes and mediaCount empty. Wherever
   follower counts are shown, show "—" when empty.

9. INFLUENCER PORTAL > PRODUCTS: add an "Outerwear" filter chip for products
   whose type is "outerwear".

10. SECURITY. Right now every entity can be read by anyone on the internet
    without signing in. Set row level security:
    - Influencer, Address, SizeProfile, SocialAccount, Interest, AffiliateCode:
      signed-in users can read and update only records they created; admins can
      read and write everything; signed-out visitors can read nothing.
    - Send: admins can read and write everything; a signed-in user can read
      only sends whose influencerEmail equals their own email; only admins can
      create, update or delete.
    - Product: any signed-in user can read; only admins can write.
    Because influencers can no longer read each other's records, change:
    - the onboarding "username taken" check to
      base44.functions.invoke("portalCheckAvailable", { username }) and use
      response.data.available;
    - the affiliate "code taken" check to
      base44.functions.invoke("portalCheckAvailable", { code }) and use
      response.data.available and response.data.suggestion.
```

---

## Check the security change worked

From any terminal, signed out:

```bash
curl -s "https://crooks-partner-hub.base44.app/api/apps/6a96ee08b3aefa8357c55ed7/entities/Address?limit=1"
```

Before the change this returns an influencer's home address. Afterwards it
must return an error or `[]`. Then sign in as an influencer and as yourself to
check both portals still load.
