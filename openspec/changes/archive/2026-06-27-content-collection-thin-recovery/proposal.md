## Why

After the recent re-crawl, 30 companies remain stuck at `status: "thin"` despite having recoverable content. Investigation isolated three distinct causes, each fixable: (1) JS-rendered SPAs whose homepage renders headlessly but whose **sub-pages are fetched via plain HTTP only** and return empty shells → dropped; (2) sites whose substantive pages live on **non-standard paths** (`/learn`, `/knowledge`, `/profit-model`) that the fixed durable-path tier list doesn't recognise → silently skipped; (3) **small-but-complete brochure sites** (a single 10KB homepage) mislabeled "thin" by the 3-page threshold even though the content is ample for summarisation.

## What Changes

- **Headless sub-page fetching for JS-sites.** When the homepage was rendered headlessly (the SPA signal), sub-pages SHALL also be fetched headlessly — plain-HTTP sub-pages on a JS-site return the empty SPA shell and get dropped. Static-HTML sites keep the fast plain-HTTP path unchanged.
- **Fallback selection tier for non-standard paths.** When fewer than 3 durable-pattern pages are selected, the stage SHALL fill remaining slots with the shallowest same-domain internal links (path depth 1 first), so sites using non-standard path conventions (`/learn`, `/knowledge`) are not silently skipped. This sits alongside the existing fresh-content (tier-3) fallback and never replaces a durable match.
- **Substantial-single-page "ok".** A 1–2 page crawl whose collected markdown is substantial (≥ a named character threshold) SHALL be `status: "ok"`, not `"thin"` — a complete brochure site with enough content to summarise is not a failure. Below that threshold, 1–2 pages remain `"thin"`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `content-collection`: the "Page Selection" requirement gains a fallback-to-shallow-internal-links rule; the "Headless Browser Fallback" requirement extends headless rendering to sub-pages when the site is detected JS-rendered; the "Status Tracking" requirement relaxes the `"thin"` classification for substantial 1–2 page crawls.

## Impact

- `pipeline/content_collection/core.py` — propagate a JS-site signal from the homepage render to sub-page fetches; relax the `pages_collected` status gate with a substantial-content threshold.
- `pipeline/content_collection/crawl.py` — `select_urls` gains a shallow-link fallback when durable tiers underfill the slate.
- `pipeline/content_collection/render.py` — expose a sub-page render entry point (render an arbitrary URL, not just the homepage).
- `tests/test_content_collection.py` — cover the three new behaviours.
- No upstream/downstream stage changes; the output schema (`_meta.json`, page `.md` files) is unchanged.
