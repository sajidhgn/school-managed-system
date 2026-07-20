#!/usr/bin/env bash
# End-to-end smoke test for the Tenancy + Auth modules against a RUNNING server.
#
# WHY THIS EXISTS
#   The pytest suite covers these flows in-process. This script exercises the same
#   paths over real HTTP against a real PostgreSQL, which is what catches wiring
#   problems the in-process tests cannot see: middleware order, RLS binding on a
#   pooled connection, and the migration/runtime role split.
#
# It reads OTP codes from the server log, so it requires EMAIL_BACKEND=console.
#
# USAGE
#   make dev > /tmp/sms.log 2>&1 &
#   ./scripts/smoke_auth.sh /tmp/sms.log
set -euo pipefail

LOG="${1:?usage: smoke_auth.sh <path-to-server-log>}"
API="${API:-http://127.0.0.1:8000/api/v1}"
STAMP="$(date +%s)"
SCHOOL_EMAIL="contact+${STAMP}@example.edu"
ADMIN_EMAIL="admin+${STAMP}@example.edu"
PASSWORD='StrongPassw0rd!23'

say() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
jqp() { python3 -m json.tool 2>/dev/null || cat; }

# Pull the newest 6-digit code out of the console email backend's log line.
#
# The pretty console renderer wraps values in ANSI colour codes, which sit between
# `subject=` and the opening quote -- so the escapes must be stripped before the
# subject can be matched. Reading the subject specifically (rather than the first
# six digits anywhere on the line) avoids matching a duration or a UUID fragment.
latest_code() {
  sleep 1.2
  sed 's/\x1b\[[0-9;]*m//g' "$LOG" \
    | grep -o "subject='[0-9]\{6\}" | tail -1 | grep -oE '[0-9]{6}'
}

say "1. Register school + first admin"
REG=$(curl -sS -X POST "$API/auth/register" -H 'Content-Type: application/json' -d "{
  \"school_name\":\"Smoke Test School ${STAMP}\",
  \"school_email\":\"${SCHOOL_EMAIL}\",
  \"full_name\":\"Smoke Admin\",
  \"email\":\"${ADMIN_EMAIL}\",
  \"password\":\"${PASSWORD}\"}")
echo "$REG" | jqp
SCHOOL_ID=$(echo "$REG" | python3 -c 'import sys,json;print(json.load(sys.stdin)["school_id"])')

say "2. Verify email with the mailed OTP"
curl -sS -X POST "$API/auth/verify-email" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"code\":\"$(latest_code)\"}" | jqp

say "3. Login must be REFUSED while the school is pending approval"
curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${PASSWORD}\"}" | jqp

say "4. Super admin signs in (role-based 2FA)"
: "${SA_EMAIL:?set SA_EMAIL to an existing super admin}"
: "${SA_PASSWORD:?set SA_PASSWORD}"
curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${SA_EMAIL}\",\"password\":\"${SA_PASSWORD}\"}" | jqp
SA_TOKENS=$(curl -sS -X POST "$API/auth/login/verify-2fa" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${SA_EMAIL}\",\"code\":\"$(latest_code)\"}")
SA_AT=$(echo "$SA_TOKENS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "super admin access token acquired"

say "5. Approve the school"
curl -sS -X POST "$API/schools/${SCHOOL_ID}/approve" -H "Authorization: Bearer ${SA_AT}" | jqp

say "6. School admin signs in (2FA) and reads its own tenant"
curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${PASSWORD}\"}" >/dev/null
AD_TOKENS=$(curl -sS -X POST "$API/auth/login/verify-2fa" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"code\":\"$(latest_code)\"}")
AD_AT=$(echo "$AD_TOKENS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AD_RT=$(echo "$AD_TOKENS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["refresh_token"])')

curl -sS "$API/auth/me" -H "Authorization: Bearer ${AD_AT}" | jqp
curl -sS "$API/schools/current" -H "Authorization: Bearer ${AD_AT}" | jqp

say "7. Tenant admin must NOT reach the super-admin school directory"
curl -sS "$API/schools?page=1&size=5" -H "Authorization: Bearer ${AD_AT}" | jqp

say "8. Refresh rotates the pair; the used refresh token is then revoked"
NEW=$(curl -sS -X POST "$API/auth/refresh" -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"${AD_RT}\"}")
echo "$NEW" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("rotated, expires_in:",d["expires_in"])'
echo "replaying the OLD refresh token (must fail):"
curl -sS -X POST "$API/auth/refresh" -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"${AD_RT}\"}" | jqp

say "9. Logout revokes the current refresh token"
NEW_RT=$(echo "$NEW" | python3 -c 'import sys,json;print(json.load(sys.stdin)["refresh_token"])')
curl -sS -X POST "$API/auth/logout" -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"${NEW_RT}\"}" | jqp

say "SMOKE TEST COMPLETE"
