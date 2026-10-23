#!/usr/bin/env bash
# Put a backup back. This REPLACES the current database and books (the old database is kept as .before-restore).
#
#   ./deploy/restore.sh backups/pathippuai-backup-20261023-020000.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVE="${1:?Usage: ./deploy/restore.sh path/to/pathippuai-backup-....tar.gz}"
[ -f "$ARCHIVE" ] || { echo "File not found: $ARCHIVE" >&2; exit 1; }

read -r -p "This replaces all current data with the backup. Type YES to continue: " ANSWER
[ "$ANSWER" = "YES" ] || { echo "Cancelled."; exit 1; }

echo "Stopping the app..."
docker compose stop app
# Run the restore in a one-off container that shares the data volume, with the backup file mounted read-only.
docker compose run --rm --no-deps -v "$(cd "$(dirname "$ARCHIVE")" && pwd):/restore:ro" app \
  python -m scripts.backup restore "/restore/$(basename "$ARCHIVE")" --force
echo "Starting the app..."
docker compose up -d app
echo "Restored."
