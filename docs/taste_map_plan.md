# Taste map — implementation plan

> **STATUS: all four phases BUILT (2026-07-16).** D first (open bottles),
> then A (style vectors), B (map page at /map/), C (prospects at
> /assistant/prospects/). This doc is now the design record; as-built
> deviations are noted inline. To populate real data: run
> `assistant_backfill_styles` once the cellar is loaded.

Commissioned 2026-07-16. the owner's decisions: **per wine** (not per vintage —
"I'm not sophisticated enough to differentiate via vintage yet"); **all wines
in the database** with a filter to cellar-only; AI-suggested "wines you might
like" are welcome but **clearly marked** and **cost-bounded** — either a
byproduct of research already being run, or an explicit user request. Never
background generation.

## Phase A — style vectors

- `Wine.style_vector` (JSON) + `Wine.style_caption` (short text). Schema
  `StyleVector`: 0–10 scales for body, acidity, tannin, sweetness,
  fruit↔savory, oak, intensity; a one-line caption; a confidence note.
- New sommelier function `style_vector(wine)` — inputs it already has:
  varietals, appellation, producer region, dossier, our tasting notes.
  ~1–2¢/wine.
- Generation triggers (no auto-spend surprises):
  1. `cellar_backfill_styles` management command (idempotent, skips wines
     that have one; `--refresh` to redo). ~$2–4 one-time at 200 wines.
  2. Piggyback: when `research_wine` runs, refresh the style vector in the
     same flow (it's already an AI moment the user initiated).
- Tests: mocked-client schema mapping; command idempotency.

## Phase B — the map page

- Projection: 7-dim PCA to 2-D in pure-stdlib Python (~30 lines; no numpy,
  no JS math). Computed per request — trivial at a few hundred wines; cache
  later only if it ever isn't.
- `/map/` (lives on the **More** tab — the tab bar stays at five, per house
  rule). Server-rendered inline SVG scatter:
  - marks = glass dots (validated palette, hollow ring for sparkling),
  - Marcellus labels via tap/hover `<title>` + link to the wine page,
  - filters: cellar-only toggle (default per the owner: show all, one tap to
    cellar), wine-type,
  - **emphasis mode**: arrive via "wines like this" link on a wine detail
    page (`?focus=<id>`) — that wine + its nearest neighbors stay lit,
    everything else grays out.
- Axis honesty: label axes only by what the PCA loadings actually say
  ("lighter ↔ fuller", "fruit ↔ savory") or leave them unlabeled. Never
  invent axis names the math doesn't support.
- Wines without a style vector yet: listed in a "not yet mapped" note with a
  link to run the backfill — never plotted at (0,0).

## Phase C — prospects: the unvetted staging area

**The taxonomy (the owner, 2026-07-16): the catalog is *vetted* — wines the owner
decided are part of his wine life (cellar, wishlist, tried — ownership NOT
required). Prospects are *unvetted* captures.** A separate model, so raw
captures and AI suggestions never masquerade as catalog:

- `Prospect(BaseModel)`: producer_name, wine_name, wine_type, varietals,
  region, `why` (AI reasoning or "scanned at K&L, didn't buy"), `source`
  (`research` | `requested` | `scanned`), optional link to the LabelScan
  (keeps the photo), status (`watching` | `promoted` | `dismissed`).
- **Channel 1 — research byproduct (no extra API call):** the
  `research_wine` schema gains `worth_watching` (0–2 entries, only when the
  research genuinely surfaced something). `source=research`.
- **Channel 2 — explicit ask (one call per click):** "Suggest 5 wines to
  watch for" button + optional hint box ("under $40", "more like the
  Tempier"), grounded in taste profiles + inventory + ratings.
  `source=requested`, ~5–8¢ per click. 
- **Channel 3 — store scan, didn't buy:** the label-scan result screen gains
  a fourth path alongside the intake modes: "save for later" → Prospect with
  the label photo attached. `source=scanned`. Captures the info without a
  catalog decision.
- **Promotion = a decision, not a receipt.** "Found it / want it / tasted
  it" → the standard prefilled intake form, where the existing three modes
  (cellar / wishlist / tried) ARE the vetting gate. No purchase required to
  promote; the human choosing a mode is the vetting. Prospect flips to
  `promoted` and links to the created wine.
- Page: "Keep an eye out" under More — cards show the why + source badge
  (+ label thumb for scans); actions: Promote, Dismiss.
- On the map: prospects render as **dashed-ring dots** (clearly not
  catalog), only when they have style vectors (explicit-ask prospects get
  one in the same call; research byproducts don't, staying off-map until
  promoted). As built: no separate toggle — prospects show unless
  cellar-only mode, which inherently excludes them.

## Phase D — open bottles (the Porto haul) — BUILT 2026-07-16

Port and madeira are drunk over weeks; a bottle used to be atomic
(in cellar → consumed). As built, per the owner: **purely opt-in, no type
logic** — "I don't need a complicated model to figure out which wines get
the workflow."

- Normal flow unchanged: **Drink** = consumed, one tap.
- A small **"not finishing it" checkbox** beside Drink → `Status.OPEN` +
  `opened_date` instead. That checkbox is the entire opt-in.
- Open bottles: dashboard **"Open now"** card (days-open counter, no
  style-aware hints — dropped by the owner), **Finish** action → consumed →
  tasting-note prompt, badge on the wine page.
- Open bottles count as drinkable stock everywhere (dashboard counts,
  wine-list counts, ready/drink-soon, wine value) and the sommelier's
  inventory summary marks them "ALREADY OPEN" so pairing can prefer them.

## Order & cost

**D first** (the Porto bottles are physically arriving), then A → B → C;
each phase lands working + tested. AI cost: one-time backfill ~$2–4; map
browsing costs nothing; prospects only on research piggyback, explicit
click, or a scan the owner chose to save.
