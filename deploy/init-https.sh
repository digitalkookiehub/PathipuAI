#!/usr/bin/env bash
# Get a free HTTPS certificate (Let's Encrypt) for the domain in .env and start Nginx with it.
#
#   ./deploy/init-https.sh you@example.com
#
# Before running: the domain's DNS must point at this server, and ports 80 and 443 must be open.
# Re-run it any time; renewal is a separate weekly job (see docs/DEPLOYMENT.md, "Renewing the certificate").
set -euo pipefail

EMAIL="${1:?Usage: ./deploy/init-https.sh you@example.com}"
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then echo "Create .env first (cp .env.production.example .env)." >&2; exit 1; fi
DOMAIN="$(grep -E '^DOMAIN=' .env | head -1 | cut -d= -f2- | tr -d '[:space:]')"
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "books.example.com" ]; then
  echo "Set DOMAIN in .env to your real domain first." >&2; exit 1
fi

echo "== 1/4 Starting the app"
docker compose up -d --build app

echo "== 2/4 Making a temporary certificate so Nginx can start"
docker compose run --rm --entrypoint sh certbot -c "
  mkdir -p /etc/letsencrypt/live/$DOMAIN &&
  if [ ! -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]; then
    apk add --no-cache openssl >/dev/null 2>&1 || true
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
      -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
      -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem -subj /CN=$DOMAIN
  fi"
docker compose up -d nginx

echo "== 3/4 Asking Let's Encrypt for the real certificate"
docker compose run --rm --entrypoint sh certbot -c "
  rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "== 4/4 Reloading Nginx with the real certificate"
docker compose exec nginx nginx -s reload

echo
echo "Done. Open https://$DOMAIN"
echo "Next: create your account with:  docker compose exec app python -m scripts.create_user YOUR-NAME"
