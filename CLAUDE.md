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

- **All six v1 phases built (2026-07-15), not yet committed/pushed.** Inventory
  (Producer/Wine/Vintage/Bottle/TastingNote, dashboard, drink-a-bottle flow),
  label scan → prefilled intake form, AI drinking-window suggest, cellar-grounded
  pairing, menu-photo analysis, distributor-email pipeline
  (`manage.py assistant_poll_email`), usage/cost page, README, Dockerfile.
  45 pytest tests green; every page smoke-tested via a live runserver walk.
- **Not yet done:** the owner fills `.env` (API key, IMAP creds) and creates the
  distributor mailbox + forward rule; live smoke test (`scripts/dev/smoke_ai.py`)
  against the real API; first commit/push (branch rename master→main pending).
- Demo data: `scripts/dev/seed_smoke_data.py` (user `smoke`).
