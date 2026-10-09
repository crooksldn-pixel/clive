import { currentUser, HttpError, json, readJson, wrap } from "../lib/http.ts";
import {
  activePromotion,
  DISCOUNT_TYPES,
  type DiscountType,
  normaliseCode,
  syncPromotions,
  termsForInfluencer,
  upsertDiscount,
  type UpsertResult,
} from "../lib/promotions.ts";
import { asString, getOr404, listAll, parseRecordDate } from "../lib/records.ts";
import { createShopify } from "../lib/shopify.ts";
import type { AffiliateCode } from "../lib/types.ts";

/**
 * shopifyCreateDiscount: makes (or updates) a creator code's Shopify discount.
 * - Affiliate tab, signed in as the influencer: { code }. The terms come from
 *   their previous code in Shopify, else the default for their country
 *   (UK: free socks, elsewhere: 15%), never from the editable record.
 * - Admin override: { code, type, value, influencerId, override: true }.
 * Returns { discountId, type, value }, then refreshes the gift rules.
 */
export const shopifyCreateDiscount = wrap(async (req, deps) => {
  const body = await readJson(req);
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in first.", "unauthenticated");
  const code = normaliseCode(body.code);
  if (!code) throw new HttpError(400, "Missing code.", "bad_request");

  const db = deps.base44.asServiceRole.entities;
  const shopify = createShopify(deps);
  const records = (await db.AffiliateCode.filter({ code })).sort(
    (a, b) => (parseRecordDate(b.created_date) || 0) - (parseRecordDate(a.created_date) || 0),
  );
  let record: AffiliateCode | undefined;
  let result: UpsertResult;

  if (body.override === true) {
    if (user.role !== "admin") throw new HttpError(403, "Only Partner Hub admins can override a code.", "forbidden");
    const type = asString(body.type) as DiscountType;
    if (!DISCOUNT_TYPES.includes(type)) throw new HttpError(400, `type must be one of ${DISCOUNT_TYPES.join(", ")}.`, "bad_type");
    const influencerId = asString(body.influencerId);
    record = records.find((r) => r.influencerId === influencerId) ?? records[0];
    if (!record) throw new HttpError(404, `The Hub has no code ${code}.`, "not_found");
    result = await upsertDiscount(deps, shopify, {
      code,
      type,
      value: Number(body.value),
      promotion: type === "free_socks" ? await activePromotion(deps) : undefined,
      storedId: record.shopifyDiscountId,
      override: true,
    });
  } else {
    if (user.role === "admin") {
      record = records[0];
    } else {
      const mine = (await db.Influencer.filter({ email: user.email }))[0];
      record = mine ? records.find((r) => r.influencerId === mine.id) : undefined;
    }
    if (!record) throw new HttpError(404, `No code ${code} belongs to you in the Hub.`, "not_found");
    const owner = await getOr404(db.Influencer, record.influencerId, "Influencer");
    if (owner.status === "blocked") throw new HttpError(409, "This account is blocked.", "influencer_blocked");
    if (records.some((r) => r.influencerId !== owner.id && r.shopifyDiscountId)) {
      throw new HttpError(409, `${code} is already someone else's code.`, "code_taken");
    }
    const terms = await termsForInfluencer(
      shopify,
      owner,
      await listAll(db.AffiliateCode, { influencerId: owner.id }),
      code,
    );
    result = await upsertDiscount(deps, shopify, {
      code,
      type: terms.type,
      value: terms.value,
      promotion: terms.type === "free_socks" ? await activePromotion(deps) : undefined,
      storedId: record.shopifyDiscountId,
      override: false,
    });
  }

  // Saved here as well as by the frontend, so the gift rules below include it.
  await db.AffiliateCode.update(record.id, { shopifyDiscountId: result.discountId, type: result.type, value: result.value });

  const warnings: string[] = [];
  try {
    await syncPromotions(deps, shopify);
  } catch (e) {
    warnings.push(`The discount is set, but the gift rules weren't refreshed: ${(e as Error).message}`);
  }
  return json({ ok: true, discountId: result.discountId, type: result.type, value: result.value, action: result.action, warnings });
});
