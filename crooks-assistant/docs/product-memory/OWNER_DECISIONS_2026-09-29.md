# Owner Decisions - 2026-09-29

Recorded from the owner's explicit instructions in a Claude Code engineering session on 29 September 2026. The session worked directly from the owner's messages, not from the engineering loop. It produced the research and plan the venture engine builds on, and the first increment described in [VENTURE_ENGINE_V1.md](./VENTURE_ENGINE_V1.md).

## A venture engine: CLIVE researches, launches and runs new product businesses

The owner, verbatim, first:

> I want to start a new fully AI dropping dropshipping business where AI videos are created automatically for each of these things. A whole post schedule is created for all socials. Best, highest quality content is made, the best products are found. For example, rooog.co, babyrideshop, roosddflare. These are all examples of dropshipping businesses that have found products that are highly marketable, such as baby costumes, riders, sparking boots, and lots of other random stuff. I want you to create me the perfect plan to create an app that generates businesses like this by doing research, seeing what's successful, seeing what content blows up and what content not, that doesn't blow up. It needs to make perfect versions of all of these dropshipping businesses and find perfect products. Je, that it is integratable to the whole Clive engine. So it can be functioning together. I want this to be flawless every step of the way from creating the business ideas to finding the products to creating the content and the content schedule. You need to do the deepest research possible on all of these businesses and how they work and what makes them successful and the best way to replicate that success.

Then, while the research ran ("Levin Labs" is ElevenLabs, as dictated):

> also research how, from end to end, Clive could do the product research, product ideas, a Levin Labs video creation or an alternative method of video creation, guiding users exactly when to post, how to post, creating the Shopify store or related store such as CJ dropshipping store for selling the products, how to market, when to market, what to price the products at, doing all of the customer support, and basically managing the whole company end to end. I, in theory, want this to happen by me pressing a button and the business, the product, the videos, when to post, how to post, all being done for me. This needs to be done with the idea that there is relatively little to zero human involvement and it will entirely be funneled by AI.

Then, after reading the plan:

> start building it into clive

Recorded:

- **Direction.** CLIVE gains a venture engine that researches, plans and in later increments launches and runs new product businesses from one button (DEC-061, IDEA-094, FEAT-074).
- **Started.** The first increment: a deterministic, read-only planning core that nothing in CLIVE calls ([VENTURE_ENGINE_V1.md](./VENTURE_ENGINE_V1.md) section 3). It reaches production only through the normal pull request, a green acceptance run on its exact head and an independent exact-SHA review.
- **Not decided by these words.** Spending, stores, listings, posts, messages to customers, new credentials or connectors, changes to protected paths and deployment stay owner-gated exactly as before (DEC-005, DEC-027, and CURRENT_TRUTH's list of what is still the owner's).

## Not yet ruled (the owner's)

1. **Sequencing.** F0 ("Finish everything already started before starting anything new", ROADMAP) is an active owner rule. This entry records the instruction to start; whether the venture engine is an exception to F0, or waits behind the finish list and the approved next phase, is the owner's to rule.
2. **Exposure.** Whether and when the planning core becomes a tool CLIVE's model can call. That edits the protected gate, so it is the owner's change ([VENTURE_ENGINE_V1.md](./VENTURE_ENGINE_V1.md) section 5).
3. **First markets and categories.** The research recommends UK customers and adult, unregulated, visually demonstrable products first, with baby and children's categories off by default.
4. **Separation from CROOKS LDN.** Whether ventures run under their own company, brands and platform accounts, given that platform bans follow the verified person across every brand.
5. **"Zero human involvement".** The research's lawful form is a one-time genesis session (identity, KYC, account ownership, a spending envelope) and then standing, capped, revocable mandates the agents work inside; building mandates is its own increment and decision.
