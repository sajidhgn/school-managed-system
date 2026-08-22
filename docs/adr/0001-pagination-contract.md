# ADR 0001: Hybrid pagination contract

Status: accepted — 2026-08-22

## Decision

EduCloud uses keyset pagination for append-only, high-churn timelines and bounded
offset pagination for operator/catalog and ordinary CRUD lists.

- Tenant audit logs use `before=<created_at>` and a stable descending timestamp
  index. New events cannot shift an older page while an administrator reads it.
- Platform audit logs will migrate to the same cursor before the table exceeds the
  operational threshold of 100,000 rows; until then, its platform-only endpoint is
  capped at 200 rows per request.
- Students, members, schools, roles, plans and platform organizations keep bounded
  page/size (or limit/offset) pagination. These screens require random page access,
  user-selected sorting and small administrative result sets.

This explicitly amends the core spec's blanket cursor requirement. A cursor is not
a universal improvement: a cursor tied to one sort order cannot support arbitrary
column sorting or “go to page N” without a separate search index and cursor format.

## Guardrails

- Every endpoint caps page size at 200.
- No unbounded list response may be added.
- A table must move to keyset pagination when its measured p95 query latency exceeds
  200 ms at production-like volume, or when inserts cause visible page drift.
- Cursor values are opaque at the API boundary whenever more than one sort key is
  needed; the audit timestamp is intentionally the only transparent cursor.
