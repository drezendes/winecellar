# Ideas parking lot

Bigger features the owner has floated but not commissioned. Sketched here so a
future session can pick one up without re-deriving the thinking. Neither is
started; both are deliberately deferred.

## Taste map — PROMOTED to `docs/taste_map_plan.md` (2026-07-16)

Commissioned with the owner's decisions (per-wine, all-DB + cellar filter,
cost-bounded prospects). The sketch below is superseded by the plan.

## Original taste map sketch (superseded)

**Goal:** a 2-D map of the cellar where distance = taste similarity, so you can
look at a wine you love and see what else lives nearby (in the cellar, on the
wishlist, or in the tried list).

**Sketch:**
1. **Style vector per wine** — a new sommelier function returns structured
   0–10 scales: body, acidity, tannin, sweetness, fruit↔savory, oak, intensity
   (+ a one-line style caption). Inputs it already has: varietals, appellation,
   dossier, our tasting notes. One cheap AI call per wine (~1–2¢), run at
   intake/research time + a `cellar_backfill_styles` management command for the
   existing collection (~$2–4 one-time at 200 wines). Store as JSON on Wine.
2. **Projection** — PCA to 2-D in Python (numpy already ships with nothing…
   we have no numpy; a 7-dim PCA is 30 lines of stdlib math, or add numpy —
   decide then). Precompute server-side per the house data-to-page rule; no JS
   math libraries.
3. **Render** — inline SVG scatter using the design system: glass dots as the
   marks (validated palette, hollow ring for sparkling), Marcellus labels on
   hover/tap via `<title>` + a detail link. Highlight-one-gray-the-rest
   "emphasis" mode when arriving from a specific wine ("wines like this").
4. **Honesty check** — the axes are latent, so label them by what the loadings
   say (e.g. "lighter ↔ fuller", "fruit ↔ savory") or not at all; never invent
   axis names the math doesn't support.

**Open questions for the owner when commissioned:** map per wine or per vintage?
Should "wines like this" also search *outside* the cellar (a buying tool) or
stay inventory-only?

## Producer world map — pins for every producer (the owner, 2026-07-16)

**Goal:** a world map with a pin per producer; tap a pin → that producer's wines.

**Sketch:**
1. **Coordinates** — extend producer research/creation with a structured
   lat/long (AI supplies it from region+name; store on Producer with a
   `location_confidence` note). Backfill command for existing producers.
   Cross-check option later: free Nominatim geocoding, but AI-from-region is
   plenty for pin-on-a-world-map accuracy.
2. **Render, two tiers:**
   - **Tier 1 (fits the app, zero deps): an engraved SVG world map** — a
     single vendored world outline SVG, pins plotted by equirectangular
     projection, styled like an old atlas plate. On-brand for "Cellar book",
     works offline/PWA, no tile servers. Wine regions cluster (France/Italy/CA),
     so add a Europe inset or tap-to-zoom on the dense area.
   - **Tier 2 (if real zoom/pan is wanted): Leaflet self-hosted** + OSM tiles.
     Tiles are an external network dependency and visually generic — only if
     tier 1 proves too cramped.

**Recommendation:** tier 1 first; it's a weekend, matches the design system,
and the dataset (dozens of producers, not thousands) doesn't need slippy-map
power.
