#!/usr/bin/env bash
set -euo pipefail

source_db="${POSTGRES_DB:-school_manage_db}"
drill_db="school_manage_restore_drill"
db_host="${POSTGRES_HOST:-localhost}"
db_port="${POSTGRES_PORT:-5432}"
db_user="${MIGRATION_USER:-postgres}"
artifact_dir="${BACKUP_DRILL_DIR:-/tmp/educloud-backup-drill}"
dump_file="${artifact_dir}/educloud.dump"

if [[ "${source_db}" == "${drill_db}" ]]; then
  echo "Refusing: source and restore-drill databases are identical." >&2
  exit 2
fi

mkdir -p "${artifact_dir}"
pg_dump -h "${db_host}" -p "${db_port}" -U "${db_user}" -d "${source_db}" \
  --format=custom --no-owner --file="${dump_file}"

dropdb -h "${db_host}" -p "${db_port}" -U "${db_user}" --if-exists "${drill_db}"
createdb -h "${db_host}" -p "${db_port}" -U "${db_user}" "${drill_db}"
pg_restore -h "${db_host}" -p "${db_port}" -U "${db_user}" -d "${drill_db}" \
  --no-owner --exit-on-error "${dump_file}"

source_counts="$(psql -h "${db_host}" -p "${db_port}" -U "${db_user}" -d "${source_db}" -Atc \
  "SELECT (SELECT count(*) FROM organizations), (SELECT count(*) FROM users), (SELECT count(*) FROM students), (SELECT count(*) FROM audit_logs)")"
restored_counts="$(psql -h "${db_host}" -p "${db_port}" -U "${db_user}" -d "${drill_db}" -Atc \
  "SELECT (SELECT count(*) FROM organizations), (SELECT count(*) FROM users), (SELECT count(*) FROM students), (SELECT count(*) FROM audit_logs)")"

if [[ "${source_counts}" != "${restored_counts}" ]]; then
  echo "Restore verification failed: ${source_counts} != ${restored_counts}" >&2
  exit 1
fi

psql -h "${db_host}" -p "${db_port}" -U "${db_user}" -d "${drill_db}" -v ON_ERROR_STOP=1 \
  -c "SELECT id, organization_id FROM memberships LIMIT 1" >/dev/null

echo "Restore verified. Counts (organizations|users|students|audit_logs): ${restored_counts}"
echo "Recovered database retained for inspection: ${drill_db}"
echo "Dump artifact: ${dump_file}"
