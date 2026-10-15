# Live re-check, 15 October 2026

The 9 October report's checks re-run on the live site after theme #207020425559
("CROOKSLDN — REVIEW: SEO + Tee Week + Returns") was published at 15:52 that day.
The status report built from these results is the Claude doc "CROOKSLDN SEO/GEO:
Promptd audit status".

| File | What it is |
|---|---|
| `extract/index.tsv`, `extract/json/` | The same 52 audit URLs fetched as Googlebot from live; SEO facts per page (`tools/seo_extract.py`) |
| `titles-descriptions.tsv` | Per URL: title length before / preview / live, live title, description lengths, robots, h1 count, invalid JSON-LD, words, and whether title and description match the 8 Oct preview (`tools/cmp1015.py`) |
| `checks.txt` | Offers with shipping and seller, graph references, Gmail mentions, largest-image attributes, collection intros and product counts, reviews, blog, variant canonical, FAQ (`tools/checks1015.py`) |
| `lcp-mobile-390.json` | Largest-paint element at 390×844 on 4 templates, live |
| `images-92-measured.tsv` | The audit's 92 image URLs: bytes on 9 Oct (WebP), now as WebP, now as PNG |
| `robots.txt`, `sitemap-urls.txt` | As served on 15 Oct (rules unchanged; 42 URLs, the same list) |
