# 1,000-organization load gate

The release profile is [`tests/load/k6-1000-organizations.js`](../../tests/load/k6-1000-organizations.js).
It requires a JSON array containing at least 1,000 objects with an `access_token`
field, one school-scoped or owner token per organization.

```bash
k6 run \
  -e BASE_URL=https://staging.example.com/api/v1 \
  -e ORG_TOKENS_FILE=/secure/staging-organization-tokens.json \
  tests/load/k6-1000-organizations.js
```

Release SLOs:

- HTTP error rate below 1%.
- p95 response time below 500 ms.
- p99 response time below 1 second.
- At least 99% of tenant-read checks succeed.

Tokens are intentionally external test input and must never be committed. The test
hits three RLS-sensitive reads per iteration, so every one of the 1,000 virtual users
executes under a different tenant binding.
