# Production deployment plan

Decided with the owner 2026-07-16. Target: **Hetzner VPS + Docker Compose +
Postgres + Caddy**, DNS on **Cloudflare**, `wine.example.com`.
Not yet built — this is the plan of record.

## The reasoning (so future sessions don't relitigate)

- **Hetzner over Azure/PaaS:** the owner concluded familiarity was a weak
  reason to pay Azure margins ("I have you to help, and I'm not touching
  the infra a lot") — Hetzner is reliable (25-yr, founder-owned, famously
  price-stable), right-sized, and cheapest. Azure remains the reference
  point, not the requirement.
- **Postgres over SQLite:** the owner's bias against SQLite is mostly the name
  (it's superbly engineered), but Postgres wins here for real reasons:
  it's his daily language (`psql` into his own data = data sovereignty),
  no type-affinity footguns, and no future container/filesystem coupling.
  Settings are already env-driven — `DATABASE_URL` does the switch.
- **Cloudflare for DNS** (and later, registrar): complementary to their
  core business, not a profit center — no scalping incentive. the owner wants
  OFF WordPress (trust). Sequence matters: move nameservers first (free,
  zero downtime, blog keeps working), transfer the domain registration
  later, rebuild the blog later still.
- **Blog consolidates onto the same box** as a future project — that's the
  cost leverage vs paying WP hosting.

## Target stack (one Hetzner VPS, Ubuntu LTS + Docker Compose)

| Service | Role |
|---|---|
| `caddy` | TLS (auto Let's Encrypt) + reverse proxy; `wine.example.com` now, blog hostnames later |
| `web` | winecellar: gunicorn + whitenoise, `DEBUG=False` |
| `db` | `postgres:17`, named volume; **never exposed publicly** |
| `backup` | nightly `pg_dump` + media/ → Backblaze B2 (restic or rclone) |
| *(later)* `blog` | the WordPress replacement |

Box: **Ashburn, VA (us-east)** — Hetzner's US region; 10–40 ms from the
US East, EUR-billed like everything Hetzner. Cheapest 4 GB-class plan
there (CPX-line, ~€5/mo) — big headroom for all of it.
Cloudflare DNS in gray-cloud (DNS-only) mode so Caddy manages certs;
orange-cloud proxy is an optional later hardening step.

**psql access (the requirement):** SSH to the box → `docker compose exec
db psql -U winecellar`, or an SSH tunnel (`ssh -L 5433:localhost:5432 …`)
for local psql/GUI clients from either machine. Port 5432 never leaves
the box.

## Sequencing (deliberately lazy — cellar loading is 1–2 months out)

1. **Now, free, independent:** move nameservers to Cloudflare (copy the
   existing WordPress records first; blog unaffected).
2. **Build phase (can happen any time, testable locally):** production
   settings (SECRET_KEY, ALLOWED_HOSTS **and** CSRF_TRUSTED_ORIGINS — the
   foundation lesson — SECURE_* headers), gunicorn + whitenoise deps,
   `docker-compose.prod.yml`, Caddyfile, backup script, deploy runbook.
   Dev environments switch to compose Postgres too (foundation lesson:
   don't let dev SQLite drift from prod Postgres; pytest may keep sqlite
   for speed with a TEST_DATABASE_URL escape hatch).
3. **Provision** the Hetzner box + B2 bucket; DNS A record for `wine`.
4. **Deploy, then load the real cellar directly into prod** — nothing to
   migrate because the real data doesn't exist yet; the demo DBs on
   desktop/laptop are throwaway. This settles the canonical-DB question:
   prod is truth, both computers become browsers.
5. Later projects: blog rebuild onto the same box; domain registration
   transfer to Cloudflare (unlock + auth code, no downtime).

## Shared-box tenancy contract (for the blog project)

The blog transition is a separate project by a separate agent; this section
is the interface so both projects build compatibly. Coordination point =
this document; whichever project provisions the box first follows it, the
other joins.

- **Caddy is the single edge.** It owns :80/:443 and ALL TLS certs. Tenant
  apps never bind public ports — each is a compose service on a shared
  docker network, routed by a Caddyfile vhost entry (hostname → container).
- **Postgres:** winecellar's instance can host a second database (own role,
  own db) if the blog needs one — a static blog needs none.
- **Backups:** the nightly B2 job covers pg_dump + winecellar media; a
  tenant adds its content directories to the same job, not a second system.
- **Hostnames:** `wine.example.com` (winecellar), apex + `www` (blog,
  at its cutover).

## Costs (steady state)

VPS ~€4.6 + B2 backups ~$1 + Cloudflare DNS $0 + domain renewal at cost
≈ **$6–7/mo infra**, plus ~$8–10 API usage. Blog later adds $0 infra and
retires the WP hosting fee.
