import { HttpError } from "./http.ts";
import type { EntityApi, Json } from "./types.ts";

const PAGE = 500;

/** Reads every matching record, a page at a time. */
export async function listAll<T extends { id: string }>(
  entity: EntityApi<T>,
  query?: Json,
  sort = "-created_date",
): Promise<T[]> {
  const out: T[] = [];
  for (let skip = 0; ; skip += PAGE) {
    const page = query ? await entity.filter(query, sort, PAGE, skip) : await entity.list(sort, PAGE, skip);
    out.push(...page);
    if (page.length < PAGE) return out;
  }
}

/** `get` throws on a missing id; this turns that into a clean 404. */
export async function getOr404<T extends { id: string }>(entity: EntityApi<T>, id: string, what: string): Promise<T> {
  if (!id) throw new HttpError(400, `Missing ${what} id.`, "bad_request");
  try {
    const rec = await entity.get(id);
    if (rec) return rec;
  } catch {
    // fall through
  }
  throw new HttpError(404, `${what} not found (${id}).`, "not_found");
}

export function asString(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

/**
 * Base44 returns record timestamps such as "2026-09-01T16:41:46.907000"
 * (UTC, no zone). Returns epoch ms, or NaN when missing.
 */
export function parseRecordDate(value: string | undefined | null): number {
  if (!value) return NaN;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  return Date.parse(hasZone ? value : `${value}Z`);
}
