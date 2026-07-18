# Production deployment plan

Decided with the owner 2026-07-16, **revised 2026-07-17** after the blog handoff
surfaced a ~6× pricing error. Target: **Hetzner Cloud CAX11 (Falkenstein, EU)
+ Docker Compose + Postgres + Caddy**, edge on **Cloudflare (orange-cloud
proxy)**, `wine.example.com`. Not yet built — this is the plan of record.

## What changed on 2026-07-17 (so nobody relitigates the reversal)

The original plan said "Ashburn (US), ~€5/mo, ~$6–7/mo infra." Two of those
were wrong; the blog agent caught it with live Hetzner API numbers off the owner's
account:

- **The €5 figure was EU pricing mislabeled as Ashburn.** Hetzner US ≈ 3.4× EU
  (real Ashburn cpx21/4 GB ≈ €37/mo ≈ $41, not €5).
- **Hetzner-US is strictly dominated.** A US-East cloud (DigitalOcean NYC /
  Linode Newark / Vultr EWR) gives *better* Boston latency (~8–10 ms vs
  Ashburn's ~18 ms) at ~$24/mo for 4 GB — cheaper AND faster than Hetzner-US.
  So "Hetzner in the US" makes no sense; the real choice is **US-East (~$24,
  ~10 ms)** vs **Hetzner-EU (~$5–12, ~85 ms)**.
- **the owner chose Hetzner-EU CAX11** (4 GB ARM, ~$5.40/mo): he already holds the
  account, it's the cheapest comfortable box, and the ~85 ms is reversible by
  design (see Reversibility). The corrected infra cost (~$6–7/mo) is
  coincidentally the doc's original number — now for the right reason (EU ARM,
  not a mislabeled US box).

**Latency reality check (why ~85 ms is fine here):** behind Cloudflare's
orange cloud, static assets and the whole blog serve from a CF edge ~10 ms
away; only winecellar's *dynamic* requests pay the ~85 ms, and CF's warm
pooled origin connection keeps it to ~one round trip. AI features (2–30 s
Claude calls) don't feel it at all; page loads gain ~85 ms TTFB (still
"instant"); only rapid HTMX taps get a slight beat. For a 2-user household app
that's a non-issue — and it's testable on seed data before any commitment.

## The reasoning (carried over, still valid)

- **Hetzner over Azure/PaaS:** familiarity was a weak reason to pay Azure
  margins. Hetzner-EU is reliable (25-yr, founder-owned, price-stable) and
  genuinely cheapest. US-East clouds were evaluated 2026-07-17 and set aside
  for cost, not quality — the switch is a ~1-hour reversible move if latency
  ever bites. (Azure remains the reference point, not the requirement.)
- **Postgres over SQLite:** the owner's daily language (`psql` into his own data =
  data sovereignty), no type-affinity footguns, env-driven `DATABASE_URL`
  switch (already wired in settings).
- **Cloudflare for DNS + edge:** nameservers **already moved** (verified
  2026-07-17: `amalia`/`hasslo.ns.cloudflare.com`; apex resolves to CF
  anycast). Orange-cloud proxy is now the **intended edge for both sites**
  (free CDN/DDoS/hidden origin IP), not a "later" hardening step. Domain
  registration transfer to Cloudflare is still a later, separate step (mind
  60-day locks).
- **Blog consolidates onto the same box** as a static `file_server` tenant —
  $0 marginal, the cost leverage vs paying WP hosting.
- **ARM (CAX line) is a non-issue:** the whole stack — python:3.12-slim,
  postgres:17, caddy, pillow/pillow-heif — is multi-arch. Build the custom
  Caddy image on the box (arm64) or with buildx.

## Target stack (one Hetzner CAX11, Ubuntu LTS + Docker Compose)

| Service | Role |
|---|---|
| `caddy` | Edge: TLS via **Cloudflare DNS-01** (custom image w/ CF DNS module) + reverse proxy; `trusted_proxies` for CF ranges. `wine.` → web; blog vhosts → `file_server`. |
| `web` | winecellar: gunicorn (gthread) + whitenoise, `DEBUG=False` |
| `db` | `postgres:17`, named volume; **never exposed publicly** |
| `backup` | nightly `restic` → Backblaze B2 (pg_dump + winecellar media + blog's Buttondown export) |
| *(tenant)* blog | static files at `/srv/blog/workshop`, served by Caddy `file_server` |

Box: **Falkenstein (EU)**, CAX11 = 2 vCPU ARM / 4 GB / 40 GB — ample for this
workload (Postgres for ~150 wines is tiny; media is a few hundred JPEGs).
Cloudflare in **orange-cloud** (proxied) for both sites.

## Edge / TLS (the orange-cloud design)

- **Certs: Caddy DNS-01 via the Cloudflare-DNS module**, using the owner's
  `CLOUDFLARE_API_TOKEN` (Zone→DNS→Edit, already provisioned). Chosen over a CF
  Origin cert because it's fully automatic (issue + renew), issues
  publicly-trusted Let's Encrypt certs that validate gray *or* orange *or*
  direct — so the scratch host (`blog.example.com`) verifies cleanly
  before the apex flips orange. Cost: a custom Caddy image with the CF DNS
  module (one-time, well-trodden).
- **CF SSL mode: "Full (strict)."** NEVER "Flexible" — with Caddy's HTTPS
  redirect it's an infinite loop.
- **`trusted_proxies`** set to Cloudflare's published IP ranges so
  logs/`X-Forwarded-For` show real client IPs. Django gets
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`.
- **Blog HTML caching:** add a CF "Cache Everything" rule for the blog
  hostnames so even HTML serves from the edge (CF free tier treats HTML as
  dynamic by default). Blog cutover concern; noted here for the shared edge.
- **100 MB free-proxy upload cap:** winecellar's uploads are phone photos,
  well under.

## Sequencing

1. ~~Move nameservers to Cloudflare~~ — **DONE** (verified 2026-07-17).
2. **Build phase (now — all locally testable, no box needed):** prod settings
   (SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SECURE_PROXY_SSL_HEADER,
   secure cookies + HSTS), gunicorn + whitenoise + psycopg deps, prod
   Dockerfile, `docker-compose.prod.yml`, custom Caddy image + Caddyfile,
   restic backup script, cloud-init + provision/dns scripts, runbook. Lives
   under `deploy/` in this repo (the canonical `/opt/box`).
3. **Provision:** Hetzner CAX11 (Falkenstein) via `HCLOUD_TOKEN`; Backblaze B2
   bucket; Cloudflare A-records `wine` + `blog` (scratch) via
   `CLOUDFLARE_API_TOKEN`.
4. **Deploy + test latency on seed data.** Live in the app a few days before
   loading the real cellar — decide keep-EU or switch-to-US-East *while there's
   nothing to migrate*. Then **load the real cellar straight into prod** (prod
   = truth; both computers become browsers; settles the canonical-DB question).
5. **Blog joins** as a `file_server` tenant + `deploy` user; the owner gates the
   apex→box cutover once the scratch host verifies. Later: domain registration
   transfer to Cloudflare.

## Reversibility (why "start cheap, switch if it bites" is low-risk)

Switching hosts later is ~1 hour, near-zero downtime, because:

- **Vendor-neutral:** Compose + Caddy + Postgres + DNS-01 run identically on
  any box.
- **Orange-cloud hides the move:** switching hosts = changing the origin
  A-record inside Cloudflare; the public CF edge IP never changes → users see
  no downtime.
- **DNS-01 re-issues certs automatically** on the new box; no cert migration.
- **The backup job is the migration tool:** restic restore of pg_dump + media
  onto the new box (also proves the backups actually work).

## Shared-box tenancy contract (for the blog project)

The blog transition is a separate project by a separate agent; this section is
the interface so both build compatibly. Coordination point = this document;
whichever project provisions the box first follows it, the other joins.

- **Caddy is the single edge.** It owns :80/:443 and ALL TLS certs. Tenant apps
  never bind public ports — each is a compose service on the shared docker
  network, routed by a Caddyfile vhost (hostname → container / `file_server`
  root).
- **Postgres:** winecellar's instance can host a second database (own role, own
  db) if the blog ever needs one — the static blog needs none.
- **Backups:** the nightly restic→B2 job covers pg_dump + winecellar media +
  the blog's **Buttondown subscriber export**. Blog *images* are already backed
  up by the blog's own `publish` sync to B2 (`b2:<bucket>/blog/workshop/images`)
  — NOT re-copied here. The blog's export script + timer (`deploy/box/backup/`
  in its repo) get absorbed as a pre-hook that drops the export where restic
  sweeps it.
- **Hostnames:** `wine.example.com` (winecellar), apex + `www` (blog, at
  cutover), `blog.example.com` (scratch/preview).

## psql access (the requirement)

SSH to the box → `docker compose exec db psql -U winecellar`, or an SSH tunnel
(`ssh -L 5433:localhost:5432 …`) for local psql/GUI clients from either
machine. Port 5432 never leaves the box.

## Costs (steady state, corrected 2026-07-17)

CAX11 ~$5.40 + B2 backups ~$1 + Cloudflare $0 + domain renewal at cost
≈ **~$6–7/mo infra**, plus ~$8–10 API usage. Blog adds $0 infra and retires
the WP hosting fee. (US-East alternative, if latency ever bites: ~$24/mo — a
+$18/mo swap, reversible per above.)

## Keys / accounts

- `HCLOUD_TOKEN` — Hetzner API (provision). Shared with the blog; copy into
  winecellar `.env`.
- `CLOUDFLARE_API_TOKEN` — Zone→DNS→Edit; used by Caddy DNS-01 **and** the dns
  script. Shared with the blog.
- Backblaze **B2** `keyID` / `applicationKey` + bucket, and a `RESTIC_PASSWORD`
  — **B2 account still to be created by the owner** (only blocker, and only for the
  backup service).
- `SECRET_KEY`, Postgres password — generated, never from the owner.
- `ANTHROPIC_API_KEY` — reuse the existing key on prod.
- the owner's SSH **public** key — box admin + the blog `deploy` user (1Password
  agent).
