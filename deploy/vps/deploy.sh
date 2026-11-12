#!/usr/bin/env bash
# Deploy or update SchoolYar on the VPS. Run as root:
#
#   bash /var/www/school-managed-system/deploy/vps/deploy.sh
#
# Pulls main, backs up the database, installs backend dependencies, migrates,
# seeds, restarts the API, builds the frontend and restarts it, checking each
# service answers before moving on. Safe to re-run: every step is idempotent.
#
# SKIP_PULL=1 deploys the checkout as it is (e.g. after checking out an older commit
# to roll back the code).
#
# First-time setup (user, directories, units, nginx, TLS) is in
# docs/operations/deploy-vps.md; this script refuses to run until it is done.

set -euo pipefail

APP_DIR=/var/www/school-managed-system
BACKEND="$APP_DIR/backend"
FRONTEND="$APP_DIR/frontend"
BACKUP_DIR=/root/db-backups
DB_NAME=school_manage_db
KEEP_BACKUPS=14

# uv's own Python 3.13 (Ubuntu 24.04 ships 3.12) lives here, outside /root, so the
# unprivileged `sms` service user can run the virtualenv built on top of it.
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
export UV_COMPILE_BYTECODE=1
export UV_LINK_MODE=copy

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# wait_for URL UNIT: poll until URL answers 2xx/3xx, else show the unit's log.
wait_for() {
  local url=$1 unit=$2
  for _ in $(seq 1 45); do
    if curl -fsS -o /dev/null "$url"; then
      echo "OK  $url"
      return 0
    fi
    sleep 2
  done
  journalctl -u "$unit" -n 40 --no-pager || true
  die "$url did not answer (unit $unit, log above)"
}

# --- Preconditions ------------------------------------------------------------
[[ $EUID -eq 0 ]] || die "run as root"
id sms >/dev/null 2>&1 || die "user 'sms' missing: see docs/operations/deploy-vps.md"
command -v uv >/dev/null || die "uv missing: see docs/operations/deploy-vps.md"
[[ -f "$BACKEND/.env" ]] || die "missing backend/.env (start from deploy/vps/backend.env.example)"
[[ -f "$FRONTEND/.env.production.local" ]] \
  || die "missing frontend/.env.production.local (start from deploy/vps/frontend.env.example)"
if grep -q 'CHANGE_ME' "$BACKEND/.env"; then
  die "backend/.env still contains CHANGE_ME values"
fi
for unit in sms-api sms-web; do
  [[ -f "/etc/systemd/system/$unit.service" ]] || die "$unit.service not installed"
done

# --- Code ---------------------------------------------------------------------
cd "$APP_DIR"
if [[ "${SKIP_PULL:-0}" != "1" ]]; then
  log "Pulling main"
  git pull --ff-only
fi
echo "Deploying $(git log -1 --format='%h %s')"

# --- Database backup ----------------------------------------------------------
log "Backing up $DB_NAME"
install -d -m 700 "$BACKUP_DIR"
backup="$BACKUP_DIR/$DB_NAME-$(date +%Y%m%d-%H%M%S).dump"
( umask 077; sudo -u postgres pg_dump -Fc "$DB_NAME" > "$backup" )
echo "Saved $backup ($(du -h "$backup" | cut -f1))"
# Keep the newest $KEEP_BACKUPS deploy backups.
ls -1t "$BACKUP_DIR/$DB_NAME"-*.dump | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm --

# --- Backend ------------------------------------------------------------------
cd "$BACKEND"
log "Installing backend dependencies"
uv sync --frozen --no-dev

log "Migrating"
.venv/bin/alembic upgrade head

log "Seeding permissions and plans (idempotent)"
.venv/bin/python -m app.cli seed

log "Restarting the API and workers"
systemctl restart sms-api
for unit in sms-book-worker sms-whatsapp-worker; do
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    systemctl restart "$unit"
    echo "restarted $unit"
  fi
done
wait_for http://127.0.0.1:8100/health sms-api

# --- Frontend -----------------------------------------------------------------
# Built after the API is back, because some pages fetch it while prerendering.
# The old web server keeps running meanwhile but may error until the restart
# below, as the build replaces .next under it (about 1-3 minutes).
cd "$FRONTEND"
log "Installing frontend dependencies"
npm ci --no-audit --no-fund

log "Building the frontend"
npm run build

# The standalone server needs the static assets and public/ next to it. Its env
# comes from the systemd unit, so drop any .env copy the build placed there.
cp -R public .next/standalone/
cp -R .next/static .next/standalone/.next/
rm -f .next/standalone/.env*
# The only place the web server writes (image and fetch caches).
install -d -o sms -g sms .next/standalone/.next/cache

log "Restarting the web server"
systemctl restart sms-web
wait_for http://127.0.0.1:3100/ sms-web

log "Deployed $(git -C "$APP_DIR" log -1 --format='%h %s')"
