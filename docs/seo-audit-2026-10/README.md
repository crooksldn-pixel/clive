# Promptd SEO/GEO audit (October 2026): implementation evidence

The audit is Promptd's "CrooksLDN AI search & website review" (October 2026, 20
pages). `REPORT.md` takes it finding by finding: before, change, where, evidence,
status. This folder holds the evidence the report cites. `docs/` is listed in
`.shopifyignore`, so none of it is uploaded with the theme.

## Where the change is

| State | Where |
|---|---|
| Code updated | This branch, and the unpublished theme "CROOKSLDN — SEO-GEO audit fixes 2026-10-08" (#206765785431), a copy of live taken on 8 Oct 2026 |
| Deployed to live | No. The live theme (#206162461015) is unchanged |
| Verified on live | No. Verified on #206765785431, rendered on the live store with its live data |

## Files

| Path | What it is |
|---|---|
| `findings.json` | The audit as a checklist: 51 findings with section, finding, recommendation, severity, scope and who controls the fix |
| `evidence/before-after.tsv` | One row per URL (50): title, length, meta description, robots, h1, canonical and JSON-LD types, before and after |
| `evidence/head/*.html` | The SEO tags of 12 key pages, copied verbatim from the rendered page source, before and after |
| `evidence/jsonld/*.json` | The full JSON-LD of the homepage, a product, a collection and the FAQ, before and after |
| `evidence/extract/{before,after}/` | The raw extraction for every URL (`index.tsv` maps file to URL) |
| `evidence/lcp-mobile-390.json` | The largest-paint element at 390×844 on four templates, live theme and new theme |
| `evidence/images-92-measured.tsv` | The audit's 92 image URLs re-fetched as a browser: width, type served, bytes |
| `evidence/regression/` | The storefront walk on both themes (`*-report.json`) and side-by-side screenshots |
| `evidence/theme-check.txt` | Shopify theme-check before and after, and what changed |
| `evidence/robots.txt`, `sitemap-urls.txt` | robots.txt and the sitemap's URLs at the time of the baseline |
| `tools/` | The scripts that produced the evidence |

## Re-running it

Against any theme, with `SP` a scratch folder holding `audit/before/index.tsv`
(the URL list from `evidence/extract/before/index.tsv`):

```sh
tools/fetch_after.sh "$SP" <theme id>          # fetch every URL through the theme preview, extract SEO facts
CJ=<cookie jar> node tools/lcp.mjs "$SP" out.json <urls…>   # largest-paint element at 390x844
CJ=<cookie jar> node tools/reg.mjs "$SP" <label>             # storefront walk with screenshots
python3 tools/seo_extract.py page.html <url>   # one page
```

The browser scripts need Playwright with Chromium; they fetch through `curl` so
they work behind a proxy, and they block analytics requests.
