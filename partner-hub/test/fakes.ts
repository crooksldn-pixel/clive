// In-memory stand-ins for the Base44 SDK and Shopify, for handler tests.
import type {
  Address,
  AffiliateCode,
  AppUser,
  Base44Like,
  Deps,
  Entities,
  EntityApi,
  Influencer,
  Interest,
  Json,
  ProductRecord,
  Promotion,
  SendRecord,
  SizeProfile,
  SocialAccount,
} from "../src/lib/types.ts";
import { clearTokenCache } from "../src/lib/shopify.ts";

let seq = 0;
const newId = () => (0x6a000000 + ++seq).toString(16).padEnd(24, "0");

export class FakeEntity<T extends { id: string }> implements EntityApi<T> {
  rows: T[] = [];
  calls: { op: string; args: unknown[] }[] = [];
  failNext: Partial<Record<"create" | "update" | "delete", Error>> = {};

  constructor(seed: Partial<T>[] = [], private clock: () => Date = () => new Date()) {
    for (const r of seed) this.rows.push({ id: newId(), created_date: this.stamp(), ...r } as unknown as T);
  }
  private stamp() {
    // Base44's own timestamp format: UTC with microseconds and no zone.
    return this.clock().toISOString().replace("Z", "000");
  }
  private sorted(rows: T[], sort?: string): T[] {
    if (!sort) return rows;
    const desc = sort.startsWith("-");
    const key = sort.replace(/^-/, "") as keyof T;
    return [...rows].sort((a, b) => {
      const x = a[key] as unknown as string | number;
      const y = b[key] as unknown as string | number;
      return (x > y ? 1 : x < y ? -1 : 0) * (desc ? -1 : 1);
    });
  }
  async list(sort?: string, limit = 50, skip = 0) {
    this.calls.push({ op: "list", args: [sort, limit, skip] });
    return this.sorted(this.rows, sort).slice(skip, skip + limit).map((r) => ({ ...r }));
  }
  async filter(query: Json, sort?: string, limit = 50, skip = 0) {
    this.calls.push({ op: "filter", args: [query, sort, limit, skip] });
    const match = (r: T) => Object.entries(query).every(([k, v]) => (r as Record<string, unknown>)[k] === v);
    return this.sorted(this.rows.filter(match), sort).slice(skip, skip + limit).map((r) => ({ ...r }));
  }
  async get(id: string) {
    const r = this.rows.find((x) => x.id === id);
    if (!r) throw Object.assign(new Error("Entity not found"), { status: 404 });
    return { ...r };
  }
  async create(data: Partial<T>) {
    this.calls.push({ op: "create", args: [data] });
    if (this.failNext.create) throw this.takeFail("create");
    const row = { ...data, id: newId(), created_date: this.stamp() } as unknown as T;
    this.rows.push(row);
    return { ...row };
  }
  async update(id: string, data: Partial<T>) {
    this.calls.push({ op: "update", args: [id, data] });
    if (this.failNext.update) throw this.takeFail("update");
    const i = this.rows.findIndex((x) => x.id === id);
    if (i < 0) throw new Error("Entity not found");
    this.rows[i] = { ...this.rows[i], ...data };
    return { ...this.rows[i] };
  }
  async delete(id: string) {
    this.calls.push({ op: "delete", args: [id] });
    if (this.failNext.delete) throw this.takeFail("delete");
    this.rows = this.rows.filter((x) => x.id !== id);
    return { success: true };
  }
  private takeFail(op: "create" | "update" | "delete") {
    const e = this.failNext[op]!;
    delete this.failNext[op];
    return e;
  }
}

export type Seed = { [K in keyof Entities]?: Json[] };

export function fakeBase44(user: AppUser | null, seed: Seed = {}, clock?: () => Date) {
  // deno-lint-ignore no-explicit-any
  const rows = (k: keyof Entities) => (seed[k] ?? []) as any[];
  const entities = {
    Influencer: new FakeEntity<Influencer>(rows("Influencer"), clock),
    Address: new FakeEntity<Address>(rows("Address"), clock),
    SocialAccount: new FakeEntity<SocialAccount>(rows("SocialAccount"), clock),
    Interest: new FakeEntity<Interest>(rows("Interest"), clock),
    SizeProfile: new FakeEntity<SizeProfile>(rows("SizeProfile"), clock),
    Send: new FakeEntity<SendRecord>(rows("Send"), clock),
    Product: new FakeEntity<ProductRecord>(rows("Product"), clock),
    AffiliateCode: new FakeEntity<AffiliateCode>(rows("AffiliateCode"), clock),
    Promotion: new FakeEntity<Promotion>(rows("Promotion"), clock),
  };
  const base44: Base44Like = {
    auth: { me: async () => user },
    asServiceRole: { entities: entities as unknown as Entities },
  };
  return { base44, entities };
}

// deno-lint-ignore no-explicit-any
export type GraphQLResponder = (variables: any, query: string) => unknown;

/**
 * A fake Shopify: answers the token endpoint and routes GraphQL by operation
 * name (PartnerHubX). A responder returns `{ data }`, `{ errors }`, a Response,
 * or throws to simulate a network failure.
 */
export class FakeShopify {
  responders: Record<string, GraphQLResponder | GraphQLResponder[]> = {};
  calls: { op: string; variables: Record<string, any>; token: string | null }[] = [];
  tokenRequests: URLSearchParams[] = [];
  tokenStatus = 200;
  issued = 0;

  constructor(public domain = "5wn03t-nm.myshopify.com") {
    clearTokenCache();
  }

  on(op: string, ...responders: GraphQLResponder[]) {
    this.responders[op] = responders.length === 1 ? responders[0] : responders;
    return this;
  }

  ops() {
    return this.calls.map((c) => c.op);
  }

  fetch: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url === `https://${this.domain}/admin/oauth/access_token`) {
      this.tokenRequests.push(new URLSearchParams(String(init?.body)));
      if (this.tokenStatus !== 200) return new Response("nope", { status: this.tokenStatus });
      return Response.json({ access_token: `shpat_test_${++this.issued}`, scope: "write_orders", expires_in: 86399 });
    }
    if (!url.startsWith(`https://${this.domain}/admin/api/`) || !url.endsWith("/graphql.json")) {
      throw new Error(`unexpected fetch ${url}`);
    }
    const body = JSON.parse(String(init?.body));
    const op = /(?:query|mutation)\s+(PartnerHub\w+)/.exec(body.query)?.[1] ?? "anonymous";
    const headers = new Headers(init?.headers);
    this.calls.push({ op, variables: body.variables, token: headers.get("x-shopify-access-token") });
    let responder = this.responders[op];
    if (Array.isArray(responder)) responder = responder.length > 1 ? responder.shift()! : responder[0];
    if (!responder) throw new Error(`no fake for ${op}`);
    const out = responder(body.variables, body.query);
    if (out instanceof Response) return out;
    return Response.json(out);
  };
}

export const NOW = new Date("2026-10-08T21:00:00Z");

export interface TestDeps extends Deps {
  slept: number[];
}

export function makeDeps(opts: {
  base44: Base44Like;
  shopify?: FakeShopify;
  secrets?: Record<string, string>;
  now?: Date;
}): TestDeps {
  const slept: number[] = [];
  const secrets: Record<string, string> = {
    SHOPIFY_CLIENT_ID: "client-id",
    SHOPIFY_CLIENT_SECRET: "client-secret",
    ...(opts.secrets ?? {}),
  };
  return {
    base44: opts.base44,
    secret: (n) => secrets[n],
    fetch: opts.shopify?.fetch ?? (async () => {
      throw new Error("no network in tests");
    }),
    now: () => opts.now ?? NOW,
    sleep: async (ms) => {
      slept.push(ms);
    },
    appId: "6a96ee08b3aefa8357c55ed7",
    slept,
  };
}

export const ADMIN: AppUser = { id: "u-admin", email: "owner@example.com", role: "admin" };
export const INFLUENCER_USER: AppUser = { id: "u-inf", email: "maya@example.com", role: "user" };

export function post(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("https://crooks-partner-hub.base44.app/api/apps/x/functions/f", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

export async function readBody(res: Response): Promise<any> {
  return JSON.parse(await res.text());
}

export async function fixture<T = any>(name: string): Promise<T> {
  return JSON.parse(await Deno.readTextFile(new URL(`./fixtures/${name}`, import.meta.url)));
}
