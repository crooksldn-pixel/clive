# Prompt for Claude Cowork

Paste everything in the box into a new Cowork task. Cowork does the whole
setup: the Shopify app (in Chrome), deploying the functions (in its shell),
the screen and security changes in the Base44 builder, and the first SYNC.
Be signed in to Shopify and Base44 in Chrome before you start. Cowork asks
before anything that matters.

```text
Set up the CROOKS Partner Hub ↔ Shopify connection. Everything is prepared in
GitHub: https://github.com/crooksldn-pixel/clive, branch
claude/compassionate-planck-9xe5of, folder partner-hub. Read
partner-hub/README.md and partner-hub/scripts/server-setup.sh before you start.

Ground rules
- Never create, cancel or edit a Shopify order, and never change products,
  prices or stock.
- Never run `base44 deploy`, `base44 entities push`, or anything with --force.
- Never show me or write down the Shopify client secret or the CLIVE API key,
  except where the steps below put them.
- Ask me before installing the Shopify app and before the first SYNC.
- If something doesn't match the README, stop and tell me what you see.

1. SHOPIFY APP (Chrome). Go to https://dev.shopify.com/dashboard (I'm signed in
   as the store owner). Create an app called "CROOKS Partner Hub". On Versions,
   set the scopes read_products, read_inventory, write_orders,
   write_merchant_managed_fulfillment_orders, read_discounts and
   read_locations, then Release. In its settings, open Protected customer data
   access and select Name, Email and Address with the reason "Shipping gifted
   products to influencers". Ask me, then install it on the CROOKSLDN store
   (5wn03t-nm.myshopify.com). Note the Client ID and Client secret for step 2.

2. DEPLOY (your shell):
     git clone --depth 1 -b claude/compassionate-planck-9xe5of https://github.com/crooksldn-pixel/clive.git
     cd clive/partner-hub
     export SHOPIFY_CLIENT_ID='<client id>' SHOPIFY_CLIENT_SECRET='<client secret>'
     bash scripts/server-setup.sh --yes
     unset SHOPIFY_CLIENT_SECRET
   When the script prints a Base44 verification code and a link, open the link
   in Chrome (I'm signed in to Base44 as the app owner), check the code
   matches, and confirm it. The script carries on by itself. Tell me every ✔,
   ! and ✖ line it printed, and the path of the CLIVE API key file.
   If it stops with ✖ "Missing Shopify permissions", add those scopes on the
   app's Versions page, release, approve the update in Shopify admin → Apps,
   and run `bash scripts/server-setup.sh --check`.
   If your shell can't reach npm, GitHub or base44.com, use the Base44
   dashboard in Chrome instead:
   - Settings → Secrets: SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET,
     SHOPIFY_STORE_DOMAIN=5wn03t-nm.myshopify.com, and PARTNER_API_KEY set to
     64 random hex characters.
   - Code → Functions: for each of the nine functions in partner-hub/README.md,
     copy the current code somewhere safe first, then replace it with
     partner-hub/base44/functions/<name>/entry.ts.

3. SCREENS AND SECURITY (Chrome). Open the Partner Hub in the Base44 builder,
   paste the text block from partner-hub/BASE44_PROMPT.md into the AI chat
   exactly as it is, and wait until it has finished. Then check in the app:
   - the admin influencer page has the new CREATE SEND dialog with variant
     dropdowns, plus MARK SHIPPED and CHECK SHOPIFY;
   - this command no longer returns an address (an error or [] is right):
       curl -s "https://crooks-partner-hub.base44.app/api/apps/6a96ee08b3aefa8357c55ed7/entities/Address?limit=1"
     If it still returns one, don't show me its contents. Tell me the security
     step didn't apply, and ask the builder to apply step 10 of the prompt again.

4. FIRST SYNC. Ask me, then run `bash scripts/server-setup.sh --sync`. It first
   checks the builder didn't change the functions, and redeploys any that it
   did. Tell me the summary.

5. Finish with a short report: what's done, anything that failed or was
   skipped, where the CLIVE key file is, and what's left for me. That should
   only be one real CREATE SEND, which I'll do myself.
```
