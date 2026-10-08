// Every Shopify Admin GraphQL operation the Partner Hub runs. Each one has
// been validated against the Admin API schema; `npm run graphql` prints them
// for re-validation.

export const VARIANTS_FOR_SEND = /* GraphQL */ `
query PartnerHubVariantsForSend($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on ProductVariant {
      id
      title
      displayName
      sku
      price
      inventoryQuantity
      inventoryPolicy
      requiresComponents
      inventoryItem { tracked }
      product { id title handle status }
      productVariantComponents(first: 10) {
        nodes {
          quantity
          productVariant {
            id
            title
            displayName
            sku
            price
            inventoryQuantity
            inventoryPolicy
            requiresComponents
            inventoryItem { tracked }
            product { id title handle status }
          }
        }
      }
    }
  }
}`;

export const ORDER_CREATE = /* GraphQL */ `
mutation PartnerHubOrderCreate($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order {
      id
      name
      legacyResourceId
      createdAt
      displayFinancialStatus
      totalPriceSet { shopMoney { amount currencyCode } }
    }
    userErrors { field message code }
  }
}`;

export const ORDERS_BY_QUERY = /* GraphQL */ `
query PartnerHubOrdersByQuery($query: String!) {
  orders(first: 5, query: $query) {
    nodes { id name createdAt cancelledAt }
  }
}`;

export const CATALOG = /* GraphQL */ `
query PartnerHubCatalog($cursor: String, $query: String) {
  products(first: 8, after: $cursor, query: $query, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      handle
      title
      productType
      tags
      status
      featuredMedia { preview { image { url } } }
      options { name position }
      variants(first: 50) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          title
          sku
          price
          inventoryQuantity
          inventoryPolicy
          requiresComponents
          inventoryItem { tracked }
          selectedOptions { name value }
        }
      }
    }
  }
}`;

export const MORE_VARIANTS = /* GraphQL */ `
query PartnerHubMoreVariants($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        title
        sku
        price
        inventoryQuantity
        inventoryPolicy
        requiresComponents
        inventoryItem { tracked }
        selectedOptions { name value }
      }
    }
  }
}`;

export const ORDERS_TRACKING = /* GraphQL */ `
query PartnerHubOrdersTracking($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on Order {
      id
      name
      cancelledAt
      displayFulfillmentStatus
      fulfillments(first: 10) {
        id
        status
        displayStatus
        createdAt
        deliveredAt
        inTransitAt
        estimatedDeliveryAt
        trackingInfo(first: 5) { company number url }
      }
    }
  }
}`;

export const FULFILLMENT_ORDERS = /* GraphQL */ `
query PartnerHubFulfillmentOrders($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    fulfillmentOrders(first: 10) {
      nodes { id status supportedActions { action } }
    }
  }
}`;

export const FULFILLMENT_CREATE = /* GraphQL */ `
mutation PartnerHubFulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment {
      id
      status
      createdAt
      trackingInfo(first: 5) { company number url }
    }
    userErrors { field message }
  }
}`;

export const DISCOUNT_USAGE = /* GraphQL */ `
query PartnerHubDiscountUsage($code: String!) {
  codeDiscountNodeByCode(code: $code) {
    id
    codeDiscount {
      __typename
      ... on DiscountCodeBasic { asyncUsageCount }
      ... on DiscountCodeBxgy { asyncUsageCount }
      ... on DiscountCodeFreeShipping { asyncUsageCount }
      ... on DiscountCodeApp { asyncUsageCount }
    }
  }
}`;

export const DISCOUNT_ORDERS = /* GraphQL */ `
query PartnerHubDiscountOrders($query: String!, $cursor: String) {
  orders(first: 100, after: $cursor, query: $query) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      cancelledAt
      test
      currentSubtotalPriceSet { shopMoney { amount currencyCode } }
    }
  }
}`;

export const SHOP_CHECK = /* GraphQL */ `
query PartnerHubShopCheck {
  shop { name myshopifyDomain currencyCode }
  currentAppInstallation { accessScopes { handle } }
  locations(first: 5) { nodes { id name isActive fulfillsOnlineOrders } }
}`;

export const WEBHOOKS = /* GraphQL */ `
query PartnerHubWebhooks {
  webhookSubscriptions(first: 50) {
    nodes { id topic uri }
  }
}`;

export const WEBHOOK_CREATE = /* GraphQL */ `
mutation PartnerHubWebhookCreate($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}`;

export const ALL_OPERATIONS = {
  VARIANTS_FOR_SEND,
  ORDER_CREATE,
  ORDERS_BY_QUERY,
  CATALOG,
  MORE_VARIANTS,
  ORDERS_TRACKING,
  FULFILLMENT_ORDERS,
  FULFILLMENT_CREATE,
  DISCOUNT_USAGE,
  DISCOUNT_ORDERS,
  SHOP_CHECK,
  WEBHOOKS,
  WEBHOOK_CREATE,
};
