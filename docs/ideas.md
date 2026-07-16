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

## Cellar valuation — BUILT 2026-07-16

The sketch below was implemented as designed: `ValuationRun` +
`VintageValuation` (assistant), the cost-basis rule in
`assistant/valuation.py`, the page at `/assistant/value/` ("Value my
cellar" button → background thread → per-vintage rows → headline +
held-at-time series). Knowledge-based estimates (no web search per run —
consistency over precision for a quarterly trend; revisit if estimates
prove too noisy). Remaining from the open questions: NV rolling-release
pricing is just "price the current release" in practice; wishlist/tried
wines are NOT valued (drinkable bottles only), and dossier typical_price
is provided to the valuation prompt as context but never stored as a value.

### Measured findings (live probe, 2026-07-16 — scripts/dev/valuation_compare.py)

- Memory vs web on 3 dev wines: **$0.012 vs $0.94 (~80×)** — search-result
  pages are token-fat (~50k input/wine). Naive web at 200 wines ≈ $40–60/run.
- Web values ran **16–43% higher** than memory across all three — memory
  prices skew systematically low (training-vintage prices). Bias looks
  systematic, which a *trend* tolerates; the level understates gain.
- **Model-version risk:** a memory-based series is consistent only within a
  model version — when ANTHROPIC_MODEL changes the series can step-jump.
  TODO when hybrid lands: record the model on each ValuationRun.
- **PARKED until the real cellar is loaded (the owner):** top-K hybrid — memory
  for all + web pass for the ~10–15 highest-value bottles, with the web
  extraction routed to Haiku 4.5 (input tokens dominate web cost; extraction
  is mechanical → ~$1–2/run instead of $50). First real use case for a
  per-feature model override in sommelier.
- Open source / own-search rejected: search access, not tokens, is the moat;
  a quarterly $4–8/year problem doesn't justify scraper maintenance.

## Original valuation sketch (implemented)

**Purpose (the owner's words, roughly):** not investing — "if I'm buying bottles
to hold and the value isn't rising, there's no point in buying to hold vs
just having ready inventory." So the questions are: what's the cellar worth
vs what I paid, and are my *hold* purchases appreciating?

**Model sketch (needs stress-testing before building — deliberately not
implemented yet):**

1. **`purchase_price` stays actuals-only, forever.** Never AI-filled, never
   edited by suggestion — it's the ground truth for "how good are my buying
   decisions." Unknown paid price = null, never fabricated.
1b. **Cost basis rule (the owner, 2026-07-16) — how the cost-vs-value series
   handles missing purchase prices:** every bottle's baseline is its
   `purchase_price` if set, **else its first valuation mark**. Gains/trends
   are always measured against the baseline, so:
   - the "cellar cost" line = sum of bases; "cellar value" line = latest
     valuation of held bottles;
   - a bottle with no purchase price shows zero gain at its first mark
     (no phantom appreciation from missing data) and real trend thereafter;
   - purchase_price stays untouched and pure for per-bottle analysis;
   - known bias: a bottle held long before its first mark has a late basis,
     so its gain is *understated* — conservative in the right direction for
     the "is buy-and-hold worth it" question.
   Report basis composition alongside ("cost basis: 140 actual, 60
   first-mark") so the number is never mistaken for all-actuals.
2. **Valuation is explicit and quarterly.** A "value my cellar" action (per
   the owner: he'll run it ~once a quarter) sweeps drinkable bottles in one
   batched AI pass. No background/automatic valuation.
3. **Store per-vintage valuation rows, not just cellar totals.** A
   `VintageValuation(vintage, per_bottle_value, valued_at, note)` row per
   run. This is the stress-test insight: cellar-total snapshots confound
   *appreciation* with *composition changes* (buying more raises the total
   without anything appreciating). Per-vintage history lets us compute the
   honest number: like-for-like appreciation on held bottles ("this Monte
   Bello: paid $180 in 2026, est $210 now"), aggregated. Totals derive from
   the rows.
4. **Honesty rules:** values are estimates and marked as such everywhere;
   wines the AI can't price get skipped with a note, never guessed; sizes
   scale from the 750 ml basis; consumed bottles keep their valuation
   history (what did drinking it "cost" vs its market value).
5. **Later, the chart** (dataviz skill): paid vs estimated over time, plus
   the like-for-like appreciation line — the one that actually answers
   "should I keep buying to hold?"

**Open stress-test questions:** how to price NV wines with rolling releases;
whether dossier `typical_price` should seed a first estimate at research
time or stay display-only (current lean: stay display-only, valuation runs
are the single source); whether wishlist/tried wines get valued (lean: no —
cellar bottles only).

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
