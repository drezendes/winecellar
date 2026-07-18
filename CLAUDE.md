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
- Secrets live in **1Password** (vault `box`; items `shared-box`
  + `winecellar`) — keystore chosen 2026-07-17 for portability across the owner's
  machines, not for at-rest security. `.env.op` / `deploy/box.env.op` are
  committed templates of `op://` refs (no secrets); resolve with
  `op run --env-file=.env.op -- <cmd>` (workstation scripts) or `op inject`
  (box `/opt/box/.env`). The box never calls 1Password at runtime — it holds a
  generated `chmod 600` copy, and the vault stays the reconstructible source of
  truth (esp. `RESTIC_PASSWORD`). A plaintext gitignored `.env` still works for
  dev (see `.env.example`).
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
- **Production target (revised 2026-07-17): Hetzner-EU CAX11 (4 GB ARM,
  Falkenstein) + Compose + Postgres + Caddy, Cloudflare orange-cloud edge,
  wine.example.com** — full plan in `docs/deployment.md`. The blog
  handoff corrected a ~6× pricing error (US ≈ 3.4× EU; Hetzner-US is
  dominated by DO/Linode US-East). the owner chose cheap EU (~$9/mo infra: €7 box
  incl. IPv4 + ~$1 B2; live price 2026-07-17) and accepts ~85 ms behind
  Cloudflare — reversible to US-East (~$24/mo) in ~1 hr
  because the stack is vendor-neutral (see the doc's Reversibility section).
  **TLS = Caddy DNS-01 via the CF plugin** (orange-cloud-safe; token already
  scoped). Postgres replaces SQLite at deploy (env-driven `DATABASE_URL`);
  prod becomes the canonical DB, real cellar loads straight in. Don't
  relitigate Azure/PaaS or the region reversal — the reasoning is in the doc.
  **Build phase shipped** (deploy/ + docker-compose.prod.yml, all
  locally-testable); next is provision → deploy → latency check → load.
- **Dev server port: 8080 on the desktop** (`manage.py runserver 8080`) —
  foundation's runserver owns :8000 there, and a wrong-port session will happily
  log into the AIM portal instead (this happened). Set
  `WINECELLAR_BASE=http://127.0.0.1:8080` for `scripts/dev/screenshot_pages.py`.
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
  appellation, ABV, producer region/country, keeps_open_days) — never
  overwriting non-blank values — because these are style/label facts, not
  taste judgments. What was filled is stored in the dossier JSON
  (`backfilled`) and shown on the wine page.
- **`purchase_price` is actuals-only, forever** (the owner, 2026-07-16): never
  AI-filled or suggested — it's the ground truth for judging his buying
  decisions. Unknown = null + coverage reporting. Market worth is a separate
  concept (valuation sketch in docs/ideas.md, not yet built).
- **An empty dossier is a failure, not a result** — research_wine raises
  rather than saving a blank "About this wine" block (hit this live with a
  small Portuguese producer, 2026-07-16).
- **Design system is documented in `docs/design.md` ("Cellar book") — derive
  from tokens, don't invent.** Garnet is a reserved accent, never paint. Glass
  dots: only 3 validated hues + hollow ring for sparkling — do NOT add more
  (wine's gamut fails CVD checks past 3; measured). Data (years/prices/counts)
  wears the mono; stat values wear ink, never the accent. New wine-facing
  numbers/meters follow the gauge/dot contracts in the doc.

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
- **Direct-to-DB research pattern (the owner, 2026-07-16):** for deeper research
  than the built-in actions do, Claude sessions may write results straight to
  the DB via ORM scripts in `scripts/dev/` — that's a benefit of owning the
  stack. Rules when doing so: never touch `purchase_price` (actuals-only);
  respect the vetted/unvetted taxonomy (unowned suggestions → Prospect, not
  Wine); store AI-sourced narrative in dossier JSON / prospect `why` with
  sources, so provenance stays visible; and confirm WHICH machine's DB is
  canonical before writing (undecided as of 2026-07-16 — desktop and laptop
  both hold dev data).
- **Money fields** (bottle purchase price) are `DecimalField` — this app has no
  numpy analytics pipeline, so the foundation FloatField rule does not apply.

## Current State (desktop session, 2026-07-18)

- **DEPLOYED & LIVE (2026-07-18): https://wine.example.com.** Box =
  Hetzner **cx23, Helsinki, 4 GB x86** (`<box-ip>`) — cax11/ARM/Falkenstein
  was capacity-unavailable at provision time (Hetzner EU crunch), so we took the
  equivalent cheap-EU-4GB x86 box (functionally identical, ~25 ms more latency).
  Stack (caddy+web+db) up; TLS via **DNS-01** (wine + blog scratch);
  **orange-cloud on** (CF SSL Full-strict, origin IP hidden, CF edge serves from
  Boston); nightly **restic→B2 verified** (systemd timer 06:20 UTC). Secrets flow
  from **1Password** (`op inject` → `/opt/box/.env`, chmod 600). **SSO evaluated
  & declined (2026-07-18):** 1Password-managed passwords on Django accounts — SSO
  adds an OAuth dependency for ~zero gain when 1Password already handles
  passwords; the only marginal add (no exposed login page / MFA) is deferrable
  (revisit only for a multi-app fleet or if MFA is wanted). **Remaining:** the owner
  creates the superuser(s); live on seed data for the latency gut-check; then
  load the real cellar straight into prod. Runbook: `deploy/README.md`.
- **Deployment build phase shipped (2026-07-17).** Blog
  handoff reconciled (`docs/deployment.md` rewritten): region reversed to
  Hetzner-EU CAX11 after the ~6× pricing correction; orange-cloud + DNS-01
  edge. App made prod-ready — `gunicorn`/`whitenoise`/`psycopg` deps,
  `DEBUG=False`-gated security settings (`SECURE_PROXY_SSL_HEADER`, secure
  cookies, HSTS, CSRF_TRUSTED_ORIGINS, WhiteNoise manifest), prod `Dockerfile`
  (migrate + collectstatic + gunicorn gthread). Canonical box config written:
  `docker-compose.prod.yml` (caddy+web+db), `deploy/` (custom Caddy w/ CF DNS
  module + Caddyfile, restic→B2 backup + systemd timer absorbing the blog's
  Buttondown export, cloud-init), `scripts/deploy/` (provision.py cax11/fsn1,
  dns.py wine record + orange/gray toggle, common.py). 144 tests still green;
  dev/tests unaffected (all prod behavior env-gated). (Now live — see the
  DEPLOYED bullet above.)
- **"Cellar book" design shipped** (docs/design.md; dark = "the lodge" after
  Cockburn's Porto). Wines-page filters (region/notes/auto-apply/count).
  **Taste map commissioned** — plan + taxonomy (vetted catalog vs unvetted
  prospects) in docs/taste_map_plan.md; **Phase D (open bottles) built**:
  opt-in "not finishing it" checkbox → OPEN status, dashboard "Open now",
  Finish action; open bottles count as drinkable stock and are marked for
  the sommelier. **Phases A-C also built the same day:** style vectors
  (`assistant_backfill_styles` + research piggyback), the taste map at
  `/map/` (stdlib PCA in cellar/taste_map.py, honest axis labels, emphasis
  mode via ?focus=), and prospects (`Prospect` model = unvetted staging;
  three channels: research worth_watching, explicit suggest-5, scan
  save-for-later; promotion via the intake form's prospect field; dashed
  rings on the map). **Cellar valuation built the same day** (/assistant/value/:
  explicit runs → per-vintage rows, cost-basis rule per docs/ideas.md,
  held-at-time series — the owner runs it quarterly). 144 tests green.
  Real-cellar style backfill still to run.

## Earlier State

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
