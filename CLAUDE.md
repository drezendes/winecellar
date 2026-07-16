# Winecellar — Claude Context

> CLAUDE.md holds **house rules, durable guidance, and current state** only.
> History and detail live in `docs/`; open todos in `TODO.md`.

## Project

Personal wine cellar app for the owner + household (2 shared-cellar accounts): inventory,
drinking windows, tasting notes, plus an AI sommelier (Claude API) for label scanning,
food pairing, restaurant-menu photo advice, and distributor-email buying suggestions.
Full plan/architecture: `docs/plan.md`.

## Stack

- Django 5.2 / Python 3.12, SQLite, server-rendered templates + HTMX (vendored in
  `static/js/`), mobile-first CSS.
- `uv` manages deps (`pyproject.toml` + `uv.lock`, `.venv`). Run everything via
  `.venv\Scripts\python.exe` — never global Python.
- LLM: `anthropic` SDK, model `claude-opus-4-8`, adaptive thinking, structured outputs
  via `client.messages.parse()` + Pydantic. All calls go through `assistant/sommelier.py`.
- Secrets ONLY in gitignored `.env` (see `.env.example`): `ANTHROPIC_API_KEY`,
  `DISTRIBUTOR_IMAP_*`.
- Tests: pytest + pytest-django, in `tests/` (configured in `pyproject.toml`).
  Run: `.venv\Scripts\python.exe -m pytest tests -q`

## Architecture

```
config/       # settings.py (single module, env-driven), urls.py
core/         # BaseModel (uuid pk + created/modified) — all models inherit it
cellar/       # inventory: Producer, Wine, Vintage, Bottle, TastingNote
assistant/    # AI features: sommelier.py service, scan/menu/email models, ApiUsage
templates/    # project-level; extend base.html
static/       # app.css, vendored htmx
scripts/dev/  # durable one-off/analysis scripts (not scratchpad)
tests/
```

## Decisions

- **Model: Opus 4.8 everywhere, deliberately.** At the owner's volume (~150 bottles,
  ~20 distributor emails/week, ~a case/month) estimated spend is **~$8–10/month**,
  with email digestion ~2/3 of it (each grounded call carries a ~4k-token inventory
  summary). One-time initial load: ~$5 for 150 label scans; dossiers ~15–20¢ each
  (two calls + web-search fees). Tiering (Sonnet for digestion) would save ~$4/mo —
  judged not worth the quality risk since every feature is a taste-judgment task.
  Revisit with data from the Usage page if volume grows; `ANTHROPIC_MODEL` in `.env`
  switches globally, and a per-feature override is a ~5-line change to `_parse`.
- **No multi-provider abstraction, deliberately.** `sommelier.py` is the seam:
  the app only sees Pydantic schemas (`pair_food(dish) -> PairingAdvice`), never
  Anthropic types. If the owner ever wants a GPT/Gemini bake-off, reimplement the
  ~6 functions inside that one module — do NOT build a provider layer preemptively.
- **Branch is `master`** (the owner's preference; ignore GitHub's main-branch nudge).
- **Dossier research is a button, not automatic on intake** — keeps store-side
  scan-and-add fast; auto-research after label scan is a ~3-line change if wanted.
- **Menu picks are ranked lists with prices** because the owner's workflow is "show me
  what's most like my taste, I choose the price point" — don't collapse categories
  back to single bottles.
- **Bottom tab bar stays at five tabs, max.** the owner chose tabs over a hamburger
  drawer (2026-07-15) but is torn: **if a sixth primary destination ever wants in,
  stop and re-ask him about switching to a drawer** — don't squeeze it in.
  Secondary pages live on the More tab (`/more/`).
- **Async AI work = daemon thread + status on the row, deliberately no queue.**
  Dossier research runs in a `threading.Thread` (assistant/tasks.py); the state
  machine lives on `Vintage.dossier_status`, and a stale `pending` (>15 min,
  `RESEARCH_TIMEOUT`) ages into `failed` with a retry button. A household app
  doesn't need Celery — reuse this pattern for future slow AI features.
- **Uploads are normalized to browser-safe JPEG at save** (assistant/images.py).
  iPhone photo-library uploads can be HEIC (opener registered in core.apps);
  browsers can't display HEIC, so we never store it.
- **Research backfill is the one exception to "AI proposes, humans commit":**
  dossier research fills *blank* catalog fields directly (varietals,
  appellation, ABV, producer region/country) — never overwriting non-blank
  values — because these are label facts, not taste judgments. What was filled
  is stored in the dossier JSON (`backfilled`) and shown on the wine page.
- **An empty dossier is a failure, not a result** — research_wine raises
  rather than saving a blank "About this wine" block (hit this live with a
  small Portuguese producer, 2026-07-16).

## House Rules

- **Never commit or push without asking.** Sequence: explain changes → update
  CLAUDE.md/TODO.md → scan staged diff for secrets → ask the owner.
- **Models:** inherit `core.models.BaseModel`; docstring stating purpose; NEVER
  hand-write migrations (`manage.py makemigrations`); ALWAYS register in admin
  (list_display/list_filter/inlines) — historically the most-skipped step.
- **Views:** `LoginRequiredMixin` on every view (site also has
  `LoginRequiredMiddleware` as a global backstop). Mutations via POST only.
  Messages framework for user feedback.
- **Data-to-page:** default to server-side render; HTMX fetch only for genuinely
  interactive or slow (AI) data. Analytical logic lives in Python where pytest can
  reach it, not JS.
- **Templates:** Django comments only — `{# #}` (single-line) /
  `{% comment %}` (multi-line). Never HTML `<!-- -->` comments.
- **Management commands:** thin shims over importable functions; idempotent;
  curated progress to stdout, detail to `logs/app.log` via the `winecellar` logger.
- **AI features propose, humans commit:** every AI output feeds a form the user
  confirms/edits before anything is saved as inventory truth.
- **Files:** use Edit/Write tools for file changes — never round-trip content
  through PowerShell Get-Content/Set-Content (UTF-8 corruption).
- **Money fields** (bottle purchase price) are `DecimalField` — this app has no
  numpy analytics pipeline, so the foundation FloatField rule does not apply.

## Current State

- **v1 committed (8c2322a).** Inventory (Producer/Wine/Vintage/Bottle/TastingNote,
  dashboard, drink-a-bottle flow), label scan → prefilled intake form, AI
  drinking-window suggest, cellar-grounded pairing, menu-photo analysis,
  distributor-email pipeline (`manage.py assistant_poll_email`), usage/cost page,
  README, Dockerfile. Branch stays `master` (the owner's preference).
- **v1.1 built on top (2026-07-15):** wine dossiers (`research_wine` — two-step:
  web-search text pass then structuring pass, because web-search citations are
  incompatible with constrained output), per-user `TasteProfile` (edit page +
  AI draft-from-history; included in pairing/menu prompts per user, all profiles
  in email digests), menu advice restructured to three named picks
  (taste_match / best_value / most_interesting). Committed as v1.1 (3d5a4ee).
- **v1.2 (2026-07-15):** menu categories are per-user preferences on TasteProfile
  (3 checkboxes + standing `menu_notes` instructions); each category returns a
  *ranked list* with prices (so the diner picks their own price point — this was
  the owner's explicit workflow); menu form takes optional `food` + `notes` inputs
  (replaced `occasion`). 53 tests green.
- **v1.3 (2026-07-15, overnight session on the owner's laptop):** async dossier
  research (background thread + HTMX-polled fragment — phone can lock and come
  back); intake modes (cellar / wishlist / tried-it → vintages without bottles,
  wine-list `show` filters, dashboard wishlist tile, wishlist toggle); label
  scans linked to their confirmed vintage with the photo on the wine page; HEIC
  upload support (pillow-heif, stored as JPEG); mobile-first redesign (bottom
  tab bar, card lists, dark mode, PWA manifest + icons, More page). 74 tests
  green. Visuals verified at iPhone size via `scripts/dev/screenshot_pages.py`
  (playwright is a dev dependency; screenshots land in `logs/screenshots/`).
  Research verified against the live API (dossier saved for Monte Bello 2019).
- **v1.3.1 (2026-07-16):** intake dupe guard (case-variants reuse the existing
  entry silently; near-matches — difflib + containment in
  `cellar.forms.similar_names` — pause with tap-to-use suggestions and a
  force-new checkbox); research backfills blank catalog fields (see Decisions)
  and empty dossiers fail with a retry instead of saving blank; research
  prompt is grounded with producer region/country and may search the
  producer's local language; per-vintage rating trajectory on the wine page
  (`Vintage.rated_notes` / `rating_trend`, ±1 point reads as steady). 93
  tests green. Live-verified on the owner's Quinta de S. José Douro Tinto 2021:
  first run saved an empty dossier (the original bug), re-run after the fix
  found the wine and backfilled the varietals.
- **Not yet done:** IMAP creds + distributor mailbox/forward rule; remaining
  live smoke tests (label/window/email); the owner's real-device iPhone pass
  (LAN: add laptop IP to ALLOWED_HOSTS in .env + `runserver 0.0.0.0:8000`);
  push to GitHub.
- Demo data: `scripts/dev/seed_smoke_data.py` (user `smoke`; includes a
  wishlist entry and a tried-at-restaurant record).
