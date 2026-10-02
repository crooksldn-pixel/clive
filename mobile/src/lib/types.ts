export type Money = { amount: string; currencyCode: string };

export type ShopImage = {
  url: string;
  width: number | null;
  height: number | null;
  altText: string | null;
};

export type ProductOption = { name: string; optionValues: { name: string }[] };

export type Variant = {
  id: string;
  availableForSale: boolean;
  selectedOptions: { name: string; value: string }[];
  price: Money;
  compareAtPrice: Money | null;
  image: ShopImage | null;
};

/** One row of the crooks.measurements metafield: { size: "M", chest: "110.5cm", ... } */
export type MeasureRow = Record<string, string>;

export type ProductCard = {
  id: string;
  handle: string;
  title: string;
  productType: string;
  availableForSale: boolean;
  featuredImage: ShopImage | null;
  price: Money;
  compareAtPrice: Money | null;
};

export type Product = ProductCard & {
  description: string;
  options: ProductOption[];
  images: ShopImage[];
  variants: Variant[];
  /** Only present when a Storefront token is configured. */
  subtitle: string | null;
  measurements: MeasureRow[] | null;
};

export type CartLine = {
  id: string;
  quantity: number;
  cost: { totalAmount: Money };
  merchandise: {
    id: string;
    title: string;
    selectedOptions: { name: string; value: string }[];
    image: ShopImage | null;
    product: { title: string; handle: string };
  };
};

export type Cart = {
  id: string;
  checkoutUrl: string;
  totalQuantity: number;
  cost: { subtotalAmount: Money; totalAmount: Money };
  lines: CartLine[];
  /** Shopify's note about the last change, e.g. a quantity capped at what is in stock. */
  notice: string | null;
};
