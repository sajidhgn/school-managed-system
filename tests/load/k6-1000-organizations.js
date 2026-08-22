import http from "k6/http";
import { check } from "k6";
import { SharedArray } from "k6/data";

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:8000/api/v1";
const tokens = new SharedArray("organization tokens", () => {
  const rows = JSON.parse(open(__ENV.ORG_TOKENS_FILE || "./organization-tokens.json"));
  if (!Array.isArray(rows) || rows.length < 1000) {
    throw new Error("ORG_TOKENS_FILE must contain at least 1,000 tenant access tokens");
  }
  return rows;
});

export const options = {
  scenarios: {
    thousand_tenants: {
      executor: "per-vu-iterations",
      vus: 1000,
      iterations: 10,
      maxDuration: "5m",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500", "p(99)<1000"],
    checks: ["rate>0.99"],
  },
};

export default function () {
  const token = tokens[(__VU - 1) % tokens.length].access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const responses = http.batch([
    ["GET", `${baseUrl}/auth/me`, null, { headers }],
    ["GET", `${baseUrl}/org/usage`, null, { headers }],
    ["GET", `${baseUrl}/schools`, null, { headers }],
  ]);
  for (const response of responses) {
    check(response, { "tenant read succeeds": (result) => result.status === 200 });
  }
}
