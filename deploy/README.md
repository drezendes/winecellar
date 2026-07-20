# Deploy example (single-tenant)

A self-contained, single-tenant production example for winecellar: Docker
Compose (Caddy + gunicorn + Postgres), TLS via **Cloudflare DNS-01**. It's a
**showcase** — genericized, no real infrastructure — so the public repo stays
independently deployable. (In production this app runs as one tenant on a shared
box managed by a separate private infra repo; that box config isn't here.)

```
../docker-compose.prod.yml   caddy + web + db
Caddyfile                    single vhost ({$WINE_HOST}); TLS via CF DNS-01
caddy/Dockerfile             custom Caddy image (Cloudflare DNS module + trusted_proxies)
```

## Prerequisites

- A domain on **Cloudflare** and a `CLOUDFLARE_API_TOKEN` scoped Zone→DNS→Edit
  (used by Caddy for DNS-01 issuance).
- Set the zone's SSL/TLS mode to **Full (strict)** — never "Flexible" (with
  Caddy's HTTPS redirect it loops).

## Run

1. Copy `.env.example` → `.env` and fill it in (`SECRET_KEY`,
   `POSTGRES_PASSWORD`, `ANTHROPIC_API_KEY`, `WINE_HOST`,
   `CLOUDFLARE_API_TOKEN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`).
2. Point a DNS A record for `WINE_HOST` at the host.
3. Build + start:
   ```sh
   docker compose -f docker-compose.prod.yml up -d --build
   ```
   Caddy builds the custom image and issues the cert via Cloudflare DNS-01;
   `web` runs migrate + collectstatic then gunicorn; `db` is Postgres 17.
4. Create the first login:
   ```sh
   docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
   ```

`psql` into your data: `docker compose -f docker-compose.prod.yml exec db psql -U winecellar`.

For a read-only shared guest account, see `create_guest` (the guest-role bullet
in `../CLAUDE.md`).
