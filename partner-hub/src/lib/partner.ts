import { HttpError } from "./http.ts";
import { getOr404, listAll } from "./records.ts";
import type {
  AffiliateCode,
  Deps,
  Influencer,
  Interest,
  ProductRecord,
  SendRecord,
  SocialAccount,
} from "./types.ts";

// Read models served to CLIVE (and anything else holding the partner key).
// Street addresses and emails stay out of list views on purpose.

function social(accounts: SocialAccount[], platform: string) {
  const a = accounts.find((s) => s.platform === platform);
  if (!a) return null;
  return {
    handle: a.handle ?? null,
    url: a.profileUrl ?? (a.handle ? profileUrl(platform, a.handle) : null),
    followers: a.followers ?? null,
  };
}

export function profileUrl(platform: string, handle: string): string {
  const h = handle.replace(/^@/, "");
  return platform === "tiktok" ? `https://www.tiktok.com/@${h}` : `https://www.instagram.com/${h}/`;
}

function sendView(s: SendRecord, username?: string) {
  return {
    id: s.id,
    influencerId: s.influencerId,
    influencer: username ? `@${username}` : undefined,
    status: s.status,
    items: s.items ?? [],
    orderName: s.shopifyOrderName ?? null,
    orderId: s.shopifyOrderId ?? null,
    orderAdminUrl: s.shopifyOrderUrl ?? null,
    carrier: s.carrier ?? null,
    trackingNumber: s.trackingNumber ?? null,
    trackingUrl: s.trackingUrl ?? null,
    dispatchedAt: s.dispatchedAt ?? null,
    deliveredAt: s.deliveredAt ?? null,
    postByDate: s.postByDate ?? null,
    postedUrl: s.postedUrl ?? null,
    createdAt: s.created_date ?? null,
  };
}

function interestView(i: Interest, products: Map<string, ProductRecord>) {
  const p = products.get(i.productHandle);
  const v = p?.variants?.find((x) => x.variantId === i.variantId) ??
    p?.variants?.find((x) => x.size === (i.size || "ONE") && x.stock > 0);
  return {
    productHandle: i.productHandle,
    productName: p?.name ?? null,
    size: i.size ?? null,
    variantId: v?.variantId ?? i.variantId ?? null,
    variantLabel: v?.label ?? null,
    stock: v?.stock ?? 0,
    flaggedAt: i.created_date ?? null,
  };
}

interface World {
  influencers: Influencer[];
  socials: SocialAccount[];
  interests: Interest[];
  sends: SendRecord[];
  codes: AffiliateCode[];
  products: Map<string, ProductRecord>;
}

async function loadWorld(deps: Deps): Promise<World> {
  const db = deps.base44.asServiceRole.entities;
  const [influencers, socials, interests, sends, codes, products] = await Promise.all([
    listAll(db.Influencer),
    listAll(db.SocialAccount),
    listAll(db.Interest),
    listAll(db.Send),
    listAll(db.AffiliateCode),
    listAll(db.Product, undefined, "name"),
  ]);
  return { influencers, socials, interests, sends, codes, products: new Map(products.map((p) => [p.handle, p])) };
}

function influencerView(inf: Influencer, w: World) {
  const mine = <T extends { influencerId: string }>(xs: T[]) => xs.filter((x) => x.influencerId === inf.id);
  const accounts = mine(w.socials);
  const sends = mine(w.sends);
  const codes = mine(w.codes);
  const last = sends[0];
  return {
    id: inf.id,
    username: inf.username,
    status: inf.status ?? null,
    country: inf.country ?? null,
    joinedAt: inf.joinedAt ?? null,
    tiktok: social(accounts, "tiktok"),
    instagram: social(accounts, "instagram"),
    interests: mine(w.interests).map((i) => interestView(i, w.products)),
    affiliateCode: codes.find((c) => c.isPrimary)?.code ?? null,
    codeUses: codes.reduce((n, c) => n + (c.usageCount ?? 0), 0),
    sends: {
      total: sends.length,
      active: sends.filter((s) => ["preparing", "dispatched", "delivered", "overdue"].includes(s.status)).length,
      owesPost: sends.some((s) => ["dispatched", "delivered", "overdue"].includes(s.status)),
      last: last ? { orderName: last.shopifyOrderName ?? null, status: last.status, createdAt: last.created_date ?? null } : null,
    },
  };
}

export async function listInfluencers(deps: Deps, opts: { status?: string; hasInterests?: boolean; neverSent?: boolean }) {
  const w = await loadWorld(deps);
  let list = w.influencers.map((i) => influencerView(i, w));
  if (opts.status) list = list.filter((i) => i.status === opts.status);
  if (opts.hasInterests) list = list.filter((i) => i.interests.length > 0);
  if (opts.neverSent) list = list.filter((i) => i.sends.total === 0);
  return list;
}

export async function getInfluencer(deps: Deps, opts: { influencerId?: string; username?: string }) {
  const db = deps.base44.asServiceRole.entities;
  let inf: Influencer | undefined;
  if (opts.influencerId) inf = await getOr404(db.Influencer, opts.influencerId, "Influencer");
  else if (opts.username) {
    inf = (await db.Influencer.filter({ username: opts.username.replace(/^@/, "").toLowerCase() }))[0];
  }
  if (!inf) throw new HttpError(404, "Influencer not found.", "not_found");
  const w = await loadWorld(deps);
  const addr = (await db.Address.filter({ influencerId: inf.id }))[0];
  const sizes = (await db.SizeProfile.filter({ influencerId: inf.id }))[0];
  return {
    ...influencerView(inf, w),
    email: inf.email,
    shipsTo: addr ? { city: addr.city ?? null, country: addr.country ?? null } : null,
    sizes: sizes ? { top: sizes.topSize ?? null, bottom: sizes.bottomSize ?? null } : null,
    sendHistory: w.sends.filter((s) => s.influencerId === inf!.id).map((s) => sendView(s)),
  };
}

export async function listSends(deps: Deps, opts: { status?: string; influencerId?: string }) {
  const db = deps.base44.asServiceRole.entities;
  const [sends, influencers] = await Promise.all([
    listAll(db.Send, opts.influencerId ? { influencerId: opts.influencerId } : undefined),
    listAll(db.Influencer),
  ]);
  const names = new Map(influencers.map((i) => [i.id, i.username]));
  return sends
    .filter((s) => !opts.status || s.status === opts.status)
    .map((s) => sendView(s, names.get(s.influencerId)));
}

export async function listProducts(deps: Deps) {
  const products = await listAll(deps.base44.asServiceRole.entities.Product, undefined, "name");
  return products
    .sort((a, b) => (a.sortOrder ?? 999) - (b.sortOrder ?? 999))
    .map((p) => ({
      handle: p.handle,
      name: p.name,
      type: p.type ?? null,
      availableToInfluencers: p.available !== false,
      shopifyStatus: p.shopifyStatus ?? null,
      syncedAt: p.syncedAt ?? null,
      variants: (p.variants ?? []).map((v) => ({ variantId: v.variantId, label: v.label, size: v.size, stock: v.stock })),
    }));
}

export async function recordPost(deps: Deps, body: Record<string, unknown>) {
  const db = deps.base44.asServiceRole.entities;
  const sendId = typeof body.sendId === "string" ? body.sendId : "";
  const postedUrl = typeof body.postedUrl === "string" ? body.postedUrl.trim() : "";
  if (!/^https:\/\/\S+$/.test(postedUrl)) throw new HttpError(400, "postedUrl must be an https:// link to the post.", "bad_url");
  const send = await getOr404(db.Send, sendId, "Send");
  if (send.status === "cancelled") throw new HttpError(409, "This send was cancelled.", "send_cancelled");
  const updated = await db.Send.update(send.id, { postedUrl, postedAt: deps.now().toISOString(), status: "posted" });
  return sendView({ ...send, ...updated });
}
