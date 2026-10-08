import type { AppUser, Deps, Json } from "./types.ts";

/** An error whose message is safe and useful to show in the admin UI. */
export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = "error",
    public details?: unknown,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/**
 * The existing frontend reads `error.response.data.error` and shows it, so
 * every failure carries a plain-English `error` string.
 */
export function errorResponse(err: unknown): Response {
  if (err instanceof HttpError) {
    return json({ ok: false, error: err.message, code: err.code, details: err.details }, err.status);
  }
  const e = err as { name?: string; message?: string; kind?: string; details?: unknown };
  if (e?.name === "ShopifyError") {
    return json(
      { ok: false, error: `Shopify: ${e.message}`, code: `shopify_${e.kind ?? "error"}`, details: e.details },
      502,
    );
  }
  console.error(err);
  return json({ ok: false, error: `Unexpected error: ${e?.message ?? String(err)}`, code: "internal" }, 500);
}

export async function readJson(req: Request): Promise<Json> {
  if (req.method === "GET" || req.method === "HEAD") return {};
  const text = await req.text();
  if (!text.trim()) return {};
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Json;
  } catch {
    // fall through
  }
  throw new HttpError(400, "The request body must be a JSON object.", "bad_json");
}

export function timingSafeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export async function currentUser(deps: Deps): Promise<AppUser | null> {
  try {
    return (await deps.base44.auth.me()) ?? null;
  } catch {
    return null;
  }
}

export async function requireAdmin(deps: Deps): Promise<AppUser> {
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in to the Partner Hub as an admin first.", "unauthenticated");
  if (user.role !== "admin") throw new HttpError(403, "Only Partner Hub admins can do this.", "forbidden");
  return user;
}

export const PARTNER_KEY_HEADER = "x-partner-key";
const MIN_KEY_LENGTH = 24;

/**
 * True when the request carries the PARTNER_API_KEY secret, either in the
 * X-Partner-Key header (CLIVE, scripts) or as `key` in the body (a Base44
 * scheduled automation, whose arguments are stored privately in Base44).
 * The Authorization header is left alone: Base44 reads it as a user token.
 */
export function hasPartnerKey(req: Request, body: Json, deps: Deps): boolean {
  const expected = deps.secret("PARTNER_API_KEY") ?? "";
  if (expected.length < MIN_KEY_LENGTH) return false;
  const given = req.headers.get(PARTNER_KEY_HEADER) ?? (typeof body.key === "string" ? body.key : "");
  return given.length > 0 && timingSafeEqual(given, expected);
}

export type Actor = { kind: "admin"; email: string } | { kind: "key" };

export async function requireAdminOrKey(req: Request, body: Json, deps: Deps): Promise<Actor> {
  if (hasPartnerKey(req, body, deps)) return { kind: "key" };
  const user = await requireAdmin(deps);
  return { kind: "admin", email: user.email };
}

export function actorLabel(actor: Actor): string {
  return actor.kind === "admin" ? actor.email : "Partner API key";
}

/** Turns thrown errors into the JSON error shape the frontend expects. */
export function wrap(
  handler: (req: Request, deps: Deps) => Promise<Response>,
): (req: Request, deps: Deps) => Promise<Response> {
  return async (req, deps) => {
    if (req.method === "OPTIONS") return new Response(null, { status: 204 });
    try {
      return await handler(req, deps);
    } catch (e) {
      return errorResponse(e);
    }
  };
}
