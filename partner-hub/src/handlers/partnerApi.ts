import { syncCatalog } from "../lib/catalog.ts";
import { markShipped, parseMarkShipped } from "../lib/fulfil.ts";
import { hasPartnerKey, HttpError, json, readJson, wrap } from "../lib/http.ts";
import { getInfluencer, listInfluencers, listProducts, listSends, recordPost } from "../lib/partner.ts";
import { asString } from "../lib/records.ts";
import { createSend, parseItems, planSend } from "../lib/sends.ts";
import { createShopify } from "../lib/shopify.ts";
import { syncTracking } from "../lib/tracking.ts";
import type { Deps } from "../lib/types.ts";
import { syncUsage } from "../lib/usage.ts";

const WRITE_ACTIONS = new Set(["createSend", "markShipped", "recordPost"]);

/**
 * partnerApi: the API for CLIVE. POST { action, ...params } with the
 * X-Partner-Key header. See partner-hub/CLIVE_API.md.
 */
export const partnerApi = wrap(async (req, deps) => {
  if (req.method !== "POST") throw new HttpError(405, "POST a JSON body with an action.", "method_not_allowed");
  const body = await readJson(req);
  if (!hasPartnerKey(req, body, deps)) {
    throw new HttpError(401, "Missing or wrong X-Partner-Key header.", "unauthenticated");
  }
  const action = asString(body.action);
  const writesEnabled = deps.secret("PARTNER_API_ALLOW_WRITES") === "true";
  const isDryRun = action === "createSend" && body.dryRun === true;
  if (WRITE_ACTIONS.has(action) && !writesEnabled && !isDryRun) {
    throw new HttpError(
      403,
      `"${action}" changes orders or records, and Partner API writes are off. Set PARTNER_API_ALLOW_WRITES=true to allow it.`,
      "writes_disabled",
    );
  }
  const data = await runAction(action, body, deps, writesEnabled);
  return json({ ok: true, action, data });
});

async function runAction(action: string, body: Record<string, unknown>, deps: Deps, writesEnabled: boolean) {
  switch (action) {
    case "ping":
      return { app: "crooks-partner-hub", writesEnabled, time: deps.now().toISOString() };
    case "listInfluencers":
      return await listInfluencers(deps, {
        status: asString(body.status) || undefined,
        hasInterests: body.hasInterests === true,
        neverSent: body.neverSent === true,
      });
    case "getInfluencer":
      return await getInfluencer(deps, {
        influencerId: asString(body.influencerId) || undefined,
        username: asString(body.username) || undefined,
      });
    case "listSends":
      return await listSends(deps, {
        status: asString(body.status) || undefined,
        influencerId: asString(body.influencerId) || undefined,
      });
    case "listProducts":
      return await listProducts(deps);
    case "checkStock": {
      const plan = await planSend(createShopify(deps), parseItems(body.items));
      return { sendable: plan.problems.length === 0, items: plan.items, stock: plan.stock, problems: plan.problems, warnings: plan.warnings };
    }
    case "createSend": {
      const influencerId = asString(body.influencerId);
      if (!influencerId) throw new HttpError(400, "Missing influencerId.", "bad_request");
      return await createSend(deps, createShopify(deps), {
        influencerId,
        items: parseItems(body.items),
        note: asString(body.note).slice(0, 500) || undefined,
        dryRun: body.dryRun === true,
        createdBy: "CLIVE (Partner API)",
      });
    }
    case "markShipped":
      return await markShipped(deps, createShopify(deps), parseMarkShipped(body));
    case "recordPost":
      return await recordPost(deps, body);
    case "syncTracking":
      return await syncTracking(deps, createShopify(deps));
    case "syncCatalog":
      return await syncCatalog(deps, createShopify(deps));
    case "syncUsage":
      return await syncUsage(deps, createShopify(deps));
    default:
      throw new HttpError(400, `Unknown action "${action}". See CLIVE_API.md for the list.`, "unknown_action");
  }
}
