# Deploying PathippuAI on a Hostinger Ubuntu VPS

This guide puts PathippuAI on one small Ubuntu server with Docker, behind Nginx with a free HTTPS certificate.
Only ports 80 and 443 are open to the internet. The app itself is never exposed directly.

You need: a VPS (Ubuntu 22.04 or 24.04, at least 2 GB RAM and 20 GB disk; 4 GB if you use the "careful" reading
method), a domain name, and about 30 minutes.

## 1. Install Docker and Docker Compose

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # log out and back in afterwards
docker compose version             # should print a version
```

Firewall (allow SSH first, or you will lock yourself out):

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

Point your domain's DNS **A record** (for example `books.example.com`) at the server's IP address. Wait until
`ping books.example.com` shows that IP.

## 2. Configure the environment

Copy the project to the server (for example `git clone` your private repository, or `scp`), then:

```bash
cd PathippuAI
cp .env.production.example .env
nano .env
```

Set at least `DOMAIN`, and a long random `SECRET_KEY` (`openssl rand -hex 32`). To translate for real, set
`TRANSLATION_PROVIDER` (`openai` or `claude`) and put your key in `TRANSLATION_API_KEY`.
The `.env` file is private: never commit it, email it or paste it into a chat.

```bash
chmod 600 .env
```

## 3. Build and start

```bash
docker compose build        # first build takes several minutes (downloads Tamil OCR data)
docker compose up -d app
docker compose ps           # app should become "healthy"
```

To include the slower, more accurate "careful" reading method, set `INSTALL_CAREFUL=true` in `.env` before
building, and raise `mem_limit` in `docker-compose.yml` to `5g`.

## 4. Domain and HTTPS

```bash
./deploy/init-https.sh you@example.com
```

This gets a free Let's Encrypt certificate and starts Nginx. Then create your account (there is no public sign-up):

```bash
docker compose exec app python -m scripts.create_user YOUR-NAME
```

Open `https://books.example.com` and sign in.

**Renewing the certificate.** Certificates last 90 days. Add a weekly cron job (`crontab -e`):

```cron
0 4 * * 1 cd /home/YOU/PathippuAI && docker compose run --rm certbot renew --quiet && docker compose exec -T nginx nginx -s reload
```

### Accounts, sign-up and forgotten passwords

- The first account (made with `scripts.create_user`) is the **owner**. Owners see an **Accounts** page.
- Anyone can use **Create an account** on the sign-in page, but the account cannot sign in until an owner approves
  it on the Accounts page. Owners get an email about each new sign-up (when email is set up). Every active account
  can see and change every book, so approve only people you know.
- **Forgot password** emails a one-time link that works for 30 minutes. It needs email settings in `.env`:

  ```env
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_SECURITY=starttls
  SMTP_USERNAME=yourname@gmail.com
  SMTP_PASSWORD=the-16-letter-app-password
  SMTP_FROM=yourname@gmail.com
  ```

  For Gmail, turn on 2-Step Verification and create an **App Password** (Google Account → Security → App
  passwords); your normal Gmail password will not work. Then run `docker compose up -d app`. Links use
  `https://DOMAIN` (or `PUBLIC_URL`). Without email, an owner can still reset a password with
  `docker compose exec app python -m scripts.create_user NAME --reset`.

## 5. Updating

```bash
cd PathippuAI
./deploy/backup.sh                  # always back up first
git pull                            # or copy the new files
docker compose build
docker compose up -d
docker compose ps
```

Database changes are applied automatically on start. Do not update while an OCR, translation or export job is
running: jobs are interrupted (they can be resumed from the page afterwards).

## 6. Backup and restore

What is backed up: the database (accounts, text, corrections, approvals, glossary, translations) and every book's
original PDF and page images. Exported PDFs are not included because they can be made again.

```bash
./deploy/backup.sh                  # writes ./backups/pathippuai-backup-DATE.tar.gz, keeps the last 14
```

Daily automatic backup at 02:00 (`crontab -e`):

```cron
0 2 * * * cd /home/YOU/PathippuAI && ./deploy/backup.sh >> backups/backup.log 2>&1
```

**Copy the backups off the server** (another computer or cloud storage). Backups on the same server do not protect
you if the server is lost. Example from your own computer:

```bash
scp YOU@books.example.com:PathippuAI/backups/pathippuai-backup-*.tar.gz ./my-backups/
```

Backups contain the private manuscript: keep them private.

**Restore** (replaces everything with the backup; the old database is kept as `.before-restore`):

```bash
./deploy/restore.sh backups/pathippuai-backup-20261023-020000.tar.gz
```

On a brand-new server: do steps 1–4, then run the restore command, then sign in with your old account.

## 7. Logs and troubleshooting

```bash
docker compose logs -f app          # application log
docker compose logs -f nginx        # web server log
docker compose ps                   # health of each container
curl -s https://books.example.com/api/health/ready
df -h; free -m                      # disk and memory
```

| Problem | What to check |
|---|---|
| Site does not open | DNS points at the server; ports 80/443 open (`sudo ufw status`); `docker compose ps` |
| Certificate step fails | DNS not ready yet, or port 80 blocked. Fix and run `init-https.sh` again |
| "413 Request Entity Too Large" on upload | Raise `client_max_body_size` in `deploy/nginx/templates/default.conf.template` and `MAX_UPLOAD_MB` |
| App restarts or is "killed" | Out of memory. Add swap, avoid the careful method on small servers, or raise the plan |
| Reading is very slow | Normal for the careful method (about a minute per page). Use "Fast" for a first pass |
| Locked out after wrong passwords | Wait 10 minutes. Forgot the password: `docker compose exec app python -m scripts.create_user NAME --reset` |
| Translation says the key is missing | Set `TRANSLATION_PROVIDER` and `TRANSLATION_API_KEY` in `.env`, then `docker compose up -d app` |
| Disk full | `docker system prune`, delete old backups in `./backups`, check `MIN_FREE_DISK_MB` |

## Security summary

- Passwords are stored as bcrypt hashes; sessions are server-side, HttpOnly, SameSite and `Secure` over HTTPS.
- Changes need a CSRF token and a same-site origin; login is rate-limited by Nginx and locks after repeated failures.
- The app container runs as a normal user with a read-only filesystem and no extra privileges; only `/data` is writable.
- API documentation pages are off in production.
- Keep the server updated: `sudo apt-get update && sudo apt-get upgrade` monthly.

## Manual quality-validation procedure

Do this after the first deployment and after any big update, with a few pages of the real book. Automated tests
cannot judge Tamil reading quality; you can.

1. **Upload** a short PDF (5–10 pages) and confirm the page count and thumbnails are right.
2. **Read pages** with "Fast", then compare 3 pages against the scan: note wrong letters, missing lines, wrong order.
   Correct and approve them; the accuracy meter on the dashboard should update.
3. **Careful method** (if installed): read the same 3 pages and compare. Keep the better one per page.
4. **Chapters and glossary**: mark chapter starts, add 3–5 spiritual terms with their meaning and whether to keep
   them unchanged.
5. **Translate** one chapter into one language. Check that glossary terms were respected, headings are translated,
   and no Tamil remains in a non-Tamil translation. Edit, then approve.
6. **Publish** a sample PDF in that language. Open it and check: fonts display correctly (no empty boxes), the cover
   and contents are right, page numbers match, nothing is cut off.
7. **Security**: sign out and confirm that reloading shows the sign-in page; open `http://` and confirm it redirects
   to `https://`; confirm a wrong password is refused.
8. **Backup**: run `./deploy/backup.sh`, then restore it on a test copy and confirm a book opens.

Record what you checked and the date. If any step fails, do not publish the book yet.
