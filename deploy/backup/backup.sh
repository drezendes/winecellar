#!/usr/bin/env bash
# Nightly box backup -> Backblaze B2, client-side encrypted via restic. ONE
# job for the whole box (tenancy contract): winecellar's Postgres dump + media,
# plus the blog's Buttondown subscriber export. Blog *images* are NOT here —
# the blog publishes those to B2 itself on every `blog publish`.
#
# Runs from box-backup.service (systemd timer) as the deploy user.
# Config comes from /opt/box/.env (chmod 600), which must define:
#   POSTGRES_PASSWORD, RESTIC_PASSWORD,
#   BACKBLAZE_BUCKET_NAME, BACKBLAZE_KEY_ID, BACKBLAZE_APPLICATION_KEY,
#   BUTTONDOWN_API_KEY
set -euo pipefail

BOX=/opt/box
COMPOSE="docker compose -f $BOX/docker-compose.prod.yml"
STAGE=/srv/backup
# set -a so the plain KEY=value lines are exported — child processes
# (buttondown_export.py, restic) read them from the environment.
set -a
# shellcheck disable=SC1091
source "$BOX/.env"
set +a

mkdir -p "$STAGE/buttondown"

# 1. Postgres logical dump (custom format -> compact, restore with pg_restore).
$COMPOSE exec -T db pg_dump -U winecellar -Fc winecellar >"$STAGE/winecellar.dump"

# 2. Blog Buttondown subscriber export (absorbed from the blog repo; the copy
#    we own, so subscriber continuity survives even a Buttondown outage).
python3 "$BOX/deploy/backup/buttondown_export.py" "$STAGE/buttondown"
find "$STAGE/buttondown" -name 'subscribers-*.json' -mtime +30 -delete

# 3. restic snapshot -> B2. Client-side encryption keeps the DB + subscriber
#    PII out of B2 in plaintext. restic's b2 backend reads these env names:
export RESTIC_REPOSITORY="b2:${BACKBLAZE_BUCKET_NAME}:winecellar-restic"
export B2_ACCOUNT_ID="$BACKBLAZE_KEY_ID"
export B2_ACCOUNT_KEY="$BACKBLAZE_APPLICATION_KEY"
export RESTIC_PASSWORD

restic snapshots >/dev/null 2>&1 || restic init # first run creates the repo
restic backup --tag nightly "$STAGE/winecellar.dump" "$STAGE/buttondown" "$BOX/media"
restic forget --prune --keep-daily 7 --keep-weekly 5 --keep-monthly 12

echo "backup complete: $(date -u +%FT%TZ)"
