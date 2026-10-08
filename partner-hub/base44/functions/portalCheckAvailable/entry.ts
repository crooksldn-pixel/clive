// CROOKS Partner Hub — Base44 function "portalCheckAvailable".
// GENERATED from partner-hub/src by `npm run build`. Edit the source, not this file.


// src/lib/http.ts
var HttpError = class extends Error {
  constructor(status, message, code = "error", details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.name = "HttpError";
  }
};
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" }
  });
}
function errorResponse(err) {
  if (err instanceof HttpError) {
    return json({ ok: false, error: err.message, code: err.code, details: err.details }, err.status);
  }
  const e = err;
  if (e?.name === "ShopifyError") {
    return json(
      { ok: false, error: `Shopify: ${e.message}`, code: `shopify_${e.kind ?? "error"}`, details: e.details },
      502
    );
  }
  console.error(err);
  return json({ ok: false, error: `Unexpected error: ${e?.message ?? String(err)}`, code: "internal" }, 500);
}
async function readJson(req) {
  if (req.method === "GET" || req.method === "HEAD") return {};
  const text = await req.text();
  if (!text.trim()) return {};
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
  } catch {
  }
  throw new HttpError(400, "The request body must be a JSON object.", "bad_json");
}
async function currentUser(deps) {
  try {
    return await deps.base44.auth.me() ?? null;
  } catch {
    return null;
  }
}
function wrap(handler) {
  return async (req, deps) => {
    if (req.method === "OPTIONS") return new Response(null, { status: 204 });
    try {
      return await handler(req, deps);
    } catch (e) {
      return errorResponse(e);
    }
  };
}

// src/handlers/portalCheckAvailable.ts
var portalCheckAvailable = wrap(async (req, deps) => {
  const body = await readJson(req);
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in first.", "unauthenticated");
  const db = deps.base44.asServiceRole.entities;
  const mine = (await db.Influencer.filter({ email: user.email }))[0];
  if (typeof body.username === "string") {
    const username = body.username.toLowerCase().replace(/[^a-z0-9._]/g, "");
    if (!username) return json({ available: false });
    const taken = (await db.Influencer.filter({ username })).some((i) => i.email !== user.email);
    return json({ available: !taken, username });
  }
  if (typeof body.code === "string") {
    const code = body.code.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!code) return json({ available: false });
    const taken = (await db.AffiliateCode.filter({ code })).some((c) => !mine || c.influencerId !== mine.id);
    return json({ available: !taken, code, suggestion: taken ? `${code}2` : void 0 });
  }
  throw new HttpError(400, "Send { username } or { code }.", "bad_request");
});

// src/lib/runtime.ts
import { createClientFromRequest } from "npm:@base44/sdk@0.8.49";
function readSecret(name) {
  try {
    const bridge = globalThis.Base44;
    const v = bridge?.secrets?.get(name);
    if (v) return v;
  } catch {
  }
  try {
    return Deno.env.get(name);
  } catch {
    return void 0;
  }
}
function serve(handler) {
  Deno.serve(async (req) => {
    let base44;
    try {
      base44 = createClientFromRequest(req);
    } catch (e) {
      return Response.json({ ok: false, error: `Not called through Base44: ${e.message}` }, { status: 400 });
    }
    return handler(req, {
      base44,
      secret: readSecret,
      fetch: (input, init) => fetch(input, init),
      now: () => /* @__PURE__ */ new Date(),
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      appId: req.headers.get("Base44-App-Id")
    });
  });
}

// src/functions/portalCheckAvailable.ts
serve(portalCheckAvailable);
