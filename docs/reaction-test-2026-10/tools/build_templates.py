import json, re, sys
src, outdir = sys.argv[1], sys.argv[2]
raw = open(src).read()
raw = re.sub(r'^/\*.*?\*/\s*', '', raw, flags=re.S)
base = json.loads(raw)

def make(name, reacted, settings):
    t = json.loads(json.dumps(base))
    main = t['sections']['main']
    s = {
        "image_reacted": reacted,
        "reacted_alt": "",
        "eager": False,
        "brush": 12,
        "teaser": True,
        "eyebrow": "Material evidence",
        "test_word": "Test",
        "reaction_label": "",
        "hint": "",
        "states": "",
        "status_word": "Status",
        "full_label": "View full reaction",
        "original_label": "View original",
        "reset_label": "Reset",
        "sr_text": "The photo is interactive: drag across it to see the reaction. View full reaction shows the whole reacted garment.",
        "space_top": 0,
        "space_bottom": 0,
    }
    s.update(settings)
    main['blocks']['reaction'] = {"type": "reaction", "settings": s}
    order = main['block_order']
    # after the app block, before the custody steps (render position is fixed by type)
    order.insert(1 if order and not order[0].startswith('s') else 0, 'reaction')
    json.dump(t, open(f'{outdir}/templates/product.{name}.json', 'w'), indent=2, ensure_ascii=False)

make('reaction-hydrocuff', 'shopify://shop_images/crooks-reaction-placeholder-hydrocuff-water.png', {
    "reaction": "water",
    "test_number": "02",
    "heading": "Rain brings out the cuffs",
    "copy": "<p>The HydroCuff shell is water-activated: where it gets wet, the cuff pattern comes through. Swipe across the photo to apply water.</p>",
})
make('reaction-puffa', 'shopify://shop_images/crooks-reaction-placeholder-puffa-heat.png', {
    "reaction": "heat",
    "test_number": "01",
    "heading": "Changes with temperature",
    "copy": "<p>The Double-Agent shell is heat-reactive: its appearance changes with temperature. Drag across the photo to apply heat.</p>",
})
print('ok')
