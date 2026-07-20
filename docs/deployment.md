# Deployment

winecellar is a standard 12-factor Django app: env-driven config, a `DATABASE_URL`
switch (SQLite in dev → Postgres in prod), gunicorn + WhiteNoise, `DEBUG=False`-gated
security settings. It runs anywhere Docker Compose does.

- **Standalone example:** `deploy/` is a self-contained, single-tenant production
  example — Caddy edge + gunicorn + Postgres, TLS via Cloudflare DNS-01. See
  `deploy/README.md` to run it. Genericized (placeholders only, no real infra).
- **Where it actually runs:** the maintainer hosts winecellar as one tenant on a
  shared box; that box — its compose, edge, DNS, backups, and deploy tooling — is
  owned by a separate **private infra repo**, not this public app repo.

## Prod stack notes

- **Edge/TLS:** Caddy issues publicly-trusted Let's Encrypt certs via the
  **Cloudflare DNS-01** module, so certs validate whether the host is served
  direct, gray-cloud, or behind Cloudflare's orange-cloud proxy. Set the zone to
  **Full (strict)** — never "Flexible" (it loops against Caddy's HTTPS redirect).
  `trusted_proxies` restores real client IPs; Django uses
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`.
- **Postgres over SQLite** in prod: `psql` access to your own data, no
  type-affinity footguns, env-driven `DATABASE_URL` (already wired in settings).
- **Vendor-neutral / reversible:** Compose + Caddy + Postgres + DNS-01 run
  identically on any host. Switching hosts is changing an origin A record (behind
  Cloudflare the public edge IP never changes) + a restic restore of the pg_dump
  and media onto the new box — the backup job doubles as the migration tool.

## psql access

`docker compose -f docker-compose.prod.yml exec db psql -U winecellar`, or an SSH
tunnel (`ssh -L 5433:localhost:5432 …`) for a local client. Postgres never binds a
public port.
