import { CATALOGUE, PRODUCT } from './queries';
import { storefront } from './shopify';
import type { MeasureRow, Product, ProductCard, ShopImage } from './types';

type RawCard = {
  id: string; handle: string; title: string; productType: string; availableForSale: boolean;
  featuredImage: ShopImage | null;
  priceRange: { minVariantPrice: ProductCard['price'] };
  compareAtPriceRange: { maxVariantPrice: ProductCard['price'] };
};

function toCard(p: RawCard): ProductCard {
  const was = p.compareAtPriceRange.maxVariantPrice;
  return {
    id: p.id, handle: p.handle, title: p.title, productType: p.productType,
    availableForSale: p.availableForSale, featuredImage: p.featuredImage,
    price: p.priceRange.minVariantPrice,
    /* Shopify reports 0.0 when nothing is on sale; only a real higher price is a "was". */
    compareAtPrice: Number(was.amount) > Number(p.priceRange.minVariantPrice.amount) ? was : null,
  };
}

export async function getCatalogue(signal?: AbortSignal): Promise<ProductCard[]> {
  const out: ProductCard[] = [];
  let after: string | null = null;
  /* Paged, with a hard stop, so a store that grows past 100 still lists everything. */
  for (let page = 0; page < 10; page++) {
    const data: { products: { pageInfo: { hasNextPage: boolean; endCursor: string | null }; nodes: RawCard[] } } =
      await storefront(CATALOGUE, { after }, signal);
    out.push(...data.products.nodes.map(toCard));
    if (!data.products.pageInfo.hasNextPage) break;
    after = data.products.pageInfo.endCursor;
  }
  return out;
}

/**
 * Category filters, built from what is actually on sale — never a fixed list,
 * so a type that sells out of the catalogue does not leave a dead filter.
 * Products with no type still appear under ALL.
 */
export function categoriesOf(cards: ProductCard[]): string[] {
  const count = new Map<string, number>();
  for (const c of cards) {
    const t = c.productType.trim();
    if (t) count.set(t, (count.get(t) ?? 0) + 1);
  }
  return [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([t]) => t);
}

function parseMeasurements(raw: string | undefined | null): MeasureRow[] | null {
  if (!raw) return null;
  try {
    const rows = JSON.parse(raw) as unknown;
    return Array.isArray(rows) && rows.length ? (rows as MeasureRow[]) : null;
  } catch {
    return null;   /* a malformed chart is no chart, not a crash */
  }
}

export async function getProduct(handle: string, signal?: AbortSignal): Promise<Product | null> {
  type Raw = RawCard & {
    description: string;
    options: Product['options'];
    images: { nodes: ShopImage[] };
    variants: { nodes: Product['variants'] };
    subtitle?: { value: string } | null;
    measurements?: { value: string } | null;
  };
  const data = await storefront<{ product: Raw | null }>(PRODUCT, { handle }, signal);
  const p = data.product;
  if (!p) return null;
  return {
    ...toCard(p),
    description: p.description,
    options: p.options,
    images: p.images.nodes,
    variants: p.variants.nodes,
    subtitle: p.subtitle?.value?.trim() || null,
    measurements: parseMeasurements(p.measurements?.value),
  };
}
