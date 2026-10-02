/**
 * Variant resolution for a product page, generic over any number of options.
 *
 * The website hit two bugs here that this is written to avoid:
 *  - a tee is Colour AND Size, so a picker that assumes one option posts the
 *    wrong garment or can never resolve one;
 *  - a size can be sold out in one colour and not another, so "is M
 *    available?" depends on what else has been chosen.
 */
import type { Product, Variant } from './types';

export type Selection = Record<string, string | undefined>;

export function isSizeOption(name: string): boolean {
  return /size/i.test(name);
}

/** The variant named by a complete selection, or null if any option is unchosen. */
export function resolveVariant(product: Product, sel: Selection): Variant | null {
  if (product.options.some((o) => !sel[o.name])) return null;
  return (
    product.variants.find((v) => v.selectedOptions.every((so) => sel[so.name] === so.value)) ?? null
  );
}

/**
 * Could this value still lead to something buyable, given the other choices
 * already made? Drives the struck-through state on each button.
 */
export function isValueAvailable(product: Product, sel: Selection, option: string, value: string): boolean {
  return product.variants.some(
    (v) =>
      v.availableForSale &&
      v.selectedOptions.every((so) =>
        so.name === option ? so.value === value : !sel[so.name] || sel[so.name] === so.value,
      ),
  );
}

/** A product with one variant and no real options ("Default Title") needs no picker. */
export function isSingleVariant(product: Product): boolean {
  return product.variants.length === 1 && product.options.length === 1 && product.options[0].name === 'Title';
}

/**
 * Starting selection. Nothing is pre-chosen except options with exactly one
 * value — a size rendered as already selected reads as a decision the
 * shopper made, which is how the wrong size ends up in a bag.
 */
export function initialSelection(product: Product): Selection {
  const sel: Selection = {};
  for (const o of product.options) if (o.optionValues.length === 1) sel[o.name] = o.optionValues[0].name;
  return sel;
}
