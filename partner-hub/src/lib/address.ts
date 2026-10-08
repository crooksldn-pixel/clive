import { HttpError } from "./http.ts";
import type { Address } from "./types.ts";

// Shopify wants a province code (e.g. "NY") for countries that have them.
// The portal collects a free-text region, so map the common spellings.
const PROVINCES: Record<string, Record<string, string>> = {
  US: {
    alabama: "AL", alaska: "AK", arizona: "AZ", arkansas: "AR", california: "CA", colorado: "CO",
    connecticut: "CT", delaware: "DE", "district of columbia": "DC", "washington dc": "DC", florida: "FL",
    georgia: "GA", hawaii: "HI", idaho: "ID", illinois: "IL", indiana: "IN", iowa: "IA", kansas: "KS",
    kentucky: "KY", louisiana: "LA", maine: "ME", maryland: "MD", massachusetts: "MA", michigan: "MI",
    minnesota: "MN", mississippi: "MS", missouri: "MO", montana: "MT", nebraska: "NE", nevada: "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", ohio: "OH", oklahoma: "OK", oregon: "OR",
    pennsylvania: "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    tennessee: "TN", texas: "TX", utah: "UT", vermont: "VT", virginia: "VA", washington: "WA",
    "west virginia": "WV", wisconsin: "WI", wyoming: "WY", "puerto rico": "PR",
  },
  CA: {
    alberta: "AB", "british columbia": "BC", manitoba: "MB", "new brunswick": "NB",
    "newfoundland and labrador": "NL", newfoundland: "NL", "northwest territories": "NT",
    "nova scotia": "NS", nunavut: "NU", ontario: "ON", "prince edward island": "PE", quebec: "QC",
    "québec": "QC", saskatchewan: "SK", yukon: "YT",
  },
  AU: {
    "australian capital territory": "ACT", "new south wales": "NSW", "northern territory": "NT",
    queensland: "QLD", "south australia": "SA", tasmania: "TAS", victoria: "VIC",
    "western australia": "WA",
  },
};

export function provinceCode(country: string, region: string | undefined): string | undefined {
  const table = PROVINCES[country];
  if (!table || !region) return undefined;
  const r = region.trim();
  const upper = r.toUpperCase();
  if (Object.values(table).includes(upper)) return upper;
  return table[r.toLowerCase().replace(/\s+/g, " ")];
}

export function splitName(fullName: string): { firstName: string; lastName: string } {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 1) return { firstName: "", lastName: parts[0] ?? "" };
  return { firstName: parts.slice(0, -1).join(" "), lastName: parts[parts.length - 1] };
}

export interface MailingAddressInput {
  firstName: string;
  lastName: string;
  address1: string;
  address2?: string;
  city: string;
  zip: string;
  countryCode: string;
  provinceCode?: string;
}

/** Turns the portal's Address record into Shopify's MailingAddressInput. */
export function toShippingAddress(addr: Address | undefined): MailingAddressInput {
  if (!addr) throw new HttpError(422, "This influencer has no shipping address on file.", "address_missing");
  const missing = (["fullName", "line1", "city", "postcode", "country"] as const).filter(
    (k) => !String(addr[k] ?? "").trim(),
  );
  if (missing.length) {
    throw new HttpError(
      422,
      `The shipping address is incomplete (missing ${missing.join(", ")}). Ask the influencer to update it.`,
      "address_incomplete",
      { missing },
    );
  }
  const country = String(addr.country).trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(country)) {
    throw new HttpError(422, `The address country "${addr.country}" isn't a two-letter country code.`, "address_invalid");
  }
  const province = provinceCode(country, addr.region);
  if (PROVINCES[country] && !province) {
    throw new HttpError(
      422,
      `Shopify needs a valid state/province for ${country} addresses, but the region is "${addr.region ?? ""}". ` +
        "Fix the influencer's address first.",
      "address_invalid",
    );
  }
  const { firstName, lastName } = splitName(String(addr.fullName));
  const out: MailingAddressInput = {
    firstName,
    lastName,
    address1: String(addr.line1).trim(),
    city: String(addr.city).trim(),
    zip: String(addr.postcode).trim(),
    countryCode: country,
  };
  if (addr.line2?.trim()) out.address2 = addr.line2.trim();
  if (province) out.provinceCode = province;
  return out;
}
