import json, sys
sys.path.insert(0, sys.argv[1])
from rx_settings import SETTINGS
schema = {
  "name": "Crooks — Reaction test",
  "tag": "section",
  "class": "crk-rx-section-wrap",
  "settings": SETTINGS,
  "presets": [{"name": "Crooks — Reaction test"}],
  "disabled_on": {"groups": ["header", "footer"]}
}
body = '''{%- comment -%}
  CROOKSLDN — reaction test, standalone. For any page: a landing page, the
  homepage, or a product template where it should sit away from the buy
  panel. On the product record itself, use the "Reaction test" block of
  Crooks — Product Record instead (it sits under the buy panel).
  Everything is in snippets/crooks-reaction.liquid.
{%- endcomment -%}
<div class="crk-root crk-record crk-rx-section">
  <div class="crk-wrap">
    {%- render 'crooks-reaction',
      s: section.settings,
      product: product,
      rx_id: section.id,
      sizes: '(min-width: 1180px) 580px, (min-width: 960px) 47vw, (min-width: 768px) calc(100vw - 132px), calc(100vw - 100px)',
      layout: 'wide',
      placement: 'section'
    -%}
  </div>
</div>

{% schema %}
''' + json.dumps(schema, indent=2, ensure_ascii=False) + '''
{% endschema %}
'''
open(sys.argv[2], 'w').write(body)
