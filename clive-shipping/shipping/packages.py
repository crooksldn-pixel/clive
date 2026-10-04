"""Packages: real ones the merchant entered, chosen for a shipment without asking again.

Nothing here invents dimensions or weights. The first time a label is needed and no package
exists, readiness asks for the real one once; after that:

  1. the package last used for this exact mix of products (learned when a label is bought),
  2. otherwise the default package,
  3. otherwise ask (only ever when there are no packages at all).

The signature is deliberately simple (products and quantities) so a later stage can replace it
with inference from product types and sizes without changing what is stored.
"""

from __future__ import annotations

from shipping.models import CustomsLine, PackagePlan, PackagePreset, ShopConfig
from shipping.store import Store, new_id


def signature(lines: list[CustomsLine]) -> str:
    return "|".join(sorted(f"{ln.product_id or ln.title}x{ln.quantity}" for ln in lines))


def preset(cfg: ShopConfig, preset_id: str | None) -> PackagePreset | None:
    return next((p for p in cfg.packages if p.id == preset_id), None)


def items_weight_g(lines: list[CustomsLine]) -> int | None:
    if any(not ln.unit_weight_g for ln in lines):
        return None
    return sum(ln.unit_weight_g * ln.quantity for ln in lines)


def plan(
    store: Store, cfg: ShopConfig, lines: list[CustomsLine], current: PackagePlan | None
) -> PackagePlan | None:
    """The package for these lines, or None when no package exists yet (ask once)."""
    weight = items_weight_g(lines) or 0
    chosen, source = None, "default"
    if current is not None and current.source == "merchant":
        chosen, source = preset(cfg, current.preset_id), "merchant"
    if chosen is None:
        learned = store.package_choice(cfg.shop, signature(lines))
        if preset(cfg, learned):
            chosen, source = preset(cfg, learned), "learned"
    if chosen is None:
        chosen, source = preset(cfg, cfg.default_package_id), "default"
    if chosen is None:
        return None
    return PackagePlan(
        preset_id=chosen.id,
        name=chosen.name,
        length_mm=chosen.length_mm,
        width_mm=chosen.width_mm,
        height_mm=chosen.height_mm,
        empty_weight_g=chosen.empty_weight_g,
        items_weight_g=weight,
        source=source,
    )


def add(
    cfg: ShopConfig,
    *,
    name: str,
    length_cm: float,
    width_cm: float,
    height_cm: float,
    empty_weight_g: int,
    actor: str,
) -> PackagePreset:
    dims = [length_cm, width_cm, height_cm]
    if not name.strip():
        raise ValueError("Give the package a name, e.g. 'Standard mailer'.")
    if any(not 1 <= d <= 200 for d in dims):
        raise ValueError("Each side should be between 1 and 200 cm.")
    if not 1 <= empty_weight_g <= 5000:
        raise ValueError("The empty package should weigh between 1 g and 5 kg.")
    p = PackagePreset(
        id=new_id("pkg"),
        name=name.strip()[:60],
        length_mm=round(length_cm * 10),
        width_mm=round(width_cm * 10),
        height_mm=round(height_cm * 10),
        empty_weight_g=int(empty_weight_g),
        created_by=actor,
    )
    cfg.packages.append(p)
    if cfg.default_package_id is None:
        cfg.default_package_id = p.id
    return p
