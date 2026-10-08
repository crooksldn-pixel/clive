import { HttpError } from "./http.ts";
import type { Deps } from "./types.ts";

export const DEFAULT_STORE_DOMAIN = "5wn03t-nm.myshopify.com";
export const DEFAULT_API_VERSION = "2026-07";

export class ShopifyError extends Error {
  constructor(
    message: string,
    public kind: "auth" | "scope" | "throttled" | "graphql" | "http" | "network" | "uncertain",
    public details?: unknown,
  ) {
    super(message);
    this.name = "ShopifyError";
  }
}

export interface ShopifyConfig {
  domain: string;
  apiVersion: string;
  staticToken?: string;
  clientId?: string;
  clientSecret?: string;
}

export function shopifyConfig(secret: Deps["secret"]): ShopifyConfig {
  const raw = (secret("SHOPIFY_STORE_DOMAIN") || DEFAULT_STORE_DOMAIN).trim().toLowerCase();
  const domain = raw.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (!/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(domain)) {
    throw new HttpError(
      500,
      `SHOPIFY_STORE_DOMAIN must be the store's .myshopify.com address (got "${raw}").`,
      "shopify_not_configured",
    );
  }
  const cfg: ShopifyConfig = {
    domain,
    apiVersion: secret("SHOPIFY_API_VERSION") || DEFAULT_API_VERSION,
    staticToken: secret("SHOPIFY_ADMIN_ACCESS_TOKEN") || undefined,
    clientId: secret("SHOPIFY_CLIENT_ID") || undefined,
    clientSecret: secret("SHOPIFY_CLIENT_SECRET") || undefined,
  };
  if (!cfg.staticToken && !(cfg.clientId && cfg.clientSecret)) {
    throw new HttpError(
      500,
      "Shopify isn't connected yet: add the SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET secrets in Base44 " +
        "(or SHOPIFY_ADMIN_ACCESS_TOKEN for an older custom app).",
      "shopify_not_configured",
    );
  }
  return cfg;
}

export function storeHandle(cfg: ShopifyConfig): string {
  return cfg.domain.replace(/\.myshopify\.com$/, "");
}

export function orderAdminUrl(cfg: ShopifyConfig, orderGid: string): string {
  const id = orderGid.split("/").pop();
  return `https://admin.shopify.com/store/${storeHandle(cfg)}/orders/${id}`;
}

// Client-credentials tokens last 24 hours. Cached per isolate so warm
// invocations skip the token request.
const tokenCache = new Map<string, { token: string; expiresAt: number }>();

export function clearTokenCache() {
  tokenCache.clear();
}

async function accessToken(cfg: ShopifyConfig, deps: Deps, force = false): Promise<string> {
  if (cfg.staticToken) return cfg.staticToken;
  const key = `${cfg.domain}:${cfg.clientId}`;
  const cached = tokenCache.get(key);
  const now = deps.now().getTime();
  if (!force && cached && cached.expiresAt - 5 * 60_000 > now) return cached.token;

  let res: Response;
  try {
    res = await deps.fetch(`https://${cfg.domain}/admin/oauth/access_token`, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
      body: new URLSearchParams({
        grant_type: "client_credentials",
        client_id: cfg.clientId!,
        client_secret: cfg.clientSecret!,
      }).toString(),
    });
  } catch (e) {
    throw new ShopifyError(`couldn't reach ${cfg.domain} for an access token (${(e as Error).message}).`, "network");
  }
  const text = await res.text();
  if (!res.ok) {
    throw new ShopifyError(
      `the access token request was refused (HTTP ${res.status}). Check SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET, ` +
        `and that the app is installed on ${cfg.domain}.`,
      "auth",
      text.slice(0, 300),
    );
  }
  let body: { access_token?: string; expires_in?: number };
  try {
    body = JSON.parse(text);
  } catch {
    throw new ShopifyError("the access token response wasn't JSON.", "auth", text.slice(0, 300));
  }
  if (!body.access_token) throw new ShopifyError("the access token response had no token.", "auth");
  tokenCache.set(key, { token: body.access_token, expiresAt: now + (body.expires_in ?? 86_399) * 1000 });
  return body.access_token;
}

interface GraphQLError {
  message: string;
  extensions?: { code?: string; [k: string]: unknown };
}

export interface GraphQLOptions {
  /**
   * False for mutations that must not run twice (orderCreate,
   * fulfillmentCreate). Those are retried only when Shopify certainly did not
   * run them (HTTP 429, THROTTLED, or a refused token).
   */
  idempotent?: boolean;
}

export interface Shopify {
  config: ShopifyConfig;
  graphql<T = any>(query: string, variables?: Record<string, unknown>, opts?: GraphQLOptions): Promise<T>;
}

const MAX_ATTEMPTS = 5;

export function createShopify(deps: Deps, cfg: ShopifyConfig = shopifyConfig(deps.secret)): Shopify {
  const url = `https://${cfg.domain}/admin/api/${cfg.apiVersion}/graphql.json`;

  async function graphql<T>(query: string, variables: Record<string, unknown> = {}, opts: GraphQLOptions = {}) {
    const idempotent = opts.idempotent ?? !/^\s*mutation\b/.test(query);
    let refreshedToken = false;

    for (let attempt = 1; ; attempt++) {
      const token = await accessToken(cfg, deps);
      let res: Response;
      try {
        res = await deps.fetch(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            accept: "application/json",
            "x-shopify-access-token": token,
          },
          body: JSON.stringify({ query, variables }),
        });
      } catch (e) {
        if (idempotent && attempt < MAX_ATTEMPTS) {
          await deps.sleep(backoff(attempt));
          continue;
        }
        throw new ShopifyError(
          `no response from Shopify (${(e as Error).message}).`,
          idempotent ? "network" : "uncertain",
        );
      }

      if (res.status === 401 && !cfg.staticToken && !refreshedToken) {
        // Token expired or rotated: Shopify refused it, so nothing ran.
        refreshedToken = true;
        await accessToken(cfg, deps, true);
        continue;
      }
      if (res.status === 401) {
        throw new ShopifyError("the access token was refused (HTTP 401). Reinstall the app or rotate its credentials.", "auth");
      }
      if (res.status === 403) {
        throw new ShopifyError(
          "the app isn't allowed to do this (HTTP 403). Add the missing access scopes to the Shopify app and reinstall it.",
          "scope",
        );
      }
      if (res.status === 429 && attempt < MAX_ATTEMPTS) {
        const retryAfter = Number(res.headers.get("retry-after"));
        await deps.sleep(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : backoff(attempt));
        continue;
      }
      if (res.status >= 500) {
        if (idempotent && attempt < MAX_ATTEMPTS) {
          await deps.sleep(backoff(attempt));
          continue;
        }
        throw new ShopifyError(
          `Shopify returned HTTP ${res.status}.`,
          idempotent ? "http" : "uncertain",
        );
      }
      if (!res.ok) {
        throw new ShopifyError(`Shopify returned HTTP ${res.status}.`, "http", (await res.text()).slice(0, 500));
      }

      let body: {
        data?: T;
        errors?: GraphQLError[];
        extensions?: { cost?: { requestedQueryCost?: number; throttleStatus?: { currentlyAvailable: number; restoreRate: number } } };
      };
      try {
        body = await res.json();
      } catch {
        throw new ShopifyError("Shopify's response couldn't be read.", idempotent ? "http" : "uncertain");
      }
      const errors = body.errors ?? [];
      if (errors.some((e) => e.extensions?.code === "THROTTLED") && attempt < MAX_ATTEMPTS) {
        const cost = body.extensions?.cost;
        const need = (cost?.requestedQueryCost ?? 100) - (cost?.throttleStatus?.currentlyAvailable ?? 0);
        const rate = cost?.throttleStatus?.restoreRate || 50;
        await deps.sleep(Math.max(1000, Math.ceil((need / rate) * 1000)));
        continue;
      }
      if (errors.some((e) => e.extensions?.code === "ACCESS_DENIED")) {
        throw new ShopifyError(
          `access denied: ${errors.map((e) => e.message).join("; ")}. Add the missing access scopes to the Shopify app.`,
          "scope",
          errors,
        );
      }
      if (errors.length) {
        const internal = errors.some((e) => e.extensions?.code === "INTERNAL_SERVER_ERROR");
        throw new ShopifyError(
          errors.map((e) => e.message).join("; "),
          internal && !idempotent ? "uncertain" : "graphql",
          errors,
        );
      }
      if (body.data === undefined) throw new ShopifyError("the response had no data.", "graphql");
      return body.data;
    }
  }

  return { config: cfg, graphql };
}

function backoff(attempt: number): number {
  return Math.min(8000, 500 * 2 ** (attempt - 1));
}

const VARIANT_GID = /^gid:\/\/shopify\/ProductVariant\/(\d+)$/;

/** Accepts a variant GID or a bare numeric id; returns the GID or null. */
export function variantGid(id: unknown): string | null {
  if (typeof id === "number" && Number.isInteger(id) && id > 0) return `gid://shopify/ProductVariant/${id}`;
  if (typeof id !== "string") return null;
  const s = id.trim();
  if (VARIANT_GID.test(s)) return s;
  if (/^\d+$/.test(s)) return `gid://shopify/ProductVariant/${s}`;
  return null;
}

export function orderGid(id: unknown): string | null {
  if (typeof id === "number" && Number.isInteger(id) && id > 0) return `gid://shopify/Order/${id}`;
  if (typeof id !== "string") return null;
  const s = id.trim();
  if (/^gid:\/\/shopify\/Order\/\d+$/.test(s)) return s;
  if (/^\d+$/.test(s)) return `gid://shopify/Order/${s}`;
  return null;
}

export function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}
