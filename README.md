# Winecellar

Personal wine cellar app with an AI sommelier. Track bottles, drinking windows,
and tasting notes; scan bottle labels and restaurant wine lists with your phone;
get food pairings from your actual cellar; turn distributor marketing emails
into buy/skip suggestions.

Django 5 + SQLite + HTMX; the AI features use the Claude API (`claude-opus-4-8`).

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync                                   # creates .venv and installs everything
Copy-Item .env.example .env               # then fill in ANTHROPIC_API_KEY
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py createsuperuser   # once per household member
.venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000 and log in.

### Configuration (.env)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — required for all AI features |
| `ANTHROPIC_MODEL` | Defaults to `claude-opus-4-8` |
| `DISTRIBUTOR_IMAP_HOST/_USER/_PASSWORD/_FOLDER` | Dedicated mailbox the app polls for distributor emails |

## Features

- **Dashboard** — cellar counts, drink-soon and ready-to-drink lists, new buying suggestions.
- **Add bottles** — one form creates producer → wine → vintage → bottles; or **Scan label**:
  photograph the bottle and the form is prefilled for you to confirm.
- **Drinking windows** — set per vintage, or one-click "Suggest with AI".
- **Wine dossier** — "Research this wine" web-searches (producer site first) and stores
  background: producer, style, vintage notes, typical price — so a bottle is never a blank slate.
- **My profile** — describe your palate once (or AI-draft it from your tasting history);
  it rides along in every recommendation prompt so answers are tailored per user.
- **Pairing** — "what goes with braised short ribs?" answered only from bottles you own.
- **Menu** — photograph a restaurant wine list; three named picks: your taste match,
  the best value, and the most interesting bottle.
- **Suggestions** — run the email poll to digest distributor offers into buy/consider/skip verdicts:

```powershell
.venv\Scripts\python.exe manage.py assistant_poll_email
```

Schedule that command (Windows Task Scheduler / cron) for hands-off operation.

- **Usage** — running estimate of API spend by feature.

## Development

```powershell
.venv\Scripts\python.exe -m pytest tests -q      # test suite (AI mocked)
.venv\Scripts\python.exe scripts\dev\smoke_ai.py label photo.jpg   # live API smoke test
```

House rules and architecture notes: `CLAUDE.md`. Plan: `docs/plan.md`.

## Docker (optional)

A Dockerfile and compose file are provided for future home-server hosting:

```powershell
docker compose up --build
```

Data (SQLite DB, uploaded photos) persists in the `data/` and `media/` volumes.
