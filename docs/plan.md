# Winecellar — Project Plan

## Context

Greenfield project in an empty personal GitHub repo. The owner wants a personal wine cellar app for himself + household that goes beyond inventory tracking: it should know what's ready to drink, suggest pairings, read wine labels and restaurant menus from photos, and turn local-distributor marketing emails into buying suggestions. Several features require an LLM; Claude's vision + text capabilities cover all of them with **no external wine datasets required**.

Decisions made with the user:
- **Framework:** Django (user maintains it; best fit anyway — admin UI for free)
- **Users:** 2 household accounts sharing one cellar (Django auth, no per-user data separation)
- **Email intake:** dedicated mailbox polled via IMAP (auto-forward distributor emails to it)
- **Hosting:** local dev only for now (`manage.py runserver`); keep it containerizable but defer deployment
- **Cost target:** ~$5–15/month API spend at personal volume (Claude Opus 4.8: $5/$25 per MTok)

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | Django 5.x, Python 3.12+ | User familiarity; admin gives day-1 data entry |
| Database | SQLite | Personal scale; trivially swappable to Postgres later |
| Frontend | Django templates + HTMX + mobile-first CSS | No JS build step; HTMX gives loading states for slow AI calls; phone-usable (menu photos at restaurants) |
| LLM | `anthropic` SDK, model `claude-opus-4-8`, adaptive thinking (`{"type": "adaptive"}`) | Vision for labels/menus, structured outputs for extraction |
| Config | `.env` via `django-environ` (`ANTHROPIC_API_KEY`, IMAP creds) | Never commit secrets |
| Email polling | Management command using `imap-tools`, run manually or via Task Scheduler | No Celery/broker complexity for v1 |
| Dependency mgmt | `uv` (pyproject.toml, uv.lock) | Fast, modern; still creates/uses `.venv` so the owner's venv habits hold |
| Testing | pytest + pytest-django, fixture-style | Matches the owner's conventions in the foundation repo |

## Conventions (adopted from the foundation repo's CLAUDE.md)

Reviewed `../foundation/.claude/CLAUDE.md` per the owner's request; these preferences transfer:

- **Doc discipline:** winecellar gets its own lean `CLAUDE.md` (house rules + current state only), `TODO.md` for open items, `docs/` for history/detail. Seeded in the scaffold phase.
- **Commit protocol:** never commit or push without asking — explain changes, update CLAUDE.md/TODO.md, scan the staged diff for secrets, then ask.
- **Model checklist:** abstract `BaseModel` (uuid pk, created/modified timestamps) in a `core` module, inherited by all models; docstrings stating purpose; always run `makemigrations` (never hand-write migrations); **always register in admin** with list_display/list_filter/inlines.
- **Views:** `LoginRequiredMixin` on every view; mutations via POST only; messages framework for feedback; templates extend a shared base.
- **Data-to-page defaults:** plain server-side render for display data; HTMX/API fetch only for genuinely interactive or slow (AI) data; analytical logic lives in Python where pytest can reach it, not JS.
- **Templates:** Django comments only (`{# #}` single-line, `{% comment %}` for multi-line) — never HTML `<!-- -->`.
- **Management commands:** thin shims over importable package functions; idempotent (safe to re-run); simplified progress/summary output tiers with detail to a log file.
- **Environment:** always run through `.venv` (`.venv\Scripts\python.exe`); secrets live only in gitignored `.env`.
- **Analysis/one-off scripts** go in `scripts/dev/` (not scratchpad) if worth keeping.

Deliberately *not* adopted (foundation-specific): Azure Key Vault/Container Apps deployment machinery, PGP client-data policy, FloatField-for-analytics rule (bottle purchase prices are money → `DecimalField` is correct here), Celery task patterns (no queue in v1), pip-compile lock files (uv.lock serves that role).

## Architecture

Two Django apps:

### `cellar` — inventory core (no AI)
Models:
- **Producer** — name, region, country, notes
- **Wine** — FK producer; name, type (red/white/rosé/sparkling/dessert/fortified), varietals, appellation
- **Vintage** — FK wine; year (nullable for NV), ABV, drink-from year, drink-until year (user-editable, AI-suggestible)
- **Bottle** — FK vintage; size, purchase date/price/source, location note, status (`in_cellar` / `consumed` / `gifted`), consumed date
- **TastingNote** — FK vintage, optional FK bottle; author (user), date, rating (e.g. 1–100 or 1–5), notes text

Views: dashboard (cellar summary + "drink soon" list from drinking windows), wine/vintage/bottle CRUD, "drink a bottle" flow (marks consumed + prompts a tasting note). All models registered in Django admin as the power-user fallback.

### `assistant` — AI features
A service module `assistant/sommelier.py` wraps one Anthropic client. Each feature is a function using `client.messages.parse()` with a Pydantic schema (structured outputs), vision inputs as base64 image blocks where relevant:

1. **`scan_label(image) -> LabelData`** — photo of a bottle → producer, wine name, vintage, varietal, region, appellation, ABV. Feeds a pre-filled "add bottle" form the user confirms/edits (AI proposes, human commits — applies to every feature).
2. **`suggest_window(vintage) -> DrinkingWindow`** — drink-from/until years + rationale, offered as a one-click fill on the vintage form.
3. **`pair_food(dish_text, inventory) -> list[Pairing]`** — "what goes with braised short ribs?" → ranked picks **from bottles actually in the cellar**, with reasoning. Inventory serialized compactly (wine, vintage, window, qty) into the prompt.
4. **`analyze_menu(image, inventory, preferences) -> MenuAdvice`** — restaurant wine list photo → parsed offerings + recommendations (grounded in the user's tasting-note history for taste preferences).
5. **`digest_email(raw_text) -> EmailDigest`** — distributor email → structured offers (wine, vintage, price, deal terms) + buy/skip suggestions informed by what's already in the cellar and past ratings.

Models to persist AI interactions (auditability + reuse): **LabelScan**, **MenuAnalysis**, **DistributorEmail** (raw message, parsed offers, suggestions, reviewed flag).

**Email polling:** management command `poll_distributor_email` — connects via IMAP (`imap-tools`), fetches unseen messages, stores raw text as DistributorEmail rows, runs `digest_email`, marks seen. New suggestions surface on the dashboard.

**AI call pattern:** synchronous in views behind HTMX indicators (label scan ~5–15s is acceptable UX for v1); email digestion happens inside the management command. All Anthropic calls go through one thin client wrapper that logs token usage per call to a small `ApiUsage` table so cost stays visible.

## Implementation phases

1. **Scaffold** — `uv init`, Django project (`config` settings package), `cellar` + `assistant` apps, `core` module with `BaseModel`, `.env` handling, `.gitignore`, base template + HTMX, auth (login required site-wide, create 2 users via createsuperuser/admin), seed `CLAUDE.md` + `TODO.md`. First commit (with the owner's go-ahead per commit protocol).
2. **Inventory core** — models, migrations, admin, CRUD views, dashboard with drink-soon logic, "drink a bottle" flow, tasting notes. Tests for models + key views.
3. **AI service layer + label scan** — `sommelier.py`, Pydantic schemas, `scan_label` + upload view + prefilled add-bottle form. Tests with mocked client; one live smoke-test script (`scripts/dev/smoke_ai.py`).
4. **Windows + pairing + menu** — `suggest_window`, `pair_food` (pairing page), `analyze_menu` (mobile-friendly photo upload page).
5. **Email pipeline** — `DistributorEmail` model, IMAP poll command, `digest_email`, dashboard suggestions panel with reviewed/dismiss actions.
6. **Polish** — token-usage view, README with setup instructions, Dockerfile + compose (build-only, keeps future hosting easy).

Each phase ends in a working state; commits happen only after asking the owner (explain → update CLAUDE.md/TODO.md → secret scan → ask).

## Verification

- `.venv\Scripts\python.exe -m pytest tests -q` — model logic (drinking-window/drink-soon queries), view auth + CRUD flows, AI features with a mocked Anthropic client (assert prompts contain inventory, parsed outputs map to models).
- `uv run manage.py runserver` — manual pass per phase: add a wine end-to-end, scan a real label photo, run `poll_distributor_email` against the test mailbox with a real distributor email forwarded in.
- `scripts/dev/smoke_ai.py` — hits the live API once per feature with sample images/text to validate schemas against the real model (run sparingly; pennies per run).

## Non-goals for v1

- Cellar slot/rack tracking (location is a free-text note), market valuation, multi-cellar/multi-tenant support, public hosting, Celery/async task queues, LWIN integration (revisit if wine-name normalization becomes annoying).
