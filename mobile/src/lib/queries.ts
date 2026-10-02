/**
 * Storefront API documents (2026-07).
 *
 * GraphQL rejects a declared variable that a document never uses, so
 * shopify.ts sends $withMeta only to documents that declare it.
 */

const IMAGE = `url width height altText`;
const MONEY = `amount currencyCode`;

const CARD = `
  id handle title productType availableForSale
  featuredImage { ${IMAGE} }
  priceRange { minVariantPrice { ${MONEY} } }
  compareAtPriceRange { maxVariantPrice { ${MONEY} } }
`;

/**
 * Sets are a buying mechanism, not a product — the website hides them from
 * every listing and so does the app. They are all productType "Sets".
 */
export const CATALOGUE = `
  query Catalogue($country: CountryCode, $after: String)
  @inContext(country: $country) {
    products(first: 100, after: $after, query: "-product_type:Sets", sortKey: CREATED_AT, reverse: true) {
      pageInfo { hasNextPage endCursor }
      nodes { ${CARD} }
    }
  }
`;

export const PRODUCT = `
  query Product($country: CountryCode, $withMeta: Boolean!, $handle: String!)
  @inContext(country: $country) {
    product(handle: $handle) {
      ${CARD}
      description
      options { name optionValues { name } }
      images(first: 20) { nodes { ${IMAGE} } }
      variants(first: 100) {
        nodes {
          id availableForSale
          selectedOptions { name value }
          price { ${MONEY} }
          compareAtPrice { ${MONEY} }
          image { ${IMAGE} }
        }
      }
      subtitle: metafield(namespace: "crooks", key: "subtitle") @include(if: $withMeta) { value }
      measurements: metafield(namespace: "crooks", key: "measurements") @include(if: $withMeta) { value }
    }
  }
`;

const CART = `
  id checkoutUrl totalQuantity
  cost { subtotalAmount { ${MONEY} } totalAmount { ${MONEY} } }
  lines(first: 100) {
    nodes {
      id quantity
      cost { totalAmount { ${MONEY} } }
      merchandise {
        ... on ProductVariant {
          id title
          selectedOptions { name value }
          image { ${IMAGE} }
          product { title handle }
        }
      }
    }
  }
`;

export const CART_GET = `
  query Cart($country: CountryCode, $id: ID!)
  @inContext(country: $country) { cart(id: $id) { ${CART} } }
`;

export const CART_CREATE = `
  mutation CartCreate($country: CountryCode, $lines: [CartLineInput!]!)
  @inContext(country: $country) {
    cartCreate(input: { lines: $lines, buyerIdentity: { countryCode: $country } }) {
      cart { ${CART} } userErrors { field message } warnings { code message }
    }
  }
`;

export const CART_ADD = `
  mutation CartAdd($country: CountryCode, $id: ID!, $lines: [CartLineInput!]!)
  @inContext(country: $country) {
    cartLinesAdd(cartId: $id, lines: $lines) { cart { ${CART} } userErrors { field message } warnings { code message } }
  }
`;

export const CART_UPDATE = `
  mutation CartUpdate($country: CountryCode, $id: ID!, $lines: [CartLineUpdateInput!]!)
  @inContext(country: $country) {
    cartLinesUpdate(cartId: $id, lines: $lines) { cart { ${CART} } userErrors { field message } warnings { code message } }
  }
`;

export const CART_REMOVE = `
  mutation CartRemove($country: CountryCode, $id: ID!, $lineIds: [ID!]!)
  @inContext(country: $country) {
    cartLinesRemove(cartId: $id, lineIds: $lineIds) { cart { ${CART} } userErrors { field message } warnings { code message } }
  }
`;
