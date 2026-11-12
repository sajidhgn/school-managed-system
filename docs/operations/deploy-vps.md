# Deploy on the VPS (sms.therawbit.ai)

SchoolYar runs natively on the shared VPS (`ssh rawai-vps`, Ubuntu 24.04), next to
the rawbit apps, using the PostgreSQL 16 and Redis already installed there. Every
file referenced here is in [`deploy/vps/`](../../deploy/vps/).

```
visitor ─▶ Cloudflare ─▶ nginx :443 ─▶ sms-web    Next.js   127.0.0.1:3100   (public)
                                          │ BFF (server-side only)
                                          ▼
                                       sms-api    FastAPI   127.0.0.1:8100   (private)
                                          │
              PostgreSQL 16 127.0.0.1:5432 (school_manage_db) · Redis 127.0.0.1:6379 db 5

sms-book-worker        textbook agent (OpenAI → pgvector)
sms-whatsapp-worker    WhatsApp outbox → WAHA (Docker, 127.0.0.1:3001)   optional
sms-maintenance.timer  daily 07:00 Pakistan time: billing, challans, late fees, retention
```

Everything runs as the unprivileged `sms` user with `TZ=Asia/Karachi`. The code and
the virtualenv are owned by root and read-only to it; it writes only to
`/var/lib/sms/{books,avatars}` and the Next.js cache.

The site is **noindexed**: the API sends `X-Robots-Tag: noindex, nofollow` on every
response, and the frontend (built with `SITE_NOINDEX=true`) adds the same header, a
`noindex` robots meta tag and an empty sitemap.

It runs as `ENVIRONMENT=staging` for now; see [Before production](#before-production).

---

## First-time setup

Everything below runs on the VPS as root: `ssh rawai-vps`.

### 1. System packages, uv, user and folders

```bash
# pgvector: the textbook-library migration runs CREATE EXTENSION vector.
apt update && apt install -y postgresql-16-pgvector

# uv in /usr/local/bin, and Python 3.13 (Ubuntu ships 3.12) somewhere the
# `sms` user can read, not /root.
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
UV_PYTHON_INSTALL_DIR=/opt/uv/python uv python install 3.13

# Service user and the only folders it may write to.
useradd --system --no-create-home --shell /usr/sbin/nologin sms
install -d -o sms -g sms -m 750 /var/lib/sms /var/lib/sms/books /var/lib/sms/avatars
```

### 2. Code and settings

```bash
cd /var/www/school-managed-system
git pull --ff-only

cp deploy/vps/backend.env.example  backend/.env
cp deploy/vps/frontend.env.example frontend/.env.production.local
chgrp sms backend/.env frontend/.env.production.local
chmod 640 backend/.env frontend/.env.production.local

nano backend/.env    # replace every CHANGE_ME
```

Where the `CHANGE_ME` values come from:

| Key | Value |
|---|---|
| `SECRET_KEY`, `WAHA_API_KEY`, `WAHA_WEBHOOK_SECRET` | New random values for this server: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `POSTGRES_PASSWORD`, `MIGRATION_PASSWORD` | The live database's passwords, the ones your Mac uses for `make migrate live=1` (`backend/.env` overlaid by `backend/.env.live`) |
| `SMTP_*`, `EMAIL_FROM_ADDRESS`, `OPENAI_API_KEY`, `SUPERADMIN_*` | Same as your local `backend/.env` (`SUPERADMIN_PASSWORD` at least 16 characters) |

`deploy.sh` refuses to run while any `CHANGE_ME` is left.

### 3. Services

```bash
cp deploy/vps/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable sms-api sms-web sms-book-worker
systemctl enable --now sms-maintenance.timer
```

### 4. WhatsApp (optional)

Skip this if you set `WHATSAPP_BACKEND=null`.

```bash
cd /var/www/school-managed-system
docker compose --env-file backend/.env -f deploy/vps/waha.compose.yml up -d
systemctl enable sms-whatsapp-worker
```

Then link each campus's number from the app's **WhatsApp** page (QR code).

### 5. First deploy

```bash
bash /var/www/school-managed-system/deploy/vps/deploy.sh
```

It backs up the database to `/root/db-backups/`, installs dependencies, applies
every pending migration (the first run brings the live database from `d5f7a9c1e3b5`
up to the newest revision, creating the `vector` extension on the way), seeds
permissions and plans, builds the frontend and starts everything, checking that
each service answers.

### 6. nginx, HTTPS and Cloudflare

```bash
cd /var/www/school-managed-system
cp deploy/vps/nginx/cloudflare-realip.conf /etc/nginx/snippets/
cp deploy/vps/nginx/sms.therawbit.ai.conf  /etc/nginx/sites-available/
ln -s ../sites-available/sms.therawbit.ai.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

certbot --nginx -d sms.therawbit.ai
```

`certbot` adds the HTTPS listener and the HTTP→HTTPS redirect to the same file. If
it fails because of the Cloudflare proxy, set the `sms` DNS record to **DNS only**
(grey cloud), run it again, then turn the proxy back on.

In Cloudflare, set **SSL/TLS → Full (strict)**. *Flexible* would loop between
Cloudflare's HTTP request and nginx's redirect to HTTPS.

### 7. Check

```bash
curl -s 127.0.0.1:8100/health                                # {"status":"ok",...}
curl -sI https://sms.therawbit.ai | grep -i x-robots-tag      # noindex, nofollow
systemctl status sms-api sms-web sms-book-worker --no-pager
systemctl list-timers sms-maintenance.timer
sudo -u postgres psql -d school_manage_db -c 'select version_num from alembic_version'
```

Then sign in at <https://sms.therawbit.ai>.

---

## Updating

Push to `main` from your Mac, then:

```bash
ssh rawai-vps
bash /var/www/school-managed-system/deploy/vps/deploy.sh
```

While the frontend builds (1 to 3 minutes), the old web server keeps running but can
show errors until it restarts.

If a deploy changes something under `deploy/vps/systemd/` or `deploy/vps/nginx/`,
copy that file into place again as in setup steps 3 and 6, then run
`systemctl daemon-reload` or `nginx -t && systemctl reload nginx`.

## Logs and day-to-day commands

```bash
journalctl -u sms-api -f                 # also sms-web, sms-book-worker, sms-whatsapp-worker
journalctl -u sms-maintenance -n 100     # the last daily run
systemctl restart sms-api                # after editing backend/.env
systemctl start sms-maintenance          # run the daily job now

# Any backend CLI command, as the service user:
cd /var/www/school-managed-system/backend
sudo -u sms .venv/bin/python -m app.cli reconcile-usage
sudo -u sms .venv/bin/python -m app.cli mfa-enroll --email admin@example.com
```

Run backend Python through `.venv/bin/...` as above, or through `deploy.sh`. A bare
`uv sync` without `UV_PYTHON_INSTALL_DIR=/opt/uv/python` rebuilds the virtualenv on a
Python under `/root`, which the `sms` user cannot read.

After changing `frontend/.env.production.local`, run `deploy.sh` again: the build
reads it too (`SITE_NOINDEX` in particular).

## Rolling back

A migration cannot be undone by deploying older code: that code does not know the
newer revision, so `alembic upgrade head` fails. Restore the backup taken just
before the bad deploy instead. **Anything written since that backup is lost.**

```bash
systemctl stop sms-web sms-api sms-book-worker sms-whatsapp-worker
ls -1t /root/db-backups/ | head                  # pick the dump from before the bad deploy
sudo -u postgres pg_restore --clean --if-exists -d school_manage_db \
  < /root/db-backups/school_manage_db-YYYYMMDD-HHMMSS.dump

cd /var/www/school-managed-system
git checkout <last-good-commit>
SKIP_PULL=1 bash deploy/vps/deploy.sh
```

Once a fix is on `main`, run `git checkout main` and deploy normally. See also
[backup-restore.md](backup-restore.md).

## Before production

`ENVIRONMENT=production` currently refuses to start, or would reject every request:

1. **Payment gateway.** Production refuses `PAYMENT_GATEWAY=mock`, which approves
   every charge, and no real gateway is implemented yet
   (`backend/app/modules/billing/gateways/`).
2. **Allowed hosts.** Production turns on `TrustedHostMiddleware` with the
   placeholder `["*.example.com"]` (`backend/app/main.py`). The BFF calls the API as
   `127.0.0.1:8100`, so every request would get a 400 until that list is configurable
   and includes `127.0.0.1`.

When going public, also set `SITE_NOINDEX=false` in `frontend/.env.production.local`
and run `deploy.sh`, so search engines can index the marketing pages. The API stays
noindexed regardless.
