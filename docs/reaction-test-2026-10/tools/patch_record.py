import json, sys
sys.path.insert(0, sys.argv[1])
from rx_settings import SETTINGS
p = sys.argv[2]
s = open(p).read()

a = '''    <div class="crk-grid">
      {%- comment -%} ---------- gallery ---------- {%- endcomment -%}'''
b = '''    {%- comment -%}
      Reaction test (snippets/crooks-reaction.liquid). One per page, from a
      "Reaction test" block. It follows the buy panel on mobile; from 960px
      it sits under the gallery and the panel spans both rows, so ADD TO BAG
      stays in view beside it (crooks-reaction.css). No block, no change.
    {%- endcomment -%}
    {%- liquid
      assign crk_rx = nil
      for block in section.blocks
        if block.type == 'reaction' and block.settings.image_reacted != blank
          assign crk_rx = block
          break
        elsif block.type == 'reaction' and request.design_mode
          assign crk_rx = block
          break
        endif
      endfor
    -%}
    <div class="crk-grid{% if crk_rx %} crk-grid--rx{% endif %}">
      {%- comment -%} ---------- gallery ---------- {%- endcomment -%}'''
assert s.count(a) == 1; s = s.replace(a, b)

a = '''          {%- endform -%}
        {%- endif -%}
      </div>
    </div>

    {%- comment -%} ---------- collapsible record sections ---------- {%- endcomment -%}'''
b = '''          {%- endform -%}
        {%- endif -%}
      </div>

      {%- if crk_rx -%}
        <div class="crk-rx-slot" {{ crk_rx.shopify_attributes }}>
          {%- render 'crooks-reaction',
            s: crk_rx.settings,
            product: product,
            rx_id: crk_rx.id,
            sizes: '(min-width: 960px) 55vw, 100vw',
            sizes_reacted: '(min-width: 1180px) 560px, (min-width: 960px) 46vw, (min-width: 768px) calc(100vw - 132px), calc(100vw - 100px)',
            placement: 'product'
          -%}
        </div>
      {%- endif -%}
    </div>

    {%- comment -%} ---------- collapsible record sections ---------- {%- endcomment -%}'''
assert s.count(a) == 1; s = s.replace(a, b)

a = '''  "blocks": [
    { "type": "@app" },'''
block = {"type": "reaction", "name": "Reaction test", "limit": 1, "settings": SETTINGS}
b = '''  "blocks": [
    { "type": "@app" },
    ''' + json.dumps(block, indent=2, ensure_ascii=False).replace('\n', '\n    ') + ','
assert s.count(a) == 1; s = s.replace(a, b)
open(p, 'w').write(s)
print('patched')
