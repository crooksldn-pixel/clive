// Shapes of the Base44 records the Partner Hub already stores, and the
// dependencies every handler receives. Field names match the live app.

export type Json = Record<string, unknown>;

export interface EntityApi<T extends { id: string } = Record<string, any> & { id: string }> {
  list(sort?: string, limit?: number, skip?: number): Promise<T[]>;
  filter(query: Json, sort?: string, limit?: number, skip?: number): Promise<T[]>;
  get(id: string): Promise<T>;
  create(data: Partial<T>): Promise<T>;
  update(id: string, data: Partial<T>): Promise<T>;
  delete(id: string): Promise<unknown>;
}

export interface Influencer {
  id: string;
  email: string;
  username: string;
  status?: "pending" | "active" | "paused" | "blocked" | string;
  country?: string;
  joinedAt?: string;
  notes?: string;
  created_date?: string;
}

export interface Address {
  id: string;
  influencerId: string;
  fullName?: string;
  line1?: string;
  line2?: string;
  city?: string;
  region?: string;
  postcode?: string;
  country?: string;
  lockedUntil?: string;
}

export interface SocialAccount {
  id: string;
  influencerId: string;
  platform: "tiktok" | "instagram" | string;
  handle?: string;
  profileUrl?: string;
  followers?: number | null;
  avatarUrl?: string;
}

export interface Interest {
  id: string;
  influencerId: string;
  productHandle: string;
  size?: string;
  variantId?: string;
  created_date?: string;
}

export interface SizeProfile {
  id: string;
  influencerId: string;
  topSize?: string;
  bottomSize?: string;
}

export interface ProductVariantRecord {
  variantId: string;
  label: string;
  size: string;
  stock: number;
  price?: number;
  sku?: string | null;
  tracked?: boolean;
  isBundle?: boolean;
}

export interface ProductRecord {
  id: string;
  handle: string;
  name: string;
  type?: string;
  sizeCategory?: string;
  imageUrl?: string;
  priceGbp?: number;
  available?: boolean;
  sortOrder?: number;
  measurementsJson?: string;
  variants?: ProductVariantRecord[];
  shopifyProductId?: string;
  shopifyStatus?: string;
  syncedAt?: string;
}

export interface SendItem {
  name: string;
  size?: string;
  variantId?: string;
  quantity?: number;
  sku?: string | null;
  /** For a set (bundle), the pieces that were actually put on the order. */
  components?: { name: string; variantId: string; quantity: number }[];
}

export type SendStatus =
  | "preparing"
  | "dispatched"
  | "delivered"
  | "posted"
  | "overdue"
  | "cancelled";

export interface SendRecord {
  id: string;
  influencerId: string;
  influencerEmail?: string;
  status: SendStatus | string;
  items?: SendItem[];
  shopifyOrderId?: string | null;
  shopifyOrderName?: string | null;
  shopifyOrderUrl?: string | null;
  trackingNumber?: string | null;
  trackingUrl?: string | null;
  carrier?: string | null;
  dispatchedAt?: string | null;
  deliveredAt?: string | null;
  postByDate?: string | null;
  postedUrl?: string | null;
  postedAt?: string | null;
  cancelledAt?: string | null;
  retailValueGbp?: number;
  createdByEmail?: string;
  lastSyncedAt?: string;
  created_date?: string;
}

export interface AffiliateCode {
  id: string;
  influencerId: string;
  code: string;
  isPrimary?: boolean;
  usageCount?: number;
  revenueGbp?: number;
  shopifyDiscountId?: string;
  type?: string;
  value?: number;
  created_date?: string;
}

/** A gift promotion, edited in the Hub's Promotions tab. */
export interface Promotion {
  id: string;
  name?: string;
  active?: boolean;
  /** Gift variants in order of preference (numeric Shopify ids). */
  giftVariantIds?: (number | string)[];
  /** The "buys any piece" collection for the Buy X Get Y discount. */
  qualifyingCollectionId?: string;
  excludeProductTypes?: string[];
}

export interface Entities {
  Influencer: EntityApi<Influencer>;
  Address: EntityApi<Address>;
  SocialAccount: EntityApi<SocialAccount>;
  Interest: EntityApi<Interest>;
  SizeProfile: EntityApi<SizeProfile>;
  Send: EntityApi<SendRecord>;
  Product: EntityApi<ProductRecord>;
  AffiliateCode: EntityApi<AffiliateCode>;
  Promotion: EntityApi<Promotion>;
}

export interface AppUser {
  id: string;
  email: string;
  role?: string;
  full_name?: string;
}

/** The parts of the Base44 SDK client the handlers use. */
export interface Base44Like {
  auth: { me(): Promise<AppUser | null> };
  asServiceRole: { entities: Entities };
}

export interface Deps {
  base44: Base44Like;
  /** Reads a Base44 secret (environment variable). */
  secret: (name: string) => string | undefined;
  fetch: typeof fetch;
  now: () => Date;
  sleep: (ms: number) => Promise<void>;
  /** The Base44 app id, from the request the platform forwarded. */
  appId?: string | null;
}

export type Handler = (req: Request, deps: Deps) => Promise<Response>;
