"""The venture engine's planning core: how a new product business is priced, screened, scored,
tested and timed before anything is spent.

Everything here is arithmetic over values the caller supplies. It reads no file it is not
handed, calls no network, asks no model and changes nothing: it cannot spend, list, publish,
order or contact anyone. Its answers are planning estimates for the owner to judge, never
results. A break-even ROAS is a target, a kill line is a rule to apply to real numbers later,
and a clear compliance screen means only that no rule here blocked the product.

Nothing in CLIVE calls this package yet. Exposing it to CLIVE's model is a separate owner
decision, because the tool list lives in the protected gate; anything that spends, lists,
publishes or contacts anyone is a new reviewed mutation behind the owner's switches. See
docs/product-memory/VENTURE_ENGINE_V1.md.

Modules:
    markets     where a venture sells: currency and how consumer tax sits in the price
    economics   contribution per order, break-even ROAS and CPA, the price floor
    pricing     price presentation, the free-shipping threshold, reference-price checks
    rules       kill and scale rules for creative and product tests
    scoring     product score and lifecycle stage from market and test signals
    compliance  the category screen that runs before any score
    seasons     retail dates by market and launch-timing arithmetic
    brief       one candidate in, one decision package out
"""
