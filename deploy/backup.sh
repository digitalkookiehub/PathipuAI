#!/usr/bin/env bash
# Make a backup of the database and all books, and copy it out of the Docker volume to ./backups on the server.
#
#   ./deploy/backup.sh            # run by hand, or from cron (see docs/DEPLOYMENT.md)
#
# IMPORTANT: ./backups is on the same server. Also copy the files somewhere else (another computer, cloud storage),
# otherwise a lost server means lost books.
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP="${KEEP:-14}"
mkdir -p backups

# The backup is made inside the running app container (a safe snapshot even while people are using the app).
docker compose exec -T app python -m scripts.backup create --dest /data/backups --keep "$KEEP"
LATEST="$(docker compose exec -T app sh -c 'ls -1 /data/backups/pathippuai-backup-*.tar.gz | tail -1' | tr -d '\r')"
docker compose cp "app:$LATEST" "./backups/"
chmod 600 ./backups/*.tar.gz

# Keep the same number of copies on the host.
ls -1t ./backups/pathippuai-backup-*.tar.gz | tail -n +"$((KEEP + 1))" | xargs -r rm -f --
echo "Backup saved in ./backups: $(basename "$LATEST")"
