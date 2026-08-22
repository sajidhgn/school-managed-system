# Backup and restore drill

Run [`backend/scripts/backup-restore-drill.sh`](../../backend/scripts/backup-restore-drill.sh)
against a staging snapshot. It creates only the explicit database
`school_manage_restore_drill`, restores a custom-format dump, compares organization,
user, student and audit counts, and executes a relational read.

```bash
cd backend
PGPASSWORD=... MIGRATION_USER=postgres POSTGRES_DB=school_manage_db \
  ./scripts/backup-restore-drill.sh
```

The restored database is retained for manual inspection. After sign-off, remove it
explicitly with `dropdb school_manage_restore_drill`. Record the date, dump size,
restore duration, counts, migration revision and reviewer in the incident/runbook
system. A production release requires a successful staging drill no older than 90
days.

The platform standard is PostgreSQL 16. Both the root Compose stack and CI use the
same major version so a dump is never first tested against a different engine during
an incident.

## Drill record

- Date: 2026-08-22
- Source: local development `school_manage_db`
- Restore target: `school_manage_restore_drill` (retained for inspection)
- Verified counts: 1 organization, 1 user, 0 students, 7 audit rows
- Relational membership read: passed
- Dump: `/tmp/educloud-backup-drill/educloud.dump` (ephemeral local artifact)
