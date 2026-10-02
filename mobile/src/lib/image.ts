/**
 * Shopify's CDN resizes on request. Asking for roughly the pixels a tile
 * needs, instead of the 3000px original, is most of a catalogue's load time.
 */
export function sized(url: string | undefined | null, width: number): string | undefined {
  if (!url) return undefined;
  const w = Math.min(2048, Math.ceil(width / 50) * 50);
  return `${url}${url.includes('?') ? '&' : '?'}width=${w}`;
}
