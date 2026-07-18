# Deploy runbook — winecellar on the shared Hetzner box

Plan of record: `docs/deployment.md` (Hetzner-EU CAX11, Docker Compose,
Postgres, Caddy edge via Cloudflare **DNS-01**, orange-cloud). This directory
is the box config; `scripts/deploy/` holds the stdlib provisioning scripts.
All `python` below = `.venv\Scripts\python.exe` from the repo root.

```
deploy/
  cloud-init.yaml        box base config (rendered by provision.py)
  Caddyfile              vhosts: wine + blog scratch (apex/www ready for cutover)
  caddy/Dockerfile       custom Caddy: CF DNS-01 + CF trusted_proxies
  backup/                nightly restic->B2 (Postgres + media + Buttondown export)
docker-compose.prod.yml  the canonical /opt/box compose (caddy + web + db)
```

The box's `/opt/box` = a clean copy of this repo (shipped in step 4). Blog
static lives at `/srv/blog/workshop`; the blog is a Caddy `file_server` tenant
(it never joins the compose).

## 0. Local prerequisites (one-time)

Secrets live in **1Password** (vault `box`, items `shared-box` +
`winecellar`), not in a plaintext `.env`. `.env.op` and `deploy/box.env.op` are
committed templates of `op://` references; `op` resolves them:

- **Workstation scripts:** `op run --env-file=.env.op -- <cmd>` — secrets go
  into the process only, nothing on disk.
- **Box `/opt/box/.env`:** generated with `op inject` (step 4).

1. 1Password desktop app signed in, **Settings → Developer → Integrate with
   1Password CLI** on. Verify: `op vault list` shows `box`.
2. SSH key: an Ed25519 key in **1Password** with its SSH agent on (private key
   never hits disk). Put the **public** half at `keys/box.pub` for provisioning.

(`SECRET_KEY`, `POSTGRES_PASSWORD`, `RESTIC_PASSWORD` were already generated
into 1Password — nothing to generate at deploy.)

## 1. Provision the box (Hetzner, Falkenstein)

```powershell
op run --env-file=.env.op -- python scripts/deploy/provision.py types   # confirm cax11 EUR/mo
op run --env-file=.env.op -- python scripts/deploy/provision.py create  # cax11 @ fsn1
op run --env-file=.env.op -- python scripts/deploy/provision.py status  # until "running"
```

Cloud-init then takes a few minutes: `deploy` user (your key), Docker, restic +
rclone, ufw (22/80/443 only), and `/opt/box`, `/srv/blog/workshop`,
`/srv/backup`. Verify: `ssh deploy@<box-ip> docker version`.

## 2. Point `wine` at the box (gray-cloud first)

```powershell
op run --env-file=.env.op -- python scripts/deploy/dns.py add-wine --ip <box-ip>
```

Gray-cloud (DNS-only) first so you verify the app + cert against the origin
directly. Orange comes in step 7.

## 3. Cloudflare SSL mode (one-time, dashboard)

Set the zone's SSL/TLS mode to **Full (strict)** (SSL/TLS → Overview). Never
"Flexible" — with Caddy's HTTPS redirect it loops. DNS-01 gives the origin a
real Let's Encrypt cert, so Full (strict) is satisfied.

## 4. Ship the repo + prod `.env` to the box

Ship the committed tree only (no `.git`, `.venv`, `.env`, media):

```powershell
git archive --format=tar HEAD | ssh deploy@<box-ip> "tar -x -C /opt/box"
```

Then generate `/opt/box/.env` straight from 1Password — the resolved secrets
stream over SSH and never touch your disk:

```powershell
op inject -i deploy/box.env.op | ssh deploy@<box-ip> "cat > /opt/box/.env && chmod 600 /opt/box/.env"
ssh deploy@<box-ip> "chmod +x /opt/box/deploy/backup/backup.sh"
```

## 5. Build + start

```sh
cd /opt/box && docker compose -f docker-compose.prod.yml up -d --build
```

Caddy builds the custom image (DNS-01) and issues the `wine` cert via
Cloudflare; `web` runs migrate + collectstatic then gunicorn; `db` is
Postgres 17. Create the first login: `docker compose -f docker-compose.prod.yml
exec web python manage.py createsuperuser`.

To hand out a **read-only guest link**, add the shared guest account
(idempotent; drop `-T` so the password prompt gets a TTY, or pass
`--password`): `docker compose -f docker-compose.prod.yml exec web python
manage.py create_guest`. It's a `Guest`-group, non-staff account — browse
only, no writes/AI/admin (see the guest-role Decisions bullet in CLAUDE.md).

## 6. Install the nightly backup timer

```sh
sudo cp /opt/box/deploy/backup/box-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now box-backup.timer
/opt/box/deploy/backup/backup.sh          # run once by hand; confirm a snapshot in B2
```

## 7. Verify, then flip `wine` orange

- Visit `https://wine.example.com` (gray-cloud): app loads, cert valid,
  login works, a label scan / pairing round-trips.
- Then the orange-cloud end state:
  ```powershell
  op run --env-file=.env.op -- python scripts/deploy/dns.py proxy --on
  ```
  No cert change needed (DNS-01). Re-verify the site through the proxy.

## 8. Load the real cellar

Only after the latency feels right on seed data (docs/deployment.md
sequencing). Loading into prod = **prod is now the canonical DB**; both
computers become browsers. Nothing to migrate — the demo DBs were throwaway.

## Updating prod (after the first deploy)

Deploys are deliberate — one command ships the committed HEAD and rebuilds:

```powershell
python scripts/deploy/deploy.py --host deploy@<box-ip>
# or, to resolve the IP from Hetzner automatically:
op run --env-file=.env.op -- python scripts/deploy/deploy.py
```

It `git archive`s HEAD → scp → extracts to `/opt/box` → `docker compose up -d
--build`, which reruns `migrate` + `collectstatic` and restarts gunicorn. Ships
only committed code, so commit (and usually push) first. Run from PowerShell so
`scp`/`ssh` use Windows OpenSSH + the 1Password agent. No auto-deploy / no CD:
migrations apply on deploy, so prod changes only when you run this.

## Reversibility (switch hosts if EU latency bites)

1. Provision the new host (same scripts, different provider/region).
2. Restore data: `restic restore latest --target /tmp/r` → `pg_restore` the
   dump into the new `db`, copy `media/`.
3. `python scripts/deploy/dns.py add-wine --ip <new-ip>` — the public CF edge
   IP is unchanged, so users see no downtime.

~1 hour, and it exercises the backup path. The compose/Caddy/DNS-01 stack is
vendor-neutral.

## psql access (the requirement)

```sh
ssh deploy@<box-ip>
docker compose -f /opt/box/docker-compose.prod.yml exec db psql -U winecellar
# or a tunnel for a local client:  ssh -L 5433:localhost:5432 deploy@<box-ip>
#   (then point psql/GUI at localhost:5433 — but 5432 never leaves the box)
```

## Blog tenant

The blog joins after the box is up: it `blog publish`es static files to
`/srv/blog/workshop` (Caddy already serves `blog.example.com`). The apex
cutover — uncommenting the apex/www blocks in `Caddyfile` + the blog's DNS flip
— is gated by the owner once the scratch host verifies. See the blog repo's
`deploy/README.md`.
